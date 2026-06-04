from __future__ import annotations

import dataclasses
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import tempfile
import time
from types import SimpleNamespace
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple
from urllib.parse import unquote, urlparse

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

from cdmw.core.dds_native import dds_native_report_dict, dds_source_path_from_report, inspect_dds_native_path
from cdmw.core.model_preview_orientation import resolve_preview_texture_flip_vertical
from cdmw.core.texture_native import read_native_texture_report_sidecar
from cdmw.models import (
    ClothPreviewBatch,
    ClothPreviewConstraint,
    ModelPreviewData,
    ModelPreviewRenderSettings,
    PreparedModelPreviewBatch,
    PreparedModelPreviewData,
    PreviewMaterialTextureInput,
    clamp_model_preview_render_settings,
    RunCancelled,
)
from cdmw.rendering.material_channels import (
    MATERIAL_CHANNEL_CONTRACT_SCHEMA_VERSION,
    resolve_preview_batch_material_channels,
)
from cdmw.rendering.asset_fidelity_preflight import asset_fidelity_preflight_manifest
from cdmw.rendering.crimson_shader_registry import (
    AUTHORITY_AUTHORITATIVE,
    AUTHORITY_GUESS,
    AUTHORITY_SIDECAR,
    decode_crimson_texture_binding,
    decode_crimson_texture_entry,
    decode_profile_for_family,
    normalize_shader_family,
    registry_manifest,
)


ISOLATED_PREVIEW_SCHEMA_VERSION = 9
SUPPORTED_ISOLATED_PREVIEW_SCHEMA_VERSIONS = {1, 2, 3, 4, 5, 6, 7, 8, 9}
MATERIAL_CONTRACT_SCHEMA_VERSION = 2
TEXTURE_QUALITY_SCHEMA_VERSION = 1
CLOTH_RUNTIME_SCHEMA_VERSION = 1
PREVIEW_OVERLAY_SCHEMA_VERSION = 1
ISOLATED_PREVIEW_VERTEX_FLOATS = 23
ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES = ISOLATED_PREVIEW_VERTEX_FLOATS * 4
_VERTEX_STRUCT = struct.Struct("<23f")
_IDENTITY_STRUCT = struct.Struct("<ii")
MESH_EDITOR_LOAD_TRACE_ENV = "CDMW_MESH_EDITOR_LOAD_TRACE"


