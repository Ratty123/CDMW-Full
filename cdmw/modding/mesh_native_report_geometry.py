from __future__ import annotations

from importlib import import_module
from typing import Mapping, Sequence

from cdmw.modding.mesh_native_binary_io import (
    _read_bone_binary_report_payloads,
    _read_f64_binary_report_payload,
    _read_face_binary_report_payload,
    _read_i32_binary_report_payload,
    _read_vec2_binary_report_payload,
    _read_vec3_binary_report_payload,
)
from cdmw.modding.mesh_native_core_payload_helpers import _copy_vertex_aligned_list, _index
from cdmw.modding.mesh_native_history import _changed_vertices_for_report, _changed_vertices_from_report_item
from cdmw.modding.mesh_native_report_application import _merge_changed_vertices
from cdmw.modding.mesh_parser import ParsedMesh


def _facade_attr(name: str):
    return getattr(import_module("cdmw.modding.mesh_native_core"), name)


def _face_json(value: object, vertex_count: int):
    return _facade_attr("_face_json")(value, vertex_count)


def _remap_vertex_aligned_list(*args, **kwargs):
    return _facade_attr("_remap_vertex_aligned_list")(*args, **kwargs)


def _vec2(value: object):
    return _facade_attr("_vec2")(value)


def _vec3(value: object):
    return _facade_attr("_vec3")(value)


def recompute_submesh_normals(submesh: object) -> None:
    _facade_attr("recompute_submesh_normals")(submesh)


def _read_vertex_aligned_native_channels(
    item: Mapping[str, object],
    expected_count: int,
) -> tuple[bool, tuple[object, ...]]:
    raw_normals_binary = item.get("normals_binary")
    raw_uvs_binary = item.get("uvs_binary")
    raw_tangents_binary = item.get("tangents_binary")
    raw_tangent_signs_binary = item.get("tangent_signs_binary")
    raw_bone_counts_binary = item.get("bone_counts_binary")
    raw_bone_indices_binary = item.get("bone_indices_binary")
    raw_bone_weights_binary = item.get("bone_weights_binary")
    raw_source_vertex_map_binary = item.get("source_vertex_map_binary")
    raw_source_vertex_offsets_binary = item.get("source_vertex_offsets_binary")
    readers = (
        (_read_vec3_binary_report_payload, raw_normals_binary),
        (_read_vec2_binary_report_payload, raw_uvs_binary),
        (_read_vec3_binary_report_payload, raw_tangents_binary),
        (_read_f64_binary_report_payload, raw_tangent_signs_binary),
        (_read_i32_binary_report_payload, raw_source_vertex_map_binary),
        (_read_i32_binary_report_payload, raw_source_vertex_offsets_binary),
    )
    decoded: list[object] = []
    for reader, descriptor in readers:
        value = reader(descriptor, expected_count=expected_count) if isinstance(descriptor, Mapping) else None
        if isinstance(descriptor, Mapping) and value is None:
            return False, ()
        decoded.append(value)
    native_bones = None
    bone_descriptors = (raw_bone_counts_binary, raw_bone_indices_binary, raw_bone_weights_binary)
    if all(isinstance(value, Mapping) for value in bone_descriptors):
        native_bones = _read_bone_binary_report_payloads(
            raw_bone_counts_binary,
            raw_bone_indices_binary,
            raw_bone_weights_binary,
            expected_count=expected_count,
        )
        if native_bones is None:
            return False, ()
    native_normals, native_uvs, native_tangents, native_tangent_signs, native_source_vertex_map, native_source_vertex_offsets = decoded
    return True, (
        native_normals,
        native_uvs,
        native_tangents,
        native_tangent_signs,
        native_bones,
        native_source_vertex_map,
        native_source_vertex_offsets,
    )


