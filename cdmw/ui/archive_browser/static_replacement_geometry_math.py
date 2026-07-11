"""Pure geometry math helpers for static replacement."""

from __future__ import annotations

import copy
import math
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from cdmw.domain.cancellation import raise_if_cancelled


Vector3 = tuple[float, float, float]
Bounds3 = tuple[Vector3, Vector3]
PartTransformValues = tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...], float]
GlobalTransformValues = tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]


@dataclass(frozen=True, slots=True)
class WorkAreaPlacementFit:
    source_center: Vector3
    target_center: Vector3
    scale: float
    notes: tuple[str, ...]
    translation: Vector3 = (0.0, 0.0, 0.0)
    up_axis: int = 1
    ground_plane: float = 0.0


AppendedPartWorkAreaFit = WorkAreaPlacementFit


def part_bbox(vertices: Sequence[Vector3]) -> Bounds3:
    if not vertices:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    xs, ys, zs = zip(*vertices)
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def _vector3(values: Sequence[object]) -> Vector3:
    vector = tuple(float(value) for value in tuple(values or ())[:3])
    return vector + (0.0,) * (3 - len(vector))


def part_bbox_center(bounds: Bounds3) -> Vector3:
    minimum, maximum = bounds
    return (
        (float(minimum[0]) + float(maximum[0])) * 0.5,
        (float(minimum[1]) + float(maximum[1])) * 0.5,
        (float(minimum[2]) + float(maximum[2])) * 0.5,
    )


def part_bbox_diagonal(bounds: Bounds3) -> float:
    minimum, maximum = bounds
    return math.dist(minimum, maximum)


def point_inside_expanded_bbox(
    point: Vector3,
    bounds: Bounds3,
    *,
    margin: float,
) -> bool:
    minimum, maximum = bounds
    return all(
        float(minimum[axis]) - margin <= float(point[axis]) <= float(maximum[axis]) + margin
        for axis in range(3)
    )


def add_vector3_delta(current: Sequence[float], delta: Sequence[float]) -> Vector3:
    current_values = tuple(float(value) for value in tuple(current or (0.0, 0.0, 0.0))[:3])
    while len(current_values) < 3:
        current_values = (*current_values, 0.0)
    delta_values = tuple(float(value) for value in tuple(delta or (0.0, 0.0, 0.0))[:3])
    while len(delta_values) < 3:
        delta_values = (*delta_values, 0.0)
    return tuple(current_values[index] + delta_values[index] for index in range(3))


def alignment_rotation_nudge_value(current_value: object, direction: object, step: object) -> float:
    return float(current_value) + (float(direction) * float(step))


def alignment_global_rotation_origin_state(
    alignment: Mapping[str, object],
    *,
    offset_xyz: Sequence[object],
    normalization_center: Sequence[object],
    normalization_scale: object,
) -> Vector3:
    target_anchor = _vector3(tuple(alignment.get("target_anchor") or (0.0, 0.0, 0.0)))
    offset = _vector3(offset_xyz)
    center = _vector3(normalization_center)
    scale = float(normalization_scale or 1.0)
    return tuple((target_anchor[index] + offset[index] - center[index]) * scale for index in range(3))


def part_transform_values(adjustment: object) -> PartTransformValues:
    return (
        tuple(float(value) for value in tuple(getattr(adjustment, "offset_xyz", None) or (0.0, 0.0, 0.0))[:3]),
        tuple(float(value) for value in tuple(getattr(adjustment, "rotate_xyz_degrees", None) or (0.0, 0.0, 0.0))[:3]),
        tuple(float(value) for value in tuple(getattr(adjustment, "scale_xyz", None) or (1.0, 1.0, 1.0))[:3]),
        float(getattr(adjustment, "uniform_scale", 1.0) or 1.0),
    )


def global_transform_values(
    offset_xyz: Sequence[float],
    rotate_xyz_degrees: Sequence[float],
    scale_xyz: Sequence[float],
) -> GlobalTransformValues:
    return (
        tuple(float(value) for value in tuple(offset_xyz)[:3]),
        tuple(float(value) for value in tuple(rotate_xyz_degrees)[:3]),
        tuple(float(value) for value in tuple(scale_xyz)[:3]),
    )


def global_fast_preview_transform_delta(
    baked_values: GlobalTransformValues,
    current_values: GlobalTransformValues,
    *,
    preview_scale: float,
) -> tuple[Vector3, Vector3, Vector3]:
    baked_offset, baked_rotation, baked_scale = baked_values
    current_offset, current_rotation, current_scale = current_values
    translation_delta = tuple((current_offset[index] - baked_offset[index]) * float(preview_scale) for index in range(3))
    rotation_delta = tuple(current_rotation[index] - baked_rotation[index] for index in range(3))
    scale_delta = tuple(
        current_scale[index] / baked_scale[index] if abs(baked_scale[index]) > 1e-8 else 1.0
        for index in range(3)
    )
    return translation_delta, rotation_delta, scale_delta


