from __future__ import annotations

from types import SimpleNamespace

def _dialog_step_0143(_state):
    def _sync_scrollbars(value: int) -> None:
        _state.line_numbers.verticalScrollBar().setValue(value)
    _state._sync_scrollbars = _sync_scrollbars

def _dialog_step_0144(_state):
    def _toggle_wrap(checked: bool) -> None:
        mode = _state.QPlainTextEdit.LineWrapMode.WidgetWidth if checked else _state.QPlainTextEdit.LineWrapMode.NoWrap
        _state.editor.setLineWrapMode(mode)
        _state._update_line_numbers()
    _state._toggle_wrap = _toggle_wrap

def _dialog_step_0145(_state):
    def _set_workflow_summary_visible(visible: bool) -> None:
        if visible:
            _state.overview_workspace_tabs.setCurrentWidget(_state.workflow_summary_page)
    _state._set_workflow_summary_visible = _set_workflow_summary_visible

def _dialog_step_0146(_state):
    def _set_overview_report_visible(visible: bool) -> None:
        if visible:
            _state.overview_workspace_tabs.setCurrentWidget(_state.overview_report_page)
        _state.overview_filler.setVisible(False)
    _state._set_overview_report_visible = _set_overview_report_visible

def _dialog_step_0147(_state):
    def _set_browser_advanced_visible(visible: bool) -> None:
        _state.browser_advanced_panel.setVisible(bool(visible))
        _state.section_nav_list.setVisible(not bool(visible))
        _state.browser_summary_label.setVisible(not bool(visible))
        _state.section_advanced_views_toggle.setVisible(not bool(visible))
    _state._set_browser_advanced_visible = _set_browser_advanced_visible

