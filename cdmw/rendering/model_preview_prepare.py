from __future__ import annotations

from array import array
from dataclasses import dataclass, fields as dataclass_fields
import hashlib
import math
from pathlib import Path
import tempfile
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QMatrix4x4, QVector3D

from cdmw.core.dds_native import dds_source_path_from_report
from cdmw.core.model_preview_orientation import resolve_preview_texture_flip_vertical
from cdmw.models import (
    ModelPreviewData,
    ModelPreviewMesh,
    ModelPreviewRenderSettings,
    PreparedModelPreviewBatch,
    PreparedModelPreviewData,
    PreviewMaterialTextureInput,
    RunCancelled,
    clamp_model_preview_render_settings,
)


FIT_DISTANCE = 3.25
OVERLAY_CLIP_EPSILON = 1e-5
PALETTE = (
    (201 / 255.0, 111 / 255.0, 81 / 255.0),
    (94 / 255.0, 133 / 255.0, 168 / 255.0),
    (156 / 255.0, 167 / 255.0, 98 / 255.0),
    (198 / 255.0, 176 / 255.0, 92 / 255.0),
    (147 / 255.0, 112 / 255.0, 166 / 255.0),
)


@dataclass(slots=True)
class ModelPreviewDrawBatch:
    mesh_index: int
    material_name: str
    texture_name: str
    first_vertex: int
    vertex_count: int
    texture_key: str = ""
    texture_dds_key: str = ""
    normal_texture_key: str = ""
    normal_texture_dds_key: str = ""
    normal_texture_strength: float = 0.0
    material_texture_key: str = ""
    material_texture_dds_key: str = ""
    material_texture_type: str = ""
    material_texture_subtype: str = ""
    material_texture_packed_channels: Tuple[str, ...] = ()
    material_decode_mode: int = 0
    height_texture_key: str = ""
    height_texture_dds_key: str = ""
    support_maps_disabled: bool = False
    has_texture_coordinates: bool = False
    texture_wrap_repeat: bool = False
    texture_flip_vertical: bool = True
    base_texture_quality: str = ""
    texture_brightness: float = 1.0
    texture_tint: Tuple[float, float, float] = ()
    texture_uv_scale: Tuple[float, float] = ()
    source_average_color: Tuple[float, float, float] = ()
    source_average_luma: float = 0.0
    normal_finite_ratio: float = 1.0
    normal_repair_count: int = 0
    tangent_finite_ratio: float = 1.0
    bitangent_finite_ratio: float = 1.0
    uv_finite_ratio: float = 1.0
    smooth_normal_ratio: float = 0.0
    position_y_min: float = 0.0
    position_y_max: float = 0.0


@dataclass(slots=True)
class TextureVisibilitySample:
    average_color: Tuple[float, float, float]
    average_luma: float
    dark_ratio: float
    average_alpha: float = 1.0
    alpha_dark_ratio: float = 0.0
    alpha_weighted_luma: float = 0.0
    min_luma: float = 0.0
    max_luma: float = 0.0
    luma_contrast: float = 0.0


@dataclass(slots=True)
class FramebufferVisibilitySample:
    visible_pixels: int = 0
    average_luma: float = 0.0
    dark_ratio: float = 0.0
    background_ratio: float = 1.0


@dataclass(slots=True)
class BatchRenderDiagnostic:
    batch_index: int
    mesh_index: int
    label: str
    texture_key: str = ""
    texture_path_set: bool = False
    image_loaded: bool = False
    image_size: str = "-"
    uv_valid: bool = False
    uv_count: int = 0
    position_count: int = 0
    texture_uploaded: bool = False
    texture_id: int = 0
    normal_texture_id: int = 0
    material_texture_id: int = 0
    height_texture_id: int = 0
    relief_texture_id: int = 0
    diffuse_unit: int = 0
    diffuse_sampler_location: int = -1
    render_mode_code: int = 0
    alpha_handling_mode: str = "default"
    texture_probe_source: str = "base"
    sampler_probe_mode: str = "normal"
    diffuse_swizzle_mode: str = "rgba"
    base_texture_quality: str = ""
    material_decode_mode: int = 0
    rich_material_response: bool = False
    prepared_image_size: str = "-"
    gl_error: str = ""
    alpha_discard_risk: bool = False
    use_texture: bool = False
    use_normal: bool = False
    use_material: bool = False
    use_height: bool = False
    use_relief: bool = False
    normal_uploaded: bool = False
    material_uploaded: bool = False
    height_uploaded: bool = False
    failure_bucket: str = ""
    failure_reason: str = ""
    sampled_luma: Optional[float] = None
    sampled_dark_ratio: Optional[float] = None
    sampled_alpha: Optional[float] = None
    material_sampled_luma: Optional[float] = None
    material_sampled_dark_ratio: Optional[float] = None
    material_sampled_alpha: Optional[float] = None
    height_sampled_luma: Optional[float] = None
    height_sampled_dark_ratio: Optional[float] = None
    height_sampled_alpha: Optional[float] = None
    height_sampled_min_luma: Optional[float] = None
    height_sampled_max_luma: Optional[float] = None
    height_sampled_contrast: Optional[float] = None
    derived_relief_sampled_luma: Optional[float] = None
    derived_relief_sampled_min_luma: Optional[float] = None
    derived_relief_sampled_max_luma: Optional[float] = None
    derived_relief_sampled_contrast: Optional[float] = None
    enhanced_relief_state: str = ""
    enhanced_relief_reason: str = ""
    relief_source: str = ""
    normal_average_strength: Optional[float] = None
    source_average_color: Tuple[float, float, float] = ()
    normal_finite_ratio: float = 1.0
    normal_repair_count: int = 0
    tangent_finite_ratio: float = 1.0
    bitangent_finite_ratio: float = 1.0
    uv_finite_ratio: float = 1.0
    smooth_normal_ratio: float = 0.0
    texture_flip_vertical: bool = True
    texture_wrap_repeat: bool = False
    texture_brightness: float = 1.0
    texture_tint: Tuple[float, float, float] = ()
    texture_uv_scale: Tuple[float, float] = ()
    visibility_guard: str = ""
    final_bucket: str = ""
    native_texture_backend: str = ""
    native_texture_status: str = ""
    native_texture_format: str = ""
    native_texture_slot: str = ""
    native_texture_normal_space: str = ""
    native_texture_normal_strength: float = 0.0
    native_texture_alpha_coverage: float = 0.0
    native_texture_scalar_range: Tuple[float, float] = ()