def _apply_cleanup_report(mesh: ParsedMesh, report: Mapping[str, object]) -> set[int] | None:
    affected: set[int] = set()
    submesh_reports = report.get("submeshes")
    if not isinstance(submesh_reports, list):
        return None
    for item in submesh_reports:
        if not isinstance(item, dict):
            continue
        submesh_index = _index(item.get("index"))
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        old_vertex_count = len(submesh.vertices)
        raw_vertices_binary = item.get("vertices_binary")
        raw_faces_binary = item.get("faces_binary")
        raw_index_map_binary = item.get("index_map_binary")
        raw_normals_binary = item.get("normals_binary")
        raw_uvs_binary = item.get("uvs_binary")
        raw_tangents_binary = item.get("tangents_binary")
        raw_tangent_signs_binary = item.get("tangent_signs_binary")
        raw_bone_counts_binary = item.get("bone_counts_binary")
        raw_bone_indices_binary = item.get("bone_indices_binary")
        raw_bone_weights_binary = item.get("bone_weights_binary")
        raw_source_vertex_map_binary = item.get("source_vertex_map_binary")
        raw_source_vertex_offsets_binary = item.get("source_vertex_offsets_binary")
        vertices = item.get("vertices")
        faces = item.get("faces")
        raw_index_map = item.get("index_map")
        if isinstance(raw_vertices_binary, Mapping):
            vertex_count = _index(raw_vertices_binary.get("count"))
            if vertex_count is None or vertex_count < 0:
                return None
            parsed_vertices = _read_vec3_binary_report_payload(raw_vertices_binary, expected_count=vertex_count)
            if parsed_vertices is None:
                return None
        elif isinstance(vertices, list):
            parsed_vertices = [_vec3(value) for value in vertices]
        else:
            continue
        if isinstance(raw_faces_binary, Mapping):
            face_count = _index(raw_faces_binary.get("count"))
            if face_count is None or face_count < 0:
                return None
            parsed_faces = _read_face_binary_report_payload(raw_faces_binary, expected_count=face_count, vertex_count=len(parsed_vertices))
            if parsed_faces is None:
                return None
        elif isinstance(faces, list):
            parsed_faces = _face_json(faces, len(parsed_vertices))
        else:
            continue
        index_map: list[int] | None = None
        if isinstance(raw_index_map_binary, Mapping):
            index_map = _read_i32_binary_report_payload(raw_index_map_binary, expected_count=old_vertex_count)
            if index_map is None:
                return None
        elif isinstance(raw_index_map, list):
            index_map = []
            for value in raw_index_map:
                parsed_index = _index(value)
                index_map.append(parsed_index if parsed_index is not None else -1)
        if index_map is not None and len(index_map) != old_vertex_count:
            return None
        if index_map is not None and any(new_index < -1 or new_index >= len(parsed_vertices) for new_index in index_map):
            return None
        channels_ok, native_channels = _read_vertex_aligned_native_channels(item, len(parsed_vertices))
        if not channels_ok:
            return None
        (
            native_normals,
            native_uvs,
            native_tangents,
            native_tangent_signs,
            native_bones,
            native_source_vertex_map,
            native_source_vertex_offsets,
        ) = native_channels
        if index_map is None:
            if native_normals is None:
                return None
            if len(submesh.uvs) == old_vertex_count and native_uvs is None:
                return None
            if len(getattr(submesh, "tangents", ()) or ()) == old_vertex_count and native_tangents is None:
                return None
            if len(getattr(submesh, "tangent_signs", ()) or ()) == old_vertex_count and native_tangent_signs is None:
                return None
            if (
                len(getattr(submesh, "bone_indices", ()) or ()) == old_vertex_count
                and len(getattr(submesh, "bone_weights", ()) or ()) == old_vertex_count
                and native_bones is None
            ):
                return None
            if len(getattr(submesh, "source_vertex_map", ()) or ()) == old_vertex_count and native_source_vertex_map is None:
                return None
            if len(getattr(submesh, "source_vertex_offsets", ()) or ()) == old_vertex_count and native_source_vertex_offsets is None:
                return None
        submesh.vertices = parsed_vertices
        submesh.faces = [tuple(face) for face in parsed_faces]
        submesh.uvs = native_uvs if native_uvs is not None else (_remap_vertex_aligned_list(submesh.uvs, index_map) if index_map is not None else [])  # type: ignore[assignment]
        submesh.normals = native_normals if native_normals is not None else (_remap_vertex_aligned_list(submesh.normals, index_map) if index_map is not None else [])  # type: ignore[assignment]
        submesh.tangents = native_tangents if native_tangents is not None else (_remap_vertex_aligned_list(submesh.tangents, index_map) if index_map is not None else [])  # type: ignore[assignment]
        if native_tangent_signs is not None:
            setattr(submesh, "tangent_signs", native_tangent_signs)
        elif index_map is not None and getattr(submesh, "tangent_signs", None):
            setattr(submesh, "tangent_signs", _remap_vertex_aligned_list(getattr(submesh, "tangent_signs"), index_map))
        else:
            setattr(submesh, "tangent_signs", [])
        if native_bones is not None:
            submesh.bone_indices, submesh.bone_weights = native_bones  # type: ignore[assignment]
        elif index_map is not None:
            submesh.bone_indices = _remap_vertex_aligned_list(submesh.bone_indices, index_map)  # type: ignore[assignment]
            submesh.bone_weights = _remap_vertex_aligned_list(submesh.bone_weights, index_map)  # type: ignore[assignment]
        else:
            submesh.bone_indices = []
            submesh.bone_weights = []
        submesh.source_vertex_map = native_source_vertex_map if native_source_vertex_map is not None else (_remap_vertex_aligned_list(submesh.source_vertex_map, index_map) if index_map is not None else [])  # type: ignore[assignment]
        submesh.source_vertex_offsets = native_source_vertex_offsets if native_source_vertex_offsets is not None else (_remap_vertex_aligned_list(submesh.source_vertex_offsets, index_map) if index_map is not None else [])  # type: ignore[assignment]
        submesh.vertex_count = len(submesh.vertices)
        submesh.face_count = len(submesh.faces)
        if native_normals is None:
            recompute_submesh_normals(submesh)
        affected.add(submesh_index)
    return affected


