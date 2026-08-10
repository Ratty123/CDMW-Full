from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QProcess

from cdmw.ui.preview.dotnet_session import DotNetPreviewSessionController
from cdmw.ui.preview.profile import DotNetPreviewProfile
from tests.test_dotnet_preview_shared_host import (
    _FakeProcess,
    _own,
    _package,
    _resolution,
    _start_controller,
)

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
        patch("cdmw.ui.preview.dotnet_session.resolve_mesh_dotnet_experiment_editor", return_value=_resolution(executable)),
        patch(
            "cdmw.ui.preview.dotnet_session.mesh_dotnet_helper_static_provenance_blockers",
            return_value=("hash mismatch",),
        ),
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
        patch("cdmw.ui.preview.dotnet_session.resolve_mesh_dotnet_experiment_editor", return_value=_resolution(executable)),
        patch("cdmw.ui.preview.dotnet_session.mesh_dotnet_helper_static_provenance_blockers", return_value=()),
    ):
        assert controller.load_package(_package(tmp_path, "authoring-a"))
    generation = controller.process_generation
    with (
        patch("cdmw.ui.preview.dotnet_session.mesh_dotnet_helper_provenance_blockers", return_value=()),
        patch("cdmw.ui.preview.dotnet_session.mesh_dotnet_renderer_blockers", return_value=()),
    ):
        controller._handle_protocol_event(  # noqa: SLF001
            {"event": "protocol_ready", "profile": "authoring", "capabilities": []},
            generation,
        )
        controller._handle_protocol_event(  # noqa: SLF001
            {"event": "ready", "profile": "authoring", "renderer": {"backend": "d3d11_vortice_shader"}},
            generation,
        )
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
