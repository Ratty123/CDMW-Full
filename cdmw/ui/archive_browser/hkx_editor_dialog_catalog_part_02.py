from __future__ import annotations

from types import SimpleNamespace

def _dialog_step_0121(_state):
    def _populate_editable_catalog_tree() -> None:
        root = _state._load_xml_root_from_editor()
        if root is None:
            return
        max_catalog_rows = 2500
        _state.editable_catalog_tree.clear()
        field_elements = root.findall("./editableFieldCatalog/fields/field")
        if not field_elements:
            placeholder = _state.QTreeWidgetItem(("No import-safe editable catalog was exported.", "", "", "", "", "", "", "", "", "", "", "", ""))
            _state.editable_catalog_tree.addTopLevelItem(placeholder)
            _state._set_hkx_editor_section_title(7, "Patchable Catalog")
            return
        grouped: Dict[str, _state.QTreeWidgetItem] = {}
        row_count = 0
        _state.editable_catalog_tree.setSortingEnabled(False)
        for field_element in field_elements[:max_catalog_rows]:
            category = field_element.get("category") or "unknown"
            group_item = grouped.get(category)
            if group_item is None:
                group_item = _state.QTreeWidgetItem((category, "", "", "", "", "", "", "", ""))
                group_item.setFlags(group_item.flags() & ~_state.Qt.ItemFlag.ItemIsEditable)
                _state.editable_catalog_tree.addTopLevelItem(group_item)
                grouped[category] = group_item
            field_item = _state.QTreeWidgetItem(
                (
                    category,
                    field_element.get("subject") or field_element.get("shape_type") or "",
                    field_element.get("editor_tab") or "",
                    field_element.get("record_index") or "",
                    field_element.get("item_index") or "",
                    field_element.get("hex_offset") or field_element.get("offset") or "",
                    field_element.get("name") or "",
                    field_element.get("value_summary") or "",
                    field_element.get("effect") or "",
                    field_element.get("confidence") or "experimental",
                    field_element.get("edit_guidance") or "",
                    field_element.get("value_constraints") or field_element.get("suggested_edit_step") or "",
                    field_element.get("description") or "",
                )
            )
            field_item.setData(
                6,
                _state.Qt.ItemDataRole.UserRole,
                {
                    "editor_tab": field_element.get("editor_tab") or "",
                    "record_index": field_element.get("record_index") or "",
                    "shape_index": field_element.get("shape_index") or "",
                    "name": field_element.get("name") or "",
                    "category": category,
                    "importable": field_element.get("importable") or "",
                },
            )
            field_item.setToolTip(6, "Use Show Selected Editor to jump to the editor that owns this value.")
            if field_element.get("importable") == "true":
                field_item.setForeground(7, _state.QBrush(_state.QColor("#9fd0ff")))
            field_item.setToolTip(10, field_element.get("edit_guidance") or "")
            field_item.setToolTip(11, field_element.get("suggested_edit_step") or field_element.get("value_constraints") or "")
            group_item.addChild(field_item)
            group_item.setExpanded(True)
            row_count += 1
        _state._style_hkx_tree_values(
            _state.editable_catalog_tree,
            value_columns=(3, 4, 5, 7, 11),
            offset_columns=(5,),
            confidence_column=9,
            guidance_columns=(6,),
            patchable_value_column=7,
        )
        for column in range(_state.editable_catalog_tree.columnCount()):
            _state.editable_catalog_tree.resizeColumnToContents(column)
        _state.editable_catalog_tree.setSortingEnabled(True)
        _state._set_hkx_editor_section_title(7, f"Patchable Catalog ({len(grouped)} / {row_count})")
        total_count = len(field_elements)
        if total_count > row_count:
            _state.editable_catalog_status_label.setText(
                f"Showing {row_count:,} of {total_count:,} import-safe editable field(s) across "
                f"{len(grouped):,} visible group(s). Use XML / Raw for the full document."
            )
        else:
            _state.editable_catalog_status_label.setText(f"{row_count:,} import-safe editable field(s) across {len(grouped):,} group(s).")
        if _state.editable_catalog_filter_edit.text().strip():
            _state._apply_editable_catalog_filter()
    _state._populate_editable_catalog_tree = _populate_editable_catalog_tree

def _dialog_step_0122(_state):
    def _catalog_item_matches_filter(item: QTreeWidgetItem, needle: str) -> bool:
        if not needle:
            return True
        row_text = " ".join(item.text(column) for column in range(_state.editable_catalog_tree.columnCount())).casefold()
        return needle in row_text
    _state._catalog_item_matches_filter = _catalog_item_matches_filter

