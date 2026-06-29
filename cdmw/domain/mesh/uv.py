"""Pure Mesh Editor UV island summary helpers."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from .editing import MeshEditSelection

Vec2 = tuple[float, float]
UvKey = tuple[float, float]
UvEdgeKey = tuple[tuple[int, int], tuple[UvKey, UvKey]]


@dataclass(frozen=True, slots=True)
class MeshUvIslandSummary:
    index: int
    submesh_index: int
    part_name: str
    material: str
    texture: str
    vertex_count: int
    face_count: int
    uv_min: Vec2
    uv_max: Vec2
    selected: bool = False
    selected_vertex_count: int = 0
    selected_face_count: int = 0

    @property
    def bounds_text(self) -> str:
        return f"U {self.uv_min[0]:.3f}-{self.uv_max[0]:.3f} | V {self.uv_min[1]:.3f}-{self.uv_max[1]:.3f}"


@dataclass(frozen=True, slots=True)
class MeshUvSummary:
    island_count: int
    selected_island_count: int
    islands: tuple[MeshUvIslandSummary, ...] = ()


def mesh_uv_region_selection(mesh: object, uv_min: Vec2, uv_max: Vec2) -> MeshEditSelection:
    start = _uv_point(uv_min) or (0.0, 0.0)
    end = _uv_point(uv_max) or (0.0, 0.0)
    min_u, max_u = sorted((start[0], end[0]))
    min_v, max_v = sorted((start[1], end[1]))
    return _mesh_uv_point_selection(mesh, lambda point: min_u <= point[0] <= max_u and min_v <= point[1] <= max_v)


def mesh_uv_lasso_selection(mesh: object, points: tuple[object, ...]) -> MeshEditSelection:
    polygon = tuple(point for raw in points if (point := _uv_point(raw)) is not None)
    if len(polygon) < 3:
        return MeshEditSelection()
    return _mesh_uv_point_selection(mesh, lambda point: _point_in_polygon(point, polygon))


def _mesh_uv_point_selection(mesh: object, contains: Callable[[Vec2], bool]) -> MeshEditSelection:
    vertices_by_submesh: dict[int, set[int]] = {}
    for submesh_index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ())):
        vertices = tuple(getattr(submesh, "vertices", ()) or ())
        uvs = tuple(getattr(submesh, "uvs", ()) or ())
        if len(uvs) != len(vertices):
            continue
        selected = {
            index
            for index, uv in enumerate(uvs)
            if (point := _uv_point(uv)) is not None and contains(point)
        }
        if selected:
            vertices_by_submesh[submesh_index] = selected
    return MeshEditSelection.from_maps(vertices_by_submesh=vertices_by_submesh)


def summarize_mesh_uvs(mesh: object, selection: MeshEditSelection | None = None) -> MeshUvSummary:
    selected_sources = set(selection.source_indices if selection is not None else ())
    selected_vertices = selection.vertex_map() if selection is not None else {}
    selected_faces = selection.face_map() if selection is not None else {}
    islands: list[MeshUvIslandSummary] = []
    for submesh_index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ())):
        for island in _submesh_uv_islands(
            submesh_index,
            submesh,
            start_index=len(islands),
            source_selected=submesh_index in selected_sources,
            selected_vertices=selected_vertices.get(submesh_index, set()),
            selected_faces=selected_faces.get(submesh_index, set()),
        ):
            islands.append(island)
    return MeshUvSummary(
        island_count=len(islands),
        selected_island_count=sum(1 for island in islands if island.selected),
        islands=tuple(islands),
    )


def _submesh_uv_islands(
    submesh_index: int,
    submesh: object,
    *,
    start_index: int,
    source_selected: bool,
    selected_vertices: set[int],
    selected_faces: set[int],
) -> tuple[MeshUvIslandSummary, ...]:
    vertices = tuple(getattr(submesh, "vertices", ()) or ())
    uvs = tuple(getattr(submesh, "uvs", ()) or ())
    faces = tuple(getattr(submesh, "faces", ()) or ())
    if len(uvs) != len(vertices) or not faces:
        return ()

    face_vertices: dict[int, tuple[int, int, int]] = {}
    face_edges: dict[int, tuple[UvEdgeKey, ...]] = {}
    edge_faces: dict[UvEdgeKey, set[int]] = {}
    for face_index, face in enumerate(faces):
        indices = _valid_face_vertices(face, len(uvs))
        if len(indices) != 3:
            continue
        normalized = (indices[0], indices[1], indices[2])
        edges = tuple(_uv_face_edges(normalized, uvs))
        face_vertices[face_index] = normalized
        face_edges[face_index] = edges
        for edge in edges:
            edge_faces.setdefault(edge, set()).add(face_index)

    summaries: list[MeshUvIslandSummary] = []
    visited: set[int] = set()
    for face_index in sorted(face_vertices):
        if face_index in visited:
            continue
        island_faces = _connected_uv_faces(face_index, face_edges, edge_faces, visited)
        island_vertices = {
            vertex_index
            for island_face_index in island_faces
            for vertex_index in face_vertices.get(island_face_index, ())
        }
        if not island_vertices:
            continue
        uv_values = [_vec2(uvs[vertex_index]) for vertex_index in sorted(island_vertices)]
        uv_min = (min(value[0] for value in uv_values), min(value[1] for value in uv_values))
        uv_max = (max(value[0] for value in uv_values), max(value[1] for value in uv_values))
        selected_vertex_count = len(island_vertices & selected_vertices)
        selected_face_count = len(island_faces & selected_faces)
        summaries.append(
            MeshUvIslandSummary(
                index=start_index + len(summaries),
                submesh_index=submesh_index,
                part_name=str(getattr(submesh, "name", "") or f"part_{submesh_index}"),
                material=str(getattr(submesh, "material", "") or ""),
                texture=str(getattr(submesh, "texture", "") or ""),
                vertex_count=len(island_vertices),
                face_count=len(island_faces),
                uv_min=uv_min,
                uv_max=uv_max,
                selected=bool(source_selected or selected_vertex_count or selected_face_count),
                selected_vertex_count=selected_vertex_count,
                selected_face_count=selected_face_count,
            )
        )
    return tuple(summaries)


def _connected_uv_faces(
    seed: int,
    face_edges: dict[int, tuple[UvEdgeKey, ...]],
    edge_faces: dict[UvEdgeKey, set[int]],
    visited: set[int],
) -> set[int]:
    pending = [seed]
    island: set[int] = set()
    while pending:
        face_index = pending.pop()
        if face_index in island or face_index in visited:
            continue
        island.add(face_index)
        visited.add(face_index)
        for edge in face_edges.get(face_index, ()):
            pending.extend(edge_faces.get(edge, set()) - island)
    return island


def _uv_face_edges(face: tuple[int, int, int], uvs: tuple[object, ...]) -> tuple[UvEdgeKey, ...]:
    return tuple(
        (_edge_key(face[index], face[(index + 1) % 3]), _uv_edge_key(uvs[face[index]], uvs[face[(index + 1) % 3]]))
        for index in range(3)
    )


def _valid_face_vertices(face: object, vertex_count: int) -> list[int]:
    if not isinstance(face, (tuple, list)):
        return []
    items = tuple(face or ())
    if len(items) < 3:
        return []
    indices: list[int] = []
    for raw_index in items[:3]:
        vertex_index = _coerce_index(raw_index)
        if vertex_index is None or vertex_index < 0 or vertex_index >= vertex_count:
            return []
        indices.append(vertex_index)
    return indices


def _coerce_index(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text or any(marker in text for marker in ".eE"):
            return None
        try:
            return int(text, 10)
        except ValueError:
            return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None


def _vec2(value: object, fallback: Vec2 = (0.0, 0.0)) -> Vec2:
    if not isinstance(value, (tuple, list)) or len(value) < 2:
        return fallback
    try:
        parsed = (float(value[0]), float(value[1]))
    except (TypeError, ValueError, OverflowError):
        return fallback
    return parsed if all(math.isfinite(component) for component in parsed) else fallback


def _uv_point(value: object) -> Vec2 | None:
    if not isinstance(value, (tuple, list)) or len(value) < 2:
        return None
    try:
        parsed = (float(value[0]), float(value[1]))
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if all(math.isfinite(component) for component in parsed) else None


def _point_in_polygon(point: Vec2, polygon: tuple[Vec2, ...]) -> bool:
    inside = False
    x, y = point
    previous = polygon[-1]
    for current in polygon:
        if _point_on_segment(point, previous, current):
            return True
        crosses = (current[1] > y) != (previous[1] > y)
        if crosses:
            slope_x = (previous[0] - current[0]) * (y - current[1]) / (previous[1] - current[1]) + current[0]
            if x <= slope_x:
                inside = not inside
        previous = current
    return inside


def _point_on_segment(point: Vec2, left: Vec2, right: Vec2) -> bool:
    cross = (point[1] - left[1]) * (right[0] - left[0]) - (point[0] - left[0]) * (right[1] - left[1])
    if abs(cross) > 1e-9:
        return False
    return min(left[0], right[0]) - 1e-9 <= point[0] <= max(left[0], right[0]) + 1e-9 and min(left[1], right[1]) - 1e-9 <= point[1] <= max(left[1], right[1]) + 1e-9


def _uv_edge_key(left: object, right: object) -> tuple[UvKey, UvKey]:
    a = _uv_key(left)
    b = _uv_key(right)
    return (a, b) if a <= b else (b, a)


def _uv_key(value: object) -> UvKey:
    u, v = _vec2(value)
    return (round(u, 6), round(v, 6))


def _edge_key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a <= b else (b, a)


__all__ = [
    "MeshUvIslandSummary",
    "MeshUvSummary",
    "mesh_uv_lasso_selection",
    "mesh_uv_region_selection",
    "summarize_mesh_uvs",
]
