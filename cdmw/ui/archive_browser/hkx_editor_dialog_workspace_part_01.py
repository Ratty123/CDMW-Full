from __future__ import annotations

from types import SimpleNamespace

def _dialog_step_0066(_state):
    def _style_modding_workspace_item(item: QTreeWidgetItem) -> None:
        safety = str(item.text(1) or "")
        risk = str(item.text(2) or "").casefold()
        linked_by = str(item.text(4) or "")
        if safety == "Import-safe":
            item.setForeground(1, _state.QBrush(_state.QColor("#9fd0ff")))
            item.setForeground(0, _state.QBrush(_state.QColor("#dbeafe")))
        elif safety == "Read-only candidate":
            item.setForeground(1, _state.QBrush(_state.QColor("#fde68a")))
            item.setForeground(0, _state.QBrush(_state.QColor("#e5e7eb")))
        elif safety == "Structural blocked":
            item.setForeground(1, _state.QBrush(_state.QColor("#fca5a5")))
            item.setForeground(0, _state.QBrush(_state.QColor("#cbd5e1")))
        if "low" in risk or "existing" in risk:
            item.setForeground(2, _state.QBrush(_state.QColor("#86efac")))
        elif "medium" in risk or "required" in risk:
            item.setForeground(2, _state.QBrush(_state.QColor("#fde68a")))
        elif risk:
            item.setForeground(2, _state.QBrush(_state.QColor("#fca5a5")))
        if linked_by in {"Fixup-backed", "Owner-array"}:
            item.setForeground(4, _state.QBrush(_state.QColor("#67e8f9")))
        elif linked_by == "Inferred":
            item.setForeground(4, _state.QBrush(_state.QColor("#fde68a")))
        elif linked_by:
            item.setForeground(4, _state.QBrush(_state.QColor("#cbd5e1")))
    _state._style_modding_workspace_item = _style_modding_workspace_item

def _dialog_step_0067(_state):
    def _populate_modding_workspace(root: ET.Element) -> None:
        _state.modding_workspace_tree.clear()
        selected_key = str(_state.workspace_task_combo.currentData() or "collision_size")
        text_filter = str(_state.workspace_filter_edit.text() or "").strip().casefold()
        workspace = root.find("./moddingWorkspaceV1")
        readiness = root.find("./hkxModdingReadiness")
        if workspace is None:
            _state.modding_workspace_status_label.setText(
                "HKX Edit Readiness: no workspace evidence found. Use Decoder Evidence or XML / Raw for the current file."
            )
            return
        task_counts: Dict[str, Tuple[int, int, int]] = {}
        for task in workspace.findall("./taskFilters/task"):
            key = str(task.get("key") or "")
            try:
                patchable = int(task.get("patchable_count") or "0")
            except ValueError:
                patchable = 0
            try:
                candidate = int(task.get("candidate_only_count") or "0")
            except ValueError:
                candidate = 0
            try:
                blocked = int(task.get("blocked_count") or "0")
            except ValueError:
                blocked = 0
            task_counts[key] = (patchable, candidate, blocked)
        _state.workspace_task_combo.blockSignals(True)
        for index in range(_state.workspace_task_combo.count()):
            key = str(_state.workspace_task_combo.itemData(index) or "")
            label = _state._workspace_task_label_for_key(key)
            patchable, candidate, blocked = task_counts.get(key, (0, 0, 0))
            suffix = f" ({patchable} / {candidate}+{blocked})" if patchable or candidate or blocked else ""
            _state.workspace_task_combo.setItemText(index, label + suffix)
        _state.workspace_task_combo.blockSignals(False)
        rows = list(workspace.findall("./rows/row"))
        groups: Dict[str, _state.QTreeWidgetItem] = {}
        shown = 0
        for row_element in rows:
            row_task = str(row_element.get("task") or "")
            if selected_key != "inspect_only" and row_task != selected_key:
                continue
            row_text = " ".join(str(value or "") for value in row_element.attrib.values()).casefold()
            if text_filter and text_filter not in row_text:
                continue
            group_label = _state._workspace_group_for_row(row_element)
            group = groups.get(group_label)
            if group is None:
                group = _state.QTreeWidgetItem((group_label, "", "", "", "", "", "", "", "", ""))
                group.setData(0, _state.BROWSER_DATA_ROLE, {"kind": "modding_workspace_group", "label": group_label})
                group.setFirstColumnSpanned(True)
                group.setToolTip(
                    0,
                    "Import-safe rows can be edited through existing fixed-size CDMW patch paths. Candidate and structural rows are browsing evidence only.",
                )
                groups[group_label] = group
                _state.modding_workspace_tree.addTopLevelItem(group)
            details = " | ".join(
                part
                for part in (
                    row_element.get("label"),
                    row_element.get("owner_class"),
                    row_element.get("member"),
                    row_element.get("relationship_chain"),
                    row_element.get("gate_reason"),
                )
                if str(part or "").strip()
            )
            item = _state.QTreeWidgetItem(
                (
                    str(row_element.get("meaning") or row_element.get("label") or ""),
                    str(row_element.get("import_safety") or ""),
                    str(row_element.get("risk") or ""),
                    str(row_element.get("evidence") or row_element.get("structural_kind") or ""),
                    str(row_element.get("linked_by") or ""),
                    str(row_element.get("record") or ""),
                    str(row_element.get("offset") or ""),
                    _state._format_hkx_display_value(str(row_element.get("original") or "")),
                    _state._format_hkx_display_value(str(row_element.get("current") or "")),
                    details,
                )
            )
            item.setData(0, _state.BROWSER_DATA_ROLE, {"kind": "modding_workspace_row", **dict(row_element.attrib)})
            item.setToolTip(0, str(row_element.get("gate_reason") or row_element.get("import_behavior") or ""))
            group.addChild(item)
            _state._style_modding_workspace_item(item)
            shown += 1
        for group_label, group in sorted(groups.items(), key=lambda pair: _state._workspace_group_sort_key(pair[0])):
            group.setText(0, f"{group_label} ({group.childCount():,})")
            group.setExpanded(True)
        _state._style_hkx_tree_values(
            _state.modding_workspace_tree,
            value_columns=(7, 8),
            offset_columns=(6,),
            confidence_column=3,
            guidance_columns=(1, 2, 3, 4, 9),
            patchable_value_column=8,
        )
        for column in range(_state.modding_workspace_tree.columnCount()):
            _state.modding_workspace_tree.resizeColumnToContents(column)
        readiness_label = workspace.get("readiness_label") or (
            readiness.get("per_file_label") if readiness is not None else "HKX readiness"
        )
        _state.modding_workspace_status_label.setText(
            "HKX Edit Readiness: "
            f"{readiness_label or 'unknown'} | "
            f"{_state.workspace_task_combo.currentText()} | "
            f"{shown:,}/{workspace.get('row_count') or '0'} rows"
        )
        _state._set_hkx_editor_section_title(0, f"Modding Workspace ({shown:,})" if shown else "Modding Workspace")
        if _state.modding_workspace_tree.currentItem() is None and _state.modding_workspace_tree.topLevelItemCount() > 0:
            first_group = _state.modding_workspace_tree.topLevelItem(0)
            if first_group is not None and first_group.childCount() > 0:
                _state.modding_workspace_tree.setCurrentItem(first_group.child(0))
    _state._populate_modding_workspace = _populate_modding_workspace

