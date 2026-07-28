"""Naming a clip so a person can choose between two of them.

`cd_phm_sword_00_01_normal_stand_weapon_out_000` describes itself completely and illegibly.
When the tool asks which of two draws to use, two names differing only at `00_01` versus
`01_03` is not a question anyone can answer.
"""

from __future__ import annotations

import unittest

from tools.placement_studio.clip_names import distinct_labels, friendly


class FriendlyNameTests(unittest.TestCase):
    def test_a_standing_draw_reads_as_one(self) -> None:
        text = friendly("cd_phm_sword_00_01_normal_stand_weapon_out_000")

        self.assertIn("Standing still", text)
        self.assertIn("drawing the weapon", text)

    def test_putting_away_is_distinguished_from_taking_out(self) -> None:
        self.assertIn("sheathing the weapon",
                      friendly("cd_phm_sword_00_01_normal_stand_weapon_in_000"))

    def test_a_mounted_clip_is_not_filed_as_standing(self) -> None:
        """`cd_prh_` is the mounted character. Reading `nor_std` off one of those put a
        horseback draw under "standing still"; the charts settle it — those clips are the
        ones `ride_weapon_upper.paac` names."""

        from tools.placement_studio.clip_names import lane_of

        self.assertEqual(lane_of("cd_prh_swd_01_01_nor_std_weapon_out_00"), "On horseback")
        self.assertEqual(
            lane_of("cd_phm_sword_00_01_normal_stand_weapon_out_000"), "Standing still"
        )

    def test_sit_is_not_claimed_to_be_horseback(self) -> None:
        """`cd_phm_swds_00_01_sit_std_*` is named by `sword_upper.paac`, an on-foot chart."""

        from tools.placement_studio.clip_names import lane_of

        self.assertNotIn("horseback", lane_of("cd_phm_swds_00_01_sit_std_weapon_out_00").lower())

    def test_the_context_is_kept(self) -> None:
        self.assertIn("running",
                      friendly("cd_phm_longsword_00_00_normal_move_run_f_weapon_out_000").lower())
        self.assertIn("low stance", friendly("cd_phm_lswd_00_01_sit_std_weapon_out_00"))
        self.assertIn("fight", friendly("cd_phm_lswd_01_01_alert_nor_std_weapon_out_00").lower())

    def test_sprinting_is_not_mistaken_for_running(self) -> None:
        self.assertIn("sprinting",
                      friendly("cd_phm_lswd_00_01_nor_move_runfast2_f_ing_00").lower())

    def test_an_unrecognised_action_keeps_its_own_words(self) -> None:
        """Losing everything but the posture would make two clips read identically."""

        self.assertIn("eat bread",
                      friendly("cd_phm_dlsd_00_01_nor_base_std_eat_bread_00"))

    def test_a_take_number_becomes_a_human_count(self) -> None:
        text = friendly("cd_phm_sword_00_01_normal_stand_weapon_in_002")

        self.assertIn("version 3", text)
        self.assertNotIn("_002", text)

    def test_a_distance_copy_says_so(self) -> None:
        self.assertIn("distant",
                      friendly("cd_phm_lswd_00_01_sit_std_weapon_in_00_lod"))

    def test_a_name_it_cannot_read_is_returned_rather_than_blanked(self) -> None:
        self.assertEqual(friendly("nonsense"), "nonsense")


class DistinctLabelTests(unittest.TestCase):
    def test_options_that_describe_alike_are_separated(self) -> None:
        labels = distinct_labels([
            "cd_phm_longsword_00_01_normal_stand_weapon_out_000",
            "cd_phm_longsword_01_03_normal_stand_weapon_out_000",
        ])

        self.assertEqual(len(set(labels)), 2, "a choice between identical labels is no choice")
        self.assertTrue(all("Standing still" in label for label in labels))

    def test_options_that_already_differ_are_left_clean(self) -> None:
        labels = distinct_labels([
            "cd_phm_lswd_00_01_sit_std_weapon_out_00",
            "cd_phm_longsword_00_01_normal_stand_weapon_out_000",
        ])

        self.assertTrue(all("[" not in label for label in labels))


if __name__ == "__main__":
    unittest.main()


class GroupingTests(unittest.TestCase):
    """Which clips are the same question, and therefore share one answer."""

    def test_takes_of_the_same_moment_are_one_question(self) -> None:
        from tools.placement_studio.clip_names import group_key

        keys = {
            group_key(name)
            for name in (
                "cd_phm_sword_00_01_normal_stand_weapon_in_000",
                "cd_phm_sword_00_01_normal_stand_weapon_in_002",
                "cd_phm_sword_00_01_normal_stand_weapon_in_002_lod",
            )
        }

        self.assertEqual(len(keys), 1, "the game picks between these at runtime")

    def test_a_different_character_is_a_different_question(self) -> None:
        """`cd_prh_` is mounted. Offered as a style for a standing draw it chose a motion
        from horseback, so the applied animation matched none of the options shown."""

        from tools.placement_studio.clip_names import group_key

        self.assertNotEqual(
            group_key("cd_phm_lswd_01_01_nor_std_weapon_out_00"),
            group_key("cd_prh_lswd_01_01_nor_std_weapon_out_00"),
        )

    def test_taking_out_is_never_grouped_with_putting_away(self) -> None:
        from tools.placement_studio.clip_names import group_key

        self.assertNotEqual(
            group_key("cd_phm_sword_00_01_normal_stand_weapon_out_000"),
            group_key("cd_phm_sword_00_01_normal_stand_weapon_in_000"),
        )

    def test_the_same_action_on_a_different_weapon_is_a_different_question(self) -> None:
        """A dual-sword draw is not a one-hand draw; one answer cannot serve both."""

        from tools.placement_studio.clip_names import group_key

        self.assertNotEqual(
            group_key("cd_phm_sword_00_01_normal_stand_weapon_out_000"),
            group_key("cd_phm_dualsword_00_01_nor_stand_weapon_out_00"),
        )

    def test_a_different_stance_is_a_different_question(self) -> None:
        """`00_01` and `01_01` are states the game chooses between at the time, so a choice
        covering both could be settled by a clip it never offered."""

        from tools.placement_studio.clip_names import group_key

        self.assertNotEqual(
            group_key("cd_phm_sword_00_01_normal_stand_weapon_out_000"),
            group_key("cd_phm_sword_01_01_normal_stand_weapon_out_000"),
        )

    def test_the_heading_names_the_weapon_and_the_state(self) -> None:
        """Three decisions reading "Standing — eat bread" is no more answerable than twenty."""

        from tools.placement_studio.clip_names import group_label

        one = group_label("cd_phm_sword_00_01_normal_stand_weapon_out_000", 10)
        other = group_label("cd_phm_dualsword_00_01_nor_stand_weapon_out_00", 2)
        stance = group_label("cd_phm_sword_01_01_normal_stand_weapon_out_000", 2)

        self.assertIn("One-handed sword", one)
        self.assertIn("Dual swords", other)
        self.assertNotEqual(one, other)
        self.assertIn("state", stance)
        self.assertNotEqual(one, stance)

    def test_the_heading_counts_what_it_settles(self) -> None:
        from tools.placement_studio.clip_names import group_label

        label = group_label("cd_phm_sword_00_01_normal_stand_weapon_in_002", 12)

        self.assertIn("12 clips", label)
        self.assertNotIn("version", label)
        self.assertNotIn("distant", label)
