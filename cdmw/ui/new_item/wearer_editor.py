"""Visible, additive wearer support on Create New Item's Template page.

Humanoid equipment gets the player controls (Kliff, Damiane, Oongka). Gear for
horses, pets, ridable creatures, the dragon, ships, wagons and the war machine is
worn by creatures or hulls; for those templates the page shows who wears them,
read-only (P8), and the player controls are hidden.
"""
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QCheckBox, QGroupBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from cdmw.services.active_ui_translation import translate_active_ui_text as tr
from cdmw.services.new_item_wearers import WearerSupportError, set_wearer_support, template_wearers, wearer_support
from cdmw.ui.new_item.wearer_labels import kind_label, wearer_label


class WearerEditor(QGroupBox):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.setTitle('Wearable by')
        self.controller = controller
        layout = QVBoxLayout(self)
        self.note = QLabel('Choose the playable character, even when Character Creator changes their appearance. This does not change model fit.')
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.player_choices = QWidget(self)
        row = QHBoxLayout(self.player_choices)
        row.setContentsMargins(0, 0, 0, 0)
        self.choices = {}
        for character, label in (('kliff', tr('Kliff')), ('damiane', tr('Damiane')), ('oongka', tr('Oongka'))):
            check = QCheckBox(label)
            check.toggled.connect(lambda enabled, name=character: self._changed(name, enabled))
            self.choices[character] = check
            row.addWidget(check)
        row.addStretch(1)
        layout.addWidget(self.player_choices)
        # Read-only: who wears a template that is not for a playable character.
        self.worn_by = QLabel()
        self.worn_by.setObjectName('new_item_worn_by')
        self.worn_by.setWordWrap(True)
        self.worn_by.hide()
        layout.addWidget(self.worn_by)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        controller.template_changed.connect(self.rebuild)
        controller.snapshot_ready.connect(self.rebuild)
        controller.plan_invalidated.connect(self.rebuild)
        self.rebuild()

    def _source(self):
        snapshot = self.controller.snapshot
        key = self.controller.draft.template_key
        return snapshot, snapshot.rows.get(key) if snapshot is not None else None

    @staticmethod
    def _equip_type(snapshot, row):
        name = getattr(snapshot, 'equip_type_name', None)
        return str(name(row) or '') if callable(name) else ''

    def _wearers_text(self, snapshot, row):
        """The read-only lines for a template worn by creatures or hulls, or "" when they cannot be read."""

        try:
            wearers = template_wearers(row, self.controller.draft.behavior_settings, snapshot.stringinfo_texts,
                                       equip_type=self._equip_type(snapshot, row))
        except (ValueError, KeyError, TypeError):
            return ''
        lines = [tr('Template kind: {value_0}').format(value_0=kind_label(wearers.kind))]
        if wearers.unrestricted:
            lines.append(tr('Not limited to particular {value_0}.').format(value_0=wearer_label(wearers.kind)))
        elif wearers.families:
            lines.append(tr('Worn by these {value_0}: {value_1}').format(
                value_0=wearer_label(wearers.kind), value_1=', '.join(wearers.families)))
        lines.append(tr('Worn model entries: {value_0}').format(value_0=wearers.worn_entries))
        return '\n'.join(lines)

    def rebuild(self, *_args):
        snapshot, row = self._source()
        support = None
        worn_by = ''
        message = tr('Select an equipment template to view wearer support.')
        if row is not None:
            try:
                support = wearer_support(row, self.controller.draft.behavior_settings, snapshot.stringinfo_texts,
                                         equip_type=self._equip_type(snapshot, row))
                message = (tr('All characters are already allowed by this template.') if support.unrestricted
                           else tr('Locked choices are already included by the template.'))
            except (ValueError, KeyError, TypeError) as exc:
                reason = str(exc) if isinstance(exc, WearerSupportError) else 'unsupported'
                if reason == 'not_player_equipment':
                    worn_by = self._wearers_text(snapshot, row)
                message = {
                    'not_equipment': tr('Wearer changes are available only for equipment.'),
                    'not_player_equipment': tr('This template is not worn by a playable character, so its wearers cannot be changed here.'),
                    'ambiguous': tr('Wearer changes need one wearable model entry. This template has no single choice.'),
                    'no_selectors': tr('This template has no explicit wearer selectors to extend.'),
                }.get(reason, tr('This template or its prefab overrides cannot be changed safely with this control.'))
        for character, check in self.choices.items():
            with QSignalBlocker(check):
                check.setChecked(support is not None and character in support.selected)
                check.setEnabled(support is not None and character in support.available and character not in support.inherited)
                check.setToolTip(tr('Inherited from the template; this control only adds wearers.')
                    if support is not None and character in support.inherited else
                    tr('This player selector is missing from the loaded game data.')
                    if support is not None and character not in support.available else '')
        creature_gear = bool(worn_by)
        self.note.setVisible(not creature_gear)
        self.player_choices.setVisible(not creature_gear)
        self.worn_by.setText(worn_by)
        self.worn_by.setVisible(creature_gear)
        self.status.setText(message)

    def _changed(self, character, enabled):
        snapshot, row = self._source()
        if row is None:
            self.rebuild()
            return
        try:
            settings = set_wearer_support(row, self.controller.draft.behavior_settings,
                                          snapshot.stringinfo_texts, character, enabled,
                                          equip_type=self._equip_type(snapshot, row))
        except (ValueError, KeyError, TypeError):
            self.rebuild()
            self.status.setText(tr('This template or its prefab overrides cannot be changed safely with this control.'))
            return
        self.controller.draft.behavior_settings = settings
        self.controller.invalidate_plan()
