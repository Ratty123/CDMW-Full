from __future__ import annotations

from array import array
import dataclasses
import copy
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
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
from cdmw.modding.mesh_native_core import write_native_preview_identity_blob
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
from cdmw.rendering.native_preview_payloads import (
    ISOLATED_PREVIEW_VERTEX_FLOATS,
    ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES,
    NativePreviewBatchPayload,
    _batch_base_color,
    _batch_has_metal_preview_response,
    _batch_normal_texture_binding_allowed,
    _batch_tangents_usable,
    _clamp01,
    _contains_token,
    _input_texture_kind,
    _lighting_preset_for_settings,
    _local_file_url,
    _looks_like_normal_texture_path,
    _normal_texture_binding_allowed,
    _normal_texture_input_binding_allowed,
    _payload_material_inputs,
    _payload_material_slots,
    _safe_float,
    _safe_int,
    _suffix_tokens,
    _technical_texture_kind,
    _vector_length,
    build_native_preview_payloads,
)
from cdmw.rendering.native_preview_material_contract import (
    _MATERIAL_CONTRACT_SLOTS,
    _NATIVE_MATERIAL_OVERRIDE_KEYS,
    _NORMALIZED_MATERIAL_CONTRACT_SLOTS,
    _apply_nonmetal_material_scalar_limits,
    _batch_has_authoritative_family_material_response,
    _batch_has_explicit_metalness_slot,
    _batch_has_unlit_material_hint,
    _batch_weapon_masked_base_tint_should_stay_masked,
    _byte4_channels,
    _combiner_generated_authoritative_albedo,
    _descriptor_contains_token,
    _descriptor_has_local_strong_nonmetal_token,
    _descriptor_prefers_sidecar_tint,
    _effective_emissive_intensity,
    _input_is_true_base_color,
    _input_source_label,
    _jsonable_native_material_override,
    _manifest_material_diagnostics,
    _manifest_source_path_is_local_file,
    _masked_texturelayer_records,
    _material_base_policy_for_batch,
    _material_contract_for_batch,
    _material_contract_shader_family,
    _material_decode_policy,
    _material_decode_profile,
    _material_hex_color_rgb,
    _material_input_contract_slots,
    _material_input_descriptor,
    _material_input_slot_state,
    _material_input_to_dict,
    _material_lighting_preset,
    _material_sidecar_paths,
    _material_slot_diagnostics,
    _native_material_hints_for_batch,
    _native_material_overrides_for_batch,
    _nonmetal_material_scalar_limits,
    _normalized_material_key,
    _normalized_material_texture_slot_states,
    _normalized_shader_family,
    _preview_material_family_keys,
    _preview_material_keys_match,
    _preview_texture_family_key,
    _preview_texture_family_key_is_specific_material_response,
    _preview_tint_color_score,
    _preview_tint_color_visible,
    _render_settings_to_dict,
    _resolved_batch_material_category,
    _resolved_batch_material_category_reason,
    _resolved_batch_material_finish,
    _sanitize_nonfile_manifest_source_paths,
    _sidecar_preview_texture_tint_for_batch,
    _slot_has_resolved_texture,
    _source_or_descriptor_has_armor_equipment,
    _source_or_descriptor_has_weapon_surface,
    _texture_quality_summary,
    _texture_slot_state,
)
from cdmw.rendering.native_preview_texture_sources import (
    _batch_dds_manifest_cache_key,
    _copy_texture,
    _dds_manifest_entry,
    _dds_manifest_entry_is_native_usable,
    _dds_textures_for_batch,
    _filter_dds_textures_for_preview_settings,
    _link_or_copy_file,
    _materialize_in_memory_texture_key,
    _materialized_in_memory_batch,
    _source_dds_for_preview_path,
    _source_file_stat_key,
    _split_legacy_pbr_texture,
    _texture_copy_slot_policy,
    _texture_sources_for_batch,
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


ISOLATED_PREVIEW_SCHEMA_VERSION = 10
SUPPORTED_ISOLATED_PREVIEW_SCHEMA_VERSIONS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
MATERIAL_CONTRACT_SCHEMA_VERSION = 2
TEXTURE_QUALITY_SCHEMA_VERSION = 1
CLOTH_RUNTIME_SCHEMA_VERSION = 1
PREVIEW_OVERLAY_SCHEMA_VERSION = 1
_IDENTITY_STRUCT = struct.Struct("<iii")
MESH_EDITOR_LOAD_TRACE_ENV = "CDMW_MESH_EDITOR_LOAD_TRACE"


def _mesh_editor_load_trace_enabled() -> bool:
    return str(os.environ.get(MESH_EDITOR_LOAD_TRACE_ENV, "") or "").strip().lower() in {"1", "true", "yes", "on"}


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
    metadata = _editor_identity_metadata(batch, vertex_count, 0)
    source_vertex_range = _batch_source_range(batch, "source_vertex_range_start", "source_vertex_range_count")
    source_face_range = _batch_source_range(batch, "source_face_range_start", "source_face_range_count")
    raw_source_vertices = (
        ()
        if source_vertex_range is not None
        else (getattr(batch, "source_vertex_indices", ()) or ())
    )
    raw_source_faces = (
        ()
        if source_face_range is not None
        else (getattr(batch, "source_face_indices", ()) or ())
    )
    source_submesh_index = _safe_int(getattr(batch, "source_submesh_index", -1), -1)
    identity_blob = bytearray()
    for vertex_offset in range(vertex_count):
        source_vertex_index = (
            int(source_vertex_range[0] + vertex_offset)
            if source_vertex_range is not None and vertex_offset < source_vertex_range[1]
            else
            _source_index_at(raw_source_vertices, vertex_offset, vertex_offset)
        )
        face_offset = int(vertex_offset) // 3
        source_face_index = (
            int(source_face_range[0] + face_offset)
            if source_face_range is not None and face_offset < source_face_range[1]
            else
            _source_index_at(raw_source_faces, face_offset, face_offset)
        )
        identity_blob.extend(_IDENTITY_STRUCT.pack(source_submesh_index, source_vertex_index, source_face_index))
    metadata["identity_size"] = len(identity_blob)
    return metadata, bytes(identity_blob)


def _editor_identity_metadata(
    batch: PreparedModelPreviewBatch,
    vertex_count: int,
    identity_size: int,
) -> Dict[str, object]:
    source_submesh_index = _safe_int(getattr(batch, "source_submesh_index", -1), -1)
    role = str(getattr(batch, "editor_role", "") or "")
    role_key = role.strip().lower()
    reference_role = "reference" in role_key or "original" in role_key
    source_vertex_range = _batch_source_range(batch, "source_vertex_range_start", "source_vertex_range_count")
    source_face_range = _batch_source_range(batch, "source_face_range_start", "source_face_range_count")
    raw_source_vertices = (
        ()
        if source_vertex_range is not None
        else (getattr(batch, "source_vertex_indices", ()) or ())
    )
    raw_source_faces = (
        ()
        if source_face_range is not None
        else (getattr(batch, "source_face_indices", ()) or ())
    )
    source_vertex_max = _source_index_max(raw_source_vertices)
    source_face_max = _source_index_max(raw_source_faces)
    return {
        "source_submesh_index": source_submesh_index,
        "source_vertex_count": (
            source_vertex_range[0] + source_vertex_range[1]
            if source_vertex_range is not None
            else source_vertex_max + 1 if source_vertex_max >= 0 else 0
        ),
        "source_face_count": (
            source_face_range[0] + source_face_range[1]
            if source_face_range is not None
            else source_face_max + 1 if source_face_max >= 0 else 0
        ),
        "identity_stride_bytes": _IDENTITY_STRUCT.size,
        "identity_file": "",
        "identity_offset": 0,
        "identity_size": int(identity_size),
        "role": role,
        "part_name": str(getattr(batch, "editor_part_name", "") or ""),
        "editable": bool(getattr(batch, "editor_editable", source_submesh_index >= 0)) and not reference_role,
    }


def _source_index_count(values: object) -> int | None:
    try:
        count = len(values)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return max(0, int(count))


def _source_index_at(values: object, offset: int, fallback: int) -> int:
    count = _source_index_count(values)
    if count is not None and 0 <= offset < count:
        try:
            return int(values[offset])  # type: ignore[index]
        except (TypeError, ValueError, IndexError, KeyError, OverflowError):
            pass
    try:
        for item_offset, raw_value in enumerate(values or ()):  # type: ignore[arg-type]
            if item_offset == offset:
                return int(raw_value)
            if item_offset > offset:
                break
    except (TypeError, ValueError, OverflowError):
        pass
    return int(fallback)


def _source_index_max(values: object) -> int:
    count = _source_index_count(values)
    if count is not None:
        max_value = -1
        indexed = True
        for offset in range(count):
            try:
                value = int(values[offset])  # type: ignore[index]
            except (TypeError, ValueError, IndexError, KeyError, OverflowError):
                indexed = False
                break
            max_value = max(max_value, value)
        if indexed:
            return max_value
    max_value = -1
    try:
        for raw_value in values or ():  # type: ignore[arg-type]
            max_value = max(max_value, int(raw_value))
    except (TypeError, ValueError, OverflowError):
        return -1
    return max_value


def _batch_source_range(batch: PreparedModelPreviewBatch, start_attr: str, count_attr: str) -> Tuple[int, int] | None:
    start = _safe_int(getattr(batch, start_attr, -1), -1)
    count = _safe_int(getattr(batch, count_attr, 0), 0)
    if start < 0 or count <= 0:
        return None
    return start, count


def _batch_source_i32_descriptor(batch: PreparedModelPreviewBatch, attr: str) -> Dict[str, object] | None:
    value = getattr(batch, attr, None)
    if not isinstance(value, Mapping):
        return None
    path = str(value.get("path") or "").strip()
    if not path:
        return None
    try:
        count = int(value.get("count", 0) or 0)
        components = int(value.get("components", 1) or 1)
    except (TypeError, ValueError, OverflowError):
        return None
    if count < 0 or components != 1:
        return None
    if str(value.get("type") or "i32").strip().lower() != "i32":
        return None
    descriptor: Dict[str, object] = {
        "path": path,
        "count": count,
        "components": 1,
        "type": "i32",
    }
    if bool(value.get("delete_after")):
        descriptor["delete_after"] = True
    return descriptor


def _write_identity_source_i32_sidecar(
    identity_path: Path,
    batch: PreparedModelPreviewBatch,
    suffix: str,
    values: object,
) -> Dict[str, object] | None:
    if values is None:
        return None
    try:
        if len(values) <= 0:  # type: ignore[arg-type]
            return None
    except TypeError:
        pass
    data = array("i")
    if data.itemsize != 4:
        return None
    try:
        data.extend(values)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        data = array("i")
        try:
            data.extend(int(index) for index in values)  # type: ignore[union-attr]
        except (TypeError, ValueError, OverflowError):
            return None
    if not data:
        return None
    sidecar_path = identity_path.with_name(f"{identity_path.stem}_{id(batch):x}_{suffix}.bin")
    try:
        sidecar_path.write_bytes(data.tobytes())
    except OSError:
        return None
    return {
        "path": str(sidecar_path),
        "count": len(data),
        "components": 1,
        "type": "i32",
    }


def _source_values_nonempty(values: object) -> bool:
    if values is None:
        return False
    try:
        return len(values) > 0  # type: ignore[arg-type]
    except TypeError:
        return True


def _cleanup_identity_sidecars(paths: Sequence[Path]) -> None:
    for sidecar_path in paths:
        try:
            sidecar_path.unlink(missing_ok=True)
        except OSError:
            pass


def _write_editor_identity_blob_native(
    identity_path: Path,
    batch: PreparedModelPreviewBatch,
    vertex_count: int,
) -> Dict[str, object] | None:
    source_submesh_index = _safe_int(getattr(batch, "source_submesh_index", -1), -1)
    role = str(getattr(batch, "editor_role", "") or "")
    source_vertex_indices_binary = _batch_source_i32_descriptor(batch, "source_vertex_indices_binary")
    source_face_indices_binary = _batch_source_i32_descriptor(batch, "source_face_indices_binary")
    source_vertex_range = None if source_vertex_indices_binary is not None else _batch_source_range(
        batch,
        "source_vertex_range_start",
        "source_vertex_range_count",
    )
    source_face_range = None if source_face_indices_binary is not None else _batch_source_range(
        batch,
        "source_face_range_start",
        "source_face_range_count",
    )
    sidecar_paths: list[Path] = []
    if source_vertex_indices_binary is None and source_vertex_range is None:
        source_vertex_values = getattr(batch, "source_vertex_indices", ()) or ()
        source_vertex_indices_binary = _write_identity_source_i32_sidecar(
            identity_path,
            batch,
            "source_vertices",
            source_vertex_values,
        )
        if source_vertex_indices_binary is not None:
            sidecar_paths.append(Path(str(source_vertex_indices_binary["path"])))
        elif _source_values_nonempty(source_vertex_values):
            _cleanup_identity_sidecars(sidecar_paths)
            return None
    if source_face_indices_binary is None and source_face_range is None:
        source_face_values = getattr(batch, "source_face_indices", ()) or ()
        source_face_indices_binary = _write_identity_source_i32_sidecar(
            identity_path,
            batch,
            "source_faces",
            source_face_values,
        )
        if source_face_indices_binary is not None:
            sidecar_paths.append(Path(str(source_face_indices_binary["path"])))
        elif _source_values_nonempty(source_face_values):
            _cleanup_identity_sidecars(sidecar_paths)
            return None
    try:
        report = write_native_preview_identity_blob(
            identity_path,
            source_submesh_index=source_submesh_index,
            vertex_count=vertex_count,
            source_vertex_indices=(),
            source_face_indices=(),
            source_vertex_indices_binary=source_vertex_indices_binary,
            source_face_indices_binary=source_face_indices_binary,
            source_vertex_start=None if source_vertex_range is None else source_vertex_range[0],
            source_vertex_count=0 if source_vertex_range is None else source_vertex_range[1],
            source_face_start=None if source_face_range is None else source_face_range[0],
            source_face_count=0 if source_face_range is None else source_face_range[1],
            role=role,
            part_name=str(getattr(batch, "editor_part_name", "") or ""),
            editable=bool(getattr(batch, "editor_editable", source_submesh_index >= 0)),
            append=True,
        )
    finally:
        _cleanup_identity_sidecars(sidecar_paths)
    if not isinstance(report, Mapping):
        return None
    return {
        "source_submesh_index": _safe_int(report.get("source_submesh_index"), source_submesh_index),
        "source_vertex_count": _safe_int(report.get("source_vertex_count"), 0),
        "source_face_count": _safe_int(report.get("source_face_count"), 0),
        "identity_stride_bytes": _safe_int(report.get("identity_stride_bytes"), _IDENTITY_STRUCT.size),
        "identity_file": "",
        "identity_offset": 0,
        "identity_size": _safe_int(report.get("identity_size"), vertex_count * _IDENTITY_STRUCT.size),
        "role": str(report.get("role", role) or ""),
        "part_name": str(report.get("part_name", getattr(batch, "editor_part_name", "") or "") or ""),
        "editable": bool(report.get("editable", False)),
    }


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


def _manifest_tuple3(value: object, default: Tuple[float, float, float] = (0.0, 0.0, 0.0)) -> Tuple[float, float, float]:
    parsed = _tuple3(value)
    return parsed if parsed else default


def _placement_frame_manifest(model: object, prepared_preview: PreparedModelPreviewData) -> Dict[str, object]:
    frame_kind = str(
        getattr(prepared_preview, "preview_frame_kind", "")
        or getattr(model, "preview_frame_kind", "")
        or ""
    ).strip()
    grid_mode = str(
        getattr(prepared_preview, "preview_grid_mode", "")
        or getattr(model, "preview_grid_mode", "")
        or ""
    ).strip()
    material_parity = str(
        getattr(prepared_preview, "preview_material_parity_mode", "")
        or getattr(model, "preview_material_parity_mode", "")
        or ""
    ).strip()
    preserve_original_materials = bool(
        getattr(prepared_preview, "preview_original_materials_preserved", False)
        or getattr(model, "preview_original_materials_preserved", False)
    )
    reference_tint_mode = str(
        getattr(prepared_preview, "preview_reference_tint_mode", "")
        or getattr(model, "preview_reference_tint_mode", "")
        or ""
    ).strip()
    if not any((frame_kind, grid_mode, material_parity, preserve_original_materials, reference_tint_mode)):
        return {}
    center = _manifest_tuple3(getattr(prepared_preview, "normalization_center", (0.0, 0.0, 0.0)))
    scale = _safe_float(getattr(prepared_preview, "normalization_scale", 1.0), 1.0)
    if not math.isfinite(scale) or abs(scale) <= 1e-8:
        scale = 1.0
    grid_y = _safe_float(
        getattr(prepared_preview, "preview_grid_y", getattr(model, "preview_grid_y", 0.0)),
        0.0,
    )
    if not math.isfinite(grid_y):
        grid_y = 0.0
    grid_origin = _manifest_tuple3(
        getattr(prepared_preview, "preview_grid_origin", getattr(model, "preview_grid_origin", (0.0, grid_y, 0.0))),
        (0.0, grid_y, 0.0),
    )
    source_path = str(
        getattr(prepared_preview, "preview_frame_source_path", "")
        or getattr(model, "preview_frame_source_path", "")
        or getattr(prepared_preview, "source_path", "")
        or getattr(model, "path", "")
        or ""
    )
    return {
        "schema_version": 1,
        "kind": frame_kind or "original_pac_frame",
        "source_path": source_path,
        "normalization_center": list(center),
        "normalization_scale": scale,
        "grid_origin": list(grid_origin),
        "grid_normal_axis": str(
            getattr(prepared_preview, "preview_grid_normal_axis", "")
            or getattr(model, "preview_grid_normal_axis", "")
            or "y"
        ),
        "grid_y": grid_y,
        "grid_mode": grid_mode or "original_frame",
        "material_parity": material_parity or "archive_preview",
        "preserve_original_materials": preserve_original_materials,
        "reference_tint_mode": reference_tint_mode or "overlay_only",
    }


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
    pose_rotations = _skeleton_pose_rotations_metadata(getattr(overlay, "skeleton_pose_rotations", ()) if overlay is not None else ())
    bone_payload = []
    for bone in bones[:4096]:
        position = _tuple3(getattr(bone, "position", ()) or ())
        parent_position = _tuple3(getattr(bone, "parent_position", ()) or ())
        bone_payload.append(
            {
                "name": str(getattr(bone, "name", "") or ""),
                "index": _safe_int(getattr(bone, "index", -1), -1),
                "parent_index": _safe_int(getattr(bone, "parent_index", -1), -1),
                "parent_name": str(getattr(bone, "parent_name", "") or ""),
                "position": list(position),
                "parent_position": list(parent_position),
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
        "pose_enabled": bool(getattr(overlay, "skeleton_pose_enabled", False)) and bool(bone_payload),
        "selected_bone_index": _safe_int(getattr(overlay, "skeleton_selected_bone_index", -1), -1),
        "posed_bone_count": len(pose_rotations),
        "pose_rotations": pose_rotations,
        "bones": bone_payload,
        "diagnostics": [] if bone_payload else ["related skeleton/HKX/HKT data was not resolved for this preview"],
    }


def _skeleton_pose_rotations_metadata(value: object) -> list[Dict[str, object]]:
    records: list[Dict[str, object]] = []
    try:
        items = tuple(value or ())  # type: ignore[arg-type]
    except TypeError:
        return records
    for raw_item in items[:4096]:
        try:
            bone_index, raw_rotation = raw_item  # type: ignore[misc]
        except (TypeError, ValueError):
            continue
        rotation = _tuple3(raw_rotation)
        if not rotation or not any(abs(component) > 1e-6 for component in rotation):
            continue
        records.append({"bone_index": _safe_int(bone_index, -1), "rotation_degrees": list(rotation)})
    return [record for record in records if int(record["bone_index"]) >= 0]


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
        return bool(enable_material_combiner), True, "original_reference_archive_parity"
    if role == "replacement_preview":
        if workspace == "modify_original_alignment" and original_reference_material_parity:
            return bool(enable_material_combiner), True, "modify_original_archive_parity"
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
    if bool(original_reference_material_parity) and str(editor_workspace or "").strip().lower() in {
        "mesh_replacement_alignment",
        "modify_original_alignment",
    }:
        settings = dataclasses.replace(settings, disable_tint=False)
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
    aggregate_identity_path = geometry_dir / "identity.bin"
    try:
        aggregate_identity_path.unlink(missing_ok=True)
    except OSError:
        pass
    aggregate_geometry_chunks: list[bytes] = []
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
        identity_offset = aggregate_identity_size
        expected_identity_size = vertex_count * _IDENTITY_STRUCT.size
        precomputed_identity_blob = bytes(getattr(batch, "editor_identity_blob", b"") or b"")
        source_indices_are_descriptor_backed = (
            _batch_source_i32_descriptor(batch, "source_vertex_indices_binary") is not None
            or _batch_source_i32_descriptor(batch, "source_face_indices_binary") is not None
        )
        used_precomputed_identity = len(precomputed_identity_blob) == expected_identity_size and not source_indices_are_descriptor_backed
        if used_precomputed_identity:
            editor_identity = _editor_identity_metadata(batch, vertex_count, expected_identity_size)
            if precomputed_identity_blob:
                with aggregate_identity_path.open("ab") as identity_stream:
                    identity_stream.write(precomputed_identity_blob)
            identity_size = expected_identity_size
        else:
            editor_identity = _write_editor_identity_blob_native(aggregate_identity_path, batch, vertex_count)
        if editor_identity is None:
            if source_indices_are_descriptor_backed:
                raise RuntimeError("native preview identity generation failed for descriptor-backed source ids")
            editor_identity, identity_blob = _editor_identity_blob(batch, vertex_count)
            if identity_blob:
                with aggregate_identity_path.open("ab") as identity_stream:
                    identity_stream.write(identity_blob)
            identity_size = len(identity_blob)
        elif not used_precomputed_identity:
            identity_size = _safe_int(editor_identity.get("identity_size"), vertex_count * _IDENTITY_STRUCT.size)
        aggregate_identity_size += identity_size
        editor_identity["identity_file"] = aggregate_identity_file
        editor_identity["identity_offset"] = identity_offset
        editor_identity["identity_size"] = identity_size
        tangents_usable = _batch_tangents_usable(batch, usable_blob, vertex_count)
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
        archive_direct_material_policy = False
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
        if material_policy == "original_reference_archive_parity":
            notes = tuple(notes) + (
                "original reference material policy: archive preview direct DDS sidecar parity",
            )
        elif material_policy == "modify_original_archive_parity":
            notes = tuple(notes) + (
                "archive preview material combiner enabled",
                "modify-original material policy: archive preview direct DDS sidecar parity",
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
        if not (textures.get("normal") or dds_textures.get("normal")):
            normal_strength = 0.0
        height_amount = max(0.0, min(0.08, _safe_float(getattr(settings, "height_effect_max", 0.35), 0.35) * 0.08))
        if _safe_float(combiner_metadata.get("height_amount", 0.0), 0.0) > 0.0:
            height_amount = max(0.0, min(0.12, _safe_float(combiner_metadata.get("height_amount"), height_amount)))
        texture_flip_vertical = resolve_preview_texture_flip_vertical(
            getattr(batch, "preview_texture_flip_vertical", None),
            source_format=getattr(prepared_preview, "format", "") or getattr(model, "format", ""),
            source_path=getattr(prepared_preview, "source_path", "") or getattr(model, "path", ""),
            default=False,
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
        if material_policy in {"original_reference_archive_parity", "modify_original_archive_parity"} and tint_active:
            notes = tuple(notes) + ("archive parity tint kept enabled",)
        batch_payload = {
                "index": batch_index,
                "material_name": str(getattr(batch, "material_name", "") or ""),
                "texture_name": str(getattr(batch, "texture_name", "") or ""),
                "vertex_file": aggregate_geometry_file,
                "vertex_offset": geometry_offset,
                "vertex_size": len(usable_blob),
                "vertex_count": vertex_count,
                "editor_identity": editor_identity,
                "base_color": list(_batch_base_color(batch, usable_blob)),
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
            if str(material_category or "").strip().lower() in {"cloth", "leather", "wood", "skin", "hair", "stone", "tooth"}:
                batch_payload["roughness"] = _safe_float(material_hints.get("roughness"), 0.55)
                batch_payload["metalness"] = _safe_float(material_hints.get("metalness"), 0.0)
                batch_payload["specular"] = _safe_float(material_hints.get("specular"), 0.08)
                batch_payload["native_material_hints"] = material_hints
                material_analysis = batch_payload.get("material_analysis")
                if isinstance(material_analysis, dict):
                    material_analysis["roughness_hint"] = batch_payload["roughness"]
                    material_analysis["metalness_hint"] = batch_payload["metalness"]
                    material_analysis["specular_hint"] = batch_payload["specular"]
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
        batches.append(_sanitize_nonfile_manifest_source_paths(batch_payload))
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
    ambient_strength = _safe_float(getattr(settings, "ambient_strength", 0.84), 0.84)
    diffuse_wrap_bias = _safe_float(getattr(settings, "diffuse_wrap_bias", 0.58), 0.58)
    diffuse_light_scale = _safe_float(getattr(settings, "diffuse_light_scale", 0.62), 0.62)
    specular_base = _safe_float(getattr(settings, "specular_base", 0.055), 0.055)
    specular_max = _safe_float(getattr(settings, "specular_max", 0.52), 0.52)
    shininess_min = _safe_float(getattr(settings, "shininess_min", 28.0), 28.0)
    shininess_max = _safe_float(getattr(settings, "shininess_max", 152.0), 152.0)
    tone_exposure = _safe_float(getattr(settings, "d3d11_tone_exposure", 1.00), 1.00)
    tone_contrast = _safe_float(getattr(settings, "d3d11_tone_contrast", 1.08), 1.08)
    tone_gamma = _safe_float(getattr(settings, "d3d11_tone_gamma", 1.00), 1.00)
    if aggregate_geometry_chunks:
        (geometry_dir / "geometry.bin").write_bytes(b"".join(aggregate_geometry_chunks))
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
        "d3d11_mip_lod_bias": _safe_float(getattr(settings, "d3d11_mip_lod_bias", -2.0), -2.0),
        "d3d11_cull_back_faces": bool(getattr(settings, "d3d11_cull_back_faces", False)),
        "d3d11_light_azimuth_degrees": _safe_float(
            getattr(settings, "d3d11_light_azimuth_degrees", -10.0),
            -10.0,
        ),
        "d3d11_light_elevation_degrees": _safe_float(
            getattr(settings, "d3d11_light_elevation_degrees", 0.0),
            0.0,
        ),
        "d3d11_normal_y_mode": str(getattr(settings, "d3d11_normal_y_mode", "asset") or "asset"),
        "d3d11_ao_strength": _safe_float(getattr(settings, "d3d11_ao_strength", 0.45), 0.45),
        "d3d11_roughness_bias": _safe_float(getattr(settings, "d3d11_roughness_bias", -0.04), -0.04),
        "d3d11_metalness_scale": _safe_float(getattr(settings, "d3d11_metalness_scale", 1.45), 1.45),
        "d3d11_environment_strength": _safe_float(getattr(settings, "d3d11_environment_strength", 0.62), 0.62),
        "d3d11_emissive_gain": _safe_float(getattr(settings, "d3d11_emissive_gain", 2.2), 2.2),
        "d3d11_tone_exposure": tone_exposure,
        "d3d11_tone_contrast": tone_contrast,
        "d3d11_tone_gamma": tone_gamma,
        "d3d11_texture_address_mode": str(getattr(settings, "d3d11_texture_address_mode", "wrap") or "wrap"),
        "lighting_preset": lighting_preset,
        "max_anisotropy": int(getattr(settings, "max_anisotropy", 16) or 16),
        "ambient_strength": ambient_strength,
        "diffuse_wrap_bias": diffuse_wrap_bias,
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
    placement_frame = _placement_frame_manifest(model, prepared_preview)
    if placement_frame:
        manifest["placement_frame"] = placement_frame
        manifest["reference_material_policy"] = "preserve"
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
