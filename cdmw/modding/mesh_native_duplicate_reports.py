from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Callable, Mapping

from cdmw.modding.mesh_native_binary_io import (
    _read_bone_binary_report_payloads,
    _read_f64_binary_report_payload,
    _read_face_binary_report_payload,
    _read_vec2_binary_report_payload,
    _read_vec3_binary_report_payload,
)
from cdmw.modding.mesh_native_core_constants import Vec2, Vec3
from cdmw.modding.mesh_native_core_payload_helpers import _finite_float, _index
from cdmw.modding.mesh_native_payloads import _source_vertex_map_report_values, _source_vertex_offsets_report_values
from cdmw.modding.mesh_native_preview_payloads import _native_preview_triangle_group
from cdmw.modding.mesh_deformer import _EXTRA_SUBMESH_ATTRS
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh


def _facade_attr(name: str):
    return getattr(import_module("cdmw.modding.mesh_native_core"), name)


def _face_json(value: object, vertex_count: int):
    return _facade_attr("_face_json")(value, vertex_count)


def _snapshot_metadata_value(value: object):
    return _facade_attr("_snapshot_metadata_value")(value)


def _vec2(value: object) -> Vec2:
    return _facade_attr("_vec2")(value)


def _vec3(value: object, fallback: float = 0.0) -> Vec3:
    return _facade_attr("_vec3")(value, fallback=fallback)


def recompute_submesh_normals(submesh: object) -> None:
    _facade_attr("recompute_submesh_normals")(submesh)


@dataclass
class _DuplicateChannels:
    normals: list[Vec3]
    uvs: list[Vec2]
    tangents: list[Vec3]
    tangent_signs: list[float]
    bone_indices: list[tuple[int, ...]]
    bone_weights: list[tuple[float, ...]]
    source_vertex_map: list[int]
    source_vertex_offsets: list[int]


def _read_duplicate_geometry(item: Mapping[str, object]) -> tuple[list[Vec3], list[tuple[int, int, int]]] | None:
    raw_vertices_binary = item.get("vertices_binary")
    raw_vertices = item.get("vertices")
    if isinstance(raw_vertices_binary, Mapping):
        vertex_count = _index(raw_vertices_binary.get("count"))
        if vertex_count is None or vertex_count < 0:
            return None
        vertices = _read_vec3_binary_report_payload(raw_vertices_binary, expected_count=vertex_count)
        if vertices is None:
            return None
    elif isinstance(raw_vertices, list):
        vertices = [_vec3(value) for value in raw_vertices]
        vertex_count = len(vertices)
    else:
        return None
    raw_faces_binary = item.get("faces_binary")
    raw_faces = item.get("faces")
    if isinstance(raw_faces_binary, Mapping):
        face_count = _index(raw_faces_binary.get("count"))
        if face_count is None or face_count < 0:
            return None
        faces = _read_face_binary_report_payload(raw_faces_binary, expected_count=face_count, vertex_count=vertex_count)
        if faces is None:
            return None
    elif isinstance(raw_faces, list):
        faces = _face_json(raw_faces, vertex_count)
        if len(faces) != len(raw_faces):
            return None
    else:
        return None
    return vertices, [tuple(face) for face in faces]


def _read_optional_channel(
    item: Mapping[str, object],
    name: str,
    vertex_count: int,
    reader: Callable[..., object],
    converter: Callable[[object], object],
) -> list[object] | None:
    binary = item.get(f"{name}_binary")
    raw = item.get(name)
    if isinstance(binary, Mapping):
        value = reader(binary, expected_count=vertex_count)
        return list(value) if value is not None and len(value) == vertex_count else None
    if isinstance(raw, list):
        return [converter(value) for value in raw] if len(raw) == vertex_count else None
    return []


def _read_duplicate_channels(item: Mapping[str, object], vertex_count: int) -> _DuplicateChannels | None:
    normals = _read_optional_channel(item, "normals", vertex_count, _read_vec3_binary_report_payload, _vec3)
    uvs = _read_optional_channel(item, "uvs", vertex_count, _read_vec2_binary_report_payload, _vec2)
    tangents = _read_optional_channel(item, "tangents", vertex_count, _read_vec3_binary_report_payload, _vec3)
    tangent_signs = _read_optional_channel(
        item, "tangent_signs", vertex_count, _read_f64_binary_report_payload,
        lambda value: _finite_float(value, 1.0),
    )
    if any(value is None for value in (normals, uvs, tangents, tangent_signs)):
        return None
    bone_indices: list[tuple[int, ...]] = []
    bone_weights: list[tuple[float, ...]] = []
    bone_descriptors = tuple(item.get(key) for key in ("bone_counts_binary", "bone_indices_binary", "bone_weights_binary"))
    if all(isinstance(value, Mapping) for value in bone_descriptors):
        bones = _read_bone_binary_report_payloads(*bone_descriptors, expected_count=vertex_count)
        if bones is None:
            return None
        bone_indices, bone_weights = bones
    source_vertex_map = _source_vertex_map_report_values(item, vertex_count)
    source_vertex_offsets = _source_vertex_offsets_report_values(item, vertex_count)
    if source_vertex_map is None or source_vertex_offsets is None:
        return None
    return _DuplicateChannels(normals, uvs, tangents, tangent_signs, bone_indices, bone_weights, source_vertex_map, source_vertex_offsets)


