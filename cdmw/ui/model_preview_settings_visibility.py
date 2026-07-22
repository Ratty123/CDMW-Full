"""Renderer-specific visibility rules for model preview settings."""

from __future__ import annotations

from cdmw.models import clamp_archive_performance_settings, clamp_model_preview_render_settings
from cdmw.ui.model_preview_gizmo_settings import GIZMO_APPEARANCE_SETTING_FIELDS


_QUALITY_LIGHTING_SETTING_FIELDS = (
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
)

DOTNET_CAMERA_INPUT_SETTING_FIELDS = (
    "orbit_sensitivity",
    "pan_sensitivity",
    "invert_orbit_x",
    "invert_orbit_y",
    "invert_pan_x",
    "invert_pan_y",
)

DOTNET_GIZMO_APPEARANCE_SETTING_FIELDS = GIZMO_APPEARANCE_SETTING_FIELDS

# The shared dialog owns camera input and placement-Gizmo preferences. Material,
# sampler, lighting, topology, and display controls stay on their resident
# .NET/Builder surfaces.
DOTNET_SUPPORTED_PREVIEW_SETTINGS_BY_TAB = {
    "General": (),
    "Quality / Lighting": (),
    "Controls": DOTNET_CAMERA_INPUT_SETTING_FIELDS,
    "Gizmo": DOTNET_GIZMO_APPEARANCE_SETTING_FIELDS,
}

DOTNET_SUPPORTED_PREVIEW_SETTING_FIELDS = frozenset(
    field
    for fields in DOTNET_SUPPORTED_PREVIEW_SETTINGS_BY_TAB.values()
    for field in fields
)

