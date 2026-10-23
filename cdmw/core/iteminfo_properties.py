"""Bounded scalar locations in the supported ItemInfo equipment layouts.

The endurance field is qualified by the complete trailing faction/repair/prefab
and inventory-routing structure, never by a fixed distance from EOF. Multiple
valid interpretations must agree on its exact offset. Unknown layouts refuse.
"""
import math
import struct

from cdmw.core.new_item_record import Cursor, RecordError
from cdmw.domain.new_item.item_properties import checked_properties


def _endurance_candidate(data, start, marker):
    cursor = Cursor(data)
    cursor.pos = start

    def flags(count):
        if any(value > 1 for value in cursor.take(count)):
            raise RecordError('Unsupported ItemInfo boolean.')

    def count():
        return cursor.count(128)

    # Clone-actor, sale, preorder, use-buff and extraction flags, then effect.
    flags(5)
    cursor.take(4)
    flags(1)  # Faction management validity; its lists are still serialized.
    for _ in range(2):
        cursor.take(28 * count())
    if marker == 0x12:
        cursor.take(4)  # Current faction-management tier.
    flags(1)
    cursor.take(8)  # Respawn time.
    endurance_at = cursor.pos
    cursor.take(2)
    for _ in range(count()):
        if cursor.unpack('I') == 0:
            raise RecordError('Unqualified repair resource.')
        cursor.take(3)  # u16 repair value and u8 repair style.
        if cursor.unpack('Q') == 0:
            raise RecordError('Unqualified repair quantity.')
    for _ in range(count()):
        if not all(math.isfinite(value) for value in cursor.unpack('3f')):
            raise RecordError('Invalid prefab scale.')
        for _ in range(2):
            cursor.take(4 * count())  # Prefab names, animation paths.
        cursor.take(2 * count())  # Equip slots.
        cursor.take(4 * count())  # Tribe/gender references.
        cursor.take(4)  # Docking switch reference.
        flags(2)
        cursor.take(1)  # Prefab data type.
    cursor.take(2 * (10 if marker == 0x12 else 9))
    cursor.finish()
    return endurance_at


def read_item_properties(row):
    """Return verified name -> (value, byte offset, width) entries only."""
    result = {}
    if row.category_info_offset is not None:
        offset = row.category_info_offset - 4
        if offset >= 0:
            result['required_level'] = (struct.unpack_from('<I', row.raw, offset)[0], offset, 4)
    if row.stat_block_offset is None or row.stat_block_end is None:
        return result
    tier_at = row.stat_block_offset - 6
    if (row.category_info_offset is not None and tier_at >= row.category_info_offset + 2
            and all(value <= 1 for value in row.raw[tier_at + 1:tier_at + 3])):
        result['item_tier'] = (row.raw[tier_at], tier_at, 1)
    if row.stat_block_marker not in (0x11, 0x12) or len(row.raw) > 65536:
        return result
    candidates = set()
    for start in range(row.stat_block_end, len(row.raw) - 52):
        try:
            candidates.add(_endurance_candidate(row.raw, start, row.stat_block_marker))
        except (RecordError, struct.error):
            continue
        if len(candidates) > 1:
            break
    if len(candidates) == 1:
        offset = candidates.pop()
        result['max_durability'] = (struct.unpack_from('<H', row.raw, offset)[0], offset, 2)
    return result


def set_item_properties(row, values):
    """Validate all requested fields before modifying a private byte copy."""
    values = checked_properties(values)
    locations = read_item_properties(row)
    wanted = {name: value for name, value in values.items() if value is not None}
    for name in wanted:
        if name not in locations:
            raise ValueError(f'The template has no verified {name} layout.')
    output = bytearray(row.raw)
    for name, value in wanted.items():
        _old, offset, width = locations[name]
        output[offset:offset + width] = value.to_bytes(width, 'little')
    from cdmw.core.iteminfo_row import parse_iteminfo_row
    final = read_item_properties(parse_iteminfo_row(bytes(output)))
    if any(final.get(name) != (value, locations[name][1], locations[name][2]) for name, value in wanted.items()):
        raise ValueError('The item property edit did not preserve its verified layout.')
    return bytes(output)
