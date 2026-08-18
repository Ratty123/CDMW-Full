from __future__ import annotations

import struct
import unittest

import pytest

from cdmw.core.archive_format import hashlittle
from cdmw.core.iteminfo_row import (
    DESC_TAG,
    NAME_TAG,
    EnchantLevel,
    ItemInfoRowError,
    PriceEntry,
    StatValue,
    clone_iteminfo_row,
    describe_row,
    encode_enchant_level,
    encode_stat_block,
    equip_type_key,
    level_with_buy_price,
    level_with_stat,
    level_without_buy_price,
    level_without_stat,
    next_level_like,
    parse_iteminfo_row,
    parse_status_names,
    price_list_with,
    price_list_without,
    rebuild_stat_block,
    socket_slots_for,
    scale_stats,
    set_buy_price,
    set_max_stack_count,
    set_price,
    set_stat_value,
)

DDD = 1000002
DPV = 1000003
COPPER = 1
CAMP_WEAPON = 15


def _lstr(tag: bytes, key: int, text: str) -> bytes:
    raw = text.encode("ascii")
    return tag + struct.pack("<II", key, len(raw)) + raw


def _price(item: int, price: int) -> bytes:
    return struct.pack("<5I", item, price, 0, 0, item)


def _level(level: int, stats, buy, level_stat_keys=(), buffs=()) -> bytes:
    out = struct.pack("<I", level) + b"\x00" * 6
    out += struct.pack("<I", len(stats)) + b"".join(struct.pack("<Iii", k, v, 0) for k, v in stats)
    out += struct.pack("<I", len(level_stat_keys)) + b"".join(struct.pack("<I", k) + b"\x00" * 21 for k in level_stat_keys)
    out += struct.pack("<I", len(buy)) + b"".join(_price(i, p) for i, p in buy)
    out += struct.pack("<I", len(buffs)) + b"".join(struct.pack("<II", b, 0) for b in buffs)
    out += struct.pack("<I", 0)
    return out


def build_row(
    *,
    key: int = 1001295,
    string_key: str = "Ziane_OneHandSword",
    max_stack: int = 1,
    equip: str = "onehandsword",
    name_key: str = "4300529278648432",
    desc_key: str = "4300529278648433",
    item_type: int = 103,
    memo: str = "지안 한손검",
    stems=("cd_phm_01_sword_0109_r", "cd_phm_01_sword_0109_l"),
    levels=None,
    prices=((COPPER, 348), (CAMP_WEAPON, 17)),
    socket_items=(1002791,),
    adds=((COPPER, 500, 0),),
) -> bytes:
    """A row in the documented shape: prefix, filler, description + item type + memo,
    filler with the stem hashes, stat block, tail."""

    if levels is None:
        levels = [
            ([(DDD, 12000)], [(COPPER, 348), (CAMP_WEAPON, 17)]),
            ([(DDD, 14000)], [(COPPER, 384), (CAMP_WEAPON, 19)]),
        ]
    out = bytearray()
    out += struct.pack("<I", key)
    out += struct.pack("<I", len(string_key)) + string_key.encode("ascii")
    out += b"\x00"  # isBlocked
    out += struct.pack("<I", max_stack)
    out += struct.pack("<I", 0)
    out += _lstr(NAME_TAG, key, name_key)
    out += struct.pack("<I", 0)
    out += struct.pack("<I", equip_type_key(equip) if equip else 0)
    out += struct.pack("<I", 1) + struct.pack("<I", 0x4425304D) + struct.pack("<II", 1, 1)  # one occupied slot
    out += b"\x00" * 16 + struct.pack("<I", 1) + struct.pack("<I", 0xF0E5E879) + b"\x00" * 10  # icon-ish filler
    out += _lstr(DESC_TAG, key, desc_key)
    out += b"\x00" * 17 + struct.pack("<H", item_type) + b"\x00" * 3
    out += b"\x00" * 10 + struct.pack("<h", 3)
    raw_memo = memo.encode("utf-8")
    out += struct.pack("<I", len(raw_memo)) + raw_memo
    out += b"\x00" * 6
    for stem in stems:
        out += struct.pack("<I", hashlittle(stem.encode(), 0xC5EDE))
    out += b"\x01\x01\x01"
    # stat block
    out += struct.pack("<I", len(socket_items)) + b"".join(struct.pack("<I", i) for i in socket_items)
    out += struct.pack("<I", len(adds)) + b"".join(struct.pack("<III", *a) for a in adds)
    out += bytes([0x11, len(socket_items), 1 if adds else 0])  # the socket item count and the has-sockets flag, as every shipped row
    out += struct.pack("<I", len(levels)) + b"".join(_level(i, s, b) for i, (s, b) in enumerate(levels))
    out += struct.pack("<I", len(prices)) + b"".join(_price(i, p) for i, p in prices)
    # tail: an optional key, socket name, and the item-group u16 list the game keeps here
    out += b"\x01" + struct.pack("<I", 1010239) + b"\x00" * 9 + struct.pack("<I", 12) + b"LHand_Socket"
    out += b"\x00" * 8 + bytes([0x11]) + b"\x00" * 3 + b"\x00" * 8  # a second 0x11 with zeros around it, like real tails
    return bytes(out)


