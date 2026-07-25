"""Settings flush must persist every pending change, not just appearance."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cdmw.services.settings_service import create_settings
from cdmw.ui.settings_tab import SettingsTab


_APP = QApplication.instance() or QApplication([])


class SettingsTabFlushPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.settings = create_settings(
            settings_file_path=Path(self._temp_dir.name) / "cdmw-test.cfg"
        )
        self.tab = SettingsTab(settings=self.settings, theme_key="dark")
        self.tab._last_applied_appearance_state = self.tab._appearance_state()

    def tearDown(self) -> None:
        self.tab.deleteLater()
        _APP.processEvents()
        self._temp_dir.cleanup()

    def _read_bool(self, key: str) -> bool:
        value = self.settings.value(key)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def test_flush_persists_preference_change_without_pending_appearance(self) -> None:
        self.tab.auto_load_archive_checkbox.setChecked(True)
        self.tab.flush_settings_save()

        self.assertTrue(self._read_bool("preferences/auto_load_archive_on_startup"))

    def test_flush_persists_preference_change_alongside_pending_appearance(self) -> None:
        """A pending appearance apply must not swallow other queued settings.

        Before the fix, ``flush_settings_save`` returned as soon as it had
        applied the appearance timer, so anything the save timer still owed --
        startup, performance, safety, and 3D preview preferences -- was dropped
        on app close and left out of exported profiles.
        """

        self.tab.auto_load_archive_checkbox.setChecked(True)
        self.tab.verbose_archive_logs_checkbox.setChecked(True)
        self.tab.ui_font_size_spin.setValue(self.tab.ui_font_size_spin.value() + 1)
        self.assertTrue(self.tab._appearance_apply_timer.isActive())
        self.assertTrue(self.tab._settings_save_timer.isActive())

        self.tab.flush_settings_save()

        self.assertEqual(
            self.tab.ui_font_size_spin.value(),
            int(self.settings.value("appearance/ui_font_size")),
        )
        self.assertTrue(self._read_bool("preferences/auto_load_archive_on_startup"))
        self.assertTrue(self._read_bool("preferences/show_verbose_archive_logs"))
        self.assertFalse(self.tab._settings_save_timer.isActive())
        self.assertFalse(self.tab._appearance_apply_timer.isActive())

    def test_flush_does_not_write_unread_model_quality_alias_key(self) -> None:
        self.tab.flush_settings_save()

        keys = {str(key) for key in self.settings.allKeys()}
        self.assertIn("archive/model_high_quality", keys)
        self.assertNotIn("archive/model_high_quality_textures", keys)


if __name__ == "__main__":
    unittest.main()
