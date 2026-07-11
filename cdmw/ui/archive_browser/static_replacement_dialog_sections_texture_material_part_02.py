from __future__ import annotations

def _texture_material_step_012(_state):
    if _state._factory_advanced_material_branch:

        def _load_advanced_dds_override_rows(*, reason: str='manual') -> bool:
            if _state._advanced_dds_overrides_loaded_helper(_state.advanced_dds_overrides_state):
                return True
            if _state._advanced_dds_overrides_loading_helper(_state.advanced_dds_overrides_state):
                return False
            _state._advanced_dds_overrides_mark_loading_helper(_state.advanced_dds_overrides_state)
            try:
                _state._ensure_source_material_plan_loaded()
            except _state.NameError:
                pass
            _state.texture_busy_bar.setFormat(_state._advanced_dds_loading_busy_text_helper())
            _state.texture_busy_bar.setVisible(True)
            _state._alignment_startup_step(_state._advanced_dds_loading_start_text_helper(reason))
            started = _state.advanced_dds_controller.start(_state.AdvancedDdsRowScanRequest(request_id=0, suggested_mappings=_state.tuple(_state.suggested_mappings or ()), sidecar_bindings=_state.tuple(_state.sidecar_bindings_for_advanced or ()), texture_sets=_state.tuple(_state.texture_sets.items()), seen_texture_rows=frozenset(_state.seen_texture_rows), binding_matches_target=_state._binding_matches_target, best_source_for_slot=_state._best_source_for_slot, texture_is_shared=_state.is_shared_material_layer_texture), on_complete=_state._advanced_dds_rows_ready, on_error=_state._advanced_dds_rows_failed, on_idle=_state._advanced_dds_rows_idle)
            if not started:
                _state._advanced_dds_rows_idle()
            return False
        _state._load_advanced_dds_override_rows = _load_advanced_dds_override_rows

def _texture_material_step_013(_state):
    if _state._factory_advanced_material_branch:

        def _ensure_advanced_dds_overrides_loaded(reason: str='manual') -> bool:
            return _state._load_advanced_dds_override_rows(reason=reason)
        _state._ensure_advanced_dds_overrides_loaded = _ensure_advanced_dds_overrides_loaded

def _texture_material_step_014(_state):
    if _state._factory_advanced_material_branch:
        _state.texture_row_assigned = lambda state: _state._texture_row_is_assigned_helper(state, _state.texture_override_assignments)
        _state.texture_row_effective_source = lambda state: _state._texture_row_effective_source_helper(state, _state.texture_override_assignments)
        _state.sync_texture_row_assignment = lambda state: _state._sync_texture_row_assignment_state_helper(state, _state.texture_override_assignments)
        _state.texture_row_current_source_indices = lambda state: _state._texture_row_current_source_indices_helper(state, source_indices_for_target_name=_state._source_indices_for_target_name)
        _state.texture_row_source_summary = lambda state, limit=3: _state._texture_row_source_summary_helper(_state.texture_row_current_source_indices(state), source_display_name=_state._source_display_name, limit=limit)
        _state.texture_source_choices_for_row = lambda state: _state._texture_source_choices_for_row_helper(state, _state.texture_files_for_mapping, effective_source=_state.texture_row_effective_source, source_key=_state._texture_source_key)

def _texture_material_step_015(_state):
    if _state._factory_advanced_material_branch:

        def _virtual_contract_prune_removed_targets_enabled() -> bool:
            try:
                return _state.bool(_state.rebuild_sidecar_checkbox.isChecked() and _state.prune_unmapped_original_dds_checkbox.isChecked())
            except _state.NameError:
                return False
        _state._virtual_contract_prune_removed_targets_enabled = _virtual_contract_prune_removed_targets_enabled

def _texture_material_step_016(_state):
    if _state._factory_advanced_material_branch:

        def _virtual_contract_prune_unmapped_enabled() -> bool:
            try:
                return _state.bool(_state.rebuild_sidecar_checkbox.isChecked() and _state.prune_unmapped_original_dds_checkbox.isChecked())
            except _state.NameError:
                return False
        _state._virtual_contract_prune_unmapped_enabled = _virtual_contract_prune_unmapped_enabled

def _texture_material_step_017(_state):
    if _state._factory_advanced_material_branch:

        def _copied_source_texture_slot_overrides(parsed_mappings: Sequence[StaticSubmeshMapping], *, occupied_keys: Optional[set[Tuple[str, str]]]=None) -> List[StaticTextureSlotOverride]:
            return _state.list(_state._copied_source_texture_slot_overrides_helper(parsed_mappings, original_part_texture_intent_rows=_state._original_part_texture_intent_rows, copied_original_texture_intents_by_source=_state.copied_original_texture_intents_by_source, copied_original_texture_disabled_sources=_state.copied_original_texture_disabled_sources, source_display_name=_state._source_display_name, texture_slot_contract_key=_state._texture_slot_contract_key, occupied_keys=occupied_keys))
        _state._copied_source_texture_slot_overrides = _copied_source_texture_slot_overrides

def _texture_material_step_018(_state):
    if _state._factory_advanced_material_branch:

        def _copied_source_texture_preview_specs(parsed_mappings: Sequence[StaticSubmeshMapping]) -> List[tuple[str, str, str, str, Tuple[int, ...], str]]:
            return _state.list(_state._copied_source_texture_preview_specs_helper(parsed_mappings, _state._copied_source_texture_slot_overrides(parsed_mappings), source_preview_path=_state._source_preview_path))
        _state._copied_source_texture_preview_specs = _copied_source_texture_preview_specs

