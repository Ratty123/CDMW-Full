"""New Item Studio, panel 4: the enchant ladder, prices and stack count."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
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
from cdmw.ui.new_item.state import BUY_PRICE_KIND, StatGrid, flat_grid_values, scaled_grid_values

_MAX_EXTRA_LEVELS = 8


class StatsPanel(QGroupBox):
    """A grid over the template's ladder: one row per level, one column per stat or price item."""

    def __init__(self, controller: NewItemStudioController, parent=None) -> None:
        super().__init__("4. Stats and prices", parent)
        self._controller = controller
        self._grid: Optional[StatGrid] = None
        self._syncing = False
        layout = QVBoxLayout(self)
        intro = QLabel(
            "One row per enhancement level (+0 at the top). The stat columns are the item's numbers at that level, "
            "the price columns what the shop charges for it at that level. Everything starts as the template's; "
            "edit a cell to change it."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.table = QTableWidget(0, 0)
        self.table.setMinimumHeight(140)
        self.table.setToolTip("Stat columns are named after the game's status entries (DDD is the damage stat every weapon ladder carries). A blue value differs from the template's; hover it to see the template's.")
        self.table.cellChanged.connect(self._cell_changed)
        layout.addWidget(self.table)

        quick = QHBoxLayout()
        self.one_copper_button = QPushButton("Sell for one copper")
        self.one_copper_button.setToolTip("Every shop price at every level and every base price becomes 1: the item costs one copper in the shop.")
        self.one_copper_button.clicked.connect(self._one_copper)
        quick.addWidget(self.one_copper_button)
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("Advanced: scale, set, add a level, reset")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.advanced_toggle.setArrowType(Qt.RightArrow)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        quick.addWidget(self.advanced_toggle)
        quick.addStretch(1)
        layout.addLayout(quick)

        self.advanced = QWidget()
        presets = QHBoxLayout(self.advanced)
        presets.setContentsMargins(0, 0, 0, 0)
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.01, 100.0)
        self.scale.setSingleStep(0.1)
        self.scale.setValue(1.5)
        self.scale.setPrefix("x ")
        presets.addWidget(self.scale)
        self.scale_button = QPushButton("Scale stats")
        self.scale_button.setToolTip("Multiply every stat of the template's ladder (not the prices) by the factor.")
        self.scale_button.clicked.connect(self._apply_scale)
        presets.addWidget(self.scale_button)
        self.flat = QSpinBox()
        self.flat.setRange(-2_000_000_000, 2_000_000_000)
        self.flat.setValue(10000)
        presets.addWidget(self.flat)
        self.flat_button = QPushButton("Set every stat to")
        self.flat_button.clicked.connect(self._apply_flat)
        presets.addWidget(self.flat_button)
        self.add_level_button = QPushButton("Add a level")
        self.add_level_button.clicked.connect(self._add_level)
        presets.addWidget(self.add_level_button)
        self.reset_button = QPushButton("Back to the template's values")
        self.reset_button.clicked.connect(self._reset)
        presets.addWidget(self.reset_button)
        presets.addStretch(1)
        self.advanced.setVisible(False)
        layout.addWidget(self.advanced)

        prices = QHBoxLayout()
        base_label = QLabel("Base prices:")
        base_label.setToolTip("The item's own price list, per money item; the shop's asking price is this plus the embedded perks' prices, before the level prices above.")
        prices.addWidget(base_label)
        self.price_table = QTableWidget(0, 2)
        self.price_table.setHorizontalHeaderLabels(["Money item", "Price"])
        self.price_table.setMaximumHeight(96)
        self.price_table.cellChanged.connect(self._price_changed)
        prices.addWidget(self.price_table, 1)
        prices.addWidget(QLabel("Max stack:"))
        self.max_stack = QSpinBox()
        self.max_stack.setRange(1, 999_999)
        self.max_stack.valueChanged.connect(self._stack_changed)
        prices.addWidget(self.max_stack)
        layout.addLayout(prices)
        self.own_rows = QCheckBox("Give the item enhancement rows of its own (unproven in game; otherwise it enhances through the template's rows)")
        self.own_rows.toggled.connect(self._own_rows_changed)
        self.own_rows.setVisible(False)
        layout.addWidget(self.own_rows)
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
                return
            grid = self._grid
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
                        item.setForeground(Qt.darkBlue)
                    self.table.setItem(level, column_index, item)
            self.price_table.setRowCount(len(grid.price_items))
            for index, (key, label, template_price) in enumerate(grid.price_items):
                name = QTableWidgetItem(label)
                name.setFlags(name.flags() & ~Qt.ItemIsEditable)
                self.price_table.setItem(index, 0, name)
                price = draft.price_values.get(key, template_price)
                self.price_table.setItem(index, 1, QTableWidgetItem(str(price)))
            row = self._controller.snapshot.row(draft.template_key) if self._controller.snapshot else None
            self.max_stack.blockSignals(True)
            self.max_stack.setValue(int(draft.max_stack_count if draft.max_stack_count is not None else (row.max_stack_count if row else 1)))
            self.max_stack.blockSignals(False)
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
        draft.max_stack_count = None
        self._controller.plan = None
        self.rebuild()


__all__ = ["StatsPanel"]
