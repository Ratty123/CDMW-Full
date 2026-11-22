"""App-wide table, tree, and list column coherence helpers.

Ensures data views (other than Browse Archives' file list) expose user-resizable
columns sized to display their full content without clipping or wasted right-edge voids.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractItemModel, QEvent, QModelIndex, QObject, QPoint, QTimer, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QListView,
    QStyle,
    QStyledItemDelegate,
    QTableView,
    QTreeView,
    QTreeWidget,
    QWidget,
)
import shiboken6

from cdmw.ui.app_event_hub import install_app_event_filter

_MAX_SAMPLE_ROWS = 250
_MAX_AUTO_COLUMN_WIDTH = 720
_MIN_SECTION_SIZE = 36


def is_archive_browser_list(widget: object) -> bool:
    """Leave Browse Archives' file list untouched as requested."""

    return type(widget).__name__ == "ArchiveBrowserTreeView"


def _should_skip_column_coherence(widget: object) -> bool:
    """Return True when a view owns or freezes its own column widths."""

    return (
        is_archive_browser_list(widget)
        or bool(widget.property("_cdmwKeepFixedColumns"))
        or bool(widget.property("cdmw_disable_auto_column_fill"))
    )


class _FullRowHoverDelegate(QStyledItemDelegate):
    """Paints cohesive full-row hover on QTableView/QTableWidget without hiding item colors."""

    def paint(self, painter, option, index) -> None:  # noqa: D401 - Qt override
        view = self.parent()
        if (
            isinstance(view, QTableView)
            and shiboken6.isValid(view)
            and not bool(option.state & QStyle.StateFlag.State_Selected)
        ):
            hover_row = getattr(view, "_cdmw_hover_row", -1)
            hover_col = getattr(view, "_cdmw_hover_col", -1)
            is_row_mode = view.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
            hovered = hover_row >= 0 and index.row() == hover_row and (
                is_row_mode or index.column() == hover_col
            )
            if hovered:
                base_color = option.palette.color(QPalette.ColorRole.Base)
                text_color = option.palette.color(QPalette.ColorRole.Text)
                tint = QColor(text_color)
                if base_color.lightnessF() >= 0.55:
                    tint.setAlpha(20)
                elif base_color.lightness() == 0 and text_color.lightness() == 255:
                    tint.setAlpha(38)
                else:
                    tint.setAlpha(24)
                painter.save()
                painter.fillRect(option.rect, tint)
                painter.restore()
        super().paint(painter, option, index)


def _repaint_table_rows(view: QTableView, rows: set[int]) -> None:
    viewport = view.viewport()
    if viewport is None or not shiboken6.isValid(viewport):
        return
    width = viewport.width()
    if width <= 0:
        return
    for row in rows:
        if row < 0:
            continue
        height = view.rowHeight(row)
        if height > 0:
            viewport.update(0, view.rowViewportPosition(row), width, height)


def _set_table_hover(view: QTableView, row: int, col: int) -> None:
    old_row = getattr(view, "_cdmw_hover_row", -1)
    old_col = getattr(view, "_cdmw_hover_col", -1)
    is_row_mode = view.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    if is_row_mode:
        if row == old_row:
            view._cdmw_hover_col = col
            return
    elif row == old_row and col == old_col:
        return
    view._cdmw_hover_row = row
    view._cdmw_hover_col = col
    _repaint_table_rows(view, {old_row, row})


def _update_table_hover_from_viewport_pos(view: QTableView, pos: QPoint) -> None:
    idx = view.indexAt(pos)
    if idx.isValid():
        _set_table_hover(view, idx.row(), idx.column())
    else:
        _set_table_hover(view, -1, -1)