_DOTNET_SETTING_EFFECTS = {
    "orbit_sensitivity": "sets resident camera orbit degrees per dragged pixel",
    "pan_sensitivity": "sets resident camera pan distance per dragged pixel",
    "invert_orbit_x": "reverses horizontal resident-camera orbit input",
    "invert_orbit_y": "reverses vertical resident-camera orbit input",
    "invert_pan_x": "reverses horizontal resident-camera pan input",
    "invert_pan_y": "reverses vertical resident-camera pan input",
    "gizmo_x_axis_color": "sets the placement Gizmo X-axis color",
    "gizmo_y_axis_color": "sets the placement Gizmo Y-axis color",
    "gizmo_z_axis_color": "sets the placement Gizmo Z-axis color",
    "gizmo_highlight_color": "sets the active and hovered Gizmo color",
    "gizmo_label_color": "sets the Gizmo label color",
    "gizmo_line_thickness_pixels": "sets Gizmo line thickness",
    "gizmo_size_scale": "scales the complete Gizmo",
    "gizmo_label_size_pixels": "sets Gizmo label font size",
    "gizmo_handle_size_pixels": "sets Gizmo handle size and hit geometry",
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
            for field in _QUALITY_LIGHTING_SETTING_FIELDS
        },
        "Controls": {
            "orbit_sensitivity": sliders["orbit_sensitivity"],
            "pan_sensitivity": sliders["pan_sensitivity"],
            "invert_orbit_x": dialog.invert_orbit_x_checkbox,
            "invert_orbit_y": dialog.invert_orbit_y_checkbox,
            "invert_pan_x": dialog.invert_pan_x_checkbox,
            "invert_pan_y": dialog.invert_pan_y_checkbox,
        },
        "Gizmo": dict(dialog.gizmo_settings_panel.controls_by_key),
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
    # This value now selects a settings layout, not a renderer.  The historical
    # native value preserves the full Archive Browser presentation controls.
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
    for tab, visible in (
        (dialog._general_tab, not dotnet),
        (dialog._quality_tab, not dotnet),
        (dialog._controls_tab, True),
        (dialog._gizmo_tab, dotnet),
    ):
        tab_index = dialog.tabs.indexOf(tab)
        if tab_index >= 0:
            dialog.tabs.setTabVisible(tab_index, visible)
    controls_index = dialog.tabs.indexOf(dialog._controls_tab)
    if controls_index >= 0:
        dialog.tabs.setTabText(controls_index, "Camera Input" if dotnet else "Controls")
    if dotnet and dialog.tabs.currentWidget() not in (dialog._controls_tab, dialog._gizmo_tab):
        dialog.tabs.setCurrentWidget(dialog._controls_tab)
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
    dialog.advanced_warning_label.setVisible(not dotnet)
    if dotnet:
        dialog.disable_tint_checkbox.setText("Ignore material tint")
        dialog.disable_brightness_checkbox.setText("Ignore texture brightness")
        dialog.disable_uv_scale_checkbox.setText("Ignore preview UV scale")
        dialog.intro_label.setText(
            "Camera input and placement-Gizmo settings for the embedded .NET/Vortice Mesh Editor preview. Changes are sent live and saved with Preview Settings."
        )
        dialog.general_hint_label.setText(
            "Renderer appearance is controlled directly from the Mesh Editor viewport."
        )
        dialog.d3d11_hint_label.setText(
            "Archive Browser renderer settings are hidden while .NET/Vortice owns the Mesh Editor preview."
        )
        dialog.quality_hint_label.setText(
            "Material, texture, sampler, and lighting controls are owned by the resident viewport surfaces."
        )
        dialog.controls_usage_hint_label.setText(
            ".NET/Vortice camera controls: left-drag orbits; middle-drag, right-drag, or Shift+left-drag pans; the mouse wheel zooms; Fit resets framing. Each role pane keeps its own camera."
        )
        dialog.inversion_hint_label.setText(
            "Orbit and pan inversion are consumed directly by resident .NET pointer handling and never edit mesh placement or export data."
        )
        dialog.controls_hint_label.setText(
            "Reset Camera Input restores orbit and pan sensitivity while preserving inversion preferences and hidden renderer settings."
        )
        dialog.reset_button.setText("Reset Camera Input")
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
            "Use textures applies resolved preview DDS files when available. Support-map preview shading can sample resolved normal, material, or height maps for an approximate asset-dependent preview."
        )
        dialog.d3d11_hint_label.setText(
            ".NET/Vortice Preview supports texture on/off, culling, view modes, Flip texture V, normal-Y override, sampler address mode, support-map shading, camera controls, zoom, fit, tool-side PBD physics preview, static HKX context when present, and exact DDS diagnostics."
        )
        dialog.quality_hint_label.setText(
            ".NET/Vortice applies these to its shader and sampler directly. Texture resolution normally comes from exact DDS resources; generated fallback maps still use the existing preview cache pipeline."
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
        dialog.reset_button.setText("Reset to Defaults")
    for widget, archive_label, embedded_label in (
        (dialog.d3d11_view_mode_combo, ".NET/Vortice view", ".NET/Vortice view"),
        (dialog.d3d11_normal_y_mode_combo, ".NET/Vortice normal Y", ".NET/Vortice normal Y"),
        (
            dialog.d3d11_texture_address_mode_combo,
            ".NET/Vortice texture address",
            ".NET/Vortice texture address",
        ),
    ):
        label = dialog._form_field_label(widget)
        if label is not None:
            label.setText(embedded_label if dotnet else archive_label)
    if not dotnet:
        dialog.high_quality_checkbox.setToolTip(
            ".NET/Vortice packages and shades resolved normal/material/height support maps only when this is enabled."
        )
    dialog._sync_probe_controls_enabled()


__all__ = [
    "DOTNET_CAMERA_INPUT_SETTING_FIELDS",
    "DOTNET_GIZMO_APPEARANCE_SETTING_FIELDS",
    "DOTNET_SUPPORTED_PREVIEW_SETTING_FIELDS",
    "DOTNET_SUPPORTED_PREVIEW_SETTINGS_BY_TAB",
    "initialize_preview_settings_state",
    "preview_setting_widgets_by_tab",
    "sync_renderer_specific_controls",
]
