"""Archive catalogue requests for AI tools, waited for on the tool's thread.

``ArchiveCatalogueService`` is a Qt service on the UI thread: each method
starts a request on the archive worker process and returns its id, and the
answer comes back later as a signal. This submits on the UI thread (a short
call), and the tool's thread waits for the signal, so neither the UI nor the
worker waits on the other. Browse Archives uses the same service and the
same worker; a request from a tool is one more request.
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject


class _Waiting:
    def __init__(self, on_batch=None) -> None:
        self.done = threading.Event()
        self.result: object = None
        self.error = ""
        self.cancelled = False
        self.batches: list[object] = []
        self.on_batch = on_batch


class CatalogueCalls(QObject):
    """One per catalogue service; lives on the UI thread."""

    def __init__(self, service, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self._waiting: dict[str, _Waiting] = {}
        self._lock = threading.Lock()
        service.result_ready.connect(self._result)
        service.request_failed.connect(self._failed)
        service.request_cancelled.connect(self._cancelled)
        service.batch_ready.connect(self._batch)

    def ui_generation(self) -> int:
        # Requests at the service's current generation are never stale; a
        # rescan that invalidates them cancels them, and the tool says so.
        return int(getattr(self.service, "_minimum_ui_generation", 0) or 0)

    def submit(self, method: str, *args, on_batch=None) -> tuple[str, _Waiting]:
        """On the UI thread: start the request and remember who waits for it."""

        waiting = _Waiting(on_batch)
        request_id = getattr(self.service, method)(*args, ui_generation=self.ui_generation())
        with self._lock:
            self._waiting[str(request_id)] = waiting
        return str(request_id), waiting

    def _take(self, request_id: str) -> _Waiting | None:
        with self._lock:
            return self._waiting.pop(str(request_id), None)

    def _result(self, request_id, _operation, payload) -> None:
        waiting = self._take(request_id)
        if waiting is not None:
            waiting.result = payload
            waiting.done.set()

    def _failed(self, request_id, error) -> None:
        waiting = self._take(request_id)
        if waiting is not None:
            waiting.error = str(getattr(error, "message", "") or error or "The archive worker failed.")
            waiting.done.set()

    def _cancelled(self, request_id) -> None:
        waiting = self._take(request_id)
        if waiting is not None:
            waiting.cancelled = True
            waiting.done.set()

    def _batch(self, request_id, _operation, payload) -> None:
        with self._lock:
            waiting = self._waiting.get(str(request_id))
        if waiting is not None:
            waiting.batches.append(payload)
            if waiting.on_batch is not None:
                try:
                    waiting.on_batch(payload)
                except Exception:
                    pass


def wait_for(context, waiting: _Waiting, request_id: str, cancel: threading.Event | None, timeout: float):
    """On the tool's thread: the result, or a ToolError for failed, cancelled and timed-out requests."""

    from cdmw.mcp.errors import CANCELLED, FAILED, ToolError

    deadline = time.monotonic() + timeout
    while not waiting.done.wait(0.05):
        if (cancel is not None and cancel.is_set()) or time.monotonic() > deadline:
            calls = context.catalogue_calls()
            context.ui_call(lambda: calls.service.cancel(request_id))
            if cancel is not None and cancel.is_set():
                raise ToolError(CANCELLED, "Cancelled.")
            raise ToolError(FAILED, "The archive worker did not answer in time.")
    if waiting.cancelled:
        raise ToolError(CANCELLED, "The request was cancelled, for example because the archives were reloaded.")
    if waiting.error:
        raise ToolError(FAILED, waiting.error)
    return waiting.result
