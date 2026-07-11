from __future__ import annotations

def _texture_added_part_texture_step_001(_state):
    _state.Optional = _state.context.get('Optional')
    _state.Path = _state.context.get('Path')
    _state.QFileDialog = _state.context.get('QFileDialog')
    _state.QMessageBox = _state.context.get('QMessageBox')
    _state.QModelIndex = _state.context.get('QModelIndex')
    _state.QSizePolicy = _state.context.get('QSizePolicy')
    _state.QTreeWidgetItem = _state.context.get('QTreeWidgetItem')
    _state.Qt = _state.context.get('Qt')
    _state.SCENE_TEXTURE_SOURCE_EXTENSIONS = _state.context.get('SCENE_TEXTURE_SOURCE_EXTENSIONS')
    _state._add_dialog_supplemental_file = _state.context.get('_add_dialog_supplemental_file')
    _state._added_part_attached_targets_helper = _state.context.get('_added_part_attached_targets_helper')
    _state._added_part_detected_assignment_state_helper = _state.context.get('_added_part_detected_assignment_state_helper')
    _state._added_part_detected_missing_message_helper = _state.context.get('_added_part_detected_missing_message_helper')
    _state._added_part_selected_texture_assignment_state_helper = _state.context.get('_added_part_selected_texture_assignment_state_helper')
    _state._added_part_target_has_material_conflict_helper = _state.context.get('_added_part_target_has_material_conflict_helper')
    _state._added_part_texture_choose_dialog_state_helper = _state.context.get('_added_part_texture_choose_dialog_state_helper')
    _state._added_part_texture_editor_context_state_helper = _state.context.get('_added_part_texture_editor_context_state_helper')
    _state._added_part_texture_group_size_state_helper = _state.context.get('_added_part_texture_group_size_state_helper')
    _state._added_part_texture_highlight_state_helper = _state.context.get('_added_part_texture_highlight_state_helper')
    _state._added_part_texture_invalid_file_message_helper = _state.context.get('_added_part_texture_invalid_file_message_helper')
    _state._added_part_texture_item_helper = _state.context.get('_added_part_texture_item_helper')
    _state._added_part_texture_row_states_helper = _state.context.get('_added_part_texture_row_states_helper')
    _state._added_part_texture_status_helper = _state.context.get('_added_part_texture_status_helper')
    _state._added_part_texture_tree_visibility_state_helper = _state.context.get('_added_part_texture_tree_visibility_state_helper')
    _state._added_texture_editor_loading_set_helper = _state.context.get('_added_texture_editor_loading_set_helper')
    _state._alignment_mesh_edit_tab_active = _state.context.get('_alignment_mesh_edit_tab_active')
    _state._auto_fit_alignment_tree_columns = _state.context.get('_auto_fit_alignment_tree_columns')
    _state._clear_transform_source_indices = _state.context.get('_clear_transform_source_indices')
    _state._current_added_part_texture_source_index_helper = _state.context.get('_current_added_part_texture_source_index_helper')
    _state._current_dialog_mappings_for_preview = _state.context.get('_current_dialog_mappings_for_preview')
    _state._queue_selection_preview_refresh = _state.context.get('_queue_selection_preview_refresh')
    _state._refresh_original_reference_preview = _state.context.get('_refresh_original_reference_preview')
    _state._refresh_source_material_plan = _state.context.get('_refresh_source_material_plan')
    _state._register_allowed_texture_source_file_helper = _state.context.get('_register_allowed_texture_source_file_helper')
    _state._selection_view_update_kwargs_helper = _state.context.get('_selection_view_update_kwargs_helper')
    _state._set_added_part_texture_override = _state.context.get('_set_added_part_texture_override')
    _state._set_mesh_replacement_selection_view = _state.context.get('_set_mesh_replacement_selection_view')
    _state._source_display_name = _state.context.get('_source_display_name')
    _state._source_material_name_for_index_helper = _state.context.get('_source_material_name_for_index_helper')
    _state._source_slot_for_added_part_helper = _state.context.get('_source_slot_for_added_part_helper')
    _state._sync_highlight_sets = _state.context.get('_sync_highlight_sets')
    _state._target_display_name = _state.context.get('_target_display_name')
    _state._update_selection_context = _state.context.get('_update_selection_context')
    _state.added_texture_assign_button = _state.context.get('added_texture_assign_button')
    _state.added_texture_assign_detected_button = _state.context.get('added_texture_assign_detected_button')
    _state.added_texture_choose_base_button = _state.context.get('added_texture_choose_base_button')
    _state.added_texture_choose_height_button = _state.context.get('added_texture_choose_height_button')
    _state.added_texture_choose_mask_button = _state.context.get('added_texture_choose_mask_button')
    _state.added_texture_choose_normal_button = _state.context.get('added_texture_choose_normal_button')
    _state.added_texture_clear_button = _state.context.get('added_texture_clear_button')
    _state.added_texture_editor = _state.context.get('added_texture_editor')
    _state.added_texture_editor_loading = _state.context.get('added_texture_editor_loading')
    _state.added_texture_empty_label = _state.context.get('added_texture_empty_label')
    _state.added_texture_group = _state.context.get('added_texture_group')
    _state.added_texture_role_combo = _state.context.get('added_texture_role_combo')
    _state.added_texture_source_combo = _state.context.get('added_texture_source_combo')
    _state.added_texture_tree = _state.context.get('added_texture_tree')
    _state.appended_source_indices = _state.context.get('appended_source_indices')
    _state.assignment_state = _state.context.get('assignment_state')
    _state.choose_state = _state.context.get('choose_state')
    _state.current_item_source_index = _state.context.get('current_item_source_index')
    _state.dialog = _state.context.get('dialog')
    _state.editor_state = _state.context.get('editor_state')
    _state.has_rows = _state.context.get('has_rows')
    _state.highlight_state = _state.context.get('highlight_state')
    _state.index = _state.context.get('index')
    _state.item = _state.context.get('item')
    _state.item_to_select = _state.context.get('item_to_select')
    _state.label = _state.context.get('label')
    _state.message = _state.context.get('message')
    _state.obj_path = _state.context.get('obj_path')
    _state.path = _state.context.get('path')
    _state.preserve_source_index = _state.context.get('preserve_source_index')
    _state.preview_only_source_indices = _state.context.get('preview_only_source_indices')
    _state.previous_scroll = _state.context.get('previous_scroll')
    _state.registered = _state.context.get('registered')
    _state.replacement_mesh_for_mapping = _state.context.get('replacement_mesh_for_mapping')
    _state.resolved = _state.context.get('resolved')
    _state.row_state = _state.context.get('row_state')
    _state.row_states = _state.context.get('row_states')
    _state.seen_texture_file_keys = _state.context.get('seen_texture_file_keys')
    _state.selected_added_part_texture_row = _state.context.get('selected_added_part_texture_row')
    _state.selected_file = _state.context.get('selected_file')
    _state.selected_source_highlight_indices = _state.context.get('selected_source_highlight_indices')
    _state.selected_source_part = _state.context.get('selected_source_part')
    _state.selected_target_original_highlight_indices = _state.context.get('selected_target_original_highlight_indices')
    _state.selected_target_slot = _state.context.get('selected_target_slot')
    _state.selected_target_source_highlight_indices = _state.context.get('selected_target_source_highlight_indices')
    _state.size_state = _state.context.get('size_state')
    _state.slot_kind = _state.context.get('slot_kind')