def _texture_material_step_019(_state):
    if _state._factory_advanced_material_branch:

        def _alignment_virtual_contract_rows(parsed_mappings: Sequence[StaticSubmeshMapping]) -> List[Dict[str, object]]:
            occupied_copied_keys: _state.set[_state.Tuple[_state.str, _state.str]] = _state.set()
            copied_overrides = _state._copied_source_texture_slot_overrides(parsed_mappings, occupied_keys=occupied_copied_keys)
            return _state._alignment_virtual_contract_rows_helper(parsed_mappings, texture_override_rows=_state.texture_override_rows, texture_override_assignments=_state.texture_override_assignments, copied_overrides=copied_overrides, texture_rows_by_target=_state.texture_rows_by_target, texture_row_assigned=_state.texture_row_assigned, texture_row_current_source_indices=_state.texture_row_current_source_indices, virtual_contract_prune_removed_targets_enabled=_state._virtual_contract_prune_removed_targets_enabled, virtual_contract_prune_unmapped_enabled=_state._virtual_contract_prune_unmapped_enabled, texture_row_effective_source=_state.texture_row_effective_source, texture_row_is_shared=_state._texture_row_is_shared, texture_role_label_for_slot=_state._texture_role_label_for_slot, texture_row_override_key=_state._texture_row_override_key, texture_override_row_sort_key=_state._texture_override_row_sort_key, texture_slot_contract_key=_state._texture_slot_contract_key)
        _state._alignment_virtual_contract_rows = _alignment_virtual_contract_rows

def _texture_material_step_020(_state):
    if _state._factory_advanced_material_branch:

        def _alignment_virtual_contract_preview_specs(parsed_mappings: Sequence[StaticSubmeshMapping], rows_override: Optional[Sequence[Mapping[str, object]]]=None) -> List[tuple[str, str, str, str, Tuple[int, ...], str]]:
            rows = rows_override if rows_override is not None else _state.alignment_virtual_texture_contract.get('rows') or ()
            return _state._alignment_virtual_contract_preview_specs_helper(rows, alignment_contract_preview_path=_state._alignment_contract_preview_path)
        _state._alignment_virtual_contract_preview_specs = _alignment_virtual_contract_preview_specs

def _texture_material_step_021(_state):
    if _state._factory_advanced_material_branch:

        def _refresh_alignment_virtual_sidecar_contract(parsed_mappings: Sequence[StaticSubmeshMapping]) -> Dict[str, object]:
            rows = _state._alignment_virtual_contract_rows(parsed_mappings)
            preview_specs = _state._alignment_virtual_contract_preview_specs(parsed_mappings, rows)
            contract_state = _state._alignment_virtual_sidecar_contract_state_helper(rows, preview_specs, sidecar_text_for_path=lambda sidecar_key: _state._virtual_contract_sidecar_text_for_path_helper(sidecar_key, sidecar_texts_by_normalized_path=_state.sidecar_texts_by_normalized_path, sidecar_texts_by_basename=_state.sidecar_texts_by_basename, sidecar_text_values=_state.sidecar_text_values, normalize_texture_reference=_state.normalize_texture_reference_for_sidecar_lookup), prune_removed_targets_enabled=_state._virtual_contract_prune_removed_targets_enabled(), prune_unmapped_enabled=_state._virtual_contract_prune_unmapped_enabled())
            _state.alignment_virtual_texture_contract.clear()
            _state.alignment_virtual_texture_contract.update(contract_state)
            return _state.alignment_virtual_texture_contract
        _state._refresh_alignment_virtual_sidecar_contract = _refresh_alignment_virtual_sidecar_contract

