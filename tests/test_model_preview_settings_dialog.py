import os
from pathlib import Path
from typing import Mapping
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from cdmw.models import ArchivePerformanceSettings, ModelPreviewRenderSettings
from cdmw.ui.model_preview_settings_dialog import ModelPreviewSettingsDialog
from cdmw.ui.model_preview_settings_visibility import (
    DOTNET_SUPPORTED_PREVIEW_SETTINGS_BY_TAB,
    preview_setting_widgets_by_tab,
)
from cdmw.ui.preview import DotNetPreviewHostFrame, DotNetPreviewProfile


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _CapturingD3D11HostFrame(DotNetPreviewHostFrame):
    def __init__(self) -> None:
        super().__init__(profile=DotNetPreviewProfile.PREVIEW)
        self.commands: list[dict[str, object]] = []
        self.controller.remember_state = self._capture_state  # type: ignore[method-assign]

    def _capture_state(
        self, key: str, event: str, payload: Mapping[str, object]
    ) -> bool:
        self.commands.append({"key": key, "command": event, **dict(payload)})
        return True


class ModelPreviewSettingsDialogTests(unittest.TestCase):
    def test_rich_lit_mode_is_available_in_settings_dialog(self) -> None:
        _app()
        dialog = ModelPreviewSettingsDialog(settings=ModelPreviewRenderSettings(render_diagnostic_mode="rich_lit"))

        self.assertEqual("Preview Settings", dialog.windowTitle())
        self.assertNotIn("Performance", [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())])
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

    def test_mesh_editor_dotnet_context_exposes_camera_input_and_gizmo_settings(self) -> None:
        _app()
        dialog = ModelPreviewSettingsDialog(
            settings=ModelPreviewRenderSettings(
                enable_tool_pbd_cloth_preview=True,
                gizmo_x_axis_color="#123456",
                gizmo_line_thickness_pixels=2.5,
            ),
            archive_renderer_backend="d3d11_native",
            preview_target="dotnet_vortice",
        )

        visible_tabs = [
            dialog.tabs.tabText(index)
            for index in range(dialog.tabs.count())
            if dialog.tabs.isTabVisible(index)
        ]
        self.assertEqual(["Camera Input", "Gizmo"], visible_tabs)
        widgets_by_tab = preview_setting_widgets_by_tab(dialog)
        self.assertEqual(set(DOTNET_SUPPORTED_PREVIEW_SETTINGS_BY_TAB), set(widgets_by_tab))
        for tab_name, widgets in widgets_by_tab.items():
            supported = set(DOTNET_SUPPORTED_PREVIEW_SETTINGS_BY_TAB[tab_name])
            visible = {field for field, widget in widgets.items() if not widget.isHidden()}
            self.assertEqual(supported, visible, tab_name)
            for field, widget in widgets.items():
                label = dialog._form_field_label(widget)
                if field in supported:
                    self.assertIn(".NET/Vortice", widget.toolTip(), field)
                    if label is not None:
                        self.assertFalse(label.isHidden(), field)
                elif label is not None:
                    self.assertTrue(label.isHidden(), field)
        self.assertFalse(dialog.tabs.isTabVisible(dialog.tabs.indexOf(dialog._general_tab)))
        self.assertFalse(dialog.tabs.isTabVisible(dialog.tabs.indexOf(dialog._quality_tab)))
        self.assertIs(dialog.tabs.currentWidget(), dialog._controls_tab)
        self.assertIn(".NET/Vortice", dialog.intro_label.text())
        self.assertTrue(dialog.advanced_warning_label.isHidden())
        self.assertIn("Each role pane keeps its own camera", dialog.controls_usage_hint_label.text())
        self.assertEqual("Reset Camera Input", dialog.reset_button.text())
        self.assertIn("hidden renderer settings", dialog.controls_hint_label.text())
        self.assertEqual("#123456", dialog.current_settings().gizmo_x_axis_color)
        self.assertEqual(2.5, dialog.current_settings().gizmo_line_thickness_pixels)

        dialog.close()
        dialog.deleteLater()

    def test_mesh_editor_gizmo_settings_apply_live_reset_and_keep_the_active_tab(self) -> None:
        _app()
        dialog = ModelPreviewSettingsDialog(
            settings=ModelPreviewRenderSettings(
                orbit_sensitivity=0.75,
                gizmo_line_thickness_pixels=1.0,
            ),
            preview_target="dotnet_vortice",
        )
        changes: list[ModelPreviewRenderSettings] = []
        dialog.settings_changed.connect(changes.append)
        dialog.tabs.setCurrentWidget(dialog._gizmo_tab)

        line_width = dialog.gizmo_settings_panel.controls_by_key["gizmo_line_thickness_pixels"]
        line_width.setValue(2.75)  # type: ignore[attr-defined]

        self.assertEqual(2.75, changes[-1].gizmo_line_thickness_pixels)
        dialog.set_settings(changes[-1])
        self.assertIs(dialog.tabs.currentWidget(), dialog._gizmo_tab)

        dialog.gizmo_settings_panel.reset_to_defaults()
        self.assertEqual(ModelPreviewRenderSettings().gizmo_line_thickness_pixels, changes[-1].gizmo_line_thickness_pixels)
        self.assertEqual(0.75, changes[-1].orbit_sensitivity)

        dialog.close()
        dialog.deleteLater()

    def test_mesh_editor_dotnet_reset_preserves_hidden_renderer_and_inversion_settings(self) -> None:
        _app()
        dialog = ModelPreviewSettingsDialog(
            settings=ModelPreviewRenderSettings(
                use_textures_by_default=False,
                d3d11_view_mode="normal",
                disable_lighting=True,
                d3d11_tone_exposure=0.35,
                orbit_sensitivity=0.91,
                pan_sensitivity=2.10,
                invert_orbit_x=True,
                invert_orbit_y=True,
                invert_pan_x=True,
                invert_pan_y=True,
                gizmo_x_axis_color="#123456",
                gizmo_size_scale=2.0,
            ),
            archive_renderer_backend="d3d11_native",
            preview_target="dotnet_vortice",
        )

        dialog._reset_defaults()
        current = dialog.current_settings()
        defaults = ModelPreviewRenderSettings()
        self.assertEqual(defaults.orbit_sensitivity, current.orbit_sensitivity)
        self.assertEqual(defaults.pan_sensitivity, current.pan_sensitivity)
        self.assertFalse(current.use_textures_by_default)
        self.assertEqual("normal", current.d3d11_view_mode)
        self.assertTrue(current.disable_lighting)
        self.assertEqual(0.35, current.d3d11_tone_exposure)
        self.assertEqual("#123456", current.gizmo_x_axis_color)
        self.assertEqual(2.0, current.gizmo_size_scale)
        self.assertTrue(current.invert_orbit_x)
        self.assertTrue(current.invert_orbit_y)
        self.assertTrue(current.invert_pan_x)
        self.assertTrue(current.invert_pan_y)

        dialog.close()
        dialog.deleteLater()

    def test_native_d3d11_render_tuning_payload_contains_visible_3d_settings(self) -> None:
        _app()
        host = _CapturingD3D11HostFrame()
        settings = ModelPreviewRenderSettings(
            max_anisotropy=8,
            d3d11_view_mode="normal",
            d3d11_light_azimuth_degrees=-12.5,
            d3d11_light_elevation_degrees=43.0,
            d3d11_ao_strength=0.35,
            d3d11_roughness_bias=0.22,
            d3d11_metalness_scale=0.45,
            d3d11_environment_strength=0.66,
            d3d11_emissive_gain=0.77,
            d3d11_tone_exposure=1.25,
            d3d11_tone_contrast=0.90,
            d3d11_tone_gamma=1.15,
            ambient_strength=0.68,
            diffuse_wrap_bias=0.84,
            diffuse_light_scale=0.88,
            orbit_sensitivity=0.31,
            pan_sensitivity=0.72,
            invert_orbit_x=True,
            invert_orbit_y=True,
            invert_pan_x=True,
            invert_pan_y=True,
        )

        try:
            self.assertTrue(host.set_render_tuning(settings))
            self.assertEqual(2, len(host.commands))
            payload = next(
                command
                for command in host.commands
                if command["command"] == "presentation_state_update"
            )["display"]["quality"]
            self.assertTrue(
                {
                    "dotnet_view_mode",
                    "max_anisotropy",
                    "diffuse_wrap_bias",
                    "orbit_sensitivity",
                    "pan_sensitivity",
                    "invert_orbit_x",
                    "invert_orbit_y",
                    "invert_pan_x",
                    "invert_pan_y",
                    "d3d11_light_azimuth_degrees",
                    "d3d11_light_elevation_degrees",
                    "d3d11_ao_strength",
                    "d3d11_roughness_bias",
                    "d3d11_metalness_scale",
                    "d3d11_environment_strength",
                    "d3d11_emissive_gain",
                    "d3d11_tone_exposure",
                    "d3d11_tone_contrast",
                    "d3d11_tone_gamma",
                    "ambient_strength",
                    "diffuse_light_scale",
                }.issubset(payload)
            )
            self.assertEqual("normal", payload["dotnet_view_mode"])
            self.assertEqual(8, payload["max_anisotropy"])
            self.assertEqual(0.84, payload["diffuse_wrap_bias"])
            self.assertEqual(0.31, payload["orbit_sensitivity"])
            self.assertEqual(0.72, payload["pan_sensitivity"])
            self.assertTrue(payload["invert_orbit_x"])
            self.assertTrue(payload["invert_orbit_y"])
            self.assertTrue(payload["invert_pan_x"])
            self.assertTrue(payload["invert_pan_y"])
            self.assertEqual(-12.5, payload["d3d11_light_azimuth_degrees"])
            self.assertEqual(43.0, payload["d3d11_light_elevation_degrees"])
            self.assertEqual(1.25, payload["d3d11_tone_exposure"])
            self.assertEqual(0.90, payload["d3d11_tone_contrast"])
            self.assertEqual(1.15, payload["d3d11_tone_gamma"])
        finally:
            host.close()
            host.deleteLater()

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
        self.assertIn("old_saved_defaults_v3", source)
        self.assertIn("old_saved_defaults_v4", source)
        self.assertIn("old_saved_defaults_v5", source)
        self.assertIn("_near(d3d11_environment_strength, 1.0)", source)
        self.assertIn("_near(d3d11_environment_strength, 0.85)", source)
        self.assertIn("_near(d3d11_tone_gamma, 1.26)", source)
        self.assertIn("d3d11_environment_strength = defaults.d3d11_environment_strength", source)
        self.assertIn("d3d11_tone_gamma = defaults.d3d11_tone_gamma", source)
        self.assertIn("diffuse_wrap_bias = defaults.diffuse_wrap_bias", source)
        self.assertIn('self.settings.setValue("preview/diffuse_wrap_bias", diffuse_wrap_bias)', source)
        self.assertIn('self.settings.setValue("preview/specular_max", specular_max)', source)
        self.assertIn('self.settings.setValue("preview/d3d11_lighting_defaults_version", 6)', source)


if __name__ == "__main__":
    unittest.main()
