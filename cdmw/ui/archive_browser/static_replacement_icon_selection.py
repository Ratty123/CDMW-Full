"""Interactive region selection for generated static-replacement icons."""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPaintEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class IconRegionSelector(QWidget):
    """Display one captured frame and let the user drag a source-image rectangle."""

    selection_changed = Signal()

    def __init__(self, image: QImage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if image.isNull() or image.width() <= 0 or image.height() <= 0:
            raise ValueError("Icon selection requires a non-empty preview image.")
        self._image = image.convertToFormat(QImage.Format.Format_RGBA8888).copy()
        self._selection = QRect(0, 0, self._image.width(), self._image.height())
        self._drag_origin: QPoint | None = None
        self._selection_before_drag = QRect(self._selection)
        self.setObjectName("MeshAlignmentIconRegionSelector")
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMinimumSize(420, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(820, 500)

    def source_selection_rect(self) -> QRect:
        return QRect(self._selection)

    def reset_selection(self) -> None:
        self._set_selection(QRect(0, 0, self._image.width(), self._image.height()))

    def image_display_rect(self) -> QRectF:
        available = QRectF(self.rect())
        if available.width() <= 0 or available.height() <= 0:
            return QRectF()
        scale = min(
            available.width() / float(self._image.width()),
            available.height() / float(self._image.height()),
        )
        width = float(self._image.width()) * scale
        height = float(self._image.height()) * scale
        return QRectF(
            available.left() + (available.width() - width) * 0.5,
            available.top() + (available.height() - height) * 0.5,
            width,
            height,
        )

    def _set_selection(self, selection: QRect) -> None:
        bounded = selection.normalized().intersected(self._image.rect())
        if bounded.width() <= 0 or bounded.height() <= 0:
            return
        if bounded == self._selection:
            return
        self._selection = bounded
        self.selection_changed.emit()
        self.update()

    def _source_point(self, widget_point: QPointF, *, clamp: bool) -> QPoint | None:
        target = self.image_display_rect()
        if target.isEmpty():
            return None
        if not clamp and not target.contains(widget_point):
            return None
        x = min(max(widget_point.x(), target.left()), target.right())
        y = min(max(widget_point.y(), target.top()), target.bottom())
        source_x = math.floor((x - target.left()) * self._image.width() / target.width())
        source_y = math.floor((y - target.top()) * self._image.height() / target.height())
        return QPoint(
            min(max(0, source_x), self._image.width() - 1),
            min(max(0, source_y), self._image.height() - 1),
        )

    def _selection_display_rect(self) -> QRectF:
        target = self.image_display_rect()
        selection = self._selection
        left = target.left() + target.width() * selection.left() / self._image.width()
        top = target.top() + target.height() * selection.top() / self._image.height()
        right = target.left() + target.width() * (selection.left() + selection.width()) / self._image.width()
        bottom = target.top() + target.height() * (selection.top() + selection.height()) / self._image.height()
        return QRectF(left, top, right - left, bottom - top)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        point = self._source_point(event.position(), clamp=False)
        if point is None:
            return
        self._drag_origin = point
        self._selection_before_drag = QRect(self._selection)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._drag_origin is None:
            super().mouseMoveEvent(event)
            return
        point = self._source_point(event.position(), clamp=True)
        if point is None:
            return
        left = min(self._drag_origin.x(), point.x())
        top = min(self._drag_origin.y(), point.y())
        right = max(self._drag_origin.x(), point.x()) + 1
        bottom = max(self._drag_origin.y(), point.y()) + 1
        self._set_selection(QRect(left, top, right - left, bottom - top))
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton or self._drag_origin is None:
            super().mouseReleaseEvent(event)
            return
        point = self._source_point(event.position(), clamp=True)
        if point is not None:
            self.mouseMoveEvent(event)
        self._drag_origin = None
        if self._selection.width() < 2 or self._selection.height() < 2:
            self._set_selection(self._selection_before_drag)
        event.accept()

    def paintEvent(self, _event: QPaintEvent) -> None:  # type: ignore[override]
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), QColor(18, 21, 27))
            target = self.image_display_rect()
            if target.isEmpty():
                return
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawImage(target, self._image)
            painter.fillRect(target, QColor(0, 0, 0, 135))
            selected_target = self._selection_display_rect()
            painter.drawImage(selected_target, self._image, QRectF(self._selection))
            painter.setPen(QPen(QColor(72, 205, 255), 2.0))
            painter.drawRect(selected_target.adjusted(1.0, 1.0, -1.0, -1.0))
        finally:
            painter.end()


class AlignmentIconSelectionDialog(QDialog):
    """Non-blocking dialog used to choose the generated icon's source region."""

    def __init__(self, image: QImage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MeshAlignmentIconSelectionDialog")
        self.setWindowTitle("Select Icon Area")
        self.setModal(True)
        self.resize(860, 620)

        layout = QVBoxLayout(self)
        instructions = QLabel(
            "Drag a rectangle around the area to use. The selection is fitted into the "
            "512 x 512 icon with its aspect ratio preserved; unused space is padded."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        self.selector = IconRegionSelector(image, self)
        layout.addWidget(self.selector, 1)

        self.selection_status = QLabel(self)
        self.selection_status.setObjectName("MeshAlignmentIconSelectionStatus")
        layout.addWidget(self.selection_status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, parent=self)
        self.reset_button = buttons.addButton("Reset to Full Frame", QDialogButtonBox.ButtonRole.ResetRole)
        self.use_selection_button = buttons.addButton("Use Selection", QDialogButtonBox.ButtonRole.AcceptRole)
        self.use_selection_button.setDefault(True)
        self.reset_button.clicked.connect(self.selector.reset_selection)
        self.use_selection_button.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.selector.selection_changed.connect(self._refresh_selection_status)
        self._refresh_selection_status()

    def selected_source_rect(self) -> tuple[int, int, int, int]:
        selection = self.selector.source_selection_rect()
        return selection.x(), selection.y(), selection.width(), selection.height()

    def _refresh_selection_status(self) -> None:
        selection = self.selector.source_selection_rect()
        self.selection_status.setText(
            f"Selected source area: {selection.width()} x {selection.height()} pixels"
        )
        self.use_selection_button.setEnabled(selection.width() >= 2 and selection.height() >= 2)


__all__ = ["AlignmentIconSelectionDialog", "IconRegionSelector"]
