from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cdmw.ui.shell.help_widgets import make_help_button


class ShellHelpWidgetsTests(unittest.TestCase):
    def test_make_help_button_formats_wrapped_tooltip(self) -> None:
        app = QApplication.instance() or QApplication([])

        button = make_help_button("Use <safe>\nhelp text")

        self.assertIsNotNone(app)
        self.assertEqual("?", button.text())
        self.assertIn("width: 360px", button.toolTip())
        self.assertIn("Use &lt;safe&gt;<br>help text", button.toolTip())
        self.assertEqual(Qt.WhatsThisCursor, button.cursor().shape())
        self.assertTrue(button.autoRaise())
        self.assertEqual(22, button.width())
        self.assertEqual(22, button.height())


if __name__ == "__main__":
    unittest.main()
