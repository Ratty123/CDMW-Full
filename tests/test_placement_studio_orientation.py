"""Borrowing a carry angle the item does not define for itself.

A one-hand sword defines `Pelvis_L_ChildSocket` and `Pelvis_R_ChildSocket` and nothing else,
because the game never slings it on the back. Routing it there kept the hip's angle — and the
hip child socket is an identity rotation while the back one is a half turn about Y, which is
exactly why the blade came out upside down.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from tools.placement_studio.corpus import Baseline  # noqa: E402
from tools.placement_studio.session import PlacementSession  # noqa: E402

_APP = QApplication.instance() or QApplication([])


def _session():
    try:
        return PlacementSession.from_baseline(Baseline.load(), "1_phm")
    except Exception as error:  # noqa: BLE001 - needs the pinned baseline
        raise unittest.SkipTest(f"no baseline available: {error}")


class BorrowedOrientationTests(unittest.TestCase):
    def test_the_back_child_socket_is_a_half_turn_from_the_hip_one(self) -> None:
        """The measurement the whole fix rests on. If this changes, the fix is wrong."""

        session = _session()
        hip = session.borrowed_child_socket("Pelvis_L_ChildSocket")
        back = session.borrowed_child_socket("Spine2_B_SubWeapon_ChildSocket")
        self.assertIsNotNone(hip)
        self.assertIsNotNone(back)

        # Hip: identity. Back: 180 degrees about Y, which reads as w=0, y=+-1.
        self.assertAlmostEqual(abs(hip.rotation.w), 1.0, places=3)
        self.assertAlmostEqual(abs(back.rotation.y), 1.0, places=3)
        self.assertAlmostEqual(abs(back.rotation.w), 0.0, places=3)

    def test_every_weapon_shares_one_local_axis_convention(self) -> None:
        """Why borrowing between items is sound at all.

        A rotation authored for one sword only means the same thing on another if they agree
        on their own local axes. They do: every weapon puts `Basic_ChildSocket` at the same
        place. Were that not so, the borrowed angle would be meaningless.
        """

        session = _session()
        seen = set()
        for weapon in session.weapons():
            grip = weapon.sockets.get("Basic_ChildSocket")
            if grip is None:
                continue
            seen.add(
                (
                    round(grip.rotation.x, 3), round(grip.rotation.y, 3),
                    round(grip.rotation.z, 3), round(grip.rotation.w, 3),
                )
            )
        self.assertEqual(len(seen), 1, f"weapons disagree on their local axes: {seen}")

    def test_a_socket_no_item_defines_cannot_be_borrowed(self) -> None:
        self.assertIsNone(_session().borrowed_child_socket("Not_A_ChildSocket"))

    def test_the_one_hand_sword_really_has_no_back_child_socket(self) -> None:
        """The premise. If the game started shipping one, the borrow is no longer needed."""

        session = _session()
        sword = next(
            (w for w in session.weapons() if w.weapon_id == "cd_phm_01_sword_0001_r"), None
        )
        if sword is None:
            self.skipTest("the pinned baseline does not carry this sword")
        self.assertIn("Pelvis_L_ChildSocket", sword.sockets)
        self.assertNotIn("Spine2_B_SubWeapon_ChildSocket", sword.sockets)


if __name__ == "__main__":
    unittest.main()
