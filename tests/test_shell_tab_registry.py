from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

from cdmw.ui.shell.navigation_controller import NavigationControllerMixin
from cdmw.ui.shell.tab_registry import DetachedToolWindow


class _Owner(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._shutting_down = False
        self.attached: list[tuple[str, bool]] = []

    def _attach_detached_tool(self, key: str, *, select_after: bool) -> None:
        self.attached.append((key, select_after))


class _LabelHolder(NavigationControllerMixin):
    def __init__(self) -> None:
        self._tool_tab_labels_by_key: dict[str, str] = {}
        self._tool_titles_by_key: dict[str, str] = {}


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

    def test_detaching_puts_back_the_caption_the_tab_is_showing(self) -> None:
        """The label cache was filled once, in English, and replayed on every detach.

        Re-inserting a tab raises no event the localizer acts on, so detaching a tool
        under a translated UI put the startup English caption back and left it there
        until the next language change.
        """

        app = QApplication.instance() or QApplication([])
        holder = _LabelHolder()
        tabs = QTabWidget()
        page = QWidget()
        tabs.addTab(page, "Archive Browser")
        holder._tool_titles_by_key["archive_browser"] = "Archive Browser"
        holder._tool_tab_labels_by_key["archive_browser"] = "Archive Browser"

        tabs.setTabText(0, "Archiv-Browser")
        label = holder._remembered_tab_label("archive_browser", tabs, 0)

        self.assertEqual("Archiv-Browser", label)
        self.assertEqual("Archiv-Browser", holder._tool_tab_labels_by_key["archive_browser"])

        # A tab that is already gone falls back to the cache rather than blanking.
        self.assertEqual(
            "Archiv-Browser",
            holder._remembered_tab_label("archive_browser", tabs, -1),
        )
        tabs.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
