from __future__ import annotations

from types import SimpleNamespace

def _source_part_assignment_step_001(_state):
    _state.Optional = _state.context.get('Optional')
    _state.QAbstractItemView = _state.context.get('QAbstractItemView')
    _state.QComboBox = _state.context.get('QComboBox')
    _state.QDialog = _state.context.get('QDialog')
    _state.QEvent = _state.context.get('QEvent')
    _state.QFrame = _state.context.get('QFrame')
    _state.QHBoxLayout = _state.context.get('QHBoxLayout')
    _state.QLabel = _state.context.get('QLabel')
    _state.QMessageBox = _state.context.get('QMessageBox')
    _state.QObject = _state.context.get('QObject')
    _state.QPushButton = _state.context.get('QPushButton')
    _state.QTreeWidget = _state.context.get('QTreeWidget')
    _state.QTreeWidgetItem = _state.context.get('QTreeWidgetItem')
    _state.QVBoxLayout = _state.context.get('QVBoxLayout')
    _state.Qt = _state.context.get('Qt')
    _state.Sequence = _state.context.get('Sequence')
    _state._add_source_tree_item = _state.context.get('_add_source_tree_item')
    _state._assignment_source_item_helper = _state.context.get('_assignment_source_item_helper')
    _state._auto_fit_alignment_tree_columns = _state.context.get('_auto_fit_alignment_tree_columns')
    _state._fit_alignment_tree_height_to_rows = _state.context.get('_fit_alignment_tree_height_to_rows')
    _state._is_marker_source = _state.context.get('_is_marker_source')
    _state._parse_mapping_edit = _state.context.get('_parse_mapping_edit')
    _state._queue_selection_preview_refresh = _state.context.get('_queue_selection_preview_refresh')
    _state._refresh_original_reference_preview = _state.context.get('_refresh_original_reference_preview')
    _state._selected_target_index = _state.context.get('_selected_target_index')
    _state._set_mapping_indices = _state.context.get('_set_mapping_indices')
    _state._set_transform_source_indices = _state.context.get('_set_transform_source_indices')
    _state._source_assigned_target_indices_helper = _state.context.get('_source_assigned_target_indices_helper')
    _state._source_display_name = _state.context.get('_source_display_name')
    _state._source_part_assignment_button_state_helper = _state.context.get('_source_part_assignment_button_state_helper')
    _state._source_part_assignment_dialog_text_helper = _state.context.get('_source_part_assignment_dialog_text_helper')
    _state._source_part_assignment_highlight_state_helper = _state.context.get('_source_part_assignment_highlight_state_helper')
    _state._source_part_assignment_import_state_helper = _state.context.get('_source_part_assignment_import_state_helper')
    _state._source_part_assignment_primary_target_helper = _state.context.get('_source_part_assignment_primary_target_helper')
    _state._source_part_assignment_route_state_helper = _state.context.get('_source_part_assignment_route_state_helper')
    _state._source_part_assignment_row_specs_helper = _state.context.get('_source_part_assignment_row_specs_helper')
    _state._source_part_assignment_summary_state_helper = _state.context.get('_source_part_assignment_summary_state_helper')
    _state._source_part_assignment_target_for_source_helper = _state.context.get('_source_part_assignment_target_for_source_helper')
    _state._source_part_assignment_target_index_helper = _state.context.get('_source_part_assignment_target_index_helper')
    _state._source_part_assignment_tree_headers_helper = _state.context.get('_source_part_assignment_tree_headers_helper')
    _state._source_part_high_density_import_action_helper = _state.context.get('_source_part_high_density_import_action_helper')
    _state._source_part_high_density_prompt_state_helper = _state.context.get('_source_part_high_density_prompt_state_helper')
    _state._source_part_high_density_reduction_limits_helper = _state.context.get('_source_part_high_density_reduction_limits_helper')
    _state._source_part_multipart_import_action_helper = _state.context.get('_source_part_multipart_import_action_helper')
    _state._source_part_multipart_prompt_state_helper = _state.context.get('_source_part_multipart_prompt_state_helper')
    _state._source_part_reduction_result_message_helper = _state.context.get('_source_part_reduction_result_message_helper')
    _state._source_part_valid_indices_helper = _state.context.get('_source_part_valid_indices_helper')
    _state._source_tree_population_mark_complete_helper = _state.context.get('_source_tree_population_mark_complete_helper')
    _state._source_tree_population_ready_text_helper = _state.context.get('_source_tree_population_ready_text_helper')
    _state._source_tree_population_set_next_index_helper = _state.context.get('_source_tree_population_set_next_index_helper')
    _state._sync_highlight_sets = _state.context.get('_sync_highlight_sets')
    _state._target_display_name = _state.context.get('_target_display_name')
    _state._texture_assignment_action_initial_state_helper = _state.context.get('_texture_assignment_action_initial_state_helper')
    _state._texture_set_for_source_index = _state.context.get('_texture_set_for_source_index')
    _state.control_tabs = _state.context.get('control_tabs')
    _state.dialog = _state.context.get('dialog')
    _state.discovered_texture_files = _state.context.get('discovered_texture_files')
    _state.event = _state.context.get('event')
    _state.flatten_scene_import_result_parts = _state.context.get('flatten_scene_import_result_parts')
    _state.format_scene_import_file_size_summary = _state.context.get('format_scene_import_file_size_summary')
    _state.group_scene_import_result_parts_by_material = _state.context.get('group_scene_import_result_parts_by_material')
    _state.independent_output_source_indices = _state.context.get('independent_output_source_indices')
    _state.mapping_edits = _state.context.get('mapping_edits')
    _state.mapping_edits_by_target = _state.context.get('mapping_edits_by_target')
    _state.original_mesh_for_mapping = _state.context.get('original_mesh_for_mapping')
    _state.part_source_combo = _state.context.get('part_source_combo')
    _state.placement_note = _state.context.get('placement_note')
    _state.preview_only_source_indices = _state.context.get('preview_only_source_indices')
    _state.reduce_scene_import_result_quality = _state.context.get('reduce_scene_import_result_quality')
    _state.replacement_mesh_for_mapping = _state.context.get('replacement_mesh_for_mapping')
    _state.scene_result = _state.context.get('scene_result')
    _state.selected_indices = _state.context.get('selected_indices')
    _state.selected_original_part = _state.context.get('selected_original_part')
    _state.selected_source_highlight_indices = _state.context.get('selected_source_highlight_indices')
    _state.selected_source_part = _state.context.get('selected_source_part')
    _state.selected_target_original_highlight_indices = _state.context.get('selected_target_original_highlight_indices')
    _state.selected_target_slot = _state.context.get('selected_target_slot')
    _state.selected_target_source_highlight_indices = _state.context.get('selected_target_source_highlight_indices')
    _state.self = _state.context.get('self')
    _state.source_indices = _state.context.get('source_indices')
    _state.source_items_by_index = _state.context.get('source_items_by_index')
    _state.source_part_inspector_control_text = _state.context.get('source_part_inspector_control_text')
    _state.source_path = _state.context.get('source_path')
    _state.source_tree = _state.context.get('source_tree')
    _state.source_tree_layout_state = _state.context.get('source_tree_layout_state')
    _state.source_tree_population_state = _state.context.get('source_tree_population_state')
    _state.source_tree_population_timer = _state.context.get('source_tree_population_timer')
    _state.source_tree_progress_label = _state.context.get('source_tree_progress_label')
    _state.static_replacement_vertex_limit = _state.context.get('static_replacement_vertex_limit')
    _state.texture_sets = _state.context.get('texture_sets')
    _state.textures_tab = _state.context.get('textures_tab')

