from __future__ import annotations

from pathlib import Path
import tempfile
from unittest.mock import patch

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QProcess

from cdmw.ui.preview.dotnet_session import DotNetPreviewSessionController
from cdmw.ui.preview.profile import DotNetPreviewProfile
from tests.test_dotnet_preview_shared_host import (
    _FakeProcess,
    _destroy_unparented_controllers,  # noqa: F401 - use the owning module's Qt teardown fixture
    _make_ready,
    _own,
    _package,
    _resolution,
    _start_controller,
)


@pytest.mark.parametrize("failure", ["exit", "process_error", "session_restart", "renderer_failed", "shutdown"])
def test_capture_failure_completes_once_and_preserves_requested_file(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    controller, process, _ = _start_controller(tmp_path)
    _make_ready(controller)
    completed = []
    controller.capture_completed.connect(completed.append)
    target = tmp_path / "capture.png"
    target.write_bytes(b"previous capture")
    assert controller.request_capture(target)
    request_id, (internal, _) = next(iter(controller._pending_captures.items()))
    internal.write_bytes(b"partial capture")
    # A rejected command is not a renderer failure and must not abort captures.
    controller._handle_protocol_event({"event": "error", "error": "invalid command"}, controller.process_generation)
    assert not completed and not controller._gpu_failed
    if failure == "exit":
        process.kill()
        process.finished.emit(1, QProcess.ExitStatus.NormalExit)
    elif failure == "process_error":
        controller._fail_current_process("protocol stopped", static_failure=False)
    elif failure == "session_restart":
        controller._discard_warm_process()
    elif failure == "renderer_failed":
        controller._handle_protocol_event({"event": "renderer_failed", "error": "surface frame failed: lost"}, controller.process_generation)
        assert controller._gpu_failed
        assert not controller._retry_timer.isActive()
        assert not controller.request_capture(tmp_path / "unserviceable.png")
    else:
        controller.shutdown()
    assert len(completed) == 1
    assert completed[0]["status"] == "error"
    assert completed[0]["requested_output_path"] == str(target)
    assert not controller._pending_captures
    if failure != "exit":
        assert internal.exists(), "the retiring helper may still be writing"
        # Even a late successful reply must neither complete again nor publish.
        controller._handle_capture_result({"event": "capture_result", "request_id": request_id, "status": "captured"})
    controller._handle_capture_result({"request_id": request_id, "status": "captured"})
    assert len(completed) == 1
    assert target.read_bytes() == b"previous capture"
    assert not internal.exists()
    process.kill()
    process.finished.emit(1, QProcess.ExitStatus.NormalExit)
    controller.shutdown()


def test_retired_helper_exit_does_not_fail_replacement_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    controller, retired, _ = _start_controller(tmp_path)
    _make_ready(controller)
    completed = []
    controller.capture_completed.connect(completed.append)
    assert controller.request_capture(tmp_path / "old.png")
    old_id, (old_internal, _) = next(iter(controller._pending_captures.items()))
    old_internal.write_bytes(b"old partial")
    controller._fail_current_process("restart", static_failure=False)
    with (
        patch("cdmw.ui.preview.dotnet_session.resolve_rust_mesh_editor", return_value=_resolution(tmp_path / "helper.exe")),
        patch("cdmw.ui.preview.dotnet_session.validate_rust_mesh_editor_package", return_value=""),
    ):
        controller.retry_now()
    replacement = controller.process
    assert replacement is not None and replacement is not retired
    _make_ready(controller)
    assert controller.request_capture(tmp_path / "new.png")
    new_id, (new_internal, _) = next(iter(controller._pending_captures.items()))
    new_internal.write_bytes(b"new image")
    retired.kill()
    retired.finished.emit(1, QProcess.ExitStatus.NormalExit)
    assert not old_internal.exists()
    assert new_internal.exists() and new_id in controller._pending_captures
    assert [item["request_id"] for item in completed] == [old_id]
    controller._handle_capture_result({"request_id": new_id, "status": "captured"})
    assert (tmp_path / "new.png").read_bytes() == b"new image"
    assert completed[-1]["status"] == "captured"
    assert len(completed) == 2
    controller.shutdown()
    replacement.kill()
    replacement.finished.emit(0, QProcess.ExitStatus.NormalExit)


def test_capture_missing_output_reports_error(tmp_path):
    controller, process, _ = _start_controller(tmp_path)
    _make_ready(controller)
    completed = []
    controller.capture_completed.connect(completed.append)
    assert controller.request_capture(tmp_path / "missing.png")
    request_id = next(iter(controller._pending_captures))
    controller._handle_capture_result({"request_id": request_id, "status": "captured"})
    assert completed[0]["status"] == "error"
    assert "Could not publish capture" in completed[0]["message"]
    controller.shutdown()
    process.kill()
    process.finished.emit(0, QProcess.ExitStatus.NormalExit)


def test_clear_preview_pins_package_until_helper_exit(tmp_path):
    from cdmw.rendering.native_preview_package_cache import native_preview_package_live_paths_guard

    controller, process, package = _start_controller(tmp_path)
    _make_ready(controller)
    assert controller.clear_preview()
    with native_preview_package_live_paths_guard() as live:
        assert package.package_dir.resolve() in live
    process.kill()
    process.finished.emit(0, QProcess.ExitStatus.NormalExit)
    with native_preview_package_live_paths_guard() as live:
        assert package.package_dir.resolve() not in live
    controller.shutdown()


def test_gpu_startup_failure_before_handshake_waits_for_explicit_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    controller, process, package = _start_controller(tmp_path)
    assert not controller._protocol_ready
    process.stdout = b'{"event":"renderer_failed","error":"adapter initialization failed"}\n'
    process.readyReadStandardOutput.emit()
    assert controller._gpu_failed
    assert not controller._ready_timer.isActive()
    # Even an unexpected exit after the failure must not enter the retry loop.
    process.kill()
    process.finished.emit(1, QProcess.ExitStatus.NormalExit)
    controller.set_visible(False)
    controller.set_visible(True)
    controller._launch_if_needed()
    assert controller.process is None
    assert not controller._retry_timer.isActive()
    assert controller.desired_package_path == str(package.package_dir)
    controller.retry_now()
    assert not controller._gpu_failed
    assert controller._retry_timer.isActive()
    controller.shutdown()
    assert not controller._runtime_output_dir


@pytest.mark.parametrize("first_exit", ["retired", "replacement"])
def test_runtime_output_waits_for_every_helper_to_finish(tmp_path, monkeypatch, first_exit):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    controller, retired, _ = _start_controller(tmp_path)
    _make_ready(controller)
    retired.terminate = lambda: None  # Cooperative shutdown has not completed.
    controller._fail_current_process("retry", static_failure=False)
    with (
        patch("cdmw.ui.preview.dotnet_session.resolve_rust_mesh_editor", return_value=_resolution(tmp_path / "helper.exe")),
        patch("cdmw.ui.preview.dotnet_session.validate_rust_mesh_editor_package", return_value=""),
    ):
        controller.retry_now()
    replacement = controller.process
    assert replacement is not None and replacement is not retired
    replacement.terminate = lambda: None
    output = controller._runtime_output_dir
    marker = output / "pending-capture.bin"
    marker.write_bytes(b"in progress")
    try:
        controller.shutdown()
        first, last = (retired, replacement) if first_exit == "retired" else (replacement, retired)
        first.kill()
        first.finished.emit(0, QProcess.ExitStatus.NormalExit)
        assert last.state() == QProcess.ProcessState.Running
        assert marker.read_bytes() == b"in progress"
        assert controller._runtime_output_dir == output
        last.kill()
        last.finished.emit(0, QProcess.ExitStatus.NormalExit)
        assert not output.exists()
        assert controller._runtime_output_dir is None
        assert not controller._pending_process_exits
    finally:
        for process in (retired, replacement):
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.finished.emit(0, QProcess.ExitStatus.NormalExit)


@pytest.mark.parametrize("failure", ["error_signal", "exception"])
def test_launch_failure_does_not_keep_runtime_output_owned(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    def failed_start(process):
        if failure == "exception":
            raise RuntimeError("start failed before creating a child")
        process.errorOccurred.emit(QProcess.ProcessError.FailedToStart)

    monkeypatch.setattr(_FakeProcess, "start", failed_start)
    controller, _, _ = _start_controller(tmp_path)
    output = controller._runtime_output_dir
    assert controller.process is None
    assert not controller._pending_process_exits
    assert output.exists()
    controller.shutdown()
    assert not output.exists()


@pytest.mark.parametrize("outcome", ["finished", "failed_to_start"])
def test_shutdown_without_current_process_keeps_retiring_output(tmp_path, monkeypatch, outcome):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    controller, process, _ = _start_controller(tmp_path)
    process.terminate = lambda: None
    output = controller._runtime_output_dir
    controller._fail_current_process("retry", static_failure=False)
    controller.shutdown()
    assert output.exists()
    process.kill()
    if outcome == "finished":
        process.finished.emit(0, QProcess.ExitStatus.NormalExit)
    else:
        process.errorOccurred.emit(QProcess.ProcessError.FailedToStart)
    assert not output.exists()
    assert not controller._pending_process_exits


def test_renderer_failure_stops_automatic_retries_and_retains_package(tmp_path: Path) -> None:
    controller, process, package = _start_controller(tmp_path)
    _make_ready(controller)
    controller._handle_protocol_event(
        {"event": "renderer_failed", "error": "device removed"}, controller.process_generation,
    )
    assert controller._gpu_failed
    assert not controller._retry_timer.isActive()
    assert not controller._activation_timer.isActive()
    assert not controller._package_timer.isActive()
    assert not controller._ready_timer.isActive()
    assert controller.desired_package_path == str(package.package_dir)
    controller._schedule_retry("device still unavailable", static_failure=False)
    assert not controller._retry_timer.isActive()
    controller.set_visible(False)
    controller.set_visible(True)
    assert controller._gpu_failed
    assert not controller._retry_timer.isActive()
    assert not controller._request_activation(package)
    assert not controller._request_resident_package_load()
    with patch.object(controller, "_fail_current_process") as restart:
        controller.retry_now()
        restart.assert_called_once_with("Restarting GPU rendering.", static_failure=False)
    assert not controller._gpu_failed
    controller.shutdown()
    process.finished.emit(0, QProcess.ExitStatus.NormalExit)

def test_selecting_package_after_gpu_failure_keeps_retry_available(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    controller, process, _package_a = _start_controller(tmp_path)
    try:
        _make_ready(controller)
        controller._handle_protocol_event(
            {"event": "renderer_failed", "error": "device removed"}, controller.process_generation,
        )
        states = []
        controller.state_changed.connect(lambda state, message: states.append((state, message)))
        process.writes.clear()
        package_b = _package(tmp_path, "after-gpu-failure")
        assert controller.load_package(package_b)
        assert controller.desired_package_path == str(package_b.package_dir)
        assert states == [("package_error", "device removed")]
        assert not controller._package_timer.isActive()
        assert not controller._retry_timer.isActive()
        assert not any(row["event"] == "package_load_request" for row in process.writes)
        with patch.object(controller, "_fail_current_process") as restart:
            controller.retry_now()
            restart.assert_called_once_with("Restarting GPU rendering.", static_failure=False)
        assert not controller._gpu_failed
        assert controller.desired_package_path == str(package_b.package_dir)
    finally:
        controller.shutdown()
        process.finished.emit(0, QProcess.ExitStatus.NormalExit)


def test_static_provenance_failure_never_constructs_process(tmp_path: Path) -> None:
    executable = tmp_path / "unverified.exe"
    executable.write_bytes(b"bad")
    process_count = 0

    def process_factory(parent: QObject) -> _FakeProcess:
        nonlocal process_count
        process_count += 1
        return _FakeProcess(parent)

    controller = _own(DotNetPreviewSessionController(
        host_hwnd=lambda: 1,
        configured_executable=executable,
        process_factory=process_factory,
    ))
    with (
        patch("cdmw.ui.preview.dotnet_session.resolve_rust_mesh_editor", return_value=_resolution(executable)),
        patch("cdmw.ui.preview.dotnet_session.validate_rust_mesh_editor_package", return_value="hash mismatch"),
    ):
        assert controller.load_package(_package(tmp_path, "blocked"))
    assert process_count == 0
    assert controller._retry_timer.isActive()  # noqa: SLF001
    assert controller._retry_timer.interval() == 30_000  # noqa: SLF001
    controller.shutdown()
    assert not controller._retry_timer.isActive()  # noqa: SLF001


def _ready_authoring_controller(
    tmp_path: Path,
) -> tuple[DotNetPreviewSessionController, _FakeProcess]:
    executable = tmp_path / "helper.exe"
    executable.write_bytes(b"test")
    processes: list[_FakeProcess] = []

    def process_factory(parent: QObject) -> _FakeProcess:
        process = _FakeProcess(parent)
        processes.append(process)
        return process

    controller = _own(DotNetPreviewSessionController(
        host_hwnd=lambda: 1,
        profile=DotNetPreviewProfile.AUTHORING,
        configured_executable=executable,
        terminate_on_close=True,
        process_factory=process_factory,
    ))
    with (
        patch("cdmw.ui.preview.dotnet_session.resolve_rust_mesh_editor", return_value=_resolution(executable)),
        patch("cdmw.ui.preview.dotnet_session.validate_rust_mesh_editor_package", return_value=""),
    ):
        assert controller.load_package(_package(tmp_path, "authoring-a"))
    _make_ready(controller)
    return controller, processes[-1]


def test_authoring_scene_frame_becomes_the_replayed_resident_scene(tmp_path: Path) -> None:
    """The mesh editor's mesh_edit frame must own the replay slot.

    Package builders all write interaction_mode "placement" into
    dotnet_scene.json, so a replay sourced from the package drops the helper out
    of Edit Mesh on every package reload.
    """
    controller, _process = _ready_authoring_controller(tmp_path)

    assert controller.send_authoring_message(
        {
            "event": "scene_state_update",
            "scene_generation": 7,
            "interaction_mode": "mesh_edit",
            "comparison_mode": "replacement_only",
        }
    )

    event, payload = controller._resident_state["scene"]  # noqa: SLF001
    assert event == "scene_state_update"
    assert payload["interaction_mode"] == "mesh_edit"
    assert payload["comparison_mode"] == "replacement_only"
    assert "event" not in payload
    controller.shutdown()


def test_authoring_scene_frame_replaces_the_package_scene_on_reload(tmp_path: Path) -> None:
    controller, process = _ready_authoring_controller(tmp_path)
    # What DotNetPreviewHost._load_scene_state remembers off the package.
    controller.remember_state(
        "scene",
        "scene_state_update",
        {"scene_generation": 1, "interaction_mode": "placement"},
    )
    assert controller.send_authoring_message(
        {
            "event": "scene_state_update",
            "scene_generation": 7,
            "interaction_mode": "mesh_edit",
        }
    )

    write_offset = len(process.writes)
    controller._replay_resident_state()  # noqa: SLF001

    replayed = [
        payload
        for payload in process.writes[write_offset:]
        if payload.get("event") == "scene_state_update"
    ]
    assert replayed, "the reload replay has to re-assert a scene frame"
    assert replayed[-1]["interaction_mode"] == "mesh_edit"
    controller.shutdown()


def test_preview_scene_frame_cannot_revert_the_authoring_interaction_mode(tmp_path: Path) -> None:
    """A placement nudge during Edit Mesh must not send interaction_mode back.

    _refresh_mesh_edit_controls calls set_alignment_preview_transform on every
    selection change, and that re-remembers the package's own scene frame.
    """
    controller, process = _ready_authoring_controller(tmp_path)
    assert controller.send_authoring_message(
        {
            "event": "scene_state_update",
            "scene_generation": 7,
            "interaction_mode": "mesh_edit",
            "comparison_mode": "replacement_only",
        }
    )

    write_offset = len(process.writes)
    # DotNetPreviewHost.set_alignment_preview_transform, whose _scene_state came
    # straight out of dotnet_scene.json.
    controller.remember_state(
        "scene",
        "scene_state_update",
        {
            "scene_generation": 8,
            "interaction_mode": "placement",
            "comparison_mode": "side_by_side",
            "placement": {"translation": [1.0, 0.0, 0.0]},
        },
    )

    sent = [
        payload
        for payload in process.writes[write_offset:]
        if payload.get("event") == "scene_state_update"
    ]
    assert sent, "the transform update still has to reach the helper"
    assert sent[-1]["interaction_mode"] == "mesh_edit"
    assert sent[-1]["comparison_mode"] == "replacement_only"
    assert sent[-1]["placement"] == {"translation": [1.0, 0.0, 0.0]}

    _event, stored = controller._resident_state["scene"]  # noqa: SLF001
    assert stored["interaction_mode"] == "mesh_edit"
    controller.shutdown()


def test_preview_scene_frame_keeps_its_own_mode_without_an_authoring_frame(tmp_path: Path) -> None:
    controller, process = _ready_authoring_controller(tmp_path)
    write_offset = len(process.writes)
    controller.remember_state(
        "scene",
        "scene_state_update",
        {"scene_generation": 3, "interaction_mode": "placement"},
    )
    sent = [
        payload
        for payload in process.writes[write_offset:]
        if payload.get("event") == "scene_state_update"
    ]
    assert sent[-1]["interaction_mode"] == "placement"
    controller.shutdown()


def test_crash_retry_schedule_and_hidden_pause(tmp_path: Path) -> None:
    controller, process, _package_a = _start_controller(tmp_path)
    process._state = QProcess.ProcessState.NotRunning
    controller._process_finished(process, controller.process_generation, 9, object())  # noqa: SLF001
    assert controller._retry_timer.isActive()  # noqa: SLF001
    assert controller._retry_timer.interval() == 500  # noqa: SLF001
    controller.set_visible(False)
    assert not controller._retry_timer.isActive()  # noqa: SLF001
    controller.shutdown()


def test_a_pending_real_package_never_activates_the_prewarm_placeholder(tmp_path: Path) -> None:
    """The prewarm scene is a procedural triangle nobody asked to see.

    With a real package desired and a handshake gate still down, the session
    used to activate the prewarm scene as a fallback — the flash of the
    placeholder at Mesh Editor start, replaced moments later by the real
    model. It now waits: every gate re-runs the launch finisher when it
    arrives, so the load fires at the first possible moment without ever
    presenting the placeholder.
    """

    owner = QObject()
    controller = DotNetPreviewSessionController(host_hwnd=lambda: 0, parent=owner)
    sent: list[dict] = []
    controller._send_json = lambda payload: bool(sent.append(dict(payload)) or True)
    controller._launch_is_prewarm = True
    controller._visible = True
    controller._protocol_ready = True
    controller._session_established = True
    controller._localization_initial_established = True
    controller._renderer_ready = False
    controller._prewarm_package = _package(tmp_path, "warm")
    controller._desired_package = _package(tmp_path, "real")

    # The helper process is not running, so the package load cannot be
    # requested yet; the only wrong move is presenting the placeholder.
    controller._maybe_finish_launch()

    assert all(payload.get("event") != "activate_request" for payload in sent)
    controller.shutdown()
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

def test_serving_prewarm_placeholder_reports_what_the_helper_is_holding(tmp_path: Path) -> None:
    """Callers outside the controller need to know a resident scene is real.

    The Mesh Editor tab reuses a running helper by activating it in place, which
    reveals whatever it holds. It cannot tell a warm process apart from a loaded
    one by looking at its own cached package, so the controller answers instead.
    `_launch_is_prewarm` is not that answer: it is cleared as soon as the
    renderer reports ready, which can happen before any package is applied.
    """

    owner = QObject()
    controller = DotNetPreviewSessionController(host_hwnd=lambda: 0, parent=owner)

    assert not controller.serving_prewarm_placeholder

    controller._prewarm_package = _package(tmp_path, "warm")
    controller._launch_is_prewarm = True
    assert controller.serving_prewarm_placeholder

    # Ready arrives before any package load and clears the launch flag; the
    # helper is still holding nothing but the placeholder.
    controller._launch_is_prewarm = False
    assert controller.serving_prewarm_placeholder

    # A real package applied into that same warm process is a resident scene.
    real_package = _package(tmp_path, "real")
    controller._applied_package_path = str(real_package.package_dir)
    assert not controller.serving_prewarm_placeholder

    controller.shutdown()
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
