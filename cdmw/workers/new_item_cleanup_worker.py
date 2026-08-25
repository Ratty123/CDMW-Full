"""Tracked retirement cleanup for New Item imported-model sources."""

from __future__ import annotations

import threading
from typing import Optional, Tuple

from PySide6.QtCore import QObject, QThread, Qt, QTimer

from cdmw.workers.new_item_workers import model_source_cleanup_task
from cdmw.workers.utility_workers import UtilityWorker


class ModelSourceCleanupLane(QObject):
    """Remove retired import roots off the UI thread after all source usages end."""

    def __init__(self, *, synchronous: bool = False, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._synchronous = bool(synchronous)
        self._jobs: list[tuple[QThread, UtilityWorker, object]] = []

    def retire(self, source: object | None) -> None:
        cleanup = getattr(source, "cleanup", None)
        if not callable(cleanup) or any(item[2] is source for item in self._jobs):
            return
        retire = getattr(source, "retire", None)
        if callable(retire):
            retire()
        task = model_source_cleanup_task(source)
        if self._synchronous:
            task(lambda _message: None, threading.Event())
            return
        worker = UtilityWorker(task, task_accepts_cancel=True)
        thread = QThread(self)
        worker.moveToThread(thread)
        self._jobs.append((thread, worker, source))
        worker.finished.connect(self._worker_finished, Qt.DirectConnection)
        thread.finished.connect(self._thread_finished, Qt.QueuedConnection)
        thread.started.connect(worker.run)
        thread.start()

    def iter_shutdown_workers(self) -> Tuple[Tuple[str, QThread, object], ...]:
        return tuple(("new item model source cleanup", thread, worker) for thread, worker, _source in self._jobs)

    def _worker_finished(self) -> None:
        worker = self.sender()
        if isinstance(worker, UtilityWorker) and worker.thread() is QThread.currentThread():
            worker.moveToThread(self.thread())
        QThread.currentThread().quit()

    def _thread_finished(self) -> None:
        thread = self.sender()
        if isinstance(thread, QThread):
            self._retire_thread(thread)

    def _retire_thread(self, thread: QThread) -> None:
        if not thread.wait(0):
            QTimer.singleShot(0, lambda thread=thread: self._retire_thread(thread))
            return
        job = next((item for item in self._jobs if item[0] is thread), None)
        if job is None:
            return
        self._jobs.remove(job)
        _thread, worker, _source = job
        worker.deleteLater()
        thread.deleteLater()


__all__ = ["ModelSourceCleanupLane"]
