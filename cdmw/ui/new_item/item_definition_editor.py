"""Structured six-area authoring through the existing Qt/native presentation."""
from copy import deepcopy

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QGroupBox, QHBoxLayout,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem, QTreeView, QVBoxLayout, QWidget)

from cdmw.core.item_layout import read_item_layout
from cdmw.core.iteminfo_definition import read_definition_fields, decode_local_string
from cdmw.domain.new_item.item_definition import (ItemDefinitionSettings, FLAGS, NUMBERS, COLLECTIONS,
    SEAL_TARGETS, encode_definition_settings)
from cdmw.services.active_ui_translation import translate_active_ui_text as tr
from cdmw.ui.new_item.choice_model import set_choice_rows
from cdmw.ui.new_item.item_settings_editor import whole_number


def _labels():
    return {
        'knowledge_key': tr('Knowledge link'), 'knowledge_obtain_type': tr('Knowledge obtain type'),
        'packed_item': tr('Packed item'), 'unpacked_item': tr('Unpacked item'), 'drop_npc_item': tr('NPC-drop conversion'),
        'bundles': tr('Bundle entries'), 'dyeable': tr('Dyeable'), 'editable_grime': tr('Editable grime'),
        'housing_only': tr('Housing only'), 'reward_loot': tr('Reward loot'), 'equip_in_clone_actor': tr('Equip in clone actor'),
        'trade_market': tr('Trade market'), 'editor_usable': tr('Editor usable'), 'shield': tr('Shield'),
        'tower_shield': tr('Tower shield'), 'wild': tr('Wild'), 'preorder': tr('Preorder'),
        'average_price': tr('Use average price'), 'save_on_use': tr('Save on use'), 'logout_on_use': tr('Logout on use'),
        'compatibility_hash': tr('Equipment compatibility'), 'occupied_slots': tr('Occupied equipment slots'),
        'sharpness': tr('Sharpness'), 'map_icon': tr('Map icon'), 'map_icon_alert': tr('Map-icon alert'),
        'item_effect': tr('Item effect reference'), 'destroy_effect': tr('Destruction effect reference'),
        'pattern_descriptions': tr('Pattern descriptions'), 'gimmick_key': tr('Gimmick link'), 'gimmick_tags': tr('Gimmick tags'),
        'sealable_items': tr('Sealable item targets'), 'sealable_characters': tr('Sealable character targets'),
        'sealable_gimmicks': tr('Sealable gimmick targets'), 'sealable_tags': tr('Sealable tag targets'),
        'sealable_tribes': tr('Sealable tribe targets'), 'sealable_money': tr('Sealable money values'),
        'all_gimmicks_sealable': tr('All gimmicks sealable'), 'delete_on_gimmick_unlock': tr('Delete on gimmick unlock'),
        'unlock_message': tr('Gimmick unlock message'), 'use_drop_target': tr('Use drop target'),
        'max_drop_subitems': tr('Maximum drop subitems'), 'respawn_value': tr('Respawn timer (raw u64)'),
        'inventory_routing': tr('Inventory routing'), 'faction': tr('Faction costs and prices'),
        'name_hash': tr('Slot name'), 'indexes': tr('Slot indices'), 'minimum': tr('Minimum'), 'maximum': tr('Maximum'),
        'gimmick': tr('Gimmick'), 'limit': tr('Sharpness limit'), 'craft_tool': tr('Craft tool'),
        'regeneration': tr('Regeneration'), 'static': tr('Static counters'), 'parameters': tr('Parameters'),
        'stat': tr('Stat'), 'value': tr('Value'), 'pattern': tr('Pattern'), 'kind': tr('Parameter type'),
        'category': tr('Localization category'), 'key': tr('Localization number'), 'text_key': tr('Localization key'),
        'target_type': tr('Target type'), 'item': tr('Item'), 'count': tr('Count'), 'target': tr('Target'),
        'valid': tr('Enabled'), 'costs': tr('Costs'), 'prices': tr('Prices'), 'tier': tr('Tier'),
    }


