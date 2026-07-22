"""Controls History callbacks for static-replacement mesh editing."""

from __future__ import annotations

from functools import partial
from types import SimpleNamespace


def create_controls_history_callbacks(state: SimpleNamespace, callbacks: SimpleNamespace) -> SimpleNamespace:
    result = SimpleNamespace()
    for function in _CALLBACKS:
        function.__annotations__ = {key: value.replace("_state.", "") if isinstance(value, str) else value for key, value in function.__annotations__.items()}
        bound = partial(function, state, callbacks)
        bound.__name__ = function.__name__
        bound.__annotations__ = dict(function.__annotations__)
        setattr(result, function.__name__, bound)
    return result


def _alignment_d3d11_process_active(_state, _callbacks, ) -> bool:
    process = _state.alignment_d3d11_state.get("process")
    state = getattr(process, "state", None)
    if not callable(state):
        return False
    try:
        process_state = state()
    except (AttributeError, RuntimeError, TypeError):
        return False
    try:
        return int(process_state) != 0
    except (TypeError, ValueError):
        text = str(process_state).strip().lower().replace("_", "")
        return text not in {"0", "notrunning", "processstate.notrunning", "qprocess.processstate.notrunning"}

def _embedded_dotnet_parent_hwnd(_state, _callbacks, ) -> int:
    win_id = getattr(_state.alignment_d3d11_preview_host, "winId", None)
    if not callable(win_id):
        return 0
    try:
        return int(win_id())
    except (RuntimeError, TypeError, ValueError):
        return 0

def _mesh_edit_control_runtime_state(_state, _callbacks):
    topology_busy = _callbacks._mesh_edit_worker_active()
    can_edit, reason = _callbacks._mesh_edit_can_edit_scope()
    dotnet_state = str(getattr(_state.dialog, "_mesh_editor_embedded_dotnet_state", "") or "").strip().lower()
    dotnet_active = bool(getattr(_state.dialog, "_mesh_editor_embedded_dotnet_active", False))
    dotnet_owns_edit_surface = bool(_state.mesh_edit_enabled_checkbox.isChecked())
    _state.mesh_edit_group.setEnabled(_state.mesh_edit_supported)
    set_toolbar_visible = getattr(_state.classic_mesh_edit_toolbar, "setVisible", None)
    classic_toolbar_visible = bool(
        _state.mesh_edit_supported
        and _state.mesh_edit_enabled_checkbox.isChecked()
        and not dotnet_owns_edit_surface
    )
    if callable(set_toolbar_visible):
        set_toolbar_visible(classic_toolbar_visible)
    classic_toolbar_enabled = bool(
        classic_toolbar_visible and dotnet_state not in {"launching", "closing"}
    )
    set_toolbar_enabled = getattr(_state.classic_mesh_edit_toolbar, "setEnabled", None)
    if callable(set_toolbar_enabled):
        set_toolbar_enabled(classic_toolbar_enabled)
    set_embedded_controls_visible = getattr(
        _state.dialog, "_mesh_editor_embedded_set_controls_visible", None
    )
    if callable(set_embedded_controls_visible):
        set_embedded_controls_visible(
            bool(
                _state.mesh_edit_supported
                and _state.mesh_edit_enabled_checkbox.isChecked()
                and not dotnet_owns_edit_surface
            )
        )
    legacy_preview_rows_visible = not dotnet_owns_edit_surface
    for row in getattr(_state.dialog, "_mesh_editor_legacy_preview_rows", ()):
        set_row_visible = getattr(row, "setVisible", None)
        if callable(set_row_visible):
            set_row_visible(legacy_preview_rows_visible)
    toolbar_signature = (
        dotnet_state,
        dotnet_active,
        bool(_state.mesh_edit_enabled_checkbox.isChecked()),
        classic_toolbar_visible,
        classic_toolbar_enabled,
        legacy_preview_rows_visible,
        _callbacks._alignment_d3d11_process_active(),
    )
    if _state.dialog is not None and getattr(
        _state.dialog, "_mesh_editor_embedded_toolbar_ownership", None
    ) != toolbar_signature:
        setattr(_state.dialog, "_mesh_editor_embedded_toolbar_ownership", toolbar_signature)
        _callbacks._record_mesh_edit_event(
            "mesh_edit_dotnet_toolbar_ownership",
            dotnet_state=dotnet_state,
            dotnet_active=dotnet_active,
            dotnet_enabled=bool(
                getattr(_state.dialog, "_mesh_editor_use_embedded_dotnet_viewport", False)
            ),
            dotnet_available=bool(getattr(_state.dialog, "_mesh_editor_dotnet_available", False)),
            parent_hwnd=_callbacks._embedded_dotnet_parent_hwnd(),
            classic_toolbar_visible=classic_toolbar_visible,
            classic_toolbar_enabled=classic_toolbar_enabled,
            legacy_preview_rows_visible=legacy_preview_rows_visible,
            dotnet_vortice_process_active=_callbacks._alignment_d3d11_process_active(),
        )
    _state.mesh_edit_enabled_checkbox.setEnabled(_state.mesh_edit_supported and not topology_busy)
    if not _state.mesh_edit_supported:
        _state.mesh_edit_enabled_checkbox.blockSignals(True)
        _state.mesh_edit_enabled_checkbox.setChecked(False)
        _state.mesh_edit_enabled_checkbox.blockSignals(False)
    return topology_busy, can_edit, reason

