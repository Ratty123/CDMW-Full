from __future__ import annotations

def _transform_drag_step_001(_state):
    _state.Dict = _state.context.get('Dict')
    _state.List = _state.context.get('List')
    _state.Mapping = _state.context.get('Mapping')
    _state.NativePreviewPanel = _state.context.get('NativePreviewPanel')
    _state.Optional = _state.context.get('Optional')
    _state.QDoubleSpinBox = _state.context.get('QDoubleSpinBox')
    _state.Sequence = _state.context.get('Sequence')
    _state.StaticReplacementTransform = _state.context.get('StaticReplacementTransform')
    _state.StaticSourcePartAdjustment = _state.context.get('StaticSourcePartAdjustment')
    _state.Tuple = _state.context.get('Tuple')
    _state._add_vector3_delta_helper = _state.context.get('_add_vector3_delta_helper')
    _state._alignment_d3d11_active_transform_preview_key_helper = _state.context.get('_alignment_d3d11_active_transform_preview_key_helper')
    _state._alignment_d3d11_base_global_transform_helper = _state.context.get('_alignment_d3d11_base_global_transform_helper')
    _state._alignment_d3d11_base_part_transform_helper = _state.context.get('_alignment_d3d11_base_part_transform_helper')
    _state._alignment_d3d11_begin_drag_generation_helper = _state.context.get('_alignment_d3d11_begin_drag_generation_helper')
    _state._alignment_d3d11_commit_drag_generation_helper = _state.context.get('_alignment_d3d11_commit_drag_generation_helper')
    _state._alignment_d3d11_drag_part_source_indices_helper = _state.context.get('_alignment_d3d11_drag_part_source_indices_helper')
    _state._alignment_d3d11_drag_transform_update_state_helper = _state.context.get('_alignment_d3d11_drag_transform_update_state_helper')
    _state._alignment_d3d11_drag_ui_flush_state_helper = _state.context.get('_alignment_d3d11_drag_ui_flush_state_helper')
    _state._alignment_d3d11_drag_ui_queue_global_helper = _state.context.get('_alignment_d3d11_drag_ui_queue_global_helper')
    _state._alignment_d3d11_drag_ui_queue_part_helper = _state.context.get('_alignment_d3d11_drag_ui_queue_part_helper')
    _state._alignment_d3d11_drag_ui_take_helper = _state.context.get('_alignment_d3d11_drag_ui_take_helper')
    _state._alignment_d3d11_drag_ui_timer_state_helper = _state.context.get('_alignment_d3d11_drag_ui_timer_state_helper')
    _state._alignment_d3d11_editor_ids_for_source_indices = _state.context.get('_alignment_d3d11_editor_ids_for_source_indices')
    _state._alignment_d3d11_fast_transform_payload_helper = _state.context.get('_alignment_d3d11_fast_transform_payload_helper')
    _state._alignment_d3d11_fast_transform_queue_state_helper = _state.context.get('_alignment_d3d11_fast_transform_queue_state_helper')
    _state._alignment_d3d11_fast_transform_replay_state_helper = _state.context.get('_alignment_d3d11_fast_transform_replay_state_helper')
    _state._alignment_d3d11_fast_transform_send_state_helper = _state.context.get('_alignment_d3d11_fast_transform_send_state_helper')
    _state._alignment_d3d11_finish_drag_update_state_helper = _state.context.get('_alignment_d3d11_finish_drag_update_state_helper')
    _state._alignment_d3d11_global_control_state_helper = _state.context.get('_alignment_d3d11_global_control_state_helper')
    _state._alignment_d3d11_global_fast_preview_edit_range_helper = _state.context.get('_alignment_d3d11_global_fast_preview_edit_range_helper')
    _state._alignment_d3d11_package_refresh_in_flight = _state.context.get('_alignment_d3d11_package_refresh_in_flight')
    _state._alignment_d3d11_part_fast_preview_edit_indices_helper = _state.context.get('_alignment_d3d11_part_fast_preview_edit_indices_helper')
    _state._alignment_d3d11_preview_active = _state.context.get('_alignment_d3d11_preview_active')
    _state._alignment_d3d11_preview_scale_helper = _state.context.get('_alignment_d3d11_preview_scale_helper')
    _state._alignment_d3d11_selected_part_control_state_helper = _state.context.get('_alignment_d3d11_selected_part_control_state_helper')
    _state._alignment_d3d11_translation_to_transform_units_helper = _state.context.get('_alignment_d3d11_translation_to_transform_units_helper')
    _state._alignment_geometry_tab_active = _state.context.get('_alignment_geometry_tab_active')
    _state._alignment_mesh_edit_tab_active = _state.context.get('_alignment_mesh_edit_tab_active')
    _state._alignment_global_fast_preview_state_helper = _state.context.get('_alignment_global_fast_preview_state_helper')
    _state._alignment_global_rotation_origin_state_helper = _state.context.get('_alignment_global_rotation_origin_state_helper')
    _state._alignment_global_transform_spin_commit_state_helper = _state.context.get('_alignment_global_transform_spin_commit_state_helper')
    _state._alignment_linked_scale_sync_state_helper = _state.context.get('_alignment_linked_scale_sync_state_helper')
    _state._alignment_part_delta_refresh_state_helper = _state.context.get('_alignment_part_delta_refresh_state_helper')
    _state._alignment_part_fast_preview_state_helper = _state.context.get('_alignment_part_fast_preview_state_helper')
    _state._alignment_part_transform_preview_queue_indices_helper = _state.context.get('_alignment_part_transform_preview_queue_indices_helper')
    _state._alignment_preview_commit_state_helper = _state.context.get('_alignment_preview_commit_state_helper')
    _state._alignment_preview_drag_prepare_state_helper = _state.context.get('_alignment_preview_drag_prepare_state_helper')
    _state._alignment_preview_rotation_context_state_helper = _state.context.get('_alignment_preview_rotation_context_state_helper')
    _state._alignment_rotation_nudge_value_helper = _state.context.get('_alignment_rotation_nudge_value_helper')
    _state._alignment_transform_preview_queue_state_helper = _state.context.get('_alignment_transform_preview_queue_state_helper')
    _state._alignment_transform_reset_state_helper = _state.context.get('_alignment_transform_reset_state_helper')
    _state._capture_static_preview_baked_transform_state_helper = _state.context.get('_capture_static_preview_baked_transform_state_helper')
    _state._clear_alignment_d3d11_fast_transform_state = _state.context.get('_clear_alignment_d3d11_fast_transform_state')
    _state._commit_spinbox_text = _state.context.get('_commit_spinbox_text')
    _state._compute_anchor_alignment = _state.context.get('_compute_anchor_alignment')
    _state._current_alignment_transform_generation = _state.context.get('_current_alignment_transform_generation')
    _state._ensure_source_part_adjustment = _state.context.get('_ensure_source_part_adjustment')
    _state._load_selected_part_controls = _state.context.get('_load_selected_part_controls')
    _state._mark_alignment_transform_changed = _state.context.get('_mark_alignment_transform_changed')
    _state._mesh_edit_raw_preview_active = _state.context.get('_mesh_edit_raw_preview_active')
    _state._part_source_indices_for_commit_helper = _state.context.get('_part_source_indices_for_commit_helper')
    _state._push_geometry_undo_snapshot = _state.context.get('_push_geometry_undo_snapshot')
    _state._queue_static_preview_rebuild = _state.context.get('_queue_static_preview_rebuild')
    _state._record_runtime_event = _state.context.get('_record_runtime_event')
    _state._refresh_source_assignment_columns = _state.context.get('_refresh_source_assignment_columns')
    _state._run_static_preview_batch = _state.context.get('_run_static_preview_batch')
    _state._safe_alignment_timer_active = _state.context.get('_safe_alignment_timer_active')
    _state._safe_start_alignment_timer = _state.context.get('_safe_start_alignment_timer')
    _state._safe_stop_alignment_timer = _state.context.get('_safe_stop_alignment_timer')
    _state._set_double_spin_value_silently_helper = _state.context.get('_set_double_spin_value_silently_helper')
    _state._single_part_source_index_for_preview_helper = _state.context.get('_single_part_source_index_for_preview_helper')
    _state._source_part_transform_values_helper = _state.context.get('_source_part_transform_values_helper')
    _state._spinbox_transform_values_helper = _state.context.get('_spinbox_transform_values_helper')
    _state._sync_alignment_transform_slider_from_spin = _state.context.get('_sync_alignment_transform_slider_from_spin')
    _state._sync_part_slider_from_spin = _state.context.get('_sync_part_slider_from_spin')
    _state.alignment_d3d11_drag_generation = _state.context.get('alignment_d3d11_drag_generation')
    _state.alignment_d3d11_drag_transaction = _state.context.get('alignment_d3d11_drag_transaction') or {}
    _state.alignment_d3d11_drag_ui_state = _state.context.get('alignment_d3d11_drag_ui_state')
    _state.alignment_d3d11_drag_ui_timer = _state.context.get('alignment_d3d11_drag_ui_timer')
    _state.alignment_d3d11_preview_host = _state.context.get('alignment_d3d11_preview_host')
    _state.alignment_d3d11_state = _state.context.get('alignment_d3d11_state')
    _state.alignment_mode_combo = _state.context.get('alignment_mode_combo')
    _state.alignment_transform_generation = _state.context.get('alignment_transform_generation')
    _state.dialog = _state.context.get('dialog')
    _state.dialog_title = _state.context.get('dialog_title')
    _state.entry = _state.context.get('entry')
    _state.flip_direction_checkbox = _state.context.get('flip_direction_checkbox')
    _state.material_edit_refresh_timer = _state.context.get('material_edit_refresh_timer')
    _state.modify_original_clone_mode = _state.context.get('modify_original_clone_mode')
    _state.offset_x_spin = _state.context.get('offset_x_spin')
    _state.offset_y_spin = _state.context.get('offset_y_spin')
    _state.offset_z_spin = _state.context.get('offset_z_spin')
    _state.original_mesh_for_mapping = _state.context.get('original_mesh_for_mapping')
    _state.original_reference_preview_model = _state.context.get('original_reference_preview_model')
    _state.overlay_dialog_preview = _state.context.get('overlay_dialog_preview')
    _state.part_offset_x_spin = _state.context.get('part_offset_x_spin')
    _state.part_offset_y_spin = _state.context.get('part_offset_y_spin')
    _state.part_offset_z_spin = _state.context.get('part_offset_z_spin')
    _state.part_rotate_x_spin = _state.context.get('part_rotate_x_spin')

