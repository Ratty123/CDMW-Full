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
        self.assertEqual(len(dialog._rows), len(_DRAWS))

        dialog._everything.setChecked(True)
        wider = sum(len(m) for _i, m, _c in dialog._rows)
        self.assertEqual(wider, len(_ALL))

        dialog._draws_only.setChecked(True)
        self.assertEqual(sum(len(m) for _i, m, _c in dialog._rows), len(_DRAWS))

    def test_the_plan_carries_exactly_what_is_ticked(self) -> None:
        dialog = _dialog()
        dialog._everything.setChecked(True)

        dialog._set_all(False)
        self.assertEqual(dialog.plan().clips, ())

        dialog._rows[0][0].setCheckState(0, Qt.Checked)
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
        self.assertEqual(sum(len(m) for _i, m, _c in dialog._rows), 2)

    def test_the_decisions_are_lifted_out_of_the_file_list(self) -> None:
        """Hunting through hundreds of rows for the few that ask something is not a UI."""

        dialog = self._with_choice()

        self.assertEqual(len(dialog._choices), 1)
        # The picker sits on the row it belongs to, not in a second list above it.
        row = next(i for i, _m, c in dialog._rows if c is not None)
        self.assertIsNotNone(dialog._clip_list.itemWidget(row, 1))

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

    def test_no_picker_appears_when_nothing_needs_deciding(self) -> None:
        rows = [(_Clip("cd_phm_sword_00_01_sit_std_weapon_in_00"),
                 _Clip("cd_phm_lswd_00_01_sit_std_weapon_in_00"))]
        dialog = MoveWeaponDialog(
            parts=[("p", "p")], positions=_POSITIONS, current_part="p",
            current_socket="Pelvis_L_Socket",
            pairs_for=lambda locomotion=False: rows, handedness="1h",
        )

        self.assertEqual(dialog._choices, {})
        self.assertIsNone(dialog._clip_list.itemWidget(dialog._rows[0][0], 1))

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
        item = next(i for i, _m, c in dialog._rows if c is not None)

        item.setCheckState(0, _Qt.Unchecked)

        self.assertEqual(len(dialog.plan().clips), 1)


class ItemSwitchTests(unittest.TestCase):
    """Changing the item must move the "from" state with it.

    The dialog kept showing the socket of whichever row was selected when it opened, and
    `plan()` compared the destination against *that*. Picking another row and choosing its
    own current socket therefore produced no move at all, silently.
    """

    def _dialog(self) -> MoveWeaponDialog:
        return MoveWeaponDialog(
            parts=[("Sword", "Sword"), ("Axe", "Axe")],
            positions=_POSITIONS,
            current_part="Sword",
            current_socket="Pelvis_L_Socket",
            part_sockets={"Sword": "Pelvis_L_Socket", "Axe": "Spine2_B_MainWeapon_Socket"},
            pairs_for=lambda locomotion=False: [],
            handedness="1h",
        )

    def test_the_from_line_follows_the_selected_item(self) -> None:
        dialog = self._dialog()
        self.assertEqual(dialog._from_label.text(), "Pelvis_L_Socket")

        dialog._part_box.setCurrentIndex(dialog._part_box.findData("Axe"))

        self.assertEqual(dialog._from_label.text(), "Spine2_B_MainWeapon_Socket")

    def test_moving_the_second_item_is_not_swallowed(self) -> None:
        dialog = self._dialog()
        dialog._part_box.setCurrentIndex(dialog._part_box.findData("Axe"))

        dialog._to_box.setCurrentIndex(dialog._to_box.findData("Pelvis_L_Socket"))

        plan = dialog.plan()
        self.assertEqual(plan.part_name, "Axe")
        self.assertEqual(plan.socket, "Pelvis_L_Socket")
        self.assertTrue(plan.moves)

    def test_choosing_the_item_s_own_socket_is_still_a_no_op(self) -> None:
        dialog = self._dialog()

        dialog._part_box.setCurrentIndex(dialog._part_box.findData("Axe"))

        self.assertEqual(dialog.plan().socket, "", "it already hangs there")


