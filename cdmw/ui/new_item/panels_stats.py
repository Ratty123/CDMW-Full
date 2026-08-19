"""New Item Studio, panel 4: the enchant ladder, prices and stack count."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.state import BUY_PRICE_KIND, STAT_KIND, StatGrid, flat_grid_values, scaled_grid_values
from cdmw.ui.new_item.ui_kit import EDIT, compact_table_height, intro_label, tone_color

_MAX_EXTRA_LEVELS = 8


class StatsPanel(QGroupBox):
    """A grid over the template's ladder: one row per level, one column per stat or price item."""

    def __init__(self, controller: NewItemStudioController, parent=None) -> None:
        super().__init__("4. Stats and prices", parent)
        self._controller = controller
        self._grid: Optional[StatGrid] = None
        self._syncing = False
        layout = QVBoxLayout(self)
        layout.addWidget(intro_label("The item's numbers per enhancement level, starting as the template's. Edit a cell; blue differs from the template (hover for its value)."))
        self.carries = intro_label("")
        layout.addWidget(self.carries)

        ladder = QGroupBox("Stats and shop prices per level")
        ladder_layout = QVBoxLayout(ladder)
        self.table = QTableWidget(0, 0)
        self.table.setToolTip("Stat columns are named after the game's status entries (DDD is the damage stat every weapon ladder carries); the price columns are what the shop charges at that level.")
        self.table.cellChanged.connect(self._cell_changed)
        ladder_layout.addWidget(self.table)
        quick = QHBoxLayout()
        self.one_copper_button = QPushButton("Sell for one copper")
        self.one_copper_button.setToolTip("Every shop price at every level and every base price becomes 1: the item costs one copper in the shop.")
        self.one_copper_button.clicked.connect(self._one_copper)
        quick.addWidget(self.one_copper_button)
        self.reset_button = QPushButton("Back to the template's values")
        self.reset_button.setToolTip("Drop every edit on this page: the ladder, the base prices, the added levels and the stack size.")
        self.reset_button.clicked.connect(self._reset)
        quick.addWidget(self.reset_button)
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("More: scale all, set all, add a level")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.RightArrow)
        self.advanced_toggle.setAutoRaise(True)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        quick.addWidget(self.advanced_toggle)
        quick.addStretch(1)
        ladder_layout.addLayout(quick)

        self.advanced = QWidget()
        presets = QHBoxLayout(self.advanced)
        presets.setContentsMargins(0, 0, 0, 0)
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.01, 100.0)
        self.scale.setSingleStep(0.1)
        self.scale.setValue(1.5)
        self.scale.setPrefix("x ")
        presets.addWidget(self.scale)
        self.scale_button = QPushButton("Scale every stat")
        self.scale_button.setToolTip("Multiply every stat of the template's ladder (not the prices) by the factor.")
        self.scale_button.clicked.connect(self._apply_scale)
        presets.addWidget(self.scale_button)
        presets.addSpacing(12)
        self.flat = QSpinBox()
        self.flat.setRange(-2_000_000_000, 2_000_000_000)
        self.flat.setValue(10000)
        presets.addWidget(self.flat)
        self.flat_button = QPushButton("Set every stat to this")
        self.flat_button.clicked.connect(self._apply_flat)
        presets.addWidget(self.flat_button)
        presets.addSpacing(12)
        self.add_level_button = QPushButton("Add a level")
        self.add_level_button.setToolTip("One more enhancement level, copying the last one; the least-proven part in game.")
        self.add_level_button.clicked.connect(self._add_level)
        presets.addWidget(self.add_level_button)
        presets.addStretch(1)
        self.advanced.setVisible(False)
        ladder_layout.addWidget(self.advanced)
        # a checkbox's text does not wrap, and this one set the whole step's minimum width,
        # so the rest of the sentence went to the tooltip
        self.own_rows = QCheckBox("Give the item enhancement rows of its own (unproven in game)")
        self.own_rows.setToolTip("Off: the item enhances through the template's own transition rows, the way every in-game check so far was built. On: rows of its own are written, which no check has confirmed yet.")
        self.own_rows.toggled.connect(self._own_rows_changed)
        self.own_rows.setVisible(False)
        ladder_layout.addWidget(self.own_rows)
        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("Add a stat:"))
        self.new_stat = QComboBox()
        self.new_stat.setMinimumWidth(260)
        self.new_stat.setToolTip("Every status entry the game has. The ones some shipped weapon or armour carries come first; the rest are marked unproven, since no shipped equipment row carries them.")
        add_row.addWidget(self.new_stat, 1)
        add_row.addWidget(QLabel("at every level:"))
        self.new_stat_value = QSpinBox()
        self.new_stat_value.setRange(-2_000_000_000, 2_000_000_000)
        self.new_stat_value.setValue(1000)
        add_row.addWidget(self.new_stat_value)
        self.add_stat_button = QPushButton("Add column")
        self.add_stat_button.setToolTip("A new column for that stat, with that value on every level; edit the cells afterwards. The plan adds the stat to the row's stat block.")
        self.add_stat_button.clicked.connect(self._add_stat_column)
        add_row.addWidget(self.add_stat_button)
        self.remove_stat_button = QPushButton("Remove column")
        self.remove_stat_button.setToolTip("Drops the added stat column the selected cell is in (a column the template carries cannot be removed, only edited).")
        self.remove_stat_button.clicked.connect(self._remove_stat_column)
        add_row.addWidget(self.remove_stat_button)
        ladder_layout.addLayout(add_row)
        layout.addWidget(ladder)

        base = QGroupBox("Base price and stack")
        base_layout = QHBoxLayout(base)
        self.price_table = QTableWidget(0, 2)
        self.price_table.setHorizontalHeaderLabels(["Money item", "Price"])
        self.price_table.setToolTip("The item's own price list, per money item; the shop's asking price is this plus the embedded perks' prices, before the level prices above.")
        self.price_table.setMaximumWidth(420)
        self.price_table.cellChanged.connect(self._price_changed)
        base_layout.addWidget(self.price_table, 1)
        stack_form = QFormLayout()
        self.max_stack = QSpinBox()
        self.max_stack.setRange(1, 999_999)
        self.max_stack.setToolTip("How many fit in one inventory slot; equipment is 1.")
        self.max_stack.valueChanged.connect(self._stack_changed)
        stack_form.addRow("Max stack:", self.max_stack)
        base_layout.addLayout(stack_form)
        base_layout.addStretch(1)
        layout.addWidget(base)
        layout.addStretch(1)
        controller.template_changed.connect(self.rebuild)

    def _toggle_advanced(self, checked: bool) -> None:
        self.advanced.setVisible(bool(checked))
        self.own_rows.setVisible(bool(checked))
        self.advanced_toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)

    def _one_copper(self) -> None:
        """Every shop price at every level and every base price becomes 1."""

        if self._grid is None:
            return
        draft = self._controller.draft
        rows = self._grid.level_count + draft.extra_levels
        for column_index, column in enumerate(self._grid.columns):
            if column.kind == BUY_PRICE_KIND:
                for level in range(rows):
                    draft.grid_values[(level, column_index)] = 1
        for key, _label, _template in self._grid.price_items:
            draft.price_values[key] = 1
        self._controller.plan = None
        self.rebuild()

    # ------------------------------------------------------------------ building

    def rebuild(self, *_args) -> None:
        self._grid = self._controller.stat_grid()
        draft = self._controller.draft
        self._syncing = True
        try:
            self.table.clear()
            if self._grid is None:
                self.table.setRowCount(0)
                self.table.setColumnCount(0)
                self.price_table.setRowCount(0)
                self.carries.setText("")
                return
            grid = self._grid
            template_stats = [column.label for column in grid.columns if column.kind == STAT_KIND and column.key not in draft.extra_stat_keys]
            added_stats = [column.label for column in grid.columns if column.kind == STAT_KIND and column.key in draft.extra_stat_keys]
            sentences = [f"This template's row carries {', '.join(template_stats) or 'no stat'} per level, plus the shop price per level; every cell can be changed."]
            if added_stats:
                sentences.append(f"Added here: {', '.join(added_stats)} (written into the row when the plan is built).")
            self.carries.setText(" ".join(sentences))
            self._refresh_status_choices()
            self.table.setColumnCount(len(grid.columns))
            self.table.setHorizontalHeaderLabels([column.label for column in grid.columns])
            rows = grid.level_count + draft.extra_levels
            self.table.setRowCount(rows)
            self.table.setVerticalHeaderLabels([f"Level {level}" for level in range(rows)])
            for level in range(rows):
                for column_index in range(len(grid.columns)):
                    template = grid.template_values[level][column_index] if level < grid.level_count else (
                        grid.template_values[-1][column_index] if grid.template_values else None
                    )
                    value = draft.grid_values.get((level, column_index), template)
                    item = QTableWidgetItem("" if value is None else str(value))
                    if template is None:
                        item.setToolTip("The template has no value here; typing one adds it.")
                    elif value != template:
                        item.setToolTip(f"Template: {template}")
                        item.setForeground(QColor(tone_color(EDIT)))
                    self.table.setItem(level, column_index, item)
            self.price_table.setRowCount(len(grid.price_items))
            for index, (key, label, template_price) in enumerate(grid.price_items):
                name = QTableWidgetItem(label)
                name.setFlags(name.flags() & ~Qt.ItemIsEditable)
                self.price_table.setItem(index, 0, name)
                price = draft.price_values.get(key, template_price)
                price_item = QTableWidgetItem(str(price))
                if price != template_price:
                    price_item.setToolTip(f"Template: {template_price}")
                    price_item.setForeground(QColor(tone_color(EDIT)))
                self.price_table.setItem(index, 1, price_item)
            row = self._controller.snapshot.row(draft.template_key) if self._controller.snapshot else None
            self.max_stack.blockSignals(True)
            self.max_stack.setValue(int(draft.max_stack_count if draft.max_stack_count is not None else (row.max_stack_count if row else 1)))
            self.max_stack.blockSignals(False)
            self.table.resizeColumnsToContents()
            compact_table_height(self.table, rows)
            self.price_table.resizeColumnsToContents()
            compact_table_height(self.price_table, len(grid.price_items), minimum_rows=1, maximum_rows=6)
        finally:
            self._syncing = False

    # ------------------------------------------------------------------ edits

    def _cell_changed(self, level: int, column_index: int) -> None:
        if self._syncing or self._grid is None:
            return
        item = self.table.item(level, column_index)
        text = (item.text() if item is not None else "").strip()
        draft = self._controller.draft
        if not text:
            draft.grid_values.pop((level, column_index), None)
        else:
            try:
                draft.grid_values[(level, column_index)] = int(text)
            except ValueError:
                self.rebuild()
                return
        self._controller.plan = None

    def _price_changed(self, index: int, column: int) -> None:
        if self._syncing or self._grid is None or column != 1:
            return
        item = self.price_table.item(index, 1)
        try:
            value = int((item.text() if item is not None else "").strip())
        except ValueError:
            self.rebuild()
            return
        key = self._grid.price_items[index][0]
        self._controller.draft.price_values[key] = value
        self._controller.plan = None

    def _refresh_status_choices(self) -> None:
        present = {column.key for column in (self._grid.columns if self._grid else ()) if column.kind == STAT_KIND}
        current = self.new_stat.currentData()
        self.new_stat.blockSignals(True)
        try:
            self.new_stat.clear()
            for key, label, carried in self._controller.status_choices():
                if key in present:
                    continue
                self.new_stat.addItem(label if carried else f"{label}  (no shipped equipment carries it: unproven)", key)
            index = self.new_stat.findData(current) if current is not None else -1
            self.new_stat.setCurrentIndex(max(0, index))
        finally:
            self.new_stat.blockSignals(False)
        self.add_stat_button.setEnabled(self.new_stat.count() > 0 and self._grid is not None)
        self.remove_stat_button.setEnabled(bool(self._controller.draft.extra_stat_keys))

    def _add_stat_column(self) -> None:
        """A new stat column after the template's stat columns, with the value on every
        level; the draft's cell values shift right past the insertion so nothing moves."""

        grid = self._grid
        key = self.new_stat.currentData()
        if grid is None or key is None:
            return
        key = int(key)
        draft = self._controller.draft
        if key in draft.extra_stat_keys or any(column.key == key and column.kind == STAT_KIND for column in grid.columns):
            return
        insert_at = sum(1 for column in grid.columns if column.kind == STAT_KIND)
        shifted = {}
        for (level, column_index), value in draft.grid_values.items():
            shifted[(level, column_index + 1 if column_index >= insert_at else column_index)] = value
        draft.grid_values = shifted
        draft.extra_stat_keys.append(key)
        rows = grid.level_count + draft.extra_levels
        for level in range(rows):
            draft.grid_values[(level, insert_at)] = int(self.new_stat_value.value())
        self._controller.plan = None
        self.rebuild()

    def _remove_stat_column(self) -> None:
        grid = self._grid
        if grid is None:
            return
        draft = self._controller.draft
        column_index = self.table.currentColumn()
        if column_index < 0 or column_index >= len(grid.columns):
            column_index = next((i for i, column in enumerate(grid.columns) if column.kind == STAT_KIND and column.key in draft.extra_stat_keys), -1)
        if column_index < 0:
            return
        column = grid.columns[column_index]
        if column.kind != STAT_KIND or column.key not in draft.extra_stat_keys:
            self._controller.status_message.emit("Only a stat column added here can be removed; the template's own stats can be edited, not dropped.", True)
            return
        draft.extra_stat_keys.remove(column.key)
        kept = {}
        for (level, index), value in draft.grid_values.items():
            if index == column_index:
                continue
            kept[(level, index - 1 if index > column_index else index)] = value
        draft.grid_values = kept
        self._controller.plan = None
        self.rebuild()

    def _own_rows_changed(self, checked: bool) -> None:
        self._controller.draft.own_enhancement_rows = bool(checked)
        self._controller.plan = None

    def _stack_changed(self, value: int) -> None:
        if self._syncing:
            return
        self._controller.draft.max_stack_count = int(value)
        self._controller.plan = None

    def _apply_scale(self) -> None:
        if self._grid is None:
            return
        self._controller.draft.grid_values.update(scaled_grid_values(self._grid, float(self.scale.value())))
        self.rebuild()

    def _apply_flat(self) -> None:
        if self._grid is None:
            return
        self._controller.draft.grid_values.update(flat_grid_values(self._grid, int(self.flat.value())))
        self.rebuild()

    def _add_level(self) -> None:
        """A new top level, seeded with the level below it so the plan actually creates it."""

        draft = self._controller.draft
        grid = self._grid
        if grid is None or draft.extra_levels >= _MAX_EXTRA_LEVELS or not grid.level_count:
            return
        new_level = grid.level_count + draft.extra_levels
        below = new_level - 1
        for column_index in range(len(grid.columns)):
            template = grid.template_values[below][column_index] if below < grid.level_count else grid.template_values[-1][column_index]
            value = draft.grid_values.get((below, column_index), template)
            if value is not None:
                draft.grid_values[(new_level, column_index)] = int(value)
        draft.extra_levels += 1
        self._controller.plan = None
        self.rebuild()

    def _reset(self) -> None:
        draft = self._controller.draft
        draft.grid_values.clear()
        draft.price_values.clear()
        draft.extra_levels = 0
        draft.extra_stat_keys.clear()
        draft.max_stack_count = None
        self._controller.plan = None
        self.rebuild()


__all__ = ["StatsPanel"]