def _transform_drag_step_002(_state):
    _state.part_rotate_y_spin = _state.context.get('part_rotate_y_spin')
    _state.part_rotate_z_spin = _state.context.get('part_rotate_z_spin')
    _state.preview_mode_combo = _state.context.get('preview_mode_combo')
    _state.prompt_shell_context = _state.context.get('prompt_shell_context')
    _state.replacement_mesh_base_for_mapping = _state.context.get('replacement_mesh_base_for_mapping')
    _state.replacement_mesh_for_mapping = _state.context.get('replacement_mesh_for_mapping')
    _state.replacement_only_preview = _state.context.get('replacement_only_preview')
    _state.rotate_x_spin = _state.context.get('rotate_x_spin')
    _state.rotate_y_spin = _state.context.get('rotate_y_spin')
    _state.rotate_z_spin = _state.context.get('rotate_z_spin')
    _state.scale_link_checkbox = _state.context.get('scale_link_checkbox')
    _state.scale_spins = _state.context.get('scale_spins')
    _state.scale_syncing = _state.context.get('scale_syncing')
    _state.scale_to_length_checkbox = _state.context.get('scale_to_length_checkbox')
    _state.scale_x_spin = _state.context.get('scale_x_spin')
    _state.scale_y_spin = _state.context.get('scale_y_spin')
    _state.scale_z_spin = _state.context.get('scale_z_spin')
    _state.selected_source_part = _state.context.get('selected_source_part')
    _state.self = _state.context.get('self')
    _state.source_material_plan_refresh_timer = _state.context.get('source_material_plan_refresh_timer')
    _state.source_part_adjustments = _state.context.get('source_part_adjustments')
    _state.static_dialog_preview = _state.context.get('static_dialog_preview')
    _state.static_preview_baked_transform_state = _state.context.get('static_preview_baked_transform_state')
    _state.static_preview_interactive_until = _state.context.get('static_preview_interactive_until')
    _state.static_preview_refresh_timer = _state.context.get('static_preview_refresh_timer')
    _state.static_preview_settle_timer = _state.context.get('static_preview_settle_timer')
    _state.tilt_step_spin = _state.context.get('tilt_step_spin')
    _state.time = _state.context.get('time')
    _state.transform_source_indices = _state.context.get('transform_source_indices')