def finite_float(value: object, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def clone_model_preview(model: object) -> object:
    if not isinstance(model, ModelPreviewData):
        return model
    cloned_meshes = []
    for mesh in getattr(model, "meshes", []) or []:
        if isinstance(mesh, ModelPreviewMesh):
            cloned_meshes.append(
                ModelPreviewMesh(
                    **{field_info.name: getattr(mesh, field_info.name) for field_info in dataclass_fields(ModelPreviewMesh)}
                )
            )
        else:
            cloned_meshes.append(mesh)
    return ModelPreviewData(
        **{
            field_info.name: cloned_meshes if field_info.name == "meshes" else getattr(model, field_info.name)
            for field_info in dataclass_fields(ModelPreviewData)
        }
    )


def initialize_mesh_preview_slot_defaults(mesh: ModelPreviewMesh) -> None:
    if (
        not str(getattr(mesh, "preview_base_texture_default_path", "") or "").strip()
        and not str(getattr(mesh, "preview_base_texture_default_name", "") or "").strip()
    ):
        mesh.preview_base_texture_default_path = str(getattr(mesh, "preview_texture_path", "") or "").strip()
        mesh.preview_base_texture_default_name = str(getattr(mesh, "texture_name", "") or "").strip()
    if (
        not str(getattr(mesh, "preview_normal_texture_default_path", "") or "").strip()
        and not str(getattr(mesh, "preview_normal_texture_default_name", "") or "").strip()
    ):
        mesh.preview_normal_texture_default_path = str(getattr(mesh, "preview_normal_texture_path", "") or "").strip()
        mesh.preview_normal_texture_default_name = str(getattr(mesh, "preview_normal_texture_name", "") or "").strip()
        mesh.preview_normal_texture_default_strength = float(getattr(mesh, "preview_normal_texture_strength", 0.0) or 0.0)
    if (
        not str(getattr(mesh, "preview_material_texture_default_path", "") or "").strip()
        and not str(getattr(mesh, "preview_material_texture_default_name", "") or "").strip()
    ):
        mesh.preview_material_texture_default_path = str(getattr(mesh, "preview_material_texture_path", "") or "").strip()
        mesh.preview_material_texture_default_name = str(getattr(mesh, "preview_material_texture_name", "") or "").strip()
        mesh.preview_material_texture_default_type = str(getattr(mesh, "preview_material_texture_type", "") or "").strip()
        mesh.preview_material_texture_default_subtype = str(getattr(mesh, "preview_material_texture_subtype", "") or "").strip()
        mesh.preview_material_texture_default_packed_channels = tuple(
            str(channel or "").strip().lower()
            for channel in (getattr(mesh, "preview_material_texture_packed_channels", ()) or ())
            if str(channel or "").strip()
        )
    if (
        not str(getattr(mesh, "preview_height_texture_default_path", "") or "").strip()
        and not str(getattr(mesh, "preview_height_texture_default_name", "") or "").strip()
    ):
        mesh.preview_height_texture_default_path = str(getattr(mesh, "preview_height_texture_path", "") or "").strip()
        mesh.preview_height_texture_default_name = str(getattr(mesh, "preview_height_texture_name", "") or "").strip()


def dds_source_path_for_preview_path(preview_path: str) -> str:
    normalized_key = str(preview_path or "").strip()
    if not normalized_key or normalized_key.lower().startswith("in_memory"):
        return ""
    try:
        direct_source = Path(normalized_key).expanduser()
        if direct_source.suffix.lower() == ".dds" and direct_source.is_file():
            return str(direct_source)
    except OSError:
        pass
    try:
        from cdmw.core.texture_native import read_native_texture_report_sidecar

        report = read_native_texture_report_sidecar(Path(normalized_key))
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


def _sanitize_vector3(
    vector: object,
    *,
    fallback: Tuple[float, float, float],
    normalize: bool = False,
) -> Tuple[Tuple[float, float, float], bool]:
    repaired = False
    try:
        x = finite_float(vector[0], fallback[0])  # type: ignore[index]
        y = finite_float(vector[1], fallback[1])  # type: ignore[index]
        z = finite_float(vector[2], fallback[2])  # type: ignore[index]
    except Exception:
        x, y, z = fallback
        repaired = True
    if normalize:
        length = math.sqrt((x * x) + (y * y) + (z * z))
        if length <= 1e-8 or not math.isfinite(length):
            return fallback, True
        x /= length
        y /= length
        z /= length
    return (x, y, z), repaired


def _sanitize_uv(uv: object) -> Tuple[Tuple[float, float], bool]:
    try:
        u = finite_float(uv[0], 0.0)  # type: ignore[index]
        v = finite_float(uv[1], 0.0)  # type: ignore[index]
    except Exception:
        return (0.0, 0.0), True
    return (u, v), False


def _sanitize_color3(color: Sequence[object], *, fallback: Tuple[float, float, float]) -> Tuple[float, float, float]:
    if len(color) < 3:
        return fallback
    return (
        max(0.0, min(1.0, finite_float(color[0], fallback[0]))),
        max(0.0, min(1.0, finite_float(color[1], fallback[1]))),
        max(0.0, min(1.0, finite_float(color[2], fallback[2]))),
    )


def _orthogonal_tangent_frame(normal: Tuple[float, float, float]) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    nx, ny, nz = normal
    length = math.sqrt((nx * nx) + (ny * ny) + (nz * nz))
    if length <= 1e-8 or not math.isfinite(length):
        nx, ny, nz = (0.0, 0.0, 1.0)
    else:
        nx /= length
        ny /= length
        nz /= length
    tangent = (0.0, 0.0, 1.0) if abs(nz) < 0.999 else (1.0, 0.0, 0.0)
    tx = tangent[1] * nz - tangent[2] * ny
    ty = tangent[2] * nx - tangent[0] * nz
    tz = tangent[0] * ny - tangent[1] * nx
    tangent_length = max((tx * tx + ty * ty + tz * tz) ** 0.5, 1e-6)
    tx /= tangent_length
    ty /= tangent_length
    tz /= tangent_length
    bx = ny * tz - nz * ty
    by = nz * tx - nx * tz
    bz = nx * ty - ny * tx
    bitangent_length = max((bx * bx + by * by + bz * bz) ** 0.5, 1e-6)
    bx /= bitangent_length
    by /= bitangent_length
    bz /= bitangent_length
    return (tx, ty, tz), (bx, by, bz)


def _build_tangent_frames(
    positions: Sequence[Tuple[float, float, float]],
    texture_coordinates: Sequence[Tuple[float, float]],
    normals: Sequence[Tuple[float, float, float]],
    indices: Sequence[int],
) -> Tuple[List[Tuple[float, float, float]], List[Tuple[float, float, float]], List[bool], List[bool]]:
    vertex_count = len(positions)
    if vertex_count <= 0 or len(texture_coordinates) != vertex_count or len(normals) != vertex_count:
        tangents = []
        bitangents = []
        for normal in normals or [(0.0, 0.0, 1.0)] * max(vertex_count, 1):
            tangent, bitangent = _orthogonal_tangent_frame(normal)
            tangents.append(tangent)
            bitangents.append(bitangent)
        return tangents[:vertex_count], bitangents[:vertex_count], [False] * vertex_count, [False] * vertex_count

    tangent_accum = [[0.0, 0.0, 0.0] for _ in range(vertex_count)]
    bitangent_accum = [[0.0, 0.0, 0.0] for _ in range(vertex_count)]
    tangent_valid = [False] * vertex_count
    bitangent_valid = [False] * vertex_count
    for triangle_index in range(0, len(indices) - 2, 3):
        a = indices[triangle_index]
        b = indices[triangle_index + 1]
        c = indices[triangle_index + 2]
        if a < 0 or b < 0 or c < 0 or a >= vertex_count or b >= vertex_count or c >= vertex_count:
            continue
        p0 = positions[a]
        p1 = positions[b]
        p2 = positions[c]
        uv0 = texture_coordinates[a]
        uv1 = texture_coordinates[b]
        uv2 = texture_coordinates[c]
        edge1 = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
        edge2 = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])
        delta_uv1 = (uv1[0] - uv0[0], uv1[1] - uv0[1])
        delta_uv2 = (uv2[0] - uv0[0], uv2[1] - uv0[1])
        determinant = (delta_uv1[0] * delta_uv2[1]) - (delta_uv1[1] * delta_uv2[0])
        if abs(determinant) <= 1e-8:
            continue
        reciprocal = 1.0 / determinant
        tangent = (
            reciprocal * ((delta_uv2[1] * edge1[0]) - (delta_uv1[1] * edge2[0])),
            reciprocal * ((delta_uv2[1] * edge1[1]) - (delta_uv1[1] * edge2[1])),
            reciprocal * ((delta_uv2[1] * edge1[2]) - (delta_uv1[1] * edge2[2])),
        )
        bitangent = (
            reciprocal * ((-delta_uv2[0] * edge1[0]) + (delta_uv1[0] * edge2[0])),
            reciprocal * ((-delta_uv2[0] * edge1[1]) + (delta_uv1[0] * edge2[1])),
            reciprocal * ((-delta_uv2[0] * edge1[2]) + (delta_uv1[0] * edge2[2])),
        )
        tangent_length = math.sqrt((tangent[0] * tangent[0]) + (tangent[1] * tangent[1]) + (tangent[2] * tangent[2]))
        bitangent_length = math.sqrt((bitangent[0] * bitangent[0]) + (bitangent[1] * bitangent[1]) + (bitangent[2] * bitangent[2]))
        if tangent_length <= 1e-8 or bitangent_length <= 1e-8 or not math.isfinite(tangent_length) or not math.isfinite(bitangent_length):
            continue
        for vertex_index in (a, b, c):
            tangent_accum[vertex_index][0] += tangent[0]
            tangent_accum[vertex_index][1] += tangent[1]
            tangent_accum[vertex_index][2] += tangent[2]
            bitangent_accum[vertex_index][0] += bitangent[0]
            bitangent_accum[vertex_index][1] += bitangent[1]
            bitangent_accum[vertex_index][2] += bitangent[2]
            tangent_valid[vertex_index] = True
            bitangent_valid[vertex_index] = True

    tangents = []
    bitangents = []
    for vertex_index in range(vertex_count):
        nx, ny, nz = normals[vertex_index]
        tx, ty, tz = tangent_accum[vertex_index]
        tangent_length = (tx * tx + ty * ty + tz * tz) ** 0.5
        if tangent_length <= 1e-6 or not math.isfinite(tangent_length):
            tangent, bitangent = _orthogonal_tangent_frame(normals[vertex_index])
            tangents.append(tangent)
            bitangents.append(bitangent)
            tangent_valid[vertex_index] = False
            bitangent_valid[vertex_index] = False
            continue
        tx /= tangent_length
        ty /= tangent_length
        tz /= tangent_length
        normal_dot_tangent = (nx * tx) + (ny * ty) + (nz * tz)
        tx -= nx * normal_dot_tangent
        ty -= ny * normal_dot_tangent
        tz -= nz * normal_dot_tangent
        tangent_length = (tx * tx + ty * ty + tz * tz) ** 0.5
        if tangent_length <= 1e-6 or not math.isfinite(tangent_length):
            tangent, bitangent = _orthogonal_tangent_frame(normals[vertex_index])
            tangents.append(tangent)
            bitangents.append(bitangent)
            tangent_valid[vertex_index] = False
            bitangent_valid[vertex_index] = False
            continue
        tx /= tangent_length
        ty /= tangent_length
        tz /= tangent_length
        bx, by, bz = bitangent_accum[vertex_index]
        if (bx * bx + by * by + bz * bz) <= 1e-6:
            bx = (ny * tz) - (nz * ty)
            by = (nz * tx) - (nx * tz)
            bz = (nx * ty) - (ny * tx)
            bitangent_valid[vertex_index] = False
        bitangent_length = (bx * bx + by * by + bz * bz) ** 0.5
        if bitangent_length <= 1e-6 or not math.isfinite(bitangent_length):
            tangent, bitangent = _orthogonal_tangent_frame(normals[vertex_index])
            tangents.append(tangent)
            bitangents.append(bitangent)
            bitangent_valid[vertex_index] = False
            continue
        bx /= bitangent_length
        by /= bitangent_length
        bz /= bitangent_length
        tangents.append((tx, ty, tz))
        bitangents.append((bx, by, bz))
    return tangents, bitangents, tangent_valid, bitangent_valid


