from __future__ import annotations

from importlib import import_module
import math
from typing import Mapping, Sequence

from cdmw.modding.mesh_native_binary_io import (
    _read_bone_binary_report_payloads,
    _read_f64_binary_report_payload,
    _read_face_binary_report_payload,
    _read_i32_binary_report_payload,
    _read_int_binary_report_payload,
    _read_vec2_binary_report_payload,
    _read_vec3_binary_report_payload,
)
from cdmw.modding.mesh_native_core_constants import NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR, Vec3
from cdmw.modding.mesh_native_core_payload_helpers import _finite_float, _index, _same_vec3_tuple
from cdmw.modding.mesh_native_history import _changed_vertices_for_report, _changed_vertices_from_report_item, _native_history_vertex_delta
from cdmw.modding.mesh_native_payloads import _i32_range_report_values
from cdmw.modding.mesh_native_preview_payloads import _native_preview_vertex_update_group
from cdmw.modding.mesh_parser import ParsedMesh


def _facade_attr(name: str):
    return getattr(import_module("cdmw.modding.mesh_native_core"), name)


def _face_json(value: object, vertex_count: int):
    return _facade_attr("_face_json")(value, vertex_count)


def _vec3(value: object, *, fallback: float = 0.0) -> Vec3:
    return _facade_attr("_vec3")(value, fallback=fallback)


def _refresh_mesh_totals(mesh: ParsedMesh) -> None:
    mesh.total_vertices = sum(len(submesh.vertices or []) for submesh in mesh.submeshes or [])
    mesh.total_faces = sum(len(submesh.faces or []) for submesh in mesh.submeshes or [])
    mesh.has_uvs = any(bool(submesh.uvs) for submesh in mesh.submeshes or [])
    mesh.has_bones = any(bool(submesh.bone_indices) or bool(submesh.bone_weights) for submesh in mesh.submeshes or [])
    for submesh in mesh.submeshes or []:
        submesh.vertex_count = len(submesh.vertices or [])
        submesh.face_count = len(submesh.faces or [])


def _apply_transform_report(mesh: ParsedMesh, report: Mapping[str, object]) -> dict[int, Sequence[int] | set[int]] | None:
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
        vertices = item.get("vertices")
        changed_positions = item.get("changed_positions")
        changed_positions_binary = item.get("changed_positions_binary")
        raw_preview_vertex_update_group = item.get("preview_vertex_update_group")
        raw_before_positions_binary = item.get("before_positions_binary")
        submesh = mesh.submeshes[submesh_index]
        parsed_changed_ordered = _changed_vertices_from_report_item(item, len(submesh.vertices))
        if parsed_changed_ordered is None:
            continue
        parsed_changed = _changed_vertices_for_report(parsed_changed_ordered)
        history_delta = _native_history_vertex_delta(item, submesh_index, parsed_changed_ordered)
        if raw_before_positions_binary is not None and history_delta is None:
            return None
        if isinstance(vertices, list):
            if len(vertices) != len(submesh.vertices):
                return None
            parsed_vertices = [_vec3(value) for value in vertices]
            if parsed_changed:
                submesh.vertices = parsed_vertices
                submesh.vertex_count = len(parsed_vertices)
                _merge_changed_vertices(
                    changed,
                    submesh_index,
                    parsed_changed,
                )
        else:
            if changed_positions_binary is not None:
                changed_positions = _read_vec3_binary_report_payload(
                    changed_positions_binary,
                    expected_count=len(parsed_changed_ordered),
                )
            if not isinstance(changed_positions, list):
                if parsed_changed:
                    return None
                changed_positions = []
            if len(changed_positions) != len(parsed_changed_ordered):
                return None
            changed_here: Sequence[int] | set[int] = parsed_changed_ordered if isinstance(parsed_changed_ordered, range) else set()
            changed_count = 0
            vertices_copy = list(submesh.vertices or [])
            for index, raw_position in zip(parsed_changed_ordered, changed_positions):
                vertices_copy[index] = _vec3(raw_position)
                changed_count += 1
                if not isinstance(changed_here, range):
                    changed_here.add(index)
            if changed_here:
                submesh.vertices = vertices_copy
                submesh.vertex_count = len(vertices_copy)
                _merge_changed_vertices(
                    changed,
                    submesh_index,
                    changed_here if changed_count == len(parsed_changed_ordered) else set(),
                )
        preview_vertex_update_group = _native_preview_vertex_update_group(raw_preview_vertex_update_group, submesh_index)
        if preview_vertex_update_group is not None:
            setattr(submesh, "cdmw_native_preview_vertex_update_group", preview_vertex_update_group)
        elif hasattr(submesh, "cdmw_native_preview_vertex_update_group"):
            delattr(submesh, "cdmw_native_preview_vertex_update_group")
        if history_delta is not None:
            setattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR, history_delta)
        elif hasattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR):
            delattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR)
    return changed