class ParseTests(unittest.TestCase):
    def test_prefix_description_type_and_stat_block(self) -> None:
        raw = build_row()
        row = parse_iteminfo_row(raw)
        self.assertEqual((row.key, row.string_key, row.is_blocked, row.max_stack_count), (1001295, "Ziane_OneHandSword", 0, 1))
        self.assertEqual(row.name_key, "4300529278648432")
        self.assertEqual(row.equip_type_key, equip_type_key("OneHandSword"))
        self.assertEqual(row.occupied_slots[0].slot_name_hash, 0x4425304D)
        self.assertEqual(row.occupied_slots[0].indexes, (1,))
        self.assertEqual(row.desc_key, "4300529278648433")
        self.assertEqual(row.item_type, 103)
        self.assertEqual(row.memo, "지안 한손검")
        self.assertEqual(row.coverage, "stat-block")
        self.assertEqual(row.socket_items, (1002791,))
        self.assertEqual(row.add_socket_materials, ((COPPER, 500, 0),))
        self.assertEqual(row.enchant_count, 2)
        self.assertEqual([lvl.level for lvl in row.enchant_levels], [0, 1])
        self.assertEqual([(s.status_key, s.value) for s in row.enchant_levels[0].stats], [(DDD, 12000)])
        self.assertEqual([(p.item_key, p.price) for p in row.enchant_levels[1].buy_prices], [(COPPER, 384), (CAMP_WEAPON, 19)])
        self.assertEqual([(p.item_key, p.price) for p in row.price_list], [(COPPER, 348), (CAMP_WEAPON, 17)])
        # offsets point at the bytes they describe
        stat = row.stat(0, DDD)
        assert stat is not None
        self.assertEqual(struct.unpack_from("<i", raw, stat.offset)[0], 12000)
        self.assertEqual(struct.unpack_from("<I", raw, row.price_list[0].offset)[0], 348)
        self.assertEqual(struct.unpack_from("<I", raw, row.max_stack_count_offset)[0], 1)
        # the second 0x11 in the tail is not mistaken for the block
        self.assertLess(row.stat_block_end, len(raw) - 20)

    def test_level_stats_and_buffs_are_carried(self) -> None:
        levels = [([(DPV, 2000)], [(COPPER, 1)])]
        raw = build_row(levels=levels, equip="helm", item_type=442)
        # hand-build a level with a DataDefinedStaticLevel entry and an equip buff
        rich = _level(0, [(DPV, 2000)], [(COPPER, 4100)], level_stat_keys=(1000007,), buffs=(1000009,))
        raw = raw.replace(_level(0, [(DPV, 2000)], [(COPPER, 1)]), rich)
        row = parse_iteminfo_row(raw)
        self.assertEqual(row.enchant_levels[0].level_stat_keys, (1000007,))
        self.assertEqual(row.enchant_levels[0].equip_buffs, (1000009,))
        self.assertEqual([(p.item_key, p.price) for p in row.enchant_levels[0].buy_prices], [(COPPER, 4100)])

    def test_a_row_without_a_stat_block_still_parses(self) -> None:
        raw = build_row()
        # corrupt the marker so no block is found; the prefix and description still decode
        cut = raw.replace(bytes([0x11, 0x01, 0x01]), bytes([0x12, 0x01, 0x01]))
        row = parse_iteminfo_row(cut)
        self.assertEqual(row.coverage, "no-stat-block")
        self.assertEqual(row.item_type, 103)
        self.assertEqual(row.enchant_levels, ())

    def test_item_keys_tighten_the_anchor(self) -> None:
        raw = build_row(socket_items=(424242,))
        self.assertEqual(parse_iteminfo_row(raw).socket_items, (424242,))
        # with the table's key set given, an unknown socket item is not a stat block
        self.assertEqual(parse_iteminfo_row(raw, item_keys={1, 15, 1001295}).coverage, "no-stat-block")

    def test_a_row_that_is_not_an_iteminfo_row_is_refused(self) -> None:
        with self.assertRaises(ItemInfoRowError):
            parse_iteminfo_row(b"\x01\x02\x03")
        with self.assertRaises(ItemInfoRowError):
            parse_iteminfo_row(struct.pack("<II", 5, 9999) + b"abc")
        bad_name = build_row().replace(NAME_TAG, b"\x07\x72\x00\x00\x00", 1)
        with self.assertRaisesRegex(ItemInfoRowError, "expected 0770000000"):
            parse_iteminfo_row(bad_name)


