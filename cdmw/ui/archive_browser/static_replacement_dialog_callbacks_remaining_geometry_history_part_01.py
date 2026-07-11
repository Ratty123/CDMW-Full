from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_dotnet_material_bridge import (
    send_resident_material_parameters,
    source_part_material_parameter_groups_for_mesh,
)

_MATERIAL_HISTORY_WIDGETS = (
    'complete_external_swap_checkbox', 'complete_swap_material_profile_combo',
    'global_gloss_reduction_spin', 'edge_relief_spin', 'edge_relief_source_combo',
    'accent_glow_spin', 'auto_brightness_spin', 'source_brightness_spin',
    'tone_contrast_spin', 'unsafe_material_preflight_checkbox',
)

def _material_history_state(context: dict[str, object]) -> dict[str, object]:
    state: dict[str, object] = {}
    for name in _MATERIAL_HISTORY_WIDGETS:
        widget = context.get(name)
        getter = getattr(widget, 'currentData', None) or getattr(widget, 'isChecked', None) or getattr(widget, 'value', None)
        if callable(getter):
            state[name] = getter()
    manual = context.get('_current_manual_material_profile_values')
    if callable(manual):
        state['manual_profile_values'] = manual()
    return state

def _restore_material_history_state(context: dict[str, object], state: object) -> None:
    if not isinstance(state, dict):
        return
    for name in _MATERIAL_HISTORY_WIDGETS:
        if name not in state:
            continue
        widget = context.get(name)
        blocker = getattr(widget, 'blockSignals', None)
        previous = blocker(True) if callable(blocker) else False
        try:
            if callable(getattr(widget, 'findData', None)):
                index = widget.findData(state[name])
                if index >= 0:
                    widget.setCurrentIndex(index)
            elif callable(getattr(widget, 'setChecked', None)):
                widget.setChecked(bool(state[name]))
            elif callable(getattr(widget, 'setValue', None)):
                widget.setValue(state[name])
        finally:
            if callable(blocker):
                blocker(previous)
    manual = context.get('_apply_manual_material_profile_values')
    if callable(manual) and isinstance(state.get('manual_profile_values'), dict):
        manual(state['manual_profile_values'], persist=False, refresh_preview=False)


def _remaining_geometry_history_step_001(_state):
    _state.state = _state._StaticReplacementDialogState(_state.context)
    _state.Any = _state.context.get('Any')
    _state.Dict = _state.context.get('Dict')
    _state.Mapping = _state.context.get('Mapping')
    _state.ParsedMesh = _state.context.get('ParsedMesh')
    _state._apply_source_material_texture_overrides_to_ui_texture_sets = _state.context.get('_apply_source_material_texture_overrides_to_ui_texture_sets')
    _state._default_texture_uv_transform_state = _state.context.get('_default_texture_uv_transform_state')
    _state._geometry_history_capture_state_helper = _state.context.get('_geometry_history_capture_state_helper')
    _state._geometry_history_push_state_helper = _state.context.get('_geometry_history_push_state_helper')
    _state._geometry_history_restore_state_helper = _state.context.get('_geometry_history_restore_state_helper')
    _state._geometry_mapping_text_by_target = _state.context.get('_geometry_mapping_text_by_target')
    _state._geometry_original_copy_text_by_index = _state.context.get('_geometry_original_copy_text_by_index')
    _state._geometry_reset_status_text_helper = _state.context.get('_geometry_reset_status_text_helper')
    _state._geometry_undo_status_text_helper = _state.context.get('_geometry_undo_status_text_helper')
    _state._invalidate_source_display_cache = _state.context.get('_invalidate_source_display_cache')
    _state._load_selected_part_controls = _state.context.get('_load_selected_part_controls')
    _state._morph_slider_refresh_controls = _state.context.get('_morph_slider_refresh_controls')
    _state._morph_slider_reload_profiles = _state.context.get('_morph_slider_reload_profiles')
    _state._alignment_d3d11_preview_active = _state.context.get('_alignment_d3d11_preview_active')
    _state._alignment_mesh_edit_tab_active = _state.context.get('_alignment_mesh_edit_tab_active')
    _state._mesh_edit_preview_source_indices = _state.context.get('_mesh_edit_preview_source_indices')
    _state._mesh_edit_replace_live_triangles_or_queue_rebuild = _state.context.get('_mesh_edit_replace_live_triangles_or_queue_rebuild')
    _state._mesh_edit_update_live_preview = _state.context.get('_mesh_edit_update_live_preview')
    _state._queue_static_preview_rebuild = _state.context.get('_queue_static_preview_rebuild')
    _state._record_runtime_event = _state.context.get('_record_runtime_event')
    if not callable(_state._record_runtime_event):
        _state._record_runtime_event = lambda *_args, **_kwargs: None
    _state._rebuild_source_part_widgets = _state.context.get('_rebuild_source_part_widgets')
    _state._record_texture_uv_global_transform_state_helper = _state.context.get('_record_texture_uv_global_transform_state_helper')
    _state._refresh_original_reference_preview = _state.context.get('_refresh_original_reference_preview')
    _state._refresh_source_assignment_columns = _state.context.get('_refresh_source_assignment_columns')
    _state._refresh_texture_row_guidance = _state.context.get('_refresh_texture_row_guidance')
    _state._refresh_texture_table = _state.context.get('_refresh_texture_table')
    _state._refresh_texture_transform_editor = _state.context.get('_refresh_texture_transform_editor')
    _state._selected_source_indices_from_tree = _state.context.get('_selected_source_indices_from_tree')
    _state._sync_highlight_sets = _state.context.get('_sync_highlight_sets')
    _state._update_mapping_status = _state.context.get('_update_mapping_status')
    _state._update_selection_context = _state.context.get('_update_selection_context')
    _state.appended_source_indices = _state.context.get('appended_source_indices')
    _state.copied_original_physics_sensitive_sources = _state.context.get('copied_original_physics_sensitive_sources')
    _state.copied_original_source_indices = _state.context.get('copied_original_source_indices')
    _state.copied_original_source_to_original_index = _state.context.get('copied_original_source_to_original_index')
    _state.copied_original_texture_disabled_sources = _state.context.get('copied_original_texture_disabled_sources')
    _state.copied_original_texture_intents_by_source = _state.context.get('copied_original_texture_intents_by_source')
    _state.copy = _state.context.get('copy')
    _state.dialog_added_supplemental_files = _state.context.get('dialog_added_supplemental_files')
    _state.edit = _state.context.get('edit')
    _state.geometry_history_guard = _state.context.get('geometry_history_guard')
    _state.geometry_initial_snapshot = _state.context.get('geometry_initial_snapshot')
    _state.geometry_undo_stack = _state.context.get('geometry_undo_stack')
    _state.group_replacement_texture_sets = _state.context.get('group_replacement_texture_sets')
    _state.independent_output_source_indices = _state.context.get('independent_output_source_indices')
    _state.item = _state.context.get('item')
    _state.mapping_edit_refresh_timer = _state.context.get('mapping_edit_refresh_timer')
    _state.mapping_edits = _state.context.get('mapping_edits')
    _state.mapping_text_by_target = _state.context.get('mapping_text_by_target')
    _state.mesh_edit_active_stroke = _state.context.get('mesh_edit_active_stroke')
    _state.mesh_edit_redo_adjustment_stack = _state.context.get('mesh_edit_redo_adjustment_stack')
    _state.mesh_edit_redo_stack = _state.context.get('mesh_edit_redo_stack')
    _state.mesh_edit_revision = _state.context.get('mesh_edit_revision')
    _state.mesh_edit_selected_faces_by_submesh = _state.context.get('mesh_edit_selected_faces_by_submesh')
    _state.mesh_edit_selected_source_indices = _state.context.get('mesh_edit_selected_source_indices')
    _state.mesh_edit_selected_vertices_by_submesh = _state.context.get('mesh_edit_selected_vertices_by_submesh')
    _state.mesh_edit_undo_adjustment_stack = _state.context.get('mesh_edit_undo_adjustment_stack')
    _state.mesh_edit_undo_stack = _state.context.get('mesh_edit_undo_stack')
    _state.morph_slider_post_edit_deltas = _state.context.get('morph_slider_post_edit_deltas')
    _state.morph_slider_topology_blocked = _state.context.get('morph_slider_topology_blocked')
    _state.morph_slider_values = _state.context.get('morph_slider_values')
    _state.original_index = _state.context.get('original_index')
    _state.original_items_by_index = _state.context.get('original_items_by_index')
    _state.original_part_copies = _state.context.get('original_part_copies')
    _state.parsed_mesh_to_preview_model = _state.context.get('parsed_mesh_to_preview_model')
    _state.preview_only_source_indices = _state.context.get('preview_only_source_indices')
    _state.push_state = _state.context.get('push_state')
    _state.reason = _state.context.get('reason')
    _state.replacement_base_mesh = _state.context.get('replacement_base_mesh')
    _state.replacement_mesh = _state.context.get('replacement_mesh')
    _state.reset_geometry_button = _state.context.get('reset_geometry_button')
    _state.restore_state = _state.context.get('restore_state')
    _state.restored_morph_slider_post_edit_deltas = _state.context.get('restored_morph_slider_post_edit_deltas')
    _state.restored_morph_slider_topology_blocked = _state.context.get('restored_morph_slider_topology_blocked')
    _state.selected_original_highlight_indices = _state.context.get('selected_original_highlight_indices')
    _state.selected_original_part = _state.context.get('selected_original_part')
    _state.selected_source_highlight_indices = _state.context.get('selected_source_highlight_indices')
    _state.selected_source_part = _state.context.get('selected_source_part')
    _state.selected_target_original_highlight_indices = _state.context.get('selected_target_original_highlight_indices')
    _state.selected_target_slot = _state.context.get('selected_target_slot')
    _state.selected_target_source_highlight_indices = _state.context.get('selected_target_source_highlight_indices')
    _state.selected_texture_row = _state.context.get('selected_texture_row')
    _state.self = _state.context.get('self')