def _texture_material_step_022(_state):
    if _state._factory_advanced_material_branch:
        _state._alignment_startup_step(_state.alignment_startup_text['advanced_dds_classification'])
        for _state.row_index, _state.row_state in _state.enumerate(_state.texture_override_rows):
            if _state.row_index and _state.row_index % 120 == 0:
                _state._alignment_startup_step(_state._alignment_startup_advanced_dds_classification_progress_text_helper(_state.row_index))
        _state.suggested_counts = _state._advanced_dds_suggested_source_counts_helper(_state.texture_override_rows)
        for _state.row_index, _state.row_state in _state.enumerate(_state.texture_override_rows):
            if _state.row_index and _state.row_index % 120 == 0:
                _state._alignment_startup_step(_state._alignment_startup_advanced_dds_guidance_progress_text_helper(_state.row_index))
            _state._advanced_dds_apply_guidance_state_helper(_state.row_state, suggested_counts=_state.suggested_counts, texture_row_is_shared=_state._texture_row_is_shared, reset_assignment_fields=True)
        _state.texture_workflow = _state.QWidget()
        _state.texture_workflow_layout = _state.QVBoxLayout(_state.texture_workflow)
        _state.texture_workflow_layout.setContentsMargins(0, 0, 0, 0)
        _state.texture_workflow_layout.setSpacing(3)
        _state.texture_summary_label = _state.QLabel()
        _state.texture_summary_label.setWordWrap(True)
        _state.texture_summary_label.setTextFormat(_state.Qt.RichText)
        _state.texture_summary_label.setObjectName('HintLabel')
        _state.texture_workflow_layout.addWidget(_state.texture_summary_label)
        _state.texture_busy_bar = _state.QProgressBar()
        _state.texture_busy_bar.setRange(0, 0)
        _state.texture_busy_bar.setTextVisible(True)
        _state.texture_editor_control_text = _state._texture_editor_control_text_helper()
        _state.texture_busy_bar.setFormat(_state.str(_state.texture_editor_control_text['texture_assignments_busy']))
        _state.texture_busy_bar.setVisible(False)
        _state.texture_workflow_layout.addWidget(_state.texture_busy_bar)
        _state.texture_override_tree = _state.QTreeWidget()
        _state.texture_override_tree.setHeaderLabels(_state.list(_state.texture_editor_control_text['override_headers']))
        _state.texture_override_tree.setMinimumHeight(320)
        _state.texture_override_tree.setMinimumWidth(0)
        _state._configure_alignment_tree(_state.texture_override_tree, (120, 220, 96, 260, 180, 96, 240), max_height=0, stretch_columns=(1, 3, 6), persist_key='advanced_dds_overrides_v2')
        _state.selected_texture_editor = _state.QWidget()
        _state.selected_texture_editor_layout = _state.QGridLayout(_state.selected_texture_editor)
        _state.selected_texture_editor_layout.setContentsMargins(0, 0, 0, 0)
        _state.selected_texture_editor_layout.setHorizontalSpacing(4)
        _state.selected_texture_editor_layout.setVerticalSpacing(2)
        _state.selected_texture_editor_label = _state.QLabel(_state.str(_state.texture_editor_control_text['selected_label']))
        _state.selected_texture_editor_label.setObjectName('HintLabel')
        _state.selected_texture_editor_label.setMinimumWidth(0)
        _state.selected_texture_editor_label.setSizePolicy(_state.QSizePolicy.Expanding, _state.QSizePolicy.Fixed)
        _state.selected_role_combo = _state.QComboBox()
        _state.selected_role_combo.setMinimumWidth(118)
        _state.selected_role_combo.setToolTip(_state.str(_state.texture_editor_control_text['role_tooltip']))
        for _state.role_kind in _state.tuple(_state.texture_editor_control_text['role_options']):
            _state.selected_role_combo.addItem(_state._texture_role_label_for_slot(_state.role_kind), _state.role_kind)
        _state.selected_source_combo = _state.QComboBox()
        _state.selected_source_combo.setMinimumWidth(190)
        _state.selected_source_combo.setSizePolicy(_state.QSizePolicy.Expanding, _state.QSizePolicy.Fixed)
        _state.selected_source_combo.setToolTip(_state.str(_state.texture_editor_control_text['source_tooltip']))
        _state.selected_choose_source_button = _state.QPushButton(_state.str(_state.texture_editor_control_text['choose_button']))
        _state.selected_choose_source_button.setMinimumWidth(0)
        _state.selected_choose_source_button.setMaximumWidth(82)
        _state.selected_choose_source_button.setToolTip(_state.str(_state.texture_editor_control_text['choose_tooltip']))
        _state.selected_apply_suggestion_button = _state.QPushButton(_state.str(_state.texture_editor_control_text['apply_suggestion_button']))
        _state.selected_apply_suggestion_button.setMinimumWidth(0)
        _state.selected_apply_suggestion_button.setMaximumWidth(118)
        _state.selected_apply_suggestion_button.setEnabled(False)
        _state.selected_apply_suggestion_button.setToolTip(_state.str(_state.texture_editor_control_text['apply_suggestion_tooltip']))
        _state.selected_texture_editor_layout.addWidget(_state.selected_texture_editor_label, 0, 0, 1, 6)
        _state.selected_texture_editor_layout.addWidget(_state.QLabel(_state.str(_state.texture_editor_control_text['role_label'])), 1, 0)
        _state.selected_texture_editor_layout.addWidget(_state.selected_role_combo, 1, 1)
        _state.selected_texture_editor_layout.addWidget(_state.QLabel(_state.str(_state.texture_editor_control_text['source_label'])), 1, 2)
        _state.selected_texture_editor_layout.addWidget(_state.selected_source_combo, 1, 3, 1, 2)
        _state.selected_texture_editor_layout.addWidget(_state.selected_choose_source_button, 1, 5)
        _state.selected_texture_editor_layout.addWidget(_state.selected_apply_suggestion_button, 1, 6)
        _state.selected_texture_editor_layout.setColumnStretch(3, 1)
        _state.texture_workflow_layout.addWidget(_state.selected_texture_editor)
        _state.texture_detail_browser = _state.QTextBrowser()
        _state.texture_detail_browser.setReadOnly(True)
        _state.texture_detail_browser.setOpenExternalLinks(False)
        _state.texture_detail_browser.setMinimumHeight(220)
        _state.texture_detail_browser.setMinimumWidth(300)
        _state.texture_detail_browser.setSizePolicy(_state.QSizePolicy.Expanding, _state.QSizePolicy.Expanding)
        _state.texture_detail_browser.setTextInteractionFlags(_state.Qt.TextSelectableByMouse)
        _state.alignment_font_sizes = _state._alignment_dialog_font_sizes(_state.context)
        _state.texture_detail_browser.setStyleSheet(_state.texture_detail_browser.styleSheet() + f"QTextBrowser {{ font-size: {_state.alignment_font_sizes['data']}px; line-height: 1.08; }}")
        _state.texture_details_splitter = _state.QSplitter(_state.Qt.Horizontal)
        _state.texture_details_splitter.addWidget(_state.texture_override_tree)
        _state.texture_details_splitter.addWidget(_state.texture_detail_browser)
        _state.texture_details_splitter.setCollapsible(0, False)
        _state.texture_details_splitter.setCollapsible(1, False)
        _state.texture_details_splitter.setStretchFactor(0, 7)
        _state.texture_details_splitter.setStretchFactor(1, 3)
        _state.texture_details_splitter.setSizes([760, 320])
        _state.texture_workflow_layout.addWidget(_state.texture_details_splitter, 1)
        _state.selected_texture_row: _state.Dict[_state.str, _state.Optional[_state.Dict[_state.str, _state.Any]]] = _state._selected_texture_row_initial_state_helper()
        _state.selected_texture_editor_loading = _state._selected_texture_editor_loading_initial_state_helper()
        _state.selected_texture_source_committing = _state._selected_texture_source_committing_initial_state_helper()

