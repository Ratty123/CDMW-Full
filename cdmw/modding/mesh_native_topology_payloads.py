from __future__ import annotations

from importlib import import_module
from pathlib import Path
import threading
from typing import Mapping

from cdmw.modding.mesh_native_binary_io import (
    _write_bone_binary_payloads,
    _write_edge_binary_payload,
    _write_f64_binary_payload,
    _write_face_binary_payload,
    _write_vec2_binary_payload,
    _write_vec3_binary_payload,
)
from cdmw.modding.mesh_native_core_constants import _TRANSIENT_NATIVE_SUBMESH_ATTRS
from cdmw.modding.mesh_native_core_payload_helpers import _finite_float, _index
from cdmw.modding.mesh_native_payloads import (
    _is_identity_i32_sequence,
    _put_i32_range_or_binary_payload,
    _put_source_face_indices_json_payload,
    _put_source_face_indices_payload,
    _put_source_vertex_map_payload,
    _put_source_vertex_offsets_payload,
)
from cdmw.modding.mesh_deformer import _EXTRA_SUBMESH_ATTRS
from cdmw.modding.mesh_parser import ParsedMesh


def _facade_attr(name: str):
    return getattr(import_module("cdmw.modding.mesh_native_core"), name)


def _ensure_native_mesh_session_submesh(*args, **kwargs):
    return _facade_attr("_ensure_native_mesh_session_submesh")(*args, **kwargs)


def _face_json_with_source_indices(*args, **kwargs):
    return _facade_attr("_face_json_with_source_indices")(*args, **kwargs)


def _native_i32_descriptor(value: object):
    return _facade_attr("_native_i32_descriptor")(value)


def _native_preview_delta_output_path(suffix: str = ".bin") -> str:
    return _facade_attr("_native_preview_delta_output_path")(suffix)


def _snapshot_metadata_value(value: object):
    return _facade_attr("_snapshot_metadata_value")(value)


def _vec2_json(value: object):
    return _facade_attr("_vec2_json")(value)


def _vec3_json(value: object):
    return _facade_attr("_vec3_json")(value)


def _put_topology_output_paths(item: dict[str, object], submesh: object, preserve_normals: bool) -> None:
    item.update(
        name=str(getattr(submesh, "name", "") or ""),
        material=str(getattr(submesh, "material", "") or ""),
        texture=str(getattr(submesh, "texture", "") or ""),
    )
    extra_attrs = {
        name: _snapshot_metadata_value(getattr(submesh, name))
        for name in _EXTRA_SUBMESH_ATTRS
        if name not in _TRANSIENT_NATIVE_SUBMESH_ATTRS and hasattr(submesh, name)
    }
    if extra_attrs:
        item["extra_attrs"] = extra_attrs
    item["changed_vertices_output_path"] = _native_preview_delta_output_path("_topology_changed_vertices.bin")
    item["vertices_output_path"] = _native_preview_delta_output_path("_topology_vertices.bin")
    item["faces_output_path"] = _native_preview_delta_output_path("_topology_faces.bin")
    aligned_outputs = (
        ("normals", "_topology_normals.bin", preserve_normals),
        ("uvs", "_topology_uvs.bin", True),
        ("tangents", "_topology_tangents.bin", True),
        ("tangent_signs", "_topology_tangent_signs.bin", True),
        ("source_vertex_map", "_topology_source_vertex_map.bin", True),
        ("source_vertex_offsets", "_topology_source_vertex_offsets.bin", True),
    )
    vertex_count = len(getattr(submesh, "vertices", ()) or ())
    for attr, suffix, enabled in aligned_outputs:
        if enabled and len(getattr(submesh, attr, ()) or ()) == vertex_count:
            item[f"{attr}_output_path"] = _native_preview_delta_output_path(suffix)
    if len(getattr(submesh, "bone_indices", ()) or ()) == vertex_count and len(getattr(submesh, "bone_weights", ()) or ()) == vertex_count:
        for name in ("counts", "indices", "weights"):
            item[f"bone_{name}_output_path"] = _native_preview_delta_output_path(f"_topology_bone_{name}.bin")
    item["preview_triangle_output_path"] = _native_preview_delta_output_path("_triangles.bin")
    item["suppress_vertex_remap_report"] = True


