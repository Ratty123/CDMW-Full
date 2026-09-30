"""Tracked retirement cleanup for New Item import sources and preview packages."""

from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from PySide6.QtCore import QObject, QProcess, QThread, Qt, QTimer
from shiboken6 import isValid

from cdmw.core.owned_temp import cleanup_owned_temp_directory
from cdmw.workers.new_item_workers import model_source_cleanup_task
from cdmw.workers.utility_workers import UtilityWorker


def preview_process_barrier(controller: object) -> threading.Event:
    """Capture owned processes on the GUI thread before requesting shutdown.

    Retired packages can wait on this event in the cleanup lane. Connecting before
    shutdown also covers a process that exits immediately or fails during startup.
    """
    ready = threading.Event()
    children = getattr(controller, "findChildren", None)
    pending = set(children(QProcess) if callable(children) else ())

    def retired(process: QProcess) -> None:
        pending.discard(process)
        if not pending:
            ready.set()

    def settled(process: QProcess) -> None:
        if not isValid(process) or process.state() == QProcess.NotRunning:
            retired(process)

    for process in tuple(pending):
        process.finished.connect(lambda *_args, process=process: settled(process))
        process.errorOccurred.connect(lambda *_args, process=process: settled(process))
        process.destroyed.connect(lambda *_args, process=process: retired(process))
        settled(process)
    if not pending:
        ready.set()
    return ready


@dataclass(frozen=True, slots=True)
class EmptyOwnedTempCleanup:
    """Retire an empty marked root after its builder and preview consumers stop."""

    path: Path
    ready: tuple[threading.Event, ...] = ()

    def wait_until_unused(self) -> None:
        for event in self.ready:
            event.wait()

    def cleanup(self) -> None:
        cleanup_owned_temp_directory(self.path, only_empty=True)


@dataclass(frozen=True, slots=True)
class PreviewPackageCleanup:
    """One retired transient directory, bounded by its owning preview root."""

    path: Path
    output_root: Path
    direct_package: bool = False
    ready: threading.Event | None = None
    empty_root_cleanup: EmptyOwnedTempCleanup | None = None

    def wait_until_unused(self, stop_event=None) -> None:
        if self.ready is not None:
            self.ready.wait()

    def cleanup(self) -> None:
        path = self.path.resolve()
        root = self.output_root.resolve()
        if path == root or not path.is_relative_to(root):
            raise ValueError("Preview cleanup must stay inside its output root.")
        if self.direct_package and (path.parent != root or not path.name.startswith("package_")):
            raise ValueError("Effect cleanup must name a directly owned package.")
        shutil.rmtree(path, ignore_errors=True)
        if self.empty_root_cleanup is not None:
            self.empty_root_cleanup.wait_until_unused()
            self.empty_root_cleanup.cleanup()


class ModelSourceCleanupLane(QObject):
    """Remove retired roots serially off the UI thread after all source usages end."""

    def __init__(self, *, synchronous: bool = False, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._synchronous = bool(synchronous)
        self._jobs: list[tuple[QThread, UtilityWorker, object]] = []
        self._pending: list[object] = []

    def retire(self, source: object | None) -> None:
        cleanup = getattr(source, "cleanup", None)
        if (
            not callable(cleanup)
            or any(item[2] is source for item in self._jobs)
            or any(item is source for item in self._pending)
        ):
            return
        retire = getattr(source, "retire", None)
        if callable(retire):
            retire()
        if self._synchronous:
            model_source_cleanup_task(source)(lambda _message: None, threading.Event())
            return
        self._pending.append(source)
        self._start_next()

    def _start_next(self) -> None:
        if self._jobs or not self._pending:
            return
        source = self._pending.pop(0)
        task = model_source_cleanup_task(source)
        worker = UtilityWorker(task, task_accepts_cancel=True)
        # ChildAdded observers must see the fully initialized QThread wrapper.
        thread = QThread()
        thread.setParent(self)
        worker.moveToThread(thread)
        self._jobs.append((thread, worker, source))
        worker.finished.connect(self._worker_finished, Qt.DirectConnection)
        thread.finished.connect(self._thread_finished, Qt.QueuedConnection)
        thread.started.connect(worker.run)
        thread.start()

    def iter_shutdown_workers(self) -> Tuple[Tuple[str, QThread, object], ...]:
        # A close poll can precede delivery of thread.finished. Promote queued
        # cleanup before reporting that the lane has no running workers.
        for thread, _worker, _source in tuple(self._jobs):
            if thread.isFinished():
                self._retire_thread(thread)
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
        self._start_next()


__all__ = ["EmptyOwnedTempCleanup", "ModelSourceCleanupLane", "PreviewPackageCleanup", "preview_process_barrier"]
