from __future__ import annotations

from types import SimpleNamespace

def _dialog_step_0094(_state):
    def _connected_current_data() -> Mapping[str, object]:
        item = _state.connected_tree.currentItem()
        data = item.data(0, _state.BROWSER_DATA_ROLE) if item is not None else None
        return data if isinstance(data, _state.Mapping) else {}
    _state._connected_current_data = _connected_current_data

def _dialog_step_0095(_state):
    def _connected_add_row(
        parent: QTreeWidgetItem,
        columns: Sequence[str],
        data: Mapping[str, object],
        *,
        patchable: bool = False,
    ) -> None:
        item = _state.QTreeWidgetItem(tuple(str(value or "") for value in columns))
        row_data = dict(data)
        risk_bucket = _state._connected_risk_bucket(row_data, item.text(4), item.text(5))
        row_data.setdefault("risk_bucket", risk_bucket)
        row_data.setdefault("value", item.text(3))
        row_data.setdefault("details", item.text(7))
        item.setData(0, _state.BROWSER_DATA_ROLE, row_data)
        if patchable:
            item.setForeground(3, _state.QBrush(_state.QColor("#9fd0ff")))
            item.setToolTip(3, "Patchable fixed-size value. Open Linked Value to edit it in the owning editor.")
            item.setBackground(3, _state.QBrush(_state.QColor("#17324d")))
        elif risk_bucket == "experimental":
            item.setForeground(0, _state.QBrush(_state.QColor("#cbd5e1")))
            item.setForeground(3, _state.QBrush(_state.QColor("#9aa7b4")))
        if risk_bucket == "safe":
            item.setForeground(5, _state.QBrush(_state.QColor("#86efac")))
        elif risk_bucket == "inferred":
            item.setForeground(5, _state.QBrush(_state.QColor("#fde68a")))
        elif risk_bucket == "experimental":
            item.setForeground(5, _state.QBrush(_state.QColor("#fca5a5")))
        item.setToolTip(2, f"Linked by: {_state.self._ui_evidence_label(row_data.get('link_evidence') or item.text(2))}")
        _state.self._ui_style_status_columns(item, {4: item.text(4), 5: risk_bucket})
        parent.addChild(item)
    _state._connected_add_row = _connected_add_row

def _dialog_step_0096(_state):
    def _connected_target_candidate_summary_lines(target_text: object) -> List[str]:
        target = str(target_text or "").strip()
        if not target:
            return []
        matches: List[_state.Mapping[str, object]] = []
        labels: List[str] = []
        for item in _state._iter_tree_items(_state.connected_tree):
            data = item.data(0, _state.BROWSER_DATA_ROLE)
            if not isinstance(data, _state.Mapping) or str(data.get("kind") or "") == "connected_group":
                continue
            row_text = " ".join(item.text(column) for column in range(_state.connected_tree.columnCount()))
            row_text += " " + " ".join(str(value) for value in data.values())
            if not _state._connected_row_text_matches_target(row_text, target):
                continue
            matches.append(data)
            label = str(
                data.get("field")
                or data.get("label")
                or data.get("connected_label")
                or item.text(2)
                or item.text(0)
                or ""
            ).strip()
            if label and label not in labels and str(data.get("kind") or "") != "connected_group":
                labels.append(label)
        if not matches:
            return []
        patchable_count = sum(1 for data in matches if str(data.get("importable") or "").strip().lower() == "true")
        exact_patchable_count = sum(
            1
            for data in matches
            if str(data.get("importable") or "").strip().lower() == "true"
            and str(data.get("link_evidence") or data.get("reference_source") or "").strip().casefold()
            in {"fixup_backed", "ptch", "exact", "owner_array", "declared_owner_array"}
        )
        read_only_context_count = sum(
            1
            for data in matches
            if str(data.get("importable") or "").strip().lower() != "true"
        )
        preview_count = sum(1 for data in matches if str(data.get("viewer_selection_id") or "").strip())
        editor_tabs = sorted(
            {
                str(data.get("editor_tab") or "").strip()
                for data in matches
                if str(data.get("editor_tab") or "").strip()
            }
        )
        lines = [
            f"Exact linked patchable values: {exact_patchable_count:,}.",
            f"Linked read-only context: {read_only_context_count:,}.",
            f"Nearby candidates: {max(0, len(matches) - exact_patchable_count - read_only_context_count):,}.",
            f"Selection links: {patchable_count:,} patchable value(s), {len(matches):,} related row(s), {preview_count:,} preview-linked row(s).",
        ]
        if editor_tabs:
            lines.append(f"Linked views: {', '.join(editor_tabs[:4])}.")
        chain_bits = []
        for chain_key, fallback_key in (
            ("body", "body_name"),
            ("shape", "shape_index"),
            ("material", "physics_material_name"),
            ("constraint/motor", "constraint_tag"),
        ):
            value = next((str(data.get(fallback_key) or "").strip() for data in matches if str(data.get(fallback_key) or "").strip()), "")
            if value:
                chain_bits.append(f"{chain_key} {value}")
        if chain_bits:
            lines.append("Relationship chain: " + " -> ".join(chain_bits) + " -> patchable values.")
        if labels:
            sample = ", ".join(labels[:7])
            if len(labels) > 7:
                sample += f", +{len(labels) - 7} more"
            lines.append(f"Likely useful fields: {sample}.")
        if patchable_count:
            lines.append("Use Open Linked Value on a blue/value row to edit through the safe CDMW patch path.")
        else:
            lines.append("No safe editable value is proven for this exact target yet; shown rows are browsing/context evidence.")
        return lines
    _state._connected_target_candidate_summary_lines = _connected_target_candidate_summary_lines

def _dialog_step_0097(_state):
    def _connected_detail_lines_from_mapping(data: Mapping[str, object]) -> List[str]:
        return _state._connected_detail_lines_from_mapping_helper(
            data,
            comparison_lines_fn=_state._comparison_lines_from_mapping,
            summary_lines_fn=_state._connected_target_candidate_summary_lines,
        )
    _state._connected_detail_lines_from_mapping = _connected_detail_lines_from_mapping

def _dialog_step_0098(_state):
    def _update_connected_detail_text(item: Optional[QTreeWidgetItem]) -> None:
        if item is None:
            _state.connected_detail_text.clear()
            return
        data = item.data(0, _state.BROWSER_DATA_ROLE)
        if isinstance(data, _state.Mapping):
            _state.connected_detail_text.setPlainText("\n".join(_state._connected_detail_lines_from_mapping(data)))
            return
        _state.connected_detail_text.setPlainText("Select a connected physics row to see exact linked values and offsets.")
    _state._update_connected_detail_text = _update_connected_detail_text

def _dialog_step_0099(_state):
    def _connected_item_score_for_target(item: QTreeWidgetItem, target_text: str) -> int:
        if item.isHidden():
            return -1
        data = item.data(0, _state.BROWSER_DATA_ROLE)
        if not isinstance(data, _state.Mapping) or str(data.get("kind") or "") == "connected_group":
            return -1
        target_key = str(target_text or "").replace(":", "/").casefold().strip()
        row_text = " ".join(item.text(column) for column in range(_state.connected_tree.columnCount())).casefold()
        row_text += " " + " ".join(str(value) for value in data.values()).casefold()
        if target_key and not _state._connected_row_text_matches_target(row_text, target_key):
            return -1
        score = 0
        viewer_id = str(data.get("viewer_selection_id") or "").replace(":", "/").casefold().strip()
        if target_key and viewer_id == target_key:
            score += 600
        if str(data.get("importable") or "").strip().lower() == "true":
            score += 320
        if str(data.get("editor_tab") or "").strip():
            score += 140
        if str(data.get("risk_bucket") or "").strip().lower() == "safe":
            score += 80
        if item.text(6).casefold().startswith("edit"):
            score += 60
        if str(data.get("record_index") or "").strip():
            score += 30
        return score
    _state._connected_item_score_for_target = _connected_item_score_for_target

