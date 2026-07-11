"""Small Qt-drawn icons for Mesh Editor tools."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication


def mesh_editor_action_icon(icon_key: str, palette: QPalette | None = None) -> QIcon:
    key = str(icon_key or "").strip().lower()
    app = QApplication.instance()
    resolved_palette = QPalette(palette or (app.palette() if app is not None else QPalette()))
    primary = QColor(resolved_palette.color(QPalette.ButtonText))
    accent = QColor(resolved_palette.color(QPalette.Highlight))
    subtle = QColor(resolved_palette.color(QPalette.PlaceholderText))
    if not subtle.isValid() or subtle.alpha() == 0:
        subtle = QColor(primary)
        subtle.setAlpha(150)
    accent.setAlpha(220)
    return _render_mesh_editor_action_icon(key, primary.rgba(), accent.rgba(), subtle.rgba())


@lru_cache(maxsize=256)
def _render_mesh_editor_action_icon(
    key: str,
    primary_rgba: int,
    accent_rgba: int,
    subtle_rgba: int,
) -> QIcon:
    primary = QColor.fromRgba(primary_rgba)
    accent = QColor.fromRgba(accent_rgba)
    subtle = QColor.fromRgba(subtle_rgba)
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(_icon_pen(primary))

    if not _draw_selection_transform_icon(painter, key, primary, accent):
        if not _draw_brush_icon(painter, key, primary, accent, subtle):
            if not _draw_mesh_operation_icon(painter, key, primary, accent):
                _draw_general_icon(painter, key, primary, accent, subtle)

    painter.end()
    return QIcon(pixmap)


def _icon_pen(color: QColor, width: float = 1.7) -> QPen:
    item = QPen(color, width)
    item.setCapStyle(Qt.RoundCap)
    item.setJoinStyle(Qt.RoundJoin)
    return item


def _draw_selection_transform_icon(
    painter: QPainter,
    key: str,
    primary: QColor,
    accent: QColor,
) -> bool:
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
        painter.setBrush(QBrush(accent))
        painter.drawPath(_triangle_path())
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
    else:
        return False
    return True


def _draw_brush_icon(
    painter: QPainter,
    key: str,
    primary: QColor,
    accent: QColor,
    subtle: QColor,
) -> bool:
    if key == "brush_grab":
        painter.drawLine(5, 15, 13, 7)
        painter.setBrush(QBrush(accent))
        painter.drawEllipse(12, 4, 4, 5)
        painter.setPen(_icon_pen(primary, 1.4))
        painter.drawLine(7, 5, 7, 11)
        painter.drawLine(4, 8, 10, 8)
        painter.drawLine(7, 5, 5, 7)
        painter.drawLine(7, 5, 9, 7)
    elif key == "brush_smooth":
        painter.setPen(_icon_pen(subtle, 1.4))
        painter.drawLine(4, 14, 7, 10)
        painter.drawLine(7, 10, 10, 14)
        painter.drawLine(10, 14, 13, 10)
        painter.drawLine(13, 10, 16, 14)
        painter.setPen(_icon_pen(accent, 2.0))
        painter.drawLine(4, 7, 16, 7)
    elif key == "brush_inflate":
        painter.setBrush(QBrush(subtle))
        painter.drawEllipse(7, 7, 6, 6)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(_icon_pen(accent, 1.6))
        for line in (
            (10, 3, 10, 6), (10, 3, 8, 5), (10, 3, 12, 5),
            (10, 17, 10, 14), (10, 17, 8, 15), (10, 17, 12, 15),
            (3, 10, 6, 10), (3, 10, 5, 8), (3, 10, 5, 12),
            (17, 10, 14, 10), (17, 10, 15, 8), (17, 10, 15, 12),
        ):
            painter.drawLine(*line)
    elif key == "brush_pinch":
        painter.setBrush(QBrush(subtle))
        painter.drawEllipse(8, 8, 4, 4)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(_icon_pen(accent, 1.7))
        for line in (
            (4, 10, 8, 10), (8, 10, 6, 8), (8, 10, 6, 12),
            (16, 10, 12, 10), (12, 10, 14, 8), (12, 10, 14, 12),
            (10, 4, 10, 8), (10, 8, 8, 6), (10, 8, 12, 6),
            (10, 16, 10, 12), (10, 12, 8, 14), (10, 12, 12, 14),
        ):
            painter.drawLine(*line)
    elif key.startswith("brush"):
        painter.drawLine(5, 15, 13, 7)
        painter.setBrush(QBrush(accent))
        painter.drawEllipse(12, 4, 4, 5)
    else:
        return False
    return True


def _draw_mesh_operation_icon(
    painter: QPainter,
    key: str,
    primary: QColor,
    accent: QColor,
) -> bool:
    if key == "delete":
        painter.drawPath(_triangle_path())
        painter.setPen(_icon_pen(accent, 2.0))
        painter.drawLine(6, 6, 14, 14)
        painter.drawLine(14, 6, 6, 14)
    elif key == "subdivide":
        painter.drawRect(4, 4, 12, 12)
        painter.setPen(_icon_pen(accent, 1.4))
        painter.drawLine(10, 4, 10, 16)
        painter.drawLine(4, 10, 16, 10)
        painter.drawLine(4, 4, 16, 16)
    elif key == "refine_smooth":
        painter.drawRect(4, 5, 12, 9)
        painter.setPen(_icon_pen(accent, 1.3))
        painter.drawLine(10, 5, 10, 14)
        painter.drawLine(4, 9, 16, 9)
        painter.setPen(_icon_pen(primary, 1.7))
        painter.drawLine(4, 17, 8, 15)
        painter.drawLine(8, 15, 12, 17)
        painter.drawLine(12, 17, 16, 15)
    elif key == "split":
        left, right = _triangle_path(), _triangle_path()
        left.translate(-3, 0)
        right.translate(3, 0)
        painter.drawPath(left)
        painter.drawPath(right)
        painter.setPen(_icon_pen(accent, 1.6))
        painter.drawLine(10, 5, 10, 15)
    elif key in {"recalculate_normals", "weighted_normals", "flip_normals"}:
        _draw_normal_operation_icon(painter, key, primary, accent)
    else:
        return False
    return True


def _draw_normal_operation_icon(
    painter: QPainter,
    key: str,
    primary: QColor,
    accent: QColor,
) -> None:
    if key == "weighted_normals":
        painter.setPen(_icon_pen(primary, 1.5))
    painter.drawPath(_triangle_path())
    if key == "weighted_normals":
        painter.setPen(_icon_pen(accent, 2.8))
        painter.drawLine(10, 12, 10, 3)
        painter.drawLine(10, 3, 8, 5)
        painter.drawLine(10, 3, 12, 5)
        painter.setBrush(QBrush(accent))
        painter.drawEllipse(7, 13, 6, 4)
    elif key == "flip_normals":
        painter.setPen(_icon_pen(accent, 1.6))
        for line in ((7, 4, 7, 11), (7, 11, 5, 9), (7, 11, 9, 9), (13, 15, 13, 8), (13, 8, 11, 10), (13, 8, 15, 10)):
            painter.drawLine(*line)
    else:
        painter.setPen(_icon_pen(accent, 1.7))
        painter.drawLine(10, 11, 10, 3)
        painter.drawLine(10, 3, 8, 5)
        painter.drawLine(10, 3, 12, 5)


def _draw_general_icon(
    painter: QPainter,
    key: str,
    primary: QColor,
    accent: QColor,
    subtle: QColor,
) -> None:
    if key in {"undo", "redo"}:
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
        painter.setPen(_icon_pen(accent))
        if "flip_u" in key:
            for line in ((10, 5, 10, 15), (5, 10, 15, 10), (5, 10, 7, 8), (15, 10, 13, 8)):
                painter.drawLine(*line)
        elif "flip_v" in key:
            for line in ((5, 10, 15, 10), (10, 5, 10, 15), (10, 5, 8, 7), (10, 15, 8, 13)):
                painter.drawLine(*line)
        else:
            painter.drawLine(4, 16, 16, 4)
    elif "normal" in key:
        painter.drawPath(_triangle_path())
        painter.setPen(_icon_pen(accent))
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
        painter.setPen(_icon_pen(accent))
        painter.drawLine(5, 14, 15, 14)
        painter.drawLine(10, 5, 10, 14)


def _triangle_path() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(10, 4)
    path.lineTo(16, 15)
    path.lineTo(4, 15)
    path.closeSubpath()
    return path


__all__ = ["mesh_editor_action_icon"]
