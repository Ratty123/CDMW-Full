from __future__ import annotations

def _texture_material_plan_final_preview_step_001(_state):
    _state.FinalPackagePreviewResult = _state.context.get('FinalPackagePreviewResult')
    _state._clear_tree_current_item = _state.context.get('_clear_tree_current_item')
    _state._final_binding_row_item_helper = _state.context.get('_final_binding_row_item_helper')
    _state._final_dds_contract_summary_html_helper = _state.context.get('_final_dds_contract_summary_html_helper')
    _state._final_material_status_item_helper = _state.context.get('_final_material_status_item_helper')
    _state._final_preview_binding_preview_status = _state.context.get('_final_preview_binding_preview_status')
    _state._final_preview_binding_row_states_helper = _state.context.get('_final_preview_binding_row_states_helper')
    _state._final_preview_binding_target_index_helper = _state.context.get('_final_preview_binding_target_index_helper')
    _state._final_preview_material_status_color = _state.context.get('_final_preview_material_status_color')
    _state._final_preview_material_status_row_states_helper = _state.context.get('_final_preview_material_status_row_states_helper')
    _state._final_preview_plan_state_helper = _state.context.get('_final_preview_plan_state_helper')
    _state._fit_alignment_tree_height_to_rows = _state.context.get('_fit_alignment_tree_height_to_rows')
    _state._is_marker_source = _state.context.get('_is_marker_source')
    _state._material_plan_summary_block = _state.context.get('_material_plan_summary_block')
    _state._refresh_source_material_plan = _state.context.get('_refresh_source_material_plan')
    _state._reset_selected_texture_plan_source_state_helper = _state.context.get('_reset_selected_texture_plan_source_state_helper')
    _state._slot_kind_for_final_preview_row = _state.context.get('_slot_kind_for_final_preview_row')
    _state._source_indices_for_target_contract = _state.context.get('_source_indices_for_target_contract')
    _state._source_material_part_summary_helper = _state.context.get('_source_material_part_summary_helper')
    _state._target_index_for_name = _state.context.get('_target_index_for_name')
    _state.binding_state = _state.context.get('binding_state')
    _state.dds_detail_panel = _state.context.get('dds_detail_panel')
    _state.final_plan_state = _state.context.get('final_plan_state')
    _state.final_preview = _state.context.get('final_preview')
    _state.material_contract_label = _state.context.get('material_contract_label')
    _state.material_plan_blocked = _state.context.get('material_plan_blocked')
    _state.material_plan_control_text = _state.context.get('material_plan_control_text')
    _state.material_plan_summary = _state.context.get('material_plan_summary')
    _state.material_plan_tree = _state.context.get('material_plan_tree')
    _state.material_routing_blocked = _state.context.get('material_routing_blocked')
    _state.material_routing_tree = _state.context.get('material_routing_tree')
    _state.message = _state.context.get('message')
    _state.preview_status = _state.context.get('preview_status')
    _state.replacement_mesh_for_mapping = _state.context.get('replacement_mesh_for_mapping')
    _state.selected_texture_plan_source = _state.context.get('selected_texture_plan_source')
    _state.simplified_part_label = _state.context.get('simplified_part_label')
    _state.source_indices = _state.context.get('source_indices')
    _state.source_parts = _state.context.get('source_parts')
    _state.status_state = _state.context.get('status_state')
    _state.target_index = _state.context.get('target_index')
    _state.texture_material_plan_loaded = _state.context.get('texture_material_plan_loaded')
    _state.texture_sets = _state.context.get('texture_sets')
    _state.texture_transform_group = _state.context.get('texture_transform_group')

