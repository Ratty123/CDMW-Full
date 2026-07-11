from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_dotnet_material_bridge import (
    resident_material_parameter_group,
    resident_material_parameters_available,
    send_resident_material_parameters,
    send_source_role_material_parameters,
)

def _parts_outliner_mapping_step_001(_state):
    _state.List = _state.context.get('List')
    _state.PARTS_OUTLINER_ROLE_OPTIONS = _state.context.get('PARTS_OUTLINER_ROLE_OPTIONS')
    _state.QBrush = _state.context.get('QBrush')
    _state.QColor = _state.context.get('QColor')
    _state.QLabel = _state.context.get('QLabel')
    _state.QLineEdit = _state.context.get('QLineEdit')
    _state.QMenu = _state.context.get('QMenu')
    _state.QPoint = _state.context.get('QPoint')
    _state.QSizePolicy = _state.context.get('QSizePolicy')
    _state.QTimer = _state.context.get('QTimer')
    _state.QTreeWidgetItem = _state.context.get('QTreeWidgetItem')
    _state.Qt = _state.context.get('Qt')
    _state.Sequence = _state.context.get('Sequence')
    _state.StaticSourcePartAdjustment = _state.context.get('StaticSourcePartAdjustment')
    _state.dialog = _state.context.get('dialog')
    _state._alignment_dialog_widgets_live = _state.context.get('_alignment_dialog_widgets_live')
    _state._alignment_mesh_edit_tab_active = _state.context.get('_alignment_mesh_edit_tab_active')
    _state._alignment_part_clipboard_can_paste = _state.context.get('_alignment_part_clipboard_can_paste')
    _state._alignment_part_transform_preview_queue_indices_helper = _state.context.get('_alignment_part_transform_preview_queue_indices_helper')
    _state._auto_fit_alignment_tree_columns = _state.context.get('_auto_fit_alignment_tree_columns')
    _state._capture_initial_geometry_snapshot = _state.context.get('_capture_initial_geometry_snapshot')
    _state._commit_mapping_edit = _state.context.get('_commit_mapping_edit')
    _state._copied_original_texture_tooltip = _state.context.get('_copied_original_texture_tooltip')
    _state._ensure_source_part_adjustment = _state.context.get('_ensure_source_part_adjustment')
    _state._fit_alignment_tree_height_to_rows = _state.context.get('_fit_alignment_tree_height_to_rows')
    _state._is_marker_source = _state.context.get('_is_marker_source')
    _state._load_selected_part_controls = _state.context.get('_load_selected_part_controls')
    _state._mapped_source_vertex_counts_helper = _state.context.get('_mapped_source_vertex_counts_helper')
    _state._mapped_target_vertex_count_helper = _state.context.get('_mapped_target_vertex_count_helper')
    _state._mapping_committed_source_cell_state_helper = _state.context.get('_mapping_committed_source_cell_state_helper')
    _state._mapping_edit_committed_text_helper = _state.context.get('_mapping_edit_committed_text_helper')
    _state._mapping_edit_draft_tooltip_helper = _state.context.get('_mapping_edit_draft_tooltip_helper')
    _state._mapping_edit_indices_helper = _state.context.get('_mapping_edit_indices_helper')
    _state._mapping_edit_placeholder_text_helper = _state.context.get('_mapping_edit_placeholder_text_helper')
    _state._mapping_edit_source_cell_state_helper = _state.context.get('_mapping_edit_source_cell_state_helper')
    _state._mapping_indices_for_source_target_helper = _state.context.get('_mapping_indices_for_source_target_helper')
    _state._mapping_preserve_split_group_count_helper = _state.context.get('_mapping_preserve_split_group_count_helper')
    _state._mapping_role_hint = _state.context.get('_mapping_role_hint')
    _state._mapping_route_button_enabled_state_helper = _state.context.get('_mapping_route_button_enabled_state_helper')
    _state._mapping_source_cell_text = _state.context.get('_mapping_source_cell_text')
    _state._mapping_source_indices_text_helper = _state.context.get('_mapping_source_indices_text_helper')
    _state._mapping_source_target_route_state_helper = _state.context.get('_mapping_source_target_route_state_helper')
    _state._mapping_status_action_state_helper = _state.context.get('_mapping_status_action_state_helper')
    _state._mapping_status_current_target_line_helper = _state.context.get('_mapping_status_current_target_line_helper')
    _state._mapping_status_physics_state_helper = _state.context.get('_mapping_status_physics_state_helper')
    _state._mapping_status_selection_lines_helper = _state.context.get('_mapping_status_selection_lines_helper')
    _state._mapping_status_summary_badges_helper = _state.context.get('_mapping_status_summary_badges_helper')
    _state._mapping_status_summary_html_helper = _state.context.get('_mapping_status_summary_html_helper')
    _state._mapping_table_advanced_visibility_state_helper = _state.context.get('_mapping_table_advanced_visibility_state_helper')
    _state._mapping_table_build_can_start_helper = _state.context.get('_mapping_table_build_can_start_helper')
    _state._mapping_table_build_complete_helper = _state.context.get('_mapping_table_build_complete_helper')
    _state._mapping_table_build_mark_complete_helper = _state.context.get('_mapping_table_build_mark_complete_helper')
    _state._mapping_table_build_mark_requested_started_helper = _state.context.get('_mapping_table_build_mark_requested_started_helper')
    _state._mapping_table_build_next_index_helper = _state.context.get('_mapping_table_build_next_index_helper')
    _state._mapping_table_build_set_next_index_helper = _state.context.get('_mapping_table_build_set_next_index_helper')
    _state._mapping_table_build_start_delay_ms_helper = _state.context.get('_mapping_table_build_start_delay_ms_helper')
    _state._mapping_table_chunk_presentation_state_helper = _state.context.get('_mapping_table_chunk_presentation_state_helper')
    _state._mapping_table_chunk_row_limit_helper = _state.context.get('_mapping_table_chunk_row_limit_helper')
    _state._mapping_table_chunk_time_budget_seconds_helper = _state.context.get('_mapping_table_chunk_time_budget_seconds_helper')
    _state._mapping_table_column_max_widths_helper = _state.context.get('_mapping_table_column_max_widths_helper')
    _state._mapping_table_column_min_widths_helper = _state.context.get('_mapping_table_column_min_widths_helper')
    _state._mapping_table_expand_columns_helper = _state.context.get('_mapping_table_expand_columns_helper')
    _state._mapping_table_height_fit_kwargs_helper = _state.context.get('_mapping_table_height_fit_kwargs_helper')
    _state._mapping_table_loading_progress_text_helper = _state.context.get('_mapping_table_loading_progress_text_helper')
    _state._mapping_table_ready_progress_text_helper = _state.context.get('_mapping_table_ready_progress_text_helper')
    _state._mapping_table_row_hidden_by_filters_helper = _state.context.get('_mapping_table_row_hidden_by_filters_helper')
    _state._mapping_table_target_row_state_helper = _state.context.get('_mapping_table_target_row_state_helper')
    _state._mapping_target_confidence_state_helper = _state.context.get('_mapping_target_confidence_state_helper')
    _state._mapping_target_dds_cell_state_helper = _state.context.get('_mapping_target_dds_cell_state_helper')
    _state._mapping_target_details_text_helper = _state.context.get('_mapping_target_details_text_helper')
    _state._mapping_target_item_helper = _state.context.get('_mapping_target_item_helper')
    _state._mapping_text_has_indices_helper = _state.context.get('_mapping_text_has_indices_helper')
    _state._mapping_vertex_limit_issues_helper = _state.context.get('_mapping_vertex_limit_issues_helper')
    _state._mapping_vertex_limit_status_line_helper = _state.context.get('_mapping_vertex_limit_status_line_helper')
    _state._parts_outliner_action_role_value_helper = _state.context.get('_parts_outliner_action_role_value_helper')
    _state._parts_outliner_action_target_index_helper = _state.context.get('_parts_outliner_action_target_index_helper')
    _state._parts_outliner_cache_matches_helper = _state.context.get('_parts_outliner_cache_matches_helper')
    _state._parts_outliner_cache_record_revision_helper = _state.context.get('_parts_outliner_cache_record_revision_helper')
    _state._parts_outliner_copied_texture_tooltip_source_index_helper = _state.context.get('_parts_outliner_copied_texture_tooltip_source_index_helper')
    _state._parts_outliner_drop_target_index_helper = _state.context.get('_parts_outliner_drop_target_index_helper')
    _state._parts_outliner_geometry_text_helper = _state.context.get('_parts_outliner_geometry_text_helper')
    _state._parts_outliner_revision_helper = _state.context.get('_parts_outliner_revision_helper')
    _state._parts_outliner_role_menu_specs_helper = _state.context.get('_parts_outliner_role_menu_specs_helper')
    _state._parts_outliner_selection_changed = _state.context.get('_parts_outliner_selection_changed')
    _state._parts_outliner_selection_row_state_helper = _state.context.get('_parts_outliner_selection_row_state_helper')
    _state._parts_outliner_source_click_action_helper = _state.context.get('_parts_outliner_source_click_action_helper')
    _state._parts_outliner_source_drop_allowed_helper = _state.context.get('_parts_outliner_source_drop_allowed_helper')
    _state._parts_outliner_source_index_helper = _state.context.get('_parts_outliner_source_index_helper')
    _state._parts_outliner_source_indices_helper = _state.context.get('_parts_outliner_source_indices_helper')
    _state._parts_outliner_source_item_helper = _state.context.get('_parts_outliner_source_item_helper')
    _state._parts_outliner_source_label_helper = _state.context.get('_parts_outliner_source_label_helper')
    _state._parts_outliner_source_role_change_refresh_reason_helper = _state.context.get('_parts_outliner_source_role_change_refresh_reason_helper')
    _state._parts_outliner_source_role_change_undo_label_helper = _state.context.get('_parts_outliner_source_role_change_undo_label_helper')
    _state._parts_outliner_source_target_apply_state_helper = _state.context.get('_parts_outliner_source_target_apply_state_helper')
    _state._parts_outliner_target_item_helper = _state.context.get('_parts_outliner_target_item_helper')
    _state._parts_outliner_target_label_helper = _state.context.get('_parts_outliner_target_label_helper')
    _state._parts_outliner_target_menu_specs_helper = _state.context.get('_parts_outliner_target_menu_specs_helper')
    _state._parts_outliner_unassigned_group_item_helper = _state.context.get('_parts_outliner_unassigned_group_item_helper')
    _state._parts_outliner_unassigned_source_indices_helper = _state.context.get('_parts_outliner_unassigned_source_indices_helper')
    _state._parts_outliner_unassigned_target_label_helper = _state.context.get('_parts_outliner_unassigned_target_label_helper')
    _state._paste_alignment_part_clipboard_as_replacement_source = _state.context.get('_paste_alignment_part_clipboard_as_replacement_source')
    _state._physics_status_tooltip = _state.context.get('_physics_status_tooltip')

