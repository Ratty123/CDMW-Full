"""app_ui_act's menu action: context menus and drop-down menus read and picked without being shown."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QApplication, QMenu, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from cdmw.mcp.errors import ToolError
from cdmw.mcp.names import DESTRUCTIVE, EDIT, OUTPUT, READ
from cdmw.mcp.ui_tree import act, effect_of_action


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class _Page(QWidget):
    """A tree whose rows have a menu built on right-click, and a button with a drop-down menu."""

    def __init__(self):
        super().__init__()
        self.seen: list[tuple] = []
        layout = QVBoxLayout(self)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["File"])
        for name in ("sword.pac", "castle.prefab", "voice.wem"):
            QTreeWidgetItem(self.tree, [name])
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._row_menu)
        self.charts = QPushButton("Action Charts")
        menu = QMenu(self.charts)
        menu.addAction("Find Action Chart by Character...", lambda: self.seen.append(("find",)))
        later = menu.addAction("Open Action Chart Mod...")
        later.setEnabled(False)
        later.setToolTip("Load the archives first.")
        self.charts.setMenu(menu)
        layout.addWidget(self.tree)
        layout.addWidget(self.charts)

    def _row_menu(self, position):
        item = self.tree.itemAt(position)
        if item is None:
            return
        name = item.text(0)
        menu = QMenu(self.tree)
        menu.addAction("Preview")
        if name.endswith(".prefab"):
            menu.addAction("Open Prefab Inspector...").triggered.connect(lambda: self.seen.append(("prefab", name)))
        export = menu.addMenu("&Export")
        export.addAction("Export File...").triggered.connect(lambda: self.seen.append(("export", name)))
        copy = QAction("Copy Filename", menu)
        menu.addAction(copy)
        chosen = menu.exec(self.tree.viewport().mapToGlobal(position))
        if chosen is copy:  # read from the returned action, as much of the app does
            self.seen.append(("copied", name))


@pytest.fixture
def page(app):
    widget = _Page()
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_a_rows_context_menu_is_listed_without_running_anything(page):
    listed = act(page.tree, "menu", row="castle.prefab")
    assert [entry["text"] for entry in listed["entries"]] == ["Preview", "Open Prefab Inspector", "Export",
                                                             "Copy Filename"]
    assert listed["entries"][2]["entries"] == [{"text": "Export File"}]
    assert page.seen == []
    assert page.tree.currentItem().text(0) == "castle.prefab"  # a right-click selects its row
    other = act(page.tree, "menu", row="voice.wem")
    assert "Open Prefab Inspector" not in [entry["text"] for entry in other["entries"]]


def test_an_entry_runs_through_triggered_and_through_the_returned_action(page):
    assert act(page.tree, "menu", row=1, menu="Open Prefab Inspector...")["picked"] == "Open Prefab Inspector"
    assert act(page.tree, "menu", row="sword.pac", menu="Copy Filename")["picked"] == "Copy Filename"
    assert page.seen == [("prefab", "castle.prefab"), ("copied", "sword.pac")]


def test_a_submenu_path_is_followed(page):
    picked = act(page.tree, "menu", row="voice.wem", menu="Export > Export File")
    assert picked["picked"] == "Export > Export File"
    assert page.seen == [("export", "voice.wem")]


def test_a_buttons_menu_is_read_and_a_disabled_entry_is_refused_with_its_tooltip(page):
    listed = act(page.charts, "menu")
    assert listed["entries"] == [{"text": "Find Action Chart by Character"},
                                 {"text": "Open Action Chart Mod", "enabled": False,
                                  "tip": "Load the archives first."}]
    with pytest.raises(ToolError, match="Load the archives first"):
        act(page.charts, "menu", menu="Open Action Chart Mod...")
    act(page.charts, "menu", menu="find action chart by character")
    assert page.seen == [("find",)]


def test_an_entry_that_does_not_exist_names_the_ones_that_do(page):
    with pytest.raises(ToolError, match="has no entry 'Delete'. It has: Preview, Export, Copy Filename"):
        act(page.tree, "menu", row="sword.pac", menu="Delete")
    with pytest.raises(ToolError, match="opens a submenu"):
        act(page.tree, "menu", row="sword.pac", menu="Export")
    assert page.seen == []


def test_no_menu_is_left_open(page):
    act(page.tree, "menu", row=0)
    act(page.tree, "menu", row=0, menu="Export > Export File")
    assert QApplication.activePopupWidget() is None


@pytest.mark.parametrize(("entry", "effect"), [
    (None, READ),
    ("Preview", EDIT),
    ("Export > Export File...", OUTPUT),
    ("Extract Selected", OUTPUT),
    ("Delete Local Copy", DESTRUCTIVE),
    ("Remove selected", DESTRUCTIVE),
    ("Open Prefab Inspector...", EDIT),
])
def test_the_class_follows_the_entry(page, entry, effect):
    assert effect_of_action(page.tree, "menu", entry) == effect


def test_a_user_only_command_in_a_menu_is_refused(page, monkeypatch):
    from cdmw.mcp import ui_menus

    monkeypatch.setattr(ui_menus, "entry_user_only", lambda path: path[-1] == "Preview")
    with pytest.raises(ToolError, match="Only you can use this control"):
        act(page.tree, "menu", row=0, menu="Preview")
    assert page.seen == []


def test_browse_archives_right_click_menu_of_a_prefab_lists_the_prefab_inspector(app, tmp_path,
                                                                                 preserve_app_appearance,
                                                                                 monkeypatch):
    """The real Browse Archives tree, built headlessly: its row menu comes back through the menu action."""

    from unittest.mock import patch

    from cdmw.app.events import AppEventBus
    from cdmw.models import ArchiveEntry
    from cdmw.services.service_container import ServiceContainer
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.main_window import MainWindow
    from cdmw.ui.shell.app_context import AppContext

    settings = create_settings(settings_file_path=tmp_path / "menus.cfg")
    context = AppContext(settings=settings, services=ServiceContainer.create_default(settings=settings),
                         event_bus=AppEventBus())
    with patch.dict(os.environ, {"CDMW_GUI_STARTUP_SMOKE": "1"}):
        window = MainWindow(app_context=context)
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.show()
        app.processEvents()
    try:
        archive = window.archive
        package = tmp_path / "game" / "0012"
        package.mkdir(parents=True)
        (package / "0.paz").write_bytes(b"prefab")
        entry = ArchiveEntry("object/castle_gate.prefab", package / "0.pamt", package / "0.paz", 0, 6, 6, 0, 0)
        monkeypatch.setattr(archive, "archive_remote_bridge", None)
        archive.archive_entries = archive.archive_filtered_entries = [entry]
        archive.archive_tree.use_legacy_model()
        archive.archive_tree.set_archive_state([entry], mode="flat")
        app.processEvents()
        listed = act(archive.archive_tree, "menu", row="castle_gate.prefab", window=window)
        texts = [row["text"] for row in listed["entries"]]
        assert "Open Prefab Inspector" in texts, texts
        assert QApplication.activePopupWidget() is None
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()