def _dialog_step_0148(_state):
    _state.editor.textChanged.connect(_state._update_line_numbers)
    _state.editor.cursorPositionChanged.connect(_state._update_cursor_status)
    _state.editor.verticalScrollBar().valueChanged.connect(_state._sync_scrollbars)
    _state.find_button.clicked.connect(_state._find_next)
    _state.search_edit.returnPressed.connect(_state._find_next)
    _state.wrap_checkbox.toggled.connect(_state._toggle_wrap)
    _state.workflow_summary_toggle.toggled.connect(_state._set_workflow_summary_visible)
    _state.overview_report_toggle.toggled.connect(_state._set_overview_report_visible)
    _state.section_combo.currentIndexChanged.connect(_state._set_hkx_editor_section)
    _state.section_nav_list.currentRowChanged.connect(_state._set_hkx_editor_section)
    _state.tab_widget.currentChanged.connect(_state._sync_hkx_editor_section_selector)
    _state.section_advanced_views_toggle.toggled.connect(_state._refresh_section_nav_visibility)
    _state.browser_advanced_toggle.toggled.connect(_state._set_browser_advanced_visible)
    _state.refresh_structured_button.clicked.connect(_state._populate_tuning_tree)
    _state.workspace_task_combo.currentIndexChanged.connect(lambda _index: _state._refresh_modding_workspace_from_editor())
    _state.workspace_filter_edit.textChanged.connect(lambda _text: _state._refresh_modding_workspace_from_editor())
    _state.modding_workspace_tree.currentItemChanged.connect(
        lambda current, _previous: _state._update_modding_workspace_detail(current)
    )
    _state.modding_workspace_tree.itemDoubleClicked.connect(
        lambda item, _column: (_state.modding_workspace_tree.setCurrentItem(item), _state._show_selected_workspace_row_values())
    )
    _state.edit_tuning_value_button.clicked.connect(_state._edit_selected_tuning_value)
    _state.tuning_editable_only_checkbox.toggled.connect(_state._populate_tuning_tree)
    _state.tuning_filter_edit.textChanged.connect(_state._apply_tuning_filter)
    _state.collision_filter_edit.textChanged.connect(_state._apply_collision_filter)
    _state.refresh_collision_button.clicked.connect(_state._populate_collision_tree)
    _state.edit_collision_value_button.clicked.connect(_state._edit_selected_collision_value)
    _state.refresh_object_layout_button.clicked.connect(_state._populate_object_layout_tree)
    _state.refresh_context_button.clicked.connect(_state._populate_context_hints_tree)
    _state.refresh_body_summary_button.clicked.connect(_state._populate_body_summary_tree)
    _state.refresh_constraint_summary_button.clicked.connect(_state._populate_constraint_summary_tree)
    _state.refresh_catalog_button.clicked.connect(_state._populate_editable_catalog_tree)
    _state.editable_catalog_filter_edit.textChanged.connect(_state._apply_editable_catalog_filter)
    _state.refresh_byte_map_button.clicked.connect(_state._populate_byte_map_tree)
    _state.byte_map_filter_edit.textChanged.connect(_state._apply_byte_map_filter)
    _state.connected_target_filter_edit.textChanged.connect(_state._apply_connected_physics_filter)
    _state.connected_workflow_combo.currentIndexChanged.connect(_state._apply_connected_physics_filter)
    _state.connected_risk_combo.currentIndexChanged.connect(_state._apply_connected_physics_filter)
    _state.connected_open_button.clicked.connect(_state._focus_selected_connected_physics)
    _state.connected_highlight_button.clicked.connect(_state._highlight_selected_connected_physics)
    _state.workflow_show_values_button.clicked.connect(_state._show_selected_workflow_values)
    _state.workflow_show_connected_button.clicked.connect(_state._show_selected_workflow_connections)
    _state.workflow_show_safe_catalog_button.clicked.connect(_state._show_selected_workflow_safe_catalog)
    _state.workflow_show_guide_button.clicked.connect(_state._show_workflow_overview_text)
    _state.workflow_guide_tree.currentItemChanged.connect(lambda current, _previous: _state._update_workflow_detail(current))
    _state.workflow_guide_tree.itemDoubleClicked.connect(lambda _item, _column: _state._show_selected_workflow_values())
    _state.preview_toggle_button.toggled.connect(lambda checked: _state._set_hkx_preview_panel_visible(bool(checked), refresh=bool(checked)))
    _state.hkx_preview_hide_button.clicked.connect(lambda: _state._set_hkx_preview_panel_visible(False))
    _state.hkx_preview_refresh_button.clicked.connect(lambda: (_state._set_hkx_preview_panel_visible(True), _state._refresh_hkx_link_preview_model()))
    _state.hkx_preview_load_model_button.clicked.connect(_state._choose_and_load_hkx_embedded_preview_model)
    _state.hkx_preview_skeleton_checkbox.toggled.connect(_state._sync_hkx_preview_context_skeleton_visibility)
    _state.focus_constraint_tuning_button.clicked.connect(_state._focus_selected_constraint_slot_in_tuning)
    _state.focus_catalog_button.clicked.connect(_state._focus_selected_catalog_field)
    _state.browser_show_editor_button.clicked.connect(_state._show_browser_row_in_editor)
    _state.browser_show_xml_button.clicked.connect(_state._show_browser_row_in_xml)
    _state.browser_show_preview_button.clicked.connect(_state._show_browser_row_in_preview)
    _state.overlay_bridge_widgets = [
        preview
        for preview in _state._hkx_overlay_preview_widgets()
        if hasattr(preview, "physics_overlay_target_selected")
    ]
    for _state.preview in _state.overlay_bridge_widgets:
        _state.preview.physics_overlay_target_selected.connect(_state._show_preview_overlay_target_in_hkx_editor)

    if _state.overlay_bridge_widgets:
        def _disconnect_hkx_overlay_selection_bridge(_result: int = 0) -> None:
            for preview in _state.overlay_bridge_widgets:
                try:
                    preview.physics_overlay_target_selected.disconnect(_state._show_preview_overlay_target_in_hkx_editor)
                except (RuntimeError, TypeError):
                    pass
                if hasattr(preview, "set_physics_overlay_edited_targets"):
                    preview.set_physics_overlay_edited_targets(())
            if _state.archive_preview_original_settings is not None:
                try:
                    _state.self.archive_model_preview.set_render_settings(_state.archive_preview_original_settings)
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass
            if _state.archive_preview_original_bones_visible is not None and hasattr(_state.self.archive_model_preview, "set_physics_overlay_bones_visible"):
                try:
                    _state.self.archive_model_preview.set_physics_overlay_bones_visible(bool(_state.archive_preview_original_bones_visible))
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass
            try:
                _state.hkx_link_preview_widget.clear_model("HKX editor 3D preview closed.", release_gl=True)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        _state._disconnect_hkx_overlay_selection_bridge = _disconnect_hkx_overlay_selection_bridge

        _state.dialog.finished.connect(_state._disconnect_hkx_overlay_selection_bridge)
    _state.hkx_browser_tree.currentItemChanged.connect(_state._handle_browser_selection)
    _state.browser_filter_edit.textChanged.connect(_state._apply_hkx_browser_filter)
    _state.browser_follow_preview_checkbox.toggled.connect(
        lambda checked: _state._handle_browser_selection(_state.hkx_browser_tree.currentItem(), None) if checked else None
    )
    _state.browser_editable_only_checkbox.toggled.connect(_state._apply_hkx_browser_filter)
    _state.browser_preview_linked_checkbox.toggled.connect(_state._apply_hkx_browser_filter)
    _state.browser_decoded_only_checkbox.toggled.connect(_state._apply_hkx_browser_filter)
    _state.browser_raw_preserved_checkbox.toggled.connect(_state._apply_hkx_browser_filter)
    _state.tuning_tree.itemChanged.connect(_state._handle_tuning_item_changed)
    _state.tuning_tree.itemDoubleClicked.connect(_state._edit_tuning_value_from_cell)
    _state.tuning_tree.currentItemChanged.connect(
        lambda current, previous: (
            _state._update_tuning_guidance(current, previous),
            _state._update_comparison_text_from_item(current, value_column=5, guidance_column=7),
        )
    )
    _state.collision_tree.itemDoubleClicked.connect(lambda item, _column: (_state.collision_tree.setCurrentItem(item, 4), _state._edit_selected_collision_value()))
    _state.collision_tree.currentItemChanged.connect(lambda current, _previous: _state._update_comparison_text_from_item(current, value_column=4))
    _state.constraint_summary_tree.itemDoubleClicked.connect(_state._focus_constraint_slot_from_cell)
    _state.editable_catalog_tree.itemDoubleClicked.connect(_state._focus_catalog_field_from_cell)
    _state.collision_tree.itemChanged.connect(_state._handle_collision_item_changed)
    _state.connected_tree.itemDoubleClicked.connect(lambda item, _column: (_state.connected_tree.setCurrentItem(item), _state._focus_selected_connected_physics()))

