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
    add_localization_entries,
    describe_categories,
    encode_paloc,
    entries_like,
    language_of_paloc_path,
    parse_paloc,
    rebuild_is_exact,
    replace_text,
    text_for_language,
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


class AddTests(unittest.TestCase):
    """New records for a new item, slotted into the numeric order the shipped tables keep."""

    def test_new_records_keep_the_numeric_order_shaped_like_the_template(self) -> None:
        # Wolf's Fang (1001295) name and description, then a later item's, as shipped.
        table = _table((7, "4300529278648432", "Wolf's Fang"), (8, "4300529278648433", "A sword."), (7, "4300533573615728", "Boots"))
        added = add_localization_entries(
            table,
            entries_like(table, "4300529278648432", {"8546989214007408": "Clone A"})    # 1990001 << 32 | 0x70
            + entries_like(table, "4300529278648433", {"4300529278648500": "Fan"}),     # between the sword and the boots
        )
        self.assertEqual(len(added), 5)
        self.assertEqual([entry.key for entry in added.entries], ["4300529278648432", "4300529278648433", "4300529278648500", "4300533573615728", "8546989214007408"])
        self.assertEqual(added.entries[2], LocalizationEntry(8, "4300529278648500", "Fan"))
        self.assertEqual(added.entries[4], LocalizationEntry(7, "8546989214007408", "Clone A"))
        self.assertEqual(parse_paloc(encode_paloc(added)), added)

    def test_two_new_keys_bound_for_the_same_gap_stay_ordered(self) -> None:
        table = _table((7, "100", "a"), (38, "questdialog_x", "q"), (7, "900", "z"), (38, "questdialog_y", "q"))
        added = add_localization_entries(table, [LocalizationEntry(7, "500", "big"), LocalizationEntry(7, "300", "small"), LocalizationEntry(7, "950", "last"), LocalizationEntry(7, "940", "penultimate")])
        self.assertEqual([entry.key for entry in added.entries], ["100", "questdialog_x", "300", "500", "900", "940", "950", "questdialog_y"])

    def test_named_keys_append_and_an_out_of_order_tail_is_left_alone(self) -> None:
        table = _table((7, "100", "a"), (7, "900", "z"))
        added = add_localization_entries(table, [LocalizationEntry(38, "questdialog_new", "q"), LocalizationEntry(7, "500", "m")])
        self.assertEqual([entry.key for entry in added.entries], ["100", "500", "900", "questdialog_new"])
        # an earlier mod appended 300 at the end: the shipped order is the leading run, and the tail is neither moved nor trusted
        tailed = _table((7, "100", "a"), (7, "900", "z"), (7, "300", "mod"))
        added = add_localization_entries(tailed, [LocalizationEntry(7, "500", "m"), LocalizationEntry(7, "950", "n")])
        self.assertEqual([entry.key for entry in added.entries], ["100", "500", "900", "950", "300"])
        self.assertEqual([entry.key for entry in add_localization_entries(_table((38, "only_named", "x")), [LocalizationEntry(7, "5", "m")]).entries], ["only_named", "5"])

    def test_duplicate_and_empty_keys_are_refused(self) -> None:
        table = _table((7, "a", "A"))
        with self.assertRaisesRegex(PalocFormatError, "already exists"):
            add_localization_entries(table, [LocalizationEntry(7, "a", "again")])
        with self.assertRaisesRegex(PalocFormatError, "repeated"):
            add_localization_entries(table, [LocalizationEntry(7, "b", "1"), LocalizationEntry(7, "b", "2")])
        with self.assertRaisesRegex(PalocFormatError, "empty"):
            add_localization_entries(table, [LocalizationEntry(7, "", "x")])
        with self.assertRaisesRegex(PalocFormatError, "template key"):
            entries_like(table, "missing", {"c": "C"})
        self.assertEqual(add_localization_entries(table, []), table)

    def test_language_helpers(self) -> None:
        self.assertEqual(language_of_paloc_path("gamedata/stringtable/binary__/localizationstring_por-br.paloc"), "por-br")
        self.assertEqual(language_of_paloc_path("localizationstring_eng.PALOC"), "eng")
        self.assertEqual(language_of_paloc_path("gamedata/x/other.pabgb"), "")
        self.assertEqual(language_of_paloc_path("nounderscore.paloc"), "")
        texts = {"eng": "Wolf's Fang", "ger": "Wolfszahn", "fre": "  "}
        self.assertEqual(text_for_language(texts, "ger"), "Wolfszahn")
        self.assertEqual(text_for_language(texts, "fre"), "Wolf's Fang", "blank falls back")
        self.assertEqual(text_for_language(texts, "jpn"), "Wolf's Fang")
        self.assertEqual(text_for_language({}, "jpn"), "")


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
