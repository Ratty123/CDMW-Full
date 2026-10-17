"""Track native window moves without changing Windows or Qt DPI handling."""

from __future__ import annotations

import ctypes
import sys
import weakref
from dataclasses import dataclass

from PySide6.QtCore import QAbstractNativeEventFilter, QEvent, QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid


_WM_CANCELMODE = 0x001F
_WM_ENTERSIZEMOVE = 0x0231
_WM_EXITSIZEMOVE = 0x0232
_TRACKER_ATTRIBUTE = "_cdmw_window_interaction_tracker"


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int32), ("y", ctypes.c_int32)]


class _MSG(ctypes.Structure):
    # Fixed-width Win32 LONG/DWORD fields also make the decoder testable off Windows.
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint32),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint32),
        ("pt", _Point),
        ("lPrivate", ctypes.c_uint32),
    ]


class _NativeWindowInteractionFilter(QAbstractNativeEventFilter):
    def __init__(self, tracker: WindowInteractionTracker) -> None:
        super().__init__()
        self._tracker = weakref.ref(tracker)

    def nativeEventFilter(self, event_type, message):
        try:
            if bytes(event_type) not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                return False, 0
            address = int(message)
            if not address:
                return False, 0
            native = _MSG.from_address(address)
            if native.message not in (_WM_ENTERSIZEMOVE, _WM_EXITSIZEMOVE, _WM_CANCELMODE):
                return False, 0
            tracker = self._tracker()
            if tracker is not None and isValid(tracker):
                tracker._native_message(int(native.hwnd or 0), int(native.message))
        except (TypeError, ValueError, OverflowError, RuntimeError, OSError):
            pass
        # WM_DPICHANGED and normal native processing belong to Qt.
        return False, 0


@dataclass
class _WindowState:
    reference: weakref.ReferenceType[QWidget]
    generation: int = 0
    active: bool = False
    ending: bool = False


class WindowInteractionTracker(QObject):
    """Window-scoped holds, released after the native move/resize handler returns.

    ``begin`` and ``end`` are deterministic hooks for behavioral tests. On other
    platforms they are the only way to start a hold; no native filter is installed.
    """

    started = Signal(object)
    finished = Signal(object)

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._windows: dict[int, _WindowState] = {}
        self._generation = 0
        self._native_filter = _NativeWindowInteractionFilter(self)
        app.installEventFilter(self)
        if sys.platform == "win32":
            app.installNativeEventFilter(self._native_filter)

    @staticmethod
    def _top_level(window: QWidget | None) -> QWidget | None:
        if window is None or not isinstance(window, QWidget) or not isValid(window):
            return None
        try:
            return window.window()
        except RuntimeError:
            return None

    def is_active(self, window: QWidget) -> bool:
        top_level = self._top_level(window)
        if top_level is None:
            return False
        state = self._windows.get(id(top_level))
        return bool(state and state.reference() is top_level and state.active)

    def begin(self, window: QWidget) -> None:
        top_level = self._top_level(window)
        if top_level is None:
            return
        key = id(top_level)
        state = self._windows.get(key)
        if state is None or state.reference() is not top_level:
            reference = weakref.ref(top_level, lambda ref, key=key: self._forget(key, ref))
            state = _WindowState(reference)
            self._windows[key] = state
            top_level.destroyed.connect(
                lambda _object=None, key=key, ref=reference: self._forget(key, ref)
            )
        if state.active and not state.ending:
            return
        self._generation += 1
        state.generation = self._generation
        state.active = True
        state.ending = False
        self.started.emit(top_level)

    def end(self, window: QWidget) -> None:
        top_level = self._top_level(window)
        if top_level is None:
            return
        key = id(top_level)
        state = self._windows.get(key)
        if state is None or state.reference() is not top_level or not state.active or state.ending:
            return
        state.ending = True
        generation = state.generation
        QTimer.singleShot(0, self, lambda: self._finish(key, generation))

    def _finish(self, key: int, generation: int) -> None:
        state = self._windows.get(key)
        if state is None or state.generation != generation or not state.active or not state.ending:
            return
        window = state.reference()
        if window is None or not isValid(window):
            self._forget(key, state.reference)
            return
        state.active = False
        state.ending = False
        self.finished.emit(window)

    def _forget(self, key: int, reference: weakref.ReferenceType[QWidget]) -> None:
        state = self._windows.get(key)
        if state is not None and state.reference is reference:
            self._windows.pop(key, None)

    def _native_message(self, hwnd: int, message: int) -> None:
        # find() only looks up an existing native handle; it never calls winId().
        window = QWidget.find(hwnd) if hwnd else None
        if window is None:
            return
        if message == _WM_ENTERSIZEMOVE:
            self.begin(window)
        elif message in (_WM_EXITSIZEMOVE, _WM_CANCELMODE):
            self.end(window)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # An accepted close produces Hide. An ignored Close must not end a hold.
        # A replaced HWND may never deliver the old handle's native exit message.
        # Destruction is handled by the signal above without touching the widget.
        if (
            event.type() in (QEvent.Type.Hide, QEvent.Type.WinIdChange)
            and isinstance(watched, QWidget)
            and isValid(watched)
        ):
            if watched.isWindow():
                self.end(watched)
        return False


def ensure_window_interaction_tracker(app: QApplication | None = None) -> WindowInteractionTracker:
    application = app if app is not None else QApplication.instance()
    if not isinstance(application, QApplication):
        raise RuntimeError("A QApplication is required for window interaction tracking")
    tracker = getattr(application, _TRACKER_ATTRIBUTE, None)
    if not isinstance(tracker, WindowInteractionTracker) or not isValid(tracker):
        tracker = WindowInteractionTracker(application)
        setattr(application, _TRACKER_ATTRIBUTE, tracker)
    return tracker