def _native_report_metrics(report: Mapping[str, object]) -> dict[str, float]:
    raw_metrics = report.get("metrics")
    if not isinstance(raw_metrics, Mapping):
        return {}
    metrics: dict[str, float] = {}
    for key, value in raw_metrics.items():
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(number):
            metrics[str(key)] = max(0.0, number)
    return metrics


def _apply_selection_report(mesh: ParsedMesh, report: Mapping[str, object]) -> dict[int, set[int]] | None:
    selected_by_submesh: dict[int, set[int]] = {}
    submesh_reports = report.get("submeshes")
    if not isinstance(submesh_reports, list):
        return None
    for item in submesh_reports:
        if not isinstance(item, dict):
            continue
        submesh_index = _index(item.get("index"))
        raw_selected = item.get("selected_vertices")
        raw_selected_binary = item.get("selected_vertices_binary")
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        vertex_count = len(mesh.submeshes[submesh_index].vertices)
        selected_range = _i32_range_report_values(
            item,
            start_key="selected_vertex_start",
            count_key="selected_vertex_count",
            max_count=vertex_count,
        )
        if selected_range is not None:
            selected = set(selected_range)
        elif isinstance(raw_selected_binary, Mapping):
            selected_values = _read_int_binary_report_payload(raw_selected_binary, max_count=vertex_count)
            if selected_values is None:
                return None
            selected = set(selected_values)
        elif isinstance(raw_selected, list):
            selected = {
                index
                for raw_index in raw_selected
                for index in [_index(raw_index)]
                if index is not None and 0 <= index < vertex_count
            }
        else:
            continue
        if selected:
            selected_by_submesh[submesh_index] = selected
    return selected_by_submesh


