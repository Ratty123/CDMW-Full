from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_dotnet_material_bridge import (
    resident_material_parameter_group,
    resident_material_parameters_available,
    send_resident_material_parameters,
    send_source_role_material_parameters,
    source_part_material_parameter_values,
)

def _selected_part_control_step_001(_state):
    _state.Qt = _state.context.get('Qt')
    _state.StaticSourcePartAdjustment = _state.context.get('StaticSourcePartAdjustment')
    _state._apply_current_glow_color_to_role_overrides = _state.context.get('_apply_current_glow_color_to_role_overrides')
    _state._alignment_mesh_edit_tab_active = _state.context.get('_alignment_mesh_edit_tab_active')
    _state._clear_transform_source_indices = _state.context.get('_clear_transform_source_indices')
    _state._copied_original_dds_badge = _state.context.get('_copied_original_dds_badge')
    _state._copied_original_texture_tooltip = _state.context.get('_copied_original_texture_tooltip')
    _state._current_dialog_mappings_for_preview = _state.context.get('_current_dialog_mappings_for_preview')
    _state._ensure_source_part_adjustment = _state.context.get('_ensure_source_part_adjustment')
    _state._ensure_material_authority_route_active = _state.context.get('_ensure_material_authority_route_active')
    _state._is_default_source_part_adjustment = _state.context.get('_is_default_source_part_adjustment')
    _state._alignment_d3d11_preview_active = _state.context.get('_alignment_d3d11_preview_active')
    _state._load_part_glow_color_controls = _state.context.get('_load_part_glow_color_controls')
    _state._mapped_source_indices = _state.context.get('_mapped_source_indices')
    _state._parse_mapping_edit = _state.context.get('_parse_mapping_edit')
    _state._part_mapped_target_indices = _state.context.get('_part_mapped_target_indices')
    _state._push_geometry_undo_snapshot = _state.context.get('_push_geometry_undo_snapshot')
    _state._queue_material_edit_refresh = _state.context.get('_queue_material_edit_refresh')
    _state._queue_material_authority_adjustment_preview_refresh = _state.context.get('_queue_material_authority_adjustment_preview_refresh')
    _state._queue_selection_preview_refresh = _state.context.get('_queue_selection_preview_refresh')
    _state._queue_static_preview_rebuild = _state.context.get('_queue_static_preview_rebuild')
    _state._queue_texture_preview_refresh = _state.context.get('_queue_texture_preview_refresh')
    _state._refresh_copied_original_texture_ui = _state.context.get('_refresh_copied_original_texture_ui')
    _state._refresh_mesh_edit_controls = _state.context.get('_refresh_mesh_edit_controls')
    _state._refresh_part_glow_color_controls_enabled = _state.context.get('_refresh_part_glow_color_controls_enabled')
    _state._refresh_parts_outliner = _state.context.get('_refresh_parts_outliner')
    _state._refresh_source_assignment_columns = _state.context.get('_refresh_source_assignment_columns')
    _state._refresh_ui_texture_sets_after_source_part_material_override = _state.context.get('_refresh_ui_texture_sets_after_source_part_material_override')
    _state._selected_source_indices_from_tree = _state.context.get('_selected_source_indices_from_tree')
    _state._selected_target_index = _state.context.get('_selected_target_index')
    _state._set_double_spin_value_silently_helper = _state.context.get('_set_double_spin_value_silently_helper')
    _state._set_mapping_indices = _state.context.get('_set_mapping_indices')
    _state._set_source_parts_apply_pending = _state.context.get('_set_source_parts_apply_pending')
    _state._set_source_parts_preview_rebuild_pending = _state.context.get('_set_source_parts_preview_rebuild_pending')
    _state._set_source_role_override_value = _state.context.get('_set_source_role_override_value')
    _state._modify_original_texture_tuning_enabled = _state.context.get('_modify_original_texture_tuning_enabled')
    _state._source_part_control_load_state_helper = _state.context.get('_source_part_control_load_state_helper')
    _state._source_part_control_state_helper = _state.context.get('_source_part_control_state_helper')
    _state._source_part_copied_texture_action_state_helper = _state.context.get('_source_part_copied_texture_action_state_helper')
    _state._source_part_copied_texture_controls_state_helper = _state.context.get('_source_part_copied_texture_controls_state_helper')
    _state._source_part_copied_texture_status_text_helper = _state.context.get('_source_part_copied_texture_status_text_helper')
    _state._source_part_display_label_helper = _state.context.get('_source_part_display_label_helper')
    _state._source_part_edit_undo_label_helper = _state.context.get('_source_part_edit_undo_label_helper')
    _state._source_part_glow_color_action_state_helper = _state.context.get('_source_part_glow_color_action_state_helper')
    _state._source_part_include_exclude_pending_reason_helper = _state.context.get('_source_part_include_exclude_pending_reason_helper')
    _state._source_part_map_to_target_state_helper = _state.context.get('_source_part_map_to_target_state_helper')
    _state._source_part_material_adjustment_state_helper = _state.context.get('_source_part_material_adjustment_state_helper')
    _state._source_part_output_action_state_helper = _state.context.get('_source_part_output_action_state_helper')
    _state._source_part_role_action_state_helper = _state.context.get('_source_part_role_action_state_helper')
    _state._source_part_selected_target_index_helper = _state.context.get('_source_part_selected_target_index_helper')
    _state._source_part_should_be_preview_only_after_unmap_helper = _state.context.get('_source_part_should_be_preview_only_after_unmap_helper')
    _state._source_part_source_combo_selection_state_helper = _state.context.get('_source_part_source_combo_selection_state_helper')
    _state._source_part_target_combo_selection_state_helper = _state.context.get('_source_part_target_combo_selection_state_helper')
    _state._source_part_unmap_target_states_helper = _state.context.get('_source_part_unmap_target_states_helper')
    _state._source_role_override_value = _state.context.get('_source_role_override_value')
    _state._source_target_summary = _state.context.get('_source_target_summary')
    _state._sync_highlight_sets = _state.context.get('_sync_highlight_sets')
    _state._sync_part_slider_from_spin = _state.context.get('_sync_part_slider_from_spin')
    _state._update_mapping_status = _state.context.get('_update_mapping_status')
    _state._update_selection_context = _state.context.get('_update_selection_context')
    _state.appended_source_indices = _state.context.get('appended_source_indices')
    _state.alignment_d3d11_preview_host = _state.context.get('alignment_d3d11_preview_host')
    _state.center_part_button = _state.context.get('center_part_button')
    _state.copied_original_texture_disabled_sources = _state.context.get('copied_original_texture_disabled_sources')
    _state.copied_original_texture_intents_by_source = _state.context.get('copied_original_texture_intents_by_source')
    _state.dialog = _state.context.get('dialog')
    _state.duplicate_part_button = _state.context.get('duplicate_part_button')
    _state.fit_part_button = _state.context.get('fit_part_button')
    _state.independent_output_source_indices = _state.context.get('independent_output_source_indices')
    _state.mapping_edits_by_target = _state.context.get('mapping_edits_by_target')
    _state.mapping_items_by_target = _state.context.get('mapping_items_by_target')
    _state.mapping_tree = _state.context.get('mapping_tree')
    _state.mirror_duplicate_part_button = _state.context.get('mirror_duplicate_part_button')
    _state.modify_original_clone_mode = _state.context.get('modify_original_clone_mode')
    _state.part_add_target_button = _state.context.get('part_add_target_button')
    _state.part_controls = _state.context.get('part_controls')
    _state.part_copied_texture_status_label = _state.context.get('part_copied_texture_status_label')
    _state.part_enabled_checkbox = _state.context.get('part_enabled_checkbox')
    _state.part_inspector_loading = _state.context.get('part_inspector_loading')
    _state.part_name_label = _state.context.get('part_name_label')
    _state.part_nudge_step_spin = _state.context.get('part_nudge_step_spin')
    _state.part_material_brightness_spin = _state.context.get('part_material_brightness_spin')
    _state.part_material_contrast_spin = _state.context.get('part_material_contrast_spin')
    _state.part_material_controls = _state.context.get('part_material_controls') or ()
    _state.part_material_gamma_spin = _state.context.get('part_material_gamma_spin')
    _state.part_material_saturation_spin = _state.context.get('part_material_saturation_spin')
    _state.QColor = _state.context.get('QColor')
    _state.QColorDialog = _state.context.get('QColorDialog')
    _state.part_emissive_checkbox = _state.context.get('part_emissive_checkbox')
    _state.part_emissive_pick_button = _state.context.get('part_emissive_pick_button')
    _state.part_emissive_strength_spin = _state.context.get('part_emissive_strength_spin')
    _state.part_role_combo = _state.context.get('part_role_combo')
    _state.part_material_colourise_pick_button = _state.context.get('part_material_colourise_pick_button')
    _state.part_material_colourise_strength_spin = _state.context.get('part_material_colourise_strength_spin')
    _state.part_material_colour_widgets = _state.context.get('part_material_colour_widgets') or ()
    _state.part_material_reset_button = _state.context.get('part_material_reset_button')
    _state.part_material_tint_pick_button = _state.context.get('part_material_tint_pick_button')
    _state.part_material_tint_b_spin = _state.context.get('part_material_tint_b_spin')
    _state.part_material_tint_g_spin = _state.context.get('part_material_tint_g_spin')
    _state.part_material_tint_r_spin = _state.context.get('part_material_tint_r_spin')
    _state.part_nudge_x_minus_button = _state.context.get('part_nudge_x_minus_button')
    _state.part_nudge_x_plus_button = _state.context.get('part_nudge_x_plus_button')
    _state.part_nudge_y_minus_button = _state.context.get('part_nudge_y_minus_button')
    _state.part_nudge_y_plus_button = _state.context.get('part_nudge_y_plus_button')
    _state.part_nudge_z_minus_button = _state.context.get('part_nudge_z_minus_button')
    _state.part_nudge_z_plus_button = _state.context.get('part_nudge_z_plus_button')
    _state.part_remove_copied_texture_button = _state.context.get('part_remove_copied_texture_button')
    _state.part_remove_target_button = _state.context.get('part_remove_target_button')
    _state.part_replace_target_button = _state.context.get('part_replace_target_button')
    _state.part_role_combo = _state.context.get('part_role_combo')
    _state.part_source_combo = _state.context.get('part_source_combo')
    _state.part_target_combo = _state.context.get('part_target_combo')
    _state.part_target_label = _state.context.get('part_target_label')
    _state.part_use_copied_texture_button = _state.context.get('part_use_copied_texture_button')

