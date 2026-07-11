from __future__ import annotations

def _transform_drag_step_044(_state):

    def _apply_alignment_d3d11_rotation_total(dx: float, dy: float, dz: float) -> None:
        _state.static_preview_refresh_timer.stop()
        delta = (float(dx), float(dy), float(dz))
        part_source_indices = _state._alignment_d3d11_drag_part_source_indices_helper(_state.alignment_d3d11_drag_transaction)
        if part_source_indices:
            if _state._active_mesh_edit_part_adjustment_mutation_blocked('D3D11 transform'):
                return
            update_state = _state._alignment_d3d11_drag_transform_update_state_helper(part_source_indices=part_source_indices, delta_xyz=delta, value_index=1, part_transform_values={int(source_index): _state._alignment_d3d11_base_part_transform(source_index) for source_index in part_source_indices})
            for source_index, new_rotation in dict(update_state['part_values']).items():
                adjustment = _state._ensure_source_part_adjustment(int(source_index))
                adjustment.rotate_xyz_degrees = new_rotation
                _state._queue_selected_part_controls_for_d3d11_drag(int(source_index), rotation=new_rotation)
            return
        _base_offset, base_rotation, _base_scale = _state._alignment_d3d11_base_global_transform()
        update_state = _state._alignment_d3d11_drag_transform_update_state_helper(part_source_indices=(), delta_xyz=delta, value_index=1, global_base_values=base_rotation)
        global_value = update_state['global_value']
        if isinstance(global_value, tuple):
            _state._queue_global_transform_values_for_d3d11_drag(rotation=global_value)
    _state._apply_alignment_d3d11_rotation_total = _apply_alignment_d3d11_rotation_total

def _transform_drag_step_045(_state):

    def _finish_alignment_d3d11_translation(dx: float, dy: float, dz: float) -> None:
        _state._apply_alignment_d3d11_translation_total(dx, dy, dz)
        _state._safe_stop_alignment_timer(_state.alignment_d3d11_drag_ui_timer)
        _state._flush_alignment_d3d11_drag_ui()
        finish_state = _state._alignment_d3d11_finish_drag_update_state_helper(_state.alignment_d3d11_drag_generation, _state.alignment_d3d11_drag_transaction)
        if bool(finish_state['refresh_source_columns']):
            _state._refresh_source_assignment_columns(lightweight=True)
        if bool(finish_state['queue_part_preview']):
            _state._queue_part_transform_preview_update(tuple(finish_state['part_source_indices']))
        if bool(finish_state['queue_global_preview']):
            _state._queue_global_transform_preview_update()
        _state._replay_alignment_d3d11_fast_transform()
    _state._finish_alignment_d3d11_translation = _finish_alignment_d3d11_translation

def _transform_drag_step_046(_state):

    def _finish_alignment_d3d11_rotation(dx: float, dy: float, dz: float) -> None:
        _state._apply_alignment_d3d11_rotation_total(dx, dy, dz)
        _state._safe_stop_alignment_timer(_state.alignment_d3d11_drag_ui_timer)
        _state._flush_alignment_d3d11_drag_ui()
        finish_state = _state._alignment_d3d11_finish_drag_update_state_helper(_state.alignment_d3d11_drag_generation, _state.alignment_d3d11_drag_transaction)
        if bool(finish_state['refresh_source_columns']):
            _state._refresh_source_assignment_columns(lightweight=True)
        if bool(finish_state['queue_part_preview']):
            _state._queue_part_transform_preview_update(tuple(finish_state['part_source_indices']))
        if bool(finish_state['queue_global_preview']):
            _state._queue_global_transform_preview_update()
        _state._replay_alignment_d3d11_fast_transform()
    _state._finish_alignment_d3d11_rotation = _finish_alignment_d3d11_rotation

def _transform_drag_step_047(_state):

    def _commit_alignment_preview_translation(dx: float, dy: float, dz: float) -> None:
        _state.static_preview_refresh_timer.stop()
        commit_state = _state._alignment_preview_commit_state_helper(_state._alignment_part_source_indices_for_commit(), current_values=(float(_state.offset_x_spin.value()), float(_state.offset_y_spin.value()), float(_state.offset_z_spin.value())), delta_xyz=(dx, dy, dz))
        if commit_state['scope'] == 'parts':
            _state._apply_alignment_part_translation_delta(tuple(commit_state['part_source_indices']), (dx, dy, dz))
            return
        global_values = commit_state['global_values']
        if isinstance(global_values, tuple):
            for spin, value in zip((_state.offset_x_spin, _state.offset_y_spin, _state.offset_z_spin), global_values):
                _state._set_double_spin_value_silently_helper(spin, float(value))
                _state._sync_alignment_transform_slider_from_spin(spin)
        _state._queue_global_transform_preview_update()
    _state._commit_alignment_preview_translation = _commit_alignment_preview_translation

