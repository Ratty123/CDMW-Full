"""Gates for proportional table columns.

`QHeaderView` has no per-column stretch weight, so one `Stretch` column beside several
`ResizeToContents` ones takes every spare pixel. These tests pin the arithmetic that
replaces it, including the case that first produced a scrollbar which never went away.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class WidthArithmeticTests(unittest.TestCase):
    """`_widths_for` is pure arithmetic and is where the behaviour lives."""

    @classmethod
    def setUpClass(cls) -> None:
        pytest.importorskip("PySide6")
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _helper(self, weights, minimums, columns=None):
        from PySide6.QtWidgets import QTableWidget

        from tools.placement_studio.table_columns import proportional_columns

        table = QTableWidget(0, columns if columns is not None else len(weights))
        self._table = table  # Qt owns the children; keep the table alive.
        return proportional_columns(table, weights, minimums)

    def test_widths_follow_the_weights(self) -> None:
        helper = self._helper((50, 30, 20), (0, 0, 0))
        self.assertEqual(helper._widths_for(1000), [500, 300, 200])

    def test_widths_always_fill_the_viewport_exactly(self) -> None:
        """Short of the width leaves a dead strip; over it produces a scrollbar."""

        helper = self._helper((42, 18, 10, 15, 15), (116, 80, 46, 62, 66))
        for available in range(420, 2000, 7):
            self.assertEqual(sum(helper._widths_for(available)), available, available)

    def test_a_minimum_is_paid_for_out_of_the_columns_with_slack(self) -> None:
        """The bug that produced a permanent scrollbar: raising to a minimum for free.

        Column 1's proportional share is 20px and its minimum is 100, so it gains 80.
        Those 80 have to come off column 0, or the total overshoots the viewport, Qt adds
        a horizontal scrollbar, the viewport shrinks, and the next pass overshoots again.
        """

        helper = self._helper((90, 10), (0, 100))
        widths = helper._widths_for(200)

        self.assertEqual(widths[1], 100)
        self.assertEqual(sum(widths), 200)

    def test_no_column_is_pushed_below_its_minimum_to_pay_for_another(self) -> None:
        helper = self._helper((80, 10, 10), (0, 90, 90))
        widths = helper._widths_for(300)

        self.assertGreaterEqual(widths[1], 90)
        self.assertGreaterEqual(widths[2], 90)
        self.assertEqual(sum(widths), 300)

    def test_minimums_that_cannot_fit_are_honoured_and_overflow(self) -> None:
        """Too narrow to be readable is a scrollbar, not a silently truncated bone name."""

        helper = self._helper((50, 50), (200, 200))
        widths = helper._widths_for(120)

        self.assertEqual(widths, [200, 200])

    def test_a_zero_width_viewport_is_left_alone(self) -> None:
        """Called before the panel is shown; writing widths then would stick at zero."""

        helper = self._helper((50, 50), (10, 10))
        helper.apply()  # viewport width is 0 offscreen before show
        self.assertEqual(helper._table.columnCount(), 2)

    def test_a_weight_count_mismatch_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self._helper((50, 50), (10, 10), columns=3)
        with self.assertRaises(ValueError):
            self._helper((50, 50, 50), (10, 10), columns=2)


class PanelColumnTests(unittest.TestCase):
    """Both rig panels declare shares for every column they have."""

    @classmethod
    def setUpClass(cls) -> None:
        pytest.importorskip("PySide6")
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_the_driven_bones_tables_size_every_column(self) -> None:
        from tools.placement_studio.window_constraints import SecondaryMotionMixin

        class Panel(SecondaryMotionMixin):
            pass

        panel = Panel()
        panel._root_widget = panel._build_secondary_motion_tab()

        for table in (panel._chain_table, panel._chain_detail):
            header = table.horizontalHeader()
            self.assertFalse(header.stretchLastSection())
            for column in range(table.columnCount()):
                self.assertGreater(table.columnWidth(column), 0, column)

    def test_the_rig_behaviour_table_sizes_every_column(self) -> None:
        from tools.placement_studio.window_rig_behaviour import RigBehaviourMixin

        class Panel(RigBehaviourMixin):
            pass

        panel = Panel()
        panel._root_widget = panel._build_rig_behaviour_tab()

        table = panel._behaviour_table
        self.assertFalse(table.horizontalHeader().stretchLastSection())
        for column in range(table.columnCount()):
            self.assertGreater(table.columnWidth(column), 0, column)


if __name__ == "__main__":
    unittest.main()