def _dialog_step_0149(_state):
    _state.connected_tree.currentItemChanged.connect(
        lambda current, _previous: (
            _state._update_comparison_text_from_item(current),
            _state._update_connected_detail_text(current),
        )
    )
    _state.decoder_tree.currentItemChanged.connect(lambda current, _previous: _state._update_decoder_evidence_detail(current))
    _state._update_line_numbers()
    _state._update_cursor_status()
    _state.initial_root = _state._load_xml_root_from_editor()
    if _state.initial_root is not None:
        _state._populate_overview(_state.initial_root)
        _state._populate_hkx_browser_tree(_state.initial_root)
    _state._populate_tuning_tree()
    _state._populate_collision_tree()
    _state._populate_object_layout_tree()
    _state._populate_context_hints_tree()
    _state._populate_body_summary_tree()
    _state._populate_constraint_summary_tree()
    _state._populate_editable_catalog_tree()
    _state._populate_byte_map_tree()
    _state._populate_connected_physics_tree()
    _state._populate_decoder_evidence_tree()
    _state._refresh_hkx_preview_placement_state()
    _state.hkx_preview_status_label.setText(
        "Embedded 3D Preview is hidden. Click Show 3D, then Load Model to choose a related .pac/.pam/.pamlod from the scanned archive."
        + _state._hkx_preview_placement_status_suffix()
    )
    _state._sync_hkx_edited_overlay_targets(_state.initial_root)
    _state._refresh_section_nav_visibility()
    _state.requested_initial_section = str(_state.initial_section or "").strip().casefold()
    _state.initial_section_index = 0
    if _state.requested_initial_section:
        for _state.section_index in range(_state.tab_widget.count()):
            if _state.tab_widget.tabText(_state.section_index).strip().casefold() == _state.requested_initial_section:
                _state.initial_section_index = _state.section_index
                break
    _state._set_hkx_editor_section(_state.initial_section_index)
    _state._sync_browser_action_buttons()

    _state.button_row = _state.QHBoxLayout()
    _state.button_row.setContentsMargins(0, 6, 0, 0)
    _state.button_row.setSpacing(8)
    _state.export_button = _state.QPushButton("Export XML...")
    _state.reset_selected_button = _state.QPushButton("Reset Selected Value")
    _state.reset_all_button = _state.QPushButton("Reset All Changes")
    _state.mod_preview_button = _state.QPushButton("Preview HKX Mod...")
    _state.mod_preview_button.setToolTip("Show the fixed-size HKX value edits that would be written before creating a loose mod package.")
    _state.write_button = _state.QPushButton("Write Loose Mod...")
    _state.close_button = _state.QPushButton("Close")
    _state.button_row.addWidget(_state.export_button)
    _state.button_row.addWidget(_state.reset_selected_button)
    _state.button_row.addWidget(_state.reset_all_button)
    _state.button_row.addStretch(1)
    _state.button_row.addWidget(_state.mod_preview_button)
    _state.button_row.addWidget(_state.write_button)
    _state.button_row.addWidget(_state.close_button)
    _state.layout.addLayout(_state.button_row)

