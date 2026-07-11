"""Topology callbacks for static-replacement mesh editing."""

from __future__ import annotations

from functools import partial
from types import SimpleNamespace


def create_topology_callbacks(state: SimpleNamespace, callbacks: SimpleNamespace) -> SimpleNamespace:
    result = SimpleNamespace()
    for function in _CALLBACKS:
        function.__annotations__ = {key: value.replace("_state.", "") if isinstance(value, str) else value for key, value in function.__annotations__.items()}
        bound = partial(function, state, callbacks)
        bound.__name__ = function.__name__
        bound.__annotations__ = dict(function.__annotations__)
        setattr(result, function.__name__, bound)
    return result


def _mesh_edit_cancel_stroke(_state, _callbacks, payload: object) -> None:
    if not _state.mesh_edit_active_stroke:
        return
    stroke_id = _state._mesh_edit_stroke_id(payload)
    if stroke_id > 0 and int(_state.mesh_edit_active_stroke.get("id", 0) or 0) != stroke_id:
        return
    if not _callbacks._mesh_edit_restore_native_stroke_delta():
        snapshot = _state.mesh_edit_active_stroke.get("snapshot")
        if snapshot is not None:
            _callbacks._mesh_edit_restore_snapshot(snapshot)
    _callbacks._mesh_edit_pop_active_stroke_snapshots()
    _callbacks._mesh_edit_clear_active_stroke()
    _callbacks._refresh_mesh_edit_controls()

def _mesh_edit_commit_delete_result(_state, _callbacks, result: object) -> None:
    _callbacks._mesh_editor_store_result_mesh(result)
    if int(result.removed_face_count or 0) <= 0:
        _callbacks._mesh_edit_pop_undo_snapshot()
        _state._pop_geometry_undo_snapshot()
        _callbacks._refresh_mesh_edit_controls()
        mesh_edit_delete_faces_text = _state._mesh_edit_delete_faces_text_helper()
        _state.self.set_status_message(mesh_edit_delete_faces_text["no_selected_vertices"])
        return
    _callbacks._mesh_edit_disable_emptied_parts(result.emptied_submesh_indices)
    _callbacks._morph_slider_mark_topology_changed(_state._mesh_edit_topology_changed_status_helper("remove_faces"))
    _callbacks._mesh_edit_clear_topology_selection()
    native_update_applied = _callbacks._mesh_editor_apply_result_native_update(result)
    _callbacks._mesh_edit_update_mesh_totals()
    if not native_update_applied:
        _callbacks._mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
    _state.mesh_edit_revision["value"] = int(_state.mesh_edit_revision.get("value", 0) or 0) + 1
    _callbacks._mesh_edit_commit_geometry_preview_state()
    _state._refresh_source_tree_selection_state()
    _state._refresh_source_assignment_columns()
    _callbacks._refresh_mesh_edit_controls()
    if not native_update_applied:
        _callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild(result.affected_submesh_indices)
    _state.self.set_status_message(_state._mesh_edit_deleted_selection_status_helper(result.removed_face_count))