def _prepare_assignment_prompt(_state, source_path, source_indices, placement_note, discovered_texture_files):
    if _state.original_mesh_for_mapping is None or _state.replacement_mesh_for_mapping is None:
        return None, 'keep'
    matched_texture_indices = tuple(int(index) for index in source_indices if _state._texture_set_for_source_index(int(index), _state.texture_sets) is not None)
    import_state = _state._source_part_assignment_import_state_helper(source_indices=source_indices, replacement_sources=tuple(_state.replacement_mesh_for_mapping.submeshes), source_name=source_path.name, placement_note=placement_note, discovered_texture_count=len(tuple(discovered_texture_files or ())), matched_texture_indices=matched_texture_indices, vertex_limit=_state.static_replacement_vertex_limit)
    appended_indices = import_state.appended_indices
    if not appended_indices:
        return None, 'keep'
    target_count = len(_state.original_mesh_for_mapping.submeshes)
    primary_target = _state._source_part_assignment_primary_target_helper(selected_target_index=_state._selected_target_index(), selected_original_index=_state.selected_original_part.get('index', -1), target_count=target_count)
    text = _state._source_part_assignment_dialog_text_helper()
    summary = _state._source_part_assignment_summary_state_helper(import_state=import_state, source_name=source_path.name, placement_note=placement_note, discovered_texture_count=len(tuple(discovered_texture_files or ())), text=text)
    return SimpleNamespace(
        import_state=import_state,
        appended_indices=appended_indices,
        target_count=target_count,
        primary_target=primary_target,
        text=text,
        summary=summary,
    ), ''


