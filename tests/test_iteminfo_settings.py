from dataclasses import replace
import struct

import pytest

from cdmw.core.item_layout import read_item_layout
from cdmw.core.iteminfo_row import parse_iteminfo_row
from cdmw.core.iteminfo_settings import read_item_settings, set_item_settings
from cdmw.domain.new_item.item_settings import ItemSettings, RepairEntry, QuantityEdit, encode_settings, decode_settings
from tests.item_layout_fixtures import full_item


@pytest.mark.parametrize('current', (False, True))
def test_repair_policy_extraction_and_use_fields_preserve_every_unassigned_field(current):
    raw = full_item(current=current)
    before = read_item_layout(raw)
    settings = ItemSettings(repairs=(RepairEntry(1, 65535, 255, (1 << 64) - 1), RepairEntry(11, 0, 0, 3)),
        blocked_store_sell=True, discardable=True, important_item=True, destroy_when_broken=False,
        preserved_on_extract=True, can_disassemble=True, extractable=True, extraction_reward=880000,
        minimum_extract_level=65535, use_actions=(1000031, 1000032),
        cooldowns=(0, 1 << 63, (1 << 64) - 1), maximum_charges=(0, 1 << 31, 0xffffffff),
        charge_type=255, shared_cooldown_group=0xffffffff)
    edited = set_item_settings(raw, settings)
    actual, _ = read_item_settings(edited)
    assert actual == settings
    expected_changes = {'_repairDataList', '_isBlockedStoreSell', '_discardable', '_isImportantItem',
        '_isDestoryWhenBroken', '_isPreservedOnExtract', '_canDisassemble', '_isExtractAbleItem',
        '_extractAdditionalDropSetInfo', '_minimumExtractEnchantLevel', '_itemUseInfoList', '_cooltime',
        '_maxChargedUseableCount', '_itemChargeType', '_sharedCoolTimeGroupNameHash'}
    after = read_item_layout(edited)
    assert all(before.data(name) == after.data(name) for name in before.fields if name not in expected_changes)
    cleared = replace(settings, repairs=(), use_actions=(), discardable=False, extraction_reward=0,
        cooldowns=(0, 0, 0), maximum_charges=(0, 0, 0))
    assert read_item_settings(set_item_settings(edited, cleared))[0] == cleared


@pytest.mark.parametrize('value', (1 << 32, (1 << 64) - 1, 0))
def test_prices_are_complete_u64_quantities_and_the_symbol_word_is_preserved(value):
    raw = full_item()
    before = read_item_layout(raw)
    price = before.data('_priceList')
    # Independently place a high amount word and a nonzero PriceFloor symbol.
    changed_price = price[:8] + struct.pack('<Q', (1 << 40) + 3) + struct.pack('<I', 77) + price[20:]
    from cdmw.core.item_layout import replace_layout_fields
    raw = replace_layout_fields(before, {'_priceList': changed_price}).raw
    legacy = parse_iteminfo_row(raw)
    assert legacy.price_list[0].full_price == (1 << 40) + 3
    assert legacy.price_list[0].symbol_number == 77
    result = read_item_layout(set_item_settings(raw, ItemSettings(quantities=(QuantityEdit('price', 1, value),))))
    assert result.data('_priceList') == changed_price[:8] + struct.pack('<Q', value) + changed_price[16:]
    quantities = read_item_settings(result.raw)[1]
    assert next(row.value for row in quantities if (row.kind, row.key) == ('price', 1)) == value


@pytest.mark.parametrize('value', (-(1 << 63), -1, 1 << 32, (1 << 63) - 1))
def test_full_stat_counter_writes_exactly_eight_bytes_without_touching_other_levels(value):
    raw = full_item()
    legacy = parse_iteminfo_row(raw)
    offset = legacy.enchant_levels[1].stats[0].offset
    expected = raw[:offset] + struct.pack('<q', value) + raw[offset + 8:]
    result = set_item_settings(raw, ItemSettings(quantities=(QuantityEdit('stat', 1000002, value, 1),)))
    assert result == expected
    assert parse_iteminfo_row(result).enchant_levels[1].stats[0].full_value == value
    assert next(row.value for row in read_item_settings(result)[1] if (row.kind, row.level) == ('stat', 1)) == value


@pytest.mark.parametrize('change', (
    {'discardable': 1}, {'charge_type': True}, {'minimum_extract_level': 65536},
    {'cooldowns': (0, 0, 1 << 64)}, {'maximum_charges': (1, 2)},
    {'repairs': (RepairEntry(0, 1, 0, 2),)}, {'repairs': (RepairEntry(1, 1, 0, 0),)},
    {'use_actions': (2, 2)}, {'quantities': (QuantityEdit('price', 1, -1),)},
    {'quantities': (QuantityEdit('stat', 1, 1 << 63, 0),)},
    {'quantities': (QuantityEdit('stat', 1, 5, 0), QuantityEdit('stat', 1, 6, 0))},
))
def test_invalid_extended_settings_refuse_before_edit(change):
    raw = full_item()
    with pytest.raises(ValueError):set_item_settings(raw, ItemSettings(**change))
    assert read_item_layout(raw).integer('_itemTier') == 3


def test_settings_wire_is_closed_and_zero_false_and_empty_lists_survive():
    settings = ItemSettings(repairs=(), discardable=False, use_actions=(), charge_type=0)
    encoded = encode_settings(settings)
    assert decode_settings(encoded) == settings
    encoded['future_field'] = 1
    with pytest.raises(ValueError, match='fields'):decode_settings(encoded)
    with pytest.raises(ValueError, match='explicit'):encode_settings(ItemSettings())


@pytest.mark.parametrize('ambiguous', (False, True))
def test_missing_or_ambiguous_source_quantity_refuses_without_changing_the_row(ambiguous):
    raw = full_item()
    if ambiguous:
        from cdmw.core.item_layout import replace_layout_fields
        layout = read_item_layout(raw)
        price = layout.data('_priceList')[4:24]
        raw = replace_layout_fields(layout, {'_priceList': struct.pack('<I', 2) + price + price}).raw
    before = bytes(raw)
    key = 1 if ambiguous else 999999
    with pytest.raises(ValueError, match='missing or ambiguous'):
        set_item_settings(raw, ItemSettings(quantities=(QuantityEdit('price', key, 1 << 40),)))
    assert raw == before


def test_destroy_when_broken_can_be_enabled_without_changing_other_fields():
    raw = full_item()
    before = read_item_layout(raw)
    result = read_item_layout(set_item_settings(raw, ItemSettings(destroy_when_broken=True)))
    assert result.data('_isDestoryWhenBroken') == b'\x01'
    assert all(before.data(field) == result.data(field) for field in before.fields if field != '_isDestoryWhenBroken')
