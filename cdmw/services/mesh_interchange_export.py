"""Snapshot-based mesh interchange export shared by the editor and legacy workers."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from cdmw.core.atomic_file import atomic_copy_file, atomic_publish_files, atomic_write_bytes, atomic_write_text
from cdmw.models import RunCancelled
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.modding.mesh_exporter import export_obj, export_fbx
from cdmw.modding.mesh_glb_interchange import export_glb, import_glb_with_sidecar
from cdmw.modding.mesh_obj_importer import import_obj
from cdmw.services.mesh_service_state import MeshExportSnapshot, MeshExportTextureSnapshot
from cdmw.services.mesh_export_readback import readback_editable_package_metadata
from cdmw.services.mesh_export_support import artifact_row as _artifact_row, texture_artifact_name as _texture_artifact_name

_BASE_TEXTURE_CHANNELS = frozenset({"base", "base_color", "albedo", "diffuse"})

def _raise_export_cancelled(stop_event: threading.Event) -> None:
    if stop_event.is_set():
        raise RunCancelled("Mesh export cancelled.")


def _wait_for_texture_updates(
    waiter: Callable[[float], bool] | None,
    stop_event: threading.Event,
) -> None:
    _raise_export_cancelled(stop_event)
    if waiter is None:
        return
    deadline = time.monotonic() + 5.0
    while True:
        _raise_export_cancelled(stop_event)
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            raise RuntimeError("resident texture updates did not become idle before export")
        if waiter(min(0.05, remaining)):
            return


def _encode_bgra_snapshot_dds(
    resource: MeshExportTextureSnapshot,
    target: Path,
    stop_event: threading.Event,
) -> None:
    from PIL import Image

    from cdmw.core import texture_native
    from cdmw.domain.textures.editor_presets import resolve_texture_editor_dds_preset

    if not resource.bgra_data or resource.width <= 0 or resource.height <= 0:
        raise ValueError(f"resident texture snapshot is incomplete: {resource.resource_id}")
    expected = int(resource.row_pitch) * int(resource.height)
    if resource.row_pitch != resource.width * 4 or len(resource.bgra_data) != expected:
        raise ValueError(f"resident texture snapshot has an invalid BGRA8 layout: {resource.resource_id}")
    if texture_native.find_directxtex_texture_binary() is None:
        raise RuntimeError("Native DirectXTex texture backend cd-texture-dx is missing.")
    target.parent.mkdir(parents=True, exist_ok=True)
    png_path = target.with_suffix(".source.png")
    try:
        Image.frombytes(
            "RGBA",
            (int(resource.width), int(resource.height)),
            resource.bgra_data,
            "raw",
            "BGRA",
        ).save(png_path, format="PNG")
        # A painted normal or mask is data, not colour: encode it with its own
        # channel's preset, and read the pixels as the material role says.
        from cdmw.services.material_authority_resource_service import _channel_preset_key
        channel = str(resource.channel or "").strip().lower()
        preset = resolve_texture_editor_dds_preset(
            "base_color" if not channel or channel in _BASE_TEXTURE_CHANNELS else _channel_preset_key(channel),
            width=int(resource.width),
            height=int(resource.height),
        )
        report = texture_native.encode_dds_with_directxtex(
            png_path,
            target,
            dds_format=preset.dds_format,
            width=int(resource.width),
            height=int(resource.height),
            mip_count=preset.mip_count,
            overwrite=True,
            source_color_policy="assume_srgb" if preset.dds_format.endswith("_SRGB") else "ignore_srgb_metadata",
            timeout_seconds=60.0,
            stop_event=stop_event,
        )
        if not report or not target.is_file():
            raise RuntimeError(f"Native DDS export failed for resident texture {resource.resource_id}.")
    finally:
        png_path.unlink(missing_ok=True)


def _stage_export_textures(
    snapshot: MeshExportSnapshot,
    staging_dir: Path,
    stop_event: threading.Event,
    *,
    relative_root: Path = Path("textures"),
) -> tuple[dict[str, object], ...]:
    from cdmw.core.dds_native import inspect_dds_native_path

    rows: list[dict[str, object]] = []
    for resource in snapshot.texture_resources:
        _raise_export_cancelled(stop_event)
        target = staging_dir / relative_root / _texture_artifact_name(resource)
        if resource.dds_data:
            atomic_write_bytes(target, resource.dds_data)
        else:
            _encode_bgra_snapshot_dds(resource, target, stop_event)
        info = inspect_dds_native_path(target)
        if info.width <= 0 or info.height <= 0 or info.mip_count <= 0 or info.reason:
            raise RuntimeError(
                f"resident texture DDS readback failed for {resource.resource_id}: "
                f"{info.reason or 'invalid dimensions or mip count'}"
            )
        rows.append(
            _artifact_row(
                target,
                staging_dir,
                "texture_dds",
                resource_id=resource.resource_id,
                channel=resource.channel,
                revision=int(resource.revision),
                logical_path=resource.logical_path,
                readback={
                    "status": "passed",
                    "format": info.format_name,
                    "width": int(info.width),
                    "height": int(info.height),
                    "mip_count": int(info.mip_count),
                    "reason": info.reason,
                },
            )
        )
    return tuple(rows)


def _apply_export_texture_bindings(
    snapshot: MeshExportSnapshot,
    texture_rows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    paths = {
        (str(row.get("resource_id") or ""), str(row.get("channel") or "")): str(row.get("path") or "")
        for row in texture_rows
    }
    submeshes = tuple(snapshot.mesh.submeshes or ())
    bindings: list[dict[str, object]] = []
    for submesh_index, submesh in enumerate(submeshes):
        current_texture = _normalized_texture_binding_path(getattr(submesh, "texture", ""))
        candidates = [
            resource
            for resource in snapshot.texture_resources
            if (not resource.affected_submeshes or submesh_index in resource.affected_submeshes)
            and paths.get((resource.resource_id, resource.channel))
        ]
        groups: dict[str, list[MeshExportTextureSnapshot]] = {}
        for resource in candidates:
            semantic = "base" if resource.channel in _BASE_TEXTURE_CHANNELS else resource.channel
            groups.setdefault(semantic, []).append(resource)
        for semantic in sorted(groups):
            resource = max(
                groups[semantic],
                key=lambda item: (
                    bool(current_texture and _normalized_texture_binding_path(item.logical_path) == current_texture),
                    bool(item.bgra_data),
                    int(item.revision),
                    item.resource_id,
                ),
            )
            relative_path = paths[(resource.resource_id, resource.channel)]
            from cdmw.modding.mesh_interchange_materials import interchange_material
            submesh.interchange_material = interchange_material(submesh)
            slots = submesh.interchange_material.setdefault("textures", {})
            key = {"base": "baseColorTexture", "normal": "normalTexture", "material": "metallicRoughnessTexture",
                   "emissive": "emissiveTexture", "roughness": "roughnessTexture", "metallic": "metallicTexture",
                   "occlusion": "occlusionTexture"}.get(semantic)
            if key:
                info = dict(slots.get(key, {}), path=relative_path)
                info.pop("missing", None)
                slots[key] = info
            if semantic == "base":
                submesh.texture = relative_path
            bindings.append(
                {
                    "submesh_index": submesh_index,
                    "resource_id": resource.resource_id,
                    "channel": resource.channel,
                    "revision": int(resource.revision),
                    "path": relative_path,
                }
            )
    return tuple(bindings)


def _normalized_texture_binding_path(value: object) -> str:
    text = str(value or "").strip()
    return os.path.normcase(os.path.abspath(os.path.normpath(text))) if text else ""


def _package_reparse_report(
    staging_dir: Path,
    name: str,
    source_mesh: ParsedMesh,
    texture_rows: Sequence[Mapping[str, object]] = (),
    texture_bindings: Sequence[Mapping[str, object]] = (),
    *,
    formats: tuple[str, ...] = ("glb", "obj", "fbx"),
) -> dict[str, object]:
    metadata_readback = readback_editable_package_metadata(staging_dir, name, source_mesh, formats=formats)
    counts = {}
    if "glb" in formats:
        counts["glb_submesh_count"] = len(import_glb_with_sidecar(staging_dir / f"{name}.glb").submeshes)
    if "obj" in formats:
        counts["obj_submesh_count"] = len(import_obj(str(staging_dir / f"{name}.obj")).submeshes)
    if "fbx" in formats:
        with (staging_dir / f"{name}.fbx").open("rb") as handle:
            if handle.read(23) != b"Kaydara FBX Binary  \x00\x1a\x00":
                raise RuntimeError("Exported FBX has an invalid binary header.")
        counts["fbx_readback"] = "binary_header_and_companion_only"
    mtl_path = staging_dir / f"{name}.mtl"
    mtl_text = mtl_path.read_text(encoding="utf-8", errors="replace") if "obj" in formats else ""
    sidecar_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in staging_dir.glob("*.meta.json")
    )
    for binding in texture_bindings:
        relative_path = str(binding.get("path") or "")
        channel = str(binding.get("channel") or "").strip().lower()
        if relative_path not in sidecar_text:
            raise RuntimeError(f"exported texture binding did not resolve in its sidecar/MTL contract: {relative_path}")
        if "obj" in formats and channel in _BASE_TEXTURE_CHANNELS and relative_path not in mtl_text:
            # Portable PNG/material-factor copies replace the DDS map in MTL.
            # Its authored source must still match the staged binding, and its
            # actual published diffuse image must be readable.
            from cdmw.modding.mesh_obj_importer import _load_obj_material_texture_map
            references = _load_obj_material_texture_map(str(staging_dir / f"{name}.obj"))
            if not references or not all((staging_dir / reference).is_file() for reference in references.values()):
                raise RuntimeError(f"portable OBJ diffuse texture is missing: {relative_path}")
    return {
        "status": "passed",
        **counts,
        "dds_readback": [dict(row.get("readback") or {}) for row in texture_rows],
        "texture_bindings": [dict(binding) for binding in texture_bindings],
        "interchange_reports": [json.loads(path.read_text(encoding="utf-8")).get("interchange_report", {})
                                for path in staging_dir.glob("*.meta.json")],
        **metadata_readback,
    }


def _package_artifact_rows(
    staging_dir: Path,
    texture_rows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    rows = [dict(row) for row in texture_rows]
    known = {str(row.get("path") or "") for row in rows}
    for path in sorted(staging_dir.rglob("*"), key=lambda item: item.as_posix().casefold()):
        relative = path.relative_to(staging_dir).as_posix()
        if not path.is_file() or relative in known or path.name == "mesh_export_report.json":
            continue
        suffix = path.suffix.lower()
        role = {
            ".glb": "mesh_glb",
            ".obj": "mesh_obj",
            ".fbx": "mesh_fbx",
            ".mtl": "mesh_material",
        }.get(suffix, "mesh_metadata" if suffix in {".json", ".txt"} else "mesh_artifact")
        rows.append(_artifact_row(path, staging_dir, role))
    return tuple(rows)


def export_editable_mesh(
    service,
    session_id: str,
    output_dir: Path | str,
    *,
    name: str = "mesh",
    formats: tuple[str, ...] = ("glb", "obj", "fbx"),
    expected_mesh_revision: int | None = None,
    texture_updates_waiter: Callable[[float], bool] | None = None,
    stop_event: threading.Event | None = None,
) -> dict[str, object]:
    """Export one coherent session snapshot, publishing only complete files.

    The retained package worker uses all three formats. The current editor
    supplies one format and the user's filename; no other writer is invoked.
    """
    if not formats or len(set(formats)) != len(formats) or set(formats) - {"glb", "fbx", "obj"}:
        raise ValueError("Mesh export supports GLB, FBX and OBJ.")
    if not name or name in {".", ".."} or any(c in name for c in '/\\'):
        raise ValueError("Mesh export requires a filename without directory components.")
    stop_event = stop_event if stop_event is not None else threading.Event()
    output_dir = Path(output_dir)
    _wait_for_texture_updates(texture_updates_waiter, stop_event)
    snapshot = service.capture_export_snapshot(
        session_id, stop_event=stop_event, expected_mesh_revision=expected_mesh_revision,
    )
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output_dir.name}.export-", dir=output_dir.parent) as temporary:
        staging_dir = Path(temporary)
        texture_rows = _stage_export_textures(snapshot, staging_dir, stop_event,
            relative_root=Path(f"{name}_textures") if len(formats) == 1 else Path("textures"))
        texture_bindings = _apply_export_texture_bindings(snapshot, texture_rows)
        snapshot_payload = service.export_snapshot_report(snapshot)
        snapshot_payload["resolved_texture_bindings"] = list(texture_bindings)
        for format_name in formats:
            _raise_export_cancelled(stop_event)
            if format_name == "fbx":
                export_fbx(snapshot.mesh, str(staging_dir), name)
            else:
                writer = export_glb if format_name == "glb" else export_obj
                writer(snapshot.mesh, str(staging_dir), name,
                       extra_payload={"export_snapshot": snapshot_payload})
        primary = staging_dir / f"{name}.{formats[0]}"
        metadata = Path(f"{primary}.meta.json")
        if len(formats) > 1:
            metadata = staging_dir / "mesh.cdmeta.json"
            atomic_copy_file(Path(f"{primary}.meta.json"), metadata)
            payload = json.loads(metadata.read_text(encoding="utf-8"))
            atomic_write_text(staging_dir / "original_asset_hash.txt", str(payload.get("source_asset_hash", "") or ""))
        _raise_export_cancelled(stop_event)
        reparse = _package_reparse_report(staging_dir, name, snapshot.mesh, texture_rows,
                                         texture_bindings, formats=formats)
        artifact_rows = _package_artifact_rows(staging_dir, texture_rows)
        snapshot_payload = service.export_snapshot_report(snapshot, artifacts=artifact_rows, output_reparse=reparse)
        snapshot_payload["resolved_texture_bindings"] = list(texture_bindings)
        report_name = "mesh_export_report.json" if len(formats) > 1 else f"{name}.{formats[0]}.export.json"
        atomic_write_text(staging_dir / report_name, json.dumps(snapshot_payload, indent=2) + "\n")
        _raise_export_cancelled(stop_event)
        staged_files = tuple(path for path in staging_dir.rglob("*") if path.is_file())
        # Cancellation stops before publication. Atomic publication either
        # succeeds completely or restores existing outputs.
        atomic_publish_files({path: output_dir / path.relative_to(staging_dir) for path in staged_files})
        result = {
            "package_dir": output_dir,
            "mesh_path": output_dir / primary.name,
            "metadata_path": output_dir / metadata.name,
            "files": tuple(output_dir / path.relative_to(staging_dir) for path in staged_files),
            "report_path": output_dir / report_name,
            "export_snapshot": snapshot_payload,
            "artifacts": artifact_rows,
        }
        for format_name in formats:
            result[f"{format_name}_path"] = output_dir / f"{name}.{format_name}"
        if len(formats) > 1:
            result["original_asset_hash_path"] = output_dir / "original_asset_hash.txt"
        return result
