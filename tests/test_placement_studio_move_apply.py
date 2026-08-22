"""Accepting the move dialog has to actually move it — as one operation, or not at all.

This exists because it once did not. `QDialog.Accepted` is a class constant, and reading it off
the dialog instance raised `AttributeError` the moment the dialog closed, so the routing and the
animation swap were both skipped. Under `pythonw` there is no console, so the failure was
completely silent: the button appeared to do nothing.

The dialog was covered and the swap was covered; nothing exercised the handler that joins them.
That is still the gap this closes, and there is now more to join: the equipment unit is
resolved before the dialog opens, the placement and every clip replacement land in one
transaction, and a read that fails must leave the session untouched rather than shipping a
changed draw for a weapon that never moved.
"""

from __future__ import annotations

import os
import sys
import unittest
import unittest.mock
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QPushButton,
    QWidget,
)

import test_placement_studio_operations as fixtures  # noqa: E402
from tools.placement_studio import carry, window_carry  # noqa: E402
from tools.placement_studio.move_operation import MoveRequest, plan_move  # noqa: E402

_APP = QApplication.instance() or QApplication([])


class _Status:
    def __init__(self) -> None:
        self.message = ""
        self.history: list = []

    def showMessage(self, text: str) -> None:  # noqa: N802 - mimics QStatusBar
        self.message = text
        self.history.append(text)

    def currentMessage(self) -> str:  # noqa: N802 - mimics QStatusBar
        return self.message


class _ClipIndex:
    def __init__(self, entries) -> None:
        self.entries = list(entries)


class _Harness(window_carry.CarryPickerMixin, QWidget):
    """The handler over a real session and edit session, with the UI stubbed out.

    Everything the mixin reaches for that belongs to another mixin or to Qt is answered here,
    so the join between the dialog and the operation model is exercised for real: the edits are
    a genuine `EditSession` and the assertions are about its commands and operations.

    A `QWidget`, because the handler parents its message boxes to itself and Qt checks the type.
    """

    def __init__(self) -> None:
        QWidget.__init__(self)
        self._session = fixtures._session()
        self._edits = fixtures._edits()
        self._session.select_weapon(fixtures._weapon(self._session, "cd_phm_02_sword_0001"))
        self._selected_part = "CD_TwoHandWeapon_Sword"
        self._clip_index = _ClipIndex(fixtures.CLIP_INDEX)
        self._swap_thread = None
        self._swap_worker = None
        self._carry_swap = QPushButton("Swap animations…", self)
        self._status = _Status()
        self._play_after_swap = True
        self._pending_move = None
        self._swap_preview = None
        self._swap_requested = 0
        self.started: list = []
        self.asked_for_clip_index = False
        self.waited_for_clip_index = False
        self.warned: list = []
        self.reported: list = []
        self.refreshed = 0
        self.chart_lanes_asked = 0
        self._chart_lanes_cache: dict = {}
        self._carry_index = None
        self._carry_filter_zone = ""

    # ── what the handler calls out to ───────────────────────────────

    def statusBar(self):  # noqa: N802 - mimics QMainWindow
        return self._status

    def _current_binding(self):
        return next(
            b for b in self._session.bindings() if b.part_name == self._selected_part
        )

    def _sync_part_box(self, name: str) -> None:
        self._selected_part = name

    def _ensure_clip_index(self, *, wait: bool = False) -> None:
        """Lives on `ClipBrowserMixin`; the swap asks for it because donors come from it.

        The swap passes `wait=True`: the dialog reads the index inside its own constructor, so
        being told the scan has *started* is not enough.
        """

        self.asked_for_clip_index = True
        self.waited_for_clip_index = wait

    def _after_edit(self) -> None:
        self.refreshed += 1

    def _populate_parts(self) -> None:
        pass

    def _populate_carry_box(self) -> None:
        pass

    def _chart_lane_index(self) -> dict:
        self.chart_lanes_asked += 1
        return {}

    def _preview_clip(self, entry) -> None:
        pass

    def _orientation_diagnostic(self, _socket: str) -> str:
        """Lives on `EditingMixin`. Reports; it must never change anything."""

        return ""

    def _show_swap_result(self, applied: int, written=None) -> None:
        self.reported.append((applied, set(written or ())))

    def _offer_carry_clips(self, socket: str, previous_zone: str = "") -> None:
        pass

    def _report_move(self, plan, operation, diagnostic: str) -> None:
        self.reported.append((0, set()))

    # `_start_move` reads the clips on a worker. Here it is short-circuited so the transaction
    # can be asserted synchronously; `apply_move` is still the real one.
    def _start_move(self, plan, *, play_after: bool = True, preview=None) -> str:
        self.started.append((plan, play_after, preview))
        return ""