def _remaining_geometry_history_step_002(_state):
    _state.snapshot = _state.context.get('snapshot')
    _state.source_display_overrides = _state.context.get('source_display_overrides')
    _state.source_geometry_revision = _state.context.get('source_geometry_revision')
    _state.source_material_texture_override_assignments = _state.context.get('source_material_texture_override_assignments')
    _state.source_part_adjustments = _state.context.get('source_part_adjustments')
    _state.source_role_overrides = _state.context.get('source_role_overrides')
    _state.static_preview_geometry_cache = _state.context.get('static_preview_geometry_cache')
    _state.static_preview_prepared_cache = _state.context.get('static_preview_prepared_cache')
    _state.target_index = _state.context.get('target_index')
    _state.texture_files_for_mapping = _state.context.get('texture_files_for_mapping') or []
    _state.texture_override_assignments = _state.context.get('texture_override_assignments')
    _state.texture_overrides_dirty = _state.context.get('texture_overrides_dirty')
    _state.texture_uv_global_transform_state = _state.context.get('texture_uv_global_transform_state')
    _state.texture_uv_transform_state = _state.context.get('texture_uv_transform_state')
    _state.transform_source_indices = _state.context.get('transform_source_indices')
    _state.undo_geometry_button = _state.context.get('undo_geometry_button')

def _remaining_geometry_history_step_003(_state):

    def _geometry_history_mesh_snapshot(mesh: object | None) -> object | None:
        if mesh is None:
            return None
        if isinstance(mesh, _state.ParsedMesh):
            try:
                from cdmw.services.mesh_workflow_service import snapshot_native_mesh_submeshes
                native_snapshot = snapshot_native_mesh_submeshes(mesh)
            except Exception:
                native_snapshot = None
            if native_snapshot is not None:
                return native_snapshot
            return _state.clone_mesh_for_static_replacement_native_first(mesh, 'history.static_geometry_snapshot', 'Python mesh history snapshot fallback blocked while native mesh core is available', fallback_allowed=_state._geometry_python_mesh_snapshot_fallback_allowed)
        return None
    _state._geometry_history_mesh_snapshot = _geometry_history_mesh_snapshot

