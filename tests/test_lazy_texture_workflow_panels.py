from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CDMW_GUI_STARTUP_SMOKE", "1")

from PySide6.QtWidgets import QApplication

from cdmw.app.events import AppEventBus
from cdmw.services.service_container import ServiceContainer
from cdmw.services.settings_service import create_settings
from cdmw.ui.main_window import MainWindow
from cdmw.ui.panel_widgets import CollapsibleSection
from cdmw.ui.shell.app_context import AppContext


_APP = QApplication.instance() or QApplication([])


class LazyTextureWorkflowPanelTests(unittest.TestCase):
    def _window(self, values: dict[str, object]) -> tuple[MainWindow, object]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        settings = create_settings(settings_file_path=Path(temp_dir.name) / "settings.ini")
        for key, value in values.items():
            settings.setValue(key, value)
        context = AppContext(
            settings=settings,
            services=ServiceContainer.create_default(settings=settings),
            event_bus=AppEventBus(),
        )
        window = MainWindow(app_context=context)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window._finalize_close)
        return window, settings

    def test_collapsed_bodies_build_once_on_first_expansion(self) -> None:
        built: list[object] = []
        section = CollapsibleSection("Deferred", body_builder=lambda _layout: built.append(object()))
        self.addCleanup(section.deleteLater)

        self.assertFalse(section.is_body_built())
        self.assertEqual([], built)
        section.set_expanded(True)
        section.set_expanded(False)
        section.set_expanded(True)

        self.assertTrue(section.is_body_built())
        self.assertEqual(1, len(built))

    def test_collapsed_workflow_panels_restore_values_when_first_expanded(self) -> None:
        window, settings = self._window(
            {
                "settings/dry_run": True,
                "asset_authoring/oiio_source_path": "C:/assets/source.exr",
                "dds_output/custom_width": 2048,
                "settings/include_filters": "characters/*",
                "chainner/exe_path": "C:/tools/chainner.exe",
            }
        )
        panels = (
            (window.textures.settings_section, "dry_run_checkbox"),
            (window.textures.asset_authoring_section, "openimageio_source_path_edit"),
            (window.textures.dds_output_section, "dds_custom_width_spin"),
            (window.textures.filters_section, "filters_edit"),
            (window.textures.chainner_section, "chainner_exe_path_edit"),
        )
        for section, attribute in panels:
            self.assertFalse(section.is_body_built(), attribute)
            self.assertNotIn(attribute, vars(window.textures))

        for section, _attribute in panels:
            section.set_expanded(True)

        self.assertTrue(window.textures.dry_run_checkbox.isChecked())
        self.assertEqual("C:/assets/source.exr", window.textures.openimageio_source_path_edit.text())
        self.assertEqual(2048, window.textures.dds_custom_width_spin.value())
        self.assertEqual("characters/*", window.textures.filters_edit.toPlainText())
        self.assertEqual("C:/tools/chainner.exe", window.textures.chainner_exe_path_edit.text())
        self.assertIs(window.textures.workflow_profiles_dialog.parent(), window.textures)

        window._save_settings()
        self.assertEqual("C:/assets/source.exr", settings.value("asset_authoring/oiio_source_path"))

    def test_persisted_expanded_panel_is_ready_during_window_construction(self) -> None:
        window, _settings = self._window(
            {
                "sections/dds_output_expanded": True,
                "dds_output/custom_width": 1024,
            }
        )

        self.assertTrue(window.textures.dds_output_section.is_body_built())
        self.assertTrue(window.textures.dds_output_section.toggle_button.isChecked())
        self.assertEqual(1024, window.textures.dds_custom_width_spin.value())
        self.assertFalse(window.textures.chainner_section.is_body_built())


if __name__ == "__main__":
    unittest.main()