def _dialog_step_0068(_state):
    def _update_modding_workspace_detail(item: Optional[QTreeWidgetItem]) -> None:
        if item is None:
            _state.modding_workspace_detail_text.clear()
            return
        data = item.data(0, _state.BROWSER_DATA_ROLE)
        if not isinstance(data, _state.Mapping) or data.get("kind") != "modding_workspace_row":
            _state.modding_workspace_detail_text.clear()
            return
        lines = [
            str(data.get("label") or data.get("meaning") or "HKX value"),
            f"Task: {data.get('task_label') or data.get('category_label') or data.get('task') or 'Inspect Only'}",
            f"Meaning: {data.get('meaning') or 'Decoded HKX value or candidate.'}",
            f"Import safety: {data.get('import_safety') or 'unknown'} | {data.get('structural_kind') or ''}",
            f"Risk: {data.get('risk') or 'unknown'}",
            f"Evidence: {data.get('evidence') or 'unknown'}",
            f"Linked by: {data.get('linked_by') or 'Context only'}",
            f"Record: {data.get('record') or '-'} | Item: {data.get('item') or '-'} | Offset: {data.get('offset') or '-'} | Size: {data.get('byte_size') or '-'}",
            f"Original: {data.get('original') or '-'}",
            f"Current: {data.get('current') or '-'}",
        ]
        chain = str(data.get("relationship_chain") or "").strip()
        if chain:
            lines.append(f"Relationship chain: {chain}")
        gate_reason = str(data.get("gate_reason") or "").strip()
        if gate_reason:
            lines.append(f"Gate: {gate_reason}")
        if str(data.get("import_safety") or "") != "Import-safe":
            lines.append("This row is not editable unless a fixed-size patch gate approves it.")
        _state.modding_workspace_detail_text.setPlainText("\n".join(lines))
    _state._update_modding_workspace_detail = _update_modding_workspace_detail

def _dialog_step_0069(_state):
    def _show_selected_workspace_row_values() -> None:
        item = _state.modding_workspace_tree.currentItem()
        data = item.data(0, _state.BROWSER_DATA_ROLE) if item is not None else None
        if not isinstance(data, _state.Mapping) or data.get("kind") != "modding_workspace_row":
            return
        label = str(data.get("label") or "")
        owner_class = str(data.get("owner_class") or "")
        member = str(data.get("member") or "")
        record = str(data.get("record") or "")
        filter_text = " ".join(part for part in (record, member, label) if part).strip()
        if "shape" in " ".join((label, owner_class, member)).casefold() or label.startswith("shapes["):
            _state.collision_filter_edit.setText(filter_text)
            _state._populate_collision_tree()
            _state._set_hkx_editor_section(2)
        else:
            _state.tuning_editable_only_checkbox.setChecked(str(data.get("import_safety") or "") == "Import-safe")
            _state.tuning_filter_edit.setText(filter_text)
            _state._populate_tuning_tree()
            _state._set_hkx_editor_section(1)
    _state._show_selected_workspace_row_values = _show_selected_workspace_row_values

def _dialog_step_0070(_state):
    def _refresh_modding_workspace_from_editor() -> None:
        root = _state._load_xml_root_from_editor()
        if root is not None:
            _state._populate_modding_workspace(root)
    _state._refresh_modding_workspace_from_editor = _refresh_modding_workspace_from_editor

def _dialog_step_0071(_state):
    def _update_workflow_detail(item: Optional[QTreeWidgetItem] = None) -> None:
        if item is None:
            item = _state.workflow_guide_tree.currentItem()
        if item is None:
            _state.workflow_detail_text.clear()
            return
        data = item.data(0, _state.BROWSER_DATA_ROLE)
        if isinstance(data, _state.Mapping):
            _state.workflow_detail_text.setPlainText("\n".join(_state._workflow_detail_lines(data)))
            return
        _state.workflow_detail_text.clear()
    _state._update_workflow_detail = _update_workflow_detail

