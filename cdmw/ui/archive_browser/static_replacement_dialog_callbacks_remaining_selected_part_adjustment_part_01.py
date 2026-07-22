from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_dotnet_material_bridge import (
    resident_material_parameter_group,
    resident_material_parameters_available,
    send_resident_material_parameters,
)

def _remaining_selected_part_adjustment_step_001(_state):
    _state.state = _state._StaticReplacementDialogState(_state.context)
    _state.Qt = _state.context.get('Qt')
    _state.StaticSourcePartAdjustment = _state.context.get('StaticSourcePartAdjustment')
    _state._ensure_source_part_adjustment = _state.context.get('_ensure_source_part_adjustment')
    _state._push_geometry_undo_snapshot = _state.context.get('_push_geometry_undo_snapshot')
    _state._queue_part_transform_preview_update = _state.context.get('_queue_part_transform_preview_update')
    _state._queue_static_preview_rebuild = _state.context.get('_queue_static_preview_rebuild')
    _state._refresh_source_assignment_columns = _state.context.get('_refresh_source_assignment_columns')
    _state._selected_source_indices_from_tree = _state.context.get('_selected_source_indices_from_tree')
    _state._clear_source_parts_apply_pending = _state.context.get('_clear_source_parts_apply_pending')
    _state._set_source_parts_apply_pending = _state.context.get('_set_source_parts_apply_pending')
    _state._sync_highlight_sets = _state.context.get('_sync_highlight_sets')
    _state._alignment_d3d11_preview_active = _state.context.get('_alignment_d3d11_preview_active')
    _state._alignment_mesh_edit_tab_active = _state.context.get('_alignment_mesh_edit_tab_active')
    _state._source_part_adjustment_apply_state_helper = _state.context.get('_source_part_adjustment_apply_state_helper')
    _state._source_part_edit_undo_label_helper = _state.context.get('_source_part_edit_undo_label_helper')
    _state._source_part_include_exclude_pending_reason_helper = _state.context.get('_source_part_include_exclude_pending_reason_helper')
    _state.adjustment = _state.context.get('adjustment')
    _state.apply_state = _state.context.get('apply_state')
    _state.part_enabled_checkbox = _state.context.get('part_enabled_checkbox')
    _state.part_inspector_loading = _state.context.get('part_inspector_loading')
    _state.part_offset_x_spin = _state.context.get('part_offset_x_spin')
    _state.part_offset_y_spin = _state.context.get('part_offset_y_spin')
    _state.part_offset_z_spin = _state.context.get('part_offset_z_spin')
    _state.part_rotate_x_spin = _state.context.get('part_rotate_x_spin')
    _state.part_rotate_y_spin = _state.context.get('part_rotate_y_spin')
    _state.part_rotate_z_spin = _state.context.get('part_rotate_z_spin')
    _state.part_scale_x_spin = _state.context.get('part_scale_x_spin')
    _state.part_scale_y_spin = _state.context.get('part_scale_y_spin')
    _state.part_scale_z_spin = _state.context.get('part_scale_z_spin')
    _state.part_uniform_spin = _state.context.get('part_uniform_spin')
    _state.dialog = _state.context.get('dialog')
    _state.prompt_shell_context = _state.context.get('prompt_shell_context')
    _state.push_undo = _state.context.get('push_undo')
    _state.queue_preview = _state.context.get('queue_preview')
    _state.selected_source_part = _state.context.get('selected_source_part')
    _state.source_index = _state.context.get('source_index')
    _state.source_item = _state.context.get('source_item')
    _state.source_items_by_index = _state.context.get('source_items_by_index')
    _state.source_part_adjustments = _state.context.get('source_part_adjustments')
    _state.source_tree_item_update_guard = _state.context.get('source_tree_item_update_guard')
    _state.target_source_index = _state.context.get('target_source_index')
    _state.self = _state.context.get('self')

def _remaining_selected_part_adjustment_step_002(_state):

    def _selected_part_live_triangle_replacer() -> object:
        replacer = _state.context.get('_mesh_edit_replace_live_triangles_or_queue_rebuild')
        if callable(replacer):
            return replacer
        if isinstance(_state.prompt_shell_context, dict):
            replacer = _state.prompt_shell_context.get('_mesh_edit_replace_live_triangles_or_queue_rebuild')
            if callable(replacer):
                return replacer
        return None
    _state._selected_part_live_triangle_replacer = _selected_part_live_triangle_replacer

def _remaining_selected_part_adjustment_step_003(_state):

    def _selected_part_mesh_edit_active() -> bool:
        if not callable(_state._alignment_mesh_edit_tab_active):
            return False
        return bool(_state._alignment_mesh_edit_tab_active())
    _state._selected_part_mesh_edit_active = _selected_part_mesh_edit_active

