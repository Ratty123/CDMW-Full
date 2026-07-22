"""Archive preview settings presentation state helpers."""

from __future__ import annotations

from dataclasses import dataclass

from cdmw.models import (
    D3D11_PREVIEW_VIEW_MODE_LABELS,
    MODEL_PREVIEW_ALPHA_HANDLING_LABELS,
    MODEL_PREVIEW_DIFFUSE_SWIZZLE_LABELS,
    MODEL_PREVIEW_SAMPLER_PROBE_LABELS,
    MODEL_PREVIEW_TEXTURE_PROBE_SOURCE_LABELS,
    ModelPreviewRenderSettings,
)


@dataclass(frozen=True, slots=True)
class ModelPreviewSettingsChangeFlags:
    needs_asset_refresh: bool
    support_slot_settings_changed: bool
    d3d11_package_affecting_changed: bool
    d3d11_render_tuning_changed: bool


_DISABLE_TOGGLE_FIELDS: tuple[tuple[str, str], ...] = (
    ("disable_tint", "Base tint"),
    ("disable_brightness", "Brightness"),
    ("disable_uv_scale", "UV scale"),
    ("force_nearest_no_mipmaps", "Nearest/no mipmaps"),
    ("disable_normal_map", "Normal map"),
    ("disable_material_map", "Material map"),
    ("disable_height_map", "Height map"),
    ("flip_texture_v", "Flip texture V"),
    ("disable_all_support_maps", "All support maps"),
    ("disable_lighting", "Lighting"),
    ("disable_depth_test", "Depth test"),
    ("show_texture_debug_strip", "Texture debug strip"),
    ("show_physics_overlay", "HKX physics overlay"),
    ("show_physics_simulation_preview", "Legacy HKX guide motion"),
    ("enable_tool_pbd_cloth_preview", "Tool-side PBD physics"),
    ("pause_tool_pbd_cloth_preview", "PBD physics paused"),
    ("show_tool_pbd_cloth_pins", "PBD physics pins"),
    ("show_tool_pbd_cloth_colliders", "PBD physics colliders"),
)


def model_preview_settings_status(settings: ModelPreviewRenderSettings) -> tuple[str, str]:
    view_label = D3D11_PREVIEW_VIEW_MODE_LABELS.get(
        settings.d3d11_view_mode,
        settings.d3d11_view_mode,
    )
    alpha_label = MODEL_PREVIEW_ALPHA_HANDLING_LABELS.get(
        settings.alpha_handling_mode,
        settings.alpha_handling_mode,
    )
    probe_label = MODEL_PREVIEW_TEXTURE_PROBE_SOURCE_LABELS.get(
        settings.texture_probe_source,
        settings.texture_probe_source,
    )
    sampler_label = MODEL_PREVIEW_SAMPLER_PROBE_LABELS.get(
        settings.sampler_probe_mode,
        settings.sampler_probe_mode,
    )
    swizzle_label = MODEL_PREVIEW_DIFFUSE_SWIZZLE_LABELS.get(
        settings.diffuse_swizzle_mode,
        settings.diffuse_swizzle_mode,
    )
    checked_disables = [
        label for field_name, label in _DISABLE_TOGGLE_FIELDS if bool(getattr(settings, field_name))
    ]
    unchecked_disables = [
        label for field_name, label in _DISABLE_TOGGLE_FIELDS if not bool(getattr(settings, field_name))
    ]
    checked_text = ", ".join(checked_disables) if checked_disables else "None"
    status = (
        f"3D Preview: .NET/Vortice {view_label} | "
        f"ON: Textures {'yes' if settings.use_textures_by_default else 'no'}, "
        f"Support-map shading {'yes' if settings.high_quality_by_default else 'no'} | "
        f"Checked disables: {checked_text}"
    )
    detail_lines = [
        f".NET/Vortice view: {view_label}",
        f"Use textures when available: {'enabled' if settings.use_textures_by_default else 'disabled'}",
        f"Support-map preview shading: {'enabled' if settings.high_quality_by_default else 'disabled'}",
        f"Alpha handling: {alpha_label}",
        f"Texture source probe: {probe_label}",
        f"Sampler probe: {sampler_label}",
        f"Diffuse swizzle: {swizzle_label}",
        f"Tool-side PBD physics preview: {'enabled' if settings.enable_tool_pbd_cloth_preview else 'disabled'}",
        f"PBD physics wind: {settings.tool_pbd_cloth_wind_strength:.2f} @ {settings.tool_pbd_cloth_wind_direction_degrees:.0f} deg",
        f"Checked disable toggles: {checked_text}",
        f"Unchecked disable toggles: {', '.join(unchecked_disables) if unchecked_disables else 'None'}",
        f"Solo batch index: {settings.solo_batch_index}",
    ]
    return status, "\n".join(detail_lines)


