from __future__ import annotations

from array import array
from ctypes import byref, c_int, c_uint, string_at
from dataclasses import dataclass, fields as dataclass_fields
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
from types import SimpleNamespace
import tempfile
import time
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QSettings, QSize, Qt, QTimer, QUrl, Signal, QSignalBlocker
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QImage,
    QImageReader,
    QMatrix4x4,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QVector2D,
    QVector3D,
    QVector4D,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget
except ImportError:
    QAudioOutput = None
    QMediaPlayer = None
    QVideoWidget = None
from PySide6.QtWidgets import (
    QApplication,
    QAbstractSpinBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QVBoxLayout,
    QFrame,
    QWidget,
)

from cdmw.models import (
    MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODE_LABELS,
    MODEL_PREVIEW_VISIBLE_TEXTURE_MODE_LABELS,
    HkxPhysicsOverlayAnchor,
    HkxPhysicsOverlayBone,
    HkxPhysicsOverlayConstraint,
    HkxPhysicsOverlayData,
    HkxPhysicsOverlayShape,
    ModelPreviewData,
    ModelPreviewMesh,
    ModelPreviewRenderSettings,
    PreparedModelPreviewBatch,
    PreparedModelPreviewData,
    PreviewMaterialTextureInput,
    RunCancelled,
    clamp_model_preview_render_settings,
)
from cdmw.rendering.model_preview_prepare import (
    BatchRenderDiagnostic as _BatchRenderDiagnostic,
    FramebufferVisibilitySample as _FramebufferVisibilitySample,
    ModelPreviewDrawBatch as _ModelPreviewDrawBatch,
    TextureVisibilitySample as _TextureVisibilitySample,
)
from cdmw.core.dds_native import (
    DdsNativeInfo,
    dds_native_report_dict,
    dds_source_path_from_report,
    inspect_dds_native_path,
)
from cdmw.core.model_preview_orientation import resolve_preview_texture_flip_vertical
from cdmw.ui.themes import get_theme

_RENDER_DIAGNOSTIC_MODE_CODES = {
    "lit": 0,
    "white_uniform": 1,
    "shader_marker": 2,
    "fragcoord_checker": 3,
    "vertex_color": 4,
    "normal": 5,
    "uv": 6,
    "cpu_average": 7,
    "base_direct": 8,
    "base_no_tint": 9,
    "base_alpha": 10,
    "normal_raw": 11,
    "material_raw": 12,
    "height_raw": 13,
    "sampler_swap_base_on_unit2": 14,
    "sampler_swap_material_on_unit0": 15,
    "base_color": 16,
    "texture_probe": 17,
    "height_depth": 18,
    "material_response": 19,
    "metal_shine": 20,
    "roughness_response": 21,
    "rich_lit": 22,
    "height_calibrated": 23,
    "relief_control_test": 24,
    "matcap": 25,
    "wireframe": 26,
    "vertex_normals": 27,
    "uv_checker": 28,
    "source_pbr_preview": 29,
    "cd_runtime_approx": 30,
}