class LaneTests(unittest.TestCase):
    """Rows are grouped under what they have in common, and say only what differs.

    Every row used to open with its own context — twelve reading "Standing — put the weapon
    away, version 4" — so the part that distinguished them sat at the end of a sentence that
    was identical every time.
    """

    def _dialog(self) -> MoveWeaponDialog:
        rows = [
            (_Clip("cd_phm_sword_00_01_normal_stand_weapon_out_000"),
             _Clip("cd_phm_longsword_00_01_normal_stand_weapon_out_000")),
            (_Clip("cd_phm_sword_00_01_normal_stand_weapon_in_002_lod"),
             _Clip("cd_phm_longsword_00_01_normal_stand_weapon_in_002_lod")),
            (_Clip("cd_phm_sword_00_01_sit_std_weapon_in_00"),
             _Clip("cd_phm_lswd_00_01_sit_std_weapon_in_00")),
        ]
        return MoveWeaponDialog(
            parts=[("p", "p")], positions=_POSITIONS, current_part="p",
            current_socket="Pelvis_L_Socket",
            pairs_for=lambda locomotion=False: rows, handedness="1h",
        )

    def _lanes(self, dialog):
        tree = dialog._clip_list
        return {tree.topLevelItem(i).text(0).split("   (")[0]: tree.topLevelItem(i)
                for i in range(tree.topLevelItemCount())}

    def test_rows_sit_under_their_context(self) -> None:
        lanes = self._lanes(self._dialog())

        self.assertIn("Standing still", lanes)
        self.assertIn("In a low stance", lanes)
        self.assertEqual(lanes["Standing still"].childCount(), 2)

    def test_a_lane_counts_what_is_in_it(self) -> None:
        tree = self._dialog()._clip_list
        titles = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]

        self.assertTrue(any("(2)" in title for title in titles))

    def test_a_row_never_repeats_its_lane(self) -> None:
        lane = self._lanes(self._dialog())["Standing still"]

        for i in range(lane.childCount()):
            self.assertNotIn("Standing still", lane.child(i).text(0))

    def test_what_makes_a_row_different_is_what_it_says(self) -> None:
        lane = self._lanes(self._dialog())["Standing still"]
        texts = [lane.child(i).text(0) for i in range(lane.childCount())]

        joined = " ".join(texts)
        self.assertIn("Drawing", joined)
        self.assertIn("Sheathing", joined)

    def test_every_row_can_be_watched_not_only_the_ambiguous_ones(self) -> None:
        played = []
        rows = [(_Clip("cd_phm_sword_00_01_sit_std_weapon_in_00"),
                 _Clip("cd_phm_lswd_00_01_sit_std_weapon_in_00"))]
        dialog = MoveWeaponDialog(
            parts=[("p", "p")], positions=_POSITIONS, current_part="p",
            current_socket="Pelvis_L_Socket", pairs_for=lambda locomotion=False: rows,
            handedness="1h", on_preview=lambda entry: played.append(entry.name),
        )

        dialog._clip_list.setCurrentItem(dialog._rows[0][0])
        dialog._watch_selected()

        self.assertEqual(played, ["cd_phm_lswd_00_01_sit_std_weapon_in_00"])

    def test_selecting_a_lane_heading_plays_nothing(self) -> None:
        played = []
        dialog = self._dialog()
        dialog._on_preview = lambda entry: played.append(entry)

        dialog._clip_list.setCurrentItem(dialog._clip_list.topLevelItem(0))
        dialog._watch_selected()

        self.assertEqual(played, [])


class RowWatchTests(unittest.TestCase):
    """Every row carries its own Watch, because reading the list is what it is for."""

    def _dialog(self, played):
        rows = [
            (_Clip("cd_phm_sword_00_01_normal_stand_weapon_out_000"),
             _Clip("cd_phm_longsword_00_01_normal_stand_weapon_out_000")),
            (_Clip("cd_phm_sword_00_01_sit_std_weapon_in_00"),
             _Clip("cd_phm_lswd_00_01_sit_std_weapon_in_00")),
        ]
        return MoveWeaponDialog(
            parts=[("p", "p")], positions=_POSITIONS, current_part="p",
            current_socket="Pelvis_L_Socket", pairs_for=lambda locomotion=False: rows,
            handedness="1h", on_preview=lambda entry: played.append(entry.name),
        )

    def test_each_row_has_its_own_button(self) -> None:
        dialog = self._dialog([])
        tree = dialog._clip_list

        for item, _members, _choice in dialog._rows:
            self.assertIsNotNone(tree.itemWidget(item, 2), "a row with nothing to press")

    def test_a_lane_heading_has_no_button(self) -> None:
        dialog = self._dialog([])
        tree = dialog._clip_list

        for i in range(tree.topLevelItemCount()):
            self.assertIsNone(tree.itemWidget(tree.topLevelItem(i), 2))

    def test_pressing_it_plays_that_row_s_stand_in(self) -> None:
        played = []
        dialog = self._dialog(played)
        tree = dialog._clip_list

        tree.itemWidget(dialog._rows[1][0], 2).click()

        self.assertEqual(played, ["cd_phm_lswd_00_01_sit_std_weapon_in_00"])

    def test_no_buttons_when_there_is_nowhere_to_play_them(self) -> None:
        rows = [(_Clip("cd_phm_sword_00_01_sit_std_weapon_in_00"),
                 _Clip("cd_phm_lswd_00_01_sit_std_weapon_in_00"))]
        dialog = MoveWeaponDialog(
            parts=[("p", "p")], positions=_POSITIONS, current_part="p",
            current_socket="Pelvis_L_Socket", pairs_for=lambda locomotion=False: rows,
            handedness="1h",
        )

        self.assertIsNone(dialog._clip_list.itemWidget(dialog._rows[0][0], 2))


