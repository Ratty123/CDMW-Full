"""Gates for the `storeinfo.pabgb` row model: parse, swap, insert, and the corpus round trip."""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.core.storeinfo_table import (  # noqa: E402
    StockEntry,
    StoreInfoError,
    apply_store_row,
    encode_stock_entry,
    encode_store_row,
    insert_stock_entry,
    parse_store_row,
    parse_store_table,
    remove_stock_entry,
    set_stock_count,
    store_index,
    swap_stock_item,
    UNLIMITED_STOCK,
)
from cdmw.core.structured_binary_editor import parse_pabgh_table  # noqa: E402

STORE = 2003
ZIANE = 1001295
CLONE = 1990001


def _entry(item: int, index: int, *, buyable: bool = True, sellable: bool = False, option: bytes | None = None,
           records: tuple[bytes, ...] = (), order: int | None = None, count: int = 1) -> StockEntry:
    drop = bytearray(55)
    drop[0x25] = 1
    drop[0x35] = drop[0x36] = 0xFF
    return StockEntry(
        store_key=STORE, min_price_percent=1_000_000, max_price_percent=1_000_000, count=count, threshold=-1,
        stock_index=index, order_index=index if order is None else order, important_save_index=-1,
        flags=bytes([1, int(sellable), int(buyable), int(option is not None), 1]), item_key=item,
        drop_bytes=bytes(drop), after_bytes=bytes(8), option_block=option, order_records=records,
    )


def _row(entries: tuple[StockEntry, ...], *, store_type: int = 1, name: str = "Store_Pai_BlackMarket", key: int = STORE) -> bytes:
    from dataclasses import replace

    entries = tuple(replace(e, store_key=key) for e in entries)
    prefix = struct.pack("<H", key) + struct.pack("<I", len(name)) + name.encode() + b"\x00"
    prefix += struct.pack("<III", 1, 1, 1) + bytes(16) + b"\xff\xff\xff\xff" + struct.pack("<I", 1)
    buyable = sum(1 for e in entries if e.is_buyable)
    sellable = sum(1 for e in entries if e.is_sellable)
    head = struct.pack("<II", buyable, sellable) + bytes([store_type]) + struct.pack("<I", len(entries))
    tail = bytes(4) + struct.pack("<I", 2) + struct.pack("<I", 15933) + bytes(4) + b"\x01"
    return prefix + head + b"".join(encode_stock_entry(e) for e in entries) + tail


def _sample() -> bytes:
    option = struct.pack("<I", 1001479) + b"\x01" + bytes(range(8))
    return _row((
        _entry(50001, 0, count=60),
        _entry(ZIANE, 1, option=option, order=7),
        _entry(1000372, 2, records=(bytes(4) + struct.pack("<I", 1) + bytes(4),)),
        _entry(1000692, 3, buyable=False, sellable=True),
    ))


def _table(rows: list[bytes]) -> tuple[bytes, bytes]:
    payload = bytearray()
    directory = bytearray()
    for raw in rows:
        directory += raw[:2] + struct.pack("<I", len(payload))
        payload += raw
    return bytes(payload), struct.pack("<H", len(rows)) + bytes(directory)