class NonIntrusiveWheelGuard(QObject):
    """Prevents accidental wheel changes on setting widgets while scrolling containers."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() != QEvent.Wheel:
            return False
        if isinstance(watched, QComboBox):
            event.ignore()
            return True
        if isinstance(watched, QAbstractSpinBox):
            event.ignore()
            return True
        if isinstance(watched, QSlider):
            event.ignore()
            return True
        return False


_wheel_guard: Optional[NonIntrusiveWheelGuard] = None


def ensure_app_wheel_guard(app: Optional[QApplication]) -> None:
    global _wheel_guard
    if app is None or _wheel_guard is not None:
        return
    _wheel_guard = NonIntrusiveWheelGuard(app)
    app.installEventFilter(_wheel_guard)


def persistent_tree_column_widths_key(settings_key: str) -> str:
    return f"{str(settings_key or '').strip()}/column_widths"


def persistent_tree_column_order_key(settings_key: str) -> str:
    return f"{str(settings_key or '').strip()}/column_order"


def _persistent_int_list(value: object) -> tuple[int, ...]:
    if isinstance(value, (list, tuple)):
        raw_values = value
    else:
        raw_values = str(value or "").replace(";", ",").split(",")
    parsed: list[int] = []
    for raw_value in raw_values:
        try:
            parsed.append(int(str(raw_value).strip()))
        except (TypeError, ValueError):
            return ()
    return tuple(parsed)


def has_persistent_tree_column_widths(
    settings: QSettings,
    settings_key: str,
    column_count: int,
    *,
    minimum_width: int = 1,
) -> bool:
    widths = _persistent_int_list(settings.value(persistent_tree_column_widths_key(settings_key), ""))
    return len(widths) == int(column_count) and all(width >= int(minimum_width) for width in widths)


def restore_persistent_tree_column_widths(
    tree: QTreeWidget,
    settings: QSettings,
    settings_key: str,
    *,
    minimum_width: int = 1,
) -> bool:
    column_count = int(tree.columnCount())
    widths = _persistent_int_list(settings.value(persistent_tree_column_widths_key(settings_key), ""))
    if len(widths) != column_count:
        return False
    if any(width < int(minimum_width) for width in widths):
        return False
    header = tree.header()
    for index, width in enumerate(widths):
        header.resizeSection(index, int(width))
    return True


def restore_persistent_tree_column_order(tree: QTreeWidget, settings: QSettings, settings_key: str) -> bool:
    column_count = int(tree.columnCount())
    order = _persistent_int_list(settings.value(persistent_tree_column_order_key(settings_key), ""))
    if len(order) != column_count or sorted(order) != list(range(column_count)):
        return False
    header = tree.header()
    for visual_index, logical_index in enumerate(order):
        current_visual = header.visualIndex(int(logical_index))
        if current_visual >= 0 and current_visual != visual_index:
            header.moveSection(current_visual, visual_index)
    return True


def make_tree_columns_persistent(
    tree: QTreeWidget,
    settings: QSettings,
    settings_key: str,
    *,
    restore_later: bool = True,
    minimum_width: int = 1,
    save_callback: Optional[Callable[[], None]] = None,
    persist_order: bool = True,
    sections_movable: bool = True,
) -> None:
    header = tree.header()
    header.setSectionsMovable(bool(sections_movable))

    def _restore() -> None:
        restore_persistent_tree_column_widths(tree, settings, settings_key, minimum_width=minimum_width)
        if persist_order:
            restore_persistent_tree_column_order(tree, settings, settings_key)

    def _save() -> None:
        column_count = int(tree.columnCount())
        widths = [str(max(int(minimum_width), int(header.sectionSize(index)))) for index in range(column_count)]
        settings.setValue(persistent_tree_column_widths_key(settings_key), ",".join(widths))
        if persist_order:
            order = [str(int(header.logicalIndex(visual_index))) for visual_index in range(column_count)]
            settings.setValue(persistent_tree_column_order_key(settings_key), ",".join(order))
        if save_callback is not None:
            try:
                save_callback()
            except Exception:
                pass
        settings.sync()

    if restore_later:
        QTimer.singleShot(0, _restore)
    else:
        _restore()
    header.sectionResized.connect(lambda *_args: _save())
    header.sectionMoved.connect(lambda *_args: _save())


def _rebalance_splitter_sizes(
    sizes: Sequence[int],
    minimums: Sequence[int],
    target_total: int,
    weights: Optional[Sequence[int]] = None,
) -> List[int]:
    count = min(len(sizes), len(minimums))
    if count <= 0:
        return []
    target_total = max(int(target_total), 1)
    safe_weights = [max(1, int(weights[index])) for index in range(count)] if weights else [1] * count
    normalized = [max(int(minimums[index]), int(sizes[index])) for index in range(count)]
    minimum_total = sum(int(minimums[index]) for index in range(count))
    if target_total <= minimum_total:
        return [max(1, int(minimums[index])) for index in range(count)]

    total = sum(normalized)
    if total < target_total:
        slack = target_total - total
        order = sorted(range(count), key=lambda index: (safe_weights[index], normalized[index]), reverse=True)
        cursor = 0
        while slack > 0:
            target_index = order[cursor % count]
            normalized[target_index] += 1
            slack -= 1
            cursor += 1
        return normalized

    excess = total - target_total
    if excess <= 0:
        return normalized

    while excess > 0:
        order = sorted(
            range(count),
            key=lambda index: (normalized[index] - int(minimums[index]), safe_weights[index], normalized[index]),
            reverse=True,
        )
        changed = False
        for target_index in order:
            available = normalized[target_index] - int(minimums[target_index])
            if available <= 0:
                continue
            reduction = min(available, max(1, excess // max(1, count)))
            normalized[target_index] -= reduction
            excess -= reduction
            changed = True
            if excess <= 0:
                break
        if not changed:
            break
    return normalized


def build_responsive_splitter_sizes(
    total_span: int,
    weights: Sequence[int],
    minimums: Sequence[int],
) -> List[int]:
    count = min(len(weights), len(minimums))
    if count <= 0:
        return []
    safe_weights = [max(1, int(weights[index])) for index in range(count)]
    safe_minimums = [max(1, int(minimums[index])) for index in range(count)]
    target_total = max(int(total_span), sum(safe_minimums), count)
    weight_total = max(sum(safe_weights), 1)
    sizes = [
        max(
            safe_minimums[index],
            int(round((target_total * safe_weights[index]) / weight_total)),
        )
        for index in range(count)
    ]
    return _rebalance_splitter_sizes(sizes, safe_minimums, target_total, safe_weights)


def build_bounded_splitter_sizes(
    total_span: int,
    weights: Sequence[int],
    minimums: Sequence[int],
    maximums: Sequence[Optional[int]],
) -> List[int]:
    count = min(len(weights), len(minimums), len(maximums))
    if count <= 0:
        return []
    safe_weights = [max(1, int(weights[index])) for index in range(count)]
    safe_minimums = [max(1, int(minimums[index])) for index in range(count)]
    safe_maximums: List[Optional[int]] = []
    for index in range(count):
        maximum = maximums[index]
        if maximum is None or int(maximum) <= 0:
            safe_maximums.append(None)
        else:
            safe_maximums.append(max(safe_minimums[index], int(maximum)))
    target_total = max(int(total_span), 1)
    sizes = build_responsive_splitter_sizes(target_total, safe_weights, safe_minimums)
    for _pass in range(count + 1):
        overflow = 0
        growable: List[int] = []
        for index, maximum in enumerate(safe_maximums):
            if maximum is not None and sizes[index] > maximum:
                overflow += sizes[index] - maximum
                sizes[index] = maximum
            elif maximum is None or sizes[index] < maximum:
                growable.append(index)
        if overflow <= 0 or not growable:
            break
        remaining = overflow
        weight_total = max(sum(safe_weights[index] for index in growable), 1)
        for index in growable:
            maximum = safe_maximums[index]
            capacity = remaining if maximum is None else maximum - sizes[index]
            if capacity <= 0:
                continue
            addition = min(capacity, max(1, int(round((overflow * safe_weights[index]) / weight_total))))
            sizes[index] += addition
            remaining -= addition
            if remaining <= 0:
                break
        if remaining <= 0:
            break
    return sizes


def clamp_splitter_sizes(
    total_span: int,
    sizes: Sequence[int],
    minimums: Sequence[int],
    *,
    fallback_weights: Optional[Sequence[int]] = None,
) -> List[int]:
    count = len(minimums)
    if count <= 0:
        return []
    safe_minimums = [max(1, int(value)) for value in minimums]
    target_total = max(int(total_span), sum(safe_minimums), count)
    if len(sizes) < count:
        return build_responsive_splitter_sizes(
            target_total,
            fallback_weights or [1] * count,
            safe_minimums,
        )
    candidate = []
    for index in range(count):
        try:
            value = int(sizes[index])
        except (TypeError, ValueError):
            return build_responsive_splitter_sizes(
                target_total,
                fallback_weights or [1] * count,
                safe_minimums,
            )
        if value <= 0:
            return build_responsive_splitter_sizes(
                target_total,
                fallback_weights or [1] * count,
                safe_minimums,
            )
        candidate.append(value)
    current_total = sum(candidate)
    if current_total <= 0:
        return build_responsive_splitter_sizes(
            target_total,
            fallback_weights or [1] * count,
            safe_minimums,
        )
    if current_total != target_total:
        scale = target_total / current_total
        candidate = [max(1, int(round(value * scale))) for value in candidate]
    return _rebalance_splitter_sizes(
        candidate,
        safe_minimums,
        target_total,
        fallback_weights or [1] * count,
    )


def ui_scale_for(widget: Optional[QWidget] = None) -> float:
    """Return a conservative logical-pixel scale for font/DPI-aware sizing."""
    font = widget.font() if widget is not None else QApplication.font()
    metrics = font.pixelSize()
    if metrics <= 0:
        point_size = font.pointSizeF()
        metrics = point_size if point_size > 0 else 11.0
    return max(0.85, min(1.7, float(metrics) / 11.0))


def available_screen_size_for(widget: Optional[QWidget] = None) -> Tuple[int, int]:
    screen = None
    if widget is not None:
        try:
            screen = widget.screen()
        except RuntimeError:
            screen = None
    app = QApplication.instance()
    if screen is None and app is not None:
        screen = app.primaryScreen()
    if screen is None:
        return (1920, 1080)
    geometry = screen.availableGeometry()
    return (max(1, int(geometry.width())), max(1, int(geometry.height())))


def available_layout_size_for(widget: Optional[QWidget] = None) -> Tuple[int, int]:
    screen_width, screen_height = available_screen_size_for(widget)
    if widget is None:
        return (screen_width, screen_height)
    try:
        window = widget.window()
    except RuntimeError:
        window = None
    if window is not None and window.isVisible():
        width = int(window.width())
        height = int(window.height())
        if width > 0 and height > 0:
            return (max(1, min(screen_width, width)), max(1, min(screen_height, height)))
    return (screen_width, screen_height)


def available_screen_width_for(widget: Optional[QWidget] = None) -> int:
    return available_screen_size_for(widget)[0]


def responsive_screen_compact_scale(widget: Optional[QWidget] = None) -> float:
    width, height = available_layout_size_for(widget)
    if width <= 1366:
        width_scale = 0.68
    elif width <= 1600:
        width_scale = 0.74
    elif width <= 1920:
        width_scale = 0.80
    elif width <= 2560:
        width_scale = 0.92
    else:
        width_scale = 1.0
    if height <= 768:
        height_scale = 0.68
    elif height <= 900:
        height_scale = 0.76
    elif height <= 1080:
        height_scale = 0.82
    elif height <= 1200:
        height_scale = 0.90
    else:
        height_scale = 1.0
    return min(width_scale, height_scale)


def scaled_px(value: int, widget: Optional[QWidget] = None) -> int:
    return max(1, int(round(float(value) * ui_scale_for(widget))))


def responsive_sidebar_bounds(widget: Optional[QWidget] = None, *, role: str = "normal") -> Tuple[int, int, int]:
    scale = ui_scale_for(widget) * responsive_screen_compact_scale(widget)
    if role == "wide":
        values = (380, 500, 680)
    elif role == "workflow":
        values = (440, 640, 840)
    elif role == "tool":
        values = (220, 260, 340)
    elif role == "narrow":
        values = (280, 340, 460)
    else:
        values = (320, 420, 560)
    return tuple(max(1, int(round(value * scale))) for value in values)  # type: ignore[return-value]


def set_sidebar_width_policy(widget: QWidget, *, role: str = "normal") -> None:
    minimum, preferred, maximum = responsive_sidebar_bounds(widget, role=role)
    widget.setMinimumWidth(minimum)
    widget.setMaximumWidth(maximum)
    widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
    widget.resize(preferred, widget.height())


class FlatSectionPanel(QWidget):
    """Simple titled panel without QGroupBox title-over-border rendering."""

    def __init__(self, title: str, *, body_margins: Tuple[int, int, int, int] = (10, 10, 10, 10), body_spacing: int = 8):
        super().__init__()
        self.setObjectName("FlatSectionPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 4, 0, 0)
        outer_layout.setSpacing(2)

        self.header_widget = QWidget()
        self.header_widget.setObjectName("FlatSectionHeader")
        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(14, 0, 0, 0)
        header_layout.setSpacing(0)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("FlatSectionTitle")
        self.title_label.setWordWrap(True)
        header_layout.addWidget(self.title_label, alignment=Qt.AlignLeft | Qt.AlignTop)
        header_layout.addStretch(1)
        outer_layout.addWidget(self.header_widget)

        self.body_frame = QFrame()
        self.body_frame.setObjectName("FlatSectionBody")
        self.body_layout = QVBoxLayout(self.body_frame)
        self.body_layout.setContentsMargins(*body_margins)
        self.body_layout.setSpacing(body_spacing)
        outer_layout.addWidget(self.body_frame, stretch=1)


class EmptyStatePanel(QWidget):
    """Centered low-noise guidance for empty tables, previews, and idle panes."""

    def __init__(self, title: str, detail: str = "", *, compact: bool = False):
        super().__init__()
        self.setObjectName("EmptyStatePanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        pad_x = scaled_px(18 if compact else 28, self)
        pad_y = scaled_px(16 if compact else 24, self)
        layout.setContentsMargins(pad_x, pad_y, pad_x, pad_y)
        layout.setSpacing(scaled_px(6, self))
        layout.addStretch(1)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("EmptyStateTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("EmptyStateDetail")
        self.detail_label.setAlignment(Qt.AlignCenter)
        self.detail_label.setWordWrap(True)
        self.detail_label.setVisible(bool(detail))
        layout.addWidget(self.detail_label)
        layout.addStretch(1)

    def set_text(self, title: str, detail: str = "") -> None:
        self.title_label.setText(title)
        self.detail_label.setText(detail)
        self.detail_label.setVisible(bool(detail))


class EmptyStateTreeWidget(QTreeWidget):
    """QTreeWidget with quiet placeholder copy when the model has no rows."""

    def __init__(self, title: str = "", detail: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.empty_title = title
        self.empty_detail = detail

    def set_empty_state(self, title: str, detail: str = "") -> None:
        self.empty_title = title
        self.empty_detail = detail
        self.viewport().update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        if self.topLevelItemCount() > 0 or not (self.empty_title or self.empty_detail):
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        rect = self.viewport().rect().adjusted(scaled_px(24, self), scaled_px(24, self), -scaled_px(24, self), -scaled_px(24, self))
        palette = self.palette()
        title_font = QFont(self.font())
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(palette.color(QPalette.Text))
        metrics = painter.fontMetrics()
        title_height = metrics.boundingRect(rect, Qt.AlignCenter | Qt.TextWordWrap, self.empty_title).height()
        detail_height = 0
        if self.empty_detail:
            detail_font = QFont(self.font())
            detail_font.setBold(False)
            painter.setFont(detail_font)
            detail_height = painter.fontMetrics().boundingRect(rect, Qt.AlignCenter | Qt.TextWordWrap, self.empty_detail).height()
        gap = scaled_px(8, self) if self.empty_title and self.empty_detail else 0
        total_height = title_height + detail_height + gap
        y = rect.center().y() - total_height // 2
        if self.empty_title:
            title_rect = QRect(rect.left(), y, rect.width(), title_height)
            painter.setFont(title_font)
            painter.setPen(palette.color(QPalette.Text))
            painter.drawText(title_rect, Qt.AlignCenter | Qt.TextWordWrap, self.empty_title)
            y += title_height + gap
        if self.empty_detail:
            detail_rect = QRect(rect.left(), y, rect.width(), detail_height)
            painter.setFont(self.font())
            painter.setPen(palette.color(QPalette.PlaceholderText))
            painter.drawText(detail_rect, Qt.AlignCenter | Qt.TextWordWrap, self.empty_detail)


class PreviewLabel(QLabel):
    color_sampled = Signal(str)

    def __init__(self, title: str):
        super().__init__(title)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(280, 220)
        self.setWordWrap(True)
        self.setObjectName("PreviewLabel")
        self._source_pixmap: Optional[QPixmap] = None
        self._source_image: Optional[QImage] = None
        self._source_image_path: str = ""
        self._source_image_size = QSize()
        self._source_image_loaded_size = QSize()
        self._source_image_load_failed = False
        self._source_revision = 0
        self._scaled_pixmap_cache: Dict[Tuple[int, int, int, int], QPixmap] = {}
        self._current_render_key: Optional[Tuple[int, int, int, int]] = None
        self._current_render_size = QSize()
        self._fallback_text = title
        self._pending_render_text = title
        self._zoom_factor = 1.0
        self._fit_to_view = True
        self._fit_scale = 1.0
        self._scroll_area = None
        self._wheel_zoom_handler: Optional[Callable[[int], None]] = None
        self._color_pick_enabled = False
        self._drag_active = False
        self._drag_start_global_pos = None
        self._drag_start_h = 0
        self._drag_start_v = 0
        self._interactive_scale_timer = QTimer(self)
        self._interactive_scale_timer.setSingleShot(True)
        self._interactive_scale_timer.setInterval(16)
        self._interactive_scale_timer.timeout.connect(self._flush_interactive_scale)
        self._idle_scale_timer = QTimer(self)
        self._idle_scale_timer.setSingleShot(True)
        self._idle_scale_timer.setInterval(140)
        self._idle_scale_timer.timeout.connect(self._flush_idle_scale)

    def clear_preview(self, message: str) -> None:
        self._interactive_scale_timer.stop()
        self._idle_scale_timer.stop()
        self._source_pixmap = None
        self._source_image = None
        self._source_image_path = ""
        self._source_image_size = QSize()
        self._source_image_loaded_size = QSize()
        self._source_image_load_failed = False
        self._source_revision += 1
        self._scaled_pixmap_cache.clear()
        self._current_render_key = None
        self._current_render_size = QSize()
        self._fallback_text = message
        self._pending_render_text = message
        self._drag_active = False
        self.setPixmap(QPixmap())
        self.setText(message)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(280, 220)
        self.setMaximumSize(16777215, 16777215)
        self.unsetCursor()

    def attach_scroll_area(self, scroll_area) -> None:
        self._scroll_area = scroll_area
        scroll_area.resized.connect(self._handle_viewport_resize)

    def set_wheel_zoom_handler(self, handler: Optional[Callable[[int], None]]) -> None:
        self._wheel_zoom_handler = handler

    def set_color_pick_enabled(self, enabled: bool) -> None:
        self._color_pick_enabled = enabled
        self._update_cursor()

    def set_zoom_factor(self, zoom_factor: float) -> None:
        self._zoom_factor = max(0.1, zoom_factor)
        if self._has_source_image():
            self._interactive_scale_timer.stop()
            self._idle_scale_timer.stop()
            self._apply_scaled_pixmap(self._fallback_text)

    def set_fit_to_view(self, fit_to_view: bool) -> None:
        self._fit_to_view = fit_to_view
        if self._has_source_image():
            self._interactive_scale_timer.stop()
            self._idle_scale_timer.stop()
            self._apply_scaled_pixmap(self._fallback_text)

    def set_fit_scale(self, fit_scale: float) -> None:
        self._fit_scale = max(0.5, min(4.0, fit_scale))
        if self._has_source_image() and self._fit_to_view:
            self._interactive_scale_timer.stop()
            self._idle_scale_timer.stop()
            self._apply_scaled_pixmap(self._fallback_text)

    def set_preview_pixmap(self, pixmap: QPixmap, fallback_text: str) -> None:
        self._interactive_scale_timer.stop()
        self._idle_scale_timer.stop()
        self._source_pixmap = pixmap
        self._source_image = None
        self._source_image_path = ""
        self._source_image_size = pixmap.size()
        self._source_image_loaded_size = pixmap.size()
        self._source_image_load_failed = False
        self._source_revision += 1
        self._scaled_pixmap_cache.clear()
        self._current_render_key = None
        self._current_render_size = QSize()
        self._fallback_text = fallback_text
        self._pending_render_text = fallback_text
        self._apply_scaled_pixmap(fallback_text)

    def set_preview_image(self, image: QImage, fallback_text: str) -> None:
        self._interactive_scale_timer.stop()
        self._idle_scale_timer.stop()
        self._source_pixmap = None
        self._source_image = image
        self._source_image_path = ""
        self._source_image_size = image.size() if not image.isNull() else QSize()
        self._source_image_loaded_size = self._source_image_size
        self._source_image_load_failed = False
        self._source_revision += 1
        self._scaled_pixmap_cache.clear()
        self._current_render_key = None
        self._current_render_size = QSize()
        self._fallback_text = fallback_text
        self._pending_render_text = fallback_text
        self._apply_scaled_pixmap(fallback_text)

    def set_preview_image_path(self, image_path: str, fallback_text: str) -> None:
        self._interactive_scale_timer.stop()
        self._idle_scale_timer.stop()
        self._source_pixmap = None
        self._source_image = None
        self._source_image_path = image_path
        self._source_image_load_failed = False
        reader = QImageReader(image_path)
        size = reader.size()
        self._source_image_size = size if size.isValid() else QSize()
        self._source_image_loaded_size = QSize()
        self._source_revision += 1
        self._scaled_pixmap_cache.clear()
        self._current_render_key = None
        self._current_render_size = QSize()
        self._fallback_text = fallback_text
        self._pending_render_text = fallback_text
        self._apply_scaled_pixmap(fallback_text)

    def current_display_scale(self) -> float:
        source_width = 0
        if self._source_pixmap is not None and not self._source_pixmap.isNull():
            source_width = self._source_pixmap.width()
        elif self._source_image_size.isValid():
            source_width = self._source_image_size.width()
        if source_width <= 0:
            return 1.0
        return max(0.1, self.width() / float(source_width))

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._has_source_image() and self._fit_to_view and self._scroll_area is None:
            self._schedule_fit_rescale()

    def _handle_viewport_resize(self) -> None:
        if self._has_source_image() and self._fit_to_view:
            self._schedule_fit_rescale()

    def _schedule_fit_rescale(self) -> None:
        self._pending_render_text = self._fallback_text
        self._interactive_scale_timer.start()
        self._idle_scale_timer.start()

    def _flush_interactive_scale(self) -> None:
        if self._has_source_image():
            self._apply_scaled_pixmap(self._pending_render_text, transformation_mode=Qt.FastTransformation)

    def _flush_idle_scale(self) -> None:
        if self._has_source_image():
            self._apply_scaled_pixmap(self._pending_render_text, transformation_mode=Qt.SmoothTransformation)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton and self._color_pick_enabled:
            current_pixmap = self.pixmap()
            point = event.position().toPoint()
            if current_pixmap is not None and not current_pixmap.isNull():
                if 0 <= point.x() < current_pixmap.width() and 0 <= point.y() < current_pixmap.height():
                    color = current_pixmap.toImage().pixelColor(point)
                    self.color_sampled.emit(color.name().upper())
                    event.accept()
                    return
        if (
            event.button() == Qt.LeftButton
            and self._can_pan()
            and self._scroll_area is not None
        ):
            self._drag_active = True
            self._drag_start_global_pos = event.globalPosition().toPoint()
            self._drag_start_h = self._scroll_area.horizontalScrollBar().value()
            self._drag_start_v = self._scroll_area.verticalScrollBar().value()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_active and self._scroll_area is not None and self._drag_start_global_pos is not None:
            delta = event.globalPosition().toPoint() - self._drag_start_global_pos
            self._scroll_area.horizontalScrollBar().setValue(self._drag_start_h - delta.x())
            self._scroll_area.verticalScrollBar().setValue(self._drag_start_v - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_active and event.button() == Qt.LeftButton:
            self._drag_active = False
            self._drag_start_global_pos = None
            self._update_cursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        delta_y = event.angleDelta().y()
        if (
            self._wheel_zoom_handler is not None
            and self._has_source_image()
            and delta_y != 0
        ):
            step = 1 if delta_y > 0 else -1
            self._wheel_zoom_handler(step)
            event.accept()
            return
        super().wheelEvent(event)

    def _can_pan(self) -> bool:
        if not self._has_source_image() or self._scroll_area is None:
            return False
        viewport = self._scroll_area.viewport().size()
        return self.width() > viewport.width() or self.height() > viewport.height()

    def _has_source_image(self) -> bool:
        return (
            self._source_pixmap is not None and not self._source_pixmap.isNull()
        ) or (self._source_image is not None and not self._source_image.isNull()) or (
            bool(self._source_image_path) and not self._source_image_load_failed
        )

    def _update_cursor(self) -> None:
        if self._color_pick_enabled:
            self.setCursor(Qt.CrossCursor)
        elif self._drag_active:
            self.setCursor(Qt.ClosedHandCursor)
        elif self._can_pan():
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.unsetCursor()

    def _apply_scaled_pixmap(self, fallback_text: str, *, transformation_mode=Qt.SmoothTransformation) -> None:
        self._fallback_text = fallback_text
        has_source_pixmap = self._source_pixmap is not None and not self._source_pixmap.isNull()
        has_source_image = self._source_image is not None and not self._source_image.isNull()
        has_source_path = bool(self._source_image_path) and not self._source_image_load_failed
        if not has_source_pixmap and not has_source_image and not has_source_path:
            self.setPixmap(QPixmap())
            self.setText(fallback_text)
            self._update_cursor()
            return

        if self._fit_to_view and self._scroll_area is not None:
            viewport = self._scroll_area.maximumViewportSize()
            if not viewport.isValid() or viewport.isEmpty():
                viewport = self._scroll_area.viewport().size()
            width = max(1, int(round((viewport.width() - 6) * self._fit_scale)))
            height = max(1, int(round((viewport.height() - 6) * self._fit_scale)))
        else:
            if has_source_pixmap:
                source_size = self._source_pixmap.size()
            elif self._source_image is not None and not self._source_image.isNull():
                source_size = self._source_image.size()
            else:
                source_size = self._source_image_size
            width = max(1, int(round(source_size.width() * self._zoom_factor)))
            height = max(1, int(round(source_size.height() * self._zoom_factor)))

        transform_key = 0 if transformation_mode == Qt.FastTransformation else 1
        cache_key = (self._source_revision, width, height, transform_key)
        if self._current_render_key == cache_key:
            current_pixmap = self.pixmap()
            if current_pixmap is not None and not current_pixmap.isNull() and current_pixmap.size() == self._current_render_size:
                self._update_cursor()
                return
        cached = self._scaled_pixmap_cache.get(cache_key)
        if cached is not None and not cached.isNull():
            scaled = cached
        elif has_source_pixmap:
            scaled = self._source_pixmap.scaled(
                width,
                height,
                Qt.KeepAspectRatio,
                transformation_mode,
            )
            self._cache_scaled_pixmap(cache_key, scaled)
        else:
            if not has_source_image:
                if not self._load_source_image_for_render(width, height):
                    self.setPixmap(QPixmap())
                    self.setText(fallback_text)
                    self._update_cursor()
                    return
            target_size = self._source_image.size().scaled(width, height, Qt.KeepAspectRatio)
            if not target_size.isValid():
                self.setPixmap(QPixmap())
                self.setText(fallback_text)
                self._update_cursor()
                return
            scaled_image = self._source_image.scaled(
                target_size,
                Qt.KeepAspectRatio,
                transformation_mode,
            )
            scaled = QPixmap.fromImage(scaled_image)
            self._cache_scaled_pixmap(cache_key, scaled)

        self.setText("")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(0, 0)
        self.resize(scaled.size())
        self.setFixedSize(scaled.size())
        self.setPixmap(scaled)
        self._current_render_key = cache_key
        self._current_render_size = scaled.size()
        self._update_cursor()

    def _cache_scaled_pixmap(self, cache_key: Tuple[int, int, int, int], pixmap: QPixmap) -> None:
        if pixmap.isNull():
            return
        self._scaled_pixmap_cache[cache_key] = pixmap
        if len(self._scaled_pixmap_cache) > 12:
            oldest_key = next(iter(self._scaled_pixmap_cache))
            self._scaled_pixmap_cache.pop(oldest_key, None)

    def _load_source_image_for_render(self, target_width: int, target_height: int) -> bool:
        if self._source_image_load_failed or not self._source_image_path:
            return False
        requested_size = QSize(max(1, target_width), max(1, target_height))
        reader = QImageReader(self._source_image_path)
        reader.setAutoTransform(True)
        if not self._source_image_size.isValid():
            size = reader.size()
            if size.isValid():
                self._source_image_size = size
        source_size = self._source_image_size if self._source_image_size.isValid() else reader.size()
        decode_target_size = (
            source_size.scaled(requested_size, Qt.KeepAspectRatio)
            if source_size.isValid()
            else requested_size
        )
        if self._source_image is not None and not self._source_image.isNull():
            loaded_size = self._source_image.size()
            if loaded_size.isValid() and (
                loaded_size.width() >= decode_target_size.width()
                and loaded_size.height() >= decode_target_size.height()
            ):
                self._source_image_loaded_size = loaded_size
                return True
        use_scaled_decode = (
            source_size.isValid()
            and source_size.width() > decode_target_size.width() * 2
            and source_size.height() > decode_target_size.height() * 2
        )
        if use_scaled_decode:
            reader.setScaledSize(decode_target_size)
        image = reader.read()
        if image.isNull() and use_scaled_decode:
            reader = QImageReader(self._source_image_path)
            reader.setAutoTransform(True)
            image = reader.read()
        if image.isNull():
            self._source_image_load_failed = True
            self._source_image = None
            self._source_image_loaded_size = QSize()
            return False
        self._source_image = image
        self._source_image_loaded_size = image.size()
        if not self._source_image_size.isValid():
            self._source_image_size = image.size()
        return True



class NativePreviewPanel(QWidget):
    view_state_changed = Signal(float, bool)
    debug_details_changed = Signal(str)
    physics_overlay_target_selected = Signal(str, str, int, str, str)
    alignment_translate_requested = Signal(float, float, float)
    alignment_drag_started = Signal()
    alignment_drag_changed = Signal(float, float, float)
    alignment_drag_finished = Signal(float, float, float)
    alignment_rotation_changed = Signal(float, float, float)
    alignment_rotation_finished = Signal(float, float, float)
    mesh_edit_stroke_started = Signal(object)
    mesh_edit_stroke_previewed = Signal(object)
    mesh_edit_stroke_finished = Signal(object)
    mesh_edit_stroke_cancelled = Signal(object)
    mesh_edit_selection_changed = Signal(object)

    from cdmw.rendering import model_preview_prepare as _prep

    _FIT_DISTANCE = _prep.FIT_DISTANCE
    _OVERLAY_CLIP_EPSILON = _prep.OVERLAY_CLIP_EPSILON
    _clip_preview_line = staticmethod(_prep.clip_preview_line)
    _alignment_euler_xyz_matrix = staticmethod(_prep.alignment_euler_xyz_matrix)
    _alignment_euler_delta_matrix = staticmethod(_prep.alignment_euler_delta_matrix)
    _render_mode_uses_derived_relief = staticmethod(_prep.render_mode_uses_derived_relief)
    _sample_base_texture_visibility = staticmethod(_prep.sample_base_texture_visibility)
    _sample_framebuffer_visibility = staticmethod(_prep.sample_framebuffer_visibility)
    _derive_relief_image_from_base = staticmethod(_prep.derive_relief_image_from_base)
    _enhanced_relief_status = staticmethod(_prep.enhanced_relief_status)
    _diffuse_probe_source_for_render_mode = staticmethod(_prep.diffuse_probe_source_for_render_mode)
    _black_output_triage_lines = staticmethod(_prep.black_output_triage_lines)
    _support_map_slot_counts_from_batches = staticmethod(_prep.support_map_slot_counts_from_batches)
    _support_map_active_counts_from_diagnostics = staticmethod(_prep.support_map_active_counts_from_diagnostics)
    _format_support_map_counts = staticmethod(_prep.format_support_map_counts)
    _build_vertex_blob = staticmethod(_prep.build_vertex_blob)
    _support_map_geometry_usable = staticmethod(_prep.support_map_geometry_usable)
    _dds_source_path_for_preview_path = staticmethod(_prep.dds_source_path_for_preview_path)
    _material_combiner_cache_dir = staticmethod(_prep.material_combiner_cache_dir)
    prepare_model_preview = staticmethod(_prep.prepare_model_preview)
    _DEFAULT_YAW = -35.0
    _DEFAULT_PITCH = 20.0

    def __init__(self, title: str, *, theme_key: str):
        super().__init__()
        self.setMinimumSize(280, 220)
        self._theme_key = theme_key
        self._message = str(title or "")
        self._current_model = None
        self._prepared_preview = None
        self._render_settings = ModelPreviewRenderSettings()
        self._use_textures = False
        self._high_quality_textures = False
        self._fit_to_view = True
        self._zoom_factor = 1.0
        self._distance = float(self._FIT_DISTANCE)
        self._yaw = float(self._DEFAULT_YAW)
        self._pitch = float(self._DEFAULT_PITCH)
        self._pan_offset = QVector3D(0.0, 0.0, 0.0)
        self._alignment_editable_indices: tuple[int, ...] = ()
        self._alignment_editable_range = (0, -1)
        self._physics_overlay_bones_visible = True
        self._physics_overlay_edited_targets: set[str] = set()
        self._selected_physics_overlay_target = ""
        self._pan_drag_active = False
        self._physics_simulation_timer = QTimer(self)
        self._physics_simulation_timer.setInterval(16)
        self._physics_simulation_timer.timeout.connect(lambda: None)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self._status_label = QLabel(self._message)
        self._status_label.setObjectName("HintLabel")
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label, stretch=1)

    def _set_message(self, message: str) -> None:
        self._message = str(message or "")
        if hasattr(self, "_status_label"):
            self._status_label.setText(self._message)
        self.debug_details_changed.emit(self._message)

    def pause_interactive_timers(self) -> None:
        self._physics_simulation_timer.stop()
        self._pan_drag_active = False

    def _resume_interactive_timers_if_visible(self) -> None:
        visible = self.isVisible() and (self.window() is None or self.window().isVisible())
        if visible and bool(getattr(self._render_settings, "show_physics_overlay", False)):
            self._physics_simulation_timer.start()

    def hideEvent(self, event) -> None:  # type: ignore[override]
        self.pause_interactive_timers()
        if not self.isVisible():
            self._pan_drag_active = False
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._resume_interactive_timers_if_visible()

    def set_theme(self, theme_key: str) -> None:
        self._theme_key = str(theme_key or self._theme_key)

    def clear_model(self, message: str, **_kwargs: object) -> None:
        self._current_model = None
        self._prepared_preview = None
        self._set_message(message)

    def set_model(self, model: object) -> None:
        prepared_model, prepared_preview = self.prepare_model_preview(
            model,
            render_settings=self._render_settings,
            enable_material_combiner=True,
        )
        self.set_prepared_model(prepared_model, prepared_preview)

    def set_model_preserving_view(self, model: object, **_kwargs: object) -> None:
        state = self.view_state_snapshot()
        self.set_model(model)
        self.restore_view_state(state)

    def set_prepared_model(self, model: object, prepared_preview: object = None, **_kwargs: object) -> None:
        self._current_model = model
        self._prepared_preview = prepared_preview
        mesh_count = len(getattr(model, "meshes", ()) or ())
        batch_count = len(getattr(prepared_preview, "batches", ()) or ()) if prepared_preview is not None else 0
        vertex_count = int(getattr(prepared_preview, "vertex_count", getattr(model, "vertex_count", 0)) or 0)
        self._set_message(f"Native D3D11 preview data ready: {mesh_count:,} mesh(es), {batch_count:,} batch(es), {vertex_count:,} vertices.")
        self._resume_interactive_timers_if_visible()

    def is_available(self) -> bool:
        return True

    def failure_reason(self) -> str:
        return ""

    def debug_details_text(self) -> str:
        return self._message

    def render_settings(self) -> ModelPreviewRenderSettings:
        return self._render_settings

    def set_render_settings(self, settings: Optional[ModelPreviewRenderSettings]) -> None:
        self._render_settings = clamp_model_preview_render_settings(settings)
        self._resume_interactive_timers_if_visible()

    def set_use_textures(self, use_textures: bool) -> None:
        self._use_textures = bool(use_textures)

    def set_high_quality_textures(self, enabled: bool) -> None:
        self._high_quality_textures = bool(enabled)

    def set_dark_background_enabled(self, _enabled: bool) -> None:
        return

    def set_alignment_guides_visible(self, _visible: bool) -> None:
        return

    def set_alignment_editing_enabled(self, _enabled: bool) -> None:
        return

    def set_alignment_translation_units_per_pixel(self, _value: float) -> None:
        return

    def set_alignment_translation_sensitivity(self, _multiplier: float) -> None:
        return

    def set_alignment_rotation_degrees_per_pixel(self, _value: float) -> None:
        return

    def set_alignment_live_translation(self, _x: float, _y: float, _z: float) -> None:
        return

    def clear_alignment_live_translation(self) -> None:
        return

    def set_alignment_live_rotation(self, _x: float, _y: float, _z: float) -> None:
        return

    def clear_alignment_live_rotation(self) -> None:
        return

    def set_alignment_committed_preview_transform(self, *_args: object, **_kwargs: object) -> None:
        return

    def clear_alignment_committed_preview_transform(self) -> None:
        return

    def set_alignment_base_rotation_degrees(self, *_args: object) -> None:
        return

    def set_alignment_rotation_origin_override(self, *_args: object) -> None:
        return

    def set_alignment_editable_mesh_range(self, start: int = 0, count: int = -1) -> None:
        self._alignment_editable_range = (int(start), int(count))

    def set_alignment_editable_mesh_indices(self, indices: Sequence[int] | None) -> None:
        self._alignment_editable_indices = tuple(int(index) for index in tuple(indices or ()))

    def set_mesh_editing_enabled(self, _enabled: bool) -> None:
        return

    def set_mesh_edit_target_mode(self, _mode: str) -> None:
        return

    def set_mesh_edit_tool(self, _tool: str) -> None:
        return

    def set_mesh_edit_source_submesh_indices(self, _indices: Sequence[int] | None) -> None:
        return

    def set_mesh_edit_delete_mode(self, _mode: str) -> None:
        return

    def set_mesh_edit_brush_settings(self, *_args: object, **_kwargs: object) -> None:
        return

    def clear_mesh_edit_vertex_selection(self) -> None:
        self.mesh_edit_selection_changed.emit({})

    def select_mesh_edit_brush_vertices(self) -> None:
        self.mesh_edit_selection_changed.emit({})

    def set_mesh_edit_vertex_selection(self, selected_vertices_by_submesh: Mapping[int, Iterable[int]]) -> None:
        groups = []
        for raw_source_index, raw_vertices in dict(selected_vertices_by_submesh or {}).items():
            try:
                source_index = int(raw_source_index)
            except (TypeError, ValueError):
                continue
            vertices = []
            for raw_vertex in tuple(raw_vertices or ()):
                try:
                    vertex_index = int(raw_vertex)
                except (TypeError, ValueError):
                    continue
                if vertex_index >= 0:
                    vertices.append(vertex_index)
            if vertices:
                groups.append({"source_submesh_index": source_index, "source_vertex_indices": sorted(set(vertices))})
        self.mesh_edit_selection_changed.emit({"groups": groups, "selected_vertex_count": sum(len(group["source_vertex_indices"]) for group in groups)})

    def set_zoom_factor(self, zoom_factor: float) -> None:
        try:
            self._zoom_factor = max(0.1, float(zoom_factor))
        except (TypeError, ValueError, OverflowError):
            self._zoom_factor = 1.0
        self._fit_to_view = False
        self._distance = float(self._FIT_DISTANCE) / max(0.1, float(self._zoom_factor))
        self.view_state_changed.emit(self._zoom_factor, self._fit_to_view)

    def set_fit_to_view(self, fit_to_view: bool) -> None:
        self._fit_to_view = bool(fit_to_view)
        if self._fit_to_view:
            self._distance = float(self._FIT_DISTANCE)
        self.view_state_changed.emit(self._zoom_factor, self._fit_to_view)

    def current_display_scale(self) -> float:
        return 1.0 if self._fit_to_view else self._zoom_factor

    def reset_view(self) -> None:
        self._fit_to_view = True
        self._zoom_factor = 1.0
        self._distance = float(self._FIT_DISTANCE)
        self._yaw = float(self._DEFAULT_YAW)
        self._pitch = float(self._DEFAULT_PITCH)
        self._pan_offset = QVector3D(0.0, 0.0, 0.0)
        self.view_state_changed.emit(self._zoom_factor, self._fit_to_view)

    def view_state_snapshot(self) -> Tuple[float, float, bool, float, float, Tuple[float, float, float]]:
        return (
            float(self._yaw),
            float(self._pitch),
            bool(self._fit_to_view),
            float(self._zoom_factor),
            float(self._distance),
            (
                float(self._pan_offset.x()),
                float(self._pan_offset.y()),
                float(self._pan_offset.z()),
            ),
        )

    def restore_view_state(
        self,
        state: Optional[Tuple[float, float, bool, float, float, Tuple[float, float, float]] | Mapping[str, object]],
    ) -> None:
        if not state:
            return
        try:
            if isinstance(state, Mapping):
                yaw = float(state.get("yaw", self._yaw))
                pitch = float(state.get("pitch", self._pitch))
                fit_to_view = bool(state.get("fit_to_view", self._fit_to_view))
                zoom_factor = float(state.get("zoom_factor", self._zoom_factor))
                distance = float(
                    self._FIT_DISTANCE if fit_to_view else self._FIT_DISTANCE / max(0.1, zoom_factor)
                )
                pan_offset = tuple(state.get("pan", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0))
            else:
                yaw, pitch, fit_to_view, zoom_factor, distance, pan_offset = state
            self._yaw = float(yaw)
            self._pitch = max(-89.0, min(89.0, float(pitch)))
            self._fit_to_view = bool(fit_to_view)
            self._zoom_factor = min(max(float(zoom_factor), 0.1), 16.0)
            self._distance = max(0.1, float(distance))
            pan_values = tuple(float(value) for value in tuple(pan_offset)[:3])
            while len(pan_values) < 3:
                pan_values = (*pan_values, 0.0)
            self._pan_offset = QVector3D(float(pan_values[0]), float(pan_values[1]), float(pan_values[2]))
        except Exception:
            return
        self.view_state_changed.emit(self._zoom_factor, self._fit_to_view)

    def set_view(
        self,
        *,
        yaw: float,
        pitch: float,
        zoom_factor: Optional[float] = None,
        fit_to_view: Optional[bool] = None,
        pan: Sequence[float] = (0.0, 0.0, 0.0),
        **_kwargs: object,
    ) -> None:
        self.restore_view_state(
            {
                "yaw": float(yaw),
                "pitch": float(pitch),
                "zoom_factor": float(self._zoom_factor if zoom_factor is None else zoom_factor),
                "fit_to_view": bool(self._fit_to_view if fit_to_view is None else fit_to_view),
                "pan": tuple(float(value) for value in tuple(pan or (0.0, 0.0, 0.0))[:3]),
            }
        )

    def support_maps_available(self) -> bool:
        batches = tuple(getattr(self._prepared_preview, "batches", ()) or ())
        return any(
            str(getattr(batch, "preview_normal_texture_path", "") or "").strip()
            or str(getattr(batch, "preview_material_texture_path", "") or "").strip()
            or str(getattr(batch, "preview_height_texture_path", "") or "").strip()
            for batch in batches
        )

    def textures_available(self) -> bool:
        batches = tuple(getattr(self._prepared_preview, "batches", ()) or ())
        return any(str(getattr(batch, "preview_texture_path", "") or "").strip() for batch in batches)

    def _iter_meshes(self) -> tuple[object, ...]:
        return tuple(getattr(self._current_model, "meshes", ()) or ())

    def base_flip_override_enabled(self) -> bool:
        return any(bool(getattr(mesh, "preview_debug_flip_base_v", False)) for mesh in self._iter_meshes())

    def support_maps_disabled(self) -> bool:
        return any(bool(getattr(mesh, "preview_debug_disable_support_maps", False)) for mesh in self._iter_meshes())

    def texture_slot_overrides_active(self) -> bool:
        for mesh in self._iter_meshes():
            for slot, current, default in (
                ("base", "preview_texture_path", "preview_base_texture_default_path"),
                ("normal", "preview_normal_texture_path", "preview_normal_texture_default_path"),
                ("material", "preview_material_texture_path", "preview_material_texture_default_path"),
                ("height", "preview_height_texture_path", "preview_height_texture_default_path"),
            ):
                if str(getattr(mesh, current, "") or "").strip() != str(getattr(mesh, default, "") or "").strip():
                    return True
        return False

    def debug_overrides_active(self) -> bool:
        return self.base_flip_override_enabled() or self.support_maps_disabled() or self.texture_slot_overrides_active()

    def set_base_texture_flip_override_enabled(self, enabled: bool) -> None:
        for mesh in self._iter_meshes():
            if isinstance(mesh, ModelPreviewMesh):
                mesh.preview_debug_flip_base_v = bool(enabled)

    def set_support_maps_disabled(self, enabled: bool) -> None:
        for mesh in self._iter_meshes():
            if isinstance(mesh, ModelPreviewMesh):
                mesh.preview_debug_disable_support_maps = bool(enabled)

    def set_texture_slot_override(self, material_name: object, slot: str, texture_path: object = "", texture_name: object = "", **_kwargs: object) -> None:
        normalized_material = str(material_name or "").strip().lower()
        slot_key = str(slot or "").strip().lower()
        path_text = str(texture_path or "").strip()
        name_text = str(texture_name or "").strip()
        field_map = {
            "base": ("preview_texture_path", "texture_name"),
            "normal": ("preview_normal_texture_path", "preview_normal_texture_name"),
            "material": ("preview_material_texture_path", "preview_material_texture_name"),
            "height": ("preview_height_texture_path", "preview_height_texture_name"),
        }
        fields = field_map.get(slot_key)
        if fields is None:
            return
        for mesh in self._iter_meshes():
            if not isinstance(mesh, ModelPreviewMesh):
                continue
            if normalized_material and str(getattr(mesh, "material_name", "") or "").strip().lower() != normalized_material:
                continue
            setattr(mesh, fields[0], path_text)
            if name_text:
                setattr(mesh, fields[1], name_text)

    @staticmethod
    def _normalize_physics_overlay_target(value: object) -> str:
        text = str(value or "").strip().replace("\\", "/").replace("#", "/").replace(":", "/").lower()
        parts = [part for part in text.split("/") if part]
        if len(parts) < 2:
            return ""
        kind = parts[0]
        if kind in {"hknpshape", "collisionshape", "collision_shape"}:
            kind = "shape"
        elif kind in {"constraintguide", "motor", "guide"}:
            kind = "constraint"
        elif kind in {"skeletonbone", "skeleton_bone"}:
            kind = "bone"
        if kind not in {"shape", "constraint", "anchor", "bone"}:
            return ""
        try:
            index = int(parts[1], 0)
        except (TypeError, ValueError):
            return ""
        return f"{kind}/{index}"

    def _physics_overlay_data(self) -> Optional[HkxPhysicsOverlayData]:
        model = self._current_model
        if not isinstance(model, ModelPreviewData):
            return None
        overlay = getattr(model, "physics_overlay", None)
        return overlay if isinstance(overlay, HkxPhysicsOverlayData) else None

    def _physics_overlay_target_info(self, viewer_id: object) -> Optional[tuple[str, str, int, str, str]]:
        normalized = self._normalize_physics_overlay_target(viewer_id)
        if not normalized:
            return None
        overlay = self._physics_overlay_data()
        if overlay is None:
            return None
        kind, index_text = normalized.split("/", 1)
        try:
            requested_index = int(index_text)
        except ValueError:
            return None
        if kind == "shape":
            for fallback_index, shape in enumerate(tuple(getattr(overlay, "shapes", ()) or ())):
                if not isinstance(shape, HkxPhysicsOverlayShape):
                    continue
                source_index = int(getattr(shape, "source_shape_index", fallback_index))
                if source_index < 0:
                    source_index = fallback_index
                if requested_index in {source_index, fallback_index}:
                    selected_index = source_index if source_index >= 0 else fallback_index
                    return (
                        "shape",
                        str(getattr(shape, "label", "") or ""),
                        selected_index,
                        str(getattr(shape, "source_path", "") or ""),
                        f"shape/{selected_index}",
                    )
        if kind == "constraint":
            constraints = tuple(getattr(overlay, "constraints", ()) or ())
            if 0 <= requested_index < len(constraints) and isinstance(constraints[requested_index], HkxPhysicsOverlayConstraint):
                constraint = constraints[requested_index]
                return (
                    "constraint",
                    str(getattr(constraint, "label", "") or ""),
                    requested_index,
                    str(getattr(constraint, "source_path", "") or ""),
                    f"constraint/{requested_index}",
                )
        if kind == "anchor":
            anchors = tuple(getattr(overlay, "anchors", ()) or ())
            if 0 <= requested_index < len(anchors) and isinstance(anchors[requested_index], HkxPhysicsOverlayAnchor):
                anchor = anchors[requested_index]
                return (
                    "anchor",
                    str(getattr(anchor, "label", "") or ""),
                    requested_index,
                    str(getattr(anchor, "source_path", "") or ""),
                    f"anchor/{requested_index}",
                )
        if kind == "bone" and self._physics_overlay_bones_visible:
            for fallback_index, bone in enumerate(tuple(getattr(overlay, "bones", ()) or ())):
                if not isinstance(bone, HkxPhysicsOverlayBone):
                    continue
                bone_index = int(getattr(bone, "index", fallback_index))
                if requested_index in {bone_index, fallback_index}:
                    selected_index = bone_index if bone_index >= 0 else fallback_index
                    return (
                        "bone",
                        str(getattr(bone, "name", "") or ""),
                        selected_index,
                        str(getattr(bone, "source_path", "") or ""),
                        f"bone/{selected_index}",
                    )
        return None

    def select_physics_overlay_target(
        self,
        viewer_id: object,
        *,
        label_hint: object = "",
        source_path_hint: object = "",
    ) -> bool:
        target = self._physics_overlay_target_info(viewer_id)
        if target is None:
            return False
        kind, label, index, source_path, normalized = target
        if label_hint and not label:
            label = str(label_hint or "")
        if source_path_hint and not source_path:
            source_path = str(source_path_hint or "")
        self._selected_physics_overlay_target = normalized
        self.physics_overlay_target_selected.emit(kind, label, index, source_path, normalized)
        return True

    def set_physics_overlay_edited_targets(self, viewer_selection_ids: object) -> None:
        self._physics_overlay_edited_targets = {
            target
            for target in (
                self._normalize_physics_overlay_target(value)
                for value in tuple(viewer_selection_ids or ())
            )
            if target
        }

    def physics_overlay_bones_visible(self) -> bool:
        return bool(self._physics_overlay_bones_visible)

    def set_physics_overlay_bones_visible(self, visible: bool) -> None:
        self._physics_overlay_bones_visible = bool(visible)
        if not self._physics_overlay_bones_visible and self._selected_physics_overlay_target.startswith("bone/"):
            self._selected_physics_overlay_target = ""

class PreviewScrollArea(QScrollArea):
    resized = Signal()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.resized.emit()


def _format_media_preview_time(value_ms: int) -> str:
    total_seconds = max(0, int(value_ms // 1000))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:d}:{seconds:02d}"


class MediaPreviewWidget(QWidget):
    def __init__(self, message: str, *, theme_key: str):
        super().__init__()
        self._message = message
        self._theme_key = theme_key
        self._media_path = ""
        self._media_kind = ""
        self._ignore_slider_update = False
        self._media_supported = bool(QMediaPlayer is not None and QAudioOutput is not None and QVideoWidget is not None)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.info_label = QLabel(message)
        self.info_label.setWordWrap(True)
        self.info_label.setObjectName("HintLabel")
        layout.addWidget(self.info_label)

        if self._media_supported:
            self.video_widget = QVideoWidget()
            self.video_widget.setMinimumHeight(220)
            layout.addWidget(self.video_widget, stretch=1)

            controls_row = QHBoxLayout()
            controls_row.setSpacing(8)
            self.play_button = QPushButton("Play")
            self.stop_button = QPushButton("Stop")
            self.position_slider = QSlider(Qt.Horizontal)
            self.position_slider.setRange(0, 0)
            self.time_label = QLabel("0:00 / 0:00")
            self.time_label.setObjectName("HintLabel")
            controls_row.addWidget(self.play_button)
            controls_row.addWidget(self.stop_button)
            controls_row.addWidget(self.position_slider, stretch=1)
            controls_row.addWidget(self.time_label)
            layout.addLayout(controls_row)

            self.audio_output = QAudioOutput(self)
            self.audio_output.setVolume(1.0)
            self.player = QMediaPlayer(self)
            self.player.setAudioOutput(self.audio_output)
            self.player.setVideoOutput(self.video_widget)
            self.player.positionChanged.connect(self._handle_position_changed)
            self.player.durationChanged.connect(self._handle_duration_changed)
            self.player.playbackStateChanged.connect(self._handle_playback_state_changed)
            self.player.mediaStatusChanged.connect(self._handle_media_status_changed)
            self.player.errorOccurred.connect(self._handle_error)

            self.play_button.clicked.connect(self._toggle_play_pause)
            self.stop_button.clicked.connect(self._stop_playback)
            self.position_slider.sliderPressed.connect(self._handle_slider_pressed)
            self.position_slider.sliderReleased.connect(self._handle_slider_released)
            self.position_slider.sliderMoved.connect(self._handle_slider_moved)
        else:
            self.video_widget = None
            self.play_button = QPushButton("Play")
            self.stop_button = QPushButton("Stop")
            self.position_slider = QSlider(Qt.Horizontal)
            self.time_label = QLabel("0:00 / 0:00")
            self.audio_output = None
            self.player = None

        self.clear_media(message)

    def set_theme(self, theme_key: str) -> None:
        self._theme_key = theme_key

    def clear_media(self, message: str) -> None:
        self._message = message
        self._media_path = ""
        self._media_kind = ""
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl())
        if self.video_widget is not None:
            self.video_widget.setVisible(False)
        self.info_label.setText(message)
        self.play_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.position_slider.setEnabled(False)
        self.position_slider.setRange(0, 0)
        self.position_slider.setValue(0)
        self.time_label.setText("0:00 / 0:00")

    def shutdown(self) -> None:
        self.clear_media(self._message)

    def set_media(self, media_path: str, *, media_kind: str, detail_text: str = "") -> None:
        normalized_path = str(media_path or "").strip()
        normalized_kind = str(media_kind or "").strip().lower()
        if not normalized_path:
            self.clear_media(detail_text or "No media preview available.")
            return

        self._media_path = normalized_path
        self._media_kind = normalized_kind

        if not self._media_supported:
            self.info_label.setText(
                "Qt Multimedia is not available in this build.\n\n"
                + (detail_text or normalized_path)
            )
            self.play_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            self.position_slider.setEnabled(False)
            return

        self.info_label.setText(detail_text or normalized_path)
        if self.video_widget is not None:
            self.video_widget.setVisible(normalized_kind == "video")
        self.play_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self.position_slider.setEnabled(True)
        self.position_slider.setRange(0, 0)
        self.position_slider.setValue(0)
        self.time_label.setText("0:00 / 0:00")
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(normalized_path))
        self.player.play()

    def _toggle_play_pause(self) -> None:
        if self.player is None:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _stop_playback(self) -> None:
        if self.player is None:
            return
        self.player.stop()

    def _handle_slider_pressed(self) -> None:
        self._ignore_slider_update = True

    def _handle_slider_released(self) -> None:
        if self.player is not None:
            self.player.setPosition(int(self.position_slider.value()))
        self._ignore_slider_update = False

    def _handle_slider_moved(self, value: int) -> None:
        duration = self.position_slider.maximum()
        self.time_label.setText(f"{_format_media_preview_time(value)} / {_format_media_preview_time(duration)}")

    def _handle_position_changed(self, position: int) -> None:
        if not self._ignore_slider_update:
            self.position_slider.setValue(int(position))
        duration = self.position_slider.maximum()
        self.time_label.setText(f"{_format_media_preview_time(position)} / {_format_media_preview_time(duration)}")

    def _handle_duration_changed(self, duration: int) -> None:
        self.position_slider.setRange(0, max(0, int(duration)))
        position = self.position_slider.value()
        self.time_label.setText(f"{_format_media_preview_time(position)} / {_format_media_preview_time(duration)}")

    def _handle_playback_state_changed(self, state) -> None:
        if QMediaPlayer is None:
            return
        self.play_button.setText("Pause" if state == QMediaPlayer.PlayingState else "Play")

    def _handle_media_status_changed(self, status) -> None:
        if QMediaPlayer is None:
            return
        if status == QMediaPlayer.EndOfMedia:
            self.play_button.setText("Play")

    def _handle_error(self, _error, error_text: str) -> None:
        message = str(error_text or "").strip() or "The multimedia backend could not open this file."
        if self._media_kind == "audio":
            message += "\n\nSome Wwise `.wem` variants are not supported by the local Qt Multimedia backend."
        self.info_label.setText(message + (f"\n\nSource: {self._media_path}" if self._media_path else ""))


def _theme_is_light(theme_key: str) -> bool:
    theme = get_theme(theme_key)
    color = QColor(theme["window"])
    return color.lightnessF() >= 0.55


_TEXT_HIGHLIGHT_STYLES = {"rich", "calm", "plain"}
_TEXT_COLOR_SCHEMES = {"theme", "vscode", "terminal", "accessible", "solarized"}


def _normalize_text_highlight_style(style: object) -> str:
    value = str(style or "rich").strip().lower()
    return value if value in _TEXT_HIGHLIGHT_STYLES else "rich"


def _normalize_text_color_scheme(scheme: object) -> str:
    value = str(scheme or "theme").strip().lower()
    return value if value in _TEXT_COLOR_SCHEMES else "theme"


def _scheme_palette(theme_key: str, scheme: object) -> Optional[Dict[str, str]]:
    normalized = _normalize_text_color_scheme(scheme)
    if normalized == "theme":
        return None
    light = _theme_is_light(theme_key)
    if normalized == "terminal":
        return {
            "comment": "#6b7280" if light else "#7dd3fc",
            "keyword": "#7c3aed" if light else "#f0abfc",
            "string": "#047857" if light else "#86efac",
            "number": "#b45309" if light else "#fbbf24",
            "tag": "#0369a1" if light else "#93c5fd",
            "attribute": "#be123c" if light else "#fda4af",
            "section": "#0f766e" if light else "#5eead4",
            "key": "#b45309" if light else "#fde68a",
            "entity": "#9333ea" if light else "#d8b4fe",
            "bracket": "#4b5563" if light else "#d1d5db",
            "success": "#047857" if light else "#22c55e",
            "warning": "#a16207" if light else "#facc15",
            "error": "#b91c1c" if light else "#f87171",
        }
    if normalized == "accessible":
        return {
            "comment": "#525252" if light else "#bdbdbd",
            "keyword": "#0000aa" if light else "#8ab4ff",
            "string": "#006400" if light else "#b7f7c1",
            "number": "#7a3e00" if light else "#ffd27d",
            "tag": "#003f8c" if light else "#9bd1ff",
            "attribute": "#6f1d8f" if light else "#e3b5ff",
            "section": "#004d40" if light else "#9ff7e8",
            "key": "#5f3700" if light else "#ffe08a",
            "entity": "#7a3e00" if light else "#ffd27d",
            "bracket": "#333333" if light else "#eeeeee",
            "success": "#006400" if light else "#76ff7a",
            "warning": "#8a5a00" if light else "#ffdd57",
            "error": "#a00000" if light else "#ff8a80",
        }
    if normalized == "solarized":
        return {
            "comment": "#657b83",
            "keyword": "#6c71c4",
            "string": "#2aa198",
            "number": "#d33682",
            "tag": "#268bd2",
            "attribute": "#b58900",
            "section": "#859900",
            "key": "#b58900",
            "entity": "#cb4b16",
            "bracket": "#839496",
            "success": "#859900",
            "warning": "#b58900",
            "error": "#dc322f",
        }
    return {
        "comment": "#008000" if light else "#6a9955",
        "keyword": "#af00db" if light else "#c586c0",
        "string": "#a31515" if light else "#ce9178",
        "number": "#098658" if light else "#b5cea8",
        "tag": "#0451a5" if light else "#569cd6",
        "attribute": "#001080" if light else "#9cdcfe",
        "section": "#795e26" if light else "#4ec9b0",
        "key": "#001080" if light else "#9cdcfe",
        "entity": "#795e26" if light else "#d7ba7d",
        "bracket": "#333333" if light else "#d4d4d4",
        "success": "#098658" if light else "#6a9955",
        "warning": "#b45309" if light else "#fbbf24",
        "error": "#c0362c" if light else "#f48771",
    }


class PreviewSyntaxHighlighter(QSyntaxHighlighter):
    CSS_TEXT_EXTENSIONS = {".css"}
    XML_TEXT_EXTENSIONS = {".xml", ".html", ".thtml", ".material", ".shader"}
    JSON_TEXT_EXTENSIONS = {".json", ".yaml", ".yml"}
    INI_TEXT_EXTENSIONS = {".ini", ".cfg"}
    PALOC_TEXT_EXTENSIONS = {".paloc"}
    LUA_TEXT_EXTENSIONS = {".lua"}
    PLAIN_SECTION_RE = re.compile(
        r"^\s*(?:[A-Z][A-Za-z0-9 /()_.-]+:|[A-Z][^\r\n:]{0,96}\bpreview for\b.+)\s*$"
    )
    PLAIN_LABEL_RE = re.compile(r"^\s*(?:[-*]\s*)?([A-Za-z][A-Za-z0-9 /()_.-]{0,72}:)")
    PLAIN_KEY_VALUE_RE = re.compile(r"\b([A-Za-z_][\w.-]*)(=)([^\s,;)]+)")
    PLAIN_WINDOWS_PATH_RE = re.compile(r"[A-Za-z]:\\[^\r\n<>|\"*?]+")
    PLAIN_RELATIVE_PATH_RE = re.compile(r"(?<![\w.-])(?:[\w.-]+[\\/]){1,}[\w./\\-]+")
    PLAIN_ASSET_FILE_RE = re.compile(
        r"(?<![\w./\\-])[\w.-]+\.(?:cfg|dds|fbx|hkt|hkx|ini|jpg|jpeg|json|lua|material|obj|pac|pam|pamlod|pamt|png|shader|tga|xml|yaml|yml)\b",
        re.IGNORECASE,
    )
    PLAIN_HEX_VALUE_RE = re.compile(r"\b0x[0-9A-Fa-f]+\b")
    PLAIN_NUMBER_RE = re.compile(r"(?<![\w./\\-])-?\b\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?\b")
    PLAIN_HAVOK_TYPE_RE = re.compile(r"\bhk[A-Za-z0-9_:<>.-]+\b")
    PLAIN_CONSTANT_RE = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
    PLAIN_WARNING_RE = re.compile(
        r"\b(warning|warn|missing|failed|failure|unsupported|truncated|unavailable|fallback|skipped|review|likely grey)\b",
        re.IGNORECASE,
    )
    PLAIN_ERROR_RE = re.compile(r"\b(error|exception|traceback|invalid|corrupt|crash)\b", re.IGNORECASE)
    PLAIN_SUCCESS_RE = re.compile(r"\b(ready|success|successful|complete|completed|detected|matches|editable)\b", re.IGNORECASE)

    LUA_KEYWORDS = {
        "and", "break", "do", "else", "elseif", "end", "false", "for", "function", "if", "in",
        "local", "nil", "not", "or", "repeat", "return", "then", "true", "until", "while",
    }

    def __init__(self, document, theme_key: str, highlight_style: str = "rich", color_scheme: str = "theme"):
        super().__init__(document)
        self.language = "plain"
        self.highlight_style = _normalize_text_highlight_style(highlight_style)
        self.color_scheme = _normalize_text_color_scheme(color_scheme)
        self.comment_format = QTextCharFormat()
        self.keyword_format = QTextCharFormat()
        self.string_format = QTextCharFormat()
        self.number_format = QTextCharFormat()
        self.tag_format = QTextCharFormat()
        self.attribute_format = QTextCharFormat()
        self.section_format = QTextCharFormat()
        self.key_format = QTextCharFormat()
        self.entity_format = QTextCharFormat()
        self.bracket_format = QTextCharFormat()
        self.path_format = QTextCharFormat()
        self.success_format = QTextCharFormat()
        self.warning_format = QTextCharFormat()
        self.error_format = QTextCharFormat()
        self.set_theme(theme_key)

    def set_theme(self, theme_key: str) -> None:
        self.current_theme_key = theme_key
        light = _theme_is_light(theme_key)
        theme = get_theme(theme_key)
        calm = self.highlight_style == "calm"

        def make(color: str, *, bold: bool = False, italic: bool = False) -> QTextCharFormat:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold and not calm:
                fmt.setFontWeight(QFont.Bold)
            fmt.setFontItalic(italic)
            return fmt

        scheme = None
        if self.highlight_style == "plain":
            base_color = theme["text"]
            self.comment_format = make(base_color)
            self.keyword_format = make(base_color)
            self.string_format = make(base_color)
            self.number_format = make(base_color)
            self.tag_format = make(base_color)
            self.attribute_format = make(base_color)
            self.section_format = make(base_color)
            self.key_format = make(base_color)
            self.entity_format = make(base_color)
            self.bracket_format = make(base_color)
        else:
            scheme = _scheme_palette(theme_key, self.color_scheme)
        if self.highlight_style == "plain":
            pass
        elif scheme is not None:
            self.comment_format = make(scheme["comment"], italic=True)
            self.keyword_format = make(scheme["keyword"], bold=True)
            self.string_format = make(scheme["string"])
            self.number_format = make(scheme["number"])
            self.tag_format = make(scheme["tag"], bold=True)
            self.attribute_format = make(scheme["attribute"])
            self.section_format = make(scheme["section"], bold=True)
            self.key_format = make(scheme["key"])
            self.entity_format = make(scheme["entity"])
            self.bracket_format = make(scheme["bracket"])
        elif calm:
            self.comment_format = make(theme["text_muted"], italic=True)
            self.keyword_format = make(theme["accent"])
            self.string_format = make("#8a4b32" if light else "#c49a8b")
            self.number_format = make("#3f7f5f" if light else "#9bbf9d")
            self.tag_format = make(theme["accent"])
            self.attribute_format = make(theme["text_strong"])
            self.section_format = make(theme["accent"])
            self.key_format = make(theme["text_strong"])
            self.entity_format = make(theme["warning_text"])
            self.bracket_format = make(theme["text_muted"])
        elif light:
            self.comment_format = make("#008000", italic=True)
            self.keyword_format = make("#af00db", bold=True)
            self.string_format = make("#a31515")
            self.number_format = make("#098658")
            self.tag_format = make("#0451a5", bold=True)
            self.attribute_format = make("#001080")
            self.section_format = make("#795e26", bold=True)
            self.key_format = make("#001080")
            self.entity_format = make("#795e26")
            self.bracket_format = make("#333333")
        else:
            self.comment_format = make("#6a9955", italic=True)
            self.keyword_format = make("#c586c0", bold=True)
            self.string_format = make("#ce9178")
            self.number_format = make("#b5cea8")
            self.tag_format = make("#569cd6", bold=True)
            self.attribute_format = make("#9cdcfe")
            self.section_format = make("#4ec9b0", bold=True)
            self.key_format = make("#9cdcfe")
            self.entity_format = make("#d7ba7d")
            self.bracket_format = make("#d4d4d4")
        if self.highlight_style == "plain":
            self.path_format = make(theme["text"])
            self.success_format = make(theme["text"])
            self.warning_format = make(theme["text"])
            self.error_format = make(theme["text"])
        else:
            active_scheme = scheme or {}
            self.path_format = make(theme["text_strong"], bold=True)
            self.success_format = make(active_scheme.get("success", "#098658" if light else "#6a9955"), bold=True)
            self.warning_format = make(active_scheme.get("warning", theme["warning_text"]), bold=True)
            self.error_format = make(active_scheme.get("error", theme["error"]), bold=True)
        self.rehighlight()

    def set_highlight_style(self, style: str) -> None:
        normalized = _normalize_text_highlight_style(style)
        if normalized == self.highlight_style:
            return
        self.highlight_style = normalized
        self.set_theme(getattr(self, "current_theme_key", "") or "graphite")

    def set_color_scheme(self, scheme: str) -> None:
        normalized = _normalize_text_color_scheme(scheme)
        if normalized == self.color_scheme:
            return
        self.color_scheme = normalized
        self.set_theme(getattr(self, "current_theme_key", "") or "graphite")

    def set_language_for_extension(self, extension: str) -> None:
        suffix = (extension or "").lower()
        if suffix in self.CSS_TEXT_EXTENSIONS:
            self.language = "css"
        elif suffix in self.XML_TEXT_EXTENSIONS:
            self.language = "xml"
        elif suffix in self.JSON_TEXT_EXTENSIONS:
            self.language = "json"
        elif suffix in self.INI_TEXT_EXTENSIONS or suffix in self.PALOC_TEXT_EXTENSIONS:
            self.language = "ini"
        elif suffix in self.LUA_TEXT_EXTENSIONS:
            self.language = "lua"
        else:
            self.language = "plain"
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # type: ignore[override]
        if self.highlight_style == "plain":
            return
        if self.language == "css":
            self._highlight_css(text)
        elif self.language == "xml":
            self._highlight_xml(text)
        elif self.language == "json":
            self._highlight_json(text)
        elif self.language == "ini":
            self._highlight_ini(text)
        elif self.language == "lua":
            self._highlight_lua(text)
        else:
            self._highlight_plain_preview(text)

    def _highlight_plain_preview(self, text: str) -> None:
        if not text.strip():
            return

        section_match = self.PLAIN_SECTION_RE.match(text)
        if section_match:
            self.setFormat(0, len(text), self.section_format)

        label_match = self.PLAIN_LABEL_RE.match(text)
        if label_match:
            start, end = label_match.span(1)
            self.setFormat(start, end - start, self.key_format)

        for match in re.finditer(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", text):
            self.setFormat(match.start(), match.end() - match.start(), self.string_format)

        for match in self.PLAIN_KEY_VALUE_RE.finditer(text):
            key_start, key_end = match.span(1)
            equals_start, equals_end = match.span(2)
            value_start, value_end = match.span(3)
            self.setFormat(key_start, key_end - key_start, self.key_format)
            self.setFormat(equals_start, equals_end - equals_start, self.bracket_format)
            self.setFormat(value_start, value_end - value_start, self.string_format)

        for match in self.PLAIN_CONSTANT_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.tag_format)
        for match in self.PLAIN_HAVOK_TYPE_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.entity_format)
        for match in self.PLAIN_HEX_VALUE_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.number_format)
        for match in self.PLAIN_NUMBER_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.number_format)
        for match in self.PLAIN_WINDOWS_PATH_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.path_format)
        for match in self.PLAIN_RELATIVE_PATH_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.path_format)
        for match in self.PLAIN_ASSET_FILE_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.path_format)

        for match in self.PLAIN_SUCCESS_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.success_format)
        for match in self.PLAIN_WARNING_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.warning_format)
        for match in self.PLAIN_ERROR_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.error_format)

    def _highlight_xml(self, text: str) -> None:
        self.setCurrentBlockState(0)
        for match in re.finditer(r"</?[\w:.-]+", text):
            self.setFormat(match.start(), match.end() - match.start(), self.tag_format)
        for match in re.finditer(r"</?|/?>", text):
            self.setFormat(match.start(), match.end() - match.start(), self.bracket_format)
        for match in re.finditer(r"\b[\w:.-]+(?=\s*=)", text):
            self.setFormat(match.start(), match.end() - match.start(), self.attribute_format)
        for match in re.finditer(r"\"[^\"\n]*\"|'[^'\n]*'", text):
            self.setFormat(match.start(), match.end() - match.start(), self.string_format)
        for match in re.finditer(r"&[#\w]+;", text):
            self.setFormat(match.start(), match.end() - match.start(), self.entity_format)

        start_index = 0 if self.previousBlockState() == 1 else text.find("<!--")
        while start_index >= 0:
            end_index = text.find("-->", start_index)
            if end_index == -1:
                self.setCurrentBlockState(1)
                self.setFormat(start_index, len(text) - start_index, self.comment_format)
                break
            length = end_index - start_index + 3
            self.setFormat(start_index, length, self.comment_format)
            start_index = text.find("<!--", end_index + 3)

    def _highlight_css(self, text: str) -> None:
        self.setCurrentBlockState(0)

        start_index = 0 if self.previousBlockState() == 1 else text.find("/*")
        while start_index >= 0:
            end_index = text.find("*/", start_index + 2)
            if end_index == -1:
                self.setCurrentBlockState(1)
                self.setFormat(start_index, len(text) - start_index, self.comment_format)
                break
            length = end_index - start_index + 2
            self.setFormat(start_index, length, self.comment_format)
            start_index = text.find("/*", end_index + 2)

        selector_match = re.match(r"\s*([^{]+?)(?=\s*\{)", text)
        if selector_match:
            self.setFormat(selector_match.start(1), selector_match.end(1) - selector_match.start(1), self.tag_format)
        for match in re.finditer(r"(?<=\{|;)\s*([-\w]+)(?=\s*:)", text):
            self.setFormat(match.start(1), match.end(1) - match.start(1), self.attribute_format)
        for match in re.finditer(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", text):
            self.setFormat(match.start(), match.end() - match.start(), self.string_format)
        for match in re.finditer(r"#[0-9A-Fa-f]{3,8}\b|(?<![\w.])-?\b\d+(?:\.\d+)?(?:px|em|rem|vh|vw|%)?\b", text):
            self.setFormat(match.start(), match.end() - match.start(), self.number_format)

    def _highlight_json(self, text: str) -> None:
        for match in re.finditer(r'"(?:\\.|[^"\\])*"(?=\s*:)', text):
            self.setFormat(match.start(), match.end() - match.start(), self.key_format)
        for match in re.finditer(r'"(?:\\.|[^"\\])*"', text):
            self.setFormat(match.start(), match.end() - match.start(), self.string_format)
        for match in re.finditer(r"\b(true|false|null)\b", text):
            self.setFormat(match.start(), match.end() - match.start(), self.keyword_format)
        for match in re.finditer(r"(?<![\w.])-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b", text):
            self.setFormat(match.start(), match.end() - match.start(), self.number_format)

    def _highlight_ini(self, text: str) -> None:
        comment_match = re.match(r"\s*[;#].*$", text)
        if comment_match:
            self.setFormat(comment_match.start(), comment_match.end() - comment_match.start(), self.comment_format)
            return
        section_match = re.match(r"\s*\[[^\]]+\]", text)
        if section_match:
            self.setFormat(section_match.start(), section_match.end() - section_match.start(), self.section_format)
            return
        key_match = re.match(r"\s*[^=:#\s][^=:#]*?(?=\s*[=:])", text)
        if key_match:
            self.setFormat(key_match.start(), key_match.end() - key_match.start(), self.key_format)
        for match in re.finditer(r"\"[^\"\n]*\"|'[^'\n]*'", text):
            self.setFormat(match.start(), match.end() - match.start(), self.string_format)
        for match in re.finditer(r"(?<![\w.])-?\b\d+(?:\.\d+)?\b", text):
            self.setFormat(match.start(), match.end() - match.start(), self.number_format)

    def _highlight_lua(self, text: str) -> None:
        comment_match = re.search(r"--.*$", text)
        text_no_comment = text[: comment_match.start()] if comment_match else text
        for match in re.finditer(r"\b(" + "|".join(sorted(self.LUA_KEYWORDS)) + r")\b", text_no_comment):
            self.setFormat(match.start(), match.end() - match.start(), self.keyword_format)
        for match in re.finditer(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", text_no_comment):
            self.setFormat(match.start(), match.end() - match.start(), self.string_format)
        for match in re.finditer(r"(?<![\w.])-?\b\d+(?:\.\d+)?\b", text_no_comment):
            self.setFormat(match.start(), match.end() - match.start(), self.number_format)
        if comment_match:
            self.setFormat(comment_match.start(), comment_match.end() - comment_match.start(), self.comment_format)


class _LineNumberArea(QWidget):
    def __init__(self, editor: "CodePreviewEditor"):
        super().__init__(editor)
        self.code_editor = editor

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(self.code_editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        self.code_editor.line_number_area_paint_event(event)


class CodePreviewEditor(QPlainTextEdit):
    def __init__(
        self,
        *,
        theme_key: str,
        parent: Optional[QWidget] = None,
        highlight_style: str = "rich",
        color_scheme: str = "theme",
    ):
        super().__init__(parent)
        self.theme_key = theme_key
        self._highlight_style = _normalize_text_highlight_style(highlight_style)
        self._color_scheme = _normalize_text_color_scheme(color_scheme)
        self._match_selections: list[QTextEdit.ExtraSelection] = []
        self._search_query = ""
        self._search_matches: list[Tuple[int, int]] = []
        self._current_search_index = -1
        self._editor_font_size = max(8, self.font().pointSize())
        self.line_number_area = _LineNumberArea(self)
        self.syntax_highlighter = PreviewSyntaxHighlighter(
            self.document(),
            theme_key,
            self._highlight_style,
            self._color_scheme,
        )
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = QFont("Consolas")
        if not font.exactMatch():
            font = QFont("Courier New")
        font.setPointSize(self._editor_font_size)
        self._apply_editor_font(font)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self._apply_combined_selections)
        self.update_line_number_area_width(0)
        self.set_theme(theme_key)

    def setPlainText(self, text: str) -> None:  # type: ignore[override]
        self._replace_plain_text_safely(str(text or ""))

    def _replace_plain_text_safely(self, text: str) -> None:
        highlighter = getattr(self, "syntax_highlighter", None)
        document = self.document()
        previous_updates_enabled = self.updatesEnabled()
        self._match_selections = []
        self._search_query = ""
        self._search_matches = []
        self._current_search_index = -1
        self.setUpdatesEnabled(False)
        widget_blocker = QSignalBlocker(self)
        document_blocker = QSignalBlocker(document)
        detached_highlighter = False
        try:
            if highlighter is not None and hasattr(highlighter, "setDocument"):
                highlighter.setDocument(None)
                detached_highlighter = True
            super().setPlainText(text)
        finally:
            if detached_highlighter:
                highlighter.setDocument(document)
                if hasattr(highlighter, "rehighlight"):
                    highlighter.rehighlight()
            del document_blocker
            del widget_blocker
            self.setUpdatesEnabled(previous_updates_enabled)
            self.update_line_number_area_width(0)
            self.viewport().update()
            self.line_number_area.update()
            self._apply_combined_selections()

    def line_number_area_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self, _new_block_count: int) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy: int) -> None:
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def line_number_area_paint_event(self, event) -> None:
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), self._gutter_background)

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        current_block_number = self.textCursor().blockNumber()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                if block_number == current_block_number:
                    painter.setPen(self._line_number_active_color)
                    font = painter.font()
                    font.setBold(True)
                    painter.setFont(font)
                else:
                    painter.setPen(self._line_number_color)
                    font = painter.font()
                    font.setBold(False)
                    painter.setFont(font)
                painter.drawText(
                    0,
                    top,
                    self.line_number_area.width() - 6,
                    self.fontMetrics().height(),
                    Qt.AlignRight | Qt.AlignVCenter,
                    number,
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

    def set_match_selections(self, selections: list[QTextEdit.ExtraSelection]) -> None:
        self._match_selections = list(selections)
        self._apply_combined_selections()

    def _apply_combined_selections(self) -> None:
        selections = []
        if not self.isReadOnly():
            super().setExtraSelections(self._match_selections)
            return
        current_line = QTextEdit.ExtraSelection()
        current_line.format.setBackground(self._current_line_color)
        current_line.format.setProperty(QTextFormat.FullWidthSelection, True)
        current_line.cursor = self.textCursor()
        current_line.cursor.clearSelection()
        selections.append(current_line)
        selections.extend(self._match_selections)
        super().setExtraSelections(selections)
        self.line_number_area.update()

    def set_theme(self, theme_key: str) -> None:
        self.theme_key = theme_key
        theme = get_theme(theme_key)
        self._gutter_background = QColor(theme["surface_alt"])
        self._line_number_color = QColor(theme["text_muted"])
        self._line_number_active_color = QColor(theme["accent"])
        self._current_line_color = QColor(theme["accent_soft"])
        self._search_match_color = QColor(theme["warning_text"])
        self._search_match_color.setAlpha(100)
        self._search_current_match_color = QColor(theme["accent"])
        self._search_current_match_color.setAlpha(150)
        self.syntax_highlighter.set_theme(theme_key)
        self.setStyleSheet(
            f"QPlainTextEdit {{ background: {theme['preview_bg']}; color: {theme['text']}; border: 1px solid {theme['border_strong']}; border-radius: 4px; selection-background-color: {theme['accent']}; selection-color: #ffffff; }}"
        )
        self.viewport().update()
        self.line_number_area.update()
        self._apply_combined_selections()

    def set_highlight_style(self, style: str) -> None:
        self._highlight_style = _normalize_text_highlight_style(style)
        if hasattr(self.syntax_highlighter, "set_highlight_style"):
            self.syntax_highlighter.set_highlight_style(self._highlight_style)

    def set_color_scheme(self, scheme: str) -> None:
        self._color_scheme = _normalize_text_color_scheme(scheme)
        if hasattr(self.syntax_highlighter, "set_color_scheme"):
            self.syntax_highlighter.set_color_scheme(self._color_scheme)
        else:
            self.syntax_highlighter.rehighlight()

    def set_language_for_extension(self, extension: str) -> None:
        self.syntax_highlighter.set_language_for_extension(extension)

    def set_wrap_enabled(self, enabled: bool) -> None:
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth if enabled else QPlainTextEdit.NoWrap)

    def search_text(self, query: str, *, jump: bool = True) -> Tuple[int, int]:
        self._search_query = str(query or "")
        self._rebuild_search_matches(jump=jump)
        return self.search_result()

    def find_next_match(self) -> Tuple[int, int]:
        if not self._search_matches:
            return self.search_result()
        self._current_search_index = (self._current_search_index + 1) % len(self._search_matches)
        self._apply_search_selection(jump=True)
        return self.search_result()

    def find_previous_match(self) -> Tuple[int, int]:
        if not self._search_matches:
            return self.search_result()
        self._current_search_index = (self._current_search_index - 1) % len(self._search_matches)
        self._apply_search_selection(jump=True)
        return self.search_result()

    def clear_search(self) -> None:
        self._search_query = ""
        self._search_matches = []
        self._current_search_index = -1
        self.set_match_selections([])

    def search_result(self) -> Tuple[int, int]:
        if not self._search_matches:
            return (0, 0)
        return (self._current_search_index + 1, len(self._search_matches))

    def _rebuild_search_matches(self, *, jump: bool) -> None:
        query = self._search_query
        if not query:
            self.clear_search()
            return
        haystack = self.toPlainText()
        lowered_haystack = haystack.lower()
        lowered_query = query.lower()
        matches: list[Tuple[int, int]] = []
        start = 0
        while True:
            index = lowered_haystack.find(lowered_query, start)
            if index < 0:
                break
            end = index + len(query)
            matches.append((index, end))
            start = max(index + len(query), index + 1)
        self._search_matches = matches
        self._current_search_index = 0 if matches else -1
        self._apply_search_selection(jump=jump and bool(matches))

    def _apply_search_selection(self, *, jump: bool) -> None:
        selections: list[QTextEdit.ExtraSelection] = []
        for match_index, (start, end) in enumerate(self._search_matches):
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(
                self._search_current_match_color
                if match_index == self._current_search_index
                else self._search_match_color
            )
            cursor = self.textCursor()
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.KeepAnchor)
            selection.cursor = cursor
            selections.append(selection)
        self.set_match_selections(selections)
        if jump and 0 <= self._current_search_index < len(self._search_matches):
            start, end = self._search_matches[self._current_search_index]
            self.center_on_span(start, end)

    def adjust_font_size(self, delta: int) -> int:
        self._editor_font_size = max(8, min(22, self._editor_font_size + delta))
        font = self.font()
        font.setPointSize(self._editor_font_size)
        self._apply_editor_font(font)
        return self._editor_font_size

    def set_font_size(self, size: int) -> int:
        self._editor_font_size = max(8, min(22, size))
        font = self.font()
        font.setPointSize(self._editor_font_size)
        self._apply_editor_font(font)
        return self._editor_font_size

    def apply_font_preferences(self, font: QFont, *, preserve_size: bool = False) -> None:
        updated_font = QFont(font)
        if preserve_size:
            updated_font.setPointSize(self._editor_font_size)
        else:
            self._editor_font_size = max(8, min(22, updated_font.pointSize()))
        self._apply_editor_font(updated_font)

    def center_on_span(self, start: int, end: int) -> None:
        cursor = self.textCursor()
        cursor.setPosition(max(0, start))
        cursor.setPosition(max(start, end), QTextCursor.KeepAnchor)
        self.setTextCursor(cursor)
        self.centerCursor()

    def _apply_editor_font(self, font: QFont) -> None:
        self.setFont(font)
        self.document().setDefaultFont(font)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self.update_line_number_area_width(0)
        self.viewport().update()
        self.line_number_area.update()
        self.syntax_highlighter.rehighlight()


class LogHighlighter(QSyntaxHighlighter):
    _timestamp_re = re.compile(r"^\[\d{2}:\d{2}:\d{2}\]")
    _error_re = re.compile(r"\b(ERROR|Traceback|Exception|FAILED|failure|fatal)\b", re.IGNORECASE)
    _warning_re = re.compile(r"\b(warning|preflight|skip|skipped)\b", re.IGNORECASE)
    _success_re = re.compile(r"\b(complete|completed|finished|ready|successfully|correct)\b", re.IGNORECASE)
    _phase_re = re.compile(r"\bPhase\s+\d+/\d+\b", re.IGNORECASE)
    _windows_path_re = re.compile(r"[A-Za-z]:\\[^\r\n<>|\"*?]+")
    _relative_path_re = re.compile(r"(?<![\w.-])(?:[\w.-]+[\\/]){2,}[\w.-]+")
    _progress_re = re.compile(r"\[\d+/\d+\]|\b\d+(?:[.,]\d+)?%")
    _action_re = re.compile(
        r"\b(UPSCALE|BUILD|COPY|DRYRUN|SYNCING|INDEXING|SCANNING|STARTING|RUNNING|LOADING|REFRESHING|EXTRACTING|CONVERTING|VALIDATING|RETRYING|FOUND)\b",
        re.IGNORECASE,
    )
    _backend_re = re.compile(r"\b(Real-ESRGAN NCNN|chaiNNer|texconv(?:\.exe)?)\b", re.IGNORECASE)
    _correction_mode_re = re.compile(
        r"\b(Match Mean Luma|Match Levels|Match Histogram|Source Match Balanced|Source Match Extended|Source Match Experimental)\b",
        re.IGNORECASE,
    )
    _texture_type_re = re.compile(r"\[(color|ui|emissive|impostor|normal|height|vector|roughness|mask|unknown)\]")
    _key_value_re = re.compile(r"\b([a-z_]+)=([^\s,;()]+)", re.IGNORECASE)
    _label_re = re.compile(
        r"\b(scale|tile|preset|model|format|mips|output|png|backend|correction|mean|range|source|providers?|folder|executable|input|root)\b",
        re.IGNORECASE,
    )
    _dimension_re = re.compile(r"\b\d+x\d+\b")
    _number_re = re.compile(r"(?<![\w./\\-])\d+(?:[.,]\d+)?\b")
    _arrow_re = re.compile(r"->")

    def __init__(self, document, theme_key: str, highlight_style: str = "rich", color_scheme: str = "theme"):
        super().__init__(document)
        self.current_theme_key = theme_key
        self._bold_enabled = True
        self.highlight_style = _normalize_text_highlight_style(highlight_style)
        self.color_scheme = _normalize_text_color_scheme(color_scheme)
        self.timestamp_format = QTextCharFormat()
        self.error_format = QTextCharFormat()
        self.warning_format = QTextCharFormat()
        self.success_format = QTextCharFormat()
        self.phase_format = QTextCharFormat()
        self.path_format = QTextCharFormat()
        self.progress_format = QTextCharFormat()
        self.action_format = QTextCharFormat()
        self.backend_format = QTextCharFormat()
        self.key_format = QTextCharFormat()
        self.value_format = QTextCharFormat()
        self.number_format = QTextCharFormat()
        self.separator_format = QTextCharFormat()
        self.error_line_format = QTextCharFormat()
        self.warning_line_format = QTextCharFormat()
        self.success_line_format = QTextCharFormat()
        self.texture_type_formats: dict[str, QTextCharFormat] = {}
        self.set_theme(theme_key)

    def set_theme(self, theme_key: str) -> None:
        self.current_theme_key = theme_key
        theme = get_theme(theme_key)
        light = _theme_is_light(theme_key)
        calm = self.highlight_style == "calm"
        scheme = _scheme_palette(theme_key, self.color_scheme)

        def make_format(
            color: str,
            *,
            bold: bool = False,
            italic: bool = False,
            background: Optional[QColor] = None,
        ) -> QTextCharFormat:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold and self._bold_enabled and not calm:
                fmt.setFontWeight(QFont.Bold)
            fmt.setFontItalic(italic)
            if background is not None:
                fmt.setBackground(background)
            return fmt

        self.timestamp_format = make_format(theme["text_muted"])
        self.error_format = make_format((scheme or {}).get("error", theme["error"] if not calm else theme["warning_text"]), bold=True)
        self.warning_format = make_format((scheme or {}).get("warning", theme["warning_text"]), bold=True)
        self.success_format = make_format((scheme or {}).get("success", "#098658" if light else "#6a9955"), bold=True)
        self.phase_format = make_format((scheme or {}).get("tag", theme["accent"]), bold=True)
        self.path_format = make_format(theme["text_strong"], bold=True)
        self.progress_format = make_format((scheme or {}).get("number", theme["accent"]), bold=True)
        self.action_format = make_format((scheme or {}).get("keyword", "#0451a5" if light else "#569cd6"), bold=True)
        self.backend_format = make_format((scheme or {}).get("tag", theme["accent"]), bold=True)
        self.key_format = make_format((scheme or {}).get("key", "#795e26" if light else "#d7ba7d"), bold=True)
        self.value_format = make_format((scheme or {}).get("string", "#a31515" if light else "#ce9178"))
        self.number_format = make_format((scheme or {}).get("number", "#098658" if light else "#b5cea8"))
        self.separator_format = make_format(theme["text_muted"], bold=True)

        warning_bg = QColor(theme["warning_bg"])
        warning_bg.setAlpha(36 if calm else (70 if light else 48))
        error_bg = QColor(theme["error"])
        error_bg.setAlpha(22 if calm else (42 if light else 34))
        success_bg = QColor(theme["accent_soft"])
        success_bg.setAlpha(46 if calm else (120 if light else 90))
        self.error_line_format = make_format(theme["text_strong"], background=error_bg)
        self.warning_line_format = make_format(theme["text"], background=warning_bg)
        self.success_line_format = make_format(theme["text"], background=success_bg)

        texture_palette = {
            "color": "#a31515" if light else "#ce9178",
            "ui": "#795e26" if light else "#d7ba7d",
            "emissive": "#b58900" if light else "#ffd166",
            "impostor": "#8a5a00" if light else "#f4a261",
            "normal": "#0451a5" if light else "#569cd6",
            "height": "#098658" if light else "#4ec9b0",
            "vector": "#0b7a75" if light else "#4ec9b0",
            "roughness": "#af00db" if light else "#c586c0",
            "mask": "#7c3aed" if light else "#c586c0",
            "unknown": theme["text_muted"],
        }
        self.texture_type_formats = {
            texture_type: make_format(color, bold=True)
            for texture_type, color in texture_palette.items()
        }
        self.rehighlight()

    def set_bold_enabled(self, enabled: bool) -> None:
        self._bold_enabled = bool(enabled)
        self.set_theme(self.current_theme_key)

    def set_highlight_style(self, style: str) -> None:
        self.highlight_style = _normalize_text_highlight_style(style)
        self.set_theme(self.current_theme_key)

    def set_color_scheme(self, scheme: str) -> None:
        self.color_scheme = _normalize_text_color_scheme(scheme)
        self.set_theme(self.current_theme_key)

    def highlightBlock(self, text: str) -> None:  # type: ignore[override]
        if self.highlight_style == "plain":
            return
        lowered = text.lower()
        if self._error_re.search(text):
            self.setFormat(0, len(text), self.error_line_format)
        elif self._warning_re.search(text):
            self.setFormat(0, len(text), self.warning_line_format)
        elif "completed successfully" in lowered:
            self.setFormat(0, len(text), self.success_line_format)

        timestamp_match = self._timestamp_re.match(text)
        if timestamp_match:
            self.setFormat(timestamp_match.start(), timestamp_match.end() - timestamp_match.start(), self.timestamp_format)

        for match in self._windows_path_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.path_format)
        for match in self._relative_path_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.path_format)

        for match in self._progress_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.progress_format)

        for match in self._phase_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.phase_format)

        for match in self._backend_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.backend_format)

        for match in self._correction_mode_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.success_format)

        for match in self._key_value_re.finditer(text):
            key_start, key_end = match.span(1)
            value_start, value_end = match.span(2)
            self.setFormat(key_start, key_end - key_start, self.key_format)
            self.setFormat(value_start, value_end - value_start, self.value_format)

        for match in self._label_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.key_format)

        for match in self._dimension_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.number_format)

        for match in self._number_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.number_format)

        for match in self._arrow_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.separator_format)

        for match in self._texture_type_re.finditer(text):
            texture_type = match.group(1).lower()
            fmt = self.texture_type_formats.get(texture_type, self.path_format)
            self.setFormat(match.start(), match.end() - match.start(), fmt)

        for match in self._action_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.action_format)

        for match in self._warning_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.warning_format)

        for match in self._error_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.error_format)

        for match in self._success_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.success_format)


class ArchiveDetailsHighlighter(QSyntaxHighlighter):
    _section_re = re.compile(
        r"^(Entry Metadata|Import Summary|Preview / Texture Notes|Preview Diagnostics|Render Sampling Diagnostics|Readable Strings|Binary Header Preview|Simplified values for .+|HKX tagfile preview for .+|What this appears to contain:|Recognized fields:|Format summary:|Tag item map:|Detected classes/types:|Decoder Evidence|Reference Semantics|Class Decode Status|Fixup-backed Fields|Asset Map|Uses|Used By|Prefab evidence|Declared Fields|Schema Declarations)\s*$"
    )
    _label_re = re.compile(r"^\s*(?:[-*]\s*)?([A-Za-z][A-Za-z0-9 /()_-]+:)")
    _warning_re = re.compile(r"\b(warning|failed|missing|truncated|unsupported|fallback|skipped|unavailable|error)\b", re.IGNORECASE)
    _windows_path_re = re.compile(r"[A-Za-z]:\\[^\r\n<>|\"*?]+")
    _relative_path_re = re.compile(r"(?<![\w.-])(?:[\w.-]+[\\/]){2,}[\w./\\-]+")
    _number_re = re.compile(r"(?<![\w./\\-])\d[\d,]*(?:\.\d+)?\b")
    _hex_value_re = re.compile(r"\b0x[0-9A-Fa-f]+\b")
    _hex_offset_re = re.compile(r"^\s*([0-9A-F]{4})(?=\s)")
    _hex_byte_re = re.compile(r"\b[0-9A-F]{2}\b")

    def __init__(self, document, theme_key: str, highlight_style: str = "rich", color_scheme: str = "theme"):
        super().__init__(document)
        self.current_theme_key = theme_key
        self.highlight_style = _normalize_text_highlight_style(highlight_style)
        self.color_scheme = _normalize_text_color_scheme(color_scheme)
        self.section_format = QTextCharFormat()
        self.label_format = QTextCharFormat()
        self.path_format = QTextCharFormat()
        self.number_format = QTextCharFormat()
        self.warning_format = QTextCharFormat()
        self.hex_offset_format = QTextCharFormat()
        self.hex_byte_format = QTextCharFormat()
        self.muted_format = QTextCharFormat()
        self.set_theme(theme_key)

    def set_theme(self, theme_key: str) -> None:
        self.current_theme_key = theme_key
        theme = get_theme(theme_key)
        light = _theme_is_light(theme_key)
        calm = self.highlight_style == "calm"
        scheme = _scheme_palette(theme_key, self.color_scheme)

        def make_format(
            color: str,
            *,
            bold: bool = False,
            italic: bool = False,
        ) -> QTextCharFormat:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold and not calm:
                fmt.setFontWeight(QFont.Bold)
            fmt.setFontItalic(italic)
            return fmt

        self.section_format = make_format((scheme or {}).get("section", theme["accent"] if not calm else theme["text_strong"]), bold=True)
        self.label_format = make_format((scheme or {}).get("key", "#795e26" if light else "#d7ba7d"), bold=True)
        self.path_format = make_format(theme["text_strong"], bold=True)
        self.number_format = make_format((scheme or {}).get("number", "#098658" if light else "#b5cea8"))
        self.warning_format = make_format((scheme or {}).get("warning", theme["warning_text"]), bold=True)
        self.hex_offset_format = make_format((scheme or {}).get("tag", "#0451a5" if light else "#569cd6"), bold=True)
        self.hex_byte_format = make_format((scheme or {}).get("string", "#ce9178" if light else "#d7ba7d"))
        self.muted_format = make_format(theme["text_muted"], italic=True)
        self.rehighlight()

    def set_highlight_style(self, style: str) -> None:
        self.highlight_style = _normalize_text_highlight_style(style)
        self.set_theme(self.current_theme_key)

    def set_color_scheme(self, scheme: str) -> None:
        self.color_scheme = _normalize_text_color_scheme(scheme)
        self.set_theme(self.current_theme_key)

    def highlightBlock(self, text: str) -> None:  # type: ignore[override]
        if self.highlight_style == "plain":
            return
        if not text.strip():
            return

        section_match = self._section_re.match(text.strip())
        if section_match:
            self.setFormat(0, len(text), self.section_format)
            return

        if text.lstrip().startswith("String scan truncated") or text.lstrip().startswith("No details available."):
            self.setFormat(0, len(text), self.muted_format)
            return

        hex_offset_match = self._hex_offset_re.match(text)
        if hex_offset_match:
            offset_start, offset_end = hex_offset_match.span(1)
            self.setFormat(offset_start, offset_end - offset_start, self.hex_offset_format)
            remainder = text[offset_end:]
            ascii_separator = remainder.find("  ")
            hex_region_end = len(text) if ascii_separator < 0 else offset_end + ascii_separator
            for match in self._hex_byte_re.finditer(text[offset_end:hex_region_end]):
                start = offset_end + match.start()
                self.setFormat(start, match.end() - match.start(), self.hex_byte_format)

        label_match = self._label_re.match(text)
        if label_match:
            start, end = label_match.span(1)
            self.setFormat(start, end - start, self.label_format)

        for match in self._windows_path_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.path_format)
        for match in self._relative_path_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.path_format)
        for match in self._hex_value_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.hex_offset_format)
        for match in self._number_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.number_format)
        for match in self._warning_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.warning_format)


class ArchiveDetailsEditor(CodePreviewEditor):
    def __init__(
        self,
        *,
        theme_key: str,
        parent: Optional[QWidget] = None,
        highlight_style: str = "rich",
        color_scheme: str = "theme",
    ):
        super().__init__(theme_key=theme_key, parent=parent, highlight_style=highlight_style, color_scheme=color_scheme)
        previous_highlighter = getattr(self, "syntax_highlighter", None)
        if previous_highlighter is not None and hasattr(previous_highlighter, "setDocument"):
            previous_highlighter.setDocument(None)
        self.syntax_highlighter = ArchiveDetailsHighlighter(
            self.document(),
            theme_key,
            self._highlight_style,
            self._color_scheme,
        )
        self.set_theme(theme_key)

    def set_language_for_extension(self, extension: str) -> None:
        _ = extension


class CollapsibleSection(QWidget):
    toggled = Signal(bool)

    def __init__(self, title: str, *, expanded: bool = False):
        super().__init__()
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(6)

        self.toggle_button = QToolButton()
        self.toggle_button.setObjectName("SectionToggle")
        self.toggle_button.setText(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.toggle_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.toggle_button.clicked.connect(self.set_expanded)
        outer_layout.addWidget(self.toggle_button)

        self.body_frame = QFrame()
        self.body_frame.setObjectName("SectionBody")
        self.body_layout = QVBoxLayout(self.body_frame)
        self.body_layout.setContentsMargins(12, 10, 12, 12)
        self.body_layout.setSpacing(8)
        outer_layout.addWidget(self.body_frame)

        self.set_expanded(expanded)

    def set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        self.toggle_button.blockSignals(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.blockSignals(False)
        self.toggle_button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.body_frame.setVisible(expanded)
        self.toggled.emit(expanded)


_QUICK_START_HTML_ES = """
<h3>Que cubre esta app</h3>
<p><b>Crimson Desert Mod Workbench</b> es una herramienta de archivos y archivos sueltos para Crimson Desert. Cubre extraccion, investigacion, edicion, reconstruccion DDS, escalado opcional, comparacion y exportacion suelta lista para mods.</p>
<ul>
  <li><b>Explorador de archivos</b>: escanear .pamt/.paz, previsualizar recursos compatibles, filtrar, clasificar y extraer a carpetas sueltas.</li>
  <li><b>Acciones de malla</b>: exportar OBJ/FBX, probar <b>Importar vista de malla</b>, probar texturas con <b>Vista previa de importar DDS</b>, ejecutar <b>Importar malla</b>, alinear reemplazos estaticos y usar <b>Intercambiar con malla del juego</b> cuando otra malla del archivo deba ser el origen.</li>
  <li><b>Flujo de texturas</b>: escanear DDS sueltos, convertir DDS a PNG si hace falta, escalar opcionalmente, reconstruir DDS, comparar resultados y exportar salida mod-ready.</li>
  <li><b>Editor de texturas</b>: abrir imagenes para edicion visible por capas y enviar la salida plana al flujo de reconstruccion.</li>
  <li><b>Asistente de reemplazo</b>: tomar PNG/DDS editados, asociarlos con el DDS original del juego, reconstruir la salida corregida y preparar carpetas mod-ready.</li>
  <li><b>Investigacion</b>: inspeccionar familias de texturas, clasificaciones desconocidas, referencias, analisis DDS, informes y notas locales.</li>
  <li><b>Busqueda de texto</b>: buscar archivos de texto de archivo o sueltos, como .xml, .json, .cfg y .lua.</li>
  <li><b>Configuracion</b>: guardar tema, densidad, cache, estado de layout, confirmaciones y preferencias de inicio.</li>