def _smooth_normal_position_key(position: Tuple[float, float, float]) -> Tuple[int, int, int]:
    return (
        int(round(float(position[0]) * 100000.0)),
        int(round(float(position[1]) * 100000.0)),
        int(round(float(position[2]) * 100000.0)),
    )


def _build_preview_smoothed_normals(
    positions: Sequence[Tuple[float, float, float]],
    normals: Sequence[Tuple[float, float, float]],
    indices: Sequence[int],
) -> Tuple[List[Tuple[float, float, float]], float]:
    vertex_count = len(positions)
    if vertex_count <= 0 or len(normals) != vertex_count:
        return list(normals), 0.0
    accum_by_position: Dict[Tuple[int, int, int], List[float]] = {}
    for triangle_index in range(0, len(indices) - 2, 3):
        a = indices[triangle_index]
        b = indices[triangle_index + 1]
        c = indices[triangle_index + 2]
        if a < 0 or b < 0 or c < 0 or a >= vertex_count or b >= vertex_count or c >= vertex_count:
            continue
        ax, ay, az = positions[a]
        bx, by, bz = positions[b]
        cx, cy, cz = positions[c]
        ab = (bx - ax, by - ay, bz - az)
        ac = (cx - ax, cy - ay, cz - az)
        face = (
            (ab[1] * ac[2]) - (ab[2] * ac[1]),
            (ab[2] * ac[0]) - (ab[0] * ac[2]),
            (ab[0] * ac[1]) - (ab[1] * ac[0]),
        )
        face_length = math.sqrt((face[0] * face[0]) + (face[1] * face[1]) + (face[2] * face[2]))
        if face_length <= 1e-12 or not math.isfinite(face_length):
            continue
        for vertex_index in (a, b, c):
            key = _smooth_normal_position_key(positions[vertex_index])
            accum = accum_by_position.setdefault(key, [0.0, 0.0, 0.0])
            accum[0] += face[0]
            accum[1] += face[1]
            accum[2] += face[2]

    smoothed = []
    changed = 0
    for vertex_index, original in enumerate(normals):
        key = _smooth_normal_position_key(positions[vertex_index])
        accum = accum_by_position.get(key)
        if accum is None:
            smoothed.append(original)
            continue
        candidate, repaired = _sanitize_vector3(accum, fallback=original, normalize=True)
        if repaired:
            smoothed.append(original)
            continue
        dot = (original[0] * candidate[0]) + (original[1] * candidate[1]) + (original[2] * candidate[2])
        if dot <= 0.05:
            smoothed.append(original)
            continue
        if dot < 0.995:
            changed += 1
        smoothed.append(candidate)
    return smoothed, changed / float(max(1, vertex_count))


def _material_decode_mode_for_semantics(kind: str, subtype: str, channels: Sequence[str]) -> int:
    key = str(kind or "").strip().lower()
    detail = str(subtype or "").strip().lower()
    channel_set = {str(channel or "").strip().lower() for channel in channels if str(channel or "").strip()}
    if key in {"orm", "rma", "mra", "arm"}:
        return {"orm": 8, "rma": 9, "mra": 10, "arm": 11}.get(key, 7)
    if key in {"material_mask", "detail_mask", "mask"}:
        return 5
    if key in {"material", "pbr"} and detail == "pbr_combined":
        return 13
    if "ao" in channel_set and "roughness" in channel_set and "metallic" in channel_set:
        return 8
    if key in {"ao", "ambientocclusion", "occlusion"}:
        return 2
    if key in {"roughness", "gloss", "smoothness"}:
        return 3
    if key in {"metallic", "metalness"}:
        return 4
    if key in {"specular", "specularglossiness"}:
        return 1
    if key in {"opacity", "alpha"}:
        return 12
    return 0


