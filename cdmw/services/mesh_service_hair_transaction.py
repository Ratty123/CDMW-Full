"""Atomic, same-topology Hair updates without copying materials or skin records.

The caller validates the hair state and finite vertex patches. Only those two
channels are writable here. Topology, UV, material and output-layout changes
continue through the complete replacement validator.
"""
from __future__ import annotations

import copy
from dataclasses import replace

from cdmw.modding.mesh_totals import refresh_mesh_totals
from cdmw.services.mesh_service_state import _MeshHairVertexDelta, _MeshHistorySnapshot
from cdmw.services.mesh_service_history import (
    _history_snapshot_retained_bytes, _history_stack_retained_bytes,
    _dispose_history_snapshot_without_state_failure,
)


def _capture(part, index, vertices):
    return _MeshHairVertexDelta(
        index, tuple(vertices), tuple(tuple(part.vertices[v]) for v in vertices),
        tuple(tuple(part.normals[v]) for v in vertices),
        tuple(tuple(row) for row in part.tangents),
        tuple(getattr(part, "tangent_signs", ()) or ()),
        copy.deepcopy(getattr(part, "tangent_face_corner_report", None)),
    )


def restore_hair_vertices(mesh, deltas):
    """Prepare every reciprocal before installing any channel, including normals."""
    reciprocal, prepared = [], []
    for delta in deltas:
        if not 0 <= delta.submesh_index < len(mesh.submeshes):
            raise ValueError("Hair history refers to a missing part.")
        part = mesh.submeshes[delta.submesh_index]
        if (len(delta.vertex_indices) != len(delta.positions) or len(delta.positions) != len(delta.normals)
                or any(not 0 <= v < min(len(part.vertices), len(part.normals)) for v in delta.vertex_indices)):
            raise ValueError("Hair history no longer matches its geometry.")
        reciprocal.append(_capture(part, delta.submesh_index, delta.vertex_indices))
        updated = copy.copy(part)
        updated.vertices, updated.normals = list(part.vertices), list(part.normals)
        for vertex, position, normal in zip(delta.vertex_indices, delta.positions, delta.normals, strict=True):
            updated.vertices[vertex], updated.normals[vertex] = position, normal
        updated.tangents, updated.tangent_signs = list(delta.tangents), list(delta.tangent_signs)
        if delta.tangent_report is not None:
            updated.tangent_face_corner_report = copy.deepcopy(delta.tangent_report)
        elif hasattr(updated, "tangent_face_corner_report"):
            delattr(updated, "tangent_face_corner_report")
        prepared.append((delta.submesh_index, updated))
    _install_parts(mesh, prepared)
    return tuple(reciprocal)


def _install_parts(mesh, prepared):
    for index, part in prepared:
        mesh.submeshes[index] = part
        if mesh.lod_levels:
            mesh.lod_levels[0][index] = part
    refresh_mesh_totals(mesh)