def _transform_drag_step_003(_state):

    def _d3d11_editor_ids_for_source_indices(indices: object, **kwargs: object) -> tuple[int, ...]:
        callback = _state._alignment_d3d11_editor_ids_for_source_indices
        if not callable(callback) and isinstance(_state.prompt_shell_context, dict):
            callback = _state.prompt_shell_context.get('_alignment_d3d11_editor_ids_for_source_indices')
        if not callable(callback):
            return ()
        return tuple((int(index) for index in tuple(callback(indices, **kwargs) or ())))
    _state._d3d11_editor_ids_for_source_indices = _d3d11_editor_ids_for_source_indices

def _transform_drag_step_004(_state):

    def _active_mesh_edit_transform_preview_queue_blocked(kind: str, event: str) -> bool:
        if not (callable(_state._mesh_edit_raw_preview_active) and _state._mesh_edit_raw_preview_active()):
            return False
        message = f'Active Mesh Editor static preview {kind} is disabled; native D3D11 preview payloads are required.'
        if callable(_state._record_runtime_event):
            _state._record_runtime_event(event, path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, reason=message)
        set_status_message = getattr(_state.self, 'set_status_message', None)
        if callable(set_status_message):
            set_status_message(message, error=True)
        return True
    _state._active_mesh_edit_transform_preview_queue_blocked = _active_mesh_edit_transform_preview_queue_blocked

def _transform_drag_step_005(_state):

    def _active_mesh_edit_part_adjustment_mutation_blocked(kind: str) -> bool:
        if not (callable(_state._alignment_mesh_edit_tab_active) and _state._alignment_mesh_edit_tab_active()):
            return False
        message = f'Active Mesh Editor source-part {kind} changes require native geometry execution; Python adjustment mutation fallback is disabled.'
        if callable(_state._record_runtime_event):
            _state._record_runtime_event('mesh_edit_source_part_adjustment_mutation_blocked', path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, reason=message)
        set_status_message = getattr(_state.self, 'set_status_message', None)
        if callable(set_status_message):
            set_status_message(message, error=True)
        return True
    _state._active_mesh_edit_part_adjustment_mutation_blocked = _active_mesh_edit_part_adjustment_mutation_blocked

def _transform_drag_step_006(_state):

    def _sync_linked_scale(value: float, source_spin: Optional[QDoubleSpinBox]=None) -> None:
        sender = source_spin if source_spin is not None else _state.dialog.sender()
        try:
            source_index = _state.scale_spins.index(sender)
        except ValueError:
            source_index = -1
        sync_state = _state._alignment_linked_scale_sync_state_helper(syncing_active=_state.scale_syncing['active'], link_enabled=_state.scale_link_checkbox.isChecked(), value=value, source_index=source_index, scale_count=len(_state.scale_spins))
        if not bool(sync_state['apply']):
            return
        _state.scale_syncing['active'] = True
        try:
            for target_index in tuple(sync_state['target_indices']):
                _state.scale_spins[int(target_index)].setValue(float(sync_state['value']))
        finally:
            _state.scale_syncing['active'] = False
    _state._sync_linked_scale = _sync_linked_scale

def _transform_drag_step_007(_state):

    def _commit_global_transform_spin(spin: QDoubleSpinBox) -> None:
        _state._commit_spinbox_text(spin)
        commit_state = _state._alignment_global_transform_spin_commit_state_helper(scale_spin=spin in _state.scale_spins, d3d11_preview_active=_state._alignment_d3d11_preview_active())
        if bool(commit_state['sync_linked_scale']):
            _state._sync_linked_scale(float(spin.value()), source_spin=spin)
        if bool(commit_state['queue_preview_update']):
            _state._queue_global_transform_preview_update()
            return
        if bool(commit_state['queue_static_rebuild']):
            _state._queue_static_preview_rebuild()
    _state._commit_global_transform_spin = _commit_global_transform_spin

def _transform_drag_step_008(_state):
    _state._global_transform_values = lambda: _state._spinbox_transform_values_helper((_state.offset_x_spin, _state.offset_y_spin, _state.offset_z_spin), (_state.rotate_x_spin, _state.rotate_y_spin, _state.rotate_z_spin), (_state.scale_x_spin, _state.scale_y_spin, _state.scale_z_spin), catch_runtime=False)
    _state._part_transform_values = lambda source_index: _state._source_part_transform_values_helper(_state.source_part_adjustments, source_index, _state.StaticSourcePartAdjustment)

def _transform_drag_step_009(_state):

    def _capture_static_preview_baked_transform_state(selected_preview_indices: Optional[Sequence[int]]=None, *, transform_generation: Optional[int]=None) -> None:
        capture_generation = int(transform_generation) if transform_generation is not None else _state._current_alignment_transform_generation()
        part_state: _state.Dict[int, object] = {}
        if _state.replacement_mesh_for_mapping is not None:
            for source_index in range(len(getattr(_state.replacement_mesh_for_mapping, 'submeshes', ()) or ())):
                part_state[source_index] = _state._part_transform_values(source_index)
        _state._capture_static_preview_baked_transform_state_helper(_state.static_preview_baked_transform_state, global_values=_state._global_transform_values(), part_values=part_state, selected_preview_indices=selected_preview_indices, transform_generation=capture_generation)
        committed_generation = int(_state.alignment_transform_generation.get('committed', 0) or 0)
        if not bool(_state.alignment_d3d11_drag_transaction.get('active')) and capture_generation >= committed_generation:
            if not _state._alignment_d3d11_package_refresh_in_flight():
                _state._clear_alignment_d3d11_fast_transform_state()
    _state._capture_static_preview_baked_transform_state = _capture_static_preview_baked_transform_state

def _transform_drag_step_010(_state):

    def _active_alignment_transform_preview_widgets() -> tuple[NativePreviewPanel, ...]:
        preview_key = _state._alignment_d3d11_active_transform_preview_key_helper(_state.preview_mode_combo.currentData())
        if preview_key == 'replacement_only':
            return (_state.replacement_only_preview,)
        if preview_key == 'overlay':
            return (_state.overlay_dialog_preview,)
        return (_state.static_dialog_preview,)
    _state._active_alignment_transform_preview_widgets = _active_alignment_transform_preview_widgets

def _transform_drag_step_011(_state):

    def _set_global_fast_preview_edit_scope(preview_widget: NativePreviewPanel) -> None:
        active_mode = str(_state.preview_mode_combo.currentData() or 'side_by_side')
        current_model = getattr(preview_widget, '_current_model', None)
        current_mesh_count = len(getattr(current_model, 'meshes', ()) or ())
        original_mesh_count = len(getattr(_state.original_reference_preview_model, 'meshes', ()) or ()) if _state.original_reference_preview_model is not None else None
        start, count = _state._alignment_d3d11_global_fast_preview_edit_range_helper(active_mode, original_mesh_count=original_mesh_count, current_mesh_count=current_mesh_count)
        preview_widget.set_alignment_editable_mesh_range(start, count)
    _state._set_global_fast_preview_edit_scope = _set_global_fast_preview_edit_scope

