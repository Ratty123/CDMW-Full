"""Keep native hosts clipped while their layout ancestors stay non-native."""

from __future__ import annotations

import weakref

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QTimer
from PySide6.QtGui import QRegion, QWindow
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid


class _NativeHostClipObserver(QObject):
    """Refresh native clipping and position after ancestor layout changes."""

    def __init__(self, widget: QWidget) -> None:
        super().__init__(widget)
        self._widget = weakref.ref(widget)
        self._watched: weakref.WeakSet[QWidget] = weakref.WeakSet()
        self._base_mask = QRegion(widget.mask())
        self._applied_mask = QRegion(widget.mask())
        self._native_mask_dirty = True
        self._refreshing = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if kind in (
            QEvent.Type.WinIdChange, QEvent.Type.ScreenChangeInternal,
            QEvent.Type.DevicePixelRatioChange,
        ):
            self._native_mask_dirty = True
        if kind in (
            QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.Resize,
            QEvent.Type.Move, QEvent.Type.ParentChange, QEvent.Type.LayoutRequest,
            QEvent.Type.WinIdChange, QEvent.Type.ScreenChangeInternal,
            QEvent.Type.DevicePixelRatioChange,
        ) and not self._timer.isActive():
            # Use final ancestor positions after Qt has finished the layout.
            self._timer.start(0)
        return False

    def _apply_mask(self, widget: QWidget, handle: QWindow | None, mask: QRegion) -> None:
        if widget.mask() != mask:
            if mask.isEmpty():
                widget.clearMask()
            else:
                widget.setMask(mask)
        if handle is not None and self._native_mask_dirty:
            # QWindow reapplies the region in the current native pixel scale.
            handle.setMask(mask)
            self._native_mask_dirty = False

    def refresh(self) -> None:
        widget = self._widget()
        if widget is None or not isValid(widget) or self._refreshing:
            return
        self._timer.stop()
        self._refreshing = True
        try:
            current_mask = widget.mask()
            if current_mask != self._applied_mask:
                self._base_mask = QRegion(current_mask)
            watched = {widget}
            visible = widget.rect()
            ancestor = None if widget.isWindow() else widget.parentWidget()
            while ancestor is not None and not ancestor.isWindow():
                watched.add(ancestor)
                offset = widget.mapTo(ancestor, QPoint())
                visible = visible.intersected(ancestor.rect().translated(-offset))
                ancestor = ancestor.parentWidget()
            for previous in tuple(self._watched):
                if previous not in watched and isValid(previous):
                    previous.removeEventFilter(self)
            for current in watched:
                if current not in self._watched:
                    current.installEventFilter(self)
            self._watched = weakref.WeakSet(watched)

            desired_mask = QRegion(self._base_mask)
            if visible != widget.rect():
                desired_mask = QRegion(visible)
                if not self._base_mask.isEmpty():
                    desired_mask &= self._base_mask
                if desired_mask.isEmpty():
                    # An empty mask means "unmasked" to Qt. This nonempty region
                    # lies outside the host, so a fully scrolled-out host and its
                    # native children stay clipped without hiding/recreating them.
                    desired_mask = QRegion(QRect(-1, -1, 1, 1))

            handle = widget.windowHandle()
            native_parent = widget.nativeParentWidget() if not widget.isWindow() else None
            if (handle is not None and native_parent is not None
                    and handle.parent() == native_parent.windowHandle()):
                # Moving alien scroll content does not reliably move its native
                # descendants on Windows. Update only this Qt host's position in
                # its existing native parent's logical coordinate system.
                position = widget.mapTo(native_parent, QPoint())
                if handle.position() != position:
                    if current_mask != desired_mask:
                        # Keep both positions clipped while the HWND moves.
                        # A fully clipped host stays masked until it returns.
                        previous = QRegion(widget.rect()) if current_mask.isEmpty() else current_mask
                        following = QRegion(widget.rect()) if desired_mask.isEmpty() else desired_mask
                        transition = previous & following
                        if transition.isEmpty():
                            transition = QRegion(QRect(-1, -1, 1, 1))
                        self._apply_mask(widget, handle, transition)
                    handle.setPosition(position)
            self._apply_mask(widget, handle, desired_mask)
            self._applied_mask = QRegion(desired_mask)
        finally:
            self._refreshing = False


def ensure_native_host_clipping(widget: QWidget) -> None:
    """Preserve host ownership, clipping and position without native ancestors.

    The observer follows ordinary and scrolling parents, including later
    reparenting, overflow and DPI changes. Native-handle requests refresh
    synchronously before embedding; layout changes refresh after Qt settles.
    Existing host masks are intersected with ancestor bounds and restored when
    clipping is no longer needed. Renderer child sizing remains with its owner.
    """
    observer = getattr(widget, "_cdmw_native_host_clip_observer", None)
    if observer is None:
        if widget.isWindow():
            return
        observer = _NativeHostClipObserver(widget)
        widget._cdmw_native_host_clip_observer = observer
    observer.refresh()
