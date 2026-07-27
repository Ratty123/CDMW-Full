"""The window has to fit on a monitor, and its dropdowns have to be readable.

Both of these went wrong silently. Qt sizes a combo to its longest entry and will not shrink
below it, so a few long rows quietly pushed the minimum window width past 4,000 px; and once
the combos were narrowed, the popup inherited that width and elided the options down the
middle, which is where a label is least readable.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

from tools.placement_studio.window import fit_popup  # noqa: E402

_APP = QApplication.instance() or QApplication([])


class PopupWidthTests(unittest.TestCase):
    def _combo(self, *items: str) -> QComboBox:
        combo = QComboBox()
        for item in items:
            combo.addItem(item)
        return combo

    def test_the_popup_is_wide_enough_for_its_longest_option(self) -> None:
        combo = self._combo("Move", "New attach point", "Send to socket")
        combo.setMinimumContentsLength(4)  # deliberately far too narrow

        fit_popup(combo)

        widest = max(
            combo.fontMetrics().horizontalAdvance(combo.itemText(i))
            for i in range(combo.count())
        )
        self.assertGreaterEqual(combo.view().minimumWidth(), widest)

    def test_narrowing_the_control_does_not_narrow_the_list(self) -> None:
        """The closed control may elide — the list it opens may not."""

        combo = self._combo("CD_MainWeapon_Sword_R   ->   Pelvis_L_Socket / RHand_Socket")
        combo.setMinimumContentsLength(10)

        fit_popup(combo)

        self.assertGreater(combo.view().minimumWidth(), combo.minimumSizeHint().width())

    def test_an_empty_dropdown_is_left_alone(self) -> None:
        combo = QComboBox()

        fit_popup(combo)

        self.assertEqual(combo.view().minimumWidth(), 0)


class WindowWidthTests(unittest.TestCase):
    def test_the_window_fits_a_normal_monitor(self) -> None:
        """A hard ceiling, because nothing in the header announces when it breaches it."""

        from tools.placement_studio.corpus import Baseline
        from tools.placement_studio.window import PlacementStudioWindow

        try:
            baseline = Baseline.load()
        except Exception as error:  # noqa: BLE001 - needs a pinned baseline to build at all
            self.skipTest(f"no baseline available: {error}")

        window = PlacementStudioWindow(baseline)
        try:
            self.assertLessEqual(
                window.minimumSizeHint().width(),
                1600,
                "the header is forcing the window wider than a 1600 px monitor",
            )
        finally:
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
