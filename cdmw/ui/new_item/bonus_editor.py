"""Equipment bonus presets and established per-enhancement parameter levels."""
from dataclasses import replace
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from cdmw.domain.new_item.authoring import EquipmentBonus, LevelBonuses
from cdmw.services.new_item_equipment_bonuses import signed_parameter


class BonusEditor(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller, self.index = controller, None
        self._syncing = False
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.load = QPushButton("Load inherent bonuses")
        self.load.clicked.connect(self._load)
        row.addWidget(self.load)
        self.customize = QCheckBox("Customize inherent bonuses")
        self.customize.toggled.connect(self._toggle)
        row.addWidget(self.customize)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Enhancement level:"))
        self.level = QComboBox()
        self.level.currentIndexChanged.connect(self._show_values)
        row.addWidget(self.level)
        self.apply_all = QPushButton("Apply to all levels")
        self.apply_all.clicked.connect(self._apply_all)
        row.addWidget(self.apply_all)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.presets = QComboBox()
        row.addWidget(self.presets, 1)
        self.use_preset = QPushButton("Use equipment preset")
        self.use_preset.clicked.connect(self._preset)
        row.addWidget(self.use_preset)
        layout.addLayout(row)
        self.values = QTableWidget(0, 2)
        self.values.setHorizontalHeaderLabels(["Inherent bonus", "Parameter level"])
        self.values.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.values, 1)
        row = QHBoxLayout()
        self.advanced = QComboBox()
        self.advanced.setToolTip("Only decoded equipment-used BuffInfo definitions are editable. Parameter levels are raw game levels; no percentage conversion is assumed.")
        row.addWidget(self.advanced, 1)
        self.add = QPushButton("Add bonus")
        self.add.clicked.connect(self._add)
        row.addWidget(self.add)
        self.remove = QPushButton("Remove selected")
        self.remove.clicked.connect(self._remove)
        row.addWidget(self.remove)
        layout.addLayout(row)
        self.state = QLabel()
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        controller.authoring_index_ready.connect(self._ready)
        controller.authoring_index_failed.connect(self._failed)
        controller.template_changed.connect(self.refresh)
        controller.snapshot_ready.connect(self._snapshot_changed)
        controller.busy_changed.connect(lambda busy: self.load.setEnabled(not busy))
        self.refresh()

    def _template(self):
        c = self.controller
        return c.snapshot.rows.get(c.draft.template_key) if c.snapshot else None

    def _load(self):
        self.state.setText("Loading bonus definitions…")
        self.controller.start_authoring_index("bonuses")

    def _snapshot_changed(self):
        self.index = None
        self.presets.clear()
        self.advanced.clear()
        self.refresh()

    def _ready(self, kind, index):
        if kind != "bonuses":
            return
        self.index = index
        self.presets.clear()
        for _item, label, values in index.presets:
            self.presets.addItem(label, values)
        self.advanced.clear()
        for key, buff in sorted(index.buffs.items(), key=lambda pair: pair[1].name):
            self.advanced.addItem(f"{buff.name} ({key})", key)
        self.refresh()

    def _failed(self, kind, message):
        if kind == "bonuses":
            self.state.setText(message)

    def refresh(self, *_args):
        self._syncing = True
        try:
            prior = self.level.currentData()
            self.level.clear()
            row = self._template()
            if row:
                for level in row.enchant_levels:
                    self.level.addItem(f"+{level.level}", level.level)
            self.level.setCurrentIndex(max(0, self.level.findData(prior)))
            self.customize.setChecked(self.controller.draft.equipment_bonuses is not None)
            self.customize.setEnabled(bool(row and row.enchant_levels))
        finally:
            self._syncing = False
        self._show_values()

    def _selections(self):
        chosen = self.controller.draft.equipment_bonuses
        row = self._template()
        inherited = {level.level: tuple(EquipmentBonus(k, signed_parameter(v)) for k, v in zip(level.equip_buffs, level.equip_buff_extras))
                     for level in row.enchant_levels} if row else {}
        if chosen == ():
            return {level: () for level in inherited}
        if chosen is not None:
            inherited.update({level.level: level.bonuses for level in chosen})
        return inherited

    def _show_values(self, *_args):
        if self._syncing:
            return
        self._syncing = True
        try:
            chosen = self._selections().get(self.level.currentData(), ())
            editable = self.customize.isChecked() and self.index is not None
            for control in (self.values, self.apply_all, self.presets, self.use_preset, self.advanced, self.add, self.remove):
                control.setEnabled(editable)
            self.values.setRowCount(len(chosen))
            for i, bonus in enumerate(chosen):
                buff = self.index.buffs.get(bonus.buff_key) if self.index else None
                label = QTableWidgetItem(buff.name if buff else str(bonus.buff_key))
                self.values.setItem(i, 0, label)
                value = QSpinBox()
                value.setRange(buff.minimum if buff else bonus.parameter, buff.maximum if buff else bonus.parameter)
                value.setValue(bonus.parameter)
                value.setEnabled(buff is not None)
                value.valueChanged.connect(lambda parameter, row=i: self._parameter(row, parameter))
                self.values.setCellWidget(i, 1, value)
            self.values.resizeColumnToContents(0)
            unsupported = len(self.index.unsupported) if self.index else 0
            self.state.setText(f"{'Custom' if self.customize.isChecked() else 'Inherited'} bonuses · {len(chosen)} at this level" + (f" · {unsupported} unsupported definitions" if unsupported else ""))
        finally:
            self._syncing = False

    def _toggle(self, checked):
        if self._syncing:
            return
        inherited = self._selections()
        self.controller.draft.equipment_bonuses = tuple(LevelBonuses(k, v) for k, v in inherited.items()) if checked else None
        self.controller.invalidate_plan()
        self._show_values()

    def _write(self, chosen, *, all_levels=False, refresh=True):
        if self._syncing or self.level.currentData() is None:
            return
        selections = self._selections()
        targets = selections.keys() if all_levels else (self.level.currentData(),)
        if all_levels:
            targets = [self.level.itemData(i) for i in range(self.level.count())]
        for level in targets:
            selections[level] = tuple(chosen)
        self.controller.draft.equipment_bonuses = tuple(LevelBonuses(k, v) for k, v in sorted(selections.items()))
        self.controller.invalidate_plan()
        if refresh:
            self._show_values()

    def _parameter(self, row, parameter):
        chosen = list(self._selections().get(self.level.currentData(), ()))
        chosen[row] = replace(chosen[row], parameter=parameter)
        self._write(chosen, refresh=False)

    def _apply_all(self):
        self._write(self._selections().get(self.level.currentData(), ()), all_levels=True)

    def _preset(self):
        values = self.presets.currentData()
        if values is not None:
            self._write(tuple(EquipmentBonus(key, parameter) for key, parameter in values))

    def _add(self):
        key = self.advanced.currentData()
        if key is None or self.index is None:
            return
        chosen = list(self._selections().get(self.level.currentData(), ()))
        if any(bonus.buff_key == key for bonus in chosen):
            return
        buff = self.index.buffs[key]
        self._write((*chosen, EquipmentBonus(key, buff.levels[0].level)))

    def _remove(self):
        chosen = list(self._selections().get(self.level.currentData(), ()))
        row = self.values.currentRow()
        if 0 <= row < len(chosen):
            chosen.pop(row)
            self._write(chosen)