def _dialog_step_0072(_state):
    def _populate_workflow_guide(root: ET.Element) -> None:
        _state.workflow_guide_tree.clear()
        for workflow in _state.WORKFLOW_GUIDES:
            safe_rows, catalog_rows, context_rows = _state._workflow_catalog_counts(root, workflow)
            risk = str(workflow.get("risk") or "Context only")
            if safe_rows <= 0 and context_rows > 0 and risk == "Low":
                risk = "Context only"
            if safe_rows <= 0 and context_rows <= 0:
                risk = "No recovered rows"
            found_text = f"{safe_rows:,} safe"
            context_text = f"{context_rows:,} context"
            item = _state.QTreeWidgetItem(
                (
                    str(workflow.get("area") or workflow.get("goal") or ""),
                    str(workflow.get("likely_edits") or ""),
                    found_text,
                    context_text,
                    risk,
                    str(workflow.get("meaning") or ""),
                )
            )
            data = dict(workflow)
            data["safe_rows"] = safe_rows
            data["catalog_rows"] = catalog_rows
            data["context_rows"] = context_rows
            data["computed_risk"] = risk
            item.setData(0, _state.BROWSER_DATA_ROLE, data)
            if safe_rows > 0:
                item.setForeground(2, _state.QBrush(_state.QColor("#86efac")))
            elif context_rows > 0:
                item.setForeground(3, _state.QBrush(_state.QColor("#fde68a")))
            else:
                item.setForeground(4, _state.QBrush(_state.QColor("#9aa7b4")))
            risk_key = risk.casefold()
            if risk_key in {"low", "safe"}:
                item.setForeground(4, _state.QBrush(_state.QColor("#86efac")))
            elif "medium" in risk_key or "context" in risk_key:
                item.setForeground(4, _state.QBrush(_state.QColor("#fde68a")))
            elif "high" in risk_key or "read-only" in risk_key:
                item.setForeground(4, _state.QBrush(_state.QColor("#fca5a5")))
            item.setToolTip(
                0,
                "Double-click to filter values for this area. Safe rows are importable fixed-size CDMW patch targets; context rows are naming/link evidence.",
            )
            _state.workflow_guide_tree.addTopLevelItem(item)
        for column in range(_state.workflow_guide_tree.columnCount()):
            _state.workflow_guide_tree.resizeColumnToContents(column)
        if _state.workflow_guide_tree.topLevelItemCount() > 0 and _state.workflow_guide_tree.currentItem() is None:
            _state.workflow_guide_tree.setCurrentItem(_state.workflow_guide_tree.topLevelItem(0))
        _state._update_workflow_detail()
    _state._populate_workflow_guide = _populate_workflow_guide

def _dialog_step_0073(_state):
    def _selected_workflow_data() -> Optional[Mapping[str, object]]:
        item = _state.workflow_guide_tree.currentItem()
        if item is None:
            return None
        data = item.data(0, _state.BROWSER_DATA_ROLE)
        return data if isinstance(data, _state.Mapping) else None
    _state._selected_workflow_data = _selected_workflow_data

def _dialog_step_0074(_state):
    def _show_selected_workflow_values() -> None:
        data = _state._selected_workflow_data()
        if not data:
            _state.QMessageBox.information(_state.dialog, "HKX Guide", "Select an area in the readable-area table first.")
            return
        filter_text = str(data.get("filter") or "").strip()
        section = str(data.get("section") or "").strip()
        if section == "Collision Editor":
            _state.collision_filter_edit.setText(filter_text)
            _state._populate_collision_tree()
            _state._set_hkx_editor_section(2)
        elif section == "Structured Editor":
            _state.tuning_editable_only_checkbox.setChecked(True)
            _state.tuning_filter_edit.setText(filter_text)
            _state._populate_tuning_tree()
            _state._set_hkx_editor_section(1)
        elif section == "Connected Physics":
            _state._show_selected_workflow_connections()
        else:
            _state.editable_catalog_filter_edit.setText(filter_text)
            _state._populate_editable_catalog_tree()
            _state._set_hkx_editor_section(7)
        _state.section_summary_label.setText(
            f"Filtered area: {data.get('area') or data.get('goal') or 'selected area'}; showing rows matching {filter_text or 'the selected area'}."
        )
    _state._show_selected_workflow_values = _show_selected_workflow_values

def _dialog_step_0075(_state):
    def _show_selected_workflow_connections() -> None:
        data = _state._selected_workflow_data()
        if not data:
            _state.QMessageBox.information(_state.dialog, "HKX Guide", "Select an area in the readable-area table first.")
            return
        target_filter = str(data.get("connected_filter") or data.get("filter") or "").strip()
        _state.connected_target_filter_edit.setText("")
        matched_combo = False
        for combo_index in range(_state.connected_workflow_combo.count()):
            combo_data = str(_state.connected_workflow_combo.itemData(combo_index) or "")
            if combo_data and combo_data == target_filter:
                _state.connected_workflow_combo.setCurrentIndex(combo_index)
                matched_combo = True
                break
        if not matched_combo:
            _state.connected_workflow_combo.setCurrentIndex(0)
            _state.connected_target_filter_edit.setText(target_filter)
        _state._apply_connected_physics_filter()
        _state._set_hkx_editor_section(9)
        _state.section_summary_label.setText(
            f"Filtered area: {data.get('area') or data.get('goal') or 'selected area'}; Connected Physics is filtered to related rows."
        )
    _state._show_selected_workflow_connections = _show_selected_workflow_connections

def _dialog_step_0076(_state):
    def _show_selected_workflow_safe_catalog() -> None:
        data = _state._selected_workflow_data()
        if not data:
            _state.QMessageBox.information(_state.dialog, "HKX Guide", "Select an area in the readable-area table first.")
            return
        filter_text = str(data.get("filter") or "").strip()
        _state.editable_catalog_filter_edit.setText(filter_text)
        _state._populate_editable_catalog_tree()
        _state._set_hkx_editor_section(7)
        _state.section_summary_label.setText(
            f"Filtered area: {data.get('area') or data.get('goal') or 'selected area'}; Patchable Catalog is filtered to import-safe candidates."
        )
    _state._show_selected_workflow_safe_catalog = _show_selected_workflow_safe_catalog

def _dialog_step_0077(_state):
    def _show_workflow_overview_text() -> None:
        _state._set_hkx_editor_section(0)
        _state.overview_workspace_tabs.setCurrentWidget(_state.overview_report_page)
        _state.overview_report_toggle.setChecked(True)
        _state.overview_text.setFocus()
    _state._show_workflow_overview_text = _show_workflow_overview_text

