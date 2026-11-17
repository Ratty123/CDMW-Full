"""New painting's previews: the frame to scale with the picture on its canvas, and the frame list.

`PaintingFrameView` draws the chosen frame at its real proportions, seen from the front,
with the picture where the frame's canvas is. It paints in logical pixels, so it is as
sharp at 150% as at 100%, and grows with the dialog. The frame itself is drawn plain in
the colour of its game icon; the 3D view beside it shows the frame's own mesh.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QLabel, QListView, QListWidget, QListWidgetItem, QSizePolicy, QVBoxLayout, QWidget

#: A dark wood, for a frame whose icon gives no colour.
DEFAULT_FRAME_COLOUR = QColor(107, 74, 43)


def frame_colour(icon: QImage) -> QColor:
    """The frame's colour in its game icon: the average of the visible pixels near its edge."""

    if icon.isNull() or icon.width() < 4 or icon.height() < 4:
        return QColor(DEFAULT_FRAME_COLOUR)
    image = icon.convertToFormat(QImage.Format.Format_ARGB32)
    width, height = image.width(), image.height()
    ring = max(1, min(width, height) // 10)
    step = max(1, min(width, height) // 64)
    total = [0, 0, 0]
    count = 0
    for y in range(0, height, step):
        edge_row = y < ring or y >= height - ring
        for x in range(0, width, step if edge_row else max(1, ring)):
            if not (edge_row or x < ring or x >= width - ring):
                continue
            colour = image.pixelColor(x, y)
            if colour.alpha() < 128:
                continue
            total[0] += colour.red()
            total[1] += colour.green()
            total[2] += colour.blue()
            count += 1
    if not count:
        return QColor(DEFAULT_FRAME_COLOUR)
    return QColor(*(int(value / count) for value in total))


class PaintingFrameView(QWidget):
    """The frame to scale, seen from the front, with the picture on its canvas."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("new_item_painting_preview")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(280, 220)
        self._frame_size: Optional[Tuple[float, float]] = None
        self._canvas_box: Optional[Tuple[float, float, float, float]] = None
        self._colour = QColor(DEFAULT_FRAME_COLOUR)
        self._picture = QImage()
        layout = QVBoxLayout(self)
        self.message = QLabel("")
        self.message.setObjectName("HintLabel")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        self.message.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addStretch(1)
        layout.addWidget(self.message)
        layout.addStretch(1)

    def sizeHint(self) -> QSize:
        return QSize(640, 520)

    # ------------------------------------------------------------------ state

    def set_frame(self, size_m: Sequence[float], canvas_size_m: Sequence[float], canvas_box: Sequence[float] = (),
                  colour: Optional[QColor] = None) -> None:
        """Show a frame `size_m` (width, height) whose canvas is at `canvas_box` (left, top,
        right, bottom from its top left, in metres); without a box the canvas is centred."""

        width, height = (max(1e-3, float(value)) for value in tuple(size_m)[:2])
        if len(tuple(canvas_box)) == 4:
            left, top, right, bottom = (float(value) for value in canvas_box)
        else:
            canvas_w, canvas_h = (min(float(value), limit) for value, limit in zip(tuple(canvas_size_m)[:2], (width, height)))
            left, top = (width - canvas_w) / 2, (height - canvas_h) / 2
            right, bottom = left + canvas_w, top + canvas_h
        left, top = max(0.0, min(left, width)), max(0.0, min(top, height))
        right, bottom = max(left + 1e-3, min(right, width)), max(top + 1e-3, min(bottom, height))
        self._frame_size = (width, height)
        self._canvas_box = (left, top, right, bottom)
        self._colour = QColor(colour) if colour is not None and colour.isValid() else QColor(DEFAULT_FRAME_COLOUR)
        self.update()

    def clear_frame(self, message: str = "") -> None:
        self._frame_size = None
        self._canvas_box = None
        self._picture = QImage()
        self.set_message(message)
        self.update()

    def set_picture(self, image: QImage) -> None:
        self._picture = QImage(image)
        if not self._picture.isNull():
            self.set_message("")
        self.update()

    def clear_picture(self, message: str = "") -> None:
        self._picture = QImage()
        self.set_message(message)
        self.update()

    def set_message(self, text: str) -> None:
        self.message.setText(str(text or ""))
        self.message.setVisible(bool(text))

    def has_frame(self) -> bool:
        return self._frame_size is not None

    def has_picture(self) -> bool:
        return not self._picture.isNull()

    def picture(self) -> QImage:
        return QImage(self._picture)

    # ------------------------------------------------------------------ geometry

    def frame_rect(self) -> QRectF:
        """Where the frame is drawn, in logical pixels; empty without a frame."""

        if self._frame_size is None:
            return QRectF()
        margin = max(12.0, min(self.width(), self.height()) * 0.06)
        box = QRectF(self.rect()).adjusted(margin, margin, -margin, -margin)
        if box.width() <= 1 or box.height() <= 1:
            return QRectF()
        width, height = self._frame_size
        scale = min(box.width() / width, box.height() / height)
        drawn = QSize(int(round(width * scale)), int(round(height * scale)))
        return QRectF(box.center().x() - drawn.width() / 2, box.center().y() - drawn.height() / 2,
                      drawn.width(), drawn.height())

    def canvas_rect(self) -> QRectF:
        """Where the picture is drawn, in logical pixels; empty without a frame."""

        frame = self.frame_rect()
        if frame.isEmpty() or self._canvas_box is None or self._frame_size is None:
            return QRectF()
        scale = frame.width() / self._frame_size[0]
        left, top, right, bottom = self._canvas_box
        return QRectF(frame.left() + left * scale, frame.top() + top * scale,
                      (right - left) * scale, (bottom - top) * scale)

    # ------------------------------------------------------------------ painting

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        frame = self.frame_rect()
        if frame.isEmpty():
            return
        canvas = self.canvas_rect()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        # A soft shadow on the wall, then the frame with light from the top left.
        shadow = max(3.0, frame.width() * 0.012)
        painter.fillRect(frame.translated(shadow, shadow * 1.4), QColor(0, 0, 0, 90))
        gradient = QLinearGradient(frame.topLeft(), frame.bottomRight())
        gradient.setColorAt(0.0, self._colour.lighter(135))
        gradient.setColorAt(0.5, self._colour)
        gradient.setColorAt(1.0, self._colour.darker(150))
        painter.fillRect(frame, QBrush(gradient))
        painter.setPen(QPen(self._colour.darker(200), 1.0))
        painter.drawRect(frame.adjusted(0.5, 0.5, -0.5, -0.5))
        if canvas.isEmpty():
            painter.end()
            return
        # The canvas sits a little into the frame: a darker lip around it.
        lip = max(1.5, min(canvas.width(), canvas.height()) * 0.01)
        painter.fillRect(canvas.adjusted(-lip, -lip, lip, lip), self._colour.darker(230))
        if self._picture.isNull():
            painter.fillRect(canvas, QColor(222, 214, 198))
            painter.setPen(QPen(QColor(190, 180, 160), 1.0, Qt.PenStyle.DashLine))
            painter.drawRect(canvas.adjusted(4, 4, -4, -4))
        else:
            painter.drawImage(canvas, self._picture)
        painter.end()


class FrameList(QListWidget):
    """The frames as a list with their thumbnails, with the few calls a combo box has.

    Row numbers are the frames' places in the list; no row is current until a frame is
    chosen, and `currentIndexChanged` gives the row (-1 for none)."""

    currentIndexChanged = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("new_item_painting_frame")
        self.setViewMode(QListView.ViewMode.ListMode)
        self.setIconSize(QSize(72, 72))
        self.setUniformItemSizes(True)
        self.setWordWrap(True)
        self.setSpacing(2)
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.currentRowChanged.connect(self.currentIndexChanged)

    def add_frame(self, text: str, data: str, icon=None, tooltip: str = "") -> QListWidgetItem:
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, data)
        if icon is not None:
            item.setIcon(icon)
        if tooltip:
            item.setToolTip(tooltip)
        self.addItem(item)
        return item

    def findData(self, data) -> int:  # noqa: N802 - as QComboBox
        for row in range(self.count()):
            if self.item(row).data(Qt.ItemDataRole.UserRole) == data:
                return row
        return -1

    def itemData(self, row: int):  # noqa: N802 - as QComboBox
        item = self.item(row)
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def currentIndex(self) -> int:  # noqa: N802 - as QComboBox
        return self.currentRow()

    def currentData(self):  # noqa: N802 - as QComboBox
        return self.itemData(self.currentRow())

    def setCurrentIndex(self, row: int) -> None:  # noqa: N802 - as QComboBox
        if row < 0 or row >= self.count():
            if self.currentRow() >= 0:
                self.setCurrentRow(-1)
            self.clearSelection()
            return
        self.setCurrentRow(row)
        self.scrollToItem(self.item(row))


__all__ = ["DEFAULT_FRAME_COLOUR", "FrameList", "PaintingFrameView", "frame_colour"]
