"""Where a clip is used, read from the charts rather than guessed from its name.

Reading the name put `cd_prh_swd_01_01_nor_std_weapon_out_00` under "standing still" because
it contains `nor_std`, and called `sit_std` clips horseback. The charts settle both: the
first is named by `ride_weapon_upper.paac`, the second by `sword_upper.paac` — an ordinary
on-foot chart.
"""

from __future__ import annotations

import unittest

from tools.placement_studio.chart_lanes import situation_of_chart
from tools.placement_studio.clip_names import lane_of


class ChartSituationTests(unittest.TestCase):
    def test_a_chart_that_names_a_situation_is_read(self) -> None:
        self.assertEqual(situation_of_chart("ride_weapon_upper.paac"), "On horseback")
        self.assertEqual(situation_of_chart("basic_lower_crouch.paac"), "Crouching")
        self.assertEqual(situation_of_chart("basic_lower_swim.paac"), "Swimming")
        self.assertEqual(situation_of_chart("basic_lower_ladder.paac"), "Climbing")

    def test_a_weapon_chart_is_not_a_situation(self) -> None:
        """`sword_upper` says which weapon, not where — and the weapon is already the row."""

        self.assertEqual(situation_of_chart("sword_upper.paac"), "")
        self.assertEqual(situation_of_chart("twohandsword_upper.paac"), "")


class LanePrecedenceTests(unittest.TestCase):
    def test_the_chart_wins_over_the_file_name(self) -> None:
        mounted = "cd_prh_swd_01_01_nor_std_weapon_out_00"
        self.assertEqual(lane_of(mounted), "On horseback")  # by prefix, without charts

        self.assertEqual(
            lane_of("cd_phm_sword_00_01_normal_stand_weapon_out_000",
                    {"cd_phm_sword_00_01_normal_stand_weapon_out_000": "Crouching"}),
            "Crouching",
            "a chart saying crouching must beat `normal_stand` in the name",
        )

    def test_the_name_is_used_only_when_no_chart_claims_the_clip(self) -> None:
        self.assertEqual(
            lane_of("cd_phm_sword_00_01_normal_stand_weapon_out_000", {}), "Standing still"
        )

    def test_a_distance_copy_follows_its_own_clip(self) -> None:
        charts = {"cd_phm_sword_00_01_normal_stand_weapon_out_000": "Swimming"}

        self.assertEqual(
            lane_of("cd_phm_sword_00_01_normal_stand_weapon_out_000_lod", charts), "Swimming"
        )

    def test_an_empty_index_never_raises(self) -> None:
        self.assertTrue(lane_of("cd_phm_sword_00_01_sit_std_weapon_in_00", None))


if __name__ == "__main__":
    unittest.main()
