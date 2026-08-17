from __future__ import annotations

import struct
import unittest
from unittest.mock import patch

import pytest

from cdmw.core.archive_format import hashlittle
from cdmw.core.stringinfo_table import (
    STRINGINFO_HASH_INIT,
    StringInfoFormatError,
    StringInfoRow,
    append_stringinfo_strings,
    build_stringinfo_row,
    parse_stringinfo,
    stringinfo_index,
    stringinfo_key,
)
from cdmw.core.structured_binary_editor import append_table_rows, parse_pabgh_table


def _table(texts: list[str]) -> tuple[bytes, bytes]:
    # Module-qualified lookups so a patched key function applies to the fixture too.
    from cdmw.core import stringinfo_table as owner

    payload = bytearray()
    directory = bytearray()
    for text in texts:
        directory += struct.pack("<II", owner.stringinfo_key(text), len(payload))
        payload += owner.build_stringinfo_row(text)
    header = struct.pack("<H", len(texts)) + bytes(directory)
    return bytes(payload), header


class StringInfoTests(unittest.TestCase):
    def test_key_is_hashlittle_with_the_game_seed(self) -> None:
        self.assertEqual(stringinfo_key("cd_phm_01_sword_0109_r"), hashlittle(b"cd_phm_01_sword_0109_r", STRINGINFO_HASH_INIT))
        self.assertEqual(stringinfo_key("cd_phm_01_sword_0109_r"), 0xA12E1FCD)

    def test_rows_parse_and_index(self) -> None:
        payload, header = _table(["rootlevel", "cd_phm_01_sword_0109_r", "狼の牙"])
        rows = parse_stringinfo(payload, header, name="synthetic")
        self.assertEqual(rows, (
            StringInfoRow(stringinfo_key("rootlevel"), "rootlevel"),
            StringInfoRow(0xA12E1FCD, "cd_phm_01_sword_0109_r"),
            StringInfoRow(stringinfo_key("狼の牙"), "狼の牙"),
        ))
        self.assertEqual(stringinfo_index(rows)[0xA12E1FCD], "cd_phm_01_sword_0109_r")

    def test_off_layout_rows_are_refused(self) -> None:
        payload, header = _table(["rootlevel", "cd_phm_01_sword_0109_r"])
        wrong_key = bytearray(payload)
        struct.pack_into("<I", wrong_key, 0, 12345)
        with self.assertRaisesRegex(StringInfoFormatError, "does not parse|directory key"):
            parse_stringinfo(bytes(wrong_key), header)
        padding = bytearray(payload)
        padding[4] = 1
        with self.assertRaisesRegex(StringInfoFormatError, "non-zero padding"):
            parse_stringinfo(bytes(padding), header)
        length = bytearray(payload)
        struct.pack_into("<I", length, 9, 3)
        with self.assertRaisesRegex(StringInfoFormatError, "declares 3"):
            parse_stringinfo(bytes(length), header)
        # a text that does not hash to its key is not a StringInfo row
        forged = struct.pack("<I5sI", stringinfo_key("a"), b"\0" * 5, 1) + b"b"
        header_forged = struct.pack("<HII", 1, stringinfo_key("a"), 0)
        with self.assertRaisesRegex(StringInfoFormatError, "not keyed by its own hash"):
            parse_stringinfo(forged, header_forged)

    def test_append_adds_only_what_is_missing_and_returns_every_key(self) -> None:
        payload, header = _table(["rootlevel", "cd_phm_01_sword_0109_r"])
        new_payload, new_header, keys = append_stringinfo_strings(
            payload, header, ["cd_phm_01_sword_9109_l", "cd_phm_01_sword_0109_r", "cd_phm_01_sword_9109_r", "cd_phm_01_sword_9109_l"]
        )
        self.assertEqual(keys, (
            stringinfo_key("cd_phm_01_sword_9109_l"), 0xA12E1FCD, stringinfo_key("cd_phm_01_sword_9109_r"), stringinfo_key("cd_phm_01_sword_9109_l"),
        ))
        rows = parse_stringinfo(new_payload, new_header)
        self.assertEqual([row.text for row in rows], ["rootlevel", "cd_phm_01_sword_0109_r", "cd_phm_01_sword_9109_l", "cd_phm_01_sword_9109_r"])
        self.assertEqual(new_payload[: len(payload)], payload, "existing rows keep their bytes and offsets")
        self.assertEqual(struct.unpack_from("<H", new_header, 0)[0], 4)
        # nothing to add leaves both buffers untouched
        same_payload, same_header, _keys = append_stringinfo_strings(new_payload, new_header, ["rootlevel"])
        self.assertEqual((same_payload, same_header), (new_payload, new_header))

    def test_a_hash_collision_is_refused_rather_than_written(self) -> None:
        # hashlittle collisions are not constructible on demand, so stand the key
        # function in with one that collides on purpose (length of the text).
        with patch("cdmw.core.stringinfo_table.stringinfo_key", side_effect=lambda text: len(str(text))):
            payload, header = _table(["alpha"])
            with self.assertRaisesRegex(StringInfoFormatError, "already names 'alpha'"):
                append_stringinfo_strings(payload, header, ["gamma"])
            with self.assertRaisesRegex(StringInfoFormatError, "both hash to"):
                append_stringinfo_strings(payload, header, ["beta", "zeta"])
            # the same text twice in one call is fine and yields one row
            new_payload, new_header, keys = append_stringinfo_strings(payload, header, ["beta", "beta"])
            self.assertEqual(keys, (4, 4))
            self.assertEqual(len(parse_stringinfo(new_payload, new_header)), 2)


