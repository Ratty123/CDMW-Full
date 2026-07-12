from __future__ import annotations

def _source_parts_outliner_step_001(_state):
    _state.CollapsibleSection = _state.context.get('CollapsibleSection')
    _state.Dict = _state.context.get('Dict')
    _state.MeshReplacementPartsOutlinerTree = _state.context.get('MeshReplacementPartsOutlinerTree')
    _state.QAbstractItemView = _state.context.get('QAbstractItemView')
    _state.QCheckBox = _state.context.get('QCheckBox')
    _state.QComboBox = _state.context.get('QComboBox')
    _state.QDoubleSpinBox = _state.context.get('QDoubleSpinBox')
    _state.QGridLayout = _state.context.get('QGridLayout')
    _state.QGroupBox = _state.context.get('QGroupBox')
    _state.QHBoxLayout = _state.context.get('QHBoxLayout')
    _state.QKeySequence = _state.context.get('QKeySequence')
    _state.QLabel = _state.context.get('QLabel')
    _state.QPushButton = _state.context.get('QPushButton')
    _state.QShortcut = _state.context.get('QShortcut')
    _state.QSizePolicy = _state.context.get('QSizePolicy')
    _state.QSlider = _state.context.get('QSlider')
    _state.QTimer = _state.context.get('QTimer')
    _state.QTreeWidget = _state.context.get('QTreeWidget')
    _state.QTreeWidgetItem = _state.context.get('QTreeWidgetItem')
    _state.QVBoxLayout = _state.context.get('QVBoxLayout')
    _state.QWidget = _state.context.get('QWidget')
    _state.Qt = _state.context.get('Qt')
    _state.SOURCE_ROLE_OPTIONS = _state.context.get('SOURCE_ROLE_OPTIONS')
    _state._alignment_dialog_widgets_live = _state.context.get('_alignment_dialog_widgets_live')
    _state._alignment_startup_original_part_list_progress_text_helper = _state.context.get('_alignment_startup_original_part_list_progress_text_helper')
    _state._alignment_startup_step = _state.context.get('_alignment_startup_step')
    _state._append_mesh_part_to_geometry = _state.context.get('_append_mesh_part_to_geometry')
    _state._apply_dds_detail_thumbnail_state = _state.context.get('_apply_dds_detail_thumbnail_state')
    _state._apply_source_material_grouped_routing = _state.context.get('_apply_source_material_grouped_routing')
    _state._apply_source_part_preview_changes = _state.context.get('_apply_source_part_preview_changes')
    _state._auto_fit_alignment_tree_columns = _state.context.get('_auto_fit_alignment_tree_columns')
    _state._clear_all_part_selections = _state.context.get('_clear_all_part_selections')
    _state._commit_spinbox_text = _state.context.get('_commit_spinbox_text')
    _state._configure_alignment_tree = _state.context.get('_configure_alignment_tree')
    _state._copied_original_source_indices_helper = _state.context.get('_copied_original_source_indices_helper')
    _state._copy_original_part_payload_helper = _state.context.get('_copy_original_part_payload_helper')
    _state._copy_source_part_with_adjustment_helper = _state.context.get('_copy_source_part_with_adjustment_helper')
    _state._dds_detail_clear_state_helper = _state.context.get('_dds_detail_clear_state_helper')
    _state._delete_selected_source_parts = _state.context.get('_delete_selected_source_parts')
    _state._duplicate_selected_part = _state.context.get('_duplicate_selected_part')
    _state._fit_alignment_tree_height_to_rows = _state.context.get('_fit_alignment_tree_height_to_rows')
    _state._install_alignment_tree_column_autofit = _state.context.get('_install_alignment_tree_column_autofit')
    _state._is_marker_source = _state.context.get('_is_marker_source')
    _state._make_double_spin_helper = _state.context.get('_make_double_spin_helper')
    _state._mapping_role_hint = _state.context.get('_mapping_role_hint')
    _state._mapping_route_button_style_helper = _state.context.get('_mapping_route_button_style_helper')
    _state._mapping_route_control_text_helper = _state.context.get('_mapping_route_control_text_helper')
    _state._mapping_route_primary_button_specs_helper = _state.context.get('_mapping_route_primary_button_specs_helper')
    _state._mapping_route_selection_button_specs_helper = _state.context.get('_mapping_route_selection_button_specs_helper')
    _state._mapping_table_action_control_text_helper = _state.context.get('_mapping_table_action_control_text_helper')
    _state._mapping_table_build_initial_state_helper = _state.context.get('_mapping_table_build_initial_state_helper')
    _state._mapping_table_build_requested_initial_state_helper = _state.context.get('_mapping_table_build_requested_initial_state_helper')
    _state._mapping_table_column_max_widths_helper = _state.context.get('_mapping_table_column_max_widths_helper')
    _state._mapping_table_column_min_widths_helper = _state.context.get('_mapping_table_column_min_widths_helper')
    _state._mapping_table_expand_columns_helper = _state.context.get('_mapping_table_expand_columns_helper')
    _state._mapping_table_height_fit_kwargs_helper = _state.context.get('_mapping_table_height_fit_kwargs_helper')
    _state._mapping_table_queued_progress_text_helper = _state.context.get('_mapping_table_queued_progress_text_helper')
    _state._mirror_submesh_x_helper = _state.context.get('_mirror_submesh_x_helper')
    _state._normalize = _state.context.get('_normalize')
    _state._original_part_action_control_text_helper = _state.context.get('_original_part_action_control_text_helper')
    _state._original_part_clipboard_action_text_helper = _state.context.get('_original_part_clipboard_action_text_helper')
    _state._original_part_clipboard_can_paste_helper = _state.context.get('_original_part_clipboard_can_paste_helper')
    _state._original_part_tree_control_text_helper = _state.context.get('_original_part_tree_control_text_helper')
    _state._original_part_tree_item_helper = _state.context.get('_original_part_tree_item_helper')
    _state._original_target_label_helper = _state.context.get('_original_target_label_helper')
    _state._part_inspector_loading_initial_state_helper = _state.context.get('_part_inspector_loading_initial_state_helper')
    _state._part_physics_review_reason_helper = _state.context.get('_part_physics_review_reason_helper')
    _state._part_selection_clear_scope_state_helper = _state.context.get('_part_selection_clear_scope_state_helper')
    _state._parts_outliner_cache_initial_state_helper = _state.context.get('_parts_outliner_cache_initial_state_helper')
    _state._parts_outliner_control_text_helper = _state.context.get('_parts_outliner_control_text_helper')
    _state._parts_outliner_item_update_guard_initial_state_helper = _state.context.get('_parts_outliner_item_update_guard_initial_state_helper')
    _state._physics_status_tooltip_helper = _state.context.get('_physics_status_tooltip_helper')
    _state._qt_object_is_valid = _state.context.get('_qt_object_is_valid')
    _state._queue_alignment_post_open_task = _state.context.get('_queue_alignment_post_open_task')
    _state._queue_part_transform_preview_update = _state.context.get('_queue_part_transform_preview_update')
    _state._queue_selection_preview_refresh = _state.context.get('_queue_selection_preview_refresh')
    _state._reference_vertices_for_appended_part_helper = _state.context.get('_reference_vertices_for_appended_part_helper')
    _state._refresh_added_part_texture_tree = _state.context.get('_refresh_added_part_texture_tree')
    _state._refresh_source_material_plan = _state.context.get('_refresh_source_material_plan')
    _state._remap_selected_source_index_helper = _state.context.get('_remap_selected_source_index_helper')
    _state._remap_source_index_collection_helper = _state.context.get('_remap_source_index_collection_helper')
    _state._remap_source_index_dict_helper = _state.context.get('_remap_source_index_dict_helper')
    _state._reset_geometry_changes = _state.context.get('_reset_geometry_changes')
    _state._rotate_xyz = _state.context.get('_rotate_xyz')
    _state._source_display_name = _state.context.get('_source_display_name')
    _state._source_mirror_plane_x_helper = _state.context.get('_source_mirror_plane_x_helper')
    _state._source_part_inspector_control_text_helper = _state.context.get('_source_part_inspector_control_text_helper')
    _state._source_part_transform_control_text_helper = _state.context.get('_source_part_transform_control_text_helper')
    _state._source_parts_action_control_text_helper = _state.context.get('_source_parts_action_control_text_helper')
    _state._source_physics_status_text_helper = _state.context.get('_source_physics_status_text_helper')
    _state._source_role_label = _state.context.get('_source_role_label')
    _state._source_texture_slot_count_helper = _state.context.get('_source_texture_slot_count_helper')
    _state._source_tree_context_selection_initial_state_helper = _state.context.get('_source_tree_context_selection_initial_state_helper')
    _state._source_tree_control_text_helper = _state.context.get('_source_tree_control_text_helper')
    _state._source_tree_item_update_guard_initial_state_helper = _state.context.get('_source_tree_item_update_guard_initial_state_helper')
    _state._source_tree_layout_state_helper = _state.context.get('_source_tree_layout_state_helper')
    _state._source_tree_population_initial_state_helper = _state.context.get('_source_tree_population_initial_state_helper')
    _state._source_tree_population_queued_text_helper = _state.context.get('_source_tree_population_queued_text_helper')
    _state._suggested_mappings_by_target_helper = _state.context.get('_suggested_mappings_by_target_helper')
    _state._sync_highlight_sets = _state.context.get('_sync_highlight_sets')

