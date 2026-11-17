"""AI connections: app_shortcuts, app_manual and textures_list read what their screens show."""
from __future__ import annotations

import json
import os
import threading
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.mcp.app_read_tools import NO_MESH, app_read_tools
from cdmw.mcp.errors import ToolError
from cdmw.mcp.schema import validate_arguments


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _run(name: str, arguments: dict, context):
    tool = next(tool for tool in app_read_tools() if tool.name == name)
    call = SimpleNamespace(tool=tool, arguments=validate_arguments(arguments, tool.schema_for_clients()),
                           context=context, cancel_event=threading.Event())
    return tool.handler(call)


# ----- Settings > Shortcuts -----------------------------------------------------------
def test_shortcuts_are_the_settings_table_with_changes_and_clashes(app, tmp_path) -> None:
    from cdmw.services import keymap_store
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.commands.registry import Command, CommandRegistry

    registry = CommandRegistry()
    registry.register(Command("shell.mcp_one", "First probe", "shell", lambda: None, keys=("Ctrl+Alt+F10",)))
    registry.register(Command("browse.mcp_two", "Second probe", "browse", lambda: None, keys=("Ctrl+Alt+F9",)))
    settings = create_settings(settings_file_path=tmp_path / "keys.cfg")
    # Rebound onto the other's key: a shell key clashes with a key anywhere.
    keymap_store.set_override(settings, "browse.mcp_two", ["Ctrl+Alt+F10"])
    context = SimpleNamespace(command_registry=lambda: registry, settings=settings)

    rows = {row["command"]: row for row in _run("app.shortcuts", {}, context)["shortcuts"]}
    assert rows["browse.mcp_two"] == {"command": "browse.mcp_two", "label": "Second probe", "context": "browse",
                                      "keys": ["Ctrl+Alt+F10"], "default_keys": ["Ctrl+Alt+F9"], "changed": True,
                                      "clashes_with": ["shell.mcp_one"]}
    assert rows["shell.mcp_one"]["clashes_with"] == ["browse.mcp_two"] and not rows["shell.mcp_one"]["changed"]
    # The Mesh Editor's commands are listed while no editor runs, as the table lists them.
    assert any(row["context"] == "mesh_editor" for row in rows.values())
    changed = _run("app.shortcuts", {"changed_only": True}, context)["shortcuts"]
    assert [row["command"] for row in changed] == ["browse.mcp_two"]
    clashing = _run("app.shortcuts", {"conflicts_only": True, "context": "shell"}, context)["shortcuts"]
    assert [row["command"] for row in clashing] == ["shell.mcp_one"]
    found = _run("app.shortcuts", {"query": "second probe"}, context)["shortcuts"]
    assert [row["command"] for row in found] == ["browse.mcp_two"]


# ----- Help ------------------------------------------------------------------------------
def test_the_manual_lists_finds_and_reads_help_topics() -> None:
    topics = _run("app.manual", {}, SimpleNamespace())["topics"]
    ids = [topic["id"] for topic in topics]
    assert "profile_settings" in ids and "mesh_editor" in ids and len(ids) == len(set(ids))
    assert all(topic["url"].startswith("https://github.com/") and "/wiki/" in topic["url"] for topic in topics)
    found = [topic["id"] for topic in _run("app.manual", {"query": "Shortcuts table conflicts"}, SimpleNamespace())[
        "topics"]]
    assert "profile_settings" in found
    one = _run("app.manual", {"topic": "profile_settings"}, SimpleNamespace())
    assert one["title"] == "Profile & Settings" and "<" not in one["text"] and "Settings / Shortcuts" in one["text"]
    assert one["url"].endswith("#profile_settings")
    short = _run("app.manual", {"topic": "profile_settings", "max_characters": 40}, SimpleNamespace())
    assert len(short["text"]) == 40 and short["truncated"]
    with pytest.raises(ToolError) as missing:
        _run("app.manual", {"topic": "no_such_topic"}, SimpleNamespace())
    assert missing.value.code == "not_found"


# ----- the Mesh Editor's Textures panel ---------------------------------------------------
class _Document(QWidget):
    def __init__(self, root) -> None:
        super().__init__()
        self.standalone_rust_session_root = root


class _Tabs(QWidget):
    def __init__(self, active) -> None:
        super().__init__()
        self.active = active


def _mesh_context(view) -> SimpleNamespace:
    return SimpleNamespace(window=SimpleNamespace(shell=SimpleNamespace(mesh_editor_tab=view)),
                           ui_call=lambda function: function())


def test_textures_are_the_panels_rows_for_the_shown_tab_without_the_panel(app, tmp_path) -> None:
    from tests.test_mesh_editor_textures_panel import _manifest

    (tmp_path / "manifest.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    other = tmp_path / "other"
    other.mkdir()
    shown = _Document(tmp_path)
    view = _Tabs(shown)
    result = _run("textures.list", {}, _mesh_context(view))
    assert result["session"] == str(tmp_path)
    assert [(p["part_index"], p["part"], p["source_file"]) for p in result["parts"]] == [
        (0, "Chest", "upper.pac"), (1, "Arms", "arms.pac")]
    chest = result["parts"][0]["textures"]
    base = next(row for row in chest if row["role"] == "base_color")
    assert base == {"role": "base_color", "role_label": "Base colour",
                    "game_path": "character/texture/cd_armor_01_d.dds", "file_name": "cd_armor_01_d.dds",
                    "shared": True, "not_one_file": False, "made_from": [],
                    "session_file": str(tmp_path / "texture-0000-aaaaaaaaaaaa.dds")}
    # Another tab shown, whose mesh is still being prepared: it says so.
    view.active = _Document(other)
    with pytest.raises(ToolError) as preparing:
        _run("textures.list", {}, _mesh_context(view))
    assert preparing.value.code == "unavailable"


def test_textures_without_a_mesh_say_what_to_open(app) -> None:
    from cdmw.ui.shell.lazy_tool_tab import LazyToolTab

    for view in (None, _Tabs(_Document(None))):
        with pytest.raises(ToolError) as refused:
            _run("textures.list", {}, _mesh_context(view))
        assert refused.value.code == "unavailable" and refused.value.message == NO_MESH
    # The Mesh Editor tab not built yet: the tool does not build it.
    built = []
    lazy = LazyToolTab(lambda: built.append(True) or _Tabs(_Document(None)))
    with pytest.raises(ToolError):
        _run("textures.list", {}, _mesh_context(lazy))
    app.processEvents()
    assert built == [] and lazy.widget_if_created() is None
