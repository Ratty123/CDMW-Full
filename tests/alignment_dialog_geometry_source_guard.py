"""Focused source guard extracted from the legacy alignment guard module."""

from __future__ import annotations

from tests import test_alignment_dialog_source_guards as _base

ROOT = _base.ROOT
_main_window_source = _base._main_window_source
static_replacement_ui_concern_source = _base.static_replacement_ui_concern_source
static_replacement_callback_concern_source = _base.static_replacement_callback_concern_source
ARCHIVE_STATIC_REPLACEMENT_ORIGINAL_PARTS = _base.ARCHIVE_STATIC_REPLACEMENT_ORIGINAL_PARTS
ARCHIVE_STATIC_REPLACEMENT_SOURCE_TREE_STATE = _base.ARCHIVE_STATIC_REPLACEMENT_SOURCE_TREE_STATE
ARCHIVE_STATIC_REPLACEMENT_PARTS_OUTLINER_STATE = _base.ARCHIVE_STATIC_REPLACEMENT_PARTS_OUTLINER_STATE
ARCHIVE_STATIC_REPLACEMENT_ALIGNMENT_SETUP_STATE = _base.ARCHIVE_STATIC_REPLACEMENT_ALIGNMENT_SETUP_STATE
ARCHIVE_STATIC_REPLACEMENT_MAPPING_TABLE_STATE = _base.ARCHIVE_STATIC_REPLACEMENT_MAPPING_TABLE_STATE