def _build_duplicate_submesh(
    source: SubMesh,
    item: Mapping[str, object],
    *,
    source_index: int,
    copy_extra_attrs: bool,
    reset_source_descriptors: bool,
    recompute_normals: bool,
) -> SubMesh | None:
    geometry = _read_duplicate_geometry(item)
    if geometry is None:
        return None
    vertices, faces = geometry
    channels = _read_duplicate_channels(item, len(vertices))
    if channels is None:
        return None
    suffix = str(item.get("name_suffix") or " duplicate")
    kwargs: dict[str, object] = {
        "name": str(item.get("name")) if "name" in item else f"{source.name or 'part'}{suffix}",
        "material": str(item.get("material")) if "material" in item else str(source.material or ""),
        "texture": str(item.get("texture")) if "texture" in item else str(source.texture or ""),
        "vertices": vertices, "uvs": channels.uvs, "normals": channels.normals,
        "tangents": channels.tangents, "faces": faces,
        "bone_indices": channels.bone_indices, "bone_weights": channels.bone_weights,
        "source_vertex_map": channels.source_vertex_map, "source_vertex_offsets": channels.source_vertex_offsets,
        "source_vertex_stride": int(source.source_vertex_stride or 0),
        "source_lod_count": int(source.source_lod_count or 0),
    }
    if reset_source_descriptors:
        kwargs.update(source_index_offset=-1, source_index_count=0, source_descriptor_offset=-1,
                      source_bbox_min=_vec3(getattr(source, "source_bbox_min", (0.0, 0.0, 0.0)), fallback=0.0),
                      source_bbox_extent=_vec3(getattr(source, "source_bbox_extent", (0.0, 0.0, 0.0)), fallback=0.0))
    result = SubMesh(**kwargs)
    result.vertex_count, result.face_count = len(result.vertices), len(result.faces)
    setattr(result, "cdmw_mesh_edit_topology_source_submesh_index", source_index)
    raw_extra_attrs = item.get("extra_attrs")
    if isinstance(raw_extra_attrs, Mapping):
        for raw_name, value in raw_extra_attrs.items():
            name = str(raw_name or "").strip()
            if name in _EXTRA_SUBMESH_ATTRS:
                setattr(result, name, _snapshot_metadata_value(value))
    elif copy_extra_attrs:
        for name in _EXTRA_SUBMESH_ATTRS:
            if hasattr(source, name):
                setattr(result, name, _snapshot_metadata_value(getattr(source, name)))
    if channels.tangent_signs:
        setattr(result, "tangent_signs", channels.tangent_signs)
    if recompute_normals and not result.normals:
        recompute_submesh_normals(result)
    return result


def _append_native_duplicate_report_submeshes(
    mesh: ParsedMesh,
    report: Mapping[str, object],
    *,
    recompute_normals: bool,
    copy_extra_attrs: bool = False,
    reset_source_descriptors: bool = False,
) -> dict[int, int] | None:
    items = report.get("submeshes")
    if not isinstance(items, list):
        return None
    appended: dict[int, int] = {}
    for item in items:
        if not isinstance(item, Mapping) or not bool(item.get("append_submesh")):
            continue
        source_index = _index(item.get("source_index", item.get("index")))
        if source_index is None or not 0 <= source_index < len(mesh.submeshes):
            return None
        new_submesh = _build_duplicate_submesh(
            mesh.submeshes[source_index], item, source_index=source_index,
            copy_extra_attrs=copy_extra_attrs, reset_source_descriptors=reset_source_descriptors,
            recompute_normals=recompute_normals,
        )
        if new_submesh is None:
            return None
        mesh.submeshes.append(new_submesh)
        new_index = len(mesh.submeshes) - 1
        preview_group = _native_preview_triangle_group(item.get("preview_triangle_group"), new_index)
        if preview_group is not None:
            setattr(new_submesh, "cdmw_native_preview_triangle_group", preview_group)
        appended[new_index] = source_index
    return appended
