from __future__ import annotations

from types import SimpleNamespace

def _populate_collision_tree_part_019(_state, _frame):
    _frame.root = _state._load_xml_root_from_editor()

def _populate_collision_tree_part_020(_state, _frame):
    _state.syncing_collision_tree['active'] = True

def _populate_collision_tree_part_021(_state, _frame):
    _state.collision_tree.clear()
    _frame.shape_elements = _frame.root.findall('./shapes/shape')

def _populate_collision_tree_part_022(_state, _frame):
    _frame.editable_row_count = 0
    _frame.read_only_row_count = 0
    _frame.max_rows = 3000
    _frame.truncated = False
    _frame.context_by_shape = _state._collision_context_by_shape_index(_frame.root)

def _populate_collision_tree_part_023_loop(_state, _frame):
    _frame.shape_index = str(_frame.shape_element.get('index') or '')
    _frame.shape_type = _frame.shape_element.get('shape_type') or 'hknpShape'
    _frame.editable_fields = _frame.shape_element.get('editable_fields') or ''
    _frame.shape_contexts = _frame.context_by_shape.get(_frame.shape_index, [])
    _frame.name_hint = _frame.shape_element.find('name_hint')
    _frame.name_summary = ''
    if _frame.name_hint is not None and _frame.name_hint.get('name'):
        _frame.name_summary = f" | name={_frame.name_hint.get('name')}"
    _frame.context_summary = ''
    if _frame.shape_contexts:
        _frame.first_context = _frame.shape_contexts[0]
        _frame.context_summary = f" | body={_frame.first_context.get('body_name') or 'unknown'}; socket={_frame.first_context.get('socket_name') or _frame.first_context.get('fixed_socket_name') or 'unknown'}; material={_frame.first_context.get('material_name') or 'unknown'}"
    _frame.shape_item = _state.QTreeWidgetItem((_frame.shape_index, _frame.shape_type, '', '', '', 'mixed', f'Editable fields: {_frame.editable_fields}{_frame.name_summary}{_frame.context_summary}'))
    _state.collision_tree.addTopLevelItem(_frame.shape_item)
    for _frame.vector_field in ('center', 'extent', 'bounds_min', 'bounds_max'):
        _frame.vector_element = _frame.shape_element.find(_frame.vector_field)
        if _frame.vector_element is None:
            continue
        _frame.values = [_frame.vector_element.get(component) or '' for component in ('x', 'y', 'z') if _frame.vector_element.get(component) not in (None, '')]
        if len(_frame.values) == 3:
            _state._add_collision_read_only_item(_frame.shape_item, shape_index=_frame.shape_index, field=_frame.vector_field, value=', '.join(_frame.values), confidence='strong inference', description='Decoded bounds/placement summary for browsing and preview selection.')
            _frame.read_only_row_count += 1
    if _frame.name_hint is not None and _frame.name_hint.get('name'):
        _frame.name_item = _state.QTreeWidgetItem((_frame.shape_index, 'name_hint', _frame.name_hint.get('name') or '', _frame.name_hint.get('source') or 'HavokShapeNameProperty', f"property_record={_frame.name_hint.get('property_record_index') or ''}; name_record={_frame.name_hint.get('name_record_index') or ''}".strip('; '), _frame.name_hint.get('confidence') or 'experimental', _frame.name_hint.findtext('description', default='Decoded in-HKX ragdoll/body shape label.')))
        _frame.shape_item.addChild(_frame.name_item)
        _frame.read_only_row_count += 1
    for _frame.context in _frame.shape_contexts:
        _frame.context_item = _state.QTreeWidgetItem((_frame.shape_index, 'body_context', _frame.context.get('body_name') or '', _frame.context.get('socket_name') or _frame.context.get('fixed_socket_name') or '', _frame.context.get('details') or _frame.context.get('material_name') or '', _frame.context.get('confidence') or 'experimental', _frame.context.get('description') or 'Descriptor body/socket/material context correlated with this decoded HKX shape.'))
        _frame.context_item.setToolTip(0, _frame.context.get('descriptor_path') or '')
        _frame.shape_item.addChild(_frame.context_item)
        _frame.read_only_row_count += 1
    _frame.mesh_summary = _frame.shape_element.find('mesh_summary')
    if _frame.mesh_summary is not None:
        _frame.mesh_bits = []
        for _frame.attr_name, _frame.label in (('sections', 'sections'), ('primitives', 'primitives'), ('aabb_nodes', 'AABB nodes'), ('shape_tags', 'shape tags'), ('data_bytes', 'data bytes')):
            _frame.value = _frame.mesh_summary.get(_frame.attr_name)
            if _frame.value not in (None, ''):
                _frame.mesh_bits.append(f'{_frame.label}={_frame.value}')
        _frame.mesh_item = _state.QTreeWidgetItem((_frame.shape_index, 'mesh_summary', '', '', '; '.join(_frame.mesh_bits), 'experimental', 'Read-only hknpMeshShape summary. Mesh topology is exported in XML but not editable yet.'))
        _frame.shape_item.addChild(_frame.mesh_item)
        _frame.read_only_row_count += 1
    _frame.mesh_details = _frame.shape_element.find('mesh_details')
    if _frame.mesh_details is not None:
        _frame.detail_bits = []
        for _frame.group_name, _frame.label in (('mesh_shape_records', 'shape records'), ('geometry_sections', 'sections'), ('primitive_buffers', 'primitive buffers'), ('aabb_tree_nodes', 'AABB records'), ('shape_tag_table', 'shape tag records'), ('mesh_byte_buffers', 'byte buffers')):
            _frame.group = _frame.mesh_details.find(_frame.group_name)
            if _frame.group is not None and _frame.group.get('record_count') is not None:
                _frame.detail_bits.append(f"{_frame.label}={_frame.group.get('record_count')}")
        _frame.detail_item = _state.QTreeWidgetItem((_frame.shape_index, 'mesh_details', '', 'guarded', '; '.join(_frame.detail_bits), 'strong inference', _frame.mesh_details.findtext('warning', default='Mesh-shape sub-records are available in XML / Raw. Primitive tuple winding edits are guarded.')))
        _frame.shape_item.addChild(_frame.detail_item)
        _frame.read_only_row_count += 1
        _frame.editability_element = _frame.mesh_details.find('editability')
        if _frame.editability_element is not None:
            for _frame.operation_element in _frame.editability_element.findall('supportedSafeOperation'):
                _frame.text = str(_frame.operation_element.text or '').strip()
                if _frame.text:
                    _state._add_collision_read_only_item(_frame.shape_item, shape_index=_frame.shape_index, field='mesh_safe_operation', value=_frame.text, confidence='strong inference', description='Supported guarded mesh edit. All other mesh topology edits remain blocked.')
                    _frame.read_only_row_count += 1
        for _frame.primitive_buffer_element in _frame.mesh_details.findall('./primitive_buffers/primitive_buffer'):
            _frame.primitive_record_index = _frame.primitive_buffer_element.get('record_index') or ''
            for _frame.primitive_element in _frame.primitive_buffer_element.findall('./primitive_words/primitive'):
                if _frame.editable_row_count >= _frame.max_rows:
                    _frame.truncated = True
                    break
                _frame.primitive_index = _frame.primitive_element.get('index') or ''
                _frame.byte_indices_element = _frame.primitive_element.find('byte_indices')
                if _frame.byte_indices_element is None:
                    continue
                _frame.values = [value for value in _state.re.split('[\\s,]+', str(_frame.byte_indices_element.text or '').strip()) if value]
                if len(_frame.values) != 4:
                    continue
                _state._add_collision_tuple_item(_frame.shape_item, shape_index=_frame.shape_index, field='mesh_primitive_tuple', row=f'record {_frame.primitive_record_index} / primitive {_frame.primitive_index}', value=' '.join(_frame.values), confidence='strong inference', description='Guarded hknpMeshShape primitive tuple. Reorder the same four byte values to flip winding; do not add/remove/change vertex indices.', key=('mesh_primitive_tuple', _frame.shape_index, _frame.primitive_record_index, _frame.primitive_index))
                _frame.editable_row_count += 1
            if _frame.truncated:
                break
    _frame.box_summary = _frame.shape_element.find('box_summary')
    if _frame.box_summary is not None:
        _frame.box_bits = []
        for _frame.attr_name, _frame.label in (('convex_radius_or_collision_margin', 'margin'), ('aabb_or_radius_factor', 'AABB factor')):
            _frame.value = _frame.box_summary.get(_frame.attr_name)
            if _frame.value not in (None, ''):
                _frame.box_bits.append(f'{_frame.label}={_frame.value}')
        _state._add_collision_read_only_item(_frame.shape_item, shape_index=_frame.shape_index, field='box_summary', value='; '.join(_frame.box_bits), confidence=_frame.box_summary.get('confidence') or 'experimental', description=_frame.box_summary.findtext('warning', default='Read-only hknpBoxShape local-frame/extent summary.'))
        _frame.read_only_row_count += 1
        for _frame.vector_field in ('center', 'half_extents', 'bounds_min', 'bounds_max'):
            _frame.vector_element = _frame.box_summary.find(_frame.vector_field)
            if _frame.vector_element is None:
                continue
            _frame.values = [_frame.vector_element.get(component) or '' for component in ('x', 'y', 'z') if _frame.vector_element.get(component) not in (None, '')]
            if len(_frame.values) == 3:
                _state._add_collision_read_only_item(_frame.shape_item, shape_index=_frame.shape_index, field=f'box_{_frame.vector_field}', value=', '.join(_frame.values), confidence=_frame.box_summary.get('confidence') or 'experimental', description='Read-only hknpBoxShape decoded vector summary.')
                _frame.read_only_row_count += 1
    _frame.sphere_radius = _frame.shape_element.find('sphere_radius')

