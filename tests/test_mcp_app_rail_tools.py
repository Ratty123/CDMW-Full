import base64
import json
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QSettings

from cdmw.mcp import approvals
from tests.mcp_rail_helpers import RailClient
from tests.test_mcp_real_window import WINDOWS_ONLY, app, profile, real
from tests.test_translation_studio import ENGLISH


def test_local_file_tools_read_owned_content(tmp_path):
    client = RailClient(tmp_path)
    source = tmp_path / "localizationstring_eng.paloc"
    source.write_bytes(ENGLISH)
    state = client.ok("local_file.describe", path=str(source))
    assert state["size"] == len(ENGLISH) and state["extension"] == ".paloc"
    part = client.ok("local_file.bytes", path=str(source), offset=1, length=3)
    assert base64.b64decode(part["base64"]) == ENGLISH[1:4] and part["more"]
    parsed = client.ok("local_file.parse", path=str(source))
    assert "PALOC localization table" in parsed["text"] and parsed["kind"] == "localization"
    text = tmp_path / "sample.xml"
    text.write_text("<x>owned</x>", encoding="utf-8")
    assert client.ok("local_file.parse", path=str(text))["text"] == "<x>owned</x>"


@WINDOWS_ONLY
def test_app_settings_shortcuts_and_diagnostics_reach_the_real_window(real):
    from cdmw.domain.archives.discovery import ARCHIVE_IGNORED_FOLDERS_OVERRIDE_SETTING

    tab = real.window.shell.settings_tab
    real.ok("app_settings_set", {"key": "preferences/remember_splitter_sizes", "value": False})
    assert not tab.remember_splitters_checkbox.isChecked()
    store = QSettings(tab.settings.fileName(), QSettings.Format.IniFormat)
    assert not store.value("preferences/remember_splitter_sizes", True, type=bool)
    real.ok("app_settings_set", {"key": ARCHIVE_IGNORED_FOLDERS_OVERRIDE_SETTING, "value": ["mods/owned"]})
    assert tab.archive_ignored_folders_group.folder_list.item(0).text() == "mods/owned"
    assert store.value(ARCHIVE_IGNORED_FOLDERS_OVERRIDE_SETTING) == ["mods/owned"]
    for key in (approvals.ENABLED_KEY, approvals.FULL_ACCESS_KEY,
                approvals.APPROVAL_KEY.format(effect="edit"), r"ARCHIVE\PACKAGE_ROOT"):
        assert real.error("app_settings_set", {"key": key, "value": "ignored"})["code"] == "refused"

    command = "shell.command_palette"
    page = tab.shortcuts_page
    original = next(row.keys for row in page.rows() if row.command_id == command)
    assert real.ok("shortcuts_change", {"action": "rebind", "command": command, "keys": ["Ctrl+Alt+F8"]})[
        "keys"] == ["Ctrl+Alt+F8"]
    assert page.row_for(command).keys == ("Ctrl+Alt+F8",)
    from cdmw.ui.commands.keymap import keymap_store

    assert keymap_store.load_keymap(store)[command] == ["Ctrl+Alt+F8"]
    assert real.ok("shortcuts_change", {"action": "unbind", "command": command})["keys"] == []
    assert real.ok("shortcuts_change", {"action": "reset", "command": command})["keys"] == list(original)

    client = RailClient(Path(tab.settings.fileName()).parent, window=real.window, settings=tab.settings)
    result = client.ok("app.diagnostics", max_characters=256000)
    evidence = json.loads(result["text"])
    assert "archive_cache_health" in evidence["context"] and "build" in evidence
    assert real.ok("app_state")["dialog"] is None


@WINDOWS_ONLY
def test_turn_history_moves_real_texture_edits_and_keeps_user_edits(real, tmp_path):
    source = tmp_path / "asset.png"
    Image.new("RGBA", (8, 8), "red").save(source)
    location = {"editor": "tool"}
    real.ok("textures_workflow", {**location, "action": "add_textures", "paths": [str(source)]})
    container = real.window.shell.texture_editor_tab
    real.wait_until(lambda: container.widget_if_created() is not None and container.widget_if_created().document is not None)
    editor = container.widget_if_created()
    client = RailClient(tmp_path, window=real.window, settings=real.settings)
    start = editor.history_index
    for name in ("First MCP layer", "Second MCP layer"):
        client.ok("textures.layer", **location, action="add")
        client.ok("textures.layer", **location, action="rename", name=name)
    assert editor.history_index == start + 4
    assert client.ok("app.turn_end")["edit_calls"] == 4
    assert client.ok("app.undo")["steps"] == 4
    assert editor.history_index == start
    assert client.ok("app.redo")["steps"] == 4
    assert editor.history_index == start + 4
    assert [layer.name for layer in editor.document.layers][-2:] == ["First MCP layer", "Second MCP layer"]
    editor.undo()
    assert client.call("app.undo")["error"]["code"] == "unavailable"
    assert editor.history_index == start + 3