def _remaining_geometry_history_step_004(_state):

    def _geometry_history_restore_mesh_snapshot(snapshot: object) -> object | None:
        if isinstance(snapshot, _state.ParsedMesh):
            return _state._geometry_history_clone_parsed_mesh_snapshot(snapshot)
        if isinstance(snapshot, _state.Mapping) and snapshot.get('kind') == 'native_submesh_snapshot':
            try:
                from cdmw.services.mesh_workflow_service import restore_native_mesh_submesh_snapshot
                restored = _state.ParsedMesh()
                if restore_native_mesh_submesh_snapshot(restored, snapshot):
                    return restored
            except Exception:
                return None
        return None
    _state._geometry_history_restore_mesh_snapshot = _geometry_history_restore_mesh_snapshot

def _remaining_geometry_history_step_005(_state):

    def _geometry_history_clone_parsed_mesh_snapshot(snapshot: ParsedMesh) -> ParsedMesh | None:
        restored = _state.clone_mesh_for_static_replacement_native_first(snapshot, 'history.static_geometry_snapshot_restore', 'Python mesh history snapshot fallback blocked while native mesh core is available', fallback_allowed=_state._geometry_python_mesh_snapshot_fallback_allowed)
        return restored if isinstance(restored, _state.ParsedMesh) else None
    _state._geometry_history_clone_parsed_mesh_snapshot = _geometry_history_clone_parsed_mesh_snapshot

def _remaining_geometry_history_step_006(_state):

    def _release_native_submesh_snapshot(value: object) -> None:
        if not isinstance(value, _state.Mapping) or value.get('kind') != 'native_submesh_snapshot':
            return
        try:
            from cdmw.services.mesh_workflow_service import dispose_native_mesh_submesh_snapshot
            dispose_native_mesh_submesh_snapshot(value)
        except Exception:
            pass
    _state._release_native_submesh_snapshot = _release_native_submesh_snapshot

def _remaining_geometry_history_step_007(_state):

    def _release_geometry_history_snapshot(snapshot: object) -> None:
        _state.release_sparse_vertex_snapshot(snapshot)
        if not isinstance(snapshot, _state.Mapping):
            return
        _state._release_native_submesh_snapshot(snapshot.get('replacement_mesh'))
        _state._release_native_submesh_snapshot(snapshot.get('replacement_base_mesh'))
    _state._release_geometry_history_snapshot = _release_geometry_history_snapshot

def _remaining_geometry_history_step_008(_state):

    def _geometry_python_mesh_snapshot_fallback_allowed(mesh: object) -> bool:
        if _state.allow_python_mesh_history_snapshot_fallback(mesh, 'history.static_geometry_snapshot'):
            return True
        message = 'Native geometry history snapshot failed; Python full-mesh snapshot fallback blocked while native mesh core is available.'
        _state._record_runtime_event('mesh_edit_geometry_python_snapshot_fallback_blocked', message=message)
        _state.self.set_status_message(message, error=True)
        return False
    _state._geometry_python_mesh_snapshot_fallback_allowed = _geometry_python_mesh_snapshot_fallback_allowed

def _remaining_geometry_history_step_009(_state):

    def _capture_geometry_history_state(reason: str, *, metadata_only: bool=False) -> Dict[str, Any]:
        replacement_snapshot = None if metadata_only else _state._geometry_history_mesh_snapshot(_state.state.replacement_mesh_for_mapping)
        replacement_base_snapshot = None if metadata_only else _state._geometry_history_mesh_snapshot(_state.state.replacement_mesh_base_for_mapping)
        if not metadata_only and _state.state.replacement_mesh_for_mapping is not None and replacement_snapshot is None:
            return {}
        if not metadata_only and _state.state.replacement_mesh_base_for_mapping is not None and replacement_base_snapshot is None:
            return {}
        return _state._geometry_history_capture_state_helper(reason=reason, replacement_mesh=replacement_snapshot, replacement_base_mesh=replacement_base_snapshot, mapping_text_by_target=_state._geometry_mapping_text_by_target(), source_part_adjustments=_state.source_part_adjustments, source_role_overrides=_state.source_role_overrides, source_display_overrides=_state.source_display_overrides, original_part_copies=_state.original_part_copies, original_copy_text_by_index=_state._geometry_original_copy_text_by_index(), appended_source_indices=_state.appended_source_indices, independent_output_source_indices=_state.independent_output_source_indices, preview_only_source_indices=_state.preview_only_source_indices, dialog_added_supplemental_files=_state.dialog_added_supplemental_files, texture_files_for_mapping=_state.texture_files_for_mapping, texture_override_assignments=_state.texture_override_assignments, source_material_texture_override_assignments=_state.source_material_texture_override_assignments, copied_original_texture_intents_by_source=_state.copied_original_texture_intents_by_source, copied_original_texture_disabled_sources=_state.copied_original_texture_disabled_sources, copied_original_source_indices=_state.copied_original_source_indices, copied_original_source_to_original_index=_state.copied_original_source_to_original_index, copied_original_physics_sensitive_sources=_state.copied_original_physics_sensitive_sources, texture_uv_transform_state=_state.texture_uv_transform_state, texture_uv_global_transform_state=_state.texture_uv_global_transform_state, mesh_edit_revision=_state.mesh_edit_revision.get('value', 0), source_geometry_revision=_state.source_geometry_revision.get('value', 0), morph_slider_values=_state.morph_slider_values, morph_slider_post_edit_deltas=_state.morph_slider_post_edit_deltas, morph_slider_topology_blocked=_state.morph_slider_topology_blocked, selected_source_index=_state.selected_source_part.get('index', -1), selected_source_indices=_state._selected_source_indices_from_tree(), selected_target_index=_state.selected_target_slot.get('index', -1), selected_original_index=_state.selected_original_part.get('index', -1), selected_source_highlights=_state.selected_source_highlight_indices, selected_target_source_highlights=_state.selected_target_source_highlight_indices, transform_source_indices=_state.transform_source_indices, selected_original_highlights=_state.selected_original_highlight_indices, selected_target_original_highlights=_state.selected_target_original_highlight_indices, metadata_only=metadata_only, material_authority_state=_material_history_state(_state.context))
    _state._capture_geometry_history_state = _capture_geometry_history_state

