"""Source-driven material texture helpers for static replacement."""

from __future__ import annotations

import hashlib
import re
import tempfile
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Optional, Sequence

from cdmw.domain.textures.material_parameters import effective_emissive_intensity, evaluate_material_parameters

from .asset_replacement import classify_texture_binding, infer_cd_texture_role_from_path
from .pac_xml_profiles import (
    PacXmlCorpusIndex,
    PacXmlProfileReport,
    PacXmlTemplateMatch,
    PacXmlWrapperProfile,
    build_pac_xml_profile_match_report,
    load_or_build_pac_xml_corpus_index,
    pac_xml_parameter_for_slot,
    parse_pac_xml_profile,
    select_best_pac_xml_template,
)
from .static_mesh_replacer import StaticOutputDrawSection
from .material_profiles import (
    CDMaterialRuntimeProfile,
    apply_true_source_basic_controls_to_profile,
    _profile_accent_glow_intensity,
    _profile_accent_glow_strength,
    _profile_allows_factor_only_authority,
    _profile_applies_source_pbr_scalars_with_preserved_layers,
    _profile_authority_contract,
    _profile_base_binding_mode,
    _profile_bruteforce_texture_scope,
    _profile_base_color_gamma,
    _profile_base_color_lift,
    _profile_base_color_saturation,
    _profile_forces_neutral_layer_support,
    _profile_is_material_authority_bruteforce,
    _profile_is_runtime_xml,
    _profile_is_source_only,
    _profile_ma_rgb_roles,
    _profile_mask_binding_mode,
    _profile_metallic_inverted,
    _profile_optional_byte,
    _profile_optional_scale,
    _profile_preserves_target_layer_response,
    _profile_routes_source_color_to_layer_slots,
    _profile_roughness_inverted,
    _profile_source_emissive_enabled,
    _profile_support_policy,
    _profile_uses_cd_smoothness_mask_response,
    _profile_uses_detail_mask_material_contract,
    _profile_uses_factor_only_material_mask,
    get_complete_swap_material_profile,
    normalize_basic_control_percent,
    normalize_edge_relief_source,
    normalize_tone_contrast,
)
from .material_sidecar_patching import (
    _normalize_texture_path,
    _apply_source_emissive_parameters,
    _apply_source_pbr_scalar_parameters,
    _neutralize_inherited_material_layers,
    _normalize_sidecar_material_name,
    _prune_source_owned_sidecar_material_wrappers,
    _reorder_source_owned_sidecar_material_wrappers,
    _sidecar_material_match_score,
    _sidecar_material_names_match,
    _sync_submesh_resources_vector_idbase,
    _escape_xml_attr,
    _next_material_parameter_index,
    _rename_sidecar_parameter_name,
    _renumber_sidecar_parameter_indexes,
    _shift_sidecar_parameter_indexes,
    _sidecar_parameter_name,
    _sidecar_texture_injection_position,
    _set_source_driven_wrapper_shader_name,
    _source_driven_parameter_item_id,
)
from .material_sidecar_payloads import (
    _apply_sidecar_material_wrapper_clones,
    _build_patched_sidecar_payloads,
    _build_removed_target_prune_sidecar_payloads,
    _visible_gem_sensitive_wrappers_touched,
)
from .material_texture_payloads import (
    _append_texture_contract_warnings,
    _build_texture_payload,
    _source_slot_needs_base_alpha_factor,
    _warn_once,
)
from .material_rebuilt_payloads import (
    _atlas_section_for_target,
    _atlas_sections_by_target_name,
    _build_complete_swap_atlas_material_payloads,
    _slot_for_complete_swap_atlas_role,
)
from .material_replacer import (
    ReplacementTextureSet,
    ReplacementTextureSlot,
    SidecarMaterialWrapperClone,
    SidecarPatchReport,
    TextureReplacementPayload,
    TextureReplacementReport,
    TextureSlotMapping,
    _overlay_original_sidecars_with_payloads,
    _replace_sidecar_payloads,
    _sidecar_texture_parameter_rows,
    is_static_replacement_helper_material_name,
    _material_authority_wrapper_needs_target_safe_preserve,
)



def _looks_like_layered_detail_texture(target_path: str) -> bool:
    """Match layered/detail texture *names* by substring marker.

    Deliberately not the same rule as
    `cdmw.domain.textures.semantics.is_stock_or_shared_texture_path`, which
    matches shipped stock assets by basename prefix. These two answered to the
    same name until 2026-07-25 and are easy to confuse: this one is a loose
    naming heuristic, that one is a do-not-overwrite guard.
    """

    basename = PurePosixPath(str(target_path or "").replace("\\", "/")).name.lower()
    return any(
        marker in basename
        for marker in (
            "layer",
            "grime",
            "damage",
            "detail",
            "shared",
            "blend",
            "maskblend",
        )
    )


def _source_driven_slots(
    texture_set: ReplacementTextureSet,
    *,
    include_pbr_material_fallback: bool = False,
    include_complete_support_fallbacks: bool = False,
    material_profile: Optional[CDMaterialRuntimeProfile] = None,
) -> list[ReplacementTextureSlot]:
    # Source-driven .pac_xml patching stays conservative but understands full
    # Crimson material families.  Clear CD roles (_o/_n/_disp/_ma/_mg) may be
    # routed; standalone glTF PBR maps are not Crimson color-blend masks.
    profile = material_profile or get_complete_swap_material_profile()
    base_binding_mode = _profile_base_binding_mode(profile)
    mask_binding_mode = _profile_mask_binding_mode(profile)
    support_policy = _profile_support_policy(profile)
    source_only = _profile_is_source_only(profile)
    runtime_xml_profile = _profile_is_runtime_xml(profile)
    allow_factor_only_authority = _profile_allows_factor_only_authority(profile)
    order = ("base", "normal", "height", "material_mask", "detail_mask", "emissive")
    slots: list[ReplacementTextureSlot] = []
    seen_paths: set[tuple[str, str]] = set()

    def profile_adjusted_slot(source_slot: ReplacementTextureSlot) -> ReplacementTextureSlot:
        slot_kind = str(source_slot.slot_kind or "").strip().lower()
        if slot_kind not in {"base", "emissive"}:
            return source_slot
        if not (_source_slot_is_real_texture(source_slot) or _source_slot_is_synthetic_factor_authority(source_slot)):
            return source_slot
        if slot_kind == "emissive":
            scale = _profile_optional_scale(profile, "emissive_color_scale")
            saturation = _profile_optional_scale(profile, "emissive_color_saturation")
            value_max = _profile_optional_byte(profile, "emissive_color_value_max")
            override_rgb = _normalized_accent_glow_rgb(
                getattr(texture_set, "accent_glow_color_rgb", ())
            )
            if scale is None and saturation is None and value_max is None and not override_rgb:
                return source_slot
            return replace(
                source_slot,
                base_color_factor=override_rgb or tuple(source_slot.base_color_factor or ()),
                base_color_scale=scale if scale is not None else 1.0,
                base_color_lift=0,
                base_color_gamma=1.0,
                base_color_saturation=saturation if saturation is not None else 1.0,
                base_color_value_max=value_max if value_max is not None else 255,
            )
        lift = _profile_base_color_lift(profile)
        scale = _profile_optional_scale(profile, "base_color_scale")
        gamma = _profile_base_color_gamma(profile)
        saturation = _profile_base_color_saturation(profile)
        value_max = _profile_optional_byte(profile, "base_color_value_max")
        auto_balance = int(max(0, min(100, int(getattr(profile, "base_color_auto_balance", 0) or 0))))
        shadow_lift = int(max(0, min(100, int(getattr(profile, "base_color_shadow_lift", 0) or 0))))
        tone_contrast = normalize_tone_contrast(getattr(profile, "base_color_tone_contrast", 0.0))
        if (
            lift <= 0
            and scale is None
            and abs(gamma - 1.0) <= 0.0001
            and abs(saturation - 1.0) <= 0.0001
            and value_max is None
            and auto_balance <= 0
            and shadow_lift <= 0
            and abs(tone_contrast) <= 0.0001
        ):
            return source_slot
        return replace(
            source_slot,
            base_color_scale=scale if scale is not None else 1.0,
            base_color_lift=lift,
            base_color_gamma=gamma,
            base_color_saturation=saturation,
            base_color_value_max=value_max if value_max is not None else 255,
            base_color_auto_balance=auto_balance,
            base_color_shadow_lift=shadow_lift,
            base_color_tone_contrast=tone_contrast,
        )

    spec_gloss_base_slot = _specular_glossiness_runtime_base_slot(texture_set)
    for slot_kind in order:
        if slot_kind == "base" and base_binding_mode == "disabled":
            continue
        if slot_kind == "material_mask" and mask_binding_mode == "disabled":
            continue
        if runtime_xml_profile and slot_kind in {"height", "material_mask", "detail_mask"}:
            continue
        if slot_kind == "emissive" and not _profile_source_emissive_enabled(profile):
            continue
        if slot_kind == "emissive" and include_complete_support_fallbacks and profile.emissive_mode != "intensity":
            continue
        source_slot = spec_gloss_base_slot if slot_kind == "base" and spec_gloss_base_slot is not None else texture_set.slots.get(slot_kind)
        if source_slot is None and slot_kind == "ao":
            source_slot = texture_set.slots.get("occlusion")
        if source_slot is None:
            continue
        if source_only and not _source_slot_is_real_texture(source_slot):
            if not (allow_factor_only_authority and _source_slot_is_synthetic_factor_authority(source_slot)):
                continue
        key = (str(source_slot.source_path.expanduser().resolve()).lower(), str(source_slot.slot_kind).lower())
        if key in seen_paths:
            continue
        seen_paths.add(key)
        slots.append(profile_adjusted_slot(source_slot))
    if (
        include_pbr_material_fallback
        and mask_binding_mode != "disabled"
        and not any(slot.slot_kind in {"material", "material_mask"} for slot in slots)
    ):
        for fallback_kind in ("material",):
            source_slot = texture_set.slots.get(fallback_kind)
            if source_slot is None:
                continue
            if _source_slot_is_explicit_pbr(source_slot):
                generated_slot = _complete_swap_runtime_material_mask_slot(texture_set, profile)
                key = (str(generated_slot.source_path.expanduser().resolve()).lower(), "material_mask")
                if key in seen_paths:
                    continue
                seen_paths.add(key)
                slots.append(generated_slot)
                break
            normalized_name = re.sub(r"[^a-z0-9]+", "", source_slot.source_path.name.lower())
            if any(
                token in normalized_name
                for token in ("metallicroughness", "metalrough", "metallicrough", "roughnessmetallic", "roughmetal")
            ):
                continue
            key = (str(source_slot.source_path.expanduser().resolve()).lower(), "material_mask")
            if key in seen_paths:
                continue
            seen_paths.add(key)
            slots.append(
                ReplacementTextureSlot(
                    material_name=source_slot.material_name,
                    slot_kind="material_mask",
                    source_path=source_slot.source_path,
                    normal_space=source_slot.normal_space,
                )
            )
            break
    if source_only:
        existing_kinds = {str(slot.slot_kind or "").strip().lower() for slot in slots}
        if include_complete_support_fallbacks and _profile_forces_neutral_layer_support(profile):
            has_explicit_source_pbr = _texture_set_has_explicit_source_pbr(texture_set)
            for fallback_kind in ("normal", "height", "material_mask", "detail_mask"):
                if fallback_kind == "material_mask" and has_explicit_source_pbr and mask_binding_mode != "disabled":
                    continue
                if fallback_kind in existing_kinds:
                    continue
                source_slot = _complete_swap_neutral_support_slot(texture_set, fallback_kind, material_profile=profile)
                key = (str(source_slot.source_path.expanduser().resolve()).lower(), str(source_slot.slot_kind).lower())
                if key in seen_paths:
                    continue
                seen_paths.add(key)
                slots.append(source_slot)
                existing_kinds.add(fallback_kind)
        if (
            include_complete_support_fallbacks
            and "material_mask" not in existing_kinds
            and mask_binding_mode != "disabled"
            and _texture_set_has_explicit_source_pbr(texture_set)
        ):
            source_slot = _complete_swap_runtime_material_mask_slot(texture_set, profile)
            key = (str(source_slot.source_path.expanduser().resolve()).lower(), str(source_slot.slot_kind).lower())
            if key not in seen_paths:
                seen_paths.add(key)
                slots.append(source_slot)
        elif (
            include_complete_support_fallbacks
            and "material_mask" not in existing_kinds
            and mask_binding_mode != "disabled"
            and _profile_uses_factor_only_material_mask(profile)
            and _texture_set_has_source_authority_data(texture_set)
        ):
            source_slot = _complete_swap_factor_only_material_mask_slot(texture_set, profile)
            key = (str(source_slot.source_path.expanduser().resolve()).lower(), str(source_slot.slot_kind).lower())
            if key not in seen_paths:
                seen_paths.add(key)
                slots.append(source_slot)
        return slots
    if include_complete_support_fallbacks and support_policy != "keep_original_support":
        existing_kinds = {str(slot.slot_kind or "").strip().lower() for slot in slots}
        for fallback_kind in ("normal", "height", "material_mask", "detail_mask"):
            if fallback_kind == "material_mask" and mask_binding_mode == "disabled":
                continue
            if fallback_kind in existing_kinds:
                continue
            source_slot = texture_set.slots.get(fallback_kind)
            if source_slot is None and fallback_kind == "material_mask":
                source_slot = _complete_swap_runtime_material_mask_slot(texture_set, profile)
            if source_slot is None:
                source_slot = _complete_swap_neutral_support_slot(texture_set, fallback_kind, material_profile=profile)
            key = (str(source_slot.source_path.expanduser().resolve()).lower(), str(source_slot.slot_kind).lower())
            if key in seen_paths:
                continue
            seen_paths.add(key)
            slots.append(source_slot)
    return slots




def _complete_swap_material_divergence_reasons(
    texture_set: ReplacementTextureSet,
    material_profile: CDMaterialRuntimeProfile,
) -> tuple[str, ...]:
    reasons: list[str] = []
    rgb_roles = _profile_ma_rgb_roles(material_profile)
    if rgb_roles != ("ao", "roughness", "metallic"):
        reasons.append("mask channel layout is " + "/".join(rgb_roles).upper())
    if _profile_roughness_inverted(material_profile):
        reasons.append("roughness polarity inverted")
    if _profile_metallic_inverted(material_profile):
        reasons.append("metallic polarity inverted")
    if bool(material_profile.force_nonmetal):
        reasons.append("metallic forced to exact zero")
    ao_mode = str(getattr(material_profile, "ao_mode", "") or "").strip().lower()
    if ao_mode == "white":
        reasons.append("AO forced white")
    emissive_mode = str(getattr(material_profile, "emissive_mode", "") or "disabled").strip().lower()
    if emissive_mode == "disabled" and "emissive" in texture_set.slots:
        reasons.append("source emissive present but calibrated emissive mode disabled")
    target_support_preserved = _profile_preserves_target_layer_response(material_profile)
    if "normal" not in texture_set.slots and not target_support_preserved:
        reasons.append("missing source normal map uses neutral normal fallback")
    if "detail_mask" not in texture_set.slots and not target_support_preserved:
        reasons.append("missing CD detail mask uses neutral fallback")
    if "height" not in texture_set.slots and not target_support_preserved:
        reasons.append("missing source height/displacement uses neutral height fallback")
    pbr_slot = texture_set.slots.get("material") or texture_set.slots.get("roughness")
    has_explicit_pbr = _source_slot_is_explicit_pbr(pbr_slot)
    if not has_explicit_pbr:
        if texture_set.roughness_factor is None and "roughness" not in texture_set.slots and "glossiness" not in texture_set.slots:
            reasons.append("missing source roughness map uses factor/profile fallback")
        if (
            texture_set.metallic_factor is None
            and "metallic" not in texture_set.slots
            and "metalness" not in texture_set.slots
            and "specular" not in texture_set.slots
        ):
            reasons.append("missing source metallic/specular map uses factor/profile fallback")
    if "ao" not in texture_set.slots and "occlusion" not in texture_set.slots and not (
        has_explicit_pbr
        and any(_sanitize_texture_component(channel) in {"ao", "occlusion", "ambientocclusion"} for channel in tuple(getattr(pbr_slot, "packed_channels", ()) or ()))
    ):
        reasons.append("missing source AO uses profile default")
    return tuple(reasons)


def _source_slot_is_real_texture(source_slot: ReplacementTextureSlot) -> bool:
    authority = str(getattr(source_slot, "source_authority", "") or "").strip().lower()
    return authority != "synthetic"


def _source_slot_is_synthetic_factor_authority(source_slot: ReplacementTextureSlot) -> bool:
    authority = str(getattr(source_slot, "source_authority", "") or "").strip().lower()
    if authority != "synthetic":
        return False
    slot_kind = str(getattr(source_slot, "slot_kind", "") or "").strip().lower()
    if slot_kind not in {"base", "emissive"}:
        return False
    if tuple(getattr(source_slot, "base_color_factor", ()) or ()):
        return True
    if _source_slot_needs_base_alpha_factor(source_slot):
        return True
    source_name = str(getattr(source_slot, "source_path", "") or "").replace("\\", "/").lower()
    return "_base_" in source_name or "_emissive_" in source_name


def _texture_set_has_real_source_texture(texture_set: ReplacementTextureSet) -> bool:
    return any(
        _source_slot_is_real_texture(slot)
        for slot in (getattr(texture_set, "slots", {}) or {}).values()
    )


def _texture_set_has_source_authority_data(texture_set: ReplacementTextureSet) -> bool:
    return any(
        _source_slot_is_real_texture(slot) or _source_slot_is_synthetic_factor_authority(slot)
        for slot in (getattr(texture_set, "slots", {}) or {}).values()
    )


def _texture_set_has_explicit_source_pbr(texture_set: ReplacementTextureSet) -> bool:
    slots = getattr(texture_set, "slots", {}) or {}
    material_slot = slots.get("material") or slots.get("roughness")
    if material_slot is not None and _source_slot_is_real_texture(material_slot) and _source_slot_is_explicit_pbr(material_slot):
        return True
    for slot_kind in ("roughness", "glossiness", "metallic", "metalness", "specular", "ao", "occlusion"):
        slot = slots.get(slot_kind)
        if slot is None:
            continue
        if _source_slot_is_real_texture(slot) and str(getattr(slot, "source_authority", "") or "").strip().lower() != "filename":
            return True
    return False


