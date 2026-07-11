"""Resident .NET material-state snapshots; no package or renderer ownership."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from cdmw.modding.mesh_parser import ParsedMesh


def _safe_int(value: object, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _dotnet_material_input_channels(source: object | None) -> dict[str, str]:
    result: dict[str, str] = {}
    if source is None:
        return result
    for item in tuple(getattr(source, "preview_material_texture_inputs", ()) or ()):
        values = item if isinstance(item, Mapping) else vars(item) if hasattr(item, "__dict__") else {}
        semantic = str(
            values.get("semantic_type", "")
            or values.get("slot_kind", "")
            or getattr(item, "semantic_type", "")
            or getattr(item, "slot_kind", "")
            or ""
        ).strip().lower()
        candidates = tuple(
            str(values.get(name, "") or getattr(item, name, "") or "").strip()
            for name in ("preview_texture_path", "source_path", "source_dds_path", "source_texture_path")
        )
        path = next((value for value in candidates if value and Path(value).expanduser().is_file()), "")
        if not path:
            path = next((value for value in candidates if value), "")
        if semantic and path and semantic not in result:
            result[semantic] = path
    return result


def _dotnet_resolved_texture_channels(source: object | None) -> dict[str, str]:
    if source is None:
        return {}
    texture = str(getattr(source, "texture", "") or "").strip()
    result = ({channel: texture for channel in ("base", "albedo", "diffuse")} if texture else {})
    result.update(_dotnet_material_input_channels(source))
    pairs = {
        "base": ("preview_texture_path", "preview_texture_dds_path", "preview_base_texture_default_path"),
        "albedo": ("preview_texture_path", "preview_texture_dds_path", "preview_base_texture_default_path"),
        "diffuse": ("preview_texture_path", "preview_texture_dds_path", "preview_base_texture_default_path"),
        "normal": ("preview_normal_texture_path", "preview_normal_texture_dds_path", "preview_normal_texture_default_path"),
        "material": ("preview_material_texture_path", "preview_material_texture_dds_path", "preview_material_texture_default_path"),
        "specular": ("preview_material_texture_path", "preview_material_texture_dds_path", "preview_material_texture_default_path"),
        "roughness": ("preview_material_texture_path", "preview_material_texture_dds_path", "preview_material_texture_default_path"),
        "metallic": ("preview_material_texture_path", "preview_material_texture_dds_path", "preview_material_texture_default_path"),
        "height": ("preview_height_texture_path", "preview_height_texture_dds_path", "preview_height_texture_default_path"),
        "emissive": ("preview_emissive_texture_path", "preview_emissive_texture_dds_path", "preview_emissive_texture_default_path"),
    }
    for channel, attrs in pairs.items():
        for attr in attrs:
            value = str(getattr(source, attr, "") or "").strip()
            if value:
                result[channel] = value
                break
    return result


def _source_file_stat_key(source: Path) -> str:
    resolved = source.resolve()
    stat = source.stat()
    return f"{resolved}|size:{stat.st_size}|mtime:{stat.st_mtime_ns}".casefold()


def mesh_dotnet_material_input_signature(mesh: ParsedMesh) -> str:
    rows: list[dict[str, object]] = []
    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        channels: list[tuple[str, str]] = []
        for channel, value in sorted(_dotnet_resolved_texture_channels(submesh).items()):
            raw_path = str(value or "").strip()
            source = Path(raw_path).expanduser()
            try:
                identity = _source_file_stat_key(source) if source.is_file() else raw_path
            except OSError:
                identity = raw_path
            channels.append((channel, identity))
        rows.append(
            {
                "material": str(getattr(submesh, "material", "") or ""),
                "texture": str(getattr(submesh, "texture", "") or ""),
                "channels": channels,
            }
        )
    payload = json.dumps(rows, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _dotnet_material_resource(raw_path: str) -> tuple[str, str]:
    source = Path(raw_path).expanduser()
    try:
        resolved = source.resolve()
        stat = resolved.stat()
        normalized_path = resolved.as_posix()
        identity = f"{normalized_path.casefold()}|size:{stat.st_size}|mtime_ns:{stat.st_mtime_ns}"
    except OSError:
        normalized_path = os.path.normpath(raw_path).replace("\\", "/")
        identity = f"raw:{normalized_path.casefold()}"
    return normalized_path, hashlib.sha256(identity.encode("utf-8")).hexdigest()


def mesh_dotnet_texture_resource_id(raw_path: str | Path) -> str:
    _normalized_path, fingerprint = _dotnet_material_resource(str(raw_path or ""))
    return f"texture:{fingerprint}"


def _dotnet_manifest_resource_bindings(
    resolved_channels: Mapping[str, str],
    packaged_channels: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    channels: dict[str, str] = {}
    resources: dict[str, dict[str, str]] = {}
    for semantic, raw_path in sorted(resolved_channels.items()):
        source_path = str(raw_path or "").strip()
        if not source_path:
            continue
        normalized_path, fingerprint = _dotnet_material_resource(source_path)
        resource_id = f"texture:{fingerprint}"
        channels[str(semantic)] = resource_id
        resources.setdefault(
            resource_id,
            {
                "resource_id": resource_id,
                "path": str(packaged_channels.get(semantic, normalized_path) or normalized_path),
                "fingerprint": fingerprint,
            },
        )
    return channels, resources


def mesh_dotnet_material_state_payload(
    mesh: ParsedMesh,
    *,
    session_id: str,
    edit_revision: int,
    generation: int,
    affected_submeshes: Sequence[int] | None = None,
) -> dict[str, object]:
    """Snapshot resident material bindings without rebuilding a package."""
    resources: dict[str, dict[str, str]] = {}
    submesh_payloads: list[dict[str, object]] = []
    all_indices: list[int] = []
    for fallback_index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ())):
        submesh_index = _safe_int(getattr(submesh, "submesh_index", fallback_index), fallback_index)
        all_indices.append(submesh_index)
        channels: dict[str, str] = {}
        for semantic, raw_path in sorted(_dotnet_resolved_texture_channels(submesh).items()):
            value = str(raw_path or "").strip()
            if not value:
                continue
            path, fingerprint = _dotnet_material_resource(value)
            resource_id = f"texture:{fingerprint}"
            resources.setdefault(
                resource_id,
                {"resource_id": resource_id, "path": path, "fingerprint": fingerprint},
            )
            channels[str(semantic)] = resource_id
        submesh_payloads.append(
            {
                "submesh_index": submesh_index,
                "material_slot_index": _safe_int(
                    getattr(submesh, "material_slot_index", fallback_index), fallback_index
                ),
                "material": str(getattr(submesh, "material", "") or ""),
                "channels": channels,
            }
        )
    valid_indices = set(all_indices)
    affected = sorted(valid_indices) if affected_submeshes is None else sorted(
        {
            index
            for value in affected_submeshes
            if (index := _safe_int(value, -1)) in valid_indices
        }
    )
    return {
        "schema": "cdmw_mesh_material_state_v2",
        "version": 2,
        "event": "material_state_update",
        "session_id": str(session_id or ""),
        "edit_revision": max(0, _safe_int(edit_revision, 0)),
        "generation": max(0, _safe_int(generation, 0)),
        "material_signature": mesh_dotnet_material_input_signature(mesh),
        "affected_submeshes": affected,
        "resources": [resources[key] for key in sorted(resources)],
        "submeshes": submesh_payloads,
    }


__all__ = [
    "mesh_dotnet_material_input_signature",
    "mesh_dotnet_material_state_payload",
    "mesh_dotnet_texture_resource_id",
]
