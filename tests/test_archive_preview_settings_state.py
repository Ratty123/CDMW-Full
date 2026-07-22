from __future__ import annotations

from dataclasses import fields, replace

from cdmw.models import ArchivePreviewResult, ModelPreviewRenderSettings
from cdmw.ui.archive_browser.preview_settings import ArchivePreviewSettingsMixin
from cdmw.ui.archive_browser.preview_settings_state import (
    ModelPreviewSettingsChangeFlags,
    model_preview_settings_change_flags,
    model_preview_settings_status,
)
from cdmw.ui.model_preview_native import ARCHIVE_MODEL_RENDERER_D3D11


def _flag_names(flags: ModelPreviewSettingsChangeFlags) -> set[str]:
    return {field.name for field in fields(flags) if getattr(flags, field.name)}


def _changed_settings(field_name: str) -> ModelPreviewRenderSettings:
    base = ModelPreviewRenderSettings()
    explicit_values = {
        "visible_texture_mode": "layer_aware_visible",
        "render_diagnostic_mode": "normals",
        "alpha_handling_mode": "blend",
        "texture_probe_source": "material",
        "sampler_probe_mode": "nearest_no_mips",
        "diffuse_swizzle_mode": "bgra",
        "d3d11_view_mode": "normal",
        "d3d11_normal_y_mode": "force_no_flip",
        "d3d11_texture_address_mode": "clamp",
        "gizmo_x_axis_color": "#123456",
        "gizmo_y_axis_color": "#123456",
        "gizmo_z_axis_color": "#123456",
        "gizmo_highlight_color": "#123456",
        "gizmo_label_color": "#123456",
    }
    old_value = getattr(base, field_name)
    if field_name in explicit_values:
        new_value = explicit_values[field_name]
    elif isinstance(old_value, bool):
        new_value = not old_value
    elif isinstance(old_value, int):
        new_value = old_value - 1 if old_value > 0 else old_value + 1
    elif isinstance(old_value, float):
        new_value = old_value - 0.05 if old_value >= 1.0 else old_value + 0.05
    else:
        raise AssertionError(f"No change value for {field_name}")
    return replace(base, **{field_name: new_value})


_EXPECTED_CHANGE_ROUTES: dict[str, set[str]] = {
    "use_textures_by_default": {"d3d11_package_affecting_changed"},
    "high_quality_by_default": {"d3d11_package_affecting_changed"},
    "alignment_use_final_output_preview": set(),
    "visible_texture_mode": {"needs_asset_refresh"},
    "render_diagnostic_mode": set(),
    "alpha_handling_mode": set(),
    "texture_probe_source": set(),
    "sampler_probe_mode": set(),
    "diffuse_swizzle_mode": set(),
    "disable_tint": set(),
    "disable_brightness": set(),
    "disable_uv_scale": set(),
    "force_nearest_no_mipmaps": set(),
    "disable_normal_map": {"support_slot_settings_changed", "d3d11_package_affecting_changed"},
    "disable_material_map": {"support_slot_settings_changed", "d3d11_package_affecting_changed"},
    "disable_height_map": {"support_slot_settings_changed", "d3d11_package_affecting_changed"},
    "disable_all_support_maps": {"support_slot_settings_changed", "d3d11_package_affecting_changed"},
    "flip_texture_v": {"support_slot_settings_changed", "d3d11_package_affecting_changed"},
    "disable_lighting": set(),
    "disable_depth_test": set(),
    "show_texture_debug_strip": set(),
    "show_physics_overlay": set(),
    "show_physics_simulation_preview": set(),
    "enable_tool_pbd_cloth_preview": {"d3d11_render_tuning_changed"},
    "pause_tool_pbd_cloth_preview": {"d3d11_render_tuning_changed"},
    "tool_pbd_cloth_wind_strength": {"d3d11_render_tuning_changed"},
    "tool_pbd_cloth_wind_direction_degrees": {"d3d11_render_tuning_changed"},
    "show_tool_pbd_cloth_pins": {"d3d11_render_tuning_changed"},
    "show_tool_pbd_cloth_colliders": {"d3d11_render_tuning_changed"},
    "solo_batch_index": set(),
    "preview_texture_max_dimension": {"needs_asset_refresh"},
    "low_quality_texture_max_dimension": {"needs_asset_refresh"},
    "max_anisotropy": {"d3d11_render_tuning_changed"},
    "d3d11_mip_lod_bias": {"d3d11_render_tuning_changed"},
    "d3d11_view_mode": {"d3d11_render_tuning_changed"},
    "d3d11_cull_back_faces": {"d3d11_render_tuning_changed"},
    "d3d11_light_azimuth_degrees": {"d3d11_render_tuning_changed"},
    "d3d11_light_elevation_degrees": {"d3d11_render_tuning_changed"},
    "d3d11_normal_y_mode": {"d3d11_render_tuning_changed"},
    "d3d11_ao_strength": {"d3d11_render_tuning_changed"},
    "d3d11_roughness_bias": {"d3d11_render_tuning_changed"},
    "d3d11_metalness_scale": {"d3d11_render_tuning_changed"},
    "d3d11_environment_strength": {"d3d11_render_tuning_changed"},
    "d3d11_emissive_gain": {"d3d11_render_tuning_changed"},
    "d3d11_tone_exposure": {"d3d11_render_tuning_changed"},
    "d3d11_tone_contrast": {"d3d11_render_tuning_changed"},
    "d3d11_tone_gamma": {"d3d11_render_tuning_changed"},
    "d3d11_texture_address_mode": {"d3d11_render_tuning_changed"},
    "ambient_strength": {"d3d11_render_tuning_changed"},
    "diffuse_wrap_bias": {"d3d11_render_tuning_changed"},
    "diffuse_light_scale": {"d3d11_render_tuning_changed"},
    "orbit_sensitivity": {"d3d11_render_tuning_changed"},
    "pan_sensitivity": {"d3d11_render_tuning_changed"},
    "invert_orbit_x": {"d3d11_render_tuning_changed"},
    "invert_orbit_y": {"d3d11_render_tuning_changed"},
    "invert_pan_x": {"d3d11_render_tuning_changed"},
    "invert_pan_y": {"d3d11_render_tuning_changed"},
    "gizmo_x_axis_color": set(),
    "gizmo_y_axis_color": set(),
    "gizmo_z_axis_color": set(),
    "gizmo_highlight_color": set(),
    "gizmo_label_color": set(),
    "gizmo_line_thickness_pixels": set(),
    "gizmo_size_scale": set(),
    "gizmo_label_size_pixels": set(),
    "gizmo_handle_size_pixels": set(),
    "normal_strength_cap": {"d3d11_package_affecting_changed"},
    "normal_strength_floor": {"d3d11_package_affecting_changed"},
    "height_effect_max": {"d3d11_package_affecting_changed"},
    "cavity_clamp_min": set(),
    "cavity_clamp_max": set(),
    "specular_base": {"d3d11_render_tuning_changed"},
    "specular_min": set(),
    "specular_max": {"d3d11_render_tuning_changed"},
    "shininess_base": set(),
    "shininess_min": {"d3d11_render_tuning_changed"},
    "shininess_max": {"d3d11_render_tuning_changed"},
    "height_shininess_boost": set(),
}