def _apply_unified_list_surface(view: QAbstractItemView) -> None:
    """Apply Create New Item's clean gridless row canvas except to excluded views."""

    if getattr(view, "_cdmw_unified_applied", False):
        return
    if is_archive_browser_list(view) or view.objectName() == "SettingsSectionNav":
        view._cdmw_unified_applied = True
        return
    view._cdmw_unified_applied = True
    # Only plain QTreeView subclasses rely on [cdmwUnifiedList="true"] in QSS;
    # QTableView/QTableWidget/QTreeWidget/QListView/QListWidget match directly,
    # avoiding unnecessary full-widget unpolish/polish passes.
    if isinstance(view, QTreeView) and not isinstance(view, QTreeWidget):
        if not bool(view.property("cdmwUnifiedList")):
            view.setProperty("cdmwUnifiedList", True)
            style = view.style()
            if style is not None:
                style.unpolish(view)
                style.polish(view)
    view.setAlternatingRowColors(False)
    set_show_grid = getattr(view, "setShowGrid", None)
    if callable(set_show_grid):
        set_show_grid(False)
    if isinstance(view, QTreeView):
        view.setAllColumnsShowFocus(True)
    if isinstance(view, QTableView):
        if not getattr(view, "_cdmw_hover_bound", False):
            view._cdmw_hover_bound = True
            view._cdmw_hover_row = -1
            view._cdmw_hover_col = -1
            view.setMouseTracking(True)
            view.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
            viewport = view.viewport()
            if viewport is not None and shiboken6.isValid(viewport):
                viewport.setMouseTracking(True)
            hover_filter = _TableHoverFilter(view)
            view.installEventFilter(hover_filter)
            if viewport is not None and shiboken6.isValid(viewport):
                viewport.installEventFilter(hover_filter)
            view._cdmw_hover_filter = hover_filter
        if type(view.itemDelegate()) is QStyledItemDelegate:
            view.setItemDelegate(_FullRowHoverDelegate(view))


def _column_has_index_widget(view: QAbstractItemView, column: int) -> bool:
    """Return True when any sampled row embeds a persistent cell widget in this column."""

    model = view.model()
    if model is None or not shiboken6.isValid(model):
        return False
    rows = min(model.rowCount(), 12)
    for row in range(rows):
        idx = model.index(row, column)
        if idx.isValid() and view.indexWidget(idx) is not None:
            return True
    return False


def _absorbable_target_column(
    view: QAbstractItemView,
    header: QHeaderView,
    changed_index: int,
) -> int | None:
    """Choose a visible non-widget column to absorb trailing void space."""

    candidates = [
        col
        for col in range(header.count())
        if not header.isSectionHidden(col) and not _column_has_index_widget(view, col)
    ]
    if len(candidates) < 2:
        return None
    if changed_index == candidates[-1]:
        return candidates[0]
    return candidates[-1]


def _absorb_header_gap(
    view: QAbstractItemView,
    header: QHeaderView,
    changed_index: int,
) -> None:
    """Fill trailing blank space when a user drags a column narrower."""

    viewport = view.viewport()
    if viewport is None or not shiboken6.isValid(viewport):
        return
    viewport_w = viewport.width()
    col_count = header.count()
    if viewport_w <= 40 or col_count < 2:
        return
    total_w = sum(
        header.sectionSize(col)
        for col in range(col_count)
        if not header.isSectionHidden(col)
    )
    gap = viewport_w - total_w
    if gap <= 2:
        return
    target = _absorbable_target_column(view, header, changed_index)
    if target is None or target == changed_index:
        return
    header._cdmw_programmatic_resize = True
    try:
        header.resizeSection(target, header.sectionSize(target) + gap)
    finally:
        header._cdmw_programmatic_resize = False


def _expand_columns_to_viewport(view: QAbstractItemView) -> None:
    """Proportionally expand columns when the viewport widens past total column width."""

    if getattr(view, "_cdmw_expanding", False) or not view.isVisible():
        return
    header = _header_for(view)
    viewport = view.viewport()
    if (
        header is None
        or not shiboken6.isValid(header)
        or header.isHidden()
        or viewport is None
        or not shiboken6.isValid(viewport)
    ):
        return
    viewport_w = viewport.width()
    col_count = header.count()
    if viewport_w <= 40 or col_count <= 0:
        return
    total_w = sum(
        header.sectionSize(col)
        for col in range(col_count)
        if not header.isSectionHidden(col)
    )
    extra = viewport_w - total_w
    if extra <= 2:
        return
    adjustable = [
        col
        for col in range(col_count)
        if not header.isSectionHidden(col) and not _column_has_index_widget(view, col)
    ]
    if not adjustable:
        return
    adj_sum = sum(header.sectionSize(col) for col in adjustable)
    if adj_sum <= 0:
        return
    view._cdmw_expanding = True
    header._cdmw_programmatic_resize = True
    try:
        remaining = extra
        last_idx = len(adjustable) - 1
        for idx, col in enumerate(adjustable):
            cur_w = header.sectionSize(col)
            if idx == last_idx:
                add_w = max(0, remaining)
            else:
                add_w = min(remaining, max(0, int(round(extra * (cur_w / adj_sum)))))
                remaining -= add_w
            if add_w > 0:
                header.resizeSection(col, cur_w + add_w)
    finally:
        header._cdmw_programmatic_resize = False
        view._cdmw_expanding = False


