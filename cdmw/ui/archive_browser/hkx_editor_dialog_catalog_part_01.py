from __future__ import annotations

from types import SimpleNamespace

def _populate_tuning_tree_part_013(_state, _frame):
    _frame.root = _state._load_xml_root_from_editor()

def _populate_tuning_tree_part_014(_state, _frame):
    _state.syncing_tree['active'] = True

def _dialog_step_0110(_state):
    def _populate_tuning_tree() -> None:
        _frame = SimpleNamespace()
        _populate_tuning_tree_part_013(_state, _frame)
        if _frame.root is None:
            return
        _populate_tuning_tree_part_014(_state, _frame)
        try:
            _state.tuning_tree.clear()
            _frame.group_elements = _frame.root.findall('./physicsTuning/groups/group')
            if not _frame.group_elements:
                _frame.placeholder = _state.QTreeWidgetItem(('No decoded physics tuning values found.', '', '', '', '', '', ''))
                _state.tuning_tree.addTopLevelItem(_frame.placeholder)
                _state._set_hkx_editor_section_title(1, 'Patchable Values')
                _state.tuning_status_label.setText('No physics tuning rows were decoded for this HKX.')
                return
            _frame.patchable_count = 0
            _frame.reference_count = 0
            _frame.patchable_only = _state.tuning_editable_only_checkbox.isChecked()
            for _frame.group_element in _frame.group_elements:
                _frame.category = _frame.group_element.get('category') or ''
                _frame.record_index = _frame.group_element.get('record_index') or ''
                _frame.type_name = _frame.group_element.get('type_name') or ''
                _frame.label = _frame.group_element.get('label') or _frame.type_name
                _frame.group_item = _state.QTreeWidgetItem((_frame.category, _frame.record_index, '', '', _frame.label, '', _frame.group_element.get('confidence') or 'experimental', _frame.group_element.findtext('description', default='')))
                _frame.group_item.setFirstColumnSpanned(False)
                _frame.group_item.setFlags(_frame.group_item.flags() & ~_state.Qt.ItemFlag.ItemIsEditable)
                _frame.group_item.setData(7, _state.Qt.ItemDataRole.UserRole, {'title': _frame.label, 'category': _frame.category, 'confidence': _frame.group_element.get('confidence') or 'experimental', 'description': _frame.group_element.findtext('description', default=''), 'edit_rule': _frame.group_element.get('edit_rule') or '', 'patchable': False})
                _state.tuning_tree.addTopLevelItem(_frame.group_item)
                if not _frame.patchable_only:
                    for _frame.hint_element in _frame.group_element.findall('./descriptorContextHints/hint'):
                        _frame.reference_count += 1
                        _frame.hint_name = _frame.hint_element.get('name') or ''
                        _frame.hint_value = _frame.hint_element.get('value') or ''
                        _frame.hint_source = _frame.hint_element.get('source') or 'descriptor_context'
                        _frame.hint_subject = _frame.hint_element.get('body_name') or _frame.hint_element.get('socket_name') or _frame.hint_element.get('constraint_tag') or ''
                        _frame.hint_item = _state.QTreeWidgetItem((_frame.category, _frame.record_index, _frame.hint_source, 'read-only', _frame.hint_name, _frame.hint_value, _frame.hint_element.get('confidence') or 'descriptor_context', f"{_frame.hint_subject} | Reference hint only; import ignores descriptor-context values. {_frame.hint_element.get('description') or ''}" if _frame.hint_subject else f"Reference hint only; import ignores descriptor-context values. {_frame.hint_element.get('description') or ''}"))
                        _frame.hint_item.setToolTip(0, _frame.hint_element.get('descriptor_path') or '')
                        _frame.hint_item.setToolTip(5, 'Read-only descriptor context. Edit the patchable rows with an Item and Offset below.')
                        _frame.hint_item.setData(7, _state.Qt.ItemDataRole.UserRole, {'title': _frame.hint_name, 'category': _frame.category, 'confidence': _frame.hint_element.get('confidence') or 'descriptor_context', 'description': _frame.hint_element.get('description') or '', 'descriptor_path': _frame.hint_element.get('descriptor_path') or '', 'body_name': _frame.hint_element.get('body_name') or '', 'socket_name': _frame.hint_element.get('socket_name') or '', 'patchable': False, 'read_only_reason': 'Read-only descriptor context. These values are not imported into the HKX.'})
                        _frame.hint_item.setFlags(_frame.hint_item.flags() & ~_state.Qt.ItemFlag.ItemIsEditable)
                        _frame.hint_item.setForeground(2, _state.QBrush(_state.QColor('#9aa7b4')))
                        _frame.hint_item.setForeground(3, _state.QBrush(_state.QColor('#9aa7b4')))
                        _frame.hint_item.setForeground(5, _state.QBrush(_state.QColor('#9aa7b4')))
                        _frame.group_item.addChild(_frame.hint_item)
                for _frame.slot_element in _frame.group_element.findall('./slots/slot'):
                    _frame.item_index = _frame.slot_element.get('item_index') or ''
                    _frame.offset = _frame.slot_element.get('hex_offset') or _frame.slot_element.get('offset') or ''
                    _frame.name = _frame.slot_element.get('name') or ''
                    _frame.value = _frame.slot_element.get('value') or ''
                    _frame.confidence = _frame.slot_element.get('confidence') or 'experimental'
                    _frame.description = _frame.slot_element.get('description') or ''
                    _frame.slot_key = (_frame.record_index, _frame.item_index, _frame.slot_element.get('offset') or '')
                    _frame.original_value = _state._remember_initial_value('tuning', _frame.slot_key, _frame.value)
                    _frame.slot_item = _state.QTreeWidgetItem((_frame.category, _frame.record_index, _frame.item_index, _frame.offset, _frame.name, _frame.value, _frame.confidence, _frame.description))
                    _frame.slot_item.setData(5, _state.Qt.ItemDataRole.UserRole, _frame.slot_key)
                    _frame.slot_item.setData(5, _state.ORIGINAL_VALUE_ROLE, _frame.original_value)
                    _frame.slot_item.setData(5, _state.DIRTY_KEY_ROLE, _state._dirty_lookup('tuning', _frame.slot_key))
                    _frame.slot_item.setData(7, _state.Qt.ItemDataRole.UserRole, {'title': _frame.name, 'category': _frame.category, 'record_index': _frame.record_index, 'item_index': _frame.item_index, 'offset': _frame.offset, 'confidence': _frame.confidence, 'description': _frame.description, 'plain_language_effect': _frame.slot_element.get('plain_language_effect') or '', 'if_increased': _frame.slot_element.get('if_increased') or '', 'if_decreased': _frame.slot_element.get('if_decreased') or '', 'safe_edit_hint': _frame.slot_element.get('safe_edit_hint') or '', 'edit_risk': _frame.slot_element.get('edit_risk') or '', 'value_constraints': _frame.slot_element.get('value_constraints') or '', 'suggested_edit_step': _frame.slot_element.get('suggested_edit_step') or '', 'patchable': True})
                    _frame.slot_item.setToolTip(5, 'Patchable value. Double-click this Value cell or use Edit Selected Value.')
                    _frame.slot_item.setToolTip(7, 'Plain-language effect: ' + (_frame.slot_element.get('plain_language_effect') or 'unknown') + '\nIf increased: ' + (_frame.slot_element.get('if_increased') or 'not recovered') + '\nIf decreased: ' + (_frame.slot_element.get('if_decreased') or 'not recovered') + '\nSafe edit hint: ' + (_frame.slot_element.get('safe_edit_hint') or 'change one value at a time') + '\nEdit risk: ' + (_frame.slot_element.get('edit_risk') or 'experimental') + '\nValue constraints: ' + (_frame.slot_element.get('value_constraints') or 'finite float; fixed offset') + '\nEdit note: ' + (_frame.slot_element.get('suggested_edit_step') or 'Fixed-size value; avoid count, topology, reference, and string changes.'))
                    _frame.slot_item.setFlags(_frame.slot_item.flags() | _state.Qt.ItemFlag.ItemIsEditable)
                    _frame.slot_item.setForeground(5, _state.QBrush(_state.QColor('#9fd0ff')))
                    _state._set_dirty_item_style(_frame.slot_item, 5, _frame.value.strip() != _frame.original_value.strip())
                    _frame.group_item.addChild(_frame.slot_item)
                    _frame.patchable_count += 1
                _frame.group_item.setExpanded(True)
            _state._style_hkx_tree_values(_state.tuning_tree, value_columns=(1, 2, 3, 5), offset_columns=(3,), confidence_column=6, guidance_columns=(7,), patchable_value_column=5)
            for _frame.column in range(_state.tuning_tree.columnCount()):
                _state.tuning_tree.resizeColumnToContents(_frame.column)
            _state.tuning_status_label.setText(f'{_frame.patchable_count:,} patchable value(s)' + (f'; {_frame.reference_count:,} read-only descriptor hint(s)' if not _frame.patchable_only else '; reference hints hidden'))
            _state._set_hkx_editor_section_title(1, f'Patchable Values ({len(_frame.group_elements)} / {_frame.patchable_count})')
            _state._apply_tuning_filter()
            _frame.first_visible = _state._first_visible_tuning_item()
            if _frame.first_visible is not None:
                _state.tuning_tree.setCurrentItem(_frame.first_visible)
            _state._update_tuning_guidance(_state.tuning_tree.currentItem())
        finally:
            _state.syncing_tree['active'] = False
    _state._populate_tuning_tree = _populate_tuning_tree

