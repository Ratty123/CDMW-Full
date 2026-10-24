"""Complete-field codecs for item.behavior, preserving all unassigned bytes."""
import struct

from cdmw.core.item_layout import read_item_layout, replace_layout_fields
from cdmw.core.new_item_record import Cursor, RecordError, text_bytes
from cdmw.domain.new_item.item_behavior import BEHAVIOR_FIELDS, ItemBehaviorSettings, encode_behavior_settings, validate_value


FORMATS = {'u8': 'B', 'u16': 'H', 'u32': 'I', 'u64': 'Q', 'i64': 'q', 'f32': 'f'}


def read_value(cursor, shape, *, generation='current', owner=''):
    if isinstance(shape, str):
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
        return {name: (0 if generation == 'legacy' and owner == 'inspect_action' and name == 'catch_tag_hash'
                       else read_value(cursor, child, generation=generation, owner=owner)) for name, child in shape[1]}
    count = shape[2] if kind == 'array' else cursor.count(shape[2])
    return [read_value(cursor, shape[1], generation=generation, owner=owner) for _ in range(count)]


def write_value(shape, value, *, generation='current', owner=''):
    validate_value(shape, value)
    if isinstance(shape, str):
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
        return b''.join(write_value(child, value[name], generation=generation, owner=owner) for name, child in shape[1]
            if not (generation == 'legacy' and owner == 'inspect_action' and name == 'catch_tag_hash'))
    prefix = b'' if kind == 'array' else struct.pack('<I', len(value))
    return prefix+b''.join(write_value(shape[1], child, generation=generation, owner=owner) for child in value)


def read_behavior_fields(raw):
    layout = read_item_layout(raw)
    result = {}
    for name, (field, shape, _section) in BEHAVIOR_FIELDS.items():
        cursor = Cursor(layout.data(field))
        result[name] = read_value(cursor, shape, generation=layout.generation, owner=name)
        cursor.finish()
    return result


def set_behavior_fields(raw, values):
    encode_behavior_settings(ItemBehaviorSettings(values))
    layout = read_item_layout(raw)
    fields = {BEHAVIOR_FIELDS[name][0]: write_value(BEHAVIOR_FIELDS[name][1], value, generation=layout.generation, owner=name)
              for name, value in values.items()}
    return replace_layout_fields(layout, fields).raw
