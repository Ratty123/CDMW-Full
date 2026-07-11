from __future__ import annotations

from dataclasses import dataclass

from importlib import import_module
from typing import Mapping, Sequence

from cdmw.modding.mesh_native_binary_io import (
    _read_bone_binary_report_payloads,
    _read_f64_binary_report_payload,
    _read_face_binary_report_payload,
    _read_vec2_binary_report_payload,
    _read_vec3_binary_report_payload,
)
from cdmw.modding.mesh_native_core_blend_helpers import _clear_vertex_aligned_topology_result
from cdmw.modding.mesh_native_core_constants import NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR, Vec2, Vec3
from cdmw.modding.mesh_native_core_payload_helpers import _finite_float, _index
from cdmw.modding.mesh_native_history import (
    _bounded_changed_vertices,
    _changed_vertices_for_report,
    _changed_vertices_from_report_item,
    _native_history_vertex_delta,
)
from cdmw.modding.mesh_native_payloads import _source_vertex_map_report_values, _source_vertex_offsets_report_values
from cdmw.modding.mesh_native_preview_payloads import (
    _copy_vertex_indices_from_report_item,
    _native_preview_triangle_group,
    _native_preview_vertex_update_group,
    _vertex_blends_from_report_item,
)
from cdmw.modding.mesh_parser import ParsedMesh


def _facade_attr(name: str):
    return getattr(import_module("cdmw.modding.mesh_native_core"), name)


def _apply_vertex_aligned_topology_result(*args, **kwargs):
    return _facade_attr("_apply_vertex_aligned_topology_result")(*args, **kwargs)


def _face_json(value: object, vertex_count: int):
    return _facade_attr("_face_json")(value, vertex_count)


def _vec2(value: object) -> Vec2:
    return _facade_attr("_vec2")(value)


def _vec3(value: object) -> Vec3:
    return _facade_attr("_vec3")(value)


@dataclass
class _MeshEditVertexState:
    vertices: list[Vec3]
    changed: Sequence[int] | set[int]
    non_topology_uvs: list[Vec2] | None
    sparse_positions: bool


@dataclass
class _TopologyChannels:
    normals: list[Vec3] | None
    uvs: list[Vec2] | None
    tangents: list[Vec3] | None
    tangent_signs: list[float] | None
    bones: tuple[list[tuple[int, ...]], list[tuple[float, ...]]] | None
    source_vertex_map: list[int]
    source_vertex_offsets: list[int]
    copy_indices: list[int]
    vertex_blends: dict[int, tuple[int, int, float]]


def _decode_mesh_edit_vertices(
    submesh: object,
    item: Mapping[str, object],
    topology_changed: bool,
    changed_ordered: Sequence[int],
) -> _MeshEditVertexState | None:
    raw_vertices = item.get("vertices")
    raw_vertices_binary = item.get("vertices_binary")
    changed: Sequence[int] | set[int] = _changed_vertices_for_report(changed_ordered)
    sparse_positions = False
    if isinstance(raw_vertices, list):
        vertices = [_vec3(value) for value in raw_vertices]
    elif isinstance(raw_vertices_binary, Mapping):
        vertex_count = _index(raw_vertices_binary.get("count"))
        if vertex_count is None or vertex_count < 0:
            return None
        vertices = _read_vec3_binary_report_payload(raw_vertices_binary, expected_count=vertex_count)
        if vertices is None:
            return None
    elif topology_changed:
        return None
    else:
        raw_changed_positions = item.get("changed_positions")
        raw_changed_positions_binary = item.get("changed_positions_binary")
        if raw_changed_positions_binary is not None:
            raw_changed_positions = _read_vec3_binary_report_payload(
                raw_changed_positions_binary,
                expected_count=len(changed_ordered),
            )
        if not isinstance(raw_changed_positions, list) or len(raw_changed_positions) != len(changed_ordered):
            return None
        vertices = list(getattr(submesh, "vertices", ()) or ())
        changed_here: Sequence[int] | set[int] = changed_ordered if isinstance(changed_ordered, range) else set()
        changed_count = 0
        for index, raw_position in zip(changed_ordered, raw_changed_positions):
            vertices[index] = _vec3(raw_position)
            changed_count += 1
            if not isinstance(changed_here, range):
                changed_here.add(index)
        changed = changed_here if changed_count == len(changed_ordered) else set()
        sparse_positions = True

    non_topology_uvs = None
    if not topology_changed:
        raw_uvs_binary = item.get("uvs_binary")
        raw_uvs = item.get("uvs")
        if isinstance(raw_uvs_binary, Mapping):
            if _index(raw_uvs_binary.get("count")) != 0:
                non_topology_uvs = _read_vec2_binary_report_payload(raw_uvs_binary, expected_count=len(vertices))
                if non_topology_uvs is None:
                    return None
        elif isinstance(raw_uvs, list):
            if len(raw_uvs) != len(vertices):
                return None
            non_topology_uvs = [_vec2(uv) for uv in raw_uvs]
    return _MeshEditVertexState(vertices, changed, non_topology_uvs, sparse_positions)