def _dialog_step_0111(_state):
    def _update_tuning_guidance(current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem] = None) -> None:
        if current is None:
            _state.tuning_guidance_text.clear()
            return
        guidance = current.data(7, _state.Qt.ItemDataRole.UserRole)
        if not isinstance(guidance, _state.Mapping):
            _state.tuning_guidance_text.setPlainText("Select a patchable tuning value to see editing guidance.")
            return
        lines: List[str] = []
        title = str(guidance.get("title") or current.text(4) or current.text(0) or "HKX tuning value")
        lines.append(title)
        category = str(guidance.get("category") or "")
        confidence = str(guidance.get("confidence") or "experimental")
        if category or confidence:
            lines.append(f"Category: {category or 'unknown'} | Confidence: {confidence}")
        if guidance.get("patchable"):
            record_index = str(guidance.get("record_index") or "")
            item_index = str(guidance.get("item_index") or "")
            offset = str(guidance.get("offset") or "")
            edit_risk = str(guidance.get("edit_risk") or "experimental")
            lines.append(f"Patch target: record {record_index}, item {item_index}, offset {offset} | Edit risk: {edit_risk}")
            effect = str(guidance.get("plain_language_effect") or "unknown")
            if_increased = str(guidance.get("if_increased") or "Effect of increasing this value is not recovered yet.")
            if_decreased = str(guidance.get("if_decreased") or "Effect of decreasing this value is not recovered yet.")
            safe_hint = str(guidance.get("safe_edit_hint") or "Change one value at a time and test in game.")
            value_constraints = str(guidance.get("value_constraints") or "finite float; fixed offset; same payload length")
            edit_note = str(
                guidance.get("suggested_edit_step")
                or "Fixed-size value; avoid count, topology, reference, and string changes."
            )
            lines.extend(
                [
                    f"Plain-language effect: {effect}",
                    f"If increased: {if_increased}",
                    f"If decreased: {if_decreased}",
                    f"Safe edit hint: {safe_hint}",
                    f"Value constraints: {value_constraints}",
                    f"Edit note: {edit_note}",
                ]
            )
        else:
            read_only_reason = str(guidance.get("read_only_reason") or "This row is context or a group header; it is not imported into the HKX.")
            lines.append(read_only_reason)
            descriptor_path = str(guidance.get("descriptor_path") or "")
            if descriptor_path:
                lines.append(f"Descriptor: {descriptor_path}")
        description = str(guidance.get("description") or "").strip()
        if description:
            lines.append(f"Description: {description}")
        _state.tuning_guidance_text.setPlainText("\n".join(lines))
    _state._update_tuning_guidance = _update_tuning_guidance