def _source_parts_outliner_step_002(_state):
    _state._target_contract_source_indices_helper = _state.context.get('_target_contract_source_indices_helper')
    _state._target_display_name = _state.context.get('_target_display_name')
    _state._target_physics_status_text_helper = _state.context.get('_target_physics_status_text_helper')
    _state._target_texture_status_details_helper = _state.context.get('_target_texture_status_details_helper')
    _state._target_texture_status_text_helper = _state.context.get('_target_texture_status_text_helper')
    _state._tree_item_primary_index_helper = _state.context.get('_tree_item_primary_index_helper')
    _state._undo_geometry_change = _state.context.get('_undo_geometry_change')
    _state._update_selection_context = _state.context.get('_update_selection_context')
    _state._wrap_spin_with_slider_helper = _state.context.get('_wrap_spin_with_slider_helper')
    _state.added_texture_tree = _state.context.get('added_texture_tree')
    _state.alignment_part_clipboard = _state.context.get('alignment_part_clipboard')
    _state.alignment_d3d11_preview_host = _state.context.get('alignment_d3d11_preview_host')
    _state.alignment_startup_text = _state.context.get('alignment_startup_text')
    _state.clear_alignment_selection_button = _state.context.get('clear_alignment_selection_button')
    _state.complete_external_swap_checkbox = _state.context.get('complete_external_swap_checkbox')
    _state.control_tabs = _state.context.get('control_tabs')
    _state.copied_original_physics_sensitive_sources = _state.context.get('copied_original_physics_sensitive_sources')
    _state.copied_original_source_indices = _state.context.get('copied_original_source_indices')
    _state.create_alignment_original_clipboard_callbacks = _state.context.get('create_alignment_original_clipboard_callbacks')
    _state.create_alignment_original_copy_payload_callbacks = _state.context.get('create_alignment_original_copy_payload_callbacks')
    _state.create_alignment_original_part_copy_callbacks = _state.context.get('create_alignment_original_part_copy_callbacks')
    _state.create_alignment_original_reference_preview_callbacks = _state.context.get('create_alignment_original_reference_preview_callbacks')
    _state.create_alignment_original_source_filter_callbacks = _state.context.get('create_alignment_original_source_filter_callbacks')
    _state.create_alignment_original_texture_intent_callbacks = _state.context.get('create_alignment_original_texture_intent_callbacks')
    _state.create_alignment_parts_outliner_mapping_callbacks = _state.context.get('create_alignment_parts_outliner_mapping_callbacks')
    _state.create_alignment_selected_part_adjustment_callbacks = _state.context.get('create_alignment_selected_part_adjustment_callbacks')
    _state.create_alignment_selected_part_control_callbacks = _state.context.get('create_alignment_selected_part_control_callbacks')
    _state.create_alignment_selected_part_glow_picker_callbacks = _state.context.get('create_alignment_selected_part_glow_picker_callbacks')
    _state.create_alignment_selection_clear_callbacks = _state.context.get('create_alignment_selection_clear_callbacks')
    _state.create_alignment_selection_route_callbacks = _state.context.get('create_alignment_selection_route_callbacks')
    _state.create_alignment_source_part_assignment_callbacks = _state.context.get('create_alignment_source_part_assignment_callbacks')
    _state.create_alignment_source_part_geometry_action_callbacks = _state.context.get('create_alignment_source_part_geometry_action_callbacks')
    _state.create_alignment_source_part_glow_callbacks = _state.context.get('create_alignment_source_part_glow_callbacks')
    _state.create_alignment_source_part_mutation_callbacks = _state.context.get('create_alignment_source_part_mutation_callbacks')
    _state.create_alignment_source_part_transform_control_callbacks = _state.context.get('create_alignment_source_part_transform_control_callbacks')
    _state.create_alignment_source_role_flush_callbacks = _state.context.get('create_alignment_source_role_flush_callbacks')
    _state.create_alignment_source_role_tree_callbacks = _state.context.get('create_alignment_source_role_tree_callbacks')
    _state.create_alignment_source_tree_role_callbacks = _state.context.get('create_alignment_source_tree_role_callbacks')
    _state.create_alignment_source_tree_selection_callbacks = _state.context.get('create_alignment_source_tree_selection_callbacks')
    _state.dds_detail_label = _state.context.get('dds_detail_label')
    _state.dds_detail_panel = _state.context.get('dds_detail_panel')
    _state.dialog = _state.context.get('dialog')
    _state.mapping_hint = _state.context.get('mapping_hint')
    _state.mapping_edits_by_target = _state.context.get('mapping_edits_by_target')
    _state.mapping_layout = _state.context.get('mapping_layout')
    _state.material_plan_control_text = _state.context.get('material_plan_control_text')
    _state.modify_original_clone_mode = bool(_state.context.get('modify_original_clone_mode'))
    _state.material_plan_tree = _state.context.get('material_plan_tree')
    _state.material_routing_tree = _state.context.get('material_routing_tree')
    _state.original_items_by_index = _state.context.get('original_items_by_index')
    _state.original_mesh_for_mapping = _state.context.get('original_mesh_for_mapping')
    _state.parts_tab = _state.context.get('parts_tab')
    _state.replacement_mesh_for_mapping = _state.context.get('replacement_mesh_for_mapping')
    _state._modify_original_texture_tuning_enabled = _state.context.get('_modify_original_texture_tuning_enabled')
    if not callable(_state._modify_original_texture_tuning_enabled):
        _state._modify_original_texture_tuning_enabled = lambda: False
    _state.selected_added_part_texture_row = _state.context.get('selected_added_part_texture_row')
    _state.selected_original_part = _state.context.get('selected_original_part')
    _state.selected_texture_plan_source = _state.context.get('selected_texture_plan_source')
    _state.selected_texture_row = _state.context.get('selected_texture_row')
    _state.sidecar_bindings = _state.context.get('sidecar_bindings')
    _state.source_parts_apply_state = _state.context.get('source_parts_apply_state')
    _state.suggested_mappings = _state.context.get('suggested_mappings')
    _state.texture_override_tree = _state.context.get('texture_override_tree')
    _state.texture_sets = _state.context.get('texture_sets')
    _state.prompt_shell_context = _state.context.get('prompt_shell_context')

def _source_parts_outliner_step_003(_state):

    def _late_context_value(name: str) -> object:
        if isinstance(_state.prompt_shell_context, dict) and name in _state.prompt_shell_context:
            return _state.prompt_shell_context.get(name)
        return _state.context.get(name)
    _state._late_context_value = _late_context_value

