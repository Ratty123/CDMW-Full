"""Settings > Shortcuts as a structured table (item 12): columns, groups, sorting, filters,
conflicts marked, keys recorded in place, and Restore all defaults."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cdmw.services import keymap_store
from cdmw.ui.commands import Command, CommandRegistry

_APP = QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


@pytest.fixture
def page(settings):
    from cdmw.ui.commands.shortcuts_page import ShortcutsPage

    registry = CommandRegistry()
    registry.register_all([
        Command("shell.about", "About", "shell", lambda: None),
        Command("shell.settings", "Settings", "shell", lambda: None, keys=("Ctrl+,",)),
        Command("browse.copy_name", "Copy Filename", "browse", lambda: None, keys=("Ctrl+Shift+C",)),
        Command("browse.zoom", "Zoom", "browse", lambda: None, keys=("Z", "Ctrl+Z")),
    ])
    shown = ShortcutsPage(registry, settings)
    shown.resize(900, 600)
    shown.show()
    try:
        yield shown
    finally:
        shown.close()
        shown.deleteLater()
        QCoreApplication.processEvents()


def _texts(page, column):
    return [page.item_for(command_id).text(column) for command_id in page.command_ids()]


def test_the_table_has_a_column_each_for_command_keys_where_and_conflicts(page):
    from cdmw.ui.commands.shortcuts_page import COLUMN_COMMAND, COLUMN_CONFLICTS, COLUMN_KEYS, COLUMN_WHERE

    header = page.table.headerItem()
    assert [header.text(column) for column in range(page.table.columnCount())] == [
        "Command", "Keys", "Where", "Conflicts with"]
    item = page.item_for("browse.zoom")
    assert (item.text(COLUMN_COMMAND), item.text(COLUMN_KEYS), item.text(COLUMN_WHERE),
            item.text(COLUMN_CONFLICTS)) == ("Zoom", "Z, Ctrl+Z", "Browse Archives", "")


def test_rows_group_by_area_and_sort_by_any_column(page):
    from cdmw.ui.commands.shortcuts_page import COLUMN_KEYS

    groups = [page.table.topLevelItem(i).text(0) for i in range(page.table.topLevelItemCount())]
    assert groups[:2] == ["Everywhere (2)", "Browse Archives (2)"]  # the area order, not the alphabet
    assert all(page.table.topLevelItem(i).childCount() for i in range(page.table.topLevelItemCount()))
    page.group_checkbox.setChecked(False)
    assert page.table.topLevelItemCount() == len(page.command_ids())  # one flat list
    page.table.sortByColumn(COLUMN_KEYS, Qt.SortOrder.DescendingOrder)
    keys = _texts(page, COLUMN_KEYS)
    assert keys == sorted(keys, key=str.casefold, reverse=True)


def test_search_and_show_filter_the_rows(page):
    from cdmw.ui.commands.shortcuts_page import SHOW_CHANGED, SHOW_CONFLICTS

    page.search.setText("ctrl+,")
    assert page.command_ids() == ["shell.settings"]
    page.search.setText("zoom browse")  # every word must match
    assert page.command_ids() == ["browse.zoom"]
    page.search.setText("")
    page.show_combo.setCurrentIndex(SHOW_CONFLICTS)
    before = set(page.command_ids())  # the Mesh Editor's committed defaults share a key or two
    assert not before & {"shell.about", "browse.zoom"}
    page._save("shell.about", ["Z"])  # Z is Zoom's, and a shell key clashes everywhere
    assert set(page.command_ids()) == before | {"shell.about", "browse.zoom"}
    page.show_combo.setCurrentIndex(SHOW_CHANGED)
    assert page.command_ids() == ["shell.about"]


def test_a_conflict_is_marked_on_its_row_and_counted(page):
    from cdmw.ui.commands.shortcuts_page import COLUMN_COMMAND, COLUMN_CONFLICTS

    from cdmw.ui.commands.keymap import conflicts

    before = len(conflicts(page.rows()))
    page._save("shell.about", ["Z"])
    about, zoom, plain = (page.item_for(i) for i in ("shell.about", "browse.zoom", "shell.settings"))
    assert about.text(COLUMN_CONFLICTS) == "Zoom" and zoom.text(COLUMN_CONFLICTS) == "About"
    marked = about.background(COLUMN_COMMAND).color()
    assert marked.isValid() and marked == zoom.background(COLUMN_COMMAND).color()
    assert plain.background(COLUMN_COMMAND).style() == Qt.BrushStyle.NoBrush
    assert not about.icon(COLUMN_CONFLICTS).isNull()
    assert page.conflict_count.text() == f"Conflicts: {before + 2}"


def _open_editor(page, command_id):
    from cdmw.ui.commands.shortcuts_page import COLUMN_KEYS, KeyEdit

    page.table.editItem(page.item_for(command_id), COLUMN_KEYS)
    # A closed editor lingers until Qt deletes it; the open one is the visible one.
    editors = [e for e in page.table.findChildren(KeyEdit, "ShortcutsInlineKey") if e.isVisible()]
    assert len(editors) == 1
    return editors[0]


def _record_in_place(page, command_id, key, modifiers=Qt.KeyboardModifier.NoModifier):
    editor = _open_editor(page, command_id)
    QTest.keyClick(editor, key, modifiers)
    for _ in range(5):
        QCoreApplication.processEvents()


def test_a_key_is_recorded_in_place_and_keeps_the_second_key(page, settings):
    from cdmw.ui.commands.shortcuts_page import COLUMN_KEYS

    _record_in_place(page, "browse.zoom", Qt.Key.Key_F7)
    assert keymap_store.load_keymap(settings) == {"browse.zoom": ["F7", "Ctrl+Z"]}
    assert page.item_for("browse.zoom").text(COLUMN_KEYS) == "F7, Ctrl+Z"
    assert page.item_for("browse.zoom").font(COLUMN_KEYS).bold()  # changed from its default
    _record_in_place(page, "shell.about", Qt.Key.Key_F7)
    assert page.message.text() == "Also used by: Zoom"  # saved, and the clash is named


@pytest.mark.parametrize(("key", "modifiers", "expected"), [
    ("Key_1", ("KeypadModifier",), ["Num1"]),  # the numpad, not the top-row 1
    ("Key_Plus", ("KeypadModifier", "ControlModifier"), ["Ctrl+NumPlus"]),
    ("Key_PageUp", (), ["PageUp"]),
])
def test_a_mesh_editor_key_recorded_in_place_is_saved_as_the_helper_reads_it(page, settings, key, modifiers, expected):
    from cdmw.services.keymap_store import mesh_editor_overrides

    mods = Qt.KeyboardModifier.NoModifier
    for name in modifiers:
        mods |= getattr(Qt.KeyboardModifier, name)
    _record_in_place(page, "mesh_editor.tool.move", getattr(Qt.Key, key), mods)
    assert mesh_editor_overrides(settings).get("tool.move") == expected


def test_a_key_the_mesh_editor_refuses_is_not_saved_in_place(page, settings):
    from cdmw.ui.commands.helper_keys import CLIPBOARD_REASON

    _record_in_place(page, "mesh_editor.tool.move", Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert keymap_store.load_keymap(settings) == {}
    assert page.message.text() == CLIPBOARD_REASON


def test_a_refill_while_a_key_is_being_recorded_waits_for_the_editor(page):
    editor = _open_editor(page, "browse.zoom")
    page.registry.register(Command("shell.late", "Late", "shell", lambda: None))
    page.refill()
    assert editor.isVisible() and "shell.late" not in page.command_ids()
    QTest.keyClick(editor, Qt.Key.Key_Escape)  # cancels: nothing saved, the table catches up
    for _ in range(5):
        QCoreApplication.processEvents()
    assert "shell.late" in page.command_ids()


def test_reset_to_default_and_restore_all_defaults(page, settings, monkeypatch):
    page._save("shell.about", ["F2"])
    page._save("browse.zoom", [])
    assert page.select_command("browse.zoom")
    page.reset_button.click()
    assert keymap_store.load_keymap(settings) == {"shell.about": ["F2"]}
    asked = []
    monkeypatch.setattr(type(page), "confirm_reset_all", lambda self: asked.append(1) or False)
    page.reset_all_button.click()
    assert asked == [1] and keymap_store.load_keymap(settings) == {"shell.about": ["F2"]}
    monkeypatch.setattr(type(page), "confirm_reset_all", lambda self: True)
    page.reset_all_button.click()
    assert keymap_store.load_keymap(settings) == {}
    assert not page.reset_all_button.isEnabled()  # nothing left to restore