def _populate_collision_tree_part_024_loop(_state, _frame):
    if _frame.sphere_radius is not None and _frame.sphere_radius.get('value') is not None:
        _state._add_collision_value_item(_frame.shape_item, shape_index=_frame.shape_index, field='sphere_radius', row='0', component='value', value=_frame.sphere_radius.get('value') or '', confidence='strong inference', description='Sphere collision radius. Must remain positive.', key=('sphere_radius', _frame.shape_index, 'value'))
        _frame.editable_row_count += 1
    _frame.capsule_radius = _frame.shape_element.find('capsule_radius')
    if _frame.capsule_radius is not None and _frame.capsule_radius.get('value') is not None:
        _state._add_collision_value_item(_frame.shape_item, shape_index=_frame.shape_index, field='capsule_radius', row='0', component='value', value=_frame.capsule_radius.get('value') or '', confidence='strong inference', description='Capsule collision radius. Must remain positive.', key=('capsule_radius', _frame.shape_index, 'value'))
        _frame.editable_row_count += 1
    for _frame.vector_field, _frame.element_name, _frame.components, _frame.confidence, _frame.description in (('vertices', 'v', ('x', 'y', 'z'), 'strong inference', 'Local-space collision vertex component.'), ('planes', 'plane', ('normal_x', 'normal_y', 'normal_z', 'distance'), 'strong inference', 'Collision plane component.'), ('capsule_endpoints', 'point', ('x', 'y', 'z'), 'strong inference', 'Local-space capsule endpoint component.')):
        for _frame.row_element in _frame.shape_element.findall(f'./{_frame.vector_field}/{_frame.element_name}'):
            _frame.row_index = _frame.row_element.get('index') or ''
            for _frame.component in _frame.components:
                if _frame.editable_row_count >= _frame.max_rows:
                    _frame.truncated = True
                    break
                if _frame.row_element.get(_frame.component) is None:
                    continue
                _state._add_collision_value_item(_frame.shape_item, shape_index=_frame.shape_index, field=_frame.vector_field, row=_frame.row_index, component=_frame.component, value=_frame.row_element.get(_frame.component) or '', confidence=_frame.confidence, description=_frame.description, key=('shape_vector', _frame.shape_index, _frame.vector_field, _frame.element_name, _frame.row_index, _frame.component))
                _frame.editable_row_count += 1
            if _frame.truncated:
                break
        if _frame.truncated:
            break
    for _frame.row_element in _frame.shape_element.findall('./mass_properties/row'):
        _frame.row_index = _frame.row_element.get('index') or ''
        for _frame.component in ('x', 'y', 'z', 'w'):
            if _frame.editable_row_count >= _frame.max_rows:
                _frame.truncated = True
                break
            if _frame.row_element.get(_frame.component) is None:
                continue
            _state._add_collision_value_item(_frame.shape_item, shape_index=_frame.shape_index, field='mass_properties', row=_frame.row_index, component=_frame.component, value=_frame.row_element.get(_frame.component) or '', confidence='experimental', description='Mass-property float component. Exact Havok field name is unconfirmed.', key=('mass_properties', _frame.shape_index, _frame.row_index, _frame.component))
            _frame.editable_row_count += 1
        if _frame.truncated:
            break
    for _frame.slot_element in _frame.shape_element.findall('./shape_payload/float'):
        if _frame.editable_row_count >= _frame.max_rows:
            _frame.truncated = True
            break
        _frame.offset = _frame.slot_element.get('offset') or ''
        _state._add_collision_value_item(_frame.shape_item, shape_index=_frame.shape_index, field='shape_payload', row=_frame.offset, component=_frame.slot_element.get('hex_offset') or _frame.offset, value=_frame.slot_element.get('value') or '', confidence='experimental', description=_frame.slot_element.get('description') or 'Fixed-offset hknp shape float slot.', key=('shape_payload', _frame.shape_index, _frame.offset, 'value'))
        _frame.editable_row_count += 1
    for _frame.face_element in _frame.shape_element.findall('./hull_topology/face_records/face'):
        _frame.face_index = _frame.face_element.get('index') or ''
        for _frame.component in ('index_start', 'vertex_count', 'meta'):
            if _frame.editable_row_count >= _frame.max_rows:
                _frame.truncated = True
                break
            if _frame.face_element.get(_frame.component) is None:
                continue
            _state._add_collision_value_item(_frame.shape_item, shape_index=_frame.shape_index, field='hull_face_records', row=_frame.face_index, component=_frame.component, value=_frame.face_element.get(_frame.component) or '', confidence='strong inference', description='Convex hull face record integer. Counts and row order must stay unchanged.', key=('hull_face_record', _frame.shape_index, _frame.face_index, _frame.component))
            _frame.editable_row_count += 1
        if _frame.truncated:
            break
    _frame.face_indices_element = _frame.shape_element.find('./hull_topology/face_indices')
    if _frame.face_indices_element is not None and (not _frame.truncated):
        _frame.face_indices = [value for value in _state.re.split('[\\s,]+', str(_frame.face_indices_element.text or '').strip()) if value]
        for _frame.value_index, _frame.value in enumerate(_frame.face_indices):
            if _frame.editable_row_count >= _frame.max_rows:
                _frame.truncated = True
                break
            _state._add_collision_value_item(_frame.shape_item, shape_index=_frame.shape_index, field='hull_face_indices', row=str(_frame.value_index), component='vertex_index', value=_frame.value, confidence='strong inference', description='Face vertex index byte. Must keep the same value count and reference existing vertices.', key=('hull_face_index', _frame.shape_index, str(_frame.value_index)))
            _frame.editable_row_count += 1
    for _frame.table_position, _frame.table_element in enumerate(_frame.shape_element.findall('./hull_topology/edge_tables/edge_table')):
        if _frame.truncated:
            break
        _frame.record_index = _frame.table_element.get('record_index') or str(_frame.table_position)
        for _frame.pair_element in _frame.table_element.findall('pair'):
            _frame.pair_index = _frame.pair_element.get('index') or ''
            for _frame.component in ('a', 'b'):
                if _frame.editable_row_count >= _frame.max_rows:
                    _frame.truncated = True
                    break
                if _frame.pair_element.get(_frame.component) is None:
                    continue
                _state._add_collision_value_item(_frame.shape_item, shape_index=_frame.shape_index, field='hull_edge_pairs', row=f'{_frame.record_index}:{_frame.pair_index}', component=_frame.component, value=_frame.pair_element.get(_frame.component) or '', confidence='experimental', description='Convex hull edge/support pair integer. Exact hknp meaning remains inferred.', key=('hull_edge_pair', _frame.shape_index, _frame.record_index, _frame.pair_index, _frame.component))
                _frame.editable_row_count += 1
            if _frame.truncated:
                break
    _frame.shape_item.setExpanded(False)

