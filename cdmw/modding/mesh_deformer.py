"""Topology-preserving mesh deformation helpers for in-app OBJ editing."""

from __future__ import annotations

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


@dataclass(frozen=True)
class MeshFaceDeleteResult:
    affected_submesh_indices: tuple[int, ...] = ()
    emptied_submesh_indices: tuple[int, ...] = ()
    removed_face_count: int = 0
    removed_vertex_count: int = 0


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
    extra_submesh_attrs = (
        "texture_slots",
        "preview_color",
        "preview_normal_texture_path",
        "preview_normal_texture_name",
        "preview_normal_texture_strength",
        "preview_material_texture_path",
        "preview_material_texture_name",
        "preview_material_texture_type",
        "preview_material_texture_subtype",
        "preview_material_texture_packed_channels",
        "preview_material_texture_inputs",
        "preview_material_parameters",
        "preview_height_texture_path",
        "preview_height_texture_name",
        "preview_sidecar_shader_family",
    )

    def clone_submesh(submesh: SubMesh) -> SubMesh:
        cloned = SubMesh(
            name=str(submesh.name or ""),
            material=str(submesh.material or ""),
            texture=str(submesh.texture or ""),
            vertices=list(submesh.vertices or []),
            uvs=list(submesh.uvs or []),
            normals=list(submesh.normals or []),
            faces=list(submesh.faces or []),
            bone_indices=list(submesh.bone_indices or []),
            bone_weights=list(submesh.bone_weights or []),
            source_vertex_map=list(submesh.source_vertex_map or []),
            vertex_count=int(submesh.vertex_count or 0),
            face_count=int(submesh.face_count or 0),
            source_vertex_offsets=list(submesh.source_vertex_offsets or []),
            source_index_offset=int(submesh.source_index_offset or -1),
            source_index_count=int(submesh.source_index_count or 0),
            source_vertex_stride=int(submesh.source_vertex_stride or 0),
            source_descriptor_offset=int(submesh.source_descriptor_offset or -1),
            source_bbox_min=tuple(submesh.source_bbox_min or (0.0, 0.0, 0.0)),
            source_bbox_extent=tuple(submesh.source_bbox_extent or (0.0, 0.0, 0.0)),
            source_lod_count=int(submesh.source_lod_count or 0),
        )
        for attr_name in extra_submesh_attrs:
            if hasattr(submesh, attr_name):
                setattr(cloned, attr_name, getattr(submesh, attr_name))
        return cloned

    return ParsedMesh(
        path=str(mesh.path or ""),
        format=str(mesh.format or ""),
        bbox_min=tuple(mesh.bbox_min or (0.0, 0.0, 0.0)),
        bbox_max=tuple(mesh.bbox_max or (0.0, 0.0, 0.0)),
        submeshes=[clone_submesh(submesh) for submesh in mesh.submeshes],
        lod_levels=[
            [clone_submesh(submesh) for submesh in lod_level]
            for lod_level in (mesh.lod_levels or [])
        ],
        total_vertices=int(mesh.total_vertices or 0),
        total_faces=int(mesh.total_faces or 0),
        has_uvs=bool(mesh.has_uvs),
        has_bones=bool(mesh.has_bones),
    )


def recompute_submesh_normals(submesh: SubMesh) -> None:
    submesh.normals = _compute_smooth_normals(submesh.vertices, submesh.faces)


def recompute_mesh_normals(mesh: ParsedMesh) -> None:
    for submesh in mesh.submeshes:
        recompute_submesh_normals(submesh)


def _remap_vertex_aligned_list(values: Sequence[object], index_map: Mapping[int, int], old_vertex_count: int) -> list[object]:
    if len(values) != old_vertex_count:
        return []
    remapped: list[object] = [None] * len(index_map)
    for old_index, new_index in index_map.items():
        remapped[new_index] = values[old_index]
    return remapped


def _valid_vertex_index_set(vertex_indices: Iterable[int], vertex_count: int) -> set[int]:
    selected: set[int] = set()
    for raw_index in vertex_indices:
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if 0 <= index < vertex_count:
            selected.add(index)
    return selected


