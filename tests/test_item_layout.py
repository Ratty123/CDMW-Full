"""Full layouts prove boundaries; synthetic edits also exercise nonempty lists."""
from pathlib import Path
import struct

import pytest

from cdmw.core.item_layout import (read_item_layout, read_item_use_layout, replace_layout_fields,
    rebind_item_hashes, counted_integers, MAX_RECORD)
from cdmw.core.iteminfo_row import parse_iteminfo_row, clone_iteminfo_row
from cdmw.core.item_use_reward import item_use_references
from cdmw.core.new_item_record import RecordError
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.services.new_item_recipes import replace_recipe_references
from tests.item_layout_fixtures import full_item, counted, use_action


@pytest.mark.parametrize('current', (False, True))
def test_complete_fields_allow_nonempty_tags_use_lists_and_exact_recipe_replacement(current):
    raw = full_item(current=current, fields={'_itemTagList': counted((15, 16, 17)),
        '_consumableTypeList': counted((1, 2)), '_itemUseInfoList': counted((77, 78)),
        '_multiChangeInfoList': counted((33, 34)), '_filterType': struct.pack('<I', 8) + b'variable'})
    layout = read_item_layout(raw)
    assert len(layout.fields) == 115 and layout.generation == ('current' if current else 'legacy')
    row = parse_iteminfo_row(raw)
    offset, uses = item_use_references(row, {77, 78})
    assert offset == layout.fields['_itemUseInfoList'].start and uses == (77, 78)
    result = read_item_layout(replace_recipe_references(row, {33, 34}, (99,)))
    assert counted_integers(result, '_multiChangeInfoList') == (99,)
    assert all(result.data(field) == layout.data(field) for field in layout.fields if field != '_multiChangeInfoList')


def test_retained_rows_qualify_all_fields_and_independently_known_positions():
    base = Path(__file__).parent / 'fixtures/new_item_golden/gamedata/binary__/client/bin'
    body, header = (base / 'iteminfo.pabgb').read_bytes(), (base / 'iteminfo.pabgh').read_bytes()
    rows = list(parse_pabgh_table(header, payload=body).row_spans(len(body)))
    assert len(rows) == 15
    for row, start, end in rows:
        layout = read_item_layout(body[start:end])
        assert len(layout.fields) == 115
        if row.row_id == 1001295:
            assert layout.fields['_priceList'].start == 1317
            assert layout.fields['_maxEndurance'].start == 1667
            assert layout.fields['_prefabDataList'].start == 1673


def test_hash_rebinding_only_changes_declared_resource_fields_even_when_values_repeat():
    old, new = 123456, 654321
    icon = struct.pack('<I', 1) + struct.pack('<II', old, 0) + bytes(6)
    raw = full_item(fields={'_itemIconList': icon, '_itemTagList': counted((old,)), '_materialKey': struct.pack('<I', old)})
    layout = read_item_layout(raw)
    result = rebind_item_hashes(layout, {old: new})
    assert result.data('_itemIconList')[4:8] == struct.pack('<I', new)
    assert result.data('_itemTagList') == layout.data('_itemTagList')
    assert result.data('_materialKey') == layout.data('_materialKey')
    with pytest.raises(RecordError, match='no declared'):
        rebind_item_hashes(layout, {999: 111})
    clone = clone_iteminfo_row(parse_iteminfo_row(raw), key=1990001, string_key='NewItem',
        name_key='new_name', desc_key='new_description', replace_hashes={old: new})
    assert read_item_layout(clone).data('_materialKey') == layout.data('_materialKey')


def test_recipe_rebinding_is_a_separate_namespace_from_resource_hashes():
    old = 123456
    icon = struct.pack('<III', 1, old, 0) + bytes(6)
    raw = full_item(fields={'_itemIconList': icon, '_multiChangeInfoList': counted((old,)),
                           '_materialKey': struct.pack('<I', old)})
    clone = clone_iteminfo_row(parse_iteminfo_row(raw), key=1990001, string_key='SeparateNamespaces',
        name_key='new_name', desc_key='new_description', replace_hashes={old: 111}, replace_recipes={old: 222})
    result = read_item_layout(clone)
    assert result.data('_itemIconList')[4:8] == struct.pack('<I', 111)
    assert counted_integers(result, '_multiChangeInfoList') == (222,)
    assert result.data('_materialKey') == struct.pack('<I', old)


def test_occupied_slot_byte_indexes_and_repeated_description_tags_have_exact_boundaries():
    base = full_item()
    layout = read_item_layout(base)
    duplicate = layout.data('_itemDesc')
    raw = replace_layout_fields(layout, {
        '_occupiedEquipSlotDataList': struct.pack('<III', 1, 777, 3) + b'\x01\x02\x03',
        '_itemDesc2': duplicate}).raw
    row = parse_iteminfo_row(raw, structured=True)
    assert row.occupied_slots[0].indexes == (1, 2, 3)
    assert row.prefix_end == read_item_layout(raw).fields['_occupiedEquipSlotDataList'].end
    assert row.desc_offset == read_item_layout(raw).fields['_itemDesc'].start
    assert parse_iteminfo_row(raw).desc_offset == row.desc_offset


@pytest.mark.parametrize('kind,payload,expected', (
    (9, b'', 'ItemUseData_DestroyOnly'),
    (1, struct.pack('<HH', 2, 3), 'ItemUseData_ExpandInventorySlot'),
    (0, struct.pack('<III', 1, 777, 4), 'ItemUseData_Skill'),
    (17, b'\0' + struct.pack('<I', 6) + b'TestUI', 'ItemUseData_OpenUI'),
))
def test_general_use_actions_decode_discriminated_payloads(kind, payload, expected):
    layout = read_item_use_layout(use_action(kind=kind, payload=payload))
    assert layout.variants[0] == expected
    assert layout.integer('_key', width=4) == 1000031
    assert layout.data('_itemUseInfoData')[0] == kind


@pytest.mark.parametrize('damage', ('truncate','append','count','size'))
def test_unknown_or_malformed_complete_layouts_refuse(damage):
    raw = full_item()
    if damage == 'truncate':raw = raw[:-1]
    elif damage == 'append':raw += b'\0'
    elif damage == 'size':raw = bytes(MAX_RECORD + 1)
    else:
        layout = read_item_layout(raw)
        offset = layout.fields['_itemTagList'].start
        raw = raw[:offset] + struct.pack('<I', 4097) + raw[offset + 4:]
    with pytest.raises(RecordError):read_item_layout(raw)
    with pytest.raises(RecordError):read_item_use_layout(use_action(kind=255))
