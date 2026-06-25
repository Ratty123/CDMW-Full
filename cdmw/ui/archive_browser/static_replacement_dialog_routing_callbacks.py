"""Routing and selection callback factories for static replacement dialog."""

from __future__ import annotations

from types import SimpleNamespace


def create_alignment_dialog_layout_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Callable = context.get('Callable')
    QSizePolicy = context.get('QSizePolicy')
    QTimer = context.get('QTimer')
    Qt = context.get('Qt')
    _alignment_dialog_responsive_layout_helper = context.get('_alignment_dialog_responsive_layout_helper')
    _alignment_dialog_widgets_live = context.get('_alignment_dialog_widgets_live')
    _preview_performance_status_helper = context.get('_preview_performance_status_helper')
    _qt_object_is_valid = context.get('_qt_object_is_valid')
    _queue_selection_preview_refresh = context.get('_queue_selection_preview_refresh')
    _queue_static_preview_rebuild = context.get('_queue_static_preview_rebuild')
    _queue_texture_preview_refresh = context.get('_queue_texture_preview_refresh')
    _queue_texture_uv_preview_refresh = context.get('_queue_texture_uv_preview_refresh')
    _refresh_mesh_editor_diagnostics = context.get('_refresh_mesh_editor_diagnostics')
    _static_preview_batch_begin_helper = context.get('_static_preview_batch_begin_helper')
    _static_preview_batch_end_helper = context.get('_static_preview_batch_end_helper')
    alignment_control_content_min_width = context.get('alignment_control_content_min_width')
    alignment_control_min_width = context.get('alignment_control_min_width')
    alignment_dialog_layout_state = context.get('alignment_dialog_layout_state')
    alignment_preview_min_width = context.get('alignment_preview_min_width')
    batch_requests = context.get('batch_requests')
    callback = context.get('callback')
    content_container = context.get('content_container')
    control_tabs = context.get('control_tabs')
    controls_panel = context.get('controls_panel')
    details = context.get('details')
    dialog = context.get('dialog')
    embedded_alignment_builder = context.get('embedded_alignment_builder')
    event = context.get('event')
    force_sizes = context.get('force_sizes')
    height = context.get('height')
    layout_spec = context.get('layout_spec')
    main_orientation = context.get('main_orientation')
    main_splitter = context.get('main_splitter')
    mesh_edit_control_content_min_width = context.get('mesh_edit_control_content_min_width')
    mesh_edit_control_max_width = context.get('mesh_edit_control_max_width')
    mesh_edit_control_min_width = context.get('mesh_edit_control_min_width')
    mesh_edit_tab = context.get('mesh_edit_tab')
    mesh_edit_tools_active = context.get('mesh_edit_tools_active')
    policy_by_name = context.get('policy_by_name')
    presentation = context.get('presentation')
    preview_orientation = context.get('preview_orientation')
    preview_panel = context.get('preview_panel')
    preview_performance_label = context.get('preview_performance_label')
    preview_splitter = context.get('preview_splitter')
    previous_dialog_resize_event = context.get('previous_dialog_resize_event')
    static_preview_batch_state = context.get('static_preview_batch_state')
    summary = context.get('summary')
    wants_rebuild = context.get('wants_rebuild')
    wants_refresh = context.get('wants_refresh')
    wants_texture = context.get('wants_texture')
    wants_texture_uv = context.get('wants_texture_uv')
    width = context.get('width')

    def _set_preview_performance_status(summary: str, *, details: str = "") -> None:
        presentation = _preview_performance_status_helper(summary, details=details)
        preview_performance_label.setText(presentation.text)
        preview_performance_label.setToolTip(presentation.tooltip)
        try:
            _refresh_mesh_editor_diagnostics(auto=True)
        except NameError:
            pass

    def _apply_alignment_dialog_responsive_layout(*, force_sizes: bool = False) -> None:
        if not _alignment_dialog_widgets_live() or not _qt_object_is_valid(main_splitter):
            return
        width = max(1, int(dialog.width()))
        height = max(1, int(dialog.height()))
        try:
            mesh_edit_tools_active = control_tabs.widget(control_tabs.currentIndex()) is mesh_edit_tab
        except Exception:
            mesh_edit_tools_active = False
        layout_spec = _alignment_dialog_responsive_layout_helper(
            alignment_dialog_layout_state,
            width=width,
            height=height,
            embedded=bool(embedded_alignment_builder),
            force_sizes=force_sizes,
            mesh_edit_tools_active=mesh_edit_tools_active,
            alignment_control_min_width=alignment_control_min_width,
            alignment_control_content_min_width=alignment_control_content_min_width,
            alignment_preview_min_width=alignment_preview_min_width,
            mesh_edit_control_min_width=mesh_edit_control_min_width,
            mesh_edit_control_content_min_width=mesh_edit_control_content_min_width,
            mesh_edit_control_max_width=mesh_edit_control_max_width,
        )
        main_orientation = Qt.Horizontal if layout_spec.main_orientation == "horizontal" else Qt.Vertical
        preview_orientation = Qt.Horizontal if layout_spec.preview_orientation == "horizontal" else Qt.Vertical
        if main_splitter.orientation() != main_orientation:
            main_splitter.setOrientation(main_orientation)
        if preview_splitter.orientation() != preview_orientation:
            preview_splitter.setOrientation(preview_orientation)
        policy_by_name = {
            "fixed": QSizePolicy.Fixed,
            "minimum_expanding": QSizePolicy.MinimumExpanding,
            "preferred": QSizePolicy.Preferred,
        }
        controls_panel.setVisible(True)
        main_splitter.setHandleWidth(layout_spec.main_handle_width)
        main_splitter.setCollapsible(0, False)
        main_splitter.setCollapsible(1, False)
        main_splitter.setStretchFactor(0, layout_spec.main_stretch[0])
        main_splitter.setStretchFactor(1, layout_spec.main_stretch[1])
        controls_panel.setSizePolicy(policy_by_name[layout_spec.controls_policy], QSizePolicy.Expanding)
        content_container.setSizePolicy(policy_by_name[layout_spec.content_policy], QSizePolicy.Expanding)
        controls_panel.setMinimumWidth(layout_spec.controls_min_width)
        content_container.setMinimumWidth(layout_spec.content_min_width)
        controls_panel.setMaximumWidth(layout_spec.controls_max_width)
        content_container.setMaximumWidth(layout_spec.content_max_width)
        preview_panel.setMinimumWidth(layout_spec.preview_min_width)
        if layout_spec.main_sizes is not None:
            main_splitter.setSizes(list(layout_spec.main_sizes))
        if layout_spec.preview_sizes is not None:
            preview_splitter.setSizes(list(layout_spec.preview_sizes))

    def _responsive_dialog_resize_event(event: object) -> None:
        if not _alignment_dialog_widgets_live():
            return
        if callable(previous_dialog_resize_event):
            previous_dialog_resize_event(event)
        QTimer.singleShot(0, _apply_alignment_dialog_responsive_layout)

    def _run_static_preview_batch(callback: Callable[[], None]) -> None:
        _static_preview_batch_begin_helper(static_preview_batch_state)
        try:
            callback()
        finally:
            batch_requests = _static_preview_batch_end_helper(static_preview_batch_state)
        if batch_requests is None:
            return
        wants_texture = bool(batch_requests.get("texture"))
        wants_texture_uv = bool(batch_requests.get("texture_uv"))
        wants_rebuild = bool(batch_requests.get("rebuild"))
        wants_refresh = bool(batch_requests.get("refresh"))
        if wants_texture:
            _queue_texture_preview_refresh()
        elif wants_texture_uv:
            _queue_texture_uv_preview_refresh()
        elif wants_rebuild:
            _queue_static_preview_rebuild()
        elif wants_refresh:
            _queue_selection_preview_refresh()

    return SimpleNamespace(
        _set_preview_performance_status=_set_preview_performance_status,
        _apply_alignment_dialog_responsive_layout=_apply_alignment_dialog_responsive_layout,
        _responsive_dialog_resize_event=_responsive_dialog_resize_event,
        _run_static_preview_batch=_run_static_preview_batch,
    )


