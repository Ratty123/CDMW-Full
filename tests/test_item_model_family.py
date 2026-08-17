"""Gates for model family discovery: ItemInfo row -> owned/borrowed parts -> files."""

from __future__ import annotations

import struct
import sys
import types
import unittest
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from cdmw.core.item_model_family import (  # noqa: E402
    ItemModelFamilyError,
    discover_item_model_family,
    find_icon_string,
    find_part_stems,
)
from cdmw.core.pappt_format import PartPrefabPart, PartPrefabRecord, PartPrefabTable  # noqa: E402
from cdmw.core.prefab_binary_edit import rewrite_prefab_paths_any_length  # noqa: E402
from cdmw.core.stringinfo_table import stringinfo_key  # noqa: E402
from test_prefab_binary_edit import _build as build_prefab  # noqa: E402

FOLDER = "1_pc/01_phm/weapon/01_onehandweapon"
MODEL_FOLDER = "1_pc/1_phm/weapon/1_onehandweapon"


def _record(stem: str, part: str = "CD_MainWeapon_Sword_R", folder: str = FOLDER) -> PartPrefabRecord:
    return PartPrefabRecord(stem=stem, folder=folder, sockets_path="x.xml", parts=(PartPrefabPart(part, 1),))


def _row(key: int, name: str, *texts: str, prefix: bytes = b"\x00" * 16) -> types.SimpleNamespace:
    """A stand-in with the four row attributes discovery reads: raw, prefix_end, key, string_key."""

    body = b"".join(struct.pack("<I", stringinfo_key(text)) for text in texts)
    return types.SimpleNamespace(raw=prefix + body + b"\x00" * 3, prefix_end=len(prefix), key=key, string_key=name)