def _selected_part_control_step_002(_state):
    _state.part_use_route_texture_button = _state.context.get('part_use_route_texture_button')
    _state.preview_only_source_indices = _state.context.get('preview_only_source_indices')
    _state.remove_part_button = _state.context.get('remove_part_button')
    _state.replace = _state.context.get('replace')
    _state.replacement_mesh_for_mapping = _state.context.get('replacement_mesh_for_mapping')
    _state.reset_part_button = _state.context.get('reset_part_button')
    _state.selected_source_highlight_indices = _state.context.get('selected_source_highlight_indices')
    _state.selected_source_part = _state.context.get('selected_source_part')
    _state.source_items_by_index = _state.context.get('source_items_by_index')
    _state.source_part_adjustments = _state.context.get('source_part_adjustments')
    _state.source_part_inspector_control_text = _state.context.get('source_part_inspector_control_text')
    _state.source_part_transform_control_text = _state.context.get('source_part_transform_control_text')
    _state.source_role_overrides = _state.context.get('source_role_overrides')
    _state.source_tree = _state.context.get('source_tree')
    _state.source_tree_item_update_guard = _state.context.get('source_tree_item_update_guard')
    _state.texture_overrides_dirty = _state.context.get('texture_overrides_dirty')
    _state.self = _state.context.get('self')