def assert_alignment_geometry_tab_uses_compact_source_parts_master_list(case: object) -> None:
    source = _main_window_source()
    outliner_source = static_replacement_ui_concern_source(ROOT, "source_parts_outliner")
    mesh_ui_source = static_replacement_ui_concern_source(ROOT, "mesh_geometry_preview")
    preview_model_source = static_replacement_callback_concern_source(ROOT, "preview_model")
    selection_source = static_replacement_callback_concern_source(ROOT, "source_tree_selection")
    original_parts_source = ARCHIVE_STATIC_REPLACEMENT_ORIGINAL_PARTS.read_text(encoding="utf-8")
    source_tree_state_source = ARCHIVE_STATIC_REPLACEMENT_SOURCE_TREE_STATE.read_text(encoding="utf-8")
    parts_outliner_state_source = ARCHIVE_STATIC_REPLACEMENT_PARTS_OUTLINER_STATE.read_text(encoding="utf-8")
    case.assertIn("_state.parts_outliner_control_text = _state._parts_outliner_control_text_helper()", outliner_source)
    case.assertIn("_state.parts_outliner_group = _state.QGroupBox(str(_state.parts_outliner_control_text['title']))", outliner_source)
    case.assertIn("_state.parts_outliner_group.setObjectName('MeshReplacementPartsOutliner')", outliner_source)
    case.assertIn("_state.parts_outliner_group.setToolTip(str(_state.parts_outliner_control_text['tooltip']))", outliner_source)
    case.assertIn("_state.parts_outliner_tree.setObjectName('MeshReplacementUnifiedPartsOutliner')", outliner_source)
    case.assertIn("_state.parts_outliner_tree.setHeaderLabels(list(_state.parts_outliner_control_text['headers']))", outliner_source)
    case.assertIn('"title": "Parts Outliner"', parts_outliner_state_source)
    case.assertIn('"headers": ["Item", "Target", "Role", "DDS", "State", "Physics", "Geometry"]', parts_outliner_state_source)
    case.assertNotIn('parts_outliner_tree.setHeaderLabels(["Item", "Target", "Role", "DDS", "Use"', source)
    case.assertNotIn("parts_outliner_tree.setItemWidget", source)
    case.assertIn("for tree in (_state.source_tree, _state.original_tree, _state.mapping_tree, _state.parts_outliner_tree):", selection_source)
    case.assertIn("_parts_outliner_unassigned_group_item_helper", source)
    case.assertIn("def parts_outliner_unassigned_group_item", source)
    case.assertIn('"Unassigned Sources"', source)
    case.assertIn('"Preview-only"', source)
    case.assertNotIn('MeshReplacementOutlinerTargetCombo', source)
    case.assertNotIn('MeshReplacementOutlinerRoleCombo', source)
    case.assertNotIn('MeshReplacementOutlinerIncludeCheckbox', source)
    case.assertIn("_state.source_tree_control_text = _state._source_tree_control_text_helper()", outliner_source)
    case.assertIn("_state.source_parts_group = _state.QGroupBox(str(_state.source_tree_control_text['source_group_title']))", outliner_source)
    case.assertIn("_state.source_parts_group.setObjectName('MeshReplacementReferenceParts')", outliner_source)
    case.assertIn("_state.source_tree.setHeaderLabels(list(_state.source_tree_control_text['source_tree_headers']))", outliner_source)
    case.assertIn('"source_group_title": "Replacement reference parts"', source_tree_state_source)
    case.assertIn('"source_tree_headers": ["Use", "#", "Source", "Role", "Target", "Status", "Geometry"]', source_tree_state_source)
    case.assertIn("_state._source_tree_population_queued_text_helper(_state.replacement_source_count)", outliner_source)
    case.assertIn("_source_tree_population_loading_text_helper(min(start, total), total)", source)
    case.assertIn("_source_tree_population_ready_text_helper(source_tree.topLevelItemCount())", source)
    case.assertIn("_state.source_parts_layout.addWidget(_state.source_tree, 0)", outliner_source)
    case.assertNotIn("parts_outliner_layout.addWidget(source_parts_group, 0)", source)
    case.assertIn("_state.mapping_layout.addWidget(_state.source_parts_group, 0)", outliner_source)
    case.assertIn("original_parts_label.setVisible(True)", source)
    case.assertIn("_state.original_part_tree_control_text = _state._original_part_tree_control_text_helper()", outliner_source)
    case.assertIn("_state.original_tree.setHeaderLabels(list(_state.original_part_tree_control_text['headers']))", outliner_source)
    case.assertIn('"headers": ["#", "Original part", "Role", "Geometry", "Copied as"]', original_parts_source)
    case.assertNotIn("original_tree.setVisible(False)", source)
    case.assertIn("source_parts_group.setVisible(True)", source)
    alignment_setup_source = ARCHIVE_STATIC_REPLACEMENT_ALIGNMENT_SETUP_STATE.read_text(encoding="utf-8")
    mapping_table_state_source = ARCHIVE_STATIC_REPLACEMENT_MAPPING_TABLE_STATE.read_text(encoding="utf-8")
    case.assertIn("_state._mapping_table_queued_progress_text_helper(len(_state.mapping_targets))", outliner_source)
    case.assertIn("_mapping_table_loading_progress_text_helper(current, total)", source)
    case.assertIn("_state._mapping_table_loading_progress_text_helper(0, len(_state.mapping_targets))", source)
    case.assertIn("_mapping_table_ready_progress_text_helper(total)", source)
    case.assertIn("_mapping_table_chunk_presentation_state_helper(", source)
    case.assertIn("def mapping_table_queued_progress_text", mapping_table_state_source)
    case.assertIn("def mapping_table_loading_progress_text", mapping_table_state_source)
    case.assertIn("def mapping_table_ready_progress_text", mapping_table_state_source)
    case.assertIn("def mapping_table_chunk_presentation_state", mapping_table_state_source)
    case.assertIn("def geometry_mapping_summary_html", mapping_table_state_source)
    case.assertIn(
        "_state._geometry_mapping_summary_html_helper(source_count, active_target_count, empty_target_count, session_edit_count=appended_count)",
        preview_model_source,
    )
    case.assertIn(
        "session_edit_count=appended_count",
        source,
    )
    case.assertIn("Replacement parts</span>", mapping_table_state_source)
    case.assertIn("Active targets</span>", mapping_table_state_source)
    case.assertIn("Empty targets</span>", mapping_table_state_source)
    case.assertIn("def output_impact_review_presentation", mapping_table_state_source)
    case.assertIn("_output_impact_review_presentation_helper(", source)
    case.assertIn("_state.output_impact_review_label.setText(output_impact['html'])", preview_model_source)
    case.assertIn("_state.output_impact_review_label.setToolTip(output_impact['tooltip'])", preview_model_source)
    case.assertIn("Removed targets: ", mapping_table_state_source)
    case.assertIn("DDS override rows ready", mapping_table_state_source)
    case.assertIn('control_tabs.addTab(parts_tab, alignment_workflow_control_text["parts_label"])', source)
    case.assertIn('"parts_label": "Parts && Routing"', alignment_setup_source)
    case.assertIn("_state.advanced_routing_layout.addWidget(_state.parts_outliner_group, 0)", outliner_source)
    case.assertIn("_state.parts_outliner_layout.addWidget(_state.mapping_group, 0)", preview_model_source)
    case.assertNotIn("parts_outliner_layout.addWidget(geometry_overview_group, 0)", source)
    case.assertIn("_state.parts_layout.addWidget(_state.parts_outliner_panel, 1)", preview_model_source)
    case.assertNotIn("selected_part_panel = QWidget(parts_routing_splitter)", source)
    case.assertIn("_state.show_advanced_mapping_checkbox = _state.QCheckBox(_state.mapping_table_action_control_text['advanced_mapping'])", outliner_source)
    case.assertIn('"advanced_mapping": "Advanced Mapping"', mapping_table_state_source)
    case.assertNotIn('show_advanced_mapping_checkbox.setProperty("cdmw_default_on_for_all_users", True)', source)
    case.assertIn("show_advanced_mapping_checkbox.setChecked(False)", source)
    case.assertIn("Normal routing should use Parts Outliner.", mapping_table_state_source)
    case.assertIn("_mapping_table_target_row_state_helper(", source)
    case.assertIn("def mapping_table_target_row_state", mapping_table_state_source)
    case.assertIn("_state.geometry_hint = _state.QLabel(_state.mapping_table_action_control_text['geometry_hint_html'])", preview_model_source)
    case.assertIn("_state.geometry_hint.setToolTip(_state.mapping_table_action_control_text['geometry_hint_tooltip'])", preview_model_source)
    case.assertIn("_state.advanced_part_tools_section = _state.CollapsibleSection(", preview_model_source)
    case.assertIn("'Part Setup'", preview_model_source)
    case.assertIn("_state.advanced_routing_section = _state.CollapsibleSection('Advanced Routing', expanded=False)", outliner_source)
    case.assertNotIn('mapping_table_action_control_text["advanced_part_transform"]', source)
    case.assertIn("_state.mapping_tree.setHeaderLabels(list(_state.mapping_table_action_control_text['headers']))", outliner_source)
    case.assertIn('"headers": ["Target", "Role", "Index", "Source", "State", "DDS", "Physics"]', mapping_table_state_source)
    case.assertIn("_state.target_slots_label = _state.QLabel(_state.mapping_table_action_control_text['target_slots_html'])", outliner_source)
    case.assertIn('"low_confidence_filter": "Show low confidence only"', mapping_table_state_source)
    case.assertIn('"empty_targets_filter": "Show removed targets only"', mapping_table_state_source)
    case.assertIn("_state.low_confidence_filter_checkbox = _state.QCheckBox(_state.mapping_table_action_control_text['low_confidence_filter'])", outliner_source)
    case.assertIn("_state.empty_targets_filter_checkbox = _state.QCheckBox(_state.mapping_table_action_control_text['empty_targets_filter'])", outliner_source)
    case.assertLess(
        outliner_source.index("_state.clear_all_selection_button = _state.selection_route_buttons['clear_all']"),
        outliner_source.index("_state.parts_outliner_mapping_callbacks = _state.create_alignment_parts_outliner_mapping_callbacks"),
    )
    case.assertIn("mapping_tree.setColumnHidden(2, True)", source)
    case.assertIn("mapping_tree.setMinimumHeight(96)", source)
    case.assertIn("def mapping_table_height_fit_kwargs", mapping_table_state_source)
    case.assertIn("_state._fit_alignment_tree_height_to_rows(_state.mapping_tree, **_state._mapping_table_height_fit_kwargs_helper())", outliner_source)
    case.assertIn("_state.advanced_routing_layout.addWidget(_state.mapping_tree, 0)", outliner_source)
    case.assertIn("mapping_tree.setVisible(False)", source)
    case.assertIn("_state._set_advanced_mapping_visible(_state.show_advanced_mapping_checkbox.isChecked())", outliner_source)
    case.assertIn("_mapping_table_advanced_visibility_state_helper(checked)", source)
    case.assertIn("original_parts_label.setVisible(True)", source)
    case.assertIn("source_parts_group.setVisible(True)", source)
    case.assertIn("mapping_action_button.setVisible(visibility_state.visible_widgets)", source)
    case.assertIn("for column, hidden in visibility_state.hidden_columns", source)
    case.assertIn("def mapping_table_advanced_visibility_state", mapping_table_state_source)
    case.assertIn("_state.mesh_edit_group.setSizePolicy(_state.QSizePolicy.Expanding, _state.QSizePolicy.Maximum)", mesh_ui_source)
    case.assertNotIn("mesh_edit_group.setMaximumWidth(mesh_edit_control_content_min_width)", source)
    case.assertIn("_state.mesh_edit_layout = _state.QVBoxLayout(_state.mesh_edit_group)", mesh_ui_source)
    case.assertIn("_state.mesh_edit_layout.addWidget(_state.mesh_edit_tool_palette)", mesh_ui_source)
    case.assertIn("QFrame#MeshEditVerticalToolPalette QToolButton:checked", source)
    case.assertIn("_state.mesh_edit_layout_page.addWidget(_state.mesh_edit_group, 0)", mesh_ui_source)
    case.assertIn("source_mix_tray.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)", source)
    case.assertNotIn("source_mix_intro_row.addWidget", source)
    case.assertIn("parts_layout.addStretch(1)", source)
    case.assertIn("_queue_alignment_post_open_task(_queue_static_preview_refresh)", source)
    case.assertIn("_queue_alignment_post_open_task(_clear_all_part_selections)", source)
    case.assertLess(
        source.index("_queue_alignment_post_open_task(_queue_static_preview_refresh)"),
        source.index("_queue_alignment_post_open_task(_clear_all_part_selections)"),
    )
    case.assertIn("def visible_tree_row_count(item: QTreeWidgetItem) -> int:", source)
    case.assertIn("count += visible_tree_row_count(item.child(child_index))", source)