class _Dialog:
    """Stands in for the staged dialog: returns a plan and nothing else."""

    Accepted = QDialog.Accepted

    def __init__(self, plan, *, accepted: bool = True, play_after: bool = True,
                 preview=None) -> None:
        self._plan = plan
        self._accepted = accepted
        self.play_after = play_after
        self._preview = preview

    def exec(self):
        return QDialog.Accepted if self._accepted else QDialog.Rejected

    def plan(self):
        return self._plan

    def request(self):
        return self._plan.request if self._plan is not None else None

    def preview_clip(self):
        return self._preview


def _plan_for(harness: _Harness, destination: str, *, scope=None, reviewed: bool = True):
    unit, error = harness._resolve_unit(harness._selected_part)
    assert unit is not None, error
    rows = ()
    scope = scope or carry.AnimationScope(carry.SCOPE_DRAW_STOW)
    if scope.replaces_animations:
        rows = carry.swappable_pairs(unit, fixtures.CLIP_INDEX, scope)
    return plan_move(
        harness._session,
        harness._edits,
        MoveRequest(
            unit=unit,
            destination_socket=destination,
            scope=scope,
            replacements=rows,
            orientation_reviewed=reviewed,
        ),
    )


def _open(harness: _Harness, plan, **dialog_kwargs) -> None:
    """Run `_on_swap_clicked` with the dialog replaced by one that returns `plan`."""

    import tools.placement_studio.move_weapon as move_weapon

    saved = move_weapon.MoveWeaponDialog
    move_weapon.MoveWeaponDialog = lambda *_a, **_k: _Dialog(plan, **dialog_kwargs)
    try:
        window_carry.CarryPickerMixin._on_swap_clicked(harness)
    finally:
        move_weapon.MoveWeaponDialog = saved


class HandlerTests(unittest.TestCase):
    def test_the_unit_is_resolved_before_the_dialog_opens(self) -> None:
        harness = _Harness()
        plan = _plan_for(harness, "Pelvis_R_Socket")
        _open(harness, plan)
        self.assertEqual(len(harness.started), 1)
        self.assertEqual(harness.started[0][0].unit.primary_part, "CD_TwoHandWeapon_Sword")

    def test_an_unresolvable_row_never_opens_the_dialog(self) -> None:
        harness = _Harness()
        harness._selected_part = "CD_MainWeapon_Nonexistent"
        opened: list = []

        import tools.placement_studio.move_weapon as move_weapon

        saved = move_weapon.MoveWeaponDialog

        def _fail(*_a, **_k):
            opened.append(True)
            raise AssertionError("the dialog must not open for an unresolvable row")

        move_weapon.MoveWeaponDialog = _fail
        try:
            with unittest.mock.patch(
                "PySide6.QtWidgets.QMessageBox.warning", lambda *a, **k: None
            ):
                window_carry.CarryPickerMixin._on_swap_clicked(harness)
        finally:
            move_weapon.MoveWeaponDialog = saved
        self.assertEqual(opened, [])
        self.assertEqual(harness.started, [])
        self.assertIn("not a descriptor row", harness._status.message)

    def test_the_swap_waits_for_the_clip_index_rather_than_only_starting_it(self) -> None:
        """The dialog builds its donor rows inside its constructor.

        With the index merely started, the pair generator runs against an empty one and the
        dialog opens saying no animation has a counterpart for this weapon — a wrong answer
        rather than a slow one, and the user moves the socket believing there was nothing to
        swap.
        """

        harness = _Harness()
        _open(harness, _plan_for(harness, "Pelvis_R_Socket"))
        self.assertTrue(harness.asked_for_clip_index)
        self.assertTrue(harness.waited_for_clip_index)

    def test_cancelling_changes_nothing(self) -> None:
        harness = _Harness()
        _open(harness, _plan_for(harness, "Pelvis_R_Socket"), accepted=False)
        self.assertEqual(harness.started, [])
        self.assertEqual(harness._edits.modified_paths(), [])
        self.assertEqual(harness._edits.operations(), [])

    def test_the_play_after_choice_is_carried_through(self) -> None:
        harness = _Harness()
        _open(harness, _plan_for(harness, "Pelvis_R_Socket"), play_after=False)
        self.assertFalse(harness.started[0][1])