def _selected_part_control_step_003(_state):

    def _refresh_selected_part_copied_texture_controls() -> None:
        source_index = int(_state.selected_source_part.get('index', -1))
        rows = _state.copied_original_texture_intents_by_source.get(source_index, []) if source_index >= 0 else []
        disabled = source_index in _state.copied_original_texture_disabled_sources
        has_rows = bool(rows)
        controls_state = _state._source_part_copied_texture_controls_state_helper(has_rows=has_rows, disabled=disabled)
        _state.part_copied_texture_status_label.setVisible(controls_state.visible)
        _state.part_use_copied_texture_button.setVisible(controls_state.visible)
        _state.part_use_route_texture_button.setVisible(controls_state.visible)
        _state.part_remove_copied_texture_button.setVisible(controls_state.visible)
        if not has_rows:
            _state.part_copied_texture_status_label.setText(_state._source_part_copied_texture_status_text_helper(has_rows=False))
            _state.part_copied_texture_status_label.setToolTip('')
        else:
            _state.part_copied_texture_status_label.setText(_state._source_part_copied_texture_status_text_helper(has_rows=True, disabled=disabled, copied_badge=_state._copied_original_dds_badge(source_index)))
            _state.part_copied_texture_status_label.setToolTip(_state._copied_original_texture_tooltip(source_index))
        _state.part_use_copied_texture_button.setEnabled(controls_state.use_copied_enabled)
        _state.part_use_route_texture_button.setEnabled(controls_state.use_route_enabled)
        _state.part_remove_copied_texture_button.setEnabled(controls_state.remove_enabled)
    _state._refresh_selected_part_copied_texture_controls = _refresh_selected_part_copied_texture_controls

def _selected_part_control_step_004(_state):

    def _material_tint_values(adjustment: object | None) -> tuple[int, int, int]:
        values = tuple(getattr(adjustment, 'material_tint_rgb', ()) or ())
        if not values:
            return (255, 255, 255)
        normalized: list[int] = []
        for value in values[:3]:
            try:
                normalized.append(max(0, min(255, int(round(float(value))))))
            except (TypeError, ValueError, OverflowError):
                normalized.append(255)
        while len(normalized) < 3:
            normalized.append(255)
        return (normalized[0], normalized[1], normalized[2])
    _state._material_tint_values = _material_tint_values

def _selected_part_control_step_005(_state):

    def _set_part_material_controls_enabled(enabled: bool) -> None:
        advanced_enabled = bool(enabled) and (not bool(_state.modify_original_clone_mode) or not callable(_state._modify_original_texture_tuning_enabled) or bool(_state._modify_original_texture_tuning_enabled()))
        # Colour controls follow the selection alone. Advanced texture tuning
        # gates only the brightness/contrast/saturation/gamma spins.
        colour_controls = {
            id(_state.part_material_tint_r_spin),
            id(_state.part_material_tint_g_spin),
            id(_state.part_material_tint_b_spin),
            id(_state.part_material_colourise_strength_spin),
        }
        for spin in tuple(_state.part_material_controls or ()):
            if hasattr(spin, 'setEnabled'):
                spin.setEnabled(bool(enabled) if id(spin) in colour_controls else advanced_enabled)
        for button in (_state.part_material_tint_pick_button, _state.part_material_colourise_pick_button, _state.part_material_reset_button):
            if button is not None and hasattr(button, 'setEnabled'):
                button.setEnabled(bool(enabled))
    _state._set_part_material_controls_enabled = _set_part_material_controls_enabled

def _selected_part_control_step_006(_state):

    def _set_part_material_controls(adjustment: object | None, *, enabled: bool) -> None:
        _state._set_part_material_controls_enabled(enabled)
        colourise_percent = round(100.0 * float(getattr(adjustment, 'material_colourise_strength', 0.0) or 0.0)) if adjustment is not None else 0.0
        values = (float(getattr(adjustment, 'material_brightness', 0.0) or 0.0) if adjustment is not None else 0.0, float(getattr(adjustment, 'material_contrast', 0.0) or 0.0) if adjustment is not None else 0.0, float(getattr(adjustment, 'material_saturation', 0.0) or 0.0) if adjustment is not None else 0.0, float(getattr(adjustment, 'material_gamma', 1.0) or 1.0) if adjustment is not None else 1.0, *_state._material_tint_values(adjustment), float(colourise_percent))
        for spin, value in zip(tuple(_state.part_material_controls or ()), values):
            _state._set_double_spin_value_silently_helper(spin, float(value))
            try:
                _state._sync_part_slider_from_spin(spin)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        _state._refresh_part_colour_swatches(adjustment, enabled=enabled)
        _state._refresh_part_emissive_controls(adjustment, enabled=enabled)
    _state._set_part_material_controls = _set_part_material_controls

def _selected_part_control_step_007(_state):

    def _material_live_values(material_state: object) -> dict[str, object]:
        return source_part_material_parameter_values(material_state)
    _state._material_live_values = _material_live_values

def _selected_part_control_step_008(_state):

    def _try_apply_selected_part_material_live_preview(material_state: object) -> bool:
        target_indices = tuple((int(index) for index in getattr(material_state, 'target_indices', ()) or ()))
        values = _state._material_live_values(material_state)
        group = resident_material_parameter_group(values, source_submesh_indices=target_indices)
        if send_resident_material_parameters(_state.dialog, (group,)):
            return True
        if not callable(_state._alignment_d3d11_preview_active) or not _state._alignment_d3d11_preview_active():
            return False
        if not hasattr(_state.alignment_d3d11_preview_host, 'set_material_overrides'):
            return False
        try:
            return bool(_state.alignment_d3d11_preview_host.set_material_overrides(source_submesh_indices=target_indices, editor_role='replacement_preview', **values))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
    _state._try_apply_selected_part_material_live_preview = _try_apply_selected_part_material_live_preview