def _build_assignment_summary(_state, frame):
    assignment_dialog = _state.QDialog(_state.dialog)
    assignment_dialog.setWindowTitle(frame.text['window_title'])
    assignment_dialog.setMinimumWidth(820)
    assignment_dialog.setStyleSheet(assignment_dialog.styleSheet() + '\n            QFrame#AssignmentSummary {\n                background: #151b22;\n                border: 1px solid #30363d;\n                border-radius: 6px;\n            }\n            QLabel#AssignmentTitle {\n                color: #79c0ff;\n                font-weight: 600;\n            }\n            QLabel#AssignmentWarning {\n                color: #f2cc60;\n                font-weight: 500;\n            }\n            QTreeWidget#AssignmentTree {\n                background: #0d1117;\n                border: 1px solid #30363d;\n                border-radius: 4px;\n                alternate-background-color: #12181f;\n            }\n            ')
    assignment_layout = _state.QVBoxLayout(assignment_dialog)
    assignment_layout.setContentsMargins(14, 12, 14, 12)
    assignment_layout.setSpacing(10)
    summary_frame = _state.QFrame()
    summary_frame.setObjectName('AssignmentSummary')
    summary_layout = _state.QVBoxLayout(summary_frame)
    summary_layout.setContentsMargins(12, 10, 12, 10)
    summary_layout.setSpacing(6)
    title = _state.QLabel(frame.summary.title)
    title.setObjectName('AssignmentTitle')
    summary_layout.addWidget(title)
    intro = _state.QLabel('\n'.join(frame.summary.summary_lines))
    intro.setWordWrap(True)
    summary_layout.addWidget(intro)
    for visible, message in (
        (frame.summary.show_texture_warning, frame.text['texture_warning']),
        (frame.summary.show_dense_warning, frame.text['dense_warning']),
    ):
        if visible:
            warning = _state.QLabel(message)
            warning.setObjectName('AssignmentWarning')
            warning.setWordWrap(True)
            summary_layout.addWidget(warning)
    assignment_layout.addWidget(summary_frame)
    frame.dialog = assignment_dialog
    frame.layout = assignment_layout