def _delete_faces_touching_submesh_vertices(
    submesh: SubMesh,
    vertex_indices: Iterable[int],
    *,
    remove_orphans: bool,
    recompute_normals: bool,
) -> tuple[int, int, bool]:
    old_vertex_count = len(submesh.vertices)
    selected = _valid_vertex_index_set(vertex_indices, old_vertex_count)
    if not selected:
        return 0, 0, False

    kept_faces: list[tuple[int, int, int]] = []
    removed_faces = 0
    for face in submesh.faces:
        if len(face) < 3:
            continue
        try:
            a, b, c = (int(face[0]), int(face[1]), int(face[2]))
        except (TypeError, ValueError):
            continue
        if a in selected or b in selected or c in selected:
            removed_faces += 1
            continue
        if 0 <= a < old_vertex_count and 0 <= b < old_vertex_count and 0 <= c < old_vertex_count:
            kept_faces.append((a, b, c))
    if removed_faces <= 0:
        return 0, 0, False

    removed_vertices = 0
    if remove_orphans:
        used_vertex_indices = sorted({index for face in kept_faces for index in face})
        index_map = {old_index: new_index for new_index, old_index in enumerate(used_vertex_indices)}
        submesh.vertices = [submesh.vertices[old_index] for old_index in used_vertex_indices]
        submesh.uvs = _remap_vertex_aligned_list(submesh.uvs, index_map, old_vertex_count)  # type: ignore[assignment]
        submesh.normals = _remap_vertex_aligned_list(submesh.normals, index_map, old_vertex_count)  # type: ignore[assignment]
        submesh.bone_indices = _remap_vertex_aligned_list(submesh.bone_indices, index_map, old_vertex_count)  # type: ignore[assignment]
        submesh.bone_weights = _remap_vertex_aligned_list(submesh.bone_weights, index_map, old_vertex_count)  # type: ignore[assignment]
        submesh.source_vertex_map = _remap_vertex_aligned_list(submesh.source_vertex_map, index_map, old_vertex_count)  # type: ignore[assignment]
        submesh.source_vertex_offsets = _remap_vertex_aligned_list(submesh.source_vertex_offsets, index_map, old_vertex_count)  # type: ignore[assignment]
        submesh.faces = [
            (index_map[a], index_map[b], index_map[c])
            for a, b, c in kept_faces
            if a in index_map and b in index_map and c in index_map
        ]
        removed_vertices = old_vertex_count - len(submesh.vertices)
    else:
        submesh.faces = kept_faces
    submesh.vertex_count = len(submesh.vertices)
    submesh.face_count = len(submesh.faces)
    if recompute_normals:
        recompute_submesh_normals(submesh)
    return removed_faces, removed_vertices, not bool(submesh.faces)


def _compact_orphan_vertices_for_submesh(
    submesh: SubMesh,
    *,
    recompute_normals: bool,
) -> tuple[int, bool]:
    old_vertex_count = len(submesh.vertices)
    if old_vertex_count <= 0:
        submesh.vertex_count = 0
        submesh.face_count = len(submesh.faces)
        return 0, not bool(submesh.faces)

    valid_faces: list[tuple[int, int, int]] = []
    for face in submesh.faces:
        if len(face) < 3:
            continue
        try:
            a, b, c = (int(face[0]), int(face[1]), int(face[2]))
        except (TypeError, ValueError):
            continue
        if 0 <= a < old_vertex_count and 0 <= b < old_vertex_count and 0 <= c < old_vertex_count:
            valid_faces.append((a, b, c))

    used_vertex_indices = sorted({index for face in valid_faces for index in face})
    index_map = {old_index: new_index for new_index, old_index in enumerate(used_vertex_indices)}
    if len(index_map) != old_vertex_count or len(valid_faces) != len(submesh.faces):
        submesh.vertices = [submesh.vertices[old_index] for old_index in used_vertex_indices]
        submesh.uvs = _remap_vertex_aligned_list(submesh.uvs, index_map, old_vertex_count)  # type: ignore[assignment]
        submesh.normals = _remap_vertex_aligned_list(submesh.normals, index_map, old_vertex_count)  # type: ignore[assignment]
        submesh.bone_indices = _remap_vertex_aligned_list(submesh.bone_indices, index_map, old_vertex_count)  # type: ignore[assignment]
        submesh.bone_weights = _remap_vertex_aligned_list(submesh.bone_weights, index_map, old_vertex_count)  # type: ignore[assignment]
        submesh.source_vertex_map = _remap_vertex_aligned_list(submesh.source_vertex_map, index_map, old_vertex_count)  # type: ignore[assignment]
        submesh.source_vertex_offsets = _remap_vertex_aligned_list(submesh.source_vertex_offsets, index_map, old_vertex_count)  # type: ignore[assignment]
        submesh.faces = [
            (index_map[a], index_map[b], index_map[c])
            for a, b, c in valid_faces
            if a in index_map and b in index_map and c in index_map
        ]

    submesh.vertex_count = len(submesh.vertices)
    submesh.face_count = len(submesh.faces)
    if recompute_normals:
        recompute_submesh_normals(submesh)
    return old_vertex_count - len(submesh.vertices), not bool(submesh.faces)