def _refresh_mesh_edit_controls(_state, _callbacks, ) -> None:
    _callbacks._refresh_mesh_edit_part_combo()
    allowed_indices = set(_state._mesh_edit_allowed_source_indices())
    _state.mesh_edit_selected_source_indices.intersection_update(allowed_indices)
    pruned_selected_vertices = _state._mesh_edit_pruned_index_groups_helper(
        _state.mesh_edit_selected_vertices_by_submesh,
        allowed_indices,
    )
    _state.mesh_edit_selected_vertices_by_submesh.clear()
    _state.mesh_edit_selected_vertices_by_submesh.update(pruned_selected_vertices)
    topology_busy, can_edit, reason = _mesh_edit_control_runtime_state(_state, _callbacks)
    editing_requested = _state._mesh_edit_editing_requested_helper(
        checkbox_checked=bool(_state.mesh_edit_enabled_checkbox.isChecked()),
        mesh_edit_supported=_state.mesh_edit_supported,
        mesh_edit_tab_active=_state._mesh_edit_tab_active(),
    )
    editing_active = _state._mesh_edit_editing_active_helper(
        editing_requested=editing_requested,
        can_edit=can_edit,
    ) and not topology_busy
    current_tool = _state._mesh_edit_current_tool()
    selected_count = _state._mesh_edit_index_group_count_helper(_state.mesh_edit_selected_vertices_by_submesh)
    selected_count += _callbacks._mesh_edit_selected_source_vertex_count(allowed_indices=allowed_indices)
    selected_face_count = _state._mesh_edit_index_group_count_helper(_state.mesh_edit_selected_faces_by_submesh)
    selected_edge_count = _callbacks._mesh_editor_selected_edge_count()
    selected_element_count = selected_count + selected_face_count + selected_edge_count
    tool_context = _state._mesh_edit_tool_context_helper(
        current_tool,
        _state._mesh_edit_selection_mode(),
        selected_count,
        editing_active=editing_active,
    )
    sculpt_tool = bool(tool_context["sculpt_tool"])
    remove_tool = bool(tool_context["remove_tool"])
    select_tool = bool(tool_context["select_tool"])
    brush_selection_tool = bool(tool_context["brush_selection_tool"])
    vertex_selection_active = bool(tool_context["selection_active"])
    selection_active = bool(editing_active and selected_element_count > 0)
    selection_actions_visible = bool(select_tool or selected_element_count > 0)
    smooth_tool = bool(tool_context["smooth_tool"])

    def _set_mesh_edit_row_visible(row_key: str, visible: bool) -> None:
        row = _state.mesh_edit_field_rows.get(str(row_key))
        if row is None:
            return
        label, widget = row
        label.setVisible(bool(visible))
        widget.setVisible(bool(visible))

    for tool, button in _state.mesh_edit_tool_buttons.items():
        button.setChecked(tool == current_tool)
    for widget in (
        _state.mesh_edit_scope_combo,
        _state.mesh_edit_part_combo,
        _state.mesh_edit_tool_palette,
        _state.mesh_edit_show_vertices_checkbox,
    ):
        widget.setEnabled(editing_requested and not topology_busy)
    _state.mesh_edit_part_combo.setEnabled(editing_requested and not topology_busy and _state._mesh_edit_scope_mode() == "selected")
    _set_mesh_edit_row_visible("scope", True)
    _set_mesh_edit_row_visible("part", True)
    _set_mesh_edit_row_visible("radius", sculpt_tool or remove_tool or brush_selection_tool)
    _set_mesh_edit_row_visible("strength", sculpt_tool)
    _set_mesh_edit_row_visible("falloff", sculpt_tool)
    _set_mesh_edit_row_visible("iterations", smooth_tool)
    _set_mesh_edit_row_visible("selection", select_tool)
    _set_mesh_edit_row_visible("depth", select_tool)
    _state.mesh_edit_delete_mode_combo.setEnabled(editing_requested and not topology_busy and remove_tool)
    _state.mesh_edit_remove_mode_label.setVisible(remove_tool)
    _state.mesh_edit_delete_mode_combo.setVisible(remove_tool)
    _state.mesh_edit_radius_spin.setEnabled(editing_requested and not topology_busy and (sculpt_tool or remove_tool or brush_selection_tool))
    _state.mesh_edit_strength_spin.setEnabled(editing_requested and not topology_busy and sculpt_tool)
    _state.mesh_edit_falloff_combo.setEnabled(editing_requested and not topology_busy and sculpt_tool)
    _state.mesh_edit_iterations_spin.setEnabled(editing_requested and not topology_busy and smooth_tool)
    _state.mesh_edit_selection_mode_combo.setEnabled(editing_requested and not topology_busy and select_tool)
    _state.mesh_edit_selection_depth_combo.setEnabled(editing_requested and not topology_busy and select_tool)
    for widget in (_state.compact_selection_mode_combo, _state.compact_selection_depth_combo):
        if widget is not None:
            widget.setVisible(select_tool)
            widget.setEnabled(editing_requested and not topology_busy and select_tool)
    _state.mesh_edit_mirror_checkbox.setVisible(sculpt_tool)
    _state.mesh_edit_mirror_checkbox.setEnabled(editing_requested and not topology_busy and sculpt_tool)
    _state.mesh_edit_option_widget.setVisible(True)
    _state.mesh_edit_clear_selection_button.setVisible(selection_actions_visible)
    _state.mesh_edit_select_part_button.setVisible(select_tool)
    _state.mesh_edit_invert_selection_button.setVisible(select_tool)
    _state.mesh_edit_selection_actions_widget.setVisible(selection_actions_visible)
    _state.mesh_edit_subdivide_selection_button.setVisible(select_tool)
    _state.mesh_edit_refine_smooth_selection_button.setVisible(select_tool)
    _state.mesh_edit_split_selection_button.setVisible(select_tool)
    _state.mesh_edit_delete_faces_button.setVisible(select_tool)
    _state.mesh_edit_clear_selection_button.setEnabled(selection_active and not topology_busy)
    _state.mesh_edit_select_part_button.setEnabled(editing_active and select_tool and bool(allowed_indices) and not topology_busy)
    _state.mesh_edit_invert_selection_button.setEnabled(editing_active and select_tool and bool(allowed_indices) and not topology_busy)
    _state.mesh_edit_grow_selection_button.setEnabled(vertex_selection_active and not topology_busy)
    _state.mesh_edit_shrink_selection_button.setEnabled(vertex_selection_active and not topology_busy)
    _state.mesh_edit_smooth_selection_button.setEnabled(vertex_selection_active and not topology_busy)
    _state.mesh_edit_subdivide_selection_button.setEnabled(
        select_tool and selection_active and not topology_busy and not _state._morph_slider_has_nonzero_values()
    )
    _state.mesh_edit_refine_smooth_selection_button.setEnabled(
        select_tool and selection_active and not topology_busy and not _state._morph_slider_has_nonzero_values()
    )
    _state.mesh_edit_split_selection_button.setEnabled(
        select_tool and selection_active and not topology_busy and not _state._morph_slider_has_nonzero_values()
    )
    _state.mesh_edit_delete_faces_button.setEnabled(
        select_tool and selection_active and not topology_busy
    )
    _state.mesh_edit_undo_button.setEnabled(bool(_state.mesh_edit_undo_stack) and not topology_busy)
    _state.mesh_edit_redo_button.setEnabled(bool(_state.mesh_edit_redo_stack) and not topology_busy)
    _state.mesh_edit_reset_part_button.setEnabled(
        not topology_busy and _state._mesh_edit_reset_available_helper(
            _state._mesh_edit_state.replacement_mesh_base_for_mapping,
            is_base_source_index_editable=_state._mesh_edit_base_source_index_is_editable,
        )
    )
    _state.mesh_edit_full_reset_button.setEnabled(_state.mesh_edit_reset_part_button.isEnabled())
    _state.mesh_edit_status_label.setText(
        _state._mesh_edit_control_status_text_helper(
            reason,
            selected_count,
            int(_state.mesh_edit_revision.get("value", 0) or 0),
            editing_active=editing_active,
        )
    )
    compact_status_set_text = getattr(_state.compact_mesh_edit_status_label, "setText", None)
    if callable(compact_status_set_text):
        compact_status_set_text(_state.mesh_edit_status_label.text())
    for compact_button, source_button in (
        (_state.compact_mesh_edit_clear_button, _state.mesh_edit_clear_selection_button),
        (_state.compact_mesh_edit_grow_button, _state.mesh_edit_grow_selection_button),
        (_state.compact_mesh_edit_shrink_button, _state.mesh_edit_shrink_selection_button),
        (_state.compact_mesh_edit_feather_button, _state.mesh_edit_smooth_selection_button),
        (_state.compact_mesh_edit_reset_scope_button, _state.mesh_edit_reset_part_button),
    ):
        set_enabled = getattr(compact_button, "setEnabled", None)
        is_enabled = getattr(source_button, "isEnabled", None)
        if callable(set_enabled) and callable(is_enabled):
            set_enabled(bool(editing_requested and is_enabled()))
    _callbacks._sync_mesh_editor_tab_action_state(
        editing_active=editing_active,
        sculpt_tool=sculpt_tool,
        selected_count=selected_count,
        selected_face_count=selected_face_count,
        selected_edge_count=selected_edge_count,
    )
    _callbacks._morph_slider_refresh_controls()
    _callbacks._sync_mesh_edit_preview_settings()

