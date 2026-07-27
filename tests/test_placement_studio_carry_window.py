"""The carry control's wiring: what it offers, and how it orders the clips it finds.

The measurement itself is covered in `test_placement_studio_carry`. What matters here is the
part a user actually touches — that picking a carry position filters the clip list to the
draws that start there, strongest first, and that the filter stays off until it is asked for.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from tools.placement_studio import carry  # noqa: E402
from tools.placement_studio.window_carry import CarryPickerMixin  # noqa: E402

_APP = QApplication.instance() or QApplication([])


class _Box:
    def __init__(self, checked: bool = True) -> None:
        self._checked = checked

    def isChecked(self) -> bool:  # noqa: N802 - mimics QCheckBox
        return self._checked

    def setChecked(self, value: bool) -> None:  # noqa: N802 - mimics QCheckBox
        self._checked = value


class _Harness(CarryPickerMixin):
    """The mixin with only what the filtering path touches."""

    def __init__(self, index=None, zone: str = "", checked: bool = True) -> None:
        self._carry_index = index
        self._carry_filter_zone = zone
        self._clip_carry_box = _Box(checked)


def _index() -> carry.CarryIndex:
    index = carry.CarryIndex()
    # A clear-cut hip draw, a marginal one, a hip sheathe, and a back draw.
    index.add("clear_weapon_out", carry.Reach("Pelvis_R_Socket", 0.09, 0.40, "r", 0.62))
    index.add("marginal_weapon_out", carry.Reach("Pelvis_R_Socket", 0.10, 0.004, "r", 0.70))
    index.add("hip_weapon_in", carry.Reach("Pelvis_L_Socket", 0.09, 0.30, "r", 0.55))
    index.add("back_weapon_out", carry.Reach("Spine2_B_SubWeapon_Socket", 0.11, 0.25, "r", 0.37))
    return index


class CarryFilterTests(unittest.TestCase):
    def test_the_filter_selects_only_the_zone_asked_for(self) -> None:
        harness = _Harness(_index(), zone="back")

        self.assertEqual(harness._carry_zone_filter(), {"back_weapon_out"})

    def test_nothing_is_filtered_before_a_carry_position_is_chosen(self) -> None:
        self.assertIsNone(_Harness(_index(), zone="")._carry_zone_filter())

    def test_nothing_is_filtered_without_a_measured_index(self) -> None:
        self.assertIsNone(_Harness(None, zone="back")._carry_zone_filter())

    def test_unticking_the_box_restores_the_whole_list(self) -> None:
        harness = _Harness(_index(), zone="hip", checked=False)

        self.assertIsNone(harness._carry_zone_filter())

    def test_draws_are_ranked_ahead_of_sheathes(self) -> None:
        ranking = _Harness(_index(), zone="hip")._carry_clip_ranking()

        self.assertLess(ranking["clear_weapon_out"], ranking["hip_weapon_in"])
        self.assertLess(ranking["marginal_weapon_out"], ranking["hip_weapon_in"])

    def test_a_clear_cut_draw_outranks_a_marginal_one_that_travelled_further(self) -> None:
        """Separation beats raw distance: a thin margin means the zone was nearly a toss-up."""

        ranking = _Harness(_index(), zone="hip")._carry_clip_ranking()

        self.assertLess(ranking["clear_weapon_out"], ranking["marginal_weapon_out"])

    def test_the_ranking_is_empty_when_there_is_nothing_to_rank(self) -> None:
        self.assertEqual(_Harness(None, zone="hip")._carry_clip_ranking(), {})


if __name__ == "__main__":
    unittest.main()