def _complete_swap_neutral_support_slot(
    texture_set: ReplacementTextureSet,
    slot_kind: str,
    *,
    material_profile: Optional[CDMaterialRuntimeProfile] = None,
) -> ReplacementTextureSlot:
    material_name = str(texture_set.material_name or "material").strip() or "material"
    profile = material_profile or get_complete_swap_material_profile()
    normalized_slot = str(slot_kind or "").strip().lower()
    edge_strength = normalize_basic_control_percent(getattr(profile, "edge_relief_strength", 0.0))
    edge_mode = normalize_edge_relief_source(getattr(profile, "edge_relief_source", "hybrid"))
    if edge_strength > 0.0 and edge_mode in {"generate_source", "hybrid"} and normalized_slot in {"height", "detail_mask"}:
        source_path = _complete_swap_edge_relief_support_png_path(texture_set, normalized_slot, profile)
    else:
        source_path = _complete_swap_neutral_support_png_path(
            material_name,
            normalized_slot,
            material_profile=profile,
        )
    return ReplacementTextureSlot(
        material_name=material_name,
        slot_kind=normalized_slot,
        source_path=source_path,
        normal_space="directx" if normalized_slot == "normal" else "",
        source_authority="synthetic",
    )


def _complete_swap_runtime_material_mask_slot(
    texture_set: ReplacementTextureSet,
    material_profile: CDMaterialRuntimeProfile,
) -> ReplacementTextureSlot:
    material_name = str(texture_set.material_name or "material").strip() or "material"
    source_path = _complete_swap_runtime_material_mask_png_path(texture_set, material_profile)
    return ReplacementTextureSlot(
        material_name=material_name,
        slot_kind="material_mask",
        source_path=source_path,
        normal_space="",
        source_authority="synthetic",
    )


def _complete_swap_factor_only_material_mask_slot(
    texture_set: ReplacementTextureSet,
    material_profile: CDMaterialRuntimeProfile,
) -> ReplacementTextureSlot:
    if _profile_mask_binding_mode(material_profile) == "detail_mask_material":
        detail_slot = _complete_swap_neutral_support_slot(
            texture_set,
            "detail_mask",
            material_profile=material_profile,
        )
        return replace(detail_slot, slot_kind="material_mask", source_authority="synthetic")
    return _complete_swap_neutral_support_slot(texture_set, "material_mask", material_profile=material_profile)


def _is_complete_swap_runtime_material_mask_path(source_slot: ReplacementTextureSlot) -> bool:
    return (
        str(source_slot.slot_kind or "").strip().lower() == "material_mask"
        and "_material_mask_" in source_slot.source_path.name.lower()
        and "cdmw_synthetic_materials" in str(source_slot.source_path.parent).lower()
    )



def _material_mask_rgba_from_roles(
    material_profile: CDMaterialRuntimeProfile,
    role_images: Mapping[str, object],
    size: tuple[int, int],
):
    from PIL import Image

    channels = []
    defaults = {
        "ao": int(material_profile.ao_default),
        "roughness": int(material_profile.roughness_default),
        "metallic": int(material_profile.metallic_default),
    }
    for role in _profile_ma_rgb_roles(material_profile):
        image = role_images.get(role)
        if image is None:
            image = Image.new("L", size, max(0, min(255, int(defaults.get(role, 0)))))
        channels.append(image)
    channels.append(Image.new("L", size, max(0, min(255, int(material_profile.alpha_default)))))
    return tuple(channels)


def _source_slot_is_explicit_pbr(source_slot: Optional[ReplacementTextureSlot]) -> bool:
    if source_slot is None:
        return False
    subtype = _sanitize_texture_component(str(getattr(source_slot, "semantic_subtype", "") or ""))
    channels = tuple(_sanitize_texture_component(channel) for channel in tuple(getattr(source_slot, "packed_channels", ()) or ()))
    authority = str(getattr(source_slot, "source_authority", "") or "").strip().lower()
    if subtype in {"metallic_roughness", "metallicroughness", "orm", "arm", "rma", "mra"}:
        return authority != "filename"
    if {"roughness", "metallic"} <= set(channels):
        return authority != "filename"
    if subtype in {"specular_glossiness", "specularglossiness", "specular_gloss", "specgloss"}:
        return authority != "filename"
    if {"specular", "glossiness"} <= set(channels):
        return authority != "filename"
    return False


def _source_slot_is_specular_glossiness(source_slot: Optional[ReplacementTextureSlot]) -> bool:
    if source_slot is None:
        return False
    subtype = _sanitize_texture_component(str(getattr(source_slot, "semantic_subtype", "") or ""))
    channels = {_sanitize_texture_component(channel) for channel in tuple(getattr(source_slot, "packed_channels", ()) or ())}
    return subtype in {"specular_glossiness", "specularglossiness", "specular_gloss", "specgloss"} or {
        "specular",
        "glossiness",
    } <= channels


def _source_slot_is_real_diffuse_base(source_slot: Optional[ReplacementTextureSlot]) -> bool:
    if source_slot is None:
        return False
    if str(getattr(source_slot, "slot_kind", "") or "").strip().lower() != "base":
        return False
    if not _source_slot_is_real_texture(source_slot):
        return False
    subtype = _sanitize_texture_component(str(getattr(source_slot, "semantic_subtype", "") or ""))
    if subtype in {"albedo", "basecolor", "base_color", "diffuse", "color"}:
        return True
    source_name = re.sub(r"[^a-z0-9]+", "", str(getattr(source_slot, "source_path", "") or "").lower())
    return any(token in source_name for token in ("diffuse", "basecolor", "albedo"))


def _source_slot_channel_index(source_slot: ReplacementTextureSlot, role: str, default_index: int) -> int:
    wanted = _sanitize_texture_component(role)
    subtype = _sanitize_texture_component(str(getattr(source_slot, "semantic_subtype", "") or ""))
    raw_channels = tuple(str(channel or "").strip().lower() for channel in tuple(getattr(source_slot, "packed_channels", ()) or ()))
    parsed: dict[str, int] = {}
    channel_letters = {"r": 0, "g": 1, "b": 2, "a": 3}
    for index, raw in enumerate(raw_channels):
        normalized = _sanitize_texture_component(raw)
        if not normalized:
            continue
        if "=" in raw:
            left, right = (part.strip().lower() for part in raw.split("=", 1))
            left = left[:1]
            if left in channel_letters:
                parsed[_sanitize_texture_component(right)] = channel_letters[left]
                continue
        if ":" in raw:
            left, right = (part.strip().lower() for part in raw.split(":", 1))
            left = left[:1]
            if left in channel_letters:
                parsed[_sanitize_texture_component(right)] = channel_letters[left]
                continue
        if normalized in {"ao", "occlusion", "ambientocclusion"}:
            parsed["ao"] = index
        elif normalized in {"roughness", "rough"}:
            parsed["roughness"] = index
        elif normalized in {"metallic", "metalness", "metal"}:
            parsed["metallic"] = index
        elif normalized in {"specular", "spec"}:
            parsed["specular"] = index
        elif normalized in {"glossiness", "gloss", "smoothness"}:
            parsed["glossiness"] = index
    compact_channels = tuple(_sanitize_texture_component(channel) for channel in raw_channels)
    if subtype in {"metallic_roughness", "metallicroughness"} and compact_channels == ("roughness", "metallic"):
        parsed["roughness"] = 1
        parsed["metallic"] = 2
    if subtype in {"specular_glossiness", "specularglossiness", "specular_gloss", "specgloss"}:
        parsed.setdefault("specular", 0)
        parsed["glossiness"] = 3
    if compact_channels[:3] in {
        ("ao", "roughness", "metallic"),
        ("occlusion", "roughness", "metallic"),
        ("ambientocclusion", "roughness", "metallic"),
    }:
        parsed.setdefault("ao", 0)
        parsed.setdefault("roughness", 1)
        parsed.setdefault("metallic", 2)
    if compact_channels[:3] == ("roughness", "metallic", "ao"):
        parsed.setdefault("roughness", 0)
        parsed.setdefault("metallic", 1)
        parsed.setdefault("ao", 2)
    if compact_channels[:3] == ("metallic", "roughness", "ao"):
        parsed.setdefault("metallic", 0)
        parsed.setdefault("roughness", 1)
        parsed.setdefault("ao", 2)
    return max(0, min(3, int(parsed.get(wanted, default_index))))


def _complete_swap_runtime_material_mask_png_path(
    texture_set: ReplacementTextureSet,
    material_profile: CDMaterialRuntimeProfile,
) -> Path:
    from PIL import Image
    parameter_values = evaluate_material_parameters(material_profile)
    material_name = str(texture_set.material_name or "material").strip() or "material"
    pbr_slot = texture_set.slots.get("material") or texture_set.slots.get("roughness")
    if pbr_slot is not None and not _source_slot_is_explicit_pbr(pbr_slot):
        pbr_slot = None
    pbr_is_specular_glossiness = _source_slot_is_specular_glossiness(pbr_slot)
    roughness_slot = texture_set.slots.get("roughness")
    if roughness_slot is pbr_slot:
        roughness_slot = None
    glossiness_slot = texture_set.slots.get("glossiness")
    metallic_slot = texture_set.slots.get("metallic") or texture_set.slots.get("metalness")
    specular_slot = texture_set.slots.get("specular")
    ao_slot = texture_set.slots.get("ao") or texture_set.slots.get("occlusion")
    factor_roughness = _factor_byte(getattr(texture_set, "roughness_factor", None), material_profile.roughness_default)
    factor_metallic = _factor_byte(getattr(texture_set, "metallic_factor", None), material_profile.metallic_default)
    roughness_scalar = _optional_factor(getattr(texture_set, "roughness_factor", None))
    metallic_scalar = _optional_factor(getattr(texture_set, "metallic_factor", None))
    specular_scalar = _optional_factor(getattr(texture_set, "specular_factor", None))
    glossiness_scalar = _optional_factor(getattr(texture_set, "glossiness_factor", None))
    occlusion_strength = _optional_factor(getattr(texture_set, "occlusion_strength", None))
    source_key_parts = [
        material_name,
        material_profile.name,
        str(material_profile.ma_layout),
        str(material_profile.ao_mode),
        str(material_profile.ao_default),
        str(material_profile.roughness_default),
        str(material_profile.metallic_default),
        str(int(parameter_values.roughness_inverted)),
        str(int(parameter_values.metalness_inverted)),
        str(int(parameter_values.force_nonmetal)),
        str(factor_roughness),
        str(factor_metallic),
        str(roughness_scalar),
        str(metallic_scalar),
        str(specular_scalar),
        str(glossiness_scalar),
        str(occlusion_strength),
        str(parameter_values.roughness_min),
        str(parameter_values.roughness_scale),
        str(parameter_values.roughness_max),
        str(parameter_values.metallic_min),
        str(parameter_values.metallic_scale),
        str(parameter_values.metallic_max),
        str(parameter_values.gloss_reduction_mode),
        str(parameter_values.global_gloss_reduction),
    ]
    for slot in (pbr_slot, roughness_slot, glossiness_slot, metallic_slot, specular_slot, ao_slot):
        if slot is not None:
            source_key_parts.append(str(slot.source_path))
            source_key_parts.append(str(getattr(slot, "semantic_subtype", "") or ""))
            source_key_parts.append(",".join(tuple(getattr(slot, "packed_channels", ()) or ())))
            source_key_parts.append(str(getattr(slot, "source_authority", "") or ""))
            try:
                source_key_parts.append(str(slot.source_path.stat().st_mtime_ns))
                source_key_parts.append(str(slot.source_path.stat().st_size))
            except OSError:
                pass
    digest = hashlib.sha1("|".join(source_key_parts).encode("utf-8", errors="ignore")).hexdigest()[:12]
    safe_material = _sanitize_texture_component(material_name) or "material"
    safe_profile = _sanitize_texture_component(material_profile.name) or "profile"
    root = Path(tempfile.gettempdir()) / "cdmw_synthetic_materials"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{safe_material}_material_mask_{safe_profile}_{digest}.png"
    if path.is_file():
        return path

    size = _first_readable_image_size(
        tuple(
            slot.source_path
            for slot in (pbr_slot, roughness_slot, glossiness_slot, metallic_slot, specular_slot, ao_slot)
            if slot is not None
        )
    )
    if size is None:
        size = (16, 16)
    pbr_ao_path = (
        pbr_slot.source_path
        if pbr_slot is not None
        and {
            _sanitize_texture_component(channel)
            for channel in tuple(getattr(pbr_slot, "packed_channels", ()) or ())
        }.intersection({"ao", "occlusion", "ambientocclusion"})
        else None
    )
    ao_channel_index = _source_slot_channel_index(pbr_slot, "ao", 0) if pbr_slot is not None else 0
    ao = _load_grayscale_channel(
        pbr_ao_path if pbr_ao_path is not None else (ao_slot.source_path if ao_slot is not None else None),
        size,
        channel_index=ao_channel_index if pbr_ao_path is not None else 0,
        default_value=material_profile.ao_default,
    )
    if str(material_profile.ao_mode or "").strip().lower() == "white":
        ao = Image.new("L", size, 255)
    elif occlusion_strength is not None:
        ao = _apply_occlusion_strength(ao, occlusion_strength)
    if pbr_is_specular_glossiness and pbr_slot is not None:
        glossiness = _load_grayscale_channel(
            pbr_slot.source_path,
            size,
            channel_index=_source_slot_channel_index(pbr_slot, "glossiness", 3),
            default_value=255 - factor_roughness,
        )
        if glossiness_scalar is not None:
            glossiness = _multiply_grayscale_channel(glossiness, glossiness_scalar)
        roughness = Image.eval(glossiness, lambda value: 255 - int(value))
        metallic = _load_rgb_luminance_channel(pbr_slot.source_path, size, default_value=factor_metallic)
        if specular_scalar is not None:
            metallic = _multiply_grayscale_channel(metallic, specular_scalar)
    elif glossiness_slot is not None and roughness_slot is None:
        glossiness = _load_grayscale_channel(
            glossiness_slot.source_path,
            size,
            channel_index=0,
            default_value=255 - factor_roughness,
        )
        if glossiness_scalar is not None:
            glossiness = _multiply_grayscale_channel(glossiness, glossiness_scalar)
        roughness = Image.eval(glossiness, lambda value: 255 - int(value))
        metallic = _load_rgb_luminance_channel(specular_slot.source_path, size, default_value=factor_metallic) if specular_slot is not None else Image.new("L", size, factor_metallic)
        if specular_slot is not None and specular_scalar is not None:
            metallic = _multiply_grayscale_channel(metallic, specular_scalar)
    else:
        roughness = _load_grayscale_channel(
            pbr_slot.source_path if pbr_slot is not None else (roughness_slot.source_path if roughness_slot is not None else None),
            size,
            channel_index=_source_slot_channel_index(pbr_slot, "roughness", 1) if pbr_slot is not None else 0,
            default_value=factor_roughness,
        )
        if (pbr_slot is not None or roughness_slot is not None) and roughness_scalar is not None:
            roughness = _multiply_grayscale_channel(roughness, roughness_scalar)
        metallic = _load_grayscale_channel(
            pbr_slot.source_path if pbr_slot is not None else (metallic_slot.source_path if metallic_slot is not None else None),
            size,
            channel_index=_source_slot_channel_index(pbr_slot, "metallic", 2) if pbr_slot is not None else 0,
            default_value=factor_metallic,
        )
        if (pbr_slot is not None or metallic_slot is not None) and metallic_scalar is not None:
            metallic = _multiply_grayscale_channel(metallic, metallic_scalar)
        if metallic_slot is None and specular_slot is not None and pbr_slot is None:
            metallic = _load_rgb_luminance_channel(specular_slot.source_path, size, default_value=factor_metallic)
            if specular_scalar is not None:
                metallic = _multiply_grayscale_channel(metallic, specular_scalar)
    if parameter_values.roughness_inverted:
        roughness = Image.eval(roughness, lambda value: 255 - int(value))
    roughness = _apply_profile_channel_adjustments(
        roughness,
        scale=parameter_values.roughness_scale,
        minimum=parameter_values.roughness_min,
        maximum=parameter_values.roughness_max,
    )
    if parameter_values.force_nonmetal:
        metallic = Image.new("L", size, 0)
    else:
        metallic = Image.eval(metallic, lambda value: 255 - int(value)) if parameter_values.metalness_inverted else metallic
        metallic = _apply_profile_channel_adjustments(
            metallic,
            scale=parameter_values.metallic_scale,
            minimum=parameter_values.metallic_min,
            maximum=parameter_values.metallic_max,
        )
    gloss_reduction = parameter_values.global_gloss_reduction
    if gloss_reduction != 0.0 and _profile_uses_cd_smoothness_mask_response(material_profile):
        strength = abs(gloss_reduction) / 100.0
        gloss_mode = parameter_values.gloss_reduction_mode
        if gloss_reduction < 0.0:
            if gloss_mode == "source_roughness_high":
                roughness = _blend_grayscale_channel_toward(roughness, 24, strength)
            elif gloss_mode == "cd_smoothness_low_preserve_metal":
                roughness = _blend_grayscale_channel_toward(roughness, 255, strength)
            else:
                roughness = _blend_grayscale_channel_toward(roughness, 255, strength)
        else:
            if gloss_mode == "source_roughness_high":
                roughness = _blend_grayscale_channel_toward(roughness, 255, strength)
            elif gloss_mode == "cd_smoothness_low_preserve_metal":
                roughness = _blend_grayscale_channel_toward(roughness, 32, strength)
            else:
                roughness = _blend_grayscale_channel_toward(roughness, 32, strength)
                metallic = _blend_grayscale_channel_toward(metallic, 0, strength)
    if _profile_uses_detail_mask_material_contract(material_profile):
        roughness = _apply_profile_channel_adjustments(
            roughness,
            minimum=parameter_values.roughness_min,
            maximum=parameter_values.roughness_max,
        )
    Image.merge(
        "RGBA",
        _material_mask_rgba_from_roles(
            material_profile,
            {"ao": ao, "roughness": roughness, "metallic": metallic},
            size,
        ),
    ).save(path)
    return path


