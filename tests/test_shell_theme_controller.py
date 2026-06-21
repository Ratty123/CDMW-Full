from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from cdmw.ui.shell.theme_controller import ThemeChangeBusyOverlay


class ShellThemeControllerTests(unittest.TestCase):
    def test_theme_change_busy_overlay_updates_state_and_timers(self) -> None:
        app = QApplication.instance() or QApplication([])
        parent = QWidget()
        parent.resize(320, 180)
        parent.show()
        overlay = ThemeChangeBusyOverlay(parent)

        overlay.show_appearance_change("graphite", title="Applying Graphite", detail="Working")
        app.processEvents()

        self.assertEqual("ThemeChangeBusyOverlay", overlay.objectName())
        self.assertTrue(overlay.isVisible())
        self.assertEqual(parent.rect(), overlay.geometry())

        overlay.finish(0)
        app.processEvents()
        overlay.deleteLater()
        parent.deleteLater()


if __name__ == "__main__":
    unittest.main()