def _texture_material_plan_final_preview_step_002(_state):

    def _refresh_material_plan_from_final_preview(final_preview: FinalPackagePreviewResult) -> None:
        material_plan_blocked = _state.material_plan_tree.blockSignals(True)
        material_routing_blocked = _state.material_routing_tree.blockSignals(True)
        try:
            _state._clear_tree_current_item(_state.material_plan_tree)
            _state._clear_tree_current_item(_state.material_routing_tree)
            _state.material_plan_tree.clear()
            _state.material_routing_tree.clear()
        finally:
            _state.material_plan_tree.blockSignals(material_plan_blocked)
            _state.material_routing_tree.blockSignals(material_routing_blocked)
        _state._reset_selected_texture_plan_source_state_helper(_state.selected_texture_plan_source)
        _state.dds_detail_panel.setVisible(False)
        _state.texture_transform_group.setVisible(False)
        final_plan_state = _state._final_preview_plan_state_helper(final_preview)
        _state.material_plan_tree.setVisible(True)
        _state.material_routing_tree.setVisible(True)
        _state.material_plan_summary.setText(_state._material_plan_summary_block(detected_sets=final_plan_state.detected_sets, detected_slots=final_plan_state.detected_slots, conflicts=final_plan_state.warnings, empty=not bool(final_plan_state.binding_rows)))
        _state.material_plan_summary.setToolTip('\n'.join((str(message) for message in final_plan_state.warnings[:12])) if final_plan_state.warnings else '')
        _state.material_contract_label.setText(_state._final_dds_contract_summary_html_helper(len(final_plan_state.binding_rows)))
        _state.material_contract_label.setToolTip(str(_state.material_plan_control_text['final_contract_tooltip']))
        for status_state in _state._final_preview_material_status_row_states_helper(final_plan_state.material_statuses, final_plan_state.binding_rows):
            source_indices = _state._source_indices_for_target_contract(status_state.material_name, status_state.material_name)
            source_parts = _state._source_material_part_summary_helper(status_state.material_name, _state.replacement_mesh_for_mapping, texture_set_count=len(_state.texture_sets), is_marker_source=_state._is_marker_source) if source_indices else '-'
            _state.material_routing_tree.addTopLevelItem(_state._final_material_status_item_helper(material_name=status_state.material_name, source_parts=source_parts, maps=status_state.maps, status_label=status_state.status_label, detail=status_state.detail, source_indices=source_indices, target_index=_state._target_index_for_name(status_state.material_name), status_color=_state._final_preview_material_status_color(status_state.status_label)))
        for binding_state in _state._final_preview_binding_row_states_helper(final_plan_state.binding_rows):
            preview_status = _state._final_preview_binding_preview_status(binding_state.binding_row)
            source_indices = _state._source_indices_for_target_contract(binding_state.part_name, binding_state.material_name)
            target_index = _state._final_preview_binding_target_index_helper(binding_state.part_name, binding_state.material_name, target_index_for_name=_state._target_index_for_name)
            _state.material_plan_tree.addTopLevelItem(_state._final_binding_row_item_helper(binding_state.binding_row, part_label=_state.simplified_part_label(binding_state.part_name), part_name=binding_state.part_name, material_name=binding_state.material_name, source_indices=source_indices, target_index=target_index, preview_status=preview_status, status_color=_state._final_preview_material_status_color(binding_state.status_label), slot_kind=_state._slot_kind_for_final_preview_row(binding_state.binding_row)))
        _state._fit_alignment_tree_height_to_rows(_state.material_routing_tree, minimum=80, screen_margin=420, maximum=180)
        _state._fit_alignment_tree_height_to_rows(_state.material_plan_tree, minimum=76, screen_margin=420, maximum=190)
        _state._fit_material_routing_tree_columns()
        _state._fit_material_plan_tree_columns()
    _state._refresh_material_plan_from_final_preview = _refresh_material_plan_from_final_preview

def _texture_material_plan_final_preview_step_003(_state):

    def _ensure_source_material_plan_loaded() -> None:
        if bool(_state.texture_material_plan_loaded.get('loading')):
            return
        if bool(_state.texture_material_plan_loaded.get('loaded')) and _state.material_plan_tree.topLevelItemCount() > 0:
            return
        _state.texture_material_plan_loaded['loading'] = True
        try:
            _state._refresh_source_material_plan(force=True)
        finally:
            _state.texture_material_plan_loaded['loading'] = False
    _state._ensure_source_material_plan_loaded = _ensure_source_material_plan_loaded

def _texture_material_plan_final_preview_step_004(_state):
    _state._factory_result_values.update({'_refresh_material_plan_from_final_preview': _state._refresh_material_plan_from_final_preview, '_ensure_source_material_plan_loaded': _state._ensure_source_material_plan_loaded})

STEPS = (
    _texture_material_plan_final_preview_step_001,
    _texture_material_plan_final_preview_step_002,
    _texture_material_plan_final_preview_step_003,
    _texture_material_plan_final_preview_step_004,
)
