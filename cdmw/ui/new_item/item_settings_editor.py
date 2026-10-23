"""Guided, exact-integer editing for the required item.properties@2 capability."""
from dataclasses import replace
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget)

from cdmw.core.iteminfo_settings import read_item_settings
from cdmw.domain.new_item.item_settings import (ItemSettings, RepairEntry, QuantityEdit,
    BOOLEAN_FIELDS, encode_settings)
from cdmw.ui.new_item.choice_model import set_choice_rows
from cdmw.services.active_ui_translation import translate_active_ui_text


def whole_number(text, minimum, maximum):
    """Accept exact integers and locale grouping, with no float conversion."""
    text = str(text).strip()
    if len(text) > 64:
        raise ValueError('Integer text is too long.')
    if not re.fullmatch(r'-?\d+', text):
        match = re.fullmatch(r"-?\d{1,3}([., '\u00a0\u202f\u066c])\d{3}(?:\1\d{3})*", text)
        if match is None:
            raise ValueError('Expected a whole number.')
        text = text.replace(match[1], '')
    value = int(text)
    if not minimum <= value <= maximum:
        raise ValueError('Integer is outside the supported range.')
    return value


class ItemSettingsEditor(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.index = None
        self._syncing = False
        self._row = None
        self._source = None
        self._quantities = ()
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.load = QPushButton('Load item references')
        self.load.clicked.connect(lambda: controller.start_authoring_index('item-settings'))
        toolbar.addWidget(self.load)
        self.reset = QPushButton('Reset this page')
        self.reset.clicked.connect(self._reset)
        toolbar.addWidget(self.reset)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        self.pages = QTabWidget()
        layout.addWidget(self.pages, 1)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

        policies = QWidget()
        form = QFormLayout(policies)
        self.policies = {}
        for name, label in zip(BOOLEAN_FIELDS, ('Block shop sale:', 'Allow discard:', 'Important item:',
                'Destroy when broken:', 'Keep after extraction:', 'Allow disassembly:', 'Allow extraction:')):
            combo = QComboBox()
            combo.addItem('Template', None)
            combo.addItem('Yes', True)
            combo.addItem('No', False)
            combo.currentIndexChanged.connect(lambda _index, field=name: self._policy_changed(field))
            self.policies[name] = combo
            form.addRow(label, combo)
        self.pages.addTab(policies, 'Item rules')

        repair = QWidget()
        box = QVBoxLayout(repair)
        self.override_repairs = QCheckBox('Override repair materials')
        self.override_repairs.toggled.connect(self._repair_toggle)
        box.addWidget(self.override_repairs)
        self.repairs = self._table(('Repair item', 'Repair value', 'Repair style', 'Quantity'))
        self.repairs.cellChanged.connect(self._repair_changed)
        box.addWidget(self.repairs, 1)
        actions = QHBoxLayout()
        self.repair_item = QComboBox()
        actions.addWidget(self.repair_item, 1)
        self.add_repair = QPushButton('Add repair material')
        self.add_repair.clicked.connect(self._add_repair)
        actions.addWidget(self.add_repair)
        self.remove_repair = QPushButton('Remove selected')
        self.remove_repair.clicked.connect(self._remove_repairs)
        actions.addWidget(self.remove_repair)
        box.addLayout(actions)
        self.pages.addTab(repair, 'Repairs')

        extraction = QWidget()
        form = QFormLayout(extraction)
        self.reward = QComboBox()
        self.reward.currentIndexChanged.connect(lambda _index: self._reward_changed())
        form.addRow('Additional extraction reward:', self.reward)
        self.minimum_extract_level = self._number('minimum_extract_level', 0, 65535)
        form.addRow('Minimum extraction level:', self.minimum_extract_level)
        self.pages.addTab(extraction, 'Extraction')

        use = QWidget()
        box = QVBoxLayout(use)
        self.override_actions = QCheckBox('Override use actions')
        self.override_actions.toggled.connect(self._action_toggle)
        box.addWidget(self.override_actions)
        self.actions = self._table(('Source action', 'Type'))
        box.addWidget(self.actions, 1)
        actions = QHBoxLayout()
        self.use_action = QComboBox()
        actions.addWidget(self.use_action, 1)
        self.add_action = QPushButton('Add use action')
        self.add_action.clicked.connect(self._add_action)
        actions.addWidget(self.add_action)
        self.remove_action = QPushButton('Remove selected')
        self.remove_action.clicked.connect(self._remove_actions)
        actions.addWidget(self.remove_action)
        box.addLayout(actions)
        form = QFormLayout()
        self.cooldowns = self._triple(form, 'cooldowns', 'Cooldown values:', (1 << 64) - 1)
        self.maximum_charges = self._triple(form, 'maximum_charges', 'Maximum charges:', 0xffffffff)
        self.charge_type = self._number('charge_type', 0, 255)
        self.charge_type.setToolTip('Raw source charge type; gameplay behaviour requires separate verification.')
        form.addRow('Charge type:', self.charge_type)
        self.shared_cooldown_group = self._number('shared_cooldown_group', 0, 0xffffffff)
        form.addRow('Shared cooldown group:', self.shared_cooldown_group)
        box.addLayout(form)
        self.pages.addTab(use, 'Use and charges')

        self.amounts = self._table(('Kind', 'Level', 'Item / stat', 'Template value', 'Override'))
        self.amounts.cellChanged.connect(self._amount_changed)
        self.amounts.setToolTip('Blank overrides inherit the template. Prices use unsigned 64-bit amounts; stat counters use signed 64-bit amounts. Existing rows only.')
        self.pages.addTab(self.amounts, 'Price and stat amounts')
        self.pages.setToolTip('Raw stored item settings. Unknown layouts and missing dependencies refuse; in-game effects remain unverified.')
        controller.authoring_index_ready.connect(self._ready)
        controller.authoring_index_failed.connect(self._failed)
        controller.snapshot_ready.connect(self._snapshot)
        controller.busy_changed.connect(lambda busy: self.load.setEnabled(not busy and controller.snapshot is not None))
        self.rebuild()

    @staticmethod
    def _table(headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        return table

    def _number(self, field, minimum, maximum):
        control = QLineEdit()
        control.setObjectName('raw_item_setting_' + field)
        control.setPlaceholderText('Template')
        control.setMaxLength(32)
        control.editingFinished.connect(lambda: self._number_changed(field, control, minimum, maximum))
        control.textEdited.connect(lambda _text: self.controller.invalidate_plan())
        return control

    def _triple(self, form, field, label, maximum):
        row = QHBoxLayout()
        controls = tuple(QLineEdit() for _ in range(3))
        for index, control in enumerate(controls):
            control.setObjectName(f'raw_item_setting_{field}_{index}')
            control.setMaxLength(32)
            control.setToolTip('Three raw stored values in source order. Timer units and in-game effects are unverified.')
            control.editingFinished.connect(lambda name=field, limit=maximum: self._triple_changed(name, limit))
            control.textEdited.connect(lambda _text: self.controller.invalidate_plan())
            row.addWidget(control)
        form.addRow(label, row)
        return controls

    def _snapshot(self):
        self.index = None
        self._row = None
        self.rebuild()

    def _ready(self, kind, index):
        if kind == 'item-settings':
            self.index = index
            self._choices()
            self.rebuild()
            self.message.setText('Some optional catalogues are unavailable; other item controls remain usable.' if index.unavailable else '')

    def _failed(self, kind, message):
        if kind == 'item-settings':
            self.message.setText(message)

    def _choices(self):
        self._syncing = True
        try:
            set_choice_rows(self.repair_item, tuple((f'{name} ({key})', key) for key, name in self.index.items) if self.index else ())
            set_choice_rows(self.use_action, tuple((f'{name} ({key})', key) for key, name, _kind in self.index.actions) if self.index else ())
        finally:
            self._syncing = False

    def default_settings(self):
        snapshot, key = self.controller.snapshot, self.controller.draft.template_key
        if self._source is not None and snapshot is not None and key is not None and not snapshot.equip_type_name(snapshot.row(key)) and self._source.use_actions:
            return ItemSettings(use_actions=self._source.use_actions)
        return None

    def _commit(self, **values):
        if self._syncing or self._source is None:
            return
        candidate = replace(self.controller.draft.item_settings or ItemSettings(), **values)
        if candidate == ItemSettings():
            candidate = self.default_settings()
        try:
            if candidate is not None:
                encode_settings(candidate)
        except (ValueError, TypeError):
            self._invalid()
            return
        self.controller.draft.item_settings = candidate
        self.message.clear()
        self.controller.invalidate_plan()
        self.rebuild()

    def _invalid(self):
        self.controller.invalidate_plan()
        self.rebuild()
        self.message.setText("Enter a whole number within the field's range.")

    def _reset(self):
        if self._source is not None:
            self.controller.draft.item_settings = self.default_settings()
            self.controller.invalidate_plan()
            self.rebuild()

    def rebuild(self):
        snapshot, draft = self.controller.snapshot, self.controller.draft
        row = snapshot.rows.get(draft.template_key) if snapshot is not None else None
        if row is not self._row:
            self._row = row
            self.message.clear()
            try:
                self._source, self._quantities = read_item_settings(row.raw) if row is not None else (None, ())
            except ValueError:
                self._source, self._quantities = None, ()
        self.pages.setEnabled(self._source is not None)
        self.reset.setEnabled(self._source is not None)
        if self._source is None:
            self.message.setText('This template has no complete supported ItemInfo layout.')
            return
        self._syncing = True
        settings = draft.item_settings or ItemSettings()
        try:
            for name, combo in self.policies.items():
                combo.setCurrentIndex(combo.findData(getattr(settings, name)))
            for name in ('minimum_extract_level', 'charge_type', 'shared_cooldown_group'):
                control = getattr(self, name)
                value = getattr(settings, name)
                control.setText('' if value is None else str(value))
                control.setPlaceholderText(str(getattr(self._source, name)))
            for name in ('cooldowns', 'maximum_charges'):
                value = getattr(settings, name)
                for index, control in enumerate(getattr(self, name)):
                    control.setText('' if value is None else str(value[index]))
                    control.setPlaceholderText(str(getattr(self._source, name)[index]))
            self.reward.clear()
            self.reward.addItem('Template', None)
            self.reward.addItem('No additional reward', 0)
            for key, name in self.index.rewards if self.index else ():
                self.reward.addItem(f'{name} ({key})', key)
            if settings.extraction_reward is not None and self.reward.findData(settings.extraction_reward) < 0:
                self.reward.addItem(str(settings.extraction_reward), settings.extraction_reward)
            self.reward.setCurrentIndex(self.reward.findData(settings.extraction_reward))
            repairs = settings.repairs if settings.repairs is not None else self._source.repairs
            self.override_repairs.setChecked(settings.repairs is not None)
            self.repairs.setRowCount(len(repairs))
            item_names = dict(self.index.items) if self.index else {}
            for index, entry in enumerate(repairs):
                item = QTableWidgetItem(f'{item_names.get(entry.resource_item, entry.resource_item)} ({entry.resource_item})')
                item.setData(Qt.UserRole, entry.resource_item)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.repairs.setItem(index, 0, item)
                for column, value in enumerate((entry.repair_value, entry.repair_style, entry.resource_count), 1):
                    item = QTableWidgetItem(str(value))
                    if settings.repairs is None:
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.repairs.setItem(index, column, item)
            self.add_repair.setEnabled(settings.repairs is not None and self.repair_item.count() > 0)
            self.remove_repair.setEnabled(settings.repairs is not None)
            actions = settings.use_actions if settings.use_actions is not None else self._source.use_actions
            self.override_actions.setChecked(settings.use_actions is not None)
            self.actions.setRowCount(len(actions))
            action_names = {key: (name, kind.removeprefix('ItemUseData_')) for key, name, kind in self.index.actions} if self.index else {}
            for index, key in enumerate(actions):
                name, kind = action_names.get(key, (str(key), ''))
                kind = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', kind)
                for column, text in enumerate((f'{name} ({key})', kind)):
                    item = QTableWidgetItem(text)
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.actions.setItem(index, column, item)
            self.add_action.setEnabled(settings.use_actions is not None and self.use_action.count() > 0)
            self.remove_action.setEnabled(settings.use_actions is not None)
            overrides = {(edit.kind, edit.level, edit.key): edit.value for edit in settings.quantities}
            kind_labels = {'price': translate_active_ui_text('Shop price'),
                'buy_price': translate_active_ui_text('Enhancement price'), 'stat': translate_active_ui_text('Stat')}
            self.amounts.setRowCount(len(self._quantities))
            for index, amount in enumerate(self._quantities):
                label = snapshot.status_names.get(amount.key, str(amount.key)) if amount.kind == 'stat' else item_names.get(amount.key, str(amount.key))
                value = overrides.get((amount.kind, amount.level, amount.key))
                for column, text in enumerate((kind_labels[amount.kind], '' if amount.level is None else str(amount.level),
                        label, str(amount.value), '' if value is None else str(value))):
                    item = QTableWidgetItem(text)
                    if column != 4:
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.amounts.setItem(index, column, item)
        finally:
            self._syncing = False

    def _policy_changed(self, field):
        self._commit(**{field: self.policies[field].currentData()})

    def _number_changed(self, field, control, minimum, maximum):
        if self._syncing:
            return
        try:
            value = whole_number(control.text(), minimum, maximum) if control.text().strip() else None
        except ValueError:
            self._invalid()
            return
        self._commit(**{field: value})

    def _triple_changed(self, field, maximum):
        if self._syncing or self._source is None:
            return
        controls = getattr(self, field)
        try:
            values = None if not any(control.text().strip() for control in controls) else tuple(
                whole_number(control.text(), 0, maximum) if control.text().strip() else getattr(self._source, field)[index]
                for index, control in enumerate(controls))
        except ValueError:
            self._invalid()
            return
        self._commit(**{field: values})

    def _reward_changed(self):
        self._commit(extraction_reward=self.reward.currentData())

    def _repair_toggle(self, checked):
        self._commit(repairs=self._source.repairs if checked and self._source is not None else None)

    def _add_repair(self):
        key = self.repair_item.currentData()
        if key is not None:
            current = self.controller.draft.item_settings
            self._commit(repairs=tuple(current.repairs or ()) + (RepairEntry(key, 1, 0, 1),))

    def _remove_repairs(self):
        selected = {index.row() for index in self.repairs.selectionModel().selectedRows()}
        current = self.controller.draft.item_settings
        if current is not None and current.repairs is not None:
            self._commit(repairs=tuple(entry for index, entry in enumerate(current.repairs) if index not in selected))

    def _repair_changed(self, _row, column):
        if self._syncing or column == 0:
            return
        try:
            entries = tuple(RepairEntry(int(self.repairs.item(row, 0).data(Qt.UserRole)),
                whole_number(self.repairs.item(row, 1).text(), 0, 65535),
                whole_number(self.repairs.item(row, 2).text(), 0, 255),
                whole_number(self.repairs.item(row, 3).text(), 1, (1 << 64) - 1))
                for row in range(self.repairs.rowCount()))
        except (ValueError, AttributeError):
            self._invalid()
            return
        self._commit(repairs=entries)

    def _action_toggle(self, checked):
        self._commit(use_actions=self._source.use_actions if checked and self._source is not None else None)

    def _add_action(self):
        key = self.use_action.currentData()
        current = self.controller.draft.item_settings
        if key is not None and current is not None and key not in (current.use_actions or ()):
            self._commit(use_actions=tuple(current.use_actions or ()) + (key,))

    def _remove_actions(self):
        selected = {index.row() for index in self.actions.selectionModel().selectedRows()}
        current = self.controller.draft.item_settings
        if current is not None and current.use_actions is not None:
            self._commit(use_actions=tuple(key for index, key in enumerate(current.use_actions) if index not in selected))

    def _amount_changed(self, row, column):
        if self._syncing or column != 4:
            return
        amount = self._quantities[row]
        text = self.amounts.item(row, 4).text().strip()
        try:
            minimum, maximum = (-(1 << 63), (1 << 63) - 1) if amount.kind == 'stat' else (0, (1 << 64) - 1)
            value = whole_number(text, minimum, maximum) if text else None
        except ValueError:
            self._invalid()
            return
        existing = self.controller.draft.item_settings or ItemSettings()
        edits = tuple(edit for edit in existing.quantities if (edit.kind, edit.level, edit.key) != (amount.kind, amount.level, amount.key))
        if value is not None:
            edits += (QuantityEdit(amount.kind, amount.key, value, amount.level),)
        self._commit(quantities=edits)