def _texture_added_part_texture_step_002(_state):
    _state.slot_sources = _state.context.get('slot_sources')
    _state.source_combo_index = _state.context.get('source_combo_index')
    _state.source_index = _state.context.get('source_index')
    _state.source_material_texture_override_assignments = _state.context.get('source_material_texture_override_assignments')
    _state.source_path = _state.context.get('source_path')
    _state.self = _state.context.get('self')
    _state.targets = _state.context.get('targets')
    _state.texture_files_for_mapping = _state.context.get('texture_files_for_mapping')
    _state.texture_sets = _state.context.get('texture_sets')
    _state.texture_state = _state.context.get('texture_state')
    _state.title = _state.context.get('title')
    _state.visibility_state = _state.context.get('visibility_state')
    _state.widget = _state.context.get('widget')

def _texture_added_part_texture_step_003(_state):

    def _sync_added_part_texture_group_size(has_rows: bool) -> None:
        size_state = _state._added_part_texture_group_size_state_helper(has_rows, empty_label_height=_state.added_texture_empty_label.sizeHint().height(), font_height=_state.added_texture_group.fontMetrics().height())
        _state.added_texture_group.setMaximumHeight(size_state.max_height)
        _state.added_texture_group.setSizePolicy(_state.QSizePolicy.Expanding, _state.QSizePolicy.Fixed if size_state.fixed_height else _state.QSizePolicy.Maximum)
        _state.added_texture_group.updateGeometry()
    _state._sync_added_part_texture_group_size = _sync_added_part_texture_group_size

