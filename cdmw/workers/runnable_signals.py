"""Signal objects for QRunnable pool tasks that the pool thread never deletes.

A pool task emits its result through a small QObject created on the GUI thread.
QThreadPool deletes a finished task on the pool thread, and when the task's
owner has already dropped its Python reference (a newer request replaced it, a
cancel, the result slot clearing it), the task's last reference goes there, and
with it the signal object: a GUI-thread QObject deleted on another thread, which
Qt does not support.

`application_owned` gives the signal object the application as its parent, so
no Python reference count decides when it dies. `release` asks the object's own
thread to delete it; the task calls it last in `run`, after any emit, so the
queued result is delivered before the object goes.
"""

from __future__ import annotations

from typing import TypeVar

from PySide6.QtCore import QCoreApplication, QObject, QThread

SignalsT = TypeVar("SignalsT", bound=QObject)


def application_owned(signals_type: type[SignalsT]) -> SignalsT:
    """Create the signal object on the GUI thread, owned by the application."""

    application = QCoreApplication.instance()
    if application is not None and QThread.currentThread() is application.thread():
        return signals_type(application)
    return signals_type()


def release(signals: QObject) -> None:
    """From any thread: delete the signal object on its own thread once it is idle."""

    try:
        signals.deleteLater()
    except RuntimeError:
        pass  # Already deleted, with the application.
