"""Qt lifecycle bridge for Retrofit/Repackage background work."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QDialog, QWidget

from cdmw.ui.shell.close_controller import register_transient_worker_controller
from cdmw.workers.mod_package_retrofit_workers import (
    ModPackageRetrofitWorker,
    RetrofitConversionRequest,
    RetrofitScanRequest,
)


class ModPackageRetrofitTaskController(QObject):
    scan_completed = Signal(object)
    conversion_completed = Signal(object)
    failed = Signal(str, str)
    progress = Signal(str, int, int, str)
    busy_changed = Signal(bool, bool)

    def __init__(self, *, thread_parent: QObject, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread_parent = thread_parent
        self._next_request_id = 0
        self._latest_scan_id = 0
        self._active_conversion_id = 0
        self._jobs: dict[int, tuple[str, ModPackageRetrofitWorker, QThread]] = {}
        self._closed = False

    def start_scan(self, source: Path) -> int:
        if self._closed:
            return 0
        self._next_request_id += 1
        request_id = self._next_request_id
        self._latest_scan_id = request_id
        for kind, worker, _thread in tuple(self._jobs.values()):
            if kind == "scan":
                worker.stop()
        self._start_job("scan", RetrofitScanRequest(request_id, Path(source)))
        return request_id

    def start_conversion(self, request: RetrofitConversionRequest) -> int:
        if self._closed or self._active_conversion_id:
            return 0
        self._next_request_id += 1
        request_id = self._next_request_id
        self._active_conversion_id = request_id
        self._start_job(
            "conversion",
            RetrofitConversionRequest(request_id, request.output_root, request.items),
        )
        return request_id

    def cancel(self) -> None:
        self._latest_scan_id = 0
        self._active_conversion_id = 0
        for _kind, worker, _thread in tuple(self._jobs.values()):
            worker.stop()
        self._emit_busy()

    def request_shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.cancel()

    def iter_shutdown_workers(self) -> tuple[tuple[str, QThread, ModPackageRetrofitWorker], ...]:
        return tuple(
            (f"retrofit_{kind}_{request_id}", thread, worker)
            for request_id, (kind, worker, thread) in self._jobs.items()
            if thread.isRunning()
        )

    def _start_job(self, kind: str, request: object) -> None:
        worker = ModPackageRetrofitWorker(kind, request)  # type: ignore[arg-type]
        thread = QThread(self._thread_parent)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_completed)
        worker.failed.connect(self._handle_failed)
        worker.cancelled.connect(self._handle_cancelled)
        worker.progress.connect(self._handle_progress)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._handle_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._jobs[int(getattr(request, "request_id"))] = (kind, worker, thread)
        thread.start(QThread.LowPriority)
        self._emit_busy()

    @Slot(int, str, object)
    def _handle_completed(self, request_id: int, kind: str, result: object) -> None:
        if self._closed:
            return
        if kind == "scan" and request_id == self._latest_scan_id:
            self.scan_completed.emit(result)
        elif kind == "conversion" and request_id == self._active_conversion_id:
            self._active_conversion_id = 0
            self.conversion_completed.emit(result)
        self._emit_busy()

    @Slot(int, str, str)
    def _handle_failed(self, request_id: int, kind: str, message: str) -> None:
        if self._closed:
            return
        if kind == "scan" and request_id != self._latest_scan_id:
            return
        if kind == "conversion" and request_id != self._active_conversion_id:
            return
        if kind == "conversion":
            self._active_conversion_id = 0
        self.failed.emit(kind, message)
        self._emit_busy()

    @Slot(int, str)
    def _handle_cancelled(self, request_id: int, _message: str) -> None:
        if request_id == self._active_conversion_id:
            self._active_conversion_id = 0
        self._emit_busy()

    @Slot(int, str, int, int, str)
    def _handle_progress(self, request_id: int, kind: str, current: int, total: int, detail: str) -> None:
        if self._closed:
            return
        if kind == "scan" and request_id != self._latest_scan_id:
            return
        if kind == "conversion" and request_id != self._active_conversion_id:
            return
        self.progress.emit(kind, current, total, detail)

    @Slot()
    def _handle_thread_finished(self) -> None:
        thread = self.sender()
        finished_ids = [request_id for request_id, (_kind, _worker, job_thread) in self._jobs.items() if job_thread is thread]
        for request_id in finished_ids:
            kind, _worker, _thread = self._jobs.pop(request_id)
            if kind == "conversion" and request_id == self._active_conversion_id:
                self._active_conversion_id = 0
        self._emit_busy()

    def _emit_busy(self) -> None:
        latest_scan = self._jobs.get(self._latest_scan_id)
        scan_busy = bool(latest_scan is not None and latest_scan[0] == "scan" and latest_scan[2].isRunning())
        conversion_busy = bool(
            self._active_conversion_id
            and any(kind == "conversion" and thread.isRunning() for kind, _worker, thread in self._jobs.values())
        )
        self.busy_changed.emit(scan_busy, conversion_busy)


class ModPackageRetrofitToolWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._retrofit_task_controller: ModPackageRetrofitTaskController | None = None

    def set_task_controller(self, controller: ModPackageRetrofitTaskController) -> None:
        self._retrofit_task_controller = controller

    def request_shutdown(self) -> None:
        if self._retrofit_task_controller is not None:
            self._retrofit_task_controller.request_shutdown()

    def iter_shutdown_workers(self) -> tuple[tuple[str, QThread, ModPackageRetrofitWorker], ...]:
        if self._retrofit_task_controller is None:
            return ()
        return self._retrofit_task_controller.iter_shutdown_workers()


def retrofit_task_controller_for_widget(
    owner: QObject,
    widget: QWidget,
) -> ModPackageRetrofitTaskController:
    existing = getattr(widget, "_retrofit_task_controller", None)
    if isinstance(existing, ModPackageRetrofitTaskController):
        return existing
    controller = ModPackageRetrofitTaskController(thread_parent=owner, parent=widget)
    setattr(widget, "_retrofit_task_controller", controller)
    if isinstance(widget, ModPackageRetrofitToolWidget):
        widget.set_task_controller(controller)
    else:
        register_transient_worker_controller(owner, controller)
    if isinstance(widget, QDialog):
        widget.finished.connect(lambda _result=0: controller.request_shutdown())
    return controller


__all__ = [
    "ModPackageRetrofitTaskController",
    "ModPackageRetrofitToolWidget",
    "retrofit_task_controller_for_widget",
]
