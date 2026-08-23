"""Dedicated cancellable worker lane for New Item effect metadata indexing."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional, Tuple

from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal

from cdmw.services.effect_catalogue import (
    EffectCatalogue,
    build_effect_catalogue,
    catalogue_signature,
    load_effect_catalogue,
    save_effect_catalogue,
)
from cdmw.services.new_item_snapshot import NewItemSnapshot
from cdmw.workers.utility_workers import UtilityWorker


class EffectCatalogueIndexLane(QObject):
    """Serialize effect indexing independently of the controller's main task lane."""

    completed = Signal(object, object)
    progress = Signal(int, int, str)
    failed = Signal(str)
    log_message = Signal(str)

    def __init__(self, *, synchronous: bool = False, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._synchronous = bool(synchronous)
        self._thread: Optional[QThread] = None
        self._worker: Optional[UtilityWorker] = None
        self._generation = 0
        self._active_generation = 0
        self._requested_snapshot: Optional[NewItemSnapshot] = None
        self._requested_cache_path: Optional[Path] = None
        self._pending_request: Optional[Tuple[NewItemSnapshot, Optional[Path]]] = None
        self._shutdown_requested = False

    def start(self, snapshot: NewItemSnapshot, *, cache_path: Optional[Path] = None) -> bool:
        if self._shutdown_requested:
            return False
        cache_path = Path(cache_path) if cache_path is not None else None
        if self._thread is not None:
            if self._requested_snapshot is snapshot and self._requested_cache_path == cache_path:
                return True
            self._requested_snapshot = snapshot
            self._requested_cache_path = cache_path
            self._pending_request = (snapshot, cache_path)
            if self._worker is not None:
                self._worker.stop()
            self._thread.requestInterruption()
            self._thread.quit()
            return True
        self._requested_snapshot = snapshot
        self._requested_cache_path = cache_path
        self._begin(snapshot, cache_path)
        return True

    def _begin(self, snapshot: NewItemSnapshot, cache_path: Optional[Path]) -> None:
        self._generation += 1
        generation = self._generation
        self._active_generation = generation
        self._pending_request = None

        def task(log, stop_event: threading.Event):
            signature = catalogue_signature(snapshot)
            if cache_path is not None:
                self.progress.emit(0, 0, "Loading cached effect metadata…")
                catalogue = load_effect_catalogue(cache_path, signature=signature)
                if stop_event.is_set():
                    raise RuntimeError("Effect indexing cancelled.")
                if catalogue is not None:
                    log(f"Loaded {len(catalogue)} effects from the metadata cache.")
                    return generation, snapshot, catalogue

            catalogue = build_effect_catalogue(
                snapshot,
                on_log=log,
                on_progress=lambda done, total, stem: self.progress.emit(done, total, stem),
                stop_event=stop_event,
            )
            if stop_event.is_set():
                raise RuntimeError("Effect indexing cancelled.")
            if cache_path is not None:
                self.progress.emit(len(catalogue), len(catalogue), "Saving effect metadata cache…")
                try:
                    save_effect_catalogue(catalogue, cache_path)
                except OSError as exc:
                    log(f"The effect catalogue could not be cached: {exc}")
            return generation, snapshot, catalogue

        if self._synchronous:
            try:
                self._completed(task(self.log_message.emit, threading.Event()))
            except (ValueError, RuntimeError, OSError) as exc:
                self._failed(str(exc))
            return

        worker = UtilityWorker(task, task_accepts_cancel=True)
        thread = QThread(self)
        worker.moveToThread(thread)
        self._thread, self._worker = thread, worker
        worker.log_message.connect(self.log_message.emit)
        worker.completed.connect(self._completed)
        worker.error.connect(self._failed)
        worker.finished.connect(self._worker_finished, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(self._thread_finished, Qt.ConnectionType.QueuedConnection)
        thread.started.connect(worker.run)
        thread.start()

    def _completed(self, result: object) -> None:
        if self._shutdown_requested or not isinstance(result, tuple) or len(result) != 3:
            return
        generation, snapshot, catalogue = result
        if (
            int(generation) != self._active_generation
            or snapshot is not self._requested_snapshot
            or not isinstance(catalogue, EffectCatalogue)
        ):
            return
        self.completed.emit(snapshot, catalogue)

    def _failed(self, message: object) -> None:
        if self._shutdown_requested or "cancelled" in str(message).casefold():
            return
        self.failed.emit(str(message))

    def _worker_finished(self) -> None:
        worker = self._worker
        if worker is not None and worker.thread() is QThread.currentThread():
            worker.moveToThread(self.thread())
        QThread.currentThread().quit()

    def _thread_finished(self) -> None:
        thread, worker = self._thread, self._worker
        if thread is not None and not thread.wait(0):
            QTimer.singleShot(0, self._thread_finished)
            return
        self._thread = None
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        if thread is not None:
            thread.deleteLater()
        pending, self._pending_request = self._pending_request, None
        if pending is not None and not self._shutdown_requested:
            QTimer.singleShot(0, lambda request=pending: self._begin(*request))

    def iter_shutdown_workers(self) -> Tuple[Tuple[str, QThread, object], ...]:
        if self._thread is None:
            return ()
        return (("effect catalogue", self._thread, self._worker),)

    def request_shutdown(self) -> None:
        self._shutdown_requested = True
        self._pending_request = None
        if self._worker is not None:
            self._worker.stop()
        if self._thread is not None:
            self._thread.requestInterruption()
            self._thread.quit()


__all__ = ["EffectCatalogueIndexLane"]