def _dialog_step_0112(_state):
    def _tuning_item_matches_filter(item: QTreeWidgetItem, needle: str) -> bool:
        if not needle:
            return True
        row_text = " ".join(item.text(column) for column in range(_state.tuning_tree.columnCount())).casefold()
        return _state._row_matches_filter_terms(row_text, needle)
    _state._tuning_item_matches_filter = _tuning_item_matches_filter

def _dialog_step_0113(_state):
    def _first_visible_tuning_item() -> Optional[QTreeWidgetItem]:
        for group_index in range(_state.tuning_tree.topLevelItemCount()):
            group_item = _state.tuning_tree.topLevelItem(group_index)
            if group_item.isHidden():
                continue
            for child_index in range(group_item.childCount()):
                child_item = group_item.child(child_index)
                if not child_item.isHidden():
                    return child_item
            return group_item
        return None
    _state._first_visible_tuning_item = _first_visible_tuning_item

def _dialog_step_0114(_state):
    def _apply_tuning_filter() -> None:
        needle = _state.tuning_filter_edit.text().strip().casefold()
        visible_groups = 0
        visible_rows = 0
        for group_index in range(_state.tuning_tree.topLevelItemCount()):
            group_item = _state.tuning_tree.topLevelItem(group_index)
            group_matches = _state._tuning_item_matches_filter(group_item, needle)
            child_visible = 0
            for child_index in range(group_item.childCount()):
                child_item = group_item.child(child_index)
                child_matches = _state._tuning_item_matches_filter(child_item, needle)
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
            _state.tuning_status_label.setText(
                f"Filter: {visible_groups:,} group(s), {visible_rows:,} visible row(s). "
                "Patchable rows have Item and Offset; descriptor_context rows are read-only."
            )
        current = _state.tuning_tree.currentItem()
        if current is not None and current.isHidden():
            replacement = _state._first_visible_tuning_item()
            if replacement is not None:
                _state.tuning_tree.setCurrentItem(replacement)
    _state._apply_tuning_filter = _apply_tuning_filter

