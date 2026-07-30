from __future__ import annotations

import unittest
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from cdmw.ui.shell.responsiveness_controller import (
    AutoTreeColumnWidthEventFilter,
    ResponsivenessControllerMixin,
    TreeHorizontalWheelGuard,
    expand_tree_columns_to_available_width,
    responsive_control_scale_for_resolution,
    responsive_control_scale_for_width,
)


class _ResponsiveWindow(ResponsivenessControllerMixin, QMainWindow):
    pass


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

    def test_control_minimums_survive_a_destroyed_cached_control(self) -> None:
        """A panel that rebuilds its controls used to crash the next appearance step.

        The cache is refreshed when a tool tab is built, never when one of its
        controls is destroyed, so a stale wrapper reached `property()` and raised
        `libshiboken: Internal C++ object (QProgressBar) already deleted` out of a
        queued theme step -- with no caller to catch it.
        """

        app = QApplication.instance() or QApplication([])
        window = _ResponsiveWindow()
        panel = QWidget(window)
        window.setCentralWidget(panel)
        progress = QProgressBar(panel)
        keeper = QPushButton("Keep", panel)
        window._cache_responsive_control_widgets()
        self.assertIn(progress, window._responsive_control_widgets)

        progress.setParent(None)
        shiboken6.delete(progress)
        app.processEvents()

        window._apply_responsive_control_minimums()

        self.assertEqual((keeper,), window._responsive_control_widgets)
        window.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