def _selected_part_control_step_009(_state):

    def _active_mesh_edit_material_tuning_mutation_blocked() -> bool:
        if not (callable(_state._alignment_mesh_edit_tab_active) and _state._alignment_mesh_edit_tab_active()):
            return False
        if bool(getattr(_state.dialog, '_mesh_editor_embedded_dotnet_active', False)) and callable(
            getattr(_state.dialog, '_mesh_editor_embedded_apply_material_parameters', None)
        ):
            return False
        message = 'Active Mesh Editor source material tuning requires native material execution; Python adjustment mutation fallback is disabled.'
        set_status_message = getattr(_state.self, 'set_status_message', None)
        if callable(set_status_message):
            set_status_message(message, error=True)
        return True
    _state._active_mesh_edit_material_tuning_mutation_blocked = _active_mesh_edit_material_tuning_mutation_blocked

def _selected_part_control_step_010(_state):

    def _active_mesh_edit_copied_texture_mutation_blocked() -> bool:
        if not (callable(_state._alignment_mesh_edit_tab_active) and _state._alignment_mesh_edit_tab_active()):
            return False
        message = 'Active Mesh Editor copied-source texture routing requires native material execution; Python texture intent mutation fallback is disabled.'
        set_status_message = getattr(_state.self, 'set_status_message', None)
        if callable(set_status_message):
            set_status_message(message, error=True)
        return True
    _state._active_mesh_edit_copied_texture_mutation_blocked = _active_mesh_edit_copied_texture_mutation_blocked

def _selected_part_control_step_011(_state):

    def _active_mesh_edit_source_part_output_mutation_blocked(action: str) -> bool:
        if not (callable(_state._alignment_mesh_edit_tab_active) and _state._alignment_mesh_edit_tab_active()):
            return False
        if resident_material_parameters_available(_state.dialog):
            return False
        message = f'Active Mesh Editor source-part {action} requires native material execution; Python adjustment mutation fallback is disabled.'
        set_status_message = getattr(_state.self, 'set_status_message', None)
        if callable(set_status_message):
            set_status_message(message, error=True)
        return True
    _state._active_mesh_edit_source_part_output_mutation_blocked = _active_mesh_edit_source_part_output_mutation_blocked

def _selected_part_control_step_012(_state):

    def _update_selected_part_material_adjustment(_signal_value: object=None, *, push_undo: bool=True) -> bool:
        if _state.part_inspector_loading['active']:
            return False
        # Colour is authored regardless of the Modify Original advanced texture
        # tuning opt-in, and the advanced spins mirror the stored adjustment
        # while hidden, so writing them back stays an identity.
        source_index = int(_state.selected_source_part.get('index', -1))
        material_state = _state._source_part_material_adjustment_state_helper(_state.source_part_adjustments, source_index=source_index, selected_source_indices=_state._selected_source_indices_from_tree(), brightness=_state.part_material_brightness_spin.value(), contrast=_state.part_material_contrast_spin.value(), saturation=_state.part_material_saturation_spin.value(), gamma=_state.part_material_gamma_spin.value(), tint_rgb=(_state.part_material_tint_r_spin.value(), _state.part_material_tint_g_spin.value(), _state.part_material_tint_b_spin.value()), default_adjustment=_state.StaticSourcePartAdjustment, colourise_rgb=_state._part_colourise_rgb_from_controls(), colourise_strength=float(_state.part_material_colourise_strength_spin.value()) / 100.0)
        if not getattr(material_state, 'available', False) or not getattr(material_state, 'changed', False):
            return False
        if _state._active_mesh_edit_material_tuning_mutation_blocked():
            return False
        if push_undo:
            _state._push_geometry_undo_snapshot(_state._source_part_edit_undo_label_helper('material'), metadata_only=True)
        for target_source_index in tuple(getattr(material_state, 'target_indices', ()) or ()):
            adjustment = _state._ensure_source_part_adjustment(int(target_source_index))
            adjustment.material_brightness = float(material_state.brightness)
            adjustment.material_contrast = float(material_state.contrast)
            adjustment.material_saturation = float(material_state.saturation)
            adjustment.material_gamma = float(material_state.gamma)
            tint_rgb = tuple((int(value) for value in tuple(material_state.tint_rgb or ())[:3]))
            adjustment.material_tint_rgb = () if tint_rgb == (255, 255, 255) else tint_rgb
            colourise_strength = float(getattr(material_state, 'colourise_strength', 0.0) or 0.0)
            colourise_rgb = tuple((int(value) for value in tuple(getattr(material_state, 'colourise_rgb', ()) or ())[:3]))
            adjustment.material_colourise_strength = colourise_strength
            adjustment.material_colourise_rgb = colourise_rgb if colourise_strength > 0.0 else ()
            if callable(_state._is_default_source_part_adjustment) and _state._is_default_source_part_adjustment(adjustment):
                _state.source_part_adjustments.pop(int(target_source_index), None)
        _state.texture_overrides_dirty['dirty'] = True
        live_updated = _state._try_apply_selected_part_material_live_preview(material_state)
        _state._refresh_ui_texture_sets_after_source_part_material_override()
        if not live_updated:
            _state._queue_material_edit_refresh(refresh_plan=True, force_plan=False, refresh_preview=True, reason='source part material adjustment')
        return True
    _state._update_selected_part_material_adjustment = _update_selected_part_material_adjustment

def _selected_part_control_step_013(_state):

    def _use_copied_original_texture_for_selected_source() -> None:
        action_state = _state._source_part_copied_texture_action_state_helper(action='use_copied', source_index=_state.selected_source_part.get('index', -1), copied_source_indices=_state.copied_original_texture_intents_by_source.keys())
        if not action_state.available:
            return
        if _state._active_mesh_edit_copied_texture_mutation_blocked():
            return
        _state._push_geometry_undo_snapshot(action_state.undo_label)
        _state.copied_original_texture_disabled_sources.discard(action_state.source_index)
        _state.texture_overrides_dirty['dirty'] = action_state.mark_dirty
        _state._refresh_copied_original_texture_ui(action_state.source_index)
        _state._refresh_selected_part_copied_texture_controls()
        if action_state.queue_preview:
            _state._queue_texture_preview_refresh()
    _state._use_copied_original_texture_for_selected_source = _use_copied_original_texture_for_selected_source

