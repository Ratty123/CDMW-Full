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


def test_the_clip_filter_rows_fit_the_lane_they_live_in():
    """Qt answers a row it cannot fit by clipping, so no row may ask for more than the lane.

    Three controls shared one row: `Distant versions`, `Only draws for this spot` and the scan
    button need 216, 312 and 338 px at this DPI — 890 with spacing, in a lane that opens at
    620. The checkbox lost its last word and the button read `ind which draws fit (~30s`.
    """

    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from tools.placement_studio.corpus import Baseline
    from tools.placement_studio.window import PlacementStudioWindow

    _app = QApplication.instance() or QApplication([])
    try:
        baseline = Baseline.load()
    except Exception as error:  # noqa: BLE001 - needs a pinned baseline to build at all
        import pytest

        pytest.skip(f"no baseline available: {error}")

    window = PlacementStudioWindow(baseline)
    try:
        checkboxes = (
            window._clip_lod_box.sizeHint().width()
            + window._clip_carry_box.sizeHint().width()
        )
        button = window._carry_match.sizeHint().width()

        # The lane the clip browser opens at; see `_build_animation_tab`.
        assert checkboxes <= 620, f"the checkbox row wants {checkboxes}px"
        assert button <= 620, f"the scan button wants {button}px"
        assert checkboxes + button > 620, (
            "these fit on one row now, so splitting them is no longer what keeps them legible"
        )
    finally:
        window.deleteLater()


def test_the_editing_bar_fits_without_clipping_anything():
    """Every control in the bottom bar must get the width its own text needs.

    Qt answers a row it cannot fit by clipping, and this bar has clipped twice: first from a
    nine-column grid, where one 362px button set the column width for six 42px nudge buttons,
    and then from squeezing everything onto two rows when the controls need about 3,050px
    between them. The guard is on the widths, not the arrangement.
    """

    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QFrame

    from tools.placement_studio.corpus import Baseline
    from tools.placement_studio.window import PlacementStudioWindow

    _app = QApplication.instance() or QApplication([])
    try:
        baseline = Baseline.load()
    except Exception as error:  # noqa: BLE001 - needs a pinned baseline to build at all
        import pytest

        pytest.skip(f"no baseline available: {error}")

    window = PlacementStudioWindow(baseline)
    try:
        panel = window._edit_target.parent()
        while panel is not None and not isinstance(panel, QFrame):
            panel = panel.parent()
        assert panel is not None, "the editing bar is not in a frame any more"

        # A 1600px monitor is the floor the window as a whole is held to; see the width test.
        assert panel.sizeHint().width() <= 1500, (
            f"the editing bar asks for {panel.sizeHint().width()}px and will clip"
        )

        # Each angle box has to hold its own prefix plus the widest value it accepts.
        for box in window._euler:
            needed = box.fontMetrics().horizontalAdvance(box.prefix() + "-180.0")
            assert box.width() >= needed, f"{box.prefix().strip()} clips its own value"
    finally:
        window.deleteLater()