def _mesh_editor_load_trace_enabled() -> bool:
    return str(os.environ.get(MESH_EDITOR_LOAD_TRACE_ENV, "") or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclasses.dataclass(frozen=True)
class NativePreviewBatchPayload:
    material_name: str = ""
    texture_name: str = ""
    vertex_count: int = 0
    bounds_min: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    bounds_max: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    base_color: Tuple[float, float, float] = (0.78, 0.48, 0.34)
    texture_source: str = ""
    normal_texture_source: str = ""
    material_texture_source: str = ""
    height_texture_source: str = ""
    normal_texture_strength: float = 1.0
    material_texture_packed_channels: Tuple[str, ...] = ()
    material_texture_slots: Tuple[str, ...] = ()
    material_texture_inputs: Tuple[PreviewMaterialTextureInput, ...] = ()
    texture_flip_vertical: bool = True
    has_texture_coordinates: bool = False
    tangents_usable: bool = False


def _local_file_url(path_value: object) -> str:
    text = str(path_value or "").strip()
    if not text:
        return ""
    if text.lower().startswith("file:"):
        return text
    try:
        path = Path(text).expanduser()
    except OSError:
        return ""
    if not path.is_file():
        return ""
    try:
        return path.resolve().as_uri()
    except (OSError, ValueError):
        return ""


def _payload_bounds(vertex_blob: bytes, vertex_count: int) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    usable_count = min(max(0, int(vertex_count)), len(vertex_blob) // ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES)
    if usable_count <= 0:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    mins = [float("inf"), float("inf"), float("inf")]
    maxs = [float("-inf"), float("-inf"), float("-inf")]
    for index in range(usable_count):
        try:
            vertex = _VERTEX_STRUCT.unpack_from(vertex_blob, index * ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES)
        except struct.error:
            break
        for axis in range(3):
            value = float(vertex[axis])
            mins[axis] = min(mins[axis], value)
            maxs[axis] = max(maxs[axis], value)
    if not all(math.isfinite(value) for value in (*mins, *maxs)):
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    return tuple(mins), tuple(maxs)  # type: ignore[return-value]


def _safe_float(value: object, fallback: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return result if math.isfinite(result) else fallback


def _safe_int(value: object, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _clamp01(value: object, fallback: float = 0.0) -> float:
    return max(0.0, min(1.0, _safe_float(value, fallback)))


def _first_vertex_color(vertex_blob: bytes) -> Tuple[float, float, float]:
    if len(vertex_blob) < ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES:
        return (0.78, 0.48, 0.34)
    try:
        vertex = _VERTEX_STRUCT.unpack_from(vertex_blob, 0)
    except struct.error:
        return (0.78, 0.48, 0.34)
    return (
        _clamp01(vertex[6], 0.78),
        _clamp01(vertex[7], 0.48),
        _clamp01(vertex[8], 0.34),
    )


def _vector_length(values: Sequence[float]) -> float:
    return math.sqrt(sum(float(value) * float(value) for value in values))


def _tangents_usable(vertex_blob: bytes, vertex_count: int) -> bool:
    if vertex_count <= 0:
        return False
    usable_count = min(vertex_count, len(vertex_blob) // ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES)
    if usable_count <= 0:
        return False
    checked = 0
    valid = 0
    for offset in range(0, usable_count * ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES, ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES):
        try:
            vertex = _VERTEX_STRUCT.unpack_from(vertex_blob, offset)
        except struct.error:
            continue
        normal = vertex[3:6]
        uv = vertex[9:11]
        tangent = vertex[11:14]
        bitangent = vertex[14:17]
        checked += 1
        if (
            all(math.isfinite(float(value)) for value in (*normal, *uv, *tangent, *bitangent))
            and _vector_length(normal) > 0.05
            and _vector_length(tangent) > 0.05
            and _vector_length(bitangent) > 0.05
        ):
            valid += 1
    return bool(checked > 0 and valid / float(checked) >= 0.80)


def _write_editor_identity_blob(
    package_dir: Path,
    geometry_dir: Path,
    batch_index: int,
    batch: PreparedModelPreviewBatch,
    vertex_count: int,
) -> Dict[str, object]:
    metadata, identity_blob = _editor_identity_blob(batch, vertex_count)
    identity_path = geometry_dir / f"batch_{batch_index:03d}_identity.bin"
    identity_path.write_bytes(identity_blob)
    metadata["identity_file"] = identity_path.relative_to(package_dir).as_posix()
    return metadata


def _editor_identity_blob(
    batch: PreparedModelPreviewBatch,
    vertex_count: int,
) -> Tuple[Dict[str, object], bytes]:
    source_submesh_index = _safe_int(getattr(batch, "source_submesh_index", -1), -1)
    raw_source_vertices = tuple(int(index) for index in tuple(getattr(batch, "source_vertex_indices", ()) or ()))
    identity_blob = bytearray()
    for vertex_offset in range(vertex_count):
        source_vertex_index = (
            int(raw_source_vertices[vertex_offset])
            if vertex_offset < len(raw_source_vertices)
            else int(vertex_offset)
        )
        identity_blob.extend(_IDENTITY_STRUCT.pack(source_submesh_index, source_vertex_index))
    return {
        "source_submesh_index": source_submesh_index,
        "source_vertex_count": len(raw_source_vertices),
        "identity_file": "",
        "identity_offset": 0,
        "identity_size": len(identity_blob),
        "role": str(getattr(batch, "editor_role", "") or ""),
        "part_name": str(getattr(batch, "editor_part_name", "") or ""),
        "editable": bool(getattr(batch, "editor_editable", source_submesh_index >= 0)),
    }, bytes(identity_blob)


def _write_cloth_runtime_payloads(
    package_dir: Path,
    geometry_dir: Path,
    batch_index: int,
    cloth_batch: object,
) -> Dict[str, object]:
    if not isinstance(cloth_batch, ClothPreviewBatch):
        return {}
    positions = tuple(getattr(cloth_batch, "positions", ()) or ())
    constraints = tuple(getattr(cloth_batch, "constraints", ()) or ())
    pin_weights = tuple(float(value) for value in tuple(getattr(cloth_batch, "pin_weights", ()) or ()))
    particle_count = len(positions)
    if particle_count <= 0:
        return {}
    if len(pin_weights) != particle_count:
        pin_weights = tuple(0.0 for _ in range(particle_count))

    particle_path = geometry_dir / f"batch_{batch_index:03d}_cloth_particles.bin"
    with particle_path.open("wb") as stream:
        for position in positions:
            try:
                x, y, z = (float(position[0]), float(position[1]), float(position[2]))
            except (TypeError, ValueError, IndexError, OverflowError):
                x, y, z = 0.0, 0.0, 0.0
            stream.write(struct.pack("<3f", x, y, z))

    pin_path = geometry_dir / f"batch_{batch_index:03d}_cloth_pins.bin"
    with pin_path.open("wb") as stream:
        for weight in pin_weights:
            stream.write(struct.pack("<f", max(0.0, min(1.0, _safe_float(weight, 0.0)))))

    constraint_path = geometry_dir / f"batch_{batch_index:03d}_cloth_constraints.bin"
    written_constraints = 0
    with constraint_path.open("wb") as stream:
        for constraint in constraints:
            if not isinstance(constraint, ClothPreviewConstraint):
                continue
            a = _safe_int(getattr(constraint, "a", -1), -1)
            b = _safe_int(getattr(constraint, "b", -1), -1)
            if a < 0 or b < 0 or a >= particle_count or b >= particle_count or a == b:
                continue
            rest_length = max(0.0, _safe_float(getattr(constraint, "rest_length", 0.0), 0.0))
            stiffness = max(0.0, min(1.0, _safe_float(getattr(constraint, "stiffness", 0.0), 0.0)))
            stream.write(struct.pack("<ii2f", a, b, rest_length, stiffness))
            written_constraints += 1

    material = getattr(cloth_batch, "material_settings", None)
    return {
        "cloth_enabled": True,
        "cloth_kind": str(getattr(cloth_batch, "simulation_kind", "cloth") or "cloth"),
        "cloth_material_name": str(getattr(cloth_batch, "simulation_material_name", "") or ""),
        "cloth_particle_file": particle_path.relative_to(package_dir).as_posix(),
        "cloth_pin_file": pin_path.relative_to(package_dir).as_posix(),
        "cloth_constraint_file": constraint_path.relative_to(package_dir).as_posix(),
        "cloth_particle_count": particle_count,
        "cloth_constraint_count": written_constraints,
        "cloth_gravity": _safe_float(getattr(material, "gravity", -10.0), -10.0),
        "cloth_damping": _safe_float(getattr(material, "damping", 0.65), 0.65),
        "cloth_air_resistance": _safe_float(getattr(material, "air_resistance", 1.0), 1.0),
        "cloth_wind_response": _safe_float(getattr(material, "wind_response", 0.4), 0.4),
        "cloth_solver_iterations": max(1, min(64, _safe_int(getattr(material, "solver_iterations", 30), 30))),
        "cloth_collision_enabled": bool(getattr(material, "collision_enabled", True)),
    }


def _tuple3(value: object) -> Tuple[float, float, float]:
    try:
        raw = tuple(value)  # type: ignore[arg-type]
        result = (float(raw[0]), float(raw[1]), float(raw[2]))
    except (TypeError, ValueError, IndexError, OverflowError):
        return ()
    return result if all(math.isfinite(component) for component in result) else ()


def _write_cloth_collider_payload(
    model: object,
    package_dir: Path,
    geometry_dir: Path,
) -> Tuple[str, int]:
    overlay = getattr(model, "physics_overlay", None)
    shapes = tuple(getattr(overlay, "shapes", ()) or ())
    if not shapes:
        return "", 0
    collider_path = geometry_dir / "cloth_colliders.bin"
    collider_count = 0
    with collider_path.open("wb") as stream:
        for shape in shapes[:512]:
            center = _tuple3(getattr(shape, "center", ()) or ())
            radius = max(0.0, _safe_float(getattr(shape, "radius", 0.0), 0.0))
            capsule_start = _tuple3(getattr(shape, "capsule_start", ()) or ())
            capsule_end = _tuple3(getattr(shape, "capsule_end", ()) or ())
            bounds_min = _tuple3(getattr(shape, "bounds_min", ()) or ())
            bounds_max = _tuple3(getattr(shape, "bounds_max", ()) or ())
            if capsule_start and capsule_end and radius > 0.0:
                record = (2.0, *capsule_start, *capsule_end, radius, 0.0, 0.0, 0.0)
            elif center and radius > 0.0:
                record = (1.0, *center, radius, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
            elif bounds_min and bounds_max:
                record = (3.0, *bounds_min, *bounds_max, 0.0, 0.0, 0.0, 0.0)
            else:
                vertices = tuple(getattr(shape, "vertices", ()) or ())
                points = [_tuple3(vertex) for vertex in vertices[:1024]]
                points = [point for point in points if point]
                if not points:
                    continue
                xs, ys, zs = zip(*points)
                record = (3.0, min(xs), min(ys), min(zs), max(xs), max(ys), max(zs), 0.0, 0.0, 0.0, 0.0)
            stream.write(struct.pack("<11f", *record))
            collider_count += 1
    if collider_count <= 0:
        try:
            collider_path.unlink()
        except OSError:
            pass
        return "", 0
    return collider_path.relative_to(package_dir).as_posix(), collider_count


def _physics_overlays_metadata(
    model: object,
    settings: ModelPreviewRenderSettings,
    *,
    cloth_batch_count: int,
    cloth_particle_count: int,
    cloth_constraint_count: int,
    cloth_collider_count: int,
) -> Dict[str, object]:
    overlay = getattr(model, "physics_overlay", None)
    return {
        "schema_version": PREVIEW_OVERLAY_SCHEMA_VERSION,
        "enabled": bool(getattr(settings, "show_physics_overlay", True)),
        "mode": "read_only",
        "cloth": bool(cloth_batch_count > 0),
        "cloth_particle_count": cloth_particle_count,
        "cloth_constraint_count": cloth_constraint_count,
        "collider_count": cloth_collider_count,
        "physics_shape_count": len(tuple(getattr(overlay, "shapes", ()) or ())),
        "anchor_count": len(tuple(getattr(overlay, "anchors", ()) or ())),
        "constraint_count": len(tuple(getattr(overlay, "constraints", ()) or ())),
        "source_paths": [str(path) for path in tuple(getattr(overlay, "source_paths", ()) or ())],
        "write_policy": "fixed_size_validated_edits_only",
    }


def _cloth_runtime_debug_metadata(
    settings: ModelPreviewRenderSettings,
    *,
    cloth_batch_count: int,
    cloth_particle_count: int,
    cloth_constraint_count: int,
    cloth_collider_count: int,
) -> Dict[str, object]:
    return {
        "schema_version": CLOTH_RUNTIME_SCHEMA_VERSION,
        "enabled": bool(getattr(settings, "enable_tool_pbd_cloth_preview", False)),
        "read_only": True,
        "batch_count": cloth_batch_count,
        "particle_count": cloth_particle_count,
        "constraint_count": cloth_constraint_count,
        "collider_count": cloth_collider_count,
        "show_pins": bool(getattr(settings, "show_tool_pbd_cloth_pins", False)),
        "show_colliders": bool(getattr(settings, "show_tool_pbd_cloth_colliders", False)),
        "paused": bool(getattr(settings, "pause_tool_pbd_cloth_preview", False)),
        "wind_strength": _safe_float(getattr(settings, "tool_pbd_cloth_wind_strength", 0.0), 0.0),
        "wind_direction_degrees": _safe_float(getattr(settings, "tool_pbd_cloth_wind_direction_degrees", 35.0), 35.0),
        "display_modes": ["particles", "pinned_vertices", "constraints", "colliders", "material_settings"],
        "write_policy": "preview_only",
    }


def _skeleton_overlay_metadata(model: object) -> Dict[str, object]:
    overlay = getattr(model, "physics_overlay", None)
    bones = tuple(getattr(overlay, "bones", ()) or ())
    bone_payload = []
    for bone in bones[:4096]:
        bone_payload.append(
            {
                "name": str(getattr(bone, "name", "") or ""),
                "index": _safe_int(getattr(bone, "index", -1), -1),
                "parent_index": _safe_int(getattr(bone, "parent_index", -1), -1),
                "parent_name": str(getattr(bone, "parent_name", "") or ""),
                "source_path": str(getattr(bone, "source_path", "") or ""),
                "confidence": str(getattr(bone, "confidence", "") or "skeleton_context"),
            }
        )
    return {
        "schema_version": PREVIEW_OVERLAY_SCHEMA_VERSION,
        "enabled": bool(bone_payload),
        "status": "ok" if bone_payload else "not_found",
        "read_only": True,
        "bone_count": len(bone_payload),
        "bones": bone_payload,
        "diagnostics": [] if bone_payload else ["related skeleton/HKX/HKT data was not resolved for this preview"],
    }


def _editable_value_groups_metadata(model: object, *, cloth_batch_count: int) -> list[Dict[str, object]]:
    overlay = getattr(model, "physics_overlay", None)
    groups: list[Dict[str, object]] = []
    if cloth_batch_count > 0:
        groups.append(
            {
                "kind": "pbd_cloth",
                "label": "PBD cloth values",
                "read_only": True,
                "write_policy": "fixed_size_validated_patch_only",
                "fields": ["gravity", "damping", "wind_response", "solver_iterations", "collision_enabled"],
            }
        )
    if overlay is not None:
        groups.append(
            {
                "kind": "hkx_physics",
                "label": "HKX physics values",
                "read_only": True,
                "write_policy": "fixed_size_numeric_patch_only",
                "unsafe_writes_blocked": ["references", "arrays", "strings", "topology", "class_metadata"],
            }
        )
    return groups


def _lighting_preset_for_settings(settings: ModelPreviewRenderSettings) -> str:
    d3d11_mode = str(getattr(settings, "d3d11_view_mode", "") or "").strip().lower()
    if d3d11_mode in {"game_outdoor", "cd_outdoor", "outdoor_game"}:
        return "game_outdoor_approx"
    mode = str(getattr(settings, "render_diagnostic_mode", "lit") or "lit").strip().lower()
    if mode in {"texture_probe", "base_direct", "base_no_tint", "normal_raw", "material_raw", "height_raw", "uv_checker"}:
        return "texture_debug"
    if mode in {"metal_shine", "roughness_response", "material_response"}:
        return "shiny_metal_inspection"
    if mode in {"rich_lit", "height_depth", "height_calibrated"}:
        return "cloth_skin_inspection"
    return "neutral_studio"


def _batch_has_metal_preview_response(batch: Mapping[str, object]) -> bool:
    if (
        str(batch.get("material_category", "") or "").strip().lower() == "metal"
        and _safe_float(batch.get("material_category_confidence"), 0.0) >= 0.45
    ):
        return True
    contract = batch.get("material_contract")
    if isinstance(contract, Mapping):
        hints = contract.get("pbr_scalar_hints")
        if isinstance(hints, Mapping):
            if _safe_float(hints.get("metalness"), 0.0) >= 0.18:
                return True
    return False


def _suffix_tokens(name: str) -> Tuple[str, ...]:
    lower = str(name or "").replace("\\", "/").split("/")[-1].lower()
    stem = lower.rsplit(".", 1)[0]
    return tuple(token for token in stem.replace("-", "_").split("_") if token)


def _contains_token(name: str, *tokens: str) -> bool:
    haystack = " ".join((str(name or "").lower(), " ".join(_suffix_tokens(name))))
    return any(str(token).lower() in haystack for token in tokens)


def _technical_texture_kind(name: str) -> str:
    tokens = _suffix_tokens(name)
    lower = str(name or "").lower()
    if (
        any(token in tokens for token in ("specularglossiness", "specgloss", "speculargloss"))
        or "specular_glossiness" in lower
        or ("specular" in lower and "glossiness" in lower)
    ):
        return "specular_glossiness"
    if any(token in tokens for token in ("emi", "emissive", "glow", "illum", "emit")) or "emissive" in lower:
        return "emissive"
    if any(token in tokens for token in ("n", "normal")) or lower.endswith("_n.dds"):
        return "normal"
    if any(token in tokens for token in ("disp", "height", "displacement")):
        return "height"
    if any(token in tokens for token in ("sp", "spec", "specular")):
        return "specular"
    if any(token in tokens for token in ("gloss", "glossiness", "smooth", "smoothness")):
        return "glossiness"
    if any(token in tokens for token in ("rough", "roughness")):
        return "roughness"
    if any(token in tokens for token in ("ao", "occlusion", "ambientocclusion")):
        return "occlusion"
    if any(token in tokens for token in ("metal", "metallic", "metalness")):
        return "metalness"
    if any(token in tokens for token in ("ma", "orm", "rma", "mra", "arm")):
        return "packed_material"
    if any(token in tokens for token in ("mg", "mask", "detail")):
        return "detail_mask"
    if any(token in tokens for token in ("opacity", "alpha")):
        return "opacity"
    return ""


def _input_texture_kind(texture_input: PreviewMaterialTextureInput) -> str:
    slot_kind = str(getattr(texture_input, "slot_kind", "") or "").strip().lower()
    semantic_type = str(getattr(texture_input, "semantic_type", "") or "").strip().lower()
    semantic_subtype = str(getattr(texture_input, "semantic_subtype", "") or "").strip().lower()
    parameter_name = str(getattr(texture_input, "parameter_name", "") or "").strip().lower()
    names = " ".join(
        (
            slot_kind,
            semantic_type,
            semantic_subtype,
            parameter_name,
            str(getattr(texture_input, "texture_name", "") or ""),
            str(getattr(texture_input, "source_texture_path", "") or ""),
            str(getattr(texture_input, "preview_texture_path", "") or ""),
        )
    )
    if slot_kind == "base" or semantic_type in {"base", "base_color", "diffuse", "albedo", "color"}:
        technical = _technical_texture_kind(names)
        return "" if technical in {"normal", "height", "packed_material", "detail_mask", "opacity", "specular", "specular_glossiness", "emissive"} else "base"
    if slot_kind == "emissive" or semantic_type == "emissive" or semantic_subtype.startswith("emissive") or _contains_token(names, "emissive", "glow", "illum"):
        return "emissive"
    if slot_kind == "normal" or semantic_type == "normal" or _contains_token(names, "normal"):
        return "normal"
    if slot_kind == "height" or semantic_type in {"height", "displacement"} or _contains_token(names, "disp", "height"):
        return "height"
    if slot_kind in {"ao", "occlusion"} or semantic_type in {"ao", "occlusion"} or semantic_subtype in {"ao", "occlusion"} or _contains_token(names, "ao", "occlusion"):
        return "occlusion"
    packed_channels = tuple(
        str(channel or "").strip().lower()
        for channel in getattr(texture_input, "packed_channels", ())
        if str(channel or "").strip()
    )
    if (
        semantic_subtype in {"specular_glossiness", "specularglossiness", "gltf_specular_glossiness"}
        or packed_channels[:2] == ("specular", "glossiness")
        or "specularglossiness" in parameter_name.replace("_", "")
    ):
        return "specular_glossiness"
    if semantic_subtype in {"metallic_roughness", "gltf_metallic_roughness"} or packed_channels[:2] == ("roughness", "metallic"):
        return "packed_material"
    if semantic_subtype in {"glossiness", "gloss", "smoothness", "smooth"} or _contains_token(names, "glossiness", "gloss", "smoothness"):
        return "glossiness"
    if semantic_subtype in {"roughness", "rough"} or _contains_token(names, "roughness"):
        return "roughness"
    if semantic_subtype in {"metal", "metallic", "metalness"} or _contains_token(names, "metallic", "metalness"):
        return "metalness"
    if semantic_subtype in {"specular", "spec"} or _contains_token(names, "specular"):
        return "specular"
    technical = _technical_texture_kind(names)
    if technical in {"specular", "specular_glossiness", "roughness", "glossiness", "metalness", "height", "normal", "opacity", "packed_material", "detail_mask", "emissive", "occlusion"}:
        return technical
    return ""


def _payload_material_slots(batch: PreparedModelPreviewBatch) -> Tuple[str, ...]:
    subtype = str(getattr(batch, "preview_material_texture_subtype", "") or "").strip().lower()
    channels = tuple(
        str(channel or "").strip().lower()
        for channel in tuple(getattr(batch, "preview_material_texture_packed_channels", ()) or ())
        if str(channel or "").strip()
    )
    descriptor = " ".join((subtype, " ".join(channels))).lower()
    if "opacity" in descriptor or channels == ("alpha",):
        return ()
    if "specular_glossiness" in descriptor or channels[:2] == ("specular", "glossiness"):
        return ("roughness", "specular")
    if subtype in {"orm", "rma", "mra"} or channels[:3] == ("ao", "roughness", "metallic"):
        return ("occlusion", "roughness", "metalness")
    if "material_mask" in descriptor or "mask" in descriptor:
        return ("roughness", "specular")
    if "roughness" in descriptor and ("metallic" in descriptor or "metalness" in descriptor):
        return ("roughness", "metalness")
    if "occlusion" in descriptor or "ao" in descriptor:
        return ("occlusion",)
    if "glossiness" in descriptor or "gloss" in descriptor:
        return ("roughness",)
    if "specular" in descriptor:
        return ("specular",)
    return ()


def _payload_material_inputs(batch: PreparedModelPreviewBatch) -> Tuple[PreviewMaterialTextureInput, ...]:
    explicit = tuple(getattr(batch, "preview_material_texture_inputs", ()) or ())
    if explicit:
        return explicit
    inputs: list[PreviewMaterialTextureInput] = []
    base_path = str(getattr(batch, "preview_texture_path", "") or "").strip()
    if base_path:
        inputs.append(
            PreviewMaterialTextureInput(
                slot_kind="base",
                texture_name=str(getattr(batch, "texture_name", "") or ""),
                preview_texture_path=base_path,
                semantic_type="color",
                visualized=True,
            )
        )
    normal_path = str(getattr(batch, "preview_normal_texture_path", "") or "").strip()
    if normal_path:
        inputs.append(
            PreviewMaterialTextureInput(
                slot_kind="normal",
                texture_name=str(getattr(batch, "preview_normal_texture_name", "") or ""),
                preview_texture_path=normal_path,
                semantic_type="normal",
                visualized=True,
            )
        )
    material_path = str(getattr(batch, "preview_material_texture_path", "") or "").strip()
    if material_path:
        inputs.append(
            PreviewMaterialTextureInput(
                slot_kind="material",
                texture_name=str(getattr(batch, "preview_material_texture_name", "") or ""),
                preview_texture_path=material_path,
                semantic_type="material",
                semantic_subtype=str(getattr(batch, "preview_material_texture_subtype", "") or ""),
                packed_channels=tuple(getattr(batch, "preview_material_texture_packed_channels", ()) or ()),
                visualized=True,
            )
        )
    height_path = str(getattr(batch, "preview_height_texture_path", "") or "").strip()
    if height_path:
        inputs.append(
            PreviewMaterialTextureInput(
                slot_kind="height",
                texture_name=str(getattr(batch, "preview_height_texture_name", "") or ""),
                preview_texture_path=height_path,
                semantic_type="height",
                visualized=True,
            )
        )
    return tuple(inputs)


def build_native_preview_payloads(
    prepared: PreparedModelPreviewData,
    *,
    render_settings: Optional[ModelPreviewRenderSettings] = None,
) -> Tuple[NativePreviewBatchPayload, ...]:
    settings = clamp_model_preview_render_settings(render_settings)
    payloads: list[NativePreviewBatchPayload] = []
    for batch in tuple(getattr(prepared, "batches", ()) or ()):
        vertex_blob = bytes(getattr(batch, "vertex_blob", b"") or b"")
        vertex_count = int(getattr(batch, "index_count", 0) or 0)
        if vertex_count <= 0 or not vertex_blob:
            continue
        bounds_min, bounds_max = _payload_bounds(vertex_blob, vertex_count)
        flip_value = getattr(batch, "preview_texture_flip_vertical", True)
        if flip_value is None:
            flip_value = resolve_preview_texture_flip_vertical(
                None,
                source_path=str(getattr(prepared, "source_path", "") or ""),
                source_format=str(getattr(prepared, "format", "") or ""),
                flip_texture_v=bool(getattr(settings, "flip_texture_v", False)),
            )
        material_channels = tuple(getattr(batch, "preview_material_texture_packed_channels", ()) or ())
        payloads.append(
            NativePreviewBatchPayload(
                material_name=str(getattr(batch, "material_name", "") or ""),
                texture_name=str(getattr(batch, "texture_name", "") or ""),
                vertex_count=vertex_count,
                bounds_min=bounds_min,
                bounds_max=bounds_max,
                base_color=_first_vertex_color(vertex_blob),
                texture_source=_local_file_url(getattr(batch, "preview_texture_path", "")),
                normal_texture_source=_local_file_url(getattr(batch, "preview_normal_texture_path", "")),
                material_texture_source=_local_file_url(getattr(batch, "preview_material_texture_path", "")),
                height_texture_source=_local_file_url(getattr(batch, "preview_height_texture_path", "")),
                normal_texture_strength=float(getattr(batch, "preview_normal_texture_strength", 1.0) or 1.0),
                material_texture_packed_channels=tuple(str(channel) for channel in material_channels),
                material_texture_slots=_payload_material_slots(batch),
                material_texture_inputs=_payload_material_inputs(batch),
                texture_flip_vertical=bool(flip_value),
                has_texture_coordinates=bool(getattr(batch, "has_texture_coordinates", False)),
                tangents_usable=_tangents_usable(vertex_blob, vertex_count),
            )
        )
    return tuple(payloads)


def _link_or_copy_file(source: Path, target: Path) -> None:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def _source_file_stat_key(source: Path) -> str:
    try:
        resolved = source.expanduser().resolve()
    except OSError:
        resolved = source
    try:
        stat = source.stat()
        return (
            f"{resolved}|size:{int(stat.st_size)}|mtime:{int(stat.st_mtime_ns)}"
        ).casefold()
    except OSError:
        return str(resolved).casefold()


def _texture_copy_slot_policy(slot_name: str, *, max_dimension: int, source_suffix: str, target_suffix: str) -> str:
    normalized_slot = str(slot_name or "texture").strip().lower() or "texture"
    return (
        f"slot:{normalized_slot}|cap:{max(0, int(max_dimension or 0))}|"
        f"source:{str(source_suffix or '').lower()}|target:{str(target_suffix or '').lower()}"
    )


def _copy_texture(
    source_path: str,
    *,
    package_dir: Path,
    textures_dir: Path,
    batch_index: int,
    slot_name: str,
    copy_cache: Dict[str, str],
    notes: list[str],
    max_dimension: int = 0,
    persistent_cache_dir: Optional[Path] = None,
) -> str:
    raw = str(source_path or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme.lower() == "file":
        raw = unquote(parsed.path or "")
        if len(raw) >= 3 and raw[0] == "/" and raw[2] == ":":
            raw = raw[1:]
    try:
        source = Path(raw).expanduser()
    except OSError:
        notes.append(f"{slot_name} invalid path")
        return ""
    if not source.is_file():
        notes.append(f"{slot_name} missing texture:{Path(raw).name}")
        return ""
    normalized_cap = max(0, int(max_dimension or 0))
    suffix = source.suffix if source.suffix else ".png"
    resize_supported = source.suffix.lower() not in {".dds"} and normalized_cap > 0
    target_suffix = ".png" if resize_supported else suffix
    slot_policy = _texture_copy_slot_policy(
        slot_name,
        max_dimension=normalized_cap,
        source_suffix=suffix,
        target_suffix=target_suffix,
    )
    key = f"{_source_file_stat_key(source)}|{slot_policy}"
    cached = copy_cache.get(key)
    if cached:
        return cached
    target = textures_dir / f"batch_{batch_index:03d}_{slot_name}_{len(copy_cache):03d}{target_suffix}"
    write_target = target
    cache_target: Optional[Path] = None
    if persistent_cache_dir is not None:
        try:
            persistent_cache_dir.mkdir(parents=True, exist_ok=True)
            key_hash = hashlib.sha1(key.encode("utf-8", errors="replace")).hexdigest()
            cache_target = persistent_cache_dir / f"{key_hash}{target_suffix}"
            if cache_target.is_file():
                _link_or_copy_file(cache_target, target)
                relative = target.relative_to(package_dir).as_posix()
                copy_cache[key] = relative
                return relative
            write_target = cache_target
        except OSError:
            cache_target = None
            write_target = target
    try:
        if resize_supported:
            image = QImage(str(source))
            if image.isNull():
                shutil.copy2(source, write_target)
            else:
                capped = max(int(image.width()), int(image.height())) > normalized_cap
                if capped:
                    image = image.scaled(
                        normalized_cap,
                        normalized_cap,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                if image.save(str(write_target), "PNG"):
                    if capped:
                        notes.append(f"{slot_name} preview texture capped:{normalized_cap}px")
                else:
                    shutil.copy2(source, write_target)
        else:
            shutil.copy2(source, write_target)
        if cache_target is not None:
            _link_or_copy_file(cache_target, target)
    except OSError as exc:
        notes.append(f"{slot_name} copy failed:{exc}")
        return ""
    relative = target.relative_to(package_dir).as_posix()
    copy_cache[key] = relative
    return relative


def _materialize_in_memory_texture_key(
    model: object,
    texture_key: str,
    *,
    textures_dir: Path,
    batch_index: int,
    slot_name: str,
) -> str:
    key = str(texture_key or "").strip()
    if not key.startswith("in_memory"):
        return key
    prefix, _separator, raw_index = key.partition(":")
    try:
        mesh_index = int(raw_index)
    except (TypeError, ValueError):
        return key
    meshes = tuple(getattr(model, "meshes", ()) or ())
    if mesh_index < 0 or mesh_index >= len(meshes):
        return key
    image_attribute = {
        "in_memory": "preview_texture_image",
        "in_memory_normal": "preview_normal_texture_image",
        "in_memory_material": "preview_material_texture_image",
        "in_memory_height": "preview_height_texture_image",
    }.get(prefix)
    if not image_attribute:
        return key
    image = getattr(meshes[mesh_index], image_attribute, None)
    if image is None or not hasattr(image, "save"):
        return key
    try:
        if hasattr(image, "isNull") and image.isNull():
            return key
    except Exception:
        return key
    materialized_dir = textures_dir / "in_memory"
    materialized_dir.mkdir(parents=True, exist_ok=True)
    target = materialized_dir / f"batch_{batch_index:03d}_{slot_name}.png"
    try:
        if image.save(str(target), "PNG"):
            return str(target)
    except Exception:
        return key
    return key


def _materialized_in_memory_batch(
    model: object,
    batch: PreparedModelPreviewBatch,
    *,
    textures_dir: Path,
    batch_index: int,
) -> PreparedModelPreviewBatch:
    replacements: Dict[str, str] = {}
    for attribute_name, slot_name in (
        ("preview_texture_path", "base"),
        ("preview_normal_texture_path", "normal"),
        ("preview_material_texture_path", "material"),
        ("preview_height_texture_path", "height"),
    ):
        value = str(getattr(batch, attribute_name, "") or "")
        materialized = _materialize_in_memory_texture_key(
            model,
            value,
            textures_dir=textures_dir,
            batch_index=batch_index,
            slot_name=slot_name,
        )
        if materialized != value:
            replacements[attribute_name] = materialized
    if not replacements:
        return batch
    return dataclasses.replace(batch, **replacements)


def _split_legacy_pbr_texture(
    source_path: str,
    *,
    package_dir: Path,
    textures_dir: Path,
    batch_index: int,
    notes: list[str],
    max_dimension: int = 0,
) -> Dict[str, str]:
    raw = str(source_path or "").strip()
    if not raw:
        return {}
    try:
        source = Path(raw).expanduser()
    except OSError:
        notes.append("legacy PBR map invalid path")
        return {}
    if not source.is_file():
        notes.append(f"legacy PBR map missing:{Path(raw).name}")
        return {}
    image = QImage(str(source)).convertToFormat(QImage.Format.Format_RGBA8888)
    if image.isNull():
        notes.append(f"legacy PBR map unreadable:{source.name}")
        return {}
    width = int(image.width())
    height = int(image.height())
    if width <= 0 or height <= 0:
        notes.append(f"legacy PBR map empty:{source.name}")
        return {}
    normalized_cap = max(0, int(max_dimension or 0))
    if normalized_cap > 0 and max(width, height) > normalized_cap:
        image = image.scaled(
            normalized_cap,
            normalized_cap,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ).convertToFormat(QImage.Format.Format_RGBA8888)
        width = int(image.width())
        height = int(image.height())
        notes.append(f"legacy PBR response capped:{normalized_cap}px")
    output_dir = textures_dir / "combined"
    output_dir.mkdir(parents=True, exist_ok=True)
    slot_channels = {
        "occlusion": 0,
        "roughness": 1,
        "metalness": 2,
        "specular": 3,
    }
    generated: Dict[str, str] = {}
    for slot_name, channel_index in slot_channels.items():
        target = QImage(width, height, QImage.Format.Format_RGB888)
        peak = 0
        for y in range(height):
            for x in range(width):
                color = image.pixelColor(x, y)
                value = (
                    color.red()
                    if channel_index == 0
                    else color.green()
                    if channel_index == 1
                    else color.blue()
                    if channel_index == 2
                    else color.alpha()
                )
                peak = max(peak, int(value))
                target.setPixelColor(x, y, QColor(value, value, value))
        if slot_name in {"metalness", "specular"} and peak <= 3:
            continue
        target_path = output_dir / f"batch_{batch_index:03d}_{slot_name}_legacy_pbr.png"
        if target.save(str(target_path), "PNG"):
            generated[slot_name] = target_path.relative_to(package_dir).as_posix()
    if generated:
        notes.append("legacy PBR response reused for D3D11 material slots")
    return generated


def _render_settings_to_dict(settings: Optional[ModelPreviewRenderSettings]) -> Dict[str, object]:
    value = clamp_model_preview_render_settings(settings)
    return {
        field_info.name: getattr(value, field_info.name)
        for field_info in dataclasses.fields(ModelPreviewRenderSettings)
    }


def _normalized_shader_family(value: object) -> str:
    return normalize_shader_family(value)


def _material_contract_shader_family(batch: PreparedModelPreviewBatch) -> str:
    candidates: list[str] = []
    direct = str(getattr(batch, "preview_sidecar_shader_family", "") or "").strip()
    if direct:
        candidates.append(direct)
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if isinstance(texture_input, PreviewMaterialTextureInput):
            shader_family = str(getattr(texture_input, "shader_family", "") or "").strip()
            if shader_family:
                candidates.append(shader_family)
    if not candidates:
        return ""
    normalized = [_normalized_shader_family(value) for value in candidates]
    for preferred in (
        "skin",
        "hair",
        "cloth_v2",
        "cloth",
        "standard_v2",
        "standard",
        "static_multitextured",
        "static_standard",
        "emissive_v2",
        "emissive",
    ):
        if preferred in normalized:
            return preferred
    return normalized[0]


def _material_decode_policy(shader_family: str) -> Dict[str, object]:
    family = _normalized_shader_family(shader_family)
    registry_policy = decode_profile_for_family(family)
    policies: Dict[str, Dict[str, object]] = {
        "skin": {
            "roughness_source": "sidecar skin roughness/detail parameters",
            "metalness_scale": 0.08,
            "specular_scale": 0.45,
            "layered_diffuse": True,
        },
        "hair": {
            "roughness_source": "hair flow/specular parameters",
            "metalness_scale": 0.02,
            "specular_scale": 0.70,
            "anisotropic_hint": True,
        },
        "cloth": {
            "roughness_source": "cloth material/detail mask parameters",
            "metalness_scale": 0.12,
            "specular_scale": 0.38,
            "layered_diffuse": True,
        },
        "cloth_v2": {
            "roughness_source": "cloth v2 colorBlend/detail/grime parameters",
            "metalness_scale": 0.16,
            "specular_scale": 0.42,
            "layered_diffuse": True,
        },
        "standard": {
            "roughness_source": "standard material mask/specular parameters",
            "metalness_scale": 0.62,
            "specular_scale": 0.82,
            "layered_diffuse": True,
        },
        "standard_v2": {
            "roughness_source": "standard v2 material/detail/grime parameters",
            "metalness_scale": 0.78,
            "specular_scale": 0.90,
            "layered_diffuse": True,
        },
        "static_standard": {
            "roughness_source": "static material mask parameters",
            "metalness_scale": 0.72,
            "specular_scale": 0.80,
            "layered_diffuse": False,
        },
        "static_multitextured": {
            "roughness_source": "rgbTexture layer material parameters",
            "metalness_scale": 0.70,
            "specular_scale": 0.78,
            "layered_diffuse": True,
        },
        "emissive_v2": {
            "roughness_source": "emissive v2 standard/detail parameters",
            "metalness_scale": 0.42,
            "specular_scale": 0.68,
            "layered_diffuse": True,
            "emissive_hint": True,
        },
    }
    policy = dict(policies.get(family, {}))
    if not policy:
        policy = {
            "roughness_source": "generic material mask/specular fallback",
            "metalness_scale": 0.55,
            "specular_scale": 0.72,
            "layered_diffuse": False,
            "unknown_family": bool(family),
        }
    policy["family"] = family or "generic"
    policy["authority"] = str(registry_policy.get("authority", "") or AUTHORITY_GUESS)
    policy["registry_schema_version"] = registry_policy.get("schema_version", 1)
    policy["global_material_promotions"] = list(tuple(registry_policy.get("global_material_promotions", ()) or ()))
    policy["unknown_policy"] = "unresolved_diagnostic"
    policy["renderdoc_truth_pass"] = registry_policy.get("renderdoc_truth_pass", {})
    return policy


def _texture_slot_state(slot_name: str, textures: Mapping[str, str], dds_textures: Mapping[str, object]) -> Dict[str, object]:
    dds_entry = dds_textures.get(slot_name)
    preview_path = str(textures.get(slot_name, "") or "")
    source_dds_path = str(dds_entry.get("source_path", "") or "") if isinstance(dds_entry, Mapping) else ""
    direct_dds = bool(
        isinstance(dds_entry, Mapping)
        and dds_entry.get("available")
        and source_dds_path
        and dds_entry.get("direct_upload_candidate")
    )
    status = "direct_dds" if direct_dds else ("preview_png" if preview_path else "missing")
    confidence = str(dds_entry.get("confidence", "") or "").strip().lower() if isinstance(dds_entry, Mapping) else ""
    if not confidence:
        confidence = "high" if direct_dds else ("medium" if preview_path else "missing")
    diagnostic = {
        "direct_dds": "using source DDS for native upload",
        "preview_png": "using preview texture fallback",
        "missing": "texture slot unresolved",
    }.get(status, status)
    state = {
        "slot": slot_name,
        "preview_path": preview_path,
        "source_dds_path": source_dds_path,
        "source_width": _safe_int(dds_entry.get("width"), 0) if isinstance(dds_entry, Mapping) else 0,
        "source_height": _safe_int(dds_entry.get("height"), 0) if isinstance(dds_entry, Mapping) else 0,
        "direct_dds": direct_dds,
        "status": status,
        "confidence": confidence,
        "authority": str(dds_entry.get("authority", "") or (AUTHORITY_AUTHORITATIVE if (direct_dds or preview_path) else AUTHORITY_GUESS)) if isinstance(dds_entry, Mapping) else (AUTHORITY_AUTHORITATIVE if preview_path else AUTHORITY_GUESS),
        "source_kind": "direct_dds" if direct_dds else ("preview_texture" if preview_path else "missing"),
        "reason": str(dds_entry.get("reason", "") or "") if isinstance(dds_entry, Mapping) else "",
        "diagnostic": diagnostic,
    }
    if isinstance(dds_entry, Mapping):
        for field in (
            "archive_path",
            "parameter_name",
            "semantic_type",
            "semantic_subtype",
            "shader_family",
            "shader_rule",
            "sidecar_path",
            "sidecar_kind",
            "packed_channels",
            "srgb_mode",
            "parameter_declared_by",
            "material_output_quality",
            "layer_role",
            "layer_channel",
            "blend_flags",
            "authority",
            "disposition",
            "registry_source_kind",
        ):
            value = dds_entry.get(field)
            if value not in (None, ""):
                state[field] = value
    return state


def _material_input_contract_slots(texture_input: PreviewMaterialTextureInput) -> Tuple[str, ...]:
    slot_kind = str(getattr(texture_input, "slot_kind", "") or "").strip().lower()
    semantic_type = str(getattr(texture_input, "semantic_type", "") or "").strip().lower()
    semantic_subtype = str(getattr(texture_input, "semantic_subtype", "") or "").strip().lower()
    parameter_name = str(getattr(texture_input, "parameter_name", "") or "").strip().lower()
    packed_channels = tuple(
        str(channel or "").strip().lower()
        for channel in tuple(getattr(texture_input, "packed_channels", ()) or ())
        if str(channel or "").strip()
    )
    descriptor = " ".join(
        (
            slot_kind,
            semantic_type,
            semantic_subtype,
            parameter_name,
            " ".join(packed_channels),
            str(getattr(texture_input, "texture_name", "") or ""),
            str(getattr(texture_input, "source_texture_path", "") or ""),
            str(getattr(texture_input, "preview_texture_path", "") or ""),
        )
    ).lower()
    compact_descriptor = descriptor.replace("_", "").replace("-", "").replace(" ", "")
    slots: list[str] = []

    def add(slot_name: str) -> None:
        normalized = str(slot_name or "").strip().lower()
        if normalized == "ao":
            normalized = "occlusion"
        elif normalized in {"metallic", "metal"}:
            normalized = "metalness"
        elif normalized in {"gloss", "smooth", "smoothness"}:
            normalized = "glossiness"
        if normalized in _NORMALIZED_MATERIAL_CONTRACT_SLOTS and normalized not in slots:
            slots.append(normalized)

    registry_decode = decode_crimson_texture_binding(
        shader_family=str(getattr(texture_input, "shader_family", "") or ""),
        parameter_name=str(getattr(texture_input, "parameter_name", "") or ""),
        source_path=str(getattr(texture_input, "source_dds_path", "") or getattr(texture_input, "source_texture_path", "") or getattr(texture_input, "preview_texture_path", "") or ""),
        slot_name=slot_kind or "material",
        semantic_subtype=semantic_subtype,
        packed_channels=packed_channels,
        layer_channel=str(getattr(texture_input, "layer_channel", "") or ""),
        blend_flags=tuple(getattr(texture_input, "blend_flags", ()) or ()),
        sidecar_kind=str(getattr(texture_input, "sidecar_kind", "") or ""),
        parameter_declared_by=str(getattr(texture_input, "parameter_declared_by", "") or ""),
    )
    registry_authority = str(registry_decode.get("authority", "") or AUTHORITY_GUESS)
    registry_source_kind = str(registry_decode.get("source_kind", "") or "")
    if registry_authority != AUTHORITY_GUESS or registry_source_kind == "explicit_packed_material":
        promoted = registry_decode.get("promoted_channels", {})
        if isinstance(promoted, Mapping) and promoted:
            for channel_name in promoted:
                add(str(channel_name))
            return tuple(slots)
        registry_slot = str(registry_decode.get("slot", "") or "")
        registry_disposition = str(registry_decode.get("disposition", "") or "")
        if registry_slot in {"base", "normal", "emissive", "height", "opacity"} and registry_disposition in {"promoted", "recorded"}:
            add(registry_slot)
            return tuple(slots)
        if registry_disposition in {"layer_only", "layer_material_response", "layer_flow", "layer_direction", "diagnostic_only", "scalar_hint"}:
            return tuple(slots)

    if "specularglossiness" in compact_descriptor or packed_channels[:2] == ("specular", "glossiness"):
        add("specular_glossiness")
        add("specular")
        add("glossiness")
    if semantic_subtype in {"metallic_roughness", "gltf_metallic_roughness"} or {"roughness", "metallic"} <= set(packed_channels):
        if any(channel in {"ao", "occlusion", "ambientocclusion"} for channel in packed_channels):
            add("occlusion")
        add("roughness")
        add("metalness")
    if slot_kind in _NORMALIZED_MATERIAL_CONTRACT_SLOTS:
        add(slot_kind)
    if slot_kind in {"ao", "metallic"}:
        add(slot_kind)
    if semantic_type in {"base", "base_color", "diffuse", "albedo", "color", "normal", "height", "emissive", "opacity"}:
        add("base" if semantic_type in {"base_color", "diffuse", "albedo", "color"} else semantic_type)
    if semantic_type in {"ao", "occlusion", "metallic", "metalness", "roughness", "specular"}:
        add(semantic_type)
    if semantic_subtype in {"ao", "occlusion", "metallic", "metalness", "roughness", "specular", "glossiness", "opacity", "height", "emissive"}:
        add(semantic_subtype)
    if "clearcoat" in compact_descriptor:
        add("clearcoat")
    if "sheen" in compact_descriptor:
        add("sheen")
    if any(marker in compact_descriptor for marker in ("transmission", "volume", "thickness", "ior", "glass")):
        add("transmission")
    if any(marker in compact_descriptor for marker in ("opacity", "alpha", "transparent")):
        add("opacity")
    if "unlit" in compact_descriptor:
        add("unlit")

    technical = _input_texture_kind(texture_input)
    if technical == "packed_material":
        for channel in packed_channels:
            add(channel)
        if not packed_channels:
            add("roughness")
            add("metalness")
    elif technical == "specular_glossiness":
        add("specular_glossiness")
        add("specular")
        add("glossiness")
    elif technical:
        add(technical)
    return tuple(slots)


def _material_input_slot_state(slot_name: str, texture_input: PreviewMaterialTextureInput) -> Dict[str, object]:
    preview_path = str(getattr(texture_input, "preview_texture_path", "") or "")
    source_path = str(getattr(texture_input, "source_texture_path", "") or "")
    source_dds_path = str(getattr(texture_input, "source_dds_path", "") or "")
    confidence = str(getattr(texture_input, "confidence", "") or "").strip().lower() or "medium"
    registry_decode = decode_crimson_texture_binding(
        shader_family=str(getattr(texture_input, "shader_family", "") or ""),
        parameter_name=str(getattr(texture_input, "parameter_name", "") or ""),
        source_path=source_dds_path or source_path or preview_path,
        slot_name=slot_name,
        semantic_subtype=str(getattr(texture_input, "semantic_subtype", "") or ""),
        packed_channels=tuple(getattr(texture_input, "packed_channels", ()) or ()),
        layer_channel=str(getattr(texture_input, "layer_channel", "") or ""),
        blend_flags=tuple(getattr(texture_input, "blend_flags", ()) or ()),
        sidecar_kind=str(getattr(texture_input, "sidecar_kind", "") or ""),
        parameter_declared_by=str(getattr(texture_input, "parameter_declared_by", "") or ""),
    )
    note_by_slot = {
        "clearcoat": "source clearcoat recorded; native preview approximates it through specular response",
        "sheen": "source sheen recorded; native preview approximates it through soft specular response",
        "transmission": "source transmission/volume recorded; native preview does not render true glass",
        "opacity": "source opacity recorded; not used as material mask to avoid opaque preview blackout",
        "specular_glossiness": "source specular-glossiness recorded; preview generation decodes RGB specular and alpha glossiness",
        "glossiness": "source glossiness recorded; preview generation inverts it to roughness where supported",
        "unlit": "source unlit material recorded; native preview uses flat non-PBR material hints",
    }
    return {
        "slot": slot_name,
        "preview_path": preview_path,
        "source_dds_path": source_dds_path,
        "source_texture_path": source_path,
        "source_width": 0,
        "source_height": 0,
        "direct_dds": False,
        "status": "input_only" if (preview_path or source_path or source_dds_path) else "recorded",
        "confidence": confidence,
        "authority": str(registry_decode.get("authority", "") or (AUTHORITY_SIDECAR if str(getattr(texture_input, "sidecar_kind", "") or getattr(texture_input, "parameter_declared_by", "") or "").strip() else AUTHORITY_GUESS)),
        "source_kind": "material_input",
        "registry_source_kind": str(registry_decode.get("source_kind", "") or ""),
        "parameter_name": str(getattr(texture_input, "parameter_name", "") or ""),
        "semantic_type": str(getattr(texture_input, "semantic_type", "") or ""),
        "semantic_subtype": str(getattr(texture_input, "semantic_subtype", "") or ""),
        "shader_family": str(getattr(texture_input, "shader_family", "") or ""),
        "packed_channels": list(tuple(getattr(texture_input, "packed_channels", ()) or ())),
        "disposition": str(registry_decode.get("disposition", "") or ""),
        "layer_channel": str(registry_decode.get("layer_channel", "") or getattr(texture_input, "layer_channel", "") or ""),
        "blend_flags": list(tuple(getattr(texture_input, "blend_flags", ()) or ())),
        "promoted_channels": dict(registry_decode.get("promoted_channels", {}) or {}),
        "diagnostic": note_by_slot.get(slot_name, "source material input recorded"),
    }


def _batch_has_unlit_material_hint(batch: PreparedModelPreviewBatch) -> bool:
    overrides = getattr(batch, "preview_native_material_overrides", {}) or {}
    if isinstance(overrides, Mapping) and str(overrides.get("material_shader_family", "") or "").strip().lower() == "gltf_unlit":
        return True
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        for parameter in tuple(getattr(texture_input, "material_parameters", ()) or ()):
            parameter_name = str(getattr(parameter, "parameter_name", "") or "").strip().lower()
            if parameter_name == "_gltfunlit" or "gltfunlit" in parameter_name.replace("_", ""):
                return True
    return False


def _normalized_material_texture_slot_states(
    batch: PreparedModelPreviewBatch,
    *,
    textures: Mapping[str, str],
    dds_textures: Mapping[str, object],
) -> Dict[str, Dict[str, object]]:
    states: Dict[str, Dict[str, object]] = {
        slot_name: {
            "slot": slot_name,
            "preview_path": "",
            "source_dds_path": "",
            "source_width": 0,
            "source_height": 0,
            "direct_dds": False,
            "status": "missing",
            "confidence": "missing",
            "source_kind": "missing",
            "diagnostic": "texture slot unresolved",
        }
        for slot_name in _NORMALIZED_MATERIAL_CONTRACT_SLOTS
    }

    def assign(slot_name: str, state: Mapping[str, object], *, replace: bool = False) -> None:
        current = states.get(slot_name)
        if current is None:
            return
        if not replace and str(current.get("status", "") or "") != "missing":
            return
        updated = dict(state)
        updated["slot"] = slot_name
        states[slot_name] = updated

    for slot_name in ("base", "normal", "occlusion", "roughness", "metalness", "specular", "height", "emissive"):
        state = _texture_slot_state(slot_name, textures, dds_textures)
        if str(state.get("status", "") or "") != "missing":
            assign(slot_name, state, replace=True)

    packed_state = _texture_slot_state("material", textures, dds_textures)
    if str(packed_state.get("status", "") or "") != "missing":
        raw_packed = packed_state.get("packed_channels", ())
        state_packed_channels = tuple(
            str(channel or "").strip().lower()
            for channel in (
                raw_packed
                if isinstance(raw_packed, Sequence) and not isinstance(raw_packed, (str, bytes, bytearray))
                else ()
            )
            if str(channel or "").strip()
        )
        batch_packed_channels = tuple(
            str(channel or "").strip().lower()
            for channel in tuple(getattr(batch, "preview_material_texture_packed_channels", ()) or ())
            if str(channel or "").strip()
        )
        registry_decode = decode_crimson_texture_binding(
            shader_family=str(packed_state.get("shader_family", "") or _material_contract_shader_family(batch)),
            parameter_name=str(packed_state.get("parameter_name", "") or ""),
            source_path=str(packed_state.get("source_dds_path", "") or packed_state.get("preview_path", "") or ""),
            slot_name="material",
            semantic_subtype=str(packed_state.get("semantic_subtype", "") or ""),
            packed_channels=state_packed_channels or batch_packed_channels,
            layer_channel=str(packed_state.get("layer_channel", "") or ""),
            blend_flags=tuple(packed_state.get("blend_flags", ()) or ()) if isinstance(packed_state.get("blend_flags", ()), Sequence) and not isinstance(packed_state.get("blend_flags", ()), (str, bytes, bytearray)) else (),
            sidecar_kind=str(packed_state.get("sidecar_kind", "") or ""),
            parameter_declared_by=str(packed_state.get("parameter_declared_by", "") or ""),
        )
        promoted = registry_decode.get("promoted_channels", {})
        promoted_mapping = promoted if isinstance(promoted, Mapping) else {}
        for channel_name, slot_name in (("ao", "occlusion"), ("roughness", "roughness"), ("metalness", "metalness"), ("metallic", "metalness")):
            if str(states[slot_name].get("status", "") or "") != "missing":
                continue
            source_channel = str(promoted_mapping.get(channel_name, "") or "")
            if not source_channel:
                continue
            state = dict(packed_state)
            state["source_kind"] = str(registry_decode.get("source_kind", "") or "packed_material")
            state["registry_source_kind"] = str(registry_decode.get("source_kind", "") or "")
            state["authority"] = str(registry_decode.get("authority", "") or AUTHORITY_GUESS)
            state["disposition"] = str(registry_decode.get("disposition", "") or "promoted")
            state["source_channel"] = source_channel
            state["diagnostic"] = str(registry_decode.get("reason", "") or f"packed material texture supplies {slot_name}")
            assign(slot_name, state, replace=True)

    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        for slot_name in _material_input_contract_slots(texture_input):
            assign(slot_name, _material_input_slot_state(slot_name, texture_input))

    if _batch_has_unlit_material_hint(batch):
        states["unlit"] = {
            "slot": "unlit",
            "preview_path": "",
            "source_dds_path": "",
            "source_width": 0,
            "source_height": 0,
            "direct_dds": False,
            "status": "recorded",
            "confidence": "high",
            "source_kind": "material_parameter",
            "diagnostic": "source unlit material recorded; native preview uses flat non-PBR material hints",
        }
    return states


def _material_sidecar_paths(batch: PreparedModelPreviewBatch) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        for value in (getattr(texture_input, "sidecar_path", ""), getattr(texture_input, "linked_mesh_path", "")):
            path = str(value or "").strip()
            if path and path not in seen:
                paths.append(path)
                seen.add(path)
    return paths


def _material_lighting_preset(shader_family: str, hints: Mapping[str, object], diagnostic_mode: str = "") -> str:
    mode = str(diagnostic_mode or "").strip().lower()
    if mode in {"texture_probe", "base_direct", "base_no_tint", "material_raw", "normal_raw", "height_raw"}:
        return "texture_debug"
    family = str(shader_family or "").strip().lower()
    if family in {"cloth", "cloth_v2", "skin", "hair"}:
        return "cloth_skin_inspection"
    if _safe_float(hints.get("metalness"), 0.0) >= 0.25 or _safe_float(hints.get("specular"), 0.0) >= 0.30:
        return "shiny_metal_inspection"
    return "neutral_studio"


def _material_decode_profile(
    shader_family: str,
    hints: Mapping[str, object],
    combiner_metadata: Mapping[str, object],
    packed_channels: Sequence[str],
) -> Dict[str, object]:
    return {
        "profile": shader_family or "generic",
        "shader_family": shader_family or "generic",
        "packed_channels": list(tuple(packed_channels or ())),
        "decode_modes": list(tuple(combiner_metadata.get("decode_modes", ()) or ())),
        "combiner_outputs": list(tuple(combiner_metadata.get("outputs", ()) or ())),
        "pbr_scalar_hints": {
            "roughness": _safe_float(hints.get("roughness"), 0.55),
            "metalness": _safe_float(hints.get("metalness"), 0.0),
            "specular": _safe_float(hints.get("specular"), 0.08),
            "height_scale": _safe_float(hints.get("height_scale"), 0.0),
            "emissive_intensity": _safe_float(hints.get("emissive_intensity"), 0.0),
        },
        "lighting_preset_hint": _material_lighting_preset(shader_family, hints),
    }


_MATERIAL_CONTRACT_SLOTS = ("base", "normal", "material", "occlusion", "roughness", "metalness", "specular", "height", "emissive")
_NORMALIZED_MATERIAL_CONTRACT_SLOTS = (
    "base",
    "normal",
    "occlusion",
    "roughness",
    "metalness",
    "specular",
    "glossiness",
    "specular_glossiness",
    "emissive",
    "opacity",
    "height",
    "clearcoat",
    "sheen",
    "transmission",
    "unlit",
)


def _material_slot_diagnostics(
    slot_states: Mapping[str, Mapping[str, object]],
    slot_order: Sequence[str] = _MATERIAL_CONTRACT_SLOTS,
) -> list[Dict[str, object]]:
    diagnostics: list[Dict[str, object]] = []
    for slot_name in tuple(slot_order or ()):
        slot = slot_states.get(slot_name, {})
        diagnostics.append(
            {
                "slot": slot_name,
                "status": str(slot.get("status", "missing") or "missing"),
                "confidence": str(slot.get("confidence", "missing") or "missing"),
                "authority": str(slot.get("authority", "") or AUTHORITY_GUESS),
                "source_kind": str(slot.get("source_kind", "missing") or "missing"),
                "registry_source_kind": str(slot.get("registry_source_kind", "") or ""),
                "source_dds_path": str(slot.get("source_dds_path", "") or ""),
                "preview_path": str(slot.get("preview_path", "") or ""),
                "source_channel": str(slot.get("source_channel", "") or ""),
                "parameter_name": str(slot.get("parameter_name", "") or ""),
                "shader_family": str(slot.get("shader_family", "") or ""),
                "disposition": str(slot.get("disposition", "") or ""),
                "note": str(slot.get("diagnostic", "") or ""),
            }
        )
    return diagnostics


def _material_contract_for_batch(
    batch: PreparedModelPreviewBatch,
    *,
    textures: Mapping[str, str],
    dds_textures: Mapping[str, object],
    combiner_metadata: Mapping[str, object],
) -> Dict[str, object]:
    shader_family = _material_contract_shader_family(batch)
    hints = _native_material_hints_for_batch(batch)
    slot_states = {
        slot_name: _texture_slot_state(slot_name, textures, dds_textures)
        for slot_name in _MATERIAL_CONTRACT_SLOTS
    }
    normalized_slot_states = _normalized_material_texture_slot_states(
        batch,
        textures=textures,
        dds_textures=dds_textures,
    )
    registry_decodes: list[Dict[str, object]] = []
    for slot_name, slot_state in slot_states.items():
        if str(slot_state.get("status", "") or "") == "missing":
            continue
        registry_decodes.append(
            dict(
                decode_crimson_texture_binding(
                    shader_family=str(slot_state.get("shader_family", "") or shader_family),
                    parameter_name=str(slot_state.get("parameter_name", "") or ""),
                    source_path=str(slot_state.get("source_dds_path", "") or slot_state.get("preview_path", "") or ""),
                    slot_name=slot_name,
                    semantic_subtype=str(slot_state.get("semantic_subtype", "") or ""),
                    packed_channels=tuple(slot_state.get("packed_channels", ()) or ()) if isinstance(slot_state.get("packed_channels", ()), Sequence) and not isinstance(slot_state.get("packed_channels", ()), (str, bytes, bytearray)) else (),
                    layer_channel=str(slot_state.get("layer_channel", "") or ""),
                    blend_flags=tuple(slot_state.get("blend_flags", ()) or ()) if isinstance(slot_state.get("blend_flags", ()), Sequence) and not isinstance(slot_state.get("blend_flags", ()), (str, bytes, bytearray)) else (),
                    sidecar_kind=str(slot_state.get("sidecar_kind", "") or ""),
                    parameter_declared_by=str(slot_state.get("parameter_declared_by", "") or ""),
                )
            )
        )
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        registry_decodes.append(
            dict(
                decode_crimson_texture_binding(
                    shader_family=str(getattr(texture_input, "shader_family", "") or shader_family),
                    parameter_name=str(getattr(texture_input, "parameter_name", "") or ""),
                    source_path=str(getattr(texture_input, "source_dds_path", "") or getattr(texture_input, "source_texture_path", "") or getattr(texture_input, "preview_texture_path", "") or ""),
                    slot_name=str(getattr(texture_input, "slot_kind", "") or "material"),
                    semantic_subtype=str(getattr(texture_input, "semantic_subtype", "") or ""),
                    packed_channels=tuple(getattr(texture_input, "packed_channels", ()) or ()),
                    layer_channel=str(getattr(texture_input, "layer_channel", "") or ""),
                    blend_flags=tuple(getattr(texture_input, "blend_flags", ()) or ()),
                    sidecar_kind=str(getattr(texture_input, "sidecar_kind", "") or ""),
                    parameter_declared_by=str(getattr(texture_input, "parameter_declared_by", "") or ""),
                )
            )
        )
    packed_channels = list(tuple(getattr(batch, "preview_material_texture_packed_channels", ()) or ()))
    normalized_channels = [str(channel or "").strip().lower() for channel in packed_channels]
    divergence_reasons: list[str] = []
    if normalized_channels and normalized_channels[:3] != ["ao", "roughness", "metallic"]:
        divergence_reasons.append("channel layout differs from default ARM")
    if not any(slot_states.get(slot, {}).get("status") != "missing" for slot in ("normal",)):
        divergence_reasons.append("missing source normal uses neutral fallback in CD runtime approximation")
    if not any(slot_states.get(slot, {}).get("status") != "missing" for slot in ("occlusion",)):
        divergence_reasons.append("missing source AO uses profile default in CD runtime approximation")
    if not any(slot_states.get(slot, {}).get("status") != "missing" for slot in ("roughness", "material")):
        divergence_reasons.append("missing source roughness uses factor/profile fallback")
    if not any(slot_states.get(slot, {}).get("status") != "missing" for slot in ("metalness", "material")):
        divergence_reasons.append("missing source metallic uses factor/profile fallback")
    if str(normalized_slot_states.get("opacity", {}).get("status", "") or "") != "missing":
        divergence_reasons.append("opacity texture recorded but not used as material response map")
    if str(normalized_slot_states.get("transmission", {}).get("status", "") or "") != "missing":
        divergence_reasons.append("transmission/volume recorded but native preview does not render true glass")
    slot_diagnostics = _material_slot_diagnostics(slot_states)
    normalized_slot_diagnostics = _material_slot_diagnostics(
        normalized_slot_states,
        _NORMALIZED_MATERIAL_CONTRACT_SLOTS,
    )
    present_slots = sum(1 for slot in slot_states.values() if str(slot.get("status", "")) != "missing")
    return {
        "schema_version": MATERIAL_CONTRACT_SCHEMA_VERSION,
        "shader_family": shader_family or "generic",
        "shader_registry": registry_manifest(),
        "registry_decodes": registry_decodes,
        "registry_policy": decode_profile_for_family(shader_family),
        "decode_policy": _material_decode_policy(shader_family),
        "decode_profile": _material_decode_profile(shader_family, hints, combiner_metadata, packed_channels),
        "pbr_scalar_hints": {
            "roughness": _safe_float(hints.get("roughness"), 0.55),
            "metalness": _safe_float(hints.get("metalness"), 0.0),
            "specular": _safe_float(hints.get("specular"), 0.08),
            "height_scale": _safe_float(hints.get("height_scale"), 0.0),
            "emissive_intensity": _safe_float(hints.get("emissive_intensity"), 0.0),
        },
        "material_hints": hints,
        "texture_slots": slot_states,
        "resolved_texture_slots": slot_states,
        "normalized_texture_slots": normalized_slot_states,
        "slot_diagnostics": slot_diagnostics,
        "normalized_slot_diagnostics": normalized_slot_diagnostics,
        "source_sidecar_paths": _material_sidecar_paths(batch),
        "packed_channels": packed_channels,
        "preview_modes": {
            "source_pbr_preview": {
                "authority": "gltf_source_textures_and_factors",
                "base": "baseColorTexture * baseColorFactor",
                "material": "metallicRoughnessTexture G/B plus occlusion/emissive inputs",
            },
            "cd_runtime_approx": {
                "authority": "generated_cd_profile_outputs",
                "profile": "arm_standard",
                "material": "_ma RGB=AO/roughness/metallic with neutral support fallbacks",
            },
        },
        "preview_divergence_reasons": divergence_reasons,
        "material_input_count": sum(
            1
            for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ())
            if isinstance(texture_input, PreviewMaterialTextureInput)
        ),
        "combiner_active": bool(combiner_metadata.get("active", False)),
        "combiner_outputs": list(tuple(combiner_metadata.get("outputs", ()) or ())),
        "status": "ok" if present_slots else "missing_textures",
        "fallback": "generic" if not shader_family else "",
    }


def _texture_quality_summary(
    *,
    textures: Mapping[str, str],
    dds_textures: Mapping[str, object],
    settings: ModelPreviewRenderSettings,
    high_quality_textures: bool,
) -> Dict[str, object]:
    support_cap = int(getattr(settings, "low_quality_texture_max_dimension", 2048) or 2048)
    base_cap = int(getattr(settings, "preview_texture_max_dimension", 16384) or 16384)
    slots = {
        slot_name: _texture_slot_state(slot_name, textures, dds_textures)
        for slot_name in _MATERIAL_CONTRACT_SLOTS
    }
    for slot_name, slot in slots.items():
        cap = base_cap if slot_name == "base" else support_cap
        slot["preview_cap"] = cap
        width = _safe_int(slot.get("source_width"), 0)
        height = _safe_int(slot.get("source_height"), 0)
        slot["source_exceeds_preview_cap"] = bool(max(width, height) > cap > 0)
        slot["safe_upscale_candidate"] = bool(slot_name == "base" and (slot.get("source_dds_path") or slot.get("preview_path")))
    low_resolution_base = False
    base = slots["base"]
    if base.get("source_width") and base.get("source_height"):
        low_resolution_base = max(_safe_int(base.get("source_width"), 0), _safe_int(base.get("source_height"), 0)) < 1024
    return {
        "schema_version": 1,
        "preview_texture_max_dimension": base_cap,
        "support_texture_max_dimension": support_cap,
        "high_quality_textures": bool(high_quality_textures),
        "slots": slots,
        "low_resolution_base": low_resolution_base,
        "upscale_handoff_policy": "opt-in visible/base textures only; technical maps preserved by default",
    }


def _combiner_generated_authoritative_albedo(combiner_metadata: Mapping[str, object]) -> bool:
    notes = tuple(str(note or "").strip().lower() for note in tuple(combiner_metadata.get("notes", ()) or ()))
    outputs = {str(output or "").strip().lower() for output in tuple(combiner_metadata.get("outputs", ()) or ())}
    return bool("albedo" in outputs and any(note.startswith("albedo synthesized") for note in notes))


def _normalized_material_key(value: object) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _byte4_channels(value: object) -> Tuple[float, float, float, float]:
    text = str(value or "").strip()
    if not text:
        return ()
    try:
        integer = int(text, 0)
    except (TypeError, ValueError, OverflowError):
        return ()
    integer = max(0, min(0xFFFFFFFF, integer))
    return tuple(((integer >> (8 * index)) & 0xFF) / 255.0 for index in range(4))  # type: ignore[return-value]


def _material_hex_color_rgb(value: object) -> Tuple[float, float, float]:
    text = str(value or "").strip()
    if not text:
        return ()
    if text.startswith("#"):
        text = text[1:]
    if len(text) not in {6, 8} or any(ch not in "0123456789abcdefABCDEF" for ch in text):
        return ()
    try:
        if len(text) == 8:
            # Crimson MaterialParameterColor sidecars use AARRGGBB for emissive color.
            return (
                int(text[2:4], 16) / 255.0,
                int(text[4:6], 16) / 255.0,
                int(text[6:8], 16) / 255.0,
            )
        return (
            int(text[0:2], 16) / 255.0,
            int(text[2:4], 16) / 255.0,
            int(text[4:6], 16) / 255.0,
        )
    except ValueError:
        return ()


def _native_material_hints_for_batch(batch: PreparedModelPreviewBatch) -> Dict[str, object]:
    inputs = tuple(
        texture_input
        for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ())
        if isinstance(texture_input, PreviewMaterialTextureInput)
    )
    shader_families = tuple(
        dict.fromkeys(
            str(getattr(texture_input, "shader_family", "") or "").strip()
            for texture_input in inputs
            if str(getattr(texture_input, "shader_family", "") or "").strip()
        )
    )
    roughness_values: list[float] = []
    metalness_values: list[float] = []
    specular_values: list[float] = []
    height_values: list[float] = []
    emissive_values: list[float] = []
    emissive_colors: list[str] = []
    for texture_input in inputs:
        for parameter in tuple(getattr(texture_input, "material_parameters", ()) or ()):
            key = _normalized_material_key(getattr(parameter, "parameter_name", ""))
            if not key:
                continue
            raw_value = str(getattr(parameter, "value", "") or "").strip()
            if "emissivecolor" in key and raw_value:
                emissive_colors.append(raw_value)
            numeric_value = getattr(parameter, "numeric_value", None)
            if numeric_value is not None:
                numeric = _clamp01(numeric_value)
                if "emissiveintensity" in key:
                    try:
                        emissive_values.append(max(0.0, min(32.0, float(numeric_value))))
                    except (TypeError, ValueError, OverflowError):
                        pass
                if "screenspacedisplacementscale" in key or "heightintensity" in key:
                    height_values.append(numeric if "heightintensity" in key else min(1.0, numeric * 8.0))
                if "specular" in key or "sheen" in key:
                    specular_values.append(numeric)
                if "roughness" in key:
                    roughness_values.append(numeric)
                if "metallic" in key or "metalness" in key:
                    metalness_values.append(numeric)
                continue
            channels = _byte4_channels(getattr(parameter, "value", ""))
            if not channels:
                continue
            channel_peak = max(channels)
            if "scratchroughness" in key or key.endswith("roughness"):
                roughness_values.append(channel_peak)
            if "scratchmetallic" in key or "metallic" in key or "metalness" in key:
                metalness_values.append(channel_peak)
            if "specular" in key:
                specular_values.append(channel_peak)

    roughness_hint = max(roughness_values) if roughness_values else 0.0
    metalness_hint = max(metalness_values) if metalness_values else 0.0
    specular_hint = max(specular_values) if specular_values else 0.0
    if metalness_hint > 0.02:
        specular_hint = max(specular_hint, 0.14 + (metalness_hint * 0.32))
    hints: Dict[str, object] = {
        "shader_families": list(shader_families[:4]),
        "roughness": round(float(max(0.0, min(1.0, roughness_hint))), 4),
        "metalness": round(float(max(0.0, min(1.0, metalness_hint * 0.42))), 4),
        "specular": round(float(max(0.0, min(1.0, specular_hint * 0.72))), 4),
        "height_scale": round(float(max(0.0, min(1.0, max(height_values) if height_values else 0.0))), 4),
        "emissive_intensity": round(float(max(0.0, min(32.0, max(emissive_values) if emissive_values else 0.0))), 4),
        "emissive_color": emissive_colors[0] if emissive_colors else "",
        "emissive_active": bool(emissive_values and max(emissive_values) > 0.0),
        "source": "sidecar_parameters" if any((roughness_values, metalness_values, specular_values, height_values, emissive_values)) else "",
    }
    overrides = getattr(batch, "preview_native_material_overrides", None)
    if isinstance(overrides, Mapping):
        override_hints = overrides.get("native_material_hints")
        if isinstance(override_hints, Mapping):
            for key in ("roughness", "metalness", "specular", "height_scale", "emissive_intensity"):
                if key in override_hints:
                    hints[key] = round(float(max(0.0, min(32.0 if key == "emissive_intensity" else 1.0, _safe_float(override_hints.get(key), _safe_float(hints.get(key), 0.0))))), 4)
            if str(override_hints.get("emissive_color", "") or "").strip():
                hints["emissive_color"] = str(override_hints.get("emissive_color", "") or "").strip()
        for key in ("roughness", "metalness", "specular", "height_scale", "emissive_intensity"):
            if key in overrides:
                hints[key] = round(float(max(0.0, min(32.0 if key == "emissive_intensity" else 1.0, _safe_float(overrides.get(key), _safe_float(hints.get(key), 0.0))))), 4)
        if str(overrides.get("emissive_color", "") or "").strip():
            hints["emissive_color"] = str(overrides.get("emissive_color", "") or "").strip()
        if any(key in overrides for key in ("roughness", "metalness", "specular", "height_scale", "emissive_intensity", "emissive_color")) or isinstance(override_hints, Mapping):
            hints["source"] = "native_material_overrides"
            hints["emissive_active"] = bool(_safe_float(hints.get("emissive_intensity"), 0.0) > 0.0)
    return hints


def _slot_has_resolved_texture(
    textures: Mapping[str, str],
    dds_textures: Mapping[str, object],
    slot_name: str,
) -> bool:
    slot = str(slot_name or "").strip().lower()
    if str(textures.get(slot, "") or "").strip():
        return True
    entry = dds_textures.get(slot)
    return bool(
        isinstance(entry, Mapping)
        and entry.get("available")
        and str(entry.get("source_path", "") or "").strip()
    )


def _batch_has_explicit_metalness_slot(batch: PreparedModelPreviewBatch) -> bool:
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        slot_kind = str(getattr(texture_input, "slot_kind", "") or "").strip().lower()
        semantic_type = str(getattr(texture_input, "semantic_type", "") or "").strip().lower()
        semantic_subtype = str(getattr(texture_input, "semantic_subtype", "") or "").strip().lower()
        parameter_key = _normalized_material_key(getattr(texture_input, "parameter_name", ""))
        if slot_kind in {"metal", "metallic", "metalness"}:
            return True
        if semantic_type in {"metal", "metallic", "metalness"} or semantic_subtype in {
            "metal",
            "metallic",
            "metalness",
            "metallic_roughness",
            "gltf_metallic_roughness",
        }:
            return True
        if ("metallic" in parameter_key or "metalness" in parameter_key) and "colorblendingmask" not in parameter_key:
            return True
        for parameter in tuple(getattr(texture_input, "material_parameters", ()) or ()):
            parameter_name = _normalized_material_key(getattr(parameter, "parameter_name", ""))
            if ("metallic" in parameter_name or "metalness" in parameter_name) and "colorblendingmask" not in parameter_name:
                return True
    return False


def _material_input_descriptor(batch: PreparedModelPreviewBatch) -> str:
    parts: list[str] = [
        str(getattr(batch, "material_name", "") or ""),
        str(getattr(batch, "texture_name", "") or ""),
        str(getattr(batch, "preview_sidecar_shader_family", "") or ""),
        str(getattr(batch, "preview_sidecar_material_primitive", "") or ""),
        str(getattr(batch, "preview_material_texture_name", "") or ""),
        str(getattr(batch, "preview_material_texture_type", "") or ""),
        str(getattr(batch, "preview_material_texture_subtype", "") or ""),
        " ".join(str(value or "") for value in tuple(getattr(batch, "preview_material_texture_packed_channels", ()) or ())),
    ]
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        parts.extend(
            [
                texture_input.slot_kind,
                texture_input.parameter_name,
                texture_input.source_texture_path,
                texture_input.source_dds_path,
                texture_input.texture_name,
                texture_input.semantic_type,
                texture_input.semantic_subtype,
                " ".join(texture_input.packed_channels),
                texture_input.material_name,
                texture_input.part_name,
                texture_input.shader_family,
                texture_input.layer_role,
                texture_input.layer_channel,
                " ".join(texture_input.blend_flags),
            ]
        )
    return " ".join(part.replace("\\", "/") for part in parts if str(part or "").strip()).lower()


def _descriptor_contains_token(descriptor: str, token: str) -> bool:
    token = str(token or "").strip().lower()
    if not token:
        return False
    start = 0
    while True:
        index = descriptor.find(token, start)
        if index < 0:
            return False
        end = index + len(token)
        left_boundary = index == 0 or not descriptor[index - 1].isalnum()
        right_boundary = end >= len(descriptor) or not descriptor[end].isalnum()
        if left_boundary and right_boundary:
            return True
        start = end


def _preview_tint_color_visible(color: Sequence[object]) -> bool:
    values = [_safe_float(value, 1.0) for value in tuple(color or ())[:3]]
    if len(values) < 3:
        return False
    return max(values) - min(values) > 0.055 or abs(max(values) - 1.0) > 0.08


def _preview_tint_color_score(color: Sequence[object]) -> float:
    values = [_safe_float(value, 1.0) for value in tuple(color or ())[:3]]
    if len(values) < 3 or not _preview_tint_color_visible(values):
        return -1.0
    luma = values[0] * 0.299 + values[1] * 0.587 + values[2] * 0.114
    return (max(values) - min(values)) * 1.60 + luma * 0.25 + 0.35


def _descriptor_prefers_sidecar_tint(source_path: object, descriptor: str) -> bool:
    text = " ".join((str(source_path or ""), str(descriptor or ""))).replace("\\", "/").lower()
    return _source_or_descriptor_has_weapon_surface(source_path, descriptor) or any(
        _descriptor_contains_token(text, token)
        for token in ("flag", "banner", "ribbon", "sash", "tassel", "fringe", "flap")
    )


def _descriptor_has_local_strong_nonmetal_token(descriptor: str) -> bool:
    text = str(descriptor or "").replace("\\", "/").lower()
    return any(
        _descriptor_contains_token(text, token)
        for token in (
            "cloth",
            "fabric",
            "flag",
            "banner",
            "tassel",
            "fringe",
            "ribbon",
            "sash",
            "rope",
            "leather",
            "hide",
            "strap",
            "belt",
            "grip",
            "wrap",
            "handle",
            "wood",
            "stick",
            "shaft",
            "haft",
            "skin",
            "hair",
            "fur",
        )
    )


def _batch_weapon_masked_base_tint_should_stay_masked(batch: PreparedModelPreviewBatch, *, source_path: object = "") -> bool:
    descriptor = _material_input_descriptor(batch)
    if not _source_or_descriptor_has_weapon_surface(source_path, descriptor):
        return False
    local_descriptor = " ".join(
        str(value or "")
        for value in (
            getattr(batch, "material_name", ""),
            getattr(batch, "texture_name", ""),
            getattr(batch, "preview_role", ""),
        )
    )
    if _descriptor_has_local_strong_nonmetal_token(local_descriptor):
        return False
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        slot_kind = str(getattr(texture_input, "slot_kind", "") or "").strip().lower()
        if slot_kind and slot_kind != "base":
            continue
        channel = str(getattr(texture_input, "layer_channel", "") or "").strip().lower()
        parameter_key = _normalized_material_key(getattr(texture_input, "parameter_name", ""))
        if channel in {"g", "b", "a"}:
            return True
        if any(token in parameter_key for token in ("diffusetextureg", "diffusetextureb", "diffusetexturea", "diffusemaskg", "diffusemaskb", "diffusemaska")):
            return True
    return False


def _sidecar_preview_texture_tint_for_batch(batch: PreparedModelPreviewBatch, *, source_path: object = "") -> Tuple[float, float, float]:
    descriptor = _material_input_descriptor(batch)
    if not _descriptor_prefers_sidecar_tint(source_path, descriptor):
        return ()
    if _batch_weapon_masked_base_tint_should_stay_masked(batch, source_path=source_path):
        return ()
    best_color: Tuple[float, float, float] = ()
    best_score = -1.0
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        input_descriptor = " ".join(
            str(value or "")
            for value in (
                getattr(texture_input, "slot_kind", ""),
                getattr(texture_input, "parameter_name", ""),
                getattr(texture_input, "material_name", ""),
                getattr(texture_input, "texture_name", ""),
                getattr(texture_input, "layer_role", ""),
                getattr(texture_input, "layer_channel", ""),
            )
        ).lower()
        for parameter in tuple(getattr(texture_input, "material_parameters", ()) or ()):
            parameter_name = _normalized_material_key(getattr(parameter, "parameter_name", ""))
            if not any(token in parameter_name for token in ("tintcolor", "dyeingdetaillayercolormask", "layercolor", "basecolor")):
                continue
            color = tuple(_safe_float(value, 1.0) for value in tuple(getattr(parameter, "color_value", ()) or ())[:3])
            if len(color) < 3:
                continue
            score = _preview_tint_color_score(color)
            if "dyeingdetail" in parameter_name or "detail" in input_descriptor:
                score += 0.18
            if "grime" in input_descriptor:
                score += 0.06
            if score > best_score:
                best_score = score
                best_color = tuple(max(0.02, min(1.35, float(value))) for value in color)
    return best_color if best_score > 0.0 else ()


def _preview_texture_family_key(value: object) -> str:
    name = Path(str(value or "").replace("\\", "/")).name.lower()
    stem = name.rsplit(".", 1)[0]
    for suffix in ("_disp", "_ma", "_mg", "_sp", "_m", "_n", "_o", "_dr"):
        if len(stem) > len(suffix) and stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def _preview_texture_family_key_is_specific_material_response(key: str) -> bool:
    normalized = str(key or "").strip().lower()
    if not normalized:
        return False
    if "texturelayer" in normalized:
        return False
    if "common" in normalized or "default" in normalized:
        return False
    if normalized.startswith("cd_temp") or "temp" in normalized:
        return False
    return True


def _preview_material_family_keys(source_path: object, batch: PreparedModelPreviewBatch) -> Tuple[str, ...]:
    keys = [
        _preview_texture_family_key(source_path),
        _preview_texture_family_key(getattr(batch, "material_name", "")),
        _preview_texture_family_key(getattr(batch, "texture_name", "")),
        _preview_texture_family_key(getattr(batch, "editor_part_name", "")),
    ]
    return tuple(dict.fromkeys(key for key in keys if key))


def _preview_material_keys_match(candidate_key: str, family_key: str) -> bool:
    candidate = str(candidate_key or "").strip().lower()
    family = str(family_key or "").strip().lower()
    if not candidate or not family:
        return False
    return candidate == family or candidate in family or family in candidate


def _batch_has_authoritative_family_material_response(batch: PreparedModelPreviewBatch, *, source_path: object = "") -> bool:
    family_keys = _preview_material_family_keys(source_path, batch)
    if not family_keys:
        return False
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        authority_text = " ".join(
            (
                str(getattr(texture_input, "sidecar_kind", "") or ""),
                str(getattr(texture_input, "parameter_declared_by", "") or ""),
                str(getattr(texture_input, "material_output_quality", "") or ""),
                str(getattr(texture_input, "confidence", "") or ""),
            )
        ).lower()
        if "exact" not in authority_text and "sidecar" not in authority_text and "technique" not in authority_text:
            continue
        input_kind = _input_texture_kind(texture_input)
        parameter_key = _normalized_material_key(getattr(texture_input, "parameter_name", ""))
        packed = " ".join(str(channel or "").lower() for channel in tuple(getattr(texture_input, "packed_channels", ()) or ()))
        source = (
            str(getattr(texture_input, "source_dds_path", "") or "")
            or str(getattr(texture_input, "source_texture_path", "") or "")
            or str(getattr(texture_input, "preview_texture_path", "") or "")
            or str(getattr(texture_input, "texture_name", "") or "")
        )
        source_text = source.lower()
        material_response = (
            input_kind in {"packed_material", "material", "specular", "roughness", "metalness", "glossiness", "specular_glossiness"}
            or _batch_has_explicit_metalness_slot(batch)
            or (parameter_key == "colorblendingmasktexture" and "_ma" in source_text)
            or ("occlusion" in packed and "roughness" in packed and ("metalness" in packed or "metallic" in packed))
        )
        if not material_response:
            continue
        texture_family_key = _preview_texture_family_key(source)
        if not _preview_texture_family_key_is_specific_material_response(texture_family_key):
            continue
        if any(_preview_material_keys_match(texture_family_key, family_key) for family_key in family_keys):
            return True
    return False


def _source_or_descriptor_has_armor_equipment(source_path: object, descriptor: str) -> bool:
    text = " ".join((str(source_path or ""), str(descriptor or ""))).replace("\\", "/").lower()
    return (
        "/armor/" in text
        or "/13_hel/" in text
        or "_hel_" in text
        or any(_descriptor_contains_token(text, token) for token in ("helmet", "helm", "armor", "armour", "plate"))
    )


def _source_or_descriptor_has_weapon_surface(source_path: object, descriptor: str) -> bool:
    text = " ".join((str(source_path or ""), str(descriptor or ""))).replace("\\", "/").lower()
    return (
        "/weapon/" in text
        or "/2_twohandweapon/" in text
        or any(_descriptor_contains_token(text, token) for token in ("weapon", "sword", "blade", "guard", "hilt", "pommel"))
    )


def _resolved_batch_material_category(
    batch: PreparedModelPreviewBatch,
    *,
    textures: Mapping[str, str],
    dds_textures: Mapping[str, object],
    material_hints: Mapping[str, object],
    material_contract: Mapping[str, object],
    source_path: object = "",
) -> Tuple[str, float]:
    family = str(material_contract.get("shader_family", "") or "").strip().lower()
    if family == "skin":
        return "skin", 0.90
    if family == "hair":
        return "hair", 0.90
    if family in {"cloth", "cloth_v2"}:
        return "cloth", 0.84

    descriptor = _material_input_descriptor(batch)
    local_descriptor = " ".join(
        part.replace("\\", "/")
        for part in (
            str(getattr(batch, "material_name", "") or ""),
            str(getattr(batch, "preview_role", "") or ""),
        )
        if part.strip()
    ).lower()
    nonmetal_tokens = {
        "skin",
        "hair",
        "cloth",
        "fabric",
        "flag",
        "banner",
        "vest",
        "tassel",
        "fringe",
        "ribbon",
        "sash",
        "rope",
        "cloak",
        "cape",
        "skirt",
        "dress",
        "mantle",
        "robe",
        "flap",
        "leather",
        "strap",
        "belt",
        "grip",
        "wrap",
        "handle",
        "wood",
        "stick",
        "shaft",
        "haft",
        "glass",
        "gem",
        "jewel",
        "crystal",
        "diamond",
        "ruby",
        "sapphire",
        "emerald",
        "stone",
        "rock",
        "ceramic",
        "eye",
        "iris",
        "pupil",
        "cornea",
        "tooth",
        "teeth",
        "fur",
        "brow",
        "eyebrow",
        "lash",
        "eyelash",
        "face",
        "nonmetal",
        "non_metal",
        "non-metal",
        "non metal",
    }
    local_nonmetal_tokens = nonmetal_tokens | {"hide", "timber"}
    local_strong_nonmetal_descriptor = any(
        _descriptor_contains_token(local_descriptor, token)
        for token in local_nonmetal_tokens
    )
    local_metal_tokens = {
        "metal",
        "steel",
        "iron",
        "blade",
        "guard",
        "hilt",
        "pommel",
        "plate",
        "silver",
        "gold",
        "copper",
        "bronze",
        "brass",
        "chrome",
    }
    if (
        any(_descriptor_contains_token(local_descriptor, token) for token in local_metal_tokens)
        and not local_strong_nonmetal_descriptor
    ):
        return "metal", 0.90 if _batch_has_explicit_metalness_slot(batch) else 0.78
    if any(_descriptor_contains_token(descriptor, token) for token in ("leather", "hide", "strap", "belt", "grip", "wrap", "handle")):
        return "leather", 0.72
    if any(_descriptor_contains_token(descriptor, token) for token in ("wood", "timber", "stick", "shaft", "haft")):
        return "wood", 0.72
    if any(_descriptor_contains_token(descriptor, token) for token in ("glass", "crystal")):
        return "glass", 0.72
    if any(_descriptor_contains_token(descriptor, token) for token in ("gem", "jewel", "diamond", "ruby", "sapphire", "emerald")):
        return "gem", 0.72
    if any(_descriptor_contains_token(descriptor, token) for token in ("stone", "rock", "ceramic")):
        return "stone", 0.72
    if any(_descriptor_contains_token(descriptor, token) for token in ("eye", "iris", "pupil", "cornea")):
        return "eye", 0.76
    if any(_descriptor_contains_token(descriptor, token) for token in ("tooth", "teeth")):
        return "tooth", 0.76
    if any(_descriptor_contains_token(descriptor, token) for token in ("hair", "fur", "beard", "brow", "eyebrow", "lash", "eyelash")):
        return "hair", 0.76

    packed_text = " ".join(str(value or "") for value in tuple(material_contract.get("packed_channels", ()) or ())).lower()
    strong_nonmetal_descriptor = any(_descriptor_contains_token(descriptor, token) for token in nonmetal_tokens)
    if any(
        _descriptor_contains_token(descriptor, token)
        for token in ("cloth", "fabric", "flag", "banner", "vest", "tassel", "fringe", "ribbon", "sash", "rope", "cloak", "cape", "skirt", "dress", "mantle", "robe", "flap")
    ):
        return "cloth", 0.72
    explicit_metal = bool(
        not strong_nonmetal_descriptor
        and (
            _safe_float(material_hints.get("metalness"), 0.0) >= 0.16
            and str(material_hints.get("source", "") or "") == "native_material_overrides"
        )
    )
    strong_metal_tokens = {
        "metal",
        "steel",
        "iron",
        "blade",
        "plate",
    }
    color_metal_tokens = {
        "silver",
        "gold",
        "copper",
        "bronze",
        "brass",
        "chrome",
    }
    strong_token_metal = any(_descriptor_contains_token(descriptor, token) for token in strong_metal_tokens) and not any(
        _descriptor_contains_token(descriptor, token) for token in nonmetal_tokens
    )
    color_token_metal = any(_descriptor_contains_token(descriptor, token) for token in color_metal_tokens) and not any(
        _descriptor_contains_token(descriptor, token) for token in nonmetal_tokens
    )
    if explicit_metal:
        return "metal", 0.92
    if (
        _source_or_descriptor_has_armor_equipment(source_path, descriptor)
        and _batch_has_authoritative_family_material_response(batch, source_path=source_path)
        and not local_strong_nonmetal_descriptor
        and not strong_nonmetal_descriptor
    ):
        return "metal", 0.90
    if (
        _source_or_descriptor_has_weapon_surface(source_path, descriptor)
        and _batch_has_authoritative_family_material_response(batch, source_path=source_path)
        and not local_strong_nonmetal_descriptor
        and (
            any(_descriptor_contains_token(local_descriptor, token) for token in local_metal_tokens)
            or _batch_has_explicit_metalness_slot(batch)
            or _safe_float(material_hints.get("metalness"), 0.0) >= 0.35
        )
    ):
        return "metal", 0.90
    if strong_token_metal:
        return "metal", 0.90 if _batch_has_explicit_metalness_slot(batch) else 0.78
    if color_token_metal:
        return "metal", 0.62
    return "generic", 0.35


def _resolved_batch_material_category_reason(
    category: str,
    batch: PreparedModelPreviewBatch,
    *,
    textures: Mapping[str, str],
    dds_textures: Mapping[str, object],
    material_hints: Mapping[str, object],
    material_contract: Mapping[str, object],
    source_path: object = "",
) -> str:
    descriptor = _material_input_descriptor(batch)
    if category == "metal":
        if (
            _source_or_descriptor_has_armor_equipment(source_path, descriptor)
            and _batch_has_authoritative_family_material_response(batch, source_path=source_path)
        ):
            return "metal:armor_family_material_response"
        if (
            _source_or_descriptor_has_weapon_surface(source_path, descriptor)
            and _batch_has_authoritative_family_material_response(batch, source_path=source_path)
        ):
            return "metal:weapon_family_material_response"
        for token in ("gold", "silver", "copper", "bronze", "brass", "chrome"):
            if _descriptor_contains_token(descriptor, token):
                return "metal:color_token"
        if (
            _safe_float(material_hints.get("metalness"), 0.0) >= 0.16
            or _slot_has_resolved_texture(textures, dds_textures, "metalness")
            or _batch_has_explicit_metalness_slot(batch)
        ):
            return "metal:material_channel"
        return "metal:material_or_part_token"
    if category in {"leather", "wood", "cloth", "skin", "hair", "stone", "tooth"}:
        return f"nonmetal:{category}_token"
    if category in {"glass", "gem", "eye"}:
        return f"glossy_nonmetal:{category}_token"
    return "generic:no_strong_material_token"


def _resolved_batch_material_finish(category: str, material_hints: Mapping[str, object]) -> str:
    normalized = str(category or "").strip().lower()
    if normalized != "metal":
        return normalized or "generic"
    roughness = _safe_float(material_hints.get("roughness"), 0.55)
    metalness = _safe_float(material_hints.get("metalness"), 0.0)
    specular = _safe_float(material_hints.get("specular"), 0.08)
    if roughness <= 0.34 or specular >= 0.42 or metalness >= 0.68:
        return "glossy_metal"
    if roughness >= 0.68 and specular <= 0.18:
        return "dull_metal"
    return "metal"


def _nonmetal_material_scalar_limits(category: str) -> Tuple[float, float, float]:
    normalized = str(category or "").strip().lower()
    limits = {
        "cloth": (0.0, 0.28, 0.48),
        "leather": (0.0, 0.36, 0.38),
        "wood": (0.0, 0.30, 0.44),
        "skin": (0.0, 0.34, 0.30),
        "hair": (0.0, 0.46, 0.36),
        "stone": (0.0, 0.24, 0.58),
        "tooth": (0.0, 0.26, 0.42),
    }
    return limits.get(normalized, (1.0, 1.0, 0.04))


def _apply_nonmetal_material_scalar_limits(
    material_hints: Dict[str, object],
    material_contract: Mapping[str, object],
    category: str,
) -> bool:
    if str(category or "").strip().lower() not in {"cloth", "leather", "wood", "skin", "hair", "stone", "tooth"}:
        return False
    metal_cap, spec_cap, roughness_floor = _nonmetal_material_scalar_limits(category)
    old_metalness = _safe_float(material_hints.get("metalness"), 0.0)
    old_specular = _safe_float(material_hints.get("specular"), 0.08)
    old_roughness = _safe_float(material_hints.get("roughness"), 0.55)
    new_metalness = min(old_metalness, metal_cap)
    new_specular = min(old_specular, spec_cap)
    new_roughness = max(old_roughness, roughness_floor)
    material_hints["metalness"] = round(float(new_metalness), 4)
    material_hints["specular"] = round(float(new_specular), 4)
    material_hints["roughness"] = round(float(new_roughness), 4)
    pbr_hints = material_contract.get("pbr_scalar_hints") if isinstance(material_contract, Mapping) else None
    if isinstance(pbr_hints, dict):
        pbr_hints["metalness"] = material_hints["metalness"]
        pbr_hints["specular"] = material_hints["specular"]
        pbr_hints["roughness"] = material_hints["roughness"]
    decode_profile = material_contract.get("decode_profile") if isinstance(material_contract, Mapping) else None
    if isinstance(decode_profile, dict):
        profile_hints = decode_profile.get("pbr_scalar_hints")
        if isinstance(profile_hints, dict):
            profile_hints["metalness"] = material_hints["metalness"]
            profile_hints["specular"] = material_hints["specular"]
            profile_hints["roughness"] = material_hints["roughness"]
    return bool(
        new_metalness != old_metalness
        or new_specular != old_specular
        or new_roughness != old_roughness
    )


def _effective_emissive_intensity(
    material_hints: Mapping[str, object],
    *,
    textures: Mapping[str, str],
    dds_textures: Mapping[str, object],
) -> float:
    hinted = _safe_float(material_hints.get("emissive_intensity"), 0.0)
    if hinted > 0.0:
        return hinted
    if _slot_has_resolved_texture(textures, dds_textures, "emissive"):
        return 4.0
    return 0.0


def _material_input_to_dict(texture_input: PreviewMaterialTextureInput) -> Dict[str, object]:
    def to_jsonable(value: object) -> object:
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return {
                field_info.name: to_jsonable(getattr(value, field_info.name))
                for field_info in dataclasses.fields(value)
            }
        if isinstance(value, tuple):
            return [to_jsonable(item) for item in value]
        if isinstance(value, list):
            return [to_jsonable(item) for item in value]
        if isinstance(value, dict):
            return {str(key): to_jsonable(item) for key, item in value.items()}
        return value

    data = {
        field_info.name: to_jsonable(getattr(texture_input, field_info.name))
        for field_info in dataclasses.fields(PreviewMaterialTextureInput)
    }
    registry_decode = decode_crimson_texture_binding(
        shader_family=str(getattr(texture_input, "shader_family", "") or ""),
        parameter_name=str(getattr(texture_input, "parameter_name", "") or ""),
        source_path=str(getattr(texture_input, "source_dds_path", "") or getattr(texture_input, "source_texture_path", "") or getattr(texture_input, "preview_texture_path", "") or ""),
        slot_name=str(getattr(texture_input, "slot_kind", "") or "material"),
        semantic_subtype=str(getattr(texture_input, "semantic_subtype", "") or ""),
        packed_channels=tuple(getattr(texture_input, "packed_channels", ()) or ()),
        layer_channel=str(getattr(texture_input, "layer_channel", "") or ""),
        blend_flags=tuple(getattr(texture_input, "blend_flags", ()) or ()),
        sidecar_kind=str(getattr(texture_input, "sidecar_kind", "") or ""),
        parameter_declared_by=str(getattr(texture_input, "parameter_declared_by", "") or ""),
    )
    data["authority"] = str(registry_decode.get("authority", "") or AUTHORITY_GUESS)
    data["disposition"] = str(registry_decode.get("disposition", "") or "")
    data["registry_source_kind"] = str(registry_decode.get("source_kind", "") or "")
    data["promoted_channels"] = dict(registry_decode.get("promoted_channels", {}) or {})
    return data


def _manifest_material_diagnostics(material_contract: Mapping[str, object]) -> list[Dict[str, object]]:
    diagnostics: list[Dict[str, object]] = [
        dict(item)
        for item in tuple(material_contract.get("slot_diagnostics", ()) or ())
        if isinstance(item, Mapping)
    ]
    native_slots = set(_MATERIAL_CONTRACT_SLOTS)
    for item in tuple(material_contract.get("normalized_slot_diagnostics", ()) or ()):
        if not isinstance(item, Mapping):
            continue
        slot_name = str(item.get("slot", "") or "")
        status = str(item.get("status", "") or "")
        if status == "missing":
            continue
        if slot_name in native_slots and status in {"direct_dds", "preview_png"}:
            continue
        diagnostics.append(dict(item))
    return diagnostics


def _input_source_label(texture_input: PreviewMaterialTextureInput) -> str:
    return (
        str(getattr(texture_input, "source_dds_path", "") or "")
        or str(getattr(texture_input, "source_texture_path", "") or "")
        or str(getattr(texture_input, "preview_texture_path", "") or "")
        or str(getattr(texture_input, "texture_name", "") or "")
    )


def _input_is_true_base_color(texture_input: PreviewMaterialTextureInput) -> bool:
    parameter_key = _normalized_material_key(getattr(texture_input, "parameter_name", ""))
    if parameter_key != "basecolortexture":
        return False
    source = _input_source_label(texture_input).lower()
    if "texturelayer" in source or "common_default" in source or "default_overlay" in source or "overlay_old" in source:
        return False
    decode = decode_crimson_texture_binding(
        shader_family=str(getattr(texture_input, "shader_family", "") or ""),
        parameter_name=str(getattr(texture_input, "parameter_name", "") or ""),
        source_path=_input_source_label(texture_input),
        slot_name=str(getattr(texture_input, "slot_kind", "") or "base"),
        semantic_subtype=str(getattr(texture_input, "semantic_subtype", "") or ""),
        packed_channels=tuple(getattr(texture_input, "packed_channels", ()) or ()),
        layer_channel=str(getattr(texture_input, "layer_channel", "") or ""),
        blend_flags=tuple(getattr(texture_input, "blend_flags", ()) or ()),
        sidecar_kind=str(getattr(texture_input, "sidecar_kind", "") or ""),
        parameter_declared_by=str(getattr(texture_input, "parameter_declared_by", "") or ""),
    )
    return str(decode.get("disposition", "") or "") == "promoted"


def _masked_texturelayer_records(batch: PreparedModelPreviewBatch) -> list[Dict[str, object]]:
    records: list[Dict[str, object]] = []
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        source = _input_source_label(texture_input)
        parameter_name = str(getattr(texture_input, "parameter_name", "") or "")
        parameter_key = _normalized_material_key(parameter_name)
        decode = decode_crimson_texture_binding(
            shader_family=str(getattr(texture_input, "shader_family", "") or ""),
            parameter_name=parameter_name,
            source_path=source,
            slot_name=str(getattr(texture_input, "slot_kind", "") or "material"),
            semantic_subtype=str(getattr(texture_input, "semantic_subtype", "") or ""),
            packed_channels=tuple(getattr(texture_input, "packed_channels", ()) or ()),
            layer_channel=str(getattr(texture_input, "layer_channel", "") or ""),
            blend_flags=tuple(getattr(texture_input, "blend_flags", ()) or ()),
            sidecar_kind=str(getattr(texture_input, "sidecar_kind", "") or ""),
            parameter_declared_by=str(getattr(texture_input, "parameter_declared_by", "") or ""),
        )
        disposition = str(decode.get("disposition", "") or "")
        source_kind = str(decode.get("source_kind", "") or "")
        is_layer_color = (
            "texturelayer" in source.lower()
            or any(token in parameter_key for token in ("grimediffuse", "detaildiffuse", "damageblendingdiffuse"))
        )
        if not is_layer_color and disposition not in {"layer_only", "layer_material_response"}:
            continue
        if disposition not in {"layer_only", "layer_material_response", "layer_flow", "layer_direction"}:
            continue
        records.append(
            {
                "code": "texturelayer_kept_masked",
                "parameter_name": parameter_name,
                "source_path": source,
                "layer_channel": str(decode.get("layer_channel", "") or getattr(texture_input, "layer_channel", "") or ""),
                "disposition": disposition,
                "source_kind": source_kind,
                "authority": str(decode.get("authority", "") or AUTHORITY_GUESS),
            }
        )
    return records


def _material_base_policy_for_batch(
    batch: PreparedModelPreviewBatch,
    *,
    material_category: str,
    combiner_metadata: Mapping[str, object],
) -> Dict[str, object]:
    notes = " ".join(
        str(note or "")
        for note in (
            tuple(combiner_metadata.get("notes", ()) or ())
            + (str(combiner_metadata.get("base_note", "") or ""),)
        )
    )
    masked_records = _masked_texturelayer_records(batch)
    has_true_base = any(
        _input_is_true_base_color(texture_input)
        for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ())
        if isinstance(texture_input, PreviewMaterialTextureInput)
    )
    neutral_metal = "neutral_metal_base_synthesized" in notes
    no_reliable = bool(
        "no_reliable_full_base_albedo" in notes
        or (str(material_category or "").strip().lower() == "metal" and masked_records and not has_true_base)
    )
    diagnostics: list[Dict[str, object]] = []
    if neutral_metal:
        diagnostics.append(
            {
                "code": "neutral_metal_base_synthesized",
                "reason": "weapon/armor metal had no reliable full base albedo; neutral base seeded from vertex/material/category hints",
                "authority": AUTHORITY_AUTHORITATIVE,
            }
        )
    diagnostics.extend(masked_records)
    if no_reliable:
        diagnostics.append(
            {
                "code": "no_reliable_full_base_albedo",
                "reason": "Crimson texturelayer diffuse inputs were retained as masked layer contribution, not whole-surface albedo",
                "authority": AUTHORITY_AUTHORITATIVE if neutral_metal else AUTHORITY_SIDECAR,
            }
        )
    policy = "true_base_color"
    if neutral_metal:
        policy = "neutral_metal_synthesized"
    elif no_reliable:
        policy = "masked_layers_no_full_base"
    return {
        "schema_version": 1,
        "policy": policy,
        "neutral_metal_base_synthesized": neutral_metal,
        "texturelayer_kept_masked": masked_records,
        "no_reliable_full_base_albedo": no_reliable,
        "true_base_color_texture_present": has_true_base,
        "diagnostics": diagnostics,
    }


_NATIVE_MATERIAL_OVERRIDE_KEYS = frozenset(
    {
        "alpha_threshold",
        "base_tint_strength",
        "height_amount",
        "height_scale",
        "material_analysis",
        "material_category",
        "material_category_confidence",
        "material_category_reason",
        "material_finish",
        "material_layers",
        "material_response_disposition",
        "material_response_promoted",
        "material_shader_family",
        "metalness",
        "native_base_quality",
        "native_material_hints",
        "normal_strength",
        "primary_material_layer",
        "roughness",
        "specular",
    }
)


def _jsonable_native_material_override(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable_native_material_override(item)
            for key, item in value.items()
            if isinstance(key, (str, int, float, bool))
        }
    if isinstance(value, (tuple, list)):
        return [_jsonable_native_material_override(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _native_material_overrides_for_batch(batch: PreparedModelPreviewBatch) -> Dict[str, object]:
    raw_overrides = getattr(batch, "preview_native_material_overrides", None)
    if not isinstance(raw_overrides, Mapping):
        return {}
    return {
        str(key): _jsonable_native_material_override(value)
        for key, value in raw_overrides.items()
        if str(key) in _NATIVE_MATERIAL_OVERRIDE_KEYS
    }


def _source_dds_for_preview_path(preview_path: str) -> str:
    raw = str(preview_path or "").strip()
    if not raw:
        return ""
    try:
        direct_source = Path(raw).expanduser()
        if direct_source.suffix.lower() == ".dds" and direct_source.is_file():
            return str(direct_source)
    except OSError:
        pass
    try:
        report = read_native_texture_report_sidecar(Path(raw))
    except Exception:
        return ""
    if not isinstance(report, Mapping):
        return ""
    source_path = dds_source_path_from_report(report)
    if not source_path:
        return ""
    try:
        source = Path(source_path).expanduser()
    except OSError:
        return ""
    return str(source) if source.is_file() else ""


def _dds_manifest_entry(
    source_path: str,
    *,
    slot_name: str,
    reason: str = "",
    inspect_cache: Optional[Dict[str, Dict[str, object]]] = None,
) -> Dict[str, object]:
    raw = str(source_path or "").strip()
    if not raw:
        return {}
    try:
        source = Path(raw).expanduser()
    except OSError:
        return {
            "slot": str(slot_name or ""),
            "source_path": raw,
            "available": False,
            "reason": "invalid DDS path",
        }
    if not source.is_file():
        return {
            "slot": str(slot_name or ""),
            "source_path": str(source),
            "available": False,
            "reason": reason or "DDS file missing",
        }
    cache_key = _source_file_stat_key(source)
    report: Dict[str, object]
    cached_report = inspect_cache.get(cache_key) if inspect_cache is not None else None
    if cached_report is not None:
        report = dict(cached_report)
    else:
        try:
            info = inspect_dds_native_path(source)
            report = dds_native_report_dict(source, info, backend="dds_native_manifest")
        except Exception as exc:
            return {
                "slot": str(slot_name or ""),
                "source_path": str(source),
                "available": False,
                "reason": f"DDS inspect failed: {exc}",
            }
        report.update(
            {
                "available": True,
                "direct_upload_candidate": bool(
                    report.get("direct_upload_candidate", False)
                    or report.get("supported_compressed", False)
                    or report.get("supported_uncompressed", False)
                ),
            }
        )
        if inspect_cache is not None:
            inspect_cache[cache_key] = dict(report)
    report.update(
        {
            "slot": str(slot_name or ""),
            "available": True,
            "direct_upload_candidate": bool(
                report.get("direct_upload_candidate", False)
                or report.get("supported_compressed", False)
                or report.get("supported_uncompressed", False)
            ),
        }
    )
    if reason:
        report["reason"] = reason
    compact = {
        key: value
        for key, value in report.items()
        if key not in {"mip_levels"}
    }
    return compact


def _dds_manifest_entry_is_native_usable(entry: object) -> bool:
    if not isinstance(entry, Mapping):
        return False
    if not bool(entry.get("available", False)):
        return False
    if not bool(entry.get("direct_upload_candidate", False)):
        return False
    source_path = str(entry.get("source_path", "") or "").strip()
    if not source_path:
        return False
    try:
        return Path(source_path).expanduser().is_file()
    except OSError:
        return False


def _dds_textures_for_batch(
    batch: PreparedModelPreviewBatch,
    *,
    inspect_cache: Optional[Dict[str, Dict[str, object]]] = None,
    include_support_slots: bool = True,
    material_input_kinds: Optional[set[str]] = None,
) -> Dict[str, object]:
    slots = {
        "base": str(getattr(batch, "preview_texture_dds_path", "") or "")
        or _source_dds_for_preview_path(str(getattr(batch, "preview_texture_path", "") or "")),
    }
    if include_support_slots:
        slots.update(
            {
                "normal": str(getattr(batch, "preview_normal_texture_dds_path", "") or "")
                or _source_dds_for_preview_path(str(getattr(batch, "preview_normal_texture_path", "") or "")),
                "material": str(getattr(batch, "preview_material_texture_dds_path", "") or "")
                or _source_dds_for_preview_path(str(getattr(batch, "preview_material_texture_path", "") or "")),
                "height": str(getattr(batch, "preview_height_texture_dds_path", "") or "")
                or _source_dds_for_preview_path(str(getattr(batch, "preview_height_texture_path", "") or "")),
            }
        )
    output: Dict[str, object] = {
        slot_name: _dds_manifest_entry(source_path, slot_name=slot_name, inspect_cache=inspect_cache)
        for slot_name, source_path in slots.items()
        if str(source_path or "").strip()
    }
    for slot_name, entry in list(output.items()):
        if not isinstance(entry, dict):
            continue
        registry_decode = decode_crimson_texture_binding(
            shader_family=str(getattr(batch, "preview_sidecar_shader_family", "") or ""),
            parameter_name="",
            source_path=str(entry.get("source_path", "") or ""),
            slot_name=slot_name,
        )
        entry["authority"] = AUTHORITY_AUTHORITATIVE if slot_name in {"base", "normal", "height"} else str(registry_decode.get("authority", "") or AUTHORITY_GUESS)
        entry["disposition"] = "promoted" if slot_name in {"base", "normal", "height"} else str(registry_decode.get("disposition", "") or "")
        entry["registry_source_kind"] = str(registry_decode.get("source_kind", "") or "")
    input_entries: list[Dict[str, object]] = []
    allowed_input_kinds = (
        None
        if material_input_kinds is None
        else {str(kind or "").strip().lower() for kind in set(material_input_kinds)}
    )
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        input_kind = _input_texture_kind(texture_input)
        if allowed_input_kinds is not None and input_kind not in allowed_input_kinds:
            continue
        source_path = str(getattr(texture_input, "source_dds_path", "") or "").strip()
        if not source_path:
            source_path = _source_dds_for_preview_path(str(getattr(texture_input, "preview_texture_path", "") or ""))
        if not source_path:
            continue
        slot_name = str(getattr(texture_input, "slot_kind", "") or "material").strip().lower() or "material"
        entry = _dds_manifest_entry(source_path, slot_name=slot_name, inspect_cache=inspect_cache)
        entry["parameter_name"] = str(getattr(texture_input, "parameter_name", "") or "")
        entry["semantic_type"] = str(getattr(texture_input, "semantic_type", "") or "")
        entry["semantic_subtype"] = str(getattr(texture_input, "semantic_subtype", "") or "")
        entry["material_name"] = str(getattr(texture_input, "material_name", "") or "")
        entry["shader_family"] = str(getattr(texture_input, "shader_family", "") or "")
        entry["shader_rule"] = str(getattr(texture_input, "shader_rule", "") or "")
        entry["sidecar_path"] = str(getattr(texture_input, "sidecar_path", "") or "")
        entry["sidecar_kind"] = str(getattr(texture_input, "sidecar_kind", "") or "")
        entry["linked_mesh_path"] = str(getattr(texture_input, "linked_mesh_path", "") or "")
        entry["packed_channels"] = list(tuple(getattr(texture_input, "packed_channels", ()) or ()))
        entry["srgb_mode"] = str(getattr(texture_input, "srgb_mode", "") or "")
        entry["parameter_declared_by"] = str(getattr(texture_input, "parameter_declared_by", "") or "")
        entry["material_output_quality"] = str(getattr(texture_input, "material_output_quality", "") or "")
        entry["layer_role"] = str(getattr(texture_input, "layer_role", "") or "")
        entry["layer_channel"] = str(getattr(texture_input, "layer_channel", "") or "")
        entry["blend_flags"] = list(tuple(getattr(texture_input, "blend_flags", ()) or ()))
        registry_decode = decode_crimson_texture_binding(
            shader_family=entry["shader_family"],
            parameter_name=entry["parameter_name"],
            source_path=str(entry.get("source_path", "") or ""),
            slot_name=slot_name,
            semantic_subtype=entry["semantic_subtype"],
            packed_channels=tuple(getattr(texture_input, "packed_channels", ()) or ()),
            layer_channel=entry["layer_channel"],
            blend_flags=tuple(getattr(texture_input, "blend_flags", ()) or ()),
            sidecar_kind=entry["sidecar_kind"],
            parameter_declared_by=entry["parameter_declared_by"],
        )
        entry["authority"] = str(registry_decode.get("authority", "") or AUTHORITY_GUESS)
        entry["disposition"] = str(registry_decode.get("disposition", "") or "")
        entry["registry_source_kind"] = str(registry_decode.get("source_kind", "") or "")
        entry["promoted_channels"] = dict(registry_decode.get("promoted_channels", {}) or {})
        if registry_decode.get("layer_channel"):
            entry["layer_channel"] = str(registry_decode.get("layer_channel", "") or "")
        input_entries.append(entry)
    if input_entries:
        output["material_inputs"] = input_entries
    return output


def _batch_dds_manifest_cache_key(
    batch: PreparedModelPreviewBatch,
    *,
    include_support_slots: bool,
    material_input_kinds: Optional[set[str]],
) -> str:
    allowed_input_kinds = (
        None
        if material_input_kinds is None
        else sorted(str(kind or "").strip().lower() for kind in set(material_input_kinds))
    )
    input_values = []
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        input_kind = _input_texture_kind(texture_input)
        if allowed_input_kinds is not None and input_kind not in set(allowed_input_kinds):
            continue
        input_values.append(
            (
                input_kind,
                str(getattr(texture_input, "slot_kind", "") or ""),
                str(getattr(texture_input, "parameter_name", "") or ""),
                str(getattr(texture_input, "source_dds_path", "") or ""),
                str(getattr(texture_input, "preview_texture_path", "") or ""),
                tuple(str(value) for value in tuple(getattr(texture_input, "packed_channels", ()) or ())),
                str(getattr(texture_input, "semantic_type", "") or ""),
                str(getattr(texture_input, "semantic_subtype", "") or ""),
                str(getattr(texture_input, "material_name", "") or ""),
                str(getattr(texture_input, "shader_family", "") or ""),
            )
        )
    payload = {
        "support": bool(include_support_slots),
        "input_kinds": allowed_input_kinds,
        "slots": {
            "base_dds": str(getattr(batch, "preview_texture_dds_path", "") or ""),
            "base_preview": str(getattr(batch, "preview_texture_path", "") or ""),
            "normal_dds": str(getattr(batch, "preview_normal_texture_dds_path", "") or ""),
            "normal_preview": str(getattr(batch, "preview_normal_texture_path", "") or ""),
            "material_dds": str(getattr(batch, "preview_material_texture_dds_path", "") or ""),
            "material_preview": str(getattr(batch, "preview_material_texture_path", "") or ""),
            "height_dds": str(getattr(batch, "preview_height_texture_dds_path", "") or ""),
            "height_preview": str(getattr(batch, "preview_height_texture_path", "") or ""),
        },
        "inputs": input_values,
    }
    return hashlib.sha1(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8", errors="replace")).hexdigest()


def _filter_dds_textures_for_preview_settings(
    dds_textures: Mapping[str, object],
    batch: PreparedModelPreviewBatch,
    *,
    render_settings: ModelPreviewRenderSettings,
    use_textures: bool,
    high_quality_textures: bool,
    promote_material_inputs: bool = True,
) -> Dict[str, object]:
    if not use_textures or not bool(getattr(batch, "has_texture_coordinates", False)):
        return {}
    support_enabled = bool(
        high_quality_textures
        and not bool(getattr(batch, "preview_debug_disable_support_maps", False))
        and not bool(getattr(render_settings, "disable_all_support_maps", False))
    )
    output: Dict[str, object] = {}
    base_entry = dds_textures.get("base")
    if _dds_manifest_entry_is_native_usable(base_entry):
        output["base"] = dict(base_entry)
    if support_enabled:
        for slot_name, disabled_attr in (
            ("normal", "disable_normal_map"),
            ("material", "disable_material_map"),
            ("height", "disable_height_map"),
        ):
            if bool(getattr(render_settings, disabled_attr, False)):
                continue
            entry = dds_textures.get(slot_name)
            if _dds_manifest_entry_is_native_usable(entry):
                output[slot_name] = dict(entry)

    def input_role(entry: Mapping[str, object]) -> str:
        descriptor = " ".join(
            str(entry.get(field, "") or "")
            for field in ("slot", "parameter_name", "semantic_type", "semantic_subtype", "source_path")
        ).lower()
        technical = _technical_texture_kind(descriptor)
        if (
            "base" in descriptor
            or "albedo" in descriptor
            or "diffuse" in descriptor
            or "color" in descriptor
        ) and technical not in {"normal", "height", "packed_material", "detail_mask", "opacity", "specular", "emissive"}:
            return "base"
        if technical == "emissive" or "emissive" in descriptor or "glow" in descriptor:
            return "emissive"
        if technical == "normal" or "normal" in descriptor:
            return "normal"
        if technical == "height" or "displacement" in descriptor:
            return "height"
        if technical in {"packed_material", "detail_mask", "specular", "roughness", "glossiness", "metalness", "occlusion"}:
            return "material"
        if any(token in descriptor for token in ("roughness", "metallic", "metalness", "occlusion", "materialmask")):
            return "material"
        if "opacity" in descriptor or "alpha" in descriptor:
            return "opacity"
        return "material"

    input_entries = dds_textures.get("material_inputs")
    if isinstance(input_entries, Sequence) and not isinstance(input_entries, (str, bytes, bytearray)):
        filtered_inputs: list[Dict[str, object]] = []
        for raw_entry in input_entries:
            if not isinstance(raw_entry, Mapping):
                continue
            if not _dds_manifest_entry_is_native_usable(raw_entry):
                continue
            role = input_role(raw_entry)
            if role in {"base", "emissive"}:
                filtered_inputs.append(dict(raw_entry))
            elif not support_enabled:
                continue
            elif role == "normal" and not bool(getattr(render_settings, "disable_normal_map", False)):
                filtered_inputs.append(dict(raw_entry))
            elif role == "height" and not bool(getattr(render_settings, "disable_height_map", False)):
                filtered_inputs.append(dict(raw_entry))
            elif role == "material" and not bool(getattr(render_settings, "disable_material_map", False)):
                filtered_inputs.append(dict(raw_entry))
        if filtered_inputs:
            for promoted_role, manifest_slot in (
                ("base", "base"),
                ("normal", "normal"),
                ("height", "height"),
                ("material", "material"),
                ("emissive", "emissive"),
            ):
                if not promote_material_inputs:
                    break
                if manifest_slot in output:
                    continue
                if promoted_role not in {"base", "emissive"} and not support_enabled:
                    continue
                if promoted_role == "normal" and bool(getattr(render_settings, "disable_normal_map", False)):
                    continue
                if promoted_role == "height" and bool(getattr(render_settings, "disable_height_map", False)):
                    continue
                if promoted_role == "material" and bool(getattr(render_settings, "disable_material_map", False)):
                    continue
                for entry in filtered_inputs:
                    if input_role(entry) != promoted_role:
                        continue
                    promoted = dict(entry)
                    promoted["slot"] = manifest_slot
                    promoted["promoted_from_material_input"] = True
                    output[manifest_slot] = promoted
                    break
            output["material_inputs"] = filtered_inputs
    return output


def _texture_sources_for_batch(
    batch: PreparedModelPreviewBatch,
    *,
    package_dir: Path,
    textures_dir: Path,
    batch_index: int,
    render_settings: ModelPreviewRenderSettings,
    use_textures: bool,
    high_quality_textures: bool,
    source_format: object,
    source_path: object,
    tangents_usable: bool,
    copy_cache: Dict[str, str],
    enable_material_combiner: bool = True,
    prefer_direct_dds: bool = False,
    direct_dds_slots: Optional[Mapping[str, object]] = None,
    legacy_pbr_cache: Optional[Dict[Tuple[str, int], Dict[str, str]]] = None,
    persistent_texture_cache_dir: Optional[Path] = None,
) -> Tuple[Dict[str, str], Tuple[str, ...], Dict[str, object]]:
    notes: list[str] = []
    textures: Dict[str, str] = {
        "base": "",
        "normal": "",
        "occlusion": "",
        "roughness": "",
        "metalness": "",
        "specular": "",
        "height": "",
        "emissive": "",
    }
    combiner_metadata: Dict[str, object] = {
        "active": False,
        "outputs": (),
        "decode_modes": (),
        "notes": (),
    }
    has_uv = bool(getattr(batch, "has_texture_coordinates", False))
    support_enabled = bool(
        use_textures
        and high_quality_textures
        and not bool(getattr(batch, "preview_debug_disable_support_maps", False))
        and not bool(getattr(render_settings, "disable_all_support_maps", False))
    )
    if not use_textures or not has_uv:
        notes.append("textures disabled" if not use_textures else "missing UVs")
        return textures, tuple(notes), combiner_metadata

    base_copy_cap = max(0, int(getattr(render_settings, "preview_texture_max_dimension", 0) or 0))
    support_copy_cap = max(0, int(getattr(render_settings, "low_quality_texture_max_dimension", 0) or 0))

    direct_dds_slots = direct_dds_slots if prefer_direct_dds and isinstance(direct_dds_slots, Mapping) else (
        _dds_textures_for_batch(batch) if prefer_direct_dds else {}
    )

    material_inputs: Tuple[PreviewMaterialTextureInput, ...] = tuple(
        texture_input
        for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ())
        if isinstance(texture_input, PreviewMaterialTextureInput)
    )

    def _direct_dds_entry_available(entry: object) -> bool:
        return bool(
            isinstance(entry, Mapping)
            and entry.get("available")
            and entry.get("source_path")
            and entry.get("direct_upload_candidate")
        )

    def has_direct_dds(slot_name: str) -> bool:
        entry = direct_dds_slots.get(slot_name)
        return _direct_dds_entry_available(entry)

    def _direct_material_input_entries() -> Tuple[Mapping[str, object], ...]:
        entries = direct_dds_slots.get("material_inputs")
        if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes, bytearray)):
            return ()
        return tuple(entry for entry in entries if isinstance(entry, Mapping))

    def _direct_material_descriptor(entry: Mapping[str, object]) -> str:
        return " ".join(
            str(entry.get(field, "") or "")
            for field in ("slot", "parameter_name", "semantic_type", "semantic_subtype", "source_path")
        ).lower()

    def _direct_material_source(entry: Mapping[str, object]) -> str:
        try:
            return str(Path(str(entry.get("source_path", "") or "")).expanduser().resolve()).casefold()
        except OSError:
            return str(entry.get("source_path", "") or "").casefold()

    def _source_identity(source_path: str) -> str:
        try:
            return str(Path(str(source_path or "")).expanduser().resolve()).casefold()
        except OSError:
            return str(source_path or "").casefold()

    def _direct_material_input_available_for(kind: str, texture_input: Optional[PreviewMaterialTextureInput] = None) -> bool:
        normalized_kind = str(kind or "").strip().lower()
        direct_source = ""
        if texture_input is not None:
            direct_source = str(getattr(texture_input, "source_dds_path", "") or "").strip()
            if not direct_source:
                direct_source = _source_dds_for_preview_path(str(getattr(texture_input, "preview_texture_path", "") or ""))
        direct_source_key = _source_identity(direct_source) if direct_source else ""
        for entry in _direct_material_input_entries():
            if not _direct_dds_entry_available(entry):
                continue
            if direct_source_key and _direct_material_source(entry) == direct_source_key:
                return True
            descriptor = _direct_material_descriptor(entry)
            technical = _technical_texture_kind(str(entry.get("source_path", "") or ""))
            if normalized_kind == "base":
                if (
                    "base" in descriptor
                    or "albedo" in descriptor
                    or "diffuse" in descriptor
                    or "color" in descriptor
                ) and technical not in {"normal", "height", "packed_material", "detail_mask", "opacity", "specular", "emissive"}:
                    return True
            elif normalized_kind == "emissive" and (technical == "emissive" or "emissive" in descriptor or "glow" in descriptor):
                return True
            elif normalized_kind == "normal" and technical == "normal":
                return True
            elif normalized_kind == "height" and technical == "height":
                return True
            elif normalized_kind == "specular" and (
                technical == "specular" or "specular" in descriptor or "_sp" in descriptor
            ):
                return True
            elif normalized_kind == "roughness" and ("roughness" in descriptor or "gloss" in descriptor or "smoothness" in descriptor):
                return True
            elif normalized_kind == "metalness" and ("metallic" in descriptor or "metalness" in descriptor):
                return True
            elif normalized_kind in {"material", "packed_material", "occlusion"} and (
                technical == "packed_material"
                or technical == "occlusion"
                or "material_mask" in descriptor
                or "packed_mask" in descriptor
                or "_ma" in descriptor
            ):
                return True
            elif normalized_kind in {"detail", "detail_mask"} and (
                technical == "detail_mask" or "detailmask" in descriptor or "colorblendingmask" in descriptor or "_mg" in descriptor
            ):
                return True
        return False

    def _direct_material_response_available() -> bool:
        return bool(
            has_direct_dds("material")
            or _direct_material_input_available_for("material")
            or _direct_material_input_available_for("specular")
            or _direct_material_input_available_for("roughness")
            or _direct_material_input_available_for("metalness")
            or _direct_material_input_available_for("detail")
        )

    def _direct_dds_available_for_source(source_path: str) -> bool:
        source_key = _source_identity(source_path)
        if not source_key:
            return False
        for slot_name in ("base", "normal", "material", "height", "emissive"):
            entry = direct_dds_slots.get(slot_name)
            if _direct_dds_entry_available(entry) and _direct_material_source(entry) == source_key:
                return True
        for entry in _direct_material_input_entries():
            if _direct_dds_entry_available(entry) and _direct_material_source(entry) == source_key:
                return True
        return False

    def _preview_source_has_direct_dds_upload(preview_path: str) -> bool:
        dds_path = _source_dds_for_preview_path(preview_path)
        return bool(dds_path and _direct_dds_available_for_source(dds_path))

    def package_relative(source_ref: str, slot_name: str) -> str:
        raw = str(source_ref or "").strip()
        if not raw:
            return ""
        try:
            from PySide6.QtCore import QUrl

            local_path = QUrl(raw).toLocalFile() if raw.lower().startswith("file:") else raw
        except Exception:
            local_path = raw
        try:
            source = Path(local_path).expanduser()
        except OSError:
            notes.append(f"{slot_name} invalid generated path")
            return ""
        if not source.is_file():
            notes.append(f"{slot_name} generated texture missing:{Path(local_path).name}")
            return ""
        try:
            return source.resolve().relative_to(package_dir.resolve()).as_posix()
        except (OSError, ValueError):
            return _copy_texture(
                str(source),
                package_dir=package_dir,
                textures_dir=textures_dir,
                batch_index=batch_index,
                slot_name=slot_name,
                copy_cache=copy_cache,
                notes=notes,
                max_dimension=base_copy_cap if slot_name == "base" else support_copy_cap,
                persistent_cache_dir=persistent_texture_cache_dir,
            )

    base_path = str(getattr(batch, "preview_texture_path", "") or "")
    if base_path:
        if has_direct_dds("base"):
            notes.append("base PNG fallback skipped; direct DDS available")
        else:
            textures["base"] = _copy_texture(
                base_path,
                package_dir=package_dir,
                textures_dir=textures_dir,
                batch_index=batch_index,
                slot_name="base",
                copy_cache=copy_cache,
                notes=notes,
                max_dimension=base_copy_cap,
                persistent_cache_dir=persistent_texture_cache_dir,
            )
    else:
        notes.append("no reliable base DDS")

    if support_enabled and not bool(getattr(render_settings, "disable_normal_map", False)):
        if has_direct_dds("normal"):
            notes.append("normal PNG fallback skipped; direct DDS available")
        else:
            textures["normal"] = _copy_texture(
                str(getattr(batch, "preview_normal_texture_path", "") or ""),
                package_dir=package_dir,
                textures_dir=textures_dir,
                batch_index=batch_index,
                slot_name="normal",
                copy_cache=copy_cache,
                notes=notes,
                max_dimension=support_copy_cap,
                persistent_cache_dir=persistent_texture_cache_dir,
            )
    if support_enabled and not bool(getattr(render_settings, "disable_height_map", False)):
        if has_direct_dds("height"):
            notes.append("height PNG fallback skipped; direct DDS available")
        else:
            textures["height"] = _copy_texture(
                str(getattr(batch, "preview_height_texture_path", "") or ""),
                package_dir=package_dir,
                textures_dir=textures_dir,
                batch_index=batch_index,
                slot_name="height",
                copy_cache=copy_cache,
                notes=notes,
                max_dimension=support_copy_cap,
                persistent_cache_dir=persistent_texture_cache_dir,
            )

    material_path = str(getattr(batch, "preview_material_texture_path", "") or "")
    material_subtype = str(getattr(batch, "preview_material_texture_subtype", "") or "").strip().lower()
    reused_legacy_pbr = False
    if support_enabled and material_path and material_subtype in {"pbr_combined", "legacy_pbr_combined"}:
        if prefer_direct_dds and _direct_material_response_available():
            notes.append("legacy PBR PNG split skipped; direct DDS material inputs available")
        else:
            try:
                cache_key = (str(Path(material_path).expanduser().resolve()).casefold(), int(support_copy_cap))
            except OSError:
                cache_key = (str(material_path).casefold(), int(support_copy_cap))
            generated = dict((legacy_pbr_cache or {}).get(cache_key, {}))
            if generated:
                notes.append("legacy PBR response reused from package cache")
            else:
                generated = _split_legacy_pbr_texture(
                    material_path,
                    package_dir=package_dir,
                    textures_dir=textures_dir,
                    batch_index=batch_index,
                    notes=notes,
                    max_dimension=support_copy_cap,
                )
                if generated and legacy_pbr_cache is not None:
                    legacy_pbr_cache[cache_key] = dict(generated)
            if not bool(getattr(render_settings, "disable_material_map", False)):
                for slot_name, relative_path in generated.items():
                    textures[slot_name] = relative_path
            if generated:
                reused_legacy_pbr = True
                combiner_metadata = {
                    "active": True,
                    "outputs": tuple(generated.keys()),
                    "decode_modes": ("pbr_combined",),
                    "notes": ("legacy PBR response reused",),
                }

    if enable_material_combiner and not reused_legacy_pbr and (support_enabled or material_inputs):
        try:
            from cdmw.ui.model_preview_material_combiner import (
                MaterialPreviewCombinerSettings,
                combine_preview_material,
                synthesize_material_texture_inputs,
            )

            synthesized_inputs = synthesize_material_texture_inputs(batch)
            combiner_payload = SimpleNamespace(
                material_name=str(getattr(batch, "material_name", "") or ""),
                texture_name=str(getattr(batch, "texture_name", "") or ""),
                source_path=str(source_path or ""),
                base_color=_first_vertex_color(getattr(batch, "vertex_blob", b"") or b""),
                texture_flip_vertical=resolve_preview_texture_flip_vertical(
                    getattr(batch, "preview_texture_flip_vertical", None),
                    source_format=source_format,
                    source_path=source_path,
                ),
                material_texture_inputs=synthesized_inputs,
                tangents_usable=bool(tangents_usable),
                normal_texture_strength=max(0.0, _safe_float(getattr(batch, "preview_normal_texture_strength", 0.0), 0.0)),
            )
            combiner_settings = MaterialPreviewCombinerSettings(
                normal_strength_floor=max(0.0, _safe_float(getattr(render_settings, "normal_strength_floor", 0.5), 0.5)),
                normal_strength_cap=max(0.0, _safe_float(getattr(render_settings, "normal_strength_cap", 1.0), 1.0)),
                height_amount=max(0.0, min(0.12, _safe_float(getattr(render_settings, "height_effect_max", 0.35), 0.35) * 0.08)),
                support_map_max_dimension=min(192, int(getattr(render_settings, "low_quality_texture_max_dimension", 192) or 192)),
            )
            combined = combine_preview_material(
                combiner_payload,
                textures_dir / "combined",
                batch_index,
                settings=combiner_settings,
            )
            combiner_metadata = {
                "active": bool(combined.active),
                "outputs": tuple(combined.outputs),
                "decode_modes": tuple(combined.decode_modes),
                "notes": tuple(combined.notes),
            }
            if combined.base_note:
                combiner_metadata["base_note"] = str(combined.base_note)
            notes.extend(str(note) for note in tuple(combined.notes or ()) if str(note))
            if combined.base_source:
                textures["base"] = package_relative(combined.base_source, "base")
            if support_enabled and not bool(getattr(render_settings, "disable_normal_map", False)) and combined.normal_source:
                textures["normal"] = package_relative(combined.normal_source, "normal")
            if support_enabled and not bool(getattr(render_settings, "disable_material_map", False)):
                if combined.occlusion_source:
                    textures["occlusion"] = package_relative(combined.occlusion_source, "occlusion")
                if combined.roughness_source:
                    textures["roughness"] = package_relative(combined.roughness_source, "roughness")
                if combined.metalness_source:
                    textures["metalness"] = package_relative(combined.metalness_source, "metalness")
                if combined.specular_source:
                    textures["specular"] = package_relative(combined.specular_source, "specular")
            if support_enabled and not bool(getattr(render_settings, "disable_height_map", False)) and combined.height_source:
                textures["height"] = package_relative(combined.height_source, "height")
                combiner_metadata["height_amount"] = float(combined.height_amount)
            if combined.normal_source:
                combiner_metadata["normal_strength"] = float(combined.normal_strength)
            combiner_metadata["texture_flip_vertical"] = bool(combined.texture_flip_vertical)
        except Exception as exc:
            notes.append(f"material combiner failed:{exc}")

    def assign_kind(
        kind: str,
        texture_source_path: str,
        label: str,
        texture_input: Optional[PreviewMaterialTextureInput] = None,
    ) -> None:
        nonlocal combiner_metadata
        combiner_decoded = bool(tuple(combiner_metadata.get("decode_modes", ()) or ()) or tuple(combiner_metadata.get("outputs", ()) or ()))
        if kind in {"base", "normal", "height"}:
            if textures.get(kind):
                return
            if prefer_direct_dds and _preview_source_has_direct_dds_upload(texture_source_path):
                notes.append(f"{kind} PNG fallback skipped; direct DDS material input available")
                return
            textures[kind] = _copy_texture(
                texture_source_path,
                package_dir=package_dir,
                textures_dir=textures_dir,
                batch_index=batch_index,
                slot_name=kind,
                copy_cache=copy_cache,
                notes=notes,
                max_dimension=base_copy_cap if kind == "base" else support_copy_cap,
                persistent_cache_dir=persistent_texture_cache_dir,
            )
            return
        if kind == "emissive":
            if textures.get(kind):
                return
            if prefer_direct_dds and _preview_source_has_direct_dds_upload(texture_source_path):
                notes.append("emissive PNG fallback skipped; direct DDS material input available")
                return
            textures[kind] = _copy_texture(
                texture_source_path,
                package_dir=package_dir,
                textures_dir=textures_dir,
                batch_index=batch_index,
                slot_name=kind,
                copy_cache=copy_cache,
                notes=notes,
                max_dimension=support_copy_cap,
                persistent_cache_dir=persistent_texture_cache_dir,
            )
            return
        if kind == "specular_glossiness":
            if not support_enabled or bool(getattr(render_settings, "disable_material_map", False)):
                return
            if textures.get("roughness") and textures.get("specular"):
                return
            try:
                from cdmw.ui.model_preview_material_combiner import (
                    MaterialPreviewCombinerSettings,
                    combine_preview_material,
                )

                spec_gloss_input = texture_input
                if spec_gloss_input is None:
                    spec_gloss_input = PreviewMaterialTextureInput(
                        slot_kind="material",
                        parameter_name="_specularGlossinessTexture",
                        source_texture_path=texture_source_path,
                        texture_name=label,
                        preview_texture_path=texture_source_path,
                        semantic_type="specular",
                        semantic_subtype="specular_glossiness",
                        packed_channels=("specular", "glossiness"),
                    )
                combiner_payload = SimpleNamespace(
                    material_name=str(getattr(batch, "material_name", "") or ""),
                    texture_name=str(getattr(batch, "texture_name", "") or ""),
                    texture_flip_vertical=resolve_preview_texture_flip_vertical(
                        getattr(batch, "preview_texture_flip_vertical", None),
                        source_format=source_format,
                        source_path=source_path,
                    ),
                    material_texture_inputs=(spec_gloss_input,),
                    tangents_usable=bool(tangents_usable),
                    normal_texture_strength=max(
                        0.0,
                        _safe_float(getattr(batch, "preview_normal_texture_strength", 0.0), 0.0),
                    ),
                )
                combiner_settings = MaterialPreviewCombinerSettings(
                    normal_strength_floor=max(0.0, _safe_float(getattr(render_settings, "normal_strength_floor", 0.5), 0.5)),
                    normal_strength_cap=max(0.0, _safe_float(getattr(render_settings, "normal_strength_cap", 1.0), 1.0)),
                    height_amount=max(0.0, min(0.12, _safe_float(getattr(render_settings, "height_effect_max", 0.35), 0.35) * 0.08)),
                    support_map_max_dimension=min(192, int(getattr(render_settings, "low_quality_texture_max_dimension", 192) or 192)),
                )
                combined = combine_preview_material(
                    combiner_payload,
                    textures_dir / "combined",
                    batch_index,
                    settings=combiner_settings,
                )
                notes.extend(str(note) for note in tuple(combined.notes or ()) if str(note))
                if combined.roughness_source and not textures.get("roughness"):
                    textures["roughness"] = package_relative(combined.roughness_source, "roughness")
                if combined.specular_source and not textures.get("specular"):
                    textures["specular"] = package_relative(combined.specular_source, "specular")
                if combined.active:
                    combiner_metadata = {
                        "active": True,
                        "outputs": tuple(
                            dict.fromkeys(tuple(combiner_metadata.get("outputs", ()) or ()) + tuple(combined.outputs or ()))
                        ),
                        "decode_modes": tuple(
                            dict.fromkeys(tuple(combiner_metadata.get("decode_modes", ()) or ()) + tuple(combined.decode_modes or ()))
                        ),
                        "notes": tuple(
                            dict.fromkeys(tuple(combiner_metadata.get("notes", ()) or ()) + tuple(combined.notes or ()))
                        ),
                        "texture_flip_vertical": bool(combined.texture_flip_vertical),
                    }
                if textures.get("roughness") or textures.get("specular"):
                    return
            except Exception as exc:
                notes.append(f"specular-glossiness split failed:{exc}")
            if not textures.get("specular"):
                textures["specular"] = _copy_texture(
                    texture_source_path,
                    package_dir=package_dir,
                    textures_dir=textures_dir,
                    batch_index=batch_index,
                    slot_name="specular",
                    copy_cache=copy_cache,
                    notes=notes,
                    max_dimension=support_copy_cap,
                    persistent_cache_dir=persistent_texture_cache_dir,
                )
            notes.append(f"specular-glossiness roughness unavailable:{label}")
            return
        if kind == "glossiness":
            if not support_enabled or bool(getattr(render_settings, "disable_material_map", False)):
                return
            if textures.get("roughness"):
                return
            try:
                from cdmw.ui.model_preview_material_combiner import (
                    MaterialPreviewCombinerSettings,
                    combine_preview_material,
                )

                gloss_input = texture_input
                if gloss_input is None:
                    gloss_input = PreviewMaterialTextureInput(
                        slot_kind="glossiness",
                        parameter_name="_glossinessTexture",
                        source_texture_path=texture_source_path,
                        texture_name=label,
                        preview_texture_path=texture_source_path,
                        semantic_type="roughness",
                        semantic_subtype="glossiness",
                        packed_channels=("glossiness",),
                    )
                combiner_payload = SimpleNamespace(
                    material_name=str(getattr(batch, "material_name", "") or ""),
                    texture_name=str(getattr(batch, "texture_name", "") or ""),
                    texture_flip_vertical=resolve_preview_texture_flip_vertical(
                        getattr(batch, "preview_texture_flip_vertical", None),
                        source_format=source_format,
                        source_path=source_path,
                    ),
                    material_texture_inputs=(gloss_input,),
                    tangents_usable=bool(tangents_usable),
                    normal_texture_strength=max(
                        0.0,
                        _safe_float(getattr(batch, "preview_normal_texture_strength", 0.0), 0.0),
                    ),
                )
                combined = combine_preview_material(
                    combiner_payload,
                    textures_dir / "combined",
                    batch_index,
                    settings=MaterialPreviewCombinerSettings(
                        support_map_max_dimension=min(192, int(getattr(render_settings, "low_quality_texture_max_dimension", 192) or 192)),
                    ),
                )
                notes.extend(str(note) for note in tuple(combined.notes or ()) if str(note))
                if combined.roughness_source and not textures.get("roughness"):
                    textures["roughness"] = package_relative(combined.roughness_source, "roughness")
                if combined.active:
                    combiner_metadata = {
                        "active": True,
                        "outputs": tuple(
                            dict.fromkeys(tuple(combiner_metadata.get("outputs", ()) or ()) + tuple(combined.outputs or ()))
                        ),
                        "decode_modes": tuple(
                            dict.fromkeys(tuple(combiner_metadata.get("decode_modes", ()) or ()) + tuple(combined.decode_modes or ()))
                        ),
                        "notes": tuple(
                            dict.fromkeys(tuple(combiner_metadata.get("notes", ()) or ()) + tuple(combined.notes or ()))
                        ),
                        "texture_flip_vertical": bool(combined.texture_flip_vertical),
                    }
                if textures.get("roughness"):
                    return
            except Exception as exc:
                notes.append(f"glossiness split failed:{exc}")
            notes.append(f"glossiness roughness unavailable:{label}")
            return
        if kind == "occlusion":
            if not support_enabled or bool(getattr(render_settings, "disable_material_map", False)):
                return
            if textures.get("occlusion"):
                return
            if prefer_direct_dds and _preview_source_has_direct_dds_upload(texture_source_path):
                notes.append("occlusion PNG fallback skipped; direct DDS material input available")
                return
            textures["occlusion"] = _copy_texture(
                texture_source_path,
                package_dir=package_dir,
                textures_dir=textures_dir,
                batch_index=batch_index,
                slot_name="occlusion",
                copy_cache=copy_cache,
                notes=notes,
                max_dimension=support_copy_cap,
                persistent_cache_dir=persistent_texture_cache_dir,
            )
            return
        if kind in {"roughness", "metalness", "specular"}:
            if not support_enabled or bool(getattr(render_settings, f"disable_material_map", False)):
                return
            if textures.get(kind):
                return
            if prefer_direct_dds and _preview_source_has_direct_dds_upload(texture_source_path):
                notes.append(f"{kind} PNG fallback skipped; direct DDS material input available")
                return
            textures[kind] = _copy_texture(
                texture_source_path,
                package_dir=package_dir,
                textures_dir=textures_dir,
                batch_index=batch_index,
                slot_name=kind,
                copy_cache=copy_cache,
                notes=notes,
                max_dimension=support_copy_cap,
                persistent_cache_dir=persistent_texture_cache_dir,
            )
            return
        if kind in {"packed_material", "detail_mask"}:
            if not support_enabled or bool(getattr(render_settings, "disable_material_map", False)):
                return
            if textures.get("material"):
                return
            if prefer_direct_dds and _preview_source_has_direct_dds_upload(texture_source_path):
                notes.append(f"{kind} PNG fallback skipped; direct DDS material input available")
                return
            textures["material"] = _copy_texture(
                texture_source_path,
                package_dir=package_dir,
                textures_dir=textures_dir,
                batch_index=batch_index,
                slot_name="material",
                copy_cache=copy_cache,
                notes=notes,
                max_dimension=support_copy_cap,
                persistent_cache_dir=persistent_texture_cache_dir,
            )
            return
        elif kind == "opacity":
            notes.append(f"opacity ignored:{label}")

    if material_path:
        material_descriptor = " ".join(
            (
                str(getattr(batch, "preview_material_texture_type", "") or ""),
                str(getattr(batch, "preview_material_texture_subtype", "") or ""),
                str(getattr(batch, "preview_material_texture_packed_channels", ()) or ()),
                material_path,
            )
        )
        assign_kind(_technical_texture_kind(material_descriptor), material_path, Path(material_path).name)

    for texture_input in material_inputs:
        source = str(getattr(texture_input, "preview_texture_path", "") or "").strip()
        if not source:
            continue
        kind = _input_texture_kind(texture_input)
        label = str(getattr(texture_input, "texture_name", "") or "").strip() or Path(source).name
        if kind and prefer_direct_dds and _direct_material_input_available_for(kind, texture_input):
            notes.append(f"{kind} PNG fallback skipped; direct DDS material input available")
            continue
        assign_kind(kind, source, label, texture_input)

    return textures, tuple(dict.fromkeys(note for note in notes if note)), combiner_metadata


def _d3d11_material_policy_for_batch(
    batch: PreparedModelPreviewBatch,
    *,
    enable_material_combiner: bool,
    prefer_direct_dds: bool,
    original_reference_material_parity: bool = True,
    editor_workspace: str = "",
) -> tuple[bool, bool, str]:
    role = str(getattr(batch, "editor_role", "") or "").strip().lower()
    workspace = str(editor_workspace or "").strip().lower()
    if role == "original_reference" and original_reference_material_parity:
        return False, True, "original_reference_archive_direct"
    if role == "replacement_preview":
        if workspace == "modify_original_alignment" and original_reference_material_parity:
            return False, True, "modify_original_archive_direct"
        return False, bool(prefer_direct_dds), "replacement_source_direct"
    return bool(enable_material_combiner), bool(prefer_direct_dds), "global"


def write_isolated_d3d11_preview_package(
    model: object,
    prepared_preview: PreparedModelPreviewData,
    *,
    render_settings: Optional[ModelPreviewRenderSettings] = None,
    use_textures: bool = True,
    high_quality_textures: bool = True,
    backend: str = "d3d11",
    output_root: Optional[Path] = None,
    enable_material_combiner: bool = True,
    prefer_direct_dds: bool = False,
    original_reference_material_parity: bool = True,
    display_mode: str = "replacement_only",
    editor_workspace: str = "",
    geometry_cache_dir: Optional[Path] = None,
    texture_cache_dir: Optional[Path] = None,
    geometry_cache_key: str = "",
    stop_event: object = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> Path:
    if not isinstance(prepared_preview, PreparedModelPreviewData):
        raise TypeError("prepared_preview must be PreparedModelPreviewData")
    started = time.perf_counter()
    trace_enabled = _mesh_editor_load_trace_enabled()
    load_trace: Dict[str, float] = dict(getattr(prepared_preview, "load_trace", {}) or {}) if trace_enabled else {}
    if output_root is None:
        package_dir = Path(tempfile.mkdtemp(prefix="cdmw_isolated_d3d11_"))
    else:
        package_dir = Path(output_root).expanduser()
        package_dir.mkdir(parents=True, exist_ok=True)
    textures_dir = package_dir / "textures"
    geometry_dir = package_dir / "geometry"
    textures_dir.mkdir(parents=True, exist_ok=True)
    geometry_dir.mkdir(parents=True, exist_ok=True)

    settings = clamp_model_preview_render_settings(render_settings)
    copy_cache: Dict[str, str] = {}
    dds_inspect_cache: Dict[str, Dict[str, object]] = {}
    dds_manifest_cache: Dict[str, Dict[str, object]] = {}
    batches: list[Dict[str, object]] = []
    unique_texture_manifest: Dict[str, Dict[str, object]] = {}
    total_vertices = 0
    prepared_batches = tuple(getattr(prepared_preview, "batches", ()) or ())
    progress_total = max(1, len(prepared_batches))
    aggregate_geometry_file = "geometry/geometry.bin"
    aggregate_identity_file = "geometry/identity.bin"
    aggregate_geometry_chunks: list[bytes] = []
    aggregate_identity_chunks: list[bytes] = []
    aggregate_geometry_size = 0
    aggregate_identity_size = 0

    def _emit_progress(current: int, total: int, message: str) -> None:
        if on_progress is None:
            return
        try:
            on_progress(max(0, int(current)), max(1, int(total)), str(message or "Writing D3D11 preview package..."))
        except Exception:
            pass

    def _record_unique_texture_manifest_entry(
        kind: str,
        slot_name: str,
        path_value: object,
        *,
        package_path: str = "",
    ) -> None:
        raw = str(path_value or "").strip()
        if not raw:
            return
        try:
            source = Path(raw).expanduser()
        except OSError:
            return
        stat_key = _source_file_stat_key(source) if source.is_file() else raw.casefold()
        key = hashlib.sha1(
            f"{kind}|{slot_name}|{stat_key}|{package_path}".encode("utf-8", errors="replace")
        ).hexdigest()
        if key in unique_texture_manifest:
            return
        payload: Dict[str, object] = {
            "kind": str(kind or "texture"),
            "slot": str(slot_name or ""),
            "source_path": str(source),
        }
        if package_path:
            payload["package_path"] = str(package_path)
        if source.is_file():
            try:
                stat = source.stat()
                payload["source_size"] = int(stat.st_size)
                payload["source_mtime_ns"] = int(stat.st_mtime_ns)
            except OSError:
                pass
        unique_texture_manifest[key] = payload

    def _record_unique_texture_manifest(
        textures: Mapping[str, str],
        dds_textures: Mapping[str, object],
    ) -> None:
        for slot_name, relative_path in sorted(textures.items()):
            relative_text = str(relative_path or "").strip()
            if not relative_text:
                continue
            _record_unique_texture_manifest_entry(
                "package_texture",
                str(slot_name),
                package_dir / relative_text,
                package_path=relative_text,
            )
        for slot_name, entry in sorted(dds_textures.items()):
            if slot_name == "material_inputs":
                continue
            if isinstance(entry, Mapping):
                _record_unique_texture_manifest_entry(
                    "direct_dds",
                    str(slot_name),
                    entry.get("source_path", ""),
                )
        input_entries = dds_textures.get("material_inputs")
        if isinstance(input_entries, Sequence) and not isinstance(input_entries, (str, bytes, bytearray)):
            for entry in input_entries:
                if isinstance(entry, Mapping):
                    _record_unique_texture_manifest_entry(
                        "direct_dds_input",
                        str(entry.get("slot", "") or "material"),
                        entry.get("source_path", ""),
                    )

    _emit_progress(0, progress_total, "Writing D3D11 preview package...")
    has_cloth_batches = any(
        isinstance(getattr(batch, "cloth_preview", None), ClothPreviewBatch)
        for batch in prepared_batches
        if isinstance(batch, PreparedModelPreviewBatch)
    )
    cloth_collider_file, cloth_collider_count = (
        _write_cloth_collider_payload(model, package_dir, geometry_dir)
        if has_cloth_batches
        else ("", 0)
    )
    cloth_batch_count = 0
    cloth_particle_count = 0
    cloth_constraint_count = 0
    legacy_pbr_cache: Dict[Tuple[str, int], Dict[str, str]] = {}
    for batch_index, batch in enumerate(prepared_batches):
        if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
            raise RunCancelled("D3D11 package write cancelled.")
        if not isinstance(batch, PreparedModelPreviewBatch):
            continue
        batch = _materialized_in_memory_batch(
            model,
            batch,
            textures_dir=textures_dir,
            batch_index=batch_index,
        )
        blob = bytes(getattr(batch, "vertex_blob", b"") or b"")
        vertex_count = max(
            0,
            min(_safe_int(getattr(batch, "index_count", 0), 0), len(blob) // ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES),
        )
        if vertex_count <= 0:
            continue
        usable_blob = blob[: vertex_count * ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES]
        geometry_offset = aggregate_geometry_size
        cached_geometry_path: Optional[Path] = None
        if geometry_cache_dir is not None and str(geometry_cache_key or "").strip():
            try:
                geometry_cache_dir.mkdir(parents=True, exist_ok=True)
                geometry_digest = hashlib.sha1(usable_blob).hexdigest()
                safe_geometry_key = hashlib.sha1(
                    str(geometry_cache_key or "").encode("utf-8", errors="replace")
                ).hexdigest()
                cached_geometry_path = geometry_cache_dir / (
                    f"{safe_geometry_key}_batch_{batch_index:03d}_{vertex_count}_{geometry_digest}.bin"
                )
                if not cached_geometry_path.is_file():
                    cached_geometry_path.write_bytes(usable_blob)
            except OSError:
                cached_geometry_path = None
        aggregate_geometry_chunks.append(usable_blob)
        aggregate_geometry_size += len(usable_blob)
        if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
            raise RunCancelled("D3D11 package write cancelled.")
        editor_identity, identity_blob = _editor_identity_blob(batch, vertex_count)
        identity_offset = aggregate_identity_size
        aggregate_identity_chunks.append(identity_blob)
        aggregate_identity_size += len(identity_blob)
        editor_identity["identity_file"] = aggregate_identity_file
        editor_identity["identity_offset"] = identity_offset
        editor_identity["identity_size"] = len(identity_blob)
        tangents_usable = _tangents_usable(usable_blob, vertex_count)
        support_dds_enabled = bool(
            use_textures
            and high_quality_textures
            and not bool(getattr(batch, "preview_debug_disable_support_maps", False))
            and not bool(getattr(settings, "disable_all_support_maps", False))
        )
        batch_enable_combiner, batch_prefer_direct_dds, material_policy = _d3d11_material_policy_for_batch(
            batch,
            enable_material_combiner=bool(enable_material_combiner),
            prefer_direct_dds=bool(prefer_direct_dds),
            original_reference_material_parity=bool(original_reference_material_parity),
            editor_workspace=editor_workspace,
        )
        archive_direct_material_policy = material_policy in {
            "original_reference_archive_direct",
            "modify_original_archive_direct",
        }
        dds_started = time.perf_counter()
        material_input_kinds = None if support_dds_enabled else {"base", "emissive"}
        dds_manifest_cache_key = _batch_dds_manifest_cache_key(
            batch,
            include_support_slots=support_dds_enabled,
            material_input_kinds=material_input_kinds,
        )
        cached_dds_manifest = dds_manifest_cache.get(dds_manifest_cache_key)
        if cached_dds_manifest is not None:
            raw_dds_textures = copy.deepcopy(cached_dds_manifest)
        else:
            raw_dds_textures = _dds_textures_for_batch(
                batch,
                inspect_cache=dds_inspect_cache,
                include_support_slots=support_dds_enabled,
                material_input_kinds=material_input_kinds,
            )
            dds_manifest_cache[dds_manifest_cache_key] = copy.deepcopy(raw_dds_textures)
        if trace_enabled:
            load_trace["dds_manifest_ms"] = float(load_trace.get("dds_manifest_ms", 0.0)) + max(0.0, (time.perf_counter() - dds_started) * 1000.0)
        dds_textures = _filter_dds_textures_for_preview_settings(
            raw_dds_textures,
            batch,
            render_settings=settings,
            use_textures=bool(use_textures),
            high_quality_textures=bool(high_quality_textures),
            promote_material_inputs=not archive_direct_material_policy,
        )
        texture_started = time.perf_counter()
        textures, notes, combiner_metadata = _texture_sources_for_batch(
            batch,
            package_dir=package_dir,
            textures_dir=textures_dir,
            batch_index=batch_index,
            render_settings=settings,
            use_textures=bool(use_textures),
            high_quality_textures=bool(high_quality_textures),
            source_format=getattr(prepared_preview, "format", "") or getattr(model, "format", ""),
            source_path=getattr(prepared_preview, "source_path", "") or getattr(model, "path", ""),
            tangents_usable=tangents_usable,
            copy_cache=copy_cache,
            enable_material_combiner=batch_enable_combiner,
            prefer_direct_dds=batch_prefer_direct_dds,
            direct_dds_slots=dds_textures,
            legacy_pbr_cache=legacy_pbr_cache,
            persistent_texture_cache_dir=Path(texture_cache_dir).expanduser() if texture_cache_dir else None,
        )
        if trace_enabled:
            load_trace["texture_copy_ms"] = float(load_trace.get("texture_copy_ms", 0.0)) + max(0.0, (time.perf_counter() - texture_started) * 1000.0)
        _record_unique_texture_manifest(textures, dds_textures)
        if material_policy == "original_reference_archive_direct":
            notes = tuple(notes) + (
                "original reference material policy: direct archive DDS upload; synthesized material combiner disabled",
            )
        elif material_policy == "modify_original_archive_direct":
            notes = tuple(notes) + (
                "modify-original material policy: direct archive DDS upload; synthesized material combiner disabled",
            )
        elif material_policy == "replacement_source_direct":
            notes = tuple(notes) + (
                "replacement material policy: direct source DDS preferred; archive material combiner disabled",
            )
        total_vertices += vertex_count
        normal_strength = max(
            _safe_float(getattr(settings, "normal_strength_floor", 0.5), 0.5),
            min(
                _safe_float(getattr(settings, "normal_strength_cap", 1.0), 1.0),
                _safe_float(getattr(batch, "preview_normal_texture_strength", 0.0), 0.0),
            ),
        )
        if _safe_float(combiner_metadata.get("normal_strength", 0.0), 0.0) > 0.0:
            normal_strength = _safe_float(combiner_metadata.get("normal_strength"), normal_strength)
        height_amount = max(0.0, min(0.08, _safe_float(getattr(settings, "height_effect_max", 0.35), 0.35) * 0.08))
        if _safe_float(combiner_metadata.get("height_amount", 0.0), 0.0) > 0.0:
            height_amount = max(0.0, min(0.12, _safe_float(combiner_metadata.get("height_amount"), height_amount)))
        texture_flip_vertical = resolve_preview_texture_flip_vertical(
            getattr(batch, "preview_texture_flip_vertical", None),
            source_format=getattr(prepared_preview, "format", "") or getattr(model, "format", ""),
            source_path=getattr(prepared_preview, "source_path", "") or getattr(model, "path", ""),
        )
        if "texture_flip_vertical" in combiner_metadata:
            texture_flip_vertical = bool(combiner_metadata.get("texture_flip_vertical", texture_flip_vertical))
        if bool(getattr(settings, "flip_texture_v", False)):
            texture_flip_vertical = not texture_flip_vertical
        prefer_generated_base_texture = bool(
            textures.get("base")
            and _combiner_generated_authoritative_albedo(combiner_metadata)
        )
        if prefer_generated_base_texture:
            notes = tuple(notes) + ("native base DDS bypassed for synthesized sidecar albedo",)
        material_contract = _material_contract_for_batch(
            batch,
            textures=textures,
            dds_textures=dds_textures,
            combiner_metadata=combiner_metadata,
        )
        material_hints = dict(_native_material_hints_for_batch(batch))
        effective_emissive_intensity = _effective_emissive_intensity(
            material_hints,
            textures=textures,
            dds_textures=dds_textures,
        )
        if effective_emissive_intensity > _safe_float(material_hints.get("emissive_intensity"), 0.0):
            material_hints["emissive_intensity"] = effective_emissive_intensity
            material_hints["emissive_active"] = True
            material_hints["source"] = "emissive_texture_default"
            pbr_hints = material_contract.get("pbr_scalar_hints")
            if isinstance(pbr_hints, dict):
                pbr_hints["emissive_intensity"] = effective_emissive_intensity
            decode_profile = material_contract.get("decode_profile")
            if isinstance(decode_profile, dict):
                profile_hints = decode_profile.get("pbr_scalar_hints")
                if isinstance(profile_hints, dict):
                    profile_hints["emissive_intensity"] = effective_emissive_intensity
        material_category, material_category_confidence = _resolved_batch_material_category(
            batch,
            textures=textures,
            dds_textures=dds_textures,
            material_hints=material_hints,
            material_contract=material_contract,
            source_path=getattr(prepared_preview, "source_path", "") or getattr(model, "path", ""),
        )
        material_category_reason = _resolved_batch_material_category_reason(
            material_category,
            batch,
            textures=textures,
            dds_textures=dds_textures,
            material_hints=material_hints,
            material_contract=material_contract,
            source_path=getattr(prepared_preview, "source_path", "") or getattr(model, "path", ""),
        )
        if _apply_nonmetal_material_scalar_limits(material_hints, material_contract, material_category):
            notes = tuple(notes) + (
                f"nonmetal scalar clamp:{material_category}",
            )
        material_base_policy = _material_base_policy_for_batch(
            batch,
            material_category=material_category,
            combiner_metadata=combiner_metadata,
        )
        material_finish = _resolved_batch_material_finish(material_category, material_hints)
        for diagnostic in tuple(material_base_policy.get("diagnostics", ()) or ()):
            if isinstance(diagnostic, Mapping):
                code = str(diagnostic.get("code", "") or "")
                if code:
                    notes = tuple(notes) + (code,)
        emissive_color = _material_hex_color_rgb(material_hints.get("emissive_color", ""))
        if not emissive_color:
            emissive_color = (0.35, 0.68, 1.0)
        texture_quality = _texture_quality_summary(
            textures=textures,
            dds_textures=dds_textures,
            settings=settings,
            high_quality_textures=bool(high_quality_textures),
        )
        raw_alpha_mode = str(getattr(batch, "preview_alpha_mode", "") or "").strip()
        native_alpha_mode = "alpha_cutout" if raw_alpha_mode.lower() == "mask" else raw_alpha_mode
        preview_double_sided = bool(getattr(batch, "preview_double_sided", False))
        texture_brightness = max(0.1, min(3.0, _safe_float(getattr(batch, "preview_texture_brightness", 1.0), 1.0)))
        texture_uv_scale_values = tuple(getattr(batch, "preview_texture_uv_scale", ()) or ())[:2]
        texture_uv_scale = tuple(
            max(0.05, min(64.0, _safe_float(value, 1.0)))
            for value in texture_uv_scale_values
        )
        while len(texture_uv_scale) < 2:
            texture_uv_scale = (*texture_uv_scale, 1.0)
        texture_tint = tuple(
            max(0.0, min(2.0, _safe_float(value, 1.0)))
            for value in tuple(getattr(batch, "preview_texture_tint", ()) or ())[:3]
        )
        tint_active = len(texture_tint) >= 3 and any(abs(float(value) - 1.0) > 1e-4 for value in texture_tint)
        source_path_text = getattr(prepared_preview, "source_path", "") or getattr(model, "path", "")
        if not tint_active:
            sidecar_texture_tint = _sidecar_preview_texture_tint_for_batch(batch, source_path=source_path_text)
            if sidecar_texture_tint:
                texture_tint = sidecar_texture_tint
                tint_active = True
                notes = tuple(notes) + ("sidecar tint promoted to preview base tint",)
        batch_payload = {
                "index": batch_index,
                "material_name": str(getattr(batch, "material_name", "") or ""),
                "texture_name": str(getattr(batch, "texture_name", "") or ""),
                "vertex_file": aggregate_geometry_file,
                "vertex_offset": geometry_offset,
                "vertex_size": len(usable_blob),
                "vertex_count": vertex_count,
                "editor_identity": editor_identity,
                "base_color": list(_first_vertex_color(usable_blob)),
                "textures": textures,
                "dds_textures": dds_textures,
                "texture_flip_vertical": texture_flip_vertical,
                "texture_brightness": texture_brightness,
                "texture_uv_scale": list(texture_uv_scale),
                "texture_tint": list(texture_tint),
                "base_tint_strength": 0.85 if tint_active else 0.0,
                "alpha_mode": native_alpha_mode,
                "source_alpha_mode": raw_alpha_mode,
                "double_sided": preview_double_sided,
                "two_sided": preview_double_sided,
                "has_texture_coordinates": bool(getattr(batch, "has_texture_coordinates", False)),
                "tangents_usable": tangents_usable,
                "normal_strength": normal_strength,
                "height_amount": height_amount,
                "roughness": _safe_float(material_hints.get("roughness"), 0.55),
                "metalness": _safe_float(material_hints.get("metalness"), 0.0),
                "specular": _safe_float(material_hints.get("specular"), 0.08),
                "height_scale": _safe_float(material_hints.get("height_scale"), 0.0),
                "emissive_intensity": _safe_float(material_hints.get("emissive_intensity"), 0.0),
                "emissive_color": list(emissive_color),
                "native_material_hints": material_hints,
                "material_contract": material_contract,
                "material_shader_family": str(material_contract.get("shader_family", "generic") or "generic"),
                "material_category": material_category,
                "material_finish": material_finish,
                "material_category_confidence": material_category_confidence,
                "material_category_reason": material_category_reason,
                "material_response_promoted": bool(
                    material_category == "metal"
                    and _slot_has_resolved_texture(textures, dds_textures, "material")
                ),
                "material_analysis": {
                    "category": material_category,
                    "finish": material_finish,
                    "confidence": material_category_confidence,
                    "reason": material_category_reason,
                    "shader_family": str(material_contract.get("shader_family", "generic") or "generic"),
                    "has_base": bool(textures.get("base") or dds_textures.get("base")),
                    "has_material": bool(textures.get("material") or dds_textures.get("material")),
                    "has_specular": bool(textures.get("specular") or dds_textures.get("specular")),
                    "has_emissive": bool(textures.get("emissive") or dds_textures.get("emissive")),
                    "roughness_hint": _safe_float(material_hints.get("roughness"), 0.55),
                    "metalness_hint": _safe_float(material_hints.get("metalness"), 0.0),
                    "specular_hint": _safe_float(material_hints.get("specular"), 0.08),
                    "emissive_intensity": _safe_float(material_hints.get("emissive_intensity"), 0.0),
                },
                "material_base_policy": material_base_policy,
                "material_base_diagnostics": list(tuple(material_base_policy.get("diagnostics", ()) or ())),
                "material_diagnostics": _manifest_material_diagnostics(material_contract)
                + list(tuple(material_base_policy.get("diagnostics", ()) or ())),
                "prefer_generated_base_texture": prefer_generated_base_texture,
                "texture_quality": texture_quality,
                "notes": list(notes),
                "material_combiner_active": bool(combiner_metadata.get("active", False)),
                "material_combiner_policy": material_policy,
                "material_combiner_enabled": batch_enable_combiner,
                "prefer_direct_dds": batch_prefer_direct_dds,
                "material_combiner_outputs": list(tuple(combiner_metadata.get("outputs", ()) or ())),
                "material_combiner_decode_modes": list(tuple(combiner_metadata.get("decode_modes", ()) or ())),
                "material_combiner_notes": list(tuple(combiner_metadata.get("notes", ()) or ())),
                "material_inputs": [
                    _material_input_to_dict(texture_input)
                    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ())
                    if isinstance(texture_input, PreviewMaterialTextureInput)
                ],
            }
        native_material_overrides = _native_material_overrides_for_batch(batch)
        if native_material_overrides:
            batch_payload.update(native_material_overrides)
            note_values = list(str(note) for note in tuple(batch_payload.get("notes", ()) or ()) if str(note))
            note_values.append("native material manifest overrides applied")
            batch_payload["notes"] = list(dict.fromkeys(note_values))
        material_channel_contract = resolve_preview_batch_material_channels(batch_payload, package_dir=package_dir).diagnostics()
        batch_payload["material_channel_contract"] = material_channel_contract
        batch_payload["material_channel_diagnostics"] = list(material_channel_contract.get("channels", ())) + list(
            material_channel_contract.get("unresolved", ())
        )
        note_values = list(str(note) for note in tuple(batch_payload.get("notes", ()) or ()) if str(note))
        quality_values = sorted(
            {
                str(item.get("material_output_quality", "") or "").strip()
                for item in batch_payload.get("material_inputs", ())
                if isinstance(item, Mapping) and str(item.get("material_output_quality", "") or "").strip()
            }
        )
        if quality_values:
            note_values.append(f"material output quality:{','.join(quality_values)}")
        shader_note = str(material_contract.get("shader_family", "") or "").strip()
        if shader_note:
            note_values.append(f"shader family:{shader_note}")
        if material_category and material_category != "generic":
            note_values.append(f"material category:{material_category}:{material_category_confidence:.2f}")
        if material_finish and material_finish not in {"generic", material_category}:
            note_values.append(f"material finish:{material_finish}")
        texture_slots = material_contract.get("texture_slots", {})
        if isinstance(texture_slots, Mapping):
            direct_slots = sorted(
                str(slot_name)
                for slot_name, slot_state in texture_slots.items()
                if isinstance(slot_state, Mapping) and str(slot_state.get("status", "") or "") == "direct_dds"
            )
            fallback_slots = sorted(
                str(slot_name)
                for slot_name, slot_state in texture_slots.items()
                if isinstance(slot_state, Mapping) and str(slot_state.get("status", "") or "") == "preview_png"
            )
            if direct_slots:
                note_values.append(f"direct DDS slots:{','.join(direct_slots)}")
            if fallback_slots:
                note_values.append(f"PNG fallback slots:{','.join(fallback_slots)}")
        unresolved_count = len(tuple(material_channel_contract.get("unresolved", ()) or ()))
        if unresolved_count:
            note_values.append(f"unresolved material channel maps:{unresolved_count}")
        batch_payload["notes"] = list(dict.fromkeys(note_values))
        cloth_payload = _write_cloth_runtime_payloads(
            package_dir,
            geometry_dir,
            batch_index,
            getattr(batch, "cloth_preview", None),
        )
        if cloth_payload:
            cloth_batch_count += 1
            cloth_particle_count += _safe_int(cloth_payload.get("cloth_particle_count"), 0)
            cloth_constraint_count += _safe_int(cloth_payload.get("cloth_constraint_count"), 0)
            if not cloth_collider_file:
                cloth_payload["cloth_collision_enabled"] = False
            batch_payload.update(cloth_payload)
        batches.append(batch_payload)
        _emit_progress(
            min(batch_index + 1, progress_total),
            progress_total,
            f"Writing D3D11 preview package... {min(batch_index + 1, progress_total)} / {progress_total} batches",
        )

    normalized_display_mode = str(display_mode or "replacement_only").strip().lower()
    if normalized_display_mode not in {"side_by_side", "overlay", "replacement_only"}:
        normalized_display_mode = "replacement_only"
    has_metal_preview_response = any(_batch_has_metal_preview_response(batch) for batch in batches)
    lighting_preset = _lighting_preset_for_settings(settings)
    if has_metal_preview_response and lighting_preset == "neutral_studio":
        lighting_preset = "shiny_metal_inspection"
    ambient_strength = _safe_float(getattr(settings, "ambient_strength", 0.55), 0.55)
    diffuse_light_scale = _safe_float(getattr(settings, "diffuse_light_scale", 0.65), 0.65)
    specular_base = _safe_float(getattr(settings, "specular_base", 0.05), 0.05)
    specular_max = _safe_float(getattr(settings, "specular_max", 0.18), 0.18)
    shininess_min = _safe_float(getattr(settings, "shininess_min", 28.0), 28.0)
    shininess_max = _safe_float(getattr(settings, "shininess_max", 72.0), 72.0)
    if has_metal_preview_response:
        ambient_strength = max(min(ambient_strength, 0.62), 0.46)
        diffuse_light_scale = max(diffuse_light_scale, 0.72)
        specular_base = max(specular_base, 0.055)
        specular_max = max(specular_max, 0.42)
        shininess_min = min(shininess_min, 24.0)
        shininess_max = max(shininess_max, 128.0)
    tone_exposure = _safe_float(getattr(settings, "d3d11_tone_exposure", 1.0), 1.0)
    tone_contrast = _safe_float(getattr(settings, "d3d11_tone_contrast", 1.0), 1.0)
    tone_gamma = _safe_float(getattr(settings, "d3d11_tone_gamma", 1.0), 1.0)
    if has_metal_preview_response:
        tone_exposure = min(tone_exposure, 0.82)
        tone_contrast = max(tone_contrast, 1.08)
        tone_gamma = max(tone_gamma, 1.04)
    if aggregate_geometry_chunks:
        (geometry_dir / "geometry.bin").write_bytes(b"".join(aggregate_geometry_chunks))
    if aggregate_identity_chunks:
        (geometry_dir / "identity.bin").write_bytes(b"".join(aggregate_identity_chunks))
    package_write_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
    if trace_enabled:
        load_trace["package_write_ms"] = package_write_ms
    manifest = {
        "schema_version": ISOLATED_PREVIEW_SCHEMA_VERSION,
        "backend": str(backend or "d3d11").strip().lower(),
        "created_at": time.time(),
        "write_ms": package_write_ms,
        "load_trace": load_trace if trace_enabled else {},
        "display_mode": normalized_display_mode,
        "editor_workspace": str(editor_workspace or "").strip(),
        "source_path": str(getattr(prepared_preview, "source_path", "") or getattr(model, "path", "") or ""),
        "format": str(getattr(prepared_preview, "format", "") or getattr(model, "format", "") or ""),
        "summary": str(getattr(prepared_preview, "summary", "") or getattr(model, "summary", "") or ""),
        "mesh_count": _safe_int(getattr(prepared_preview, "mesh_count", 0), 0),
        "vertex_count": total_vertices,
        "face_count": _safe_int(getattr(prepared_preview, "face_count", 0), 0),
        "normalization_center": list(getattr(prepared_preview, "normalization_center", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)),
        "normalization_scale": _safe_float(getattr(prepared_preview, "normalization_scale", 1.0), 1.0),
        "render_settings": _render_settings_to_dict(settings),
        "orbit_sensitivity": _safe_float(getattr(settings, "orbit_sensitivity", 0.22), 0.22),
        "pan_sensitivity": _safe_float(getattr(settings, "pan_sensitivity", 0.60), 0.60),
        "invert_orbit_x": bool(getattr(settings, "invert_orbit_x", False)),
        "invert_orbit_y": bool(getattr(settings, "invert_orbit_y", False)),
        "invert_pan_x": bool(getattr(settings, "invert_pan_x", False)),
        "invert_pan_y": bool(getattr(settings, "invert_pan_y", False)),
        "use_textures": bool(use_textures),
        "high_quality_textures": bool(high_quality_textures),
        "texture_manifest": {
            "schema_version": 1,
            "texture_count": len(unique_texture_manifest),
            "textures": list(unique_texture_manifest.values()),
        },
        "render_diagnostic_mode": str(getattr(settings, "render_diagnostic_mode", "lit") or "lit"),
        "d3d11_view_mode": str(getattr(settings, "d3d11_view_mode", "lit") or "lit"),
        "d3d11_mip_lod_bias": _safe_float(getattr(settings, "d3d11_mip_lod_bias", -0.85), -0.85),
        "d3d11_cull_back_faces": bool(getattr(settings, "d3d11_cull_back_faces", False)),
        "d3d11_light_azimuth_degrees": _safe_float(
            getattr(settings, "d3d11_light_azimuth_degrees", -52.0),
            -52.0,
        ),
        "d3d11_light_elevation_degrees": _safe_float(
            getattr(settings, "d3d11_light_elevation_degrees", 27.0),
            27.0,
        ),
        "d3d11_normal_y_mode": str(getattr(settings, "d3d11_normal_y_mode", "asset") or "asset"),
        "d3d11_ao_strength": _safe_float(getattr(settings, "d3d11_ao_strength", 1.0), 1.0),
        "d3d11_roughness_bias": _safe_float(getattr(settings, "d3d11_roughness_bias", 0.0), 0.0),
        "d3d11_metalness_scale": _safe_float(getattr(settings, "d3d11_metalness_scale", 1.0), 1.0),
        "d3d11_environment_strength": _safe_float(getattr(settings, "d3d11_environment_strength", 1.0), 1.0),
        "d3d11_emissive_gain": _safe_float(getattr(settings, "d3d11_emissive_gain", 1.0), 1.0),
        "d3d11_tone_exposure": tone_exposure,
        "d3d11_tone_contrast": tone_contrast,
        "d3d11_tone_gamma": tone_gamma,
        "d3d11_texture_address_mode": str(getattr(settings, "d3d11_texture_address_mode", "wrap") or "wrap"),
        "lighting_preset": lighting_preset,
        "max_anisotropy": int(getattr(settings, "max_anisotropy", 16) or 16),
        "ambient_strength": ambient_strength,
        "diffuse_light_scale": diffuse_light_scale,
        "specular_base": specular_base,
        "specular_max": specular_max,
        "shininess_min": shininess_min,
        "shininess_max": shininess_max,
        "material_contract_schema": MATERIAL_CONTRACT_SCHEMA_VERSION,
        "material_channel_contract_schema": MATERIAL_CHANNEL_CONTRACT_SCHEMA_VERSION,
        "texture_quality_schema": TEXTURE_QUALITY_SCHEMA_VERSION,
        "texture_quality_policy": {
            "preview_texture_max_dimension": int(getattr(settings, "preview_texture_max_dimension", 16384) or 16384),
            "support_texture_max_dimension": int(getattr(settings, "low_quality_texture_max_dimension", 2048) or 2048),
            "upscale_handoff": "opt-in visible/base textures only",
            "technical_map_default": "preserve",
        },
        "cloth_runtime_schema": CLOTH_RUNTIME_SCHEMA_VERSION,
        "cloth_batch_count": cloth_batch_count,
        "cloth_particle_count": cloth_particle_count,
        "cloth_constraint_count": cloth_constraint_count,
        "cloth_collider_file": cloth_collider_file,
        "cloth_collider_count": cloth_collider_count,
        "physics_overlays": _physics_overlays_metadata(
            model,
            settings,
            cloth_batch_count=cloth_batch_count,
            cloth_particle_count=cloth_particle_count,
            cloth_constraint_count=cloth_constraint_count,
            cloth_collider_count=cloth_collider_count,
        ),
        "cloth_runtime_debug": _cloth_runtime_debug_metadata(
            settings,
            cloth_batch_count=cloth_batch_count,
            cloth_particle_count=cloth_particle_count,
            cloth_constraint_count=cloth_constraint_count,
            cloth_collider_count=cloth_collider_count,
        ),
        "skeleton_overlay": _skeleton_overlay_metadata(model),
        "editable_value_groups": _editable_value_groups_metadata(model, cloth_batch_count=cloth_batch_count),
        "batches": batches,
    }
    asset_preflight = asset_fidelity_preflight_manifest(manifest, package_dir=package_dir)
    manifest["asset_fidelity_preflight"] = asset_preflight
    manifest["dds_encoder_matrix"] = asset_preflight.get("dds_encoder_matrix", {})
    manifest["tangent_basis"] = asset_preflight.get("tangent_basis", {})
    manifest["import_preflight"] = asset_preflight.get("import_validators", {})
    manifest["mesh_health"] = asset_preflight.get("mesh_health", {})
    manifest["image_color_preflight"] = asset_preflight.get("image_color", {})
    manifest["normal_y_policy"] = asset_preflight.get("normal_y_policy", {})
    manifest["renderdoc_truth_pass"] = asset_preflight.get("renderdoc_truth_pass", {})
    manifest["shader_asset_fidelity_status"] = asset_preflight.get("shader_asset_fidelity_status", {})
    (package_dir / "manifest.json").write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
    _emit_progress(progress_total, progress_total, "D3D11 preview package manifest written.")
    return package_dir


def read_isolated_d3d11_preview_manifest(package_dir: Path) -> Mapping[str, Any]:
    manifest_path = Path(package_dir).expanduser() / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("isolated preview manifest is not a JSON object")
    if _safe_int(data.get("schema_version"), 0) not in SUPPORTED_ISOLATED_PREVIEW_SCHEMA_VERSIONS:
        raise ValueError(f"unsupported isolated preview schema version: {data.get('schema_version')!r}")
    return data


__all__ = [
    "NativePreviewBatchPayload",
    "build_native_preview_payloads",
    "ISOLATED_PREVIEW_SCHEMA_VERSION",
    "ISOLATED_PREVIEW_VERTEX_FLOATS",
    "ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES",
    "SUPPORTED_ISOLATED_PREVIEW_SCHEMA_VERSIONS",
    "read_isolated_d3d11_preview_manifest",
    "write_isolated_d3d11_preview_package",
]