def _parts_outliner_mapping_step_002(_state):
    _state._push_geometry_undo_snapshot = _state.context.get('_push_geometry_undo_snapshot')
    _state._qt_object_is_valid = _state.context.get('_qt_object_is_valid')
    _state._queue_material_edit_refresh = _state.context.get('_queue_material_edit_refresh')
    _state._queue_selection_preview_refresh = _state.context.get('_queue_selection_preview_refresh')
    _state._queue_static_preview_rebuild = _state.context.get('_queue_static_preview_rebuild')
    _state._queue_static_preview_refresh = _state.context.get('_queue_static_preview_refresh')
    _state._refresh_source_assignment_columns = _state.context.get('_refresh_source_assignment_columns')
    _state._refresh_source_material_plan = _state.context.get('_refresh_source_material_plan')
    _state._removed_target_dds_cell_text = _state.context.get('_removed_target_dds_cell_text')
    _state._removed_target_dds_tooltip_helper = _state.context.get('_removed_target_dds_tooltip_helper')
    _state._routing_effect_lines_helper = _state.context.get('_routing_effect_lines_helper')
    _state._routing_source_material_labels_helper = _state.context.get('_routing_source_material_labels_helper')
    _state._select_source_part_from_viewport = _state.context.get('_select_source_part_from_viewport')
    _state._selected_source_indices_state_helper = _state.context.get('_selected_source_indices_state_helper')
    _state._selected_source_summary = _state.context.get('_selected_source_summary')
    _state._selection_view_update_kwargs_helper = _state.context.get('_selection_view_update_kwargs_helper')
    _state._set_mesh_replacement_selection_view = _state.context.get('_set_mesh_replacement_selection_view')
    _state._set_preview_performance_status = _state.context.get('_set_preview_performance_status')
    _state._show_replacement_sources_context_menu_for_viewport = _state.context.get('_show_replacement_sources_context_menu_for_viewport')
    _state._set_source_role_override_value = _state.context.get('_set_source_role_override_value')
    _state._source_assignment_index_helper = _state.context.get('_source_assignment_index_helper')
    _state._source_display_name = _state.context.get('_source_display_name')
    _state._source_index_from_tree_item = _state.context.get('_source_index_from_tree_item')
    _state._source_index_help_text = _state.context.get('_source_index_help_text')
    _state._source_material_group_label_helper = _state.context.get('_source_material_group_label_helper')
    _state._source_outliner_dds_text = _state.context.get('_source_outliner_dds_text')
    _state._source_outliner_geometry_helper = _state.context.get('_source_outliner_geometry_helper')
    _state._source_outliner_label_helper = _state.context.get('_source_outliner_label_helper')
    _state._source_outliner_state = _state.context.get('_source_outliner_state')
    _state._source_part_check_toggle_state_helper = _state.context.get('_source_part_check_toggle_state_helper')
    _state._source_part_display_label_helper = _state.context.get('_source_part_display_label_helper')
    _state._source_part_edit_undo_label_helper = _state.context.get('_source_part_edit_undo_label_helper')
    _state._source_part_include_exclude_pending_reason_helper = _state.context.get('_source_part_include_exclude_pending_reason_helper')
    _state._source_part_role_action_state_helper = _state.context.get('_source_part_role_action_state_helper')
    _state._source_part_routing_preview_action_helper = _state.context.get('_source_part_routing_preview_action_helper')
    _state._source_parts_apply_pending_presentation_helper = _state.context.get('_source_parts_apply_pending_presentation_helper')
    _state._source_parts_clear_apply_pending_helper = _state.context.get('_source_parts_clear_apply_pending_helper')
    _state._source_parts_clear_apply_pending_presentation_helper = _state.context.get('_source_parts_clear_apply_pending_presentation_helper')
    _state._source_parts_mark_apply_pending_helper = _state.context.get('_source_parts_mark_apply_pending_helper')
    _state._source_parts_mark_preview_rebuild_pending_helper = _state.context.get('_source_parts_mark_preview_rebuild_pending_helper')
    _state._source_parts_preview_rebuild_pending_helper = _state.context.get('_source_parts_preview_rebuild_pending_helper')
    _state._source_parts_preview_rebuild_pending_presentation_helper = _state.context.get('_source_parts_preview_rebuild_pending_presentation_helper')
    _state._source_physics_status_text = _state.context.get('_source_physics_status_text')
    _state._source_role_label = _state.context.get('_source_role_label')
    _state._source_tree_item_helper = _state.context.get('_source_tree_item_helper')
    _state._source_tree_item_state_helper = _state.context.get('_source_tree_item_state_helper')
    _state._sync_highlight_sets = _state.context.get('_sync_highlight_sets')
    _state._target_display_name = _state.context.get('_target_display_name')
    _state._target_mapping_selection_view_payload_helper = _state.context.get('_target_mapping_selection_view_payload_helper')
    _state._target_outliner_state = _state.context.get('_target_outliner_state')
    _state._target_physics_status_text = _state.context.get('_target_physics_status_text')
    _state._target_selection_changed = _state.context.get('_target_selection_changed')
    _state._target_texture_status_details = _state.context.get('_target_texture_status_details')
    _state._target_texture_status_text = _state.context.get('_target_texture_status_text')
    _state._texture_set_for_source_index_helper = _state.context.get('_texture_set_for_source_index_helper')
    _state._tree_item_source_index_or_fallback_helper = _state.context.get('_tree_item_source_index_or_fallback_helper')
    _state._tree_item_target_index_or_fallback_helper = _state.context.get('_tree_item_target_index_or_fallback_helper')
    _state._unique_nonnegative_indices_helper = _state.context.get('_unique_nonnegative_indices_helper')
    _state._update_selection_context = _state.context.get('_update_selection_context')
    _state.advanced_part_tools_section = _state.context.get('advanced_part_tools_section')
    _state.apply_best_guesses_button = _state.context.get('apply_best_guesses_button')
    _state.apply_source_parts_button = _state.context.get('apply_source_parts_button')
    _state.assign_source_button = _state.context.get('assign_source_button')
    _state.clear_all_guesses_button = _state.context.get('clear_all_guesses_button')
    _state.clear_target_button = _state.context.get('clear_target_button')
    _state.copied_original_texture_disabled_sources = _state.context.get('copied_original_texture_disabled_sources')
    _state.copied_original_texture_intents_by_source = _state.context.get('copied_original_texture_intents_by_source')
    _state.empty_targets_filter_checkbox = _state.context.get('empty_targets_filter_checkbox')
    _state.group_materials_button = _state.context.get('group_materials_button')
    _state.independent_output_source_indices = _state.context.get('independent_output_source_indices')
    _state.initial_mapping_text_by_target = _state.context.get('initial_mapping_text_by_target')
    _state.low_confidence_filter_checkbox = _state.context.get('low_confidence_filter_checkbox')
    _state.mapping_edit_refresh_timer = _state.context.get('mapping_edit_refresh_timer')
    _state.mapping_edits = _state.context.get('mapping_edits')
    _state.mapping_edits_by_target = _state.context.get('mapping_edits_by_target')
    _state.mapping_items_by_target = _state.context.get('mapping_items_by_target')
    _state.mapping_progress_label = _state.context.get('mapping_progress_label')
    _state.mapping_status_label = _state.context.get('mapping_status_label')
    _state.mapping_table_build_requested = _state.context.get('mapping_table_build_requested')
    _state.mapping_table_build_state = _state.context.get('mapping_table_build_state')
    _state.mapping_table_build_timer = _state.context.get('mapping_table_build_timer')
    _state.mapping_targets = _state.context.get('mapping_targets')
    _state.mapping_tree = _state.context.get('mapping_tree')
    _state.mappings_by_target = _state.context.get('mappings_by_target')
    _state.merge_source_button = _state.context.get('merge_source_button')
    _state.original_button_panel = _state.context.get('original_button_panel')
    _state.original_mesh_for_mapping = _state.context.get('original_mesh_for_mapping')
    _state.original_part_clipboard_action_text = _state.context.get('original_part_clipboard_action_text')
    _state.original_parts_label = _state.context.get('original_parts_label')
    _state.original_tree = _state.context.get('original_tree')
    _state.parts_outliner_cache_state = _state.context.get('parts_outliner_cache_state')
    _state.parts_outliner_item_update_guard = _state.context.get('parts_outliner_item_update_guard')
    _state.parts_outliner_source_items = _state.context.get('parts_outliner_source_items')
    _state.parts_outliner_target_items = _state.context.get('parts_outliner_target_items')
    _state.parts_outliner_tree = _state.context.get('parts_outliner_tree')
    _state.preview_only_source_indices = _state.context.get('preview_only_source_indices')
    _state.preview_target_button = _state.context.get('preview_target_button')
    _state.remove_source_button = _state.context.get('remove_source_button')
    _state.replacement_mesh_for_mapping = _state.context.get('replacement_mesh_for_mapping')
    _state.row = _state.context.get('row')
    _state.selected_source_highlight_indices = _state.context.get('selected_source_highlight_indices')

