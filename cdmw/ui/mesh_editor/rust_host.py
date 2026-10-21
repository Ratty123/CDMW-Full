"""Windows Qt host for the embedded Rust Mesh Editor child window."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedLayout,
    QStackedWidget,
    QVBoxLayout,
    QWhatsThis,
    QWidget,
)

from cdmw.ui.native_window_clipping import ensure_native_host_clipping
from cdmw.ui.shell.help_widgets import make_help_button


_GWL_STYLE = -16
_WS_CHILD = 0x40000000
_WS_POPUP = 0x80000000
_SW_HIDE = 0
_SW_SHOW = 5
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_FRAMECHANGED = 0x0020
_SWP_NOOWNERZORDER = 0x0200
_SWP_ASYNCWINDOWPOS = 0x4000


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
    user32.ShowWindowAsync.argtypes = [hwnd, ctypes.c_int]
    user32.ShowWindowAsync.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = [hwnd, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
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
    focus_requested = Signal()
    run_validation_requested = Signal()
    build_mod_requested = Signal()
    add_to_archive_browser_requested = Signal()
    continue_modified_mesh_requested = Signal()
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
        ensure_native_host_clipping(self)
        self.setObjectName("MeshEditorEmbeddedRustHost")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumSize(320, 240)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.controller = None  # Explicitly not a Vortice preview controller.
        self._theme_key = str(theme_key or "graphite")
        self.setProperty("cdmwThemeKey", self._theme_key)
        self._child_hwnd = 0
        self._child_process_id = 0
        self._launch_parent_hwnd = 0
        self._editor_visible = False
        self._focus_request_supported = False
        self._focus_timer = QTimer(self)
        self._focus_timer.setSingleShot(True)
        self._focus_timer.timeout.connect(self._request_child_focus)
        self._geometry_sync_timer = QTimer(self)
        self._geometry_sync_timer.setSingleShot(True)
        self._geometry_sync_timer.timeout.connect(self._sync_child_geometry_after_layout)

        root = QStackedLayout(self)
        root.setStackingMode(QStackedLayout.StackAll)
        root.setContentsMargins(0, 0, 0, 0)
        # A native child cannot paint over a sibling of its parent. Keep the
        # renderer in its own surface so the loading page also covers the window
        # it creates before reporting ready (while its GPU is initializing).
        self._surface = QFrame(self)
        self._surface.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self._surface.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self._surface.installEventFilter(self)
        root.addWidget(self._surface)
        self._pages = QStackedWidget(self)
        self._pages.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self._pages.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self._pages.setObjectName("MeshEditorRustHostPages")
        root.addWidget(self._pages)
        root.setCurrentWidget(self._pages)

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
        result_outer = QVBoxLayout(self._result_page)
        result_outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self._result_page)
        scroll.setObjectName("MeshEditorRustResultScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget(scroll)
        result_layout = QVBoxLayout(content)
        result_layout.setContentsMargins(8, 20, 8, 20)
        result_layout.addStretch(1)
        title = QLabel("Mesh edits accepted", content)
        title.setObjectName("MeshEditorRustResultTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        result_layout.addWidget(title)
        self._result_label = QLabel("", content)
        self._result_label.setObjectName("MeshEditorRustResultSummary")
        self._result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._result_label.setWordWrap(True)
        result_layout.addWidget(self._result_label)
        action_specs = (
                ("Keep editing", "ReopenEdit", "Resume current edit", self.reopen_edit_requested,
                 "Reopen the accepted mesh in the current session, keeping its fitting setup, parts and output choices. The original source stays the reference. Undo/Redo starts again when the editor reopens."),
                ("Keep editing", "Continueeditingmodifiedmesh", "Start next edit pass", self.continue_modified_mesh_requested,
                 "Rebuild the finished mesh and start a fresh editing pass from it. Your geometry changes, colours and textures carry over. Undo/Redo history and fitting setup start fresh. This is useful after baking a fit, before removing parts or mesh islands."),
                ("Save and reuse", "BuildMod", "Build Mod...", self.build_mod_requested,
                 "Create a mod package for your chosen mod manager. Choose the mod name, output folder and package format in the next window."),
                ("Save and reuse", "AddtoArchiveBrowser", "Add to Archive Browser", self.add_to_archive_browser_requested,
                 "Add the finished mesh to Archive Browser > Controls > Edited results. Open it there for a fresh editing pass, or choose another mesh from a combined Refit result. Results stay available until you close CDMW. This does not install a mod or change your game archives."),
                ("Check or install", "RunValidation", "Check mesh", self.run_validation_requested,
                 "Check whether this mesh can be rebuilt in its output format. Finish Edit Mesh already checks the accepted edit; use this to run that check again. A passed check does not verify appearance in the game."),
                ("Check or install", "InstallasOverlay", "Install to game...", self.install_overlay_requested,
                 "Install this mesh directly through CDMW's overlay workflow. Close Crimson Desert first. The next step shows what will change and asks for confirmation before installation. Use Build Mod if you want a package for a mod manager."),
                ("", "CloseSession", "Close this mesh", self.close_session_requested,
                 "Close the current mesh editing session. Build a mod or add the finished mesh to Archive Browser first if you want to keep using the result."),
        )
        current_heading = None
        for heading, action_id, text, signal, description in action_specs:
            if heading != current_heading:
                current_heading = heading
                group = QGroupBox(heading, content) if heading else QWidget(content)
                if heading:
                    group.setObjectName("MeshEditorRustResultGroup" + "".join(heading.split()))
                layout = QVBoxLayout(group)
                layout.setContentsMargins(6, 6, 6, 6)
                if heading == "Keep editing":
                    hint = QLabel("Resume keeps your fitting setup. A new pass starts from the finished mesh.", group)
                    hint.setWordWrap(True)
                    layout.addWidget(hint)
                result_layout.addWidget(group)
            row = QHBoxLayout()
            button = QPushButton(text, group)
            # Keep existing lookup keys independent of the clearer labels.
            button.setObjectName("MeshEditorRustResult" + action_id)
            button.setMinimumHeight(34)
            button.setToolTip(description)
            button.setWhatsThis(description)
            button.clicked.connect(signal.emit)
            row.addWidget(button, 1)
            help_button = make_help_button(description)
            help_button.setObjectName(button.objectName() + "Help")
            help_button.setAccessibleName("Help: " + text)
            help_button.setWhatsThis(description)
            help_button.clicked.connect(
                lambda _checked=False, target=help_button: QWhatsThis.showText(
                    target.mapToGlobal(target.rect().bottomRight()), target.whatsThis(), target,
                )
            )
            row.addWidget(help_button)
            layout.addLayout(row)
        result_layout.addStretch(1)
        scroll.setWidget(content)
        result_outer.addWidget(scroll)
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
            ensure_native_host_clipping(self)
            return max(0, int(self._surface.winId()))
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
        *,
        reveal: bool = True,
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
        if reveal:
            self.show_editor()
        else:
            # Windows does not paint a hidden child. Let it render underneath
            # a native loading page, which can cover an embedded native window.
            self._editor_visible = True
            self._set_child_visible(self.isVisible())
            self._pages.raise_()
        return True, ""

    def request_first_frame(self) -> None:
        """Request an asynchronous paint while the loading page covers the child."""
        if sys.platform == "win32" and self._child_hwnd > 0:
            _windows_api().PostMessageW(wintypes.HWND(self._child_hwnd), 0x000F, 0, 0)

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
        if int(user32.GetParent(child) or 0) != parent_hwnd:
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
            flags = _SWP_NOZORDER | _SWP_NOACTIVATE | _SWP_NOOWNERZORDER | _SWP_ASYNCWINDOWPOS
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
                # The renderer may have stopped pumping its window queue. A
                # synchronous hide would block Qt before its kill timer runs.
                user32.ShowWindowAsync(child, _SW_SHOW if visible else _SW_HIDE)
        except (AttributeError, OSError, TypeError, ValueError):
            return

    def _sync_child_geometry_after_layout(self) -> None:
        if self._editor_visible and self.isVisible():
            self._sync_child_geometry()

    def detach_child_window(self) -> None:
        self._focus_timer.stop()
        self._focus_request_supported = False
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

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched is self._surface and event.type() == QEvent.Type.WinIdChange and self._child_hwnd > 0:
            self._reparent_child()
        return super().eventFilter(watched, event)

    def event(self, event: QEvent) -> bool:
        event_type = event.type()
        if event_type == QEvent.Type.Show:
            ensure_native_host_clipping(self)
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
                # Qt can deliver Show/Resize before resizing the native parent,
                # especially when a prewarmed hidden tab first becomes visible.
                # Coalesce a second sync after that native layout has settled.
                self._geometry_sync_timer.start(0)
        elif event_type == QEvent.Type.Hide:
            self._focus_timer.stop()
            self._geometry_sync_timer.stop()
            self._set_child_visible(False)
        elif event_type == QEvent.Type.FocusIn and self._editor_visible and self._child_hwnd > 0:
            self._focus_timer.start(0)
        elif event_type == QEvent.Type.FocusOut:
            self._focus_timer.stop()
        return super().event(event)

    def _request_child_focus(self) -> None:
        if self._focus_request_supported and self._editor_visible and self.isVisible() and self.hasFocus():
            self.focus_requested.emit()


__all__ = ["RustMeshEditorHostFrame"]