def _selected_part_control_step_014(_state):

    def _use_route_texture_for_selected_copied_source() -> None:
        action_state = _state._source_part_copied_texture_action_state_helper(action='use_route', source_index=_state.selected_source_part.get('index', -1), copied_source_indices=_state.copied_original_texture_intents_by_source.keys())
        if not action_state.available:
            return
        if _state._active_mesh_edit_copied_texture_mutation_blocked():
            return
        _state._push_geometry_undo_snapshot(action_state.undo_label)
        if action_state.disable_copied_texture:
            _state.copied_original_texture_disabled_sources.add(action_state.source_index)
        _state.texture_overrides_dirty['dirty'] = action_state.mark_dirty
        _state._refresh_copied_original_texture_ui(action_state.source_index)
        _state._refresh_selected_part_copied_texture_controls()
        if action_state.queue_preview:
            _state._queue_texture_preview_refresh()
    _state._use_route_texture_for_selected_copied_source = _use_route_texture_for_selected_copied_source

def _selected_part_control_step_015(_state):

    def _remove_copied_texture_from_selected_source() -> None:
        action_state = _state._source_part_copied_texture_action_state_helper(action='remove', source_index=_state.selected_source_part.get('index', -1), copied_source_indices=_state.copied_original_texture_intents_by_source.keys())
        if not action_state.available:
            return
        if _state._active_mesh_edit_copied_texture_mutation_blocked():
            return
        _state._push_geometry_undo_snapshot(action_state.undo_label)
        if action_state.remove_intent:
            _state.copied_original_texture_intents_by_source.pop(action_state.source_index, None)
        _state.copied_original_texture_disabled_sources.discard(action_state.source_index)
        _state.texture_overrides_dirty['dirty'] = action_state.mark_dirty
        _state._refresh_copied_original_texture_ui(action_state.source_index)
        _state._refresh_selected_part_copied_texture_controls()
        if action_state.queue_preview:
            _state._queue_texture_preview_refresh()
    _state._remove_copied_texture_from_selected_source = _remove_copied_texture_from_selected_source

def _selected_part_control_step_016(_state):

    def _load_selected_part_controls() -> None:
        source_index = int(_state.selected_source_part.get('index', -1))
        _state.part_inspector_loading['active'] = True
        try:
            has_replacement_sources = _state.replacement_mesh_for_mapping is not None and bool(getattr(_state.replacement_mesh_for_mapping, 'submeshes', ()) or ())
            source_count = len(getattr(_state.replacement_mesh_for_mapping, 'submeshes', ()) or ())
            mapped_target_indices = _state._part_mapped_target_indices(source_index)
            selected_target_choice = _state._selected_target_index()
            source = _state.replacement_mesh_for_mapping.submeshes[source_index] if _state.replacement_mesh_for_mapping is not None and 0 <= source_index < source_count else None
            label = _state._source_part_display_label_helper(source_index, source, {}) if source is not None else ''
            adjustment = _state.source_part_adjustments.get(source_index, _state.StaticSourcePartAdjustment(source_index))
            selected_source_indices = _state._selected_source_indices_from_tree()
            load_state = _state._source_part_control_load_state_helper(source_index=source_index, source_count=source_count, has_replacement_sources=has_replacement_sources, current_target_choice=_state.part_target_combo.currentData(), mapped_target_indices=mapped_target_indices, selected_target_index=selected_target_choice, name_placeholder=_state.source_part_inspector_control_text['name_placeholder'], target_placeholder=_state.source_part_inspector_control_text['target_placeholder'], source_label=label, target_summary=_state._source_target_summary(source_index) if source is not None else '', role_value=_state._source_role_override_value(source_index) if source is not None else '', multi_selected_count=len(selected_source_indices), adjustment=adjustment if source is not None else None)
            control_state = load_state.control_state
            for spin in _state.part_controls:
                spin.setEnabled(control_state.has_source)
            _state._set_part_material_controls_enabled(control_state.has_source)
            _state.part_nudge_step_spin.setEnabled(control_state.has_source)
            for nudge_button in (_state.part_nudge_x_minus_button, _state.part_nudge_x_plus_button, _state.part_nudge_y_minus_button, _state.part_nudge_y_plus_button, _state.part_nudge_z_minus_button, _state.part_nudge_z_plus_button, _state.center_part_button):
                nudge_button.setEnabled(control_state.has_source)
            _state.part_source_combo.setEnabled(control_state.source_combo_enabled)
            _state.part_enabled_checkbox.setEnabled(control_state.has_source)
            _state.part_role_combo.setEnabled(control_state.has_source)
            _state.part_target_combo.setEnabled(control_state.has_source)
            _state.part_replace_target_button.setEnabled(control_state.target_choice_available)
            _state.part_add_target_button.setEnabled(control_state.target_choice_available)
            _state.part_remove_target_button.setEnabled(control_state.mapped_target_available)
            _state.remove_part_button.setEnabled(control_state.has_source)
            mesh_edit_active = bool(
                callable(_state._alignment_mesh_edit_tab_active)
                and _state._alignment_mesh_edit_tab_active()
            )
            _state.reset_part_button.setEnabled(control_state.has_source and not mesh_edit_active)
            if mesh_edit_active:
                _state.reset_part_button.setToolTip(
                    'Resident part reset is disabled until a native reset command is supported.'
                )
            else:
                _state.reset_part_button.setToolTip(_state.source_part_transform_control_text['reset_part_tooltip'])
            _state.fit_part_button.setEnabled(control_state.fit_part_enabled)
            _state.duplicate_part_button.setEnabled(control_state.has_source)
            _state.mirror_duplicate_part_button.setEnabled(control_state.has_source)
            _state._refresh_selected_part_copied_texture_controls()
            if not load_state.has_source:
                _state.part_name_label.setText(load_state.name_text)
                _state.part_target_label.setText(load_state.target_text)
                _state.part_source_combo.blockSignals(True)
                _state.part_source_combo.setCurrentIndex(0)
                _state.part_source_combo.blockSignals(False)
                _state.part_enabled_checkbox.setChecked(True)
                _state.part_role_combo.blockSignals(True)
                _state.part_role_combo.setCurrentIndex(0)
                _state.part_role_combo.blockSignals(False)
                _state._load_part_glow_color_controls(None)
                _state._set_part_material_controls(None, enabled=False)
                _state.part_target_combo.blockSignals(True)
                _state.part_target_combo.setCurrentIndex(0)
                _state.part_target_combo.blockSignals(False)
                for spin, value in zip(_state.part_controls, load_state.transform_values):
                    _state._set_double_spin_value_silently_helper(spin, value)
                    _state._sync_part_slider_from_spin(spin)
                _state._refresh_selected_part_copied_texture_controls()
                return
            _state.part_name_label.setText(load_state.name_text)
            _state.part_target_label.setText(load_state.target_text)
            _state.part_source_combo.blockSignals(True)
            part_source_combo_index = _state.part_source_combo.findData(load_state.source_combo_value)
            _state.part_source_combo.setCurrentIndex(max(0, part_source_combo_index))
            _state.part_source_combo.blockSignals(False)
            _state.part_enabled_checkbox.blockSignals(True)
            _state.part_enabled_checkbox.setChecked(load_state.enabled_checked)
            _state.part_enabled_checkbox.blockSignals(False)
            _state.part_role_combo.blockSignals(True)
            role_index = _state.part_role_combo.findData(load_state.role_value)
            _state.part_role_combo.setCurrentIndex(max(0, role_index))
            _state.part_role_combo.blockSignals(False)
            _state._load_part_glow_color_controls(adjustment)
            _state._set_part_material_controls(adjustment, enabled=True)
            _state.part_target_combo.blockSignals(True)
            target_combo_index = _state.part_target_combo.findData(load_state.target_choice)
            _state.part_target_combo.setCurrentIndex(max(0, target_combo_index))
            _state.part_target_combo.blockSignals(False)
            raw_target_choice = _state.part_target_combo.currentData()
            loaded_control_state = _state._source_part_control_state_helper(source_index=source_index, has_replacement_sources=has_replacement_sources, target_choice=raw_target_choice, mapped_target_indices=mapped_target_indices, selected_target_index=selected_target_choice)
            _state.part_replace_target_button.setEnabled(loaded_control_state.target_choice_available)
            _state.part_add_target_button.setEnabled(loaded_control_state.target_choice_available)
            _state.part_remove_target_button.setEnabled(loaded_control_state.mapped_target_available)
            _state.remove_part_button.setEnabled(loaded_control_state.has_source)
            for spin, value in zip(_state.part_controls, load_state.transform_values):
                _state._set_double_spin_value_silently_helper(spin, value)
                _state._sync_part_slider_from_spin(spin)
            _state._refresh_selected_part_copied_texture_controls()
        finally:
            _state.part_inspector_loading['active'] = False
            try:
                if callable(_state._refresh_mesh_edit_controls):
                    _state._refresh_mesh_edit_controls()
            except NameError:
                pass
    _state._load_selected_part_controls = _load_selected_part_controls