def _texture_added_part_texture_step_004(_state):

    def _highlight_added_part_texture_source(source_index: int) -> None:
        targets = _state._added_part_attached_targets_helper(source_index, _state._current_dialog_mappings_for_preview()) if source_index >= 0 else ()
        texture_state, _texture_color = _state._added_part_texture_status_helper(source_index, attached_targets=targets, has_material_conflict=_state._added_part_target_has_material_conflict_helper(source_index, _state._current_dialog_mappings_for_preview(), source_material_name_for_index=lambda index: _state._source_material_name_for_index_helper(index, _state.replacement_mesh_for_mapping, _state.texture_sets)), base_source_path=_state._source_slot_for_added_part_helper(source_index, 'base', _state.replacement_mesh_for_mapping, _state.texture_sets, _state.source_material_texture_override_assignments), preview_only_source_indices=_state.preview_only_source_indices) if source_index >= 0 else ('-', '#8b949e')
        highlight_state = _state._added_part_texture_highlight_state_helper(source_index=source_index, target_indices=targets, material_name=_state._source_material_name_for_index_helper(source_index, _state.replacement_mesh_for_mapping, _state.texture_sets) if source_index >= 0 else '', texture_state=texture_state)
        _state.selected_source_part['index'] = int(highlight_state['selected_source_index'])
        _state.selected_source_highlight_indices.clear()
        _state.selected_source_highlight_indices.update(tuple(highlight_state['source_highlight_indices']))
        _state._clear_transform_source_indices()
        _state.selected_target_source_highlight_indices.clear()
        _state.selected_target_source_highlight_indices.update(tuple(highlight_state['target_source_highlight_indices']))
        _state.selected_target_original_highlight_indices.clear()
        _state.selected_target_original_highlight_indices.update(tuple(highlight_state['target_original_highlight_indices']))
        _state.selected_target_slot['index'] = int(highlight_state['selected_target_index'])
        _state._sync_highlight_sets()
        _state._refresh_original_reference_preview()
        _state._set_mesh_replacement_selection_view(**_state._selection_view_update_kwargs_helper(highlight_state['selection_view']))
        _state._update_selection_context()
        _state._queue_selection_preview_refresh()
    _state._highlight_added_part_texture_source = _highlight_added_part_texture_source

