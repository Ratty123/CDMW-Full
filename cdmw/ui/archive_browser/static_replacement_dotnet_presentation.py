"""Pure resident .NET presentation payload helpers for Replacement Builder."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from typing import Any


_RENDER_SETTING_FIELDS = (
    "use_textures_by_default",
    "high_quality_by_default",
    "render_diagnostic_mode",
    "disable_lighting",
    "disable_depth_test",
    "disable_tint",
    "disable_brightness",
    "disable_uv_scale",
    "disable_normal_map",
    "disable_material_map",
    "disable_height_map",
    "disable_all_support_maps",
    "flip_texture_v",
    "force_nearest_no_mipmaps",
    "d3d11_view_mode",
    "d3d11_cull_back_faces",
    "d3d11_light_azimuth_degrees",
    "d3d11_light_elevation_degrees",
    "d3d11_normal_y_mode",
    "d3d11_ao_strength",
    "d3d11_roughness_bias",
    "d3d11_metalness_scale",
    "d3d11_environment_strength",
    "d3d11_emissive_gain",
    "d3d11_tone_exposure",
    "d3d11_tone_contrast",
    "d3d11_tone_gamma",
    "d3d11_texture_address_mode",
    "max_anisotropy",
    "d3d11_mip_lod_bias",
    "ambient_strength",
    "diffuse_wrap_bias",
    "diffuse_light_scale",
    "normal_strength_cap",
    "height_effect_max",
    "specular_base",
    "specular_max",
    "shininess_max",
    "orbit_sensitivity",
    "pan_sensitivity",
    "invert_orbit_x",
    "invert_orbit_y",
    "invert_pan_x",
    "invert_pan_y",
)


def _json_value(value: object) -> object:
    if is_dataclass(value):
        return {str(key): _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


def effective_builder_comparison_mode(
    comparison_mode: object,
    mesh_edit_active: bool,
) -> str:
    """Resolve the resident role layout without changing the saved placement choice."""
    if mesh_edit_active:
        return "replacement_only"
    return str(comparison_mode or "replacement_only").strip().lower()


def builder_presentation_state(
    *,
    comparison_mode: object,
    camera: Mapping[str, object] | None,
    render_settings: object,
    grid_visible: bool,
    gizmo_visible: bool,
    part_pick_enabled: bool,
    mesh_edit_active: bool = False,
    selected_source_indices: Sequence[int] = (),
    selected_target_source_indices: Sequence[int] = (),
    selected_original_indices: Sequence[int] = (),
    selected_target_original_indices: Sequence[int] = (),
    hovered_source_index: int = -1,
    source_part_adjustments: Mapping[object, object] | None = None,
    uv_state: Mapping[str, object] | None = None,
    side_by_side_split_ratio: float = 0.5,
) -> dict[str, object]:
    mode = str(comparison_mode or "replacement_only").strip().lower()
    active_view = {
        "original_only": "reference",
        "overlay": "comparison",
        "side_by_side": "comparison",
    }.get(mode, "editable")
    adjustments = {
        str(key): _json_value(value)
        for key, value in (source_part_adjustments or {}).items()
    }
    hidden = sorted(
        int(key)
        for key, value in (source_part_adjustments or {}).items()
        if not bool(getattr(value, "enabled", True))
    )
    settings = {
        field: _json_value(getattr(render_settings, field))
        for field in _RENDER_SETTING_FIELDS
        if hasattr(render_settings, field)
    }
    d3d11_view_mode = str(settings.get("d3d11_view_mode", "lit") or "lit").strip().lower()
    diagnostic_mode = str(settings.get("render_diagnostic_mode", "lit") or "lit").strip().lower()
    effective_view_mode = d3d11_view_mode if d3d11_view_mode != "lit" else diagnostic_mode
    display_mode = {
        "wire": "wire",
        "wireframe": "wire",
        "vertices": "vertices",
        "wire_vertices": "wire_vertices",
        "xray": "xray",
    }.get(effective_view_mode, "textured")
    if mesh_edit_active:
        display_mode = "wire_vertices"
    material_debug_mode = {
        "base": 1,
        "base_color": 1,
        "base_direct": 1,
        "base_no_tint": 1,
        "albedo_base_only": 1,
        "normal": 2,
        "normal_raw": 2,
        "roughness": 3,
        "metallic": 4,
        "metalness": 4,
        "emissive": 5,
        "specular": 6,
        "specular_gloss": 6,
        "uv": 8,
        "uv_checker": 8,
        "base_alpha": 9,
        "part_id": 10,
        "material_raw": 11,
        "material_response": 11,
        "layer_mask": 12,
        "masked_layer_contribution": 12,
    }.get(effective_view_mode, 0)
    return {
        "active_view": active_view,
        "comparison_mode": mode,
        "side_by_side_split_ratio": max(
            0.18,
            min(0.82, float(side_by_side_split_ratio)),
        ),
        "camera": _json_value(dict(camera or {})),
        "display": {
            "mode": display_mode,
            "material_debug_mode": material_debug_mode,
            "grid_visible": bool(grid_visible),
            "gizmo_visible": bool(gizmo_visible),
            "part_pick_enabled": bool(part_pick_enabled),
            "quality": settings,
        },
        "highlights": {
            "source_indices": sorted(
                {
                    *(int(index) for index in selected_source_indices),
                    *(int(index) for index in selected_target_source_indices),
                }
            ),
            "original_indices": sorted(
                {
                    *(int(index) for index in selected_original_indices),
                    *(int(index) for index in selected_target_original_indices),
                }
            ),
            "hovered_source_index": int(hovered_source_index),
        },
        "visibility": {"hidden_submesh_indices": hidden},
        "part_transforms": adjustments,
        "uv": _json_value(dict(uv_state or {})),
    }


def builder_part_highlight_state(
    *,
    selection_active: bool,
    highlighted_source_indices: Sequence[int] = (),
    highlighted_original_indices: Sequence[int] = (),
    hovered_source_index: int = -1,
    hidden_source_indices: Sequence[int] = (),
    grid_visible: bool,
    gizmo_visible: bool,
    part_pick_enabled: bool,
) -> dict[str, object]:
    """Build a resident selection update from logical Builder part indices."""
    try:
        hovered_index = int(hovered_source_index)
    except (TypeError, ValueError):
        hovered_index = -1
    if not part_pick_enabled or hovered_index < 0:
        hovered_index = -1
    source_indices = (
        sorted({int(index) for index in highlighted_source_indices if int(index) >= 0})
        if selection_active
        else []
    )
    original_indices = (
        sorted({int(index) for index in highlighted_original_indices if int(index) >= 0})
        if selection_active
        else []
    )
    return {
        "display": {
            "grid_visible": bool(grid_visible),
            "gizmo_visible": bool(gizmo_visible),
            "part_pick_enabled": bool(part_pick_enabled),
        },
        "highlights": {
            "source_indices": source_indices,
            "original_indices": original_indices,
            "hovered_source_index": hovered_index,
        },
        "visibility": {
            "hidden_submesh_indices": sorted(
                {int(index) for index in hidden_source_indices if int(index) >= 0}
            ),
        },
    }


def send_resident_presentation_state(
    dialog: object,
    state: Mapping[str, object],
) -> bool:
    if not bool(getattr(dialog, "_mesh_editor_embedded_dotnet_active", False)):
        return False
    sender = getattr(dialog, "_mesh_editor_embedded_set_presentation_state", None)
    if not callable(sender):
        return False
    try:
        return bool(sender(dict(state)))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


__all__ = [
    "builder_part_highlight_state",
    "builder_presentation_state",
    "effective_builder_comparison_mode",
    "send_resident_presentation_state",
]