def _populate_collision_tree_part_025(_state, _frame):
    _state._style_hkx_tree_values(_state.collision_tree, value_columns=(0, 2, 3, 4), confidence_column=5, guidance_columns=(4,), patchable_value_column=4)
    for _frame.column in range(_state.collision_tree.columnCount()):
        _state.collision_tree.resizeColumnToContents(_frame.column)
    _frame.suffix = f'{len(_frame.shape_elements)} / {_frame.editable_row_count}+{_frame.read_only_row_count}'
    if _frame.truncated:
        _frame.suffix += ' truncated'
    _state._set_hkx_editor_section_title(2, f'Collision Shapes ({_frame.suffix})')
    _state.collision_status_label.setText(f'{_frame.editable_row_count:,} editable and {_frame.read_only_row_count:,} read-only collision row(s) across {len(_frame.shape_elements):,} shape(s).')
    _state._apply_collision_filter()

def _dialog_step_0132(_state):
    def _populate_collision_tree() -> None:
        _frame = SimpleNamespace()
        _populate_collision_tree_part_019(_state, _frame)
        if _frame.root is None:
            return
        _populate_collision_tree_part_020(_state, _frame)
        try:
            _populate_collision_tree_part_021(_state, _frame)
            if not _frame.shape_elements:
                _frame.placeholder = _state.QTreeWidgetItem(('No decoded collision shapes found.', '', '', '', '', '', ''))
                _state.collision_tree.addTopLevelItem(_frame.placeholder)
                _state._set_hkx_editor_section_title(2, 'Collision Shapes')
                _state.collision_status_label.setText('No decoded collision shapes found.')
                return
            _populate_collision_tree_part_022(_state, _frame)
            for _frame.shape_element in _frame.shape_elements:
                _populate_collision_tree_part_023_loop(_state, _frame)
                _populate_collision_tree_part_024_loop(_state, _frame)
                if _frame.truncated:
                    _frame.note = _state.QTreeWidgetItem((_frame.shape_index, 'truncated', '', '', '', 'raw', 'Collision editor row limit reached; use XML / Raw for remaining values.'))
                    _frame.shape_item.addChild(_frame.note)
                    break
            _populate_collision_tree_part_025(_state, _frame)
        finally:
            _state.syncing_collision_tree['active'] = False
    _state._populate_collision_tree = _populate_collision_tree

