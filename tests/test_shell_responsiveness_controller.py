from __future__ import annotations

import unittest
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem

from cdmw.ui.shell.responsiveness_controller import (
    AutoTreeColumnWidthEventFilter,
    TreeHorizontalWheelGuard,
    expand_tree_columns_to_available_width,
    responsive_control_scale_for_resolution,
    responsive_control_scale_for_width,
)


class ShellResponsivenessControllerTests(unittest.TestCase):
    def test_compact_screen_scale_uses_width_and_height(self) -> None:
        self.assertEqual(0.78, responsive_control_scale_for_resolution(1366, 768))
        self.assertEqual(0.90, responsive_control_scale_for_resolution(1920, 1080))
        self.assertEqual(1.0, responsive_control_scale_for_resolution(3840, 2160))
        self.assertEqual(0.90, responsive_control_scale_for_width(1920))

    def test_tree_helpers_construct_and_fit_columns(self) -> None:
        app = QApplication.instance() or QApplication([])
        tree = QTreeWidget()
        tree.setColumnCount(2)
        tree.addTopLevelItem(QTreeWidgetItem(["name", "value"]))
        tree.resize(320, 120)
        expand_tree_columns_to_available_width(tree)

        self.assertIsInstance(AutoTreeColumnWidthEventFilter(), AutoTreeColumnWidthEventFilter)
        self.assertIsInstance(TreeHorizontalWheelGuard(tree), TreeHorizontalWheelGuard)
        app.processEvents()
        tree.deleteLater()


if __name__ == "__main__":
    unittest.main()