def _selected_part_control_step_017(_state):

    def _selected_part_source_changed(_index: int=-1) -> None:
        if _state.part_inspector_loading['active']:
            return
        selection_state = _state._source_part_source_combo_selection_state_helper(_state.part_source_combo.currentData(), available_source_indices=_state.source_items_by_index.keys())
        if selection_state.select_existing_source:
            source_item = _state.source_items_by_index.get(selection_state.source_index)
            _state.source_tree.clearSelection()
            source_item.setSelected(True)
            _state.source_tree.setCurrentItem(source_item)
            return
        _state.selected_source_part['index'] = -1
        _state.selected_source_highlight_indices.clear()
        _state._clear_transform_source_indices()
        _state._sync_highlight_sets()
        _state._load_selected_part_controls()
        _state._update_mapping_status()
        _state._queue_selection_preview_refresh()
    _state._selected_part_source_changed = _selected_part_source_changed

def _selected_part_control_step_018(_state):

    def _set_selected_source_role() -> None:
        if _state.part_inspector_loading['active']:
            return
        action_state = _state._source_part_role_action_state_helper(source_index=_state.selected_source_part.get('index', -1), role_value=_state.part_role_combo.currentData(), undo_label=_state._source_part_edit_undo_label_helper('role'))
        if not action_state.available:
            return
        if _state._active_mesh_edit_source_part_output_mutation_blocked('role change'):
            return
        _state._push_geometry_undo_snapshot(action_state.undo_label, metadata_only=True)
        # The role applies to the whole selection. Assigning it to the current
        # part alone left a multi-part selection unable to reach the glow
        # controls, which require every selected part to carry the role.
        try:
            role_indices = tuple(_state._selected_source_indices_from_tree())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            role_indices = ()
        if action_state.source_index not in role_indices:
            role_indices = (*role_indices, action_state.source_index)
        resident_updated = False
        for role_index in role_indices:
            _state._set_source_role_override_value(role_index, action_state.normalized_role)
            role_adjustment = _state.source_part_adjustments.get(role_index)
            resident_updated = send_source_role_material_parameters(
                _state.dialog,
                role_index,
                action_state.normalized_role,
                getattr(role_adjustment, 'emissive_color_rgb', ()) if role_adjustment is not None else (),
                emissive_strength=getattr(role_adjustment, 'emissive_strength', None) if role_adjustment is not None else None,
            ) or resident_updated
        _state._load_part_glow_color_controls(_state.source_part_adjustments.get(action_state.source_index))
        # Keep the inspector's Emits light box in step with the Role box, in
        # whichever direction the user changed it.
        _state._refresh_part_emissive_controls(
            _state.source_part_adjustments.get(action_state.source_index),
            enabled=True,
        )
        _state._refresh_source_assignment_columns(lightweight=True)
        try:
            _state._refresh_parts_outliner()
        except NameError:
            pass
        if callable(_state._queue_material_authority_adjustment_preview_refresh):
            _state._queue_material_authority_adjustment_preview_refresh(
                resource_keys=('part_glow_color', 'part_glow_strength'),
            )
        _state._queue_material_edit_refresh(refresh_plan=action_state.refresh_plan, force_plan=action_state.force_plan, refresh_preview=action_state.refresh_preview and not resident_updated, reason=action_state.refresh_reason)
    _state._set_selected_source_role = _set_selected_source_role