def _dialog_step_0100(_state):
    def _select_best_connected_row_for_target(target_text: str) -> bool:
        scored: List[Tuple[int, QTreeWidgetItem]] = []
        for item in _state._iter_tree_items(_state.connected_tree):
            score = _state._connected_item_score_for_target(item, target_text)
            if score >= 0:
                scored.append((score, item))
        if not scored:
            return False
        scored.sort(key=lambda pair: pair[0], reverse=True)
        item = scored[0][1]
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        _state.connected_tree.setCurrentItem(item)
        _state.connected_tree.scrollToItem(item, _state.QAbstractItemView.PositionAtCenter)
        _state._update_connected_detail_text(item)
        return True
    _state._select_best_connected_row_for_target = _select_best_connected_row_for_target

def _dialog_step_0101(_state):
    def _update_decoder_evidence_detail(item: Optional[QTreeWidgetItem]) -> None:
        if item is None:
            _state.decoder_detail_text.clear()
            return
        data = item.data(0, _state.BROWSER_DATA_ROLE)
        data_map = data if isinstance(data, _state.Mapping) else {}
        lines = [
            item.text(0),
            f"Status: {item.text(1) or data_map.get('status') or 'context'}",
        ]
        for label, key in (
            ("Decoded fields", "decoded_field_count"),
            ("References", "reference_count"),
            ("Bytes", "byte_count"),
            ("Evidence", "link_evidence"),
            ("Source", "source"),
            ("Confidence", "confidence"),
        ):
            value = data_map.get(key)
            if isinstance(value, list):
                value = ", ".join(str(entry) for entry in value)
            if value not in (None, "", []):
                lines.append(f"{label}: {value}")
        missing = data_map.get("missing_requirements")
        if isinstance(missing, list) and missing:
            lines.append("")
            lines.append("Missing semantics:")
            lines.extend(f"- {value}" for value in missing if str(value).strip())
        elif item.text(5):
            lines.append(f"Missing/source: {item.text(5)}")
        _state.decoder_detail_text.setPlainText("\n".join(lines))
    _state._update_decoder_evidence_detail = _update_decoder_evidence_detail

def _populate_decoder_evidence_tree_part_006(_state, _frame):
    _frame.root = _state._load_xml_root_from_editor()

def _populate_decoder_evidence_tree_part_007(_state, _frame):
    _state.decoder_tree.clear()
    _frame.evidence = _frame.root.find('./decoderEvidence')
    _frame.fixup_v2 = _frame.root.find('./fixupSemanticsV2')
    _frame.semantic_model = _frame.root.find('./semanticModelV1')
    _frame.semantic_gate = _frame.root.find('./semanticWriterGateV1')
    _frame.edit_map = _frame.root.find('./editCandidateMapV1')
    _frame.class_decoder_v2 = _frame.root.find('./classDecoderEvidenceV2')
    _frame.real_metadata_v2 = _frame.root.find('./realHkclassMetadataV2')

def _populate_decoder_evidence_tree_part_008(_state, _frame):
    _frame.status = (_frame.evidence.get('status') if _frame.evidence is not None else None) or 'native evidence'
    _frame.source = (_frame.evidence.get('source') if _frame.evidence is not None else None) or 'native_rust_cd_hkx'
    _frame.class_count = (_frame.class_decoder_v2.get('class_status_count') if _frame.class_decoder_v2 is not None else None) or (_frame.evidence.get('class_status_count') if _frame.evidence is not None else None) or '0'
    _frame.priority_count = (_frame.evidence.get('priority_class_count') if _frame.evidence is not None else None) or '0'
    _frame.unresolved_count = (_frame.evidence.get('unresolved_or_packed_case_count') if _frame.evidence is not None else None) or '0'
    _frame.semantic_objects = (_frame.semantic_model.get('object_count') if _frame.semantic_model is not None else None) or '0'
    _frame.edit_candidates = (_frame.edit_map.get('candidate_count') if _frame.edit_map is not None else None) or '0'
    _state.decoder_status_label.setText(f'{_frame.class_count} class evidence row(s), {_frame.priority_count} priority row(s), {_frame.unresolved_count} unresolved/packed fixup case(s), {_frame.semantic_objects} semantic object(s), {_frame.edit_candidates} fixed-size edit candidate(s). Source: {_frame.source}.')
    _frame.refs_group = _state.QTreeWidgetItem(('Reference Semantics', _frame.status, '', '', '', 'object/null/data/string/type/packed buckets'))
    _frame.refs_group.setData(0, _state.BROWSER_DATA_ROLE, {'kind': 'decoder_group', 'source': _frame.source})
    _state.decoder_tree.addTopLevelItem(_frame.refs_group)
    for _frame.semantic in _frame.evidence.findall('./referenceSemantics/semantic') if _frame.evidence is not None else []:
        _frame.data = {'kind': 'decoder_reference_semantic', 'status': _frame.semantic.get('name') or '', 'source': 'decoderEvidence/referenceSemantics'}
        _frame.child = _state.QTreeWidgetItem((_frame.semantic.get('name') or '', 'semantic', '', '', _frame.semantic.get('count') or '', _frame.data['source']))
        _frame.child.setText(0, _state.self._ui_evidence_label(_frame.semantic.get('name') or 'semantic'))
        _frame.child.setData(0, _state.BROWSER_DATA_ROLE, _frame.data)
        _frame.refs_group.addChild(_frame.child)
    _frame.links_group = _state.QTreeWidgetItem(('Link Evidence', _frame.status, '', '', '', 'fixup-backed, owner-array, typed, inferred, raw'))
    _frame.links_group.setData(0, _state.BROWSER_DATA_ROLE, {'kind': 'decoder_group', 'source': _frame.source})
    _state.decoder_tree.addTopLevelItem(_frame.links_group)
    for _frame.link in _frame.evidence.findall('./linkEvidence/evidence') if _frame.evidence is not None else []:
        _frame.data = {'kind': 'decoder_link_evidence', 'status': _frame.link.get('name') or '', 'source': 'decoderEvidence/linkEvidence'}
        _frame.child = _state.QTreeWidgetItem((_frame.link.get('name') or '', 'evidence', '', '', _frame.link.get('count') or '', _frame.data['source']))
        _frame.child.setText(0, _state.self._ui_evidence_label(_frame.link.get('name') or 'evidence'))
        _frame.child.setData(0, _state.BROWSER_DATA_ROLE, _frame.data)
        _frame.links_group.addChild(_frame.child)
    _frame.classes_group = _state.QTreeWidgetItem(('Class Decode Status', _frame.status, '', '', '', 'read-only class gaps ranked by native evidence'))
    _frame.classes_group.setData(0, _state.BROWSER_DATA_ROLE, {'kind': 'decoder_group', 'source': _frame.source})
    _state.decoder_tree.addTopLevelItem(_frame.classes_group)
    _frame.class_rows = 0
    _frame.primary_class_elements = _frame.class_decoder_v2.findall('./classStatuses/class') if _frame.class_decoder_v2 is not None and _frame.class_decoder_v2.findall('./classStatuses/class') else _frame.evidence.findall('./classStatuses/class') if _frame.evidence is not None else []
    for _frame.class_element in _frame.primary_class_elements:
        _frame.missing = [requirement.text or '' for requirement in _frame.class_element.findall('./missingRequirements/requirement') if (requirement.text or '').strip()]
        _frame.link_evidence = [row.get('name') or '' for row in _frame.class_element.findall('./linkEvidence/evidence') if (row.get('name') or '').strip()]
        _frame.data = dict(_frame.class_element.attrib)
        _frame.data['kind'] = 'decoder_class_status'
        _frame.data['missing_requirements'] = _frame.missing
        _frame.data['link_evidence'] = _frame.link_evidence
        _frame.missing_text = '; '.join(_frame.missing[:3])
        if len(_frame.missing) > 3:
            _frame.missing_text += f'; +{len(_frame.missing) - 3} more'
        _frame.row_item = _state.QTreeWidgetItem((_frame.class_element.get('type_name') or _frame.class_element.get('name') or '', _frame.class_element.get('friendly_status') or _frame.class_element.get('status') or '', _frame.class_element.get('decoded_field_count') or '', _frame.class_element.get('reference_count') or '', _frame.class_element.get('byte_count') or '', _frame.missing_text))
        _frame.row_item.setData(0, _state.BROWSER_DATA_ROLE, _frame.data)
        _frame.status_text = (_frame.class_element.get('status') or '').casefold()
        if 'raw' in _frame.status_text:
            _frame.row_item.setForeground(1, _state.QBrush(_state.QColor('#fca5a5')))
        elif 'partial' in _frame.status_text:
            _frame.row_item.setForeground(1, _state.QBrush(_state.QColor('#fde68a')))
        else:
            _frame.row_item.setForeground(1, _state.QBrush(_state.QColor('#86efac')))
        if _frame.link_evidence:
            _frame.row_item.setToolTip(0, f"Link evidence: {', '.join((_state.self._ui_evidence_label(value) for value in _frame.link_evidence))}")
        _frame.classes_group.addChild(_frame.row_item)
        _frame.class_rows += 1
    _frame.fixup_group = _state.QTreeWidgetItem(('Fixup-backed Fields', _frame.status, '', '', '', 'fields linked by native PTCH/fixup evidence'))
    _frame.fixup_group.setData(0, _state.BROWSER_DATA_ROLE, {'kind': 'decoder_group', 'source': _frame.source})
    _state.decoder_tree.addTopLevelItem(_frame.fixup_group)
    for _frame.field in _frame.evidence.findall('./fixupBackedFields/field') if _frame.evidence is not None else []:
        _frame.data = dict(_frame.field.attrib)
        _frame.data['kind'] = 'decoder_fixup_field'
        _frame.data['source'] = 'decoderEvidence/fixupBackedFields'
        _frame.child = _state.QTreeWidgetItem((_frame.field.get('class_name') or '', _frame.field.get('field_name') or '', '', _frame.field.get('reference_category') or '', _frame.field.get('count') or '', _frame.field.get('confidence') or ''))
        _frame.child.setData(0, _state.BROWSER_DATA_ROLE, _frame.data)
        _frame.fixup_group.addChild(_frame.child)
    if _frame.fixup_v2 is not None:
        _frame.semantics_v2_group = _state.QTreeWidgetItem(('Fixup / PTCH Semantics V2', _frame.fixup_v2.get('status') or '', '', '', _frame.fixup_v2.get('patch_site_count') or '', 'object/null/data/string/type/packed patch-site buckets'))
        _frame.semantics_v2_group.setData(0, _state.BROWSER_DATA_ROLE, {'kind': 'decoder_group', 'source': 'fixupSemanticsV2'})
        _state.decoder_tree.addTopLevelItem(_frame.semantics_v2_group)
        for _frame.bucket in _frame.fixup_v2.findall('./semanticBuckets/bucket'):
            _frame.data = dict(_frame.bucket.attrib)
            _frame.data['kind'] = 'decoder_fixup_v2_bucket'
            _frame.data['source'] = 'fixupSemanticsV2/semanticBuckets'
            _frame.child = _state.QTreeWidgetItem((_frame.bucket.get('name') or '', 'semantic bucket', '', '', _frame.bucket.get('count') or '', _frame.data['source']))
            _frame.child.setText(0, _state.self._ui_evidence_label(_frame.bucket.get('name') or 'semantic'))
            _frame.child.setData(0, _state.BROWSER_DATA_ROLE, _frame.data)
            _frame.semantics_v2_group.addChild(_frame.child)
        for _frame.site in _frame.fixup_v2.findall('./patchSites/patchSite')[:256]:
            _frame.data = dict(_frame.site.attrib)
            _frame.data['kind'] = 'decoder_fixup_v2_patch_site'
            _frame.data['source'] = 'fixupSemanticsV2/patchSites'
            _frame.child = _state.QTreeWidgetItem((f"patch site {_frame.site.get('index') or ''}", _frame.site.get('semantic_bucket') or _frame.site.get('target_status') or '', _frame.site.get('owner_local_offset') or '', _frame.site.get('target_record_index') or '', _frame.site.get('patched_slot_value') or '', f"{_frame.site.get('section') or ''} {_frame.site.get('tuple_shape') or ''}".strip()))
            _frame.child.setData(0, _state.BROWSER_DATA_ROLE, _frame.data)
            _frame.semantics_v2_group.addChild(_frame.child)
        _frame.semantics_v2_group.setExpanded(_frame.semantics_v2_group.childCount() <= 80)

