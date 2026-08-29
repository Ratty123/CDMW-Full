"""Backend preparation for Model Library inline previews."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shlex
import struct
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ElementTree
from collections import defaultdict
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Optional
from urllib.parse import unquote, urlparse

from cdmw.constants import APP_VERSION
from cdmw.core.common import run_process_with_cancellation
from cdmw.core.model_preview_orientation import scene_import_normalizes_texture_v
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.library.models import IMPORTABLE_MODEL_EXTENSIONS
from cdmw.core.archive_modding import (
    attach_scene_preview_textures,
    import_scene_mesh_with_report,
    parsed_mesh_to_preview_model,
)
from cdmw.services.mesh_dotnet_material_state import set_dotnet_preview_texture_flip_vertical
from cdmw.services.model_library_service import ModelLibraryService
from cdmw.modding.scene_import_result_ops import reduce_scene_import_result_quality
from cdmw.models import ModelPreviewRenderSettings, clamp_model_preview_render_settings
from cdmw.rendering.dotnet_preview_package_cache import dotnet_preview_package_cache_budget
from cdmw.rendering.material_channels import resolve_preview_batch_material_channels
from cdmw.rendering.model_preview_prepare import prepare_model_preview
from cdmw.services.mesh_dotnet_preview_package import (
    build_or_lookup_dotnet_preview_package_from_model,
    lookup_dotnet_preview_package_hit_from_model_identity,
)

_DOTNET_INLINE_PREVIEW_MAX_FACES_PER_SUBMESH = 50_000
_DOTNET_INLINE_PREVIEW_MAX_VERTICES_PER_SUBMESH = 80_000
_SUBPROCESS_TIMEOUT_SECONDS = 300
_PREVIEW_PACKAGE_CACHE_MODE = "balanced"
_MODEL_LIBRARY_CACHE_IDENTITY_SCHEMA = 2
_MODEL_LIBRARY_CACHE_SUMMARY_SCHEMA = 1
_GLB_HEADER = struct.Struct("<4sII")
_GLB_CHUNK_HEADER = struct.Struct("<II")
_GLB_JSON_CHUNK = 0x4E4F534A


def _model_library_preview_package_cache_identity(
    source_path: Path,
    import_path: Path,
    *,
    extract_root: Path | None,
    render_settings: object,
    texture_flip_vertical: bool,
    stop_event: threading.Event | None,
) -> str | None:
    """Key a package by every supported source resource and render input."""

    source = Path(source_path).expanduser().resolve()
    resolved = Path(import_path).expanduser().resolve()
    if not source.is_file() or not resolved.is_file():
        return None
    if source.suffix.lower() == ".zip":
        dependency_paths = (source,)
        try:
            selected_member = resolved.relative_to(Path(extract_root).expanduser().resolve()).as_posix()
        except (OSError, ValueError, TypeError):
            selected_member = resolved.name
    else:
        dependency_paths = _model_library_preview_dependency_paths(resolved)
        if dependency_paths is None:
            return None
        selected_member = resolved.name
    revisions = []
    for dependency in dependency_paths:
        revision = _model_library_file_revision(dependency, stop_event=stop_event)
        if revision is None:
            return None
        revisions.append(revision)
    settings_payload = _model_preview_render_settings_payload(render_settings)
    identity_payload = {
        "schema": _MODEL_LIBRARY_CACHE_IDENTITY_SCHEMA,
        "app_version": APP_VERSION,
        "source": str(source),
        "selected_member": selected_member,
        "dependencies": revisions,
        "texture_flip_vertical": bool(texture_flip_vertical),
        "render_settings": settings_payload,
        "cache_profile": _PREVIEW_PACKAGE_CACHE_MODE,
        "face_limit": _DOTNET_INLINE_PREVIEW_MAX_FACES_PER_SUBMESH,
        "vertex_limit": _DOTNET_INLINE_PREVIEW_MAX_VERTICES_PER_SUBMESH,
    }
    encoded = json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "model-library-v2:" + hashlib.sha256(encoded).hexdigest()


def _model_library_file_revision(
    path: Path,
    *,
    stop_event: threading.Event | None,
) -> dict[str, object] | None:
    try:
        resolved = Path(path).expanduser().resolve()
        stat = resolved.stat()
        digest = hashlib.sha256()
        with resolved.open("rb") as stream:
            while True:
                raise_if_cancelled(stop_event)
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError:
        return None
    return {
        "path": str(resolved),
        "mtime_ns": int(stat.st_mtime_ns),
        "size": int(stat.st_size),
        "sha256": digest.hexdigest(),
    }


def _model_library_gltf_document(path: Path) -> Mapping[str, object] | None:
    try:
        if path.suffix.lower() == ".gltf":
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            return payload if isinstance(payload, Mapping) else None
        with path.open("rb") as stream:
            header = stream.read(_GLB_HEADER.size)
            magic, _version, _length = _GLB_HEADER.unpack(header)
            if magic != b"glTF":
                return None
            while True:
                chunk_header = stream.read(_GLB_CHUNK_HEADER.size)
                if not chunk_header:
                    return None
                chunk_length, chunk_type = _GLB_CHUNK_HEADER.unpack(chunk_header)
                chunk = stream.read(chunk_length)
                if len(chunk) != chunk_length:
                    return None
                if chunk_type == _GLB_JSON_CHUNK:
                    payload = json.loads(chunk.rstrip(b"\x00 \t\r\n").decode("utf-8"))
                    return payload if isinstance(payload, Mapping) else None
    except (OSError, ValueError, struct.error, UnicodeDecodeError):
        return None


def _model_library_local_reference(owner: Path, raw_reference: object) -> Path | None:
    text = unquote(str(raw_reference or "").strip().strip('"\''))
    parsed = urlparse(text)
    if not text or parsed.scheme or text.startswith("data:"):
        return None
    try:
        candidate = owner.parent.joinpath(*PurePosixPath(text.replace("\\", "/")).parts).resolve()
    except (OSError, ValueError):
        return None
    return candidate if candidate.is_file() else None


def _model_library_preview_dependency_paths(import_path: Path) -> tuple[Path, ...] | None:
    source = Path(import_path).expanduser().resolve()
    suffix = source.suffix.lower()
    discovered: list[Path] = [source]
    if suffix in {".gltf", ".glb"}:
        document = _model_library_gltf_document(source)
        if document is None:
            return None
        for collection_name in ("buffers", "images"):
            for row in tuple(document.get(collection_name, ()) or ()):
                if not isinstance(row, Mapping) or "uri" not in row:
                    continue
                reference = str(row.get("uri", "") or "")
                if reference.startswith("data:"):
                    continue
                candidate = _model_library_local_reference(source, reference)
                if candidate is None:
                    return None
                discovered.append(candidate)
    elif suffix == ".obj":
        try:
            lines = source.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        except OSError:
            return None
        material_paths = []
        for line in lines:
            if line.lstrip().lower().startswith("mtllib "):
                candidate = _model_library_local_reference(source, line.split(None, 1)[1])
                if candidate is None:
                    return None
                material_paths.append(candidate)
                discovered.append(candidate)
        for material_path in material_paths:
            try:
                material_lines = material_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
            except OSError:
                return None
            for line in material_lines:
                parts = shlex.split(line, comments=True, posix=True)
                if parts and parts[0].lower() in {"map_kd", "map_ks", "map_bump", "bump", "disp", "decal"}:
                    candidate = _model_library_local_reference(material_path, parts[-1])
                    if candidate is None:
                        return None
                    discovered.append(candidate)
    elif suffix == ".dae":
        try:
            root = ElementTree.parse(source).getroot()
        except (OSError, ElementTree.ParseError):
            return None
        for image in root.iter():
            if str(image.tag).rsplit("}", 1)[-1] != "image":
                continue
            for element in image:
                if str(element.tag).rsplit("}", 1)[-1] != "init_from" or not str(element.text or "").strip():
                    continue
                candidate = _model_library_local_reference(source, element.text)
                if candidate is None:
                    return None
                discovered.append(candidate)
    elif suffix not in {".stl", ".ply"}:
        return None
    unique = {str(path).casefold(): path for path in discovered}
    return tuple(unique[key] for key in sorted(unique))


def _model_preview_render_settings_payload(render_settings: object) -> dict[str, object]:
    settings = clamp_model_preview_render_settings(render_settings if isinstance(render_settings, ModelPreviewRenderSettings) else None)
    return {field.name: getattr(settings, field.name) for field in dataclasses.fields(ModelPreviewRenderSettings)}


def _model_preview_render_settings_from_payload(payload: object) -> ModelPreviewRenderSettings:
    if not isinstance(payload, Mapping):
        return ModelPreviewRenderSettings()
    defaults = ModelPreviewRenderSettings()
    values = {
        field.name: payload.get(field.name, getattr(defaults, field.name))
        for field in dataclasses.fields(ModelPreviewRenderSettings)
    }
    return clamp_model_preview_render_settings(ModelPreviewRenderSettings(**values))


def _model_library_preview_worker_command(input_path: Path, output_path: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [
            sys.executable,
            "--model-library-preview-worker",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ]
    return [
        sys.executable,
        str(Path(__file__).resolve().parents[2] / "cdmw_app.py"),
        "--model-library-preview-worker",
        "--input",
        str(input_path),
        "--output",
        str(output_path),
    ]


def _model_library_preview_wire_result(result: Mapping[str, object]) -> dict[str, object]:
    quality_reduction = result.get("quality_reduction")
    if dataclasses.is_dataclass(quality_reduction):
        quality_reduction = dataclasses.asdict(quality_reduction)
    return {
        key: value
        for key, value in result.items()
        if key not in {"preview_model", "prepared_preview", "audit", "quality_reduction"}
    } | {"quality_reduction": quality_reduction}


def model_library_preview_material_channel_summary(prepared_preview: object) -> str:
    batches = tuple(getattr(prepared_preview, "batches", ()) or ())
    if not batches:
        return ""
    channel_counts: dict[str, int] = defaultdict(int)
    unresolved_counts: dict[str, int] = defaultdict(int)
    for batch in batches:
        textures = {
            "base": str(getattr(batch, "preview_texture_path", "") or ""),
            "normal": str(getattr(batch, "preview_normal_texture_path", "") or ""),
            "material": str(getattr(batch, "preview_material_texture_path", "") or ""),
            "height": str(getattr(batch, "preview_height_texture_path", "") or ""),
        }
        dds_textures = {
            "base": {
                "source_path": str(getattr(batch, "preview_texture_dds_path", "") or ""),
                "confidence": "exact",
            },
            "normal": {
                "source_path": str(getattr(batch, "preview_normal_texture_dds_path", "") or ""),
                "confidence": "exact",
            },
            "material": {
                "source_path": str(getattr(batch, "preview_material_texture_dds_path", "") or ""),
                "confidence": "unresolved",
            },
            "height": {
                "source_path": str(getattr(batch, "preview_height_texture_dds_path", "") or ""),
                "confidence": "unresolved",
            },
        }
        payload = {
            "material_name": str(getattr(batch, "material_name", "") or ""),
            "texture_name": str(getattr(batch, "texture_name", "") or ""),
            "textures": {slot: value for slot, value in textures.items() if value},
            "dds_textures": {slot: value for slot, value in dds_textures.items() if str(value.get("source_path", "") or "")},
            "material_contract": {
                "texture_slots": {
                    slot: {
                        "confidence": dds_textures.get(slot, {}).get("confidence", "inferred"),
                        "diagnostic": "Model Library resolved preview texture",
                    }
                    for slot, value in textures.items()
                    if value or str(dds_textures.get(slot, {}).get("source_path", "") or "")
                },
                "packed_channels": tuple(getattr(batch, "preview_material_texture_packed_channels", ()) or ()),
            },
        }
        contract = resolve_preview_batch_material_channels(payload)
        for channel in contract.channels.values():
            channel_counts[channel.sketchfab_channel or channel.channel] += 1
        for unresolved in contract.unresolved:
            slot = str(unresolved.get("slot", "") or "").strip()
            if slot:
                unresolved_counts[slot] += 1
    channel_text = ", ".join(f"{name}:{count}" for name, count in sorted(channel_counts.items())[:8]) or "none"
    unresolved_text = ", ".join(f"{name}:{count}" for name, count in sorted(unresolved_counts.items())[:6])
    return f"{channel_text}; unresolved {unresolved_text}" if unresolved_text else channel_text


def _model_library_cached_preview_result(
    package_path: Path,
    metadata: Mapping[str, object],
    *,
    request_id: int,
    model_name: str,
    source_path: Path,
    import_path: Path,
    renderer_backend: str,
    high_quality_textures: bool,
    lookup_ms: float,
) -> dict[str, object] | None:
    if int(metadata.get("model_library_summary_schema", 0) or 0) != _MODEL_LIBRARY_CACHE_SUMMARY_SCHEMA:
        return None
    raw_summary = metadata.get("model_library_summary")
    if not isinstance(raw_summary, Mapping):
        return None
    summary = dict(raw_summary)
    return {
        "request_id": int(request_id),
        "model_name": model_name,
        "source_path": str(source_path),
        "import_path": str(import_path),
        "renderer_backend": renderer_backend,
        "preview_model": None,
        "prepared_preview": None,
        "dotnet_preview_package_path": str(package_path),
        "dotnet_package_ms": max(0.0, float(lookup_ms)),
        "cache_hit": True,
        "high_quality_textures": bool(high_quality_textures),
        "audit": None,
        "audit_category": "",
        "audit_confidence": 0.0,
        "audit_texture_slots": (),
        "audit_workflows": (),
        "audit_warnings": (),
        "audit_false_positive": False,
        "audit_mixed_model": False,
        **summary,
    }


def prepare_model_library_inline_preview(
    source_path: Path | str,
    *,
    payload: Optional[Mapping[str, object]] = None,
    extract_root: Optional[Path] = None,
    render_settings: object = None,
    renderer_backend: str = "d3d11_vortice_shader",
    model_name: str = "",
    request_id: int = 0,
    high_quality_textures: bool = False,
    progress: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> dict[str, object]:
    """Prepare one canonical .NET/Vortice package for the Model Library preview.

    Model Library previews always use fast preview textures, so
    ``high_quality_textures`` is reported back for telemetry and status text
    rather than selecting a texture tier.
    """

    progress = progress or (lambda _message: None)
    source = Path(source_path)
    metadata = dict(payload or {})
    name = str(model_name or metadata.get("name", "") or source.stem or "model")
    backend = str(renderer_backend or "d3d11_vortice_shader").strip().lower()
    if backend != "d3d11_vortice_shader":
        raise ValueError(f"Unsupported model preview renderer: {backend}")
    raise_if_cancelled(stop_event)
    progress(f"Resolving model preview source: {source}")
    resolved_import_path = ModelLibraryService().resolve_importable_model(
        source,
        extract_root=extract_root,
        stop_event=stop_event,
    )
    if resolved_import_path is None:
        raise ValueError(
            f"{source.suffix or 'This file'} does not contain an importable model: "
            f"{', '.join(sorted(IMPORTABLE_MODEL_EXTENSIONS))}."
        )
    raise_if_cancelled(stop_event)
    texture_flip_vertical = scene_import_normalizes_texture_v(
        resolved_import_path.suffix,
        resolved_import_path,
    )
    if bool(getattr(render_settings, "flip_texture_v", False)):
        texture_flip_vertical = not texture_flip_vertical
    cache_root = Path(tempfile.gettempdir()) / "cdmw_preview_packages"
    cache_max_bytes, cache_target_bytes = dotnet_preview_package_cache_budget(_PREVIEW_PACKAGE_CACHE_MODE)
    cache_identity = _model_library_preview_package_cache_identity(
        source,
        resolved_import_path,
        extract_root=extract_root,
        render_settings=render_settings,
        texture_flip_vertical=texture_flip_vertical,
        stop_event=stop_event,
    )
    if cache_identity is not None:
        lookup_started = time.perf_counter()
        cached_hit = lookup_dotnet_preview_package_hit_from_model_identity(
            cache_root=cache_root,
            archive_identity=cache_identity,
            cancelled=(stop_event.is_set if stop_event is not None else None),
        )
        lookup_ms = max(0.0, (time.perf_counter() - lookup_started) * 1000.0)
        if cached_hit is not None:
            cached_package, cached_metadata = cached_hit
            cached_result = _model_library_cached_preview_result(
                cached_package.package_dir,
                cached_metadata,
                request_id=request_id,
                model_name=name,
                source_path=source,
                import_path=resolved_import_path,
                renderer_backend=backend,
                high_quality_textures=high_quality_textures,
                lookup_ms=lookup_ms,
            )
            if cached_result is not None:
                progress("Loaded a validated durable .NET/Vortice preview package.")
                return cached_result
    raise_if_cancelled(stop_event)
    progress(f"Reading model file: {resolved_import_path}")
    scene_result = import_scene_mesh_with_report(
        resolved_import_path,
        include_external_audit=False,
        stop_event=stop_event,
    )
    raise_if_cancelled(stop_event)
    presentation_mesh = getattr(scene_result.mesh, "_cdmw_presentation_mesh", None)
    if presentation_mesh is not None:
        scene_result.mesh = presentation_mesh
    original_vertices = int(scene_result.mesh.total_vertices)
    original_faces = int(scene_result.mesh.total_faces)
    submeshes = tuple(getattr(scene_result.mesh, "submeshes", ()) or ())
    quality_reduction = None
    max_faces = _DOTNET_INLINE_PREVIEW_MAX_FACES_PER_SUBMESH
    max_vertices = _DOTNET_INLINE_PREVIEW_MAX_VERTICES_PER_SUBMESH
    if any(
        len(getattr(submesh, "faces", ()) or ()) > max_faces
        or len(getattr(submesh, "vertices", ()) or ()) > max_vertices
        for submesh in submeshes
    ):
        progress("Reducing preview mesh density...")
        scene_result, quality_reduction = reduce_scene_import_result_quality(
            scene_result,
            max_faces_per_submesh=max_faces,
            max_vertices_per_submesh=max_vertices,
        )
    raise_if_cancelled(stop_event)
    preview_model = parsed_mesh_to_preview_model(scene_result.mesh)
    texture_count = attach_scene_preview_textures(preview_model, scene_result, resolved_import_path)
    parsed_texture_flip_vertical = scene_import_normalizes_texture_v(
        getattr(scene_result.mesh, "format", ""),
        getattr(scene_result.mesh, "path", "") or resolved_import_path,
    )
    if bool(getattr(render_settings, "flip_texture_v", False)):
        parsed_texture_flip_vertical = not parsed_texture_flip_vertical
    if parsed_texture_flip_vertical != texture_flip_vertical:
        cache_identity = None
        texture_flip_vertical = parsed_texture_flip_vertical
    set_dotnet_preview_texture_flip_vertical(preview_model, texture_flip_vertical)
    raise_if_cancelled(stop_event)
    # Support maps are synthesized once while the canonical package is written,
    # so the preparation-side combiner would only repeat that work.
    prepared_model, prepared_preview = prepare_model_preview(
        preview_model,
        render_settings=render_settings,
        enable_material_combiner=False,
    )
    raise_if_cancelled(stop_event)
    package_started = time.perf_counter()
    progress("Writing canonical .NET/Vortice preview package...")
    material_channel_summary = model_library_preview_material_channel_summary(prepared_preview)
    audit = getattr(scene_result, "external_audit", None)
    quality_reduction_payload = (
        dataclasses.asdict(quality_reduction)
        if dataclasses.is_dataclass(quality_reduction)
        else quality_reduction
    )
    summary_metadata = {
        "source_vertices": original_vertices,
        "source_faces": original_faces,
        "vertices": int(scene_result.mesh.total_vertices),
        "faces": int(scene_result.mesh.total_faces),
        "quality_reduction": quality_reduction_payload,
        "meshes": len(getattr(preview_model, "meshes", ()) or ()),
        "textures": int(texture_count),
        "texture_flip_vertical": bool(texture_flip_vertical),
        "material_channel_summary": material_channel_summary,
        "diagnostics": tuple(scene_result.diagnostics or ()),
        "audit_category": str(getattr(audit, "verified_category", "") or ""),
        "audit_confidence": float(getattr(audit, "confidence", 0.0) or 0.0),
        "audit_texture_slots": tuple(getattr(audit, "texture_slots", ()) or ()),
        "audit_workflows": tuple(getattr(audit, "pbr_workflows", ()) or ()),
        "audit_warnings": tuple(getattr(audit, "warnings", ()) or ()),
        "audit_false_positive": bool(getattr(audit, "false_positive", False)),
        "audit_mixed_model": bool(getattr(audit, "mixed_model", False)),
    }
    effective_cache_mode = _PREVIEW_PACKAGE_CACHE_MODE if cache_identity is not None else "off"
    package_dir = str(
        build_or_lookup_dotnet_preview_package_from_model(
            prepared_model,
            cache_root=cache_root,
            archive_identity=cache_identity or f"model-library-uncached:{resolved_import_path}",
            cache_mode=effective_cache_mode,
            max_bytes=cache_max_bytes,
            target_bytes=cache_target_bytes,
            cancelled=(stop_event.is_set if stop_event is not None else None),
            metadata={
                "surface": "model_library",
                "source_path": str(resolved_import_path),
                "model_library_summary_schema": _MODEL_LIBRARY_CACHE_SUMMARY_SCHEMA,
                "model_library_summary": summary_metadata,
            },
        ).package_dir
    )
    package_ms = max(0.0, (time.perf_counter() - package_started) * 1000.0)
    raise_if_cancelled(stop_event)
    return {
        "request_id": int(request_id),
        "model_name": name,
        "source_path": str(source),
        "import_path": str(resolved_import_path),
        "renderer_backend": backend,
        "preview_model": prepared_model,
        "prepared_preview": prepared_preview,
        "dotnet_preview_package_path": package_dir,
        "dotnet_package_ms": package_ms,
        "source_vertices": original_vertices,
        "source_faces": original_faces,
        "vertices": int(scene_result.mesh.total_vertices),
        "faces": int(scene_result.mesh.total_faces),
        "quality_reduction": quality_reduction,
        "meshes": len(getattr(preview_model, "meshes", ()) or ()),
        "textures": int(texture_count),
        "texture_flip_vertical": bool(texture_flip_vertical),
        "high_quality_textures": bool(high_quality_textures),
        "material_channel_summary": material_channel_summary,
        "diagnostics": tuple(scene_result.diagnostics or ()),
        "audit": audit,
        "audit_category": str(getattr(audit, "verified_category", "") or ""),
        "audit_confidence": float(getattr(audit, "confidence", 0.0) or 0.0),
        "audit_texture_slots": tuple(getattr(audit, "texture_slots", ()) or ()),
        "audit_workflows": tuple(getattr(audit, "pbr_workflows", ()) or ()),
        "audit_warnings": tuple(getattr(audit, "warnings", ()) or ()),
        "audit_false_positive": bool(getattr(audit, "false_positive", False)),
        "audit_mixed_model": bool(getattr(audit, "mixed_model", False)),
    }


def prepare_model_library_inline_preview_in_subprocess(
    source_path: Path | str,
    *,
    payload: Optional[Mapping[str, object]] = None,
    extract_root: Optional[Path] = None,
    render_settings: object = None,
    renderer_backend: str = "d3d11_vortice_shader",
    model_name: str = "",
    request_id: int = 0,
    high_quality_textures: bool = False,
    progress: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> dict[str, object]:
    progress = progress or (lambda _message: None)
    progress("Preparing preview in isolated worker...")
    with TemporaryDirectory(prefix="cdmw_model_preview_worker_") as temp_dir:
        root = Path(temp_dir)
        input_path = root / "request.json"
        output_path = root / "result.json"
        input_path.write_text(
            json.dumps(
                {
                    "source_path": str(Path(source_path)),
                    "payload": dict(payload or {}),
                    "extract_root": str(extract_root) if extract_root is not None else "",
                    "render_settings": _model_preview_render_settings_payload(render_settings),
                    "renderer_backend": str(renderer_backend or "d3d11_vortice_shader"),
                    "model_name": str(model_name or ""),
                    "request_id": int(request_id),
                    "high_quality_textures": bool(high_quality_textures),
                }
            ),
            encoding="utf-8",
        )
        returncode, stdout, stderr = run_process_with_cancellation(
            _model_library_preview_worker_command(input_path, output_path),
            timeout_seconds=_SUBPROCESS_TIMEOUT_SECONDS,
            stop_event=stop_event,
            timeout_warning_interval_seconds=15.0,
            on_timeout_warning=lambda elapsed: progress(
                f"Still preparing preview in isolated worker ({elapsed:.0f}s)..."
            ),
        )
        if returncode != 0:
            message = (stderr or stdout or "").strip()
            raise RuntimeError(message[-1200:] or f"Model preview worker failed with exit code {returncode}.")
        if not output_path.is_file():
            raise RuntimeError("Model preview worker did not write a result.")
        result = json.loads(output_path.read_text(encoding="utf-8"))
        if not isinstance(result, dict):
            raise RuntimeError("Model preview worker wrote an invalid result.")
        return result


def run_model_library_preview_worker(input_path: Path, output_path: Path) -> int:
    request = json.loads(Path(input_path).read_text(encoding="utf-8"))
    if not isinstance(request, dict):
        raise ValueError("Model preview worker request must be a JSON object.")
    result = prepare_model_library_inline_preview(
        request.get("source_path", ""),
        payload=request.get("payload") if isinstance(request.get("payload"), dict) else None,
        extract_root=Path(str(request.get("extract_root", ""))) if str(request.get("extract_root", "") or "").strip() else None,
        render_settings=_model_preview_render_settings_from_payload(request.get("render_settings")),
        renderer_backend=str(request.get("renderer_backend", "d3d11_vortice_shader") or "d3d11_vortice_shader"),
        model_name=str(request.get("model_name", "") or ""),
        request_id=int(request.get("request_id", 0) or 0),
        high_quality_textures=bool(request.get("high_quality_textures", False)),
    )
    Path(output_path).write_text(json.dumps(_model_library_preview_wire_result(result)), encoding="utf-8")
    return 0


__all__ = [
    "model_library_preview_material_channel_summary",
    "prepare_model_library_inline_preview",
    "prepare_model_library_inline_preview_in_subprocess",
    "run_model_library_preview_worker",
]
