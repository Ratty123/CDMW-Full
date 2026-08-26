"""Pure settings-to-protocol payload mapping for the resident .NET preview host."""

from __future__ import annotations

from collections.abc import Mapping

from cdmw.domain.camera_bindings import (
    DEFAULT_MIDDLE_DRAG,
    DEFAULT_RIGHT_DRAG,
    normalize_camera_drag,
    resolve_camera_bindings,
)


def render_tuning_payloads(
    settings: object,
    current_cloth: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    orbit_modifier, pan_modifier = resolve_camera_bindings(
        getattr(settings, "camera_orbit_modifier", None),
        getattr(settings, "camera_pan_modifier", None),
    )
    quality = {
        "max_anisotropy": int(getattr(settings, "max_anisotropy", 16) or 16),
        "d3d11_mip_lod_bias": float(getattr(settings, "d3d11_mip_lod_bias", -2.0)),
        "d3d11_background_color": str(getattr(settings, "d3d11_background_color", "") or ""),
        "d3d11_grid_color": str(getattr(settings, "d3d11_grid_color", "") or ""),
        "d3d11_wire_color": str(getattr(settings, "d3d11_wire_color", "") or ""),
        "d3d11_vertex_color": str(getattr(settings, "d3d11_vertex_color", "") or ""),
        "d3d11_grid_spacing_scale": float(getattr(settings, "d3d11_grid_spacing_scale", 1.0) or 1.0),
        "d3d11_grid_line_count": int(getattr(settings, "d3d11_grid_line_count", 10) or 10),
        "dotnet_view_mode": str(getattr(settings, "d3d11_view_mode", "lit") or "lit"),
        "d3d11_cull_back_faces": bool(getattr(settings, "d3d11_cull_back_faces", False)),
        "d3d11_light_azimuth_degrees": float(getattr(settings, "d3d11_light_azimuth_degrees", -10.0)),
        "d3d11_light_elevation_degrees": float(getattr(settings, "d3d11_light_elevation_degrees", 0.0)),
        "d3d11_normal_y_mode": str(getattr(settings, "d3d11_normal_y_mode", "asset") or "asset"),
        "d3d11_ao_strength": float(getattr(settings, "d3d11_ao_strength", 0.45)),
        "d3d11_roughness_bias": float(getattr(settings, "d3d11_roughness_bias", -0.04)),
        "d3d11_metalness_scale": float(getattr(settings, "d3d11_metalness_scale", 1.45)),
        "d3d11_environment_strength": float(getattr(settings, "d3d11_environment_strength", 0.62)),
        "d3d11_emissive_gain": float(getattr(settings, "d3d11_emissive_gain", 2.2)),
        "d3d11_tone_exposure": float(getattr(settings, "d3d11_tone_exposure", 1.0)),
        "d3d11_tone_contrast": float(getattr(settings, "d3d11_tone_contrast", 1.08)),
        "d3d11_tone_gamma": float(getattr(settings, "d3d11_tone_gamma", 0.92)),
        "d3d11_texture_address_mode": str(getattr(settings, "d3d11_texture_address_mode", "wrap") or "wrap"),
        "ambient_strength": float(getattr(settings, "ambient_strength", 0.84) or 0.84),
        "diffuse_wrap_bias": float(getattr(settings, "diffuse_wrap_bias", 0.58) or 0.58),
        "diffuse_light_scale": float(getattr(settings, "diffuse_light_scale", 0.62) or 0.62),
        "specular_base": float(getattr(settings, "specular_base", 0.055) or 0.055),
        "specular_max": float(getattr(settings, "specular_max", 0.52) or 0.52),
        "shininess_max": float(getattr(settings, "shininess_max", 152.0) or 152.0),
        "orbit_sensitivity": float(getattr(settings, "orbit_sensitivity", 0.22) or 0.22),
        "pan_sensitivity": float(getattr(settings, "pan_sensitivity", 0.60) or 0.60),
        "invert_orbit_x": bool(getattr(settings, "invert_orbit_x", False)),
        "invert_orbit_y": bool(getattr(settings, "invert_orbit_y", False)),
        "invert_pan_x": bool(getattr(settings, "invert_pan_x", False)),
        "invert_pan_y": bool(getattr(settings, "invert_pan_y", False)),
        "camera_orbit_modifier": orbit_modifier,
        "camera_pan_modifier": pan_modifier,
        "camera_middle_drag": normalize_camera_drag(
            getattr(settings, "camera_middle_drag", None),
            DEFAULT_MIDDLE_DRAG,
        ),
        "camera_right_drag": normalize_camera_drag(
            getattr(settings, "camera_right_drag", None),
            DEFAULT_RIGHT_DRAG,
        ),
    }
    cloth = dict(current_cloth)
    cloth.update(
        {
            "enabled": bool(getattr(settings, "enable_tool_pbd_cloth_preview", False)),
            "paused": bool(getattr(settings, "pause_tool_pbd_cloth_preview", False)),
            "wind_strength": float(getattr(settings, "tool_pbd_cloth_wind_strength", 0.0) or 0.0),
            "wind_direction_degrees": float(
                getattr(settings, "tool_pbd_cloth_wind_direction_degrees", 35.0) or 35.0
            ),
            "show_pins": bool(getattr(settings, "show_tool_pbd_cloth_pins", False)),
            "show_colliders": bool(getattr(settings, "show_tool_pbd_cloth_colliders", False)),
        }
    )
    return quality, cloth


__all__ = ["render_tuning_payloads"]