def _dialog_step_0115(_state):
    def _populate_object_layout_tree() -> None:
        root = _state._load_xml_root_from_editor()
        if root is None:
            return
        _state.object_layout_tree.clear()
        object_elements = root.findall("./objects/object")
        if not object_elements:
            placeholder = _state.QTreeWidgetItem(("No decoded object layout records found.", "", "", "", "", "", "", "", ""))
            _state.object_layout_tree.addTopLevelItem(placeholder)
            _state._set_hkx_editor_section_title(3, "Object Layout")
            return
        shown_field_count = 0
        for object_element in object_elements:
            record_index = object_element.get("record_index") or ""
            type_name = object_element.get("type_name") or ""
            status = object_element.get("status") or ""
            status_label, status_tip, status_color = _state._hkx_status_display(status)
            status_text = object_element.get("status_label") or status_label
            status_reason = object_element.get("status_reason") or status_tip
            missing_requirements = object_element.get("missing_requirements") or ""
            confidence = object_element.get("confidence") or ""
            description = object_element.findtext("description", default="")
            if status_reason and status_reason not in description:
                description = f"{description} {status_reason}".strip()
            object_item = _state.QTreeWidgetItem(
                (
                    record_index,
                    type_name,
                    status_text,
                    "",
                    object_element.get("byte_length") or "",
                    f"record {record_index}",
                    "",
                    confidence,
                    description,
                )
            )
            object_item.setData(
                0,
                _state.Qt.ItemDataRole.UserRole,
                {
                    "status": status,
                    "status_label": status_text,
                    "decode_category": object_element.get("decode_category") or "",
                    "status_reason": status_reason,
                    "missing_requirements": missing_requirements,
                },
            )
            object_item.setForeground(2, _state.QBrush(status_color))
            object_item.setToolTip(2, status_reason)
            if missing_requirements:
                object_item.setToolTip(5, f"Missing for full decode: {missing_requirements}")
            _state.object_layout_tree.addTopLevelItem(object_item)
            for field_element in object_element.findall("./layout/field"):
                value_text = field_element.findtext("value", default="")
                if len(value_text) > 180:
                    value_text = value_text[:177] + "..."
                field_item = _state.QTreeWidgetItem(
                    (
                        record_index,
                        type_name,
                        "field",
                        field_element.get("hex_offset") or field_element.get("offset") or "",
                        field_element.get("size") or "",
                        field_element.get("name") or "",
                        value_text,
                        field_element.get("confidence") or "",
                        field_element.get("description") or "",
                    )
                )
                object_item.addChild(field_item)
                shown_field_count += 1
            references_element = object_element.find("references")
            if references_element is not None:
                references_item = _state.QTreeWidgetItem((record_index, type_name, "references", "", "", "reference candidates", "", "experimental", "Words that match other ITEM record offsets."))
                object_item.addChild(references_item)
                for reference_element in references_element.findall("reference"):
                    target = (
                        f"record {reference_element.get('target_record_index') or '?'} "
                        f"{reference_element.get('target_type_name') or ''}"
                    ).strip()
                    reference_item = _state.QTreeWidgetItem(
                        (
                            record_index,
                            type_name,
                            reference_element.get("kind") or "reference",
                            reference_element.get("hex_offset") or reference_element.get("offset") or "",
                            "4",
                            target,
                            reference_element.get("raw_value") or "",
                            reference_element.get("confidence") or "experimental",
                            "Possible ITEM reference candidate inferred from matching offset values.",
                        )
                    )
                    references_item.addChild(reference_item)
            raw_ranges_element = object_element.find("rawRanges")
            if raw_ranges_element is not None:
                raw_item = _state.QTreeWidgetItem((record_index, type_name, "raw", "", "", "raw preserved ranges", "", "raw", "Original bytes preserved unless supported edits are applied."))
                object_item.addChild(raw_item)
                for range_element in raw_ranges_element.findall("range"):
                    raw_range_item = _state.QTreeWidgetItem(
                        (
                            record_index,
                            type_name,
                            range_element.get("edit_rule") or "raw",
                            range_element.get("hex_offset") or range_element.get("offset") or "",
                            range_element.get("size") or "",
                            range_element.get("name") or "",
                            range_element.get("encoding") or "",
                            "raw",
                            range_element.get("description") or "",
                        )
                    )
                    raw_item.addChild(raw_range_item)
            object_item.setExpanded(False)
        _state._style_hkx_tree_values(
            _state.object_layout_tree,
            value_columns=(0, 3, 4, 6),
            offset_columns=(3,),
            confidence_column=7,
        )
        for column in range(_state.object_layout_tree.columnCount()):
            _state.object_layout_tree.resizeColumnToContents(column)
        _state._set_hkx_editor_section_title(3, f"Object Layout ({len(object_elements)} / {shown_field_count})")
    _state._populate_object_layout_tree = _populate_object_layout_tree

def _populate_context_hints_tree_part_015(_state, _frame):
    _frame.root = _state._load_xml_root_from_editor()

def _populate_context_hints_tree_part_016(_state, _frame):
    _state.context_tree.clear()
    _frame.descriptors = _frame.root.findall('./companionDescriptorHints/descriptor')
    _frame.body_context = _frame.root.find('./physicsBodyContext')
    _frame.physics_material_context = _frame.root.find('./physicsMaterialContext')
    _frame.physics_names = _frame.root.find('./physicsNames')
    _frame.physics_body_summary = _frame.root.find('./physicsBodySummary')