def _dialog_step_0150(_state):
    def _export_editor_xml() -> None:
        selected, _selected_filter = _state.QFileDialog.getSaveFileName(
            _state.dialog,
            "Export Edited HKX XML",
            str(_state.self._default_archive_hkx_xml_path(_state.entry)),
            "HKX Geometry XML (*.geometry.xml *.xml);;XML (*.xml)",
        )
        if not selected:
            return
        output_path = _state.Path(selected)
        if not output_path.suffix:
            output_path = output_path.with_name(f"{output_path.name}.geometry.xml")
        _state.start_hkx_editor_xml_export(_state.self, output_path, _state.editor.toPlainText(), message_parent=_state.dialog)
    _state._export_editor_xml = _export_editor_xml

def _dialog_step_0151(_state):
    def _refresh_hkx_editor_views() -> None:
        refreshed_root = _state._load_xml_root_from_editor()
        if refreshed_root is not None:
            _state._populate_overview(refreshed_root)
            _state._populate_hkx_browser_tree(refreshed_root)
        _state._populate_tuning_tree()
        _state._populate_collision_tree()
        _state._populate_object_layout_tree()
        _state._populate_context_hints_tree()
        _state._populate_body_summary_tree()
        _state._populate_constraint_summary_tree()
        _state._populate_editable_catalog_tree()
        _state._populate_byte_map_tree()
        _state._populate_connected_physics_tree()
        _state._populate_decoder_evidence_tree()
        _state._update_line_numbers()
        _state._update_cursor_status()
        _state._refresh_dirty_status()
    _state._refresh_hkx_editor_views = _refresh_hkx_editor_views

def _dialog_step_0152(_state):
    def _reset_selected_value() -> None:
        current_index = _state.tab_widget.currentIndex()
        if current_index == 1:
            item = _state.tuning_tree.currentItem()
            if item is not None and item.parent() is not None:
                key = item.data(5, _state.Qt.ItemDataRole.UserRole)
                original = item.data(5, _state.ORIGINAL_VALUE_ROLE)
                if isinstance(key, tuple) and original not in (None, ""):
                    item.setText(5, str(original))
                    return
        if current_index == 2:
            item = _state.collision_tree.currentItem()
            if item is not None and item.parent() is not None:
                key = item.data(4, _state.Qt.ItemDataRole.UserRole)
                original = item.data(4, _state.ORIGINAL_VALUE_ROLE)
                if isinstance(key, tuple) and original not in (None, ""):
                    item.setText(4, str(original))
                    return
        _state.QMessageBox.information(_state.dialog, "Reset HKX Value", "Select a patchable value in Patchable Values or Collision Shapes first.")
    _state._reset_selected_value = _reset_selected_value

def _dialog_step_0153(_state):
    def _reset_all_changes() -> None:
        if not _state.dirty_values_by_key:
            _state.QMessageBox.information(_state.dialog, "Reset HKX Changes", "There are no edited HKX values to reset.")
            return
        answer = _state.QMessageBox.question(
            _state.dialog,
            "Reset HKX Changes",
            f"Reset {len(_state.dirty_values_by_key):,} edited HKX value(s) back to the original exported XML?",
        )
        if answer != _state.QMessageBox.StandardButton.Yes:
            return
        _state.dirty_values_by_key.clear()
        _state.initial_values_by_key.clear()
        _state.editor.blockSignals(True)
        _state.editor.setPlainText(_state.document_text)
        _state.editor.blockSignals(False)
        _state._refresh_hkx_editor_views()
    _state._reset_all_changes = _reset_all_changes

