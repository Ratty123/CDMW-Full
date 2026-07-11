from __future__ import annotations

import ctypes
from importlib import import_module
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from typing import Mapping

if os.name == "nt":
    import msvcrt

from cdmw.core.common import (
    BoundedTextTail,
    ProcessTimeoutExpired,
    finish_process_tree,
    hidden_process_group_kwargs,
    raise_if_cancelled,
    read_bounded_text_line,
    start_bounded_text_stream_drain,
)
from cdmw.models import RunCancelled

_MESH_CORE_PROTOCOL_LINE_MAX_BYTES = 16 * 1024 * 1024


def _clear_native_mesh_core_session_cache() -> None:
    import_module("cdmw.modding.mesh_native_core")._clear_native_mesh_core_session_cache()


class NativeMeshCoreServiceClient:
    """Persistent JSON-line client for cdmw-mesh-core.exe helper jobs."""

    def __init__(self, binary: Path) -> None:
        self.binary = Path(binary)
        self.binary_signature = self.resolve_binary_signature(self.binary)
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._jobs_completed = 0
        self._stdout_thread: threading.Thread | None = None
        self._stdout_lines: queue.Queue[object] = queue.Queue(maxsize=8)
        self._stdout_stream: object | None = None
        self._stdout_buffer = bytearray()
        self._stderr_thread: threading.Thread | None = None
        self._stderr_tail = BoundedTextTail()

    @staticmethod
    def resolve_binary_signature(binary: Path) -> tuple[int, int]:
        try:
            stat_result = Path(binary).stat()
        except OSError:
            return (0, 0)
        return (int(getattr(stat_result, "st_mtime_ns", 0) or 0), int(getattr(stat_result, "st_size", 0) or 0))

    def shutdown(self) -> None:
        with self._lock:
            _clear_native_mesh_core_session_cache()
            process = self._process
            self._process = None
            self._jobs_completed = 0
            if process is None:
                return
            shutdown_requested = False
            try:
                if process.poll() is None and process.stdin is not None:
                    process.stdin.write('{"command":"shutdown"}\n')
                    process.stdin.flush()
                    shutdown_requested = True
            except OSError:
                pass
            finish_process_tree(process, grace_seconds=1.0, request_stop=not shutdown_requested)
            self._close_process_streams_locked(process)

    def _kill_locked(self) -> None:
        _clear_native_mesh_core_session_cache()
        process = self._process
        self._process = None
        self._jobs_completed = 0
        if process is None:
            return
        # A cancelled/failed service job cannot be reused safely. Kill this
        # child directly; cdmw-mesh-core owns no child processes. Fall back to
        # tree cleanup only if the direct termination does not complete.
        try:
            process.kill()
            process.wait(timeout=0.25)
        except (OSError, subprocess.TimeoutExpired):
            finish_process_tree(process, grace_seconds=0.0, request_stop=False)
        self._close_process_streams_locked(process)

    def _close_process_streams_locked(self, process: object) -> None:
        self._stdout_stream = None
        self._stdout_buffer.clear()
        for stream in (
            getattr(process, "stdin", None),
            getattr(process, "stdout", None),
            getattr(process, "stderr", None),
        ):
            close = getattr(stream, "close", None)
            if not callable(close):
                continue
            try:
                close()
            except (OSError, ValueError):
                pass
        stdout_thread = self._stdout_thread
        self._stdout_thread = None
        if stdout_thread is not None and stdout_thread is not threading.current_thread():
            stdout_thread.join(0.2)
        stderr_thread = self._stderr_thread
        self._stderr_thread = None
        if stderr_thread is not None and stderr_thread is not threading.current_thread():
            stderr_thread.join(0.2)

    @property
    def stderr_tail(self) -> str:
        return self._stderr_tail.text()

    def _read_stdout_line_locked(self, timeout_seconds: float, *, stop_event: threading.Event | None = None) -> str:
        process = self._process
        if process is None:
            raise RuntimeError("native mesh-core service is not running")
        if os.name == "nt" and self._stdout_stream is not None:
            return self._read_windows_stdout_line_locked(
                process,
                self._stdout_stream,
                timeout_seconds,
                stop_event=stop_event,
            )
        deadline = time.monotonic() + max(0.1, float(timeout_seconds))
        while True:
            try:
                raise_if_cancelled(stop_event, "Native mesh-core job cancelled.")
            except RunCancelled:
                self._kill_locked()
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                self._kill_locked()
                raise ProcessTimeoutExpired([str(self.binary), "--service"], float(timeout_seconds))
            try:
                item = self._stdout_lines.get(timeout=min(0.02, remaining))
            except queue.Empty:
                continue
            break
        if isinstance(item, BaseException):
            self._kill_locked()
            raise RuntimeError(f"native mesh-core service read failed: {item}") from item
        line = str(item or "").strip()
        if not line:
            self._kill_locked()
            raise RuntimeError("native mesh-core service closed its stdout")
        return line

    def _read_windows_stdout_line_locked(
        self,
        process: object,
        stream: object,
        timeout_seconds: float,
        *,
        stop_event: threading.Event | None = None,
    ) -> str:
        deadline = time.monotonic() + max(0.1, float(timeout_seconds))
        try:
            file_descriptor = stream.fileno()  # type: ignore[attr-defined]
            pipe_handle = msvcrt.get_osfhandle(file_descriptor)
        except (AttributeError, OSError, ValueError) as exc:
            self._kill_locked()
            raise RuntimeError(f"native mesh-core service stdout handle is unavailable: {exc}") from exc
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        peek_named_pipe = kernel32.PeekNamedPipe
        peek_named_pipe.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_void_p,
        ]
        peek_named_pipe.restype = ctypes.c_int
        spin_deadline = time.monotonic() + 0.002
        while True:
            newline = self._stdout_buffer.find(b"\n")
            if newline >= 0:
                raw = bytes(self._stdout_buffer[: newline + 1])
                del self._stdout_buffer[: newline + 1]
                return raw.decode("utf-8", errors="replace").strip()
            try:
                raise_if_cancelled(stop_event, "Native mesh-core job cancelled.")
            except RunCancelled:
                self._kill_locked()
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                self._kill_locked()
                raise ProcessTimeoutExpired([str(self.binary), "--service"], float(timeout_seconds))
            available = ctypes.c_uint32(0)
            if not peek_named_pipe(
                ctypes.c_void_p(pipe_handle),
                None,
                0,
                None,
                ctypes.byref(available),
                None,
            ):
                error = ctypes.get_last_error()
                self._kill_locked()
                raise OSError(error, "PeekNamedPipe failed for native mesh-core stdout")
            if available.value > 0:
                remaining_capacity = _MESH_CORE_PROTOCOL_LINE_MAX_BYTES + 1 - len(self._stdout_buffer)
                chunk = os.read(file_descriptor, min(int(available.value), max(1, remaining_capacity)))
                self._stdout_buffer.extend(chunk)
                if len(self._stdout_buffer) > _MESH_CORE_PROTOCOL_LINE_MAX_BYTES:
                    self._kill_locked()
                    raise ValueError("native mesh-core protocol line exceeds 16 MiB")
                spin_deadline = time.monotonic() + 0.002
                continue
            poll = getattr(process, "poll", None)
            if callable(poll) and poll() is not None:
                if self._stdout_buffer:
                    raw = bytes(self._stdout_buffer)
                    self._stdout_buffer.clear()
                    return raw.decode("utf-8", errors="replace").strip()
                self._kill_locked()
                raise RuntimeError("native mesh-core service closed its stdout")
            if time.monotonic() >= spin_deadline:
                time.sleep(min(0.001, remaining))

    def _start_stdout_reader_locked(self, stream: object) -> None:
        self._stdout_lines = queue.Queue(maxsize=8)

        def drain() -> None:
            while True:
                try:
                    line = read_bounded_text_line(stream)  # type: ignore[arg-type]
                    self._stdout_lines.put(line, timeout=0.1)
                except BaseException as exc:  # pragma: no cover - pipe teardown defense
                    try:
                        self._stdout_lines.put(exc, timeout=0.1)
                    except queue.Full:
                        pass
                    return
                if not line:
                    return

        self._stdout_thread = threading.Thread(
            target=drain,
            name="cdmw-mesh-core-stdout",
            daemon=True,
        )
        self._stdout_thread.start()

    def _start_locked(self, *, stop_event: threading.Event | None = None) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            return
        if process is not None:
            self._close_process_streams_locked(process)
        _clear_native_mesh_core_session_cache()
        self._jobs_completed = 0
        self._process = subprocess.Popen(
            [str(self.binary), "--service"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_process_group_kwargs(),
        )
        stderr = self._process.stderr
        stdout = self._process.stdout
        self._stderr_tail = BoundedTextTail()
        if stdout is None:
            self._kill_locked()
            raise RuntimeError("native mesh-core service stdout is unavailable")
        if os.name == "nt":
            self._stdout_stream = stdout
            self._stdout_buffer.clear()
        else:
            self._start_stdout_reader_locked(stdout)
        if stderr is not None:
            self._stderr_thread, self._stderr_tail = start_bounded_text_stream_drain(
                stderr,
                name="cdmw-mesh-core-stderr",
            )
        ready_line = self._read_stdout_line_locked(5.0, stop_event=stop_event)
        try:
            ready = json.loads(ready_line)
        except json.JSONDecodeError as exc:
            self._kill_locked()
            raise RuntimeError(f"native mesh-core service sent invalid ready line: {ready_line}") from exc
        if str(ready.get("event") or "").strip().lower() != "ready":
            self._kill_locked()
            raise RuntimeError(f"native mesh-core service did not become ready: {ready_line}")

    def run_job(
        self,
        command: str,
        job_path: Path,
        report_path: Path,
        *,
        timeout_seconds: float,
        stop_event: threading.Event | None = None,
    ) -> None:
        with self._lock:
            self._start_locked(stop_event=stop_event)
            process = self._process
            if process is None or process.stdin is None:
                raise RuntimeError("native mesh-core service stdin is unavailable")
            request = json.dumps(
                {"command": command, "job_path": str(job_path), "report_path": str(report_path)},
                separators=(",", ":"),
            )
            try:
                process.stdin.write(request + "\n")
                process.stdin.flush()
            except OSError as exc:
                self._kill_locked()
                raise RuntimeError(f"native mesh-core service write failed: {exc}") from exc
            response_line = self._read_stdout_line_locked(timeout_seconds, stop_event=stop_event)
            try:
                response = json.loads(response_line)
            except json.JSONDecodeError as exc:
                self._kill_locked()
                raise RuntimeError(f"native mesh-core service sent invalid response: {response_line}") from exc
            response_status = str(response.get("status") or response.get("event") or "").strip().lower()
            if response_status == "error" and not report_path.is_file():
                raise RuntimeError(str(response.get("message") or "native mesh-core service returned an error"))
            self._jobs_completed += 1

    def run_inline_job(
        self,
        command: str,
        payload: Mapping[str, object],
        *,
        timeout_seconds: float,
        stop_event: threading.Event | None = None,
    ) -> dict[str, object]:
        with self._lock:
            self._start_locked(stop_event=stop_event)
            process = self._process
            if process is None or process.stdin is None:
                raise RuntimeError("native mesh-core service stdin is unavailable")
            request = json.dumps(
                {"command": command, "payload": dict(payload)},
                separators=(",", ":"),
                allow_nan=False,
            )
            try:
                process.stdin.write(request + "\n")
                process.stdin.flush()
            except OSError as exc:
                self._kill_locked()
                raise RuntimeError(f"native mesh-core service write failed: {exc}") from exc
            response_line = self._read_stdout_line_locked(timeout_seconds, stop_event=stop_event)
            try:
                response = json.loads(response_line)
            except json.JSONDecodeError as exc:
                self._kill_locked()
                raise RuntimeError(f"native mesh-core service sent invalid response: {response_line}") from exc
            if not isinstance(response, dict):
                self._kill_locked()
                raise RuntimeError("native mesh-core service sent non-object response")
            response_status = str(response.get("status") or response.get("event") or "").strip().lower()
            if response_status == "error" and not isinstance(response.get("inline_report"), Mapping):
                raise RuntimeError(str(response.get("message") or "native mesh-core service returned an error"))
            self._jobs_completed += 1
            return response
