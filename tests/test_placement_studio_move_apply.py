"""Pressing "Move it" has to actually move it.

This exists because it once did not. `QDialog.Accepted` is a class constant, and reading it
off the dialog instance raised `AttributeError` the moment the dialog closed — so the routing
and the animation swap were both skipped. Under `pythonw` there is no console, so the failure
was completely silent: the button appeared to do nothing.

The dialog was covered and the swap was covered; nothing exercised the handler that joins
them. That is the gap this closes.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from tools.placement_studio import window_carry  # noqa: E402
from tools.placement_studio.editing import EditSession  # noqa: E402
from tools.placement_studio.move_weapon import MovePlan  # noqa: E402

_APP = QApplication.instance() or QApplication([])


class _Clip:
    def __init__(self, name: str) -> None:
        self.name = name
        self.path = f"character/motion/1_pc/1_phm/{name}.paa"


class _Part:
    def __init__(self) -> None:
        self.in_socket = "Pelvis_L_Socket"
        self.category = "weapon"


class _Binding:
    def __init__(self) -> None:
        self.part_name = "CD_MainWeapon_Sword_R"
        self.part = _Part()


class _Placed:
    def __init__(self, name: str) -> None:
        self.name = name


class _Session:
    """Only what the handler reads while assembling the dialog."""

    model = "1_phm"
    weapon = None

    def bindings(self):
        return [_Binding()]

    def placed_sockets(self):
        return [_Placed("Pelvis_L_Socket"), _Placed("Spine2_B_MainWeapon_Socket")]


class _Status:
    def __init__(self) -> None:
        self.message = ""

    def showMessage(self, text: str) -> None:  # noqa: N802 - mimics QStatusBar
        self.message = text

    def currentMessage(self) -> str:  # noqa: N802 - mimics QStatusBar
        return self.message


class _Harness(window_carry.CarryPickerMixin):
    """The handler with only what it touches, so the join is testable without a game."""

    def __init__(self, plan: MovePlan) -> None:
        self._plan = plan
        self._session = _Session()
        self._edits = EditSession({})
        self._selected_part = "CD_MainWeapon_Sword_R"
        self._swap_thread = None
        self._swap_worker = None
        self._status = _Status()
        self.routed_to = ""
        self.swapped = ()

    # what the handler calls out to
    def statusBar(self):  # noqa: N802 - mimics QMainWindow
        return self._status

    def _current_binding(self):
        return _Binding()

    def _apply_carry_move(self, socket: str) -> None:
        self.routed_to = socket

    def _start_clip_swap(self, pairs) -> str:
        self.swapped = tuple(pairs)
        return f"{len(self.swapped)} clip file(s) replaced"

    def _sync_part_box(self, _name: str) -> None:
        pass


def _run(plan: MovePlan, *, accepted: bool = True) -> _Harness:
    harness = _Harness(plan)

    class _Dialog:
        Accepted = QDialog.Accepted

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def exec(self):
            return QDialog.Accepted if accepted else QDialog.Rejected

        def plan(self):
            return plan

    original = window_carry.CarryPickerMixin._on_swap_clicked
    import tools.placement_studio.move_weapon as move_weapon

    saved = move_weapon.MoveWeaponDialog
    move_weapon.MoveWeaponDialog = _Dialog
    try:
        original(harness)
    finally:
        move_weapon.MoveWeaponDialog = saved
    return harness


_PAIRS = ((_Clip("sword_out"), _Clip("longsword_out")),)


class MoveAppliesTests(unittest.TestCase):
    def test_a_move_with_animations_does_both(self) -> None:
        harness = _run(MovePlan("CD_MainWeapon_Sword_R", "Spine2_B_MainWeapon_Socket", _PAIRS))

        self.assertEqual(harness.routed_to, "Spine2_B_MainWeapon_Socket")
        self.assertEqual(len(harness.swapped), 1)

    def test_cancelling_changes_nothing(self) -> None:
        harness = _run(
            MovePlan("CD_MainWeapon_Sword_R", "Spine2_B_MainWeapon_Socket", _PAIRS),
            accepted=False,
        )

        self.assertEqual(harness.routed_to, "")
        self.assertEqual(harness.swapped, ())

    def test_a_move_without_animations_still_routes_and_says_so(self) -> None:
        harness = _run(MovePlan("CD_MainWeapon_Sword_R", "Spine2_B_MainWeapon_Socket", ()))

        self.assertEqual(harness.routed_to, "Spine2_B_MainWeapon_Socket")
        self.assertEqual(harness.swapped, ())
        self.assertIn("Animations left alone", harness._status.message)

    def test_animations_alone_swap_without_routing(self) -> None:
        """Restyling in place is a legitimate edit; it must not require a move."""

        harness = _run(MovePlan("CD_MainWeapon_Sword_R", "", _PAIRS))

        self.assertEqual(harness.routed_to, "")
        self.assertEqual(len(harness.swapped), 1)


if __name__ == "__main__":
    unittest.main()