def _source_parts_outliner_step_004(_state):
    _state.source_tree_control_text = _state._source_tree_control_text_helper()
    _state.source_tree_layout_state = _state._source_tree_layout_state_helper()
    _state.source_tree = _state.QTreeWidget()
    _state.source_tree.setHeaderLabels(list(_state.source_tree_control_text['source_tree_headers']))
    _state.source_tree.setMinimumHeight(_state.source_tree_layout_state.minimum_height)
    _state._configure_alignment_tree(_state.source_tree, _state.source_tree_layout_state.configure_widths, max_height=_state.source_tree_layout_state.max_height, stretch_columns=_state.source_tree_layout_state.expand_columns, persist_key=_state.source_tree_layout_state.persist_key)
    _state.source_tree.setSelectionMode(_state.QAbstractItemView.ExtendedSelection)
    _state.source_tree.setSelectionBehavior(_state.QAbstractItemView.SelectRows)
    _state.source_parts_group = _state.QGroupBox(str(_state.source_tree_control_text['source_group_title']))
    _state.source_parts_group.setObjectName('MeshReplacementReferenceParts')
    _state.source_parts_group.setSizePolicy(_state.QSizePolicy.Expanding, _state.QSizePolicy.Maximum)
    _state.source_parts_layout = _state.QVBoxLayout(_state.source_parts_group)
    _state.source_parts_layout.setContentsMargins(5, 3, 5, 3)
    _state.source_parts_layout.setSpacing(3)
    _state.source_parts_layout.setAlignment(_state.Qt.AlignTop)
    _state._source_index_from_tree_item = lambda item: _state._tree_item_primary_index_helper(item)
    _state.source_tree_context_selection_state = _state._source_tree_context_selection_initial_state_helper()
    _state.alignment_original_source_filter_callbacks = _state.create_alignment_original_source_filter_callbacks({**_state.context, **_state._factory_globals, **vars(_state), '_selected_source_indices_from_tree': lambda *args, **kwargs: _state._selected_source_indices_from_tree(*args, **kwargs)})
    _state._SourceTreeContextSelectionFilter = _state.alignment_original_source_filter_callbacks._SourceTreeContextSelectionFilter
    _state.source_tree_context_selection_filter = _state._SourceTreeContextSelectionFilter(_state.source_tree)
    _state.source_tree.viewport().installEventFilter(_state.source_tree_context_selection_filter)
    _state.source_tree_item_update_guard = _state._source_tree_item_update_guard_initial_state_helper()
    _state._copied_original_source_indices = lambda: _state._copied_original_source_indices_helper(_state.replacement_mesh_for_mapping, _state.copied_original_source_indices)
    _state.alignment_original_reference_preview_callbacks = _state.create_alignment_original_reference_preview_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
    _state._refresh_original_reference_preview = _state.alignment_original_reference_preview_callbacks._refresh_original_reference_preview
    _state.original_tree = _state.QTreeWidget()
    _state.original_part_tree_control_text = _state._original_part_tree_control_text_helper()
    _state.original_tree.setHeaderLabels(list(_state.original_part_tree_control_text['headers']))
    _state.original_tree.setMinimumHeight(72)
    _state._configure_alignment_tree(_state.original_tree, (36, 130, 68, 98, 92), max_height=128, stretch_columns=(1, 4), persist_key='original_parts')
    _state._alignment_startup_step(_state.alignment_startup_text['original_part_list'])
    for _state.original_index, _state.original_part in enumerate(_state.original_mesh_for_mapping.submeshes):
        if _state.original_index and _state.original_index % 25 == 0:
            _state._alignment_startup_step(_state._alignment_startup_original_part_list_progress_text_helper(_state.original_index))
        _state.label = getattr(_state.original_part, 'material', '') or getattr(_state.original_part, 'name', '') or f'target {_state.original_index}'
        _state.role_hint = _state._mapping_role_hint(f"{getattr(_state.original_part, 'name', '')} {getattr(_state.original_part, 'material', '')}")
        _state.geometry_text = f"{len(getattr(_state.original_part, 'vertices', ()) or ()):,.0f} vertices, {len(getattr(_state.original_part, 'faces', ()) or ()):,.0f} faces"
        _state.original_item = _state._original_part_tree_item_helper(original_index=_state.original_index, label=_state.label, role_hint=_state.role_hint, geometry_text=_state.geometry_text, source_name=str(getattr(_state.original_part, 'name', '') or ''), source_material=str(getattr(_state.original_part, 'material', '') or ''))
        _state.original_tree.addTopLevelItem(_state.original_item)
        _state.original_items_by_index[_state.original_index] = _state.original_item
    _state.original_part_action_control_text = _state._original_part_action_control_text_helper()
    _state.original_copy_button = _state.QPushButton(_state.original_part_action_control_text['copy'])
    _state.original_copy_assign_button = _state.QPushButton(_state.original_part_action_control_text['copy_assign'])
    _state.original_clear_selection_button = _state.QPushButton(_state.original_part_action_control_text['clear_selection'])
    _state.original_copy_button.setToolTip(_state.original_part_action_control_text['copy_tooltip'])
    _state.original_copy_assign_button.setToolTip(_state.original_part_action_control_text['copy_assign_tooltip'])
    _state.original_clear_selection_button.setToolTip(_state.original_part_action_control_text['clear_selection_tooltip'])
    for _state.original_button in (_state.original_copy_button, _state.original_copy_assign_button, _state.original_clear_selection_button):
        _state.original_button.setMinimumWidth(0)
    _state._original_index_from_tree_item = lambda item: _state._tree_item_primary_index_helper(item)
    _state._original_target_label = lambda original_index: _state._original_target_label_helper(original_index, _state.original_mesh_for_mapping)
    _state.alignment_original_texture_intent_callbacks = _state.create_alignment_original_texture_intent_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
    _state._selected_original_index_from_tree = _state.alignment_original_texture_intent_callbacks._selected_original_index_from_tree
    _state._original_part_texture_intent_rows = _state.alignment_original_texture_intent_callbacks._original_part_texture_intent_rows
    _state._copied_original_texture_tooltip = _state.alignment_original_texture_intent_callbacks._copied_original_texture_tooltip
    _state._copied_original_dds_badge = _state.alignment_original_texture_intent_callbacks._copied_original_dds_badge
    _state._part_physics_review_reason = lambda label_text, part: _state._part_physics_review_reason_helper(label_text, part)
    _state._copy_original_part_payload = lambda original_index: _state._copy_original_part_payload_helper(original_index, _state.original_mesh_for_mapping, target_label=_state._original_target_label, role_hint=_state._mapping_role_hint, texture_intent_rows=_state._original_part_texture_intent_rows, physics_review_reason=_state._part_physics_review_reason)
    _state.alignment_original_copy_payload_callbacks = _state.create_alignment_original_copy_payload_callbacks({**_state.context, **_state._factory_globals, **vars(_state), '_add_source_tree_item': lambda *args, **kwargs: _state._add_source_tree_item(*args, **kwargs), '_load_selected_part_controls': lambda *args, **kwargs: _state._load_selected_part_controls(*args, **kwargs), '_parse_mapping_edit': lambda *args, **kwargs: _state._parse_mapping_edit(*args, **kwargs), '_refresh_added_part_texture_tree': lambda *args, **kwargs: _state._refresh_added_part_texture_tree(*args, **kwargs), '_refresh_parts_outliner': lambda *args, **kwargs: _state._refresh_parts_outliner(*args, **kwargs), '_refresh_source_material_plan': lambda *args, **kwargs: _state._refresh_source_material_plan(*args, **kwargs), '_selected_target_index': lambda *args, **kwargs: _state._selected_target_index(*args, **kwargs), '_set_mapping_indices': lambda *args, **kwargs: _state._set_mapping_indices(*args, **kwargs), '_set_transform_source_indices': lambda *args, **kwargs: _state._set_transform_source_indices(*args, **kwargs)})
    _state._refresh_copied_original_texture_ui = _state.alignment_original_copy_payload_callbacks._refresh_copied_original_texture_ui
    _state._append_original_part_payload_as_source = _state.alignment_original_copy_payload_callbacks._append_original_part_payload_as_source
    _state.original_part_clipboard_action_text = _state._original_part_clipboard_action_text_helper()
    _state.alignment_original_clipboard_callbacks = _state.create_alignment_original_clipboard_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
    _state._copy_original_part_to_alignment_clipboard = _state.alignment_original_clipboard_callbacks._copy_original_part_to_alignment_clipboard
    _state._paste_alignment_part_clipboard_as_replacement_source = _state.alignment_original_clipboard_callbacks._paste_alignment_part_clipboard_as_replacement_source
    _state._show_original_parts_context_menu = _state.alignment_original_clipboard_callbacks._show_original_parts_context_menu
    _state._alignment_part_clipboard_can_paste = lambda: _state._original_part_clipboard_can_paste_helper(_state.alignment_part_clipboard, _state.original_mesh_for_mapping)
    _state.alignment_original_clipboard_callbacks = _state.create_alignment_original_clipboard_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
    _state._copy_original_part_to_alignment_clipboard = _state.alignment_original_clipboard_callbacks._copy_original_part_to_alignment_clipboard
    _state._paste_alignment_part_clipboard_as_replacement_source = _state.alignment_original_clipboard_callbacks._paste_alignment_part_clipboard_as_replacement_source
    _state._show_original_parts_context_menu = _state.alignment_original_clipboard_callbacks._show_original_parts_context_menu
    _state.alignment_original_part_copy_callbacks = _state.create_alignment_original_part_copy_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
    _state._copy_selected_original_part = _state.alignment_original_part_copy_callbacks._copy_selected_original_part
    _state.alignment_source_role_tree_callbacks = _state.create_alignment_source_role_tree_callbacks({**_state.context, **_state._factory_globals, **vars(_state), '_apply_source_part_preview_changes': lambda *args, **kwargs: _state._apply_source_part_preview_changes(*args, **kwargs), '_delete_selected_source_parts': lambda *args, **kwargs: _state._delete_selected_source_parts(*args, **kwargs), '_load_selected_part_controls': lambda *args, **kwargs: _state._load_selected_part_controls(*args, **kwargs), '_refresh_parts_outliner': lambda *args, **kwargs: _state._refresh_parts_outliner(*args, **kwargs), '_selected_source_index': lambda *args, **kwargs: _state._selected_source_index(*args, **kwargs), '_selected_source_indices_from_tree': lambda *args, **kwargs: _state._selected_source_indices_from_tree(*args, **kwargs)})
    _state._apply_source_role_selection = _state.alignment_source_role_tree_callbacks._apply_source_role_selection
    _state._show_replacement_sources_context_menu = _state.alignment_source_role_tree_callbacks._show_replacement_sources_context_menu
    _state._show_replacement_sources_context_menu_for_viewport = _state.alignment_source_role_tree_callbacks._show_replacement_sources_context_menu_for_viewport
    _state._populate_source_tree_chunk = _state.alignment_source_role_tree_callbacks._populate_source_tree_chunk
    _state.alignment_source_tree_role_callbacks = _state.create_alignment_source_tree_role_callbacks({**_state.context, **_state._factory_globals, **vars(_state), '_apply_source_role_selection': lambda *args, **kwargs: _state._apply_source_role_selection(*args, **kwargs), '_refresh_parts_outliner': lambda *args, **kwargs: _state._refresh_parts_outliner(*args, **kwargs)})
    _state._open_source_tree_role_dropdown = _state.alignment_source_tree_role_callbacks._open_source_tree_role_dropdown
    _state._handle_source_tree_item_clicked = _state.alignment_source_tree_role_callbacks._handle_source_tree_item_clicked
    _state._finish_source_tree_population = _state.alignment_source_tree_role_callbacks._finish_source_tree_population
    _state.alignment_source_role_tree_callbacks = _state.create_alignment_source_role_tree_callbacks({**_state.context, **_state._factory_globals, **vars(_state), '_apply_source_part_preview_changes': lambda *args, **kwargs: _state._apply_source_part_preview_changes(*args, **kwargs), '_delete_selected_source_parts': lambda *args, **kwargs: _state._delete_selected_source_parts(*args, **kwargs), '_load_selected_part_controls': lambda *args, **kwargs: _state._load_selected_part_controls(*args, **kwargs), '_refresh_parts_outliner': lambda *args, **kwargs: _state._refresh_parts_outliner(*args, **kwargs), '_selected_source_index': lambda *args, **kwargs: _state._selected_source_index(*args, **kwargs), '_selected_source_indices_from_tree': lambda *args, **kwargs: _state._selected_source_indices_from_tree(*args, **kwargs)})
    _state._apply_source_role_selection = _state.alignment_source_role_tree_callbacks._apply_source_role_selection
    _state._show_replacement_sources_context_menu = _state.alignment_source_role_tree_callbacks._show_replacement_sources_context_menu
    _state._show_replacement_sources_context_menu_for_viewport = _state.alignment_source_role_tree_callbacks._show_replacement_sources_context_menu_for_viewport
    _state._populate_source_tree_chunk = _state.alignment_source_role_tree_callbacks._populate_source_tree_chunk
    _state.original_copy_button.clicked.connect(lambda _checked=False: _state._copy_selected_original_part(assign_to_target=False))
    _state.original_copy_assign_button.clicked.connect(lambda _checked=False: _state._copy_selected_original_part(assign_to_target=True))
    _state.original_tree.setContextMenuPolicy(_state.Qt.CustomContextMenu)
    _state.original_tree.customContextMenuRequested.connect(_state._show_original_parts_context_menu)
    _state.source_tree.setContextMenuPolicy(_state.Qt.CustomContextMenu)
    _state.source_tree.itemClicked.connect(_state._handle_source_tree_item_clicked)
    _state.original_parts_label = _state.QLabel(str(_state.source_tree_control_text['original_label_html']))
    _state.original_parts_label.setTextFormat(_state.Qt.RichText)
    _state.original_parts_label.setVisible(True)
    _state.mapping_layout.addWidget(_state.original_parts_label)
    _state._fit_alignment_tree_height_to_rows(_state.original_tree, minimum=72, screen_margin=520, maximum=220)
    _state._auto_fit_alignment_tree_columns(_state.original_tree, (34, 100, 60, 110, 80), (48, 220, 140, 180, 160), expand_column=1)
    _state.original_tree.setVisible(True)

