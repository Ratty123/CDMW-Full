"""Resident, retrying QProcess controller for the shared .NET/Vortice preview."""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from cdmw.services.atomic_file_service import atomic_copy_file
from cdmw.services.preview_rendering_service import (
    acquire_dotnet_preview_package_cache_lease_for_path,
)
from cdmw.services.mesh_dotnet_experiment import (
    MeshDotNetExperimentPackage,
    mesh_dotnet_experiment_command,
    mesh_dotnet_experiment_package_from_path,
    mesh_dotnet_helper_provenance_blockers,
    mesh_dotnet_helper_static_provenance_blockers,
    mesh_dotnet_renderer_blockers,
    resolve_mesh_dotnet_experiment_editor,
)
from cdmw.ui.mesh_editor.process_io import (
    DOTNET_PROTOCOL_BUFFER_LIMIT,
    DOTNET_PROTOCOL_LINE_LIMIT,
    append_bounded_text,
    qprocess_is_running,
    stop_qprocess_async,
)
from cdmw.ui.preview.profile import DotNetPreviewProfile


_TRANSIENT_RETRY_DELAYS_MS = (500, 1_000, 2_000, 5_000)
_STEADY_RETRY_DELAY_MS = 5_000
_STATIC_RETRY_DELAY_MS = 30_000
_READY_TIMEOUT_MS = 10_000
_PACKAGE_TIMEOUT_MS = 15_000

_BASE_PROTOCOL_CAPABILITIES = (
    "helper_build_provenance_v1",
    "resident_package_load_v1",
    "resident_preview_package_replace_v2",
    "deterministic_offscreen_capture_v1",
    "absolute_camera_state_v1",
    "view_state_changed_v1",
    "overlay_state_update_v1",
    "skeleton_overlay_v1",
    "pbd_cloth_overlay_v1",
)
_PREVIEW_PROTOCOL_CAPABILITIES = (
    "preview_profile_read_only_v1",
    "preview_session_v1",
    "read_only_part_pick_v1",
)
_AUTHORING_PROTOCOL_CAPABILITIES = (
    "mesh_edit_revision_ack_v1",
    "resident_mutation_envelope_v2",
    "host_tool_state_v1",
)