def part_fast_preview_transform_delta(
    baked_values: PartTransformValues,
    current_values: PartTransformValues,
    *,
    preview_scale: float,
) -> tuple[Vector3, Vector3, Vector3]:
    baked_offset, baked_rotation, baked_scale, baked_uniform = baked_values
    current_offset, current_rotation, current_scale, current_uniform = current_values
    translation_delta = tuple((current_offset[index] - baked_offset[index]) * float(preview_scale) for index in range(3))
    rotation_delta = tuple(current_rotation[index] - baked_rotation[index] for index in range(3))
    scale_delta = tuple(
        (current_scale[index] * current_uniform) / (baked_scale[index] * baked_uniform)
        if abs(baked_scale[index] * baked_uniform) > 1e-8
        else 1.0
        for index in range(3)
    )
    return translation_delta, rotation_delta, scale_delta


def fit_uniform_scale_for_bounds(source_vertices: Sequence[Vector3], target_vertices: Sequence[Vector3]) -> float | None:
    if not source_vertices or not target_vertices:
        return None
    source_min, source_max = part_bbox(source_vertices)
    target_min, target_max = part_bbox(target_vertices)
    source_dims = [max(1e-8, source_max[index] - source_min[index]) for index in range(3)]
    target_dims = [max(1e-8, target_max[index] - target_min[index]) for index in range(3)]
    ratios = [target_dims[index] / source_dims[index] for index in range(3) if source_dims[index] > 1e-8]
    if not ratios:
        return None
    return max(0.001, min(100.0, min(ratios)))


def center_offset_for_bounds(source_vertices: Sequence[Vector3], target_vertices: Sequence[Vector3]) -> Vector3 | None:
    if not source_vertices or not target_vertices:
        return None
    source_center = part_bbox_center(part_bbox(source_vertices))
    target_center = part_bbox_center(part_bbox(target_vertices))
    return (
        float(target_center[0]) - float(source_center[0]),
        float(target_center[1]) - float(source_center[1]),
        float(target_center[2]) - float(source_center[2]),
    )


def reference_vertices_for_appended_part(
    original_mesh: object | None,
    *,
    target_index: int,
    original_index: int,
) -> list[Vector3]:
    submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ()) if original_mesh is not None else ()
    if not submeshes:
        return []
    if 0 <= target_index < len(submeshes):
        vertices = list(getattr(submeshes[target_index], "vertices", ()) or ())
        if vertices:
            return vertices
    if 0 <= original_index < len(submeshes):
        vertices = list(getattr(submeshes[original_index], "vertices", ()) or ())
        if vertices:
            return vertices
    return [
        vertex
        for submesh in submeshes
        for vertex in (getattr(submesh, "vertices", ()) or ())
    ]


def vertices_for_source_indices(mesh: object, source_indices: Sequence[int]) -> list[Vector3]:
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    vertices: list[Vector3] = []
    for source_index in source_indices:
        if 0 <= int(source_index) < len(submeshes):
            vertices.extend(getattr(submeshes[int(source_index)], "vertices", ()) or ())
    return vertices


def external_import_work_area_fit(
    source_vertices: Sequence[Vector3],
    reference_vertices: Sequence[Vector3],
    *,
    up_axis: int,
    ground_plane: float = 0.0,
) -> WorkAreaPlacementFit | None:
    if not source_vertices:
        return None
    source_bounds = part_bbox(source_vertices)
    reference_bounds = part_bbox(reference_vertices) if reference_vertices else None
    return external_import_work_area_fit_from_bounds(
        source_bounds,
        reference_bounds,
        up_axis=up_axis,
        ground_plane=ground_plane,
    )