def build_vertex_blob(model: object, *, flip_texture_v: bool = False) -> Tuple[bytes, int, List[ModelPreviewDrawBatch]]:
    meshes = getattr(model, "meshes", None)
    if not meshes:
        return b"", 0, []
    vertex_data = array("f")
    vertex_count = 0
    batches: List[ModelPreviewDrawBatch] = []
    for mesh_index, mesh in enumerate(meshes):
        positions: List[Tuple[float, float, float]] = []
        position_repair_count = 0
        for raw_position in list(getattr(mesh, "positions", []) or []):
            position, repaired = _sanitize_vector3(raw_position, fallback=(0.0, 0.0, 0.0))
            positions.append(position)
            if repaired:
                position_repair_count += 1
        normals = list(getattr(mesh, "normals", []) or [])
        indices = list(getattr(mesh, "indices", []) or [])
        if not positions or not indices:
            continue
        if len(normals) != len(positions):
            normals = [(0.0, 0.0, 1.0)] * len(positions)
        sanitized_normals = []
        normal_repair_count = 0
        for normal in normals:
            sanitized_normal, repaired = _sanitize_vector3(normal, fallback=(0.0, 0.0, 1.0), normalize=True)
            sanitized_normals.append(sanitized_normal)
            if repaired:
                normal_repair_count += 1
        normals = sanitized_normals
        smoothed_normals, smooth_normal_ratio = _build_preview_smoothed_normals(positions, normals, indices)
        texture_coordinates: List[Tuple[float, float]] = []
        uv_repair_count = 0
        raw_texture_coordinates = list(getattr(mesh, "texture_coordinates", []) or [])
        if len(raw_texture_coordinates) == len(positions):
            for raw_uv in raw_texture_coordinates:
                uv, repaired = _sanitize_uv(raw_uv)
                texture_coordinates.append(uv)
                if repaired:
                    uv_repair_count += 1
        has_texture_coordinates = len(texture_coordinates) == len(positions)
        tangents, bitangents, tangent_valid, bitangent_valid = _build_tangent_frames(positions, texture_coordinates, normals, indices)
        sanitized_tangents = []
        sanitized_bitangents = []
        tangent_repair_count = 0
        bitangent_repair_count = 0
        for vertex_index in range(len(positions)):
            tangent_fallback, bitangent_fallback = _orthogonal_tangent_frame(normals[vertex_index])
            tangent_source = tangents[vertex_index] if vertex_index < len(tangents) else tangent_fallback
            bitangent_source = bitangents[vertex_index] if vertex_index < len(bitangents) else bitangent_fallback
            tangent, tangent_repaired = _sanitize_vector3(tangent_source, fallback=tangent_fallback, normalize=True)
            bitangent, bitangent_repaired = _sanitize_vector3(bitangent_source, fallback=bitangent_fallback, normalize=True)
            sanitized_tangents.append(tangent)
            sanitized_bitangents.append(bitangent)
            if tangent_repaired or not (vertex_index < len(tangent_valid) and tangent_valid[vertex_index]):
                tangent_repair_count += 1
            if bitangent_repaired or not (vertex_index < len(bitangent_valid) and bitangent_valid[vertex_index]):
                bitangent_repair_count += 1
        tangents = sanitized_tangents
        bitangents = sanitized_bitangents
        texture_wrap_repeat = False
        if has_texture_coordinates:
            us = [uv[0] for uv in texture_coordinates]
            vs = [uv[1] for uv in texture_coordinates]
            texture_wrap_repeat = min(us) < -0.05 or max(us) > 1.05 or min(vs) < -0.05 or max(vs) > 1.05
        color = _sanitize_color3(tuple(getattr(mesh, "preview_color", ()) or ()), fallback=PALETTE[mesh_index % len(PALETTE)])
        batch_first_vertex = vertex_count
        for triangle_index in range(0, len(indices) - 2, 3):
            a = indices[triangle_index]
            b = indices[triangle_index + 1]
            c = indices[triangle_index + 2]
            if a < 0 or b < 0 or c < 0 or a >= len(positions) or b >= len(positions) or c >= len(positions):
                continue
            for vertex_index, barycentric in ((a, (1.0, 0.0, 0.0)), (b, (0.0, 1.0, 0.0)), (c, (0.0, 0.0, 1.0))):
                px, py, pz = positions[vertex_index]
                nx, ny, nz = normals[vertex_index]
                tu, tv = texture_coordinates[vertex_index] if has_texture_coordinates else (0.0, 0.0)
                tx, ty, tz = tangents[vertex_index] if vertex_index < len(tangents) else (1.0, 0.0, 0.0)
                bx, by, bz = bitangents[vertex_index] if vertex_index < len(bitangents) else (0.0, 1.0, 0.0)
                sx, sy, sz = smoothed_normals[vertex_index] if vertex_index < len(smoothed_normals) else (nx, ny, nz)
                ba, bb, bc = barycentric
                vertex_data.extend((px, py, pz, nx, ny, nz, color[0], color[1], color[2], tu, tv, tx, ty, tz, bx, by, bz, sx, sy, sz, ba, bb, bc))
            vertex_count += 3
        batch_vertex_count = vertex_count - batch_first_vertex
        if batch_vertex_count <= 0:
            continue
        texture_key = str(getattr(mesh, "preview_texture_path", "") or "").strip()
        if not texture_key and getattr(mesh, "preview_texture_image", None) is not None:
            texture_key = f"in_memory:{mesh_index}"
        normal_texture_key = str(getattr(mesh, "preview_normal_texture_path", "") or "").strip()
        if not normal_texture_key and getattr(mesh, "preview_normal_texture_image", None) is not None:
            normal_texture_key = f"in_memory_normal:{mesh_index}"
        material_texture_key = str(getattr(mesh, "preview_material_texture_path", "") or "").strip()
        if not material_texture_key and getattr(mesh, "preview_material_texture_image", None) is not None:
            material_texture_key = f"in_memory_material:{mesh_index}"
        height_texture_key = str(getattr(mesh, "preview_height_texture_path", "") or "").strip()
        if not height_texture_key and getattr(mesh, "preview_height_texture_image", None) is not None:
            height_texture_key = f"in_memory_height:{mesh_index}"
        texture_flip_vertical = resolve_preview_texture_flip_vertical(
            getattr(mesh, "preview_texture_flip_vertical", None),
            source_format=getattr(model, "format", ""),
            source_path=getattr(model, "path", ""),
            flip_texture_v=bool(flip_texture_v),
        )
        if bool(getattr(mesh, "preview_debug_flip_base_v", False)):
            texture_flip_vertical = not texture_flip_vertical
        material_texture_type = str(getattr(mesh, "preview_material_texture_type", "") or "").strip().lower()
        material_texture_subtype = str(getattr(mesh, "preview_material_texture_subtype", "") or "").strip().lower()
        material_texture_packed_channels = tuple(
            str(channel or "").strip().lower()
            for channel in (getattr(mesh, "preview_material_texture_packed_channels", ()) or ())
            if str(channel or "").strip()
        )
        texture_tint_values = tuple(getattr(mesh, "preview_texture_tint", ()) or ())[:3]
        texture_tint = tuple(max(0.0, min(2.0, finite_float(value, 1.0))) for value in texture_tint_values)
        texture_uv_scale_values = tuple(getattr(mesh, "preview_texture_uv_scale", ()) or ())[:2]
        texture_uv_scale = tuple(max(0.05, min(64.0, finite_float(value, 1.0))) for value in texture_uv_scale_values)
        if len(texture_uv_scale) >= 2 and (abs(float(texture_uv_scale[0]) - 1.0) > 1e-6 or abs(float(texture_uv_scale[1]) - 1.0) > 1e-6):
            texture_wrap_repeat = True
        vertex_total = max(1, len(positions))
        position_y_min = min((float(position[1]) for position in positions), default=0.0)
        position_y_max = max((float(position[1]) for position in positions), default=0.0)
        batches.append(
            ModelPreviewDrawBatch(
                mesh_index=mesh_index,
                material_name=str(getattr(mesh, "material_name", "") or "").strip(),
                texture_name=str(getattr(mesh, "texture_name", "") or "").strip(),
                first_vertex=batch_first_vertex,
                vertex_count=batch_vertex_count,
                texture_key=texture_key,
                texture_dds_key=str(getattr(mesh, "preview_texture_dds_path", "") or "").strip() or dds_source_path_for_preview_path(texture_key),
                normal_texture_key=normal_texture_key,
                normal_texture_dds_key=str(getattr(mesh, "preview_normal_texture_dds_path", "") or "").strip() or dds_source_path_for_preview_path(normal_texture_key),
                normal_texture_strength=float(getattr(mesh, "preview_normal_texture_strength", 0.0) or 0.0),
                material_texture_key=material_texture_key,
                material_texture_dds_key=str(getattr(mesh, "preview_material_texture_dds_path", "") or "").strip() or dds_source_path_for_preview_path(material_texture_key),
                material_texture_type=material_texture_type,
                material_texture_subtype=material_texture_subtype,
                material_texture_packed_channels=material_texture_packed_channels,
                material_decode_mode=_material_decode_mode_for_semantics(material_texture_type, material_texture_subtype, material_texture_packed_channels),
                height_texture_key=height_texture_key,
                height_texture_dds_key=str(getattr(mesh, "preview_height_texture_dds_path", "") or "").strip() or dds_source_path_for_preview_path(height_texture_key),
                support_maps_disabled=bool(getattr(mesh, "preview_debug_disable_support_maps", False)),
                has_texture_coordinates=has_texture_coordinates,
                texture_wrap_repeat=texture_wrap_repeat,
                texture_flip_vertical=texture_flip_vertical,
                base_texture_quality=str(getattr(mesh, "preview_base_texture_quality", "") or "").strip().lower(),
                texture_brightness=max(0.1, min(3.0, finite_float(getattr(mesh, "preview_texture_brightness", 1.0), 1.0))),
                texture_tint=texture_tint,
                texture_uv_scale=texture_uv_scale,
                normal_finite_ratio=max(0.0, 1.0 - (float(normal_repair_count + position_repair_count) / float(vertex_total))),
                normal_repair_count=normal_repair_count,
                tangent_finite_ratio=max(0.0, 1.0 - (float(tangent_repair_count) / float(vertex_total))),
                bitangent_finite_ratio=max(0.0, 1.0 - (float(bitangent_repair_count) / float(vertex_total))),
                uv_finite_ratio=max(0.0, 1.0 - (float(uv_repair_count) / float(vertex_total))) if has_texture_coordinates else 0.0,
                smooth_normal_ratio=max(0.0, min(1.0, float(smooth_normal_ratio))),
                position_y_min=position_y_min,
                position_y_max=position_y_max,
            )
        )
    return vertex_data.tobytes(), vertex_count, batches


