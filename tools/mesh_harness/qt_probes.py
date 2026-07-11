from __future__ import annotations

from collections.abc import Mapping
from cdmw.domain.mesh import MeshEditCommand
from cdmw.domain.mesh import MeshEditSelection
from cdmw.services.mesh_service import MeshService
from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts
from cdmw.modding.mesh_native_core import native_mesh_core_available
from cdmw.modding.mesh_native_core import native_mesh_core_fallback_counts
from cdmw.modding.mesh_native_core import native_mesh_core_fallback_events
import os
import threading
import time

from tools.mesh_harness.fixtures import (
    build_native_benchmark_mesh,
)

from tools.mesh_harness.service_summary import (
    _command_summary,
)

def _run_mesh_edit_command_worker_qt(
    service: MeshService,
    session_id: str,
    command: MeshEditCommand,
    *,
    action_text: str,
    cancel_after_progress_ms: int | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, object]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QMetaObject, QObject, QThread, QTimer, Qt, Slot
    from PySide6.QtWidgets import QApplication
    from cdmw.workers.mesh_editor_workers import MeshEditCommandWorker
    app = QApplication.instance() or QApplication(["mesh-editor-qt-worker"])
    worker = MeshEditCommandWorker(1, service, session_id, command, action_text=action_text)
    thread = QThread()
    state: dict[str, object] = {"completed": None, "error": "", "cancelled": "", "finished": False}
    progress_events: list[dict[str, object]] = []
    heartbeat_ms: list[float] = []
    cancel_requested_ms: list[float] = []
    thread_ready = threading.Event()
    def elapsed_ms() -> float:
        return (time.perf_counter() - started) * 1000.0

    class Receiver(QObject):
        @Slot(int, int, str)
        def on_progress(self, _request_id: int, percent: int, message: str) -> None:
            progress_events.append({"elapsed_ms": elapsed_ms(), "percent": int(percent), "message": str(message or "")})
            if cancel_after_progress_ms is not None and not cancel_requested_ms and not cancel_timer.isActive():
                cancel_timer.start(max(0, int(cancel_after_progress_ms)))

        @Slot(int, object)
        def on_completed(self, _request_id: int, result: object) -> None:
            state["completed"] = _command_summary(result)
            state["completed_at_ms"] = elapsed_ms()

        @Slot(int, str)
        def on_error(self, _request_id: int, message: str) -> None:
            state["error"] = str(message or "")
            state["error_at_ms"] = elapsed_ms()

        @Slot(int, str)
        def on_cancelled(self, _request_id: int, message: str) -> None:
            state["cancelled"] = str(message or "")
            state["cancelled_at_ms"] = elapsed_ms()

        @Slot()
        def on_finished(self) -> None:
            state["finished"] = True
            state["finished_at_ms"] = elapsed_ms()
            timer.stop()
            cancel_timer.stop()

    class ThreadReadyProbe(QObject):
        @Slot()
        def acknowledge(self) -> None:
            thread_ready.set()
    receiver = Receiver()
    ready_probe = ThreadReadyProbe()
    timer = QTimer(receiver)
    timer.setInterval(25)

    def request_cancel() -> None:
        if not cancel_requested_ms:
            cancel_requested_ms.append(elapsed_ms())
        worker.stop()

    cancel_timer = QTimer(receiver)
    cancel_timer.setSingleShot(True)
    cancel_timer.timeout.connect(request_cancel)
    timer.timeout.connect(lambda: heartbeat_ms.append(elapsed_ms()))
    worker.moveToThread(thread)
    ready_probe.moveToThread(thread)
    worker.progress_changed.connect(receiver.on_progress, Qt.ConnectionType.QueuedConnection)
    worker.completed.connect(receiver.on_completed, Qt.ConnectionType.QueuedConnection)
    worker.error.connect(receiver.on_error, Qt.ConnectionType.QueuedConnection)
    worker.cancelled.connect(receiver.on_cancelled, Qt.ConnectionType.QueuedConnection)
    worker.finished.connect(receiver.on_finished, Qt.ConnectionType.QueuedConnection)
    worker.finished.connect(worker.deleteLater)
    worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
    thread.finished.connect(ready_probe.deleteLater)

    thread_start_started = time.perf_counter()
    thread.start(QThread.Priority.LowPriority)
    thread_start_return_ms = (time.perf_counter() - thread_start_started) * 1000.0
    ready_requested = bool(QMetaObject.invokeMethod(ready_probe, "acknowledge", Qt.ConnectionType.QueuedConnection))
    ready_deadline = time.monotonic() + min(5.0, max(0.5, float(timeout_seconds)))
    while ready_requested and not thread_ready.is_set() and time.monotonic() < ready_deadline:
        app.processEvents()
        time.sleep(0.001)
    thread_ready_ms = (time.perf_counter() - thread_start_started) * 1000.0

    started = dispatch_started = time.perf_counter()
    timer.start()
    worker_invoked = bool(
        thread_ready.is_set()
        and QMetaObject.invokeMethod(worker, "run", Qt.ConnectionType.QueuedConnection)
    )
    dispatch_return_ms = (time.perf_counter() - dispatch_started) * 1000.0
    deadline = time.monotonic() + max(0.5, float(timeout_seconds))
    while worker_invoked and not bool(state["finished"]) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    timed_out = not worker_invoked or not bool(state["finished"])
    if timed_out:
        request_cancel()
        thread.requestInterruption()
        thread.quit()
    thread_stopped = bool(thread.wait(5000))
    timer.stop()
    cancel_timer.stop()
    if thread_stopped:
        receiver.deleteLater()
        thread.deleteLater()
        app.processEvents()
    total_elapsed_ms = elapsed_ms()

    first_progress_ms = float(progress_events[0]["elapsed_ms"]) if progress_events else None
    heartbeat_gaps = [heartbeat_ms[index] - heartbeat_ms[index - 1] for index in range(1, len(heartbeat_ms))]
    max_heartbeat_gap_ms = max(heartbeat_gaps) if heartbeat_gaps else 0.0
    cancel_requested_at = cancel_requested_ms[0] if cancel_requested_ms else None
    cancel_terminal_at = state.get("cancelled_at_ms", state.get("finished_at_ms"))
    cancel_latency_ms = (
        max(0.0, float(cancel_terminal_at) - float(cancel_requested_at))
        if cancel_requested_at is not None and cancel_terminal_at is not None
        else None
    )
    completed = state["completed"] if isinstance(state.get("completed"), Mapping) else {}
    return {
        "dispatch_return_ms": dispatch_return_ms,
        "thread_start_return_ms": thread_start_return_ms,
        "thread_ready_ms": thread_ready_ms,
        "thread_ready": thread_ready.is_set(),
        "ready_requested": ready_requested,
        "worker_invoked": worker_invoked,
        "first_progress_ms": first_progress_ms,
        "heartbeat_count": len(heartbeat_ms),
        "max_heartbeat_gap_ms": max_heartbeat_gap_ms,
        "total_elapsed_ms": total_elapsed_ms,
        "timed_out": timed_out,
        "thread_stopped": thread_stopped,
        "completed": dict(completed),
        "progress_events": progress_events,
        "error": state.get("error", ""),
        "cancelled": state.get("cancelled", ""),
        "cancel_requested_ms": cancel_requested_at,
        "cancel_latency_ms": cancel_latency_ms,
    }

