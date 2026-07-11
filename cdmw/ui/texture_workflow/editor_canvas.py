from __future__ import annotations

"""Canvas widget for the standalone Texture Editor UI."""

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QScrollArea, QSizePolicy, QWidget

from cdmw.models import TextureEditorSelection
from cdmw.ui.texture_workflow.editor_images import _rgba_array_to_qimage


class TextureEditorCanvas(QWidget):
    stroke_committed = Signal(object)
    selection_committed = Signal(object)
    clone_source_picked = Signal(object)
    color_sampled = Signal(str)
    hover_info_changed = Signal(object)
    wheel_zoom_requested = Signal(int, int, int)
    floating_transform_requested = Signal(object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._image: Optional[QImage] = None
        self._edited_rgba: Optional[np.ndarray] = None
        self._original_rgba: Optional[np.ndarray] = None
        self._edited_image: Optional[QImage] = None
        self._original_image: Optional[QImage] = None
        self._display_image: Optional[QImage] = None
        self._channel_rgba: Optional[np.ndarray] = None
        self._channel_image: Optional[QImage] = None
        self._channel_mode = ""
        self._scroll_area: Optional[QScrollArea] = None
        self._fit_to_view = True
        self._zoom_factor = 1.0
        self._display_scale = 1.0
        self._tool = "paint"
        self._brush_size = 32.0
        self._brush_hardness = 80
        self._brush_tip = "round"
        self._brush_roundness = 100
        self._brush_angle = 0
        self._brush_pattern = "solid"
        self._symmetry_mode = "off"
        self._view_mode = "edited"
        self._split_percent = 50
        self._grid_enabled = False
        self._grid_size = 64
        self._grid_color = QColor("#74C1FF")
        self._grid_opacity = 42
        self._guides_enabled = False
        self._vertical_guides: Tuple[int, ...] = ()
        self._horizontal_guides: Tuple[int, ...] = ()
        self._selection = TextureEditorSelection()
        self._floating_bounds: Optional[Tuple[int, int, int, int]] = None
        self._floating_origin_bounds: Optional[Tuple[int, int, int, int]] = None
        self._floating_offset_x = 0
        self._floating_offset_y = 0
        self._floating_scale_x = 1.0
        self._floating_scale_y = 1.0
        self._floating_rotation_degrees = 0.0
        self._quick_mask_image: Optional[QImage] = None
        self._clone_source_point: Optional[Tuple[int, int]] = None
        self._hover_point: Optional[Tuple[int, int]] = None
        self._sample_target = ""
        self._dragging = False
        self._drag_points: List[Tuple[int, int]] = []
        self._rect_origin: Optional[Tuple[int, int]] = None
        self._lasso_points: List[Tuple[float, float]] = []
        self._pan_start = None
        self._last_stroke_point: Optional[Tuple[int, int]] = None
        self._transform_drag_mode = ""
        self._transform_drag_start_point: Optional[Tuple[float, float]] = None
        self._transform_drag_start_bounds: Optional[Tuple[int, int, int, int]] = None
        self._transform_drag_start_origin_bounds: Optional[Tuple[int, int, int, int]] = None
        self._transform_drag_start_offset = (0, 0)
        self._transform_drag_start_scale = (1.0, 1.0)
        self._transform_drag_start_rotation = 0.0
        self.setMouseTracking(True)
        self.setMinimumSize(1, 1)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def _brush_tools(self) -> set[str]:
        return {"paint", "erase", "sharpen", "soften", "clone", "heal", "smudge", "dodge_burn"}

    def attach_scroll_area(self, scroll_area: QScrollArea) -> None:
        self._scroll_area = scroll_area
        scroll_area.viewport().installEventFilter(self)
        self._update_display_geometry()

    def eventFilter(self, watched, event):  # type: ignore[override]
        if (
            self._scroll_area is not None
            and watched is self._scroll_area.viewport()
        ):
            if event.type() == QEvent.Type.Resize:
                self._update_display_geometry()
            elif event.type() == QEvent.Type.Wheel and self._image is not None:
                delta = int(event.angleDelta().y())
                if delta == 0:
                    delta = int(event.pixelDelta().y())
                if delta == 0:
                    return super().eventFilter(watched, event)
                viewport_pos = event.position().toPoint()
                canvas_pos = self.mapFrom(self._scroll_area.viewport(), viewport_pos)
                clamped = self._clamp_widget_point_to_image(canvas_pos)
                if clamped is not None:
                    self.wheel_zoom_requested.emit(int(delta), int(clamped.x()), int(clamped.y()))
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

    def _display_target_rect(self) -> QRect:
        if self._image is None:
            return QRect()
        width = max(1, int(round(self._image.width() * self._display_scale)))
        height = max(1, int(round(self._image.height() * self._display_scale)))
        return QRect(0, 0, width, height)

    def set_image(self, image: Optional[QImage]) -> None:
        self._edited_rgba = None
        self._original_rgba = None
        self._channel_rgba = None
        self._channel_image = None
        self._channel_mode = ""
        self._edited_image = image.copy() if image is not None else None
        self._original_image = None
        self._image = image.copy() if image is not None else None
        self._display_image = self._image.copy() if self._image is not None else None
        self._update_display_geometry()
        self.update()

    def set_rgba_images(
        self,
        edited_rgba: Optional[np.ndarray],
        *,
        original_rgba: Optional[np.ndarray] = None,
        dirty_bounds: Optional[Tuple[int, int, int, int]] = None,
    ) -> None:
        edited = np.ascontiguousarray(edited_rgba, dtype=np.uint8) if edited_rgba is not None else None
        original = np.ascontiguousarray(original_rgba, dtype=np.uint8) if original_rgba is not None else None
        edited_reused = edited is not None and edited is self._edited_rgba and self._edited_image is not None
        original_reused = original is not None and original is self._original_rgba and self._original_image is not None
        self._edited_rgba = edited
        self._original_rgba = original
        if not edited_reused:
            self._edited_image = _rgba_array_to_qimage(edited, copy=False) if edited is not None else None
            self._channel_rgba = None
            self._channel_image = None
            self._channel_mode = ""
        if not original_reused:
            self._original_image = _rgba_array_to_qimage(original, copy=False) if original is not None else None
        self._refresh_display_image(dirty_bounds=dirty_bounds if edited_reused else None)

    def set_view_mode(self, mode: str) -> None:
        normalized = (mode or "edited").strip().lower()
        if normalized == self._view_mode:
            return
        self._view_mode = normalized
        self._refresh_display_image()

    def set_compare_split_percent(self, percent: int) -> None:
        percent = max(5, min(95, int(percent)))
        if percent == self._split_percent:
            return
        self._split_percent = percent
        self.update()

    def set_grid_state(
        self,
        *,
        enabled: bool,
        grid_size: int,
        grid_color: Optional[QColor] = None,
        grid_opacity: int = 42,
    ) -> None:
        next_enabled = bool(enabled)
        next_size = max(2, int(grid_size))
        next_color = QColor(grid_color) if grid_color is not None and grid_color.isValid() else QColor(self._grid_color)
        next_opacity = max(5, min(100, int(grid_opacity)))
        if (
            next_enabled == self._grid_enabled
            and next_size == self._grid_size
            and next_color == self._grid_color
            and next_opacity == self._grid_opacity
        ):
            return
        self._grid_enabled = next_enabled
        self._grid_size = next_size
        if grid_color is not None and grid_color.isValid():
            self._grid_color = next_color
        self._grid_opacity = next_opacity
        self.update()

    def set_guide_state(
        self,
        *,
        enabled: bool,
        vertical_guides: Sequence[int],
        horizontal_guides: Sequence[int],
    ) -> None:
        self._guides_enabled = bool(enabled)
        self._vertical_guides = tuple(max(0, int(value)) for value in vertical_guides)
        self._horizontal_guides = tuple(max(0, int(value)) for value in horizontal_guides)
        self.update()

    def set_symmetry_mode(self, mode: str) -> None:
        normalized = (mode or "off").strip().lower()
        if normalized == self._symmetry_mode:
            return
        self._symmetry_mode = normalized
        self.update()

    def _build_channel_qimage(
        self,
        channel_key: str,
        *,
        dirty_bounds: Optional[Tuple[int, int, int, int]] = None,
    ) -> Optional[QImage]:
        rgba = self._edited_rgba
        if rgba is None:
            return None
        channel_index = {"red": 0, "green": 1, "blue": 2}.get(channel_key, 3)
        reusable = (
            self._channel_mode == channel_key
            and self._channel_rgba is not None
            and self._channel_rgba.shape == rgba.shape
            and self._channel_image is not None
        )
        if not reusable:
            self._channel_rgba = np.empty_like(rgba)
            self._channel_image = _rgba_array_to_qimage(self._channel_rgba, copy=False)
            self._channel_mode = channel_key
            dirty_bounds = None
        if dirty_bounds is None:
            source = rgba[..., channel_index]
            target = self._channel_rgba
        else:
            x, y, width, height = (int(value) for value in dirty_bounds)
            left = max(0, x)
            top = max(0, y)
            right = min(rgba.shape[1], x + max(0, width))
            bottom = min(rgba.shape[0], y + max(0, height))
            if right <= left or bottom <= top:
                return self._channel_image
            source = rgba[top:bottom, left:right, channel_index]
            target = self._channel_rgba[top:bottom, left:right]
        target[..., :3] = source[..., None]
        target[..., 3] = 255
        return self._channel_image

    def _refresh_display_image(
        self,
        *,
        dirty_bounds: Optional[Tuple[int, int, int, int]] = None,
    ) -> None:
        previous_size = (
            (self._image.width(), self._image.height())
            if self._image is not None
            else None
        )
        self._image = self._edited_image
        if self._edited_image is None:
            self._display_image = None
            self._update_display_geometry()
            self.update()
            return
        mode = self._view_mode
        if mode == "original" and self._original_image is not None:
            self._display_image = self._original_image
        elif mode in {"red", "green", "blue", "alpha"}:
            self._display_image = self._build_channel_qimage(mode, dirty_bounds=dirty_bounds)
        else:
            self._display_image = self._edited_image
        current_size = (self._image.width(), self._image.height())
        if current_size != previous_size:
            self._update_display_geometry()
        else:
            self._update_dirty_image_region(dirty_bounds)

    def _update_dirty_image_region(
        self,
        dirty_bounds: Optional[Tuple[int, int, int, int]],
    ) -> None:
        if dirty_bounds is None or self._view_mode == "original":
            self.update()
            return
        x, y, width, height = (int(value) for value in dirty_bounds)
        if width <= 0 or height <= 0:
            return
        scale = max(0.0001, float(self._display_scale))
        left = int(math.floor(x * scale)) - 2
        top = int(math.floor(y * scale)) - 2
        right = int(math.ceil((x + width) * scale)) + 2
        bottom = int(math.ceil((y + height) * scale)) + 2
        self.update(QRect(left, top, max(1, right - left), max(1, bottom - top)))

    def set_tool(self, tool: str) -> None:
        self._tool = tool
        if tool not in self._brush_tools():
            self._last_stroke_point = None
        self.update()

    def set_brush_size(self, size: float) -> None:
        self._brush_size = max(0.25, float(size))
        self.update()

    def set_brush_visual_state(
        self,
        *,
        hardness: int,
        tip: str,
        roundness: int,
        angle_degrees: int,
        pattern: str,
    ) -> None:
        self._brush_hardness = max(0, min(100, int(hardness)))
        self._brush_tip = str(tip or "round")
        self._brush_roundness = max(10, min(100, int(roundness)))
        self._brush_angle = int(angle_degrees)
        self._brush_pattern = str(pattern or "solid")
        self.update()

    def _draw_brush_outline(self, painter: QPainter, center_x: float, center_y: float) -> None:
        diameter = max(1.0, float(self._brush_size) * self._display_scale)
        radius = diameter / 2.0
        roundness_ratio = max(0.15, min(1.0, float(self._brush_roundness) / 100.0))
        width = diameter * roundness_ratio
        height = diameter
        painter.save()
        painter.translate(center_x, center_y)
        painter.rotate(float(self._brush_angle))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 210), 1.1))
        tip_key = (self._brush_tip or "round").strip().lower()
        if tip_key == "image_stamp":
            painter.drawRect(QRect(int(round(-width / 2.0)), int(round(-height / 2.0)), max(1, int(round(width))), max(1, int(round(height)))))
            painter.drawLine(int(round(-width / 2.0)), int(round(-height / 2.0)), int(round(width / 2.0)), int(round(height / 2.0)))
            painter.drawLine(int(round(width / 2.0)), int(round(-height / 2.0)), int(round(-width / 2.0)), int(round(height / 2.0)))
        elif tip_key == "square":
            painter.drawRect(QRect(int(round(-width / 2.0)), int(round(-height / 2.0)), max(1, int(round(width))), max(1, int(round(height)))))
        elif tip_key == "diamond":
            path = QPainterPath()
            path.moveTo(0.0, -height / 2.0)
            path.lineTo(width / 2.0, 0.0)
            path.lineTo(0.0, height / 2.0)
            path.lineTo(-width / 2.0, 0.0)
            path.closeSubpath()
            painter.drawPath(path)
        else:
            painter.drawEllipse(
                QRect(
                    int(round(-width / 2.0)),
                    int(round(-height / 2.0)),
                    max(1, int(round(width))),
                    max(1, int(round(height))),
                )
            )
        painter.setPen(QPen(QColor("#74C1FF"), 0.9))
        if tip_key == "image_stamp":
            painter.drawRect(QRect(int(round(-(width + 2.0) / 2.0)), int(round(-(height + 2.0) / 2.0)), max(1, int(round(width + 2.0))), max(1, int(round(height + 2.0)))))
        elif tip_key == "square":
            painter.drawRect(QRect(int(round(-(width + 2.0) / 2.0)), int(round(-(height + 2.0) / 2.0)), max(1, int(round(width + 2.0))), max(1, int(round(height + 2.0)))))
        elif tip_key == "diamond":
            path = QPainterPath()
            path.moveTo(0.0, -(height + 2.0) / 2.0)
            path.lineTo((width + 2.0) / 2.0, 0.0)
            path.lineTo(0.0, (height + 2.0) / 2.0)
            path.lineTo(-(width + 2.0) / 2.0, 0.0)
            path.closeSubpath()
            painter.drawPath(path)
        else:
            painter.drawEllipse(
                QRect(
                    int(round(-(width + 2.0) / 2.0)),
                    int(round(-(height + 2.0) / 2.0)),
                    max(1, int(round(width + 2.0))),
                    max(1, int(round(height + 2.0))),
                )
            )
        painter.restore()

    def _draw_brush_hud(self, painter: QPainter, center_x: float, center_y: float) -> None:
        tip_label = "Stamp" if (self._brush_tip or "").strip().lower() == "image_stamp" else self._brush_tip.title()
        hud_text = f"{max(0.25, self._brush_size):.2f}px  H{self._brush_hardness}%  {tip_label}  R{self._brush_roundness}%  A{self._brush_angle}°"
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(hud_text) + 12
        text_height = metrics.height() + 8
        hud_x = int(round(center_x + 18))
        hud_y = int(round(center_y + 18))
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(18, 22, 30, 210))
        painter.drawRoundedRect(hud_x, hud_y, text_width, text_height, 6, 6)
        painter.setPen(QColor("#E7EDF7"))
        painter.drawText(hud_x + 6, hud_y + text_height - 5, hud_text)
        painter.restore()

    def _emit_hover_info(self, point: Optional[Tuple[int, int]]) -> None:
        if point is None or self._image is None:
            self.hover_info_changed.emit(None)
            return
        if point[0] < 0 or point[1] < 0 or point[0] >= self._image.width() or point[1] >= self._image.height():
            self.hover_info_changed.emit(None)
            return
        pixel = QColor(self._image.pixel(point[0], point[1]))
        self.hover_info_changed.emit(
            {
                "x": int(point[0]),
                "y": int(point[1]),
                "rgba": (
                    int(pixel.red()),
                    int(pixel.green()),
                    int(pixel.blue()),
                    int(pixel.alpha()),
                ),
            }
        )

    def _append_lasso_point(self, point: Tuple[float, float]) -> None:
        if not self._lasso_points:
            self._lasso_points = [point]
            return
        last_x, last_y = self._lasso_points[-1]
        dx = float(point[0] - last_x)
        dy = float(point[1] - last_y)
        if (dx * dx + dy * dy) < 0.16:
            return
        self._lasso_points.append(point)

    def set_selection(self, selection: TextureEditorSelection) -> None:
        if selection == self._selection:
            return
        self._selection = selection
        self.update()

    def set_floating_bounds(self, bounds: Optional[Tuple[int, int, int, int]]) -> None:
        self._floating_bounds = bounds
        if bounds is None:
            self._floating_origin_bounds = None
            self._floating_offset_x = 0
            self._floating_offset_y = 0
            self._floating_scale_x = 1.0
            self._floating_scale_y = 1.0
            self._floating_rotation_degrees = 0.0
            self._transform_drag_mode = ""
        self.update()

    def set_floating_transform_state(
        self,
        *,
        current_bounds: Optional[Tuple[int, int, int, int]],
        origin_bounds: Optional[Tuple[int, int, int, int]],
        offset_x: int,
        offset_y: int,
        scale_x: float,
        scale_y: float,
        rotation_degrees: float,
    ) -> None:
        next_state = (
            current_bounds,
            origin_bounds,
            int(offset_x),
            int(offset_y),
            float(scale_x),
            float(scale_y),
            float(rotation_degrees),
        )
        current_state = (
            self._floating_bounds,
            self._floating_origin_bounds,
            self._floating_offset_x,
            self._floating_offset_y,
            self._floating_scale_x,
            self._floating_scale_y,
            self._floating_rotation_degrees,
        )
        if next_state == current_state:
            return
        self._floating_bounds = current_bounds
        self._floating_origin_bounds = origin_bounds
        self._floating_offset_x = int(offset_x)
        self._floating_offset_y = int(offset_y)
        self._floating_scale_x = float(scale_x)
        self._floating_scale_y = float(scale_y)
        self._floating_rotation_degrees = float(rotation_degrees)
        self.update()

    def set_quick_mask_overlay(self, overlay: Optional[QImage]) -> None:
        if overlay is None and self._quick_mask_image is None:
            return
        self._quick_mask_image = overlay.copy() if overlay is not None else None
        self.update()

    def set_clone_source_point(self, point: Optional[Tuple[int, int]]) -> None:
        if point == self._clone_source_point:
            return
        self._clone_source_point = point
        self.update()

    def set_color_sample_target(self, target: str) -> None:
        self._sample_target = target
        self.setCursor(Qt.CrossCursor if target else Qt.ArrowCursor)

    def current_display_scale(self) -> float:
        return self._display_scale

    def is_fit_to_view(self) -> bool:
        return self._fit_to_view

    def set_fit_to_view(self, fit_to_view: bool) -> None:
        self._fit_to_view = bool(fit_to_view)
        self._update_display_geometry()

    def set_zoom_factor(self, factor: float) -> None:
        self._fit_to_view = False
        self._zoom_factor = max(0.05, min(32.0, float(factor)))
        self._update_display_geometry()

    def _update_display_geometry(self) -> None:
        if self._image is None:
            if self._scroll_area is not None:
                viewport = self._scroll_area.viewport().size()
                self.resize(max(280, viewport.width() - 12), max(220, viewport.height() - 12))
            else:
                self.resize(420, 300)
            self._display_scale = 1.0
            self.update()
            return
        width = max(1, self._image.width())
        height = max(1, self._image.height())
        if self._fit_to_view and self._scroll_area is not None:
            viewport = self._scroll_area.viewport().size()
            usable_w = max(1, viewport.width() - 12)
            usable_h = max(1, viewport.height() - 12)
            scale = min(usable_w / width, usable_h / height)
            self._display_scale = max(0.05, min(32.0, scale))
        else:
            self._display_scale = max(0.05, min(32.0, self._zoom_factor))
        target = self._display_target_rect()
        self.resize(max(1, target.width()), max(1, target.height()))
        self.update()

    def _widget_to_image_point(self, pos) -> Optional[Tuple[int, int]]:
        if self._image is None:
            return None
        scale = max(0.0001, self._display_scale)
        x = int(pos.x() / scale)
        y = int(pos.y() / scale)
        if x < 0 or y < 0 or x >= self._image.width() or y >= self._image.height():
            return None
        return (x, y)

    def _widget_to_image_point_float(self, pos) -> Optional[Tuple[float, float]]:
        if self._image is None:
            return None
        scale = max(0.0001, self._display_scale)
        x = float(pos.x()) / scale
        y = float(pos.y()) / scale
        if x < 0.0 or y < 0.0 or x >= float(self._image.width()) or y >= float(self._image.height()):
            return None
        max_x = max(0.0, float(self._image.width()) - 0.001)
        max_y = max(0.0, float(self._image.height()) - 0.001)
        return (min(max_x, x), min(max_y, y))

    def _clamp_widget_point_to_image(self, pos) -> Optional[QPoint]:
        if self._image is None:
            return None
        if self.width() <= 0 or self.height() <= 0:
            return None
        clamped_x = min(max(int(round(pos.x())), 0), max(0, self.width() - 1))
        clamped_y = min(max(int(round(pos.y())), 0), max(0, self.height() - 1))
        return QPoint(clamped_x, clamped_y)

    def _sample_color(self, point: Tuple[int, int]) -> str:
        if self._image is None:
            return "#000000"
        pixel = QColor(self._image.pixel(point[0], point[1]))
        return pixel.name().upper()

    def _floating_handle_rects(self) -> Dict[str, QRectF]:
        if self._floating_bounds is None:
            return {}
        x, y, width, height = self._floating_bounds
        scale = max(0.0001, self._display_scale)
        widget_x = float(x) * scale
        widget_y = float(y) * scale
        widget_w = max(1.0, float(width) * scale)
        widget_h = max(1.0, float(height) * scale)
        handle_size = max(10.0, min(16.0, max(10.0, scale * 0.75)))
        half = handle_size / 2.0
        left = widget_x
        right = widget_x + widget_w
        top = widget_y
        bottom = widget_y + widget_h
        center_x = widget_x + (widget_w / 2.0)
        rotate_y = top - max(18.0, handle_size * 1.6)
        return {
            "scale_nw": QRectF(left - half, top - half, handle_size, handle_size),
            "scale_ne": QRectF(right - half, top - half, handle_size, handle_size),
            "scale_sw": QRectF(left - half, bottom - half, handle_size, handle_size),
            "scale_se": QRectF(right - half, bottom - half, handle_size, handle_size),
            "rotate": QRectF(center_x - half, rotate_y - half, handle_size, handle_size),
        }

    def _floating_transform_hit(self, pos) -> Optional[str]:
        if self._floating_bounds is None:
            return None
        point = QPoint(int(round(pos.x())), int(round(pos.y())))
        for name, rect in self._floating_handle_rects().items():
            if rect.contains(pos):
                return name
        scale = max(0.0001, self._display_scale)
        x, y, width, height = self._floating_bounds
        widget_rect = QRectF(float(x) * scale, float(y) * scale, max(1.0, float(width) * scale), max(1.0, float(height) * scale))
        if widget_rect.contains(pos):
            return "move"
        return None

    def _cursor_for_floating_hit(self, hit: Optional[str]):
        if hit == "move":
            return Qt.SizeAllCursor
        if hit in {"scale_nw", "scale_se"}:
            return Qt.SizeFDiagCursor
        if hit in {"scale_ne", "scale_sw"}:
            return Qt.SizeBDiagCursor
        if hit == "rotate":
            return Qt.CrossCursor
        return Qt.ArrowCursor

    def _clamped_image_point_float(self, pos) -> Optional[Tuple[float, float]]:
        if self._image is None:
            return None
        precise = self._widget_to_image_point_float(pos)
        if precise is not None:
            return precise
        clamped = self._clamp_widget_point_to_image(pos.toPoint())
        if clamped is None:
            return None
        scale = max(0.0001, self._display_scale)
        max_x = max(0.0, float(self._image.width()) - 0.001)
        max_y = max(0.0, float(self._image.height()) - 0.001)
        return (
            min(max_x, max(0.0, float(clamped.x()) / scale)),
            min(max_y, max(0.0, float(clamped.y()) / scale)),
        )

    def _build_floating_transform_payload(self, current_point: Tuple[float, float], *, commit: bool) -> Optional[Dict[str, object]]:
        if (
            not self._transform_drag_mode
            or self._transform_drag_start_point is None
            or self._transform_drag_start_bounds is None
            or self._transform_drag_start_origin_bounds is None
        ):
            return None
        mode = self._transform_drag_mode
        start_point = self._transform_drag_start_point
        start_x, start_y, start_w, start_h = self._transform_drag_start_bounds
        origin_x, origin_y, _origin_w, _origin_h = self._transform_drag_start_origin_bounds
        payload: Dict[str, object] = {
            "mode": mode,
            "commit": bool(commit),
            "offset_x": int(self._transform_drag_start_offset[0]),
            "offset_y": int(self._transform_drag_start_offset[1]),
            "scale_x": float(self._transform_drag_start_scale[0]),
            "scale_y": float(self._transform_drag_start_scale[1]),
            "rotation_degrees": float(self._transform_drag_start_rotation),
        }
        if mode == "move":
            payload["offset_x"] = int(round(self._transform_drag_start_offset[0] + (current_point[0] - start_point[0])))
            payload["offset_y"] = int(round(self._transform_drag_start_offset[1] + (current_point[1] - start_point[1])))
            return payload
        if mode.startswith("scale_"):
            anchor_x = float(start_x)
            anchor_y = float(start_y)
            if mode == "scale_nw":
                anchor_x = float(start_x + start_w)
                anchor_y = float(start_y + start_h)
            elif mode == "scale_ne":
                anchor_x = float(start_x)
                anchor_y = float(start_y + start_h)
            elif mode == "scale_sw":
                anchor_x = float(start_x + start_w)
                anchor_y = float(start_y)
            current_width = max(1.0, abs(anchor_x - current_point[0]))
            current_height = max(1.0, abs(anchor_y - current_point[1]))
            factor = max(current_width / max(1.0, float(start_w)), current_height / max(1.0, float(start_h)))
            factor = max(0.05, min(8.0, factor))
            next_w = max(1.0, float(start_w) * factor)
            next_h = max(1.0, float(start_h) * factor)
            if mode == "scale_nw":
                next_x = anchor_x - next_w
                next_y = anchor_y - next_h
            elif mode == "scale_ne":
                next_x = anchor_x
                next_y = anchor_y - next_h
            elif mode == "scale_sw":
                next_x = anchor_x - next_w
                next_y = anchor_y
            else:
                next_x = anchor_x
                next_y = anchor_y
            payload["offset_x"] = int(round(next_x - float(origin_x)))
            payload["offset_y"] = int(round(next_y - float(origin_y)))
            payload["scale_x"] = float(self._transform_drag_start_scale[0] * factor)
            payload["scale_y"] = float(self._transform_drag_start_scale[1] * factor)
            return payload
        if mode == "rotate":
            center_x = float(start_x) + (float(start_w) / 2.0)
            center_y = float(start_y) + (float(start_h) / 2.0)
            start_angle = math.degrees(math.atan2(start_point[1] - center_y, start_point[0] - center_x))
            current_angle = math.degrees(math.atan2(current_point[1] - center_y, current_point[0] - center_x))
            payload["rotation_degrees"] = float(self._transform_drag_start_rotation + (current_angle - start_angle))
            return payload
        return None

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#222733"))
        if self._image is None or self._display_image is None:
            painter.setPen(QColor("#9CA6B8"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Open a texture to start editing.")
            return
        target_rect = self._display_target_rect()
        if target_rect.isEmpty():
            return
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if self._view_mode == "split" and self._original_image is not None and self._edited_image is not None:
            split_ratio = max(0.05, min(0.95, float(self._split_percent) / 100.0))
            split_x = int(round(target_rect.width() * split_ratio))
            source_split_x = int(round(self._edited_image.width() * split_ratio))
            if split_x > 0 and source_split_x > 0:
                painter.drawImage(
                    target_rect.adjusted(0, 0, -(target_rect.width() - split_x), 0),
                    self._original_image,
                    self._original_image.rect().adjusted(0, 0, -(self._original_image.width() - source_split_x), 0),
                )
            if split_x < target_rect.width() and source_split_x < self._edited_image.width():
                painter.drawImage(
                    target_rect.adjusted(split_x, 0, 0, 0),
                    self._edited_image,
                    self._edited_image.rect().adjusted(source_split_x, 0, 0, 0),
                )
            painter.setPen(QPen(QColor("#8ED0FF"), 2))
            painter.drawLine(split_x, 0, split_x, target_rect.height())
        else:
            painter.drawImage(target_rect, self._display_image)
        if self._quick_mask_image is not None:
            painter.drawImage(target_rect, self._quick_mask_image)
        if self._grid_enabled and self._grid_size > 1:
            grid_step = float(self._grid_size) * max(0.01, self._display_scale)
            if grid_step >= 6.0:
                base_color = QColor(self._grid_color if self._grid_color.isValid() else QColor("#74C1FF"))
                opacity_ratio = max(0.05, min(1.0, float(self._grid_opacity) / 100.0))
                minor_color = QColor(base_color)
                major_color = QColor(base_color)
                minor_color.setAlpha(max(8, int(round(255.0 * opacity_ratio * 0.38))))
                major_color.setAlpha(max(minor_color.alpha() + 12, int(round(255.0 * opacity_ratio * 0.72))))
                minor_pen = QPen(minor_color, 1)
                major_pen = QPen(major_color, 1)
                x = grid_step
                line_index = 1
                while x < target_rect.width():
                    painter.setPen(major_pen if (line_index % 4 == 0) else minor_pen)
                    painter.drawLine(int(round(x)), 0, int(round(x)), target_rect.height())
                    x += grid_step
                    line_index += 1
                y = grid_step
                line_index = 1
                while y < target_rect.height():
                    painter.setPen(major_pen if (line_index % 4 == 0) else minor_pen)
                    painter.drawLine(0, int(round(y)), target_rect.width(), int(round(y)))
                    y += grid_step
                    line_index += 1
        if self._guides_enabled:
            guide_pen = QPen(QColor(116, 193, 255, 165), 1)
            guide_pen.setStyle(Qt.DashLine)
            painter.setPen(guide_pen)
            for guide_x in self._vertical_guides:
                x = int(round(float(guide_x) * max(0.01, self._display_scale)))
                painter.drawLine(x, 0, x, target_rect.height())
            for guide_y in self._horizontal_guides:
                y = int(round(float(guide_y) * max(0.01, self._display_scale)))
                painter.drawLine(0, y, target_rect.width(), y)
        if self._symmetry_mode != "off":
            symmetry_pen = QPen(QColor(116, 193, 255, 110), 1)
            symmetry_pen.setStyle(Qt.DashLine)
            painter.setPen(symmetry_pen)
            if self._symmetry_mode in {"horizontal", "both"}:
                guide_x = int(round((self._image.width() * 0.5) * max(0.01, self._display_scale)))
                painter.drawLine(guide_x, 0, guide_x, target_rect.height())
            if self._symmetry_mode in {"vertical", "both"}:
                guide_y = int(round((self._image.height() * 0.5) * max(0.01, self._display_scale)))
                painter.drawLine(0, guide_y, target_rect.width(), guide_y)
        scale = self._display_scale
        painter.setRenderHint(QPainter.Antialiasing, True)
        selection_pen = QPen(QColor("#69B8FF"))
        selection_pen.setStyle(Qt.DashLine)
        selection_pen.setWidth(2)
        painter.setPen(selection_pen)
        if self._selection.mask_polygons:
            for polygon_points in self._selection.mask_polygons:
                if len(polygon_points) < 3:
                    continue
                path = QPainterPath()
                first = polygon_points[0]
                path.moveTo(first[0] * scale, first[1] * scale)
                for point in polygon_points[1:]:
                    path.lineTo(point[0] * scale, point[1] * scale)
                path.closeSubpath()
                painter.drawPath(path)
        elif self._selection.mode == "rect" and self._selection.rect is not None:
            x, y, w, h = self._selection.rect
            painter.drawRect(int(x * scale), int(y * scale), int(w * scale), int(h * scale))
        elif self._selection.mode == "lasso" and self._selection.polygon_points:
            path = QPainterPath()
            first = self._selection.polygon_points[0]
            path.moveTo(first[0] * scale, first[1] * scale)
            for point in self._selection.polygon_points[1:]:
                path.lineTo(point[0] * scale, point[1] * scale)
            path.closeSubpath()
            painter.drawPath(path)
        overlay_pen = QPen(QColor("#F8D25C"))
        overlay_pen.setWidth(2)
        painter.setPen(overlay_pen)
        if self._drag_points and self._tool in {"paint", "erase", "sharpen", "soften", "clone", "heal"}:
            overlay_path = QPainterPath()
            first = self._drag_points[0]
            overlay_path.moveTo(first[0] * scale, first[1] * scale)
            for point in self._drag_points[1:]:
                overlay_path.lineTo(point[0] * scale, point[1] * scale)
            brush_width = max(1.0, float(self._brush_size) * scale)
            fill_color = {
                "paint": QColor(116, 193, 255, 58),
                "erase": QColor(255, 118, 118, 52),
                "sharpen": QColor(255, 212, 92, 56),
                "soften": QColor(134, 196, 255, 52),
                "clone": QColor(104, 236, 194, 48),
                "heal": QColor(104, 236, 194, 48),
            }.get(self._tool, QColor(255, 212, 92, 52))
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(fill_color, brush_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            if len(self._drag_points) == 1:
                painter.drawEllipse(
                    int(round((first[0] * scale) - (brush_width / 2.0))),
                    int(round((first[1] * scale) - (brush_width / 2.0))),
                    int(round(brush_width)),
                    int(round(brush_width)),
                )
            else:
                painter.drawPath(overlay_path)
        elif self._drag_points and self._tool == "move":
            move_pen = QPen(QColor("#8BD0FF"), 2.0)
            move_pen.setCapStyle(Qt.RoundCap)
            painter.setPen(move_pen)
            start = self._drag_points[0]
            end = self._drag_points[-1]
            painter.drawLine(
                int(round(start[0] * scale)),
                int(round(start[1] * scale)),
                int(round(end[0] * scale)),
                int(round(end[1] * scale)),
            )
            handle_radius = 5
            painter.setPen(QPen(QColor(255, 255, 255, 160), 1.2))
            painter.setBrush(QColor(139, 208, 255, 84))
            painter.drawEllipse(
                int(round(end[0] * scale)) - handle_radius,
                int(round(end[1] * scale)) - handle_radius,
                handle_radius * 2,
                handle_radius * 2,
            )
        if self._lasso_points and self._tool == "lasso":
            path = QPainterPath()
            first = self._lasso_points[0]
            path.moveTo(first[0] * scale, first[1] * scale)
            for point in self._lasso_points[1:]:
                path.lineTo(point[0] * scale, point[1] * scale)
            painter.drawPath(path)
        if self._rect_origin is not None and self._drag_points and self._tool == "select_rect":
            start = self._rect_origin
            end = self._drag_points[-1]
            x = min(start[0], end[0])
            y = min(start[1], end[1])
            w = abs(end[0] - start[0])
            h = abs(end[1] - start[1])
            painter.drawRect(int(x * scale), int(y * scale), int(w * scale), int(h * scale))
        if self._clone_source_point is not None:
            x = int(self._clone_source_point[0] * scale)
            y = int(self._clone_source_point[1] * scale)
            painter.setPen(QPen(QColor("#FF7A7A"), 2))
            painter.drawLine(x - 10, y, x + 10, y)
            painter.drawLine(x, y - 10, x, y + 10)
        if self._floating_bounds is not None:
            x, y, w, h = self._floating_bounds
            painter.setPen(QPen(QColor("#F2C14E"), 2, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(int(round(x * scale)), int(round(y * scale)), int(round(w * scale)), int(round(h * scale)))
            if self._tool == "move":
                handle_pen = QPen(QColor("#FFD97A"), 1.2)
                painter.setPen(handle_pen)
                painter.setBrush(QColor(38, 45, 58, 220))
                handle_rects = self._floating_handle_rects()
                rotate_rect = handle_rects.get("rotate")
                if rotate_rect is not None:
                    center_x = int(round((x + (w / 2.0)) * scale))
                    center_y = int(round(y * scale))
                    rotate_center = rotate_rect.center()
                    painter.drawLine(center_x, center_y, int(round(rotate_center.x())), int(round(rotate_center.y())))
                for rect in handle_rects.values():
                    painter.drawEllipse(rect)
        hover_point = self._drag_points[-1] if self._drag_points else self._hover_point
        if hover_point is not None and self._tool in self._brush_tools():
            center_x = float(hover_point[0]) * scale
            center_y = float(hover_point[1]) * scale
            self._draw_brush_outline(painter, center_x, center_y)
            self._draw_brush_hud(painter, center_x, center_y)
        if self._tool in {"clone", "heal"} and self._clone_source_point is not None and hover_point is not None:
            source_x = float(self._clone_source_point[0]) * scale
            source_y = float(self._clone_source_point[1]) * scale
            if self._drag_points:
                dx = hover_point[0] - self._drag_points[0][0]
                dy = hover_point[1] - self._drag_points[0][1]
                source_x = float(self._clone_source_point[0] + dx) * scale
                source_y = float(self._clone_source_point[1] + dy) * scale
            painter.setPen(QPen(QColor("#8ED0FF"), 1.0, Qt.DashLine))
            painter.drawLine(
                int(round(hover_point[0] * scale)),
                int(round(hover_point[1] * scale)),
                int(round(source_x)),
                int(round(source_y)),
            )
            painter.setPen(QPen(QColor("#FFDA79"), 1.2))
            painter.drawEllipse(int(round(source_x - 4)), int(round(source_y - 4)), 8, 8)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._image is None:
            return
        point = self._widget_to_image_point(event.position())
        self._hover_point = point
        self._emit_hover_info(point)
        if self._sample_target:
            if point is None:
                return
            self.color_sampled.emit(f"{self._sample_target}|{self._sample_color(point)}")
            self.set_color_sample_target("")
            return
        if event.button() in {Qt.MiddleButton, Qt.RightButton} and self._scroll_area is not None:
            if (
                event.button() == Qt.RightButton
                and self._tool in {"clone", "heal"}
                and (event.modifiers() & Qt.ControlModifier)
            ):
                self.clone_source_picked.emit(point)
                return
            self._pan_start = (event.globalPosition().toPoint(), self._scroll_area.horizontalScrollBar().value(), self._scroll_area.verticalScrollBar().value())
            self.setCursor(Qt.ClosedHandCursor)
            return
        if event.button() != Qt.LeftButton:
            return
        if self._tool == "move" and self._floating_bounds is not None:
            transform_hit = self._floating_transform_hit(event.position())
            if transform_hit is not None:
                precise_point = self._clamped_image_point_float(event.position())
                if precise_point is None:
                    return
                self._transform_drag_mode = transform_hit
                self._transform_drag_start_point = precise_point
                self._transform_drag_start_bounds = self._floating_bounds
                self._transform_drag_start_origin_bounds = self._floating_origin_bounds or self._floating_bounds
                self._transform_drag_start_offset = (int(self._floating_offset_x), int(self._floating_offset_y))
                self._transform_drag_start_scale = (float(self._floating_scale_x), float(self._floating_scale_y))
                self._transform_drag_start_rotation = float(self._floating_rotation_degrees)
                self.setCursor(self._cursor_for_floating_hit(transform_hit))
                self.update()
                return
        if point is None:
            return
        if (event.modifiers() & Qt.AltModifier) and self._tool in {"paint", "fill"}:
            self.color_sampled.emit(f"paint|{self._sample_color(point)}")
            return
        if (
            (event.modifiers() & Qt.ShiftModifier)
            and self._tool in self._brush_tools()
            and self._last_stroke_point is not None
        ):
            self.stroke_committed.emit({"tool": self._tool, "points": [self._last_stroke_point, point]})
            self._last_stroke_point = point
            self.update()
            return
        self._dragging = True
        self._drag_points = [point]
        if self._tool == "select_rect":
            self._rect_origin = point
        elif self._tool == "lasso":
            precise_point = self._widget_to_image_point_float(event.position())
            if precise_point is not None:
                self._lasso_points = [precise_point]
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._pan_start is not None and self._scroll_area is not None:
            current = event.globalPosition().toPoint()
            start_point, start_x, start_y = self._pan_start
            delta = current - start_point
            self._scroll_area.horizontalScrollBar().setValue(start_x - delta.x())
            self._scroll_area.verticalScrollBar().setValue(start_y - delta.y())
            return
        if self._transform_drag_mode:
            precise_point = self._clamped_image_point_float(event.position())
            if precise_point is None:
                return
            payload = self._build_floating_transform_payload(precise_point, commit=False)
            if payload is not None:
                self.floating_transform_requested.emit(payload)
            return
        point = self._widget_to_image_point(event.position())
        self._hover_point = point
        self._emit_hover_info(point)
        if not self._dragging:
            if self._tool == "move" and self._sample_target == "":
                self.setCursor(self._cursor_for_floating_hit(self._floating_transform_hit(event.position())))
            self.update()
            return
        if self._tool == "lasso":
            precise_point = self._widget_to_image_point_float(event.position())
            if precise_point is None:
                return
            self._append_lasso_point(precise_point)
        else:
            if point is None:
                return
            self._drag_points.append(point)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._pan_start is not None and event.button() in {Qt.MiddleButton, Qt.RightButton}:
            self._pan_start = None
            self.setCursor(Qt.ArrowCursor)
            return
        if self._transform_drag_mode and event.button() == Qt.LeftButton:
            precise_point = self._clamped_image_point_float(event.position())
            payload = None if precise_point is None else self._build_floating_transform_payload(precise_point, commit=True)
            self._transform_drag_mode = ""
            self._transform_drag_start_point = None
            self._transform_drag_start_bounds = None
            self._transform_drag_start_origin_bounds = None
            self.setCursor(Qt.ArrowCursor)
            if payload is not None:
                self.floating_transform_requested.emit(payload)
            self.update()
            return
        if not self._dragging or event.button() != Qt.LeftButton:
            return
        self._dragging = False
        if self._tool == "select_rect" and self._rect_origin is not None and self._drag_points:
            start = self._rect_origin
            end = self._drag_points[-1]
            rect = (min(start[0], end[0]), min(start[1], end[1]), abs(end[0] - start[0]), abs(end[1] - start[1]))
            self.selection_committed.emit({"mode": "rect", "rect": rect})
        elif self._tool == "lasso" and len(self._lasso_points) >= 3:
            self.selection_committed.emit({"mode": "lasso", "points": list(self._lasso_points)})
        elif self._drag_points:
            self.stroke_committed.emit({"tool": self._tool, "points": list(self._drag_points)})
            if self._tool in self._brush_tools():
                self._last_stroke_point = self._drag_points[-1]
        self._drag_points = []
        self._lasso_points = []
        self._rect_origin = None
        self.update()

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._hover_point = None
        self._emit_hover_info(None)
        if self._pan_start is None and not self._transform_drag_mode and not self._sample_target:
            self.setCursor(Qt.ArrowCursor)
        self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if self._image is None:
            event.ignore()
            return
        delta = int(event.angleDelta().y())
        if delta == 0:
            delta = int(event.pixelDelta().y())
        if delta == 0:
            event.ignore()
            return
        pos = self._clamp_widget_point_to_image(event.position().toPoint())
        if pos is None:
            event.ignore()
            return
        self.wheel_zoom_requested.emit(int(delta), int(pos.x()), int(pos.y()))
        event.accept()


__all__ = ["TextureEditorCanvas"]
