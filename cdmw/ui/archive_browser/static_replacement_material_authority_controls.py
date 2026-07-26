"""Material Authority control text and predicates for static replacement."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
from pathlib import Path

@dataclass(frozen=True)
class MaterialAuthorityPerformanceStatus:
    summary: str
    details: str = ""


MATERIAL_AUTHORITY_BASIC_CONTROL_PROFILES = frozenset(
    {
        "material_authority_true_source",
        "material_authority_pbr_source_test",
        "material_authority_detail_mask",
        "material_authority_clean_source",
        "material_authority_manual",
    }
)

MATERIAL_AUTHORITY_PREVIEW_SIGNATURE_VISIBLE_SLOTS = (
    "base",
    "material",
    "material_mask",
    "detail_mask",
    "emissive",
    "roughness",
    "metallic",
    "metalness",
    "ao",
    "normal",
    "height",
)

MATERIAL_AUTHORITY_EDGE_RELIEF_SOURCES = frozenset(
    {
        "hybrid",
        "preserve_target",
        "generate_source",
    }
)

MATERIAL_AUTHORITY_RESET_VALUES = {
    "global_gloss_reduction": 0,
    "auto_brightness": 50,
    "source_brightness": 0,
    "tone_contrast": 0,
    "edge_relief": 0,
    "edge_relief_source": "hybrid",
    "accent_glow": 0,
}

MATERIAL_AUTHORITY_VISIBLE_COMPLETE_SWAP_PROFILE_NAMES = (
    "material_authority_detail_mask",
    "material_authority_manual",
)

MATERIAL_AUTHORITY_STALE_GLOW_SETTINGS_KEYS = (
    "settings/complete_swap_accent_glow_strength",
    "settings/complete_swap_accent_glow_color_enabled",
    "settings/complete_swap_accent_glow_color_rgb",
)


def material_authority_basic_controls_profile_enabled(profile_name: object) -> bool:
    return str(profile_name or "") in MATERIAL_AUTHORITY_BASIC_CONTROL_PROFILES


def material_authority_clamped_int(
    value: object,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        number = int(round(float(value if value is not None else default)))
    except (TypeError, ValueError, OverflowError):
        number = int(default)
    return max(int(minimum), min(int(maximum), number))


def material_authority_edge_relief_source(value: object) -> str:
    source = str(value or "hybrid")
    if source not in MATERIAL_AUTHORITY_EDGE_RELIEF_SOURCES:
        return "hybrid"
    return source


def material_authority_reset_values() -> dict[str, object]:
    return dict(MATERIAL_AUTHORITY_RESET_VALUES)


def material_authority_requested_profile_name(
    profile_name: object,
    *,
    resolve_profile_name: object,
    fallback: str = "material_authority_detail_mask",
) -> str:
    requested = str(profile_name or "").strip() or fallback
    if requested.startswith("material_authority_manual:"):
        return "material_authority_manual"
    if callable(resolve_profile_name):
        try:
            resolved = resolve_profile_name(requested)
        except Exception:
            resolved = requested
        requested = str(resolved or requested)
    return requested or fallback


def material_authority_complete_swap_tooltip() -> str:
    return (
        "Material Authority uses the proven working-mod route: source color through _overlayColorTexture, "
        "source PBR/material mask through _detailMaskTexture, and no glossy color-blend mask. "
        "Manual starts from the same route and exposes advanced overrides."
    )


def material_authority_route_summary_text() -> str:
    return (
        "Materials default to the recommended source texture route. Material Authority tuning, sidecar pruning, "
        "manual slot mapping, and UV transforms are shown directly."
    )


def material_authority_global_gloss_tooltip() -> str:
    return (
        "Signed gloss/matte bias for generated material masks/scalar slots. "
        "Negative makes Material Authority glossier; positive makes it more matte. "
        "The legacy glossy color-blend route stays bypassed unless Manual mapping restores it."
    )


def material_authority_sidecar_warning_html() -> str:
    return (
        "<span style='color:#8b949e;'>Shader wrappers preserved; "
        "added parts can emit their own DDS bindings when routed.</span>"
    )


def material_authority_sidecar_warning_tooltip() -> str:
    return (
        "Source-driven patching keeps shader parameters and shared layers. "
        "Added parts with Base_Color/normal/material/height maps are routed through the selected target material; "
        "standalone Metallic/Roughness/AO maps still need packed material-mask routing."
    )


def material_authority_donor_control_text() -> dict[str, object]:
    return {
        "group_title": "Cross-Original Material Sources",
        "group_tooltip": (
            "Use Another Original Mesh lets a selected donor part provide original-game DDS bindings "
            "or a guarded .pac_xml material behavior graft."
        ),
        "hint": "Select a target row, then use another original mesh as a donor for textures or material behavior.",
        "use_button": "Use Another Original Mesh...",
        "use_button_tooltip": (
            "Open another loaded original mesh, inspect its parts/textures/.pac_xml shader family, "
            "and bind it to the selected target."
        ),
        "clear_button": "Clear Selected Target",
        "clear_button_tooltip": "Remove the donor material source assigned to the selected target row.",
        "plan_headers": ["Target", "Material source", "Donor", "Shader", "Status"],
        "dialog_title": "Use Another Original Mesh",
        "select_target_message": "Select a target draw/material row first, then choose the donor original mesh.",
        "no_mesh_message": "No other loaded original mesh entries are available.",
        "picker_prompt": "Search donor original mesh by name, path, package, or role",
        "progress_message": "Reading donor original mesh...",
        "donor_preview_note": "Donor original mesh preview.",
        "donor_preview_clear": (
            "Donor material source loaded.\n\n"
            "Geometry preview is skipped here to keep material selection responsive."
        ),
        "part_headers": ["Donor part", "Shader", "Textures", "Emissive/glow"],
        "texture_headers": ["Role", "Parameter", "DDS", "Shader", "State"],
        "parts_label": "Donor parts / material wrappers",
        "textures_label": "Donor sidecar texture bindings",
        "mode_label": "Material source",
        "mode_tooltip": (
            "Authoritative donor recipe rewrites the target wrapper with donor shader/texture/material parameters "
            "while preserving the target wrapper identity; "
            "Donor material behavior uses compatible target .pac_xml texture parameters first, then grafts the donor "
            "wrapper payload only when needed; "
            "Donor material profile grafts the donor wrapper but keeps current replacement base/normal bindings; "
            "Donor textures only patches compatible target texture parameters."
        ),
        "apply_button": "Use Selected Donor Material",
        "apply_button_tooltip": "Assign the selected donor part/material to the current target draw slot.",
        "profile_fallback_status": (
            "Using donor .pac_xml material recipe fallback. Authoritative donor recipe is selected by default "
            "and replaces inherited target material bindings."
        ),
        "default_status": (
            "Authoritative donor recipe is selected by default: it grafts the donor wrapper and replaces inherited "
            "target material bindings."
        ),
        "select_binding_message": "Select a donor part or texture binding first.",
        "unreadable_sidecar_message": (
            "The selected donor material has no readable .pac_xml/sidecar text, so it cannot be assigned."
        ),
        "assigned_status": "Assigned {donor_part_name} to {target_name}.",
    }


def material_authority_path_signature(value: object) -> tuple[str, int, int]:
    path_text = str(value or "").strip()
    if not path_text:
        return ("", 0, 0)
    try:
        path = Path(path_text).expanduser()
        stat = path.stat()
        return (str(path), int(stat.st_size), int(stat.st_mtime_ns))
    except (OSError, TypeError, ValueError):
        return (path_text, 0, 0)


def material_authority_preview_signature_hashes(
    *,
    visible_payload: object,
    controls: object,
) -> dict[str, str]:
    cache_payload = (visible_payload, controls)
    return {
        "visible": hashlib.sha1(repr(visible_payload).encode("utf-8", errors="replace")).hexdigest(),
        "cache": hashlib.sha1(repr(cache_payload).encode("utf-8", errors="replace")).hexdigest(),
    }


def material_authority_preview_signature(
    *,
    texture_sets: object,
    profile: object,
    source_part_adjustments: object,
    global_gloss_reduction: object,
    auto_brightness: object,
    source_brightness: object,
    tone_contrast: object,
    edge_relief: object,
    edge_relief_source: object,
    accent_glow: object,
    glow_color_enabled: object,
    glow_rgb: object,
    texture_slots_resolver: object,
    profile_payload_builder: object,
    fallback_profile_payload_builder: object,
) -> dict[str, str]:
    slot_rows = []
    items = texture_sets.items() if hasattr(texture_sets, "items") else ()
    for material_key, texture_set_obj in sorted((str(key), value) for key, value in items):
        try:
            slots = texture_slots_resolver(texture_set_obj, profile, enabled=True)
        except Exception:
            slots = texture_slots_resolver(texture_set_obj, enabled=False)
        for slot_name in MATERIAL_AUTHORITY_PREVIEW_SIGNATURE_VISIBLE_SLOTS:
            source_slot = slots.get(slot_name) if hasattr(slots, "get") else None
            if source_slot is None:
                continue
            slot_rows.append(
                material_authority_preview_slot_signature_row(
                    material_key=material_key,
                    slot_name=slot_name,
                    source_slot=source_slot,
                )
            )
    controls = material_authority_preview_controls_signature(
        global_gloss_reduction=global_gloss_reduction,
        auto_brightness=auto_brightness,
        source_brightness=source_brightness,
        tone_contrast=tone_contrast,
        edge_relief=edge_relief,
        edge_relief_source=edge_relief_source,
        accent_glow=accent_glow,
        glow_color_enabled=glow_color_enabled,
        glow_rgb=glow_rgb,
        source_role_rows=material_authority_source_role_signature_rows(source_part_adjustments),
    )
    try:
        profile_payload = profile_payload_builder(profile)
    except Exception:
        profile_payload = fallback_profile_payload_builder(profile)
    visible_payload = (
        str(getattr(profile, "name", "") or ""),
        profile_payload,
        tuple(slot_rows),
    )
    return material_authority_preview_signature_hashes(
        visible_payload=visible_payload,
        controls=controls,
    )


def material_authority_preview_slot_signature_row(
    *,
    material_key: object,
    slot_name: object,
    source_slot: object,
) -> tuple[object, ...]:
    source_path = getattr(source_slot, "source_path", "")
    return (
        str(material_key),
        str(slot_name),
        str(getattr(source_slot, "slot_kind", "") or ""),
        str(getattr(source_slot, "material_name", "") or ""),
        str(getattr(source_slot, "source_authority", "") or ""),
        tuple(getattr(source_slot, "base_color_factor", ()) or ()),
        float(getattr(source_slot, "base_color_scale", 1.0) or 1.0),
        int(getattr(source_slot, "base_color_lift", 0) or 0),
        float(getattr(source_slot, "base_color_gamma", 1.0) or 1.0),
        float(getattr(source_slot, "base_color_saturation", 1.0) or 1.0),
        int(getattr(source_slot, "base_color_value_max", 255) or 255),
        material_authority_path_signature(source_path),
    )


def material_authority_source_role_signature_rows(
    adjustments: object,
) -> tuple[tuple[object, ...], ...]:
    rows: list[tuple[object, ...]] = []
    items = adjustments.items() if hasattr(adjustments, "items") else ()
    for source_index, adjustment in sorted(items):
        material_role = str(getattr(adjustment, "material_role", "") or "")
        glow_rgb = tuple(getattr(adjustment, "emissive_color_rgb", ()) or ())
        emissive_strength = getattr(adjustment, "emissive_strength", None)
        try:
            material_brightness = round(float(getattr(adjustment, "material_brightness", 0.0) or 0.0), 4)
            material_contrast = round(float(getattr(adjustment, "material_contrast", 0.0) or 0.0), 4)
            material_saturation = round(float(getattr(adjustment, "material_saturation", 0.0) or 0.0), 4)
            material_gamma = round(float(getattr(adjustment, "material_gamma", 1.0) or 1.0), 4)
        except (TypeError, ValueError, OverflowError):
            material_brightness = material_contrast = material_saturation = 0.0
            material_gamma = 1.0
        material_tint = tuple(getattr(adjustment, "material_tint_rgb", ()) or ())
        material_tint_rgb = tuple(int(value) for value in material_tint[:3]) if material_tint else ()
        colourise = tuple(getattr(adjustment, "material_colourise_rgb", ()) or ())
        colourise_rgb = tuple(int(value) for value in colourise[:3]) if colourise else ()
        try:
            colourise_strength = round(
                max(0.0, min(1.0, float(getattr(adjustment, "material_colourise_strength", 0.0) or 0.0))),
                4,
            )
        except (TypeError, ValueError, OverflowError):
            colourise_strength = 0.0
        has_material_adjustment = (
            abs(material_brightness) > 0.0001
            or abs(material_contrast) > 0.0001
            or abs(material_saturation) > 0.0001
            or abs(material_gamma - 1.0) > 0.0001
            or bool(material_tint_rgb)
            or colourise_strength > 0.0001
        )
        if not material_role.strip() and not glow_rgb and emissive_strength is None and not has_material_adjustment:
            continue
        rows.append(
            (
                int(source_index),
                material_role,
                tuple(int(value) for value in glow_rgb),
                None if emissive_strength is None else max(0.0, round(float(emissive_strength), 4)),
                material_brightness,
                material_contrast,
                material_saturation,
                material_gamma,
                material_tint_rgb,
                colourise_rgb,
                colourise_strength,
            )
        )
    return tuple(rows)


def material_authority_preview_controls_signature(
    *,
    global_gloss_reduction: object,
    auto_brightness: object,
    source_brightness: object,
    tone_contrast: object,
    edge_relief: object,
    edge_relief_source: object,
    accent_glow: object,
    glow_color_enabled: object,
    glow_rgb: object,
    source_role_rows: object,
) -> tuple[object, ...]:
    return (
        int(global_gloss_reduction),
        int(auto_brightness),
        int(source_brightness),
        int(tone_contrast),
        int(edge_relief),
        str(edge_relief_source or "hybrid"),
        int(accent_glow),
        bool(glow_color_enabled),
        tuple(glow_rgb or ()),
        tuple(source_role_rows or ()),
    )


def material_authority_profile_adjustment_kwargs(
    *,
    global_gloss_reduction: object,
    edge_relief: object,
    edge_relief_source: object,
    accent_glow: object,
    auto_brightness: object,
    source_brightness: object,
    tone_contrast: object,
) -> dict[str, object]:
    return {
        "gloss_reduction": float(global_gloss_reduction),
        "edge_relief_strength": float(edge_relief),
        "edge_relief_source": material_authority_edge_relief_source(edge_relief_source),
        "accent_glow_strength": float(accent_glow),
        "auto_brightness_balance": float(auto_brightness),
        "dark_detail_lift": float(source_brightness),
        "tone_contrast": float(tone_contrast),
    }


def material_authority_global_gloss_reduction_hint(
    *,
    complete_enabled: bool,
    profile_name: object,
    value: object,
) -> str:
    try:
        gloss_value = int(value)
    except (TypeError, ValueError, OverflowError):
        gloss_value = 0
    profile = str(profile_name or "")
    if not complete_enabled:
        return "Enable Complete source-owned mesh/material swap to use gloss/matte bias."
    if profile == "material_authority_runtime_xml":
        return "Legacy Runtime XML preserves stock material layers; this only affects generated masks or compatible scalar slots."
    if profile == "material_authority_detail_mask" and gloss_value < 0:
        return (
            "Material Authority gloss boost lowers generated detail-mask roughness and raises compatible shine; "
            "the glossy color-blend mask stays bypassed."
        )
    if profile == "material_authority_detail_mask" and gloss_value > 0:
        return "Material Authority matte bias raises generated detail-mask roughness; the glossy color-blend mask stays bypassed."
    if profile == "material_authority_pbr_source_test" and gloss_value >= 90:
        return "PBR Source Test: strong gloss cut raises source material roughness while preserving source metalness."
    if gloss_value < 0:
        return "Gloss boost: generated source-owned materials get lower roughness and stronger compatible shine."
    if gloss_value == 0:
        return "0% keeps the proven Material Authority response."
    if gloss_value >= 90:
        return "Strong matte override: CD gloss/smoothness and metal/spec response are driven low."
    return "Generated source-owned materials get lower CD gloss/smoothness and metal/shine response."


def material_authority_preview_inactive_reason(
    *,
    complete_enabled: bool,
    basic_profile_enabled: bool,
    has_texture_sets: bool,
    original_material_preview_active: bool,
) -> str:
    if not complete_enabled:
        return "Complete source-owned swap is off."
    if not basic_profile_enabled:
        return "Selected material profile does not use Material Authority adjustments."
    if not has_texture_sets:
        return "No source texture set is loaded."
    if original_material_preview_active:
        return "Original-material preview is active."
    return ""


def material_authority_controls_affect_visible_preview(inactive_reason: object) -> bool:
    return not bool(inactive_reason)


def material_authority_adjustment_status_text(
    *,
    basic_profile_enabled: bool,
    inactive_reason: str,
) -> str:
    if inactive_reason:
        if basic_profile_enabled:
            return f"Adjustments updated. Preview unchanged: {inactive_reason}"
        return ""
    return "Adjustments updated. Preview refresh queued."


def material_authority_adjustment_refresh_reason() -> str:
    return "material authority adjustment"


def material_authority_preview_signature_initial_state() -> dict[str, str]:
    return {"visible": "", "cache": ""}


def material_authority_complete_swap_routing_progress_message() -> str:
    return "Applying complete source-owned swap routing."


def material_authority_complete_swap_routing_reason() -> str:
    return "complete source-owned swap routing"


def material_authority_complete_swap_update_queued_message() -> str:
    return "Complete source-owned swap update queued."


def material_authority_complete_swap_update_performance() -> MaterialAuthorityPerformanceStatus:
    return MaterialAuthorityPerformanceStatus(
        summary=material_authority_complete_swap_update_queued_message(),
        details=(
            "Child material options are updated without firing their individual preview refreshes; "
            "one routing/material preview rebuild is queued after the UI repaints."
        ),
    )


def material_authority_complete_swap_next_transition_generation(value: object) -> int:
    try:
        current = int(value or 0)
    except (TypeError, ValueError, OverflowError):
        current = 0
    return current + 1


def material_authority_complete_swap_forced_child_states(
    *,
    rebuild_sidecar: object,
    inject_base_color: object,
    source_color_faithful: object,
    external_material_reset: object,
    prune_unmapped_original_dds: object,
) -> tuple[bool, bool, bool, bool, bool]:
    return (
        bool(rebuild_sidecar),
        bool(inject_base_color),
        bool(source_color_faithful),
        bool(external_material_reset),
        bool(prune_unmapped_original_dds),
    )


def material_authority_complete_swap_restored_child_states(
    previous_states: object,
) -> dict[str, bool] | None:
    if not isinstance(previous_states, tuple) or len(previous_states) != 5:
        return None
    return {
        "rebuild_sidecar": bool(previous_states[0]),
        "inject_base_color": bool(previous_states[1]),
        "source_color_faithful": bool(previous_states[2]),
        "external_material_reset": bool(previous_states[3]),
        "prune_unmapped_original_dds": bool(previous_states[4]),
    }


def material_authority_complete_swap_source_output_size_index(source_index: object) -> int:
    try:
        index = int(source_index)
    except (TypeError, ValueError, OverflowError):
        index = -1
    return max(0, index)


def material_authority_complete_swap_profile_name(
    current_profile: object,
    *,
    fallback: str = "material_authority_detail_mask",
) -> str:
    return str(current_profile or "").strip() or fallback


def material_authority_complete_swap_should_apply_checked(
    *,
    current_generation: object,
    expected_generation: object,
    checked: object,
) -> bool:
    try:
        current = int(current_generation or 0)
        expected = int(expected_generation or 0)
    except (TypeError, ValueError, OverflowError):
        return False
    return current == expected and bool(checked)


def material_authority_adjustment_setting_state(
    value: object,
    *,
    default: int,
    minimum: int,
    maximum: int,
    settings_key: str = "",
) -> dict[str, object]:
    return {
        "value": material_authority_clamped_int(
            value,
            default=default,
            minimum=minimum,
            maximum=maximum,
        ),
        "settings_key": str(settings_key or ""),
    }


def material_authority_edge_relief_source_setting(value: object) -> dict[str, str]:
    return {
        "value": material_authority_edge_relief_source(value),
        "settings_key": "settings/complete_swap_edge_relief_source",
    }


def material_authority_control_tooltips() -> dict[str, str]:
    return {
        "custom_glow_checkbox": (
            "Optional color override for source parts explicitly marked Role: Glow / emissive. "
            "Accent glow at 0% disables emissive output."
        ),
        "custom_glow_channel": (
            "Custom glow/emissive color channel for source parts marked Role: Glow / emissive."
        ),
        "custom_glow_pick": "Choose a custom glow/emissive color for glow-role source parts.",
        "reset_adjustments": (
            "Reset Material Authority adjustment sliders to the recommended live-preview defaults."
        ),
        "unsafe_preflight": (
            "Expert loose-export override. If material preflight finds non-authoritative bindings, "
            "write the loose mod anyway. This is ignored for direct archive patch and may produce "
            "original tint/gloss/layers, grey parts, or missing textures in-game."
        ),
    }


def material_authority_setup_tooltips() -> dict[str, str]:
    return {
        "rebuild_sidecar": (
            "Writes a patched .pac_xml/.pami so compatible source textures replace target texture slots. "
            "This preserves the target shader behavior unless the neutralize or complete-swap options below are enabled."
        ),
        "prune_unmapped_original_dds": (
            "After source textures are bound, delete original DDS parameters that are not part of the new visible material contract. "
            "Leave off only when you intentionally want hidden original shader layers to remain."
        ),
        "inject_base_color": (
            "If an imported part has a base-color texture but the chosen target wrapper has no safe color parameter, add one in the generated sidecar."
        ),
        "source_color_faithful": (
            "Use when the target's original material makes imported textures too colored, dirty, dark, or patterned. "
            "This can change the source colors, so leave it off unless old grime/detail/color-blend/tint layers visibly pollute the new DDS."
        ),
        "external_material_reset": (
            "Experimental repair for stubborn target shaders. It can remove cloth/sheen/scratch/height response and should stay off unless normal source-owned binding still looks wrong."
        ),
        "complete_external_swap": (
            "Treat the imported mesh and its source DDS files as the visible authority. This auto-routes replacement parts and writes source texture bindings; "
            "source sidecar binding, unused-original pruning, missing base slots, tint/detail neutralization, and inherited material-response reset are forced while enabled."
        ),
    }


def material_authority_setup_labels() -> dict[str, str]:
    return {
        "rebuild_sidecar": "Bind source textures in target sidecar",
        "prune_unmapped_original_dds": "Remove unused original texture refs",
        "inject_base_color": "Create missing base-color slot",
        "source_color_faithful": "Neutralize original tint/detail layers",
        "external_material_reset": "Advanced: reset inherited material response",
        "complete_external_swap": "Complete source-owned mesh/material swap",
        "runtime_material_profile": "Runtime material profile",
        "unsafe_preflight": "Allow unsafe material preflight export",
        "texture_size": "Texture size",
        "texture_orientation": "Texture orientation",
    }


def material_authority_adjustment_tooltips() -> dict[str, str]:
    return {
        "source_brightness": (
            "Signed source base-color brightness before DDS export. "
            "Negative dims the generated source color; positive lifts dark and midtone detail."
        ),
        "tone_contrast": (
            "Manual tone curve after auto brightness. Negative softens harsh contrast; positive increases texture contrast."
        ),
        "auto_brightness": (
            "Measures each source base texture and nudges very dark or very bright textures toward a stable in-game midrange before DDS export."
        ),
        "edge_relief": (
            "Adds shader/texture relief for source-owned material edges. This does not edit mesh geometry."
        ),
        "edge_relief_source": (
            "Preserve target support keeps compatible height/detail support slots; Generate from source builds simple support from source textures; Hybrid tries target support first."
        ),
        "accent_glow": (
            "Adds emissive shader parameters to source-owned accent parts such as gem, crystal, rune, glow, flame, lens, eye, and other emissive-named materials."
        ),
    }


def material_authority_adjustment_labels() -> dict[str, str]:
    return {
        "group_title": "Material Authority Adjustments",
        "global_gloss_bias": "Gloss / matte bias",
        "global_gloss_hint": "0% keeps the proven Material Authority response.",
        "auto_brightness": "Auto brightness",
        "source_brightness": "Source brightness",
        "tone_contrast": "Tone contrast",
        "edge_relief": "Edge relief",
        "edge_relief_source": "Edge relief source",
        "accent_glow": "Accent glow",
        "glow_color": "Glow color",
        "custom_glow_color": "Custom glow color",
        "custom_glow_pick": "Pick",
        "reset_adjustments": "Reset Adjustments",
        "hint": "Defaults keep the proven route; these controls affect generated source-owned DDS/XML only.",
    }


def material_authority_stale_glow_settings_keys() -> tuple[str, ...]:
    return MATERIAL_AUTHORITY_STALE_GLOW_SETTINGS_KEYS


def material_authority_basic_controls_hint(
    *,
    visible: bool,
    enabled: bool,
    inactive_reason: str,
) -> str:
    if not visible:
        return "Select Material Authority or Manual to use material controls."
    if not enabled:
        return "Select Material Authority or Manual to use material controls."
    if inactive_reason:
        return f"Settings apply on export. Preview unchanged: {inactive_reason}"
    return "Auto brightness normalizes source base DDS exposure; Source brightness can dim or lift source color; Tone contrast shapes the curve."


def material_authority_sidecar_option_state(
    *,
    sidecar_enabled: bool,
    complete_mode: bool,
    unsafe_preflight_checked: bool,
) -> dict[str, bool]:
    if complete_mode and not sidecar_enabled:
        return {
            "force_rebuild_sidecar": True,
            "clear_dependent_sidecar_options": False,
            "rebuild_sidecar_enabled": False,
            "dependent_sidecar_options_enabled": False,
            "complete_material_controls_enabled": True,
            "unsafe_preflight_enabled": True,
            "clear_unsafe_preflight": False,
        }
    dependent_enabled = bool(sidecar_enabled and not complete_mode)
    return {
        "force_rebuild_sidecar": False,
        "clear_dependent_sidecar_options": not sidecar_enabled,
        "rebuild_sidecar_enabled": not complete_mode,
        "dependent_sidecar_options_enabled": dependent_enabled,
        "complete_material_controls_enabled": True,
        "unsafe_preflight_enabled": bool(complete_mode),
        "clear_unsafe_preflight": bool(not complete_mode and unsafe_preflight_checked),
    }


def material_authority_sidecar_dependent_toggle_state(
    *,
    checked: object,
    rebuild_sidecar_checked: object,
    refresh_output: bool = False,
) -> dict[str, bool]:
    force_rebuild = bool(checked and not rebuild_sidecar_checked)
    return {
        "force_rebuild_sidecar": force_rebuild,
        "refresh_output": bool(refresh_output and not force_rebuild),
        "refresh_preview": not force_rebuild,
    }


def material_authority_sidecar_control_application_state(
    sidecar_state: Mapping[str, object],
) -> dict[str, object]:
    complete_controls_enabled = bool(sidecar_state.get("complete_material_controls_enabled"))
    dependent_controls_enabled = bool(sidecar_state.get("dependent_sidecar_options_enabled"))
    return {
        "force_rebuild_sidecar": bool(sidecar_state.get("force_rebuild_sidecar")),
        "clear_dependent_sidecar_options": bool(sidecar_state.get("clear_dependent_sidecar_options")),
        "clear_unsafe_preflight": bool(sidecar_state.get("clear_unsafe_preflight")),
        "rebuild_sidecar_enabled": bool(sidecar_state.get("rebuild_sidecar_enabled")),
        "dependent_sidecar_options_enabled": dependent_controls_enabled,
        "complete_material_controls_enabled": complete_controls_enabled,
        "unsafe_preflight_enabled": bool(sidecar_state.get("unsafe_preflight_enabled")),
        "dependent_control_keys": (
            "prune_unmapped_original_dds",
            "inject_base_color",
            "source_color_faithful",
            "external_material_reset",
        ),
        "complete_control_keys": (
            "complete_swap_material_profile",
            "global_gloss_reduction",
            "auto_brightness",
            "source_brightness",
            "tone_contrast", "edge_relief", "edge_relief_source",
            "accent_glow",
            "reset_adjustments",
        ),
    }


def _set_widget_enabled(widget: object, enabled: bool) -> None:
    if hasattr(widget, "setEnabled"):
        widget.setEnabled(bool(enabled))


def _set_widget_checked(widget: object, checked: bool) -> None:
    if hasattr(widget, "setChecked"):
        widget.setChecked(bool(checked))


def material_authority_apply_sidecar_control_state(
    sidecar_state: Mapping[str, object],
    *,
    rebuild_sidecar_widget: object,
    dependent_widgets: Sequence[object],
    complete_widgets: Sequence[object],
    unsafe_preflight_widget: object,
) -> dict[str, object]:
    state = material_authority_sidecar_control_application_state(sidecar_state)
    if state["force_rebuild_sidecar"]:
        _set_widget_checked(rebuild_sidecar_widget, True)
        return state
    if state["clear_dependent_sidecar_options"]:
        for widget in dependent_widgets:
            _set_widget_checked(widget, False)
    _set_widget_enabled(rebuild_sidecar_widget, bool(state["rebuild_sidecar_enabled"]))
    for widget in dependent_widgets:
        _set_widget_enabled(widget, bool(state["dependent_sidecar_options_enabled"]))
    for widget in complete_widgets:
        _set_widget_enabled(widget, bool(state["complete_material_controls_enabled"]))
    _set_widget_enabled(unsafe_preflight_widget, bool(state["unsafe_preflight_enabled"]))
    if state["clear_unsafe_preflight"]:
        _set_widget_checked(unsafe_preflight_widget, False)
    return state


__all__ = [
    "MATERIAL_AUTHORITY_BASIC_CONTROL_PROFILES",
    "MATERIAL_AUTHORITY_EDGE_RELIEF_SOURCES",
    "MATERIAL_AUTHORITY_PREVIEW_SIGNATURE_VISIBLE_SLOTS",
    "MATERIAL_AUTHORITY_RESET_VALUES",
    "MATERIAL_AUTHORITY_STALE_GLOW_SETTINGS_KEYS",
    "MATERIAL_AUTHORITY_VISIBLE_COMPLETE_SWAP_PROFILE_NAMES",
    "MaterialAuthorityPerformanceStatus",
    "material_authority_adjustment_refresh_reason",
    "material_authority_adjustment_status_text",
    "material_authority_adjustment_setting_state",
    "material_authority_apply_sidecar_control_state",
    "material_authority_adjustment_labels",
    "material_authority_adjustment_tooltips",
    "material_authority_basic_controls_hint",
    "material_authority_basic_controls_profile_enabled",
    "material_authority_clamped_int",
    "material_authority_complete_swap_forced_child_states",
    "material_authority_complete_swap_next_transition_generation",
    "material_authority_complete_swap_profile_name",
    "material_authority_complete_swap_restored_child_states",
    "material_authority_complete_swap_routing_progress_message",
    "material_authority_complete_swap_routing_reason",
    "material_authority_complete_swap_should_apply_checked",
    "material_authority_complete_swap_source_output_size_index",
    "material_authority_complete_swap_tooltip",
    "material_authority_complete_swap_update_performance",
    "material_authority_complete_swap_update_queued_message",
    "material_authority_controls_affect_visible_preview",
    "material_authority_control_tooltips",
    "material_authority_donor_control_text",
    "material_authority_edge_relief_source",
    "material_authority_edge_relief_source_setting",
    "material_authority_global_gloss_tooltip",
    "material_authority_global_gloss_reduction_hint",
    "material_authority_path_signature",
    "material_authority_profile_adjustment_kwargs",
    "material_authority_preview_controls_signature",
    "material_authority_preview_inactive_reason",
    "material_authority_preview_signature",
    "material_authority_preview_signature_initial_state",
    "material_authority_preview_signature_hashes",
    "material_authority_preview_slot_signature_row",
    "material_authority_reset_values",
    "material_authority_requested_profile_name",
    "material_authority_route_summary_text",
    "material_authority_sidecar_warning_html",
    "material_authority_sidecar_warning_tooltip",
    "material_authority_sidecar_control_application_state",
    "material_authority_sidecar_dependent_toggle_state",
    "material_authority_sidecar_option_state",
    "material_authority_setup_labels",
    "material_authority_setup_tooltips",
    "material_authority_source_role_signature_rows",
    "material_authority_stale_glow_settings_keys",
]
