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


def test_overlays_send_only_what_the_action_takes(document):
    document["tab"] = _Tab(controls=("overlays",))
    outcome = _run("mesh.overlays", {"action": "set", "deformation_heatmap": True})
    assert outcome == {"done": True, "overlays": {"parts": []}}
    _run("mesh.overlays", {"action": "inspection", "light": "behind", "light_strength": 1.2})
    _run("mesh.overlays", {"action": "frame_bone"})
    assert document["tab"].sent == [
        ("overlays", {"action": "set", "deformation_heatmap": True}),
        ("overlays", {"action": "inspection", "light": "behind", "light_strength": 1.2}),
        ("overlays", {"action": "frame_bone"}),
    ]
    with pytest.raises(ToolError, match="needs one of"):
        _run("mesh.overlays", {"action": "set"})
    with pytest.raises(ToolError, match="not light"):
        _run("mesh.overlays", {"action": "set", "light": "front"})


# ----- view_capture through the helper's own render -----------------------------------------------
#: Windows' extended-length prefix, which the helper's canonical paths carry.
EXTENDED = "\\\\?\\"


class _CaptureTab(_Tab):
    def __init__(self, root, write_to=None, ok=True):
        super().__init__(controls=("capture",))
        self.standalone_rust_session_root = root
        self.write_to, self.ok = write_to, ok

    def send_editor_control(self, control, arguments):
        from PySide6.QtGui import QColor, QImage

        from cdmw.ui.mesh_editor.editor_controls import keep_editor_control_answer

        self.sent.append((control, dict(arguments)))
        path = self.write_to or (self.standalone_rust_session_root / "captures" / "view-1.png")
        path.parent.mkdir(parents=True, exist_ok=True)
        image = QImage(64, 36, QImage.Format.Format_RGB32)
        image.fill(QColor(30, 140, 60))
        image.save(str(path))
        keep_editor_control_answer(self, {"token": len(self.sent), "ok": self.ok,
                                          "message": "" if self.ok else "The 3D view has no renderer.",
                                          "state": {"path": EXTENDED + str(path), "width": 64, "height": 36}})
        return len(self.sent)


def _picture(tab, max_side=256):
    from cdmw.mcp.view_tools import _helper_picture

    facts = {"view": "mesh_editor"}
    return _helper_picture(_Call({}), max_side, facts), facts


def test_the_mesh_editor_view_is_drawn_by_its_renderer_and_the_file_removed(document, tmp_path):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    tab = document["tab"] = _CaptureTab(tmp_path)
    result, _facts = _picture(tab, 128)
    assert result is not None
    assert tab.sent == [("capture", {"max_side": 128})]
    assert not (tmp_path / "captures" / "view-1.png").exists()


def test_a_picture_outside_the_session_folder_is_refused_and_a_refusal_falls_back(document, tmp_path):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    outside = tmp_path / "elsewhere" / "view.png"
    document["tab"] = _CaptureTab(tmp_path / "session", write_to=outside)
    (tmp_path / "session").mkdir()
    with pytest.raises(ToolError, match="outside its session folder"):
        _picture(document["tab"])
    assert outside.exists()  # not ours to remove
    document["tab"] = _CaptureTab(tmp_path / "session", ok=False)
    result, facts = _picture(document["tab"])
    assert result is None and facts["helper_capture"] == "The 3D view has no renderer."
    document["tab"] = _Tab(controls=("hair",))
    assert _picture(document["tab"])[0] is None  # an older helper: the window's own picture next
