"""Renderer-specific visibility rules for model preview settings."""

from __future__ import annotations

from cdmw.models import clamp_archive_performance_settings, clamp_model_preview_render_settings


DOTNET_SUPPORTED_PREVIEW_SETTINGS_BY_TAB = {
    "General": (
        "use_textures_by_default",
        "high_quality_by_default",
        "disable_all_support_maps",
        "disable_normal_map",
        "disable_material_map",
        "disable_height_map",
        "flip_texture_v",
        "d3d11_cull_back_faces",
        "disable_tint",
        "disable_brightness",
        "disable_uv_scale",
        "disable_depth_test",
        "d3d11_view_mode",
        "d3d11_normal_y_mode",
        "d3d11_texture_address_mode",
    ),
    "Quality / Lighting": (
        "max_anisotropy",
        "d3d11_mip_lod_bias",
        "force_nearest_no_mipmaps",
        "disable_lighting",
        "ambient_strength",
        "diffuse_light_scale",
        "diffuse_wrap_bias",
        "d3d11_light_azimuth_degrees",
        "d3d11_light_elevation_degrees",
        "normal_strength_cap",
        "height_effect_max",
        "specular_base",
        "specular_max",
        "shininess_max",
        "d3d11_ao_strength",
        "d3d11_roughness_bias",
        "d3d11_metalness_scale",
        "d3d11_environment_strength",
        "d3d11_emissive_gain",
        "d3d11_tone_exposure",
        "d3d11_tone_contrast",
        "d3d11_tone_gamma",
    ),
    "Controls": (
        "orbit_sensitivity",
        "pan_sensitivity",
        "invert_orbit_x",
        "invert_orbit_y",
        "invert_pan_x",
        "invert_pan_y",
    ),
}

DOTNET_SUPPORTED_PREVIEW_SETTING_FIELDS = frozenset(
    field
    for fields in DOTNET_SUPPORTED_PREVIEW_SETTINGS_BY_TAB.values()
    for field in fields
)

_DOTNET_SETTING_EFFECTS = {
    "use_textures_by_default": "toggles base-texture sampling in every resident role pane",
    "high_quality_by_default": "enables resolved support maps and the requested anisotropic filtering",
    "disable_all_support_maps": "disables normal, material, height, and emissive support-map shading",
    "disable_normal_map": "removes the resolved normal map from the HLSL lighting path",
    "disable_material_map": "removes resolved roughness, metallic, and specular maps from HLSL shading",
    "disable_height_map": "removes resolved height-map UV displacement from HLSL shading",
    "flip_texture_v": "flips sampled material UVs vertically in the HLSL constant buffer",
    "d3d11_cull_back_faces": "rebuilds the Vortice rasterizer state with back-face culling on or off",
    "disable_tint": "bypasses resolved material tint parameters in the HLSL base-color path",
    "disable_brightness": "bypasses resolved material texture-brightness parameters",
    "disable_uv_scale": "bypasses the active preview UV scale while retaining offset and rotation",
    "disable_depth_test": "switches resident solid rendering between normal and disabled depth testing",
    "d3d11_view_mode": "selects the resident textured or material-debug shader output in every role pane",
    "d3d11_normal_y_mode": "uses the asset normal-Y convention or forces its HLSL inversion state",
    "d3d11_texture_address_mode": "rebuilds the Vortice sampler with wrap or clamp addressing",
    "max_anisotropy": "sets the Vortice sampler anisotropy while support-map preview shading is enabled",
    "d3d11_mip_lod_bias": "sets the Vortice sampler mip LOD bias",
    "force_nearest_no_mipmaps": "switches the Vortice sampler to nearest point filtering",
    "disable_lighting": "bypasses direct and ambient material lighting in the HLSL path",
    "ambient_strength": "scales ambient light supplied to the material shader",
    "diffuse_light_scale": "scales direct diffuse light supplied to the material shader",
    "diffuse_wrap_bias": "changes wrapped diffuse response in the material shader",
    "d3d11_light_azimuth_degrees": "rotates the material shader light horizontally",
    "d3d11_light_elevation_degrees": "rotates the material shader light vertically",
    "normal_strength_cap": "scales tangent-space normal-map strength in the material shader",
    "height_effect_max": "scales height-map UV displacement in the material shader",
    "specular_base": "sets fallback dielectric specular response when no specular map is resolved",
    "specular_max": "scales the final specular response in the material shader",
    "shininess_max": "sets the maximum specular highlight power",
    "d3d11_ao_strength": "controls the ambient-occlusion approximation applied to ambient light",
    "d3d11_roughness_bias": "adds a bias to resolved or fallback roughness",
    "d3d11_metalness_scale": "scales resolved or fallback metalness",
    "d3d11_environment_strength": "scales environment-derived ambient light",
    "d3d11_emissive_gain": "scales resolved or overridden emissive output",
    "d3d11_tone_exposure": "scales final shader exposure",
    "d3d11_tone_contrast": "adjusts final shader contrast",
    "d3d11_tone_gamma": "adjusts final shader gamma",
    "orbit_sensitivity": "sets resident camera orbit degrees per dragged pixel",
    "pan_sensitivity": "sets resident camera pan distance per dragged pixel",
    "invert_orbit_x": "reverses horizontal resident-camera orbit input",
    "invert_orbit_y": "reverses vertical resident-camera orbit input",
    "invert_pan_x": "reverses horizontal resident-camera pan input",
    "invert_pan_y": "reverses vertical resident-camera pan input",
}