def run_native_mesh_editor_qt_responsiveness() -> dict[str, object]:
    clear_native_mesh_core_fallback_counts()
    native_available = native_mesh_core_available()
    if not native_available:
        return {"ok": False, "native_core_available": False, "reason": "native mesh core binary not available"}

    service = MeshService()
    view = service.open_edit_session(build_native_benchmark_mesh(), session_id="native-editor-qt-responsiveness", mode="edit")
    command = MeshEditCommand(
        "subdivide",
        selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
        params={"max_faces_per_submesh": 512, "recompute_normals": True},
        mode="edit",
        label="Subdivide",
    )
    worker_run = _run_mesh_edit_command_worker_qt(service, view.session_id, command, action_text="Subdivide")
    fallback_counts = native_mesh_core_fallback_counts()
    fallback_events = list(native_mesh_core_fallback_events())
    completed = worker_run["completed"] if isinstance(worker_run.get("completed"), Mapping) else {}
    service.close_edit_session(view.session_id)
    thread_ready_ok = bool(worker_run["thread_ready"] and worker_run["ready_requested"] and worker_run["worker_invoked"])
    dispatch_ok = float(worker_run["dispatch_return_ms"]) <= 50.0
    progress_ok = worker_run["first_progress_ms"] is not None and float(worker_run["first_progress_ms"]) <= 100.0
    heartbeat_ok = bool(
        float(worker_run["max_heartbeat_gap_ms"]) <= 200.0
        and (
            int(worker_run["heartbeat_count"]) >= 2
            or float(worker_run["total_elapsed_ms"]) <= 200.0
        )
    )
    command_ok = bool(completed.get("status") == "ok")
    fallback_ok = not fallback_counts
    return {
        "ok": bool(command_ok and thread_ready_ok and dispatch_ok and progress_ok and heartbeat_ok and fallback_ok and worker_run["thread_stopped"] and not worker_run["timed_out"]),
        "native_core_available": native_available,
        "thread_start_return_ms": worker_run["thread_start_return_ms"],
        "thread_ready_ms": worker_run["thread_ready_ms"],
        "thread_ready_ok": thread_ready_ok,
        "dispatch_return_ms": worker_run["dispatch_return_ms"],
        "dispatch_target_ok": dispatch_ok,
        "first_progress_ms": worker_run["first_progress_ms"],
        "progress_target_ok": progress_ok,
        "heartbeat_count": worker_run["heartbeat_count"],
        "max_heartbeat_gap_ms": worker_run["max_heartbeat_gap_ms"],
        "qt_heartbeat_ok": heartbeat_ok,
        "total_elapsed_ms": worker_run["total_elapsed_ms"],
        "timed_out": worker_run["timed_out"],
        "thread_stopped": worker_run["thread_stopped"],
        "command": dict(completed),
        "command_ok": command_ok,
        "progress_events": worker_run["progress_events"],
        "native_fallback_ok": fallback_ok,
        "native_fallback_counts": fallback_counts,
        "native_fallback_events": fallback_events,
        "error": worker_run["error"],
        "cancelled": worker_run["cancelled"],
    }