class _Archive:
    """A dict of path -> payload standing in for the archives."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = {k.lower(): v for k, v in files.items()}

    def read(self, path: str):
        return self.files.get(path.lower())

    def exists(self, path: str) -> bool:
        return path.lower() in self.files


def _ziane_like():
    """A sword that owns `_r/_l` and borrows another sword's sheath, as Ziane's does."""

    pac_0109 = f"character/model/{MODEL_FOLDER}/cd_phm_01_sword_0109.pac"
    pac_0168_in = f"character/model/{MODEL_FOLDER}/cd_phm_01_sword_0168_in.pac"
    pappt = PartPrefabTable(records=(
        _record("cd_phm_01_sword_0109_r"), _record("cd_phm_01_sword_0109_l", "CD_MainWeapon_Sword_L"),
        _record("cd_phm_01_sword_0168_r_in_index01"), _record("cd_phm_01_sword_0168_l_in_index01"),
        _record("cd_phm_01_sword_0168_r"),
    ))
    texts = [r.stem for r in pappt.records] + ["ItemIcon_Prefab_CD_PHM_01_Sword_0109", "Unrelated"]
    stringinfo = {stringinfo_key(t): t for t in texts}
    archive = _Archive({
        f"character/bin__/prefab/{FOLDER}/cd_phm_01_sword_0109_r.prefab": build_prefab(pac_0109),
        f"character/bin__/prefab/{FOLDER}/cd_phm_01_sword_0109_l.prefab": build_prefab(pac_0109),
        f"character/bin__/prefab/{FOLDER}/cd_phm_01_sword_0168_r_in_index01.prefab": build_prefab(pac_0168_in),
        f"character/bin__/prefab/{FOLDER}/cd_phm_01_sword_0168_l_in_index01.prefab": build_prefab(pac_0168_in),
        pac_0109: b"PAC-bytes",
        f"character/modelproperty/{MODEL_FOLDER}/cd_phm_01_sword_0109.pac_xml": b"<pac_xml texture='cd_phm_01_sword_0109_d.dds'/>",
        f"character/bin__/meshphysics/{MODEL_FOLDER}/cd_phm_01_sword_0109.hkx": b"HKX",
        "ui/texture/icon/itemicon_prefab_cd_phm_01_sword_0109.dds": b"DDS",
    })
    row = _row(
        1001295, "Ziane_OneHandSword",
        "cd_phm_01_sword_0109_r", "cd_phm_01_sword_0168_r_in_index01", "cd_phm_01_sword_0109_r",
        "cd_phm_01_sword_0109_l", "cd_phm_01_sword_0168_l_in_index01", "ItemIcon_Prefab_CD_PHM_01_Sword_0109",
    )
    return row, stringinfo, pappt, archive


class DiscoveryTests(unittest.TestCase):
    def test_a_sword_that_borrows_its_sheath(self) -> None:
        row, stringinfo, pappt, archive = _ziane_like()
        stems = find_part_stems(row, stringinfo, pappt)
        self.assertEqual([s for _h, s in stems], [
            "cd_phm_01_sword_0109_r", "cd_phm_01_sword_0168_r_in_index01",
            "cd_phm_01_sword_0109_l", "cd_phm_01_sword_0168_l_in_index01",
        ], "first occurrence order, duplicates collapsed")
        self.assertEqual(find_icon_string(row, stringinfo)[1], "ItemIcon_Prefab_CD_PHM_01_Sword_0109")
        family = discover_item_model_family(row, stringinfo=stringinfo, pappt=pappt, read_entry=archive.read, path_exists=archive.exists)
        self.assertEqual(family.model_stem, "cd_phm_01_sword_0109")
        self.assertEqual(family.model_folder, MODEL_FOLDER)
        self.assertEqual(family.owned_stems, ("cd_phm_01_sword_0109_r", "cd_phm_01_sword_0109_l"))
        self.assertEqual(family.borrowed_stems, ("cd_phm_01_sword_0168_r_in_index01", "cd_phm_01_sword_0168_l_in_index01"))
        self.assertEqual([(f.role, f.exists) for f in family.files], [
            ("pac", True), ("pac_xml", True), ("hkx", True), ("prefab", True), ("prefab", True), ("icon", True),
        ])
        self.assertEqual(family.files_for("pac_xml")[0].mentions_stem, True, "the pac_xml names its own textures")
        self.assertEqual(family.files_for("pac")[0].mentions_stem, False)
        self.assertEqual(family.missing_files, ())
        self.assertEqual(family.icon_hash, stringinfo_key("ItemIcon_Prefab_CD_PHM_01_Sword_0109"))
        renamed = dict((old, new) for _role, old, new in family.renamed("cd_phm_01_sword_9109"))
        self.assertEqual(renamed[f"character/model/{MODEL_FOLDER}/cd_phm_01_sword_0109.pac"], f"character/model/{MODEL_FOLDER}/cd_phm_01_sword_9109.pac")
        self.assertEqual(renamed[f"character/bin__/prefab/{FOLDER}/cd_phm_01_sword_0109_l.prefab"], f"character/bin__/prefab/{FOLDER}/cd_phm_01_sword_9109_l.prefab")
        self.assertEqual(renamed["ui/texture/icon/itemicon_prefab_cd_phm_01_sword_0109.dds"], "ui/texture/icon/itemicon_prefab_cd_phm_01_sword_9109.dds")
        self.assertEqual(family.renamed_icon_string("cd_phm_01_sword_9109"), "ItemIcon_Prefab_cd_phm_01_sword_9109")
        self.assertIn("icon string", family.notes[0])

    def test_missing_files_are_listed_not_hidden(self) -> None:
        row, stringinfo, pappt, archive = _ziane_like()
        del archive.files[f"character/bin__/meshphysics/{MODEL_FOLDER}/cd_phm_01_sword_0109.hkx"]
        family = discover_item_model_family(row, stringinfo=stringinfo, pappt=pappt, read_entry=archive.read)
        self.assertEqual([f.role for f in family.missing_files], ["hkx"])

    def test_icon_that_names_a_part_resolves_to_its_mesh(self) -> None:
        pac = "character/model/1_pc/1_phm/armor/18_acc/cd_phm_00_ring_00_0011.pac"
        pappt = PartPrefabTable(records=(
            _record("cd_phm_00_ring_0011_r", folder="1_pc/01_phm/armor/18_acc"),
            _record("cd_phm_00_ring_0011_l", folder="1_pc/01_phm/armor/18_acc"),
            _record("cd_phw_01_ring_0011_r", folder="1_pc/02_phw/armor/18_acc"),
        ))
        stringinfo = {stringinfo_key(t): t for t in [r.stem for r in pappt.records] + ["ItemIcon_Prefab_CD_PHM_00_Ring_0011_L"]}
        archive = _Archive({
            "character/bin__/prefab/1_pc/01_phm/armor/18_acc/cd_phm_00_ring_0011_r.prefab": build_prefab(pac),
            "character/bin__/prefab/1_pc/01_phm/armor/18_acc/cd_phm_00_ring_0011_l.prefab": build_prefab(pac),
            "character/bin__/prefab/1_pc/02_phw/armor/18_acc/cd_phw_01_ring_0011_r.prefab": build_prefab(pac.replace("phm_00", "phw_01")),
            pac: b"pac",
        })
        row = _row(8502, "Ring", "cd_phm_00_ring_0011_r", "cd_phm_00_ring_0011_l", "cd_phw_01_ring_0011_r", "ItemIcon_Prefab_CD_PHM_00_Ring_0011_L")
        family = discover_item_model_family(row, stringinfo=stringinfo, pappt=pappt, read_entry=archive.read)
        self.assertEqual(family.model_stem, "cd_phm_00_ring_00_0011")
        self.assertEqual(family.owned_stems, ("cd_phm_00_ring_0011_r", "cd_phm_00_ring_0011_l"))
        self.assertEqual(family.borrowed_stems, ("cd_phw_01_ring_0011_r",))
        # the prefab stems only share `cd_phm_00_ring` with the mesh stem, so they keep their tail
        self.assertEqual(family.rename_stem("cd_phm_00_ring_0011_l", "cd_phm_00_ring_00_9011"), "cd_phm_00_ring_00_9011_0011_l")
        self.assertEqual(family.rename_stem("cd_phm_00_ring_00_0011", "cd_phm_00_ring_00_9011"), "cd_phm_00_ring_00_9011")
        with self.assertRaisesRegex(ItemModelFamilyError, "shares no name"):
            family.rename_stem("gimmick_trap_bomb_01", "cd_phm_00_ring_00_9011")
        with self.assertRaisesRegex(ItemModelFamilyError, "new model stem"):
            family.rename_stem("cd_phm_00_ring_00_0011", "")

    def test_fallbacks_and_refusals(self) -> None:
        pac_a = "character/model/6_object/tools/cd_t0000_paper_0002.pac"
        pappt = PartPrefabTable(records=(_record("cd_t0000_paper_0258", folder="6_object/tools"), _record("cd_t0000_paper_0259", folder="6_object/tools")))
        stringinfo = {stringinfo_key(t): t for t in ["cd_t0000_paper_0258", "cd_t0000_paper_0259", "ItemIcon_Prefab_gimmick_paper", "ItemIcon_Prefab_cd_t0000_other"]}
        archive = _Archive({"character/bin__/prefab/6_object/tools/cd_t0000_paper_0258.prefab": build_prefab(pac_a), pac_a: b"pac"})
        # no icon: the mesh the parts share
        family = discover_item_model_family(_row(1, "Paper", "cd_t0000_paper_0258"), stringinfo=stringinfo, pappt=pappt, read_entry=archive.read)
        self.assertEqual(family.model_stem, "cd_t0000_paper_0002")
        self.assertEqual(family.owned_stems, ("cd_t0000_paper_0258",))
        self.assertIsNone(family.icon_string)
        self.assertIsNone(family.renamed_icon_string("x"))
        self.assertIn("no icon", " ".join(family.notes))
        # an icon named after something else falls back, and takes the new stem when renamed
        family = discover_item_model_family(_row(2, "Paper", "cd_t0000_paper_0258", "ItemIcon_Prefab_gimmick_paper"), stringinfo=stringinfo, pappt=pappt, read_entry=archive.read)
        self.assertEqual(family.model_stem, "cd_t0000_paper_0002")
        self.assertEqual(family.renamed_icon_string("cd_t0000_paper_9002"), "ItemIcon_Prefab_cd_t0000_paper_9002")
        self.assertEqual(family.renamed("cd_t0000_paper_9002")[-1][2], "ui/texture/icon/itemicon_prefab_cd_t0000_paper_9002.dds")
        self.assertEqual(family.rename_stem("cd_t0000_paper_0258", "cd_t0000_paper_9002"), "cd_t0000_paper_9002_0258")
        # a stem the table does not know is noted, and one whose prefab is unreadable too
        family = discover_item_model_family(_row(3, "Paper", "cd_t0000_paper_0258", "cd_t0000_paper_0259"), stringinfo=stringinfo, pappt=pappt, read_entry=archive.read)
        self.assertTrue(any("names no .pac" in note for note in family.notes), family.notes)
        with self.assertRaisesRegex(ItemModelFamilyError, "no part-prefab stems"):
            discover_item_model_family(_row(4, "Nothing", "Unrelated"), stringinfo=stringinfo, pappt=pappt, read_entry=archive.read)


@pytest.mark.real_game
class VanillaFamilyTests(unittest.TestCase):
    """Ziane's sword resolves exactly as the installed spike found it, and the corpus resolves."""

    def test_every_shipped_item_with_parts_resolves_and_swords_own_both_hands(self) -> None:
        from tools.placement_studio import corpus
        from cdmw.core.archive_extraction import read_archive_entry_data
        from cdmw.core.iteminfo_row import parse_iteminfo_row
        from cdmw.core.pappt_format import parse_pappt
        from cdmw.core.prefab_binary import decode_prefab_binary
        from cdmw.core.stringinfo_table import parse_stringinfo, stringinfo_index
        from cdmw.core.structured_binary_editor import parse_pabgh_table

        if not corpus.game_root().is_dir():
            self.skipTest("needs the installed game")
        entries = {}
        for _package, entry in corpus._iter_archive_entries(corpus.game_root()):
            entries[corpus.normalize_game_path(entry.path)] = entry

        def read(path):
            entry = entries.get(path.lower())
            return read_archive_entry_data(entry)[0] if entry is not None else None

        bin_dir = "gamedata/binary__/client/bin"
        payload, header = read(f"{bin_dir}/iteminfo.pabgb"), read(f"{bin_dir}/iteminfo.pabgh")
        if payload is None or header is None:
            self.skipTest("iteminfo not found")
        stringinfo = stringinfo_index(parse_stringinfo(read(f"{bin_dir}/stringinfo.pabgb"), read(f"{bin_dir}/stringinfo.pabgh")))
        pappt = parse_pappt(read("character/bin__/partprefabtable.pappt"))
        spans = parse_pabgh_table(header, payload=payload).row_spans(len(payload))
        keys = {row.row_id for row, _s, _e in spans}
        rows = {row.row_id: parse_iteminfo_row(payload[s:e], item_keys=keys) for row, s, e in spans}

        ziane = discover_item_model_family(rows[1001295], stringinfo=stringinfo, pappt=pappt, read_entry=read, path_exists=lambda p: p.lower() in entries)
        self.assertEqual(ziane.model_stem, "cd_phm_01_sword_0109")
        self.assertEqual(ziane.model_folder, "1_pc/1_phm/weapon/1_onehandweapon")
        self.assertEqual(ziane.owned_stems, ("cd_phm_01_sword_0109_r", "cd_phm_01_sword_0109_l"))
        self.assertEqual(ziane.borrowed_stems, ("cd_phm_01_sword_0168_r_in_index01", "cd_phm_01_sword_0168_l_in_index01"))
        self.assertEqual(ziane.icon_string, "ItemIcon_Prefab_CD_PHM_01_Sword_0109")
        self.assertEqual([f.role for f in ziane.files], ["pac", "pac_xml", "hkx", "prefab", "prefab", "icon"])
        self.assertEqual(ziane.missing_files, ())
        self.assertEqual([f.mentions_stem for f in ziane.files[:2]], [False, False], "a byte copy of pac and pac_xml is self-contained")

        # NI-008: the two owned prefabs take a longer stem through the full rewriter
        old_pac = ziane.files_for("pac")[0].path
        new_pac = old_pac.replace("cd_phm_01_sword_0109", "cd_phm_01_sword_0109_longer_stem")
        for prefab in ziane.files_for("prefab"):
            result = rewrite_prefab_paths_any_length(read(prefab.path), {old_pac: new_pac})
            self.assertGreater(result.byte_delta, 0)
            texts = [s.text for s in decode_prefab_binary(result.data).resource_strings()]
            self.assertIn(new_pac, texts)
            self.assertNotIn(old_pac, texts)

        resolved = swords = swords_both_hands = 0
        for row in rows.values():
            if not find_part_stems(row, stringinfo, pappt):
                continue
            family = discover_item_model_family(row, stringinfo=stringinfo, pappt=pappt, read_entry=read, path_exists=lambda p: p.lower() in entries)
            resolved += 1
            if family.model_folder == "1_pc/1_phm/weapon/1_onehandweapon":
                swords += 1
                suffixes = {stem[len(family.model_stem):] for stem in family.owned_stems}
                if {"_r", "_l"} <= suffixes and not family.missing_files:
                    swords_both_hands += 1
        self.assertGreater(resolved, 5000)
        self.assertGreater(swords, 100)
        self.assertGreater(swords_both_hands / swords, 0.9, (swords, swords_both_hands))


if __name__ == "__main__":
    unittest.main()
