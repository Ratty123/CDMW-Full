"""Texture/material callback factories for static replacement dialog."""

from __future__ import annotations

from types import SimpleNamespace


def create_alignment_added_part_texture_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Optional = context.get('Optional')
    Path = context.get('Path')
    QFileDialog = context.get('QFileDialog')
    QMessageBox = context.get('QMessageBox')
    QModelIndex = context.get('QModelIndex')
    QSizePolicy = context.get('QSizePolicy')
    QTreeWidgetItem = context.get('QTreeWidgetItem')
    Qt = context.get('Qt')
    SCENE_TEXTURE_SOURCE_EXTENSIONS = context.get('SCENE_TEXTURE_SOURCE_EXTENSIONS')
    _add_dialog_supplemental_file = context.get('_add_dialog_supplemental_file')
    _added_part_attached_targets_helper = context.get('_added_part_attached_targets_helper')
    _added_part_detected_assignment_state_helper = context.get('_added_part_detected_assignment_state_helper')
    _added_part_detected_missing_message_helper = context.get('_added_part_detected_missing_message_helper')
    _added_part_selected_texture_assignment_state_helper = context.get('_added_part_selected_texture_assignment_state_helper')
    _added_part_target_has_material_conflict_helper = context.get('_added_part_target_has_material_conflict_helper')
    _added_part_texture_choose_dialog_state_helper = context.get('_added_part_texture_choose_dialog_state_helper')
    _added_part_texture_editor_context_state_helper = context.get('_added_part_texture_editor_context_state_helper')
    _added_part_texture_group_size_state_helper = context.get('_added_part_texture_group_size_state_helper')
    _added_part_texture_highlight_state_helper = context.get('_added_part_texture_highlight_state_helper')
    _added_part_texture_invalid_file_message_helper = context.get('_added_part_texture_invalid_file_message_helper')
    _added_part_texture_item_helper = context.get('_added_part_texture_item_helper')
    _added_part_texture_row_states_helper = context.get('_added_part_texture_row_states_helper')
    _added_part_texture_status_helper = context.get('_added_part_texture_status_helper')
    _added_part_texture_tree_visibility_state_helper = context.get('_added_part_texture_tree_visibility_state_helper')
    _added_texture_editor_loading_set_helper = context.get('_added_texture_editor_loading_set_helper')
    _alignment_mesh_edit_tab_active = context.get('_alignment_mesh_edit_tab_active')
    _auto_fit_alignment_tree_columns = context.get('_auto_fit_alignment_tree_columns')
    _clear_transform_source_indices = context.get('_clear_transform_source_indices')
    _current_added_part_texture_source_index_helper = context.get('_current_added_part_texture_source_index_helper')
    _current_dialog_mappings_for_preview = context.get('_current_dialog_mappings_for_preview')
    _queue_selection_preview_refresh = context.get('_queue_selection_preview_refresh')
    _refresh_original_reference_preview = context.get('_refresh_original_reference_preview')
    _refresh_source_material_plan = context.get('_refresh_source_material_plan')
    _register_allowed_texture_source_file_helper = context.get('_register_allowed_texture_source_file_helper')
    _selection_view_update_kwargs_helper = context.get('_selection_view_update_kwargs_helper')
    _set_added_part_texture_override = context.get('_set_added_part_texture_override')
    _set_mesh_replacement_selection_view = context.get('_set_mesh_replacement_selection_view')
    _source_display_name = context.get('_source_display_name')
    _source_material_name_for_index_helper = context.get('_source_material_name_for_index_helper')
    _source_slot_for_added_part_helper = context.get('_source_slot_for_added_part_helper')
    _sync_highlight_sets = context.get('_sync_highlight_sets')
    _target_display_name = context.get('_target_display_name')
    _update_selection_context = context.get('_update_selection_context')
    added_texture_assign_button = context.get('added_texture_assign_button')
    added_texture_assign_detected_button = context.get('added_texture_assign_detected_button')
    added_texture_choose_base_button = context.get('added_texture_choose_base_button')
    added_texture_choose_height_button = context.get('added_texture_choose_height_button')
    added_texture_choose_mask_button = context.get('added_texture_choose_mask_button')
    added_texture_choose_normal_button = context.get('added_texture_choose_normal_button')
    added_texture_clear_button = context.get('added_texture_clear_button')
    added_texture_editor = context.get('added_texture_editor')
    added_texture_editor_loading = context.get('added_texture_editor_loading')
    added_texture_empty_label = context.get('added_texture_empty_label')
    added_texture_group = context.get('added_texture_group')
    added_texture_role_combo = context.get('added_texture_role_combo')
    added_texture_source_combo = context.get('added_texture_source_combo')
    added_texture_tree = context.get('added_texture_tree')
    appended_source_indices = context.get('appended_source_indices')
    assignment_state = context.get('assignment_state')
    choose_state = context.get('choose_state')
    current_item_source_index = context.get('current_item_source_index')
    dialog = context.get('dialog')
    editor_state = context.get('editor_state')
    has_rows = context.get('has_rows')
    highlight_state = context.get('highlight_state')
    index = context.get('index')
    item = context.get('item')
    item_to_select = context.get('item_to_select')
    label = context.get('label')
    message = context.get('message')
    obj_path = context.get('obj_path')
    path = context.get('path')
    preserve_source_index = context.get('preserve_source_index')
    preview_only_source_indices = context.get('preview_only_source_indices')
    previous_scroll = context.get('previous_scroll')
    registered = context.get('registered')
    replacement_mesh_for_mapping = context.get('replacement_mesh_for_mapping')
    resolved = context.get('resolved')
    row_state = context.get('row_state')
    row_states = context.get('row_states')
    seen_texture_file_keys = context.get('seen_texture_file_keys')
    selected_added_part_texture_row = context.get('selected_added_part_texture_row')
    selected_file = context.get('selected_file')
    selected_source_highlight_indices = context.get('selected_source_highlight_indices')
    selected_source_part = context.get('selected_source_part')
    selected_target_original_highlight_indices = context.get('selected_target_original_highlight_indices')
    selected_target_slot = context.get('selected_target_slot')
    selected_target_source_highlight_indices = context.get('selected_target_source_highlight_indices')
    size_state = context.get('size_state')
    slot_kind = context.get('slot_kind')
    slot_sources = context.get('slot_sources')
    source_combo_index = context.get('source_combo_index')
    source_index = context.get('source_index')
    source_material_texture_override_assignments = context.get('source_material_texture_override_assignments')
    source_path = context.get('source_path')
    self = context.get('self')
    targets = context.get('targets')
    texture_files_for_mapping = context.get('texture_files_for_mapping')
    texture_sets = context.get('texture_sets')
    texture_state = context.get('texture_state')
    title = context.get('title')
    visibility_state = context.get('visibility_state')
    widget = context.get('widget')

    def _sync_added_part_texture_group_size(has_rows: bool) -> None:
        size_state = _added_part_texture_group_size_state_helper(
            has_rows,
            empty_label_height=added_texture_empty_label.sizeHint().height(),
            font_height=added_texture_group.fontMetrics().height(),
        )
        added_texture_group.setMaximumHeight(size_state.max_height)
        added_texture_group.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed if size_state.fixed_height else QSizePolicy.Maximum,
        )
        added_texture_group.updateGeometry()

    def _highlight_added_part_texture_source(source_index: int) -> None:
        targets = (
            _added_part_attached_targets_helper(source_index, _current_dialog_mappings_for_preview())
            if source_index >= 0
            else ()
        )
        texture_state, _texture_color = (
            _added_part_texture_status_helper(
                source_index,
                attached_targets=targets,
                has_material_conflict=_added_part_target_has_material_conflict_helper(
                    source_index,
                    _current_dialog_mappings_for_preview(),
                    source_material_name_for_index=lambda index: _source_material_name_for_index_helper(
                        index,
                        replacement_mesh_for_mapping,
                        texture_sets,
                    ),
                ),
                base_source_path=_source_slot_for_added_part_helper(
                    source_index,
                    "base",
                    replacement_mesh_for_mapping,
                    texture_sets,
                    source_material_texture_override_assignments,
                ),
                preview_only_source_indices=preview_only_source_indices,
            )
            if source_index >= 0
            else ("-", "#8b949e")
        )
        highlight_state = _added_part_texture_highlight_state_helper(
            source_index=source_index,
            target_indices=targets,
            material_name=(
                _source_material_name_for_index_helper(
                    source_index,
                    replacement_mesh_for_mapping,
                    texture_sets,
                )
                if source_index >= 0
                else ""
            ),
            texture_state=texture_state,
        )
        selected_source_part["index"] = int(highlight_state["selected_source_index"])
        selected_source_highlight_indices.clear()
        selected_source_highlight_indices.update(
            tuple(highlight_state["source_highlight_indices"])  # type: ignore[arg-type]
        )
        _clear_transform_source_indices()
        selected_target_source_highlight_indices.clear()
        selected_target_source_highlight_indices.update(
            tuple(highlight_state["target_source_highlight_indices"])  # type: ignore[arg-type]
        )
        selected_target_original_highlight_indices.clear()
        selected_target_original_highlight_indices.update(
            tuple(highlight_state["target_original_highlight_indices"])  # type: ignore[arg-type]
        )
        selected_target_slot["index"] = int(highlight_state["selected_target_index"])
        _sync_highlight_sets()
        _refresh_original_reference_preview()
        _set_mesh_replacement_selection_view(
            **_selection_view_update_kwargs_helper(highlight_state["selection_view"])  # type: ignore[arg-type]
        )
        _update_selection_context()
        _queue_selection_preview_refresh()

    def _refresh_added_part_texture_editor(source_index: int = -1) -> None:
        _added_texture_editor_loading_set_helper(added_texture_editor_loading, True)
        try:
            slot_kind = str(added_texture_role_combo.currentData() or "base")
            editor_state = _added_part_texture_editor_context_state_helper(
                source_index,
                slot_kind,
                replacement_mesh=replacement_mesh_for_mapping,
                texture_sets_by_key=texture_sets,
                override_assignments=source_material_texture_override_assignments,
                texture_files_for_mapping=texture_files_for_mapping,
            )
            for widget in (
                added_texture_role_combo,
                added_texture_source_combo,
                added_texture_assign_button,
                added_texture_assign_detected_button,
                added_texture_clear_button,
                added_texture_choose_base_button,
                added_texture_choose_normal_button,
                added_texture_choose_mask_button,
                added_texture_choose_height_button,
            ):
                widget.setEnabled(editor_state.has_source)
            added_texture_source_combo.blockSignals(True)
            added_texture_source_combo.clear()
            for label, source_path in editor_state.source_choices:
                added_texture_source_combo.addItem(label, source_path)
            if editor_state.has_source:
                source_combo_index = added_texture_source_combo.findData(editor_state.current_source)
                added_texture_source_combo.setCurrentIndex(max(0, source_combo_index))
            added_texture_source_combo.blockSignals(False)
        finally:
            _added_texture_editor_loading_set_helper(added_texture_editor_loading, False)

    def _refresh_added_part_texture_tree(preserve_source_index: Optional[int] = None) -> None:
        if preserve_source_index is None:
            preserve_source_index = int(selected_added_part_texture_row.get("source_index", -1))
        previous_scroll = added_texture_tree.verticalScrollBar().value()
        added_texture_tree.blockSignals(True)
        try:
            added_texture_tree.clear()
            item_to_select: Optional[QTreeWidgetItem] = None
            row_states = _added_part_texture_row_states_helper(
                tuple(appended_source_indices),
                replacement_mesh=replacement_mesh_for_mapping,
                mappings=_current_dialog_mappings_for_preview(),
                texture_sets_by_key=texture_sets,
                override_assignments=source_material_texture_override_assignments,
                preview_only_source_indices=preview_only_source_indices,
                preserve_source_index=int(preserve_source_index),
                source_display_name=_source_display_name,
                target_display_name=_target_display_name,
            )
            for row_state in row_states:
                item = _added_part_texture_item_helper(
                    source_index=row_state.source_index,
                    source_display_name=row_state.source_display_name,
                    target_summary=row_state.target_summary,
                    material_name=row_state.material_name,
                    base_display=row_state.base_display,
                    normal_display=row_state.normal_display,
                    material_display=row_state.material_display,
                    height_display=row_state.height_display,
                    status_label=row_state.status_label,
                    status_color=row_state.status_color,
                )
                added_texture_tree.addTopLevelItem(item)
                if row_state.selected:
                    item_to_select = item
            visibility_state = _added_part_texture_tree_visibility_state_helper(
                added_texture_tree.topLevelItemCount()
            )
            added_texture_empty_label.setVisible(visibility_state.empty_label_visible)
            added_texture_tree.setVisible(visibility_state.tree_visible)
            added_texture_editor.setVisible(visibility_state.editor_visible)
            _sync_added_part_texture_group_size(visibility_state.has_rows)
            if item_to_select is not None:
                added_texture_tree.setCurrentItem(item_to_select)
                selected_added_part_texture_row["source_index"] = int(item_to_select.data(0, Qt.UserRole))
            else:
                selected_added_part_texture_row["source_index"] = -1
                added_texture_tree.clearSelection()
                added_texture_tree.setCurrentIndex(QModelIndex())
            added_texture_tree.verticalScrollBar().setValue(previous_scroll)
        finally:
            added_texture_tree.blockSignals(False)
        _auto_fit_alignment_tree_columns(
            added_texture_tree,
            (120, 120, 130, 130, 130, 130, 130, 100),
            (220, 220, 240, 250, 250, 250, 250, 150),
            expand_column=3,
        )
        _refresh_added_part_texture_editor(int(selected_added_part_texture_row.get("source_index", -1)))

    def _current_added_part_texture_source_index() -> int:
        item = added_texture_tree.currentItem()
        current_item_source_index: object = None
        if item is not None:
            try:
                current_item_source_index = item.data(0, Qt.UserRole)
            except (TypeError, ValueError):
                current_item_source_index = None
        return _current_added_part_texture_source_index_helper(
            current_item_source_index,
            selected_added_part_texture_row.get("source_index", -1),
        )

    def _register_added_part_texture_file(path: Path) -> Optional[Path]:
        resolved = _register_allowed_texture_source_file_helper(
            path,
            texture_files_for_mapping=texture_files_for_mapping,
            seen_texture_file_keys=seen_texture_file_keys,
            allowed_extensions=SCENE_TEXTURE_SOURCE_EXTENSIONS,
        )
        if resolved is None:
            return None
        _add_dialog_supplemental_file(resolved)
        return resolved

    def _active_mesh_edit_added_part_texture_mutation_blocked() -> bool:
        if not (callable(_alignment_mesh_edit_tab_active) and _alignment_mesh_edit_tab_active()):
            return False
        message = (
            "Active Mesh Editor added-part texture overrides require native material execution; "
            "Python texture override mutation fallback is disabled."
        )
        set_status_message = getattr(self, "set_status_message", None)
        if callable(set_status_message):
            set_status_message(message, error=True)
        return True

    def _assign_added_part_selected_texture() -> None:
        assignment_state = _added_part_selected_texture_assignment_state_helper(
            loading_active=bool(added_texture_editor_loading.get("active")),
            source_index=_current_added_part_texture_source_index(),
            slot_kind=str(added_texture_role_combo.currentData() or "base"),
            source_path=str(added_texture_source_combo.currentData() or ""),
        )
        if not assignment_state["apply"]:
            return
        if _active_mesh_edit_added_part_texture_mutation_blocked():
            return
        _set_added_part_texture_override(
            int(assignment_state["source_index"]),
            str(assignment_state["slot_kind"]),
            str(assignment_state["source_path"]),
        )

    def _assign_detected_added_part_textures() -> None:
        source_index = _current_added_part_texture_source_index()
        slot_sources = {
            slot_kind: _source_slot_for_added_part_helper(
                source_index,
                slot_kind,
                replacement_mesh_for_mapping,
                texture_sets,
                source_material_texture_override_assignments,
            )
            for slot_kind in ("base", "normal", "material", "height")
        }
        assignment_state = _added_part_detected_assignment_state_helper(
            source_index=source_index,
            slot_sources=slot_sources,
        )
        if not assignment_state["apply"]:
            return
        if _active_mesh_edit_added_part_texture_mutation_blocked():
            return
        for slot_kind, source_path in tuple(assignment_state["assignments"]):  # type: ignore[arg-type]
            _set_added_part_texture_override(source_index, slot_kind, source_path)
        if assignment_state["show_missing"]:
            title, message = _added_part_detected_missing_message_helper()
            QMessageBox.information(dialog, title, message)

    def _choose_added_part_texture(slot_kind: str) -> None:
        source_index = _current_added_part_texture_source_index()
        choose_state = _added_part_texture_choose_dialog_state_helper(
            source_index,
            slot_kind,
            obj_parent=obj_path.parent,
        )
        if not choose_state.should_open:
            return
        selected_file, _selected_filter = QFileDialog.getOpenFileName(
            dialog,
            choose_state.title,
            choose_state.directory,
            choose_state.file_filter,
        )
        if not selected_file:
            return
        registered = _register_added_part_texture_file(Path(selected_file))
        if registered is None:
            title, message = _added_part_texture_invalid_file_message_helper()
            QMessageBox.warning(dialog, title, message)
            return
        if _active_mesh_edit_added_part_texture_mutation_blocked():
            return
        _set_added_part_texture_override(source_index, slot_kind, str(registered))
        try:
            _refresh_source_material_plan()
        except NameError:
            pass

    def _clear_added_part_texture_override() -> None:
        source_index = _current_added_part_texture_source_index()
        slot_kind = str(added_texture_role_combo.currentData() or "base")
        if _active_mesh_edit_added_part_texture_mutation_blocked():
            return
        _set_added_part_texture_override(source_index, slot_kind, "")

    def _added_texture_tree_selection_changed(*_args: object) -> None:
        source_index = _current_added_part_texture_source_index()
        selected_added_part_texture_row["source_index"] = source_index
        _refresh_added_part_texture_editor(source_index)
        _highlight_added_part_texture_source(source_index)

    def _added_texture_role_changed(*_args: object) -> None:
        if added_texture_editor_loading.get("active"):
            return
        _refresh_added_part_texture_editor(_current_added_part_texture_source_index())

    return SimpleNamespace(
        _sync_added_part_texture_group_size=_sync_added_part_texture_group_size,
        _highlight_added_part_texture_source=_highlight_added_part_texture_source,
        _refresh_added_part_texture_editor=_refresh_added_part_texture_editor,
        _refresh_added_part_texture_tree=_refresh_added_part_texture_tree,
        _current_added_part_texture_source_index=_current_added_part_texture_source_index,
        _register_added_part_texture_file=_register_added_part_texture_file,
        _assign_added_part_selected_texture=_assign_added_part_selected_texture,
        _assign_detected_added_part_textures=_assign_detected_added_part_textures,
        _choose_added_part_texture=_choose_added_part_texture,
        _clear_added_part_texture_override=_clear_added_part_texture_override,
        _added_texture_tree_selection_changed=_added_texture_tree_selection_changed,
        _added_texture_role_changed=_added_texture_role_changed,
    )


