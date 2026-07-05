"""Mesh deformation helpers for in-app geometry editing."""

from __future__ import annotations

import math
import os
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


@dataclass
class MeshSubdivisionResult:
    affected_submesh_indices: tuple[int, ...] = ()
    changed_vertices_by_submesh: dict[int, set[int]] | None = None
    added_vertex_count: int = 0
    added_face_count: int = 0


@dataclass(frozen=True)
class MeshPartSplitResult:
    source_submesh_index: int = -1
    new_submesh_index: int = -1
    moved_face_count: int = 0
    moved_vertex_count: int = 0


_EXTRA_SUBMESH_ATTRS = (
    "texture_slots",
    "preview_color",
    "preview_role",
    "preview_texture_path",
    "preview_texture_name",
    "preview_texture_dds_path",
    "preview_texture_flip_vertical",
    "preview_texture_brightness",
    "preview_texture_contrast",
    "preview_texture_saturation",
    "preview_texture_gamma",
    "preview_texture_tint",
    "preview_texture_uv_scale",
    "preview_base_texture_default_path",
    "preview_base_texture_default_name",
    "preview_vertex_color_mean",
    "preview_vertex_alpha_mean",
    "preview_vertex_alpha_min",
    "preview_vertex_color_count",
    "preview_normal_texture_path",
    "preview_normal_texture_name",
    "preview_normal_texture_dds_path",
    "preview_normal_texture_strength",
    "preview_material_texture_path",
    "preview_material_texture_name",
    "preview_material_texture_dds_path",
    "preview_material_texture_type",
    "preview_material_texture_subtype",
    "preview_material_texture_packed_channels",
    "preview_material_texture_inputs",
    "preview_material_parameters",
    "preview_material_texture_default_path",
    "preview_material_texture_default_name",
    "preview_native_material_overrides",
    "preview_height_texture_path",
    "preview_height_texture_name",
    "preview_height_texture_dds_path",
    "preview_alpha_mode",
    "preview_double_sided",
    "preview_sidecar_shader_family",
    "cdmw_material_authority_profile",
    "cdmw_material_authority_contract",
    "cdmw_source_material_name",
    "cdmw_target_material_name",
    "cdmw_target_material_slot_index",
    "cdmw_material_slot_kind",
    "cdmw_source_texture_set_key",
    "cdmw_material_route_status",
    "cdmw_material_route_reason",
    "cdmw_mesh_edit_material_source_submesh_index",
    "cdmw_mesh_edit_topology_source_submesh_index",
    "cdmw_native_preview_triangle_group",
    "cdmw_native_preview_vertex_update_group",
)


def _copy_extra_submesh_attrs(source: SubMesh, target: SubMesh) -> None:
    for attr_name in _EXTRA_SUBMESH_ATTRS:
        if hasattr(source, attr_name):
            value = getattr(source, attr_name)
            if isinstance(value, dict):
                value = dict(value)
            elif isinstance(value, list):
                value = list(value)
            elif isinstance(value, set):
                value = set(value)
            setattr(target, attr_name, value)


def mesh_topology_signature(mesh: ParsedMesh) -> MeshTopologySignature:
    return MeshTopologySignature(
        submesh_count=len(mesh.submeshes),
        vertex_counts=tuple(len(submesh.vertices) for submesh in mesh.submeshes),
        face_counts=tuple(len(submesh.faces) for submesh in mesh.submeshes),
        faces=tuple(_topology_face_triples(submesh) for submesh in mesh.submeshes),
    )


def _topology_face_triples(submesh: SubMesh) -> tuple[tuple[int, int, int], ...]:
    vertex_count = len(submesh.vertices or ())
    triples: list[tuple[int, int, int]] = []
    for face in submesh.faces or ():
        if len(face) < 3:
            continue
        try:
            a, b, c = (int(face[0]), int(face[1]), int(face[2]))
        except (TypeError, ValueError, OverflowError):
            continue
        if 0 <= a < vertex_count and 0 <= b < vertex_count and 0 <= c < vertex_count:
            triples.append((a, b, c))
    return tuple(triples)


def assert_mesh_topology_unchanged(before: MeshTopologySignature, mesh: ParsedMesh) -> None:
    after = mesh_topology_signature(mesh)
    if after != before:
        raise ValueError("Mesh edit changed topology; only existing vertex positions may be modified.")


