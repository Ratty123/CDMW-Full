"""Hair Tools by numbers (mesh_hair, mesh_hair_setup) and the choosers they answer.

The panel's commands an AI connection sends must not open a chooser: Apply edited DDS…
takes the file the command carries, Change references… the head and body CDMW found, and
Import custom hair mesh… the mesh file. These run the real protocol worker, with every
chooser patched to fail the test if it opens.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from cdmw.mcp.errors import ToolError
from tests.test_mesh_hair_authoring import TEXTURE, _fixtures, dds, editor  # noqa: F401


def _no_chooser(*_args, **_kwargs):
    raise AssertionError("a chooser opened")


def _run(tab, request):
    from PySide6.QtWidgets import QApplication

    tab.standalone_rust_protocol_queue.append(request)
    tab._start_next_rust_protocol_worker()
    deadline = time.monotonic() + 30
    while tab.standalone_rust_protocol_thread is not None and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.005)
    assert tab.standalone_rust_protocol_thread is None, "the command never returned"


def _editor_tab(editor, tmp_path, monkeypatch):  # noqa: F811
    from tests.test_mesh_rust_editor_selection import _tab

    _, session = editor
    tab = _tab(tmp_path)
    tab.standalone_rust_authoring_session = session
    tab.standalone_rust_process_generation = session.process_generation
    responses = []
    monkeypatch.setattr(tab, "_send_rust_message", lambda message: responses.append(message) or True)
    return tab, session, responses


@pytest.mark.parametrize("given", ["file", "relative", "missing"])
def test_apply_edited_dds_takes_the_file_the_command_carries_without_a_chooser(
        editor, tmp_path, monkeypatch, given):  # noqa: F811
    from PySide6.QtWidgets import QFileDialog
    from tests.test_mesh_rust_editor_selection import _dispose

    tab, session, responses = _editor_tab(editor, tmp_path, monkeypatch)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", _no_chooser)
    edited = tmp_path / "edited.dds"
    edited.write_bytes(dds())
    path = {"file": str(edited), "relative": "edited.dds", "missing": str(tmp_path / "gone.dds")}[given]
    try:
        request = _fixtures._request(session, "command_request", 1)
        request.update(command="hair_texture", arguments={"texture_path": TEXTURE, "dds_path": path})
        _run(tab, request)
        result = next(message for message in responses if message["event"] == "command_result")
        if given == "file":
            # The file was read and checked against the template DDS; this fixture's material has
            # no preview binding, so the commit after it refuses. No chooser was asked.
            assert result["ok"] is True or "preview binding" in result["error"], result
        else:
            assert result["ok"] is False and "existing .dds" in result["error"], result
            assert result["payload"].get("state")  # the session stays open
    finally:
        tab.standalone_rust_authoring_session = None
        _dispose(tab)


def test_the_buttons_own_apply_edited_dds_still_asks(editor, tmp_path, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QFileDialog
    from tests.test_mesh_rust_editor_selection import _dispose

    tab, session, responses = _editor_tab(editor, tmp_path, monkeypatch)
    asked = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: asked.append(a) or ("", ""))
    try:
        request = _fixtures._request(session, "command_request", 1)
        request.update(command="hair_texture", arguments={"texture_path": TEXTURE})
        _run(tab, request)
        result = next(message for message in responses if message["event"] == "command_result")
        assert asked and result["error"] == "DDS selection cancelled."
    finally:
        tab.standalone_rust_authoring_session = None
        _dispose(tab)


def _reference_tab(monkeypatch):
    from cdmw.ui.mesh_editor import hair_flow

    target = SimpleNamespace(identity="hair", path="character/model/hair.pac")
    service = SimpleNamespace(current_session=object())
    owner = SimpleNamespace(archive=SimpleNamespace(archive_catalogue_service=service))
    tab = SimpleNamespace(window=lambda: owner, _current_target_entry=lambda: target,
                          archive_session_dependencies="target-files", standalone_rust_closing=False)
    session = SimpleNamespace(shadow_session_id="s", shadow_service=SimpleNamespace(
        _session=lambda _sid: SimpleNamespace(hair_state=None)))
    tab.standalone_rust_authoring_session = session
    monkeypatch.setattr("cdmw.ui.mesh_editor.hair_reference_picker.HairReferencePickerDialog", _no_chooser)
    return hair_flow, tab, session


def test_change_references_takes_the_head_and_body_offered_for_its_token(monkeypatch):
    hair_flow, tab, session = _reference_tab(monkeypatch)
    token = hair_flow.offer_hair_references(tab, ("head-entry", "head-files"), ("body-entry", "body-files"))
    event = {"command": "hair_begin", "arguments": {"change_references": True, hair_flow.HAIR_REFERENCES_KEY: token}}
    prepared = hair_flow.prepare_hair_event(tab, session, event)["arguments"]
    assert (prepared["_archive_entry"], prepared["_archive_dependencies"]) == ("head-entry", "head-files")
    assert (prepared["_body_archive_entry"], prepared["_body_archive_dependencies"]) == ("body-entry", "body-files")
    assert hair_flow.HAIR_REFERENCES_KEY not in prepared
    # Each offer answers one command: the same token again (or a stranger's) asks nobody and refuses.
    with pytest.raises(ValueError, match="no longer waiting"):
        hair_flow.prepare_hair_event(tab, session, event)


def test_change_references_without_a_token_still_opens_the_choosers(monkeypatch):
    hair_flow, tab, session = _reference_tab(monkeypatch)
    hair_flow.offer_hair_references(tab, ("h", "hf"), ("b", "bf"))
    with pytest.raises(AssertionError, match="a chooser opened"):
        hair_flow.prepare_hair_event(tab, session, {"command": "hair_begin",
                                                    "arguments": {"change_references": True}})


@pytest.mark.parametrize("suffix, problem", [(".obj", ""), (".fbx", "Blender"), (".txt", "existing OBJ")])
def test_import_custom_hair_mesh_takes_the_file_the_command_carries(tmp_path, monkeypatch, suffix, problem):
    from PySide6.QtWidgets import QFileDialog
    from cdmw.ui.mesh_editor import replacement_flow

    monkeypatch.setattr(QFileDialog, "getOpenFileName", _no_chooser)
    mesh = tmp_path / f"hair{suffix}"
    mesh.write_text("o hair\n", encoding="utf-8")
    target = SimpleNamespace(identity="hair")
    tab = SimpleNamespace(_current_target_entry=lambda: target, standalone_rust_closing=False,
                          window=lambda: None, archive_session_dependencies="files")
    session = SimpleNamespace(shadow_session_id="s", shadow_service=SimpleNamespace(
        _session=lambda _sid: SimpleNamespace(replacement_state=object())))
    tab.standalone_rust_authoring_session = session
    event = {"command": "hair_import_custom", "arguments": {"source_path": str(mesh)}}
    if problem:
        with pytest.raises(ValueError, match=problem):
            replacement_flow.prepare_replacement_event(tab, session, event)
    else:
        assert replacement_flow.prepare_replacement_event(tab, session, event)["arguments"]["source_path"] == str(mesh)


# ----- the editor_control round trip on a real document --------------------------------------
def test_a_document_sends_editor_controls_its_helper_lists_and_keeps_answers_by_token(tmp_path, monkeypatch):
    from cdmw.ui.mesh_editor.editor_controls import ANSWERS_KEPT, take_editor_control_answer
    from tests.test_mesh_rust_editor_selection import _dispose, _tab

    tab = _tab(tmp_path)
    sent = []
    monkeypatch.setattr(tab, "_send_rust_message", lambda message: sent.append(message) or True)
    try:
        tab.standalone_rust_ready = True
        assert tab.send_editor_control("hair", {"action": "state"}) == 0  # an older helper lists none
        tab.standalone_rust_editor_controls = frozenset({"hair"})
        token = tab.send_editor_control("hair", {"action": "state"})
        assert token and sent[-1]["event"] == "editor_control"
        assert sent[-1]["control"] == "hair" and sent[-1]["token"] == token
        assert sent[-1]["arguments"] == {"action": "state"}
        assert tab.send_editor_control("islands", {}) == 0
        payload = tab._rust_host_message("editor_control", request_id=0, extra={
            "token": token, "control": "hair", "ok": False, "message": "Open Hair first", "state": {"active": False}})
        payload["event"] = "editor_control"
        tab.standalone_rust_authoring_session = SimpleNamespace(
            session_id=payload["session_id"], process_generation=payload["process_generation"])
        monkeypatch.setattr(tab, "_validate_rust_event_identity", lambda value: "editor_control")
        tab._handle_rust_protocol_event(payload)
        answer = take_editor_control_answer(tab, token)
        assert answer == {"control": "hair", "ok": False, "message": "Open Hair first", "state": {"active": False}}
        assert take_editor_control_answer(tab, token) is None
        for extra in range(ANSWERS_KEPT + 4):
            tab._handle_rust_protocol_event({**payload, "token": 1000 + extra})
        assert len(tab.standalone_rust_editor_control_answers) == ANSWERS_KEPT
    finally:
        tab.standalone_rust_authoring_session = None
        _dispose(tab)


# ----- the tool -----------------------------------------------------------------------------
class _Call:
    def __init__(self, context, arguments):
        self.context, self.arguments = context, arguments

    def check_cancelled(self):
        return None


class _HelperTab:
    """A document whose helper answers hair controls as cdmw_hair_host.rs does."""

    def __init__(self, preparing_polls=2):
        self.standalone_rust_ready = True
        self.standalone_rust_authoring_session = object()
        self.standalone_rust_editor_controls = frozenset({"hair"})
        self.standalone_rust_editor_control_answers = {}
        self.standalone_rust_host_panel_commands_supported = True
        self.sent = []
        self._preparing = preparing_polls

    def send_editor_control(self, control, arguments):
        from cdmw.ui.mesh_editor.editor_controls import keep_editor_control_answer

        self.sent.append(dict(arguments))
        token = len(self.sent)
        action = arguments["action"]
        if action == "settings":  # prepared in the background, then saved
            preparing = True
        elif action == "state" and self._preparing > 0:
            self._preparing -= 1
            preparing = self._preparing > 0
        else:
            preparing = False
        ok = action != "rigid"
        keep_editor_control_answer(self, {"token": token, "control": control, "ok": ok,
                                          "message": "" if ok else "Select the scalp sections to attach rigidly",
                                          "state": {"active": True, "preparing": preparing, "busy": False}})
        return token


@pytest.fixture
def helper(monkeypatch):
    from cdmw.mcp import mesh_edit_tools, mesh_tools

    tab = _HelperTab()
    monkeypatch.setattr(mesh_tools, "shown_document", lambda context: tab)
    monkeypatch.setattr(mesh_tools, "ready_document", lambda context, **kw: tab)
    history = iter(range(100))
    monkeypatch.setattr(mesh_edit_tools, "history_now", lambda call: {"undo": next(history)})
    return tab


def _hair_tool():
    from cdmw.mcp.mesh_hair_tools import mesh_hair_tools

    return {tool.name: tool for tool in mesh_hair_tools()}


def _call(arguments):
    from cdmw.mcp.schema import validate_arguments

    tool = _hair_tool()["mesh.hair"]
    return _Call(SimpleNamespace(ui_call=lambda function: function()), validate_arguments(arguments, tool.input_schema))


def test_mesh_hair_edits_wait_until_prepared_and_return_the_history(helper):
    tool = _hair_tool()["mesh.hair"]
    outcome = tool.handler(_call({"action": "settings", "lock_ids": [3], "width": 0.02, "density": 4}))
    assert outcome["done"] is True and outcome["waited"] is True
    assert outcome["hair"]["preparing"] is False
    assert helper.sent[0] == {"action": "settings", "lock_ids": [3], "width": 0.02, "density": 4}
    assert all(message == {"action": "state"} for message in helper.sent[1:])
    assert outcome["history_before"] != outcome["history"]


def test_mesh_hair_reports_the_panels_refusal_and_reads_without_history(helper):
    tool = _hair_tool()["mesh.hair"]
    refused = tool.handler(_call({"action": "rigid"}))
    assert refused["done"] is False and "scalp sections" in refused["message"]
    read = tool.handler(_call({"action": "state"}))
    assert read["done"] is True and "history" not in read
    assert tool.effect_of(_call({"action": "state"})) == "read"
    assert tool.effect_of(_call({"action": "empty"})) == "edit"


@pytest.mark.parametrize("arguments, problem", [
    ({"action": "fill"}, "needs preset"),
    ({"action": "empty", "width": 0.2}, "not width"),
    ({"action": "texture", "texture_path": TEXTURE}, "needs dds_path"),
    ({"action": "begin", "head": "character/model/head.pac"}, "needs body"),
])
def test_mesh_hair_checks_each_actions_own_arguments(helper, arguments, problem):
    with pytest.raises(ToolError, match=problem):
        _hair_tool()["mesh.hair"].handler(_call(arguments))
    assert not helper.sent


def test_mesh_hair_refuses_panel_edits_on_an_older_helper(helper):
    helper.standalone_rust_editor_controls = frozenset()
    with pytest.raises(ToolError, match="host_editor_controls_v1"):
        _hair_tool()["mesh.hair"].handler(_call({"action": "empty"}))
    with pytest.raises(ToolError, match="host_editor_controls_v1"):
        _hair_tool()["mesh.hair"].handler(_call({"action": "import_custom", "path": "C:/x/hair.obj"}))


def test_mesh_hair_sends_texture_and_import_with_the_files_their_choosers_would_give(helper, monkeypatch, tmp_path):
    from cdmw.mcp import mesh_edit_tools

    sent = []
    monkeypatch.setattr(mesh_edit_tools, "_send_edit", lambda call, command, arguments: sent.append(
        (command, arguments)) or {"done": True})
    monkeypatch.setattr(mesh_edit_tools, "_send_output", lambda call, command, arguments: sent.append(
        (command, arguments)) or {"done": True})
    edited, mesh = tmp_path / "edited.dds", tmp_path / "hair.glb"
    edited.write_bytes(dds())
    mesh.write_bytes(b"glTF")
    tool = _hair_tool()["mesh.hair"]
    tool.handler(_call({"action": "texture", "texture_path": TEXTURE, "dds_path": str(edited)}))
    tool.handler(_call({"action": "import_custom", "path": str(mesh)}))
    tool.handler(_call({"action": "color", "color": [0.2, 0.1, 0.05]}))
    assert sent == [("hair_texture", {"texture_path": TEXTURE, "dds_path": str(edited)}),
                    ("hair_import_custom", {"source_path": str(mesh)}),
                    ("hair_color", {"color": [0.2, 0.1, 0.05]})]
    with pytest.raises(ToolError, match="Blender"):
        fbx = tmp_path / "hair.fbx"
        fbx.write_bytes(b"x")
        tool.handler(_call({"action": "import_custom", "path": str(fbx)}))


# ----- the setup ------------------------------------------------------------------------------
class _Signal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *args):
        for slot in self._slots:
            slot(*args)


class _Check:
    def __init__(self, checked=False):
        self.checked = checked

    def setChecked(self, value):
        self.checked = bool(value)

    def isChecked(self):
        return self.checked


class _Button:
    def __init__(self):
        self.enabled = False

    def isEnabled(self):
        return self.enabled


class _Label:
    def __init__(self, text=""):
        self._text = text

    def text(self):
        return self._text


class _SetupDialog:
    def __init__(self, ready_after, mode):
        self.finished = _Signal()
        self.keep_scalp_cap, self.choose_donor_material = _Check(True), _Check(False)
        self.waiting_start = _Button()
        self.status = _Label("Loading the mounted character and hairstyle catalogue…")
        self.polls, self.ready_after, self.mode = 0, ready_after, mode
        self.started = False
        self._picker = SimpleNamespace(_closed=False, _rows={}, _verified=set(), choose=_Button(),
                                       status=_Label(""), _key=lambda: None, _choose=self._choose)

    def _choose(self):
        self.started = True
        self.finished.emit(1)

    def _start(self):
        self._choose()

    def reject(self):
        self.finished.emit(0)

    def tick(self):
        self.polls += 1
        if self.polls >= self.ready_after:
            self.waiting_start.enabled = True
            if self.mode == "existing":
                row = SimpleNamespace(path="character/model/1_pc/3_phw/hair/cd_phw_hair_0004.pac")
                self._picker._rows = {"k": row}
                self._picker._verified = {"k"}
                self._picker._key = lambda: "k"
                self._picker.choose.enabled = True


@pytest.fixture
def setup(monkeypatch):
    from cdmw.mcp import mesh_hair_tools
    from cdmw.ui.mesh_editor import hair_flow

    box = {}

    def start(tab, mode, preset="empty", *, character=None, target_path=""):
        dialog = _SetupDialog(ready_after=3, mode=mode)
        box.update(dialog=dialog, mode=mode, character=character, target=target_path)
        return dialog

    monkeypatch.setattr(hair_flow, "start_hair_workflow", start)
    monkeypatch.setattr(mesh_hair_tools, "_setup_document", lambda context: object())
    monkeypatch.setattr("cdmw.mcp.mesh_tools._act", lambda call, function, answers=None: function())
    original = mesh_hair_tools.time.sleep
    monkeypatch.setattr(mesh_hair_tools.time, "sleep", lambda s: (box["dialog"].tick() if "dialog" in box else None,
                                                                  original(0))[1])
    return box


def _setup_call(arguments):
    from cdmw.mcp.schema import validate_arguments

    tool = _hair_tool()["mesh.hair_setup"]
    return tool, _Call(SimpleNamespace(ui_call=lambda function: function()),
                       validate_arguments(arguments, tool.input_schema))


def test_setup_creates_a_hairstyle_once_start_is_offered(setup):
    tool, call = _setup_call({"character": "Damiane", "keep_scalp_cap": False})
    outcome = tool.handler(call)
    assert outcome["started"] is True and outcome["character"] == "Damiane"
    assert setup["mode"] == "generated" and setup["dialog"].started
    assert setup["dialog"].keep_scalp_cap.isChecked() is False


def test_setup_edits_the_named_hairstyle_once_the_chooser_has_checked_it(setup):
    donor = "character/model/1_pc/3_phw/hair/cd_phw_hair_0004.pac"
    tool, call = _setup_call({"character": "Damiane", "mode": "edit", "donor": donor})
    outcome = tool.handler(call)
    assert outcome["started"] is True and setup["mode"] == "existing" and setup["target"] == donor


def test_setup_needs_a_donor_to_edit_and_gives_up_with_its_status(setup, monkeypatch):
    from cdmw.mcp import mesh_hair_tools

    tool, call = _setup_call({"character": "Kliff", "mode": "edit"})
    with pytest.raises(ToolError, match="donor"):
        tool.handler(call)
    monkeypatch.setattr(mesh_hair_tools, "SETUP_S", 0.0)
    tool, call = _setup_call({"character": "Kliff", "mode": "edit", "donor": "character/model/other.pac"})
    with pytest.raises(ToolError, match="did not start in time"):
        tool.handler(call)


# ----- finding the head and body without the choosers -------------------------------------------
HEAD = "character/model/1_pc/2_phw/head/head/cd_phw_00_head_0001.pac"
BODY = "character/model/1_pc/2_phw/nude/phw_00_nude_0001.pac"


@pytest.fixture
def resolver(monkeypatch):
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication
    from cdmw.ui.mesh_editor import hair_reference_resolution as module

    QApplication.instance() or QApplication([])

    class Service(QObject):
        result_ready = Signal(object, object, object)
        request_failed = Signal(object, object)

        def __init__(self):
            super().__init__()
            self.current_session = SimpleNamespace(session_id="catalogue")
            self.asked, self.cancelled = [], []

        def get_character_catalog_detail(self, request, ui_generation=0):
            self.asked.append(request.key)
            return f"request-{len(self.asked)}"

        def cancel(self, request):
            self.cancelled.append(request)

    class Preparation(QObject):
        ready = Signal(int, object)
        failed = Signal(int, str)

        def __init__(self, _service, parent=None):
            super().__init__(parent)

        def start(self, detail, token):
            entry = SimpleNamespace(path=detail.row.path, basename=detail.row.path.rsplit("/", 1)[-1])
            texture = SimpleNamespace(path="character/texture/skin.dds", basename="skin.dds")
            self.ready.emit(token, SimpleNamespace(dependencies_complete=True, detail=detail,
                                                   entries=(entry, texture), entries_by_id={7: entry}))

        def cancel(self):
            pass

    monkeypatch.setattr(module, "CharacterPreviewPreparation", Preparation)
    monkeypatch.setattr(module, "CharacterCatalogDetailResult", SimpleNamespace)
    service = Service()
    owner = SimpleNamespace(archive=SimpleNamespace(archive_catalogue_service=service))
    return module, service, owner


def _detail(path, catalogue_role, **row):
    fields = {"path": path, "model_count": 1, "resolution": "resolved", "body_family": "2_phw",
              "role": catalogue_role, **row}
    return SimpleNamespace(row=SimpleNamespace(**fields), models=(SimpleNamespace(entry_id=7),))


def _resolve(module, owner, role, path):
    found = []
    resolution = module.HairReferenceResolution(owner)
    resolution.done.connect(lambda entry, dependencies, error: found.append((entry, dependencies, error)))
    resolution.start(role, path, "Damiane")
    return resolution, found


def test_a_head_and_body_are_found_as_the_chooser_finds_them(resolver):
    module, service, owner = resolver
    for role, path, catalogue_role in (("head", HEAD, "head"), ("body", BODY, "whole_character")):
        resolution, found = _resolve(module, owner, role, path)
        assert service.asked[-1] == f"asset:{path}"
        service.result_ready.emit(f"request-{len(service.asked)}", "detail", _detail(path, catalogue_role))
        entry, dependencies, error = found[0]
        assert not error and entry.path == path
        assert dependencies.selected_entry is entry and "character/texture/skin.dds" in dependencies.entries_by_normalized_path


@pytest.mark.parametrize("role, path, row, problem", [
    ("head", BODY, {}, "heads that Change references offers"),
    ("body", "character/model/1_pc/1_phm/nude/phm_00_nude_0001.pac", {}, "base bodies"),
    ("head", HEAD, {"model_count": 2}, "not one resolved model"),
    ("head", HEAD, {"body_family": "1_phm"}, "body family"),
    ("head", HEAD, {"role": "body"}, "heads that Change references offers"),
])
def test_a_reference_the_chooser_would_not_list_is_refused_with_its_reason(resolver, role, path, row, problem):
    module, service, owner = resolver
    resolution, found = _resolve(module, owner, role, path)
    if not found:  # the path itself passed: the catalogue's answer decides
        row = {"role": role, **row}
        service.result_ready.emit(f"request-{len(service.asked)}", "detail", _detail(path, row.pop("role"), **row))
    assert found and found[0][0] is None and problem in found[0][2], found
