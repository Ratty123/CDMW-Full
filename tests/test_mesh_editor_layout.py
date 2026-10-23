from __future__ import annotations

import json

import pytest
from PySide6.QtCore import QSettings

from cdmw.services.mesh_editor_layout import (
    MESH_LAYOUT_KEY, load_mesh_layout, save_mesh_layout, validated_mesh_layout,
)


@pytest.mark.parametrize("enabled", [False, True])
def test_hover_preference_round_trips_with_existing_panel_layout(tmp_path, enabled):
    path = str(tmp_path / "editor.ini")
    settings = QSettings(path, QSettings.Format.IniFormat)
    layout = {"auto_open_parts_on_hover": enabled, "cdmw_tool_rail": 310.0,
              "floating": {"Viewport": [120.0, 180.0]}}
    assert save_mesh_layout(settings, layout)
    settings.sync()
    assert load_mesh_layout(QSettings(path, QSettings.Format.IniFormat)) == layout


@pytest.mark.parametrize("invalid", ["false", 0, None, [], {}])
def test_invalid_hover_preference_is_ignored(invalid):
    assert validated_mesh_layout({"auto_open_parts_on_hover": invalid}) == {}


def test_hover_preference_respects_the_existing_layout_memory_option(tmp_path):
    settings = QSettings(str(tmp_path / "editor.ini"), QSettings.Format.IniFormat)
    layout = {"auto_open_parts_on_hover": False, "cdmw_right_panels": 450.0}
    assert save_mesh_layout(settings, layout)
    settings.setValue("preferences/remember_splitter_sizes", False)
    assert load_mesh_layout(settings) == {}
    assert not save_mesh_layout(settings, {"auto_open_parts_on_hover": True})
    assert json.loads(settings.value(MESH_LAYOUT_KEY)) == layout