def preview_material_texture_inputs_for_prepared_batch(
    mesh: object,
    batch: ModelPreviewDrawBatch,
) -> Tuple[PreviewMaterialTextureInput, ...]:
    explicit_inputs = tuple(getattr(mesh, "preview_material_texture_inputs", ()) or ())
    if explicit_inputs:
        enriched_inputs: List[PreviewMaterialTextureInput] = []
        changed = False
        for item in explicit_inputs:
            if not isinstance(item, PreviewMaterialTextureInput):
                enriched_inputs.append(item)
                continue
            if str(getattr(item, "source_dds_path", "") or "").strip():
                enriched_inputs.append(item)
                continue
            source_dds_path = dds_source_path_for_preview_path(str(getattr(item, "preview_texture_path", "") or ""))
            if not source_dds_path:
                enriched_inputs.append(item)
                continue
            values = {field_info.name: getattr(item, field_info.name) for field_info in dataclass_fields(PreviewMaterialTextureInput)}
            values["source_dds_path"] = source_dds_path
            enriched_inputs.append(PreviewMaterialTextureInput(**values))
            changed = True
        return tuple(enriched_inputs) if changed else explicit_inputs
    material_name = str(getattr(mesh, "material_name", "") or batch.material_name or "").strip()
    texture_name = str(getattr(mesh, "texture_name", "") or batch.texture_name or "").strip()
    inputs: List[PreviewMaterialTextureInput] = []
    if batch.texture_key:
        inputs.append(
            PreviewMaterialTextureInput(
                slot_kind="base",
                texture_name=texture_name,
                preview_texture_path=batch.texture_key,
                source_texture_path=texture_name or batch.texture_key,
                source_dds_path=batch.texture_dds_key or dds_source_path_for_preview_path(batch.texture_key),
                semantic_type="color",
                semantic_subtype="albedo",
                material_name=material_name,
                confidence=batch.base_texture_quality or "prepared",
                visualized=True,
            )
        )
    if batch.normal_texture_key:
        normal_name = str(getattr(mesh, "preview_normal_texture_name", "") or batch.normal_texture_key).strip()
        inputs.append(
            PreviewMaterialTextureInput(
                slot_kind="normal",
                texture_name=normal_name,
                preview_texture_path=batch.normal_texture_key,
                source_texture_path=normal_name,
                source_dds_path=batch.normal_texture_dds_key or dds_source_path_for_preview_path(batch.normal_texture_key),
                semantic_type="normal",
                semantic_subtype="normal",
                material_name=material_name,
                confidence="prepared",
                visualized=True,
            )
        )
    if batch.material_texture_key:
        material_texture_name = str(getattr(mesh, "preview_material_texture_name", "") or batch.material_texture_key).strip()
        inputs.append(
            PreviewMaterialTextureInput(
                slot_kind="material",
                texture_name=material_texture_name,
                preview_texture_path=batch.material_texture_key,
                source_texture_path=material_texture_name,
                source_dds_path=batch.material_texture_dds_key or dds_source_path_for_preview_path(batch.material_texture_key),
                semantic_type=str(batch.material_texture_type or "material").strip().lower(),
                semantic_subtype=str(batch.material_texture_subtype or "").strip().lower(),
                packed_channels=tuple(batch.material_texture_packed_channels or ()),
                material_name=material_name,
                confidence="prepared",
                visualized=True,
            )
        )
    if batch.height_texture_key:
        height_name = str(getattr(mesh, "preview_height_texture_name", "") or batch.height_texture_key).strip()
        inputs.append(
            PreviewMaterialTextureInput(
                slot_kind="height",
                texture_name=height_name,
                preview_texture_path=batch.height_texture_key,
                source_texture_path=height_name,
                source_dds_path=batch.height_texture_dds_key or dds_source_path_for_preview_path(batch.height_texture_key),
                semantic_type="height",
                semantic_subtype="displacement",
                material_name=material_name,
                confidence="prepared",
                visualized=True,
            )
        )
    return tuple(inputs)


def material_combiner_cache_dir(model: ModelPreviewData) -> Path:
    digest = hashlib.sha1()
    digest.update(b"material-combiner-v6")
    digest.update(str(getattr(model, "path", "") or "").encode("utf-8", errors="replace"))
    for mesh in tuple(getattr(model, "meshes", ()) or ()):
        for field_name in (
            "material_name",
            "texture_name",
            "preview_texture_path",
            "preview_normal_texture_path",
            "preview_material_texture_path",
            "preview_height_texture_path",
            "preview_texture_dds_path",
            "preview_normal_texture_dds_path",
            "preview_material_texture_dds_path",
            "preview_height_texture_dds_path",
            "preview_material_texture_name",
            "preview_material_texture_type",
            "preview_material_texture_subtype",
            "preview_base_texture_default_name",
        ):
            path_text = str(getattr(mesh, field_name, "") or "").strip()
            digest.update(path_text.encode("utf-8", errors="replace"))
            try:
                stat = Path(path_text).stat()
            except OSError:
                continue
            digest.update(str(int(stat.st_size)).encode("ascii"))
            digest.update(str(int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)))).encode("ascii"))
        for channel in tuple(getattr(mesh, "preview_material_texture_packed_channels", ()) or ()):
            digest.update(str(channel or "").encode("utf-8", errors="replace"))
        for texture_input in tuple(getattr(mesh, "preview_material_texture_inputs", ()) or ()):
            for field_name in (
                "slot_kind",
                "parameter_name",
                "source_texture_path",
                "texture_name",
                "preview_texture_path",
                "semantic_type",
                "semantic_subtype",
                "shader_family",
                "confidence",
            ):
                digest.update(str(getattr(texture_input, field_name, "") or "").encode("utf-8", errors="replace"))
            for parameter in tuple(getattr(texture_input, "material_parameters", ()) or ()):
                for field_name in ("parameter_kind", "parameter_name", "value"):
                    digest.update(str(getattr(parameter, field_name, "") or "").encode("utf-8", errors="replace"))
    return Path(tempfile.gettempdir()) / "cdmw_material_combiner" / digest.hexdigest()[:20]


def apply_material_combiner(
    model: ModelPreviewData,
    *,
    render_settings: Optional[ModelPreviewRenderSettings] = None,
    stop_event=None,
) -> None:
    settings = clamp_model_preview_render_settings(render_settings)
    if bool(getattr(settings, "disable_all_support_maps", False)) or bool(getattr(settings, "disable_material_map", False)):
        return
    try:
        from types import SimpleNamespace
        from cdmw.ui.model_preview_material_combiner import (
            MaterialPreviewCombinerSettings,
            combine_preview_material,
            synthesize_material_texture_inputs,
        )
    except Exception:
        return
    output_root = material_combiner_cache_dir(model)
    for mesh_index, mesh in enumerate(tuple(getattr(model, "meshes", ()) or ())):
        if stop_event is not None and stop_event.is_set():
            raise RunCancelled("Model preview preparation cancelled.")
        if not isinstance(mesh, ModelPreviewMesh):
            continue
        inputs = synthesize_material_texture_inputs(mesh)
        if not inputs:
            continue
        has_material_input = any(
            str(getattr(item, "slot_kind", "") or "").strip().lower() in {"material", "material_mask", "detail_mask"}
            for item in inputs
        )
        if not has_material_input:
            continue
        mesh_output_dir = output_root / f"mesh_{mesh_index:03d}"
        cached_material = mesh_output_dir / f"batch_{mesh_index:03d}_combined_pbr.png"
        if cached_material.is_file():
            mesh.preview_material_texture_path = str(cached_material)
            mesh.preview_material_texture_image = None
            mesh.preview_material_texture_name = cached_material.name
            mesh.preview_material_texture_type = "material"
            mesh.preview_material_texture_subtype = "pbr_combined"
            mesh.preview_material_texture_packed_channels = ("ao", "roughness", "metallic", "specular")
            continue
        try:
            combined = combine_preview_material(
                SimpleNamespace(
                    material_name=str(getattr(mesh, "material_name", "") or ""),
                    texture_name=str(getattr(mesh, "texture_name", "") or ""),
                    texture_flip_vertical=False,
                    material_texture_inputs=inputs,
                    tangents_usable=bool(len(getattr(mesh, "texture_coordinates", ()) or ()) == len(getattr(mesh, "positions", ()) or ())),
                    normal_texture_strength=max(0.0, finite_float(getattr(mesh, "preview_normal_texture_strength", 0.0), 0.0)),
                ),
                mesh_output_dir,
                mesh_index,
                settings=MaterialPreviewCombinerSettings(
                    normal_strength_floor=max(0.0, finite_float(getattr(settings, "normal_strength_floor", 0.5), 0.5)),
                    normal_strength_cap=max(0.0, finite_float(getattr(settings, "normal_strength_cap", 1.0), 1.0)),
                    height_amount=max(0.0, min(0.12, finite_float(getattr(settings, "height_effect_max", 0.35), 0.35) * 0.08)),
                    support_map_max_dimension=min(192, int(getattr(settings, "low_quality_texture_max_dimension", 192) or 192)),
                ),
            )
        except Exception:
            continue
        material_source = str(getattr(combined, "legacy_material_source", "") or getattr(combined, "material_source", "") or "").strip()
        if material_source:
            mesh.preview_material_texture_path = material_source
            mesh.preview_material_texture_image = None
            mesh.preview_material_texture_name = Path(material_source).name
            mesh.preview_material_texture_type = "material"
            mesh.preview_material_texture_subtype = "pbr_combined"
            mesh.preview_material_texture_packed_channels = ("ao", "roughness", "metallic", "specular")
        base_source = str(getattr(combined, "base_source", "") or "").strip()
        if base_source:
            mesh.preview_texture_path = base_source
            mesh.preview_texture_image = None
        height_source = str(getattr(combined, "height_source", "") or "").strip()
        if height_source and not bool(getattr(settings, "disable_height_map", False)):
            mesh.preview_height_texture_path = height_source
            mesh.preview_height_texture_image = None
            mesh.preview_height_texture_name = Path(height_source).name


