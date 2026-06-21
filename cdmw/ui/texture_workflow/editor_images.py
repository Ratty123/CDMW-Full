from __future__ import annotations

"""Image and icon helpers for the standalone Texture Editor UI."""

from typing import Optional

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QImage, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication

from cdmw.core.texture_editor import build_texture_editor_selection_mask
from cdmw.models import TextureEditorDocument


def _rgba_array_to_qimage(array: np.ndarray) -> QImage:
    rgba = np.ascontiguousarray(array, dtype=np.uint8)
    height, width = rgba.shape[:2]
    image = QImage(rgba.data, width, height, width * 4, QImage.Format_RGBA8888)
    return image.copy()


def texture_editor_quick_mask_overlay_image(document: TextureEditorDocument) -> Optional[QImage]:
    if not document.quick_mask_enabled:
        return None
    quick_mask = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    if quick_mask is None or not np.any(quick_mask > 0):
        return None
    overlay = np.zeros((document.height, document.width, 4), dtype=np.uint8)
    overlay[..., 0] = 235
    overlay[..., 1] = 70
    overlay[..., 2] = 90
    overlay[..., 3] = np.clip(np.round(quick_mask.astype(np.float32) * 0.32), 0.0, 255.0).astype(np.uint8)
    return _rgba_array_to_qimage(overlay)


def texture_editor_layer_thumbnail_preview_pixels(pixels: Optional[np.ndarray]) -> Optional[np.ndarray]:
    if pixels is None or pixels.size == 0:
        return None
    alpha = pixels[..., 3]
    ys, xs = np.where(alpha > 0)
    if xs.size > 0 and ys.size > 0:
        x0 = max(0, int(xs.min()))
        y0 = max(0, int(ys.min()))
        x1 = int(xs.max()) + 1
        y1 = int(ys.max()) + 1
        return pixels[y0:y1, x0:x1]
    return pixels