def _dialog_step_0123(_state):
    def _apply_editable_catalog_filter() -> None:
        needle = _state.editable_catalog_filter_edit.text().strip().casefold()
        visible_groups = 0
        visible_rows = 0
        for group_index in range(_state.editable_catalog_tree.topLevelItemCount()):
            group_item = _state.editable_catalog_tree.topLevelItem(group_index)
            group_matches = _state._catalog_item_matches_filter(group_item, needle)
            child_visible = 0
            for child_index in range(group_item.childCount()):
                child_item = group_item.child(child_index)
                child_matches = _state._catalog_item_matches_filter(child_item, needle)
                child_item.setHidden(bool(needle and not child_matches and not group_matches))
                if not child_item.isHidden():
                    child_visible += 1
                    visible_rows += 1
            group_item.setHidden(bool(needle and not group_matches and child_visible == 0))
            if not group_item.isHidden():
                visible_groups += 1
                if needle:
                    group_item.setExpanded(True)
        if needle:
            _state.editable_catalog_status_label.setText(f"Filter: {visible_groups:,} group(s), {visible_rows:,} editable field row(s).")
    _state._apply_editable_catalog_filter = _apply_editable_catalog_filter

def _dialog_step_0124(_state):
    def _focus_selected_catalog_field() -> None:
        item = _state.editable_catalog_tree.currentItem()
        if item is None:
            _state.QMessageBox.information(_state.dialog, "Patchable Catalog", "Select a patchable catalog field first.")
            return
        field_data = item.data(6, _state.Qt.ItemDataRole.UserRole)
        if not isinstance(field_data, dict):
            _state.QMessageBox.information(_state.dialog, "Patchable Catalog", "Select a field row, not a category row.")
            return
        editor_tab = str(field_data.get("editor_tab") or "")
        record_index = str(field_data.get("record_index") or "").strip()
        shape_index = str(field_data.get("shape_index") or "").strip()
        name = str(field_data.get("name") or "").strip()
        if editor_tab == "Structured Editor":
            _state.tuning_editable_only_checkbox.setChecked(True)
            _state.tuning_filter_edit.setText(f"{record_index} {name}".strip())
            _state._populate_tuning_tree()
            _state._set_hkx_editor_section(1)
            return
        if editor_tab == "Collision Editor":
            _state.collision_filter_edit.setText(f"{shape_index} {name}".strip() or str(field_data.get("category") or ""))
            _state._populate_collision_tree()
            _state._set_hkx_editor_section(2)
            return
        _state.QMessageBox.information(_state.dialog, "Patchable Catalog", f"No GUI jump is available for {editor_tab or 'this row'} yet.")
    _state._focus_selected_catalog_field = _focus_selected_catalog_field

def _dialog_step_0125(_state):
    def _focus_catalog_field_from_cell(item: QTreeWidgetItem, _column: int) -> None:
        _state.editable_catalog_tree.setCurrentItem(item)
        _state._focus_selected_catalog_field()
    _state._focus_catalog_field_from_cell = _focus_catalog_field_from_cell

def _dialog_step_0126(_state):
    def _populate_byte_map_tree() -> None:
        root = _state._load_xml_root_from_editor()
        if root is None:
            return
        _state.byte_map_tree.clear()
        entry_elements = root.findall("./bytePatchMap/entries/entry")
        if not entry_elements:
            placeholder = _state.QTreeWidgetItem(("No byte patch map was exported.", "", "", "", "", "", "", "", "", "", ""))
            _state.byte_map_tree.addTopLevelItem(placeholder)
            _state._set_hkx_editor_section_title(8, "Byte Map")
            _state.byte_map_status_label.setText("No byte patch map rows were decoded.")
            return
        grouped: Dict[str, _state.QTreeWidgetItem] = {}
        row_count = 0
        for entry_element in entry_elements:
            category = entry_element.get("category") or "unknown"
            group_item = grouped.get(category)
            if group_item is None:
                group_item = _state.QTreeWidgetItem((category, "", "", "", "", "", "", "", "", "", ""))
                group_item.setFlags(group_item.flags() & ~_state.Qt.ItemFlag.ItemIsEditable)
                _state.byte_map_tree.addTopLevelItem(group_item)
                grouped[category] = group_item
            row_item = _state.QTreeWidgetItem(
                (
                    category,
                    entry_element.get("subject") or "",
                    entry_element.get("path") or "",
                    entry_element.get("record_index") or "",
                    entry_element.get("item_index") or "",
                    entry_element.get("row_index") or "",
                    entry_element.get("component") or "",
                    entry_element.get("hex_relative_offset") or entry_element.get("relative_offset") or "",
                    entry_element.get("hex_absolute_data_offset") or entry_element.get("absolute_data_offset") or "",
                    entry_element.get("value_type") or "",
                    entry_element.get("description") or "",
                )
            )
            row_item.setToolTip(8, "Absolute byte offset in the HKX file payload.")
            group_item.addChild(row_item)
            group_item.setExpanded(False)
            row_count += 1
        _state._style_hkx_tree_values(
            _state.byte_map_tree,
            value_columns=(3, 4, 5, 6, 7, 8, 9),
            offset_columns=(7, 8),
        )
        for column in range(_state.byte_map_tree.columnCount()):
            _state.byte_map_tree.resizeColumnToContents(column)
        _state._set_hkx_editor_section_title(8, f"Byte Map ({len(grouped)} / {row_count})")
        _state.byte_map_status_label.setText(f"{row_count:,} byte-level patch target(s) across {len(grouped):,} group(s).")
        _state._apply_byte_map_filter()
    _state._populate_byte_map_tree = _populate_byte_map_tree

