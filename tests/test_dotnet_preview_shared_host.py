from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QProcess, Signal
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.services.mesh_dotnet_experiment import (
    MeshDotNetExecutableResolution,
    MeshDotNetExperimentPackage,
    mesh_dotnet_experiment_command,
)
from cdmw.ui.localization import UiLocalizer
from cdmw.ui.preview.dotnet_host import DotNetPreviewHostFrame
from cdmw.ui.preview.dotnet_session import DotNetPreviewSessionController
from cdmw.ui.preview.profile import DotNetPreviewProfile


_APP = QApplication.instance() or QApplication([])

#: Controllers built without a parent, so nothing outside this module owns them.
_UNPARENTED: list[DotNetPreviewSessionController] = []


def _own(controller: DotNetPreviewSessionController) -> DotNetPreviewSessionController:
    """Register a parentless controller so this module destroys it, not the collector.

    Production always gives the controller a parent and it dies with the window.
    Here there is no parent, so the C++ object is destroyed whenever the Python
    reference count happens to reach zero -- which, in a full-suite run, is
    partway through the *next* file's Qt construction. That destruction lands
    inside another Qt operation and aborts the interpreter with
    `QWaitCondition: Destroyed while threads are still waiting`, exit code 3, no
    traceback and no pytest summary. It killed every CI run at roughly 24%.
    """

    _UNPARENTED.append(controller)
    return controller


@pytest.fixture(autouse=True)
def _destroy_unparented_controllers():
    """Keep each controller's destruction inside the test that created it."""

    yield
    while _UNPARENTED:
        controller = _UNPARENTED.pop()
        if not shiboken6.isValid(controller):
            continue
        controller.shutdown()
        shiboken6.delete(controller)


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


def test_clear_preview_is_safe_after_controller_qobject_is_deleted() -> None:
    owner = QObject()
    controller = DotNetPreviewSessionController(host_hwnd=lambda: 0, parent=owner)
    controller.shutdown()
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert controller.clear_preview() is False


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

    controller = _own(DotNetPreviewSessionController(
        host_hwnd=lambda: 1,
        profile=DotNetPreviewProfile.PREVIEW,
        configured_executable=executable,
        terminate_on_close=True,
        process_factory=process_factory,
    ))
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


def _helper_localization_contract() -> tuple[tuple[str, ...], str]:
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "cdmw"
        / "resources"
        / "localization"
        / "source_manifest.json"
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    keys = tuple(
        sorted(
            {
                str(entry["key"])
                for entry in payload["entries"]
                if any(
                    str(origin.get("path", "")).startswith(
                        "tools/dotnet_mesh_editor_experiment/"
                    )
                    for origin in entry.get("origins", ())
                )
            }
        )
    )
    digest = hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()
    return keys, digest


def _localization_protocol_ready(
    *,
    profile: str = "preview",
) -> dict[str, object]:
    keys, digest = _helper_localization_contract()
    return {
        "event": "protocol_ready",
        "profile": profile,
        "capabilities": ["ui_localization_v1"],
        "localization_keys": list(keys),
        "localization_key_manifest_hash": digest,
    }


def _localization_ack(
    request: dict[str, object],
    *,
    status: str = "applied",
) -> dict[str, object]:
    return {
        "event": "ui_localization_state_ack",
        "status": status,
        **{
            key: request[key]
            for key in (
                "language_code",
                "plural_rule",
                "catalog_hash",
                "key_manifest_hash",
                "session_id",
                "process_generation",
                "request_id",
                "localization_revision",
            )
        },
    }


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
    controller._localization_initial_established = True  # noqa: SLF001

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