class _FakeD3D11Host:
    def __init__(self, result: bool) -> None:
        self.result = result
        self.render_tuning_settings: list[ModelPreviewRenderSettings] = []

    def set_render_tuning(self, settings: ModelPreviewRenderSettings) -> bool:
        self.render_tuning_settings.append(settings)
        return self.result


class _FakePreviewSettingsWindow(ArchivePreviewSettingsMixin):
    def __init__(self, *, live_tuning_result: bool) -> None:
        self._model_preview_render_settings = ModelPreviewRenderSettings()
        self.archive_d3d11_preview_host = _FakeD3D11Host(live_tuning_result)
        self.current_archive_preview_result = ArchivePreviewResult(
            status="ok",
            preferred_view="model",
            native_preview_package_path="native-package",
        )
        self.archive_preview_showing_loose = False
        self._settings_ready = True
        self.status_messages: list[tuple[str, bool]] = []
        self.refreshed_assets = 0
        self.scheduled_asset_refreshes = 0
        self.saved_settings = 0
        self.synced_controls = 0
        self.refreshed_status = 0
        self.updated_preview_models: list[object] = []

    def findChildren(self, *_args: object, **_kwargs: object) -> list[object]:
        return []

    def _archive_model_renderer_backend(self) -> str:
        return ARCHIVE_MODEL_RENDERER_D3D11

    def _refresh_current_model_preview_assets(self, *, force: bool = False) -> None:
        self.refreshed_assets += 1

    def _schedule_current_model_preview_asset_refresh(self) -> None:
        self.scheduled_asset_refreshes += 1

    def set_status_message(self, message: str, error: bool = False) -> None:
        self.status_messages.append((message, error))

    def _update_archive_model_action_controls(self, preview_model: object) -> None:
        self.updated_preview_models.append(preview_model)

    def _refresh_archive_preview_settings_status(self) -> None:
        self.refreshed_status += 1

    def _sync_model_preview_settings_controls(self) -> None:
        self.synced_controls += 1

    def schedule_settings_save(self) -> None:
        self.saved_settings += 1


def test_model_preview_settings_status_preserves_default_summary_and_details() -> None:
    status, details = model_preview_settings_status(ModelPreviewRenderSettings())

    assert status == (
        "3D Preview: Visible Mesh Base First | Lit | ON: Textures yes, "
        "Support-map shading yes | Checked disables: Brightness, UV scale, HKX physics overlay"
    )
    assert "Visible texture mode: Mesh Base First" in details
    assert "Diagnostic render mode: Lit" in details
    assert "Use textures when available: enabled" in details
    assert "Support-map preview shading: enabled" in details
    assert "Alpha handling: Default Discard" in details
    assert "Texture source probe: Base" in details
    assert "Sampler probe: Normal Bindings" in details
    assert "Diffuse swizzle: RGBA" in details
    assert "Tool-side PBD physics preview: disabled" in details
    assert "PBD physics wind: 0.00 @ 35 deg" in details
    assert "Solo batch index: -1" in details