def _dialog_step_0133(_state):
    def _collision_item_matches_filter(item: QTreeWidgetItem, needle: str) -> bool:
        if not needle:
            return True
        row_text = " ".join(item.text(column) for column in range(_state.collision_tree.columnCount())).casefold()
        return _state._row_matches_filter_terms(row_text, needle)
    _state._collision_item_matches_filter = _collision_item_matches_filter

def _dialog_step_0134(_state):
    def _apply_collision_filter() -> None:
        needle = _state.collision_filter_edit.text().strip().casefold()
        visible_shapes = 0
        visible_rows = 0
        for shape_index in range(_state.collision_tree.topLevelItemCount()):
            shape_item = _state.collision_tree.topLevelItem(shape_index)
            shape_matches = _state._collision_item_matches_filter(shape_item, needle)
            child_visible = 0
            for child_index in range(shape_item.childCount()):
                child_item = shape_item.child(child_index)
                child_matches = _state._collision_item_matches_filter(child_item, needle)
                child_item.setHidden(bool(needle and not child_matches and not shape_matches))
                if not child_item.isHidden():
                    child_visible += 1
                    visible_rows += 1
            shape_item.setHidden(bool(needle and not shape_matches and child_visible == 0))
            if not shape_item.isHidden():
                visible_shapes += 1
                if needle:
                    shape_item.setExpanded(True)
        if needle:
            _state.collision_status_label.setText(f"Filter: {visible_shapes:,} shape(s), {visible_rows:,} visible row(s).")
    _state._apply_collision_filter = _apply_collision_filter

def _handle_collision_item_changed_part_026(_state, _frame):
    _frame.key = _frame.item.data(4, _state.Qt.ItemDataRole.UserRole)

def _handle_collision_item_changed_part_027(_state, _frame):
    _frame.raw_value = _frame.item.text(4).strip()
    _frame.kind = str(_frame.key[0])

def _handle_collision_item_changed_part_028(_state, _frame):
    _frame.integer_kinds = {'hull_face_record', 'hull_face_index', 'hull_edge_pair'}

def _handle_collision_item_changed_part_029(_state, _frame):
    _frame.root = _state._load_xml_root_from_editor()

def _handle_collision_item_changed_part_030(_state, _frame):
    _frame.target: Optional[ET.Element] = None
    _frame.attr_name = ''
    _frame.shape_index = str(_frame.key[1]) if len(_frame.key) > 1 else ''
    _frame.shape_element = _state._collision_shape_by_index(_frame.root, _frame.shape_index)

