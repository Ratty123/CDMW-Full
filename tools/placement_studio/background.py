"""One cancellable task plus one newest pending request, with nonblocking teardown."""
from __future__ import annotations

from threading import Event

from PySide6.QtCore import QObject, QThread, QTimer, Signal


_retained = set()


def _release(thread):
    # finished is emitted just before native teardown. Retain until wait(0) confirms it.
    if not thread.wait(0):
        QTimer.singleShot(10, lambda: _release(thread))
        return
    _retained.discard(thread)
    thread.deleteLater()


class _Task(QThread):
    completed = Signal(int, object, str)
    progress = Signal(int, int, int)

    def __init__(self, generation, work):
        super().__init__()  # Never parent a running native thread to a closing widget.
        self.generation = generation
        self.work = work
        self.cancelled = Event()

    def run(self):
        result, error = None, ""
        try:
            result = self.work(self.cancelled.is_set,
                               lambda a, b: self.progress.emit(self.generation, a, b))
        except Exception as exc:  # report to the owning UI thread
            error = str(exc)
        self.work = None
        self.completed.emit(self.generation, result, error)


class LatestTask(QObject):
    """Only current results reach ready; obsolete work stops before its next expensive stage."""
    ready = Signal(object, str)
    progress = Signal(int, int)
    idle = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._generation = 0
        self._thread = None
        self._pending = None
        self._closed = False

    @property
    def busy(self):
        return self._thread is not None or self._pending is not None

    def submit(self, work):
        if self._closed:
            return
        self.cancel()
        self._pending = (self._generation, work)
        self._start_pending()

    def cancel(self):
        self._generation += 1
        self._pending = None
        if self._thread is not None:
            self._thread.cancelled.set()

    def shutdown(self):
        self._closed = True
        self.cancel()

    def _start_pending(self):
        if self._thread is not None or self._pending is None or self._closed:
            return
        generation, work = self._pending
        self._pending = None
        thread = self._thread = _Task(generation, work)
        _retained.add(thread)
        thread.completed.connect(self._completed)
        thread.progress.connect(self._progress)
        thread.finished.connect(self._finished)
        thread.finished.connect(lambda: _release(thread))
        thread.start()

    def _completed(self, generation, result, error):
        if not self._closed and generation == self._generation:
            self.ready.emit(result, error)

    def _progress(self, generation, done, total):
        if not self._closed and generation == self._generation:
            self.progress.emit(done, total)

    def _finished(self):
        self._thread = None
        self._start_pending()
        if self._thread is None:
            self.idle.emit()