def test_model_preview_settings_status_preserves_unknown_values_and_disabled_flags() -> None:
    settings = ModelPreviewRenderSettings(
        use_textures_by_default=False,
        high_quality_by_default=False,
        visible_texture_mode="custom_visible",
        render_diagnostic_mode="custom_render",
        alpha_handling_mode="custom_alpha",
        texture_probe_source="custom_probe",
        sampler_probe_mode="custom_sampler",
        diffuse_swizzle_mode="custom_swizzle",
        disable_tint=False,
        disable_brightness=False,
        disable_uv_scale=False,
        show_physics_overlay=False,
        tool_pbd_cloth_wind_strength=1.25,
        tool_pbd_cloth_wind_direction_degrees=90,
        solo_batch_index=3,
    )

    status, details = model_preview_settings_status(settings)

    assert status == (
        "3D Preview: Visible custom_visible | custom_render | ON: Textures no, "
        "Support-map shading no | Checked disables: None"
    )
    assert "Alpha handling: custom_alpha" in details
    assert "Texture source probe: custom_probe" in details
    assert "Sampler probe: custom_sampler" in details
    assert "Diffuse swizzle: custom_swizzle" in details
    assert "Checked disable toggles: None" in details
    assert "PBD physics wind: 1.25 @ 90 deg" in details
    assert "Solo batch index: 3" in details


def test_model_preview_settings_change_flags_detect_asset_refresh() -> None:
    previous = ModelPreviewRenderSettings()
    current = ModelPreviewRenderSettings(visible_texture_mode="layer_aware_visible")

    flags = model_preview_settings_change_flags(previous, current)

    assert flags.needs_asset_refresh is True
    assert flags.support_slot_settings_changed is False
    assert flags.d3d11_package_affecting_changed is False
    assert flags.d3d11_render_tuning_changed is False


def test_model_preview_settings_change_flags_detect_support_slot_package_changes() -> None:
    previous = ModelPreviewRenderSettings()
    current = ModelPreviewRenderSettings(disable_normal_map=True)

    flags = model_preview_settings_change_flags(previous, current)

    assert flags.needs_asset_refresh is False
    assert flags.support_slot_settings_changed is True
    assert flags.d3d11_package_affecting_changed is True
    assert flags.d3d11_render_tuning_changed is False


def test_model_preview_settings_change_flags_detect_render_tuning_only_changes() -> None:
    previous = ModelPreviewRenderSettings()
    current = ModelPreviewRenderSettings(d3d11_tone_gamma=2.0)

    flags = model_preview_settings_change_flags(previous, current)

    assert flags.needs_asset_refresh is False
    assert flags.support_slot_settings_changed is False
    assert flags.d3d11_package_affecting_changed is False
    assert flags.d3d11_render_tuning_changed is True


def test_model_preview_settings_change_flags_routes_every_declared_setting() -> None:
    field_names = {field.name for field in fields(ModelPreviewRenderSettings)}

    assert set(_EXPECTED_CHANGE_ROUTES) == field_names
    for field_name, expected_routes in _EXPECTED_CHANGE_ROUTES.items():
        flags = model_preview_settings_change_flags(
            ModelPreviewRenderSettings(),
            _changed_settings(field_name),
        )

        assert _flag_names(flags) == expected_routes, field_name


def test_model_preview_settings_change_flags_routes_known_3d_setting_regressions() -> None:
    expected_routes_by_field = {
        "d3d11_view_mode": {"d3d11_render_tuning_changed"},
        "max_anisotropy": {"d3d11_render_tuning_changed"},
        "diffuse_wrap_bias": {"d3d11_render_tuning_changed"},
        "preview_texture_max_dimension": {"needs_asset_refresh"},
    }

    for field_name, expected_routes in expected_routes_by_field.items():
        flags = model_preview_settings_change_flags(
            ModelPreviewRenderSettings(),
            _changed_settings(field_name),
        )

        assert _flag_names(flags) == expected_routes, field_name


def test_model_preview_settings_live_d3d11_tuning_success_does_not_rebuild_preview() -> None:
    window = _FakePreviewSettingsWindow(live_tuning_result=True)
    current = ModelPreviewRenderSettings(d3d11_view_mode="normal")

    window._handle_model_preview_settings_changed(current)

    assert window.archive_d3d11_preview_host.render_tuning_settings == [current]
    assert window.refreshed_assets == 0
    assert window.scheduled_asset_refreshes == 0
    assert window.status_messages == [("Updated native D3D11 render tuning.", False)]
    assert window.saved_settings == 1


def test_model_preview_settings_live_d3d11_tuning_failure_reloads_preview() -> None:
    window = _FakePreviewSettingsWindow(live_tuning_result=False)

    window._handle_model_preview_settings_changed(ModelPreviewRenderSettings(d3d11_view_mode="normal"))

    assert len(window.archive_d3d11_preview_host.render_tuning_settings) == 1
    assert window.refreshed_assets == 1
    assert window.scheduled_asset_refreshes == 0
    assert window.status_messages == [("Reloading native D3D11 preview to apply render settings.", False)]
    assert window.saved_settings == 1
