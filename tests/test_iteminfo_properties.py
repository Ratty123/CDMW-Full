"""Bounded equipment-property edits, independent offsets and byte preservation."""
from dataclasses import replace
from pathlib import Path
import struct

import pytest

from cdmw.core.iteminfo_properties import read_item_properties, set_item_properties
from cdmw.core.iteminfo_row import parse_iteminfo_row, rebuild_stat_block
from cdmw.core.structured_binary_editor import parse_pabgh_table
from tests.test_iteminfo_row import build_row


def property_row(raw=None, *, marker=0x11, tier=3, level=17, durability=430, rich=False):
    """Owned synthetic suffix; expected offsets come from construction, not the reader."""
    row = parse_iteminfo_row(build_row() if raw is None else raw)
    # The older synthetic helper has only three opaque bytes before the block.
    # Give this fixture the schema's six explicit tier/drop bytes instead.
    raw = (row.raw[:row.stat_block_offset - 3] + struct.pack('<BBBBH', tier, 0, 1, 0, 0)
           + row.raw[row.stat_block_offset:])
    row = parse_iteminfo_row(raw)
    row = parse_iteminfo_row(rebuild_stat_block(replace(row, stat_block_marker=marker)))
    prefix = bytearray(row.raw[:row.stat_block_end])
    prefix[row.stat_block_offset - 6] = tier
    struct.pack_into('<I', prefix, row.category_info_offset - 4, level)
    # Opaque variable section preceding the independently constructed suffix.
    prefix += b'variable-before-faction' if rich else b'\x93\xa7\x82'
    suffix = bytearray(b'\x01\x00\x01\x00\x01' + struct.pack('<I', 0) + b'\x00')
    for _ in range(2):
        suffix += struct.pack('<I', int(rich))
        if rich:
            suffix += struct.pack('<IQQQ', 1, 2, 3, 4)
    if marker == 0x12:
        suffix += struct.pack('<I', 8)
    suffix += b'\x01' + struct.pack('<Q', 123)
    durability_at = len(prefix) + len(suffix)
    suffix += struct.pack('<HI', durability, int(rich))
    if rich:
        suffix += struct.pack('<IHBQ', 1, 60, 2, 25)
    suffix += struct.pack('<I', int(rich))
    if rich:
        suffix += struct.pack('<3f', 1.0, 0.5, 2.0)
        for width, values in (('I', (43, 44)), ('I', (55,)), ('H', (2, 5)), ('I', (66, 67, 68))):
            suffix += struct.pack('<I', len(values)) + struct.pack('<' + width * len(values), *values)
        suffix += struct.pack('<I', 77) + b'\x01\x00\x02'
    suffix += struct.pack('<' + 'H' * (10 if marker == 0x12 else 9),
                          *range(10 if marker == 0x12 else 9))
    return bytes(prefix + suffix), {'item_tier': row.stat_block_offset - 6,
                                  'required_level': row.category_info_offset - 4,
                                  'max_durability': durability_at}


@pytest.mark.parametrize('marker', (0x11, 0x12))
@pytest.mark.parametrize('rich', (False, True))
def test_properties_use_variable_boundaries_and_preserve_every_other_byte(marker, rich):
    raw, offsets = property_row(marker=marker, rich=rich)
    row = parse_iteminfo_row(raw)
    locations = read_item_properties(row)
    assert locations == {'item_tier': (3, offsets['item_tier'], 1),
                         'required_level': (17, offsets['required_level'], 4),
                         'max_durability': (430, offsets['max_durability'], 2)}
    values = {'item_tier': 255, 'required_level': 0xffffffff, 'max_durability': 65535}
    edited = set_item_properties(row, values)
    expected = bytearray(raw)
    for name, value in values.items():
        _old, offset, width = locations[name]
        expected[offset:offset + width] = value.to_bytes(width, 'little')
    assert edited == bytes(expected)
    assert {name: value[0] for name, value in read_item_properties(parse_iteminfo_row(edited)).items()} == values
    # An explicit zero remains distinct from inheritance, including after a resize.
    zero = set_item_properties(row, dict.fromkeys(values, 0))
    resized = rebuild_stat_block(parse_iteminfo_row(zero), socket_items=(), add_socket_materials=())
    assert all(value[0] == 0 for value in read_item_properties(parse_iteminfo_row(resized)).values())


def test_retained_source_fixture_qualifies_all_rows_and_known_endurance_offset():
    base = Path(__file__).parent / 'fixtures/new_item_golden/gamedata/binary__/client/bin'
    body, header = (base / 'iteminfo.pabgb').read_bytes(), (base / 'iteminfo.pabgh').read_bytes()
    rows = list(parse_pabgh_table(header, payload=body).row_spans(len(body)))
    assert len(rows) == 15
    for directory, start, end in rows:
        locations = read_item_properties(parse_iteminfo_row(body[start:end]))
        assert set(locations) == {'item_tier', 'required_level', 'max_durability'}
        assert locations['max_durability'][0] == 65535
        if directory.row_id == 1001295:
            assert locations['max_durability'] == (65535, 1667, 2)


@pytest.mark.parametrize('damage', ('truncated', 'extra', 'old-opaque-tail', 'ambiguous'))
def test_unqualified_endurance_refuses_without_changing_source(damage):
    raw, offsets = property_row(rich=True)
    if damage == 'truncated':
        raw = raw[:-1]
    elif damage == 'extra':
        raw += b'\xff'
    elif damage == 'old-opaque-tail':
        raw = build_row()
    else:
        # Both a zero-scale prefab and an empty suffix reach EOF, with different
        # endurance positions. Neither interpretation may win by scan order.
        row = parse_iteminfo_row(raw)
        suffix = bytearray(90)
        struct.pack_into('<I', suffix, 33, 1)
        raw = raw[:row.stat_block_end] + suffix
    row = parse_iteminfo_row(raw)
    assert 'max_durability' not in read_item_properties(row)
    with pytest.raises(ValueError, match='no verified max_durability'):
        set_item_properties(row, {'item_tier': None, 'required_level': 21, 'max_durability': 900})
    assert row.raw == raw


@pytest.mark.parametrize('name,bad', [('item_tier', 256), ('required_level', 1 << 32),
                                     ('max_durability', 65536), ('item_tier', True),
                                     ('required_level', -1), ('max_durability', 1.5)])
def test_out_of_range_and_non_integer_property_values_refuse(name, bad):
    raw, _ = property_row()
    values = dict.fromkeys(('item_tier', 'required_level', 'max_durability'))
    values[name] = bad
    with pytest.raises(ValueError):
        set_item_properties(parse_iteminfo_row(raw), values)