def _mesh_edit_delete_selected_faces(_state, _callbacks, ) -> None:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return
    can_edit, reason = _callbacks._mesh_edit_can_edit_scope()
    if not can_edit:
        _state.QMessageBox.information(_state.dialog, _state._mesh_edit_dialog_title_helper(), reason)
        return
    if _state._morph_slider_has_nonzero_values():
        mesh_edit_delete_faces_text = _state._mesh_edit_delete_faces_text_helper()
        _state.QMessageBox.information(_state.dialog, _state._mesh_edit_dialog_title_helper(), mesh_edit_delete_faces_text["morph_blocker"])
        return
    allowed_indices = set(_state._mesh_edit_allowed_source_indices())
    selected_faces = _state._mesh_edit_sorted_index_groups_helper(
        _state.mesh_edit_selected_faces_by_submesh,
        allowed_source_indices=allowed_indices,
        mesh=_state._mesh_edit_state.replacement_mesh_for_mapping,
    )
    selected_vertices = _state._mesh_edit_sorted_index_groups_helper(
        _state.mesh_edit_selected_vertices_by_submesh,
        allowed_source_indices=allowed_indices,
        mesh=_state._mesh_edit_state.replacement_mesh_for_mapping,
    )
    selected_sources = _callbacks._mesh_editor_action_source_indices()
    selected_edges = _callbacks._mesh_editor_edge_selection(selected_vertices, selected_faces)
    if not selected_faces and not selected_vertices and not selected_edges and not selected_sources:
        mesh_edit_delete_faces_text = _state._mesh_edit_delete_faces_text_helper()
        _state.QMessageBox.information(_state.dialog, _state._mesh_edit_dialog_title_helper(), mesh_edit_delete_faces_text["select_faces"])
        return
    params = {"remove_orphans": True, "recompute_normals": True}
    if _callbacks._mesh_edit_start_topology_worker(
        "delete",
        action_text="Delete Selection",
        selected_vertices=selected_vertices,
        selected_faces=selected_faces,
        selected_edges=selected_edges,
        selected_source_indices=selected_sources,
        params=params,
        commit_callback=_callbacks._mesh_edit_commit_delete_result,
    ):
        return
    _callbacks._mesh_edit_record_snapshot()
    result = _callbacks._mesh_editor_apply_static_replacement_edit(
        _state._mesh_edit_state.replacement_mesh_for_mapping,
        "delete",
        edges_by_submesh=selected_edges,
        faces_by_submesh=selected_faces,
        vertices_by_submesh=selected_vertices,
        source_indices=selected_sources,
        **params,
    )
    _callbacks._mesh_edit_commit_delete_result(result)

def _mesh_edit_commit_subdivide_result(_state, _callbacks, result: object, *, refine_smooth: bool = False) -> None:
    _callbacks._mesh_editor_store_result_mesh(result)
    if not result.affected_submesh_indices:
        _callbacks._mesh_edit_pop_undo_snapshot()
        _state._pop_geometry_undo_snapshot()
        _callbacks._refresh_mesh_edit_controls()
        mesh_edit_subdivide_text = _state._mesh_edit_subdivide_text_helper()
        _state.self.set_status_message(mesh_edit_subdivide_text["no_selected_vertices"])
        return
    status_key = "refine_smooth_selection" if refine_smooth else "subdivide_selection"
    _callbacks._morph_slider_mark_topology_changed(_state._mesh_edit_topology_changed_status_helper(status_key))
    _state.mesh_edit_selected_vertices_by_submesh.clear()
    _state.mesh_edit_selected_edges_by_submesh.clear()
    _state.mesh_edit_selected_faces_by_submesh.clear()
    _state.mesh_edit_selected_source_indices.clear()
    _state.mesh_edit_selected_vertices_by_submesh.update(
        _state._mesh_edit_index_groups_as_sets_helper(result.changed_vertices_by_submesh or {})
    )
    native_update_applied = _callbacks._mesh_editor_apply_result_native_update(result)
    _callbacks._mesh_edit_update_mesh_totals()
    if not native_update_applied:
        _callbacks._mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
    _state.mesh_edit_revision["value"] = int(_state.mesh_edit_revision.get("value", 0) or 0) + 1
    _callbacks._mesh_edit_commit_geometry_preview_state()
    _state._refresh_source_tree_selection_state()
    _state._refresh_source_assignment_columns()
    _callbacks._refresh_mesh_edit_controls()
    _callbacks._mesh_edit_sync_d3d11_selection()
    if not native_update_applied:
        _callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild(result.affected_submesh_indices)
    status = (
        _state._mesh_edit_refined_selection_status_helper(result.added_face_count)
        if refine_smooth and callable(_state._mesh_edit_refined_selection_status_helper)
        else _state._mesh_edit_subdivided_selection_status_helper(result.added_face_count)
    )
    _state.self.set_status_message(status)

