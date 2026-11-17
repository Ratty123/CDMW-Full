"""AI connections against the real main window, built headlessly: the tools find what they name."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cdmw.app import app_folder
from tests.mcp_full_helpers import McpApp

pytestmark = pytest.mark.skipif(os.name != "nt", reason="AI connections are Windows-only")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def profile(monkeypatch, tmp_path) -> Path:
    folder = tmp_path / "profile"
    folder.mkdir()
    monkeypatch.setenv(app_folder.PROFILE_DIR_ENV, str(folder))
    app_folder._reset_for_tests()
    yield folder
    app_folder._reset_for_tests()


@pytest.fixture
def real(app, profile, tmp_path):
    from cdmw.app.events import AppEventBus
    from cdmw.services.service_container import ServiceContainer
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.ai_connections.controller import remove_ai_connections
    from cdmw.ui.main_window import MainWindow
    from cdmw.ui.shell.app_context import AppContext

    settings = create_settings(settings_file_path=tmp_path / "real.cfg")
    context = AppContext(settings=settings, services=ServiceContainer.create_default(settings=settings),
                         event_bus=AppEventBus())
    with patch.dict(os.environ, {"CDMW_GUI_STARTUP_SMOKE": "1"}):
        window = MainWindow(app_context=context)
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.show()
        app.processEvents()
    remove_ai_connections()  # the window's own; this test brings the harness's
    session = McpApp(app, profile, settings, window)
    try:
        yield session
    finally:
        session.close()
        window.close()
        window.deleteLater()
        app.processEvents()


def test_the_tools_read_and_drive_the_real_window(real) -> None:
    from cdmw.ui.shell.compact.registry import COMPACT_TOOL_SPECS

    mcp = real
    state = mcp.ok("app_state")
    assert state["title"].endswith("[AI connections on, Full access]")
    assert [row["key"] for row in state["tools"]] == [spec.key for spec in COMPACT_TOOL_SPECS]
    assert state["tool"] in {spec.key for spec in COMPACT_TOOL_SPECS}
    assert state["dialog"] is None and state["mesh_documents"] == 0 and state["archives_loaded"] is False
    # Every rail entry's command is in the registry, and app_open_tool runs it.
    listed = {row["id"] for row in mcp.ok("commands_list", {"context": "shell", "limit": 500})["commands"]}
    assert {"shell.open." + spec.key for spec in COMPACT_TOOL_SPECS} <= listed
    available = next(row["key"] for row in state["tools"] if row["available"] and row["key"] != state["tool"])
    mcp.ok("app_open_tool", {"tool": available})
    assert mcp.ok("app_state")["tool"] == available
    by_command = mcp.ok("app_run_command", {"command": "shell.open." + state["tool"]})
    assert by_command["ran"] and mcp.ok("app_state")["tool"] == state["tool"]
    # The page's controls, and a picture of the window.
    controls = mcp.ok("app_ui", {"limit": 500})
    assert controls["total"] > 10 and controls["window"]["title"].startswith("Crimson Desert Mod Workbench")
    assert {"button", "label"} <= {row["kind"] for row in controls["controls"]}
    picture = mcp.call("app_screenshot", {"max_side": 400})
    assert not picture["isError"] and picture["content"][0]["type"] == "image"
    # The area tools say what is missing instead of failing.
    assert mcp.ok("mesh_state") == {"documents": [], "open": False}
    assert mcp.ok("textures_state")["open"] is False
    selection = mcp.ok("view_selection")
    assert selection["selected"] == "" and selection["editing_here"] is False
    new_item = mcp.ok("new_item_state")
    assert new_item["open"] in (True, False)
    assert mcp.error("view_open", {"path": "character/model/none.pac"})["code"] == "unavailable"
    assert mcp.error("mesh_open", {"path": "character/model/none.pac"})["code"] == "unavailable"
    # The game folder's field is the user's alone, also on the real window.
    from cdmw.mcp.ui_tree import widget_id

    field = real.window.archive.archive_package_root_edit
    error = mcp.error("app_ui_act", {"widget": widget_id(field), "action": "set_text", "value": "C:/x"})
    assert error["code"] == "refused" and field.text() != "C:/x"
