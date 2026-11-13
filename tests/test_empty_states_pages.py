"""P11 step 6 on the pages outside the main thread's: each empty panel says what to do next,
its button runs that step, and the empty state takes the panel's place."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.ui.commands.registry import Command, command_registry


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def opened(app):
    """Record shell.open.* runs instead of switching tools."""
    ran = []
    registry = command_registry()
    for key in ("archive_browser", "settings_placeholder"):
        registry.register(Command(f"shell.open.{key}", key, "shell", lambda key=key: ran.append(key)), replace=True)
    return ran


def _entry(root: Path):
    from cdmw.models import ArchiveEntry

    return ArchiveEntry("gamedata/a.xml", root / "0009/0.pamt", root / "0009/0.paz", 0, 1, 1, 0, 0)


# ----- Search File Text --------------------------------------------------------------
def _text_search(root: Path):
    from cdmw.ui.text_search.tab import TextSearchTab

    return TextSearchTab(settings=QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat),
                         base_dir=root, theme_key="graphite")


def test_search_file_text_says_to_scan_then_to_search_then_what_to_change(app, opened, tmp_path):
    from cdmw.ui.text_search import controller as text

    tab = _text_search(tmp_path)
    try:
        tab._update_controls()
        state = tab.results_empty_state
        assert tab.results_stack.currentWidget() is state
        assert state.sentence_label.text() == text.SEARCH_NOT_SCANNED_TEXT
        state.button.click()
        assert opened == ["archive_browser"]

        tab.set_archive_entries([_entry(tmp_path)], str(tmp_path))
        assert state.sentence_label.text() == text.SEARCH_READY_TEXT and state.button.text() == "Search"

        tab._searched_query = "missing words"
        tab._update_controls()
        assert state.sentence_label.text() == text.SEARCH_NOTHING_MATCHED_TEXT
        state.button.click()
        assert opened == ["archive_browser"]  # it changes the search, it does not open a tool
    finally:
        tab.deleteLater()


def _pump(app, predicate, timeout=5.0):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not predicate():
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert predicate()


# ----- Drafts & Mods ------------------------------------------------------------------
def test_drafts_and_mods_says_how_to_save_work_and_how_to_clear_a_filter(app, opened, tmp_path):
    from cdmw.services.item_package_saved_work import register_item_package
    from cdmw.ui.mesh_editor import saved_work_page as page_module
    from cdmw.ui.mesh_editor.saved_work_page import SavedWorkPage

    page = SavedWorkPage(draft_root=tmp_path / "empty-drafts")
    try:
        page.show()
        _pump(app, lambda: page.table_switch.is_empty())
        assert page.empty_state.sentence_label.text() == page_module.SAVED_WORK_EMPTY_TEXT
        assert not page.details_panel.isVisible() and not page.table.isVisible()
        page.empty_state.button.click()
        assert opened == ["archive_browser"]
    finally:
        page.close()
        page.deleteLater()

    drafts, package = tmp_path / "drafts", tmp_path / "Blade.cdmw"
    package.write_bytes(b"package")
    register_item_package(drafts, package_path=package, identity="i" * 32, title="Blade", draft_bytes=b"{}",
                          template_name="Sword_A")
    page = SavedWorkPage(draft_root=drafts)
    try:
        page.show()
        _pump(app, lambda: page.table.rowCount() == 1)
        assert not page.table_switch.is_empty() and page.details_panel.isVisible()
        page.filter_edit.setText("no such name")
        _pump(app, lambda: page.table_switch.is_empty())
        assert page.empty_state.sentence_label.text() == page_module.SAVED_WORK_NO_MATCH_TEXT
        assert page.empty_state.button.text() == page_module.SAVED_WORK_SHOW_ALL_TEXT
        page.empty_state.button.click()
        _pump(app, lambda: page.table.rowCount() == 1 and not page.table_switch.is_empty())
        assert page.filter_edit.text() == ""
    finally:
        page.close()
        page.deleteLater()


# ----- Edit Translations ----------------------------------------------------------------
def test_edit_translations_asks_for_the_game_folder_then_for_a_language(app, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtWidgets import QLineEdit

    import tools.translation_studio.tab as tab_module

    monkeypatch.setattr(tab_module, "available_languages", lambda _root=None, *, on_progress=None: ("eng", "kor"))
    focused = []
    root_edit = QLineEdit("")
    window = SimpleNamespace(archive=SimpleNamespace(archive_package_root_edit=root_edit),
                             focus_archive_locations=lambda: focused.append(True))
    tab = tab_module.TranslationStudioTab(window=window)
    try:
        state = tab.empty_state
        assert tab.editor_switch.is_empty() and not tab.table.isVisibleTo(tab)
        assert state.sentence_label.text() == tab_module.TRANSLATIONS_NO_GAME_TEXT
        state.button.click()
        assert focused == [True]

        root_edit.setText(str(tmp_path))
        _pump(app, lambda: tab.language_box.count() == 2 and not tab.iter_shutdown_workers())
        assert state.sentence_label.text() == tab_module.TRANSLATIONS_LOAD_TEXT
        assert state.button.text() == "Load" and state.button.isEnabled()

        tab._catalogue = SimpleNamespace()  # a table was loaded
        tab._sync_empty_state()
        assert not tab.editor_switch.is_empty() and tab.table.isVisibleTo(tab)
    finally:
        tab._catalogue = None
        tab.request_shutdown()
        tab.deleteLater()


# ----- Textures -------------------------------------------------------------------------
def test_textures_offers_to_add_textures_in_the_asset_lists_place(app, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFileDialog

    from cdmw.services.settings_service import create_settings
    from cdmw.ui.main_window import MainWindow
    from cdmw.ui.shell.app_context import AppContext
    from cdmw.ui.texture_workflow import workspace_ui

    asked = []
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args, **kwargs: (asked.append(True), ([], ""))[1])
    monkeypatch.setenv("CDMW_GUI_STARTUP_SMOKE", "1")
    settings = create_settings(settings_file_path=tmp_path / "textures.cfg")
    window = MainWindow(app_context=AppContext.from_settings(settings))
    try:
        window.setAttribute(Qt.WA_DontShowOnScreen)
        window.resize(1450, 1000)
        window.show()
        window._activate_tool_key("textures")
        window.texture_editor_tab.ensure_widget()
        app.processEvents()
        textures = window.textures
        state = textures.assets_empty_state
        assert textures.assets_switch.is_empty()
        assert not textures.asset_list.isVisible() and not textures.remove_texture_button.isVisible()
        assert state.sentence_label.text() == workspace_ui.TEXTURES_EMPTY_TEXT and state.button.text() == "Add Textures"
        state.button.click()
        assert asked, "the button opens the same file picker as the toolbar's Add Textures"

        source = tmp_path / "owned.png"
        source.write_bytes(b"not read")
        textures.job.add_source(source)
        textures._refresh_texture_assets()
        assert not textures.assets_switch.is_empty() and textures.asset_list.topLevelItemCount() == 1
    finally:
        window._close_force_accept = True
        window.close()
        window.deleteLater()
        app.processEvents()