class EditTests(unittest.TestCase):
    def test_in_place_edits_change_only_their_bytes(self) -> None:
        raw = build_row()
        row = parse_iteminfo_row(raw)
        edited = set_stat_value(row, 1, DDD, 99999)
        self.assertEqual(len(edited), len(raw))
        self.assertEqual(sum(1 for a, b in zip(raw, edited) if a != b), 3)
        self.assertEqual(parse_iteminfo_row(edited).stat(1, DDD).value, 99999)
        edited = set_buy_price(row, 0, CAMP_WEAPON, 1)
        self.assertEqual([(p.item_key, p.price) for p in parse_iteminfo_row(edited).enchant_levels[0].buy_prices], [(COPPER, 348), (CAMP_WEAPON, 1)])
        edited = set_price(row, COPPER, 1234)
        self.assertEqual(parse_iteminfo_row(edited).price_list[0].price, 1234)
        edited = set_max_stack_count(row, 5)
        self.assertEqual(parse_iteminfo_row(edited).max_stack_count, 5)
        scaled = parse_iteminfo_row(scale_stats(row, DDD, 1.5))
        self.assertEqual([lvl.stats[0].value for lvl in scaled.enchant_levels], [18000, 21000])
        # negative values are i32
        negative = parse_iteminfo_row(set_stat_value(row, 0, DDD, -5))
        self.assertEqual(negative.stat(0, DDD).value, -5)

    def test_edits_refuse_what_is_not_there(self) -> None:
        row = parse_iteminfo_row(build_row())
        with self.assertRaisesRegex(ItemInfoRowError, "no stat"):
            set_stat_value(row, 0, DPV, 1)
        with self.assertRaisesRegex(ItemInfoRowError, "no buy price"):
            set_buy_price(row, 0, 99, 1)
        with self.assertRaisesRegex(ItemInfoRowError, "no entry"):
            set_price(row, 99, 1)
        with self.assertRaisesRegex(ItemInfoRowError, "no level carries"):
            scale_stats(row, DPV, 2)
        with self.assertRaisesRegex(ItemInfoRowError, "i32"):
            set_stat_value(row, 0, DDD, 2**40)
        with self.assertRaisesRegex(ItemInfoRowError, "positive"):
            set_max_stack_count(row, 0)