def _mesh_edit_capture_undo_snapshot(_state, _callbacks, snapshot: object, *, take_ownership: bool = False) -> object | None:
    if isinstance(snapshot, _state.ParsedMesh):
        try:
            from cdmw.services.mesh_workflow_service import snapshot_native_mesh_submeshes

            native_snapshot = snapshot_native_mesh_submeshes(snapshot)
        except Exception as exc:
            _callbacks._record_mesh_edit_event("mesh_edit_native_undo_snapshot_exception", message=str(exc))
            native_snapshot = None
        if native_snapshot is not None:
            return native_snapshot
        _callbacks._record_mesh_edit_event(
            "mesh_edit_native_undo_snapshot_failed",
            message="Native undo snapshot failed; Python full-mesh undo snapshot fallback is disabled.",
        )
        _state.self.set_status_message(
            "Native undo snapshot failed; Python full-mesh undo snapshot fallback is disabled.",
            error=True,
        )
        return None
    return snapshot

def _mesh_edit_restore_undo_snapshot(_state, _callbacks, snapshot: object) -> _state.ParsedMesh | None:
    if isinstance(snapshot, _state.ParsedMesh):
        return None
    if isinstance(snapshot, _state.Mapping) and snapshot.get("kind") == "native_submesh_snapshot":
        try:
            from cdmw.services.mesh_workflow_service import restore_native_mesh_submesh_snapshot

            restored = _state.ParsedMesh()
            if restore_native_mesh_submesh_snapshot(restored, snapshot):
                return restored
        except Exception as exc:
            _callbacks._record_mesh_edit_event("mesh_edit_native_undo_restore_exception", message=str(exc))
            return None
    return None