def _parts_outliner_mapping_step_003(_state):
    _state.selected_source_part = _state.context.get('selected_source_part')
    _state.selected_target_slot = _state.context.get('selected_target_slot')
    _state.simplified_part_label = _state.context.get('simplified_part_label')
    _state.source_display_overrides = _state.context.get('source_display_overrides')
    _state.source_items_by_index = _state.context.get('source_items_by_index')
    _state.source_part_adjustments = _state.context.get('source_part_adjustments')
    _state.source_parts_apply_state = _state.context.get('source_parts_apply_state')
    _state.source_parts_group = _state.context.get('source_parts_group')
    _state.source_parts_pending_label = _state.context.get('source_parts_pending_label')
    _state.source_tree = _state.context.get('source_tree')
    _state.source_tree_item_update_guard = _state.context.get('source_tree_item_update_guard')
    _state.static_replacement_vertex_limit = _state.context.get('static_replacement_vertex_limit')
    _state.target_slots_label = _state.context.get('target_slots_label')
    _state.texture_overrides_dirty = _state.context.get('texture_overrides_dirty')
    _state.texture_sets = _state.context.get('texture_sets')
    _state.time = _state.context.get('time')
    _state.transform_source_indices = _state.context.get('transform_source_indices')
    _state.self = _state.context.get('self')
    _state._parts_outliner_source_label = lambda source_index: _state._source_outliner_label_helper(source_index, _state.replacement_mesh_for_mapping, _state.source_display_overrides, simplify_label=_state.simplified_part_label)
    _state._parts_outliner_source_geometry = lambda source_index: _state._source_outliner_geometry_helper(source_index, _state.replacement_mesh_for_mapping)