def _dialog_step_0154(_state):
    def _byte_patch_entry_for_dirty_key(root: ET.Element, prefix: str, key: tuple) -> Optional[ET.Element]:
        if prefix == "tuning" and len(key) == 3:
            record_index, item_index, local_offset = (str(key[0]), str(key[1]), str(key[2]))
            for entry_element in root.findall("./bytePatchMap/entries/entry"):
                if (
                    str(entry_element.get("record_index") or "") == record_index
                    and str(entry_element.get("item_index") or "") == item_index
                    and str(entry_element.get("local_offset") or entry_element.get("relative_offset") or "") == local_offset
                    and str(entry_element.get("import_safety") or "import_safe") == "import_safe"
                ):
                    return entry_element
            return None
        if prefix != "collision" or not key:
            return None
        kind = str(key[0])
        path = ""
        shape_index = str(key[1]) if len(key) > 1 else ""
        if kind in {"sphere_radius", "capsule_radius"} and len(key) >= 3:
            path = f"shapes[{shape_index}].{kind}"
        elif kind == "shape_vector" and len(key) == 6:
            _kind, shape_index, vector_field, _element_name, row_index, component = key
            path = f"shapes[{shape_index}].{vector_field}[{row_index}].{component}"
        elif kind == "mass_properties" and len(key) == 4:
            _kind, shape_index, row_index, component = key
            path = f"shapes[{shape_index}].mass_properties.float_rows[{row_index}].{component}"
        elif kind == "shape_payload" and len(key) == 4:
            _kind, shape_index, offset, _component = key
            for entry_element in root.findall("./bytePatchMap/entries/entry"):
                if (
                    str(entry_element.get("path") or "").startswith(f"shapes[{shape_index}].shape_payload.")
                    and str(entry_element.get("local_offset") or entry_element.get("relative_offset") or "") == str(offset)
                    and str(entry_element.get("import_safety") or "import_safe") == "import_safe"
                ):
                    return entry_element
            return None
        if not path:
            return None
        for entry_element in root.findall("./bytePatchMap/entries/entry"):
            if (
                str(entry_element.get("path") or "") == path
                and str(entry_element.get("import_safety") or "import_safe") == "import_safe"
            ):
                return entry_element
        return None
    _state._byte_patch_entry_for_dirty_key = _byte_patch_entry_for_dirty_key

def _dialog_step_0155(_state):
    def _hkx_mod_package_change_rows() -> Tuple[List[Dict[str, str]], List[str]]:
        root = _state._load_xml_root_from_editor()
        if root is None:
            return [], ["Current HKX XML could not be parsed."]
        rows: List[Dict[str, str]] = []
        blocked: List[str] = []
        for dirty_key, dirty_values in _state.dirty_values_by_key.items():
            prefix = str(dirty_key[0]) if isinstance(dirty_key, tuple) and dirty_key else ""
            key = tuple(dirty_key[1]) if isinstance(dirty_key, tuple) and len(dirty_key) > 1 and isinstance(dirty_key[1], tuple) else ()
            label, original_value, current_value = dirty_values
            entry_element = _state._byte_patch_entry_for_dirty_key(root, prefix, key)
            if entry_element is None:
                blocked.append(f"{label}: no approved byte patch map entry")
                continue
            gate_status = str(entry_element.get("gate_status") or "enabled")
            import_safety = str(entry_element.get("import_safety") or "import_safe")
            structural_kind = str(entry_element.get("structural_kind") or "")
            if gate_status not in {"enabled", ""} or import_safety != "import_safe" or structural_kind == "structural_blocked":
                blocked.append(
                    f"{label}: {import_safety or 'unknown safety'}, gate={gate_status or 'unknown'}, kind={structural_kind or 'unknown'}"
                )
                continue
            rows.append(
                {
                    "label": str(label),
                    "task": str(entry_element.get("task_label") or entry_element.get("category_label") or entry_element.get("task_category") or ""),
                    "category": str(entry_element.get("category") or ""),
                    "owner_class": str(entry_element.get("owner_class") or entry_element.get("subject") or ""),
                    "member": str(entry_element.get("member") or entry_element.get("field") or entry_element.get("name") or ""),
                    "record": str(entry_element.get("record_index") or ""),
                    "item": str(entry_element.get("item_index") or "-"),
                    "offset": str(
                        entry_element.get("absolute_offset_hex")
                        or entry_element.get("hex_absolute_data_offset")
                        or entry_element.get("absolute_data_offset")
                        or ""
                    ),
                    "local_offset": str(entry_element.get("hex_relative_offset") or entry_element.get("relative_offset") or ""),
                    "byte_size": str(entry_element.get("byte_size") or ""),
                    "original": str(original_value),
                    "current": str(current_value),
                    "risk": str(entry_element.get("risk_label") or entry_element.get("risk") or ""),
                    "evidence": str(
                        entry_element.get("linked_by")
                        or entry_element.get("link_evidence")
                        or entry_element.get("evidence")
                        or ""
                    ),
                    "path": str(entry_element.get("path") or ""),
                    "import_behavior": str(entry_element.get("import_behavior") or "CDMW fixed-size patch into original HKX bytes"),
                }
            )
        return rows, blocked
    _state._hkx_mod_package_change_rows = _hkx_mod_package_change_rows

