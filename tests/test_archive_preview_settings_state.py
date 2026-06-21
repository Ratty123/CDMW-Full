from __future__ import annotations

from cdmw.models import ModelPreviewRenderSettings
from cdmw.ui.archive_browser.preview_settings_state import (
    model_preview_settings_change_flags,
    model_preview_settings_status,
)


def test_model_preview_settings_status_preserves_default_summary_and_details() -> None:
    status, details = model_preview_settings_status(ModelPreviewRenderSettings())

    assert status == (
        "3D Preview: Visible Mesh Base First | Lit | ON: Textures yes, "
        "Support-map shading yes | Checked disables: Base tint, Brightness, UV scale, HKX physics overlay"
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
