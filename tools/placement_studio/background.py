"""One cancellable task plus one newest pending request, with nonblocking teardown."""
from __future__ import annotations

from threading import Condition, Event
import time
import weakref

from PySide6.QtCore import QCoreApplication, QObject, QThread, QTimer, Signal


_retained = set()
_IDLE_TIMEOUT = 0.5


def _release(thread):
    # finished is emitted just before native teardown. Retain until wait(0) confirms it.
    if not thread.wait(0):
        QTimer.singleShot(10, lambda: _release(thread))
        return
    _retained.discard(thread)
    thread.deleteLater()


def others_busy(*, excluding: str = "") -> bool:
    """Whether a task other than those named `excluding` is running right now.

    A running task is Python on another thread, so the UI thread will queue for the GIL;
    the viewport uses this to move its playback frames off the UI thread only then.
    """

    # Sleeping persistent LatestTask threads set _active_work=False; plain retained QThreads
    # (such as window_carry stopping threads) fall back to thread.isRunning().
    return any(
        getattr(thread, "owner", "") != excluding
        and bool(getattr(thread, "_active_work", thread.isRunning()))
        for thread in tuple(_retained)
    )


def _stop_thread_ref(thread_ref) -> None:
    thread = thread_ref()
    if thread is not None:
        thread.request_stop()


class _WorkerThread(QThread):
    completed = Signal(int, int, object, str, bool)
    progress = Signal(int, int, int)

    def __init__(self, owner: str = ""):
        super().__init__()  # Never parent a running native thread to a closing widget.
        self.owner = owner
        self._cond = Condition()
        self._job = None
        self._stop = False
        self._exiting = False
        self._active_work = False
        self._idle_event = Event()
        self._idle_event.set()

    def submit_job(self, generation: int, seq: int, work, cancel_event: Event) -> bool:
        with self._cond:
            if self._exiting or self._stop:
                return False
            self._job = (generation, seq, work, cancel_event)
            self._active_work = True
            self._idle_event.clear()
            self._cond.notify_all()
            return True

    def cancel_queued(self) -> None:
        with self._cond:
            if self._job is not None:
                _gen, _seq, _work, cancel_event = self._job
                cancel_event.set()
                self._job = (_gen, _seq, None, cancel_event)

    def request_stop(self) -> None:
        with self._cond:
            self._stop = True
            self._exiting = True
            self._job = None
            self._cond.notify_all()

    def wait_idle(self, msecs: int) -> bool:
        return self._idle_event.wait(max(0, int(msecs)) / 1000.0)

    def run(self):
        try:
            while True:
                with self._cond:
                    deadline = None
                    while self._job is None and not self._stop:
                        self._active_work = False
                        self._idle_event.set()
                        if deadline is None:
                            deadline = time.monotonic() + _IDLE_TIMEOUT
                        remaining = deadline - time.monotonic()
                        if remaining <= 0.0:
                            self._exiting = True
                            return
                        self._cond.wait(remaining)
                    if self._stop:
                        self._active_work = False
                        self._idle_event.set()
                        self._exiting = True
                        return
                    generation, seq, work, cancelled = self._job
                    self._job = None
                    self._active_work = True
                    self._idle_event.clear()
                result, error = None, ""
                try:
                    if work is not None and not cancelled.is_set():
                        result = work(
                            cancelled.is_set,
                            lambda a, b, gen=generation: self.progress.emit(gen, a, b),
                        )
                except Exception as exc:  # report to the owning UI thread
                    error = str(exc)
                work = None
                with self._cond:
                    idle_now = self._job is None or self._stop
                    if idle_now:
                        self._active_work = False
                        self._idle_event.set()
                self.completed.emit(generation, seq, result, error, idle_now)
        finally:
            with self._cond:
                self._active_work = False
                self._idle_event.set()
                self._exiting = True


class LatestTask(QObject):
    """Only current results reach ready; obsolete work stops before its next expensive stage."""
    ready = Signal(object, str)
    progress = Signal(int, int)
    idle = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._generation = 0
        self._submitted_seq = 0
        self._thread = None
        self._current_cancel = None
        self._busy = False
        self._closed = False

    @property
    def busy(self):
        return bool(self._busy)

    def _create_thread(self) -> _WorkerThread:
        thread = self._thread = _WorkerThread(self.objectName())
        _retained.add(thread)
        thread.completed.connect(self._completed)
        thread.progress.connect(self._progress)
        thread.finished.connect(lambda t=thread: self._thread_finished(t))
        thread.finished.connect(lambda t=thread: _release(t))
        ref = weakref.ref(thread)
        self.destroyed.connect(lambda _obj=None, r=ref: _stop_thread_ref(r))
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(lambda r=ref: _stop_thread_ref(r))
        return thread

    def submit(self, work):
        if self._closed:
            return
        self.cancel()
        self._submitted_seq += 1
        seq = self._submitted_seq
        cancel_event = Event()
        self._current_cancel = cancel_event
        self._busy = True
        thread = self._thread
        if thread is not None:
            thread.owner = self.objectName()
            if thread.submit_job(self._generation, seq, work, cancel_event):
                if not thread.isRunning():
                    thread.start()
                return
        thread = self._create_thread()
        thread.submit_job(self._generation, seq, work, cancel_event)
        thread.start()

    def cancel(self):
        self._generation += 1
        if self._current_cancel is not None:
            self._current_cancel.set()
            self._current_cancel = None
        if self._thread is not None:
            self._thread.cancel_queued()

    def shutdown(self):
        self._closed = True
        self.cancel()
        self._busy = False
        if self._thread is not None:
            self._thread.request_stop()

    def wait(self, msecs: int) -> bool:
        """Block until the running work returns, at most `msecs`; True when nothing runs."""
        thread = self._thread
        if thread is None:
            return True
        if self._closed:
            return thread.wait(msecs)
        return thread.wait_idle(msecs)

    def _completed(self, generation, seq, result, error, idle_now):
        became_idle = bool(idle_now) and seq == self._submitted_seq
        if became_idle:
            self._busy = False
        if not self._closed and generation == self._generation:
            self.ready.emit(result, error)
        if became_idle and not self._busy and not self._closed:
            self.idle.emit()

    def _progress(self, generation, done, total):
        if not self._closed and generation == self._generation:
            self.progress.emit(done, total)

    def _thread_finished(self, thread):
        if self._thread is thread:
            self._thread = None