def _remaining_geometry_history_step_010(_state):

    def _refresh_geometry_history_buttons() -> None:
        try:
            if callable(getattr(_state.undo_geometry_button, 'setEnabled', None)):
                _state.undo_geometry_button.setEnabled(bool(_state.geometry_undo_stack))
            if callable(getattr(_state.reset_geometry_button, 'setEnabled', None)):
                _state.reset_geometry_button.setEnabled(bool(_state.geometry_initial_snapshot))
        except NameError:
            pass
    _state._refresh_geometry_history_buttons = _refresh_geometry_history_buttons

def _remaining_geometry_history_step_011(_state):

    def _push_geometry_undo_snapshot(reason: str, *, metadata_only: bool=False) -> None:
        snapshot = _state._capture_geometry_history_state(reason, metadata_only=metadata_only)
        if not snapshot:
            return
        old_stack = tuple(_state.geometry_undo_stack or ())
        push_state = _state._geometry_history_push_state_helper(_state.geometry_undo_stack, snapshot, guard_active=bool(_state.geometry_history_guard.get('active')))
        if not push_state.pushed:
            _state._release_geometry_history_snapshot(snapshot)
            return
        _state.retain_sparse_vertex_snapshot(snapshot)
        kept_snapshot_ids = {id(item) for item in push_state.snapshots}
        for old_snapshot in old_stack:
            if id(old_snapshot) not in kept_snapshot_ids:
                _state._release_geometry_history_snapshot(old_snapshot)
        _state.geometry_undo_stack[:] = list(push_state.snapshots)
        _state._refresh_geometry_history_buttons()
    _state._push_geometry_undo_snapshot = _push_geometry_undo_snapshot

def _remaining_geometry_history_step_012(_state):

    def _pop_geometry_undo_snapshot() -> None:
        if _state.geometry_undo_stack:
            _state._release_geometry_history_snapshot(_state.geometry_undo_stack.pop())
        _state._refresh_geometry_history_buttons()
    _state._pop_geometry_undo_snapshot = _pop_geometry_undo_snapshot

def _remaining_geometry_history_step_013(_state):

    def _push_geometry_sparse_mesh_edit_snapshot(reason: str, sparse_snapshot: Mapping[str, Any]) -> bool:
        if not isinstance(sparse_snapshot, _state.Mapping):
            return False
        if sparse_snapshot.get('kind') != 'native_sparse_vertex_delta':
            return False
        before_positions = sparse_snapshot.get('before_positions_by_submesh')
        if not isinstance(before_positions, _state.Mapping) or not before_positions:
            return False
        snapshot = {'kind': 'native_sparse_vertex_delta', 'reason': str(reason or 'Mesh edit stroke'), 'before_positions_by_submesh': _state.copy.deepcopy(dict(before_positions)), 'mesh_edit_revision': int(sparse_snapshot.get('mesh_edit_revision', _state.mesh_edit_revision.get('value', 0)) or 0), 'source_geometry_revision': int(sparse_snapshot.get('source_geometry_revision', _state.source_geometry_revision.get('value', 0)) or 0), 'morph_slider_values': _state.copy.deepcopy(dict(sparse_snapshot.get('morph_slider_values', _state.morph_slider_values) or {})), 'morph_slider_post_edit_deltas': _state.copy.deepcopy(list(sparse_snapshot.get('morph_slider_post_edit_deltas', _state.morph_slider_post_edit_deltas) or ())), 'morph_slider_topology_blocked': _state.copy.deepcopy(dict(sparse_snapshot.get('morph_slider_topology_blocked', _state.morph_slider_topology_blocked) or {}))}
        old_stack = tuple(_state.geometry_undo_stack or ())
        push_state = _state._geometry_history_push_state_helper(_state.geometry_undo_stack, snapshot, guard_active=bool(_state.geometry_history_guard.get('active')))
        if not push_state.pushed:
            return False
        _state.retain_sparse_vertex_snapshot(snapshot)
        kept_snapshot_ids = {id(item) for item in push_state.snapshots}
        for old_snapshot in old_stack:
            if id(old_snapshot) not in kept_snapshot_ids:
                _state._release_geometry_history_snapshot(old_snapshot)
        _state.geometry_undo_stack[:] = list(push_state.snapshots)
        _state._refresh_geometry_history_buttons()
        return True
    _state._push_geometry_sparse_mesh_edit_snapshot = _push_geometry_sparse_mesh_edit_snapshot

def _remaining_geometry_history_step_014(_state):

    def _geometry_sparse_restore_source_indices(before_positions: object) -> tuple[int, ...]:
        if not isinstance(before_positions, _state.Mapping):
            return ()
        indices: set[int] = set()
        for raw_index in before_positions:
            try:
                source_index = int(raw_index)
            except (TypeError, ValueError, OverflowError):
                continue
            if source_index >= 0:
                indices.add(source_index)
        return tuple(sorted(indices))
    _state._geometry_sparse_restore_source_indices = _geometry_sparse_restore_source_indices

def _remaining_geometry_history_step_015(_state):

    def _geometry_source_index_tuple(source_indices: object) -> tuple[int, ...]:
        indices: set[int] = set()
        for raw_index in source_indices or ():
            try:
                source_index = int(raw_index)
            except (TypeError, ValueError, OverflowError):
                continue
            if source_index >= 0:
                indices.add(source_index)
        return tuple(sorted(indices))
    _state._geometry_source_index_tuple = _geometry_source_index_tuple

def _remaining_geometry_history_step_016(_state):

    def _geometry_python_sparse_restore_fallback_allowed(mesh: object, before_positions: object) -> bool:
        source_indices = _state._geometry_sparse_restore_source_indices(before_positions)
        message = 'Native geometry history restore failed; Python restore fallback is disabled.'
        _state._record_runtime_event('mesh_edit_geometry_python_sparse_restore_fallback_blocked', source_indices=source_indices, message=message)
        _state.self.set_status_message(message, error=True)
        return False
    _state._geometry_python_sparse_restore_fallback_allowed = _geometry_python_sparse_restore_fallback_allowed