def _populate_decoder_evidence_tree_part_009(_state, _frame):
    if _frame.semantic_model is not None:
        _frame.semantic_model_group = _state.QTreeWidgetItem(('Semantic Model V1', _frame.semantic_model.get('status') or '', _frame.semantic_model.get('field_count') or '', '', _frame.semantic_model.get('object_count') or '', 'read-only object graph; write path remains gated'))
        _frame.semantic_model_group.setData(0, _state.BROWSER_DATA_ROLE, {'kind': 'decoder_group', 'source': 'semanticModelV1'})
        _state.decoder_tree.addTopLevelItem(_frame.semantic_model_group)
        for _frame.object_element in _frame.semantic_model.findall('./objects/object')[:256]:
            _frame.data = dict(_frame.object_element.attrib)
            _frame.data['kind'] = 'decoder_semantic_object'
            _frame.data['source'] = 'semanticModelV1/objects'
            _frame.child = _state.QTreeWidgetItem((_frame.object_element.get('type_name') or f"record {_frame.object_element.get('record_index') or ''}", _frame.object_element.get('class_metadata_source') or _frame.object_element.get('status') or '', _frame.object_element.get('field_count') or '', _frame.object_element.get('reference_count') or '', _frame.object_element.get('record_index') or '', _frame.object_element.get('status') or ''))
            _frame.child.setData(0, _state.BROWSER_DATA_ROLE, _frame.data)
            _frame.semantic_model_group.addChild(_frame.child)
        _frame.semantic_model_group.setExpanded(False)
    if _frame.edit_map is not None:
        _frame.edit_map_group = _state.QTreeWidgetItem(('Native Edit Candidate Map', _frame.edit_map.get('status') or '', '', '', _frame.edit_map.get('candidate_count') or '', 'only write-enabled rows are routed through CDMW fixed-size patches'))
        _frame.edit_map_group.setData(0, _state.BROWSER_DATA_ROLE, {'kind': 'decoder_group', 'source': 'editCandidateMapV1'})
        _state.decoder_tree.addTopLevelItem(_frame.edit_map_group)
        for _frame.candidate in _frame.edit_map.findall('./candidates/candidate')[:256]:
            _frame.data = dict(_frame.candidate.attrib)
            _frame.data['kind'] = 'decoder_edit_candidate'
            _frame.data['source'] = 'editCandidateMapV1/candidates'
            _frame.child = _state.QTreeWidgetItem((f"{_frame.candidate.get('class') or ''}.{_frame.candidate.get('member') or ''}".strip('.'), 'write-enabled' if _frame.candidate.get('write_enabled') == 'true' else 'candidate only', _frame.candidate.get('byte_size') or '', _frame.candidate.get('record_index') or '', _frame.candidate.get('local_offset') or _frame.candidate.get('offset_hex') or '', f"{_frame.candidate.get('supported_write_type') or ''} | {_frame.candidate.get('risk_label') or ''}".strip(' |')))
            _frame.child.setData(0, _state.BROWSER_DATA_ROLE, _frame.data)
            if _frame.candidate.get('write_enabled') == 'true':
                _frame.child.setForeground(1, _state.QBrush(_state.QColor('#86efac')))
            else:
                _frame.child.setForeground(1, _state.QBrush(_state.QColor('#9aa7b4')))
            _frame.edit_map_group.addChild(_frame.child)
        _frame.edit_map_group.setExpanded(_frame.edit_map_group.childCount() <= 80)
    if _frame.semantic_gate is not None:
        _frame.gate_group = _state.QTreeWidgetItem(('Semantic Writer Gate', _frame.semantic_gate.get('status') or '', '', '', _frame.semantic_gate.get('patchable_slot_count') or '', 'Havok XML import and semantic rebuild remain blocked until byte-identity coverage passes'))
        _frame.gate_group.setData(0, _state.BROWSER_DATA_ROLE, {'kind': 'decoder_group', 'source': 'semanticWriterGateV1'})
        _state.decoder_tree.addTopLevelItem(_frame.gate_group)
        for _frame.blocked in _frame.semantic_gate.findall('./blockedEditClasses/blocked'):
            _frame.data = {'kind': 'decoder_blocked_edit', 'source': 'semanticWriterGateV1/blockedEditClasses', 'status': 'blocked'}
            _frame.child = _state.QTreeWidgetItem((_frame.blocked.text or '', 'blocked', '', '', '', 'semantic writer gate'))
            _frame.child.setData(0, _state.BROWSER_DATA_ROLE, _frame.data)
            _frame.child.setForeground(1, _state.QBrush(_state.QColor('#fca5a5')))
            _frame.gate_group.addChild(_frame.child)
        _frame.gate_group.setExpanded(False)
    if _frame.real_metadata_v2 is not None:
        _frame.metadata_group = _state.QTreeWidgetItem(('Real hkClass Metadata V2', _frame.real_metadata_v2.get('status') or '', _frame.real_metadata_v2.get('member_count') or '', '', _frame.real_metadata_v2.get('class_count') or '', 'real metadata preferred; synthetic __types__ remains fallback'))
        _frame.metadata_group.setData(0, _state.BROWSER_DATA_ROLE, {'kind': 'decoder_group', 'source': 'realHkclassMetadataV2'})
        _state.decoder_tree.addTopLevelItem(_frame.metadata_group)
        for _frame.class_element in _frame.real_metadata_v2.findall('./classes/class')[:256]:
            _frame.data = dict(_frame.class_element.attrib)
            _frame.data['kind'] = 'decoder_real_hkclass'
            _frame.data['source'] = 'realHkclassMetadataV2/classes'
            _frame.child = _state.QTreeWidgetItem((_frame.class_element.get('name') or '', _frame.class_element.get('metadata_source') or _frame.class_element.get('confidence') or '', '', '', _frame.class_element.get('object_size') or '', _frame.class_element.get('base_class') or _frame.class_element.get('signature_hex') or ''))
            _frame.child.setData(0, _state.BROWSER_DATA_ROLE, _frame.data)
            _frame.metadata_group.addChild(_frame.child)
        _frame.metadata_group.setExpanded(False)
    _frame.refs_group.setExpanded(True)
    _frame.links_group.setExpanded(True)
    _frame.classes_group.setExpanded(_frame.class_rows <= 80)
    _frame.fixup_group.setExpanded(_frame.fixup_group.childCount() <= 80)
    _state._style_hkx_tree_values(_state.decoder_tree, value_columns=(2, 3, 4), confidence_column=5, guidance_columns=(0, 5))
    for _frame.column in range(_state.decoder_tree.columnCount()):
        _state.decoder_tree.resizeColumnToContents(_frame.column)
    _state._set_hkx_editor_section_title(10, f'Decoder Evidence ({_frame.class_rows})' if _frame.class_rows else 'Decoder Evidence')

