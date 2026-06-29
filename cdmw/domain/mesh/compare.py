"""Pure source-vs-edited Mesh Editor comparison helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]

_EPSILON = 1.0e-5


@dataclass(frozen=True, slots=True)
class MeshBoundsSummary:
    minimum: Vec3
    maximum: Vec3
    size: Vec3
    center: Vec3
    diagonal: float

    @property
    def size_text(self) -> str:
        return _vec3_text(self.size)

    @property
    def center_text(self) -> str:
        return _vec3_text(self.center)

    @property
    def axis_profile_text(self) -> str:
        return f"X {self.size[0]:.3f} | Y {self.size[1]:.3f} | Z {self.size[2]:.3f}"


@dataclass(frozen=True, slots=True)
class MeshPartCompareSummary:
    index: int
    original_name: str
    edited_name: str
    original_material: str
    edited_material: str
    original_texture: str
    edited_texture: str
    original_vertex_count: int
    edited_vertex_count: int
    original_face_count: int
    edited_face_count: int
    original_uv_count: int
    edited_uv_count: int
    original_bounds: MeshBoundsSummary
    edited_bounds: MeshBoundsSummary
    original_missing: bool = False
    edited_missing: bool = False
    topology_changed: bool = False
    material_changed: bool = False
    texture_changed: bool = False
    uv_changed: bool = False
    bounds_changed: bool = False

    @property
    def changed(self) -> bool:
        return bool(
            self.original_missing
            or self.edited_missing
            or self.topology_changed
            or self.material_changed
            or self.texture_changed
            or self.uv_changed
            or self.bounds_changed
        )

    @property
    def label(self) -> str:
        name = self.edited_name or self.original_name or f"part_{self.index}"
        return f"{self.index}: {name}"

    @property
    def change_text(self) -> str:
        labels: list[str] = []
        if self.original_missing:
            labels.append("added")
        if self.edited_missing:
            labels.append("removed")
        if self.topology_changed:
            labels.append("topology")
        if self.material_changed:
            labels.append("material")
        if self.texture_changed:
            labels.append("texture")
        if self.uv_changed:
            labels.append("uv")
        if self.bounds_changed:
            labels.append("bounds")
        return ", ".join(labels) if labels else "matching"


@dataclass(frozen=True, slots=True)
class MeshCompareSummary:
    mesh_format: str
    original_part_count: int
    edited_part_count: int
    original_vertex_count: int
    edited_vertex_count: int
    original_face_count: int
    edited_face_count: int
    original_bounds: MeshBoundsSummary
    edited_bounds: MeshBoundsSummary
    scale_ratio: float
    original_orientation_axis: str
    edited_orientation_axis: str
    part_count_changed: bool
    topology_changed: bool
    bounds_changed: bool
    scale_changed: bool
    orientation_changed: bool
    material_mismatch_count: int
    texture_mismatch_count: int
    uv_mismatch_count: int
    bounds_mismatch_count: int
    changed_part_count: int
    parts: tuple[MeshPartCompareSummary, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(
            self.part_count_changed
            or self.topology_changed
            or self.bounds_changed
            or self.scale_changed
            or self.orientation_changed
            or self.material_mismatch_count
            or self.texture_mismatch_count
            or self.uv_mismatch_count
            or self.bounds_mismatch_count
        )

    @property
    def scale_text(self) -> str:
        if math.isinf(self.scale_ratio):
            return "inf"
        return f"{self.scale_ratio:.3f}x"


def compare_meshes(original_mesh: object, edited_mesh: object) -> MeshCompareSummary:
    original_submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ())
    edited_submeshes = tuple(getattr(edited_mesh, "submeshes", ()) or ())
    original_bounds = _mesh_bounds(original_submeshes)
    edited_bounds = _mesh_bounds(edited_submeshes)
    parts = tuple(
        _part_compare(
            index,
            original_submeshes[index] if index < len(original_submeshes) else None,
            edited_submeshes[index] if index < len(edited_submeshes) else None,
        )
        for index in range(max(len(original_submeshes), len(edited_submeshes)))
    )
    original_axis = _dominant_axis(original_bounds.size)
    edited_axis = _dominant_axis(edited_bounds.size)
    scale_ratio = _scale_ratio(original_bounds.diagonal, edited_bounds.diagonal)
    topology_changed = len(original_submeshes) != len(edited_submeshes) or any(part.topology_changed for part in parts)
    return MeshCompareSummary(
        mesh_format=str(getattr(edited_mesh, "format", "") or getattr(original_mesh, "format", "") or "").strip().lower(),
        original_part_count=len(original_submeshes),
        edited_part_count=len(edited_submeshes),
        original_vertex_count=sum(_vertex_count(submesh) for submesh in original_submeshes),
        edited_vertex_count=sum(_vertex_count(submesh) for submesh in edited_submeshes),
        original_face_count=sum(_face_count(submesh) for submesh in original_submeshes),
        edited_face_count=sum(_face_count(submesh) for submesh in edited_submeshes),
        original_bounds=original_bounds,
        edited_bounds=edited_bounds,
        scale_ratio=scale_ratio,
        original_orientation_axis=original_axis,
        edited_orientation_axis=edited_axis,
        part_count_changed=len(original_submeshes) != len(edited_submeshes),
        topology_changed=topology_changed,
        bounds_changed=not _bounds_close(original_bounds, edited_bounds),
        scale_changed=not _close(scale_ratio, 1.0),
        orientation_changed=bool(original_axis and edited_axis and original_axis != edited_axis),
        material_mismatch_count=sum(1 for part in parts if part.material_changed),
        texture_mismatch_count=sum(1 for part in parts if part.texture_changed),
        uv_mismatch_count=sum(1 for part in parts if part.uv_changed),
        bounds_mismatch_count=sum(1 for part in parts if part.bounds_changed),
        changed_part_count=sum(1 for part in parts if part.changed),
        parts=parts,
    )


def _part_compare(index: int, original: object | None, edited: object | None) -> MeshPartCompareSummary:
    original_bounds = _submesh_bounds(original)
    edited_bounds = _submesh_bounds(edited)
    has_both = original is not None and edited is not None
    original_uvs = _uv_signature(original)
    edited_uvs = _uv_signature(edited)
    return MeshPartCompareSummary(
        index=index,
        original_name=_name(original, index),
        edited_name=_name(edited, index),
        original_material=_text_attr(original, "material"),
        edited_material=_text_attr(edited, "material"),
        original_texture=_text_attr(original, "texture"),
        edited_texture=_text_attr(edited, "texture"),
        original_vertex_count=_vertex_count(original),
        edited_vertex_count=_vertex_count(edited),
        original_face_count=_face_count(original),
        edited_face_count=_face_count(edited),
        original_uv_count=len(original_uvs),
        edited_uv_count=len(edited_uvs),
        original_bounds=original_bounds,
        edited_bounds=edited_bounds,
        original_missing=original is None and edited is not None,
        edited_missing=edited is None and original is not None,
        topology_changed=not has_both or _vertex_count(original) != _vertex_count(edited) or _face_count(original) != _face_count(edited),
        material_changed=has_both and _text_attr(original, "material") != _text_attr(edited, "material"),
        texture_changed=has_both and _text_attr(original, "texture") != _text_attr(edited, "texture"),
        uv_changed=has_both and original_uvs != edited_uvs,
        bounds_changed=has_both and not _bounds_close(original_bounds, edited_bounds),
    )


def _mesh_bounds(submeshes: tuple[object, ...]) -> MeshBoundsSummary:
    return _bounds_for_vertices(vertex for submesh in submeshes for vertex in tuple(getattr(submesh, "vertices", ()) or ()))


def _submesh_bounds(submesh: object | None) -> MeshBoundsSummary:
    return _bounds_for_vertices(tuple(getattr(submesh, "vertices", ()) or ()) if submesh is not None else ())


def _bounds_for_vertices(vertices: object) -> MeshBoundsSummary:
    parsed = tuple(vertex for vertex in (_vec3(value) for value in vertices) if vertex is not None)
    if not parsed:
        return MeshBoundsSummary((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 0.0)
    minimum = tuple(min(vertex[axis] for vertex in parsed) for axis in range(3))
    maximum = tuple(max(vertex[axis] for vertex in parsed) for axis in range(3))
    size = tuple(maximum[axis] - minimum[axis] for axis in range(3))
    center = tuple((minimum[axis] + maximum[axis]) * 0.5 for axis in range(3))
    diagonal = math.sqrt(sum(component * component for component in size))
    return MeshBoundsSummary(minimum, maximum, size, center, diagonal)


def _dominant_axis(size: Vec3) -> str:
    axes = (("X", abs(size[0])), ("Y", abs(size[1])), ("Z", abs(size[2])))
    ordered = sorted(axes, key=lambda item: item[1], reverse=True)
    if ordered[0][1] <= _EPSILON:
        return ""
    if ordered[1][1] > 0.0 and (ordered[0][1] - ordered[1][1]) <= ordered[0][1] * 0.05:
        return ""
    return ordered[0][0]


def _scale_ratio(original_diagonal: float, edited_diagonal: float) -> float:
    if original_diagonal <= _EPSILON:
        return 1.0 if edited_diagonal <= _EPSILON else math.inf
    return edited_diagonal / original_diagonal


def _bounds_close(left: MeshBoundsSummary, right: MeshBoundsSummary) -> bool:
    return all(_close(left.size[index], right.size[index]) for index in range(3)) and all(
        _close(left.center[index], right.center[index]) for index in range(3)
    )


def _close(left: float, right: float) -> bool:
    return abs(float(left) - float(right)) <= _EPSILON


def _vertex_count(submesh: object | None) -> int:
    return len(tuple(getattr(submesh, "vertices", ()) or ())) if submesh is not None else 0


def _face_count(submesh: object | None) -> int:
    return len(tuple(getattr(submesh, "faces", ()) or ())) if submesh is not None else 0


def _uv_signature(submesh: object | None) -> tuple[Vec2 | None, ...]:
    if submesh is None:
        return ()
    return tuple(_uv_key(value) for value in tuple(getattr(submesh, "uvs", ()) or ()))


def _uv_key(value: object) -> Vec2 | None:
    parsed = _vec2(value)
    if parsed is None:
        return None
    return (round(parsed[0], 6), round(parsed[1], 6))


def _vec2(value: object) -> Vec2 | None:
    if not isinstance(value, (tuple, list)) or len(value) < 2:
        return None
    try:
        parsed = (float(value[0]), float(value[1]))
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if all(math.isfinite(component) for component in parsed) else None


def _vec3(value: object) -> Vec3 | None:
    if not isinstance(value, (tuple, list)) or len(value) < 3:
        return None
    try:
        parsed = (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if all(math.isfinite(component) for component in parsed) else None


def _vec3_text(value: Vec3) -> str:
    return f"{value[0]:.3f}, {value[1]:.3f}, {value[2]:.3f}"


def _name(source: object | None, index: int) -> str:
    return _text_attr(source, "name") or f"part_{index}"


def _text_attr(source: object | None, name: str) -> str:
    return str(getattr(source, name, "") or "").strip() if source is not None else ""


__all__ = [
    "MeshBoundsSummary",
    "MeshCompareSummary",
    "MeshPartCompareSummary",
    "compare_meshes",
]