def _build_assignment_tree(_state, frame):
    assignment_tree = _state.QTreeWidget()
    assignment_tree.setObjectName('AssignmentTree')
    assignment_tree.setColumnCount(3)
    assignment_tree.setHeaderLabels(list(_state._source_part_assignment_tree_headers_helper()))
    assignment_tree.setRootIsDecorated(False)
    assignment_tree.setAlternatingRowColors(True)
    assignment_tree.setUniformRowHeights(True)
    assignment_tree.setSelectionMode(_state.QAbstractItemView.SingleSelection)
    assignment_tree.setMinimumHeight(130)
    assignment_tree.setMaximumHeight(320)
    assignment_tree.header().setStretchLastSection(True)
    assignment_tree.header().resizeSection(0, 310)
    assignment_tree.header().resizeSection(1, 170)
    row_target_combos = []
    focus_filters = []

    def combo_target_index(combo):
        return _state._source_part_assignment_target_index_helper(combo.currentData())

    def row_targets():
        return tuple((int(source_index), combo_target_index(combo)) for source_index, combo in tuple(row_target_combos))

    def target_for_source(source_index):
        return _state._source_part_assignment_target_for_source_helper(row_targets(), source_index)

    def highlight_source(source_index, target_index=None):
        mapped_source_indices = ()
        normalized_target = _state._source_part_assignment_target_index_helper(target_index) if target_index is not None else -1
        if normalized_target >= 0:
            edit = _state.mapping_edits_by_target.get(normalized_target)
            if edit is not None:
                mapped_source_indices = tuple(_state._parse_mapping_edit(edit))
        highlight = _state._source_part_assignment_highlight_state_helper(source_index=source_index, target_index=target_index, mapped_source_indices=mapped_source_indices)
        _state.selected_source_part['index'] = highlight.source_index
        _state.selected_source_highlight_indices.clear()
        if highlight.source_index >= 0:
            _state.selected_source_highlight_indices.add(highlight.source_index)
        _state._set_transform_source_indices((highlight.source_index,) if highlight.source_index >= 0 else ())
        if target_index is not None:
            _state.selected_target_slot['index'] = highlight.target_index
            _state.selected_target_original_highlight_indices.clear()
            _state.selected_target_original_highlight_indices.update(highlight.target_original_indices)
            _state.selected_target_source_highlight_indices.clear()
            _state.selected_target_source_highlight_indices.update(highlight.target_source_indices)
        _state._sync_highlight_sets()
        _state._refresh_original_reference_preview()
        _state._queue_selection_preview_refresh()

    class AssignmentSourceFocusFilter(_state.QObject):
        def __init__(self, source_index, target_combo):
            super().__init__(frame.dialog)
            self.source_index = int(source_index)
            self.target_combo = target_combo

        def eventFilter(self, watched, event):
            if event.type() in {_state.QEvent.Type.FocusIn, _state.QEvent.Type.MouseButtonPress}:
                highlight_source(self.source_index, combo_target_index(self.target_combo))
            return False

    row_specs = _state._source_part_assignment_row_specs_helper(appended_indices=frame.appended_indices, replacement_sources=tuple(_state.replacement_mesh_for_mapping.submeshes), source_display_names=tuple(_state._source_display_name(index) for index in range(len(_state.replacement_mesh_for_mapping.submeshes))), target_display_names=tuple(_state._target_display_name(index) for index in range(frame.target_count)), primary_target=frame.primary_target, text=frame.text)
    for row_spec in row_specs:
        item = _state._assignment_source_item_helper(assignment_tree, source_index=row_spec.source_index, display_name=_state._source_display_name(row_spec.source_index), geometry_text=row_spec.geometry_text, tooltip=row_spec.tooltip)
        combo = _state.QComboBox()
        for option in row_spec.target_options:
            combo.addItem(option.label, option.target_index)
        combo.setCurrentIndex(max(0, combo.findData(row_spec.default_target)))
        focus_filter = AssignmentSourceFocusFilter(row_spec.source_index, combo)
        combo.installEventFilter(focus_filter)
        focus_filters.append(focus_filter)
        combo.currentIndexChanged.connect(lambda _row=0, index=int(row_spec.source_index), target_combo=combo: highlight_source(index, combo_target_index(target_combo)))
        assignment_tree.setItemWidget(item, 2, combo)
        row_target_combos.append((int(row_spec.source_index), combo))
    if assignment_tree.topLevelItemCount() > 0:
        first_item = assignment_tree.topLevelItem(0)
        assignment_tree.setCurrentItem(first_item)
        try:
            first_index = int(first_item.data(0, _state.Qt.UserRole))
            highlight_source(first_index, target_for_source(first_index))
        except (TypeError, ValueError):
            pass

    def selection_changed():
        item = assignment_tree.currentItem()
        if item is None:
            return
        try:
            source_index = int(item.data(0, _state.Qt.UserRole))
        except (TypeError, ValueError):
            return
        highlight_source(source_index, target_for_source(source_index))

    assignment_tree.itemSelectionChanged.connect(selection_changed)
    frame.layout.addWidget(assignment_tree)
    frame.row_targets = row_targets
    frame.focus_filters = focus_filters


