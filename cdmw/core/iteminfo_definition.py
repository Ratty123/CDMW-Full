"""Declared-field codecs for the six extended ItemInfo definition areas."""
import struct

from cdmw.core.item_layout import read_item_layout, replace_layout_fields
from cdmw.core.new_item_record import Cursor, RecordError, text_bytes
from cdmw.domain.new_item.item_definition import FLAGS, NUMBERS, COLLECTIONS, SEAL_TARGETS, decode_definition_settings


def _flag(cursor):
    value = cursor.unpack('B')
    if value not in (0, 1):
        raise RecordError('Unsupported item definition flag.')
    return bool(value)


def _local(cursor):
    return {'category': cursor.unpack('B'), 'key': cursor.unpack('Q'), 'text_key': cursor.text()}


def decode_local_string(raw):
    cursor = Cursor(raw)
    value = _local(cursor)
    cursor.finish()
    return value


def encode_local_string(value):
    return struct.pack('<BQ', value['category'], value['key']) + text_bytes(value['text_key'])


def _stat_list(cursor, parameter=False):
    return [{'stat': cursor.unpack('I'), 'value': cursor.unpack('B' if parameter else 'q')}
            for _ in range(cursor.count(256))]


def _read(kind, cursor, generation):
    if kind == 'sharpness':
        value = {'limit': cursor.unpack('H'), 'craft_tool': cursor.unpack('H')}
        for name in ('maximum', 'regeneration', 'static', 'parameters'):
            value[name] = _stat_list(cursor, name == 'parameters')
        return value
    if kind == 'faction':
        value = {'valid': _flag(cursor)}
        for name in ('costs', 'prices'):
            value[name] = [dict(zip(('item', 'count', 'minimum', 'maximum'), cursor.unpack('IQQQ')))
                           for _ in range(cursor.count(256))]
        value['tier'] = cursor.unpack('I') if generation == 'current' else None
        return value
    if kind == 'routing':
        return [cursor.unpack('H') for _ in range(10 if generation == 'current' else 9)]
    values = []
    for _ in range(cursor.count(256)):
        if kind == 'bundles':
            value = {'minimum': cursor.unpack('Q'), 'gimmick': cursor.unpack('I')}
        elif kind == 'slots':
            value = {'name_hash': cursor.unpack('I'), 'indexes': [cursor.unpack('B') for _ in range(cursor.count(16))]}
        elif kind == 'patterns':
            value = {'pattern': cursor.unpack('I'), 'parameters': []}
            for _ in range(cursor.count(64)):
                parameter = {'kind': cursor.unpack('B')}
                parameter.update(_local(cursor))
                value['parameters'].append(parameter)
        elif kind == 'sealable':
            value = {'target_type': cursor.unpack('B'), 'item': cursor.unpack('I'), 'count': cursor.unpack('Q')}
            target_type = value['target_type']
            if target_type not in SEAL_TARGETS:
                raise RecordError('Unsupported seal target kind.')
            value['target'] = cursor.text() if target_type == 2 else None if target_type == 5 else cursor.unpack('I')
        elif kind == 'strings':
            value = cursor.text()
        else:
            value = cursor.unpack('I')
        values.append(value)
    return values


def _counted(values, encoder):
    return struct.pack('<I', len(values)) + b''.join(encoder(row) for row in values)


def _pack_stats(values, parameter=False):
    return _counted(values, lambda row: struct.pack('<IB' if parameter else '<Iq', row['stat'], row['value']))


def _write(kind, value, generation):
    if kind == 'sharpness':
        return struct.pack('<HH', value['limit'], value['craft_tool']) + b''.join(
            _pack_stats(value[name], name == 'parameters') for name in ('maximum', 'regeneration', 'static', 'parameters'))
    if kind == 'faction':
        if (generation == 'legacy') != (value['tier'] is None):
            raise RecordError('Faction tier must match the source generation.')
        result = bytes([int(value['valid'])])
        for name in ('costs', 'prices'):
            result += _counted(value[name], lambda row: struct.pack('<IQQQ', row['item'], row['count'], row['minimum'], row['maximum']))
        return result + (struct.pack('<I', value['tier']) if value['tier'] is not None else b'')
    if kind == 'routing':
        if len(value) != (10 if generation == 'current' else 9):
            raise RecordError('Inventory routing length must match the source generation.')
        return b''.join(struct.pack('<H', entry) for entry in value)
    def row_bytes(row):
        if kind == 'bundles':
            return struct.pack('<QI', row['minimum'], row['gimmick'])
        if kind == 'slots':
            return struct.pack('<I', row['name_hash']) + _counted(row['indexes'], lambda index: bytes([index]))
        if kind == 'patterns':
            return struct.pack('<I', row['pattern']) + _counted(row['parameters'],
                lambda parameter: bytes([parameter['kind']]) + encode_local_string(parameter))
        if kind == 'sealable':
            result = struct.pack('<BIQ', row['target_type'], row['item'], row['count'])
            if row['target_type'] == 2:
                return result + text_bytes(row['target'])
            return result if row['target_type'] == 5 else result + struct.pack('<I', row['target'])
        return text_bytes(row) if kind == 'strings' else struct.pack('<I', row)
    return _counted(value, row_bytes)


def read_definition_fields(raw):
    layout = read_item_layout(raw)
    result = {}
    for name, (field, _section) in FLAGS.items():
        cursor = Cursor(layout.data(field))
        result[name] = _flag(cursor)
        cursor.finish()
    for name, (field, width, _section, _table) in NUMBERS.items():
        result[name] = layout.integer(field, width=width)
    for name, (field, kind, _section) in COLLECTIONS.items():
        cursor = Cursor(layout.data(field))
        result[name] = _read(kind, cursor, layout.generation)
        cursor.finish()
    return result


def set_definition_fields(raw, values):
    decode_definition_settings({'fields': values, 'secondary_description': None})
    layout = read_item_layout(raw)
    replacements = {}
    for name, value in values.items():
        if name in FLAGS:
            replacements[FLAGS[name][0]] = bytes([int(value)])
        elif name in NUMBERS:
            field, width, _section, _table = NUMBERS[name]
            replacements[field] = value.to_bytes(width, 'little')
        else:
            field, kind, _section = COLLECTIONS[name]
            replacements[field] = _write(kind, value, layout.generation)
    return replace_layout_fields(layout, replacements).raw
