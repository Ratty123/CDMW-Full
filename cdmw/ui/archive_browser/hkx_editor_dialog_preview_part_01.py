from __future__ import annotations

from types import SimpleNamespace

def _dialog_step_0017(_state):
    def _set_hkx_preview_panel_visible(visible: bool, *, refresh: bool = False) -> None:
        visible = bool(visible)
        _state.hkx_preview_panel.setVisible(visible)
        try:
            has_existing_preview = isinstance(_state._current_hkx_link_preview_model(), _state.ModelPreviewData)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            has_existing_preview = False
        _state.hkx_preview_refresh_button.setVisible(bool(visible and has_existing_preview and not _state.hkx_link_preview_state.get("loaded")))
        _state.preview_toggle_button.setText("Hide 3D" if visible else "Show 3D")
        _state.preview_toggle_button.setToolTip(
            "Hide the embedded 3D Preview pane." if visible else
            "Show the optional embedded 3D Preview pane. Use Load Model inside the pane if no preview is already loaded."
        )
        if _state.preview_toggle_button.isChecked() != visible:
            _state.preview_toggle_button.blockSignals(True)
            _state.preview_toggle_button.setChecked(visible)
            _state.preview_toggle_button.blockSignals(False)
        if visible:
            sizes = _state.workspace_splitter.sizes()
            if len(sizes) >= 3 and sizes[2] <= 40:
                _state.workspace_splitter.setSizes([280, 920, 560])
            if refresh and not bool(_state.hkx_link_preview_state.get("loaded")):
                _state._refresh_hkx_link_preview_model()
    _state._set_hkx_preview_panel_visible = _set_hkx_preview_panel_visible

def _dialog_step_0018(_state):
    def _refresh_section_nav_visibility() -> None:
        show_advanced = _state.section_advanced_views_toggle.isChecked()
        for row in range(_state.section_nav_list.count()):
            item = _state.section_nav_list.item(row)
            if item is None:
                continue
            is_primary = bool(item.data(_state.Qt.ItemDataRole.UserRole + 1))
            item.setHidden(not show_advanced and not is_primary)
    _state._refresh_section_nav_visibility = _refresh_section_nav_visibility

def _dialog_step_0019(_state):
    def _ensure_section_nav_visible(index: int) -> None:
        item = _state.section_nav_list.item(index) if 0 <= index < _state.section_nav_list.count() else None
        if item is not None and item.isHidden():
            _state.section_advanced_views_toggle.blockSignals(True)
            _state.section_advanced_views_toggle.setChecked(True)
            _state.section_advanced_views_toggle.blockSignals(False)
            _state._refresh_section_nav_visibility()
    _state._ensure_section_nav_visible = _ensure_section_nav_visible

def _dialog_step_0020(_state):
    def _set_hkx_editor_section_title(index: int, title: str) -> None:
        _state.tab_widget.setTabText(index, title)
        if 0 <= index < _state.section_combo.count():
            _state.section_combo.setItemText(index, title)
        if 0 <= index < _state.section_nav_list.count():
            _state.section_nav_list.item(index).setText(title)
        if _state.tab_widget.currentIndex() == index:
            _state.section_current_label.setText(title)
    _state._set_hkx_editor_section_title = _set_hkx_editor_section_title

def _dialog_step_0021(_state):
    def _set_hkx_editor_section(index: int) -> None:
        if index < 0 or index >= _state.tab_widget.count():
            return
        if index == _state.placement_tab_index:
            _state.self.set_status_message("Placement view is disabled - WIP.", error=True)
            index = 0
        _state.tab_widget.setCurrentIndex(index)
        _state.section_current_label.setText(_state.tab_widget.tabText(index))
        if _state.section_combo.currentIndex() != index:
            _state.section_combo.blockSignals(True)
            _state.section_combo.setCurrentIndex(index)
            _state.section_combo.blockSignals(False)
        _state._ensure_section_nav_visible(index)
        if _state.section_nav_list.currentRow() != index:
            _state.section_nav_list.blockSignals(True)
            _state.section_nav_list.setCurrentRow(index)
            _state.section_nav_list.blockSignals(False)
        _state.section_summary_label.setText(_state.SECTION_SUMMARIES.get(index, ""))
    _state._set_hkx_editor_section = _set_hkx_editor_section