def external_import_work_area_fit_from_bounds(
    source_bounds: Bounds3,
    reference_bounds: Bounds3 | None,
    *,
    up_axis: int,
    ground_plane: float = 0.0,
) -> WorkAreaPlacementFit | None:
    axis = max(0, min(2, int(up_axis)))
    source_min, source_max = source_bounds
    source_center = part_bbox_center(source_bounds)
    source_diag = max(part_bbox_diagonal(source_bounds), 1e-8)
    reference_center = part_bbox_center(reference_bounds) if reference_bounds is not None else (0.0, 0.0, 0.0)
    reference_diag = max(part_bbox_diagonal(reference_bounds), 1e-8) if reference_bounds is not None else 1.0
    scale = 1.0
    if reference_bounds is not None:
        if source_diag > reference_diag * 2.5:
            scale = max(0.001, min(100.0, (reference_diag * 1.15) / source_diag))
        elif source_diag < reference_diag * 0.02:
            scale = max(0.001, min(100.0, (reference_diag * 0.12) / source_diag))
    target_center = list(reference_center)
    if reference_bounds is None:
        target_center = [0.0, 0.0, 0.0]
    target_center[axis] = float(ground_plane) - ((float(source_min[axis]) - float(source_center[axis])) * scale)
    target_center_tuple = (target_center[0], target_center[1], target_center[2])
    translation = tuple(
        target_center_tuple[index] - (float(source_center[index]) * scale)
        for index in range(3)
    )
    horizontal_axes = tuple(index for index in range(3) if index != axis)
    needs_recenter = any(
        abs(float(target_center_tuple[index]) - float(source_center[index])) > max(reference_diag * 0.02, 1e-5)
        for index in horizontal_axes
    )
    original_bottom = float(source_min[axis])
    needs_bottom_align = abs(original_bottom - float(ground_plane)) > 1e-5
    if not needs_recenter and not needs_bottom_align and abs(scale - 1.0) <= 1e-8:
        return None
    notes: list[str] = []
    if needs_recenter:
        notes.append("centered in the current asset work area")
    if needs_bottom_align:
        notes.append("bottom-aligned to the preview grid")
    if abs(scale - 1.0) > 1e-8:
        notes.append(f"scaled {scale:.4g}x for preview control")
    return WorkAreaPlacementFit(
        source_center=source_center,
        target_center=target_center_tuple,
        scale=scale,
        notes=tuple(notes),
        translation=translation,
        up_axis=axis,
        ground_plane=float(ground_plane),
    )


def appended_part_work_area_fit(
    source_vertices: Sequence[Vector3],
    reference_vertices: Sequence[Vector3],
) -> AppendedPartWorkAreaFit | None:
    if not source_vertices:
        return None
    return external_import_work_area_fit(
        source_vertices,
        reference_vertices,
        up_axis=1,
        ground_plane=0.0,
    )


def transformed_vertices_for_work_area(
    vertices: Sequence[Vector3],
    fit: AppendedPartWorkAreaFit,
    *,
    stop_event: threading.Event | None = None,
) -> list[Vector3]:
    transformed: list[Vector3] = []
    for index, vertex in enumerate(vertices):
        if index % 4096 == 0:
            raise_if_cancelled(stop_event, "Static replacement preflight stopped by user.")
        transformed.append(
            (
                fit.target_center[0] + ((float(vertex[0]) - fit.source_center[0]) * fit.scale),
                fit.target_center[1] + ((float(vertex[1]) - fit.source_center[1]) * fit.scale),
                fit.target_center[2] + ((float(vertex[2]) - fit.source_center[2]) * fit.scale),
            )
        )
    return transformed


def source_mirror_plane_x(original_mesh: object | None, source_vertices: Sequence[Vector3]) -> float:
    submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ()) if original_mesh is not None else ()
    original_vertices = [
        vertex
        for submesh in submeshes
        for vertex in (getattr(submesh, "vertices", ()) or ())
    ]
    if original_vertices:
        return float(part_bbox_center(part_bbox(original_vertices))[0])
    if source_vertices:
        return float(part_bbox_center(part_bbox(source_vertices))[0])
    return 0.0


def mirror_submesh_x(
    source: object,
    plane_x: float,
    *,
    normalize_vector: Callable[[Vector3], Vector3],
) -> object:
    native_mirror = _mirror_submesh_x_native_clone(source, plane_x)
    if native_mirror is not None:
        return native_mirror
    mirrored = copy.deepcopy(source)
    mirrored.vertices = [
        (2.0 * float(plane_x) - float(vertex[0]), float(vertex[1]), float(vertex[2]))
        for vertex in (getattr(mirrored, "vertices", ()) or ())
    ]
    normals = list(getattr(mirrored, "normals", ()) or ())
    if normals and len(normals) == len(mirrored.vertices):
        mirrored.normals = [
            normalize_vector((-float(normal[0]), float(normal[1]), float(normal[2])))
            for normal in normals
        ]
    mirrored.faces = [
        (int(face[0]), int(face[2]), int(face[1]))
        for face in (getattr(mirrored, "faces", ()) or ())
        if len(face) >= 3
    ]
    mirrored.vertex_count = len(mirrored.vertices)
    mirrored.face_count = len(mirrored.faces)
    return mirrored


def _mirror_submesh_x_native_clone(submesh: object, plane_x: float) -> object | None:
    try:
        from cdmw.services.mesh_workflow_service import clone_native_mesh_affine_transformed_submesh
    except Exception:
        return None
    position_matrix = (
        -1.0,
        0.0,
        0.0,
        2.0 * float(plane_x),
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
    )
    normal_matrix = (
        -1.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
    )
    try:
        return clone_native_mesh_affine_transformed_submesh(
            submesh,
            position_matrix=position_matrix,
            normal_matrix=normal_matrix,
            reverse_face_winding=True,
        )
    except Exception:
        return None


