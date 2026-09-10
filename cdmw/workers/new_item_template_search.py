"""One cancellable, latest-request-only lane for the Template Find field."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal

from cdmw.domain.cancellation import RunCancelled
from cdmw.services.new_item_template_search import TemplateSearchCatalogue, search_template_options


@dataclass(frozen=True)
class _SearchRequest:
    catalogue: TemplateSearchCatalogue
    text: str
    group_key: int | None
    sort_column: int
    descending: bool

    def run_template_search(self, stop_event=None):
        return search_template_options(
            self.catalogue, self.text, group_key=self.group_key,
            sort_column=self.sort_column, descending=self.descending,
            limit=None, stop_event=stop_event,
        )


class _SearchThread(QThread):
    completed = Signal(int, object, object)
    failed = Signal(int, str)

    def __init__(self, generation, request, parent):
        super().__init__(parent)
        self.generation = generation
        self.request = request
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            options = self.request.run_template_search(self.stop_event)
            if not self.stop_event.is_set():
                self.completed.emit(self.generation, self.request.catalogue, options)
        except RunCancelled:
            pass
        except Exception as exc:  # noqa: BLE001 - report a failed search without losing the current rows
            self.failed.emit(self.generation, str(exc))


class TemplateSearchLane(QObject):
    completed = Signal(object, object)
    failed = Signal(str)

    def __init__(self, *, synchronous=False, parent=None):
        super().__init__(parent)
        self._synchronous = bool(synchronous)
        self._generation = 0
        self._thread = None
        self._pending = None
        self._shutdown_requested = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._start_pending)
        self._reap_timer = QTimer(self)
        self._reap_timer.setSingleShot(True)
        self._reap_timer.timeout.connect(self._thread_finished)

    def request(self, catalogue, text, *, group_key=None, sort_column=-1, descending=False, debounce_ms=150):
        if self._shutdown_requested:
            return
        self.cancel()
        self._pending = (self._generation, _SearchRequest(catalogue, str(text), group_key, sort_column, descending))
        if self._synchronous:
            self._start_pending()
        else:
            self._timer.start(debounce_ms)

    def cancel(self):
        self._generation += 1
        self._timer.stop()
        self._pending = None
        if self._thread is not None:
            self._thread.stop()

    def _start_pending(self):
        if self._shutdown_requested or self._thread is not None or self._pending is None:
            return
        (generation, request), self._pending = self._pending, None
        if self._synchronous:
            try:
                self._completed(generation, request.catalogue, request.run_template_search())
            except Exception as exc:  # noqa: BLE001 - same failure contract as the background worker
                self._failed(generation, str(exc))
            return
        thread = _SearchThread(generation, request, self)
        self._thread = thread
        thread.completed.connect(self._completed, Qt.ConnectionType.QueuedConnection)
        thread.failed.connect(self._failed, Qt.ConnectionType.QueuedConnection)
        thread.finished.connect(self._thread_finished, Qt.ConnectionType.QueuedConnection)
        thread.start()

    def _completed(self, generation, catalogue, options):
        if not self._shutdown_requested and generation == self._generation:
            self.completed.emit(catalogue, options)

    def _failed(self, generation, message):
        if not self._shutdown_requested and generation == self._generation:
            self.failed.emit(message)

    def _thread_finished(self):
        thread = self._thread
        if thread is None:
            return
        if not thread.wait(0):
            self._reap_timer.start(1)
            return
        self._thread = None
        thread.deleteLater()
        if not self._timer.isActive():
            self._start_pending()

    def iter_shutdown_workers(self):
        return (("template search", self._thread, self._thread),) if self._thread is not None else ()

    def request_shutdown(self):
        self._shutdown_requested = True
        self.cancel()
