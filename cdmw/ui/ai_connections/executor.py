"""Run a short call on the UI thread from a tool's thread, and wait for it.

The same pattern as the automation bridge: a queued signal hands the call to
the UI thread, which runs it as a click's handler would; the caller waits on
an event. A call only starts work or reads interface state; slow work runs
on the worker the interface already uses for it.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Qt, Signal

UI_CALL_TIMEOUT_S = 30.0


class _Pending:
    def __init__(self, function: Callable[[], object]) -> None:
        self.function = function
        self.done = threading.Event()
        self.result: object = None
        self.error: BaseException | None = None


class UiExecutor(QObject):
    _run = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._run.connect(self._on_ui, Qt.ConnectionType.QueuedConnection)

    def call(self, function: Callable[[], object], timeout: float = UI_CALL_TIMEOUT_S) -> object:
        if QThread.currentThread() is self.thread():
            return function()
        pending = _Pending(function)
        self._run.emit(pending)
        if not pending.done.wait(timeout):
            from cdmw.mcp.errors import FAILED, ToolError

            raise ToolError(FAILED, "The interface did not answer in time; try again when CDMW is idle.")
        if pending.error is not None:
            raise pending.error
        return pending.result

    def _on_ui(self, pending: _Pending) -> None:
        try:
            pending.result = pending.function()
        except BaseException as exc:  # handed back to the caller's thread
            pending.error = exc
        finally:
            pending.done.set()