class ParseTests(unittest.TestCase):
    def test_a_row_parses_and_re_encodes(self) -> None:
        raw = _sample()
        row = parse_store_row(raw, key=STORE)
        self.assertEqual(row.name, "Store_Pai_BlackMarket")
        self.assertEqual((row.buyable_count, row.sellable_count, row.store_type), (3, 1, 1))
        self.assertEqual([e.item_key for e in row.entries], [50001, ZIANE, 1000372, 1000692])
        self.assertEqual([e.stock_index for e in row.entries], [0, 1, 2, 3])
        self.assertEqual(row.entries[1].order_index, 7)
        self.assertEqual(row.entries[1].option_item_key, 1001479)
        self.assertIsNone(row.entries[0].option_block)
        self.assertEqual(len(row.entries[2].order_records), 1)
        self.assertEqual(row.entries[0].count, 60)
        self.assertEqual([e.is_buyable for e in row.entries], [True, True, True, False])
        self.assertEqual([e.is_sellable for e in row.entries], [False, False, False, True])
        self.assertEqual(row.entries[1].offset, row.entries[0].end)
        self.assertEqual(row.entries[1].end - row.entries[1].offset, 0x84)
        self.assertEqual(row.entries[2].end - row.entries[2].offset, 0x77 + 12)
        self.assertEqual(len(row.tail), 17)
        self.assertEqual(encode_store_row(row), raw)
        self.assertEqual(row.entries_for(ZIANE)[0].stock_index, 1)

    def test_an_empty_store_parses(self) -> None:
        raw = _row(())
        row = parse_store_row(raw)
        self.assertEqual(row.entries, ())
        self.assertEqual(row.tail, raw[-17:])
        self.assertEqual(encode_store_row(row), raw)

    def test_refusals(self) -> None:
        raw = _sample()
        with self.assertRaisesRegex(StoreInfoError, "directory key"):
            parse_store_row(raw, key=STORE + 1)
        broken = bytearray(raw)
        row = parse_store_row(raw)
        struct.pack_into("<I", broken, row.entries[1].offset + 0x66, 1)  # second key no longer repeats
        with self.assertRaisesRegex(StoreInfoError, "does not repeat|does not read|no stock"):
            parse_store_row(bytes(broken))
        with self.assertRaisesRegex(StoreInfoError, "too short"):
            parse_store_row(b"\x01\x02")