def create_alignment_original_texture_intent_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Dict = context.get('Dict')
    List = context.get('List')
    Path = context.get('Path')
    _archive_dds_preview_source_for_path = context.get('_archive_dds_preview_source_for_path')
    _binding_matches_target = context.get('_binding_matches_target')
    _copied_original_dds_badge_helper = context.get('_copied_original_dds_badge_helper')
    _copied_original_texture_tooltip_helper = context.get('_copied_original_texture_tooltip_helper')
    _matches_target = context.get('_matches_target')
    _original_index_from_tree_item = context.get('_original_index_from_tree_item')
    _original_part_texture_intent_rows_helper = context.get('_original_part_texture_intent_rows_helper')
    _original_target_label = context.get('_original_target_label')
    _preview_source_for_path = context.get('_preview_source_for_path')
    binding = context.get('binding')
    binding_names = context.get('binding_names')
    classify_texture_binding = context.get('classify_texture_binding')
    copied_original_texture_disabled_sources = context.get('copied_original_texture_disabled_sources')
    copied_original_texture_intents_by_source = context.get('copied_original_texture_intents_by_source')
    name = context.get('name')
    original_index = context.get('original_index')
    original_mesh_for_mapping = context.get('original_mesh_for_mapping')
    original_tree = context.get('original_tree')
    rows = context.get('rows')
    selected_items = context.get('selected_items')
    selected_original_part = context.get('selected_original_part')
    sidecar_bindings = context.get('sidecar_bindings')
    source_index = context.get('source_index')
    target_key = context.get('target_key')
    target_name = context.get('target_name')
    texture_path = context.get('texture_path')

    def _selected_original_index_from_tree() -> int:
        source_index = _original_index_from_tree_item(original_tree.currentItem())
        if source_index >= 0:
            return source_index
        selected_items = original_tree.selectedItems()
        return _original_index_from_tree_item(selected_items[0]) if selected_items else int(selected_original_part.get("index", -1))

    def _original_part_texture_intent_rows(original_index: int) -> List[Dict[str, str]]:
        if not callable(_original_part_texture_intent_rows_helper):
            return []

        def _preview_source_for_path(texture_path: str) -> Path | None:
            try:
                return _archive_dds_preview_source_for_path(texture_path)
            except NameError:
                return None

        def _matches_target(binding: object, target_name: str) -> bool:
            try:
                if callable(_binding_matches_target):
                    return _binding_matches_target(binding, target_name)
            except NameError:
                pass
            binding_names = (
                str(getattr(binding, "part_name", "") or ""),
                str(getattr(binding, "submesh_name", "") or ""),
                str(getattr(binding, "material_name", "") or ""),
            )
            target_key = target_name.lower()
            return any(name.strip().lower() == target_key for name in binding_names)

        return _original_part_texture_intent_rows_helper(
            original_index,
            original_mesh_for_mapping,
            sidecar_bindings,
            target_label=_original_target_label,
            preview_source_for_path=_preview_source_for_path,
            binding_matches_target=_matches_target,
            classify_texture_binding=classify_texture_binding,
        )

    def _copied_original_texture_tooltip(source_index: int) -> str:
        rows = copied_original_texture_intents_by_source.get(int(source_index), [])
        return _copied_original_texture_tooltip_helper(rows)

    def _copied_original_dds_badge(source_index: int) -> str:
        rows = copied_original_texture_intents_by_source.get(int(source_index), [])
        return _copied_original_dds_badge_helper(
            source_index,
            rows,
            copied_original_texture_disabled_sources,
        )

    return SimpleNamespace(
        _selected_original_index_from_tree=_selected_original_index_from_tree,
        _original_part_texture_intent_rows=_original_part_texture_intent_rows,
        _copied_original_texture_tooltip=_copied_original_texture_tooltip,
        _copied_original_dds_badge=_copied_original_dds_badge,
    )


def create_alignment_original_clipboard_callbacks(context: dict[str, object]) -> SimpleNamespace:
    QMenu = context.get('QMenu')
    QMessageBox = context.get('QMessageBox')
    QPoint = context.get('QPoint')
    _alignment_part_clipboard_can_paste = context.get('_alignment_part_clipboard_can_paste')
    _append_original_part_payload_as_source = context.get('_append_original_part_payload_as_source')
    _copied_original_clipboard_status_message_helper = context.get('_copied_original_clipboard_status_message_helper')
    _copy_original_part_payload = context.get('_copy_original_part_payload')
    _pasted_original_source_status_message_helper = context.get('_pasted_original_source_status_message_helper')
    alignment_part_clipboard = context.get('alignment_part_clipboard')
    chosen = context.get('chosen')
    copy_action = context.get('copy_action')
    dialog = context.get('dialog')
    item = context.get('item')
    menu = context.get('menu')
    new_source_index = context.get('new_source_index')
    original_index = context.get('original_index')
    original_part_clipboard_action_text = context.get('original_part_clipboard_action_text')
    original_tree = context.get('original_tree')
    payload = context.get('payload')
    pos = context.get('pos')
    rows = context.get('rows')
    self = context.get('self')

    def _copy_original_part_to_alignment_clipboard(original_index: int = -1) -> None:
        if original_index < 0:
            original_index = _selected_original_index_from_tree()
        payload = _copy_original_part_payload(original_index)
        if payload is None:
            QMessageBox.information(
                dialog,
                original_part_clipboard_action_text["copy_select_title"],
                original_part_clipboard_action_text["copy_select_message"],
            )
            return
        alignment_part_clipboard.clear()
        alignment_part_clipboard.update(payload)
        rows = tuple(payload.get("texture_rows", ()) or ())
        self.set_status_message(_copied_original_clipboard_status_message_helper(original_index, len(rows)))

    def _paste_alignment_part_clipboard_as_replacement_source() -> None:
        if not _alignment_part_clipboard_can_paste():
            QMessageBox.information(
                dialog,
                original_part_clipboard_action_text["paste_select_title"],
                original_part_clipboard_action_text["paste_select_message"],
            )
            return
        new_source_index = _append_original_part_payload_as_source(
            alignment_part_clipboard,
            assign_to_target=False,
            preview_only=True,
            undo_label=original_part_clipboard_action_text["paste_undo_label"],
        )
        if new_source_index >= 0:
            self.set_status_message(_pasted_original_source_status_message_helper(new_source_index))

    def _show_original_parts_context_menu(pos: QPoint) -> None:
        item = original_tree.itemAt(pos)
        if item is not None:
            original_tree.setCurrentItem(item)
        menu = QMenu(original_tree)
        copy_action = menu.addAction(original_part_clipboard_action_text["copy_part_with_textures"])
        copy_action.setEnabled(_selected_original_index_from_tree() >= 0)
        chosen = menu.exec(original_tree.viewport().mapToGlobal(pos))
        if chosen is copy_action:
            _copy_original_part_to_alignment_clipboard(_selected_original_index_from_tree())

    return SimpleNamespace(
        _copy_original_part_to_alignment_clipboard=_copy_original_part_to_alignment_clipboard,
        _paste_alignment_part_clipboard_as_replacement_source=_paste_alignment_part_clipboard_as_replacement_source,
        _show_original_parts_context_menu=_show_original_parts_context_menu,
    )


