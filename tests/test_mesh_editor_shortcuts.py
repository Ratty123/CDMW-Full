from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QSettings

from cdmw.services.mesh_editor_shortcuts import (
    MAX_SHORTCUT_OVERRIDES,
    MESH_SHORTCUTS_KEY,
    load_mesh_shortcuts,
    save_mesh_shortcuts,
    validated_mesh_shortcuts,
)
from tests.test_mesh_rust_editor_selection import _dispose, _tab


def test_overrides_round_trip_and_reset_all_saves_an_empty_map(tmp_path: Path) -> None:
    path = str(tmp_path / "editor.ini")
    settings = QSettings(path, QSettings.Format.IniFormat)
    overrides = {"tool.move": [], "tool.scale": ["G"], "session.redo": ["Ctrl+Shift+Z", "Ctrl+Y"]}
    assert save_mesh_shortcuts(settings, overrides)
    settings.sync()
    assert load_mesh_shortcuts(QSettings(path, QSettings.Format.IniFormat)) == overrides
    assert save_mesh_shortcuts(settings, {})
    assert load_mesh_shortcuts(settings) == {}


def test_shortcuts_ignore_the_layout_memory_option(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "editor.ini"), QSettings.Format.IniFormat)
    settings.setValue("preferences/remember_splitter_sizes", False)
    assert save_mesh_shortcuts(settings, {"tool.move": ["M"]})
    assert load_mesh_shortcuts(settings) == {"tool.move": ["M"]}


def test_validation_keeps_unknown_ids_and_drops_malformed_entries() -> None:
    value = {
        "future.tool": ["K"],
        "Bad ID": ["K"],
        "tool.move": ["G", "H", "J"],
        "tool.rotate": [7],
        "tool.scale": ["Ctrl+Ä"],
        "tool.grab": ["x" * 33],
        "tool.bend": "Shift+W",
    }
    assert validated_mesh_shortcuts(value) == {"future.tool": ["K"]}
    assert validated_mesh_shortcuts(["tool.move"]) == {}
    many = {f"tool.extra{index}": ["K"] for index in range(MAX_SHORTCUT_OVERRIDES + 10)}
    assert len(validated_mesh_shortcuts(many)) == MAX_SHORTCUT_OVERRIDES


def test_unreadable_saved_shortcuts_fall_back_to_defaults(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "editor.ini"), QSettings.Format.IniFormat)
    settings.setValue(MESH_SHORTCUTS_KEY, "{not json")
    assert load_mesh_shortcuts(settings) == {}
    assert not save_mesh_shortcuts(settings, "tool.move")


def test_editor_event_saves_shortcuts_and_the_next_theme_carries_them(tmp_path: Path) -> None:
    tab = _tab(tmp_path)
    tab.standalone_rust_authoring_session = SimpleNamespace(session_id="rust-session")
    tab.standalone_rust_process_generation = 4
    try:
        assert tab._rust_theme_payload()["shortcuts"] == {}
        tab._handle_rust_protocol_event({
            "event": "shortcuts_changed",
            "protocol": "cdmw_rust_mesh_editor_protocol_v1",
            "session_id": "rust-session",
            "process_generation": 4,
            "shortcuts": {"tool.scale": ["G"], "tool.move": []},
        })
        assert json.loads(tab.settings.value(MESH_SHORTCUTS_KEY)) == {"tool.move": [], "tool.scale": ["G"]}
        assert tab._rust_theme_payload()["shortcuts"] == {"tool.move": [], "tool.scale": ["G"]}
    finally:
        tab.standalone_rust_authoring_session = None
        _dispose(tab)