def _parts_outliner_mapping_step_004(_state):

    def _selected_source_indices_from_tree(*, include_fallback: bool=True) -> List[int]:
        selected_items: _state.Sequence[_state.QTreeWidgetItem] = ()
        if _state._qt_object_is_valid(_state.source_tree):
            try:
                selected_items = tuple(_state.source_tree.selectedItems())
            except RuntimeError:
                selected_items = ()
        return list(_state._selected_source_indices_state_helper(selected_items, source_index_from_item=_state._source_index_from_tree_item, fallback_source_index=_state.selected_source_part.get('index', -1), include_fallback=include_fallback))
    _state._selected_source_indices_from_tree = _selected_source_indices_from_tree

def _parts_outliner_mapping_step_005(_state):

    def _set_transform_source_indices(source_indices: Sequence[int]) -> None:
        _state.transform_source_indices.clear()
        _state.transform_source_indices.update(_state._alignment_part_transform_preview_queue_indices_helper(source_indices))
    _state._set_transform_source_indices = _set_transform_source_indices

def _parts_outliner_mapping_step_006(_state):

    def _clear_transform_source_indices() -> None:
        _state.transform_source_indices.clear()
    _state._clear_transform_source_indices = _clear_transform_source_indices

def _parts_outliner_mapping_step_007(_state):

    _state._resident_parts_session_active = lambda: resident_material_parameters_available(_state.dialog)

    def _active_mesh_edit_include_exclude_mutation_blocked() -> bool:
        if not (callable(_state._alignment_mesh_edit_tab_active) and _state._alignment_mesh_edit_tab_active()):
            return False
        if _state._resident_parts_session_active():
            return False
        message = 'Active Mesh Editor source-part include/exclude changes require native geometry execution; Python adjustment mutation fallback is disabled.'
        set_status_message = getattr(_state.self, 'set_status_message', None)
        if callable(set_status_message):
            set_status_message(message, error=True)
        return True
    _state._active_mesh_edit_include_exclude_mutation_blocked = _active_mesh_edit_include_exclude_mutation_blocked

def _parts_outliner_mapping_step_008(_state):

    def _active_mesh_edit_source_routing_mutation_blocked(action: str) -> bool:
        if not (callable(_state._alignment_mesh_edit_tab_active) and _state._alignment_mesh_edit_tab_active()):
            return False
        if _state._resident_parts_session_active():
            return False
        message = f'Active Mesh Editor source routing {action} requires native material execution; Python routing mutation fallback is disabled.'
        set_status_message = getattr(_state.self, 'set_status_message', None)
        if callable(set_status_message):
            set_status_message(message, error=True)
        return True
    _state._active_mesh_edit_source_routing_mutation_blocked = _active_mesh_edit_source_routing_mutation_blocked

def _parts_outliner_mapping_step_009(_state):

    def _set_source_parts_apply_pending(reason: str) -> None:
        reason_text = _state._source_parts_mark_apply_pending_helper(_state.source_parts_apply_state, reason)
        presentation = _state._source_parts_apply_pending_presentation_helper(reason_text)
        try:
            _state.apply_source_parts_button.setEnabled(presentation.apply_button_enabled)
            _state.source_parts_pending_label.setText(presentation.label_text)
            _state.source_parts_pending_label.setVisible(presentation.label_visible)
        except NameError:
            pass
        _state._set_preview_performance_status(presentation.performance_summary, details=presentation.performance_details)
    _state._set_source_parts_apply_pending = _set_source_parts_apply_pending

def _parts_outliner_mapping_step_010(_state):

    def _clear_source_parts_apply_pending() -> None:
        _state._source_parts_clear_apply_pending_helper(_state.source_parts_apply_state)
        presentation = _state._source_parts_clear_apply_pending_presentation_helper()
        try:
            _state.apply_source_parts_button.setEnabled(presentation.apply_button_enabled)
            _state.source_parts_pending_label.setText(presentation.label_text)
            _state.source_parts_pending_label.setVisible(presentation.label_visible)
        except NameError:
            pass
    _state._clear_source_parts_apply_pending = _clear_source_parts_apply_pending

def _parts_outliner_mapping_step_011(_state):

    def _set_source_parts_preview_rebuild_pending(reason: str) -> None:
        reason_text = _state._source_parts_mark_preview_rebuild_pending_helper(_state.source_parts_apply_state, reason)
        presentation = _state._source_parts_preview_rebuild_pending_presentation_helper(reason_text)
        try:
            _state.apply_source_parts_button.setEnabled(presentation.apply_button_enabled)
            _state.source_parts_pending_label.setText(presentation.label_text)
            _state.source_parts_pending_label.setVisible(presentation.label_visible)
        except NameError:
            pass
        _state._set_preview_performance_status(presentation.performance_summary, details=presentation.performance_details)
    _state._set_source_parts_preview_rebuild_pending = _set_source_parts_preview_rebuild_pending

def _parts_outliner_mapping_step_012(_state):

    def _clear_source_parts_preview_rebuild_pending() -> None:
        if not _state._source_parts_preview_rebuild_pending_helper(_state.source_parts_apply_state):
            return
        _state._clear_source_parts_apply_pending()
    _state._clear_source_parts_preview_rebuild_pending = _clear_source_parts_preview_rebuild_pending

def _parts_outliner_mapping_step_013(_state):

    def _add_source_tree_item(source_index: int, source: object) -> None:
        if _state._is_marker_source(source):
            return
        label = _state._source_part_display_label_helper(source_index, source, _state.source_display_overrides)
        role_hint = _state._source_role_label(source_index)
        copied_texture_rows = _state.copied_original_texture_intents_by_source.get(int(source_index), [])
        adjustment = _state.source_part_adjustments.get(source_index)
        item_state = _state._source_tree_item_state_helper(source_index=source_index, source=source, copied_texture_rows=copied_texture_rows, copied_texture_disabled=int(source_index) in _state.copied_original_texture_disabled_sources, adjustment=adjustment)
        source_item = _state._source_tree_item_helper(source_index=item_state.source_index, label=label, role_hint=role_hint, geometry_text=item_state.geometry_text, source_name=item_state.source_name, source_material=item_state.source_material, copied_texture_count=item_state.copied_texture_count, copied_texture_disabled=item_state.copied_texture_disabled, copied_texture_tooltip=_state._copied_original_texture_tooltip(source_index), enabled=item_state.enabled)
        _state.source_tree.addTopLevelItem(source_item)
        _state.source_items_by_index[source_index] = source_item
    _state._add_source_tree_item = _add_source_tree_item