def prepare_model_preview(
    model: object,
    *,
    render_settings: Optional[ModelPreviewRenderSettings] = None,
    stop_event=None,
    enable_material_combiner: bool = True,
) -> Tuple[object, Optional[PreparedModelPreviewData]]:
    if stop_event is not None and stop_event.is_set():
        raise RunCancelled("Model preview preparation cancelled.")
    cloned_model = clone_model_preview(model)
    if not isinstance(cloned_model, ModelPreviewData):
        return cloned_model, None
    for mesh in getattr(cloned_model, "meshes", None) or []:
        if stop_event is not None and stop_event.is_set():
            raise RunCancelled("Model preview preparation cancelled.")
        if isinstance(mesh, ModelPreviewMesh):
            initialize_mesh_preview_slot_defaults(mesh)
    if bool(enable_material_combiner):
        apply_material_combiner(cloned_model, render_settings=render_settings, stop_event=stop_event)
    vertex_blob, vertex_count, mesh_batches = build_vertex_blob(cloned_model)
    prepared_batches: List[PreparedModelPreviewBatch] = []
    cloth_preview = getattr(cloned_model, "cloth_preview", None)

    def int_or_default(value: object, default: int = -1) -> int:
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return default

    cloth_by_mesh_index = {
        int_or_default(getattr(batch, "mesh_index", -1), -1): batch
        for batch in tuple(getattr(cloth_preview, "batches", ()) or ())
        if int_or_default(getattr(batch, "mesh_index", -1), -1) >= 0
    }
    cloth_by_source_submesh = {
        int_or_default(getattr(batch, "source_submesh_index", -1), -1): batch
        for batch in tuple(getattr(cloth_preview, "batches", ()) or ())
        if int_or_default(getattr(batch, "source_submesh_index", -1), -1) >= 0
    }
    floats_per_vertex = 23
    bytes_per_vertex = floats_per_vertex * 4
    for mesh, batch in zip(getattr(cloned_model, "meshes", ()) or (), mesh_batches):
        if stop_event is not None and stop_event.is_set():
            raise RunCancelled("Model preview preparation cancelled.")
        start = int(batch.first_vertex) * bytes_per_vertex
        end = start + (int(batch.vertex_count) * bytes_per_vertex)
        mesh_source_submesh_index = int_or_default(getattr(mesh, "source_submesh_index", -1), -1)
        mesh_source_vertices = tuple(int(index) for index in tuple(getattr(mesh, "source_vertex_indices", ()) or ()))
        mesh_indices = tuple(int(index) for index in tuple(getattr(mesh, "indices", ()) or ()))
        emitted_source_vertices: Tuple[int, ...] = ()
        if mesh_source_vertices and mesh_indices:
            emitted = []
            for index in mesh_indices[: int(batch.vertex_count)]:
                emitted.append(int(mesh_source_vertices[int(index)]) if 0 <= int(index) < len(mesh_source_vertices) else int(index))
            emitted_source_vertices = tuple(emitted)
        elif mesh_indices:
            emitted_source_vertices = tuple(mesh_indices[: int(batch.vertex_count)])
        elif int(batch.vertex_count) > 0:
            emitted_source_vertices = tuple(range(int(batch.vertex_count)))
        cloth_batch = cloth_by_mesh_index.get(int(getattr(batch, "mesh_index", -1))) or cloth_by_source_submesh.get(mesh_source_submesh_index)
        editor_role = str(getattr(mesh, "preview_role", "") or "").strip()
        editor_role_key = editor_role.lower()
        editor_editable = mesh_source_submesh_index >= 0 or ("replacement" in editor_role_key and "reference" not in editor_role_key and "original" not in editor_role_key)
        if editor_role_key.startswith("hkx_"):
            editor_editable = False
        prepared_batches.append(
            PreparedModelPreviewBatch(
                material_name=str(getattr(mesh, "material_name", "") or "").strip(),
                texture_name=str(getattr(mesh, "texture_name", "") or "").strip(),
                vertex_blob=vertex_blob[start:end],
                index_count=int(batch.vertex_count),
                preview_texture_path=batch.texture_key,
                preview_texture_dds_path=batch.texture_dds_key or dds_source_path_for_preview_path(batch.texture_key),
                preview_base_texture_quality=batch.base_texture_quality,
                preview_normal_texture_path=batch.normal_texture_key,
                preview_normal_texture_dds_path=batch.normal_texture_dds_key or dds_source_path_for_preview_path(batch.normal_texture_key),
                preview_material_texture_path=batch.material_texture_key,
                preview_material_texture_dds_path=batch.material_texture_dds_key or dds_source_path_for_preview_path(batch.material_texture_key),
                preview_height_texture_path=batch.height_texture_key,
                preview_height_texture_dds_path=batch.height_texture_dds_key or dds_source_path_for_preview_path(batch.height_texture_key),
                preview_texture_flip_vertical=batch.texture_flip_vertical,
                preview_texture_brightness=float(batch.texture_brightness or 1.0),
                preview_texture_tint=tuple(batch.texture_tint or ()),
                preview_texture_uv_scale=tuple(batch.texture_uv_scale or ()),
                preview_normal_texture_strength=float(batch.normal_texture_strength or 0.0),
                preview_material_texture_type=batch.material_texture_type,
                preview_material_texture_subtype=batch.material_texture_subtype,
                preview_material_texture_packed_channels=tuple(batch.material_texture_packed_channels or ()),
                preview_material_texture_inputs=preview_material_texture_inputs_for_prepared_batch(mesh, batch),
                preview_native_material_overrides=dict(getattr(mesh, "preview_native_material_overrides", {}) or {}),
                preview_alpha_mode=str(getattr(mesh, "preview_alpha_mode", "") or "").strip(),
                preview_double_sided=bool(getattr(mesh, "preview_double_sided", False)),
                has_texture_coordinates=bool(batch.has_texture_coordinates),
                texture_wrap_repeat=bool(batch.texture_wrap_repeat),
                preview_debug_flip_base_v=False,
                preview_debug_disable_support_maps=bool(batch.support_maps_disabled),
                position_y_min=float(getattr(batch, "position_y_min", 0.0) or 0.0),
                position_y_max=float(getattr(batch, "position_y_max", 0.0) or 0.0),
                source_submesh_index=mesh_source_submesh_index,
                source_vertex_indices=emitted_source_vertices,
                editor_role=editor_role,
                editor_part_name=str(getattr(mesh, "material_name", "") or getattr(mesh, "texture_name", "") or getattr(mesh, "source_submesh_index", "") or "").strip(),
                editor_editable=editor_editable,
                cloth_preview=cloth_batch,
            )
        )
    return cloned_model, PreparedModelPreviewData(
        source_path=str(getattr(cloned_model, "path", "") or "").strip(),
        format=str(getattr(cloned_model, "format", "") or "").strip(),
        summary=str(getattr(cloned_model, "summary", "") or "").strip(),
        mesh_count=int(getattr(cloned_model, "mesh_count", 0) or 0),
        vertex_count=int(getattr(cloned_model, "vertex_count", vertex_count) or vertex_count),
        face_count=int(getattr(cloned_model, "face_count", 0) or 0),
        lod_index=int(getattr(cloned_model, "lod_index", -1) or -1),
        lod_count=int(getattr(cloned_model, "lod_count", 0) or 0),
        normalization_center=tuple(getattr(cloned_model, "normalization_center", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)),
        normalization_scale=float(getattr(cloned_model, "normalization_scale", 1.0) or 1.0),
        batches=tuple(prepared_batches),
        cloth_preview=getattr(cloned_model, "cloth_preview", None),
    )