def _blend_grayscale_channel_toward(image: object, target_value: int, strength: float):
    from PIL import Image

    target = max(0, min(255, int(target_value)))
    amount = max(0.0, min(1.0, float(strength)))
    return Image.eval(image, lambda value: max(0, min(255, int(round(int(value) + (target - int(value)) * amount)))))


def _apply_profile_channel_adjustments(
    image: object,
    *,
    scale: Optional[float] = None,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
):
    from PIL import Image

    adjusted = image
    if scale is not None and abs(float(scale) - 1.0) > 0.0001:
        adjusted = Image.eval(adjusted, lambda value: max(0, min(255, int(round(int(value) * float(scale))))))
    if minimum is not None:
        floor = max(0, min(255, int(minimum)))
        adjusted = Image.eval(adjusted, lambda value: max(floor, int(value)))
    if maximum is not None:
        ceiling = max(0, min(255, int(maximum)))
        adjusted = Image.eval(adjusted, lambda value: min(ceiling, int(value)))
    return adjusted


def _optional_factor(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError, OverflowError):
        return None


def _multiply_grayscale_channel(image: object, factor: float):
    from PIL import Image

    scalar = max(0.0, min(1.0, float(factor)))
    return Image.eval(image, lambda value: max(0, min(255, int(round(int(value) * scalar)))))


def _apply_occlusion_strength(image: object, strength: float):
    from PIL import Image

    scalar = max(0.0, min(1.0, float(strength)))
    return Image.eval(image, lambda value: max(0, min(255, int(round(255 - ((255 - int(value)) * scalar))))))


def _factor_byte(value: Optional[float], fallback: int) -> int:
    if value is None:
        return max(0, min(255, int(fallback)))
    try:
        return max(0, min(255, int(round(float(value) * 255.0))))
    except (TypeError, ValueError, OverflowError):
        return max(0, min(255, int(fallback)))


def _first_readable_image_size(paths: Sequence[Path]) -> Optional[tuple[int, int]]:
    try:
        from PIL import Image

        for path in tuple(paths or ()):
            try:
                with Image.open(path) as image:
                    width = max(1, min(4096, int(image.width)))
                    height = max(1, min(4096, int(image.height)))
                    return width, height
            except Exception:
                continue
    except Exception:
        return None
    return None


def _load_grayscale_channel(
    path: Optional[Path],
    size: tuple[int, int],
    *,
    channel_index: int,
    default_value: int,
):
    from PIL import Image

    value = max(0, min(255, int(default_value)))
    if path is None:
        return Image.new("L", size, value)
    try:
        with Image.open(path) as image:
            rgba = image.convert("RGBA")
            if rgba.size != size:
                resampling = getattr(Image, "Resampling", Image).LANCZOS
                rgba = rgba.resize(size, resampling)
            channels = rgba.split()
            index = max(0, min(len(channels) - 1, int(channel_index)))
            return channels[index]
    except Exception:
        return Image.new("L", size, value)


def _load_rgb_luminance_channel(
    path: Optional[Path],
    size: tuple[int, int],
    *,
    default_value: int,
):
    from PIL import Image

    value = max(0, min(255, int(default_value)))
    if path is None:
        return Image.new("L", size, value)
    try:
        with Image.open(path) as image:
            rgba = image.convert("RGBA")
            if rgba.size != size:
                resampling = getattr(Image, "Resampling", Image).LANCZOS
                rgba = rgba.resize(size, resampling)
            return rgba.convert("L")
    except Exception:
        return Image.new("L", size, value)


def _complete_swap_neutral_support_png_path(
    material_name: str,
    slot_kind: str,
    *,
    material_profile: Optional[CDMaterialRuntimeProfile] = None,
) -> Path:
    normalized_slot = str(slot_kind or "").strip().lower()
    profile = material_profile or get_complete_swap_material_profile()
    colors = {
        "normal": (128, 128, 255, 255),
        "height": (128, 128, 128, 255),
        # Complete-swap fallback masks should be inert for CD's runtime shader:
        # full AO, moderate roughness, no metalness/spec response, and no detail layer.
        "material_mask": (
            *tuple(
                {
                    "ao": int(profile.ao_default),
                    "roughness": int(profile.roughness_default),
                    "metallic": int(profile.metallic_default),
                }.get(role, 0)
                for role in _profile_ma_rgb_roles(profile)
            ),
            int(profile.alpha_default),
        ),
        "detail_mask": (0, 0, 0, 0),
    }
    color = colors.get(normalized_slot, (128, 128, 128, 255))
    digest = hashlib.sha1(f"{material_name}|complete_support|{normalized_slot}|{color}".encode("utf-8", errors="ignore")).hexdigest()[:12]
    safe_material = _sanitize_texture_component(material_name) or "material"
    safe_slot = _sanitize_texture_component(normalized_slot) or "support"
    root = Path(tempfile.gettempdir()) / "cdmw_synthetic_materials"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{safe_material}_{safe_slot}_neutral_{digest}.png"
    if not path.is_file():
        from PIL import Image

        Image.new("RGBA", (16, 16), color).save(path)
    return path


def _complete_swap_edge_relief_support_png_path(
    texture_set: ReplacementTextureSet,
    slot_kind: str,
    material_profile: CDMaterialRuntimeProfile,
) -> Path:
    normalized_slot = str(slot_kind or "").strip().lower()
    material_name = str(texture_set.material_name or "material").strip() or "material"
    strength = normalize_basic_control_percent(getattr(material_profile, "edge_relief_strength", 0.0)) / 100.0
    source_slot = (
        texture_set.slots.get("normal")
        or texture_set.slots.get("base")
        or texture_set.slots.get("material")
        or texture_set.slots.get("roughness")
    )
    source_path = source_slot.source_path if source_slot is not None else Path()
    source_key = [material_name, normalized_slot, f"{strength:.6f}", str(source_path)]
    try:
        stat = source_path.stat()
        source_key.extend((str(stat.st_mtime_ns), str(stat.st_size)))
    except OSError:
        pass
    digest = hashlib.sha1("|".join(source_key).encode("utf-8", errors="ignore")).hexdigest()[:12]
    safe_material = _sanitize_texture_component(material_name) or "material"
    root = Path(tempfile.gettempdir()) / "cdmw_synthetic_materials"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{safe_material}_{normalized_slot}_edge_relief_{digest}.png"
    if path.is_file():
        return path
    from PIL import Image, ImageChops, ImageFilter

    size = _first_readable_image_size((source_path,)) or (16, 16)
    if source_path.is_file():
        try:
            with Image.open(source_path) as image:
                rgba = image.convert("RGBA")
                if rgba.size != size:
                    resampling = getattr(Image, "Resampling", Image).LANCZOS
                    rgba = rgba.resize(size, resampling)
                luma = rgba.convert("L")
        except Exception:
            luma = Image.new("L", size, 128)
    else:
        luma = Image.new("L", size, 128)
    edges = luma.filter(ImageFilter.FIND_EDGES)
    edge_boost = edges.point(lambda value: max(0, min(255, int(round(int(value) * strength)))))
    if normalized_slot == "detail_mask":
        alpha = edge_boost.point(lambda value: max(0, min(255, int(round(int(value) * 0.75)))))
        Image.merge("RGBA", (edge_boost, edge_boost, edge_boost, alpha)).save(path)
        return path
    base = Image.new("L", size, 128)
    raised = ImageChops.add(base, edge_boost.point(lambda value: int(round(int(value) * 0.35))))
    Image.merge("RGBA", (raised, raised, raised, Image.new("L", size, 255))).save(path)
    return path


def _source_driven_parameter_name(
    slot_kind: str,
    *,
    material_profile: Optional[CDMaterialRuntimeProfile] = None,
) -> str:
    normalized = str(slot_kind or "").strip().lower()
    profile = material_profile or get_complete_swap_material_profile()
    if normalized == "base":
        base_mode = _profile_base_binding_mode(profile)
        if base_mode == "disabled" or base_mode == "tint_only":
            return ""
        if base_mode == "overlay_from_colorblend_slot":
            return "_colorBlendingMaskTexture"
    if normalized == "material_mask":
        mask_mode = _profile_mask_binding_mode(profile)
        if mask_mode in {"disabled", "scratch_scalars"}:
            return ""
        if mask_mode == "detail_mask_material":
            return "_detailMaskTexture"
    return {
        "base": "_overlayColorTexture",
        "normal": "_normalTexture",
        "height": "_heightTexture",
        "material_mask": "_colorBlendingMaskTexture",
        "detail_mask": "_detailMaskTexture",
        "emissive": "_emissiveIntensityTexture",
    }.get(normalized, "")


def _byte4_uniform_rgb(value: int) -> int:
    byte_value = max(0, min(255, int(value)))
    return byte_value | (byte_value << 8) | (byte_value << 16)


def _profile_scalar_byte4(value: Optional[float]) -> Optional[int]:
    if value is None:
        return None
    return _byte4_uniform_rgb(_factor_byte(value, 0))


def _profile_scalar_values(
    material_profile: CDMaterialRuntimeProfile,
    source_values: Optional[tuple[int, int, str]] = None,
) -> tuple[Optional[int], Optional[int], Optional[float], str]:
    roughness_value = _profile_scalar_byte4(getattr(material_profile, "scratch_roughness", None))
    metallic_value = _profile_scalar_byte4(getattr(material_profile, "scratch_metallic", None))
    source_name = ""
    if source_values is not None:
        if roughness_value is None:
            roughness_value = source_values[0]
        if metallic_value is None:
            metallic_value = source_values[1]
        source_name = str(source_values[2] or "")
    shine_value = getattr(material_profile, "shine_scalar", None)
    return roughness_value, metallic_value, shine_value, source_name


def _mean_image_channel(path: Path, channel_index: int) -> Optional[float]:
    try:
        from PIL import Image, ImageStat

        with Image.open(path) as image:
            rgba = image.convert("RGBA")
            if max(rgba.size) > 512:
                rgba.thumbnail((512, 512))
            stat = ImageStat.Stat(rgba)
            means = tuple(float(value) for value in stat.mean)
            if channel_index < 0 or channel_index >= len(means):
                return None
            return max(0.0, min(255.0, means[channel_index]))
    except Exception:
        return None


def _mean_image_rgb_luminance(path: Path) -> Optional[float]:
    try:
        from PIL import Image, ImageStat

        with Image.open(path) as image:
            rgba = image.convert("RGBA")
            if max(rgba.size) > 512:
                rgba.thumbnail((512, 512))
            stat = ImageStat.Stat(rgba.convert("L"))
            if not stat.mean:
                return None
            return max(0.0, min(255.0, float(stat.mean[0])))
    except Exception:
        return None


def _looks_like_gltf_metallic_roughness(path: Path) -> bool:
    normalized_name = re.sub(r"[^a-z0-9]+", "", path.name.lower())
    return any(
        token in normalized_name
        for token in ("metallicroughness", "metalrough", "metallicrough", "roughnessmetallic", "roughmetal")
    )


def _source_pbr_scalar_values(texture_set: ReplacementTextureSet) -> Optional[tuple[int, int, str]]:
    roughness_scalar = _optional_factor(getattr(texture_set, "roughness_factor", None))
    metallic_scalar = _optional_factor(getattr(texture_set, "metallic_factor", None))
    specular_scalar = _optional_factor(getattr(texture_set, "specular_factor", None))
    glossiness_scalar = _optional_factor(getattr(texture_set, "glossiness_factor", None))
    material_slot = texture_set.slots.get("material") or texture_set.slots.get("roughness")
    if material_slot is not None and _source_slot_is_explicit_pbr(material_slot):
        if _source_slot_is_specular_glossiness(material_slot):
            glossiness = _mean_image_channel(material_slot.source_path, _source_slot_channel_index(material_slot, "glossiness", 3))
            if glossiness is not None and glossiness_scalar is not None:
                glossiness *= glossiness_scalar
            roughness = 255.0 - glossiness if glossiness is not None else None
            metalness = _mean_image_rgb_luminance(material_slot.source_path)
            if metalness is not None and specular_scalar is not None:
                metalness *= specular_scalar
        else:
            roughness = _mean_image_channel(material_slot.source_path, _source_slot_channel_index(material_slot, "roughness", 1))
            metalness = _mean_image_channel(material_slot.source_path, _source_slot_channel_index(material_slot, "metallic", 2))
            if roughness is not None and roughness_scalar is not None:
                roughness *= roughness_scalar
            if metalness is not None and metallic_scalar is not None:
                metalness *= metallic_scalar
        if roughness is not None or metalness is not None:
            rough_byte = int(round(roughness if roughness is not None else 127.0))
            metal_byte = int(round(metalness if metalness is not None else 0.0))
            return (
                _byte4_uniform_rgb(rough_byte),
                _byte4_uniform_rgb(metal_byte),
                material_slot.source_path.name,
            )
    roughness_slot = texture_set.slots.get("roughness")
    glossiness_slot = texture_set.slots.get("glossiness")
    metallic_slot = texture_set.slots.get("metallic") or texture_set.slots.get("metalness")
    specular_slot = texture_set.slots.get("specular")
    if roughness_slot is None and glossiness_slot is None and metallic_slot is None and specular_slot is None:
        return None
    if roughness_slot is not None:
        roughness = _mean_image_channel(roughness_slot.source_path, 0)
        if roughness is not None and roughness_scalar is not None:
            roughness *= roughness_scalar
    elif glossiness_slot is not None:
        glossiness = _mean_image_channel(glossiness_slot.source_path, 0)
        if glossiness is not None and glossiness_scalar is not None:
            glossiness *= glossiness_scalar
        roughness = 255.0 - glossiness if glossiness is not None else None
    else:
        roughness = None
    if metallic_slot is not None:
        metalness = _mean_image_channel(metallic_slot.source_path, 0)
        if metalness is not None and metallic_scalar is not None:
            metalness *= metallic_scalar
    elif specular_slot is not None:
        metalness = _mean_image_rgb_luminance(specular_slot.source_path)
        if metalness is not None and specular_scalar is not None:
            metalness *= specular_scalar
    else:
        metalness = None
    if roughness is None and metalness is None:
        return None
    source_name = (
        roughness_slot.source_path.name
        if roughness_slot is not None
        else glossiness_slot.source_path.name
        if glossiness_slot is not None
        else metallic_slot.source_path.name
        if metallic_slot is not None
        else specular_slot.source_path.name
        if specular_slot is not None
        else "source PBR"
    )
    return (
        _byte4_uniform_rgb(int(round(roughness if roughness is not None else 127.0))),
        _byte4_uniform_rgb(int(round(metalness if metalness is not None else 0.0))),
        source_name,
    )


_ACCENT_GLOW_TOKENS = {
    "accent",
    "core",
    "crystal",
    "emissive",
    "energy",
    "eye",
    "fire",
    "flame",
    "gem",
    "glass",
    "glow",
    "jewel",
    "lava",
    "lens",
    "light",
    "magic",
    "orb",
    "rune",
}

_ACCENT_GLOW_FACTOR_SHELL_TOKENS = {
    "inside",
    "inner",
    "outside",
    "outer",
    "shell",
}


def _normalized_source_part_material_role(raw_role: object) -> str:
    value = str(raw_role or "").strip().lower().replace("_", " ").replace("-", " ")
    if not value:
        return ""
    tokens = {token for token in re.split(r"[^a-z0-9]+", value) if token}
    if tokens & {"glow", "emissive", "emission", "accent"}:
        return "glow"
    if tokens & {"blade"}:
        return "blade"
    if tokens & {"handle", "grip"}:
        return "handle"
    if tokens & {"guard", "crossguard"}:
        return "guard"
    if tokens & {"cloth", "fabric"}:
        return "cloth"
    if tokens & {"wood", "oak", "pine", "bark", "timber", "plank"}:
        return "wood"
    if tokens & {"leather", "hide"}:
        return "leather"
    if tokens & {"stone", "rock", "granite", "marble", "slate"}:
        return "stone"
    if tokens & {"metal", "metallic", "metalness", "steel", "iron", "gold", "silver", "bronze", "copper"}:
        return "metal"
    if tokens & {"shiny", "glossy", "polished", "mirror", "clearcoat"}:
        return "shiny"
    if tokens & {"glass", "crystal", "lens", "gem", "jewel"}:
        return "glass"
    return value.replace(" ", "/")


def _solid_material_factor_png_path(
    material_name: str,
    slot_kind: str,
    rgb: Sequence[float],
) -> Path:
    components = tuple(max(0, min(255, int(round(float(component) * 255.0)))) for component in tuple(rgb[:3]))
    digest = hashlib.sha1(f"{material_name}|{slot_kind}|{components}".encode("utf-8", errors="ignore")).hexdigest()[:12]
    safe_material = _sanitize_texture_component(material_name) or "material"
    safe_slot = _sanitize_texture_component(slot_kind) or "slot"
    root = Path(tempfile.gettempdir()) / "cdmw_synthetic_materials"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{safe_material}_{safe_slot}_{digest}.png"
    if not path.is_file():
        from PIL import Image

        Image.new("RGBA", (16, 16), (components[0], components[1], components[2], 255)).save(path)
    return path


def _material_tokens(value: str) -> set[str]:
    stop_words = {
        "cd",
        "phm",
        "pc",
        "texture",
        "material",
        "mesh",
        "obj",
        "dds",
        "png",
        "source",
        "target",
        "donor",
        "original",
        "replacement",
    }
    tokens: set[str] = set()
    for raw_token in re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split():
        token = re.sub(r"\d+$", "", raw_token.strip())
        if len(token) > 1 and token not in stop_words and not token.isdigit():
            tokens.add(token)
    return tokens


def _best_source_material_for_target(target_material: str, target_to_source_material: Mapping[str, str]) -> str:
    target_key = str(target_material or "").strip().lower()
    if target_key in target_to_source_material:
        return target_to_source_material[target_key]
    best_value = ""
    best_score = 0.0
    target_tokens = _material_tokens(target_key)
    for target_name, source_material in target_to_source_material.items():
        source_tokens = _material_tokens(f"{target_name} {source_material}")
        overlap = target_tokens & source_tokens
        score = float(len(overlap) * 8)
        for token in overlap:
            score += min(6.0, len(token) * 0.75)
        if target_name and (target_name in target_key or target_key in target_name):
            score += min(20.0, len(target_name) * 0.5)
        target_name_tokens = _material_tokens(target_name)
        if "sword" in target_tokens and "blade" in target_name_tokens:
            score += 14.0
        if "blade" in target_tokens and "blade" in target_name_tokens:
            score += 14.0
        if "handle" in target_tokens and "handle" in target_name_tokens:
            score += 14.0
        if "guard" in target_tokens and "guard" in target_name_tokens:
            score += 14.0
        if "acc" in target_tokens and "acc" in target_name_tokens:
            score += 14.0
        if score > best_score:
            best_score = score
            best_value = source_material
    return best_value if best_score >= 11.5 else ""


