"""Shared material-override payload rules for resident Mesh Editor previews."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


MATERIAL_OVERRIDE_KEYS = (
    "texture_brightness",
    "roughness",
    "roughness_hint_present",
    "metalness",
    "metalness_hint_present",
    "specular",
    "specular_hint_present",
    "height_scale",
    "emissive_intensity",
    "emissive_color",
    "emissive_color_authoritative",
    "emissive_scalar_mask",
    "contrast",
    "saturation",
    "gamma",
    "tint_color",
)

SCALAR_MATERIAL_OVERRIDE_KEYS = (
    "texture_brightness",
    "roughness",
    "metalness",
    "specular",
    "height_scale",
    "emissive_intensity",
    "contrast",
    "saturation",
    "gamma",
)

COLOR_MATERIAL_OVERRIDE_KEYS = ("emissive_color", "tint_color")

BOOLEAN_MATERIAL_OVERRIDE_KEYS = (
    "roughness_hint_present",
    "metalness_hint_present",
    "specular_hint_present",
    "emissive_color_authoritative",
    "emissive_scalar_mask",
)

DEFAULT_MATERIAL_OVERRIDES: Mapping[str, object] = {
    "texture_brightness": 1.0,
    "roughness": 0.0,
    "roughness_hint_present": False,
    "metalness": 0.0,
    "metalness_hint_present": False,
    "specular": 0.0,
    "specular_hint_present": False,
    "height_scale": 0.0,
    "emissive_intensity": 0.0,
    "emissive_color": [0.35, 0.68, 1.0],
    "emissive_color_authoritative": False,
    "emissive_scalar_mask": False,
    "contrast": 1.0,
    "saturation": 1.0,
    "gamma": 1.0,
    "tint_color": [1.0, 1.0, 1.0],
}


def material_override_groups_for_native_triangle_groups(
    triangle_groups: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    groups: list[Mapping[str, object]] = []
    for triangle_group in triangle_groups:
        source_index = coerce_source_index(triangle_group.get("source_submesh_index"))
        if source_index is None or source_index < 0:
            continue
        group: dict[str, object] = {
            "source_submesh_indices": [source_index],
            "editor_role": "replacement_preview",
        }
        for key in ("material_name", "texture_name"):
            if key in triangle_group:
                group[key] = triangle_group[key]
        if "material_name" in group or "texture_name" in group:
            group.update(DEFAULT_MATERIAL_OVERRIDES)
        for key in MATERIAL_OVERRIDE_KEYS:
            if key in triangle_group:
                group[key] = triangle_group[key]
        for key in ("roughness", "metalness", "specular"):
            presence_key = f"{key}_hint_present"
            if key in triangle_group and presence_key not in triangle_group:
                group[presence_key] = True
        if (
            "emissive_color" in triangle_group
            and "emissive_color_authoritative" not in triangle_group
        ):
            group["emissive_color_authoritative"] = True
        if len(group) > 2:
            groups.append(group)
    return tuple(groups)


def sanitized_material_override_values(
    overrides: Mapping[str, object],
    *,
    include_defaults: bool,
) -> dict[str, object]:
    values: dict[str, object] = {}
    defaults = DEFAULT_MATERIAL_OVERRIDES if include_defaults else {}
    invalid_emissive_color = (
        "emissive_color" in overrides
        and _finite_color(overrides["emissive_color"]) is None
    )
    for key in SCALAR_MATERIAL_OVERRIDE_KEYS:
        if key not in overrides:
            continue
        parsed = _finite_float_or_none(overrides[key])
        if parsed is not None:
            values[key] = parsed
        elif key in defaults:
            values[key] = defaults[key]
    for key in COLOR_MATERIAL_OVERRIDE_KEYS:
        if key not in overrides:
            continue
        parsed_color = _finite_color(overrides[key])
        if parsed_color is not None:
            values[key] = parsed_color
        elif key in defaults:
            default = defaults[key]
            values[key] = list(default) if isinstance(default, list) else default
    for key in BOOLEAN_MATERIAL_OVERRIDE_KEYS:
        if key in overrides:
            values[key] = (
                False
                if key == "emissive_color_authoritative" and invalid_emissive_color
                else bool(overrides[key])
            )
        elif key in defaults:
            values[key] = bool(defaults[key])
    if (
        "emissive_color" in values
        and "emissive_color_authoritative" not in overrides
        and not invalid_emissive_color
    ):
        values["emissive_color_authoritative"] = True
    for key in ("roughness", "metalness", "specular"):
        presence_key = f"{key}_hint_present"
        if key in overrides and presence_key not in overrides:
            values[presence_key] = True
    return values


def coerce_source_index(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None


def _finite_color(value: object) -> list[float] | None:
    if not isinstance(value, (tuple, list)) or len(value) < 3:
        return None
    parsed = [_finite_float_or_none(component) for component in value[:3]]
    if any(component is None for component in parsed):
        return None
    return [float(component) for component in parsed if component is not None]


def _finite_float_or_none(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None