def _parts_outliner_mapping_step_014(_state):

    def _source_item_check_state_changed(item: QTreeWidgetItem, column: int) -> None:
        source_index = _state._source_index_from_tree_item(item)
        toggle_state = _state._source_part_check_toggle_state_helper(source_index=source_index, column=column, guard_active=bool(_state.source_tree_item_update_guard.get('active')), checked=item.checkState(0) == _state.Qt.Checked, selected_source_index=_state.selected_source_part.get('index', -1))
        if not toggle_state.available:
            return
        if _state._active_mesh_edit_include_exclude_mutation_blocked():
            return
        _state._push_geometry_undo_snapshot(
            _state._source_part_edit_undo_label_helper(toggle_state.undo_action), metadata_only=True
        )
        adjustment = _state._ensure_source_part_adjustment(toggle_state.source_index)
        adjustment.enabled = toggle_state.enabled
        resident_updated = send_resident_material_parameters(
            _state.dialog,
            (resident_material_parameter_group(
                {'visible': bool(toggle_state.enabled)},
                source_submesh_indices=(toggle_state.source_index,),
            ),),
        )
        _state._refresh_source_assignment_columns()
        if toggle_state.refresh_selected_controls:
            if callable(_state._load_selected_part_controls):
                _state._load_selected_part_controls()
        if callable(_state._sync_highlight_sets):
            _state._sync_highlight_sets()
        if resident_updated:
            _state._clear_source_parts_apply_pending()
        elif toggle_state.apply_pending:
            _state._set_source_parts_apply_pending(_state._source_part_include_exclude_pending_reason_helper())
        else:
            _state._set_source_parts_preview_rebuild_pending(_state._source_part_include_exclude_pending_reason_helper())
            if callable(_state._queue_selection_preview_refresh):
                _state._queue_selection_preview_refresh()
            else:
                _state._queue_static_preview_rebuild()
    _state._source_item_check_state_changed = _source_item_check_state_changed

def _parts_outliner_mapping_step_015(_state):
    _state._outliner_source_index_from_item = lambda item: _state._parts_outliner_source_index_helper(item)
    _state._parts_outliner_drop_target_index = lambda item: _state._parts_outliner_drop_target_index_helper(item, user_role=int(_state.Qt.UserRole))

def _parts_outliner_mapping_step_016(_state):

    def _parts_outliner_set_source_selection(source_indices: Sequence[int], *, activate_transform: bool, select_reference_rows: bool=True) -> None:
        normalized = list(_state._unique_nonnegative_indices_helper(source_indices))
        if select_reference_rows:
            source_blocked = _state.source_tree.blockSignals(True)
            try:
                _state.source_tree.clearSelection()
                for source_index in normalized:
                    source_item = _state.source_items_by_index.get(source_index)
                    if source_item is None:
                        continue
                    source_item.setSelected(True)
                    _state.source_tree.setCurrentItem(source_item)
            finally:
                _state.source_tree.blockSignals(source_blocked)
        if activate_transform:
            _state.selected_source_part['index'] = normalized[0] if normalized else -1
            _state.selected_source_highlight_indices.clear()
            _state.selected_source_highlight_indices.update(normalized)
            _state._set_transform_source_indices(normalized)
        else:
            _state.selected_source_part['index'] = -1
            _state.selected_source_highlight_indices.clear()
            _state._clear_transform_source_indices()
    _state._parts_outliner_set_source_selection = _parts_outliner_set_source_selection

def _parts_outliner_mapping_step_017(_state):

    def _refresh_parts_outliner() -> None:
        if bool(_state.parts_outliner_item_update_guard.get('refreshing')):
            return
        revision = _state._parts_outliner_revision_helper(original_mesh=_state.original_mesh_for_mapping, replacement_mesh=_state.replacement_mesh_for_mapping, mapping_edits=_state.mapping_edits, preview_only_source_indices=_state.preview_only_source_indices, independent_output_source_indices=_state.independent_output_source_indices, copied_original_texture_intents_by_source=_state.copied_original_texture_intents_by_source)
        if _state._parts_outliner_cache_matches_helper(_state.parts_outliner_cache_state, revision, has_items=_state.parts_outliner_tree.topLevelItemCount() > 0):
            return
        _state._parts_outliner_cache_record_revision_helper(_state.parts_outliner_cache_state, revision)
        _state.parts_outliner_item_update_guard['refreshing'] = True
        try:
            _state.parts_outliner_tree.clear()
            _state.parts_outliner_source_items.clear()
            _state.parts_outliner_target_items.clear()
            assignment_index = _state._source_assignment_index_helper(_state.mapping_edits, parse_mapping_edit=_state._parse_mapping_edit)
            assigned_sources: set[int] = set()
            if _state.original_mesh_for_mapping is not None:
                for target_index, target in enumerate(_state.original_mesh_for_mapping.submeshes):
                    target_name = _state._target_display_name(target_index)
                    edit = _state.mapping_edits_by_target.get(target_index)
                    source_indices = _state._parse_mapping_edit(edit) if edit is not None else []
                    assigned_sources.update(_state._parts_outliner_source_indices_helper(source_indices))
                    target_label_text = getattr(target, 'material', '') or getattr(target, 'name', '') or target_name
                    state_text, state_color = _state._target_outliner_state(target_index, source_indices)
                    dds_cell_state = _state._mapping_target_dds_cell_state_helper(state_text=state_text, has_source_indices=bool(source_indices))
                    physics_text = _state._target_physics_status_text(target_label_text, target)
                    target_item = _state._parts_outliner_target_item_helper(target_index=target_index, label=_state._parts_outliner_target_label_helper(target_index, target_label_text, simplify_label=_state.simplified_part_label), role_hint=_state._mapping_role_hint(f"{getattr(target, 'name', '')} {getattr(target, 'material', '')}"), dds_text=_state._removed_target_dds_cell_text(target_label_text) if dds_cell_state['uses_removed_target_text'] else _state._target_texture_status_text(target_label_text), state_text=state_text, state_color=state_color, physics_text=physics_text, geometry_text=_state._parts_outliner_geometry_text_helper(target), source_indices=tuple(source_indices), texture_tooltip=_state._target_texture_status_details(target_label_text), physics_tooltip=_state._physics_status_tooltip(physics_text))
                    _state.parts_outliner_tree.addTopLevelItem(target_item)
                    _state.parts_outliner_target_items[target_index] = target_item
                    for source_index in source_indices:
                        source_state, source_color = _state._source_outliner_state(source_index, tuple(assignment_index.get(source_index, ())))
                        source_physics = _state._source_physics_status_text(source_index, target_index)
                        tooltip_source_index = _state._parts_outliner_copied_texture_tooltip_source_index_helper(source_index, _state.copied_original_texture_intents_by_source)
                        source_item = _state._parts_outliner_source_item_helper(source_index=source_index, target_index=target_index, label=_state._parts_outliner_source_label_helper(_state._parts_outliner_source_label(source_index)), target_text=target_name, role_label=_state._source_role_label(source_index), dds_text=_state._source_outliner_dds_text(source_index), state_text=source_state, state_color=source_color, physics_text=source_physics, geometry_text=_state._parts_outliner_source_geometry(source_index), physics_tooltip=_state._physics_status_tooltip(source_physics), copied_texture_tooltip=_state._copied_original_texture_tooltip(tooltip_source_index) if tooltip_source_index is not None else '')
                        target_item.addChild(source_item)
                        _state.parts_outliner_source_items[source_index] = source_item
                    target_item.setExpanded(True)
            unassigned_indices = _state._parts_outliner_unassigned_source_indices_helper(_state.replacement_mesh_for_mapping, tuple(assigned_sources), is_marker_source=_state._is_marker_source)
            if unassigned_indices:
                group_item = _state._parts_outliner_unassigned_group_item_helper(len(unassigned_indices))
                _state.parts_outliner_tree.addTopLevelItem(group_item)
                for source_index in unassigned_indices:
                    assigned_target_indices = tuple(assignment_index.get(int(source_index), ()))
                    source_state, source_color = _state._source_outliner_state(source_index, assigned_target_indices)
                    source_physics = _state._source_physics_status_text(source_index, -1)
                    tooltip_source_index = _state._parts_outliner_copied_texture_tooltip_source_index_helper(source_index, _state.copied_original_texture_intents_by_source)
                    source_item = _state._parts_outliner_source_item_helper(source_index=source_index, target_index=-1, label=_state._parts_outliner_source_label_helper(_state._parts_outliner_source_label(source_index)), target_text=_state._parts_outliner_unassigned_target_label_helper(), role_label=_state._source_role_label(source_index), dds_text=_state._source_outliner_dds_text(source_index), state_text=source_state, state_color=source_color, physics_text=source_physics, geometry_text=_state._parts_outliner_source_geometry(source_index), physics_tooltip=_state._physics_status_tooltip(source_physics), copied_texture_tooltip=_state._copied_original_texture_tooltip(tooltip_source_index) if tooltip_source_index is not None else '', unassigned=True)
                    group_item.addChild(source_item)
                    _state.parts_outliner_source_items[source_index] = source_item
                group_item.setExpanded(True)
            _state._fit_alignment_tree_height_to_rows(_state.parts_outliner_tree, minimum=128, screen_margin=420, maximum=420)
            _state.parts_outliner_tree.setProperty('cdmw_defer_autofit', False)
            _state._auto_fit_alignment_tree_columns(_state.parts_outliner_tree, (120, 110, 70, 64, 72, 56, 100), (260, 260, 150, 130, 140, 100, 220), expand_columns=(0, 1, 6))
        finally:
            _state.parts_outliner_item_update_guard['refreshing'] = False
    _state._refresh_parts_outliner = _refresh_parts_outliner