def compact_orphan_vertices(
    mesh: ParsedMesh | SubMesh,
    submesh_indices: Iterable[int] | None = None,
    *,
    recompute_normals: bool = True,
) -> MeshFaceDeleteResult:
    if isinstance(mesh, SubMesh):
        removed_vertices, emptied = _compact_orphan_vertices_for_submesh(
            mesh,
            recompute_normals=recompute_normals,
        )
        return MeshFaceDeleteResult(
            affected_submesh_indices=(0,) if removed_vertices else (),
            emptied_submesh_indices=(0,) if emptied and removed_vertices else (),
            removed_vertex_count=removed_vertices,
        )

    if submesh_indices is None:
        target_indices = range(len(mesh.submeshes))
    else:
        target_indices = []
        for raw_index in submesh_indices:
            try:
                submesh_index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if 0 <= submesh_index < len(mesh.submeshes):
                target_indices.append(submesh_index)

    affected: list[int] = []
    emptied: list[int] = []
    removed_vertex_count = 0
    for submesh_index in target_indices:
        removed_vertices, is_empty = _compact_orphan_vertices_for_submesh(
            mesh.submeshes[int(submesh_index)],
            recompute_normals=recompute_normals,
        )
        if removed_vertices <= 0:
            continue
        affected.append(int(submesh_index))
        if is_empty:
            emptied.append(int(submesh_index))
        removed_vertex_count += removed_vertices

    mesh.total_vertices = sum(len(submesh.vertices) for submesh in mesh.submeshes)
    mesh.total_faces = sum(len(submesh.faces) for submesh in mesh.submeshes)
    mesh.has_uvs = any(bool(submesh.uvs) for submesh in mesh.submeshes)
    mesh.has_bones = any(bool(submesh.bone_indices) or bool(submesh.bone_weights) for submesh in mesh.submeshes)
    return MeshFaceDeleteResult(
        affected_submesh_indices=tuple(affected),
        emptied_submesh_indices=tuple(emptied),
        removed_vertex_count=removed_vertex_count,
    )


def delete_faces_touching_vertices(
    mesh: ParsedMesh | SubMesh,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]] | Iterable[int],
    *,
    remove_orphans: bool = True,
    recompute_normals: bool = True,
) -> MeshFaceDeleteResult:
    if isinstance(mesh, SubMesh):
        if isinstance(selected_vertices_by_submesh, Mapping):
            submesh_vertex_indices: list[object] = []
            for values in selected_vertices_by_submesh.values():
                submesh_vertex_indices.extend(tuple(values or ()))
        else:
            submesh_vertex_indices = list(tuple(selected_vertices_by_submesh or ()))
        removed_faces, removed_vertices, emptied = _delete_faces_touching_submesh_vertices(
            mesh,
            submesh_vertex_indices,
            remove_orphans=remove_orphans,
            recompute_normals=recompute_normals,
        )
        return MeshFaceDeleteResult(
            affected_submesh_indices=(0,) if removed_faces else (),
            emptied_submesh_indices=(0,) if emptied and removed_faces else (),
            removed_face_count=removed_faces,
            removed_vertex_count=removed_vertices,
        )

    affected: list[int] = []
    emptied: list[int] = []
    removed_face_count = 0
    removed_vertex_count = 0
    if not isinstance(selected_vertices_by_submesh, Mapping):
        return MeshFaceDeleteResult()
    for raw_submesh_index, raw_vertex_indices in selected_vertices_by_submesh.items():
        try:
            submesh_index = int(raw_submesh_index)
        except (TypeError, ValueError):
            continue
        if submesh_index < 0 or submesh_index >= len(mesh.submeshes):
            continue
        removed_faces, removed_vertices, is_empty = _delete_faces_touching_submesh_vertices(
            mesh.submeshes[submesh_index],
            raw_vertex_indices,
            remove_orphans=remove_orphans,
            recompute_normals=recompute_normals,
        )
        if removed_faces <= 0:
            continue
        affected.append(submesh_index)
        if is_empty:
            emptied.append(submesh_index)
        removed_face_count += removed_faces
        removed_vertex_count += removed_vertices

    mesh.total_vertices = sum(len(submesh.vertices) for submesh in mesh.submeshes)
    mesh.total_faces = sum(len(submesh.faces) for submesh in mesh.submeshes)
    mesh.has_uvs = any(bool(submesh.uvs) for submesh in mesh.submeshes)
    mesh.has_bones = any(bool(submesh.bone_indices) or bool(submesh.bone_weights) for submesh in mesh.submeshes)
    return MeshFaceDeleteResult(
        affected_submesh_indices=tuple(affected),
        emptied_submesh_indices=tuple(emptied),
        removed_face_count=removed_face_count,
        removed_vertex_count=removed_vertex_count,
    )


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