def _transform_drag_step_012(_state):

    def _set_part_fast_preview_edit_scope(preview_widget: NativePreviewPanel) -> None:
        selected_indices = _state.static_preview_baked_transform_state.get('selected_preview_indices')
        active_mode = str(_state.preview_mode_combo.currentData() or 'side_by_side')
        original_mesh_count = len(getattr(_state.original_reference_preview_model, 'meshes', ()) or ()) if _state.original_reference_preview_model is not None else None
        editable_indices = _state._alignment_d3d11_part_fast_preview_edit_indices_helper(selected_indices, active_mode, original_mesh_count=original_mesh_count)
        if editable_indices is None:
            return
        preview_widget.set_alignment_editable_mesh_indices(editable_indices)
    _state._set_part_fast_preview_edit_scope = _set_part_fast_preview_edit_scope

def _transform_drag_step_013(_state):

    def _queue_alignment_d3d11_fast_transform(*, source_submesh_indices: Sequence[int]=(), translation: Sequence[float]=(0.0, 0.0, 0.0), rotation_degrees: Sequence[float]=(0.0, 0.0, 0.0), scale_xyz: Sequence[float]=(1.0, 1.0, 1.0)) -> bool:
        transform_generation = _state._current_alignment_transform_generation() if callable(_state._current_alignment_transform_generation) else 0
        payload = _state._alignment_d3d11_fast_transform_payload_helper(source_submesh_indices=source_submesh_indices, translation=translation, rotation_degrees=rotation_degrees, scale_xyz=scale_xyz, transform_generation=transform_generation)
        preview_active = _state._alignment_d3d11_preview_active() if callable(_state._alignment_d3d11_preview_active) else False
        queue_state = _state._alignment_d3d11_fast_transform_queue_state_helper(_state.alignment_d3d11_state, payload, preview_active=preview_active, drag_active=bool(_state.alignment_d3d11_drag_transaction.get('active')))
        if not bool(queue_state['send_preview']):
            return False
        return _state._send_alignment_d3d11_fast_transform_state(scope_source_indices=tuple(queue_state['source_indices']))
    _state._queue_alignment_d3d11_fast_transform = _queue_alignment_d3d11_fast_transform

def _transform_drag_step_014(_state):

    def _send_alignment_d3d11_fast_transform_state(*, scope_source_indices: Optional[Sequence[int]]=None) -> bool:
        send_state = _state._alignment_d3d11_fast_transform_send_state_helper(_state.alignment_d3d11_state, _state._d3d11_editor_ids_for_source_indices, scope_source_indices=scope_source_indices)
        state_ok = True
        if bool(send_state['update_scope']):
            state_ok = _state.alignment_d3d11_preview_host.set_alignment_state(enabled=True, source_submesh_indices=tuple(send_state['scope_source_indices']), translation_sensitivity=0.85, rotation_degrees_per_pixel=0.18)
        transform_ok = _state.alignment_d3d11_preview_host.set_alignment_preview_transforms(translation=send_state['translation'], rotation_degrees=send_state['rotation_degrees'], scale_xyz=send_state['scale_xyz'], part_transforms=send_state['part_transforms'])
        return bool(state_ok and transform_ok)
    _state._send_alignment_d3d11_fast_transform_state = _send_alignment_d3d11_fast_transform_state

def _transform_drag_step_015(_state):

    def _replay_alignment_d3d11_fast_transform() -> None:
        package_quality = str(_state.alignment_d3d11_state.get('active_package_quality', '') or _state.alignment_d3d11_state.get('queued_package_quality', '') or _state.alignment_d3d11_state.get('pending_package_quality', '') or '').strip().lower()
        reload_reason = str(_state.alignment_d3d11_state.get('active_reason', '') or _state.alignment_d3d11_state.get('queued_reason', '') or _state.alignment_d3d11_state.get('pending_reason', '') or '')
        raw_geometry_conflict = bool(_state._mesh_edit_raw_preview_active()) and package_quality == 'mesh_edit_raw'
        replay_state = _state._alignment_d3d11_fast_transform_replay_state_helper(_state.alignment_d3d11_state, mesh_edit_raw_active=raw_geometry_conflict, preview_active=_state._alignment_d3d11_preview_active(), reload_reason=reload_reason, package_quality=package_quality)
        if bool(replay_state['clear_state']):
            _state._clear_alignment_d3d11_fast_transform_state()
            if bool(replay_state['reset_host']):
                _state.alignment_d3d11_preview_host.set_alignment_state(enabled=False, source_submesh_indices=(), translation_sensitivity=0.85, rotation_degrees_per_pixel=0.18)
                _state.alignment_d3d11_preview_host.set_alignment_preview_transform()
            return
        if not bool(replay_state['send_preview']):
            return
        _state._send_alignment_d3d11_fast_transform_state()
    _state._replay_alignment_d3d11_fast_transform = _replay_alignment_d3d11_fast_transform

def _transform_drag_step_016(_state):

    def _apply_global_transform_fast_preview() -> bool:
        baked = _state.static_preview_baked_transform_state.get('global')
        preview_scale = _state._alignment_d3d11_preview_scale_helper(_state.original_reference_preview_model)
        fast_preview_state = _state._alignment_global_fast_preview_state_helper(baked, _state._global_transform_values(), preview_scale=preview_scale, d3d11_active=_state._alignment_d3d11_preview_active(), drag_active=bool(_state.alignment_d3d11_drag_transaction.get('active')))
        if not bool(fast_preview_state['apply']):
            return False
        for preview_widget in _state._active_alignment_transform_preview_widgets():
            _state._set_global_fast_preview_edit_scope(preview_widget)
            base_rotation = tuple(fast_preview_state['base_rotation'])
            preview_widget.set_alignment_base_rotation_degrees(float(base_rotation[0]), float(base_rotation[1]), float(base_rotation[2]))
            preview_widget.set_alignment_rotation_origin_override(_state._current_global_rotation_origin_for_preview())
            preview_widget.set_alignment_committed_preview_transform(translation=fast_preview_state['translation'], rotation_degrees=fast_preview_state['rotation_degrees'], scale_xyz=fast_preview_state['scale_xyz'])
        if bool(fast_preview_state['queue_d3d11']):
            _state._queue_alignment_d3d11_fast_transform(source_submesh_indices=tuple(fast_preview_state['source_submesh_indices']), translation=fast_preview_state['translation'], rotation_degrees=fast_preview_state['rotation_degrees'], scale_xyz=fast_preview_state['scale_xyz'])
        return True
    _state._apply_global_transform_fast_preview = _apply_global_transform_fast_preview