def clone_mesh_for_editing(mesh: ParsedMesh) -> ParsedMesh:
    def clone_submesh(submesh: SubMesh) -> SubMesh:
        cloned = SubMesh(
            name=str(submesh.name or ""),
            material=str(submesh.material or ""),
            texture=str(submesh.texture or ""),
            vertices=list(submesh.vertices or []),
            uvs=list(submesh.uvs or []),
            normals=list(submesh.normals or []),
            tangents=list(submesh.tangents or []),
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
        _copy_extra_submesh_attrs(submesh, cloned)
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
        except (TypeError, ValueError, OverflowError):
            continue
        if 0 <= index < vertex_count:
            selected.add(index)
    return selected


def _average_tuple(values: Sequence[object], a: int, b: int, old_vertex_count: int) -> tuple[float, ...] | None:
    if len(values) != old_vertex_count:
        return None
    try:
        left = tuple(float(component) for component in values[a])  # type: ignore[arg-type]
        right = tuple(float(component) for component in values[b])  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError, IndexError):
        return None
    length = min(len(left), len(right))
    if length <= 0:
        return None
    return tuple((left[index] + right[index]) * 0.5 for index in range(length))


def _blend_bone_assignment(
    bone_indices: Sequence[object],
    bone_weights: Sequence[object],
    a: int,
    b: int,
    old_vertex_count: int,
) -> tuple[tuple[int, ...], tuple[float, ...]] | None:
    if len(bone_indices) != old_vertex_count or len(bone_weights) != old_vertex_count:
        return None
    try:
        left_indices = tuple(int(value) for value in bone_indices[a])  # type: ignore[arg-type]
        right_indices = tuple(int(value) for value in bone_indices[b])  # type: ignore[arg-type]
        left_weights = tuple(float(value) for value in bone_weights[a])  # type: ignore[arg-type]
        right_weights = tuple(float(value) for value in bone_weights[b])  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError, IndexError):
        return None
    weight_by_bone: dict[int, float] = {}
    for bone, weight in zip(left_indices, left_weights):
        if bone >= 0 and weight > 0.0:
            weight_by_bone[bone] = weight_by_bone.get(bone, 0.0) + weight * 0.5
    for bone, weight in zip(right_indices, right_weights):
        if bone >= 0 and weight > 0.0:
            weight_by_bone[bone] = weight_by_bone.get(bone, 0.0) + weight * 0.5
    width = max(1, min(8, max(len(left_indices), len(right_indices), 4)))
    top = sorted(weight_by_bone.items(), key=lambda item: item[1], reverse=True)[:width]
    total = sum(weight for _bone, weight in top) or 1.0
    blended_indices = [bone for bone, _weight in top]
    blended_weights = [weight / total for _bone, weight in top]
    while len(blended_indices) < width:
        blended_indices.append(0)
        blended_weights.append(0.0)
    return tuple(blended_indices), tuple(blended_weights)


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
        except (TypeError, ValueError, OverflowError):
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