def _normalized_selection_by_submesh(
    mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]] | Iterable[int],
) -> dict[int, set[int]]:
    if not isinstance(selected_vertices_by_submesh, Mapping):
        selected_vertices_by_submesh = {0: selected_vertices_by_submesh}
    result: dict[int, set[int]] = {}
    for raw_submesh_index, raw_vertices in selected_vertices_by_submesh.items():
        try:
            submesh_index = int(raw_submesh_index)
        except (TypeError, ValueError):
            continue
        if not (0 <= submesh_index < len(mesh.submeshes)):
            continue
        vertex_count = len(mesh.submeshes[submesh_index].vertices)
        selected: set[int] = set()
        for raw_vertex in tuple(raw_vertices or ()):
            try:
                vertex_index = int(raw_vertex)
            except (TypeError, ValueError):
                continue
            if 0 <= vertex_index < vertex_count:
                selected.add(vertex_index)
        if selected:
            result[submesh_index] = selected
    return result


def grow_vertex_selection(
    mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]] | Iterable[int],
    *,
    steps: int = 1,
) -> dict[int, set[int]]:
    selection = _normalized_selection_by_submesh(mesh, selected_vertices_by_submesh)
    for _step in range(max(0, int(steps or 0))):
        next_selection: dict[int, set[int]] = {index: set(vertices) for index, vertices in selection.items()}
        for submesh_index, selected in selection.items():
            adjacency = build_vertex_adjacency(mesh.submeshes[submesh_index])
            expanded = next_selection.setdefault(submesh_index, set())
            for vertex_index in selected:
                if 0 <= vertex_index < len(adjacency):
                    expanded.update(adjacency[vertex_index])
        selection = next_selection
    return selection


def shrink_vertex_selection(
    mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]] | Iterable[int],
    *,
    steps: int = 1,
) -> dict[int, set[int]]:
    selection = _normalized_selection_by_submesh(mesh, selected_vertices_by_submesh)
    for _step in range(max(0, int(steps or 0))):
        next_selection: dict[int, set[int]] = {}
        for submesh_index, selected in selection.items():
            adjacency = build_vertex_adjacency(mesh.submeshes[submesh_index])
            kept: set[int] = set()
            for vertex_index in selected:
                if not (0 <= vertex_index < len(adjacency)):
                    continue
                neighbors = adjacency[vertex_index]
                if not neighbors or all(neighbor in selected for neighbor in neighbors):
                    kept.add(vertex_index)
            if kept:
                next_selection[submesh_index] = kept
        selection = next_selection
    return selection


def smooth_vertex_selection(
    mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]] | Iterable[int],
    *,
    iterations: int = 1,
) -> dict[int, set[int]]:
    selection = _normalized_selection_by_submesh(mesh, selected_vertices_by_submesh)
    for _iteration in range(max(0, int(iterations or 0))):
        next_selection: dict[int, set[int]] = {}
        for submesh_index, submesh in enumerate(mesh.submeshes):
            selected = selection.get(submesh_index, set())
            if not selected:
                continue
            adjacency = build_vertex_adjacency(submesh)
            smoothed: set[int] = set()
            for vertex_index, neighbors in enumerate(adjacency):
                if not neighbors:
                    if vertex_index in selected:
                        smoothed.add(vertex_index)
                    continue
                selected_neighbor_count = sum(1 for neighbor in neighbors if neighbor in selected)
                ratio = selected_neighbor_count / max(1, len(neighbors))
                if vertex_index in selected:
                    if ratio >= 0.25:
                        smoothed.add(vertex_index)
                elif ratio >= 0.65:
                    smoothed.add(vertex_index)
            if smoothed:
                next_selection[submesh_index] = smoothed
        selection = next_selection
    return selection


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