def _transform_drag_step_017(_state):

    def _apply_part_transform_fast_preview(source_index: int) -> bool:
        parts = _state.static_preview_baked_transform_state.get('parts')
        baked = parts.get(source_index) if isinstance(parts, dict) else None
        preview_scale = _state._alignment_d3d11_preview_scale_helper(_state.original_reference_preview_model)
        fast_preview_state = _state._alignment_part_fast_preview_state_helper(int(source_index), baked, _state._part_transform_values(source_index), preview_scale=preview_scale, d3d11_active=_state._alignment_d3d11_preview_active(), drag_active=bool(_state.alignment_d3d11_drag_transaction.get('active')))
        if not bool(fast_preview_state['apply']):
            return False
        for preview_widget in _state._active_alignment_transform_preview_widgets():
            _state._set_part_fast_preview_edit_scope(preview_widget)
            base_rotation = tuple(fast_preview_state['base_rotation'])
            preview_widget.set_alignment_base_rotation_degrees(float(base_rotation[0]), float(base_rotation[1]), float(base_rotation[2]))
            preview_widget.set_alignment_rotation_origin_override(fast_preview_state['origin_override'])
            preview_widget.set_alignment_committed_preview_transform(translation=fast_preview_state['translation'], rotation_degrees=fast_preview_state['rotation_degrees'], scale_xyz=fast_preview_state['scale_xyz'])
        if bool(fast_preview_state['queue_d3d11']):
            _state._queue_alignment_d3d11_fast_transform(source_submesh_indices=tuple(fast_preview_state['source_submesh_indices']), translation=fast_preview_state['translation'], rotation_degrees=fast_preview_state['rotation_degrees'], scale_xyz=fast_preview_state['scale_xyz'])
        return True
    _state._apply_part_transform_fast_preview = _apply_part_transform_fast_preview

def _transform_drag_step_018(_state):

    def _queue_global_transform_preview_update(*_args: object) -> None:
        _state._mark_alignment_transform_changed()
        queue_time = _state.time.monotonic()
        applied = _state._apply_global_transform_fast_preview()
        preview_queue_state = _state._alignment_transform_preview_queue_state_helper(now=queue_time, applied=applied)
        _state.static_preview_interactive_until['time'] = float(preview_queue_state['interactive_until'])
        if bool(preview_queue_state['start_timer']) and (not _state._active_mesh_edit_transform_preview_queue_blocked('transform refresh', 'mesh_edit_static_preview_transform_refresh_blocked')):
            _state.static_preview_refresh_timer.start()
    _state._queue_global_transform_preview_update = _queue_global_transform_preview_update

def _transform_drag_step_019(_state):

    def _queue_part_transform_preview_update(source_index: object) -> None:
        _state._mark_alignment_transform_changed()
        queue_time = _state.time.monotonic()
        source_indices = _state._alignment_part_transform_preview_queue_indices_helper(source_index)
        applied = False
        for index in source_indices:
            applied = bool(_state._apply_part_transform_fast_preview(int(index))) or applied
        preview_queue_state = _state._alignment_transform_preview_queue_state_helper(now=queue_time, applied=applied)
        _state.static_preview_interactive_until['time'] = float(preview_queue_state['interactive_until'])
        if bool(preview_queue_state['start_timer']) and (not _state._active_mesh_edit_transform_preview_queue_blocked('transform refresh', 'mesh_edit_static_preview_transform_refresh_blocked')):
            _state.static_preview_refresh_timer.start()
    _state._queue_part_transform_preview_update = _queue_part_transform_preview_update

def _transform_drag_step_020(_state):
    for _state.spin in (_state.offset_x_spin, _state.offset_y_spin, _state.offset_z_spin, _state.rotate_x_spin, _state.rotate_y_spin, _state.rotate_z_spin, _state.scale_x_spin, _state.scale_y_spin, _state.scale_z_spin):
        _state.spin.valueChanged.connect(_state._queue_global_transform_preview_update)
        _state.spin.editingFinished.connect(lambda spin=spin: _state._commit_global_transform_spin(spin))
    for _state.spin in (_state.scale_x_spin, _state.scale_y_spin, _state.scale_z_spin):
        _state.spin.valueChanged.connect(_state._sync_linked_scale)
    _state.alignment_mode_combo.currentIndexChanged.connect(_state._queue_static_preview_rebuild)
    _state.scale_to_length_checkbox.toggled.connect(_state._queue_static_preview_rebuild)
    _state.flip_direction_checkbox.toggled.connect(_state._queue_static_preview_rebuild)
    if _state.modify_original_clone_mode:
        _state.alignment_mode_combo.setCurrentIndex(max(0, _state.alignment_mode_combo.findData('manual')))
        _state.scale_to_length_checkbox.setChecked(False)
        _state.flip_direction_checkbox.setChecked(False)

def _transform_drag_step_021(_state):

    def _apply_alignment_transform_reset_state(reset_state: Mapping[str, object]) -> None:
        alignment_mode = reset_state.get('alignment_mode')
        if isinstance(alignment_mode, str):
            _state.alignment_mode_combo.setCurrentIndex(max(0, _state.alignment_mode_combo.findData(alignment_mode)))
        scale_to_length = reset_state.get('scale_to_length')
        if isinstance(scale_to_length, bool):
            _state.scale_to_length_checkbox.setChecked(scale_to_length)
        flip_direction = reset_state.get('flip_direction')
        if isinstance(flip_direction, bool):
            _state.flip_direction_checkbox.setChecked(flip_direction)
        scale_link = reset_state.get('scale_link')
        if isinstance(scale_link, bool):
            _state.scale_link_checkbox.setChecked(scale_link)
        offset = reset_state.get('offset')
        if isinstance(offset, tuple):
            for spin, value in zip((_state.offset_x_spin, _state.offset_y_spin, _state.offset_z_spin), offset):
                spin.setValue(float(value))
        rotation = reset_state.get('rotation')
        if isinstance(rotation, tuple):
            for spin, value in zip((_state.rotate_x_spin, _state.rotate_y_spin, _state.rotate_z_spin), rotation):
                spin.setValue(float(value))
        scale = reset_state.get('scale')
        if isinstance(scale, tuple):
            for spin, value in zip((_state.scale_x_spin, _state.scale_y_spin, _state.scale_z_spin), scale):
                spin.setValue(float(value))
    _state._apply_alignment_transform_reset_state = _apply_alignment_transform_reset_state