def _remaining_selected_part_adjustment_step_004(_state):

    def _refresh_selected_part_enable_preview(source_indices: object) -> None:
        if callable(_state._sync_highlight_sets):
            _state._sync_highlight_sets()
        if callable(_state._alignment_d3d11_preview_active) and _state._alignment_d3d11_preview_active():
            replacer = _state._selected_part_live_triangle_replacer()
            if callable(replacer):
                replacer(source_indices)
                return
            set_status_message = getattr(_state.self, 'set_status_message', None)
            if callable(set_status_message):
                set_status_message('.NET/Vortice source enable preview commands are unavailable; preview is stale. Retry .NET/Vortice Preview to resync.', error=True)
            return
        if _state._selected_part_mesh_edit_active():
            set_status_message = getattr(_state.self, 'set_status_message', None)
            if callable(set_status_message):
                set_status_message('Active Mesh Editor source enable preview requires .NET/Vortice refresh; Python preview rebuild fallback is disabled.', error=True)
            return
        _state._set_source_parts_preview_rebuild_pending(_state._source_part_include_exclude_pending_reason_helper())
        _state._queue_static_preview_rebuild()
    _state._refresh_selected_part_enable_preview = _refresh_selected_part_enable_preview

def _remaining_selected_part_adjustment_step_005(_state):

    def _update_selected_part_adjustment(_signal_value: object=None, *, queue_preview: bool=True, push_undo: bool=True) -> bool:
        if _state.part_inspector_loading['active']:
            return False
        source_index = int(_state.selected_source_part.get('index', -1))
        apply_state = _state._source_part_adjustment_apply_state_helper(_state.source_part_adjustments, source_index=source_index, selected_source_indices=_state._selected_source_indices_from_tree(), enabled=bool(_state.part_enabled_checkbox.isChecked()), offset_xyz=(_state.part_offset_x_spin.value(), _state.part_offset_y_spin.value(), _state.part_offset_z_spin.value()), rotate_xyz_degrees=(_state.part_rotate_x_spin.value(), _state.part_rotate_y_spin.value(), _state.part_rotate_z_spin.value()), scale_xyz=(_state.part_scale_x_spin.value(), _state.part_scale_y_spin.value(), _state.part_scale_z_spin.value()), uniform_scale=_state.part_uniform_spin.value(), default_adjustment=_state.StaticSourcePartAdjustment)
        if not apply_state.available or not apply_state.changed:
            return False
        mesh_edit_active = _state._selected_part_mesh_edit_active()
        if mesh_edit_active and apply_state.geometry_changed:
            set_status_message = getattr(_state.self, 'set_status_message', None)
            if callable(set_status_message):
                set_status_message('Active Mesh Editor source-part transform changes require native geometry execution; Python adjustment mutation fallback is disabled.', error=True)
            return False
        if mesh_edit_active and apply_state.enabled_changed and not resident_material_parameters_available(_state.dialog):
            set_status_message = getattr(_state.self, 'set_status_message', None)
            if callable(set_status_message):
                set_status_message('Active Mesh Editor part visibility is unavailable until the resident material channel is ready.', error=True)
            return False
        if push_undo:
            _state._push_geometry_undo_snapshot(
                _state._source_part_edit_undo_label_helper('toggle' if apply_state.enabled_changed else 'adjust'),
                metadata_only=not apply_state.geometry_changed,
            )
        for target_source_index in apply_state.target_indices:
            adjustment = _state._ensure_source_part_adjustment(target_source_index)
            adjustment.enabled = apply_state.enabled
            adjustment.offset_xyz = apply_state.offset_xyz
            adjustment.rotate_xyz_degrees = apply_state.rotate_xyz_degrees
            adjustment.scale_xyz = apply_state.scale_xyz
            adjustment.uniform_scale = apply_state.uniform_scale
            source_item = _state.source_items_by_index.get(target_source_index)
            if source_item is not None:
                _state.source_tree_item_update_guard['active'] = True
                try:
                    source_item.setCheckState(0, _state.Qt.Checked if apply_state.enabled else _state.Qt.Unchecked)
                finally:
                    _state.source_tree_item_update_guard['active'] = False
        _state._refresh_source_assignment_columns(lightweight=not apply_state.enabled_changed)
        if queue_preview:
            if apply_state.enabled_changed:
                resident_updated = mesh_edit_active and send_resident_material_parameters(
                    _state.dialog,
                    tuple(
                        resident_material_parameter_group(
                            {'visible': bool(apply_state.enabled)},
                            source_submesh_indices=(target_source_index,),
                        )
                        for target_source_index in apply_state.target_indices
                    ),
                )
                if resident_updated:
                    if callable(_state._sync_highlight_sets):
                        _state._sync_highlight_sets()
                    if callable(_state._clear_source_parts_apply_pending):
                        _state._clear_source_parts_apply_pending()
                elif mesh_edit_active:
                    _state._set_source_parts_apply_pending(_state._source_part_include_exclude_pending_reason_helper())
                else:
                    _state._refresh_selected_part_enable_preview(apply_state.target_indices)
            else:
                _state._queue_part_transform_preview_update(tuple(apply_state.target_indices))
        return True
    _state._update_selected_part_adjustment = _update_selected_part_adjustment

def _remaining_selected_part_adjustment_step_006(_state):
    _state._factory_result_values.update({'_update_selected_part_adjustment': _state._update_selected_part_adjustment})

STEPS = (
    _remaining_selected_part_adjustment_step_001,
    _remaining_selected_part_adjustment_step_002,
    _remaining_selected_part_adjustment_step_003,
    _remaining_selected_part_adjustment_step_004,
    _remaining_selected_part_adjustment_step_005,
    _remaining_selected_part_adjustment_step_006,
)
