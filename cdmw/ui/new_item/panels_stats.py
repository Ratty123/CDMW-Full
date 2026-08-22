"""New Item Studio, panel 4: the enchant ladder, prices and stack count."""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
)

from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.state import BUY_PRICE_KIND, STAT_KIND, StatGrid, scaled_grid_values
from cdmw.ui.new_item.ui_kit import EDIT, WARN, NoteLabel, compact_table_height, elided, intro_label, note, tone_color

_MAX_EXTRA_LEVELS = 8
#: how far outside the shipped range a value may sit before the note turns amber
_RANGE_SLACK = 10
#: a column label in a button, shortened so one long status name cannot widen the step
_BUTTON_LABEL_CHARS = 40


class StatsPanel(QGroupBox):
    """A grid over the template's ladder: one row per level, one column per stat or price item.

    One draft change is one rail refresh: every edit here goes through
    :meth:`_draft_changed`, which rebuilds the grid when its shape changed and then
    invalidates the plan, and the tab refreshes its summary from that one signal. The
    tables' own per-cell signals are blocked while a rebuild fills them, because Qt
    emits one per cell and a listener validating the whole draft per signal turned a
    refill into dozens of validations.
    """

    def __init__(self, controller: NewItemStudioController, parent=None) -> None:
        super().__init__("4. Combat stats and prices", parent)
        self._controller = controller
        self._grid: Optional[StatGrid] = None
        self._syncing = False
        #: the stat keys the Add-a-stat list was last built for, so a rebuild that left the
        #: ladder's stats alone does not refill the whole list
        self._status_choice_keys: Optional[tuple] = None
        layout = QVBoxLayout(self)
        layout.addWidget(intro_label(
            "Attack, defence and similar fields are raw game values, not the damage number shown to the player. "
            "Start from the template and compare changes rather than guessing a display value."
        ))
        self.carries = intro_label("")
        layout.addWidget(self.carries)
        layout.addWidget(self._build_ladder_group())
        layout.addWidget(self._build_base_group())
        layout.addStretch(1)
        controller.template_changed.connect(self.rebuild)

    # ------------------------------------------------------------------ construction

    def _build_ladder_group(self) -> QGroupBox:
        ladder = QGroupBox("Enhancement ladder: raw stats and the price at each level")
        ladder_layout = QVBoxLayout(ladder)
        self.table = QTableWidget(0, 0)
        self.table.setToolTip(
            "Stat columns are stored ItemInfo values: DDD is the raw attack field every weapon carries. "
            "Price columns are currencies charged at that enhancement level."
        )
        self.table.cellChanged.connect(self._cell_changed)
        self.table.currentCellChanged.connect(self._selected_cell_changed)
        ladder_layout.addWidget(self.table)
        self.selection_note = NoteLabel("")
        ladder_layout.addWidget(self.selection_note)
        quick = QHBoxLayout()
        self.one_copper_button = QPushButton("Set all prices here to 1")
        self.one_copper_button.setToolTip(
            "Set every stored level-up and base-price field on this page to 1. Embedded perk prices may still contribute to the final shop cost."
        )
        self.one_copper_button.clicked.connect(self._one_copper)
        quick.addWidget(self.one_copper_button)
        self.reset_button = QPushButton("Restore this step")
        self.reset_button.setToolTip(
            "Return stats, prices, added levels, stack size and enhancement-row ownership to the template."
        )
        self.reset_button.clicked.connect(self._reset)
        quick.addWidget(self.reset_button)
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("Advanced / experimental")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.RightArrow)
        self.advanced_toggle.setAutoRaise(True)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        quick.addWidget(self.advanced_toggle)
        quick.addStretch(1)
        ladder_layout.addLayout(quick)
        self.advanced = self._build_advanced_group()
        self.advanced.setVisible(False)
        ladder_layout.addWidget(self.advanced)
        return ladder

    def _build_advanced_group(self) -> QGroupBox:
        advanced = QGroupBox("Advanced and experimental editing")
        advanced_layout = QVBoxLayout(advanced)
        self.advanced_warning = NoteLabel("")
        self.advanced_warning.set_note(
            "These controls write raw fields. Values far outside the range used by the game's own equipment have crashed the game when an item was bought.",
            WARN,
        )
        advanced_layout.addWidget(self.advanced_warning)

        presets = QFormLayout()
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.01, 100.0)
        self.scale.setSingleStep(0.1)
        self.scale.setValue(1.5)
        self.scale.setPrefix("x ")
        scale_row = QHBoxLayout()
        scale_row.addWidget(self.scale)
        self.scale_button = QPushButton("Scale template stat columns")
        self.scale_button.setToolTip(
            "Multiply the template's existing raw stat values by this factor. Prices, added stats and added levels are left alone."
        )
        self.scale_button.clicked.connect(self._apply_scale)
        scale_row.addWidget(self.scale_button)
        scale_row.addStretch(1)
        presets.addRow("Relative change:", scale_row)

        self.flat = QSpinBox()
        self.flat.setRange(-2_000_000_000, 2_000_000_000)
        self.flat.setValue(0)
        flat_row = QHBoxLayout()
        flat_row.addWidget(self.flat)
        #: the button names the column it writes (see _refresh_column_actions)
        self.flat_button = QPushButton("Set selected stat column")
        self.flat_button.setToolTip(
            "Set only the selected stat column at every level. Currency columns are never changed by this action."
        )
        self.flat_button.clicked.connect(self._apply_flat)
        flat_row.addWidget(self.flat_button)
        flat_row.addStretch(1)
        presets.addRow("Exact raw value:", flat_row)

        level_row = QHBoxLayout()
        self.add_level_button = QPushButton("Add a level")
        self.add_level_button.setToolTip("One more enhancement level, copying the last one; the least-proven part in game.")
        self.add_level_button.clicked.connect(self._add_level)
        level_row.addWidget(self.add_level_button)
        self.remove_level_button = QPushButton("Remove the last added level")
        self.remove_level_button.setToolTip("Drops the top added level and its values; the template's own levels stay.")
        self.remove_level_button.clicked.connect(self._remove_level)
        level_row.addWidget(self.remove_level_button)
        level_row.addStretch(1)
        presets.addRow("Enhancement ladder:", level_row)
        advanced_layout.addLayout(presets)

        self.own_rows = QCheckBox("Separate enhancement transitions (experimental)")
        self.own_rows.setToolTip("Off: the item enhances through the template's own transition rows, the way every in-game check so far was built. On: rows of its own are written, which no check has confirmed yet.")
        self.own_rows.toggled.connect(self._own_rows_changed)
        advanced_layout.addWidget(self.own_rows)

        add_form = QFormLayout()
        self.new_stat = QComboBox()
        self.new_stat.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.new_stat.setMinimumContentsLength(24)
        self.new_stat.setToolTip("Every status entry the game has. The ones some shipped weapon or armour carries come first; the rest are marked unproven, since no shipped equipment row carries them.")
        add_form.addRow("Add a raw stat:", self.new_stat)
        self.new_stat_value = QSpinBox()
        self.new_stat_value.setRange(-2_000_000_000, 2_000_000_000)
        self.new_stat_value.setValue(0)
        add_form.addRow("Initial value at every level:", self.new_stat_value)
        add_buttons = QHBoxLayout()
        self.add_stat_button = QPushButton("Add column")
        self.add_stat_button.setToolTip("A new column for that stat, with that value on every level; edit the cells afterwards. The plan adds the stat to the row's stat block.")
        self.add_stat_button.clicked.connect(self._add_stat_column)
        add_buttons.addWidget(self.add_stat_button)
        #: the button names the added column it drops (see _refresh_column_actions)
        self.remove_stat_button = QPushButton("Remove column")
        self.remove_stat_button.setToolTip("Drops the named added column and its values; a column the template carries cannot be removed, only edited.")
        self.remove_stat_button.clicked.connect(self._remove_stat_column)
        add_buttons.addWidget(self.remove_stat_button)
        add_buttons.addStretch(1)
        add_form.addRow("", add_buttons)
        advanced_layout.addLayout(add_form)
        #: what the game's own rows carry for the chosen stat: a value outside that range
        #: is where an added stat goes strange in play
        self.stat_range_note = NoteLabel("")
        advanced_layout.addWidget(self.stat_range_note)
        self.new_stat.currentIndexChanged.connect(self._stat_choice_changed)
        return advanced

    def _build_base_group(self) -> QGroupBox:
        base = QGroupBox("Shop price and stack size")
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
        return base

    def _toggle_advanced(self, checked: bool) -> None:
        self.advanced.setVisible(bool(checked))
        self.advanced_toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)

    # ------------------------------------------------------------------ building

    def rebuild(self, *_args) -> None:
        """Refill both tables from the draft, as one event rather than one per cell."""

        self._grid = self._controller.stat_grid()
        self._syncing = True
        self.table.blockSignals(True)
        self.price_table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        self.price_table.setUpdatesEnabled(False)
        try:
            self._fill_tables()
        finally:
            self.table.setUpdatesEnabled(True)
            self.price_table.setUpdatesEnabled(True)
            self.table.blockSignals(False)
            self.price_table.blockSignals(False)
            self._syncing = False
        self._refresh_column_actions()
        self._refresh_selected_cell_note(self.table.currentRow(), self.table.currentColumn())

    def _fill_tables(self) -> None:
        grid = self._grid
        draft = self._controller.draft
        self.table.clear()
        if grid is None:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self.price_table.setRowCount(0)
            self.carries.setText("")
            return
        template_stats = [column.label for column in grid.columns if column.kind == STAT_KIND and column.key not in draft.extra_stat_keys]
        added_stats = [column.label for column in grid.columns if column.kind == STAT_KIND and column.key in draft.extra_stat_keys]
        sentences = [
            f"The template carries {', '.join(template_stats) or 'no raw stat'} per level. "
            "Blue cells differ from it; select a cell to see the exact change and shipped range."
        ]
        if added_stats:
            sentences.append(f"Added here: {', '.join(added_stats)} (written into the row when the plan is built).")
        self.carries.setText(" ".join(sentences))
        self._refresh_status_choices()
        self.table.setColumnCount(len(grid.columns))
        self.table.setHorizontalHeaderLabels([
            f"{column.label} — raw" if column.kind == STAT_KIND else column.label.replace("Price (", "Level price (")
            for column in grid.columns
        ])
        rows = grid.level_count + draft.extra_levels
        self.table.setRowCount(rows)
        self.table.setVerticalHeaderLabels([
            f"Level {level}" if level < grid.level_count else f"Level {level} (added)" for level in range(rows)
        ])
        for level in range(rows):
            for column_index in range(len(grid.columns)):
                template = self._template_value(level, column_index)
                value = draft.grid_values.get((level, column_index), template)
                item = QTableWidgetItem("" if value is None else str(value))
                self._style_cell(item, value, template)
                self.table.setItem(level, column_index, item)
        self.price_table.setRowCount(len(grid.price_items))
        for index, (key, label, template_price) in enumerate(grid.price_items):
            name = QTableWidgetItem(label)
            name.setFlags(name.flags() & ~Qt.ItemIsEditable)
            self.price_table.setItem(index, 0, name)
            price = draft.price_values.get(key, template_price)
            price_item = QTableWidgetItem(str(price))
            self._style_cell(price_item, price, template_price)
            self.price_table.setItem(index, 1, price_item)
        row = self._controller.snapshot.row(draft.template_key) if self._controller.snapshot else None
        self.max_stack.blockSignals(True)
        self.max_stack.setValue(int(draft.max_stack_count if draft.max_stack_count is not None else (row.max_stack_count if row else 1)))
        self.max_stack.blockSignals(False)
        self.own_rows.blockSignals(True)
        self.own_rows.setChecked(bool(draft.own_enhancement_rows))
        self.own_rows.blockSignals(False)
        self.table.resizeColumnsToContents()
        compact_table_height(self.table, rows)
        self.price_table.resizeColumnsToContents()
        compact_table_height(self.price_table, len(grid.price_items), minimum_rows=1, maximum_rows=6)
        if rows and grid.columns and self.table.currentRow() < 0:
            self.table.setCurrentCell(0, 0)

    def _template_value(self, level: int, column_index: int) -> Optional[int]:
        """The template's value for a cell; an added level reads the top template level."""

        grid = self._grid
        if grid is None or not grid.template_values or column_index >= len(grid.columns):
            return None
        if level < grid.level_count:
            return grid.template_values[level][column_index]
        return grid.template_values[-1][column_index]

    @staticmethod
    def _style_cell(item: QTableWidgetItem, value: Optional[int], template: Optional[int]) -> None:
        """Blue text on a blue wash where the cell differs from the template, and a
        tooltip with the template's value; the default look where it agrees."""

        changed = value is not None and value != template
        if template is None:
            item.setToolTip("The template has no value here; typing one adds it.")
        elif changed:
            item.setToolTip(f"Template: {template}")
        else:
            item.setToolTip("")
        if changed:
            tint = QColor(tone_color(EDIT))
            item.setForeground(QBrush(tint))
            tint.setAlpha(36)
            item.setBackground(QBrush(tint))
        else:
            # clear the roles rather than store a null brush: the delegate paints any
            # brush it is handed, and a null one is black text on the dark theme
            item.setData(Qt.ForegroundRole, None)
            item.setData(Qt.BackgroundRole, None)

    def _restyle_cell(self, table: QTableWidget, row: int, column: int, value: Optional[int], template: Optional[int]) -> None:
        """Restyle one cell in place; a rebuild for one edit re-laid the whole step."""

        item = table.item(row, column)
        if item is None:
            return
        syncing, blocked = self._syncing, table.signalsBlocked()
        self._syncing = True
        table.blockSignals(True)
        try:
            self._style_cell(item, value, template)
        finally:
            table.blockSignals(blocked)
            self._syncing = syncing

    def _restore_cell(self, table: QTableWidget, row: int, column: int, value: Optional[int]) -> None:
        """Put the last valid value back into one cell, without a rebuild."""

        item = table.item(row, column)
        if item is None:
            return
        syncing, blocked = self._syncing, table.signalsBlocked()
        self._syncing = True
        table.blockSignals(True)
        try:
            item.setText("" if value is None else str(value))
        finally:
            table.blockSignals(blocked)
            self._syncing = syncing

    def _draft_changed(self, *, rebuild: bool) -> None:
        """After the draft changed: refill the grid when its shape or many cells changed,
        then invalidate the plan. That order matters: the controller's signal is what
        refreshes the rail, and the rail reads this panel's grid."""

        if rebuild:
            self.rebuild()
        self._controller.invalidate_plan()

    # ------------------------------------------------------------------ edits

    def _cell_changed(self, level: int, column_index: int) -> None:
        if self._syncing or self._grid is None:
            return
        item = self.table.item(level, column_index)
        text = (item.text() if item is not None else "").strip()
        draft = self._controller.draft
        template = self._template_value(level, column_index)
        if not text:
            draft.grid_values.pop((level, column_index), None)
        else:
            try:
                draft.grid_values[(level, column_index)] = int(text)
            except ValueError:
                self._restore_cell(self.table, level, column_index, draft.grid_values.get((level, column_index), template))
                self.selection_note.set_note("This cell is not a whole number; it went back to its last valid value.", WARN)
                return
        self._restyle_cell(self.table, level, column_index, draft.grid_values.get((level, column_index), template), template)
        self._draft_changed(rebuild=False)
        self._refresh_selected_cell_note(level, column_index)

    def _selected_cell_changed(self, row: int, column: int, _old_row: int, _old_column: int) -> None:
        self._refresh_selected_cell_note(row, column)
        self._refresh_column_actions()

    def _refresh_selected_cell_note(self, level: int, column_index: int) -> None:
        """Three short lines under the grid: the cell, how it compares with the template,
        and what the game's own equipment carries for that stat."""

        grid = self._grid
        if grid is None or level < 0 or column_index < 0 or column_index >= len(grid.columns):
            self.selection_note.set_note("Select a cell to compare it with the template.", None)
            return
        column = grid.columns[column_index]
        template = self._template_value(level, column_index)
        item = self.table.item(level, column_index)
        try:
            value = int((item.text() if item is not None else "").strip())
        except ValueError:
            self.selection_note.set_note("This cell is not a whole number; it went back to its last valid value.", WARN)
            return
        lines: List[Tuple[str, Optional[str]]] = [note(f"Level {level} {column.label}: {value:,}", None)]
        if template is None:
            lines.append(note("Template: no value here, so this is an addition", EDIT))
        elif value == int(template):
            lines.append(note(f"Template: {int(template):,}, unchanged", None))
        else:
            delta = value - int(template)
            if int(template):
                percent = delta / abs(int(template)) * 100.0
                lines.append(note(f"Template: {int(template):,} ({delta:+,}, {percent:+.1f}%)", EDIT))
            else:
                lines.append(note(f"Template: {int(template):,} ({delta:+,})", EDIT))
        if column.kind == BUY_PRICE_KIND:
            lines.append(note("Currency, not a combat stat", None))
        else:
            measured = self._controller.status_value_range(int(column.key))
            if measured is None:
                lines.append(note("Shipped equipment: none carries this stat, so there is no range to go by", WARN))
            else:
                _entries, low, _middle, high = measured
                if value < (low / _RANGE_SLACK if low > 0 else low) or value > high * _RANGE_SLACK:
                    lines.append(note(f"Shipped equipment: {low:,} to {high:,}; this value is far outside that range", WARN))
                else:
                    lines.append(note(f"Shipped equipment: {low:,} to {high:,}", None))
            if not self.flat.hasFocus():
                self.flat.setValue(value)
        self.selection_note.set_lines(lines)

    def _refresh_column_actions(self) -> None:
        """Name the column the exact-value and remove-column buttons act on, and enable
        the ladder buttons only while they have something to do."""

        grid = self._grid
        draft = self._controller.draft
        stat_column = self._selected_stat_column_index()
        if grid is not None and stat_column >= 0:
            self.flat_button.setText(f"Set {elided(grid.columns[stat_column].label, _BUTTON_LABEL_CHARS)} at every level")
            self.flat_button.setEnabled(True)
        else:
            self.flat_button.setText("Set selected stat column")
            self.flat_button.setEnabled(False)
        removable = self._removable_column_index()
        if grid is not None and removable >= 0:
            self.remove_stat_button.setText(f"Remove the {elided(grid.columns[removable].label, _BUTTON_LABEL_CHARS)} column")
            self.remove_stat_button.setEnabled(True)
        else:
            self.remove_stat_button.setText("Remove column")
            self.remove_stat_button.setEnabled(False)
        has_ladder = grid is not None and bool(grid.level_count)
        self.scale_button.setEnabled(has_ladder)
        self.add_level_button.setEnabled(has_ladder and draft.extra_levels < _MAX_EXTRA_LEVELS)
        self.remove_level_button.setEnabled(has_ladder and draft.extra_levels > 0)

    def _price_changed(self, index: int, column: int) -> None:
        if self._syncing or self._grid is None or column != 1:
            return
        item = self.price_table.item(index, 1)
        key, _label, template = self._grid.price_items[index]
        draft = self._controller.draft
        try:
            value = int((item.text() if item is not None else "").strip())
        except ValueError:
            self._restore_cell(self.price_table, index, 1, draft.price_values.get(key, template))
            return
        draft.price_values[key] = value
        self._restyle_cell(self.price_table, index, 1, value, template)
        self._draft_changed(rebuild=False)

    def _refresh_status_choices(self) -> None:
        present = tuple(sorted(column.key for column in (self._grid.columns if self._grid else ()) if column.kind == STAT_KIND))
        cache_key = (id(self._controller.snapshot), present)
        if cache_key != self._status_choice_keys:
            self._status_choice_keys = cache_key
            current = self.new_stat.currentData()
            self.new_stat.blockSignals(True)
            try:
                self.new_stat.clear()
                for key, label, carried in self._controller.status_choices():
                    if key in present:
                        continue
                    self.new_stat.addItem(label if carried else f"{label} — experimental", key)
                index = self.new_stat.findData(current) if current is not None else -1
                self.new_stat.setCurrentIndex(max(0, index))
            finally:
                self.new_stat.blockSignals(False)
        self.add_stat_button.setEnabled(self.new_stat.count() > 0 and self._grid is not None)
        self._stat_choice_changed()

    def _stat_choice_changed(self, _index: int = 0) -> None:
        """Say what shipped equipment carries for this stat, and start the value there."""

        key = self.new_stat.currentData()
        if key is None:
            self.stat_range_note.set_note("", None)
            return
        measured = self._controller.status_value_range(int(key))
        label = self.new_stat.currentText().split(" — ")[0]
        if measured is None:
            self.stat_range_note.set_note(f"No shipped equipment carries {label}, so there is no value to go by; whatever you type here is a guess.", WARN)
            return
        entries, low, middle, high = measured
        self.stat_range_note.set_note(
            f"Shipped equipment carries {label} between {low:,} and {high:,} (median {middle:,}, {entries:,} entrie(s)). "
            "A value far outside that range has crashed the game when the item is bought.",
            None,
        )
        if not self.new_stat_value.hasFocus():
            self.new_stat_value.setValue(int(middle))

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
        self._draft_changed(rebuild=True)

    def _removable_column_index(self) -> int:
        """The added stat column the Remove button drops: the selected one when the
        selection is on an added column, else the most recently added."""

        grid = self._grid
        if grid is None:
            return -1
        draft = self._controller.draft
        extra = set(draft.extra_stat_keys)
        current = self.table.currentColumn()
        if 0 <= current < len(grid.columns) and grid.columns[current].kind == STAT_KIND and grid.columns[current].key in extra:
            return current
        for key in reversed(draft.extra_stat_keys):
            index = next((i for i, column in enumerate(grid.columns) if column.kind == STAT_KIND and column.key == key), -1)
            if index >= 0:
                return index
        return -1

    def _remove_stat_column(self) -> None:
        grid = self._grid
        column_index = self._removable_column_index()
        if grid is None or column_index < 0:
            return
        draft = self._controller.draft
        draft.extra_stat_keys.remove(grid.columns[column_index].key)
        kept = {}
        for (level, index), value in draft.grid_values.items():
            if index == column_index:
                continue
            kept[(level, index - 1 if index > column_index else index)] = value
        draft.grid_values = kept
        self._draft_changed(rebuild=True)

    def _own_rows_changed(self, checked: bool) -> None:
        self._controller.draft.own_enhancement_rows = bool(checked)
        self._draft_changed(rebuild=False)

    def _stack_changed(self, value: int) -> None:
        if self._syncing:
            return
        draft = self._controller.draft
        row = self._controller.snapshot.row(draft.template_key) if self._controller.snapshot is not None and draft.template_key is not None else None
        draft.max_stack_count = None if row is not None and int(value) == int(row.max_stack_count) else int(value)
        self._draft_changed(rebuild=False)

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
        self._draft_changed(rebuild=True)

    def _apply_scale(self) -> None:
        if self._grid is None:
            return
        self._controller.draft.grid_values.update(scaled_grid_values(self._grid, float(self.scale.value())))
        self._draft_changed(rebuild=True)

    def _apply_flat(self) -> None:
        grid = self._grid
        if grid is None:
            return
        column_index = self._selected_stat_column_index()
        if column_index < 0:
            self._controller.status_message.emit("Select a stat column first; prices are not raw stats.", True)
            return
        draft = self._controller.draft
        rows = grid.level_count + draft.extra_levels
        for level in range(rows):
            draft.grid_values[(level, column_index)] = int(self.flat.value())
        self._draft_changed(rebuild=True)

    def _selected_stat_column_index(self) -> int:
        grid = self._grid
        if grid is None:
            return -1
        current = self.table.currentColumn()
        if 0 <= current < len(grid.columns) and grid.columns[current].kind == STAT_KIND:
            return current
        return next((index for index, column in enumerate(grid.columns) if column.kind == STAT_KIND), -1)

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
        self._draft_changed(rebuild=True)

    def _remove_level(self) -> None:
        """Drop the top added level and every value typed into it; template levels stay."""

        draft = self._controller.draft
        grid = self._grid
        if grid is None or draft.extra_levels <= 0:
            return
        top = grid.level_count + draft.extra_levels - 1
        for key in [key for key in draft.grid_values if key[0] == top]:
            del draft.grid_values[key]
        draft.extra_levels -= 1
        self._draft_changed(rebuild=True)

    def _reset(self) -> None:
        draft = self._controller.draft
        draft.grid_values.clear()
        draft.price_values.clear()
        draft.extra_levels = 0
        draft.extra_stat_keys.clear()
        draft.max_stack_count = None
        draft.own_enhancement_rows = False
        self.own_rows.blockSignals(True)
        self.own_rows.setChecked(False)
        self.own_rows.blockSignals(False)
        self._draft_changed(rebuild=True)

    def summary_text(self) -> tuple[str, bool]:
        """A short, truthful rail summary for this step."""

        draft = self._controller.draft
        grid = self._grid
        stat_count = price_count = 0
        if grid is not None:
            for (level, column_index), value in draft.grid_values.items():
                if value is None or column_index >= len(grid.columns):
                    continue
                if level >= grid.level_count:
                    continue
                template = grid.template_values[level][column_index] if level < grid.level_count else None
                if value == template:
                    continue
                if grid.columns[column_index].kind == STAT_KIND:
                    stat_count += 1
                else:
                    price_count += 1
        price_count += sum(
            1 for key, _label, template in (grid.price_items if grid is not None else ())
            if draft.price_values.get(key, template) != template
        )
        extras = int(draft.extra_levels > 0) + int(bool(draft.extra_stat_keys)) + int(draft.max_stack_count is not None) + int(draft.own_enhancement_rows)
        if not (stat_count or price_count or extras):
            return "Combat and prices: template values", False
        parts = []
        if stat_count:
            parts.append(f"{stat_count} stat cell(s)")
        if price_count:
            parts.append(f"{price_count} price field(s)")
        if draft.extra_levels:
            parts.append(f"{draft.extra_levels} added level(s)")
        if draft.extra_stat_keys:
            parts.append(f"{len(draft.extra_stat_keys)} added stat(s)")
        if draft.max_stack_count is not None:
            parts.append("stack changed")
        if draft.own_enhancement_rows:
            parts.append("separate enhancement rows")
        return f"Combat and prices: {', '.join(parts)}", True


__all__ = ["StatsPanel"]
