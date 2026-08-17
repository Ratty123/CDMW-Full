"""Gates for the `itemgroupinfo.pabgb` row model."""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.core.itemgroupinfo_table import (  # noqa: E402
    ItemGroupError,
    add_group_members,
    apply_item_group_row,
    encode_item_group_row,
    groups_containing,
    parse_item_group_row,
    parse_item_group_table,
)


def _row(key: int, name: str, members: tuple[int, ...], *, subgroups: tuple[int, ...] = (), tail_extra: bytes = b"") -> bytes:
    raw = name.encode("ascii")
    digits = b"7284264533"
    out = struct.pack("<H", key) + struct.pack("<I", len(raw)) + raw + b"\x00" + bytes([8, 0x80, 0, 0, 0])
    out += struct.pack("<II", key, len(digits)) + digits
    out += struct.pack("<I", len(subgroups)) + b"".join(struct.pack("<H", s) for s in subgroups)
    out += struct.pack("<I", len(members)) + b"".join(struct.pack("<I", m) for m in members)
    out += struct.pack("<I", len(tail_extra)) + tail_extra + b"\xff\xff" + b"\x02" + struct.pack("<I", 0xEAC5E173) + struct.pack("<I", 0)
    return out


def _table(rows: list[bytes]) -> tuple[bytes, bytes]:
    payload = bytearray()
    header = bytearray(struct.pack("<H", len(rows)))
    for raw in rows:
        header += raw[:2] + struct.pack("<I", len(payload))
        payload += raw
    return bytes(payload), bytes(header)


class ItemGroupTests(unittest.TestCase):
    def test_parse_and_encode(self) -> None:
        raw = _row(17010, "ItemGroup_Equip_Weapon_OneHandSword", (240018, 1001295, 13800), subgroups=(17011, 17012))
        row = parse_item_group_row(raw, key=17010, item_keys={240018, 1001295, 13800})
        self.assertEqual((row.key, row.name), (17010, "ItemGroup_Equip_Weapon_OneHandSword"))
        self.assertEqual(row.subgroups, (17011, 17012))
        self.assertEqual(row.members, (240018, 1001295, 13800))
        self.assertEqual(len(row.tail), 15)
        self.assertEqual(encode_item_group_row(row), raw)
        self.assertEqual(struct.unpack_from("<I", raw, row.members_offset - 4)[0], 3)
        longer = _row(1, "ItemGroup_x", (5,), tail_extra=b"\x02\x02")
        self.assertEqual(len(parse_item_group_row(longer).tail), 17)
        empty = parse_item_group_row(_row(2, "ItemGroup_Empty", ()))
        self.assertEqual(empty.members, ())

    def test_refusals(self) -> None:
        raw = _row(17010, "ItemGroup_A", (240018,))
        with self.assertRaisesRegex(ItemGroupError, "directory key"):
            parse_item_group_row(raw, key=1)
        with self.assertRaisesRegex(ItemGroupError, "not item keys"):
            parse_item_group_row(raw, item_keys={1})
        with self.assertRaisesRegex(ItemGroupError, "08 80 tag"):
            parse_item_group_row(raw[:20] + b"\x01" + raw[21:])
        with self.assertRaisesRegex(ItemGroupError, "follow the member list"):
            parse_item_group_row(raw + b"\x00")
        row = parse_item_group_row(raw)
        with self.assertRaisesRegex(ItemGroupError, "already lists"):
            add_group_members(row, [240018])
        with self.assertRaisesRegex(ItemGroupError, "does not list"):
            add_group_members(row, [7], after=99)
        with self.assertRaisesRegex(ItemGroupError, "twice"):
            add_group_members(row, [7, 7])
        self.assertIs(add_group_members(row, []), row)

    def test_add_and_apply(self) -> None:
        payload, header = _table([_row(17010, "ItemGroup_A", (240018, 1001295, 13800)), _row(17011, "ItemGroup_B", (1001295,))])
        rows = parse_item_group_table(payload, header, item_keys={240018, 1001295, 13800})
        self.assertEqual([r.key for r in groups_containing(rows, 1001295)], [17010, 17011])
        grown = add_group_members(rows[0], [1990000], after=1001295)
        self.assertEqual(grown.members, (240018, 1001295, 1990000, 13800))
        appended = add_group_members(rows[1], [1990000, 1990001])
        self.assertEqual(appended.members, (1001295, 1990000, 1990001))
        payload, header = apply_item_group_row(payload, header, grown)
        payload, header = apply_item_group_row(payload, header, appended)
        again = parse_item_group_table(payload, header)
        self.assertEqual([r.members for r in again], [(240018, 1001295, 1990000, 13800), (1001295, 1990000, 1990001)])
        self.assertEqual(again[0].tail, rows[0].tail)
        self.assertEqual(again[1].prefix, rows[1].prefix)


@pytest.mark.real_game
class VanillaItemGroupTests(unittest.TestCase):
    def test_every_shipped_group_round_trips_and_lists_only_items(self) -> None:
        from tools.placement_studio import corpus
        from cdmw.core.archive_extraction import read_archive_entry_data
        from cdmw.core.structured_binary_editor import parse_pabgh_table

        if not corpus.game_root().is_dir():
            self.skipTest("needs the installed game")
        wanted = {
            "gamedata/binary__/client/bin/itemgroupinfo.pabgb", "gamedata/binary__/client/bin/itemgroupinfo.pabgh",
            "gamedata/binary__/client/bin/iteminfo.pabgb", "gamedata/binary__/client/bin/iteminfo.pabgh",
        }
        found = {}
        for _package, entry in corpus._iter_archive_entries(corpus.game_root()):
            path = corpus.normalize_game_path(entry.path)
            if path in wanted:
                found[path.rsplit("/", 1)[-1]] = read_archive_entry_data(entry)[0]
        if len(found) != 4:
            self.skipTest("tables not found in the archives")
        item_keys = {row.row_id for row, _s, _e in parse_pabgh_table(found["iteminfo.pabgh"], payload=found["iteminfo.pabgb"]).row_spans(len(found["iteminfo.pabgb"]))}
        rows = parse_item_group_table(found["itemgroupinfo.pabgb"], found["itemgroupinfo.pabgh"], item_keys=item_keys)
        self.assertGreater(len(rows), 1500)
        for row in rows:
            self.assertEqual(encode_item_group_row(row), row.raw, row.name)
        ziane = groups_containing(rows, 1001295)
        self.assertEqual(len(ziane), 11, [g.name for g in ziane])
        self.assertIn("ItemGroup_Equip_Weapon_OneHandSword", [g.name for g in ziane])


if __name__ == "__main__":
    unittest.main()