def _mesh_edit_subdivide_selection(_state, _callbacks, *, refine_smooth: bool = False) -> None:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return
    can_edit, reason = _callbacks._mesh_edit_can_edit_scope()
    if not can_edit:
        _state.QMessageBox.information(_state.dialog, _state._mesh_edit_dialog_title_helper(), reason)
        return
    if _state._morph_slider_has_nonzero_values():
        mesh_edit_subdivide_text = _state._mesh_edit_subdivide_text_helper()
        _state.QMessageBox.information(_state.dialog, _state._mesh_edit_dialog_title_helper(), mesh_edit_subdivide_text["morph_blocker"])
        return
    allowed_indices = set(_state._mesh_edit_allowed_source_indices())
    selected_vertices = _state._mesh_edit_sorted_index_groups_helper(
        _state.mesh_edit_selected_vertices_by_submesh,
        allowed_source_indices=allowed_indices,
        mesh=_state._mesh_edit_state.replacement_mesh_for_mapping,
    )
    selected_faces = _state._mesh_edit_sorted_index_groups_helper(
        _state.mesh_edit_selected_faces_by_submesh,
        allowed_source_indices=allowed_indices,
        mesh=_state._mesh_edit_state.replacement_mesh_for_mapping,
    )
    selected_sources = _callbacks._mesh_editor_action_source_indices()
    selected_edges = _callbacks._mesh_editor_edge_selection(selected_vertices, selected_faces)
    if not selected_vertices and not selected_faces and not selected_edges and not selected_sources:
        mesh_edit_subdivide_text = _state._mesh_edit_subdivide_text_helper()
        _state.QMessageBox.information(_state.dialog, _state._mesh_edit_dialog_title_helper(), mesh_edit_subdivide_text["select_vertices"])
        return
    params = {
        "max_faces_per_submesh": 512,
        "recompute_normals": True,
        "smooth_iterations": int(_state.mesh_edit_iterations_spin.value()) if refine_smooth else 2,
        "smooth_strength": (float(_state.mesh_edit_strength_spin.value()) / 100.0) if refine_smooth else 0.5,
    }
    if _callbacks._mesh_edit_start_topology_worker(
        "refine_smooth" if refine_smooth else "subdivide",
        action_text="Refine Smooth" if refine_smooth else "Subdivide",
        selected_vertices=selected_vertices,
        selected_faces=selected_faces,
        selected_edges=selected_edges,
        selected_source_indices=selected_sources,
        params=params,
        commit_callback=lambda result, refine=refine_smooth: _callbacks._mesh_edit_commit_subdivide_result(
            result,
            refine_smooth=refine,
        ),
    ):
        return
    _callbacks._mesh_edit_record_snapshot()
    result = _callbacks._mesh_editor_apply_static_replacement_edit(
        _state._mesh_edit_state.replacement_mesh_for_mapping,
        "refine_smooth" if refine_smooth else "subdivide",
        vertices_by_submesh=selected_vertices,
        edges_by_submesh=selected_edges,
        faces_by_submesh=selected_faces,
        source_indices=selected_sources,
        **params,
    )
    _callbacks._mesh_edit_commit_subdivide_result(result, refine_smooth=refine_smooth)

def _mesh_edit_commit_split_result(_state, _callbacks, result: object) -> None:
    split_text = _state._mesh_edit_split_text_helper()
    _callbacks._mesh_editor_store_result_mesh(result)
    if int(getattr(result, "moved_face_count", 0) or 0) <= 0 or int(getattr(result, "new_submesh_index", -1)) < 0:
        _callbacks._mesh_edit_pop_undo_snapshot()
        _state._pop_geometry_undo_snapshot()
        _callbacks._refresh_mesh_edit_controls()
        _state.self.set_status_message(split_text["no_selected_faces"])
        return
    source_index = int(result.source_submesh_index)
    new_source_index = int(result.new_submesh_index)
    if hasattr(_state.appended_source_indices, "add"):
        _state.appended_source_indices.add(new_source_index)
    _state.selected_source_part["index"] = new_source_index
    _state.source_geometry_revision["value"] = int(_state.source_geometry_revision.get("value", 0) or 0) + 1
    _callbacks._morph_slider_mark_topology_changed(_state._mesh_edit_topology_changed_status_helper("split_selection"))
    _callbacks._mesh_edit_clear_topology_selection()
    if _state._alignment_d3d11_preview_active():
        _state.alignment_d3d11_preview_host.clear_mesh_edit_vertex_selection()
    native_update_applied = _callbacks._mesh_editor_apply_result_native_update(result)
    _callbacks._mesh_edit_update_mesh_totals()
    if not native_update_applied:
        _callbacks._mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
    _state.mesh_edit_revision["value"] = int(_state.mesh_edit_revision.get("value", 0) or 0) + 1
    _callbacks._mesh_edit_commit_geometry_preview_state()
    if callable(_state._rebuild_source_part_widgets):
        _state._rebuild_source_part_widgets()
    if _state.source_tree is not None and isinstance(_state.source_items_by_index, dict):
        item = _state.source_items_by_index.get(new_source_index)
        if item is not None:
            blocked = _state.source_tree.blockSignals(True)
            try:
                _state.source_tree.clearSelection()
                item.setSelected(True)
                _state.source_tree.setCurrentItem(item)
            finally:
                _state.source_tree.blockSignals(blocked)
            _state.source_tree.scrollToItem(item)
    _state._refresh_source_tree_selection_state()
    _state._refresh_source_assignment_columns()
    _callbacks._refresh_mesh_edit_controls()
    if not native_update_applied:
        _callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild((source_index, new_source_index))
    _state.self.set_status_message(_state._mesh_edit_split_selection_status_helper(result.moved_face_count))