def _dialog_step_0156(_state):
    def _hkx_mod_package_preview_text() -> str:
        root = _state._load_xml_root_from_editor()
        readiness = root.find("./hkxModdingReadiness") if root is not None else None
        byte_patch_map = root.find("./bytePatchMap") if root is not None else None
        hkx_edit_gate = root.find("./hkxEditGateV1") if root is not None else None
        change_rows, blocked_rows = _state._hkx_mod_package_change_rows()
        lines = [
            f"Target HKX: {_state.entry.path}",
            "",
        ]
        if readiness is not None:
            labels = [
                str(element.text or "").strip()
                for element in readiness.findall("./readinessLabels/label")
                if str(element.text or "").strip()
            ]
            lines.append(f"Readiness: {readiness.get('per_file_label') or readiness.get('status') or 'unknown'}")
            if labels:
                lines.append("Evidence: " + ", ".join(labels))
            lines.append(f"Import path: {readiness.get('modding_path') or 'CDMW fixed-size patch XML/JSON only'}")
            lines.append(f"Havok XML importable: {readiness.get('havok_xml_importable') or 'false'}")
            gate = readiness.find("./semanticWriterGate")
            if gate is not None:
                lines.append(f"Semantic writer: {gate.get('status') or 'disabled'} ({gate.get('mode') or 'fixed_size_patch_only'})")
            lines.append("")
        if hkx_edit_gate is not None:
            lines.append(
                "Edit gate: "
                f"{hkx_edit_gate.get('status') or 'unknown'} | "
                f"enabled={hkx_edit_gate.get('write_enabled_candidate_count') or '0'} | "
                f"candidate-only={hkx_edit_gate.get('candidate_only_count') or '0'}"
            )
            lines.append("")
        if change_rows:
            lines.append(f"Pending import-safe fixed-size value edits: {len(change_rows):,}")
            for row in change_rows[:64]:
                lines.append(
                    "- "
                    f"{row['label']} | task={row['task'] or row['category'] or 'unknown'} | "
                    f"class={row['owner_class'] or 'unknown'} | member={row['member'] or 'unknown'} | "
                    f"record={row['record']} item={row['item']} | "
                    f"offset={row['offset']} local={row['local_offset']} size={row['byte_size']} | "
                    f"{row['original']} -> {row['current']} | risk={row['risk'] or 'unknown'} | evidence={row['evidence'] or 'unknown'}"
                )
            if len(change_rows) > 64:
                lines.append(f"- ... {len(change_rows) - 64:,} more")
        else:
            lines.append("Pending fixed-size value edits: 0")
            lines.append("No loose HKX patch will be written unless a patchable value changes.")
        if blocked_rows:
            lines.append("")
            lines.append(f"Blocked edited rows: {len(blocked_rows):,}")
            for row in blocked_rows[:32]:
                lines.append(f"- {row}")
            if len(blocked_rows) > 32:
                lines.append(f"- ... {len(blocked_rows) - 32:,} more")
        if byte_patch_map is not None:
            lines.append("")
            lines.append(
                "Patch map: "
                f"{byte_patch_map.get('entry_count') or '0'} fixed-size target(s), "
                f"status={byte_patch_map.get('status') or 'unknown'}"
            )
        lines.extend(
            [
                "",
                "Blocked by policy: Havok XML import, array count edits, reference edits, string edits, and topology edits.",
                "Game archives are not modified; successful writes produce a loose mod package.",
            ]
        )
        return "\n".join(lines)
    _state._hkx_mod_package_preview_text = _hkx_mod_package_preview_text

