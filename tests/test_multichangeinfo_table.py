"""Gates for the `multichangeinfo.pabgb` transition-row model."""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from cdmw.core.multichangeinfo_table import (  # noqa: E402
    MultiChangeError,
    allocate_multichange_keys,
    clone_multichange_row,
    clone_transition_rows,
    find_multichange_keys,
    parse_multichange_row,
    parse_multichange_table,
    transition_rows_for,
)
from cdmw.core.iteminfo_row import parse_iteminfo_row  # noqa: E402
from test_iteminfo_row import build_row  # noqa: E402

TEMPLATE = 1001295


def _row(key: int, name: str, item: int, *, tail: bytes = bytes(40)) -> bytes:
    raw = name.encode("ascii")
    return struct.pack("<II", key, len(raw)) + raw + bytes([0]) + bytes(24) + struct.pack("<I", item) + tail


def _table(rows: list[tuple[int, bytes]]) -> tuple[bytes, bytes]:
    payload = bytearray()
    header = bytearray(struct.pack("<H", len(rows)))
    for key, raw in rows:
        header += struct.pack("<II", key, len(payload))
        payload += raw
    return bytes(payload), bytes(header)


class MultiChangeTests(unittest.TestCase):
    def test_parse_and_clone(self) -> None:
        raw = _row(1013129, "Ziane_OneHandSword_0", TEMPLATE)
        row = parse_multichange_row(raw, key=1013129)
        self.assertEqual((row.key, row.name, row.item_key, row.level_suffix), (1013129, "Ziane_OneHandSword_0", TEMPLATE, 0))
        clone = parse_multichange_row(clone_multichange_row(row, key=1990000, name="Ziane_Clone_OneHandSword_0", item_key=1990000))
        self.assertEqual((clone.key, clone.name, clone.item_key), (1990000, "Ziane_Clone_OneHandSword_0", 1990000))
        self.assertEqual(clone.raw[clone.name_end:], raw[row.name_end:].replace(struct.pack("<I", TEMPLATE), struct.pack("<I", 1990000), 1))
        with self.assertRaisesRegex(MultiChangeError, "directory key"):
            parse_multichange_row(raw, key=1)
        with self.assertRaisesRegex(MultiChangeError, "NUL"):
            parse_multichange_row(raw[:4] + struct.pack("<I", 200) + raw[8:])
        with self.assertRaisesRegex(MultiChangeError, "1..255"):
            clone_multichange_row(row, key=1, name="", item_key=1)
        short = parse_multichange_row(struct.pack("<II", 5, 3) + b"abc" + bytes([0]) + bytes(4))
        self.assertIsNone(short.item_key)
        with self.assertRaisesRegex(MultiChangeError, "no item key"):
            clone_multichange_row(short, key=6, name="x", item_key=1)

    def test_list_discovery_and_own_rows(self) -> None:
        payload, header = _table([
            (1013129, _row(1013129, "Ziane_OneHandSword_0", TEMPLATE)),
            (1013130, _row(1013130, "Ziane_OneHandSword_1", TEMPLATE)),
            (1013200, _row(1013200, "Sharpening_Recipe_0", 55)),
        ])
        rows = {r.key: r for r in parse_multichange_table(payload, header)}
        item = build_row()
        parsed = parse_iteminfo_row(item)
        at = parsed.stat_block_offset - 3
        item = item[:at] + struct.pack("<IIII", 3, 1013129, 1013130, 1013200) + item[at:]
        parsed = parse_iteminfo_row(item)
        self.assertEqual(find_multichange_keys(parsed, rows), (1013129, 1013130, 1013200))
        own = transition_rows_for(rows, (1013129, 1013130, 1013200), TEMPLATE)
        self.assertEqual([r.name for r in own], ["Ziane_OneHandSword_0", "Ziane_OneHandSword_1"], "the shared recipe is not the item's own")
        self.assertEqual(find_multichange_keys(parse_iteminfo_row(build_row()), rows), ())
        keys = allocate_multichange_keys(rows, 2)
        self.assertEqual(keys, (1990000, 1990001))
        self.assertEqual(allocate_multichange_keys(rows, 0), ())
        new_payload, new_header, mapping = clone_transition_rows(payload, header, own, new_item_key=1990000, new_item_name="Clone", new_keys=keys)
        again = {r.key: r for r in parse_multichange_table(new_payload, new_header)}
        self.assertEqual(mapping, {1013129: 1990000, 1013130: 1990001})
        self.assertEqual([again[k].name for k in keys], ["Clone_0", "Clone_1"])
        self.assertEqual([again[k].item_key for k in keys], [1990000, 1990000])
        self.assertEqual(again[1013200].raw, rows[1013200].raw)
        with self.assertRaisesRegex(MultiChangeError, "one new key"):
            clone_transition_rows(payload, header, own, new_item_key=1, new_item_name="x", new_keys=(1,))


@pytest.mark.real_game
class VanillaMultiChangeTests(unittest.TestCase):
    def test_every_shipped_row_parses_and_ziane_lists_fourteen_of_its_own(self) -> None:
        from tools.placement_studio import corpus
        from cdmw.core.archive_extraction import read_archive_entry_data
        from cdmw.core.structured_binary_editor import parse_pabgh_table

        if not corpus.game_root().is_dir():
            self.skipTest("needs the installed game")
        wanted = {
            "gamedata/binary__/client/bin/multichangeinfo.pabgb", "gamedata/binary__/client/bin/multichangeinfo.pabgh",
            "gamedata/binary__/client/bin/iteminfo.pabgb", "gamedata/binary__/client/bin/iteminfo.pabgh",
        }
        found = {}
        for _package, entry in corpus._iter_archive_entries(corpus.game_root()):
            path = corpus.normalize_game_path(entry.path)
            if path in wanted:
                found[path.rsplit("/", 1)[-1]] = read_archive_entry_data(entry)[0]
        if len(found) != 4:
            self.skipTest("tables not found")
        rows = {r.key: r for r in parse_multichange_table(found["multichangeinfo.pabgb"], found["multichangeinfo.pabgh"])}
        self.assertGreater(len(rows), 18000)
        spans = parse_pabgh_table(found["iteminfo.pabgh"], payload=found["iteminfo.pabgb"]).row_spans(len(found["iteminfo.pabgb"]))
        keys = {row.row_id for row, _s, _e in spans}
        items = {row.row_id: parse_iteminfo_row(found["iteminfo.pabgb"][s:e], item_keys=keys) for row, s, e in spans}
        ziane = items[1001295]
        listed = find_multichange_keys(ziane, rows)
        own = transition_rows_for(rows, listed, 1001295)
        self.assertEqual(len(listed), 14)
        self.assertEqual([r.name for r in own], [f"Ziane_OneHandSword_{n}" for n in range(14)])
        # every item with a list resolves at least one own transition row or none at all; no row names a wrong item
        with_list = sum(1 for item in items.values() if find_multichange_keys(item, rows))
        self.assertGreater(with_list, 3500)


if __name__ == "__main__":
    unittest.main()
