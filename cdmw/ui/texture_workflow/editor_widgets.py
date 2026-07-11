from __future__ import annotations

"""Small widgets used by the standalone Texture Editor UI."""

import math
from typing import Optional, Sequence, Tuple

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolButton, QVBoxLayout, QWidget

class CollapsibleSection(QWidget):
    toggled = Signal(bool)

    def __init__(
        self,
        title: str,
        content_widget: QWidget,
        *,
        expanded: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._content_widget = content_widget
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.toggle_button = QToolButton()
        self.toggle_button.setText(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.toggle_button.setMinimumHeight(26)
        self.toggle_button.setObjectName("SectionToggle")
        self.toggle_button.clicked.connect(self.set_expanded)
        layout.addWidget(self.toggle_button)
        layout.addWidget(self._content_widget)
        self.set_expanded(expanded)

    def is_expanded(self) -> bool:
        return self.toggle_button.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        self.toggle_button.blockSignals(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.blockSignals(False)
        self.toggle_button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._content_widget.setVisible(expanded)
        self.toggled.emit(expanded)


class TextureEditorNavigator(QWidget):
    center_requested = Signal(float, float)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._image: Optional[QImage] = None
        self._image_width = 0
        self._image_height = 0
        self._viewport_rect: Optional[Tuple[float, float, float, float]] = None
        self._dragging = False
        self.setMinimumSize(170, 120)
        self.setMaximumHeight(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_state(
        self,
        image: Optional[QImage],
        *,
        image_width: int,
        image_height: int,
        viewport_rect: Optional[Tuple[float, float, float, float]],
    ) -> None:
        self._image = image
        self._image_width = max(0, int(image_width))
        self._image_height = max(0, int(image_height))
        self._viewport_rect = viewport_rect
        self.update()

    def _target_rect(self) -> QRectF:
        if self._image_width <= 0 or self._image_height <= 0:
            return QRectF()
        inner = QRectF(8.0, 8.0, max(1.0, float(self.width()) - 16.0), max(1.0, float(self.height()) - 16.0))
        scale = min(inner.width() / float(self._image_width), inner.height() / float(self._image_height))
        width = float(self._image_width) * scale
        height = float(self._image_height) * scale
        x = inner.x() + ((inner.width() - width) / 2.0)
        y = inner.y() + ((inner.height() - height) / 2.0)
        return QRectF(x, y, width, height)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1B202A"))
        target = self._target_rect()
        if target.isEmpty():
            painter.setPen(QColor("#8B97AA"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Navigator")
            return
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setPen(QPen(QColor(255, 255, 255, 18), 1))
        painter.setBrush(QColor(255, 255, 255, 6))
        painter.drawRoundedRect(target, 6, 6)
        if self._image is not None:
            painter.drawImage(target, self._image)
        else:
            painter.setPen(QColor("#8B97AA"))
            painter.drawText(target.toRect(), Qt.AlignCenter, "No preview")
        if self._viewport_rect is not None and self._image_width > 0 and self._image_height > 0:
            vx, vy, vw, vh = self._viewport_rect
            view = QRectF(
                target.x() + ((vx / float(self._image_width)) * target.width()),
                target.y() + ((vy / float(self._image_height)) * target.height()),
                max(6.0, (vw / float(self._image_width)) * target.width()),
                max(6.0, (vh / float(self._image_height)) * target.height()),
            )
            view = view.intersected(target)
            painter.setBrush(QColor(116, 193, 255, 30))
            painter.setPen(QPen(QColor("#74C1FF"), 1.4))
            painter.drawRoundedRect(view, 4, 4)

    def _emit_center_request(self, pos) -> None:
        target = self._target_rect()
        if target.isEmpty() or self._image_width <= 0 or self._image_height <= 0 or not target.contains(pos):
            return
        ratio_x = (float(pos.x()) - target.x()) / max(1.0, target.width())
        ratio_y = (float(pos.y()) - target.y()) / max(1.0, target.height())
        image_x = max(0.0, min(float(self._image_width), ratio_x * float(self._image_width)))
        image_y = max(0.0, min(float(self._image_height), ratio_y * float(self._image_height)))
        self.center_requested.emit(image_x, image_y)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() != Qt.LeftButton:
            return
        self._dragging = True
        self._emit_center_request(event.position())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._dragging:
            self._emit_center_request(event.position())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self._dragging = False


class TextureEditorRuler(QWidget):
    def __init__(self, orientation: Qt.Orientation, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._orientation = orientation
        self._image_length = 0
        self._other_length = 0
        self._display_scale = 1.0
        self._scroll_value = 0
        self._viewport_offset = 0
        self._hover_position: Optional[int] = None
        self._guides: Tuple[int, ...] = ()
        if orientation == Qt.Horizontal:
            self.setFixedHeight(22)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        else:
            self.setFixedWidth(22)
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

    def set_state(
        self,
        *,
        image_length: int,
        other_length: int,
        display_scale: float,
        scroll_value: int,
        viewport_offset: int,
        hover_position: Optional[int],
        guides: Sequence[int],
    ) -> None:
        self._image_length = max(0, int(image_length))
        self._other_length = max(0, int(other_length))
        self._display_scale = max(0.0001, float(display_scale))
        self._scroll_value = max(0, int(scroll_value))
        self._viewport_offset = int(viewport_offset)
        self._hover_position = None if hover_position is None else int(hover_position)
        self._guides = tuple(int(value) for value in guides)
        self.update()

    def _tick_step(self) -> int:
        if self._display_scale <= 0:
            return 100
        desired = 80.0 / self._display_scale
        magnitude = 1
        while magnitude * 10 <= desired:
            magnitude *= 10
        for factor in (1, 2, 5, 10):
            candidate = magnitude * factor
            if candidate >= desired:
                return max(1, int(candidate))
        return max(1, int(magnitude * 10))

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1C212B"))
        if self._image_length <= 0:
            return
        painter.setPen(QPen(QColor(255, 255, 255, 18), 1))
        if self._orientation == Qt.Horizontal:
            painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
            visible_pixels = self.width() / self._display_scale
        else:
            painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
            visible_pixels = self.height() / self._display_scale
        start_pixel = -float(self._viewport_offset) / self._display_scale
        end_pixel = min(float(self._image_length), start_pixel + visible_pixels)
        step = self._tick_step()
        first_tick = int(math.floor(start_pixel / float(step)) * step)
        painter.setPen(QPen(QColor("#A9B6CB"), 1))
        value = first_tick
        while value <= end_pixel + step:
            widget_pos = (float(value) - start_pixel) * self._display_scale
            if self._orientation == Qt.Horizontal:
                x = int(round(widget_pos))
                painter.drawLine(x, self.height() - 8, x, self.height())
                painter.drawText(x + 2, 12, str(value))
            else:
                y = int(round(widget_pos))
                painter.drawLine(self.width() - 8, y, self.width(), y)
                painter.save()
                painter.translate(8, y + 16)
                painter.rotate(-90)
                painter.drawText(0, 0, str(value))
                painter.restore()
            value += step
        guide_pen = QPen(QColor(116, 193, 255, 140), 1)
        hover_pen = QPen(QColor("#F2C14E"), 1)
        for guide in self._guides:
            pos = self._viewport_offset + (float(guide) * self._display_scale)
            painter.setPen(guide_pen)
            if self._orientation == Qt.Horizontal:
                x = int(round(pos))
                painter.drawLine(x, 0, x, self.height())
            else:
                y = int(round(pos))
                painter.drawLine(0, y, self.width(), y)
        if self._hover_position is not None:
            pos = self._viewport_offset + (float(self._hover_position) * self._display_scale)
            painter.setPen(hover_pen)
            if self._orientation == Qt.Horizontal:
                x = int(round(pos))
                painter.drawLine(x, 0, x, self.height())
            else:
                y = int(round(pos))
                painter.drawLine(0, y, self.width(), y)

__all__ = ["CollapsibleSection", "TextureEditorNavigator", "TextureEditorRuler"]