def _mesh_edit_push_undo_snapshot(_state, _callbacks, snapshot: _state.ParsedMesh, *, take_ownership: bool = False) -> bool:
    stored_snapshot = _callbacks._mesh_edit_capture_undo_snapshot(snapshot, take_ownership=take_ownership)
    if stored_snapshot is None:
        return False
    _state.mesh_edit_undo_stack.append(stored_snapshot)
    _state.retain_mesh_history_snapshot(stored_snapshot)
    _state.mesh_edit_undo_adjustment_stack.append(_state._mesh_edit_part_state_snapshot())
    if len(_state.mesh_edit_undo_stack) > 30:
        _state.release_mesh_history_snapshot(_state.mesh_edit_undo_stack.pop(0))
        if _state.mesh_edit_undo_adjustment_stack:
            del _state.mesh_edit_undo_adjustment_stack[0]
    _state.clear_mesh_history_snapshot_stack(_state.mesh_edit_redo_stack)
    _state.mesh_edit_redo_adjustment_stack.clear()
    return True

def _mesh_edit_pop_undo_snapshot(_state, _callbacks, ) -> None:
    if _state.mesh_edit_undo_stack:
        _state.release_mesh_history_snapshot(_state.mesh_edit_undo_stack.pop())
    if _state.mesh_edit_undo_adjustment_stack:
        _state.mesh_edit_undo_adjustment_stack.pop()

def _mesh_edit_pop_active_stroke_snapshots(_state, _callbacks, ) -> None:
    if bool(_state.mesh_edit_active_stroke.get("undo_snapshot_pushed", True)):
        _callbacks._mesh_edit_pop_undo_snapshot()
    if bool(_state.mesh_edit_active_stroke.get("geometry_snapshot_pushed", True)):
        _state._pop_geometry_undo_snapshot()