def _transform_drag_step_048(_state):

    def _commit_alignment_preview_rotation(dx: float, dy: float, dz: float) -> None:
        _state.static_preview_refresh_timer.stop()
        commit_state = _state._alignment_preview_commit_state_helper(_state._alignment_part_source_indices_for_commit(), current_values=(float(_state.rotate_x_spin.value()), float(_state.rotate_y_spin.value()), float(_state.rotate_z_spin.value())), delta_xyz=(dx, dy, dz))
        if commit_state['scope'] == 'parts':
            _state._apply_alignment_part_rotation_delta(tuple(commit_state['part_source_indices']), (dx, dy, dz))
            return
        global_values = commit_state['global_values']
        if isinstance(global_values, tuple):
            for spin, value in zip((_state.rotate_x_spin, _state.rotate_y_spin, _state.rotate_z_spin), global_values):
                _state._set_double_spin_value_silently_helper(spin, float(value))
                _state._sync_alignment_transform_slider_from_spin(spin)
        _state._queue_global_transform_preview_update()
    _state._commit_alignment_preview_rotation = _commit_alignment_preview_rotation

def _transform_drag_step_049(_state):
    _state._factory_result_values.update({'_sync_linked_scale': _state._sync_linked_scale, '_commit_global_transform_spin': _state._commit_global_transform_spin, '_global_transform_values': _state._global_transform_values, '_part_transform_values': _state._part_transform_values, '_capture_static_preview_baked_transform_state': _state._capture_static_preview_baked_transform_state, '_active_alignment_transform_preview_widgets': _state._active_alignment_transform_preview_widgets, '_set_global_fast_preview_edit_scope': _state._set_global_fast_preview_edit_scope, '_set_part_fast_preview_edit_scope': _state._set_part_fast_preview_edit_scope, '_queue_alignment_d3d11_fast_transform': _state._queue_alignment_d3d11_fast_transform, '_send_alignment_d3d11_fast_transform_state': _state._send_alignment_d3d11_fast_transform_state, '_replay_alignment_d3d11_fast_transform': _state._replay_alignment_d3d11_fast_transform, '_apply_global_transform_fast_preview': _state._apply_global_transform_fast_preview, '_apply_part_transform_fast_preview': _state._apply_part_transform_fast_preview, '_queue_global_transform_preview_update': _state._queue_global_transform_preview_update, '_queue_part_transform_preview_update': _state._queue_part_transform_preview_update, '_apply_alignment_transform_reset_state': _state._apply_alignment_transform_reset_state, '_reset_location_values': _state._reset_location_values, '_reset_rotation_values': _state._reset_rotation_values, '_reset_scale_values': _state._reset_scale_values, '_reset_placement_values': _state._reset_placement_values, '_nudge_rotation': _state._nudge_rotation, '_current_global_rotation_origin_for_preview': _state._current_global_rotation_origin_for_preview, '_alignment_part_source_indices_for_commit': _state._alignment_part_source_indices_for_commit, '_apply_alignment_part_translation_delta': _state._apply_alignment_part_translation_delta, '_apply_alignment_part_rotation_delta': _state._apply_alignment_part_rotation_delta, '_sync_alignment_preview_rotation_context': _state._sync_alignment_preview_rotation_context, '_prepare_alignment_preview_drag': _state._prepare_alignment_preview_drag, '_prepare_alignment_d3d11_preview_drag': _state._prepare_alignment_d3d11_preview_drag, '_commit_alignment_d3d11_drag_generation': _state._commit_alignment_d3d11_drag_generation, '_set_global_transform_values_for_d3d11_drag': _state._set_global_transform_values_for_d3d11_drag, '_queue_global_transform_values_for_d3d11_drag': _state._queue_global_transform_values_for_d3d11_drag, '_set_selected_part_controls_for_d3d11_drag': _state._set_selected_part_controls_for_d3d11_drag, '_queue_selected_part_controls_for_d3d11_drag': _state._queue_selected_part_controls_for_d3d11_drag, '_flush_alignment_d3d11_drag_ui': _state._flush_alignment_d3d11_drag_ui, '_alignment_d3d11_base_global_transform': _state._alignment_d3d11_base_global_transform, '_alignment_d3d11_base_part_transform': _state._alignment_d3d11_base_part_transform, '_alignment_d3d11_translation_to_transform_units': _state._alignment_d3d11_translation_to_transform_units, '_apply_alignment_d3d11_translation_total': _state._apply_alignment_d3d11_translation_total, '_apply_alignment_d3d11_rotation_total': _state._apply_alignment_d3d11_rotation_total, '_finish_alignment_d3d11_translation': _state._finish_alignment_d3d11_translation, '_finish_alignment_d3d11_rotation': _state._finish_alignment_d3d11_rotation, '_commit_alignment_preview_translation': _state._commit_alignment_preview_translation, '_commit_alignment_preview_rotation': _state._commit_alignment_preview_rotation})

STEPS = (
    _transform_drag_step_044,
    _transform_drag_step_045,
    _transform_drag_step_046,
    _transform_drag_step_047,
    _transform_drag_step_048,
    _transform_drag_step_049,
)
