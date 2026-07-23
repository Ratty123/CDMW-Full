from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QObject, QProcess, Signal
from PySide6.QtWidgets import QApplication

from cdmw.services.mesh_dotnet_experiment import (
    MeshDotNetExecutableResolution,
    MeshDotNetExperimentPackage,
    mesh_dotnet_experiment_command,
)
from cdmw.ui.preview.dotnet_host import DotNetPreviewHostFrame
from cdmw.ui.preview.dotnet_session import DotNetPreviewSessionController
from cdmw.ui.preview.profile import DotNetPreviewProfile


_APP = QApplication.instance() or QApplication([])


class _FakeProcess(QObject):
    started = Signal()
    finished = Signal(int, object)
    errorOccurred = Signal(object)
    readyReadStandardOutput = Signal()
    readyReadStandardError = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.program = ""
        self.arguments: list[str] = []
        self.working_directory = ""
        self.writes: list[dict[str, object]] = []
        self.stdout = b""
        self.stderr = b""
        self._state = QProcess.ProcessState.NotRunning

    def setProgram(self, value: str) -> None:
        self.program = value

    def setArguments(self, values: list[str]) -> None:
        self.arguments = list(values)

    def setWorkingDirectory(self, value: str) -> None:
        self.working_directory = value

    def setProcessChannelMode(self, _mode: object) -> None:
        return

    def start(self) -> None:
        self._state = QProcess.ProcessState.Running
        self.started.emit()

    def state(self) -> QProcess.ProcessState:
        return self._state

    def write(self, data: bytes) -> int:
        self.writes.append(json.loads(bytes(data).decode("utf-8")))
        return len(data)

    def readAllStandardOutput(self) -> bytes:
        data, self.stdout = self.stdout, b""
        return data

    def readAllStandardError(self) -> bytes:
        data, self.stderr = self.stderr, b""
        return data

    def errorString(self) -> str:
        return "fake process error"

    def processId(self) -> int:
        return 4242

    def terminate(self) -> None:
        self._state = QProcess.ProcessState.NotRunning

    def kill(self) -> None:
        self._state = QProcess.ProcessState.NotRunning


def _package(root: Path, name: str) -> MeshDotNetExperimentPackage:
    package_dir = root / name
    output_dir = package_dir / "output"
    output_dir.mkdir(parents=True)
    paths = {
        "mesh_path": package_dir / "mesh.obj",
        "obj_sidecar_path": package_dir / "mesh.obj.meta.json",
        "cdmeta_path": package_dir / "mesh.cdmeta.json",
        "original_asset_hash_path": package_dir / "original_asset_hash.txt",
        "scene_mesh_path": package_dir / "scene.obj",
        "scene_manifest_path": package_dir / "dotnet_scene.json",
    }
    for key, path in paths.items():
        if key == "scene_manifest_path":
            path.write_text(
                json.dumps(
                    {
                        "source_identity": name,
                        "scene_generation": 1,
                        "editable_submesh_count": 1,
                        "reference_submesh_count": 0,
                    }
                ),
                encoding="utf-8",
            )
        else:
            path.write_text("", encoding="utf-8")
    (package_dir / "net_materials.json").write_text(
        json.dumps({"material_signature": f"signature-{name}"}),
        encoding="utf-8",
    )
    return MeshDotNetExperimentPackage(
        package_dir=package_dir,
        mesh_path=paths["mesh_path"],
        obj_sidecar_path=paths["obj_sidecar_path"],
        cdmeta_path=paths["cdmeta_path"],
        original_asset_hash_path=paths["original_asset_hash_path"],
        status_path=output_dir / "status.json",
        output_dir=output_dir,
        edit_operations_path=output_dir / "edit_operations.json",
        launch_manifest_path=package_dir / "dotnet_launch.json",
        material_signature=f"signature-{name}",
        scene_mesh_path=paths["scene_mesh_path"],
        scene_manifest_path=paths["scene_manifest_path"],
    )