def _mesh_edit_source_enable_mutation_blocked(_state, _callbacks, action: str, source_indices: object = ()) -> None:
    message = (
        "Active Mesh Editor source enable changes require native part-state execution; "
        "Python source adjustment mutation fallback is disabled."
    )
    _callbacks._record_mesh_edit_event(
        "mesh_edit_source_enable_mutation_blocked",
        action=str(action or "source_enable"),
        source_indices=tuple(source_indices or ()),
        message=message,
    )
    _state.self.set_status_message(message, error=True)

def _mesh_edit_restore_enabled_snapshot(_state, _callbacks, snapshot: object) -> None:
    if isinstance(snapshot, _state.Mapping) and bool(snapshot.get('metadata_only')):
        restore = _state._restore_geometry_history_state
        if callable(restore):
            current = dict(snapshot)
            current['mesh_edit_revision'] = int(_state.mesh_edit_revision.get('value', 0) or 0)
            current['source_geometry_revision'] = int(_state.source_geometry_revision.get('value', 0) or 0)
            restore(current)
            return
    snapshot_items = tuple(_state._mesh_edit_enabled_snapshot_items_helper(snapshot))
    if snapshot_items:
        _callbacks._mesh_edit_source_enable_mutation_blocked(
            "history.restore_source_enable",
            (source_index for source_index, _enabled in snapshot_items),
        )

def _sync_source_tree_enabled_checks(_state, _callbacks, ) -> None:
    _state.source_tree_item_update_guard["active"] = True
    try:
        for source_index, source_item in _state.source_items_by_index.items():
            adjustment = _state.source_part_adjustments.get(int(source_index))
            source_item.setCheckState(0, _state.Qt.Checked if adjustment is None or bool(adjustment.enabled) else _state.Qt.Unchecked)
    finally:
        _state.source_tree_item_update_guard["active"] = False

def _mesh_edit_disable_emptied_parts(_state, _callbacks, source_indices: _state.Sequence[int]) -> None:
    if source_indices:
        _callbacks._mesh_edit_source_enable_mutation_blocked("topology.disable_emptied_parts", source_indices)
    _callbacks._sync_source_tree_enabled_checks()

def _mesh_edit_record_snapshot(_state, _callbacks, ) -> None:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return
    _state._push_geometry_undo_snapshot("Mesh edit")
    if not _callbacks._mesh_edit_push_undo_snapshot(_state._mesh_edit_state.replacement_mesh_for_mapping):
        _state._pop_geometry_undo_snapshot()

def _mesh_edit_restore_base_sources_native(_state, _callbacks, source_indices: _state.Sequence[int], *, operation: str) -> bool:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None or _state._mesh_edit_state.replacement_mesh_base_for_mapping is None:
        return False
    try:
        from cdmw.services.mesh_workflow_service import restore_native_mesh_submeshes_from_mesh

        restored = restore_native_mesh_submeshes_from_mesh(
            _state._mesh_edit_state.replacement_mesh_for_mapping,
            _state._mesh_edit_state.replacement_mesh_base_for_mapping,
            source_indices,
            timeout_seconds=20.0,
        )
        if restored:
            _callbacks._mesh_editor_clear_static_replacement_session()
            _state.mesh_edit_native_result_submesh_counts["value"] = ()
        return restored
    except Exception as exc:
        _callbacks._record_mesh_edit_event(
            "mesh_edit_native_base_restore_failed",
            operation=str(operation or "mesh_edit.reset"),
            message=str(exc),
            source_indices=tuple(source_indices or ()),
        )
        return False

def _mesh_edit_abort_recorded_snapshot(_state, _callbacks, ) -> None:
    _callbacks._mesh_edit_pop_undo_snapshot()
    _state._pop_geometry_undo_snapshot()