def _header_for(view: QAbstractItemView) -> QHeaderView | None:
    if isinstance(view, QTableView):
        return view.horizontalHeader()
    if isinstance(view, QTreeView):
        return view.header()
    return None


def _ensure_header_tracking(
    header: QHeaderView,
    view: QAbstractItemView | None = None,
) -> set[int]:
    if view is not None:
        header._cdmw_owner_view = view
    user_resized = getattr(header, "_cdmw_user_resized", None)
    if isinstance(user_resized, set):
        return user_resized
    user_resized = set()
    header._cdmw_user_resized = user_resized
    header._cdmw_programmatic_resize = False

    def _on_section_resized(logical_index: int, old_size: int, new_size: int) -> None:
        if getattr(header, "_cdmw_programmatic_resize", False):
            return
        user_resized.add(logical_index)
        owner = getattr(header, "_cdmw_owner_view", None)
        if (
            owner is None
            or not isinstance(owner, QAbstractItemView)
            or not shiboken6.isValid(owner)
            or not owner.isVisible()
            or _should_skip_column_coherence(owner)
            or new_size >= old_size
        ):
            return
        _absorb_header_gap(owner, header, logical_index)

    header.sectionResized.connect(_on_section_resized)
    return user_resized


def mark_user_sized_columns(header: QHeaderView, columns) -> None:
    """Treat ``columns`` as sized by the user, so a fit keeps their widths.

    A width restored from the saved layout is the user's, but it is applied
    before the view is shown and before this module tracks the header, so
    nothing would otherwise record it and the first fit on Show (or on a model
    change) would replace it.
    """

    if not isinstance(header, QHeaderView) or not shiboken6.isValid(header):
        return
    _ensure_header_tracking(header).update(int(col) for col in columns)


def _measure_text_width(metrics, text: str) -> int:
    if not text:
        return 0
    return max((metrics.horizontalAdvance(line) for line in text.splitlines()), default=0)