</ul>
<h3>Configuracion inicial recomendada</h3>
<ol>
  <li>Crea una carpeta dedicada para la app y coloca alli el <b>.exe</b> portable para mantener juntos configuracion, cache, herramientas y workspace.</li>
  <li>Abre <b>Configuracion &gt; Ubicaciones de archivo</b> y define la ruta del juego/paquete de Crimson Desert. Usa deteccion automatica si aplica.</li>
  <li>Abre <b>Configuracion &gt; Setup</b> y haz clic en <b>Inicializar espacio</b>.</li>
  <li>Usa las herramientas DirectXTex/native incluidas para DDS; <b>texconv.exe</b> queda como fallback legacy opcional.</li>
  <li>Define <b>Raiz DDS original</b>, <b>Raiz PNG</b> y <b>Raiz de salida</b>. Activa staging DDS solo si quieres una carpeta PNG previa al escalado.</li>
  <li>Elige un backend de escalado: desactivado, <b>Real-ESRGAN NCNN</b> directo o <b>chaiNNer</b>.</li>
  <li>Empieza con una politica de texturas segura y deja las reglas automaticas activadas para preservar mapas tecnicos riesgosos.</li>
  <li>Revisa perfiles, reglas y coincidencias antes de ejecutar un lote.</li>
  <li>Usa <b>Vista de politica</b> antes de <b>Iniciar</b> para revisar la accion planeada por textura.</li>
  <li>Ejecuta un subconjunto pequeno primero y revisa el resultado en <b>Comparar</b>.</li>
  <li>Si ya editaste una textura fuera de la app, usa <b>Asistente de reemplazo</b>.</li>
  <li>Para mallas, empieza en <b>Explorador de archivos</b>: selecciona una malla .pam/.pamlod/.pac, usa <b>Importar vista de malla</b> para probar sin escribir y usa <b>Importar malla</b> solo cuando la alineacion y las texturas se vean correctas.</li>