def _populate_context_hints_tree_part_017(_state, _frame):
    _frame.row_count = 0
    if _frame.body_context is not None:
        _frame.context_item = _state.QTreeWidgetItem(('HKX + descriptors', 'physics_body_context', _frame.body_context.get('status') or '', f"bodies={_frame.body_context.get('body_count') or '0'}, constraints={_frame.body_context.get('constraint_hint_count') or '0'}", _frame.body_context.findtext('description', default='')))
        _state.context_tree.addTopLevelItem(_frame.context_item)
        for _frame.body_element in _frame.body_context.findall('./bodies/body'):
            _frame.body_label = _frame.body_element.get('body_name') or _frame.body_element.get('socket_name') or f"body {_frame.body_element.get('descriptor_body_index') or ''}"
            _frame.body_item = _state.QTreeWidgetItem((_frame.body_element.get('descriptor_path') or '', 'body_context', _frame.body_label, f"socket={_frame.body_element.get('socket_name') or ''}; material={_frame.body_element.get('physics_material_name') or ''}", _frame.body_element.findtext('description', default='')))
            _frame.context_item.addChild(_frame.body_item)
            for _frame.hint_element in _frame.body_element.findall('./numericHints/hint'):
                _frame.body_item.addChild(_state.QTreeWidgetItem((_frame.body_element.get('descriptor_path') or '', 'body_numeric_hint', _frame.hint_element.get('name') or '', _frame.hint_element.get('value') or '', _frame.hint_element.get('description') or '')))
                _frame.row_count += 1
            for _frame.match_element in _frame.body_element.findall('./shapeMatches/shape'):
                _frame.decoded = f"{_frame.match_element.get('decoded_shape_type') or 'shape'} #{_frame.match_element.get('decoded_shape_index') or '?'}"
                _frame.details = []
                for _frame.attr_name in ('descriptor_radius', 'descriptor_height', 'decoded_radius', 'decoded_length'):
                    if _frame.match_element.get(_frame.attr_name) is not None:
                        _frame.details.append(f'{_frame.attr_name}={_frame.match_element.get(_frame.attr_name)}')
                _frame.match_item = _state.QTreeWidgetItem((_frame.body_element.get('descriptor_path') or '', 'shape_match', _frame.decoded, '; '.join(_frame.details), _frame.match_element.findtext('description', default='')))
                _frame.body_item.addChild(_frame.match_item)
                _frame.row_count += 1
        for _frame.constraint_element in _frame.body_context.findall('./constraints/constraint'):
            _frame.constraint_item = _state.QTreeWidgetItem((_frame.constraint_element.get('descriptor_path') or '', 'constraint_context', _frame.constraint_element.get('tag') or '', _frame.constraint_element.get('body_name') or _frame.constraint_element.get('socket_name') or '', _frame.constraint_element.findtext('description', default='')))
            _frame.context_item.addChild(_frame.constraint_item)
            for _frame.hint_element in _frame.constraint_element.findall('./numericHints/hint'):
                _frame.constraint_item.addChild(_state.QTreeWidgetItem((_frame.constraint_element.get('descriptor_path') or '', 'constraint_numeric_hint', _frame.hint_element.get('name') or '', _frame.hint_element.get('value') or '', _frame.hint_element.get('description') or '')))
                _frame.row_count += 1
        _frame.context_item.setExpanded(True)
    if _frame.physics_material_context is not None:
        _frame.material_hints = _frame.physics_material_context.findall('./hints/hint')
        _frame.material_item = _state.QTreeWidgetItem(('model/material descriptors', 'physics_material_context', _frame.physics_material_context.get('status') or '', f'simulation hints={len(_frame.material_hints)}', _frame.physics_material_context.findtext('description', default='')))
        _state.context_tree.addTopLevelItem(_frame.material_item)
        for _frame.hint_element in _frame.material_hints:
            _frame.name = _frame.hint_element.get('submesh_name') or _frame.hint_element.get('pbd_simulation_material') or _frame.hint_element.get('material_name') or f"hint {_frame.hint_element.get('index') or ''}"
            _frame.details = []
            for _frame.attr_name, _frame.label in (('simulation_role', 'role'), ('pbd_simulation_material', 'pbd'), ('material_name', 'material'), ('jiggle_wind_weight', 'wind'), ('parameter_name', 'parameter'), ('parameter_value', 'value')):
                _frame.value = _frame.hint_element.get(_frame.attr_name)
                if _frame.value:
                    _frame.details.append(f'{_frame.label}={_frame.value}')
            _frame.material_item.addChild(_state.QTreeWidgetItem((_frame.hint_element.get('descriptor_path') or '', 'material_simulation_hint', _frame.name, '; '.join(_frame.details), _frame.hint_element.get('simulation_role_description') or '')))
            _frame.row_count += 1
        _frame.material_item.setExpanded(True)
    if _frame.physics_names is not None:
        _frame.shape_names = _frame.physics_names.findall('./shapeNameProperties/shapeName')
        _frame.char_strings = _frame.physics_names.findall('./charStrings/string')
        _frame.names_item = _state.QTreeWidgetItem(('HKX', 'physics_names', 'char strings / HavokShapeNameProperty', f'strings={len(_frame.char_strings)}, shape names={len(_frame.shape_names)}', _frame.physics_names.findtext('description', default='')))
        _state.context_tree.addTopLevelItem(_frame.names_item)
        for _frame.string_element in _frame.char_strings:
            _frame.string_item = _state.QTreeWidgetItem(('HKX', 'char_string', _frame.string_element.get('text') or '', f"record={_frame.string_element.get('record_index') or ''}; role={_frame.string_element.get('simulation_role') or ''}", _frame.string_element.get('simulation_role_description') or _frame.string_element.get('description') or 'Decoded in-HKX string.'))
            _frame.names_item.addChild(_frame.string_item)
            _frame.row_count += 1
        for _frame.shape_name_element in _frame.shape_names:
            _frame.name_item = _state.QTreeWidgetItem(('HKX', 'shape_name', _frame.shape_name_element.get('name') or '', f"property_record={_frame.shape_name_element.get('property_record_index') or ''}; name_record={_frame.shape_name_element.get('name_record_index') or ''}; role={_frame.shape_name_element.get('simulation_role') or ''}", _frame.shape_name_element.get('description') or 'Decoded in-HKX ragdoll/body shape label.'))
            _frame.names_item.addChild(_frame.name_item)
            _frame.row_count += 1
        _frame.names_item.setExpanded(True)
    if _frame.physics_body_summary is not None:
        _frame.body_elements = _frame.physics_body_summary.findall('./bodies/body')
        _frame.summary_item = _state.QTreeWidgetItem(('HKX', 'physics_body_summary', f'bodies={len(_frame.body_elements)}', _frame.physics_body_summary.get('confidence') or '', _frame.physics_body_summary.findtext('description', default='')))
        _state.context_tree.addTopLevelItem(_frame.summary_item)
        for _frame.body_element in _frame.body_elements:
            _frame.capsule_element = _frame.body_element.find('capsule')
            _frame.details = []
            if _frame.capsule_element is not None:
                _frame.details.append(f"radius={_frame.capsule_element.get('radius') or ''}")
                _frame.details.append(f"length={_frame.capsule_element.get('length') or ''}")
            if _frame.body_element.get('socket_name'):
                _frame.details.append(f"socket={_frame.body_element.get('socket_name')}")
            _frame.body_item = _state.QTreeWidgetItem(('HKX', 'body_summary', _frame.body_element.get('body_name') or f"shape {_frame.body_element.get('shape_index') or ''}", '; '.join((value for value in _frame.details if value and (not value.endswith('=')))), _frame.body_element.findtext('description', default='')))
            _frame.summary_item.addChild(_frame.body_item)
            _frame.row_count += 1
            for _frame.context_element in _frame.body_element.findall('./descriptorContexts/context'):
                _frame.context_item = _state.QTreeWidgetItem((_frame.context_element.get('descriptor_path') or 'descriptor', 'body_summary_descriptor_context', _frame.context_element.get('body_name') or '', f"socket={_frame.context_element.get('socket_name') or _frame.context_element.get('fixed_socket_name') or ''}; material={_frame.context_element.get('physics_material_name') or ''}".strip('; '), 'Descriptor context near this shape; shown separately from the in-HKX body name.'))
                _frame.body_item.addChild(_frame.context_item)
                _frame.row_count += 1
        _frame.summary_item.setExpanded(True)