def _dialog_step_0022(_state):
    def _sync_hkx_editor_section_selector(index: int) -> None:
        _state.section_current_label.setText(_state.tab_widget.tabText(index) if 0 <= index < _state.tab_widget.count() else "")
        if 0 <= index < _state.section_combo.count() and _state.section_combo.currentIndex() != index:
            _state.section_combo.blockSignals(True)
            _state.section_combo.setCurrentIndex(index)
            _state.section_combo.blockSignals(False)
        _state._ensure_section_nav_visible(index)
        if 0 <= index < _state.section_nav_list.count() and _state.section_nav_list.currentRow() != index:
            _state.section_nav_list.blockSignals(True)
            _state.section_nav_list.setCurrentRow(index)
            _state.section_nav_list.blockSignals(False)
        _state.section_summary_label.setText(_state.SECTION_SUMMARIES.get(index, ""))
    _state._sync_hkx_editor_section_selector = _sync_hkx_editor_section_selector

def _dialog_step_0023(_state):
    def _style_hkx_browser_item(
        item: QTreeWidgetItem,
        *,
        confidence: str = "",
        status: str = "",
        importable: bool = False,
        viewer_id: str = "",
        read_only: bool = False,
    ) -> None:
        confidence_key = str(confidence or "").strip().lower()
        status_key = str(status or item.text(1) or "").strip().lower()
        if status_key in {"editable", "decoded", "partially_decoded", "raw_preserved", "raw"}:
            status_label, status_tip, status_color = _state._hkx_status_display(status_key)
            item.setForeground(0, _state.QBrush(status_color))
            item.setToolTip(0, status_tip)
            if item.text(3).strip() == status_key:
                item.setText(3, status_label)
            elif not item.toolTip(3):
                item.setToolTip(3, status_tip)
        if importable:
            item.setForeground(2, _state.QBrush(_state.QColor("#9fd0ff")))
            item.setForeground(0, _state.QBrush(_state.QColor("#dbeafe")))
            item.setToolTip(0, "Patchable fixed-size HKX value.")
        elif read_only and viewer_id:
            item.setForeground(0, _state.QBrush(_state.QColor("#bae6fd")))
            item.setForeground(2, _state.QBrush(_state.QColor("#cbd5e1")))
            item.setToolTip(0, "Read-only decoded HKX row with a 3D preview target.")
        elif read_only:
            item.setForeground(0, _state.QBrush(_state.QColor("#cbd5e1")))
            item.setToolTip(0, "Read-only HKX metadata. It is ignored on import.")
        if viewer_id:
            item.setForeground(1, _state.QBrush(_state.QColor("#67e8f9")))
            item.setToolTip(1, f"Preview target: {viewer_id}")
        if confidence_key in {"confirmed", "descriptor_context", "descriptor-context"}:
            item.setForeground(3, _state.QBrush(_state.QColor("#86efac")))
        elif confidence_key in {"strong inference", "strong_inference", "skeleton_context"}:
            item.setForeground(3, _state.QBrush(_state.QColor("#fde68a")))
        elif confidence_key in {"experimental", "raw", "raw_preserved"}:
            item.setForeground(3, _state.QBrush(_state.QColor("#fca5a5")))
        if status_key in {"editable", "decoded", "partially_decoded", "raw_preserved", "raw"}:
            status_label, status_tip, status_color = _state._hkx_status_display(status_key)
            item.setForeground(0, _state.QBrush(status_color))
            if status_key == "partially_decoded":
                item.setForeground(1, _state.QBrush(status_color))
            if not item.toolTip(0) or item.toolTip(0).startswith("Read-only"):
                item.setToolTip(0, status_tip)
            if item.text(3).strip() == status_key:
                item.setText(3, status_label)
    _state._style_hkx_browser_item = _style_hkx_browser_item

def _dialog_step_0024(_state):
    def _hkx_item_is_patchable(item: QTreeWidgetItem, guidance_columns: Sequence[int]) -> bool:
        data = item.data(0, _state.BROWSER_DATA_ROLE)
        if isinstance(data, _state.Mapping) and str(data.get("importable") or "").strip().lower() == "true":
            return True
        for column in guidance_columns:
            guidance = item.data(column, _state.Qt.ItemDataRole.UserRole)
            if isinstance(guidance, _state.Mapping) and bool(guidance.get("patchable")):
                return True
            if isinstance(guidance, _state.Mapping) and str(guidance.get("importable") or "").strip().lower() == "true":
                return True
            if item.data(column, _state.ORIGINAL_VALUE_ROLE) is not None or item.data(column, _state.DIRTY_KEY_ROLE) is not None:
                return True
        return False
    _state._hkx_item_is_patchable = _hkx_item_is_patchable