def _apply_recalculate_normals_report(
    mesh: ParsedMesh,
    report: Mapping[str, object],
    *,
    return_changed_vertices: bool = False,
) -> set[int] | dict[int, Sequence[int] | set[int]] | None:
    affected: set[int] = set()
    changed: dict[int, Sequence[int] | set[int]] = {}
    operation = str(report.get("operation") or "")
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
        raw_normals = item.get("normals")
        if isinstance(raw_normals, list):
            if len(raw_normals) != len(submesh.vertices):
                return None
            parsed_normals = [_vec3(value, fallback=0.0) for value in raw_normals]
        else:
            parsed_normals = _read_vec3_binary_report_payload(
                item.get("normals_binary"),
                expected_count=len(submesh.vertices),
            )
            if parsed_normals is None:
                continue
        parsed_changed_ordered = _changed_vertices_from_report_item(item, len(parsed_normals))
        has_native_changed_vertices = parsed_changed_ordered is not None
        parsed_changed = _changed_vertices_for_report(parsed_changed_ordered)
        before_normals = () if has_native_changed_vertices else tuple(_vec3(normal, fallback=0.0) for normal in submesh.normals or ())
        faces = item.get("faces")
        faces_binary = item.get("faces_binary")
        faces_changed = False
        if isinstance(faces, list):
            parsed_faces = _face_json(faces, len(submesh.vertices))
            if len(parsed_faces) != len(faces):
                return None
            next_faces = [tuple(face) for face in parsed_faces]
            submesh.faces = next_faces
            faces_changed = True
        elif isinstance(faces_binary, Mapping):
            parsed_faces = _read_face_binary_report_payload(
                faces_binary,
                expected_count=len(submesh.faces or ()),
                vertex_count=len(submesh.vertices),
            )
            if parsed_faces is None:
                return None
            next_faces = [tuple(face) for face in parsed_faces]
            submesh.faces = next_faces
            faces_changed = True
        submesh.normals = parsed_normals
        normals_changed = bool(parsed_changed) if has_native_changed_vertices else False
        if not has_native_changed_vertices:
            normals_changed = not _same_vec3_tuple(before_normals, tuple(parsed_normals))
        if faces_changed or normals_changed:
            affected.add(submesh_index)
        if has_native_changed_vertices:
            if parsed_changed:
                _merge_changed_vertices(
                    changed,
                    submesh_index,
                    parsed_changed,
                )
        elif normals_changed:
            _merge_changed_vertices(changed, submesh_index, range(len(parsed_normals)))
        if return_changed_vertices:
            preview_vertex_update_group = _native_preview_vertex_update_group(
                item.get("preview_vertex_update_group"),
                submesh_index,
            )
            if preview_vertex_update_group is not None:
                setattr(submesh, "cdmw_native_preview_vertex_update_group", preview_vertex_update_group)
            elif hasattr(submesh, "cdmw_native_preview_vertex_update_group"):
                delattr(submesh, "cdmw_native_preview_vertex_update_group")
        elif operation == "flip_normals" and hasattr(submesh, "cdmw_native_preview_vertex_update_group"):
            delattr(submesh, "cdmw_native_preview_vertex_update_group")
    return changed if return_changed_vertices else affected


def _apply_generate_tangents_report(mesh: ParsedMesh, report: Mapping[str, object]) -> set[int] | None:
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
        if bool(item.get("clear_tangents")):
            had_tangents = bool(getattr(submesh, "tangents", None))
            submesh.tangents = []
            if hasattr(submesh, "tangent_signs"):
                setattr(submesh, "tangent_signs", [])
            if hasattr(submesh, "tangent_face_corner_report"):
                delattr(submesh, "tangent_face_corner_report")
            if had_tangents:
                affected.add(submesh_index)
            continue
        if not bool(item.get("vertex_storage_safe", True)):
            if _apply_native_tangent_split_result(submesh, item) is None:
                if _apply_face_corner_tangent_split(submesh, item) is None:
                    return None
            setattr(
                submesh,
                "tangent_face_corner_report",
                _tangent_face_corner_report(
                    item,
                    len(submesh.tangents),
                    vertex_storage_safe=True,
                    topology_split_applied=True,
                ),
            )
            affected.add(submesh_index)
            continue
        tangents = item.get("tangents")
        raw_tangents_binary = item.get("tangents_binary")
        if isinstance(raw_tangents_binary, Mapping):
            parsed_tangents = _read_vec3_binary_report_payload(raw_tangents_binary, expected_count=len(submesh.vertices))
            if parsed_tangents is None:
                return None
        elif isinstance(tangents, list):
            if len(tangents) != len(submesh.vertices):
                return None
            parsed_tangents = [_vec3(value, fallback=0.0) for value in tangents]
        else:
            continue
        raw_signs_binary = item.get("tangent_signs_binary")
        raw_signs = item.get("tangent_signs")
        parsed_signs: list[float] | None = None
        if isinstance(raw_signs_binary, Mapping):
            parsed_signs = _read_f64_binary_report_payload(
                raw_signs_binary,
                expected_count=len(parsed_tangents),
            )
        elif isinstance(raw_signs, list) and len(raw_signs) == len(parsed_tangents):
            try:
                parsed_signs = [float(value) for value in raw_signs]
            except (TypeError, ValueError, OverflowError):
                return None
        if (raw_signs_binary is not None or raw_signs is not None) and parsed_signs is None:
            return None
        parsed_changed_ordered = _changed_vertices_from_report_item(item, len(parsed_tangents))
        has_native_changed_vertices = parsed_changed_ordered is not None
        parsed_changed = _changed_vertices_for_report(parsed_changed_ordered)
        before = () if has_native_changed_vertices else tuple(_vec3(tangent, fallback=0.0) for tangent in tuple(getattr(submesh, "tangents", ()) or ()))
        submesh.tangents = parsed_tangents
        if parsed_signs is not None:
            setattr(submesh, "tangent_signs", parsed_signs)
        setattr(submesh, "tangent_face_corner_report", _tangent_face_corner_report(item, len(parsed_tangents)))
        if (has_native_changed_vertices and parsed_changed) or (
            not has_native_changed_vertices and not _same_vec3_tuple(before, tuple(parsed_tangents))
        ):
            affected.add(submesh_index)
    return affected