def create_alignment_original_texture_material_callbacks(context: dict[str, object]) -> SimpleNamespace:
    ARCHIVE_MESH_EXTENSIONS = context.get('ARCHIVE_MESH_EXTENSIONS')
    AlignmentOriginalTexturePreviewWorker = context.get('AlignmentOriginalTexturePreviewWorker')
    ArchiveEntry = context.get('ArchiveEntry')
    DONOR_MODE_OPTIONS = context.get('DONOR_MODE_OPTIONS')
    Dict = context.get('Dict')
    List = context.get('List')
    ModelPreviewData = context.get('ModelPreviewData')
    NativePreviewPanel = context.get('NativePreviewPanel')
    Optional = context.get('Optional')
    Path = context.get('Path')
    QAbstractItemView = context.get('QAbstractItemView')
    QApplication = context.get('QApplication')
    QComboBox = context.get('QComboBox')
    QDialog = context.get('QDialog')
    QDialogButtonBox = context.get('QDialogButtonBox')
    QHBoxLayout = context.get('QHBoxLayout')
    QLabel = context.get('QLabel')
    QMessageBox = context.get('QMessageBox')
    QProgressDialog = context.get('QProgressDialog')
    QPushButton = context.get('QPushButton')
    QSplitter = context.get('QSplitter')
    QThread = context.get('QThread')
    QTreeWidget = context.get('QTreeWidget')
    QTreeWidgetItem = context.get('QTreeWidgetItem')
    QVBoxLayout = context.get('QVBoxLayout')
    QWidget = context.get('QWidget')
    Qt = context.get('Qt')
    RunCancelled = context.get('RunCancelled')
    Sequence = context.get('Sequence')
    StaticSubmeshMapping = context.get('StaticSubmeshMapping')
    Tuple = context.get('Tuple')
    _alignment_d3d11_clear_archive_parity_upgrade_helper = context.get('_alignment_d3d11_clear_archive_parity_upgrade_helper')
    _alignment_d3d11_clear_original_texture_worker_refs_helper = context.get('_alignment_d3d11_clear_original_texture_worker_refs_helper')
    _alignment_d3d11_next_original_texture_worker_request_id_helper = context.get('_alignment_d3d11_next_original_texture_worker_request_id_helper')
    _alignment_d3d11_original_texture_worker_request_current_helper = context.get('_alignment_d3d11_original_texture_worker_request_current_helper')
    _alignment_d3d11_record_original_texture_worker_refs_helper = context.get('_alignment_d3d11_record_original_texture_worker_refs_helper')
    _alignment_mesh_edit_tab_active = context.get('_alignment_mesh_edit_tab_active')
    _alignment_texture_lookup_indexes = context.get('_alignment_texture_lookup_indexes')
    _apply_selected_donor_material = context.get('_apply_selected_donor_material')
    _attach_model_sidecar_texture_preview_paths = context.get('_attach_model_sidecar_texture_preview_paths')
    _attach_model_support_texture_preview_paths = context.get('_attach_model_support_texture_preview_paths')
    _attach_model_texture_preview_paths = context.get('_attach_model_texture_preview_paths')
    _auto_fit_alignment_tree_columns = context.get('_auto_fit_alignment_tree_columns')
    _clear_transform_source_indices = context.get('_clear_transform_source_indices')
    _clone_preview_model = context.get('_clone_preview_model')
    _donor_bindings_from_sidecar_profiles_helper = context.get('_donor_bindings_from_sidecar_profiles_helper')
    _donor_material_plan_build_state_helper = context.get('_donor_material_plan_build_state_helper')
    _donor_material_plan_item_helper = context.get('_donor_material_plan_item_helper')
    _donor_material_plan_tree_size_state_helper = context.get('_donor_material_plan_tree_size_state_helper')
    _donor_material_status_text_helper = context.get('_donor_material_status_text_helper')
    _donor_mesh_picker_candidates_helper = context.get('_donor_mesh_picker_candidates_helper')
    _donor_part_changed = context.get('_donor_part_changed')
    _donor_part_rows_helper = context.get('_donor_part_rows_helper')
    _donor_part_tree_item_helper = context.get('_donor_part_tree_item_helper')
    _donor_texture_binding_display_state_helper = context.get('_donor_texture_binding_display_state_helper')
    _donor_texture_binding_item_helper = context.get('_donor_texture_binding_item_helper')
    _empty_donor_part_tree_item_helper = context.get('_empty_donor_part_tree_item_helper')
    _extract_archive_model_sidecar_texture_references = context.get('_extract_archive_model_sidecar_texture_references')
    _load_native_preview_core_material_manifest_for_alignment = context.get('_load_native_preview_core_material_manifest_for_alignment')
    _mark_alignment_d3d11_rebuild_reason = context.get('_mark_alignment_d3d11_rebuild_reason')
    _material_plan_detail_state_helper = context.get('_material_plan_detail_state_helper')
    _material_plan_highlight_state_helper = context.get('_material_plan_highlight_state_helper')
    _material_plan_item_selection_helper = context.get('_material_plan_item_selection_helper')
    _material_route_control_state_helper = context.get('_material_route_control_state_helper')
    _material_routing_conflict_messages_helper = context.get('_material_routing_conflict_messages_helper')
    _normalize_model_visible_texture_mode = context.get('_normalize_model_visible_texture_mode')
    _original_reference_texture_preview_clear_loading_helper = context.get('_original_reference_texture_preview_clear_loading_helper')
    _original_reference_texture_preview_error_state_helper = context.get('_original_reference_texture_preview_error_state_helper')
    _original_reference_texture_preview_exception_state_helper = context.get('_original_reference_texture_preview_exception_state_helper')
    _original_reference_texture_preview_load_start_state_helper = context.get('_original_reference_texture_preview_load_start_state_helper')
    _original_texture_preview_toggle_state_helper = context.get('_original_texture_preview_toggle_state_helper')
    _populate_combo_options_helper = context.get('_populate_combo_options_helper')
    _populate_donor_texture_tree = context.get('_populate_donor_texture_tree')
    _queue_selection_preview_refresh = context.get('_queue_selection_preview_refresh')
    _queue_static_preview_refresh = context.get('_queue_static_preview_refresh')
    _queue_texture_preview_refresh = context.get('_queue_texture_preview_refresh')
    _record_runtime_event = context.get('_record_runtime_event')
    _refresh_dds_detail_thumbnail = context.get('_refresh_dds_detail_thumbnail')
    _refresh_original_reference_preview = context.get('_refresh_original_reference_preview')
    _resolve_original_textures = context.get('_resolve_original_textures')
    _selected_donor_bindings_for_plan = context.get('_selected_donor_bindings_for_plan')
    _selected_donor_bindings_for_plan_helper = context.get('_selected_donor_bindings_for_plan_helper')
    _selected_material_target_index_helper = context.get('_selected_material_target_index_helper')
    _selected_target_index = context.get('_selected_target_index')
    _selection_view_update_kwargs_helper = context.get('_selection_view_update_kwargs_helper')
    _set_alignment_d3d11_loading = context.get('_set_alignment_d3d11_loading')
    _set_alignment_d3d11_progress = context.get('_set_alignment_d3d11_progress')
    _set_mesh_replacement_selection_view = context.get('_set_mesh_replacement_selection_view')
    _set_preview_performance_status = context.get('_set_preview_performance_status')
    _source_material_names_for_mapping_helper = context.get('_source_material_names_for_mapping_helper')
    _sync_highlight_sets = context.get('_sync_highlight_sets')
    _target_display_name = context.get('_target_display_name')
    _target_material_name_for_index_helper = context.get('_target_material_name_for_index_helper')
    _texture_uv_transform_key = context.get('_texture_uv_transform_key')
    _update_selection_context = context.get('_update_selection_context')
    build_archive_preview_result = context.get('build_archive_preview_result')
    alignment_d3d11_state = context.get('alignment_d3d11_state')
    apply_selected_source_textures_button = context.get('apply_selected_source_textures_button')
    binding = context.get('binding')
    bindings_for_part = context.get('bindings_for_part')
    bindings_for_plan = context.get('bindings_for_plan')
    checked = context.get('checked')
    control_state = context.get('control_state')
    current = context.get('current')
    dds_detail_label = context.get('dds_detail_label')
    dds_detail_panel = context.get('dds_detail_panel')
    detail_html = context.get('detail_html')
    detail_state = context.get('detail_state')
    dialog = context.get('dialog')
    dialog_title = context.get('dialog_title')
    display_state = context.get('display_state')
    donor_apply_button = context.get('donor_apply_button')
    donor_bindings = context.get('donor_bindings')
    donor_bindings_from_profile = context.get('donor_bindings_from_profile')
    donor_buttons = context.get('donor_buttons')
    donor_control_text = context.get('donor_control_text')
    donor_dialog = context.get('donor_dialog')
    donor_entry = context.get('donor_entry')
    donor_header = context.get('donor_header')
    donor_layout = context.get('donor_layout')
    donor_material_group = context.get('donor_material_group')
    donor_material_plan_tree = context.get('donor_material_plan_tree')
    donor_material_plans_by_target = context.get('donor_material_plans_by_target')
    donor_mode_combo = context.get('donor_mode_combo')
    donor_mode_row = context.get('donor_mode_row')
    donor_part_tree = context.get('donor_part_tree')
    donor_preview = context.get('donor_preview')
    donor_right = context.get('donor_right')
    donor_right_layout = context.get('donor_right_layout')
    donor_sidecar_texts = context.get('donor_sidecar_texts')
    donor_splitter = context.get('donor_splitter')
    donor_status_label = context.get('donor_status_label')
    donor_texture_tree = context.get('donor_texture_tree')
    entry = context.get('entry')
    error_state = context.get('error_state')
    exc = context.get('exc')
    exception_state = context.get('exception_state')
    highlight_state = context.get('highlight_state')
    item = context.get('item')
    load_state = context.get('load_state')
    mapping = context.get('mapping')
    mappings = context.get('mappings')
    material_choose_file_button = context.get('material_choose_file_button')
    material_combo_index = context.get('material_combo_index')
    material_do_not_emit_button = context.get('material_do_not_emit_button')
    material_keep_original_button = context.get('material_keep_original_button')
    material_key = context.get('material_key')
    material_name = context.get('material_name')
    material_neutralize_button = context.get('material_neutralize_button')
    material_plan_control_text = context.get('material_plan_control_text')
    material_use_route_source_button = context.get('material_use_route_source_button')
    mesh_entries = context.get('mesh_entries')
    message = context.get('message')
    modify_original_clone_mode = context.get('modify_original_clone_mode')
    native_material_batches = context.get('native_material_batches')
    normalized_visible_texture_mode = context.get('normalized_visible_texture_mode')
    original_dialog_preview = context.get('original_dialog_preview')
    original_mesh_for_mapping = context.get('original_mesh_for_mapping')
    original_reference_preview_model = context.get('original_reference_preview_model')
    original_reference_texture_preview_state = context.get('original_reference_texture_preview_state')
    original_texture_preview_state = context.get('original_texture_preview_state')
    original_texture_worker_receiver = context.get('original_texture_worker_receiver')
    package_root_text = context.get('package_root_text')
    part_item = context.get('part_item')
    part_target_combo = context.get('part_target_combo')
    plan = context.get('plan')
    plan_state = context.get('plan_state')
    preview_model = context.get('preview_model')
    _get_preview_render_settings = context.get('_get_preview_render_settings')
    preview_render_settings = context.get('preview_render_settings')
    profile_mode_index = context.get('profile_mode_index')
    progress = context.get('progress')
    read_archive_entry_data = context.get('read_archive_entry_data')
    rebuild_sidecar_checkbox = context.get('rebuild_sidecar_checkbox')
    replacement_mesh_for_mapping = context.get('replacement_mesh_for_mapping')
    request_id = context.get('request_id')
    row = context.get('row')
    selected_source_highlight_indices = context.get('selected_source_highlight_indices')
    selected_source_part = context.get('selected_source_part')
    selected_target_original_highlight_indices = context.get('selected_target_original_highlight_indices')
    selected_target_slot = context.get('selected_target_slot')
    selected_target_source_highlight_indices = context.get('selected_target_source_highlight_indices')
    selected_texture_plan_source = context.get('selected_texture_plan_source')
    selected_texture_plan_source_state = context.get('selected_texture_plan_source_state')
    selection = context.get('selection')
    self = context.get('self')
    sidecar_bindings = context.get('sidecar_bindings')
    sidecar_bindings_for_advanced = context.get('sidecar_bindings_for_advanced')
    sidecar_data = context.get('sidecar_data')
    sidecar_entry = context.get('sidecar_entry')
    sidecar_text = context.get('sidecar_text')
    sidecar_texts_by_basename = context.get('sidecar_texts_by_basename')
    sidecar_texts_by_normalized_path = context.get('sidecar_texts_by_normalized_path')
    size_state = context.get('size_state')
    source_entry = context.get('source_entry')
    stop_event = context.get('stop_event')
    target_index = context.get('target_index')
    target_material_name = context.get('target_material_name')
    texconv_path = context.get('texconv_path')
    texconv_text = context.get('texconv_text')
    texts = context.get('texts')
    texture_entries_by_basename_for_alignment = context.get('texture_entries_by_basename_for_alignment')
    texture_entries_by_normalized_path_for_alignment = context.get('texture_entries_by_normalized_path_for_alignment')
    texture_overrides_dirty = context.get('texture_overrides_dirty')
    texture_sets = context.get('texture_sets')
    texture_transform_group = context.get('texture_transform_group')
    texture_transform_material_combo = context.get('texture_transform_material_combo')
    thread = context.get('thread')
    threading = context.get('threading')
    toggle_state = context.get('toggle_state')
    try_decode_text_like_archive_data = context.get('try_decode_text_like_archive_data')
    worker = context.get('worker')
    worker_request_id = context.get('worker_request_id')

    def _current_preview_render_settings() -> object:
        if callable(_get_preview_render_settings):
            return _get_preview_render_settings()
        return preview_render_settings

    def _stop_original_reference_texture_worker() -> None:
        worker = alignment_d3d11_state.get("original_texture_worker")
        if isinstance(worker, AlignmentOriginalTexturePreviewWorker):
            worker.stop()
        thread = alignment_d3d11_state.get("original_texture_thread")
        if isinstance(thread, QThread) and thread.isRunning():
            thread.quit()
            thread.wait(150)
        _alignment_d3d11_clear_original_texture_worker_refs_helper(alignment_d3d11_state)

    def _cleanup_original_reference_texture_worker_refs() -> None:
        _alignment_d3d11_clear_original_texture_worker_refs_helper(alignment_d3d11_state)

    def _handle_original_reference_texture_preview_error(request_id: int, message: str) -> None:
        error_state = _original_reference_texture_preview_error_state_helper(
            original_reference_texture_preview_state,
            request_current=_alignment_d3d11_original_texture_worker_request_current_helper(
                alignment_d3d11_state,
                request_id,
            ),
            message=message,
        )
        if not error_state.handled:
            return
        _record_runtime_event(
            "mesh_alignment_original_texture_preview_failed",
            path=getattr(entry, "path", ""),
            dialog_title=dialog_title,
            message=str(message),
            modify_original_clone=modify_original_clone_mode,
        )
        original_dialog_preview.clear_model(error_state.message)
        _set_alignment_d3d11_loading(False, error_state.message)
        _set_preview_performance_status(
            error_state.performance.summary,
            details=error_state.performance.details,
        )
        _alignment_d3d11_clear_archive_parity_upgrade_helper(alignment_d3d11_state)
        _mark_alignment_d3d11_rebuild_reason("material")
        _queue_static_preview_refresh()

    def _current_archive_original_preview_model() -> object | None:
        if ModelPreviewData is None or ArchiveEntry is None or not callable(getattr(self, "_same_archive_entry", None)):
            return None
        current_entry = self._current_archive_entry() if callable(getattr(self, "_current_archive_entry", None)) else None
        if not isinstance(current_entry, ArchiveEntry) or not self._same_archive_entry(current_entry, entry):
            return None
        sync_current = getattr(self, "_sync_current_archive_preview_model_from_widget", None)
        if callable(sync_current):
            sync_current()
        current_result = getattr(self, "current_archive_preview_result", None)
        preview_model = getattr(current_result, "preview_model", None)
        if not isinstance(preview_model, ModelPreviewData) or not getattr(preview_model, "meshes", None):
            return None
        clone_archive_preview = getattr(self, "_clone_archive_preview_model", None)
        if callable(clone_archive_preview):
            cloned = clone_archive_preview(preview_model, strip_images=True)
        else:
            cloned = _clone_preview_model(preview_model)
        return cloned if isinstance(cloned, ModelPreviewData) else preview_model

    def _load_original_reference_texture_preview() -> None:
        load_state = _original_reference_texture_preview_load_start_state_helper(
            original_reference_texture_preview_state,
            has_original_reference_model=original_reference_preview_model is not None,
        )
        if not load_state.should_start:
            return
        _set_alignment_d3d11_progress(
            10,
            load_state.progress_message,
            stage="source_textures",
            detail=load_state.detail,
        )
        _set_preview_performance_status(
            load_state.performance.summary,
            details=load_state.performance.details,
        )
        try:
            texconv_text = self.texconv_path_edit.text().strip()
            texconv_path = Path(texconv_text).expanduser() if texconv_text else None
            package_root_text = self.archive_package_root_edit.text().strip()
            current_preview_render_settings = _current_preview_render_settings()
            normalized_visible_texture_mode = _normalize_model_visible_texture_mode(
                str(getattr(current_preview_render_settings, "visible_texture_mode", ""))
            )
            current_archive_preview_model = _current_archive_original_preview_model()
            companion_entry = (
                self._find_archive_preview_companion_entry(entry)
                if callable(getattr(self, "_find_archive_preview_companion_entry", None))
                else None
            )
            support_texture_slots = (
                self._archive_preview_support_texture_slots(current_preview_render_settings)
                if callable(getattr(self, "_archive_preview_support_texture_slots", None))
                else ("normal", "material", "height")
            )
            archive_texture_entries_by_normalized_path = getattr(self, "archive_entries_by_normalized_path", {})
            archive_texture_entries_by_basename = getattr(self, "archive_entries_by_basename", {})
            archive_sidecar_entries_by_texture_path = getattr(self, "archive_sidecar_entries_by_texture_path", {})
            archive_sidecar_entries_by_texture_basename = getattr(self, "archive_sidecar_entries_by_texture_basename", {})

            def _resolve_original_textures(stop_event: threading.Event) -> tuple[object, int]:
                if stop_event.is_set():
                    raise RunCancelled("Original texture preview cancelled.")
                archive_preview_authoritative = ModelPreviewData is not None and isinstance(
                    current_archive_preview_model,
                    ModelPreviewData,
                )
                preview_model = _clone_preview_model(current_archive_preview_model) if archive_preview_authoritative else None
                if preview_model is None and callable(build_archive_preview_result):
                    preview_result = build_archive_preview_result(
                        texconv_path,
                        entry,
                        companion_entry=companion_entry,
                        texture_entries_by_normalized_path=archive_texture_entries_by_normalized_path,
                        texture_entries_by_basename=archive_texture_entries_by_basename,
                        sidecar_entries_by_texture_path=archive_sidecar_entries_by_texture_path,
                        sidecar_entries_by_texture_basename=archive_sidecar_entries_by_texture_basename,
                        visible_texture_mode=normalized_visible_texture_mode,
                        support_texture_slots=support_texture_slots,
                        stop_event=stop_event,
                    )
                    preview_candidate = getattr(preview_result, "preview_model", None)
                    if (
                        ModelPreviewData is not None
                        and isinstance(preview_candidate, ModelPreviewData)
                        and getattr(preview_candidate, "meshes", None)
                    ):
                        preview_model = _clone_preview_model(preview_candidate)
                        archive_preview_authoritative = True
                if preview_model is None:
                    preview_model = _clone_preview_model(original_reference_preview_model)
                (
                    texture_entries_by_normalized_path_for_alignment,
                    texture_entries_by_basename_for_alignment,
                ) = _alignment_texture_lookup_indexes()
                if stop_event.is_set():
                    raise RunCancelled("Original texture preview cancelled.")
                if not archive_preview_authoritative:
                    if normalized_visible_texture_mode == "mesh_base_first":
                        _attach_model_texture_preview_paths(
                            texconv_path,
                            entry,
                            preview_model,
                            texture_entries_by_normalized_path=texture_entries_by_normalized_path_for_alignment,
                            texture_entries_by_basename=texture_entries_by_basename_for_alignment,
                            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                            sidecar_texts_by_basename=sidecar_texts_by_basename,
                        )
                    _attach_model_sidecar_texture_preview_paths(
                        texconv_path,
                        entry,
                        preview_model,
                        parsed_mesh=original_mesh_for_mapping,
                        sidecar_texture_bindings=sidecar_bindings,
                        visible_texture_mode=normalized_visible_texture_mode,
                        texture_entries_by_normalized_path=texture_entries_by_normalized_path_for_alignment,
                        texture_entries_by_basename=texture_entries_by_basename_for_alignment,
                        sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                        sidecar_texts_by_basename=sidecar_texts_by_basename,
                    )
                    if normalized_visible_texture_mode != "mesh_base_first":
                        _attach_model_texture_preview_paths(
                            texconv_path,
                            entry,
                            preview_model,
                            texture_entries_by_normalized_path=texture_entries_by_normalized_path_for_alignment,
                            texture_entries_by_basename=texture_entries_by_basename_for_alignment,
                            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                            sidecar_texts_by_basename=sidecar_texts_by_basename,
                        )
                    if sidecar_bindings and normalized_visible_texture_mode == "mesh_base_first":
                        _attach_model_sidecar_texture_preview_paths(
                            texconv_path,
                            entry,
                            preview_model,
                            parsed_mesh=original_mesh_for_mapping,
                            sidecar_texture_bindings=sidecar_bindings,
                            visible_texture_mode="layer_aware_visible",
                            texture_entries_by_normalized_path=texture_entries_by_normalized_path_for_alignment,
                            texture_entries_by_basename=texture_entries_by_basename_for_alignment,
                            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                            sidecar_texts_by_basename=sidecar_texts_by_basename,
                            fallback_only=True,
                        )
                        _attach_model_texture_preview_paths(
                            texconv_path,
                            entry,
                            preview_model,
                            texture_entries_by_normalized_path=texture_entries_by_normalized_path_for_alignment,
                            texture_entries_by_basename=texture_entries_by_basename_for_alignment,
                            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                            sidecar_texts_by_basename=sidecar_texts_by_basename,
                            override_existing_base=True,
                            prefer_material_name_for_base=True,
                        )
                    if stop_event.is_set():
                        raise RunCancelled("Original texture preview cancelled.")
                    _attach_model_support_texture_preview_paths(
                        texconv_path,
                        entry,
                        preview_model,
                        parsed_mesh=original_mesh_for_mapping,
                        sidecar_texture_bindings=sidecar_bindings,
                        texture_entries_by_normalized_path=texture_entries_by_normalized_path_for_alignment,
                        texture_entries_by_basename=texture_entries_by_basename_for_alignment,
                        sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                        sidecar_texts_by_basename=sidecar_texts_by_basename,
                    )
                self._attach_archive_model_preview_images(preview_model)
                native_material_batches = _load_native_preview_core_material_manifest_for_alignment(
                    preview_model,
                    package_root_text,
                )
                return preview_model, native_material_batches

            _stop_original_reference_texture_worker()
            worker_request_id = _alignment_d3d11_next_original_texture_worker_request_id_helper(
                alignment_d3d11_state
            )
            worker = AlignmentOriginalTexturePreviewWorker(worker_request_id, _resolve_original_textures)
            thread = QThread(dialog)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.completed.connect(
                original_texture_worker_receiver.handle_completed,
                Qt.QueuedConnection,
            )
            worker.error.connect(
                original_texture_worker_receiver.handle_error,
                Qt.QueuedConnection,
            )
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(_cleanup_original_reference_texture_worker_refs)
            _alignment_d3d11_record_original_texture_worker_refs_helper(
                alignment_d3d11_state,
                worker=worker,
                thread=thread,
            )
            thread.start()
        except Exception as exc:
            exception_state = _original_reference_texture_preview_exception_state_helper(
                original_reference_texture_preview_state,
                exc,
            )
            _record_runtime_event(
                "mesh_alignment_original_texture_preview_failed",
                path=getattr(entry, "path", ""),
                dialog_title=dialog_title,
                message=str(exc),
                modify_original_clone=modify_original_clone_mode,
            )
            original_dialog_preview.clear_model(exception_state.message)
            _set_alignment_d3d11_loading(False, exception_state.message)
            _set_preview_performance_status(
                exception_state.performance.summary,
                details=exception_state.performance.details,
            )
            _queue_static_preview_refresh()
            _original_reference_texture_preview_clear_loading_helper(original_reference_texture_preview_state)

    def _highlight_texture_plan_item(item: Optional[QTreeWidgetItem]) -> None:
        selection = _material_plan_item_selection_helper(item)
        material_name = selection.material_name
        highlight_state = _material_plan_highlight_state_helper(
            has_item=selection.has_item,
            source_indices=selection.source_indices,
            target_index=selection.target_index,
            material_name=material_name,
            texture_role=selection.texture_role,
            texture_path=selection.texture_path,
        )
        selected_source_part["index"] = int(highlight_state["selected_source_index"])
        selected_source_highlight_indices.clear()
        selected_source_highlight_indices.update(
            tuple(highlight_state["source_highlight_indices"])  # type: ignore[arg-type]
        )
        _clear_transform_source_indices()
        selected_texture_plan_source_state = highlight_state["texture_plan_source"]
        selected_texture_plan_source["material_name"] = selected_texture_plan_source_state["material_name"]  # type: ignore[index]
        selected_texture_plan_source["source_indices"] = selected_texture_plan_source_state["source_indices"]  # type: ignore[index]
        if material_name:
            try:
                material_key = _texture_uv_transform_key(material_name)
                material_combo_index = texture_transform_material_combo.findData(material_key)  # type: ignore[name-defined]
                if material_combo_index >= 0:
                    texture_transform_material_combo.setCurrentIndex(material_combo_index)  # type: ignore[name-defined]
            except NameError:
                pass
        selected_target_source_highlight_indices.clear()
        selected_target_source_highlight_indices.update(
            tuple(highlight_state["target_source_highlight_indices"])  # type: ignore[arg-type]
        )
        selected_target_original_highlight_indices.clear()
        selected_target_original_highlight_indices.update(
            tuple(highlight_state["target_original_highlight_indices"])  # type: ignore[arg-type]
        )
        selected_target_slot["index"] = int(highlight_state["selected_target_index"])
        _sync_highlight_sets()
        _refresh_original_reference_preview()
        _set_mesh_replacement_selection_view(
            **_selection_view_update_kwargs_helper(highlight_state["selection_view"])  # type: ignore[arg-type]
        )
        _update_selection_context()
        try:
            control_state = _material_route_control_state_helper(
                has_item=item is not None,
                material_name=material_name,
                has_texture_sets=bool(texture_sets),
                has_sidecar_bindings=bool(sidecar_bindings_for_advanced),
            )
            apply_selected_source_textures_button.setEnabled(control_state.apply_selected_source_textures_enabled)
            material_use_route_source_button.setEnabled(control_state.use_route_source_enabled)
            material_keep_original_button.setEnabled(control_state.keep_original_enabled)
            material_choose_file_button.setEnabled(control_state.choose_file_enabled)
            material_neutralize_button.setEnabled(control_state.neutralize_enabled)
            material_do_not_emit_button.setEnabled(control_state.do_not_emit_enabled)
        except NameError:
            pass
        try:
            detail_html = str(item.data(0, Qt.UserRole + 3) or "") if item is not None else ""
            detail_state = _material_plan_detail_state_helper(
                has_item=item is not None,
                detail_html=detail_html,
                material_name=material_name,
                empty_text=str(material_plan_control_text["dds_detail_select_row"]),
            )
            dds_detail_panel.setVisible(detail_state.visible)
            dds_detail_label.setText(detail_state.detail_html)
            _refresh_dds_detail_thumbnail(item)
        except NameError:
            pass
        try:
            texture_transform_group.setVisible(detail_state.transform_visible)
        except NameError:
            pass
        _queue_selection_preview_refresh()

    def _source_material_names_for_mapping(mapping: StaticSubmeshMapping) -> List[str]:
        return list(_source_material_names_for_mapping_helper(mapping, replacement_mesh_for_mapping, texture_sets))

    def _material_routing_conflict_messages(mappings: Sequence[StaticSubmeshMapping]) -> List[str]:
        return list(_material_routing_conflict_messages_helper(mappings, replacement_mesh_for_mapping, texture_sets))

    def _refresh_donor_material_plan_tree() -> None:
        donor_material_plan_tree.clear()
        for target_index, plan in sorted(donor_material_plans_by_target.items()):
            donor_material_plan_tree.addTopLevelItem(
                _donor_material_plan_item_helper(
                    int(target_index),
                    plan,
                    target_display_name=_target_display_name(int(target_index)),
                )
            )
        size_state = _donor_material_plan_tree_size_state_helper(donor_material_plan_tree.topLevelItemCount())
        donor_material_plan_tree.setVisible(size_state.has_rows)
        donor_material_group.setMaximumHeight(size_state.group_max_height)
        donor_material_plan_tree.setMaximumHeight(size_state.tree_max_height)
        _auto_fit_alignment_tree_columns(
            donor_material_plan_tree,
            (120, 100, 140, 120, 90),
            (240, 180, 280, 240, 160),
            expand_columns=(0, 2, 3),
        )

    def _active_mesh_edit_donor_material_mutation_blocked() -> bool:
        if not (callable(_alignment_mesh_edit_tab_active) and _alignment_mesh_edit_tab_active()):
            return False
        message = (
            "Active Mesh Editor donor material routing requires native material execution; "
            "Python donor material plan mutation fallback is disabled."
        )
        set_status_message = getattr(self, "set_status_message", None)
        if callable(set_status_message):
            set_status_message(message, error=True)
        return True

    def _clear_selected_donor_material_source() -> None:
        target_index = _selected_material_target_index_helper(_selected_target_index, part_target_combo.currentData)
        if target_index < 0:
            item = donor_material_plan_tree.currentItem()
            try:
                target_index = int(item.data(0, Qt.UserRole)) if item is not None else -1
            except (TypeError, ValueError):
                target_index = -1
        if target_index < 0:
            return
        if _active_mesh_edit_donor_material_mutation_blocked():
            return
        donor_material_plans_by_target.pop(target_index, None)
        texture_overrides_dirty["dirty"] = True
        _refresh_donor_material_plan_tree()
        _queue_texture_preview_refresh()

    def _load_donor_sidecar_texts(source_entry: ArchiveEntry) -> Dict[str, str]:
        texts: Dict[str, str] = {}
        for sidecar_entry in self._archive_model_sidecar_entries_for_swap(source_entry):
            try:
                sidecar_data, _decompressed, _note = read_archive_entry_data(sidecar_entry)
                sidecar_text = try_decode_text_like_archive_data(sidecar_data) or ""
            except Exception:
                continue
            if sidecar_text.strip():
                texts[sidecar_entry.path.replace("\\", "/")] = sidecar_text
        return texts

    def _open_original_material_source_picker() -> None:
        target_index = _selected_material_target_index_helper(_selected_target_index, part_target_combo.currentData)
        if target_index < 0:
            QMessageBox.information(
                dialog,
                str(donor_control_text["dialog_title"]),
                str(donor_control_text["select_target_message"]),
            )
            return
        target_material_name = _target_material_name_for_index_helper(target_index, original_mesh_for_mapping)
        mesh_entries = _donor_mesh_picker_candidates_helper(
            tuple(getattr(self, "archive_entries", ()) or ()),
            entry,
            same_entry=self._same_archive_entry,
            mesh_extensions=ARCHIVE_MESH_EXTENSIONS,
            archive_entry_type=ArchiveEntry,
        )
        if not mesh_entries:
            QMessageBox.information(
                dialog,
                str(donor_control_text["dialog_title"]),
                str(donor_control_text["no_mesh_message"]),
            )
            return
        donor_entry = self._choose_archive_mesh_source_dialog(
            dialog,
            title=str(donor_control_text["dialog_title"]),
            entries=mesh_entries,
            prompt=str(donor_control_text["picker_prompt"]),
            excluded_entry=entry,
        )
        if not isinstance(donor_entry, ArchiveEntry):
            return
        progress = QProgressDialog(str(donor_control_text["progress_message"]), "", 0, 0, dialog)
        progress.setWindowTitle(str(donor_control_text["dialog_title"]))
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        QApplication.processEvents()
        donor_bindings_from_profile = False
        try:
            (
                donor_bindings,
                _donor_sidecar_paths,
                _donor_texts_by_path,
                _donor_texts_by_basename,
            ) = _extract_archive_model_sidecar_texture_references(
                donor_entry,
                archive_entries_by_basename=self.archive_entries_by_basename,
            )
            donor_sidecar_texts = _load_donor_sidecar_texts(donor_entry)
            if not donor_bindings:
                donor_bindings = _donor_bindings_from_sidecar_profiles_helper(donor_sidecar_texts)
                donor_bindings_from_profile = bool(donor_bindings)
        except Exception as exc:
            progress.close()
            QApplication.processEvents()
            QMessageBox.warning(dialog, str(donor_control_text["dialog_title"]), str(exc))
            return
        progress.close()
        QApplication.processEvents()
        donor_dialog = QDialog(dialog)
        donor_dialog.setWindowTitle(f"{donor_control_text['dialog_title']} - {donor_entry.basename}")
        donor_dialog.resize(1180, 720)
        donor_layout = QVBoxLayout(donor_dialog)
        donor_layout.setContentsMargins(8, 8, 8, 8)
        donor_layout.setSpacing(6)
        donor_header = QLabel(
            f"Target: {_target_display_name(target_index)} | Donor: {donor_entry.path}"
        )
        donor_header.setTextInteractionFlags(Qt.TextSelectableByMouse)
        donor_header.setWordWrap(True)
        donor_layout.addWidget(donor_header)
        donor_splitter = QSplitter(Qt.Horizontal)
        donor_preview = NativePreviewPanel(str(donor_control_text["donor_preview_note"]), theme_key=self.current_theme_key)
        donor_preview.setMinimumSize(330, 320)
        donor_preview.set_render_settings(_current_preview_render_settings())
        donor_preview.clear_model(str(donor_control_text["donor_preview_clear"]))
        donor_splitter.addWidget(donor_preview)
        donor_right = QWidget()
        donor_right_layout = QVBoxLayout(donor_right)
        donor_right_layout.setContentsMargins(6, 0, 0, 0)
        donor_right_layout.setSpacing(5)
        donor_part_tree = QTreeWidget()
        donor_part_tree.setHeaderLabels(list(donor_control_text["part_headers"]))
        donor_part_tree.setMinimumHeight(160)
        for row in _donor_part_rows_helper(tuple(donor_bindings or ())):
            donor_part_tree.addTopLevelItem(_donor_part_tree_item_helper(row))
        if donor_part_tree.topLevelItemCount() <= 0:
            donor_part_tree.addTopLevelItem(_empty_donor_part_tree_item_helper())
        donor_texture_tree = QTreeWidget()
        donor_texture_tree.setHeaderLabels(list(donor_control_text["texture_headers"]))
        donor_texture_tree.setMinimumHeight(240)
        donor_texture_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)

        def _populate_donor_texture_tree(bindings_for_part: Sequence[object]) -> None:
            donor_texture_tree.clear()
            for binding in tuple(bindings_for_part or ()):
                display_state = _donor_texture_binding_display_state_helper(binding)
                donor_texture_tree.addTopLevelItem(
                    _donor_texture_binding_item_helper(
                        binding,
                        slot_label=display_state.slot_label,
                        parameter_name=display_state.parameter_name,
                        texture_path=display_state.texture_path,
                        state=display_state.state,
                    )
                )
            _auto_fit_alignment_tree_columns(
                donor_texture_tree,
                (90, 130, 220, 160, 100),
                (160, 230, 380, 260, 180),
                expand_columns=(2, 3),
            )

        if donor_part_tree.topLevelItemCount() > 0:
            donor_part_tree.setCurrentItem(donor_part_tree.topLevelItem(0))
            _populate_donor_texture_tree(tuple(donor_part_tree.topLevelItem(0).data(0, Qt.UserRole) or ()))

        def _donor_part_changed(current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]) -> None:
            _populate_donor_texture_tree(tuple(current.data(0, Qt.UserRole) if current is not None else ()))

        donor_part_tree.currentItemChanged.connect(_donor_part_changed)
        donor_right_layout.addWidget(QLabel(str(donor_control_text["parts_label"])))
        donor_right_layout.addWidget(donor_part_tree, 0)
        donor_right_layout.addWidget(QLabel(str(donor_control_text["textures_label"])))
        donor_right_layout.addWidget(donor_texture_tree, 1)
        donor_mode_row = QHBoxLayout()
        donor_mode_row.setContentsMargins(0, 0, 0, 0)
        donor_mode_row.setSpacing(5)
        donor_mode_combo = QComboBox()
        _populate_combo_options_helper(donor_mode_combo, DONOR_MODE_OPTIONS)
        profile_mode_index = donor_mode_combo.findData("authoritative_recipe")
        if profile_mode_index >= 0:
            donor_mode_combo.setCurrentIndex(profile_mode_index)
        donor_mode_combo.setToolTip(str(donor_control_text["mode_tooltip"]))
        donor_apply_button = QPushButton(str(donor_control_text["apply_button"]))
        donor_apply_button.setMinimumWidth(0)
        donor_apply_button.setToolTip(str(donor_control_text["apply_button_tooltip"]))
        donor_mode_row.addWidget(QLabel(str(donor_control_text["mode_label"])))
        donor_mode_row.addWidget(donor_mode_combo, 1)
        donor_mode_row.addWidget(donor_apply_button)
        donor_right_layout.addLayout(donor_mode_row)
        donor_status_label = QLabel(
            _donor_material_status_text_helper(
                donor_control_text,
                donor_bindings_from_profile=donor_bindings_from_profile,
            )
        )
        donor_status_label.setObjectName("HintLabel")
        donor_status_label.setWordWrap(True)
        donor_right_layout.addWidget(donor_status_label)
        donor_splitter.addWidget(donor_right)
        donor_splitter.setStretchFactor(0, 2)
        donor_splitter.setStretchFactor(1, 3)
        donor_layout.addWidget(donor_splitter, 1)
        donor_buttons = QDialogButtonBox(QDialogButtonBox.Close)
        donor_buttons.rejected.connect(donor_dialog.reject)
        donor_layout.addWidget(donor_buttons)

        def _selected_donor_bindings_for_plan() -> Tuple[object, ...]:
            part_item = donor_part_tree.currentItem()
            return _selected_donor_bindings_for_plan_helper(
                tuple(
                    item.data(0, Qt.UserRole)
                    for item in donor_texture_tree.selectedItems()
                    if item.data(0, Qt.UserRole) is not None
                ),
                tuple(part_item.data(0, Qt.UserRole) if part_item is not None else ()),
            )

        def _apply_selected_donor_material() -> None:
            bindings_for_plan = _selected_donor_bindings_for_plan()
            plan_state = _donor_material_plan_build_state_helper(
                bindings_for_plan,
                donor_sidecar_texts,
                target_material_name=target_material_name,
                patch_mode=donor_mode_combo.currentData(),
                sidecar_bindings_for_advanced=tuple(sidecar_bindings_for_advanced or ()),
            )
            if plan_state.message_key == "select_binding":
                QMessageBox.information(
                    donor_dialog,
                    str(donor_control_text["dialog_title"]),
                    str(donor_control_text["select_binding_message"]),
                )
                return
            if plan_state.message_key == "unreadable_sidecar" or plan_state.plan is None:
                QMessageBox.warning(
                    donor_dialog,
                    str(donor_control_text["dialog_title"]),
                    str(donor_control_text["unreadable_sidecar_message"]),
                )
                return
            if _active_mesh_edit_donor_material_mutation_blocked():
                return
            donor_material_plans_by_target[target_index] = plan_state.plan
            rebuild_sidecar_checkbox.setChecked(True)
            texture_overrides_dirty["dirty"] = True
            _refresh_donor_material_plan_tree()
            _queue_texture_preview_refresh()
            donor_status_label.setText(
                str(donor_control_text["assigned_status"]).format(
                    donor_part_name=plan_state.donor_part_name or "donor material",
                    target_name=_target_display_name(target_index),
                )
            )

        donor_apply_button.clicked.connect(_apply_selected_donor_material)
        donor_dialog.exec()

    def _set_original_texture_preview_enabled(checked: bool) -> None:
        toggle_state = _original_texture_preview_toggle_state_helper(
            original_texture_preview_state,
            original_reference_texture_preview_state,
            checked,
            modify_original_clone_mode=modify_original_clone_mode,
        )
        if toggle_state.should_load:
            _load_original_reference_texture_preview()
        if toggle_state.should_refresh:
            _queue_texture_preview_refresh()

    return SimpleNamespace(
        _stop_original_reference_texture_worker=_stop_original_reference_texture_worker,
        _cleanup_original_reference_texture_worker_refs=_cleanup_original_reference_texture_worker_refs,
        _handle_original_reference_texture_preview_error=_handle_original_reference_texture_preview_error,
        _load_original_reference_texture_preview=_load_original_reference_texture_preview,
        _highlight_texture_plan_item=_highlight_texture_plan_item,
        _source_material_names_for_mapping=_source_material_names_for_mapping,
        _material_routing_conflict_messages=_material_routing_conflict_messages,
        _refresh_donor_material_plan_tree=_refresh_donor_material_plan_tree,
        _clear_selected_donor_material_source=_clear_selected_donor_material_source,
        _load_donor_sidecar_texts=_load_donor_sidecar_texts,
        _open_original_material_source_picker=_open_original_material_source_picker,
        _set_original_texture_preview_enabled=_set_original_texture_preview_enabled,
    )


