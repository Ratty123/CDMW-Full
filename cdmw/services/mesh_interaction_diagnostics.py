"""Bounded, non-blocking flight recorder for Mesh Editor sessions.

The resident .NET helper can emit pointer-driven protocol messages every
frame.  Serialising and appending each one from the Qt callback makes the
diagnostic trail part of the interaction hot path, so the act of recording a
freeze can cause the freeze.  This recorder copies each event into a bounded
queue and owns all filesystem work on one background thread.
"""

from __future__ import annotations

import atexit
import json
import os
import queue
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from pathlib import Path


MESH_INTERACTION_LOG_MAX_BYTES = 24 * 1024 * 1024
MESH_INTERACTION_QUEUE_LIMIT = 8192
MESH_INTERACTION_RECENT_LIMIT = 512


def _recent_event_summary(row: Mapping[str, object]) -> dict[str, object]:
    """Keep the in-memory diagnostics view useful without retaining meshes."""

    summary: dict[str, object] = {}
    for key, value in row.items():
        if value is None or isinstance(value, (bool, int, float, str)):
            summary[str(key)] = value
        elif isinstance(value, Mapping):
            summary[str(key)] = {
                "value_type": "mapping",
                "item_count": len(value),
            }
        elif isinstance(value, (list, tuple, set, frozenset)):
            summary[str(key)] = {
                "value_type": type(value).__name__,
                "item_count": len(value),
            }
        else:
            summary[str(key)] = {"value_type": type(value).__name__}
    return summary


def default_mesh_interaction_log_path() -> Path:
    """Resolve the diagnostic bundle's current-session JSONL path."""

    crash_dir = str(os.environ.get("CDMW_CRASH_DIR", "") or "").strip()
    if crash_dir:
        directory = Path(crash_dir)
    else:
        from cdmw.domain.workspace import workspace_paths
        from cdmw.services.settings_service import resolve_settings_file_path

        directory = Path(
            workspace_paths(resolve_settings_file_path().parent)["crash_reports_dir"]
        )
    return directory / "dotnet_protocol_current.jsonl"


class MeshInteractionFlightRecorder:
    """Persist a bounded JSONL trail without blocking the event producer."""

    _STOP = object()

    def __init__(
        self,
        path_resolver: Callable[[], Path] = default_mesh_interaction_log_path,
        *,
        max_bytes: int = MESH_INTERACTION_LOG_MAX_BYTES,
        queue_limit: int = MESH_INTERACTION_QUEUE_LIMIT,
        recent_limit: int = MESH_INTERACTION_RECENT_LIMIT,
    ) -> None:
        self._path_resolver = path_resolver
        self._max_bytes = max(1, int(max_bytes))
        self._queue: queue.Queue[dict[str, object] | object] = queue.Queue(
            maxsize=max(1, int(queue_limit))
        )
        self._recent: deque[dict[str, object]] = deque(
            maxlen=max(1, int(recent_limit))
        )
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_requested = threading.Event()
        self._accepted = 0
        self._written = 0
        self._dropped_queue_full = 0
        self._dropped_size_cap = 0
        self._serialization_errors = 0
        self._write_errors = 0
        self._maximum_queue_depth = 0
        self._written_bytes = 0
        self._path = ""
        self._last_error = ""

    def record(
        self,
        kind: str,
        direction: str,
        payload: Mapping[str, object],
        *,
        critical: bool = False,
    ) -> bool:
        """Queue one shallow event snapshot and return immediately."""

        row = {str(key): value for key, value in payload.items()}
        row.update(
            {
                "recorded_at_utc": round(time.time(), 6),
                "monotonic_ns": time.perf_counter_ns(),
                "kind": str(kind or "event"),
                "direction": str(direction or "internal"),
            }
        )
        with self._lock:
            self._recent.append(_recent_event_summary(row))
        self._ensure_started()
        try:
            self._queue.put_nowait(row)
        except queue.Full:
            if not critical or not self._make_room_for_critical_event():
                with self._lock:
                    self._dropped_queue_full += 1
                return False
            try:
                self._queue.put_nowait(row)
            except queue.Full:
                with self._lock:
                    self._dropped_queue_full += 1
                return False
        depth = self._queue.qsize()
        with self._lock:
            self._accepted += 1
            self._maximum_queue_depth = max(self._maximum_queue_depth, depth)
        return True

    def _make_room_for_critical_event(self) -> bool:
        try:
            discarded = self._queue.get_nowait()
        except queue.Empty:
            return False
        self._queue.task_done()
        if discarded is self._STOP:
            try:
                self._queue.put_nowait(discarded)
            except queue.Full:
                pass
            return False
        with self._lock:
            self._dropped_queue_full += 1
        return True

    def _ensure_started(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(
                target=self._run,
                name="cdmw-mesh-interaction-log",
                daemon=True,
            )
            self._thread.start()

    def _run(self) -> None:
        handle = None
        try:
            path = Path(self._path_resolver())
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = path.open("w", encoding="utf-8", buffering=64 * 1024)
            with self._lock:
                self._path = str(path)
            while True:
                try:
                    item = self._queue.get(timeout=0.1)
                except queue.Empty:
                    if self._stop_requested.is_set():
                        break
                    continue
                try:
                    if item is self._STOP:
                        break
                    self._write_row(handle, item)
                    for _index in range(127):
                        try:
                            queued = self._queue.get_nowait()
                        except queue.Empty:
                            break
                        try:
                            if queued is self._STOP:
                                self._stop_requested.set()
                                break
                            self._write_row(handle, queued)
                        finally:
                            self._queue.task_done()
                    handle.flush()
                finally:
                    self._queue.task_done()
        except Exception as exc:
            with self._lock:
                self._write_errors += 1
                self._last_error = f"{type(exc).__name__}: {exc}"
            self._drain_unwritten()
        finally:
            if handle is not None:
                try:
                    handle.flush()
                    handle.close()
                except OSError as exc:
                    with self._lock:
                        self._write_errors += 1
                        self._last_error = f"{type(exc).__name__}: {exc}"

    def _write_row(self, handle: object, row: object) -> None:
        if not isinstance(row, Mapping):
            return
        try:
            line = json.dumps(dict(row), default=str, separators=(",", ":")) + "\n"
        except Exception as exc:
            with self._lock:
                self._serialization_errors += 1
                self._last_error = f"{type(exc).__name__}: {exc}"
            return
        encoded_bytes = len(line.encode("utf-8"))
        with self._lock:
            written_bytes = self._written_bytes
        if written_bytes + encoded_bytes > self._max_bytes:
            with self._lock:
                self._dropped_size_cap += 1
            return
        try:
            handle.write(line)  # type: ignore[attr-defined]
        except OSError as exc:
            with self._lock:
                self._write_errors += 1
                self._last_error = f"{type(exc).__name__}: {exc}"
            return
        with self._lock:
            self._written += 1
            self._written_bytes += encoded_bytes

    def _drain_unwritten(self) -> None:
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return
            try:
                if item is not self._STOP:
                    with self._lock:
                        self._write_errors += 1
            finally:
                self._queue.task_done()

    def flush(self, timeout_seconds: float = 1.0) -> bool:
        """Wait a bounded time for events already accepted by the recorder."""

        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while self._queue.unfinished_tasks:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.005)
        return True

    def shutdown(self, timeout_seconds: float = 1.5) -> bool:
        """Flush accepted work and stop the writer with a bounded join."""

        with self._lock:
            existing_thread = self._thread
        if existing_thread is None:
            return True
        self._stop_requested.set()
        flushed = self.flush(max(0.0, float(timeout_seconds)) * 0.6)
        try:
            self._queue.put_nowait(self._STOP)
        except queue.Full:
            pass
        thread = existing_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, float(timeout_seconds)) * 0.4)
        return bool(flushed and (thread is None or not thread.is_alive()))

    def snapshot(self, *, recent_limit: int = 80) -> dict[str, object]:
        with self._lock:
            recent = list(self._recent)[-max(0, int(recent_limit)) :]
            return {
                "path": self._path,
                "accepted_events": self._accepted,
                "written_events": self._written,
                "queued_events": self._queue.qsize(),
                "dropped_queue_full": self._dropped_queue_full,
                "dropped_size_cap": self._dropped_size_cap,
                "serialization_errors": self._serialization_errors,
                "write_errors": self._write_errors,
                "maximum_queue_depth": self._maximum_queue_depth,
                "written_bytes": self._written_bytes,
                "writer_alive": bool(self._thread is not None and self._thread.is_alive()),
                "last_error": self._last_error,
                "recent_events": recent,
            }


