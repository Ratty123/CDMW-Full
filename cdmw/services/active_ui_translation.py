"""Translate already-rendered GUI text through whichever localizer owns the process.

This is the whole of what a standalone Qt tool needs in order to speak the user's
language: read the localizer the application published on itself, and ask it to
render one string. It lives here rather than in `cdmw.ui.localization` because
Placement Studio is guarded against importing `cdmw.ui` at all — that module
carries the shell's dialog patching and widget-tree walking, and dragging it into
a standalone tool is the coupling the guard exists to prevent.

`cdmw.ui.localization` re-exports these names, so the app-side callers that
already import them from there keep working.
"""

from __future__ import annotations

# QCoreApplication, not QApplication: the instance is the same object and property()
# is QObject API, and cdmw/services is guarded against importing PySide6.QtWidgets.
from PySide6.QtCore import QCoreApplication, QObject
from shiboken6 import isValid as qt_object_is_valid


#: The property an application sets on itself to publish its live localizer.
ACTIVE_UI_LOCALIZER_PROPERTY = "_cdmw_ui_localizer"


def active_ui_localizer() -> object | None:
    """Return the localizer the running application published, if it has one."""

    app = QCoreApplication.instance()
    if app is None or not qt_object_is_valid(app):
        return None
    localizer = app.property(ACTIVE_UI_LOCALIZER_PROPERTY)
    # A localizer whose C++ half has already gone is worse than none at all.
    if isinstance(localizer, QObject) and not qt_object_is_valid(localizer):
        return None
    return localizer


def translate_active_text(value: object) -> object:
    """Translate a value if it is text and a localizer is available, else pass it through."""

    localizer = active_ui_localizer()
    translate_rendered = getattr(localizer, "translate_rendered", None)
    if not callable(translate_rendered) or not isinstance(value, str):
        return value
    return translate_rendered(value)


def translate_active_ui_text(value: str) -> str:
    """Translate one already-rendered GUI value through the process owner."""

    return str(translate_active_text(str(value or "")))


__all__ = [
    "ACTIVE_UI_LOCALIZER_PROPERTY",
    "active_ui_localizer",
    "translate_active_text",
    "translate_active_ui_text",
]