def _remaining_geometry_history_step_017(_state):

    def _geometry_python_normal_fallback_allowed(mesh: object, source_indices: object) -> bool:
        message = 'Native geometry normal recompute failed; Python normal fallback is disabled.'
        normalized_source_indices = _state._geometry_source_index_tuple(source_indices)
        _state._record_runtime_event('mesh_edit_geometry_python_normals_fallback_blocked', source_indices=normalized_source_indices, message=message)
        _state.self.set_status_message(message, error=True)
        return False
    _state._geometry_python_normal_fallback_allowed = _geometry_python_normal_fallback_allowed

def _remaining_geometry_history_step_018(_state):

    def _geometry_d3d11_preview_active() -> bool:
        return bool(callable(_state._alignment_d3d11_preview_active) and _state._alignment_d3d11_preview_active())
    _state._geometry_d3d11_preview_active = _geometry_d3d11_preview_active

def _remaining_geometry_history_step_019(_state):

    def _geometry_mesh_edit_active() -> bool:
        if not callable(_state._alignment_mesh_edit_tab_active):
            return False
        return bool(_state._alignment_mesh_edit_tab_active())
    _state._geometry_mesh_edit_active = _geometry_mesh_edit_active

def _remaining_geometry_history_step_020(_state):

    def _geometry_history_restore_mutation_blocked() -> bool:
        if not _state._geometry_mesh_edit_active():
            return False
        message = 'Active Mesh Editor geometry history restore requires native history execution; Python state restore fallback is disabled.'
        _state._record_runtime_event('mesh_edit_geometry_history_python_state_restore_blocked', message=message)
        _state.self.set_status_message(message, error=True)
        return True
    _state._geometry_history_restore_mutation_blocked = _geometry_history_restore_mutation_blocked

def _remaining_geometry_history_step_021(_state):

    def _geometry_changed_vertex_range(raw_vertices: object) -> range | None:
        if isinstance(raw_vertices, range) and raw_vertices.step == 1:
            return raw_vertices
        if not isinstance(raw_vertices, _state.Mapping):
            return None
        for start_key, count_key in (('changed_vertex_start', 'changed_vertex_count'), ('source_vertex_start', 'source_vertex_count')):
            try:
                raw_start = raw_vertices.get(start_key, -1)
                raw_count = raw_vertices.get(count_key, 0)
                start = int(raw_start if raw_start is not None else -1)
                count = int(raw_count if raw_count is not None else 0)
            except (TypeError, ValueError, OverflowError):
                continue
            if start >= 0 and count >= 0:
                return range(start, start + count)
        return None
    _state._geometry_changed_vertex_range = _geometry_changed_vertex_range

def _remaining_geometry_history_step_022(_state):

    def _geometry_changed_vertex_groups_for_live_update(changed_vertices_by_submesh: object) -> dict[int, object]:
        if not isinstance(changed_vertices_by_submesh, _state.Mapping):
            return {}
        changed: dict[int, object] = {}
        for raw_submesh_index, raw_vertices in changed_vertices_by_submesh.items():
            try:
                submesh_index = int(raw_submesh_index)
            except (TypeError, ValueError, OverflowError):
                continue
            if submesh_index < 0:
                continue
            compact_range = _state._geometry_changed_vertex_range(raw_vertices)
            if compact_range is not None:
                changed[submesh_index] = compact_range
                continue
            if isinstance(raw_vertices, _state.Mapping):
                changed[submesh_index] = dict(raw_vertices)
                continue
            values: set[int] = set()
            for raw_index in raw_vertices or ():
                try:
                    vertex_index = int(raw_index)
                except (TypeError, ValueError, OverflowError):
                    continue
                if vertex_index >= 0:
                    values.add(vertex_index)
            if values:
                changed[submesh_index] = values
        return changed
    _state._geometry_changed_vertex_groups_for_live_update = _geometry_changed_vertex_groups_for_live_update

def _remaining_geometry_history_step_023(_state):

    def _geometry_refresh_sparse_restore_preview(changed_vertices_by_submesh: Mapping[int, object], *, include_normals: bool) -> None:
        if _state._geometry_d3d11_preview_active():
            live_preview_updater = _state.context.get('_mesh_edit_update_live_preview') or _state._mesh_edit_update_live_preview
            if callable(live_preview_updater):
                live_preview_updater(changed_vertices_by_submesh, include_normals=include_normals, immediate=True)
                return
            message = 'Native D3D11 mesh edit commands are unavailable; preview is stale. Reload D3D11 preview to resync.'
            _state._record_runtime_event('mesh_edit_geometry_sparse_restore_live_update_unavailable', source_indices=tuple(sorted((int(index) for index in changed_vertices_by_submesh))), message=message)
            _state.self.set_status_message(message, error=True)
            return
        if _state._geometry_mesh_edit_active():
            message = 'Active Mesh Editor geometry restore requires native D3D11 refresh; Python preview rebuild fallback is disabled.'
            _state._record_runtime_event('mesh_edit_geometry_sparse_restore_python_preview_rebuild_blocked', source_indices=tuple(sorted((int(index) for index in changed_vertices_by_submesh))), message=message)
            _state.self.set_status_message(message, error=True)
            return
        _state.state.replacement_preview_model = _state.parsed_mesh_to_preview_model(_state.state.replacement_mesh_for_mapping)
        _state._queue_static_preview_rebuild()
    _state._geometry_refresh_sparse_restore_preview = _geometry_refresh_sparse_restore_preview

def _remaining_geometry_history_step_024(_state):

    def _geometry_full_restore_source_indices() -> object:
        if callable(_state._mesh_edit_preview_source_indices):
            return _state._mesh_edit_preview_source_indices()
        mesh = _state.state.replacement_mesh_for_mapping
        return range(len(getattr(mesh, 'submeshes', ()) or ())) if mesh is not None else ()
    _state._geometry_full_restore_source_indices = _geometry_full_restore_source_indices