def _populate_overview_part_001(_state, _frame):
    _state._populate_workflow_guide(_frame.root)
    _state._populate_modding_workspace(_frame.root)
    _frame.report = _frame.root.find('converterReport')
    _frame.decode_gap_summary = _frame.root.find('decodeGapSummary')
    _frame.compatibility = _frame.root.find('cdmwHkxCompatibility')
    _frame.physics = _frame.root.find('physicsSystem')
    _frame.policy = _frame.root.find('reimportPolicy')
    _frame.user_guide = _frame.root.find('userEditingGuide')
    _frame.tuning_groups = _frame.root.findall('./physicsTuning/groups/group')
    _frame.object_elements = _frame.root.findall('./objects/object')
    _frame.shape_elements = _frame.root.findall('./shapes/shape')
    _frame.descriptor_elements = _frame.root.findall('./companionDescriptorHints/descriptor')
    _frame.body_context = _frame.root.find('./physicsBodyContext')
    _frame.constraint_summary = _frame.root.find('./physicsConstraintSummary')
    _frame.editable_catalog = _frame.root.find('./editableFieldCatalog')
    _frame.byte_patch_map = _frame.root.find('./bytePatchMap')
    _frame.parity_report = _frame.root.find('./hkxXmlParityReport')
    _frame.hkclass_readiness = _frame.root.find('./hkclassMetadataReadiness')
    _frame.modding_readiness = _frame.root.find('./hkxModdingReadiness')
    _frame.tagfile_fixups = _frame.root.find('./tagfileReferenceFixups')
    _frame.fixup_semantics = _frame.root.find('./fixupSemanticsReport')
    _frame.lines = [f'Crimson Desert HKX converter overview for {_state.entry.path}', '']

def _populate_overview_part_002(_state, _frame):
    if _frame.modding_readiness is not None:
        _frame.label = _frame.modding_readiness.get('per_file_label') or 'HKX readiness'
        _frame.labels = [str(element.text or '').strip() for element in _frame.modding_readiness.findall('./readinessLabels/label') if str(element.text or '').strip()]
        _frame.patchable_count = _frame.modding_readiness.get('patchable_slot_count') or '0'
        _frame.decoded_count = _frame.modding_readiness.get('decoded_object_count') or '0'
        _frame.fixup_count = _frame.modding_readiness.get('fixup_backed_reference_edge_count') or '0'
        _frame.import_path = _frame.modding_readiness.get('modding_path') or 'CDMW fixed-size patch XML/JSON only'
        _frame.havok_policy = _frame.modding_readiness.get('havok_xml_policy') or 'read_only_view'
        _frame.label_text = f'{_frame.label} | patchable {_frame.patchable_count} | decoded {_frame.decoded_count} | refs {_frame.fixup_count} | CDMW fixed-size patches only'
        _state.modding_readiness_label.setText(_frame.label_text)
        _state.modding_readiness_label.setToolTip(f"{(', '.join(_frame.labels) if _frame.labels else _frame.modding_readiness.get('status') or 'readiness unknown')}\nImport path: {_frame.import_path}\nHavok XML: {_frame.havok_policy}")
        _frame.gate = _frame.modding_readiness.find('./semanticWriterGate')
        _frame.lines.append('Modding readiness:')
        _frame.lines.append(f'  - label: {_frame.label}')
        if _frame.labels:
            _frame.lines.append('  - evidence labels: ' + ', '.join(_frame.labels))
        _frame.lines.append(f'  - patchable slots: {_frame.patchable_count}')
        _frame.lines.append(f'  - decoded objects: {_frame.decoded_count}')
        _frame.lines.append(f"  - Havok XML importable: {_frame.modding_readiness.get('havok_xml_importable') or 'false'}")
        if _frame.gate is not None:
            _frame.lines.append(f"  - semantic writer gate: {_frame.gate.get('status') or 'unknown'}, mode={_frame.gate.get('mode') or 'unknown'}, no-edit={_frame.gate.get('no_edit_binary_writer_status') or 'not_started'}")
        _frame.external_refs = [tool.get('name') or '' for tool in _frame.modding_readiness.findall('./externalToolReferences/tool') if tool.get('name')]
        if _frame.external_refs:
            _frame.lines.append('  - external references: ' + ', '.join(_frame.external_refs[:6]))
        _frame.lines.append('')
    else:
        _state.modding_readiness_label.setText('HKX readiness: fixed-size CDMW patch rows only; Havok-style XML is read-only.')
    if _frame.report is not None:
        _frame.lines.extend([f"Format: {_frame.report.get('format') or 'unknown'}", f"Status: {_frame.report.get('status') or 'unknown'}", f"CDMW HKX compatibility: {_frame.report.get('cdmw_hkx_compatibility_status') or _frame.report.get('status') or 'unknown'}", f"SDK: {_frame.report.get('sdk_version') or 'unknown'}", f"Confidence: {_frame.report.get('confidence') or 'unknown'}", f"ITEM records: {_frame.report.get('item_record_count') or '0'}", f"Editable records: {_frame.report.get('editable_record_count') or '0'}", f"Decoded coverage: {_frame.report.get('decoded_coverage') or '0'}", ''])
        _frame.status_lines = [f"{_state._hkx_status_display(status.get('name'))[0]} ({status.get('name')}): {status.get('count')}" for status in _frame.report.findall('./recordStatusCounts/status')]
        if _frame.status_lines:
            _frame.lines.append('Record status counts:')
            _frame.lines.extend((f'  - {line}' for line in _frame.status_lines))
            _frame.lines.append('')
        _frame.target_lines = [f"{target.get('type_name')}: {target.get('coverage_status')} ({target.get('record_count')} record(s), editable={target.get('editable_slot_count')})" for target in _frame.report.findall('./schemaTargetCoverage/target') if target.get('present') == 'true']
        if _frame.target_lines:
            _frame.lines.append('Schema target coverage:')
            _frame.lines.extend((f'  - {line}' for line in _frame.target_lines[:10]))
            if len(_frame.target_lines) > 10:
                _frame.lines.append(f'  - ... {len(_frame.target_lines) - 10:,} more target type(s)')
            _frame.lines.append('')
        _frame.unknown_lines = [f"#{area.get('priority_rank')} {area.get('type_name')}: {area.get('unresolved_byte_count') or area.get('raw_preserved_byte_count')} unresolved byte(s), {area.get('unresolved_reason') or 'unknown'}" for area in _frame.report.findall('./failedOrUnknownSchemaAreas/area')]
        if _frame.unknown_lines:
            _frame.lines.append('Top unknown schema areas:')
            _frame.lines.extend((f'  - {line}' for line in _frame.unknown_lines[:8]))
            _frame.lines.append('')
    if _frame.decode_gap_summary is not None:
        _frame.lines.append('Decode gaps:')
        _frame.lines.append(f"  - status: {_frame.decode_gap_summary.get('status') or 'unknown'}, gaps={_frame.decode_gap_summary.get('gap_count') or '0'}, unresolved bytes={_frame.decode_gap_summary.get('total_unresolved_byte_count') or '0'}")
        for _frame.gap in _frame.decode_gap_summary.findall('./gaps/gap')[:8]:
            _frame.lines.append(f"  - #{_frame.gap.get('priority_rank') or '?'} {_frame.gap.get('type_name') or 'unknown'}: {_frame.gap.get('friendly_status_label') or _frame.gap.get('status') or 'partial'}; next={_frame.gap.get('suggested_next_decoder_step') or 'recover metadata'}")
        _frame.lines.append('')
    if _frame.compatibility is not None:
        _frame.gate_lines = [f"{gate.get('name')}: {gate.get('value')}" for gate in _frame.compatibility.findall('./gates/gate')]
        if _frame.gate_lines:
            _frame.lines.append('Compatibility gates:')
            _frame.lines.extend((f'  - {line}' for line in _frame.gate_lines[:10]))
            _frame.lines.append('')
    if _frame.user_guide is not None:
        _frame.lines.append('Editing guide:')
        _frame.summary_text = str(_frame.user_guide.findtext('summary', default='')).strip()
        if _frame.summary_text:
            _frame.lines.append(f'  - {_frame.summary_text}')
        _frame.safe_edits = [str(element.text or '').strip() for element in _frame.user_guide.findall('./safeFirstEdits/edit') if str(element.text or '').strip()]
        if _frame.safe_edits:
            _frame.lines.append('  - documented lower-risk edit classes:')
            _frame.lines.extend((f'    * {value}' for value in _frame.safe_edits[:5]))
        _frame.avoid_edits = [str(element.text or '').strip() for element in _frame.user_guide.findall('./avoidUntilDecoded/avoid') if str(element.text or '').strip()]
        if _frame.avoid_edits:
            _frame.lines.append('  - avoid until decoded:')
            _frame.lines.extend((f'    * {value}' for value in _frame.avoid_edits[:5]))
        _frame.lines.append('')
    if _frame.physics is not None:
        _frame.lines.append('Physics system:')
        for _frame.type_element in _frame.physics.findall('./typeCounts/type'):
            _frame.lines.append(f"  - {_frame.type_element.get('name')}: {_frame.type_element.get('count')}")
        _frame.lines.append('')
    if _frame.tuning_groups:
        _frame.category_counts: _state.Counter[str] = _state.Counter((group.get('category') or 'unknown' for group in _frame.tuning_groups))
        _frame.lines.append('Structured editable tuning groups:')
        for _frame.category, _frame.count in sorted(_frame.category_counts.items()):
            _frame.lines.append(f'  - {_frame.category}: {_frame.count}')
        _frame.lines.append('')
    if _frame.object_elements:
        _frame.layout_field_count = sum((len(object_element.findall('./layout/field')) for object_element in _frame.object_elements))
        _frame.reference_count = sum((len(object_element.findall('./references/reference')) for object_element in _frame.object_elements))
        _frame.raw_range_count = sum((len(object_element.findall('./rawRanges/range')) for object_element in _frame.object_elements))
        _frame.lines.append('Object layout view:')
        _frame.lines.append(f'  - objects: {len(_frame.object_elements)}')
        _frame.lines.append(f'  - layout fields: {_frame.layout_field_count}')
        _frame.lines.append(f'  - reference candidates: {_frame.reference_count}')
        _frame.lines.append(f'  - raw preserved ranges: {_frame.raw_range_count}')
        _frame.lines.append('')
    _frame.relationship_graph = _frame.root.find('./relationshipGraph')