def _resolution(executable: Path) -> MeshDotNetExecutableResolution:
    return MeshDotNetExecutableResolution("", "", "", "", str(executable), True, True, "test")


def _start_controller(tmp_path: Path) -> tuple[DotNetPreviewSessionController, _FakeProcess, MeshDotNetExperimentPackage]:
    executable = tmp_path / "helper.exe"
    executable.write_bytes(b"test")
    processes: list[_FakeProcess] = []

    def process_factory(parent: QObject) -> _FakeProcess:
        process = _FakeProcess(parent)
        processes.append(process)
        return process

    controller = DotNetPreviewSessionController(
        host_hwnd=lambda: 1,
        profile=DotNetPreviewProfile.PREVIEW,
        configured_executable=executable,
        terminate_on_close=True,
        process_factory=process_factory,
    )
    package = _package(tmp_path, "package-a")
    with (
        patch("cdmw.ui.preview.dotnet_session.resolve_mesh_dotnet_experiment_editor", return_value=_resolution(executable)),
        patch("cdmw.ui.preview.dotnet_session.mesh_dotnet_helper_static_provenance_blockers", return_value=()),
    ):
        assert controller.load_package(package)
    return controller, processes[-1], package


def _make_ready(controller: DotNetPreviewSessionController) -> None:
    generation = controller.process_generation
    with (
        patch("cdmw.ui.preview.dotnet_session.mesh_dotnet_helper_provenance_blockers", return_value=()),
        patch("cdmw.ui.preview.dotnet_session.mesh_dotnet_renderer_blockers", return_value=()),
    ):
        controller._handle_protocol_event(  # noqa: SLF001 - focused protocol ownership test
            {"event": "protocol_ready", "profile": "preview", "capabilities": []},
            generation,
        )
        controller._handle_protocol_event(  # noqa: SLF001
            {"event": "ready", "profile": "preview", "renderer": {"backend": "d3d11_vortice_shader"}},
            generation,
        )
        controller._handle_protocol_event(  # noqa: SLF001
            {
                "event": "preview_session_state_ack",
                "status": "applied",
                "process_generation": generation,
            },
            generation,
        )


def test_helper_command_selects_explicit_profiles(tmp_path: Path) -> None:
    package = _package(tmp_path, "command")
    _program, preview = mesh_dotnet_experiment_command(tmp_path / "helper.exe", package, profile="preview")
    _program, authoring = mesh_dotnet_experiment_command(tmp_path / "helper.exe", package, profile="authoring")
    assert preview[-2:] == ["--profile", "preview"]
    assert authoring[-2:] == ["--profile", "authoring"]


def test_renderer_ready_keeps_process_for_nonfatal_material_audit_gaps(tmp_path: Path) -> None:
    controller, process, _package_a = _start_controller(tmp_path)
    ready_payloads: list[object] = []
    controller.renderer_ready.connect(ready_payloads.append)

    controller._handle_renderer_ready(  # noqa: SLF001 - focused readiness contract test
        {
            "event": "ready",
            "profile": "preview",
            "renderer": {
                "backend": "d3d11_vortice_shader",
                "gpu_backed": True,
                "renderer_blocked": False,
                "dds_resources": 24,
                "native_dds_parity": False,
                "dds_native_dxgi_upload": True,
                "dds_upload_mode": "native_dds_mip_chain_with_bitmap_generated_mips",
                "material_contract_gap": ["profile-specific material graphs without capture evidence"],
            },
        }
    )

    assert controller.process is process
    assert controller._renderer_ready is True  # noqa: SLF001
    assert not controller._retry_timer.isActive()  # noqa: SLF001
    assert len(ready_payloads) == 1
    controller.shutdown()


