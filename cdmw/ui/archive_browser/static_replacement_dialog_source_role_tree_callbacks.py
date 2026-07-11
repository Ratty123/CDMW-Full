"""Source role tree callback factory for the static replacement dialog."""

from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_source_part_action_state import (
    dispatch_source_part_context_action,
    source_part_context_action_specs,
)


class _SourcePartMenuDispatcher:
    def __init__(self, context: dict[str, object]) -> None:
        self.context = context

    def _callback(self, name: str) -> object:
        callback = self.context.get(name)
        return callback if callable(callback) else None

    def _mesh_edit_active(self) -> bool:
        active = self._callback("_alignment_mesh_edit_tab_active")
        return bool(callable(active) and active())

    def _resident_part_action(self, action_key: str, source_indices: list[int]) -> bool | None:
        if not self._mesh_edit_active():
            return None
        dialog = self.context.get("dialog")
        runner = getattr(dialog, "_mesh_editor_embedded_run_part_action", None)
        if callable(runner):
            return bool(runner(str(action_key), tuple(source_indices)))
        status = getattr(self.context.get("self"), "set_status_message", None)
        if callable(status):
            status(f"Resident part action is unavailable: {action_key}.", error=True)
        return False

    def history_state(self) -> tuple[bool, bool]:
        if self._mesh_edit_active():
            dialog = self.context.get("dialog")
            controller = getattr(dialog, "_mesh_editor_embedded_controller", None)
            controller = controller() if callable(controller) else None
            try:
                view = controller.session_view()
                return int(view.undo_count or 0) > 0, int(view.redo_count or 0) > 0
            except (AttributeError, RuntimeError):
                return False, False
        button = self.context.get("undo_geometry_button")
        try:
            return bool(button is not None and button.isEnabled()), False
        except RuntimeError:
            return False, False

    def all_visible(self, source_indices: list[int]) -> bool:
        qt = self.context.get("Qt")
        items = self.context.get("source_items_by_index")
        if qt is None or not isinstance(items, dict):
            return True
        visible_items = tuple(items.get(index) for index in source_indices if items.get(index) is not None)
        return bool(visible_items) and all(item.checkState(0) == qt.Checked for item in visible_items)

    def target_index(self) -> int:
        try:
            return int(self.context.get("selected_target_slot", {}).get("index", -1))
        except (AttributeError, TypeError, ValueError):
            return -1

    def apply_role_selection(
        self,
        source_index: int,
        role_value: str,
        undo_label: str = "Change source role",
    ) -> None:
        role_action_state = self._callback("_source_part_role_action_state_helper")
        set_role_override = self._callback("_set_source_role_override_value")
        if not callable(role_action_state) or not callable(set_role_override):
            return
        action_state = role_action_state(
            source_index=source_index,
            role_value=role_value,
            undo_label=undo_label,
        )
        if not action_state.available:
            return
        push_undo = self._callback("_push_geometry_undo_snapshot")
        if callable(push_undo):
            push_undo(action_state.undo_label)
        set_role_override(action_state.source_index, action_state.normalized_role)
        refresh_assignment_columns = self._callback("_refresh_source_assignment_columns")
        if callable(refresh_assignment_columns):
            refresh_assignment_columns(lightweight=True)
        for callback_name in ("_refresh_parts_outliner", "_load_selected_part_controls"):
            callback = self._callback(callback_name)
            if callable(callback):
                callback()
        queue_material_edit = self._callback("_queue_material_edit_refresh")
        if callable(queue_material_edit):
            queue_material_edit(
                refresh_plan=action_state.refresh_plan,
                force_plan=action_state.force_plan,
                refresh_preview=action_state.refresh_preview,
                reason=action_state.refresh_reason,
            )

    def _set_visible(self, source_indices: list[int], visible: bool) -> bool:
        qt = self.context.get("Qt")
        items = self.context.get("source_items_by_index")
        if qt is None or not isinstance(items, dict):
            return False
        changed = False
        check_state = qt.Checked if visible else qt.Unchecked
        for source_index in source_indices:
            item = items.get(source_index)
            if item is not None and item.checkState(0) != check_state:
                item.setCheckState(0, check_state)
                changed = True
        return changed

    def dispatch(
        self,
        action_key: str,
        *,
        clicked_source_index: int,
        source_indices: list[int],
        all_visible: bool,
        apply_role: object,
    ) -> bool:
        tree = self.context.get("source_tree")
        items = self.context.get("source_items_by_index")
        item = items.get(clicked_source_index) if isinstance(items, dict) else None

        def select_only() -> bool:
            if item is None or tree is None:
                return False
            tree.clearSelection()
            item.setSelected(True)
            tree.setCurrentItem(item)
            return True

        def toggle_selection() -> bool:
            if item is None or tree is None:
                return False
            item.setSelected(not item.isSelected())
            tree.setCurrentItem(item)
            return True

        def topology(command: str) -> bool:
            resident_result = self._resident_part_action(command, source_indices)
            if resident_result is not None:
                return resident_result
            callback = self._callback(
                "_delete_selected_source_parts" if command == "delete" else "_duplicate_selected_part"
            )
            if not callable(callback):
                return False
            result = callback(source_indices) if command == "delete" else callback(mirrored=False)
            return result is not False

        def role(value: str) -> bool:
            if not callable(apply_role):
                return False
            for source_index in source_indices:
                apply_role(source_index, value, "Set source role glow" if value else "Clear source role")
            return bool(source_indices)

        def route() -> bool:
            callback = self._callback("_apply_parts_outliner_source_target")
            target_index = self.target_index()
            if not callable(callback) or target_index < 0:
                return False
            for source_index in source_indices:
                callback(source_index, target_index)
            return True

        def history(command: str) -> bool:
            resident_result = self._resident_part_action(command, source_indices)
            if resident_result is not None:
                return resident_result
            callback = self._callback("_undo_geometry_change") if command == "undo" else None
            return bool(callable(callback) and callback() is not False)

        return dispatch_source_part_context_action(
            action_key,
            {
                "select_only": select_only,
                "toggle_selection": toggle_selection,
                "duplicate": lambda: topology("duplicate"),
                "delete": lambda: topology("delete"),
                "set_role_glow": lambda: role("glow"),
                "set_role_auto": lambda: role(""),
                "toggle_visibility": lambda: self._set_visible(source_indices, not all_visible),
                "route_selected_target": route,
                "undo": lambda: history("undo"),
                "redo": lambda: history("redo"),
            },
        )


