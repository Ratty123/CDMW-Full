"""Latest-wins worker ownership for Texture Research detail and report tasks."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from functools import partial

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Slot

from cdmw.workers.research_analysis_workers import (
    AnalysisDetailRequest,
    AnalysisDetailResult,
    AnalysisDetailWorker,
    AnalysisReportExportRequest,
    AnalysisReportExportResult,
    AnalysisReportExportWorker,
)


class ResearchAnalysisTaskController(QObject):
    def __init__(self, owner: QObject, *, debounce_ms: int = 60) -> None:
        super().__init__(owner)
        self._owner = owner
        self._closed = False
        self._detail_request_id = 0
        self._export_request_id = 0
        self._pending_detail: AnalysisDetailRequest | None = None
        self._pending_export: AnalysisReportExportRequest | None = None
        self._detail_debounce_ready = False
        self._detail_jobs: dict[int, tuple[QThread, AnalysisDetailWorker]] = {}
        self._export_jobs: dict[int, tuple[QThread, AnalysisReportExportWorker]] = {}
        self._detail_complete: Callable[[AnalysisDetailResult], None] | None = None
        self._detail_error: Callable[[str], None] | None = None
        self._export_complete: Callable[[AnalysisReportExportResult], None] | None = None
        self._export_error: Callable[[str], None] | None = None
        self._export_idle: Callable[[], None] | None = None
        self._detail_timer = QTimer(self)
        self._detail_timer.setSingleShot(True)
        self._detail_timer.setInterval(max(0, int(debounce_ms)))
        self._detail_timer.timeout.connect(self._launch_pending_detail)

    def queue_detail(
        self,
        request: AnalysisDetailRequest,
        *,
        on_complete: Callable[[AnalysisDetailResult], None],
        on_error: Callable[[str], None],
    ) -> bool:
        if self._closed:
            return False
        self._detail_request_id += 1
        current = dataclasses.replace(request, request_id=self._detail_request_id)
        self._pending_detail = current
        self._detail_complete = on_complete
        self._detail_error = on_error
        self._detail_debounce_ready = False
        self._stop_jobs(self._detail_jobs)
        self._detail_timer.start()
        return True

    def cancel_detail(self) -> None:
        self._detail_request_id += 1
        self._pending_detail = None
        self._detail_debounce_ready = False
        self._detail_timer.stop()
        self._stop_jobs(self._detail_jobs)

    def start_export(
        self,
        request: AnalysisReportExportRequest,
        *,
        on_complete: Callable[[AnalysisReportExportResult], None],
        on_error: Callable[[str], None],
        on_idle: Callable[[], None],
    ) -> bool:
        if self._closed:
            return False
        self._export_request_id += 1
        current = dataclasses.replace(request, request_id=self._export_request_id)
        self._export_complete = on_complete
        self._export_error = on_error
        self._export_idle = on_idle
        self._stop_jobs(self._export_jobs)
        if self._export_jobs:
            self._pending_export = current
        else:
            self._pending_export = None
            self._launch_export(current)
        return True

    def request_shutdown(self) -> None:
        self._closed = True
        self.cancel_detail()
        self._export_request_id += 1
        self._pending_export = None
        self._stop_jobs(self._export_jobs)

    def iter_shutdown_workers(self) -> tuple[tuple[str, QThread, object], ...]:
        tracked: list[tuple[str, QThread, object]] = []
        for label, jobs in (("research_detail", self._detail_jobs), ("research_export", self._export_jobs)):
            for thread, worker in jobs.values():
                try:
                    if thread.isRunning():
                        tracked.append((label, thread, worker))
                except RuntimeError:
                    pass
        return tuple(tracked)

    @Slot()
    def _launch_pending_detail(self) -> None:
        self._detail_debounce_ready = True
        self._try_launch_detail()

    def _try_launch_detail(self) -> None:
        request = self._pending_detail
        if (
            self._closed
            or not self._detail_debounce_ready
            or self._detail_jobs
            or request is None
            or request.request_id != self._detail_request_id
        ):
            return
        self._pending_detail = None
        worker = AnalysisDetailWorker(request)
        thread = self._wire_worker(worker, "detail", request.request_id)
        self._detail_jobs[request.request_id] = (thread, worker)
        thread.start(QThread.LowPriority)

    def _launch_export(self, request: AnalysisReportExportRequest) -> None:
        worker = AnalysisReportExportWorker(request)
        thread = self._wire_worker(worker, "export", request.request_id)
        self._export_jobs[request.request_id] = (thread, worker)
        thread.start(QThread.LowPriority)

    def _wire_worker(self, worker: object, lane: str, request_id: int) -> QThread:
        thread = QThread(self._owner)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        if lane == "detail":
            worker.completed.connect(self._handle_detail_completed, Qt.QueuedConnection)
            worker.error.connect(self._handle_detail_error, Qt.QueuedConnection)
        else:
            worker.completed.connect(self._handle_export_completed, Qt.QueuedConnection)
            worker.error.connect(self._handle_export_error, Qt.QueuedConnection)
        worker.finished.connect(thread.quit, Qt.DirectConnection)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            partial(self._handle_thread_finished, lane, request_id),
            Qt.QueuedConnection,
        )
        return thread

    @Slot(object)
    def _handle_detail_completed(self, result: object) -> None:
        if (
            not self._closed
            and isinstance(result, AnalysisDetailResult)
            and result.request_id == self._detail_request_id
            and self._detail_complete is not None
        ):
            self._detail_complete(result)

    @Slot(int, str)
    def _handle_detail_error(self, request_id: int, message: str) -> None:
        if not self._closed and request_id == self._detail_request_id and self._detail_error is not None:
            self._detail_error(message)

    @Slot(object)
    def _handle_export_completed(self, result: object) -> None:
        if (
            not self._closed
            and isinstance(result, AnalysisReportExportResult)
            and result.request_id == self._export_request_id
            and self._export_complete is not None
        ):
            self._export_complete(result)

    @Slot(int, str)
    def _handle_export_error(self, request_id: int, message: str) -> None:
        if not self._closed and request_id == self._export_request_id and self._export_error is not None:
            self._export_error(message)

    def _handle_thread_finished(self, lane: str, request_id: int) -> None:
        jobs = self._detail_jobs if lane == "detail" else self._export_jobs
        jobs.pop(request_id, None)
        if lane == "detail":
            self._try_launch_detail()
            return
        pending_export = self._pending_export
        if (
            not self._closed
            and not self._export_jobs
            and pending_export is not None
            and pending_export.request_id == self._export_request_id
        ):
            self._pending_export = None
            self._launch_export(pending_export)
            return
        if (
            not self._closed
            and request_id == self._export_request_id
            and self._export_idle is not None
        ):
            self._export_idle()

    @staticmethod
    def _stop_jobs(jobs: dict[int, tuple[QThread, object]]) -> None:
        for _thread, worker in tuple(jobs.values()):
            try:
                worker.stop()
            except RuntimeError:
                pass


__all__ = ["ResearchAnalysisTaskController"]