def test_latest_package_generation_rejects_stale_apply(tmp_path: Path) -> None:
    controller, process, first = _start_controller(tmp_path)
    assert controller.process_id == 4242
    applied: list[tuple[str, int]] = []
    controller.package_applied.connect(lambda path, generation: applied.append((path, generation)))
    _make_ready(controller)
    assert applied == [(str(first.package_dir), 1)]

    second = _package(tmp_path, "package-b")
    third = _package(tmp_path, "package-c")
    assert controller.load_package(second)
    second_request = next(payload for payload in reversed(process.writes) if payload.get("event") == "package_load_request")
    assert controller.load_package(third)
    third_request = next(payload for payload in reversed(process.writes) if payload.get("event") == "package_load_request")
    assert second_request["generation"] == 2
    assert third_request["generation"] == 3

    controller._handle_protocol_event(  # noqa: SLF001
        {**second_request, "event": "package_load_applied"},
        controller.process_generation,
    )
    assert applied == [(str(first.package_dir), 1)]
    controller._handle_protocol_event(  # noqa: SLF001
        {**third_request, "event": "package_load_applied"},
        controller.process_generation,
    )
    assert applied[-1] == (str(third.package_dir), 3)
    assert controller.applied_package_path == str(third.package_dir)
    controller.shutdown()
    assert controller.process_id == 0


def test_prewarm_uses_no_package_generation_and_real_request_supersedes_it(tmp_path: Path) -> None:
    executable = tmp_path / "helper.exe"
    executable.write_bytes(b"test")
    processes: list[_FakeProcess] = []

    def process_factory(parent: QObject) -> _FakeProcess:
        process = _FakeProcess(parent)
        processes.append(process)
        return process

    controller = DotNetPreviewSessionController(
        host_hwnd=lambda: 1,
        profile=DotNetPreviewProfile.PREVIEW,
        configured_executable=executable,
        terminate_on_close=True,
        process_factory=process_factory,
    )
    warmup = _package(tmp_path, "prewarm")
    released: list[bool] = []
    lease = SimpleNamespace(release=lambda: released.append(True))
    with (
        patch("cdmw.ui.preview.dotnet_session.resolve_mesh_dotnet_experiment_editor", return_value=_resolution(executable)),
        patch("cdmw.ui.preview.dotnet_session.mesh_dotnet_helper_static_provenance_blockers", return_value=()),
        patch(
            "cdmw.ui.preview.dotnet_session.acquire_dotnet_preview_package_cache_lease_for_path",
            return_value=lease,
        ),
    ):
        assert controller.prewarm(warmup)

    process = processes[-1]
    assert controller.package_generation == 0
    assert controller.applied_package_path == ""
    generation = controller.process_generation
    with patch("cdmw.ui.preview.dotnet_session.mesh_dotnet_helper_provenance_blockers", return_value=()):
        controller._handle_protocol_event(  # noqa: SLF001
            {"event": "protocol_ready", "profile": "preview", "capabilities": []},
            generation,
        )
    controller._handle_protocol_event(  # noqa: SLF001
        {
            "event": "preview_session_state_ack",
            "status": "applied",
            "process_generation": generation,
        },
        generation,
    )
    assert controller.package_generation == 0
    assert controller.applied_package_path == ""
    assert not controller._ready_timer.isActive()  # noqa: SLF001
    prewarm_capture = next(
        payload for payload in reversed(process.writes) if payload.get("event") == "capture_request"
    )
    assert prewarm_capture["width"] == 64
    assert prewarm_capture["height"] == 64
    assert str(prewarm_capture["output_path"]).startswith(str(warmup.output_dir))
    controller._handle_protocol_event(  # noqa: SLF001
        {**prewarm_capture, "event": "capture_result", "status": "captured"},
        generation,
    )
    assert controller._prewarm_capture_request_id == 0  # noqa: SLF001
    assert controller.process is process
    assert controller._prewarm_package is warmup  # noqa: SLF001
    assert controller._package_key(warmup.package_dir) in controller._package_leases  # noqa: SLF001
    assert released == []
    controller.set_visible(False)

    real_package = _package(tmp_path, "real-package")
    assert controller.load_package(real_package)
    assert not any(payload.get("event") == "package_load_request" for payload in process.writes)
    controller.set_visible(True)
    request = next(
        payload for payload in reversed(process.writes) if payload.get("event") == "package_load_request"
    )
    assert request["generation"] == 1
    assert request["package_path"] == str(real_package.package_dir)
    controller._handle_protocol_event(  # noqa: SLF001
        {**request, "event": "package_load_applied"},
        generation,
    )
    assert process.writes[-1]["event"] == "activate_request"
    assert process.writes[-1]["material_signature"] == real_package.material_signature
    with patch("cdmw.ui.preview.dotnet_session.mesh_dotnet_renderer_blockers", return_value=()):
        controller._handle_protocol_event(  # noqa: SLF001
            {"event": "ready", "profile": "preview", "renderer": {"backend": "d3d11_vortice_shader"}},
            generation,
        )
    assert request["generation"] == 1
    assert request["package_path"] == str(real_package.package_dir)
    assert sum(payload.get("event") == "package_load_request" for payload in process.writes) == 1
    assert controller.process_generation == 1
    controller.shutdown()


