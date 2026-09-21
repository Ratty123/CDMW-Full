"""Bounded cancellable lookups for New Item panels; only the latest result lands."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal

from cdmw.domain.cancellation import RunCancelled


class _LookupThread(QThread):
    completed = Signal(int, object, object)
    failed = Signal(int, object, str)

    def __init__(self, generation, key, task):
        super().__init__()
        self.generation, self.key, self.task = generation, key, task
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            result = self.task(self.stop_event)
            if not self.stop_event.is_set():
                self.completed.emit(self.generation, self.key, result)
        except RunCancelled:
            pass
        except Exception as exc:  # noqa: BLE001 - delivered to the owning panel
            self.failed.emit(self.generation, self.key, str(exc))


class NewItemLookupLane(QObject):
    completed = Signal(object, object)
    failed = Signal(object, str)

    def __init__(self, *, synchronous=False, parent=None):
        super().__init__(parent)
        self._synchronous = synchronous
        self._generation = 0
        self._thread = self._pending = None
        self._closed = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._start)
        self._reap = QTimer(self)
        self._reap.setSingleShot(True)
        self._reap.timeout.connect(self._finished)

    @property
    def busy(self):
        return self._thread is not None or self._pending is not None

    def request(self, key, task, *, delay_ms=0):
        if self._closed:
            return
        self.cancel()
        self._pending = (self._generation, key, task)
        if self._synchronous:
            self._start()
        else:
            self._timer.start(delay_ms)

    def cancel(self):
        self._generation += 1
        self._timer.stop()
        self._pending = None
        if self._thread is not None:
            self._thread.stop()

    def _start(self):
        if self._closed or self._thread is not None or self._pending is None:
            return
        (generation, key, task), self._pending = self._pending, None
        if self._synchronous:
            try:
                self._completed(generation, key, task(threading.Event()))
            except RunCancelled:
                pass
            except Exception as exc:  # noqa: BLE001 - same error delivery as threaded execution
                self._failed(generation, key, str(exc))
            return
        thread = self._thread = _LookupThread(generation, key, task)
        thread.setParent(self)
        thread.completed.connect(self._completed, Qt.QueuedConnection)
        thread.failed.connect(self._failed, Qt.QueuedConnection)
        thread.finished.connect(self._finished, Qt.QueuedConnection)
        thread.start(QThread.LowPriority)

    def _completed(self, generation, key, result):
        if not self._closed and generation == self._generation:
            self.completed.emit(key, result)

    def _failed(self, generation, key, message):
        if not self._closed and generation == self._generation:
            self.failed.emit(key, message)

    def _finished(self):
        thread = self._thread
        if thread is None:
            return
        if not thread.wait(0):
            self._reap.start(1)
            return
        self._thread = None
        thread.deleteLater()
        if not self._timer.isActive():
            self._start()

    def iter_shutdown_workers(self):
        return (("new item lookup", self._thread, self._thread),) if self._thread is not None else ()

    def request_shutdown(self):
        self._closed = True
        self.cancel()
