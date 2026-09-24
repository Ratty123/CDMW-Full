import json
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QSettings

from cdmw.services.mesh_editor_layout import MESH_LAYOUT_KEY, load_mesh_layout, validated_mesh_layout
from tests.test_mesh_rust_editor_selection import _dispose, _tab


def test_native_panel_event_round_trips_cfg_without_authoring_work(tmp_path):
    tab = _tab(tmp_path)
    tab.standalone_rust_authoring_session = SimpleNamespace(session_id="layout-session", closed=False)
    tab.standalone_rust_process_generation = 3
    layout = {"cdmw_tool_rail": 302, "cdmw_right_panels": 401,
              "cdmw_pinned_tool_settings": 291, "floating": {"Viewport": [80, 160]}}
    event = {"protocol": "cdmw_rust_mesh_editor_protocol_v1", "session_id": "layout-session",
             "process_generation": 3, "event": "layout_changed", "layout": layout}
    try:
        with patch.object(tab, "_start_next_rust_protocol_worker") as worker, patch.object(tab, "_fail_rust_editor") as failed:
            tab._handle_rust_protocol_event(event)
            tab.settings.sync()
            settings = QSettings(tab.settings.fileName(), QSettings.IniFormat)
            assert load_mesh_layout(settings) == layout
            assert tab._rust_theme_payload()["layout"] == layout
            worker.assert_not_called()
            tab._handle_rust_protocol_event({**event, "process_generation": 2, "layout": {"cdmw_tool_rail": 333}})
            failed.assert_called_once()
            assert load_mesh_layout(settings) == layout
    finally:
        tab.standalone_rust_authoring_session = None
        _dispose(tab)


def test_malformed_or_disabled_native_layout_does_not_override_defaults(tmp_path):
    assert validated_mesh_layout({"cdmw_tool_rail": float("nan"), "cdmw_right_panels": -9,
                                  "arbitrary": 400, "floating": {"tool": [True, 90000]}}) == {}
    settings = QSettings(str(tmp_path / "user.cfg"), QSettings.IniFormat)
    settings.setValue(MESH_LAYOUT_KEY, "malformed")
    assert load_mesh_layout(settings) == {}
    settings.setValue(MESH_LAYOUT_KEY, json.dumps({"cdmw_right_panels": 390}))
    settings.setValue("preferences/remember_splitter_sizes", False)
    assert load_mesh_layout(settings) == {}