_RECORDER = MeshInteractionFlightRecorder()


def record_mesh_interaction_event(
    kind: str,
    direction: str,
    payload: Mapping[str, object],
    *,
    critical: bool = False,
) -> bool:
    return _RECORDER.record(kind, direction, payload, critical=critical)


def record_mesh_protocol_send(
    payload: Mapping[str, object],
    *,
    sent: bool,
    reason: str = "",
) -> bool:
    row = {**dict(payload), "sent": bool(sent)}
    if reason:
        row["send_reason"] = str(reason)
    event = str(payload.get("event", "") or "")
    return record_mesh_interaction_event(
        "protocol",
        "host_to_helper",
        row,
        critical=event == "command_result" or not sent,
    )


def send_recorded_mesh_protocol_message(
    controller: object | None,
    payload: Mapping[str, object],
) -> bool:
    if controller is None:
        record_mesh_protocol_send(payload, sent=False, reason="no_active_controller")
        return False
    try:
        sent = bool(controller.send_authoring_message(payload))  # type: ignore[attr-defined]
    except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
        record_mesh_protocol_send(payload, sent=False, reason=f"{type(exc).__name__}: {exc}")
        return False
    record_mesh_protocol_send(payload, sent=sent)
    return sent


def mesh_interaction_diagnostics_snapshot(*, recent_limit: int = 80) -> dict[str, object]:
    return _RECORDER.snapshot(recent_limit=recent_limit)


def flush_mesh_interaction_events(timeout_seconds: float = 1.0) -> bool:
    return _RECORDER.flush(timeout_seconds)


def shutdown_mesh_interaction_recorder(timeout_seconds: float = 1.5) -> bool:
    return _RECORDER.shutdown(timeout_seconds)


atexit.register(shutdown_mesh_interaction_recorder)


__all__ = [
    "MESH_INTERACTION_LOG_MAX_BYTES",
    "MESH_INTERACTION_QUEUE_LIMIT",
    "MESH_INTERACTION_RECENT_LIMIT",
    "MeshInteractionFlightRecorder",
    "default_mesh_interaction_log_path",
    "flush_mesh_interaction_events",
    "mesh_interaction_diagnostics_snapshot",
    "record_mesh_interaction_event",
    "record_mesh_protocol_send",
    "send_recorded_mesh_protocol_message",
    "shutdown_mesh_interaction_recorder",
]