</ol>
<h3>Guia rapida de mallas</h3>
<ul>
  <li><b>Exportar OBJ/FBX</b>: util para inspeccionar o editar externamente. OBJ es la base de round-trip cuando la app puede escribir los metadatos necesarios.</li>
  <li><b>Importar vista de malla</b>: abre la revision y <b>Alineacion de reemplazo de malla</b> sin escribir salida.</li>
  <li><b>Vista previa de importar DDS</b>: prueba una textura DDS en el modelo seleccionado sin escribir salida.</li>
  <li><b>Importar malla</b>: despues de revisar, permite exportar salida suelta mod-ready o parchear archivos donde sea compatible.</li>
  <li><b>Intercambiar con malla del juego</b>: primero marca la malla seleccionada como destino, luego selecciona otra malla del archivo como origen. La app abre la misma alineacion de reemplazo y puede incluir texturas, sidecars, esqueletos o animaciones relacionadas cuando corresponda.</li>
  <li><b>GLB/glTF/DAE</b>: se tratan como fuentes estaticas. No convierten skins, huesos, animaciones ni grafos PBR complejos a datos nativos del juego.</li>
</ul>
<h3>Areas principales</h3>
<ul>
  <li><b>Configuracion / Setup</b>: creacion de workspace, herramientas externas, enlaces de ayuda e importadores.</li>
  <li><b>Configuracion / Rutas</b>: origen, staging, PNG, salida y raices de exportacion mod-ready.</li>
  <li><b>Salida DDS</b>: formato, tamano, mips y staging globales.</li>
  <li><b>Perfiles, reglas y coincidencias</b>: planificacion reutilizable por archivo.</li>
  <li><b>Escalado</b>: backend, politica, controles NCNN y notas.</li>
  <li><b>Comparar</b>: revision lado a lado antes de lotes grandes.</li>