def _populate_overview_part_003(_state, _frame):
    if _frame.relationship_graph is not None:
        _frame.lines.append('Relationship graph:')
        _frame.lines.append(f"  - nodes: {_frame.relationship_graph.get('node_count') or '0'}")
        _frame.lines.append(f"  - edges: {_frame.relationship_graph.get('edge_count') or '0'}")
        _frame.lines.append(f"  - record reference edges: {_frame.relationship_graph.get('reference_edge_count') or '0'}")
        _frame.lines.append('')
    if _frame.parity_report is not None or _frame.tagfile_fixups is not None or _frame.fixup_semantics is not None:
        _frame.lines.append('HKX XML parity and PTCH proof:')
        if _frame.parity_report is not None:
            _frame.root_object = _frame.parity_report.find('./rootObject')
            if _frame.root_object is not None:
                _frame.lines.append(f"  - root: {_frame.root_object.get('class') or 'unknown'} {_frame.root_object.get('toplevelobject') or ''} ({_frame.root_object.get('method') or 'unknown'}, {_frame.root_object.get('confidence') or 'unknown'})")
            _frame.lines.append(f"  - emitted params: {_frame.parity_report.get('havok_like_params_emitted') or '0'} ({_frame.parity_report.get('havok_named_params_emitted') or '0'} named)")
            _frame.lines.append(f"  - references: {_frame.parity_report.get('references_resolved') or '0'} resolved, {_frame.parity_report.get('references_unresolved') or '0'} unresolved")
            _frame.lines.append(f"  - PTCH-backed refs: {_frame.parity_report.get('ptch_fixup_backed_references') or '0'} (object={_frame.parity_report.get('object_references_resolved_by_ptch') or '0'}, inferred={_frame.parity_report.get('object_references_resolved_by_inference') or '0'})")
        if _frame.tagfile_fixups is not None:
            _frame.lines.append(f"  - patch sites: {_frame.tagfile_fixups.get('ptch_patch_site_count') or '0'} found, {_frame.tagfile_fixups.get('ptch_resolved_patch_site_count') or '0'} resolved, {_frame.tagfile_fixups.get('ptch_null_patch_site_count') or '0'} null, {_frame.tagfile_fixups.get('ptch_unresolved_patch_site_count') or '0'} unresolved")
        if _frame.fixup_semantics is not None:
            _frame.lines.append(f"  - fixup semantics status: {_frame.fixup_semantics.get('status') or 'unknown'}")
            _frame.remaining_cases = [f"{case.get('case')}: {case.get('count')}" for case in _frame.fixup_semantics.findall('./remainingCases/remainingCase')]
            if _frame.remaining_cases:
                _frame.lines.append('  - remaining PTCH cases: ' + '; '.join(_frame.remaining_cases[:6]))
        _frame.lines.append('')
    if _frame.hkclass_readiness is not None:
        _frame.lines.append('Decoder readiness:')
        _frame.lines.append(f"  - hkClass metadata: {_frame.hkclass_readiness.get('status') or 'unknown'}")
        _frame.lines.append(f"  - real hkClass metadata recovered: {_frame.hkclass_readiness.get('real_hkclass_metadata_recovered') or 'false'}")
        _frame.native_graph = _frame.hkclass_readiness.find('./nativeModelGraph')
        if _frame.native_graph is not None:
            _frame.lines.append(f"  - native graph: {_frame.native_graph.get('status') or 'unknown'}, nodes={_frame.native_graph.get('native_model_graph_node_count') or '0'}, fixup refs={_frame.native_graph.get('native_model_graph_fixup_backed_reference_edge_count') or '0'}")
        _frame.no_edit_writer = _frame.hkclass_readiness.find('./noEditBinaryWriter')
        if _frame.no_edit_writer is not None:
            _frame.lines.append(f"  - no-edit binary writer: {_frame.no_edit_writer.get('status') or 'unknown'}, byte-identical={_frame.no_edit_writer.get('byte_identical_no_edit_rebuild_supported') or 'false'}")
        _frame.hard_targets = _frame.hkclass_readiness.find('./hardDecoderTargets')
        if _frame.hard_targets is not None:
            _frame.lines.append(f"  - hard internals: {_frame.hard_targets.get('observed_target_count') or '0'} observed, {_frame.hard_targets.get('unresolved_target_count') or '0'} unresolved, {_frame.hard_targets.get('native_total_observed_byte_count') or '0'} byte(s)")
        _frame.missing_metadata = [requirement.get('key') or '' for requirement in _frame.hkclass_readiness.findall("./missingRealHkclassMetadata/requirement[@recovered='false']") if requirement.get('key')]
        if _frame.missing_metadata:
            _frame.lines.append('  - missing real metadata: ' + ', '.join(_frame.missing_metadata[:8]))
        _frame.lines.append('  - representative corpus needed: object_hkx, cloak_meshphysics_hkx, character_havokphysics_hkx, ragdoll_body_hkx, mesh_heavy_hkx, animation_hkx')
        _frame.lines.append('  - run Scan HKX Corpus... on real extracted HKX folders to prove the remaining cases.')
        _frame.lines.append('')
    if _frame.shape_elements:
        _frame.editable_shape_fields = 0
        for _frame.shape_element in _frame.shape_elements:
            _frame.editable_fields = str(_frame.shape_element.get('editable_fields') or '').split()
            _frame.editable_shape_fields += len(_frame.editable_fields)
        _frame.lines.append('Collision editor:')
        _frame.lines.append(f'  - shapes: {len(_frame.shape_elements)}')
        _frame.lines.append(f'  - editable shape field groups: {_frame.editable_shape_fields}')
        _frame.lines.append('')
    if _frame.descriptor_elements:
        _frame.body_count = sum((_frame._safe_int_text(descriptor.get('body_desc_count')) for descriptor in _frame.descriptor_elements))
        _frame.constraint_count = sum((_frame._safe_int_text(descriptor.get('constraint_desc_count')) for descriptor in _frame.descriptor_elements))
        _frame.shape_desc_count = sum((_frame._safe_int_text(descriptor.get('shape_desc_count')) for descriptor in _frame.descriptor_elements))
        _frame.lines.append('Companion descriptor context:')
        _frame.lines.append(f'  - descriptor XMLs: {len(_frame.descriptor_elements)}')
        _frame.lines.append(f'  - body descriptors: {_frame.body_count}')
        _frame.lines.append(f'  - constraint descriptors: {_frame.constraint_count}')
        _frame.lines.append(f'  - shape descriptors: {_frame.shape_desc_count}')
        _frame.lines.append('')
    if _frame.body_context is not None:
        _frame.lines.append('Correlated physics context:')
        _frame.lines.append(f"  - status: {_frame.body_context.get('status') or 'unknown'}")
        _frame.lines.append(f"  - body contexts: {_frame.body_context.get('body_count') or '0'}")
        _frame.lines.append(f"  - constraint hints: {_frame.body_context.get('constraint_hint_count') or '0'}")
        _frame.lines.append(f"  - confidence: {_frame.body_context.get('confidence') or 'experimental'}")
        _frame.lines.append('')
    if _frame.constraint_summary is not None:
        _frame.lines.append('Constraint summary:')
        _frame.lines.append(f"  - constraints: {_frame.constraint_summary.get('constraint_count') or '0'}")
        _frame.lines.append(f"  - confidence: {_frame.constraint_summary.get('confidence') or 'experimental'}")
        _frame.lines.append('')
    if _frame.editable_catalog is not None:
        _frame.lines.append('Editable catalog:')
        _frame.lines.append(f"  - import-safe routed values: {_frame.editable_catalog.get('field_count') or '0'}")
        for _frame.category in _frame.editable_catalog.findall('./categoryCounts/category'):
            _frame.lines.append(f"  - {_frame.category.get('name')}: {_frame.category.get('count')}")
        _frame.effects = [f"{effect.get('name')}: {effect.get('count')}" for effect in _frame.editable_catalog.findall('./effectCounts/effect')]
        if _frame.effects:
            _frame.lines.append('  - likely effects: ' + '; '.join(_frame.effects[:8]))
        _frame.lines.append('')
    if _frame.byte_patch_map is not None:
        _frame.lines.append('Byte patch map:')
        _frame.lines.append(f"  - fixed-size patch targets: {_frame.byte_patch_map.get('entry_count') or '0'}")
        _frame.lines.append(f"  - status: {_frame.byte_patch_map.get('status') or 'unknown'}")
        _frame.lines.append('')