def _transform_drag_step_022(_state):

    def _reset_location_values() -> None:

        def _apply() -> None:
            reset_state = _state._alignment_transform_reset_state_helper('location')
            _state._apply_alignment_transform_reset_state(reset_state)
            if bool(reset_state['queue_rebuild']):
                _state._queue_static_preview_rebuild()
        _state._run_static_preview_batch(_apply)
    _state._reset_location_values = _reset_location_values

def _transform_drag_step_023(_state):

    def _reset_rotation_values() -> None:

        def _apply() -> None:
            reset_state = _state._alignment_transform_reset_state_helper('rotation')
            _state._apply_alignment_transform_reset_state(reset_state)
            if bool(reset_state['queue_rebuild']):
                _state._queue_static_preview_rebuild()
        _state._run_static_preview_batch(_apply)
    _state._reset_rotation_values = _reset_rotation_values

def _transform_drag_step_024(_state):

    def _reset_scale_values() -> None:

        def _apply() -> None:
            reset_state = _state._alignment_transform_reset_state_helper('scale')
            _state._apply_alignment_transform_reset_state(reset_state)
            if bool(reset_state['queue_rebuild']):
                _state._queue_static_preview_rebuild()
        _state._run_static_preview_batch(_apply)
    _state._reset_scale_values = _reset_scale_values

def _transform_drag_step_025(_state):

    def _reset_placement_values() -> None:

        def _apply() -> None:
            reset_state = _state._alignment_transform_reset_state_helper('placement', modify_original_clone_mode=_state.modify_original_clone_mode)
            _state._apply_alignment_transform_reset_state(reset_state)
            if bool(reset_state['queue_rebuild']):
                _state._queue_static_preview_rebuild()
        _state._run_static_preview_batch(_apply)
    _state._reset_placement_values = _reset_placement_values

def _transform_drag_step_026(_state):

    def _nudge_rotation(spin: QDoubleSpinBox, direction: float) -> None:
        spin.setValue(_state._alignment_rotation_nudge_value_helper(spin.value(), direction, _state.tilt_step_spin.value()))
    _state._nudge_rotation = _nudge_rotation

