"""Run cyclic Python cleanup on Qt's GUI thread, never an allocating worker."""

from __future__ import annotations

import gc
import sys

from PySide6.QtCore import QObject, QThread, QTimer, Slot
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid


# Python 3.14.0-3.14.4 collect a slice of the old generation with collect(1).
# Python 3.11 and 3.14.5+ use the three-generation thresholds instead.
_INCREMENTAL_GC = (3, 14, 0) <= sys.version_info[:3] < (3, 14, 5)


class GuiGarbageCollector(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        restore_gc = gc.enable if gc.isenabled() else gc.disable
        gc.disable()
        # aboutToQuit is too early: workers and Qt objects still need teardown.
        # Do not capture self in this callback or depend on a live Qt wrapper.
        self.destroyed.connect(lambda: restore_gc())
        self._collecting = False
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._collect)
        self._timer.start()

    @Slot()
    def _collect(self) -> None:
        if self._collecting:
            return
        counts, thresholds = gc.get_count(), gc.get_threshold()
        if thresholds[0] <= 0 or counts[0] < thresholds[0]:
            return
        generation = 0
        if _INCREMENTAL_GC:
            generation = 1
        elif counts[1] > thresholds[1]:
            generation = 2 if counts[2] > thresholds[2] else 1
        self._collecting = True
        try:
            gc.collect(generation)
        finally:
            self._collecting = False


def ensure_app_garbage_collector(app: QApplication) -> GuiGarbageCollector:
    if QThread.currentThread() != app.thread():
        raise RuntimeError("GUI garbage collection must be installed on the GUI thread")
    existing = getattr(app, "_cdmw_garbage_collector", None)
    if isinstance(existing, GuiGarbageCollector) and isValid(existing):
        return existing
    collector = GuiGarbageCollector(app)
    app._cdmw_garbage_collector = collector
    return collector
