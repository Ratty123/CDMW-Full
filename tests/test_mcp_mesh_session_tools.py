"""mesh_session presses the Mesh Editor's own session buttons and fills Name Draft."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

from cdmw.mcp.errors import ToolError
from cdmw.mcp.mesh_session_tools import RESULT_BUTTONS, mesh_session_tools
from cdmw.mcp.schema import validate_arguments
from cdmw.mcp.server import ToolCall
from cdmw.ui.ai_connections.executor import UiExecutor


@pytest.fixture
def editor(tmp_path):
    app = QApplication.instance() or QApplication([])
    tab = QWidget()
    layout = QVBoxLayout(tab)
    pressed = []
    for action, name in RESULT_BUTTONS.items():
        button = QPushButton(action, tab)
        button.setObjectName(name)
        button.clicked.connect(lambda _checked=False, action=action: pressed.append(action))
        button.setVisible(action != "return_to_new_item")  # an ordinary session, not Create New Item's
        layout.addWidget(button)
    tab.draft_name_button = QPushButton("Name Draft...", tab)
    tab.draft_name_button.setObjectName("MeshEditorNameDraftButton")
    layout.addWidget(tab.draft_name_button)
    tab.show()
    app.processEvents()
    executor = UiExecutor(tab)
    context = SimpleNamespace(window=SimpleNamespace(shell=SimpleNamespace(mesh_editor_tab=tab)),
                              ui_call=executor.call, game_folder=lambda: "")
    table = {tool.name: tool for tool in mesh_session_tools()}

    def call(**args):
        tool = table["mesh.session"]
        request = ToolCall(tool, validate_arguments(args, tool.input_schema), context)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(tool.handler, request)
            while not future.done():
                app.processEvents()
            return future.result()

    yield tab, pressed, call
    tab.deleteLater()


def test_result_page_buttons_are_pressed_and_hidden_ones_refused(editor):
    tab, pressed, call = editor
    for action in ("resume", "next_pass", "add_to_archive_browser", "check"):
        assert call(action=action)["pressed"] == action
    assert pressed == ["resume", "next_pass", "add_to_archive_browser", "check"]
    with pytest.raises(ToolError, match="not shown"):
        call(action="return_to_new_item")


def test_name_draft_fills_the_dialog_and_saves_its_lineage(editor, tmp_path, monkeypatch):
    from cdmw.ui.mesh_editor import saved_work_naming

    tab, _pressed, call = editor
    tab.mesh_editor_draft_manifest_path = tmp_path / "draft.json"
    tab.mesh_editor_draft_root = tmp_path
    tab.mesh_editor_draft_lineage = {}
    tab.standalone_controller = SimpleNamespace(active_session_id="s", mesh_service=SimpleNamespace(
        _session=lambda _id: SimpleNamespace(mesh_draft_plan=None)))
    tab.status_message_requested = SimpleNamespace(emit=lambda *_args: None)
    saved = []
    monkeypatch.setattr(saved_work_naming, "list_projects",
                        lambda _root: [SimpleNamespace(name="Armour set", project_id="p1")])
    monkeypatch.setattr(saved_work_naming, "name_session_draft",
                        lambda _path, _plan, *, name, project_id: saved.append((name, project_id)))
    tab.draft_name_button.clicked.connect(lambda: saved_work_naming.name_current_draft(tab))
    result = call(action="name_draft", name="Long coat", project="Armour set")
    assert saved == [("Long coat", "p1")] and result["draft"] == {"name": "Long coat", "project": "p1"}
    with pytest.raises(ToolError, match="no project"):
        call(action="name_draft", name="Long coat", project="Missing")
    with pytest.raises(ToolError, match="name"):
        call(action="name_draft")