def _texture_material_step_023(_state):
    if _state._factory_advanced_material_branch:

        def _refresh_texture_row_guidance() -> None:
            _state.texture_sets = _state.group_replacement_texture_sets(_state.texture_files_for_mapping, obj_mesh=_state.replacement_mesh_for_mapping)
            _state._apply_source_material_texture_overrides_to_ui_texture_sets(_state.texture_sets)
            for row_state in _state.texture_override_rows:
                suggested_source = '' if _state._texture_row_is_shared(row_state) else _state._best_source_for_slot(_state.str(row_state.get('target_name', '') or ''), _state.tuple(row_state.get('source_indices', ()) or ()), _state.str(row_state.get('slot_kind', '') or 'material'), _state.texture_sets, parameter_name=_state.str(row_state.get('parameter_name', '') or ''), target_texture_path=_state.str(row_state.get('target_path', '') or ''), target_shader_family=_state.str(row_state.get('shader_family', '') or ''))
                row_state['suggested_source'] = suggested_source
            suggested_counts = _state._advanced_dds_suggested_source_counts_helper(_state.texture_override_rows)
            for row_state in _state.texture_override_rows:
                _state._advanced_dds_apply_guidance_state_helper(row_state, suggested_counts=suggested_counts, texture_row_is_shared=_state._texture_row_is_shared, texture_role_label_for_slot=_state._texture_role_label_for_slot)
                _state.sync_texture_row_assignment(row_state)
        _state._refresh_texture_row_guidance = _refresh_texture_row_guidance

def _texture_material_step_024(_state):
    if _state._factory_advanced_material_branch:
        _state.alignment_texture_table_callbacks = _state.create_alignment_texture_table_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
        _state._sync_texture_selection_highlight = _state.alignment_texture_table_callbacks._sync_texture_selection_highlight
        _state._diagnostics_for_target_html = _state.alignment_texture_table_callbacks._diagnostics_for_target_html
        _state._current_texture_row = _state.alignment_texture_table_callbacks._current_texture_row
        _state._current_texture_target_name = _state.alignment_texture_table_callbacks._current_texture_target_name
        _state._sync_selected_texture_editor = _state.alignment_texture_table_callbacks._sync_selected_texture_editor
        _state._refresh_texture_details = _state.alignment_texture_table_callbacks._refresh_texture_details
        _state._set_texture_row_assignment = _state.alignment_texture_table_callbacks._set_texture_row_assignment
        _state._update_texture_summary_label = _state.alignment_texture_table_callbacks._update_texture_summary_label
        _state._apply_texture_row_to_item = _state.alignment_texture_table_callbacks._apply_texture_row_to_item
        _state._refresh_texture_row_in_place = _state.alignment_texture_table_callbacks._refresh_texture_row_in_place
        _state._refresh_texture_table = _state.alignment_texture_table_callbacks._refresh_texture_table
        _state._texture_table_selection_changed = _state.alignment_texture_table_callbacks._texture_table_selection_changed
        _state._selected_texture_role_changed = _state.alignment_texture_table_callbacks._selected_texture_role_changed
        _state._commit_texture_row_source = _state.alignment_texture_table_callbacks._commit_texture_row_source
        _state._selected_texture_source_changed = _state.alignment_texture_table_callbacks._selected_texture_source_changed
        _state._choose_selected_texture_source = _state.alignment_texture_table_callbacks._choose_selected_texture_source
        _state._clear_selected_texture_source = _state.alignment_texture_table_callbacks._clear_selected_texture_source
        _state._apply_selected_texture_suggestion = _state.alignment_texture_table_callbacks._apply_selected_texture_suggestion
        _state._texture_table_item_activated = _state.alignment_texture_table_callbacks._texture_table_item_activated
        _state._apply_replacement_texture_plan_to_overrides = _state.alignment_texture_table_callbacks._apply_replacement_texture_plan_to_overrides
        _state._apply_all_suggested_override_sources = _state.alignment_texture_table_callbacks._apply_all_suggested_override_sources
        _state._clear_target_texture_assignments = _state.alignment_texture_table_callbacks._clear_target_texture_assignments
        _state._selected_material_override_rows = _state.alignment_texture_table_callbacks._selected_material_override_rows
        _state._clear_selected_material_texture_assignments = _state.alignment_texture_table_callbacks._clear_selected_material_texture_assignments
        _state._choose_file_for_selected_material = _state.alignment_texture_table_callbacks._choose_file_for_selected_material

def _texture_material_step_025(_state):
    if _state._factory_advanced_material_branch:

        def _apply_texture_selected_part_filter() -> None:
            _state._refresh_texture_table()
        _state._apply_texture_selected_part_filter = _apply_texture_selected_part_filter

def _texture_material_step_026(_state):
    if _state._factory_advanced_material_branch:
        _state._confirm_texture_assignment_action = lambda title, planned_rows, *, reason: _state._confirm_texture_assignment_action_helper(_state.dialog, title, planned_rows, reason=reason, summary_html=_state._texture_assignment_summary_html)
        _state.alignment_texture_table_callbacks = _state.create_alignment_texture_table_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
        _state._apply_replacement_texture_plan_to_overrides = _state.alignment_texture_table_callbacks._apply_replacement_texture_plan_to_overrides
        _state._apply_all_suggested_override_sources = _state.alignment_texture_table_callbacks._apply_all_suggested_override_sources
        _state._clear_target_texture_assignments = _state.alignment_texture_table_callbacks._clear_target_texture_assignments
        _state._selected_material_override_rows = _state.alignment_texture_table_callbacks._selected_material_override_rows
        _state._clear_selected_material_texture_assignments = _state.alignment_texture_table_callbacks._clear_selected_material_texture_assignments
        _state._choose_file_for_selected_material = _state.alignment_texture_table_callbacks._choose_file_for_selected_material

