"""Resident, nonblocking QProcess client for the full-CDMW archive worker."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Callable, Mapping, Sequence
from uuid import uuid4

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from cdmw.domain.archives.catalogue import ArchiveSessionHandle
from cdmw.domain.archives.catalogue_operations import (
    ARCHIVE_BACKEND_MAXIMUM_MESSAGE_BYTES,
    ARCHIVE_BACKEND_PROTOCOL_VERSION,
    ArchiveBackendEnvelope,
    ArchiveBackendError,
    ArchiveBackendOperation,
    ArchiveBackendStatus,
    CancelRequest,
    PingRequest,
    PingResult,
)
from cdmw.domain.archives.catalogue_wire import ArchiveContractError, to_wire
from cdmw.services.process_control_service import force_stop_windows_process_tree
from cdmw.ui.shell.archive_backend_resources import resolve_archive_backend_worker


ARCHIVE_BACKEND_STDERR_LIMIT = 64 * 1024
ARCHIVE_BACKEND_START_TIMEOUT_MS = 10_000
ARCHIVE_BACKEND_SHUTDOWN_GRACE_MS = 1_000
ARCHIVE_BACKEND_TERMINATE_GRACE_MS = 1_000


class ArchiveBackendClientState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    HANDSHAKING = "handshaking"
    READY = "ready"
    STOPPING = "stopping"
    FAILED = "failed"


_AUTOMATIC_RETRY_OPERATIONS = frozenset(
    {
        ArchiveBackendOperation.CACHE_HEALTH,
        ArchiveBackendOperation.OPEN_ARCHIVE,
    }
)


@dataclass(slots=True)
class _PendingRequest:
    envelope: ArchiveBackendEnvelope
    expected_session_id: str | None
    expected_fingerprint: str | None
    sent: bool = False
    retries: int = 0


class ArchiveBackendClient(QObject):
    """Own one worker process and correlate bounded protocol messages."""

    state_changed = Signal(str)
    worker_ready = Signal()
    worker_crashed = Signal(str)
    diagnostics_changed = Signal(str)
    request_started = Signal(str)
    request_progress = Signal(str, object)
    request_batch = Signal(str, object)
    request_succeeded = Signal(str, object)
    request_failed = Signal(str, object)
    request_cancelled = Signal(str)
    response_rejected = Signal(str, str)

    def __init__(
        self,
        *,
        cache_root: Path | str,
        worker_executable: Path | str | None = None,
        worker_program: Path | str | None = None,
        worker_arguments: Sequence[str] = (),
        client_version: str = "cdmw-python-v2",
        process_factory: Callable[[QObject], QProcess] = QProcess,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if worker_executable is not None and worker_program is not None:
            raise ValueError("Specify worker_executable or worker_program, not both.")
        self._cache_root = Path(cache_root).expanduser().resolve()
        self._explicit_worker = worker_executable
        self._worker_program = Path(worker_program).expanduser().resolve() if worker_program else None
        self._worker_arguments = tuple(str(argument) for argument in worker_arguments)
        self._client_version = str(client_version or "cdmw-python-v2")
        self._process_factory = process_factory
        self._process: QProcess | None = None
        self._state = ArchiveBackendClientState.STOPPED
        self._stdout_buffer = bytearray()
        self._stderr_tail = bytearray()
        self._pending: dict[str, _PendingRequest] = {}
        self._queued_request_ids: deque[str] = deque()
        self._session_fingerprints: dict[str, str] = {}
        self._control_request_ids: set[str] = set()
        self._minimum_ui_generation = 0
        self._handshake_request_id: str | None = None
        self._shutdown_request_id: str | None = None
        self._expected_stop = False
        self._resident_requested = False
        self._automatic_restart_used = False
        self._process_generation = 0

        self._start_timer = QTimer(self)
        self._start_timer.setSingleShot(True)
        self._start_timer.timeout.connect(self._handle_start_timeout)
        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.setSingleShot(True)
        self._shutdown_timer.timeout.connect(self._terminate_after_shutdown_grace)
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(self._kill_after_terminate_grace)

    @property
    def state(self) -> ArchiveBackendClientState:
        return self._state

    @property
    def diagnostics_tail(self) -> str:
        return bytes(self._stderr_tail).decode("utf-8", "replace")

    @property
    def is_ready(self) -> bool:
        return self._state is ArchiveBackendClientState.READY

    @property
    def process_id(self) -> int:
        process = self._process
        if process is None:
            return 0
        try:
            return int(process.processId())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return 0

    def submit(
        self,
        operation: ArchiveBackendOperation,
        payload: object,
        *,
        ui_generation: int,
        session_id: str | None = None,
        expected_fingerprint: str | None = None,
        request_id: str | None = None,
    ) -> str:
        if self._state is ArchiveBackendClientState.STOPPING:
            raise RuntimeError("Archive backend is shutting down.")
        envelope = ArchiveBackendEnvelope.request(
            operation,
            payload,
            ui_generation=ui_generation,
            session_id=session_id,
            request_id=request_id,
        )
        pending = _PendingRequest(
            envelope=envelope,
            expected_session_id=session_id,
            expected_fingerprint=expected_fingerprint,
        )
        self._pending[envelope.request_id] = pending
        self._queued_request_ids.append(envelope.request_id)
        self._resident_requested = True
        if self._state in {ArchiveBackendClientState.STOPPED, ArchiveBackendClientState.FAILED}:
            self._automatic_restart_used = False
        self._ensure_started()
        if self.is_ready:
            self._flush_queue()
        return envelope.request_id

    def cancel(self, request_id: str, *, ui_generation: int | None = None) -> bool:
        pending = self._pending.get(str(request_id))
        if pending is None:
            return False
        if not pending.sent:
            self._remove_queued_request(request_id)
            self._pending.pop(request_id, None)
            self.request_cancelled.emit(request_id)
            return True
        if not self.is_ready:
            return False
        generation = pending.envelope.ui_generation if ui_generation is None else int(ui_generation)
        self._send_cancel(request_id, generation)
        return True

    def invalidate_before(self, ui_generation: int) -> None:
        self._minimum_ui_generation = max(self._minimum_ui_generation, int(ui_generation))
        stale_ids = [
            request_id
            for request_id, pending in self._pending.items()
            if pending.envelope.ui_generation < self._minimum_ui_generation
        ]
        for request_id in stale_ids:
            pending = self._pending.pop(request_id)
            self._remove_queued_request(request_id)
            if pending.sent and self.is_ready:
                self._send_cancel(request_id, self._minimum_ui_generation)
            error = ArchiveBackendError(
                "stale_generation",
                "Archive backend response was invalidated by a newer UI generation.",
            )
            self.request_failed.emit(request_id, error)

    def shutdown(self) -> None:
        if self._state in {ArchiveBackendClientState.STOPPED, ArchiveBackendClientState.STOPPING}:
            return
        self._resident_requested = False
        self._expected_stop = True
        self._set_state(ArchiveBackendClientState.STOPPING)
        for request_id in tuple(self._pending):
            self._fail_request(
                request_id,
                ArchiveBackendError("client_shutdown", "Archive backend request stopped during application shutdown."),
            )
        if self._process_is_running() and self._handshake_request_id is None:
            self._shutdown_request_id = str(uuid4())
            envelope = ArchiveBackendEnvelope.request(
                ArchiveBackendOperation.SHUTDOWN,
                {},
                request_id=self._shutdown_request_id,
                ui_generation=self._minimum_ui_generation,
            )
            if self._write_envelope(envelope):
                self._shutdown_timer.start(ARCHIVE_BACKEND_SHUTDOWN_GRACE_MS)
                return
        self._terminate_after_shutdown_grace()

    def _ensure_started(self) -> None:
        if self._state in {
            ArchiveBackendClientState.STARTING,
            ArchiveBackendClientState.HANDSHAKING,
            ArchiveBackendClientState.READY,
            ArchiveBackendClientState.STOPPING,
        }:
            return
        try:
            if self._worker_program is not None:
                program = self._worker_program
            else:
                program = resolve_archive_backend_worker(self._explicit_worker)
        except (FileNotFoundError, OSError) as exc:
            self._set_state(ArchiveBackendClientState.FAILED)
            self._fail_all("worker_missing", str(exc))
            return

        process = self._process_factory(self)
        self._process_generation += 1
        generation = self._process_generation
        self._process = process
        self._stdout_buffer.clear()
        self._stderr_tail.clear()
        self._expected_stop = False
        self._handshake_request_id = None
        process.setProcessChannelMode(QProcess.SeparateChannels)
        try:
            process.setWorkingDirectory(str(program.parent))
        except (AttributeError, RuntimeError):
            pass
        process.started.connect(lambda: self._handle_process_started(process, generation))
        process.readyReadStandardOutput.connect(
            lambda: self._drain_stdout(process, generation)
        )
        process.readyReadStandardError.connect(
            lambda: self._drain_stderr(process, generation)
        )
        process.errorOccurred.connect(
            lambda error: self._handle_process_error(process, generation, error)
        )
        process.finished.connect(
            lambda code, status: self._handle_process_finished(process, generation, code, status)
        )
        arguments = [*self._worker_arguments, "--cache-root", str(self._cache_root)]
        self._set_state(ArchiveBackendClientState.STARTING)
        self._start_timer.start(ARCHIVE_BACKEND_START_TIMEOUT_MS)
        process.start(str(program), arguments)

    def _handle_process_started(self, process: QProcess, generation: int) -> None:
        if not self._is_current_process(process, generation) or self._state is ArchiveBackendClientState.STOPPING:
            return
        self._set_state(ArchiveBackendClientState.HANDSHAKING)
        self._start_timer.start(ARCHIVE_BACKEND_START_TIMEOUT_MS)
        self._handshake_request_id = str(uuid4())
        handshake = ArchiveBackendEnvelope.request(
            ArchiveBackendOperation.PING,
            PingRequest(self._client_version),
            request_id=self._handshake_request_id,
            ui_generation=self._minimum_ui_generation,
        )
        if not self._write_envelope(handshake):
            self._protocol_failure("Archive backend handshake could not be written.")

    def _drain_stdout(self, process: QProcess, generation: int) -> None:
        if not self._is_current_process(process, generation):
            return
        try:
            chunk = bytes(process.readAllStandardOutput())
        except (AttributeError, RuntimeError, TypeError):
            return
        if not chunk:
            return
        self._stdout_buffer.extend(chunk)
        while True:
            newline = self._stdout_buffer.find(b"\n")
            if newline < 0:
                if len(self._stdout_buffer) > ARCHIVE_BACKEND_MAXIMUM_MESSAGE_BYTES:
                    self._protocol_failure("Archive backend stdout exceeded the 1 MiB message bound.")
                return
            raw_line = bytes(self._stdout_buffer[:newline])
            del self._stdout_buffer[: newline + 1]
            if len(raw_line) > ARCHIVE_BACKEND_MAXIMUM_MESSAGE_BYTES:
                self._protocol_failure("Archive backend emitted an oversized protocol message.")
                return
            if raw_line.endswith(b"\r"):
                raw_line = raw_line[:-1]
            if raw_line:
                self._handle_protocol_line(raw_line)

    def _drain_stderr(self, process: QProcess, generation: int) -> None:
        if not self._is_current_process(process, generation):
            return
        try:
            chunk = bytes(process.readAllStandardError())
        except (AttributeError, RuntimeError, TypeError):
            return
        if not chunk:
            return
        self._stderr_tail.extend(chunk)
        if len(self._stderr_tail) > ARCHIVE_BACKEND_STDERR_LIMIT:
            del self._stderr_tail[:-ARCHIVE_BACKEND_STDERR_LIMIT]
        self.diagnostics_changed.emit(self.diagnostics_tail)

    def _handle_protocol_line(self, raw_line: bytes) -> None:
        try:
            text = raw_line.decode("utf-8", "strict")
            raw_message = json.loads(text)
            message = ArchiveBackendEnvelope.from_wire(raw_message)
        except (UnicodeDecodeError, json.JSONDecodeError, ArchiveContractError, TypeError, ValueError) as exc:
            self._protocol_failure(f"Archive backend emitted invalid protocol JSON: {exc}")
            return
        if message.protocol_version != ARCHIVE_BACKEND_PROTOCOL_VERSION:
            self._protocol_failure(
                f"Archive backend protocol {message.protocol_version} is incompatible with {ARCHIVE_BACKEND_PROTOCOL_VERSION}."
            )
            return
        if message.request_id == self._handshake_request_id:
            self._handle_handshake_message(message)
            return
        if message.request_id == self._shutdown_request_id:
            return
        if message.request_id in self._control_request_ids:
            if message.status in {
                ArchiveBackendStatus.RESULT,
                ArchiveBackendStatus.CANCELLED,
                ArchiveBackendStatus.ERROR,
            }:
                self._control_request_ids.discard(message.request_id)
            return
        pending = self._pending.get(message.request_id)
        if pending is None:
            self.response_rejected.emit(message.request_id, "unknown_or_stale_request")
            return
        rejection = self._correlation_rejection(pending, message)
        if rejection:
            self._fail_request(
                message.request_id,
                ArchiveBackendError("stale_response", "Archive backend response correlation failed.", rejection),
            )
            self.response_rejected.emit(message.request_id, rejection)
            return
        if message.status is ArchiveBackendStatus.STARTED:
            self.request_started.emit(message.request_id)
        elif message.status is ArchiveBackendStatus.PROGRESS:
            self.request_progress.emit(message.request_id, message.payload or {})
        elif message.status is ArchiveBackendStatus.BATCH:
            self.request_batch.emit(message.request_id, message.payload or {})
        elif message.status is ArchiveBackendStatus.RESULT:
            self._observe_success(message, pending)
            self._pending.pop(message.request_id, None)
            self._automatic_restart_used = False
            self.request_succeeded.emit(message.request_id, message.payload or {})
        elif message.status is ArchiveBackendStatus.CANCELLED:
            self._pending.pop(message.request_id, None)
            self.request_cancelled.emit(message.request_id)
        elif message.status is ArchiveBackendStatus.ERROR:
            self._pending.pop(message.request_id, None)
            self.request_failed.emit(
                message.request_id,
                message.error or ArchiveBackendError("worker_failure", "Archive backend request failed."),
            )

    def _handle_handshake_message(self, message: ArchiveBackendEnvelope) -> None:
        if message.status is ArchiveBackendStatus.STARTED:
            return
        if message.status is not ArchiveBackendStatus.RESULT or message.payload is None:
            detail = message.error.message if message.error is not None else "No compatibility result was returned."
            self._protocol_failure(f"Archive backend handshake failed: {detail}")
            return
        try:
            result = PingResult.from_wire(message.payload)
        except ArchiveContractError as exc:
            self._protocol_failure(f"Archive backend handshake was malformed: {exc}")
            return
        if result.protocol_version != ARCHIVE_BACKEND_PROTOCOL_VERSION or result.native_abi_version != 1 or result.index_version != 2:
            self._protocol_failure(
                "Archive backend compatibility mismatch "
                f"(protocol={result.protocol_version}, native={result.native_abi_version}, index={result.index_version})."
            )
            return
        self._handshake_request_id = None
        self._start_timer.stop()
        self._set_state(ArchiveBackendClientState.READY)
        self.worker_ready.emit()
        self._flush_queue()

    def _correlation_rejection(
        self,
        pending: _PendingRequest,
        message: ArchiveBackendEnvelope,
    ) -> str:
        request = pending.envelope
        if message.operation is not request.operation:
            return "operation_mismatch"
        if message.ui_generation != request.ui_generation:
            return "generation_mismatch"
        if message.ui_generation < self._minimum_ui_generation:
            return "stale_generation"
        if pending.expected_session_id is not None and message.session_id != pending.expected_session_id:
            return "session_mismatch"
        if pending.expected_fingerprint is not None:
            current = self._session_fingerprints.get(pending.expected_session_id or "")
            if current != pending.expected_fingerprint:
                return "fingerprint_mismatch"
        return ""

    def _observe_success(self, message: ArchiveBackendEnvelope, pending: _PendingRequest) -> None:
        if pending.envelope.operation not in {
            ArchiveBackendOperation.OPEN_ARCHIVE,
            ArchiveBackendOperation.REFRESH_ARCHIVE,
        } or message.payload is None:
            return
        try:
            session = ArchiveSessionHandle.from_wire(message.payload)
        except ArchiveContractError:
            return
        self._session_fingerprints[session.session_id] = session.fingerprint

    def _flush_queue(self) -> None:
        if not self.is_ready:
            return
        while self._queued_request_ids:
            request_id = self._queued_request_ids.popleft()
            pending = self._pending.get(request_id)
            if pending is None or pending.sent:
                continue
            if pending.envelope.ui_generation < self._minimum_ui_generation:
                self._fail_request(
                    request_id,
                    ArchiveBackendError("stale_generation", "Archive backend request was superseded before dispatch."),
                )
                continue
            if not self._write_envelope(pending.envelope):
                self._fail_request(
                    request_id,
                    ArchiveBackendError("write_failed", "Archive backend request could not be written."),
                )
                self._protocol_failure("Archive backend stdin rejected a complete request.")
                return
            pending.sent = True

    def _write_envelope(self, envelope: ArchiveBackendEnvelope) -> bool:
        process = self._process
        if process is None or not self._process_is_running():
            return False
        try:
            data = (json.dumps(to_wire(envelope), separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        except (TypeError, ValueError):
            return False
        if len(data) - 1 > ARCHIVE_BACKEND_MAXIMUM_MESSAGE_BYTES:
            return False
        try:
            return int(process.write(data)) == len(data)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False

    def _send_cancel(self, target_request_id: str, ui_generation: int) -> None:
        cancel = ArchiveBackendEnvelope.request(
            ArchiveBackendOperation.CANCEL,
            CancelRequest(target_request_id),
            ui_generation=ui_generation,
        )
        if self._write_envelope(cancel):
            self._control_request_ids.add(cancel.request_id)

    def _handle_start_timeout(self) -> None:
        if self._state not in {ArchiveBackendClientState.STARTING, ArchiveBackendClientState.HANDSHAKING}:
            return
        self._protocol_failure("Archive backend did not become ready within 10 seconds.")

    def _handle_process_error(
        self,
        process: QProcess,
        generation: int,
        error: object,
    ) -> None:
        if not self._is_current_process(process, generation):
            return
        self._drain_stderr(process, generation)
        if self._state is ArchiveBackendClientState.STARTING:
            self._set_state(ArchiveBackendClientState.FAILED)
            self._fail_all("process_start_failed", f"Archive backend process failed to start: {error}")

    def _handle_process_finished(
        self,
        process: QProcess,
        generation: int,
        exit_code: int,
        exit_status: object,
    ) -> None:
        if not self._is_current_process(process, generation):
            return
        self._drain_stdout(process, generation)
        self._drain_stderr(process, generation)
        self._start_timer.stop()
        self._shutdown_timer.stop()
        self._kill_timer.stop()
        self._process = None
        self._handshake_request_id = None
        self._shutdown_request_id = None
        self._control_request_ids.clear()
        self._session_fingerprints.clear()
        try:
            process.deleteLater()
        except RuntimeError:
            pass
        if self._expected_stop or self._state is ArchiveBackendClientState.STOPPING:
            self._expected_stop = False
            self._set_state(ArchiveBackendClientState.STOPPED)
            return

        detail = self.diagnostics_tail.strip() or f"exit code {exit_code}, status {exit_status}"
        self.worker_crashed.emit(detail)
        retry_ids: list[str] = []
        for request_id, pending in tuple(self._pending.items()):
            if (
                pending.envelope.operation in _AUTOMATIC_RETRY_OPERATIONS
                and pending.retries < 1
                and not self._automatic_restart_used
            ):
                pending.retries += 1
                pending.sent = False
                retry_ids.append(request_id)
            else:
                self._fail_request(
                    request_id,
                    ArchiveBackendError(
                        "worker_crashed",
                        "Archive backend stopped unexpectedly; this operation was not automatically retried.",
                        detail,
                    ),
                )
        self._queued_request_ids = deque(retry_ids)
        should_restart = not self._automatic_restart_used and (bool(retry_ids) or self._resident_requested)
        if should_restart:
            self._automatic_restart_used = True
            self._set_state(ArchiveBackendClientState.STOPPED)
            QTimer.singleShot(0, self._ensure_started)
        else:
            self._set_state(ArchiveBackendClientState.FAILED)

    def _protocol_failure(self, message: str) -> None:
        self._append_diagnostic(message)
        process = self._process
        if process is None or not self._process_is_running():
            self._set_state(ArchiveBackendClientState.FAILED)
            self._fail_all("protocol_failure", message)
            return
        try:
            process.kill()
        except (AttributeError, RuntimeError):
            self._set_state(ArchiveBackendClientState.FAILED)
            self._fail_all("protocol_failure", message)

    def _terminate_after_shutdown_grace(self) -> None:
        self._shutdown_timer.stop()
        process = self._process
        if process is None or not self._process_is_running():
            self._set_state(ArchiveBackendClientState.STOPPED)
            return
        try:
            process.terminate()
        except (AttributeError, RuntimeError):
            pass
        self._kill_timer.start(ARCHIVE_BACKEND_TERMINATE_GRACE_MS)

    def _kill_after_terminate_grace(self) -> None:
        process = self._process
        if process is None or not self._process_is_running():
            return
        process_id = self.process_id
        if process_id > 0:
            force_stop_windows_process_tree(process_id, include_root=False)
        try:
            process.kill()
        except (AttributeError, RuntimeError):
            pass

    def _process_is_running(self) -> bool:
        process = self._process
        if process is None:
            return False
        try:
            return process.state() != QProcess.NotRunning
        except (AttributeError, RuntimeError):
            return False

    def _is_current_process(self, process: QProcess, generation: int) -> bool:
        return self._process is process and self._process_generation == generation

    def _remove_queued_request(self, request_id: str) -> None:
        self._queued_request_ids = deque(
            queued for queued in self._queued_request_ids if queued != request_id
        )

    def _fail_request(self, request_id: str, error: ArchiveBackendError) -> None:
        if self._pending.pop(request_id, None) is not None:
            self._remove_queued_request(request_id)
            self.request_failed.emit(request_id, error)

    def _fail_all(self, code: str, message: str) -> None:
        for request_id in tuple(self._pending):
            self._fail_request(request_id, ArchiveBackendError(code, message, self.diagnostics_tail or None))

    def _append_diagnostic(self, value: str) -> None:
        data = (str(value or "") + "\n").encode("utf-8", "replace")
        self._stderr_tail.extend(data)
        if len(self._stderr_tail) > ARCHIVE_BACKEND_STDERR_LIMIT:
            del self._stderr_tail[:-ARCHIVE_BACKEND_STDERR_LIMIT]
        self.diagnostics_changed.emit(self.diagnostics_tail)

    def _set_state(self, state: ArchiveBackendClientState) -> None:
        if self._state is state:
            return
        self._state = state
        self.state_changed.emit(state.value)


__all__ = [
    "ARCHIVE_BACKEND_SHUTDOWN_GRACE_MS",
    "ARCHIVE_BACKEND_START_TIMEOUT_MS",
    "ARCHIVE_BACKEND_STDERR_LIMIT",
    "ARCHIVE_BACKEND_TERMINATE_GRACE_MS",
    "ArchiveBackendClient",
    "ArchiveBackendClientState",
]
