"""Delete a QThread's worker on the GUI thread, once that thread has ended.

The usual shape, ``worker.finished.connect(worker.deleteLater)``, deletes the
worker on its own thread: the thread's event loop, or ``QThread``'s finish
step when ``quit`` came first, runs the DeferredDelete there. For a worker
made in Python, PySide's destructor then takes the GIL on that thread. The GUI
thread meanwhile drops its own Python reference (``self._worker = None`` in a
``finished`` slot), and PySide deletes a Python-owned QObject at once, on the
thread that dropped it, whichever thread the object lives in. Both threads
delete the same worker: an access violation on an unnamed ``[QThread]`` with
no Python frame, or a heap corruption. Under GIL contention (a busy Python
worker, such as Finish in the Mesh Editor) the window is milliseconds wide;
B pass 13 crashed this way twice, in Finish while the texture sharing search
ran its per-batch scan threads.

`release_worker_after_thread` replaces that connection. It holds a Python
reference to the worker until ``thread.isFinished()`` (QThread sets it after
its last DeferredDelete), so the last reference, and with it the C++ delete,
goes on the GUI thread after the worker's thread is gone. The worker thread
never runs a PySide destructor for it.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QCoreApplication, QObject, Qt, QThread, QTimer, Slot

#: How often the held workers are looked at again while a finished thread winds down.
_SWEEP_INTERVAL_MS = 5

_lock = threading.Lock()
_reaper: "_WorkerReaper | None" = None


class _WorkerReaper(QObject):
    """One per application, on the GUI thread: holds workers until their threads end."""

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._held: dict[int, tuple[object, object]] = {}
        self._held_lock = threading.Lock()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_SWEEP_INTERVAL_MS)
        self._timer.timeout.connect(self.sweep)

    def hold(self, thread: QThread, worker: QObject) -> None:
        with self._held_lock:
            self._held[id(worker)] = (thread, worker)
        # A slot of this GUI-thread object: queued from the ending thread, and no
        # Python callable whose connection the worker thread would have to free.
        thread.finished.connect(self.sweep, Qt.ConnectionType.UniqueConnection)

    def held_count(self) -> int:
        with self._held_lock:
            return len(self._held)

    @Slot()
    def sweep(self) -> None:
        released = []
        with self._held_lock:
            for key, (thread, worker) in list(self._held.items()):
                if _thread_ended(thread):
                    released.append(self._held.pop(key))
            pending = bool(self._held)
        for _thread, worker in released:
            _delete_if_cpp_owned(worker)
        released.clear()  # the last Python references go here, on the GUI thread
        if pending and not self._timer.isActive():
            self._timer.start()


def _thread_ended(thread: object) -> bool:
    try:
        return bool(thread.isFinished())  # type: ignore[attr-defined]
    except RuntimeError:
        return True  # the QThread itself was deleted, which Qt allows only once it ended
    except AttributeError:
        return True


def _delete_if_cpp_owned(worker: object) -> None:
    """A worker Python does not own is not deleted by dropping it: delete it here."""

    try:
        import shiboken6

        if shiboken6.isValid(worker) and not shiboken6.ownedByPython(worker):
            shiboken6.delete(worker)
    except (RuntimeError, TypeError):
        pass


def _application_reaper() -> _WorkerReaper | None:
    global _reaper
    application = QCoreApplication.instance()
    if application is None:
        return None
    with _lock:
        reaper = _reaper
        try:
            if reaper is not None and reaper.parent() == application:
                return reaper
        except RuntimeError:
            pass  # deleted with an earlier application
        if QThread.currentThread() != application.thread():
            return None
        _reaper = reaper = _WorkerReaper(application)
        return reaper


def release_worker_after_thread(thread: QThread, worker: QObject) -> None:
    """Use in place of ``worker.finished.connect(worker.deleteLater)`` for a worker
    moved to ``thread``: the worker is deleted on the GUI thread after the thread ended."""

    reaper = _application_reaper() if isinstance(thread, QThread) and isinstance(worker, QObject) else None
    if reaper is None:
        # No application yet, a thread started off the GUI thread, or stand-ins in a
        # test: the old way.
        worker.finished.connect(worker.deleteLater)  # type: ignore[attr-defined]
        return
    reaper.hold(thread, worker)


def held_worker_count() -> int:
    """Workers waiting for their thread to end (tests, diagnostics)."""

    reaper = _reaper
    try:
        return reaper.held_count() if reaper is not None else 0
    except RuntimeError:
        return 0


__all__ = ["held_worker_count", "release_worker_after_thread"]
