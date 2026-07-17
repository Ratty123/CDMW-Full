"""Compatibility-safe dialog shell with unexported-change protection."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QMessageBox, QWidget


class PacXmlEditorDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PacXmlEditorDialog")
        self._has_unexported_changes: Callable[[], bool] = lambda: False
        self._allow_close = False

    def set_unexported_changes_callback(self, callback: Callable[[], bool]) -> None:
        self._has_unexported_changes = callback

    def accept(self) -> None:
        if self._confirm_discard_if_needed():
            super().accept()

    def reject(self) -> None:
        if self._confirm_discard_if_needed():
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._confirm_discard_if_needed():
            self._allow_close = True
            super().closeEvent(event)
        else:
            event.ignore()

    def _confirm_discard_if_needed(self) -> bool:
        if self._allow_close or not self._has_unexported_changes():
            return True
        answer = QMessageBox.question(
            self,
            "Discard Unexported PAC XML Changes?",
            "This editor contains changes that have not been exported to a mod package. Discard them and close?",
            QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer == QMessageBox.Discard:
            self._allow_close = True
            return True
        return False


__all__ = ["PacXmlEditorDialog"]
