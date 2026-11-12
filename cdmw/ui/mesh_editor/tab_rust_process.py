"""Rust Mesh Editor process protocol, diagnostics, and shutdown."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from importlib import import_module
from pathlib import Path

import shiboken6
from PySide6.QtCore import QCoreApplication, QProcess, QProcessEnvironment, QThread, QTimer

from cdmw.services.mesh_rust_contract import (
    RUST_MESH_EDIT_BACKEND,
    RUST_MESH_EDITOR_PROTOCOL,
    RUST_MESH_RENDERER,
    RUST_UI_TRANSLATION_PARTS_CAPABILITY,
)
from cdmw.ui.mesh_editor.process_io import (
    DOTNET_PROTOCOL_BUFFER_LIMIT,
    DOTNET_PROTOCOL_EVENT_LIMIT,
    DOTNET_PROTOCOL_LINE_LIMIT,
    append_bounded_text,
    qprocess_is_running,
    register_owned_qprocess_for_exit,
    stop_qprocess_async,
    unregister_owned_qprocess_for_exit,
)
from cdmw.ui.mesh_editor.rust_theme_transport import protocol_line, rust_theme_digest

_RUST_PROTOCOL_QUEUE_LIMIT = 128
_RUST_READY_TIMEOUT_MS = 10_000
_RUST_RENDERER_READY_TIMEOUT_MS = 60_000
_RUST_FINISH_EXIT_TIMEOUT_MS = 3_000
_RUST_DIAGNOSTIC_BUFFER_LIMIT = 16 * 1024
_RUST_DIAGNOSTIC_TEXT_LIMIT = 2 * 1024
_RUST_DIAGNOSTIC_LINE_LIMIT = 8
#: A new spare starts this long after a session became ready, as the dialog spare refills.
_RUST_SPARE_REFILL_MS = 5_000
#: "0" turns the pre-started Mesh Editor helper off (tests that count launches do).
EDITOR_SPARE_ENV = "CDMW_EDITOR_SPARE"


def editor_spare_enabled() -> bool:
    return os.environ.get(EDITOR_SPARE_ENV, "1").strip() != "0"


class _RustEditorSpare:
    """One Mesh Editor helper started before it is needed (``--cdmw-session-pending``).

    It creates its window, GPU device and pipelines, says ``pending_ready`` and waits
    for ``open_session``. The tab adopts it when it opens a session with the same
    executable and host window, and it is never more than one. A spare that exits
    or fails before it is adopted is dropped; the open then launches as before.
    """

    def __init__(self) -> None:
        self.process: QProcess | None = None
        self.state = "idle"  # idle, starting, pending
        self.executable: Path | None = None
        self.signature = ""
        self.parent_hwnd = 0
        self.announcement: dict = {}
        self.started_at = 0.0
        self.pending_at = 0.0
        self._buffer = b""
        self._waiting: tuple[Callable, Callable] | None = None

    def matches(self, executable: Path | None, signature: str, parent_hwnd: int) -> bool:
        return (
            self.process is not None
            and self.state in {"starting", "pending"}
            and executable is not None
            and self.executable == Path(executable)
            and self.signature == signature
            and self.parent_hwnd == int(parent_hwnd)
        )

    def start(self, process: QProcess, executable: Path, signature: str, parent_hwnd: int,
              *, arguments_prefix: tuple[str, ...] = ()) -> None:
        """``arguments_prefix`` lets a test run a stand-in helper script with its interpreter."""

        self.release()
        self.process, self.state = process, "starting"
        self.executable, self.signature, self.parent_hwnd = Path(executable), signature, int(parent_hwnd)
        self.announcement, self._buffer, self._waiting = {}, b"", None
        self.started_at, self.pending_at = time.perf_counter(), 0.0
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.setProgram(str(executable))
        process.setArguments([*arguments_prefix, "--cdmw-session-pending",
                              "--embedded-parent-hwnd", str(int(parent_hwnd))])
        process.setWorkingDirectory(str(Path(executable).parent))
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("WGPU_BACKEND", "dx12")
        environment.insert("RUST_BACKTRACE", "full")
        process.setProcessEnvironment(environment)
        process.readyReadStandardOutput.connect(self._read)
        process.readyReadStandardError.connect(self._drain_stderr)
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._error)
        register_owned_qprocess_for_exit(process)
        process.start()

    def adopt(self, on_ready: Callable[[QProcess, dict], None], on_failed: Callable[[], None]) -> bool:
        """Hand the helper over now, or as soon as it says ``pending_ready``."""

        if self.process is None or self.state not in {"starting", "pending"}:
            return False
        self._waiting = (on_ready, on_failed)
        if self.state == "pending":
            self._hand_over()
        return True

    def release(self) -> None:
        process, waiting = self.process, self._waiting
        self._reset()
        if process is not None:
            self._disconnect(process)
            stop_qprocess_async(process)
        if waiting is not None:
            waiting[1]()

    def _reset(self) -> None:
        self.process, self.state, self._waiting, self._buffer = None, "idle", None, b""

    def _disconnect(self, process: QProcess) -> None:
        for signal, slot in (
            (process.readyReadStandardOutput, self._read),
            (process.readyReadStandardError, self._drain_stderr),
            (process.finished, self._finished),
            (process.errorOccurred, self._error),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def _hand_over(self) -> None:
        process, announcement, (on_ready, _on_failed) = self.process, self.announcement, self._waiting
        self._disconnect(process)
        self._reset()
        on_ready(process, announcement)

    def _read(self) -> None:
        if self.process is None:
            return
        try:
            data = self._buffer + bytes(self.process.readAllStandardOutput())
        except RuntimeError:
            return
        while self.state == "starting" and (end := data.find(b"\n")) >= 0:
            line, data = data[:end].rstrip(b"\r"), data[end + 1:]
            try:
                payload = json.loads(line.decode("utf-8", errors="replace")) if line else {}
            except ValueError:
                payload = {}
            event = payload.get("event") if isinstance(payload, dict) else None
            if event == "pending_ready" and payload.get("protocol") == RUST_MESH_EDITOR_PROTOCOL:
                self.state, self.announcement, self.pending_at = "pending", payload, time.perf_counter()
            elif event is not None:
                # pending_failed or anything unexpected: this helper is not usable.
                self.release()
                return
        self._buffer = data[-DOTNET_PROTOCOL_BUFFER_LIMIT:]
        if self.state == "pending" and self._waiting is not None:
            self._hand_over()

    def _drain_stderr(self) -> None:
        try:
            if self.process is not None:
                self.process.readAllStandardError()
        except RuntimeError:
            pass

    def _finished(self, *_args) -> None:
        self.release()

    def _error(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.release()


def _rust_stderr_failure_marker(line: str) -> bool:
    lowered = str(line or "").strip().lower()
    return (
        "panicked at" in lowered
        or lowered.startswith("error")
        or lowered.startswith("fatal")
        or " error " in f" {lowered} "
    )


def _rust_stderr_backtrace_start(line: str) -> bool:
    lowered = str(line or "").strip().lower()
    return lowered in {"backtrace:", "stack backtrace:"}


def _rust_stderr_backtrace_note(line: str) -> bool:
    lowered = str(line or "").strip().lower()
    return (
        lowered.startswith("note: some details are omitted")
        or lowered.startswith("note: run with `rust_backtrace=")
        or lowered.startswith("note: run with rust_backtrace=")
    )


class MeshEditorRustProcessMixin:
    def _hair_start_options(self):
        pending = getattr(self, "_pending_hair_start", None)
        self._pending_hair_start = None
        target = self._current_target_entry()
        if pending and target is not None and pending[0] == target.identity:
            return {"hair_start_mode": pending[1]}
        return {}

    def _launch_rust_editor_process(self, session: object) -> None:
        executable = self.standalone_rust_executable_path
        resolution = self._rust_executable_resolution()
        (
            resolved_text,
            executable_signature,
            incompatibility_reason,
        ) = self._validate_rust_executable_resolution(resolution)
        resolved_path = Path(resolved_text) if resolved_text else None
        if incompatibility_reason:
            self.standalone_rust_checked_executable = resolved_text
            self.standalone_rust_checked_executable_signature = executable_signature
            self.standalone_rust_incompatible_reason = incompatibility_reason
            self._fail_rust_editor(
                f"Mesh Editor unavailable before launch: {incompatibility_reason}"
            )
            return
        if (
            executable is None
            or resolved_path is None
            or resolved_path.resolve() != executable.resolve()
            or executable_signature
            != self.standalone_rust_launch_executable_signature
        ):
            self._fail_rust_editor(
                "The Mesh Editor executable package changed while its shadow session was being prepared. "
                "Open the mesh again to use the newly validated package.",
                incompatible=True,
            )
            return
        host = getattr(self, "standalone_native_host_frame", None)
        prepare_launch = getattr(host, "prepare_launch", None)
        parent_hwnd = int(prepare_launch() or 0) if callable(prepare_launch) else 0
        if parent_hwnd <= 0:
            self._fail_rust_editor(
                "Mesh Editor could not create its embedded native host window.",
                incompatible=True,
            )
            return
        self.standalone_rust_launch_parent_hwnd = parent_hwnd
        spare = getattr(self, "_rust_spare", None)
        if editor_spare_enabled() and spare is not None and spare.matches(
            executable, executable_signature, parent_hwnd
        ):
            token = object()
            self._rust_spare_adoption = token

            def ready(process: QProcess, _announcement: dict, *, current: object = token) -> None:
                if getattr(self, "_rust_spare_adoption", None) is not current or (
                    self.standalone_rust_process is not None
                ):
                    stop_qprocess_async(process)  # the open was cancelled while it waited
                    return
                self._rust_spare_adoption = None
                self._adopt_rust_editor_process(process, session)

            def failed(*, current: object = token) -> None:
                if getattr(self, "_rust_spare_adoption", None) is current:
                    self._rust_spare_adoption = None
                    self._launch_fresh_rust_editor_process(session, executable, parent_hwnd)

            if spare.adopt(ready, failed):
                self._set_rust_status("Opening the embedded Mesh Editor...")
                return
        self._launch_fresh_rust_editor_process(session, executable, parent_hwnd)

    def _launch_fresh_rust_editor_process(self, session: object, executable: Path, parent_hwnd: int) -> None:
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.setProgram(str(executable))
        process.setArguments(
            [
                "--cdmw-session",
                str(session.manifest_path),
                "--embedded-parent-hwnd",
                str(parent_hwnd),
            ]
        )
        process.setWorkingDirectory(str(executable.parent))
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("WGPU_BACKEND", "dx12")
        environment.insert("RUST_BACKTRACE", "full")
        process.setProcessEnvironment(environment)
        process.started.connect(lambda current=process: self._handle_rust_process_started(current))
        self._connect_rust_process_signals(process)
        self._take_rust_process(process, session)
        register_owned_qprocess_for_exit(process)
        self._set_rust_status("Launching the embedded Mesh Editor...")
        process.start()

    def _connect_rust_process_signals(self, process: QProcess) -> None:
        process.readyReadStandardOutput.connect(
            lambda current=process: self._handle_rust_stdout_ready(current)
        )
        process.readyReadStandardError.connect(
            lambda current=process: self._handle_rust_stderr_ready(current)
        )
        process.errorOccurred.connect(
            lambda error, current=process: self._handle_rust_process_error(current, error)
        )
        process.finished.connect(
            lambda code, status, current=process: self._handle_rust_process_finished(
                current, code, status
            )
        )

    def _take_rust_process(self, process: QProcess, session: object) -> None:
        self.standalone_rust_process = process
        self.standalone_rust_gpu_failed = False
        # Every launch starts from the manifest's theme; ready resends only a change.
        theme = getattr(session, "theme", None)
        self.standalone_rust_theme_digest = (
            rust_theme_digest(theme) if isinstance(theme, Mapping) else ""
        )

    def _adopt_rust_editor_process(self, process: QProcess, session: object) -> None:
        """Give a pre-started helper its session; it answers hello and ready as a launch does."""

        self._connect_rust_process_signals(process)
        self._take_rust_process(process, session)
        line = json.dumps({
            "event": "open_session",
            "protocol": RUST_MESH_EDITOR_PROTOCOL,
            "manifest": str(session.manifest_path),
        }, separators=(",", ":")).encode("utf-8") + b"\n"
        try:
            written = int(process.write(line))
        except RuntimeError:
            written = -1
        if written != len(line):
            self._fail_rust_editor("The pre-started Mesh Editor did not accept its session.")
            return
        self._handle_rust_process_started(process)
        # Output it wrote while it was being handed over is read now.
        if process.bytesAvailable():
            self._handle_rust_stdout_ready(process)

    def _rust_editor_spare(self) -> _RustEditorSpare:
        spare = getattr(self, "_rust_spare", None)
        if spare is None:
            spare = self._rust_spare = _RustEditorSpare()
            app = QCoreApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(spare.release)
        return spare

    def _ensure_rust_editor_spare(self, executable_text: str, executable_signature: str) -> None:
        """Start the one pending helper if none matching this executable and host is starting or waiting."""

        if not editor_spare_enabled() or not executable_text or not executable_signature:
            return
        host = getattr(self, "standalone_native_host_frame", None)
        host_hwnd = getattr(host, "host_hwnd", None)
        try:
            parent_hwnd = int(host_hwnd() or 0) if callable(host_hwnd) else 0
        except (RuntimeError, TypeError, ValueError):
            parent_hwnd = 0
        if parent_hwnd <= 0:
            return
        spare = self._rust_editor_spare()
        executable = Path(executable_text)
        if spare.matches(executable, executable_signature, parent_hwnd):
            return
        spare.start(QProcess(self), executable, executable_signature, parent_hwnd)

    def _refill_rust_editor_spare(self) -> None:
        if not shiboken6.isValid(self) or getattr(self, "standalone_rust_prepare_active_request_id", 0):
            return
        self._ensure_rust_editor_spare(
            str(getattr(self, "standalone_rust_checked_executable", "") or ""),
            str(getattr(self, "standalone_rust_checked_executable_signature", "") or ""),
        )

    def _handle_rust_process_started(self, process: QProcess) -> None:
        if process is not self.standalone_rust_process:
            return
        self.standalone_rust_ready_timer.start(_RUST_READY_TIMEOUT_MS)
        host = getattr(self, "standalone_native_host_frame", None)
        show_loading = getattr(host, "show_loading", None)
        if callable(show_loading):
            show_loading("Mesh Editor started; verifying its embedded child window...")
        self._set_rust_status("Mesh Editor started; waiting for its CDMW handshake...")

    def _handle_rust_stdout_ready(self, process: QProcess) -> None:
        if process is not self.standalone_rust_process:
            return
        try:
            chunk = bytes(process.readAllStandardOutput())
        except RuntimeError:
            return
        # Keep bytes until a whole message arrives: pipe reads can split UTF-8.
        # A burst of complete messages does not count against the residue limit.
        data, self.standalone_rust_stdout_buffer = self.standalone_rust_stdout_buffer + chunk, b""
        offset = 0
        while (end := data.find(b"\n", offset)) >= 0:
            line = data[offset:end]
            offset = end + 1
            if not line:
                continue
            if len(line) > DOTNET_PROTOCOL_LINE_LIMIT:
                self._fail_rust_editor("Mesh Editor sent an oversized protocol message.", incompatible=True)
                return
            line = line.rstrip(b"\r")
            if not line:
                continue
            try:
                payload = json.loads(line.decode("utf-8", errors="replace"))
            except ValueError:
                self._fail_rust_editor("Mesh Editor wrote non-JSON data to its control stream.", incompatible=True)
                return
            if not isinstance(payload, dict):
                self._fail_rust_editor("Mesh Editor protocol message was not an object.", incompatible=True)
                return
            self._handle_rust_protocol_event(payload)
            if process is not self.standalone_rust_process:
                return
        residue = data[offset:]
        if len(residue) > DOTNET_PROTOCOL_BUFFER_LIMIT:
            self._fail_rust_editor("Mesh Editor protocol buffer exceeded its limit.", incompatible=True)
            return
        self.standalone_rust_stdout_buffer = residue

    def _handle_rust_stderr_ready(self, process: QProcess) -> None:
        if process is not self.standalone_rust_process:
            return
        try:
            text = bytes(process.readAllStandardError()).decode("utf-8", errors="replace")
        except RuntimeError:
            return
        self.standalone_rust_stderr_tail = append_bounded_text(
            self.standalone_rust_stderr_tail,
            text,
        )
        self._record_rust_stderr_diagnostics(text)

    def _record_rust_stderr_diagnostics(self, text: str) -> None:
        pending = self.standalone_rust_stderr_partial + str(text or "")
        self.standalone_rust_stderr_partial = ""
        for segment in pending.splitlines(keepends=True):
            if segment.endswith(("\n", "\r")):
                self._record_rust_stderr_diagnostic_line(segment.rstrip("\r\n"))
            else:
                self.standalone_rust_stderr_partial = segment[
                    -_RUST_DIAGNOSTIC_BUFFER_LIMIT:
                ]

    def _record_rust_stderr_diagnostic_line(self, line: str) -> None:
        stripped = str(line or "").strip()
        if not stripped:
            return
        if _rust_stderr_failure_marker(stripped):
            self.standalone_rust_stderr_in_backtrace = False
        elif _rust_stderr_backtrace_start(stripped):
            self.standalone_rust_stderr_in_backtrace = True
            return
        elif self.standalone_rust_stderr_in_backtrace or _rust_stderr_backtrace_note(
            stripped
        ):
            return
        self.standalone_rust_stderr_diagnostic = append_bounded_text(
            self.standalone_rust_stderr_diagnostic,
            f"{stripped}\n",
            max_chars=_RUST_DIAGNOSTIC_BUFFER_LIMIT,
        )

    def _rust_process_diagnostic(self) -> str:
        lines = [
            line.strip()
            for line in self.standalone_rust_stderr_diagnostic.splitlines()
            if line.strip()
        ]
        partial = self.standalone_rust_stderr_partial.strip()
        if partial and (
            not self.standalone_rust_stderr_in_backtrace
            or _rust_stderr_failure_marker(partial)
        ):
            lines.append(partial)
        panic_indexes = [
            index
            for index, line in enumerate(lines)
            if "panicked at" in line.lower()
        ]
        marker_indexes = [
            index for index, line in enumerate(lines) if _rust_stderr_failure_marker(line)
        ]
        if panic_indexes or marker_indexes:
            start = (panic_indexes or marker_indexes)[-1]
            lines = lines[start : start + _RUST_DIAGNOSTIC_LINE_LIMIT]
        else:
            lines = lines[-min(3, _RUST_DIAGNOSTIC_LINE_LIMIT) :]
        diagnostic = " | ".join(
            line for line in lines if not _rust_stderr_backtrace_note(line)
        )
        if len(diagnostic) <= _RUST_DIAGNOSTIC_TEXT_LIMIT:
            return diagnostic
        # This punctuation is not a translatable phrase; constructing it keeps
        # the localization extractor from treating ``{value_0}…`` as a UI key.
        return diagnostic[: _RUST_DIAGNOSTIC_TEXT_LIMIT - 1].rstrip() + chr(0x2026)

    def _drain_rust_process_output(self, process: QProcess) -> None:
        # QProcess can emit finished/error before the final readyRead signals are
        # dispatched. Read both channels while this process is still authoritative.
        self._handle_rust_stderr_ready(process)
        self._handle_rust_stdout_ready(process)

    def _rust_process_diagnostic_suffix(self) -> str:
        diagnostic = self._rust_process_diagnostic()
        return f" Last diagnostic: {diagnostic}" if diagnostic else ""

    def _validate_rust_event_identity(self, payload: Mapping[str, object]) -> str:
        session = self.standalone_rust_authoring_session
        if session is None:
            raise ValueError("CDMW has no matching Rust shadow session")
        if str(payload.get("protocol", "") or "") != RUST_MESH_EDITOR_PROTOCOL:
            raise ValueError("protocol version does not match")
        if str(payload.get("session_id", "") or "") != session.session_id:
            raise ValueError("session id does not match")
        try:
            generation = int(payload.get("process_generation", 0) or 0)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("process generation is invalid") from exc
        if generation != self.standalone_rust_process_generation:
            raise ValueError("process generation is stale")
        return str(payload.get("event", "") or "").strip().lower()

    def _handle_rust_protocol_event(self, payload: dict[str, object]) -> None:
        try:
            event = self._validate_rust_event_identity(payload)
        except ValueError as exc:
            self._fail_rust_editor(f"Mesh Editor handshake failed: {exc}.", incompatible=True)
            return
        self.standalone_rust_protocol_events.append(dict(payload))
        del self.standalone_rust_protocol_events[:-DOTNET_PROTOCOL_EVENT_LIMIT]
        if self.standalone_rust_failure_reported:
            # Keep terminal diagnostics while the failed helper exits, but never
            # let its remaining replies reactivate rendering or enqueue edits.
            return
        if event == "hello":
            self._handle_rust_hello(payload)
            return
        if event == "ready":
            self._handle_rust_ready(payload)
            return
        if event == "app_shortcut":
            # A chord that belongs to CDMW, pressed with focus in the editor's window (P12).
            if str(payload.get("command", "") or "") == "command_palette":
                from cdmw.ui.commands.palette import open_command_palette

                try:
                    window = self.window()
                except (AttributeError, RuntimeError):
                    window = None
                if window is not None:
                    open_command_palette(window)
            return
        if event == "commands_state":
            self._mirror_rust_commands(payload.get("commands"))
            return
        if event == "state_snapshot":
            return
        if event == "switch_item_piece":
            index = payload.get("index")
            if (self.standalone_rust_ready and type(index) is int
                    and 0 < index < len(self.item_set_contexts)
                    and not self.standalone_rust_protocol_queue
                    and self.standalone_rust_protocol_worker is None):
                self.switch_item_piece_requested.emit(index)
            return
        if event == "layout_changed":
            from cdmw.services.mesh_editor_layout import save_mesh_layout
            from cdmw.ui.widgets import request_settings_sync

            if save_mesh_layout(self.settings, payload.get("layout")):
                request_settings_sync(self.settings)
            return
        if event == "preview_settings_changed":
            from cdmw.ui.preview.preview_settings_hub import preview_settings_hub

            hub = preview_settings_hub()
            settings = payload.get("settings")
            if hub is not None and isinstance(settings, Mapping):
                hub.update(**{str(key): value for key, value in settings.items()})
            return
        if event == "shortcuts_changed":
            from cdmw.services.mesh_editor_shortcuts import save_mesh_shortcuts
            from cdmw.ui.widgets import request_settings_sync

            if save_mesh_shortcuts(self.settings, payload.get("shortcuts")):
                request_settings_sync(self.settings)
            return
        if event in {"renderer_failed", "renderer_recovered"}:
            self.standalone_rust_gpu_failed = event == "renderer_failed"
            self.standalone_rust_ready_timer.stop()
            host = getattr(self, "standalone_native_host_frame", None)
            message = str(payload.get("message", "") or "")
            if self.standalone_rust_gpu_failed:
                if host is not None:
                    host.show_error(message)
            elif host is not None:
                host.show_editor()
            self._set_rust_status(message, error=self.standalone_rust_gpu_failed)
            return
        if event == "error":
            message = str(payload.get("message", "") or "Rust renderer reported an error")
            self._fail_rust_editor(message)
            return
        if event not in {"transaction_request", "command_request", "finish_request", "cancel", "vertex_inspect"}:
            self._fail_rust_editor(f"Mesh Editor sent unsupported event '{event or '(empty)'}'.", incompatible=True)
            return
        if not self.standalone_rust_ready:
            self._send_rust_error_response(payload, "Mesh Editor is not ready for authoring commands")
            return
        try:
            request_id = int(payload.get("request_id", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            request_id = 0
        if request_id <= self.standalone_rust_last_client_request_id:
            self._send_rust_error_response(payload, "Mesh Editor request was replayed or out of order")
            return
        self.standalone_rust_last_client_request_id = request_id
        # Inspection shares the owned worker lifecycle, but never delays a newer
        # selection or mutation. Keep only its newest queued request.
        self.standalone_rust_protocol_queue[:] = [
            queued for queued in self.standalone_rust_protocol_queue
            if queued.get("event") != "vertex_inspect"
        ]
        active = self.standalone_rust_active_event or {}
        if active.get("event") == "vertex_inspect" and self.standalone_rust_protocol_worker is not None:
            self.standalone_rust_protocol_worker.stop()
        if event == "vertex_inspect" and payload.get("cancel_only") is True:
            return
        if len(self.standalone_rust_protocol_queue) >= _RUST_PROTOCOL_QUEUE_LIMIT:
            self._send_rust_error_response(payload, "Mesh Editor command queue is full")
            return
        self.standalone_rust_protocol_queue.append(dict(payload))
        self._start_next_rust_protocol_worker()

    def _handle_rust_hello(self, payload: Mapping[str, object]) -> None:
        if self.standalone_rust_hello_received:
            self._fail_rust_editor("Mesh Editor repeated its hello handshake.", incompatible=True)
            return
        renderer = str(payload.get("renderer", "") or "")
        edit_backend = str(payload.get("edit_backend", "") or "")
        if renderer != RUST_MESH_RENDERER or edit_backend != RUST_MESH_EDIT_BACKEND:
            self._fail_rust_editor(
                "Mesh Editor provenance does not match the packaged renderer/backend contract.",
                incompatible=True,
            )
            return
        capabilities = payload.get("capabilities", ())
        capability_set = {
            str(value or "").strip()
            for value in capabilities
            if isinstance(value, str)
        } if isinstance(capabilities, (list, tuple)) else set()
        if "embedded_child_window_v1" not in capability_set:
            self._fail_rust_editor(
                "Mesh Editor does not support the required embedded child-window contract.",
                incompatible=True,
            )
            return
        self.standalone_native_host_frame._focus_request_supported = "host_focus_v1" in capability_set
        self.standalone_rust_translation_parts_supported = (
            RUST_UI_TRANSLATION_PARTS_CAPABILITY in capability_set
        )
        session = self.standalone_rust_authoring_session
        if session is not None and (
            session.hair_start_mode
            or session.shadow_service._session(session.shadow_session_id).hair_state is not None
        ):
            from cdmw.services.mesh_rust_contract import RUST_HAIR_AUTHORING_CAPABILITY

            if RUST_HAIR_AUTHORING_CAPABILITY not in capability_set:
                self._fail_rust_editor(
                    "This hair draft requires an updated Hair-capable Rust helper.",
                    incompatible=True,
                )
                return
        try:
            child_hwnd = int(payload.get("child_hwnd", 0) or 0)
            embedded_parent_hwnd = int(payload.get("embedded_parent_hwnd", 0) or 0)
            process_id = int(self.standalone_rust_process.processId()) if self.standalone_rust_process is not None else 0
        except (RuntimeError, TypeError, ValueError, OverflowError):
            child_hwnd = 0
            embedded_parent_hwnd = 0
            process_id = 0
        host = getattr(self, "standalone_native_host_frame", None)
        attach = getattr(host, "attach_child_window", None)
        if not callable(attach):
            self._fail_rust_editor("CDMW has no embedded Mesh Editor host.", incompatible=True)
            return
        attached, reason = attach(child_hwnd, process_id, embedded_parent_hwnd)
        if not attached:
            self._fail_rust_editor(
                f"Mesh Editor embedding failed: {reason or 'child window was rejected'}.",
                incompatible=True,
            )
            return
        self.standalone_rust_child_hwnd = child_hwnd
        self.standalone_rust_hello_received = True
        # A validated child can still be compiling the driver's first shader
        # pipelines. Keep initialization bounded without treating it as an
        # incompatible protocol or enabling editing before the ready event.
        self.standalone_rust_ready_timer.start(_RUST_RENDERER_READY_TIMEOUT_MS)
        self._set_rust_status("Mesh Editor is preparing its renderer and textures...")
        self._send_rust_message(
            self._rust_host_message(
                "hello",
                request_id=0,
                extra={"host": "cdmw", "status": "accepted"},
            )
        )

    def _shared_preview_settings_changed(self, _values: object = None) -> None:
        """Another viewport changed the shared Preview settings: follow them."""
        if getattr(self, "standalone_rust_ready", False) and self.standalone_rust_process is not None:
            self._send_rust_theme_update()

    def _handle_rust_ready(self, _payload: Mapping[str, object]) -> None:
        if not self.standalone_rust_hello_received:
            self._fail_rust_editor("Mesh Editor became ready before hello.", incompatible=True)
            return
        self.standalone_rust_ready_timer.stop()
        self.standalone_rust_ready = True
        self._release_background_warmups()
        if editor_spare_enabled():
            QTimer.singleShot(_RUST_SPARE_REFILL_MS, self, self._refill_rust_editor_spare)
        became_ready = getattr(self, "became_ready", None)  # the live-edit component's signal
        if became_ready is not None and hasattr(became_ready, "emit"):
            became_ready.emit()
        self._send_rust_theme_update()
        if not getattr(self, "_shared_preview_settings_connected", False):
            from cdmw.ui.preview.preview_settings_hub import preview_settings_hub

            hub = preview_settings_hub()
            if hub is not None:
                hub.changed.connect(self._shared_preview_settings_changed)
                self._shared_preview_settings_connected = True
        host = getattr(self, "standalone_native_host_frame", None)
        show_editor = getattr(host, "show_editor", None)
        if callable(show_editor):
            show_editor()
        simplified_parts, material_parts = getattr(
            self.standalone_rust_authoring_session,
            "material_synthesis_budget_parts",
            (0, 0),
        )
        if self.standalone_rust_texture_unavailable_reason:
            self._set_rust_status(
                "Mesh Editor will use an untextured neutral surface: "
                f"{self.standalone_rust_texture_unavailable_reason}",
                error=True,
            )
        elif simplified_parts:
            self._set_rust_status(
                f"Mesh Editor is ready. {simplified_parts} of {material_parts} parts use simplified "
                "materials to stay within the 768 MiB texture limit.",
                error=True,
            )
        else:
            self._set_rust_status(
                "Mesh Editor is ready. Changes remain isolated until Finish Edit Mesh."
            )
        self._sync_mesh_editor_backend_controls(has_active_session=True)

    def _start_next_rust_protocol_worker(self) -> None:
        if getattr(self, "_archive_refit_picker_active", False):
            return
        if self.standalone_rust_protocol_thread is not None or not self.standalone_rust_protocol_queue:
            return
        session = self.standalone_rust_authoring_session
        if session is None or self.standalone_rust_closing:
            self.standalone_rust_protocol_queue.clear()
            return
        event = self.standalone_rust_protocol_queue.pop(0)
        preparation_error = str(event.get("_hair_preparation_error", ""))
        if (event.get("command") == "hair_begin"
                and not dict(event.get("arguments") or {}).get("_hair_context_ready")):
            from cdmw.ui.mesh_editor.hair_flow import begin_hair_context
            try:
                begin_hair_context(self, session, event)
                return
            except Exception as exc:
                preparation_error = str(exc) or type(exc).__name__
        elif event.get("command") == "hair_begin" and dict(event.get("arguments") or {}).get("change_references"):
            from cdmw.ui.mesh_editor.hair_flow import prepare_hair_event
            self._archive_refit_picker_active = True
            try:
                event = prepare_hair_event(self, session, event)
            except Exception as exc:
                preparation_error = str(exc) or type(exc).__name__
            finally:
                self._archive_refit_picker_active = False
            if self.standalone_rust_authoring_session is not session or self.standalone_rust_closing:
                QTimer.singleShot(0, self._start_next_rust_protocol_worker)
                return
        if event.get("command") == "hair_texture":
            from PySide6.QtWidgets import QFileDialog
            self._archive_refit_picker_active = True
            try:
                path, _ = QFileDialog.getOpenFileName(self, "Apply Edited Hair DDS", "", "DDS textures (*.dds)")
            finally:
                self._archive_refit_picker_active = False
            if self.standalone_rust_authoring_session is not session or self.standalone_rust_closing:
                QTimer.singleShot(0, self._start_next_rust_protocol_worker)
                return
            if not path:
                self._send_rust_error_response(event, "DDS selection cancelled.")
                QTimer.singleShot(0, self._start_next_rust_protocol_worker)
                return
            event = {**event, "arguments": {**dict(event.get("arguments") or {}), "_dds_path": path}}
        if event.get("command") in {"replacement_choose", "replacement_include", "replacement_islands", "replacement_cloth", "replacement_guides", "replacement_weapon_collisions", "replacement_collision_volumes", "replacement_jiggle", "replacement_physics_profile", "replacement_translucency", "replacement_emission", "replacement_shader_controls"}:
            from cdmw.ui.mesh_editor.replacement_flow import prepare_replacement_event
            self._archive_refit_picker_active = True
            try:
                event = prepare_replacement_event(self, session, event)
            except Exception as exc:
                preparation_error = str(exc) or type(exc).__name__
            finally:
                self._archive_refit_picker_active = False
            if self.standalone_rust_authoring_session is not session or self.standalone_rust_closing:
                QTimer.singleShot(0, self._start_next_rust_protocol_worker)
                return
        if event.get("command") == "refit_choose_archive":
            from cdmw.ui.mesh_editor.archive_refit_flow import prepare_archive_refit_event
            self._archive_refit_picker_active = True
            try:
                event = prepare_archive_refit_event(self, session, event)
            except Exception as exc:
                preparation_error = str(exc) or type(exc).__name__
            finally:
                self._archive_refit_picker_active = False
            if (
                self.standalone_rust_authoring_session is not session
                or self.standalone_rust_closing
            ):
                QTimer.singleShot(0, self._start_next_rust_protocol_worker)
                return
        if event.get("command") == "refit_fit_to_body":
            from cdmw.ui.mesh_editor.refit_reference_preparation import prepare_refit_fit_event
            event = prepare_refit_fit_event(self, session, event)
        if event.get("command") == "cloth_collision_input" and dict(event.get("arguments") or {}).get("source") == "archive":
            from cdmw.ui.mesh_editor.cloth_collision_flow import prepare_cloth_collision_event
            self._archive_refit_picker_active = True
            try:
                event = prepare_cloth_collision_event(self, session, event)
            except Exception as exc:
                preparation_error = str(exc) or type(exc).__name__
            finally:
                self._archive_refit_picker_active = False
            if self.standalone_rust_authoring_session is not session or self.standalone_rust_closing:
                QTimer.singleShot(0, self._start_next_rust_protocol_worker)
                return
        self.standalone_rust_protocol_request_id += 1
        worker_request_id = self.standalone_rust_protocol_request_id
        worker_type = getattr(
            import_module("cdmw.workers.mesh_rust_editor_workers"),
            "MeshRustProtocolWorker",
        )
        worker = worker_type(
            worker_request_id, session, event, preparation_error=preparation_error,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_rust_protocol_completed)
        worker.error.connect(self._handle_rust_protocol_worker_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(
            lambda current=thread: self._handle_rust_protocol_thread_finished(current)
        )
        thread.finished.connect(thread.deleteLater)
        self.standalone_rust_protocol_worker = worker
        self.standalone_rust_protocol_thread = thread
        self.standalone_rust_active_event = event
        self.standalone_rust_protocol_status = None
        if event.get("event") != "vertex_inspect":
            self._set_rust_status(self._rust_busy_message(event))
        thread.start()

    @staticmethod
    def _rust_busy_message(event: Mapping[str, object]) -> str:
        event_name = str(event.get("event", "") or "")
        if event_name == "finish_request":
            return "Validating and finishing the isolated Mesh Editor session..."
        if event_name == "transaction_request":
            return "Recording Mesh Editor gesture..."
        if event_name == "cancel":
            return "Cancelling Mesh Editor..."
        command = str(event.get("command", "") or "").replace("_", " ").strip()
        return f"Applying Mesh Editor {command or 'command'}..."

    def _handle_rust_protocol_completed(
        self,
        worker_request_id: int,
        _client_request_id: int,
        response: dict[str, object],
        finish_accepted: bool,
    ) -> None:
        if worker_request_id != self.standalone_rust_protocol_request_id:
            return
        active_event = dict(self.standalone_rust_active_event or {})
        if self.standalone_rust_closing and not finish_accepted and active_event.get("event") != "cancel":
            return
        if active_event.get("event") == "vertex_inspect":
            if not self.standalone_rust_closing and not self.standalone_rust_protocol_worker._stop_event.is_set():
                self._send_rust_message(response)
            return
        cancelled = active_event.get("event") == "cancel"
        # Finish and Cancel have already disposed the shadow. Record their
        # outcome before replying, since the helper may exit as soon as it reads it.
        if finish_accepted:
            self.standalone_rust_finish_accepted = True
            self.standalone_rust_ready = False
        elif cancelled:
            self.standalone_rust_closing = True
        self._send_rust_message(response)
        if finish_accepted:
            self._refresh_after_rust_finish(response)
            if self.standalone_rust_process is not None:
                self.standalone_rust_finish_timer.start(_RUST_FINISH_EXIT_TIMEOUT_MS)
        elif cancelled:
            self._publish_rust_protocol_status("Mesh Editor cancelled; CDMW mesh unchanged.")
            self._stop_rust_editor_process()
        else:
            hair_status = getattr(self, "hair_entry_status", None)
            if hair_status is not None:
                session = self.standalone_rust_authoring_session
                hair_active = (
                    active_event.get("event") == "transaction_request"
                    and session is not None
                    and not session.closed
                    and session.shadow_service._session(session.shadow_session_id).hair_state is not None
                )
                if active_event.get("command") == "hair_begin" or hair_active:
                    hair_status.setText("Ready — select visible hair to begin editing.")
            payload = response.get("payload", {})
            result = payload.get("result", {}) if isinstance(payload, dict) else {}
            if isinstance(result, dict) and result.get("hair_texture_source"):
                from cdmw.ui.mesh_editor.hair_flow import open_hair_texture_source
                open_hair_texture_source(self, result["hair_texture_source"])
            warning = str(result.get("appearance_warning") or "") if isinstance(result, dict) else ""
            self._publish_rust_protocol_status(warning or "Mesh Editor command completed.")

    def _handle_rust_protocol_worker_error(
        self,
        worker_request_id: int,
        _client_request_id: int,
        _event: str,
        message: str,
        recovery: dict[str, object],
    ) -> None:
        if worker_request_id != self.standalone_rust_protocol_request_id:
            return
        request = dict(self.standalone_rust_active_event or {})
        if self.standalone_rust_closing and request.get("event") not in {"finish_request", "cancel"}:
            return
        if request.get("event") == "vertex_inspect":
            if not self.standalone_rust_closing:
                self._send_rust_error_response(request, message)
            return
        self._send_rust_error_response(request, message, recovery=recovery)
        hair_status = getattr(self, "hair_entry_status", None)
        if hair_status is not None and (request.get("command") == "hair_begin" or request.get("event") == "transaction_request"):
            hair_status.setText(str(message))
        if self.standalone_rust_closing and str(
            request.get("event", "") or ""
        ).strip().lower() == "finish_request":
            self._publish_rust_protocol_status(
                "Mesh Editor Finish was cancelled before commit; authoritative geometry is unchanged."
            )
        else:
            self._publish_rust_protocol_status(f"Mesh Editor rejected the operation: {message}", error=True)

    def _publish_rust_protocol_status(self, message: str, *, error: bool = False) -> None:
        # Shell status updates repolish Qt widgets. Doing that while PySide is
        # destroying the protocol worker can deadlock Qt's connection mutex
        # against the GIL. Send the protocol result immediately, but publish its
        # status only after this worker's thread has finished its teardown.
        if getattr(self, "standalone_rust_protocol_thread", None) is not None:
            self.standalone_rust_protocol_status = (message, error)
        else:
            self._set_rust_status(message, error=error)

    def _handle_rust_protocol_thread_finished(self, thread: QThread) -> None:
        if self.standalone_rust_protocol_thread is not thread:
            return
        self.standalone_rust_protocol_thread = None
        self.standalone_rust_protocol_worker = None
        self.standalone_rust_active_event = None
        status = getattr(self, "standalone_rust_protocol_status", None)
        self.standalone_rust_protocol_status = None
        if status is not None:
            self._set_rust_status(status[0], error=status[1])
        stop_after_protocol = self.standalone_rust_stop_after_protocol
        self.standalone_rust_stop_after_protocol = False
        close_session_pending = self.standalone_rust_close_session_pending
        if self.standalone_rust_dispose_pending:
            self._schedule_rust_session_dispose()
        elif stop_after_protocol:
            self._stop_rust_editor_process()
        elif not self.standalone_rust_closing:
            self._start_next_rust_protocol_worker()
        if close_session_pending:
            self.standalone_rust_close_session_pending = False
            self.standalone_rust_terminal_close_pending = True
            closing_controller = getattr(self, "standalone_controller", None)
            QTimer.singleShot(
                0,
                lambda expected_controller=closing_controller: (
                    self._complete_deferred_rust_session_close(expected_controller)
                ),
            )

    def _complete_deferred_rust_session_close(
        self,
        expected_controller: object | None = None,
    ) -> None:
        if expected_controller is None:
            if not self.standalone_rust_terminal_close_pending:
                return
        elif expected_controller is not getattr(self, "standalone_controller", None):
            self.standalone_rust_terminal_close_pending = False
            self.standalone_rust_close_session_pending = False
            return
        self.standalone_rust_terminal_close_pending = False
        self.standalone_rust_close_session_pending = False
        self.close_standalone_session()

    def _send_rust_error_response(
        self,
        request: Mapping[str, object],
        message: str,
        *,
        recovery: Mapping[str, object] | None = None,
    ) -> None:
        event = str(request.get("event", "") or "error")
        result_event = {
            "vertex_inspect": "vertex_inspect_result",
            "transaction_request": "transaction_result",
            "command_request": "command_result",
            "finish_request": "finish_result",
            "cancel": "error",
        }.get(event, "error")
        response = self._rust_host_message(
            result_event,
            request_id=int(request.get("request_id", 0) or 0),
            extra={
                "ok": False,
                "error": str(message or "Mesh Editor request failed"),
                "payload": dict(recovery or {}),
            },
        )
        self._send_rust_message(response)

    def _rust_command_registry(self):
        from cdmw.ui.commands.registry import CommandRegistry

        try:
            window = self.window()
        except (AttributeError, RuntimeError):
            return None
        registry = getattr(window, "command_registry", None)
        return registry if isinstance(registry, CommandRegistry) else None

    def _mirror_rust_commands(self, commands: object) -> None:
        """The editor's own commands join the registry and the palette (P12)."""

        registry = self._rust_command_registry()
        if registry is None or not isinstance(commands, list):
            return
        from cdmw.ui.mesh_editor.editor_commands import mirror_helper_commands

        mirror_helper_commands(registry, [row for row in commands if isinstance(row, Mapping)],
                               self._send_rust_command, lambda: bool(self.standalone_rust_ready))

    def _send_rust_command(self, helper_id: str) -> bool:
        return self._send_rust_message(
            self._rust_host_message("run_command", request_id=0, extra={"command": str(helper_id)})
        )

    def _rust_host_message(
        self,
        event: str,
        *,
        request_id: int,
        extra: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        session = self.standalone_rust_authoring_session
        revision = 0
        if session is not None and not session.closed:
            try:
                revision = session.shadow_service.session_view(session.shadow_session_id).revision
            except (KeyError, RuntimeError):
                revision = 0
        payload: dict[str, object] = {
            "event": str(event),
            "protocol": RUST_MESH_EDITOR_PROTOCOL,
            "session_id": session.session_id if session is not None else "",
            "request_id": int(request_id),
            "base_revision": int(revision),
            "process_generation": int(self.standalone_rust_process_generation),
        }
        payload.update(dict(extra or {}))
        return payload

    def _send_rust_message(self, payload: Mapping[str, object]) -> bool:
        process = self.standalone_rust_process
        if process is None or not qprocess_is_running(process):
            return False
        message = dict(payload)
        body = message.get("payload")
        if isinstance(body, Mapping) and "payload_file" in body:
            message["payload"] = {"payload_file": body["payload_file"]}
        data = protocol_line(message)
        try:
            return int(process.write(data)) == len(data)
        except (RuntimeError, TypeError, ValueError):
            return False

    def _refresh_after_rust_finish(self, _response: Mapping[str, object]) -> None:
        controller = self.standalone_rust_target_controller
        if controller is None or controller is not getattr(self, "standalone_controller", None):
            return
        try:
            view = controller.session_view()
            session = self.standalone_rust_authoring_session
            validation = getattr(session, "accepted_export_validation", None)
            if (
                validation is not None
                and session.authoritative_service is controller.mesh_service
                and session.authoritative_session_id == controller.active_session_id == view.session_id
                and validation[0] == view.revision
                and validation[1].ok
            ):
                self.standalone_export_validation_revision = validation[0]
                self.standalone_last_export_validation_report = validation[1]
            self.update_editor_session_state(
                view,
                active_selection_mode=controller.active_selection_mode,
            )
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
            pass
        host = getattr(self, "standalone_native_host_frame", None)
        show_result = getattr(host, "show_result", None)
        if callable(show_result):
            show_result(
                "Your mesh changes passed validation. Choose how to keep editing, save the result or install it."
            )
        self._publish_rust_protocol_status("Mesh Editor finished and CDMW accepted the validated geometry.")

    def _handle_rust_ready_timeout(self) -> None:
        if self.standalone_rust_ready:
            return
        if self.standalone_rust_hello_received:
            self._fail_rust_editor(
                "Mesh Editor did not finish preparing its renderer and textures."
            )
            return
        self._fail_rust_editor(
            "Mesh Editor did not complete the cdmw_rust_mesh_editor_protocol_v1 handshake.",
            incompatible=True,
        )

    def _handle_rust_finish_exit_timeout(self) -> None:
        if self.standalone_rust_finish_accepted and self._rust_editor_process_running():
            self._stop_rust_editor_process(
                reason="Mesh Editor finished and CDMW accepted the validated geometry."
            )

    def _handle_rust_process_error(self, process: QProcess, error: object) -> None:
        if process is not self.standalone_rust_process:
            return
        self._drain_rust_process_output(process)
        if self.standalone_rust_closing:
            return
        self.standalone_rust_process_error_reported = True
        suffix = self._rust_process_diagnostic_suffix()
        if error == QProcess.ProcessError.FailedToStart:
            self.standalone_rust_process = None
            unregister_owned_qprocess_for_exit(process)
            try:
                process.deleteLater()
            except RuntimeError:
                pass
        self._fail_rust_editor(f"Mesh Editor process failed.{suffix}")

    def _handle_rust_process_finished(
        self,
        process: QProcess,
        exit_code: int,
        _exit_status: object,
    ) -> None:
        if process is not self.standalone_rust_process:
            return
        if not shiboken6.isValid(self.standalone_rust_ready_timer):
            # The helper exited while the window tears this tab down: its Qt
            # children are already destroyed, so only release the process.
            self.standalone_rust_process = None
            unregister_owned_qprocess_for_exit(process)
            self.standalone_rust_ready = False
            self.standalone_rust_child_hwnd = 0
            return
        self._drain_rust_process_output(process)
        self.standalone_rust_ready_timer.stop()
        self.standalone_rust_finish_timer.stop()
        self.standalone_rust_process = None
        unregister_owned_qprocess_for_exit(process)
        self.standalone_rust_ready = False
        host = getattr(self, "standalone_native_host_frame", None)
        detach = getattr(host, "detach_child_window", None)
        if callable(detach):
            detach()
        self.standalone_rust_child_hwnd = 0
        try:
            process.deleteLater()
        except RuntimeError:
            pass
        if self.standalone_rust_finish_accepted:
            show_result = getattr(host, "show_result", None)
            if callable(show_result):
                show_result(
                    "Your mesh changes passed validation. Choose how to keep editing, save the result or install it."
                )
            self._publish_rust_protocol_status("Mesh Editor finished and CDMW accepted the validated geometry.")
        elif self._rust_finish_protocol_active():
            session = self.standalone_rust_authoring_session
            if session is not None and not session.closed:
                session.request_cancel()
            self.standalone_rust_stop_after_protocol = True
            self._publish_rust_protocol_status(
                "Mesh Editor closed while Finish was running; waiting for the safe terminal result."
            )
        elif (
            self.standalone_rust_process_error_reported
            or (not self.standalone_rust_closing and not self.standalone_rust_failure_reported)
        ):
            suffix = self._rust_process_diagnostic_suffix()
            self._publish_rust_protocol_status(
                f"Mesh Editor closed (exit {int(exit_code)}); its shadow changes were discarded.{suffix}",
                error=True,
            )
            show_error = getattr(host, "show_error", None)
            if callable(show_error):
                show_error(
                    f"Mesh Editor closed unexpectedly. Its unaccepted changes were discarded.{suffix}"
                )
        self.standalone_rust_closing = True
        self.standalone_rust_dispose_pending = True
        self._schedule_rust_session_dispose()
        registry = self._rust_command_registry()
        if registry is not None:  # the editor's commands leave with its helper
            from cdmw.ui.mesh_editor.editor_commands import clear_helper_commands

            clear_helper_commands(registry)
        closed = getattr(self, "closed", None)  # the live-edit component's signal
        if closed is not None and hasattr(closed, "emit"):
            closed.emit()

    def _fail_rust_editor(self, message: str, *, incompatible: bool = False) -> None:
        release = getattr(self, "_release_background_warmups", None)
        if callable(release):
            release()
        if self.standalone_rust_failure_reported:
            return
        self.standalone_rust_failure_reported = True
        if incompatible:
            self.standalone_rust_incompatible_reason = str(message or "Incompatible executable")
        host = getattr(self, "standalone_native_host_frame", None)
        show_error = getattr(host, "show_error", None)
        if callable(show_error):
            show_error(str(message or "Mesh Editor failed"))
        self._set_rust_status(str(message or "Mesh Editor failed"), error=True)
        self._stop_rust_editor_process()

    def _stop_rust_editor_process(self, *, reason: str = "") -> None:
        hair_context = getattr(self, "_hair_context_preparation", None)
        self._hair_entry_generation = getattr(self, "_hair_entry_generation", 0) + 1
        if hair_context is not None:
            hair_context.cancel()
        self.standalone_rust_closing = True
        self.standalone_rust_ready = False
        # A spare still on its way to this open is stopped when it arrives.
        self._rust_spare_adoption = None
        picker = getattr(self, "_archive_refit_picker", None)
        if picker is not None:
            picker.request_shutdown()
        collision_picker = getattr(self, "_cloth_collision_picker", None)
        if collision_picker is not None:
            collision_picker.reject()
        hair_picker = getattr(self, "_hair_picker", None)
        if hair_picker is not None:
            hair_picker.request_shutdown()
        self.standalone_rust_ready_timer.stop()
        self.standalone_rust_finish_timer.stop()
        self.standalone_rust_protocol_queue.clear()
        host = getattr(self, "standalone_native_host_frame", None)
        detach = getattr(host, "detach_child_window", None)
        if callable(detach):
            detach()
        self.standalone_rust_child_hwnd = 0
        self._stop_rust_session_prepare(invalidate=True)
        worker = self.standalone_rust_protocol_worker
        finish_active = self._rust_finish_protocol_active()
        if worker is not None and not finish_active:
            worker.stop()
        if finish_active:
            session = self.standalone_rust_authoring_session
            cancel_won = bool(
                session is not None
                and not session.closed
                and session.request_cancel()
            )
            self.standalone_rust_stop_after_protocol = True
            if cancel_won:
                reason = "Cancelling Mesh Editor Finish; authoritative geometry remains unchanged."
            else:
                reason = (
                    "Mesh Editor Finish already owns the atomic commit boundary; "
                    "waiting for its terminal result."
                )
            if reason:
                self._set_rust_status(reason)
            return
        process = self.standalone_rust_process
        if process is not None and qprocess_is_running(process):
            self.standalone_rust_host_request_id += 1
            self._send_rust_message(
                self._rust_host_message(
                    "cancel",
                    request_id=self.standalone_rust_host_request_id,
                    extra={"reason": str(reason or "CDMW session closed")},
                )
            )
            stop_qprocess_async(process, grace_ms=1000)
        else:
            self.standalone_rust_dispose_pending = True
            self._schedule_rust_session_dispose()
        if reason:
            self._set_rust_status(reason)