def test_localization_ack_gates_initial_ready_and_live_switch_is_resident(
    tmp_path: Path,
) -> None:
    controller, process, package = _start_controller(tmp_path)
    localizer = UiLocalizer(language_dir=tmp_path / "languages", language_code="ja")
    controller.set_ui_localizer(localizer)
    ready_payloads: list[object] = []
    applied_locales: list[tuple[str, int]] = []
    controller.renderer_ready.connect(ready_payloads.append)
    controller.localization_applied.connect(
        lambda code, revision: applied_locales.append((code, revision))
    )
    generation = controller.process_generation

    with (
        patch(
            "cdmw.ui.preview.dotnet_session.mesh_dotnet_helper_provenance_blockers",
            return_value=(),
        ),
        patch(
            "cdmw.ui.preview.dotnet_session.mesh_dotnet_renderer_blockers",
            return_value=(),
        ),
    ):
        controller._handle_protocol_event(  # noqa: SLF001
            _localization_protocol_ready(),
            generation,
        )
        initial_request = next(
            payload
            for payload in process.writes
            if payload.get("event") == "ui_localization_state"
        )
        assert initial_request["language_code"] == "ja"
        assert initial_request["plural_rule"] == "other"
        assert set(initial_request["translations"]) == set(
            _helper_localization_contract()[0]
        )
        assert any(
            any(ord(character) > 127 for character in str(value))
            for value in initial_request["translations"].values()
        )
        encoded = (
            json.dumps(initial_request, ensure_ascii=False, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        assert len(encoded) < 256 * 1024

        controller._handle_protocol_event(  # noqa: SLF001
            {
                "event": "ready",
                "profile": "preview",
                "renderer": {"backend": "d3d11_vortice_shader"},
            },
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
        assert ready_payloads == []
        assert controller.applied_package_path == ""

        stale_ack = _localization_ack(initial_request)
        stale_ack["catalog_hash"] = "stale"
        controller._handle_protocol_event(stale_ack, generation)  # noqa: SLF001
        assert ready_payloads == []

        controller._handle_protocol_event(  # noqa: SLF001
            _localization_ack(initial_request),
            generation,
        )

    assert len(ready_payloads) == 1
    assert controller.applied_package_path == str(package.package_dir)
    assert applied_locales == [("ja", localizer.revision)]
    original_process_id = controller.process_id
    original_package_generation = controller.package_generation

    localizer.load_language("de")
    german_request = process.writes[-1]
    assert german_request["event"] == "ui_localization_state"
    localizer.load_language("fr")
    french_request = process.writes[-1]
    assert french_request["event"] == "ui_localization_state"
    assert french_request["language_code"] == "fr"

    controller._handle_protocol_event(  # noqa: SLF001
        _localization_ack(german_request),
        generation,
    )
    assert applied_locales == [("ja", initial_request["localization_revision"])]
    controller._handle_protocol_event(  # noqa: SLF001
        _localization_ack(french_request),
        generation,
    )
    assert applied_locales[-1] == ("fr", french_request["localization_revision"])
    assert controller.process_id == original_process_id
    assert controller.package_generation == original_package_generation
    assert controller.applied_package_path == str(package.package_dir)
    controller.shutdown()


def test_localization_manifest_mismatch_is_rejected_and_latest_locale_replays(
    tmp_path: Path,
) -> None:
    controller, process, _package = _start_controller(tmp_path)
    localizer = UiLocalizer(language_dir=tmp_path / "languages", language_code="de")
    controller.set_ui_localizer(localizer)
    generation = controller.process_generation
    ready_payload = _localization_protocol_ready()

    with patch(
        "cdmw.ui.preview.dotnet_session.mesh_dotnet_helper_provenance_blockers",
        return_value=(),
    ):
        mismatched = dict(ready_payload)
        mismatched["localization_key_manifest_hash"] = "bad"
        controller._handle_protocol_event(mismatched, generation)  # noqa: SLF001
    assert controller.process is None
    assert process.state() == QProcess.ProcessState.NotRunning

    replay_root = tmp_path / "replay"
    replay_root.mkdir()
    controller, process, _package = _start_controller(replay_root)
    localizer = UiLocalizer(
        language_dir=tmp_path / "replay-languages",
        language_code="zh-Hant",
    )
    controller.set_ui_localizer(localizer)
    generation = controller.process_generation
    with patch(
        "cdmw.ui.preview.dotnet_session.mesh_dotnet_helper_provenance_blockers",
        return_value=(),
    ):
        controller._handle_protocol_event(  # noqa: SLF001
            _localization_protocol_ready(),
            generation,
        )
        first_request = next(
            payload
            for payload in reversed(process.writes)
            if payload.get("event") == "ui_localization_state"
        )
        assert first_request["language_code"] == "zh-Hant"

        localizer.load_language("ko")
        controller._reset_localization_handshake()  # noqa: SLF001
        controller._protocol_ready = False  # noqa: SLF001
        controller._process_generation += 1  # noqa: SLF001
        reconnected_generation = controller.process_generation
        controller._handle_protocol_event(  # noqa: SLF001
            _localization_protocol_ready(),
            reconnected_generation,
        )

    replay_request = next(
        payload
        for payload in reversed(process.writes)
        if payload.get("event") == "ui_localization_state"
    )
    assert replay_request["language_code"] == "ko"
    assert replay_request["process_generation"] == reconnected_generation
    assert replay_request["localization_revision"] == localizer.revision
    controller.shutdown()


def test_preview_host_inherits_the_shell_localizer(tmp_path: Path) -> None:
    shell = QWidget()
    shell.ui_localizer = UiLocalizer(  # type: ignore[attr-defined]
        language_dir=tmp_path / "languages",
        language_code="es-419",
        parent=shell,
    )
    controller = _own(
        DotNetPreviewSessionController(
            host_hwnd=lambda: 1,
            profile=DotNetPreviewProfile.PREVIEW,
            terminate_on_close=True,
            process_factory=lambda parent: _FakeProcess(parent),
        )
    )
    host = DotNetPreviewHostFrame(parent=shell, controller=controller)

    assert controller._ui_localizer is shell.ui_localizer  # type: ignore[attr-defined]  # noqa: SLF001
    host.deleteLater()
    shell.deleteLater()


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

    controller = _own(DotNetPreviewSessionController(
        host_hwnd=lambda: 1,
        profile=DotNetPreviewProfile.PREVIEW,
        configured_executable=executable,
        terminate_on_close=True,
        process_factory=process_factory,
    ))
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

    controller = _own(DotNetPreviewSessionController(
        host_hwnd=lambda: 1,
        profile=DotNetPreviewProfile.AUTHORING,
        configured_executable=executable,
        terminate_on_close=True,
        process_factory=process_factory,
    ))
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


def _authoring_controller(
    tmp_path: Path,
    *,
    capabilities: tuple[str, ...] = (),
) -> tuple[DotNetPreviewSessionController, list[_FakeProcess], Path]:
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
    controller._capabilities.update(capabilities)  # noqa: SLF001 - handshake is faked below
    return controller, processes, executable


def _start_authoring_session(
    controller: DotNetPreviewSessionController,
    processes: list[_FakeProcess],
    executable: Path,
    tmp_path: Path,
    *,
    session_id: str,
    package_name: str,
) -> MeshDotNetExperimentPackage:
    assert controller.set_authoritative_session_id(session_id)
    package = replace(
        _package(tmp_path, package_name),
        scene_frame=SimpleNamespace(scene_session_id=session_id),
    )
    capabilities = set(controller.capabilities)
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
        assert controller.load_package(package)
    with patch(
        "cdmw.ui.preview.dotnet_session.mesh_dotnet_helper_provenance_blockers",
        return_value=(),
    ):
        controller._handle_protocol_event(  # noqa: SLF001
            {
                "event": "protocol_ready",
                "profile": "authoring",
                "capabilities": sorted(capabilities),
            },
            controller.process_generation,
        )
    return package


def test_released_authoring_session_hands_the_warm_helper_to_the_next_one(
    tmp_path: Path,
) -> None:
    """Closing a mesh must not leave the helper claimed by a session that is gone.

    `clear_preview` drops the package, the leases and the viewport but keeps the
    process warm for the next mesh on purpose. The session claim had no matching
    release, so it outlived its owner: every later bind was refused and the next
    mesh's package was rejected as "belongs to a different active edit session"
    with no way back except killing the helper.
    """

    controller, processes, executable = _authoring_controller(
        tmp_path,
        capabilities=("authoring_session_handoff_v1",),
    )
    _start_authoring_session(
        controller,
        processes,
        executable,
        tmp_path,
        session_id="edit-session-a",
        package_name="released-a",
    )
    process = processes[-1]

    assert controller.clear_preview()
    assert controller.is_running, "the resident helper is kept warm across a close"
    write_offset = len(process.writes)

    assert controller.set_authoritative_session_id("edit-session-b")

    handoff = [
        payload
        for payload in process.writes[write_offset:]
        if payload.get("event") in {"session_release", "session_state"}
    ]
    assert [payload["event"] for payload in handoff] == ["session_release", "session_state"]
    assert handoff[0]["session_id"] == "edit-session-a"
    assert handoff[1]["session_id"] == "edit-session-b"
    assert handoff[1]["provisional_session"] is False
    assert controller.process is process, "the handoff keeps the warm process"

    second = replace(
        _package(tmp_path, "released-b"),
        scene_frame=SimpleNamespace(scene_session_id="edit-session-b"),
    )
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
        assert controller.load_package(second)
    assert controller.desired_package_path == str(second.package_dir)
    controller.shutdown()


def test_the_same_session_reclaiming_its_helper_costs_no_rebind(tmp_path: Path) -> None:
    """A suspend and resume within one mesh is not a handoff.

    `clear_preview` runs on every ordinary release, including the ones that end
    with the same session coming straight back. Treating that as a handoff would
    re-handshake the helper -- and, on a helper without the capability, throw the
    warm process away -- for a session that never actually changed.
    """

    controller, processes, executable = _authoring_controller(
        tmp_path,
        capabilities=("authoring_session_handoff_v1",),
    )
    _start_authoring_session(
        controller,
        processes,
        executable,
        tmp_path,
        session_id="edit-session-a",
        package_name="resumed-a",
    )
    process = processes[-1]

    assert controller.clear_preview()
    write_offset = len(process.writes)

    assert controller.set_authoritative_session_id("edit-session-a")

    assert [
        payload
        for payload in process.writes[write_offset:]
        if payload.get("event") in {"session_release", "session_state"}
    ] == []
    assert controller.process is process
    controller.shutdown()


def test_a_helper_that_cannot_hand_off_is_replaced_rather_than_reused(tmp_path: Path) -> None:
    """Without the capability the warm start is traded for a correct one.

    An older helper latches its resident session for the life of the process and
    cannot be told the owner left, so it would refuse every correlated message
    from the arriving session: the mesh would appear and then answer nothing.
    """

    controller, processes, executable = _authoring_controller(tmp_path)
    _start_authoring_session(
        controller,
        processes,
        executable,
        tmp_path,
        session_id="edit-session-a",
        package_name="legacy-a",
    )
    process = processes[-1]

    assert controller.clear_preview()
    assert controller.set_authoritative_session_id("edit-session-b")

    assert controller.process is not process
    assert [
        payload
        for payload in process.writes
        if payload.get("event") == "session_release"
    ] == []
    controller.shutdown()


def test_a_live_authoring_session_is_still_not_stealable(tmp_path: Path) -> None:
    """The claim only lapses on release; an owner that never let go still owns it."""

    controller, processes, executable = _authoring_controller(
        tmp_path,
        capabilities=("authoring_session_handoff_v1",),
    )
    _start_authoring_session(
        controller,
        processes,
        executable,
        tmp_path,
        session_id="edit-session-a",
        package_name="live-a",
    )

    assert not controller.set_authoritative_session_id("edit-session-b")
    assert controller.process is processes[-1]
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


def test_twenty_hide_show_cycles_reactivate_the_same_resident_process_and_state(
    tmp_path: Path,
) -> None:
    controller, process, _package = _start_controller(tmp_path)
    states: list[tuple[str, str]] = []
    controller.state_changed.connect(lambda state, message: states.append((state, message)))
    _make_ready(controller)
    initial_activation = next(
        payload
        for payload in reversed(process.writes)
        if payload.get("event") == "activate_request"
    )
    controller._handle_protocol_event(  # noqa: SLF001
        {
            "event": "activated",
            "activation_request_id": initial_activation["activation_request_id"],
            "process_generation": initial_activation["process_generation"],
            "package_generation": initial_activation["package_generation"],
        },
        controller.process_generation,
    )

    remembered = {
        "scene": (
            "scene_state_update",
            {"scene_generation": 8, "interaction_mode": "mesh_edit"},
        ),
        "camera": ("camera_state_update", {"yaw": 0.25, "pitch": -0.1}),
        "selection": ("selection_state_update", {"source_indices": [0]}),
        "tool": (
            "tool_state",
            {
                "enabled": True,
                "tool": "select",
                "selection_mode": "brush",
                "selection_operation": "add",
                "target_mode": "source",
            },
        ),
        "display": ("display_state_update", {"mode": "solid_textured"}),
    }
    for key, (event, payload) in remembered.items():
        assert controller.remember_state(key, event, payload)
    resident_snapshot = {
        key: (event, dict(payload))
        for key, (event, payload) in controller._resident_state.items()  # noqa: SLF001
    }
    process_id = process.processId()
    package_generation = controller.package_generation
    process_generation = controller.process_generation

    for _cycle in range(20):
        write_offset = len(process.writes)
        controller.set_visible(False)
        assert process.writes[-1]["event"] == "deactivate_request"
        assert states[-1][0] == "inactive"

        controller.set_visible(True)
        activation = next(
            payload
            for payload in reversed(process.writes[write_offset:])
            if payload.get("event") == "activate_request"
        )
        assert not any(
            payload.get("event") == "package_load_request"
            for payload in process.writes[write_offset:]
        )
        assert states[-1][0] == "resuming"
        controller._handle_protocol_event(  # noqa: SLF001
            {
                "event": "activated",
                "activation_request_id": activation["activation_request_id"],
                "process_generation": activation["process_generation"],
                "package_generation": activation["package_generation"],
            },
            process_generation,
        )
        assert states[-1][0] == "ready"
        assert controller.process is process
        assert process.processId() == process_id
        assert controller.process_generation == process_generation
        assert controller.package_generation == package_generation
        assert controller._resident_state == resident_snapshot  # noqa: SLF001

    controller.shutdown()


def test_show_with_a_different_desired_identity_loads_before_activation(tmp_path: Path) -> None:
    controller, process, _initial_package = _start_controller(tmp_path)
    _make_ready(controller)
    controller.set_visible(False)
    replacement = _package(tmp_path, "package-b")

    assert controller.load_package(replacement)
    write_offset = len(process.writes)
    controller.set_visible(True)

    resumed = process.writes[write_offset:]
    assert [payload.get("event") for payload in resumed] == ["package_load_request"]
    assert resumed[0]["package_path"] == str(replacement.package_dir)
    controller.shutdown()


def test_a_recovered_activation_cycle_gets_its_own_retry_budget(tmp_path: Path) -> None:
    controller, _process, _package = _start_controller(tmp_path)
    _make_ready(controller)
    controller._pending_activation = None  # noqa: SLF001 - recovered-cycle seam
    controller._activation_retry_count = 1  # noqa: SLF001

    assert controller._request_activation(controller._applied_package)  # noqa: SLF001

    assert controller._activation_retry_count == 0  # noqa: SLF001
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
    controller = _own(DotNetPreviewSessionController(
        host_hwnd=lambda: 1,
        profile=DotNetPreviewProfile.AUTHORING,
        terminate_on_close=True,
        process_factory=lambda parent: _FakeProcess(parent),
    ))
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


def test_preview_host_new_body_package_applies_front_camera_with_safe_fit_margin(
    tmp_path: Path,
) -> None:
    controller, _process, first = _start_controller(tmp_path)
    host = DotNetPreviewHostFrame(profile="preview", controller=controller)
    assert host.load_package(first)

    second = _package(tmp_path, "body-package")
    assert host.load_package(
        second,
        reset_view=True,
        initial_view_state={
            "yaw": 180.0,
            "pitch": 0.0,
            "zoom_factor": 0.75,
            "reason": "archive_model_initial_front",
        },
    )

    event, payload = controller._resident_state["presentation"]  # noqa: SLF001
    assert event == "presentation_state_update"
    assert payload["camera"] == {
        "role": "editable",
        "yaw": 180.0,
        "pitch": 0.0,
        "fit_mode": "fit",
        "fit_relative_zoom": 0.75,
        "pan": [0.0, 0.0],
        "command_generation": 1,
    }
    assert host.view_state_snapshot()["zoom_factor"] == 0.75
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
