"""Pure material authority contract rules for texture replacement workflows."""

from __future__ import annotations

from collections.abc import Mapping
import json
import re

_MANUAL_COMPLETE_SWAP_MATERIAL_PROFILE_NAME = "material_authority_manual"
_MANUAL_COMPLETE_SWAP_MATERIAL_PROFILE_PREFIX = f"{_MANUAL_COMPLETE_SWAP_MATERIAL_PROFILE_NAME}:"
_AUTHORITY_CONTRACTS = {
    "runtime_xml_preserve",
    "true_source_authority",
    "true_source_authority_detail_mask",
}


def sanitize_texture_component(value: object) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(value or "").lower())).strip("_")


def material_profile_mask_binding_mode(material_profile: object) -> str:
    mode = sanitize_texture_component(str(getattr(material_profile, "mask_binding_mode", "") or "color_blending_mask"))
    aliases = {
        "colorblending": "color_blending_mask",
        "colorblendingmask": "color_blending_mask",
        "mask": "color_blending_mask",
        "detailmask": "detail_mask_material",
        "detailmaskmaterial": "detail_mask_material",
        "detailmaterial": "detail_mask_material",
        "materialdetailmask": "detail_mask_material",
        "scratch": "scratch_scalars",
        "scratchscalars": "scratch_scalars",
        "off": "disabled",
        "none": "disabled",
    }
    return aliases.get(
        mode,
        mode if mode in {"color_blending_mask", "detail_mask_material", "scratch_scalars", "disabled"} else "color_blending_mask",
    )


def material_profile_support_policy(material_profile: object) -> str:
    policy = sanitize_texture_component(str(getattr(material_profile, "support_policy", "") or "generated_or_neutral"))
    aliases = {
        "generatedorneutral": "generated_or_neutral",
        "neutral": "generated_or_neutral",
        "keep": "keep_original_support",
        "keeporiginal": "keep_original_support",
        "keeporiginalsupport": "keep_original_support",
        "generated": "generated_only",
        "generatedonly": "generated_only",
        "sourceonly": "source_only",
        "strict": "source_only",
        "strictsource": "source_only",
        "strictsourceonly": "source_only",
    }
    return aliases.get(policy, policy if policy in {"generated_or_neutral", "keep_original_support", "generated_only", "source_only"} else "generated_or_neutral")


def material_profile_is_runtime_xml(material_profile: object | None) -> bool:
    if material_profile is None:
        return False
    name = sanitize_texture_component(str(getattr(material_profile, "name", "") or ""))
    if name == "material_authority_runtime_xml":
        return True
    return (
        sanitize_texture_component(str(getattr(material_profile, "xml_profile_mode", "") or "")) == "runtime_xml"
        and material_profile_mask_binding_mode(material_profile) == "disabled"
        and material_profile_support_policy(material_profile) == "keep_original_support"
        and bool(getattr(material_profile, "preserve_target_layer_response", False))
    )


def material_profile_authority_contract(profile: object | None) -> str:
    if profile is None:
        return ""
    raw = sanitize_texture_component(str(getattr(profile, "authority_contract", "") or ""))
    aliases = {
        "runtime_xml": "runtime_xml_preserve",
        "runtimexml": "runtime_xml_preserve",
        "runtime_xml_authority": "runtime_xml_preserve",
        "runtime_xml_preserve": "runtime_xml_preserve",
        "corpus_preserve": "runtime_xml_preserve",
        "preserve": "runtime_xml_preserve",
        "true_source": "true_source_authority",
        "source_authority": "true_source_authority",
        "strict_source": "true_source_authority",
        "strict_source_authority": "true_source_authority",
        "true_source_authority": "true_source_authority",
        "detail_mask_authority": "true_source_authority_detail_mask",
        "detailmaskauthority": "true_source_authority_detail_mask",
        "true_source_detail_mask": "true_source_authority_detail_mask",
        "true_source_authority_detail_mask": "true_source_authority_detail_mask",
    }
    resolved = aliases.get(raw, raw)
    if resolved in _AUTHORITY_CONTRACTS:
        return resolved
    if material_profile_is_runtime_xml(profile):
        return "runtime_xml_preserve"
    return ""


def _manual_profile_payload(profile_name: object) -> Mapping[str, object] | None:
    text = str(profile_name or "").strip()
    if not text.startswith(_MANUAL_COMPLETE_SWAP_MATERIAL_PROFILE_PREFIX):
        return None
    payload_text = text[len(_MANUAL_COMPLETE_SWAP_MATERIAL_PROFILE_PREFIX) :]
    if not payload_text:
        return {}
    try:
        parsed = json.loads(payload_text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, Mapping) else {}


