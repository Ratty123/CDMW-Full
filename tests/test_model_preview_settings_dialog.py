import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from cdmw.models import ModelPreviewRenderSettings
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
        self.assertIn("tool-side PBD cloth preview", dialog.enable_tool_pbd_cloth_preview_checkbox.text())
        self.assertIn("does not enable hair or body jiggle", dialog.enable_tool_pbd_cloth_preview_checkbox.toolTip())
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
        self.assertTrue(dialog.render_diagnostic_mode_combo.isHidden())
        self.assertTrue(dialog.disable_depth_test_checkbox.isHidden())
        self.assertFalse(dialog.disable_all_support_maps_checkbox.isHidden())
        self.assertFalse(dialog.disable_normal_map_checkbox.isHidden())
        self.assertFalse(dialog.flip_texture_v_checkbox.isHidden())
        self.assertFalse(dialog._slider_controls["max_anisotropy"].isHidden())
        self.assertFalse(dialog._slider_controls["ambient_strength"].isHidden())
        self.assertFalse(dialog.d3d11_hint_label.isHidden())
        self.assertIn("Flip texture V", dialog.d3d11_hint_label.text())
        self.assertIn("tool-side PBD cloth preview", dialog.d3d11_hint_label.text())
        self.assertIn("static HKX context", dialog.d3d11_hint_label.text())
        self.assertFalse(dialog.current_settings().flip_texture_v)
        dialog.flip_texture_v_checkbox.setChecked(True)
        self.assertTrue(dialog.current_settings().flip_texture_v)

        legacy_index = dialog.archive_renderer_backend_combo.findData("legacy_opengl")
        self.assertGreaterEqual(legacy_index, 0)
        dialog.archive_renderer_backend_combo.setCurrentIndex(legacy_index)

        self.assertEqual("legacy_opengl", dialog.current_archive_renderer_backend())
        self.assertFalse(dialog.render_diagnostic_mode_combo.isHidden())
        self.assertFalse(dialog.disable_depth_test_checkbox.isHidden())
        self.assertTrue(dialog.flip_texture_v_checkbox.isHidden())

        dialog.close()
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