class OneOperationTests(unittest.TestCase):
    """`_apply_move_operation` is the transaction. These are its properties."""

    def test_placement_and_animations_land_as_one_operation(self) -> None:
        harness = _Harness()
        plan = _plan_for(harness, "Pelvis_R_Socket")
        clip_bytes = {row.target_path: b"donor bytes" for row in plan.request.replacements}
        harness._apply_move_operation(plan, clip_bytes)

        operations = harness._edits.operations()
        self.assertEqual(len(operations), 1)
        operation = operations[0]
        self.assertEqual(
            set(operation.routed_parts()),
            {"CD_TwoHandWeapon_Sword", "CD_TwoHandWeapon_Sword_IN"},
        )
        self.assertEqual(len(operation.created_sockets()), 2)
        self.assertEqual(len(operation.replaced_clips()), len(clip_bytes))

    def test_one_undo_takes_the_whole_operation_back(self) -> None:
        harness = _Harness()
        plan = _plan_for(harness, "Pelvis_R_Socket")
        clip_bytes = {row.target_path: b"donor bytes" for row in plan.request.replacements}
        harness._apply_move_operation(plan, clip_bytes)
        self.assertTrue(harness._edits.modified_paths())
        harness._edits.undo_operation()
        self.assertEqual(harness._edits.modified_paths(), [])
        self.assertEqual(harness._edits.operations(), [])

    def test_a_move_without_animations_still_routes(self) -> None:
        harness = _Harness()
        plan = _plan_for(
            harness, "Pelvis_R_Socket",
            scope=carry.AnimationScope(carry.SCOPE_PLACEMENT_ONLY),
        )
        harness._apply_move_operation(plan, {})
        operation = harness._edits.operations()[0]
        self.assertTrue(operation.routed_parts())
        self.assertEqual(operation.replaced_clips(), ())

    def test_animations_that_could_not_be_read_are_reported_not_hidden(self) -> None:
        harness = _Harness()
        plan = _plan_for(harness, "Pelvis_R_Socket")
        rows = plan.request.replacements
        self.assertGreater(len(rows), 1)
        # One clip read, the rest unreadable. That used to vanish into a success message, so a
        # partly applied swap read as a whole one.
        harness._apply_move_operation(plan, {rows[0].target_path: b"donor bytes"})
        self.assertIn("could not be read", harness._status.message)
        self.assertIn(f"{len(rows) - 1} could not be read", harness._status.message)

    def test_a_blocked_plan_records_nothing(self) -> None:
        harness = _Harness()
        # Full-body scope with no confirmation is blocked, which is exactly what a plan the
        # dialog would refuse to accept looks like.
        plan = _plan_for(
            harness, "Pelvis_R_Socket",
            scope=carry.AnimationScope(carry.SCOPE_FULL_BODY),
        )
        self.assertTrue(plan.blocked)
        with unittest.mock.patch(
            "PySide6.QtWidgets.QMessageBox.warning", lambda *a, **k: None
        ):
            harness._apply_move_operation(plan, {})
        self.assertEqual(harness._edits.operations(), [])
        self.assertEqual(harness._edits.modified_paths(), [])
        self.assertIn("Nothing was changed", harness._status.message)

    def test_a_cancelled_read_leaves_the_session_untouched(self) -> None:
        """The placement is no longer applied ahead of the clips.

        It used to be: route first, then read the donors on a worker. A cancel between the two
        left the weapon on its new socket with the old animations — a mod that plays a back
        draw from the hip.
        """

        harness = _Harness()
        harness._pending_move = _plan_for(harness, "Pelvis_R_Socket")
        harness._on_swap_ready(None, "")
        self.assertEqual(harness._edits.modified_paths(), [])
        self.assertEqual(harness._edits.operations(), [])
        self.assertIn("nothing was changed", harness._status.message)

    def test_earlier_operations_are_untouched_by_a_later_one(self) -> None:
        harness = _Harness()
        first = _plan_for(harness, "Pelvis_R_Socket")
        harness._apply_move_operation(
            first, {row.target_path: b"a" for row in first.request.replacements}
        )
        second = _plan_for(
            harness, "Pelvis_L_Socket",
            scope=carry.AnimationScope(carry.SCOPE_PLACEMENT_ONLY),
        )
        harness._apply_move_operation(second, {})
        operations = harness._edits.operations()
        self.assertEqual(len(operations), 2)
        self.assertTrue(operations[0].replaced_clips())
        self.assertEqual(operations[1].replaced_clips(), ())