def _remaining_geometry_history_step_025(_state):

    def _geometry_refresh_full_restore_preview() -> None:
        if _state._geometry_d3d11_preview_active():
            if callable(_state._mesh_edit_replace_live_triangles_or_queue_rebuild):
                _state._mesh_edit_replace_live_triangles_or_queue_rebuild(_state._geometry_full_restore_source_indices(), replace_all=True)
                return
            live_preview_updater = _state.context.get('_mesh_edit_update_live_preview') or _state._mesh_edit_update_live_preview
            if callable(live_preview_updater):
                live_preview_updater(None, include_normals=True, immediate=True)
                return
            message = 'Native D3D11 mesh edit commands are unavailable; preview is stale. Reload D3D11 preview to resync.'
            _state._record_runtime_event('mesh_edit_geometry_full_restore_live_update_unavailable', message=message)
            _state.self.set_status_message(message, error=True)
            return
        if _state._geometry_mesh_edit_active():
            message = 'Active Mesh Editor geometry restore requires native D3D11 refresh; Python preview rebuild fallback is disabled.'
            _state._record_runtime_event('mesh_edit_geometry_full_restore_python_preview_rebuild_blocked', message=message)
            _state.self.set_status_message(message, error=True)
            return
        _state.state.replacement_preview_model = _state.parsed_mesh_to_preview_model(_state.state.replacement_mesh_for_mapping) if _state.state.replacement_mesh_for_mapping is not None else None
        _state._queue_static_preview_rebuild()
    _state._geometry_refresh_full_restore_preview = _geometry_refresh_full_restore_preview

def _remaining_geometry_history_step_026(_state):

    def _restore_sparse_mesh_edit_geometry_history_state(snapshot: Mapping[str, Any]) -> bool:
        if not isinstance(snapshot, _state.Mapping) or snapshot.get('kind') != 'native_sparse_vertex_delta':
            return False
        if _state.state.replacement_mesh_for_mapping is None:
            return False
        before_positions = snapshot.get('before_positions_by_submesh')
        if not isinstance(before_positions, _state.Mapping) or not before_positions:
            return False
        changed_vertices_by_submesh: dict[int, object] = {}
        try:
            from cdmw.services.mesh_workflow_service import apply_native_mesh_sparse_vertex_restore
            native_restore = apply_native_mesh_sparse_vertex_restore(_state.state.replacement_mesh_for_mapping, before_positions)
        except Exception:
            native_restore = None
        if native_restore is not None:
            changed_vertices_by_submesh = _state._geometry_changed_vertex_groups_for_live_update(native_restore or {})
        else:
            _state._geometry_python_sparse_restore_fallback_allowed(_state.state.replacement_mesh_for_mapping, before_positions)
            return False
        if not changed_vertices_by_submesh:
            return False
        normal_changed_vertices_by_submesh: dict[int, object] = {}
        include_normals = False
        try:
            from cdmw.services.mesh_workflow_service import apply_native_mesh_recalculate_normals
            native_normals = apply_native_mesh_recalculate_normals(_state.state.replacement_mesh_for_mapping, changed_vertices_by_submesh, return_changed_vertices=True)
        except Exception:
            native_normals = None
        if native_normals is not None:
            normal_changed_vertices_by_submesh = _state._geometry_changed_vertex_groups_for_live_update(native_normals or {})
            include_normals = bool(normal_changed_vertices_by_submesh)
        else:
            _state._geometry_python_normal_fallback_allowed(_state.state.replacement_mesh_for_mapping, changed_vertices_by_submesh)
        _state.static_preview_geometry_cache.clear()
        _state.static_preview_prepared_cache.clear()
        _state.mesh_edit_revision['value'] = int(snapshot.get('mesh_edit_revision', _state.mesh_edit_revision.get('value', 0)) or 0)
        _state.source_geometry_revision['value'] = int(snapshot.get('source_geometry_revision', _state.source_geometry_revision.get('value', 0)) or 0)
        _state.morph_slider_values.clear()
        _state.morph_slider_values.update(_state.copy.deepcopy(dict(snapshot.get('morph_slider_values', {}) or {})))
        _state.morph_slider_post_edit_deltas[:] = _state.copy.deepcopy(list(snapshot.get('morph_slider_post_edit_deltas', []) or ()))
        _state.morph_slider_topology_blocked.clear()
        _state.morph_slider_topology_blocked.update(dict(snapshot.get('morph_slider_topology_blocked', {}) or {}))
        _state.mesh_edit_active_stroke.clear()
        _state.mesh_edit_selected_vertices_by_submesh.clear()
        _state.mesh_edit_selected_faces_by_submesh.clear()
        if hasattr(_state.mesh_edit_selected_source_indices, 'clear'):
            _state.mesh_edit_selected_source_indices.clear()
        _state.clear_mesh_history_snapshot_stack(_state.mesh_edit_undo_stack)
        _state.clear_mesh_history_snapshot_stack(_state.mesh_edit_redo_stack)
        _state.mesh_edit_undo_adjustment_stack.clear()
        _state.mesh_edit_redo_adjustment_stack.clear()
        try:
            restored_morph_slider_post_edit_deltas = _state.copy.deepcopy(_state.morph_slider_post_edit_deltas)
            restored_morph_slider_topology_blocked = dict(_state.morph_slider_topology_blocked)
            _state._morph_slider_reload_profiles(preserve_values=True)
            _state.morph_slider_post_edit_deltas[:] = restored_morph_slider_post_edit_deltas
            _state.morph_slider_topology_blocked.clear()
            _state.morph_slider_topology_blocked.update(restored_morph_slider_topology_blocked)
            _state._morph_slider_refresh_controls()
        except NameError:
            pass
        _state.texture_overrides_dirty['dirty'] = True
        _state.state.texture_sets = _state.group_replacement_texture_sets(_state.texture_files_for_mapping, obj_mesh=_state.state.replacement_mesh_for_mapping)
        _state._apply_source_material_texture_overrides_to_ui_texture_sets(_state.state.texture_sets)
        _state._refresh_source_assignment_columns()
        _state._update_selection_context()
        _state._geometry_refresh_sparse_restore_preview(normal_changed_vertices_by_submesh or changed_vertices_by_submesh, include_normals=include_normals)
        return True
    _state._restore_sparse_mesh_edit_geometry_history_state = _restore_sparse_mesh_edit_geometry_history_state