def _mesh_edit_replace_working_mesh(_state, _callbacks, snapshot: object, *, native_update: object | None = None) -> None:
    if _callbacks._mesh_edit_restore_sparse_vertex_snapshot(snapshot, increment_revision=True, include_normals=True):
        return
    restored_snapshot = _callbacks._mesh_edit_restore_undo_snapshot(snapshot)
    if restored_snapshot is None:
        return
    _state.mesh_edit_native_result_submesh_counts["value"] = ()
    _state._mesh_edit_state.replacement_mesh_for_mapping = restored_snapshot
    native_update_applied = bool(
        native_update is not None
        and _state._alignment_d3d11_preview_active()
        and _callbacks._mesh_editor_apply_native_update(native_update)
    )
    if native_update_applied:
        _state.mesh_edit_preview_model_dirty["value"] = True
    else:
        _callbacks._morph_slider_capture_post_edit_deltas()
        _callbacks._mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
    _state.mesh_edit_revision["value"] = int(_state.mesh_edit_revision.get("value", 0) or 0) + 1
    _callbacks._mesh_edit_commit_geometry_preview_state()
    _callbacks._sync_source_tree_enabled_checks()
    _state._refresh_source_assignment_columns()
    _callbacks._refresh_mesh_edit_controls()
    if not native_update_applied:
        _callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild(_state._mesh_edit_preview_source_indices(), replace_all=True)

def _mesh_edit_replace_result_working_mesh(_state, _callbacks, result: object) -> None:
    native_update = getattr(result, "native_update", None)
    if _callbacks._mesh_editor_result_has_deferred_native_python_apply(result):
        if not _callbacks._mesh_editor_store_result_mesh(result):
            return
        _state.mesh_edit_revision["value"] = int(_state.mesh_edit_revision.get("value", 0) or 0) + 1
        _callbacks._mesh_edit_commit_geometry_preview_state()
        _callbacks._sync_source_tree_enabled_checks()
        _state._refresh_source_assignment_columns()
        _callbacks._refresh_mesh_edit_controls()
        if native_update is not None and _state._alignment_d3d11_preview_active() and _callbacks._mesh_editor_apply_native_update(native_update):
            return
        raise RuntimeError("native deferred history result did not include preview payload; Python mesh replacement is disabled")
    _callbacks._mesh_edit_replace_working_mesh(
        _callbacks._mesh_editor_result_mesh_for_state(result),
        native_update=native_update,
    )

def _mesh_edit_undo(_state, _callbacks, ) -> None:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None or not _state.mesh_edit_undo_stack:
        return
    mesh_editor_session = _callbacks._mesh_editor_fresh_static_replacement_session()
    if mesh_editor_session is not None and mesh_editor_session.view().undo_count > 0:
        redo_snapshot = _callbacks._mesh_edit_capture_undo_snapshot(_state._mesh_edit_state.replacement_mesh_for_mapping)
        if redo_snapshot is None:
            return
        result = mesh_editor_session.undo()
        _state.mesh_edit_redo_stack.append(redo_snapshot)
        _state.retain_mesh_history_snapshot(redo_snapshot)
        _state.mesh_edit_redo_adjustment_stack.append(_state._mesh_edit_part_state_snapshot())
        adjustment_snapshot = (
            _state.mesh_edit_undo_adjustment_stack.pop()
            if _state.mesh_edit_undo_adjustment_stack
            else _state._mesh_edit_part_state_snapshot()
        )
        _state.release_mesh_history_snapshot(_state.mesh_edit_undo_stack.pop())
        _callbacks._mesh_edit_replace_result_working_mesh(result)
        _callbacks._mesh_edit_restore_enabled_snapshot(adjustment_snapshot)
        _callbacks._mesh_editor_remember_static_replacement_session_mesh()
        return
    snapshot = _state.mesh_edit_undo_stack.pop()
    current_snapshot = _callbacks._mesh_edit_current_sparse_vertex_snapshot(snapshot)
    redo_snapshot = (
        current_snapshot
        if current_snapshot is not None
        else _callbacks._mesh_edit_capture_undo_snapshot(_state._mesh_edit_state.replacement_mesh_for_mapping)
    )
    if redo_snapshot is None:
        _state.mesh_edit_undo_stack.append(snapshot)
        return
    _state.mesh_edit_redo_stack.append(redo_snapshot)
    _state.retain_mesh_history_snapshot(redo_snapshot)
    _state.mesh_edit_redo_adjustment_stack.append(_state._mesh_edit_part_state_snapshot())
    adjustment_snapshot = (
        _state.mesh_edit_undo_adjustment_stack.pop()
        if _state.mesh_edit_undo_adjustment_stack
        else _state._mesh_edit_part_state_snapshot()
    )
    _callbacks._mesh_edit_replace_working_mesh(snapshot)
    _callbacks._mesh_edit_restore_enabled_snapshot(adjustment_snapshot)
    _state.release_mesh_history_snapshot(snapshot)

