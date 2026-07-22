"""Manual Material Authority profile helpers for static replacement."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from cdmw.domain.textures.material_authority_state import (
    MaterialAuthorityCapability,
    material_authority_control_spec,
)


MODIFY_ORIGINAL_ADVANCED_TEXTURE_TUNING_SETTINGS_KEY = "settings/modify_original_advanced_texture_tuning"
MODIFY_ORIGINAL_MANUAL_TEXTURE_TUNING_SETTINGS_KEY = "settings/modify_original_manual_texture_tuning"
MODIFY_ORIGINAL_MANUAL_TEXTURE_TUNING_PRESETS_KEY = "settings/modify_original_manual_texture_tuning_presets"

MODIFY_ORIGINAL_MANUAL_TEXTURE_TUNING_KEYS = (
    "base_color_lift",
    "base_color_scale",
    "base_color_gamma",
    "base_color_saturation",
    "base_color_value_max",
    "emissive_color_scale",
    "emissive_color_saturation",
    "emissive_color_value_max",
    "roughness_default",
    "roughness_min",
    "roughness_scale",
    "roughness_max",
    "metallic_default",
    "metallic_min",
    "metallic_scale",
    "metallic_max",
    "ao_default",
    "alpha_default",
    "scratch_roughness",
    "scratch_metallic",
    "shine_scalar",
    "displacement_scale_multiplier",
    "displacement_scale_max",
    "neutral_color_rgb",
    "roughness_inverted",
    "metallic_inverted",
    "force_nonmetal",
    "preserve_scratch_alpha",
    "allow_factor_only_authority",
    "factor_only_material_mask",
    "force_neutral_layer_support",
    "preserve_target_layer_response",
)

MATERIAL_AUTHORITY_RESIDENT_MANUAL_PARAMETER_KEYS = frozenset(
    {
        "scratch_roughness",
        "scratch_metallic",
        "shine_scalar",
    }
)

MATERIAL_AUTHORITY_RESIDENT_RESOURCE_KEYS = frozenset(
    {
        "base_binding_mode",
        "base_color_lift",
        "base_color_scale",
        "base_color_gamma",
        "base_color_saturation",
        "base_color_value_max",
        "mask_binding_mode",
        "support_policy",
        "emissive_mode",
        "emissive_color_scale",
        "emissive_color_saturation",
        "emissive_color_value_max",
        "roughness_default",
        "roughness_min",
        "roughness_scale",
        "roughness_max",
        "metallic_default",
        "metallic_min",
        "metallic_scale",
        "metallic_max",
        "ao_default",
        "displacement_scale_multiplier",
        "displacement_scale_max",
        "roughness_inverted",
        "metallic_inverted",
        "force_nonmetal",
        "allow_factor_only_authority",
        "factor_only_material_mask",
        "force_neutral_layer_support",
    }
)

MATERIAL_AUTHORITY_RESIDENT_EXPORT_ONLY_KEYS = frozenset(
    {
        "authority_contract",
        "alpha_default",
        "scratch_roughness",
        "scratch_metallic",
        "shine_scalar",
        "neutral_color_rgb",
        "preserve_scratch_alpha",
        "preserve_target_layer_response",
        "source_color_layer_authority",
    }
)

_MATERIAL_RESOURCE_CHANNELS = {
    "global_gloss_reduction": ("material_mask",),
    "auto_brightness": ("base",),
    "source_brightness": ("base",),
    "tone_contrast": ("base",),
    "base_binding_mode": ("base",),
    "base_color_lift": ("base",),
    "base_color_scale": ("base",),
    "base_color_gamma": ("base",),
    "base_color_saturation": ("base",),
    "base_color_value_max": ("base",),
    "allow_factor_only_authority": ("base",),
    "mask_binding_mode": ("material_mask",),
    "roughness_default": ("material_mask",),
    "roughness_min": ("material_mask",),
    "roughness_scale": ("material_mask",),
    "roughness_max": ("material_mask",),
    "metallic_default": ("material_mask",),
    "metallic_min": ("material_mask",),
    "metallic_scale": ("material_mask",),
    "metallic_max": ("material_mask",),
    "ao_default": ("material_mask",),
    "roughness_inverted": ("material_mask",),
    "metallic_inverted": ("material_mask",),
    "force_nonmetal": ("material_mask",),
    "factor_only_material_mask": ("material_mask",),
    "support_policy": ("normal", "height", "material_mask"),
    "force_neutral_layer_support": ("normal", "height", "material_mask"),
    "edge_relief": ("normal", "height", "material_mask"),
    "edge_relief_source": ("normal", "height", "material_mask"),
    "displacement_scale_multiplier": ("height",),
    "displacement_scale_max": ("height",),
    "emissive_mode": ("emissive",),
    "emissive_color_scale": ("emissive",),
    "emissive_color_saturation": ("emissive",),
    "emissive_color_value_max": ("emissive",),
    "accent_glow": ("emissive",),
    "part_glow_color": ("emissive",),
    "part_glow_strength": ("emissive",),
}


def material_authority_resource_channels(control_keys: Sequence[object]) -> tuple[str, ...]:
    keys = tuple(str(key or "").strip() for key in control_keys)
    if "*" in keys:
        return ("base", "normal", "height", "material_mask", "emissive")
    return tuple(
        dict.fromkeys(
            channel
            for key in keys
            for channel in _MATERIAL_RESOURCE_CHANNELS.get(key, ())
        )
    )


def manual_material_profile_default_values(profile: object | None) -> dict[str, object]:
    return {
        "base_binding_mode": str(getattr(profile, "base_binding_mode", "overlay_texture") or "overlay_texture"),
        "mask_binding_mode": str(getattr(profile, "mask_binding_mode", "detail_mask_material") or "detail_mask_material"),
        "support_policy": str(getattr(profile, "support_policy", "source_only") or "source_only"),
        "emissive_mode": str(getattr(profile, "emissive_mode", "intensity") or "intensity"),
        "authority_contract": str(getattr(profile, "authority_contract", "true_source_authority_detail_mask") or "true_source_authority_detail_mask"),
        "base_color_lift": int(getattr(profile, "base_color_lift", 68) or 0),
        "base_color_scale": float(getattr(profile, "base_color_scale", 0.90) or 0.0),
        "base_color_gamma": float(getattr(profile, "base_color_gamma", 0.62) or 0.0),
        "base_color_saturation": float(getattr(profile, "base_color_saturation", 0.66) or 0.0),
        "base_color_value_max": int(getattr(profile, "base_color_value_max", 218) or 255),
        "emissive_color_scale": float(getattr(profile, "emissive_color_scale", None) if getattr(profile, "emissive_color_scale", None) is not None else 1.0),
        "emissive_color_saturation": float(getattr(profile, "emissive_color_saturation", None) if getattr(profile, "emissive_color_saturation", None) is not None else 1.0),
        "emissive_color_value_max": int(getattr(profile, "emissive_color_value_max", 72) or 255),
        "roughness_default": int(getattr(profile, "roughness_default", 240) or 0),
        "roughness_min": int(getattr(profile, "roughness_min", 246) or 0),
        "roughness_scale": float(getattr(profile, "roughness_scale", 1.0) or 1.0),
        "roughness_max": 255,
        "metallic_default": int(getattr(profile, "metallic_default", 0) or 0),
        "metallic_min": 0,
        "metallic_scale": float(getattr(profile, "metallic_scale", 0.34) or 1.0),
        "metallic_max": int(getattr(profile, "metallic_max", 112) or 255),
        "ao_default": int(getattr(profile, "ao_default", 255) or 255),
        "alpha_default": int(getattr(profile, "alpha_default", 0) or 0),
        "scratch_roughness": float(getattr(profile, "scratch_roughness", 1.0) or 0.0),
        "scratch_metallic": float(getattr(profile, "scratch_metallic", 0.0) or 0.0),
        "shine_scalar": float(getattr(profile, "shine_scalar", 0.0) or 0.0),
        "displacement_scale_multiplier": float(getattr(profile, "displacement_scale_multiplier", 0.0) or 0.0),
        "displacement_scale_max": float(getattr(profile, "displacement_scale_max", 0.0) or 0.0),
        "neutral_color_rgb": tuple(getattr(profile, "neutral_color_rgb", (216, 216, 216)) or (216, 216, 216)),
        "roughness_inverted": bool(getattr(profile, "roughness_inverted", False)),
        "metallic_inverted": bool(getattr(profile, "metallic_inverted", False)),
        "force_nonmetal": bool(getattr(profile, "force_nonmetal", False)),
        "preserve_scratch_alpha": bool(getattr(profile, "preserve_scratch_alpha", True)),
        "allow_factor_only_authority": bool(getattr(profile, "allow_factor_only_authority", True)),
        "factor_only_material_mask": bool(getattr(profile, "factor_only_material_mask", True)),
        "force_neutral_layer_support": bool(getattr(profile, "force_neutral_layer_support", False)),
        "preserve_target_layer_response": bool(getattr(profile, "preserve_target_layer_response", False)),
        "source_color_layer_authority": bool(getattr(profile, "source_color_layer_authority", False)),
        "global_gloss_reduction": float(getattr(profile, "global_gloss_reduction", 0.0) or 0.0),
    }


def modify_original_advanced_texture_tuning_settings_key() -> str:
    return MODIFY_ORIGINAL_ADVANCED_TEXTURE_TUNING_SETTINGS_KEY


def modify_original_manual_texture_tuning_presets_key() -> str:
    return MODIFY_ORIGINAL_MANUAL_TEXTURE_TUNING_PRESETS_KEY


def modify_original_manual_texture_tuning_settings_key() -> str:
    return MODIFY_ORIGINAL_MANUAL_TEXTURE_TUNING_SETTINGS_KEY


def modify_original_manual_texture_tuning_values(
    raw_values: object,
    *,
    defaults: Mapping[str, object],
) -> dict[str, object]:
    values = dict(defaults)
    if isinstance(raw_values, Mapping):
        for key in MODIFY_ORIGINAL_MANUAL_TEXTURE_TUNING_KEYS:
            if key in values and key in raw_values:
                values[key] = raw_values[key]
    return values


def stored_manual_material_profile_values(
    stored_profile_name: str,
    stored_profile: object,
    defaults: Mapping[str, object],
) -> dict[str, object]:
    if str(stored_profile_name or "") != "material_authority_manual":
        return {}
    return {
        str(key): getattr(stored_profile, str(key), default_value)
        for key, default_value in defaults.items()
        if hasattr(stored_profile, str(key))
    }


def coerce_manual_material_profile_values(
    raw_values: object,
    defaults: Mapping[str, object],
) -> dict[str, object]:
    values = dict(defaults)
    if isinstance(raw_values, Mapping):
        values.update({str(key): value for key, value in raw_values.items() if str(key) in values})
    return values


def load_manual_material_profile_values(
    *,
    defaults: Mapping[str, object],
    stored_values: Mapping[str, object],
    raw_settings: object,
) -> dict[str, object]:
    values = dict(defaults)
    values.update({str(key): value for key, value in stored_values.items() if str(key) in values})
    if isinstance(raw_settings, str) and raw_settings.strip():
        try:
            parsed = json.loads(raw_settings)
        except Exception:
            parsed = {}
        if isinstance(parsed, Mapping):
            values.update({str(key): value for key, value in parsed.items() if str(key) in values})
    return values


def load_manual_material_profile_presets(
    raw_settings: object,
    *,
    defaults: Mapping[str, object],
) -> list[dict[str, object]]:
    try:
        parsed = json.loads(raw_settings) if isinstance(raw_settings, str) and raw_settings.strip() else []
    except Exception:
        parsed = []
    presets: list[dict[str, object]] = []
    if not isinstance(parsed, Sequence) or isinstance(parsed, (str, bytes)):
        return presets
    for item in parsed:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        presets.append(
            {
                "name": name,
                "details": str(item.get("details") or "").strip(),
                "recommended_models": str(item.get("recommended_models") or "").strip(),
                "values": coerce_manual_material_profile_values(item.get("values"), defaults),
            }
        )
    return presets


def manual_material_profile_presets_payload(
    presets: Sequence[Mapping[str, object]],
    *,
    defaults: Mapping[str, object],
) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for item in presets:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        payload.append(
            {
                "schema": "cdmw_manual_material_profile_v1",
                "name": name,
                "details": str(item.get("details") or "").strip(),
                "recommended_models": str(item.get("recommended_models") or "").strip(),
                "values": coerce_manual_material_profile_values(item.get("values"), defaults),
            }
        )
    return payload


def manual_material_profile_inactive_reasons(values: Mapping[str, object]) -> dict[str, str]:
    base_mode = str(values.get("base_binding_mode") or "").strip()
    mask_mode = str(values.get("mask_binding_mode") or "").strip()
    support_mode = str(values.get("support_policy") or "").strip()
    emissive_mode = str(values.get("emissive_mode") or "").strip()
    authority_contract = str(values.get("authority_contract") or "").strip()
    allow_factor_colors = bool(values.get("allow_factor_only_authority"))
    inactive: dict[str, str] = {}
    if base_mode in {"disabled", "tint_only"}:
        for key in ("base_color_lift", "base_color_gamma", "base_color_saturation", "base_color_value_max", "base_color_scale"):
            inactive[key] = "No effect: Color slot is disabled."
    if emissive_mode == "disabled":
        for key in ("emissive_color_scale", "emissive_color_saturation", "emissive_color_value_max"):
            inactive[key] = "No effect: Emissive routing is disabled."
    if mask_mode in {"disabled", "scratch_scalars"}:
        for key in (
            "roughness_default",
            "roughness_min",
            "roughness_scale",
            "roughness_max",
            "metallic_default",
            "metallic_min",
            "metallic_scale",
            "metallic_max",
            "ao_default",
            "alpha_default",
            "force_nonmetal",
            "roughness_inverted",
            "metallic_inverted",
            "factor_only_material_mask",
        ):
            inactive[key] = "No effect: PBR/mask slot is not generating a material-mask DDS."
    if not allow_factor_colors:
        inactive["factor_only_material_mask"] = "No effect: Use factor-only colors is off."
    if bool(values.get("force_nonmetal")):
        reason = "No effect: Force nonmetal fixes effective metallic to exactly zero."
        for key in (
            "metallic_default",
            "metallic_min",
            "metallic_scale",
            "metallic_max",
            "scratch_metallic",
            "metallic_inverted",
        ):
            inactive[key] = reason
    if support_mode != "source_only":
        inactive["force_neutral_layer_support"] = "No effect: neutral support fill only applies to Source only support maps."
    if support_mode == "keep_original_support":
        for key in ("displacement_scale_multiplier", "displacement_scale_max"):
            inactive[key] = "No effect: Support maps are preserving original target height/detail."
    if authority_contract == "runtime_xml_preserve" and support_mode == "keep_original_support":
        inactive["force_neutral_layer_support"] = "No effect: Runtime XML preserve keeps target/corpus support unless support maps are changed."
    return inactive


def material_authority_target_height_supported(bindings: object) -> bool | None:
    """Return true only for a declared height input with a readable resource."""
    if not isinstance(bindings, Sequence) or isinstance(bindings, (str, bytes)):
        return None
    rows = tuple(bindings)
    if not rows:
        return None
    for binding in rows:
        value = lambda name: (
            binding.get(name, "") if isinstance(binding, Mapping) else getattr(binding, name, "")
        )
        evidence = " ".join(
            str(value(name) or "").strip().lower()
            for name in ("parameter_name", "texture_role", "texture_path", "layer_role", "layer_channel")
        )
        if not any(token in evidence for token in ("height", "displacement", "parallax", "bump")):
            continue
        for name in ("resolved_path", "source_path", "local_path", "extracted_path", "texture_path"):
            raw_path = str(value(name) or "").strip()
            if raw_path:
                try:
                    if Path(raw_path).expanduser().is_file():
                        return True
                except OSError:
                    pass
    return False


def selected_manual_material_profile_preset(
    presets: Sequence[Mapping[str, object]],
    name: object,
) -> dict[str, object] | None:
    selected_name = str(name or "").strip()
    if not selected_name:
        return None
    lowered = selected_name.casefold()
    for preset in presets:
        if str(preset.get("name") or "").strip().casefold() == lowered:
            return dict(preset)
    return None


def manual_material_profile_preset_names(
    presets: Sequence[Mapping[str, object]],
) -> list[str]:
    return [
        name
        for name in (str(preset.get("name") or "").strip() for preset in presets if isinstance(preset, Mapping))
        if name
    ]


def manual_material_profile_preset_metadata(
    preset: Mapping[str, object],
) -> dict[str, str]:
    return {
        "name": str(preset.get("name") or ""),
        "details": str(preset.get("details") or ""),
        "recommended_models": str(preset.get("recommended_models") or ""),
    }


def manual_material_profile_preset_from_fields(
    *,
    name: object,
    details: object,
    recommended_models: object,
    values: Mapping[str, object],
) -> dict[str, object]:
    return {
        "name": str(name or "").strip(),
        "details": str(details or "").strip(),
        "recommended_models": str(recommended_models or "").strip(),
        "values": dict(values),
    }


def manual_material_profile_tooltips() -> dict[str, str]:
    return {
        "preset_combo": "Saved manual material profiles. Pick one to inspect, then Load to apply its values.",
        "preset_name": "Name for this saved manual material profile.",
        "preset_details": "Notes about the look this preset is trying to achieve.",
        "preset_recommended": "Optional model paths, source asset names, material names, or tags this preset works well with.",
        "preset_save": "Save the current manual slider values plus name/details/recommended models.",
        "preset_load": "Apply the selected saved profile values to the manual controls.",
        "preset_delete": "Delete the selected saved manual profile.",
        "apply": (
            "Force the current manual values into the preview/build impact now. "
            "Slider edits also queue a debounced preview refresh."
        ),
        "reset": "Reset every manual knob to the current Material Authority baseline.",
    }


def manual_material_profile_control_text() -> dict[str, str]:
    return {
        "group_title": "Material Authority Manual",
        "group_object": "MeshAlignmentManualMaterialProfileGroup",
        "preset_group": "Saved Manual Profiles",
        "preset_name_placeholder": "Profile name, e.g. Clean Dark Metal",
        "preset_details_placeholder": "What this profile changes and why",
        "preset_recommended_placeholder": "Recommended models/materials, paths, or tags",
        "preset_save_button": "Save Current",
        "preset_load_button": "Load",
        "preset_delete_button": "Delete",
        "saved_label": "Saved",
        "name_label": "Name",
        "details_label": "Details",
        "recommended_label": "Recommended",
        "apply_button": "Apply Manual Settings",
        "reset_button": "Reset To Material Authority",
        "no_saved_profile": "No saved profile",
        "save_title": "Save Manual Profile",
        "save_missing_name": "Enter a profile name before saving.",
        "load_title": "Load Manual Profile",
        "load_missing_selection": "Select a saved manual profile first.",
        "delete_title": "Delete Manual Profile",
        "delete_missing_selection": "Select a saved manual profile first.",
    }


def manual_material_profile_saved_message(name: object) -> str:
    return f'Saved manual material profile "{name}".'


def manual_material_profile_delete_question(name: object) -> str:
    return f'Delete saved manual material profile "{name}"?'


def manual_material_profile_texture_impact_html() -> str:
    return (
        "<div style='line-height:1.35;'>"
        "<div style='font-weight:700; color:#f0f6fc; margin-bottom:4px;'>Texture impact</div>"
        "<div style='color:#d29922; margin-bottom:6px;'>"
        "<b>Conditional:</b> controls need matching source maps/factors and target sidecar slots. If missing, the change may only affect generated metadata, or may have no visible in-game effect."
        "</div>"
        "<table cellspacing='0' cellpadding='3' style='border-collapse:collapse;'>"
        "<tr><td><span style='color:#7ee787; font-weight:700;'>Color</span></td>"
        "<td>base DDS <span style='color:#8b949e;'>*_base*.dds / _overlayColorTexture</span></td>"
        "<td style='color:#8b949e;'>Affects source albedo/color.</td></tr>"
        "<tr><td><span style='color:#ff7b72; font-weight:700;'>Emissive</span></td>"
        "<td>emissive DDS <span style='color:#8b949e;'>*_emi.dds</span></td>"
        "<td style='color:#8b949e;'>Only when source has emissive.</td></tr>"
        "<tr><td><span style='color:#79c0ff; font-weight:700;'>PBR mask</span></td>"
        "<td>material mask DDS <span style='color:#8b949e;'>*_ma.dds / _detailMaskTexture</span></td>"
        "<td style='color:#8b949e;'>Roughness, metal, AO, mask alpha. Shared masks affect every part using that DDS.</td></tr>"
        "<tr><td><span style='color:#ffa657; font-weight:700;'>Shader</span></td>"
        "<td>sidecar XML <span style='color:#8b949e;'>no separate DDS</span></td>"
        "<td style='color:#8b949e;'>Shader roughness/metal/shine, neutral tint, invert, force nonmetal.</td></tr>"
        "<tr><td><span style='color:#c297ff; font-weight:700;'>Height</span></td>"
        "<td>support DDS <span style='color:#8b949e;'>*_disp.dds / *_mg.dds</span></td>"
        "<td style='color:#8b949e;'>Only when support maps write or preserve height/detail.</td></tr>"
        "</table>"
        "<div style='color:#8b949e; margin-top:5px;'>Exact output filenames appear in the build notes.</div>"
        "</div>"
    )


def manual_material_profile_change_status_text(dirty: bool) -> str:
    if dirty:
        return "Manual settings changed. Preview refresh queued; press Apply Manual Settings to force it now."
    return "Manual settings applied. Further slider changes queue live preview refresh."


def manual_material_profile_dirty_state(dirty: object) -> dict[str, object]:
    dirty_value = bool(dirty)
    return {
        "dirty": dirty_value,
        "apply_enabled": dirty_value,
        "status_text": manual_material_profile_change_status_text(dirty_value),
    }


def manual_material_profile_control_effect_states(
    values: Mapping[str, object],
    *,
    control_keys: Sequence[object],
    control_tooltips: Mapping[str, object],
    target_height_supported: bool | None = None,
    resident_parameter_only: bool = False,
    resident_parameters_available: bool = True,
    resident_resources_available: bool = False,
    include_expert: bool = False,
) -> dict[str, dict[str, object]]:
    inactive = manual_material_profile_inactive_reasons(values)
    if target_height_supported is False:
        reason = "No effect: The target material has no height/displacement input."
        inactive["displacement_scale_multiplier"] = reason
        inactive["displacement_scale_max"] = reason
    if resident_parameter_only:
        resource_reason = "Unavailable until the resident .NET material-resource channel is Ready."
        parameter_reason = "Unavailable until the resident .NET material-parameter channel is Ready."
        export_reason = "Unavailable during resident editing: this control changes export/sidecar structure only."
        mask_mode = str(values.get("mask_binding_mode") or "").strip().lower()
        scalar_surface_mode = mask_mode in {"scratch_scalars", "disabled"}
        parameter_no_effect = (
            {
                "roughness_min", "roughness_scale", "roughness_max",
                "metallic_min", "metallic_scale", "metallic_max",
                "roughness_inverted", "metallic_inverted",
            }
            if scalar_surface_mode
            else {"scratch_roughness", "scratch_metallic"}
        )
        for raw_key in control_keys:
            key = str(raw_key)
            if key in MATERIAL_AUTHORITY_RESIDENT_EXPORT_ONLY_KEYS:
                inactive.setdefault(key, export_reason)
            elif key in MATERIAL_AUTHORITY_RESIDENT_RESOURCE_KEYS:
                if not resident_resources_available:
                    inactive.setdefault(key, resource_reason)
            elif key in MATERIAL_AUTHORITY_RESIDENT_MANUAL_PARAMETER_KEYS:
                if not resident_parameters_available:
                    inactive.setdefault(key, parameter_reason)
                elif key in parameter_no_effect:
                    inactive.setdefault(key, "No live effect in the selected PBR/mask mode.")
            else:
                inactive.setdefault(key, "Unavailable during resident editing: no target-supported live effect is implemented.")
    states: dict[str, dict[str, object]] = {}
    for raw_key in control_keys:
        key = str(raw_key)
        reason = inactive.get(key, "")
        spec = material_authority_control_spec(key)
        if (
            spec is not None
            and spec.capability is MaterialAuthorityCapability.EXPERT_ONLY
            and not include_expert
        ):
            reason = "Unsafe Expert only: target-dependent or not trustworthy in the normal WYSIWYG preview."
        elif spec is not None and str(values.get(key, "") or "").strip().lower() in spec.expert_values:
            reason = "The selected routing value is an Unsafe Expert override and cannot receive the normal WYSIWYG badge."
        tooltip = str(control_tooltips.get(key, "") or "")
        if reason:
            tooltip = f"{tooltip}\n\n{reason}" if tooltip else reason
        states[key] = {
            "enabled": not reason,
            "tooltip": tooltip,
        }
    return states


def manual_material_profile_panel_state(
    profile_name: object,
    *,
    complete_enabled: bool,
) -> dict[str, bool]:
    manual_selected = str(profile_name or "") == "material_authority_manual"
    return {
        "visible": manual_selected,
        "enabled": bool(manual_selected),
    }


def manual_material_profile_token(
    profile_name: object,
    *,
    manual_token: object,
    fallback: str = "material_authority_detail_mask",
) -> str:
    selected = str(profile_name or fallback)
    if selected == "material_authority_manual":
        return str(manual_token)
    return selected or fallback


def manual_material_profile_initial_status_html() -> str:
    return (
        "<span style='color:#8b949e;'>Manual sliders queue preview refresh after input settles; "
        "Apply forces the current values now.</span>"
    )


def manual_profile_ready_initial_state() -> dict[str, bool]:
    return {"ready": False}


def manual_profile_dirty_initial_state() -> dict[str, bool]:
    return {"dirty": False}


def manual_material_profile_fallback_payload(profile: object) -> dict[str, str]:
    return {"name": str(getattr(profile, "name", "") or "")}


def manual_material_profile_preview_warning_html() -> str:
    return (
        "<div style='line-height:1.35;'>"
        "<div style='font-weight:700; color:#d29922; margin-bottom:3px;'>Preview warning</div>"
        "<table cellspacing='0' cellpadding='3' style='border-collapse:collapse;'>"
        "<tr><td><span style='color:#ffa657; font-weight:700;'>Tool preview</span></td>"
        "<td style='color:#c9d1d9;'>Approximation only.</td></tr>"
        "<tr><td><span style='color:#ff7b72; font-weight:700;'>In-game render</span></td>"
        "<td style='color:#8b949e;'>It cannot render the exact same textured look as the in-game CD shader, lighting, material layers, and post-processing.</td></tr>"
        "</table>"
        "</div>"
    )


def upsert_manual_material_profile_preset(
    presets: Sequence[Mapping[str, object]],
    preset: Mapping[str, object],
) -> list[dict[str, object]]:
    name = str(preset.get("name") or "").strip()
    if not name:
        return [dict(item) for item in presets if isinstance(item, Mapping)]
    next_presets = [dict(item) for item in presets if isinstance(item, Mapping)]
    lowered = name.casefold()
    clean_preset = dict(preset)
    clean_preset["name"] = name
    for index, existing in enumerate(tuple(next_presets)):
        if str(existing.get("name") or "").strip().casefold() == lowered:
            next_presets[index] = clean_preset
            break
    else:
        next_presets.append(clean_preset)
    return sorted(next_presets, key=lambda item: str(item.get("name") or "").casefold())


def delete_manual_material_profile_preset(
    presets: Sequence[Mapping[str, object]],
    name: object,
) -> list[dict[str, object]]:
    lowered = str(name or "").strip().casefold()
    return [
        dict(existing)
        for existing in presets
        if isinstance(existing, Mapping)
        and str(existing.get("name") or "").strip().casefold() != lowered
    ]


__all__ = [
    "MODIFY_ORIGINAL_MANUAL_TEXTURE_TUNING_KEYS",
    "coerce_manual_material_profile_values",
    "delete_manual_material_profile_preset",
    "load_manual_material_profile_presets",
    "load_manual_material_profile_values",
    "material_authority_resource_channels",
    "material_authority_target_height_supported",
    "manual_material_profile_default_values",
    "manual_material_profile_change_status_text",
    "manual_material_profile_control_text",
    "manual_material_profile_control_effect_states",
    "manual_material_profile_delete_question",
    "manual_material_profile_dirty_state",
    "manual_material_profile_inactive_reasons",
    "manual_material_profile_initial_status_html",
    "manual_material_profile_fallback_payload",
    "manual_material_profile_panel_state",
    "manual_material_profile_token",
    "manual_profile_dirty_initial_state",
    "manual_profile_ready_initial_state",
    "modify_original_advanced_texture_tuning_settings_key",
    "modify_original_manual_texture_tuning_presets_key",
    "modify_original_manual_texture_tuning_settings_key",
    "modify_original_manual_texture_tuning_values",
    "manual_material_profile_preset_from_fields",
    "manual_material_profile_preset_metadata",
    "manual_material_profile_preset_names",
    "manual_material_profile_presets_payload",
    "manual_material_profile_preview_warning_html",
    "manual_material_profile_saved_message",
    "manual_material_profile_texture_impact_html",
    "manual_material_profile_tooltips",
    "selected_manual_material_profile_preset",
    "stored_manual_material_profile_values",
    "upsert_manual_material_profile_preset",
]