class TableAppendTests(unittest.TestCase):
    """The generic .pabgb/.pabgh row append that StringInfo (and ItemInfo) rides on."""

    def test_appends_rows_to_an_8_byte_directory(self) -> None:
        payload, header = _table(["a", "bb"])
        row = build_stringinfo_row("ccc")
        new_payload, new_header = append_table_rows(payload, header, [row])
        table = parse_pabgh_table(new_header, payload=new_payload)
        self.assertEqual([r.row_id for r in table.rows], [stringinfo_key("a"), stringinfo_key("bb"), stringinfo_key("ccc")])
        self.assertEqual(table.rows[-1].offset, len(payload))
        self.assertEqual(new_payload[len(payload):], row)

    def test_appends_rows_to_a_2_byte_key_directory(self) -> None:
        # rows: u16 key, u32 len, name -- the itemgroupinfo/storeinfo shape
        def row(key: int, name: bytes) -> bytes:
            return struct.pack("<HI", key, len(name)) + name

        rows = [row(10, b"alpha"), row(11, b"beta")]
        payload = b"".join(rows)
        header = struct.pack("<H", 2) + struct.pack("<HI", 10, 0) + struct.pack("<HI", 11, len(rows[0]))
        table = parse_pabgh_table(header, payload=payload)
        self.assertEqual((table.key_width, table.header_size), (2, 2))
        new_payload, new_header = append_table_rows(payload, header, [row(12, b"gamma"), row(13, b"delta")])
        table = parse_pabgh_table(new_header, payload=new_payload)
        self.assertEqual([r.row_id for r in table.rows], [10, 11, 12, 13])
        self.assertEqual(table.key_width, 2)
        self.assertEqual(new_payload[table.rows[3].offset:], row(13, b"delta"))

    def test_refusals(self) -> None:
        payload, header = _table(["a", "bb"])
        with self.assertRaisesRegex(ValueError, "already holds"):
            append_table_rows(payload, header, [build_stringinfo_row("a")])
        with self.assertRaisesRegex(ValueError, "already holds"):
            append_table_rows(payload, header, [build_stringinfo_row("c"), build_stringinfo_row("c")])
        with self.assertRaisesRegex(ValueError, "shorter than"):
            append_table_rows(payload, header, [b"\x01"])
        # a 1-byte count cannot go past 255 rows
        one_byte_rows = [struct.pack("<BI", i, 4) + b"row!" for i in range(255)]
        one_payload = b"".join(one_byte_rows)
        offsets = [i * 9 for i in range(255)]
        one_header = struct.pack("<B", 255) + b"".join(struct.pack("<BI", i, o) for i, o in zip(range(255), offsets))
        with self.assertRaisesRegex(ValueError, "does not parse|do not fit|count"):
            append_table_rows(one_payload, one_header, [struct.pack("<BI", 255, 4) + b"row!"])


@pytest.mark.real_game
class VanillaStringInfoTests(unittest.TestCase):
    def test_every_shipped_row_is_keyed_by_its_own_hash(self) -> None:
        from tools.placement_studio import corpus
        from cdmw.core.archive_extraction import read_archive_entry_data

        if not corpus.game_root().is_dir():
            self.skipTest("needs the installed game")
        found = {}
        for _package, entry in corpus._iter_archive_entries(corpus.game_root()):
            path = corpus.normalize_game_path(entry.path)
            if path in ("gamedata/binary__/client/bin/stringinfo.pabgb", "gamedata/binary__/client/bin/stringinfo.pabgh"):
                found[path.rsplit(".", 1)[-1]] = entry
        if len(found) != 2:
            self.skipTest("stringinfo.pabgb/.pabgh not found in the archives")
        payload = read_archive_entry_data(found["pabgb"])[0]
        header = read_archive_entry_data(found["pabgh"])[0]
        rows = parse_stringinfo(payload, header, name="stringinfo")
        self.assertGreater(len(rows), 30_000)
        self.assertEqual(stringinfo_index(rows)[0xA12E1FCD], "cd_phm_01_sword_0109_r")


if __name__ == "__main__":
    unittest.main()
