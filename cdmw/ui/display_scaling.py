"""Font-safe controls and reachable content on small logical desktop work areas.

Qt already converts device pixels to logical pixels. Keep the user's font and
use layout hints for content; scroll only when a workspace cannot shrink further.
"""

from __future__ import annotations

import weakref

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractSpinBox, QApplication, QComboBox, QFrame,
    QLabel, QLayout, QLineEdit, QMainWindow, QPushButton, QScrollArea, QSizePolicy,
    QStackedWidget, QStyle, QStyleOptionButton, QStyleOptionToolButton,
    QToolButton, QVBoxLayout, QWidget,
)
from shiboken6 import isValid


def protect_control_text(widget: QWidget) -> None:
    """Remove pixel caps that are smaller than the current styled text hint."""
    text_button = isinstance(widget, QAbstractButton) and bool(widget.text())
    if isinstance(widget, QToolButton) and widget.toolButtonStyle() == Qt.ToolButtonIconOnly:
        text_button = False
    if text_button or isinstance(widget, (QComboBox, QLineEdit, QAbstractSpinBox)):
        current = (widget.minimumWidth(), widget.minimumHeight(), widget.maximumWidth(), widget.maximumHeight())
        previous = getattr(widget, "_display_text_limits", None)
        base = list(current if previous is None else previous[0])
        if previous is not None:
            for index, value in enumerate(current):
                if value != previous[1][index]:
                    base[index] = value  # An owning feature changed its constraint.
        hint = widget.sizeHint()
        height = max(base[1], hint.height(), widget.fontMetrics().height() + 12)
        width = base[0]
        if text_button:
            text_width = widget.fontMetrics().size(Qt.TextShowMnemonic, widget.text()).width()
            if not widget.icon().isNull():
                text_width += widget.iconSize().width() + 6
            padding = 12
            if isinstance(widget, QPushButton):
                option = QStyleOptionButton()
                widget.initStyleOption(option)
                contents = widget.style().subElementRect(QStyle.SE_PushButtonContents, option, widget)
                padding = max(padding, widget.width() - contents.width())
                if widget.menu() is not None:
                    padding += widget.style().pixelMetric(QStyle.PM_MenuButtonIndicator, option, widget)
            elif isinstance(widget, QToolButton):
                option = QStyleOptionToolButton()
                widget.initStyleOption(option)
                if widget.menu() is not None:
                    padding += widget.style().pixelMetric(QStyle.PM_MenuButtonIndicator, option, widget)
            width = max(width, hint.width(), text_width + padding)
        desired = (width, height, max(base[2], width), max(base[3], height))
        if current != desired:
            widget.setMaximumSize(desired[2], desired[3])
            widget.setMinimumSize(desired[0], desired[1])
        widget._display_text_limits = (tuple(base), desired)
    elif isinstance(widget, QLabel) and widget.text() and not widget.wordWrap():
        height = widget.fontMetrics().height() + 2 * widget.margin()
        if widget.maximumHeight() < height:
            widget.setMaximumHeight(height)
            widget.setMinimumHeight(height)


class CurrentToolStack(QStackedWidget):
    """Inactive tools must not impose their minimum size on the active tool."""

    def minimumSizeHint(self) -> QSize:
        current = self.currentWidget()
        return current.minimumSizeHint().expandedTo(current.minimumSize()) if current else QSize(0, 0)

    def sizeHint(self) -> QSize:
        current = self.currentWidget()
        return current.sizeHint() if current else QSize(0, 0)


def scrollable_content(content: QWidget, parent: QWidget | None = None) -> QScrollArea:
    scroll = QScrollArea(parent)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidgetResizable(True)
    scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    scroll.setWidget(content)
    return scroll


def _normal_window(widget: QWidget) -> bool:
    return widget.isWindow() and widget.windowType() in (Qt.Window, Qt.Dialog, Qt.Tool)