def _parts_outliner_mapping_step_018(_state):

    def _show_parts_outliner_context_menu(pos: QPoint) -> None:
        item = _state.parts_outliner_tree.itemAt(pos)
        if item is not None:
            _state.parts_outliner_tree.setCurrentItem(item)
            row_state = _state._parts_outliner_selection_row_state_helper(item, user_role=int(_state.Qt.UserRole))
            source_indices = tuple(row_state.get('source_indices', ())) if row_state is not None else ()
            if str(row_state.get('row_kind', '')) == 'source' and source_indices:
                source_index = int(source_indices[0])
                _state._parts_outliner_set_source_selection((source_index,), activate_transform=True)
                callback = _state._show_replacement_sources_context_menu_for_viewport
                if callable(callback):
                    callback(source_index, _state.parts_outliner_tree.viewport().mapToGlobal(pos))
                    return
        menu = _state.QMenu(_state.parts_outliner_tree)
        paste_action = menu.addAction(_state.original_part_clipboard_action_text['paste_replacement_source'])
        paste_action.setEnabled(_state._alignment_part_clipboard_can_paste())
        chosen = menu.exec(_state.parts_outliner_tree.viewport().mapToGlobal(pos))
        if chosen is paste_action:
            _state._paste_alignment_part_clipboard_as_replacement_source()
    _state._show_parts_outliner_context_menu = _show_parts_outliner_context_menu

def _parts_outliner_mapping_step_019(_state):

    def _apply_parts_outliner_source_target(source_index: int, target_index: int) -> None:
        if _state.replacement_mesh_for_mapping is None:
            return
        apply_state = _state._parts_outliner_source_target_apply_state_helper(source_index=source_index, target_index=target_index, source_count=len(_state.replacement_mesh_for_mapping.submeshes))
        if not apply_state.available:
            return
        if _state._active_mesh_edit_source_routing_mutation_blocked('target changes'):
            return
        _state._push_geometry_undo_snapshot('Change source target', metadata_only=True)
        route_state = _state._mapping_source_target_route_state_helper(apply_state.target_index)
        defer_preview = bool(route_state['defer_preview'])
        for candidate_target, edit in tuple(_state.mapping_edits):
            current_indices = tuple(_state._parse_mapping_edit(edit))
            updated_indices = _state._mapping_indices_for_source_target_helper(current_indices, apply_state.source_index, target_matches=int(candidate_target) == apply_state.target_index)
            if updated_indices != current_indices:
                _state._set_mapping_indices(candidate_target, updated_indices, push_undo=False, defer_preview=defer_preview)
        if route_state['preview_only']:
            _state.preview_only_source_indices.add(apply_state.source_index)
        else:
            _state.preview_only_source_indices.discard(apply_state.source_index)
        _state.independent_output_source_indices.discard(apply_state.source_index)
        _state.selected_target_slot['index'] = int(route_state['selected_target_index'])
        _state.texture_overrides_dirty['dirty'] = True
        _state._refresh_source_assignment_columns()
        _state._refresh_parts_outliner()
        _state._select_source_part_from_viewport(apply_state.source_index)
        try:
            _state._refresh_source_material_plan()
        except NameError:
            pass
        _state._update_mapping_status()
        preview_action = _state._source_part_routing_preview_action_helper(defer_preview=defer_preview, pending_reason=str(route_state['pending_reason']))
        if _state._resident_parts_session_active():
            _state._set_source_parts_apply_pending('resident source routing change awaits renderer/service confirmation')
        elif preview_action['apply_pending']:
            _state._set_source_parts_apply_pending(str(preview_action['pending_reason']))
        elif preview_action['queue_preview']:
            _state._queue_static_preview_rebuild()
    _state._apply_parts_outliner_source_target = _apply_parts_outliner_source_target

def _parts_outliner_mapping_step_020(_state):

    def _handle_parts_outliner_source_drop(source_item: object, target_item: object) -> bool:
        if not isinstance(source_item, _state.QTreeWidgetItem):
            return False
        source_index = _state._outliner_source_index_from_item(source_item)
        target_index = _state._parts_outliner_drop_target_index(target_item if isinstance(target_item, _state.QTreeWidgetItem) else None)
        if not _state._parts_outliner_source_drop_allowed_helper(refreshing=bool(_state.parts_outliner_item_update_guard.get('refreshing')), source_index=source_index, target_index=target_index):
            return False
        _state._apply_parts_outliner_source_target(source_index, target_index)
        return True
    _state._handle_parts_outliner_source_drop = _handle_parts_outliner_source_drop

