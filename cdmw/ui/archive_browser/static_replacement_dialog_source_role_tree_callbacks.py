"""Source role tree callback factory for the static replacement dialog."""

from __future__ import annotations

from types import SimpleNamespace


def create_alignment_source_role_tree_callbacks(context: dict[str, object]) -> SimpleNamespace:
    QMenu = context.get('QMenu')
    QPoint = context.get('QPoint')
    _add_source_tree_item = context.get('_add_source_tree_item')
    _alignment_part_clipboard_can_paste = context.get('_alignment_part_clipboard_can_paste')
    _apply_source_part_preview_changes = context.get('_apply_source_part_preview_changes')
    _delete_selected_source_parts = context.get('_delete_selected_source_parts')
    _finish_source_tree_population = context.get('_finish_source_tree_population')
    _load_selected_part_controls = context.get('_load_selected_part_controls')
    _paste_alignment_part_clipboard_as_replacement_source = context.get('_paste_alignment_part_clipboard_as_replacement_source')
    _push_geometry_undo_snapshot = context.get('_push_geometry_undo_snapshot')
    _queue_material_edit_refresh = context.get('_queue_material_edit_refresh')
    _refresh_parts_outliner = context.get('_refresh_parts_outliner')
    _refresh_source_assignment_columns = context.get('_refresh_source_assignment_columns')
    _selected_source_index = context.get('_selected_source_index')
    _selected_source_indices_from_tree = context.get('_selected_source_indices_from_tree')
    _set_source_role_override_value = context.get('_set_source_role_override_value')
    _source_index_from_tree_item = context.get('_source_index_from_tree_item')
    _source_part_context_menu_text_helper = context.get('_source_part_context_menu_text_helper')
    _source_part_role_action_state_helper = context.get('_source_part_role_action_state_helper')
    _source_tree_context_menu_selection_state_helper = context.get('_source_tree_context_menu_selection_state_helper')
    _source_tree_context_selection_clear_multi_indices_helper = context.get('_source_tree_context_selection_clear_multi_indices_helper')
    _source_tree_context_selection_multi_indices_helper = context.get('_source_tree_context_selection_multi_indices_helper')
    _source_tree_context_selection_set_right_press_helper = context.get('_source_tree_context_selection_set_right_press_helper')
    _source_tree_population_chunk_policy_helper = context.get('_source_tree_population_chunk_policy_helper')
    _source_tree_population_loading_text_helper = context.get('_source_tree_population_loading_text_helper')
    _source_tree_population_next_index_helper = context.get('_source_tree_population_next_index_helper')
    _source_tree_population_set_next_index_helper = context.get('_source_tree_population_set_next_index_helper')
    original_part_clipboard_action_text = context.get('original_part_clipboard_action_text')
    pos = context.get('pos')
    replacement_mesh_for_mapping = context.get('replacement_mesh_for_mapping')
    role_value = context.get('role_value')
    source_items_by_index = context.get('source_items_by_index')
    source_parts_apply_state = context.get('source_parts_apply_state')
    source_tree = context.get('source_tree')
    source_tree_context_selection_state = context.get('source_tree_context_selection_state')
    source_tree_population_state = context.get('source_tree_population_state')
    source_tree_population_timer = context.get('source_tree_population_timer')
    source_tree_progress_label = context.get('source_tree_progress_label')
    time = context.get('time')
    undo_label = context.get('undo_label')

    def _late_callback(name: str, captured: object) -> object:
        if callable(captured):
            return captured
        candidate = context.get(name)
        return candidate if callable(candidate) else None

    def _apply_source_role_selection(source_index: int, role_value: str, undo_label: str = "Change source role") -> None:
        role_action_state = _late_callback(
            "_source_part_role_action_state_helper",
            _source_part_role_action_state_helper,
        )
        if not callable(role_action_state):
            return
        action_state = role_action_state(
            source_index=source_index,
            role_value=role_value,
            undo_label=undo_label,
        )
        if not action_state.available:
            return
        set_role_override = _late_callback("_set_source_role_override_value", _set_source_role_override_value)
        if not callable(set_role_override):
            return
        push_undo = _late_callback("_push_geometry_undo_snapshot", _push_geometry_undo_snapshot)
        if callable(push_undo):
            push_undo(action_state.undo_label)
        set_role_override(action_state.source_index, action_state.normalized_role)
        refresh_assignment_columns = _late_callback("_refresh_source_assignment_columns", _refresh_source_assignment_columns)
        if callable(refresh_assignment_columns):
            refresh_assignment_columns(lightweight=True)
        refresh_outliner = _late_callback("_refresh_parts_outliner", _refresh_parts_outliner)
        if callable(refresh_outliner):
            refresh_outliner()
        load_controls = _late_callback("_load_selected_part_controls", _load_selected_part_controls)
        if callable(load_controls):
            load_controls()
        queue_material_edit = _late_callback("_queue_material_edit_refresh", _queue_material_edit_refresh)
        if callable(queue_material_edit):
            queue_material_edit(
                refresh_plan=action_state.refresh_plan,
                force_plan=action_state.force_plan,
                refresh_preview=action_state.refresh_preview,
                reason=action_state.refresh_reason,
            )

    def _show_replacement_sources_context_menu(
        pos: QPoint,
        *,
        global_pos: object = None,
        source_index_override: int = -1,
    ) -> None:
        source_index_from_item = _late_callback("_source_index_from_tree_item", _source_index_from_tree_item)
        selected_indices_from_tree = _late_callback(
            "_selected_source_indices_from_tree",
            _selected_source_indices_from_tree,
        )
        preserved_indices_for_menu = _late_callback(
            "_source_tree_context_selection_multi_indices_helper",
            _source_tree_context_selection_multi_indices_helper,
        )
        menu_selection_state = _late_callback(
            "_source_tree_context_menu_selection_state_helper",
            _source_tree_context_menu_selection_state_helper,
        )
        selected_source_index = _late_callback("_selected_source_index", _selected_source_index)
        context_menu_text = _late_callback(
            "_source_part_context_menu_text_helper",
            _source_part_context_menu_text_helper,
        )
        if (
            QMenu is None
            or source_tree is None
            or not callable(source_index_from_item)
            or not callable(selected_indices_from_tree)
            or not callable(preserved_indices_for_menu)
            or not callable(menu_selection_state)
            or not callable(selected_source_index)
            or not callable(context_menu_text)
        ):
            return
        item = None
        try:
            source_index_override = int(source_index_override)
        except (TypeError, ValueError):
            source_index_override = -1
        if source_index_override >= 0 and isinstance(source_items_by_index, dict):
            item = source_items_by_index.get(source_index_override)
        if item is None:
            item = source_tree.itemAt(pos)
        clicked_source_index = source_index_override if source_index_override >= 0 else source_index_from_item(item)
        selected_source_indices = selected_indices_from_tree(include_fallback=False)
        preserved_multi_indices = preserved_indices_for_menu(
            source_tree_context_selection_state
        )
        context_selection = menu_selection_state(
            clicked_source_index=clicked_source_index,
            selected_source_indices=selected_source_indices,
            preserved_multi_indices=preserved_multi_indices,
            clicked_item_selected=bool(item is not None and item.isSelected()),
        )
        selected_source_indices = list(context_selection.selected_source_indices)
        if item is not None:
            if context_selection.select_clicked_item:
                source_tree.clearSelection()
                item.setSelected(True)
                if context_selection.clear_multi_indices:
                    clear_multi_indices = _late_callback(
                        "_source_tree_context_selection_clear_multi_indices_helper",
                        _source_tree_context_selection_clear_multi_indices_helper,
                    )
                    if callable(clear_multi_indices):
                        clear_multi_indices(source_tree_context_selection_state)
            source_tree.setCurrentItem(item)
        source_index = selected_source_index()
        delete_source_indices = selected_source_indices or selected_indices_from_tree(include_fallback=True)
        try:
            menu_parent = source_tree.window() or source_tree
        except RuntimeError:
            menu_parent = source_tree
        menu = QMenu(menu_parent)
        source_part_context_menu_text = context_menu_text()
        delete_action = menu.addAction(source_part_context_menu_text["delete_selected_parts"])
        delete_action.setEnabled(bool(delete_source_indices))
        apply_action = menu.addAction(source_part_context_menu_text["apply"])
        apply_action.setEnabled(bool(source_parts_apply_state.get("pending")))
        menu.addSeparator()
        paste_action = menu.addAction(original_part_clipboard_action_text["paste_replacement_source"])
        clipboard_can_paste = _late_callback(
            "_alignment_part_clipboard_can_paste",
            _alignment_part_clipboard_can_paste,
        )
        paste_action.setEnabled(bool(callable(clipboard_can_paste) and clipboard_can_paste()))
        menu.addSeparator()
        glow_role_action = menu.addAction(source_part_context_menu_text["set_role_glow"])
        auto_role_action = menu.addAction(source_part_context_menu_text["set_role_auto"])
        glow_role_action.setEnabled(source_index >= 0)
        auto_role_action.setEnabled(source_index >= 0)
        chosen = menu.exec(global_pos if global_pos is not None else source_tree.viewport().mapToGlobal(pos))
        if chosen is delete_action:
            delete_parts = _late_callback("_delete_selected_source_parts", _delete_selected_source_parts)
            if callable(delete_parts):
                delete_parts(delete_source_indices)
        elif chosen is apply_action:
            apply_changes = _late_callback("_apply_source_part_preview_changes", _apply_source_part_preview_changes)
            if callable(apply_changes):
                apply_changes()
        elif chosen is paste_action:
            paste_source = _late_callback(
                "_paste_alignment_part_clipboard_as_replacement_source",
                _paste_alignment_part_clipboard_as_replacement_source,
            )
            if callable(paste_source):
                paste_source()
        elif chosen is glow_role_action and source_index >= 0:
            _apply_source_role_selection(source_index, "glow", "Set source role glow")
        elif chosen is auto_role_action and source_index >= 0:
            _apply_source_role_selection(source_index, "", "Clear source role")
        set_right_press = _late_callback(
            "_source_tree_context_selection_set_right_press_helper",
            _source_tree_context_selection_set_right_press_helper,
        )
        if callable(set_right_press):
            set_right_press(source_tree_context_selection_state, False)

    def _show_replacement_sources_context_menu_for_viewport(source_index: int, global_pos: object) -> None:
        if QPoint is None or source_tree is None:
            return
        try:
            source_index = int(source_index)
        except (TypeError, ValueError):
            return
        if source_index < 0:
            return
        item = source_items_by_index.get(source_index) if isinstance(source_items_by_index, dict) else None
        local_pos = source_tree.visualItemRect(item).center() if item is not None else source_tree.viewport().rect().center()
        _show_replacement_sources_context_menu(
            local_pos,
            global_pos=global_pos,
            source_index_override=source_index,
        )

    def _populate_source_tree_chunk() -> None:
        if replacement_mesh_for_mapping is None:
            source_tree_population_timer.stop()
            _finish_source_tree_population()
            return
        total = len(getattr(replacement_mesh_for_mapping, "submeshes", ()) or ())
        start = _source_tree_population_next_index_helper(source_tree_population_state)
        chunk_policy = _source_tree_population_chunk_policy_helper()
        deadline = time.perf_counter() + chunk_policy.time_budget_seconds
        added = 0
        while start < total and added < chunk_policy.row_limit and time.perf_counter() < deadline:
            source = replacement_mesh_for_mapping.submeshes[start]
            if start not in source_items_by_index:
                _add_source_tree_item(start, source)
            start += 1
            added += 1
        _source_tree_population_set_next_index_helper(source_tree_population_state, start)
        source_tree_progress_label.setText(
            _source_tree_population_loading_text_helper(min(start, total), total)
        )
        if start >= total:
            source_tree_population_timer.stop()
            _finish_source_tree_population()
        else:
            source_tree_population_timer.start()

    return SimpleNamespace(
        _apply_source_role_selection=_apply_source_role_selection,
        _show_replacement_sources_context_menu=_show_replacement_sources_context_menu,
        _show_replacement_sources_context_menu_for_viewport=_show_replacement_sources_context_menu_for_viewport,
        _populate_source_tree_chunk=_populate_source_tree_chunk,
    )
