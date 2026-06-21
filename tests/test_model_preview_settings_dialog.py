import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from cdmw.models import ArchivePerformanceSettings, ModelPreviewRenderSettings
from cdmw.ui.model_preview_settings_dialog import ModelPreviewSettingsDialog


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class ModelPreviewSettingsDialogTests(unittest.TestCase):
    def test_rich_lit_mode_is_available_in_settings_dialog(self) -> None:
        _app()
        dialog = ModelPreviewSettingsDialog(settings=ModelPreviewRenderSettings(render_diagnostic_mode="rich_lit"))

        rich_index = dialog.render_diagnostic_mode_combo.findData("rich_lit")
        self.assertGreaterEqual(rich_index, 0)
        self.assertEqual("Enhanced Relief Preview", dialog.render_diagnostic_mode_combo.itemText(rich_index))
        self.assertEqual("rich_lit", dialog.current_settings().render_diagnostic_mode)

        dialog.close()
        dialog.deleteLater()

    def test_material_quality_sliders_are_available_in_settings_dialog(self) -> None:
        _app()
        dialog = ModelPreviewSettingsDialog(settings=ModelPreviewRenderSettings(render_diagnostic_mode="lit"))

        self.assertIn("normal_strength_cap", dialog._slider_controls)
        self.assertIn("height_effect_max", dialog._slider_controls)
        self.assertIn("diffuse_wrap_bias", dialog._slider_controls)
        self.assertIn("specular_max", dialog._slider_controls)
        self.assertIn("shininess_max", dialog._slider_controls)
        self.assertEqual(
            ModelPreviewRenderSettings().height_effect_max,
            dialog.current_settings().height_effect_max,
        )

        dialog.close()
        dialog.deleteLater()

    def test_settings_dialog_warns_that_diagnostics_are_advanced(self) -> None:
        _app()
        dialog = ModelPreviewSettingsDialog(settings=ModelPreviewRenderSettings())

        dialog_text = " ".join(label.text() for label in dialog.findChildren(QLabel))
        self.assertIn("Advanced diagnostics", dialog_text)
        self.assertIn("no visible effect", dialog_text)
        self.assertTrue(dialog.show_physics_overlay_checkbox.isChecked())
        self.assertIn("HKX physics overlay", dialog.show_physics_overlay_checkbox.text())
        self.assertFalse(dialog.show_physics_simulation_preview_checkbox.isChecked())
        self.assertIn("legacy HKX guide motion", dialog.show_physics_simulation_preview_checkbox.text())
        self.assertIn("spring/sway diagnostic", dialog.show_physics_simulation_preview_checkbox.toolTip())
        self.assertIn("Skeleton context stays fixed", dialog.show_physics_simulation_preview_checkbox.toolTip())
        self.assertFalse(dialog.enable_tool_pbd_cloth_preview_checkbox.isChecked())
        self.assertIn("tool-side PBD physics preview", dialog.enable_tool_pbd_cloth_preview_checkbox.text())
        self.assertIn("cloth, leather, hair, and ropes", dialog.enable_tool_pbd_cloth_preview_checkbox.toolTip())
        self.assertFalse(dialog.pause_tool_pbd_cloth_preview_checkbox.isEnabled())
        self.assertFalse(dialog.show_tool_pbd_cloth_pins_checkbox.isEnabled())
        self.assertFalse(dialog.show_tool_pbd_cloth_colliders_checkbox.isEnabled())

        dialog.enable_tool_pbd_cloth_preview_checkbox.setChecked(True)
        current = dialog.current_settings()
        self.assertTrue(current.enable_tool_pbd_cloth_preview)
        self.assertTrue(dialog.pause_tool_pbd_cloth_preview_checkbox.isEnabled())
        self.assertTrue(dialog.show_tool_pbd_cloth_pins_checkbox.isEnabled())
        self.assertTrue(dialog.show_tool_pbd_cloth_colliders_checkbox.isEnabled())

        dialog.close()
        dialog.deleteLater()

    def test_performance_subset_preserves_hidden_archive_settings_on_emit(self) -> None:
        _app()
        dialog = ModelPreviewSettingsDialog(
            settings=ModelPreviewRenderSettings(),
            archive_performance_settings=ArchivePerformanceSettings(
                resource_profile="maximum_throughput",
                archive_fetch_batch_size=1200,
                native_archive_acceleration=False,
                enable_sidecar_indexing=True,
                sidecar_worker_count=3,
                preview_cache_limit=64,
                native_preview_cache_mode="aggressive",
            ),
        )
        emitted = []
        dialog.archive_performance_changed.connect(emitted.append)

        dialog.preview_cache_limit_spin.setValue(96)

        self.assertTrue(emitted)
        current = emitted[-1]
        self.assertEqual("maximum_throughput", current.resource_profile)
        self.assertEqual(1200, current.archive_fetch_batch_size)
        self.assertFalse(current.native_archive_acceleration)
        self.assertEqual(96, current.preview_cache_limit)
        self.assertEqual("aggressive", current.native_preview_cache_mode)
        self.assertTrue(current.enable_sidecar_indexing)
        self.assertEqual(3, current.sidecar_worker_count)

        dialog.close()
        dialog.deleteLater()

    def test_controls_tab_explains_preview_navigation_and_inversion(self) -> None:
        _app()
        dialog = ModelPreviewSettingsDialog(settings=ModelPreviewRenderSettings())

        dialog_text = " ".join(label.text() for label in dialog.findChildren(QLabel))
        self.assertIn("left-drag orbits", dialog_text)
        self.assertIn("Shift+left-drag pans", dialog_text)
        self.assertIn("These controls only move the preview camera/view", dialog_text)
        self.assertIn("Invert orbit X reverses horizontal orbit", dialog_text)
        self.assertIn("never edits the asset", dialog_text)
        self.assertIn("Reverse horizontal orbit", dialog.invert_orbit_x_checkbox.toolTip())
        self.assertIn("Reverse vertical orbit", dialog.invert_orbit_y_checkbox.toolTip())
        self.assertIn("screen-space preview navigation", dialog.invert_pan_x_checkbox.toolTip())
        self.assertIn("screen-space preview navigation", dialog.invert_pan_y_checkbox.toolTip())

        dialog.close()
        dialog.deleteLater()

    def test_probe_texture_selection_switches_to_selected_texture_probe_mode(self) -> None:
        _app()
        dialog = ModelPreviewSettingsDialog(settings=ModelPreviewRenderSettings(render_diagnostic_mode="lit"))

        self.assertTrue(dialog.texture_probe_source_combo.isEnabled())
        self.assertEqual("lit", dialog.current_settings().render_diagnostic_mode)

        material_index = dialog.texture_probe_source_combo.findData("material")
        self.assertGreaterEqual(material_index, 0)
        dialog.texture_probe_source_combo.setCurrentIndex(material_index)

        current = dialog.current_settings()
        self.assertEqual("texture_probe", current.render_diagnostic_mode)
        self.assertEqual("material", current.texture_probe_source)

        dialog.close()
        dialog.deleteLater()

    def test_d3d11_backend_hides_legacy_only_diagnostics(self) -> None:
        _app()
        dialog = ModelPreviewSettingsDialog(
            settings=ModelPreviewRenderSettings(render_diagnostic_mode="lit"),
            archive_renderer_backend="d3d11_native",
        )

        self.assertEqual("d3d11_native", dialog.current_archive_renderer_backend())
        self.assertTrue(dialog.archive_renderer_backend_combo.isHidden())
        self.assertTrue(dialog.render_diagnostic_mode_combo.isHidden())
        self.assertFalse(dialog.d3d11_view_mode_combo.isHidden())
        self.assertFalse(dialog.d3d11_normal_y_mode_combo.isHidden())
        self.assertFalse(dialog.d3d11_texture_address_mode_combo.isHidden())
        self.assertFalse(dialog.d3d11_cull_back_faces_checkbox.isHidden())
        self.assertTrue(dialog.disable_depth_test_checkbox.isHidden())
        self.assertFalse(dialog.disable_all_support_maps_checkbox.isHidden())
        self.assertEqual("Ignore support maps", dialog.disable_all_support_maps_checkbox.text())
        self.assertFalse(dialog.disable_normal_map_checkbox.isHidden())
        self.assertEqual("Ignore normal map", dialog.disable_normal_map_checkbox.text())
        self.assertFalse(dialog.flip_texture_v_checkbox.isHidden())
        self.assertFalse(dialog._slider_controls["max_anisotropy"].isHidden())
        self.assertFalse(dialog._slider_controls["ambient_strength"].isHidden())
        self.assertFalse(dialog.d3d11_hint_label.isHidden())
        self.assertIn("Flip texture V", dialog.d3d11_hint_label.text())
        self.assertIn("tool-side PBD physics preview", dialog.d3d11_hint_label.text())
        self.assertIn("static HKX context", dialog.d3d11_hint_label.text())
        self.assertFalse(dialog.current_settings().flip_texture_v)
        dialog.flip_texture_v_checkbox.setChecked(True)
        self.assertTrue(dialog.current_settings().flip_texture_v)
        view_index = dialog.d3d11_view_mode_combo.findData("normal")
        self.assertGreaterEqual(view_index, 0)
        dialog.d3d11_view_mode_combo.setCurrentIndex(view_index)
        outdoor_index = dialog.d3d11_view_mode_combo.findData("game_outdoor")
        self.assertGreaterEqual(outdoor_index, 0)
        self.assertEqual("Game Outdoor Approx", dialog.d3d11_view_mode_combo.itemText(outdoor_index))
        normal_y_index = dialog.d3d11_normal_y_mode_combo.findData("force_no_flip")
        self.assertGreaterEqual(normal_y_index, 0)
        dialog.d3d11_normal_y_mode_combo.setCurrentIndex(normal_y_index)
        address_index = dialog.d3d11_texture_address_mode_combo.findData("clamp")
        self.assertGreaterEqual(address_index, 0)
        dialog.d3d11_texture_address_mode_combo.setCurrentIndex(address_index)
        dialog.d3d11_cull_back_faces_checkbox.setChecked(True)
        current = dialog.current_settings()
        self.assertEqual("normal", current.d3d11_view_mode)
        self.assertEqual("force_no_flip", current.d3d11_normal_y_mode)
        self.assertEqual("clamp", current.d3d11_texture_address_mode)
        self.assertTrue(current.d3d11_cull_back_faces)

        self.assertEqual(-1, dialog.archive_renderer_backend_combo.findData("legacy_green_up"))
        dialog.set_archive_renderer_backend("legacy_green_up")
        self.assertEqual("d3d11_native", dialog.current_archive_renderer_backend())
        self.assertTrue(dialog.render_diagnostic_mode_combo.isHidden())
        self.assertFalse(dialog.d3d11_view_mode_combo.isHidden())
        self.assertTrue(dialog.disable_depth_test_checkbox.isHidden())
        self.assertFalse(dialog.flip_texture_v_checkbox.isHidden())

        dialog.close()
        dialog.deleteLater()

    def test_game_outdoor_d3d11_view_mode_survives_settings_dialog(self) -> None:
        _app()
        dialog = ModelPreviewSettingsDialog(
            settings=ModelPreviewRenderSettings(d3d11_view_mode="game_outdoor"),
            archive_renderer_backend="d3d11_native",
        )

        self.assertEqual("game_outdoor", dialog.current_settings().d3d11_view_mode)

        dialog.close()
        dialog.deleteLater()

    def test_removed_webgl_backend_normalizes_to_d3d11(self) -> None:
        _app()
        dialog = ModelPreviewSettingsDialog(
            settings=ModelPreviewRenderSettings(render_diagnostic_mode="lit"),
            archive_renderer_backend="webgl_pbr_reference",
        )

        self.assertEqual("d3d11_native", dialog.current_archive_renderer_backend())
        self.assertEqual(-1, dialog.archive_renderer_backend_combo.findData("webgl_pbr_reference"))
        self.assertTrue(dialog.render_diagnostic_mode_combo.isHidden())
        self.assertFalse(dialog.d3d11_view_mode_combo.isHidden())
        self.assertFalse(dialog.disable_all_support_maps_checkbox.isHidden())
        self.assertFalse(dialog.disable_normal_map_checkbox.isHidden())
        self.assertFalse(dialog.flip_texture_v_checkbox.isHidden())
        self.assertFalse(dialog.d3d11_hint_label.isHidden())
        self.assertIn("D3D11 packages", dialog.high_quality_checkbox.toolTip())

        dialog.close()
        dialog.deleteLater()

    def test_legacy_saved_d3d11_lighting_defaults_are_migrated(self) -> None:
        source = Path("cdmw/ui/archive_browser/preview_settings.py").read_text(encoding="utf-8")

        self.assertIn("preview/d3d11_lighting_defaults_version", source)
        self.assertIn("old_saved_defaults_v2", source)
        self.assertIn("_near(d3d11_environment_strength, 1.0)", source)
        self.assertIn("d3d11_environment_strength = defaults.d3d11_environment_strength", source)
        self.assertIn("diffuse_wrap_bias = defaults.diffuse_wrap_bias", source)
        self.assertIn('self.settings.setValue("preview/diffuse_wrap_bias", diffuse_wrap_bias)', source)
        self.assertIn('self.settings.setValue("preview/specular_max", specular_max)', source)


if __name__ == "__main__":
    unittest.main()
