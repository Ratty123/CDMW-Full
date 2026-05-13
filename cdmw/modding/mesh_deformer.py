"""Topology-preserving mesh deformation helpers for in-app OBJ editing."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .mesh_parser import ParsedMesh, SubMesh, _compute_smooth_normals


Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class MeshTopologySignature:
    submesh_count: int
    vertex_counts: tuple[int, ...]
    face_counts: tuple[int, ...]
    faces: tuple[tuple[tuple[int, int, int], ...], ...]


def mesh_topology_signature(mesh: ParsedMesh) -> MeshTopologySignature:
    return MeshTopologySignature(
        submesh_count=len(mesh.submeshes),
        vertex_counts=tuple(len(submesh.vertices) for submesh in mesh.submeshes),
        face_counts=tuple(len(submesh.faces) for submesh in mesh.submeshes),
        faces=tuple(tuple(tuple(int(index) for index in face[:3]) for face in submesh.faces) for submesh in mesh.submeshes),
    )


def assert_mesh_topology_unchanged(before: MeshTopologySignature, mesh: ParsedMesh) -> None:
    after = mesh_topology_signature(mesh)
    if after != before:
        raise ValueError("Mesh edit changed topology; only existing vertex positions may be modified.")


def clone_mesh_for_editing(mesh: ParsedMesh) -> ParsedMesh:
    return copy.deepcopy(mesh)


def recompute_submesh_normals(submesh: SubMesh) -> None:
    submesh.normals = _compute_smooth_normals(submesh.vertices, submesh.faces)


def recompute_mesh_normals(mesh: ParsedMesh) -> None:
    for submesh in mesh.submeshes:
        recompute_submesh_normals(submesh)


def _vec3(value: Sequence[object], fallback: Vec3 = (0.0, 0.0, 0.0)) -> Vec3:
    if len(value) < 3:
        return fallback
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError, OverflowError):
        return fallback


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a: Vec3, scale: float) -> Vec3:
    return (a[0] * scale, a[1] * scale, a[2] * scale)


def _length(a: Vec3) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _normalize(a: Vec3, fallback: Vec3 = (0.0, 1.0, 0.0)) -> Vec3:
    length = _length(a)
    if length <= 1e-8:
        return fallback
    return (a[0] / length, a[1] / length, a[2] / length)


def brush_falloff_weight(distance: float, radius: float, falloff: str = "smooth") -> float:
    try:
        normalized = max(0.0, min(1.0, float(distance) / max(float(radius), 1e-8)))
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if normalized >= 1.0:
        return 0.0
    mode = str(falloff or "smooth").strip().lower()
    if mode == "linear":
        return 1.0 - normalized
    if mode == "sharp":
        return (1.0 - normalized) ** 2
    if mode == "constant":
        return 1.0
    t = normalized
    return 1.0 - (t * t * (3.0 - 2.0 * t))


def build_vertex_adjacency(submesh: SubMesh) -> list[set[int]]:
    adjacency = [set() for _vertex in submesh.vertices]
    for face in submesh.faces:
        if len(face) < 3:
            continue
        a, b, c = (int(face[0]), int(face[1]), int(face[2]))
        if 0 <= a < len(adjacency) and 0 <= b < len(adjacency) and 0 <= c < len(adjacency):
            adjacency[a].update((b, c))
            adjacency[b].update((a, c))
            adjacency[c].update((a, b))
    return adjacency


def build_x_mirror_pairs(vertices: Sequence[Sequence[object]], *, tolerance: float = 1e-4) -> dict[int, int]:
    buckets: dict[tuple[int, int, int], list[int]] = {}
    normalized_vertices = [_vec3(vertex) for vertex in vertices]
    scale = 1.0 / max(float(tolerance), 1e-8)
    for index, vertex in enumerate(normalized_vertices):
        key = (round(vertex[0] * scale), round(vertex[1] * scale), round(vertex[2] * scale))
        buckets.setdefault(key, []).append(index)
    pairs: dict[int, int] = {}
    for index, vertex in enumerate(normalized_vertices):
        mirror_key = (round(-vertex[0] * scale), round(vertex[1] * scale), round(vertex[2] * scale))
        candidates = buckets.get(mirror_key, [])
        if not candidates:
            continue
        best = min(
            candidates,
            key=lambda candidate: _length(
                _sub(normalized_vertices[candidate], (-vertex[0], vertex[1], vertex[2]))
            ),
        )
        pairs[index] = best
    return pairs


def _affected_vertex_weights(
    submesh: SubMesh,
    *,
    center: Vec3,
    radius: float,
    falloff: str,
    vertex_indices: Iterable[int] | None,
    vertex_weights: Mapping[int, float] | Iterable[Sequence[object]] | None = None,
) -> dict[int, float]:
    allowed = None
    if vertex_indices is not None:
        allowed = set()
        for raw_index in vertex_indices:
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(submesh.vertices):
                allowed.add(index)
    if vertex_weights is not None:
        explicit_weights: dict[int, float] = {}
        items: Iterable[object]
        if isinstance(vertex_weights, Mapping):
            items = vertex_weights.items()
        else:
            items = vertex_weights
        for item in items:
            try:
                raw_index, raw_weight = item  # type: ignore[misc]
                index = int(raw_index)
                weight = max(0.0, min(1.0, float(raw_weight)))
            except (TypeError, ValueError, OverflowError):
                continue
            if 0 <= index < len(submesh.vertices) and (allowed is None or index in allowed) and weight > 0.0:
                explicit_weights[index] = max(explicit_weights.get(index, 0.0), weight)
        return explicit_weights
    weights: dict[int, float] = {}
    indexed_vertices = (
        ((index, submesh.vertices[index]) for index in allowed)
        if allowed is not None
        else enumerate(submesh.vertices)
    )
    for index, raw_vertex in indexed_vertices:
        vertex = _vec3(raw_vertex)
        weight = brush_falloff_weight(_length(_sub(vertex, center)), radius, falloff)
        if weight > 0.0 or (allowed is not None and index in allowed):
            weights[index] = max(weight, 1.0 if allowed is not None and radius <= 1e-8 else weight)
    return weights


def _with_mirror_weights(
    submesh: SubMesh,
    weights: Mapping[int, float],
    *,
    mirror_x: bool,
    mirror_pairs: Mapping[int, int] | None = None,
) -> dict[int, tuple[float, bool]]:
    result: dict[int, tuple[float, bool]] = {int(index): (float(weight), False) for index, weight in weights.items()}
    if not mirror_x:
        return result
    pairs = dict(mirror_pairs or build_x_mirror_pairs(submesh.vertices))
    for index, weight in weights.items():
        mirror_index = pairs.get(int(index))
        if mirror_index is None:
            continue
        previous = result.get(mirror_index)
        if previous is None or float(weight) > previous[0]:
            result[mirror_index] = (float(weight), True)
    return result


def apply_vertex_delta(
    submesh: SubMesh,
    vertex_indices: Iterable[int],
    delta: Sequence[object],
    *,
    mirror_x: bool = False,
    mirror_pairs: Mapping[int, int] | None = None,
    recompute_normals: bool = True,
) -> list[int]:
    delta_vec = _vec3(delta)
    direct_weights: dict[int, float] = {}
    for raw_index in vertex_indices:
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(submesh.vertices):
            direct_weights[index] = 1.0
    weighted_indices = _with_mirror_weights(
        submesh,
        direct_weights,
        mirror_x=mirror_x,
        mirror_pairs=mirror_pairs,
    )
    if not weighted_indices:
        return []
    vertices = list(submesh.vertices)
    changed: list[int] = []
    for index, (_weight, mirrored) in weighted_indices.items():
        applied_delta = (-delta_vec[0], delta_vec[1], delta_vec[2]) if mirrored else delta_vec
        vertices[index] = _add(_vec3(vertices[index]), applied_delta)
        changed.append(index)
    submesh.vertices = vertices
    submesh.vertex_count = len(vertices)
    if recompute_normals:
        recompute_submesh_normals(submesh)
    return sorted(changed)


def apply_brush_deformation(
    submesh: SubMesh,
    *,
    tool: str,
    center: Sequence[object],
    radius: float,
    strength: float,
    drag_delta: Sequence[object] = (0.0, 0.0, 0.0),
    amount: float = 0.0,
    falloff: str = "smooth",
    vertex_indices: Iterable[int] | None = None,
    vertex_weights: Mapping[int, float] | Iterable[Sequence[object]] | None = None,
    mirror_x: bool = False,
    mirror_pairs: Mapping[int, int] | None = None,
    adjacency: Sequence[set[int]] | None = None,
    invert: bool = False,
    recompute_normals: bool = True,
) -> list[int]:
    if not submesh.vertices:
        return []
    tool_key = str(tool or "grab").strip().lower()
    center_vec = _vec3(center)
    radius_value = max(float(radius), 1e-8)
    strength_value = max(0.0, min(1.0, float(strength)))
    delta_vec = _vec3(drag_delta)
    direct_weights = _affected_vertex_weights(
        submesh,
        center=center_vec,
        radius=radius_value,
        falloff=falloff,
        vertex_indices=vertex_indices,
        vertex_weights=vertex_weights,
    )
    weighted_indices = _with_mirror_weights(
        submesh,
        direct_weights,
        mirror_x=mirror_x,
        mirror_pairs=mirror_pairs,
    )
    if not weighted_indices:
        return []

    vertices = [_vec3(vertex) for vertex in submesh.vertices]
    normals = (
        [_vec3(normal, (0.0, 1.0, 0.0)) for normal in submesh.normals]
        if len(submesh.normals) == len(vertices)
        else _compute_smooth_normals(vertices, submesh.faces)
    )
    adjacency_map = list(adjacency or build_vertex_adjacency(submesh)) if tool_key == "smooth" else []
    amount_value = float(amount)
    if abs(amount_value) <= 1e-8:
        amount_value = _length(delta_vec)
    amount_value *= strength_value
    new_vertices = list(vertices)

    for index, (weight, mirrored) in weighted_indices.items():
        vertex = vertices[index]
        effective_weight = float(weight) * strength_value
        applied_delta = (-delta_vec[0], delta_vec[1], delta_vec[2]) if mirrored else delta_vec
        if tool_key == "grab":
            new_vertices[index] = _add(vertex, _mul(applied_delta, float(weight) * strength_value))
        elif tool_key == "inflate":
            direction = _normalize(normals[index], _normalize(_sub(vertex, center_vec)))
            signed_amount = -amount_value if invert else amount_value
            new_vertices[index] = _add(vertex, _mul(direction, signed_amount * float(weight)))
        elif tool_key == "pinch":
            local_center = (-center_vec[0], center_vec[1], center_vec[2]) if mirrored else center_vec
            direction = _normalize(_sub(local_center, vertex), (0.0, 0.0, 0.0))
            signed_amount = -abs(amount_value) if invert else abs(amount_value)
            new_vertices[index] = _add(vertex, _mul(direction, signed_amount * float(weight)))
        elif tool_key == "smooth":
            neighbors = adjacency_map[index] if index < len(adjacency_map) else set()
            if not neighbors:
                continue
            avg = (
                sum(vertices[neighbor][0] for neighbor in neighbors) / len(neighbors),
                sum(vertices[neighbor][1] for neighbor in neighbors) / len(neighbors),
                sum(vertices[neighbor][2] for neighbor in neighbors) / len(neighbors),
            )
            blend = max(0.0, min(1.0, effective_weight))
            new_vertices[index] = (
                vertex[0] + (avg[0] - vertex[0]) * blend,
                vertex[1] + (avg[1] - vertex[1]) * blend,
                vertex[2] + (avg[2] - vertex[2]) * blend,
            )
        else:
            new_vertices[index] = _add(vertex, _mul(applied_delta, float(weight) * strength_value))

    submesh.vertices = new_vertices
    submesh.vertex_count = len(new_vertices)
    if recompute_normals:
        recompute_submesh_normals(submesh)
    return sorted(weighted_indices)
