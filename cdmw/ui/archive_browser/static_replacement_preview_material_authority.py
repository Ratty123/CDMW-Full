"""Material-authority preview helpers for static replacement textures."""

from __future__ import annotations

from collections.abc import Mapping

from cdmw.domain.textures.material_parameters import (
    evaluate_material_parameters,
    material_parameter_renderer_overrides,
    profile_source_emissive_enabled,
    source_emissive_strength,
)
from cdmw.models import PreviewMaterialParameterInput


_MATERIAL_AUTHORITY_PREVIEW_HINT_MARKER = "_material_authority_preview_native_hint_keys"
_MATERIAL_AUTHORITY_PREVIEW_PREVIOUS_HINTS = "_material_authority_preview_previous_native_hints"


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
    source: object | None = None,
    part_adjustment: object | None = None,
) -> dict[str, object]:
    if not enabled or profile is None:
        return {}
    manual_role = str(getattr(part_adjustment, "material_role", "") or "").strip().lower() in {"glow", "emissive"}
    source_role = source is None or source_emissive_strength(source) is not None
    evaluated = evaluate_material_parameters(
        profile,
        source_slot=source,
        part_adjustment=part_adjustment,
        base_brightness=base_brightness,
        emissive_role=manual_role or (profile_source_emissive_enabled(profile) and source_role),
    )
    renderer_parameters = material_parameter_renderer_overrides(evaluated)
    native_hints = {
        key: renderer_parameters[key]
        for key in ("roughness", "metalness", "specular", "height_scale")
        if key in renderer_parameters
    }
    return {
        "texture_brightness": renderer_parameters["texture_brightness"],
        "native_material_hints": native_hints,
        "renderer_parameters": renderer_parameters,
    }


def apply_material_authority_preview_native_hints(
    mesh: object,
    profile: object | None,
    *,
    enabled: bool,
    source: object | None = None,
    part_adjustment: object | None = None,
) -> None:
    clear_material_authority_preview_native_hints(mesh)
    override_values = material_authority_preview_native_override_values(
        profile,
        enabled=enabled,
        base_brightness=getattr(mesh, "preview_texture_brightness", 1.0),
        source=source,
        part_adjustment=part_adjustment,
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
