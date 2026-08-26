from __future__ import annotations

import struct
import unittest

import pytest

from cdmw.core.pappt_format import (
    HeadPrefabRecord,
    PapptFormatError,
    PapptLayoutError,
    PartPrefabPart,
    PartPrefabRecord,
    PartPrefabTable,
    describe_folders,
    encode_pappt,
    insert_part_prefabs,
    parse_pappt,
    rebuild_is_exact,
)


def _s(text: str) -> bytes:
    raw = text.encode("utf-8") + b"\x00"
    return bytes([len(raw)]) + raw


SOCKETS = "character/descriptors/socketbonedata/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0001_r.sockets.xml"


def _sword(stem: str, part: str) -> PartPrefabRecord:
    return PartPrefabRecord(
        stem=stem,
        folder="1_pc/01_phm/weapon/01_onehandweapon",
        sockets_path=SOCKETS,
        extra="",
        flag=1,
        parts=(PartPrefabPart(part, 1),),
    )


def _synthetic_bytes(*, tag_prefix: bytes = b"") -> bytes:
    """Hand-built bytes in either shipped shape: two swords, one hand and one head."""

    out = bytearray(b"\x00" * 8)
    out += struct.pack("<I", 3)
    out += _s("cd_phm_01_sword_0109_l") + _s("1_pc/01_phm/weapon/01_onehandweapon") + _s(SOCKETS) + tag_prefix + _s("")
    out += bytes([1, 1]) + _s("CD_MainWeapon_Sword_L") + bytes([1])
    out += _s("cd_phm_01_sword_0109_r") + _s("1_pc/01_phm/weapon/01_onehandweapon") + _s(SOCKETS) + tag_prefix + _s("")
    out += bytes([1, 1]) + _s("CD_MainWeapon_Sword_R") + bytes([1])
    out += _s("cd_phm_00_hand_0078_02") + _s("1_pc/01_phm/armor/11_hand") + _s("x.sockets.xml") + tag_prefix + _s("Empty")
    out += bytes([0, 2]) + _s("CD_Hand") + bytes([1]) + _s("CD_Hand_Acc") + bytes([0])
    out += struct.pack("<I", 1)
    out += _s("cd_phm_00_head_00_0001") + _s("1_pc/01_phm/head/head")
    return bytes(out)


class PapptParseEncodeTests(unittest.TestCase):
    def test_parses_the_shipped_shape_and_rebuilds_it_exactly(self) -> None:
        data = _synthetic_bytes()
        table = parse_pappt(data, name="synthetic")
        self.assertEqual(len(table), 3)
        self.assertEqual(table.records[0], _sword("cd_phm_01_sword_0109_l", "CD_MainWeapon_Sword_L"))
        self.assertEqual(table.records[1].prefab_path, "character/bin__/prefab/1_pc/01_phm/weapon/01_onehandweapon/cd_phm_01_sword_0109_r.prefab")
        hand = table.records[2]
        self.assertEqual((hand.extra, hand.flag), ("Empty", 0))
        self.assertEqual(hand.parts, (PartPrefabPart("CD_Hand", 1), PartPrefabPart("CD_Hand_Acc", 0)))
        self.assertEqual(table.head_records, (HeadPrefabRecord("cd_phm_00_head_00_0001", "1_pc/01_phm/head/head"),))
        self.assertEqual(encode_pappt(table), data)
        self.assertTrue(rebuild_is_exact(data))
        self.assertEqual(describe_folders(table), {"1_pc/01_phm/weapon/01_onehandweapon": 2, "1_pc/01_phm/armor/11_hand": 1})

    def test_index_and_find(self) -> None:
        table = parse_pappt(_synthetic_bytes())
        self.assertIs(table.find("cd_phm_01_sword_0109_r"), table.records[1])
        self.assertIsNone(table.find("nope"))
        self.assertEqual(set(table.index()), {"cd_phm_01_sword_0109_l", "cd_phm_01_sword_0109_r", "cd_phm_00_hand_0078_02"})

    def test_game_200_record_prefix_round_trips_and_is_kept_for_inserted_records(self) -> None:
        data = _synthetic_bytes(tag_prefix=b"\x01")
        table = parse_pappt(data, name="game 2.00.00 synthetic")
        self.assertEqual(table.tag_prefix, b"\x01")
        self.assertEqual(encode_pappt(table), data)

        template = table.find("cd_phm_01_sword_0109_r")
        assert template is not None
        extended = insert_part_prefabs(
            table,
            (template.cloned("cd_phm_01_sword_9109_r"),),
            after_stem=template.stem,
        )
        rebuilt = encode_pappt(extended)
        self.assertEqual(parse_pappt(rebuilt), extended)

    def test_an_empty_table_round_trips(self) -> None:
        empty = PartPrefabTable(records=(), head_records=())
        self.assertEqual(parse_pappt(encode_pappt(empty)), empty)

    def test_truncated_and_off_layout_input_is_refused(self) -> None:
        data = _synthetic_bytes()
        with self.assertRaises(PapptFormatError):
            parse_pappt(data[:-1])
        with self.assertRaises(PapptFormatError):
            parse_pappt(data + b"\x00")
        broken = bytearray(data)
        broken[12] = 0  # a zero-length string cannot even hold its NUL
        with self.assertRaisesRegex(PapptFormatError, "length 0"):
            parse_pappt(bytes(broken))
        not_terminated = bytearray(data)
        not_terminated[13 + len("cd_phm_01_sword_0109_l")] = 0x41
        with self.assertRaisesRegex(PapptFormatError, "NUL-terminated"):
            parse_pappt(bytes(not_terminated))
        with self.assertRaises(PapptFormatError):
            parse_pappt(b"\x00" * 8)
        with self.assertRaisesRegex(PapptLayoutError, "unsupported part-prefab table layout"):
            parse_pappt(b"not a table")
        self.assertFalse(rebuild_is_exact(b"not a table"))

    def test_encode_refuses_what_the_format_cannot_hold(self) -> None:
        long_stem = _sword("s" * 255, "CD_MainWeapon_Sword_R")
        with self.assertRaisesRegex(PapptFormatError, "255"):
            encode_pappt(PartPrefabTable(records=(long_stem,)))
        wide_flag = PartPrefabRecord(stem="a", folder="b", sockets_path="c", flag=300)
        with self.assertRaisesRegex(PapptFormatError, "does not fit a byte"):
            encode_pappt(PartPrefabTable(records=(wide_flag,)))
        with self.assertRaisesRegex(PapptFormatError, "eight bytes"):
            encode_pappt(PartPrefabTable(records=(), reserved=b"\x00"))
        with self.assertRaisesRegex(PapptFormatError, "tag prefix"):
            encode_pappt(PartPrefabTable(records=(), tag_prefix=b"\x02"))