def _texture_added_part_texture_step_005(_state):

    def _refresh_added_part_texture_editor(source_index: int=-1) -> None:
        _state._added_texture_editor_loading_set_helper(_state.added_texture_editor_loading, True)
        try:
            slot_kind = str(_state.added_texture_role_combo.currentData() or 'base')
            editor_state = _state._added_part_texture_editor_context_state_helper(source_index, slot_kind, replacement_mesh=_state.replacement_mesh_for_mapping, texture_sets_by_key=_state.texture_sets, override_assignments=_state.source_material_texture_override_assignments, texture_files_for_mapping=_state.texture_files_for_mapping)
            for widget in (_state.added_texture_role_combo, _state.added_texture_source_combo, _state.added_texture_assign_button, _state.added_texture_assign_detected_button, _state.added_texture_clear_button, _state.added_texture_choose_base_button, _state.added_texture_choose_normal_button, _state.added_texture_choose_mask_button, _state.added_texture_choose_height_button):
                widget.setEnabled(editor_state.has_source)
            _state.added_texture_source_combo.blockSignals(True)
            _state.added_texture_source_combo.clear()
            for label, source_path in editor_state.source_choices:
                _state.added_texture_source_combo.addItem(label, source_path)
            if editor_state.has_source:
                source_combo_index = _state.added_texture_source_combo.findData(editor_state.current_source)
                _state.added_texture_source_combo.setCurrentIndex(max(0, source_combo_index))
            _state.added_texture_source_combo.blockSignals(False)
        finally:
            _state._added_texture_editor_loading_set_helper(_state.added_texture_editor_loading, False)
    _state._refresh_added_part_texture_editor = _refresh_added_part_texture_editor

def _texture_added_part_texture_step_006(_state):

    def _refresh_added_part_texture_tree(preserve_source_index: Optional[int]=None) -> None:
        if preserve_source_index is None:
            preserve_source_index = int(_state.selected_added_part_texture_row.get('source_index', -1))
        previous_scroll = _state.added_texture_tree.verticalScrollBar().value()
        _state.added_texture_tree.blockSignals(True)
        try:
            _state.added_texture_tree.clear()
            item_to_select: _state.Optional[_state.QTreeWidgetItem] = None
            row_states = _state._added_part_texture_row_states_helper(tuple(_state.appended_source_indices), replacement_mesh=_state.replacement_mesh_for_mapping, mappings=_state._current_dialog_mappings_for_preview(), texture_sets_by_key=_state.texture_sets, override_assignments=_state.source_material_texture_override_assignments, preview_only_source_indices=_state.preview_only_source_indices, preserve_source_index=int(preserve_source_index), source_display_name=_state._source_display_name, target_display_name=_state._target_display_name)
            for row_state in row_states:
                item = _state._added_part_texture_item_helper(source_index=row_state.source_index, source_display_name=row_state.source_display_name, target_summary=row_state.target_summary, material_name=row_state.material_name, base_display=row_state.base_display, normal_display=row_state.normal_display, material_display=row_state.material_display, height_display=row_state.height_display, status_label=row_state.status_label, status_color=row_state.status_color)
                _state.added_texture_tree.addTopLevelItem(item)
                if row_state.selected:
                    item_to_select = item
            visibility_state = _state._added_part_texture_tree_visibility_state_helper(_state.added_texture_tree.topLevelItemCount())
            _state.added_texture_empty_label.setVisible(visibility_state.empty_label_visible)
            _state.added_texture_tree.setVisible(visibility_state.tree_visible)
            _state.added_texture_editor.setVisible(visibility_state.editor_visible)
            _state._sync_added_part_texture_group_size(visibility_state.has_rows)
            if item_to_select is not None:
                _state.added_texture_tree.setCurrentItem(item_to_select)
                _state.selected_added_part_texture_row['source_index'] = int(item_to_select.data(0, _state.Qt.UserRole))
            else:
                _state.selected_added_part_texture_row['source_index'] = -1
                _state.added_texture_tree.clearSelection()
                _state.added_texture_tree.setCurrentIndex(_state.QModelIndex())
            _state.added_texture_tree.verticalScrollBar().setValue(previous_scroll)
        finally:
            _state.added_texture_tree.blockSignals(False)
        _state._auto_fit_alignment_tree_columns(_state.added_texture_tree, (120, 120, 130, 130, 130, 130, 130, 100), (220, 220, 240, 250, 250, 250, 250, 150), expand_column=3)
        _state._refresh_added_part_texture_editor(int(_state.selected_added_part_texture_row.get('source_index', -1)))
    _state._refresh_added_part_texture_tree = _refresh_added_part_texture_tree