def _dialog_step_0025(_state):
    def _iter_tree_items(tree: QTreeWidget) -> List[QTreeWidgetItem]:
        rows: List[QTreeWidgetItem] = []

        def _collect(item: QTreeWidgetItem) -> None:
            rows.append(item)
            for child_index in range(item.childCount()):
                _collect(item.child(child_index))

        for top_index in range(tree.topLevelItemCount()):
            _collect(tree.topLevelItem(top_index))
        return rows
    _state._iter_tree_items = _iter_tree_items

def _dialog_step_0026(_state):
    def _style_hkx_tree_values(
        tree: QTreeWidget,
        *,
        value_columns: Sequence[int] = (),
        offset_columns: Sequence[int] = (),
        confidence_column: int = -1,
        guidance_columns: Sequence[int] = (),
        patchable_value_column: int = -1,
    ) -> None:
        mono_font = _state.build_monospace_font(_state.self.settings)
        for item in _state._iter_tree_items(tree):
            patchable = _state._hkx_item_is_patchable(item, guidance_columns)
            for column in offset_columns:
                if column < tree.columnCount() and item.text(column).strip():
                    item.setFont(column, mono_font)
                    item.setForeground(column, _state.QBrush(_state.QColor("#fbbf24")))
            for column in value_columns:
                if column >= tree.columnCount() or not item.text(column).strip():
                    continue
                item.setFont(column, mono_font)
                text_kind = _state._hkx_numeric_text_kind(item.text(column))
                if patchable and column == patchable_value_column:
                    dirty_key = item.data(column, _state.DIRTY_KEY_ROLE)
                    if dirty_key not in _state.dirty_values_by_key:
                        item.setBackground(column, _state.QBrush(_state.QColor("#17324d")))
                    item.setForeground(column, _state.QBrush(_state.QColor("#bfdbfe")))
                elif text_kind == "offset":
                    item.setForeground(column, _state.QBrush(_state.QColor("#fbbf24")))
                elif text_kind == "reference":
                    item.setForeground(column, _state.QBrush(_state.QColor("#67e8f9")))
                elif text_kind == "before_after":
                    item.setForeground(column, _state.QBrush(_state.QColor("#f0abfc")))
                elif text_kind in {"number", "mixed"}:
                    item.setForeground(column, _state.QBrush(_state.QColor("#c4b5fd")))
                elif text_kind == "vector":
                    item.setForeground(column, _state.QBrush(_state.QColor("#93c5fd")))
                else:
                    item.setForeground(column, _state.QBrush(_state.QColor("#d1d5db")))
            if confidence_column >= 0 and confidence_column < tree.columnCount():
                confidence = item.text(confidence_column)
                if confidence:
                    item.setForeground(confidence_column, _state.QBrush(_state._hkx_confidence_color(confidence)))
            if patchable:
                item.setForeground(0, _state.QBrush(_state.QColor("#dbeafe")))
    _state._style_hkx_tree_values = _style_hkx_tree_values

def _dialog_step_0027(_state):
    def _sync_browser_action_buttons() -> None:
        data = _state._current_browser_data()
        has_data = bool(data)
        has_preview_hint = has_data and _state._has_preview_link_hint(data)
        _state.browser_show_editor_button.setEnabled(has_data and bool(data.get("editor_tab")))
        _state.browser_show_xml_button.setEnabled(has_data and bool(data.get("patch_path") or data.get("id") or data.get("label")))
        _state.browser_show_preview_button.setEnabled(has_preview_hint)
        if not has_data:
            _state.browser_show_preview_button.setToolTip("Select a decoded row first.")
        elif not has_preview_hint:
            _state.browser_show_preview_button.setToolTip("This row has no recovered visible 3D target yet.")
        elif not _state._available_hkx_preview_target_ids():
            _state.browser_show_preview_button.setToolTip(
                "This row has a recovered 3D target, but no matching model preview is loaded yet. "
                "Click Show in 3D, then use Load Model in the embedded preview pane."
            )
        else:
            _state.browser_show_preview_button.setToolTip("Open the embedded 3D Preview pane and highlight this row's target.")
    _state._sync_browser_action_buttons = _sync_browser_action_buttons

