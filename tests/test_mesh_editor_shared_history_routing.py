"""Work B item 4 on the tab: Undo and Redo routed by the one history, the dock's part."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from cdmw.ui.mesh_editor import shared_history_routing as routing
from cdmw.ui.mesh_editor.shared_edit_history import SharedEditHistory
from cdmw.ui.mesh_editor.texture_tools_dock import LiveTextureTarget, MeshEditorTextureTools, _target_key

_APP = QApplication.instance() or QApplication([])


class _Editor(QWidget):
    """The Texture Editor's history as the dock sees it."""

    def __init__(self) -> None:
        super().__init__()
        self.history_snapshots, self.history_index = [object()], 0
        self.undo_button, self.redo_button = QPushButton("Undo"), QPushButton("Redo")
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        self.opened = []

    def edit(self) -> None:
        self.history_snapshots = self.history_snapshots[: self.history_index + 1] + [object()]
        self.history_index += 1

    def undo(self) -> None:
        self.history_index = max(0, self.history_index - 1)

    def redo(self) -> None:
        self.history_index = min(len(self.history_snapshots) - 1, self.history_index + 1)

    def open_source_path(self, path, *, binding=None) -> None:
        self.opened.append(path)


def _dock(editor: _Editor) -> tuple[MeshEditorTextureTools, object]:
    dock = MeshEditorTextureTools(editor_factory=lambda _parent: editor)
    target = LiveTextureTarget(session_id="s", source_path=r"C:\t\ub_d.dds", source_sha256="abc",
                               channel="color", display_name="ub_d.dds", game_path="character/texture/ub_d.dds")
    dock.open_target(target)
    return dock, target


def _tab(dock, history):
    sent = []
    tab = SimpleNamespace(_shared_edit_history=history, _texture_tools_panel=lambda: dock,
                          standalone_rust_ready=True, standalone_rust_protocol_thread=None,
                          _send_rust_message=lambda message: sent.append(message) or True,
                          _rust_host_message=lambda event, request_id, extra: {"event": event, **extra})
    return tab, sent


def test_undo_goes_to_the_mesh_or_steps_the_texture_here():
    editor = _Editor()
    dock, target = _dock(editor)
    history = SharedEditHistory()
    dock.shared_history = history
    tab, sent = _tab(dock, history)
    history.merged([{"action": "transform", "label": "Move", "state": "applied"}])
    dock.observe_history(target)
    editor.edit()
    dock.observe_history(target)

    # The texture edit is on top: Undo steps it here and asks the worker only for the state.
    routed = routing.route_history_step(tab, {"event": "command_request", "command": "undo", "request_id": 4})
    assert routed["command"] == "state" and routed["request_id"] == 4
    assert editor.history_index == 0
    assert history.current_history_payload()["history_cursor"] == 1

    # Now the mesh edit is on top: Undo goes to the worker as it is.
    routed = routing.route_history_step(tab, {"event": "command_request", "command": "undo"})
    assert routed["command"] == "undo"
    fields = history.merged([{"action": "transform", "label": "Move", "state": "undone"}])
    assert fields["history_cursor"] == 0

    # Redo: the mesh edit first, then the texture edit here.
    assert routing.route_history_step(tab, {"event": "command_request", "command": "redo"})["command"] == "redo"
    history.merged([{"action": "transform", "label": "Move", "state": "applied"}])
    assert routing.route_history_step(tab, {"event": "command_request", "command": "redo"})["command"] == "state"
    assert editor.history_index == 1
    assert history.current_history_payload()["history_cursor"] == 2
    # Nothing left to redo: the mesh stacks are not asked.
    assert routing.route_history_step(tab, {"event": "command_request", "command": "redo"})["command"] == "state"
    assert sent == []


def test_other_requests_pass_untouched():
    tab = SimpleNamespace(_shared_edit_history=SharedEditHistory())
    event = {"event": "transaction_request", "command": "undo"}
    assert routing.route_history_step(tab, event) == event
    assert routing.route_history_step(SimpleNamespace(), {"event": "command_request", "command": "undo"}) == {
        "event": "command_request", "command": "undo"}


def test_a_texture_edit_in_the_dock_reaches_the_editor_and_again_after_a_reply():
    editor = _Editor()
    dock, target = _dock(editor)
    history = SharedEditHistory()
    dock.shared_history = history
    tab, sent = _tab(dock, history)
    tab.standalone_rust_protocol_thread = object()  # a request is being built
    dock.history_moved.connect(lambda: routing.texture_history_changed(tab))
    dock.observe_history(target)
    editor.edit()
    dock.observe_history(target)
    assert [m["event"] for m in sent] == ["history_update"]
    entry = sent[0]["payload"]["history_entries"][0]
    assert entry["label"] == "Texture edit" and entry["texture"] == "ub_d.dds"
    routing.follow_reply(tab)
    routing.follow_reply(tab)
    assert [m["event"] for m in sent] == ["history_update", "history_update"]


def test_the_dock_buttons_ask_the_editor_and_fall_back_to_the_texture():
    editor = _Editor()
    dock, _target = _dock(editor)
    asked = []
    dock.step_handler = lambda step: asked.append(step) or True
    editor.edit()
    editor.undo_button.click()
    assert asked == ["undo"] and editor.history_index == 1
    dock.step_handler = None
    editor.undo_button.click()
    assert editor.history_index == 0
    sent = []
    tab = SimpleNamespace(standalone_rust_ready=True, _send_rust_message=lambda m: sent.append(m) or True,
                          _rust_host_message=lambda event, request_id, extra: {"event": event, **extra})
    assert routing.step_from_dock(tab, "redo") is True
    assert sent == [{"event": "run_command", "command": "session.redo"}]
    assert routing.step_from_dock(SimpleNamespace(standalone_rust_ready=False), "undo") is False


def test_target_keys_match_the_dock():
    assert _target_key(r"C:\t\ub_d.dds") == _target_key(r"C:\t\ub_d.dds")


def test_the_real_authoring_session_takes_the_shared_history():
    # B pass 2 (2026-11-16): the session class is a slotted dataclass, so a history the
    # class did not declare could not be attached and the editor never opened.
    from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession

    session = RustMeshAuthoringSession.__new__(RustMeshAuthoringSession)
    tab = SimpleNamespace(_texture_tools_panel=lambda: None)
    history = routing.attach_shared_history(tab, session)
    assert session.shared_history is history is tab._shared_edit_history
    view = SimpleNamespace(history_entries=[{"action": "transform", "label": "Move", "state": "applied"}])
    assert session.history_fields(view)["history_entries"] == [{"action": "transform", "label": "Move"}]