def _run_assignment_dialog(_state, frame):
    button_state = _state._source_part_assignment_button_state_helper(primary_target=frame.primary_target, target_count=frame.target_count, texture_warning=frame.import_state.texture_warning, current_target_name=_state._target_display_name(frame.primary_target) if 0 <= frame.primary_target < frame.target_count else '', text=frame.text)
    button_row = _state.QHBoxLayout()
    button_row.setSpacing(8)
    apply_button = _state.QPushButton(frame.text['apply_button'])
    apply_button.setDefault(True)
    add_all_button = _state.QPushButton(button_state.add_all_text)
    if button_state.add_all_tooltip:
        add_all_button.setToolTip(button_state.add_all_tooltip)
    add_all_button.setEnabled(button_state.add_all_enabled)
    assign_order_button = _state.QPushButton(frame.text['assign_by_order'])
    assign_order_button.setEnabled(button_state.assign_order_enabled)
    textures_button = _state.QPushButton(frame.text['open_textures'])
    textures_button.setVisible(button_state.textures_visible)
    keep_button = _state.QPushButton(frame.text['preview_only_button'])
    cancel_button = _state.QPushButton(frame.text['cancel_import'])
    cancel_button.setToolTip(frame.text['cancel_import_tooltip'])
    buttons = (apply_button, add_all_button, assign_order_button, textures_button, keep_button, cancel_button)
    for button in buttons:
        button.setMinimumWidth(0)
    button_row.addStretch(1)
    for button in buttons:
        button_row.addWidget(button)
    frame.layout.addLayout(button_row)
    action = _state._texture_assignment_action_initial_state_helper()

    def finish(value):
        action['value'] = value
        frame.dialog.accept()

    for button, value in zip(buttons, ('apply', 'add_all', 'by_order', 'textures', 'preview', 'cancel')):
        button.clicked.connect(lambda _checked=False, selected=value: finish(selected))
    if frame.dialog.exec() != _state.QDialog.Accepted:
        action['value'] = 'cancel'
    return str(action.get('value', '') or 'cancel')


def _apply_assignment_route(_state, frame, action):
    route = _state._source_part_assignment_route_state_helper(action=action, appended_indices=frame.appended_indices, primary_target=frame.primary_target, target_count=frame.target_count, row_targets=frame.row_targets())
    if route.open_textures:
        _state.independent_output_source_indices.difference_update(route.preview_indices)
        _state.preview_only_source_indices.update(route.preview_indices)
        _state.control_tabs.setCurrentWidget(_state.textures_tab)
        return route.route
    if route.cancel_import:
        return 'cancel'
    for target_index, indices in route.assignments_by_target.items():
        edit = _state.mapping_edits_by_target.get(target_index)
        if edit is None:
            continue
        merged = _state._parse_mapping_edit(edit)
        for index in indices:
            if int(index) not in merged:
                merged.append(int(index))
        _state._set_mapping_indices(target_index, merged, push_undo=False)
    _state.independent_output_source_indices.difference_update(route.attached_indices)
    _state.independent_output_source_indices.difference_update(route.preview_indices)
    _state.preview_only_source_indices.update(route.preview_indices)
    _state.preview_only_source_indices.difference_update(route.attached_indices)
    return route.route


def _source_part_assignment_step_002(_state):
    def _prompt_assign_appended_mesh_parts(source_path: Path, source_indices: Sequence[int], *, placement_note: str='', discovered_texture_files: Sequence[Path]=()) -> str:
        frame, early_route = _prepare_assignment_prompt(_state, source_path, source_indices, placement_note, discovered_texture_files)
        if frame is None:
            return early_route
        _build_assignment_summary(_state, frame)
        _build_assignment_tree(_state, frame)
        return _apply_assignment_route(_state, frame, _run_assignment_dialog(_state, frame))
    _state._prompt_assign_appended_mesh_parts = _prompt_assign_appended_mesh_parts

