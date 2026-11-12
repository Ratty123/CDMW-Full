"""Commands and shortcuts through the paths the app uses (plan 8.7, group E).

Each test builds what the app builds: the shell's own window, its embedded
Texture Editor, the Settings page as the shell makes it. No stand-ins.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CDMW_GUI_STARTUP_SMOKE", "1")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

_APP = QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def shell(tmp_path_factory):
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.main_window import MainWindow
    from cdmw.ui.shell.app_context import AppContext

    folder = tmp_path_factory.mktemp("shell")
    previous = os.environ.get("CDMW_PROFILE_DIR")
    os.environ["CDMW_PROFILE_DIR"] = str(folder / "profile")
    settings = create_settings(settings_file_path=folder / "settings.ini")
    window = MainWindow(app_context=AppContext.from_settings(settings))
    try:
        yield window
    finally:
        window._finalize_close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if previous is None:
            os.environ.pop("CDMW_PROFILE_DIR", None)
        else:
            os.environ["CDMW_PROFILE_DIR"] = previous


def _page_ids(page) -> set[str]:
    from cdmw.ui.commands.shortcuts_page import _ID_ROLE

    return {str(page.table.item(row, 0).data(_ID_ROLE)) for row in range(page.table.rowCount())}


# ----- E1 -----------------------------------------------------------------
def test_e1_the_shell_s_texture_editor_registers_its_commands(shell):
    from cdmw.ui.texture_workflow.editor_commands import NO_IMAGE_REASON, command_id

    editor = shell.texture_editor_tab.ensure_widget()
    registry = shell.command_registry
    assert editor.workspace_embedded  # the only Texture Editor the app builds
    assert {command_id("open_file"), command_id("tool_paint"), command_id("export_dds")} <= {
        c.id for c in registry.commands("texture_editor")}
    assert registry.get(command_id("clear_selection")).keys == ("Ctrl+D", "Escape")
    assert registry.reason(command_id("save_png")) == NO_IMAGE_REASON
    # Its Actions menu entries are views of the commands, and reach the editor only through them.
    assert editor.action_open_file.property("_cdmw_command_id") == command_id("open_file")
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QMenu

    menu, plain = QMenu(), QAction("plain")
    menu.addAction(plain)  # a menu listens to its entries too
    baseline = plain.receivers("2triggered(bool)")
    menu.deleteLater()
    assert editor.action_open_file.receivers("2triggered(bool)") == baseline + 1
    assert not editor.action_export_png.isEnabled()
    assert editor.action_export_png.toolTip() == NO_IMAGE_REASON


def test_e1_outside_edit_mode_the_texture_editor_s_commands_say_why(shell):
    from cdmw.ui.texture_workflow.editor_commands import EDIT_MODE_REASON, command_id

    editor = shell.texture_editor_tab.ensure_widget()
    registry = shell.command_registry
    shell.textures.set_texture_mode("upscale", activate=False)
    try:
        assert registry.reason(command_id("open_file")) == EDIT_MODE_REASON
    finally:
        shell.textures.set_texture_mode("edit", activate=False)
    assert registry.available(command_id("open_file"))


# ----- E3 -----------------------------------------------------------------
def _open_shortcuts(shell):
    """Settings > Shortcuts as a user opens it (the offscreen platform shows nothing on screen)."""

    from PySide6.QtTest import QTest

    shell.show()
    shell.show_settings()
    shell.settings_tab.show_settings_section("shortcuts")
    page = shell.settings_tab.shortcuts_page
    for _ in range(100):
        if page.isVisible():
            break
        QTest.qWait(20)
    assert page.isVisible()
    return page


def _leave_shortcuts(shell):
    shell.settings_tab.show_settings_section("general")
    QCoreApplication.processEvents()


def test_e3_the_shortcuts_page_lists_the_shell_s_commands_on_first_open(shell):
    page = _open_shortcuts(shell)
    try:
        assert {"shell.settings", "shell.about", "shell.open.archive_browser"} <= _page_ids(page)
    finally:
        _leave_shortcuts(shell)


def test_e3_a_command_registered_while_the_page_is_hidden_is_listed_when_it_shows(shell):
    from cdmw.ui.commands import Command

    _leave_shortcuts(shell)
    shell.command_registry.register(Command("shell.e3_probe", "E3 probe", "shell", lambda: None), replace=True)
    try:
        page = _open_shortcuts(shell)
        assert "shell.e3_probe" in _page_ids(page)
    finally:
        _leave_shortcuts(shell)
        shell.command_registry._commands.pop("shell.e3_probe", None)
        shell.command_registry.refresh("shell")
