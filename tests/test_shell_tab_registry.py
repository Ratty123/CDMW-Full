from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from cdmw.ui.shell.tab_registry import DetachedToolWindow


class _Owner(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._shutting_down = False
        self.attached: list[tuple[str, bool]] = []

    def _attach_detached_tool(self, key: str, *, select_after: bool) -> None:
        self.attached.append((key, select_after))


class ShellTabRegistryTests(unittest.TestCase):
    def test_detached_tool_window_reattaches_on_user_close(self) -> None:
        app = QApplication.instance() or QApplication([])
        owner = _Owner()
        window = DetachedToolWindow(owner, "texture_editor", "Texture Editor")

        window.close()
        app.processEvents()

        self.assertEqual([("texture_editor", False)], owner.attached)
        window.deleteLater()
        owner.deleteLater()


if __name__ == "__main__":
    unittest.main()