def _source_part_assignment_step_003(_state):

    def _maybe_flatten_scene_import_parts(source_path: Path, scene_result: SceneImportResult) -> Optional[SceneImportResult]:
        prompt_state = _state._source_part_multipart_prompt_state_helper(source_name=source_path.name, mesh=scene_result.mesh)
        if not prompt_state.should_prompt:
            return scene_result
        message_box = _state.QMessageBox(_state.dialog)
        message_box.setIcon(_state.QMessageBox.Question)
        message_box.setWindowTitle(prompt_state.title)
        message_box.setText(prompt_state.message)
        keep_button = message_box.addButton(prompt_state.keep_separate_parts, _state.QMessageBox.AcceptRole)
        group_button = message_box.addButton(prompt_state.group_by_material, _state.QMessageBox.ActionRole)
        flatten_button = message_box.addButton(prompt_state.flatten_to_one_part, _state.QMessageBox.ActionRole)
        cancel_button = message_box.addButton(prompt_state.cancel_import, _state.QMessageBox.RejectRole)
        message_box.setDefaultButton(group_button)
        message_box.exec()
        clicked = message_box.clickedButton()
        import_action = _state._source_part_multipart_import_action_helper(clicked, cancel_button=cancel_button, group_button=group_button, flatten_button=flatten_button)
        if import_action == 'cancel':
            return None
        if import_action == 'group':
            return _state.group_scene_import_result_parts_by_material(scene_result, part_name=source_path.stem)
        if import_action != 'flatten':
            return scene_result
        flattened_result = _state.flatten_scene_import_result_parts(scene_result, part_name=source_path.stem)
        return flattened_result
    _state._maybe_flatten_scene_import_parts = _maybe_flatten_scene_import_parts

def _source_part_assignment_step_004(_state):

    def _maybe_reduce_high_density_scene_import(source_path: Path, scene_result: SceneImportResult) -> Optional[SceneImportResult]:
        size_text = _state.format_scene_import_file_size_summary(source_path, scene_result)
        prompt_state = _state._source_part_high_density_prompt_state_helper(mesh=scene_result.mesh, size_text=size_text)
        if not prompt_state.should_prompt:
            return scene_result
        message_box = _state.QMessageBox(_state.dialog)
        message_box.setIcon(_state.QMessageBox.Warning)
        message_box.setWindowTitle(prompt_state.title)
        message_box.setText(prompt_state.message)
        keep_button = message_box.addButton(prompt_state.keep_full_quality, _state.QMessageBox.AcceptRole)
        reduce_button = message_box.addButton(prompt_state.reduce_quality, _state.QMessageBox.ActionRole)
        cancel_button = message_box.addButton(prompt_state.cancel_import, _state.QMessageBox.RejectRole)
        message_box.setDefaultButton(keep_button)
        message_box.exec()
        clicked = message_box.clickedButton()
        import_action = _state._source_part_high_density_import_action_helper(clicked, cancel_button=cancel_button, reduce_button=reduce_button)
        if import_action == 'cancel':
            return None
        if import_action != 'reduce':
            return scene_result
        reduction_limits = _state._source_part_high_density_reduction_limits_helper()
        reduced_result, reduction_report = _state.reduce_scene_import_result_quality(scene_result, max_faces_per_submesh=reduction_limits.max_faces_per_submesh, max_vertices_per_submesh=reduction_limits.max_vertices_per_submesh)
        _state.QMessageBox.information(_state.dialog, prompt_state.reduction_title, _state._source_part_reduction_result_message_helper(original_vertices=reduction_report.original_vertices, original_faces=reduction_report.original_faces, reduced_vertices=reduction_report.reduced_vertices, reduced_faces=reduction_report.reduced_faces))
        return reduced_result
    _state._maybe_reduce_high_density_scene_import = _maybe_reduce_high_density_scene_import