def _texture_added_part_texture_step_007(_state):

    def _current_added_part_texture_source_index() -> int:
        item = _state.added_texture_tree.currentItem()
        current_item_source_index: object = None
        if item is not None:
            try:
                current_item_source_index = item.data(0, _state.Qt.UserRole)
            except (TypeError, ValueError):
                current_item_source_index = None
        return _state._current_added_part_texture_source_index_helper(current_item_source_index, _state.selected_added_part_texture_row.get('source_index', -1))
    _state._current_added_part_texture_source_index = _current_added_part_texture_source_index

def _texture_added_part_texture_step_008(_state):

    def _register_added_part_texture_file(path: Path) -> Optional[Path]:
        resolved = _state._register_allowed_texture_source_file_helper(path, texture_files_for_mapping=_state.texture_files_for_mapping, seen_texture_file_keys=_state.seen_texture_file_keys, allowed_extensions=_state.SCENE_TEXTURE_SOURCE_EXTENSIONS)
        if resolved is None:
            return None
        _state._add_dialog_supplemental_file(resolved)
        return resolved
    _state._register_added_part_texture_file = _register_added_part_texture_file

def _texture_added_part_texture_step_009(_state):

    def _active_mesh_edit_added_part_texture_mutation_blocked() -> bool:
        if not (callable(_state._alignment_mesh_edit_tab_active) and _state._alignment_mesh_edit_tab_active()):
            return False
        message = 'Active Mesh Editor added-part texture overrides require native material execution; Python texture override mutation fallback is disabled.'
        set_status_message = getattr(_state.self, 'set_status_message', None)
        if callable(set_status_message):
            set_status_message(message, error=True)
        return True
    _state._active_mesh_edit_added_part_texture_mutation_blocked = _active_mesh_edit_added_part_texture_mutation_blocked

def _texture_added_part_texture_step_010(_state):

    def _assign_added_part_selected_texture() -> None:
        assignment_state = _state._added_part_selected_texture_assignment_state_helper(loading_active=bool(_state.added_texture_editor_loading.get('active')), source_index=_state._current_added_part_texture_source_index(), slot_kind=str(_state.added_texture_role_combo.currentData() or 'base'), source_path=str(_state.added_texture_source_combo.currentData() or ''))
        if not assignment_state['apply']:
            return
        if _state._active_mesh_edit_added_part_texture_mutation_blocked():
            return
        _state._set_added_part_texture_override(int(assignment_state['source_index']), str(assignment_state['slot_kind']), str(assignment_state['source_path']))
    _state._assign_added_part_selected_texture = _assign_added_part_selected_texture

def _texture_added_part_texture_step_011(_state):

    def _assign_detected_added_part_textures() -> None:
        source_index = _state._current_added_part_texture_source_index()
        slot_sources = {slot_kind: _state._source_slot_for_added_part_helper(source_index, slot_kind, _state.replacement_mesh_for_mapping, _state.texture_sets, _state.source_material_texture_override_assignments) for slot_kind in ('base', 'normal', 'material', 'height')}
        assignment_state = _state._added_part_detected_assignment_state_helper(source_index=source_index, slot_sources=slot_sources)
        if not assignment_state['apply']:
            return
        if _state._active_mesh_edit_added_part_texture_mutation_blocked():
            return
        for slot_kind, source_path in tuple(assignment_state['assignments']):
            _state._set_added_part_texture_override(source_index, slot_kind, source_path)
        if assignment_state['show_missing']:
            title, message = _state._added_part_detected_missing_message_helper()
            _state.QMessageBox.information(_state.dialog, title, message)
    _state._assign_detected_added_part_textures = _assign_detected_added_part_textures