def _texture_material_step_027(_state):
    if _state._factory_advanced_material_branch:

        def _apply_selected_source_material_textures() -> None:
            if not _state._ensure_advanced_dds_overrides_loaded(reason='use-selected'):
                return
            action_state = _state._selected_source_material_texture_action_state_helper(_state.selected_texture_plan_source, _state.texture_sets, _state.texture_override_rows, texture_set_for_source_index=_state._texture_set_for_source_index, source_indices_for_material_name=lambda material_name: _state._source_indices_for_material_name_helper(material_name, _state.replacement_mesh_for_mapping, texture_set_count=_state.len(_state.texture_sets), is_marker_source=_state._is_marker_source), texture_row_current_source_indices=_state.texture_row_current_source_indices, source_slot_for_texture_row=_state._source_slot_for_texture_row_helper)
            if action_state.message_key == 'missing_selection':
                _state.QMessageBox.information(_state.dialog, _state.str(_state.material_plan_control_text['use_selected_missing_title']), _state.str(_state.material_plan_control_text['use_selected_missing_message']))
                return
            planned_rows = _state.list(action_state.planned_rows)
            if not planned_rows:
                if action_state.message_key == 'base_enabled':
                    _state.rebuild_sidecar_checkbox.setChecked(True)
                    _state.inject_base_color_checkbox.setChecked(True)
                    _state._queue_texture_preview_refresh()
                    _state.QMessageBox.information(_state.dialog, _state.str(_state.material_plan_control_text['use_selected_missing_title']), _state.str(_state.material_plan_control_text['use_selected_base_enabled']))
                    return
                _state.QMessageBox.information(_state.dialog, _state.str(_state.material_plan_control_text['use_selected_missing_title']), _state.str(_state.material_plan_control_text['use_selected_no_rows']))
                return
            if not _state._confirm_texture_assignment_action(_state.str(_state.material_plan_control_text['use_selected']), planned_rows, reason=_state.str(_state.material_plan_control_text['use_selected_reason']).format(material_name=action_state.material_name)):
                return
            for row_state, source_path, _decision in planned_rows:
                _state._set_texture_row_assignment(row_state, source_path, True)
            if action_state.saw_base:
                _state.rebuild_sidecar_checkbox.setChecked(True)
                _state.inject_base_color_checkbox.setChecked(True)
            _state._refresh_texture_table(_state.selected_texture_row.get('row'))
            _state._queue_texture_preview_refresh()
        _state._apply_selected_source_material_textures = _apply_selected_source_material_textures

def _texture_material_step_028(_state):
    if _state._factory_advanced_material_branch:

        def _use_route_source_for_selected_material() -> None:
            _state._apply_selected_source_material_textures()
        _state._use_route_source_for_selected_material = _use_route_source_for_selected_material

def _texture_material_step_029(_state):
    if _state._factory_advanced_material_branch:

        def _apply_registered_texture_sources(selected_files: object) -> bool:
            added = _state._register_texture_source_files_helper(selected_files or (), texture_files_for_mapping=_state.texture_files_for_mapping, seen_texture_file_keys=_state.seen_texture_file_keys, allowed_extensions=_state.SCENE_TEXTURE_SOURCE_EXTENSIONS)
            add_state = _state._registered_texture_sources_action_state_helper(added, has_texture_sets=_state.bool(_state.texture_sets), rebuild_sidecar_checked=_state.bool(_state.rebuild_sidecar_checkbox.isChecked()))
            if add_state.message_key == 'none_added':
                return False
            _state._refresh_texture_row_guidance()
            _state._refresh_source_material_plan()
            if add_state.should_check_rebuild_sidecar:
                _state.rebuild_sidecar_checkbox.setChecked(True)
            _state._refresh_texture_table(_state.selected_texture_row.get('row'))
            _state._queue_texture_preview_refresh()
            return True
        _state._apply_registered_texture_sources = _apply_registered_texture_sources

def _texture_material_step_030(_state):
    if _state._factory_advanced_material_branch:

        def _add_missing_texture_sources() -> None:
            selected_files, _selected_filter = _state.QFileDialog.getOpenFileNames(_state.dialog, _state.str(_state.material_plan_control_text['add_replacement_textures_title']), _state.str(_state.obj_path.parent), _state.str(_state.material_plan_control_text['texture_file_filter']))
            _state._apply_registered_texture_sources(selected_files)
        _state._add_missing_texture_sources = _add_missing_texture_sources

def _texture_material_step_031(_state):
    if _state._factory_advanced_material_branch:
        _state.texture_folder_scan_controller = _state.StaticReplacementTextureFolderScanController(self, _state.dialog)
        setattr(_state.dialog, '_texture_folder_scan_controller', _state.texture_folder_scan_controller)
        _state.dialog.finished.connect(lambda _result=0: _state.texture_folder_scan_controller.request_shutdown())

def _texture_material_step_032(_state):
    if _state._factory_advanced_material_branch:

        def _texture_folder_scan_completed(result: object) -> None:
            files = _state.tuple(_state.getattr(result, 'files', ()) or ())
            _state._apply_registered_texture_sources(files)
            truncated = _state.bool(_state.getattr(result, 'truncated', False))
            errors = _state.tuple(_state.getattr(result, 'errors', ()) or ())
            if truncated:
                self.set_status_message(f'Texture folder scan added up to {_state.len(files):,} file(s) and stopped at the safety limit.', error=True)
            elif errors:
                self.set_status_message(f'Texture folder scan completed with {_state.len(errors):,} unreadable path(s).', error=True)
        _state._texture_folder_scan_completed = _texture_folder_scan_completed

def _texture_material_step_033(_state):
    if _state._factory_advanced_material_branch:

        def _texture_folder_scan_failed(message: str) -> None:
            self.set_status_message(f'Texture folder scan failed: {message}', error=True)
        _state._texture_folder_scan_failed = _texture_folder_scan_failed

def _texture_material_step_034(_state):
    if _state._factory_advanced_material_branch:

        def _texture_folder_scan_idle() -> None:
            try:
                _state.add_texture_folder_button.setEnabled(True)
            except RuntimeError:
                pass
        _state._texture_folder_scan_idle = _texture_folder_scan_idle

