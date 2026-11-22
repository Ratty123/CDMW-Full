"""Font-safe controls and reachable content on small logical desktop work areas.

Qt already converts device pixels to logical pixels. Keep the user's font and
use layout hints for content; scroll only when a workspace cannot shrink further.
"""

from __future__ import annotations

import math
import sys
import weakref
from time import monotonic

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QRegion, QWindow
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractSpinBox, QApplication, QComboBox, QDockWidget, QFrame,
    QLabel, QLayout, QLineEdit, QMainWindow, QPushButton, QScrollArea, QSizePolicy,
    QStackedWidget, QStyle, QStyleOptionButton, QStyleOptionToolButton,
    QToolButton, QVBoxLayout, QWidget,
)
from shiboken6 import isValid

from cdmw.ui.window_interaction import ensure_window_interaction_tracker
from cdmw.ui.app_event_hub import install_app_event_filter


def _button_fast_key(widget: QAbstractButton, text: str) -> tuple:
    return (text, widget.minimumWidth(), widget.minimumHeight(), widget.maximumWidth(), widget.maximumHeight())


def _button_signature(widget: QAbstractButton, text: str) -> tuple:
    return (
        text,
        widget.font().key(),
        widget.icon().cacheKey(),
        widget.menu() is not None if isinstance(widget, (QPushButton, QToolButton)) else False,
        widget.minimumWidth(),
        widget.minimumHeight(),
        widget.maximumWidth(),
        widget.maximumHeight(),
    )


def protect_control_text(widget: QWidget) -> None:
    """Remove pixel caps that are smaller than the current styled text hint."""
    is_button = isinstance(widget, QAbstractButton)
    button_text = widget.text() if is_button else ""
    text_button = is_button and bool(button_text)
    if text_button and isinstance(widget, QToolButton) and widget.toolButtonStyle() == Qt.ToolButtonIconOnly:
        text_button = False
    if text_button or isinstance(widget, (QComboBox, QLineEdit, QAbstractSpinBox)):
        current = (widget.minimumWidth(), widget.minimumHeight(), widget.maximumWidth(), widget.maximumHeight())
        if text_button:
            sig = _button_signature(widget, button_text)
            if getattr(widget, "_display_text_sig", None) == sig:
                widget._display_text_fast = _button_fast_key(widget, button_text)
                return
        else:
            sig = (widget.font().key(), current)
            if getattr(widget, "_display_text_sig", None) == sig:
                widget._display_text_fast = current
                return
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
            text_width = widget.fontMetrics().size(Qt.TextShowMnemonic, button_text).width()
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
        if text_button:
            widget._display_text_sig = _button_signature(widget, button_text)
            widget._display_text_fast = _button_fast_key(widget, button_text)
        else:
            widget._display_text_sig = (widget.font().key(), desired)
            widget._display_text_fast = desired
    elif isinstance(widget, QLabel) and widget.text() and not widget.wordWrap():
        fast = (widget.minimumHeight(), widget.maximumHeight())
        sig = (widget.font().key(), widget.margin(), fast[0], fast[1])
        if getattr(widget, "_display_text_sig", None) == sig:
            widget._display_text_fast = fast
            return
        height = widget.fontMetrics().height() + 2 * widget.margin()
        if widget.maximumHeight() < height:
            widget.setMaximumHeight(height)
            widget.setMinimumHeight(height)
        fast = (widget.minimumHeight(), widget.maximumHeight())
        widget._display_text_sig = (widget.font().key(), widget.margin(), fast[0], fast[1])
        widget._display_text_fast = fast


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
    return (widget.isWindow() and widget.windowType() in (Qt.Window, Qt.Dialog, Qt.Tool)
            and not widget.testAttribute(Qt.WA_DontShowOnScreen))


def _available_screen_rects() -> tuple[QRect, ...]:
    return tuple(screen.availableGeometry() for screen in QApplication.screens())


