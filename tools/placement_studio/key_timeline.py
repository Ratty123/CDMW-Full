"""A key timeline for the Edit animation tab: see the keys, scrub, drag keys to retime them.

One lane per thing being keyed (the selected bone's pose keys, the selected hand or foot's
reach keys), seconds along the top, the playhead across everything, and a shaded band for
each joined animation with its fade drawn as a ramp. Clicking or dragging on empty space
scrubs; dragging a key moves it to another frame; right-clicking a key offers to remove it.

The widget only reports what the animator did (`seek_requested`, `key_moved`,
`key_removed`); the tab owns the edit and changes it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QMenu, QSizePolicy, QWidget

from cdmw.services.active_ui_translation import translate_active_ui_text

FPS = 30
_LABEL_WIDTH = 108
_RULER_HEIGHT = 18
_LANE_HEIGHT = 22
_HIT_PIXELS = 7


@dataclass(frozen=True)
class Lane:
    #: What the tab calls the lane back by, e.g. "pose" or "reach".
    key: str
    label: str
    frames: Tuple[int, ...] = ()
    #: Frames drawn filled: a pinned reach key.
    filled: Tuple[int, ...] = ()


@dataclass(frozen=True)
class Band:
    """A joined animation: where it starts, how long it fades in, where it ends (frames)."""

    start: float
    fade: float
    end: float
    label: str = ""


class KeyTimeline(QWidget):
    seek_requested = Signal(float)
    #: lane key, from frame, to frame
    key_moved = Signal(str, int, int)
    #: lane key, frame
    key_removed = Signal(str, int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._last_frame = 0
        self._playhead = 0.0
        self._lanes: List[Lane] = []
        self._bands: List[Band] = []
        self._drag: Optional[Tuple[str, int]] = None
        self._drag_to: Optional[int] = None
        self._scrubbing = False
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip(translate_active_ui_text(
            "Click or drag to move the playhead. Drag a key to move it to another moment; "
            "right-click a key to remove it."))

    # ── what to show ────────────────────────────────────────────────

    def set_length(self, last_frame: int) -> None:
        self._last_frame = max(0, int(last_frame))
        self.update()

    def set_playhead(self, frame: float) -> None:
        if abs(frame - self._playhead) > 1e-6:
            self._playhead = float(frame)
            self.update()

    def set_lanes(self, lanes: Iterable[Lane]) -> None:
        self._lanes = list(lanes)
        self.updateGeometry()
        self.update()

    def set_bands(self, bands: Iterable[Band]) -> None:
        self._bands = list(bands)
        self.update()

    def lanes(self) -> Sequence[Lane]:
        return tuple(self._lanes)

    def sizeHint(self) -> QSize:
        return QSize(420, _RULER_HEIGHT + _LANE_HEIGHT * max(1, len(self._lanes)) + 6)

    def minimumSizeHint(self) -> QSize:
        return QSize(200, self.sizeHint().height())

    # ── geometry ────────────────────────────────────────────────────

    def _track_rect(self) -> QRectF:
        return QRectF(_LABEL_WIDTH, 0, max(1.0, self.width() - _LABEL_WIDTH - 8), self.height())

    def x_of(self, frame: float) -> float:
        rect = self._track_rect()
        return rect.left() + rect.width() * min(1.0, max(0.0, frame / max(1, self._last_frame)))

    def frame_at(self, x: float) -> int:
        rect = self._track_rect()
        t = (x - rect.left()) / rect.width()
        return int(round(min(1.0, max(0.0, t)) * max(1, self._last_frame)))

    def _lane_at(self, y: float) -> Optional[int]:
        index = int((y - _RULER_HEIGHT) // _LANE_HEIGHT)
        return index if 0 <= index < len(self._lanes) else None

    def _lane_centre(self, index: int) -> float:
        return _RULER_HEIGHT + _LANE_HEIGHT * index + _LANE_HEIGHT / 2

    def key_at(self, point: QPointF) -> Optional[Tuple[str, int]]:
        """The key under `point`, as `(lane key, frame)`."""

        index = self._lane_at(point.y())
        if index is None:
            return None
        lane = self._lanes[index]
        best = None
        for frame in lane.frames:
            distance = abs(self.x_of(frame) - point.x())
            if distance <= _HIT_PIXELS and (best is None or distance < best[0]):
                best = (distance, frame)
        return (lane.key, best[1]) if best is not None else None

    # ── drawing ─────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        palette = self.palette()
        base = palette.base().color()
        text = palette.text().color()
        mid = palette.mid().color()
        accent = palette.highlight().color()
        painter.fillRect(self.rect(), base)
        rect = self._track_rect()

        # Joined animations: a band, its fade drawn as a ramp up to full height.
        for band in self._bands:
            left, fade, right = self.x_of(band.start), self.x_of(band.start + band.fade), self.x_of(band.end)
            shade = QColor(accent)
            shade.setAlpha(40)
            path = QPainterPath()
            path.moveTo(left, self.height())
            path.lineTo(fade, _RULER_HEIGHT)
            path.lineTo(right, _RULER_HEIGHT)
            path.lineTo(right, self.height())
            path.closeSubpath()
            painter.fillPath(path, shade)
            if band.label:
                painter.setPen(text)
                painter.drawText(QRectF(fade + 3, 1, max(0.0, right - fade - 6), _RULER_HEIGHT - 2),
                                 Qt.AlignLeft | Qt.AlignVCenter, band.label)

        # The ruler: a tick every second, labelled; finer ticks when there is room.
        painter.setPen(QPen(mid, 1))
        painter.drawLine(QPointF(rect.left(), _RULER_HEIGHT - 0.5), QPointF(rect.right(), _RULER_HEIGHT - 0.5))
        seconds = self._last_frame / FPS
        step = 1.0 if rect.width() / max(seconds, 1e-6) >= 28 else 5.0
        fine = rect.width() / max(seconds, 1e-6) >= 120
        t = 0.0
        while t <= seconds + 1e-9:
            x = self.x_of(t * FPS)
            painter.setPen(QPen(mid, 1))
            painter.drawLine(QPointF(x, _RULER_HEIGHT - 6), QPointF(x, self.height()))
            if not self._bands or not any(self.x_of(b.start + b.fade) <= x <= self.x_of(b.end) for b in self._bands):
                painter.setPen(text)
                painter.drawText(QPointF(x + 2, _RULER_HEIGHT - 6), f"{t:g} s")
            if fine:
                for tenth in range(1, 10):
                    sub = t + tenth / 10.0
                    if sub > seconds:
                        break
                    xs = self.x_of(sub * FPS)
                    painter.drawLine(QPointF(xs, _RULER_HEIGHT - 3), QPointF(xs, _RULER_HEIGHT - 1))
            t += step

        # Lanes and their keys.
        for index, lane in enumerate(self._lanes):
            centre = self._lane_centre(index)
            painter.setPen(QPen(mid, 1, Qt.DotLine))
            painter.drawLine(QPointF(rect.left(), centre), QPointF(rect.right(), centre))
            painter.setPen(text)
            painter.drawText(QRectF(4, centre - _LANE_HEIGHT / 2, _LABEL_WIDTH - 8, _LANE_HEIGHT),
                             Qt.AlignLeft | Qt.AlignVCenter,
                             painter.fontMetrics().elidedText(lane.label, Qt.ElideRight, _LABEL_WIDTH - 8))
            for frame in lane.frames:
                dragging = self._drag == (lane.key, frame) and self._drag_to is not None
                shown = self._drag_to if dragging else frame
                self._draw_key(painter, self.x_of(shown), centre, frame in lane.filled, accent, text,
                               ghost=False)
                if dragging and shown != frame:
                    self._draw_key(painter, self.x_of(frame), centre, frame in lane.filled, accent, text,
                                   ghost=True)

        # The playhead over everything.
        x = self.x_of(self._playhead)
        painter.setPen(QPen(accent, 2))
        painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        painter.end()

    @staticmethod
    def _draw_key(painter: QPainter, x: float, y: float, filled: bool, accent: QColor, outline: QColor,
                  *, ghost: bool) -> None:
        size = 5.5
        diamond = QPolygonF([QPointF(x, y - size), QPointF(x + size, y), QPointF(x, y + size),
                             QPointF(x - size, y)])
        colour = QColor(accent)
        if ghost:
            colour.setAlpha(70)
        painter.setPen(QPen(outline if not ghost else colour, 1))
        painter.setBrush(colour if filled or not ghost else Qt.NoBrush)
        if not filled and not ghost:
            painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 110))
        painter.drawPolygon(diamond)

    # ── input ───────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        point = event.position()
        if point.x() < _LABEL_WIDTH:
            return
        hit = self.key_at(point)
        if event.button() == Qt.RightButton:
            if hit is not None:
                menu = QMenu(self)
                remove = menu.addAction(translate_active_ui_text("Remove this key"))
                if menu.exec(event.globalPosition().toPoint()) is remove:
                    self.key_removed.emit(*hit)
            return
        if event.button() != Qt.LeftButton:
            return
        if hit is not None:
            self._drag, self._drag_to = hit, hit[1]
        else:
            self._scrubbing = True
            self.seek_requested.emit(float(self.frame_at(point.x())))
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        point = event.position()
        if self._drag is not None:
            frame = self.frame_at(point.x())
            if frame != self._drag_to:
                self._drag_to = frame
                self.update()
        elif self._scrubbing:
            self.seek_requested.emit(float(self.frame_at(point.x())))
        else:
            self.setCursor(Qt.SizeHorCursor if self.key_at(point) is not None else Qt.ArrowCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if self._drag is not None:
            (lane, frame), to = self._drag, self._drag_to
            self._drag = self._drag_to = None
            if to is not None and to != frame:
                self.key_moved.emit(lane, frame, to)
            else:
                self.seek_requested.emit(float(frame))
            self.update()
        self._scrubbing = False


__all__ = ["Band", "KeyTimeline", "Lane"]
