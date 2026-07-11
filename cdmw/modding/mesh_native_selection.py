from __future__ import annotations

from importlib import import_module
import os
from pathlib import Path
import shutil
import tempfile
from typing import Mapping, Sequence

from cdmw.modding.mesh_native_binary_io import (
    _read_i32_components_binary_report_payload,
    _read_int_binary_report_payload,
    _write_edge_binary_payload,
    _write_face_binary_payload,
)
from cdmw.modding.mesh_native_core_blend_helpers import _edge_list, _int_list
from cdmw.modding.mesh_native_core_constants import NATIVE_MESH_CORE_BACKEND_ID
from cdmw.modding.mesh_native_core_payload_helpers import _index
from cdmw.modding.mesh_native_payloads import (
    _i32_range_report_values,
    _put_i32_range_or_binary_payload,
    _put_source_face_indices_payload,
)
from cdmw.modding.mesh_parser import ParsedMesh


def _facade_attr(name: str):
    return getattr(import_module("cdmw.modding.mesh_native_core"), name)


def _ensure_native_mesh_session_submesh(*args, **kwargs):
    return _facade_attr("_ensure_native_mesh_session_submesh")(*args, **kwargs)


def _face_json_with_source_indices(*args, **kwargs):
    return _facade_attr("_face_json_with_source_indices")(*args, **kwargs)


def _native_preview_delta_output_path(suffix: str = ".bin") -> str:
    return _facade_attr("_native_preview_delta_output_path")(suffix)


def _native_report_metrics(report: Mapping[str, object]) -> dict[str, float]:
    return _facade_attr("_native_report_metrics")(report)


def _run_native_mesh_core_job(*args, **kwargs):
    return _facade_attr("_run_native_mesh_core_job")(*args, **kwargs)


def find_native_mesh_core_binary():
    return _facade_attr("find_native_mesh_core_binary")()


def _native_selection_operation(value: object) -> str:
    operation = str(value or "replace").strip().lower()
    if operation == "extend":
        operation = "add"
    elif operation == "remove":
        operation = "subtract"
    return operation if operation in {"add", "subtract", "toggle"} else "replace"


def _combine_native_selection_sources(
    submesh_count: int,
    current: Sequence[int],
    incoming: Sequence[int],
    operation: str,
) -> tuple[int, ...]:
    current_set = {
        index
        for raw_index in (current if current is not None else ())
        if (index := _index(raw_index)) is not None and 0 <= index < submesh_count
    }
    incoming_set = {
        index
        for raw_index in (incoming if incoming is not None else ())
        if (index := _index(raw_index)) is not None and 0 <= index < submesh_count
    }
    if operation == "add":
        current_set.update(incoming_set)
        return tuple(sorted(current_set))
    if operation == "subtract":
        current_set.difference_update(incoming_set)
        return tuple(sorted(current_set))
    if operation == "toggle":
        for index in incoming_set:
            if index in current_set:
                current_set.remove(index)
            else:
                current_set.add(index)
        return tuple(sorted(current_set))
    return tuple(sorted(incoming_set))


def _empty_pruned_selection(source_indices: Sequence[int]) -> dict[str, object]:
    return {
        "vertices_by_submesh": {},
        "edges_by_submesh": {},
        "faces_by_submesh": {},
        "source_indices": source_indices,
    }


def _selection_indices(values: object, *, limit: int | None = None) -> list[int]:
    result: list[int] = []
    for raw_index in values or ():
        index = _index(raw_index)
        if index is not None and index >= 0 and (limit is None or index < limit):
            result.append(index)
    return sorted(set(result))


def _selection_edges(values: object, vertex_count: int) -> list[tuple[int, int]]:
    result: set[tuple[int, int]] = set()
    for raw_edge in values or ():
        if not isinstance(raw_edge, (tuple, list)) or len(raw_edge) < 2:
            continue
        left, right = _index(raw_edge[0]), _index(raw_edge[1])
        if left is not None and right is not None and 0 <= left < vertex_count and 0 <= right < vertex_count and left != right:
            result.add((min(left, right), max(left, right)))
    return sorted(result)


