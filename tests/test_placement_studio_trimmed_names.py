"""Clip rows are the file name with the boilerplate taken out, not a rewrite of it.

A row of `cd_boarmimic_basic_00_00_nor_move_walkfast_turn180l_stt_00` is mostly parts that are
the same on every row. Taking those out leaves something readable that is still recognisably
the file on disk — which a translation into prose would not be, and which matters because the
search box matches the real name and the mod is written against it.
"""

from __future__ import annotations

import unittest

from tools.placement_studio.clip_names import trimmed


class TrimmedNameTests(unittest.TestCase):
    def test_the_worked_example(self) -> None:
        self.assertEqual(
            trimmed("cd_boarmimic_basic_00_00_nor_move_walkfast_turn180l_stt_00"),
            "Boarmimic - Move - Walkfast - Turn 180 L (start)",
        )

    def test_the_boilerplate_goes(self) -> None:
        """`cd`, the take numbers, and the default stance are on every clip in the game."""

        out = trimmed("cd_phm_sword_01_01_nor_std_weapon_out_00")

        for noise in ("cd", "01", "nor", "_"):
            self.assertNotIn(noise, out)

    def test_a_pair_that_means_one_thing_stays_one_thing(self) -> None:
        """Split apart, `Weapon - Out` is less legible than the file name was."""

        self.assertIn("Draw", trimmed("cd_phm_sword_01_01_nor_std_weapon_out_00"))
        self.assertIn("Sheathe", trimmed("cd_oongka_lswd_00_01_nor_base_std_weapon_in"))

    def test_abbreviations_are_spelled_out(self) -> None:
        """A row saying `Lswd` has translated nothing."""

        out = trimmed("cd_phm_lswd_00_01_nor_std_weapon_out_00")

        self.assertIn("Kliff", out)
        self.assertIn("Longsword", out)

    def test_the_phase_survives_the_trim(self) -> None:
        """Start, middle and end are three clips; collapsing them would merge three rows."""

        base = "cd_phm_basic_00_00_nor_move_walkfast_f_{}_00"
        labels = {trimmed(base.format(phase)) for phase in ("stt", "ing", "end")}

        self.assertEqual(len(labels), 3, f"phases collapsed onto one row: {labels}")

    def test_a_name_that_repeats_itself_is_said_once(self) -> None:
        out = trimmed("cd_corpse_lk_phm_basic_00_00_item_corpse_lk_phm_std_lift_end_00")

        self.assertEqual(out.lower().count("corpse"), 1, out)

    def test_an_unknown_word_still_appears(self) -> None:
        """Vanishing is worse than being cryptic — the row has to stay findable."""

        self.assertIn("Zzqq", trimmed("cd_zzqq_00_nor_std_00"))

    def test_a_name_that_is_all_boilerplate_falls_back_to_itself(self) -> None:
        self.assertEqual(trimmed("cd_00_nor"), "cd_00_nor")


class ChartNamedClipTests(unittest.TestCase):
    """The clips a chart names are written a little differently, and still have to read well."""

    def test_the_underscoreless_spelling_is_recognised(self) -> None:
        """`weaponin` is one token, so the pair rule never sees it — it needs its own entry."""

        self.assertIn("Sheathe", trimmed("cd_damian_rd_prh_spr_00_01_nor_base_std_weaponin_00"))
        self.assertIn("Draw", trimmed("cd_damian_rd_prh_sythe_01_01_nor_base_std_weaponout_00"))

    def test_horseback_is_said_once(self) -> None:
        """`rd` and `prh` both mean mounted; naming both is noise."""

        out = trimmed("cd_oongka_rd_prh_hm_01_01_nor_base_std_weaponin_00")

        self.assertEqual(out.lower().count("horseback"), 1, out)
        self.assertNotIn("Rd", out)

    def test_a_stance_is_not_contradicted_by_the_default_marker(self) -> None:
        """In `sit_base_std`, `std` marks the standard variant *of sitting*.

        Spelled out as well it gave rows reading `Seated - Standing`, which names two stances
        for one clip and leaves the reader to guess which is true.
        """

        out = trimmed("cd_nairah_bow_00_01_sit_base_std_weapon_in_00")

        self.assertIn("Seated", out)
        self.assertNotIn("Standing", out)

    def test_standing_survives_when_it_is_the_real_stance(self) -> None:
        self.assertIn("Standing", trimmed("cd_phm_sword_01_01_nor_std_weapon_out_00"))
