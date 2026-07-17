"""Compatibility-safe dialog shell with unexported-change protection."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QCloseEvent, QShowEvent
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget


_INITIAL_SCREEN_FRACTION = 0.9


class PacXmlEditorDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PacXmlEditorDialog")
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowSystemMenuHint, True)
        self.setSizeGripEnabled(True)
        self._has_unexported_changes: Callable[[], bool] = lambda: False
        self._allow_close = False
        self._screen_size_applied = False

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

    def showEvent(self, event: QShowEvent) -> None:
        if not self._screen_size_applied:
            self._screen_size_applied = True
            screen = self.screen() or QApplication.primaryScreen()
            if screen is not None:
                available = screen.availableGeometry()
                target = _screen_aware_initial_size(self.size(), available.size())
                self.resize(target)
                self.move(
                    available.topLeft()
                    + QPoint(
                        (available.width() - target.width()) // 2,
                        (available.height() - target.height()) // 2,
                    )
                )
        super().showEvent(event)

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


def _screen_aware_initial_size(preferred: QSize, available: QSize) -> QSize:
    width = min(
        available.width(),
        max(preferred.width(), int(available.width() * _INITIAL_SCREEN_FRACTION)),
    )
    height = min(
        available.height(),
        max(preferred.height(), int(available.height() * _INITIAL_SCREEN_FRACTION)),
    )
    return QSize(max(1, width), max(1, height))


__all__ = ["PacXmlEditorDialog"]
