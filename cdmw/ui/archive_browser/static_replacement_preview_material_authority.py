"""Material-authority preview helpers for static replacement textures."""

from __future__ import annotations

from collections.abc import Mapping

from cdmw.models import PreviewMaterialParameterInput


_MATERIAL_AUTHORITY_PREVIEW_HINT_MARKER = "_material_authority_preview_native_hint_keys"
_MATERIAL_AUTHORITY_PREVIEW_PREVIOUS_HINTS = "_material_authority_preview_previous_native_hints"


def _safe_float(value: object, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return float(fallback)


def _clamp_float(value: object, minimum: float, maximum: float, fallback: float) -> float:
    return max(float(minimum), min(float(maximum), _safe_float(value, fallback)))


def material_authority_preview_parameters(
    profile: object,
    *,
    enabled: bool,
) -> tuple[PreviewMaterialParameterInput, ...]:
    if not enabled:
        return ()
    parameters: list[PreviewMaterialParameterInput] = []
    for attr_name, parameter_name in (
        ("scratch_roughness", "_scratchRoughness"),
        ("scratch_metallic", "_scratchMetallic"),
        ("shine_scalar", "_specularAmount"),
        ("displacement_scale_multiplier", "_heightIntensity"),
    ):
        value = getattr(profile, attr_name, None)
        if value is None:
            continue
        try:
            numeric_value = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError, OverflowError):
            continue
        parameters.append(
            PreviewMaterialParameterInput(
                parameter_kind="float",
                parameter_name=parameter_name,
                value=f"{numeric_value:.6f}",
                numeric_value=numeric_value,
            )
        )
    return tuple(parameters)


def clear_material_authority_preview_native_hints(mesh: object) -> None:
    overrides = getattr(mesh, "preview_native_material_overrides", None)
    if not isinstance(overrides, Mapping):
        return
    owned_hint_keys = tuple(str(key) for key in tuple(overrides.get(_MATERIAL_AUTHORITY_PREVIEW_HINT_MARKER, ()) or ()))
    if not owned_hint_keys:
        return
    previous_hints = overrides.get(_MATERIAL_AUTHORITY_PREVIEW_PREVIOUS_HINTS)
    previous_hints = dict(previous_hints) if isinstance(previous_hints, Mapping) else {}
    next_overrides = dict(overrides)
    next_overrides.pop(_MATERIAL_AUTHORITY_PREVIEW_HINT_MARKER, None)
    next_overrides.pop(_MATERIAL_AUTHORITY_PREVIEW_PREVIOUS_HINTS, None)
    current_hints = next_overrides.get("native_material_hints")
    if isinstance(current_hints, Mapping):
        next_hints = dict(current_hints)
        for key in owned_hint_keys:
            if key in previous_hints:
                next_hints[key] = previous_hints[key]
            else:
                next_hints.pop(key, None)
        if next_hints:
            next_overrides["native_material_hints"] = next_hints
        else:
            next_overrides.pop("native_material_hints", None)
    mesh.preview_native_material_overrides = next_overrides


def material_authority_preview_native_override_values(
    profile: object | None,
    *,
    enabled: bool,
    base_brightness: object = 1.0,
) -> dict[str, object]:
    if not enabled or profile is None:
        return {}

    brightness = _clamp_float(base_brightness, 0.1, 3.0, 1.0)
    base_scale = _clamp_float(getattr(profile, "base_color_scale", 1.0), 0.1, 4.0, 1.0)
    shadow_lift = _clamp_float(getattr(profile, "base_color_shadow_lift", 0.0), 0.0, 100.0, 0.0)
    auto_balance = _clamp_float(getattr(profile, "base_color_auto_balance", 0.0), 0.0, 100.0, 0.0)
    gamma = _clamp_float(getattr(profile, "base_color_gamma", 1.0), 0.25, 4.0, 1.0)
    tone = _clamp_float(getattr(profile, "base_color_tone_contrast", 0.0), -100.0, 100.0, 0.0)
    brightness *= base_scale
    brightness *= 1.0 + shadow_lift * 0.006
    brightness *= 1.0 + auto_balance * 0.002
    if gamma < 1.0:
        brightness *= 1.0 + (1.0 - gamma) * 0.75
    if tone < 0.0:
        brightness *= 1.0 + abs(tone) * 0.0015
    elif tone > 0.0:
        brightness *= max(0.55, 1.0 - tone * 0.001)

    native_hints: dict[str, float] = {}
    scratch_roughness = getattr(profile, "scratch_roughness", None)
    if scratch_roughness is not None:
        native_hints["roughness"] = _clamp_float(scratch_roughness, 0.0, 1.0, 0.55)
    scratch_metallic = getattr(profile, "scratch_metallic", None)
    if scratch_metallic is not None:
        native_hints["metalness"] = _clamp_float(scratch_metallic, 0.0, 1.0, 0.0)
    shine_scalar = getattr(profile, "shine_scalar", None)
    if shine_scalar is not None:
        native_hints["specular"] = _clamp_float(shine_scalar, 0.0, 1.0, 0.08)
    height_scale = max(
        _clamp_float(getattr(profile, "displacement_scale_multiplier", 0.0), 0.0, 1.0, 0.0),
        _clamp_float(getattr(profile, "edge_relief_strength", 0.0), 0.0, 100.0, 0.0) / 100.0,
    )
    if height_scale > 0.0:
        native_hints["height_scale"] = height_scale
    if bool(getattr(profile, "force_nonmetal", False)):
        native_hints["metalness"] = 0.0
        native_hints["specular"] = min(native_hints.get("specular", 0.08), 0.04)
        native_hints["roughness"] = max(native_hints.get("roughness", 0.55), 0.65)
    return {
        "texture_brightness": max(0.1, min(3.0, brightness)),
        "native_material_hints": native_hints,
    }


def apply_material_authority_preview_native_hints(
    mesh: object,
    profile: object | None,
    *,
    enabled: bool,
) -> None:
    clear_material_authority_preview_native_hints(mesh)
    override_values = material_authority_preview_native_override_values(
        profile,
        enabled=enabled,
        base_brightness=getattr(mesh, "preview_texture_brightness", 1.0),
    )
    if not override_values:
        return

    mesh.preview_texture_brightness = float(override_values["texture_brightness"])
    native_hints = dict(override_values.get("native_material_hints", {}) or {})
    if not native_hints:
        return

    overrides = dict(getattr(mesh, "preview_native_material_overrides", {}) or {})
    current_hints = overrides.get("native_material_hints")
    current_hints = dict(current_hints) if isinstance(current_hints, Mapping) else {}
    previous_hints = {key: current_hints[key] for key in native_hints if key in current_hints}
    current_hints.update(native_hints)
    overrides["native_material_hints"] = current_hints
    overrides[_MATERIAL_AUTHORITY_PREVIEW_HINT_MARKER] = tuple(native_hints)
    overrides[_MATERIAL_AUTHORITY_PREVIEW_PREVIOUS_HINTS] = previous_hints
    mesh.preview_native_material_overrides = overrides


__all__ = [
    "apply_material_authority_preview_native_hints",
    "clear_material_authority_preview_native_hints",
    "material_authority_preview_native_override_values",
    "material_authority_preview_parameters",
]