def run_native_mesh_editor_qt_cancellation() -> dict[str, object]:
    clear_native_mesh_core_fallback_counts()
    native_available = native_mesh_core_available()
    if not native_available:
        return {"ok": False, "native_core_available": False, "reason": "native mesh core binary not available"}

    service = MeshService()
    # Keep this probe large enough to enter native work, but small enough that
    # cooperative cancellation has a stable sub-500 ms deadline under load.
    view = service.open_edit_session(
        build_native_benchmark_mesh(rows=200, columns=200),
        session_id="native-editor-qt-cancellation",
        mode="edit",
    )
    prewarm = service.apply_command(
        view.session_id,
        MeshEditCommand(
            "brush",
            selection=MeshEditSelection.from_maps(vertices_by_submesh={0: tuple(range(32))}),
            params={"tool": "grab", "center": (16.0, 0.0, 0.0), "radius": 8.0, "strength": 0.5, "delta": (0.0, 0.0, 0.05)},
            mode="sculpt",
            label="Prewarm Brush",
        ),
    )
    face_count = len(service.working_mesh(view.session_id).submeshes[0].faces)
    command = MeshEditCommand(
        "subdivide",
        selection=MeshEditSelection.from_maps(faces_by_submesh={0: range(face_count)}),
        params={"recompute_normals": True},
        mode="edit",
        label="Subdivide Cancel",
    )
    worker_run = _run_mesh_edit_command_worker_qt(
        service,
        view.session_id,
        command,
        action_text="Subdivide Cancel",
        cancel_after_progress_ms=10,
        timeout_seconds=15.0,
    )
    fallback_counts = native_mesh_core_fallback_counts()
    fallback_events = list(native_mesh_core_fallback_events())
    service.close_edit_session(view.session_id)
    thread_ready_ok = bool(worker_run["thread_ready"] and worker_run["ready_requested"] and worker_run["worker_invoked"])
    dispatch_ok = float(worker_run["dispatch_return_ms"]) <= 50.0
    progress_ok = worker_run["first_progress_ms"] is not None and float(worker_run["first_progress_ms"]) <= 100.0
    cancel_latency = worker_run["cancel_latency_ms"]
    cancel_ok = bool(worker_run["cancelled"]) and cancel_latency is not None and float(cancel_latency) <= 500.0
    fallback_ok = not fallback_counts
    return {
        "ok": bool(prewarm.ok and thread_ready_ok and dispatch_ok and progress_ok and cancel_ok and fallback_ok and worker_run["thread_stopped"] and not worker_run["timed_out"]),
        "native_core_available": native_available,
        "prewarm_command": _command_summary(prewarm),
        "thread_start_return_ms": worker_run["thread_start_return_ms"],
        "thread_ready_ms": worker_run["thread_ready_ms"],
        "thread_ready_ok": thread_ready_ok,
        "dispatch_return_ms": worker_run["dispatch_return_ms"],
        "dispatch_target_ok": dispatch_ok,
        "first_progress_ms": worker_run["first_progress_ms"],
        "progress_target_ok": progress_ok,
        "cancel_requested_ms": worker_run["cancel_requested_ms"],
        "cancel_latency_ms": cancel_latency,
        "cancel_target_ok": cancel_ok,
        "heartbeat_count": worker_run["heartbeat_count"],
        "max_heartbeat_gap_ms": worker_run["max_heartbeat_gap_ms"],
        "total_elapsed_ms": worker_run["total_elapsed_ms"],
        "timed_out": worker_run["timed_out"],
        "thread_stopped": worker_run["thread_stopped"],
        "command": worker_run["completed"],
        "progress_events": worker_run["progress_events"],
        "native_fallback_ok": fallback_ok,
        "native_fallback_counts": fallback_counts,
        "native_fallback_events": fallback_events,
        "error": worker_run["error"],
        "cancelled": worker_run["cancelled"],
    }