def alignment_euler_xyz_matrix(rotation_degrees: Sequence[float]) -> QMatrix4x4:
    values = [0.0, 0.0, 0.0]
    for index, value in enumerate(tuple(rotation_degrees or ())[:3]):
        values[index] = finite_float(value, 0.0)
    rx, ry, rz = (math.radians(value) for value in values)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    return QMatrix4x4(
        cz * cy,
        (cz * sy * sx) - (sz * cx),
        (cz * sy * cx) + (sz * sx),
        0.0,
        sz * cy,
        (sz * sy * sx) + (cz * cx),
        (sz * sy * cx) - (cz * sx),
        0.0,
        -sy,
        cy * sx,
        cy * cx,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    )


def alignment_euler_delta_matrix(base_rotation: Sequence[float], live_delta: Sequence[float]) -> QMatrix4x4:
    base_values = tuple(float(value) for value in tuple(base_rotation or ())[:3])
    live_values = tuple(float(value) for value in tuple(live_delta or ())[:3])
    if len(base_values) != 3 or len(live_values) != 3:
        return alignment_euler_xyz_matrix(live_values)
    base_matrix = alignment_euler_xyz_matrix(base_values)
    target_matrix = alignment_euler_xyz_matrix((base_values[0] + live_values[0], base_values[1] + live_values[1], base_values[2] + live_values[2]))
    try:
        return target_matrix * base_matrix.inverted()[0]
    except Exception:
        return alignment_euler_xyz_matrix(live_values)


def render_mode_uses_derived_relief(render_mode: object) -> bool:
    mode = getattr(render_mode, "render_diagnostic_mode", render_mode)
    return str(mode or "").strip().lower() in {"rich_lit", "height_calibrated", "cd_runtime_approx"}


