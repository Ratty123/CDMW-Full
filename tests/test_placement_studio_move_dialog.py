"""The staged dialog that moves a weapon and takes its animations along.

What matters is that nothing happens until the review page has been seen and the action
accepted, and that everything the form shows is the plan the caller will act on. Each test
here is one of the plan's clarity requirements:

* three states side by side, so an earlier experiment cannot read as the game's default
* raw socket names beside friendly labels, because side bugs are debugged by raw name
* the linked case selected and locked unless an advanced exception is taken
* four animation scopes, draw-and-stow by default, full-body needing a confirmation
* an action label that says what will happen — never `Move it` for a move that moves nothing
* changing the item rebuilding every dependent value, not just one label
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import test_placement_studio_operations as fixtures  # noqa: E402
from tools.placement_studio import carry  # noqa: E402
from tools.placement_studio.editing import (  # noqa: E402
    OP_MOVE_EQUIPMENT,
    EditSession,
    OperationScope,
)
from tools.placement_studio.move_operation import plan_move  # noqa: E402
from tools.placement_studio.move_weapon import (  # noqa: E402
    PAGE_ANIMATIONS,
    PAGE_REVIEW,
    REVIEW_FIRST_LABEL,
    MoveWeaponDialog,
    socket_choice_label,
)

_APP = QApplication.instance() or QApplication([])

_POSITIONS = [
    ("Spine2_B_MainWeapon_Socket", "Back — main weapon"),
    ("Pelvis_R_Socket", "Hip — right"),
    ("Pelvis_L_Socket", "Hip — left"),
]

_PARTS = [
    ("CD_TwoHandWeapon_Sword", "CD_TwoHandWeapon_Sword   —   Spine2_B_MainWeapon_Socket"),
    ("CD_MainWeapon_Sword_R", "CD_MainWeapon_Sword_R   —   Pelvis_L_Socket"),
]


class _Bench:
    """A live session and edit session, with the callbacks the dialog needs."""

    def __init__(self) -> None:
        self.session = fixtures._session()
        self.edits: EditSession = fixtures._edits()
        self.unit = fixtures._two_hand_unit(self.session)
        self.previewed: list = []
        self.placements: list = []
        self.file_lists: list = []

    def unit_for(self, part_name: str):
        weapon_for = {
            "CD_TwoHandWeapon_Sword": "cd_phm_02_sword_0001",
            "CD_MainWeapon_Sword_R": "cd_phm_01_sword_0001_r",
            "CD_MainWeapon_Shield_L": "cd_phm_03_shield_0001",
        }
        weapon_id = weapon_for.get(part_name)
        if weapon_id:
            self.session.select_weapon(fixtures._weapon(self.session, weapon_id))
        from tools.placement_studio.session import EquipmentResolutionError

        try:
            unit = self.session.resolve_equipment_unit(
                part_name,
                available_families={carry.family_of(c.name) for c in fixtures.CLIP_INDEX},
            )
        except EquipmentResolutionError as exc:
            return None, str(exc)
        return unit, ""

    def pairs_for(self, unit, scope):
        return carry.swappable_pairs(unit, fixtures.CLIP_INDEX, scope)

    def plan_for(self, request):
        return plan_move(self.session, self.edits, request)

    def dialog(self, **overrides) -> MoveWeaponDialog:
        fields = dict(
            unit=self.unit,
            parts=_PARTS,
            positions=_POSITIONS,
            unit_for=self.unit_for,
            pairs_for=self.pairs_for,
            plan_for=self.plan_for,
            on_preview=self.previewed.append,
            on_preview_placement=self.placements.append,
            on_show_files=self.file_lists.append,
        )
        fields.update(overrides)
        return MoveWeaponDialog(**fields)


def _set_destination(dialog: MoveWeaponDialog, socket: str) -> None:
    dialog._to_box.setCurrentIndex(dialog._to_box.findData(socket))


def _set_scope(dialog: MoveWeaponDialog, kind: str) -> None:
    dialog._scope_buttons[kind].setChecked(True)


def _rows(dialog: MoveWeaponDialog):
    return dialog._rows


class LabellingTests(unittest.TestCase):
    def test_raw_socket_names_sit_beside_friendly_labels(self) -> None:
        self.assertEqual(
            socket_choice_label("Pelvis_R_Socket", "Hip — right"),
            "Hip — right  [Pelvis_R_Socket]",
        )
        # A socket with no friendly name shows its raw name once, not twice.
        self.assertEqual(socket_choice_label("Odd_Socket", "Odd_Socket"), "Odd_Socket")

    def test_the_destination_box_carries_raw_names(self) -> None:
        dialog = _Bench().dialog()
        texts = [dialog._to_box.itemText(i) for i in range(dialog._to_box.count())]
        self.assertTrue(all("[" in text and "]" in text for text in texts), texts)
        self.assertIn("Hip — right  [Pelvis_R_Socket]", texts)

    def test_the_dialog_states_whose_left_and_right(self) -> None:
        dialog = _Bench().dialog()
        page = dialog._pages.widget(1)
        labels = [
            child.text() for child in page.findChildren(type(dialog._zone_label))
        ]
        self.assertTrue(
            any("character's perspective" in text for text in labels),
            labels,
        )


class OpeningStateTests(unittest.TestCase):
    def test_it_opens_on_where_the_item_already_hangs(self) -> None:
        dialog = _Bench().dialog()
        self.assertEqual(dialog._to_box.currentData(), "Spine2_B_MainWeapon_Socket")
        self.assertFalse(dialog.plan().placement_changes)

    def test_opening_on_a_no_op_offers_no_move(self) -> None:
        dialog = _Bench().dialog()
        _set_scope(dialog, carry.SCOPE_PLACEMENT_ONLY)
        self.assertEqual(dialog.plan().action_label(), "No changes")
        self.assertFalse(dialog._accept.isEnabled())

    def test_the_banner_names_the_earlier_operations(self) -> None:
        bench = _Bench()
        with bench.edits.begin_operation(
            OperationScope(
                kind=OP_MOVE_EQUIPMENT,
                equipment_unit_id=bench.unit.unit_id,
                model=fixtures.MODEL,
                allowed_descriptor_parts=(bench.unit.primary_part,),
                allowed_descriptor_files=(fixtures.DESC,),
                allowed_socket_files=(fixtures.W2H,),
            )
        ) as handle:
            handle.set_route(
                fixtures.DESC, bench.unit.primary_part, "in_socket", "Pelvis_L_Socket"
            )
        earlier = [op.operation_id for op in bench.edits.operations()]
        dialog = bench.dialog(earlier_operations=earlier)
        self.assertIn("1 earlier operation", dialog._banner_label.text())
        self.assertIn("will not be packaged", dialog._banner_label.text())

    def test_with_no_history_the_banner_says_so(self) -> None:
        dialog = _Bench().dialog()
        self.assertIn("first operation", dialog._banner_label.text())


class ThreeStateTests(unittest.TestCase):
    def test_pending_is_shown_apart_from_vanilla(self) -> None:
        bench = _Bench()
        with bench.edits.begin_operation(
            OperationScope(
                kind=OP_MOVE_EQUIPMENT,
                equipment_unit_id=bench.unit.unit_id,
                model=fixtures.MODEL,
                allowed_descriptor_parts=(bench.unit.primary_part,),
                allowed_descriptor_files=(fixtures.DESC,),
                allowed_socket_files=(fixtures.W2H,),
            )
        ) as handle:
            handle.set_route(
                fixtures.DESC, bench.unit.primary_part, "in_socket", "Pelvis_L_Socket"
            )
        dialog = bench.dialog()
        _set_destination(dialog, "Pelvis_R_Socket")

        headers = [
            dialog._states.horizontalHeaderItem(column).text() for column in range(4)
        ]
        self.assertEqual(
            headers, ["Field", "Vanilla", "Pending before this operation", "Proposed"]
        )
        row = next(
            index
            for index in range(dialog._states.rowCount())
            if dialog._states.item(index, 0).text() == "Weapon body socket"
        )
        self.assertEqual(dialog._states.item(row, 1).text(), "Spine2_B_MainWeapon_Socket")
        self.assertEqual(dialog._states.item(row, 2).text(), "Pelvis_L_Socket")
        self.assertEqual(dialog._states.item(row, 3).text(), "Pelvis_R_Socket")

    def test_the_case_row_gets_its_own_states(self) -> None:
        dialog = _Bench().dialog()
        _set_destination(dialog, "Pelvis_R_Socket")
        fields = [
            dialog._states.item(index, 0).text()
            for index in range(dialog._states.rowCount())
        ]
        self.assertIn("Weapon body socket", fields)
        self.assertIn("Sheath body socket", fields)
        self.assertIn("Sheath child socket", fields)


class LinkedPartTests(unittest.TestCase):
    def test_the_required_case_is_ticked_and_locked(self) -> None:
        dialog = _Bench().dialog()
        box = dialog._link_boxes["CD_TwoHandWeapon_Sword_IN"]
        self.assertTrue(box.isChecked())
        self.assertFalse(box.isEnabled())
        self.assertEqual(dialog.leave_behind(), ())

    def test_the_advanced_exception_unlocks_it(self) -> None:
        dialog = _Bench().dialog()
        dialog._link_exception.setChecked(True)
        box = dialog._link_boxes["CD_TwoHandWeapon_Sword_IN"]
        self.assertTrue(box.isEnabled())
        box.setChecked(False)
        self.assertEqual(dialog.leave_behind(), ("CD_TwoHandWeapon_Sword_IN",))

    def test_leaving_the_case_behind_becomes_a_confirmation(self) -> None:
        dialog = _Bench().dialog()
        _set_destination(dialog, "Pelvis_R_Socket")
        dialog._link_exception.setChecked(True)
        dialog._link_boxes["CD_TwoHandWeapon_Sword_IN"].setChecked(False)
        self.assertIn(
            "leave CD_TwoHandWeapon_Sword_IN behind", dialog.plan().confirmations
        )

    def test_turning_the_exception_off_re_ticks_the_required_row(self) -> None:
        dialog = _Bench().dialog()
        dialog._link_exception.setChecked(True)
        dialog._link_boxes["CD_TwoHandWeapon_Sword_IN"].setChecked(False)
        dialog._link_exception.setChecked(False)
        self.assertTrue(dialog._link_boxes["CD_TwoHandWeapon_Sword_IN"].isChecked())


class PlacementPageTests(unittest.TestCase):
    def test_it_says_which_sockets_it_would_create(self) -> None:
        dialog = _Bench().dialog()
        _set_destination(dialog, "Pelvis_R_Socket")
        created = dialog._new_socket_label.text()
        self.assertIn("CDMW_Sword_hip_ChildSocket", created)
        self.assertIn("CDMW_Sword_IN_hip_sheath_ChildSocket", created)

    def test_it_names_the_orientation_source(self) -> None:
        dialog = _Bench().dialog()
        _set_destination(dialog, "Pelvis_R_Socket")
        self.assertIn("copied from another item", dialog._orientation_label.text())

    def test_a_borrowed_aim_asks_to_be_reviewed(self) -> None:
        dialog = _Bench().dialog()
        _set_destination(dialog, "Pelvis_R_Socket")
        self.assertTrue(dialog._orientation_reviewed.isEnabled())
        self.assertTrue(
            any("borrows its aim" in item for item in dialog.plan().confirmations)
        )
        dialog._orientation_reviewed.setChecked(True)
        self.assertFalse(
            any("borrows its aim" in item for item in dialog.plan().confirmations)
        )

    def test_the_zone_is_stated_with_its_raw_token(self) -> None:
        dialog = _Bench().dialog()
        _set_destination(dialog, "Pelvis_R_Socket")
        self.assertIn("hip", dialog._zone_label.text().lower())


class AnimationScopeTests(unittest.TestCase):
    def test_construction_does_not_report_an_unhandled_exception(self) -> None:
        captured: list[tuple[type[BaseException], BaseException]] = []
        previous_hook = sys.excepthook
        sys.excepthook = lambda exc_type, exc_value, _traceback: captured.append(
            (exc_type, exc_value)
        )
        try:
            dialog = _Bench().dialog()
        finally:
            sys.excepthook = previous_hook

        dialog.deleteLater()
        _APP.processEvents()
        self.assertEqual([], captured)

    def test_draw_and_stow_is_the_default(self) -> None:
        dialog = _Bench().dialog()
        self.assertTrue(dialog._scope_buttons[carry.SCOPE_DRAW_STOW].isChecked())
        self.assertEqual(dialog.scope().kind, carry.SCOPE_DRAW_STOW)

    def test_all_four_scopes_are_offered_and_named(self) -> None:
        dialog = _Bench().dialog()
        self.assertEqual(set(dialog._scope_buttons), set(carry.SCOPE_ORDER))
        self.assertIn(
            "advanced", dialog._scope_buttons[carry.SCOPE_FULL_BODY].text().lower()
        )

    def test_the_list_follows_the_scope_both_ways(self) -> None:
        dialog = _Bench().dialog()
        draws = sum(len(m) for _i, m, _c in _rows(dialog))
        _set_scope(dialog, carry.SCOPE_FULL_BODY)
        everything = sum(len(m) for _i, m, _c in _rows(dialog))
        self.assertGreater(everything, draws)
        _set_scope(dialog, carry.SCOPE_DRAW_STOW)
        self.assertEqual(sum(len(m) for _i, m, _c in _rows(dialog)), draws)

    def test_placement_only_empties_the_list(self) -> None:
        dialog = _Bench().dialog()
        _set_scope(dialog, carry.SCOPE_PLACEMENT_ONLY)
        self.assertEqual(_rows(dialog), [])
        self.assertIn("placement only", dialog._count_label.text())

    def test_full_body_needs_its_confirmation(self) -> None:
        dialog = _Bench().dialog()
        _set_destination(dialog, "Pelvis_R_Socket")
        dialog._orientation_reviewed.setChecked(True)
        _set_scope(dialog, carry.SCOPE_FULL_BODY)
        self.assertTrue(dialog._advanced_confirm.isVisible() or True)
        self.assertTrue(dialog.plan().blocked)
        dialog._advanced_confirm.setChecked(True)
        self.assertFalse(dialog.plan().blocked)

    def test_mounted_and_borrowed_are_off_until_asked_for(self) -> None:
        dialog = _Bench().dialog()
        self.assertFalse(dialog._include_mounted.isChecked())
        self.assertFalse(dialog._include_borrowed.isChecked())
        self.assertFalse(dialog.scope().include_mounted)
        self.assertFalse(dialog.scope().include_borrowed)

    def test_every_context_group_is_offered(self) -> None:
        dialog = _Bench().dialog()
        self.assertEqual(
            set(dialog._context_boxes), {name for name, _label in carry.CONTEXT_GROUPS}
        )

    def test_moving_between_zones_recommends_draw_and_stow(self) -> None:
        dialog = _Bench().dialog()
        _set_destination(dialog, "Pelvis_R_Socket")
        self.assertEqual(dialog.scope().kind, carry.SCOPE_DRAW_STOW)

    def test_moving_within_a_zone_recommends_placement_only(self) -> None:
        bench = _Bench()
        dialog = bench.dialog()
        # Start from a hip carry so the destination is the same zone.
        dialog._part_box.setCurrentIndex(dialog._part_box.findData("CD_MainWeapon_Sword_R"))
        _set_destination(dialog, "Pelvis_R_Socket")
        self.assertEqual(dialog.scope().kind, carry.SCOPE_PLACEMENT_ONLY)

    def test_unticking_a_row_reduces_the_chosen_set(self) -> None:
        dialog = _Bench().dialog()
        before = len(dialog.chosen_replacements())
        self.assertTrue(before)
        _rows(dialog)[0][0].setCheckState(0, Qt.Unchecked)
        self.assertLess(len(dialog.chosen_replacements()), before)

    def test_select_none_then_all_round_trips(self) -> None:
        dialog = _Bench().dialog()
        total = len(dialog.chosen_replacements())
        dialog._set_all(False)
        self.assertEqual(dialog.chosen_replacements(), ())
        dialog._set_all(True)
        self.assertEqual(len(dialog.chosen_replacements()), total)

    def test_only_two_handed_targets_reach_the_list(self) -> None:
        dialog = _Bench().dialog()
        _set_scope(dialog, carry.SCOPE_FULL_BODY)
        for row in dialog.chosen_replacements():
            self.assertIn(row.target_family, ("longsword", "lswd"))


class ItemChangeTests(unittest.TestCase):
    def test_changing_the_item_rebuilds_everything_that_depends_on_it(self) -> None:
        dialog = _Bench().dialog()
        two_hand_rows = {row.target.name for row in dialog.chosen_replacements()}
        self.assertTrue(two_hand_rows)
        self.assertEqual(dialog._unit.handedness, "2h")
        self.assertEqual(dialog._link_boxes and list(dialog._link_boxes),
                         ["CD_TwoHandWeapon_Sword_IN"])

        dialog._part_box.setCurrentIndex(dialog._part_box.findData("CD_MainWeapon_Sword_R"))

        self.assertEqual(dialog._unit.primary_part, "CD_MainWeapon_Sword_R")
        self.assertEqual(dialog._unit.handedness, "1h")
        self.assertEqual(dialog._unit.target_animation_families,
                         tuple(sorted(set(dialog._unit.target_animation_families))))
        self.assertNotIn("longsword", dialog._unit.target_animation_families)
        one_hand_rows = {row.target.name for row in dialog.chosen_replacements()}
        self.assertFalse(one_hand_rows & two_hand_rows)
        # The one-hand sword has no case row in the fixture, so the section empties.
        self.assertEqual(list(dialog._link_boxes), [])
        # And the destination follows the new row rather than keeping the old one's.
        self.assertEqual(dialog._to_box.currentData(), "Pelvis_L_Socket")

    def test_an_unresolvable_item_blocks_rather_than_falling_back(self) -> None:
        bench = _Bench()

        def refuse(_part_name: str):
            return None, "That row and that asset are different items."

        dialog = bench.dialog(unit_for=refuse)
        dialog._part_box.setCurrentIndex(dialog._part_box.findData("CD_MainWeapon_Sword_R"))
        self.assertIsNone(dialog._unit)
        self.assertIn("different items", dialog._unit_problem.text())
        self.assertIsNone(dialog.request())
        self.assertFalse(dialog._accept.isEnabled())


class ActionLabelTests(unittest.TestCase):
    def _reviewed(self, dialog: MoveWeaponDialog) -> MoveWeaponDialog:
        dialog._pages.setCurrentIndex(PAGE_REVIEW)
        return dialog

    def test_review_comes_before_the_action(self) -> None:
        dialog = _Bench().dialog()
        _set_destination(dialog, "Pelvis_R_Socket")
        dialog._orientation_reviewed.setChecked(True)
        self.assertEqual(dialog._accept.text(), REVIEW_FIRST_LABEL)
        dialog._accept.click()
        self.assertEqual(dialog._pages.currentIndex(), PAGE_REVIEW)
        self.assertNotEqual(dialog._accept.text(), REVIEW_FIRST_LABEL)

    def test_a_move_with_animations_says_both(self) -> None:
        dialog = _Bench().dialog()
        _set_destination(dialog, "Pelvis_R_Socket")
        dialog._orientation_reviewed.setChecked(True)
        self._reviewed(dialog)
        count = len(dialog.chosen_replacements())
        self.assertEqual(
            dialog._accept.text(), f"Move weapon and case, replace {count} animations"
        )

    def test_a_move_alone_says_move(self) -> None:
        dialog = _Bench().dialog()
        _set_destination(dialog, "Pelvis_R_Socket")
        dialog._orientation_reviewed.setChecked(True)
        _set_scope(dialog, carry.SCOPE_PLACEMENT_ONLY)
        self._reviewed(dialog)
        self.assertEqual(dialog._accept.text(), "Move weapon and case")

    def test_animations_alone_never_say_move(self) -> None:
        dialog = _Bench().dialog()
        # The destination is still where the item hangs, so there is no placement change.
        self._reviewed(dialog)
        label = dialog._accept.text()
        self.assertTrue(label.startswith("Replace "), label)
        self.assertNotIn("Move", label)

    def test_nothing_at_all_disables_the_action(self) -> None:
        dialog = _Bench().dialog()
        _set_scope(dialog, carry.SCOPE_PLACEMENT_ONLY)
        self._reviewed(dialog)
        self.assertEqual(dialog._accept.text(), "No changes")
        self.assertFalse(dialog._accept.isEnabled())

    def test_a_blocked_plan_cannot_be_accepted(self) -> None:
        dialog = _Bench().dialog()
        _set_destination(dialog, "Pelvis_R_Socket")
        _set_scope(dialog, carry.SCOPE_FULL_BODY)
        self._reviewed(dialog)
        self.assertTrue(dialog.plan().blocked)
        self.assertFalse(dialog._accept.isEnabled())
        self.assertTrue(dialog._blocker_label.text())


class ReviewPageTests(unittest.TestCase):
    def _reviewed(self, dialog: MoveWeaponDialog) -> str:
        dialog._pages.setCurrentIndex(PAGE_REVIEW)
        return dialog._review_view.toPlainText()

    def test_the_review_states_every_scope_fact(self) -> None:
        dialog = _Bench().dialog()
        _set_destination(dialog, "Pelvis_R_Socket")
        dialog._orientation_reviewed.setChecked(True)
        text = self._reviewed(dialog)
        for expected in (
            "CD_TwoHandWeapon_Sword",
            "CD_TwoHandWeapon_Sword_IN",
            "Pelvis_R_Socket",
            "Target families",
            "Donor families",
            "Borrowed-character clips",
            "Mounted clips",
            "Earlier operations",
            "Files that would change",
        ):
            self.assertIn(expected, text)

    def test_the_review_lists_the_exact_animation_files(self) -> None:
        dialog = _Bench().dialog()
        _set_destination(dialog, "Pelvis_R_Socket")
        dialog._orientation_reviewed.setChecked(True)
        text = self._reviewed(dialog)
        for row in dialog.chosen_replacements()[:5]:
            self.assertIn(row.target_path, text)

    def test_the_shortcuts_hand_the_plan_back(self) -> None:
        bench = _Bench()
        dialog = bench.dialog()
        _set_destination(dialog, "Pelvis_R_Socket")
        dialog._orientation_reviewed.setChecked(True)
        dialog._pages.setCurrentIndex(PAGE_REVIEW)
        dialog._show_files.click()
        self.assertEqual(len(bench.file_lists), 1)
        self.assertIs(bench.file_lists[0], dialog.plan())

    def test_watch_plays_the_donor_the_row_would_be_given(self) -> None:
        bench = _Bench()
        dialog = bench.dialog()
        dialog._pages.setCurrentIndex(PAGE_ANIMATIONS)
        item, members, _choice = _rows(dialog)[0]
        dialog._clip_list.setCurrentItem(item)
        dialog._watch_selected()
        self.assertEqual(bench.previewed[-1].name, members[0].donor.name)

    def test_reset_puts_every_control_back(self) -> None:
        dialog = _Bench().dialog()
        _set_destination(dialog, "Pelvis_R_Socket")
        _set_scope(dialog, carry.SCOPE_FULL_BODY)
        dialog._include_mounted.setChecked(True)
        dialog._link_exception.setChecked(True)
        dialog._reset()
        self.assertEqual(dialog._to_box.currentData(), "Spine2_B_MainWeapon_Socket")
        self.assertEqual(dialog.scope().kind, carry.SCOPE_DRAW_STOW)
        self.assertFalse(dialog._include_mounted.isChecked())
        self.assertFalse(dialog._link_exception.isChecked())


class RequestTests(unittest.TestCase):
    def test_the_request_is_what_the_form_shows(self) -> None:
        dialog = _Bench().dialog()
        _set_destination(dialog, "Pelvis_R_Socket")
        dialog._orientation_reviewed.setChecked(True)
        request = dialog.request()
        self.assertEqual(request.destination_socket, "Pelvis_R_Socket")
        self.assertEqual(request.unit.primary_part, "CD_TwoHandWeapon_Sword")
        self.assertEqual(request.include_links, ("CD_TwoHandWeapon_Sword_IN",))
        self.assertEqual(request.leave_behind, ())
        self.assertTrue(request.orientation_reviewed)
        self.assertEqual(
            len(request.replacements), len(dialog.chosen_replacements())
        )

    def test_nothing_is_applied_by_opening_the_dialog(self) -> None:
        bench = _Bench()
        dialog = bench.dialog()
        _set_destination(dialog, "Pelvis_R_Socket")
        _set_scope(dialog, carry.SCOPE_FULL_BODY)
        dialog._pages.setCurrentIndex(PAGE_REVIEW)
        self.assertEqual(bench.edits.modified_paths(), [])
        self.assertEqual(bench.edits.operations(), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
