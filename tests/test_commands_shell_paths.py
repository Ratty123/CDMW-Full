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


# ----- E4 and E7: keys recorded by the page -------------------------------
def _change(shell, monkeypatch, command_id, key=None, modifiers=None, *, slot=0):
    """Change... on ``command_id``'s row: press ``key`` in a slot, then OK if the dialog allows it."""

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDialog, QDialogButtonBox

    from cdmw.ui.commands import shortcuts_page as module
    from cdmw.ui.commands.shortcuts_page import _ID_ROLE

    seen = {}

    def exec_(dialog):
        editors = getattr(dialog, "editors", [dialog.editor])
        if key is not None:
            QTest.keyClick(editors[slot], key, modifiers or Qt.KeyboardModifier.NoModifier)
        ok = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)
        seen["ok"], seen["text"] = ok.isEnabled(), dialog.conflict.text()
        return QDialog.DialogCode.Accepted if ok.isEnabled() else QDialog.DialogCode.Rejected

    monkeypatch.setattr(module.KeyDialog, "exec", exec_)
    page = _open_shortcuts(shell)
    try:
        page.search.setText(command_id)
        row = next(r for r in range(page.table.rowCount()) if page.table.item(r, 0).data(_ID_ROLE) == command_id)
        page.table.selectRow(row)
        page.change_selected()
    finally:
        page.search.setText("")
        _leave_shortcuts(shell)
    return seen


@pytest.fixture
def clean_keymap(shell):
    from cdmw.ui.commands.keymap import reset_all

    reset_all(shell.command_registry, shell.settings)
    yield shell
    reset_all(shell.command_registry, shell.settings)


def _helper_keys(shell, helper_id):
    from cdmw.services.keymap_store import mesh_editor_overrides

    return mesh_editor_overrides(shell.settings).get(helper_id)


@pytest.mark.parametrize(("key", "modifiers", "expected"), [
    ("Key_PageUp", (), ["PageUp"]),
    ("Key_Delete", ("ControlModifier",), ["Ctrl+Delete"]),
    ("Key_1", ("KeypadModifier",), ["Num1"]),  # not the top-row 1
    ("Key_Plus", ("KeypadModifier", "ControlModifier"), ["Ctrl+NumPlus"]),
    ("Key_Period", ("KeypadModifier",), ["NumDecimal"]),
    ("Key_Comma", ("ShiftModifier",), ["Shift+Comma"]),
])
def test_e4_a_key_recorded_for_a_mesh_editor_command_is_saved_as_the_helper_reads_it(
        clean_keymap, monkeypatch, key, modifiers, expected):
    from PySide6.QtCore import Qt

    from cdmw.ui.commands.helper_keys import helper_binding

    shell = clean_keymap
    mods = Qt.KeyboardModifier.NoModifier
    for name in modifiers:
        mods |= getattr(Qt.KeyboardModifier, name)
    seen = _change(shell, monkeypatch, "mesh_editor.tool.move", getattr(Qt.Key, key), mods)
    assert seen["ok"]
    saved = _helper_keys(shell, "tool.move")
    assert saved == expected
    assert all(helper_binding(text).text == text for text in saved)  # the helper's grammar takes it unchanged


@pytest.mark.parametrize(("key", "modifiers", "reason"), [
    ("Key_Escape", (), "EDITING_KEY_REASON"),
    ("Key_Space", (), "EDITING_KEY_REASON"),
    ("Key_Left", ("ControlModifier",), "EDITING_KEY_REASON"),
    ("Key_F4", ("AltModifier",), "CLOSE_WINDOW_REASON"),
    ("Key_C", ("ControlModifier",), "CLIPBOARD_REASON"),
    ("Key_V", ("ControlModifier", "ShiftModifier"), "CLIPBOARD_REASON"),
    ("Key_P", ("ControlModifier", "ShiftModifier"), "APP_COMMAND_REASON"),
    ("Key_A", ("MetaModifier",), "UNSUPPORTED_REASON"),
    ("Key_Print", (), "UNSUPPORTED_REASON"),
])
def test_e4_a_key_the_helper_refuses_is_refused_by_the_page_with_its_reason(
        clean_keymap, monkeypatch, key, modifiers, reason):
    from PySide6.QtCore import Qt

    from cdmw.ui.commands import helper_keys

    shell = clean_keymap
    mods = Qt.KeyboardModifier.NoModifier
    for name in modifiers:
        mods |= getattr(Qt.KeyboardModifier, name)
    seen = _change(shell, monkeypatch, "mesh_editor.tool.move", getattr(Qt.Key, key), mods)
    assert not seen["ok"] and seen["text"] == getattr(helper_keys, reason)
    assert _helper_keys(shell, "tool.move") is None  # nothing saved: the default stays


