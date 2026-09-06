"""Windows Qt host for the embedded Rust Mesh Editor child window."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


_GWL_STYLE = -16
_WS_CHILD = 0x40000000
_WS_POPUP = 0x80000000
_SW_HIDE = 0
_SW_SHOW = 5
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_FRAMECHANGED = 0x0020
_SWP_NOOWNERZORDER = 0x0200


def _windows_api() -> object:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    hwnd = wintypes.HWND
    user32.IsWindow.argtypes = [hwnd]
    user32.IsWindow.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [hwnd, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetParent.argtypes = [hwnd]
    user32.GetParent.restype = hwnd
    user32.SetParent.argtypes = [hwnd, hwnd]
    user32.SetParent.restype = hwnd
    user32.GetClientRect.argtypes = [hwnd, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        hwnd,
        hwnd,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [hwnd, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetFocus.argtypes = [hwnd]
    user32.SetFocus.restype = hwnd
    user32.GetWindowLongPtrW.argtypes = [hwnd, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [hwnd, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    return user32


class RustMeshEditorHostFrame(QFrame):
    """Hosts one process-owned winit child and owns its failure/result UI."""

    retry_requested = Signal()
    run_validation_requested = Signal()
    build_mod_requested = Signal()
    install_overlay_requested = Signal()
    restore_overlay_requested = Signal()
    reopen_edit_requested = Signal()
    close_session_requested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        theme_key: str = "graphite",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("MeshEditorEmbeddedRustHost")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumSize(320, 240)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self.controller = None  # Explicitly not a Vortice preview controller.
        self._theme_key = str(theme_key or "graphite")
        self.setProperty("cdmwThemeKey", self._theme_key)
        self._child_hwnd = 0
        self._child_process_id = 0
        self._launch_parent_hwnd = 0
        self._editor_visible = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self._pages = QStackedWidget(self)
        self._pages.setObjectName("MeshEditorRustHostPages")
        root.addWidget(self._pages, 1)

        self._status_page = QFrame(self._pages)
        status_layout = QVBoxLayout(self._status_page)
        status_layout.addStretch(1)
        self._status_label = QLabel("Preparing Mesh Editor...", self._status_page)
        self._status_label.setObjectName("MeshEditorRustHostStatus")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setWordWrap(True)
        status_layout.addWidget(self._status_label)
        retry_row = QHBoxLayout()
        retry_row.addStretch(1)
        self._retry_button = QPushButton("Retry", self._status_page)
        self._retry_button.setObjectName("MeshEditorRustHostRetry")
        self._retry_button.clicked.connect(self.retry_requested.emit)
        retry_row.addWidget(self._retry_button)
        retry_row.addStretch(1)
        status_layout.addLayout(retry_row)
        status_layout.addStretch(1)
        self._pages.addWidget(self._status_page)

        self._result_page = QFrame(self._pages)
        result_layout = QVBoxLayout(self._result_page)
        result_layout.setContentsMargins(28, 28, 28, 28)
        result_layout.addStretch(1)
        title = QLabel("Mesh edit accepted", self._result_page)
        title.setObjectName("MeshEditorRustResultTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        result_layout.addWidget(title)
        self._result_label = QLabel("", self._result_page)
        self._result_label.setObjectName("MeshEditorRustResultSummary")
        self._result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._result_label.setWordWrap(True)
        result_layout.addWidget(self._result_label)
        actions = QGridLayout()
        action_specs = (
            ("Run Validation", self.run_validation_requested),
            ("Build Mod", self.build_mod_requested),
            ("Install as Overlay", self.install_overlay_requested),
            ("Restore Last Overlay Install", self.restore_overlay_requested),
            ("Reopen Edit", self.reopen_edit_requested),
            ("Close Session", self.close_session_requested),
        )
        for index, (text, signal) in enumerate(action_specs):
            button = QPushButton(text, self._result_page)
            button.setObjectName("MeshEditorRustResult" + "".join(text.split()))
            button.setMinimumHeight(34)
            button.clicked.connect(signal.emit)
            actions.addWidget(button, index // 2, index % 2)
        result_layout.addLayout(actions)
        result_layout.addStretch(1)
        self._pages.addWidget(self._result_page)
        self.show_loading("Preparing the embedded Mesh Editor...")

    def set_theme(self, theme_key: str) -> None:
        """Retain CDMW's active theme contract for the embedded surface."""

        self._theme_key = str(theme_key or self._theme_key)
        self.setProperty("cdmwThemeKey", self._theme_key)
        self.update()

    def sync_ui_font(self, font: QFont, data_font: QFont | None = None) -> None:
        """Apply CDMW typography to the Qt-owned loading and result pages."""

        _ = data_font
        applied = QFont(font)
        self.setFont(applied)
        for child in self.findChildren(QWidget):
            child.setFont(applied)

    def host_hwnd(self) -> int:
        try:
            return max(0, int(self.winId()))
        except (RuntimeError, TypeError, ValueError):
            return 0

    @property
    def child_hwnd(self) -> int:
        return int(self._child_hwnd)

    def prepare_launch(self) -> int:
        self.detach_child_window()
        self._launch_parent_hwnd = self.host_hwnd()
        self.show_loading("Preparing the embedded Mesh Editor...")
        return self._launch_parent_hwnd

    def attach_child_window(
        self,
        child_hwnd: int,
        process_id: int,
        embedded_parent_hwnd: int,
    ) -> tuple[bool, str]:
        if sys.platform != "win32":
            return False, "Embedded Mesh Editor is supported on Windows only"
        parent_hwnd = self.host_hwnd()
        if parent_hwnd <= 0 or self._launch_parent_hwnd <= 0:
            return False, "CDMW did not create a native Mesh Editor host window"
        if int(embedded_parent_hwnd) != int(self._launch_parent_hwnd):
            return False, "Preview reported a stale or mismatched embedded parent window"
        if int(child_hwnd) <= 0 or int(process_id) <= 0:
            return False, "Preview did not report a valid child window or process"
        try:
            user32 = _windows_api()
            child = wintypes.HWND(int(child_hwnd))
            if not user32.IsWindow(child):
                return False, "Preview reported a window that no longer exists"
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(child, ctypes.byref(owner))
            if int(owner.value) != int(process_id):
                return False, "Preview child window is not owned by the launched process"
            self._child_hwnd = int(child_hwnd)
            self._child_process_id = int(process_id)
            if not self._reparent_child():
                self.detach_child_window()
                return False, "Preview child window could not be attached to CDMW"
        except (AttributeError, OSError, TypeError, ValueError) as exc:
            self.detach_child_window()
            return False, f"Preview child-window validation failed: {exc}"
        self.show_editor()
        return True, ""

    def _reparent_child(self) -> bool:
        if sys.platform != "win32" or self._child_hwnd <= 0:
            return False
        parent_hwnd = self.host_hwnd()
        if parent_hwnd <= 0:
            return False
        user32 = _windows_api()
        child = wintypes.HWND(self._child_hwnd)
        if not user32.IsWindow(child):
            self._child_hwnd = 0
            return False
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(child, ctypes.byref(owner))
        if int(owner.value) != self._child_process_id:
            self._child_hwnd = 0
            return False
        user32.SetParent(child, wintypes.HWND(parent_hwnd))
        if int(user32.GetParent(child) or 0) != parent_hwnd:
            return False
        style = int(user32.GetWindowLongPtrW(child, _GWL_STYLE))
        user32.SetWindowLongPtrW(
            child,
            _GWL_STYLE,
            ctypes.c_ssize_t((style | _WS_CHILD) & ~_WS_POPUP),
        )
        self._sync_child_geometry(force_frame_refresh=True)
        return True

    def _sync_child_geometry(self, *, force_frame_refresh: bool = False) -> None:
        if sys.platform != "win32" or self._child_hwnd <= 0:
            return
        try:
            user32 = _windows_api()
            parent = wintypes.HWND(self.host_hwnd())
            child = wintypes.HWND(self._child_hwnd)
            if not user32.IsWindow(child):
                self._child_hwnd = 0
                return
            rect = wintypes.RECT()
            if not user32.GetClientRect(parent, ctypes.byref(rect)):
                return
            width = max(0, int(rect.right - rect.left))
            height = max(0, int(rect.bottom - rect.top))
            if width <= 0 or height <= 0:
                return
            flags = _SWP_NOZORDER | _SWP_NOACTIVATE | _SWP_NOOWNERZORDER
            if force_frame_refresh:
                flags |= _SWP_FRAMECHANGED
            user32.SetWindowPos(child, None, 0, 0, width, height, flags)
        except (AttributeError, OSError, TypeError, ValueError):
            return

    def _set_child_visible(self, visible: bool) -> None:
        if sys.platform != "win32" or self._child_hwnd <= 0:
            return
        try:
            user32 = _windows_api()
            child = wintypes.HWND(self._child_hwnd)
            if user32.IsWindow(child):
                user32.ShowWindow(child, _SW_SHOW if visible else _SW_HIDE)
        except (AttributeError, OSError, TypeError, ValueError):
            return

    def detach_child_window(self) -> None:
        self._set_child_visible(False)
        self._child_hwnd = 0
        self._child_process_id = 0
        self._editor_visible = False

    def show_loading(self, message: str) -> None:
        self._editor_visible = False
        self._set_child_visible(False)
        self._status_label.setText(str(message or "Preparing Mesh Editor..."))
        self._retry_button.setVisible(False)
        self._pages.setCurrentWidget(self._status_page)
        self._pages.setVisible(True)

    def show_error(self, message: str) -> None:
        self._editor_visible = False
        self._set_child_visible(False)
        self._status_label.setText(str(message or "Mesh Editor failed."))
        self._retry_button.setVisible(True)
        self._pages.setCurrentWidget(self._status_page)
        self._pages.setVisible(True)

    def show_editor(self) -> None:
        self._editor_visible = True
        self._pages.setVisible(False)
        self._sync_child_geometry(force_frame_refresh=True)
        self._set_child_visible(self.isVisible())

    def show_result(self, message: str) -> None:
        self._editor_visible = False
        self._set_child_visible(False)
        self._result_label.setText(str(message or "The validated mesh revision is ready for output."))
        self._pages.setCurrentWidget(self._result_page)
        self._pages.setVisible(True)

    def event(self, event: QEvent) -> bool:
        event_type = event.type()
        device_pixel_ratio_change = getattr(
            QEvent.Type,
            "DevicePixelRatioChange",
            None,
        )
        if event_type == QEvent.Type.WinIdChange and self._child_hwnd > 0:
            self._reparent_child()
        elif event_type in {
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.WindowStateChange,
            QEvent.Type.ScreenChangeInternal,
        } or (
            device_pixel_ratio_change is not None
            and event_type == device_pixel_ratio_change
        ):
            if self._editor_visible:
                self._sync_child_geometry(force_frame_refresh=event_type == QEvent.Type.Show)
                self._set_child_visible(self.isVisible())
        elif event_type == QEvent.Type.Hide:
            self._set_child_visible(False)
        elif event_type == QEvent.Type.FocusIn and self._child_hwnd > 0:
            try:
                _windows_api().SetFocus(wintypes.HWND(self._child_hwnd))
            except (AttributeError, OSError, TypeError, ValueError):
                pass
        return super().event(event)


__all__ = ["RustMeshEditorHostFrame"]