</ul>
<h3>Nota sobre cache de sidecars</h3>
<p>Crear el cache global de sidecars puede tardar mucho en archivos grandes. Mejora referencias inversas DDS, conexiones de texturas de modelos y busqueda de sidecars/materiales. Si lo activas, deja que termine; se configura en <b>Configuracion &gt; Rendimiento del explorador de archivos</b>.</p>
<h3>Advertencia sobre texturas tecnicas</h3>
<p>Las texturas visibles de color no son iguales que mapas tecnicos. Altura, desplazamiento, normales, mascaras, vectores y otros DDS sensibles son mas riesgosos al pasar por PNG.</p>
<ul>
  <li>Empieza con un preajuste seguro.</li>
  <li>Manten las reglas automaticas activadas.</li>
  <li>Revisa perfiles y rutas del planificador antes de forzar mapas tecnicos por la ruta PNG visible.</li>
</ul>
<h3>Documentacion</h3>
<p>El menu <b>Documentacion</b> abre un navegador de documentacion con busqueda y temas de flujo, perfiles y rutas del planificador.</p>
"""


_QUICK_START_HTML_DE = """
<h3>Was diese App abdeckt</h3>
<p><b>Crimson Desert Mod Workbench</b> ist ein Archiv- und Loose-File-Werkzeug fuer Crimson Desert. Es deckt Extraktion, Research, Bearbeitung, DDS-Neuaufbau, optionales Upscaling, Vergleich und mod-fertigen Loose-Export ab.</p>
<ul>
  <li><b>Archiv-Browser</b>: .pamt/.paz scannen, unterstuetzte Assets anzeigen, filtern, klassifizieren und in lose Ordner extrahieren.</li>
  <li><b>Mesh-Aktionen</b>: OBJ/FBX exportieren, <b>Mesh-Importvorschau</b> testen, Texturen mit <b>DDS-Importvorschau</b> pruefen, <b>Mesh importieren</b> ausfuehren, statische Ersetzungen ausrichten und <b>Mit Ingame-Mesh tauschen</b> nutzen, wenn eine andere Archiv-Mesh als Quelle dienen soll.</li>
  <li><b>Textur-Workflow</b>: lose DDS scannen, DDS bei Bedarf zu PNG konvertieren, optional hochskalieren, DDS neu erstellen, Ergebnisse vergleichen und mod-fertige Ausgabe exportieren.</li>
  <li><b>Textur-Editor</b>: Bilder fuer sichtbare Ebenenbearbeitung oeffnen und die flache Ausgabe zurueck in den Neuaufbau senden.</li>
  <li><b>Ersetzungsassistent</b>: bearbeitete PNG/DDS mit dem Original-DDS abgleichen, korrigierte Ausgabe neu erstellen und mod-fertige Ordner vorbereiten.</li>
  <li><b>Recherche</b>: Texturfamilien, unbekannte Klassifizierungen, Referenzen, DDS-Analyse, Berichte und lokale Notizen pruefen.</li>
  <li><b>Textsuche</b>: Archiv- oder lose Textdateien wie .xml, .json, .cfg und .lua durchsuchen.</li>
  <li><b>Einstellungen</b>: Theme, Dichte, Cache, Layoutstatus, Bestaetigungen und Startpraeferenzen speichern.</li>