def preview_setting_widgets_by_tab(dialog: object) -> dict[str, dict[str, object]]:
    sliders = dialog._slider_controls
    return {
        "General": {
            "use_textures_by_default": dialog.use_textures_checkbox,
            "high_quality_by_default": dialog.high_quality_checkbox,
            "disable_all_support_maps": dialog.disable_all_support_maps_checkbox,
            "disable_normal_map": dialog.disable_normal_map_checkbox,
            "disable_material_map": dialog.disable_material_map_checkbox,
            "disable_height_map": dialog.disable_height_map_checkbox,
            "flip_texture_v": dialog.flip_texture_v_checkbox,
            "d3d11_cull_back_faces": dialog.d3d11_cull_back_faces_checkbox,
            "disable_tint": dialog.disable_tint_checkbox,
            "disable_brightness": dialog.disable_brightness_checkbox,
            "disable_uv_scale": dialog.disable_uv_scale_checkbox,
            "disable_depth_test": dialog.disable_depth_test_checkbox,
            "visible_texture_mode": dialog.visible_texture_mode_combo,
            "d3d11_view_mode": dialog.d3d11_view_mode_combo,
            "render_diagnostic_mode": dialog.render_diagnostic_mode_combo,
            "d3d11_normal_y_mode": dialog.d3d11_normal_y_mode_combo,
            "d3d11_texture_address_mode": dialog.d3d11_texture_address_mode_combo,
            "enable_tool_pbd_cloth_preview": dialog.enable_tool_pbd_cloth_preview_checkbox,
            "pause_tool_pbd_cloth_preview": dialog.pause_tool_pbd_cloth_preview_checkbox,
            "tool_pbd_cloth_wind_strength": sliders["tool_pbd_cloth_wind_strength"],
            "tool_pbd_cloth_wind_direction_degrees": sliders[
                "tool_pbd_cloth_wind_direction_degrees"
            ],
            "show_tool_pbd_cloth_pins": dialog.show_tool_pbd_cloth_pins_checkbox,
            "show_tool_pbd_cloth_colliders": dialog.show_tool_pbd_cloth_colliders_checkbox,
            "reset_tool_pbd_cloth_preview": dialog.reset_tool_pbd_cloth_button,
        },
        "Quality / Lighting": {
            field: (
                dialog.force_nearest_no_mipmaps_checkbox
                if field == "force_nearest_no_mipmaps"
                else dialog.disable_lighting_checkbox
                if field == "disable_lighting"
                else sliders[field]
            )
            for field in DOTNET_SUPPORTED_PREVIEW_SETTINGS_BY_TAB["Quality / Lighting"]
        },
        "Controls": {
            "orbit_sensitivity": sliders["orbit_sensitivity"],
            "pan_sensitivity": sliders["pan_sensitivity"],
            "invert_orbit_x": dialog.invert_orbit_x_checkbox,
            "invert_orbit_y": dialog.invert_orbit_y_checkbox,
            "invert_pan_x": dialog.invert_pan_x_checkbox,
            "invert_pan_y": dialog.invert_pan_y_checkbox,
        },
    }


