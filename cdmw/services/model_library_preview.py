"""Backend preparation for Model Library inline previews."""

from __future__ import annotations

import dataclasses
import json
import sys
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional

from cdmw.core.common import raise_if_cancelled, run_process_with_cancellation
from cdmw.core.archive_modding import (
    attach_scene_preview_textures,
    import_scene_mesh_with_report,
    parsed_mesh_to_preview_model,
)
from cdmw.core.model_catalogue import IMPORTABLE_MODEL_EXTENSIONS, resolve_importable_model_path
from cdmw.modding.scene_import_result_ops import reduce_scene_import_result_quality
from cdmw.models import ModelPreviewRenderSettings, clamp_model_preview_render_settings
from cdmw.rendering.material_channels import resolve_preview_batch_material_channels
from cdmw.rendering.model_preview_prepare import prepare_model_preview
from cdmw.rendering.native_preview_package import write_isolated_d3d11_preview_package

_INLINE_PREVIEW_MAX_FACES_PER_SUBMESH = 500
_INLINE_PREVIEW_MAX_VERTICES_PER_SUBMESH = 1200
_NATIVE_INLINE_PREVIEW_MAX_FACES_PER_SUBMESH = 50_000
_NATIVE_INLINE_PREVIEW_MAX_VERTICES_PER_SUBMESH = 80_000
_SUBPROCESS_TIMEOUT_SECONDS = 300


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


def prepare_model_library_inline_preview(
    source_path: Path | str,
    *,
    payload: Optional[Mapping[str, object]] = None,
    extract_root: Optional[Path] = None,
    render_settings: object = None,
    renderer_backend: str = "native_d3d11",
    model_name: str = "",
    request_id: int = 0,
    high_quality_textures: bool = False,
    progress: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> dict[str, object]:
    progress = progress or (lambda _message: None)
    source = Path(source_path)
    metadata = dict(payload or {})
    name = str(model_name or metadata.get("name", "") or source.stem or "model")
    backend = str(renderer_backend or "native_d3d11").strip().lower()
    raise_if_cancelled(stop_event)
    progress(f"Resolving model preview source: {source}")
    resolved_import_path = resolve_importable_model_path(source, extract_root=extract_root)
    if resolved_import_path is None:
        raise ValueError(
            f"{source.suffix or 'This file'} does not contain an importable model: "
            f"{', '.join(sorted(IMPORTABLE_MODEL_EXTENSIONS))}."
        )
    raise_if_cancelled(stop_event)
    progress(f"Reading model file: {resolved_import_path}")
    scene_result = import_scene_mesh_with_report(resolved_import_path, include_external_audit=False)
    raise_if_cancelled(stop_event)
    original_vertices = int(scene_result.mesh.total_vertices)
    original_faces = int(scene_result.mesh.total_faces)
    submeshes = tuple(getattr(scene_result.mesh, "submeshes", ()) or ())
    quality_reduction = None
    max_faces = _INLINE_PREVIEW_MAX_FACES_PER_SUBMESH
    max_vertices = _INLINE_PREVIEW_MAX_VERTICES_PER_SUBMESH
    if backend == "native_d3d11" and bool(high_quality_textures):
        max_faces = _NATIVE_INLINE_PREVIEW_MAX_FACES_PER_SUBMESH
        max_vertices = _NATIVE_INLINE_PREVIEW_MAX_VERTICES_PER_SUBMESH
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
    raise_if_cancelled(stop_event)
    prepared_model, prepared_preview = prepare_model_preview(
        preview_model,
        render_settings=render_settings,
        enable_material_combiner=True,
    )
    raise_if_cancelled(stop_event)
    package_dir = ""
    package_ms = 0.0
    if backend == "native_d3d11":
        package_started = time.perf_counter()
        progress("Writing native D3D11 preview package...")
        package_dir = str(
            write_isolated_d3d11_preview_package(
                prepared_model,
                prepared_preview,
                render_settings=render_settings,
                use_textures=True,
                high_quality_textures=bool(high_quality_textures),
                backend="d3d11",
                enable_material_combiner=True,
                prefer_direct_dds=True,
                editor_workspace="model_library",
                on_progress=lambda _current, _total, message: progress(message),
            )
        )
        package_ms = max(0.0, (time.perf_counter() - package_started) * 1000.0)
    raise_if_cancelled(stop_event)
    audit = getattr(scene_result, "external_audit", None)
    return {
        "request_id": int(request_id),
        "model_name": name,
        "source_path": str(source),
        "import_path": str(resolved_import_path),
        "renderer_backend": backend,
        "preview_model": prepared_model,
        "prepared_preview": prepared_preview,
        "d3d11_package_dir": package_dir,
        "d3d11_package_ms": package_ms,
        "source_vertices": original_vertices,
        "source_faces": original_faces,
        "vertices": int(scene_result.mesh.total_vertices),
        "faces": int(scene_result.mesh.total_faces),
        "quality_reduction": quality_reduction,
        "meshes": len(getattr(preview_model, "meshes", ()) or ()),
        "textures": int(texture_count),
        "material_channel_summary": model_library_preview_material_channel_summary(prepared_preview),
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
    renderer_backend: str = "native_d3d11",
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
                    "renderer_backend": str(renderer_backend or "native_d3d11"),
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
        renderer_backend=str(request.get("renderer_backend", "native_d3d11") or "native_d3d11"),
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