</ul>
<h3>Empfohlene Starteinrichtung</h3>
<ol>
  <li>Erstelle einen eigenen Ordner fuer die App und lege die portable <b>.exe</b> dort ab, damit Konfiguration, Cache, Tools und Workspace zusammen bleiben.</li>
  <li>Oeffne <b>Einstellungen &gt; Archiv-Orte</b> und setze den Crimson-Desert-Spiel-/Paketpfad. Nutze Auto-Erkennung, wenn moeglich.</li>
  <li>Oeffne <b>Einstellungen &gt; Einrichtung</b> und klicke auf <b>Arbeitsbereich einrichten</b>.</li>
  <li>Nutze die gebuendelten DirectXTex/native-DDS-Tools; <b>texconv.exe</b> bleibt nur optionaler Legacy-Fallback.</li>
  <li>Setze <b>Original-DDS-Stamm</b>, <b>PNG-Stamm</b> und <b>Ausgabe-Stamm</b>. Aktiviere DDS-Staging nur fuer einen separaten PNG-Staging-Ordner.</li>
  <li>Waehle ein Upscaling-Backend: deaktiviert, direktes <b>Real-ESRGAN NCNN</b> oder <b>chaiNNer</b>.</li>
  <li>Starte mit einer sicheren Textur-Richtlinie und lasse automatische Regeln aktiv, damit riskante technische Maps erhalten bleiben.</li>
  <li>Pruefe Profile, Regeln und Treffer, bevor du einen Stapellauf startest.</li>
  <li>Nutze <b>Richtlinienvorschau</b> vor <b>Start</b>, um die geplante Aktion pro Textur zu pruefen.</li>
  <li>Fuehre zuerst eine kleine Auswahl aus und pruefe das Ergebnis in <b>Vergleichen</b>.</li>
  <li>Wenn du eine Textur bereits extern bearbeitet hast, nutze den <b>Ersetzungsassistent</b>.</li>
  <li>Fuer Meshes im <b>Archiv-Browser</b> starten: .pam/.pamlod/.pac waehlen, mit <b>Mesh-Importvorschau</b> ohne Schreiben testen und <b>Mesh importieren</b> erst nutzen, wenn Ausrichtung und Texturen korrekt aussehen.</li>