def _source_parts_outliner_step_005(_state):
    _state.mapping_layout.addWidget(_state.original_tree, 0)
    _state.original_button_panel = _state.QWidget()
    _state.original_button_panel.setVisible(True)
    _state.original_button_row = _state.QHBoxLayout(_state.original_button_panel)
    _state.original_button_row.setContentsMargins(0, 0, 0, 0)
    _state.original_button_row.addWidget(_state.original_copy_button)
    _state.original_button_row.addWidget(_state.original_copy_assign_button)
    _state.original_button_row.addWidget(_state.original_clear_selection_button)
    _state.original_button_row.addStretch(1)
    _state.mapping_layout.addWidget(_state.original_button_panel)
    _state.mapping_layout.addWidget(_state.source_parts_group, 0)
    _state.source_parts_group.setVisible(True)
    _state._alignment_startup_step(_state.alignment_startup_text['replacement_source_queue'])
    _state.source_tree_population_timer = _state.QTimer(_state.dialog)
    _state.source_tree_population_timer.setInterval(0)
    _state.source_tree_population_state = _state._source_tree_population_initial_state_helper()
    _state.replacement_source_count = len(getattr(_state.replacement_mesh_for_mapping, 'submeshes', ()) or ())
    _state.source_tree_progress_label = _state.QLabel(_state._source_tree_population_queued_text_helper(_state.replacement_source_count))
    _state.source_tree_progress_label.setObjectName('HintLabel')
    _state.source_tree_progress_label.setWordWrap(True)
    _state.replacement_sources_label = _state.QLabel(str(_state.source_tree_control_text['replacement_label_html']))
    _state.replacement_sources_label.setTextFormat(_state.Qt.RichText)
    _state.replacement_sources_label.setVisible(False)
    _state.source_parts_layout.addWidget(_state.source_tree_progress_label)
    _state._fit_alignment_tree_height_to_rows(_state.source_tree, **_state.source_tree_layout_state.height_fit_kwargs)
    _state._auto_fit_alignment_tree_columns(_state.source_tree, _state.source_tree_layout_state.autofit_min_widths, _state.source_tree_layout_state.autofit_max_widths, expand_columns=_state.source_tree_layout_state.expand_columns)
    _state._install_alignment_tree_column_autofit(_state.source_tree, _state.source_tree_layout_state.autofit_min_widths, _state.source_tree_layout_state.autofit_max_widths, expand_columns=_state.source_tree_layout_state.expand_columns)
    _state.source_parts_layout.addWidget(_state.source_tree, 0)
    _state.source_parts_button_row = _state.QHBoxLayout()
    _state.source_parts_button_row.setContentsMargins(0, 0, 0, 0)
    _state.source_parts_button_row.setSpacing(4)
    _state.source_parts_action_control_text = _state._source_parts_action_control_text_helper()
    _state.duplicate_source_parts_button = _state.QPushButton(_state.source_parts_action_control_text['duplicate_button'])
    _state.delete_source_parts_button = _state.QPushButton(_state.source_parts_action_control_text['delete_button'])
    _state.apply_source_parts_button = _state.QPushButton(_state.source_parts_action_control_text['apply_button'])
    _state.duplicate_source_parts_button.setObjectName(_state.source_parts_action_control_text['duplicate_object'])
    _state.delete_source_parts_button.setObjectName(_state.source_parts_action_control_text['delete_object'])
    _state.apply_source_parts_button.setObjectName(_state.source_parts_action_control_text['apply_object'])
    _state.duplicate_source_parts_button.setToolTip(_state.source_parts_action_control_text['duplicate_tooltip'])
    _state.delete_source_parts_button.setToolTip(_state.source_parts_action_control_text['delete_tooltip'])
    _state.apply_source_parts_button.setToolTip(_state.source_parts_action_control_text['apply_tooltip'])
    _state.apply_source_parts_button.setEnabled(bool(_state.source_parts_apply_state.get('pending')))
    for _state.source_parts_button in (_state.duplicate_source_parts_button, _state.delete_source_parts_button, _state.apply_source_parts_button):
        _state.source_parts_button.setMinimumWidth(0)
        _state.source_parts_button_row.addWidget(_state.source_parts_button)
    _state.source_parts_button_row.addStretch(1)
    _state.source_parts_layout.addLayout(_state.source_parts_button_row)
    _state.source_parts_pending_label = _state.QLabel(_state.source_parts_action_control_text['pending_label'])
    _state.source_parts_pending_label.setObjectName('HintLabel')
    _state.source_parts_pending_label.setWordWrap(True)
    _state.source_parts_pending_label.setVisible(False)
    _state.source_parts_layout.addWidget(_state.source_parts_pending_label)
    _state.source_parts_group.setMaximumHeight(16777215)
    _state._alignment_startup_step(_state.alignment_startup_text['routing_controls'])
    _state.mapping_table_action_control_text = _state._mapping_table_action_control_text_helper()
    _state.advanced_routing_section = _state.CollapsibleSection('Advanced Routing', expanded=False)
    _state.advanced_routing_section.setVisible(not _state.modify_original_clone_mode)
    _state.advanced_routing_layout = _state.advanced_routing_section.body_layout
    if _state.mapping_hint is not None:
        _state.advanced_routing_layout.addWidget(_state.mapping_hint)
    _state.mapping_layout.addWidget(_state.advanced_routing_section)
    _state.mapping_tree = _state.QTreeWidget()
    _state.mapping_tree.setHeaderLabels(list(_state.mapping_table_action_control_text['headers']))
    _state.mapping_tree.setMinimumHeight(96)
    _state._configure_alignment_tree(_state.mapping_tree, (170, 70, 118, 190, 76, 88, 72), max_height=0, stretch_columns=(0, 3), persist_key='target_routing')
    _state.mapping_tree.setHorizontalScrollBarPolicy(_state.Qt.ScrollBarAlwaysOff)
    _state.mapping_tree.setColumnHidden(1, True)
    _state.mapping_tree.setProperty('cdmw_defer_autofit', True)
    _state.mappings_by_target = _state._suggested_mappings_by_target_helper(_state.suggested_mappings)
    _state.initial_mapping_text_by_target: _state.Dict[int, str] = {}
    _state.mapping_table_build_state = _state._mapping_table_build_initial_state_helper()
    _state.mapping_table_build_timer = _state.QTimer(_state.dialog)
    _state.mapping_table_build_timer.setInterval(0)
    _state.mapping_targets = tuple(getattr(_state.original_mesh_for_mapping, 'submeshes', ()) or ())
    _state.mapping_progress_label = _state.QLabel(_state._mapping_table_queued_progress_text_helper(len(_state.mapping_targets)))
    _state.mapping_progress_label.setObjectName('HintLabel')
    _state.mapping_progress_label.setWordWrap(True)
    _state._target_contract_source_indices = lambda target_label_text: _state._target_contract_source_indices_helper(target_label_text, _state.original_mesh_for_mapping, _state.mapping_edits_by_target, _state.mappings_by_target)
    _state._source_texture_slot_count = lambda source_indices: _state._source_texture_slot_count_helper(source_indices, _state.replacement_mesh_for_mapping, _state.texture_sets)
    _state._target_texture_status_details = lambda target_label_text: _state._target_texture_status_details_helper(target_label_text, _state.sidecar_bindings, _state._target_contract_source_indices(target_label_text), _state.replacement_mesh_for_mapping, _state.texture_sets)
    _state._target_texture_status_text = lambda target_label_text: _state._target_texture_status_text_helper(target_label_text, _state.sidecar_bindings, _state._source_texture_slot_count(_state._target_contract_source_indices(target_label_text)))
    _state._target_physics_status_text = lambda target_label_text, target: _state._target_physics_status_text_helper(target_label_text, target, physics_review_reason=_state._part_physics_review_reason)
    _state._source_physics_status_text = lambda source_index, target_index=-1: _state._source_physics_status_text_helper(source_index, target_index, _state.replacement_mesh_for_mapping, _state.copied_original_physics_sensitive_sources, source_role_label=_state._source_role_label, source_display_name=_state._source_display_name, physics_review_reason=_state._part_physics_review_reason)
    _state._physics_status_tooltip = lambda status_text: _state._physics_status_tooltip_helper(status_text)
    _state.parts_outliner_control_text = _state._parts_outliner_control_text_helper()
    _state.parts_outliner_group = _state.QGroupBox(str(_state.parts_outliner_control_text['title']))
    _state.parts_outliner_group.setObjectName('MeshReplacementPartsOutliner')
    _state.parts_outliner_group.setToolTip(str(_state.parts_outliner_control_text['tooltip']))
    _state.parts_outliner_group.setSizePolicy(_state.QSizePolicy.Expanding, _state.QSizePolicy.Maximum)
    _state.parts_outliner_layout = _state.QVBoxLayout(_state.parts_outliner_group)
    _state.parts_outliner_layout.setContentsMargins(5, 3, 5, 3)
    _state.parts_outliner_layout.setSpacing(3)
    _state.parts_outliner_tree = _state.MeshReplacementPartsOutlinerTree()
    _state.parts_outliner_tree.setObjectName('MeshReplacementUnifiedPartsOutliner')
    _state.parts_outliner_tree.setHeaderLabels(list(_state.parts_outliner_control_text['headers']))
    _state.parts_outliner_tree.setMinimumHeight(128)
    _state.parts_outliner_tree.setHorizontalScrollBarPolicy(_state.Qt.ScrollBarAlwaysOff)
    _state.parts_outliner_tree.setSelectionMode(_state.QAbstractItemView.SingleSelection)
    _state.parts_outliner_tree.setDragEnabled(True)
    _state.parts_outliner_tree.setAcceptDrops(True)
    _state.parts_outliner_tree.viewport().setAcceptDrops(True)
    _state.parts_outliner_tree.setDropIndicatorShown(True)
    _state.parts_outliner_tree.setDragDropMode(_state.QAbstractItemView.InternalMove)

