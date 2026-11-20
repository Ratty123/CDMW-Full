"""MCP gap plan item 16: setup, helper locations and language files."""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QWidget

from tests.mcp_rail_helpers import RailClient
from tests.test_mcp_real_window import WINDOWS_ONLY, app, profile, real  # noqa: F401 - fixtures


@pytest.fixture
def settings_client(tmp_path):
    QApplication.instance() or QApplication([])
    store = QSettings(str(tmp_path / "cdmw.ini"), QSettings.Format.IniFormat)
    tab = QWidget()
    shell = SimpleNamespace(settings=store, _tool_widgets_by_key={"settings": tab})
    client = RailClient(tmp_path, window=SimpleNamespace(shell=shell))
    yield client, store
    tab.deleteLater()


def test_helper_locations_are_checked_before_they_are_saved(settings_client, tmp_path) -> None:
    client, store = settings_client
    blender = tmp_path / "Blender Foundation" / "blender.exe"
    blender.parent.mkdir()
    blender.write_bytes(b"")
    assert client.ok("app.settings_set", key="new_item/blender_executable", value=str(blender))["value"] == str(blender)
    assert store.value("new_item/blender_executable") == str(blender)
    notepad = tmp_path / "notepad.exe"
    notepad.write_bytes(b"")
    assert client.call("app.settings_set", key="new_item/blender_executable",
                       value=str(notepad))["error"]["code"] == "invalid_arguments"

    dmm = tmp_path / "DMM"
    dmm.mkdir()
    assert client.call("app.settings_set", key="dmm/install_folder", value=str(dmm))["error"]["code"] == (
        "invalid_arguments")
    (dmm / "DMM.exe").write_bytes(b"")
    client.ok("app.settings_set", key="dmm/install_folder", value=str(dmm))
    assert store.value("dmm/install_folder") == str(dmm)
    assert client.call("app.settings_set", key="dmm/install_folder", value="DMM")["error"]["code"] == (
        "invalid_arguments")
    assert client.ok("app.settings_set", key="dmm/install_folder", value="")["value"] == ""


def test_setup_tools_check_their_inputs(settings_client, tmp_path) -> None:
    client, _store = settings_client
    assert client.call("app.workspace_init", folder=str(tmp_path / "missing"))["error"]["code"] in (
        "invalid_arguments", "refused")
    assert client.call("app.language_export", save_file=str(tmp_path / "x.txt"))["error"]["code"] == (
        "invalid_arguments")
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert client.call("app.language_import", file=str(bad))["error"]["code"] == "invalid_arguments"


@WINDOWS_ONLY
def test_workspace_and_language_files_reach_the_real_window(real, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = real.ok("app_workspace_init", {"folder": str(workspace)})
    assert Path(result["paths"]["output_root"]).is_relative_to(workspace)
    assert Path(result["paths"]["output_root"]).is_dir()

    exported = tmp_path / "en_language.json"
    # The export's completion box is read and closed by the tool, not left waiting.
    assert "Exported language file" in real.ok("app_language_export", {"save_file": str(exported)})["report"]
    payload = json.loads(exported.read_text(encoding="utf-8-sig"))
    assert payload
    payload["language_code"], payload["language_name"] = "xx-test", "Test Language"
    translated = tmp_path / "xx_language.json"
    translated.write_text(json.dumps(payload), encoding="utf-8")
    imported = real.ok("app_language_import", {"file": str(translated)})
    assert imported["language"] == "xx-test" and "Imported language" in imported["report"]
    real.ok("app_settings_set", {"key": "appearance/language", "value": "en"})