def _apply_auto_uv_report(mesh: ParsedMesh, report: Mapping[str, object]) -> dict[int, Sequence[int] | set[int]] | None:
    changed: dict[int, Sequence[int] | set[int]] = {}
    submesh_reports = report.get("submeshes")
    if not isinstance(submesh_reports, list):
        return None
    for item in submesh_reports:
        if not isinstance(item, dict) or str(item.get("status") or "ok").lower() != "ok":
            continue
        submesh_index = _index(item.get("index"))
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        raw_remap_binary = item.get("vertex_remap_binary")
        raw_vertices_binary = item.get("vertices_binary")
        raw_uvs_binary = item.get("uvs_binary")
        raw_faces_binary = item.get("faces_binary")
        raw_normals_binary = item.get("normals_binary")
        raw_tangents_binary = item.get("tangents_binary")
        raw_tangent_signs_binary = item.get("tangent_signs_binary")
        raw_bone_counts_binary = item.get("bone_counts_binary")
        raw_bone_indices_binary = item.get("bone_indices_binary")
        raw_bone_weights_binary = item.get("bone_weights_binary")
        raw_source_vertex_map_binary = item.get("source_vertex_map_binary")
        raw_source_vertex_offsets_binary = item.get("source_vertex_offsets_binary")
        raw_remap = item.get("vertex_remap")
        raw_uvs = item.get("uvs")
        raw_faces = item.get("faces")
        if isinstance(raw_remap_binary, Mapping):
            output_count = _index(raw_remap_binary.get("count"))
            if output_count is None:
                output_count = _index(item.get("output_vertex_count"))
            if output_count is None or output_count < 0:
                return None
            remap = _read_i32_binary_report_payload(raw_remap_binary, expected_count=output_count)
            if remap is None:
                return None
        elif isinstance(raw_remap, list):
            remap = []
            for value in raw_remap:
                old_index = _index(value)
                if old_index is None:
                    return None
                remap.append(old_index)
        else:
            continue
        if any(old_index < 0 or old_index >= len(submesh.vertices) for old_index in remap):
            return None
        if isinstance(raw_vertices_binary, Mapping):
            parsed_vertices = _read_vec3_binary_report_payload(raw_vertices_binary, expected_count=len(remap))
            if parsed_vertices is None:
                return None
        else:
            parsed_vertices = [submesh.vertices[old_index] for old_index in remap]
        if isinstance(raw_uvs_binary, Mapping):
            parsed_uvs = _read_vec2_binary_report_payload(raw_uvs_binary, expected_count=len(remap))
            if parsed_uvs is None:
                return None
        elif isinstance(raw_uvs, list):
            parsed_uvs = [_vec2(value) for value in raw_uvs]
        else:
            continue
        if len(parsed_uvs) != len(remap):
            return None
        if isinstance(raw_faces_binary, Mapping):
            face_count = _index(raw_faces_binary.get("count"))
            if face_count is None:
                face_count = _index(item.get("output_face_count"))
            if face_count is None or face_count < 0:
                return None
            parsed_faces = _read_face_binary_report_payload(raw_faces_binary, expected_count=face_count, vertex_count=len(parsed_uvs))
            if parsed_faces is None:
                return None
        elif isinstance(raw_faces, list):
            parsed_faces = _face_json(raw_faces, len(parsed_uvs))
            if len(parsed_faces) != len(raw_faces):
                return None
        else:
            continue

        channels_ok, native_channels = _read_vertex_aligned_native_channels(item, len(remap))
        if not channels_ok:
            return None
        (
            native_normals,
            native_uvs,
            native_tangents,
            native_tangent_signs,
            native_bones,
            native_source_vertex_map,
            native_source_vertex_offsets,
        ) = native_channels

        parsed_changed_ordered = _changed_vertices_from_report_item(item, len(parsed_uvs))
        has_native_changed_vertices = parsed_changed_ordered is not None
        parsed_changed = _changed_vertices_for_report(parsed_changed_ordered)
        old_vertex_count = len(submesh.vertices)
        old_face_count = len(submesh.faces)
        old_uvs = () if has_native_changed_vertices else (
            tuple(_vec2(uv) for uv in submesh.uvs) if len(submesh.uvs) == old_vertex_count else ()
        )
        submesh.vertices = parsed_vertices
        submesh.uvs = parsed_uvs
        submesh.faces = [tuple(face) for face in parsed_faces]
        submesh.normals = native_normals if native_normals is not None else _copy_vertex_aligned_list(submesh.normals, remap)  # type: ignore[assignment]
        submesh.tangents = native_tangents if native_tangents is not None else _copy_vertex_aligned_list(submesh.tangents, remap)  # type: ignore[assignment]
        if native_tangent_signs is not None:
            setattr(submesh, "tangent_signs", native_tangent_signs)
        elif getattr(submesh, "tangent_signs", None):
            setattr(submesh, "tangent_signs", _copy_vertex_aligned_list(getattr(submesh, "tangent_signs"), remap))
        if native_bones is not None:
            submesh.bone_indices, submesh.bone_weights = native_bones  # type: ignore[assignment]
        else:
            submesh.bone_indices = _copy_vertex_aligned_list(submesh.bone_indices, remap)  # type: ignore[assignment]
            submesh.bone_weights = _copy_vertex_aligned_list(submesh.bone_weights, remap)  # type: ignore[assignment]
        submesh.source_vertex_map = native_source_vertex_map if native_source_vertex_map is not None else _copy_vertex_aligned_list(submesh.source_vertex_map, remap)  # type: ignore[assignment]
        submesh.source_vertex_offsets = native_source_vertex_offsets if native_source_vertex_offsets is not None else _copy_vertex_aligned_list(submesh.source_vertex_offsets, remap)  # type: ignore[assignment]
        if len(submesh.normals) != len(submesh.vertices):
            recompute_submesh_normals(submesh)
        submesh.vertex_count = len(submesh.vertices)
        submesh.face_count = len(submesh.faces)
        changed_vertices: Sequence[int] | set[int] = (
            parsed_changed_ordered if isinstance(parsed_changed_ordered, range) else parsed_changed
        ) if has_native_changed_vertices else ()
        if not has_native_changed_vertices and (
            submesh.vertex_count != old_vertex_count
            or submesh.face_count != old_face_count
            or tuple(parsed_uvs) != old_uvs
        ):
            changed_vertices = range(len(submesh.vertices))
        if changed_vertices:
            _merge_changed_vertices(changed, submesh_index, changed_vertices)
            setattr(
                submesh,
                "auto_uv_report",
                {
                    "unwrap_backend": item.get("unwrap_backend"),
                    "topology_changed": bool(item.get("topology_changed")),
                    "chart_count": _index(item.get("chart_count")) or 0,
                    "vertex_remap": tuple(remap),
                },
            )
    return changed