def fit_resizable_columns(view: object, *, force: bool = False) -> None:
    """Make columns Interactive, show full content, and avoid clipping or dead voids."""

    if not isinstance(view, QAbstractItemView) or not shiboken6.isValid(view):
        return
    if is_archive_browser_list(view):
        return
    _apply_unified_list_surface(view)
    if _should_skip_column_coherence(view):
        return

    if isinstance(view, QListView):
        if view.objectName() != "SettingsSectionNav":
            view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            view.setTextElideMode(Qt.TextElideMode.ElideNone)
        return

    header = _header_for(view)
    if header is None or not shiboken6.isValid(header) or header.isHidden():
        return

    col_count = header.count()
    if col_count <= 0:
        return

    user_resized = _ensure_header_tracking(header, view)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    if not view.property("_cdmwKeepElide"):
        view.setTextElideMode(Qt.TextElideMode.ElideNone)
    if isinstance(view, QTableView) and not view.property("_cdmwKeepWordWrap"):
        view.setWordWrap(False)
    header._cdmw_programmatic_resize = True
    try:
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(_MIN_SECTION_SIZE)
        for col in range(col_count):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
    finally:
        header._cdmw_programmatic_resize = False
    view._cdmw_coherence_fitted = True

    model: QAbstractItemModel | None = view.model()
    if model is None:
        return

    row_count = model.rowCount()
    h_metrics = header.fontMetrics()
    c_metrics = view.fontMetrics()
    is_table = isinstance(view, QTableView)
    is_tree = isinstance(view, QTreeView)

    sampled_rows: list[tuple[QModelIndex, int, int, bool]] = []
    if is_tree:
        stack: list[tuple[QModelIndex, int, int]] = []
        root_idx = view.rootIndex()
        for r in range(min(model.rowCount(root_idx), _MAX_SAMPLE_ROWS) - 1, -1, -1):
            stack.append((root_idx, r, 0))
        while stack and len(sampled_rows) < _MAX_SAMPLE_ROWS:
            parent_idx, r, depth = stack.pop()
            if view.isRowHidden(r, parent_idx):
                continue
            row_idx = model.index(r, 0, parent_idx)
            if not row_idx.isValid():
                continue
            spanned = view.isFirstColumnSpanned(r, parent_idx)
            sampled_rows.append((parent_idx, r, depth, spanned))
            child_count = model.rowCount(row_idx)
            if child_count > 0:
                limit = min(child_count, _MAX_SAMPLE_ROWS - len(sampled_rows))
                for cr in range(limit - 1, -1, -1):
                    stack.append((row_idx, cr, depth + 1))
    else:
        for r in range(min(row_count, _MAX_SAMPLE_ROWS)):
            if is_table and view.isRowHidden(r):
                continue
            sampled_rows.append((QModelIndex(), r, 0, False))

    tree_indent = view.indentation() if is_tree else 0
    tree_icon_w = view.iconSize().width() if is_tree else 0

    needed: list[int] = []
    has_widget_col: list[bool] = []
    hidden = [header.isSectionHidden(col) for col in range(col_count)]
    for col in range(col_count):
        if hidden[col]:
            # A hidden column takes no room, so it neither counts towards the
            # width nor receives slack, and its size is left as it is.
            needed.append(header.sectionSize(col))
            has_widget_col.append(False)
            continue
        if not force and col in user_resized:
            needed.append(max(_MIN_SECTION_SIZE, header.sectionSize(col)))
            has_widget_col.append(False)
            continue

        header_text = str(model.headerData(col, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) or "")
        col_w = max(48, _measure_text_width(h_metrics, header_text) + 24)
        widget_col = False

        for parent_idx, row, depth, spanned in sampled_rows:
            if spanned and col == 0:
                continue
            idx = model.index(row, col, parent_idx)
            if not idx.isValid():
                continue
            cell_widget = view.indexWidget(idx)
            if isinstance(cell_widget, QWidget):
                widget_col = True
                continue
            text = model.data(idx, Qt.ItemDataRole.DisplayRole)
            if text is not None:
                text_w = _measure_text_width(c_metrics, str(text))
                extra = 30
                has_deco = model.data(idx, Qt.ItemDataRole.DecorationRole) is not None
                if is_tree and col == 0:
                    extra += (depth + 1) * tree_indent + 16
                    if has_deco or (tree_icon_w > 0 and model.rowCount(idx) == 0):
                        extra += max(20, tree_icon_w + 6)
                elif has_deco:
                    extra += 20
                if model.data(idx, Qt.ItemDataRole.CheckStateRole) is not None:
                    extra += 20
                col_w = max(col_w, text_w + extra)

        if widget_col:
            current_w = header.sectionSize(col)
            col_w = max(current_w, 96)
        else:
            col_w = min(col_w, _MAX_AUTO_COLUMN_WIDTH)
        needed.append(col_w)
        has_widget_col.append(widget_col)

    viewport = view.viewport()
    viewport_w = viewport.width() if viewport is not None else 0
    total_w = sum(width for col, width in enumerate(needed) if not hidden[col])
    if viewport_w > 0 and total_w < viewport_w:
        slack = viewport_w - total_w
        candidates = [
            col for col in range(col_count)
            if not hidden[col] and not has_widget_col[col] and (force or col not in user_resized)
        ]
        if candidates:
            primary = view.property("_cdmwPrimaryColumn")
            if isinstance(primary, int) and primary in candidates:
                target = primary
            else:
                target = max(candidates, key=lambda c: (needed[c], -c))
            needed[target] += slack

    header._cdmw_programmatic_resize = True
    try:
        for col, width in enumerate(needed):
            if not hidden[col] and header.sectionSize(col) != width:
                header.resizeSection(col, width)
    finally:
        header._cdmw_programmatic_resize = False