def _texture_material_step_035(_state):
    if _state._factory_advanced_material_branch:

        def _add_missing_texture_folder() -> None:
            selected_dir = _state.QFileDialog.getExistingDirectory(_state.dialog, _state.str(_state.material_plan_control_text['add_replacement_folder_title']), _state.str(_state.obj_path.parent))
            if not selected_dir:
                return
            started = _state.texture_folder_scan_controller.start(selected_dir, allowed_extensions=_state.tuple(_state.SCENE_TEXTURE_SOURCE_EXTENSIONS), on_complete=_state._texture_folder_scan_completed, on_error=_state._texture_folder_scan_failed, on_idle=_state._texture_folder_scan_idle)
            _state.add_texture_folder_button.setEnabled(not started)
        _state._add_missing_texture_folder = _add_missing_texture_folder

def _texture_material_step_036(_state):
    if _state._factory_advanced_material_branch:
        _state.texture_filter_refresh['func'] = _state._apply_texture_selected_part_filter
        _state.texture_override_tree.currentItemChanged.connect(_state._texture_table_selection_changed)
        _state.texture_override_tree.itemActivated.connect(_state._texture_table_item_activated)
        _state.selected_role_combo.currentIndexChanged.connect(_state._selected_texture_role_changed)
        _state.selected_source_combo.currentIndexChanged.connect(_state._selected_texture_source_changed)
        _state.selected_choose_source_button.clicked.connect(_state._choose_selected_texture_source)
        _state.selected_apply_suggestion_button.clicked.connect(_state._apply_selected_texture_suggestion)
        _state.apply_texture_plan_button.clicked.connect(_state._apply_replacement_texture_plan_to_overrides)
        _state.apply_selected_source_textures_button.clicked.connect(_state._apply_selected_source_material_textures)
        _state.material_use_route_source_button.clicked.connect(_state._use_route_source_for_selected_material)
        _state.material_keep_original_button.clicked.connect(_state._clear_selected_material_texture_assignments)
        _state.material_choose_file_button.clicked.connect(_state._choose_file_for_selected_material)
        _state.material_neutralize_button.clicked.connect(_state._clear_selected_material_texture_assignments)
        _state.material_do_not_emit_button.clicked.connect(_state._clear_selected_material_texture_assignments)
        _state.apply_all_suggested_overrides_button.clicked.connect(_state._apply_all_suggested_override_sources)
        _state.texture_filter_selected_checkbox.toggled.connect(_state._apply_texture_selected_part_filter)
        _state.texture_show_advanced_checkbox.toggled.connect(_state._apply_texture_selected_part_filter)
        _state.clear_target_textures_button.clicked.connect(_state._clear_target_texture_assignments)
        _state.keep_original_target_button.clicked.connect(_state._clear_target_texture_assignments)
        _state.do_not_emit_texture_button.clicked.connect(_state._clear_target_texture_assignments)
        _state.add_textures_button.clicked.connect(_state._add_missing_texture_sources)
        _state.add_texture_folder_button.clicked.connect(_state._add_missing_texture_folder)
        _state.advanced_dds_load_button.clicked.connect(lambda _checked=False: _state._ensure_advanced_dds_overrides_loaded(reason='button'))
        _state.texture_layout.addWidget(_state.texture_workflow, 1)
        _state._refresh_texture_table()
        _state.advanced_texture_section = _state.CollapsibleSection(_state.str(_state.advanced_dds_control_text['section_title']), expanded=False)
        _state.advanced_texture_section.toggled.connect(lambda expanded: _state._ensure_advanced_dds_overrides_loaded(reason='section') if expanded else None)
        _state.advanced_texture_section.body_layout.addWidget(_state.texture_group)
        _state.textures_layout.addWidget(_state.advanced_texture_section, 0)
        _state._queue_alignment_post_open_task(_state._queue_static_preview_refresh)
        _state.initial_static_preview_refreshed = True