def _texture_added_part_texture_step_012(_state):

    def _choose_added_part_texture(slot_kind: str) -> None:
        source_index = _state._current_added_part_texture_source_index()
        choose_state = _state._added_part_texture_choose_dialog_state_helper(source_index, slot_kind, obj_parent=_state.obj_path.parent)
        if not choose_state.should_open:
            return
        selected_file, _selected_filter = _state.QFileDialog.getOpenFileName(_state.dialog, choose_state.title, choose_state.directory, choose_state.file_filter)
        if not selected_file:
            return
        registered = _state._register_added_part_texture_file(_state.Path(selected_file))
        if registered is None:
            title, message = _state._added_part_texture_invalid_file_message_helper()
            _state.QMessageBox.warning(_state.dialog, title, message)
            return
        if _state._active_mesh_edit_added_part_texture_mutation_blocked():
            return
        _state._set_added_part_texture_override(source_index, slot_kind, str(registered))
        try:
            _state._refresh_source_material_plan()
        except NameError:
            pass
    _state._choose_added_part_texture = _choose_added_part_texture

def _texture_added_part_texture_step_013(_state):

    def _clear_added_part_texture_override() -> None:
        source_index = _state._current_added_part_texture_source_index()
        slot_kind = str(_state.added_texture_role_combo.currentData() or 'base')
        if _state._active_mesh_edit_added_part_texture_mutation_blocked():
            return
        _state._set_added_part_texture_override(source_index, slot_kind, '')
    _state._clear_added_part_texture_override = _clear_added_part_texture_override

def _texture_added_part_texture_step_014(_state):

    def _added_texture_tree_selection_changed(*_args: object) -> None:
        source_index = _state._current_added_part_texture_source_index()
        _state.selected_added_part_texture_row['source_index'] = source_index
        _state._refresh_added_part_texture_editor(source_index)
        _state._highlight_added_part_texture_source(source_index)
    _state._added_texture_tree_selection_changed = _added_texture_tree_selection_changed

def _texture_added_part_texture_step_015(_state):

    def _added_texture_role_changed(*_args: object) -> None:
        if _state.added_texture_editor_loading.get('active'):
            return
        _state._refresh_added_part_texture_editor(_state._current_added_part_texture_source_index())
    _state._added_texture_role_changed = _added_texture_role_changed

def _texture_added_part_texture_step_016(_state):
    _state._factory_result_values.update({'_sync_added_part_texture_group_size': _state._sync_added_part_texture_group_size, '_highlight_added_part_texture_source': _state._highlight_added_part_texture_source, '_refresh_added_part_texture_editor': _state._refresh_added_part_texture_editor, '_refresh_added_part_texture_tree': _state._refresh_added_part_texture_tree, '_current_added_part_texture_source_index': _state._current_added_part_texture_source_index, '_register_added_part_texture_file': _state._register_added_part_texture_file, '_assign_added_part_selected_texture': _state._assign_added_part_selected_texture, '_assign_detected_added_part_textures': _state._assign_detected_added_part_textures, '_choose_added_part_texture': _state._choose_added_part_texture, '_clear_added_part_texture_override': _state._clear_added_part_texture_override, '_added_texture_tree_selection_changed': _state._added_texture_tree_selection_changed, '_added_texture_role_changed': _state._added_texture_role_changed})

STEPS = (
    _texture_added_part_texture_step_001,
    _texture_added_part_texture_step_002,
    _texture_added_part_texture_step_003,
    _texture_added_part_texture_step_004,
    _texture_added_part_texture_step_005,
    _texture_added_part_texture_step_006,
    _texture_added_part_texture_step_007,
    _texture_added_part_texture_step_008,
    _texture_added_part_texture_step_009,
    _texture_added_part_texture_step_010,
    _texture_added_part_texture_step_011,
    _texture_added_part_texture_step_012,
    _texture_added_part_texture_step_013,
    _texture_added_part_texture_step_014,
    _texture_added_part_texture_step_015,
    _texture_added_part_texture_step_016,
)
