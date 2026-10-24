"""Exact declared-field edits for consumable and inventory settings."""
import struct

from cdmw.core.item_layout import read_item_layout, replace_layout_fields, counted_integers
from cdmw.core.new_item_record import Cursor, RecordError
from cdmw.domain.new_item.item_inventory import (ItemInventorySettings, MaterialGroup, ReserveSlotTarget,
    BOOLEAN_FIELDS, INTEGER_FIELDS, LIST_FIELDS, PAIR_FIELDS, encode_inventory_settings)


def read_item_inventory(raw):
    layout = read_item_layout(raw)
    values = {}
    for name, field in BOOLEAN_FIELDS.items():
        value = layout.integer(field, width=1)
        if value not in (0, 1):
            raise RecordError(f'Unsupported {field} flag.')
        values[name] = bool(value)
    for name, (field, width, _minimum, _maximum) in INTEGER_FIELDS.items():
        values[name] = layout.integer(field, width=width)
    for name, field in LIST_FIELDS.items():
        values[name] = counted_integers(layout, field)
    for name, field in PAIR_FIELDS.items():
        cursor = Cursor(layout.data(field))
        cls, fmt = (ReserveSlotTarget, 'II') if name == 'reserve_slots' else (MaterialGroup, 'HI')
        values[name] = tuple(cls(*cursor.unpack(fmt)) for _ in range(cursor.count(256)))
        cursor.finish()
    return ItemInventorySettings(**values)


def set_item_inventory(raw, settings):
    encode_inventory_settings(settings)
    layout = read_item_layout(raw)
    replacements = {}
    for name, field in BOOLEAN_FIELDS.items():
        if (value := getattr(settings, name)) is not None:
            replacements[field] = bytes([int(value)])
    for name, (field, width, _minimum, _maximum) in INTEGER_FIELDS.items():
        if (value := getattr(settings, name)) is not None:
            replacements[field] = value.to_bytes(width, 'little')
    for name, field in LIST_FIELDS.items():
        if (value := getattr(settings, name)) is not None:
            replacements[field] = struct.pack('<I', len(value)) + b''.join(struct.pack('<I', key) for key in value)
    for name, field in PAIR_FIELDS.items():
        if (value := getattr(settings, name)) is not None:
            pairs = ((row.slot_key, row.condition_key) for row in value) if name == 'reserve_slots' else (
                (row.group_key, row.value) for row in value)
            fmt = '<II' if name == 'reserve_slots' else '<HI'
            replacements[field] = struct.pack('<I', len(value)) + b''.join(struct.pack(fmt, *row) for row in pairs)
    return replace_layout_fields(layout, replacements).raw