def _parts_outliner_mapping_step_021(_state):

    def _apply_parts_outliner_source_role(source_index: int, role_value: str) -> None:
        action_state = _state._source_part_role_action_state_helper(source_index=source_index, role_value=role_value, undo_label=_state._parts_outliner_source_role_change_undo_label_helper(), refresh_reason=_state._parts_outliner_source_role_change_refresh_reason_helper())
        if not action_state.available:
            return
        if _state._active_mesh_edit_source_routing_mutation_blocked('role changes'):
            return
        _state._push_geometry_undo_snapshot(action_state.undo_label, metadata_only=True)
        _state._set_source_role_override_value(action_state.source_index, action_state.normalized_role)
        adjustment = _state.source_part_adjustments.get(action_state.source_index)
        resident_updated = send_source_role_material_parameters(
            _state.dialog,
            action_state.source_index,
            action_state.normalized_role,
            getattr(adjustment, 'emissive_color_rgb', ()) if adjustment is not None else (),
            emissive_strength=getattr(adjustment, 'emissive_strength', None) if adjustment is not None else None,
        )
        _state._refresh_source_assignment_columns(lightweight=True)
        _state._refresh_parts_outliner()
        _state._select_source_part_from_viewport(action_state.source_index)
        _state._queue_material_edit_refresh(refresh_plan=action_state.refresh_plan, force_plan=action_state.force_plan, refresh_preview=action_state.refresh_preview and not resident_updated, reason=action_state.refresh_reason)
        _state._update_mapping_status()
    _state._apply_parts_outliner_source_role = _apply_parts_outliner_source_role

def _parts_outliner_mapping_step_022(_state):

    def _open_parts_outliner_target_dropdown(item: QTreeWidgetItem, column: int) -> None:
        source_index = _state._outliner_source_index_from_item(item)
        if source_index < 0:
            return
        menu = _state.QMenu(_state.parts_outliner_tree)
        target_labels = tuple((_state._target_display_name(target_index) for target_index, _target in enumerate(_state.original_mesh_for_mapping.submeshes))) if _state.original_mesh_for_mapping is not None else ()
        for label, target_value in _state._parts_outliner_target_menu_specs_helper(target_labels):
            action = menu.addAction(label)
            action.setData(target_value)
        rect = _state.parts_outliner_tree.visualItemRect(item)
        point = _state.parts_outliner_tree.viewport().mapToGlobal(rect.bottomLeft())
        chosen = menu.exec(point)
        if chosen is None:
            return
        target_index = _state._parts_outliner_action_target_index_helper(chosen.data())
        _state._apply_parts_outliner_source_target(source_index, target_index)
    _state._open_parts_outliner_target_dropdown = _open_parts_outliner_target_dropdown

def _parts_outliner_mapping_step_023(_state):

    def _open_parts_outliner_role_dropdown(item: QTreeWidgetItem, column: int) -> None:
        source_index = _state._outliner_source_index_from_item(item)
        if source_index < 0:
            return
        menu = _state.QMenu(_state.parts_outliner_tree)
        for label, role_value in _state._parts_outliner_role_menu_specs_helper(_state.PARTS_OUTLINER_ROLE_OPTIONS):
            action = menu.addAction(label)
            action.setData(role_value)
        rect = _state.parts_outliner_tree.visualItemRect(item)
        point = _state.parts_outliner_tree.viewport().mapToGlobal(rect.bottomLeft())
        chosen = menu.exec(point)
        if chosen is None:
            return
        _state._apply_parts_outliner_source_role(source_index, _state._parts_outliner_action_role_value_helper(chosen.data()))
    _state._open_parts_outliner_role_dropdown = _open_parts_outliner_role_dropdown

def _parts_outliner_mapping_step_024(_state):

    def _handle_parts_outliner_item_clicked(item: QTreeWidgetItem, column: int) -> None:
        if item is None or bool(_state.parts_outliner_item_update_guard.get('refreshing')):
            return
        _state._parts_outliner_selection_changed(item, None)
        click_action = _state._parts_outliner_source_click_action_helper(item.data(0, _state.Qt.UserRole), column)
        if click_action == 'target':
            _state._open_parts_outliner_target_dropdown(item, column)
        elif click_action == 'role':
            _state._open_parts_outliner_role_dropdown(item, column)
    _state._handle_parts_outliner_item_clicked = _handle_parts_outliner_item_clicked

def _parts_outliner_mapping_step_025(_state):

    def _append_mapping_target_row(target_index: int, target: object) -> None:
        mapping = _state.mappings_by_target.get(int(target_index))
        row_state = _state._mapping_table_target_row_state_helper(target_index=target_index, target=target, mapping=mapping)
        target_role_hint = _state._mapping_role_hint(row_state.target_role_source_text)
        edit = _state.QLineEdit()
        edit.setText(row_state.initial_mapping_text)
        _state.initial_mapping_text_by_target[row_state.target_index] = edit.text()
        edit.setProperty('committed_mapping_text', edit.text())
        confidence_state = _state._mapping_target_confidence_state_helper(mapping)
        confidence_label_text = str(confidence_state['text'])
        confidence_color = str(confidence_state['color'])
        outliner_state, outliner_state_color = _state._target_outliner_state(row_state.target_index, row_state.initial_source_indices)
        confidence_label = _state.QLabel(confidence_label_text)
        confidence_label.setToolTip('Low confidence means the source name, size, or position did not strongly match this original slot. Override by typing the correct replacement source index.')
        confidence_label.setStyleSheet(f'color: {confidence_color}; font-weight: 600;')
        selected_text, selected_ok = _state._selected_source_summary(edit.text())
        selected_display = _state._mapping_source_cell_text(selected_text, selected_ok)
        target_details = _state._mapping_target_details_text_helper(row_state.target_index, row_state.target_label_text, target_role_hint, target)
        target_dds_status = _state._removed_target_dds_cell_text(row_state.target_label_text) if outliner_state == 'Removed' else _state._target_texture_status_text(row_state.target_label_text)
        mapping_item = _state._mapping_target_item_helper(target_index=row_state.target_index, target_label_text=row_state.target_label_text, target_role_hint=target_role_hint, selected_display=selected_display, outliner_state=outliner_state, outliner_state_color=outliner_state_color, target_dds_status=target_dds_status, physics_status=_state._target_physics_status_text(row_state.target_label_text, target), initial_source_indices=row_state.initial_source_indices, confidence_label_text=confidence_label_text, target_details=target_details, target_texture_details=_state._target_texture_status_details(row_state.target_label_text), selected_ok=selected_ok, removed=row_state.removed, mapping_text_empty=row_state.mapping_text_empty)
        _state.mapping_tree.addTopLevelItem(mapping_item)
        _state.mapping_items_by_target[row_state.target_index] = mapping_item

        def _update_selected_source_label(text: str, *, item: QTreeWidgetItem=mapping_item) -> None:
            summary, ok = _state._selected_source_summary(text)
            source_cell_state = _state._mapping_edit_source_cell_state_helper(text, edit.property('committed_mapping_text'), has_source_indices=_state._mapping_text_has_indices_helper(text))
            item.setText(3, _state._mapping_source_cell_text(summary, ok))
            item.setData(0, _state.Qt.UserRole, tuple(_state._parse_mapping_edit(edit)))
            item.setData(0, _state.Qt.UserRole + 3, bool(source_cell_state['is_empty']))
            item.setToolTip(3, _state._mapping_edit_draft_tooltip_helper())
            item.setForeground(3, _state.QBrush(_state.QColor(str(source_cell_state['foreground']))))
        edit.textChanged.connect(_update_selected_source_label)
        edit.editingFinished.connect(lambda edit=edit: _state._commit_mapping_edit(edit))
        edit.setPlaceholderText(_state._mapping_edit_placeholder_text_helper())
        edit.setToolTip(_state._source_index_help_text())
        edit.setMinimumHeight(max(22, edit.sizeHint().height()))
        edit.setSizePolicy(_state.QSizePolicy.Expanding, _state.QSizePolicy.Fixed)
        _state.mapping_tree.setItemWidget(mapping_item, 2, edit)
        _state.mapping_edits.append((row_state.target_index, edit))
        _state.mapping_edits_by_target[row_state.target_index] = edit
    _state._append_mapping_target_row = _append_mapping_target_row