def create_alignment_source_tree_role_callbacks(context: dict[str, object]) -> SimpleNamespace:
    QMenu = context.get('QMenu')
    QTreeWidgetItem = context.get('QTreeWidgetItem')
    SOURCE_TREE_ROLE_OPTIONS = context.get('SOURCE_TREE_ROLE_OPTIONS')
    _apply_source_role_selection = context.get('_apply_source_role_selection')
    _auto_fit_alignment_tree_columns = context.get('_auto_fit_alignment_tree_columns')
    _fit_alignment_tree_height_to_rows = context.get('_fit_alignment_tree_height_to_rows')
    _refresh_parts_outliner = context.get('_refresh_parts_outliner')
    _source_index_from_tree_item = context.get('_source_index_from_tree_item')
    _source_tree_population_mark_complete_helper = context.get('_source_tree_population_mark_complete_helper')
    _source_tree_population_ready_text_helper = context.get('_source_tree_population_ready_text_helper')
    _source_tree_role_menu_specs_helper = context.get('_source_tree_role_menu_specs_helper')
    action = context.get('action')
    chosen = context.get('chosen')
    column = context.get('column')
    item = context.get('item')
    label = context.get('label')
    menu = context.get('menu')
    point = context.get('point')
    rect = context.get('rect')
    role_value = context.get('role_value')
    source_index = context.get('source_index')
    source_parts_group = context.get('source_parts_group')
    source_tree = context.get('source_tree')
    source_tree_layout_state = context.get('source_tree_layout_state')
    source_tree_population_state = context.get('source_tree_population_state')
    source_tree_progress_label = context.get('source_tree_progress_label')

    def _open_source_tree_role_dropdown(item: QTreeWidgetItem, column: int) -> None:
        source_index = _source_index_from_tree_item(item)
        if source_index < 0:
            return
        menu = QMenu(source_tree)
        for label, role_value in _source_tree_role_menu_specs_helper(SOURCE_TREE_ROLE_OPTIONS):
            action = menu.addAction(label)
            action.setData(role_value)
        rect = source_tree.visualItemRect(item)
        point = source_tree.viewport().mapToGlobal(rect.bottomLeft())
        chosen = menu.exec(point)
        if chosen is None:
            return
        _apply_source_role_selection(source_index, str(chosen.data() or ""))

    def _handle_source_tree_item_clicked(item: QTreeWidgetItem, column: int) -> None:
        if item is None or int(column) != 3:
            return
        _open_source_tree_role_dropdown(item, column)

    def _finish_source_tree_population() -> None:
        _source_tree_population_mark_complete_helper(source_tree_population_state)
        source_tree_progress_label.setText(
            _source_tree_population_ready_text_helper(source_tree.topLevelItemCount())
        )
        _fit_alignment_tree_height_to_rows(source_tree, **source_tree_layout_state.height_fit_kwargs)
        _auto_fit_alignment_tree_columns(
            source_tree,
            source_tree_layout_state.autofit_min_widths,
            source_tree_layout_state.autofit_max_widths,
            expand_columns=source_tree_layout_state.expand_columns,
        )
        source_parts_group.setMaximumHeight(16777215)
        try:
            _refresh_parts_outliner()
        except NameError:
            pass

    return SimpleNamespace(
        _open_source_tree_role_dropdown=_open_source_tree_role_dropdown,
        _handle_source_tree_item_clicked=_handle_source_tree_item_clicked,
        _finish_source_tree_population=_finish_source_tree_population,
    )


def create_alignment_selection_route_callbacks(context: dict[str, object]) -> SimpleNamespace:
    _parse_mapping_edit = context.get('_parse_mapping_edit')
    _selected_source_index = context.get('_selected_source_index')
    _selected_target_index = context.get('_selected_target_index')
    _set_mapping_indices = context.get('_set_mapping_indices')
    edit = context.get('edit')
    index = context.get('index')
    indices = context.get('indices')
    mapping_edits_by_target = context.get('mapping_edits_by_target')
    source_index = context.get('source_index')
    target_index = context.get('target_index')

    def _assign_selected_source_to_target() -> None:
        source_index = _selected_source_index()
        target_index = _selected_target_index()
        if source_index < 0 or target_index < 0:
            return
        _set_mapping_indices(target_index, [source_index])

    def _merge_selected_source_into_target() -> None:
        source_index = _selected_source_index()
        target_index = _selected_target_index()
        edit = mapping_edits_by_target.get(target_index)
        if source_index < 0 or edit is None:
            return
        indices = _parse_mapping_edit(edit)
        if source_index not in indices:
            indices.append(source_index)
        _set_mapping_indices(target_index, indices)

    def _remove_selected_source_from_target() -> None:
        source_index = _selected_source_index()
        target_index = _selected_target_index()
        edit = mapping_edits_by_target.get(target_index)
        if source_index < 0 or edit is None:
            return
        _set_mapping_indices(
            target_index,
            [index for index in _parse_mapping_edit(edit) if index != source_index],
            defer_preview=True,
        )

    def _clear_selected_target() -> None:
        target_index = _selected_target_index()
        if target_index >= 0:
            _set_mapping_indices(target_index, [], defer_preview=True)

    return SimpleNamespace(
        _assign_selected_source_to_target=_assign_selected_source_to_target,
        _merge_selected_source_into_target=_merge_selected_source_into_target,
        _remove_selected_source_from_target=_remove_selected_source_from_target,
        _clear_selected_target=_clear_selected_target,
    )