def _source_parts_outliner_step_006(_state):
    _state.parts_outliner_tree.setDefaultDropAction(_state.Qt.MoveAction)
    _state.parts_outliner_tree.setDragDropOverwriteMode(False)
    _state.parts_outliner_tree.setProperty('cdmw_defer_autofit', True)
    _state._configure_alignment_tree(_state.parts_outliner_tree, (150, 124, 78, 76, 82, 62, 110), max_height=340, stretch_columns=(0, 1, 6), persist_key='unified_parts_outliner')
    _state.parts_outliner_tree.setRootIsDecorated(True)
    _state.parts_outliner_layout.addWidget(_state.parts_outliner_tree, 0)
    _state.parts_outliner_item_update_guard = _state._parts_outliner_item_update_guard_initial_state_helper()
    _state.parts_outliner_cache_state = _state._parts_outliner_cache_initial_state_helper()
    _state.parts_outliner_source_items: _state.Dict[int, _state.QTreeWidgetItem] = {}
    _state.parts_outliner_target_items: _state.Dict[int, _state.QTreeWidgetItem] = {}
    _state.low_confidence_filter_checkbox = _state.QCheckBox(_state.mapping_table_action_control_text['low_confidence_filter'])
    _state.empty_targets_filter_checkbox = _state.QCheckBox(_state.mapping_table_action_control_text['empty_targets_filter'])
    _state.mapping_table_build_requested = _state._mapping_table_build_requested_initial_state_helper()
    _state.QTimer.singleShot(0, lambda: (_state._fit_alignment_tree_height_to_rows(_state.original_tree, minimum=72, screen_margin=520, maximum=220), _state._fit_alignment_tree_height_to_rows(_state.source_tree, **_state.source_tree_layout_state.height_fit_kwargs), _state._fit_alignment_tree_height_to_rows(_state.mapping_tree, **_state._mapping_table_height_fit_kwargs_helper()), _state._auto_fit_alignment_tree_columns(_state.original_tree, (34, 100, 60, 110, 80), (48, 220, 140, 180, 160), expand_column=1), _state._auto_fit_alignment_tree_columns(_state.source_tree, _state.source_tree_layout_state.autofit_min_widths, _state.source_tree_layout_state.autofit_max_widths, expand_columns=_state.source_tree_layout_state.expand_columns), _state._auto_fit_alignment_tree_columns(_state.mapping_tree, _state._mapping_table_column_min_widths_helper(), _state._mapping_table_column_max_widths_helper(), expand_columns=_state._mapping_table_expand_columns_helper())))
    _state.advanced_routing_layout.addWidget(_state.parts_outliner_group, 0)
    _state.target_slots_label = _state.QLabel(_state.mapping_table_action_control_text['target_slots_html'])
    _state.target_slots_label.setWordWrap(True)
    _state.target_slots_label.setTextFormat(_state.Qt.RichText)
    _state.target_slots_label.setToolTip(_state.mapping_table_action_control_text['target_slots_tooltip'])
    _state.target_slots_label.setVisible(False)
    _state.advanced_routing_layout.addWidget(_state.target_slots_label)
    _state.advanced_routing_layout.addWidget(_state.mapping_progress_label)
    _state.mapping_progress_label.setVisible(False)
    _state.mapping_filter_row = _state.QHBoxLayout()
    _state.mapping_filter_row.addWidget(_state.low_confidence_filter_checkbox)
    _state.mapping_filter_row.addWidget(_state.empty_targets_filter_checkbox)
    _state.mapping_filter_row.addStretch(1)
    _state.advanced_routing_layout.addLayout(_state.mapping_filter_row)
    _state.clear_all_guesses_button = _state.QPushButton(_state.mapping_table_action_control_text['clear_all_guesses'])
    _state.apply_best_guesses_button = _state.QPushButton(_state.mapping_table_action_control_text['apply_best_guesses'])
    _state.group_materials_button = _state.QPushButton(_state.mapping_table_action_control_text['group_materials'])
    _state.preview_target_button = _state.QPushButton(_state.mapping_table_action_control_text['preview_target'])
    _state.clear_all_guesses_button.setToolTip(_state.mapping_table_action_control_text['clear_all_guesses_tooltip'])
    _state.apply_best_guesses_button.setToolTip(_state.mapping_table_action_control_text['apply_best_guesses_tooltip'])
    _state.group_materials_button.setToolTip(_state.mapping_table_action_control_text['group_materials_tooltip'])
    _state.preview_target_button.setToolTip(_state.mapping_table_action_control_text['preview_target_tooltip'])
    for _state.mapping_action_button in (_state.clear_all_guesses_button, _state.apply_best_guesses_button, _state.group_materials_button, _state.preview_target_button):
        _state.mapping_action_button.setMinimumWidth(0)
    _state.mapping_action_row = _state.QHBoxLayout()
    _state.mapping_action_row.addWidget(_state.clear_all_guesses_button)
    _state.mapping_action_row.addWidget(_state.apply_best_guesses_button)
    _state.mapping_action_row.addWidget(_state.group_materials_button)
    _state.mapping_action_row.addWidget(_state.preview_target_button)
    _state.mapping_action_row.addStretch(1)
    _state.advanced_routing_layout.addLayout(_state.mapping_action_row)
    _state.show_advanced_mapping_checkbox = _state.QCheckBox(_state.mapping_table_action_control_text['advanced_mapping'])
    _state.show_advanced_mapping_checkbox.setToolTip(_state.mapping_table_action_control_text['advanced_mapping_tooltip'])
    _state.show_advanced_mapping_checkbox.setChecked(False)
    _state.advanced_routing_layout.addWidget(_state.show_advanced_mapping_checkbox)
    _state.mapping_tree.setColumnHidden(2, True)
    _state.mapping_tree.setVisible(False)
    _state.advanced_routing_layout.addWidget(_state.mapping_tree, 0)
    _state.mapping_status_label = _state.QLabel(_state.mapping_table_action_control_text['mapping_status_initial'])
    _state.mapping_status_label.setWordWrap(True)
    _state.mapping_status_label.setTextFormat(_state.Qt.RichText)
    _state.mapping_status_label.setObjectName('MeshRoutingSelectedContractSummary')
    _state.advanced_routing_layout.addWidget(_state.mapping_status_label)
    _state.mapping_buttons = _state.QHBoxLayout()
    _state.mapping_route_control_text = _state._mapping_route_control_text_helper()
    _state.primary_route_buttons: dict[str, _state.QPushButton] = {}
    for _state.button_spec in _state._mapping_route_primary_button_specs_helper(_state.mapping_route_control_text):
        _state.route_button = _state.QPushButton(_state.button_spec.label)
        _state.route_button.setObjectName(_state.button_spec.object_name)
        _state.route_button.setToolTip(_state.button_spec.tooltip)
        _state.route_button.setStyleSheet(_state._mapping_route_button_style_helper(_state.button_spec.object_name, _state.button_spec.color))
        _state.route_button.setMinimumWidth(0)
        _state.mapping_buttons.addWidget(_state.route_button)
        _state.primary_route_buttons[_state.button_spec.key] = _state.route_button
    _state.assign_source_button = _state.primary_route_buttons['assign_source']
    _state.merge_source_button = _state.primary_route_buttons['merge_source']
    _state.remove_source_button = _state.primary_route_buttons['remove_source']
    _state.clear_target_button = _state.primary_route_buttons['clear_target']
    _state.mapping_buttons.addStretch(1)
    _state.advanced_routing_layout.addLayout(_state.mapping_buttons)
    _state.mapping_selection_buttons = _state.QHBoxLayout()
    _state.selection_route_buttons: dict[str, _state.QPushButton] = {}
    for _state.button_spec in _state._mapping_route_selection_button_specs_helper(_state.mapping_route_control_text):
        _state.selection_button = _state.QPushButton(_state.button_spec.label)
        _state.selection_button.setToolTip(_state.button_spec.tooltip)
        _state.selection_button.setMinimumWidth(0)
        _state.mapping_selection_buttons.addWidget(_state.selection_button)
        _state.selection_route_buttons[_state.button_spec.key] = _state.selection_button
    _state.clear_replacement_selection_button = _state.selection_route_buttons['clear_replacement']
    _state.clear_all_selection_button = _state.selection_route_buttons['clear_all']
    _state.mapping_selection_buttons.addStretch(1)
    _state.advanced_routing_layout.addLayout(_state.mapping_selection_buttons)
    _state.parts_outliner_mapping_callbacks = _state.create_alignment_parts_outliner_mapping_callbacks({**_state.context, **_state._factory_globals, **vars(_state), '_parts_outliner_selection_changed': lambda *args, **kwargs: _state._parts_outliner_selection_changed(*args, **kwargs), '_select_source_part_from_viewport': lambda *args, **kwargs: _state._select_source_part_from_viewport(*args, **kwargs), '_target_selection_changed': lambda *args, **kwargs: _state._target_selection_changed(*args, **kwargs)})
    _state._parts_outliner_source_label = _state.parts_outliner_mapping_callbacks._parts_outliner_source_label
    _state._parts_outliner_source_geometry = _state.parts_outliner_mapping_callbacks._parts_outliner_source_geometry
    _state._selected_source_indices_from_tree = _state.parts_outliner_mapping_callbacks._selected_source_indices_from_tree
    _state._set_transform_source_indices = _state.parts_outliner_mapping_callbacks._set_transform_source_indices
    _state._clear_transform_source_indices = _state.parts_outliner_mapping_callbacks._clear_transform_source_indices
    _state._set_source_parts_apply_pending = _state.parts_outliner_mapping_callbacks._set_source_parts_apply_pending
    _state._clear_source_parts_apply_pending = _state.parts_outliner_mapping_callbacks._clear_source_parts_apply_pending
    _state._set_source_parts_preview_rebuild_pending = _state.parts_outliner_mapping_callbacks._set_source_parts_preview_rebuild_pending
    _state._clear_source_parts_preview_rebuild_pending = _state.parts_outliner_mapping_callbacks._clear_source_parts_preview_rebuild_pending
    _state._add_source_tree_item = _state.parts_outliner_mapping_callbacks._add_source_tree_item
    _state._source_item_check_state_changed = _state.parts_outliner_mapping_callbacks._source_item_check_state_changed
    _state._outliner_source_index_from_item = _state.parts_outliner_mapping_callbacks._outliner_source_index_from_item
    _state._parts_outliner_set_source_selection = _state.parts_outliner_mapping_callbacks._parts_outliner_set_source_selection

