"""Shell icon and tray-icon ownership boundary."""

from __future__ import annotations

import ctypes
import os

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget

from cdmw.constants import APP_NAME, APP_ORGANIZATION
from cdmw.ui.shell.diagnostics_controller import qt_wrapper_is_valid


class IconController:
    def __init__(self, context: object | None = None) -> None:
        self.context = context


class AppWindowIconEventFilter(QObject):
    def __init__(self, app_icon: QIcon, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._app_icon = QIcon(app_icon)

    def set_app_icon(self, app_icon: QIcon) -> None:
        self._app_icon = QIcon(app_icon)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        try:
            event_type = event.type()
        except RuntimeError:
            return False
        if (
            event_type in (QEvent.Type.Show, QEvent.Type.WindowActivate)
            and qt_wrapper_is_valid(watched)
            and isinstance(watched, QWidget)
            and not self._app_icon.isNull()
        ):
            try:
                if watched.isWindow():
                    watched.setWindowIcon(self._app_icon)
            except RuntimeError:
                pass
        return False


def apply_windows_app_user_model_id() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_ORGANIZATION}.{APP_NAME}")
    except Exception:
        pass


__all__ = ["AppWindowIconEventFilter", "IconController", "apply_windows_app_user_model_id"]
