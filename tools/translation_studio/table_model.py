"""A virtualised table over one language's 187,521 lines.

`QTableWidget` would need 187,521 row widgets built up front, which costs seconds and
hundreds of megabytes for a view showing thirty rows. `QAbstractTableModel` builds
nothing: it answers `data()` for the cells actually on screen, so loading a language and
filtering it stay instant.

The model holds a *view* — a tuple of entry indexes produced by a search — rather than
the catalogue's own order, so filtering is a cheap swap of that tuple and never touches
the underlying table.
"""

from __future__ import annotations

from typing import Optional, Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from .catalogue import TranslationCatalogue

KEY, CATEGORY, TEXT, REFERENCE = range(4)
_HEADERS = ("Key", "Group", "Text", "Reference")

#: Rows carrying an unsaved edit, so a pass is visible at a glance.
_EDITED_BACKGROUND = QColor(58, 74, 42)


class TranslationTableModel(QAbstractTableModel):
    def __init__(self, catalogue: Optional[TranslationCatalogue] = None, parent=None) -> None:
        super().__init__(parent)
        self._catalogue = catalogue
        self._view: tuple[int, ...] = ()
        self._categories: dict[int, str] = {}
        if catalogue is not None:
            self.set_catalogue(catalogue)

    # ------------------------------------------------------------------ wiring

    def set_catalogue(self, catalogue: Optional[TranslationCatalogue]) -> None:
        self.beginResetModel()
        self._catalogue = catalogue
        self._categories = dict(catalogue.categories()) if catalogue is not None else {}
        self._view = tuple(range(len(catalogue))) if catalogue is not None else ()
        self.endResetModel()

    def set_view(self, indexes: Sequence[int]) -> None:
        self.beginResetModel()
        self._view = tuple(indexes)
        self.endResetModel()

    @property
    def catalogue(self) -> Optional[TranslationCatalogue]:
        return self._catalogue

    def entry_index(self, row: int) -> Optional[int]:
        return self._view[row] if 0 <= row < len(self._view) else None

    # ------------------------------------------------------------- model plumbing

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._view)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(_HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        return _HEADERS[section]

    def flags(self, index: QModelIndex):
        base = super().flags(index)
        if index.isValid() and index.column() == TEXT:
            return base | Qt.ItemIsEditable
        return base

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid() or self._catalogue is None:
            return None
        entry_index = self.entry_index(index.row())
        if entry_index is None:
            return None
        row = self._catalogue.row(entry_index)
        column = index.column()
        if role in (Qt.DisplayRole, Qt.EditRole):
            if column == KEY:
                return row.key
            if column == CATEGORY:
                return self._categories.get(row.category, str(row.category))
            if column == TEXT:
                return row.text
            return row.reference
        if role == Qt.BackgroundRole and row.edited:
            return _EDITED_BACKGROUND
        if role == Qt.ToolTipRole:
            if column == REFERENCE and row.reference:
                return row.reference
            if column == TEXT:
                shipped = self._catalogue.table.entries[entry_index].text
                return f"Ships as: {shipped}" if row.edited else row.text
        return None

    def setData(self, index: QModelIndex, value, role=Qt.EditRole) -> bool:  # noqa: N802
        if role != Qt.EditRole or not index.isValid() or index.column() != TEXT:
            return False
        if self._catalogue is None:
            return False
        entry_index = self.entry_index(index.row())
        if entry_index is None:
            return False
        self._catalogue.set_text(entry_index, str(value))
        # The whole row repaints: the edit changes the text and the row's highlight.
        left = self.index(index.row(), 0)
        right = self.index(index.row(), len(_HEADERS) - 1)
        self.dataChanged.emit(left, right, [Qt.DisplayRole, Qt.BackgroundRole])
        return True

    def revert_row(self, row: int) -> None:
        if self._catalogue is None:
            return
        entry_index = self.entry_index(row)
        if entry_index is None:
            return
        self._catalogue.revert(entry_index)
        left = self.index(row, 0)
        right = self.index(row, len(_HEADERS) - 1)
        self.dataChanged.emit(left, right, [Qt.DisplayRole, Qt.BackgroundRole])

    def refresh(self) -> None:
        """Repaint everything: used after a reset, which touches arbitrary rows."""

        if not self._view:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self._view) - 1, len(_HEADERS) - 1),
            [Qt.DisplayRole, Qt.BackgroundRole],
        )