def _source_parts_outliner_step_007(_state):
    _state._refresh_parts_outliner = _state.parts_outliner_mapping_callbacks._refresh_parts_outliner
    _state._show_parts_outliner_context_menu = _state.parts_outliner_mapping_callbacks._show_parts_outliner_context_menu
    _state._apply_parts_outliner_source_target = _state.parts_outliner_mapping_callbacks._apply_parts_outliner_source_target
    _state._parts_outliner_drop_target_index = _state.parts_outliner_mapping_callbacks._parts_outliner_drop_target_index
    _state._handle_parts_outliner_source_drop = _state.parts_outliner_mapping_callbacks._handle_parts_outliner_source_drop
    _state._apply_parts_outliner_source_role = _state.parts_outliner_mapping_callbacks._apply_parts_outliner_source_role
    _state._open_parts_outliner_target_dropdown = _state.parts_outliner_mapping_callbacks._open_parts_outliner_target_dropdown
    _state._open_parts_outliner_role_dropdown = _state.parts_outliner_mapping_callbacks._open_parts_outliner_role_dropdown
    _state._handle_parts_outliner_item_clicked = _state.parts_outliner_mapping_callbacks._handle_parts_outliner_item_clicked
    _state._append_mapping_target_row = _state.parts_outliner_mapping_callbacks._append_mapping_target_row
    _state._build_mapping_table_chunk = _state.parts_outliner_mapping_callbacks._build_mapping_table_chunk
    _state._apply_target_slot_filters = _state.parts_outliner_mapping_callbacks._apply_target_slot_filters
    _state._ensure_mapping_table_building = _state.parts_outliner_mapping_callbacks._ensure_mapping_table_building
    _state._clear_all_mapping_guesses = _state.parts_outliner_mapping_callbacks._clear_all_mapping_guesses
    _state._apply_best_mapping_guesses = _state.parts_outliner_mapping_callbacks._apply_best_mapping_guesses
    _state._preview_selected_target_slot = _state.parts_outliner_mapping_callbacks._preview_selected_target_slot
    _state._selected_source_index = _state.parts_outliner_mapping_callbacks._selected_source_index
    _state._selected_target_index = _state.parts_outliner_mapping_callbacks._selected_target_index
    _state._parse_mapping_edit = _state.parts_outliner_mapping_callbacks._parse_mapping_edit
    _state._texture_set_for_source_index = _state.parts_outliner_mapping_callbacks._texture_set_for_source_index
    _state._source_material_group_label = _state.parts_outliner_mapping_callbacks._source_material_group_label
    _state._mapped_target_vertex_count = _state.parts_outliner_mapping_callbacks._mapped_target_vertex_count
    _state._mapped_source_vertex_counts = _state.parts_outliner_mapping_callbacks._mapped_source_vertex_counts
    _state._mapping_preserve_split_group_count = _state.parts_outliner_mapping_callbacks._mapping_preserve_split_group_count
    _state._mapping_vertex_limit_issues = _state.parts_outliner_mapping_callbacks._mapping_vertex_limit_issues
    _state._routing_source_material_labels = _state.parts_outliner_mapping_callbacks._routing_source_material_labels
    _state._routing_effect_lines = _state.parts_outliner_mapping_callbacks._routing_effect_lines
    _state._set_advanced_mapping_visible = _state.parts_outliner_mapping_callbacks._set_advanced_mapping_visible
    _state._update_mapping_status = _state.parts_outliner_mapping_callbacks._update_mapping_status
    _state._sync_target_mapping_tree_item = _state.parts_outliner_mapping_callbacks._sync_target_mapping_tree_item
    _state._set_mapping_indices = _state.parts_outliner_mapping_callbacks._set_mapping_indices
    _state.alignment_source_tree_population_role_callbacks = _state.create_alignment_source_tree_role_callbacks({**_state.context, **_state._factory_globals, **vars(_state), '_apply_source_role_selection': lambda *args, **kwargs: _state._apply_source_role_selection(*args, **kwargs), '_refresh_parts_outliner': lambda *args, **kwargs: _state._refresh_parts_outliner(*args, **kwargs)})
    _state._finish_source_tree_population = _state.alignment_source_tree_population_role_callbacks._finish_source_tree_population
    _state.alignment_source_role_tree_population_callbacks = _state.create_alignment_source_role_tree_callbacks({**_state.context, **_state._factory_globals, **vars(_state), '_apply_source_part_preview_changes': lambda *args, **kwargs: _state._apply_source_part_preview_changes(*args, **kwargs), '_apply_parts_outliner_source_target': lambda *args, **kwargs: _state._apply_parts_outliner_source_target(*args, **kwargs), '_delete_selected_source_parts': lambda *args, **kwargs: _state._delete_selected_source_parts(*args, **kwargs), '_duplicate_selected_part': lambda *args, **kwargs: _state._duplicate_selected_part(*args, **kwargs), '_load_selected_part_controls': lambda *args, **kwargs: _state._load_selected_part_controls(*args, **kwargs), '_refresh_parts_outliner': lambda *args, **kwargs: _state._refresh_parts_outliner(*args, **kwargs), '_selected_source_index': lambda *args, **kwargs: _state._selected_source_index(*args, **kwargs), '_selected_source_indices_from_tree': lambda *args, **kwargs: _state._selected_source_indices_from_tree(*args, **kwargs), '_undo_geometry_change': lambda *args, **kwargs: _state._undo_geometry_change(*args, **kwargs)})
    _state._show_replacement_sources_context_menu = _state.alignment_source_role_tree_population_callbacks._show_replacement_sources_context_menu
    _state._show_replacement_sources_context_menu_for_viewport = _state.alignment_source_role_tree_population_callbacks._show_replacement_sources_context_menu_for_viewport
    setattr(_state.dialog, '_show_replacement_sources_context_menu_for_viewport', _state._show_replacement_sources_context_menu_for_viewport)
    _state._populate_source_tree_chunk = _state.alignment_source_role_tree_population_callbacks._populate_source_tree_chunk
    _state.source_tree.customContextMenuRequested.connect(_state._show_replacement_sources_context_menu)
    _state.source_tree_population_timer.timeout.connect(_state._populate_source_tree_chunk)
    _state._queue_alignment_post_open_task(_state.source_tree_population_timer.start)
    _state.source_tree.itemChanged.connect(_state._source_item_check_state_changed)
    _state.parts_outliner_tree.setContextMenuPolicy(_state.Qt.CustomContextMenu)
    _state.parts_outliner_tree.customContextMenuRequested.connect(_state._show_parts_outliner_context_menu)
    _state.parts_outliner_tree.itemClicked.connect(_state._handle_parts_outliner_item_clicked)
    _state.parts_outliner_tree.set_source_drop_handler(_state._handle_parts_outliner_source_drop)
    _state.mapping_table_build_timer.timeout.connect(_state._build_mapping_table_chunk)
    _state.low_confidence_filter_checkbox.toggled.connect(_state._apply_target_slot_filters)
    _state.empty_targets_filter_checkbox.toggled.connect(_state._apply_target_slot_filters)
    _state.clear_all_guesses_button.clicked.connect(_state._clear_all_mapping_guesses)
    _state.apply_best_guesses_button.clicked.connect(_state._apply_best_mapping_guesses)
    _state.show_advanced_mapping_checkbox.toggled.connect(_state._set_advanced_mapping_visible)
    _state._set_advanced_mapping_visible(_state.show_advanced_mapping_checkbox.isChecked())
    _state.control_tabs.currentChanged.connect(lambda index: _state._ensure_mapping_table_building() if _state.control_tabs.widget(index) is _state.parts_tab else None)
    _state._remap_source_index_collection = lambda values, index_map: _state._remap_source_index_collection_helper(tuple(values or ()), index_map)
    _state._remap_selected_source_index = lambda value, index_map: _state._remap_selected_source_index_helper(value, index_map)
    _state._remap_source_index_dict = lambda values, index_map, *, copy_values=False: _state._remap_source_index_dict_helper(values, index_map, copy_values=copy_values)
    _state.alignment_source_part_mutation_callbacks = None

