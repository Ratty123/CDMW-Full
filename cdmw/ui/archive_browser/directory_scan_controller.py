"""Responsive directory-scan delivery for archive-browser dialogs."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from cdmw.workers.directory_scan_workers import (
    DirectoryScanRequest,
    DirectoryScanResult,
    DirectoryScanWorker,
)


class DirectoryScanController(QObject):
    """Run one latest-wins scan and deliver its paths in bounded UI batches."""

    batch_ready = Signal(int, object)
    completed = Signal(int, bool)
    error = Signal(int, str)
    busy_changed = Signal(bool)

    def __init__(
        self,
        *,
        thread_parent: QObject,
        parent: QObject | None = None,
        batch_size: int = 64,
    ) -> None:
        super().__init__(parent)
        self._thread_parent = thread_parent
        self._batch_size = max(1, int(batch_size))
        self._request_id = 0
        self._jobs: dict[int, tuple[DirectoryScanWorker, QThread]] = {}
        self._paths: tuple[Path, ...] = ()
        self._path_index = 0
        self._truncated = False
        self._busy = False
        self._closed = False
        self._batch_timer = QTimer(self)
        self._batch_timer.setSingleShot(True)
        self._batch_timer.timeout.connect(self._deliver_next_batch)

    def start(
        self,
        root: Path,
        *,
        suffixes: Sequence[str],
        max_results: int = 10_000,
        max_entries: int = 2_000_000,
    ) -> int:
        if self._closed:
            return 0
        self.cancel()
        self._request_id += 1
        request_id = self._request_id
        worker = DirectoryScanWorker(
            DirectoryScanRequest(
                request_id=request_id,
                root=Path(root),
                suffixes=tuple(suffixes),
                max_results=max_results,
                max_entries=max_entries,
            )
        )
        thread = QThread(self._thread_parent)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_scan_ready)
        worker.error.connect(self._handle_scan_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda rid=request_id: self._jobs.pop(rid, None))
        self._jobs[request_id] = (worker, thread)
        self._set_busy(True)
        thread.start(QThread.LowPriority)
        return request_id

    def cancel(self) -> None:
        self._request_id += 1
        self._batch_timer.stop()
        self._paths = ()
        self._path_index = 0
        for worker, _thread in tuple(self._jobs.values()):
            worker.stop()
        self._set_busy(False)

    def close(self) -> None:
        self._closed = True
        self.cancel()

    def is_running(self) -> bool:
        return self._busy

    def has_jobs(self) -> bool:
        return bool(self._jobs)

    def _set_busy(self, busy: bool) -> None:
        busy = bool(busy)
        if busy == self._busy:
            return
        self._busy = busy
        self.busy_changed.emit(busy)

    @Slot(int, object)
    def _handle_scan_ready(self, request_id: int, result: object) -> None:
        if self._closed or request_id != self._request_id or not isinstance(result, DirectoryScanResult):
            return
        self._paths = result.paths
        self._path_index = 0
        self._truncated = result.truncated
        self._batch_timer.start(0)

    @Slot(int, str)
    def _handle_scan_error(self, request_id: int, message: str) -> None:
        if self._closed or request_id != self._request_id:
            return
        self._set_busy(False)
        self.error.emit(request_id, message)

    @Slot()
    def _deliver_next_batch(self) -> None:
        request_id = self._request_id
        if self._closed or not self._busy:
            return
        end = min(len(self._paths), self._path_index + self._batch_size)
        if end > self._path_index:
            self.batch_ready.emit(request_id, self._paths[self._path_index:end])
            self._path_index = end
        if self._path_index < len(self._paths):
            self._batch_timer.start(0)
            return
        truncated = self._truncated
        self._set_busy(False)
        self.completed.emit(request_id, truncated)


__all__ = ["DirectoryScanController"]