class EditTests(unittest.TestCase):
    def test_swap_moves_both_copies_and_nothing_else(self) -> None:
        raw = _sample()
        row = parse_store_row(raw)
        swapped = swap_stock_item(row, ZIANE, CLONE)
        self.assertEqual(len(swapped.raw), len(raw))
        again = parse_store_row(swapped.raw)
        self.assertEqual([e.item_key for e in again.entries], [50001, CLONE, 1000372, 1000692])
        entry = row.entries[1]
        diff = [i for i in range(len(raw)) if raw[i] != swapped.raw[i]]
        self.assertTrue(all(entry.offset + 0x2B <= i < entry.offset + 0x2F or entry.offset + 0x66 <= i < entry.offset + 0x6A for i in diff))
        with self.assertRaisesRegex(StoreInfoError, "does not stock"):
            swap_stock_item(row, 42, CLONE)
        twice = parse_store_row(_row((_entry(ZIANE, 0), _entry(ZIANE, 1))))
        with self.assertRaisesRegex(StoreInfoError, "2 times"):
            swap_stock_item(twice, ZIANE, CLONE)
        self.assertEqual([e.item_key for e in swap_stock_item(twice, ZIANE, CLONE, all_entries=True).entries], [CLONE, CLONE])
        # the line's unlock requirement (the knowledge of a collection prop) can be dropped so the item sells freely
        self.assertEqual(row.entries[1].requirement_item_key, 1001479)
        freed = swap_stock_item(row, ZIANE, CLONE, keep_requirement=False)
        self.assertEqual(len(freed.raw), len(raw) - 13)
        again = parse_store_row(freed.raw)
        self.assertIsNone(again.entries[1].requirement_item_key)
        self.assertEqual([e.item_key for e in again.entries], [50001, CLONE, 1000372, 1000692])
        self.assertEqual((again.buyable_count, again.sellable_count), (row.buyable_count, row.sellable_count))
        self.assertEqual(again.entries[0].requirement_item_key, row.entries[0].requirement_item_key, "other lines keep theirs")
        free_insert = parse_store_row(insert_stock_entry(row, CLONE, template=row.entries[1], keep_requirement=False).raw)
        self.assertIsNone(free_insert.entries_for(CLONE)[0].requirement_item_key)

    def test_a_line_can_be_given_unlimited_stock(self) -> None:
        raw = _sample()
        row = parse_store_row(raw)
        self.assertEqual(UNLIMITED_STOCK, 0xFFFFFFFF)
        # on a swap: the count is the only other thing that moves
        swapped = parse_store_row(swap_stock_item(row, ZIANE, CLONE, count=UNLIMITED_STOCK).raw)
        self.assertEqual(swapped.entries_for(CLONE)[0].count, UNLIMITED_STOCK)
        self.assertEqual(len(swapped.raw), len(raw))
        self.assertEqual([e.count for e in swapped.entries if e.item_key != CLONE], [e.count for e in row.entries if e.item_key != ZIANE])
        # on an insert: the new line's own count, the template's untouched
        grown = parse_store_row(insert_stock_entry(row, CLONE, count=UNLIMITED_STOCK).raw)
        self.assertEqual(grown.entries_for(CLONE)[0].count, UNLIMITED_STOCK)
        self.assertEqual(grown.entries_for(1000372)[0].count, row.entries_for(1000372)[0].count)
        # on a line already in the shop: in place, same length, only the count bytes differ
        again = set_stock_count(row, ZIANE, 7)
        self.assertEqual(len(again.raw), len(raw))
        self.assertEqual(parse_store_row(again.raw).entries_for(ZIANE)[0].count, 7)
        entry = row.entries[1]
        diff = [i for i in range(len(raw)) if raw[i] != again.raw[i]]
        self.assertTrue(diff and all(entry.offset + 0x12 <= i < entry.offset + 0x16 for i in diff))
        with self.assertRaisesRegex(StoreInfoError, "does not stock"):
            set_stock_count(row, 42, 1)

    def test_insert_after_the_buyable_entries(self) -> None:
        row = parse_store_row(_sample())
        grown = insert_stock_entry(row, CLONE)
        again = parse_store_row(grown.raw)
        self.assertEqual([e.item_key for e in again.entries], [50001, ZIANE, 1000372, CLONE, 1000692])
        self.assertEqual([e.stock_index for e in again.entries], [0, 1, 2, 3, 4], "renumbered so index == position")
        self.assertEqual((again.buyable_count, again.sellable_count), (4, 1))
        new = again.entries[3]
        self.assertEqual(new.order_index, 8, "one past the largest order index")
        self.assertEqual(len(new.order_records), 1, "shaped like the last buyable entry")
        self.assertTrue(new.is_buyable and not new.is_sellable)
        self.assertEqual(again.entries[4].order_index, 3, "the sellable entry kept its order index")
        self.assertEqual(len(grown.raw), len(row.raw) + 0x77 + 12)
        self.assertEqual(grown.prefix, row.prefix)
        self.assertEqual(grown.tail, row.tail)
        # explicit template and position
        placed = insert_stock_entry(row, CLONE, template=row.entries[1], position=0)
        self.assertEqual([e.item_key for e in placed.entries][:2], [CLONE, 50001])
        self.assertEqual(placed.entries[0].option_item_key, 1001479)
        self.assertEqual([e.stock_index for e in placed.entries], [0, 1, 2, 3, 4])
        with self.assertRaisesRegex(StoreInfoError, "already stocks"):
            insert_stock_entry(row, ZIANE)
        with self.assertRaisesRegex(StoreInfoError, "outside"):
            insert_stock_entry(row, CLONE, position=9)
        empty = parse_store_row(_row(()))
        with self.assertRaisesRegex(StoreInfoError, "no buyable entry"):
            insert_stock_entry(empty, CLONE)
        seeded = insert_stock_entry(empty, CLONE, template=row.entries[0])
        self.assertEqual((seeded.buyable_count, seeded.sellable_count, len(seeded.entries)), (1, 0, 1))
        self.assertEqual(parse_store_row(seeded.raw).entries[0].item_key, CLONE)

    def test_remove(self) -> None:
        row = parse_store_row(_sample())
        smaller = remove_stock_entry(row, ZIANE)
        again = parse_store_row(smaller.raw)
        self.assertEqual([e.item_key for e in again.entries], [50001, 1000372, 1000692])
        self.assertEqual([e.stock_index for e in again.entries], [0, 1, 2])
        self.assertEqual((again.buyable_count, again.sellable_count), (2, 1))
        with self.assertRaisesRegex(StoreInfoError, "0 times"):
            remove_stock_entry(row, 42)

    def test_apply_shifts_the_directory(self) -> None:
        payload, header = _table([_sample(), _row((_entry(7, 0),), name="Store_Other", key=STORE + 1)])
        rows = parse_store_table(payload, header)
        self.assertEqual([r.name for r in rows], ["Store_Pai_BlackMarket", "Store_Other"])
        grown = insert_stock_entry(rows[0], CLONE)
        new_payload, new_header = apply_store_row(payload, header, grown)
        again = parse_store_table(new_payload, new_header)
        self.assertEqual(len(again), 2)
        self.assertEqual(store_index(again)["Store_Pai_BlackMarket"].entries_for(CLONE)[0].stock_index, 3)
        self.assertEqual(again[1].raw, rows[1].raw, "the other row moved but did not change")
        table = parse_pabgh_table(new_header, payload=new_payload)
        self.assertEqual(len(new_payload) - len(payload), len(grown.raw) - len(rows[0].raw))
        self.assertEqual(table.row_spans(len(new_payload))[1][1], len(grown.raw))

    def test_encode_checks_shapes(self) -> None:
        entry = _entry(1, 0)
        with self.assertRaisesRegex(StoreInfoError, "five flag"):
            encode_stock_entry(_bad(entry, flags=b"\x01"))
        with self.assertRaisesRegex(StoreInfoError, "option block"):
            encode_stock_entry(_bad(entry, option_block=b"\x00" * 3))
        with self.assertRaisesRegex(StoreInfoError, "u32"):
            entry.with_item(-1)


