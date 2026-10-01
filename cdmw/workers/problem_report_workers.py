"""Independent report collection lane, retained until its thread actually stops."""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QObject, QThread, QTimer, Qt, Signal, Slot

from cdmw.services.problem_report_service import ProblemReportRequest, collect_problem_report, load_problem_report
from cdmw.workers.utility_workers import UtilityWorker

_active_collections: set[ProblemReportCollection] = set()


class ProblemReportCollection(QObject):
    completed = Signal(int, object)
    failed = Signal(int, str)
    stopped = Signal()

    def __init__(self, request_id: int, request: ProblemReportRequest) -> None:
        super().__init__()
        self.request_id = request_id
        self._cancelled = False
        self.worker_thread = QThread()
        self.worker = UtilityWorker(
            lambda _log, stop_event: (load_problem_report(request.draft_path, request.snapshot, stop_event=stop_event)
                                     if request.draft_path else collect_problem_report(request, stop_event=stop_event)),
            task_accepts_cancel=True,
        )
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.completed.connect(self._completed)
        self.worker.error.connect(self._failed)
        self.worker.finished.connect(self.worker.deleteLater)
        # quit() is thread-safe: don't require a live UI event loop during application exit.
        self.worker.finished.connect(self.worker_thread.quit, Qt.ConnectionType.DirectConnection)
        self.worker_thread.finished.connect(self._stopped)
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.cancel)

    def start(self) -> None:
        _active_collections.add(self)
        self.worker_thread.start()

    @Slot()
    def cancel(self) -> None:
        self._cancelled = True
        if self.worker is not None:
            self.worker.stop()

    @Slot(object)
    def _completed(self, result: object) -> None:
        if not self._cancelled:
            self.completed.emit(self.request_id, result)

    @Slot(str)
    def _failed(self, message: str) -> None:
        if not self._cancelled:
            self.failed.emit(self.request_id, message)

    @Slot()
    def _stopped(self) -> None:
        # finished can precede native TLS/deferred-delete teardown. Poll without
        # blocking the UI before releasing wrappers owned by the worker thread.
        if not self.worker_thread.wait(0):
            QTimer.singleShot(10, self._stopped)
            return
        self.worker = None
        self.worker_thread.deleteLater()
        self.worker_thread = None
        _active_collections.discard(self)
        self.stopped.emit()
        self.deleteLater()
