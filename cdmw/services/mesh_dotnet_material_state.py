"""Resident .NET material-state snapshots; no package or renderer ownership."""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from cdmw.modding.mesh_parser import ParsedMesh


_COMPONENT_NAMES = ("r", "g", "b", "a")


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
        semantic = {"base_color": "base", "color": "base", "metalness": "metallic"}.get(
            semantic, semantic
        )
        if semantic and path and semantic not in result:
            result[semantic] = path
    return result


def _material_texture_metadata(source: object | None) -> tuple[str, tuple[str, ...]]:
    if source is None:
        return "", ()
    subtype = str(getattr(source, "preview_material_texture_subtype", "") or "").strip().lower()
    packed = tuple(
        str(value or "").strip().lower()
        for value in tuple(getattr(source, "preview_material_texture_packed_channels", ()) or ())
        if str(value or "").strip()
    )
    for item in tuple(getattr(source, "preview_material_texture_inputs", ()) or ()):
        values = item if isinstance(item, Mapping) else vars(item) if hasattr(item, "__dict__") else {}
        semantic = str(
            values.get("semantic_type", "")
            or values.get("slot_kind", "")
            or getattr(item, "semantic_type", "")
            or getattr(item, "slot_kind", "")
            or ""
        ).strip().lower()
        if semantic != "material":
            continue
        subtype = str(
            values.get("semantic_subtype", "")
            or getattr(item, "semantic_subtype", "")
            or subtype
        ).strip().lower()
        item_packed = tuple(
            str(value or "").strip().lower()
            for value in tuple(values.get("packed_channels", ()) or getattr(item, "packed_channels", ()) or ())
            if str(value or "").strip()
        )
        if item_packed:
            packed = item_packed
        break
    return subtype, packed


def _dotnet_material_channel_components(source: object | None) -> dict[str, str]:
    subtype, packed = _material_texture_metadata(source)
    normalized = tuple(value.replace("metalness", "metallic") for value in packed)
    if subtype in {"metallic_roughness", "metallicroughness", "gltf_metallic_roughness"}:
        return {"roughness": "g", "metallic": "b"}
    if subtype in {"orm", "arm"}:
        return {"roughness": "g", "metallic": "b"}
    if subtype == "rma":
        return {"roughness": "r", "metallic": "g"}
    if subtype == "mra":
        return {"metallic": "r", "roughness": "g"}
    if subtype in {"specular_glossiness", "specularglossiness", "gltf_specular_glossiness"}:
        return {"roughness": "a", "specular": "rgb"}
    if normalized[:2] == ("roughness", "metallic"):
        return {"roughness": "g", "metallic": "b"}
    result: dict[str, str] = {}
    for index, semantic in enumerate(normalized[:4]):
        if semantic in {"roughness", "metallic", "specular"}:
            result.setdefault(semantic, _COMPONENT_NAMES[index])
    return result


def _material_parameter_value(source: object | None, parameter_name: str) -> object | None:
    wanted = parameter_name.strip().casefold()
    for item in tuple(getattr(source, "preview_material_parameters", ()) or ()):
        values = item if isinstance(item, Mapping) else vars(item) if hasattr(item, "__dict__") else {}
        name = str(values.get("parameter_name", "") or getattr(item, "parameter_name", "") or "").strip().casefold()
        if name != wanted:
            continue
        color = tuple(values.get("color_value", ()) or getattr(item, "color_value", ()) or ())
        if len(color) >= 3:
            return tuple(color[:3])
        numeric = values.get("numeric_value", getattr(item, "numeric_value", None))
        if numeric is not None:
            return numeric
        return values.get("value", getattr(item, "value", None))
    return None


def _finite_float(value: object, *, minimum: float, maximum: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return max(minimum, min(maximum, number)) if math.isfinite(number) else None


def _color3(value: object) -> tuple[float, float, float] | None:
    if isinstance(value, str) and len(value.strip()) == 7 and value.strip().startswith("#"):
        try:
            return tuple(int(value.strip()[offset : offset + 2], 16) / 255.0 for offset in (1, 3, 5))  # type: ignore[return-value]
        except ValueError:
            return None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) < 3:
        return None
    components = tuple(_finite_float(component, minimum=0.0, maximum=2.0) for component in value[:3])
    return components if all(component is not None for component in components) else None  # type: ignore[return-value]