def _parts_outliner_mapping_step_026(_state):

    def _build_mapping_table_chunk() -> None:
        if not _state._alignment_dialog_widgets_live() or not _state._qt_object_is_valid(_state.mapping_progress_label) or (not _state._qt_object_is_valid(_state.mapping_tree)):
            _state.mapping_table_build_timer.stop()
            return
        if _state._mapping_table_build_complete_helper(_state.mapping_table_build_state):
            _state.mapping_table_build_timer.stop()
            return
        started = _state.time.monotonic()
        appended = 0
        total = len(_state.mapping_targets)
        while _state._mapping_table_build_next_index_helper(_state.mapping_table_build_state) < total:
            target_index = _state._mapping_table_build_next_index_helper(_state.mapping_table_build_state)
            _state._append_mapping_target_row(target_index, _state.mapping_targets[target_index])
            _state._mapping_table_build_set_next_index_helper(_state.mapping_table_build_state, target_index + 1)
            appended += 1
            if appended >= _state._mapping_table_chunk_row_limit_helper() or _state.time.monotonic() - started >= _state._mapping_table_chunk_time_budget_seconds_helper():
                break
        current = _state._mapping_table_build_next_index_helper(_state.mapping_table_build_state)
        _state.mapping_progress_label.setText(_state._mapping_table_loading_progress_text_helper(current, total))
        chunk_presentation = _state._mapping_table_chunk_presentation_state_helper(current_rows=current, total_rows=total, show_low_only=_state.low_confidence_filter_checkbox.isChecked(), show_empty_only=_state.empty_targets_filter_checkbox.isChecked())
        if chunk_presentation.filters_active or chunk_presentation.complete:
            _state._apply_target_slot_filters(fit_height=chunk_presentation.fit_height)
        if chunk_presentation.complete:
            _state._mapping_table_build_mark_complete_helper(_state.mapping_table_build_state)
            _state.mapping_table_build_timer.stop()
            _state.mapping_progress_label.setText(_state._mapping_table_ready_progress_text_helper(total))
            _state._refresh_source_assignment_columns(lightweight=True)
            _state.mapping_tree.setProperty('cdmw_defer_autofit', False)
            _state._auto_fit_alignment_tree_columns(_state.mapping_tree, _state._mapping_table_column_min_widths_helper(), _state._mapping_table_column_max_widths_helper(), expand_columns=_state._mapping_table_expand_columns_helper())
            _state._capture_initial_geometry_snapshot()
            _state._refresh_parts_outliner()
    _state._build_mapping_table_chunk = _build_mapping_table_chunk

def _parts_outliner_mapping_step_027(_state):

    def _apply_target_slot_filters(_checked: object=None, *, fit_height: bool=True) -> None:
        if not _state._alignment_dialog_widgets_live() or not _state._qt_object_is_valid(_state.mapping_tree):
            return
        show_low_only = bool(_state.low_confidence_filter_checkbox.isChecked())
        show_empty_only = bool(_state.empty_targets_filter_checkbox.isChecked())
        for item_index in range(_state.mapping_tree.topLevelItemCount()):
            item = _state.mapping_tree.topLevelItem(item_index)
            confidence_text = str(item.data(0, _state.Qt.UserRole + 2) or '')
            is_empty = bool(item.data(0, _state.Qt.UserRole + 3))
            item.setHidden(_state._mapping_table_row_hidden_by_filters_helper(confidence_text=confidence_text, is_empty=is_empty, show_low_only=show_low_only, show_empty_only=show_empty_only))
        if fit_height:
            _state._fit_alignment_tree_height_to_rows(_state.mapping_tree, **_state._mapping_table_height_fit_kwargs_helper())
    _state._apply_target_slot_filters = _apply_target_slot_filters

def _parts_outliner_mapping_step_028(_state):

    def _ensure_mapping_table_building() -> None:
        if not _state._alignment_dialog_widgets_live() or not _state._qt_object_is_valid(_state.mapping_progress_label):
            _state.mapping_table_build_timer.stop()
            return
        if not _state._mapping_table_build_can_start_helper(_state.mapping_table_build_requested, _state.mapping_table_build_state):
            return
        _state._mapping_table_build_mark_requested_started_helper(_state.mapping_table_build_requested)
        _state.mapping_progress_label.setText(_state._mapping_table_loading_progress_text_helper(0, len(_state.mapping_targets)))
        _state.QTimer.singleShot(_state._mapping_table_build_start_delay_ms_helper(), _state.mapping_table_build_timer.start)
    _state._ensure_mapping_table_building = _ensure_mapping_table_building

STEPS = (
    _parts_outliner_mapping_step_001,
    _parts_outliner_mapping_step_002,
    _parts_outliner_mapping_step_003,
    _parts_outliner_mapping_step_004,
    _parts_outliner_mapping_step_005,
    _parts_outliner_mapping_step_006,
    _parts_outliner_mapping_step_007,
    _parts_outliner_mapping_step_008,
    _parts_outliner_mapping_step_009,
    _parts_outliner_mapping_step_010,
    _parts_outliner_mapping_step_011,
    _parts_outliner_mapping_step_012,
    _parts_outliner_mapping_step_013,
    _parts_outliner_mapping_step_014,
    _parts_outliner_mapping_step_015,
    _parts_outliner_mapping_step_016,
    _parts_outliner_mapping_step_017,
    _parts_outliner_mapping_step_018,
    _parts_outliner_mapping_step_019,
    _parts_outliner_mapping_step_020,
    _parts_outliner_mapping_step_021,
    _parts_outliner_mapping_step_022,
    _parts_outliner_mapping_step_023,
    _parts_outliner_mapping_step_024,
    _parts_outliner_mapping_step_025,
    _parts_outliner_mapping_step_026,
    _parts_outliner_mapping_step_027,
    _parts_outliner_mapping_step_028,
)
