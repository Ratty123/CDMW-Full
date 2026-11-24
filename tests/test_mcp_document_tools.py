"""The Mesh Editor's documents by numbers (mesh_open_file, mesh_open_piece, mesh_close_document,
mesh_switch_piece, mesh_history_jump, mesh_reference_pieces)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cdmw.mcp.errors import ToolError


class _Call:
    def __init__(self, arguments, window=None):
        self.context = SimpleNamespace(ui_call=lambda function: function(), window=window)
        self.arguments = arguments

    def check_cancelled(self):
        return None


class _Signal:
    def __init__(self):
        self.emitted = []

    def emit(self, *args):
        self.emitted.append(args)


class _Document:
    def __init__(self, name, pending=False):
        self.name, self.pending = name, pending
        self.opened, self.closed_session, self.discarded = [], False, False
        self.standalone_status_label = SimpleNamespace(text=lambda: "Mesh Editor cannot open: no helper.")

    def open_mesh_file_session_async(self, path):
        self.opened.append(path)
        return 7 if self.name != "broken" else None

    def close_standalone_session(self):
        self.closed_session = True
        self.pending = False
        return True


class _View:
    def __init__(self, documents):
        self._documents = list(documents)
        self.active = self._documents[0]
        self.closed = []

    @property
    def documents(self):
        return tuple(self._documents)

    def open_new_document(self):
        document = _Document("new")
        self._documents.append(document)
        self.active = document
        return document

    def close_document(self, index):
        self.closed.append(index)
        self._documents.pop(index)
        return True


@pytest.fixture
def editor(monkeypatch):
    from cdmw.mcp import mesh_tools
    from cdmw.ui.mesh_editor.live_edit import end_edit_prompt

    box = {"view": _View([_Document("shown")])}
    monkeypatch.setattr(mesh_tools, "_view", lambda context: box["view"])
    monkeypatch.setattr(mesh_tools, "_act", lambda call, function, answers=None: function())
    monkeypatch.setattr(end_edit_prompt, "has_pending_edit", lambda document: bool(getattr(document, "pending", False)))
    monkeypatch.setattr(end_edit_prompt, "mark_discarded", lambda document: setattr(document, "discarded", True))
    monkeypatch.setattr("cdmw.ui.mesh_editor.documents.document_label", lambda document: document.name)
    return box


def _run(name, arguments, window=None):
    from cdmw.mcp.catalogue import typed_tools
    from cdmw.mcp.schema import validate_arguments

    tool = next(tool for tool in typed_tools() if tool.name == name)
    return tool.handler(_Call(validate_arguments(arguments, tool.input_schema), window))


def test_a_file_opens_in_the_shown_document_or_beside_an_unfinished_edit(editor, tmp_path):
    mesh = tmp_path / "sword.pac"
    mesh.write_bytes(b"PAR ")
    outcome = _run("mesh.open_file", {"path": str(mesh)})
    assert outcome["opening"] is True and editor["view"].documents[0].opened == [mesh]
    editor["view"].documents[0].pending = True
    _run("mesh.open_file", {"path": str(mesh)})
    assert [document.name for document in editor["view"].documents] == ["shown", "new"]
    assert editor["view"].documents[1].opened == [mesh] and len(editor["view"].documents[0].opened) == 1


@pytest.mark.parametrize("name", ["sword.txt", "missing.pac"])
def test_a_file_that_cannot_be_opened_is_refused_first(editor, tmp_path, name):
    (tmp_path / "sword.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ToolError, match="full path of an existing"):
        _run("mesh.open_file", {"path": str(tmp_path / name)})
    with pytest.raises(ToolError, match="full path"):
        _run("mesh.open_file", {"path": "sword.pac"})


def test_the_documents_own_reason_comes_back_when_it_does_not_open(editor, tmp_path):
    editor["view"] = _View([_Document("broken")])
    mesh = tmp_path / "sword.obj"
    mesh.write_text("o x\n", encoding="utf-8")
    with pytest.raises(ToolError, match="no helper"):
        _run("mesh.open_file", {"path": str(mesh)})


def test_a_document_with_an_unfinished_edit_closes_only_when_its_edit_is_discarded(editor):
    view = editor["view"] = _View([_Document("first"), _Document("edited", pending=True), _Document("third")])
    with pytest.raises(ToolError, match="unfinished edit"):
        _run("mesh.close_document", {"index": 1})
    assert view.closed == []
    outcome = _run("mesh.close_document", {"index": 1, "discard_edit": True})
    edited = outcome  # the closed document is gone from the view
    assert edited["closed"] == 1 and edited["discarded"] is True and edited["documents"] == 2
    assert view.closed == [1]
    with pytest.raises(ToolError, match="2 open documents"):
        _run("mesh.close_document", {"index": 5})
    from cdmw.mcp.catalogue import typed_tools

    tool = next(tool for tool in typed_tools() if tool.name == "mesh.close_document")
    assert tool.effect_of(_Call({"index": 0})) == "edit"
    assert tool.effect_of(_Call({"index": 0, "discard_edit": True})) == "destructive"


def test_a_closed_unfinished_edit_is_discarded_as_the_close_question_does(editor):
    edited = _Document("edited", pending=True)
    editor["view"] = _View([edited, _Document("other")])
    _run("mesh.close_document", {"index": 0, "discard_edit": True})
    assert edited.discarded and edited.closed_session


def _piece_tab(monkeypatch, pieces=3):
    from cdmw.mcp import mesh_tools

    contexts = tuple(SimpleNamespace(selected_entry=SimpleNamespace(path=f"character/model/piece_{i}.pac"))
                     for i in range(pieces))
    tab = SimpleNamespace(item_set_contexts=contexts, switch_item_piece_requested=_Signal(),
                          standalone_rust_protocol_thread=None, standalone_rust_protocol_queue=[])
    monkeypatch.setattr(mesh_tools, "ready_document", lambda context, **kw: tab)
    monkeypatch.setattr(mesh_tools, "_act", lambda call, function, answers=None: function())
    return tab


def test_switch_piece_asks_for_another_piece_of_the_set(monkeypatch):
    tab = _piece_tab(monkeypatch)
    outcome = _run("mesh.switch_piece", {"piece": 2})
    assert tab.switch_item_piece_requested.emitted == [(2,)]
    assert outcome["switching_to"] == "character/model/piece_2.pac"
    with pytest.raises(ToolError, match="1 to 2"):
        _run("mesh.switch_piece", {"piece": 3})
    tab.standalone_rust_protocol_queue.append({"event": "command_request"})
    with pytest.raises(ToolError, match="working on the last request"):
        _run("mesh.switch_piece", {"piece": 1})
    single = _piece_tab(monkeypatch, pieces=1)
    with pytest.raises(ToolError, match="not one piece of a set"):
        _run("mesh.switch_piece", {"piece": 1})
    assert not single.switch_item_piece_requested.emitted


def test_open_piece_clears_the_set_scope_then_opens_the_file(monkeypatch):
    from cdmw.mcp import mesh_tools

    clicks = []
    button = SimpleNamespace(isEnabled=lambda: True, click=lambda: clicks.append(True))
    archive = SimpleNamespace(archive_remote_bridge=SimpleNamespace(item_set_members=("a", "b")),
                              archive_clear_asset_scope_button=button)
    opened = []
    monkeypatch.setattr(mesh_tools, "_act", lambda call, function, answers=None: function())
    monkeypatch.setattr(mesh_tools, "_open", lambda call: opened.append(dict(call.arguments)) or {"opening": True})
    outcome = _run("mesh.open_piece", {"path": "character/model/piece_1.pac"},
                   window=SimpleNamespace(archive=archive))
    assert clicks == [True] and opened == [{"path": "character/model/piece_1.pac"}]
    assert outcome == {"opening": True, "cleared_scope": True}
    archive.archive_remote_bridge.item_set_members = ()
    assert _run("mesh.open_piece", {"path": "character/model/x.pac"},
                window=SimpleNamespace(archive=archive))["cleared_scope"] is False
    assert clicks == [True]


class _ControlTab:
    def __init__(self, answers):
        self.standalone_rust_ready = True
        self.standalone_rust_authoring_session = object()
        self.standalone_rust_editor_controls = frozenset({"document"})
        self.standalone_rust_editor_control_answers = {}
        self.answers, self.sent = list(answers), []

    def send_editor_control(self, control, arguments):
        from cdmw.ui.mesh_editor.editor_controls import keep_editor_control_answer

        self.sent.append(dict(arguments))
        ok, message, state = self.answers.pop(0)
        keep_editor_control_answer(self, {"token": len(self.sent), "ok": ok, "message": message, "state": state})
        return len(self.sent)


def _control_tab(monkeypatch, answers):
    from cdmw.mcp import mesh_edit_tools, mesh_tools

    tab = _ControlTab(answers)
    monkeypatch.setattr(mesh_tools, "shown_document", lambda context: tab)
    monkeypatch.setattr(mesh_tools, "ready_document", lambda context, **kw: tab)
    history = iter(({"cursor": 3}, {"cursor": 1}))
    monkeypatch.setattr(mesh_edit_tools, "history_now", lambda call: next(history))
    return tab


def test_history_jump_waits_until_the_traversal_has_arrived(monkeypatch):
    traversing = {"history": {"traversing": True}}
    tab = _control_tab(monkeypatch, [(True, "", traversing), (True, "", traversing),
                                     (True, "", {"history": {"traversing": False, "cursor": 1}})])
    outcome = _run("mesh.history_jump", {"cursor": 1})
    assert outcome["done"] is True and outcome["history_before"] == {"cursor": 3}
    assert outcome["history"] == {"cursor": 1} and outcome["document"]["history"]["cursor"] == 1
    assert tab.sent == [{"action": "history_cursor", "cursor": 1}, {"action": "state"}, {"action": "state"}]


def test_reference_pieces_read_or_change_one_piece(monkeypatch):
    tab = _control_tab(monkeypatch, [(True, "", {"reference_pieces": []}),
                                     (False, "This document has no reference piece 4; the state lists them.", {})])
    assert _run("mesh.reference_pieces", {})["document"] == {"reference_pieces": []}
    refused = _run("mesh.reference_pieces", {"piece": 4, "visible": False})
    assert refused["done"] is False and "no reference piece 4" in refused["message"]
    assert tab.sent == [{"action": "state"}, {"action": "reference_piece", "piece": 4, "visible": False}]
    with pytest.raises(ToolError, match="together"):
        _run("mesh.reference_pieces", {"piece": 1})