def _selected_part_control_step_019(_state):

    def _set_selected_source_glow_color() -> None:
        try:
            selected_indices = tuple(_state._selected_source_indices_from_tree())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            selected_indices = ()
        # Every selected glow part is edited; _apply_current_glow_color_to_role_overrides
        # skips any that do not carry the role.
        if not selected_indices:
            return
        if callable(_state._ensure_material_authority_route_active):
            _state._ensure_material_authority_route_active('source_part_glow_edit')
        action_state = _state._source_part_glow_color_action_state_helper()
        if _state._active_mesh_edit_source_part_output_mutation_blocked('glow override'):
            return
        _state._push_geometry_undo_snapshot(_state._source_part_edit_undo_label_helper(action_state.undo_action), metadata_only=True)
        _state._apply_current_glow_color_to_role_overrides()
        _state._refresh_ui_texture_sets_after_source_part_material_override()
        _state.texture_overrides_dirty['dirty'] = True
        _state._refresh_part_glow_color_controls_enabled()
        if callable(_state._queue_material_authority_adjustment_preview_refresh):
            _state._queue_material_authority_adjustment_preview_refresh(
                resource_keys=('part_glow_color', 'part_glow_strength'),
            )
        _state._queue_material_edit_refresh(refresh_plan=action_state.refresh_plan, force_plan=action_state.force_plan, refresh_preview=action_state.refresh_preview and not resident_material_parameters_available(_state.dialog), reason=action_state.refresh_reason)
    _state._set_selected_source_glow_color = _set_selected_source_glow_color

def _selected_part_control_step_020(_state):

    def _selected_part_target_index() -> int:
        return _state._source_part_selected_target_index_helper(_state.part_target_combo.currentData())
    _state._selected_part_target_index = _selected_part_target_index

def _selected_part_control_step_021(_state):

    def _select_part_target_row() -> None:
        if _state.part_inspector_loading['active']:
            return
        source_index = int(_state.selected_source_part.get('index', -1))
        selection_state = _state._source_part_target_combo_selection_state_helper(_state.part_target_combo.currentData(), source_index=source_index, mapped_target_indices=_state._part_mapped_target_indices(source_index))
        target_item = _state.mapping_items_by_target.get(selection_state.target_index)
        if target_item is not None:
            _state.mapping_tree.setCurrentItem(target_item)
        button_state = selection_state.button_state
        _state.part_replace_target_button.setEnabled(button_state.replace_enabled)
        _state.part_add_target_button.setEnabled(button_state.add_enabled)
        _state.part_remove_target_button.setEnabled(button_state.remove_enabled)
        _state._update_mapping_status()
        _state._update_selection_context()
    _state._select_part_target_row = _select_part_target_row

def _selected_part_control_step_022(_state):

    def _map_selected_part_to_combo_target(*, replace: bool) -> None:
        source_index = int(_state.selected_source_part.get('index', -1))
        target_index = _state._selected_part_target_index()
        edit = _state.mapping_edits_by_target.get(target_index)
        if edit is None:
            return
        map_state = _state._source_part_map_to_target_state_helper(source_index=source_index, target_index=target_index, current_indices=_state._parse_mapping_edit(edit), replace=replace)
        if not map_state.available:
            return
        target_item = _state.mapping_items_by_target.get(target_index)
        if target_item is not None:
            _state.mapping_tree.setCurrentItem(target_item)
        _state._set_mapping_indices(map_state.target_index, list(map_state.source_indices))
        _state._load_selected_part_controls()
    _state._map_selected_part_to_combo_target = _map_selected_part_to_combo_target

def _selected_part_control_step_023(_state):

    def _remove_selected_part_from_combo_target() -> None:
        source_index = int(_state.selected_source_part.get('index', -1))
        target_indices = _state._part_mapped_target_indices(source_index)
        if source_index < 0 or not target_indices:
            return
        target_source_indices = {int(target_index): tuple(_state._parse_mapping_edit(edit)) for target_index in target_indices for edit in (_state.mapping_edits_by_target.get(target_index),) if edit is not None}
        for unmap_state in _state._source_part_unmap_target_states_helper(source_index=source_index, target_indices=target_indices, target_source_indices=target_source_indices):
            _state._set_mapping_indices(unmap_state.target_index, list(unmap_state.remaining_source_indices), push_undo=unmap_state.push_undo, undo_label=_state._source_part_edit_undo_label_helper('unmap'), defer_preview=True)
        if _state._source_part_should_be_preview_only_after_unmap_helper(source_index=source_index, appended_source_indices=_state.appended_source_indices, mapped_source_indices=_state._mapped_source_indices(_state._current_dialog_mappings_for_preview())):
            _state.independent_output_source_indices.discard(source_index)
            _state.preview_only_source_indices.add(source_index)
        _state._load_selected_part_controls()
    _state._remove_selected_part_from_combo_target = _remove_selected_part_from_combo_target