class DotNetPreviewSessionController(QObject):
    """Own exactly one helper process and a latest-wins resident package stream."""

    state_changed = Signal(str, str)
    protocol_event = Signal(object)
    renderer_ready = Signal(object)
    package_applied = Signal(str, int)
    package_failed = Signal(str, int, str)
    view_state_changed = Signal(object)
    part_pick_result = Signal(object)
    capture_completed = Signal(object)
    rehydrate_requested = Signal(int)

    def __init__(
        self,
        *,
        host_hwnd: Callable[[], int],
        profile: DotNetPreviewProfile | str = DotNetPreviewProfile.PREVIEW,
        configured_executable: Path | str | None = None,
        terminate_on_close: bool = False,
        authoring_rehydrator: Callable[["DotNetPreviewSessionController"], bool] | None = None,
        process_factory: Callable[[QObject], object] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.profile = DotNetPreviewProfile.normalize(profile)
        self._host_hwnd = host_hwnd
        self._configured_executable = configured_executable
        self._terminate_on_close = bool(terminate_on_close)
        self._authoring_rehydrator = authoring_rehydrator
        self._process_factory = process_factory or (lambda owner: QProcess(owner))

        self._process: object | None = None
        self._process_generation = 0
        self._package_generation = 0
        self._package_request_id = 0
        self._pending_package_generation = 0
        self._protocol_request_id = 0
        self._launch_package_generation = 0
        self._launch_package_path = ""
        self._launch_is_prewarm = False
        self._prewarm_package: MeshDotNetExperimentPackage | None = None
        self._desired_package: MeshDotNetExperimentPackage | None = None
        self._desired_package_identity: tuple[str, str, str] | None = None
        self._applied_package: MeshDotNetExperimentPackage | None = None
        self._applied_package_identity: tuple[str, str, str] | None = None
        self._invalid_retry_package_path = ""
        self._invalid_retry_status_path = ""
        self._invalid_retry_reset_view = False
        self._applied_package_path = ""
        self._applied_package_generation = 0
        self._visible = True
        self._closed = False
        self._protocol_ready = False
        self._renderer_ready = False
        self._session_established = False
        self._active = False
        self._retry_attempt = 0
        self._retry_reason = ""
        self._executable = Path()
        self._stdout_buffer = b""
        self._stdout_tail = ""
        self._stderr_tail = ""
        self._capabilities: set[str] = set()
        self._session_id = uuid.uuid4().hex
        self._resident_state: OrderedDict[str, tuple[str, dict[str, object]]] = OrderedDict()
        self._package_leases: dict[str, object] = {}
        self._pending_captures: dict[int, tuple[Path, Path]] = {}
        self._prewarm_capture_request_id = 0
        self._prewarm_capture_path: Path | None = None
        self._last_event: dict[str, object] = {}

        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._launch_if_needed)
        self._ready_timer = QTimer(self)
        self._ready_timer.setSingleShot(True)
        self._ready_timer.timeout.connect(self._handle_ready_timeout)
        self._package_timer = QTimer(self)
        self._package_timer.setSingleShot(True)
        self._package_timer.timeout.connect(self._handle_package_timeout)

    @property
    def process_generation(self) -> int:
        return self._process_generation

    @property
    def package_generation(self) -> int:
        return self._package_generation

    @property
    def applied_package_generation(self) -> int:
        return self._applied_package_generation

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(self._capabilities)

    @property
    def process(self) -> object | None:
        return self._process

    @property
    def process_id(self) -> int:
        process = self._process
        if process is None:
            return 0
        try:
            return max(0, int(process.processId()))
        except (AttributeError, RuntimeError, TypeError, ValueError, OverflowError):
            return 0

    @property
    def is_running(self) -> bool:
        return self._process is not None and qprocess_is_running(self._process)

    def set_configured_executable(self, executable: Path | str | None) -> None:
        self._configured_executable = executable

    def set_authoritative_session_id(self, session_id: str) -> bool:
        normalized = str(session_id or "").strip()
        if self.profile is not DotNetPreviewProfile.AUTHORING or not normalized:
            return False
        if self._session_established and normalized != self._session_id:
            return False
        self._session_id = normalized
        return True

    def set_authoring_rehydrator(
        self,
        callback: Callable[["DotNetPreviewSessionController"], bool] | None,
    ) -> None:
        self._authoring_rehydrator = callback

    def send_authoring_message(self, payload: Mapping[str, object]) -> bool:
        if self.profile is not DotNetPreviewProfile.AUTHORING or not self._can_send_protocol():
            return False
        message = dict(payload)
        message.setdefault("session_id", self._session_id)
        message.setdefault("process_generation", self._process_generation)
        message.setdefault("protocol_version", 2)
        return self._send_json(message)

    @property
    def desired_package_path(self) -> str:
        package = self._desired_package
        return str(package.package_dir) if package is not None else ""

    @property
    def applied_package_path(self) -> str:
        return self._applied_package_path

    @property
    def last_event(self) -> Mapping[str, object]:
        return dict(self._last_event)

    def load_package(
        self,
        package: MeshDotNetExperimentPackage | Path | str,
        status_path: Path | str | None = None,
        *,
        reset_view: bool = False,
        force_reload: bool = False,
    ) -> bool:
        if self._closed:
            return False
        try:
            resolved = (
                package
                if isinstance(package, MeshDotNetExperimentPackage)
                else mesh_dotnet_experiment_package_from_path(package, status_path=status_path)
            )
        except (OSError, TypeError, ValueError) as exc:
            self._invalid_retry_package_path = str(package)
            self._invalid_retry_status_path = str(status_path or "")
            self._invalid_retry_reset_view = bool(reset_view)
            detail = f".NET/Vortice preview package is invalid: {exc}"
            self.package_failed.emit(str(package), self._package_generation, detail)
            self._set_state("package_error", detail)
            return False
        self._invalid_retry_package_path = ""
        self._invalid_retry_status_path = ""
        self._invalid_retry_reset_view = False
        identity = self._package_identity(resolved)
        if self.profile is DotNetPreviewProfile.AUTHORING:
            scene_session_id = str(
                getattr(getattr(resolved, "scene_frame", None), "scene_session_id", "") or ""
            ).strip()
            if scene_session_id and not self.set_authoritative_session_id(scene_session_id):
                detail = (
                    ".NET/Vortice authoring package belongs to a different active edit session. "
                    "Close the current editor before opening another mesh."
                )
                self.package_failed.emit(str(resolved.package_dir), self._package_generation, detail)
                self._set_state("package_error", detail)
                return False
        if not force_reload and identity == self._desired_package_identity:
            if reset_view:
                self._resident_state.pop("presentation", None)
            if self._visible and identity == self._applied_package_identity:
                self._activate()
            elif (
                self._visible
                and self._can_send_protocol()
                and self._protocol_ready
                and self._renderer_ready
                and self._session_established
                and not self._package_timer.isActive()
            ):
                # A prior recoverable package failure leaves the desired identity
                # intact. A repeated request is an explicit retry, not a new scene
                # generation or process launch.
                self._request_resident_package_load()
            return True

        previous_desired = self.desired_package_path
        self._hold_package_lease(resolved.package_dir)
        self._package_generation += 1
        self._desired_package = resolved
        self._desired_package_identity = identity
        if reset_view:
            self._resident_state.pop("presentation", None)
        if (
            previous_desired
            and self._package_key(previous_desired) != self._package_key(resolved.package_dir)
            and self._package_key(previous_desired) != self._package_key(self._applied_package_path)
        ):
            self._release_package_lease(previous_desired)
        self._set_state("preparing", ".NET/Vortice Preview is preparing the selected model…")
        if not force_reload and identity == self._applied_package_identity:
            self._package_timer.stop()
            self._pending_package_generation = 0
            self._applied_package = resolved
            self._applied_package_path = str(resolved.package_dir)
            self._applied_package_generation = self._package_generation
            self._retain_package_leases({self._applied_package_path})
            self._set_state("ready", ".NET/Vortice Preview")
            if self._visible:
                self._activate()
            return True
        if self._visible:
            if self._launch_is_prewarm and not self._renderer_ready:
                if not self._request_resident_package_load():
                    self._activate_prewarm()
            elif self._can_send_protocol():
                self._request_resident_package_load()
            else:
                self.retry_now()
        return True

    def prewarm(
        self,
        package: MeshDotNetExperimentPackage | Path | str,
        status_path: Path | str | None = None,
    ) -> bool:
        """Start the resident helper without consuming a user package generation."""

        if self._closed or self._desired_package is not None or self.is_running:
            return False
        try:
            resolved = (
                package
                if isinstance(package, MeshDotNetExperimentPackage)
                else mesh_dotnet_experiment_package_from_path(package, status_path=status_path)
            )
        except (OSError, TypeError, ValueError):
            return False
        self._prewarm_package = resolved
        self._hold_package_lease(resolved.package_dir)
        self._launch_if_needed()
        return self.is_running

    def clear_preview(self) -> bool:
        self._package_generation += 1
        self._desired_package = None
        self._desired_package_identity = None
        self._applied_package = None
        self._applied_package_identity = None
        self._applied_package_path = ""
        self._applied_package_generation = 0
        self._invalid_retry_package_path = ""
        self._invalid_retry_status_path = ""
        self._invalid_retry_reset_view = False
        self._package_timer.stop()
        self._pending_package_generation = 0
        self._deactivate_for_replacement()
        self._release_package_leases()
        self._set_state("empty", "Select a model to open .NET/Vortice Preview.")
        return True

    def set_visible(self, visible: bool) -> None:
        self._visible = bool(visible)
        if self._closed:
            return
        if not self._visible:
            self._retry_timer.stop()
            self._send_json({"event": "deactivate_request"})
            self._active = False
            self._set_state("inactive", ".NET/Vortice Preview paused while hidden.")
            return
        if self._launch_is_prewarm and self._session_established and not self._renderer_ready:
            if self._desired_package is None or not self._request_resident_package_load():
                self._activate_prewarm()
            if self._desired_package is None:
                return
        if self._desired_package is None:
            self._set_state("empty", "Select a model to open .NET/Vortice Preview.")
            return
        if self._process is None or not qprocess_is_running(self._process):
            self.retry_now()
        elif self._applied_package_path and self._session_established:
            self._activate_applied()
            if self._applied_package_identity != self._desired_package_identity:
                self._request_resident_package_load()
        else:
            self._request_resident_package_load()

    def retry_now(self) -> None:
        if self._closed or not self._visible:
            return
        if self._invalid_retry_package_path:
            self.load_package(
                self._invalid_retry_package_path,
                self._invalid_retry_status_path or None,
                reset_view=self._invalid_retry_reset_view,
                force_reload=True,
            )
            return
        if self._desired_package is None:
            return
        self._retry_timer.stop()
        if self._process is not None and qprocess_is_running(self._process):
            if self._can_send_protocol():
                self._request_resident_package_load()
            return
        self._launch_if_needed()

    def remember_state(self, key: str, event: str, payload: Mapping[str, object]) -> bool:
        normalized_key = str(key or event).strip().lower()
        body = dict(payload)
        body.pop("event", None)
        self._resident_state[normalized_key] = (str(event), body)
        if self._session_established and self._renderer_ready:
            return self.send_correlated(event, body) > 0
        return True

    def forget_state(self, key: str) -> None:
        self._resident_state.pop(str(key or "").strip().lower(), None)

    def send_correlated(self, event: str, payload: Mapping[str, object] | None = None) -> int:
        if not self._session_established:
            return 0
        self._protocol_request_id += 1
        request_id = self._protocol_request_id
        message = dict(payload or {})
        message.update(
            {
                "event": str(event),
                "session_id": self._session_id,
                "request_id": request_id,
                "base_revision": 0,
                "revision": 0,
                "edit_revision": 0,
                "process_generation": self._process_generation,
                "protocol_version": 2,
            }
        )
        return request_id if self._send_json(message) else 0

    def request_capture(self, output_path: Path | str, *, width: int = 512, height: int = 512) -> bool:
        package = self._desired_package
        if package is None or not self._session_established:
            return False
        capture_dir = package.output_dir / "captures"
        try:
            capture_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        internal_path = capture_dir / f"capture_{self._protocol_request_id + 1:08d}.png"
        request_id = self.send_correlated(
            "capture_request",
            {
                "output_path": str(internal_path),
                "width": max(64, min(2048, int(width))),
                "height": max(64, min(2048, int(height))),
            },
        )
        if request_id <= 0:
            return False
        self._pending_captures[request_id] = (internal_path, Path(output_path).expanduser())
        return True

    def hold_package_lease(self, package_dir: Path | str) -> bool:
        before = len(self._package_leases)
        self._hold_package_lease(Path(package_dir))
        return len(self._package_leases) > before or self._package_key(package_dir) in self._package_leases

    def release_package_lease(self, package_dir: Path | str) -> None:
        self._release_package_lease(package_dir)

    def retain_package_lease(self, package_dir: Path | str) -> None:
        self._retain_package_leases({str(package_dir)})

    def release_package_leases(self) -> None:
        self._release_package_leases()

    def deactivate(self) -> None:
        self.set_visible(False)

    def activate(self) -> None:
        self.set_visible(True)

    def close(self) -> None:
        if self._closed:
            return
        if not self._terminate_on_close:
            self.deactivate()
            return
        self.shutdown()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._retry_timer.stop()
        self._ready_timer.stop()
        self._package_timer.stop()
        self._pending_package_generation = 0
        process = self._process
        self._process = None
        if process is not None:
            self._send_json_to_process(process, {"event": "close_request"})
            stop_qprocess_async(process)
        self._release_package_leases()
        self._pending_captures.clear()
        self._clear_prewarm_capture()
        self._prewarm_package = None
        self._launch_is_prewarm = False
        self._set_state("closed", ".NET/Vortice Preview closed.")

    def _launch_if_needed(self) -> None:
        package = self._desired_package or self._prewarm_package
        prewarm_launch = self._desired_package is None and self._prewarm_package is not None
        if self._closed or package is None or (not self._visible and not prewarm_launch):
            return
        if self._process is not None and qprocess_is_running(self._process):
            return
        parent_hwnd = self._safe_host_hwnd()
        if parent_hwnd <= 0:
            self._schedule_retry("Preview host window is not ready.", static_failure=False)
            return
        resolution = resolve_mesh_dotnet_experiment_editor(self._configured_executable)
        executable = Path(resolution.resolved_path).expanduser() if resolution.resolved_path else Path()
        require_manifest = bool(getattr(sys, "frozen", False) or (executable.parent / "cdmw-mesh-dotnet-editor.manifest.json").is_file())
        required_capabilities = self._required_protocol_capabilities()
        blockers = mesh_dotnet_helper_static_provenance_blockers(
            executable,
            require_manifest=require_manifest,
            required_capabilities=required_capabilities,
        )
        if blockers:
            self._schedule_retry(
                ".NET/Vortice helper was not executed: " + "; ".join(blockers),
                static_failure=True,
            )
            return
        try:
            program, arguments = mesh_dotnet_experiment_command(
                executable,
                package,
                embedded_parent_hwnd=parent_hwnd,
                profile=self.profile.value,
            )
        except (OSError, TypeError, ValueError) as exc:
            self._schedule_retry(f"Could not configure .NET/Vortice Preview: {exc}", static_failure=False)
            return

        process = self._process_factory(self)
        self._process_generation += 1
        generation = self._process_generation
        self._launch_package_generation = self._package_generation
        self._launch_package_path = str(package.package_dir)
        self._launch_is_prewarm = prewarm_launch
        self._process = process
        self._executable = Path(program)
        self._protocol_ready = False
        self._renderer_ready = False
        self._session_established = False
        self._pending_package_generation = 0
        self._active = False
        self._capabilities.clear()
        self._clear_prewarm_capture()
        self._stdout_buffer = b""
        self._stdout_tail = ""
        self._stderr_tail = ""
        try:
            process.setProgram(program)
            process.setArguments(arguments)
            process.setWorkingDirectory(str(package.package_dir))
            process.setProcessChannelMode(QProcess.SeparateChannels)
            process.readyReadStandardOutput.connect(
                lambda target=process, token=generation: self._read_stdout(target, token)
            )
            process.readyReadStandardError.connect(
                lambda target=process, token=generation: self._read_stderr(target, token)
            )
            process.started.connect(lambda target=process, token=generation: self._process_started(target, token))
            process.finished.connect(
                lambda exit_code=0, exit_status=0, target=process, token=generation: self._process_finished(
                    target, token, int(exit_code), exit_status
                )
            )
            process.errorOccurred.connect(
                lambda error, target=process, token=generation: self._process_error(target, token, error)
            )
            process.start()
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            if self._process is process:
                self._process = None
            stop_qprocess_async(process)
            self._schedule_retry(f".NET/Vortice Preview launch failed: {exc}", static_failure=False)
            return
        self._ready_timer.start(_READY_TIMEOUT_MS)
        self._set_state("launching", ".NET/Vortice Preview is starting…")

    def _process_started(self, process: object, generation: int) -> None:
        if not self._is_current_process(process, generation):
            return
        self._set_state("connecting", ".NET/Vortice Preview is connecting…")

    def _process_finished(self, process: object, generation: int, exit_code: int, exit_status: object) -> None:
        if not self._is_current_process(process, generation):
            self._delete_process_later(process)
            return
        self._read_stdout(process, generation)
        self._read_stderr(process, generation)
        self._process = None
        self._ready_timer.stop()
        self._package_timer.stop()
        self._pending_package_generation = 0
        self._protocol_ready = False
        self._renderer_ready = False
        self._session_established = False
        self._clear_prewarm_capture()
        self._active = False
        self._prewarm_package = None
        self._launch_is_prewarm = False
        self._delete_process_later(process)
        self._retain_package_leases({self.desired_package_path})
        if not self._closed and self._visible and self._desired_package is not None:
            details = self._stderr_tail.strip() or self._stdout_tail.strip()
            suffix = f" ({details[-400:]})" if details else ""
            self._schedule_retry(
                f".NET/Vortice Preview exited with code {exit_code}{suffix}",
                static_failure=False,
            )

    def _process_error(self, process: object, generation: int, error: object) -> None:
        if not self._is_current_process(process, generation):
            return
        try:
            detail = str(process.errorString() or error)
        except (AttributeError, RuntimeError):
            detail = str(error)
        if not qprocess_is_running(process):
            self._fail_current_process(f".NET/Vortice Preview process error: {detail}", static_failure=False)

    def _read_stdout(self, process: object, generation: int) -> None:
        if not self._is_current_process(process, generation):
            return
        try:
            chunk = bytes(process.readAllStandardOutput())
        except (AttributeError, RuntimeError, TypeError):
            return
        if not chunk:
            return
        self._stdout_tail = append_bounded_text(self._stdout_tail, chunk.decode("utf-8", errors="replace"))
        self._stdout_buffer += chunk
        if len(self._stdout_buffer) > DOTNET_PROTOCOL_BUFFER_LIMIT:
            self._fail_current_process(".NET/Vortice protocol buffer exceeded its safety limit.", static_failure=False)
            return
        while b"\n" in self._stdout_buffer:
            raw_line, self._stdout_buffer = self._stdout_buffer.split(b"\n", 1)
            if len(raw_line) > DOTNET_PROTOCOL_LINE_LIMIT:
                self._fail_current_process(".NET/Vortice protocol line exceeded its safety limit.", static_failure=False)
                return
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            if isinstance(payload, Mapping):
                self._handle_protocol_event(dict(payload), generation)

    def _read_stderr(self, process: object, generation: int) -> None:
        if not self._is_current_process(process, generation):
            return
        try:
            chunk = bytes(process.readAllStandardError()).decode("utf-8", errors="replace")
        except (AttributeError, RuntimeError, TypeError):
            return
        if chunk:
            self._stderr_tail = append_bounded_text(self._stderr_tail, chunk)

    def _handle_protocol_event(self, payload: dict[str, object], generation: int) -> None:
        if generation != self._process_generation:
            return
        event = str(payload.get("event", payload.get("type", "")) or "").strip().lower()
        if not event:
            return
        if event == "ready":
            if not self._handle_renderer_ready(payload):
                return
            self._last_event = dict(payload)
            self.protocol_event.emit(dict(payload))
            return
        self._last_event = dict(payload)
        self.protocol_event.emit(dict(payload))
        if event == "protocol_ready":
            self._handle_protocol_ready(payload)
        elif event == "preview_session_state_ack":
            if str(payload.get("status", "") or "").lower() == "applied" and self._event_process_matches(payload):
                self._session_established = True
                self._maybe_finish_launch()
        elif event == "package_load_applied":
            self._handle_package_applied(payload)
        elif event == "package_load_failed":
            self._handle_package_failed(payload)
        elif event == "view_state_changed":
            self.view_state_changed.emit(dict(payload))
        elif event == "part_pick_result":
            self.part_pick_result.emit(dict(payload))
        elif event == "capture_result":
            self._handle_capture_result(payload)
        elif event == "activated":
            self._active = True
            self._retry_attempt = 0
            self._set_state("ready", ".NET/Vortice Preview")
        elif event == "deactivated":
            self._active = False
        elif event == "error":
            # Helper-level request errors (invalid tool state, stale sessions,
            # malformed commands, and similar protocol rejections) do not
            # imply that the process or D3D device is unhealthy. Consumers get
            # the original event above and can offer a retry without discarding
            # the resident scene. An actual helper exit or QProcess/device
            # failure still follows the process retry path.
            return

    def _handle_protocol_ready(self, payload: Mapping[str, object]) -> None:
        if str(payload.get("profile", "") or "").strip().lower() != self.profile.value:
            self._fail_current_process(".NET/Vortice helper started with the wrong profile.", static_failure=True)
            return
        manifest_path = self._executable.parent / "cdmw-mesh-dotnet-editor.manifest.json"
        blockers = mesh_dotnet_helper_provenance_blockers(
            self._executable,
            payload,
            require_manifest=bool(getattr(sys, "frozen", False) or manifest_path.is_file()),
            required_capabilities=self._required_protocol_capabilities(),
        )
        if blockers:
            self._fail_current_process(
                ".NET/Vortice helper provenance blocked: " + "; ".join(blockers),
                static_failure=True,
            )
            return
        raw_capabilities = payload.get("capabilities", ())
        if isinstance(raw_capabilities, Sequence) and not isinstance(raw_capabilities, (str, bytes)):
            self._capabilities = {str(value) for value in raw_capabilities}
        self._protocol_ready = True
        if self.profile is DotNetPreviewProfile.PREVIEW:
            sent = self._send_json(
                {
                    "event": "preview_session_state",
                    "session_id": self._session_id,
                    "process_generation": self._process_generation,
                    "protocol_version": 2,
                }
            )
            if not sent:
                self._fail_current_process("Could not establish the preview session.", static_failure=False)
        else:
            sent = self._send_json(
                {
                    "event": "session_state",
                    "session_id": self._session_id,
                    "process_generation": self._process_generation,
                    "protocol_version": 2,
                    "revision": 0,
                    "edit_revision": 0,
                    "history": {"undo": [], "redo": []},
                    "selection": {},
                }
            )
            self._session_established = bool(sent)
            if not sent:
                self._fail_current_process("Could not establish the authoring session.", static_failure=False)
                return
            self._maybe_finish_launch()

    def _handle_renderer_ready(self, payload: Mapping[str, object]) -> bool:
        if self._renderer_ready:
            return False
        if str(payload.get("profile", "") or "").strip().lower() != self.profile.value:
            self._fail_current_process(".NET/Vortice renderer reported the wrong profile.", static_failure=True)
            return False
        blockers = mesh_dotnet_renderer_blockers(
            payload,
            embedded=True,
        )
        if blockers:
            self._fail_current_process(
                ".NET/Vortice renderer was rejected: " + "; ".join(blockers),
                static_failure=False,
            )
            return False
        self._renderer_ready = True
        self._ready_timer.stop()
        self.renderer_ready.emit(dict(payload))
        self._maybe_finish_launch()
        return True

    def _maybe_finish_launch(self) -> None:
        if (
            self._launch_is_prewarm
            and self._protocol_ready
            and self._session_established
            and not self._renderer_ready
        ):
            # A hidden embedded HWND cannot present its first frame yet. The
            # helper and D3D device are nevertheless resident after the
            # protocol/session handshake, so keep them alive until a real
            # request makes the host visible and the correlated Ready arrives.
            self._request_prewarm_capture()
            if self._visible and self._desired_package is not None:
                if not self._request_resident_package_load():
                    self._activate_prewarm()
            else:
                self._ready_timer.stop()
                self._set_state("prewarmed", ".NET/Vortice Preview is ready for a model.")
            return
        if not (self._protocol_ready and self._renderer_ready and self._session_established):
            return
        if self._launch_is_prewarm:
            self._launch_is_prewarm = False
            if self._desired_package is not None:
                self._request_resident_package_load()
            else:
                self._send_json({"event": "deactivate_request"})
                self._active = False
                self._set_state("prewarmed", ".NET/Vortice Preview is ready for a model.")
            return
        if (
            self._launch_package_generation != self._package_generation
            or self._launch_package_path != self.desired_package_path
        ):
            self._request_resident_package_load()
            return
        self._accept_applied_package(self._launch_package_path, self._launch_package_generation)

    def _request_resident_package_load(self) -> bool:
        package = self._desired_package
        if package is None or not self._can_send_protocol():
            return False
        if not (self._protocol_ready and self._session_established):
            return False
        if not self._renderer_ready and not self._launch_is_prewarm:
            return False
        if (
            self._applied_package_path == self.desired_package_path
            and self._applied_package_generation == self._package_generation
        ):
            return True
        if (
            self._pending_package_generation == self._package_generation
            and self._package_timer.isActive()
        ):
            return True
        self._package_request_id += 1
        request_id = self._package_request_id
        generation = self._package_generation
        sent = self._send_json(
            {
                "event": "package_load_request",
                "request_id": request_id,
                "generation": generation,
                "package_path": str(package.package_dir),
            }
        )
        if sent:
            self._pending_package_generation = generation
            self._package_timer.start(_PACKAGE_TIMEOUT_MS)
            self._set_state("preparing", ".NET/Vortice Preview is loading the selected model…")
        return sent

    def _handle_package_applied(self, payload: Mapping[str, object]) -> None:
        if not self._package_event_is_current(payload):
            return
        self._package_timer.stop()
        self._pending_package_generation = 0
        self._accept_applied_package(self.desired_package_path, self._package_generation)

    def _handle_package_failed(self, payload: Mapping[str, object]) -> None:
        if not self._package_event_is_current(payload):
            return
        message = str(payload.get("message", payload.get("reason", "Package load failed.")) or "Package load failed.")
        self._fail_current_package(message)

    def _accept_applied_package(self, package_path: str, generation: int) -> None:
        if generation != self._package_generation or package_path != self.desired_package_path:
            return
        self._applied_package_path = package_path
        self._applied_package_generation = generation
        self._applied_package = self._desired_package
        self._applied_package_identity = self._desired_package_identity
        self._retain_package_leases({package_path})
        self._replay_resident_state()
        if self.profile is DotNetPreviewProfile.AUTHORING:
            self.rehydrate_requested.emit(self._process_generation)
            if self._authoring_rehydrator is not None:
                try:
                    if not bool(self._authoring_rehydrator(self)):
                        self._fail_current_process(
                            "Authoritative Mesh Editor state could not be restored.",
                            static_failure=False,
                        )
                        return
                except Exception as exc:
                    self._fail_current_process(
                        f"Authoritative Mesh Editor state restore failed: {exc}",
                        static_failure=False,
                    )
                    return
        self.package_applied.emit(package_path, generation)
        if self._visible:
            self._activate()

    def _replay_resident_state(self) -> None:
        for _key, (event, payload) in tuple(self._resident_state.items()):
            self.send_correlated(event, payload)

    def _activate(self) -> bool:
        if not self._visible or self._applied_package_path != self.desired_package_path:
            return False
        return self._send_json(
            {
                "event": "activate_request",
                "material_signature": str(getattr(self._desired_package, "material_signature", "") or ""),
            }
        )

    def _activate_applied(self) -> bool:
        if not self._visible or not self._applied_package_path:
            return False
        return self._send_json(
            {
                "event": "activate_request",
                "material_signature": str(
                    getattr(self._applied_package, "material_signature", "") or ""
                ),
            }
        )

    def _activate_prewarm(self) -> bool:
        package = self._prewarm_package
        if (
            not self._visible
            or package is None
            or not self._launch_is_prewarm
            or not self._protocol_ready
            or not self._session_established
        ):
            return False
        sent = self._send_json(
            {
                "event": "activate_request",
                "material_signature": str(getattr(package, "material_signature", "") or ""),
            }
        )
        if sent:
            self._ready_timer.start(_READY_TIMEOUT_MS)
            self._set_state("preparing", ".NET/Vortice Preview is activating the resident rendererâ€¦")
        return sent

    def _deactivate_for_replacement(self) -> None:
        if self._process is not None and qprocess_is_running(self._process):
            self._send_json({"event": "deactivate_request"})
        self._active = False

    def _handle_capture_result(self, payload: Mapping[str, object]) -> None:
        try:
            request_id = int(payload.get("request_id", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            request_id = 0
        if request_id == self._prewarm_capture_request_id:
            self._clear_prewarm_capture()
            if str(payload.get("status", "") or "").strip().lower() == "captured":
                self._set_state("prewarmed", ".NET/Vortice Preview is GPU-warmed and ready for a model.")
            self.capture_completed.emit(dict(payload))
            return
        paths = self._pending_captures.pop(request_id, None)
        result = dict(payload)
        if paths is not None:
            internal_path, target_path = paths
            ok = str(payload.get("status", "") or "").lower() == "captured" and internal_path.is_file()
            if ok:
                try:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    atomic_copy_file(internal_path, target_path)
                    result["requested_output_path"] = str(target_path)
                except OSError as exc:
                    result["status"] = "error"
                    result["message"] = f"Could not publish capture: {exc}"
            try:
                internal_path.unlink(missing_ok=True)
            except OSError:
                pass
        self.capture_completed.emit(result)

    def _request_prewarm_capture(self) -> bool:
        package = self._prewarm_package
        if package is None or not self._session_established:
            return False
        if self._prewarm_capture_request_id > 0:
            return True
        capture_dir = package.output_dir / "captures"
        try:
            capture_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        capture_path = capture_dir / f"prewarm_{self._process_generation:08d}.png"
        request_id = self.send_correlated(
            "capture_request",
            {
                "output_path": str(capture_path),
                "width": 64,
                "height": 64,
            },
        )
        if request_id <= 0:
            return False
        self._prewarm_capture_request_id = request_id
        self._prewarm_capture_path = capture_path
        return True

    def _clear_prewarm_capture(self) -> None:
        capture_path = self._prewarm_capture_path
        self._prewarm_capture_request_id = 0
        self._prewarm_capture_path = None
        if capture_path is None:
            return
        try:
            capture_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _handle_ready_timeout(self) -> None:
        self._fail_current_process(".NET/Vortice Preview did not become ready in time.", static_failure=False)

    def _handle_package_timeout(self) -> None:
        self._fail_current_package("Package replacement timed out.")

    def _fail_current_package(self, message: str) -> None:
        self._package_timer.stop()
        self._pending_package_generation = 0
        detail = str(message or "Package load failed.")
        self.package_failed.emit(self.desired_package_path, self._package_generation, detail)
        self._set_state(
            "package_error",
            f".NET/Vortice package load failed: {detail} The current model was kept; retry when ready.",
        )

    def _fail_current_process(self, reason: str, *, static_failure: bool) -> None:
        process = self._process
        self._process = None
        self._ready_timer.stop()
        self._package_timer.stop()
        self._protocol_ready = False
        self._renderer_ready = False
        self._session_established = False
        self._pending_package_generation = 0
        self._clear_prewarm_capture()
        self._active = False
        self._prewarm_package = None
        self._launch_is_prewarm = False
        if process is not None:
            stop_qprocess_async(process)
        self._retain_package_leases({self.desired_package_path})
        self._schedule_retry(reason, static_failure=static_failure)

    def _schedule_retry(self, reason: str, *, static_failure: bool) -> None:
        self._retry_reason = str(reason or ".NET/Vortice Preview is unavailable.")
        if self._desired_package is None and self._prewarm_package is not None:
            prewarm_path = str(self._prewarm_package.package_dir)
            self._prewarm_package = None
            self._launch_is_prewarm = False
            self._release_package_lease(prewarm_path)
        if self._closed or not self._visible or self._desired_package is None:
            self._set_state("inactive", self._retry_reason)
            return
        if static_failure:
            delay_ms = _STATIC_RETRY_DELAY_MS
        else:
            index = min(self._retry_attempt, len(_TRANSIENT_RETRY_DELAYS_MS))
            delay_ms = (
                _TRANSIENT_RETRY_DELAYS_MS[index]
                if index < len(_TRANSIENT_RETRY_DELAYS_MS)
                else _STEADY_RETRY_DELAY_MS
            )
            self._retry_attempt += 1
        self._retry_timer.start(delay_ms)
        self._set_state("retrying", f"{self._retry_reason} Retrying automatically.")

    def _required_protocol_capabilities(self) -> tuple[str, ...]:
        profile_capabilities = (
            _PREVIEW_PROTOCOL_CAPABILITIES
            if self.profile is DotNetPreviewProfile.PREVIEW
            else _AUTHORING_PROTOCOL_CAPABILITIES
        )
        return (*_BASE_PROTOCOL_CAPABILITIES, *profile_capabilities)

    def _send_json(self, payload: Mapping[str, object]) -> bool:
        process = self._process
        return process is not None and self._send_json_to_process(process, payload)

    @staticmethod
    def _send_json_to_process(process: object, payload: Mapping[str, object]) -> bool:
        if not qprocess_is_running(process):
            return False
        try:
            data = (json.dumps(dict(payload), separators=(",", ":"), default=str) + "\n").encode("utf-8")
            return int(process.write(data)) == len(data)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False

    def _can_send_protocol(self) -> bool:
        return self._process is not None and qprocess_is_running(self._process)

    def _safe_host_hwnd(self) -> int:
        try:
            return max(0, int(self._host_hwnd() or 0))
        except (RuntimeError, TypeError, ValueError):
            return 0

    def _event_process_matches(self, payload: Mapping[str, object]) -> bool:
        try:
            return int(payload.get("process_generation", 0) or 0) == self._process_generation
        except (TypeError, ValueError, OverflowError):
            return False

    def _package_event_is_current(self, payload: Mapping[str, object]) -> bool:
        try:
            request_id = int(payload.get("request_id", 0) or 0)
            generation = int(payload.get("generation", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            return False
        return request_id == self._package_request_id and generation == self._package_generation

    def _is_current_process(self, process: object, generation: int) -> bool:
        return self._process is process and generation == self._process_generation

    @staticmethod
    def _delete_process_later(process: object) -> None:
        try:
            process.deleteLater()
        except (AttributeError, RuntimeError):
            pass

    @staticmethod
    def _package_key(package_dir: Path | str) -> str:
        try:
            return str(Path(package_dir).expanduser().resolve()).casefold()
        except OSError:
            return str(package_dir).casefold()

    @classmethod
    def _package_identity(
        cls,
        package: MeshDotNetExperimentPackage,
    ) -> tuple[str, str, str]:
        scene_signature = ""
        scene_path = getattr(package, "scene_manifest_path", None)
        if scene_path:
            try:
                scene_signature = hashlib.sha256(Path(scene_path).read_bytes()).hexdigest()
            except OSError:
                scene_signature = str(scene_path)
        return (
            cls._package_key(package.package_dir),
            str(getattr(package, "material_signature", "") or ""),
            scene_signature,
        )

    def _hold_package_lease(self, package_dir: Path) -> None:
        key = self._package_key(package_dir)
        if key in self._package_leases:
            return
        lease = acquire_dotnet_preview_package_cache_lease_for_path(Path(package_dir))
        if lease is not None:
            self._package_leases[key] = lease

    def _release_package_lease(self, package_dir: Path | str) -> None:
        lease = self._package_leases.pop(self._package_key(package_dir), None)
        release = getattr(lease, "release", None)
        if callable(release):
            release()

    def _retain_package_leases(self, package_paths: set[str]) -> None:
        keep = {self._package_key(path) for path in package_paths if path}
        for key, lease in tuple(self._package_leases.items()):
            if key in keep:
                continue
            self._package_leases.pop(key, None)
            release = getattr(lease, "release", None)
            if callable(release):
                release()

    def _release_package_leases(self) -> None:
        leases = tuple(self._package_leases.values())
        self._package_leases.clear()
        for lease in leases:
            release = getattr(lease, "release", None)
            if callable(release):
                release()

    def _set_state(self, state: str, message: str) -> None:
        self.state_changed.emit(str(state), str(message))


__all__ = ["DotNetPreviewSessionController"]
