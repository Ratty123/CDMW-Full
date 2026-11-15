"""What follows a keymap save (reviews of 9ff3c4bd8 and 59fd00c5e, 2026-11-13).

A listener that fails is logged and the others still run, and the save stands.
Create New Item gets the palette's new keys at once, not at its next state change.
"""

from __future__ import annotations

import logging

import pytest
from PySide6.QtCore import QCoreApplication, QObject, QSettings
from PySide6.QtWidgets import QApplication

from cdmw.services import keymap_store
from cdmw.ui.new_item import rust_ui_tab


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


@pytest.fixture
def listeners(monkeypatch):
    saved: list = []
    monkeypatch.setattr(keymap_store, "_SAVED_LISTENERS", saved)
    return saved


def test_a_failing_listener_is_logged_and_the_rest_still_follow(settings, listeners, caplog) -> None:
    heard = []

    def broken(_settings):
        raise RuntimeError("listener broke")

    keymap_store.on_keymap_saved(broken)
    keymap_store.on_keymap_saved(lambda current: heard.append(current))
    with caplog.at_level(logging.ERROR, logger="cdmw.services.keymap_store"):
        keymap = keymap_store.set_override(settings, "shell.settings", ["Ctrl+,"])
    assert keymap == {"shell.settings": ["Ctrl+,"]}
    assert heard == [settings]
    assert keymap_store.load_keymap(settings) == {"shell.settings": ["Ctrl+,"]}
    assert "listener broke" in caplog.text


class _Tab(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.published = 0

    def _publish_state(self) -> None:
        self.published += 1


def test_create_new_item_publishes_its_state_when_the_keymap_is_saved(settings, listeners) -> None:
    QApplication.instance() or QApplication([])
    tab = _Tab()
    rust_ui_tab._follow_keymap(tab)
    keymap_store.set_override(settings, "shell.command_palette", ["Ctrl+K"])
    QCoreApplication.processEvents()
    assert tab.published == 1

    del tab  # a closed tab drops out
    keymap_store.set_override(settings, "shell.command_palette", ["Ctrl+J"])
    QCoreApplication.processEvents()


def test_the_palette_may_not_take_a_key_a_mesh_editor_command_uses() -> None:
    from types import SimpleNamespace

    from cdmw.ui.commands.keymap import KeymapRow
    from cdmw.ui.commands.shortcuts_page import ShortcutsPage

    rows = [KeymapRow("mesh_editor.tool.knife", "mesh_editor", "Knife", ("K",), ("Ctrl+K",), "Tools"),
            KeymapRow("shell.settings", "shell", "Settings", ("Ctrl+,",), ("Ctrl+,",))]
    page = SimpleNamespace(rows=lambda: rows)
    keys, reason = ShortcutsPage._palette_key_check(page, ["Ctrl+K"])
    assert keys == [] and "Knife" in reason
    assert ShortcutsPage._palette_key_check(page, ["Ctrl+Shift+P"]) == (["Ctrl+Shift+P"], "")
    # A shell command's key is a conflict to report, not one to refuse.
    assert ShortcutsPage._palette_key_check(page, ["Ctrl+,"]) == (["Ctrl+,"], "")