def _dialog_step_0028(_state):
    def _browser_item_matches_filters(item: QTreeWidgetItem) -> bool:
        data = item.data(0, _state.BROWSER_DATA_ROLE)
        data_map = data if isinstance(data, _state.Mapping) else {}
        row_text = " ".join(item.text(column) for column in range(_state.hkx_browser_tree.columnCount())).casefold()
        if data_map:
            row_text += " " + " ".join(str(value) for value in data_map.values()).casefold()
        needle = _state.browser_filter_edit.text().strip().casefold()
        if needle and needle not in row_text:
            return False
        importable = str(data_map.get("importable") or "").strip().lower() == "true"
        preview_linked = _state._has_preview_link_hint(data_map)
        cached_preview_targets = _state.browser_filter_state.get("available_preview_targets")
        available_preview_targets = cached_preview_targets if isinstance(cached_preview_targets, set) else set()
        preview_viewer_id = ""
        if preview_linked:
            preview_viewer_id = _state._previewable_viewer_id(data_map.get("viewer_selection_id"))
            if not preview_viewer_id and str(data_map.get("shape_index") or "").strip():
                preview_viewer_id = _state._previewable_viewer_id(f"shape/{data_map.get('shape_index')}")
        confidence = str(data_map.get("confidence") or item.text(3) or "").strip().lower()
        kind = str(data_map.get("kind") or item.text(1) or "").strip().lower()
        source = str(data_map.get("source") or "").strip().lower()
        raw_preserved = confidence in {"raw", "raw_preserved"} or "raw" in kind or "raw_preserved" in source
        decoded = bool(data_map) and not raw_preserved
        if _state.browser_editable_only_checkbox.isChecked() and not importable:
            return False
        if _state.browser_preview_linked_checkbox.isChecked():
            if not preview_linked:
                return False
            if available_preview_targets and preview_viewer_id and preview_viewer_id not in available_preview_targets:
                return False
        if _state.browser_decoded_only_checkbox.isChecked() and not decoded:
            return False
        if _state.browser_raw_preserved_checkbox.isChecked() and not raw_preserved:
            return False
        return True
    _state._browser_item_matches_filters = _browser_item_matches_filters

def _dialog_step_0029(_state):
    def _apply_hkx_browser_filter() -> None:
        total_rows = 0
        visible_rows = 0
        _state.browser_filter_state["available_preview_targets"] = _state._available_hkx_preview_target_ids()

        def _apply_item(item: QTreeWidgetItem) -> bool:
            nonlocal total_rows, visible_rows
            total_rows += 1
            own_match = _state._browser_item_matches_filters(item)
            child_visible = False
            for child_index in range(item.childCount()):
                if _apply_item(item.child(child_index)):
                    child_visible = True
            visible = own_match or child_visible
            item.setHidden(not visible)
            if visible:
                visible_rows += 1
                if child_visible and _state.browser_filter_edit.text().strip():
                    item.setExpanded(True)
            return visible

        for top_index in range(_state.hkx_browser_tree.topLevelItemCount()):
            _apply_item(_state.hkx_browser_tree.topLevelItem(top_index))
        active_filters = []
        if _state.browser_filter_edit.text().strip():
            active_filters.append("text")
        if _state.browser_editable_only_checkbox.isChecked():
            active_filters.append("patchable")
        if _state.browser_preview_linked_checkbox.isChecked():
            active_filters.append("3D-linked")
        if _state.browser_decoded_only_checkbox.isChecked():
            active_filters.append("decoded/context")
        if _state.browser_raw_preserved_checkbox.isChecked():
            active_filters.append("raw/unknown")
        filter_suffix = f" | filters: {', '.join(active_filters)}" if active_filters else ""
        suffix_note = ""
        current_available_targets = _state.browser_filter_state.get("available_preview_targets")
        if (
            _state.browser_preview_linked_checkbox.isChecked()
            and isinstance(current_available_targets, set)
            and not current_available_targets
        ):
            suffix_note = " Load a matching model preview to verify which recovered targets are actually visible."
        _state.browser_status_label.setText(
            f"{visible_rows:,} / {total_rows:,} HKX browser row(s) visible{filter_suffix}.{suffix_note}"
        )
        _state._sync_browser_action_buttons()
    _state._apply_hkx_browser_filter = _apply_hkx_browser_filter