def _handle_collision_item_changed_part_031(_state, _frame):
    if _frame.kind == 'sphere_radius':
        _frame.target = _frame.shape_element.find('sphere_radius')
        _frame.attr_name = str(_frame.key[2])
    elif _frame.kind == 'capsule_radius':
        _frame.target = _frame.shape_element.find('capsule_radius')
        _frame.attr_name = str(_frame.key[2])
    elif _frame.kind == 'shape_vector' and len(_frame.key) == 6:
        _frame._kind, _frame._shape_index, _frame.vector_field, _frame.element_name, _frame.row_index, _frame.component = _frame.key
        for _frame.candidate in _frame.shape_element.findall(f'./{_frame.vector_field}/{_frame.element_name}'):
            if str(_frame.candidate.get('index') or '') == str(_frame.row_index):
                _frame.target = _frame.candidate
                _frame.attr_name = str(_frame.component)
                break
    elif _frame.kind == 'mass_properties' and len(_frame.key) == 4:
        _frame._kind, _frame._shape_index, _frame.row_index, _frame.component = _frame.key
        for _frame.candidate in _frame.shape_element.findall('./mass_properties/row'):
            if str(_frame.candidate.get('index') or '') == str(_frame.row_index):
                _frame.target = _frame.candidate
                _frame.attr_name = str(_frame.component)
                break
    elif _frame.kind == 'shape_payload' and len(_frame.key) == 4:
        _frame._kind, _frame._shape_index, _frame.offset, _frame.component = _frame.key
        for _frame.candidate in _frame.shape_element.findall('./shape_payload/float'):
            if str(_frame.candidate.get('offset') or '') == str(_frame.offset):
                _frame.target = _frame.candidate
                _frame.attr_name = str(_frame.component)
                break
    elif _frame.kind == 'hull_face_record' and len(_frame.key) == 4:
        _frame._kind, _frame._shape_index, _frame.face_index, _frame.component = _frame.key
        for _frame.candidate in _frame.shape_element.findall('./hull_topology/face_records/face'):
            if str(_frame.candidate.get('index') or '') == str(_frame.face_index):
                _frame.target = _frame.candidate
                _frame.attr_name = str(_frame.component)
                break
    elif _frame.kind == 'hull_face_index' and len(_frame.key) == 3:
        _frame._kind, _frame._shape_index, _frame.value_index = _frame.key
        _frame.target = _frame.shape_element.find('./hull_topology/face_indices')
        if _frame.target is not None:
            _frame.values = [value for value in _state.re.split('[\\s,]+', str(_frame.target.text or '').strip()) if value]
            try:
                _frame.index = int(str(_frame.value_index), 0)
            except ValueError:
                _frame.index = -1
            if 0 <= _frame.index < len(_frame.values):
                _frame.values[_frame.index] = str(int(_frame.raw_value, 0))
                _frame.target.text = ' '.join(_frame.values)
                _frame.attr_name = '__text__'
    elif _frame.kind == 'hull_edge_pair' and len(_frame.key) == 5:
        _frame._kind, _frame._shape_index, _frame.record_index, _frame.pair_index, _frame.component = _frame.key
        for _frame.table_element in _frame.shape_element.findall('./hull_topology/edge_tables/edge_table'):
            if str(_frame.table_element.get('record_index') or '') != str(_frame.record_index):
                continue
            for _frame.candidate in _frame.table_element.findall('pair'):
                if str(_frame.candidate.get('index') or '') == str(_frame.pair_index):
                    _frame.target = _frame.candidate
                    _frame.attr_name = str(_frame.component)
                    break
            if _frame.target is not None:
                break

def _handle_collision_item_changed_part_032(_state, _frame):
    if _frame.attr_name != '__text__':
        _frame.target.set(_frame.attr_name, str(int(_frame.raw_value, 0)) if _frame.kind in _frame.integer_kinds else _frame.raw_value)
    _frame.original_value = str(_frame.item.data(4, _state.ORIGINAL_VALUE_ROLE) or '')
    _state._record_dirty_value('collision', _frame.key, f'{_frame.item.text(0)} {_frame.item.text(1)} {_frame.item.text(2)} {_frame.item.text(3)}', _frame.original_value, _frame.raw_value)
    _frame.cursor = _state.editor.textCursor()
    _state.editor.blockSignals(True)
    _state.editor.setPlainText(_state._format_xml_from_root(_frame.root))
    _state.editor.blockSignals(False)
    _state.editor.setTextCursor(_frame.cursor)
    _state._populate_overview(_frame.root)
    _state._populate_hkx_browser_tree(_frame.root)
    _state._populate_body_summary_tree()
    _state._populate_constraint_summary_tree()
    _state._populate_editable_catalog_tree()
    _state._populate_byte_map_tree()
    _state._populate_connected_physics_tree()
    _state._populate_decoder_evidence_tree()
    _state._update_line_numbers()
    _state._update_cursor_status()
    _state._refresh_dirty_status()
    _state._sync_hkx_edited_overlay_targets(refreshed_root)

