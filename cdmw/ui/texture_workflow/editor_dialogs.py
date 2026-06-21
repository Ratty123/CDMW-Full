from __future__ import annotations

"""Dialogs used by the standalone Texture Editor UI."""

from typing import Dict, Optional

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QKeySequenceEdit, QVBoxLayout, QWidget

class ShortcutEditorDialog(QDialog):
    def __init__(
        self,
        *,
        shortcuts: Dict[str, str],
        labels: Dict[str, str],
        defaults: Dict[str, str],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Texture Editor Shortcuts")
        self._defaults = defaults
        self._edits: Dict[str, QKeySequenceEdit] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        hint = QLabel("Set the shortcuts you want for common Texture Editor actions.")
        hint.setWordWrap(True)
        hint.setObjectName("HintLabel")
        layout.addWidget(hint)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        for key, label in labels.items():
            edit = QKeySequenceEdit()
            edit.setKeySequence(QKeySequence(shortcuts.get(key, defaults.get(key, ""))))
            self._edits[key] = edit
            form.addRow(label, edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        defaults_button = buttons.addButton("Defaults", QDialogButtonBox.ResetRole)
        defaults_button.clicked.connect(self.reset_to_defaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def reset_to_defaults(self) -> None:
        for key, edit in self._edits.items():
            edit.setKeySequence(QKeySequence(self._defaults.get(key, "")))

    def shortcut_map(self) -> Dict[str, str]:
        return {key: edit.keySequence().toString(QKeySequence.NativeText) for key, edit in self._edits.items()}


__all__ = ["ShortcutEditorDialog"]