def _read_topology_channels(item: Mapping[str, object], vertex_count: int) -> _TopologyChannels | None:
    def vec3_channel(name: str) -> list[Vec3] | None | bool:
        binary = item.get(f"{name}_binary")
        raw = item.get(name)
        if isinstance(binary, Mapping):
            value = _read_vec3_binary_report_payload(binary, expected_count=vertex_count)
            return value if value is not None else False
        if isinstance(raw, list):
            return [_vec3(value) for value in raw] if len(raw) == vertex_count else False
        return None

    normals = vec3_channel("normals")
    tangents = vec3_channel("tangents")
    if normals is False or tangents is False:
        return None
    raw_uvs_binary = item.get("uvs_binary")
    raw_uvs = item.get("uvs")
    if isinstance(raw_uvs_binary, Mapping):
        uvs = _read_vec2_binary_report_payload(raw_uvs_binary, expected_count=vertex_count)
        if uvs is None:
            return None
    elif isinstance(raw_uvs, list):
        if len(raw_uvs) != vertex_count:
            return None
        uvs = [_vec2(uv) for uv in raw_uvs]
    else:
        uvs = None
    raw_signs_binary = item.get("tangent_signs_binary")
    raw_signs = item.get("tangent_signs")
    if isinstance(raw_signs_binary, Mapping):
        signs = _read_f64_binary_report_payload(raw_signs_binary, expected_count=vertex_count)
        if signs is None:
            return None
    elif isinstance(raw_signs, list):
        if len(raw_signs) != vertex_count:
            return None
        signs = [_finite_float(value, 1.0) for value in raw_signs]
    else:
        signs = None
    bones = None
    bone_descriptors = tuple(item.get(key) for key in ("bone_counts_binary", "bone_indices_binary", "bone_weights_binary"))
    if all(isinstance(value, Mapping) for value in bone_descriptors):
        bones = _read_bone_binary_report_payloads(*bone_descriptors, expected_count=vertex_count)
        if bones is None:
            return None
    source_vertex_map = _source_vertex_map_report_values(item, vertex_count)
    source_vertex_offsets = _source_vertex_offsets_report_values(item, vertex_count)
    copy_indices = _copy_vertex_indices_from_report_item(item, vertex_count)
    vertex_blends = _vertex_blends_from_report_item(item)
    if source_vertex_map is None or source_vertex_offsets is None or copy_indices is None or vertex_blends is None:
        return None
    if copy_indices and len(copy_indices) != vertex_count:
        return None
    return _TopologyChannels(normals, uvs, tangents, signs, bones, source_vertex_map, source_vertex_offsets, copy_indices, vertex_blends)


def _apply_topology_result(
    submesh: object,
    item: Mapping[str, object],
    vertices: list[Vec3],
    old_vertex_count: int,
    skip_topology_normals: bool,
) -> bool:
    channels = _read_topology_channels(item, len(vertices))
    if channels is None:
        return False
    has_source_map = bool(channels.source_vertex_map)
    has_source_offsets = bool(channels.source_vertex_offsets)
    if channels.copy_indices:
        _apply_vertex_aligned_topology_result(
            submesh,
            channels.copy_indices,
            channels.vertex_blends,
            old_vertex_count,
            skip_normals=skip_topology_normals or channels.normals is not None,
            skip_uvs=channels.uvs is not None,
            skip_tangents=channels.tangents is not None,
            skip_tangent_signs=channels.tangent_signs is not None,
            skip_bones=channels.bones is not None,
            skip_source_vertex_map=has_source_map,
            skip_source_vertex_offsets=has_source_offsets,
        )
    elif not vertices:
        _clear_vertex_aligned_topology_result(submesh)
    for attr, value in (("normals", channels.normals), ("uvs", channels.uvs), ("tangents", channels.tangents)):
        if value is not None:
            setattr(submesh, attr, value)
    if channels.tangent_signs is not None:
        setattr(submesh, "tangent_signs", channels.tangent_signs)
    if channels.bones is not None:
        submesh.bone_indices, submesh.bone_weights = channels.bones
    if has_source_map:
        submesh.source_vertex_map = channels.source_vertex_map
    if has_source_offsets:
        submesh.source_vertex_offsets = channels.source_vertex_offsets
    raw_faces = item.get("faces")
    raw_faces_binary = item.get("faces_binary")
    if isinstance(raw_faces, list):
        faces = _face_json(raw_faces, len(vertices))
        if len(faces) != len(raw_faces):
            return False
    elif isinstance(raw_faces_binary, Mapping):
        face_count = _index(raw_faces_binary.get("count"))
        if face_count is None or face_count < 0:
            return False
        faces = _read_face_binary_report_payload(raw_faces_binary, expected_count=face_count, vertex_count=len(vertices))
        if faces is None:
            return False
    else:
        return False
    submesh.faces = [tuple(face) for face in faces]
    submesh.face_count = len(submesh.faces)
    return True


