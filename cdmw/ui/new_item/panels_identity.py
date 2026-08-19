"""New Item Studio, panel 2: the new item's identity (names, keys, stem)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
)

from cdmw.domain.new_item.rules import LOCALIZATION_LANGUAGES
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.ui_kit import BLOCK, OK, WARN, NoteLabel, intro_label, note, tinted

LANGUAGE_LABELS = {
    "eng": "English", "kor": "Korean", "jpn": "Japanese", "rus": "Russian", "tur": "Turkish",
    "spa-es": "Spanish (Spain)", "spa-mx": "Spanish (Latin America)", "fre": "French", "ger": "German",
    "ita": "Italian", "pol": "Polish", "por-br": "Portuguese (Brazil)", "zho-tw": "Chinese (Traditional)",
    "zho-cn": "Chinese (Simplified)",
}


class IdentityPanel(QGroupBox):
    def __init__(self, controller: NewItemStudioController, parent=None) -> None:
        super().__init__("2. Identity", parent)
        self._controller = controller
        self._language = "eng"
        self._suggested_name = ""
        layout = QVBoxLayout(self)
        layout.addWidget(intro_label("The internal name for the tables, and the name and description players read, per language."))
        form = QFormLayout()
        self.internal_name = QLineEdit()
        self.internal_name.setPlaceholderText("ASCII letters, digits and underscores; unique, e.g. Ziane_Clone_OneHandSword")
        self.internal_name.textChanged.connect(self._store_internal_name)
        form.addRow("Internal name:", self.internal_name)
        self.item_key = QSpinBox()
        self.item_key.setRange(0, 0x7FFFFFFF)
        self.item_key.setSpecialValueText("allocate automatically")
        self.item_key.setToolTip("Leave at 0 to take the next free key from 1990000; the range the in-game-verified clones used.")
        self.item_key.valueChanged.connect(self._store_item_key)
        form.addRow("Item key:", self.item_key)
        self.stem = QLineEdit()
        self.stem.setPlaceholderText("allocated automatically, e.g. cd_phm_01_sword_9109")
        self.stem.setToolTip("Only used when the item gets its own model files or icon; leave empty to have one suggested from the template's stem.")
        self.stem.textChanged.connect(self._store_stem)
        form.addRow("Model stem:", self.stem)
        layout.addLayout(form)

        names = QGroupBox("Names and descriptions")
        # one form, so the name and the description carry labels like the fields above them
        names_layout = QFormLayout(names)
        names_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.language = QComboBox()
        for code in LOCALIZATION_LANGUAGES:
            self.language.addItem(f"{LANGUAGE_LABELS.get(code, code)} ({code})", code)
        self.language.currentIndexChanged.connect(self._switch_language)
        names_layout.addRow("Language:", self.language)
        self.display_name = QLineEdit()
        self.display_name.setPlaceholderText("Shown in game; English is required, other languages fall back to it")
        self.display_name.textChanged.connect(self._store_display_name)
        names_layout.addRow("Name:", self.display_name)
        self.description = QPlainTextEdit()
        self.description.setPlaceholderText("Description shown in game; empty keeps the template's description in this language")
        self.description.setMinimumHeight(72)
        self.description.setMaximumHeight(120)
        self.description.textChanged.connect(self._store_description)
        names_layout.addRow("Description:", self.description)
        layout.addWidget(names)

        checks = QGroupBox("Checks")
        checks_layout = QVBoxLayout(checks)
        self.issues = NoteLabel("")
        checks_layout.addWidget(self.issues)
        self.issues_ok = QLabel(tinted("Nothing blocks the plan.", OK))
        checks_layout.addWidget(self.issues_ok)
        layout.addWidget(checks)
        layout.addStretch(1)
        controller.template_changed.connect(self._template_changed)

    # ------------------------------------------------------------------ draft

    def _store_internal_name(self, text: str) -> None:
        self._controller.draft.internal_name = str(text)
        self.refresh_issues()

    def _store_item_key(self, value: int) -> None:
        self._controller.draft.item_key = int(value) or None
        self.refresh_issues()

    def _store_stem(self, text: str) -> None:
        self._controller.draft.stem = str(text)
        self.refresh_issues()

    def _switch_language(self, _index: int) -> None:
        code = self.language.currentData()
        self._language = str(code or "eng")
        draft = self._controller.draft
        self.display_name.blockSignals(True)
        self.description.blockSignals(True)
        try:
            self.display_name.setText(draft.display_names.get(self._language, ""))
            self.description.setPlainText(draft.descriptions.get(self._language, ""))
        finally:
            self.display_name.blockSignals(False)
            self.description.blockSignals(False)

    def _store_display_name(self, text: str) -> None:
        self._controller.draft.display_names[self._language] = str(text)
        self.refresh_issues()

    def _store_description(self) -> None:
        self._controller.draft.descriptions[self._language] = self.description.toPlainText()

    def _template_changed(self, _key: object) -> None:
        self.stem.blockSignals(True)
        self.item_key.blockSignals(True)
        try:
            self.stem.setText("")
            self.item_key.setValue(0)
        finally:
            self.stem.blockSignals(False)
            self.item_key.blockSignals(False)
        # a name to start from: the template's with a suffix no item has, so the first
        # thing the reader sees is not "already exists"
        current = self.internal_name.text().strip()
        if not current or current == self._suggested_name or current == self._controller.template_name():
            suggestion = self._controller.suggest_internal_name()
            if suggestion:
                self._suggested_name = suggestion
                self.internal_name.setText(suggestion)
        self.refresh_issues()

    def refresh_issues(self) -> None:
        issues = self._controller.validate()
        blocked = [issue for issue in issues if issue.is_error]
        self.issues_ok.setVisible(not blocked)
        if not issues:
            self.issues.set_lines([])
            return
        ordered = sorted(issues, key=lambda issue: 0 if issue.is_error else 1)
        lines = [note(f"Blocked: {issue.message}", BLOCK) if issue.is_error else note(f"Note: {issue.message}", WARN) for issue in ordered[:8]]
        if len(issues) > 8:
            lines.append(note(f"... {len(issues) - 8} more", None))
        self.issues.set_lines(lines)

    def set_stem_enabled(self, enabled: bool) -> None:
        self.stem.setEnabled(bool(enabled))


__all__ = ["IdentityPanel", "LANGUAGE_LABELS"]