def _dialog_step_0135(_state):
    def _handle_collision_item_changed(item: QTreeWidgetItem, column: int) -> None:
        _frame = SimpleNamespace(item=item, column=column)
        if _state.syncing_collision_tree['active'] or _frame.column != 4 or _frame.item.parent() is None:
            return
        _handle_collision_item_changed_part_026(_state, _frame)
        if not isinstance(_frame.key, tuple) or not _frame.key:
            return
        _handle_collision_item_changed_part_027(_state, _frame)
        if _frame.kind == 'mesh_primitive_tuple':
            _frame.values = [value for value in _state.re.split('[\\s,]+', _frame.raw_value) if value]
            if len(_frame.values) != 4:
                _state.QMessageBox.warning(_state.dialog, 'HKX Collision Value', 'Mesh primitive tuple must contain exactly four byte values.')
                _state._populate_collision_tree()
                return
            try:
                _frame.parsed_values = [int(value, 0) for value in _frame.values]
            except ValueError:
                _state.QMessageBox.warning(_state.dialog, 'HKX Collision Value', 'Mesh primitive tuple values must be integers.')
                _state._populate_collision_tree()
                return
            if any((value < 0 or value > 255 for value in _frame.parsed_values)):
                _state.QMessageBox.warning(_state.dialog, 'HKX Collision Value', 'Mesh primitive tuple values must be between 0 and 255.')
                _state._populate_collision_tree()
                return
            _frame.original_values = [value for value in _state.re.split('[\\s,]+', str(_frame.item.data(4, _state.ORIGINAL_VALUE_ROLE) or '').strip()) if value]
            try:
                _frame.original_parsed = [int(value, 0) for value in _frame.original_values]
            except ValueError:
                _frame.original_parsed = []
            if sorted((value for value in _frame.parsed_values if value != 255)) != sorted((value for value in _frame.original_parsed if value != 255)) or _frame.parsed_values.count(255) != _frame.original_parsed.count(255):
                _state.QMessageBox.warning(_state.dialog, 'HKX Collision Value', 'Only winding/order edits are supported: keep the exact same tuple values and only reorder them.')
                _state._populate_collision_tree()
                return
            _frame.root = _state._load_xml_root_from_editor()
            if _frame.root is None:
                return
            _frame.shape_index = str(_frame.key[1]) if len(_frame.key) > 1 else ''
            _frame.primitive_record_index = str(_frame.key[2]) if len(_frame.key) > 2 else ''
            _frame.primitive_index = str(_frame.key[3]) if len(_frame.key) > 3 else ''
            _frame.shape_element = _state._collision_shape_by_index(_frame.root, _frame.shape_index)
            _frame.target = None
            if _frame.shape_element is not None:
                for _frame.primitive_buffer_element in _frame.shape_element.findall('./mesh_details/primitive_buffers/primitive_buffer'):
                    if str(_frame.primitive_buffer_element.get('record_index') or '') != _frame.primitive_record_index:
                        continue
                    for _frame.primitive_element in _frame.primitive_buffer_element.findall('./primitive_words/primitive'):
                        if str(_frame.primitive_element.get('index') or '') == _frame.primitive_index:
                            _frame.target = _frame.primitive_element.find('byte_indices')
                            break
                    if _frame.target is not None:
                        break
            if _frame.target is None:
                _state.QMessageBox.warning(_state.dialog, 'HKX Collision Value', 'Could not find the matching mesh primitive tuple in XML.')
                _state._populate_collision_tree()
                return
            _frame.normalized_value = ' '.join((str(value) for value in _frame.parsed_values))
            _frame.target.text = _frame.normalized_value
            _frame.original_value = str(_frame.item.data(4, _state.ORIGINAL_VALUE_ROLE) or '')
            _state._record_dirty_value('collision', _frame.key, f'{_frame.item.text(0)} {_frame.item.text(1)} {_frame.item.text(2)}', _frame.original_value, _frame.normalized_value)
            _frame.cursor = _state.editor.textCursor()
            _state.editor.blockSignals(True)
            _state.editor.setPlainText(_state._format_xml_from_root(_frame.root))
            _state.editor.blockSignals(False)
            _state.editor.setTextCursor(_frame.cursor)
            _state._populate_overview(_frame.root)
            _state._populate_hkx_browser_tree(_frame.root)
            _state._populate_body_summary_tree()
            _state._populate_constraint_summary_tree()
            _state._populate_editable_catalog_tree()
            _state._populate_byte_map_tree()
            _state._populate_connected_physics_tree()
            _state._populate_decoder_evidence_tree()
            _state._update_line_numbers()
            _state._update_cursor_status()
            _state._refresh_dirty_status()
            return
        _handle_collision_item_changed_part_028(_state, _frame)
        if isinstance(_frame.key, tuple) and str(_frame.key[0]) in _frame.integer_kinds:
            try:
                int(_frame.raw_value, 0)
            except ValueError:
                _state.QMessageBox.warning(_state.dialog, 'HKX Collision Value', 'Value must be an integer.')
                _state._populate_collision_tree()
                return
        else:
            try:
                float(_frame.raw_value)
            except ValueError:
                _state.QMessageBox.warning(_state.dialog, 'HKX Collision Value', 'Value must be numeric.')
                _state._populate_collision_tree()
                return
        _handle_collision_item_changed_part_029(_state, _frame)
        if _frame.root is None:
            return
        _handle_collision_item_changed_part_030(_state, _frame)
        if _frame.shape_element is None:
            _state.QMessageBox.warning(_state.dialog, 'HKX Collision Value', 'Could not find the matching shape.')
            _state._populate_collision_tree()
            return
        _handle_collision_item_changed_part_031(_state, _frame)
        if _frame.target is None or not _frame.attr_name:
            _state.QMessageBox.warning(_state.dialog, 'HKX Collision Value', 'Could not find the matching XML collision value.')
            _state._populate_collision_tree()
            return
        _handle_collision_item_changed_part_032(_state, _frame)
    _state._handle_collision_item_changed = _handle_collision_item_changed