class CloneTests(unittest.TestCase):
    def test_clone_rekeys_renames_and_swaps_hashes(self) -> None:
        template = parse_iteminfo_row(build_row())
        old_r = hashlittle(b"cd_phm_01_sword_0109_r", 0xC5EDE)
        new_r = hashlittle(b"cd_phm_01_sword_9109_r", 0xC5EDE)
        clone = clone_iteminfo_row(
            template,
            key=1990002,
            string_key="ZianeCloneB_OneHandSword",
            name_key="4300529299990021",
            desc_key="4300529299990022",
            replace_hashes={old_r: new_r},
        )
        row = parse_iteminfo_row(clone)
        self.assertEqual((row.key, row.string_key, row.name_key, row.desc_key), (1990002, "ZianeCloneB_OneHandSword", "4300529299990021", "4300529299990022"))
        self.assertEqual(clone.count(struct.pack("<I", 1990002)), 3)
        self.assertEqual(clone.count(struct.pack("<I", 1001295)), 0)
        self.assertEqual(clone.count(struct.pack("<I", new_r)), 1)
        self.assertEqual(clone.count(struct.pack("<I", old_r)), 0)
        # everything else survived: stats, prices, item type, memo, sockets
        self.assertEqual([lvl.stats[0].value for lvl in row.enchant_levels], [12000, 14000])
        self.assertEqual(row.price_list[0].price, 348)
        self.assertEqual((row.item_type, row.memo, row.socket_items), (103, "지안 한손검", (1002791,)))

    def test_clone_refusals(self) -> None:
        template = parse_iteminfo_row(build_row())
        with self.assertRaisesRegex(ItemInfoRowError, "different"):
            clone_iteminfo_row(template, key=1001295, string_key="x", name_key="1")
        with self.assertRaisesRegex(ItemInfoRowError, "description key"):
            clone_iteminfo_row(template, key=5, string_key="x", name_key="1")
        with self.assertRaisesRegex(ItemInfoRowError, "does not occur"):
            clone_iteminfo_row(template, key=5, string_key="x", name_key="1", desc_key="2", replace_hashes={12345: 1})
        with self.assertRaisesRegex(ItemInfoRowError, "positive"):
            clone_iteminfo_row(template, key=0, string_key="x", name_key="1", desc_key="2")
        # a template whose key appears elsewhere is refused rather than guessed at
        raw = build_row() + struct.pack("<I", 1001295)
        with self.assertRaisesRegex(ItemInfoRowError, "still appears"):
            clone_iteminfo_row(parse_iteminfo_row(raw), key=5, string_key="x", name_key="1", desc_key="2")