class RowMergeTests(unittest.TestCase):
    """One row per thing you can decide, and no two rows in a lane reading alike.

    Takes and distance copies of the same moment share a row, because the game picks between
    those for itself. Different weapons do not, because they are different decisions — but
    then they must say which weapon, or the list is a wall of identical lines.
    """

    def _dialog(self) -> MoveWeaponDialog:
        rows = [
            # Two takes plus a distance copy: one row.
            (_Clip("cd_phm_sword_00_01_normal_stand_weapon_out_000"),
             _Clip("cd_phm_longsword_00_01_normal_stand_weapon_out_000")),
            (_Clip("cd_phm_sword_00_01_normal_stand_weapon_out_002"),
             _Clip("cd_phm_longsword_00_01_normal_stand_weapon_out_002")),
            (_Clip("cd_phm_sword_00_01_normal_stand_weapon_out_002_lod"),
             _Clip("cd_phm_longsword_00_01_normal_stand_weapon_out_002_lod")),
            # A different weapon doing the same thing: its own row.
            (_Clip("cd_phm_dualsword_00_01_nor_stand_weapon_out_00"),
             _Clip("cd_phm_longsword_00_01_normal_stand_weapon_out_000")),
        ]
        return MoveWeaponDialog(
            parts=[("p", "p")], positions=_POSITIONS, current_part="p",
            current_socket="Pelvis_L_Socket", pairs_for=lambda locomotion=False: rows,
            handedness="1h",
        )

    def test_takes_and_distance_copies_share_a_row(self) -> None:
        dialog = self._dialog()

        self.assertEqual(len(dialog._rows), 2, "three takes are one decision, not three")

    def test_no_two_rows_in_a_lane_read_alike(self) -> None:
        tree = self._dialog()._clip_list

        for i in range(tree.topLevelItemCount()):
            lane = tree.topLevelItem(i)
            texts = [lane.child(j).text(0) for j in range(lane.childCount())]
            self.assertEqual(len(set(texts)), len(texts), f"repeated row under {lane.text(0)}")

    def test_rows_that_would_read_alike_name_their_weapon(self) -> None:
        tree = self._dialog()._clip_list
        lane = tree.topLevelItem(0)
        texts = [lane.child(j).text(0).lower() for j in range(lane.childCount())]

        self.assertTrue(any("dual swords" in text for text in texts))

    def test_a_merged_row_still_carries_every_file(self) -> None:
        self.assertEqual(len(self._dialog().plan().clips), 4, "merging must not drop files")

    def test_a_row_says_how_many_files_it_stands_for(self) -> None:
        tree = self._dialog()._clip_list
        texts = [
            tree.topLevelItem(i).child(j).text(0)
            for i in range(tree.topLevelItemCount())
            for j in range(tree.topLevelItem(i).childCount())
        ]

        self.assertTrue(any("3 files" in text for text in texts))


class BorrowedRowTests(unittest.TestCase):
    """A row using the other character's animation says so on its face.

    The clip plays — the two rigs share 403 bone names — but `.paa` keys are bind-pose deltas,
    so on different proportions the same rotations land somewhere slightly different. Somebody
    about to ship a mod built on one should learn that from the row, not from a commit message.
    """

    @staticmethod
    def _entry(name: str):
        class _E:
            pass

        entry = _E()
        entry.name = name
        entry.path = f"character/motion/1_pc/2_phw/{name}.paa"
        entry.category = "draw"
        return entry

    def _dialog(self, pairs):
        return MoveWeaponDialog(
            parts=[("CD_MainWeapon_Sword_R", "Sword")],
            positions=[("Pelvis_L_Socket", "Hip — left")],
            current_part="CD_MainWeapon_Sword_R",
            pairs_for=lambda **_k: pairs,
            handedness="1h",
        )

    @staticmethod
    def _rows(dialog):
        tree = dialog._clip_list
        out = []
        for i in range(tree.topLevelItemCount()):
            lane = tree.topLevelItem(i)
            out.extend(lane.child(j) for j in range(lane.childCount()))
        return out

    def test_a_borrowed_row_is_marked(self) -> None:
        target = self._entry("cd_phw_rpr_00_01_nor_std_weapon_out_00")
        donor = self._entry("cd_phm_lswd_00_01_nor_std_weapon_out_00")
        dialog = self._dialog([(target, donor, (donor,))])

        rows = self._rows(dialog)
        self.assertTrue(rows, "the dialog listed nothing")
        self.assertIn("borrowed", rows[0].text(0).lower())
        self.assertIn("different proportions", rows[0].toolTip(0))

    def test_a_same_character_row_is_not_marked(self) -> None:
        target = self._entry("cd_phw_rpr_00_01_nor_std_weapon_out_00")
        donor = self._entry("cd_phw_lswd_00_01_nor_std_weapon_out_00")
        dialog = self._dialog([(target, donor, (donor,))])

        rows = self._rows(dialog)
        self.assertTrue(rows)
        self.assertNotIn("borrowed", rows[0].text(0).lower())

    def test_the_file_names_stay_in_the_tooltip(self) -> None:
        """The caveat is added to what was there, not swapped for it."""

        target = self._entry("cd_phw_rpr_00_01_nor_std_weapon_out_00")
        donor = self._entry("cd_phm_lswd_00_01_nor_std_weapon_out_00")
        dialog = self._dialog([(target, donor, (donor,))])

        tip = self._rows(dialog)[0].toolTip(0)
        self.assertIn(target.name, tip)
        self.assertIn(donor.name, tip)
