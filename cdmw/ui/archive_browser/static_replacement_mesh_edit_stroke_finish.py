"""Stroke Finish callbacks for static-replacement mesh editing."""

from __future__ import annotations

from functools import partial
from types import SimpleNamespace


def create_stroke_finish_callbacks(state: SimpleNamespace, callbacks: SimpleNamespace) -> SimpleNamespace:
    result = SimpleNamespace()
    for function in _CALLBACKS:
        function.__annotations__ = {key: value.replace("_state.", "") if isinstance(value, str) else value for key, value in function.__annotations__.items()}
        bound = partial(function, state, callbacks)
        bound.__name__ = function.__name__
        bound.__annotations__ = dict(function.__annotations__)
        setattr(result, function.__name__, bound)
    return result


def _mesh_edit_finish_stroke(_state, _callbacks, payload: object) -> None:
    stroke_id = _state._mesh_edit_stroke_id(payload)
    if stroke_id <= 0 or int(_state.mesh_edit_active_stroke.get("id", 0) or 0) != stroke_id:
        return
    tool = _state._mesh_edit_payload_choice_helper(
        payload if isinstance(payload, _state.Mapping) else {},
        "tool",
        _state.mesh_edit_active_stroke.get("tool") or _state._mesh_edit_current_tool(),
        {"move", "grab", "smooth", "inflate", "pinch", "remove", "vertex"},
    )
    if tool == "remove":
        _mesh_edit_finish_remove_stroke(_state, _callbacks, payload)
        return
    _mesh_edit_finish_geometry_stroke(_state, _callbacks, stroke_id, tool)


