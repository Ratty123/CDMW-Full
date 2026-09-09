"""New Item Studio, panel 2: the new item's identity (names, keys, stem)."""

from __future__ import annotations

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.new_item.rules import LOCALIZATION_LANGUAGES
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.ui_kit import BLOCK, OK, WARN, NoteLabel, note

LANGUAGE_LABELS = {
    "eng": "English", "kor": "Korean", "jpn": "Japanese", "rus": "Russian", "tur": "Turkish",
    "spa-es": "Spanish (Spain)", "spa-mx": "Spanish (Latin America)", "fre": "French", "ger": "German",
    "ita": "Italian", "pol": "Polish", "por-br": "Portuguese (Brazil)", "zho-tw": "Chinese (Traditional)",
    "zho-cn": "Chinese (Simplified)", "ara": "Arabic",
}


class IdentityPanel(QGroupBox):
    def __init__(self, controller: NewItemStudioController, parent=None) -> None:
        super().__init__("2. Identity", parent)
        self._controller = controller
        self._language = "eng"
        self._suggested_name = ""
        self._manual_item_key = 0
        self._manual_stem = ""
        outer = QVBoxLayout(self)
        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.workspace_splitter.setChildrenCollapsible(False)
        outer.addWidget(self.workspace_splitter, 1)
        self.editor = QWidget()
        layout = QVBoxLayout(self.editor)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        editor_scroll = QScrollArea()
        editor_scroll.setWidgetResizable(True)
        editor_scroll.setFrameShape(QScrollArea.NoFrame)
        editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        editor_scroll.setWidget(self.editor)
        self.workspace_splitter.addWidget(editor_scroll)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.internal_name = QLineEdit()
        self.internal_name.setClearButtonEnabled(True)
        self.internal_name.setMaxLength(64)
        self.internal_name.setValidator(QRegularExpressionValidator(QRegularExpression(r"[A-Za-z][A-Za-z0-9_]{0,63}"), self.internal_name))
        self.internal_name.setPlaceholderText("ASCII letters, digits and underscores; unique, e.g. Equipment_Clone")
        self.internal_name.setToolTip("ASCII letters, digits and underscores; unique, e.g. Equipment_Clone")
        self.internal_name.textChanged.connect(self._store_internal_name)
        internal_row = QHBoxLayout()
        internal_row.setContentsMargins(0, 0, 0, 0)
        internal_row.addWidget(self.internal_name, 1)
        self.internal_name_state = self._state_icon()
        internal_row.addWidget(self.internal_name_state)
        form.addRow("Internal name:", internal_row)

        self.item_key_manual = QCheckBox("Manual")
        self.item_key = QSpinBox()
        self.item_key.setRange(0, 0x7FFFFFFF)
        self.item_key.setSpecialValueText("allocate automatically")
        self.item_key.setGroupSeparatorShown(True)
        self.item_key.setToolTip("Leave at 0 to take the next free key from 1990000; the range the in-game-verified clones used.")
        self.item_key_manual.setToolTip(self.item_key.toolTip())
        self.item_key.setEnabled(False)
        self.item_key.valueChanged.connect(self._store_item_key)
        self.item_key_manual.toggled.connect(self._item_key_manual_changed)
        item_key_row = QHBoxLayout()
        item_key_row.setContentsMargins(0, 0, 0, 0)
        item_key_row.addWidget(self.item_key_manual)
        item_key_row.addWidget(self.item_key, 1)
        self.item_key_state = self._state_icon()
        item_key_row.addWidget(self.item_key_state)
        form.addRow("Item key:", item_key_row)

        self.stem_manual = QCheckBox("Manual")
        self.stem = QLineEdit()
        self.stem.setClearButtonEnabled(True)
        self.stem.setMaxLength(64)
        self.stem.setValidator(QRegularExpressionValidator(QRegularExpression(r"[a-z0-9][a-z0-9_]{0,63}"), self.stem))
        self.stem.setPlaceholderText("Allocated automatically from the template model")
        self.stem.setToolTip("Only used when the item gets its own model files or icon; leave empty to have one suggested from the template's stem.")
        self.stem_manual.setToolTip(self.stem.toolTip())
        self.stem.setEnabled(False)
        self.stem.textChanged.connect(self._store_stem)
        self.stem_manual.toggled.connect(self._stem_manual_changed)
        stem_row = QHBoxLayout()
        stem_row.setContentsMargins(0, 0, 0, 0)
        stem_row.addWidget(self.stem_manual)
        stem_row.addWidget(self.stem, 1)
        self.stem_state = self._state_icon()
        stem_row.addWidget(self.stem_state)
        form.addRow("Model stem:", stem_row)
        self.identifiers = QGroupBox("Technical identifiers")
        identifiers_layout = QVBoxLayout(self.identifiers)
        self.identifier_fields = QWidget()
        self.identifier_fields.setLayout(form)
        self.identifiers_toggle = QToolButton()
        self.identifiers_toggle.setText("Internal name and manual identifiers")
        self.identifiers_toggle.setCheckable(True)
        self.identifiers_toggle.setAutoRaise(True)
        self.identifiers_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.identifiers_toggle.setArrowType(Qt.RightArrow)
        self.identifiers_toggle.toggled.connect(self.identifier_fields.setVisible)
        self.identifiers_toggle.toggled.connect(
            lambda expanded: self.identifiers_toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        )
        identifiers_layout.addWidget(self.identifiers_toggle)
        self.identifier_summary = QLabel("")
        self.identifier_summary.setWordWrap(True)
        identifiers_layout.addWidget(self.identifier_summary)
        identifiers_layout.addWidget(self.identifier_fields)
        self.identifier_fields.hide()

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
        self.description.setPlaceholderText("Item description; unspecified languages use English when provided")
        self.description.setMinimumHeight(72)
        self.description.setMaximumHeight(120)
        self.description.textChanged.connect(self._store_description)
        names_layout.addRow("Description:", self.description)
        layout.addWidget(names)
        layout.addWidget(self.identifiers)

        checks = QGroupBox("Checks")
        checks_layout = QVBoxLayout(checks)
        self.issues = NoteLabel("")
        checks_layout.addWidget(self.issues)
        self.issues_ok = QLabel("Identity is ready.")
        self.issues_ok.setObjectName("HintLabel")
        self.issues_ok.setProperty("healthState", "healthy")
        checks_layout.addWidget(self.issues_ok)
        layout.addWidget(checks)
        layout.addStretch(1)
        self.preview_group = QGroupBox("Item presentation")
        self.preview_group.setMinimumWidth(320)
        preview_layout = QVBoxLayout(self.preview_group)
        self.preview_holder = QWidget(self.preview_group)
        self.preview_holder_layout = QVBoxLayout(self.preview_holder)
        self.preview_holder_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.addWidget(self.preview_holder, 1)
        self.presentation_name = QLabel("")
        self.presentation_name.setTextFormat(Qt.TextFormat.PlainText)
        self.presentation_name.setWordWrap(True)
        self.presentation_description = QLabel("")
        self.presentation_description.setTextFormat(Qt.TextFormat.PlainText)
        self.presentation_description.setWordWrap(True)
        self.display_name.textChanged.connect(self.presentation_name.setText)
        preview_layout.addWidget(self.presentation_name)
        preview_layout.addWidget(self.presentation_description)
        self.workspace_splitter.addWidget(self.preview_group)
        self.workspace_splitter.setStretchFactor(0, 3)
        self.workspace_splitter.setStretchFactor(1, 2)
        self.workspace_splitter.setSizes((720, 480))
        controller.template_changed.connect(self._template_changed)
        self._refresh_identity_states(())

    # ------------------------------------------------------------------ draft

    def _state_icon(self) -> QLabel:
        label = QLabel(self)
        label.setAlignment(Qt.AlignCenter)
        label.setFixedWidth(20)
        return label

    def _set_identity_state(self, label: QLabel, state: str, tooltip: str) -> None:
        standard = {
            "auto": QStyle.StandardPixmap.SP_BrowserReload,
            OK: QStyle.StandardPixmap.SP_DialogApplyButton,
            WARN: QStyle.StandardPixmap.SP_MessageBoxWarning,
            BLOCK: QStyle.StandardPixmap.SP_MessageBoxCritical,
        }[state]
        label.setPixmap(self.style().standardIcon(standard).pixmap(16, 16))
        label.setProperty("identityState", state)
        label.setToolTip(str(tooltip or ""))

    @staticmethod
    def _field_issue(issues: tuple, field: str):
        matching = [issue for issue in issues if issue.field == field]
        return next((issue for issue in matching if issue.is_error), matching[0] if matching else None)

    def _refresh_identity_states(self, issues: tuple) -> None:
        self.identifier_summary.setText(self.internal_name.text())
        self.presentation_name.setText(self.display_name.text())
        self.presentation_description.setText(self.description.toPlainText())
        internal_issue = self._field_issue(issues, "internal_name")
        if internal_issue is not None:
            self._set_identity_state(self.internal_name_state, BLOCK if internal_issue.is_error else WARN, internal_issue.message)
        elif self.internal_name.text().strip():
            self._set_identity_state(self.internal_name_state, OK, self.internal_name.toolTip())
        else:
            self._set_identity_state(self.internal_name_state, WARN, self.internal_name.toolTip())

        item_issue = self._field_issue(issues, "item_key")
        if not self.item_key_manual.isChecked():
            self._set_identity_state(self.item_key_state, "auto", self.item_key.toolTip())
        elif item_issue is not None:
            self._set_identity_state(self.item_key_state, BLOCK if item_issue.is_error else WARN, item_issue.message)
        else:
            self._set_identity_state(self.item_key_state, OK, self.item_key.toolTip())

        stem_issue = self._field_issue(issues, "stem")
        if not self.stem_manual.isChecked():
            self._set_identity_state(self.stem_state, "auto", self.stem.toolTip())
        elif stem_issue is not None:
            self._set_identity_state(self.stem_state, BLOCK if stem_issue.is_error else WARN, stem_issue.message)
        else:
            self._set_identity_state(self.stem_state, OK, self.stem.toolTip())

    def _store_internal_name(self, text: str) -> None:
        self._controller.draft.internal_name = str(text)
        self._controller.invalidate_plan()
        self.refresh_issues()

    def _store_item_key(self, value: int) -> None:
        if not self.item_key_manual.isChecked():
            return
        self._manual_item_key = int(value)
        self._controller.draft.item_key = int(value) or None
        self._controller.invalidate_plan()
        self.refresh_issues()

    def _store_stem(self, text: str) -> None:
        if not self.stem_manual.isChecked():
            return
        self._manual_stem = str(text)
        self._controller.draft.stem = str(text)
        self._controller.invalidate_plan()
        self.refresh_issues()

    def _item_key_manual_changed(self, manual: bool) -> None:
        self.item_key.setEnabled(bool(manual))
        if manual:
            suggested_key, _suggested_stem = self._controller.suggest_identity_allocations()
            value = self._manual_item_key or int(suggested_key or 1_990_000)
            self.item_key.blockSignals(True)
            try:
                self.item_key.setMinimum(1)
                self.item_key.setSpecialValueText("")
                self.item_key.setValue(value)
            finally:
                self.item_key.blockSignals(False)
            self._controller.draft.item_key = value
        else:
            self._manual_item_key = int(self.item_key.value() or self._manual_item_key)
            self.item_key.blockSignals(True)
            try:
                self.item_key.setMinimum(0)
                self.item_key.setSpecialValueText("allocate automatically")
                self.item_key.setValue(0)
            finally:
                self.item_key.blockSignals(False)
            self._controller.draft.item_key = None
        self._controller.invalidate_plan()
        self.refresh_issues()

    def _stem_manual_changed(self, manual: bool) -> None:
        self.stem.setEnabled(bool(manual))
        if manual:
            _suggested_key, suggested_stem = self._controller.suggest_identity_allocations()
            value = self._manual_stem or str(suggested_stem or "")
            self.stem.blockSignals(True)
            try:
                self.stem.setText(value)
            finally:
                self.stem.blockSignals(False)
            self._controller.draft.stem = value
        else:
            self._manual_stem = self.stem.text().strip() or self._manual_stem
            self.stem.blockSignals(True)
            try:
                self.stem.setText("")
            finally:
                self.stem.blockSignals(False)
            self._controller.draft.stem = ""
        self._controller.invalidate_plan()
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
        self.presentation_name.setText(self.display_name.text())
        self.presentation_description.setText(self.description.toPlainText())

    def _store_display_name(self, text: str) -> None:
        self._controller.draft.display_names[self._language] = str(text)
        self._controller.invalidate_plan()
        self.refresh_issues()

    def _store_description(self) -> None:
        self._controller.draft.descriptions[self._language] = self.description.toPlainText()
        self.presentation_description.setText(self.description.toPlainText())
        self._controller.invalidate_plan()

    def _template_changed(self, _key: object) -> None:
        self.stem.blockSignals(True)
        self.item_key.blockSignals(True)
        self.stem_manual.blockSignals(True)
        self.item_key_manual.blockSignals(True)
        try:
            self._manual_stem = ""
            self._manual_item_key = 0
            self.stem_manual.setChecked(False)
            self.item_key_manual.setChecked(False)
            self.stem.setText("")
            self.item_key.setMinimum(0)
            self.item_key.setSpecialValueText("allocate automatically")
            self.item_key.setValue(0)
            self.stem.setEnabled(False)
            self.item_key.setEnabled(False)
        finally:
            self.stem.blockSignals(False)
            self.item_key.blockSignals(False)
            self.stem_manual.blockSignals(False)
            self.item_key_manual.blockSignals(False)
        # a name to start from: the template's with a suffix no item has, so the first
        # thing the reader sees is not "already exists"
        current = self.internal_name.text().strip()
        if not current or current == self._suggested_name or current == self._controller.template_name():
            suggestion = self._controller.suggest_internal_name()
            if suggestion:
                self._suggested_name = suggestion
                # Template selection already invalidated the plan. Publishing this
                # programmatic seed through textChanged used to invalidate and validate
                # the same draft again before the template signal had finished.
                self.internal_name.blockSignals(True)
                try:
                    self.internal_name.setText(suggestion)
                finally:
                    self.internal_name.blockSignals(False)
                self._controller.draft.internal_name = suggestion
        self.refresh_issues()

    def refresh_issues(self) -> tuple:
        """Show identity issues and return all issues for the workflow header."""

        issues = self._controller.validate()
        self._refresh_identity_states(issues)
        identity_issues = tuple(
            issue for issue in issues
            if issue.field.split(".", 1)[0] in {"internal_name", "item_key", "stem", "display_names", "descriptions"}
        )
        blocked = [issue for issue in identity_issues if issue.is_error]
        self.issues_ok.setVisible(not blocked)
        if not identity_issues:
            self.issues.set_lines([])
            return issues
        ordered = sorted(identity_issues, key=lambda issue: 0 if issue.is_error else 1)
        lines = [note(f"Blocked: {issue.message}", BLOCK) if issue.is_error else note(f"Note: {issue.message}", WARN) for issue in ordered[:8]]
        if len(identity_issues) > 8:
            lines.append(note(f"... {len(identity_issues) - 8} more", None))
        self.issues.set_lines(lines)
        return issues

    def mount_preview(self, preview: QWidget) -> None:
        """Present the already resident item preview without requesting new content."""
        if preview.parentWidget() is not self.preview_holder:
            self.preview_holder_layout.addWidget(preview, 1)

    def set_stem_enabled(self, enabled: bool) -> None:
        self.stem_manual.setEnabled(bool(enabled))
        self.stem.setEnabled(bool(enabled) and self.stem_manual.isChecked())


__all__ = ["IdentityPanel", "LANGUAGE_LABELS"]