def _dotnet_initial_material_parameters(
    source: object | None,
    resolved_channels: Mapping[str, str],
) -> dict[str, object]:
    if source is None:
        return {}
    result: dict[str, object] = {}
    color = _color3(getattr(source, "preview_color", ()))
    if color is not None and color != (1.0, 1.0, 1.0):
        result["tint_color"] = list(color)
    overrides = getattr(source, "preview_native_material_overrides", {})
    overrides = overrides if isinstance(overrides, Mapping) else {}
    subtype, _packed = _material_texture_metadata(source)
    is_gltf = subtype in {
        "metallic_roughness",
        "metallicroughness",
        "gltf_metallic_roughness",
        "specular_glossiness",
        "specularglossiness",
        "gltf_specular_glossiness",
    } or any(
        str(
            (item if isinstance(item, Mapping) else vars(item) if hasattr(item, "__dict__") else {}).get(
                "parameter_name", getattr(item, "parameter_name", "")
            )
            or ""
        ).startswith("_gltf")
        for item in tuple(getattr(source, "preview_material_parameters", ()) or ())
    )
    roughness = _finite_float(
        overrides.get("roughness", _material_parameter_value(source, "_roughnessFactor")),
        minimum=0.0,
        maximum=1.0,
    )
    metallic = _finite_float(
        overrides.get("metalness", overrides.get("metallic", _material_parameter_value(source, "_metallicFactor"))),
        minimum=0.0,
        maximum=1.0,
    )
    if is_gltf and roughness is None and "roughness" not in resolved_channels:
        roughness = 1.0
    if is_gltf and metallic is None and "metallic" not in resolved_channels:
        metallic = 1.0
    specular = _finite_float(
        overrides.get("specular", _material_parameter_value(source, "_specularFactor")),
        minimum=0.0,
        maximum=1.0,
    )
    if roughness is not None:
        result["roughness_scale" if "roughness" in resolved_channels else "roughness"] = roughness
    if metallic is not None:
        result["metalness_scale" if "metallic" in resolved_channels else "metalness"] = metallic
    if specular is not None and abs(specular - 1.0) > 1e-6:
        result["specular"] = specular
    if subtype in {"specular_glossiness", "specularglossiness", "gltf_specular_glossiness"}:
        result["roughness_inverted"] = True
    emissive_color = _color3(
        overrides.get("emissive_color", _material_parameter_value(source, "_emissiveColor"))
    )
    emissive_intensity = _finite_float(
        overrides.get("emissive_intensity", _material_parameter_value(source, "_emissiveIntensity")),
        minimum=0.0,
        maximum=32.0,
    )
    if emissive_color is not None:
        result["emissive_color"] = list(emissive_color)
    if emissive_intensity is not None:
        result["emissive_intensity"] = emissive_intensity
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
        "height": ("preview_height_texture_path", "preview_height_texture_dds_path", "preview_height_texture_default_path"),
        "emissive": ("preview_emissive_texture_path", "preview_emissive_texture_dds_path", "preview_emissive_texture_default_path"),
    }
    for channel, attrs in pairs.items():
        for attr in attrs:
            value = str(getattr(source, attr, "") or "").strip()
            if value:
                result[channel] = value
                break
    material_path = result.get("material", "")
    if material_path:
        for channel in _dotnet_material_channel_components(source):
            result.setdefault(channel, material_path)
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
                "channel_components": _dotnet_material_channel_components(submesh),
                "parameters": _dotnet_initial_material_parameters(
                    submesh, _dotnet_resolved_texture_channels(submesh)
                ),
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
                "channel_components": _dotnet_material_channel_components(submesh),
                "parameters": _dotnet_initial_material_parameters(
                    submesh, _dotnet_resolved_texture_channels(submesh)
                ),
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
