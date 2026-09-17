from __future__ import annotations

import json
import tempfile
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QProcess

from cdmw.ui.mesh_editor.process_io import (
    DOTNET_PROTOCOL_BUFFER_LIMIT,
    DOTNET_PROTOCOL_LINE_LIMIT,
)
from cdmw.services.mesh_rust_contract import RUST_MESH_EDITOR_PROTOCOL
from tests.test_dotnet_preview_shared_host import (
    _destroy_unparented_controllers,  # noqa: F401 - owns the preview's Qt teardown
    _make_ready,
    _start_controller,
)
from tests.test_mesh_rust_editor_selection import _BufferedProcess, _dispose, _tab


@pytest.fixture(params=["preview", "editor"])
def stream(request, tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    events = []
    failures = []
    if request.param == "preview":
        owner, process, _ = _start_controller(tmp_path)
        _make_ready(owner)
        owner.protocol_event.connect(events.append)
        fail = owner._fail_current_process

        def fail_preview(reason, *, static_failure):
            failures.append(reason)
            fail(reason, static_failure=static_failure)

        monkeypatch.setattr(owner, "_fail_current_process", fail_preview)

        def feed(chunk):
            process.stdout = chunk
            process.readyReadStandardOutput.emit()

        retire = owner._discard_warm_process
        get_buffer = lambda: owner._stdout_buffer
    else:
        owner = _tab(tmp_path)
        process = _BufferedProcess()
        owner.standalone_rust_process = process
        monkeypatch.setattr(owner, "_handle_rust_protocol_event", events.append)
        fail = owner._fail_rust_editor

        def fail_editor(reason, *, incompatible=False):
            failures.append(reason)
            fail(reason, incompatible=incompatible)

        monkeypatch.setattr(owner, "_fail_rust_editor", fail_editor)

        def feed(chunk):
            process.stdout_chunks.append(chunk)
            owner._handle_rust_stdout_ready(process)

        retire = lambda: setattr(owner, "standalone_rust_process", None)
        get_buffer = lambda: owner.standalone_rust_stdout_buffer

    try:
        yield SimpleNamespace(
            kind=request.param, owner=owner, feed=feed, events=events,
            failures=failures, retire=retire, get_buffer=get_buffer,
        )
    finally:
        if request.param == "preview":
            owner.shutdown()
            process.kill()
            process.finished.emit(0, QProcess.ExitStatus.NormalExit)
        else:
            owner.standalone_rust_process = None
            _dispose(owner)


def _message(**fields):
    return (json.dumps({"event": "state_snapshot", **fields}, ensure_ascii=False) + "\n").encode("utf-8")


def test_complete_protocol_burst_is_not_an_oversized_message(stream):
    line = _message(text="x" * (DOTNET_PROTOCOL_LINE_LIMIT // 2))
    count = DOTNET_PROTOCOL_BUFFER_LIMIT // len(line) + 2
    stream.feed(line * count + b'{"event": "state_')

    assert not stream.failures
    assert len(stream.events) == count
    stream.feed(b'snapshot", "last": true}\n')
    assert stream.events[-1]["last"] is True
    assert len(stream.events) == count + 1
    assert not stream.get_buffer()


def test_protocol_accepts_blank_lines_and_crlf(stream):
    stream.feed(b"\r\n\n" + _message(text="ready").replace(b"\n", b"\r\n") + b"\r\n")

    assert not stream.failures
    assert stream.events == [{"event": "state_snapshot", "text": "ready"}]
    assert not stream.get_buffer()


@pytest.mark.parametrize("character", ["é", "漢", "🙂"])
def test_protocol_preserves_utf8_split_between_process_reads(stream, character):
    expected = "material_" + character + ".dds"
    message = _message(path=expected)
    split = message.index(character.encode("utf-8")) + 1
    stream.feed(message[:split])
    assert not stream.events
    stream.feed(message[split:])

    assert not stream.failures
    assert stream.events == [{"event": "state_snapshot", "path": expected}]


@pytest.mark.parametrize("kind", ["line", "unterminated", "multibyte_line"])
def test_protocol_still_rejects_oversized_input(stream, kind):
    if kind == "line":
        payload = _message(text="x" * DOTNET_PROTOCOL_LINE_LIMIT)
    elif kind == "multibyte_line":
        payload = _message(text="漢" * (DOTNET_PROTOCOL_LINE_LIMIT // 2))
    else:
        payload = b"{" + b"x" * DOTNET_PROTOCOL_BUFFER_LIMIT
    stream.feed(payload)

    assert stream.failures
    assert not stream.events
    assert not stream.get_buffer(), "a rejected message must release its retained input"


def test_protocol_stops_dispatching_after_helper_is_retired(stream, monkeypatch):
    def consume(payload):
        stream.events.append(payload)
        stream.retire()

    if stream.kind == "preview":
        # The first callback can retire the helper without changing its generation.
        stream.owner.protocol_event.disconnect()
        stream.owner.protocol_event.connect(consume)
    else:
        monkeypatch.setattr(stream.owner, "_handle_rust_protocol_event", consume)
    stream.feed(_message(index=1) + _message(index=2))
    stream.feed(_message(index=3))

    assert [event["index"] for event in stream.events] == [1]
    assert not stream.get_buffer()


@pytest.mark.parametrize("event", ["ready", "renderer_recovered", "command_request"])
def test_failed_editor_keeps_terminal_diagnostics_without_accepting_actions(tmp_path, monkeypatch, event):
    owner = _tab(tmp_path)
    owner.standalone_rust_failure_reported = True
    owner.standalone_rust_gpu_failed = True
    owner.standalone_rust_authoring_session = SimpleNamespace(session_id="failed-session")
    actions = []
    monkeypatch.setattr(owner, "_handle_rust_ready", actions.append)
    monkeypatch.setattr(owner, "_send_rust_error_response", lambda *args: actions.append(args))
    payload = {
        "event": event, "session_id": "failed-session",
        "protocol": RUST_MESH_EDITOR_PROTOCOL,
        "process_generation": owner.standalone_rust_process_generation,
    }
    try:
        owner._handle_rust_protocol_event(payload)

        assert owner.standalone_rust_protocol_events == [payload]
        assert owner.standalone_rust_gpu_failed
        assert not actions
        assert not owner.standalone_rust_protocol_queue
    finally:
        owner.standalone_rust_authoring_session = None
        _dispose(owner)
