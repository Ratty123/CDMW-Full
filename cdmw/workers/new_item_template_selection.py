"""Prepare a template before its UI observers read family/material/validation facts."""

import threading

from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal

from cdmw.domain.cancellation import RunCancelled, raise_if_cancelled


def prepare_template(snapshot, key, stop_event):
    from cdmw.services.new_item_snapshot import build_context
    from cdmw.services.new_item_template_model import template_material_parts

    raise_if_cancelled(stop_event)
    build_context(snapshot, key)
    raise_if_cancelled(stop_event)
    parts = template_material_parts(snapshot, key, stop_event=stop_event)
    raise_if_cancelled(stop_event)
    return parts


class _SelectionThread(QThread):
    completed = Signal(int, object, object, object)
    failed = Signal(int, str)

    def __init__(self, generation, snapshot, key, parent):
        super().__init__()
        self.setParent(parent)
        self.generation, self.snapshot, self.key = generation, snapshot, key
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            parts = prepare_template(self.snapshot, self.key, self.stop_event)
            if not self.stop_event.is_set():
                self.completed.emit(self.generation, self.snapshot, self.key, parts)
        except RunCancelled:
            pass
        except Exception as exc:
            self.failed.emit(self.generation, str(exc))


class TemplateSelectionLane(QObject):
    completed = Signal(object, object, object)
    failed = Signal(str)

    def __init__(self, *, synchronous=False, parent=None):
        super().__init__(parent)
        self._synchronous = synchronous
        self._generation = 0
        self._thread = self._pending = None
        self._closed = False
        self._reap = QTimer(self)
        self._reap.setSingleShot(True)
        self._reap.timeout.connect(self._finished)

    def request(self, snapshot, key):
        if self._closed:
            return
        self.cancel()
        self._pending = (self._generation, snapshot, key)
        self._start()

    def cancel(self):
        self._generation += 1
        self._pending = None
        if self._thread is not None:
            self._thread.stop()

    def _start(self):
        if self._closed or self._thread is not None or self._pending is None:
            return
        (generation, snapshot, key), self._pending = self._pending, None
        if self._synchronous:
            try:
                self._completed(generation, snapshot, key, prepare_template(snapshot, key, threading.Event()))
            except Exception as exc:
                self._failed(generation, str(exc))
            return
        thread = _SelectionThread(generation, snapshot, key, self)
        self._thread = thread
        thread.completed.connect(self._completed, Qt.QueuedConnection)
        thread.failed.connect(self._failed, Qt.QueuedConnection)
        thread.finished.connect(self._finished, Qt.QueuedConnection)
        thread.start()

    def _completed(self, generation, snapshot, key, parts):
        if not self._closed and generation == self._generation:
            self.completed.emit(snapshot, key, parts)

    def _failed(self, generation, message):
        if not self._closed and generation == self._generation:
            self.failed.emit(message)

    def _finished(self):
        if self._thread is None:
            return
        if not self._thread.wait(0):
            self._reap.start(1)
            return
        self._thread.deleteLater()
        self._thread = None
        self._start()

    def iter_shutdown_workers(self):
        return (("template selection", self._thread, self._thread),) if self._thread is not None else ()

    def request_shutdown(self):
        self._closed = True
        self.cancel()
