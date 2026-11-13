"""Choose which models of a large folder to list in Drafts & Mods.

Add Mod Folder lists every model of a mod. An extracted game folder holds
thousands, so this asks which ones to add: filter by any part of the name or
path, select up to the listing limit, and each chosen model becomes one row
that Continue Editing opens with the folder's own material and textures.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePosixPath

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.mesh_saved_work_service import MAX_FOLDER_MODELS

# Enough to scroll; a longer match list asks for a narrower filter instead of
# building thousands of rows on the UI thread.
VISIBLE_MODEL_ROWS = 500
_PATH_ROLE = Qt.ItemDataRole.UserRole


class FolderModelPicker(QDialog):
    """A filterable list of a folder's models with a capped multi-selection."""

    def __init__(self, model_paths: Sequence[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FolderModelPicker")
        self.setWindowTitle("Choose Models to Add")
        self._paths = tuple(model_paths)
        self._keys = tuple(path.casefold() for path in self._paths)
        self._chosen: dict[str, str] = {}
        layout = QVBoxLayout(self)
        intro = QLabel(
            "This folder holds more models than one mod. Choose the ones to list; "
            "each opens with the folder's own material and textures, and the game's files for the rest.",
            self,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.filter_edit = QLineEdit(self)
        self.filter_edit.setObjectName("FolderModelPickerFilter")
        self.filter_edit.setPlaceholderText("Filter by model name or path")
        self.filter_edit.setClearButtonEnabled(True)
        layout.addWidget(self.filter_edit)
        self.list = QListWidget(self)
        self.list.setObjectName("FolderModelPickerList")
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setUniformItemSizes(True)
        layout.addWidget(self.list, 1)
        self.count_label = QLabel("", self)
        self.count_label.setObjectName("FolderModelPickerCount")
        self.count_label.setWordWrap(True)
        layout.addWidget(self.count_label)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self.add_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.add_button.setText("Add Selected")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.filter_edit.textChanged.connect(lambda _text: self._populate())
        self.list.itemSelectionChanged.connect(self._selection_changed)
        self.list.itemDoubleClicked.connect(lambda _item: self.accept() if self.add_button.isEnabled() else None)
        self.resize(720, 560)
        self._populate()

    def selected_paths(self) -> list[str]:
        """The chosen game paths, in the folder's order."""

        return [path for path in self._paths if path.casefold() in self._chosen]

    def _matches(self) -> list[str]:
        words = self.filter_edit.text().casefold().split()
        return [path for path, key in zip(self._paths, self._keys) if all(word in key for word in words)]

    def _populate(self) -> None:
        matches = self._matches()
        self.list.blockSignals(True)
        self.list.clear()
        for path in matches[:VISIBLE_MODEL_ROWS]:
            pure = PurePosixPath(path)
            item = QListWidgetItem(f"{pure.name}    {pure.parent.as_posix()}")
            item.setData(_PATH_ROLE, path)
            item.setToolTip(path)
            self.list.addItem(item)
            # A model chosen under another filter stays chosen.
            item.setSelected(path.casefold() in self._chosen)
        self.list.blockSignals(False)
        self._shown = {path.casefold() for path in matches[:VISIBLE_MODEL_ROWS]}
        self._match_count = len(matches)
        self._sync()

    def _selection_changed(self) -> None:
        selected = {str(item.data(_PATH_ROLE)) for item in self.list.selectedItems()}
        # Only rows on screen can change; choices hidden by the filter are kept.
        self._chosen = {key: path for key, path in self._chosen.items() if key not in self._shown}
        self._chosen.update({path.casefold(): path for path in selected})
        self._sync()

    def _sync(self) -> None:
        chosen, matched, total = len(self._chosen), self._match_count, len(self._paths)
        if matched > VISIBLE_MODEL_ROWS:
            self.count_label.setText(
                f"{matched} of {total} models match; the first {VISIBLE_MODEL_ROWS} are shown. "
                f"Type more to narrow the list. {chosen} selected, up to {MAX_FOLDER_MODELS}."
            )
        else:
            self.count_label.setText(
                f"{matched} of {total} models match. {chosen} selected, up to {MAX_FOLDER_MODELS}."
            )
        self.add_button.setEnabled(1 <= chosen <= MAX_FOLDER_MODELS)


__all__ = ["FolderModelPicker", "VISIBLE_MODEL_ROWS"]