def _dialog_step_0030(_state):
    def _dirty_lookup(prefix: str, key: tuple) -> Tuple[str, tuple]:
        return (prefix, tuple(str(part) for part in key))
    _state._dirty_lookup = _dirty_lookup

def _dialog_step_0031(_state):
    def _remember_initial_value(prefix: str, key: tuple, value: str) -> str:
        lookup_key = _state._dirty_lookup(prefix, key)
        if lookup_key not in _state.initial_values_by_key:
            _state.initial_values_by_key[lookup_key] = str(value)
        return _state.initial_values_by_key[lookup_key]
    _state._remember_initial_value = _remember_initial_value

def _dialog_step_0032(_state):
    def _set_dirty_item_style(item: QTreeWidgetItem, value_column: int, dirty: bool) -> None:
        if dirty:
            item.setBackground(value_column, _state.QBrush(_state.QColor("#314d73")))
            item.setForeground(value_column, _state.QBrush(_state.QColor("#ffffff")))
            font = item.font(value_column)
            font.setBold(True)
            item.setFont(value_column, font)
        else:
            item.setBackground(value_column, _state.QBrush())
            font = item.font(value_column)
            font.setBold(False)
            item.setFont(value_column, font)
    _state._set_dirty_item_style = _set_dirty_item_style

def _dialog_step_0033(_state):
    def _refresh_dirty_status() -> None:
        dirty_count = len(_state.dirty_values_by_key)
        if dirty_count:
            _state.browser_status_label.setText(f"{dirty_count:,} edited HKX value(s) pending loose-mod write.")
        else:
            _state.browser_status_label.setText("No edited HKX values.")
    _state._refresh_dirty_status = _refresh_dirty_status

def _dialog_step_0034(_state):
    def _record_dirty_value(prefix: str, key: tuple, label: str, original_value: str, current_value: str) -> None:
        lookup_key = _state._dirty_lookup(prefix, key)
        if str(current_value).strip() == str(original_value).strip():
            _state.dirty_values_by_key.pop(lookup_key, None)
        else:
            _state.dirty_values_by_key[lookup_key] = (label, str(original_value), str(current_value))
        _state._refresh_dirty_status()
        _state._sync_hkx_edited_overlay_targets()
    _state._record_dirty_value = _record_dirty_value

def _dialog_step_0035(_state):
    def _dirty_lookup_from_mapping(data: Mapping[str, object]) -> Optional[Tuple[str, tuple]]:
        record_index = str(data.get("record_index") or "").strip()
        item_index = str(data.get("item_index") or "").strip()
        offset = str(data.get("offset") or "").strip()
        if record_index and item_index and offset:
            return _state._dirty_lookup("tuning", (record_index, item_index, offset))
        return None
    _state._dirty_lookup_from_mapping = _dirty_lookup_from_mapping

def _dialog_step_0036(_state):
    def _dirty_before_after_from_mapping(data: Mapping[str, object]) -> Optional[Tuple[str, str, str]]:
        lookup_key = _state._dirty_lookup_from_mapping(data)
        if lookup_key is None:
            return None
        dirty = _state.dirty_values_by_key.get(lookup_key)
        if dirty is None:
            return None
        label, original_value, current_value = dirty
        return (str(label), str(original_value), str(current_value))
    _state._dirty_before_after_from_mapping = _dirty_before_after_from_mapping

def _dialog_step_0037(_state):
    def _value_with_dirty_preview(data: Mapping[str, object], fallback_value: object = "") -> str:
        dirty = _state._dirty_before_after_from_mapping(data)
        if dirty is not None:
            _label, original_value, current_value = dirty
            return _state._format_hkx_display_value(f"{original_value} -> {current_value}")
        return _state._format_hkx_display_value(fallback_value or data.get("value") or data.get("original_value") or "")
    _state._value_with_dirty_preview = _value_with_dirty_preview