def _put_topology_aligned_input_payloads(
    item: dict[str, object],
    submesh: object,
    prefix: Path,
    preserve_normals: bool,
) -> None:
    vertex_count = len(getattr(submesh, "vertices", ()) or ())
    if preserve_normals and len(getattr(submesh, "normals", ()) or ()) == vertex_count:
        item["normals_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_normals.bin"), submesh.normals, fallback=0.0)
    if len(getattr(submesh, "uvs", ()) or ()) == vertex_count:
        item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), submesh.uvs)
    if len(getattr(submesh, "tangents", ()) or ()) == vertex_count:
        item["tangents_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_tangents.bin"), getattr(submesh, "tangents", ()) or (), fallback=0.0)
    if len(getattr(submesh, "tangent_signs", ()) or ()) == vertex_count:
        item["tangent_signs_binary"] = _write_f64_binary_payload(prefix.with_name(prefix.name + "_tangent_signs.bin"), getattr(submesh, "tangent_signs", ()) or ())
    if len(getattr(submesh, "bone_indices", ()) or ()) == vertex_count and len(getattr(submesh, "bone_weights", ()) or ()) == vertex_count:
        bones = _write_bone_binary_payloads(prefix, getattr(submesh, "bone_indices", ()) or (), getattr(submesh, "bone_weights", ()) or ())
        if bones is not None:
            item.update(bones)
    if len(getattr(submesh, "source_vertex_map", ()) or ()) == vertex_count:
        _put_source_vertex_map_payload(item, prefix, getattr(submesh, "source_vertex_map", ()) or ())
    if len(getattr(submesh, "source_vertex_offsets", ()) or ()) == vertex_count:
        _put_source_vertex_offsets_payload(item, prefix, getattr(submesh, "source_vertex_offsets", ()) or ())


def _put_topology_json_input_payloads(item: dict[str, object], submesh: object, preserve_normals: bool) -> None:
    vertex_count = len(getattr(submesh, "vertices", ()) or ())
    item["vertices"] = [_vec3_json(vertex) for vertex in submesh.vertices]
    if preserve_normals and len(getattr(submesh, "normals", ()) or ()) == vertex_count:
        item["normals"] = [_vec3_json(normal) for normal in submesh.normals]
    if len(getattr(submesh, "uvs", ()) or ()) == vertex_count:
        item["uvs"] = [_vec2_json(uv) for uv in submesh.uvs]
    if len(getattr(submesh, "tangents", ()) or ()) == vertex_count:
        item["tangents"] = [_vec3_json(value) for value in tuple(getattr(submesh, "tangents", ()) or ())]
    if len(getattr(submesh, "tangent_signs", ()) or ()) == vertex_count:
        item["tangent_signs"] = [_finite_float(value, 1.0) for value in tuple(getattr(submesh, "tangent_signs", ()) or ())]
    if len(getattr(submesh, "source_vertex_map", ()) or ()) == vertex_count:
        item["source_vertex_map"] = [int(value) for value in tuple(getattr(submesh, "source_vertex_map", ()) or ())]
    if len(getattr(submesh, "source_vertex_offsets", ()) or ()) == vertex_count:
        _put_source_vertex_offsets_payload(item, None, getattr(submesh, "source_vertex_offsets", ()) or ())


def _put_topology_geometry(
    item: dict[str, object],
    mesh: ParsedMesh,
    submesh_index: int,
    *,
    binary: Path | None,
    sidecar_root: Path | None,
    preserve_normals: bool,
    edge_selected: bool,
    vertex_selected: bool,
    allow_empty_faces_for_selected_vertices: bool,
    stop_event: threading.Event | None,
    timeout_seconds: float,
) -> tuple[list[int] | None, int] | None:
    submesh = mesh.submeshes[submesh_index]
    vertex_count = len(submesh.vertices)
    face_count = len(submesh.faces or ())
    session_id = _ensure_native_mesh_session_submesh(binary, mesh, submesh_index, stop_event=stop_event, timeout_seconds=timeout_seconds) if binary is not None else None
    if session_id:
        item["session_id"] = session_id
        return None, face_count
    faces, source_face_indices = _face_json_with_source_indices(submesh.faces, vertex_count)
    if not faces and not edge_selected and not (allow_empty_faces_for_selected_vertices and vertex_selected):
        return None
    face_count = len(faces)
    if sidecar_root is not None:
        prefix = sidecar_root / f"topology_{submesh_index}"
        item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices)
        item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
        if not _is_identity_i32_sequence(source_face_indices):
            _put_source_face_indices_payload(item, prefix, source_face_indices)
        _put_topology_aligned_input_payloads(item, submesh, prefix, preserve_normals)
    else:
        _put_topology_json_input_payloads(item, submesh, preserve_normals)
        item["faces"] = faces
        if not _is_identity_i32_sequence(source_face_indices):
            _put_source_face_indices_json_payload(item, source_face_indices)
    return source_face_indices, face_count