</ol>
<h3>Schnellguide fuer Meshes</h3>
<ul>
  <li><b>OBJ/FBX exportieren</b>: nuetzlich fuer Inspektion oder externe Bearbeitung. OBJ ist die Roundtrip-Basis, wenn die App die noetigen Metadaten schreiben kann.</li>
  <li><b>Mesh-Importvorschau</b>: oeffnet Review und <b>Mesh-Ersetzungsausrichtung</b>, ohne Ausgabe zu schreiben.</li>
  <li><b>DDS-Importvorschau</b>: testet eine DDS-Textur am gewaehlten Modell, ohne Ausgabe zu schreiben.</li>
  <li><b>Mesh importieren</b>: nach der Pruefung mod-fertige Loose-Ausgabe oder Patch schreiben, wo kompatibel.</li>
  <li><b>Mit Ingame-Mesh tauschen</b>: zuerst die ausgewaehlte Mesh als Ziel markieren, dann eine andere Archiv-Mesh als Quelle waehlen. Die App oeffnet dieselbe Ersetzungsausrichtung und kann passende Texturen, Sidecars, Skelette oder Animationen einschliessen.</li>
  <li><b>GLB/glTF/DAE</b>: werden als statische Quellen behandelt. Skins, Knochen, Animationen und komplexe PBR-Graphen werden nicht in native Spieldaten konvertiert.</li>
</ul>
<h3>Hauptbereiche</h3>
<ul>
  <li><b>Einstellungen / Einrichtung</b>: Workspace-Erstellung, externe Tools, Hilfelinks und Importhelfer.</li>
  <li><b>Einstellungen / Pfade</b>: Quelle, Staging, PNG, Ausgabe und mod-fertige Exportstaemme.</li>
  <li><b>DDS-Ausgabe</b>: globale Format-, Groessen-, Mip- und Staging-Regeln.</li>
  <li><b>Profile, Regeln und Treffer</b>: wiederverwendbare Planung pro Datei.</li>
  <li><b>Upscaling</b>: Backend, Richtlinie, NCNN-Steuerung und Notizen.</li>
  <li><b>Vergleichen</b>: Seit-an-Seit-Pruefung vor groesseren Laeufen.</li>
</ul>
<h3>Hinweis zum Sidecar-Cache</h3>
<p>Der globale Sidecar-Cache kann bei grossen Archiven lange dauern. Er verbessert DDS-Rueckreferenzen, Modell-Textur-Verbindungen und Material-Sidecar-Suche. Wenn du ihn aktivierst, lass den ersten Lauf fertig werden; die Optionen findest du unter <b>Einstellungen &gt; Archiv-Browser-Leistung</b>.</p>
<h3>Warnung zu technischen Texturen</h3>
<p>Sichtbare Farbtexturen sind nicht dasselbe wie technische Maps. Hoehe, Displacement, Normalen, Masken, Vektoren und andere empfindliche DDS-Dateien sind riskanter, wenn sie ueber PNG laufen.</p>
<ul>
  <li>Starte mit einem sicheren Preset.</li>
  <li>Lasse automatische Regeln aktiv.</li>
  <li>Pruefe Planerprofile und Planerpfade, bevor technische Maps in den sichtbaren PNG-Pfad gezwungen werden.</li>