def create_alignment_selection_clear_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Mapping = context.get('Mapping')
    QTreeWidget = context.get('QTreeWidget')
    _clear_transform_source_indices = context.get('_clear_transform_source_indices')
    _clear_tree_current_item_helper = context.get('_clear_tree_current_item_helper')
    _load_selected_part_controls = context.get('_load_selected_part_controls')
    _part_selection_clear_scope_state_helper = context.get('_part_selection_clear_scope_state_helper')
    _queue_selection_preview_refresh = context.get('_queue_selection_preview_refresh')
    _refresh_original_reference_preview = context.get('_refresh_original_reference_preview')
    _selection_view_update_kwargs_helper = context.get('_selection_view_update_kwargs_helper')
    _set_mesh_replacement_selection_view = context.get('_set_mesh_replacement_selection_view')
    _sync_highlight_sets = context.get('_sync_highlight_sets')
    _update_mapping_status = context.get('_update_mapping_status')
    _update_selection_context = context.get('_update_selection_context')
    clear_state = context.get('clear_state')
    mapping_tree = context.get('mapping_tree')
    original_tree = context.get('original_tree')
    selected_original_highlight_indices = context.get('selected_original_highlight_indices')
    selected_original_part = context.get('selected_original_part')
    selected_source_highlight_indices = context.get('selected_source_highlight_indices')
    selected_source_part = context.get('selected_source_part')
    selected_target_original_highlight_indices = context.get('selected_target_original_highlight_indices')
    selected_target_slot = context.get('selected_target_slot')
    selected_target_source_highlight_indices = context.get('selected_target_source_highlight_indices')
    selection_payload = context.get('selection_payload')
    source_tree = context.get('source_tree')
    tree = context.get('tree')

    def _clear_tree_current_item(tree: QTreeWidget) -> None:
        _clear_tree_current_item_helper(tree)

    def _apply_part_selection_clear_scope_state(clear_state: Mapping[str, object]) -> None:
        if clear_state.get("selected_source_index") is not None:
            selected_source_part["index"] = int(clear_state["selected_source_index"])
        if clear_state.get("selected_original_index") is not None:
            selected_original_part["index"] = int(clear_state["selected_original_index"])
        if clear_state.get("selected_target_index") is not None:
            selected_target_slot["index"] = int(clear_state["selected_target_index"])
        if clear_state.get("clear_source_highlights"):
            selected_source_highlight_indices.clear()
        if clear_state.get("clear_original_highlights"):
            selected_original_highlight_indices.clear()
        if clear_state.get("clear_target_source_highlights"):
            selected_target_source_highlight_indices.clear()
        if clear_state.get("clear_target_original_highlights"):
            selected_target_original_highlight_indices.clear()
        if clear_state.get("clear_transform_sources"):
            _clear_transform_source_indices()
        selection_payload = clear_state["selection_view"]
        _set_mesh_replacement_selection_view(
            **_selection_view_update_kwargs_helper(selection_payload)  # type: ignore[arg-type]
        )

    def _clear_original_selection() -> None:
        _clear_tree_current_item(original_tree)
        _apply_part_selection_clear_scope_state(_part_selection_clear_scope_state_helper("original"))
        _sync_highlight_sets()
        _refresh_original_reference_preview()
        _update_selection_context()
        _queue_selection_preview_refresh()

    def _clear_replacement_selection() -> None:
        _clear_tree_current_item(source_tree)
        _apply_part_selection_clear_scope_state(_part_selection_clear_scope_state_helper("source"))
        _sync_highlight_sets()
        _load_selected_part_controls()
        _update_mapping_status()
        _update_selection_context()
        _queue_selection_preview_refresh()

    def _clear_target_selection() -> None:
        _clear_tree_current_item(mapping_tree)
        _apply_part_selection_clear_scope_state(_part_selection_clear_scope_state_helper("target"))
        _sync_highlight_sets()
        _refresh_original_reference_preview()
        _load_selected_part_controls()
        _update_mapping_status()
        _update_selection_context()
        _queue_selection_preview_refresh()

    return SimpleNamespace(
        _clear_tree_current_item=_clear_tree_current_item,
        _apply_part_selection_clear_scope_state=_apply_part_selection_clear_scope_state,
        _clear_original_selection=_clear_original_selection,
        _clear_replacement_selection=_clear_replacement_selection,
        _clear_target_selection=_clear_target_selection,
    )


def create_alignment_source_part_transform_control_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Optional = context.get('Optional')
    QDoubleSpinBox = context.get('QDoubleSpinBox')
    QSlider = context.get('QSlider')
    _make_spinbox_slider_helper = context.get('_make_spinbox_slider_helper')
    part_offset_x_spin = context.get('part_offset_x_spin')
    part_offset_y_spin = context.get('part_offset_y_spin')
    part_offset_z_spin = context.get('part_offset_z_spin')
    part_rotate_x_spin = context.get('part_rotate_x_spin')
    part_rotate_y_spin = context.get('part_rotate_y_spin')
    part_rotate_z_spin = context.get('part_rotate_z_spin')
    part_transform_sliders = context.get('part_transform_sliders')
    scale = context.get('scale')
    slider = context.get('slider')
    slider_maximum = context.get('slider_maximum')
    slider_minimum = context.get('slider_minimum')
    slider_value = context.get('slider_value')
    spin = context.get('spin')
    tooltip = context.get('tooltip')

    def _part_transform_slider(
        spin: QDoubleSpinBox,
        *,
        scale: float,
        tooltip: str,
        slider_minimum: Optional[float] = None,
        slider_maximum: Optional[float] = None,
    ) -> QSlider:
        slider = _make_spinbox_slider_helper(
            spin,
            scale=scale,
            tooltip=tooltip,
            object_name="AlignmentPartTransformSlider",
            minimum_width=72,
            slider_minimum=slider_minimum,
            slider_maximum=slider_maximum,
        )
        part_transform_sliders[spin] = slider
        return slider

    def _sync_part_slider_from_spin(spin: QDoubleSpinBox) -> None:
        slider = part_transform_sliders.get(spin)
        if slider is None:
            return
        scale = 2000.0 if spin in (part_offset_x_spin, part_offset_y_spin, part_offset_z_spin) else 10.0 if spin in (part_rotate_x_spin, part_rotate_y_spin, part_rotate_z_spin) else 1000.0
        slider_value = int(round(float(spin.value()) * scale))
        if slider.value() == slider_value:
            return
        slider.blockSignals(True)
        slider.setValue(slider_value)
        slider.blockSignals(False)

    return SimpleNamespace(
        _part_transform_slider=_part_transform_slider,
        _sync_part_slider_from_spin=_sync_part_slider_from_spin,
    )


