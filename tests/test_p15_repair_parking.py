"""P15 repair pass, section 8.7 A3 and A4: returning from parking and from a crash relaunch.

Through the real path: park, the view closing, unpark's rewrite on its thread,
the relaunch, then the new helper's hello and its first request.
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication

from cdmw.services.mesh_rust_contract import (
    RUST_MESH_EDIT_BACKEND, RUST_MESH_EDITOR_PROTOCOL, RUST_MESH_RENDERER,
)
from cdmw.ui.preview.engine_channel import EngineEditChannel
from tests.test_mesh_rust_editor_selection import _dispose, _tab

_APP = QApplication.instance() or QApplication([])


def _channel(tab, written):
    return EngineEditChannel(
        lambda data: written.extend(json.loads(line) for line in bytes(data).splitlines()) or len(data),
        lambda: 7, lambda _channel: None, tab)


def _wait(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _APP.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _ready_tab(tmp_path, monkeypatch, *, stub_dispose=True):
    tab = _tab(tmp_path)
    written: list[dict] = []
    session = SimpleNamespace(
        closed=False, session_id="draft-a", root=tmp_path, hair_start_mode="",
        shadow_session_id="shadow",
        shadow_service=SimpleNamespace(session_view=lambda _id: SimpleNamespace(revision=4),
                                       _session=lambda _id: SimpleNamespace(hair_state=None)),
        rewrite_for_relaunch=lambda generation: None,
        request_cancel=lambda: True,
    )
    launched: list[object] = []
    failures: list[str] = []
    monkeypatch.setattr(tab, "_launch_rust_editor_process", lambda current: launched.append(current))
    if stub_dispose:
        monkeypatch.setattr(tab, "_schedule_rust_session_dispose", lambda: failures.append("disposed"))
    original_fail = tab._fail_rust_editor
    monkeypatch.setattr(tab, "_fail_rust_editor", lambda message, **kw: failures.append(message))
    monkeypatch.setattr(tab.standalone_native_host_frame, "attach_child_window",
                        lambda child, pid, parent: (True, ""), raising=False)
    tab.standalone_rust_authoring_session = session
    tab.standalone_rust_process = _channel(tab, written)
    tab.standalone_rust_ready = True
    tab.standalone_rust_hello_received = True
    tab.standalone_rust_last_client_request_id = 40  # the first helper's requests
    tab.standalone_rust_process_generation = 3
    return tab, session, written, launched, failures, original_fail


def _hello(tab):
    return {"event": "hello", "protocol": RUST_MESH_EDITOR_PROTOCOL, "session_id": "draft-a",
            "process_generation": tab.standalone_rust_process_generation, "renderer": RUST_MESH_RENDERER,
            "edit_backend": RUST_MESH_EDIT_BACKEND, "capabilities": ["embedded_child_window_v1"],
            "child_hwnd": 11, "embedded_parent_hwnd": 12}


def test_a_document_returning_from_parking_accepts_its_new_helper(tmp_path, monkeypatch) -> None:
    tab, session, written, launched, failures, _fail = _ready_tab(tmp_path, monkeypatch)
    try:
        channel = tab.standalone_rust_process
        assert tab.park_rust_editor()
        tab._handle_rust_process_finished(channel, 0, QProcess.ExitStatus.NormalExit)  # noqa: SLF001
        assert tab.unpark_rust_editor()
        assert _wait(lambda: launched == [session]), "the parked editor was not started again"
        tab.standalone_rust_process = _channel(tab, written)
        # A3: the new helper's hello is a first handshake, not a repeated one.
        tab._handle_rust_protocol_event(_hello(tab))  # noqa: SLF001
        assert failures == [], failures
        assert tab.standalone_rust_hello_received
        # A4: its first request is not refused as replayed.
        tab.standalone_rust_ready = True
        queued: list[dict] = []
        monkeypatch.setattr(tab, "_start_next_rust_protocol_worker", lambda: queued.append(True))
        tab._handle_rust_protocol_event({"event": "command_request", "protocol": RUST_MESH_EDITOR_PROTOCOL,  # noqa: SLF001
                                         "session_id": "draft-a", "request_id": 1,
                                         "process_generation": tab.standalone_rust_process_generation,
                                         "command": "state", "arguments": {}})
        refused = [line for line in written if "replayed" in json.dumps(line)]
        assert not refused and queued, (refused, written[-3:])
    finally:
        tab.standalone_rust_authoring_session = None
        _dispose(tab)


def test_a_crash_relaunch_accepts_the_new_helper_s_first_request(tmp_path, monkeypatch) -> None:
    tab, session, written, launched, failures, _fail = _ready_tab(tmp_path, monkeypatch)
    try:
        assert tab._recover_rust_editor_after_crash()  # noqa: SLF001
        assert _wait(lambda: launched == [session]), "the editor was not started again after the crash"
        tab.standalone_rust_process = _channel(tab, written)
        tab._handle_rust_protocol_event(_hello(tab))  # noqa: SLF001
        assert failures == [], failures
        tab.standalone_rust_ready = True
        queued: list[dict] = []
        monkeypatch.setattr(tab, "_start_next_rust_protocol_worker", lambda: queued.append(True))
        tab._handle_rust_protocol_event({"event": "command_request", "protocol": RUST_MESH_EDITOR_PROTOCOL,  # noqa: SLF001
                                         "session_id": "draft-a", "request_id": 1,
                                         "process_generation": tab.standalone_rust_process_generation,
                                         "command": "state", "arguments": {}})
        refused = [line for line in written if "replayed" in json.dumps(line)]
        assert not refused and queued, (refused, written[-3:])
    finally:
        tab.standalone_rust_authoring_session = None
        _dispose(tab)


def test_an_own_process_crash_keeps_its_session_while_a_request_finishes(tmp_path, monkeypatch) -> None:
    """A7: Qt reports the crash as an error, then as finished; the recovery keeps the session."""

    class _Process(QProcess):
        def processId(self):  # noqa: N802 - QProcess shape
            return 9

    # The real failure path and dispose scheduling: with a request running it only marks the session.
    tab, session, written, launched, failures, _fail = _ready_tab(tmp_path, monkeypatch, stub_dispose=False)
    monkeypatch.setattr(tab, "_fail_rust_editor", _fail)
    process = _Process()
    tab.standalone_rust_process = process
    tab.standalone_rust_protocol_thread = object()  # a request is still running
    try:
        tab._handle_rust_process_error(process, QProcess.ProcessError.Crashed)  # noqa: SLF001
        tab._handle_rust_process_finished(process, 1, QProcess.ExitStatus.CrashExit)  # noqa: SLF001
        assert not tab.standalone_rust_dispose_pending, "the kept session is disposed when the request ends"
        assert tab.standalone_rust_authoring_session is session
    finally:
        tab.standalone_rust_protocol_thread = None
        tab.standalone_rust_authoring_session = None
        _dispose(tab)


def test_a_second_crash_names_the_file_and_asks_one_document_at_a_time(tmp_path, monkeypatch) -> None:
    """Section 8.7 F3: the prompt named no file, and every document asked at once."""

    from types import SimpleNamespace as _NS

    from cdmw.ui.mesh_editor import tab_rust_process

    tabs = []
    for name in ("sword.pac", "helmet.pac"):
        tab, *_ = _ready_tab(tmp_path / name, monkeypatch)
        monkeypatch.setattr(tab, "_current_target_entry", lambda name=name: _NS(basename=name))
        tab._rust_last_crash_at = time.monotonic()  # the first crash a moment ago
        tabs.append(tab)
    asked, open_now, nested = [], [], []

    def answer(box):
        nested.append(len(open_now))
        open_now.append(box)
        asked.append(box.text())
        _wait(lambda: False, timeout=0.3)  # the box's own event loop: other prompts may try to open
        open_now.pop()
        return "discard"

    monkeypatch.setattr(tab_rust_process, "crash_prompt_override", answer)
    for tab in tabs:  # one shared process ended: both documents lost their view
        assert tab._recover_rust_editor_after_crash()
    assert _wait(lambda: len(asked) == 2, timeout=5.0)
    assert nested == [0, 0], "a second prompt opened over the first"
    assert any("sword.pac" in text for text in asked) and any("helmet.pac" in text for text in asked)


def test_a_crash_while_editing_in_browse_continues_in_browse_s_viewport(tmp_path, monkeypatch) -> None:
    """Section 8.7 F4: the relaunch found Browse's process still restarting and moved to the tab."""

    from cdmw.ui.mesh_editor.live_edit.browse_viewport import BrowseViewportBinding
    from cdmw.ui.preview.engine_channel import EDIT_IN_PLACE_CAPABILITY
    from tests.test_dotnet_preview_shared_host import _make_ready, _start_controller

    controller, process, _ = _start_controller(tmp_path)
    controller._test_handshake_capabilities = (EDIT_IN_PLACE_CAPABILITY,)
    tab, session, *_ = _ready_tab(tmp_path / "doc", monkeypatch)
    binding = BrowseViewportBinding(SimpleNamespace(controller=controller), "sword.pac")
    tab.live_edit.edit_in_viewport(binding)
    adopted, moved = [], []
    monkeypatch.setattr(tab, "_adopt_rust_editor_process",
                        lambda channel, current, **kw: adopted.append((channel, kw)))
    tab.live_edit.moved_to_own_viewport.connect(moved.append)
    # Browse's process is restarting after the crash: not ready yet.
    tab._rust_last_crash_at = time.monotonic()
    assert tab._open_in_bound_viewport(session)
    assert tab.live_edit.viewport_binding is binding and not moved
    _make_ready(controller)
    assert _wait(lambda: bool(adopted), timeout=5.0)
    assert adopted[0][1].get("keep_view") is True and not moved
    process.kill()
    process.finished.emit(1, QProcess.ExitStatus.NormalExit)
    controller.shutdown()


def test_showing_a_parked_document_before_its_helper_exits_is_no_crash(tmp_path, monkeypatch) -> None:
    """Section 8.8 R13: the late exit counted as a crash, and twice in a minute raised
    the crash prompt for a healthy document."""

    tab, session, written, launched, failures, _fail = _ready_tab(tmp_path, monkeypatch)
    try:
        channel = tab.standalone_rust_process
        assert tab.park_rust_editor()
        assert tab.unpark_rust_editor(), "showing it again was refused while its view closed"
        tab._handle_rust_process_finished(channel, 0, QProcess.ExitStatus.NormalExit)  # noqa: SLF001
        assert _wait(lambda: launched == [session]), "the view did not open again after the exit"
        assert not getattr(tab, "_rust_last_crash_at", 0.0), "the parked exit counted as a crash"
        assert failures == [], failures
    finally:
        tab.standalone_rust_authoring_session = None
        _dispose(tab)
