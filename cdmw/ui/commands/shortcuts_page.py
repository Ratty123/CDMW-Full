"""Settings > Shortcuts: one place to search, rebind, reset and see conflicts (P12 step 4)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.ui.commands.keymap import conflicts, keymap_rows, reset_all, save_keys
from cdmw.ui.commands.registry import CommandRegistry

#: Context -> the name the page shows for it.
CONTEXT_LABELS = {
    "shell": "Everywhere",
    "browse": "Browse Archives",
    "mesh_editor": "Mesh Editor",
    "texture_editor": "Texture Editor",
    "new_item": "Create New Item",
    "mod_management": "Mod Management",
}
_ID_ROLE = Qt.ItemDataRole.UserRole + 1


def _translate(text: str) -> str:
    try:
        from cdmw.ui.localization import _active_ui_localizer

        localizer = _active_ui_localizer()
        return str(localizer.translate(text)) if localizer is not None else text
    except Exception:
        return text


class KeyDialog(QDialog):
    """Record one key for a command; leave it empty to unbind."""

    def __init__(self, label: str, keys: tuple[str, ...], parent: QWidget | None = None,
                 *, conflict_for=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Change Shortcut")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(_translate(label)))
        self.editor = QKeySequenceEdit(QKeySequence(keys[0] if keys else ""), self)
        self.editor.setMaximumSequenceLength(1)
        layout.addWidget(self.editor)
        # The conflict is named while the key is chosen, before anything is saved.
        self.conflict = QLabel(self)
        self.conflict.setObjectName("HintLabel")
        self.conflict.setWordWrap(True)
        layout.addWidget(self.conflict)
        self._conflict_for = conflict_for or (lambda _keys: "")
        self.editor.keySequenceChanged.connect(lambda _sequence: self._show_conflict())
        self._show_conflict()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _show_conflict(self) -> None:
        self.conflict.setText(self._conflict_for(self.keys()))

    def keys(self) -> list[str]:
        text = self.editor.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        return [text] if text else []


class ShortcutsPage(QWidget):
    """Every command's keys, searchable, with conflicts named before they are saved."""

    def __init__(self, registry: CommandRegistry, settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ShortcutsPage")
        self.registry, self.settings = registry, settings
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit(self)
        self.search.setObjectName("ShortcutsSearch")
        self.search.setPlaceholderText("Search commands or keys")
        layout.addWidget(self.search)
        self.table = QTableWidget(0, 4, self)
        self.table.setObjectName("ShortcutsTable")
        self.table.setHorizontalHeaderLabels(["Where", "Command", "Keys", "Conflicts with"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(320)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        self.change_button = QPushButton("Change...", self)
        self.unbind_button = QPushButton("Unbind", self)
        self.reset_button = QPushButton("Reset", self)
        self.reset_all_button = QPushButton("Reset All", self)
        for button in (self.change_button, self.unbind_button, self.reset_button):
            row.addWidget(button)
        row.addStretch(1)
        row.addWidget(self.reset_all_button)
        layout.addLayout(row)
        self.search.textChanged.connect(self.refill)
        self.table.itemDoubleClicked.connect(lambda _item: self.change_selected())
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        self.change_button.clicked.connect(self.change_selected)
        self.unbind_button.clicked.connect(lambda: self._save_selected([]))
        self.reset_button.clicked.connect(lambda: self._save_selected(None))
        self.reset_all_button.clicked.connect(self._reset_all)
        registry.keymap_changed.connect(self.refill)
        # Bound methods: Qt drops these connections when the page is destroyed.
        registry.changed.connect(self._registry_changed)
        self.refill()

    def _registry_changed(self, _context: str = "") -> None:
        if self.isVisible():
            self.refill()

    # ----- content -------------------------------------------------------------
    def rows(self):
        return keymap_rows(self.registry, self.settings)

    def refill(self, *_args) -> None:
        text = self.search.text().casefold().split()
        rows = self.rows()
        clashes = conflicts(rows)
        labels = {row.command_id: _translate(row.label) for row in rows}
        selected = self.selected_command_id()
        self.table.setRowCount(0)
        for row in rows:
            where = _translate(CONTEXT_LABELS.get(row.context, row.context))
            label = labels[row.command_id].replace("&", "")
            keys = ", ".join(row.keys)
            others = ", ".join(labels.get(other, other) for other in clashes.get(row.command_id, ()))
            haystack = " ".join((where, label, row.label, row.command_id, keys)).casefold()
            if text and not all(word in haystack for word in text):
                continue
            index = self.table.rowCount()
            self.table.insertRow(index)
            for column, value in enumerate((where, label, keys, others)):
                item = QTableWidgetItem(value)
                item.setData(_ID_ROLE, row.command_id)
                if column == 2 and row.changed:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.table.setItem(index, column, item)
            if row.command_id == selected:
                self.table.selectRow(index)
        self._sync_buttons()

    def selected_command_id(self) -> str:
        items = self.table.selectedItems()
        return str(items[0].data(_ID_ROLE) or "") if items else ""

    def _sync_buttons(self) -> None:
        chosen = bool(self.selected_command_id())
        for button in (self.change_button, self.unbind_button, self.reset_button):
            button.setEnabled(chosen)

    # ----- editing -------------------------------------------------------------
    def change_selected(self) -> None:
        command_id = self.selected_command_id()
        row = next((r for r in self.rows() if r.command_id == command_id), None)
        if row is None:
            return
        dialog = KeyDialog(row.label, row.keys, self, conflict_for=lambda keys: self.conflict_text(row, keys))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save(command_id, dialog.keys())

    def conflict_text(self, row, keys: list[str]) -> str:
        """Which commands the proposed keys would clash with, if any."""

        from dataclasses import replace

        rows = [replace(r, keys=tuple(keys)) if r.command_id == row.command_id else r for r in self.rows()]
        others = conflicts(rows).get(row.command_id, ())
        if not others:
            return ""
        names = ", ".join(_translate(r.label) for r in rows if r.command_id in others)
        return _translate("Also used by: {names}").replace("{names}", names)

    def _save_selected(self, keys: list[str] | None) -> None:
        command_id = self.selected_command_id()
        if command_id:
            self._save(command_id, keys)

    def _save(self, command_id: str, keys: list[str] | None) -> None:
        save_keys(self.registry, self.settings, command_id, keys)

    def _reset_all(self) -> None:
        reset_all(self.registry, self.settings)