def create_alignment_source_part_glow_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Optional = context.get('Optional')
    StaticSourcePartAdjustment = context.get('StaticSourcePartAdjustment')
    _complete_external_swap_enabled = context.get('_complete_external_swap_enabled')
    _source_part_glow_color_controls_state_helper = context.get('_source_part_glow_color_controls_state_helper')
    _source_part_glow_rgb_helper = context.get('_source_part_glow_rgb_helper')
    adjustment = context.get('adjustment')
    can_override = context.get('can_override')
    controls_ready = context.get('controls_ready')
    controls_state = context.get('controls_state')
    part_glow_color_checkbox = context.get('part_glow_color_checkbox')
    part_glow_color_pick_button = context.get('part_glow_color_pick_button')
    part_glow_color_spins = context.get('part_glow_color_spins')
    spin = context.get('spin')

    prompt_shell_context = context.get('prompt_shell_context')

    def _prompt_context_value(name: str) -> object:
        if isinstance(prompt_shell_context, dict) and name in prompt_shell_context:
            return prompt_shell_context.get(name)
        return context.get(name)

    def _part_glow_color_checkbox() -> object:
        return _prompt_context_value('part_glow_color_checkbox')

    def _part_glow_color_pick_button() -> object:
        return _prompt_context_value('part_glow_color_pick_button')

    def _part_glow_color_spins() -> tuple[object, ...]:
        spins = _prompt_context_value('part_glow_color_spins')
        if not isinstance(spins, (list, tuple)):
            return ()
        return tuple(
            spin
            for spin in spins
            if callable(getattr(spin, "value", None))
        )

    def _selected_part_glow_rgb_from_controls() -> tuple[int, int, int]:
        values = tuple(spin.value() for spin in _part_glow_color_spins())
        if callable(_source_part_glow_rgb_helper):
            return _source_part_glow_rgb_helper(values)
        return (0, 0, 0)

    def _sync_part_glow_color_button() -> None:
        spins = _part_glow_color_spins()
        checkbox = _part_glow_color_checkbox()
        pick_button = _part_glow_color_pick_button()
        if not spins or checkbox is None or pick_button is None:
            return
        controls_state = _source_part_glow_color_controls_state_helper(
            rgb=_selected_part_glow_rgb_from_controls(),
            complete_external_swap_enabled=True,
            checked=checkbox.isChecked(),
            checkbox_enabled=checkbox.isEnabled(),
        )
        pick_button.setText(controls_state.color_text)
        pick_button.setStyleSheet(controls_state.style_sheet)

    def _refresh_part_glow_color_controls_enabled() -> None:
        spins = _part_glow_color_spins()
        checkbox = _part_glow_color_checkbox()
        pick_button = _part_glow_color_pick_button()
        if not spins or checkbox is None or pick_button is None:
            return
        try:
            can_override = bool(_complete_external_swap_enabled())
        except Exception:
            can_override = True
        checkbox.setEnabled(can_override)
        controls_state = _source_part_glow_color_controls_state_helper(
            rgb=_selected_part_glow_rgb_from_controls(),
            complete_external_swap_enabled=can_override,
            checked=checkbox.isChecked(),
            checkbox_enabled=checkbox.isEnabled(),
        )
        for spin in spins:
            spin.setEnabled(controls_state.enabled)
        pick_button.setEnabled(controls_state.enabled)
        _sync_part_glow_color_button()

    def _load_part_glow_color_controls(adjustment: Optional[StaticSourcePartAdjustment]) -> None:
        _ = adjustment
        _refresh_part_glow_color_controls_enabled()

    return SimpleNamespace(
        _selected_part_glow_rgb_from_controls=_selected_part_glow_rgb_from_controls,
        _sync_part_glow_color_button=_sync_part_glow_color_button,
        _refresh_part_glow_color_controls_enabled=_refresh_part_glow_color_controls_enabled,
        _load_part_glow_color_controls=_load_part_glow_color_controls,
    )


def create_alignment_source_part_geometry_action_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Path = context.get('Path')
    SCENE_TEXTURE_SOURCE_EXTENSIONS = context.get('SCENE_TEXTURE_SOURCE_EXTENSIONS')
    Sequence = context.get('Sequence')
    _ensure_source_part_adjustment = context.get('_ensure_source_part_adjustment')
    _load_selected_part_controls = context.get('_load_selected_part_controls')
    _push_geometry_undo_snapshot = context.get('_push_geometry_undo_snapshot')
    _queue_static_preview_rebuild = context.get('_queue_static_preview_rebuild')
    _reference_vertices_for_appended_part = context.get('_reference_vertices_for_appended_part')
    _register_dialog_supplemental_file_helper = context.get('_register_dialog_supplemental_file_helper')
    _selected_target_index = context.get('_selected_target_index')
    _set_double_spin_value_silently_helper = context.get('_set_double_spin_value_silently_helper')
    _source_part_appended_work_area_fit_state_helper = context.get('_source_part_appended_work_area_fit_state_helper')
    _source_part_center_on_target_state_helper = context.get('_source_part_center_on_target_state_helper')
    _source_part_edit_undo_label_helper = context.get('_source_part_edit_undo_label_helper')
    _source_part_fit_size_state_helper = context.get('_source_part_fit_size_state_helper')
    _source_part_nudge_delta_helper = context.get('_source_part_nudge_delta_helper')
    _transformed_vertices_for_work_area = context.get('_transformed_vertices_for_work_area')
    _update_selected_part_adjustment = context.get('_update_selected_part_adjustment')
    adjustment = context.get('adjustment')
    axis = context.get('axis')
    center_state = context.get('center_state')
    delta = context.get('delta')
    dialog_added_supplemental_files = context.get('dialog_added_supplemental_files')
    direction = context.get('direction')
    dx = context.get('dx')
    dy = context.get('dy')
    dz = context.get('dz')
    fit_state = context.get('fit_state')
    mesh = context.get('mesh')
    original_mesh_for_mapping = context.get('original_mesh_for_mapping')
    part_nudge_step_spin = context.get('part_nudge_step_spin')
    part_offset_x_spin = context.get('part_offset_x_spin')
    part_offset_y_spin = context.get('part_offset_y_spin')
    part_offset_z_spin = context.get('part_offset_z_spin')
    path = context.get('path')
    refresh_parsed_mesh_totals = context.get('refresh_parsed_mesh_totals')
    replacement_mesh_base_for_mapping = context.get('replacement_mesh_base_for_mapping')
    replacement_mesh_for_mapping = context.get('replacement_mesh_for_mapping')
    selected_source_part = context.get('selected_source_part')
    source_index = context.get('source_index')
    source_indices = context.get('source_indices')
    spin = context.get('spin')
    submesh = context.get('submesh')
    supplemental_files = context.get('supplemental_files')
    texture_files_for_mapping = context.get('texture_files_for_mapping')
    value = context.get('value')

    def _normalize_appended_part_to_work_area(source_indices: Sequence[int]) -> str:
        if replacement_mesh_for_mapping is None or replacement_mesh_base_for_mapping is None:
            return ""
        fit_state = _source_part_appended_work_area_fit_state_helper(
            source_indices=source_indices,
            source_count=len(replacement_mesh_for_mapping.submeshes),
            replacement_mesh=replacement_mesh_for_mapping,
            reference_vertices=_reference_vertices_for_appended_part(),
        )
        if not fit_state.should_apply or fit_state.fit is None:
            return ""

        for mesh in (replacement_mesh_for_mapping, replacement_mesh_base_for_mapping):
            for source_index in fit_state.source_indices:
                if 0 <= source_index < len(mesh.submeshes):
                    submesh = mesh.submeshes[source_index]
                    submesh.vertices = _transformed_vertices_for_work_area(submesh.vertices or [], fit_state.fit)
                    submesh.vertex_count = len(submesh.vertices)
                    submesh.face_count = len(submesh.faces)
            refresh_parsed_mesh_totals(mesh)
        return fit_state.placement_note

    def _fit_selected_part_size() -> None:
        if replacement_mesh_for_mapping is None or original_mesh_for_mapping is None:
            return
        fit_state = _source_part_fit_size_state_helper(
            source_index=int(selected_source_part.get("index", -1)),
            target_index=_selected_target_index(),
            replacement_mesh=replacement_mesh_for_mapping,
            original_mesh=original_mesh_for_mapping,
        )
        if not fit_state.available or fit_state.uniform_scale is None:
            return
        _push_geometry_undo_snapshot(_source_part_edit_undo_label_helper("fit"))
        adjustment = _ensure_source_part_adjustment(fit_state.source_index)
        adjustment.uniform_scale = fit_state.uniform_scale
        adjustment.scale_xyz = (1.0, 1.0, 1.0)
        _load_selected_part_controls()
        _queue_static_preview_rebuild()

    def _nudge_selected_part(dx: float, dy: float, dz: float) -> None:
        source_index = int(selected_source_part.get("index", -1))
        if source_index < 0:
            return
        _push_geometry_undo_snapshot(_source_part_edit_undo_label_helper("nudge"))
        for spin, delta in (
            (part_offset_x_spin, dx),
            (part_offset_y_spin, dy),
            (part_offset_z_spin, dz),
        ):
            _set_double_spin_value_silently_helper(spin, float(spin.value()) + float(delta))
            _sync_part_slider_from_spin(spin)
        _update_selected_part_adjustment()

    def _nudge_selected_part_axis(axis: str, direction: float) -> None:
        _nudge_selected_part(
            *_source_part_nudge_delta_helper(
                axis,
                float(part_nudge_step_spin.value()),
                direction,
            )
        )

    def _center_selected_part_on_target() -> None:
        if replacement_mesh_for_mapping is None or original_mesh_for_mapping is None:
            return
        center_state = _source_part_center_on_target_state_helper(
            source_index=int(selected_source_part.get("index", -1)),
            target_index=_selected_target_index(),
            replacement_mesh=replacement_mesh_for_mapping,
            original_mesh=original_mesh_for_mapping,
        )
        if not center_state.available or center_state.offset is None:
            return
        _push_geometry_undo_snapshot(_source_part_edit_undo_label_helper("center"))
        for spin, value in (
            (part_offset_x_spin, center_state.offset[0]),
            (part_offset_y_spin, center_state.offset[1]),
            (part_offset_z_spin, center_state.offset[2]),
        ):
            _set_double_spin_value_silently_helper(spin, value)
            _sync_part_slider_from_spin(spin)
        _update_selected_part_adjustment()

    def _add_dialog_supplemental_file(path: Path) -> None:
        _register_dialog_supplemental_file_helper(
            path,
            dialog_added_supplemental_files=dialog_added_supplemental_files,
            supplemental_files=supplemental_files or (),
            texture_files_for_mapping=texture_files_for_mapping,
            allowed_texture_extensions=SCENE_TEXTURE_SOURCE_EXTENSIONS,
        )

    return SimpleNamespace(
        _normalize_appended_part_to_work_area=_normalize_appended_part_to_work_area,
        _fit_selected_part_size=_fit_selected_part_size,
        _nudge_selected_part=_nudge_selected_part,
        _nudge_selected_part_axis=_nudge_selected_part_axis,
        _center_selected_part_on_target=_center_selected_part_on_target,
        _add_dialog_supplemental_file=_add_dialog_supplemental_file,
    )