def _dialog_step_0127(_state):
    def _byte_map_item_matches_filter(item: QTreeWidgetItem, needle: str) -> bool:
        if not needle:
            return True
        row_text = " ".join(item.text(column) for column in range(_state.byte_map_tree.columnCount())).casefold()
        return needle in row_text
    _state._byte_map_item_matches_filter = _byte_map_item_matches_filter

def _dialog_step_0128(_state):
    def _apply_byte_map_filter() -> None:
        needle = _state.byte_map_filter_edit.text().strip().casefold()
        visible_groups = 0
        visible_rows = 0
        for group_index in range(_state.byte_map_tree.topLevelItemCount()):
            group_item = _state.byte_map_tree.topLevelItem(group_index)
            group_matches = _state._byte_map_item_matches_filter(group_item, needle)
            child_visible = 0
            for child_index in range(group_item.childCount()):
                child_item = group_item.child(child_index)
                child_matches = _state._byte_map_item_matches_filter(child_item, needle)
                child_item.setHidden(bool(needle and not child_matches and not group_matches))
                if not child_item.isHidden():
                    child_visible += 1
                    visible_rows += 1
            group_item.setHidden(bool(needle and not group_matches and child_visible == 0))
            if not group_item.isHidden():
                visible_groups += 1
                if needle:
                    group_item.setExpanded(True)
        if needle:
            _state.byte_map_status_label.setText(f"Filter: {visible_groups:,} group(s), {visible_rows:,} byte map row(s).")
    _state._apply_byte_map_filter = _apply_byte_map_filter

def _dialog_step_0129(_state):
    def _add_collision_value_item(
        parent: QTreeWidgetItem,
        *,
        shape_index: str,
        field: str,
        row: str,
        component: str,
        value: str,
        description: str,
        key: tuple,
        confidence: str = "experimental",
    ) -> None:
        original_value = _state._remember_initial_value("collision", key, value)
        item = _state.QTreeWidgetItem((shape_index, field, row, component, value, confidence, description))
        item.setData(4, _state.Qt.ItemDataRole.UserRole, key)
        item.setData(4, _state.ORIGINAL_VALUE_ROLE, original_value)
        item.setData(4, _state.DIRTY_KEY_ROLE, _state._dirty_lookup("collision", key))
        item.setFlags(item.flags() | _state.Qt.ItemFlag.ItemIsEditable)
        item.setToolTip(4, "Patchable value. Double-click this row or use Edit Selected Value.")
        _state._set_dirty_item_style(item, 4, value.strip() != original_value.strip())
        parent.addChild(item)
    _state._add_collision_value_item = _add_collision_value_item

def _dialog_step_0130(_state):
    def _add_collision_tuple_item(
        parent: QTreeWidgetItem,
        *,
        shape_index: str,
        field: str,
        row: str,
        value: str,
        description: str,
        key: tuple,
        confidence: str = "strong inference",
    ) -> None:
        original_value = _state._remember_initial_value("collision", key, value)
        item = _state.QTreeWidgetItem((shape_index, field, row, "byte_indices", value, confidence, description))
        item.setData(4, _state.Qt.ItemDataRole.UserRole, key)
        item.setData(4, _state.ORIGINAL_VALUE_ROLE, original_value)
        item.setData(4, _state.DIRTY_KEY_ROLE, _state._dirty_lookup("collision", key))
        item.setFlags(item.flags() | _state.Qt.ItemFlag.ItemIsEditable)
        item.setForeground(1, _state.QBrush(_state.QColor("#bae6fd")))
        item.setForeground(4, _state.QBrush(_state.QColor("#dbeafe")))
        item.setToolTip(
            4,
            "Guarded mesh edit. Enter four byte values, keeping the same values as the original tuple, only reordered.",
        )
        _state._set_dirty_item_style(item, 4, value.strip() != original_value.strip())
        parent.addChild(item)
    _state._add_collision_tuple_item = _add_collision_tuple_item

def _dialog_step_0131(_state):
    def _add_collision_read_only_item(
        parent: QTreeWidgetItem,
        *,
        shape_index: str,
        field: str,
        row: str = "",
        component: str = "",
        value: str = "",
        confidence: str = "experimental",
        description: str = "",
    ) -> None:
        item = _state.QTreeWidgetItem((shape_index, field, row, component, value, confidence, description))
        item.setFlags(item.flags() & ~_state.Qt.ItemFlag.ItemIsEditable)
        item.setForeground(1, _state.QBrush(_state.QColor("#cbd5e1")))
        item.setForeground(4, _state.QBrush(_state.QColor("#cbd5e1")))
        item.setToolTip(4, "Read-only decoded collision context. It is ignored on import.")
        parent.addChild(item)
    _state._add_collision_read_only_item = _add_collision_read_only_item

STEPS = (_dialog_step_0121, _dialog_step_0122, _dialog_step_0123, _dialog_step_0124, _dialog_step_0125, _dialog_step_0126, _dialog_step_0127, _dialog_step_0128, _dialog_step_0129, _dialog_step_0130, _dialog_step_0131,)
