from __future__ import annotations

from cdmw.domain.textures.material_parameters import source_emissive_strength
from cdmw.ui.archive_browser.static_replacement_dotnet_material_bridge import (
    resident_material_parameter_group,
    send_resident_material_parameters,
)

def _remaining_source_role_flush_step_001(_state):
    _state.state = _state._StaticReplacementDialogState(_state.context)
    _state.List = _state.context.get('List')
    _state.StaticSourcePartAdjustment = _state.context.get('StaticSourcePartAdjustment')
    _state._alignment_mesh_edit_tab_active = _state.context.get('_alignment_mesh_edit_tab_active')
    _state._apply_source_material_texture_overrides_to_ui_texture_sets = _state.context.get('_apply_source_material_texture_overrides_to_ui_texture_sets')
    _state._ensure_source_part_adjustment = _state.context.get('_ensure_source_part_adjustment')
    _state._parse_mapping_edit = _state.context.get('_parse_mapping_edit')
    _state._selected_part_glow_rgb_from_controls = _state.context.get('_selected_part_glow_rgb_from_controls')
    _state._selected_part_glow_strength_from_controls = _state.context.get('_selected_part_glow_strength_from_controls')
    _state._selected_glow_source_indices = _state.context.get('_selected_glow_source_indices')
    _state._source_assigned_target_indices_helper = _state.context.get('_source_assigned_target_indices_helper')
    _state._source_part_glow_emissive_update_states_helper = _state.context.get('_source_part_glow_emissive_update_states_helper')
    _state._source_part_role_export_flush_states_helper = _state.context.get('_source_part_role_export_flush_states_helper')
    _state.adjustment = _state.context.get('adjustment')
    _state.changed = _state.context.get('changed')
    _state.dialog = _state.context.get('dialog')
    _state.flush_state = _state.context.get('flush_state')
    _state.group_replacement_texture_sets = _state.context.get('group_replacement_texture_sets')
    _state.mapping_edits = _state.context.get('mapping_edits')
    _state.part_glow_color_checkbox = _state.context.get('part_glow_color_checkbox')
    _state.part_glow_strength_checkbox = _state.context.get('part_glow_strength_checkbox')
    _state.source_index = _state.context.get('source_index')
    _state.source_part_adjustments = _state.context.get('source_part_adjustments')
    _state.source_role_overrides = _state.context.get('source_role_overrides')
    _state.self = _state.context.get('self')
    _state.texture_files_for_mapping = _state.context.get('texture_files_for_mapping') or []
    _state.update_state = _state.context.get('update_state')
    _state.update_states = _state.context.get('update_states')
    _state.prompt_shell_context = _state.context.get('prompt_shell_context')

def _remaining_source_role_flush_step_002(_state):

    def _prompt_context_value(name: str) -> object:
        if isinstance(_state.prompt_shell_context, dict) and name in _state.prompt_shell_context:
            return _state.prompt_shell_context.get(name)
        return _state.context.get(name)
    _state._prompt_context_value = _prompt_context_value

def _remaining_source_role_flush_step_003(_state):

    def _part_glow_color_checkbox() -> object:
        return _state._prompt_context_value('part_glow_color_checkbox')
    _state._part_glow_color_checkbox = _part_glow_color_checkbox

    def _part_glow_strength_checkbox() -> object:
        return _state._prompt_context_value('part_glow_strength_checkbox')
    _state._part_glow_strength_checkbox = _part_glow_strength_checkbox

def _remaining_source_role_flush_step_004(_state):

    def _active_mesh_edit_source_glow_mutation_blocked() -> bool:
        if not (callable(_state._alignment_mesh_edit_tab_active) and _state._alignment_mesh_edit_tab_active()):
            return False
        if bool(getattr(_state.dialog, '_mesh_editor_embedded_dotnet_active', False)) and callable(
            getattr(_state.dialog, '_mesh_editor_embedded_apply_material_parameters', None)
        ):
            return False
        message = 'Active Mesh Editor source glow overrides require native material execution; Python adjustment mutation fallback is disabled.'
        set_status_message = getattr(_state.self, 'set_status_message', None)
        if callable(set_status_message):
            set_status_message(message, error=True)
        return True
    _state._active_mesh_edit_source_glow_mutation_blocked = _active_mesh_edit_source_glow_mutation_blocked