def _mesh_edit_split_selection_to_part(_state, _callbacks, ) -> None:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return
    can_edit, reason = _callbacks._mesh_edit_can_edit_scope()
    if not can_edit:
        _state.QMessageBox.information(_state.dialog, _state._mesh_edit_dialog_title_helper(), reason)
        return
    split_text = _state._mesh_edit_split_text_helper()
    if _state._morph_slider_has_nonzero_values():
        _state.QMessageBox.information(_state.dialog, _state._mesh_edit_dialog_title_helper(), split_text["morph_blocker"])
        return
    allowed_indices = set(_state._mesh_edit_allowed_source_indices())
    selected_faces = _state._mesh_edit_sorted_index_groups_helper(
        _state.mesh_edit_selected_faces_by_submesh,
        allowed_source_indices=allowed_indices,
        mesh=_state._mesh_edit_state.replacement_mesh_for_mapping,
    )
    selected_vertices = _state._mesh_edit_sorted_index_groups_helper(
        _state.mesh_edit_selected_vertices_by_submesh,
        allowed_source_indices=allowed_indices,
        mesh=_state._mesh_edit_state.replacement_mesh_for_mapping,
    )
    selected_sources = _callbacks._mesh_editor_action_source_indices()
    selected_edges = _callbacks._mesh_editor_edge_selection(selected_vertices, selected_faces)
    if not selected_faces and not selected_vertices and not selected_edges and not selected_sources:
        _state.QMessageBox.information(_state.dialog, _state._mesh_edit_dialog_title_helper(), split_text["select_faces"])
        return
    if _callbacks._mesh_edit_start_topology_worker(
        "split",
        action_text="Split Selection To Part",
        selected_vertices=selected_vertices,
        selected_faces=selected_faces,
        selected_edges=selected_edges,
        selected_source_indices=selected_sources,
        params={"recompute_normals": True},
        commit_callback=_callbacks._mesh_edit_commit_split_result,
    ):
        return
    _callbacks._mesh_edit_record_snapshot()
    try:
        result = _callbacks._mesh_editor_apply_static_replacement_edit(
            _state._mesh_edit_state.replacement_mesh_for_mapping,
            "split",
            faces_by_submesh=selected_faces,
            edges_by_submesh=selected_edges,
            vertices_by_submesh=selected_vertices,
            source_indices=selected_sources,
            recompute_normals=True,
        )
    except ValueError as exc:
        _callbacks._mesh_edit_pop_undo_snapshot()
        _state._pop_geometry_undo_snapshot()
        _callbacks._refresh_mesh_edit_controls()
        _state.QMessageBox.information(_state.dialog, _state._mesh_edit_dialog_title_helper(), split_text.get("multiple_parts", str(exc)))
        return
    _callbacks._mesh_edit_commit_split_result(result)


_CALLBACKS = (
    _mesh_edit_cancel_stroke,
    _mesh_edit_commit_delete_result,
    _mesh_edit_delete_selected_faces,
    _mesh_edit_commit_subdivide_result,
    _mesh_edit_subdivide_selection,
    _mesh_edit_commit_split_result,
    _mesh_edit_split_selection_to_part,
)