def _texture_material_step_037(_state):
    if not _state._factory_advanced_material_branch:
        if False and _state.sidecar_bindings:
            _state.advanced_dds_control_text = _state._advanced_dds_control_text_helper()
            _state.texture_group = _state.QGroupBox(_state.str(_state.advanced_dds_control_text['legacy_group_title']))
            _state.texture_group.setSizePolicy(_state.QSizePolicy.Expanding, _state.QSizePolicy.Preferred)
            _state.texture_layout = _state.QVBoxLayout(_state.texture_group)
            _state.texture_layout.setAlignment(_state.Qt.AlignTop)
            _state.texture_hint = _state.QLabel(_state.str(_state.advanced_dds_control_text['legacy_hint']))
            _state.texture_hint.setWordWrap(True)
            _state.texture_hint.setObjectName('HintLabel')
            _state.texture_layout.addWidget(_state.texture_hint)
            if not _state.texture_files_for_mapping:
                _state.no_sources_hint = _state.QLabel(_state.str(_state.advanced_dds_control_text['legacy_no_sources_hint']))
                _state.no_sources_hint.setWordWrap(True)
                _state.no_sources_hint.setObjectName('HintLabel')
                _state.texture_layout.addWidget(_state.no_sources_hint)
            _state.texture_filter_selected_checkbox = _state.QCheckBox(_state.str(_state.advanced_dds_control_text['legacy_filter_selected']))
            _state.texture_filter_selected_checkbox.setToolTip(_state.str(_state.advanced_dds_control_text['legacy_filter_selected_tooltip']))
            _state.texture_layout.addWidget(_state.texture_filter_selected_checkbox)
            _state.texture_sets = _state.group_replacement_texture_sets(_state.texture_files_for_mapping, obj_mesh=_state.replacement_mesh_for_mapping)
            _state._apply_source_material_texture_overrides_to_ui_texture_sets(_state.texture_sets)
            _state.texture_tree = _state.QTreeWidget()
            _state.texture_tree.setHeaderLabels(_state.list(_state.advanced_dds_control_text['legacy_headers']))
            _state.texture_tree.setMinimumHeight(150)
            _state._configure_texture_mapping_tree(_state.texture_tree, persist_key='legacy_texture_slot_mapping')
            _state.active_mappings = _state.list(_state.suggested_mappings or [])
            _state.seen_texture_rows: _state.set[_state.tuple[_state.str, _state.str, _state.str, _state.str]] = _state.set()
            _state.row_index = 0
            for _state.mapping in _state.active_mappings:
                for _state.binding in _state.sidecar_bindings:
                    _state.target_path = _state.str(_state.getattr(_state.binding, 'texture_path', '') or '').replace('\\', '/').strip()
                    if not _state.target_path.lower().endswith('.dds'):
                        continue
                    if not _state._binding_matches_target(_state.binding, _state.mapping.target_submesh_name):
                        continue
                    _state.parameter_name = _state.str(_state.getattr(_state.binding, 'parameter_name', '') or '').strip()
                    _state.texture_classification = _state.classify_texture_binding(_state.parameter_name, _state.target_path)
                    _state.slot_kind = _state.texture_classification.slot_kind
                    _state.visualized = _state.texture_classification.visualized
                    _state.row_key = (_state.mapping.target_submesh_name.lower(), _state.parameter_name.lower(), _state.target_path.lower(), _state.slot_kind)
                    if _state.row_key in _state.seen_texture_rows:
                        continue
                    _state.seen_texture_rows.add(_state.row_key)
                    _state.binding_part_name = _state.str(_state.getattr(_state.binding, 'part_name', '') or _state.getattr(_state.binding, 'submesh_name', '') or '').strip()
                    _state.binding_shader_family = _state.str(_state.getattr(_state.binding, 'shader_family', '') or '').strip()
                    _state.binding_sidecar_kind = _state.str(_state.getattr(_state.binding, 'sidecar_kind', '') or '').strip()
                    _state.binding_linked_mesh = _state.str(_state.getattr(_state.binding, 'linked_mesh_path', '') or '').strip()
                    _state.part_display = _state.binding_part_name or _state.mapping.target_submesh_name
                    if _state.binding_shader_family:
                        _state.part_display = f'{_state.part_display} / {_state.binding_shader_family}'
                    _state.checkbox = _state.QCheckBox()
                    _state.combo = _state.QComboBox()
                    _state.combo.setMinimumContentsLength(10)
                    _state.combo.setSizeAdjustPolicy(_state.QComboBox.AdjustToMinimumContentsLengthWithIcon)
                    _state.combo.setSizePolicy(_state.QSizePolicy.Expanding, _state.QSizePolicy.Fixed)
                    _state.combo.addItem('Auto / keep original', '')
                    for _state.texture_file in _state.texture_files_for_mapping:
                        _state.combo.addItem(_state.texture_file.name, _state.str(_state.texture_file))
                    _state.suggested_source = _state._best_source_for_slot(_state.mapping.target_submesh_name, _state.mapping.source_submesh_indices, _state.slot_kind, _state.texture_sets, parameter_name=_state.parameter_name, target_texture_path=_state.target_path, target_shader_family=_state.binding_shader_family)
                    _state.is_shared_texture_layer = _state.is_shared_material_layer_texture(_state.target_path)
                    _state.can_auto_assign_texture = _state.bool(_state.suggested_source and _state.visualized and (not _state.is_shared_texture_layer) and (_state.slot_kind in {'base', 'normal', 'material', 'material_mask', 'detail_mask', 'height'}))
                    if _state.can_auto_assign_texture:
                        _state.source_index = _state.combo.findData(_state.suggested_source)
                        if _state.source_index >= 0:
                            _state.combo.setCurrentIndex(_state.source_index)
                            _state.checkbox.setChecked(True)
                    _state.parameter_display = _state.parameter_name or _state.texture_classification.slot_label or _state.slot_kind
                    _state.source_indices = _state.tuple(_state.mapping.source_submesh_indices)
                    _state.texture_item = _state._texture_assignment_slot_item_helper(part_display=_state.part_display, parameter_display=_state.parameter_display, target_path=_state.target_path, source_indices=_state.source_indices, target_name=_state.str(_state.mapping.target_submesh_name or ''), binding_part_name=_state.binding_part_name, binding_shader_family=_state.binding_shader_family, binding_sidecar_kind=_state.binding_sidecar_kind, binding_linked_mesh=_state.binding_linked_mesh, slot_label=_state.str(_state.texture_classification.slot_label or ''), slot_kind=_state.slot_kind, semantic_type=_state.str(_state.texture_classification.semantic_type or ''), semantic_subtype=_state.str(_state.texture_classification.semantic_subtype or ''), reason=_state.str(_state.texture_classification.reason or ''))
                    _state.texture_items_by_source.append((_state.texture_item, _state.source_indices))
                    _state.texture_tree.addTopLevelItem(_state.texture_item)

                    def _refresh_texture_status(*, item: QTreeWidgetItem=_state.texture_item, checkbox: QCheckBox=_state.checkbox, combo: QComboBox=_state.combo, visualized: bool=_state.visualized, is_shared_texture_layer: bool=_state.is_shared_texture_layer) -> None:
                        has_source = _state.bool(_state.str(combo.currentData() or '').strip())
                        if is_shared_texture_layer and (not checkbox.isChecked()):
                            state_text = 'Optional shared layer'
                            state_color = '#facc15'
                        elif not visualized:
                            state_text = 'Not visualized'
                            state_color = '#facc15'
                        elif checkbox.isChecked() and has_source:
                            state_text = 'Assigned'
                            state_color = '#86efac'
                        elif checkbox.isChecked():
                            state_text = 'Auto'
                            state_color = '#93c5fd'
                        elif has_source:
                            state_text = 'Preview-only'
                            state_color = '#93c5fd'
                        else:
                            state_text = 'Original'
                            state_color = '#94a3b8'
                        item.setText(4, state_text)
                        item.setForeground(4, _state.QBrush(_state.QColor(state_color)))

                    def _texture_combo_changed(_index: int, *, checkbox: QCheckBox=_state.checkbox, combo: QComboBox=_state.combo, refresh_status: Callable[[], None]=_state._refresh_texture_status) -> None:
                        if _state.str(combo.currentData() or '').strip():
                            checkbox.setChecked(True)
                        refresh_status()
                        _state._queue_texture_preview_refresh()
                    _state.combo.currentIndexChanged.connect(_state._texture_combo_changed)
                    _state.checkbox.toggled.connect(lambda _checked, refresh_status=_refresh_texture_status: (refresh_status(), _state._queue_texture_preview_refresh()))
                    _state._refresh_texture_status()
                    _state.texture_tree.setItemWidget(_state.texture_item, 0, _state.checkbox)
                    _state.texture_tree.setItemWidget(_state.texture_item, 5, _state.combo)
                    _state.texture_override_rows.append((_state.checkbox, _state.combo, _state.target_path, _state.slot_kind, _state.mapping.target_submesh_name, _state.tuple(_state.mapping.source_submesh_indices), _state.bool(_state.visualized)))
                    _state.row_index += 1
            if _state.row_index == 0:
                _state.texture_layout.addWidget(_state.QLabel(_state.str(_state.texture_editor_control_text['no_editable_slots'])))
            else:

                def _apply_legacy_texture_selected_part_filter() -> None:
                    selected_index = _state.int(_state.selected_source_part.get('index', -1))
                    enabled = _state.bool(_state.texture_filter_selected_checkbox.isChecked()) if _state.texture_filter_selected_checkbox is not None else False
                    for item, source_indices in _state.texture_items_by_source:
                        target_name = _state.str(item.data(0, _state.Qt.UserRole + 1) or '')
                        current_source_indices = _state._source_indices_for_target_name(target_name) or _state.tuple(source_indices)
                        item.setData(0, _state.Qt.UserRole, _state.tuple(current_source_indices))
                        item.setHidden(_state.bool(enabled and selected_index >= 0 and (selected_index not in current_source_indices)))
                _state.texture_filter_refresh['func'] = _state._apply_legacy_texture_selected_part_filter
                _state.texture_filter_selected_checkbox.toggled.connect(_state._apply_legacy_texture_selected_part_filter)
                _state._apply_legacy_texture_selected_part_filter()
                _state.texture_layout.addWidget(_state.texture_tree, 0)
                _state.QTimer.singleShot(0, lambda tree=texture_tree: _state._fit_alignment_tree_height_to_rows(tree, minimum=150, screen_margin=300))

            def _set_advanced_dds_overrides_expanded(checked: bool) -> None:
                for child_widget in _state.texture_group.findChildren(_state.QWidget):
                    child_widget.setVisible(_state.bool(checked))
                _state.texture_group.setMaximumHeight(16777215 if checked else _state.max(28, _state.texture_group.fontMetrics().height() + 12))
            _state.texture_group.toggled.connect(_state._set_advanced_dds_overrides_expanded)
            _state._set_advanced_dds_overrides_expanded(False)
            _state.textures_layout.addWidget(_state.texture_group, 0)
            _state._queue_alignment_post_open_task(_state._queue_static_preview_refresh)
            _state.initial_static_preview_refreshed = True
        elif not _state.texture_assignment_rows_skipped:
            _state.texture_editor_control_text = _state._texture_editor_control_text_helper()
            _state.textures_layout.addWidget(_state.QLabel(_state.str(_state.texture_editor_control_text['no_sidecar_slots'])), 0)