def create_alignment_material_plan_column_callbacks(context: dict[str, object]) -> SimpleNamespace:
    QTimer = context.get('QTimer')
    _auto_fit_alignment_tree_columns = context.get('_auto_fit_alignment_tree_columns')
    _material_plan_column_fit_specs_helper = context.get('_material_plan_column_fit_specs_helper')
    _material_plan_column_refit_requests_helper = context.get('_material_plan_column_refit_requests_helper')
    callbacks = context.get('callbacks')
    column_specs = context.get('column_specs')
    delay_ms = context.get('delay_ms')
    material_plan_tree = context.get('material_plan_tree')
    material_routing_tree = context.get('material_routing_tree')
    tree_key = context.get('tree_key')

    def _fit_material_routing_tree_columns() -> None:
        column_specs = _material_plan_column_fit_specs_helper()["routing"]
        try:
            _auto_fit_alignment_tree_columns(
                material_routing_tree,
                column_specs["minimum_widths"],
                column_specs["maximum_widths"],
                expand_columns=column_specs["expand_columns"],
            )
        except RuntimeError:
            return

    def _fit_material_plan_tree_columns() -> None:
        column_specs = _material_plan_column_fit_specs_helper()["plan"]
        try:
            _auto_fit_alignment_tree_columns(
                material_plan_tree,
                column_specs["minimum_widths"],
                column_specs["maximum_widths"],
                expand_columns=column_specs["expand_columns"],
            )
        except RuntimeError:
            return

    def _schedule_material_plan_column_refit() -> None:
        callbacks = {
            "routing": _fit_material_routing_tree_columns,
            "plan": _fit_material_plan_tree_columns,
        }
        for delay_ms, tree_key in _material_plan_column_refit_requests_helper():
            QTimer.singleShot(int(delay_ms), callbacks[str(tree_key)])

    return SimpleNamespace(
        _fit_material_routing_tree_columns=_fit_material_routing_tree_columns,
        _fit_material_plan_tree_columns=_fit_material_plan_tree_columns,
        _schedule_material_plan_column_refit=_schedule_material_plan_column_refit,
    )


