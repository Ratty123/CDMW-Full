"""Exact raw inventory controls for the separate item.inventory@1 capability."""
from dataclasses import replace

from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget)

from cdmw.core.iteminfo_inventory import read_item_inventory
from cdmw.domain.new_item.item_inventory import (ItemInventorySettings, MaterialGroup, ReserveSlotTarget,
    BOOLEAN_FIELDS, LIST_FIELDS, PAIR_FIELDS, encode_inventory_settings)
from cdmw.ui.new_item.item_settings_editor import whole_number


class ItemInventoryEditor(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._snapshot = self._row = self._source = None
        self._syncing = False
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        toolbar.addStretch(1)
        self.reset = QPushButton('Reset this page')
        self.reset.clicked.connect(self._reset)
        toolbar.addWidget(self.reset)
        layout.addLayout(toolbar)
        self.pages = QTabWidget()
        layout.addWidget(self.pages)
        behavior, materials = QWidget(), QWidget()
        forms = QFormLayout(behavior), QFormLayout(materials)
        self.policies = {}
        for name, label in (('apply_max_stack_cap', 'Apply stack cap:'), ('use_immediately', 'Use immediately:'),
                ('hide_on_pop', 'Hide on inventory pop:'), ('enable_alert_ui', 'Enable UI alerts:'),
                ('inventory_buff', 'Inventory use buff:')):
            combo = QComboBox()
            for text, value in (('Template', None), ('Yes', True), ('No', False)):
                combo.addItem(text, value)
            combo.currentIndexChanged.connect(lambda _index, field=name: self._commit(**{field: self.policies[field].currentData()}))
            self.policies[name] = combo
            forms[0].addRow(label, combo)
        self.numbers = {}
        for name, label in (('quick_slot_index', 'Quick-slot index:'), ('usable_alert_type', 'Usable alert type:')):
            control = QLineEdit()
            control.editingFinished.connect(lambda field=name: self._number(field))
            forms[0].addRow(label, control)
            self.numbers[name] = control
        self.lists, self.overrides = {}, {}
        for name, label in (('consumable_types', 'Consumable type IDs:'), ('reserve_slots', 'Reserve slots:'),
                ('tags', 'Item tag IDs:'), ('material_items', 'Material item IDs:'),
                ('material_gimmicks', 'Material gimmick IDs:'), ('material_groups', 'Material groups:')):
            line = QWidget()
            box = QHBoxLayout(line)
            box.setContentsMargins(0, 0, 0, 0)
            override = QCheckBox('Override')
            control = QLineEdit()
            control.setMaxLength(16384)
            control.setToolTip('Separate entries with semicolons. A checked empty list clears it; unchecked inherits. Reserve slots use slot:condition; material groups use group:raw value. IDs and raw enum values have unverified gameplay meanings.')
            override.toggled.connect(lambda checked, field=name: self._toggle(field, checked))
            control.editingFinished.connect(lambda field=name: self._list(field))
            box.addWidget(override)
            box.addWidget(control, 1)
            self.lists[name], self.overrides[name] = control, override
            forms[0 if name in ('consumable_types', 'reserve_slots') else 1].addRow(label, line)
        self.pages.addTab(behavior, 'Consumable behavior')
        self.pages.addTab(materials, 'Tags and material eligibility')
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.setToolTip('These settings require item.inventory version 1. Material and reserve-slot references are verified. Tags, consumable types and byte selectors are raw values; in-game effects remain unverified.')

    def rebuild(self):
        snapshot, draft = self.controller.snapshot, self.controller.draft
        row = snapshot.rows.get(draft.template_key) if snapshot is not None else None
        if row is not self._row or snapshot is not self._snapshot:
            self._row, self._snapshot = row, snapshot
            try:
                self._source = read_item_inventory(row.raw) if row else None
            except ValueError:
                self._source = None
        self.setEnabled(self._source is not None)
        settings = draft.inventory_settings or ItemInventorySettings()
        self._syncing = True
        try:
            for name, control in self.policies.items():
                control.setCurrentIndex(control.findData(getattr(settings, name)))
            for name, control in self.numbers.items():
                value = getattr(settings, name)
                control.setText('' if value is None else str(value))
                control.setPlaceholderText(str(getattr(self._source, name)) if self._source else '')
            for name, control in self.lists.items():
                value = getattr(settings, name)
                self.overrides[name].setChecked(value is not None)
                control.setEnabled(value is not None)
                if value is None:
                    value = getattr(self._source, name) if self._source else ()
                control.setText('; '.join(f'{entry.slot_key}:{entry.condition_key}' if name == 'reserve_slots'
                    else f'{entry.group_key}:{entry.value}' if name == 'material_groups' else str(entry) for entry in value))
        finally:
            self._syncing = False

    def _commit(self, **values):
        if self._syncing or self._source is None:
            return
        candidate = replace(self.controller.draft.inventory_settings or ItemInventorySettings(), **values)
        if candidate == ItemInventorySettings():
            candidate = None
        try:
            if candidate is not None:
                encode_inventory_settings(candidate)
        except (ValueError, TypeError):
            self._invalid()
            return
        self.controller.draft.inventory_settings = candidate
        self.controller.invalidate_plan()
        self.message.clear()
        self.rebuild()

    def _invalid(self):
        self.controller.invalidate_plan()
        self.rebuild()
        self.message.setText('Invalid inventory value or duplicate entry.')

    def _number(self, name):
        if self._syncing:
            return
        try:
            text = self.numbers[name].text().strip()
            self._commit(**{name: whole_number(text, 0, 255) if text else None})
        except ValueError:
            self._invalid()

    def _toggle(self, name, checked):
        if not self._syncing and self._source is not None:
            self._commit(**{name: getattr(self._source, name) if checked else None})

    def _list(self, name):
        if self._syncing or not self.overrides[name].isChecked():
            return
        try:
            text = self.lists[name].text().strip()
            result = []
            for entry in text.split(';') if text else ():
                if name in PAIR_FIELDS:
                    left, right = entry.split(':')
                    if name == 'reserve_slots':
                        result.append(ReserveSlotTarget(whole_number(left, 1, 0xffffffff), whole_number(right, 0, 0xffffffff)))
                    else:
                        result.append(MaterialGroup(whole_number(left, 1, 65535), whole_number(right, 0, 0xffffffff)))
                else:
                    result.append(whole_number(entry, 0 if name in ('tags', 'consumable_types') else 1, 0xffffffff))
            self._commit(**{name: tuple(result)})
        except ValueError:
            self._invalid()

    def _reset(self):
        self._commit(**{name: None for name in (*BOOLEAN_FIELDS, *LIST_FIELDS, *PAIR_FIELDS, *self.numbers)})