def _mesh_edit_redo(_state, _callbacks, ) -> None:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None or not _state.mesh_edit_redo_stack:
        return
    mesh_editor_session = _callbacks._mesh_editor_fresh_static_replacement_session()
    if mesh_editor_session is not None and mesh_editor_session.view().redo_count > 0:
        undo_snapshot = _callbacks._mesh_edit_capture_undo_snapshot(_state._mesh_edit_state.replacement_mesh_for_mapping)
        if undo_snapshot is None:
            return
        result = mesh_editor_session.redo()
        _state.mesh_edit_undo_stack.append(undo_snapshot)
        _state.retain_mesh_history_snapshot(undo_snapshot)
        _state.mesh_edit_undo_adjustment_stack.append(_state._mesh_edit_part_state_snapshot())
        adjustment_snapshot = (
            _state.mesh_edit_redo_adjustment_stack.pop()
            if _state.mesh_edit_redo_adjustment_stack
            else _state._mesh_edit_part_state_snapshot()
        )
        _state.release_mesh_history_snapshot(_state.mesh_edit_redo_stack.pop())
        _callbacks._mesh_edit_replace_result_working_mesh(result)
        _callbacks._mesh_edit_restore_enabled_snapshot(adjustment_snapshot)
        _callbacks._mesh_editor_remember_static_replacement_session_mesh()
        return
    snapshot = _state.mesh_edit_redo_stack.pop()
    current_snapshot = _callbacks._mesh_edit_current_sparse_vertex_snapshot(snapshot)
    undo_snapshot = (
        current_snapshot
        if current_snapshot is not None
        else _callbacks._mesh_edit_capture_undo_snapshot(_state._mesh_edit_state.replacement_mesh_for_mapping)
    )
    if undo_snapshot is None:
        _state.mesh_edit_redo_stack.append(snapshot)
        return
    _state.mesh_edit_undo_stack.append(undo_snapshot)
    _state.retain_mesh_history_snapshot(undo_snapshot)
    _state.mesh_edit_undo_adjustment_stack.append(_state._mesh_edit_part_state_snapshot())
    adjustment_snapshot = (
        _state.mesh_edit_redo_adjustment_stack.pop()
        if _state.mesh_edit_redo_adjustment_stack
        else _state._mesh_edit_part_state_snapshot()
    )
    _callbacks._mesh_edit_replace_working_mesh(snapshot)
    _callbacks._mesh_edit_restore_enabled_snapshot(adjustment_snapshot)
    _state.release_mesh_history_snapshot(snapshot)

def _mesh_edit_reset_scope(_state, _callbacks, ) -> None:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None or _state._mesh_edit_state.replacement_mesh_base_for_mapping is None:
        return
    source_indices = _state._mesh_edit_reset_scope_source_indices_helper(
        _state._mesh_edit_state.replacement_mesh_for_mapping,
        _state._mesh_edit_state.replacement_mesh_base_for_mapping,
        scope_mode=_state._mesh_edit_scope_mode(),
        selected_scope_source_index=_state._mesh_edit_selected_scope_source_index(),
        is_base_source_index_editable=_state._mesh_edit_base_source_index_is_editable,
    )
    if not source_indices:
        return
    if not _callbacks._mesh_editor_sync_static_replacement_session_to_working_mesh("mesh_edit.reset_scope"):
        return
    restore_deleted_output_by_source: dict[int, bool] = {}
    for source_index in source_indices:
        working_source = _state._mesh_edit_state.replacement_mesh_for_mapping.submeshes[source_index]
        base_source = _state._mesh_edit_state.replacement_mesh_base_for_mapping.submeshes[source_index]
        restore_deleted_output_by_source[source_index] = _state._mesh_edit_should_restore_deleted_output_helper(
            working_source,
            base_source,
    )
    _callbacks._mesh_edit_record_snapshot()
    if not _callbacks._mesh_edit_restore_base_sources_native(source_indices, operation="mesh_edit.reset_scope"):
        _callbacks._mesh_edit_abort_recorded_snapshot()
        _state.self.set_status_message(
            "Native Mesh Editor reset failed; Python geometry clone fallback is disabled.",
            error=True,
        )
        return
    for source_index in source_indices:
        _state.mesh_edit_selected_vertices_by_submesh.pop(source_index, None)
        _state.mesh_edit_selected_source_indices.discard(source_index)
    restore_deleted_sources = tuple(
        source_index for source_index in source_indices if restore_deleted_output_by_source.get(source_index)
    )
    if restore_deleted_sources:
        _callbacks._mesh_edit_source_enable_mutation_blocked("reset.restore_deleted_output", restore_deleted_sources)
    if _state._morph_slider_has_loaded_deltas():
        _callbacks._morph_slider_zero_post_edit_deltas_for_sources(source_indices)
        if _callbacks._morph_slider_refresh_topology_block_state():
            _callbacks._morph_slider_apply_to_working_mesh(increment_revision=False, refresh_controls=False)
    _callbacks._mesh_edit_update_mesh_totals()
    _callbacks._mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
    _state.mesh_edit_revision["value"] = int(_state.mesh_edit_revision.get("value", 0) or 0) + 1
    _callbacks._mesh_edit_commit_geometry_preview_state()
    _callbacks._sync_source_tree_enabled_checks()
    _state._refresh_source_tree_selection_state()
    _state._refresh_source_assignment_columns()
    _callbacks._refresh_mesh_edit_controls()
    _callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild(source_indices)

