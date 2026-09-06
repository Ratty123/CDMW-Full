"""Synthetic current-generation records; no licensed game payloads."""
from dataclasses import replace

import pytest

from cdmw.core.iteminfo_row import encode_stat_block, parse_iteminfo_row, rebuild_stat_block
from cdmw.core.storeinfo_table import (
    StoreInfoError, encode_store_row, insert_stock_entry, parse_store_row,
    parse_store_table, swap_stock_item,
)
from tests.test_iteminfo_row import build_row
from tests.test_storeinfo_table import _row, _sample, _table, CLONE, ZIANE


@pytest.mark.parametrize("marker", (0x11, 0x12))
def test_item_marker_survives_rebuild_and_edits(marker):
    raw = bytearray(build_row())
    legacy = parse_iteminfo_row(raw)
    position = legacy.stat_block_offset + 8 + 4 * len(legacy.socket_items) + 12 * len(legacy.add_socket_materials)
    raw[position] = marker
    row = parse_iteminfo_row(raw)
    assert row.stat_block_marker == marker
    assert rebuild_stat_block(row) == raw
    assert encode_stat_block(row) == raw[row.stat_block_offset:row.stat_block_end]
    edited = parse_iteminfo_row(rebuild_stat_block(row, socket_items=(), add_socket_materials=()))
    assert edited.stat_block_marker == marker
    assert edited.socket_items == edited.add_socket_materials == ()
    assert [(s.status_key, s.value, s.extra) for s in edited.enchant_levels[0].stats] == [
        (s.status_key, s.value, s.extra) for s in row.enchant_levels[0].stats]


def current_store():
    legacy = parse_store_row(_sample())
    return replace(legacy, layout="current", prefix=legacy.prefix + b"\x00",
                   entries=tuple(replace(e, condition_data=bytes(range(i, i + 8)))
                                 for i, e in enumerate(legacy.entries)))


def test_current_stock_preserves_conditions_options_and_order_records():
    source = current_store()
    raw = encode_store_row(source)
    row = parse_store_row(raw, layout="current")
    assert encode_store_row(row) == raw
    for actual, expected in zip(row.entries, source.entries):
        assert actual.condition_data == expected.condition_data
        assert actual.order_records == expected.order_records
        assert actual.option_block == expected.option_block
    moved = parse_store_row(swap_stock_item(row, ZIANE, CLONE).raw, layout="current")
    assert moved.entries_for(CLONE)[0].condition_data == source.entries[1].condition_data
    inserted = insert_stock_entry(row, CLONE, template=row.entries[1], keep_requirement=False, count=7)
    again = parse_store_row(inserted.raw, layout="current")
    assert again.entries_for(CLONE)[0].count == 7
    assert again.entries_for(CLONE)[0].condition_data == row.entries[1].condition_data
    assert again.entries_for(CLONE)[0].option_block is None
    assert len(again.entries) == len(row.entries) + 1
    payload, header = _table([raw])
    assert parse_store_table(payload, header, layout="current")[0].raw == raw


def test_wrong_layout_and_cross_generation_stock_are_refused():
    row = current_store()
    with pytest.raises(StoreInfoError):
        parse_store_row(encode_store_row(row), layout="legacy")
    with pytest.raises(StoreInfoError, match="different layouts"):
        insert_stock_entry(row, CLONE, template=parse_store_row(_sample()).entries[0])
    with pytest.raises(StoreInfoError, match="unsupported"):
        parse_store_row(_row(()), layout="unknown")