def _dialog_step_0038(_state):
    def _comparison_lines_from_mapping(data: Mapping[str, object]) -> List[str]:
        importable = str(data.get("importable") or "").strip().lower() == "true"
        preview_linked = bool(str(data.get("viewer_selection_id") or "").strip())
        if importable:
            row_state = "patchable fixed-size value"
        elif preview_linked:
            row_state = "read-only preview-linked context"
        else:
            row_state = "read-only metadata"
        lines = [
            str(data.get("label") or data.get("title") or "HKX value"),
            f"Kind: {data.get('kind') or data.get('category') or data.get('source') or 'unknown'}",
            f"State: {row_state}",
        ]
        friendly_meaning = _state._friendly_hkx_value_meaning(data)
        if friendly_meaning:
            lines.append(f"Plain meaning: {friendly_meaning}")
        dirty = _state._dirty_before_after_from_mapping(data)
        if dirty is not None:
            _dirty_label, original_value, current_value = dirty
            lines.extend(
                [
                    "Edit state: edited, pending loose-mod write",
                    f"Before: {original_value}",
                    f"After: {current_value}",
                ]
            )
        for label, key in (
            ("Context", "context_label"),
            ("Body", "body_name"),
            ("Socket", "socket_name"),
            ("Fixed socket", "fixed_socket_name"),
            ("Material", "physics_material_name"),
            ("Shape", "shape_index"),
            ("Shape type", "shape_type"),
            ("Context source", "context_source"),
            ("Identity path", "identity_path"),
            ("Value", "value"),
            ("Original", "original_value"),
            ("Confidence", "confidence"),
            ("Risk", "edit_risk"),
            ("Effect", "effect"),
            ("Patch path", "patch_path"),
            ("Record", "record_index"),
            ("Item", "item_index"),
            ("Offset", "hex_offset"),
            ("Byte offset", "hex_absolute_byte_offset"),
            ("Viewer id", "viewer_selection_id"),
        ):
            value = data.get(key)
            if value not in (None, ""):
                lines.append(f"{label}: {_state._format_hkx_display_value(value) if label in {'Value', 'Original', 'Offset', 'Byte offset'} else value}")
        for label, key in (
            ("Explanation", "explanation"),
            ("If increased", "if_increased"),
            ("If decreased", "if_decreased"),
            ("Safe edit", "safe_edit_hint"),
            ("Constraints", "value_constraints"),
        ):
            value = str(data.get(key) or "").strip()
            if value:
                lines.append(f"{label}: {value}")
        return lines
    _state._comparison_lines_from_mapping = _comparison_lines_from_mapping

def _dialog_step_0039(_state):
    def _update_comparison_text_from_item(
        item: Optional[QTreeWidgetItem],
        *,
        value_column: int = -1,
        guidance_column: int = -1,
    ) -> None:
        if item is None:
            _state.comparison_text.clear()
            return
        browser_data = item.data(0, _state.BROWSER_DATA_ROLE)
        if isinstance(browser_data, _state.Mapping):
            _state.comparison_text.setPlainText("\n".join(_state._comparison_lines_from_mapping(browser_data)))
            return
        lines = [item.text(0) or "HKX value"]
        if value_column >= 0:
            current_value = item.text(value_column)
            original_value = item.data(value_column, _state.ORIGINAL_VALUE_ROLE)
            if original_value not in (None, ""):
                lines.append(f"Original: {original_value}")
            if current_value:
                lines.append(f"Current: {current_value}")
            dirty_key = item.data(value_column, _state.DIRTY_KEY_ROLE)
            if dirty_key in _state.dirty_values_by_key:
                lines.append("State: edited")
        if guidance_column >= 0:
            guidance = item.data(guidance_column, _state.Qt.ItemDataRole.UserRole)
            if isinstance(guidance, _state.Mapping):
                lines.extend(_state._comparison_lines_from_mapping(guidance))
        if len(lines) == 1:
            lines.append("Select a patchable row to see edit guidance and byte mapping.")
        _state.comparison_text.setPlainText("\n".join(lines))
    _state._update_comparison_text_from_item = _update_comparison_text_from_item

def _dialog_step_0040(_state):
    def _update_line_numbers() -> None:
        _state.line_numbers.setPlainText("\n".join(str(index) for index in range(1, _state.editor.blockCount() + 1)))
        _state.line_numbers.verticalScrollBar().setValue(_state.editor.verticalScrollBar().value())
    _state._update_line_numbers = _update_line_numbers