def _dialog_step_0102(_state):
    def _populate_decoder_evidence_tree() -> None:
        _frame = SimpleNamespace()
        _populate_decoder_evidence_tree_part_006(_state, _frame)
        if _frame.root is None:
            return
        _populate_decoder_evidence_tree_part_007(_state, _frame)
        if _frame.evidence is None and _frame.fixup_v2 is None and (_frame.semantic_model is None) and (_frame.semantic_gate is None) and (_frame.edit_map is None) and (_frame.class_decoder_v2 is None) and (_frame.real_metadata_v2 is None):
            _state.decoder_tree.addTopLevelItem(_state.QTreeWidgetItem(('No decoder evidence exported.', '', '', '', '', '')))
            _state.decoder_status_label.setText('No normalized decoder evidence is present in this HKX export.')
            _state._set_hkx_editor_section_title(10, 'Decoder Evidence')
            return
        _populate_decoder_evidence_tree_part_008(_state, _frame)
        _populate_decoder_evidence_tree_part_009(_state, _frame)
    _state._populate_decoder_evidence_tree = _populate_decoder_evidence_tree

def _populate_connected_physics_tree_part_010(_state, _frame):
    _frame.root = _state._load_xml_root_from_editor()

def _populate_connected_physics_tree_part_011(_state, _frame):
    _state.connected_tree.clear()
    _frame.nodes_by_id = _state._connected_node_lookup(_frame.root)
    _frame.total_rows = 0
    _frame.exact_link_group = _state.QTreeWidgetItem(('Fixup-backed / Exact Links', '', '', '', '', '', '', 'PTCH/fixup-backed references or direct editor links: patch targets, decoded owners, and exact preview targets.'))
    _frame.exact_link_group.setData(0, _state.BROWSER_DATA_ROLE, {'kind': 'connected_group', 'label': 'Fixup-backed / Exact Links'})
    _state.connected_tree.addTopLevelItem(_frame.exact_link_group)
    _frame.owner_array_group = _state.QTreeWidgetItem(('Owner-array Links', '', '', '', '', '', '', 'Native owner-array context such as system bodies, materials, constraints, skeleton arrays, and shape storage.'))
    _frame.owner_array_group.setData(0, _state.BROWSER_DATA_ROLE, {'kind': 'connected_group', 'label': 'Owner-array Links'})
    _state.connected_tree.addTopLevelItem(_frame.owner_array_group)
    _frame.likely_link_group = _state.QTreeWidgetItem(('Likely Links', '', '', '', '', '', '', 'Inferred body/shape/constraint relationships. Useful context, but not proven ownership.'))
    _frame.likely_link_group.setData(0, _state.BROWSER_DATA_ROLE, {'kind': 'connected_group', 'label': 'Likely Links'})
    _state.connected_tree.addTopLevelItem(_frame.likely_link_group)
    _frame.raw_evidence_group = _state.QTreeWidgetItem(('Raw Decoder Evidence', '', '', '', '', '', '', 'Low-level relationship graph edges, raw refs, and decoder observations.'))
    _frame.raw_evidence_group.setData(0, _state.BROWSER_DATA_ROLE, {'kind': 'connected_group', 'label': 'Raw Decoder Evidence'})
    _state.connected_tree.addTopLevelItem(_frame.raw_evidence_group)
    _frame.exact_rows = 0
    _frame.owner_array_rows = 0
    _frame.likely_rows = 0
    _frame.raw_evidence_rows = 0
    for _frame.edge in _frame.root.findall('./relationshipGraph/edges/edge')[:1600]:
        _frame.source_id = _frame.edge.get('source') or ''
        _frame.target_id = _frame.edge.get('target') or ''
        _frame.source_node = _frame.nodes_by_id.get(_frame.source_id, {})
        _frame.target_node = _frame.nodes_by_id.get(_frame.target_id, {})
        _frame.viewer_id = str(_frame.edge.get('viewer_selection_id') or '') or str(_frame.source_node.get('viewer_selection_id') or '') or str(_frame.target_node.get('viewer_selection_id') or '') or (_frame.source_id if str(_frame.source_id).startswith(('shape/', 'constraint/', 'anchor/', 'bone/')) else '') or (_frame.target_id if str(_frame.target_id).startswith(('shape/', 'constraint/', 'anchor/', 'bone/')) else '')
        _frame.record_index = _frame.edge.get('record_index') or _frame.source_node.get('record_index') or _frame.target_node.get('record_index') or ''
        _frame.confidence = _frame.edge.get('confidence') or _frame.source_node.get('confidence') or _frame.target_node.get('confidence') or 'experimental'
        _frame.relation = _frame.edge.get('relation') or 'linked'
        _frame.editor_tab = _frame.edge.get('editor_tab') or _frame.target_node.get('editor_tab') or _frame.source_node.get('editor_tab') or ('Object Layout' if _frame.record_index else '')
        _frame.importable_value = _frame.edge.get('importable') or _frame.target_node.get('importable') or _frame.source_node.get('importable') or ''
        _frame.link_evidence = _frame.edge.get('link_evidence') or ('fixup_backed' if str(_frame.edge.get('fixup_backed') or '').strip().lower() == 'true' else 'exact' if _frame.relation in {'decoded_from', 'has_editable_value', 'writes_byte_offset', 'writes_bytes'} else 'inferred')
        _frame.data = {'kind': 'connected_relationship', 'label': _state._connected_node_label(_frame.nodes_by_id, _frame.source_id), 'connected_label': _state._connected_node_label(_frame.nodes_by_id, _frame.target_id), 'source_id': _frame.source_id, 'target_id': _frame.target_id, 'relation': _frame.relation, 'value': _frame.edge.get('value') or _frame.target_node.get('value') or _frame.source_node.get('value') or _frame.edge.get('target') or '', 'confidence': _frame.confidence, 'record_index': _frame.record_index, 'item_index': _frame.edge.get('item_index') or _frame.target_node.get('item_index') or _frame.source_node.get('item_index') or '', 'offset': _frame.edge.get('offset') or _frame.target_node.get('offset') or _frame.source_node.get('offset') or '', 'hex_offset': _frame.edge.get('hex_offset') or _frame.target_node.get('hex_offset') or _frame.source_node.get('hex_offset') or '', 'field': _frame.edge.get('field') or _frame.target_node.get('field') or _frame.source_node.get('field') or '', 'viewer_selection_id': _frame.viewer_id, 'editor_tab': _frame.editor_tab, 'importable': _frame.importable_value, 'link_evidence': _frame.link_evidence, 'display_evidence': _state.self._ui_evidence_label(_frame.link_evidence), 'effect': _frame.edge.get('effect') or _frame.target_node.get('effect') or _frame.source_node.get('effect') or '', 'edit_risk': _frame.edge.get('edit_risk') or _frame.target_node.get('edit_risk') or _frame.source_node.get('edit_risk') or '', 'explanation': _frame.edge.get('description') or 'Recovered relationship edge from the HKX relationship graph.'}
        for _frame.extra_key in ('identity_path', 'hex_absolute_data_offset', 'absolute_data_offset', 'byte_size', 'value_type', 'owner_field', 'reference_source', 'reference_category', 'category', 'subject', 'shape_index', 'shape_type'):
            _frame.value = _frame.edge.get(_frame.extra_key) or _frame.target_node.get(_frame.extra_key) or _frame.source_node.get(_frame.extra_key)
            if _frame.value not in (None, ''):
                _frame.data[_frame.extra_key] = _frame.value
        _frame.is_patchable = str(_frame.importable_value).strip().lower() == 'true' or _frame.relation in {'has_editable_value', 'writes_byte_offset'}
        if _frame.link_evidence == 'declared_owner_array':
            _frame.relationship_parent = _frame.owner_array_group
            _frame.owner_array_rows += 1
        elif _frame.link_evidence in {'exact', 'fixup_backed', 'typed_layout'} or _frame.is_patchable:
            _frame.relationship_parent = _frame.exact_link_group
            _frame.exact_rows += 1
        elif _frame.link_evidence == 'inferred' and _frame.relation not in {'contains', 'indexes'}:
            _frame.relationship_parent = _frame.likely_link_group
            _frame.likely_rows += 1
        else:
            _frame.relationship_parent = _frame.raw_evidence_group
            _frame.raw_evidence_rows += 1
        _state._connected_add_row(_frame.relationship_parent, (_frame.data['label'], _frame.data['connected_label'], f"{_frame.relation} ({_frame.data['display_evidence']})", _state._value_with_dirty_preview(_frame.data, _frame.data['value']), _frame.confidence, _state._connected_risk_bucket(_frame.data, str(_frame.confidence), ''), 'Edit value' if _frame.is_patchable else 'Inspect object', f"{_frame.source_id} -> {_frame.target_id}; viewer={_frame.viewer_id}; record={_frame.record_index}; item={_frame.data.get('item_index') or ''}; offset={_frame.data.get('hex_offset') or _frame.data.get('offset') or ''}; byte={_frame.data.get('hex_absolute_data_offset') or ''}"), _frame.data, patchable=_frame.is_patchable)
        _frame.total_rows += 1
    _frame.exact_link_group.setExpanded(True)
    _frame.owner_array_group.setExpanded(_frame.owner_array_rows <= 120)
    _frame.likely_link_group.setExpanded(_frame.likely_rows <= 80)
    _frame.raw_evidence_group.setExpanded(False)
    _frame.label_group = _state.QTreeWidgetItem(('Context Only', '', '', '', '', '', '', 'Recovered strings, body names, sockets, materials, and simulation-role hints.'))
    _frame.label_group.setData(0, _state.BROWSER_DATA_ROLE, {'kind': 'connected_group', 'label': 'Context Only'})
    _state.connected_tree.addTopLevelItem(_frame.label_group)
    _frame.label_rows = 0
    for _frame.body in _frame.root.findall('./physicsBodySummary/bodies/body'):
        _frame.shape_index = _frame.body.get('shape_index') or ''
        _frame.viewer_id = f'shape/{_frame.shape_index}' if _frame.shape_index else ''
        _frame.label_text = _frame.body.get('body_name') or _frame.body.get('socket_name') or _frame.body.get('fixed_socket_name') or f'shape {_frame.shape_index}'
        _frame.values = []
        for _frame.attr_name, _frame.label_name in (('simulation_role', 'role'), ('physics_material_name', 'material'), ('socket_name', 'socket'), ('fixed_socket_name', 'fixed')):
            _frame.value = _frame.body.get(_frame.attr_name)
            if _frame.value:
                _frame.values.append(f'{_frame.label_name}={_frame.value}')
        _frame.confidence = _frame.body.get('confidence') or 'experimental'
        _frame.data = {'kind': 'connected_name_evidence', 'label': _frame.label_text, 'connected_label': _frame.body.get('shape_type') or 'body/shape', 'relation': 'body label', 'value': '; '.join(_frame.values), 'confidence': _frame.confidence, 'viewer_selection_id': _frame.viewer_id, 'shape_index': _frame.shape_index, 'editor_tab': 'Collision Editor' if _frame.viewer_id else '', 'explanation': _frame.body.findtext('description', default='') or 'Recovered body/shape label. This is concrete naming evidence when present, but it is still read-only context.'}
        _state._connected_add_row(_frame.label_group, (_frame.data['label'], _frame.data['connected_label'], _frame.data['relation'], _frame.data['value'], _frame.confidence, _state._connected_risk_bucket(_frame.data, _frame.confidence, ''), 'Open shape' if _frame.viewer_id else 'Context', f'viewer={_frame.viewer_id}; shape={_frame.shape_index}; name source=physicsBodySummary'), _frame.data)
        _frame.label_rows += 1
        _frame.total_rows += 1
        for _frame.context in _frame.body.findall('./descriptorContexts/context'):
            _frame.context_label = _frame.context.get('body_name') or _frame.context.get('socket_name') or _frame.context.get('fixed_socket_name') or _frame.label_text
            _frame.context_value = '; '.join((part for part in (f"role={_frame.context.get('simulation_role')}" if _frame.context.get('simulation_role') else '', f"material={_frame.context.get('physics_material_name')}" if _frame.context.get('physics_material_name') else '', f"socket={_frame.context.get('socket_name') or _frame.context.get('fixed_socket_name')}" if _frame.context.get('socket_name') or _frame.context.get('fixed_socket_name') else '') if part))
            _frame.context_data = {'kind': 'connected_descriptor_label_evidence', 'label': _frame.context_label, 'connected_label': _frame.context.get('descriptor_path') or 'descriptor', 'relation': 'descriptor label', 'value': _frame.context_value, 'confidence': _frame.context.get('confidence') or 'descriptor_context', 'viewer_selection_id': _frame.viewer_id, 'shape_index': _frame.shape_index, 'editor_tab': 'Collision Editor' if _frame.viewer_id else '', 'explanation': 'Companion descriptor label/material context correlated with this HKX body or shape.'}
            _state._connected_add_row(_frame.label_group, (_frame.context_data['label'], _frame.context_data['connected_label'], _frame.context_data['relation'], _frame.context_data['value'], _frame.context_data['confidence'], _state._connected_risk_bucket(_frame.context_data, str(_frame.context_data['confidence']), ''), 'Open shape' if _frame.viewer_id else 'Context', f"viewer={_frame.viewer_id}; descriptor={_frame.context.get('descriptor_path') or ''}"), _frame.context_data)
            _frame.label_rows += 1
            _frame.total_rows += 1
    for _frame.shape_name in _frame.root.findall('./physicsNames/shapeNameProperties/shapeName'):
        _frame.value = '; '.join((part for part in (f"role={_frame.shape_name.get('simulation_role')}" if _frame.shape_name.get('simulation_role') else '', f"name_record={_frame.shape_name.get('name_record_index')}" if _frame.shape_name.get('name_record_index') else '', f"property_record={_frame.shape_name.get('property_record_index')}" if _frame.shape_name.get('property_record_index') else '') if part))
        _frame.data = {'kind': 'connected_hkx_shape_name', 'label': _frame.shape_name.get('name') or f"shape name {_frame.shape_name.get('index') or ''}", 'connected_label': 'HavokShapeNameProperty', 'relation': 'in-HKX string', 'value': _frame.value, 'confidence': _frame.shape_name.get('confidence') or 'experimental', 'record_index': _frame.shape_name.get('property_record_index') or '', 'editor_tab': 'Object Layout', 'explanation': _frame.shape_name.get('description') or 'Decoded in-HKX shape/body name string.'}
        _state._connected_add_row(_frame.label_group, (_frame.data['label'], _frame.data['connected_label'], _frame.data['relation'], _frame.data['value'], _frame.data['confidence'], _state._connected_risk_bucket(_frame.data, str(_frame.data['confidence']), ''), 'Inspect object', f"property_record={_frame.shape_name.get('property_record_index') or ''}; name_record={_frame.shape_name.get('name_record_index') or ''}"), _frame.data)
        _frame.label_rows += 1
        _frame.total_rows += 1
    for _frame.string_row in _frame.root.findall('./physicsNames/charStrings/string'):
        _frame.data = {'kind': 'connected_hkx_char_string', 'label': _frame.string_row.get('text') or f"char record {_frame.string_row.get('record_index') or ''}", 'connected_label': 'char/string record', 'relation': 'decoded string', 'value': _frame.string_row.get('simulation_role') or '', 'confidence': _frame.string_row.get('confidence') or 'confirmed', 'record_index': _frame.string_row.get('record_index') or '', 'editor_tab': 'Object Layout', 'explanation': _frame.string_row.get('description') or 'Decoded in-HKX string. Use this as naming evidence, not as an editable value.'}
        _state._connected_add_row(_frame.label_group, (_frame.data['label'], _frame.data['connected_label'], _frame.data['relation'], _frame.data['value'], _frame.data['confidence'], _state._connected_risk_bucket(_frame.data, str(_frame.data['confidence']), ''), 'Inspect string', f"record={_frame.string_row.get('record_index') or ''}; role={_frame.string_row.get('simulation_role') or ''}; {_frame.string_row.get('simulation_role_description') or ''}"), _frame.data)
        _frame.label_rows += 1
        _frame.total_rows += 1

