"""Sound bank editor: change stored values, add or remove properties and variations.

The dialog only collects a plan; reading the bank and writing the loose mod run
as utility tasks in `patch_actions`.
"""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QListWidget, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from cdmw.services.archive_workflow_service import (
    HircEdit,
    HircPropertyChange,
    SoundBankEditPlan,
    VariationRequest,
)
from cdmw.ui.display_scaling import fit_window_to_screen

_COLUMNS = ("Object", "Type", "Value", "Stored", "New", "Unit")
_RANDOM_SEQUENCE = 5


def _format(value: float | int, integer: bool) -> str:
    return str(int(value)) if integer else f"{float(value):g}"


class SoundBankEditorDialog(QDialog):
    def __init__(self, parent, title: str, model) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit Sound Bank: {title}")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.resize(900, 640)
        self.model = model
        self.pending_properties: list[HircPropertyChange] = []
        self.removed_variations: list[tuple[int, int]] = []
        self.added_variations: list[VariationRequest] = []

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Edit the values this bank stores, add or remove properties, and add or remove sounds in random "
            "containers. The result is written as a DMM loose mod; the installed game is not changed. "
            "On a bus, Volume affects only sounds routed straight to it; BusVolume is the bus's own volume. "
            "Added sounds have not been confirmed in game yet."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        for note in model.notes:
            label = QLabel(note)
            label.setWordWrap(True)
            layout.addWidget(label)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter by object id or value name")
        # The largest shipped bank lists 3,242 values; filter once typing pauses.
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(200)
        self._filter_timer.timeout.connect(lambda: self._apply_filter(self.filter_edit.text()))
        self.filter_edit.textChanged.connect(lambda _text: self._filter_timer.start())
        self._haystacks = [f"{item.object_id} {item.target}".lower() for item in model.rows]
        layout.addWidget(self.filter_edit)

        self.table = QTableWidget(len(model.rows), len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(list(_COLUMNS))
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setResizeContentsPrecision(200)
        header.setStretchLastSection(True)
        self.table.setUpdatesEnabled(False)
        for row, item in enumerate(model.rows):
            cells = (str(item.object_id), item.kind_name, item.target, _format(item.value, item.integer), "", item.unit)
            for column, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if column != 4:
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, cell)
        self.table.resizeColumnsToContents()
        self.table.setUpdatesEnabled(True)
        layout.addWidget(self.table, 1)

        add_row = QHBoxLayout()
        self.object_combo = QComboBox()
        for obj in model.objects:
            kind = "random container" if obj.kind == _RANDOM_SEQUENCE else f"type {obj.kind}"
            self.object_combo.addItem(f"{obj.object_id} ({kind})", obj.object_id)
        self.object_combo.currentIndexChanged.connect(self._refresh_addable)
        self.property_combo = QComboBox()
        self.value_edit = QLineEdit()
        self.value_edit.setPlaceholderText("value, or min, max for a range")
        add_button = QPushButton("Add Property")
        add_button.clicked.connect(self._add_property)
        add_row.addWidget(self.object_combo, 2)
        add_row.addWidget(self.property_combo, 2)
        add_row.addWidget(self.value_edit, 2)
        add_row.addWidget(add_button)
        layout.addLayout(add_row)

        action_row = QHBoxLayout()
        remove_button = QPushButton("Remove Selected Property")
        remove_button.clicked.connect(self._remove_selected_property)
        self.add_variation_button = QPushButton("Add Sound to Container...")
        self.add_variation_button.clicked.connect(self._add_variation)
        self.remove_variation_button = QPushButton("Remove Sound from Container...")
        self.remove_variation_button.clicked.connect(self._remove_variation)
        action_row.addWidget(remove_button)
        action_row.addStretch(1)
        action_row.addWidget(self.add_variation_button)
        action_row.addWidget(self.remove_variation_button)
        layout.addLayout(action_row)

        layout.addWidget(QLabel("Pending structural changes"))
        self.pending_list = QListWidget()
        self.pending_list.setMaximumHeight(120)
        layout.addWidget(self.pending_list)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.write_button = QPushButton("Write Loose Mod...")
        self.write_button.setDefault(True)
        self.write_button.clicked.connect(self._accept_if_valid)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(self.write_button)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        self._refresh_addable()

    def showEvent(self, event):
        super().showEvent(event)
        fit_window_to_screen(self)

    def _current_object(self):
        object_id = self.object_combo.currentData()
        return next((obj for obj in self.model.objects if obj.object_id == object_id), None)

    def _refresh_addable(self, *_args) -> None:
        obj = self._current_object()
        self.property_combo.clear()
        if obj is not None:
            for name in obj.addable_properties:
                self.property_combo.addItem(name, f"property:{name}")
            for name in obj.addable_ranges:
                self.property_combo.addItem(f"{name} range", f"range:{name}")
        is_container = obj is not None and obj.kind == _RANDOM_SEQUENCE and bool(obj.children)
        self.add_variation_button.setEnabled(is_container)
        self.remove_variation_button.setEnabled(is_container and len(obj.children) > 1)

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        self.table.setUpdatesEnabled(False)
        for row, haystack in enumerate(self._haystacks):
            hidden = bool(needle) and needle not in haystack
            if self.table.isRowHidden(row) != hidden:
                self.table.setRowHidden(row, hidden)
        self.table.setUpdatesEnabled(True)

    def _pending(self, text: str) -> None:
        self.pending_list.addItem(text)

    def _add_property(self) -> None:
        obj = self._current_object()
        target = self.property_combo.currentData()
        if obj is None or not target:
            return
        try:
            parts = [float(part) for part in self.value_edit.text().replace(";", ",").split(",") if part.strip()]
        except ValueError:
            parts = []
        if target.startswith("range:"):
            if len(parts) != 2 or parts[0] > parts[1]:
                QMessageBox.warning(self, "Add Property", "A range needs two numbers, minimum then maximum.")
                return
            value: object = (parts[0], parts[1])
        elif len(parts) == 1 and math.isfinite(parts[0]):
            value = int(parts[0]) if parts[0].is_integer() else parts[0]
        else:
            QMessageBox.warning(self, "Add Property", "Enter one number for the property.")
            return
        self.pending_properties.append(HircPropertyChange(obj.object_id, target, value))
        self._pending(f"object {obj.object_id}: add {target} = {value}")

    def _remove_selected_property(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        for row in rows:
            target = self.table.item(row, 2).text()
            if not target.startswith(("property:", "range:")):
                continue
            if target.startswith("range:"):
                target = target.rsplit(":", 1)[0]
            object_id = int(self.table.item(row, 0).text())
            change = HircPropertyChange(object_id, target, None)
            if change not in self.pending_properties:
                self.pending_properties.append(change)
                self._pending(f"object {object_id}: remove {target}")

    def _add_variation(self) -> None:
        obj = self._current_object()
        if obj is None or not obj.children:
            return
        labels = [str(child) for child in obj.children]
        template, accepted = QInputDialog.getItem(
            self, "Add Sound to Container", "Copy the settings of sound:", labels, 0, False
        )
        if not accepted:
            return
        path, _selected = QFileDialog.getOpenFileName(
            self, "Select Audio for the New Sound", "", "Audio Files (*.wav *.ogg *.mp3 *.wem)"
        )
        if not path:
            return
        self.added_variations.append(VariationRequest(obj.object_id, int(template), Path(path)))
        self._pending(f"container {obj.object_id}: add {Path(path).name} (settings of sound {template})")

    def _remove_variation(self) -> None:
        obj = self._current_object()
        if obj is None or len(obj.children) < 2:
            return
        labels = [str(child) for child in obj.children]
        sound, accepted = QInputDialog.getItem(self, "Remove Sound from Container", "Sound to remove:", labels, 0, False)
        if accepted and (obj.object_id, int(sound)) not in self.removed_variations:
            self.removed_variations.append((obj.object_id, int(sound)))
            self._pending(f"container {obj.object_id}: remove sound {sound}")

    def value_edits(self) -> list[HircEdit]:
        edits = []
        for row, item in enumerate(self.model.rows):
            text = self.table.item(row, 4).text().strip()
            if not text:
                continue
            number = float(text)
            if item.integer and not number.is_integer():
                raise ValueError(f"{item.target} of object {item.object_id} takes a whole number.")
            edits.append(HircEdit(item.object_id, item.target, int(number) if item.integer else number))
        return edits

    def plan(self) -> SoundBankEditPlan:
        return SoundBankEditPlan(
            tuple(self.value_edits()),
            tuple(self.pending_properties),
            tuple(self.removed_variations),
            tuple(self.added_variations),
        )

    def _accept_if_valid(self) -> None:
        try:
            plan = self.plan()
        except ValueError as error:
            QMessageBox.warning(self, "Edit Sound Bank", f"A new value is not a number: {error}")
            return
        if plan.empty:
            QMessageBox.information(self, "Edit Sound Bank", "Nothing has been changed yet.")
            return
        self.accept()


__all__ = ["SoundBankEditorDialog"]
