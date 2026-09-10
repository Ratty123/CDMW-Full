"""Rust Mesh Editor process protocol, diagnostics, and shutdown."""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib import import_module
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QThread, QTimer

from cdmw.services.mesh_rust_contract import (
    RUST_MESH_EDIT_BACKEND,
    RUST_MESH_EDITOR_PROTOCOL,
    RUST_MESH_RENDERER,
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

_RUST_PROTOCOL_QUEUE_LIMIT = 128
_RUST_READY_TIMEOUT_MS = 10_000
_RUST_FINISH_EXIT_TIMEOUT_MS = 3_000
_RUST_DIAGNOSTIC_BUFFER_LIMIT = 16 * 1024
_RUST_DIAGNOSTIC_TEXT_LIMIT = 2 * 1024
_RUST_DIAGNOSTIC_LINE_LIMIT = 8


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
        self.standalone_rust_process = process
        register_owned_qprocess_for_exit(process)
        self._set_rust_status("Launching the embedded Mesh Editor...")
        process.start()

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
            chunk = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        except RuntimeError:
            return
        self.standalone_rust_stdout_buffer += chunk
        if len(self.standalone_rust_stdout_buffer) > DOTNET_PROTOCOL_BUFFER_LIMIT:
            self._fail_rust_editor("Mesh Editor protocol buffer exceeded its limit.", incompatible=True)
            return
        while "\n" in self.standalone_rust_stdout_buffer:
            line, self.standalone_rust_stdout_buffer = self.standalone_rust_stdout_buffer.split("\n", 1)
            line = line.rstrip("\r")
            if not line:
                continue
            if len(line) > DOTNET_PROTOCOL_LINE_LIMIT:
                self._fail_rust_editor("Mesh Editor sent an oversized protocol message.", incompatible=True)
                return
            try:
                payload = json.loads(line)
            except ValueError:
                self._fail_rust_editor("Mesh Editor wrote non-JSON data to its control stream.", incompatible=True)
                return
            if not isinstance(payload, dict):
                self._fail_rust_editor("Mesh Editor protocol message was not an object.", incompatible=True)
                return
            self._handle_rust_protocol_event(payload)

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
        if event == "hello":
            self._handle_rust_hello(payload)
            return
        if event == "ready":
            self._handle_rust_ready(payload)
            return
        if event == "state_snapshot":
            return
        if event == "error":
            message = str(payload.get("message", "") or "Rust renderer reported an error")
            self._fail_rust_editor(message)
            return
        if event not in {"transaction_request", "command_request", "finish_request", "cancel"}:
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
        self._send_rust_message(
            self._rust_host_message(
                "hello",
                request_id=0,
                extra={"host": "cdmw", "status": "accepted"},
            )
        )

    def _handle_rust_ready(self, _payload: Mapping[str, object]) -> None:
        if not self.standalone_rust_hello_received:
            self._fail_rust_editor("Mesh Editor became ready before hello.", incompatible=True)
            return
        self.standalone_rust_ready_timer.stop()
        self.standalone_rust_ready = True
        self._send_rust_theme_update()
        host = getattr(self, "standalone_native_host_frame", None)
        show_editor = getattr(host, "show_editor", None)
        if callable(show_editor):
            show_editor()
        if self.standalone_rust_texture_unavailable_reason:
            self._set_rust_status(
                "Mesh Editor will use an untextured neutral surface: "
                f"{self.standalone_rust_texture_unavailable_reason}",
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
        preparation_error = ""
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
        self._send_rust_message(response)
        if finish_accepted:
            self.standalone_rust_finish_accepted = True
            self.standalone_rust_ready = False
            self._refresh_after_rust_finish(response)
            self.standalone_rust_finish_timer.start(_RUST_FINISH_EXIT_TIMEOUT_MS)
        elif str(active_event.get("event", "") or "") == "cancel":
            self.standalone_rust_closing = True
            self._stop_rust_editor_process(reason="Mesh Editor cancelled; CDMW mesh unchanged.")
        else:
            self._set_rust_status("Mesh Editor command completed.")

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
        self._send_rust_error_response(request, message, recovery=recovery)
        if self.standalone_rust_closing and str(
            request.get("event", "") or ""
        ).strip().lower() == "finish_request":
            self._set_rust_status(
                "Mesh Editor Finish was cancelled before commit; authoritative geometry is unchanged."
            )
        else:
            self._set_rust_status(f"Mesh Editor rejected the operation: {message}", error=True)

    def _handle_rust_protocol_thread_finished(self, thread: QThread) -> None:
        if self.standalone_rust_protocol_thread is not thread:
            return
        self.standalone_rust_protocol_thread = None
        self.standalone_rust_protocol_worker = None
        self.standalone_rust_active_event = None
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
        data = (json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
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
                "CDMW accepted the validated mesh revision. Choose an output action, reopen editing, or close the session."
            )
        self._set_rust_status("Mesh Editor finished and CDMW accepted the validated geometry.")

    def _handle_rust_ready_timeout(self) -> None:
        if self.standalone_rust_ready:
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
        finish_still_running = self._rust_finish_protocol_active()
        if finish_still_running:
            session = self.standalone_rust_authoring_session
            if session is not None and not session.closed:
                session.request_cancel()
            self.standalone_rust_stop_after_protocol = True
            self._set_rust_status(
                "Mesh Editor closed while Finish was running; waiting for the safe terminal result."
            )
        elif self.standalone_rust_finish_accepted:
            show_result = getattr(host, "show_result", None)
            if callable(show_result):
                show_result(
                    "CDMW accepted the validated mesh revision. Choose an output action, reopen editing, or close the session."
                )
            self._set_rust_status("Mesh Editor finished and CDMW accepted the validated geometry.")
        elif (
            self.standalone_rust_process_error_reported
            or not self.standalone_rust_failure_reported
        ):
            suffix = self._rust_process_diagnostic_suffix()
            self._set_rust_status(
                f"Mesh Editor closed (exit {int(exit_code)}); its shadow changes were discarded.{suffix}",
                error=bool(exit_code) or self.standalone_rust_process_error_reported,
            )
            show_error = getattr(host, "show_error", None)
            if callable(show_error):
                show_error(
                    f"Mesh Editor closed unexpectedly. Its unaccepted changes were discarded.{suffix}"
                )
        self.standalone_rust_closing = True
        self.standalone_rust_dispose_pending = True
        self._schedule_rust_session_dispose()

    def _fail_rust_editor(self, message: str, *, incompatible: bool = False) -> None:
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
        self.standalone_rust_closing = True
        self.standalone_rust_ready = False
        picker = getattr(self, "_archive_refit_picker", None)
        if picker is not None:
            picker.request_shutdown()
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
