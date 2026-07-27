"""The one form that moves a weapon and takes its animations along.

What matters is that nothing happens until OK and that the plan reflects exactly what the
form shows — the list is the answer to "which animations", so it has to be the same list the
caller acts on.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialogButtonBox  # noqa: E402

from tools.placement_studio.move_weapon import MoveWeaponDialog  # noqa: E402

_APP = QApplication.instance() or QApplication([])


class _Clip:
    def __init__(self, name: str) -> None:
        self.name = name
        self.path = f"character/motion/1_pc/1_phm/{name}.paa"


_DRAWS = [(_Clip("cd_phm_sword_00_01_normal_stand_weapon_out_000"),
           _Clip("cd_phm_longsword_00_01_normal_stand_weapon_out_000"))]
_ALL = _DRAWS + [
    (_Clip(f"cd_phm_sword_00_01_normal_move_run_f_ing_00{i}"),
     _Clip(f"cd_phm_longsword_00_01_normal_move_run_f_ing_00{i}"))
    for i in range(5)
]

_POSITIONS = [("Pelvis_L_Socket", "Hip — left"), ("Spine2_B_MainWeapon_Socket", "Back")]


def _dialog(current_socket: str = "Pelvis_L_Socket") -> MoveWeaponDialog:
    return MoveWeaponDialog(
        parts=[("CD_MainWeapon_Sword_R", "CD_MainWeapon_Sword_R")],
        positions=_POSITIONS,
        current_part="CD_MainWeapon_Sword_R",
        current_socket=current_socket,
        pairs_for=lambda locomotion=False: (_ALL if locomotion else _DRAWS),
        handedness="1h",
    )


class MoveDialogTests(unittest.TestCase):
    def test_it_opens_on_where_the_item_already_hangs(self) -> None:
        dialog = _dialog()

        self.assertEqual(dialog._to_box.currentData(), "Pelvis_L_Socket")
        self.assertEqual(dialog.plan().socket, "", "no move means no routing edit")

    def test_choosing_a_new_position_is_what_makes_it_a_move(self) -> None:
        dialog = _dialog()

        dialog._to_box.setCurrentIndex(1)

        self.assertEqual(dialog.plan().socket, "Spine2_B_MainWeapon_Socket")
        self.assertTrue(dialog.plan().moves)

    def test_the_scope_switches_the_list_both_ways(self) -> None:
        """Unticking one radio does not tick the other, so both must be listened to."""

        dialog = _dialog()
        self.assertEqual(dialog._clip_list.count(), len(_DRAWS))

        dialog._everything.setChecked(True)
        self.assertEqual(dialog._clip_list.count(), len(_ALL))

        dialog._draws_only.setChecked(True)
        self.assertEqual(dialog._clip_list.count(), len(_DRAWS))

    def test_the_plan_carries_exactly_what_is_ticked(self) -> None:
        dialog = _dialog()
        dialog._everything.setChecked(True)

        dialog._set_all(False)
        self.assertEqual(dialog.plan().clips, ())

        dialog._clip_list.item(0).setCheckState(Qt.Checked)
        self.assertEqual(len(dialog.plan().clips), 1)

    def test_turning_the_animations_off_leaves_only_the_move(self) -> None:
        dialog = _dialog()
        dialog._to_box.setCurrentIndex(1)

        dialog._animations.setChecked(False)

        plan = dialog.plan()
        self.assertEqual(plan.clips, ())
        self.assertEqual(plan.socket, "Spine2_B_MainWeapon_Socket")

    def test_an_edit_that_would_change_nothing_cannot_be_confirmed(self) -> None:
        """Same position, nothing ticked — refuse it rather than write an empty mod."""

        dialog = _dialog()
        dialog._animations.setChecked(False)

        self.assertFalse(dialog._buttons.button(QDialogButtonBox.Ok).isEnabled())

    def test_the_count_says_how_many_of_how_many(self) -> None:
        dialog = _dialog()
        dialog._everything.setChecked(True)

        self.assertIn(f"{len(_ALL)} of {len(_ALL)}", dialog._count_label.text())


if __name__ == "__main__":
    unittest.main()


class DonorChoiceTests(unittest.TestCase):
    """Some animations can be played more than one way; the tool must not choose silently."""

    def _with_choice(self) -> MoveWeaponDialog:
        # Real-shaped names: grouping reads the family and the stance out of them.
        first = _Clip("cd_phm_longsword_00_01_normal_stand_weapon_out_000")
        second = _Clip("cd_phm_longsword_01_03_normal_stand_weapon_out_000")
        rows = [
            (_Clip("cd_phm_sword_00_01_normal_stand_weapon_out_000"), first, (first, second)),
            (_Clip("cd_phm_sword_00_01_sit_std_weapon_in_00"),
             _Clip("cd_phm_lswd_00_01_sit_std_weapon_in_00")),
        ]
        return MoveWeaponDialog(
            parts=[("CD_MainWeapon_Sword_R", "CD_MainWeapon_Sword_R")],
            positions=_POSITIONS,
            current_part="CD_MainWeapon_Sword_R",
            current_socket="Pelvis_L_Socket",
            pairs_for=lambda locomotion=False: rows,
            handedness="1h",
        )

    def test_only_the_ambiguous_row_gets_a_picker(self) -> None:
        dialog = self._with_choice()

        self.assertEqual(dialog._undecided(), 1, "the single-option row needs no picker")
        self.assertEqual(dialog._clip_list.count(), 2)

    def test_the_decisions_are_lifted_out_of_the_file_list(self) -> None:
        """Hunting through hundreds of rows for the few that ask something is not a UI."""

        dialog = self._with_choice()

        self.assertEqual(len(dialog._choices), 1)
        self.assertIn("(1)", dialog._choice_group.title())

    def test_the_choice_is_named_after_what_it_is_not_its_file(self) -> None:
        label = next(iter(self._with_choice()._choices.values())).label

        self.assertNotIn("cd_", label)
        self.assertNotIn("_00_", label)

    def test_the_styles_are_numbered_so_they_can_be_told_apart(self) -> None:
        """They differ only by stance, which has no word — so they are numbered and watchable."""

        box = next(iter(self._with_choice()._choices.values())).box
        texts = [box.itemText(i) for i in range(box.count())]

        self.assertEqual(len(set(texts)), len(texts), "two identical options is not a choice")
        self.assertTrue(all(text.startswith("Style") for text in texts))

    def test_the_section_hides_when_nothing_needs_deciding(self) -> None:
        rows = [(_Clip("cd_phm_sword_00_01_sit_std_weapon_in_00"),
                 _Clip("cd_phm_lswd_00_01_sit_std_weapon_in_00"))]
        dialog = MoveWeaponDialog(
            parts=[("p", "p")], positions=_POSITIONS, current_part="p",
            current_socket="Pelvis_L_Socket",
            pairs_for=lambda locomotion=False: rows, handedness="1h",
        )

        self.assertEqual(dialog._choices, {})
        self.assertNotIn("need a choice", dialog._count_label.text())

    def test_the_count_points_at_the_rows_needing_a_decision(self) -> None:
        self.assertIn("need a choice", self._with_choice()._count_label.text())

    def test_the_first_option_is_the_default(self) -> None:
        dialog = self._with_choice()

        donors = [donor.name for _target, donor in dialog.plan().clips]

        self.assertIn("cd_phm_longsword_00_01_normal_stand_weapon_out_000", donors)

    def test_choosing_another_option_changes_what_is_applied(self) -> None:
        dialog = self._with_choice()

        next(iter(dialog._choices.values())).box.setCurrentIndex(1)

        donors = [donor.name for _target, donor in dialog.plan().clips]
        self.assertIn("cd_phm_longsword_01_03_normal_stand_weapon_out_000", donors)
        self.assertNotIn("cd_phm_longsword_00_01_normal_stand_weapon_out_000", donors)

    def test_unticking_an_ambiguous_row_drops_it(self) -> None:
        from PySide6.QtCore import Qt as _Qt

        dialog = self._with_choice()
        item = next(i for i, _t, s in dialog._rows if isinstance(s, tuple))

        item.setCheckState(_Qt.Unchecked)

        self.assertEqual(len(dialog.plan().clips), 1)
