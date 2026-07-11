from __future__ import annotations

import os
import subprocess
import sys
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
                "asset_authoring/material_maker_project_path": "C:/assets/material.mm",
                "dds_output/custom_width": 2048,
                "settings/include_filters": "characters/*",
                "chainner/exe_path": "C:/tools/chainner.exe",
            }
        )
        panels = (
            (window.settings_section, "dry_run_checkbox"),
            (window.asset_authoring_section, "material_maker_project_edit"),
            (window.dds_output_section, "dds_custom_width_spin"),
            (window.filters_section, "filters_edit"),
            (window.chainner_section, "chainner_exe_path_edit"),
        )
        for section, attribute in panels:
            self.assertFalse(section.is_body_built(), attribute)
            self.assertNotIn(attribute, vars(window))

        for section, _attribute in panels:
            section.set_expanded(True)

        self.assertTrue(window.dry_run_checkbox.isChecked())
        self.assertEqual("C:/assets/material.mm", window.material_maker_project_edit.text())
        self.assertEqual(2048, window.dds_custom_width_spin.value())
        self.assertEqual("characters/*", window.filters_edit.toPlainText())
        self.assertEqual("C:/tools/chainner.exe", window.chainner_exe_path_edit.text())

        window._save_settings()
        self.assertEqual("C:/assets/material.mm", settings.value("asset_authoring/material_maker_project_path"))

    def test_persisted_expanded_panel_is_ready_during_window_construction(self) -> None:
        window, _settings = self._window(
            {
                "sections/dds_output_expanded": True,
                "dds_output/custom_width": 1024,
            }
        )

        self.assertTrue(window.dds_output_section.is_body_built())
        self.assertTrue(window.dds_output_section.toggle_button.isChecked())
        self.assertEqual(1024, window.dds_custom_width_spin.value())
        self.assertFalse(window.chainner_section.is_body_built())

    def test_collapsed_panel_providers_stay_unimported_in_clean_process(self) -> None:
        script = r"""
import os
import sys
import tempfile
from pathlib import Path
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["CDMW_GUI_STARTUP_SMOKE"] = "1"
os.environ["CDMW_MAIN_WINDOW_CLASS_ONLY"] = "1"
os.environ["CDMW_SINGLE_INSTANCE_SCOPE"] = f"lazy-panel-imports-{os.getpid()}"
from cdmw.services import settings_service
from PySide6.QtWidgets import QApplication
import cdmw.ui.shell.app_window as app_window
settings_path = Path(tempfile.mkdtemp(prefix="cdmw-lazy-panel-imports-")) / "settings.ini"
settings_service.resolve_settings_file_path = lambda **_kwargs: settings_path
app_window.resolve_settings_file_path = lambda: settings_path
MainWindow = app_window.run_gui()
from cdmw.app.events import AppEventBus
from cdmw.services.service_container import ServiceContainer
from cdmw.ui.shell.app_context import AppContext
app = QApplication.instance() or QApplication([])
settings = settings_service.create_settings(settings_file_path=settings_path)
window = MainWindow(app_context=AppContext(settings, ServiceContainer.create_default(settings=settings), AppEventBus()))
providers = (
    "cdmw.ui.texture_workflow.settings_panel",
    "cdmw.ui.texture_workflow.asset_authoring_panel",
    "cdmw.ui.texture_workflow.dds_output_panel",
    "cdmw.ui.texture_workflow.workflow_profiles_ui",
    "cdmw.ui.texture_workflow.upscale_backend_panel",
)
assert not [name for name in providers if name in sys.modules]
window._finalize_close()
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
