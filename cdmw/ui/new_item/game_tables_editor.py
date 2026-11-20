"""Pick a game table, a row and a whitelisted value, and collect the changes for a mod.

The widget only edits a list of `TableFieldEdit`s; loading a table and writing a mod
belong to its host (Create New Item's controller, or Archive Browser's dialog), which run
that work off the UI thread and hand the loaded `TableEditIndex` back through `set_index`.
Standard widgets only, so Create New Item's Rust interface projects it unchanged.
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QGroupBox, QProgressBar, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from cdmw.core.static_table_records import TableFieldEdit
from cdmw.services.active_ui_translation import translate_active_ui_text

ROW_LIMIT = 500
_KEY_ROLE = Qt.UserRole


#: Speed Tuning's tables (experimental); offered in Edit Game Table Values, not in Create New Item.
SPEED_TABLES = ("aimovespeedinfo", "gimmickinfo")


def table_names(*, include_speed: bool = True) -> dict[str, str]:
    names = {
        "characterinfo": translate_active_ui_text("Characters and NPCs"),
        "dropsetinfo": translate_active_ui_text("Drop sets (loot)"),
        "gameplayvariableinfo": translate_active_ui_text("Gameplay switches"),
        "inventory": translate_active_ui_text("Inventories and bags"),
        "mercenaryinfo": translate_active_ui_text("Mercenaries and pets"),
        "skill": translate_active_ui_text("Skills"),
        "wantedinfo": translate_active_ui_text("Bounties"),
        "aimovespeedinfo": translate_active_ui_text("AI movement speeds (experimental)"),
        "gimmickinfo": translate_active_ui_text("Gimmicks (experimental)"),
    }
    if not include_speed:
        for kind in SPEED_TABLES:
            names.pop(kind, None)
    return names


def _field_names() -> dict[str, str]:
    return {
        "_defaultSlotCount": translate_active_ui_text("Starting slots"),
        "_maxSlotCount": translate_active_ui_text("Maximum slots"),
        "_maxLevel": translate_active_ui_text("Maximum level"),
        "_cooltime": translate_active_ui_text("Cooldown (raw)"),
        "_allowSkillWithLowResource": translate_active_ui_text("Usable with low resource"),
        "_increasePrice": translate_active_ui_text("Bounty increase"),
        "_defaultLimitHireCount": translate_active_ui_text("Hire limit"),
        "_maxLimitHireCount": translate_active_ui_text("Hire limit ceiling"),
        "_defaultLimitSummonCount": translate_active_ui_text("Summon limit"),
        "_characterScale": translate_active_ui_text("Model scale"),
        "_callMercenaryCoolTime": translate_active_ui_text("Companion call cooldown (raw)"),
        "_initialVariable": translate_active_ui_text("Starts switched on"),
        "_percent": translate_active_ui_text("drop chance"),
        "_minValue": translate_active_ui_text("minimum quantity"),
        "_maxValue": translate_active_ui_text("maximum quantity"),
        "_deadDropPercent": translate_active_ui_text("drop chance on death"),
        "_throwDropPercent": translate_active_ui_text("drop chance when thrown"),
        "_experience": translate_active_ui_text("experience"),
        "_pushObjectSpeedRate": translate_active_ui_text("Pushed object speed rate"),
        "_targetMoveSpeed": translate_active_ui_text("move speed"),
        "_minMoveSpeed": translate_active_ui_text("minimum move speed"),
        "_maxRotationSpeed": translate_active_ui_text("turn speed"),
    }


def _group_names() -> dict[str, str]:
    return {
        "DropInfoData": translate_active_ui_text("Drop"),
        "CharacterEquipmentData": translate_active_ui_text("Equipment"),
        "CharacterLevelData": translate_active_ui_text("Level"),
        "AIMoveSpeedData": translate_active_ui_text("Speed entry"),
    }


def value_label(target, owner: str = "") -> str:
    fields = _field_names()
    if isinstance(target, str):
        return fields.get(target, target)
    position = " ".join(str(part + 1) for part in target if isinstance(part, int))
    group = _group_names().get(owner, owner)
    return f"{group} {position}: {fields.get(target[-1], target[-1])}"


def parse_value(rule, text: str):
    """The stored value for `text`, or ValueError naming the allowed range."""

    text = str(text).strip().replace(" ", "").replace(",", "") if rule.kind != "float32" else str(text).strip()
    if rule.kind == "float32":
        value = float(text.replace(",", "."))
        if not math.isfinite(value) or not rule.minimum <= value <= rule.maximum:
            raise ValueError(f"{rule.minimum:g} to {rule.maximum:g}")
        return value
    if rule.kind == "bool":
        lowered = text.lower()
        if lowered in ("1", "yes", "true", "on"):
            return 1
        if lowered in ("0", "no", "false", "off"):
            return 0
        raise ValueError("0 or 1")
    if not text.lstrip("-").isdigit():
        raise ValueError(f"{int(rule.minimum):,} to {int(rule.maximum):,}")
    value = int(text)
    if not rule.minimum <= value <= rule.maximum:
        raise ValueError(f"{int(rule.minimum):,} to {int(rule.maximum):,}")
    return value


class GameTablesEditor(QWidget):
    """Collects game table edits. `load_requested(table)` asks the host to load a table."""

    load_requested = Signal(str)
    edits_changed = Signal(object)

    def __init__(self, parent=None, *, include_speed: bool = False, side_by_side: bool = False):
        super().__init__(parent)
        self._include_speed = include_speed
        self._index = None
        self._shown_key = None
        self._edits: dict[tuple, TableFieldEdit] = {}
        self._labels: dict[tuple, str] = {}
        layout = QVBoxLayout(self)
        if side_by_side:
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)
        intro = QLabel("Change values in existing rows of the game's tables. Their effect in game has not "
                       "been verified.")
        intro.setObjectName("HintLabel")
        intro.setWordWrap(True)
        intro.setToolTip("Only values whose storage is proven on every shipped row are offered.")
        layout.addWidget(intro)
        self.intro = intro

        top = QHBoxLayout()
        self.table_label = QLabel("Table:")
        top.addWidget(self.table_label)
        self.table = QComboBox()
        for kind, label in sorted(table_names(include_speed=include_speed).items(), key=lambda item: item[1].casefold()):
            self.table.addItem(label, kind)
        top.addWidget(self.table, 1)
        self.load = QPushButton("Load table")
        self.load.setToolTip("Read the selected table from the game's archives.")
        self.load.clicked.connect(self._request_load)
        top.addWidget(self.load)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter rows by name or key")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill_rows)
        top.addWidget(self.search, 1)
        layout.addLayout(top)
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setTextVisible(False)
        self.busy.setMaximumHeight(6)
        self.busy.setVisible(False)
        layout.addWidget(self.busy)

        self.rows = QTableWidget(0, 3)
        self.rows.setHorizontalHeaderLabels(["Key", "Name", "Copy"])
        self._configure(self.rows)
        self.rows.horizontalHeader().setStretchLastSection(False)
        self.rows.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.rows.itemSelectionChanged.connect(self._fill_values)
        self.values = QTableWidget(0, 4)
        self.values.setHorizontalHeaderLabels(["Value", "Current", "In this mod", "About"])
        self._configure(self.values)
        self.values.itemSelectionChanged.connect(self._value_selected)

        edit = QHBoxLayout()
        edit.addWidget(QLabel("New value:"))
        self.value = QLineEdit()
        self.value.setPlaceholderText("Select a value above")
        self.value.returnPressed.connect(self._set_value)
        edit.addWidget(self.value, 1)
        self.set = QPushButton("Set value")
        self.set.clicked.connect(self._set_value)
        edit.addWidget(self.set)
        self.restore = QPushButton("Restore value")
        self.restore.setToolTip("Remove this mod's change to the selected value.")
        self.restore.clicked.connect(self._restore_value)
        edit.addWidget(self.restore)

        pending_title = QLabel("Changes in this mod:")
        self.pending = QTableWidget(0, 4)
        self.pending.setHorizontalHeaderLabels(["Table", "Row", "Value", "New value"])
        self._configure(self.pending)
        buttons = QHBoxLayout()
        self.remove = QPushButton("Remove selected change")
        self.remove.clicked.connect(self._remove_selected)
        buttons.addWidget(self.remove)
        buttons.addStretch(1)
        self.pending_layout = None
        if side_by_side:
            # Rows on the left, the selected row's values and this mod's changes on the right,
            # each in its own frame, so a wide tab shows all three without scrolling.
            for table in (self.rows, self.values, self.pending):
                table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                table.verticalHeader().setDefaultSectionSize(28)
            splitter = QSplitter(Qt.Orientation.Horizontal)
            splitter.setChildrenCollapsible(False)
            splitter.setHandleWidth(8)
            splitter.setStyleSheet("QSplitter::handle { background: transparent; }")
            # The app draws group boxes without a frame: these margins put each box's contents
            # straight under its heading, as on the other pages of Speed & Prefabs.
            box_margins = (6, 6, 6, 4)
            rows_box = QGroupBox("Rows")
            rows_layout = QVBoxLayout(rows_box)
            rows_layout.setContentsMargins(*box_margins)
            rows_layout.setSpacing(8)
            top.removeWidget(self.search)
            rows_layout.addWidget(self.search)
            rows_layout.addWidget(self.rows, 1)
            self.message = QLabel()
            self.message.setObjectName("HintLabel")
            self.message.setWordWrap(True)
            rows_layout.addWidget(self.message)
            splitter.addWidget(rows_box)
            right = QWidget()
            column = QVBoxLayout(right)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(8)
            values_box = QGroupBox("Values of the selected row")
            values_layout = QVBoxLayout(values_box)
            values_layout.setContentsMargins(*box_margins)
            values_layout.setSpacing(8)
            values_layout.addWidget(self.values, 1)
            values_layout.addLayout(edit)
            column.addWidget(values_box, 3)
            pending_box = QGroupBox("Changes in this mod")
            self.pending_layout = QVBoxLayout(pending_box)
            self.pending_layout.setContentsMargins(*box_margins)
            self.pending_layout.setSpacing(8)
            pending_title.setVisible(False)
            self.pending_layout.addWidget(self.pending, 1)
            self.pending_layout.addLayout(buttons)
            column.addWidget(pending_box, 2)
            splitter.addWidget(right)
            splitter.setStretchFactor(0, 2)
            splitter.setStretchFactor(1, 3)
            layout.addWidget(splitter, 1)
        else:
            # Stacked, each with its own stretch: Create New Item's Rust view gives a table room
            # only as a stretched child of a column; side by side in a row both collapse to a line.
            layout.addWidget(self.rows, 3)
            layout.addWidget(self.values, 2)
            layout.addLayout(edit)
            layout.addWidget(pending_title)
            layout.addWidget(self.pending, 2)
            layout.addLayout(buttons)
            self.message = QLabel()
            self.message.setWordWrap(True)
            layout.addWidget(self.message)
        self._update_controls()

    @staticmethod
    def _configure(table: QTableWidget) -> None:
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)

    # --- host interface -------------------------------------------------------------

    def set_table_choice_visible(self, visible: bool) -> None:
        """Hide the table list and Load button when the host picks the table (Speed & Prefabs)."""

        for widget in (self.table_label, self.table, self.load):
            widget.setVisible(visible)

    def current_table(self) -> str:
        return str(self.table.currentData() or "")

    def loaded_table(self) -> str:
        return self._index.table if self._index is not None else ""

    def set_loading(self, loading: bool) -> None:
        self.load.setEnabled(not loading)
        self.busy.setVisible(loading)
        if loading:
            self.message.setText("Reading the table from the game's archives…")

    def set_index(self, index) -> None:
        """Show a loaded `TableEditIndex`."""

        self._index = index
        position = self.table.findData(index.table)
        if position >= 0 and position != self.table.currentIndex():
            self.table.blockSignals(True)
            self.table.setCurrentIndex(position)
            self.table.blockSignals(False)
        locked = sum(1 for row in index.rows if not row.editable)
        text = f"{len(index.rows):,} rows loaded."
        if locked:
            text += f" {locked:,} exist only in the DLC copy, which a DMM mod cannot change."
        if index.refused:
            text += f" {index.refused:,} rows use a layout this build cannot read and are not listed."
        self.message.setText(text)
        self.load.setEnabled(True)
        self.busy.setVisible(False)
        self._fill_rows()

    def show_error(self, message: str) -> None:
        self.load.setEnabled(True)
        self.busy.setVisible(False)
        self.message.setText(str(message))

    def refresh_loaded(self) -> None:
        """Show the loaded table's own state again, after a read that was for another table."""

        if self._index is not None:
            self.set_index(self._index)

    def edits(self) -> tuple[TableFieldEdit, ...]:
        return tuple(self._edits[key] for key in sorted(self._edits, key=lambda k: (k[0], k[1], str(k[2]))))

    def set_edits(self, edits) -> None:
        self._edits = {(edit.table, edit.key, edit.target): edit for edit in edits or ()}
        self._fill_pending()
        self._fill_values()

    def clear_index(self) -> None:
        self._index = None
        self.rows.setRowCount(0)
        self.values.setRowCount(0)
        self._update_controls()

    # --- internals ------------------------------------------------------------------

    def _request_load(self) -> None:
        if self.current_table():
            self.set_loading(True)
            self.load_requested.emit(self.current_table())

    def _fill_rows(self) -> None:
        self.rows.setRowCount(0)
        if self._index is None:
            return
        needle = self.search.text().strip().casefold()
        matches = [row for row in self._index.rows
                   if not needle or needle in row.name.casefold() or needle == str(row.key)]
        shown = matches[:ROW_LIMIT]
        self.rows.setRowCount(len(shown))
        for position, row in enumerate(shown):
            key = QTableWidgetItem(str(row.key))
            key.setData(_KEY_ROLE, row.key)
            self.rows.setItem(position, 0, key)
            self.rows.setItem(position, 1, QTableWidgetItem(row.name))
            copy = QTableWidgetItem("DLC" if "." in row.layer else "Base")
            if not row.editable:
                copy.setToolTip("This row exists only in the DLC copy; a DMM mod cannot change it.")
            self.rows.setItem(position, 2, copy)
        if len(matches) > len(shown):
            self.message.setText(f"Showing the first {len(shown):,} of {len(matches):,} matching rows; "
                                 "type more of a name to narrow them.")
        self._fill_values()

    def _selected_row(self):
        if self._index is None:
            return None
        items = self.rows.selectedItems()
        if not items:
            return None
        key = self.rows.item(items[0].row(), 0).data(_KEY_ROLE)
        return next((row for row in self._index.rows if row.key == key), None)

    def _fill_values(self) -> None:
        row = self._selected_row()
        kept = None
        if row is not None and row.key == self._shown_key:
            items = self.values.selectedItems()
            kept = self.values.item(items[0].row(), 0).data(_KEY_ROLE) if items else None
        self._shown_key = None if row is None else row.key
        self.values.blockSignals(True)
        self.values.setRowCount(0)
        if row is None:
            self.values.blockSignals(False)
            self._update_controls()
            return
        self.values.setRowCount(len(row.values))
        for position, value in enumerate(row.values):
            owner = getattr(value, "owner", "") or ""
            label = value_label(value.target, owner) if owner or isinstance(value.target, str) else value.label
            name = QTableWidgetItem(label)
            name.setData(_KEY_ROLE, position)
            self.values.setItem(position, 0, name)
            self.values.setItem(position, 1, QTableWidgetItem(str(value.value)))
            pending = self._edits.get((self._index.table, row.key, value.target))
            self.values.setItem(position, 2, QTableWidgetItem("" if pending is None else str(pending.value)))
            self.values.setItem(position, 3, QTableWidgetItem(value.rule.note))
        if kept is not None:
            self.values.selectRow(kept)
        self.values.blockSignals(False)
        self._update_controls()

    def _selected_value(self):
        row = self._selected_row()
        items = self.values.selectedItems()
        if row is None or not items:
            return row, None
        return row, row.values[self.values.item(items[0].row(), 0).data(_KEY_ROLE)]

    def _value_selected(self) -> None:
        row, value = self._selected_value()
        if value is not None:
            pending = self._edits.get((self._index.table, row.key, value.target))
            self.value.setText(str(pending.value if pending is not None else value.value))
        self._update_controls()

    def _set_value(self) -> None:
        row, value = self._selected_value()
        if value is None:
            return
        if not row.editable:
            self.message.setText("This row exists only in the DLC copy; a DMM mod cannot change it.")
            return
        try:
            stored = parse_value(value.rule, self.value.text())
        except ValueError as exc:
            self.message.setText(f"Enter a value from {exc}.")
            return
        key = (self._index.table, row.key, value.target)
        if stored == value.value:
            self._edits.pop(key, None)
        else:
            self._edits[key] = TableFieldEdit(self._index.table, row.key, value.target, stored)
            self._labels[key] = f"{row.name} ({row.key})"
        self.message.setText("")
        self._changed()

    def _restore_value(self) -> None:
        row, value = self._selected_value()
        if value is not None:
            self._edits.pop((self._index.table, row.key, value.target), None)
            self.value.setText(str(value.value))
            self._changed()

    def _remove_selected(self) -> None:
        items = self.pending.selectedItems()
        if items:
            key = self.pending.item(items[0].row(), 0).data(_KEY_ROLE)
            self._edits.pop(key, None)
            self._changed()

    def _changed(self) -> None:
        self._fill_pending()
        self._fill_values()
        self.edits_changed.emit(self.edits())

    def _fill_pending(self) -> None:
        names = table_names()
        edits = self.edits()
        self.pending.setRowCount(len(edits))
        for position, edit in enumerate(edits):
            key = (edit.table, edit.key, edit.target)
            table = QTableWidgetItem(names.get(edit.table, edit.table))
            table.setData(_KEY_ROLE, key)
            self.pending.setItem(position, 0, table)
            self.pending.setItem(position, 1, QTableWidgetItem(self._labels.get(key, str(edit.key))))
            self.pending.setItem(position, 2, QTableWidgetItem(value_label(edit.target, self._owner(edit))))
            self.pending.setItem(position, 3, QTableWidgetItem(str(edit.value)))
        self._update_controls()

    def _owner(self, edit) -> str:
        if isinstance(edit.target, str) or self._index is None or self._index.table != edit.table:
            return ""
        row = next((row for row in self._index.rows if row.key == edit.key), None)
        value = next((value for value in (row.values if row else ()) if value.target == edit.target), None)
        return getattr(value, "owner", "") if value is not None else ""

    def _update_controls(self) -> None:
        row, value = self._selected_value()
        usable = value is not None and row is not None and row.editable
        self.value.setEnabled(usable)
        self.set.setEnabled(usable)
        self.restore.setEnabled(usable and (self._index.table, row.key, value.target) in self._edits)
        self.remove.setEnabled(bool(self._edits))


__all__ = ["GameTablesEditor", "parse_value", "table_names", "value_label"]