def _create_tool_icon(tool_key: str, palette: Optional[QPalette] = None) -> QIcon:
    size = 20
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    app = QApplication.instance()
    resolved_palette = QPalette(palette or (app.palette() if app is not None else QPalette()))
    accent = QColor(resolved_palette.color(QPalette.Highlight))
    primary = QColor(resolved_palette.color(QPalette.ButtonText))
    subtle = QColor(resolved_palette.color(QPalette.PlaceholderText))
    if not subtle.isValid() or subtle.alpha() == 0:
        subtle = QColor(primary)
        subtle.setAlpha(170)
    accent.setAlpha(230)

    def _pen(color: QColor, width: float = 1.8, *, dashed: bool = False) -> QPen:
        pen = QPen(color, width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        if dashed:
            pen.setStyle(Qt.DashLine)
        return pen

    painter.setBrush(Qt.NoBrush)
    if tool_key == "paint":
        painter.setPen(_pen(primary, 2.0))
        painter.drawLine(4, 15, 12, 7)
        painter.setBrush(QBrush(accent))
        painter.setPen(_pen(accent, 1.5))
        painter.drawEllipse(12, 4, 4, 4)
    elif tool_key == "erase":
        painter.setBrush(QBrush(accent))
        painter.setPen(_pen(primary, 1.6))
        path = QPainterPath()
        path.moveTo(5, 13)
        path.lineTo(10, 6)
        path.lineTo(16, 10)
        path.lineTo(11, 16)
        path.closeSubpath()
        painter.drawPath(path)
    elif tool_key == "sharpen":
        painter.setPen(_pen(primary, 1.8))
        painter.drawLine(10, 3, 10, 17)
        painter.drawLine(3, 10, 17, 10)
        painter.drawLine(5, 5, 15, 15)
        painter.drawLine(15, 5, 5, 15)
    elif tool_key == "soften":
        painter.setPen(_pen(primary, 1.2))
        painter.setBrush(QBrush(accent))
        painter.drawEllipse(5, 5, 10, 10)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(_pen(subtle, 1.2))
        painter.drawEllipse(3, 3, 14, 14)
    elif tool_key == "clone":
        painter.setPen(_pen(primary, 1.6))
        painter.drawEllipse(4, 6, 7, 7)
        painter.drawEllipse(9, 6, 7, 7)
        painter.drawLine(8, 13, 8, 17)
        painter.drawLine(12, 13, 12, 17)
    elif tool_key == "heal":
        painter.setPen(_pen(primary, 1.8))
        painter.drawEllipse(4, 4, 12, 12)
        painter.drawLine(10, 6, 10, 14)
        painter.drawLine(6, 10, 14, 10)
    elif tool_key == "move":
        painter.setPen(_pen(primary, 1.8))
        painter.drawLine(10, 3, 10, 17)
        painter.drawLine(3, 10, 17, 10)
        painter.drawLine(10, 3, 8, 5)
        painter.drawLine(10, 3, 12, 5)
        painter.drawLine(10, 17, 8, 15)
        painter.drawLine(10, 17, 12, 15)
        painter.drawLine(3, 10, 5, 8)
        painter.drawLine(3, 10, 5, 12)
        painter.drawLine(17, 10, 15, 8)
        painter.drawLine(17, 10, 15, 12)
    elif tool_key == "fill":
        painter.setPen(_pen(primary, 1.6))
        bucket = QPainterPath()
        bucket.moveTo(5, 8)
        bucket.lineTo(9, 4)
        bucket.lineTo(15, 10)
        bucket.lineTo(11, 14)
        bucket.closeSubpath()
        painter.setBrush(QBrush(accent))
        painter.drawPath(bucket)
        painter.setBrush(QBrush(QColor("#C6E4FF")))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(11, 13, 5, 3)
    elif tool_key == "gradient":
        painter.setPen(Qt.NoPen)
        gradient_path = QPainterPath()
        gradient_path.moveTo(4, 14)
        gradient_path.lineTo(16, 6)
        painter.setPen(_pen(primary, 1.4))
        painter.drawLine(4, 14, 16, 6)
        painter.setBrush(QBrush(accent))
        painter.drawEllipse(3, 13, 3, 3)
        warm = QColor(accent)
        warm = warm.lighter(130 if primary.lightness() < 160 else 85)
        warm.setAlpha(220)
        painter.setBrush(QBrush(warm))
        painter.drawEllipse(14, 5, 3, 3)
    elif tool_key == "smudge":
        painter.setPen(_pen(primary, 1.5))
        painter.drawLine(4, 15, 9, 10)
        painter.drawLine(9, 10, 14, 12)
        painter.setBrush(QBrush(accent))
        painter.setPen(_pen(accent, 1.3))
        painter.drawEllipse(12, 4, 4, 7)
    elif tool_key == "dodge_burn":
        painter.setPen(_pen(primary, 1.5))
        warm = QColor(accent)
        warm = warm.lighter(140 if primary.lightness() < 160 else 90)
        warm.setAlpha(220)
        painter.setBrush(QBrush(warm))
        painter.drawEllipse(3, 8, 6, 6)
        cool = QColor(subtle)
        cool.setAlpha(220)
        painter.setBrush(QBrush(cool))
        painter.drawEllipse(11, 6, 6, 8)
        painter.setPen(_pen(accent, 1.3))
        painter.drawLine(8, 11, 12, 10)
    elif tool_key == "patch":
        painter.setPen(_pen(primary, 1.4, dashed=True))
        painter.drawRect(3, 4, 7, 7)
        painter.setPen(_pen(accent, 1.4))
        painter.drawLine(10, 7, 15, 12)
        painter.drawRect(11, 11, 5, 5)
    elif tool_key == "select_rect":
        painter.setPen(_pen(primary, 1.5, dashed=True))
        painter.drawRect(4, 4, 12, 10)
    elif tool_key == "lasso":
        painter.setPen(_pen(primary, 1.8))
        path = QPainterPath()
        path.moveTo(5, 8)
        path.cubicTo(4, 2, 16, 2, 15, 9)
        path.cubicTo(14, 15, 7, 16, 7, 12)
        painter.drawPath(path)
        painter.drawLine(7, 12, 10, 17)
    elif tool_key == "recolor":
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("#FF8C7A")))
        painter.drawEllipse(3, 8, 6, 6)
        painter.setBrush(QBrush(QColor("#7CCB7A")))
        painter.drawEllipse(7, 4, 6, 6)
        painter.setBrush(QBrush(QColor("#74C1FF")))
        painter.drawEllipse(11, 8, 6, 6)
    painter.end()
    return QIcon(pixmap)


__all__ = [
    "_create_tool_icon",
    "_rgba_array_to_qimage",
    "texture_editor_layer_thumbnail_preview_pixels",
    "texture_editor_quick_mask_overlay_image",
]
