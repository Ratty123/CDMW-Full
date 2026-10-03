from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CDMW_GUI_STARTUP_SMOKE", "1")

from PySide6.QtCore import QElapsedTimer, QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QSizePolicy

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

        for combo in (
            window.textures.dds_format_mode_combo,
            window.textures.dds_size_mode_combo,
            window.textures.dds_mip_mode_combo,
            window.textures.dds_custom_format_combo,
        ):
            self.assertGreaterEqual(combo.minimumContentsLength(), 18)
            self.assertEqual(combo.sizeAdjustPolicy(), QComboBox.AdjustToMinimumContentsLengthWithIcon)
            self.assertEqual(combo.sizePolicy().horizontalPolicy(), QSizePolicy.Expanding)

    def test_openimageio_worker_delivers_its_report_and_releases_the_busy_panel(self) -> None:
        window, _settings = self._window({})
        textures = window.textures
        textures.asset_authoring_section.set_expanded(True)
        calls = []

        class Service:
            def run_openimageio_metadata(self, source, configured_paths, **_kwargs):
                calls.append((source, QThread.currentThread() == _APP.thread()))
                return {
                    "status": "ok",
                    "metadata": {"width": 32, "height": 16, "channel_count": 4, "bit_depth": 8},
                }

        with patch.object(textures, "_asset_authoring_service", return_value=Service()):
            textures._start_openimageio_task("metadata", (Path("source.png"),))

        timer = QElapsedTimer()
        timer.start()
        while window.shell.worker_thread is not None and timer.elapsed() < 5000:
            QTest.qWait(10)

        self.assertIsNone(window.shell.worker_thread, "OpenImageIO worker did not finish")
        self.assertIsNone(window.shell.utility_worker)
        self.assertEqual(calls, [(Path("source.png"), False)])
        self.assertEqual(textures.openimageio_status_label.text(), "OpenImageIO metadata complete.")
        self.assertIn("32 x 16, 4 channel(s), 8-bit", textures.openimageio_report_view.toPlainText())
        self.assertEqual(textures.current_file_value.text(), "Completed")

    def test_editable_filters_and_override_keep_long_values_and_undo(self) -> None:
        filters = "\n".join(f"characters/filter-{index}/*" for index in range(205))
        override = "{\n" + ",\n".join(f'  "input-{index}": "value"' for index in range(305)) + "\n}"
        window, settings = self._window({
            "settings/include_filters": filters,
            "chainner/override_json": override,
        })
        window.textures.filters_section.set_expanded(True)
        window.textures.chainner_section.set_expanded(True)
        for editor, expected in (
            (window.textures.filters_edit, filters),
            (window.textures.chainner_override_edit, override),
        ):
            self.assertEqual(expected, editor.toPlainText())
            self.assertTrue(editor.isUndoRedoEnabled())
            editor.insertPlainText("edited")
            self.assertNotEqual(expected, editor.toPlainText())
            editor.undo()
            self.assertEqual(expected, editor.toPlainText())
        window._save_settings()
        self.assertEqual(filters, settings.value("settings/include_filters"))
        self.assertEqual(override, settings.value("chainner/override_json"))

    def test_shared_recolor_source_change_clears_analysis_and_preview_without_removing_assets(self) -> None:
        import dataclasses
        from PySide6.QtGui import QImage
        from cdmw.core.recolor_variants import analyze_recolor_variant_package
        from tests.test_recolor_variants import _write_mod

        window, settings = self._window({"ui/active_tool_key": "archive_browser"})
        source = _write_mod(Path(settings.fileName()).parent)
        analysis = analyze_recolor_variant_package(source)
        # Material rows exercise shared selection without decoding DDS files.
        analysis = dataclasses.replace(analysis, targets=tuple(
            target for target in analysis.targets if target.target_kind == "material_color"
        ))
        self.assertTrue(analysis.targets)
        textures = window.textures
        textures.set_texture_mode("recolor")
        recolor = window.recolor_variants_tab.ensure_widget()
        recolor.source_path_edit.setText(str(source))
        recolor.analysis = analysis
        recolor._populate_targets_tree()
        editor = window.texture_editor_tab.ensure_widget()
        image = QImage(4, 4, QImage.Format_RGBA8888)
        image.fill(0)
        editor.show_workspace_preview(image, image)
        recolor.current_preview_image = object()
        assets = dict(textures.job.assets)
        operation = textures.job.begin("recolor_preview")

        recolor.source_path_edit.setText(str(source.parent / "other-mod"))

        self.assertIsNone(recolor.analysis)
        self.assertIsNone(textures.job.recolor_analysis)
        self.assertIsNone(recolor.current_preview_image)
        self.assertIsNone(editor.workspace_preview)
        self.assertFalse(recolor.build_button.isEnabled())
        self.assertFalse(textures.job.accept(operation))
        self.assertEqual(assets, textures.job.assets)


if __name__ == "__main__":
    unittest.main()