def _put_selection_prune_payloads(
    item: dict[str, object],
    prefix: Path,
    *,
    selected_vertices: Sequence[int],
    selected_edges: Sequence[tuple[int, int]],
    selected_faces: Sequence[int],
    selected_all_vertices: bool,
    current_vertices: Sequence[int],
    current_edges: Sequence[tuple[int, int]],
    current_faces: Sequence[int],
    operation: str,
    vertex_count: int,
) -> None:
    if selected_vertices:
        _put_i32_range_or_binary_payload(item, values=selected_vertices, start_key="selected_vertex_start", count_key="selected_vertex_count", binary_key="selected_vertices_binary", binary_path=prefix.with_name(prefix.name + "_selected_vertices.bin"), max_count=vertex_count)
    if selected_all_vertices:
        item["selected_all_vertices"] = True
    if selected_edges:
        item["selected_edges_binary"] = _write_edge_binary_payload(prefix.with_name(prefix.name + "_selected_edges.bin"), selected_edges)
    if selected_faces:
        _put_i32_range_or_binary_payload(item, values=selected_faces, start_key="selected_face_start", count_key="selected_face_count", binary_key="selected_faces_binary", binary_path=prefix.with_name(prefix.name + "_selected_faces.bin"))
    if operation == "replace":
        return
    if current_vertices:
        _put_i32_range_or_binary_payload(item, values=current_vertices, start_key="current_selected_vertex_start", count_key="current_selected_vertex_count", binary_key="current_selected_vertices_binary", binary_path=prefix.with_name(prefix.name + "_current_vertices.bin"), max_count=vertex_count)
    if current_edges:
        item["current_selected_edges_binary"] = _write_edge_binary_payload(prefix.with_name(prefix.name + "_current_edges.bin"), current_edges)
    if current_faces:
        _put_i32_range_or_binary_payload(item, values=current_faces, start_key="current_selected_face_start", count_key="current_selected_face_count", binary_key="current_selected_faces_binary", binary_path=prefix.with_name(prefix.name + "_current_faces.bin"))


def _build_selection_prune_item(
    mesh: ParsedMesh,
    submesh_index: int,
    sidecar_root: Path,
    binary: Path,
    operation: str,
    vertices_by_submesh: Mapping[int, set[int]],
    edges_by_submesh: Mapping[int, set[tuple[int, int]]],
    faces_by_submesh: Mapping[int, set[int]],
    current_vertices_by_submesh: Mapping[int, set[int]],
    current_edges_by_submesh: Mapping[int, set[tuple[int, int]]],
    current_faces_by_submesh: Mapping[int, set[int]],
    selected_all_vertex_sources: set[int],
    timeout_seconds: float,
) -> dict[str, object] | None:
    submesh = mesh.submeshes[submesh_index]
    vertex_count = len(getattr(submesh, "vertices", ()) or ())
    face_count = len(getattr(submesh, "faces", ()) or ())
    selected_vertices = _selection_indices(vertices_by_submesh.get(submesh_index, ()), limit=vertex_count)
    selected_edges = _selection_edges(edges_by_submesh.get(submesh_index, ()), vertex_count)
    selected_faces = _selection_indices(faces_by_submesh.get(submesh_index, ()))
    current_vertices = _selection_indices(current_vertices_by_submesh.get(submesh_index, ()), limit=vertex_count)
    current_edges = _selection_edges(current_edges_by_submesh.get(submesh_index, ()), vertex_count)
    current_faces = _selection_indices(current_faces_by_submesh.get(submesh_index, ()))
    selected_all_vertices = submesh_index in selected_all_vertex_sources
    if vertex_count <= 0 or not (selected_vertices or selected_edges or selected_faces or selected_all_vertices or current_vertices or current_edges or current_faces):
        return None
    prefix = sidecar_root / f"selection_prune_{submesh_index}"
    item: dict[str, object] = {
        "index": submesh_index,
        "face_count": face_count,
        "selection_operation": operation,
        "selected_vertices_output_path": _native_preview_delta_output_path("_pruned_vertices.bin"),
        "selected_edges_output_path": _native_preview_delta_output_path("_pruned_edges.bin"),
        "selected_faces_output_path": _native_preview_delta_output_path("_pruned_faces.bin"),
    }
    session_id = _ensure_native_mesh_session_submesh(binary, mesh, submesh_index, timeout_seconds=timeout_seconds)
    if session_id:
        item["session_id"] = session_id
    else:
        faces, source_face_indices = _face_json_with_source_indices(submesh.faces, vertex_count)
        item["vertex_count"] = vertex_count
        item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
        _put_source_face_indices_payload(item, prefix, source_face_indices)
    _put_selection_prune_payloads(
        item, prefix, selected_vertices=selected_vertices, selected_edges=selected_edges,
        selected_faces=selected_faces, selected_all_vertices=selected_all_vertices,
        current_vertices=current_vertices, current_edges=current_edges, current_faces=current_faces,
        operation=operation, vertex_count=vertex_count,
    )
    return item