def _apply_uv_transform_report(mesh: ParsedMesh, report: Mapping[str, object]) -> dict[int, Sequence[int] | set[int]] | None:
    changed: dict[int, Sequence[int] | set[int]] = {}
    submesh_reports = report.get("submeshes")
    if not isinstance(submesh_reports, list):
        return None
    for item in submesh_reports:
        if not isinstance(item, dict):
            continue
        submesh_index = _index(item.get("index"))
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        parsed_changed_ordered = _changed_vertices_from_report_item(item, len(submesh.vertices))
        if bool(item.get("clear_uvs")):
            if parsed_changed_ordered is not None and parsed_changed_ordered:
                submesh.uvs = []
                mesh.has_uvs = any(bool(getattr(candidate, "uvs", None)) for candidate in mesh.submeshes)
                _merge_changed_vertices(changed, submesh_index, parsed_changed_ordered)
            continue
        expected_uv_count = len(submesh.uvs)
        if expected_uv_count != len(submesh.vertices):
            expected_uv_count = len(submesh.vertices)
        raw_uvs_binary = item.get("uvs_binary")
        raw_uvs = item.get("uvs")
        if isinstance(raw_uvs_binary, Mapping):
            parsed_uvs = _read_vec2_binary_report_payload(raw_uvs_binary, expected_count=expected_uv_count)
            if parsed_uvs is None:
                return None
        elif isinstance(raw_uvs, list):
            if len(raw_uvs) != expected_uv_count:
                return None
            parsed_uvs = [_vec2(value) for value in raw_uvs]
        else:
            continue
        parsed_changed_ordered = _changed_vertices_from_report_item(item, len(parsed_uvs))
        if parsed_changed_ordered is None:
            continue
        if parsed_changed_ordered:
            submesh.uvs = parsed_uvs
            if len(parsed_uvs) == len(submesh.vertices) and parsed_uvs:
                mesh.has_uvs = True
            _merge_changed_vertices(
                changed,
                submesh_index,
                parsed_changed_ordered,
            )
    return changed