def commit_hair_vertices(authoring, snapshot, state, new, old, updates, label, stop_event):
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    session = service._session(sid)
    owned = {group["part"] for group in new["groups"]}
    previous_groups = old["groups"]
    if {(g["id"], g["part"], g["mode"]) for g in new["groups"]} != {
        (g["id"], g["part"], g["mode"]) for g in previous_groups
    }:
        raise ValueError("Changing hair part ownership requires complete geometry publication.")
    for binding in new["bindings"]:
        if binding["part"] >= len(snapshot.mesh.submeshes) or binding["vertex"] >= len(snapshot.mesh.submeshes[binding["part"]].vertices):
            raise ValueError("Hair binding refers to removed geometry.")
    for lock in new["locks"]:
        if lock["part"] >= len(snapshot.mesh.submeshes) or any(v >= len(snapshot.mesh.submeshes[lock["part"]].vertices) for v in lock["vertices"]):
            raise ValueError("Hair lock refers to removed geometry.")
    deltas, prepared = [], []
    for index, (vertices, positions, normals) in updates.items():
        if index not in owned:
            raise ValueError("Hair transaction changed an unassigned part.")
        if not vertices:
            continue
        original = snapshot.mesh.submeshes[index]
        deltas.append(_capture(original, index, vertices))
        part = copy.copy(original)
        part.vertices, part.normals = list(original.vertices), list(original.normals)
        for vertex, position, normal in zip(vertices, positions, normals, strict=True):
            part.vertices[vertex], part.normals[vertex] = tuple(position), tuple(normal)
        part.tangents, part.tangent_signs = [], []
        if hasattr(part, "tangent_face_corner_report"):
            delattr(part, "tangent_face_corner_report")
        prepared.append((index, part))
    changed = dict(prepared)
    replacement = replace(snapshot.replacement_state,
        revision=snapshot.replacement_state.revision + 1,
        parts=tuple(replace(p, import_positions=tuple(changed[p.target_index].vertices),
                            import_normals=tuple(changed[p.target_index].normals))
                    if p.target_index in changed else p for p in snapshot.replacement_state.parts))
    with session.export_lock:
        if (session.closed or session.revision != snapshot.mesh_revision or session.hair_state is not snapshot.hair_state
                or session.native_editor_mesh_dirty or session.native_editor_session_ready):
            raise ValueError("Hair edit became stale before publication.")
        marker = _MeshHistorySnapshot(
            mesh=None, mode=session.mode, selection=session.selection,
            edit_operations=tuple(session.edit_operations), hair_vertex_deltas=tuple(deltas),
            history_action="hair_groom", history_label=label, selection_only=not deltas,
            object_transform=session.object_transform,
            replacement_state=session.replacement_state, restore_replacement_state=True,
            hair_state=session.hair_state, restore_hair_state=True,
        )
        marker.retained_bytes = _history_snapshot_retained_bytes(marker)
        after = replace(marker, hair_state=state, replacement_state=replacement, retained_bytes=0)
        # The reciprocal has the same number of coordinates and no more tangent
        # data. Count the changed immutable states too, before accepting the edit.
        after_bytes = _history_snapshot_retained_bytes(after)
        limit = max(0, int(service.max_history_bytes))
        if max(marker.retained_bytes, after_bytes) > limit:
            raise ValueError("Hair edit exceeds the reversible history memory limit.")
        next_undo = [*session.undo_stack, marker]
        discarded = list(session.redo_stack)
        while len(next_undo) > max(1, int(service.max_history)) or _history_stack_retained_bytes(next_undo) > limit:
            discarded.append(next_undo.pop(0))
        authoring._raise_if_cancelled(stop_event)
        # Build the new containers first; shared unmodified parts remain live
        # only in the current mesh, never retained as a history snapshot.
        candidate = copy.copy(session.working_mesh)
        candidate.submeshes = list(candidate.submeshes)
        candidate.lod_levels = [candidate.submeshes, *candidate.lod_levels[1:]] if candidate.lod_levels else []
        _install_parts(candidate, prepared)
        checkpoint = (session.working_mesh, session.replacement_state, session.hair_state,
                      session.undo_stack, session.redo_stack, session.revision)
        try:
            _publish(session, candidate, replacement, state, next_undo)
        except Exception:
            (session.working_mesh, session.replacement_state, session.hair_state,
             session.undo_stack, session.redo_stack, session.revision) = checkpoint
            raise
    for old in discarded:
        _dispose_history_snapshot_without_state_failure(old)
    try:
        service._schedule_mesh_layer_autosave(session)
    except Exception as exc:
        session.mesh_layer_autosave_error = str(exc)


def _publish(session, mesh, replacement, state, undo):
    session.working_mesh = mesh
    session.replacement_state = replacement
    session.hair_state = state
    session.undo_stack, session.redo_stack = undo, []
    session.revision += 1