def _texture_material_step_038(_state):
    if not _state.initial_static_preview_refreshed:
        _state._queue_alignment_post_open_task(_state._queue_static_preview_refresh)

def _texture_material_step_039(_state):
    _state._factory_result_values.update({'_copied_source_texture_slot_overrides': vars(_state).get('_copied_source_texture_slot_overrides'), '_load_original_reference_texture_preview': vars(_state).get('_load_original_reference_texture_preview'), '_save_texture_transform_controls': vars(_state).get('_save_texture_transform_controls'), 'binding': vars(_state).get('binding'), 'rows': vars(_state).get('rows'), 'source_index': vars(_state).get('source_index'), 'target_name': vars(_state).get('target_name'), 'texture_transform_offset_u_spin': vars(_state).get('texture_transform_offset_u_spin'), 'texture_transform_offset_v_spin': vars(_state).get('texture_transform_offset_v_spin'), 'texture_transform_scale_u_spin': vars(_state).get('texture_transform_scale_u_spin'), 'texture_transform_scale_v_spin': vars(_state).get('texture_transform_scale_v_spin')})

STEPS = (
    _texture_material_step_012,
    _texture_material_step_013,
    _texture_material_step_014,
    _texture_material_step_015,
    _texture_material_step_016,
    _texture_material_step_017,
    _texture_material_step_018,
    _texture_material_step_019,
    _texture_material_step_020,
    _texture_material_step_021,
    _texture_material_step_022,
    _texture_material_step_023,
    _texture_material_step_024,
    _texture_material_step_025,
    _texture_material_step_026,
    _texture_material_step_027,
    _texture_material_step_028,
    _texture_material_step_029,
    _texture_material_step_030,
    _texture_material_step_031,
    _texture_material_step_032,
    _texture_material_step_033,
    _texture_material_step_034,
    _texture_material_step_035,
    _texture_material_step_036,
    _texture_material_step_037,
    _texture_material_step_038,
    _texture_material_step_039,
)