def _remaining_source_role_flush_step_005(_state):

    def _resident_role_group(source_index: int, adjustment: object) -> dict[str, object]:
        role = str(getattr(adjustment, 'material_role', '') or '').strip().lower()
        color = tuple(getattr(adjustment, 'emissive_color_rgb', ()) or ())
        strength = source_emissive_strength(adjustment)
        values: dict[str, object] = {
            'material_role': role,
            'emissive_intensity': strength if role == 'glow' and strength is not None else (1.0 if role == 'glow' else None),
            'emissive_color': (
                tuple(max(0.0, min(1.0, float(value) / 255.0)) for value in color[:3])
                if role == 'glow' and len(color) >= 3
                else None
            ),
        }
        return resident_material_parameter_group(values, source_submesh_indices=(source_index,))
    _state._resident_role_group = _resident_role_group

    def _apply_current_glow_color_to_role_overrides() -> None:
        selected_indices = (
            tuple(_state._selected_glow_source_indices())
            if callable(_state._selected_glow_source_indices)
            else ()
        )
        if len(selected_indices) != 1:
            return
        checkbox = _state._part_glow_color_checkbox()
        strength_checkbox = _state._part_glow_strength_checkbox()
        use_color = bool(checkbox is not None and callable(getattr(checkbox, 'isChecked', None)) and checkbox.isChecked())
        use_strength = bool(
            strength_checkbox is not None
            and callable(getattr(strength_checkbox, 'isChecked', None))
            and strength_checkbox.isChecked()
        )
        rgb = _state._selected_part_glow_rgb_from_controls() if callable(_state._selected_part_glow_rgb_from_controls) else ()
        strength = (
            _state._selected_part_glow_strength_from_controls()
            if callable(_state._selected_part_glow_strength_from_controls)
            else 1.0
        )
        update_states = _state._source_part_glow_emissive_update_states_helper(
            _state.source_part_adjustments,
            source_index=selected_indices[0],
            rgb=rgb,
            use_color=use_color,
            strength=strength,
            use_strength=use_strength,
        )
        if update_states and _state._active_mesh_edit_source_glow_mutation_blocked():
            return
        for update_state in update_states:
            adjustment = _state.source_part_adjustments.get(update_state.source_index)
            if adjustment is not None:
                adjustment.emissive_color_rgb = update_state.emissive_color_rgb
                adjustment.emissive_strength = update_state.emissive_strength
        send_resident_material_parameters(
            _state.dialog,
            tuple(
                _state._resident_role_group(update_state.source_index, _state.source_part_adjustments[update_state.source_index])
                for update_state in update_states
                if update_state.source_index in _state.source_part_adjustments
            ),
        )
        if update_states:
            _state._refresh_ui_texture_sets_after_source_part_material_override()
    _state._apply_current_glow_color_to_role_overrides = _apply_current_glow_color_to_role_overrides

def _remaining_source_role_flush_step_006(_state):

    def _flush_source_role_overrides_for_export() -> None:
        changed = False
        changed_adjustments: list[tuple[int, object]] = []
        for flush_state in _state._source_part_role_export_flush_states_helper(_state.source_role_overrides, _state.source_part_adjustments, default_adjustment=_state.StaticSourcePartAdjustment):
            if flush_state.changed and _state._active_mesh_edit_source_glow_mutation_blocked():
                return
            adjustment = _state._ensure_source_part_adjustment(flush_state.source_index)
            if flush_state.material_role_changed:
                adjustment.material_role = flush_state.normalized_role
            changed = changed or flush_state.changed
            if flush_state.changed:
                changed_adjustments.append((flush_state.source_index, adjustment))
        send_resident_material_parameters(
            _state.dialog,
            tuple(_state._resident_role_group(source_index, adjustment) for source_index, adjustment in changed_adjustments),
        )
        _state._apply_current_glow_color_to_role_overrides()
        if changed:
            _state._refresh_ui_texture_sets_after_source_part_material_override()
    _state._flush_source_role_overrides_for_export = _flush_source_role_overrides_for_export

def _remaining_source_role_flush_step_007(_state):

    def _refresh_ui_texture_sets_after_source_part_material_override() -> None:
        if _state.state.replacement_mesh_for_mapping is None:
            return
        try:
            _state.state.texture_sets = _state.group_replacement_texture_sets(_state.texture_files_for_mapping, obj_mesh=_state.state.replacement_mesh_for_mapping)
            _state._apply_source_material_texture_overrides_to_ui_texture_sets(_state.state.texture_sets)
        except Exception:
            return
    _state._refresh_ui_texture_sets_after_source_part_material_override = _refresh_ui_texture_sets_after_source_part_material_override

def _remaining_source_role_flush_step_008(_state):

    def _part_mapped_target_indices(source_index: int) -> List[int]:
        return list(_state._source_assigned_target_indices_helper(source_index, _state.mapping_edits, parse_mapping_edit=_state._parse_mapping_edit))
    _state._part_mapped_target_indices = _part_mapped_target_indices

def _remaining_source_role_flush_step_009(_state):
    _state._factory_result_values.update({'_apply_current_glow_color_to_role_overrides': _state._apply_current_glow_color_to_role_overrides, '_flush_source_role_overrides_for_export': _state._flush_source_role_overrides_for_export, '_refresh_ui_texture_sets_after_source_part_material_override': _state._refresh_ui_texture_sets_after_source_part_material_override, '_part_mapped_target_indices': _state._part_mapped_target_indices})

STEPS = (
    _remaining_source_role_flush_step_001,
    _remaining_source_role_flush_step_002,
    _remaining_source_role_flush_step_003,
    _remaining_source_role_flush_step_004,
    _remaining_source_role_flush_step_005,
    _remaining_source_role_flush_step_006,
    _remaining_source_role_flush_step_007,
    _remaining_source_role_flush_step_008,
    _remaining_source_role_flush_step_009,
)