def _populate_connected_physics_tree_part_012(_state, _frame):
    for _frame.hint_element in _frame.root.findall('./physicsMaterialContext/hints/hint'):
        _frame.name = _frame.hint_element.get('submesh_name') or _frame.hint_element.get('pbd_simulation_material') or _frame.hint_element.get('material_name') or f"material hint {_frame.hint_element.get('index') or ''}"
        _frame.value = '; '.join((part for part in (f"role={_frame.hint_element.get('simulation_role')}" if _frame.hint_element.get('simulation_role') else '', f"pbd={_frame.hint_element.get('pbd_simulation_material')}" if _frame.hint_element.get('pbd_simulation_material') else '', f"material={_frame.hint_element.get('material_name')}" if _frame.hint_element.get('material_name') else '') if part))
        _frame.data = {'kind': 'connected_material_label_evidence', 'label': _frame.name, 'connected_label': _frame.hint_element.get('descriptor_path') or 'material descriptor', 'relation': 'material/simulation label', 'value': _frame.value, 'confidence': _frame.hint_element.get('confidence') or 'descriptor_context', 'explanation': _frame.hint_element.get('simulation_role_description') or 'Descriptor-side material/simulation naming evidence.'}
        _state._connected_add_row(_frame.label_group, (_frame.data['label'], _frame.data['connected_label'], _frame.data['relation'], _frame.data['value'], _frame.data['confidence'], _state._connected_risk_bucket(_frame.data, str(_frame.data['confidence']), ''), 'Context', f"descriptor={_frame.hint_element.get('descriptor_path') or ''}; parameter={_frame.hint_element.get('parameter_name') or ''}"), _frame.data)
        _frame.label_rows += 1
        _frame.total_rows += 1
    _frame.label_group.setExpanded(_frame.label_rows <= 80)
    _frame.body_group = _state.QTreeWidgetItem(('Likely Links: Bodies / Shapes', '', '', '', '', '', '', 'Body summaries correlated to decoded shapes and descriptor context.'))
    _frame.body_group.setData(0, _state.BROWSER_DATA_ROLE, {'kind': 'connected_group', 'label': 'Likely Links: Bodies / Shapes'})
    _state.connected_tree.addTopLevelItem(_frame.body_group)
    _frame.body_rows = 0
    for _frame.body in _frame.root.findall('./physicsBodySummary/bodies/body'):
        _frame.shape_index = _frame.body.get('shape_index') or ''
        _frame.viewer_id = f'shape/{_frame.shape_index}' if _frame.shape_index else ''
        _frame.capsule = _frame.body.find('capsule')
        _frame.radius = _frame.capsule.get('radius') if _frame.capsule is not None else ''
        _frame.length = _frame.capsule.get('length') if _frame.capsule is not None else ''
        _frame.value = '; '.join((part for part in (f'radius={_frame.radius}' if _frame.radius else '', f'length={_frame.length}' if _frame.length else '') if part))
        _frame.confidence = _frame.body.get('confidence') or 'experimental'
        _frame.data = {'kind': 'connected_body_shape', 'label': _frame.body.get('body_name') or f'shape {_frame.shape_index}', 'connected_label': _frame.body.get('shape_type') or 'shape', 'relation': 'body -> shape', 'value': _frame.value, 'confidence': _frame.confidence, 'viewer_selection_id': _frame.viewer_id, 'shape_index': _frame.shape_index, 'editor_tab': 'Collision Editor' if _frame.shape_index else '', 'explanation': _frame.body.findtext('description', default='')}
        _state._connected_add_row(_frame.body_group, (_frame.data['label'], _frame.data['connected_label'], 'body -> shape', _frame.value, _frame.confidence, _state._connected_risk_bucket(_frame.data, _frame.confidence, ''), 'Open shape', f"viewer={_frame.viewer_id}; editable={_frame.body.get('editable_fields') or ''}; material={_frame.body.get('physics_material_name') or ''}; socket={_frame.body.get('socket_name') or ''}"), _frame.data)
        _frame.body_rows += 1
        _frame.total_rows += 1
        for _frame.context in _frame.body.findall('./descriptorContexts/context'):
            _frame.context_data = {'kind': 'connected_body_context', 'label': _frame.body.get('body_name') or f'shape {_frame.shape_index}', 'connected_label': _frame.context.get('body_name') or _frame.context.get('socket_name') or 'descriptor context', 'relation': 'descriptor context', 'value': _frame.context.get('physics_material_name') or '', 'confidence': _frame.context.get('confidence') or 'descriptor_context', 'viewer_selection_id': _frame.viewer_id, 'shape_index': _frame.shape_index, 'editor_tab': 'Collision Editor' if _frame.shape_index else '', 'explanation': 'Descriptor-side body/socket/material context; read-only.'}
            _state._connected_add_row(_frame.body_group, (_frame.context_data['label'], _frame.context_data['connected_label'], 'descriptor context', _frame.context_data['value'], _frame.context_data['confidence'], _state._connected_risk_bucket(_frame.context_data, str(_frame.context_data['confidence']), ''), 'Open shape', f"source={_frame.context.get('descriptor_path') or ''}; socket={_frame.context.get('socket_name') or _frame.context.get('fixed_socket_name') or ''}"), _frame.context_data)
            _frame.body_rows += 1
            _frame.total_rows += 1
    _frame.body_group.setExpanded(_frame.body_rows <= 80)
    _frame.constraint_group = _state.QTreeWidgetItem(('Likely Links: Constraints / Motors', '', '', '', '', '', '', 'Constraint and motor rows connected to editable tuning slots.'))
    _frame.constraint_group.setData(0, _state.BROWSER_DATA_ROLE, {'kind': 'connected_group', 'label': 'Likely Links: Constraints / Motors'})
    _state.connected_tree.addTopLevelItem(_frame.constraint_group)
    _frame.constraint_rows = 0
    for _frame.constraint in _frame.root.findall('./physicsConstraintSummary/constraints/constraint'):
        _frame.constraint_index = _frame.constraint.get('index') or ''
        _frame.viewer_id = f'constraint/{_frame.constraint_index}' if _frame.constraint_index else ''
        _frame.descriptor_context = _frame.constraint.find('descriptorContext')
        _frame.connected_to = ''
        if _frame.descriptor_context is not None:
            _frame.connected_to = ' -> '.join((part for part in (_frame.descriptor_context.get('body_name') or '', _frame.descriptor_context.get('socket_name') or _frame.descriptor_context.get('fixed_socket_name') or '') if part))
        _frame.data = {'kind': 'connected_constraint', 'label': _frame.constraint.get('name') or f'constraint {_frame.constraint_index}', 'connected_label': _frame.connected_to or _frame.constraint.get('type_name') or '', 'relation': 'constraint', 'value': _frame.constraint.get('type_name') or '', 'confidence': _frame.constraint.get('confidence') or 'experimental', 'viewer_selection_id': _frame.viewer_id, 'record_index': _frame.constraint.get('constraint_record_index') or '', 'editor_tab': 'Structured Editor', 'explanation': _frame.constraint.findtext('description', default='')}
        _state._connected_add_row(_frame.constraint_group, (_frame.data['label'], _frame.data['connected_label'], 'constraint', _frame.data['value'], _frame.data['confidence'], _state._connected_risk_bucket(_frame.data, str(_frame.data['confidence']), ''), 'Open values', f"viewer={_frame.viewer_id}; constraint_record={_frame.constraint.get('constraint_record_index') or ''}; motor_record={_frame.constraint.get('motor_record_index') or ''}"), _frame.data)
        _frame.constraint_rows += 1
        _frame.total_rows += 1
        for _frame.slot_parent_name, _frame.slot_kind in (('constraint_slots', 'constraint slot'), ('motor_slots', 'motor slot')):
            for _frame.slot in _frame.constraint.findall(f'./{_frame.slot_parent_name}/*'):
                _frame.record_index = _frame.constraint.get('motor_record_index') if _frame.slot_kind == 'motor slot' else _frame.constraint.get('constraint_record_index')
                _frame.risk = _frame.slot.get('edit_risk') or 'inferred'
                _frame.slot_data = {'kind': 'connected_constraint_value', 'label': _frame.constraint.get('name') or f'constraint {_frame.constraint_index}', 'connected_label': _frame.slot.get('name') or _frame.slot_kind, 'relation': _frame.slot_kind, 'value': _frame.slot.get('value') or '', 'confidence': _frame.slot.get('confidence') or 'experimental', 'edit_risk': _frame.risk, 'record_index': _frame.record_index or '', 'item_index': _frame.slot.get('item_index') or '', 'offset': _frame.slot.get('offset') or '', 'hex_offset': _frame.slot.get('hex_offset') or '', 'viewer_selection_id': _frame.viewer_id, 'editor_tab': 'Structured Editor', 'importable': 'true', 'field': _frame.slot.get('name') or '', 'explanation': _frame.slot.get('description') or 'Fixed-offset tuning slot; edit from Patchable Values.'}
                _state._connected_add_row(_frame.constraint_group, (_frame.slot_data['label'], _frame.slot_data['connected_label'], _frame.slot_kind, _state._value_with_dirty_preview(_frame.slot_data, _frame.slot_data['value']), _frame.slot_data['confidence'], _state._connected_risk_bucket(_frame.slot_data, str(_frame.slot_data['confidence']), _frame.risk), 'Edit value', f"record={_frame.record_index or ''}; item={_frame.slot.get('item_index') or ''}; offset={_frame.slot.get('hex_offset') or _frame.slot.get('offset') or ''}; viewer={_frame.viewer_id}"), _frame.slot_data, patchable=True)
                _frame.constraint_rows += 1
                _frame.total_rows += 1
    _frame.constraint_group.setExpanded(_frame.constraint_rows <= 100)
    _frame.value_group = _state.QTreeWidgetItem(('Patchable Values', '', '', '', '', '', '', 'Patchable and contextual rows routed through the structured editors.'))
    _frame.value_group.setData(0, _state.BROWSER_DATA_ROLE, {'kind': 'connected_group', 'label': 'Patchable Values'})
    _state.connected_tree.addTopLevelItem(_frame.value_group)
    _frame.value_rows = 0
    for _frame.group in _frame.root.findall('./editorModel/groups/group'):
        for _frame.row in _frame.group.findall('./rows/row')[:3000]:
            _frame.row_data = dict(_frame.row.attrib)
            _frame.row_data.setdefault('kind', 'connected_editor_row')
            _frame.row_data.setdefault('field', _frame.row.get('field') or _frame.row.get('label') or '')
            for _frame.child_name, _frame.key in (('explanation', 'explanation'), ('ifIncreased', 'if_increased'), ('ifDecreased', 'if_decreased'), ('safeEditHint', 'safe_edit_hint'), ('valueConstraints', 'value_constraints')):
                _frame.text = _frame.row.findtext(_frame.child_name, default='')
                if _frame.text:
                    _frame.row_data[_frame.key] = _frame.text
            _frame.importable = _frame.row.get('importable') == 'true'
            _frame.confidence = _frame.row.get('confidence') or 'experimental'
            _frame.risk = _frame.row.get('edit_risk') or ('safe' if _frame.importable else 'inferred')
            _frame.value = _state._value_with_dirty_preview(_frame.row_data, _state._connected_value_text(_frame.row.get('value') or '', _frame.row.get('original_value') or ''))
            _state._connected_add_row(_frame.value_group, (_frame.row.get('viewer_selection_id') or _frame.row.get('subject') or _frame.row.get('label') or _frame.row.get('id') or '', _frame.row.get('subject') or _frame.row.get('record_index') or '', _frame.row.get('field') or _frame.row.get('category') or '', _frame.value, _frame.confidence, _state._connected_risk_bucket(_frame.row_data, _frame.confidence, _frame.risk), 'Edit value' if _frame.importable else 'Context', f"editor={_frame.row.get('editor_tab') or ''}; record={_frame.row.get('record_index') or ''}; item={_frame.row.get('item_index') or ''}; offset={_frame.row.get('hex_offset') or _frame.row.get('offset') or ''}; effect={_frame.row.get('effect') or ''}"), _frame.row_data, patchable=_frame.importable)
            _frame.value_rows += 1
            _frame.total_rows += 1
    _frame.value_group.setExpanded(_frame.value_rows <= 80)
    if _frame.total_rows == 0:
        _state.connected_tree.addTopLevelItem(_state.QTreeWidgetItem(('No connected physics metadata was exported.', '', '', '', '', '', '', '')))
    _state._style_hkx_tree_values(_state.connected_tree, value_columns=(3, 7), confidence_column=4, guidance_columns=(0,), patchable_value_column=3)
    for _frame.column in range(_state.connected_tree.columnCount()):
        _state.connected_tree.resizeColumnToContents(_frame.column)
    _state._set_hkx_editor_section_title(9, f'Connected Physics ({_frame.total_rows})' if _frame.total_rows else 'Connected Physics')
    _state._apply_connected_physics_filter()
    if _state.connected_tree.currentItem() is None:
        _state._select_best_connected_row_for_target(_state.connected_target_filter_edit.text().strip())

