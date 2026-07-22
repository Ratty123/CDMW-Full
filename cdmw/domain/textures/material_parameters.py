"""Pure material-parameter normalization shared by preview and export."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Sequence


@dataclass(frozen=True, slots=True)
class MaterialParameterEvaluation:
    base_brightness: float
    base_color_scale: float
    base_color_lift: int
    gamma: float
    saturation: float
    value_max: int
    auto_balance: int
    shadow_lift: int
    tone_contrast: float
    tint_color: tuple[float, ...]
    brightness_percent: float
    contrast_percent: float
    saturation_percent: float
    gamma_multiplier: float
    tint_adjustment: tuple[float, ...]
    roughness: float | None
    metalness: float | None
    specular: float | None
    roughness_inverted: bool
    metalness_inverted: bool
    force_nonmetal: bool
    roughness_min: int | None
    roughness_scale: float | None
    roughness_max: int | None
    metallic_min: int | None
    metallic_scale: float | None
    metallic_max: int | None
    global_gloss_reduction: float
    gloss_reduction_mode: str
    height_scale: float | None
    relief_source: str
    emissive_intensity: float | None
    emissive_color: tuple[float, ...]
    emissive_role: str


def _float(value: object, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        number = float(default)
    return max(float(minimum), min(float(maximum), number))


def _integer(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        number = int(default)
    return max(int(minimum), min(int(maximum), number))


def _optional_float(value: object, minimum: float, maximum: float) -> float | None:
    if value is None or value == "":
        return None
    try:
        return max(float(minimum), min(float(maximum), float(value)))
    except (TypeError, ValueError, OverflowError):
        return None


def _optional_integer(value: object, minimum: int, maximum: int) -> int | None:
    if value is None or value == "":
        return None
    try:
        return max(int(minimum), min(int(maximum), int(value)))
    except (TypeError, ValueError, OverflowError):
        return None


def _normalized_color(value: object, *, byte_values: bool = False) -> tuple[float, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    raw = tuple(value)
    if len(raw) < 3:
        return ()
    scale = 255.0 if byte_values else 1.0
    try:
        return tuple(max(0.0, min(1.0, float(component) / scale)) for component in raw[:3])
    except (TypeError, ValueError, OverflowError):
        return ()


def normalize_global_gloss_reduction(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if number == 0.0:
        return 0.0
    if -1.0 <= number <= 1.0:
        number *= 100.0
    return max(-100.0, min(100.0, number))


def normalize_basic_control_percent(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if number <= 0.0:
        return 0.0
    if number <= 1.0:
        number *= 100.0
    return max(0.0, min(100.0, number))


def normalize_signed_basic_control_percent(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if number == 0.0:
        return 0.0
    if -1.0 <= number <= 1.0:
        number *= 100.0
    return max(-100.0, min(100.0, number))


def normalize_tone_contrast(value: object) -> float:
    return _float(value, 0.0, -100.0, 100.0)


def normalize_edge_relief_source(value: object) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    normalized = {
        "preserve": "preserve_target",
        "preserve_target_support": "preserve_target",
        "target": "preserve_target",
        "generate": "generate_source",
        "generated": "generate_source",
        "source": "generate_source",
        "source_generated": "generate_source",
    }.get(normalized, normalized)
    return normalized if normalized in {"preserve_target", "generate_source", "hybrid"} else "hybrid"


def normalize_gloss_reduction_mode(value: object) -> str:
    mode = re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(value or "cd_smoothness_low").lower())).strip("_")
    aliases = {
        "cdsmoothnesslow": "cd_smoothness_low",
        "smoothnesslow": "cd_smoothness_low",
        "low": "cd_smoothness_low",
        "cdsmoothnesslowpreservemetal": "cd_smoothness_low_preserve_metal",
        "smoothnesslowpreservemetal": "cd_smoothness_low_preserve_metal",
        "lowpreservemetal": "cd_smoothness_low_preserve_metal",
        "preservemetal": "cd_smoothness_low_preserve_metal",
        "sourceroughnesshigh": "source_roughness_high",
        "roughnesshigh": "source_roughness_high",
        "mattehigh": "source_roughness_high",
        "pbr": "source_roughness_high",
    }
    compact = mode.replace("_", "")
    normalized = aliases.get(compact, mode)
    return normalized if normalized in {
        "cd_smoothness_low",
        "cd_smoothness_low_preserve_metal",
        "source_roughness_high",
    } else "cd_smoothness_low"


def profile_roughness_inverted(profile: object | None) -> bool:
    return bool(profile is not None and (getattr(profile, "roughness_inverted", False) or getattr(profile, "roughness_invert", False)))


def profile_metallic_inverted(profile: object | None) -> bool:
    return bool(profile is not None and (getattr(profile, "metallic_inverted", False) or getattr(profile, "metallic_invert", False)))


def profile_accent_glow_strength(profile: object | None) -> float:
    return 0.0 if profile is None else normalize_basic_control_percent(getattr(profile, "accent_glow_strength", 0.0))


def profile_accent_glow_intensity(profile: object | None) -> float:
    if profile is None:
        return 0.0
    strength = profile_accent_glow_strength(profile)
    maximum = max(1.0, _float(getattr(profile, "accent_glow_intensity_max", 5.5), 5.5, 0.0, 20.0))
    return 1.0 + (maximum - 1.0) * (strength / 100.0)


def profile_source_emissive_enabled(profile: object | None) -> bool:
    return bool(profile is not None and str(getattr(profile, "emissive_mode", "") or "").strip().lower() == "intensity")


def profile_source_emissive_parameter_intensity(profile: object | None) -> float:
    if not profile_source_emissive_enabled(profile):
        return 0.0
    return profile_accent_glow_intensity(profile)


def source_emissive_strength(source: object | None) -> float | None:
    """Read an imported emissive scalar without depending on scene model types."""
    if source is None:
        return None
    candidates: list[object] = []
    has_emissive = False
    direct = getattr(source, "emissive_strength", None)
    if direct is not None:
        try:
            direct_value = float(direct)
        except (TypeError, ValueError, OverflowError):
            direct_value = math.nan
        return max(0.0, direct_value) if math.isfinite(direct_value) else None
    parameters = list(getattr(source, "preview_material_parameters", ()) or ())
    slots = getattr(source, "slots", None)
    if hasattr(slots, "get") and slots.get("emissive") is not None:
        has_emissive = True
    for texture_input in tuple(getattr(source, "preview_material_texture_inputs", ()) or ()):
        if str(getattr(texture_input, "slot_kind", "") or "").strip().lower() == "emissive":
            has_emissive = True
        parameters.extend(tuple(getattr(texture_input, "material_parameters", ()) or ()))
    for parameter in parameters:
        if str(getattr(parameter, "parameter_name", "") or "").strip().lower() != "_emissiveintensity":
            continue
        candidates.append(getattr(parameter, "numeric_value", None))
        candidates.append(getattr(parameter, "value", None))
    values: list[float] = []
    for candidate in candidates:
        try:
            value = float(candidate)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(value):
            values.append(max(0.0, value))
    return max(values) if values else 1.0 if has_emissive else None


def effective_emissive_intensity(
    profile: object | None,
    *,
    source: object | None = None,
    part_adjustment: object | None = None,
) -> float:
    part_strength = source_emissive_strength(part_adjustment)
    base_strength = part_strength if part_strength is not None else source_emissive_strength(source)
    if base_strength is None:
        base_strength = 1.0
    boost = max(1.0, profile_accent_glow_intensity(profile)) if profile is not None else 1.0
    return max(0.0, min(20.0, base_strength * boost))


def _combined_tint(source: object | None, part_adjustment: object | None) -> tuple[tuple[float, ...], tuple[float, ...]]:
    source_tint = _normalized_color(getattr(source, "base_color_factor", ()) if source is not None else ())
    part_tint = _normalized_color(
        getattr(part_adjustment, "material_tint_rgb", ()) if part_adjustment is not None else (),
        byte_values=True,
    )
    if len(source_tint) >= 3:
        multiplier = part_tint if len(part_tint) >= 3 else (1.0, 1.0, 1.0)
        return tuple(source_tint[index] * multiplier[index] for index in range(3)), part_tint
    if len(part_tint) >= 3 and any(abs(component - 1.0) > 0.0001 for component in part_tint):
        return part_tint, part_tint
    return source_tint, part_tint


def evaluate_material_parameters(
    profile: object | None = None,
    *,
    source_slot: object | None = None,
    part_adjustment: object | None = None,
    base_brightness: object = 1.0,
    emissive_role: bool | None = None,
    emissive_intensity: object | None = None,
    emissive_color: object = (),
) -> MaterialParameterEvaluation:
    source = source_slot if source_slot is not None else profile
    brightness_percent = _float(getattr(part_adjustment, "material_brightness", 0.0), 0.0, -100.0, 100.0)
    contrast_percent = _float(getattr(part_adjustment, "material_contrast", 0.0), 0.0, -100.0, 100.0)
    saturation_percent = _float(getattr(part_adjustment, "material_saturation", 0.0), 0.0, -100.0, 100.0)
    gamma_multiplier = _float(getattr(part_adjustment, "material_gamma", 1.0), 1.0, 0.25, 4.0)
    tint_color, tint_adjustment = _combined_tint(source, part_adjustment)
    scale = _float(getattr(source, "base_color_scale", 1.0), 1.0, 0.0, 4.0)
    gamma = _float(getattr(source, "base_color_gamma", 1.0), 1.0, 0.1, 4.0)
    saturation = _float(getattr(source, "base_color_saturation", 1.0), 1.0, 0.0, 4.0)
    tone_contrast = normalize_tone_contrast(getattr(source, "base_color_tone_contrast", 0.0))
    scale = max(0.0, min(4.0, scale * (1.0 + brightness_percent / 100.0)))
    gamma = max(0.1, min(4.0, gamma * gamma_multiplier))
    saturation = max(0.0, min(4.0, saturation * (1.0 + saturation_percent / 100.0)))
    tone_contrast = normalize_tone_contrast(tone_contrast + contrast_percent)

    mask_binding_mode = getattr(profile, "mask_binding_mode", None)
    scalar_surface_mode = mask_binding_mode is None or str(mask_binding_mode or "").strip().lower() in {
        "scratch_scalars",
        "disabled",
    }
    roughness = _optional_float(getattr(profile, "scratch_roughness", None), 0.0, 1.0) if scalar_surface_mode else None
    metalness = _optional_float(getattr(profile, "scratch_metallic", None), 0.0, 1.0) if scalar_surface_mode else None
    specular = _optional_float(getattr(profile, "shine_scalar", None), 0.0, 1.0)
    displacement = _optional_float(getattr(profile, "displacement_scale_multiplier", None), 0.0, 1.0)
    displacement_cap = _optional_float(getattr(profile, "displacement_scale_max", None), 0.0, 1.0)
    edge_present = profile is not None and hasattr(profile, "edge_relief_strength")
    edge_relief = normalize_basic_control_percent(getattr(profile, "edge_relief_strength", 0.0)) / 100.0
    height_scale = max(displacement or 0.0, edge_relief) if displacement is not None or edge_present else None
    if height_scale is not None and displacement_cap is not None:
        height_scale = min(height_scale, displacement_cap)

    raw_role = str(getattr(part_adjustment, "material_role", "") or "").strip().lower()
    role_enabled = bool(emissive_role) if emissive_role is not None else raw_role in {"glow", "emissive", "emission"}
    role_name = "emissive" if role_enabled else ""
    intensity = None
    if role_enabled:
        intensity = (
            _float(emissive_intensity, 0.0, 0.0, 20.0)
            if emissive_intensity is not None
            else effective_emissive_intensity(
                profile,
                source=source_slot,
                part_adjustment=part_adjustment,
            )
        )
    raw_emissive_color = emissive_color or getattr(part_adjustment, "emissive_color_rgb", ()) or getattr(profile, "accent_glow_color_rgb", ())
    color_uses_bytes = bool(raw_emissive_color) and all(isinstance(value, int) for value in tuple(raw_emissive_color)[:3])

    return MaterialParameterEvaluation(
        base_brightness=_float(base_brightness, 1.0, 0.1, 3.0),
        base_color_scale=scale,
        base_color_lift=_integer(getattr(source, "base_color_lift", 0), 0, 0, 254),
        gamma=gamma,
        saturation=saturation,
        value_max=_integer(getattr(source, "base_color_value_max", 255), 255, 0, 255),
        auto_balance=_integer(getattr(source, "base_color_auto_balance", 0), 0, 0, 100),
        shadow_lift=_integer(getattr(source, "base_color_shadow_lift", 0), 0, 0, 100),
        tone_contrast=tone_contrast,
        tint_color=tint_color,
        brightness_percent=brightness_percent,
        contrast_percent=contrast_percent,
        saturation_percent=saturation_percent,
        gamma_multiplier=gamma_multiplier,
        tint_adjustment=tint_adjustment,
        roughness=roughness,
        metalness=metalness,
        specular=specular,
        roughness_inverted=profile_roughness_inverted(profile),
        metalness_inverted=profile_metallic_inverted(profile),
        force_nonmetal=bool(getattr(profile, "force_nonmetal", False)),
        roughness_min=_optional_integer(getattr(profile, "roughness_min", None), 0, 255),
        roughness_scale=_optional_float(getattr(profile, "roughness_scale", None), 0.0, 4.0),
        roughness_max=_optional_integer(getattr(profile, "roughness_max", None), 0, 255),
        metallic_min=_optional_integer(getattr(profile, "metallic_min", None), 0, 255),
        metallic_scale=_optional_float(getattr(profile, "metallic_scale", None), 0.0, 4.0),
        metallic_max=_optional_integer(getattr(profile, "metallic_max", None), 0, 255),
        global_gloss_reduction=normalize_global_gloss_reduction(getattr(profile, "global_gloss_reduction", 0.0)),
        gloss_reduction_mode=normalize_gloss_reduction_mode(getattr(profile, "gloss_reduction_mode", "cd_smoothness_low")),
        height_scale=height_scale,
        relief_source=normalize_edge_relief_source(getattr(profile, "edge_relief_source", "hybrid")),
        emissive_intensity=intensity,
        emissive_color=_normalized_color(raw_emissive_color, byte_values=color_uses_bytes) if role_enabled else (),
        emissive_role=role_name,
    )


def material_parameter_renderer_overrides(evaluation: MaterialParameterEvaluation) -> dict[str, object]:
    tint = evaluation.tint_color if len(evaluation.tint_color) >= 3 else (1.0, 1.0, 1.0)
    roughness = evaluation.roughness
    metalness = evaluation.metalness
    specular = evaluation.specular
    if evaluation.force_nonmetal:
        if roughness is not None:
            roughness = max(0.65, roughness)
        metalness = 0.0
        specular = min(0.04, specular if specular is not None else 0.08)
    tone = evaluation.tone_contrast
    contrast = max(0.35, 1.0 + 0.55 * (tone / 100.0)) if tone < 0.0 else 1.0 + 0.75 * (tone / 100.0)
    post_contrast_brightness = 1.0 + 0.10 * (-tone / 100.0) if tone < 0.0 else 1.0
    payload: dict[str, object] = {
        "texture_brightness": max(0.1, min(3.0, evaluation.base_brightness * evaluation.base_color_scale)),
        "contrast": contrast,
        "post_contrast_brightness": post_contrast_brightness,
        "saturation": evaluation.saturation,
        "gamma": evaluation.gamma,
        "tint_color": [float(value) for value in tint[:3]],
        "base_color_lift": evaluation.base_color_lift,
        "value_max": evaluation.value_max,
        "auto_balance": evaluation.auto_balance,
        "shadow_lift": evaluation.shadow_lift,
        "roughness_inverted": evaluation.roughness_inverted,
        "metalness_inverted": evaluation.metalness_inverted,
    }
    for key, value in (("roughness", roughness), ("metalness", metalness), ("specular", specular), ("height_scale", evaluation.height_scale), ("emissive_intensity", evaluation.emissive_intensity)):
        if value is not None:
            payload[key] = float(value)
    if len(evaluation.emissive_color) >= 3:
        payload["emissive_color"] = [float(value) for value in evaluation.emissive_color[:3]]
    if evaluation.emissive_role:
        payload["material_role"] = evaluation.emissive_role
    for key, value in (
        ("roughness_scale", evaluation.roughness_scale),
        ("roughness_min", evaluation.roughness_min),
        ("roughness_max", evaluation.roughness_max),
        ("metalness_scale", evaluation.metallic_scale),
        ("metalness_min", evaluation.metallic_min),
        ("metalness_max", evaluation.metallic_max),
    ):
        if value is not None:
            payload[key] = value
    gloss_strength = abs(evaluation.global_gloss_reduction) / 100.0
    if gloss_strength > 0.0:
        if evaluation.global_gloss_reduction < 0.0:
            roughness_target = 24 / 255.0 if evaluation.gloss_reduction_mode == "source_roughness_high" else 1.0
        else:
            roughness_target = 1.0 if evaluation.gloss_reduction_mode == "source_roughness_high" else 32 / 255.0
        payload["roughness_blend_target"] = roughness_target
        payload["roughness_blend_strength"] = gloss_strength
        if evaluation.global_gloss_reduction > 0.0 and evaluation.gloss_reduction_mode == "cd_smoothness_low":
            payload["metalness_blend_target"] = 0.0
            payload["metalness_blend_strength"] = gloss_strength
    return payload


__all__ = [
    "MaterialParameterEvaluation",
    "effective_emissive_intensity",
    "evaluate_material_parameters",
    "material_parameter_renderer_overrides",
    "normalize_basic_control_percent",
    "normalize_edge_relief_source",
    "normalize_global_gloss_reduction",
    "normalize_signed_basic_control_percent",
    "normalize_tone_contrast",
    "profile_accent_glow_intensity",
    "profile_accent_glow_strength",
    "profile_metallic_inverted",
    "profile_roughness_inverted",
    "profile_source_emissive_enabled",
    "profile_source_emissive_parameter_intensity",
    "source_emissive_strength",
]