def _source_parts_outliner_step_008(_state):

    def _delete_selected_source_parts(
        source_indices: Optional[Sequence[int]]=None,
        *,
        resident_state_only: bool=False,
        previous_source_count: int=0,
    ) -> None:
        if _state.alignment_source_part_mutation_callbacks is None:
            return
        _state.alignment_source_part_mutation_callbacks._delete_selected_source_parts(
            source_indices,
            resident_state_only=resident_state_only,
            previous_source_count=previous_source_count,
        )
    _state._delete_selected_source_parts = _delete_selected_source_parts

def _source_parts_outliner_step_009(_state):

    def _apply_source_part_preview_changes() -> None:
        if _state.alignment_source_part_mutation_callbacks is None:
            return
        _state.alignment_source_part_mutation_callbacks._apply_source_part_preview_changes()
    _state._apply_source_part_preview_changes = _apply_source_part_preview_changes

def _source_parts_outliner_step_010(_state):

    def _apply_source_material_grouped_routing() -> None:
        if _state.alignment_source_part_mutation_callbacks is None:
            return
        _state.alignment_source_part_mutation_callbacks._apply_source_material_grouped_routing()
    _state._apply_source_material_grouped_routing = _apply_source_material_grouped_routing

def _source_parts_outliner_step_011(_state):

    def _duplicate_selected_part(*, mirrored: bool=False) -> None:
        if _state.alignment_source_part_mutation_callbacks is None:
            return
        _state.alignment_source_part_mutation_callbacks._duplicate_selected_part(mirrored=mirrored)
    _state._duplicate_selected_part = _duplicate_selected_part

