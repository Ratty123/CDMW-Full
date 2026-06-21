"""Static mesh replacement source-part, UV, and adjustment helpers."""

from __future__ import annotations

from .mesh_parser import ParsedMesh, SubMesh
from .static_mesh_geometry import _bbox, _center, _is_marker_submesh, _normalize, _rotate_xyz
from .static_mesh_types import (
    StaticIndependentPart,
    StaticMeshReplacementOptions,
    StaticSourcePartAdjustment,
    StaticTextureUvTransform,
)

def _independent_parts_for_options(
    options: StaticMeshReplacementOptions,
    replacement_mesh: ParsedMesh,
    *,
    include_preview_only: bool,
) -> list[StaticIndependentPart]:
    parts: list[StaticIndependentPart] = []
    seen: set[int] = set()
    for raw_part in getattr(options, "independent_output_parts", []) or []:
        if not bool(getattr(raw_part, "enabled", True)):
            continue
        if bool(getattr(raw_part, "preview_only", False)) and not include_preview_only:
            continue
        try:
            source_index = int(getattr(raw_part, "source_submesh_index"))
        except (TypeError, ValueError):
            continue
        if source_index < 0 or source_index >= len(replacement_mesh.submeshes):
            continue
        if source_index in seen:
            continue
        submesh = replacement_mesh.submeshes[source_index]
        if _is_marker_submesh(submesh):
            continue
        seen.add(source_index)
        parts.append(
            StaticIndependentPart(
                source_submesh_index=source_index,
                label=str(getattr(raw_part, "label", "") or ""),
                material_name=str(getattr(raw_part, "material_name", "") or ""),
                enabled=True,
                preview_only=bool(getattr(raw_part, "preview_only", False)),
                clone_target_submesh_index=int(getattr(raw_part, "clone_target_submesh_index", -1) or -1),
            )
        )
    return parts


def _independent_source_indices(
    options: StaticMeshReplacementOptions,
    replacement_mesh: ParsedMesh,
    *,
    include_preview_only: bool,
) -> set[int]:
    return {
        int(part.source_submesh_index)
        for part in _independent_parts_for_options(
            options,
            replacement_mesh,
            include_preview_only=include_preview_only,
        )
    }



def _texture_uv_transforms_by_key(
    transforms: list[StaticTextureUvTransform],
) -> dict[str, StaticTextureUvTransform]:
    by_key: dict[str, StaticTextureUvTransform] = {}
    for transform in transforms or []:
        material_name = str(getattr(transform, "source_material_name", "") or "").strip()
        if not material_name:
            continue
        by_key[material_name.lower()] = transform
    return by_key


def _texture_uv_transform_for_submesh(
    submesh: SubMesh,
    transforms_by_key: dict[str, StaticTextureUvTransform],
) -> StaticTextureUvTransform | None:
    for value in (submesh.material, submesh.name):
        key = str(value or "").strip().lower()
        if key and key in transforms_by_key:
            return transforms_by_key[key]
    return None


def _apply_texture_uv_transform(submesh: SubMesh, transform: StaticTextureUvTransform) -> None:
    if not submesh.uvs or len(submesh.uvs) != len(submesh.vertices):
        return
    pivot_u, pivot_v = _uv_pair(transform.pivot_uv, (0.5, 0.5))
    offset_u, offset_v = _uv_pair(transform.offset_uv, (0.0, 0.0))
    scale_u, scale_v = _uv_pair(transform.scale_uv, (1.0, 1.0))
    scale_u = scale_u if abs(scale_u) > 1e-8 else 1.0
    scale_v = scale_v if abs(scale_v) > 1e-8 else 1.0
    rotate_steps = int(round(float(getattr(transform, "rotate_degrees", 0) or 0) / 90.0)) % 4

    transformed: list[tuple[float, float]] = []
    for raw_u, raw_v in submesh.uvs:
        u = (float(raw_u) - pivot_u) * scale_u
        v = (float(raw_v) - pivot_v) * scale_v
        if bool(transform.flip_u):
            u = -u
        if bool(transform.flip_v):
            v = -v
        for _step in range(rotate_steps):
            u, v = -v, u
        transformed.append((u + pivot_u + offset_u, v + pivot_v + offset_v))
    submesh.uvs = transformed


def _uv_pair(value: tuple[float, float] | None, fallback: tuple[float, float]) -> tuple[float, float]:
    try:
        if value is None:
            return fallback
        return (float(value[0]), float(value[1]))
    except Exception:
        return fallback


def _source_part_adjustments_by_index(
    adjustments: list[StaticSourcePartAdjustment] | None,
) -> dict[int, StaticSourcePartAdjustment]:
    by_index: dict[int, StaticSourcePartAdjustment] = {}
    for adjustment in adjustments or []:
        try:
            source_index = int(adjustment.source_submesh_index)
        except Exception:
            continue
        if source_index >= 0:
            by_index[source_index] = adjustment
    return by_index


def _apply_source_part_adjustment(
    submesh: SubMesh,
    adjustment: StaticSourcePartAdjustment,
    *,
    pivot: tuple[float, float, float] | None = None,
) -> None:
    if not submesh.vertices:
        return
    pivot = pivot if pivot is not None else _center(*_bbox(submesh.vertices))
    sx, sy, sz = adjustment.scale_xyz or (1.0, 1.0, 1.0)
    uniform = float(adjustment.uniform_scale or 1.0)
    scale_xyz = (float(sx) * uniform, float(sy) * uniform, float(sz) * uniform)
    offset = tuple(float(value) for value in adjustment.offset_xyz)
    rotation = tuple(float(value) for value in adjustment.rotate_xyz_degrees)
    adjusted_vertices: list[tuple[float, float, float]] = []
    for vertex in submesh.vertices:
        local = (
            (float(vertex[0]) - pivot[0]) * scale_xyz[0],
            (float(vertex[1]) - pivot[1]) * scale_xyz[1],
            (float(vertex[2]) - pivot[2]) * scale_xyz[2],
        )
        rotated = _rotate_xyz(local, rotation)
        adjusted_vertices.append(
            (
                rotated[0] + pivot[0] + offset[0],
                rotated[1] + pivot[1] + offset[1],
                rotated[2] + pivot[2] + offset[2],
            )
        )
    submesh.vertices = adjusted_vertices
    if submesh.normals and len(submesh.normals) == len(submesh.vertices):
        submesh.normals = [_normalize(_rotate_xyz(normal, rotation)) for normal in submesh.normals]