def sample_base_texture_visibility(
    texture_image: QImage,
    texture_coordinates: Sequence[object],
    *,
    flip_vertical: bool,
    max_samples: int = 384,
) -> Optional[TextureVisibilitySample]:
    if texture_image.isNull() or not texture_coordinates:
        return None
    width = int(texture_image.width())
    height = int(texture_image.height())
    if width <= 0 or height <= 0:
        return None
    step = max(1, len(texture_coordinates) // max(1, int(max_samples)))
    red_total = green_total = blue_total = alpha_total = luma_total = alpha_weighted_luma_total = 0.0
    min_luma = 1.0
    max_luma = 0.0
    dark_count = alpha_dark_count = sample_count = 0
    for coord in texture_coordinates[::step]:
        try:
            u = float(coord[0])  # type: ignore[index]
            v = float(coord[1])  # type: ignore[index]
        except Exception:
            continue
        if not math.isfinite(u) or not math.isfinite(v):
            continue
        u = u - math.floor(u)
        v = v - math.floor(v)
        if flip_vertical:
            v = 1.0 - v
        x = max(0, min(width - 1, int(round(u * float(width - 1)))))
        y = max(0, min(height - 1, int(round(v * float(height - 1)))))
        color = texture_image.pixelColor(x, y)
        red = float(color.redF())
        green = float(color.greenF())
        blue = float(color.blueF())
        alpha = float(color.alphaF())
        luma = (0.2126 * red) + (0.7152 * green) + (0.0722 * blue)
        red_total += red
        green_total += green
        blue_total += blue
        alpha_total += alpha
        luma_total += luma
        alpha_weighted_luma_total += luma * alpha
        min_luma = min(min_luma, luma)
        max_luma = max(max_luma, luma)
        if luma < 0.035:
            dark_count += 1
        if alpha <= 0.01:
            alpha_dark_count += 1
        sample_count += 1
        if sample_count >= max_samples:
            break
    if sample_count <= 0:
        return None
    divisor = float(sample_count)
    return TextureVisibilitySample(
        average_color=(red_total / divisor, green_total / divisor, blue_total / divisor),
        average_luma=luma_total / divisor,
        dark_ratio=dark_count / divisor,
        average_alpha=alpha_total / divisor,
        alpha_dark_ratio=alpha_dark_count / divisor,
        alpha_weighted_luma=alpha_weighted_luma_total / divisor,
        min_luma=min_luma,
        max_luma=max_luma,
        luma_contrast=max_luma - min_luma,
    )


def sample_framebuffer_visibility(
    image: QImage,
    background: QColor,
    *,
    max_samples: int = 4096,
) -> FramebufferVisibilitySample:
    if image.isNull():
        return FramebufferVisibilitySample()
    width = int(image.width())
    height = int(image.height())
    if width <= 0 or height <= 0:
        return FramebufferVisibilitySample()
    total_pixels = width * height
    step = max(1, int(math.sqrt(max(1, total_pixels // max(1, int(max_samples))))))
    bg = QColor(background)
    bg_rgb = (bg.red(), bg.green(), bg.blue())
    visible = 0
    dark = 0
    background_count = 0
    luma_total = 0.0
    sampled = 0
    for y in range(0, height, step):
        for x in range(0, width, step):
            color = image.pixelColor(x, y)
            rgb = (color.red(), color.green(), color.blue())
            sampled += 1
            if max(abs(rgb[index] - bg_rgb[index]) for index in range(3)) <= 3:
                background_count += 1
                continue
            visible += 1
            luma = (0.2126 * float(color.redF())) + (0.7152 * float(color.greenF())) + (0.0722 * float(color.blueF()))
            luma_total += luma
            if luma < 0.075:
                dark += 1
    if sampled <= 0:
        return FramebufferVisibilitySample()
    return FramebufferVisibilitySample(
        visible_pixels=visible,
        average_luma=(luma_total / float(max(1, visible))),
        dark_ratio=(dark / float(max(1, visible))),
        background_ratio=(background_count / float(sampled)),
    )


def derive_relief_image_from_base(texture_image: QImage, *, max_dimension: int = 512) -> Optional[QImage]:
    if texture_image.isNull():
        return None
    image = texture_image.convertToFormat(QImage.Format_RGBA8888)
    if image.isNull():
        return None
    width = int(image.width())
    height = int(image.height())
    if width <= 1 or height <= 1:
        return None
    longest = max(width, height)
    if longest > max_dimension:
        target = image.size().scaled(int(max_dimension), int(max_dimension), Qt.KeepAspectRatio)
        if target.width() > 1 and target.height() > 1:
            image = image.scaled(target, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            width = int(image.width())
            height = int(image.height())
    luma_values: List[float] = []
    luma_grid: List[List[float]] = []
    for y in range(height):
        row = []
        for x in range(width):
            color = image.pixelColor(x, y)
            luma = (0.2126 * float(color.redF())) + (0.7152 * float(color.greenF())) + (0.0722 * float(color.blueF()))
            row.append(luma)
            luma_values.append(luma)
        luma_grid.append(row)
    if not luma_values:
        return None
    sorted_luma = sorted(luma_values)
    low = sorted_luma[int(max(0, min(len(sorted_luma) - 1, round((len(sorted_luma) - 1) * 0.05))))]
    high = sorted_luma[int(max(0, min(len(sorted_luma) - 1, round((len(sorted_luma) - 1) * 0.95))))]
    contrast = max(high - low, 0.0)
    if contrast < 0.018:
        return None
    relief = QImage(width, height, QImage.Format_RGBA8888)
    contrast_gain = max(1.0, min(4.0, 0.42 / max(contrast, 0.001)))
    for y in range(height):
        ym = max(0, y - 1)
        yp = min(height - 1, y + 1)
        for x in range(width):
            xm = max(0, x - 1)
            xp = min(width - 1, x + 1)
            center = luma_grid[y][x]
            local_average = (
                luma_grid[ym][xm] + luma_grid[ym][x] + luma_grid[ym][xp]
                + luma_grid[y][xm] + center + luma_grid[y][xp]
                + luma_grid[yp][xm] + luma_grid[yp][x] + luma_grid[yp][xp]
            ) / 9.0
            sobel_x = (
                -luma_grid[ym][xm] + luma_grid[ym][xp]
                - (2.0 * luma_grid[y][xm]) + (2.0 * luma_grid[y][xp])
                - luma_grid[yp][xm] + luma_grid[yp][xp]
            )
            sobel_y = (
                -luma_grid[ym][xm] - (2.0 * luma_grid[ym][x]) - luma_grid[ym][xp]
                + luma_grid[yp][xm] + (2.0 * luma_grid[yp][x]) + luma_grid[yp][xp]
            )
            edge = min(1.0, math.sqrt((sobel_x * sobel_x) + (sobel_y * sobel_y)) * 1.35)
            normalized = ((center - low) / max(contrast, 0.001)) - 0.5
            local_detail = (center - local_average) * 2.5
            relief_value = 0.5 + (normalized * 0.42 * contrast_gain) + (local_detail * 0.28) + ((edge - 0.20) * 0.16)
            grey = max(0, min(255, int(round(max(0.0, min(1.0, relief_value)) * 255.0))))
            relief.setPixelColor(x, y, QColor(grey, grey, grey, 255))
    return relief


def enhanced_relief_status(
    *,
    render_mode_code: int,
    high_quality_enabled: bool,
    support_maps_enabled: bool,
    support_maps_disabled: bool,
    height_key: str,
    height_texture_available: bool,
    height_luma: Optional[TextureVisibilitySample],
    derived_relief_key: str = "",
    derived_relief_texture_available: bool = False,
    derived_relief_luma: Optional[TextureVisibilitySample] = None,
    height_map_disabled: bool,
    height_effect_max: float,
) -> Tuple[str, str, bool, str]:
    if render_mode_code == 24:
        return "control-test", "Relief Control Test is visualizing slider values directly.", False, "control-test"
    if render_mode_code not in {22, 23}:
        return "inactive", "Enhanced Relief Preview mode is not selected.", False, "inactive"
    if not high_quality_enabled:
        return "inactive", "Support-map preview shading is disabled.", False, "inactive"
    if float(height_effect_max) <= 0.001:
        return "inactive", "Relief depth is set to zero.", False, "inactive"
    true_height_usable = bool(
        support_maps_enabled
        and not support_maps_disabled
        and not height_map_disabled
        and str(height_key or "").strip()
        and height_texture_available
        and height_luma is not None
        and float(height_luma.luma_contrast) >= 0.010
    )
    derived_usable = bool(
        str(derived_relief_key or "").strip()
        and derived_relief_texture_available
        and derived_relief_luma is not None
        and float(derived_relief_luma.luma_contrast) >= 0.018
    )
    if true_height_usable and derived_usable:
        return "active", "Calibrated height relief with derived base micro-detail is active.", True, "height+derived-detail"
    if true_height_usable:
        return "active", "Calibrated height relief is active.", True, "height-map"
    if derived_usable:
        return "active", "Derived base-texture relief is active.", True, "derived-base"
    if height_luma is not None and str(height_key or "").strip() and height_texture_available:
        return "inactive", "Height map is present but nearly flat.", False, "inactive"
    if derived_relief_luma is not None and str(derived_relief_key or "").strip() and derived_relief_texture_available:
        return "inactive", "Derived relief source is nearly flat.", False, "inactive"
    return "inactive", "No usable relief source is available.", False, "inactive"


def diffuse_probe_source_for_render_mode(settings: ModelPreviewRenderSettings, render_mode: str) -> str:
    normalized_mode = str(render_mode or "").strip().lower()
    if normalized_mode in {"base_direct", "base_no_tint", "base_alpha", "base_color", "sampler_swap_base_on_unit2"}:
        return "base"
    if normalized_mode == "texture_probe":
        source = str(getattr(settings, "texture_probe_source", "base") or "base").strip().lower()
        return source if source in {"base", "normal", "material", "height"} else "base"
    if normalized_mode == "sampler_swap_material_on_unit0":
        return "material"
    return "base"


def support_map_geometry_usable(batch: ModelPreviewDrawBatch) -> bool:
    return bool(
        getattr(batch, "has_texture_coordinates", False)
        and float(getattr(batch, "tangent_finite_ratio", 0.0) or 0.0) >= 0.75
        and float(getattr(batch, "uv_finite_ratio", 0.0) or 0.0) >= 0.95
    )


def support_map_slot_counts_from_batches(batches: Sequence[ModelPreviewDrawBatch]) -> Dict[str, int]:
    counts = {"normal": 0, "material": 0, "height": 0}
    for batch in batches:
        if batch.normal_texture_key:
            counts["normal"] += 1
        if batch.material_texture_key:
            counts["material"] += 1
        if batch.height_texture_key:
            counts["height"] += 1
    return counts


def support_map_active_counts_from_diagnostics(diagnostics: Mapping[int, object]) -> Dict[str, int]:
    counts = {"normal": 0, "material": 0, "height": 0}
    for item in diagnostics.values():
        if getattr(item, "use_normal", False):
            counts["normal"] += 1
        if getattr(item, "use_material", False):
            counts["material"] += 1
        if getattr(item, "use_height", False):
            counts["height"] += 1
    return counts


def format_support_map_counts(counts: Mapping[str, int]) -> str:
    return f"n:{int(counts.get('normal', 0))} m:{int(counts.get('material', 0))} h:{int(counts.get('height', 0))}"


def black_output_triage_lines(diagnostics: Sequence[object], framebuffer: object) -> Tuple[str, ...]:
    lines: List[str] = []
    visible_pixels = int(getattr(framebuffer, "visible_pixels", 0) or 0)
    dark_ratio = float(getattr(framebuffer, "dark_ratio", 0.0) or 0.0)
    if visible_pixels > 0 and dark_ratio >= 0.90:
        lines.append("Framebuffer is mostly dark; checking visible-color inputs.")
    missing_base = [
        item for item in tuple(diagnostics or ())
        if not bool(getattr(item, "texture_path_set", False)) and not bool(getattr(item, "use_texture", False))
    ]
    support_only = [
        item for item in missing_base
        if bool(getattr(item, "use_normal", False))
        or bool(getattr(item, "use_material", False))
        or bool(getattr(item, "use_height", False))
    ]
    if missing_base:
        lines.append("Missing base/color texture: support maps cannot provide visible color by themselves.")
    if support_only:
        lines.append("One or more batches have only normal/material/height support maps active.")
    if not lines:
        lines.append("Native renderer diagnostics did not find a missing base/color cause.")
    return tuple(lines)


def clip_preview_line(start: Sequence[float], end: Sequence[float]) -> Optional[Tuple[Tuple[float, float, float, float], Tuple[float, float, float, float]]]:
    if len(start) < 4 or len(end) < 4:
        return None
    a = tuple(float(value) for value in start[:4])
    b = tuple(float(value) for value in end[:4])
    delta = tuple(b[index] - a[index] for index in range(4))
    t0 = 0.0
    t1 = 1.0

    def _plane_value(point: Sequence[float], plane: int) -> float:
        x, y, z, w = point
        if plane == 0:
            return x + w
        if plane == 1:
            return -x + w
        if plane == 2:
            return y + w
        if plane == 3:
            return -y + w
        if plane == 4:
            return z + w
        if plane == 5:
            return -z + w
        return w - OVERLAY_CLIP_EPSILON

    for plane in range(7):
        fa = _plane_value(a, plane)
        fb = _plane_value(b, plane)
        if fa < 0.0 and fb < 0.0:
            return None
        if fa >= 0.0 and fb >= 0.0:
            continue
        denom = fa - fb
        if abs(denom) <= 1e-12:
            return None
        t = fa / denom
        if fa < 0.0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return None

    def _at(t: float) -> Tuple[float, float, float, float]:
        return (
            a[0] + delta[0] * t,
            a[1] + delta[1] * t,
            a[2] + delta[2] * t,
            max(a[3] + delta[3] * t, OVERLAY_CLIP_EPSILON),
        )

    return (_at(t0), _at(t1))