def _report_count(value: object) -> int | None:
    if not isinstance(value, Mapping):
        return None
    count = _index(value.get("count"))
    return count if count is not None and count >= 0 else None


def _apply_native_tangent_split_result(submesh: object, item: Mapping[str, object]) -> bool | None:
    if not bool(item.get("topology_split_applied")):
        return None
    vertex_count = _index(item.get("output_vertex_count"))
    if vertex_count is None:
        vertex_count = _report_count(item.get("vertices_binary"))
    face_count = _index(item.get("output_face_count"))
    if face_count is None:
        face_count = _report_count(item.get("faces_binary"))
    if vertex_count is None or face_count is None:
        return None
    vertices = _read_vec3_binary_report_payload(item.get("vertices_binary"), expected_count=vertex_count)
    faces = _read_face_binary_report_payload(item.get("faces_binary"), expected_count=face_count, vertex_count=vertex_count)
    uvs = _read_vec2_binary_report_payload(item.get("uvs_binary"), expected_count=vertex_count)
    normals = _read_vec3_binary_report_payload(item.get("normals_binary"), expected_count=vertex_count)
    tangents = _read_vec3_binary_report_payload(item.get("tangents_binary"), expected_count=vertex_count)
    tangent_signs = _read_f64_binary_report_payload(item.get("tangent_signs_binary"), expected_count=vertex_count)
    if vertices is None or faces is None or uvs is None or normals is None or tangents is None or tangent_signs is None:
        return None

    bone_indices: list[tuple[int, ...]] = []
    bone_weights: list[tuple[float, ...]] = []
    if (
        isinstance(item.get("bone_counts_binary"), Mapping)
        or isinstance(item.get("bone_indices_binary"), Mapping)
        or isinstance(item.get("bone_weights_binary"), Mapping)
    ):
        bone_payload = _read_bone_binary_report_payloads(
            item.get("bone_counts_binary"),
            item.get("bone_indices_binary"),
            item.get("bone_weights_binary"),
            expected_count=vertex_count,
        )
        if bone_payload is None:
            return None
        bone_indices, bone_weights = bone_payload

    source_vertex_map: list[int] = []
    source_vertex_offsets: list[int] = []
    if isinstance(item.get("source_vertex_map_binary"), Mapping):
        parsed_source_map = _read_i32_binary_report_payload(item.get("source_vertex_map_binary"), expected_count=vertex_count)
        if parsed_source_map is None:
            return None
        source_vertex_map = parsed_source_map
    if isinstance(item.get("source_vertex_offsets_binary"), Mapping):
        parsed_source_offsets = _read_i32_binary_report_payload(item.get("source_vertex_offsets_binary"), expected_count=vertex_count)
        if parsed_source_offsets is None:
            return None
        source_vertex_offsets = parsed_source_offsets

    submesh.vertices = vertices
    submesh.uvs = uvs
    submesh.normals = normals
    submesh.tangents = tangents
    submesh.faces = list(faces)
    submesh.bone_indices = bone_indices
    submesh.bone_weights = bone_weights
    submesh.source_vertex_map = source_vertex_map
    submesh.source_vertex_offsets = source_vertex_offsets
    submesh.vertex_count = len(vertices)
    submesh.face_count = len(faces)
    setattr(submesh, "tangent_signs", tangent_signs)
    return True


