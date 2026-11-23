"""AI connections: Mesh Editor tools that looked covered but failed at runtime, each driven
through the real server and bridge against a real host session behind the editor's own
protocol code (the stand-in helper turns a ``cdmw_command`` into the request its button sends)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from cdmw.mcp import approvals  # noqa: F401  (the approvals module is loaded as the app loads it)
from tests.test_mcp_area_tools import app, connect, profile, settings  # noqa: F401  (fixtures)
from tests.test_automation_authoring_commands import editor  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="AI connections are Windows-only")


@pytest.fixture
def answered(editor, connect):  # noqa: F811
    """The stand-in editor whose helper answers every command, with the connection around it."""

    from PySide6.QtCore import QTimer

    from tests.test_mesh_rust_authoring_exact_output import _request

    ui, host = editor.ui, editor.host
    next_id = [30]

    def helper(message):
        # As the helper does: the command comes back as its button's request, numbered in
        # order as the editor's handler records it, and queued for the editor's worker.
        editor.sent.append(dict(message))
        if message.get("event") == "cdmw_command":
            next_id[0] += 1

            def request(request_id=next_id[0], command=message["command"], arguments=message["arguments"]):
                ui.standalone_rust_last_client_request_id = request_id
                ui.standalone_rust_protocol_queue.append({**_request(host, "command_request", request_id),
                                                         "command": command, "arguments": arguments})
                ui._start_next_rust_protocol_worker()

            QTimer.singleShot(0, request)
        return True

    ui._send_rust_message = helper
    ui.standalone_rust_host_edit_commands_supported = True
    ui.standalone_rust_host_output_commands_supported = True
    ui.standalone_rust_host_panel_commands_supported = True
    editor.mcp = connect(editor.window)
    # A call that waits for the editor answers within the call, not as a job to follow.
    editor.mcp.controller.server.quick_result_s = 60.0
    yield editor


def _select_part_vertices(editor, part: int = 0, count: int = 3) -> None:
    mcp = editor.mcp
    selected = mcp.ok("mesh_select", {"vertices": {str(part): list(range(count))}})
    assert selected["done"], selected
    assert selected["selection"]["vertices"] == count


# ----- 1. Vertex Parameters ---------------------------------------------------------------
def test_vertex_inspect_reads_the_selection_and_its_token_edits_it(answered) -> None:
    editor, mcp = answered, answered.mcp
    service, session_id = editor.host.shadow_service, editor.host.shadow_session_id
    empty = mcp.ok("mesh_vertex_inspect")
    assert empty["count"] == 0 and empty["rows"] == [] and "select" in empty["message"]

    _select_part_vertices(editor, count=3)
    page = mcp.ok("mesh_vertex_inspect")
    part = service.working_mesh(session_id).submeshes[0]
    assert page["count"] == 3 and page["pages"] == 1 and page["page_size"] == 128
    row = page["rows"][0]
    assert (row["part"], row["vertex"]) == (0, 0)
    assert row["position"] == pytest.approx(list(part.vertices[0]))
    assert row["uv0"] == pytest.approx(list(part.uvs[0]))
    assert set(row) >= {"normal", "tangent", "weights", "cloth", "source", "part_name"}
    assert row["weights"]["influences"] and {"slot", "bone", "name", "weight"} <= set(row["weights"]["influences"][0])
    capabilities = page["capabilities"]
    assert set(capabilities) >= {"position", "uv0", "normal", "tangent", "weights", "cloth", "uv1", "colours"}
    assert all("reason" in value and "editable" in value for value in capabilities.values())
    token = page["token"]
    assert set(token) == {"session_id", "mesh_revision", "selection_revision", "topology_generation"}
    # Paged as the inspector pages: one vertex a page here.
    second = mcp.ok("mesh_vertex_inspect", {"page": 1, "page_size": 1})
    assert second["pages"] == 3 and [r["vertex"] for r in second["rows"]] == [1]
    assert mcp.error("mesh_vertex_inspect", {"page_size": 129})["code"] == "invalid_arguments"

    # The token as it came back: the edit is one History step through the inspector's own Apply.
    assert capabilities["position"]["editable"], capabilities["position"]
    before = part.vertices[1][2]
    edited = mcp.ok("mesh_vertex_edit", {"token": token, "edits": {"position": {"mode": "offset",
                                                                                "values": [None, None, 0.25]}}})
    assert edited["done"], edited
    assert edited["history"]["undo"] == edited["history_before"]["undo"] + 1
    after = service.working_mesh(session_id).submeshes[0]
    assert after.vertices[1][2] == pytest.approx(before + 0.25)
    # A text token, or one from before the edit, is refused.
    assert mcp.error("mesh_vertex_edit", {"token": "abc", "edits": {"position": {"values": [0, 0, 0]}}})[
        "code"] == "invalid_arguments"
    stale = mcp.ok("mesh_vertex_edit", {"token": token, "edits": {"position": {"values": [None, None, 0.0]}}})
    assert stale["history"]["undo"] == stale["history_before"]["undo"]
    assert service.working_mesh(session_id).submeshes[0].vertices[1][2] == pytest.approx(before + 0.25)


# ----- 3. Layers: Copy ------------------------------------------------------------------
def test_a_layer_copy_sent_by_name_copies_the_current_selection(answered) -> None:
    editor, mcp = answered, answered.mcp
    service, session_id = editor.host.shadow_service, editor.host.shadow_session_id
    faces = len(service.working_mesh(session_id).submeshes[0].faces)
    assert mcp.ok("mesh_select", {"faces": {"0": list(range(faces))}})["done"]
    copied = mcp.ok("mesh_layers", {"action": "copy"})
    assert copied["done"], copied
    # The copy carried no selection: the session's own was copied, not an empty one.
    sent = [m for m in editor.sent if m.get("event") == "cdmw_command"][-1]
    assert (sent["command"], sent["arguments"]) == ("layer_copy", {})
    assert service._session(session_id).native_clipboard_ready, copied["status"]
