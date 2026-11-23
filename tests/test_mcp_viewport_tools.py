"""The Mesh Editor's view by numbers (mesh_islands and the other editor_control tools)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cdmw.mcp.errors import ToolError


class _Call:
    def __init__(self, arguments):
        self.context = SimpleNamespace(ui_call=lambda function: function())
        self.arguments = arguments

    def check_cancelled(self):
        return None


class _Tab:
    """A document whose helper answers controls by name, as cdmw_host_controls.rs does."""

    def __init__(self, controls=("hair", "islands"), answer=None):
        self.standalone_rust_ready = True
        self.standalone_rust_authoring_session = object()
        self.standalone_rust_editor_controls = frozenset(controls)
        self.standalone_rust_editor_control_answers = {}
        self.sent = []
        self.answer = answer or (lambda control, arguments: (True, "", {"parts": []}))

    def send_editor_control(self, control, arguments):
        from cdmw.ui.mesh_editor.editor_controls import keep_editor_control_answer

        self.sent.append((control, dict(arguments)))
        ok, message, state = self.answer(control, arguments)
        keep_editor_control_answer(self, {"token": len(self.sent), "control": control, "ok": ok,
                                          "message": message, "state": state})
        return len(self.sent)


@pytest.fixture
def document(monkeypatch):
    from cdmw.mcp import mesh_tools

    box = {"tab": _Tab()}
    monkeypatch.setattr(mesh_tools, "shown_document", lambda context: box["tab"])
    monkeypatch.setattr(mesh_tools, "ready_document", lambda context, **kw: box["tab"])
    return box


def _tool(name):
    from cdmw.mcp.catalogue import typed_tools

    return next(tool for tool in typed_tools() if tool.name == name)


def _run(name, arguments):
    from cdmw.mcp.schema import validate_arguments

    tool = _tool(name)
    return tool.handler(_Call(validate_arguments(arguments, tool.input_schema)))


def test_islands_are_used_by_part_and_number(document):
    outcome = _run("mesh.islands", {"action": "visibility", "part": 1, "island": 2, "visible": False})
    assert outcome == {"done": True, "islands": {"parts": []}}
    assert document["tab"].sent == [("islands", {"action": "visibility", "part": 1, "island": 2, "visible": False})]
    _run("mesh.islands", {"action": "select_many", "islands": [{"part": 0, "island": 0}, {"part": 1, "island": 3}]})
    assert document["tab"].sent[-1][1]["islands"] == [{"part": 0, "island": 0}, {"part": 1, "island": 3}]


def test_islands_report_the_lists_refusal(document):
    document["tab"].answer = lambda control, arguments: (False, "Part 0 has islands 0 to 1.", {"usable": True})
    outcome = _run("mesh.islands", {"action": "select", "part": 0, "island": 9})
    assert outcome["done"] is False and outcome["message"] == "Part 0 has islands 0 to 1."
    assert outcome["islands"] == {"usable": True}


@pytest.mark.parametrize("arguments, problem", [
    ({"action": "select", "part": 0}, "needs island"),
    ({"action": "show_all", "part": 0}, "not part"),
    ({"action": "visibility", "part": 0, "island": 1}, "needs visible"),
    ({"action": "colours"}, "needs enabled"),
])
def test_islands_check_each_actions_arguments_before_sending(document, arguments, problem):
    with pytest.raises(ToolError, match=problem):
        _run("mesh.islands", arguments)
    assert not document["tab"].sent


def test_islands_need_a_helper_that_lists_the_control(document):
    document["tab"] = _Tab(controls=("hair",))
    with pytest.raises(ToolError, match="host_editor_controls_v1"):
        _run("mesh.islands", {"action": "state"})
    tool = _tool("mesh.islands")
    assert tool.effect_of(_Call({"action": "state"})) == "read"
    assert tool.effect_of(_Call({"action": "isolate"})) == "edit"


def test_an_unanswered_control_fails_instead_of_waiting_forever(document, monkeypatch):
    from cdmw.mcp import editor_control

    class Silent(_Tab):
        def send_editor_control(self, control, arguments):
            return 5

    document["tab"] = Silent()
    monkeypatch.setattr(editor_control, "ANSWER_S", 0.05)
    with pytest.raises(ToolError, match="did not answer"):
        _run("mesh.islands", {"action": "state"})
