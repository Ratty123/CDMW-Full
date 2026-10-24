"""Raw stat-family and equipment passive controls for item.stats@1."""
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QHeaderView, QHBoxLayout,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from cdmw.core.item_layout import read_item_layout
from cdmw.core.iteminfo_stats import read_item_stats, stat_list_spans
from cdmw.domain.new_item.item_stats import ItemStatSettings, StatOverride, PassiveSkill, encode_stat_settings
from cdmw.services.active_ui_translation import translate_active_ui_text
from cdmw.ui.new_item.choice_model import set_choice_rows
from cdmw.ui.new_item.item_settings_editor import whole_number


class ItemStatsEditor(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.index = None
        self._row = None
        self._snapshot_source = None
        self._statistics = ()
        self._display = ()
        self._skills = ()
        self._available = False
        self._syncing = False
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel('Regeneration and level-based stats'))
        top.addStretch(1)
        self.reset = QPushButton('Reset this page')
        self.reset.clicked.connect(self._reset)
        top.addWidget(self.reset)
        layout.addLayout(top)
        self.statistics = self._table(('Kind', 'Level', 'Stat', 'Template value', 'Override'))
        self.statistics.setToolTip('Regeneration counters are signed 64-bit values. Level-based parameters are raw bytes (0–255), not flat stat amounts. Blank inherits. Add or remove entries within existing enhancement levels.')
        self.statistics.cellChanged.connect(self._stat_changed)
        layout.addWidget(self.statistics, 1)
        stats_actions = QHBoxLayout()
        self.stat_kind, self.stat_level, self.stat_key = QComboBox(), QComboBox(), QComboBox()
        for label, kind in (('Regeneration maximum', 'regeneration_max'), ('Regeneration', 'regeneration'),
                            ('Level-based parameter', 'level_stat')):
            self.stat_kind.addItem(label, kind)
        stats_actions.addWidget(self.stat_kind)
        stats_actions.addWidget(self.stat_level)
        stats_actions.addWidget(self.stat_key, 1)
        self.add_stat = QPushButton('Add stat entry')
        self.add_stat.clicked.connect(self._add_stat)
        stats_actions.addWidget(self.add_stat)
        self.remove_stat = QPushButton('Remove stat entries')
        self.remove_stat.clicked.connect(self._remove_stats)
        stats_actions.addWidget(self.remove_stat)
        layout.addLayout(stats_actions)
        self.override_passives = QCheckBox('Override equipment passive skills')
        self.override_passives.toggled.connect(self._toggle_passives)
        layout.addWidget(self.override_passives)
        self.passives = self._table(('Passive skill', 'Skill level'))
        self.passives.cellChanged.connect(self._skill_changed)
        layout.addWidget(self.passives, 1)
        actions = QHBoxLayout()
        self.skill = QComboBox()
        actions.addWidget(self.skill, 1)
        self.add = QPushButton('Add passive skill')
        self.add.clicked.connect(self._add)
        actions.addWidget(self.add)
        self.remove = QPushButton('Remove selected')
        self.remove.clicked.connect(self._remove)
        actions.addWidget(self.remove)
        layout.addLayout(actions)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.setToolTip('These raw settings require item.stats version 1. Referenced status and skill tables are verified; gameplay meanings remain unverified.')

    @staticmethod
    def _table(headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        return table

    def rebuild(self, index=None):
        snapshot, draft = self.controller.snapshot, self.controller.draft
        row = snapshot.rows.get(draft.template_key) if snapshot is not None else None
        if row is not self._row or snapshot is not self._snapshot_source:
            self._row = row
            self._snapshot_source = snapshot
            try:
                self._statistics, self._skills = read_item_stats(row.raw) if row is not None else ((), ())
                self._available = row is not None
                levels = sorted({level for _kind, level, _span in stat_list_spans(read_item_layout(row.raw))}) if row is not None else ()
                self.stat_level.clear()
                for level in levels:
                    self.stat_level.addItem(str(level), level)
                set_choice_rows(self.stat_key, tuple((name, key) for key, name in sorted(snapshot.status_names.items())) if row is not None else ())
            except ValueError:
                self._statistics, self._skills, self._available = (), (), False
        self.setEnabled(self._available)
        if not self._available:
            self._display = ()
            self._syncing = True
            try:
                self.statistics.setRowCount(0)
                self.passives.setRowCount(0)
            finally:
                self._syncing = False
            return
        self._syncing = True
        try:
            if index is not self.index:
                self.index = index
                set_choice_rows(self.skill, tuple((f'{name} ({key})', key) for key, name in index.skills) if index else ())
            settings = draft.stat_settings or ItemStatSettings()
            overrides = {(edit.kind, edit.level, edit.key): edit.value for edit in settings.statistics}
            labels = {'regeneration_max': translate_active_ui_text('Regeneration maximum'),
                      'regeneration': translate_active_ui_text('Regeneration'),
                      'level_stat': translate_active_ui_text('Level-based parameter')}
            source_keys = {(stat.kind, stat.level, stat.key) for stat in self._statistics}
            self._display = self._statistics + tuple(StatOverride(edit.kind, edit.level, edit.key, 0)
                for edit in settings.statistics if (edit.kind, edit.level, edit.key) not in source_keys)
            self.statistics.setRowCount(len(self._display))
            for number, stat in enumerate(self._display):
                identity = stat.kind, stat.level, stat.key
                value = overrides.get(identity)
                text_value = translate_active_ui_text('Remove') if identity in overrides and value is None else '' if value is None else str(value)
                for column, text in enumerate((labels[stat.kind], str(stat.level),
                        snapshot.status_names.get(stat.key, str(stat.key)), '' if identity not in source_keys else str(stat.value), text_value)):
                    item = QTableWidgetItem(text)
                    if column != 4:
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.statistics.setItem(number, column, item)
            self.override_passives.setChecked(settings.passive_skills is not None)
            skills = self._skills if settings.passive_skills is None else settings.passive_skills
            names = dict(index.skills) if index else {}
            self.passives.setRowCount(len(skills))
            for number, skill in enumerate(skills):
                key = QTableWidgetItem(f'{names.get(skill.skill_key, skill.skill_key)} ({skill.skill_key})')
                key.setData(Qt.UserRole, skill.skill_key)
                key.setFlags(key.flags() & ~Qt.ItemIsEditable)
                self.passives.setItem(number, 0, key)
                level = QTableWidgetItem(str(skill.level))
                if settings.passive_skills is None:
                    level.setFlags(level.flags() & ~Qt.ItemIsEditable)
                self.passives.setItem(number, 1, level)
            self.add.setEnabled(settings.passive_skills is not None and self.skill.count() > 0)
            self.remove.setEnabled(settings.passive_skills is not None)
            self.add_stat.setEnabled(self.stat_level.count() > 0 and self.stat_key.count() > 0)
        finally:
            self._syncing = False

    def _commit(self, **values):
        if self._syncing or not self._available:
            return
        candidate = replace(self.controller.draft.stat_settings or ItemStatSettings(), **values)
        if candidate == ItemStatSettings():
            candidate = None
        try:
            if candidate is not None:
                encode_stat_settings(candidate)
        except (ValueError, TypeError):
            self._invalid()
            return
        self.controller.draft.stat_settings = candidate
        self.controller.invalidate_plan()
        self.message.clear()
        self.rebuild(self.index)

    def _invalid(self):
        self.controller.invalidate_plan()
        self.rebuild(self.index)
        self.message.setText('Invalid stat or passive skill value.')

    def _reset(self):
        self.controller.draft.stat_settings = None
        self.controller.invalidate_plan()
        self.message.clear()
        self.rebuild(self.index)

    def _stat_changed(self, number, column):
        if self._syncing or column != 4:
            return
        stat = self._display[number]
        text = self.statistics.item(number, 4).text().strip()
        try:
            minimum, maximum = (0, 255) if stat.kind == 'level_stat' else (-(1 << 63), (1 << 63) - 1)
            value = whole_number(text, minimum, maximum) if text else None
        except ValueError:
            self._invalid()
            return
        settings = self.controller.draft.stat_settings or ItemStatSettings()
        edits = tuple(edit for edit in settings.statistics if (edit.kind, edit.level, edit.key) != (stat.kind, stat.level, stat.key))
        if value is not None:
            edits += (StatOverride(stat.kind, stat.level, stat.key, value),)
        self._commit(statistics=edits)

    def _add_stat(self):
        kind, level, key = self.stat_kind.currentData(), self.stat_level.currentData(), self.stat_key.currentData()
        if level is None or key is None:
            return
        settings = self.controller.draft.stat_settings or ItemStatSettings()
        identity = kind, level, key
        if any((row.kind, row.level, row.key) == identity for row in self._display):
            return
        self._commit(statistics=settings.statistics + (StatOverride(kind, level, key, 0),))

    def _remove_stats(self):
        selected = {index.row() for index in self.statistics.selectionModel().selectedRows()}
        identities = {(self._display[number].kind, self._display[number].level, self._display[number].key) for number in selected}
        settings = self.controller.draft.stat_settings or ItemStatSettings()
        edits = tuple(edit for edit in settings.statistics if (edit.kind, edit.level, edit.key) not in identities)
        source_keys = {(row.kind, row.level, row.key) for row in self._statistics}
        edits += tuple(StatOverride(kind, level, key, None) for kind, level, key in sorted(identities & source_keys))
        self._commit(statistics=edits)

    def _toggle_passives(self, checked):
        self._commit(passive_skills=self._skills if checked else None)

    def _add(self):
        key = self.skill.currentData()
        settings = self.controller.draft.stat_settings
        if key is not None and settings is not None and key not in {skill.skill_key for skill in settings.passive_skills or ()}:
            self._commit(passive_skills=tuple(settings.passive_skills or ()) + (PassiveSkill(key, 1),))

    def _remove(self):
        selected = {index.row() for index in self.passives.selectionModel().selectedRows()}
        settings = self.controller.draft.stat_settings
        if settings is not None and settings.passive_skills is not None:
            self._commit(passive_skills=tuple(skill for number, skill in enumerate(settings.passive_skills) if number not in selected))

    def _skill_changed(self, _row, column):
        if self._syncing or column != 1:
            return
        try:
            skills = tuple(PassiveSkill(int(self.passives.item(row, 0).data(Qt.UserRole)),
                whole_number(self.passives.item(row, 1).text(), 0, 0xffffffff)) for row in range(self.passives.rowCount()))
        except (ValueError, AttributeError):
            self._invalid()
            return
        self._commit(passive_skills=skills)
