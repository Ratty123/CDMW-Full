"""A real, deterministic font for any test that measures rendered text.

The offscreen platform plugin ships **no fonts at all**. `QFont("Segoe UI")`
resolves to an empty family there, and Qt answers every metric from a built-in
fallback that is roughly twice as wide as the font the application actually
uses: "Distant versions" measures 208 px with no font registered and 98 px in
Segoe UI at the same point size. A width threshold tuned against the fallback is
tuned against a number the application never produces.

That also makes such a test order-dependent, because anything that registers a
font changes the answer for every widget built afterwards in the same process.
`cdmw.ui.shell.theme_controller._register_windows_cjk_fonts` does exactly that
when a localization test resolves fonts for a CJK language, and it is never
undone -- the registration is process-wide and deliberately permanent in the
application. Running that test first halved every width in the Placement Studio
layout test.

Pinning the application's own default font fixes both: the numbers become the
ones the application produces, and they stop depending on what ran first.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase, QFontInfo
from PySide6.QtWidgets import QApplication

from cdmw.constants import DEFAULT_UI_FONT_FAMILY, DEFAULT_UI_FONT_SIZE

#: The file each default family lives in, so the font can be registered on a
#: platform plugin that exposes none of the installed ones.
_FONT_FILES: dict[str, str] = {
    "segoe ui": "segoeui.ttf",
}


def ensure_default_ui_font_available() -> bool:
    """Registers the application's default UI font, and reports whether it resolved."""

    if QFontInfo(QFont(DEFAULT_UI_FONT_FAMILY)).family().casefold() == DEFAULT_UI_FONT_FAMILY.casefold():
        return True
    filename = _FONT_FILES.get(DEFAULT_UI_FONT_FAMILY.casefold())
    if not filename:
        return False
    path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / filename
    if not path.is_file():
        return False
    QFontDatabase.addApplicationFont(str(path))
    return QFontInfo(QFont(DEFAULT_UI_FONT_FAMILY)).family().casefold() == DEFAULT_UI_FONT_FAMILY.casefold()


def pin_default_ui_font(app: QApplication) -> bool:
    """Makes `app` measure text in its own default font.

    Returns `False` when the font could not be made available, which is the
    signal to skip rather than to assert against fallback metrics.
    """

    if not ensure_default_ui_font_available():
        return False
    app.setFont(QFont(DEFAULT_UI_FONT_FAMILY, DEFAULT_UI_FONT_SIZE))
    return True


__all__ = ["ensure_default_ui_font_available", "pin_default_ui_font"]
