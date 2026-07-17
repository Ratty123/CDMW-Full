"""Read-only original, patched, and diff views for the PAC XML editor."""

from __future__ import annotations

import difflib

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QTabWidget, QVBoxLayout, QWidget


class PacXmlSourceChangesView(QWidget):
    def __init__(self, original_text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PacXmlSourceChangesTab")
        self._original_text = str(original_text)
        self._patched_text = str(original_text)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.status_label = QLabel("No changes. Original bytes will be preserved.")
        self.status_label.setObjectName("HintLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("PacXmlSourceInnerTabs")
        self.original_edit = self._editor("PacXmlOriginalSource", self._original_text)
        self.patched_edit = self._editor("PacXmlPatchedSource", self._patched_text)
        self.diff_edit = self._editor("PacXmlDiffSource", "No changes.")
        self.tabs.addTab(self.original_edit, "Original")
        self.tabs.addTab(self.patched_edit, "Patched")
        self.tabs.addTab(self.diff_edit, "Diff")
        layout.addWidget(self.tabs, 1)

    @staticmethod
    def _editor(name: str, text: str) -> QPlainTextEdit:
        editor = QPlainTextEdit()
        editor.setObjectName(name)
        editor.setReadOnly(True)
        editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        editor.setPlainText(text)
        return editor

    def set_patched_source(self, patched_text: str, *, changed_count: int = 0, validation_text: str = "") -> None:
        self._patched_text = str(patched_text)
        self.patched_edit.setPlainText(self._patched_text)
        if self._patched_text == self._original_text:
            diff = "No changes."
        else:
            diff = "".join(
                difflib.unified_diff(
                    self._original_text.splitlines(keepends=True),
                    self._patched_text.splitlines(keepends=True),
                    fromfile="original.pac_xml",
                    tofile="patched.pac_xml",
                    n=3,
                )
            )
        self.diff_edit.setPlainText(diff)
        message = f"{changed_count} changed parameter(s). Patched XML passed structural validation."
        if validation_text:
            message = validation_text
        self.status_label.setText(message)

    def show_validation_error(self, error: object) -> None:
        self.status_label.setText(f"Validation error: {error}")

    def jump_to_line(self, source_line: int, *, patched: bool = False) -> None:
        editor = self.patched_edit if patched else self.original_edit
        self.tabs.setCurrentWidget(editor)
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.Start)
        for _ in range(max(0, int(source_line) - 1)):
            if not cursor.movePosition(QTextCursor.Down):
                break
        editor.setTextCursor(cursor)
        editor.centerCursor()
        editor.setFocus()


__all__ = ["PacXmlSourceChangesView"]
