"""Keep workflow dialogs authoritative while Rust presents their controls."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QColorDialog, QDialog, QFileDialog, QMenu, QWidget
from shiboken6 import isValid


class PresentationDialogs(QObject):
    changed = Signal()

    def __init__(self, workflow, visible_parent):
        super().__init__(visible_parent)
        self.workflow = workflow
        self.visible_parent = visible_parent
        self.active = False
        self._dialogs = []
        self._native = []
        QApplication.instance().installEventFilter(self)

    def owns(self, widget):
        current = widget
        while current is not None:
            if current is self.workflow or current in self._dialogs or current in self._native:
                return True
            current = current.parent()
        return False

    def dialogs(self):
        self._dialogs = [dialog for dialog in self._dialogs if isValid(dialog) and not dialog.isHidden()]
        return tuple(self._dialogs)

    def native_modal(self):
        self._native = [dialog for dialog in self._native if isValid(dialog) and not dialog.isHidden()]
        return bool(self._native)

    def eventFilter(self, watched, event):
        if not self.active or not isinstance(watched, (QDialog, QMenu)):
            return False
        kind = event.type()
        if kind in (QEvent.Polish, QEvent.Show) and self.owns(watched):
            if isinstance(watched, (QFileDialog, QColorDialog)):
                if watched not in self._native:
                    self._native.append(watched)
                # OS-owned file/colour pickers remain visible and owned by the
                # experimental tab even though the workflow itself is offscreen.
                if watched.parentWidget() is not self.visible_parent:
                    watched.setParent(self.visible_parent, watched.windowFlags())
            else:
                watched.setAttribute(Qt.WA_DontShowOnScreen, True)
                if isinstance(watched, QDialog) and kind == QEvent.Show:
                    # Rust presents this modal and the bridge enforces its input
                    # boundary. A hidden Qt modal disables the visible host HWND
                    # too, leaving the projected buttons unable to dismiss it.
                    # Clear exec()'s flag just before Qt registers the window.
                    watched.setAttribute(Qt.WA_ShowModal, False)
                if watched not in self._dialogs:
                    self._dialogs.append(watched)
            self.changed.emit()
        elif kind in (QEvent.Hide, QEvent.Close) and (watched in self._dialogs or watched in self._native):
            self.changed.emit()
        return False

    def close(self):
        self.active = False
        for dialog in (*self._dialogs, *self._native):
            if isValid(dialog):
                dialog.close()
        self._dialogs.clear()
        self._native.clear()
        QApplication.instance().removeEventFilter(self)