def _populate_context_hints_tree_part_018(_state, _frame):
    for _frame.descriptor in _frame.descriptors:
        _frame.source_path = _frame.descriptor.get('path') or _frame.descriptor.get('stem') or 'descriptor'
        _frame.descriptor_item = _state.QTreeWidgetItem((_frame.source_path, 'descriptor', _frame.descriptor.get('root_tag') or '', f"bodies={_frame.descriptor.get('body_desc_count') or '0'}, constraints={_frame.descriptor.get('constraint_desc_count') or '0'}, shapes={_frame.descriptor.get('shape_desc_count') or '0'}", _frame.descriptor.findtext('description', default='')))
        _state.context_tree.addTopLevelItem(_frame.descriptor_item)
        for _frame.group_name, _frame.category, _frame.value_attr in (('body_names', 'body', 'name'), ('socket_names', 'socket', 'name'), ('fixed_socket_names', 'fixed_socket', 'name'), ('physics_material_names', 'physics_material', 'name')):
            _frame.group_element = _frame.descriptor.find(_frame.group_name)
            if _frame.group_element is None:
                continue
            _frame.group_item = _state.QTreeWidgetItem((_frame.source_path, _frame.category, _frame.group_name, '', 'Descriptor names that can help label matching HKX body/shape records.'))
            _frame.descriptor_item.addChild(_frame.group_item)
            for _frame.value_element in list(_frame.group_element):
                _frame.value = _frame.value_element.get(_frame.value_attr) or (_frame.value_element.text or '').strip()
                if not _frame.value:
                    continue
                _frame.group_item.addChild(_state.QTreeWidgetItem((_frame.source_path, _frame.category, _frame.value, '', '')))
                _frame.row_count += 1
        _frame.numeric_element = _frame.descriptor.find('numericHints')
        if _frame.numeric_element is not None:
            _frame.numeric_item = _state.QTreeWidgetItem((_frame.source_path, 'numeric_hints', 'descriptor numeric values', '', 'Likely body/constraint tuning values from referenced descriptor XML.'))
            _frame.descriptor_item.addChild(_frame.numeric_item)
            for _frame.hint_element in _frame.numeric_element.findall('hint'):
                _frame.name = _frame.hint_element.get('name') or ''
                _frame.description = _frame.hint_element.get('description') or ''
                _frame.hint_item = _state.QTreeWidgetItem((_frame.source_path, 'numeric_hint', _frame.name, '', _frame.description))
                _frame.numeric_item.addChild(_frame.hint_item)
                for _frame.value_element in _frame.hint_element.findall('value'):
                    _frame.value = (_frame.value_element.text or '').strip()
                    if not _frame.value:
                        continue
                    _frame.hint_item.addChild(_state.QTreeWidgetItem((_frame.source_path, 'value', _frame.name, _frame.value, _frame.description)))
                    _frame.row_count += 1
        _frame.descriptor_item.setExpanded(True)
    _state._style_hkx_tree_values(_state.context_tree, value_columns=(3,))
    for _frame.column in range(_state.context_tree.columnCount()):
        _state.context_tree.resizeColumnToContents(_frame.column)
    _frame.context_count = len(_frame.descriptors) + (1 if _frame.body_context is not None else 0) + (1 if _frame.physics_material_context is not None else 0) + (1 if _frame.physics_names is not None else 0) + (1 if _frame.physics_body_summary is not None else 0)
    _state._set_hkx_editor_section_title(4, f'Context Hints ({_frame.context_count} / {_frame.row_count})')