def _bad(entry: StockEntry, **changes) -> StockEntry:
    from dataclasses import replace
    return replace(entry, **changes)


@pytest.mark.real_game
class VanillaStoreTests(unittest.TestCase):
    """Every shipped store row round-trips, its head counts match its flags, and Wolf's Fang is where the spike found it."""

    def test_every_shipped_store_round_trips(self) -> None:
        from tools.placement_studio import corpus
        from cdmw.core.archive_extraction import read_archive_entry_data

        if not corpus.game_root().is_dir():
            self.skipTest("needs the installed game")
        wanted = {"gamedata/binary__/client/bin/storeinfo.pabgb", "gamedata/binary__/client/bin/storeinfo.pabgh"}
        found = {}
        for _package, entry in corpus._iter_archive_entries(corpus.game_root()):
            path = corpus.normalize_game_path(entry.path)
            if path in wanted:
                found[path.rsplit(".", 1)[-1]] = read_archive_entry_data(entry)[0]
        if len(found) != 2:
            self.skipTest("storeinfo not found in the archives")
        rows = parse_store_table(found["pabgb"], found["pabgh"])
        self.assertGreater(len(rows), 400)
        entries = 0
        for row in rows:
            self.assertEqual(encode_store_row(row), row.raw, row.name)
            self.assertEqual([e.stock_index for e in row.entries], list(range(len(row.entries))), row.name)
            self.assertEqual(row.buyable_count, sum(1 for e in row.entries if e.is_buyable), row.name)
            self.assertEqual(row.sellable_count, sum(1 for e in row.entries if e.is_sellable), row.name)
            entries += len(row.entries)
        self.assertGreater(entries, 6000)
        by_name = store_index(rows)
        black_market = by_name["Store_Pai_BlackMarket"]
        self.assertEqual(black_market.key, 2003)
        self.assertEqual(len(black_market.entries_for(ZIANE)), 1)
        for name, key in (("Store_Tash_Harness", 1681), ("Store_Camp_Equipment", 6600), ("Store_Pai_Equipment", 61)):
            self.assertEqual(by_name[name].key, key)
        # the edits the New Item Studio needs, on the shipped rows
        swapped = swap_stock_item(black_market, ZIANE, CLONE)
        self.assertEqual(len(swapped.raw), len(black_market.raw))
        grown = insert_stock_entry(by_name["Store_Camp_Equipment"], CLONE)
        payload, header = apply_store_row(found["pabgb"], found["pabgh"], grown)
        again = store_index(parse_store_table(payload, header))
        self.assertEqual(again["Store_Camp_Equipment"].entries_for(CLONE)[0].stock_index, 112)
        self.assertEqual(again["Store_Pai_BlackMarket"].raw, black_market.raw)


if __name__ == "__main__":
    unittest.main()