def create_alignment_complete_swap_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Callable = context.get('Callable')
    List = context.get('List')
    QTimer = context.get('QTimer')
    StaticSubmeshMapping = context.get('StaticSubmeshMapping')
    _alignment_d3d11_live_frame_available = context.get('_alignment_d3d11_live_frame_available')
    _alignment_dialog_widgets_live = context.get('_alignment_dialog_widgets_live')
    _apply_checked_complete_swap = context.get('_apply_checked_complete_swap')
    _call_if_alignment_widgets_live = context.get('_call_if_alignment_widgets_live')
    _is_marker_source = context.get('_is_marker_source')
    _mapped_source_indices = context.get('_mapped_source_indices')
    _mapping_edit_valid_source_indices_helper = context.get('_mapping_edit_valid_source_indices_helper')
    _mapping_table_build_complete_helper = context.get('_mapping_table_build_complete_helper')
    _material_authority_complete_swap_forced_child_states_helper = context.get('_material_authority_complete_swap_forced_child_states_helper')
    _material_authority_complete_swap_next_transition_generation_helper = context.get('_material_authority_complete_swap_next_transition_generation_helper')
    _material_authority_complete_swap_profile_name_helper = context.get('_material_authority_complete_swap_profile_name_helper')
    _material_authority_complete_swap_restored_child_states_helper = context.get('_material_authority_complete_swap_restored_child_states_helper')
    _material_authority_complete_swap_routing_progress_message_helper = context.get('_material_authority_complete_swap_routing_progress_message_helper')
    _material_authority_complete_swap_routing_reason_helper = context.get('_material_authority_complete_swap_routing_reason_helper')
    _material_authority_complete_swap_should_apply_checked_helper = context.get('_material_authority_complete_swap_should_apply_checked_helper')
    _material_authority_complete_swap_source_output_size_index_helper = context.get('_material_authority_complete_swap_source_output_size_index_helper')
    _material_authority_complete_swap_update_performance_helper = context.get('_material_authority_complete_swap_update_performance_helper')
    _material_authority_complete_swap_update_queued_message_helper = context.get('_material_authority_complete_swap_update_queued_message_helper')
    _push_geometry_undo_snapshot = context.get('_push_geometry_undo_snapshot')
    _queue_source_material_plan_refresh = context.get('_queue_source_material_plan_refresh')
    _queue_static_preview_rebuild = context.get('_queue_static_preview_rebuild')
    _queue_texture_preview_refresh = context.get('_queue_texture_preview_refresh')
    _refresh_output_impact_review = context.get('_refresh_output_impact_review')
    _refresh_sidecar_option_state = context.get('_refresh_sidecar_option_state')
    _refresh_source_assignment_columns = context.get('_refresh_source_assignment_columns')
    _refresh_texture_override_tree = context.get('_refresh_texture_override_tree')
    _select_complete_swap_material_profile = context.get('_select_complete_swap_material_profile')
    _semantic_tokens = context.get('_semantic_tokens')
    _set_alignment_d3d11_progress = context.get('_set_alignment_d3d11_progress')
    _set_checkbox_checked_silently_helper = context.get('_set_checkbox_checked_silently_helper')
    _set_combo_index_silently_helper = context.get('_set_combo_index_silently_helper')
    _set_preview_performance_status = context.get('_set_preview_performance_status')
    _source_group_label_or_fallback_helper = context.get('_source_group_label_or_fallback_helper')
    _source_material_group_label = context.get('_source_material_group_label')
    _source_part_assign_material_groups_to_targets_helper = context.get('_source_part_assign_material_groups_to_targets_helper')
    _source_part_group_initial_target_counts_helper = context.get('_source_part_group_initial_target_counts_helper')
    _source_part_group_items_helper = context.get('_source_part_group_items_helper')
    _source_part_material_groups_helper = context.get('_source_part_material_groups_helper')
    _source_renderable_indices_helper = context.get('_source_renderable_indices_helper')
    _target_submesh_display_name_helper = context.get('_target_submesh_display_name_helper')
    _update_mapping_status = context.get('_update_mapping_status')
    _update_selection_context = context.get('_update_selection_context')
    callback = context.get('callback')
    checked = context.get('checked')
    complete_external_swap_checkbox = context.get('complete_external_swap_checkbox')
    complete_swap_material_profile_combo = context.get('complete_swap_material_profile_combo')
    complete_swap_performance = context.get('complete_swap_performance')
    current_profile = context.get('current_profile')
    edit = context.get('edit')
    exc = context.get('exc')
    external_material_reset_checkbox = context.get('external_material_reset_checkbox')
    independent_output_source_indices = context.get('independent_output_source_indices')
    index = context.get('index')
    inject_base_color_checkbox = context.get('inject_base_color_checkbox')
    live_frame_available = context.get('live_frame_available')
    mapped_sources = context.get('mapped_sources')
    mapping = context.get('mapping')
    mapping_edits = context.get('mapping_edits')
    mapping_edits_by_target = context.get('mapping_edits_by_target')
    mapping_table_build_state = context.get('mapping_table_build_state')
    mapping_table_ready = context.get('mapping_table_ready')
    mappings = context.get('mappings')
    message = context.get('message')
    original_mesh_for_mapping = context.get('original_mesh_for_mapping')
    parsed_mappings = context.get('parsed_mappings')
    persist = context.get('persist')
    preview_only_source_indices = context.get('preview_only_source_indices')
    previous_blocked = context.get('previous_blocked')
    previous_states = context.get('previous_states')
    profile_name = context.get('profile_name')
    prune_unmapped_original_dds_checkbox = context.get('prune_unmapped_original_dds_checkbox')
    push_undo = context.get('push_undo')
    rebuild_sidecar_checkbox = context.get('rebuild_sidecar_checkbox')
    render_source_indices = context.get('render_source_indices')
    replacement_mesh_for_mapping = context.get('replacement_mesh_for_mapping')
    source_color_faithful_checkbox = context.get('source_color_faithful_checkbox')
    source_face_counts = context.get('source_face_counts')
    source_groups = context.get('source_groups')
    source_index = context.get('source_index')
    source_indices = context.get('source_indices')
    source_initial_targets = context.get('source_initial_targets')
    source_part_adjustments = context.get('source_part_adjustments')
    suggested_mappings = context.get('suggested_mappings')
    target = context.get('target')
    target_count = context.get('target_count')
    target_index = context.get('target_index')
    target_sources = context.get('target_sources')
    text = context.get('text')
    texture_output_size_combo = context.get('texture_output_size_combo')
    texture_override_assignments = context.get('texture_override_assignments')
    texture_overrides_dirty = context.get('texture_overrides_dirty')
    texture_sets = context.get('texture_sets')
    transition_generation = context.get('transition_generation')

    def _complete_external_swap_mappings() -> List[StaticSubmeshMapping]:
        if original_mesh_for_mapping is None or replacement_mesh_for_mapping is None:
            return list(suggested_mappings or [])
        mapping_table_ready = True
        try:
            mapping_table_ready = _mapping_table_build_complete_helper(mapping_table_build_state)
        except NameError:
            mapping_table_ready = True
        if mapping_edits and mapping_table_ready:
            render_source_indices = set(
                _source_renderable_indices_helper(
                    replacement_mesh_for_mapping,
                    source_part_adjustments,
                    is_marker_source=_is_marker_source,
                    excluded_source_indices=preview_only_source_indices,
                )
            )
            parsed_mappings: List[StaticSubmeshMapping] = []
            for target_index, edit in mapping_edits:
                source_indices = list(_mapping_edit_valid_source_indices_helper(edit, render_source_indices))
                target = original_mesh_for_mapping.submeshes[target_index]
                parsed_mappings.append(
                    StaticSubmeshMapping(
                        target_submesh_index=target_index,
                        target_submesh_name=_target_submesh_display_name_helper(target_index, target),
                        source_submesh_indices=source_indices,
                        target_material_slot_index=target_index,
                        merge_sources=True,
                    )
                )
            if parsed_mappings:
                return parsed_mappings
        source_initial_targets = _source_part_group_initial_target_counts_helper(
            suggested_mappings,
            lambda source_index: _source_material_group_label(int(source_index), texture_sets),
        )
        source_groups, source_face_counts = _source_part_material_groups_helper(
            replacement_mesh_for_mapping,
            source_part_adjustments,
            source_material_group_label=lambda source_index: _source_material_group_label(
                int(source_index),
                texture_sets,
            ),
            source_group_label_or_fallback=_source_group_label_or_fallback_helper,
            is_marker_source=_is_marker_source,
            excluded_source_indices=tuple(preview_only_source_indices),
        )
        target_count = len(original_mesh_for_mapping.submeshes)
        if not source_groups or target_count <= 0:
            return [
                StaticSubmeshMapping(
                    target_submesh_index=target_index,
                    target_submesh_name=_target_submesh_display_name_helper(target_index, target),
                    source_submesh_indices=[],
                    target_material_slot_index=target_index,
                    merge_sources=True,
                )
                for target_index, target in enumerate(original_mesh_for_mapping.submeshes)
            ]
        target_sources, _overflow_groups = _source_part_assign_material_groups_to_targets_helper(
            _source_part_group_items_helper(source_groups, source_face_counts),
            target_count=target_count,
            original_mesh=original_mesh_for_mapping,
            replacement_mesh=replacement_mesh_for_mapping,
            target_display_name=_target_submesh_display_name_helper,
            source_initial_targets=source_initial_targets,
            semantic_tokens=_semantic_tokens,
        )
        return [
            StaticSubmeshMapping(
                target_submesh_index=target_index,
                target_submesh_name=_target_submesh_display_name_helper(target_index, target),
                source_submesh_indices=list(target_sources.get(target_index, [])),
                target_material_slot_index=target_index,
                merge_sources=True,
            )
            for target_index, target in enumerate(original_mesh_for_mapping.submeshes)
        ]

    def _apply_complete_external_swap_routing_to_ui(*, push_undo: bool = True) -> None:
        if not _alignment_dialog_widgets_live():
            return
        def _call_if_alignment_widgets_live(callback: Callable[[], None]) -> None:
            if not _alignment_dialog_widgets_live():
                return
            try:
                callback()
            except RuntimeError as exc:
                message = str(exc)
                if "already deleted" in message or "Internal C++ object" in message:
                    return
                raise

        mappings = _complete_external_swap_mappings()
        live_frame_available = _alignment_d3d11_live_frame_available()
        _set_alignment_d3d11_progress(
            8,
            _material_authority_complete_swap_routing_progress_message_helper(),
            stage="complete_swap_routing",
            active=not live_frame_available,
        )
        if push_undo:
            _push_geometry_undo_snapshot("Apply complete external swap routing")
        for mapping in mappings:
            edit = mapping_edits_by_target.get(int(mapping.target_submesh_index))
            if edit is None:
                continue
            text = ", ".join(str(index) for index in tuple(mapping.source_submesh_indices or ()))
            edit.setText(text)
            edit.setProperty("committed_mapping_text", text)
        mapped_sources = _mapped_source_indices(mappings)
        independent_output_source_indices.difference_update(mapped_sources)
        texture_override_assignments.clear()
        texture_overrides_dirty["dirty"] = True
        if not _alignment_dialog_widgets_live():
            return
        _call_if_alignment_widgets_live(_refresh_source_assignment_columns)
        _call_if_alignment_widgets_live(_update_mapping_status)
        _call_if_alignment_widgets_live(_update_selection_context)
        _call_if_alignment_widgets_live(_queue_static_preview_rebuild)
        try:
            _call_if_alignment_widgets_live(_refresh_texture_override_tree)
        except NameError:
            pass
        _queue_source_material_plan_refresh(
            force_plan=True,
            reason=_material_authority_complete_swap_routing_reason_helper(),
        )
        _call_if_alignment_widgets_live(_refresh_output_impact_review)
        _call_if_alignment_widgets_live(_queue_texture_preview_refresh)

    def _select_complete_swap_material_profile_silently(profile_name: str, *, persist: bool = False) -> None:
        block_signals = getattr(complete_swap_material_profile_combo, "blockSignals", None)
        if not callable(block_signals) or not callable(_select_complete_swap_material_profile):
            return
        previous_blocked = bool(block_signals(True))
        try:
            _select_complete_swap_material_profile(profile_name, persist=persist)
        finally:
            block_signals(previous_blocked)

    def _complete_swap_widgets_live() -> bool:
        return bool(callable(_alignment_dialog_widgets_live) and _alignment_dialog_widgets_live())

    def _complete_swap_refresh_sidecar_options() -> None:
        if callable(_refresh_sidecar_option_state):
            _refresh_sidecar_option_state()

    def _sync_complete_external_swap_mode(checked: bool) -> None:
        if not _complete_swap_widgets_live():
            return
        current_generation = complete_external_swap_checkbox.property("transition_generation")  # type: ignore[name-defined]
        if callable(_material_authority_complete_swap_next_transition_generation_helper):
            transition_generation = _material_authority_complete_swap_next_transition_generation_helper(current_generation)
        else:
            try:
                transition_generation = int(current_generation or 0) + 1
            except (TypeError, ValueError):
                transition_generation = 1
        complete_external_swap_checkbox.setProperty("transition_generation", transition_generation)  # type: ignore[name-defined]
        if callable(_set_alignment_d3d11_progress) and callable(_material_authority_complete_swap_update_queued_message_helper):
            live_frame_available = (
                bool(_alignment_d3d11_live_frame_available())
                if callable(_alignment_d3d11_live_frame_available)
                else False
            )
            _set_alignment_d3d11_progress(
                5,
                _material_authority_complete_swap_update_queued_message_helper(),
                stage="complete_swap_toggle_queued",
                active=not live_frame_available,
            )
        if callable(_material_authority_complete_swap_update_performance_helper) and callable(_set_preview_performance_status):
            complete_swap_performance = _material_authority_complete_swap_update_performance_helper()
            _set_preview_performance_status(
                complete_swap_performance.summary,
                details=complete_swap_performance.details,
            )
        if checked:
            forced_child_states = None
            if callable(_material_authority_complete_swap_forced_child_states_helper):
                forced_child_states = _material_authority_complete_swap_forced_child_states_helper(
                    rebuild_sidecar=rebuild_sidecar_checkbox.isChecked(),  # type: ignore[name-defined]
                    inject_base_color=inject_base_color_checkbox.isChecked(),  # type: ignore[name-defined]
                    source_color_faithful=source_color_faithful_checkbox.isChecked(),  # type: ignore[name-defined]
                    external_material_reset=external_material_reset_checkbox.isChecked(),  # type: ignore[name-defined]
                    prune_unmapped_original_dds=prune_unmapped_original_dds_checkbox.isChecked(),  # type: ignore[name-defined]
                )
            complete_external_swap_checkbox.setProperty(  # type: ignore[name-defined]
                "previous_forced_child_states",
                forced_child_states,
            )
            if callable(_set_checkbox_checked_silently_helper):
                _set_checkbox_checked_silently_helper(rebuild_sidecar_checkbox, True)  # type: ignore[name-defined]
                _set_checkbox_checked_silently_helper(inject_base_color_checkbox, True)  # type: ignore[name-defined]
                _set_checkbox_checked_silently_helper(source_color_faithful_checkbox, True)  # type: ignore[name-defined]
                _set_checkbox_checked_silently_helper(external_material_reset_checkbox, True)  # type: ignore[name-defined]
                _set_checkbox_checked_silently_helper(prune_unmapped_original_dds_checkbox, True)  # type: ignore[name-defined]
            find_data = getattr(texture_output_size_combo, "findData", None)
            if (
                callable(find_data)
                and callable(_set_combo_index_silently_helper)
                and callable(_material_authority_complete_swap_source_output_size_index_helper)
            ):
                _set_combo_index_silently_helper(
                    texture_output_size_combo,  # type: ignore[name-defined]
                    _material_authority_complete_swap_source_output_size_index_helper(
                        find_data("source")
                    ),
                )
            current_data = getattr(complete_swap_material_profile_combo, "currentData", None)
            if callable(current_data) and callable(_material_authority_complete_swap_profile_name_helper):
                current_profile = current_data()
                _select_complete_swap_material_profile_silently(
                    _material_authority_complete_swap_profile_name_helper(current_profile),
                    persist=True,
                )
            _complete_swap_refresh_sidecar_options()

            def _apply_checked_complete_swap() -> None:
                if not _complete_swap_widgets_live():
                    return
                if callable(_material_authority_complete_swap_should_apply_checked_helper) and not _material_authority_complete_swap_should_apply_checked_helper(
                    current_generation=complete_external_swap_checkbox.property("transition_generation"),  # type: ignore[name-defined]
                    expected_generation=transition_generation,
                    checked=complete_external_swap_checkbox.isChecked(),  # type: ignore[name-defined]
                ):
                    return
                _apply_complete_external_swap_routing_to_ui(push_undo=True)

            QTimer.singleShot(0, _apply_checked_complete_swap)
        else:
            previous_states = (
                _material_authority_complete_swap_restored_child_states_helper(
                    complete_external_swap_checkbox.property("previous_forced_child_states")  # type: ignore[name-defined]
                )
                if callable(_material_authority_complete_swap_restored_child_states_helper)
                else None
            )
            if previous_states is not None and callable(_set_checkbox_checked_silently_helper):
                _set_checkbox_checked_silently_helper(rebuild_sidecar_checkbox, previous_states["rebuild_sidecar"])  # type: ignore[name-defined]
                _set_checkbox_checked_silently_helper(inject_base_color_checkbox, previous_states["inject_base_color"])  # type: ignore[name-defined]
                _set_checkbox_checked_silently_helper(source_color_faithful_checkbox, previous_states["source_color_faithful"])  # type: ignore[name-defined]
                _set_checkbox_checked_silently_helper(external_material_reset_checkbox, previous_states["external_material_reset"])  # type: ignore[name-defined]
                _set_checkbox_checked_silently_helper(prune_unmapped_original_dds_checkbox, previous_states["prune_unmapped_original_dds"])  # type: ignore[name-defined]
            complete_external_swap_checkbox.setProperty("previous_forced_child_states", None)  # type: ignore[name-defined]
            _complete_swap_refresh_sidecar_options()
            if not _complete_swap_widgets_live():
                return
            try:
                if callable(_refresh_output_impact_review):
                    _refresh_output_impact_review()
                if callable(_queue_texture_preview_refresh):
                    _queue_texture_preview_refresh()
            except RuntimeError as exc:
                message = str(exc)
                if "already deleted" not in message and "Internal C++ object" not in message:
                    raise

    return SimpleNamespace(
        _complete_external_swap_mappings=_complete_external_swap_mappings,
        _apply_complete_external_swap_routing_to_ui=_apply_complete_external_swap_routing_to_ui,
        _select_complete_swap_material_profile_silently=_select_complete_swap_material_profile_silently,
        _sync_complete_external_swap_mode=_sync_complete_external_swap_mode,
    )