def _reference_target_path(reference: object) -> str:
    return str(
        getattr(reference, "resolved_archive_path", "")
        or getattr(reference, "reference_name", "")
        or ""
    ).replace("\\", "/").strip()


def _normalized_accent_glow_rgb(value: object) -> tuple[float, float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    raw = tuple(value)
    if len(raw) < 3:
        return ()
    try:
        components = tuple(float(component) for component in raw[:3])
    except (TypeError, ValueError, OverflowError):
        return ()
    if any(component > 1.0 for component in components):
        components = tuple(component / 255.0 for component in components)
    return tuple(max(0.0, min(1.0, component)) for component in components[:3])


def _complete_swap_accent_emissive_slot(
    texture_set: ReplacementTextureSet,
    target_name: str,
    material_profile: CDMaterialRuntimeProfile,
) -> Optional[ReplacementTextureSlot]:
    if _profile_accent_glow_strength(material_profile) <= 0.0 and not _texture_set_has_explicit_glow_authority(texture_set):
        return None
    override_rgb = _normalized_accent_glow_rgb(getattr(texture_set, "accent_glow_color_rgb", ()))
    existing = texture_set.slots.get("emissive")
    if existing is not None:
        if override_rgb:
            return replace(existing, base_color_factor=override_rgb)
        return existing
    if not _texture_set_is_accent_glow_candidate(texture_set, target_name):
        return None
    base_slot = texture_set.slots.get("base")
    if base_slot is not None:
        if _source_slot_is_real_texture(base_slot):
            if not _texture_set_has_explicit_glow_authority(texture_set):
                return None
            color = override_rgb or tuple(texture_set.base_color_factor or ()) or (1.0, 1.0, 1.0)
            try:
                rgb = tuple(max(0.0, min(1.0, float(component))) for component in color[:3])
            except (TypeError, ValueError, OverflowError):
                rgb = (1.0, 1.0, 1.0)
            return ReplacementTextureSlot(
                material_name=texture_set.material_name,
                slot_kind="emissive",
                source_path=_solid_material_factor_png_path(
                    texture_set.material_name,
                    "explicit_part_emissive",
                    rgb if len(rgb) >= 3 else (1.0, 1.0, 1.0),
                ),
                source_authority="explicit_part_glow",
            )
        return replace(
            base_slot,
            slot_kind="emissive",
            source_authority=str(base_slot.source_authority or "synthetic_accent_glow"),
            base_color_scale=1.0,
            base_color_lift=0,
            base_color_gamma=1.0,
            base_color_saturation=1.0,
            base_color_value_max=255,
            base_color_shadow_lift=0,
            base_color_tone_contrast=0.0,
            base_color_factor=override_rgb or tuple(base_slot.base_color_factor or ()),
        )
    color = override_rgb or tuple(texture_set.base_color_factor or ())
    if not color and _texture_set_has_explicit_glow_authority(texture_set):
        color = (1.0, 1.0, 1.0)
    if len(color) >= 3:
        try:
            rgb = tuple(max(0.0, min(1.0, float(component))) for component in color[:3])
        except (TypeError, ValueError, OverflowError):
            rgb = ()
        if rgb:
            return ReplacementTextureSlot(
                material_name=texture_set.material_name,
                slot_kind="emissive",
                source_path=_solid_material_factor_png_path(texture_set.material_name, "accent_emissive", rgb),
                source_authority="synthetic_accent_glow",
            )
    return None


def _complete_swap_accent_glow_skip_reason(
    texture_set: ReplacementTextureSet,
    target_name: str,
    material_profile: CDMaterialRuntimeProfile,
) -> str:
    if _profile_accent_glow_strength(material_profile) <= 0.0:
        return ""
    if texture_set.slots.get("emissive") is not None:
        return ""
    if not _texture_set_is_accent_glow_candidate(texture_set, target_name):
        return ""
    base_slot = texture_set.slots.get("base")
    if base_slot is None:
        return ""
    if not _source_slot_is_real_texture(base_slot):
        return ""
    if _texture_set_has_explicit_glow_authority(texture_set):
        return ""
    material_name = str(getattr(texture_set, "material_name", "") or target_name or "material").strip() or "material"
    return (
        f"Accent glow skipped for {material_name}: no explicit emissive/glow source was found. "
        "A real base texture was not auto-bound as _emissiveIntensityTexture because that can "
        "wash out yellow/white detail in game lighting."
    )


def _specular_glossiness_runtime_base_slot(texture_set: ReplacementTextureSet) -> Optional[ReplacementTextureSlot]:
    """Use spec-gloss RGB as fallback base only when no real diffuse/base texture is present."""

    slots = getattr(texture_set, "slots", {}) or {}
    base_slot = slots.get("base")
    material_slot = slots.get("material")
    if base_slot is None or material_slot is None:
        return None
    if _source_slot_is_real_diffuse_base(base_slot):
        return None
    if not _source_slot_is_specular_glossiness(material_slot):
        return None
    specular_scalar = _optional_factor(getattr(texture_set, "specular_factor", None))
    if specular_scalar is not None and specular_scalar <= 0.003:
        return None
    if not _specular_glossiness_should_drive_runtime_base(base_slot, material_slot, specular_scalar):
        return None
    try:
        source_path = _specular_glossiness_runtime_base_png_path(
            texture_set,
            base_slot=base_slot,
            spec_gloss_slot=material_slot,
            specular_scalar=specular_scalar,
        )
    except Exception:
        return None
    return replace(
        base_slot,
        source_path=source_path,
        source_authority="gltf",
        base_color_factor=(),
        base_color_scale=1.0,
        base_color_lift=0,
        base_color_gamma=1.0,
        base_color_saturation=1.0,
        base_color_value_max=255,
        base_color_auto_balance=0,
        base_color_shadow_lift=0,
        base_color_tone_contrast=0.0,
    )


def _specular_glossiness_should_drive_runtime_base(
    base_slot: ReplacementTextureSlot,
    spec_gloss_slot: ReplacementTextureSlot,
    specular_scalar: Optional[float],
) -> bool:
    base_luma = _mean_image_rgb_luminance(base_slot.source_path)
    spec_luma = _mean_image_rgb_luminance(spec_gloss_slot.source_path)
    if base_luma is None or spec_luma is None:
        return False
    scalar = 1.0 if specular_scalar is None else max(0.0, min(1.0, float(specular_scalar)))
    spec_luma *= scalar
    if base_luma > 96.0:
        return False
    return spec_luma >= max(56.0, base_luma * 1.4 + 18.0)


def _specular_glossiness_runtime_base_png_path(
    texture_set: ReplacementTextureSet,
    *,
    base_slot: ReplacementTextureSlot,
    spec_gloss_slot: ReplacementTextureSlot,
    specular_scalar: Optional[float],
) -> Path:
    base_path = base_slot.source_path
    spec_path = spec_gloss_slot.source_path
    key_parts = [
        "spec_gloss_runtime_base_v1",
        str(getattr(texture_set, "material_name", "") or ""),
        str(base_path),
        str(spec_path),
        str(specular_scalar),
    ]
    for path in (base_path, spec_path):
        try:
            stat = path.stat()
            key_parts.extend((str(stat.st_mtime_ns), str(stat.st_size)))
        except OSError:
            pass
    digest = hashlib.sha1("|".join(key_parts).encode("utf-8", errors="ignore")).hexdigest()[:12]
    safe_material = _sanitize_texture_component(str(getattr(texture_set, "material_name", "") or "")) or "material"
    root = Path(tempfile.gettempdir()) / "cdmw_synthetic_materials"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{safe_material}_specgloss_runtime_base_{digest}.png"
    if path.is_file():
        return path

    from PIL import Image

    with Image.open(base_path) as base_image, Image.open(spec_path) as spec_image:
        base_rgba = base_image.convert("RGBA")
        spec_rgba = spec_image.convert("RGBA")
        if spec_rgba.size != base_rgba.size:
            resampling = getattr(Image, "Resampling", Image).LANCZOS
            spec_rgba = spec_rgba.resize(base_rgba.size, resampling)
        spec_r, spec_g, spec_b, _spec_a = spec_rgba.split()
        if specular_scalar is not None:
            scalar = max(0.0, min(1.0, float(specular_scalar)))
            spec_r = spec_r.point(lambda value: max(0, min(255, int(round(int(value) * scalar)))))
            spec_g = spec_g.point(lambda value: max(0, min(255, int(round(int(value) * scalar)))))
            spec_b = spec_b.point(lambda value: max(0, min(255, int(round(int(value) * scalar)))))
        _base_r, _base_g, _base_b, base_a = base_rgba.split()
        Image.merge("RGBA", (spec_r, spec_g, spec_b, base_a)).save(path)
    return path


def _texture_set_is_accent_glow_candidate(texture_set: ReplacementTextureSet, target_name: str) -> bool:
    role_tags = {
        _normalized_source_part_material_role(tag)
        for tag in tuple(getattr(texture_set, "source_role_tags", ()) or ())
    }
    if role_tags & {"glow"}:
        return True
    text_parts = [
        str(texture_set.material_name or ""),
        str(target_name or ""),
    ]
    for slot in tuple((texture_set.slots or {}).values()):
        text_parts.append(str(getattr(slot, "source_path", "") or ""))
        text_parts.append(str(getattr(slot, "semantic_subtype", "") or ""))
        text_parts.append(str(getattr(slot, "source_authority", "") or ""))
    tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", " ".join(text_parts).lower())
        if token
    }
    compact = _sanitize_texture_component(" ".join(text_parts))
    if tokens.intersection(_ACCENT_GLOW_TOKENS) or any(token in compact for token in _ACCENT_GLOW_TOKENS):
        return True
    return _texture_set_is_saturated_factor_shell_accent(texture_set, tokens)


def _texture_set_has_explicit_glow_authority(texture_set: ReplacementTextureSet) -> bool:
    role_tags = {
        _normalized_source_part_material_role(tag)
        for tag in tuple(getattr(texture_set, "source_role_tags", ()) or ())
    }
    if "glow" in role_tags:
        return True
    for slot in tuple((getattr(texture_set, "slots", {}) or {}).values()):
        slot_kind = str(getattr(slot, "slot_kind", "") or "").strip().lower()
        if slot_kind == "emissive":
            return True
        text_parts = (
            str(getattr(slot, "source_path", "") or ""),
            str(getattr(slot, "semantic_subtype", "") or ""),
            str(getattr(slot, "source_authority", "") or ""),
        )
        tokens = {token for token in re.split(r"[^a-z0-9]+", " ".join(text_parts).lower()) if token}
        compact = _sanitize_texture_component(" ".join(text_parts))
        if tokens & {"emissive", "emission", "glow", "illum", "illumination", "light"}:
            return True
        if any(marker in compact for marker in ("emissive", "emission", "glow", "illumination")):
            return True
    return False


def _texture_set_is_saturated_factor_shell_accent(
    texture_set: ReplacementTextureSet,
    tokens: set[str],
) -> bool:
    if not (tokens & _ACCENT_GLOW_FACTOR_SHELL_TOKENS):
        return False
    face_count = int(getattr(texture_set, "source_face_count", 0) or 0)
    if face_count <= 0 or face_count > 6000:
        return False
    base_slot = (getattr(texture_set, "slots", {}) or {}).get("base")
    if base_slot is not None and _source_slot_is_real_texture(base_slot):
        return False
    color = tuple(getattr(texture_set, "base_color_factor", ()) or ())
    if len(color) < 3:
        return False
    try:
        rgb = tuple(max(0.0, min(1.0, float(component))) for component in color[:3])
    except (TypeError, ValueError, OverflowError):
        return False
    strongest = max(rgb)
    weakest = min(rgb)
    return strongest >= 0.45 and (strongest - weakest) >= 0.35


def _texture_set_accent_glow_color_hex(
    texture_set: ReplacementTextureSet,
    source_slot: Optional[ReplacementTextureSlot],
) -> str:
    color = _normalized_accent_glow_rgb(getattr(texture_set, "accent_glow_color_rgb", ()))
    if not color:
        color = tuple(texture_set.base_color_factor or ())
    if len(color) < 3 and source_slot is not None:
        color = tuple(getattr(source_slot, "base_color_factor", ()) or ())
    if len(color) >= 3:
        try:
            rgb = tuple(max(0, min(255, int(round(float(component) * 255.0)))) for component in color[:3])
            if any(component > 0 for component in rgb) or _normalized_accent_glow_rgb(getattr(texture_set, "accent_glow_color_rgb", ())):
                return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}FF"
        except (TypeError, ValueError, OverflowError):
            pass
    if source_slot is not None:
        try:
            from PIL import Image, ImageStat

            with Image.open(source_slot.source_path) as image:
                rgba = image.convert("RGBA")
                if max(rgba.size) > 256:
                    rgba.thumbnail((256, 256))
                stat = ImageStat.Stat(rgba)
                rgb = tuple(max(0, min(255, int(round(value)))) for value in stat.mean[:3])
                if any(component > 10 for component in rgb):
                    strongest = max(rgb)
                    if strongest > 0:
                        boosted = tuple(max(0, min(255, int(round(component * 255.0 / strongest)))) for component in rgb)
                        return f"#{boosted[0]:02X}{boosted[1]:02X}{boosted[2]:02X}FF"
        except Exception:
            pass
    return "#FFFFFFFF"


def _texture_role_for_parameter_and_path(parameter_name: str, texture_path: str) -> str:
    role = infer_cd_texture_role_from_path(texture_path)
    if role:
        return role
    classification = classify_texture_binding(parameter_name, texture_path)
    return str(classification.slot_kind or "").strip().lower()


def _source_driven_template_reference(
    original_texture_refs: Sequence[object],
    slot_kind: str,
) -> Optional[object]:
    normalized = str(slot_kind or "").strip().lower()
    preferred_parameters = {
        "base": ("_overlaycolortexture", "_basecolortexture", "_diffusetexture", "_albedotexture", "_emissiveintensitytexture"),
        "normal": ("_normaltexture",),
        "height": ("_heighttexture",),
        "material_mask": ("_colorblendingmasktexture", "_overlaycolortexture"),
        "detail_mask": ("_detailmasktexture",),
        "emissive": ("_emissiveintensitytexture", "_emissivetexture", "_emissiveprogresstexture", "_overlaycolortexture"),
    }.get(normalized, ())

    fallback: Optional[object] = None
    parameter_fallback: Optional[object] = None
    for reference in original_texture_refs:
        target_path = _reference_target_path(reference)
        if not target_path.lower().endswith(".dds") or getattr(reference, "resolved_entry", None) is None:
            continue
        if fallback is None:
            fallback = reference
        parameter = str(getattr(reference, "sidecar_parameter_name", "") or "").strip().lower()
        role = _texture_role_for_parameter_and_path(parameter, target_path)
        if role == normalized:
            return reference
        if parameter in preferred_parameters and not parameter_fallback and (not role or role == normalized):
            parameter_fallback = reference
    return parameter_fallback or fallback


def _source_driven_texture_parent(original_texture_refs: Sequence[object]) -> str:
    for reference in original_texture_refs:
        target_path = _reference_target_path(reference)
        if target_path.lower().endswith(".dds"):
            parent = PurePosixPath(target_path.replace("\\", "/")).parent.as_posix()
            if parent and parent != ".":
                return parent
    return "character/texture"