def _update_native_edit_metadata(
    submesh: object,
    item: Mapping[str, object],
    submesh_index: int,
    history_delta: object,
) -> None:
    for attr, parser, key in (
        ("cdmw_native_preview_triangle_group", _native_preview_triangle_group, "preview_triangle_group"),
        ("cdmw_native_preview_vertex_update_group", _native_preview_vertex_update_group, "preview_vertex_update_group"),
    ):
        value = parser(item.get(key), submesh_index)
        if value is not None:
            setattr(submesh, attr, value)
        elif hasattr(submesh, attr):
            delattr(submesh, attr)
    if history_delta is not None:
        setattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR, history_delta)
    elif hasattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR):
        delattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR)


def _apply_mesh_edit_report_item(
    mesh: ParsedMesh,
    item: Mapping[str, object],
    submesh_index: int,
    skip_topology_normals: bool,
) -> tuple[bool, Sequence[int] | set[int]] | None:
    submesh = mesh.submeshes[submesh_index]
    old_vertex_count = len(submesh.vertices)
    topology_changed = bool(item.get("topology_changed"))
    changed_ordered = _changed_vertices_from_report_item(item, (1 << 30) if topology_changed else old_vertex_count)
    if changed_ordered is None:
        changed_ordered = []
    history_delta = None if topology_changed else _native_history_vertex_delta(item, submesh_index, changed_ordered)
    if item.get("before_positions_binary") is not None and history_delta is None:
        return None
    state = _decode_mesh_edit_vertices(submesh, item, topology_changed, changed_ordered)
    if state is None:
        return None
    if topology_changed:
        if not _apply_topology_result(submesh, item, state.vertices, old_vertex_count, skip_topology_normals):
            return None
    elif len(state.vertices) != old_vertex_count:
        return None
    if state.sparse_positions:
        if state.changed:
            submesh.vertices = state.vertices
            submesh.vertex_count = len(state.vertices)
    elif item.get("vertices") is not None or item.get("vertices_binary") is not None:
        submesh.vertices = state.vertices
        submesh.vertex_count = len(state.vertices)
    if state.non_topology_uvs is not None:
        submesh.uvs = state.non_topology_uvs
    if topology_changed:
        submesh.vertices = state.vertices
        submesh.vertex_count = len(state.vertices)
    changed = _bounded_changed_vertices(state.changed, len(state.vertices))
    _update_native_edit_metadata(submesh, item, submesh_index, history_delta)
    return topology_changed, changed


def _apply_mesh_edit_report(
    mesh: ParsedMesh,
    report: Mapping[str, object],
    *,
    skip_topology_normals: bool = False,
) -> tuple[set[int], dict[int, Sequence[int] | set[int]]] | None:
    affected: set[int] = set()
    changed_vertices_by_submesh: dict[int, Sequence[int] | set[int]] = {}
    submesh_reports = report.get("submeshes")
    if not isinstance(submesh_reports, list):
        return None
    for item in submesh_reports:
        if not isinstance(item, dict):
            continue
        submesh_index = _index(item.get("index"))
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        result = _apply_mesh_edit_report_item(mesh, item, submesh_index, skip_topology_normals)
        if result is None:
            return None
        topology_changed, changed = result
        if topology_changed or changed:
            affected.add(submesh_index)
        if changed:
            changed_vertices_by_submesh[submesh_index] = changed
    return affected, changed_vertices_by_submesh