class _TableHoverFilter(QObject):
    """Per-table filter handling row hover without intercepting QApplication events."""

    def __init__(self, view: QTableView) -> None:
        super().__init__(view)
        self._view = view

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802 - Qt override
        etype = event.type()
        view = self._view
        if etype == QEvent.Type.MouseMove:
            if shiboken6.isValid(view):
                pos_fn = getattr(event, "position", None)
                pos = pos_fn().toPoint() if callable(pos_fn) else event.pos()
                _update_table_hover_from_viewport_pos(view, pos)
            return False
        if etype == QEvent.Type.HoverMove:
            if watched is view and shiboken6.isValid(view):
                viewport = view.viewport()
                if viewport is not None and shiboken6.isValid(viewport):
                    pos_fn = getattr(event, "position", None)
                    pt = pos_fn().toPoint() if callable(pos_fn) else event.pos()
                    vp_pos = viewport.mapFrom(view, pt)
                    if viewport.rect().contains(vp_pos):
                        _update_table_hover_from_viewport_pos(view, vp_pos)
                    else:
                        _set_table_hover(view, -1, -1)
            return False
        if etype in (QEvent.Type.HoverLeave, QEvent.Type.Leave, QEvent.Type.Hide):
            if shiboken6.isValid(view):
                _set_table_hover(view, -1, -1)
        return False


class _ViewportResizeFilter(QObject):
    """Per-viewport Resize filter so column expansion never taps QApplication."""

    def __init__(self, view: QAbstractItemView) -> None:
        super().__init__(view)
        self._view = view

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802 - Qt override
        if event.type() != QEvent.Type.Resize:
            return False
        owner = self._view
        if (
            shiboken6.isValid(owner)
            and not is_archive_browser_list(owner)
            and not _should_skip_column_coherence(owner)
            and getattr(owner, "_cdmw_coherence_fitted", False)
        ):
            _expand_columns_to_viewport(owner)
        return False


class _TableCoherenceFilter(QObject):
    """Subscribes ONLY to QEvent.Show via AppEventHub to bind shown data views."""

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802 - Qt override
        if event.type() != QEvent.Type.Show:
            return False
        if not isinstance(watched, QAbstractItemView) or not shiboken6.isValid(watched):
            return False
        if is_archive_browser_list(watched):
            return False
        _apply_unified_list_surface(watched)
        if _should_skip_column_coherence(watched):
            return False
        self._bind_viewport(watched)
        self._bind_model(watched)
        self._schedule_fit(watched)
        return False

    def _schedule_fit(self, view: QAbstractItemView) -> None:
        if not shiboken6.isValid(view):
            return
        timer = getattr(view, "_cdmw_coherence_timer", None)
        if not isinstance(timer, QTimer):
            timer = QTimer(view)
            timer.setSingleShot(True)
            timer.setInterval(0)
            timer.timeout.connect(lambda v=view: fit_resizable_columns(v))
            view._cdmw_coherence_timer = timer
        if not timer.isActive():
            timer.start()

    def _bind_viewport(self, view: QAbstractItemView) -> None:
        if getattr(view, "_cdmw_viewport_resize_filter", None) is not None:
            return
        viewport = view.viewport()
        if viewport is None or not shiboken6.isValid(viewport):
            return
        vp_filter = _ViewportResizeFilter(view)
        viewport.installEventFilter(vp_filter)
        view._cdmw_viewport_resize_filter = vp_filter

    def _bind_model(self, view: QAbstractItemView) -> None:
        if isinstance(view, QTreeView) and not getattr(view, "_cdmw_expanded_bound", False):
            view._cdmw_expanded_bound = True
            view.expanded.connect(lambda _idx, v=view: self._schedule_fit(v))
        model = view.model()
        if model is None or not shiboken6.isValid(model):
            return
        bound_model = getattr(view, "_cdmw_coherence_model", None)
        if bound_model is model:
            return
        view._cdmw_coherence_model = model
        trigger = lambda *_args, v=view: self._schedule_fit(v)
        for sig in (
            model.modelReset,
            model.rowsInserted,
            model.layoutChanged,
            model.headerDataChanged,
            model.dataChanged,
        ):
            sig.connect(trigger)


def install_table_coherence_filter(app: QApplication | None = None) -> None:
    """Install one deduplicated Show-only filter on AppEventHub for data views."""

    target_app = app or QApplication.instance()
    if target_app is None:
        return
    if getattr(target_app, "_cdmw_table_coherence_filter", None) is not None:
        return
    filt = _TableCoherenceFilter(target_app)
    install_app_event_filter(target_app, filt, (QEvent.Type.Show,))
    target_app._cdmw_table_coherence_filter = filt
