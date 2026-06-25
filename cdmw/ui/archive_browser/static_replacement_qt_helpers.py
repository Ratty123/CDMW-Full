"""Small Qt helpers shared by static replacement dialog code."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QModelIndex, QObject, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True, slots=True)
class IntSliderSpinRow:
    slider: QSlider
    spin: QSpinBox
    row: QHBoxLayout


def inline_help_button(text: str) -> QPushButton:
    button = QPushButton("?")
    button.setObjectName("InlineHelpButton")
    button.setFixedSize(16, 16)
    button.setToolTip(str(text or "").strip())
    button.setFocusPolicy(Qt.NoFocus)
    return button


def alignment_camera_button(label: str, object_name: str, tooltip: str) -> QPushButton:
    button = QPushButton(label)
    button.setObjectName(object_name)
    button.setMinimumWidth(0)
    button.setMaximumWidth(64)
    button.setToolTip(tooltip)
    return button


def new_alignment_scroll_tab(
    parent: QWidget,
    object_name: str,
    *,
    embedded: bool,
    content_minimum_width: int,
) -> tuple[QScrollArea, QWidget, QVBoxLayout]:
    scroll = QScrollArea(parent)
    scroll.setObjectName(object_name)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff if embedded else Qt.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    page = QWidget(scroll)
    page.setMinimumWidth(0 if embedded else int(content_minimum_width))
    page.setSizePolicy(
        QSizePolicy.Ignored if embedded else QSizePolicy.MinimumExpanding,
        QSizePolicy.Preferred,
    )
    page_layout = QVBoxLayout(page)
    page_layout.setContentsMargins(3, 2, 3, 2)
    page_layout.setSpacing(3)
    page_layout.setAlignment(Qt.AlignTop)
    scroll.setWidget(page)
    return scroll, page, page_layout


def clear_tree_current_item(tree: QTreeWidget | None) -> None:
    if tree is None:
        return
    try:
        tree.clearSelection()
        tree.setCurrentIndex(QModelIndex())
    except RuntimeError:
        return


def commit_spinbox_text(spin: QDoubleSpinBox, *, block_signals: bool = False) -> None:
    previous_blocked = False
    try:
        if block_signals:
            previous_blocked = bool(spin.blockSignals(True))
        spin.interpretText()
    except RuntimeError:
        pass
    finally:
        if block_signals:
            try:
                spin.blockSignals(previous_blocked)
            except RuntimeError:
                pass


def make_double_spin(
    value: float,
    minimum: float,
    maximum: float,
    decimals: int,
    step: float,
    suffix: str = "",
) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setDecimals(decimals)
    spin.setSingleStep(step)
    spin.setValue(value)
    spin.setKeyboardTracking(False)
    if suffix:
        spin.setSuffix(suffix)
    return spin


def set_double_spin_value_silently(spin: QDoubleSpinBox, value: float) -> None:
    spin.blockSignals(True)
    spin.setValue(float(value))
    spin.blockSignals(False)


def make_spinbox_slider(
    spin: QDoubleSpinBox,
    *,
    scale: float,
    tooltip: str,
    object_name: str,
    minimum_width: int,
    slider_minimum: float | None = None,
    slider_maximum: float | None = None,
) -> QSlider:
    slider = QSlider(Qt.Horizontal)
    slider.setObjectName(object_name)
    slider.setToolTip(tooltip)
    minimum = float(spin.minimum()) if slider_minimum is None else float(slider_minimum)
    maximum = float(spin.maximum()) if slider_maximum is None else float(slider_maximum)
    slider.setMinimum(int(round(minimum * scale)))
    slider.setMaximum(int(round(maximum * scale)))
    slider.setSingleStep(max(1, int(round(float(spin.singleStep()) * scale))))
    slider.setPageStep(max(slider.singleStep(), slider.singleStep() * 10))
    slider.setValue(int(round(float(spin.value()) * scale)))
    slider.setMinimumWidth(int(minimum_width))

    def _sync_slider_from_spin(value: float, *, target_slider: QSlider = slider, slider_scale: float = scale) -> None:
        slider_value = int(round(float(value) * slider_scale))
        if target_slider.value() == slider_value:
            return
        target_slider.blockSignals(True)
        target_slider.setValue(slider_value)
        target_slider.blockSignals(False)

    def _sync_spin_from_slider(value: int, *, target_spin: QDoubleSpinBox = spin, slider_scale: float = scale) -> None:
        spin_value = float(value) / float(slider_scale)
        if abs(float(target_spin.value()) - spin_value) <= max(1e-9, float(target_spin.singleStep()) * 0.1):
            return
        target_spin.setValue(spin_value)

    spin.valueChanged.connect(_sync_slider_from_spin)
    slider.valueChanged.connect(_sync_spin_from_slider)
    return slider


def wrap_spin_with_slider(spin: QDoubleSpinBox, slider: QSlider) -> QWidget:
    wrapper = QWidget()
    wrapper_layout = QVBoxLayout(wrapper)
    wrapper_layout.setContentsMargins(0, 0, 0, 0)
    wrapper_layout.setSpacing(1)
    wrapper_layout.addWidget(spin)
    wrapper_layout.addWidget(slider)
    return wrapper


def make_int_slider_spin_row(
    *,
    slider_object_name: str,
    spin_object_name: str,
    minimum: int,
    maximum: int,
    value: int,
    tooltip: str,
    suffix: str = "%",
    single_step: int = 1,
    page_step: int = 10,
    spacing: int = 5,
) -> IntSliderSpinRow:
    slider = QSlider(Qt.Horizontal)
    slider.setObjectName(slider_object_name)
    slider.setRange(int(minimum), int(maximum))
    slider.setSingleStep(int(single_step))
    slider.setPageStep(int(page_step))
    slider.setToolTip(tooltip)
    spin = QSpinBox()
    spin.setObjectName(spin_object_name)
    spin.setRange(int(minimum), int(maximum))
    spin.setSuffix(suffix)
    spin.setToolTip(tooltip)
    clamped_value = max(int(minimum), min(int(maximum), int(value)))
    slider.setValue(clamped_value)
    spin.setValue(clamped_value)
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(int(spacing))
    row.addWidget(slider, 1)
    row.addWidget(spin)
    return IntSliderSpinRow(slider=slider, spin=spin, row=row)


def make_int_spin(
    *,
    object_name: str,
    minimum: int,
    maximum: int,
    value: int,
    prefix: str = "",
    suffix: str = "",
    tooltip: str = "",
    minimum_width: int | None = None,
    keyboard_tracking: bool | None = None,
) -> QSpinBox:
    spin = QSpinBox()
    spin.setObjectName(object_name)
    spin.setRange(int(minimum), int(maximum))
    if prefix:
        spin.setPrefix(prefix)
    if suffix:
        spin.setSuffix(suffix)
    if tooltip:
        spin.setToolTip(tooltip)
    if minimum_width is not None:
        spin.setMinimumWidth(int(minimum_width))
    if keyboard_tracking is not None:
        spin.setKeyboardTracking(bool(keyboard_tracking))
    spin.setValue(max(int(minimum), min(int(maximum), int(value))))
    return spin


def set_int_slider_spin_value_silently(
    slider: QSlider,
    spin: QSpinBox,
    value: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    clamped_value = max(int(minimum), min(int(maximum), int(value)))
    if slider.value() != clamped_value:
        slider.blockSignals(True)
        slider.setValue(clamped_value)
        slider.blockSignals(False)
    if spin.value() != clamped_value:
        spin.blockSignals(True)
        spin.setValue(clamped_value)
        spin.blockSignals(False)
    return clamped_value


def set_checkbox_checked_silently(checkbox: QCheckBox, checked: bool) -> None:
    previous_blocked = bool(checkbox.blockSignals(True))
    try:
        checkbox.setChecked(bool(checked))
    finally:
        checkbox.blockSignals(previous_blocked)


def set_combo_index_silently(combo: QComboBox, index: int) -> None:
    if int(index) < 0 or combo.currentIndex() == int(index):
        return
    previous_blocked = bool(combo.blockSignals(True))
    try:
        combo.setCurrentIndex(int(index))
    finally:
        combo.blockSignals(previous_blocked)


def tree_item_primary_index(item: QTreeWidgetItem | None, *, column: int = 0, role: int = Qt.UserRole) -> int:
    if item is None:
        return -1
    raw_indices = item.data(column, role)
    try:
        return int(raw_indices[0] if isinstance(raw_indices, (tuple, list)) and raw_indices else raw_indices)
    except (TypeError, ValueError):
        return -1


def qt_object_is_valid(widget: object) -> bool:
    if widget is None:
        return False
    try:
        import shiboken6
    except Exception:
        shiboken6 = None
    if shiboken6 is not None:
        try:
            return bool(shiboken6.isValid(widget))
        except Exception:
            return False
    try:
        widget.objectName()  # type: ignore[attr-defined]
        return True
    except RuntimeError:
        return False
    except Exception:
        return True


def safe_stop_timer(timer: object) -> None:
    if not qt_object_is_valid(timer):
        return
    try:
        timer.stop()  # type: ignore[attr-defined]
    except RuntimeError:
        return


def safe_start_timer(timer: object) -> None:
    if not qt_object_is_valid(timer):
        return
    try:
        timer.start()  # type: ignore[attr-defined]
    except RuntimeError:
        return


def safe_timer_active(timer: object) -> bool:
    if not qt_object_is_valid(timer):
        return False
    try:
        return bool(timer.isActive())  # type: ignore[attr-defined]
    except RuntimeError:
        return False


def tree_item_source_index_or_fallback(item: QTreeWidgetItem | None, fallback: int) -> int:
    if item is None:
        try:
            return int(fallback)
        except (TypeError, ValueError):
            return -1
    raw_indices = item.data(0, Qt.UserRole) or item.data(1, Qt.UserRole) or ()
    try:
        return int(raw_indices[0] if isinstance(raw_indices, (tuple, list)) and raw_indices else raw_indices)
    except (TypeError, ValueError):
        return -1


def tree_item_target_index_or_fallback(item: QTreeWidgetItem | None, fallback: int) -> int:
    if item is not None:
        try:
            return int(item.data(0, Qt.UserRole + 1))
        except (TypeError, ValueError):
            pass
    try:
        return int(fallback)
    except (TypeError, ValueError):
        return -1


def parts_outliner_source_index(item: QTreeWidgetItem | None) -> int:
    if item is None or str(item.data(0, Qt.UserRole) or "") != "source":
        return -1
    raw_sources = item.data(0, Qt.UserRole + 2)
    if isinstance(raw_sources, (tuple, list, set)) and raw_sources:
        raw_sources = tuple(raw_sources)[0]
    try:
        return int(raw_sources)
    except (TypeError, ValueError):
        return -1


def visible_tree_row_count(item: QTreeWidgetItem) -> int:
    if item.isHidden():
        return 0
    count = 1
    if item.isExpanded():
        for child_index in range(item.childCount()):
            count += visible_tree_row_count(item.child(child_index))
    return count


def fit_tree_height_to_rows(
    tree: QTreeWidget,
    *,
    minimum: int,
    screen_margin: int,
    maximum: int = 0,
    screen_provider: Callable[[], object | None] | None = None,
) -> None:
    screen = screen_provider() if screen_provider is not None else QApplication.primaryScreen()
    available_geometry = screen.availableGeometry() if screen is not None else None  # type: ignore[attr-defined]
    available_height = int(available_geometry.height()) if available_geometry is not None else 900
    screen_cap = max(int(minimum), available_height - int(screen_margin))
    if maximum > 0:
        screen_cap = min(screen_cap, max(int(minimum), int(maximum)))

    visible_rows = 0
    for item_index in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(item_index)
        if item is not None:
            visible_rows += visible_tree_row_count(item)
    row_height = tree.sizeHintForRow(0)
    if row_height <= 0:
        row_height = tree.fontMetrics().height() + 6
    header_height = max(tree.header().sizeHint().height(), tree.fontMetrics().height() + 6)
    content_height = header_height + (visible_rows * row_height) + 5
    if tree.horizontalScrollBarPolicy() != Qt.ScrollBarAlwaysOff:
        content_height += max(16, tree.horizontalScrollBar().sizeHint().height())
    target_height = min(screen_cap, max(int(minimum), content_height))
    tree.setMinimumHeight(target_height)
    tree.setMaximumHeight(target_height)


def configure_alignment_tree(
    tree: QTreeWidget,
    widths: Sequence[int],
    *,
    max_height: int = 0,
    stretch_columns: Sequence[int] = (),
    persist_key: str = "",
    settings: object | None = None,
    save_callback: Callable[[], object] | None = None,
    persist_columns: Callable[..., object] | None = None,
) -> None:
    tree.setRootIsDecorated(False)
    tree.setAlternatingRowColors(True)
    tree.setMouseTracking(False)
    tree.viewport().setMouseTracking(False)
    tree.setUniformRowHeights(True)
    tree.setTextElideMode(Qt.ElideMiddle)
    tree.setWordWrap(False)
    tree.setMinimumWidth(0)
    tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    tree.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    tree.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    tree.setSelectionMode(QAbstractItemView.SingleSelection)
    tree.setStyleSheet(tree.styleSheet() + "QTreeWidget::item { padding: 0 2px; }")
    header = tree.header()
    header.setSectionsClickable(True)
    header.setMinimumSectionSize(28)
    header.setStretchLastSection(True)
    header.setSectionsMovable(False)
    stretch_column_set = set(int(column) for column in stretch_columns)
    if not stretch_column_set and widths:
        stretch_column_set.add(len(widths) - 1)
    for column, width in enumerate(widths):
        if column in stretch_column_set:
            header.setSectionResizeMode(column, QHeaderView.Stretch)
        else:
            header.setSectionResizeMode(column, QHeaderView.Interactive)
        tree.setColumnWidth(column, int(width))
    if persist_key and persist_columns is not None and settings is not None:
        persist_columns(
            tree,
            settings,
            f"alignment/{persist_key}",
            minimum_width=28,
            save_callback=save_callback,
            restore_later=False,
            persist_order=False,
            sections_movable=False,
        )
        header.setStretchLastSection(True)
    if max_height > 0:
        tree.setMaximumHeight(max_height)


def configure_texture_mapping_tree(
    tree: QTreeWidget,
    *,
    persist_key: str = "",
    settings: object | None = None,
    save_callback: Callable[[], object] | None = None,
    persist_columns: Callable[..., object] | None = None,
) -> None:
    tree.setRootIsDecorated(False)
    tree.setAlternatingRowColors(True)
    tree.setMouseTracking(False)
    tree.viewport().setMouseTracking(False)
    tree.setUniformRowHeights(True)
    tree.setTextElideMode(Qt.ElideMiddle)
    tree.setWordWrap(False)
    tree.setMinimumWidth(0)
    tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    tree.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    tree.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    tree.setSelectionMode(QAbstractItemView.SingleSelection)
    header = tree.header()
    header.setSectionsClickable(True)
    header.setStretchLastSection(False)
    header.setMinimumSectionSize(38)
    header.setSectionsMovable(False)
    for column, width in enumerate((56, 170, 150, 170, 118, 240)):
        header.setSectionResizeMode(column, QHeaderView.Interactive)
        tree.setColumnWidth(column, int(width))
    header.setSectionResizeMode(5, QHeaderView.Stretch)
    if persist_key and persist_columns is not None and settings is not None:
        persist_columns(
            tree,
            settings,
            f"alignment/{persist_key}",
            minimum_width=38,
            save_callback=save_callback,
            restore_later=False,
            persist_order=False,
            sections_movable=False,
        )
    tree.setMaximumHeight(420)


def auto_fit_tree_columns(
    tree: QTreeWidget,
    minimums: Sequence[int],
    maximums: Sequence[int],
    *,
    expand_column: int = -1,
    expand_columns: Sequence[int] = (),
) -> None:
    if not qt_object_is_valid(tree):
        return
    try:
        header = tree.header()
    except RuntimeError as exc:
        message = str(exc)
        if "already deleted" in message or "Internal C++ object" in message:
            return
        raise
    if header is None:
        return
    if not qt_object_is_valid(header):
        return
    if bool(tree.property("cdmw_defer_autofit")):
        return
    if not tree.isVisible():
        return
    minimum_values = tuple(int(value) for value in minimums)
    maximum_values = tuple(int(value) for value in maximums)
    column_count = min(tree.columnCount(), len(minimum_values), len(maximum_values))
    if column_count <= 0:
        return
    header.setStretchLastSection(False)
    header.setSectionsMovable(False)
    measured_widths: list[int] = []
    target_widths: list[int] = []
    for column in range(column_count):
        header.setSectionResizeMode(column, QHeaderView.Interactive)
        tree.resizeColumnToContents(column)
        measured = max(int(tree.columnWidth(column)) + 6, int(header.sectionSizeHint(column)))
        minimum = max(18, int(minimum_values[column]))
        maximum = max(minimum, int(maximum_values[column]))
        measured_widths.append(measured)
        target_widths.append(max(minimum, min(maximum, measured)))
    viewport_width = max(0, int(tree.viewport().width()))
    if viewport_width <= 0:
        viewport_width = max(0, int(tree.width()) - 4)
    available_width = max(sum(minimum_values[:column_count]), viewport_width - 4) if viewport_width > 0 else 0
    if available_width > 0:
        over_width = sum(target_widths) - available_width
        shrinkable = [column for column in range(column_count) if target_widths[column] > minimum_values[column]]
        while over_width > 0 and shrinkable:
            share = max(1, (int(over_width) + len(shrinkable) - 1) // len(shrinkable))
            next_shrinkable: list[int] = []
            for column in shrinkable:
                capacity = max(0, target_widths[column] - minimum_values[column])
                delta = min(capacity, share, over_width)
                if delta > 0:
                    target_widths[column] -= delta
                    over_width -= delta
                if target_widths[column] > minimum_values[column]:
                    next_shrinkable.append(column)
                if over_width <= 0:
                    next_shrinkable.extend(
                        candidate
                        for candidate in shrinkable
                        if candidate != column and target_widths[candidate] > minimum_values[candidate]
                    )
                    break
            if len(next_shrinkable) == len(shrinkable) and all(
                target_widths[column] <= minimum_values[column]
                for column in next_shrinkable
            ):
                break
            shrinkable = sorted(set(next_shrinkable))
        extra_width = available_width - sum(target_widths)
        preferred_columns: list[int] = []
        for column in tuple(expand_columns or ()):
            if 0 <= int(column) < column_count and int(column) not in preferred_columns:
                preferred_columns.append(int(column))
        if 0 <= int(expand_column) < column_count and int(expand_column) not in preferred_columns:
            preferred_columns.append(int(expand_column))
        for column in range(column_count):
            if measured_widths[column] > target_widths[column] and column not in preferred_columns:
                preferred_columns.append(column)
        for column in preferred_columns:
            if extra_width <= 0:
                break
            capacity = max(0, measured_widths[column] - target_widths[column])
            if capacity <= 0:
                continue
            delta = min(capacity, extra_width)
            target_widths[column] += delta
            extra_width -= delta
        if extra_width > 0:
            fill_columns = preferred_columns or [column_count - 1]
            share = max(1, (int(extra_width) + len(fill_columns) - 1) // len(fill_columns))
            for column in fill_columns:
                if extra_width <= 0:
                    break
                delta = min(share, extra_width)
                target_widths[column] += delta
                extra_width -= delta
    for column, target_width in enumerate(target_widths):
        tree.setColumnWidth(column, max(18, int(target_width)))
    stretch_targets = [
        int(column)
        for column in tuple(expand_columns or ())
        if 0 <= int(column) < column_count
    ]
    if 0 <= int(expand_column) < column_count and int(expand_column) not in stretch_targets:
        stretch_targets.append(int(expand_column))
    for column in stretch_targets or [column_count - 1]:
        header.setSectionResizeMode(column, QHeaderView.Stretch)


def install_tree_column_autofit(
    tree: QTreeWidget,
    minimums: Sequence[int],
    maximums: Sequence[int],
    *,
    expand_column: int = -1,
    expand_columns: Sequence[int] = (),
    event_filters: list[QObject] | None = None,
) -> QObject:
    class _TreeColumnAutofitFilter(QObject):
        def __init__(self, watched_tree: QTreeWidget) -> None:
            super().__init__(watched_tree)
            self._tree = watched_tree
            self._pending = False

        def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
            if event.type() in (QEvent.Type.Show, QEvent.Type.Resize, QEvent.Type.LayoutRequest):
                self._queue()
            return False

        def _queue(self) -> None:
            if self._pending:
                return
            self._pending = True
            QTimer.singleShot(32, self._fit)

        def _fit(self) -> None:
            self._pending = False
            auto_fit_tree_columns(
                self._tree,
                minimums,
                maximums,
                expand_column=expand_column,
                expand_columns=expand_columns,
            )

    autofit_filter = _TreeColumnAutofitFilter(tree)
    tree.installEventFilter(autofit_filter)
    tree.viewport().installEventFilter(autofit_filter)
    if event_filters is not None:
        event_filters.append(autofit_filter)
    return autofit_filter


__all__ = [
    "IntSliderSpinRow",
    "alignment_camera_button",
    "auto_fit_tree_columns",
    "clear_tree_current_item",
    "configure_alignment_tree",
    "configure_texture_mapping_tree",
    "commit_spinbox_text",
    "fit_tree_height_to_rows",
    "inline_help_button",
    "install_tree_column_autofit",
    "make_double_spin",
    "make_int_slider_spin_row",
    "make_int_spin",
    "make_spinbox_slider",
    "new_alignment_scroll_tab",
    "parts_outliner_source_index",
    "qt_object_is_valid",
    "safe_start_timer",
    "safe_stop_timer",
    "safe_timer_active",
    "set_checkbox_checked_silently",
    "set_combo_index_silently",
    "set_double_spin_value_silently",
    "set_int_slider_spin_value_silently",
    "tree_item_primary_index",
    "tree_item_source_index_or_fallback",
    "tree_item_target_index_or_fallback",
    "visible_tree_row_count",
    "wrap_spin_with_slider",
]
