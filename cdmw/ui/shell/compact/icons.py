"""Small palette-derived line icons for the compact shell."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap


def _line(painter: QPainter, *points: tuple[float, float]) -> None:
    for start, end in zip(points, points[1:]):
        painter.drawLine(QPointF(*start), QPointF(*end))


def compact_line_icon(name: str, palette: QPalette, *, size: int = 18) -> QIcon:
    """Draw a dependency-free icon using the current palette's text/accent colors."""

    extent = max(12, int(size))
    pixmap = QPixmap(extent, extent)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    color = palette.color(QPalette.ColorRole.ButtonText)
    accent = palette.color(QPalette.ColorRole.Highlight)
    pen = QPen(color, max(1.2, extent / 13.0), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    scale = extent / 18.0
    painter.scale(scale, scale)
    key = str(name or "").lower()

    if key == "folder":
        path = QPainterPath(QPointF(2.0, 5.0))
        path.lineTo(7.0, 5.0)
        path.lineTo(8.5, 7.0)
        path.lineTo(16.0, 7.0)
        path.lineTo(15.0, 15.0)
        path.lineTo(2.0, 15.0)
        path.closeSubpath()
        painter.drawPath(path)
    elif key in {"model", "mesh"}:
        _line(painter, (9, 2), (15, 5.5), (15, 12.5), (9, 16), (3, 12.5), (3, 5.5), (9, 2))
        _line(painter, (3, 5.5), (9, 9), (15, 5.5))
        _line(painter, (9, 9), (9, 16))
    elif key == "image":
        painter.drawRect(QRectF(2.5, 3.0, 13.0, 12.0))
        painter.drawEllipse(QPointF(12.5, 6.0), 1.2, 1.2)
        _line(painter, (4, 13), (7.5, 9.5), (10, 12), (12, 10), (15, 13))
    elif key == "add":
        painter.drawRect(QRectF(2.5, 2.5, 13.0, 13.0))
        _line(painter, (9, 5.5), (9, 12.5))
        _line(painter, (5.5, 9), (12.5, 9))
    elif key == "person":
        painter.drawEllipse(QPointF(9, 4), 2, 2)
        _line(painter, (9, 6), (9, 12), (5, 16))
        _line(painter, (9, 12), (13, 16))
        _line(painter, (4, 8), (9, 9), (14, 8))
    elif key == "layers":
        _line(painter, (2.5, 6), (9, 2.5), (15.5, 6), (9, 9.5), (2.5, 6))
        _line(painter, (3, 9), (9, 12.5), (15, 9))
        _line(painter, (3, 12), (9, 15.5), (15, 12))
    elif key == "swap":
        _line(painter, (3, 6), (14, 6), (11.5, 3.5))
        _line(painter, (15, 12), (4, 12), (6.5, 14.5))
    elif key == "droplet":
        path = QPainterPath(QPointF(9, 2))
        path.cubicTo(7.5, 5.0, 4.0, 8.5, 4.0, 11.0)
        path.cubicTo(4.0, 14.0, 6.2, 16.0, 9.0, 16.0)
        path.cubicTo(11.8, 16.0, 14.0, 14.0, 14.0, 11.0)
        path.cubicTo(14.0, 8.5, 10.5, 5.0, 9.0, 2.0)
        painter.drawPath(path)
    elif key == "brush":
        _line(painter, (3, 15), (6, 12), (13.5, 4.5), (15.5, 2.5))
        _line(painter, (5.5, 11.5), (9, 15), (3, 16), (3, 15))
    elif key == "package":
        painter.drawRoundedRect(QRectF(2.5, 4.5, 13.0, 11.0), 1.0, 1.0)
        _line(painter, (2.5, 8), (15.5, 8))
        _line(painter, (7, 5), (7, 8), (11, 8), (11, 5))
    elif key == "document":
        path = QPainterPath(QPointF(4, 2))
        path.lineTo(11, 2)
        path.lineTo(15, 6)
        path.lineTo(15, 16)
        path.lineTo(4, 16)
        path.closeSubpath()
        painter.drawPath(path)
        _line(painter, (11, 2), (11, 6), (15, 6))
        _line(painter, (6.5, 9), (12.5, 9))
        _line(painter, (6.5, 12), (12.5, 12))
    elif key == "globe":
        painter.drawEllipse(QRectF(2.5, 2.5, 13.0, 13.0))
        painter.drawEllipse(QRectF(6.0, 2.5, 6.0, 13.0))
        _line(painter, (3, 7), (15, 7))
        _line(painter, (3, 11), (15, 11))
    elif key == "book":
        path = QPainterPath(QPointF(2.5, 4))
        path.quadTo(6, 3, 9, 6)
        path.quadTo(12, 3, 15.5, 4)
        path.lineTo(15.5, 15)
        path.quadTo(12, 14, 9, 16)
        path.quadTo(6, 14, 2.5, 15)
        path.closeSubpath()
        painter.drawPath(path)
        _line(painter, (9, 6), (9, 16))
    elif key == "search":
        painter.drawEllipse(QRectF(2.5, 2.5, 9.5, 9.5))
        _line(painter, (11, 11), (16, 16))
    elif key in {"chevron_down", "chevron_up"}:
        points = ((4, 6), (9, 11), (14, 6)) if key.endswith("down") else ((4, 12), (9, 7), (14, 12))
        _line(painter, *points)
    elif key == "activity":
        pen.setColor(accent)
        painter.setPen(pen)
        _line(painter, (2, 10), (5.5, 10), (7.5, 5), (10, 14), (12, 8), (16, 8))
    elif key == "more":
        for x in (5.0, 9.0, 13.0):
            painter.drawEllipse(QPointF(x, 9), 0.9, 0.9)
    else:
        painter.drawEllipse(QRectF(3.0, 3.0, 12.0, 12.0))

    painter.end()
    return QIcon(pixmap)


__all__ = ["compact_line_icon"]
