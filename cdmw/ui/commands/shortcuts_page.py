"""Settings > Shortcuts: one place to search, rebind, reset and see conflicts (P12 step 4)."""

from __future__ import annotations

from PySide6.QtCore import QKeyCombination, Qt
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


class KeyEdit(QKeySequenceEdit):
    """One recorded key. Qt's editor drops the numpad; with ``keep_numpad`` it is kept (``Num+1``)."""

    def __init__(self, text: str, parent: QWidget | None = None, *, keep_numpad: bool = False) -> None:
        super().__init__(QKeySequence(text), parent)
        self.setMaximumSequenceLength(1)
        self._keep_numpad = keep_numpad
        self.touched = False

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().keyPressEvent(event)
        self.touched = True
        numpad = Qt.KeyboardModifier.KeypadModifier
        sequence = self.keySequence()
        if self._keep_numpad and event.modifiers() & numpad and sequence.count():
            combination = sequence[0]
            if not combination.keyboardModifiers() & numpad:
                self.setKeySequence(QKeySequence(QKeyCombination(combination.keyboardModifiers() | numpad,
                                                                 combination.key())))

    def text(self) -> str:
        return self.keySequence().toString(QKeySequence.SequenceFormat.PortableText)


class KeyDialog(QDialog):
    """Record a command's keys (a first and a second); leave both empty to unbind.

    ``check`` turns the recorded keys into the keys to save, or names why they
    cannot be saved; the Mesh Editor helper's commands use its grammar there.
    """

    def __init__(self, label: str, keys: tuple[str, ...], parent: QWidget | None = None,
                 *, conflict_for=None, check=None, shown=None, keep_numpad: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle("Change Shortcut")
        self._original = tuple(keys)
        self._check = check or (lambda recorded: (recorded, ""))
        shown = shown or (lambda key: key)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(_translate(label)))
        self.editors: list[KeyEdit] = []
        for slot, title in enumerate(("First key", "Second key")):
            layout.addWidget(QLabel(_translate(title), self))
            editor = KeyEdit(shown(keys[slot]) if slot < len(keys) else "", self, keep_numpad=keep_numpad)
            editor.keySequenceChanged.connect(lambda _sequence: self._show_state())
            layout.addWidget(editor)
            self.editors.append(editor)
        self.editor = self.editors[0]
        # The conflict, or why a key cannot be used, is named before anything is saved.
        self.conflict = QLabel(self)
        self.conflict.setObjectName("HintLabel")
        self.conflict.setWordWrap(True)
        layout.addWidget(self.conflict)
        self._conflict_for = conflict_for or (lambda _keys: "")
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._show_state()

    def recorded(self) -> list[str]:
        """Each slot's key: what was recorded in it, or the key it had when nothing was."""

        result: list[str] = []
        for slot, editor in enumerate(self.editors):
            key = editor.text() if editor.touched or slot >= len(self._original) else self._original[slot]
            if key and key not in result:
                result.append(key)
        return result

    def refusal(self) -> str:
        return self._check(self.recorded())[1]

    def _show_state(self) -> None:
        refusal = self.refusal()
        self.conflict.setText(_translate(refusal) if refusal else self._conflict_for(self.keys()))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not refusal)

    def keys(self) -> list[str]:
        keys, refusal = self._check(self.recorded())
        return [] if refusal else list(keys)

    def accept(self) -> None:
        if not self.refusal():
            super().accept()


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
        self._stale = False
        self.refill()

    def _registry_changed(self, _context: str = "") -> None:
        # Settings builds this page before the shell registers its commands, and
        # tools register theirs later still: a change while hidden is read on show.
        if self.isVisible():
            self.refill()
        else:
            self._stale = True

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._stale:
            self.refill()
        super().showEvent(event)

    # ----- content -------------------------------------------------------------
    def rows(self):
        return keymap_rows(self.registry, self.settings)

    def refill(self, *_args) -> None:
        self._stale = False
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
        dialog = self.key_dialog(row)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save(command_id, dialog.keys())

    def key_dialog(self, row) -> KeyDialog:
        """The dialog that changes ``row``'s keys; the helper's commands follow its grammar."""

        options = {}
        if row.helper:
            from cdmw.ui.commands.helper_keys import check_helper_keys, qt_key_text

            options = dict(check=lambda keys: check_helper_keys(keys, takes_modifier=row.takes_modifier),
                           shown=qt_key_text, keep_numpad=True)
        return KeyDialog(row.label, row.keys, self, conflict_for=lambda keys: self.conflict_text(row, keys),
                         **options)

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