def test_e4_a_selection_modifier_keeps_its_modifier_and_refuses_a_chord(clean_keymap, monkeypatch):
    from PySide6.QtCore import Qt

    from cdmw.ui.commands.helper_keys import MODIFIER_ONLY_REASON

    shell = clean_keymap
    seen = _change(shell, monkeypatch, "mesh_editor.selection.extend_modifier", Qt.Key.Key_A)
    assert not seen["ok"] and seen["text"] == MODIFIER_ONLY_REASON
    seen = _change(shell, monkeypatch, "mesh_editor.selection.extend_modifier")  # OK without a new key
    assert seen["ok"] and _helper_keys(shell, "selection.extend_modifier") in (None, ["Shift"])


def test_e4_every_mesh_editor_default_reads_back_through_the_page_grammar():
    """The Python side of shortcuts.rs's every_default_parses_and_round_trips."""
    from PySide6.QtGui import QKeySequence

    from cdmw.ui.commands.helper_keys import helper_binding, qt_key_text
    from cdmw.ui.commands.keymap import mesh_editor_command_list

    for spec in mesh_editor_command_list():
        for text in spec["defaults"]:
            binding = helper_binding(text)
            assert binding.text == text and not binding.reason, text
            assert binding.modifier_only == (spec["group"] == "SelectionModifiers"), text
            if not binding.modifier_only:
                # What the key editor shows for it reads back as the same binding.
                shown = QKeySequence(qt_key_text(text)).toString(QKeySequence.SequenceFormat.PortableText)
                assert helper_binding(shown).text == text, (text, shown)


# ----- E7 -----------------------------------------------------------------
def test_e7_the_palette_shows_the_keymap_s_keys(clean_keymap):
    from PySide6.QtCore import Qt

    from cdmw.ui.commands.keymap import save_keys
    from cdmw.ui.commands.palette import open_command_palette

    shell = clean_keymap
    save_keys(shell.command_registry, shell.settings, "shell.about", ["Ctrl+Alt+F12"])
    palette = open_command_palette(shell)
    try:
        palette.search.setText("shell.about")
        texts = [palette.list.item(i).text() for i in range(palette.list.count())
                 if palette.list.item(i).data(Qt.ItemDataRole.UserRole + 1) == "shell.about"]
        assert texts and "Ctrl+Alt+F12" in texts[0]
    finally:
        palette.close()
        palette.deleteLater()


def test_e7_changing_a_two_key_command_keeps_its_second_key(clean_keymap, monkeypatch):
    from PySide6.QtCore import Qt

    from cdmw.services.keymap_store import load_keymap, texture_editor_keys

    shell = clean_keymap
    shell.texture_editor_tab.ensure_widget()
    seen = _change(shell, monkeypatch, "texture_editor.clear_selection", Qt.Key.Key_E,
                   Qt.KeyboardModifier.ControlModifier)
    assert seen["ok"]
    assert load_keymap(shell.settings)["texture_editor.clear_selection"] == ["Ctrl+E", "Escape"]
    keys = texture_editor_keys(shell.settings)
    assert (keys["clear_selection"], keys["clear_selection_alt"]) == ("Ctrl+E", "Escape")


def test_e7_unbinding_a_two_key_command_clears_both_keys_in_the_editor(clean_keymap):
    from PySide6.QtGui import QKeySequence

    from cdmw.services.keymap_store import texture_editor_keys
    from cdmw.ui.commands.keymap import save_keys

    shell = clean_keymap
    editor = shell.texture_editor_tab.ensure_widget()
    save_keys(shell.command_registry, shell.settings, "texture_editor.clear_selection", [])
    keys = texture_editor_keys(shell.settings)
    assert keys["clear_selection"] == "" and keys["clear_selection_alt"] == ""
    live = {shortcut.key().toString(QKeySequence.SequenceFormat.PortableText) for shortcut in editor._shortcut_objects}
    assert "Esc" not in live and "Ctrl+D" not in live