def create_alignment_source_role_tree_callbacks(context: dict[str, object]) -> SimpleNamespace:
    QMenu = context.get('QMenu')
    QPoint = context.get('QPoint')
    _add_source_tree_item = context.get('_add_source_tree_item')
    _alignment_part_clipboard_can_paste = context.get('_alignment_part_clipboard_can_paste')
    _apply_source_part_preview_changes = context.get('_apply_source_part_preview_changes')
    _finish_source_tree_population = context.get('_finish_source_tree_population')
    _paste_alignment_part_clipboard_as_replacement_source = context.get('_paste_alignment_part_clipboard_as_replacement_source')
    _selected_source_indices_from_tree = context.get('_selected_source_indices_from_tree')
    _source_index_from_tree_item = context.get('_source_index_from_tree_item')
    _source_part_context_menu_text_helper = context.get('_source_part_context_menu_text_helper')
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

    menu_dispatcher = _SourcePartMenuDispatcher(context)

    def _apply_source_role_selection(source_index: int, role_value: str, undo_label: str = "Change source role") -> None:
        menu_dispatcher.apply_role_selection(source_index, role_value, undo_label)

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
        delete_source_indices = selected_source_indices or selected_indices_from_tree(include_fallback=True)
        try:
            menu_parent = source_tree.window() or source_tree
        except RuntimeError:
            menu_parent = source_tree
        menu = QMenu(menu_parent)
        source_part_context_menu_text = context_menu_text()
        can_undo, can_redo = menu_dispatcher.history_state()
        all_visible = menu_dispatcher.all_visible(delete_source_indices)
        selected_target_index = menu_dispatcher.target_index()
        action_by_key = {}
        for spec in source_part_context_action_specs(
            has_selection=bool(delete_source_indices),
            all_visible=all_visible,
            can_route=selected_target_index >= 0,
            can_undo=can_undo,
            can_redo=can_redo,
        ):
            action = menu.addAction(spec.label)
            action.setEnabled(spec.enabled)
            if spec.unavailable_reason:
                action.setToolTip(spec.unavailable_reason)
            action_by_key[spec.key] = action
        menu.addSeparator()
        apply_action = menu.addAction(source_part_context_menu_text["apply"])
        apply_action.setEnabled(bool(source_parts_apply_state.get("pending")))
        menu.addSeparator()
        paste_action = menu.addAction(original_part_clipboard_action_text["paste_replacement_source"])
        clipboard_can_paste = _late_callback(
            "_alignment_part_clipboard_can_paste",
            _alignment_part_clipboard_can_paste,
        )
        paste_action.setEnabled(bool(callable(clipboard_can_paste) and clipboard_can_paste()))
        chosen = menu.exec(global_pos if global_pos is not None else source_tree.viewport().mapToGlobal(pos))
        chosen_key = next((key for key, action in action_by_key.items() if chosen is action), "")
        if chosen_key:
            menu_dispatcher.dispatch(
                chosen_key,
                clicked_source_index=clicked_source_index,
                source_indices=delete_source_indices,
                all_visible=all_visible,
                apply_role=_apply_source_role_selection,
            )
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
