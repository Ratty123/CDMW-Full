"""Structured parameter browser and typed value inspector for PAC XML."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, Sequence

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)



class PacXmlParameterRow(Protocol):
    row_id: str
    kind: str
    group_label: str
    parameter_name: str
    value: str
    detail: str
    parameter_type: str
    shader_name: str
    item_id: str
    index: str
    source_order: int
    source_line: int
    explicit: bool
    editable: bool
    risk: str


def byte4_channels(raw_value: object) -> tuple[int, int, int, int]:
    value = int(str(raw_value or "0").strip(), 0)
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("Byte4 must fit in an unsigned 32-bit value.")
    return tuple((value >> (index * 8)) & 0xFF for index in range(4))  # type: ignore[return-value]


def byte4_raw_value(channels: Sequence[int]) -> int:
    if len(channels) != 4:
        raise ValueError("Byte4 requires four channels.")
    value = 0
    for index, channel in enumerate(channels):
        parsed = int(channel)
        if not 0 <= parsed <= 255:
            raise ValueError("Each Byte4 channel must be between 0 and 255.")
        value |= parsed << (index * 8)
    return value


def friendly_parameter_name(exact_name: object) -> str:
    exact = str(exact_name or "").strip().lstrip("_")
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", exact).replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else str(exact_name or "")


@dataclass(slots=True)
class _HistoryEdit:
    row_id: str
    before: str
    after: str


class PacXmlTypedInspector(QWidget):
    """Raw field plus type-specific controls that remain synchronized."""

    def __init__(self, rows: Sequence[PacXmlParameterRow], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PacXmlTypedInspector")
        self._field: PacXmlParameterRow | None = None
        self._syncing = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        self.field_label = QLabel("Select a parameter to inspect its exact value.")
        self.field_label.setObjectName("PacXmlInspectorFieldLabel")
        self.field_label.setWordWrap(True)
        layout.addWidget(self.field_label)

        raw_row = QHBoxLayout()
        raw_row.addWidget(QLabel("Raw value"))
        self.raw_edit = QLineEdit()
        self.raw_edit.setObjectName("PacXmlRawValueEdit")
        self.raw_edit.setClearButtonEnabled(True)
        raw_row.addWidget(self.raw_edit, 1)
        self.absent_value_button = QPushButton("Set absent value")
        self.absent_value_button.setObjectName("PacXmlAbsentValueButton")
        self.absent_value_button.setVisible(False)
        raw_row.addWidget(self.absent_value_button)
        layout.addLayout(raw_row)

        self.guide_stack = QStackedWidget()
        self.guide_stack.setObjectName("PacXmlTypedGuideStack")
        self.empty_page = QLabel("The exact XML value remains available above.")
        self.empty_page.setWordWrap(True)
        self.guide_stack.addWidget(self.empty_page)

        self.vector_page = QWidget()
        vector_layout = QHBoxLayout(self.vector_page)
        vector_layout.setContentsMargins(0, 0, 0, 0)
        self.vector_spins: list[QDoubleSpinBox] = []
        for label in ("X", "Y", "Z"):
            vector_layout.addWidget(QLabel(label))
            spin = QDoubleSpinBox()
            spin.setDecimals(8)
            spin.setRange(-1.0e12, 1.0e12)
            spin.setSingleStep(0.01)
            spin.valueChanged.connect(self._vector_changed)
            self.vector_spins.append(spin)
            vector_layout.addWidget(spin, 1)
        self.guide_stack.addWidget(self.vector_page)

        self.bool_page = QWidget()
        bool_layout = QHBoxLayout(self.bool_page)
        bool_layout.setContentsMargins(0, 0, 0, 0)
        self.bool_checkbox = QCheckBox("Enabled")
        self.bool_checkbox.toggled.connect(self._bool_changed)
        bool_layout.addWidget(self.bool_checkbox)
        bool_layout.addStretch(1)
        self.guide_stack.addWidget(self.bool_page)

        self.integer_page = QWidget()
        integer_layout = QFormLayout(self.integer_page)
        integer_layout.setContentsMargins(0, 0, 0, 0)
        self.integer_spin = QDoubleSpinBox()
        self.integer_spin.setDecimals(0)
        self.integer_spin.setSingleStep(1)
        self.integer_spin.valueChanged.connect(self._integer_changed)
        integer_layout.addRow("Integer", self.integer_spin)
        self.guide_stack.addWidget(self.integer_page)

        self.byte4_page = QWidget()
        byte_layout = QGridLayout(self.byte4_page)
        byte_layout.setContentsMargins(0, 0, 0, 0)
        self.byte_spins: list[QSpinBox] = []
        for index in range(4):
            byte_layout.addWidget(QLabel(f"Byte {index}"), 0, index)
            spin = QSpinBox()
            spin.setRange(0, 255)
            spin.valueChanged.connect(self._byte4_changed)
            self.byte_spins.append(spin)
            byte_layout.addWidget(spin, 1, index)
        self.byte4_hint = QLabel("")
        self.byte4_hint.setObjectName("HintLabel")
        byte_layout.addWidget(self.byte4_hint, 2, 0, 1, 4)
        self.guide_stack.addWidget(self.byte4_page)

        self.bit_page = QWidget()
        bit_layout = QGridLayout(self.bit_page)
        bit_layout.setContentsMargins(0, 0, 0, 0)
        bit_layout.setHorizontalSpacing(5)
        bit_layout.setVerticalSpacing(2)
        self.bit_checkboxes: list[QCheckBox] = []
        for index in range(32):
            checkbox = QCheckBox(str(index))
            checkbox.setToolTip(f"Bit {index} (0x{1 << index:08X})")
            checkbox.toggled.connect(self._bits_changed)
            self.bit_checkboxes.append(checkbox)
            bit_layout.addWidget(checkbox, index // 8, index % 8)
        self.guide_stack.addWidget(self.bit_page)

        self.cloth_page = QWidget()
        cloth_layout = QFormLayout(self.cloth_page)
        cloth_layout.setContentsMargins(0, 0, 0, 0)
        self.cloth_combo = QComboBox()
        self.cloth_combo.setEditable(True)
        cloth_values = sorted({row.value for row in rows if row.kind == "clothcategory" and row.value})
        self.cloth_combo.addItems(cloth_values)
        self.cloth_combo.currentTextChanged.connect(self._cloth_changed)
        cloth_layout.addRow("Category", self.cloth_combo)
        self.guide_stack.addWidget(self.cloth_page)

        self.texture_page = QLabel("Archive virtual asset path. Texture references normally end in .dds.")
        self.texture_page.setWordWrap(True)
        self.guide_stack.addWidget(self.texture_page)

        layout.addWidget(self.guide_stack)
        self.validation_label = QLabel("")
        self.validation_label.setObjectName("PacXmlValidationLabel")
        self.validation_label.setWordWrap(True)
        layout.addWidget(self.validation_label)

        self.raw_edit.textChanged.connect(self._raw_changed)
        self.absent_value_button.clicked.connect(self._toggle_absent_value)
        self.set_field(None, "")

    def set_field(self, field: PacXmlParameterRow | None, current_value: str) -> None:
        self._field = field
        self._syncing = True
        raw_blocker = QSignalBlocker(self.raw_edit)
        try:
            self.raw_edit.setEnabled(field is not None)
            self.raw_edit.setReadOnly(field is None or not field.editable)
            self.raw_edit.setText(str(current_value or ""))
            self.raw_edit.setToolTip(str(current_value or ""))
            if field is None:
                self.field_label.setText("Select a parameter to inspect its exact value.")
                self.validation_label.clear()
                self.absent_value_button.setVisible(False)
                self.guide_stack.setCurrentWidget(self.empty_page)
                return
            self.field_label.setText(
                f"{friendly_parameter_name(field.parameter_name)}  |  Exact: {field.parameter_name}  |  "
                f"{field.parameter_type or field.kind}"
            )
            self.absent_value_button.setVisible(field.editable and not field.explicit)
            self.absent_value_button.setText("Set absent value" if not current_value else "Restore absent value")
            if not field.editable:
                self.validation_label.setText("Read only: this parameter type or value shape is not safely recognized.")
            elif field.risk:
                self.validation_label.setText(f"High-risk runtime value: {field.risk}")
            elif not field.explicit:
                self.validation_label.setText("This scalar has no value attribute. Use the explicit action to add or restore it.")
            else:
                self.validation_label.setText("Editable value. Structural XML fields remain locked.")
            self._show_kind(field.kind)
            self._sync_guides_from_raw(str(current_value or ""))
        finally:
            del raw_blocker
            self._syncing = False

    def _show_kind(self, kind: str) -> None:
        if kind in {"color", "float", "float2", "float3", "half2"}:
            self.guide_stack.setCurrentWidget(self.vector_page)
            count = 3 if kind in {"color", "float3"} else 2 if kind in {"float2", "half2"} else 1
            for index, spin in enumerate(self.vector_spins):
                spin.setVisible(index < count)
        elif kind == "bool":
            self.guide_stack.setCurrentWidget(self.bool_page)
        elif kind in {"int", "uint"}:
            self.integer_spin.setRange(-(2**31) if kind == "int" else 0, (2**31) - 1 if kind == "int" else (2**32) - 1)
            self.guide_stack.setCurrentWidget(self.integer_page)
        elif kind == "byte4":
            self.guide_stack.setCurrentWidget(self.byte4_page)
        elif kind == "bitflag32":
            self.guide_stack.setCurrentWidget(self.bit_page)
        elif kind == "clothcategory":
            self.guide_stack.setCurrentWidget(self.cloth_page)
        elif kind == "texture":
            self.guide_stack.setCurrentWidget(self.texture_page)
        else:
            self.guide_stack.setCurrentWidget(self.empty_page)

    def _raw_changed(self, value: str) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            self.raw_edit.setToolTip(value)
            self._sync_guides_from_raw(value)
            if self._field is not None and not self._field.explicit:
                self.absent_value_button.setText("Set absent value" if not value else "Restore absent value")
        finally:
            self._syncing = False

    def _sync_guides_from_raw(self, value: str) -> None:
        field = self._field
        if field is None:
            return
        if field.kind in {"color", "float", "float2", "float3", "half2"}:
            values = _color_tokens(value) if field.kind == "color" else _float_tokens(value)
            for index, spin in enumerate(self.vector_spins):
                if index < len(values):
                    spin.setValue(values[index])
        elif field.kind == "bool":
            self.bool_checkbox.setChecked(value.strip().casefold() in {"1", "true"})
        elif field.kind in {"int", "uint"}:
            try:
                self.integer_spin.setValue(int(value.strip(), 0))
            except ValueError:
                pass
        elif field.kind == "byte4":
            try:
                channels = byte4_channels(value)
                numeric = int(value.strip(), 0)
            except (TypeError, ValueError):
                self.byte4_hint.setText("Enter a decimal or 0x-prefixed 32-bit value.")
            else:
                for spin, channel in zip(self.byte_spins, channels):
                    spin.setValue(channel)
                self.byte4_hint.setText(f"Decimal {numeric}  |  Hex 0x{numeric:08X}")
        elif field.kind == "bitflag32":
            try:
                numeric = int(value.strip(), 0)
            except ValueError:
                return
            if not 0 <= numeric <= 0xFFFFFFFF:
                return
            for index, checkbox in enumerate(self.bit_checkboxes):
                checkbox.setChecked(bool(numeric & (1 << index)))
        elif field.kind == "clothcategory":
            self.cloth_combo.setCurrentText(value)

    def _vector_changed(self, _value: float) -> None:
        if self._syncing or self._field is None:
            return
        count = 3 if self._field.kind in {"color", "float3"} else 2 if self._field.kind in {"float2", "half2"} else 1
        separator = ", " if "," in self.raw_edit.text() else " "
        self.raw_edit.setText(separator.join(_format_float(self.vector_spins[index].value()) for index in range(count)))

    def _bool_changed(self, checked: bool) -> None:
        if self._syncing:
            return
        word_style = self.raw_edit.text().strip().casefold() in {"true", "false"}
        self.raw_edit.setText(("true" if checked else "false") if word_style else ("1" if checked else "0"))

    def _integer_changed(self, value: float) -> None:
        if self._syncing:
            return
        numeric = int(value)
        self.raw_edit.setText(hex(numeric) if self.raw_edit.text().strip().casefold().startswith("0x") else str(numeric))

    def _byte4_changed(self, _value: int) -> None:
        if self._syncing:
            return
        numeric = byte4_raw_value([spin.value() for spin in self.byte_spins])
        self.raw_edit.setText(f"0x{numeric:08X}" if self.raw_edit.text().strip().casefold().startswith("0x") else str(numeric))

    def _bits_changed(self, _checked: bool) -> None:
        if self._syncing:
            return
        numeric = sum((1 << index) for index, checkbox in enumerate(self.bit_checkboxes) if checkbox.isChecked())
        self.raw_edit.setText(f"0x{numeric:08X}" if self.raw_edit.text().strip().casefold().startswith("0x") else str(numeric))

    def _cloth_changed(self, value: str) -> None:
        if not self._syncing:
            self.raw_edit.setText(value)

    def _toggle_absent_value(self) -> None:
        field = self._field
        if field is None or field.explicit:
            return
        self.raw_edit.setText("" if self.raw_edit.text().strip() else _default_value(field.kind))


class PacXmlParameterPanel(QWidget):
    rowSelected = Signal(str)

    def __init__(self, rows: Sequence[PacXmlParameterRow], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PacXmlParametersTab")
        self.rows = tuple(rows)
        self.rows_by_id = {row.row_id: row for row in self.rows}
        self.row_items: dict[str, QTreeWidgetItem] = {}
        self._undo: list[_HistoryEdit] = []
        self._redo: list[_HistoryEdit] = []
        self._history_replaying = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        filters = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("PacXmlParameterSearch")
        self.search_edit.setPlaceholderText("Search friendly/exact names, values, shaders, or paths...")
        self.search_edit.setClearButtonEnabled(True)
        self.part_filter = QComboBox()
        self.part_filter.setObjectName("PacXmlPartFilter")
        self.part_filter.addItem("All parts")
        self.part_filter.addItems(list(dict.fromkeys(row.group_label for row in self.rows)))
        self.type_filter = QComboBox()
        self.type_filter.setObjectName("PacXmlTypeFilter")
        self.type_filter.addItem("All types")
        self.type_filter.addItems(sorted({row.parameter_type or row.kind for row in self.rows}, key=str.casefold))
        self.changed_filter = QCheckBox("Changed only")
        self.changed_filter.setObjectName("PacXmlChangedFilter")
        filters.addWidget(self.search_edit, 2)
        filters.addWidget(self.part_filter)
        filters.addWidget(self.type_filter)
        filters.addWidget(self.changed_filter)
        layout.addLayout(filters)

        self.tree = QTreeWidget()
        self.tree.setObjectName("PacXmlParameterTree")
        self.tree.setColumnCount(6)
        self.tree.setHeaderLabels(["Part / Shader", "Type", "Friendly name", "Value", "Validation", "Exact name"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QTreeWidget.SingleSelection)
        self.tree.setSelectionBehavior(QTreeWidget.SelectRows)
        self._populate_tree()
        layout.addWidget(self.tree, 1)

        self.inspector = PacXmlTypedInspector(self.rows)
        layout.addWidget(self.inspector)
        history_row = QHBoxLayout()
        self.undo_button = QPushButton("Undo")
        self.undo_button.setObjectName("PacXmlUndoButton")
        self.redo_button = QPushButton("Redo")
        self.redo_button.setObjectName("PacXmlRedoButton")
        self.reset_all_button = QPushButton("Reset All")
        self.reset_all_button.setObjectName("PacXmlResetAllButton")
        history_row.addWidget(self.undo_button)
        history_row.addWidget(self.redo_button)
        history_row.addWidget(self.reset_all_button)
        history_row.addStretch(1)
        layout.addLayout(history_row)

        self.search_edit.textChanged.connect(self._apply_filters)
        self.part_filter.currentTextChanged.connect(self._apply_filters)
        self.type_filter.currentTextChanged.connect(self._apply_filters)
        self.changed_filter.toggled.connect(self._apply_filters)
        self.tree.currentItemChanged.connect(self._selection_changed)
        self.tree.itemChanged.connect(lambda _item, _column: self._apply_filters())
        self.inspector.raw_edit.textChanged.connect(self._inspector_value_changed)
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        self.reset_all_button.clicked.connect(self.reset_all)
        self._update_history_buttons()

    def _populate_tree(self) -> None:
        group_items: dict[str, QTreeWidgetItem] = {}
        shaders_by_group: dict[str, list[str]] = {}
        for row in self.rows:
            shaders_by_group.setdefault(row.group_label, [])
            if row.shader_name and row.shader_name not in shaders_by_group[row.group_label]:
                shaders_by_group[row.group_label].append(row.shader_name)
        for row in self.rows:
            group_item = group_items.get(row.group_label)
            if group_item is None:
                shaders = ", ".join(shaders_by_group.get(row.group_label, ()))
                group_item = QTreeWidgetItem([row.group_label, "", shaders, "", f"{sum(1 for value in self.rows if value.group_label == row.group_label)} parameters", ""])
                group_item.setFirstColumnSpanned(False)
                group_item.setFlags(group_item.flags() & ~Qt.ItemIsSelectable)
                group_items[row.group_label] = group_item
                self.tree.addTopLevelItem(group_item)
            state = "Read only" if not row.editable else "Absent value" if not row.explicit else "High risk" if row.risk else "Valid"
            item = QTreeWidgetItem(
                ["", row.parameter_type or row.kind, friendly_parameter_name(row.parameter_name), row.value, state, row.parameter_name]
            )
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setData(0, Qt.UserRole, row.row_id)
            item.setData(3, Qt.UserRole, row.value)
            item.setToolTip(0, f"Part: {row.group_label}\nShader: {row.shader_name or 'unknown'}")
            item.setToolTip(2, f"Friendly: {friendly_parameter_name(row.parameter_name)}\nExact: {row.parameter_name}")
            item.setToolTip(3, row.value or "Value attribute is absent")
            item.setToolTip(4, f"{row.detail}\nSource line: {row.source_line}")
            item.setToolTip(5, row.parameter_name)
            group_item.addChild(item)
            self.row_items[row.row_id] = item
        self.tree.expandAll()
        widths = (210, 100, 180, 300, 110, 200)
        for column, width in enumerate(widths):
            self.tree.setColumnWidth(column, width)

    def current_row_id(self) -> str:
        item = self.tree.currentItem()
        return str(item.data(0, Qt.UserRole) or "") if item is not None else ""

    def current_row(self) -> PacXmlParameterRow | None:
        return self.rows_by_id.get(self.current_row_id())

    def select_row(self, row_id: str) -> bool:
        item = self.row_items.get(str(row_id))
        if item is None:
            return False
        parent = item.parent()
        if parent is not None:
            parent.setExpanded(True)
        item.setHidden(False)
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)
        return True

    def set_row_value(self, row_id: str, value: str, *, record_history: bool = True) -> bool:
        item = self.row_items.get(str(row_id))
        if item is None:
            return False
        before = item.text(3)
        after = str(value or "")
        if before == after:
            return False
        if record_history and not self._history_replaying:
            if self._undo and self._undo[-1].row_id == row_id and self._undo[-1].after == before:
                self._undo[-1].after = after
            else:
                self._undo.append(_HistoryEdit(str(row_id), before, after))
            self._redo.clear()
        item.setText(3, after)
        item.setToolTip(3, after or "Value attribute is absent")
        self._update_changed_state(item)
        self._apply_filters()
        self._update_history_buttons()
        return True

    def edited_values(self, kinds: set[str] | None = None) -> dict[str, str]:
        edited: dict[str, str] = {}
        for row_id, item in self.row_items.items():
            row = self.rows_by_id[row_id]
            if kinds is not None and row.kind not in kinds:
                continue
            current = item.text(3).strip()
            if current != row.value:
                edited[row_id] = current
        return edited

    def undo(self) -> None:
        if not self._undo:
            return
        edit = self._undo.pop()
        self._history_replaying = True
        try:
            self.set_row_value(edit.row_id, edit.before, record_history=False)
        finally:
            self._history_replaying = False
        self._redo.append(edit)
        self._update_history_buttons()

    def redo(self) -> None:
        if not self._redo:
            return
        edit = self._redo.pop()
        self._history_replaying = True
        try:
            self.set_row_value(edit.row_id, edit.after, record_history=False)
        finally:
            self._history_replaying = False
        self._undo.append(edit)
        self._update_history_buttons()

    def reset_all(self) -> None:
        for row_id, item in self.row_items.items():
            original = self.rows_by_id[row_id].value
            if item.text(3) != original:
                self.set_row_value(row_id, original, record_history=True)

    def _selection_changed(self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None) -> None:
        row_id = str(current.data(0, Qt.UserRole) or "") if current is not None else ""
        row = self.rows_by_id.get(row_id)
        self.inspector.set_field(row, current.text(3) if row is not None and current is not None else "")
        if row_id:
            self.rowSelected.emit(row_id)

    def _inspector_value_changed(self, value: str) -> None:
        row_id = self.current_row_id()
        if row_id:
            self.set_row_value(row_id, value, record_history=True)

    def _apply_filters(self, *_args: object) -> None:
        query = self.search_edit.text().strip().casefold()
        part = self.part_filter.currentText()
        type_name = self.type_filter.currentText()
        changed_only = self.changed_filter.isChecked()
        for index in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(index)
            visible_children = 0
            for child_index in range(group.childCount()):
                item = group.child(child_index)
                row_id = str(item.data(0, Qt.UserRole) or "")
                row = self.rows_by_id[row_id]
                haystack = " ".join(
                    (row.group_label, row.shader_name, row.parameter_type, row.kind, row.parameter_name, friendly_parameter_name(row.parameter_name), item.text(3), row.detail)
                ).casefold()
                visible = (
                    (not query or query in haystack)
                    and (part == "All parts" or row.group_label == part)
                    and (type_name == "All types" or (row.parameter_type or row.kind) == type_name)
                    and (not changed_only or item.text(3).strip() != row.value)
                )
                item.setHidden(not visible)
                visible_children += int(visible)
            group.setHidden(visible_children == 0)

    def _update_changed_state(self, item: QTreeWidgetItem) -> None:
        row_id = str(item.data(0, Qt.UserRole) or "")
        row = self.rows_by_id.get(row_id)
        if row is None:
            return
        if item.text(3).strip() != row.value:
            item.setText(4, "Changed" + (" / High risk" if row.risk else ""))
        else:
            item.setText(4, "Read only" if not row.editable else "Absent value" if not row.explicit else "High risk" if row.risk else "Valid")

    def _update_history_buttons(self) -> None:
        self.undo_button.setEnabled(bool(self._undo))
        self.redo_button.setEnabled(bool(self._redo))
        self.reset_all_button.setEnabled(bool(self.edited_values()))


def _float_tokens(value: str) -> tuple[float, ...]:
    try:
        return tuple(float(token) for token in re.split(r"[\s,;]+", value.strip()) if token)
    except ValueError:
        return ()


def _color_tokens(value: str) -> tuple[float, ...]:
    normalized = str(value or "").strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", normalized):
        return tuple(int(normalized[index : index + 2], 16) / 255.0 for index in (0, 2, 4))
    return _float_tokens(value)


def _format_float(value: float) -> str:
    return format(float(value), ".12g")


def _default_value(kind: str) -> str:
    if kind == "bool":
        return "false"
    if kind in {"float2", "half2"}:
        return "0 0"
    if kind in {"float3", "color"}:
        return "0 0 0"
    return "0"


__all__ = [
    "PacXmlParameterPanel",
    "PacXmlParameterRow",
    "PacXmlTypedInspector",
    "byte4_channels",
    "byte4_raw_value",
    "friendly_parameter_name",
]