class RebuildTests(unittest.TestCase):
    """The stat block re-serialised from its parse, and shape edits through it."""

    def test_encode_reproduces_the_parsed_block(self) -> None:
        raw = build_row()
        row = parse_iteminfo_row(raw)
        self.assertEqual(encode_stat_block(row), raw[row.stat_block_offset:row.stat_block_end])
        self.assertEqual(rebuild_stat_block(row), raw)
        # extras, static-level entries and buffs survive the round trip too
        rich = _level(0, [(DPV, 2000)], [(COPPER, 4100)], level_stat_keys=(1000007,), buffs=(1000009,))
        raw2 = build_row(levels=[([(DPV, 2000)], [(COPPER, 1)])]).replace(_level(0, [(DPV, 2000)], [(COPPER, 1)]), rich)
        row2 = parse_iteminfo_row(raw2)
        self.assertEqual(encode_enchant_level(row2.enchant_levels[0]), rich)
        self.assertEqual(rebuild_stat_block(row2), raw2)

    def test_adding_a_level_a_stat_and_a_price(self) -> None:
        raw = build_row()
        row = parse_iteminfo_row(raw)
        levels = list(row.enchant_levels)
        levels[0] = level_with_stat(levels[0], 1000007, 500)          # a stat the template lacks
        levels[1] = level_with_stat(levels[1], DDD, 99000)            # an existing one, changed
        levels.append(level_with_buy_price(next_level_like(levels[-1]), 11, 777))
        prices = price_list_with(row.price_list, 11, 250)
        prices = price_list_with(prices, COPPER, 1)
        rebuilt = rebuild_stat_block(row, levels=levels, price_list=prices)
        # nothing outside the block moved
        self.assertEqual(rebuilt[: row.stat_block_offset], raw[: row.stat_block_offset])
        self.assertEqual(rebuilt[len(rebuilt) - (len(raw) - row.stat_block_end):], raw[row.stat_block_end:])
        again = parse_iteminfo_row(rebuilt)
        self.assertEqual([lvl.level for lvl in again.enchant_levels], [0, 1, 2])
        self.assertEqual([(s.status_key, s.value) for s in again.enchant_levels[0].stats], [(DDD, 12000), (1000007, 500)])
        self.assertEqual(again.stat(1, DDD).value, 99000)
        self.assertEqual(again.stat(2, DDD).value, 99000, "the new level copies the last one")
        self.assertEqual([(p.item_key, p.price) for p in again.enchant_levels[2].buy_prices], [(COPPER, 384), (CAMP_WEAPON, 19), (11, 777)])
        self.assertEqual([(p.item_key, p.price) for p in again.price_list], [(COPPER, 1), (CAMP_WEAPON, 17), (11, 250)])
        self.assertEqual(again.enchant_count, 3)
        # every rebuilt value is editable in place afterwards
        self.assertEqual(parse_iteminfo_row(set_stat_value(again, 2, DDD, 5)).stat(2, DDD).value, 5)

    def test_removing_stats_prices_and_levels(self) -> None:
        raw = build_row()
        row = parse_iteminfo_row(raw)
        levels = [level_without_stat(row.enchant_levels[0], DDD), level_without_buy_price(row.enchant_levels[1], CAMP_WEAPON)]
        prices = price_list_without(row.price_list, CAMP_WEAPON)
        again = parse_iteminfo_row(rebuild_stat_block(row, levels=levels, price_list=prices))
        self.assertEqual(again.enchant_levels[0].stats, ())
        self.assertEqual([p.item_key for p in again.enchant_levels[1].buy_prices], [COPPER])
        self.assertEqual([p.item_key for p in again.price_list], [COPPER])
        shorter = parse_iteminfo_row(rebuild_stat_block(row, levels=row.enchant_levels[:1]))
        self.assertEqual(shorter.enchant_count, 1)
        with self.assertRaisesRegex(ItemInfoRowError, "no stat"):
            level_without_stat(row.enchant_levels[0], DPV)
        with self.assertRaisesRegex(ItemInfoRowError, "no buy price"):
            level_without_buy_price(row.enchant_levels[0], 99)
        with self.assertRaisesRegex(ItemInfoRowError, "no entry"):
            price_list_without(row.price_list, 99)

    def test_socket_items_can_be_replaced_added_and_removed(self) -> None:
        raw = build_row()
        row = parse_iteminfo_row(raw)
        self.assertEqual(row.socket_items, (1002791,))
        four = parse_iteminfo_row(rebuild_stat_block(row, socket_items=(1002787, 1002793, 1002812, 1002910)))
        self.assertEqual(four.socket_items, (1002787, 1002793, 1002812, 1002910))
        # the byte after 0x11 is the count the game reads (a stale 3 under four gems showed three in game, 2026-08-18)
        self.assertEqual(four.stat_block_flags, (4, 1))
        self.assertEqual(row.stat_block_flags, (1, 1))
        def shape(item):
            return (
                [[(s.status_key, s.value) for s in level.stats] for level in item.enchant_levels],
                [[(p.item_key, p.price) for p in level.buy_prices] for level in item.enchant_levels],
                [(p.item_key, p.price) for p in item.price_list], item.add_socket_materials, item.item_type, item.memo,
            )
        self.assertEqual(shape(four), shape(row), "everything else in the block and the row survives")
        self.assertEqual(len(four.raw), len(raw) + 12)
        none = parse_iteminfo_row(rebuild_stat_block(row, socket_items=()))
        self.assertEqual(none.socket_items, ())
        self.assertEqual(none.stat_block_flags, (0, 1))
        self.assertEqual(none.enchant_count, row.enchant_count)
        self.assertEqual(rebuild_stat_block(row, socket_items=row.socket_items), raw, "the template's own list is a no-op")
        eight = parse_iteminfo_row(rebuild_stat_block(row, socket_items=tuple(1002785 + i for i in range(8))))
        self.assertEqual(len(eight.socket_items), 8, "the reader's limit")
        with self.assertRaisesRegex(ItemInfoRowError, "more than 8"):
            rebuild_stat_block(row, socket_items=tuple(1002785 + i for i in range(9)))
        with self.assertRaisesRegex(ItemInfoRowError, "positive u32"):
            rebuild_stat_block(row, socket_items=(0,))
        # socket slots (`_addSocketMaterialList`) grow with the shipped price progression
        self.assertEqual(socket_slots_for(row, 1), ((COPPER, 500, 0),), "already enough")
        self.assertEqual(socket_slots_for(row, 4), ((COPPER, 500, 0), (COPPER, 1000, 0), (COPPER, 2000, 0), (COPPER, 3000, 0)))
        grown = parse_iteminfo_row(rebuild_stat_block(row, socket_items=(1002787, 1002793, 1002812, 1002910), add_socket_materials=socket_slots_for(row, 4)))
        self.assertEqual((len(grown.socket_items), grown.add_socket_materials), (4, ((COPPER, 500, 0), (COPPER, 1000, 0), (COPPER, 2000, 0), (COPPER, 3000, 0))))
        self.assertEqual(shape(grown)[0], shape(row)[0], "the ladder is untouched")
        bare = parse_iteminfo_row(rebuild_stat_block(row, add_socket_materials=()))
        self.assertEqual(socket_slots_for(bare, 2), ((1, 500, 0), (1, 1000, 0)))
        self.assertEqual(bare.stat_block_flags, (1, 0), "no slots: the has-sockets byte drops")

    def test_rebuild_refusals(self) -> None:
        row = parse_iteminfo_row(build_row())
        with self.assertRaisesRegex(ItemInfoRowError, "0..n-1"):
            rebuild_stat_block(row, levels=[row.enchant_levels[1]])
        with self.assertRaisesRegex(ItemInfoRowError, "i32"):
            level_with_stat(row.enchant_levels[0], DDD, 2**40)
        with self.assertRaisesRegex(ItemInfoRowError, "u32"):
            level_with_buy_price(row.enchant_levels[0], COPPER, -1)
        with self.assertRaisesRegex(ItemInfoRowError, "u32"):
            price_list_with(row.price_list, COPPER, 2**32)
        with self.assertRaisesRegex(ItemInfoRowError, "six header bytes"):
            encode_enchant_level(EnchantLevel(level=0, stats=(), buy_prices=(), header_bytes=b"\x00"))
        with self.assertRaisesRegex(ItemInfoRowError, "25 bytes"):
            encode_enchant_level(EnchantLevel(level=0, stats=(), buy_prices=(), level_stat_keys=(1,), level_stat_entries=(b"\x00",)))
        no_block = parse_iteminfo_row(build_row().replace(bytes([0x11, 0x01, 0x01]), bytes([0x12, 0x01, 0x01])))
        with self.assertRaisesRegex(ItemInfoRowError, "no decoded stat block"):
            rebuild_stat_block(no_block)
        # a level built by hand still encodes
        fresh = EnchantLevel(level=0, stats=(StatValue(DDD, 1),), buy_prices=(PriceEntry(COPPER, 2),))
        self.assertEqual(len(encode_enchant_level(fresh)), 4 + 6 + 4 + 12 + 4 + 4 + 20 + 4 + 4)