def _dialog_step_0116(_state):
    def _populate_context_hints_tree() -> None:
        _frame = SimpleNamespace()
        _populate_context_hints_tree_part_015(_state, _frame)
        if _frame.root is None:
            return
        _populate_context_hints_tree_part_016(_state, _frame)
        if not _frame.descriptors and _frame.body_context is None and (_frame.physics_material_context is None) and (_frame.physics_names is None) and (_frame.physics_body_summary is None):
            _frame.placeholder = _state.QTreeWidgetItem(('No companion descriptor hints found.', '', '', '', ''))
            _state.context_tree.addTopLevelItem(_frame.placeholder)
            _state._set_hkx_editor_section_title(4, 'Context Hints')
            return
        _populate_context_hints_tree_part_017(_state, _frame)
        _populate_context_hints_tree_part_018(_state, _frame)
    _state._populate_context_hints_tree = _populate_context_hints_tree

def _dialog_step_0117(_state):
    def _populate_body_summary_tree() -> None:
        root = _state._load_xml_root_from_editor()
        if root is None:
            return
        _state.body_summary_tree.clear()
        body_elements = root.findall("./physicsBodySummary/bodies/body")
        if not body_elements:
            placeholder = _state.QTreeWidgetItem(("No decoded HKX body summary found.", "", "", "", "", "", "", ""))
            _state.body_summary_tree.addTopLevelItem(placeholder)
            _state._set_hkx_editor_section_title(5, "Body Summary")
            return
        row_count = 0
        for body_element in body_elements:
            capsule_element = body_element.find("capsule")
            radius = capsule_element.get("radius") if capsule_element is not None else ""
            length = capsule_element.get("length") if capsule_element is not None else ""
            context_bits = []
            if body_element.get("socket_name"):
                context_bits.append(f"socket={body_element.get('socket_name')}")
            if body_element.get("physics_material_name"):
                context_bits.append(f"material={body_element.get('physics_material_name')}")
            body_item = _state.QTreeWidgetItem(
                (
                    body_element.get("body_name") or f"shape {body_element.get('shape_index') or ''}",
                    f"{body_element.get('shape_type') or ''} #{body_element.get('shape_index') or ''}",
                    radius or "",
                    length or "",
                    "; ".join(context_bits),
                    body_element.get("editable_fields") or "",
                    body_element.get("confidence") or "experimental",
                    body_element.findtext("description", default=""),
                )
            )
            _state.body_summary_tree.addTopLevelItem(body_item)
            row_count += 1
            for context_element in body_element.findall("./descriptorContexts/context"):
                context_item = _state.QTreeWidgetItem(
                    (
                        context_element.get("body_name") or "descriptor context",
                        "",
                        "",
                        "",
                        (
                            f"socket={context_element.get('socket_name') or context_element.get('fixed_socket_name') or ''}; "
                            f"material={context_element.get('physics_material_name') or ''}"
                        ).strip("; "),
                        "",
                        context_element.get("confidence") or "descriptor_context",
                        "Descriptor-side body/socket/material context near this HKX shape; read-only and ignored on import.",
                    )
                )
                context_item.setToolTip(0, context_element.get("descriptor_path") or "")
                body_item.addChild(context_item)
                row_count += 1
            body_item.setExpanded(True)
        _state._style_hkx_tree_values(
            _state.body_summary_tree,
            value_columns=(1, 2, 3, 4, 5),
            confidence_column=6,
        )
        for column in range(_state.body_summary_tree.columnCount()):
            _state.body_summary_tree.resizeColumnToContents(column)
        _state._set_hkx_editor_section_title(5, f"Body Summary ({len(body_elements)} / {row_count})")
    _state._populate_body_summary_tree = _populate_body_summary_tree