def _window_is_reachable(window: QWidget, work_areas: tuple[QRect, ...]) -> bool:
    """Allow useful partial visibility and windows spanning actual work areas.

    An ordinary-size window only needs a draggable caption and usable content
    to stay where the user put it. A window larger than any individual screen
    must also have its content covered by the desktop, with a small allowance
    for outer clipping. A gap between monitors is never treated as a screen.
    """
    frame = window.frameGeometry()
    client = window.geometry()
    caption_height = max(24, client.top() - frame.top())
    caption = QRect(frame.left(), frame.top(), frame.width(), min(frame.height(), caption_height))
    caption_reachable = any(
        (visible := caption.intersected(area)).width() >= min(160, caption.width())
        and visible.height() >= min(20, caption.height())
        for area in work_areas
    )
    content_reachable = any(
        (visible := client.intersected(area)).width() >= min(160, client.width())
        and visible.height() >= min(96, client.height())
        for area in work_areas
    )
    if not caption_reachable or not content_reachable:
        return False
    if any(frame.width() <= area.width() and frame.height() <= area.height() for area in work_areas):
        return True
    if len(work_areas) <= 1:
        return False
    desktop = QRegion()
    for area in work_areas:
        desktop |= QRegion(area)
    # Keep a large, useful spanning window even when its outer edge is slightly
    # clipped. Subtraction tests full coverage; QRegion.contains(QRect) only
    # tests overlap and a bounding rectangle would incorrectly fill screen gaps.
    inset_x, inset_y = min(48, client.width() // 4), min(48, client.height() // 4)
    content = client.adjusted(inset_x, inset_y, -inset_x, -inset_y)
    return QRegion(content).subtracted(desktop).isEmpty()


def fit_window_to_screen(window: QWidget, available: QRect | None = None) -> None:
    """Recover inaccessible windows without disturbing useful manual placement.

    Overflow wrapping is permanent once needed. The central widget, layout, and
    nested preview parents retain their identities across subsequent resizes.
    An explicit work area requests the existing bounded single-screen fit.
    """
    if (not isValid(window) or not _normal_window(window) or window.isMinimized()
            or ensure_window_interaction_tracker().is_active(window)):
        return
    screen = window.screen() or QApplication.primaryScreen()
    if available is None:
        if screen is None:
            return
        if (not window.isMaximized() and not window.isFullScreen()
                and _window_is_reachable(window, _available_screen_rects())):
            return
        available = screen.availableGeometry()
    bounds = available.adjusted(8, 8, -8, -8)
    frame = window.frameGeometry()
    decoration = frame.size() - window.size()
    limit = QSize(max(1, bounds.width() - max(0, decoration.width())),
                  max(1, bounds.height() - max(0, decoration.height())))
    # Main windows and docks own internal layouts tied to their widget type.
    # Only their content's layout can move into the overflow scroll area.
    if isinstance(window, QMainWindow):
        root = window.centralWidget()
    elif isinstance(window, QDockWidget):
        root = window.widget()
    else:
        root = window
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
        desired_size = window.size().boundedTo(limit)
        if window.size() != desired_size:
            window.resize(desired_size)
        frame = window.frameGeometry()
        x = min(max(frame.x(), bounds.left()), max(bounds.left(), bounds.right() - frame.width() + 1))
        y = min(max(frame.y(), bounds.top()), max(bounds.top(), bounds.bottom() - frame.height() + 1))
        if frame.x() != x or frame.y() != y:
            window.move(x, y)


class DisplayScalingPolicy(QObject):
    """One application filter also covers late-created tools and owned dialogs."""

    _FIT_DELAY_MS = 120

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._controls: weakref.WeakSet[QWidget] = weakref.WeakSet()
        self._windows: weakref.WeakKeyDictionary[QWidget, float | None] = weakref.WeakKeyDictionary()
        self._last_fit: weakref.WeakKeyDictionary[QWidget, tuple] = weakref.WeakKeyDictionary()
        self._connected: weakref.WeakSet[QWidget] = weakref.WeakSet()
        self._busy = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._apply_pending)
        self._window_timer = QTimer(self)
        self._window_timer.setSingleShot(True)
        self._window_timer.setInterval(self._FIT_DELAY_MS)
        self._window_timer.timeout.connect(self._fit_pending_windows)
        self._interaction = ensure_window_interaction_tracker(app)
        self._interaction.started.connect(self._window_interaction_started)
        self._interaction.finished.connect(self._window_interaction_finished)
        for screen in app.screens():
            self._connect_screen(screen)
        app.screenAdded.connect(self._connect_screen)
        app.screenRemoved.connect(self._refresh_windows)

    def _connect_screen(self, screen: object) -> None:
        screen.availableGeometryChanged.connect(self._refresh_windows)
        screen.logicalDotsPerInchChanged.connect(self._refresh_windows)
        screen.geometryChanged.connect(self._refresh_windows)

    def _refresh_windows(self, *_args: object) -> None:
        for window in QApplication.topLevelWidgets():
            if _normal_window(window) and window.isVisible():
                self.schedule_window_fit(window)

    def schedule_window_fit(self, window: QWidget) -> None:
        """Coalesce fitting per window, including requests from shell callers."""
        if not isValid(window) or not _normal_window(window):
            return
        handle = window.windowHandle()
        # While a large window is built, PySide can return a stale wrapper of another
        # type (a QWidgetItem) for a reused address; connect on a later event instead.
        if isinstance(handle, QWindow) and window not in self._connected:
            handle.screenChanged.connect(self._window_screen_changed)
            self._connected.add(window)
        self._windows[window] = (
            None if self._interaction.is_active(window)
            else monotonic() + self._FIT_DELAY_MS / 1000.0
        )
        self._arm_window_timer()

    def _window_screen_changed(self, *_args: object) -> None:
        handle = self.sender()
        for window in tuple(self._connected):
            if isValid(window) and window.windowHandle() is handle:
                self.schedule_window_fit(window)
                break

    def _window_interaction_started(self, window: QWidget) -> None:
        if isValid(window) and _normal_window(window):
            self._windows[window] = None
            self._arm_window_timer()

    def _window_interaction_finished(self, window: QWidget) -> None:
        if isValid(window) and window.isVisible():
            self.schedule_window_fit(window)

    def _arm_window_timer(self) -> None:
        deadlines = []
        for window, deadline in tuple(self._windows.items()):
            if not isValid(window) or not window.isVisible() or not _normal_window(window):
                self._windows.pop(window, None)
            elif self._interaction.is_active(window):
                self._windows[window] = None
            elif deadline is not None:
                deadlines.append(deadline)
        if deadlines:
            delay_ms = max(1, math.ceil((min(deadlines) - monotonic()) * 1000))
            self._window_timer.start(delay_ms)
        else:
            # Native holds have no timeout. Pausing with the mouse held must not
            # run fitting, and a held window must not starve another window.
            self._window_timer.stop()

    @staticmethod
    def _fit_signature(window: QWidget) -> tuple:
        return (
            window.frameGeometry().getRect(), window.minimumSize(), window.minimumSizeHint(),
            window.windowState(), window.devicePixelRatioF(),
            tuple(area.getRect() for area in _available_screen_rects()),
        )

    def _schedule(self) -> None:
        # Restarting a zero timer for every layout/paint can starve it during
        # lazy construction and translation of a large widget tree.
        if not self._timer.isActive():
            self._timer.start(0)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if self._busy:
            return False
        kind = event.type()
        if kind == QEvent.Paint:
            if not isinstance(watched, QAbstractButton) or not isValid(watched):
                return False
            text = watched.text()
            if not text:
                return False
            if isinstance(watched, QToolButton) and watched.toolButtonStyle() == Qt.ToolButtonIconOnly:
                return False
            if getattr(watched, "_display_text_fast", None) == _button_fast_key(watched, text):
                return False
            self._controls.add(watched)
            self._schedule()
            return False
        if kind in (QEvent.Move, QEvent.Resize, QEvent.WindowStateChange, QEvent.ScreenChangeInternal, QEvent.DevicePixelRatioChange):
            if isinstance(watched, QWidget) and watched.isWindow() and isValid(watched) and _normal_window(watched):
                self.schedule_window_fit(watched)
            return False
        if kind == QEvent.Hide:
            if isinstance(watched, QWidget) and watched.isWindow() and isValid(watched) and _normal_window(watched):
                self._windows.pop(watched, None)
                self._last_fit.pop(watched, None)
                self._arm_window_timer()
            return False
        # Some existing UI visitors pass layout items, which are not QObjects.
        if not isinstance(watched, QWidget) or not isValid(watched):
            return False
        if kind in (QEvent.Polish, QEvent.FontChange, QEvent.StyleChange):
            if isinstance(watched, (QAbstractButton, QComboBox, QLineEdit, QAbstractSpinBox, QLabel)):
                watched._display_text_sig = None
                watched._display_text_fast = None
                self._controls.add(watched)
                self._schedule()
        elif kind == QEvent.Show:
            if isinstance(watched, (QAbstractButton, QComboBox, QLineEdit, QAbstractSpinBox, QLabel)):
                self._controls.add(watched)
                self._schedule()
            if watched.isWindow() and _normal_window(watched):
                self.schedule_window_fit(watched)
        elif kind == QEvent.LayoutRequest:
            added = False
            for child in watched.children():
                if isinstance(child, QAbstractButton):
                    text = child.text()
                    if not text or getattr(child, "_display_text_fast", None) == _button_fast_key(child, text):
                        continue
                    self._controls.add(child)
                    added = True
                elif isinstance(child, (QComboBox, QLineEdit, QAbstractSpinBox)):
                    fast = (child.minimumWidth(), child.minimumHeight(), child.maximumWidth(), child.maximumHeight())
                    if getattr(child, "_display_text_fast", None) == fast:
                        continue
                    self._controls.add(child)
                    added = True
                elif isinstance(child, QLabel):
                    if child.wordWrap() or not child.text():
                        continue
                    if getattr(child, "_display_text_fast", None) == (child.minimumHeight(), child.maximumHeight()):
                        continue
                    self._controls.add(child)
                    added = True
            if added:
                self._schedule()
            if watched.isWindow() and _normal_window(watched):
                self.schedule_window_fit(watched)
        return False

    def _apply_pending(self) -> None:
        controls = tuple(self._controls)
        self._controls.clear()
        self._busy = True
        try:
            for widget in controls:
                if isValid(widget):
                    protect_control_text(widget)
        finally:
            self._busy = False

    def _fit_pending_windows(self) -> None:
        now = monotonic()
        self._busy = True
        try:
            for window, deadline in tuple(self._windows.items()):
                if not isValid(window) or not window.isVisible() or not _normal_window(window):
                    self._windows.pop(window, None)
                    continue
                if self._interaction.is_active(window):
                    self._windows[window] = None
                    continue
                if deadline is None or deadline > now:
                    continue
                self._windows.pop(window, None)
                if self._last_fit.get(window) == self._fit_signature(window):
                    continue
                fit_window_to_screen(window)
                self._last_fit[window] = self._fit_signature(window)
        finally:
            self._busy = False
            self._arm_window_timer()


#: Every event type DisplayScalingPolicy.eventFilter acts on.
DISPLAY_SCALING_EVENT_TYPES = (
    QEvent.Polish, QEvent.Show, QEvent.FontChange, QEvent.StyleChange, QEvent.Paint,
    QEvent.LayoutRequest, QEvent.Move, QEvent.Resize, QEvent.WindowStateChange,
    QEvent.ScreenChangeInternal, QEvent.DevicePixelRatioChange, QEvent.Hide,
)


def ensure_app_display_scaling(app: QApplication | None = None) -> DisplayScalingPolicy | None:
    app = app or QApplication.instance()
    if app is None:
        return None
    if sys.platform == "win32":
        # Embedded native hosts must not promote ordinary sibling widgets to
        # HWNDs, which repeat Qt screen/DPR propagation during monitor moves.
        app.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
    policy = getattr(app, "_cdmw_display_scaling", None)
    if policy is None:
        policy = DisplayScalingPolicy(app)
        app._cdmw_display_scaling = policy
        install_app_event_filter(app, policy, DISPLAY_SCALING_EVENT_TYPES)
    return policy