class HelperTests(unittest.TestCase):
    def test_status_names_and_equip_type_key(self) -> None:
        rows = [(1000000, b"Hp"), (1000002, b"DDD"), (1000003, b"DPV")]
        payload = bytearray()
        directory = bytearray()
        for key, name in rows:
            directory += struct.pack("<II", key, len(payload))
            payload += struct.pack("<II", key, len(name)) + name + b"\x00" * 4
        header = struct.pack("<H", len(rows)) + bytes(directory)
        self.assertEqual(dict(parse_status_names(bytes(payload), header)), {1000000: "Hp", 1000002: "DDD", 1000003: "DPV"})
        self.assertEqual(equip_type_key("OneHandSword"), 0x5E703280)
        lines = describe_row(parse_iteminfo_row(build_row()), {DDD: "DDD"})
        self.assertIn("DDD=12000", lines[1])
        self.assertIn("price: 1:348", lines[-1])


@pytest.mark.real_game
class VanillaItemInfoTests(unittest.TestCase):
    """Every shipped row parses, and the stat block says what the equip types say."""

    def test_the_shipped_table_decodes_and_agrees_with_its_neighbours(self) -> None:
        from tools.placement_studio import corpus
        from cdmw.core.archive_extraction import read_archive_entry_data
        from cdmw.core.structured_binary_editor import parse_pabgh_table

        if not corpus.game_root().is_dir():
            self.skipTest("needs the installed game")
        wanted = {
            "gamedata/binary__/client/bin/iteminfo.pabgb", "gamedata/binary__/client/bin/iteminfo.pabgh",
            "gamedata/binary__/client/bin/equiptypeinfo.pabgb", "gamedata/binary__/client/bin/equiptypeinfo.pabgh",
        }
        found = {}
        for _package, entry in corpus._iter_archive_entries(corpus.game_root()):
            path = corpus.normalize_game_path(entry.path)
            if path in wanted:
                found[path.rsplit("/", 1)[-1]] = read_archive_entry_data(entry)[0]
        if len(found) != 4:
            self.skipTest("iteminfo/equiptypeinfo not found in the archives")
        table = parse_pabgh_table(found["iteminfo.pabgh"], payload=found["iteminfo.pabgb"])
        payload = found["iteminfo.pabgb"]
        spans = table.row_spans(len(payload))
        keys = {row.row_id for row, _s, _e in spans}
        equip = parse_pabgh_table(found["equiptypeinfo.pabgh"], payload=found["equiptypeinfo.pabgb"])
        equip_names = {}
        for row, start, _end in equip.row_spans(len(found["equiptypeinfo.pabgb"])):
            length = struct.unpack_from("<I", found["equiptypeinfo.pabgb"], start + 4)[0]
            equip_names[row.row_id] = found["equiptypeinfo.pabgb"][start + 8 : start + 8 + length].split(b"\x00", 1)[0].decode()
        weapons = {"OneHandSword", "TwoHandSword", "OneHandMace", "TwoHandPike", "TwoHandSpear", "OneHandDagger", "TwoHandAxe", "OneHandAxe", "OneHandCannon", "OneHandPistol", "TwoHandGiantSword", "OneHandBow"}
        parsed = 0
        with_block = 0
        weapon_ladders = 0
        types_by_equip: dict[str, set[int]] = {}
        for row, start, end in spans:
            item = parse_iteminfo_row(payload[start:end], item_keys=keys)
            parsed += 1
            self.assertEqual(item.key, row.row_id)
            if item.equip_type_key:
                self.assertEqual(equip_type_key(equip_names[item.equip_type_key]), item.equip_type_key)
            if item.stat_block_offset is not None:
                with_block += 1
            name = equip_names.get(item.equip_type_key, "")
            if item.item_type is not None and name in weapons:
                types_by_equip.setdefault(name, set()).add(item.item_type)
            if name in weapons and item.enchant_levels:
                weapon_ladders += 1
                self.assertIn(1000002, {s.status_key for s in item.enchant_levels[0].stats}, f"{item.string_key} has no DDD")
        self.assertEqual(parsed, len(spans))
        self.assertGreater(with_block, len(spans) * 0.9, "the stat block anchor should resolve on almost every row")
        self.assertGreater(weapon_ladders, 200)
        for name, types in types_by_equip.items():
            self.assertEqual(len(types), 1, f"{name} has more than one item type: {sorted(types)}")

    def test_every_shipped_stat_block_re_encodes_byte_for_byte(self) -> None:
        from tools.placement_studio import corpus
        from cdmw.core.archive_extraction import read_archive_entry_data
        from cdmw.core.structured_binary_editor import parse_pabgh_table

        if not corpus.game_root().is_dir():
            self.skipTest("needs the installed game")
        found = {}
        for _package, entry in corpus._iter_archive_entries(corpus.game_root()):
            path = corpus.normalize_game_path(entry.path)
            if path in ("gamedata/binary__/client/bin/iteminfo.pabgb", "gamedata/binary__/client/bin/iteminfo.pabgh"):
                found[path.rsplit(".", 1)[-1]] = read_archive_entry_data(entry)[0]
        if len(found) != 2:
            self.skipTest("iteminfo not found in the archives")
        table = parse_pabgh_table(found["pabgh"], payload=found["pabgb"])
        payload = found["pabgb"]
        spans = table.row_spans(len(payload))
        keys = {row.row_id for row, _s, _e in spans}
        checked = 0
        for row, start, end in spans:
            item = parse_iteminfo_row(payload[start:end], item_keys=keys)
            if item.stat_block_offset is None:
                continue
            self.assertEqual(encode_stat_block(item), item.raw[item.stat_block_offset:item.stat_block_end], item.string_key)
            self.assertEqual(rebuild_stat_block(item), item.raw, item.string_key)
            self.assertEqual(item.stat_block_flags, (len(item.socket_items), 1 if item.add_socket_materials else 0), f"{item.string_key}: the two bytes after 0x11 are the socket count and the has-sockets flag")
            checked += 1
        self.assertGreater(checked, 6000)


if __name__ == "__main__":
    unittest.main()
