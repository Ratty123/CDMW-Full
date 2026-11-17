"""Settings > Shortcuts: one place to search, rebind, reset and see conflicts (P12 step 4).

Every command's keys sit in one table with a column each for the command, its
keys, where it applies and what it clashes with. Rows group by area, sort by any
column and filter; a key is recorded in place (double-click the Keys cell) or
with Change..., which also takes a second key.
"""

from __future__ import annotations

from PySide6.QtCore import QKeyCombination, QTimer, Qt
from PySide6.QtGui import QBrush, QColor, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.ui.commands.keymap import conflicts, keymap_rows, reset_all, save_keys
from cdmw.ui.commands.palette import PALETTE_COMMAND
from cdmw.ui.commands.registry import CommandRegistry, display_label

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
#: What a row sorts by: an area's place for a group, the column's text for a command.
_SORT_ROLE = Qt.ItemDataRole.UserRole + 2
COLUMN_COMMAND, COLUMN_KEYS, COLUMN_WHERE, COLUMN_CONFLICTS = range(4)
#: The Show filter's entries, in order.
SHOW_ALL, SHOW_CONFLICTS, SHOW_CHANGED = range(3)
EDIT_HINT = ("Double-click a key to record a new one in place; Escape cancels. "
             "Change... also sets a second key.")
RECORD_HINT = "Press the new key. Escape cancels."
RESTORE_ALL_QUESTION = "Restore the default keys of every command, in every tool?"


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