def _remaining_geometry_history_step_027(_state):

    def _restore_geometry_history_state(snapshot: Mapping[str, Any]) -> None:
        if not snapshot:
            return
        _state.geometry_history_guard['active'] = True
        try:
            if _state._restore_sparse_mesh_edit_geometry_history_state(snapshot):
                return
            restore_state = _state._geometry_history_restore_state_helper(snapshot, default_texture_uv_global_transform_state=_state._default_texture_uv_transform_state('__global__'))
            if not restore_state.metadata_only and _state._geometry_history_restore_mutation_blocked():
                return
            replacement_mesh = restore_state.replacement_mesh
            replacement_base_mesh = restore_state.replacement_base_mesh
            if not restore_state.metadata_only:
                _state.state.replacement_mesh_for_mapping = _state._geometry_history_restore_mesh_snapshot(replacement_mesh)
                _state.state.replacement_mesh_base_for_mapping = _state._geometry_history_restore_mesh_snapshot(replacement_base_mesh)
            _state.source_part_adjustments.clear()
            _state.source_part_adjustments.update(_state.copy.deepcopy(restore_state.source_part_adjustments))
            _state.source_role_overrides.clear()
            _state.source_role_overrides.update(restore_state.source_role_overrides)
            _state.source_display_overrides.clear()
            _state.source_display_overrides.update(restore_state.source_display_overrides)
            _state._invalidate_source_display_cache()
            _state.original_part_copies[:] = list(_state.copy.deepcopy(restore_state.original_part_copies))
            _state.appended_source_indices.clear()
            _state.appended_source_indices.update(restore_state.appended_source_indices)
            _state.independent_output_source_indices.clear()
            _state.independent_output_source_indices.update(restore_state.independent_output_source_indices)
            _state.preview_only_source_indices.clear()
            _state.preview_only_source_indices.update(restore_state.preview_only_source_indices)
            _state.dialog_added_supplemental_files[:] = restore_state.dialog_added_supplemental_files
            _state.texture_files_for_mapping[:] = restore_state.texture_files_for_mapping
            _state.texture_override_assignments.clear()
            _state.texture_override_assignments.update(restore_state.texture_override_assignments)
            _state.source_material_texture_override_assignments.clear()
            _state.source_material_texture_override_assignments.update(restore_state.source_material_texture_override_assignments)
            _state.copied_original_texture_intents_by_source.clear()
            _state.copied_original_texture_intents_by_source.update(restore_state.copied_original_texture_intents_by_source)
            _state.copied_original_texture_disabled_sources.clear()
            _state.copied_original_texture_disabled_sources.update(restore_state.copied_original_texture_disabled_sources)
            _state.copied_original_source_indices.clear()
            _state.copied_original_source_indices.update(restore_state.copied_original_source_indices)
            _state.copied_original_source_to_original_index.clear()
            _state.copied_original_source_to_original_index.update(restore_state.copied_original_source_to_original_index)
            _state.copied_original_physics_sensitive_sources.clear()
            _state.copied_original_physics_sensitive_sources.update(restore_state.copied_original_physics_sensitive_sources)
            _state.texture_uv_transform_state.clear()
            _state.texture_uv_transform_state.update(restore_state.texture_uv_transform_state)
            _state._record_texture_uv_global_transform_state_helper(_state.texture_uv_global_transform_state, restore_state.texture_uv_global_transform_state)
            _restore_material_history_state(_state.context, restore_state.material_authority_state)
            _state.mesh_edit_revision['value'] = restore_state.mesh_edit_revision
            _state.source_geometry_revision['value'] = restore_state.source_geometry_revision
            _state.morph_slider_values.clear()
            _state.morph_slider_values.update(restore_state.morph_slider_values)
            _state.morph_slider_post_edit_deltas[:] = _state.copy.deepcopy(restore_state.morph_slider_post_edit_deltas)
            _state.morph_slider_topology_blocked.clear()
            _state.morph_slider_topology_blocked.update(restore_state.morph_slider_topology_blocked)
            _state.selected_source_part['index'] = restore_state.selected_source_index
            _state.selected_target_slot['index'] = restore_state.selected_target_index
            _state.selected_original_part['index'] = restore_state.selected_original_index
            _state.selected_source_highlight_indices.clear()
            _state.selected_source_highlight_indices.update(restore_state.selected_source_highlights)
            _state.selected_target_source_highlight_indices.clear()
            _state.selected_target_source_highlight_indices.update(restore_state.selected_target_source_highlights)
            _state.transform_source_indices.clear()
            _state.transform_source_indices.update(restore_state.transform_source_indices)
            _state.selected_original_highlight_indices.clear()
            _state.selected_original_highlight_indices.update(restore_state.selected_original_highlights)
            _state.selected_target_original_highlight_indices.clear()
            _state.selected_target_original_highlight_indices.update(restore_state.selected_target_original_highlights)
            for original_index, item in _state.original_items_by_index.items():
                item.setText(4, str(restore_state.original_copy_text_by_index.get(int(original_index), '')))
            mapping_text_by_target = restore_state.mapping_text_by_target
            for target_index, edit in _state.mapping_edits:
                edit.setText(str(mapping_text_by_target.get(int(target_index), '')))
                edit.setProperty('committed_mapping_text', edit.text().strip())
            _state._rebuild_source_part_widgets(restore_state.selected_source_indices, current_index=restore_state.selected_source_index)
            _state.static_preview_geometry_cache.clear()
            _state.static_preview_prepared_cache.clear()
            _state.mesh_edit_active_stroke.clear()
            _state.mesh_edit_selected_vertices_by_submesh.clear()
            _state.mesh_edit_selected_faces_by_submesh.clear()
            if hasattr(_state.mesh_edit_selected_source_indices, 'clear'):
                _state.mesh_edit_selected_source_indices.clear()
            if not restore_state.metadata_only:
                _state.clear_mesh_history_snapshot_stack(_state.mesh_edit_undo_stack)
                _state.clear_mesh_history_snapshot_stack(_state.mesh_edit_redo_stack)
                _state.mesh_edit_undo_adjustment_stack.clear()
                _state.mesh_edit_redo_adjustment_stack.clear()
            try:
                restored_morph_slider_post_edit_deltas = _state.copy.deepcopy(_state.morph_slider_post_edit_deltas)
                restored_morph_slider_topology_blocked = dict(_state.morph_slider_topology_blocked)
                _state._morph_slider_reload_profiles(preserve_values=True)
                _state.morph_slider_post_edit_deltas[:] = restored_morph_slider_post_edit_deltas
                _state.morph_slider_topology_blocked.clear()
                _state.morph_slider_topology_blocked.update(restored_morph_slider_topology_blocked)
                _state._morph_slider_refresh_controls()
            except NameError:
                pass
            _state.texture_overrides_dirty['dirty'] = True
            _state.state.texture_sets = _state.group_replacement_texture_sets(_state.texture_files_for_mapping, obj_mesh=_state.state.replacement_mesh_for_mapping)
            _state._apply_source_material_texture_overrides_to_ui_texture_sets(_state.state.texture_sets)
            _state._sync_highlight_sets()
            _state._refresh_original_reference_preview()
            _state._refresh_source_assignment_columns()
            try:
                _state._refresh_texture_row_guidance()
                _state._refresh_texture_table(_state.selected_texture_row.get('row'))
            except NameError:
                pass
            try:
                _state._refresh_texture_transform_editor()
            except NameError:
                pass
            _state._load_selected_part_controls()
            _state._update_mapping_status()
            _state._update_selection_context()
            resident_updated = False
            if restore_state.metadata_only:
                adjustment_type = _state.context.get('StaticSourcePartAdjustment')
                groups = source_part_material_parameter_groups_for_mesh(
                    _state.state.replacement_mesh_for_mapping, _state.source_part_adjustments, adjustment_type
                )
                resident_updated = send_resident_material_parameters(_state.context.get('dialog'), groups)
                flush_roles = _state.context.get('_flush_source_role_overrides_for_export')
                if callable(flush_roles):
                    flush_roles()
            if not resident_updated:
                _state._geometry_refresh_full_restore_preview()
        finally:
            _state.geometry_history_guard['active'] = False
            _state._refresh_geometry_history_buttons()
    _state._restore_geometry_history_state = _restore_geometry_history_state