def _populate_overview_part_004(_state, _frame):
    if _frame.policy is not None:
        _frame.lines.append('Reimport policy:')
        _frame.lines.append(f"  - status: {_frame.policy.get('status') or 'unknown'}")
        _frame.lines.append(f"  - write target: {_frame.policy.get('write_target') or 'unknown'}")
        _frame.rejected = _frame.policy.findall('./rejected_changes/rejectedChange')
        if _frame.rejected:
            _frame.lines.append(f'  - rejected structural changes: {len(_frame.rejected)}')
        _frame.allowed = _frame.policy.findall('./allowed_edits/allowedEdit')
        if _frame.allowed:
            _frame.lines.append(f'  - allowed fixed-size edit classes: {len(_frame.allowed)}')
        _frame.lines.append('')
    _frame.lines.append('Write behavior: edited output is written as a mod-ready loose HKX package; installed game archives are not modified.')
    _state.overview_text.setPlainText('\n'.join(_frame.lines))

def _dialog_step_0078(_state):
    def _populate_overview(root: ET.Element) -> None:
        _frame = SimpleNamespace(root=root)
        _populate_overview_part_001(_state, _frame)
        def _safe_int_text(value: object) -> int:
            try:
                return int(str(value or '0'), 0)
            except ValueError:
                return 0
        _frame._safe_int_text = _safe_int_text
        _populate_overview_part_002(_state, _frame)
        _populate_overview_part_003(_state, _frame)
        _populate_overview_part_004(_state, _frame)
    _state._populate_overview = _populate_overview

