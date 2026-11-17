"""Run cyclic Python cleanup on Qt's GUI thread, never an allocating worker.

Every second the young generation is collected: its cost follows what was
allocated since the last pass, a few milliseconds. A full collection walks
every live object (millions once the archive catalogue, a Create New Item
snapshot and a Mesh Editor session are loaded: seconds on the window thread),
so it runs only while nobody has touched the keyboard or mouse for a while, or
when one has not run for a long time, and only after something was allocated.
"""

from __future__ import annotations

import gc
import logging
import sys
import time
from typing import Callable

from PySide6.QtCore import QObject, QThread, QTimer, Slot
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid


# Python 3.14.0-3.14.4 collect a slice of the old generation with collect(1).
# Python 3.11 and 3.14.5+ use the three-generation thresholds instead. On
# 3.14.3 that slice is usually empty and now and then the whole heap: a
# collect(1) took 4.8 s on the window thread in the review (2.3 GiB private).
_INCREMENTAL_GC = (3, 14, 0) <= sys.version_info[:3] < (3, 14, 5)

#: No input to any window for this long counts as idle.
FULL_COLLECTION_IDLE_S = 5.0
#: Full collections are at least this far apart...
FULL_COLLECTION_MIN_INTERVAL_S = 60.0
#: ...and at most this far, idle or not, so old garbage cannot pile up.
FULL_COLLECTION_MAX_INTERVAL_S = 300.0
#: Young collections since the last full one before another is worth it.
FULL_COLLECTION_MIN_YOUNG_PASSES = 10

_LOGGER = logging.getLogger(__name__)
_input_functions = None


def _system_input_idle_seconds() -> float:
    """Seconds since the last keyboard or mouse input to any window (Windows)."""

    global _input_functions
    if sys.platform != "win32":
        return 0.0
    import ctypes
    from ctypes import wintypes

    class LastInputInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    if _input_functions is None:
        # Private loaders: typing `ctypes.windll` functions changes them for
        # every module in the process.
        user32, kernel32 = ctypes.WinDLL("user32"), ctypes.WinDLL("kernel32")
        user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LastInputInfo)]
        user32.GetLastInputInfo.restype = wintypes.BOOL
        kernel32.GetTickCount.argtypes = []
        kernel32.GetTickCount.restype = wintypes.DWORD
        _input_functions = (user32.GetLastInputInfo, kernel32.GetTickCount, LastInputInfo)
    get_last_input, get_tick_count, info_type = _input_functions
    info = info_type()
    info.cbSize = ctypes.sizeof(info)
    if not get_last_input(ctypes.byref(info)):
        return 0.0
    return ((int(get_tick_count()) - int(info.dwTime)) & 0xFFFFFFFF) / 1000.0


def _release_layout_item_wrappers() -> None:
    """The idle sweep of PySide's wrappers of Qt-made layout items (see layout_item_wrappers)."""

    try:
        from cdmw.ui.layout_item_wrappers import release_all_layout_item_wrappers

        release_all_layout_item_wrappers()
    except Exception:  # noqa: BLE001 - a sweep must never break the collector
        _LOGGER.debug("layout item wrapper sweep failed", exc_info=True)


class GuiGarbageCollector(QObject):
    def __init__(
        self,
        app: QApplication,
        *,
        input_idle_seconds: Callable[[], float] = _system_input_idle_seconds,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(app)
        restore_gc = gc.enable if gc.isenabled() else gc.disable
        gc.disable()
        # aboutToQuit is too early: workers and Qt objects still need teardown.
        # Do not capture self in this callback or depend on a live Qt wrapper.
        self.destroyed.connect(lambda: restore_gc())
        self._collecting = False
        self._input_idle_seconds = input_idle_seconds
        self._clock = clock
        self._last_full_at = clock()
        self._young_passes_since_full = 0
        self.last_full_collection_ms = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._collect)
        self._timer.start()

    def _full_collection_due(self) -> bool:
        if self._young_passes_since_full < FULL_COLLECTION_MIN_YOUNG_PASSES:
            return False
        since_full = self._clock() - self._last_full_at
        if since_full < FULL_COLLECTION_MIN_INTERVAL_S:
            return False
        if since_full >= FULL_COLLECTION_MAX_INTERVAL_S:
            return True
        try:
            return float(self._input_idle_seconds()) >= FULL_COLLECTION_IDLE_S
        except Exception:  # noqa: BLE001 - no input clock means not idle
            return False

    @Slot()
    def _collect(self) -> None:
        if self._collecting:
            return
        self._collecting = True
        try:
            if self._full_collection_due():
                started = time.perf_counter()
                gc.collect()
                _release_layout_item_wrappers()
                self.last_full_collection_ms = (time.perf_counter() - started) * 1000.0
                self._last_full_at = self._clock()
                self._young_passes_since_full = 0
                if self.last_full_collection_ms >= 250.0:
                    _LOGGER.info("gui_full_gc elapsed_ms=%.0f", self.last_full_collection_ms)
                return
            counts, thresholds = gc.get_count(), gc.get_threshold()
            if thresholds[0] <= 0 or counts[0] < thresholds[0]:
                return
            # The older generations only in a full collection (above): on the
            # window thread their cost is the whole heap's.
            generation = 0
            if not _INCREMENTAL_GC and counts[1] > thresholds[1]:
                generation = 1
            gc.collect(generation)
            self._young_passes_since_full += 1
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
