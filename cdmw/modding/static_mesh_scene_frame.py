"""Authoritative immutable placement frames for static mesh replacement."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from .mesh_parser import ParsedMesh, SubMesh
from .static_mesh_geometry import (
    _apply_transform,
    _bbox,
    _center,
    _compute_anchor_alignment,
    _is_marker_submesh,
)
from .static_mesh_types import StaticReplacementTransform


Vec3 = tuple[float, float, float]
Matrix4 = tuple[
    float, float, float, float,
    float, float, float, float,
    float, float, float, float,
    float, float, float, float,
]


@dataclass(frozen=True, slots=True)
class StaticAlignmentBasis:
    source_anchor: Vec3
    target_anchor: Vec3
    source_axis: Vec3
    target_axis: Vec3
    length_scale: float
    roll_radians: float
    fit_scale_xyz: Vec3
    fit_offset: Vec3
    model_matrix: Matrix4

    def as_legacy_alignment(self) -> dict[str, Vec3 | float]:
        return {
            "source_anchor": self.source_anchor,
            "target_anchor": self.target_anchor,
            "source_axis": self.source_axis,
            "target_axis": self.target_axis,
            "scale": self.length_scale,
            "roll_angle": self.roll_radians,
        }


@dataclass(frozen=True, slots=True)
class StaticManualTransformDelta:
    translation: Vec3
    rotation_degrees: Vec3
    scale_xyz: Vec3
    manual_adjustment: Vec3


@dataclass(frozen=True, slots=True)
class StaticWorldBounds:
    minimum: Vec3
    maximum: Vec3

    @property
    def center(self) -> Vec3:
        return _center(self.minimum, self.maximum)

    @property
    def extent(self) -> float:
        return max(self.maximum[index] - self.minimum[index] for index in range(3))


@dataclass(frozen=True, slots=True)
class StaticSceneRoleFrame:
    role: str
    model_matrix: Matrix4
    world_bounds: StaticWorldBounds
    visible: bool
    submesh_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class StaticGroundPlane:
    origin: Vec3
    normal: Vec3 = (0.0, 1.0, 0.0)


@dataclass(frozen=True, slots=True)
class StaticTransformFrame:
    """Exact affine components used by final static replacement output."""

    alignment: StaticAlignmentBasis
    manual_delta: StaticManualTransformDelta
    effective_model_matrix: Matrix4

    def transform_point(self, point: Vec3) -> Vec3:
        return matrix_transform_point(self.effective_model_matrix, point)


@dataclass(frozen=True, slots=True)
class StaticMeshSceneFrame:
    """One immutable Python-owned frame shared with the resident renderer."""

    format: str
    source_identity: str
    scene_generation: int
    transform: StaticTransformFrame
    editable: StaticSceneRoleFrame
    reference: StaticSceneRoleFrame
    placement_pivot: Vec3
    selection_pivot: Vec3 | None
    ground_plane: StaticGroundPlane
    grid_origin: Vec3
    framing_bounds: StaticWorldBounds
    framing_extent: float
    comparison_mode: str
    interaction_mode: str

    def with_protocol_context(
        self,
        *,
        source_identity: str | None = None,
        scene_generation: int | None = None,
        comparison_mode: str | None = None,
        interaction_mode: str | None = None,
    ) -> StaticMeshSceneFrame:
        comparison = _comparison_mode(comparison_mode or self.comparison_mode)
        return replace(
            self,
            source_identity=str(source_identity if source_identity is not None else self.source_identity),
            scene_generation=max(0, int(scene_generation if scene_generation is not None else self.scene_generation)),
            comparison_mode=comparison,
            interaction_mode=_interaction_mode(interaction_mode or self.interaction_mode),
            editable=replace(self.editable, visible=comparison != "original_only"),
            reference=replace(
                self.reference,
                visible=bool(self.reference.submesh_indices) and comparison != "replacement_only",
            ),
        )

    def to_protocol_payload(self) -> dict[str, object]:
        editable_bounds = _bounds_payload(self.editable.world_bounds)
        reference_bounds = _bounds_payload(self.reference.world_bounds)
        framing_bounds = _bounds_payload(self.framing_bounds)
        manual = self.transform.manual_delta
        alignment = self.transform.alignment
        return {
            "format": self.format,
            "protocol_version": 2,
            "source_identity": self.source_identity,
            "scene_generation": self.scene_generation,
            "coordinate_contract": {
                "matrix_layout": "row_major",
                "vector_convention": "row_vector",
                "handedness": "right_handed",
                "units": "source_mesh_units",
                "multiplication_order": "source_point_then_automatic_alignment_then_manual_delta",
            },
            "editable_submesh_count": len(self.editable.submesh_indices),
            "reference_submesh_count": len(self.reference.submesh_indices),
            "roles": {
                "editable": _role_payload(self.editable),
                "reference": _role_payload(self.reference),
                # Compatibility aliases retained for v1 package readers.
                "replacement": list(self.editable.submesh_indices),
                "original_reference": list(self.reference.submesh_indices),
            },
            "automatic_alignment": {
                "model_matrix": list(alignment.model_matrix),
                "source_anchor": list(alignment.source_anchor),
                "target_anchor": list(alignment.target_anchor),
                "source_axis": list(alignment.source_axis),
                "target_axis": list(alignment.target_axis),
                "length_scale": alignment.length_scale,
                "roll_radians": alignment.roll_radians,
                "fit_scale_xyz": list(alignment.fit_scale_xyz),
                "fit_offset": list(alignment.fit_offset),
            },
            "manual_delta": {
                "translation": list(manual.translation),
                "rotation_degrees": list(manual.rotation_degrees),
                "scale_xyz": list(manual.scale_xyz),
                "manual_adjustment": list(manual.manual_adjustment),
            },
            "placement": {
                "translation": list(manual.translation),
                "rotation_degrees": list(manual.rotation_degrees),
                "scale": list(manual.scale_xyz),
                "manual_adjustment": list(manual.manual_adjustment),
            },
            "placement_pivot": list(self.placement_pivot),
            "selection_pivot": list(self.selection_pivot) if self.selection_pivot is not None else None,
            "ground_plane": {
                "origin": list(self.ground_plane.origin),
                "normal": list(self.ground_plane.normal),
            },
            "grid": {
                "visible": True,
                "origin": list(self.grid_origin),
                "normal_axis": "y",
                "spacing": max(self.framing_extent / 10.0, 0.01),
                "major_line_every": 5,
            },
            "framing": {"bounds": framing_bounds, "extent": self.framing_extent},
            "bounds": framing_bounds,
            "editable_world_bounds": editable_bounds,
            "reference_world_bounds": reference_bounds,
            "comparison_mode": self.comparison_mode,
            "interaction_mode": self.interaction_mode,
            "gizmo": {"visible": True, "tool": "move", "space": "world"},
        }


def _vec3(value: Sequence[float]) -> Vec3:
    return float(value[0]), float(value[1]), float(value[2])


def _manual_delta(transform: StaticReplacementTransform) -> StaticManualTransformDelta:
    scale = transform.scale_xyz or (transform.scale, transform.scale, transform.scale)
    return StaticManualTransformDelta(
        translation=_vec3(transform.offset_xyz),
        rotation_degrees=_vec3(transform.rotate_xyz_degrees),
        scale_xyz=_vec3(scale),
        manual_adjustment=_vec3(transform.manual_adjustment),
    )


def _mesh_delta_bounds(submeshes: Sequence[SubMesh]) -> tuple[Vec3, Vec3]:
    vertices = [
        vertex
        for submesh in submeshes
        if not _is_marker_submesh(submesh)
        for vertex in tuple(getattr(submesh, "vertices", ()) or ())
    ]
    return _bbox(vertices)


def _matrix_from_transform(
    transform: StaticReplacementTransform,
    fit_scale_xyz: Vec3,
    fit_offset: Vec3,
    alignment: Mapping[str, Vec3 | float],
) -> Matrix4:
    origin = _apply_transform((0.0, 0.0, 0.0), transform, fit_scale_xyz, fit_offset, dict(alignment))
    columns = tuple(
        tuple(
            _apply_transform(axis, transform, fit_scale_xyz, fit_offset, dict(alignment))[component]
            - origin[component]
            for component in range(3)
        )
        for axis in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    )
    # System.Numerics consumes row-major Matrix4x4 fields with row-vector
    # coordinates. Translation therefore occupies M41/M42/M43.
    return (
        columns[0][0], columns[0][1], columns[0][2], 0.0,
        columns[1][0], columns[1][1], columns[1][2], 0.0,
        columns[2][0], columns[2][1], columns[2][2], 0.0,
        origin[0], origin[1], origin[2], 1.0,
    )


def matrix_transform_point(matrix: Matrix4, point: Vec3) -> Vec3:
    x, y, z = point
    return (
        x * matrix[0] + y * matrix[4] + z * matrix[8] + matrix[12],
        x * matrix[1] + y * matrix[5] + z * matrix[9] + matrix[13],
        x * matrix[2] + y * matrix[6] + z * matrix[10] + matrix[14],
    )


def build_static_transform_frame(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    transform: StaticReplacementTransform,
    *,
    alignment_source_indices: set[int] | None = None,
    include_grid_floor: bool = True,
    bounds_for_submeshes: Callable[[Sequence[SubMesh]], tuple[Vec3, Vec3]] | None = None,
) -> StaticTransformFrame:
    """Calculate the exact affine components used by final build math."""
    bound_indices = None if alignment_source_indices is None else {int(index) for index in alignment_source_indices}
    alignment_sources = [
        submesh
        for index, submesh in enumerate(tuple(replacement_mesh.submeshes or ()))
        if bound_indices is None or index in bound_indices
    ]
    alignment_mesh = ParsedMesh(path=replacement_mesh.path, format=replacement_mesh.format)
    alignment_mesh.submeshes = list(alignment_sources)
    alignment = _compute_anchor_alignment(original_mesh, alignment_mesh, transform)
    fit_scale_xyz: Vec3 = (1.0, 1.0, 1.0)
    fit_offset: Vec3 = (0.0, 0.0, 0.0)
    bounds_getter = bounds_for_submeshes or _mesh_delta_bounds
    if transform.fit_to_original_bbox:
        src_min, src_max = bounds_getter(alignment_sources)
        dst_min, dst_max = bounds_getter(original_mesh.submeshes)
        src_dims = tuple(src_max[index] - src_min[index] for index in range(3))
        dst_dims = tuple(dst_max[index] - dst_min[index] for index in range(3))
        if transform.preserve_aspect_ratio:
            ratios = [
                dst_dims[index] / src_dims[index]
                for index in range(3)
                if src_dims[index] > 1.0e-8
            ]
            uniform = min(ratios) if ratios else 1.0
            fit_scale_xyz = (uniform, uniform, uniform)
        else:
            fit_scale_xyz = tuple(
                dst_dims[index] / src_dims[index] if src_dims[index] > 1.0e-8 else 1.0
                for index in range(3)
            )  # type: ignore[assignment]
        src_center = _center(src_min, src_max)
        dst_center = _center(dst_min, dst_max)
        fit_offset = tuple(
            dst_center[index] - src_center[index] * fit_scale_xyz[index]
            for index in range(3)
        )  # type: ignore[assignment]
    if include_grid_floor and str(transform.alignment_mode or "").strip().lower() == "grid_flat":
        minimum_y: float | None = None
        for submesh in alignment_sources:
            if _is_marker_submesh(submesh):
                continue
            for vertex in tuple(getattr(submesh, "vertices", ()) or ()):
                y = _apply_transform(vertex, transform, fit_scale_xyz, fit_offset, alignment)[1]
                if math.isfinite(y):
                    minimum_y = y if minimum_y is None else min(minimum_y, y)
        if minimum_y is not None and abs(minimum_y) > 1.0e-8:
            fit_offset = (fit_offset[0], fit_offset[1] - minimum_y, fit_offset[2])

    automatic_transform = replace(
        transform,
        rotate_xyz_degrees=(0.0, 0.0, 0.0),
        scale=1.0,
        scale_xyz=(1.0, 1.0, 1.0),
        offset_xyz=(0.0, 0.0, 0.0),
        manual_adjustment=(0.0, 0.0, 0.0),
    )
    alignment_basis = StaticAlignmentBasis(
        source_anchor=_vec3(alignment["source_anchor"]),  # type: ignore[arg-type]
        target_anchor=_vec3(alignment["target_anchor"]),  # type: ignore[arg-type]
        source_axis=_vec3(alignment["source_axis"]),  # type: ignore[arg-type]
        target_axis=_vec3(alignment["target_axis"]),  # type: ignore[arg-type]
        length_scale=float(alignment["scale"]),
        roll_radians=float(alignment.get("roll_angle", 0.0) or 0.0),
        fit_scale_xyz=fit_scale_xyz,
        fit_offset=fit_offset,
        model_matrix=_matrix_from_transform(automatic_transform, fit_scale_xyz, fit_offset, alignment),
    )
    return StaticTransformFrame(
        alignment=alignment_basis,
        manual_delta=_manual_delta(transform),
        effective_model_matrix=_matrix_from_transform(transform, fit_scale_xyz, fit_offset, alignment),
    )


def _mesh_world_bounds(
    mesh: ParsedMesh,
    matrix: Matrix4,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> StaticWorldBounds:
    minimum = [math.inf, math.inf, math.inf]
    maximum = [-math.inf, -math.inf, -math.inf]
    found = False
    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        if cancelled is not None and cancelled():
            raise RuntimeError("authoritative scene-frame calculation cancelled")
        if _is_marker_submesh(submesh):
            continue
        for vertex in tuple(getattr(submesh, "vertices", ()) or ()):
            transformed = matrix_transform_point(matrix, _vec3(vertex))
            found = True
            for axis in range(3):
                minimum[axis] = min(minimum[axis], transformed[axis])
                maximum[axis] = max(maximum[axis], transformed[axis])
    if not found:
        return StaticWorldBounds((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    return StaticWorldBounds(_vec3(minimum), _vec3(maximum))


def _combined_bounds(*bounds: StaticWorldBounds) -> StaticWorldBounds:
    return StaticWorldBounds(
        tuple(min(item.minimum[axis] for item in bounds) for axis in range(3)),  # type: ignore[arg-type]
        tuple(max(item.maximum[axis] for item in bounds) for axis in range(3)),  # type: ignore[arg-type]
    )


def _comparison_mode(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"side_by_side", "overlay", "original_only", "replacement_only"}:
        return normalized
    if normalized in {"ghost"}:
        return "overlay"
    if normalized in {"source"}:
        return "original_only"
    return "replacement_only"


def _interaction_mode(value: str) -> str:
    return "mesh_edit" if str(value or "").strip().lower() == "mesh_edit" else "placement"


def _scene_identity_sample_indices(count: int, *, maximum: int = 65) -> tuple[int, ...]:
    if count <= 0:
        return ()
    if count <= maximum:
        return tuple(range(count))
    last = count - 1
    return tuple(sorted({round(last * offset / (maximum - 1)) for offset in range(maximum)}))


def _update_scene_identity_geometry(digest: Any, submesh: object) -> None:
    vertices = getattr(submesh, "vertices", ()) or ()
    faces = getattr(submesh, "faces", ()) or ()
    try:
        vertex_count = len(vertices)
    except TypeError:
        vertices = tuple(vertices)
        vertex_count = len(vertices)
    try:
        face_count = len(faces)
    except TypeError:
        faces = tuple(faces)
        face_count = len(faces)
    digest.update(f"vertices:{vertex_count}|faces:{face_count}|".encode("ascii"))
    for index in _scene_identity_sample_indices(vertex_count):
        digest.update(f"v:{index}:".encode("ascii"))
        digest.update(repr(_vec3(vertices[index])).encode("ascii", errors="replace"))
    for index in _scene_identity_sample_indices(face_count):
        digest.update(f"f:{index}:".encode("ascii"))
        try:
            value = tuple(int(component) for component in faces[index])
        except (TypeError, ValueError):
            value = repr(faces[index])
        digest.update(repr(value).encode("ascii", errors="replace"))


def static_scene_source_identity(mesh: ParsedMesh, reference_mesh: ParsedMesh | None = None) -> str:
    digest = hashlib.sha256()
    for role, item in (("editable", mesh), ("reference", reference_mesh)):
        digest.update(role.encode("utf-8"))
        if item is None:
            digest.update(b"none")
            continue
        digest.update(str(getattr(item, "path", "") or "").replace("\\", "/").encode("utf-8", errors="replace"))
        digest.update(str(getattr(item, "_cdmw_mesh_asset_source_hash", "") or "").encode("ascii", errors="ignore"))
        for submesh in tuple(getattr(item, "submeshes", ()) or ()):
            digest.update(str(getattr(submesh, "name", "") or "").encode("utf-8", errors="replace"))
            _update_scene_identity_geometry(digest, submesh)
    return digest.hexdigest()


def build_authoritative_static_scene_frame(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    transform: StaticReplacementTransform,
    *,
    source_identity: str = "",
    scene_generation: int = 0,
    comparison_mode: str = "side_by_side",
    interaction_mode: str = "placement",
    alignment_source_indices: set[int] | None = None,
    selection_pivot_source: Vec3 | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> StaticMeshSceneFrame:
    transform_frame = build_static_transform_frame(
        original_mesh,
        replacement_mesh,
        transform,
        alignment_source_indices=alignment_source_indices,
    )
    editable_bounds = _mesh_world_bounds(
        replacement_mesh,
        transform_frame.effective_model_matrix,
        cancelled=cancelled,
    )
    reference_bounds = _mesh_world_bounds(original_mesh, IDENTITY_MATRIX, cancelled=cancelled)
    framing_bounds = _combined_bounds(editable_bounds, reference_bounds)
    editable_count = len(tuple(getattr(replacement_mesh, "submeshes", ()) or ()))
    reference_count = len(tuple(getattr(original_mesh, "submeshes", ()) or ()))
    comparison = _comparison_mode(comparison_mode)
    placement_pivot = transform_frame.transform_point(transform_frame.alignment.source_anchor)
    selection_pivot = (
        transform_frame.transform_point(selection_pivot_source)
        if selection_pivot_source is not None
        else None
    )
    ground_origin = (editable_bounds.center[0], editable_bounds.minimum[1], editable_bounds.center[2])
    identity = str(source_identity or static_scene_source_identity(replacement_mesh, original_mesh))
    return StaticMeshSceneFrame(
        format="cdmw_resident_scene_frame_v2",
        source_identity=identity,
        scene_generation=max(0, int(scene_generation)),
        transform=transform_frame,
        editable=StaticSceneRoleFrame(
            role="editable",
            model_matrix=transform_frame.effective_model_matrix,
            world_bounds=editable_bounds,
            visible=comparison != "original_only",
            submesh_indices=tuple(range(editable_count)),
        ),
        reference=StaticSceneRoleFrame(
            role="reference",
            model_matrix=IDENTITY_MATRIX,
            world_bounds=reference_bounds,
            visible=reference_count > 0 and comparison != "replacement_only",
            submesh_indices=tuple(range(editable_count, editable_count + reference_count)),
        ),
        placement_pivot=placement_pivot,
        selection_pivot=selection_pivot,
        ground_plane=StaticGroundPlane(ground_origin),
        grid_origin=ground_origin,
        framing_bounds=framing_bounds,
        framing_extent=max(0.01, framing_bounds.extent),
        comparison_mode=comparison,
        interaction_mode=_interaction_mode(interaction_mode),
    )


def selection_pivot_source_from_mesh(mesh: ParsedMesh, selection: object) -> Vec3 | None:
    """Return a source-space centroid for the current authoritative selection."""
    selected: dict[int, set[int]] = {}
    for attribute in ("vertices_by_submesh",):
        for raw_submesh, raw_indices in dict(getattr(selection, attribute, {}) or {}).items():
            selected.setdefault(int(raw_submesh), set()).update(int(index) for index in raw_indices)
    for raw_submesh, raw_edges in dict(getattr(selection, "edges_by_submesh", {}) or {}).items():
        target = selected.setdefault(int(raw_submesh), set())
        for edge in raw_edges:
            target.update((int(edge[0]), int(edge[1])))
    for raw_submesh, raw_faces in dict(getattr(selection, "faces_by_submesh", {}) or {}).items():
        submesh_index = int(raw_submesh)
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        target = selected.setdefault(submesh_index, set())
        faces = tuple(getattr(mesh.submeshes[submesh_index], "faces", ()) or ())
        for face_index in raw_faces:
            if 0 <= int(face_index) < len(faces):
                target.update(int(index) for index in faces[int(face_index)])
    for source_index in tuple(getattr(selection, "source_indices", ()) or ()):
        index = int(source_index)
        if 0 <= index < len(mesh.submeshes):
            selected.setdefault(index, set()).update(range(len(mesh.submeshes[index].vertices)))
    vertices = [
        mesh.submeshes[submesh_index].vertices[vertex_index]
        for submesh_index, indices in selected.items()
        if 0 <= submesh_index < len(mesh.submeshes)
        for vertex_index in indices
        if 0 <= vertex_index < len(mesh.submeshes[submesh_index].vertices)
    ]
    if not vertices:
        return None
    count = float(len(vertices))
    return tuple(sum(float(vertex[axis]) for vertex in vertices) / count for axis in range(3))  # type: ignore[return-value]


def _bounds_payload(bounds: StaticWorldBounds) -> dict[str, list[float]]:
    return {
        "min": list(bounds.minimum),
        "max": list(bounds.maximum),
        "center": list(bounds.center),
    }


def _role_payload(role: StaticSceneRoleFrame) -> dict[str, object]:
    return {
        "submesh_indices": list(role.submesh_indices),
        "model_matrix": list(role.model_matrix),
        "world_bounds": _bounds_payload(role.world_bounds),
        "visible": role.visible,
    }


IDENTITY_MATRIX: Matrix4 = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)


__all__ = [
    "IDENTITY_MATRIX",
    "StaticAlignmentBasis",
    "StaticGroundPlane",
    "StaticManualTransformDelta",
    "StaticMeshSceneFrame",
    "StaticSceneRoleFrame",
    "StaticTransformFrame",
    "StaticWorldBounds",
    "build_authoritative_static_scene_frame",
    "build_static_transform_frame",
    "matrix_transform_point",
    "selection_pivot_source_from_mesh",
    "static_scene_source_identity",
]