def _source_driven_texture_prefix(original_sidecars: Sequence[tuple[object, str]]) -> str:
    if original_sidecars:
        sidecar_path = str(getattr(original_sidecars[0][0], "path", "") or "").replace("\\", "/")
        name = PurePosixPath(sidecar_path).name.lower()
        for suffix in (".pac_xml", ".pam_xml", ".pamlod_xml", ".pami", ".xml"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        if name.endswith(".pac") or name.endswith(".pam") or name.endswith(".pamlod"):
            name = PurePosixPath(name).stem
        cleaned = _sanitize_texture_component(name)
        if cleaned:
            return cleaned
    return "static_replacement"


def _source_driven_texture_output_path(
    texture_parent: str,
    texture_prefix: str,
    source_slot: ReplacementTextureSlot,
    emitted_paths: set[str],
) -> str:
    parent = str(texture_parent or "character/texture").replace("\\", "/").strip("/")
    prefix = _sanitize_texture_component(texture_prefix) or "static_replacement"
    output_stem, role_suffix = _source_driven_texture_output_name_parts(prefix, source_slot)
    base_name = f"{output_stem}{role_suffix}.dds"
    candidate = f"{parent}/{base_name}" if parent else base_name
    normalized = _normalize_texture_path(candidate)
    if normalized not in emitted_paths:
        emitted_paths.add(normalized)
        return candidate
    index = 2
    while True:
        base_name = f"{output_stem}_{index}{role_suffix}.dds"
        candidate = f"{parent}/{base_name}" if parent else base_name
        normalized = _normalize_texture_path(candidate)
        if normalized not in emitted_paths:
            emitted_paths.add(normalized)
            return candidate
        index += 1


def _source_driven_texture_output_name_parts(
    texture_prefix: str,
    source_slot: ReplacementTextureSlot,
) -> tuple[str, str]:
    prefix = _sanitize_texture_component(texture_prefix) or "static_replacement"
    slot_kind = str(source_slot.slot_kind or "").strip().lower()
    source_stem = _sanitize_texture_component(source_slot.source_path.stem) or slot_kind or "texture"
    if slot_kind == "normal":
        source_stem = _strip_source_role_suffix(
            source_stem,
            (
                "normal_green_up",
                "normal_directx",
                "normal_dx",
                "normalmap",
                "detailnormal",
                "wrinklenormal",
                "damagenormal",
                "normal",
                "norm",
                "nrm",
                "nm",
                "wn",
                "n",
            ),
        )
        return _source_driven_prefixed_stem(prefix, source_stem), "_n"
    if slot_kind == "height":
        source_stem = _strip_source_role_suffix(
            source_stem,
            ("displacement", "height", "depth", "dmap", "disp", "bump", "hgt", "hei", "he", "d", "h"),
        )
        return _source_driven_prefixed_stem(prefix, source_stem), "_disp"
    if slot_kind == "material":
        source_stem = _strip_source_role_suffix(
            source_stem,
            (
                "colorblendingmask",
                "detailmaterial",
                "detailmask",
                "material_mask",
                "materialmask",
                "mask_amg",
                "mask_1bit",
                "material",
                "mask",
                "masks",
                "mat",
                "ma",
                "mg",
                "sp",
                "m",
            ),
        )
        return _source_driven_prefixed_stem(prefix, source_stem), "_ma"
    if slot_kind == "material_mask":
        source_stem = _strip_source_role_suffix(
            source_stem,
            (
                "colorblendingmask",
                "material_mask",
                "materialmask",
                "mask_amg",
                "mask_1bit",
                "mask",
                "masks",
                "mat",
                "ma",
                "m",
            ),
        )
        return _source_driven_prefixed_stem(prefix, source_stem), "_ma"
    if slot_kind == "detail_mask":
        source_stem = _strip_source_role_suffix(
            source_stem,
            (
                "detailmaterial",
                "detail_mask",
                "detailmask",
                "mg",
            ),
        )
        return _source_driven_prefixed_stem(prefix, source_stem), "_mg"
    if slot_kind == "emissive":
        source_stem = _strip_source_role_suffix(
            source_stem,
            (
                "emissiveintensitytexture",
                "emissiveprogresstexture",
                "emissivetexture",
                "emissive",
                "emission",
                "illumination",
                "illum",
                "glow",
                "emi",
                "em",
            ),
        )
        return _source_driven_prefixed_stem(prefix, source_stem), "_emi"
    return _source_driven_prefixed_stem(prefix, source_stem), ""


def _source_driven_prefixed_stem(prefix: str, source_stem: str) -> str:
    cleaned = _sanitize_texture_component(source_stem)
    if not cleaned:
        return prefix
    if cleaned == prefix or cleaned.startswith(f"{prefix}_"):
        return cleaned
    return f"{prefix}_{cleaned}"


def _strip_source_role_suffix(source_stem: str, suffixes: Sequence[str]) -> str:
    cleaned = _sanitize_texture_component(source_stem)
    for suffix in sorted((_sanitize_texture_component(value) for value in suffixes), key=len, reverse=True):
        if not suffix:
            continue
        if cleaned == suffix:
            return ""
        marker = f"_{suffix}"
        if cleaned.endswith(marker):
            return cleaned[: -len(marker)].strip("_")
    return cleaned


def _sanitize_texture_component(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(value or "").lower())).strip("_")