def _dialog_step_0103(_state):
    def _populate_connected_physics_tree() -> None:
        _frame = SimpleNamespace()
        _populate_connected_physics_tree_part_010(_state, _frame)
        if _frame.root is None:
            return
        _populate_connected_physics_tree_part_011(_state, _frame)
        _populate_connected_physics_tree_part_012(_state, _frame)
    _state._populate_connected_physics_tree = _populate_connected_physics_tree

def _dialog_step_0104(_state):
    def _connected_item_matches_filter(item: QTreeWidgetItem) -> bool:
        data = item.data(0, _state.BROWSER_DATA_ROLE)
        data_map = data if isinstance(data, _state.Mapping) else {}
        row_text = " ".join(item.text(column) for column in range(_state.connected_tree.columnCount())).casefold()
        if data_map:
            row_text += " " + " ".join(str(value) for value in data_map.values()).casefold()
        target_filter = _state.connected_target_filter_edit.text().strip()
        workflow_terms = _state._filter_terms(str(_state.connected_workflow_combo.currentData() or ""))
        if target_filter and not _state._connected_row_text_matches_target(row_text, target_filter):
            return False
        if workflow_terms and not any(term in row_text for term in workflow_terms):
            return False
        risk_filter = str(_state.connected_risk_combo.currentData() or "")
        risk_bucket = str(data_map.get("risk_bucket") or item.text(5) or "").strip().casefold()
        if risk_filter == "safe" and risk_bucket != "safe":
            return False
        if risk_filter == "inferred" and risk_bucket != "inferred":
            return False
        if risk_filter == "experimental" and risk_bucket != "experimental":
            return False
        return True
    _state._connected_item_matches_filter = _connected_item_matches_filter