def initialize_preview_settings_state(
    dialog: object,
    settings: object,
    archive_performance_settings: object,
    archive_renderer_backend: object,
    preview_target: object,
) -> None:
    dialog._base_settings = clamp_model_preview_render_settings(settings)
    dialog._archive_performance_settings = clamp_archive_performance_settings(archive_performance_settings)
    dialog._archive_renderer_backend = dialog._normalize_archive_renderer_backend(archive_renderer_backend)
    normalized_target = str(preview_target or "").strip().lower()
    dialog._preview_target = (
        dialog.PREVIEW_TARGET_DOTNET_VORTICE
        if normalized_target == dialog.PREVIEW_TARGET_DOTNET_VORTICE
        else dialog.PREVIEW_TARGET_NATIVE_D3D11
    )
    dialog._slider_controls = {}


def sync_renderer_specific_controls(dialog: object) -> None:
    d3d11 = dialog.current_archive_renderer_backend() == dialog.ARCHIVE_RENDERER_D3D11
    dotnet = dialog._preview_target == dialog.PREVIEW_TARGET_DOTNET_VORTICE
    legacy = False
    diagnostics_index = dialog.tabs.indexOf(dialog._diagnostics_tab)
    if diagnostics_index >= 0:
        dialog.tabs.setTabVisible(diagnostics_index, legacy)
    dialog._set_form_field_visible(dialog.render_diagnostic_mode_combo, legacy)
    dialog._set_form_field_visible(dialog.visible_texture_mode_combo, not dotnet)
    dialog._set_form_field_visible(dialog.d3d11_view_mode_combo, d3d11)
    dialog._set_form_field_visible(dialog.flip_texture_v_checkbox, True)
    dialog._set_form_field_visible(dialog.d3d11_cull_back_faces_checkbox, d3d11)
    dialog._set_form_field_visible(dialog.d3d11_normal_y_mode_combo, d3d11)
    dialog._set_form_field_visible(dialog.d3d11_texture_address_mode_combo, d3d11)
    for key in (
        "d3d11_mip_lod_bias",
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
    ):
        control = dialog._slider_controls.get(key)
        if control is not None:
            dialog._set_form_field_visible(control, d3d11)
    for widget in (
        dialog.alpha_handling_combo,
        dialog.texture_probe_source_combo,
        dialog.sampler_probe_combo,
        dialog.diffuse_swizzle_combo,
        dialog.disable_tint_checkbox,
        dialog.disable_brightness_checkbox,
        dialog.disable_uv_scale_checkbox,
        dialog.force_nearest_no_mipmaps_checkbox,
        dialog.disable_lighting_checkbox,
        dialog.disable_depth_test_checkbox,
        dialog.show_texture_debug_strip_checkbox,
        dialog.show_physics_overlay_checkbox,
        dialog.show_physics_simulation_preview_checkbox,
        dialog.solo_batch_spin,
    ):
        widget.setVisible(legacy)
    setting_widgets = preview_setting_widgets_by_tab(dialog)
    if dotnet:
        for widgets in setting_widgets.values():
            for field, widget in widgets.items():
                supported = field in DOTNET_SUPPORTED_PREVIEW_SETTING_FIELDS
                dialog._set_form_field_visible(widget, supported)
                widget.setProperty("previewSettingKey", field)
                if supported:
                    tooltip = (
                        f".NET/Vortice: {_DOTNET_SETTING_EFFECTS[field]}. "
                        "Changes are sent live to the resident preview."
                    )
                    widget.setProperty("dotnetEffectTooltip", tooltip)
                    widget.setToolTip(tooltip)
    else:
        for widget in (
            dialog.enable_tool_pbd_cloth_preview_checkbox,
            dialog.pause_tool_pbd_cloth_preview_checkbox,
            dialog.show_tool_pbd_cloth_pins_checkbox,
            dialog.show_tool_pbd_cloth_colliders_checkbox,
            dialog.reset_tool_pbd_cloth_button,
        ):
            dialog._set_form_field_visible(widget, True)
        for key in ("tool_pbd_cloth_wind_strength", "tool_pbd_cloth_wind_direction_degrees"):
            dialog._set_form_field_visible(dialog._slider_controls[key], True)
    dialog.d3d11_hint_label.setVisible(d3d11)
    if dotnet:
        dialog.disable_tint_checkbox.setText("Ignore material tint")
        dialog.disable_brightness_checkbox.setText("Ignore texture brightness")
        dialog.disable_uv_scale_checkbox.setText("Ignore preview UV scale")
        dialog.intro_label.setText(
            "Realtime settings for the embedded .NET/Vortice Mesh Editor preview. Changes are sent to the resident preview immediately."
        )
        dialog.advanced_warning_label.setText(
            "Only settings with an active .NET/Vortice renderer or camera consumer are shown. Texture-dependent controls have an effect only when the mesh provides the corresponding maps."
        )
        dialog.general_hint_label.setText(
            "Texture, support-map, material-adjustment, view-mode, sampler, lighting, and camera controls update the resident .NET/Vortice preview. They do not edit or reload the mesh asset."
        )
        dialog.d3d11_hint_label.setText(
            ".NET/Vortice preview settings are limited to controls handled by its resident D3D11 renderer and camera. Archive-only texture-selection policy and unsupported simulation controls are hidden here."
        )
        dialog.quality_hint_label.setText(
            "Every visible control on this tab is applied live to the resident .NET/Vortice sampler, shader constants, or rasterizer state. Texture- and map-dependent controls require the corresponding resolved material resource."
        )
        dialog.controls_usage_hint_label.setText(
            ".NET/Vortice camera controls: left-drag orbits; middle-drag, right-drag, or Shift+left-drag pans; the mouse wheel zooms; Fit resets framing. Each role pane keeps its own camera."
        )
        dialog.inversion_hint_label.setText(
            "Orbit and pan inversion are consumed directly by resident .NET pointer handling and never edit mesh placement or export data."
        )
        dialog.controls_hint_label.setText(
            "Reset preserves camera inversion preferences while restoring the other preview defaults."
        )
    else:
        dialog.disable_tint_checkbox.setText("Disable base tint")
        dialog.disable_brightness_checkbox.setText("Disable brightness")
        dialog.disable_uv_scale_checkbox.setText("Disable UV scale")
        dialog.intro_label.setText(
            "Realtime model-preview controls for the Archive Browser. Adjust these while the preview is visible to see the result immediately."
        )
        dialog.advanced_warning_label.setText(
            "Advanced diagnostics and render options can be expensive, visually incorrect, asset-dependent, or have no visible effect on some previews. Use them for inspection rather than as guaranteed final rendering."
        )
        dialog.general_hint_label.setText(
            "Use textures applies resolved preview DDS files when available. Support-map preview shading can sample resolved normal, material, or height maps for an approximate asset-dependent preview. Visible texture mode controls how aggressively sidecar-visible layers are allowed to replace the mesh-derived base texture."
        )
        dialog.d3d11_hint_label.setText(
            "Native D3D11 supports texture on/off, culling, D3D11 view modes, Flip texture V, normal-Y override, sampler address mode, support-map shading, camera controls, zoom, fit, tool-side PBD physics preview, static HKX context when present, and native DDS diagnostics."
        )
        dialog.quality_hint_label.setText(
            "Native D3D11 applies these to its shader and sampler directly. Texture resolution normally comes from direct DDS upload; generated fallback maps still use the existing preview cache pipeline."
        )
        dialog.controls_usage_hint_label.setText(
            "Preview controls: left-drag orbits around the model; middle-drag, right-drag, or Shift+left-drag pans; mouse wheel zooms; Fit resets the view framing. These controls only move the preview camera/view."
        )
        dialog.inversion_hint_label.setText(
            "Invert orbit X reverses horizontal orbit: dragging left/right spins around the model in the opposite direction. Invert orbit Y reverses vertical orbit. Pan inversion reverses screen-space panning and never edits the asset."
        )
        dialog.controls_hint_label.setText(
            "Reset keeps the inversion checkboxes as-is so you do not lose your preferred camera controls."
        )
    for widget, native_label, dotnet_label in (
        (dialog.d3d11_view_mode_combo, "D3D11 view mode", "View mode"),
        (dialog.d3d11_normal_y_mode_combo, "D3D11 normal Y", "Normal-map Y"),
        (dialog.d3d11_texture_address_mode_combo, "D3D11 texture address", "Texture address"),
    ):
        label = dialog._form_field_label(widget)
        if label is not None:
            label.setText(dotnet_label if dotnet else native_label)
    if not dotnet:
        dialog.high_quality_checkbox.setToolTip(
            "D3D11 packages and shades resolved normal/material/height support maps only when this is enabled."
        )
    dialog._sync_probe_controls_enabled()


__all__ = [
    "DOTNET_SUPPORTED_PREVIEW_SETTING_FIELDS",
    "DOTNET_SUPPORTED_PREVIEW_SETTINGS_BY_TAB",
    "initialize_preview_settings_state",
    "preview_setting_widgets_by_tab",
    "sync_renderer_specific_controls",
]
