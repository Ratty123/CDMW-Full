"""Tree column helpers for Research tab views."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtWidgets import QTreeWidget

from cdmw.ui.widgets import has_persistent_tree_column_widths, make_tree_columns_persistent

__all__ = [
    "auto_fit_persisted_research_tree_columns",
    "auto_fit_research_tree_columns",
    "has_saved_research_tree_columns",
    "make_research_tree_columns_persistent",
    "research_tree_storage_key",
]


def research_tree_storage_key(storage_name: str) -> str:
    return f"research/{storage_name}"


def make_research_tree_columns_persistent(
    tree: QTreeWidget,
    settings: object,
    storage_name: str,
    *,
    minimum_width: int = 56,
) -> None:
    make_tree_columns_persistent(tree, settings, research_tree_storage_key(storage_name), minimum_width=minimum_width)


def has_saved_research_tree_columns(
    tree: QTreeWidget,
    settings: object,
    storage_name: str,
    *,
    minimum_width: int = 56,
) -> bool:
    return has_persistent_tree_column_widths(
        settings,
        research_tree_storage_key(storage_name),
        tree.columnCount(),
        minimum_width=minimum_width,
    )


def auto_fit_research_tree_columns(
    tree: QTreeWidget,
    *,
    stretch_column: int,
    min_widths: Mapping[int, int],
    has_saved_columns: bool = False,
) -> None:
    header = tree.header()
    if header is None or tree.columnCount() <= 0:
        return
    viewport_width = max(tree.viewport().width(), tree.width() - 24, 0)
    if viewport_width <= 0:
        return
    if has_saved_columns:
        saved_total = sum(
            header.sectionSize(column)
            for column in range(tree.columnCount())
            if not tree.isColumnHidden(column)
        )
        if saved_total >= viewport_width - 24:
            return
    tree.setUpdatesEnabled(False)
    try:
        fixed_width = 0
        for column in range(tree.columnCount()):
            if column == stretch_column:
                continue
            width = max(min_widths.get(column, 72), header.sectionSize(column))
            header.resizeSection(column, width)
            fixed_width += width
        header.resizeSection(
            stretch_column,
            max(min_widths.get(stretch_column, 220), viewport_width - fixed_width - 12),
        )
    finally:
        tree.setUpdatesEnabled(True)


def auto_fit_persisted_research_tree_columns(
    tree: QTreeWidget,
    settings: object,
    storage_name: str,
    *,
    stretch_column: int,
    min_widths: Mapping[int, int],
) -> None:
    auto_fit_research_tree_columns(
        tree,
        stretch_column=stretch_column,
        min_widths=min_widths,
        has_saved_columns=has_saved_research_tree_columns(tree, settings, storage_name),
    )