def _dialog_step_0105(_state):
    def _apply_connected_physics_filter() -> int:
        total_rows = 0
        visible_rows = 0

        def _apply_item(item: QTreeWidgetItem) -> bool:
            nonlocal total_rows, visible_rows
            total_rows += 1
            own_match = _state._connected_item_matches_filter(item)
            child_visible = False
            for child_index in range(item.childCount()):
                if _apply_item(item.child(child_index)):
                    child_visible = True
            visible = own_match or child_visible
            item.setHidden(not visible)
            if visible:
                visible_rows += 1
                if child_visible and _state.connected_target_filter_edit.text().strip():
                    item.setExpanded(True)
            return visible

        for top_index in range(_state.connected_tree.topLevelItemCount()):
            _apply_item(_state.connected_tree.topLevelItem(top_index))
        filters = []
        if _state.connected_target_filter_edit.text().strip():
            filters.append("target/text")
        if str(_state.connected_workflow_combo.currentData() or ""):
            filters.append(str(_state.connected_workflow_combo.currentText()))
        if str(_state.connected_risk_combo.currentData() or ""):
            filters.append(str(_state.connected_risk_combo.currentText()))
        suffix = f" | filters: {', '.join(filters)}" if filters else ""
        _state.connected_status_label.setText(f"{visible_rows:,} / {total_rows:,} connected physics row(s) visible{suffix}.")
        return visible_rows
    _state._apply_connected_physics_filter = _apply_connected_physics_filter