def fit_window_to_screen(window: QWidget, available: QRect | None = None) -> None:
    """Keep the full frame on screen without discarding oversized dialog content.

    Overflow wrapping is permanent once needed. The central widget, layout, and
    nested preview parents retain their identities across subsequent resizes.
    """
    if not _normal_window(window) or window.isMinimized():
        return
    screen = window.screen() or QApplication.primaryScreen()
    if available is None:
        if screen is None:
            return
        available = screen.availableGeometry()
    bounds = available.adjusted(8, 8, -8, -8)
    frame = window.frameGeometry()
    decoration = frame.size() - window.size()
    limit = QSize(max(1, bounds.width() - max(0, decoration.width())),
                  max(1, bounds.height() - max(0, decoration.height())))
    root = window.centralWidget() if isinstance(window, QMainWindow) else window
    if root is not None and root.layout() is not None:
        required = window.minimumSizeHint().expandedTo(window.minimumSize())
        if required.width() > limit.width() or required.height() > limit.height():
            if "_display_overflow_scroll" not in root.__dict__:
                layout = root.layout()
                body = QWidget()
                body.setMinimumSize(root.minimumSize())
                # Qt transfers the layout with its existing child widgets once.
                body.setLayout(layout)
                outer = QVBoxLayout(root)
                outer.setContentsMargins(0, 0, 0, 0)
                outer.setSpacing(0)
                outer.setSizeConstraint(QLayout.SetNoConstraint)
                scroll = scrollable_content(body, root)
                outer.addWidget(scroll)
                root._display_overflow_scroll = scroll
            root.setMinimumSize(0, 0)
            window.setMinimumSize(0, 0)
            root.layout().activate()
    if not window.isMaximized() and not window.isFullScreen():
        window.resize(window.size().boundedTo(limit))
        frame = window.frameGeometry()
        x = min(max(frame.x(), bounds.left()), max(bounds.left(), bounds.right() - frame.width() + 1))
        y = min(max(frame.y(), bounds.top()), max(bounds.top(), bounds.bottom() - frame.height() + 1))
        window.move(x, y)


class DisplayScalingPolicy(QObject):
    """One application filter also covers late-created tools and owned dialogs."""

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._controls: weakref.WeakSet[QWidget] = weakref.WeakSet()
        self._windows: weakref.WeakSet[QWidget] = weakref.WeakSet()
        self._connected: weakref.WeakSet[QWidget] = weakref.WeakSet()
        self._busy = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._apply_pending)
        for screen in app.screens():
            self._connect_screen(screen)
        app.screenAdded.connect(self._connect_screen)

    def _connect_screen(self, screen: object) -> None:
        screen.availableGeometryChanged.connect(self._refresh_windows)
        screen.logicalDotsPerInchChanged.connect(self._refresh_windows)
        screen.geometryChanged.connect(self._refresh_windows)

    def _refresh_windows(self, *_args: object) -> None:
        for window in QApplication.topLevelWidgets():
            if _normal_window(window) and window.isVisible():
                self._windows.add(window)
        self._schedule()

    def _schedule(self) -> None:
        # Restarting a zero timer for every layout/paint can starve it during
        # lazy construction and translation of a large widget tree.
        if not self._timer.isActive():
            self._timer.start(0)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # Some existing UI visitors pass layout items, which are not QObjects.
        if self._busy or not isinstance(watched, QWidget) or not isValid(watched):
            return False
        kind = event.type()
        if kind in (QEvent.Polish, QEvent.Show, QEvent.FontChange, QEvent.StyleChange) or (
            kind == QEvent.Paint and isinstance(watched, QAbstractButton)
        ):
            self._controls.add(watched)
            self._schedule()
        elif kind == QEvent.LayoutRequest:
            for child in watched.children():
                if isinstance(child, (QAbstractButton, QComboBox, QLineEdit, QAbstractSpinBox, QLabel)):
                    self._controls.add(child)
            self._schedule()
        if _normal_window(watched) and kind in (
            QEvent.Show, QEvent.Resize, QEvent.LayoutRequest, QEvent.WindowStateChange,
            QEvent.ScreenChangeInternal, QEvent.DevicePixelRatioChange,
        ):
            self._windows.add(watched)
            self._schedule()
        return False

    def _apply_pending(self) -> None:
        controls, windows = tuple(self._controls), tuple(self._windows)
        self._controls.clear()
        self._windows.clear()
        self._busy = True
        try:
            for widget in controls:
                if isValid(widget):
                    protect_control_text(widget)
            for window in windows:
                if not isValid(window) or not window.isVisible():
                    continue
                handle = window.windowHandle()
                if handle is not None and window not in self._connected:
                    handle.screenChanged.connect(self._refresh_windows)
                    self._connected.add(window)
                fit_window_to_screen(window)
        finally:
            self._busy = False


def ensure_app_display_scaling(app: QApplication | None = None) -> DisplayScalingPolicy | None:
    app = app or QApplication.instance()
    if app is None:
        return None
    policy = getattr(app, "_cdmw_display_scaling", None)
    if policy is None:
        policy = DisplayScalingPolicy(app)
        app._cdmw_display_scaling = policy
        app.installEventFilter(policy)
    return policy
