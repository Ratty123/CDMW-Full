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

    def test_settings_navigation_compacts_to_its_labels_and_selected_list_font(self) -> None:
        self.tab.ui_font_size_spin.setValue(8)
        self.tab.data_font_size_spin.setValue(8)
        self.tab.flush_settings_save()
        self.tab.resize(1100, 760)
        self.tab.show()
        _APP.processEvents()

        nav = self.tab.section_nav_list
        row_heights = tuple(nav.item(row).sizeHint().height() for row in range(nav.count()))
        last_item_rect = nav.visualItemRect(nav.item(nav.count() - 1))
        english_width = nav.width()
        self.assertEqual("", nav.styleSheet())
        self.assertEqual(8, nav.font().pointSize())
        self.assertGreaterEqual(nav.minimumWidth(), 154)
        self.assertLessEqual(nav.maximumWidth(), 220)
        self.assertEqual(nav.minimumWidth(), nav.maximumWidth())
        self.assertLess(max(row_heights), 40)
        self.assertEqual(nav.minimumHeight(), nav.maximumHeight())
        self.assertLess(nav.maximumHeight(), 260)
        self.assertLess(last_item_rect.bottom(), nav.viewport().height())

        nav.item(3).setText("Translated performance navigation")
        self.tab._apply_section_nav_style()
        _APP.processEvents()
        self.assertGreater(nav.width(), english_width)
        self.assertLessEqual(nav.width(), 220)


if __name__ == "__main__":
    unittest.main()