def _remaining_geometry_history_step_028(_state):

    def _undo_geometry_change() -> None:
        if not _state.geometry_undo_stack:
            return
        snapshot = _state.geometry_undo_stack.pop()
        try:
            _state._restore_geometry_history_state(snapshot)
        finally:
            _state._release_geometry_history_snapshot(snapshot)
        _state.self.set_status_message(_state._geometry_undo_status_text_helper(snapshot.get('reason', 'Geometry change')))
    _state._undo_geometry_change = _undo_geometry_change

def _remaining_geometry_history_step_029(_state):

    def _reset_geometry_changes() -> None:
        if not _state.geometry_initial_snapshot:
            return
        _state._push_geometry_undo_snapshot('Reset Geometry')
        _state._restore_geometry_history_state(_state.geometry_initial_snapshot)
        _state._refresh_geometry_history_buttons()
        _state.self.set_status_message(_state._geometry_reset_status_text_helper())
    _state._reset_geometry_changes = _reset_geometry_changes

def _remaining_geometry_history_step_030(_state):

    def _capture_initial_geometry_snapshot() -> None:
        if _state.geometry_initial_snapshot:
            return
        _state.geometry_initial_snapshot.update(_state._capture_geometry_history_state('Initial Geometry'))
        _state._refresh_geometry_history_buttons()
    _state._capture_initial_geometry_snapshot = _capture_initial_geometry_snapshot

def _remaining_geometry_history_step_031(_state):

    def _flush_mapping_edit_refresh() -> None:
        _state.mapping_edit_refresh_timer.stop()
        if _state._geometry_mesh_edit_active():
            message = 'Active Mesh Editor mapping edits require native material execution; Python routing mutation fallback is disabled.'
            _state.self.set_status_message(message, error=True)
            return
        _state.texture_overrides_dirty['dirty'] = True
        _state._refresh_source_assignment_columns()
        _state._update_mapping_status()
        _state._update_selection_context()
        _state._queue_static_preview_rebuild()
    _state._flush_mapping_edit_refresh = _flush_mapping_edit_refresh

def _remaining_geometry_history_step_032(_state):
    _state._factory_result_values.update({'_capture_geometry_history_state': _state._capture_geometry_history_state, '_refresh_geometry_history_buttons': _state._refresh_geometry_history_buttons, '_push_geometry_undo_snapshot': _state._push_geometry_undo_snapshot, '_push_geometry_sparse_mesh_edit_snapshot': _state._push_geometry_sparse_mesh_edit_snapshot, '_pop_geometry_undo_snapshot': _state._pop_geometry_undo_snapshot, '_restore_geometry_history_state': _state._restore_geometry_history_state, '_undo_geometry_change': _state._undo_geometry_change, '_reset_geometry_changes': _state._reset_geometry_changes, '_capture_initial_geometry_snapshot': _state._capture_initial_geometry_snapshot, '_flush_mapping_edit_refresh': _state._flush_mapping_edit_refresh})

STEPS = (
    _remaining_geometry_history_step_001,
    _remaining_geometry_history_step_002,
    _remaining_geometry_history_step_003,
    _remaining_geometry_history_step_004,
    _remaining_geometry_history_step_005,
    _remaining_geometry_history_step_006,
    _remaining_geometry_history_step_007,
    _remaining_geometry_history_step_008,
    _remaining_geometry_history_step_009,
    _remaining_geometry_history_step_010,
    _remaining_geometry_history_step_011,
    _remaining_geometry_history_step_012,
    _remaining_geometry_history_step_013,
    _remaining_geometry_history_step_014,
    _remaining_geometry_history_step_015,
    _remaining_geometry_history_step_016,
    _remaining_geometry_history_step_017,
    _remaining_geometry_history_step_018,
    _remaining_geometry_history_step_019,
    _remaining_geometry_history_step_020,
    _remaining_geometry_history_step_021,
    _remaining_geometry_history_step_022,
    _remaining_geometry_history_step_023,
    _remaining_geometry_history_step_024,
    _remaining_geometry_history_step_025,
    _remaining_geometry_history_step_026,
    _remaining_geometry_history_step_027,
    _remaining_geometry_history_step_028,
    _remaining_geometry_history_step_029,
    _remaining_geometry_history_step_030,
    _remaining_geometry_history_step_031,
    _remaining_geometry_history_step_032,
)