def _tangent_face_corner_report(
    item: Mapping[str, object],
    tangent_count: int,
    *,
    vertex_storage_safe: bool | None = None,
    topology_split_applied: bool = False,
) -> dict[str, object]:
    source_safe = bool(item.get("vertex_storage_safe", True))
    return {
        "backend": item.get("tangent_backend"),
        "face_corner_remap": item.get("face_corner_remap"),
        "vertex_storage_safe": source_safe if vertex_storage_safe is None else bool(vertex_storage_safe),
        "source_vertex_storage_safe": source_safe,
        "topology_split_applied": bool(topology_split_applied),
        "split_required_vertices": tuple(
            index
            for raw_index in item.get("split_required_vertices", [])
            for index in [_index(raw_index)]
            if index is not None and 0 <= index < max(0, tangent_count)
        ),
    }


def _apply_face_corner_tangent_split(submesh: object, item: Mapping[str, object]) -> bool | None:
    old_vertices = list(getattr(submesh, "vertices", ()) or ())
    old_faces = list(getattr(submesh, "faces", ()) or ())
    old_vertex_count = len(old_vertices)
    face_corners = _parsed_face_corner_tangents(item, old_faces, old_vertex_count)
    if face_corners is None:
        return None

    old_uvs = list(getattr(submesh, "uvs", ()) or ())
    old_normals = list(getattr(submesh, "normals", ()) or ())
    old_bone_indices = list(getattr(submesh, "bone_indices", ()) or ())
    old_bone_weights = list(getattr(submesh, "bone_weights", ()) or ())
    old_source_vertex_map = list(getattr(submesh, "source_vertex_map", ()) or ())
    old_source_vertex_offsets = list(getattr(submesh, "source_vertex_offsets", ()) or ())

    has_uvs = len(old_uvs) == old_vertex_count
    has_normals = len(old_normals) == old_vertex_count
    has_bone_indices = len(old_bone_indices) == old_vertex_count
    has_bone_weights = len(old_bone_weights) == old_vertex_count
    has_source_vertex_map = len(old_source_vertex_map) == old_vertex_count
    has_source_vertex_offsets = len(old_source_vertex_offsets) == old_vertex_count

    new_vertices: list[object] = []
    new_uvs: list[object] = []
    new_normals: list[object] = []
    new_tangents: list[Vec3] = []
    new_tangent_signs: list[float] = []
    new_bone_indices: list[object] = []
    new_bone_weights: list[object] = []
    new_source_vertex_map: list[int] = []
    new_source_vertex_offsets: list[int] = []
    new_faces: list[tuple[int, int, int]] = []
    corner_index_by_key: dict[tuple[int, Vec3, float], int] = {}

    for face_index in range(len(old_faces)):
        vertices, tangents, signs = face_corners.get(face_index, ((), (), ()))
        if len(vertices) != 3 or len(tangents) != 3 or len(signs) != 3:
            return None
        new_face: list[int] = []
        for old_index, tangent, sign in zip(vertices, tangents, signs):
            key = (old_index, tangent, sign)
            new_index = corner_index_by_key.get(key)
            if new_index is None:
                new_index = len(new_vertices)
                corner_index_by_key[key] = new_index
                new_vertices.append(old_vertices[old_index])
                new_uvs.append(old_uvs[old_index] if has_uvs else (0.0, 0.0))
                new_normals.append(old_normals[old_index] if has_normals else (0.0, 0.0, 1.0))
                new_tangents.append(tangent)
                new_tangent_signs.append(sign)
                if has_bone_indices:
                    new_bone_indices.append(old_bone_indices[old_index])
                if has_bone_weights:
                    new_bone_weights.append(old_bone_weights[old_index])
                if has_source_vertex_map:
                    new_source_vertex_map.append(int(old_source_vertex_map[old_index]))
                if has_source_vertex_offsets:
                    new_source_vertex_offsets.append(int(old_source_vertex_offsets[old_index]))
            new_face.append(new_index)
        new_faces.append((new_face[0], new_face[1], new_face[2]))

    submesh.vertices = new_vertices
    submesh.uvs = new_uvs
    submesh.normals = new_normals
    submesh.tangents = new_tangents
    submesh.faces = new_faces
    submesh.bone_indices = new_bone_indices
    submesh.bone_weights = new_bone_weights
    submesh.source_vertex_map = new_source_vertex_map
    submesh.source_vertex_offsets = new_source_vertex_offsets
    submesh.vertex_count = len(new_vertices)
    submesh.face_count = len(new_faces)
    setattr(submesh, "tangent_signs", new_tangent_signs)
    return True


