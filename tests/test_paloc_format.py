"""Gates for the `.paloc` string table reader and writer."""

from __future__ import annotations

from pathlib import Path
import struct
import sys
import unittest

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.core.paloc_format import (  # noqa: E402
    LocalizationEntry,
    LocalizationTable,
    PalocFormatError,
    describe_categories,
    encode_paloc,
    parse_paloc,
    rebuild_is_exact,
    replace_text,
)


def _table(*rows: tuple[int, str, str]) -> LocalizationTable:
    return LocalizationTable(
        entries=tuple(LocalizationEntry(category=c, key=k, text=t) for c, k, t in rows)
    )


class RoundTripTests(unittest.TestCase):
    def test_a_table_round_trips(self) -> None:
        table = _table((38, "questdialog_main_00001", "Hello."), (9, "262897", "Unavailable."))
        data = encode_paloc(table)
        self.assertEqual(parse_paloc(data), table)
        self.assertTrue(rebuild_is_exact(data))

    def test_the_count_is_a_footer(self) -> None:
        data = encode_paloc(_table((1, "a1", "x"), (1, "b2", "y"), (1, "c3", "z")))
        self.assertEqual(struct.unpack_from("<I", data, len(data) - 4)[0], 3)

    def test_an_empty_table_is_just_the_footer(self) -> None:
        data = encode_paloc(LocalizationTable(entries=()))
        self.assertEqual(data, struct.pack("<I", 0))
        self.assertEqual(len(parse_paloc(data)), 0)

    def test_empty_text_is_preserved(self) -> None:
        data = encode_paloc(_table((3, "key", "")))
        self.assertEqual(parse_paloc(data).entries[0].text, "")

    def test_non_ascii_text_survives(self) -> None:
        for text in ("Grüße, Reisender", "회색 갈기", "Приветствую", "日本語テキスト"):
            with self.subTest(text=text):
                data = encode_paloc(_table((3, "k", text)))
                self.assertEqual(parse_paloc(data).entries[0].text, text)
                self.assertTrue(rebuild_is_exact(data))

    def test_named_and_numeric_keys_both_work(self) -> None:
        table = _table((38, "questdialog_pywel_akapen_00985", "a"), (9, "4294967344", "b"))
        self.assertEqual(parse_paloc(encode_paloc(table)), table)


class EditTests(unittest.TestCase):
    def test_a_translation_may_change_length(self) -> None:
        table = _table((38, "k1", "Short"), (38, "k2", "Keep"))
        edited, missing = replace_text(table, {"k1": "A considerably longer line of dialogue."})
        self.assertEqual(missing, ())
        self.assertEqual(edited.index()["k1"].text, "A considerably longer line of dialogue.")
        self.assertEqual(edited.index()["k2"].text, "Keep")
        # The whole point of the format: nothing downstream is offset-addressed.
        self.assertEqual(parse_paloc(encode_paloc(edited)), edited)

    def test_unknown_keys_are_reported_not_added(self) -> None:
        table = _table((1, "k1", "a"))
        edited, missing = replace_text(table, {"nope": "b"})
        self.assertEqual(missing, ("nope",))
        self.assertEqual(len(edited), 1)

    def test_categories_are_described_from_the_data(self) -> None:
        table = _table(
            (38, "questdialog_a", "x"),
            (38, "questdialog_b", "y"),
            (9, "12345", "z"),
        )
        described = describe_categories(table)
        self.assertEqual(described[38], "questdialog")
        self.assertEqual(described[9], "(numeric)")


class RejectionTests(unittest.TestCase):
    def test_a_short_buffer_is_refused(self) -> None:
        with self.assertRaises(PalocFormatError):
            parse_paloc(b"\x00")

    def test_a_lying_footer_is_refused(self) -> None:
        data = bytearray(encode_paloc(_table((1, "k", "v"))))
        data[-4:] = struct.pack("<I", 99)
        with self.assertRaises(PalocFormatError):
            parse_paloc(bytes(data))

    def test_a_record_running_past_the_end_is_refused(self) -> None:
        data = struct.pack("<III", 1, 0, 9999) + b"ab" + struct.pack("<I", 1)
        with self.assertRaises(PalocFormatError):
            parse_paloc(data)

    def test_non_utf8_is_refused(self) -> None:
        body = struct.pack("<III", 1, 0, 2) + b"\xff\xfe" + struct.pack("<I", 0)
        with self.assertRaises(PalocFormatError):
            parse_paloc(body + struct.pack("<I", 1))

    def test_rebuild_is_exact_says_no_rather_than_raising(self) -> None:
        self.assertFalse(rebuild_is_exact(b"not a table"))


@pytest.mark.real_game
class VanillaRoundTripTests(unittest.TestCase):
    """Round-trip a shipped string table straight out of the archives."""

    def test_a_shipped_table_rebuilds_byte_for_byte(self) -> None:
        from tools.placement_studio import corpus
        from cdmw.core.archive_extraction import read_archive_entry_data

        if not corpus.game_root().is_dir():
            self.skipTest("needs the installed game")
        smallest = None
        for _package, entry in corpus._iter_archive_entries(corpus.game_root()):
            path = corpus.normalize_game_path(entry.path)
            if not path.endswith(".paloc"):
                continue
            size = int(getattr(entry, "orig_size", 0) or 0)
            if smallest is None or size < smallest[0]:
                smallest = (size, path, entry)
        if smallest is None:
            self.skipTest("no .paloc entries in the archives")
        _size, path, entry = smallest
        data, _decompressed, _note = read_archive_entry_data(entry)
        table = parse_paloc(data, name=path)
        self.assertGreater(len(table), 100_000, "a shipped table holds every line in the game")
        self.assertEqual(encode_paloc(table), data)