def create_alignment_material_plan_final_preview_callbacks(context: dict[str, object]) -> SimpleNamespace:
    FinalPackagePreviewResult = context.get('FinalPackagePreviewResult')
    _clear_tree_current_item = context.get('_clear_tree_current_item')
    _final_binding_row_item_helper = context.get('_final_binding_row_item_helper')
    _final_dds_contract_summary_html_helper = context.get('_final_dds_contract_summary_html_helper')
    _final_material_status_item_helper = context.get('_final_material_status_item_helper')
    _final_preview_binding_preview_status = context.get('_final_preview_binding_preview_status')
    _final_preview_binding_row_states_helper = context.get('_final_preview_binding_row_states_helper')
    _final_preview_binding_target_index_helper = context.get('_final_preview_binding_target_index_helper')
    _final_preview_material_status_color = context.get('_final_preview_material_status_color')
    _final_preview_material_status_row_states_helper = context.get('_final_preview_material_status_row_states_helper')
    _final_preview_plan_state_helper = context.get('_final_preview_plan_state_helper')
    _fit_alignment_tree_height_to_rows = context.get('_fit_alignment_tree_height_to_rows')
    _is_marker_source = context.get('_is_marker_source')
    _material_plan_summary_block = context.get('_material_plan_summary_block')
    _refresh_source_material_plan = context.get('_refresh_source_material_plan')
    _reset_selected_texture_plan_source_state_helper = context.get('_reset_selected_texture_plan_source_state_helper')
    _slot_kind_for_final_preview_row = context.get('_slot_kind_for_final_preview_row')
    _source_indices_for_target_contract = context.get('_source_indices_for_target_contract')
    _source_material_part_summary_helper = context.get('_source_material_part_summary_helper')
    _target_index_for_name = context.get('_target_index_for_name')
    binding_state = context.get('binding_state')
    dds_detail_panel = context.get('dds_detail_panel')
    final_plan_state = context.get('final_plan_state')
    final_preview = context.get('final_preview')
    material_contract_label = context.get('material_contract_label')
    material_plan_blocked = context.get('material_plan_blocked')
    material_plan_control_text = context.get('material_plan_control_text')
    material_plan_summary = context.get('material_plan_summary')
    material_plan_tree = context.get('material_plan_tree')
    material_routing_blocked = context.get('material_routing_blocked')
    material_routing_tree = context.get('material_routing_tree')
    message = context.get('message')
    preview_status = context.get('preview_status')
    replacement_mesh_for_mapping = context.get('replacement_mesh_for_mapping')
    selected_texture_plan_source = context.get('selected_texture_plan_source')
    simplified_part_label = context.get('simplified_part_label')
    source_indices = context.get('source_indices')
    source_parts = context.get('source_parts')
    status_state = context.get('status_state')
    target_index = context.get('target_index')
    texture_material_plan_loaded = context.get('texture_material_plan_loaded')
    texture_sets = context.get('texture_sets')
    texture_transform_group = context.get('texture_transform_group')

    def _refresh_material_plan_from_final_preview(final_preview: FinalPackagePreviewResult) -> None:
        material_plan_blocked = material_plan_tree.blockSignals(True)
        material_routing_blocked = material_routing_tree.blockSignals(True)
        try:
            _clear_tree_current_item(material_plan_tree)
            _clear_tree_current_item(material_routing_tree)
            material_plan_tree.clear()
            material_routing_tree.clear()
        finally:
            material_plan_tree.blockSignals(material_plan_blocked)
            material_routing_tree.blockSignals(material_routing_blocked)
        _reset_selected_texture_plan_source_state_helper(selected_texture_plan_source)
        dds_detail_panel.setVisible(False)
        texture_transform_group.setVisible(False)
        final_plan_state = _final_preview_plan_state_helper(final_preview)
        material_plan_tree.setVisible(True)
        material_routing_tree.setVisible(True)
        material_plan_summary.setText(
            _material_plan_summary_block(
                detected_sets=final_plan_state.detected_sets,
                detected_slots=final_plan_state.detected_slots,
                conflicts=final_plan_state.warnings,
                empty=not bool(final_plan_state.binding_rows),
            )
        )
        material_plan_summary.setToolTip(
            "\n".join(str(message) for message in final_plan_state.warnings[:12])
            if final_plan_state.warnings
            else ""
        )
        material_contract_label.setText(_final_dds_contract_summary_html_helper(len(final_plan_state.binding_rows)))
        material_contract_label.setToolTip(str(material_plan_control_text["final_contract_tooltip"]))
        for status_state in _final_preview_material_status_row_states_helper(
            final_plan_state.material_statuses,
            final_plan_state.binding_rows,
        ):
            source_indices = _source_indices_for_target_contract(status_state.material_name, status_state.material_name)
            source_parts = (
                _source_material_part_summary_helper(
                    status_state.material_name,
                    replacement_mesh_for_mapping,
                    texture_set_count=len(texture_sets),
                    is_marker_source=_is_marker_source,
                )
                if source_indices
                else "-"
            )
            material_routing_tree.addTopLevelItem(
                _final_material_status_item_helper(
                    material_name=status_state.material_name,
                    source_parts=source_parts,
                    maps=status_state.maps,
                    status_label=status_state.status_label,
                    detail=status_state.detail,
                    source_indices=source_indices,
                    target_index=_target_index_for_name(status_state.material_name),
                    status_color=_final_preview_material_status_color(status_state.status_label),
                )
            )
        for binding_state in _final_preview_binding_row_states_helper(final_plan_state.binding_rows):
            preview_status = _final_preview_binding_preview_status(binding_state.binding_row)
            source_indices = _source_indices_for_target_contract(binding_state.part_name, binding_state.material_name)
            target_index = _final_preview_binding_target_index_helper(
                binding_state.part_name,
                binding_state.material_name,
                target_index_for_name=_target_index_for_name,
            )
            material_plan_tree.addTopLevelItem(
                _final_binding_row_item_helper(
                    binding_state.binding_row,
                    part_label=simplified_part_label(binding_state.part_name),
                    part_name=binding_state.part_name,
                    material_name=binding_state.material_name,
                    source_indices=source_indices,
                    target_index=target_index,
                    preview_status=preview_status,
                    status_color=_final_preview_material_status_color(binding_state.status_label),
                    slot_kind=_slot_kind_for_final_preview_row(binding_state.binding_row),
                )
            )
        _fit_alignment_tree_height_to_rows(material_routing_tree, minimum=80, screen_margin=420, maximum=180)
        _fit_alignment_tree_height_to_rows(material_plan_tree, minimum=76, screen_margin=420, maximum=190)
        _fit_material_routing_tree_columns()
        _fit_material_plan_tree_columns()

    def _ensure_source_material_plan_loaded() -> None:
        if bool(texture_material_plan_loaded.get("loading")):
            return
        if bool(texture_material_plan_loaded.get("loaded")) and material_plan_tree.topLevelItemCount() > 0:
            return
        texture_material_plan_loaded["loading"] = True
        try:
            _refresh_source_material_plan(force=True)
        finally:
            texture_material_plan_loaded["loading"] = False

    return SimpleNamespace(
        _refresh_material_plan_from_final_preview=_refresh_material_plan_from_final_preview,
        _ensure_source_material_plan_loaded=_ensure_source_material_plan_loaded,
    )