def _mesh_edit_full_reset_mesh(_state, _callbacks, ) -> None:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None or _state._mesh_edit_state.replacement_mesh_base_for_mapping is None:
        return
    source_indices = _state._mesh_edit_full_reset_source_indices_helper(
        _state._mesh_edit_state.replacement_mesh_for_mapping,
        _state._mesh_edit_state.replacement_mesh_base_for_mapping,
        is_base_source_index_editable=_state._mesh_edit_base_source_index_is_editable,
    )
    if not source_indices:
        return
    if not _callbacks._mesh_editor_sync_static_replacement_session_to_working_mesh("mesh_edit.full_reset"):
        return
    restore_deleted_output_by_source: dict[int, bool] = {}
    for source_index in source_indices:
        working_source = _state._mesh_edit_state.replacement_mesh_for_mapping.submeshes[source_index]
        base_source = _state._mesh_edit_state.replacement_mesh_base_for_mapping.submeshes[source_index]
        restore_deleted_output_by_source[source_index] = _state._mesh_edit_should_restore_deleted_output_helper(
            working_source,
            base_source,
    )
    _callbacks._mesh_edit_record_snapshot()
    if not _callbacks._mesh_edit_restore_base_sources_native(source_indices, operation="mesh_edit.full_reset"):
        _callbacks._mesh_edit_abort_recorded_snapshot()
        _state.self.set_status_message(
            "Native Mesh Editor full reset failed; Python geometry clone fallback is disabled.",
            error=True,
        )
        return
    restore_deleted_sources = tuple(
        source_index for source_index in source_indices if restore_deleted_output_by_source.get(source_index)
    )
    if restore_deleted_sources:
        _callbacks._mesh_edit_source_enable_mutation_blocked("full_reset.restore_deleted_output", restore_deleted_sources)
    _state.mesh_edit_selected_vertices_by_submesh.clear()
    _state.mesh_edit_selected_edges_by_submesh.clear()
    _state.mesh_edit_selected_faces_by_submesh.clear()
    _state.mesh_edit_selected_source_indices.clear()
    if _state._morph_slider_has_loaded_deltas():
        _callbacks._morph_slider_zero_post_edit_deltas_for_sources(source_indices)
        _callbacks._morph_slider_refresh_topology_block_state()
    _callbacks._mesh_edit_update_mesh_totals()
    _callbacks._mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
    _state.mesh_edit_revision["value"] = int(_state.mesh_edit_revision.get("value", 0) or 0) + 1
    _callbacks._mesh_edit_commit_geometry_preview_state()
    _callbacks._sync_source_tree_enabled_checks()
    _state._refresh_source_tree_selection_state()
    _state._refresh_source_assignment_columns()
    _callbacks._refresh_mesh_edit_controls()
    if _state._alignment_d3d11_preview_active():
        _state.alignment_d3d11_preview_host.clear_mesh_edit_vertex_selection()
    _callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild(source_indices)


_CALLBACKS = (
    _alignment_d3d11_process_active,
    _embedded_dotnet_parent_hwnd,
    _refresh_mesh_edit_controls,
    _mesh_edit_capture_undo_snapshot,
    _mesh_edit_restore_undo_snapshot,
    _mesh_edit_push_undo_snapshot,
    _mesh_edit_pop_undo_snapshot,
    _mesh_edit_pop_active_stroke_snapshots,
    _mesh_edit_source_enable_mutation_blocked,
    _mesh_edit_restore_enabled_snapshot,
    _sync_source_tree_enabled_checks,
    _mesh_edit_disable_emptied_parts,
    _mesh_edit_record_snapshot,
    _mesh_edit_restore_base_sources_native,
    _mesh_edit_abort_recorded_snapshot,
    _mesh_edit_replace_working_mesh,
    _mesh_edit_replace_result_working_mesh,
    _mesh_edit_undo,
    _mesh_edit_redo,
    _mesh_edit_reset_scope,
    _mesh_edit_full_reset_mesh,
)