def _dialog_step_0157(_state):
    def _show_hkx_mod_package_preview() -> None:
        preview_dialog = _state.QDialog(_state.dialog)
        preview_dialog.setWindowTitle("HKX Mod Package Preview")
        preview_dialog.resize(980, 620)
        preview_layout = _state.QVBoxLayout(preview_dialog)
        preview_text = _state.QPlainTextEdit()
        preview_text.setReadOnly(True)
        preview_text.setLineWrapMode(_state.QPlainTextEdit.LineWrapMode.NoWrap)
        preview_text.setFont(_state.build_monospace_font(_state.self.settings))
        preview_text.setPlainText(_state._hkx_mod_package_preview_text())
        preview_layout.addWidget(preview_text)
        close_preview_button = _state.QPushButton("Close")
        close_preview_button.clicked.connect(preview_dialog.accept)
        preview_button_row = _state.QHBoxLayout()
        preview_button_row.addStretch(1)
        preview_button_row.addWidget(close_preview_button)
        preview_layout.addLayout(preview_button_row)
        preview_dialog.exec()
    _state._show_hkx_mod_package_preview = _show_hkx_mod_package_preview

def _dialog_step_0158(_state):
    def _write_loose_mod() -> None:
        edited_text = _state.editor.toPlainText()
        if not edited_text.strip():
            _state.QMessageBox.warning(_state.dialog, "Write HKX Loose Mod", "The HKX XML editor is empty.")
            return
        if _state.dirty_values_by_key:
            change_rows, blocked_rows = _state._hkx_mod_package_change_rows()
            if blocked_rows:
                _state.QMessageBox.warning(
                    _state.dialog,
                    "Write HKX Loose Mod",
                    (
                        "One or more edited rows are not backed by the current import-safe byte patch map.\n\n"
                        + "\n".join(f"- {row}" for row in blocked_rows[:16])
                        + ("\n- ..." if len(blocked_rows) > 16 else "")
                    ),
                )
                return
            if not change_rows:
                _state.QMessageBox.information(
                    _state.dialog,
                    "Write HKX Loose Mod",
                    "No approved fixed-size HKX byte changes are pending.",
                )
                return
            preview_lines = _state._hkx_mod_package_preview_text().splitlines()
            preview_lines.append("")
            preview_lines.append("Game archives will not be modified. Continue writing the loose mod package?")
            answer = _state.QMessageBox.question(_state.dialog, "Write HKX Loose Mod", "\n".join(preview_lines[:80]))
            if answer != _state.QMessageBox.StandardButton.Yes:
                return
        _state.dialog.accept()
        _state.self._start_current_archive_hkx_document_import_content(
            entry=_state.entry,
            document_text=edited_text,
            document_source_label="the in-app HKX XML editor",
            document_label="XML",
            apply_document=_state.apply_hkx_editable_geometry_xml,
        )
    _state._write_loose_mod = _write_loose_mod

def _dialog_step_0159(_state):
    _state.export_button.clicked.connect(_state._export_editor_xml)
    _state.reset_selected_button.clicked.connect(_state._reset_selected_value)
    _state.reset_all_button.clicked.connect(_state._reset_all_changes)
    _state.mod_preview_button.clicked.connect(_state._show_hkx_mod_package_preview)
    _state.write_button.clicked.connect(_state._write_loose_mod)
    _state.close_button.clicked.connect(_state.dialog.reject)
    _state.dialog.exec()

STEPS = (_dialog_step_0143, _dialog_step_0144, _dialog_step_0145, _dialog_step_0146, _dialog_step_0147, _dialog_step_0148, _dialog_step_0149, _dialog_step_0150, _dialog_step_0151, _dialog_step_0152, _dialog_step_0153, _dialog_step_0154, _dialog_step_0155, _dialog_step_0156, _dialog_step_0157, _dialog_step_0158, _dialog_step_0159,)