def _parsed_face_corner_tangents(
    item: Mapping[str, object],
    old_faces: list[object],
    old_vertex_count: int,
) -> dict[int, tuple[tuple[int, int, int], tuple[Vec3, Vec3, Vec3], tuple[float, float, float]]] | None:
    raw_face_corners = item.get("face_corner_tangents")
    if not isinstance(raw_face_corners, list) or len(raw_face_corners) != len(old_faces):
        return None
    result: dict[int, tuple[tuple[int, int, int], tuple[Vec3, Vec3, Vec3], tuple[float, float, float]]] = {}
    for raw_item in raw_face_corners:
        if not isinstance(raw_item, Mapping):
            return None
        face_index = _index(raw_item.get("face_index"))
        if face_index is None or not 0 <= face_index < len(old_faces) or face_index in result:
            return None
        actual_face = _valid_face_tuple(old_faces[face_index], old_vertex_count)
        vertices = _valid_face_tuple(raw_item.get("vertices"), old_vertex_count)
        if actual_face is None or vertices is None or vertices != actual_face:
            return None
        raw_tangents = raw_item.get("tangents")
        raw_signs = raw_item.get("signs")
        if not isinstance(raw_tangents, list) or len(raw_tangents) != 3:
            return None
        signs_source = raw_signs if isinstance(raw_signs, list) and len(raw_signs) == 3 else [1.0, 1.0, 1.0]
        result[face_index] = (
            vertices,
            tuple(_vec3(value, fallback=0.0) for value in raw_tangents),  # type: ignore[assignment]
            tuple(1.0 if _finite_float(value, 1.0) >= 0.0 else -1.0 for value in signs_source),  # type: ignore[assignment]
        )
    return result if len(result) == len(old_faces) else None


def _valid_face_tuple(face: object, vertex_count: int) -> tuple[int, int, int] | None:
    if not isinstance(face, (tuple, list)) or len(face) < 3:
        return None
    a = _index(face[0])
    b = _index(face[1])
    c = _index(face[2])
    if a is None or b is None or c is None:
        return None
    if not (0 <= a < vertex_count and 0 <= b < vertex_count and 0 <= c < vertex_count):
        return None
    return a, b, c


def _merge_changed_vertices(
    changed: dict[int, Sequence[int] | set[int]],
    submesh_index: int,
    indices: Sequence[int] | set[int],
) -> None:
    if not indices:
        return
    current = changed.get(submesh_index)
    if not current:
        changed[submesh_index] = indices
        return
    merged = {int(index) for index in current}
    merged.update(int(index) for index in indices)
    if merged:
        changed[submesh_index] = merged