def _dialog_step_0041(_state):
    def _update_cursor_status() -> None:
        cursor = _state.editor.textCursor()
        _state.line_status_label.setText(f"Line {cursor.blockNumber() + 1}, Column {cursor.positionInBlock() + 1}")
    _state._update_cursor_status = _update_cursor_status

def _dialog_step_0042(_state):
    def _format_xml_from_root(root: ET.Element) -> str:
        try:
            _state.ET.indent(root, space="  ")
        except (AttributeError, TypeError, ValueError):
            # Best effort: formatting should not block XML serialization.
            pass
        return _state.ET.tostring(root, encoding="unicode")
    _state._format_xml_from_root = _format_xml_from_root

def _dialog_step_0043(_state):
    def _load_xml_root_from_editor() -> Optional[ET.Element]:
        try:
            return _state.ET.fromstring(_state.editor.toPlainText())
        except _state.ET.ParseError as exc:
            _state.QMessageBox.warning(_state.dialog, "HKX XML", f"Could not parse current XML:\n{exc}")
            return None
    _state._load_xml_root_from_editor = _load_xml_root_from_editor

def _dialog_step_0044(_state):
    def _silent_xml_root_from_editor() -> Optional[ET.Element]:
        try:
            return _state.ET.fromstring(_state.editor.toPlainText())
        except _state.ET.ParseError:
            return None
    _state._silent_xml_root_from_editor = _silent_xml_root_from_editor

def _dialog_step_0045(_state):
    def _dirty_overlay_viewer_ids_from_root(root: Optional[ET.Element]) -> set[str]:
        viewer_ids: set[str] = set()
        tuning_dirty_keys = {
            key
            for prefix, key in _state.dirty_values_by_key
            if prefix == "tuning" and isinstance(key, tuple) and len(key) == 3
        }
        for prefix, key in _state.dirty_values_by_key:
            if prefix != "collision" or not isinstance(key, tuple) or len(key) < 2:
                continue
            shape_index = str(key[1] or "").strip()
            if shape_index:
                viewer_ids.add(f"shape/{shape_index}")
        if root is None or not tuning_dirty_keys:
            return viewer_ids
        for row in root.findall("./editorModel/groups/group/rows/row"):
            dirty_key = _state._dirty_lookup(
                "tuning",
                (
                    row.get("record_index") or "",
                    row.get("item_index") or "",
                    row.get("offset") or "",
                ),
            )[1]
            if dirty_key not in tuning_dirty_keys:
                continue
            viewer_id = str(row.get("viewer_selection_id") or "").strip()
            if viewer_id:
                viewer_ids.add(viewer_id)
        for constraint in root.findall("./physicsConstraintSummary/constraints/constraint"):
            constraint_index = str(constraint.get("index") or "").strip()
            if not constraint_index:
                continue
            for slot_parent_name, record_attr in (
                ("constraint_slots", "constraint_record_index"),
                ("motor_slots", "motor_record_index"),
            ):
                record_index = str(constraint.get(record_attr) or "").strip()
                if not record_index:
                    continue
                for slot in constraint.findall(f"./{slot_parent_name}/*"):
                    dirty_key = _state._dirty_lookup(
                        "tuning",
                        (
                            record_index,
                            slot.get("item_index") or "",
                            slot.get("offset") or "",
                        ),
                    )[1]
                    if dirty_key in tuning_dirty_keys:
                        viewer_ids.add(f"constraint/{constraint_index}")
        return viewer_ids
    _state._dirty_overlay_viewer_ids_from_root = _dirty_overlay_viewer_ids_from_root

def _dialog_step_0046(_state):
    def _hkx_overlay_preview_widgets() -> List[object]:
        widgets: List[object] = []
        seen: set[int] = set()
        for preview in (_state.hkx_link_preview_widget, _state.self.archive_model_preview):
            if preview is None or id(preview) in seen:
                continue
            seen.add(id(preview))
            widgets.append(preview)
        return widgets
    _state._hkx_overlay_preview_widgets = _hkx_overlay_preview_widgets