def _selected_part_control_step_024(_state):

    def _reset_selected_part() -> None:
        source_index = int(_state.selected_source_part.get('index', -1))
        action_state = _state._source_part_output_action_state_helper(action='reset', source_index=source_index, selected_source_indices=_state._selected_source_indices_from_tree())
        if not action_state.available:
            return
        if callable(_state._alignment_mesh_edit_tab_active) and _state._alignment_mesh_edit_tab_active():
            set_status_message = getattr(_state.self, 'set_status_message', None)
            if callable(set_status_message):
                set_status_message('Resident part reset is disabled until a native reset command is supported.', error=True)
            return
        if _state._active_mesh_edit_source_part_output_mutation_blocked('reset'):
            return
        _state._push_geometry_undo_snapshot(_state._source_part_edit_undo_label_helper(action_state.undo_action), metadata_only=True)
        for target_source_index in action_state.target_indices:
            _state.source_part_adjustments.pop(target_source_index, None)
            _state.source_role_overrides.pop(target_source_index, None)
            source_item = _state.source_items_by_index.get(target_source_index)
            if source_item is not None:
                _state.source_tree_item_update_guard['active'] = True
                try:
                    source_item.setCheckState(0, _state.Qt.Checked if action_state.source_checked else _state.Qt.Unchecked)
                finally:
                    _state.source_tree_item_update_guard['active'] = False
        resident_updated = send_resident_material_parameters(
            _state.dialog,
            tuple(
                resident_material_parameter_group(
                    {
                        **source_part_material_parameter_values(_state.StaticSourcePartAdjustment(target_source_index)),
                        'visible': True,
                        'material_role': None,
                        'emissive_intensity': None,
                        'emissive_color': None,
                    },
                    source_submesh_indices=(target_source_index,),
                )
                for target_source_index in action_state.target_indices
            ),
        )
        _state._load_selected_part_controls()
        _state._refresh_source_assignment_columns()
        if resident_updated:
            _state._clear_source_parts_apply_pending()
        else:
            _state._queue_static_preview_rebuild()
    _state._reset_selected_part = _reset_selected_part

def _selected_part_control_step_025(_state):

    def _remove_selected_part_from_output() -> None:
        source_index = int(_state.selected_source_part.get('index', -1))
        action_state = _state._source_part_output_action_state_helper(action='remove', source_index=source_index, selected_source_indices=_state._selected_source_indices_from_tree())
        if not action_state.available:
            return
        if _state._active_mesh_edit_source_part_output_mutation_blocked('remove from output'):
            return
        _state._push_geometry_undo_snapshot(_state._source_part_edit_undo_label_helper(action_state.undo_action), metadata_only=True)
        for target_source_index in action_state.target_indices:
            adjustment = _state._ensure_source_part_adjustment(target_source_index)
            adjustment.enabled = False
            source_item = _state.source_items_by_index.get(target_source_index)
            if source_item is not None:
                _state.source_tree_item_update_guard['active'] = True
                try:
                    source_item.setCheckState(0, _state.Qt.Checked if action_state.source_checked else _state.Qt.Unchecked)
                finally:
                    _state.source_tree_item_update_guard['active'] = False
        resident_updated = send_resident_material_parameters(
            _state.dialog,
            tuple(
                resident_material_parameter_group({'visible': False}, source_submesh_indices=(target_source_index,))
                for target_source_index in action_state.target_indices
            ),
        )
        _state.part_enabled_checkbox.blockSignals(True)
        _state.part_enabled_checkbox.setChecked(action_state.part_enabled_checked)
        _state.part_enabled_checkbox.blockSignals(False)
        _state._refresh_source_assignment_columns()
        if callable(_state._sync_highlight_sets):
            _state._sync_highlight_sets()
        if resident_updated:
            _state._clear_source_parts_apply_pending()
        elif action_state.apply_pending:
            _state._set_source_parts_apply_pending(_state._source_part_include_exclude_pending_reason_helper())
        else:
            if callable(_state._set_source_parts_preview_rebuild_pending):
                _state._set_source_parts_preview_rebuild_pending(_state._source_part_include_exclude_pending_reason_helper())
            _state._queue_static_preview_rebuild()
    _state._remove_selected_part_from_output = _remove_selected_part_from_output

def _selected_part_control_step_026(_state):
    _state._factory_result_values.update({'_refresh_selected_part_copied_texture_controls': _state._refresh_selected_part_copied_texture_controls, '_use_copied_original_texture_for_selected_source': _state._use_copied_original_texture_for_selected_source, '_use_route_texture_for_selected_copied_source': _state._use_route_texture_for_selected_copied_source, '_remove_copied_texture_from_selected_source': _state._remove_copied_texture_from_selected_source, '_load_selected_part_controls': _state._load_selected_part_controls, '_selected_part_source_changed': _state._selected_part_source_changed, '_set_selected_source_role': _state._set_selected_source_role, '_set_selected_source_glow_color': _state._set_selected_source_glow_color, '_selected_part_target_index': _state._selected_part_target_index, '_select_part_target_row': _state._select_part_target_row, '_map_selected_part_to_combo_target': _state._map_selected_part_to_combo_target, '_remove_selected_part_from_combo_target': _state._remove_selected_part_from_combo_target, '_reset_selected_part': _state._reset_selected_part, '_remove_selected_part_from_output': _state._remove_selected_part_from_output, '_update_selected_part_material_adjustment': _state._update_selected_part_material_adjustment})

STEPS = (
    _selected_part_control_step_001,
    _selected_part_control_step_002,
    _selected_part_control_step_003,
    _selected_part_control_step_004,
    _selected_part_control_step_005,
    _selected_part_control_step_006,
    _selected_part_control_step_007,
    _selected_part_control_step_008,
    _selected_part_control_step_009,
    _selected_part_control_step_010,
    _selected_part_control_step_011,
    _selected_part_control_step_012,
    _selected_part_control_step_013,
    _selected_part_control_step_014,
    _selected_part_control_step_015,
    _selected_part_control_step_016,
    _selected_part_control_step_017,
    _selected_part_control_step_018,
    _selected_part_control_step_019,
    _selected_part_control_step_020,
    _selected_part_control_step_021,
    _selected_part_control_step_022,
    _selected_part_control_step_023,
    _selected_part_control_step_024,
    _selected_part_control_step_025,
    _selected_part_control_step_026,
)
