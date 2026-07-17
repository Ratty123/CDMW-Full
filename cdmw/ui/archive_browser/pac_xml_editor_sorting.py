"""Opt-in, natural column sorting for PAC XML tree views."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem


_NUMBER_PATTERN = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_HEX_PATTERN = re.compile(r"^[+-]?0x[0-9a-f]+$", re.IGNORECASE)
_NATURAL_CHUNKS = re.compile(r"(\d+)")


def _natural_sort_key(value: object) -> tuple[object, ...]:
    text = str(value or "").strip()
    if _HEX_PATTERN.fullmatch(text):
        sign = -1 if text.startswith("-") else 1
        unsigned = text.lstrip("+-")
        return (0, Decimal(sign * int(unsigned, 16)))
    if _NUMBER_PATTERN.fullmatch(text):
        try:
            return (0, Decimal(text))
        except InvalidOperation:
            pass
    chunks = tuple(
        (0, int(chunk)) if chunk.isdigit() else (1, chunk.casefold())
        for chunk in _NATURAL_CHUNKS.split(text)
        if chunk
    )
    return (1, chunks)


class NaturalSortTreeWidgetItem(QTreeWidgetItem):
    def __init__(self, texts: Sequence[str], *, source_order: int = 0) -> None:
        super().__init__(list(texts))
        self.source_order = int(source_order)

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        column = tree.active_sort_column if isinstance(tree, HeaderSortableTreeWidget) else 0
        left = (_natural_sort_key(self.text(column)), self.source_order)
        right = (
            _natural_sort_key(other.text(column)),
            int(getattr(other, "source_order", 0)),
        )
        return left < right


class HeaderSortableTreeWidget(QTreeWidget):
    """Preserve insertion order until the user explicitly clicks a header."""

    def __init__(self, parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.active_sort_column = -1
        self.active_sort_order = Qt.AscendingOrder
        self.setSortingEnabled(False)
        header = self.header()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(False)
        header.setSortIndicatorClearable(False)
        header.setToolTip("Click a column heading to sort; click it again to reverse the order.")
        header.sectionClicked.connect(self._sort_from_header)

    def _sort_from_header(self, column: int) -> None:
        if column == self.active_sort_column:
            order = (
                Qt.DescendingOrder
                if self.active_sort_order == Qt.AscendingOrder
                else Qt.AscendingOrder
            )
        else:
            order = Qt.AscendingOrder
        self.active_sort_column = int(column)
        self.active_sort_order = order
        self.header().setSortIndicator(column, order)
        self.header().setSortIndicatorShown(True)
        self.sortItems(column, order)

    def resort(self) -> None:
        if self.active_sort_column >= 0:
            self.sortItems(self.active_sort_column, self.active_sort_order)


__all__ = ["HeaderSortableTreeWidget", "NaturalSortTreeWidgetItem"]