def _mesh_edit_finish_remove_stroke(_state, _callbacks, payload: object) -> None:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        _callbacks._mesh_edit_clear_active_stroke()
        _callbacks._refresh_mesh_edit_controls()
        return
    delete_mode = _state._mesh_edit_payload_choice_helper(
        payload if isinstance(payload, _state.Mapping) else {},
        "delete_mode",
        _state.mesh_edit_active_stroke.get("delete_mode") or _state.mesh_edit_delete_mode_combo.currentData() or "release",
        {"release", "live", "selection"},
    )
    if delete_mode == "selection":
        _callbacks._mesh_edit_pop_undo_snapshot()
        _state._pop_geometry_undo_snapshot()
        _callbacks._mesh_edit_clear_active_stroke()
        _callbacks._refresh_mesh_edit_controls()
        return
    if delete_mode == "live":
        changed = bool(_state.mesh_edit_active_stroke.get("changed"))
        if not changed:
            _callbacks._mesh_edit_pop_undo_snapshot()
            _state._pop_geometry_undo_snapshot()
            _callbacks._mesh_edit_clear_active_stroke()
            _callbacks._refresh_mesh_edit_controls()
            return
        live_submeshes = _state.mesh_edit_active_stroke.get("live_delete_submeshes", set())
        submesh_indices = _state._mesh_edit_optional_sorted_indices_helper(live_submeshes)
        compact_result = _callbacks._mesh_editor_apply_static_replacement_edit(
            _state._mesh_edit_state.replacement_mesh_for_mapping,
            "delete_loose_vertices",
            source_indices=submesh_indices,
            recompute_normals=True,
            record_history=False,
        )
        _callbacks._mesh_editor_store_result_mesh(compact_result)
        _callbacks._mesh_editor_remember_static_replacement_session_mesh()
        _callbacks._mesh_edit_disable_emptied_parts(compact_result.emptied_submesh_indices)
        _callbacks._morph_slider_mark_topology_changed(_state._mesh_edit_topology_changed_status_helper("remove_faces"))
        _callbacks._mesh_edit_clear_topology_selection()
        removed_faces = int(_state.mesh_edit_active_stroke.get("live_removed_face_count", 0) or 0)
        topology_sources = _state._mesh_edit_topology_source_indices_helper(
            live_submeshes,
            compact_result.affected_submesh_indices,
        )
        _callbacks._mesh_edit_clear_active_stroke()
        _callbacks._mesh_edit_commit_working_mesh(
            _state._mesh_edit_live_delete_status_helper(removed_faces),
            topology_source_indices=topology_sources,
            native_result=compact_result,
        )
        return
    if _state.mesh_edit_active_stroke.get("native_release_remove_selected"):
        session = _callbacks._mesh_editor_fresh_static_replacement_session() or _callbacks._mesh_editor_ensure_static_replacement_session(
            _state._mesh_edit_state.replacement_mesh_for_mapping
        )
        if not isinstance(session, _state.StaticReplacementMeshEditSession) or session.view().selection.is_empty():
            _callbacks._mesh_edit_pop_undo_snapshot()
            _state._pop_geometry_undo_snapshot()
            _callbacks._mesh_edit_clear_active_stroke()
            _callbacks._refresh_mesh_edit_controls()
            return
        result = session.apply_current_selection(
            "delete",
            remove_orphans=True,
            recompute_normals=True,
            record_history=False,
        )
    else:
        remove_faces = _state.mesh_edit_active_stroke.get("remove_faces_by_submesh", {})
        selected_faces = _state._mesh_edit_sorted_index_groups_helper(remove_faces)
        remove_vertices = _state.mesh_edit_active_stroke.get("remove_vertices_by_submesh", {})
        selected_vertices = _state._mesh_edit_sorted_index_groups_helper(remove_vertices)
        if not selected_faces and not selected_vertices:
            _callbacks._mesh_edit_pop_undo_snapshot()
            _state._pop_geometry_undo_snapshot()
            _callbacks._mesh_edit_clear_active_stroke()
            _callbacks._refresh_mesh_edit_controls()
            return
        if selected_faces:
            delete_selection = {"faces_by_submesh": selected_faces}
        else:
            delete_selection = {"vertices_by_submesh": selected_vertices}
        result = _callbacks._mesh_editor_apply_static_replacement_edit(
            _state._mesh_edit_state.replacement_mesh_for_mapping,
            "delete",
            remove_orphans=True,
            recompute_normals=True,
            record_history=False,
            **delete_selection,
        )
    if int(result.removed_face_count or 0) <= 0:
        _callbacks._mesh_edit_pop_undo_snapshot()
        _state._pop_geometry_undo_snapshot()
        _callbacks._mesh_edit_clear_active_stroke()
        _callbacks._refresh_mesh_edit_controls()
        mesh_edit_delete_faces_text = _state._mesh_edit_delete_faces_text_helper()
        _state.self.set_status_message(mesh_edit_delete_faces_text["no_brush_faces"])
        return
    _callbacks._mesh_editor_store_result_mesh(result)
    _callbacks._mesh_editor_remember_static_replacement_session_mesh()
    _callbacks._mesh_edit_disable_emptied_parts(result.emptied_submesh_indices)
    _callbacks._morph_slider_mark_topology_changed(_state._mesh_edit_topology_changed_status_helper("remove_faces"))
    _callbacks._mesh_edit_clear_topology_selection()
    _callbacks._mesh_edit_clear_active_stroke()
    _callbacks._mesh_edit_commit_working_mesh(
        _state._mesh_edit_deleted_faces_status_helper(result.removed_face_count),
        topology_source_indices=result.affected_submesh_indices,
        native_result=result,
    )
    return