def _dialog_step_0136(_state):
    def _handle_tuning_item_changed(item: QTreeWidgetItem, column: int) -> None:
        if _state.syncing_tree["active"]:
            return
        if column != 5 or item.parent() is None:
            return
        key = item.data(5, _state.Qt.ItemDataRole.UserRole)
        if not isinstance(key, tuple) or len(key) != 3:
            return
        record_index, item_index, offset = (str(key[0]), str(key[1]), str(key[2]))
        raw_value = item.text(5).strip()
        try:
            parsed_value = float(raw_value)
        except ValueError:
            _state.QMessageBox.warning(_state.dialog, "HKX Tuning Value", "Value must be numeric.")
            _state._populate_tuning_tree()
            return
        if not _state.math.isfinite(parsed_value):
            _state.QMessageBox.warning(_state.dialog, "HKX Tuning Value", "Value must be a finite number.")
            _state._populate_tuning_tree()
            return
        root = _state._load_xml_root_from_editor()
        if root is None:
            return
        target = None
        for group_element in root.findall("./physicsTuning/groups/group"):
            if str(group_element.get("record_index") or "") != record_index:
                continue
            for slot_element in group_element.findall("./slots/slot"):
                if (
                    str(slot_element.get("item_index") or "") == item_index
                    and str(slot_element.get("offset") or "") == offset
                ):
                    target = slot_element
                    break
            if target is not None:
                break
        if target is None:
            _state.QMessageBox.warning(_state.dialog, "HKX Tuning Value", "Could not find the matching XML tuning slot.")
            _state._populate_tuning_tree()
            return
        target.set("value", raw_value)
        for field_element in root.findall("./editableFieldCatalog/fields/field"):
            if (
                str(field_element.get("record_index") or "") == record_index
                and str(field_element.get("item_index") or "") == item_index
                and str(field_element.get("offset") or "") == offset
            ):
                field_element.set("value_summary", raw_value)
        original_value = str(item.data(5, _state.ORIGINAL_VALUE_ROLE) or "")
        _state._record_dirty_value("tuning", key, f"record {record_index} {item.text(4)}", original_value, raw_value)
        cursor = _state.editor.textCursor()
        _state.editor.blockSignals(True)
        _state.editor.setPlainText(_state._format_xml_from_root(root))
        _state.editor.blockSignals(False)
        _state.editor.setTextCursor(cursor)
        _state._populate_overview(root)
        _state._populate_hkx_browser_tree(root)
        _state._populate_constraint_summary_tree()
        _state._populate_editable_catalog_tree()
        _state._populate_byte_map_tree()
        _state._populate_connected_physics_tree()
        _state._populate_decoder_evidence_tree()
        _state._update_line_numbers()
        _state._update_cursor_status()
        _state._refresh_dirty_status()
    _state._handle_tuning_item_changed = _handle_tuning_item_changed

def _dialog_step_0137(_state):
    def _prompt_hkx_numeric_value(title: str, label: str, current_text: str, guidance: object = None) -> Optional[str]:
        prompt_lines = [
            label,
        ]
        if isinstance(guidance, _state.Mapping):
            effect = str(guidance.get("plain_language_effect") or "").strip()
            if_increased = str(guidance.get("if_increased") or "").strip()
            if_decreased = str(guidance.get("if_decreased") or "").strip()
            safe_hint = str(guidance.get("safe_edit_hint") or "").strip()
            edit_risk = str(guidance.get("edit_risk") or "").strip()
            value_constraints = str(guidance.get("value_constraints") or "").strip()
            suggested_edit_step = str(guidance.get("suggested_edit_step") or "").strip()
            if effect:
                prompt_lines.append(f"Plain-language effect: {effect}")
            if if_increased:
                prompt_lines.append(f"If increased: {if_increased}")
            if if_decreased:
                prompt_lines.append(f"If decreased: {if_decreased}")
            if safe_hint:
                prompt_lines.append(f"Safe edit: {safe_hint}")
            if edit_risk:
                prompt_lines.append(f"Edit risk: {edit_risk}")
            if value_constraints:
                prompt_lines.append(f"Value constraints: {value_constraints}")
            if suggested_edit_step:
                prompt_lines.append(f"Edit note: {suggested_edit_step}")
        try:
            current_value = float(str(current_text).strip())
        except ValueError:
            current_value = 0.0
        editor_dialog = _state.QDialog(_state.dialog)
        editor_dialog.setWindowTitle(title)
        editor_dialog.resize(520, 280)
        editor_layout = _state.QVBoxLayout(editor_dialog)
        explanation = _state.QLabel("\n".join(prompt_lines))
        explanation.setWordWrap(True)
        editor_layout.addWidget(explanation)
        spin = _state.QDoubleSpinBox()
        spin.setDecimals(8)
        spin.setRange(-1_000_000_000.0, 1_000_000_000.0)
        spin.setSingleStep(0.01)
        spin.setValue(current_value)
        spin.selectAll()
        editor_layout.addWidget(spin)
        button_row = _state.QHBoxLayout()
        ok_button = _state.QPushButton("Apply")
        cancel_button = _state.QPushButton("Cancel")
        button_row.addStretch(1)
        button_row.addWidget(ok_button)
        button_row.addWidget(cancel_button)
        editor_layout.addLayout(button_row)
        ok_button.clicked.connect(editor_dialog.accept)
        cancel_button.clicked.connect(editor_dialog.reject)
        if editor_dialog.exec() != _state.QDialog.DialogCode.Accepted:
            return None
        value = spin.value()
        if not _state.math.isfinite(value):
            _state.QMessageBox.warning(_state.dialog, title, "Value must be a finite number.")
            return None
        return f"{value:.8g}"
    _state._prompt_hkx_numeric_value = _prompt_hkx_numeric_value