def test_authoring_prewarm_binds_the_real_edit_session_before_package_switch(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "helper.exe"
    executable.write_bytes(b"test")
    processes: list[_FakeProcess] = []

    def process_factory(parent: QObject) -> _FakeProcess:
        process = _FakeProcess(parent)
        processes.append(process)
        return process

    controller = DotNetPreviewSessionController(
        host_hwnd=lambda: 1,
        profile=DotNetPreviewProfile.AUTHORING,
        configured_executable=executable,
        terminate_on_close=True,
        process_factory=process_factory,
    )
    assert controller.set_authoritative_session_id("edit-session-a")
    warmup = _package(tmp_path, "authoring-prewarm")
    with (
        patch(
            "cdmw.ui.preview.dotnet_session.resolve_mesh_dotnet_experiment_editor",
            return_value=_resolution(executable),
        ),
        patch(
            "cdmw.ui.preview.dotnet_session.mesh_dotnet_helper_static_provenance_blockers",
            return_value=(),
        ),
    ):
        assert controller.prewarm(warmup)

    process = processes[-1]
    with patch(
        "cdmw.ui.preview.dotnet_session.mesh_dotnet_helper_provenance_blockers",
        return_value=(),
    ):
        controller._handle_protocol_event(  # noqa: SLF001
            {"event": "protocol_ready", "profile": "authoring", "capabilities": []},
            controller.process_generation,
        )
    session_message = next(
        payload for payload in process.writes if payload.get("event") == "session_state"
    )
    assert session_message["session_id"] == "edit-session-a"

    real_package = replace(
        _package(tmp_path, "authoring-real"),
        scene_frame=SimpleNamespace(scene_session_id="edit-session-a"),
    )
    assert controller.load_package(real_package)
    request = next(
        payload
        for payload in reversed(process.writes)
        if payload.get("event") == "package_load_request"
    )
    assert request["generation"] == 1
    assert controller.process is process

    wrong_session = replace(
        _package(tmp_path, "authoring-wrong-session"),
        scene_frame=SimpleNamespace(scene_session_id="edit-session-b"),
    )
    generation = controller.package_generation
    assert not controller.set_authoritative_session_id("edit-session-b")
    assert not controller.load_package(wrong_session)
    assert controller.package_generation == generation
    assert controller.process is process
    controller.shutdown()


def test_same_package_identity_is_an_idempotent_resident_activation(tmp_path: Path) -> None:
    controller, process, package = _start_controller(tmp_path)
    _make_ready(controller)
    generation = controller.package_generation
    load_count = sum(payload.get("event") == "package_load_request" for payload in process.writes)
    write_offset = len(process.writes)

    assert controller.load_package(package)

    assert controller.package_generation == generation
    assert sum(payload.get("event") == "package_load_request" for payload in process.writes) == load_count
    assert [payload.get("event") for payload in process.writes[write_offset:]] == ["activate_request"]
    controller.shutdown()


def test_same_path_with_changed_scene_signature_creates_one_new_generation(tmp_path: Path) -> None:
    controller, process, package = _start_controller(tmp_path)
    _make_ready(controller)
    generation = controller.package_generation
    package.scene_manifest_path.write_text(
        json.dumps({"source_identity": "package-a", "scene_generation": 2}),
        encoding="utf-8",
    )

    assert controller.load_package(package)

    request = next(payload for payload in reversed(process.writes) if payload.get("event") == "package_load_request")
    assert controller.package_generation == generation + 1
    assert request["generation"] == generation + 1
    controller.shutdown()


def test_duplicate_ready_is_filtered_before_shared_consumers(tmp_path: Path) -> None:
    controller, _process, _package_a = _start_controller(tmp_path)
    protocol_events: list[dict[str, object]] = []
    ready_events: list[dict[str, object]] = []
    controller.protocol_event.connect(protocol_events.append)
    controller.renderer_ready.connect(ready_events.append)
    _make_ready(controller)
    ready_payload = {
        "event": "ready",
        "profile": "preview",
        "renderer": {"backend": "d3d11_vortice_shader"},
    }

    with patch("cdmw.ui.preview.dotnet_session.mesh_dotnet_renderer_blockers", return_value=()):
        controller._handle_protocol_event(ready_payload, controller.process_generation)  # noqa: SLF001

    assert len(ready_events) == 1
    assert sum(payload.get("event") == "ready" for payload in protocol_events) == 1
    controller.shutdown()


def test_protocol_request_error_keeps_resident_process_without_retry(tmp_path: Path) -> None:
    controller, process, package = _start_controller(tmp_path)
    _make_ready(controller)
    protocol_events: list[dict[str, object]] = []
    controller.protocol_event.connect(protocol_events.append)

    controller._handle_protocol_event(  # noqa: SLF001 - focused process-failure boundary
        {
            "event": "error",
            "code": "invalid_tool_state",
            "message": "Unsupported Mesh .NET tool: vertex",
        },
        controller.process_generation,
    )

    assert controller.process is process
    assert controller.applied_package_path == str(package.package_dir)
    assert not controller._retry_timer.isActive()  # noqa: SLF001
    assert protocol_events[-1]["code"] == "invalid_tool_state"
    controller.shutdown()


def test_authoring_host_normalizes_legacy_selection_tool() -> None:
    controller = DotNetPreviewSessionController(
        host_hwnd=lambda: 1,
        profile=DotNetPreviewProfile.AUTHORING,
        terminate_on_close=True,
        process_factory=lambda parent: _FakeProcess(parent),
    )
    host = DotNetPreviewHostFrame(
        profile=DotNetPreviewProfile.AUTHORING,
        controller=controller,
    )

    assert host.set_mesh_edit_state(
        enabled=False,
        tool="vertex",
        selection_mode="vertex",
    )

    event, payload = controller._resident_state["tool"]  # noqa: SLF001
    assert event == "tool_state"
    assert payload["tool"] == "select"
    assert payload["enabled"] is False
    controller.shutdown()
    host.deleteLater()


def test_package_failure_keeps_resident_scene_and_process_retryable(tmp_path: Path) -> None:
    controller, process, first = _start_controller(tmp_path)
    _make_ready(controller)
    states: list[tuple[str, str]] = []
    failures: list[tuple[str, int, str]] = []
    controller.state_changed.connect(lambda state, message: states.append((state, message)))
    controller.package_failed.connect(lambda path, generation, message: failures.append((path, generation, message)))
    second = _package(tmp_path, "package-b")
    write_offset = len(process.writes)
    assert controller.load_package(second)
    request = next(payload for payload in reversed(process.writes) if payload.get("event") == "package_load_request")
    controller._handle_protocol_event(  # noqa: SLF001
        {**request, "event": "package_load_failed", "message": "missing texture"},
        controller.process_generation,
    )

    assert controller.process is process
    assert controller.applied_package_path == str(first.package_dir)
    assert not controller._retry_timer.isActive()  # noqa: SLF001
    assert failures[-1] == (str(second.package_dir), 2, "missing texture")
    assert states[-1][0] == "package_error"
    assert "deactivate_request" not in {
        str(payload.get("event", "")) for payload in process.writes[write_offset:]
    }
    failed_generation = controller.package_generation
    failed_request_id = int(request["request_id"])

    assert controller.load_package(second)

    retry_request = next(
        payload
        for payload in reversed(process.writes)
        if payload.get("event") == "package_load_request"
    )
    assert controller.package_generation == failed_generation
    assert int(retry_request["request_id"]) == failed_request_id + 1
    assert retry_request["package_path"] == str(second.package_dir)
    controller.shutdown()


def test_invalid_replacement_is_recoverable_and_keeps_resident_scene(tmp_path: Path) -> None:
    controller, process, package = _start_controller(tmp_path)
    _make_ready(controller)
    states: list[str] = []
    controller.state_changed.connect(lambda state, _message: states.append(state))

    missing_package = tmp_path / "missing-package"
    assert not controller.load_package(missing_package)

    assert controller.process is process
    assert controller.applied_package_path == str(package.package_dir)
    assert states[-1] == "package_error"
    assert not controller._retry_timer.isActive()  # noqa: SLF001

    repaired = _package(tmp_path, "missing-package")
    generation = controller.package_generation
    controller.retry_now()

    retry_request = next(
        payload
        for payload in reversed(process.writes)
        if payload.get("event") == "package_load_request"
    )
    assert retry_request["package_path"] == str(repaired.package_dir)
    assert controller.package_generation == generation + 1
    controller.shutdown()


def test_preview_host_restores_absolute_camera_and_rejects_mutation(tmp_path: Path) -> None:
    controller, _process, package = _start_controller(tmp_path)
    host = DotNetPreviewHostFrame(profile="preview", controller=controller)
    assert host.load_package(package)
    assert host.restore_view_state(
        {
            "yaw": 27.0,
            "pitch": -11.0,
            "zoom_factor": 2.5,
            "fit_to_view": False,
            "pan": (3.0, 4.0, 0.0),
        }
    )
    event, payload = controller._resident_state["presentation"]  # noqa: SLF001
    assert event == "presentation_state_update"
    assert payload["camera"] == {
        "role": "editable",
        "yaw": 27.0,
        "pitch": -11.0,
        "fit_mode": "manual",
        "fit_relative_zoom": 2.5,
        "pan": [3.0, 4.0],
        "command_generation": 1,
    }
    assert host.update_mesh_edit_vertices([], revision=2) is False
    controller.shutdown()


def test_preview_host_changes_viewport_display_mode_through_resident_presentation(tmp_path: Path) -> None:
    controller, _process, package = _start_controller(tmp_path)
    host = DotNetPreviewHostFrame(profile="preview", controller=controller)
    assert host.load_package(package)

    assert host.set_viewport_display_mode("untextured-wire")

    event, payload = controller._resident_state["presentation"]  # noqa: SLF001
    assert event == "presentation_state_update"
    assert payload["display"]["mode"] == "untextured_wire"
    controller.shutdown()


def test_preview_host_new_package_reset_replaces_stale_camera_replay(tmp_path: Path) -> None:
    controller, _process, first = _start_controller(tmp_path)
    host = DotNetPreviewHostFrame(profile="preview", controller=controller)
    assert host.load_package(first)
    assert host.restore_view_state(
        {
            "yaw": 27.0,
            "pitch": -11.0,
            "zoom_factor": 2.5,
            "fit_to_view": False,
            "pan": (33.0, -14.0, 0.0),
        }
    )

    second = _package(tmp_path, "package-b")
    assert host.load_package(
        second,
        reset_view=True,
        initial_view_state={"yaw": 0.0, "pitch": -89.0, "reason": "archive_model_initial_overhead"},
    )
    assert host.set_render_tuning(SimpleNamespace())
    event, payload = controller._resident_state["presentation"]  # noqa: SLF001
    assert event == "presentation_state_update"
    assert payload["camera"] == {
        "role": "editable",
        "yaw": 0.0,
        "pitch": -89.0,
        "fit_mode": "fit",
        "fit_relative_zoom": 1.0,
        "pan": [0.0, 0.0],
        "command_generation": 2,
    }
    assert host.view_state_snapshot()["pan"] == (0.0, 0.0, 0.0)

    assert host.restore_view_state(
        {
            "yaw": 18.0,
            "pitch": 7.0,
            "zoom_factor": 1.75,
            "fit_to_view": False,
            "pan": (8.0, 5.0, 0.0),
        }
    )
    assert host.load_package(second, reset_view=False)
    assert host.set_render_tuning(SimpleNamespace())
    _event, same_model_payload = controller._resident_state["presentation"]  # noqa: SLF001
    assert same_model_payload["camera"]["pan"] == [8.0, 5.0]
    assert same_model_payload["camera"]["fit_mode"] == "manual"
    controller.shutdown()


def test_preview_host_fit_resets_pan_and_zoom_without_changing_angle(tmp_path: Path) -> None:
    controller, _process, package = _start_controller(tmp_path)
    host = DotNetPreviewHostFrame(profile="preview", controller=controller)
    assert host.load_package(package)
    assert host.restore_view_state(
        {
            "yaw": 18.0,
            "pitch": -7.0,
            "zoom_factor": 3.0,
            "fit_to_view": False,
            "pan": (40.0, -25.0, 0.0),
        }
    )

    host.set_fit_to_view(True)

    _event, payload = controller._resident_state["presentation"]  # noqa: SLF001
    assert payload["camera"]["yaw"] == 18.0
    assert payload["camera"]["pitch"] == -7.0
    assert payload["camera"]["fit_mode"] == "fit"
    assert payload["camera"]["fit_relative_zoom"] == 1.0
    assert payload["camera"]["pan"] == [0.0, 0.0]
    controller.shutdown()


def test_preview_host_preserves_zero_degree_renderer_camera(tmp_path: Path) -> None:
    controller, _process, package = _start_controller(tmp_path)
    host = DotNetPreviewHostFrame(profile="preview", controller=controller)
    assert host.load_package(package)

    host._handle_view_state_payload(  # noqa: SLF001
        {
            "active_camera_context": "editable",
            "view_contexts": [
                {
                    "id": "editable",
                    "camera": {
                        "yaw_degrees": 0.0,
                        "pitch_degrees": 0.0,
                        "fit_relative_zoom": 1.0,
                        "fit_mode": "manual",
                        "pan": [0.0, 0.0],
                    },
                }
            ],
        }
    )

    state = host.view_state_snapshot()
    assert state["yaw"] == 0.0
    assert state["pitch"] == 0.0
    controller.shutdown()


def test_static_provenance_failure_never_constructs_process(tmp_path: Path) -> None:
    executable = tmp_path / "unverified.exe"
    executable.write_bytes(b"bad")
    process_count = 0

    def process_factory(parent: QObject) -> _FakeProcess:
        nonlocal process_count
        process_count += 1
        return _FakeProcess(parent)

    controller = DotNetPreviewSessionController(
        host_hwnd=lambda: 1,
        configured_executable=executable,
        process_factory=process_factory,
    )
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


def test_crash_retry_schedule_and_hidden_pause(tmp_path: Path) -> None:
    controller, process, _package_a = _start_controller(tmp_path)
    process._state = QProcess.ProcessState.NotRunning
    controller._process_finished(process, controller.process_generation, 9, object())  # noqa: SLF001
    assert controller._retry_timer.isActive()  # noqa: SLF001
    assert controller._retry_timer.interval() == 500  # noqa: SLF001
    controller.set_visible(False)
    assert not controller._retry_timer.isActive()  # noqa: SLF001
    controller.shutdown()
