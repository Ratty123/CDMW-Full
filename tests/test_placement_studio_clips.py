"""The motion clip index behind the Placement & Animation Studio browser.

Pure index logic on synthetic paths — no game install, no Qt. The archive-backed path is
exercised by the studio itself; what is worth pinning here is the classification and the
filtering, because both decide whether a clip the user knows exists can be found.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tools.placement_studio.clips import (
    ANY,
    ClipIndex,
    classify,
    index_directory,
    read_clip,
    rig_of,
    summarise,
)
from tools.placement_studio.clips import _entry as make_entry


def _index(*paths: str) -> ClipIndex:
    return ClipIndex(make_entry(path, None) for path in paths)


_PHM = "character/motion/1_pc/1_phm/"
_PHW = "character/motion/1_pc/2_phw/"


class ClassificationTests(unittest.TestCase):
    def test_draw_and_sheathe_are_separated(self) -> None:
        self.assertEqual(classify("cd_phm_longsword_00_01_normal_stand_weapon_out_000.paa"), "draw")
        self.assertEqual(classify("cd_phm_longsword_00_01_normal_stand_weapon_in_000.paa"), "sheathe")

    def test_combat_beats_locomotion_when_a_name_carries_both(self) -> None:
        """`att_nor_move_run` is an attack that moves, not a run."""

        self.assertEqual(classify("cd_phm_baxe_01_01_att_nor_move_run_f_00.paa"), "attack")

    def test_locomotion_tokens(self) -> None:
        self.assertEqual(classify("cd_phm_lswd_01_01_nor_move_runfast_f_ing_00.paa"), "run")
        self.assertEqual(classify("cd_phm_lswd_01_01_nor_move_walkfast_ing_00.paa"), "walk")
        self.assertEqual(classify("cd_phm_basic_00_00_nor_move_jump_f_stt_00.paa"), "jump")
        self.assertEqual(classify("cd_phm_lswd_01_01_nor_std_idle_00.paa"), "idle")

    def test_an_unrecognised_name_is_other_not_a_guess(self) -> None:
        self.assertEqual(classify("cd_phm_something_entirely_new_00.paa"), "other")


class RigTests(unittest.TestCase):
    def test_rig_comes_from_the_motion_path(self) -> None:
        self.assertEqual(rig_of(_PHM + "clip.paa"), "1_pc/1_phm")
        self.assertEqual(rig_of("character/motion/2_mon/cd_m0001_00_bear/clip.paa"), "2_mon/cd_m0001_00_bear")

    def test_a_path_outside_the_motion_tree_has_no_rig(self) -> None:
        self.assertEqual(rig_of("character/model/1_pc/1_phm/phm_01.pab"), "")


class FilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = _index(
            _PHM + "cd_phm_longsword_00_01_normal_stand_weapon_out_000.paa",
            _PHM + "cd_phm_longsword_00_01_normal_stand_weapon_in_000.paa",
            _PHM + "cd_phm_lswd_01_01_nor_move_runfast_f_ing_00.paa",
            _PHM + "cd_phm_longsword_00_01_normal_stand_weapon_out_000_lod.paa",
            _PHW + "cd_phw_lswd_00_01_nor_std_weapon_out_00.paa",
        )

    def test_lod_copies_are_hidden_unless_asked_for(self) -> None:
        _found, total = self.index.filter()
        self.assertEqual(total, 4)
        _found, with_lod = self.index.filter(include_lod=True)
        self.assertEqual(with_lod, 5)

    def test_filtering_by_rig(self) -> None:
        found, total = self.index.filter(rig="1_pc/2_phw")
        self.assertEqual(total, 1)
        self.assertTrue(found[0].path.startswith(_PHW))

    def test_filtering_by_category(self) -> None:
        _found, total = self.index.filter(category="draw")
        self.assertEqual(total, 2)

    def test_search_terms_all_have_to_match(self) -> None:
        _found, both = self.index.filter(text="longsword weapon_out")
        self.assertEqual(both, 1)
        _found, neither = self.index.filter(text="longsword nonesuch")
        self.assertEqual(neither, 0)

    def test_the_cap_limits_rows_but_not_the_reported_total(self) -> None:
        """A silently truncated list reads as 'that clip is not in the game'."""

        found, total = self.index.filter(limit=2)
        self.assertEqual(len(found), 2)
        self.assertEqual(total, 4)
        self.assertIn("of 4", summarise(found, total, 2))

    def test_rigs_are_listed_once_and_sorted(self) -> None:
        self.assertEqual(self.index.rigs(), ("1_pc/1_phm", "1_pc/2_phw"))

    def test_any_matches_everything(self) -> None:
        _found, total = self.index.filter(rig=ANY, category=ANY)
        self.assertEqual(total, 4)


class DirectoryIndexTests(unittest.TestCase):
    def test_indexes_a_tree_and_reads_back(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            clip = root / "character" / "motion" / "1_pc" / "1_phm"
            clip.mkdir(parents=True)
            payload = b"PAR " + bytes(32)
            (clip / "cd_phm_lswd_01_01_nor_std_idle_00.paa").write_bytes(payload)
            index = index_directory(root)
            self.assertEqual(len(index), 1)
            entry = index.entries[0]
            self.assertEqual(entry.rig, "1_pc/1_phm")
            self.assertEqual(entry.category, "idle")
            self.assertEqual(read_clip(entry), payload)

    def test_an_entry_with_no_source_refuses_to_read(self) -> None:
        entry = make_entry(_PHM + "clip.paa", None)
        with self.assertRaises(ValueError):
            read_clip(entry)


if __name__ == "__main__":
    unittest.main()