def model_preview_settings_change_flags(
    previous_settings: ModelPreviewRenderSettings,
    preview_settings: ModelPreviewRenderSettings,
) -> ModelPreviewSettingsChangeFlags:
    needs_asset_refresh = (
        previous_settings.preview_texture_max_dimension != preview_settings.preview_texture_max_dimension
        or previous_settings.low_quality_texture_max_dimension != preview_settings.low_quality_texture_max_dimension
        or previous_settings.visible_texture_mode != preview_settings.visible_texture_mode
    )
    support_slot_settings_changed = (
        previous_settings.disable_all_support_maps != preview_settings.disable_all_support_maps
        or previous_settings.disable_normal_map != preview_settings.disable_normal_map
        or previous_settings.disable_material_map != preview_settings.disable_material_map
        or previous_settings.disable_height_map != preview_settings.disable_height_map
        or previous_settings.flip_texture_v != preview_settings.flip_texture_v
    )
    d3d11_package_affecting_changed = (
        previous_settings.use_textures_by_default != preview_settings.use_textures_by_default
        or previous_settings.high_quality_by_default != preview_settings.high_quality_by_default
        or support_slot_settings_changed
        or previous_settings.normal_strength_floor != preview_settings.normal_strength_floor
        or previous_settings.normal_strength_cap != preview_settings.normal_strength_cap
        or previous_settings.height_effect_max != preview_settings.height_effect_max
        or getattr(previous_settings, "specular_response", None) != getattr(preview_settings, "specular_response", None)
        or getattr(previous_settings, "surface_contrast", None) != getattr(preview_settings, "surface_contrast", None)
    )
    d3d11_render_tuning_changed = (
        previous_settings.max_anisotropy != preview_settings.max_anisotropy
        or previous_settings.d3d11_mip_lod_bias != preview_settings.d3d11_mip_lod_bias
        or previous_settings.d3d11_view_mode != preview_settings.d3d11_view_mode
        or previous_settings.d3d11_cull_back_faces != preview_settings.d3d11_cull_back_faces
        or previous_settings.d3d11_light_azimuth_degrees != preview_settings.d3d11_light_azimuth_degrees
        or previous_settings.d3d11_light_elevation_degrees != preview_settings.d3d11_light_elevation_degrees
        or previous_settings.d3d11_normal_y_mode != preview_settings.d3d11_normal_y_mode
        or previous_settings.d3d11_ao_strength != preview_settings.d3d11_ao_strength
        or previous_settings.d3d11_roughness_bias != preview_settings.d3d11_roughness_bias
        or previous_settings.d3d11_metalness_scale != preview_settings.d3d11_metalness_scale
        or previous_settings.d3d11_environment_strength != preview_settings.d3d11_environment_strength
        or previous_settings.d3d11_emissive_gain != preview_settings.d3d11_emissive_gain
        or previous_settings.d3d11_tone_exposure != preview_settings.d3d11_tone_exposure
        or previous_settings.d3d11_tone_contrast != preview_settings.d3d11_tone_contrast
        or previous_settings.d3d11_tone_gamma != preview_settings.d3d11_tone_gamma
        or previous_settings.d3d11_texture_address_mode != preview_settings.d3d11_texture_address_mode
        or previous_settings.ambient_strength != preview_settings.ambient_strength
        or previous_settings.diffuse_wrap_bias != preview_settings.diffuse_wrap_bias
        or previous_settings.diffuse_light_scale != preview_settings.diffuse_light_scale
        or previous_settings.specular_base != preview_settings.specular_base
        or previous_settings.specular_max != preview_settings.specular_max
        or previous_settings.shininess_min != preview_settings.shininess_min
        or previous_settings.shininess_max != preview_settings.shininess_max
        or previous_settings.orbit_sensitivity != preview_settings.orbit_sensitivity
        or previous_settings.pan_sensitivity != preview_settings.pan_sensitivity
        or previous_settings.invert_orbit_x != preview_settings.invert_orbit_x
        or previous_settings.invert_orbit_y != preview_settings.invert_orbit_y
        or previous_settings.invert_pan_x != preview_settings.invert_pan_x
        or previous_settings.invert_pan_y != preview_settings.invert_pan_y
        or previous_settings.enable_tool_pbd_cloth_preview != preview_settings.enable_tool_pbd_cloth_preview
        or previous_settings.pause_tool_pbd_cloth_preview != preview_settings.pause_tool_pbd_cloth_preview
        or previous_settings.tool_pbd_cloth_wind_strength != preview_settings.tool_pbd_cloth_wind_strength
        or previous_settings.tool_pbd_cloth_wind_direction_degrees != preview_settings.tool_pbd_cloth_wind_direction_degrees
        or previous_settings.show_tool_pbd_cloth_pins != preview_settings.show_tool_pbd_cloth_pins
        or previous_settings.show_tool_pbd_cloth_colliders != preview_settings.show_tool_pbd_cloth_colliders
    )
    return ModelPreviewSettingsChangeFlags(
        needs_asset_refresh=needs_asset_refresh,
        support_slot_settings_changed=support_slot_settings_changed,
        d3d11_package_affecting_changed=d3d11_package_affecting_changed,
        d3d11_render_tuning_changed=d3d11_render_tuning_changed,
    )


__all__ = [
    "ModelPreviewSettingsChangeFlags",
    "model_preview_settings_change_flags",
    "model_preview_settings_status",
]