def _delete_submesh_faces_by_indices(
    submesh: SubMesh,
    face_indices: Iterable[int],
    *,
    remove_orphans: bool,
    recompute_normals: bool,
) -> tuple[int, int, bool]:
    old_vertex_count = len(submesh.vertices)
    old_face_count = len(submesh.faces)
    selected_faces: set[int] = set()
    for raw_index in face_indices:
        try:
            face_index = int(raw_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if 0 <= face_index < old_face_count:
            selected_faces.add(face_index)
    if not selected_faces:
        return 0, 0, False

    kept_faces: list[tuple[int, int, int]] = []
    removed_faces = 0
    for face_index, face in enumerate(submesh.faces):
        if len(face) < 3:
            continue
        try:
            a, b, c = (int(face[0]), int(face[1]), int(face[2]))
        except (TypeError, ValueError, OverflowError):
            continue
        if face_index in selected_faces:
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
        except (TypeError, ValueError, OverflowError):
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
            except (TypeError, ValueError, OverflowError):
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
        except (TypeError, ValueError, OverflowError):
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


def delete_faces_by_indices(
    mesh: ParsedMesh | SubMesh,
    selected_faces_by_submesh: Mapping[int, Iterable[int]] | Iterable[int],
    *,
    remove_orphans: bool = True,
    recompute_normals: bool = True,
) -> MeshFaceDeleteResult:
    """Delete exact face indices without expanding through shared vertices."""

    if isinstance(mesh, SubMesh):
        if isinstance(selected_faces_by_submesh, Mapping):
            submesh_face_indices: list[object] = []
            for values in selected_faces_by_submesh.values():
                submesh_face_indices.extend(tuple(values or ()))
        else:
            submesh_face_indices = list(tuple(selected_faces_by_submesh or ()))
        removed_faces, removed_vertices, emptied = _delete_submesh_faces_by_indices(
            mesh,
            submesh_face_indices,
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
    if not isinstance(selected_faces_by_submesh, Mapping):
        return MeshFaceDeleteResult()
    for raw_submesh_index, raw_face_indices in selected_faces_by_submesh.items():
        try:
            submesh_index = int(raw_submesh_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if submesh_index < 0 or submesh_index >= len(mesh.submeshes):
            continue
        removed_faces, removed_vertices, is_empty = _delete_submesh_faces_by_indices(
            mesh.submeshes[submesh_index],
            raw_face_indices,
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


def _valid_face_index_set(face_indices: Iterable[int], face_count: int) -> set[int]:
    selected: set[int] = set()
    for raw_index in face_indices:
        try:
            index = int(raw_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if 0 <= index < face_count:
            selected.add(index)
    return selected


def _face_indices_touching_vertices(submesh: SubMesh, vertex_indices: Iterable[int]) -> set[int]:
    selected_vertices = _valid_vertex_index_set(vertex_indices, len(submesh.vertices))
    if not selected_vertices:
        return set()
    selected_faces: set[int] = set()
    for face_index, face in enumerate(submesh.faces or ()):
        if len(face) < 3:
            continue
        try:
            a, b, c = (int(face[0]), int(face[1]), int(face[2]))
        except (TypeError, ValueError, OverflowError):
            continue
        if a in selected_vertices or b in selected_vertices or c in selected_vertices:
            selected_faces.add(face_index)
    return selected_faces


def _compact_submesh_faces(submesh: SubMesh, kept_faces: Sequence[tuple[int, int, int]]) -> int:
    old_vertex_count = len(submesh.vertices)
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
    submesh.vertex_count = len(submesh.vertices)
    submesh.face_count = len(submesh.faces)
    return old_vertex_count - len(submesh.vertices)


def split_faces_to_submesh(
    mesh: ParsedMesh,
    *,
    selected_faces_by_submesh: Mapping[int, Iterable[int]] | None = None,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]] | None = None,
    name_suffix: str = " split",
    recompute_normals: bool = True,
) -> MeshPartSplitResult:
    face_groups: dict[int, set[int]] = {}
    for raw_submesh_index, raw_faces in (selected_faces_by_submesh or {}).items():
        try:
            submesh_index = int(raw_submesh_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if 0 <= submesh_index < len(mesh.submeshes):
            faces = _valid_face_index_set(raw_faces, len(mesh.submeshes[submesh_index].faces))
            if faces:
                face_groups[submesh_index] = faces
    if not face_groups:
        for raw_submesh_index, raw_vertices in (selected_vertices_by_submesh or {}).items():
            try:
                submesh_index = int(raw_submesh_index)
            except (TypeError, ValueError, OverflowError):
                continue
            if 0 <= submesh_index < len(mesh.submeshes):
                faces = _face_indices_touching_vertices(mesh.submeshes[submesh_index], raw_vertices)
                if faces:
                    face_groups[submesh_index] = faces
    if not face_groups:
        return MeshPartSplitResult()
    if len(face_groups) != 1:
        raise ValueError("Select faces from one part before splitting.")

    source_submesh_index, selected_faces = next(iter(face_groups.items()))
    source = mesh.submeshes[source_submesh_index]
    old_vertex_count = len(source.vertices)
    moved_faces: list[tuple[int, int, int]] = []
    kept_faces: list[tuple[int, int, int]] = []
    for face_index, face in enumerate(source.faces or ()):
        if len(face) < 3:
            continue
        try:
            normalized_face = (int(face[0]), int(face[1]), int(face[2]))
        except (TypeError, ValueError, OverflowError):
            continue
        if any(index < 0 or index >= old_vertex_count for index in normalized_face):
            continue
        if face_index in selected_faces:
            moved_faces.append(normalized_face)
        else:
            kept_faces.append(normalized_face)
    if not moved_faces:
        return MeshPartSplitResult(source_submesh_index=source_submesh_index)

    moved_vertex_indices = sorted({index for face in moved_faces for index in face})
    moved_index_map = {old_index: new_index for new_index, old_index in enumerate(moved_vertex_indices)}
    new_name_base = str(source.name or source.material or f"part {source_submesh_index}").strip()
    new_submesh = SubMesh(
        name=f"{new_name_base}{name_suffix}",
        material=str(source.material or ""),
        texture=str(source.texture or ""),
        vertices=[source.vertices[old_index] for old_index in moved_vertex_indices],
        uvs=_remap_vertex_aligned_list(source.uvs, moved_index_map, old_vertex_count),  # type: ignore[arg-type]
        normals=_remap_vertex_aligned_list(source.normals, moved_index_map, old_vertex_count),  # type: ignore[arg-type]
        faces=[
            (moved_index_map[a], moved_index_map[b], moved_index_map[c])
            for a, b, c in moved_faces
        ],
        bone_indices=_remap_vertex_aligned_list(source.bone_indices, moved_index_map, old_vertex_count),  # type: ignore[arg-type]
        bone_weights=_remap_vertex_aligned_list(source.bone_weights, moved_index_map, old_vertex_count),  # type: ignore[arg-type]
        source_vertex_map=_remap_vertex_aligned_list(source.source_vertex_map, moved_index_map, old_vertex_count),  # type: ignore[arg-type]
        source_vertex_offsets=_remap_vertex_aligned_list(source.source_vertex_offsets, moved_index_map, old_vertex_count),  # type: ignore[arg-type]
        source_index_offset=-1,
        source_index_count=0,
        source_vertex_stride=int(source.source_vertex_stride or 0),
        source_descriptor_offset=-1,
        source_bbox_min=tuple(source.source_bbox_min or (0.0, 0.0, 0.0)),
        source_bbox_extent=tuple(source.source_bbox_extent or (0.0, 0.0, 0.0)),
        source_lod_count=int(source.source_lod_count or 0),
    )
    new_submesh.vertex_count = len(new_submesh.vertices)
    new_submesh.face_count = len(new_submesh.faces)
    _copy_extra_submesh_attrs(source, new_submesh)
    new_submesh.cdmw_mesh_edit_material_source_submesh_index = source_submesh_index
    new_submesh.cdmw_mesh_edit_topology_source_submesh_index = source_submesh_index
    removed_vertices = _compact_submesh_faces(source, kept_faces)
    if recompute_normals:
        if source.faces:
            recompute_submesh_normals(source)
        recompute_submesh_normals(new_submesh)
    mesh.submeshes.append(new_submesh)
    mesh.total_vertices = sum(len(submesh.vertices) for submesh in mesh.submeshes)
    mesh.total_faces = sum(len(submesh.faces) for submesh in mesh.submeshes)
    mesh.has_uvs = any(bool(submesh.uvs) for submesh in mesh.submeshes)
    mesh.has_bones = any(bool(submesh.bone_indices) or bool(submesh.bone_weights) for submesh in mesh.submeshes)
    return MeshPartSplitResult(
        source_submesh_index=source_submesh_index,
        new_submesh_index=len(mesh.submeshes) - 1,
        moved_face_count=len(moved_faces),
        moved_vertex_count=len(moved_vertex_indices),
    )


def subdivide_faces_touching_vertices(
    mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]] | None = None,
    *,
    selected_faces_by_submesh: Mapping[int, Iterable[int]] | None = None,
    max_faces_per_submesh: int = 256,
    recompute_normals: bool = True,
) -> MeshSubdivisionResult:
    affected: list[int] = []
    changed_vertices: dict[int, set[int]] = {}
    added_vertex_count = 0
    added_face_count = 0
    face_limit = max(1, _int_value(max_faces_per_submesh, 1))
    face_groups: dict[int, set[int]] = {}
    for raw_submesh_index, raw_faces in (selected_faces_by_submesh or {}).items():
        try:
            submesh_index = int(raw_submesh_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if submesh_index < 0 or submesh_index >= len(mesh.submeshes):
            continue
        faces = _valid_face_index_set(raw_faces, len(mesh.submeshes[submesh_index].faces))
        if faces:
            face_groups[submesh_index] = set(sorted(faces)[:face_limit])

    selection_items = face_groups.items() if face_groups else (selected_vertices_by_submesh or {}).items()
    for raw_submesh_index, raw_selection in selection_items:
        try:
            submesh_index = int(raw_submesh_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if submesh_index < 0 or submesh_index >= len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        old_vertex_count = len(submesh.vertices)
        if not submesh.faces:
            continue

        if face_groups:
            split_face_indices = set(raw_selection)
        else:
            selected = _valid_vertex_index_set(raw_selection, old_vertex_count)
            if not selected:
                continue
            split_face_indices: set[int] = set()
            for face_index, face in enumerate(submesh.faces or ()):
                if len(face) < 3:
                    continue
                try:
                    a, b, c = (int(face[0]), int(face[1]), int(face[2]))
                except (TypeError, ValueError, OverflowError):
                    continue
                if a in selected or b in selected or c in selected:
                    split_face_indices.add(face_index)
                    if len(split_face_indices) >= face_limit:
                        break
        if not split_face_indices:
            continue

        vertices = [_vec3(vertex) for vertex in submesh.vertices]
        original_uvs = list(submesh.uvs or [])
        original_normals = list(submesh.normals or [])
        original_bone_indices = list(submesh.bone_indices or [])
        original_bone_weights = list(submesh.bone_weights or [])
        original_source_vertex_map = list(submesh.source_vertex_map or [])
        original_source_vertex_offsets = list(submesh.source_vertex_offsets or [])
        has_uvs = len(original_uvs) == old_vertex_count
        has_normals = len(original_normals) == old_vertex_count
        has_bones = len(original_bone_indices) == old_vertex_count and len(original_bone_weights) == old_vertex_count
        has_source_vertex_map = len(original_source_vertex_map) == old_vertex_count
        has_source_vertex_offsets = len(original_source_vertex_offsets) == old_vertex_count
        uvs = list(original_uvs) if has_uvs else []
        normals = list(original_normals) if has_normals else []
        bone_indices = list(original_bone_indices) if has_bones else []
        bone_weights = list(original_bone_weights) if has_bones else []
        source_vertex_map = list(original_source_vertex_map) if has_source_vertex_map else []
        source_vertex_offsets = list(original_source_vertex_offsets) if has_source_vertex_offsets else []
        edge_midpoints: dict[tuple[int, int], int] = {}
        touched = changed_vertices.setdefault(submesh_index, set())

        def midpoint_index(a: int, b: int) -> int:
            nonlocal added_vertex_count
            key = (a, b) if a <= b else (b, a)
            existing = edge_midpoints.get(key)
            if existing is not None:
                return existing
            midpoint = (
                (vertices[a][0] + vertices[b][0]) * 0.5,
                (vertices[a][1] + vertices[b][1]) * 0.5,
                (vertices[a][2] + vertices[b][2]) * 0.5,
            )
            new_index = len(vertices)
            vertices.append(midpoint)
            averaged_uv = _average_tuple(original_uvs, a, b, old_vertex_count) if has_uvs else None
            if has_uvs and averaged_uv is not None:
                uvs.append(averaged_uv)  # type: ignore[arg-type]
            averaged_normal = _average_tuple(original_normals, a, b, old_vertex_count) if has_normals else None
            if has_normals and averaged_normal is not None and len(averaged_normal) >= 3:
                normals.append(_normalize(averaged_normal[:3]))  # type: ignore[arg-type]
            blended_bones = (
                _blend_bone_assignment(original_bone_indices, original_bone_weights, a, b, old_vertex_count)
                if has_bones
                else None
            )
            if has_bones and blended_bones is not None:
                indices, weights = blended_bones
                bone_indices.append(indices)  # type: ignore[arg-type]
                bone_weights.append(weights)  # type: ignore[arg-type]
            if has_source_vertex_map:
                source_vertex_map.append(-1)
            if has_source_vertex_offsets:
                source_vertex_offsets.append(-1)
            edge_midpoints[key] = new_index
            touched.add(new_index)
            added_vertex_count += 1
            return new_index

        new_faces: list[tuple[int, int, int]] = []
        for face_index, face in enumerate(submesh.faces or ()):
            if len(face) < 3:
                continue
            try:
                a, b, c = (int(face[0]), int(face[1]), int(face[2]))
            except (TypeError, ValueError, OverflowError):
                continue
            if not (0 <= a < old_vertex_count and 0 <= b < old_vertex_count and 0 <= c < old_vertex_count):
                continue
            if face_index not in split_face_indices:
                new_faces.append((a, b, c))
                continue
            ab = midpoint_index(a, b)
            bc = midpoint_index(b, c)
            ca = midpoint_index(c, a)
            touched.update((a, b, c, ab, bc, ca))
            new_faces.extend(
                (
                    (a, ab, ca),
                    (ab, b, bc),
                    (ca, bc, c),
                    (ab, bc, ca),
                )
            )
            added_face_count += 3

        submesh.vertices = vertices
        if len(uvs) == len(vertices):
            submesh.uvs = uvs  # type: ignore[assignment]
        if len(normals) == len(vertices):
            submesh.normals = normals  # type: ignore[assignment]
        if len(bone_indices) == len(vertices):
            submesh.bone_indices = bone_indices  # type: ignore[assignment]
        if len(bone_weights) == len(vertices):
            submesh.bone_weights = bone_weights  # type: ignore[assignment]
        if len(source_vertex_map) == len(vertices):
            submesh.source_vertex_map = source_vertex_map  # type: ignore[assignment]
        if len(source_vertex_offsets) == len(vertices):
            submesh.source_vertex_offsets = source_vertex_offsets  # type: ignore[assignment]
        submesh.faces = new_faces
        submesh.vertex_count = len(vertices)
        submesh.face_count = len(new_faces)
        if recompute_normals:
            recompute_submesh_normals(submesh)
        affected.append(submesh_index)

    if affected:
        mesh.total_vertices = sum(len(submesh.vertices) for submesh in mesh.submeshes)
        mesh.total_faces = sum(len(submesh.faces) for submesh in mesh.submeshes)
        mesh.has_uvs = any(bool(submesh.uvs) for submesh in mesh.submeshes)
        mesh.has_bones = any(bool(submesh.bone_indices) or bool(submesh.bone_weights) for submesh in mesh.submeshes)
    return MeshSubdivisionResult(
        affected_submesh_indices=tuple(affected),
        changed_vertices_by_submesh=changed_vertices,
        added_vertex_count=added_vertex_count,
        added_face_count=added_face_count,
    )


def _vec3(value: Sequence[object], fallback: Vec3 = (0.0, 0.0, 0.0)) -> Vec3:
    if len(value) < 3:
        return fallback
    try:
        parsed = (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError, OverflowError):
        return fallback
    return parsed if all(math.isfinite(component) for component in parsed) else fallback


def _finite_float(value: object, fallback: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return parsed if math.isfinite(parsed) else fallback


def _int_value(value: object, fallback: int = 1) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
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


def _same_vec3(a: Vec3, b: Vec3) -> bool:
    return abs(a[0] - b[0]) <= 1e-8 and abs(a[1] - b[1]) <= 1e-8 and abs(a[2] - b[2]) <= 1e-8


def _normalize(a: Vec3, fallback: Vec3 = (0.0, 1.0, 0.0)) -> Vec3:
    length = _length(a)
    if length <= 1e-8:
        return fallback
    return (a[0] / length, a[1] / length, a[2] / length)


def brush_falloff_weight(distance: float, radius: float, falloff: str = "smooth") -> float:
    normalized = max(0.0, min(1.0, _finite_float(distance) / max(_finite_float(radius), 1e-8)))
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
        try:
            a, b, c = (int(face[0]), int(face[1]), int(face[2]))
        except (TypeError, ValueError, OverflowError):
            continue
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
        except (TypeError, ValueError, OverflowError):
            continue
        if not (0 <= submesh_index < len(mesh.submeshes)):
            continue
        vertex_count = len(mesh.submeshes[submesh_index].vertices)
        selected: set[int] = set()
        for raw_vertex in raw_vertices or ():
            try:
                vertex_index = int(raw_vertex)
            except (TypeError, ValueError, OverflowError):
                continue
            if 0 <= vertex_index < vertex_count:
                selected.add(vertex_index)
        if selected:
            result[submesh_index] = selected
    return result


def _native_vertex_selection(
    mesh: ParsedMesh,
    selection: dict[int, set[int]],
    *,
    operation: str,
    iterations: int,
) -> dict[int, set[int]] | None:
    try:
        from .mesh_native_core import apply_native_mesh_selection
    except ImportError:
        return None
    return apply_native_mesh_selection(mesh, selection, operation=operation, iterations=iterations)


def _mesh_count_hint(mesh: ParsedMesh, attr: str) -> int:
    try:
        direct = int(getattr(mesh, attr, 0) or 0)
    except (TypeError, ValueError, OverflowError):
        direct = 0
    if direct > 0:
        return direct
    total = 0
    member = "faces" if attr == "total_faces" else "vertices"
    for submesh in getattr(mesh, "submeshes", ()) or ():
        try:
            total += len(getattr(submesh, member, ()) or ())
        except TypeError:
            continue
    return total


def _valid_source_indices(mesh: ParsedMesh, source_indices: Iterable[int] | None) -> tuple[int, ...]:
    if source_indices is None:
        return tuple(range(len(mesh.submeshes)))
    result: list[int] = []
    seen: set[int] = set()
    for raw_index in source_indices or ():
        index = _int_value(raw_index, -1)
        if index < 0 or index >= len(mesh.submeshes) or index in seen:
            continue
        seen.add(index)
        result.append(index)
    return tuple(result)


def _target_vertex_count(mesh: ParsedMesh, source_indices: Iterable[int]) -> int:
    total = 0
    submeshes = getattr(mesh, "submeshes", ()) or ()
    for submesh_index in source_indices:
        if not (0 <= submesh_index < len(submeshes)):
            continue
        try:
            total += len(getattr(submeshes[submesh_index], "vertices", ()) or ())
        except TypeError:
            continue
    return total


def _allow_python_selection_expansion_fallback(
    mesh: ParsedMesh,
    operation: str,
    source_indices: Iterable[int],
    *,
    selected_vertex_count: int = 0,
) -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return True
    try:
        from .mesh_native_core import native_mesh_core_available, record_native_mesh_core_fallback
    except ImportError:
        return True
    if not native_mesh_core_available():
        return True
    target_vertex_count = _target_vertex_count(mesh, source_indices)
    vertex_count = max(
        _mesh_count_hint(mesh, "total_vertices"),
        target_vertex_count,
        int(selected_vertex_count or 0),
    )
    face_count = _mesh_count_hint(mesh, "total_faces")
    record_native_mesh_core_fallback(
        f"{operation}.blocked",
        "Python selection expansion fallback blocked while native mesh core is available",
        vertex_count=vertex_count,
        face_count=face_count,
        target_vertex_count=target_vertex_count,
        selected_vertex_count=int(selected_vertex_count or 0),
    )
    return False


def grow_vertex_selection(
    mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]] | Iterable[int],
    *,
    steps: int = 1,
) -> dict[int, set[int]]:
    selection = _normalized_selection_by_submesh(mesh, selected_vertices_by_submesh)
    step_count = max(0, _int_value(steps, 0))
    native_selection = _native_vertex_selection(mesh, selection, operation="grow", iterations=step_count)
    if native_selection is not None:
        return native_selection
    if not _allow_python_selection_expansion_fallback(
        mesh,
        "selection.grow",
        selection.keys(),
        selected_vertex_count=sum(len(vertices) for vertices in selection.values()),
    ):
        return {}
    for _step in range(step_count):
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
    step_count = max(0, _int_value(steps, 0))
    native_selection = _native_vertex_selection(mesh, selection, operation="shrink", iterations=step_count)
    if native_selection is not None:
        return native_selection
    if not _allow_python_selection_expansion_fallback(
        mesh,
        "selection.shrink",
        selection.keys(),
        selected_vertex_count=sum(len(vertices) for vertices in selection.values()),
    ):
        return {}
    for _step in range(step_count):
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
    iteration_count = max(0, _int_value(iterations, 0))
    native_selection = _native_vertex_selection(mesh, selection, operation="smooth", iterations=iteration_count)
    if native_selection is not None:
        return native_selection
    if not _allow_python_selection_expansion_fallback(
        mesh,
        "selection.smooth",
        selection.keys(),
        selected_vertex_count=sum(len(vertices) for vertices in selection.values()),
    ):
        return {}
    for _iteration in range(iteration_count):
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


def invert_vertex_selection(
    mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]] | Iterable[int],
    *,
    source_indices: Iterable[int] | None = None,
) -> dict[int, set[int]]:
    selection = _normalized_selection_by_submesh(mesh, selected_vertices_by_submesh)
    target_sources = _valid_source_indices(mesh, source_indices)
    native_selection = None
    try:
        from .mesh_native_core import apply_native_mesh_selection
    except ImportError:
        native_selection = None
    else:
        native_selection = apply_native_mesh_selection(
            mesh,
            selection,
            source_indices=target_sources,
            operation="invert",
            iterations=1,
        )
    if native_selection is not None:
        return native_selection
    if not _allow_python_selection_expansion_fallback(
        mesh,
        "selection.invert",
        target_sources,
        selected_vertex_count=sum(len(vertices) for vertices in selection.values()),
    ):
        return {}
    inverted: dict[int, set[int]] = {}
    for submesh_index in target_sources:
        vertex_count = len(mesh.submeshes[submesh_index].vertices)
        vertices = set(range(vertex_count)) - selection.get(submesh_index, set())
        if vertices:
            inverted[submesh_index] = vertices
    return inverted


def select_all_vertex_selection(
    mesh: ParsedMesh,
    source_indices: Iterable[int],
) -> dict[int, set[int]]:
    target_sources = _valid_source_indices(mesh, source_indices)
    native_selection = None
    try:
        from .mesh_native_core import apply_native_mesh_selection
    except ImportError:
        native_selection = None
    else:
        native_selection = apply_native_mesh_selection(
            mesh,
            {},
            source_indices=target_sources,
            operation="all",
            iterations=0,
        )
    if native_selection is not None:
        return native_selection
    if not _allow_python_selection_expansion_fallback(mesh, "selection.select_all", target_sources):
        return {}
    selection: dict[int, set[int]] = {}
    for submesh_index in target_sources:
        vertex_count = len(mesh.submeshes[submesh_index].vertices)
        if vertex_count > 0:
            selection[submesh_index] = set(range(vertex_count))
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
            except (TypeError, ValueError, OverflowError):
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
            except (TypeError, ValueError, OverflowError):
                continue
            weight = max(0.0, min(1.0, _finite_float(raw_weight)))
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
    result: dict[int, tuple[float, bool]] = {}
    for raw_index, raw_weight in weights.items():
        try:
            index = int(raw_index)
        except (TypeError, ValueError, OverflowError):
            continue
        weight = _finite_float(raw_weight)
        if weight > 0.0:
            result[index] = (weight, False)
    if not mirror_x:
        return result
    pairs = dict(mirror_pairs or build_x_mirror_pairs(submesh.vertices))
    for index, (weight, _mirrored) in tuple(result.items()):
        mirror_index = pairs.get(index)
        if mirror_index is None:
            continue
        previous = result.get(mirror_index)
        if previous is None or weight > previous[0]:
            result[mirror_index] = (weight, True)
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
        except (TypeError, ValueError, OverflowError):
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
        current = _vec3(vertices[index])
        moved = _add(current, applied_delta)
        if not _same_vec3(current, moved):
            vertices[index] = moved
            changed.append(index)
    if not changed:
        return []
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
    iterations: int = 1,
    invert: bool = False,
    recompute_normals: bool = True,
) -> list[int]:
    if not submesh.vertices:
        return []
    tool_key = str(tool or "grab").strip().lower()
    center_vec = _vec3(center)
    radius_value = max(_finite_float(radius), 1e-8)
    strength_value = max(0.0, min(1.0, _finite_float(strength)))
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
    normals: list[Vec3] = []
    if tool_key == "inflate":
        normals = (
            [_vec3(normal, (0.0, 1.0, 0.0)) for normal in submesh.normals]
            if len(submesh.normals) == len(vertices)
            else _compute_smooth_normals(vertices, submesh.faces)
        )
    adjacency_map = list(adjacency or build_vertex_adjacency(submesh)) if tool_key == "smooth" else []
    iteration_count = max(1, min(12, _int_value(iterations, 1)))
    amount_value = _finite_float(amount)
    if abs(amount_value) <= 1e-8:
        amount_value = _length(delta_vec)
    amount_value *= strength_value
    new_vertices = list(vertices)

    if tool_key == "smooth":
        relax_vertices = list(vertices)
        for _iteration in range(iteration_count):
            next_vertices = list(relax_vertices)
            for index, (weight, _mirrored) in weighted_indices.items():
                neighbors = adjacency_map[index] if index < len(adjacency_map) else set()
                if not neighbors:
                    continue
                valid_neighbors = [neighbor for neighbor in neighbors if 0 <= int(neighbor) < len(relax_vertices)]
                if not valid_neighbors:
                    continue
                avg = (
                    sum(relax_vertices[neighbor][0] for neighbor in valid_neighbors) / len(valid_neighbors),
                    sum(relax_vertices[neighbor][1] for neighbor in valid_neighbors) / len(valid_neighbors),
                    sum(relax_vertices[neighbor][2] for neighbor in valid_neighbors) / len(valid_neighbors),
                )
                vertex = relax_vertices[index]
                blend = max(0.0, min(1.0, float(weight) * strength_value))
                next_vertices[index] = (
                    vertex[0] + (avg[0] - vertex[0]) * blend,
                    vertex[1] + (avg[1] - vertex[1]) * blend,
                    vertex[2] + (avg[2] - vertex[2]) * blend,
                )
            relax_vertices = next_vertices
        new_vertices = relax_vertices
    for index, (weight, mirrored) in weighted_indices.items():
        if tool_key == "smooth":
            continue
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
        else:
            new_vertices[index] = _add(vertex, _mul(applied_delta, float(weight) * strength_value))

    changed = sorted(index for index in weighted_indices if not _same_vec3(vertices[index], new_vertices[index]))
    if not changed:
        return []
    submesh.vertices = new_vertices
    submesh.vertex_count = len(new_vertices)
    if recompute_normals:
        recompute_submesh_normals(submesh)
    return changed
