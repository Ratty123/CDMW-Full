"""Complete-field codecs for item.behavior, preserving all unassigned bytes."""
import struct

from cdmw.core.item_layout import read_item_layout, replace_layout_fields
from cdmw.core.new_item_record import Cursor, RecordError, text_bytes
from cdmw.domain.new_item.item_behavior import BEHAVIOR_FIELDS, INSPECTION, DOCKING, ItemBehaviorSettings, encode_behavior_settings, validate_value


FORMATS = {'u8': 'B', 'u16': 'H', 'u32': 'I', 'u64': 'Q', 'i64': 'q', 'f32': 'f'}


def read_value(cursor, shape, *, generation='current', owner=''):
    if isinstance(shape, str):
        if shape == 'texture':
            return cursor.unpack('I') if generation == 'compact' else cursor.text()
        if shape in FORMATS: return cursor.unpack(FORMATS[shape])
        if shape == 'text': return cursor.text()
        if shape == 'bool':
            value = cursor.unpack('B')
            if value not in (0, 1): raise RecordError('Unsupported item behavior flag.')
            return bool(value)
        if shape == 'subitem':
            tag = cursor.unpack('B')
            value = {'type': tag, 'value': cursor.unpack('I') if tag in (0, 3, 9) else None}
            validate_value(shape, value)
            return value
    kind = shape[0]
    if kind == 'optional':
        present = read_value(cursor, 'bool')
        return read_value(cursor, shape[1], generation=generation, owner=owner) if present else None
    if kind == 'record':
        result = {}
        for name,child in shape[1]:
            if generation == 'compact' and shape == DOCKING and name == 'sync_break_parent':
                result['owner_condition'] = cursor.unpack('I')
            result[name] = (0 if generation == 'legacy' and owner == 'inspect_action' and name == 'catch_tag_hash'
                           else read_value(cursor, child, generation=generation, owner=owner))
        if generation == 'compact' and shape == INSPECTION:
            result.update(extract_distance_bits=cursor.unpack('I'),extract_angle_bits=cursor.unpack('I'))
        if generation == 'compact' and shape == DOCKING:
            result['use_cooldown'] = read_value(cursor,'bool')
        return result
    count = shape[2] if kind == 'array' else cursor.count(shape[2])
    return [read_value(cursor, shape[1], generation=generation, owner=owner) for _ in range(count)]


def write_value(shape, value, *, generation='current', owner=''):
    validate_value(shape, value)
    if isinstance(shape, str):
        if shape == 'texture':
            if generation == 'compact':
                from cdmw.core.stringinfo_table import stringinfo_key, UNSET_TEXTURE_KEY
                return struct.pack('<I',value if type(value) is int else stringinfo_key(value) if value else UNSET_TEXTURE_KEY)
            if not isinstance(value,str):
                raise RecordError('This source generation stores a texture name, not a hash.')
            return text_bytes(value)
        if shape in FORMATS: return struct.pack('<'+FORMATS[shape], value)
        if shape == 'bool': return bytes([int(value)])
        if shape == 'text': return text_bytes(value)
        if shape == 'subitem':
            return bytes([value['type']]) + (struct.pack('<I', value['value']) if value['type'] in (0, 3, 9) else b'')
    kind = shape[0]
    if kind == 'optional':
        return b'\0' if value is None else b'\1'+write_value(shape[1], value, generation=generation, owner=owner)
    if kind == 'record':
        if generation == 'legacy' and owner == 'inspect_action' and value['catch_tag_hash'] != 0:
            raise RecordError('This source generation has no inspect catch-tag hash.')
        result = b''
        for name,child in shape[1]:
            if generation == 'legacy' and owner == 'inspect_action' and name == 'catch_tag_hash': continue
            if generation == 'compact' and shape == DOCKING and name == 'sync_break_parent':
                result += struct.pack('<I',value.get('owner_condition',0))
            result += write_value(child,value[name],generation=generation,owner=owner)
        if generation == 'compact' and shape == INSPECTION:
            result += struct.pack('<II',value.get('extract_distance_bits',0),value.get('extract_angle_bits',0))
        if generation == 'compact' and shape == DOCKING:
            result += bytes([int(value.get('use_cooldown',False))])
        return result
    prefix = b'' if kind == 'array' else struct.pack('<I', len(value))
    return prefix+b''.join(write_value(shape[1], child, generation=generation, owner=owner) for child in value)


def read_behavior_fields(raw):
    layout = read_item_layout(raw)
    result = {}
    for name, (field, shape, _section) in BEHAVIOR_FIELDS.items():
        from cdmw.core.compact_static import field_payload
        data = layout.data(field) if not isinstance(shape,str) and shape[0] == 'optional' else field_payload(layout,field)
        if data is None:
            result[name] = default_value(shape)
            continue
        cursor = Cursor(data)
        try:
            result[name] = read_value(cursor, shape, generation=layout.generation, owner=name)
            cursor.finish()
        except RecordError as exc:
            raise RecordError(f'{field}: {exc}') from exc
    return result


def set_behavior_fields(raw, values):
    encode_behavior_settings(ItemBehaviorSettings(values))
    layout = read_item_layout(raw)
    fields = {BEHAVIOR_FIELDS[name][0]: write_value(BEHAVIOR_FIELDS[name][1], value, generation=layout.generation, owner=name)
              for name, value in values.items()}
    from cdmw.core.compact_static import field_bytes
    for name in values:
        field,shape,_section = BEHAVIOR_FIELDS[name]
        if isinstance(shape,str) or shape[0] != 'optional':
            fields[field] = field_bytes(layout,field,fields[field])
    return replace_layout_fields(layout, fields).raw


def default_value(shape):
    """The editable value of an absent compact optional structure."""
    if isinstance(shape,str):
        return {'type':18,'value':None} if shape == 'subitem' else False if shape == 'bool' else '' if shape in ('text','texture') else 0
    if shape[0] == 'optional': return None
    if shape[0] == 'record': return {name:default_value(child) for name,child in shape[1]}
    if shape[0] == 'array': return [default_value(shape[1]) for _ in range(shape[2])]
    return []