class PapptInsertTests(unittest.TestCase):
    def test_cloned_records_slot_in_after_their_template(self) -> None:
        table = parse_pappt(_synthetic_bytes())
        template_l = table.find("cd_phm_01_sword_0109_l")
        template_r = table.find("cd_phm_01_sword_0109_r")
        assert template_l is not None and template_r is not None
        new = insert_part_prefabs(
            table,
            (template_l.cloned("cd_phm_01_sword_9109_l"), template_r.cloned("cd_phm_01_sword_9109_r")),
            after_stem="cd_phm_01_sword_0109_r",
        )
        stems = [record.stem for record in new.records]
        self.assertEqual(stems, ["cd_phm_01_sword_0109_l", "cd_phm_01_sword_0109_r", "cd_phm_01_sword_9109_l", "cd_phm_01_sword_9109_r", "cd_phm_00_hand_0078_02"])
        clone = new.find("cd_phm_01_sword_9109_r")
        assert clone is not None
        self.assertEqual((clone.folder, clone.sockets_path, clone.parts), (template_r.folder, template_r.sockets_path, template_r.parts))
        self.assertEqual(clone.prefab_path, "character/bin__/prefab/1_pc/01_phm/weapon/01_onehandweapon/cd_phm_01_sword_9109_r.prefab")
        # the original table is untouched and the new one re-parses
        self.assertEqual(len(table), 3)
        self.assertEqual(parse_pappt(encode_pappt(new)), new)
        self.assertEqual(new.head_records, table.head_records)

    def test_appending_without_an_anchor_goes_to_the_end(self) -> None:
        table = parse_pappt(_synthetic_bytes())
        new = insert_part_prefabs(table, (_sword("cd_phm_01_sword_9109_r", "CD_MainWeapon_Sword_R"),))
        self.assertEqual(new.records[-1].stem, "cd_phm_01_sword_9109_r")
        self.assertIs(insert_part_prefabs(table, ()), table)

    def test_duplicate_or_malformed_stems_are_refused(self) -> None:
        table = parse_pappt(_synthetic_bytes())
        with self.assertRaisesRegex(PapptFormatError, "already in the table"):
            insert_part_prefabs(table, (_sword("cd_phm_01_sword_0109_r", "CD_MainWeapon_Sword_R"),))
        with self.assertRaisesRegex(PapptFormatError, "given twice"):
            insert_part_prefabs(table, (_sword("new_a", "P"), _sword("new_a", "P")))
        with self.assertRaisesRegex(PapptFormatError, "bare file stem"):
            insert_part_prefabs(table, (_sword("folder/new_a", "P"),))
        with self.assertRaisesRegex(PapptFormatError, "nothing to insert after"):
            insert_part_prefabs(table, (_sword("new_a", "P"),), after_stem="missing")
        with self.assertRaises(TypeError):
            insert_part_prefabs(table, ("not a record",))  # type: ignore[arg-type]


@pytest.mark.real_game
class VanillaPapptTests(unittest.TestCase):
    """The shipped table straight out of the archives."""

    def test_the_shipped_table_parses_to_the_last_byte_and_rebuilds_exactly(self) -> None:
        from tools.placement_studio import corpus
        from cdmw.core.archive_extraction import read_archive_entry_data

        if not corpus.game_root().is_dir():
            self.skipTest("needs the installed game")
        found = None
        for _package, entry in corpus._iter_archive_entries(corpus.game_root()):
            if corpus.normalize_game_path(entry.path) == "character/bin__/partprefabtable.pappt":
                found = entry
                break
        if found is None:
            self.skipTest("no partprefabtable.pappt in the archives")
        data, _decompressed, _note = read_archive_entry_data(found)
        table = parse_pappt(data, name="partprefabtable.pappt")
        self.assertGreater(len(table), 10_000, "the shipped table names every part prefab")
        self.assertGreater(len(table.head_records), 1_000)
        self.assertEqual(encode_pappt(table), data)
        stems = [record.stem for record in table.records]
        self.assertEqual(len(set(stems)), len(stems), "stems are unique, which is what makes them a key")
        sword = table.find("cd_phm_01_sword_0109_r")
        assert sword is not None
        self.assertEqual(sword.folder, "1_pc/01_phm/weapon/01_onehandweapon")
        self.assertEqual([part.name for part in sword.parts], ["CD_MainWeapon_Sword_R"])


if __name__ == "__main__":
    unittest.main()