class _SortItem(QTreeWidgetItem):
    """Sorts by ``_SORT_ROLE``, so areas keep their order and text sorts without case."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        column = tree.sortColumn() if tree is not None else 0
        mine, theirs = self.data(column, _SORT_ROLE), other.data(column, _SORT_ROLE)
        if mine is None or theirs is None:
            return super().__lt__(other)
        return mine < theirs


class KeyCaptureDelegate(QStyledItemDelegate):
    """Records one key in the Keys cell: the first key pressed is saved, Escape cancels."""

    def __init__(self, page: "ShortcutsPage") -> None:
        super().__init__(page.table)
        self.page = page

    def createEditor(self, parent, option, index):  # noqa: N802 - Qt API
        row = self.page.row_for(str(index.data(_ID_ROLE) or ""))
        if index.column() != COLUMN_KEYS or row is None or row.takes_modifier:
            return None
        editor = KeyEdit("", parent, keep_numpad=row.helper)
        editor.setObjectName("ShortcutsInlineKey")
        editor.setProperty("_cdmw_command_id", row.command_id)
        editor.keySequenceChanged.connect(lambda _sequence, e=editor: self._recorded(e))
        self.page.show_message(_translate(RECORD_HINT))
        return editor

    def setEditorData(self, editor, index) -> None:  # noqa: N802 - Qt API
        pass  # the editor starts empty: it records

    def setModelData(self, editor, model, index) -> None:  # noqa: N802 - Qt API
        # The keymap, not the cell, holds the key. Saving refills the table, so it
        # waits until the editor is gone.
        if editor.keySequence().count():
            command_id, key = str(editor.property("_cdmw_command_id") or ""), editor.text()
            QTimer.singleShot(0, lambda: self.page.record_key(command_id, key))

    def updateEditorGeometry(self, editor, option, index) -> None:  # noqa: N802 - Qt API
        editor.setGeometry(option.rect)

    def paint(self, painter, option, index) -> None:
        # The theme styles every item, which hides a row's own background; a conflict's tint is painted here.
        brush = index.data(Qt.ItemDataRole.BackgroundRole)
        if isinstance(brush, QBrush) and brush.style() != Qt.BrushStyle.NoBrush                 and not option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, brush)
        super().paint(painter, option, index)

    def _recorded(self, editor: KeyEdit) -> None:
        if editor.keySequence().count():
            self.commitData.emit(editor)
            self.closeEditor.emit(editor, QAbstractItemDelegate.EndEditHint.NoHint)


class ShortcutsPage(QWidget):
    """Every command's keys in one sortable, grouped table, with conflicts named before they are saved."""

    def __init__(self, registry: CommandRegistry, settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ShortcutsPage")
        self.registry, self.settings = registry, settings
        self._collapsed: set[str] = set()
        self._rows_by_id: dict = {}
        self._stale = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        filters = QHBoxLayout()
        self.search = QLineEdit(self)
        self.search.setObjectName("ShortcutsSearch")
        self.search.setPlaceholderText("Search commands or keys")
        self.search.setClearButtonEnabled(True)
        filters.addWidget(self.search, 1)
        self.show_label = QLabel("Show", self)
        filters.addWidget(self.show_label)
        self.show_combo = QComboBox(self)
        self.show_combo.setObjectName("ShortcutsShowFilter")
        self.show_combo.addItems(["All commands", "With conflicts", "Changed keys"])
        filters.addWidget(self.show_combo)
        self.group_checkbox = QCheckBox("Group by area", self)
        self.group_checkbox.setObjectName("ShortcutsGroupByArea")
        self.group_checkbox.setChecked(True)
        filters.addWidget(self.group_checkbox)
        layout.addLayout(filters)

        self.table = QTreeWidget(self)
        self.table.setObjectName("ShortcutsTable")
        self.table.setHeaderLabels(["Command", "Keys", "Where", "Conflicts with"])
        self.table.setUniformRowHeights(True)
        self.table.setIndentation(self.fontMetrics().height())  # follows the font, so the display scale
        self.table.setAlternatingRowColors(True)
        self.table.setAllColumnsShowFocus(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.setItemDelegate(KeyCaptureDelegate(self))
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(COLUMN_COMMAND, Qt.SortOrder.AscendingOrder)
        header = self.table.header()
        header.setStretchLastSection(False)
        header.setSectionsMovable(False)
        header.setSectionResizeMode(COLUMN_COMMAND, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COLUMN_KEYS, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COLUMN_WHERE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COLUMN_CONFLICTS, QHeaderView.ResizeMode.Stretch)
        # Room for a few rows on a small window; the Settings page gives it the rest of its height.
        self.table.setMinimumHeight(self.fontMetrics().height() * 10)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.table, 1)

        self.message = QLabel(EDIT_HINT, self)
        self.message.setObjectName("HintLabel")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

        row = QHBoxLayout()
        self.change_button = QPushButton("Change...", self)
        self.unbind_button = QPushButton("Unbind", self)
        self.reset_button = QPushButton("Reset to default", self)
        self.reset_all_button = QPushButton("Restore all defaults", self)
        self.reset_all_button.setObjectName("ShortcutsRestoreAllDefaults")
        for button in (self.change_button, self.unbind_button, self.reset_button):
            row.addWidget(button)
        row.addStretch(1)
        self.conflict_count = QLabel(self)
        self.conflict_count.setObjectName("ShortcutsConflictCount")
        row.addWidget(self.conflict_count)
        row.addWidget(self.reset_all_button)
        layout.addLayout(row)

        self.search.textChanged.connect(self.refill)
        self.show_combo.currentIndexChanged.connect(self.refill)
        self.group_checkbox.toggled.connect(self.refill)
        self.table.itemDoubleClicked.connect(self._double_clicked)
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        self.table.itemCollapsed.connect(self._group_collapsed)
        self.table.itemExpanded.connect(self._group_expanded)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.itemDelegate().closeEditor.connect(self._editor_closed)
        self.change_button.clicked.connect(self.change_selected)
        self.unbind_button.clicked.connect(lambda: self._save_selected([]))
        self.reset_button.clicked.connect(lambda: self._save_selected(None))
        self.reset_all_button.clicked.connect(self._reset_all)
        registry.keymap_changed.connect(self.refill)
        # Bound methods: Qt drops these connections when the page is destroyed.
        registry.changed.connect(self._registry_changed)
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

    def _editing(self) -> bool:
        return self.table.state() == QAbstractItemView.State.EditingState

    def _editor_closed(self, *_args) -> None:
        self.show_message("")
        if self._stale:
            QTimer.singleShot(0, self.refill)

    def _group_collapsed(self, item: QTreeWidgetItem) -> None:
        self._collapsed.add(str(item.data(0, _ID_ROLE) or ""))

    def _group_expanded(self, item: QTreeWidgetItem) -> None:
        self._collapsed.discard(str(item.data(0, _ID_ROLE) or ""))

    # ----- content -------------------------------------------------------------
    def rows(self):
        return keymap_rows(self.registry, self.settings)

    def row_for(self, command_id: str):
        return self._rows_by_id.get(command_id)

    @staticmethod
    def _conflict_colors() -> tuple[QColor, QColor]:
        from cdmw.ui.themes import get_theme

        app = QApplication.instance()
        theme = get_theme(str(app.property("_cdmw_theme_key") or "") if app is not None else "")
        return QColor(theme.get("warning_text", "#8a5a00")), QColor(theme.get("warning_bg", "#fff4d8"))

    def refill(self, *_args) -> None:
        if self._editing():
            self._stale = True  # the open key editor keeps its row; the table refills when it closes
            return
        self._stale = False
        words = self.search.text().casefold().split()
        show = self.show_combo.currentIndex()
        grouped = self.group_checkbox.isChecked()
        rows = self.rows()
        self._rows_by_id = {row.command_id: row for row in rows}
        clashes = conflicts(rows)
        labels = {row.command_id: display_label(_translate(row.label)) for row in rows}
        selected = self.selected_command_id()
        warning_text, warning_back = self._conflict_colors()
        warning_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        area_order = {context: index for index, context in enumerate(CONTEXT_LABELS)}
        self.table.setSortingEnabled(False)
        self.table.clear()
        self.table.setRootIsDecorated(grouped)
        groups: dict[str, QTreeWidgetItem] = {}
        reselect = None
        for row in rows:
            clash_ids = clashes.get(row.command_id, ())
            if (show == SHOW_CONFLICTS and not clash_ids) or (show == SHOW_CHANGED and not row.changed):
                continue
            where = _translate(CONTEXT_LABELS.get(row.context, row.context))
            label = labels[row.command_id]
            keys = ", ".join(row.keys)
            others = ", ".join(labels.get(other, other) for other in clash_ids)
            haystack = " ".join((where, label, row.label, row.command_id, keys, others)).casefold()
            if words and not all(word in haystack for word in words):
                continue
            parent = self.table.invisibleRootItem()
            if grouped:
                parent = groups.get(row.context)
                if parent is None:
                    parent = groups[row.context] = self._group_item(row.context, where, area_order)
            texts = (label, keys, where, others)
            item = _SortItem(parent, list(texts))
            for column, text in enumerate(texts):
                item.setData(column, _ID_ROLE, row.command_id)
                item.setData(column, _SORT_ROLE, (text.casefold(), label.casefold()))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            if row.changed:
                font = item.font(COLUMN_KEYS)
                font.setBold(True)
                item.setFont(COLUMN_KEYS, font)
                default = ", ".join(row.defaults) or _translate("None")
                item.setToolTip(COLUMN_KEYS, _translate("Default: {keys}").replace("{keys}", default))
            if clash_ids:
                for column in range(self.table.columnCount()):
                    item.setForeground(column, QBrush(warning_text))
                    item.setBackground(column, QBrush(warning_back))
                item.setIcon(COLUMN_CONFLICTS, warning_icon)
                item.setToolTip(COLUMN_CONFLICTS, _translate("Also used by: {names}").replace("{names}", others))
            if row.command_id == selected:
                reselect = item
        for context, group in groups.items():
            group.setText(0, f"{group.text(0)} ({group.childCount()})")
            group.setExpanded(context not in self._collapsed)
        self.table.setSortingEnabled(True)
        if reselect is not None:
            self.table.setCurrentItem(reselect)
            self.table.scrollToItem(reselect)
        total = sum(1 for row in rows if row.command_id in clashes)
        self.conflict_count.setText(_translate("Conflicts: {count}").replace("{count}", str(total)) if total else "")
        self.reset_all_button.setEnabled(any(row.changed for row in rows))
        self._sync_buttons()

    def _group_item(self, context: str, where: str, order: dict[str, int]) -> QTreeWidgetItem:
        group = _SortItem(self.table.invisibleRootItem(), [where])
        group.setData(0, _ID_ROLE, context)
        for column in range(self.table.columnCount()):
            # Areas keep their order whichever column sorts the commands inside them.
            group.setData(column, _SORT_ROLE, (order.get(context, len(order)), where.casefold()))
        group.setFlags(Qt.ItemFlag.ItemIsEnabled)
        group.setFirstColumnSpanned(True)
        font = group.font(0)
        font.setBold(True)
        group.setFont(0, font)
        return group

    def _command_items(self) -> list[QTreeWidgetItem]:
        found: list[QTreeWidgetItem] = []

        def walk(parent: QTreeWidgetItem) -> None:
            for index in range(parent.childCount()):
                child = parent.child(index)
                if child.flags() & Qt.ItemFlag.ItemIsSelectable:
                    found.append(child)
                else:
                    walk(child)

        walk(self.table.invisibleRootItem())
        return found

    def command_ids(self) -> list[str]:
        """The commands the table lists now, in the order it shows them."""

        return [str(item.data(0, _ID_ROLE)) for item in self._command_items()]

    def item_for(self, command_id: str) -> QTreeWidgetItem | None:
        return next((item for item in self._command_items() if item.data(0, _ID_ROLE) == command_id), None)

    def select_command(self, command_id: str) -> bool:
        item = self.item_for(command_id)
        if item is not None:
            self.table.setCurrentItem(item)
        return item is not None

    def selected_command_id(self) -> str:
        items = self.table.selectedItems()
        if not items or not (items[0].flags() & Qt.ItemFlag.ItemIsSelectable):
            return ""
        return str(items[0].data(0, _ID_ROLE) or "")

    def _sync_buttons(self) -> None:
        chosen = bool(self.selected_command_id())
        for button in (self.change_button, self.unbind_button, self.reset_button):
            button.setEnabled(chosen)

    def show_message(self, text: str) -> None:
        """A line under the table: what a recorded key did, or how to record one."""

        self.message.setText(text or _translate(EDIT_HINT))

    # ----- editing -------------------------------------------------------------
    def _double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        row = self.row_for(str(item.data(0, _ID_ROLE) or ""))
        if row is None or not (item.flags() & Qt.ItemFlag.ItemIsSelectable):
            return
        if column != COLUMN_KEYS or row.takes_modifier:
            self.change_selected()  # the Keys cell records in place; the rest of the row opens Change...

    def _context_menu(self, position) -> None:
        item = self.table.itemAt(position)
        row = self.row_for(self.selected_command_id())
        if item is None or row is None:
            return
        menu = QMenu(self)
        record = menu.addAction(_translate("Record a new key"))
        record.triggered.connect(lambda: self.table.editItem(item, COLUMN_KEYS))
        record.setEnabled(not row.takes_modifier)
        menu.addAction(_translate("Change..."), self.change_selected)
        menu.addAction(_translate("Unbind"), lambda: self._save_selected([]))
        menu.addAction(_translate("Reset to default"), lambda: self._save_selected(None))
        menu.exec(self.table.viewport().mapToGlobal(position))

    def record_key(self, command_id: str, key: str) -> bool:
        """Save ``key`` as the command's first key, keeping its second; a refusal is named, not saved."""

        row = self.row_for(command_id)
        if row is None or not key:
            return False
        recorded = [key, *(other for other in row.keys[1:] if other != key)]
        keys, refusal = self.key_rules(row)["check"](recorded)
        if refusal:
            self.show_message(_translate(refusal))
            return False
        clash = self.conflict_text(row, list(keys))
        self._save(command_id, list(keys))
        self.select_command(command_id)
        self.show_message(clash)
        return True

    def change_selected(self) -> None:
        command_id = self.selected_command_id()
        row = next((r for r in self.rows() if r.command_id == command_id), None)
        if row is None:
            return
        dialog = self.key_dialog(row)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save(command_id, dialog.keys())

    def key_rules(self, row) -> dict:
        """How ``row``'s keys are checked and shown; the Mesh Editor helper's commands follow its grammar."""

        if row.helper:
            from cdmw.ui.commands.helper_keys import check_helper_keys, palette_chords, qt_key_text

            palette_chords(self.settings)  # the palette's keys as this keymap has them, editor running or not

            return dict(check=lambda keys: check_helper_keys(keys, takes_modifier=row.takes_modifier),
                        shown=qt_key_text, keep_numpad=True)
        if row.command_id == PALETTE_COMMAND:
            return dict(check=self._palette_key_check)
        return dict(check=lambda keys: (list(keys), ""))

    def key_dialog(self, row) -> KeyDialog:
        """The dialog that changes ``row``'s keys (a first and a second)."""

        return KeyDialog(row.label, row.keys, self, conflict_for=lambda keys: self.conflict_text(row, keys),
                         **self.key_rules(row))

    def _palette_key_check(self, keys: list[str]) -> tuple[list[str], str]:
        """The palette may not take a key a Mesh Editor command uses (review of 59fd00c5e).

        The editor hands the palette's keys to CDMW before its own commands see
        them, so that command would stop working while the editor is open.
        """

        from cdmw.ui.commands.helper_keys import helper_binding

        for key in keys:
            chord = helper_binding(key).text
            if not chord:
                continue
            for other in self.rows():
                if other.helper and any(helper_binding(used).text == chord for used in other.keys):
                    name = display_label(_translate(other.label))
                    return [], _translate("The Mesh Editor command {name} uses this key.").replace("{name}", name)
        return list(keys), ""

    def conflict_text(self, row, keys: list[str]) -> str:
        """Which commands the proposed keys would clash with, if any."""

        from dataclasses import replace

        rows = [replace(r, keys=tuple(keys)) if r.command_id == row.command_id else r for r in self.rows()]
        others = conflicts(rows).get(row.command_id, ())
        if not others:
            return ""
        names = ", ".join(display_label(_translate(r.label)) for r in rows if r.command_id in others)
        return _translate("Also used by: {names}").replace("{names}", names)

    def _save_selected(self, keys: list[str] | None) -> None:
        command_id = self.selected_command_id()
        if command_id:
            self._save(command_id, keys)

    def _save(self, command_id: str, keys: list[str] | None) -> None:
        save_keys(self.registry, self.settings, command_id, keys)

    def confirm_reset_all(self) -> bool:
        answer = QMessageBox.question(
            self, _translate("Restore all defaults"), _translate(RESTORE_ALL_QUESTION),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def _reset_all(self) -> None:
        if self.confirm_reset_all():
            reset_all(self.registry, self.settings)
            self.show_message("")