def _dialog_step_0138(_state):
    def _confirm_hkx_edit_risk(guidance: object, *, title: str) -> bool:
        if not isinstance(guidance, _state.Mapping):
            return True
        confidence = str(guidance.get("confidence") or "").strip().lower()
        edit_risk = str(guidance.get("edit_risk") or "").strip().lower()
        if edit_risk not in {"high", "experimental"} and confidence not in {"experimental", "raw", "raw_preserved"}:
            return True
        answer = _state.QMessageBox.question(
            _state.dialog,
            title,
            (
                "This value is not confirmed safe.\n\n"
                f"Confidence: {confidence or 'unknown'}\n"
                f"Edit risk: {edit_risk or 'unknown'}\n\n"
                "Apply this edit anyway?"
            ),
        )
        return answer == _state.QMessageBox.StandardButton.Yes
    _state._confirm_hkx_edit_risk = _confirm_hkx_edit_risk

def _dialog_step_0139(_state):
    def _edit_selected_tuning_value() -> None:
        item = _state.tuning_tree.currentItem()
        if item is None or item.parent() is None:
            _state.QMessageBox.information(_state.dialog, "HKX Tuning Value", "Select a patchable value row first.")
            return
        key = item.data(5, _state.Qt.ItemDataRole.UserRole)
        if not isinstance(key, tuple) or len(key) != 3:
            _state.QMessageBox.information(
                _state.dialog,
                "HKX Tuning Value",
                (
                    "This row is read-only context. Descriptor-context values explain nearby XML hints, "
                    "but they are not imported into the HKX. Select a row with an Item and Offset to patch the HKX."
                ),
            )
            return
        guidance = item.data(7, _state.Qt.ItemDataRole.UserRole)
        value = _state._prompt_hkx_numeric_value(
            "Edit HKX Tuning Value",
            f"{item.text(4)}\nRecord {item.text(1)}, item {item.text(2)}, offset {item.text(3)}",
            item.text(5),
            guidance,
        )
        if value is None:
            return
        if not _state._confirm_hkx_edit_risk(guidance, title="Edit HKX Tuning Value"):
            return
        _state.tuning_tree.setCurrentItem(item, 5)
        item.setText(5, value)
    _state._edit_selected_tuning_value = _edit_selected_tuning_value

def _dialog_step_0140(_state):
    def _edit_selected_collision_value() -> None:
        item = _state.collision_tree.currentItem()
        if item is None or item.parent() is None:
            _state.QMessageBox.information(_state.dialog, "HKX Collision Value", "Select a patchable collision value row first.")
            return
        key = item.data(4, _state.Qt.ItemDataRole.UserRole)
        if not isinstance(key, tuple) or not key:
            _state.QMessageBox.information(_state.dialog, "HKX Collision Value", "This collision row is read-only context.")
            return
        kind = str(key[0])
        if kind in {"hull_face_record", "hull_face_index", "hull_edge_pair"}:
            value, accepted = _state.QInputDialog.getText(
                _state.dialog,
                "Edit HKX Integer Value",
                f"{item.text(1)} {item.text(2)} {item.text(3)}\nInteger value; counts and row order must stay unchanged.",
                text=item.text(4),
            )
            if not accepted:
                return
            value = value.strip()
            try:
                int(value, 0)
            except ValueError:
                _state.QMessageBox.warning(_state.dialog, "HKX Collision Value", "Value must be an integer.")
                return
        else:
            value = _state._prompt_hkx_numeric_value(
                "Edit HKX Collision Value",
                f"{item.text(1)} {item.text(2)} {item.text(3)}\n{item.text(6)}",
                item.text(4),
            )
            if value is None:
                return
        _state.collision_tree.setCurrentItem(item, 4)
        item.setText(4, value)
    _state._edit_selected_collision_value = _edit_selected_collision_value

def _dialog_step_0141(_state):
    def _edit_tuning_value_from_cell(item: QTreeWidgetItem, column: int) -> None:
        if column != 5:
            return
        key = item.data(5, _state.Qt.ItemDataRole.UserRole)
        if isinstance(key, tuple) and len(key) == 3:
            _state.tuning_tree.setCurrentItem(item, 5)
            _state._edit_selected_tuning_value()
        elif item.parent() is not None:
            _state.QMessageBox.information(
                _state.dialog,
                "HKX Tuning Value",
                "This is a read-only descriptor-context hint. Use a patchable row with an Item and Offset.",
            )
    _state._edit_tuning_value_from_cell = _edit_tuning_value_from_cell

def _dialog_step_0142(_state):
    def _find_next() -> None:
        pattern = _state.search_edit.text()
        if not pattern:
            return
        if _state.editor.find(pattern):
            return
        cursor = _state.editor.textCursor()
        cursor.movePosition(_state.QTextCursor.MoveOperation.Start)
        _state.editor.setTextCursor(cursor)
        _state.editor.find(pattern)
    _state._find_next = _find_next

STEPS = (_dialog_step_0132, _dialog_step_0133, _dialog_step_0134, _dialog_step_0135, _dialog_step_0136, _dialog_step_0137, _dialog_step_0138, _dialog_step_0139, _dialog_step_0140, _dialog_step_0141, _dialog_step_0142,)
