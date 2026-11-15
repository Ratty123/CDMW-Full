"""Create New Item's pages take the palette's keys from CDMW's keymap (review of ddc81f5d).

The page hard-wired Ctrl+Shift+P; its theme payload now carries the keymap's chords
as the Mesh Editor's does, and the helper reads them from there.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings

from cdmw.services import settings_service
from cdmw.services.keymap_store import set_override
from cdmw.ui.commands import helper_keys
from cdmw.ui.commands.palette import PALETTE_COMMAND
from cdmw.ui.new_item import rust_ui_tab


def test_the_page_payload_names_the_palette_keys_the_keymap_gives(tmp_path, monkeypatch) -> None:
    settings = QSettings(str(tmp_path / "keys.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings_service, "app_settings", lambda: settings)
    try:
        assert rust_ui_tab._palette_chords() == ["Ctrl+Shift+P"]  # noqa: SLF001
        set_override(settings, PALETTE_COMMAND, ["Ctrl+K"])
        assert rust_ui_tab._palette_chords() == ["Ctrl+K"]  # noqa: SLF001
    finally:
        set_override(settings, PALETTE_COMMAND, None)
        helper_keys.palette_chords(QSettings(str(tmp_path / "fresh.ini"), QSettings.Format.IniFormat))
