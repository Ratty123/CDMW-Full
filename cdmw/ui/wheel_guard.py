"""Application-wide guards for wheel-sensitive controls."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QAbstractSpinBox, QComboBox, QSlider

try:
    import shiboken6
except Exception:  # pragma: no cover - shipped with PySide6, defensive for test-only imports.
    shiboken6 = None


class NonIntrusiveWheelGuard(QObject):
    """Prevents accidental wheel changes on setting widgets while scrolling containers."""

    @staticmethod
    def _watched_is_valid(watched: object) -> bool:
        if watched is None:
            return False
        if shiboken6 is not None:
            try:
                return bool(shiboken6.isValid(watched))
            except Exception:
                return False
        try:
            watched.objectName()  # type: ignore[attr-defined]
            return True
        except RuntimeError:
            return False
        except Exception:
            return True

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        try:
            event_type = event.type()
        except RuntimeError:
            return False
        if event_type != QEvent.Type.Wheel:
            return False
        if not self._watched_is_valid(watched):
            return False
        try:
            if isinstance(watched, QComboBox):
                event.ignore()
                return True
            if isinstance(watched, QAbstractSpinBox):
                event.ignore()
                return True
            if isinstance(watched, QSlider):
                event.ignore()
                return True
        except RuntimeError:
            return False
        return False


_wheel_guard: Optional[NonIntrusiveWheelGuard] = None


def ensure_app_wheel_guard(app: Optional[QApplication]) -> None:
    global _wheel_guard
    if app is None or _wheel_guard is not None:
        return
    _wheel_guard = NonIntrusiveWheelGuard(app)
    app.installEventFilter(_wheel_guard)


__all__ = ["NonIntrusiveWheelGuard", "ensure_app_wheel_guard"]