def _populate_hkx_browser_tree_part_005(_state, _frame):
    _state.hkx_browser_tree.clear()
    _frame.compatibility = _frame.root.find('./cdmwHkxCompatibility')
    _frame.converter_report = _frame.root.find('./converterReport')
    _frame.decode_gap_summary = _frame.root.find('./decodeGapSummary')
    _frame.editor_model = _frame.root.find('./editorModel')
    _frame.relationship_graph = _frame.root.find('./relationshipGraph')
    _frame.row_count = 0
    _frame.summary_parts: List[str] = []
    if _frame.converter_report is not None:
        _frame.editable_count = _frame.converter_report.get('editable_record_count') or '0'
        _frame.item_count = _frame.converter_report.get('item_record_count') or '0'
        _frame.compatibility_status = _frame.converter_report.get('cdmw_hkx_compatibility_status') or _frame.converter_report.get('status') or 'unknown'
        _frame.partial_count = '0'
        for _frame.status_element in _frame.converter_report.findall('./recordStatusCounts/status'):
            if _frame.status_element.get('name') == 'partially_decoded':
                _frame.partial_count = _frame.status_element.get('count') or '0'
                break
        _frame.summary_parts.append(f'{_frame.compatibility_status} | items {_frame.item_count} | patchable {_frame.editable_count} | partial {_frame.partial_count}')
    elif _frame.compatibility is not None:
        _frame.summary_parts.append(str(_frame.compatibility.get('status') or 'unknown'))
    if _frame.decode_gap_summary is not None:
        _frame.summary_parts.append(f"gaps {_frame.decode_gap_summary.get('gap_count') or '0'}")
    else:
        _frame.summary_parts.append('overview has decoder status')
    _state.browser_summary_label.setText(' | '.join((part for part in _frame.summary_parts if part)))
    if _frame.editor_model is not None:
        _frame.model_item = _state.QTreeWidgetItem(('Guided Editor Model', 'editor_model', f"{_frame.editor_model.get('row_count') or '0'} rows", _frame.editor_model.get('status') or ''))
        _frame.model_item.setData(0, _state.BROWSER_DATA_ROLE, {'label': 'Guided Editor Model', 'kind': 'editor_model', 'value': f"{_frame.editor_model.get('row_count') or '0'} rows", 'explanation': _frame.editor_model.findtext('description', default='')})
        _state.hkx_browser_tree.addTopLevelItem(_frame.model_item)
        for _frame.group_element in _frame.editor_model.findall('./groups/group'):
            _frame.title = _frame.group_element.get('title') or _frame.group_element.get('key') or 'Group'
            _frame.group_item = _state.QTreeWidgetItem((_frame.title, _frame.group_element.get('key') or 'group', f"{_frame.group_element.get('row_count') or '0'} rows", ''))
            _frame.group_item.setData(0, _state.BROWSER_DATA_ROLE, {'label': _frame.title, 'kind': _frame.group_element.get('key') or 'group', 'value': f"{_frame.group_element.get('row_count') or '0'} rows", 'explanation': 'Grouped HKX browser/editor rows. Child rows are ignored on import; patching uses the underlying XML fields.'})
            _frame.model_item.addChild(_frame.group_item)
            for _frame.row_element in _frame.group_element.findall('./rows/row'):
                _frame.row_data = dict(_frame.row_element.attrib)
                _frame.row_data['kind'] = _frame.group_element.get('key') or _frame.row_element.get('category') or ''
                for _frame.child_name, _frame.data_key in (('explanation', 'explanation'), ('ifIncreased', 'if_increased'), ('ifDecreased', 'if_decreased'), ('safeEditHint', 'safe_edit_hint'), ('valueConstraints', 'value_constraints')):
                    _frame.text_value = _frame.row_element.findtext(_frame.child_name, default='')
                    if _frame.text_value:
                        _frame.row_data[_frame.data_key] = _frame.text_value
                _frame.row_name = _frame.row_element.get('display_label') or _frame.row_element.get('label') or _frame.row_element.get('id') or 'row'
                _frame.row_kind = _frame.row_element.get('context_label') or _frame.row_element.get('field') or _frame.row_element.get('category') or ''
                _frame.duplicate_record_match = _state.re.fullmatch('\\s*(record\\s+\\d+)\\s*:\\s*(.+?)\\s*', str(_frame.row_name or ''), flags=_state.re.IGNORECASE)
                if _frame.duplicate_record_match and (not str(_frame.row_kind or '').strip() or str(_frame.row_kind or '').strip() == str(_frame.row_name or '').strip()):
                    _frame.row_name = _frame.duplicate_record_match.group(1)
                    _frame.row_kind = _frame.duplicate_record_match.group(2)
                elif str(_frame.row_name or '').strip() == str(_frame.row_kind or '').strip() and str(_frame.row_element.get('subject') or '').strip():
                    _frame.row_kind = str(_frame.row_element.get('subject') or '').strip()
                _frame.row_item = _state.QTreeWidgetItem((_frame.row_name, _frame.row_kind, _frame.row_element.get('value') or '', _frame.row_element.get('confidence') or ''))
                _frame.row_item.setData(0, _state.BROWSER_DATA_ROLE, _frame.row_data)
                _frame.row_importable = _frame.row_element.get('importable') == 'true'
                _frame.row_viewer_id = _frame.row_element.get('viewer_selection_id') or ''
                _state._style_hkx_browser_item(_frame.row_item, confidence=_frame.row_element.get('confidence') or '', importable=_frame.row_importable, viewer_id=_frame.row_viewer_id, read_only=not _frame.row_importable)
                if _frame.row_element.get('edit_risk') in {'high', 'experimental'}:
                    _frame.row_item.setToolTip(0, _frame.row_element.get('edit_risk') or '')
                _frame.group_item.addChild(_frame.row_item)
                _frame.row_count += 1
            _frame.group_item.setExpanded(_frame.group_item.childCount() <= 80)
        _frame.model_item.setExpanded(True)
    if _frame.relationship_graph is not None:
        _frame.graph_item = _state.QTreeWidgetItem(('Relationship Graph', 'graph', f"{_frame.relationship_graph.get('node_count') or '0'} nodes / {_frame.relationship_graph.get('edge_count') or '0'} edges", _frame.relationship_graph.get('status') or ''))
        _frame.graph_item.setData(0, _state.BROWSER_DATA_ROLE, {'label': 'Relationship Graph', 'kind': 'relationship_graph', 'value': _frame.graph_item.text(2), 'explanation': _frame.relationship_graph.findtext('description', default='')})
        _state.hkx_browser_tree.addTopLevelItem(_frame.graph_item)
        for _frame.node_element in _frame.relationship_graph.findall('./nodes/node')[:600]:
            _frame.node_data = dict(_frame.node_element.attrib)
            _frame.node_item = _state.QTreeWidgetItem((_frame.node_element.get('label') or _frame.node_element.get('id') or 'node', _frame.node_element.get('kind') or 'node', _frame.node_element.get('type_name') or _frame.node_element.get('subject') or '', _frame.node_element.get('confidence') or ''))
            _frame.node_item.setData(0, _state.BROWSER_DATA_ROLE, _frame.node_data)
            _state._style_hkx_browser_item(_frame.node_item, confidence=_frame.node_element.get('confidence') or '', viewer_id=_frame.node_element.get('viewer_selection_id') or _frame.node_element.get('id') or '')
            _frame.graph_item.addChild(_frame.node_item)
        _frame.graph_item.setExpanded(False)
    if _state.hkx_browser_tree.topLevelItemCount() == 0:
        _state.hkx_browser_tree.addTopLevelItem(_state.QTreeWidgetItem(('No HKX browser metadata was exported.', '', '', '')))
    _state._style_hkx_tree_values(_state.hkx_browser_tree, value_columns=(2,), confidence_column=3, guidance_columns=(0,))
    for _frame.column in range(_state.hkx_browser_tree.columnCount()):
        _state.hkx_browser_tree.resizeColumnToContents(_frame.column)
    _state._apply_hkx_browser_filter()