def copy_source_part_with_adjustment(
    source: object,
    adjustment: object,
    *,
    rotate_vector: Callable[[Vector3, Sequence[float]], Vector3],
    normalize_vector: Callable[[Vector3], Vector3],
    mirror_x_around_bounds_center: bool = False,
) -> object:
    native_copy = _copy_source_part_with_adjustment_native_copy(
        source,
        adjustment,
        mirror_x_around_bounds_center=mirror_x_around_bounds_center,
    )
    if native_copy is not None:
        return native_copy
    copied = copy.deepcopy(source)
    if _copy_source_part_with_adjustment_native(copied, adjustment):
        if mirror_x_around_bounds_center:
            plane_x = source_mirror_plane_x(None, list(getattr(copied, "vertices", ()) or ()))
            return mirror_submesh_x(copied, plane_x, normalize_vector=normalize_vector)
        return copied
    vertices = list(getattr(copied, "vertices", ()) or ())
    if not vertices:
        return copied
    pivot = part_bbox_center(part_bbox(vertices))
    sx, sy, sz = tuple(getattr(adjustment, "scale_xyz", None) or (1.0, 1.0, 1.0))
    uniform = float(getattr(adjustment, "uniform_scale", 1.0) or 1.0)
    scale_xyz = (float(sx) * uniform, float(sy) * uniform, float(sz) * uniform)
    offset_xyz = tuple(float(value) for value in getattr(adjustment, "offset_xyz", (0.0, 0.0, 0.0)))
    rotation = tuple(float(value) for value in getattr(adjustment, "rotate_xyz_degrees", (0.0, 0.0, 0.0)))
    transformed_vertices: list[Vector3] = []
    for vertex in vertices:
        local = (
            (float(vertex[0]) - pivot[0]) * scale_xyz[0],
            (float(vertex[1]) - pivot[1]) * scale_xyz[1],
            (float(vertex[2]) - pivot[2]) * scale_xyz[2],
        )
        rotated = rotate_vector(local, rotation)
        transformed_vertices.append(
            (
                rotated[0] + pivot[0] + offset_xyz[0],
                rotated[1] + pivot[1] + offset_xyz[1],
                rotated[2] + pivot[2] + offset_xyz[2],
            )
        )
    copied.vertices = transformed_vertices
    normals = list(getattr(copied, "normals", ()) or ())
    if normals and len(normals) == len(transformed_vertices):
        copied.normals = [normalize_vector(rotate_vector(tuple(normal), rotation)) for normal in normals]
    copied.vertex_count = len(copied.vertices)
    copied.face_count = len(getattr(copied, "faces", ()) or ())
    if mirror_x_around_bounds_center:
        plane_x = source_mirror_plane_x(None, list(getattr(copied, "vertices", ()) or ()))
        return mirror_submesh_x(copied, plane_x, normalize_vector=normalize_vector)
    return copied


def _copy_source_part_with_adjustment_native_copy(
    submesh: object,
    adjustment: object,
    *,
    mirror_x_around_bounds_center: bool = False,
) -> object | None:
    try:
        from cdmw.services.mesh_workflow_service import clone_native_mesh_affine_transformed_submesh
    except Exception:
        return None
    try:
        return clone_native_mesh_affine_transformed_submesh(
            submesh,
            source_part_adjustment=adjustment,
            mirror_x_around_bounds_center=mirror_x_around_bounds_center,
        )
    except Exception:
        return None


def _copy_source_part_with_adjustment_native(submesh: object, adjustment: object) -> bool:
    try:
        from cdmw.services.mesh_workflow_service import apply_native_mesh_affine_transform_submeshes
    except Exception:
        return False
    try:
        changed = apply_native_mesh_affine_transform_submeshes(
            [submesh],
            source_part_adjustments_by_index={0: adjustment},
        )
    except Exception:
        return False
    return changed == {0}


__all__ = [
    "AppendedPartWorkAreaFit",
    "WorkAreaPlacementFit",
    "Bounds3",
    "GlobalTransformValues",
    "PartTransformValues",
    "Vector3",
    "add_vector3_delta",
    "appended_part_work_area_fit",
    "center_offset_for_bounds",
    "copy_source_part_with_adjustment",
    "external_import_work_area_fit",
    "external_import_work_area_fit_from_bounds",
    "fit_uniform_scale_for_bounds",
    "global_fast_preview_transform_delta",
    "global_transform_values",
    "mirror_submesh_x",
    "part_bbox",
    "part_bbox_center",
    "part_bbox_diagonal",
    "part_fast_preview_transform_delta",
    "part_transform_values",
    "point_inside_expanded_bbox",
    "reference_vertices_for_appended_part",
    "source_mirror_plane_x",
    "transformed_vertices_for_work_area",
    "vertices_for_source_indices",
]
