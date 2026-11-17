"""Rust Mesh Editor process protocol, diagnostics, and shutdown."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Mapping
from importlib import import_module
from pathlib import Path

import shiboken6
from PySide6.QtCore import QProcess, QProcessEnvironment, QThread, QTimer

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

#: How often the Mesh Editor tab checks whether the draft's last autosave failed.
RUST_SAVE_STATUS_POLL_MS = 2000

_RUST_PROTOCOL_QUEUE_LIMIT = 128
_RUST_READY_TIMEOUT_MS = 10_000
_RUST_RENDERER_READY_TIMEOUT_MS = 60_000
_RUST_FINISH_EXIT_TIMEOUT_MS = 3_000
_RUST_DIAGNOSTIC_BUFFER_LIMIT = 16 * 1024
_RUST_DIAGNOSTIC_TEXT_LIMIT = 2 * 1024
_RUST_DIAGNOSTIC_LINE_LIMIT = 8
#: A second renderer crash within this many seconds stops the automatic restart (P4 V3).
_RUST_CRASH_RETRY_WINDOW_S = 60.0
#: Tests answer the second-crash question here: ``lambda box: "finish"`` or ``"discard"``.
crash_prompt_override = None
#: A second-crash prompt is open; another document's waits for it (section 8.7 F3).
_crash_prompt_open = False
#: ``edit_in_place_blocker`` while Browse's process is (re)starting, and how long to wait for it.
_BOUND_VIEWPORT_NOT_READY = "the viewport is not ready"
_BOUND_VIEWPORT_WAIT_S = 20.0


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


#: What a parked document says (P15 step 3).
PARKED_STATUS = "This document is parked to save memory. Its 3D view opens again when you show it."

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
        stages = dict(getattr(session, "open_stage_ms", None) or {})
        if stages:
            from cdmw.ui.mesh_editor.tab_rust_editor import _record_open_stage_timings

            _record_open_stage_timings(self, stages)
        if self._open_in_bound_viewport(session):
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
        if self._open_in_engine_window(session, parent_hwnd):
            return
        self._launch_fresh_rust_editor_process(session, executable, parent_hwnd)

    def _open_in_bound_viewport(self, session: object) -> bool:
        """Edit in Browse's viewport when one is bound (P4 V3): its process enters edit mode."""

        binding = getattr(self, "_viewport_binding", None)
        if binding is None:
            return False
        channel = binding.borrow()
        if channel is None:
            reason = binding.blocker() or "Browse's viewport cannot edit now"
            if self._wait_for_bound_viewport(session, reason):
                return True
            self._leave_bound_viewport(reason)
            return False
        self._bound_viewport_wait_since = 0.0
        self._set_rust_status("Opening the edit in Browse's viewport...")
        self._adopt_rust_editor_process(channel, session, keep_view=True)
        return True

    def _wait_for_bound_viewport(self, session: object, reason: str) -> bool:
        """Browse's process is starting again (after a crash of the process the edit
        shared): wait for it, so the edit continues in Browse's viewport and not in
        the tab (section 8.7 F4). False once it is not that, or waited too long."""

        now = time.monotonic()
        crashed_at = float(getattr(self, "_rust_last_crash_at", 0.0) or 0.0)
        if reason != _BOUND_VIEWPORT_NOT_READY or not crashed_at or now - crashed_at > _RUST_CRASH_RETRY_WINDOW_S:
            self._bound_viewport_wait_since = 0.0
            return False
        since = float(getattr(self, "_bound_viewport_wait_since", 0.0) or 0.0)
        if not since:
            self._bound_viewport_wait_since = since = now
        if now - since > _BOUND_VIEWPORT_WAIT_S:
            self._bound_viewport_wait_since = 0.0
            return False
        self._set_rust_status("Waiting for Browse's viewport to start again...")
        QTimer.singleShot(250, self, lambda current=session: self._retry_bound_viewport(current))
        return True

    def _retry_bound_viewport(self, session: object) -> None:
        if session is not self.standalone_rust_authoring_session or getattr(session, "closed", True):
            self._bound_viewport_wait_since = 0.0
            return
        if getattr(self, "_viewport_binding", None) is None:
            return
        if not self._open_in_bound_viewport(session):
            self._launch_rust_editor_process(session)  # waited too long: the tab's own view

    def _open_in_engine_window(self, session: object, parent_hwnd: int) -> bool:
        """Edit in a window of Browse's process under the tab (P4 V5): no process of its own.

        Falls back to the usual launch when Browse's process cannot hold it, and
        does not ask again for a session it once refused.
        """

        if getattr(self, "_engine_window_refused_session", None) is session:
            return False
        from cdmw.services.engine_capture import engine_capture_router

        controller = engine_capture_router().resident_controller()
        borrow = getattr(controller, "borrow_for_window_edit", None)
        channel = borrow(self) if callable(borrow) else None
        if channel is None:
            return False
        self._set_rust_status("Opening the embedded Mesh Editor...")
        self._adopt_rust_editor_process(channel, session, own_window_parent=parent_hwnd)
        return True

    def _leave_bound_viewport(self, reason: str) -> None:
        """Stop using Browse's viewport; the next launch uses the host's own."""

        release = getattr(self, "_release_viewport_binding", None)
        if callable(release):
            release()
        moved = getattr(self, "moved_to_own_viewport", None)
        if moved is not None and hasattr(moved, "emit"):
            moved.emit(str(reason or ""))

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

    def _adopt_rust_editor_process(self, process: QProcess, session: object, *, keep_view: bool = False,
                                   own_window_parent: int = 0) -> None:
        """Give a pre-started helper its session; it answers hello and ready as a launch does.

        ``keep_view``: the helper is Browse's, already showing the model (P4 V3); it
        keeps its camera, view and every texture whose digest matches.
        ``own_window_parent``: the helper is Browse's and the edit gets a window of
        its own under this one, the tab's host (P4 V5).
        """

        self._connect_rust_process_signals(process)
        self._take_rust_process(process, session)
        message = {
            "event": "open_session",
            "protocol": RUST_MESH_EDITOR_PROTOCOL,
            "manifest": str(session.manifest_path),
            "keep_view": bool(keep_view),
        }
        session_id = str(getattr(session, "session_id", "") or "")
        if session_id:
            # Browse's process holds one edit per document and routes by it (P15).
            message["session_id"] = session_id
            if hasattr(process, "session_id"):
                process.session_id = session_id
        if own_window_parent > 0:
            message.update(viewport="own", parent_hwnd=int(own_window_parent))
        line = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
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
        if event == "texture_updated":
            self._live_textures().acknowledge(payload)
            return
        if event == "live_textures":
            self._show_live_textures(payload.get("textures"))
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
                registry = self._rust_command_registry()
                if registry is not None:  # Settings > Shortcuts shows the new keys
                    self._rust_keymap_echo = True
                    try:
                        registry.keymap_changed.emit()
                    finally:
                        self._rust_keymap_echo = False
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

    # ----- live texture edits (step 8) --------------------------------------
    def _live_textures(self):
        live = getattr(self, "_live_texture_updates", None)
        if live is None:
            from cdmw.ui.mesh_editor.live_texture_updates import LiveTextureUpdates

            def session_root():
                root = getattr(self, "standalone_rust_session_root", None)
                return Path(root) if root else None

            def send(fields):
                if not self.standalone_rust_ready:
                    return False
                return self._send_rust_message(self._rust_host_message("texture_update", request_id=0, extra=fields))

            live = self._live_texture_updates = LiveTextureUpdates(session_root, send, self)
        return live

    def _show_live_textures(self, textures: object) -> None:
        """The editor said which textures an edit shows on, per part (B item 6): the layers
        the shader combines count, the ones combined when the model opened do not."""

        from cdmw.ui.mesh_editor.tab_rust_editor import _host_panel, _host_textures_panel
        from cdmw.ui.mesh_editor.textures_panel import shown_live_by_source

        shown = shown_live_by_source(textures)
        dock = _host_textures_panel(self)
        set_shown = getattr(dock, "set_shown_live_textures", None)
        if callable(set_shown):
            set_shown(shown)
        tools = _host_panel(self, "_texture_tools_panel")
        show = getattr(tools, "set_shown_live_sources", None)
        if callable(show):
            show(shown)

    def _live_texture_keeper(self):
        """Keeps this document's texture edits in its draft (step 8, item 3)."""

        keeper = getattr(self, "_live_texture_keeping", None)
        if keeper is None:
            from cdmw.ui.mesh_editor.live_texture_keeping import LiveTextureKeeper

            keeper = self._live_texture_keeping = LiveTextureKeeper(
                self._live_textures(), self._live_texture_draft_root, self)
            keeper.status.connect(self.status_message_requested.emit)
            keeper.kept_changed.connect(self._show_live_texture_kept_text)
        return keeper

    def _shared_texture_check(self):
        check = getattr(self, "_shared_texture_checking", None)
        if check is None:
            from cdmw.ui.mesh_editor.shared_texture_check import SharedTextureCheck

            check = self._shared_texture_checking = SharedTextureCheck(
                self._new_texture_reference_search, self._texture_archive_entry,
                self._texture_reference_session_id, self._own_model_stems, self)
            check.changed.connect(self._show_shared_texture_result)
        return check

    def _browse_archives(self):
        window = self.window() if callable(getattr(self, "window", None)) else None
        return getattr(window, "archive", None)

    def _new_texture_reference_search(self):
        from cdmw.services.archive_reference_search import ArchiveReferenceSearchController

        archive = self._browse_archives()
        return ArchiveReferenceSearchController(getattr(archive, "archive_catalogue_service", None), self)

    def _texture_reference_session_id(self) -> str:
        bridge = getattr(self._browse_archives(), "archive_remote_bridge", None)
        session = getattr(bridge, "current_session", None)
        return str(getattr(session, "session_id", "") or "") if bool(getattr(bridge, "displays_v2", False)) else ""

    def _texture_archive_entry(self, game_path: str):
        from cdmw.domain.archives.filters import active_archive_entry_for_virtual_path

        key = str(game_path or "").replace("\\", "/").strip().lower()
        candidates = self._archive_texture_indexes()[0].get(key, ())
        return active_archive_entry_for_virtual_path(list(candidates)) if candidates else None

    def _own_model_stems(self) -> tuple[str, ...]:
        """The opened model's files by name: their own sidecars are not "other" files."""

        paths = []
        target = self._current_target_entry()
        if target is not None:
            paths.append(str(getattr(target, "path", "") or ""))
        for context in tuple(getattr(self, "item_set_contexts", ()) or ()):
            for asset in tuple(getattr(context, "assets", ()) or ()):
                paths.append(str(getattr(getattr(asset, "entry", None), "path", "") or ""))
        return tuple(dict.fromkeys(Path(path.replace("\\", "/")).name.split(".", 1)[0].casefold()
                                   for path in paths if path))

    def _show_shared_texture_result(self, game_path: str) -> None:
        from cdmw.ui.mesh_editor.tab_rust_editor import _host_panel

        tools = _host_panel(self, "_texture_tools_panel")
        result = self._shared_texture_check().texture_users_found(game_path)
        show = getattr(tools, "set_sharing_text", None)
        if callable(show) and result is not None:
            show(game_path, result.sharing_notice)

    def _live_texture_draft_root(self) -> Path | None:
        """The document's draft folder, once it exists on disk (a planned draft is not yet)."""

        manifest = getattr(self, "mesh_editor_draft_manifest_path", None)
        try:
            return Path(manifest).parent if manifest is not None and Path(manifest).is_file() else None
        except (OSError, TypeError, ValueError):
            return None

    def _show_live_texture_kept_text(self, text: str) -> None:
        from cdmw.ui.mesh_editor.tab_rust_editor import _host_panel

        tools = _host_panel(self, "_texture_tools_panel")
        show = getattr(tools, "set_kept_text", None)
        if callable(show):
            show(text)

    def _live_texture_session_id(self) -> str:
        # The document, not one editor session: edits made after Finish still belong to it.
        document_id = getattr(self, "_live_texture_document_id", "")
        if not document_id:
            from uuid import uuid4

            document_id = self._live_texture_document_id = f"mesh-document-{uuid4().hex}"
        return document_id

    def open_texture_in_window(self, texture_id: str) -> None:
        """Open a Textures panel row in the texture tools docked beside the model (step 8)."""

        from cdmw.ui.mesh_editor.tab_rust_editor import _host_textures_panel

        dock = _host_textures_panel(self)
        row = dock.texture_row(texture_id) if dock is not None else None
        session_id = self._live_texture_session_id()
        if row is None or not row.decoded_path:
            return
        from cdmw.domain.textures.original_output import TextureOutputRefused, check_texture_editable
        from cdmw.services.mesh_live_texture_output import LiveTextureSource
        from cdmw.ui.mesh_editor.tab_rust_editor import _host_panel
        from cdmw.ui.mesh_editor.texture_tools_dock import LiveTextureTarget

        tools = _host_panel(self, "_texture_tools_panel")
        if tools is None:
            return

        users = dock.texture_users(texture_id)
        try:
            # Refused before the first edit when the original cannot be written back as it was.
            original = check_texture_editable(Path(row.decoded_path))
        except TextureOutputRefused as exc:
            self.status_message_requested.emit(exc.reason, True)
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "Texture Editor", exc.reason)
            return
        self._live_textures().remember_source(row.source_sha256, LiveTextureSource(
            game_path=row.game_path, original=original, users=users, role=row.role))

        tools.open_target(LiveTextureTarget(
            session_id=session_id,
            source_path=row.decoded_path,
            source_sha256=row.source_sha256,
            channel=row.role,
            display_name=row.file_name,
            game_path=row.game_path,
            users=users,
            in_renderer=self._texture_shown_live(dock, row),
        ))
        # Which other game files use it, searched in the background (item 5).
        check = self._shared_texture_check()
        check.search_texture_users(row.game_path)
        self._show_shared_texture_result(row.game_path)

    @staticmethod
    def _texture_shown_live(dock, row) -> bool:
        # The same file can be a drawn layer on one part and left out on another: an edit
        # shows when any part draws it.
        shown = getattr(dock, "texture_shown_live", None)
        return bool(shown(row.source_sha256)) if callable(shown) else bool(row.in_renderer)

    def _on_texture_window_edit(self, session_id: str, source_sha256: str, image, changed: bool = True) -> None:
        if session_id and session_id == self._live_texture_session_id():
            self._live_textures().push(source_sha256, image, changed=changed)
            self._live_texture_keeper().edited()

    def _live_texture_plan(self, *, include_body: bool = True):
        """What Build Mod writes for the textures edited live, or None when none were.

        ``include_body``: whether the mod holds the body a Fit follows (Include the body)."""

        live = getattr(self, "_live_texture_updates", None)
        edited = live.edited_textures() if live is not None else {}
        if not edited:
            return None
        import numpy as np

        from cdmw.services.mesh_live_texture_output import LiveTextureEdit, plan_live_texture_outputs
        from cdmw.ui.mesh_editor.live_texture_updates import image_rgba8

        edits = []
        for source_sha256, image in edited.items():
            source = live.sources.get(source_sha256) or self._restored_live_texture_source(source_sha256)
            if source is None:
                continue
            width, height, data = image_rgba8(image)
            check = getattr(self, "_shared_texture_checking", None)
            shared = check.texture_users_found(source.game_path) if check is not None else None
            edits.append(LiveTextureEdit(
                source_sha256=source_sha256,
                game_path=source.game_path,
                other_files=shared.other_files if shared is not None else (),
                original=source.original,
                rgba=np.frombuffer(data, dtype=np.uint8).reshape(height, width, 4).copy(),
                users=source.users,
            ))
        return plan_live_texture_outputs(edits, self._archive_texture_indexes()[0],
                                         parts_in_build=self._parts_in_build(include_body=include_body))

    def _parts_in_build(self, *, include_body: bool = True) -> tuple[str, ...] | None:
        """The parts Build Mod writes (deleted parts are gone from the working mesh, parts
        whose Include is off are left out, and so is the body a Fit follows unless
        ``include_body``), or None when they cannot be read: then no texture is left out."""

        from contextlib import nullcontext

        from cdmw.services.mesh_live_texture_output import parts_in_build

        controller = getattr(self, "standalone_controller", None)
        try:
            service, session_id = controller.mesh_service, controller.active_session_id
            mesh = service.working_mesh(session_id)
            session_of = getattr(service, "_session", None)
            session = session_of(session_id) if callable(session_of) else None
            lock = getattr(session, "export_lock", None)
            with lock if lock is not None else nullcontext():
                context = getattr(session, "archive_refit_context", None)
                replacement = getattr(session, "replacement_state", None)
            body = ()
            if not include_body:
                from cdmw.services.mesh_archive_refit import archive_refit_body_assets

                morph = getattr(service, "cached_morph_state", None)
                body = tuple(index for asset in archive_refit_body_assets(
                    context, morph(session_id) if callable(morph) else None) for index in asset.part_indices)
            return parts_in_build(mesh, context, replacement, left_out_parts=body)
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
            return None

    def _restored_live_texture_source(self, source_sha256: str):
        """What Build Mod needs about an edit restored from the draft whose texture was not
        opened since: read from the Textures panel's row of the same texture."""

        from cdmw.domain.textures.original_output import TextureOutputRefused, check_texture_editable
        from cdmw.services.mesh_live_texture_output import LiveTextureSource
        from cdmw.ui.mesh_editor.tab_rust_editor import _host_textures_panel

        dock = _host_textures_panel(self)
        rows = getattr(dock, "texture_rows", None)
        for row in (rows() if callable(rows) else ()):
            if str(row.source_sha256).lower() == str(source_sha256).lower() and row.decoded_path:
                try:
                    original = check_texture_editable(Path(row.decoded_path))
                except TextureOutputRefused:
                    return None
                source = LiveTextureSource(game_path=row.game_path, original=original,
                                           users=dock.texture_users(row.texture_id), role=row.role)
                self._live_textures().remember_source(source_sha256, source)
                return source
        return None

    def push_live_texture(self, source_sha256: str, image) -> int:
        """Show an edited texture on the model now; returns the edit's revision."""

        return self._live_textures().push(source_sha256, image)

    def _handle_rust_ready(self, _payload: Mapping[str, object]) -> None:
        if not self.standalone_rust_hello_received:
            self._fail_rust_editor("Mesh Editor became ready before hello.", incompatible=True)
            return
        self.standalone_rust_ready_timer.stop()
        self.standalone_rust_ready = True
        live = getattr(self, "_live_texture_updates", None)
        if live is not None:
            live.reapply()
            live.flush()  # edits made while the editor was starting (step 8)
        self._release_background_warmups()
        self._query_deferred_rust_morph_state()
        self._start_rust_save_status_watch()
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
        from cdmw.ui.mesh_editor.shared_history_routing import route_history_step

        event = route_history_step(self, event)
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
        from cdmw.workers.thread_lifetime import release_worker_after_thread
        release_worker_after_thread(thread, worker)
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
        from cdmw.ui.mesh_editor.shared_history_routing import follow_reply

        follow_reply(self)
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
        """The window's registry, or the application's one: Browse's edit component
        has no window, and a detached tool window has no registry of its own
        (section 8.7 E2, E6)."""

        from cdmw.ui.commands import registry as registry_module
        from cdmw.ui.commands.registry import CommandRegistry

        try:
            window = self.window()
        except (AttributeError, RuntimeError):
            window = None
        registry = getattr(window, "command_registry", None)
        if isinstance(registry, CommandRegistry):
            return registry
        registry = registry_module.command_registry()
        return registry if isinstance(registry, CommandRegistry) else None

    def _clear_rust_commands(self) -> None:
        """This document's mirrored commands leave with its helper; others' stay."""

        registry = self._rust_command_registry()
        if registry is not None:
            from cdmw.ui.mesh_editor.editor_commands import clear_helper_commands

            clear_helper_commands(registry, self)

    def _mirror_rust_commands(self, commands: object) -> None:
        """The editor's own commands join the registry and the palette (P12)."""

        registry = self._rust_command_registry()
        if registry is None or not isinstance(commands, list):
            return
        from cdmw.ui.mesh_editor.editor_commands import mirror_helper_commands

        mirror_helper_commands(registry, [row for row in commands if isinstance(row, Mapping)],
                               self._send_rust_command, lambda: bool(self.standalone_rust_ready), owner=self)
        if not getattr(self, "_rust_follows_keymap", False):
            # A key changed in Settings > Shortcuts reaches the running editor at once.
            self._rust_follows_keymap = True
            registry.keymap_changed.connect(self._rust_keymap_changed)

    def _rust_keymap_changed(self) -> None:
        if getattr(self, "_rust_keymap_echo", False):
            return  # the editor itself just saved these keys
        if getattr(self, "standalone_rust_ready", False) and self.standalone_rust_process is not None:
            self._send_rust_theme_update()

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
        if getattr(self, "_live_texture_updates", None) is not None:
            self._live_texture_keeper().finished()

    def _query_deferred_rust_morph_state(self) -> None:
        """The editor shows before its morph data (P4 V3): ask for it now, send it when it comes."""

        session = self.standalone_rust_authoring_session
        arrived = getattr(self, "morph_state_arrived", None)
        query = getattr(session, "query_deferred_morph_state", None)
        if session is None or arrived is None or not callable(query):
            return
        if not getattr(session, "defer_morph_state", False) or getattr(session, "deferred_morph_ready", True):
            return
        # Tools unlock as their back end becomes ready (P4 V4). Said before the query
        # starts: building a host message reads the revision, which waits behind it.
        self._send_rust_tool_groups({"morph": "Morph data is still being prepared."})
        if not query(lambda payload, current=session: arrived.emit(current, payload)):
            self._send_rust_tool_groups({})

    def _send_rust_morph_state(self, session: object, payload: object) -> None:
        if (session is not self.standalone_rust_authoring_session or not self.standalone_rust_ready
                or not isinstance(payload, Mapping)):
            return
        self._send_rust_message(self._rust_host_message("morph_state", request_id=0,
                                                        extra={"payload": dict(payload)}))
        self._send_rust_tool_groups({})

    def _start_rust_save_status_watch(self) -> None:
        """A draft autosave that fails says so in the editor (2026-11-13).

        The draft saves on a background thread after each change, so its failure
        comes after the change's own reply: the editor is told on its own line,
        and told again when a later save succeeds.
        """

        timer = getattr(self, "standalone_rust_save_status_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setInterval(RUST_SAVE_STATUS_POLL_MS)
            timer.timeout.connect(self._poll_rust_save_status)
            self.standalone_rust_save_status_timer = timer
        self.standalone_rust_save_status_sent = ""
        timer.start()

    def _rust_save_status_error(self) -> str:
        session = self.standalone_rust_authoring_session
        for service_name, id_name in (("shadow_service", "shadow_session_id"),
                                      ("authoritative_service", "authoritative_session_id")):
            service = getattr(session, service_name, None)
            session_id = getattr(session, id_name, None)
            if service is None or not session_id:
                continue
            try:
                error = str(getattr(service._session(session_id), "mesh_layer_autosave_error", "") or "")
            except (AttributeError, KeyError, RuntimeError, TypeError):
                continue
            if error:
                return error
        return ""

    def _poll_rust_save_status(self) -> None:
        session = self.standalone_rust_authoring_session
        timer = getattr(self, "standalone_rust_save_status_timer", None)
        if session is None or getattr(session, "closed", True) or not self.standalone_rust_ready:
            if timer is not None:
                timer.stop()
            return
        error = self._rust_save_status_error()
        if error == getattr(self, "standalone_rust_save_status_sent", ""):
            return
        if self._send_rust_message(self._rust_host_message("save_status", request_id=0, extra={"error": error})):
            self.standalone_rust_save_status_sent = error

    def _send_rust_tool_groups(self, preparing: Mapping[str, str]) -> bool:
        """Tell the editor which tool groups are still preparing, and why (P4 V4)."""

        groups = {str(name): {"ready": False, "reason": str(reason)} for name, reason in preparing.items()}
        return self._send_rust_message(self._rust_host_message("tool_groups", request_id=0,
                                                               extra={"groups": groups}))

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
        refusal = str(getattr(process, "refusal", "") or "")
        session = self.standalone_rust_authoring_session
        if refusal and not self.standalone_rust_hello_received and session is not None and not session.closed:
            # Browse's viewport could not enter edit mode: open the editor in the
            # host's own viewport with the same prepared session.
            self.standalone_rust_process = None
            self.standalone_rust_ready_timer.stop()
            self._record_engine_edit_refusal(process, refusal)
            if getattr(process, "own_window", False):
                # Browse's process could not hold the tab's window: a process of its own.
                self._engine_window_refused_session = session
            else:
                self._leave_bound_viewport(refusal)
            self._launch_rust_editor_process(session)
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
        if getattr(self, "standalone_rust_parked", False):
            # Parked (P15 step 3): the view closed on purpose; the session stays.
            self.standalone_rust_closing = False
            if getattr(self, "standalone_rust_unpark_requested", False):
                self.unpark_rust_editor()  # shown again while it closed
                return
            self._set_rust_status(PARKED_STATUS)
            return
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
            (self.standalone_rust_process_error_reported
             or (not self.standalone_rust_closing and not self.standalone_rust_failure_reported))
            and self._recover_rust_editor_after_crash()
        ):
            # The shadow session outlives the renderer (P4 V3): nothing is disposed.
            self._clear_rust_commands()
            return
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
        self._clear_rust_commands()  # the editor's commands leave with its helper
        release = getattr(self, "_release_viewport_binding", None)
        if callable(release):  # Browse's viewport shows its own scene again
            release()
        closed = getattr(self, "closed", None)  # the live-edit component's signal
        if closed is not None and hasattr(closed, "emit"):
            closed.emit()

    def _record_engine_edit_refusal(self, process: object, reason: str) -> None:
        """Name in the runtime record why Browse's process did not hold this edit."""

        try:
            window = self.window()
        except (AttributeError, RuntimeError, TypeError):
            return
        recorder = getattr(window, "_record_runtime_event", None)
        if callable(recorder):
            try:
                # A warning, so the diagnostics log keeps it without verbose logging.
                recorder("mesh_editor_engine_edit_refused", severity="warning", reason=str(reason),
                         own_window=bool(getattr(process, "own_window", False)))
            except (RuntimeError, TypeError, ValueError):
                pass

    def _recover_rust_editor_after_crash(self) -> bool:
        """Keep the shadow session when the renderer exits unexpectedly (P4 V3).

        The first crash starts a new renderer and enters the edit again at the last
        accepted step. A second one within a minute stops retrying and offers Finish
        or Discard without a viewport. False: not recoverable (it never opened).
        """

        session = self.standalone_rust_authoring_session
        if (session is None or getattr(session, "closed", True) or not self.standalone_rust_hello_received
                or not callable(getattr(session, "rewrite_for_relaunch", None))):
            return False
        now = time.monotonic()
        previous = float(getattr(self, "_rust_last_crash_at", 0.0) or 0.0)
        self._rust_last_crash_at = now
        self.standalone_rust_ready = False
        self.standalone_rust_hello_received = False
        # The session is kept: a failure path that ran first (Qt reports a crash
        # as an error, then as finished) must not dispose it when a request ends
        # (section 8.7 A7).
        self.standalone_rust_dispose_pending = False
        self.standalone_rust_closing = False
        host = getattr(self, "standalone_native_host_frame", None)
        if previous and now - previous < _RUST_CRASH_RETRY_WINDOW_S:
            message = ("The 3D view stopped again. Your edits up to the last completed step are kept; "
                       "choose Finish or Discard.")
            show_error = getattr(host, "show_error", None)
            if callable(show_error):
                show_error(message)
            self._set_rust_status(message, error=True)
            QTimer.singleShot(0, self, lambda current=session: self._offer_finish_or_discard_after_crash(current))
            return True
        message = ("The 3D view stopped and was restarted. Your edits up to the last completed step are kept; "
                   "the step in progress was lost.")
        show_loading = getattr(host, "show_loading", None)
        if callable(show_loading):
            show_loading(message)
        self._set_rust_status(message, error=True)
        QTimer.singleShot(0, self, lambda current=session: self._rewrite_rust_session_after_crash(current))
        return True

    def _rewrite_rust_session_after_crash(self, session: object) -> None:
        if session is not self.standalone_rust_authoring_session or getattr(session, "closed", True):
            return
        if self.standalone_rust_protocol_thread is not None or self.standalone_rust_prepare_thread is not None:
            # A request still finishing against the shadow: write the files after it.
            QTimer.singleShot(100, self, lambda current=session: self._rewrite_rust_session_after_crash(current))
            return
        self.standalone_rust_process_generation += 1
        generation = self.standalone_rust_process_generation
        done = self.crash_rewrite_done

        def rewrite() -> None:
            try:
                session.rewrite_for_relaunch(generation)
            except Exception as exc:  # reported on the UI thread
                done.emit(session, f"{type(exc).__name__}: {exc}")
                return
            done.emit(session, "")

        threading.Thread(target=rewrite, name="cdmw-mesh-editor-crash-rewrite", daemon=True).start()

    def _relaunch_rust_editor_after_crash(self, session: object, error: str) -> None:
        if session is not self.standalone_rust_authoring_session or getattr(session, "closed", True):
            return
        if error:
            self.standalone_rust_failure_reported = False
            self._fail_rust_editor(f"Mesh Editor could not restart after its 3D view stopped: {error}")
            return
        self.standalone_rust_closing = False
        self.standalone_rust_failure_reported = False
        self.standalone_rust_process_error_reported = False
        self.standalone_rust_finish_accepted = False
        # A new helper (after a crash or a park) says hello once and numbers its
        # requests from 1 again (section 8.7 A3 and A4).
        self.standalone_rust_hello_received = False
        self.standalone_rust_ready = False
        self.standalone_rust_last_client_request_id = 0
        self.standalone_rust_stdout_buffer = b""
        self.standalone_rust_dispose_pending = False
        self._launch_rust_editor_process(session)

    def _offer_finish_or_discard_after_crash(self, session: object) -> None:
        """Second crash: no viewport; Finish or Discard the shadow session."""

        global _crash_prompt_open

        if session is not self.standalone_rust_authoring_session or getattr(session, "closed", True):
            return
        if _crash_prompt_open:
            # One shared process ended for several documents: ask about each in
            # turn, never one box over another (section 8.7 F3).
            QTimer.singleShot(250, self, lambda current=session: self._offer_finish_or_discard_after_crash(current))
            return
        from PySide6.QtWidgets import QMessageBox

        target = getattr(self, "_current_target_entry", None)
        try:
            entry = target() if callable(target) else None
        except (AttributeError, RuntimeError, TypeError):
            entry = None
        name = str(getattr(entry, "basename", "") or getattr(entry, "path", "") or "")
        box = QMessageBox(self.window() if callable(getattr(self, "window", None)) else None)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Mesh Editor Stopped")
        box.setText(f"The 3D view of {name} stopped twice within a minute." if name
                    else "The 3D view stopped twice within a minute.")
        box.setInformativeText("Your edits up to the last completed step are kept. Finish keeps them as a "
                               "pending edit; Discard drops them.")
        finish = box.addButton("Finish", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        _crash_prompt_open = True
        try:
            answer = crash_prompt_override(box) if crash_prompt_override is not None else None
            if answer is None:
                box.exec()
                answer = "finish" if box.clickedButton() is finish else "discard"
        finally:
            _crash_prompt_open = False
        if session is not self.standalone_rust_authoring_session or getattr(session, "closed", True):
            return
        if answer == "finish":
            self.standalone_rust_host_request_id += 1
            self.standalone_rust_protocol_queue.append(self._rust_host_message(
                "finish_request", request_id=self.standalone_rust_host_request_id, extra={"hidden_parts": []}))
            self._start_next_rust_protocol_worker()
            return
        if session is not None:
            session.discard_requested = True  # the user chose Discard
        self.standalone_rust_closing = True
        self.standalone_rust_dispose_pending = True
        self._schedule_rust_session_dispose()
        release = getattr(self, "_release_viewport_binding", None)
        if callable(release):
            release()
        closed = getattr(self, "closed", None)
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

    def park_rust_editor(self) -> bool:
        """Close this document's 3D view to free its memory, keeping its session (P15 step 3).

        The shadow session, its session files, its edit and its history stay; only
        the editor's window and its GPU resources go. ``unpark_rust_editor`` opens
        the view again from the session files, as a restart after a crash does.
        False when the editor is not idle (a request or Finish is running).
        """

        session = self.standalone_rust_authoring_session
        process = self.standalone_rust_process
        if (session is None or getattr(session, "closed", True) or process is None
                or not self.standalone_rust_ready or getattr(self, "standalone_rust_parked", False)):
            return False
        if (self._rust_finish_protocol_active() or self.standalone_rust_protocol_thread is not None
                or self.standalone_rust_prepare_thread is not None):
            return False
        self.standalone_rust_parked = True
        self.standalone_rust_ready = False
        self.standalone_rust_host_request_id += 1
        if not self._send_rust_message(self._rust_host_message("cancel", request_id=self.standalone_rust_host_request_id)):
            self.standalone_rust_parked = False
            self.standalone_rust_ready = True
            return False
        return True

    def unpark_rust_editor(self) -> bool:
        """Open a parked document's 3D view again at its last accepted step."""

        if not getattr(self, "standalone_rust_parked", False):
            return False
        session = self.standalone_rust_authoring_session
        if session is None or getattr(session, "closed", True):
            self.standalone_rust_parked = False
            return False
        if self.standalone_rust_process is not None:
            # Its view is still closing: it stays parked until the helper has exited,
            # so that exit is no crash, and opens again then (section 8.8 R13).
            self.standalone_rust_unpark_requested = True
            self._set_rust_status("Opening this document's 3D view again...")
            return True
        self.standalone_rust_parked = False
        self.standalone_rust_unpark_requested = False
        self._set_rust_status("Opening this document's 3D view again...")
        self._rewrite_rust_session_after_crash(session)
        return True

    def _stop_rust_editor_process(self, *, reason: str = "") -> None:
        hair_context = getattr(self, "_hair_context_preparation", None)
        self._hair_entry_generation = getattr(self, "_hair_entry_generation", 0) + 1
        if hair_context is not None:
            hair_context.cancel()
        self.standalone_rust_closing = True
        self.standalone_rust_ready = False
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
            release = getattr(self, "_release_viewport_binding", None)
            if callable(release):  # stopped before its session opened: Browse shows its own view again
                release()
        if reason:
            self._set_rust_status(reason)