def _parse_selection_prune_report(mesh: ParsedMesh, raw_items: object, source_indices: Sequence[int]) -> dict[str, object] | None:
    if not isinstance(raw_items, list):
        return None
    vertices: dict[int, set[int]] = {}
    edges: dict[int, set[tuple[int, int]]] = {}
    faces: dict[int, set[int]] = {}
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        submesh_index = _index(item.get("index"))
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        vertex_count = len(getattr(submesh, "vertices", ()) or ())
        face_count = len(getattr(submesh, "faces", ()) or ())
        selected_vertices = _i32_range_report_values(item, start_key="selected_vertex_start", count_key="selected_vertex_count", max_count=vertex_count)
        if selected_vertices is None:
            selected_vertices = _read_int_binary_report_payload(item.get("selected_vertices_binary"), max_count=vertex_count)
        if selected_vertices is None:
            selected_vertices = [index for index in _int_list(item.get("selected_vertices")) if 0 <= index < vertex_count]
        if selected_vertices:
            vertices[submesh_index] = set(selected_vertices)
        edge_descriptor = item.get("selected_edges_binary")
        edge_count = _index(edge_descriptor.get("count")) if isinstance(edge_descriptor, Mapping) else None
        raw_edges = _read_i32_components_binary_report_payload(edge_descriptor, expected_count=edge_count, components=2) if edge_count is not None else None
        selected_edges = {(min(left, right), max(left, right)) for left, right in (raw_edges if raw_edges is not None else _edge_list(item.get("selected_edges"))) if 0 <= left < vertex_count and 0 <= right < vertex_count and left != right}
        if selected_edges:
            edges[submesh_index] = selected_edges
        selected_faces = _i32_range_report_values(item, start_key="selected_face_start", count_key="selected_face_count", max_count=face_count)
        if selected_faces is None:
            selected_faces = _read_int_binary_report_payload(item.get("selected_faces_binary"), max_count=face_count)
        if selected_faces is None:
            selected_faces = [index for index in _int_list(item.get("selected_faces")) if 0 <= index < face_count]
        if selected_faces:
            faces[submesh_index] = set(selected_faces)
    return {"vertices_by_submesh": vertices, "edges_by_submesh": edges, "faces_by_submesh": faces, "source_indices": source_indices}


def prune_native_mesh_selection(
    mesh: ParsedMesh,
    *,
    vertices_by_submesh: Mapping[int, set[int]],
    edges_by_submesh: Mapping[int, set[tuple[int, int]]],
    faces_by_submesh: Mapping[int, set[int]],
    selected_all_vertices_by_submesh: Sequence[int] = (),
    source_indices: Sequence[int] = (),
    current_vertices_by_submesh: Mapping[int, set[int]] | None = None,
    current_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    current_faces_by_submesh: Mapping[int, set[int]] | None = None,
    current_source_indices: Sequence[int] = (),
    selection_operation: object = "replace",
    metrics_out: dict[str, float] | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    operation = _native_selection_operation(selection_operation)
    valid_sources = _combine_native_selection_sources(len(mesh.submeshes), current_source_indices, source_indices, operation)
    current_vertices_by_submesh = current_vertices_by_submesh or {}
    current_edges_by_submesh = current_edges_by_submesh or {}
    current_faces_by_submesh = current_faces_by_submesh or {}
    selected_all_sources = {index for raw in (selected_all_vertices_by_submesh or ()) if (index := _index(raw)) is not None and 0 <= index < len(mesh.submeshes)}
    target_indices = set(vertices_by_submesh) | set(edges_by_submesh) | set(faces_by_submesh) | selected_all_sources | set(current_vertices_by_submesh) | set(current_edges_by_submesh) | set(current_faces_by_submesh)
    if not target_indices:
        return _empty_pruned_selection(valid_sources)
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_selection_prune_"))
    try:
        payloads = []
        for raw_index in sorted(target_indices):
            index = _index(raw_index)
            if index is None or not 0 <= index < len(mesh.submeshes):
                continue
            item = _build_selection_prune_item(
                mesh, index, sidecar_root, binary, operation,
                vertices_by_submesh, edges_by_submesh, faces_by_submesh,
                current_vertices_by_submesh, current_edges_by_submesh, current_faces_by_submesh,
                selected_all_sources, timeout_seconds,
            )
            if item is not None:
                payloads.append(item)
        if not payloads:
            return _empty_pruned_selection(valid_sources)
        report = _run_native_mesh_core_job(binary, "selection-prune-json", {"version": 1, "backend": NATIVE_MESH_CORE_BACKEND_ID, "operation": "selection_prune", "selection_operation": operation, "submeshes": payloads}, timeout_seconds=timeout_seconds)
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    if metrics_out is not None:
        metrics_out.update(_native_report_metrics(report))
    return _parse_selection_prune_report(mesh, report.get("submeshes"), valid_sources)