def _mesh_edit_finish_geometry_stroke(
    _state, _callbacks, stroke_id: int, tool: str
) -> None:
    native_transform_stroke_started = bool(_state.mesh_edit_active_stroke.get("native_transform_stroke_started"))
    if native_transform_stroke_started and _state._mesh_edit_state.replacement_mesh_for_mapping is not None:
        try:
            if tool in {"move", "vertex"}:
                _callbacks._mesh_editor_apply_static_replacement_edit(
                    _state._mesh_edit_state.replacement_mesh_for_mapping,
                    "transform",
                    stroke_phase="end",
                    stroke_id=str(stroke_id),
                    record_history=False,
                    recompute_normals=False,
                    _require_native_history_delta=True,
                )
            elif tool == "grab":
                _callbacks._mesh_editor_apply_static_replacement_edit(
                    _state._mesh_edit_state.replacement_mesh_for_mapping,
                    "brush",
                    mode="sculpt",
                    tool="grab",
                    strength=0.0,
                    stroke_phase="end",
                    stroke_id=str(stroke_id),
                    record_history=False,
                    recompute_normals=False,
                    _require_native_history_delta=True,
                )
        except Exception as exc:
            _state.self.set_status_message(f"Native Mesh Editor stroke finish failed: {exc}", error=True)
    changed = bool(_state.mesh_edit_active_stroke.get("changed"))
    if not changed:
        _callbacks._mesh_edit_pop_active_stroke_snapshots()
        _callbacks._mesh_edit_clear_active_stroke()
        _callbacks._refresh_mesh_edit_controls()
        return
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        _callbacks._mesh_edit_clear_active_stroke()
        _callbacks._refresh_mesh_edit_controls()
        return
    changed_sources_payload = _state.mesh_edit_active_stroke.get("changed_vertices_by_submesh", {})
    changed_sources = _state._mesh_edit_mapping_keys_helper(changed_sources_payload)
    normal_sources = set(changed_sources or _state._mesh_edit_preview_source_indices())
    normal_changed_vertices_by_submesh = {}
    native_update_applied = bool(_state.mesh_edit_active_stroke.get("native_update_applied"))
    if not native_update_applied:
        try:
            from cdmw.services.mesh_workflow_service import apply_native_mesh_recalculate_normals

            native_normals = apply_native_mesh_recalculate_normals(
                _state._mesh_edit_state.replacement_mesh_for_mapping,
                normal_sources,
                return_changed_vertices=True,
            )
        except Exception as exc:
            _callbacks._record_mesh_edit_event("mesh_edit_native_stroke_normal_recalculate_exception", message=str(exc))
            native_normals = None
        if native_normals is not None:
            normal_changed_vertices_by_submesh = _callbacks._mesh_edit_changed_vertex_groups_for_live_update(native_normals or {})
        else:
            _callbacks._mesh_edit_python_normal_fallback_allowed(_state._mesh_edit_state.replacement_mesh_for_mapping, normal_sources)
    try:
        before_topology = _state.mesh_edit_active_stroke.get("before_topology")
        if before_topology is not None:
            _state.assert_mesh_topology_unchanged(before_topology, _state._mesh_edit_state.replacement_mesh_for_mapping)  # type: ignore[arg-type]
    except Exception as exc:
        snapshot = _state.mesh_edit_active_stroke.get("snapshot")
        if snapshot is not None:
            _callbacks._mesh_edit_restore_snapshot(snapshot)
        _callbacks._mesh_edit_pop_active_stroke_snapshots()
        _callbacks._mesh_edit_clear_active_stroke()
        _callbacks._refresh_mesh_edit_controls()
        _state.QMessageBox.warning(_state.dialog, _state._mesh_edit_blocked_title_helper(), str(exc))
        return
    _callbacks._mesh_edit_update_mesh_totals()
    if native_update_applied:
        _state.mesh_edit_preview_model_dirty["value"] = True
    else:
        _callbacks._morph_slider_capture_post_edit_deltas()
        _callbacks._mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
    _state.mesh_edit_revision["value"] = int(_state.mesh_edit_revision.get("value", 0) or 0) + 1
    _callbacks._mesh_edit_commit_geometry_preview_state()
    _callbacks._mesh_edit_replace_active_undo_with_native_sparse_snapshot()
    _callbacks._mesh_edit_push_active_sparse_geometry_snapshot()
    _callbacks._mesh_edit_clear_active_stroke()
    _callbacks._refresh_mesh_edit_controls()
    if native_update_applied:
        return
    if _state._alignment_d3d11_preview_active():
        _callbacks._mesh_edit_update_live_preview(
            normal_changed_vertices_by_submesh
            or _callbacks._mesh_edit_changed_vertex_groups_for_live_update(changed_sources_payload or {})
            or _state._mesh_edit_all_live_vertices_for_sources(changed_sources or _state._mesh_edit_preview_source_indices()),
            include_normals=True,
            immediate=True,
        )
    else:
        _callbacks._mesh_edit_mark_native_preview_stale(
            "Active Mesh Editor stroke finish requires native D3D11 refresh; Python preview rebuild fallback is disabled."
        )


_CALLBACKS = (
    _mesh_edit_finish_stroke,
)
