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
    def test_screen_change_consumes_dirty_metrics_once(self) -> None:
        app = QApplication.instance() or QApplication([])
        window = _ResponsiveWindow()
        window._responsive_metrics_dirty = True
        calls = []

        def apply_defaults(**kwargs):
            calls.append(kwargs)
            if kwargs["apply_expensive_metrics"]:
                window._responsive_metrics_dirty = False

        window._apply_responsive_window_defaults = apply_defaults
        window._apply_responsive_resize_adjustments()
        window._apply_responsive_resize_adjustments()
        self.assertTrue(calls[0]["apply_expensive_metrics"])
        self.assertTrue(calls[0]["adjust_window_geometry"])
        self.assertFalse(calls[1]["apply_expensive_metrics"])
        self.assertFalse(calls[1]["adjust_window_geometry"])
        self.assertFalse(calls[0]["restore_saved_splitters"])
        window.deleteLater()
        app.processEvents()

    def test_same_monitor_work_area_change_refreshes_metrics_and_fits_window(self) -> None:
        from unittest.mock import Mock
        from PySide6.QtCore import QObject, QRect, QTimer, Signal

        class Screen(QObject):
            availableGeometryChanged = Signal(object)
            logicalDotsPerInchChanged = Signal(float)
            geometryChanged = Signal(object)
            area = QRect(0, 0, 1920, 1040)
            ratio = 1.0

            def availableGeometry(self):
                return self.area

            def devicePixelRatio(self):
                return self.ratio

            def logicalDotsPerInch(self):
                return 96.0

        app = QApplication.instance() or QApplication([])
        screen = Screen()
        window = _ResponsiveWindow()
        window.screen = lambda: screen
        window._shutting_down = False
        window._responsive_resize_timer = QTimer(window)
        window._apply_responsive_theme_metrics = Mock()
        window._apply_responsive_control_minimums = Mock()
        window.resize(1800, 950)
        window._responsive_last_screen_signature = window._screen_signature_for_responsive_layout()
        window._watch_responsive_screen_metrics()
        screen.area = QRect(0, 0, 1280, 672)
        screen.ratio = 1.5
        screen.availableGeometryChanged.emit(screen.area)
        self.assertTrue(window._responsive_metrics_dirty)
        window._apply_responsive_resize_adjustments()
        self.assertLessEqual(window.width(), 1280)
        self.assertLessEqual(window.height(), 672)
        window._apply_responsive_theme_metrics.assert_called_once()
        window._apply_responsive_control_minimums.assert_called_once()
        self.assertFalse(window._responsive_metrics_dirty)
        window._apply_responsive_resize_adjustments()
        window._apply_responsive_theme_metrics.assert_called_once()
        window.deleteLater()
        app.processEvents()

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
