from __future__ import annotations

import os
from typing import Iterable, Mapping

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.modding.mesh_native_core import (
    apply_native_mesh_selection,
    native_mesh_core_available,
    prune_native_mesh_selection,
    record_native_mesh_core_fallback,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services.mesh_service_kernel import _mesh_count_hint
from cdmw.services.mesh_service_reports import _coerce_index


_PYTHON_MESH_SELECTION_FALLBACK_VERTEX_LIMIT = 10_000


def _command_selection(command: MeshEditCommand) -> MeshEditSelection | None:
    if command.selection is not None:
        return command.selection
    params = dict(command.params or {})
    keys = {"vertices_by_submesh", "edges_by_submesh", "faces_by_submesh", "source_indices"}
    if not any(key in params for key in keys):
        return None
    return MeshEditSelection.from_maps(
        vertices_by_submesh=params.get("vertices_by_submesh"),  # type: ignore[arg-type]
        edges_by_submesh=params.get("edges_by_submesh"),  # type: ignore[arg-type]
        faces_by_submesh=params.get("faces_by_submesh"),  # type: ignore[arg-type]
        source_indices=params.get("source_indices"),  # type: ignore[arg-type]
    )


def _apply_selection_operation(current: MeshEditSelection, incoming: MeshEditSelection, operation: object) -> MeshEditSelection:
    mode = str(operation or "replace").strip().lower()
    if mode == "replace":
        return incoming
    if mode == "extend":
        mode = "add"
    if mode == "remove":
        mode = "subtract"
    if mode not in {"add", "subtract", "toggle"}:
        return incoming
    return MeshEditSelection.from_maps(
        vertices_by_submesh=_combine_selection_map(current.vertex_map(), incoming.vertex_map(), mode),
        edges_by_submesh=_combine_selection_map(current.edge_map(), incoming.edge_map(), mode),
        faces_by_submesh=_combine_selection_map(current.face_map(), incoming.face_map(), mode),
        source_indices=_combine_selection_values(set(current.source_indices), set(incoming.source_indices), mode),
    )


def _apply_selection_operation_to_mesh(
    mesh: ParsedMesh,
    current: MeshEditSelection,
    incoming: MeshEditSelection,
    operation: object,
    *,
    stop_event: object | None = None,
    metrics_out: dict[str, float] | None = None,
) -> MeshEditSelection:
    mode = str(operation or "replace").strip().lower()
    if mode in {"grow", "shrink", "smooth"}:
        native_selection = apply_native_mesh_selection(
            mesh,
            incoming.vertex_map(),
            selected_edges_by_submesh=incoming.edge_map(),
            selected_faces_by_submesh=incoming.face_map(),
            source_indices=incoming.source_indices,
            operation=mode,
            iterations=1,
            stop_event=stop_event,  # type: ignore[arg-type]
            metrics_out=metrics_out,
        )
        if native_selection is not None:
            return MeshEditSelection.from_maps(vertices_by_submesh=native_selection)
        record_native_mesh_core_fallback(
            f"selection.{mode}.blocked",
            "Native selection edit failed; Python selection expansion fallback is disabled",
            vertex_count=sum(len(getattr(submesh, "vertices", ()) or ()) for submesh in getattr(mesh, "submeshes", ()) or ()),
            face_count=sum(len(getattr(submesh, "faces", ()) or ()) for submesh in getattr(mesh, "submeshes", ()) or ()),
        )
        return current
    native_pruned = prune_native_mesh_selection(
        mesh,
        vertices_by_submesh=incoming.vertex_map(),
        edges_by_submesh=incoming.edge_map(),
        faces_by_submesh=incoming.face_map(),
        source_indices=incoming.source_indices,
        current_vertices_by_submesh=current.vertex_map(),
        current_edges_by_submesh=current.edge_map(),
        current_faces_by_submesh=current.face_map(),
        current_source_indices=current.source_indices,
        selection_operation=operation,
        metrics_out=metrics_out,
    )
    if native_pruned is not None:
        return MeshEditSelection.from_maps(
            vertices_by_submesh=native_pruned.get("vertices_by_submesh"),  # type: ignore[arg-type]
            edges_by_submesh=native_pruned.get("edges_by_submesh"),  # type: ignore[arg-type]
            faces_by_submesh=native_pruned.get("faces_by_submesh"),  # type: ignore[arg-type]
            source_indices=native_pruned.get("source_indices"),  # type: ignore[arg-type]
        )
    if not _allow_python_selection_fallback(mesh, "selection.prune"):
        return _source_only_selection_after_operation(mesh, current, incoming, operation)
    return _prune_selection_to_mesh(mesh, _apply_selection_operation(current, incoming, operation))


def _combine_selection_map(left: dict[int, set[object]], right: dict[int, set[object]], mode: str) -> dict[int, set[object]]:
    result = {submesh: set(values) for submesh, values in left.items()}
    for submesh, values in right.items():
        result[submesh] = _combine_selection_values(result.get(submesh, set()), values, mode)
        if not result[submesh]:
            result.pop(submesh, None)
    return result


def _combine_selection_values(left: set[object], right: set[object], mode: str) -> set[object]:
    result = set(left)
    if mode == "add":
        result.update(right)
    elif mode == "subtract":
        result.difference_update(right)
    elif mode == "toggle":
        for value in right:
            if value in result:
                result.remove(value)
            else:
                result.add(value)
    return result


def _selection_after_working_mesh_replace(
    previous_mesh: ParsedMesh,
    working_mesh: ParsedMesh,
    selection: MeshEditSelection,
) -> tuple[MeshEditSelection, tuple[str, ...]]:
    if selection.is_empty():
        return MeshEditSelection(), ()
    if _mesh_topology_signature(previous_mesh) != _mesh_topology_signature(working_mesh):
        return (
            MeshEditSelection(),
            ("selection_cleared_after_external_import: topology changed; previous selection cannot be mapped safely",),
        )
    preserved = _prune_selection_to_mesh(working_mesh, selection)
    if preserved.is_empty() and not selection.is_empty():
        return (
            MeshEditSelection(),
            ("selection_cleared_after_external_import: previous selection is invalid on imported mesh",),
        )
    if preserved != selection:
        return (
            preserved,
            ("selection_pruned_after_external_import: invalid selection members were removed",),
        )
    return preserved, ()


def _mesh_topology_signature(mesh: ParsedMesh) -> tuple[tuple[int, int], ...]:
    return tuple(
        (len(tuple(submesh.vertices or ())), len(tuple(submesh.faces or ())))
        for submesh in tuple(mesh.submeshes or ())
    )


def _prune_selection_to_mesh(mesh: ParsedMesh, selection: MeshEditSelection) -> MeshEditSelection:
    native_pruned = prune_native_mesh_selection(
        mesh,
        vertices_by_submesh=selection.vertex_map(),
        edges_by_submesh=selection.edge_map(),
        faces_by_submesh=selection.face_map(),
        source_indices=selection.source_indices,
    )
    if native_pruned is not None:
        return MeshEditSelection.from_maps(
            vertices_by_submesh=native_pruned.get("vertices_by_submesh"),  # type: ignore[arg-type]
            edges_by_submesh=native_pruned.get("edges_by_submesh"),  # type: ignore[arg-type]
            faces_by_submesh=native_pruned.get("faces_by_submesh"),  # type: ignore[arg-type]
            source_indices=native_pruned.get("source_indices"),  # type: ignore[arg-type]
        )
    if not _allow_python_selection_fallback(mesh, "selection.prune"):
        return _source_only_selection_for_mesh(mesh, selection.source_indices)

    submeshes = mesh.submeshes or ()
    vertices_by_submesh: dict[int, set[int]] = {}
    edges_by_submesh: dict[int, set[tuple[int, int]]] = {}
    faces_by_submesh: dict[int, set[int]] = {}
    source_indices: set[int] = set()

    for submesh_index, vertices in selection.vertex_map().items():
        if not 0 <= submesh_index < len(submeshes):
            continue
        vertex_count = len(submeshes[submesh_index].vertices or ())
        kept = {index for index in vertices if 0 <= index < vertex_count}
        if kept:
            vertices_by_submesh[submesh_index] = kept

    for submesh_index, edges in selection.edge_map().items():
        if not 0 <= submesh_index < len(submeshes):
            continue
        kept = _valid_selected_edges_for_submesh(submeshes[submesh_index], edges)
        if kept:
            edges_by_submesh[submesh_index] = kept

    for submesh_index, faces in selection.face_map().items():
        if not 0 <= submesh_index < len(submeshes):
            continue
        submesh = submeshes[submesh_index]
        kept = {
            index
            for index in faces
            if 0 <= index < len(submesh.faces or ())
            and len(_valid_face_vertices(submesh.faces[index], len(submesh.vertices or ()))) == 3
        }
        if kept:
            faces_by_submesh[submesh_index] = kept

    for index in selection.source_indices:
        if 0 <= index < len(submeshes):
            source_indices.add(index)

    return MeshEditSelection.from_maps(
        vertices_by_submesh=vertices_by_submesh,
        edges_by_submesh=edges_by_submesh,
        faces_by_submesh=faces_by_submesh,
        source_indices=source_indices,
    )


def _source_only_selection_after_operation(
    mesh: ParsedMesh,
    current: MeshEditSelection,
    incoming: MeshEditSelection,
    operation: object,
) -> MeshEditSelection:
    mode = str(operation or "replace").strip().lower()
    if mode == "extend":
        mode = "add"
    if mode == "remove":
        mode = "subtract"
    if mode not in {"replace", "add", "subtract", "toggle"}:
        mode = "replace"
    source_indices = (
        set(incoming.source_indices)
        if mode == "replace"
        else _combine_selection_values(set(current.source_indices), set(incoming.source_indices), mode)
    )
    return _source_only_selection_for_mesh(mesh, source_indices)


def _source_only_selection_for_mesh(mesh: ParsedMesh, source_indices: Iterable[int]) -> MeshEditSelection:
    submesh_count = len(mesh.submeshes or ())
    valid_sources: set[int] = set()
    for raw_index in source_indices:
        index = _coerce_index(raw_index)
        if index is not None and 0 <= index < submesh_count:
            valid_sources.add(index)
    return MeshEditSelection.from_maps(source_indices=tuple(sorted(valid_sources)))


def _valid_selected_edges_for_submesh(submesh: SubMesh, edges: set[tuple[int, int]]) -> set[tuple[int, int]]:
    vertex_count = len(submesh.vertices or ())
    selected = {
        _edge_key(a, b)
        for a, b in edges
        if 0 <= a < vertex_count and 0 <= b < vertex_count and a != b
    }
    if not selected:
        return set()
    if not submesh.faces:
        return selected
    return selected & _existing_face_edges(submesh)


def _existing_face_edges(submesh: SubMesh) -> set[tuple[int, int]]:
    vertex_count = len(submesh.vertices or ())
    edges: set[tuple[int, int]] = set()
    for face in submesh.faces or ():
        indices = _valid_face_vertices(face, vertex_count)
        if len(indices) == 3:
            a, b, c = indices
            edges.update((_edge_key(a, b), _edge_key(b, c), _edge_key(c, a)))
    return edges


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


def _edge_key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a <= b else (b, a)


def _allow_python_selection_fallback(mesh: ParsedMesh, operation: str) -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip() or not native_mesh_core_available():
        return True
    _record_blocked_python_selection_fallback(
        mesh,
        operation,
        "Python mesh selection fallback blocked while native mesh core is available",
    )
    return False


def _record_blocked_python_selection_fallback(mesh: ParsedMesh, operation: str, reason: str) -> None:
    record_native_mesh_core_fallback(
        f"{operation}.blocked",
        reason,
        vertex_count=_mesh_count_hint(mesh, "total_vertices"),
        face_count=_mesh_count_hint(mesh, "total_faces"),
    )


def _selected_skin_weight_vertex_count(
    mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]],
    selected_all_submeshes: Iterable[int],
) -> int:
    limit = _PYTHON_MESH_SELECTION_FALLBACK_VERTEX_LIMIT
    selected = 0
    selected_all = {index for index in (_coerce_index(value) for value in selected_all_submeshes) if index is not None}
    for submesh_index in selected_all:
        if 0 <= submesh_index < len(mesh.submeshes or ()):
            selected += len(mesh.submeshes[submesh_index].vertices or ())
            if selected > limit:
                return selected
    for vertex_indices in selected_vertices_by_submesh.values():
        try:
            selected += len(vertex_indices)  # type: ignore[arg-type]
        except TypeError:
            return limit + 1
        if selected > limit:
            return selected
    return selected
