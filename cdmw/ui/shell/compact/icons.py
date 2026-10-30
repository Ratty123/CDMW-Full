"""Small palette-aware vector icons for the compact shell."""

from __future__ import annotations

from math import ceil

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer


# Official Clyde symbol, unmodified geometry; use Discord's black/white variants.
# https://discord.com/branding
# https://cdn.prod.website-files.com/6257adef93867e50d84d30e2/66e3d7f4ef6498ac018f2c55_Symbol.svg
_DISCORD_SYMBOL = b'''<svg viewBox="0 0 64 48" xmlns="http://www.w3.org/2000/svg">
<path d="M40.575 0C39.9562 1.09866 39.4006 2.2352 38.8954 3.397C34.0967 2.67719 29.2096 2.67719 24.3982 3.397C23.9057 2.2352 23.3374 1.09866 22.7186 0C18.2104 0.770324 13.8157 2.12155 9.64839 4.02841C1.38951 16.2652 -0.845688 28.1863 0.265599 39.9432C5.10222 43.517 10.5197 46.2447 16.2909 47.9874C17.5916 46.2447 18.7407 44.3883 19.7257 42.4562C17.8568 41.7616 16.0509 40.8903 14.3208 39.88C14.7755 39.5517 15.2175 39.2107 15.6468 38.8824C25.7873 43.6559 37.5316 43.6559 47.6847 38.8824C48.1141 39.236 48.5561 39.577 49.0107 39.88C47.2806 40.9029 45.4748 41.7616 43.5931 42.4688C44.5781 44.4009 45.7273 46.2573 47.028 48C52.7991 46.2573 58.2167 43.5422 63.0533 39.9684C64.3666 26.3299 60.8055 14.5099 53.6452 4.04104C49.4905 2.13418 45.0959 0.782952 40.5876 0.0252565L40.575 0ZM21.1401 32.7072C18.0209 32.7072 15.4321 29.8785 15.4321 26.3804C15.4321 22.8824 17.9199 20.041 21.1275 20.041C24.3351 20.041 26.886 22.895 26.8354 26.3804C26.7849 29.8658 24.3224 32.7072 21.1401 32.7072ZM42.1788 32.7072C39.047 32.7072 36.4834 29.8785 36.4834 26.3804C36.4834 22.8824 38.9712 20.041 42.1788 20.041C45.3864 20.041 47.9246 22.895 47.8741 26.3804C47.8236 29.8658 45.3611 32.7072 42.1788 32.7072Z" fill="white"/>
</svg>'''


def _line(painter: QPainter, *points: tuple[float, float]) -> None:
    for start, end in zip(points, points[1:]):
        painter.drawLine(QPointF(*start), QPointF(*end))


class _LineIconEngine(QIconEngine):
    def __init__(self, name: str, palette: QPalette, extent: int) -> None:
        super().__init__()
        self.name = name
        self.palette = QPalette(palette)
        self.extent = max(12, int(extent))

    def clone(self):
        return _LineIconEngine(self.name, self.palette, self.extent)

    def paint(self, painter, rect, mode, state):
        painter.save()
        extent = min(rect.width(), rect.height(), self.extent)
        painter.translate(rect.x() + (rect.width() - extent) / 2, rect.y() + (rect.height() - extent) / 2)
        _paint_icon(painter, self.name, self.palette, extent)
        painter.restore()

    def pixmap(self, size, mode, state):
        return self.scaledPixmap(size, mode, state, 1.0)

    def scaledPixmap(self, size, mode, state, scale):
        pixmap = QPixmap(QSize(max(1, ceil(size.width() * scale)), max(1, ceil(size.height() * scale))))
        pixmap.setDevicePixelRatio(scale)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return pixmap


def compact_line_icon(name: str, palette: QPalette, *, size: int = 18) -> QIcon:
    """Rasterize vector artwork at the requesting window's device pixel ratio."""
    return QIcon(_LineIconEngine(name, palette, size))


def _paint_icon(painter: QPainter, name: str, palette: QPalette, extent: int) -> None:
    painter.setRenderHint(QPainter.Antialiasing, True)
    color = palette.color(QPalette.ColorRole.ButtonText)
    accent = palette.color(QPalette.ColorRole.Highlight)
    pen = QPen(color, 18.0 / 13.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
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
    elif key == "discord":
        background = palette.color(QPalette.ColorRole.Window)
        channels = (background.redF(), background.greenF(), background.blueF())
        linear = (value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels)
        luminance = sum(weight * value for weight, value in zip((0.2126, 0.7152, 0.0722), linear))
        ink = b"black" if luminance > 0.179 else b"white"
        QSvgRenderer(_DISCORD_SYMBOL.replace(b'fill="white"', b'fill="' + ink + b'"')).render(
            painter, QRectF(1, 3, 16, 12)
        )
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
    elif key == "bug":
        head = QPainterPath(QPointF(6.5, 6))
        head.cubicTo(6.5, 2.5, 11.5, 2.5, 11.5, 6)
        painter.drawPath(head)
        painter.drawRoundedRect(QRectF(5, 6, 8, 10), 2.5, 2.5)
        _line(painter, (7.2, 3.9), (5.5, 2))
        _line(painter, (10.8, 3.9), (12.5, 2))
        _line(painter, (9, 8), (9, 15.5))
        _line(painter, (5, 8), (3.5, 6.5), (2, 6.5))
        _line(painter, (13, 8), (14.5, 6.5), (16, 6.5))
        _line(painter, (5, 11), (2, 11))
        _line(painter, (13, 11), (16, 11))
        _line(painter, (5.5, 14), (3.5, 15.5), (2, 15.5))
        _line(painter, (12.5, 14), (14.5, 15.5), (16, 15.5))
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

__all__ = ["compact_line_icon"]