def _dialog_step_0079(_state):
    def _populate_hkx_browser_tree(root: ET.Element) -> None:
        _frame = SimpleNamespace(root=root)
        _populate_hkx_browser_tree_part_005(_state, _frame)
    _state._populate_hkx_browser_tree = _populate_hkx_browser_tree

def _dialog_step_0080(_state):
    def _current_browser_data() -> Mapping[str, object]:
        item = _state.hkx_browser_tree.currentItem()
        data = item.data(0, _state.BROWSER_DATA_ROLE) if item is not None else None
        return data if isinstance(data, _state.Mapping) else {}
    _state._current_browser_data = _current_browser_data

def _dialog_step_0081(_state):
    def _iter_hkx_browser_items() -> List[QTreeWidgetItem]:
        items: List[QTreeWidgetItem] = []

        def _collect(item: QTreeWidgetItem) -> None:
            items.append(item)
            for child_index in range(item.childCount()):
                _collect(item.child(child_index))

        for top_index in range(_state.hkx_browser_tree.topLevelItemCount()):
            _collect(_state.hkx_browser_tree.topLevelItem(top_index))
        return items
    _state._iter_hkx_browser_items = _iter_hkx_browser_items

STEPS = (_dialog_step_0066, _dialog_step_0067, _dialog_step_0068, _dialog_step_0069, _dialog_step_0070, _dialog_step_0071, _dialog_step_0072, _dialog_step_0073, _dialog_step_0074, _dialog_step_0075, _dialog_step_0076, _dialog_step_0077, _dialog_step_0078, _dialog_step_0079, _dialog_step_0080, _dialog_step_0081,)
