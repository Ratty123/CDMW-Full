"""Responsive layout sizing helpers shared by UI features."""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QApplication, QLayout, QLayoutItem, QSizePolicy, QWidget


class FlowLayout(QLayout):
    """A row of controls that wraps onto further lines when it is narrow.

    Its minimum width is its widest item, so a row of controls never holds its
    page wider than one control.
    """

    def __init__(self, parent: Optional[QWidget] = None, *, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: List[QLayoutItem] = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 - Qt override
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> Optional[QLayoutItem]:  # noqa: N802 - Qt override
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> Optional[QLayoutItem]:  # noqa: N802 - Qt override
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802 - Qt override
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt override
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt override
        return self._arrange(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - Qt override
        super().setGeometry(rect)
        self._arrange(rect, move=True)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        shown = [item for item in self._items if not item.isEmpty()]
        width = sum(item.sizeHint().width() for item in shown) + self.spacing() * max(0, len(shown) - 1)
        height = max((item.sizeHint().height() for item in shown), default=0)
        margins = self.contentsMargins()
        return QSize(width + margins.left() + margins.right(), height + margins.top() + margins.bottom())

    def minimumSize(self) -> QSize:  # noqa: N802 - Qt override
        size = QSize()
        for item in self._items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _arrange(self, rect: QRect, *, move: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, line_height = area.x(), area.y(), 0
        for item in self._items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            if x > area.x() and x + hint.width() > area.right() + 1:
                x, y = area.x(), y + line_height + self.spacing()
                line_height = 0
            if move:
                item.setGeometry(QRect(QPoint(x, y), QSize(min(hint.width(), area.width()), hint.height())))
            x += hint.width() + self.spacing()
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


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
