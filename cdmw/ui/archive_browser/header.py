"""Archive browser tree header settings and column menu helpers."""

from __future__ import annotations

from typing import List

from PySide6.QtWidgets import QMenu


class ArchiveBrowserHeaderMixin:
    """Archive browser tree column persistence and header menu helpers."""

    def _archive_tree_column_labels(self) -> List[str]:
        header_item = self.archive_tree.headerItem()
        return [
            header_item.text(column) or f"Column {column + 1}"
            for column in range(self.archive_tree.columnCount())
        ]

    def _archive_tree_visible_column_count(self) -> int:
        return sum(
            1
            for column in range(self.archive_tree.columnCount())
            if not self.archive_tree.isColumnHidden(column)
        )

    def _parse_archive_tree_column_ints(self, key: str, *, clamp_to_columns: bool = True) -> List[int]:
        raw_value = self.settings.value(key)
        if raw_value in (None, ""):
            return []
        if isinstance(raw_value, str):
            parts = [part.strip() for part in raw_value.split(",") if part.strip()]
        elif isinstance(raw_value, (list, tuple)):
            parts = list(raw_value)
        else:
            return []
        values: List[int] = []
        for part in parts:
            try:
                value = int(part)
            except (TypeError, ValueError):
                continue
            if not clamp_to_columns or 0 <= value < self.archive_tree.columnCount():
                values.append(value)
        return values

    def _apply_archive_tree_header_settings(self) -> None:
        if not hasattr(self, "archive_tree"):
            return
        header = self.archive_tree.header()
        if header is None:
            return
        widths = self._parse_archive_tree_column_ints("ui/archive_tree_v5_column_widths", clamp_to_columns=False)
        for column, width in enumerate(widths[: self.archive_tree.columnCount()]):
            if width > 0:
                header.resizeSection(column, max(48, width))
        order = self._parse_archive_tree_column_ints("ui/archive_tree_v5_column_order")
        if len(order) == self.archive_tree.columnCount() and len(set(order)) == self.archive_tree.columnCount():
            for target_visual, logical_index in enumerate(order):
                current_visual = header.visualIndex(logical_index)
                if current_visual >= 0 and current_visual != target_visual:
                    header.moveSection(current_visual, target_visual)
        hidden_columns = set(self._parse_archive_tree_column_ints("ui/archive_tree_v5_hidden_columns"))
        if len(hidden_columns) >= self.archive_tree.columnCount():
            hidden_columns = set()
        for column in range(self.archive_tree.columnCount()):
            self.archive_tree.setColumnHidden(column, column in hidden_columns)
        self.archive_tree.compact_hidden_columns()
        self._update_archive_tree_sort_indicator()
        self._schedule_archive_files_pane_fit_to_columns()

    def _save_archive_tree_header_settings(self) -> None:
        if not hasattr(self, "archive_tree"):
            return
        header = self.archive_tree.header()
        if header is None:
            return
        order = [
            str(header.logicalIndex(visual_index))
            for visual_index in range(self.archive_tree.columnCount())
        ]
        widths = [
            str(max(1, header.sectionSize(column)))
            for column in range(self.archive_tree.columnCount())
        ]
        hidden = [
            str(column)
            for column in range(self.archive_tree.columnCount())
            if self.archive_tree.isColumnHidden(column)
        ]
        self.settings.setValue("ui/archive_tree_v5_column_order", ",".join(order))
        self.settings.setValue("ui/archive_tree_v5_column_widths", ",".join(widths))
        self.settings.setValue("ui/archive_tree_v5_hidden_columns", ",".join(hidden))

    def _set_archive_tree_column_visible(self, column: int, visible: bool) -> None:
        if not (0 <= column < self.archive_tree.columnCount()):
            return
        if not visible and self._archive_tree_visible_column_count() <= 1:
            self.archive_tree.setColumnHidden(column, False)
            return
        self.archive_tree.setColumnHidden(column, not visible)
        self.archive_tree.compact_hidden_columns()
        self.schedule_settings_save()
        self._schedule_archive_files_pane_fit_to_columns()

    def _reset_archive_tree_columns(self) -> None:
        header = self.archive_tree.header()
        if header is None:
            return
        for column in range(self.archive_tree.columnCount()):
            self.archive_tree.setColumnHidden(column, False)
        for logical_index in range(self.archive_tree.columnCount()):
            current_visual = header.visualIndex(logical_index)
            if current_visual >= 0 and current_visual != logical_index:
                header.moveSection(current_visual, logical_index)
        default_widths = [360, 220, 110, 145, 84, 130, 122, 360]
        for column, width in enumerate(default_widths[: self.archive_tree.columnCount()]):
            header.resizeSection(column, width)
        self.schedule_settings_save()
        self._schedule_column_autofit()

    def _show_archive_tree_header_context_menu(self, position) -> None:
        if not hasattr(self, "archive_tree"):
            return
        menu = QMenu(self)
        for column, label in enumerate(self._archive_tree_column_labels()):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(not self.archive_tree.isColumnHidden(column))
            action.setEnabled(
                self.archive_tree.isColumnHidden(column)
                or self._archive_tree_visible_column_count() > 1
            )
            action.toggled.connect(
                lambda checked, current_column=column: self._set_archive_tree_column_visible(current_column, checked)
            )
        menu.addSeparator()
        show_all_action = menu.addAction("Show All Columns")
        show_all_action.triggered.connect(lambda _checked=False: self._set_all_archive_tree_columns_visible())
        reset_action = menu.addAction("Reset Columns")
        reset_action.triggered.connect(lambda _checked=False: self._reset_archive_tree_columns())
        menu.exec(self.archive_tree.header().mapToGlobal(position))

    def _set_all_archive_tree_columns_visible(self) -> None:
        for column in range(self.archive_tree.columnCount()):
            self.archive_tree.setColumnHidden(column, False)
        self.archive_tree.compact_hidden_columns()
        self.schedule_settings_save()


__all__ = ["ArchiveBrowserHeaderMixin"]
