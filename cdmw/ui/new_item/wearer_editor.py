"""Visible, additive wearer support on Create New Item's Template page."""
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QCheckBox, QGroupBox, QHBoxLayout, QLabel, QVBoxLayout

from cdmw.services.active_ui_translation import translate_active_ui_text as tr
from cdmw.services.new_item_wearers import WearerSupportError, set_wearer_support, wearer_support


class WearerEditor(QGroupBox):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.setTitle('Wearable by')
        self.controller = controller
        layout = QVBoxLayout(self)
        self.note = QLabel('Choose the playable character, even when Character Creator changes their appearance. This does not change model fit.')
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        row = QHBoxLayout()
        self.choices = {}
        for character, label in (('kliff', tr('Kliff')), ('damiane', tr('Damiane')), ('oongka', tr('Oongka'))):
            check = QCheckBox(label)
            check.toggled.connect(lambda enabled, name=character: self._changed(name, enabled))
            self.choices[character] = check
            row.addWidget(check)
        row.addStretch(1)
        layout.addLayout(row)
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

    def rebuild(self, *_args):
        snapshot, row = self._source()
        support = None
        message = tr('Select an equipment template to view wearer support.')
        if row is not None:
            try:
                support = wearer_support(row, self.controller.draft.behavior_settings, snapshot.stringinfo_texts)
                message = (tr('All characters are already allowed by this template.') if support.unrestricted
                           else tr('Locked choices are already included by the template.'))
            except (ValueError, KeyError, TypeError) as exc:
                reason = str(exc) if isinstance(exc, WearerSupportError) else 'unsupported'
                message = {
                    'not_equipment': tr('Wearer changes are available only for equipment.'),
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
        self.status.setText(message)

    def _changed(self, character, enabled):
        snapshot, row = self._source()
        if row is None:
            self.rebuild()
            return
        try:
            settings = set_wearer_support(row, self.controller.draft.behavior_settings,
                                          snapshot.stringinfo_texts, character, enabled)
        except (ValueError, KeyError, TypeError):
            self.rebuild()
            self.status.setText(tr('This template or its prefab overrides cannot be changed safely with this control.'))
            return
        self.controller.draft.behavior_settings = settings
        self.controller.invalidate_plan()