</ul>
<h3>Dokumentation</h3>
<p>Das Menue <b>Dokumentation</b> oeffnet einen durchsuchbaren Dokumentationsbrowser mit Workflow-Themen, Profilen und Planerpfaden.</p>
"""


class QuickStartDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle("Startup Setup")
        self.setMinimumSize(560, 460)
        self.resize(720, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title_label = QLabel("Startup setup guide")
        title_font = QFont(self.font())
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        intro_label = QLabel(
            "Start by putting the portable EXE in its own app folder, setting the Crimson Desert game/package path in Settings > Archive Locations, then clicking Init Workspace. DDS preview and rebuild use DirectXTex/native helpers first; texconv is optional legacy fallback."
        )
        intro_label.setObjectName("HintLabel")
        intro_label.setWordWrap(True)
        layout.addWidget(intro_label)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(False)
        self.browser.setReadOnly(True)
        quick_start_html = (
            """
            <h3>What This App Covers</h3>
            <p><b>Crimson Desert Mod Workbench</b> is a read-only archive and loose-file workflow tool for Crimson Desert. It is built around extraction, research, editing, DDS rebuild, optional upscaling, comparison, and mod-ready loose export.</p>
            <ul>
              <li><b>Dashboard</b>: launch common tasks, check workspace paths/tool health, review recent work, and reopen the last result.</li>
              <li><b>Archive Browser</b>: scan <b>.pamt/.paz</b>, preview supported assets, filter, classify, and extract to loose folders.</li>
              <li><b>Mesh Actions</b>: export OBJ/FBX, test <b>Import Mesh Preview</b>, preview texture overrides with <b>Import DDS Preview</b>, run <b>Import Mesh</b>, align static replacements, and use <b>Swap With In-Game Mesh</b> when another loaded archive mesh should become the source.</li>
              <li><b>Texture Workflow</b>: scan loose DDS files, convert DDS to PNG when needed, optionally upscale, rebuild DDS, compare results, and export loose mod output.</li>
              <li><b>Texture Editor</b>: open images directly for layered visible-texture editing and send flattened output back into the rebuild flow.</li>
              <li><b>Texture Replacer</b>: take edited PNG/DDS files, match them to the original game DDS, rebuild corrected output, and prepare mod-ready folders.</li>
              <li><b>Model Library</b>: scan local/importable models, use mirror catalogue metadata, preview models, and route imports to archive workflows.</li>
              <li><b>Icon Creator</b>: manage icon source images and generate compatible item-icon packages from archive targets.</li>
              <li><b>Research</b>: inspect grouped texture families, unknown classifications, references, DDS analysis, reports, and local notes.</li>
              <li><b>Text Search</b>: search archive or loose text-like files such as <b>.xml</b>, <b>.json</b>, <b>.cfg</b>, and <b>.lua</b>.</li>
              <li><b>Settings</b>: store theme, density, cache behavior, remembered layout state, confirmations, and startup preferences beside the EXE.</li>
            </ul>
            <h3>Recommended Startup Setup</h3>
            <ol>
              <li>Create or choose a dedicated folder for the app, then place the portable <b>.exe</b> there so config, cache, tools, and workspace folders stay together.</li>
              <li>Open <b>Settings &gt; Archive Locations</b> and set the Crimson Desert game/package path. Use <b>Auto-detect</b> if the game is in a common install location.</li>
              <li>Open <b>Settings &gt; Setup</b> and click <b>Init Workspace</b>.</li>
              <li>Use the bundled DirectXTex/native DDS tools. <b>texconv.exe</b> is optional legacy fallback only.</li>
              <li>Confirm <b>Original DDS root</b>, <b>PNG root</b>, and <b>Output root</b>. Enable DDS staging only if you want a separate pre-upscale PNG staging folder.</li>
              <li>Choose an upscaling backend in <b>Upscaling</b>: disabled, direct <b>Real-ESRGAN NCNN</b>, or <b>chaiNNer</b>.</li>
              <li>Keep a safer <b>Texture Policy</b> preset first and leave automatic rules enabled so risky technical DDS files are preserved instead of pushed through the visible PNG path.</li>
              <li>Open <b>Profiles, Rules &amp; Matches</b> and review the starter workflow assignments before running a batch.</li>
              <li>Use <b>Preview Policy</b> before <b>Start</b> if you want to inspect the planned per-texture action.</li>
              <li>Click <b>Scan</b> in the Texture Workflow tab.</li>
              <li>Run a small subset first, then review the output in <b>Compare</b> before trying a larger batch.</li>
              <li>If you already edited a texture outside the app, use <b>Texture Replacer</b> instead of the batch workflow.</li>
              <li>If you want to edit visible textures inside the app, open them in <b>Texture Editor</b> and then send the flattened result back into <b>Texture Replacer</b> or <b>Texture Workflow</b>.</li>
              <li>For mesh work, start in <b>Archive Browser</b>: select a <b>.pam</b>, <b>.pamlod</b>, or <b>.pac</b>, use <b>Import Mesh Preview</b> to test without writing, and use <b>Import Mesh</b> only after alignment and texture choices look correct.</li>
            </ol>
            <h3>Mesh Quick Guide</h3>
            <ul>
              <li><b>Export OBJ/FBX</b>: use this for inspection or external editing. OBJ is the round-trip baseline when the app can write the companion metadata needed for import.</li>
              <li><b>Import Mesh Preview</b>: opens review and <b>Mesh Replacement Alignment</b> without writing archive or loose output.</li>
              <li><b>Import DDS Preview</b>: tests a DDS texture override on the selected model without writing output.</li>
              <li><b>Import Mesh</b>: after review, writes a supported replacement as mod-ready loose output or an archive patch where that workflow is available.</li>
              <li><b>Swap With In-Game Mesh</b>: first mark the selected archive mesh as the target, then choose another loaded archive mesh as the source. The app opens the same replacement alignment flow and can carry related textures, sidecars, skeletons, or animations when appropriate.</li>
              <li><b>GLB/glTF/DAE</b>: treated as static replacement sources. Skins, bones, animations, and complex PBR material graphs are not converted into native game material data.</li>
            </ul>
            <h3>Pick The Right Starting Path</h3>
            <ul>
              <li><b>I want to look inside the game files</b>: open <b>Archive Browser</b>, choose a package root, scan, filter, preview, and extract selected files.</li>
              <li><b>I want to replace a model</b>: use <b>Archive Browser</b> mesh actions, start with <b>Import Mesh Preview</b>, then continue to <b>Import Mesh</b> or <b>Swap With In-Game Mesh</b> after checking alignment.</li>
              <li><b>I want to batch-process loose DDS files</b>: use <b>Texture Workflow</b> with a small folder first, then review in <b>Compare</b>.</li>
              <li><b>I already edited one texture</b>: use <b>Texture Replacer</b> so the original DDS controls format, dimensions, mips, and output path.</li>
              <li><b>I want to edit inside the app</b>: use <b>Texture Editor</b>, save a project if you need layers later, then export or send the flattened PNG onward.</li>
              <li><b>I need to understand what a texture family is</b>: use <b>Research</b> for grouped sets, classifications, references, analysis, and notes.</li>
              <li><b>I am searching for XML, JSON, Lua, or config strings</b>: use <b>Text Search</b> against archives or loose folders.</li>
            </ul>
            <h3>Sidecar Cache Note</h3>
            <p>Building the global sidecar cache is intentionally optional because it can be expensive on large archives. It improves DDS related-file discovery, reverse references, mesh texture connections, and material-sidecar lookup. If you enable it, let the first run finish even when it takes a long time. Configure sidecar indexing and worker count in <b>Settings &gt; Archive Browser Performance</b>.</p>
            <h3>Safety Reminders</h3>
            <p>Visible color textures are not the same as technical maps. Height, displacement, normals, masks, vectors, and other precision-sensitive DDS files are riskier to push through PNG intermediates.</p>
            <ul>
              <li>Start with a safer preset.</li>
              <li>Keep automatic rules enabled.</li>
              <li>Use preview-only paths before writing mesh or archive output.</li>
              <li>Open Documentation for detailed field references, recipes, troubleshooting, and FAQs.</li>
            </ul>
            <h3>Where Details Live</h3>
            <p>The <b>Documentation</b> menu is topic-based and searchable. Use it for mesh import/swap steps, archive guides, Texture Workflow profiles and rules, Texture Editor tools, Texture Replacer packaging, Research, Text Search, settings, troubleshooting, and FAQs.</p>
            """
        )
        self.browser.setFont(self.font())
        self.browser.document().setDefaultFont(self.font())
        self.browser.setProperty("_i18n_source_html", quick_start_html)
        self.browser.setProperty("_i18n_html_es", _QUICK_START_HTML_ES)
        self.browser.setProperty("_i18n_html_de", _QUICK_START_HTML_DE)
        self.browser.setHtml(quick_start_html)
        layout.addWidget(self.browser, stretch=1)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.open_archive_locations_button = QPushButton("Open Archive Locations")
        self.open_setup_button = QPushButton("Open Setup && Paths")
        self.open_chainner_button = QPushButton("Open chaiNNer Setup")
        self.open_docs_button = QPushButton("Open Documentation")
        self.close_button = QPushButton("Close")
        button_row.addWidget(self.open_archive_locations_button)
        button_row.addWidget(self.open_setup_button)
        button_row.addWidget(self.open_chainner_button)
        button_row.addWidget(self.open_docs_button)
        button_row.addStretch(1)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

        self.open_archive_locations_button.clicked.connect(self._open_archive_locations)
        self.open_setup_button.clicked.connect(self._open_setup)
        self.open_chainner_button.clicked.connect(self._open_chainner_setup)
        self.open_docs_button.clicked.connect(self._open_docs)
        self.close_button.clicked.connect(self.accept)

    def _open_setup(self) -> None:
        self.parent_window.focus_quick_start_sections(include_chainner=False)
        self.accept()

    def _open_chainner_setup(self) -> None:
        self.parent_window.focus_quick_start_sections(include_chainner=True)
        self.accept()

    def _open_archive_locations(self) -> None:
        self.parent_window.focus_archive_locations()
        self.accept()

    def _open_docs(self) -> None:
        parent_window = self.parent_window
        self.accept()
        if parent_window is not None and hasattr(parent_window, "show_documentation_dialog"):
            QTimer.singleShot(0, lambda: parent_window.show_documentation_dialog(topic_id="overview"))


class AboutDialog(QDialog):
    def __init__(
        self,
        parent,
        *,
        title: str,
        intro_html: str,
        sections: Sequence[Dict[str, str]],
        initial_section_id: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(840, 560)
        self.resize(1080, 720)
        self._sections: List[Dict[str, str]] = [dict(section) for section in sections]
        self._filtered_sections: List[Dict[str, str]] = list(self._sections)
        self._initial_section_id = initial_section_id.strip()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title_label = QLabel(title)
        title_font = QFont(self.font())
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        self.intro_html = intro_html
        guide_label = QLabel(
            "Search or choose a topic on the left. The reader shows one topic at a time so longer documentation stays navigable."
        )
        guide_label.setObjectName("HintLabel")
        guide_label.setWordWrap(True)
        layout.addWidget(guide_label)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        search_label = QLabel("Search")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search topics, fields, tabs, planner paths, planner profiles...")
        self.topic_count_label = QLabel("")
        self.topic_count_label.setObjectName("HintLabel")
        search_row.addWidget(search_label)
        search_row.addWidget(self.search_edit, stretch=1)
        search_row.addWidget(self.topic_count_label)
        layout.addLayout(search_row)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, stretch=1)

        topic_panel = QWidget()
        topic_layout = QVBoxLayout(topic_panel)
        topic_layout.setContentsMargins(0, 0, 0, 0)
        topic_layout.setSpacing(8)
        topic_hint = QLabel("Choose a documentation topic or search by feature name.")
        topic_hint.setObjectName("HintLabel")
        topic_hint.setWordWrap(True)
        topic_layout.addWidget(topic_hint)
        self.topic_list = QListWidget()
        self.topic_list.setAlternatingRowColors(True)
        self.topic_list.setProperty("_i18n_translate_items", True)
        topic_layout.addWidget(self.topic_list, stretch=1)
        splitter.addWidget(topic_panel)

        self.browser = QTextBrowser()
        self.browser.setReadOnly(True)
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.setFont(self.font())
        self.browser.document().setDefaultFont(self.font())
        self.browser.setProperty("_i18n_source_html", "")
        splitter.addWidget(self.browser)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 760])

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        self.search_edit.textChanged.connect(self._refresh_topic_list)
        self.topic_list.currentItemChanged.connect(self._handle_topic_changed)
        self.browser.anchorClicked.connect(self._handle_anchor_clicked)

        self._refresh_topic_list()
        if self._initial_section_id:
            self.select_section(self._initial_section_id)
        elif self.topic_list.count() > 0:
            self._select_first_topic()

    def _build_document_html(self, title: str, intro_html: str) -> str:
        section_html: List[str] = []
        for section in self._sections:
            section_id = str(section.get("id", "") or "").strip()
            section_title = str(section.get("title", "") or "").strip()
            section_body = str(section.get("html", "") or "")
            if not section_id or not section_title:
                continue
            section_html.append(
                f"<a name=\"{section_id}\"></a><h2>{section_title}</h2>{section_body}"
            )
        return (
            f"<h3>{title}</h3>{intro_html}"
            "<hr/>"
            + "<hr/>".join(section_html)
        )

    def _build_section_html(self, section: Dict[str, str]) -> str:
        section_id = str(section.get("id", "") or "").strip()
        section_title = str(section.get("title", "") or "").strip() or "Documentation"
        section_summary = str(section.get("summary", "") or "").strip()
        section_body = str(section.get("html", "") or "")
        category = self._section_category(section)
        summary_html = f"<p><i>{section_summary}</i></p>" if section_summary else ""
        category_html = f"<p><b>{category}</b></p>" if category else ""
        css = """
        <style>
        h2 { margin-top: 0; }
        h4 { margin-bottom: 4px; }
        table { border-collapse: collapse; width: 100%; margin: 8px 0 12px 0; }
        th, td { border: 1px solid #6b7280; padding: 5px 7px; vertical-align: top; }
        th { background: rgba(127, 127, 127, 0.18); font-weight: 600; }
        .doc-callout { border-left: 4px solid #3b82f6; padding: 7px 10px; margin: 8px 0; background: rgba(59, 130, 246, 0.10); }
        .doc-warning { border-left-color: #f59e0b; background: rgba(245, 158, 11, 0.12); }
        .doc-danger { border-left-color: #ef4444; background: rgba(239, 68, 68, 0.10); }
        .doc-ok { border-left-color: #22c55e; background: rgba(34, 197, 94, 0.10); }
        .pill { border: 1px solid #6b7280; border-radius: 4px; padding: 1px 4px; white-space: nowrap; }
        </style>
        """
        if section_id == "overview":
            return f"{css}<h2>{section_title}</h2>{category_html}{summary_html}{self.intro_html}<hr/>{section_body}"
        return f"{css}<h2>{section_title}</h2>{category_html}{summary_html}{section_body}"

    @staticmethod
    def _topic_search_text(section: Dict[str, str]) -> str:
        title = str(section.get("title", "") or "")
        keywords = str(section.get("keywords", "") or "")
        body = str(section.get("html", "") or "")
        plain_body = re.sub(r"<[^>]+>", " ", body)
        return f"{title}\n{keywords}\n{plain_body}".lower()

    @staticmethod
    def _section_category(section: Dict[str, str]) -> str:
        category = str(section.get("category", "") or "").strip()
        if category:
            return category
        section_id = str(section.get("id", "") or "").strip()
        if section_id in {"overview", "quick_start", "first_run_checklist", "faq"}:
            return "Start Here"
        if section_id.startswith("workflow_") or section_id in {"dds_output", "upscaling_backends", "texture_workflow_guides", "compare_review"}:
            return "Texture Workflow"
        if section_id in {"archive_browser", "archive_guides", "mesh_media_guides"}:
            return "Archive Browser"
        if section_id in {"texture_editor", "replace_assistant", "research", "text_search"}:
            return "Tools"
        if section_id in {"mod_packaging", "safety", "settings_files", "troubleshooting"}:
            return "Reference"
        return "Other"

    @staticmethod
    def _category_sort_key(category: str) -> Tuple[int, str]:
        order = {
            "Start Here": 0,
            "Texture Workflow": 1,
            "Archive Browser": 2,
            "Tools": 3,
            "Reference": 4,
            "Other": 99,
        }
        return (order.get(category, 50), category.lower())

    def _localized_category_label(self, category: str) -> str:
        language_code = self._current_language_code()
        labels = {
            "es": {
                "Start Here": "Primeros pasos",
                "Texture Workflow": "Flujo de texturas",
                "Archive Browser": "Explorador de archivos",
                "Tools": "Herramientas",
                "Reference": "Referencia",
                "Other": "Otros",
            },
            "de": {
                "Start Here": "Start",
                "Texture Workflow": "Textur-Workflow",
                "Archive Browser": "Archiv-Browser",
                "Tools": "Werkzeuge",
                "Reference": "Referenz",
                "Other": "Weitere Themen",
            },
        }
        return labels.get(language_code, {}).get(category, category)

    def _add_topic_group_header(self, category: str) -> None:
        item = QListWidgetItem("")
        item.setFlags(Qt.NoItemFlags)
        item.setData(Qt.UserRole, "")
        item.setSizeHint(QSize(0, 30))
        self.topic_list.addItem(item)

        header_widget = QWidget()
        header_widget.setAttribute(Qt.WA_TransparentForMouseEvents)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(8, 5, 8, 3)
        header_layout.setSpacing(8)

        label = QLabel(self._localized_category_label(category).upper())
        label_font = QFont(self.topic_list.font())
        label_font.setBold(True)
        label_font.setPointSize(max(8, label_font.pointSize() - 1))
        label.setFont(label_font)
        label.setAttribute(Qt.WA_TransparentForMouseEvents)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Plain)
        divider.setAttribute(Qt.WA_TransparentForMouseEvents)
        divider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        palette = self.topic_list.palette()
        muted = palette.color(QPalette.Disabled, QPalette.Text)
        if not muted.isValid():
            muted = palette.color(QPalette.Text)
        divider_color = palette.color(QPalette.Mid)
        if not divider_color.isValid():
            divider_color = muted
        label.setStyleSheet(f"color: {muted.name()};")
        divider.setStyleSheet(f"color: {divider_color.name()}; background: {divider_color.name()}; max-height: 1px;")

        header_layout.addWidget(label, stretch=0)
        header_layout.addWidget(divider, stretch=1)
        self.topic_list.setItemWidget(item, header_widget)

    def _refresh_topic_list(self) -> None:
        query = self.search_edit.text().strip().lower()
        current_section_id = self.current_section_id()
        self._filtered_sections = [
            section
            for section in self._sections
            if not query or query in self._topic_search_text(section)
        ]
        self.topic_list.blockSignals(True)
        self.topic_list.clear()
        grouped_sections: Dict[str, List[Dict[str, str]]] = {}
        for section in self._filtered_sections:
            grouped_sections.setdefault(self._section_category(section), []).append(section)
        for category in sorted(grouped_sections, key=self._category_sort_key):
            self._add_topic_group_header(category)
            for section in grouped_sections[category]:
                item = QListWidgetItem(str(section.get("title", "") or "Untitled"))
                item.setData(Qt.UserRole, str(section.get("id", "") or ""))
                item.setForeground(QBrush(self.topic_list.palette().color(QPalette.Text)))
                summary = str(section.get("summary", "") or "")
                if summary:
                    item.setToolTip(summary)
                self.topic_list.addItem(item)
        self.topic_list.blockSignals(False)
        self.topic_count_label.setText(self._format_topic_count(len(self._filtered_sections)))
        if not self._filtered_sections:
            self.browser.setHtml(
                "<h2>No Matching Topics</h2><p>Try a broader search term such as <b>DDS</b>, <b>archive</b>, <b>profile</b>, <b>replace</b>, or <b>FAQ</b>.</p>"
            )
            return
        if current_section_id:
            for index in range(self.topic_list.count()):
                item = self.topic_list.item(index)
                if str(item.data(Qt.UserRole) or "") == current_section_id:
                    self.topic_list.setCurrentItem(item)
                    return
        self._select_first_topic()

    def _select_first_topic(self) -> None:
        for index in range(self.topic_list.count()):
            item = self.topic_list.item(index)
            if str(item.data(Qt.UserRole) or ""):
                self.topic_list.setCurrentItem(item)
                return

    def _current_language_code(self) -> str:
        parent = self.parent()
        localizer = getattr(parent, "ui_localizer", None)
        return str(getattr(localizer, "language_code", "en") or "en").strip().lower()

    def _format_topic_count(self, count: int) -> str:
        language_code = self._current_language_code()
        if language_code == "es":
            return f"{count} tema" if count == 1 else f"{count} temas"
        if language_code == "de":
            return f"{count} Thema" if count == 1 else f"{count} Themen"
        return f"{count} topic" if count == 1 else f"{count} topics"

    def current_section_id(self) -> str:
        item = self.topic_list.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.UserRole) or "")

    def select_section(self, section_id: str) -> None:
        target_id = section_id.strip()
        if not target_id:
            return
        for index in range(self.topic_list.count()):
            item = self.topic_list.item(index)
            if str(item.data(Qt.UserRole) or "") == target_id:
                self.topic_list.setCurrentItem(item)
                self._render_section(target_id)
                return
        self.search_edit.clear()
        for index in range(self.topic_list.count()):
            item = self.topic_list.item(index)
            if str(item.data(Qt.UserRole) or "") == target_id:
                self.topic_list.setCurrentItem(item)
                self._render_section(target_id)
                return

    def _handle_topic_changed(self, current: Optional[QListWidgetItem], _previous: Optional[QListWidgetItem]) -> None:
        if current is None:
            return
        self._render_section(str(current.data(Qt.UserRole) or ""))

    def _scroll_to_section(self, section_id: str) -> None:
        if not section_id:
            return
        QTimer.singleShot(0, lambda: self.browser.scrollToAnchor(section_id))

    def _render_section(self, section_id: str) -> None:
        if not section_id:
            return
        for section in self._sections:
            if str(section.get("id", "") or "") == section_id:
                html = self._build_section_html(section)
                self.browser.setProperty("_i18n_source_html", html)
                self.browser.setHtml(html)
                QTimer.singleShot(0, lambda: self.browser.moveCursor(QTextCursor.Start))
                return

    def _handle_anchor_clicked(self, url: QUrl) -> None:
        if url.scheme() in {"http", "https"}:
            QDesktopServices.openUrl(url)
            return
        target_id = url.fragment().strip()
        if not target_id and url.scheme() == "topic":
            target_id = url.path().strip("/").strip()
        if target_id:
            self.select_section(target_id)