def complete_swap_material_authority_contract(profile_name: object = "") -> str:
    manual_payload = _manual_profile_payload(profile_name)
    if manual_payload is not None:
        contract = sanitize_texture_component(manual_payload.get("authority_contract", ""))
        return contract if contract in _AUTHORITY_CONTRACTS else "true_source_authority_detail_mask"

    normalized = sanitize_texture_component(profile_name or "arm_standard")
    aliases = {
        "source_pbr_runtime": "arm_emissive",
        "source_pbr_no_emissive": "arm_standard",
        "source_pbr_roughness_inverted": "arm_gloss",
        "source_pbr_metallic_inverted": "arm_metal_invert",
        "source_pbr_nonmetal_matte": "arm_nonmetal_matte",
        "source_triplet_strict": "source_graph_strict",
        "strict_source": "source_graph_strict",
        "strict_source_owned": "source_graph_strict",
        "manual": _MANUAL_COMPLETE_SWAP_MATERIAL_PROFILE_NAME,
        "material_authority_user": _MANUAL_COMPLETE_SWAP_MATERIAL_PROFILE_NAME,
        "manual_material_authority": _MANUAL_COMPLETE_SWAP_MATERIAL_PROFILE_NAME,
        "material_authority": "material_authority_detail_mask",
        "automatic": "material_authority_detail_mask",
        "material_authority_automatic": "material_authority_detail_mask",
        "material_authority_default": "material_authority_detail_mask",
        "recommended_material_authority": "material_authority_detail_mask",
        "runtime_xml": "material_authority_runtime_xml",
        "xml_runtime": "material_authority_runtime_xml",
        "material_authority_xml": "material_authority_runtime_xml",
        "material_authority_runtime": "material_authority_runtime_xml",
        "runtime_xml_authority": "material_authority_runtime_xml",
        "corpus_xml": "material_authority_runtime_xml",
        "xml_authority": "material_authority_runtime_xml",
        "true_source": "material_authority_true_source",
        "source_authority": "material_authority_true_source",
        "material_authority_source": "material_authority_clean_source",
        "material_authority_true": "material_authority_true_source",
        "true_source_authority": "material_authority_true_source",
        "pbr_source_test": "material_authority_pbr_source_test",
        "source_pbr_test": "material_authority_pbr_source_test",
        "material_authority_pbr": "material_authority_pbr_source_test",
        "true_source_pbr": "material_authority_pbr_source_test",
        "detail_mask": "material_authority_detail_mask",
        "detail_mask_source": "material_authority_detail_mask",
        "material_authority_detail": "material_authority_detail_mask",
        "material_authority_detail_mask_source": "material_authority_detail_mask",
        "true_source_detail_mask": "material_authority_detail_mask",
        "placeholder_safe": "material_authority_detail_mask",
        "placeholder_safe_test": "material_authority_detail_mask",
        "material_authority_placeholder_safe": "material_authority_detail_mask",
        "material_authority_placeholder_safe_test": "material_authority_detail_mask",
        "clean_source": "material_authority_clean_source",
        "material_authority_clean": "material_authority_clean_source",
        "clean_source_authority": "material_authority_clean_source",
        "bruteforce": "material_authority_bruteforce",
        "material_bruteforce": "material_authority_bruteforce",
        "authority_bruteforce": "material_authority_bruteforce",
        "bruteforce_tuned": "material_authority_bruteforce_tuned",
        "material_bruteforce_tuned": "material_authority_bruteforce_tuned",
        "bitbright_tune": "material_authority_bruteforce_tuned",
        "detail_preserve": "material_authority_detail_preserve",
        "target_detail_preserve": "material_authority_detail_preserve",
        "stock_detail_preserve": "material_authority_detail_preserve",
        "source_color_relief": "material_authority_source_color_relief_preserve",
        "color_relief": "material_authority_source_color_relief_preserve",
        "source_color_target_relief": "material_authority_source_color_relief_preserve",
        "material_authority_color_relief": "material_authority_source_color_relief_preserve",
    }
    resolved = aliases.get(normalized, normalized)
    contracts = {
        _MANUAL_COMPLETE_SWAP_MATERIAL_PROFILE_NAME: "true_source_authority_detail_mask",
        "material_authority_runtime_xml": "runtime_xml_preserve",
        "material_authority_true_source": "true_source_authority",
        "material_authority_pbr_source_test": "true_source_authority",
        "material_authority_detail_mask": "true_source_authority_detail_mask",
        "material_authority_placeholder_safe_test": "true_source_authority_detail_mask",
        "material_authority_detail_preserve": "runtime_xml_preserve",
        "material_authority_source_color_relief_preserve": "runtime_xml_preserve",
    }
    return contracts.get(resolved, "")


def complete_swap_material_allows_inherited_layer_color_bindings(profile_name: object = "") -> bool:
    return complete_swap_material_authority_contract(profile_name) == "runtime_xml_preserve"


def complete_swap_material_requires_true_source_authority(profile_name: object = "") -> bool:
    return complete_swap_material_authority_contract(profile_name).startswith("true_source_authority")


__all__ = [
    "complete_swap_material_allows_inherited_layer_color_bindings",
    "complete_swap_material_authority_contract",
    "complete_swap_material_requires_true_source_authority",
    "material_profile_authority_contract",
    "material_profile_is_runtime_xml",
    "material_profile_mask_binding_mode",
    "material_profile_support_policy",
    "sanitize_texture_component",
]