def _dialog_step_0106(_state):
    def _focus_connected_data(data: Mapping[str, object]) -> bool:
        editor_tab = str(data.get("editor_tab") or "").strip()
        record_index = str(data.get("record_index") or "").strip()
        field = str(data.get("field") or data.get("connected_label") or data.get("label") or "").strip()
        if editor_tab == "Structured Editor":
            _state.tuning_editable_only_checkbox.setChecked(str(data.get("importable") or "").strip().lower() == "true")
            item_index = str(data.get("item_index") or "").strip()
            _state.tuning_filter_edit.setText(" ".join(value for value in (record_index, item_index, field) if value).strip())
            _state._populate_tuning_tree()
            _state._set_hkx_editor_section(1)
            return True
        if editor_tab == "Collision Editor":
            viewer_id = str(data.get("viewer_selection_id") or "").strip()
            shape_hint = viewer_id.replace("shape/", "").replace("shape:", "")
            _state.collision_filter_edit.setText(" ".join(value for value in (shape_hint, field) if value).strip())
            _state._populate_collision_tree()
            _state._set_hkx_editor_section(2)
            return True
        if record_index:
            _state._set_hkx_editor_section(3)
            return True
        pattern = str(data.get("patch_path") or data.get("id") or data.get("label") or "").strip()
        if pattern:
            _state._set_hkx_editor_section(_state.tab_widget.count() - 1)
            _state.search_edit.setText(pattern)
            cursor = _state.editor.textCursor()
            cursor.movePosition(_state.QTextCursor.MoveOperation.Start)
            _state.editor.setTextCursor(cursor)
            _state.editor.find(pattern)
            return True
        return False
    _state._focus_connected_data = _focus_connected_data

def _dialog_step_0107(_state):
    def _focus_selected_connected_physics() -> None:
        data = _state._connected_current_data()
        if not data:
            _state.QMessageBox.information(_state.dialog, "Connected Physics", "Select a connected physics row first.")
            return
        if not _state._focus_connected_data(data):
            _state.QMessageBox.information(_state.dialog, "Connected Physics", "This row has no recovered editor or XML jump yet.")
            return
        _state._update_comparison_text_from_item(_state.connected_tree.currentItem())
        _state._update_connected_detail_text(_state.connected_tree.currentItem())
    _state._focus_selected_connected_physics = _focus_selected_connected_physics

def _dialog_step_0108(_state):
    def _highlight_selected_connected_physics() -> None:
        data = _state._connected_current_data()
        if not data:
            _state.connected_status_label.setText("Select a connected physics row first.")
            return
        if not _state._highlight_browser_data_in_preview(
            data,
            status_label=_state.connected_status_label,
            switch_to_embedded_preview=True,
        ) and not _state.connected_status_label.text().strip():
            _state.connected_status_label.setText(
                "This connected row has no visible 3D target yet. It may be a raw record, string, material, or unresolved reference rather than a decoded shape/constraint."
            )
    _state._highlight_selected_connected_physics = _highlight_selected_connected_physics

STEPS = (_dialog_step_0094, _dialog_step_0095, _dialog_step_0096, _dialog_step_0097, _dialog_step_0098, _dialog_step_0099, _dialog_step_0100, _dialog_step_0101, _dialog_step_0102, _dialog_step_0103, _dialog_step_0104, _dialog_step_0105, _dialog_step_0106, _dialog_step_0107, _dialog_step_0108,)
