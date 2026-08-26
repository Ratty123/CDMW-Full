"""New Item Studio, panel 1: choose the template item."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.ui_kit import intro_label

#: How long keyboard row navigation waits before it takes a row as chosen. Long enough
#: that arrow-keying through the list passes rows without rebuilding five steps at each
#: one. An explicit mouse click commits immediately through ``_apply_clicked_pick``.
_SETTLE_MS = 180
_MATCH_PAGE_SIZE = 60


class TemplatePanel(QGroupBox):
    """A search box over equipment items; picking one fixes the class the clone inherits."""

    def __init__(self, controller: NewItemStudioController, parent=None) -> None:
        super().__init__("1. Template", parent)
        self._controller = controller
        self._syncing = False
        self._match_options: list[tuple[int, str, str, str]] = []
        self._sort_column = -1
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._column_widths_initialized = False
        self._resizing_match_columns = False
        layout = QVBoxLayout(self)
        layout.addWidget(intro_label("Every new item is a copy of a shipped one: the template sets its slot, type, sockets, animations and any optional sheathed variant; everything after changes the copy. Equipment only."))
        self.workspace_layout = QHBoxLayout()
        self.workspace_layout.setContentsMargins(0, 0, 0, 0)
        self.selection_column = QWidget(self)
        selection_layout = QVBoxLayout(self.selection_column)
        selection_layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("Find:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Internal name or item key")
        self.filter_edit.textChanged.connect(self._refresh_matches)
        row.addWidget(self.filter_edit, 1)
        selection_layout.addLayout(row)
        self.matches = QTreeWidget()
        self.matches.setColumnCount(4)
        self.matches.setHeaderLabels(["Internal name:", "Item Name", "Key", "Type"])
        self.matches.setRootIsDecorated(False)
        self.matches.setUniformRowHeights(True)
        self.matches.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.matches.setAllColumnsShowFocus(True)
        self.matches.setProperty("cdmw_disable_auto_column_fill", True)
        header = self.matches.header()
        header.setStretchLastSection(False)
        for column in range(self.matches.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(False)
        header.setSortIndicatorClearable(False)
        header.setToolTip("Click a column heading to sort; click it again to reverse the order.")
        header.sectionClicked.connect(self._sort_matches_by_column)
        header.sectionResized.connect(self._match_column_resized)
        self.matches.setMinimumHeight(160)
        self.matches.currentItemChanged.connect(self._pick)
        self.matches.itemClicked.connect(self._apply_clicked_pick)
        self.matches.verticalScrollBar().valueChanged.connect(self._load_more_matches)
        self._column_fit_timer = QTimer(self)
        self._column_fit_timer.setSingleShot(True)
        self._column_fit_timer.timeout.connect(self._fit_match_columns_to_viewport)
        self._matches_viewport = self.matches.viewport()
        self._matches_viewport.installEventFilter(self)
        # Choosing a template rebuilds five steps, which is ~100 ms of work that has to
        # happen; arrow-keying down the list asked for it once per row it passed through.
        # The list still moves at once (Qt owns that); navigation waits for the reader to
        # settle on one, while an explicit mouse click takes that row immediately.
        self._pick_timer = QTimer(self)
        self._pick_timer.setSingleShot(True)
        self._pick_timer.setInterval(_SETTLE_MS)
        self._pick_timer.timeout.connect(self._apply_pick)
        self._pending_key: Optional[int] = None
        selection_layout.addWidget(self.matches, 1)
        chosen = QGroupBox("The chosen template")
        chosen_layout = QVBoxLayout(chosen)
        self.summary = QLabel("Choose a template item.")
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        chosen_layout.addWidget(self.summary)
        selection_layout.addWidget(chosen)
        self.workspace_layout.addWidget(self.selection_column, 2)
        self.preview_group = QGroupBox("Preview")
        self.preview_group.setMinimumHeight(340)
        preview_layout = QVBoxLayout(self.preview_group)
        preview_note = QLabel(
            "Preview controls: left-drag orbits around the model; middle-drag, right-drag, or Shift+left-drag pans; "
            "mouse wheel zooms; Fit resets the view framing. These controls only move the preview camera/view."
        )
        preview_note.setObjectName("new_item_intro")
        preview_note.setWordWrap(True)
        preview_layout.addWidget(preview_note)
        self.preview_holder = QWidget(self.preview_group)
        self.preview_holder_layout = QVBoxLayout(self.preview_holder)
        self.preview_holder_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.addWidget(self.preview_holder, 1)
        self.preview_status = QLabel("")
        self.preview_status.setObjectName("new_item_intro")
        self.preview_status.setWordWrap(True)
        preview_layout.addWidget(self.preview_status)
        self.workspace_layout.addWidget(self.preview_group, 3)
        layout.addLayout(self.workspace_layout, 1)
        self._preview = None
        controller.snapshot_ready.connect(self._refresh_matches)
        controller.template_changed.connect(self._show_template)

    def mount_preview(self, preview: QWidget) -> None:
        """Keep the one resident item viewport under the selected template."""

        if self._preview is not preview:
            self._preview = preview
            preview.status_changed.connect(self.preview_status.setText)
        if preview.parentWidget() is not self.preview_holder:
            self.preview_holder_layout.addWidget(preview, 1)

    def _refresh_matches(self, *_args) -> None:
        self._syncing = True
        try:
            self.matches.clear()
            self._match_options = self._controller.template_options(self.filter_edit.text(), limit=None)
            self._sort_match_options()
            self._append_match_rows(preferred_key=self._controller.draft.template_key)
        finally:
            self._syncing = False

    def _append_match_rows(self, count: int = _MATCH_PAGE_SIZE, *, preferred_key: Optional[int] = None) -> None:
        start = self.matches.topLevelItemCount()
        end = min(start + count, len(self._match_options))
        for key, internal_name, item_name, equip in self._match_options[start:end]:
            item = QTreeWidgetItem([internal_name, item_name, str(key), equip])
            item.setData(0, Qt.UserRole, key)
            self.matches.addTopLevelItem(item)
            if key == preferred_key:
                self.matches.setCurrentItem(item)

    def _load_more_matches(self, value: int) -> None:
        if self._syncing or self.matches.topLevelItemCount() >= len(self._match_options):
            return
        scroll_bar = self.matches.verticalScrollBar()
        threshold = scroll_bar.maximum() - max(1, scroll_bar.pageStep() // 3)
        if int(value) < threshold:
            return
        self._syncing = True
        try:
            self._append_match_rows()
        finally:
            self._syncing = False

    def _sort_match_options(self) -> None:
        column = self._sort_column
        if column < 0:
            return

        def sort_key(option: tuple[int, str, str, str]):
            key, internal_name, item_name, equip = option
            values = (internal_name.casefold(), item_name.casefold(), int(key), equip.casefold())
            return values[column], internal_name.casefold(), int(key)

        self._match_options.sort(
            key=sort_key,
            reverse=self._sort_order == Qt.SortOrder.DescendingOrder,
        )

    def _sort_matches_by_column(self, column: int) -> None:
        if self._syncing or not 0 <= int(column) < self.matches.columnCount():
            return
        column = int(column)
        if column == self._sort_column:
            self._sort_order = (
                Qt.SortOrder.DescendingOrder
                if self._sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self._sort_column = column
            self._sort_order = Qt.SortOrder.AscendingOrder

        current = self.matches.currentItem()
        current_key = current.data(0, Qt.UserRole) if current is not None else None
        visible_count = max(_MATCH_PAGE_SIZE, self.matches.topLevelItemCount())
        self._syncing = True
        try:
            self.matches.header().setSortIndicator(self._sort_column, self._sort_order)
            self.matches.header().setSortIndicatorShown(True)
            self._sort_match_options()
            self.matches.clear()
            self._append_match_rows(visible_count, preferred_key=current_key if isinstance(current_key, int) else None)
        finally:
            self._syncing = False

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt virtual method
        if (
            hasattr(self, "_matches_viewport")
            and watched is self._matches_viewport
            and event.type() == QEvent.Type.Resize
        ):
            self._column_fit_timer.start(0)
        return super().eventFilter(watched, event)

    def _match_column_resized(self, column: int, _old_size: int, _new_size: int) -> None:
        if self._column_widths_initialized and not self._resizing_match_columns:
            self._fit_match_columns_to_viewport(changed_column=int(column))

    def _fit_match_columns_to_viewport(self, *, changed_column: int = -1) -> None:
        if self._resizing_match_columns:
            return
        available = self._matches_viewport.width()
        if available < 320:
            return
        header = self.matches.header()
        self._resizing_match_columns = True
        try:
            if not self._column_widths_initialized:
                key_width = max(80, round(available * 0.11))
                type_width = max(110, round(available * 0.17))
                name_width = max(200, available - key_width - type_width)
                internal_width = round(name_width * 0.56)
                widths = (internal_width, name_width - internal_width, key_width, type_width)
                for column, width in enumerate(widths):
                    header.resizeSection(column, width)
                self._column_widths_initialized = True
                return

            widths = [header.sectionSize(column) for column in range(self.matches.columnCount())]
            gap = available - sum(widths)
            if 0 <= changed_column < self.matches.columnCount():
                if gap > 2:
                    target = 0 if changed_column == self.matches.columnCount() - 1 else self.matches.columnCount() - 1
                    header.resizeSection(target, widths[target] + gap)
                return
            if abs(gap) <= 2:
                return
            remaining = available
            total = max(1, sum(widths))
            for column, width in enumerate(widths):
                fitted = remaining if column == len(widths) - 1 else max(
                    header.minimumSectionSize(),
                    round(available * width / total),
                )
                header.resizeSection(column, fitted)
                remaining -= fitted
        finally:
            self._resizing_match_columns = False

    def _pick(self, current: Optional[QTreeWidgetItem], _previous=None) -> None:
        if self._syncing or current is None:
            return
        key = current.data(0, Qt.UserRole)
        if isinstance(key, int) and key != self._controller.draft.template_key:
            self._pending_key = key
            self._pick_timer.start()

    def _apply_pick(self) -> None:
        """The row the reader stopped on, once they have stopped on it."""

        key, self._pending_key = self._pending_key, None
        if key is not None and key != self._controller.draft.template_key:
            self._controller.set_template(key)

    def _apply_clicked_pick(self, current: QTreeWidgetItem, _column: int = 0) -> None:
        """Take an explicitly clicked row now; only row navigation needs settling."""

        if self._syncing:
            return
        key = current.data(0, Qt.UserRole)
        self._pick_timer.stop()
        self._pending_key = key if isinstance(key, int) and key != self._controller.draft.template_key else None
        self._apply_pick()

    def apply_pending_pick(self) -> None:
        """Take the pending row now: leaving the step must not leave it unchosen."""

        if self._pick_timer.isActive():
            self._pick_timer.stop()
            self._apply_pick()

    def prefill(self, template_key: int) -> None:
        self._pick_timer.stop()
        self._pending_key = None
        self.filter_edit.setText(str(template_key))
        self._controller.set_template(template_key)
        self._refresh_matches()

    def _show_template(self, key: object) -> None:
        if key is None:
            self.summary.setText("Choose a template item.")
            self.preview_status.setText("")
            return
        self.summary.setText("\n".join(self._controller.template_summary()))


__all__ = ["TemplatePanel"]