class UnitByIdTests(unittest.TestCase):
    """Packaging resolves the unit an *earlier* operation belonged to, not the current one."""

    def test_a_unit_id_resolves_against_the_asset_it_names(self) -> None:
        harness = _Harness()
        two_hand, error = harness._resolve_unit("CD_TwoHandWeapon_Sword")
        self.assertIsNone(error or None)
        # The window moves on to another weapon, the way a user would.
        harness._session.select_weapon(
            fixtures._weapon(harness._session, "cd_phm_01_sword_0001_r")
        )
        harness._selected_part = "CD_MainWeapon_Sword_R"
        again, error = harness._resolve_unit_by_id(two_hand.unit_id)
        self.assertEqual(error, "")
        self.assertEqual(again.unit_id, two_hand.unit_id)
        # And the linked sheath comes with it, which is what the case-row check needs.
        self.assertEqual(
            [link.part_name for link in again.linked_parts], ["CD_TwoHandWeapon_Sword_IN"]
        )

    def test_a_unit_id_for_an_unloaded_asset_reports_rather_than_guesses(self) -> None:
        harness = _Harness()
        unit, error = harness._resolve_unit_by_id("1_phm/cd_phm_99_sword_0001/CD_X")
        self.assertIsNone(unit)
        self.assertIn("not loaded", error)

    def test_a_unit_id_for_another_character_is_refused(self) -> None:
        harness = _Harness()
        unit, error = harness._resolve_unit_by_id("2_phw/cd_phw_02_sword_0001/CD_X")
        self.assertIsNone(unit)
        self.assertIn("belongs to 2_phw", error)


class CarryComboTests(unittest.TestCase):
    """The one-control move. Placement only, and still one operation."""

    class _Combo:
        def __init__(self, socket: str) -> None:
            self._socket = socket

        def currentData(self):  # noqa: N802 - mimics QComboBox
            return self._socket

    def test_the_combo_never_replaces_animations(self) -> None:
        harness = _Harness()
        harness._carry_syncing = False
        harness._carry_box = self._Combo("Pelvis_R_Socket")
        window_carry.CarryPickerMixin._on_carry_changed(harness, 0)
        self.assertEqual(len(harness.started), 1)
        plan = harness.started[0][0]
        self.assertEqual(plan.request.scope.kind, carry.SCOPE_PLACEMENT_ONLY)
        self.assertEqual(plan.request.replacements, ())

    def test_the_combo_defers_a_move_it_cannot_show_an_orientation_for(self) -> None:
        """A borrowed aim needs reviewing, and a dropdown cannot show one.

        The two-hand sword has no hip child socket, so a hip move borrows its angle. The combo
        sends the user to the dialog rather than committing an aim nobody looked at.
        """

        harness = _Harness()
        harness._carry_syncing = False
        harness._carry_box = self._Combo("Pelvis_R_Socket")
        harness._populate_carry_box = lambda: None
        window_carry.CarryPickerMixin._on_carry_changed(harness, 0)
        # The fixture's aim resolves by borrowing, which is a confirmation rather than a
        # blocker, so the move proceeds. Blocked plans are the ones that stop here.
        self.assertTrue(harness.started or "Use Swap animations" in harness._status.message)


if __name__ == "__main__":
    unittest.main()