def _build_source_driven_sidecar_text(
    sidecar_text: str,
    target_bindings: Mapping[str, Sequence[tuple[str, str, str]]],
    *,
    exact_only: bool = False,
    shader_name: str = "",
    insert_missing_slots: bool = False,
    material_authority_bruteforce: bool = False,
    material_profile: Optional[CDMaterialRuntimeProfile] = None,
    template_allowed_insertions: Mapping[str, Mapping[str, str]] = {},
    template_shader_overrides: Mapping[str, str] = {},
    target_safe_preserve_enabled: bool = False,
    target_safe_preserve_wrapper_names: Optional[set[str]] = None,
) -> tuple[str, int, set[str], set[str]]:
    wrapper_pattern = re.compile(
        r"\s*<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b[^>]*>.*?</(?P=tag)>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    default_bindings: Sequence[tuple[str, str, str]] = ()
    unique_binding_sets = {
        tuple((parameter, texture_path, slot_kind) for parameter, texture_path, slot_kind in bindings)
        for bindings in target_bindings.values()
    }
    if len(unique_binding_sets) == 1:
        default_bindings = next(iter(unique_binding_sets))
    changed_count = 0
    used_texture_paths: set[str] = set()
    changed_wrapper_names: set[str] = set()

    def replace_wrapper(match: re.Match[str]) -> str:
        nonlocal changed_count, used_texture_paths, changed_wrapper_names
        wrapper_text = match.group(0)
        wrapper_name = _source_driven_wrapper_name(wrapper_text)
        bindings = _source_driven_bindings_for_wrapper(
            wrapper_name,
            target_bindings,
            () if exact_only else default_bindings,
            exact_only=bool(exact_only),
        )
        if not bindings:
            return wrapper_text
        target_safe_preserve = bool(
            target_safe_preserve_enabled
            and _material_authority_wrapper_needs_target_safe_preserve(wrapper_text)
        )
        if target_safe_preserve and wrapper_name and target_safe_preserve_wrapper_names is not None:
            target_safe_preserve_wrapper_names.add(wrapper_name)
        patched_wrapper, changed, wrapper_used_paths = _patch_source_driven_wrapper_texture_slots(
            wrapper_text,
            bindings,
            shader_name=shader_name,
            template_shader_name=str(
                dict(template_shader_overrides or {}).get(_normalize_sidecar_material_name(wrapper_name), "") or ""
            ),
            insert_missing_slots=insert_missing_slots,
            material_authority_bruteforce=material_authority_bruteforce,
            material_profile=material_profile,
            template_allowed_insertions=template_allowed_insertions.get(
                _normalize_sidecar_material_name(wrapper_name),
                {},
            ),
            target_safe_preserve=target_safe_preserve,
        )
        if changed:
            changed_count += 1
            used_texture_paths.update(wrapper_used_paths)
            if wrapper_name:
                changed_wrapper_names.add(wrapper_name)
            return patched_wrapper
        return wrapper_text

    return (
        wrapper_pattern.sub(replace_wrapper, str(sidecar_text or "")),
        changed_count,
        used_texture_paths,
        changed_wrapper_names,
    )



def _source_driven_texture_keep_rules(
    target_bindings: Mapping[str, Sequence[tuple[str, str, str]]],
    *,
    material_profile: Optional[CDMaterialRuntimeProfile] = None,
) -> list[tuple[str, str]]:
    rules: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    detail_mask_contract = _profile_uses_detail_mask_material_contract(material_profile)

    def add(parameter_name: str, texture_path: str) -> None:
        parameter = str(parameter_name or "").strip()
        path = str(texture_path or "").replace("\\", "/").strip()
        key = (parameter.lower(), _normalize_texture_path(path))
        if not parameter or not key[1] or key in seen:
            return
        seen.add(key)
        rules.append((parameter, path))

    for bindings in target_bindings.values():
        for parameter_name, texture_path, slot_kind in bindings:
            add(parameter_name, texture_path)
            slot = str(slot_kind or "").strip().lower()
            parameter_key = str(parameter_name or "").strip().lower()
            if detail_mask_contract and (
                slot == "base"
                or parameter_key
                in {
                    "_overlaycolortexture",
                    "_basecolortexture",
                    "_diffusetexture",
                    "_albedotexture",
                }
            ):
                add("_baseColorTexture", texture_path)
    return rules


def _build_source_driven_pac_material_payloads(
    *,
    texture_sets: Mapping[str, ReplacementTextureSet],
    original_texture_refs: Sequence[object],
    original_sidecars: Sequence[tuple[object, str]],
    active_target_names: Sequence[str],
    target_to_source_material: Mapping[str, str],
    read_original_texture_bytes: Callable[[object], bytes],
    original_texture_source_path: Callable[[object], Path],
    report: TextureReplacementReport,
    on_log: Optional[Callable[[str], None]],
    texture_output_size_mode: str,
    neutralize_inherited_material_layers: bool = False,
    complete_external_material_reset: bool = False,
    complete_swap_material_profile: str = "arm_standard",
    complete_swap_global_gloss_reduction: float = 0.0,
    complete_swap_edge_relief_strength: float = 0.0,
    complete_swap_edge_relief_source: str = "hybrid",
    complete_swap_accent_glow_strength: float = 0.0,
    complete_swap_auto_brightness_balance: float = 0.0,
    complete_swap_dark_detail_lift: float = 0.0,
    complete_swap_tone_contrast: float = 0.0,
    removed_target_material_names: Sequence[str] = (),
    prune_removed_target_texture_parameters: bool = False,
    prune_unmapped_original_texture_parameters: bool = False,
    material_wrapper_clones: Sequence[SidecarMaterialWrapperClone] = (),
    source_owned_keep_material_names: Sequence[str] = (),
    output_draw_sections: Sequence[StaticOutputDrawSection] = (),
    pac_xml_corpus_root: str | Path | None = None,
    pac_xml_profile_cache_path: str | Path | None = None,
) -> list[TextureReplacementPayload]:
    material_profile = apply_true_source_basic_controls_to_profile(
        get_complete_swap_material_profile(complete_swap_material_profile),
        gloss_reduction=complete_swap_global_gloss_reduction,
        edge_relief_strength=complete_swap_edge_relief_strength,
        edge_relief_source=complete_swap_edge_relief_source,
        accent_glow_strength=complete_swap_accent_glow_strength,
        auto_brightness_balance=complete_swap_auto_brightness_balance,
        dark_detail_lift=complete_swap_dark_detail_lift,
        tone_contrast=complete_swap_tone_contrast,
    )
    material_authority_bruteforce = bool(_profile_is_material_authority_bruteforce(material_profile))
    removed_target_material_names = tuple(
        str(name or "").strip()
        for name in tuple(removed_target_material_names or ())
        if str(name or "").strip()
    )
    prune_removed_target_texture_parameters = bool(prune_removed_target_texture_parameters and removed_target_material_names)
    prune_unmapped_original_texture_parameters = bool(prune_unmapped_original_texture_parameters)
    if _profile_preserves_target_layer_response(material_profile):
        prune_unmapped_original_texture_parameters = False
        if _profile_is_runtime_xml(material_profile):
            _warn_once(
                report,
                "Material authority runtime XML: preserving target/corpus PAC XML shader, wrapper order, stock masks, detail, height, grime, dye, and PBD response; patching compatible direct source slots only.",
            )
        elif material_profile.name == "material_authority_pbr_source_test":
            _warn_once(
                report,
                "Material Authority PBR Source Test: using direct source bindings, high material roughness, source metalness, and no inherited dye/detail layer color pipeline.",
            )
        elif _profile_routes_source_color_to_layer_slots(material_profile):
            _warn_once(
                report,
                "Material authority source color + relief: source color authoritative; target relief/support preserved.",
            )
        else:
            _warn_once(
                report,
                "Material authority detail preserve: keeping target CD height/material/detail layer texture parameters.",
            )
    if material_authority_bruteforce:
        prune_unmapped_original_texture_parameters = False
        _warn_once(
            report,
            "Material authority brute force: preserving target shader texture parameter slots and repointing them to source-derived DDS.",
        )
    if _profile_authority_contract(material_profile) == "true_source_authority":
        _warn_once(
            report,
            "Material authority true source: original PAC/XML supplies draw ABI and protected hooks only; active source-owned wrappers use source or neutral generated visible material bindings.",
        )
    elif _profile_authority_contract(material_profile) == "true_source_authority_detail_mask":
        _warn_once(
            report,
            "Material Authority: source base uses working-mod overlay ItemID and source material mask is routed through _detailMaskTexture to avoid the glossy color-blend response.",
        )
    if not original_sidecars or (
        not active_target_names
        and not prune_removed_target_texture_parameters
        and not prune_unmapped_original_texture_parameters
    ):
        return []

    target_bindings: dict[str, list[tuple[str, str, str]]] = {}
    target_pbr_scalars: dict[str, tuple[int, int, str]] = {}
    target_emissive_settings: dict[str, tuple[str, float]] = {}
    generated_payloads: list[TextureReplacementPayload] = []
    generated_by_source: dict[tuple[str, str], str] = {}
    emitted_paths: set[str] = set()
    divergence_reported_materials: set[str] = set()
    texture_parent = _source_driven_texture_parent(original_texture_refs)
    texture_prefix = _source_driven_texture_prefix(original_sidecars)
    atlas_sections_by_target = _atlas_sections_by_target_name(output_draw_sections)
    runtime_xml_reports: list[PacXmlProfileReport] = []
    runtime_xml_template_insertions: dict[str, dict[str, str]] = {}
    runtime_xml_template_shader_overrides: dict[str, str] = {}
    runtime_xml_template_note_keys: set[tuple[str, str]] = set()
    runtime_xml_corpus_state: dict[str, object] = {"loaded": False, "index": None}
    if _profile_is_runtime_xml(material_profile):
        for sidecar_entry, sidecar_text in tuple(original_sidecars or ()):
            sidecar_path = str(getattr(sidecar_entry, "path", "") or "").strip()
            try:
                parsed_report = parse_pac_xml_profile(sidecar_text, sidecar_path)
            except Exception as exc:
                _warn_once(report, f"PAC XML runtime profile parser skipped {PurePosixPath(sidecar_path).name}: {exc}")
                continue
            if parsed_report.wrappers:
                runtime_xml_reports.append(parsed_report)

    def runtime_xml_corpus_index() -> Optional[PacXmlCorpusIndex]:
        if not _profile_is_runtime_xml(material_profile):
            return None
        if not bool(runtime_xml_corpus_state.get("loaded")):
            runtime_xml_corpus_state["loaded"] = True
            try:
                corpus_index = load_or_build_pac_xml_corpus_index(
                    pac_xml_corpus_root,
                    cache_path=pac_xml_profile_cache_path,
                )
                runtime_xml_corpus_state["index"] = corpus_index
                if corpus_index.xml_count:
                    _warn_once(
                        report,
                        "PAC XML corpus index ready: "
                        f"{corpus_index.xml_count:,} XML; {corpus_index.wrapper_count:,} wrappers; "
                        f"{corpus_index.parameter_count:,} params; paired models {corpus_index.paired_model_count:,}.",
                    )
                    if bool(getattr(corpus_index, "sqlite_backed", False)):
                        _warn_once(report, "PAC XML profile cache: sqlite v2; lazy template lookup.")
                else:
                    root_note = str(pac_xml_corpus_root or "").strip() or f"${{CDMW_PAC_XML_CORPUS_ROOT}}"
                    _warn_once(report, f"PAC XML corpus index unavailable or empty: {root_note}.")
            except Exception as exc:
                runtime_xml_corpus_state["index"] = None
                _warn_once(report, f"PAC XML corpus index failed to load: {exc}")
        loaded = runtime_xml_corpus_state.get("index")
        return loaded if isinstance(loaded, PacXmlCorpusIndex) else None

    def runtime_xml_report_and_wrapper_for_target(
        target_name: str,
    ) -> tuple[Optional[PacXmlProfileReport], Optional[PacXmlWrapperProfile]]:
        exact_target = _normalize_sidecar_material_name(target_name)
        best_report: Optional[PacXmlProfileReport] = None
        best_wrapper: Optional[PacXmlWrapperProfile] = None
        best_score = 0.0
        for parsed_report in runtime_xml_reports:
            for wrapper in parsed_report.wrappers:
                wrapper_name = str(wrapper.wrapper_name or "").strip()
                score = 0.0
                if _normalize_sidecar_material_name(wrapper_name) == exact_target:
                    score += 10.0
                elif wrapper_name and _sidecar_material_names_match(wrapper_name, target_name):
                    score += 7.0
                else:
                    score += _sidecar_material_match_score(target_name, wrapper_name)
                if score > best_score:
                    best_score = score
                    best_report = parsed_report
                    best_wrapper = wrapper
        if best_score < 3.0:
            return None, None
        return best_report, best_wrapper

    def runtime_xml_existing_parameter_name(target_name: str, slot_kind: str) -> str:
        slot = str(slot_kind or "").strip().lower()
        allowed_parameters = {
            "base": {"_overlaycolortexture", "_basecolortexture", "_diffusetexture", "_albedotexture"},
            "normal": {"_normaltexture"},
            "emissive": {"_emissiveintensitytexture", "_emissivetexture", "_emissiveprogresstexture"},
        }.get(slot, set())
        if not allowed_parameters:
            return ""
        template_map = runtime_xml_template_insertions.get(_normalize_sidecar_material_name(target_name), {})
        if slot in template_map:
            return template_map[slot]
        for reference in tuple(original_texture_refs or ()):
            material_name = str(getattr(reference, "material_name", "") or "").strip()
            if material_name and not _sidecar_material_names_match(material_name, target_name):
                continue
            parameter_name = str(getattr(reference, "sidecar_parameter_name", "") or "").strip()
            if parameter_name.lower() in allowed_parameters:
                return parameter_name
        parsed_report, target_wrapper = runtime_xml_report_and_wrapper_for_target(target_name)
        if parsed_report is None or target_wrapper is None:
            return ""
        return pac_xml_parameter_for_slot(target_wrapper, slot)

    def runtime_xml_wrapper_needs_template_fallback(
        parsed_report: Optional[PacXmlProfileReport],
        target_wrapper: Optional[PacXmlWrapperProfile],
        slot_kind: str,
    ) -> bool:
        if parsed_report is None or target_wrapper is None:
            return False
        family = str(parsed_report.profile.family or "").strip().lower()
        if family not in {"weapon", "prop", "tool", "static", "monster", "riding"}:
            return False
        shader_family = str(target_wrapper.shader_family or "").strip()
        slot = str(slot_kind or "").strip().lower()
        if shader_family in {"Cloth", "Hair", "Fur", "Skin", "SkinWrinkle", "Eye", "EyeCover"}:
            return False
        if shader_family in {"Emissive", "Poster", "Chain"} and slot != "emissive":
            return True
        return False

    def runtime_xml_template_match_for_slot(
        target_name: str,
        slot_kind: str,
        *,
        unsafe_target_profile: bool = False,
    ) -> PacXmlTemplateMatch:
        parsed_report, target_wrapper = runtime_xml_report_and_wrapper_for_target(target_name)
        match = select_best_pac_xml_template(
            parsed_report,
            target_wrapper,
            slot_kind,
            runtime_xml_corpus_index(),
            allow_shader_mismatch=bool(unsafe_target_profile),
            preferred_shader_families=("Standard_Ver2", "Standard") if unsafe_target_profile else (),
        )
        target_key = _normalize_sidecar_material_name(target_name)
        slot = str(slot_kind or "").strip().lower()
        if match.supports_slot and match.template_parameter_name:
            runtime_xml_template_insertions.setdefault(target_key, {})[slot] = match.template_parameter_name
            if unsafe_target_profile and match.template_shader_name:
                runtime_xml_template_shader_overrides[target_key] = match.template_shader_name
        note_key = (target_key, slot)
        if note_key not in runtime_xml_template_note_keys:
            runtime_xml_template_note_keys.add(note_key)
            _warn_once(report, match.summary(target_name=target_name, slot_kind=slot))
        return match

    def source_graph_texture_set_for_target(
        target_name: str,
        texture_set: ReplacementTextureSet,
    ) -> Optional[ReplacementTextureSet]:
        if not complete_external_material_reset or not _profile_is_source_only(material_profile):
            return texture_set
        if _profile_allows_factor_only_authority(material_profile) and _texture_set_has_source_authority_data(texture_set):
            return texture_set
        if _texture_set_has_real_source_texture(texture_set):
            return texture_set
        fallback_candidates = [
            candidate
            for candidate in texture_sets.values()
            if _texture_set_has_real_source_texture(candidate)
        ]
        if len(fallback_candidates) == 1:
            fallback = fallback_candidates[0]
            _warn_once(
                report,
                f"Strict source-owned routing inherited real source texture set {fallback.material_name} "
                f"for factor-only material {texture_set.material_name} on {target_name}.",
            )
            return fallback
        if len(fallback_candidates) > 1:
            names = ", ".join(
                str(candidate.material_name or "").strip()
                for candidate in fallback_candidates
                if str(candidate.material_name or "").strip()
            )
            report.errors.append(
                f"Strict source-owned routing cannot choose a texture fallback for factor-only material "
                f"{texture_set.material_name} on {target_name}: multiple source texture sets are available ({names}). "
                "Choose a source material override or split the draw section."
            )
            return None
        report.warnings.append(
            f"Strict source-owned routing found no real source texture set for factor-only material "
            f"{texture_set.material_name} on {target_name}."
        )
        return None

    def runtime_xml_slot_supported_by_target(target_name: str, slot_kind: str) -> bool:
        if not _profile_is_runtime_xml(material_profile):
            return True
        slot = str(slot_kind or "").strip().lower()
        parameter_sets = {
            "base": {"_overlaycolortexture", "_basecolortexture", "_diffusetexture", "_albedotexture"},
            "normal": {"_normaltexture"},
            "emissive": {"_emissiveintensitytexture", "_emissivetexture", "_emissiveprogresstexture"},
        }
        allowed_parameters = parameter_sets.get(slot)
        if allowed_parameters is None:
            return False
        parsed_report, target_wrapper = runtime_xml_report_and_wrapper_for_target(target_name)
        if runtime_xml_wrapper_needs_template_fallback(parsed_report, target_wrapper, slot):
            match = runtime_xml_template_match_for_slot(target_name, slot, unsafe_target_profile=True)
            if match.supports_slot:
                _warn_once(
                    report,
                    f"PAC XML runtime profile: unsafe target shader/profile on {target_name}; "
                    f"using matched corpus template {match.template_path or '<none>'} "
                    f"({match.template_shader_family or 'unknown shader'}).",
                )
                return True
            return False
        for reference in tuple(original_texture_refs or ()):
            material_name = str(getattr(reference, "material_name", "") or "").strip()
            if material_name and not _sidecar_material_names_match(material_name, target_name):
                continue
            parameter_name = str(getattr(reference, "sidecar_parameter_name", "") or "").strip().lower()
            if parameter_name in allowed_parameters:
                return True
        match = runtime_xml_template_match_for_slot(target_name, slot)
        return bool(match.supports_slot)

    for target_name in active_target_names:
        if is_static_replacement_helper_material_name(target_name):
            _warn_once(
                report,
                f"Preserved helper material wrapper {target_name}; automatic source texture routing does not patch _black/_inside-style parts. "
                "Use Advanced original-DDS overrides only if you intentionally want to edit that helper shader.",
            )
            continue
        atlas_section = _atlas_section_for_target(target_name, atlas_sections_by_target)
        if atlas_section is not None:
            atlas_bindings, atlas_payloads = _build_complete_swap_atlas_material_payloads(
                target_name=target_name,
                section=atlas_section,
                texture_sets=texture_sets,
                original_texture_refs=original_texture_refs,
                texture_parent=texture_parent,
                texture_prefix=texture_prefix,
                emitted_paths=emitted_paths,
                read_original_texture_bytes=read_original_texture_bytes,
                original_texture_source_path=original_texture_source_path,
                report=report,
                on_log=on_log,
                texture_output_size_mode=texture_output_size_mode,
                material_profile=material_profile,
            )
            generated_payloads.extend(atlas_payloads)
            if atlas_bindings:
                target_bindings[target_name] = atlas_bindings
                if any(str(slot_kind or "").strip().lower() == "emissive" for _parameter, _path, slot_kind in atlas_bindings):
                    for rect in tuple(getattr(atlas_section, "atlas_rects", ()) or ()):
                        material_name = str(getattr(rect, "source_material_name", "") or "").strip()
                        texture_set = texture_sets.get(material_name.lower())
                        if texture_set is None:
                            continue
                        emissive_slot = _slot_for_complete_swap_atlas_role(texture_set, "emissive", material_profile=material_profile)
                        if emissive_slot is None:
                            continue
                        target_emissive_settings[target_name] = (
                            _texture_set_accent_glow_color_hex(texture_set, emissive_slot),
                            effective_emissive_intensity(material_profile, source=texture_set),
                        )
                        break
            continue
        source_material = _best_source_material_for_target(target_name, target_to_source_material)
        texture_set = texture_sets.get(str(source_material or "").strip().lower()) if source_material else None
        if texture_set is None and len(texture_sets) == 1:
            texture_set = next(iter(texture_sets.values()))
        if texture_set is None:
            report.warnings.append(f"No replacement texture set was selected for rebuilt draw section {target_name}.")
            continue
        texture_set = source_graph_texture_set_for_target(target_name, texture_set)
        if texture_set is None:
            continue
        if complete_external_material_reset:
            material_key = str(texture_set.material_name or "").strip().lower()
            if material_key and material_key not in divergence_reported_materials:
                divergence_reported_materials.add(material_key)
                for reason in _complete_swap_material_divergence_reasons(texture_set, material_profile):
                    _warn_once(
                        report,
                        f"CD Runtime Approx divergence for {texture_set.material_name}: {reason}.",
                    )
            pbr_scalars = _source_pbr_scalar_values(texture_set)
            if pbr_scalars is not None:
                target_pbr_scalars[target_name] = pbr_scalars
        bindings: list[tuple[str, str, str]] = []
        source_slots = list(_source_driven_slots(
            texture_set,
            include_pbr_material_fallback=bool(complete_external_material_reset),
            include_complete_support_fallbacks=bool(complete_external_material_reset),
            material_profile=material_profile,
        ))
        if not any(str(slot.slot_kind or "").strip().lower() == "emissive" for slot in source_slots):
            accent_slot = _complete_swap_accent_emissive_slot(texture_set, target_name, material_profile)
            if accent_slot is not None:
                source_slots.append(accent_slot)
            else:
                skip_reason = _complete_swap_accent_glow_skip_reason(texture_set, target_name, material_profile)
                if skip_reason:
                    _warn_once(report, skip_reason)
        for source_slot in source_slots:
            if not runtime_xml_slot_supported_by_target(target_name, source_slot.slot_kind):
                continue
            parameter_name = (
                runtime_xml_existing_parameter_name(target_name, source_slot.slot_kind)
                if _profile_is_runtime_xml(material_profile)
                else ""
            )
            if not parameter_name:
                parameter_name = _source_driven_parameter_name(source_slot.slot_kind, material_profile=material_profile)
            if not parameter_name:
                continue
            source_key = (
                str(source_slot.source_path.expanduser().resolve()).lower(),
                str(source_slot.slot_kind or "").strip().lower(),
            )
            output_texture_path = generated_by_source.get(source_key)
            if output_texture_path is None:
                template_reference = _source_driven_template_reference(original_texture_refs, source_slot.slot_kind)
                target_entry = getattr(template_reference, "resolved_entry", None) if template_reference is not None else None
                if target_entry is None:
                    report.warnings.append(
                        f"Could not find an original DDS template for {source_slot.slot_kind} source {source_slot.source_path.name}."
                    )
                    continue
                output_texture_path = _source_driven_texture_output_path(
                    texture_parent,
                    texture_prefix,
                    source_slot,
                    emitted_paths,
                )
                try:
                    payload_data = _build_texture_payload(
                        source_slot,
                        target_entry=target_entry,
                        read_original_texture_bytes=read_original_texture_bytes,
                        original_texture_source_path=original_texture_source_path,
                        report=report,
                        on_log=on_log,
                        texture_output_size_mode=texture_output_size_mode,
                    )
                except Exception as exc:
                    report.errors.append(
                        f"Failed to build source-driven replacement texture for {source_slot.source_path.name}: {exc}"
                    )
                    continue
                generated_by_source[source_key] = output_texture_path
                generated_payloads.append(
                    TextureReplacementPayload(
                        target_path=output_texture_path,
                        payload_data=payload_data,
                        kind="texture_generated",
                        source_path=source_slot.source_path,
                        note=f"Source-driven material texture: {source_slot.source_path.name} -> {output_texture_path}",
                    )
                )
                if _is_complete_swap_runtime_material_mask_path(source_slot):
                    _warn_once(
                        report,
                        "Complete swap generated CD runtime material mask from source PBR/factors "
                        f"for {source_slot.material_name} using profile {material_profile.name}.",
                    )
                if (
                    normalize_basic_control_percent(getattr(material_profile, "edge_relief_strength", 0.0)) > 0.0
                    and str(source_slot.slot_kind or "").strip().lower() in {"height", "detail_mask"}
                    and "edge_relief" in source_slot.source_path.name.lower()
                ):
                    _warn_once(
                        report,
                        f"Edge relief generated {source_slot.slot_kind} support for {source_slot.material_name}: "
                        f"{output_texture_path}.",
                    )
            bindings.append((parameter_name, output_texture_path, source_slot.slot_kind))
            if str(source_slot.slot_kind or "").strip().lower() == "emissive":
                target_emissive_settings[target_name] = (
                    _texture_set_accent_glow_color_hex(texture_set, source_slot),
                    effective_emissive_intensity(material_profile, source=texture_set),
                )
            report.slot_mappings.append(
                TextureSlotMapping(
                    target_material_name=target_name,
                    target_texture_path=f"(source-driven {parameter_name})",
                    slot_kind=source_slot.slot_kind,
                    source_material_name=source_slot.material_name,
                    source_path=source_slot.source_path,
                    output_texture_path=output_texture_path,
                    normal_space=source_slot.normal_space,
                )
            )
        if bindings:
            target_bindings[target_name] = bindings

    if not generated_payloads or not target_bindings:
        if prune_unmapped_original_texture_parameters:
            return _build_patched_sidecar_payloads(
                original_sidecars=original_sidecars,
                sidecar_replacements_by_path={},
                sidecar_parameter_injections=(),
                texture_parameter_keep_rules=(),
                prune_unmapped_texture_parameters=True,
                prune_material_names=(),
                report=report,
            )
        if prune_removed_target_texture_parameters:
            return _build_removed_target_prune_sidecar_payloads(
                original_sidecars=original_sidecars,
                removed_target_material_names=removed_target_material_names,
                keep_rules=(),
                report=report,
            )
        return []

    sidecar_payloads: list[TextureReplacementPayload] = []
    used_source_texture_paths: set[str] = set()
    for sidecar_entry, sidecar_text in original_sidecars:
        sidecar_path = str(getattr(sidecar_entry, "path", "") or "").strip()
        target_safe_preserve_wrapper_names: set[str] = set()
        clone_report = SidecarPatchReport(sidecar_path=sidecar_path)
        cloned_sidecar_text = _apply_sidecar_material_wrapper_clones(
            sidecar_text,
            material_wrapper_clones,
            clone_report,
        )
        if clone_report.replaced_count or clone_report.warnings:
            report.sidecar_reports.append(clone_report)
            for warning in clone_report.warnings:
                _warn_once(report, warning)
        patched_text, changed_wrappers, used_paths, changed_wrapper_names = _build_source_driven_sidecar_text(
            cloned_sidecar_text,
            target_bindings,
            exact_only=bool(complete_external_material_reset),
            shader_name=material_profile.shader
            if complete_external_material_reset
            and not _profile_is_runtime_xml(material_profile)
            and not _profile_preserves_target_layer_response(material_profile)
            else "",
            insert_missing_slots=bool(complete_external_material_reset and not _profile_is_runtime_xml(material_profile)),
            material_authority_bruteforce=material_authority_bruteforce,
            material_profile=material_profile,
            template_allowed_insertions=runtime_xml_template_insertions if _profile_is_runtime_xml(material_profile) else {},
            template_shader_overrides=runtime_xml_template_shader_overrides if _profile_is_runtime_xml(material_profile) else {},
            target_safe_preserve_enabled=bool(
                complete_external_material_reset
                and not _profile_is_runtime_xml(material_profile)
                and _profile_uses_detail_mask_material_contract(material_profile)
            ),
            target_safe_preserve_wrapper_names=target_safe_preserve_wrapper_names,
        )
        target_safe_preserve_keys = {
            _normalize_sidecar_material_name(name)
            for name in target_safe_preserve_wrapper_names
            if _normalize_sidecar_material_name(name)
        }
        if target_safe_preserve_wrapper_names:
            _warn_once(
                report,
                "Material Authority target-safe preserve applied: "
                + ", ".join(sorted(target_safe_preserve_wrapper_names)[:8])
                + (" ..." if len(target_safe_preserve_wrapper_names) > 8 else ""),
            )
        gem_sensitive_wrappers = _visible_gem_sensitive_wrappers_touched(cloned_sidecar_text, changed_wrapper_names)
        if gem_sensitive_wrappers:
            _warn_once(
                report,
                "Visible gem-sensitive material wrapper(s) changed in a gem/emissive PAC XML: "
                + ", ".join(gem_sensitive_wrappers[:8])
                + (" ..." if len(gem_sensitive_wrappers) > 8 else "")
                + ". Validate gem color separately before treating the edit as blade/body-only.",
            )
        glow_settings = {
            target_name: target_emissive_settings[target_name]
            for target_name in target_bindings
            if target_name in target_emissive_settings
        }
        if glow_settings:
            patched_text, glow_wrappers = _apply_source_emissive_parameters(
                patched_text,
                glow_settings,
                exact_only=bool(complete_external_material_reset),
                preserve_shader_material_names=target_safe_preserve_wrapper_names,
            )
            if glow_wrappers:
                if _profile_accent_glow_strength(material_profile) > 0.0:
                    _warn_once(
                        report,
                        "Accent glow applied: "
                        f"{_profile_accent_glow_strength(material_profile):.0f}% "
                        f"({_profile_accent_glow_intensity(material_profile):.2f} emissive intensity) "
                        f"on {glow_wrappers:,} source-owned wrapper(s).",
                    )
                else:
                    _warn_once(
                        report,
                        f"Source emissive material parameters applied on {glow_wrappers:,} source-owned wrapper(s).",
                    )
        neutralized_parameters = 0
        if neutralize_inherited_material_layers and changed_wrappers > 0:
            neutralize_material_names = list(changed_wrapper_names) or list(target_bindings.keys())
            target_safe_neutralize_material_names: list[str] = []
            if target_safe_preserve_keys:
                standard_neutralize_material_names: list[str] = []
                for name in neutralize_material_names:
                    if _normalize_sidecar_material_name(name) in target_safe_preserve_keys:
                        target_safe_neutralize_material_names.append(name)
                    else:
                        standard_neutralize_material_names.append(name)
                neutralize_material_names = standard_neutralize_material_names
            keep_rules = _source_driven_texture_keep_rules(
                target_bindings,
                material_profile=material_profile,
            )
            neutralized_wrappers = 0
            if neutralize_material_names:
                patched_text, neutralized_wrappers, neutralized_parameters = _neutralize_inherited_material_layers(
                    patched_text,
                    material_names=neutralize_material_names,
                    keep_rules=keep_rules,
                    complete_external_reset=bool(complete_external_material_reset),
                    material_profile=material_profile,
                    exact_only=bool(complete_external_material_reset),
                )
            if target_safe_neutralize_material_names:
                patched_text, target_safe_neutralized_wrappers, target_safe_neutralized_parameters = _neutralize_inherited_material_layers(
                    patched_text,
                    material_names=target_safe_neutralize_material_names,
                    keep_rules=keep_rules,
                    complete_external_reset=bool(complete_external_material_reset),
                    material_profile=material_profile,
                    exact_only=bool(complete_external_material_reset),
                    preserve_wrapper_layer_support=True,
                )
                neutralized_wrappers += target_safe_neutralized_wrappers
                neutralized_parameters += target_safe_neutralized_parameters
                if target_safe_neutralized_parameters:
                    _warn_once(
                        report,
                        "Material Authority target-safe preserve neutralized inherited tint/layer scalar response for "
                        f"{target_safe_neutralized_wrappers:,} material wrapper(s), "
                        f"{target_safe_neutralized_parameters:,} parameter edit(s).",
                    )
            if neutralized_parameters:
                if complete_external_material_reset:
                    report.warnings.append(
                        "Complete external swap reset inherited target shader/material response for "
                        f"{neutralized_wrappers:,} source-driven material wrapper(s), {neutralized_parameters:,} parameter edit(s)."
                    )
                else:
                    report.warnings.append(
                        "Neutralized inherited material layers for "
                        f"{neutralized_wrappers:,} source-driven material wrapper(s), {neutralized_parameters:,} parameter edit(s)."
                    )
        if changed_wrappers <= 0:
            report.warnings.append(
                f"Skipped source-driven sidecar {PurePosixPath(sidecar_path).name}; no compatible material wrapper texture slot could be patched."
            )
            continue
        if complete_external_material_reset and (
            not _profile_preserves_target_layer_response(material_profile)
            or _profile_applies_source_pbr_scalars_with_preserved_layers(material_profile)
        ) and (
            target_pbr_scalars
            or material_profile.scratch_roughness is not None
            or material_profile.scratch_metallic is not None
            or material_profile.shine_scalar is not None
        ):
            scalar_material_names = list(changed_wrapper_names) or [
                name for name in target_bindings.keys() if name in target_pbr_scalars
            ]
            normalized_used_paths = {_normalize_texture_path(path) for path in used_paths}
            applied_scalar_wrappers = 0
            applied_sources: set[str] = set()
            for target_name in target_bindings:
                source_values = target_pbr_scalars.get(target_name)
                used_material_mask_binding = any(
                    str(slot_kind or "").strip().lower() in {"material", "material_mask"}
                    and _normalize_texture_path(texture_path) in normalized_used_paths
                    for _parameter_name, texture_path, slot_kind in target_bindings.get(target_name, ())
                )
                has_profile_scalars = (
                    material_profile.scratch_roughness is not None
                    or material_profile.scratch_metallic is not None
                    or material_profile.shine_scalar is not None
                )
                if used_material_mask_binding and not has_profile_scalars:
                    continue
                if source_values is None and not has_profile_scalars:
                    continue
                names_for_target = [
                    name for name in scalar_material_names if _sidecar_material_names_match(name, target_name)
                ] or [target_name]
                if target_safe_preserve_keys:
                    names_for_target = [
                        name
                        for name in names_for_target
                        if _normalize_sidecar_material_name(name) not in target_safe_preserve_keys
                    ]
                if not names_for_target:
                    continue
                roughness_value, metallic_value, shine_value, source_name = _profile_scalar_values(
                    material_profile,
                    source_values,
                )
                if roughness_value is None and metallic_value is None and shine_value is None:
                    continue
                patched_text, scalar_wrappers = _apply_source_pbr_scalar_parameters(
                    patched_text,
                    material_names=names_for_target,
                    roughness_value=roughness_value,
                    metallic_value=metallic_value,
                    shine_value=shine_value,
                    exact_only=bool(complete_external_material_reset),
                )
                if scalar_wrappers:
                    applied_scalar_wrappers += scalar_wrappers
                    if source_name:
                        applied_sources.add(source_name)
            if applied_scalar_wrappers:
                if (
                    material_profile.scratch_roughness is not None
                    or material_profile.scratch_metallic is not None
                    or material_profile.shine_scalar is not None
                ):
                    report.warnings.append(
                        "Complete external swap applied calibrated scratch/shine scalar profile "
                        f"{material_profile.name} to {applied_scalar_wrappers:,} material wrapper(s)."
                    )
                else:
                    report.warnings.append(
                        "Complete external swap derived scratch roughness/metallic values from source PBR map(s) "
                        f"for {applied_scalar_wrappers:,} material wrapper(s): {', '.join(sorted(applied_sources))}."
                    )
        if complete_external_material_reset and _profile_is_runtime_xml(material_profile):
            _warn_once(
                report,
                "Material authority runtime XML: preserved original PAC XML wrapper order, helper/protected wrappers, IDs, and inactive material blocks.",
            )
        elif complete_external_material_reset:
            ordered_material_names = list(source_owned_keep_material_names or active_target_names)
            patched_text, removed_wrapper_names = _prune_source_owned_sidecar_material_wrappers(
                patched_text,
                keep_material_names=ordered_material_names,
            )
            if removed_wrapper_names:
                report.warnings.append(
                    "Complete external swap removed stale original material wrapper(s) from rebuilt PAC XML: "
                    + ", ".join(removed_wrapper_names[:8])
                    + (" ..." if len(removed_wrapper_names) > 8 else "")
                )
            patched_text, order_updates = _reorder_source_owned_sidecar_material_wrappers(
                patched_text,
                ordered_material_names=ordered_material_names,
            )
            if order_updates:
                report.warnings.append(
                    "Complete external swap reordered _subMeshResources wrappers to match rebuilt PAC draw sections."
                )
            patched_text, idbase_updates = _sync_submesh_resources_vector_idbase(patched_text)
            if idbase_updates:
                report.warnings.append(
                    "Complete external swap updated _subMeshResources IdBase for source-owned material wrapper IDs."
                )
        final_sidecar_refs = {
            _normalize_texture_path(texture_path)
            for _parameter_name, texture_path in _sidecar_texture_parameter_rows(patched_text)
            if str(texture_path or "").strip()
        }
        used_source_texture_paths.update(
            _normalize_texture_path(path)
            for path in used_paths
            if _normalize_texture_path(path) in final_sidecar_refs
        )
        if _profile_is_runtime_xml(material_profile):
            try:
                profile_match = build_pac_xml_profile_match_report(
                    cloned_sidecar_text,
                    patched_text,
                    sidecar_path,
                    changed_wrappers=changed_wrappers,
                    generated_dds=len(generated_payloads),
                )
                _warn_once(
                    report,
                    profile_match.chosen_profile.summary(),
                )
                _warn_once(report, profile_match.summary())
                for warning in profile_match.unsafe_refs[:6]:
                    _warn_once(report, f"PAC XML texture contract warning: {warning}")
            except Exception:
                pass
        sidecar_payloads.append(
            TextureReplacementPayload(
                target_path=sidecar_path,
                payload_data=patched_text.encode("utf-8"),
                kind="sidecar_generated",
                source_path=Path(PurePosixPath(sidecar_path).name),
                note=(
                    "Source-driven material sidecar patched from replacement mesh textures; "
                    "source-color faithful mode neutralized inherited material layers."
                    if neutralize_inherited_material_layers and neutralized_parameters > 0
                    else "Source-driven material sidecar patched from replacement mesh textures."
                ),
            )
        )

    if sidecar_payloads:
        if used_source_texture_paths:
            before_count = len(generated_payloads)
            generated_payloads = [
                payload
                for payload in generated_payloads
                if _normalize_texture_path(payload.target_path) in used_source_texture_paths
            ]
            skipped_count = before_count - len(generated_payloads)
            if skipped_count:
                report.warnings.append(
                    f"Skipped {skipped_count:,} generated source texture(s) because no compatible original shader parameter used them."
                )
            report.slot_mappings[:] = [
                mapping
                for mapping in report.slot_mappings
                if not str(mapping.target_texture_path or "").startswith("(source-driven ")
                or _normalize_texture_path(mapping.output_texture_path) in used_source_texture_paths
            ]
        if neutralize_inherited_material_layers:
            if complete_external_material_reset:
                report.warnings.append(
                    "PAC XML source-driven patch: complete external swap reset target shader/material response and used source texture roles where possible."
                )
            elif any("Neutralized inherited material layers" in warning for warning in report.warnings):
                report.warnings.append(
                    "PAC XML source-driven patch: source-color faithful mode neutralized inherited tint/grime/detail/color-blend layers on patched wrappers."
                )
            else:
                report.warnings.append(
                    "PAC XML source-driven patch: source-color faithful mode was enabled, but no inherited material layers matched the patched wrappers."
                )
        else:
            report.warnings.append(
                "PAC XML source-driven patch: preserved original shader wrappers and rebound compatible direct texture slots only."
            )
        _append_texture_contract_warnings(
            texture_payloads=generated_payloads,
            sidecar_payloads=sidecar_payloads,
            report=report,
        )
    if prune_removed_target_texture_parameters or prune_unmapped_original_texture_parameters:
        keep_rules = _source_driven_texture_keep_rules(
            target_bindings,
            material_profile=material_profile,
        )
        if prune_unmapped_original_texture_parameters:
            pruned_payloads = _build_patched_sidecar_payloads(
                original_sidecars=_overlay_original_sidecars_with_payloads(original_sidecars, sidecar_payloads),
                sidecar_replacements_by_path={},
                sidecar_parameter_injections=(),
                texture_parameter_keep_rules=keep_rules,
                prune_unmapped_texture_parameters=True,
                prune_material_names=list(target_bindings.keys()) if complete_external_material_reset else (),
                report=report,
            )
        else:
            pruned_payloads = _build_removed_target_prune_sidecar_payloads(
                original_sidecars=_overlay_original_sidecars_with_payloads(original_sidecars, sidecar_payloads),
                removed_target_material_names=removed_target_material_names,
                keep_rules=keep_rules,
                report=report,
            )
        if pruned_payloads:
            sidecar_payloads = _replace_sidecar_payloads(sidecar_payloads, pruned_payloads)
    return generated_payloads + sidecar_payloads


def _apply_detail_mask_material_contract_to_wrapper(
    wrapper_text: str,
    material_mask_paths: Sequence[str],
    *,
    preserve_layer_support: bool = False,
) -> tuple[str, bool]:
    """Apply working-mod route: source color stays visible, source PBR mask becomes detail mask."""

    wanted_detail_paths = {
        _normalize_texture_path(path)
        for path in tuple(material_mask_paths or ())
        if _normalize_texture_path(path)
    }
    texture_pattern = re.compile(
        r"\s*<MaterialParameterTexture\b[^>]*>.*?</MaterialParameterTexture>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    changed = False
    kept_detail = False
    overlay_base_path = ""

    def set_item_id(block: str, item_id: str) -> str:
        if re.search(r'\bItemID="[^"]*"', block, flags=re.IGNORECASE):
            return re.sub(r'\bItemID="[^"]*"', f'ItemID="{item_id}"', block, count=1, flags=re.IGNORECASE)
        return re.sub(r"(<MaterialParameterTexture\b)", rf'\1 ItemID="{item_id}"', block, count=1, flags=re.IGNORECASE)

    def block_path(block: str) -> str:
        path_match = re.search(r'\b(?:_path|path|Path|_value|Value|value)="([^"]*)"', block, flags=re.IGNORECASE)
        return str(path_match.group(1) if path_match else "").replace("\\", "/").strip()

    def patch_block(match: re.Match[str]) -> str:
        nonlocal changed, kept_detail, overlay_base_path
        block = match.group(0)
        parameter_name = _sidecar_parameter_name(block).strip().lower()
        if parameter_name == "_overlaycolortexture":
            overlay_base_path = block_path(block)
            patched_block = set_item_id(block, "3936485985222654")
            if patched_block != block:
                changed = True
            return patched_block
        if parameter_name == "_colorblendingmasktexture":
            if preserve_layer_support:
                return block
            changed = True
            return ""
        if parameter_name == "_detailmasktexture":
            normalized_path = _normalize_texture_path(block_path(block))
            should_keep = False
            if wanted_detail_paths:
                should_keep = normalized_path in wanted_detail_paths and not kept_detail
            else:
                should_keep = not kept_detail
            if not should_keep:
                if preserve_layer_support:
                    return block
                changed = True
                return ""
            kept_detail = True
            patched_block = set_item_id(block, "2838988925698046")
            if patched_block != block:
                changed = True
            return patched_block
        return block

    patched = texture_pattern.sub(patch_block, wrapper_text)
    if overlay_base_path:
        patched, base_changed = _replace_source_driven_texture_parameter(
            patched,
            ("_basecolortexture",),
            overlay_base_path,
            preferred_existing_roles=("base",),
            allow_unclassified_parameter=True,
        )
        if not base_changed:
            patched, base_changed = _insert_source_driven_texture_parameter(
                patched,
                "_baseColorTexture",
                overlay_base_path,
            )
        if base_changed:
            changed = True
    if changed:
        patched = _renumber_sidecar_parameter_indexes(patched)
    return patched, changed


def _patch_source_driven_wrapper_texture_slots(
    wrapper_text: str,
    bindings: Sequence[tuple[str, str, str]],
    *,
    shader_name: str = "",
    template_shader_name: str = "",
    insert_missing_slots: bool = False,
    material_authority_bruteforce: bool = False,
    material_profile: Optional[CDMaterialRuntimeProfile] = None,
    template_allowed_insertions: Mapping[str, str] = {},
    target_safe_preserve: bool = False,
) -> tuple[str, bool, set[str]]:
    patched = wrapper_text
    changed = False
    used_paths: set[str] = set()
    runtime_xml_profile = _profile_is_runtime_xml(material_profile)
    detail_mask_material_contract = _profile_uses_detail_mask_material_contract(material_profile)
    material_mask_paths: list[str] = []
    forced_emissive_shader = False
    template_allowed_insertions = {
        str(slot or "").strip().lower(): str(parameter or "").strip()
        for slot, parameter in dict(template_allowed_insertions or {}).items()
        if str(slot or "").strip() and str(parameter or "").strip()
    }

    def insertion_allowed(slot_name: str) -> bool:
        return bool(insert_missing_slots or (not runtime_xml_profile and slot_name in {"base", "emissive"}) or slot_name in template_allowed_insertions)

    def insertion_parameter(slot_name: str, fallback: str) -> str:
        value = template_allowed_insertions.get(slot_name)
        return value if value else fallback

    for _parameter_name, texture_path, slot_kind in bindings:
        slot = str(slot_kind or "").strip().lower()
        requested_parameter = str(_parameter_name or "").strip()
        requested_parameter_key = requested_parameter.lower()
        texture_value = str(texture_path or "").replace("\\", "/").strip()
        if not slot or not texture_value:
            continue
        if slot == "base":
            if requested_parameter_key == "_colorblendingmasktexture":
                patched, did_change = _replace_source_driven_texture_parameter(
                    patched,
                    ("_colorblendingmasktexture",),
                    texture_value,
                    preferred_existing_roles=("material_mask",),
                    allow_unclassified_parameter=True,
                )
                if not did_change:
                    patched, did_change = _insert_source_driven_texture_parameter(
                        patched,
                        "_colorBlendingMaskTexture",
                        texture_value,
                    )
            else:
                patched, did_change = _replace_source_driven_texture_parameter(
                    patched,
                    ("_overlaycolortexture", "_basecolortexture", "_diffusetexture", "_albedotexture"),
                    texture_value,
                    preferred_existing_roles=("base",),
                    allow_unclassified_parameter=True,
                )
                if not did_change and insertion_allowed("base"):
                    patched, did_change = _insert_source_driven_texture_parameter(
                        patched,
                        insertion_parameter("base", "_overlayColorTexture"),
                        texture_value,
                    )
        elif slot == "normal":
            patched, did_change = _replace_source_driven_texture_parameter(
                patched,
                ("_normaltexture",),
                texture_value,
                preferred_existing_roles=("normal",),
                allow_unclassified_parameter=True,
            )
            if not did_change and insertion_allowed("normal"):
                patched, did_change = _insert_source_driven_texture_parameter(
                    patched,
                    insertion_parameter("normal", "_normalTexture"),
                    texture_value,
                )
        elif slot == "height":
            patched, did_change = _replace_source_driven_texture_parameter(
                patched,
                ("_heighttexture",),
                texture_value,
                preferred_existing_roles=("height",),
                allow_unclassified_parameter=True,
            )
            if not did_change and insertion_allowed("height"):
                patched, did_change = _insert_source_driven_texture_parameter(
                    patched,
                    insertion_parameter("height", "_heightTexture"),
                    texture_value,
                )
        elif slot == "material_mask":
            if detail_mask_material_contract and target_safe_preserve:
                patched, did_change = _replace_source_driven_texture_parameter(
                    patched,
                    ("_detailmasktexture",),
                    texture_value,
                    rename_to="_detailMaskTexture",
                    preferred_existing_roles=("detail_mask", "material_mask"),
                    allow_unclassified_parameter=True,
                )
                if not did_change and insertion_allowed("material_mask"):
                    patched, did_change = _insert_source_driven_texture_parameter(
                        patched,
                        insertion_parameter("material_mask", "_detailMaskTexture"),
                        texture_value,
                    )
            elif detail_mask_material_contract or requested_parameter_key == "_detailmasktexture":
                patched, did_change = _replace_source_driven_texture_parameter(
                    patched,
                    ("_colorblendingmasktexture", "_detailmasktexture"),
                    texture_value,
                    rename_to="_detailMaskTexture",
                    preferred_existing_roles=("material_mask", "detail_mask"),
                    allow_unclassified_parameter=True,
                )
                if not did_change and insertion_allowed("material_mask"):
                    patched, did_change = _insert_source_driven_texture_parameter(
                        patched,
                        insertion_parameter("material_mask", "_detailMaskTexture"),
                        texture_value,
                    )
            else:
                patched, did_change = _replace_source_driven_texture_parameter(
                    patched,
                    ("_colorblendingmasktexture", "_overlaycolortexture"),
                    texture_value,
                    preferred_existing_roles=("material_mask",),
                    allow_unclassified_parameter=False,
                )
                if not did_change and insertion_allowed("material_mask"):
                    patched, did_change = _insert_source_driven_texture_parameter(
                        patched,
                        insertion_parameter("material_mask", "_colorBlendingMaskTexture"),
                        texture_value,
                    )
            if did_change:
                material_mask_paths.append(texture_value)
        elif slot == "detail_mask":
            patched, did_change = _replace_source_driven_texture_parameter(
                patched,
                ("_detailmasktexture",),
                texture_value,
                preferred_existing_roles=("detail_mask",),
                allow_unclassified_parameter=True,
            )
            if not did_change and insertion_allowed("detail_mask"):
                patched, did_change = _insert_source_driven_texture_parameter(
                    patched,
                    insertion_parameter("detail_mask", "_detailMaskTexture"),
                    texture_value,
                )
        elif slot == "material":
            patched, did_change = _replace_source_driven_texture_parameter(
                patched,
                ("_colorblendingmasktexture", "_detailmasktexture"),
                texture_value,
                preferred_existing_roles=("material", "material_mask", "detail_mask"),
                allow_unclassified_parameter=True,
            )
        elif slot == "emissive":
            patched, did_change = _replace_source_driven_texture_parameter(
                patched,
                ("_emissiveintensitytexture", "_emissivetexture", "_emissiveprogresstexture"),
                texture_value,
                preferred_existing_roles=("emissive", "base"),
                allow_unclassified_parameter=True,
            )
            if not did_change and insertion_allowed("emissive"):
                patched, did_change = _insert_source_driven_texture_parameter(
                    patched,
                    insertion_parameter("emissive", "_emissiveIntensityTexture"),
                    texture_value,
                )
            if did_change and not runtime_xml_profile and not target_safe_preserve:
                forced_emissive_shader = True
                patched = re.sub(
                    r'(<Material\b[^>]*\b_materialName=")([^"]*)(")',
                    r"\1SkinnedMeshEmissive_Ver2\3",
                    patched,
                    count=1,
                    flags=re.IGNORECASE | re.DOTALL,
                )
        else:
            did_change = False
        if did_change:
            changed = True
            used_paths.add(texture_value)
    if detail_mask_material_contract:
        patched, contract_changed = _apply_detail_mask_material_contract_to_wrapper(
            patched,
            material_mask_paths,
            preserve_layer_support=target_safe_preserve,
        )
        if contract_changed:
            changed = True
    if _profile_routes_source_color_to_layer_slots(material_profile):
        patched, color_changed, color_used_paths = _route_source_base_to_visible_color_texture_parameters(
            patched,
            bindings,
        )
        if color_changed:
            changed = True
            used_paths.update(color_used_paths)
    if material_authority_bruteforce:
        patched, brute_changed, brute_used_paths = _bruteforce_source_authority_texture_parameters(
            patched,
            bindings,
            material_profile=material_profile,
        )
        if brute_changed:
            changed = True
            used_paths.update(brute_used_paths)
    effective_shader_name = str(template_shader_name or "").strip() or str(shader_name or "").strip()
    if changed and effective_shader_name and not forced_emissive_shader and not target_safe_preserve:
        patched = _set_source_driven_wrapper_shader_name(patched, effective_shader_name)
    return patched, changed, used_paths


def _route_source_base_to_visible_color_texture_parameters(
    wrapper_text: str,
    bindings: Sequence[tuple[str, str, str]],
) -> tuple[str, bool, set[str]]:
    base_path = ""
    for parameter_name, texture_path, slot_kind in tuple(bindings or ()):
        slot = str(slot_kind or "").strip().lower()
        parameter_key = str(parameter_name or "").strip().lower()
        if slot == "base" or parameter_key in {"_overlaycolortexture", "_basecolortexture", "_diffusetexture", "_albedotexture"}:
            base_path = str(texture_path or "").replace("\\", "/").strip()
            if base_path:
                break
    if not base_path:
        return wrapper_text, False, set()

    texture_pattern = re.compile(
        r"<MaterialParameterTexture\b[^>]*>.*?</MaterialParameterTexture>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    changed = False
    used_paths: set[str] = set()

    def is_visible_color_parameter(parameter_name: str, texture_path: str) -> bool:
        parameter_key = str(parameter_name or "").strip().lower()
        compact = re.sub(r"[^a-z0-9]+", "", parameter_key)
        if any(token in compact for token in ("normal", "height", "displacement", "material", "roughness", "metallic", "metalness", "specular", "gloss", "ao", "occlusion")):
            return False
        if compact in {"colorblendingmasktexture", "detailmasktexture", "layermask"}:
            return False
        if any(
            token in compact
            for token in (
                "overlaycolor",
                "basecolor",
                "diffusetexture",
                "albedotexture",
                "grimediffuse",
                "detaildiffuse",
                "emissivetexture",
                "emissiveintensitytexture",
                "rgbtexture",
            )
        ):
            return True
        return _texture_role_for_parameter_and_path(parameter_key, texture_path) == "base"

    def patch_block(match: re.Match[str]) -> str:
        nonlocal changed
        block = match.group(0)
        parameter_name = _sidecar_parameter_name(block)
        path_match = re.search(r'(\b(?:_path|path|Path|_value|Value|value)=")([^"]*)(")', block, flags=re.IGNORECASE)
        if path_match is None:
            return block
        current_path = str(path_match.group(2) or "").replace("\\", "/").strip()
        if not is_visible_color_parameter(parameter_name, current_path):
            return block
        used_paths.add(base_path)
        if current_path == base_path:
            return block
        changed = True
        return block[: path_match.start()] + f"{path_match.group(1)}{_escape_xml_attr(base_path)}{path_match.group(3)}" + block[path_match.end() :]

    return texture_pattern.sub(patch_block, wrapper_text), changed, used_paths


def _bruteforce_source_authority_texture_parameters(
    wrapper_text: str,
    bindings: Sequence[tuple[str, str, str]],
    *,
    material_profile: Optional[CDMaterialRuntimeProfile] = None,
) -> tuple[str, bool, set[str]]:
    """Repoint every shader texture parameter to source-derived authority maps.

    CD weapon shaders often route visible color through grime/detail/layer slots,
    not just ``_overlayColorTexture``.  This probe keeps original parameter names
    so the shader ABI stays intact, but prevents any stock texture path from
    surviving inside a source-owned wrapper.
    """

    scope = _profile_bruteforce_texture_scope(material_profile)
    quality_safe = scope in {"quality_safe", "qualitysafe", "stable", "safe"}
    source_paths: dict[str, str] = {}
    for parameter_name, texture_path, slot_kind in tuple(bindings or ()):
        slot = str(slot_kind or "").strip().lower()
        path = str(texture_path or "").replace("\\", "/").strip()
        parameter_key = str(parameter_name or "").strip().lower()
        if not path:
            continue
        if slot == "base" or parameter_key in {"_overlaycolortexture", "_basecolortexture", "_diffusetexture", "_albedotexture"}:
            source_paths.setdefault("base", path)
        elif slot == "normal":
            source_paths.setdefault("normal", path)
        elif slot == "height" and quality_safe:
            source_paths.setdefault("height", path)
        elif slot == "detail_mask" and quality_safe:
            source_paths.setdefault("detail_mask", path)
        elif slot in {"material", "material_mask", "detail_mask", "height"}:
            source_paths.setdefault("material", path)
    if "material" not in source_paths:
        for _parameter_name, texture_path, slot_kind in tuple(bindings or ()):
            if str(slot_kind or "").strip().lower() in {"material_mask", "material"} and str(texture_path or "").strip():
                source_paths["material"] = str(texture_path or "").replace("\\", "/").strip()
                break
    fallback = source_paths.get("base") or source_paths.get("material") or source_paths.get("normal") or ""
    if not fallback:
        return wrapper_text, False, set()

    texture_pattern = re.compile(
        r"<MaterialParameterTexture\b[^>]*>.*?</MaterialParameterTexture>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    changed = False
    used_paths: set[str] = set()

    def replacement_for_parameter(parameter_name: str) -> str:
        normalized = str(parameter_name or "").strip().lower()
        compact = re.sub(r"[^a-z0-9]+", "", normalized)
        if quality_safe and any(token in compact for token in ("height", "displacement", "parallax", "bump")):
            return source_paths.get("height") or source_paths.get("detail_mask") or source_paths.get("material") or fallback
        if "normal" in compact:
            return source_paths.get("normal") or source_paths.get("base") or fallback
        if quality_safe and compact in {"detailmasktexture", "detailmask", "layermask"}:
            return source_paths.get("detail_mask") or source_paths.get("material") or source_paths.get("base") or fallback
        if quality_safe and any(token in compact for token in ("detailheight", "grimeheight", "damageheight")):
            return source_paths.get("height") or source_paths.get("detail_mask") or source_paths.get("material") or fallback
        if quality_safe and any(token in compact for token in ("detailmaterial", "grimematerial", "damagematerial", "colorblendingmask")):
            return source_paths.get("material") or source_paths.get("detail_mask") or source_paths.get("base") or fallback
        if any(token in compact for token in ("color", "colour", "diffuse", "albedo", "overlay", "emissive", "rgbtexture")):
            if "colorblendingmask" not in compact:
                return source_paths.get("base") or fallback
        if any(
            token in compact
            for token in (
                "mask",
                "material",
                "roughness",
                "metallic",
                "metalness",
                "specular",
                "gloss",
                "height",
                "displacement",
                "detail",
                "grime",
                "damage",
                "ao",
                "occlusion",
            )
        ):
            return source_paths.get("material") or source_paths.get("base") or fallback
        return source_paths.get("base") or fallback

    def patch_block(match: re.Match[str]) -> str:
        nonlocal changed
        block = match.group(0)
        parameter_name = _sidecar_parameter_name(block)
        texture_value = replacement_for_parameter(parameter_name)
        if not texture_value:
            return block
        path_match = re.search(r'(\b(?:_path|path|Path|_value|Value|value)=")([^"]*)(")', block, flags=re.IGNORECASE)
        if path_match is None:
            return block
        if str(path_match.group(2) or "").replace("\\", "/").strip() == texture_value:
            used_paths.add(texture_value)
            return block
        changed = True
        used_paths.add(texture_value)
        return block[: path_match.start()] + f"{path_match.group(1)}{_escape_xml_attr(texture_value)}{path_match.group(3)}" + block[path_match.end() :]

    patched = texture_pattern.sub(patch_block, wrapper_text)
    if changed:
        patched = _renumber_sidecar_parameter_indexes(patched)
    return patched, changed, used_paths



def _replace_source_driven_texture_parameter(
    wrapper_text: str,
    candidate_names: Sequence[str],
    texture_path: str,
    *,
    rename_to: str = "",
    preferred_existing_roles: Sequence[str] = (),
    allow_unclassified_parameter: bool = False,
) -> tuple[str, bool]:
    normalized_candidates = {str(name or "").strip().lower() for name in candidate_names if str(name or "").strip()}
    if not normalized_candidates:
        return wrapper_text, False
    texture_pattern = re.compile(
        r"<MaterialParameterTexture\b[^>]*>.*?</MaterialParameterTexture>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    normalized_preferred_roles = {
        str(role or "").strip().lower()
        for role in preferred_existing_roles
        if str(role or "").strip()
    }
    matches: list[tuple[int, re.Match[str], str]] = []
    for match in texture_pattern.finditer(wrapper_text):
        block = match.group(0)
        block_name = _sidecar_parameter_name(block).lower()
        if block_name not in normalized_candidates:
            continue
        path_match = re.search(r'\b(?:_path|path|Path|_value|Value|value)="([^"]*)"', block, flags=re.IGNORECASE)
        existing_path = path_match.group(1) if path_match is not None else ""
        role = _texture_role_for_parameter_and_path(block_name, existing_path)
        if normalized_preferred_roles:
            if role in normalized_preferred_roles:
                score = 100
            elif allow_unclassified_parameter and not infer_cd_texture_role_from_path(existing_path):
                score = 30
            else:
                continue
        else:
            score = 50
        matches.append((score, match, block))
    if not matches:
        return wrapper_text, False
    matches.sort(key=lambda item: item[0], reverse=True)
    _score, match, block = matches[0]
    patched_block = block
    if rename_to:
        patched_block = _rename_sidecar_parameter_name(patched_block, rename_to)
    effective_parameter_name = rename_to or _sidecar_parameter_name(patched_block)
    expected_item_id = _source_driven_parameter_item_id(effective_parameter_name)
    if expected_item_id != "0":
        if re.search(r'\bItemID="[^"]*"', patched_block, flags=re.IGNORECASE):
            patched_block = re.sub(
                r'\bItemID="[^"]*"',
                f'ItemID="{expected_item_id}"',
                patched_block,
                count=1,
                flags=re.IGNORECASE,
            )
        else:
            patched_block = re.sub(
                r"(<MaterialParameterTexture\b)",
                rf'\1 ItemID="{expected_item_id}"',
                patched_block,
                count=1,
                flags=re.IGNORECASE,
            )
    patched_block = re.sub(
        r'(\b(?:_path|path|Path|_value|Value|value)=")[^"]*(")',
        lambda path_match: f'{path_match.group(1)}{_escape_xml_attr(texture_path)}{path_match.group(2)}',
        patched_block,
        count=1,
        flags=re.IGNORECASE,
    )
    if patched_block == block:
        return wrapper_text, False
    return wrapper_text[: match.start()] + patched_block + wrapper_text[match.end() :], True


def _insert_source_driven_texture_parameter(
    wrapper_text: str,
    parameter_name: str,
    texture_path: str,
) -> tuple[str, bool]:
    normalized_parameter = str(parameter_name or "").strip()
    normalized_texture_path = str(texture_path or "").replace("\\", "/").strip()
    if not wrapper_text or not normalized_parameter or not normalized_texture_path:
        return wrapper_text, False

    texture_pattern = re.compile(
        r"<MaterialParameterTexture\b[^>]*>.*?</MaterialParameterTexture>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    lower_parameter = normalized_parameter.lower()
    for match in texture_pattern.finditer(wrapper_text):
        if _sidecar_parameter_name(match.group(0)).lower() == lower_parameter:
            return wrapper_text, False

    indent_match = re.search(r"\n([ \t]*)<MaterialParameter", wrapper_text)
    parameter_indent = indent_match.group(1) if indent_match else "\t\t\t\t\t\t\t"
    value_indent = f"{parameter_indent}\t"
    escaped_parameter = _escape_xml_attr(normalized_parameter)
    escaped_path = _escape_xml_attr(normalized_texture_path)
    item_id = _source_driven_parameter_item_id(normalized_parameter)
    insert_index = _next_material_parameter_index(wrapper_text)
    block = (
        f'\n{parameter_indent}<MaterialParameterTexture StringItemID="{escaped_parameter}" '
        f'ItemID="{item_id}" _name="{escaped_parameter}" Index="{insert_index}">'
        f'\n{value_indent}<ResourceReferencePath_ITexture Name="_value" _path="{escaped_path}"/>'
        f"\n{parameter_indent}</MaterialParameterTexture>"
    )

    parameter_vector_match = re.search(
        r'(<Vector\b[^>]*\bName="_parameters"[^>]*>)(.*?)(\s*</Vector>)',
        wrapper_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not parameter_vector_match:
        self_closing_match = re.match(
            r"(?P<leading>\s*)<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b(?P<attrs>[^>]*)/\s*>\s*$",
            wrapper_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if self_closing_match is not None:
            leading = self_closing_match.group("leading") or ""
            tag = self_closing_match.group("tag")
            attrs = self_closing_match.group("attrs") or ""
            patched = (
                f"{leading}<{tag}{attrs}>"
                f"\n\t\t\t\t\t<Material><Vector Name=\"_parameters\">"
                f"{block}"
                f"\n\t\t\t\t\t</Vector></Material>"
                f"\n{leading}</{tag}>"
            )
            return patched, True
        close_match = re.search(
            r"</(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)>\s*$",
            wrapper_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if close_match is None:
            return wrapper_text, False
        inserted_body = (
            f"\n\t\t\t\t\t<Material><Vector Name=\"_parameters\">"
            f"{block}"
            f"\n\t\t\t\t\t</Vector></Material>"
        )
        return wrapper_text[: close_match.start()] + inserted_body + wrapper_text[close_match.start() :], True

    parameter_body = parameter_vector_match.group(2)
    insert_offset_in_body, insert_index = _sidecar_texture_injection_position(parameter_body, normalized_parameter)
    if insert_index is None:
        insert_index = _next_material_parameter_index(wrapper_text)
    block = (
        f'\n{parameter_indent}<MaterialParameterTexture StringItemID="{escaped_parameter}" '
        f'ItemID="{item_id}" _name="{escaped_parameter}" Index="{insert_index}">'
        f'\n{value_indent}<ResourceReferencePath_ITexture Name="_value" _path="{escaped_path}"/>'
        f"\n{parameter_indent}</MaterialParameterTexture>"
    )

    if insert_offset_in_body is not None:
        parameter_body = _shift_sidecar_parameter_indexes(parameter_body, insert_index)
        new_parameter_body = parameter_body[:insert_offset_in_body] + block + parameter_body[insert_offset_in_body:]
    else:
        new_parameter_body = parameter_body + block

    return (
        wrapper_text[: parameter_vector_match.start(2)]
        + new_parameter_body
        + wrapper_text[parameter_vector_match.end(2) :],
        True,
    )


def _source_driven_wrapper_name(wrapper_text: str) -> str:
    name_match = re.search(
        r'(?:_subMeshName|subMeshName|SubMeshName|_submesh|submesh|MaterialName|materialName|Name|name)="([^"]+)"',
        wrapper_text,
        flags=re.IGNORECASE,
    )
    return str(name_match.group(1) if name_match else "").strip()


def _source_driven_bindings_for_wrapper(
    wrapper_name: str,
    target_bindings: Mapping[str, Sequence[tuple[str, str, str]]],
    default_bindings: Sequence[tuple[str, str, str]],
    *,
    exact_only: bool = False,
) -> Sequence[tuple[str, str, str]]:
    if not target_bindings:
        return ()
    if is_static_replacement_helper_material_name(wrapper_name):
        return ()
    wrapper_key = _normalize_sidecar_material_name(wrapper_name)
    for target_name, bindings in target_bindings.items():
        if wrapper_key and wrapper_key == _normalize_sidecar_material_name(target_name):
            return bindings
    if exact_only:
        return ()
    best_score = 0.0
    best_bindings: Sequence[tuple[str, str, str]] = ()
    for target_name, bindings in target_bindings.items():
        score = _sidecar_material_match_score(wrapper_name, target_name)
        if score > best_score:
            best_score = score
            best_bindings = bindings
    if best_score >= 6.0:
        return best_bindings
    return default_bindings


def _source_driven_parameter_body(bindings: Sequence[tuple[str, str, str]]) -> str:
    lines = [
        '\n\t\t\t\t\t\t\t<MaterialParameterBitFlag32 StringItemID="_renderSettingFlag" ItemID="8" _name="_renderSettingFlag" _value="4" Index="0"/>'
    ]
    index = 1
    for parameter_name, texture_path, _slot_kind in bindings:
        item_id = _source_driven_parameter_item_id(parameter_name)
        escaped_parameter = _escape_xml_attr(parameter_name)
        escaped_path = _escape_xml_attr(texture_path)
        lines.append(
            f'\n\t\t\t\t\t\t\t<MaterialParameterTexture StringItemID="{escaped_parameter}" ItemID="{item_id}" _name="{escaped_parameter}" Index="{index}">'
            f'\n\t\t\t\t\t\t\t\t<ResourceReferencePath_ITexture Name="_value" _path="{escaped_path}"/>'
            "\n\t\t\t\t\t\t\t</MaterialParameterTexture>"
        )
        index += 1
    return "".join(lines)



def _is_direct_pac_driven_parameter(reference: object, target_path: str) -> bool:
    if not target_path.lower().endswith(".dds"):
        return False
    if _looks_like_layered_detail_texture(target_path):
        return False
    parameter = str(getattr(reference, "sidecar_parameter_name", "") or "").strip().lower()
    return parameter in {
        "_overlaycolortexture",
        "_basecolortexture",
        "_diffusetexture",
        "_albedotexture",
        "_normaltexture",
        "_heighttexture",
        "_emissiveintensitytexture",
        "_emissivetexture",
        "_emissiveprogresstexture",
        "_colorblendingmasktexture",
        "_detailmasktexture",
    }
from . import material_replacer as _material_replacer_facade

_material_replacer_facade._bind_lazy_material_exports(__name__, globals())
del _material_replacer_facade