def _source_part_assignment_step_005(_state):

    def _rebuild_source_part_widgets(selected_indices: Sequence[int]=(), *, current_index: int=-1) -> None:
        if _state.replacement_mesh_for_mapping is None:
            return
        source_count = len(_state.replacement_mesh_for_mapping.submeshes)
        selected_set = set(_state._source_part_valid_indices_helper(selected_indices, source_count=source_count))
        try:
            current_index = int(current_index)
        except (TypeError, ValueError):
            current_index = -1
        source_blocked = _state.source_tree.blockSignals(True)
        combo_blocked = _state.part_source_combo.blockSignals(True)
        try:
            _state.source_tree_population_timer.stop()
            _state.source_tree.clear()
            _state.source_items_by_index.clear()
            _state.part_source_combo.clear()
            _state.part_source_combo.addItem(_state.source_part_inspector_control_text['source_select_label'], -1)
            for source_index, source in enumerate(_state.replacement_mesh_for_mapping.submeshes):
                if _state._is_marker_source(source):
                    continue
                _state._add_source_tree_item(source_index, source)
                _state.part_source_combo.addItem(_state._source_display_name(source_index), source_index)
            _state.source_tree.clearSelection()
            current_item: _state.Optional[_state.QTreeWidgetItem] = None
            for source_index in sorted(selected_set):
                item = _state.source_items_by_index.get(source_index)
                if item is None:
                    continue
                item.setSelected(True)
                if current_item is None:
                    current_item = item
            if current_index >= 0 and current_index in _state.source_items_by_index:
                current_item = _state.source_items_by_index[current_index]
                current_item.setSelected(True)
            if current_item is not None:
                _state.source_tree.setCurrentItem(current_item)
            combo_index = _state.part_source_combo.findData(current_index)
            _state.part_source_combo.setCurrentIndex(combo_index if combo_index >= 0 else 0)
            _state._source_tree_population_set_next_index_helper(_state.source_tree_population_state, source_count)
            _state._source_tree_population_mark_complete_helper(_state.source_tree_population_state)
            _state.source_tree_progress_label.setText(_state._source_tree_population_ready_text_helper(_state.source_tree.topLevelItemCount()))
        finally:
            _state.part_source_combo.blockSignals(combo_blocked)
            _state.source_tree.blockSignals(source_blocked)
        _state.selected_source_part['index'] = current_index if current_index in _state.source_items_by_index else -1
        _state._fit_alignment_tree_height_to_rows(_state.source_tree, **_state.source_tree_layout_state.height_fit_kwargs)
        _state._auto_fit_alignment_tree_columns(_state.source_tree, _state.source_tree_layout_state.autofit_min_widths, _state.source_tree_layout_state.autofit_max_widths, expand_columns=_state.source_tree_layout_state.expand_columns)
    _state._rebuild_source_part_widgets = _rebuild_source_part_widgets

def _source_part_assignment_step_006(_state):

    def _source_mapping_target_indices(source_index: int) -> List[int]:
        return list(_state._source_assigned_target_indices_helper(int(source_index), _state.mapping_edits, parse_mapping_edit=_state._parse_mapping_edit))
    _state._source_mapping_target_indices = _source_mapping_target_indices

def _source_part_assignment_step_007(_state):
    _state._factory_result_values.update({'_prompt_assign_appended_mesh_parts': _state._prompt_assign_appended_mesh_parts, '_maybe_flatten_scene_import_parts': _state._maybe_flatten_scene_import_parts, '_maybe_reduce_high_density_scene_import': _state._maybe_reduce_high_density_scene_import, '_rebuild_source_part_widgets': _state._rebuild_source_part_widgets, '_source_mapping_target_indices': _state._source_mapping_target_indices})

STEPS = (
    _source_part_assignment_step_001,
    _source_part_assignment_step_002,
    _source_part_assignment_step_003,
    _source_part_assignment_step_004,
    _source_part_assignment_step_005,
    _source_part_assignment_step_006,
    _source_part_assignment_step_007,
)