def _transform_drag_step_027(_state):

    def _current_global_rotation_origin_for_preview() -> Optional[Tuple[float, float, float]]:
        if _state.original_reference_preview_model is None or _state.original_mesh_for_mapping is None:
            return None
        preview_replacement_mesh = _state.replacement_mesh_for_mapping or _state.replacement_mesh_base_for_mapping
        if preview_replacement_mesh is None:
            return None
        try:
            alignment = _state._compute_anchor_alignment(_state.original_mesh_for_mapping, preview_replacement_mesh, _state.StaticReplacementTransform(scale_to_original_length=bool(_state.scale_to_length_checkbox.isChecked()), alignment_mode=str(_state.alignment_mode_combo.currentData() or 'grid_flat'), flip_target_axis=bool(_state.flip_direction_checkbox.isChecked())))
            offset = (float(_state.offset_x_spin.value()), float(_state.offset_y_spin.value()), float(_state.offset_z_spin.value()))
            center = tuple(getattr(_state.original_reference_preview_model, 'normalization_center', (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0))
            while len(center) < 3:
                center = (*center, 0.0)
            return _state._alignment_global_rotation_origin_state_helper(alignment, offset_xyz=offset, normalization_center=center, normalization_scale=getattr(_state.original_reference_preview_model, 'normalization_scale', 1.0))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return None
    _state._current_global_rotation_origin_for_preview = _current_global_rotation_origin_for_preview

def _transform_drag_step_028(_state):

    def _alignment_part_source_indices_for_commit() -> List[int]:
        if not callable(_state._part_source_indices_for_commit_helper):
            return []
        geometry_tab_active = _state._alignment_geometry_tab_active() if callable(_state._alignment_geometry_tab_active) else False
        return list(_state._part_source_indices_for_commit_helper(_state.transform_source_indices, _state.replacement_mesh_for_mapping, geometry_tab_active=geometry_tab_active))
    _state._alignment_part_source_indices_for_commit = _alignment_part_source_indices_for_commit

def _transform_drag_step_029(_state):
    _state._alignment_single_part_source_index_for_preview = lambda: _state._single_part_source_index_for_preview_helper(_state._alignment_part_source_indices_for_commit())

def _transform_drag_step_030(_state):

    def _apply_alignment_part_translation_delta(source_indices: Sequence[int], delta_xyz: Sequence[float]) -> None:
        if _state._active_mesh_edit_part_adjustment_mutation_blocked('transform'):
            return
        for source_index in source_indices:
            adjustment = _state._ensure_source_part_adjustment(int(source_index))
            adjustment.offset_xyz = _state._add_vector3_delta_helper(adjustment.offset_xyz or (0.0, 0.0, 0.0), delta_xyz)
        refresh_state = _state._alignment_part_delta_refresh_state_helper(_state.selected_source_part.get('index', -1), source_indices)
        if bool(refresh_state['reload_selected_controls']):
            _state._load_selected_part_controls()
        if bool(refresh_state['refresh_source_columns']):
            _state._refresh_source_assignment_columns(lightweight=True)
        if bool(refresh_state['queue_part_preview']):
            _state._queue_part_transform_preview_update(tuple(refresh_state['source_indices']))
    _state._apply_alignment_part_translation_delta = _apply_alignment_part_translation_delta

def _transform_drag_step_031(_state):

    def _apply_alignment_part_rotation_delta(source_indices: Sequence[int], delta_xyz: Sequence[float]) -> None:
        if _state._active_mesh_edit_part_adjustment_mutation_blocked('transform'):
            return
        for source_index in source_indices:
            adjustment = _state._ensure_source_part_adjustment(int(source_index))
            adjustment.rotate_xyz_degrees = _state._add_vector3_delta_helper(adjustment.rotate_xyz_degrees or (0.0, 0.0, 0.0), delta_xyz)
        refresh_state = _state._alignment_part_delta_refresh_state_helper(_state.selected_source_part.get('index', -1), source_indices)
        if bool(refresh_state['reload_selected_controls']):
            _state._load_selected_part_controls()
        if bool(refresh_state['refresh_source_columns']):
            _state._refresh_source_assignment_columns(lightweight=True)
        if bool(refresh_state['queue_part_preview']):
            _state._queue_part_transform_preview_update(tuple(refresh_state['source_indices']))
    _state._apply_alignment_part_rotation_delta = _apply_alignment_part_rotation_delta

def _transform_drag_step_032(_state):

    def _sync_alignment_preview_rotation_context(preview_widget: NativePreviewPanel) -> None:
        selected_index = _state._alignment_single_part_source_index_for_preview()
        part_rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
        if selected_index >= 0:
            adjustment = _state.source_part_adjustments.get(selected_index, _state.StaticSourcePartAdjustment(selected_index))
            part_rotation = tuple((float(value) for value in tuple(adjustment.rotate_xyz_degrees or (0.0, 0.0, 0.0))[:3]))
        rotation_state = _state._alignment_preview_rotation_context_state_helper(selected_index, part_rotation=part_rotation, global_rotation=(float(_state.rotate_x_spin.value()), float(_state.rotate_y_spin.value()), float(_state.rotate_z_spin.value())), global_origin=_state._current_global_rotation_origin_for_preview())
        rotation = rotation_state['base_rotation']
        if isinstance(rotation, tuple):
            preview_widget.set_alignment_base_rotation_degrees(rotation[0], rotation[1], rotation[2])
        preview_widget.set_alignment_rotation_origin_override(rotation_state['origin_override'])
    _state._sync_alignment_preview_rotation_context = _sync_alignment_preview_rotation_context

def _transform_drag_step_033(_state):

    def _prepare_alignment_preview_drag(preview_widget: NativePreviewPanel) -> None:
        _state._safe_stop_alignment_timer(_state.material_edit_refresh_timer)
        _state._safe_stop_alignment_timer(_state.source_material_plan_refresh_timer)
        _state._safe_stop_alignment_timer(_state.static_preview_refresh_timer)
        _state._safe_stop_alignment_timer(_state.static_preview_settle_timer)
        prepare_state = _state._alignment_preview_drag_prepare_state_helper(_state._alignment_part_source_indices_for_commit(), undo_label='Preview part drag')
        if bool(prepare_state['push_undo']):
            _state._push_geometry_undo_snapshot(str(prepare_state['undo_label']))
        _state._sync_alignment_preview_rotation_context(preview_widget)
    _state._prepare_alignment_preview_drag = _prepare_alignment_preview_drag

def _transform_drag_step_034(_state):

    def _prepare_alignment_d3d11_preview_drag() -> None:
        _state._safe_stop_alignment_timer(_state.material_edit_refresh_timer)
        _state._safe_stop_alignment_timer(_state.source_material_plan_refresh_timer)
        _state._safe_stop_alignment_timer(_state.static_preview_refresh_timer)
        _state._safe_stop_alignment_timer(_state.static_preview_settle_timer)
        _state._safe_stop_alignment_timer(_state.alignment_d3d11_drag_ui_timer)
        _state._flush_alignment_d3d11_drag_ui()
        prepare_state = _state._alignment_preview_drag_prepare_state_helper(_state._alignment_part_source_indices_for_commit(), undo_label='D3D11 part drag')
        part_source_indices = tuple(prepare_state['part_source_indices'])
        if bool(prepare_state['push_undo']):
            _state._push_geometry_undo_snapshot(str(prepare_state['undo_label']))
        _state._alignment_d3d11_begin_drag_generation_helper(_state.alignment_d3d11_drag_generation, _state.alignment_d3d11_drag_transaction, part_source_indices=part_source_indices, global_values=_state._global_transform_values(), part_values_by_source_index={int(source_index): _state._part_transform_values(int(source_index)) for source_index in part_source_indices})
    _state._prepare_alignment_d3d11_preview_drag = _prepare_alignment_d3d11_preview_drag

def _transform_drag_step_035(_state):

    def _commit_alignment_d3d11_drag_generation() -> None:
        _state._alignment_d3d11_commit_drag_generation_helper(_state.alignment_d3d11_drag_generation, _state.alignment_d3d11_drag_transaction)
    _state._commit_alignment_d3d11_drag_generation = _commit_alignment_d3d11_drag_generation

def _transform_drag_step_036(_state):

    def _set_global_transform_values_for_d3d11_drag(*, offset: Optional[Sequence[float]]=None, rotation: Optional[Sequence[float]]=None) -> None:
        control_state = _state._alignment_d3d11_global_control_state_helper(offset=offset, rotation=rotation)
        if not bool(control_state['apply']):
            return
        normalized_offset = control_state['offset']
        if isinstance(normalized_offset, tuple):
            for spin, value in zip((_state.offset_x_spin, _state.offset_y_spin, _state.offset_z_spin), normalized_offset):
                _state._set_double_spin_value_silently_helper(spin, float(value))
                _state._sync_alignment_transform_slider_from_spin(spin)
        normalized_rotation = control_state['rotation']
        if isinstance(normalized_rotation, tuple):
            for spin, value in zip((_state.rotate_x_spin, _state.rotate_y_spin, _state.rotate_z_spin), normalized_rotation):
                _state._set_double_spin_value_silently_helper(spin, float(value))
                _state._sync_alignment_transform_slider_from_spin(spin)
    _state._set_global_transform_values_for_d3d11_drag = _set_global_transform_values_for_d3d11_drag

def _transform_drag_step_037(_state):

    def _queue_global_transform_values_for_d3d11_drag(*, offset: Optional[Sequence[float]]=None, rotation: Optional[Sequence[float]]=None) -> None:
        _state._alignment_d3d11_drag_ui_queue_global_helper(_state.alignment_d3d11_drag_ui_state, offset=offset, rotation=rotation)
        timer_state = _state._alignment_d3d11_drag_ui_timer_state_helper(active=_state._safe_alignment_timer_active(_state.alignment_d3d11_drag_ui_timer))
        if bool(timer_state['start_timer']):
            _state._safe_start_alignment_timer(_state.alignment_d3d11_drag_ui_timer)
    _state._queue_global_transform_values_for_d3d11_drag = _queue_global_transform_values_for_d3d11_drag

def _transform_drag_step_038(_state):

    def _set_selected_part_controls_for_d3d11_drag(source_index: int, *, offset: Optional[Sequence[float]]=None, rotation: Optional[Sequence[float]]=None) -> None:
        control_state = _state._alignment_d3d11_selected_part_control_state_helper(_state.selected_source_part.get('index', -1), source_index, offset=offset, rotation=rotation)
        if not bool(control_state['apply']):
            return
        normalized_offset = control_state['offset']
        if isinstance(normalized_offset, tuple):
            for spin, value in zip((_state.part_offset_x_spin, _state.part_offset_y_spin, _state.part_offset_z_spin), normalized_offset):
                _state._set_double_spin_value_silently_helper(spin, float(value))
                _state._sync_part_slider_from_spin(spin)
        normalized_rotation = control_state['rotation']
        if isinstance(normalized_rotation, tuple):
            for spin, value in zip((_state.part_rotate_x_spin, _state.part_rotate_y_spin, _state.part_rotate_z_spin), normalized_rotation):
                _state._set_double_spin_value_silently_helper(spin, float(value))
                _state._sync_part_slider_from_spin(spin)
    _state._set_selected_part_controls_for_d3d11_drag = _set_selected_part_controls_for_d3d11_drag

def _transform_drag_step_039(_state):

    def _queue_selected_part_controls_for_d3d11_drag(source_index: int, *, offset: Optional[Sequence[float]]=None, rotation: Optional[Sequence[float]]=None) -> None:
        _state._alignment_d3d11_drag_ui_queue_part_helper(_state.alignment_d3d11_drag_ui_state, source_index, offset=offset, rotation=rotation)
        timer_state = _state._alignment_d3d11_drag_ui_timer_state_helper(active=_state._safe_alignment_timer_active(_state.alignment_d3d11_drag_ui_timer))
        if bool(timer_state['start_timer']):
            _state._safe_start_alignment_timer(_state.alignment_d3d11_drag_ui_timer)
    _state._queue_selected_part_controls_for_d3d11_drag = _queue_selected_part_controls_for_d3d11_drag

def _transform_drag_step_040(_state):

    def _flush_alignment_d3d11_drag_ui() -> None:
        global_offset, global_rotation, controls = _state._alignment_d3d11_drag_ui_take_helper(_state.alignment_d3d11_drag_ui_state)
        flush_state = _state._alignment_d3d11_drag_ui_flush_state_helper(global_offset, global_rotation, controls)
        global_control = flush_state['global']
        if isinstance(global_control, _state.Mapping) and bool(global_control['apply']):
            _state._set_global_transform_values_for_d3d11_drag(offset=global_control['offset'] if isinstance(global_control['offset'], tuple) else None, rotation=global_control['rotation'] if isinstance(global_control['rotation'], tuple) else None)
        for values in tuple(flush_state['parts']):
            if isinstance(values, _state.Mapping):
                _state._set_selected_part_controls_for_d3d11_drag(int(values['source_index']), offset=values['offset'] if isinstance(values['offset'], tuple) else None, rotation=values['rotation'] if isinstance(values['rotation'], tuple) else None)
    _state._flush_alignment_d3d11_drag_ui = _flush_alignment_d3d11_drag_ui

def _transform_drag_step_041(_state):
    _state.alignment_d3d11_drag_ui_timer.timeout.connect(_state._flush_alignment_d3d11_drag_ui)
    _state._alignment_d3d11_base_global_transform = lambda: _state._alignment_d3d11_base_global_transform_helper(_state.alignment_d3d11_drag_transaction, _state._global_transform_values())
    _state._alignment_d3d11_base_part_transform = lambda source_index: _state._alignment_d3d11_base_part_transform_helper(_state.alignment_d3d11_drag_transaction, int(source_index), _state._part_transform_values(int(source_index)))

def _transform_drag_step_042(_state):

    def _alignment_d3d11_translation_to_transform_units(dx: float, dy: float, dz: float) -> tuple[float, float, float]:
        preview_scale = _state._alignment_d3d11_preview_scale_helper(_state.original_reference_preview_model)
        return _state._alignment_d3d11_translation_to_transform_units_helper((dx, dy, dz), preview_scale=preview_scale)
    _state._alignment_d3d11_translation_to_transform_units = _alignment_d3d11_translation_to_transform_units

def _transform_drag_step_043(_state):

    def _apply_alignment_d3d11_translation_total(dx: float, dy: float, dz: float) -> None:
        _state.static_preview_refresh_timer.stop()
        delta = _state._alignment_d3d11_translation_to_transform_units(dx, dy, dz)
        part_source_indices = _state._alignment_d3d11_drag_part_source_indices_helper(_state.alignment_d3d11_drag_transaction)
        if part_source_indices:
            if _state._active_mesh_edit_part_adjustment_mutation_blocked('D3D11 transform'):
                return
            update_state = _state._alignment_d3d11_drag_transform_update_state_helper(part_source_indices=part_source_indices, delta_xyz=delta, value_index=0, part_transform_values={int(source_index): _state._alignment_d3d11_base_part_transform(source_index) for source_index in part_source_indices})
            for source_index, new_offset in dict(update_state['part_values']).items():
                adjustment = _state._ensure_source_part_adjustment(int(source_index))
                adjustment.offset_xyz = new_offset
                _state._queue_selected_part_controls_for_d3d11_drag(int(source_index), offset=new_offset)
            return
        base_offset, _base_rotation, _base_scale = _state._alignment_d3d11_base_global_transform()
        update_state = _state._alignment_d3d11_drag_transform_update_state_helper(part_source_indices=(), delta_xyz=delta, value_index=0, global_base_values=base_offset)
        global_value = update_state['global_value']
        if isinstance(global_value, tuple):
            _state._queue_global_transform_values_for_d3d11_drag(offset=global_value)
    _state._apply_alignment_d3d11_translation_total = _apply_alignment_d3d11_translation_total

STEPS = (
    _transform_drag_step_001,
    _transform_drag_step_002,
    _transform_drag_step_003,
    _transform_drag_step_004,
    _transform_drag_step_005,
    _transform_drag_step_006,
    _transform_drag_step_007,
    _transform_drag_step_008,
    _transform_drag_step_009,
    _transform_drag_step_010,
    _transform_drag_step_011,
    _transform_drag_step_012,
    _transform_drag_step_013,
    _transform_drag_step_014,
    _transform_drag_step_015,
    _transform_drag_step_016,
    _transform_drag_step_017,
    _transform_drag_step_018,
    _transform_drag_step_019,
    _transform_drag_step_020,
    _transform_drag_step_021,
    _transform_drag_step_022,
    _transform_drag_step_023,
    _transform_drag_step_024,
    _transform_drag_step_025,
    _transform_drag_step_026,
    _transform_drag_step_027,
    _transform_drag_step_028,
    _transform_drag_step_029,
    _transform_drag_step_030,
    _transform_drag_step_031,
    _transform_drag_step_032,
    _transform_drag_step_033,
    _transform_drag_step_034,
    _transform_drag_step_035,
    _transform_drag_step_036,
    _transform_drag_step_037,
    _transform_drag_step_038,
    _transform_drag_step_039,
    _transform_drag_step_040,
    _transform_drag_step_041,
    _transform_drag_step_042,
    _transform_drag_step_043,
)