def _source_parts_outliner_step_012(_state):

    def _append_mesh_part_to_geometry() -> None:
        if _state.alignment_source_part_mutation_callbacks is None:
            return
        _state.alignment_source_part_mutation_callbacks._append_mesh_part_to_geometry()
    _state._append_mesh_part_to_geometry = _append_mesh_part_to_geometry

def _source_parts_outliner_step_013(_state):

    def _complete_external_swap_enabled() -> bool:
        checkbox = _state._late_context_value('complete_external_swap_checkbox')
        return bool(checkbox is not None and callable(getattr(checkbox, 'isChecked', None)) and checkbox.isChecked())
    _state._complete_external_swap_enabled = _complete_external_swap_enabled

def _source_parts_outliner_step_014(_state):
    _state.alignment_selection_route_callbacks = _state.create_alignment_selection_route_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
    _state._assign_selected_source_to_target = _state.alignment_selection_route_callbacks._assign_selected_source_to_target
    _state._merge_selected_source_into_target = _state.alignment_selection_route_callbacks._merge_selected_source_into_target
    _state._remove_selected_source_from_target = _state.alignment_selection_route_callbacks._remove_selected_source_from_target
    _state._clear_selected_target = _state.alignment_selection_route_callbacks._clear_selected_target
    _state.alignment_selection_clear_callbacks = _state.create_alignment_selection_clear_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
    _state._clear_tree_current_item = _state.alignment_selection_clear_callbacks._clear_tree_current_item
    _state._apply_part_selection_clear_scope_state = _state.alignment_selection_clear_callbacks._apply_part_selection_clear_scope_state
    _state._clear_original_selection = _state.alignment_selection_clear_callbacks._clear_original_selection
    _state._clear_replacement_selection = _state.alignment_selection_clear_callbacks._clear_replacement_selection
    _state._clear_target_selection = _state.alignment_selection_clear_callbacks._clear_target_selection

def _source_parts_outliner_step_015(_state):

    def _clear_replacement_selection() -> None:
        clear_state = _state._part_selection_clear_scope_state_helper('replacement')
        _state._apply_part_selection_clear_scope_state(clear_state)
        _state._clear_tree_current_item(_state.source_tree)
        _state._load_selected_part_controls()
        _state._sync_highlight_sets()
        _state._update_mapping_status()
        _state._update_selection_context()
        _state._queue_selection_preview_refresh()
    _state._clear_replacement_selection = _clear_replacement_selection

def _source_parts_outliner_step_016(_state):

    def _clear_target_selection() -> None:
        clear_state = _state._part_selection_clear_scope_state_helper('target')
        _state._apply_part_selection_clear_scope_state(clear_state)
        _state._clear_tree_current_item(_state.mapping_tree)
        _state._load_selected_part_controls()
        _state._sync_highlight_sets()
        _state._refresh_original_reference_preview()
        _state._update_mapping_status()
        _state._update_selection_context()
        _state._queue_selection_preview_refresh()
    _state._clear_target_selection = _clear_target_selection

def _source_parts_outliner_step_017(_state):

    def _clear_all_part_selections() -> None:
        if not _state._alignment_dialog_widgets_live():
            return
        for tree in (_state.source_tree, _state.original_tree, _state.mapping_tree, _state.parts_outliner_tree):
            if not _state._qt_object_is_valid(tree):
                return
            previous_blocked = tree.blockSignals(True)
            try:
                _state._clear_tree_current_item(tree)
            finally:
                tree.blockSignals(previous_blocked)
        _state._apply_part_selection_clear_scope_state(_state._part_selection_clear_scope_state_helper('all'))
        if _state._qt_object_is_valid(_state.added_texture_tree):
            _state._clear_tree_current_item(_state.added_texture_tree)
        if isinstance(_state.selected_added_part_texture_row, dict):
            _state.selected_added_part_texture_row['source_index'] = -1
        if _state._qt_object_is_valid(_state.texture_override_tree):
            _state._clear_tree_current_item(_state.texture_override_tree)
        if isinstance(_state.selected_texture_row, dict):
            _state.selected_texture_row['row'] = None
        if _state._qt_object_is_valid(_state.material_plan_tree):
            _state._clear_tree_current_item(_state.material_plan_tree)
        if _state._qt_object_is_valid(_state.material_routing_tree):
            _state._clear_tree_current_item(_state.material_routing_tree)
        if isinstance(_state.selected_texture_plan_source, dict):
            _state.selected_texture_plan_source['material_name'] = ''
            _state.selected_texture_plan_source['source_indices'] = ()
        if _state._qt_object_is_valid(_state.dds_detail_label) and _state._qt_object_is_valid(_state.dds_detail_panel):
            clear_state = _state._dds_detail_clear_state_helper(_state.material_plan_control_text)
            _state.dds_detail_label.setText(clear_state.detail_text)
            if callable(_state._apply_dds_detail_thumbnail_state):
                _state._apply_dds_detail_thumbnail_state(clear_state.thumbnail)
            _state.dds_detail_panel.setVisible(clear_state.panel_visible)
        _state._sync_highlight_sets()
        _state._refresh_original_reference_preview()
        _state._load_selected_part_controls()
        _state._update_mapping_status()
        _state._update_selection_context()
        _state._queue_selection_preview_refresh()
    _state._clear_all_part_selections = _clear_all_part_selections

STEPS = (
    _source_parts_outliner_step_001,
    _source_parts_outliner_step_002,
    _source_parts_outliner_step_003,
    _source_parts_outliner_step_004,
    _source_parts_outliner_step_005,
    _source_parts_outliner_step_006,
    _source_parts_outliner_step_007,
    _source_parts_outliner_step_008,
    _source_parts_outliner_step_009,
    _source_parts_outliner_step_010,
    _source_parts_outliner_step_011,
    _source_parts_outliner_step_012,
    _source_parts_outliner_step_013,
    _source_parts_outliner_step_014,
    _source_parts_outliner_step_015,
    _source_parts_outliner_step_016,
    _source_parts_outliner_step_017,
)