class ItemDefinitionEditor(QWidget):
    PATH = Qt.UserRole
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.index = None
        self._snapshot = self._row = self._source = None
        self._syncing = False
        self._editing_cell = False
        self._refresh = QTimer(self)
        self._refresh.setSingleShot(True)
        self._refresh.timeout.connect(self.rebuild)
        self._display = None
        self._nodes = {}
        self._views = {}
        self._view_name = None
        self._english = {}
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.load = QPushButton('Load definition references')
        self.load.clicked.connect(lambda: controller.start_authoring_index('item-definition'))
        self.reset = QPushButton('Reset this page')
        self.reset.clicked.connect(self._reset)
        top.addWidget(self.load); top.addWidget(self.reset); top.addStretch(1)
        layout.addLayout(top)
        selectors = QHBoxLayout()
        self.section = QComboBox()
        set_choice_rows(self.section, ((tr('Text and knowledge'), 'text'), (tr('Linked items and bundles'), 'links'),
            (tr('Item flags'), 'flags'), (tr('Equipment and sharpness'), 'equipment'),
            (tr('Presentation'), 'presentation'), (tr('World and economy'), 'world')))
        self.field = QComboBox()
        self.section.currentIndexChanged.connect(self._section_changed)
        self.field.currentIndexChanged.connect(lambda: self.rebuild())
        selectors.addWidget(self.section); selectors.addWidget(self.field, 1)
        layout.addLayout(selectors)
        self.description = QGroupBox('Secondary description')
        description_layout = QVBoxLayout(self.description)
        self.override_description = QCheckBox('Override secondary description')
        self.override_description.toggled.connect(self._description_toggle)
        self.description_source = QComboBox()
        self.description_source.currentIndexChanged.connect(self._description_source_changed)
        description_layout.addWidget(self.override_description); description_layout.addWidget(self.description_source)
        self.translations = QTableWidget(0, 3)
        self.translations.setHorizontalHeaderLabels(('Language', 'Source (English)', 'Override'))
        self.translations.horizontalHeader().setStretchLastSection(True)
        self.translations.cellChanged.connect(self._description_changed)
        description_layout.addWidget(self.translations)
        self.clear_description = QPushButton('Clear secondary description')
        self.clear_description.clicked.connect(lambda: self._commit(description={'source_item': None, 'texts': {}}))
        description_layout.addWidget(self.clear_description)
        layout.addWidget(self.description)
        self.override = QCheckBox('Override selected field')
        self.override.toggled.connect(self._toggle)
        layout.addWidget(self.override)
        self.tree = QTreeView()
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.model = QStandardItemModel(self.tree)
        self.tree.setModel(self.model)
        self.model.itemChanged.connect(self._changed)
        self.tree.selectionModel().currentChanged.connect(lambda: self._reference_choices())
        layout.addWidget(self.tree, 1)
        actions = QHBoxLayout()
        self.add = QPushButton('Add entry'); self.add.clicked.connect(self._add)
        self.remove = QPushButton('Remove selected'); self.remove.clicked.connect(self._remove)
        self.picker = QComboBox()
        self.use = QPushButton('Use selected value'); self.use.clicked.connect(self._use_reference)
        for widget in (self.add, self.remove, self.picker, self.use): actions.addWidget(widget)
        layout.addLayout(actions)
        self.message = QLabel(); self.message.setWordWrap(True); layout.addWidget(self.message)
        self.setToolTip('These settings require item.definition version 1. Uncheck an override to inherit; an empty overridden list clears it. Counters and selectors are raw source values. References are checked; game and save effects remain unverified.')
        self.tree.setToolTip('Edit the Value column. Select a list to add entries, or select entries to remove them. Use loaded reference choices for known IDs. Respawn and routing values retain unverified raw meanings.')
        self.override_description.setToolTip('A new secondary description needs a source item with an existing secondary-description namespace. The template is used when no other source is selected. Blank language overrides use English or the source text.')
        controller.authoring_index_ready.connect(self._ready)
        controller.authoring_index_failed.connect(self._failed)
        controller.snapshot_ready.connect(self._snapshot_changed)
        controller.busy_changed.connect(lambda busy: self.load.setEnabled(not busy and controller.snapshot is not None))
        self._section_changed()

    def _section_changed(self):
        labels = _labels()
        group = self.section.currentData()
        choices = [(labels[name], name) for name, (_field, section) in FLAGS.items() if section == group]
        choices += [(labels[name], name) for name, (_field, _width, section, _table) in NUMBERS.items() if section == group]
        choices += [(labels[name], name) for name, (_field, _kind, section) in COLLECTIONS.items() if section == group]
        self._syncing = True
        set_choice_rows(self.field, tuple(choices))
        self._syncing = False
        self.rebuild()

    def _snapshot_changed(self):
        self.index = None
        self._snapshot = None
        self.rebuild()

    def _ready(self, kind, index):
        if kind == 'item-definition':
            self.index = index
            self.rebuild()
            self.message.setText('Some optional catalogues are unavailable; other item controls remain usable.' if index.unavailable else '')

    def _failed(self, kind, message):
        if kind == 'item-definition': self.message.setText(message)

    def rebuild(self):
        if self._syncing: return
        if self._editing_cell:
            self._refresh.start(0)
            return
        self._refresh.stop()
        if self._view_name is not None:
            self._views[self._view_name] = (self._selected_path(), tuple(path for path, node in self._nodes.items()
                if self.tree.isExpanded(node.index().siblingAtColumn(0))))
        snapshot, draft = self.controller.snapshot, self.controller.draft
        row = snapshot.rows.get(draft.template_key) if snapshot is not None else None
        if snapshot is not self._snapshot or row is not self._row:
            self._views.clear()
            if snapshot is not self._snapshot: self.index = None
            self._snapshot, self._row = snapshot, row
            self._english = snapshot.english.index() if snapshot is not None else {}
            try: self._source = read_definition_fields(row.raw) if row else None
            except ValueError: self._source = None
        self.setEnabled(self._source is not None)
        self.description.setVisible(self.section.currentData() == 'text')
        self._syncing = True
        try:
            settings = draft.definition_settings or ItemDefinitionSettings()
            name = self.field.currentData()
            self.override.setChecked(name in settings.fields)
            self.tree.setEnabled(name in settings.fields and self._source is not None)
            self._display = deepcopy(settings.fields.get(name, self._source.get(name) if self._source else None))
            self._view_name = name
            current_path, expanded = self._views.get(name, ((), None))
            self.model.clear(); self.model.setHorizontalHeaderLabels((tr('Setting'), tr('Value')))
            self._nodes = {}
            if self._source is not None and name:
                self._build(self.model.invisibleRootItem(), self._display, (), _labels()[name])
                if expanded is None:
                    self.tree.expandToDepth(1)
                else:
                    for path in expanded:
                        if path in self._nodes: self.tree.setExpanded(self._nodes[path].index().siblingAtColumn(0), True)
                node = self._nodes.get(current_path, self._nodes.get(()))
                if node is not None: self.tree.setCurrentIndex(node.index())
                self.tree.resizeColumnToContents(0)
            self._description_rebuild(settings)
        finally: self._syncing = False
        self._reference_choices()

    def _build(self, parent, value, path, label):
        title, cell = QStandardItem(label), QStandardItem()
        title.setEditable(False); cell.setEditable(False)
        title.setData(path, self.PATH); cell.setData(path, self.PATH)
        parent.appendRow((title, cell)); self._nodes[path] = cell
        if isinstance(value, dict):
            labels = _labels()
            for key, child in value.items(): self._build(title, child, path+(key,), labels[key])
        elif isinstance(value, list):
            for number, child in enumerate(value): self._build(title, child, path+(number,), str(number+1))
        elif type(value) is bool:
            cell.setCheckable(True); cell.setCheckState(Qt.Checked if value else Qt.Unchecked)
        elif value is not None:
            cell.setText(str(value)); cell.setEditable(True)

    def _selected_path(self):
        index = self.tree.currentIndex()
        return tuple(index.data(self.PATH) or ()) if index.isValid() else ()

    @staticmethod
    def _at(value, path):
        for part in path: value = value[part]
        return value

    @staticmethod
    def _assign(value, path, replacement):
        if not path: return replacement
        ItemDefinitionEditor._at(value, path[:-1])[path[-1]] = replacement
        return value

    def _commit(self, *, fields=None, description=...):
        if self._syncing or self._source is None: return
        current = self.controller.draft.definition_settings or ItemDefinitionSettings()
        candidate = ItemDefinitionSettings(deepcopy(current.fields if fields is None else fields),
            deepcopy(current.secondary_description if description is ... else description))
        if not candidate.fields and candidate.secondary_description is None: candidate = None
        try:
            if candidate is not None: encode_definition_settings(candidate)
        except (ValueError, TypeError):
            self._invalid(); return
        self.controller.draft.definition_settings = candidate
        if self._editing_cell:
            self._display = deepcopy(candidate.fields[self.field.currentData()])
        self.controller.invalidate_plan(); self.message.clear(); self.rebuild()

    def _field_commit(self, value):
        current = self.controller.draft.definition_settings or ItemDefinitionSettings()
        fields = deepcopy(dict(current.fields)); fields[self.field.currentData()] = value
        self._commit(fields=fields)

    def _invalid(self):
        self.controller.invalidate_plan(); self.rebuild()
        self.message.setText('Invalid definition value, range or duplicate entry.')

    def _toggle(self, checked):
        if self._syncing or self._source is None: return
        name = self.field.currentData()
        current = self.controller.draft.definition_settings or ItemDefinitionSettings()
        fields = deepcopy(dict(current.fields))
        if checked: fields[name] = deepcopy(self._source[name])
        else: fields.pop(name, None)
        self._commit(fields=fields)

    def _changed(self, item):
        if self._syncing or item.column() != 1 or not self.override.isChecked(): return
        path = tuple(item.data(self.PATH) or ())
        original = self._at(self._display, path)
        self._editing_cell = True
        try:
            value = item.checkState() == Qt.Checked if type(original) is bool else (
                whole_number(item.text(), -(1 << 63), (1 << 64)-1) if type(original) is int else item.text())
            changed = self._assign(deepcopy(self._display), path, value)
            if path and path[-1] == 'target_type':
                record = self._at(changed, path[:-1])
                record['target'] = '' if value == 2 else None if value == 5 else (record['target'] if type(record['target']) is int else 0)
            self._field_commit(changed)
        except (ValueError, KeyError, TypeError): self._invalid()
        finally: self._editing_cell = False

    def _reference_kind(self, path):
        name = self.field.currentData()
        if not path:
            if name in NUMBERS:
                return name if name in ('map_icon', 'compatibility_hash') else NUMBERS[name][3]
            return None
        leaf = path[-1]
        if leaf in ('item', 'gimmick', 'craft_tool', 'stat', 'pattern', 'text_key', 'name_hash'):
            return {'item': 'iteminfo', 'gimmick': 'gimmickinfo', 'craft_tool': 'crafttoolinfo', 'stat': 'statusinfo',
                    'pattern': 'patterndescriptioninfo', 'text_key': 'localization', 'name_hash': 'slot'}[leaf]
        if leaf == 'target_type': return 'seal_kind'
        if leaf == 'target':
            record = self._at(self._display, path[:-1]); table = SEAL_TARGETS.get(record['target_type'])
            return table if table not in (None, 'tag') else None
        return None

    def _reference_choices(self):
        if self._syncing: return
        path = self._selected_path()
        kind = self._reference_kind(path) if self._source is not None else None
        rows = ()
        if self.index is not None:
            if kind == 'map_icon': rows = tuple((self._snapshot.stringinfo_texts.get(key, str(key)), key) for key in self.index.map_icons)
            elif kind == 'compatibility_hash': rows = tuple((str(key), key) for key in sorted(self.index.compatibility_hashes))
            elif kind == 'slot': rows = tuple((self._snapshot.stringinfo_texts.get(key, str(key)), key) for key in sorted(self.index.slot_indexes))
            elif kind == 'localization': rows = tuple((key, key) for key in self.index.localizations)
            else: rows = tuple((f'{name} ({key})', key) for key, name in self.index.choices.get(kind, ()))
        if kind == 'seal_kind':
            rows = tuple((tr(label), key) for key, label in enumerate(('Item', 'Gimmick', 'Tag', 'Character', 'Tribe', 'No target')))
        set_choice_rows(self.picker, rows)
        self.use.setEnabled(bool(rows) and self.override.isChecked())
        self.add.setEnabled(self.override.isChecked())
        self.remove.setEnabled(self.override.isChecked())

    def _use_reference(self):
        path, value = self._selected_path(), self.picker.currentData()
        if value is None or not self.override.isChecked(): return
        changed = deepcopy(self._display)
        if self._reference_kind(path) == 'localization':
            self._at(changed, path[:-1]).update(self.index.localizations[value])
        else:
            changed = self._assign(changed, path, value)
            if path and path[-1] == 'target_type':
                record = self._at(changed, path[:-1]); record['target'] = '' if value == 2 else None if value == 5 else 0
        self._field_commit(changed)

    def _list_path(self):
        path = self._selected_path()
        while path:
            if isinstance(self._at(self._display, path), list): return path
            path = path[:-1]
        return () if isinstance(self._display, list) else None

    def _entry(self, path, values):
        name = self.field.currentData()
        def key(table, used=()):
            return next((key for key, _name in self.index.choices.get(table, ()) if key not in used), None) if self.index else None
        if name == 'sharpness':
            chosen = key('statusinfo', {row['stat'] for row in values})
            return {'stat': chosen, 'value': 0} if chosen else None
        if name == 'faction':
            chosen = key('iteminfo', {row['item'] for row in values})
            return {'item': chosen, 'count': 1, 'minimum': 0, 'maximum': 0} if chosen else None
        kind = COLLECTIONS.get(name, (None, None, None))[1]
        if kind == 'patterns' and path: return {'kind': 0, 'category': 0, 'key': 0, 'text_key': ''}
        if kind == 'patterns':
            chosen = key('patterndescriptioninfo', {row['pattern'] for row in values})
            return {'pattern': chosen, 'parameters': []} if chosen else None
        if kind == 'bundles':
            chosen = key('gimmickinfo', {row['gimmick'] for row in values})
            return {'minimum': 1, 'gimmick': chosen} if chosen else None
        if kind == 'slots':
            if path:
                slot = self._at(self._display, path[:-1])
                return next((n for n in sorted(self.index.slot_indexes.get(slot['name_hash'], ())) if n not in values), None) if self.index else None
            chosen = next((n for n in self.index.slot_indexes if n not in {row['name_hash'] for row in values}), None) if self.index else None
            return {'name_hash': chosen, 'indexes': []} if chosen else None
        if kind == 'sealable':
            chosen = key('iteminfo', {row['item'] for row in values if row['target_type'] == 5})
            return {'target_type': 5, 'item': chosen, 'count': 1, 'target': None} if chosen else None
        if kind == 'strings': return next(('tag_'+str(n) for n in range(257) if 'tag_'+str(n) not in values), None)
        if kind == 'u32s': return next((n for n in range(257) if n not in values), None)
        return None

    def _add(self):
        if not self.override.isChecked(): return
        path = self._list_path()
        if path is None: return
        changed = deepcopy(self._display); values = self._at(changed, path); entry = self._entry(path, values)
        if entry is None:
            self.message.setText('Load references and select a list with an available entry.'); return
        values.append(entry); self._field_commit(changed)

    def _remove(self):
        if not self.override.isChecked() or self.field.currentData() == 'inventory_routing': return
        entries = set()
        for index in self.tree.selectionModel().selectedRows():
            path = tuple(index.data(self.PATH) or ())
            for n in range(len(path)-1, -1, -1):
                component = path[n]
                if type(component) is int:
                    entries.add(path[:n+1]); break
        removals = {}
        for path in entries:
            if not any(path[:n] in entries for n in range(1, len(path))):
                removals.setdefault(path[:-1], set()).add(path[-1])
        changed = deepcopy(self._display)
        for path in sorted(removals, key=len, reverse=True):
            values = self._at(changed, path)
            for number in sorted(removals[path], reverse=True): del values[number]
        if removals: self._field_commit(changed)

    def _description_rebuild(self, settings):
        value = settings.secondary_description
        self.override_description.setChecked(value is not None)
        selected = value['source_item'] if value else None
        rows = ((tr('Template'), None),) + (tuple((f'{name} ({key})', key) for key, name in self.index.descriptions) if self.index else ())
        if selected is not None and all(key != selected for _name, key in rows):
            source = self._snapshot.rows.get(selected) if self._snapshot else None
            rows += ((f'{source.string_key} ({selected})' if source else str(selected), selected),)
        set_choice_rows(self.description_source, rows)
        self.description_source.setCurrentIndex(self.description_source.findData(selected))
        self.description_source.setEnabled(value is not None)
        self.clear_description.setEnabled(value is not None)
        languages = self._snapshot.languages if self._snapshot is not None else ()
        self.translations.setRowCount(len(languages))
        self.translations.setEnabled(value is not None)
        source_key = selected or self.controller.draft.template_key
        source = self._snapshot.rows.get(source_key) if self._snapshot else None
        original = ''
        try:
            key = decode_local_string(read_item_layout(source.raw).data('_itemDesc2'))['text_key'] if source else ''
            original = self._english[key].text if key in self._english else ''
        except ValueError: pass
        for row, language in enumerate(languages):
            for column, text in enumerate((language, original, value['texts'].get(language, '') if value else '')):
                item = QTableWidgetItem(text)
                if column != 2: item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.translations.setItem(row, column, item)

    def _description_toggle(self, checked):
        if self._syncing: return
        self._commit(description={'source_item': None, 'texts': {'eng': ''}} if checked else None)

    def _description_source_changed(self):
        if self._syncing or not self.override_description.isChecked(): return
        current = self.controller.draft.definition_settings.secondary_description
        value = deepcopy(current); value['source_item'] = self.description_source.currentData()
        if not value['texts']: value['texts'] = {'eng': ''}
        self._commit(description=value)

    def _description_changed(self, row, column):
        if self._syncing or column != 2 or not self.override_description.isChecked(): return
        value = deepcopy(self.controller.draft.definition_settings.secondary_description)
        language, text = self.translations.item(row, 0).text(), self.translations.item(row, 2).text()
        if text: value['texts'][language] = text
        else: value['texts'].pop(language, None)
        if not value['texts']: value['source_item'] = None
        self._commit(description=value)

    def _reset(self):
        self.controller.draft.definition_settings = None
        self.controller.invalidate_plan(); self.message.clear(); self.rebuild()