def create_alignment_texture_table_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Any = context.get('Any')
    Dict = context.get('Dict')
    List = context.get('List')
    Mapping = context.get('Mapping')
    Optional = context.get('Optional')
    Path = context.get('Path')
    QAbstractItemView = context.get('QAbstractItemView')
    QApplication = context.get('QApplication')
    QFileDialog = context.get('QFileDialog')
    QMessageBox = context.get('QMessageBox')
    QModelIndex = context.get('QModelIndex')
    QTreeWidgetItem = context.get('QTreeWidgetItem')
    Qt = context.get('Qt')
    _all_suggested_override_sources_action_state_helper = context.get('_all_suggested_override_sources_action_state_helper')
    _apply_texture_row_to_item_helper = context.get('_apply_texture_row_to_item_helper')
    _alignment_mesh_edit_tab_active = context.get('_alignment_mesh_edit_tab_active')
    _auto_fit_alignment_tree_columns = context.get('_auto_fit_alignment_tree_columns')
    _choose_texture_source_dialog_helper = context.get('_choose_texture_source_dialog_helper')
    _clear_transform_source_indices = context.get('_clear_transform_source_indices')
    _confirm_texture_assignment_action = context.get('_confirm_texture_assignment_action')
    _current_dialog_mappings_for_preview = context.get('_current_dialog_mappings_for_preview')
    _ensure_advanced_dds_overrides_loaded = context.get('_ensure_advanced_dds_overrides_loaded')
    _queue_selection_preview_refresh = context.get('_queue_selection_preview_refresh')
    _queue_texture_preview_refresh = context.get('_queue_texture_preview_refresh')
    _refresh_alignment_virtual_sidecar_contract = context.get('_refresh_alignment_virtual_sidecar_contract')
    _refresh_original_reference_preview = context.get('_refresh_original_reference_preview')
    _refresh_texture_row_guidance = context.get('_refresh_texture_row_guidance')
    _register_texture_source_file_helper = context.get('_register_texture_source_file_helper')
    _selected_material_override_rows_helper = context.get('_selected_material_override_rows_helper')
    _selected_material_texture_clear_action_state_helper = context.get('_selected_material_texture_clear_action_state_helper')
    _selected_material_texture_file_action_state_helper = context.get('_selected_material_texture_file_action_state_helper')
    _selected_texture_editor_state_helper = context.get('_selected_texture_editor_state_helper')
    _selected_texture_source_combo_change_state_helper = context.get('_selected_texture_source_combo_change_state_helper')
    _selected_texture_source_commit_state_helper = context.get('_selected_texture_source_commit_state_helper')
    _set_texture_row_assignment_helper = context.get('_set_texture_row_assignment_helper')
    _suggested_texture_plan_action_state_helper = context.get('_suggested_texture_plan_action_state_helper')
    _sync_highlight_sets = context.get('_sync_highlight_sets')
    _target_index_for_name = context.get('_target_index_for_name')
    _target_texture_clear_assignment_state_helper = context.get('_target_texture_clear_assignment_state_helper')
    _texture_details_state_helper = context.get('_texture_details_state_helper')
    _texture_item_for_row_helper = context.get('_texture_item_for_row_helper')
    _texture_override_item_helper = context.get('_texture_override_item_helper')
    _texture_override_row_sort_key = context.get('_texture_override_row_sort_key')
    _texture_plan_status_color = context.get('_texture_plan_status_color')
    _texture_role_label_for_slot = context.get('_texture_role_label_for_slot')
    _texture_row_can_apply_suggested_for_target = context.get('_texture_row_can_apply_suggested_for_target')
    _texture_row_selection_highlight_state_helper = context.get('_texture_row_selection_highlight_state_helper')
    _texture_row_visible_helper = context.get('_texture_row_visible_helper')
    _texture_summary_label_html = context.get('_texture_summary_label_html')
    _texture_summary_metrics = context.get('_texture_summary_metrics')
    _texture_target_diagnostics_html = context.get('_texture_target_diagnostics_html')
    _update_selection_context = context.get('_update_selection_context')
    action_state = context.get('action_state')
    advanced_dds_control_text = context.get('advanced_dds_control_text')
    advanced_hidden = context.get('advanced_hidden')
    apply_state = context.get('apply_state')
    assigned_count = context.get('assigned_count')
    checked = context.get('checked')
    clear_state = context.get('clear_state')
    column = context.get('column')
    combo_state = context.get('combo_state')
    commit_state = context.get('commit_state')
    details_state = context.get('details_state')
    dialog = context.get('dialog')
    editor_state = context.get('editor_state')
    file_state = context.get('file_state')
    highlight_state = context.get('highlight_state')
    index = context.get('index')
    initial_state = context.get('initial_state')
    item = context.get('item')
    item_to_select = context.get('item_to_select')
    label = context.get('label')
    material_plan_control_text = context.get('material_plan_control_text')
    obj_path = context.get('obj_path')
    path = context.get('path')
    planned_rows = context.get('planned_rows')
    preserve_row = context.get('preserve_row')
    previous_scroll_value = context.get('previous_scroll_value')
    role_index = context.get('role_index')
    row_state = context.get('row_state')
    rows = context.get('rows')
    seen_texture_file_keys = context.get('seen_texture_file_keys')
    selected_apply_suggestion_button = context.get('selected_apply_suggestion_button')
    selected_file = context.get('selected_file')
    selected_role_combo = context.get('selected_role_combo')
    selected_row = context.get('selected_row')
    selected_source_combo = context.get('selected_source_combo')
    selected_source_highlight_indices = context.get('selected_source_highlight_indices')
    selected_source_part = context.get('selected_source_part')
    selected_target_original_highlight_indices = context.get('selected_target_original_highlight_indices')
    selected_target_slot = context.get('selected_target_slot')
    selected_target_source_highlight_indices = context.get('selected_target_source_highlight_indices')
    selected_texture_editor_label = context.get('selected_texture_editor_label')
    selected_texture_editor_loading = context.get('selected_texture_editor_loading')
    selected_texture_plan_source = context.get('selected_texture_plan_source')
    selected_texture_row = context.get('selected_texture_row')
    selected_texture_source_committing = context.get('selected_texture_source_committing')
    simplified_part_label = context.get('simplified_part_label')
    source_path = context.get('source_path')
    self = context.get('self')
    state = context.get('state')
    suggested_source = context.get('suggested_source')
    summary_visible_count = context.get('summary_visible_count')
    sync_editor = context.get('sync_editor')
    sync_texture_row_assignment = context.get('sync_texture_row_assignment')
    target_index = context.get('target_index')
    target_name = context.get('target_name')
    texture_busy_bar = context.get('texture_busy_bar')
    texture_detail_browser = context.get('texture_detail_browser')
    texture_files_for_mapping = context.get('texture_files_for_mapping')
    texture_filter_selected_checkbox = context.get('texture_filter_selected_checkbox')
    texture_override_assignments = context.get('texture_override_assignments')
    texture_override_rows = context.get('texture_override_rows')
    texture_override_tree = context.get('texture_override_tree')
    texture_overrides_dirty = context.get('texture_overrides_dirty')
    texture_row_assigned = context.get('texture_row_assigned')
    texture_row_current_source_indices = context.get('texture_row_current_source_indices')
    texture_row_effective_source = context.get('texture_row_effective_source')
    texture_row_source_summary = context.get('texture_row_source_summary')
    texture_rows_by_target = context.get('texture_rows_by_target')
    texture_show_advanced_checkbox = context.get('texture_show_advanced_checkbox')
    texture_source_choices_for_row = context.get('texture_source_choices_for_row')
    texture_summary_label = context.get('texture_summary_label')
    total_count = context.get('total_count')
    transform_source_indices = context.get('transform_source_indices')
    visible_count = context.get('visible_count')
    visible_rows = context.get('visible_rows')

    def _sync_texture_selection_highlight(row_state: Optional[Mapping[str, Any]]) -> None:
        target_index = _target_index_for_name(str(row_state.get("target_name", "") or "")) if row_state is not None else -1
        highlight_state = _texture_row_selection_highlight_state_helper(
            source_indices=texture_row_current_source_indices(row_state),
            target_index=target_index,
            selected_source_highlights=tuple(selected_source_highlight_indices),
            selected_target_original_highlights=tuple(selected_target_original_highlight_indices),
            transform_source_indices=tuple(transform_source_indices),
        )
        if not bool(highlight_state["changed"]):
            _update_selection_context()
            return
        selected_source_part["index"] = int(highlight_state["selected_source_index"])
        selected_source_highlight_indices.clear()
        _clear_transform_source_indices()
        selected_target_source_highlight_indices.clear()
        selected_target_source_highlight_indices.update(
            tuple(highlight_state["target_source_highlight_indices"])  # type: ignore[arg-type]
        )
        selected_target_original_highlight_indices.clear()
        selected_target_original_highlight_indices.update(
            tuple(highlight_state["target_original_highlight_indices"])  # type: ignore[arg-type]
        )
        selected_target_slot["index"] = int(highlight_state["selected_target_index"])
        _sync_highlight_sets()
        _refresh_original_reference_preview()
        _update_selection_context()
        _queue_selection_preview_refresh()

    def _diagnostics_for_target_html(target_name: str, selected_row: Optional[Dict[str, Any]] = None) -> str:
        rows = texture_rows_by_target.get(target_name, [])
        for row_state in rows:
            sync_texture_row_assignment(row_state)
        if selected_row is not None:
            sync_texture_row_assignment(selected_row)
        return _texture_target_diagnostics_html(
            target_name,
            rows,
            selected_row,
            texture_row_source_summary=texture_row_source_summary,
            texture_row_is_assigned=texture_row_assigned,
        )

    def _current_texture_row() -> Optional[Dict[str, Any]]:
        item = texture_override_tree.currentItem()
        if item is not None:
            row_state = item.data(0, Qt.UserRole + 1)
            if isinstance(row_state, dict):
                return row_state
        return selected_texture_row.get("row")

    def _current_texture_target_name() -> str:
        row_state = _current_texture_row()
        return str(row_state.get("target_name", "") or "") if row_state is not None else ""

    def _active_mesh_edit_texture_table_mutation_blocked() -> bool:
        if not (callable(_alignment_mesh_edit_tab_active) and _alignment_mesh_edit_tab_active()):
            return False
        message = (
            "Active Mesh Editor texture table overrides require native material execution; "
            "Python texture override mutation fallback is disabled."
        )
        set_status_message = getattr(self, "set_status_message", None)
        if callable(set_status_message):
            set_status_message(message, error=True)
        return True

    def _sync_selected_texture_editor(row_state: Optional[Dict[str, Any]]) -> None:
        selected_texture_editor_loading["active"] = True
        try:
            editor_state = _selected_texture_editor_state_helper(
                row_state,
                source_choices=texture_source_choices_for_row,
                effective_source=texture_row_effective_source,
                source_summary=texture_row_source_summary,
                source_summary_tooltip=lambda state: texture_row_source_summary(state, limit=20),
            )
            selected_role_combo.setEnabled(editor_state.has_row)
            selected_source_combo.setEnabled(editor_state.has_row)
            if row_state is not None:
                sync_texture_row_assignment(row_state)
            selected_source_combo.blockSignals(True)
            selected_source_combo.clear()
            for label, source_path in editor_state.source_choices:
                selected_source_combo.addItem(label, source_path)
            selected_source_combo.setCurrentIndex(editor_state.source_index)
            selected_source_combo.blockSignals(False)
            selected_texture_editor_label.setText(editor_state.label_text)
            selected_texture_editor_label.setToolTip(editor_state.label_tooltip)
            selected_role_combo.blockSignals(True)
            role_index = selected_role_combo.findData(editor_state.role_kind)
            selected_role_combo.setCurrentIndex(max(0, role_index))
            selected_role_combo.blockSignals(False)
            selected_apply_suggestion_button.setText(editor_state.suggestion_button_text)
            selected_apply_suggestion_button.setEnabled(editor_state.suggestion_available)
            selected_apply_suggestion_button.setToolTip(editor_state.suggestion_tooltip)
        finally:
            selected_texture_editor_loading["active"] = False

    def _refresh_texture_details(row_state: Optional[Dict[str, Any]] = None, *, sync_editor: bool = True) -> None:
        if row_state is None:
            row_state = selected_texture_row.get("row")
        details_state = _texture_details_state_helper(
            row_state,
            current_target_name=_current_texture_target_name,
            texture_rows_by_target=texture_rows_by_target,
            assigned=texture_row_assigned,
        )
        if sync_editor:
            _sync_selected_texture_editor(row_state)
        _sync_texture_selection_highlight(row_state)
        if row_state is None:
            texture_detail_browser.setHtml(
                "<html><body style='color:#8b949e; background:#1f1f1f; font-size:0.8em;'>"
                "Select a texture role to inspect parameter, source, original DDS, final behavior, and warnings."
                "</body></html>"
            )
        else:
            row_state["_assigned_count"] = details_state.assigned_count
            row_state["_target_row_count"] = details_state.target_row_count
            texture_detail_browser.setHtml(
                _diagnostics_for_target_html(details_state.target_name, row_state)
                if details_state.target_name
                else ""
            )

    def _set_texture_row_assignment(row_state: Dict[str, Any], source_path: str, checked: bool) -> None:
        if _active_mesh_edit_texture_table_mutation_blocked():
            return
        _set_texture_row_assignment_helper(
            row_state,
            texture_override_assignments,
            texture_overrides_dirty,
            source_path=source_path,
            checked=checked,
        )

    def _update_texture_summary_label(visible_count: Optional[int] = None) -> None:
        summary_visible_count, assigned_count, advanced_hidden, total_count = _texture_summary_metrics(
            texture_override_rows,
            visible_count=visible_count,
            visible_predicate=lambda state: _texture_row_visible_helper(
                state,
                show_advanced=bool(texture_show_advanced_checkbox.isChecked()),
                filter_selected=bool(texture_filter_selected_checkbox.isChecked()),
                selected_source_index=int(selected_source_part.get("index", -1)),
            ),
            assigned_predicate=texture_row_assigned,
            show_advanced=bool(texture_show_advanced_checkbox.isChecked()),
        )
        texture_summary_label.setText(
            _texture_summary_label_html(
                visible_count=summary_visible_count,
                assigned_count=assigned_count,
                total_count=total_count,
                advanced_hidden=advanced_hidden,
            )
        )

    def _apply_texture_row_to_item(item: QTreeWidgetItem, row_state: Dict[str, Any]) -> None:
        _apply_texture_row_to_item_helper(
            item,
            row_state,
            sync_assignment=sync_texture_row_assignment,
            source_summary=texture_row_source_summary,
            source_summary_tooltip=lambda state: texture_row_source_summary(state, limit=20),
            effective_source=texture_row_effective_source,
            assigned=texture_row_assigned,
            status_color_for_label=_texture_plan_status_color,
        )

    def _refresh_texture_row_in_place(row_state: Dict[str, Any], *, sync_editor: bool = True) -> bool:
        item = texture_override_tree.currentItem()
        if item is None or item.data(0, Qt.UserRole + 1) is not row_state:
            item = _texture_item_for_row_helper(texture_override_tree, row_state)
        if item is None:
            return False
        selected_texture_row["row"] = row_state
        texture_override_tree.blockSignals(True)
        try:
            texture_override_tree.setCurrentItem(item)
            _apply_texture_row_to_item(item, row_state)
        finally:
            texture_override_tree.blockSignals(False)
        _update_texture_summary_label()
        _refresh_texture_details(row_state, sync_editor=sync_editor)
        texture_override_tree.scrollToItem(item, QAbstractItemView.EnsureVisible)
        return True

    def _refresh_texture_table(
        preserve_row: Optional[Dict[str, Any]] = None,
        *,
        select_first: bool = False,
    ) -> None:
        if preserve_row is None:
            preserve_row = selected_texture_row.get("row")
        previous_scroll_value = texture_override_tree.verticalScrollBar().value()
        texture_busy_bar.setFormat("Updating texture assignments...")
        texture_busy_bar.setVisible(True)
        QApplication.processEvents()
        texture_override_tree.blockSignals(True)
        try:
            _refresh_alignment_virtual_sidecar_contract(_current_dialog_mappings_for_preview())
            texture_override_tree.clear()
            visible_rows = [
                row_state
                for row_state in sorted(
                    texture_override_rows,
                    key=lambda row_state: _texture_override_row_sort_key(
                        row_state,
                        texture_rows_by_target,
                        assigned_predicate=texture_row_assigned,
                    ),
                )
                if _texture_row_visible_helper(
                    row_state,
                    show_advanced=bool(texture_show_advanced_checkbox.isChecked()),
                    filter_selected=bool(texture_filter_selected_checkbox.isChecked()),
                    selected_source_index=int(selected_source_part.get("index", -1)),
                )
            ]
            _update_texture_summary_label(len(visible_rows))
            item_to_select: Optional[QTreeWidgetItem] = None
            for row_state in visible_rows:
                item = _texture_override_item_helper()
                _apply_texture_row_to_item(item, row_state)
                texture_override_tree.addTopLevelItem(item)
                if preserve_row is row_state:
                    item_to_select = item
            texture_override_tree.blockSignals(False)
            if item_to_select is not None:
                texture_override_tree.setCurrentItem(item_to_select)
                selected_texture_row["row"] = item_to_select.data(0, Qt.UserRole + 1)
                texture_override_tree.scrollToItem(item_to_select, QAbstractItemView.EnsureVisible)
            else:
                selected_texture_row["row"] = None
                texture_override_tree.clearSelection()
                texture_override_tree.setCurrentIndex(QModelIndex())
                texture_override_tree.verticalScrollBar().setValue(previous_scroll_value)
            _refresh_texture_details(selected_texture_row.get("row"))
            texture_override_tree.setMinimumHeight(320)
            texture_override_tree.setMaximumHeight(16777215)
            _auto_fit_alignment_tree_columns(
                texture_override_tree,
                (120, 150, 90, 180, 220, 96, 180),
                (220, 280, 180, 340, 420, 140, 360),
                expand_column=4,
            )
        finally:
            texture_override_tree.blockSignals(False)
            texture_busy_bar.setVisible(False)

    def _texture_table_selection_changed(*_args: object) -> None:
        selected_texture_row["row"] = _current_texture_row()
        _refresh_texture_details(selected_texture_row.get("row"))

    def _selected_texture_role_changed(*_args: object) -> None:
        if selected_texture_editor_loading["active"]:
            return
        row_state = _current_texture_row()
        if row_state is None:
            return
        row_state["slot_kind"] = str(selected_role_combo.currentData() or "material")
        row_state["role_label"] = _texture_role_label_for_slot(str(row_state.get("slot_kind", "") or "material"))
        selected_texture_row["row"] = row_state
        _refresh_texture_row_guidance()
        _refresh_texture_table(row_state)
        _queue_texture_preview_refresh()

    def _commit_texture_row_source(row_state: Dict[str, Any], source_path: str, *, sync_editor: bool = True) -> None:
        if selected_texture_source_committing["active"]:
            return
        commit_state = _selected_texture_source_commit_state_helper(
            source_path,
            current_source=texture_row_effective_source(row_state),
            current_checked=texture_row_assigned(row_state),
        )
        selected_texture_source_committing["active"] = True
        try:
            if commit_state.changed:
                _set_texture_row_assignment(row_state, commit_state.source_path, commit_state.desired_checked)
            selected_texture_row["row"] = row_state
            if not _refresh_texture_row_in_place(row_state, sync_editor=sync_editor):
                _refresh_texture_table(row_state)
            if not sync_editor:
                editor_state = _selected_texture_editor_state_helper(
                    row_state,
                    source_choices=texture_source_choices_for_row,
                    effective_source=texture_row_effective_source,
                    source_summary=texture_row_source_summary,
                    source_summary_tooltip=lambda state: texture_row_source_summary(state, limit=20),
                )
                selected_apply_suggestion_button.setText(editor_state.suggestion_button_text)
                selected_apply_suggestion_button.setEnabled(editor_state.suggestion_available)
                selected_apply_suggestion_button.setToolTip(editor_state.suggestion_tooltip)
        finally:
            selected_texture_source_committing["active"] = False
        if commit_state.changed:
            _queue_texture_preview_refresh()

    def _selected_texture_source_changed(index: int = -1, *_args: object) -> None:
        if selected_texture_editor_loading["active"] or selected_texture_source_committing["active"]:
            return
        row_state = _current_texture_row()
        if row_state is None:
            return
        combo_state = _selected_texture_source_combo_change_state_helper(
            index,
            current_index=selected_source_combo.currentIndex,
            count=selected_source_combo.count,
            item_data=selected_source_combo.itemData,
        )
        row_state = selected_texture_row.get("row") or row_state
        _commit_texture_row_source(row_state, combo_state.source_path, sync_editor=False)

    def _choose_selected_texture_source() -> None:
        if selected_texture_source_committing["active"]:
            return
        row_state = _current_texture_row()
        if row_state is None:
            return
        source_path = _choose_texture_source_dialog_helper(
            dialog,
            row_state,
            texture_source_choices_for_row(row_state),
            texture_row_effective_source(row_state),
            part_label=simplified_part_label,
            role_label_for_slot=_texture_role_label_for_slot,
        )
        if source_path is None:
            return
        _commit_texture_row_source(row_state, source_path)

    def _clear_selected_texture_source() -> None:
        if selected_texture_source_committing["active"]:
            return
        row_state = _current_texture_row()
        if row_state is None:
            return
        _commit_texture_row_source(row_state, "")

    def _apply_selected_texture_suggestion() -> None:
        if selected_texture_source_committing["active"]:
            return
        row_state = _current_texture_row()
        if row_state is None:
            return
        suggested_source = str(row_state.get("suggested_source", "") or "").strip()
        if not suggested_source:
            return
        _commit_texture_row_source(row_state, suggested_source)

    def _texture_table_item_activated(item: Optional[QTreeWidgetItem], column: int) -> None:
        if item is None or int(column) != 4:
            return
        row_state = item.data(0, Qt.UserRole + 1)
        if not isinstance(row_state, dict):
            return
        texture_override_tree.setCurrentItem(item)
        _choose_selected_texture_source()

    def _apply_replacement_texture_plan_to_overrides() -> None:
        if not _ensure_advanced_dds_overrides_loaded(reason="apply-suggested"):
            return
        _refresh_texture_row_guidance()
        apply_state = _suggested_texture_plan_action_state_helper(
            texture_override_rows,
            can_apply=_texture_row_can_apply_suggested_for_target,
        )
        planned_rows = list(apply_state.rows)
        if not _confirm_texture_assignment_action(
            str(material_plan_control_text["apply_suggested"]),
            planned_rows,
            reason=str(material_plan_control_text["apply_suggested_reason"]),
        ):
            return
        for row_state, suggested_source, _decision in planned_rows:
            _set_texture_row_assignment(row_state, suggested_source, True)
        _refresh_texture_table(selected_texture_row.get("row"))
        _queue_texture_preview_refresh()

    def _apply_all_suggested_override_sources() -> None:
        if not _ensure_advanced_dds_overrides_loaded(reason="apply-all-suggested"):
            return
        _refresh_texture_row_guidance()
        action_state = _all_suggested_override_sources_action_state_helper(texture_override_rows)
        planned_rows = list(action_state.rows)
        if action_state.message_key == "no_suggestions":
            QMessageBox.information(
                dialog,
                str(advanced_dds_control_text["no_suggestions_title"]),
                str(advanced_dds_control_text["no_suggestions_message"]),
            )
            return
        if not _confirm_texture_assignment_action(
            str(advanced_dds_control_text["apply_all_button"]),
            planned_rows,
            reason=str(advanced_dds_control_text["apply_all_reason"]),
        ):
            return
        for row_state, suggested_source, _decision in planned_rows:
            _set_texture_row_assignment(row_state, suggested_source, True)
        _refresh_texture_table(selected_texture_row.get("row"))
        _queue_texture_preview_refresh()

    def _clear_target_texture_assignments() -> None:
        if not _ensure_advanced_dds_overrides_loaded(reason="clear-target"):
            return
        clear_state = _target_texture_clear_assignment_state_helper(
            texture_rows_by_target,
            _current_texture_target_name(),
        )
        for row_state in clear_state.rows:
            _set_texture_row_assignment(row_state, "", False)
        _refresh_texture_table(selected_texture_row.get("row"))
        _queue_texture_preview_refresh()

    def _selected_material_override_rows() -> List[Dict[str, Any]]:
        if not _ensure_advanced_dds_overrides_loaded(reason="material-route"):
            return []
        return list(
            _selected_material_override_rows_helper(
                texture_override_rows,
                selected_texture_plan_source,
                texture_row_current_source_indices=texture_row_current_source_indices,
            )
        )

    def _clear_selected_material_texture_assignments() -> None:
        clear_state = _selected_material_texture_clear_action_state_helper(_selected_material_override_rows())
        if clear_state.message_key == "select_route":
            QMessageBox.information(
                dialog,
                str(material_plan_control_text["texture_route_title"]),
                str(material_plan_control_text["texture_route_select_first"]),
            )
            return
        for row_state in clear_state.rows:
            _set_texture_row_assignment(row_state, "", False)
        _refresh_texture_table(selected_texture_row.get("row"))
        _queue_texture_preview_refresh()

    def _choose_file_for_selected_material() -> None:
        rows = _selected_material_override_rows()
        initial_state = _selected_material_texture_clear_action_state_helper(rows)
        if initial_state.message_key == "select_route":
            QMessageBox.information(
                dialog,
                str(material_plan_control_text["texture_route_title"]),
                str(material_plan_control_text["texture_route_select_first"]),
            )
            return
        selected_file, _selected_filter = QFileDialog.getOpenFileName(
            dialog,
            str(material_plan_control_text["choose_route_texture_title"]),
            str(obj_path.parent),
            str(material_plan_control_text["texture_file_filter"]),
        )
        file_state = _selected_material_texture_file_action_state_helper(
            rows,
            selected_file,
            is_file=lambda path: path.is_file(),
        )
        if file_state.message_key in {"cancelled", "missing_file"}:
            return
        for row_state in file_state.rows:
            _set_texture_row_assignment(row_state, file_state.texture_path, True)
        _register_texture_source_file_helper(
            Path(file_state.texture_path),
            texture_files_for_mapping=texture_files_for_mapping,
            seen_texture_file_keys=seen_texture_file_keys,
        )
        _refresh_texture_row_guidance()
        _refresh_texture_table(selected_texture_row.get("row"))
        _queue_texture_preview_refresh()

    return SimpleNamespace(
        _sync_texture_selection_highlight=_sync_texture_selection_highlight,
        _diagnostics_for_target_html=_diagnostics_for_target_html,
        _current_texture_row=_current_texture_row,
        _current_texture_target_name=_current_texture_target_name,
        _sync_selected_texture_editor=_sync_selected_texture_editor,
        _refresh_texture_details=_refresh_texture_details,
        _set_texture_row_assignment=_set_texture_row_assignment,
        _update_texture_summary_label=_update_texture_summary_label,
        _apply_texture_row_to_item=_apply_texture_row_to_item,
        _refresh_texture_row_in_place=_refresh_texture_row_in_place,
        _refresh_texture_table=_refresh_texture_table,
        _texture_table_selection_changed=_texture_table_selection_changed,
        _selected_texture_role_changed=_selected_texture_role_changed,
        _commit_texture_row_source=_commit_texture_row_source,
        _selected_texture_source_changed=_selected_texture_source_changed,
        _choose_selected_texture_source=_choose_selected_texture_source,
        _clear_selected_texture_source=_clear_selected_texture_source,
        _apply_selected_texture_suggestion=_apply_selected_texture_suggestion,
        _texture_table_item_activated=_texture_table_item_activated,
        _apply_replacement_texture_plan_to_overrides=_apply_replacement_texture_plan_to_overrides,
        _apply_all_suggested_override_sources=_apply_all_suggested_override_sources,
        _clear_target_texture_assignments=_clear_target_texture_assignments,
        _selected_material_override_rows=_selected_material_override_rows,
        _clear_selected_material_texture_assignments=_clear_selected_material_texture_assignments,
        _choose_file_for_selected_material=_choose_file_for_selected_material,
    )