def _put_topology_selection(
    item: dict[str, object],
    submesh: object,
    submesh_index: int,
    face_count: int,
    source_face_indices: list[int] | None,
    selected_faces_by_submesh: Mapping[int, set[int]],
    selected_vertices_by_submesh: Mapping[int, set[int]],
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]],
    all_faces_by_submesh: set[int],
    selected_vertices_binary_by_submesh: Mapping[object, object],
    sidecar_root: Path | None,
) -> bool:
    vertex_count = len(getattr(submesh, "vertices", ()) or ())
    raw_selected_faces = selected_faces_by_submesh.get(submesh_index, set())
    if raw_selected_faces:
        if source_face_indices is None:
            _, source_face_indices = _face_json_with_source_indices(submesh.faces, vertex_count)
        if not _is_identity_i32_sequence(source_face_indices):
            offsets = {source: offset for offset, source in enumerate(source_face_indices)}
            selected_faces = sorted(offsets[index] for index in raw_selected_faces if index in offsets)
        else:
            selected_faces = sorted(index for index in raw_selected_faces if 0 <= index < face_count)
    else:
        selected_faces = []
    selected_vertices = sorted(index for index in selected_vertices_by_submesh.get(submesh_index, set()) if 0 <= index < vertex_count)
    raw_binary = selected_vertices_binary_by_submesh.get(submesh_index, selected_vertices_binary_by_submesh.get(str(submesh_index)))
    selected_vertices_binary = _native_i32_descriptor(raw_binary)
    if selected_vertices_binary is not None:
        try:
            selected_vertex_count = int(selected_vertices_binary.get("count", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            selected_vertices_binary = None
        else:
            if selected_vertex_count <= 0 or selected_vertex_count > vertex_count:
                selected_vertices_binary = None
    selected_edges = sorted({(min(int(left), int(right)), max(int(left), int(right))) for left, right in selected_edges_by_submesh.get(submesh_index, set()) if 0 <= int(left) < vertex_count and 0 <= int(right) < vertex_count and int(left) != int(right)})
    selected_all_faces = submesh_index in all_faces_by_submesh
    if sidecar_root is not None:
        prefix = sidecar_root / f"topology_{submesh_index}"
        if selected_faces:
            _put_i32_range_or_binary_payload(item, values=selected_faces, start_key="selected_face_start", count_key="selected_face_count", binary_key="selected_faces_binary", binary_path=prefix.with_name(prefix.name + "_selected_faces.bin"), max_count=face_count)
        if selected_vertices_binary is not None:
            item["selected_vertices_binary"] = selected_vertices_binary
        elif selected_vertices:
            _put_i32_range_or_binary_payload(item, values=selected_vertices, start_key="selected_vertex_start", count_key="selected_vertex_count", binary_key="selected_vertices_binary", binary_path=prefix.with_name(prefix.name + "_selected_vertices.bin"), max_count=vertex_count)
        if selected_edges:
            item["selected_edges_binary"] = _write_edge_binary_payload(prefix.with_name(prefix.name + "_selected_edges.bin"), selected_edges)
    if selected_all_faces:
        item["selected_all_faces"] = True
    if selected_faces and "selected_faces_binary" not in item and "selected_face_start" not in item:
        item["selected_faces"] = selected_faces
    if selected_edges and "selected_edges_binary" not in item:
        item["selected_edges"] = [[left, right] for left, right in selected_edges]
    if selected_vertices and "selected_vertices_binary" not in item and "selected_vertex_start" not in item:
        item["selected_vertices"] = selected_vertices
    return bool(selected_faces or selected_edges or selected_vertices or selected_vertices_binary is not None or selected_all_faces)


def _topology_edit_submeshes(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    selected_vertices_by_submesh: Mapping[int, set[int]],
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    all_faces_by_submesh: set[int] | None = None,
    *,
    binary: Path | None = None,
    sidecar_root: Path | None = None,
    preserve_normals: bool = False,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
    selected_vertices_binary_by_submesh: Mapping[object, object] | None = None,
    allow_empty_faces_for_selected_vertices: bool = False,
) -> list[dict[str, object]]:
    selected_edges_by_submesh = selected_edges_by_submesh or {}
    all_faces_by_submesh = all_faces_by_submesh or set()
    selected_vertices_binary_by_submesh = selected_vertices_binary_by_submesh or {}
    target_indices = set(selected_faces_by_submesh) | set(selected_vertices_by_submesh) | set(selected_edges_by_submesh) | set(all_faces_by_submesh)
    target_indices.update(index for raw in selected_vertices_binary_by_submesh if (index := _index(raw)) is not None)
    payloads: list[dict[str, object]] = []
    for submesh_index in sorted(target_indices):
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        vertex_count = len(submesh.vertices)
        face_count = len(submesh.faces or ())
        edge_selected = bool(selected_edges_by_submesh.get(submesh_index))
        vertex_selected = bool(selected_vertices_by_submesh.get(submesh_index))
        if vertex_count <= 0 or (face_count <= 0 and not edge_selected and not (allow_empty_faces_for_selected_vertices and vertex_selected)):
            continue
        item: dict[str, object] = {"index": submesh_index}
        _put_topology_output_paths(item, submesh, preserve_normals)
        geometry = _put_topology_geometry(
            item, mesh, submesh_index, binary=binary, sidecar_root=sidecar_root,
            preserve_normals=preserve_normals, edge_selected=edge_selected, vertex_selected=vertex_selected,
            allow_empty_faces_for_selected_vertices=allow_empty_faces_for_selected_vertices,
            stop_event=stop_event, timeout_seconds=timeout_seconds,
        )
        if geometry is None:
            continue
        source_face_indices, face_count = geometry
        if _put_topology_selection(
            item, submesh, submesh_index, face_count, source_face_indices,
            selected_faces_by_submesh, selected_vertices_by_submesh, selected_edges_by_submesh,
            all_faces_by_submesh, selected_vertices_binary_by_submesh, sidecar_root,
        ):
            payloads.append(item)
    return payloads
