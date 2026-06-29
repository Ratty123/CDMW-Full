"""Small Qt-drawn icons for Mesh Editor tools."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication


def mesh_editor_action_icon(icon_key: str, palette: QPalette | None = None) -> QIcon:
    key = str(icon_key or "").strip().lower()
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    app = QApplication.instance()
    resolved_palette = QPalette(palette or (app.palette() if app is not None else QPalette()))
    primary = QColor(resolved_palette.color(QPalette.ButtonText))
    accent = QColor(resolved_palette.color(QPalette.Highlight))
    subtle = QColor(resolved_palette.color(QPalette.PlaceholderText))
    if not subtle.isValid() or subtle.alpha() == 0:
        subtle = QColor(primary)
        subtle.setAlpha(150)
    accent.setAlpha(220)

    def pen(color: QColor, width: float = 1.7) -> QPen:
        item = QPen(color, width)
        item.setCapStyle(Qt.RoundCap)
        item.setJoinStyle(Qt.RoundJoin)
        return item

    painter.setBrush(Qt.NoBrush)
    painter.setPen(pen(primary))

    if key.startswith("select_vertex"):
        painter.setBrush(QBrush(accent))
        for x, y in ((6, 6), (14, 6), (10, 14)):
            painter.drawEllipse(x - 2, y - 2, 4, 4)
    elif key.startswith("select_edge"):
        painter.drawLine(5, 13, 15, 7)
        painter.setBrush(QBrush(accent))
        painter.drawEllipse(3, 11, 4, 4)
        painter.drawEllipse(13, 5, 4, 4)
    elif key.startswith("select_face"):
        path = _triangle_path()
        painter.setBrush(QBrush(accent))
        painter.drawPath(path)
    elif key == "transform_move":
        painter.drawLine(10, 3, 10, 17)
        painter.drawLine(3, 10, 17, 10)
        painter.drawLine(10, 3, 8, 5)
        painter.drawLine(10, 3, 12, 5)
        painter.drawLine(17, 10, 15, 8)
        painter.drawLine(17, 10, 15, 12)
    elif key == "transform_rotate":
        painter.drawArc(4, 4, 12, 12, 30 * 16, 280 * 16)
        painter.drawLine(14, 5, 16, 4)
        painter.drawLine(14, 5, 14, 8)
    elif key == "transform_scale":
        painter.drawRect(5, 5, 8, 8)
        painter.drawLine(9, 9, 16, 16)
        painter.drawLine(16, 16, 12, 16)
        painter.drawLine(16, 16, 16, 12)
    elif key.startswith("brush"):
        painter.drawLine(5, 15, 13, 7)
        painter.setBrush(QBrush(accent))
        painter.drawEllipse(12, 4, 4, 5)
    elif key in {"undo", "redo"}:
        if key == "undo":
            painter.drawArc(4, 5, 12, 10, 25 * 16, 255 * 16)
            painter.drawLine(5, 9, 3, 6)
            painter.drawLine(5, 9, 8, 8)
        else:
            painter.drawArc(4, 5, 12, 10, -100 * 16, 255 * 16)
            painter.drawLine(15, 9, 17, 6)
            painter.drawLine(15, 9, 12, 8)
    elif key.startswith("uv"):
        painter.drawRect(4, 4, 12, 12)
        painter.setPen(pen(accent))
        if "flip_u" in key:
            painter.drawLine(10, 5, 10, 15)
            painter.drawLine(5, 10, 15, 10)
            painter.drawLine(5, 10, 7, 8)
            painter.drawLine(15, 10, 13, 8)
        elif "flip_v" in key:
            painter.drawLine(5, 10, 15, 10)
            painter.drawLine(10, 5, 10, 15)
            painter.drawLine(10, 5, 8, 7)
            painter.drawLine(10, 15, 8, 13)
        else:
            painter.drawLine(4, 16, 16, 4)
    elif "normal" in key:
        painter.drawPath(_triangle_path())
        painter.setPen(pen(accent))
        painter.drawLine(10, 10, 10, 3)
        painter.drawLine(10, 3, 8, 5)
        painter.drawLine(10, 3, 12, 5)
    elif key.startswith("material"):
        painter.setBrush(QBrush(accent))
        painter.drawRect(4, 5, 12, 10)
        painter.setBrush(QBrush(subtle))
        painter.drawRect(8, 9, 8, 6)
    elif key.startswith("mode_object"):
        painter.drawRect(5, 5, 10, 10)
        painter.drawLine(5, 5, 8, 2)
        painter.drawLine(15, 5, 18, 2)
        painter.drawLine(8, 2, 18, 2)
    elif key.startswith("mode_sculpt"):
        painter.setBrush(QBrush(accent))
        painter.drawEllipse(5, 5, 10, 10)
        painter.setBrush(Qt.NoBrush)
        painter.drawLine(8, 14, 13, 8)
    else:
        painter.drawPath(_triangle_path())
        painter.setPen(pen(accent))
        painter.drawLine(5, 14, 15, 14)
        painter.drawLine(10, 5, 10, 14)

    painter.end()
    return QIcon(pixmap)


def _triangle_path() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(10, 4)
    path.lineTo(16, 15)
    path.lineTo(4, 15)
    path.closeSubpath()
    return path


__all__ = ["mesh_editor_action_icon"]
