"""P12 step 4: one keymap for Qt and the Mesh Editor helper, and its Settings page."""
from __future__ import annotations

import json

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from cdmw.services import keymap_store
from cdmw.services.mesh_editor_shortcuts import load_mesh_shortcuts, save_mesh_shortcuts
from cdmw.ui.commands import Command, CommandRegistry


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


def test_an_upgrade_from_saved_mesh_editor_overrides_keeps_them(settings):
    settings.setValue(keymap_store.LEGACY_MESH_KEY, json.dumps({"tool.move": ["M"], "tool.rotate": []}))
    assert not keymap_store.keymap_written(settings)
    assert keymap_store.load_keymap(settings) == {"mesh_editor.tool.move": ["M"], "mesh_editor.tool.rotate": []}
    # The helper still receives its overrides by its own ids.
    assert load_mesh_shortcuts(settings) == {"tool.move": ["M"], "tool.rotate": []}
    # The first write keeps them, and from then on the keymap is the store.
    keymap_store.set_override(settings, "shell.settings", ["Ctrl+,"])
    assert keymap_store.keymap_written(settings)
    settings.setValue(keymap_store.LEGACY_MESH_KEY, json.dumps({"tool.move": ["X"]}))
    assert load_mesh_shortcuts(settings) == {"tool.move": ["M"], "tool.rotate": []}


def test_an_upgrade_from_saved_texture_editor_keys_keeps_them(settings):
    settings.setValue("texture_editor/shortcuts/open_file", "Ctrl+Alt+F")
    settings.setValue("texture_editor/shortcuts/tool_paint", "B")  # the default: not an override
    settings.setValue("texture_editor/shortcuts/tool_erase", "")  # unbound
    assert keymap_store.load_keymap(settings) == {"texture_editor.open_file": ["Ctrl+Alt+F"],
                                                  "texture_editor.tool_erase": []}
    keys = keymap_store.texture_editor_keys(settings)
    assert keys["open_file"] == "Ctrl+Alt+F" and keys["tool_paint"] == "B" and keys["tool_erase"] == ""


def test_both_editors_and_the_shell_share_one_store(settings):
    save_mesh_shortcuts(settings, {"tool.scale": ["T"]})
    keymap_store.save_texture_editor_keys(settings, {"fit_view": "Shift+F", "tool_paint": "B"})
    keymap_store.set_override(settings, "shell.about", ["F1"])
    assert keymap_store.load_keymap(settings) == {
        "mesh_editor.tool.scale": ["T"], "texture_editor.fit_view": ["Shift+F"], "shell.about": ["F1"]}
    # The helper's own editor replaces only its part.
    save_mesh_shortcuts(settings, {})
    assert "mesh_editor.tool.scale" not in keymap_store.load_keymap(settings)
    keymap_store.reset_keymap(settings, prefix="texture_editor.")
    assert keymap_store.load_keymap(settings) == {"shell.about": ["F1"]}


def test_conflicts_are_named_within_a_context_and_for_shell_keys(app):
    from cdmw.ui.commands.keymap import KeymapRow, conflicts

    rows = [
        KeymapRow("texture_editor.tool_paint", "texture_editor", "Paint tool", ("B",), ("B",)),
        KeymapRow("texture_editor.tool_blur", "texture_editor", "Blur tool", (), ("B",)),
        KeymapRow("mesh_editor.tool.bend", "mesh_editor", "Bend", (), ("B",)),  # another context: fine
        KeymapRow("shell.about", "shell", "About", (), ("Ctrl+K",)),
        KeymapRow("browse.copy", "browse", "Copy", (), ("ctrl+k",)),
    ]
    clashes = conflicts(rows)
    assert clashes["texture_editor.tool_paint"] == ["texture_editor.tool_blur"]
    assert "mesh_editor.tool.bend" not in clashes
    assert clashes["shell.about"] == ["browse.copy"]


def test_the_mesh_editor_s_command_list_is_committed(app):
    from cdmw.ui.commands.keymap import mesh_editor_command_list

    ids = {row["id"] for row in mesh_editor_command_list()}
    assert {"tool.move", "tool.grab", "session.undo"} <= ids


def test_the_shortcuts_page_rebinds_resets_and_tells_every_consumer(app, settings):
    from cdmw.ui.commands.shortcuts_page import ShortcutsPage

    registry = CommandRegistry()
    registry.register(Command("shell.about", "About", "shell", lambda: None))
    heard = []
    registry.keymap_changed.connect(lambda: heard.append(1))
    page = ShortcutsPage(registry, settings)
    try:
        ids = {page.table.item(row, 0).data(Qt.ItemDataRole.UserRole + 1) for row in range(page.table.rowCount())}
        assert "shell.about" in ids and "mesh_editor.tool.move" in ids  # editor rows without an editor running
        page.search.setText("about")
        assert page.table.rowCount() == 1
        page.table.selectRow(0)
        page._save("shell.about", ["F1"])
        assert heard == [1] and keymap_store.load_keymap(settings) == {"shell.about": ["F1"]}
        assert page.table.item(0, 2).text() == "F1"
        # A key another command holds is named before it is saved.
        page.search.setText("")
        move = next(r for r in page.rows() if r.command_id == "mesh_editor.tool.move")
        assert page.conflict_text(next(r for r in page.rows() if r.command_id == "shell.about"),
                                  list(move.keys)).startswith("Also used by:")
        page._save("shell.about", None)
        assert keymap_store.load_keymap(settings) == {}
    finally:
        page.deleteLater()


def test_shell_keys_run_their_command_and_follow_a_rebind(app, settings):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit, QWidget

    from cdmw.ui.commands.keymap import QtShortcutBinder

    registry = CommandRegistry()
    ran = []
    registry.register(Command("shell.about", "About", "shell", lambda: ran.append("about"), keys=("F7",)))
    window = QWidget()
    field = QLineEdit(window)
    window.show()
    QtShortcutBinder(registry, settings, shell_parent=window)
    try:
        window.activateWindow()
        assert QTest.qWaitForWindowActive(window)
        QTest.keyClick(window, Qt.Key.Key_F7)
        assert ran == ["about"]
        from cdmw.ui.commands.keymap import save_keys

        save_keys(registry, settings, "shell.about", ["F8"])
        QTest.keyClick(window, Qt.Key.Key_F7)
        QTest.keyClick(window, Qt.Key.Key_F8)
        assert ran == ["about", "about"]
        # A single letter never fires while a text field has focus.
        save_keys(registry, settings, "shell.about", ["B"])
        field.setFocus()
        QTest.keyClick(field, Qt.Key.Key_B)
        assert ran == ["about", "about"] and field.text() == "b"
    finally:
        window.deleteLater()