def _dialog_step_0047(_state):
    try:
        _state.archive_preview_original_settings = _state.self.archive_model_preview.render_settings()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _state.archive_preview_original_settings = None
    try:
        _state.archive_preview_original_bones_visible = (
            _state.self.archive_model_preview.physics_overlay_bones_visible()
            if hasattr(_state.self.archive_model_preview, "physics_overlay_bones_visible")
            else None
        )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _state.archive_preview_original_bones_visible = None

def _dialog_step_0048(_state):
    def _enable_hkx_preview_overlay(preview: object) -> None:
        if preview is _state.self.archive_model_preview:
            return
        if not hasattr(preview, "render_settings") or not hasattr(preview, "set_render_settings"):
            return
        try:
            preview_settings = preview.render_settings()
            if (
                not bool(getattr(preview_settings, "show_physics_overlay", True))
                or bool(getattr(preview_settings, "show_physics_simulation_preview", False))
            ):
                preview.set_render_settings(
                    _state.dataclasses.replace(
                        preview_settings,
                        show_physics_overlay=True,
                        show_physics_simulation_preview=False,
                    )
                )
        except (AttributeError, RuntimeError, TypeError, ValueError):
            # Best effort: overlay previews keep their existing render settings if sync fails.
            pass
    _state._enable_hkx_preview_overlay = _enable_hkx_preview_overlay

def _dialog_step_0049(_state):
    def _current_hkx_link_preview_model() -> Optional[ModelPreviewData]:
        active_archive_preview = _state.self._active_archive_model_preview_widget() or _state.self.archive_model_preview
        try:
            widget_model = active_archive_preview.current_model_preview()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            widget_model = None
        if isinstance(widget_model, _state.ModelPreviewData) and getattr(widget_model, "meshes", None):
            return widget_model
        result = getattr(_state.self, "current_archive_preview_result", None)
        preview_model = getattr(result, "preview_model", None)
        if isinstance(preview_model, _state.ModelPreviewData) and getattr(preview_model, "meshes", None):
            cloned = _state.self._clone_archive_preview_model(preview_model, strip_images=False)
            return cloned if isinstance(cloned, _state.ModelPreviewData) else preview_model
        return None
    _state._current_hkx_link_preview_model = _current_hkx_link_preview_model

def _dialog_step_0050(_state):
    def _current_embedded_hkx_preview_model() -> Optional[ModelPreviewData]:
        if not hasattr(_state.hkx_link_preview_widget, "current_model_preview"):
            return None
        try:
            preview_model = _state.hkx_link_preview_widget.current_model_preview()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            preview_model = None
        return preview_model if isinstance(preview_model, _state.ModelPreviewData) else None
    _state._current_embedded_hkx_preview_model = _current_embedded_hkx_preview_model

def _dialog_step_0051(_state):
    _state.hkx_preview_placement_state: Dict[str, object] = {"evidence_count": 0, "summary": ""}

def _dialog_step_0052(_state):
    def _refresh_hkx_preview_placement_state() -> None:
        evidence_count = 0
        summary_text = ""
        try:
            graph, _references = _state.self._archive_asset_family_graph_for_entry(_state.entry)
            evidence_count = len(tuple(getattr(graph, "attachment_evidence", ()) or ()))
            summary_text = str(getattr(graph, "summary", "") or "").strip()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            evidence_count = 0
            summary_text = ""
        _state.hkx_preview_placement_state["evidence_count"] = evidence_count
        _state.hkx_preview_placement_state["summary"] = summary_text
    _state._refresh_hkx_preview_placement_state = _refresh_hkx_preview_placement_state

STEPS = (_dialog_step_0017, _dialog_step_0018, _dialog_step_0019, _dialog_step_0020, _dialog_step_0021, _dialog_step_0022, _dialog_step_0023, _dialog_step_0024, _dialog_step_0025, _dialog_step_0026, _dialog_step_0027, _dialog_step_0028, _dialog_step_0029, _dialog_step_0030, _dialog_step_0031, _dialog_step_0032, _dialog_step_0033, _dialog_step_0034, _dialog_step_0035, _dialog_step_0036, _dialog_step_0037, _dialog_step_0038, _dialog_step_0039, _dialog_step_0040, _dialog_step_0041, _dialog_step_0042, _dialog_step_0043, _dialog_step_0044, _dialog_step_0045, _dialog_step_0046, _dialog_step_0047, _dialog_step_0048, _dialog_step_0049, _dialog_step_0050, _dialog_step_0051, _dialog_step_0052,)