def _dialog_step_0118(_state):
    def _populate_constraint_summary_tree() -> None:
        root = _state._load_xml_root_from_editor()
        if root is None:
            return
        _state.constraint_summary_tree.clear()
        constraint_elements = root.findall("./physicsConstraintSummary/constraints/constraint")
        if not constraint_elements:
            placeholder = _state.QTreeWidgetItem(("No decoded HKX constraint summary found.", "", "", "", "", "", "", ""))
            _state.constraint_summary_tree.addTopLevelItem(placeholder)
            _state._set_hkx_editor_section_title(6, "Constraint Summary")
            return
        row_count = 0
        for constraint_element in constraint_elements:
            constraint_item = _state.QTreeWidgetItem(
                (
                    constraint_element.get("name") or f"constraint {constraint_element.get('index') or ''}",
                    constraint_element.get("type_name") or "",
                    constraint_element.get("constraint_record_index") or "",
                    constraint_element.get("motor_record_index") or "",
                    "",
                    "",
                    constraint_element.get("confidence") or "experimental",
                    constraint_element.findtext("description", default=""),
                )
            )
            _state.constraint_summary_tree.addTopLevelItem(constraint_item)
            row_count += 1
            descriptor_context = constraint_element.find("descriptorContext")
            if descriptor_context is not None:
                context_item = _state.QTreeWidgetItem(
                    (
                        constraint_element.get("name") or "",
                        "descriptor_context",
                        "",
                        "",
                        descriptor_context.get("tag") or "",
                        (
                            f"body={descriptor_context.get('body_name') or ''}; "
                            f"socket={descriptor_context.get('socket_name') or descriptor_context.get('fixed_socket_name') or ''}"
                        ).strip("; "),
                        descriptor_context.get("confidence") or "descriptor_context",
                        "Read-only descriptor XML hint for this constraint.",
                    )
                )
                context_item.setToolTip(0, descriptor_context.get("descriptor_path") or "")
                constraint_item.addChild(context_item)
                row_count += 1
                for hint_element in descriptor_context.findall("./numericHints/hint"):
                    hint_item = _state.QTreeWidgetItem(
                        (
                            constraint_element.get("name") or "",
                            "descriptor_hint",
                            "",
                            "",
                            hint_element.get("name") or "",
                            hint_element.get("value") or "",
                            "descriptor_context",
                            hint_element.get("description") or "",
                        )
                    )
                    context_item.addChild(hint_item)
                    row_count += 1
            for slot_parent_name, slot_kind in (("constraint_slots", "constraint_slot"), ("motor_slots", "motor_slot")):
                for slot_element in constraint_element.findall(f"./{slot_parent_name}/*"):
                    slot_item = _state.QTreeWidgetItem(
                        (
                            constraint_element.get("name") or "",
                            slot_kind,
                            constraint_element.get("constraint_record_index") or "",
                            constraint_element.get("motor_record_index") or "",
                            f"{slot_element.get('name') or ''} {slot_element.get('hex_offset') or ''}".strip(),
                            slot_element.get("value") or "",
                            slot_element.get("confidence") or "experimental",
                            slot_element.get("description") or "Fixed-offset tuning slot; edit from Patchable Values.",
                        )
                    )
                    slot_item.setData(
                        4,
                        _state.Qt.ItemDataRole.UserRole,
                        {
                            "record_index": constraint_element.get("motor_record_index")
                            if slot_kind == "motor_slot"
                            else constraint_element.get("constraint_record_index"),
                            "slot_name": slot_element.get("name") or "",
                            "hex_offset": slot_element.get("hex_offset") or "",
                        },
                    )
                    slot_item.setToolTip(4, "Double-click or use Show in Patchable Values to edit the linked patchable value.")
                    constraint_item.addChild(slot_item)
                    row_count += 1
            constraint_item.setExpanded(True)
        _state._style_hkx_tree_values(
            _state.constraint_summary_tree,
            value_columns=(2, 3, 4, 5),
            confidence_column=6,
        )
        for column in range(_state.constraint_summary_tree.columnCount()):
            _state.constraint_summary_tree.resizeColumnToContents(column)
        _state._set_hkx_editor_section_title(6, f"Constraint Summary ({len(constraint_elements)} / {row_count})")
    _state._populate_constraint_summary_tree = _populate_constraint_summary_tree

def _dialog_step_0119(_state):
    def _focus_selected_constraint_slot_in_tuning() -> None:
        item = _state.constraint_summary_tree.currentItem()
        if item is None:
            _state.QMessageBox.information(_state.dialog, "Constraint Summary", "Select a constraint or motor slot first.")
            return
        slot_data = item.data(4, _state.Qt.ItemDataRole.UserRole)
        if not isinstance(slot_data, dict):
            _state.QMessageBox.information(
                _state.dialog,
                "Constraint Summary",
                "Select a constraint_slot or motor_slot child row to jump to its patchable value.",
            )
            return
        record_index = str(slot_data.get("record_index") or "").strip()
        slot_name = str(slot_data.get("slot_name") or "").strip()
        if not record_index:
            _state.QMessageBox.information(_state.dialog, "Constraint Summary", "This row has no linked tuning record.")
            return
        _state.tuning_editable_only_checkbox.setChecked(True)
        _state.tuning_filter_edit.setText(f"{record_index} {slot_name}".strip())
        _state._set_hkx_editor_section(1)
        _state._populate_tuning_tree()
    _state._focus_selected_constraint_slot_in_tuning = _focus_selected_constraint_slot_in_tuning

def _dialog_step_0120(_state):
    def _focus_constraint_slot_from_cell(item: QTreeWidgetItem, _column: int) -> None:
        _state.constraint_summary_tree.setCurrentItem(item)
        _state._focus_selected_constraint_slot_in_tuning()
    _state._focus_constraint_slot_from_cell = _focus_constraint_slot_from_cell

STEPS = (_dialog_step_0110, _dialog_step_0111, _dialog_step_0112, _dialog_step_0113, _dialog_step_0114, _dialog_step_0115, _dialog_step_0116, _dialog_step_0117, _dialog_step_0118, _dialog_step_0119, _dialog_step_0120,)
