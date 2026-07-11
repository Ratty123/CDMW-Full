"""Material authority profiles and probe package helpers."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Optional, Sequence

from cdmw.domain.textures.material_authority import (
    material_profile_authority_contract,
    material_profile_is_runtime_xml,
    material_profile_mask_binding_mode,
    material_profile_support_policy,
)
from cdmw.domain.textures.material_parameters import (
    normalize_basic_control_percent as _normalize_basic_control_percent,
    normalize_edge_relief_source as _normalize_edge_relief_source,
    normalize_global_gloss_reduction as _normalize_global_gloss_reduction,
    normalize_gloss_reduction_mode as _normalize_gloss_reduction_mode,
    normalize_signed_basic_control_percent as _normalize_signed_basic_control_percent,
    normalize_tone_contrast as _normalize_tone_contrast,
    profile_accent_glow_intensity as _material_parameter_accent_glow_intensity,
    profile_accent_glow_strength as _material_parameter_accent_glow_strength,
    profile_metallic_inverted as _material_parameter_metallic_inverted,
    profile_roughness_inverted as _material_parameter_roughness_inverted,
    profile_source_emissive_enabled as _material_parameter_source_emissive_enabled,
    profile_source_emissive_parameter_intensity as _material_parameter_source_emissive_intensity,
)

MANUAL_COMPLETE_SWAP_MATERIAL_PROFILE_NAME = "material_authority_manual"
_MANUAL_COMPLETE_SWAP_MATERIAL_PROFILE_PREFIX = f"{MANUAL_COMPLETE_SWAP_MATERIAL_PROFILE_NAME}:"


def _sanitize_texture_component(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(value or "").lower())).strip("_")


@dataclass(slots=True, frozen=True)
class CDMaterialRuntimeProfile:
    name: str
    label: str
    ma_layout: str = "arm"
    material_mask_layout: str = "ao_roughness_metallic_alpha"
    roughness_inverted: bool = False
    roughness_invert: bool = False
    metallic_inverted: bool = False
    metallic_invert: bool = False
    force_nonmetal: bool = False
    ao_mode: str = "source"
    ao_default: int = 255
    roughness_default: int = 192
    metallic_default: int = 0
    alpha_default: int = 0
    emissive_mode: str = "disabled"
    shader: str = "SkinnedMeshStandard_Ver2"
    base_binding_mode: str = "overlay_texture"
    mask_binding_mode: str = "color_blending_mask"
    support_policy: str = "generated_or_neutral"
    scratch_roughness: Optional[float] = None
    scratch_metallic: Optional[float] = None
    shine_scalar: Optional[float] = None
    neutral_color_rgb: tuple[int, int, int] = ()
    preserve_scratch_alpha: bool = False
    displacement_scale_multiplier: Optional[float] = None
    displacement_scale_max: Optional[float] = None
    allow_factor_only_authority: bool = False
    bruteforce_texture_scope: str = "all"
    force_neutral_layer_support: bool = False
    factor_only_material_mask: bool = False
    preserve_target_layer_response: bool = False
    source_color_layer_authority: bool = False
    base_color_lift: int = 0
    base_color_scale: Optional[float] = None
    base_color_gamma: Optional[float] = None
    base_color_saturation: Optional[float] = None
    base_color_value_max: Optional[int] = None
    base_color_auto_balance: int = 0
    base_color_shadow_lift: int = 0
    base_color_tone_contrast: float = 0.0
    emissive_color_scale: Optional[float] = None
    emissive_color_saturation: Optional[float] = None
    emissive_color_value_max: Optional[int] = None
    roughness_min: Optional[int] = None
    roughness_scale: Optional[float] = None
    roughness_max: Optional[int] = None
    metallic_min: Optional[int] = None
    metallic_scale: Optional[float] = None
    metallic_max: Optional[int] = None
    xml_profile_mode: str = ""
    authority_contract: str = ""
    global_gloss_reduction: float = 0.0
    gloss_reduction_mode: str = "cd_smoothness_low"
    edge_relief_strength: float = 0.0
    edge_relief_source: str = "hybrid"
    accent_glow_strength: float = 0.0
    accent_glow_intensity_max: float = 5.5
    suppress_runtime_placeholder_material_bindings: bool = False
    note: str = ""


_MANUAL_PROFILE_FIELD_NAMES = (
    "ao_default",
    "roughness_default",
    "metallic_default",
    "alpha_default",
    "scratch_roughness",
    "scratch_metallic",
    "shine_scalar",
    "neutral_color_rgb",
    "displacement_scale_multiplier",
    "displacement_scale_max",
    "base_color_lift",
    "base_color_scale",
    "base_color_gamma",
    "base_color_saturation",
    "base_color_value_max",
    "base_color_auto_balance",
    "base_color_shadow_lift",
    "base_color_tone_contrast",
    "emissive_color_scale",
    "emissive_color_saturation",
    "emissive_color_value_max",
    "roughness_min",
    "roughness_scale",
    "roughness_max",
    "metallic_min",
    "metallic_scale",
    "metallic_max",
    "roughness_inverted",
    "roughness_invert",
    "metallic_inverted",
    "metallic_invert",
    "force_nonmetal",
    "preserve_scratch_alpha",
    "allow_factor_only_authority",
    "factor_only_material_mask",
    "force_neutral_layer_support",
    "preserve_target_layer_response",
    "source_color_layer_authority",
    "emissive_mode",
    "base_binding_mode",
    "mask_binding_mode",
    "support_policy",
    "authority_contract",
    "edge_relief_strength",
    "edge_relief_source",
    "global_gloss_reduction",
    "accent_glow_strength",
    "accent_glow_intensity_max",
)


def _material_authority_clean_source_profile() -> CDMaterialRuntimeProfile:
    return CDMaterialRuntimeProfile(
        name="material_authority_clean_source",
        label="Material Authority Clean Source",
        ma_layout="arm",
        material_mask_layout="ao_roughness_metallic_alpha",
        ao_mode="white",
        roughness_default=240,
        metallic_default=0,
        emissive_mode="intensity",
        support_policy="source_only",
        scratch_roughness=1.0,
        scratch_metallic=0.0,
        shine_scalar=0.0,
        neutral_color_rgb=(216, 216, 216),
        preserve_scratch_alpha=True,
        displacement_scale_multiplier=0.0,
        displacement_scale_max=0.0,
        allow_factor_only_authority=True,
        factor_only_material_mask=True,
        base_color_lift=68,
        base_color_scale=0.90,
        base_color_gamma=0.62,
        base_color_saturation=0.66,
        base_color_value_max=218,
        emissive_color_scale=0.18,
        emissive_color_saturation=0.60,
        emissive_color_value_max=72,
        roughness_min=246,
        metallic_scale=0.34,
        metallic_max=112,
        gloss_reduction_mode="source_roughness_high",
        note=(
            "Source-owned mesh replacement profile: bind source base/normal/PBR directly, "
            "lift very dark source albedo, cap hot emissive colors, and remove inherited CD grime/detail/height layers."
        ),
    )


def _material_authority_runtime_xml_profile() -> CDMaterialRuntimeProfile:
    return CDMaterialRuntimeProfile(
        name="material_authority_runtime_xml",
        label="Material Authority Runtime XML",
        ma_layout="arm",
        material_mask_layout="ao_roughness_metallic_alpha",
        ao_mode="white",
        roughness_default=240,
        metallic_default=0,
        emissive_mode="intensity",
        shader="",
        mask_binding_mode="disabled",
        support_policy="keep_original_support",
        neutral_color_rgb=(216, 216, 216),
        allow_factor_only_authority=True,
        preserve_scratch_alpha=True,
        preserve_target_layer_response=True,
        base_color_scale=1.0,
        base_color_gamma=1.0,
        base_color_saturation=1.0,
        base_color_value_max=255,
        emissive_color_scale=0.18,
        emissive_color_saturation=0.60,
        emissive_color_value_max=72,
        xml_profile_mode="runtime_xml",
        authority_contract="runtime_xml_preserve",
        note=(
            "Recommended XML-first material authority: preserve the target PAC XML shader, wrapper order, "
            "stock material/detail/height/grime/PBD response, and patch only compatible source base/normal/emissive slots."
        ),
    )


def _material_authority_true_source_profile() -> CDMaterialRuntimeProfile:
    return replace(
        _material_authority_clean_source_profile(),
        name="material_authority_true_source",
        label="Material Authority True Source",
        authority_contract="true_source_authority",
        note=(
            "Strict source-authority material path: original PAC/XML supplies draw ABI, wrapper order, IDs, "
            "render flags, and protected cloth/PBD hooks only; active source-owned wrappers use source or "
            "neutral generated visible material bindings."
        ),
    )


def _material_authority_pbr_source_test_profile() -> CDMaterialRuntimeProfile:
    return replace(
        _material_authority_clean_source_profile(),
        name="material_authority_pbr_source_test",
        label="Material Authority PBR Source Test",
        authority_contract="true_source_authority",
        roughness_inverted=False,
        roughness_invert=False,
        roughness_default=255,
        roughness_min=240,
        roughness_scale=1.0,
        roughness_max=255,
        metallic_scale=None,
        metallic_max=None,
        force_nonmetal=False,
        scratch_roughness=1.0,
        scratch_metallic=None,
        shine_scalar=0.0,
        gloss_reduction_mode="source_roughness_high",
        note=(
            "Experimental source-PBR authority profile: preserve source metalness, drive CD material green as high roughness "
            "for a matte response, and avoid the inherited CD dye/detail layer color pipeline."
        ),
    )


def _material_authority_detail_mask_profile() -> CDMaterialRuntimeProfile:
    return replace(
        _material_authority_pbr_source_test_profile(),
        name="material_authority_detail_mask",
        label="Automatic",
        authority_contract="true_source_authority_detail_mask",
        mask_binding_mode="detail_mask_material",
        base_color_lift=0,
        base_color_scale=1.0,
        base_color_gamma=1.0,
        base_color_saturation=1.0,
        base_color_value_max=255,
        emissive_color_scale=None,
        emissive_color_saturation=None,
        emissive_color_value_max=None,
        note=(
            "Proven working-mod material authority: bind source base through _overlayColorTexture with the "
            "working-mod overlay ItemID, route source PBR/material mask through _detailMaskTexture, and remove "
            "the glossy _colorBlendingMaskTexture response from source-owned wrappers."
        ),
    )


def _material_authority_placeholder_safe_test_profile() -> CDMaterialRuntimeProfile:
    return replace(
        _material_authority_detail_mask_profile(),
        name="material_authority_placeholder_safe_test",
        label="Material Authority Placeholder Safe Test",
        suppress_runtime_placeholder_material_bindings=True,
        note=(
            "Test-only Material Authority variant: same proven detail-mask material route, but runtime ABI "
            "placeholder draw slots stay on their original material wrappers so source glow/emissive bindings "
            "cannot attach to tiny hidden placeholder triangles."
        ),
    )


def _material_authority_manual_default_profile() -> CDMaterialRuntimeProfile:
    return replace(
        _material_authority_detail_mask_profile(),
        name=MANUAL_COMPLETE_SWAP_MATERIAL_PROFILE_NAME,
        label="Manual",
        note=(
            "Manual source-owned material profile based on Material Authority. "
            "UI controls override color, emissive, roughness, metallic, tint reset, displacement, and source-routing behavior."
        ),
    )


def _manual_profile_payload(profile_name: str) -> Optional[dict[str, object]]:
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
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def serialize_complete_swap_manual_material_profile(values: Mapping[str, object]) -> str:
    payload = {
        key: value
        for key, value in dict(values or {}).items()
        if key in _MANUAL_PROFILE_FIELD_NAMES
    }
    return _MANUAL_COMPLETE_SWAP_MATERIAL_PROFILE_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _coerce_optional_float(value: object, *, minimum: float = 0.0, maximum: float = 4.0) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return max(minimum, min(maximum, number))


def _coerce_optional_byte(value: object) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return max(0, min(255, int(value)))
    except (TypeError, ValueError, OverflowError):
        return None


def _manual_material_profile_from_payload(payload: Mapping[str, object]) -> CDMaterialRuntimeProfile:
    profile = _material_authority_manual_default_profile()
    updates: dict[str, object] = {}
    for key in (
        "ao_default",
        "roughness_default",
        "metallic_default",
        "alpha_default",
        "base_color_lift",
        "base_color_value_max",
        "base_color_auto_balance",
        "base_color_shadow_lift",
        "emissive_color_value_max",
        "roughness_min",
        "roughness_max",
        "metallic_min",
        "metallic_max",
    ):
        if key in payload:
            value = _coerce_optional_byte(payload.get(key))
            if value is not None:
                updates[key] = value
    for key in (
        "scratch_roughness",
        "scratch_metallic",
        "shine_scalar",
        "displacement_scale_multiplier",
        "displacement_scale_max",
        "base_color_scale",
        "base_color_gamma",
        "base_color_saturation",
        "emissive_color_scale",
        "emissive_color_saturation",
        "roughness_scale",
        "metallic_scale",
    ):
        if key in payload:
            updates[key] = _coerce_optional_float(payload.get(key))
    if "accent_glow_intensity_max" in payload:
        intensity_max = _coerce_optional_float(
            payload.get("accent_glow_intensity_max"),
            minimum=0.0,
            maximum=20.0,
        )
        if intensity_max is not None:
            updates["accent_glow_intensity_max"] = intensity_max
    if "base_color_tone_contrast" in payload:
        updates["base_color_tone_contrast"] = normalize_tone_contrast(payload.get("base_color_tone_contrast"))
    for key in (
        "roughness_inverted",
        "roughness_invert",
        "metallic_inverted",
        "metallic_invert",
        "force_nonmetal",
        "preserve_scratch_alpha",
        "allow_factor_only_authority",
        "factor_only_material_mask",
        "force_neutral_layer_support",
        "preserve_target_layer_response",
        "source_color_layer_authority",
    ):
        if key in payload:
            updates[key] = bool(payload.get(key))
    for key, allowed in (
        ("emissive_mode", {"disabled", "intensity"}),
        ("base_binding_mode", {"overlay_texture", "overlay_from_colorblend_slot", "tint_only", "disabled"}),
        ("mask_binding_mode", {"color_blending_mask", "detail_mask_material", "scratch_scalars", "disabled"}),
        ("support_policy", {"source_only", "generated_or_neutral", "generated_only", "keep_original_support"}),
        ("authority_contract", {"runtime_xml_preserve", "true_source_authority", "true_source_authority_detail_mask"}),
    ):
        raw = str(payload.get(key, "") or "").strip().lower()
        if raw in allowed:
            updates[key] = raw
    if "edge_relief_strength" in payload:
        updates["edge_relief_strength"] = normalize_basic_control_percent(payload.get("edge_relief_strength"))
    if "edge_relief_source" in payload:
        updates["edge_relief_source"] = normalize_edge_relief_source(payload.get("edge_relief_source"))
    if "global_gloss_reduction" in payload:
        updates["global_gloss_reduction"] = normalize_global_gloss_reduction(payload.get("global_gloss_reduction"))
    if "accent_glow_strength" in payload:
        updates["accent_glow_strength"] = normalize_basic_control_percent(payload.get("accent_glow_strength"))
    raw_rgb = payload.get("neutral_color_rgb")
    if isinstance(raw_rgb, Sequence) and not isinstance(raw_rgb, (str, bytes)) and len(raw_rgb) >= 3:
        try:
            updates["neutral_color_rgb"] = tuple(max(0, min(255, int(component))) for component in tuple(raw_rgb)[:3])
        except (TypeError, ValueError, OverflowError):
            pass
    return replace(profile, **updates)


@dataclass(slots=True, frozen=True)
class CDMaterialProbeVariant:
    name: str
    label: str
    material_profile_name: str
    description: str


@dataclass(slots=True, frozen=True)
class CDMaterialProbePackageResult:
    output_root: Path
    variant_dirs: tuple[Path, ...]
    manifests: tuple[Path, ...]


@dataclass(slots=True, frozen=True)
class SourceMaterialRoutingResult:
    target_material_name: str
    source_material_name: str = ""
    source_part_names: tuple[str, ...] = ()
    detected_roles: tuple[str, ...] = ()
    status: str = "Unknown"
    reason: str = ""
    blocker: bool = False


@dataclass(slots=True, frozen=True)
class TextureAssignmentGuidance:
    checked_by_default: bool
    confidence: str
    state_label: str
    reason: str
    advanced: bool = False


_HELPER_MATERIAL_SUFFIXES = ("black", "inside")


def complete_swap_material_runtime_profiles() -> tuple[CDMaterialRuntimeProfile, ...]:
    """Return game-facing CD material profiles available to complete swap.

    These are intentionally data-only.  They let complete swap emit probeable
    variants without changing PAC runtime ABI or texture routing.
    """

    return (
        CDMaterialRuntimeProfile(
            name="arm_standard",
            label="ARM Standard",
            ma_layout="arm",
            material_mask_layout="ao_roughness_metallic_alpha",
            note="Default calibrated baseline: _ma RGB=AO/roughness/metallic, emissive disabled.",
        ),
        CDMaterialRuntimeProfile(
            name="arm_emissive",
            label="ARM Emissive",
            ma_layout="arm",
            material_mask_layout="ao_roughness_metallic_alpha",
            emissive_mode="intensity",
            shader="SkinnedMeshEmissive_Ver2",
            note="ARM mask with source emissive intensity binding enabled for runtime calibration.",
        ),
        CDMaterialRuntimeProfile(
            name="rma_standard",
            label="RMA Standard",
            ma_layout="rma",
            material_mask_layout="roughness_metallic_ao_alpha",
            note="_ma RGB=roughness/metallic/AO probe.",
        ),
        CDMaterialRuntimeProfile(
            name="mra_standard",
            label="MRA Standard",
            ma_layout="mra",
            material_mask_layout="metallic_roughness_ao_alpha",
            note="_ma RGB=metallic/roughness/AO probe.",
        ),
        CDMaterialRuntimeProfile(
            name="arm_gloss",
            label="ARM Gloss",
            ma_layout="arm",
            material_mask_layout="ao_roughness_metallic_alpha",
            roughness_inverted=True,
            roughness_invert=True,
            note="Probe whether CD treats the roughness channel as gloss/smoothness.",
        ),
        CDMaterialRuntimeProfile(
            name="arm_metal_invert",
            label="ARM Metal Invert",
            ma_layout="arm",
            material_mask_layout="ao_roughness_metallic_alpha",
            metallic_inverted=True,
            metallic_invert=True,
            note="Probe whether CD treats the metallic/spec channel inverted.",
        ),
        CDMaterialRuntimeProfile(
            name="arm_ao_white",
            label="ARM AO White",
            ma_layout="arm",
            material_mask_layout="ao_roughness_metallic_alpha",
            ao_mode="white",
            note="Probe AO neutral value by forcing AO white.",
        ),
        CDMaterialRuntimeProfile(
            name="arm_nonmetal_matte",
            label="ARM Nonmetal Matte",
            ma_layout="arm",
            material_mask_layout="ao_roughness_metallic_alpha",
            roughness_default=224,
            metallic_default=0,
            force_nonmetal=True,
            scratch_roughness=0.88,
            scratch_metallic=0.0,
            shine_scalar=0.20,
            note="Runtime-safe calibration profile: high roughness and no metallic response.",
        ),
        CDMaterialRuntimeProfile(
            name="source_graph_strict",
            label="Source Graph Strict",
            ma_layout="arm",
            material_mask_layout="ao_roughness_metallic_alpha",
            ao_mode="white",
            support_policy="source_only",
            note=(
                "Strict source-owned mode: route only texture roles proven by the imported material graph "
                "or explicit source files; generate _ma only from real source PBR inputs."
            ),
        ),
        _material_authority_runtime_xml_profile(),
        _material_authority_true_source_profile(),
        _material_authority_pbr_source_test_profile(),
        _material_authority_detail_mask_profile(),
        _material_authority_placeholder_safe_test_profile(),
        _material_authority_manual_default_profile(),
        _material_authority_clean_source_profile(),
        CDMaterialRuntimeProfile(
            name="material_authority_bruteforce",
            label="Material Authority Brute Force",
            ma_layout="arm",
            material_mask_layout="ao_roughness_metallic_alpha",
            ao_mode="white",
            support_policy="source_only",
            note=(
                "Emergency source-owned probe: keep target shader texture slots but repoint every "
                "color/normal/material slot to source-derived DDS so CD layer stacks cannot use stock textures."
            ),
        ),
        CDMaterialRuntimeProfile(
            name="material_authority_bruteforce_tuned",
            label="Material Authority Brute Force Tuned",
            ma_layout="arm",
            material_mask_layout="ao_roughness_metallic_alpha",
            ao_mode="white",
            roughness_default=240,
            metallic_default=0,
            emissive_mode="intensity",
            support_policy="source_only",
            scratch_roughness=1.0,
            scratch_metallic=0.0,
            shine_scalar=0.0,
            neutral_color_rgb=(216, 216, 216),
            preserve_scratch_alpha=True,
            displacement_scale_multiplier=0.0,
            displacement_scale_max=0.0,
            allow_factor_only_authority=True,
            bruteforce_texture_scope="quality_safe",
            force_neutral_layer_support=True,
            note=(
                "Opt-in brute-force fine tune: keep source-owned texture authority and exact factor-only materials, "
                "but route height/detail-height to neutral support maps and disable displacement shimmer."
            ),
        ),
        CDMaterialRuntimeProfile(
            name="material_authority_detail_preserve",
            label="Material Authority Detail Preserve",
            ma_layout="arm",
            material_mask_layout="ao_roughness_metallic_alpha",
            ao_mode="white",
            support_policy="keep_original_support",
            allow_factor_only_authority=True,
            preserve_target_layer_response=True,
            authority_contract="runtime_xml_preserve",
            note=(
                "Comparison profile: patch source base/normal/factor color while preserving the target "
                "CD height/material/detail layer response that carries edge detail and non-gloss calibration."
            ),
        ),
        CDMaterialRuntimeProfile(
            name="material_authority_source_color_relief_preserve",
            label="Material Authority Source Color + Relief",
            ma_layout="arm",
            material_mask_layout="ao_roughness_metallic_alpha",
            ao_mode="white",
            support_policy="keep_original_support",
            allow_factor_only_authority=True,
            preserve_target_layer_response=True,
            source_color_layer_authority=True,
            authority_contract="runtime_xml_preserve",
            note=(
                "Comparison profile: route source base/factor color into visible CD color layers while "
                "preserving target normal/height/material support response for edge relief."
            ),
        ),
    )


def get_complete_swap_material_profile(profile_name: str = "") -> CDMaterialRuntimeProfile:
    manual_payload = _manual_profile_payload(profile_name)
    if manual_payload is not None:
        return _manual_material_profile_from_payload(manual_payload)
    normalized = _sanitize_texture_component(profile_name or "arm_standard")
    aliases = {
        "source_pbr_runtime": "arm_emissive",
        "source_pbr_no_emissive": "arm_standard",
        "source_pbr_roughness_inverted": "arm_gloss",
        "source_pbr_metallic_inverted": "arm_metal_invert",
        "source_pbr_nonmetal_matte": "arm_nonmetal_matte",
        "source_triplet_strict": "source_graph_strict",
        "strict_source": "source_graph_strict",
        "strict_source_owned": "source_graph_strict",
        "manual": MANUAL_COMPLETE_SWAP_MATERIAL_PROFILE_NAME,
        "material_authority_user": MANUAL_COMPLETE_SWAP_MATERIAL_PROFILE_NAME,
        "manual_material_authority": MANUAL_COMPLETE_SWAP_MATERIAL_PROFILE_NAME,
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
        "material_authority_detail_mask": "material_authority_detail_mask",
        "material_authority_detail_mask_source": "material_authority_detail_mask",
        "true_source_detail_mask": "material_authority_detail_mask",
        "placeholder_safe": "material_authority_detail_mask",
        "placeholder_safe_test": "material_authority_detail_mask",
        "material_authority_placeholder_safe": "material_authority_detail_mask",
        "material_authority_placeholder_safe_test": "material_authority_placeholder_safe_test",
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
    normalized = aliases.get(normalized, normalized)
    profiles = {profile.name: profile for profile in complete_swap_material_runtime_profiles()}
    return profiles.get(normalized, profiles["arm_standard"])


def normalize_global_gloss_reduction(value: object) -> float:
    return _normalize_global_gloss_reduction(value)


def normalize_basic_control_percent(value: object) -> float:
    return _normalize_basic_control_percent(value)


def normalize_signed_basic_control_percent(value: object) -> float:
    return _normalize_signed_basic_control_percent(value)


def normalize_tone_contrast(value: object) -> float:
    return _normalize_tone_contrast(value)


def normalize_edge_relief_source(value: object) -> str:
    return _normalize_edge_relief_source(value)


def _profile_uses_cd_smoothness_mask_response(material_profile: CDMaterialRuntimeProfile) -> bool:
    """True for source-authority profiles where the runtime mask channel behaves like CD gloss/smoothness."""

    mask_mode = str(getattr(material_profile, "mask_binding_mode", "") or "").strip().lower()
    xml_mode = str(getattr(material_profile, "xml_profile_mode", "") or "").strip().lower()
    contract = str(getattr(material_profile, "authority_contract", "") or "").strip().lower()
    name = str(getattr(material_profile, "name", "") or "").strip().lower()
    if name == MANUAL_COMPLETE_SWAP_MATERIAL_PROFILE_NAME:
        return mask_mode != "disabled"
    return bool(
        mask_mode != "disabled"
        and xml_mode != "runtime_xml"
        and contract != "runtime_xml_preserve"
    )


def _profile_global_gloss_reduction(material_profile: CDMaterialRuntimeProfile) -> float:
    return normalize_global_gloss_reduction(getattr(material_profile, "global_gloss_reduction", 0.0))


def _profile_accent_glow_strength(material_profile: Optional[CDMaterialRuntimeProfile]) -> float:
    return _material_parameter_accent_glow_strength(material_profile)


def _profile_accent_glow_intensity(material_profile: Optional[CDMaterialRuntimeProfile]) -> float:
    return _material_parameter_accent_glow_intensity(material_profile)


def _profile_requires_accent_glow_for_source_emissive(
    material_profile: Optional[CDMaterialRuntimeProfile],
) -> bool:
    if material_profile is None:
        return False
    name = str(getattr(material_profile, "name", "") or "").strip().lower()
    contract = str(getattr(material_profile, "authority_contract", "") or "").strip().lower()
    return name.startswith("material_authority") or contract.startswith("true_source_authority")


def _profile_source_emissive_enabled(material_profile: Optional[CDMaterialRuntimeProfile]) -> bool:
    return _material_parameter_source_emissive_enabled(material_profile)


def _profile_source_emissive_parameter_intensity(
    material_profile: Optional[CDMaterialRuntimeProfile],
) -> float:
    return _material_parameter_source_emissive_intensity(material_profile)


def _profile_gloss_reduction_mode(material_profile: CDMaterialRuntimeProfile) -> str:
    return _normalize_gloss_reduction_mode(getattr(material_profile, "gloss_reduction_mode", "cd_smoothness_low"))


def _blend_byte_value(value: Optional[int], target: int, strength: float, fallback: int = 0) -> int:
    current = max(0, min(255, int(value if value is not None else fallback)))
    wanted = max(0, min(255, int(target)))
    return max(0, min(255, int(round(current + (wanted - current) * strength))))


def _blend_float_value(value: Optional[float], target: float, strength: float, fallback: float = 0.0) -> float:
    current = float(value if value is not None else fallback)
    return float(current + (float(target) - current) * strength)


def apply_global_gloss_reduction_to_profile(
    material_profile: CDMaterialRuntimeProfile,
    reduction: object,
) -> CDMaterialRuntimeProfile:
    bias = normalize_global_gloss_reduction(reduction)
    if bias == 0.0:
        return material_profile
    strength = abs(bias) / 100.0

    if bias < 0.0:
        if _profile_uses_cd_smoothness_mask_response(material_profile):
            gloss_mode = _profile_gloss_reduction_mode(material_profile)
            if gloss_mode == "source_roughness_high":
                scratch_roughness = float(
                    material_profile.scratch_roughness if material_profile.scratch_roughness is not None else 1.0
                )
                shine_scalar = float(material_profile.shine_scalar if material_profile.shine_scalar is not None else 0.0)
                detail_mask_contract = _profile_uses_detail_mask_material_contract(material_profile)
                return replace(
                    material_profile,
                    global_gloss_reduction=bias,
                    roughness_default=_blend_byte_value(material_profile.roughness_default, 192 if detail_mask_contract else 48, strength, 255),
                    roughness_min=_blend_byte_value(material_profile.roughness_min, 192 if detail_mask_contract else 0, strength, 240),
                    roughness_scale=max(0.0, _blend_float_value(material_profile.roughness_scale, 0.65, strength, 1.0)),
                    roughness_max=_blend_byte_value(material_profile.roughness_max, 255 if detail_mask_contract else 128, strength, 255),
                    scratch_roughness=max(0.0, min(1.0, _blend_float_value(scratch_roughness, 0.18, strength, 1.0))),
                    scratch_metallic=material_profile.scratch_metallic,
                    shine_scalar=max(0.0, min(1.0, _blend_float_value(shine_scalar, 0.55, strength, 0.0))),
                    force_nonmetal=False,
                )
            if gloss_mode == "cd_smoothness_low_preserve_metal":
                scratch_smoothness = float(
                    material_profile.scratch_roughness if material_profile.scratch_roughness is not None else 0.125
                )
                shine_scalar = float(material_profile.shine_scalar if material_profile.shine_scalar is not None else 0.0)
                return replace(
                    material_profile,
                    global_gloss_reduction=bias,
                    roughness_default=_blend_byte_value(material_profile.roughness_default, 255, strength, 32),
                    roughness_min=_blend_byte_value(material_profile.roughness_min, 224, strength, 0),
                    roughness_scale=max(0.0, _blend_float_value(material_profile.roughness_scale, 1.0, strength, 1.0)),
                    roughness_max=_blend_byte_value(material_profile.roughness_max, 255, strength, 32),
                    scratch_roughness=max(0.0, min(1.0, _blend_float_value(scratch_smoothness, 0.85, strength, 0.125))),
                    scratch_metallic=material_profile.scratch_metallic,
                    shine_scalar=max(0.0, min(1.0, _blend_float_value(shine_scalar, 0.45, strength, 0.0))),
                    force_nonmetal=False,
                )
            scratch_roughness = float(material_profile.scratch_roughness if material_profile.scratch_roughness is not None else 0.50)
            scratch_metallic = float(material_profile.scratch_metallic if material_profile.scratch_metallic is not None else 0.0)
            shine_scalar = float(material_profile.shine_scalar if material_profile.shine_scalar is not None else 0.0)
            return replace(
                material_profile,
                global_gloss_reduction=bias,
                roughness_default=_blend_byte_value(material_profile.roughness_default, 255, strength, 192),
                roughness_min=_blend_byte_value(material_profile.roughness_min, 224, strength, material_profile.roughness_default),
                roughness_scale=max(0.0, _blend_float_value(material_profile.roughness_scale, 1.0, strength, 1.0)),
                roughness_max=_blend_byte_value(material_profile.roughness_max, 255, strength, 255),
                scratch_roughness=max(0.0, min(1.0, _blend_float_value(scratch_roughness, 0.85, strength, 0.50))),
                scratch_metallic=max(0.0, min(1.0, _blend_float_value(scratch_metallic, 0.35, strength, 0.0))),
                shine_scalar=max(0.0, min(1.0, _blend_float_value(shine_scalar, 0.45, strength, 0.0))),
                force_nonmetal=False,
            )

        scratch_roughness = float(material_profile.scratch_roughness if material_profile.scratch_roughness is not None else 1.0)
        scratch_metallic = float(material_profile.scratch_metallic if material_profile.scratch_metallic is not None else 0.0)
        shine_scalar = float(material_profile.shine_scalar if material_profile.shine_scalar is not None else 0.0)
        return replace(
            material_profile,
            global_gloss_reduction=bias,
            scratch_roughness=max(0.0, min(1.0, _blend_float_value(scratch_roughness, 0.20, strength, 1.0))),
            scratch_metallic=max(0.0, min(1.0, _blend_float_value(scratch_metallic, 0.35, strength, 0.0))),
            shine_scalar=max(0.0, min(1.0, _blend_float_value(shine_scalar, 0.45, strength, 0.0))),
            force_nonmetal=False,
        )

    percent = bias

    if _profile_uses_cd_smoothness_mask_response(material_profile):
        gloss_mode = _profile_gloss_reduction_mode(material_profile)
        if gloss_mode == "source_roughness_high":
            scratch_roughness = float(
                material_profile.scratch_roughness if material_profile.scratch_roughness is not None else 0.0
            )
            shine_scalar = float(material_profile.shine_scalar if material_profile.shine_scalar is not None else 0.0)
            return replace(
                material_profile,
                global_gloss_reduction=percent,
                roughness_default=_blend_byte_value(material_profile.roughness_default, 255, strength, 192),
                roughness_min=_blend_byte_value(material_profile.roughness_min, 255, strength, 0),
                roughness_scale=max(1.0, _blend_float_value(material_profile.roughness_scale, 1.0, strength, 1.0)),
                roughness_max=_blend_byte_value(material_profile.roughness_max, 255, strength, 255),
                scratch_roughness=max(0.0, min(1.0, _blend_float_value(scratch_roughness, 1.0, strength, 0.0))),
                scratch_metallic=None,
                shine_scalar=max(0.0, min(1.0, _blend_float_value(shine_scalar, 0.0, strength, 0.0))),
                force_nonmetal=False,
            )
        if gloss_mode == "cd_smoothness_low_preserve_metal":
            scratch_smoothness = float(
                material_profile.scratch_roughness if material_profile.scratch_roughness is not None else 0.125
            )
            shine_scalar = float(material_profile.shine_scalar if material_profile.shine_scalar is not None else 0.0)
            return replace(
                material_profile,
                global_gloss_reduction=percent,
                roughness_default=_blend_byte_value(material_profile.roughness_default, 32, strength, 32),
                roughness_min=_blend_byte_value(material_profile.roughness_min, 0, strength, 0),
                roughness_scale=max(0.0, _blend_float_value(material_profile.roughness_scale, 1.0, strength, 1.0)),
                roughness_max=_blend_byte_value(material_profile.roughness_max, 32, strength, 32),
                scratch_roughness=max(0.0, min(1.0, _blend_float_value(scratch_smoothness, 0.125, strength, 0.125))),
                scratch_metallic=material_profile.scratch_metallic,
                shine_scalar=max(0.0, min(1.0, _blend_float_value(shine_scalar, 0.0, strength, 0.0))),
                force_nonmetal=False,
            )
        # CD Standard_Ver2 weapon masks use the middle material channel as a gloss/smoothness-style
        # response in practice.  Lowering it makes source-owned swaps visibly more matte; raising it
        # can leave the same mirror/glass response users are trying to remove.
        scratch_roughness = float(material_profile.scratch_roughness if material_profile.scratch_roughness is not None else 1.0)
        scratch_metallic = float(material_profile.scratch_metallic if material_profile.scratch_metallic is not None else 0.0)
        shine_scalar = float(material_profile.shine_scalar if material_profile.shine_scalar is not None else 0.0)
        return replace(
            material_profile,
            global_gloss_reduction=percent,
            roughness_default=_blend_byte_value(material_profile.roughness_default, 32, strength, 192),
            roughness_min=_blend_byte_value(material_profile.roughness_min, 0, strength, material_profile.roughness_default),
            roughness_scale=max(0.0, _blend_float_value(material_profile.roughness_scale, 1.0, strength, 1.0)),
            roughness_max=_blend_byte_value(material_profile.roughness_max, 64, strength, 255),
            metallic_default=_blend_byte_value(material_profile.metallic_default, 0, strength, 0),
            metallic_min=_blend_byte_value(material_profile.metallic_min, 0, strength, 0),
            metallic_scale=max(0.0, _blend_float_value(material_profile.metallic_scale, 0.0, strength, 1.0)),
            metallic_max=_blend_byte_value(material_profile.metallic_max, 0, strength, 255),
            alpha_default=_blend_byte_value(material_profile.alpha_default, 0, strength, 0),
            scratch_roughness=max(0.0, min(1.0, _blend_float_value(scratch_roughness, 0.50, strength, 1.0))),
            scratch_metallic=max(0.0, min(1.0, _blend_float_value(scratch_metallic, 0.0, strength, 0.0))),
            shine_scalar=max(0.0, min(1.0, _blend_float_value(shine_scalar, 0.0, strength, 0.0))),
            force_nonmetal=bool(material_profile.force_nonmetal or percent >= 90.0),
        )

    def lower_byte(value: Optional[int], fallback: int = 0) -> int:
        return _blend_byte_value(value, 0, strength, fallback)

    def lower_scale(value: Optional[float], fallback: float = 1.0) -> float:
        current = max(0.0, min(4.0, float(value if value is not None else fallback)))
        return max(0.0, min(current, current * (1.0 - strength)))

    scratch_roughness = float(material_profile.scratch_roughness if material_profile.scratch_roughness is not None else 0.0)
    scratch_metallic = float(material_profile.scratch_metallic if material_profile.scratch_metallic is not None else 0.0)
    shine_scalar = float(material_profile.shine_scalar if material_profile.shine_scalar is not None else 0.0)
    return replace(
        material_profile,
        global_gloss_reduction=percent,
        metallic_default=lower_byte(material_profile.metallic_default, 0),
        metallic_min=lower_byte(material_profile.metallic_min, 0),
        metallic_scale=lower_scale(material_profile.metallic_scale, 1.0),
        metallic_max=lower_byte(material_profile.metallic_max, 255),
        scratch_roughness=max(scratch_roughness, scratch_roughness + (1.0 - scratch_roughness) * strength),
        scratch_metallic=max(0.0, min(scratch_metallic, scratch_metallic * (1.0 - strength))),
        shine_scalar=max(0.0, min(shine_scalar, shine_scalar * (1.0 - strength))),
        force_nonmetal=bool(material_profile.force_nonmetal or percent >= 90.0),
    )


def apply_true_source_basic_controls_to_profile(
    material_profile: CDMaterialRuntimeProfile,
    *,
    gloss_reduction: object = 0.0,
    edge_relief_strength: object = 0.0,
    edge_relief_source: object = "hybrid",
    accent_glow_strength: object = 0.0,
    auto_brightness_balance: object = 0.0,
    dark_detail_lift: object = 0.0,
    tone_contrast: object = 0.0,
) -> CDMaterialRuntimeProfile:
    profile = apply_global_gloss_reduction_to_profile(material_profile, gloss_reduction)
    edge_strength = normalize_basic_control_percent(edge_relief_strength)
    updates: dict[str, object] = {}
    auto_balance_strength = normalize_basic_control_percent(auto_brightness_balance)
    if auto_balance_strength > 0.0:
        updates["base_color_auto_balance"] = int(round(auto_balance_strength))
    brightness_strength = normalize_signed_basic_control_percent(dark_detail_lift)
    if brightness_strength > 0.0:
        strength = brightness_strength / 100.0
        current_shadow_lift = int(max(0, min(100, int(getattr(profile, "base_color_shadow_lift", 0) or 0))))
        current_gamma = _profile_base_color_gamma(profile)
        updates["base_color_shadow_lift"] = max(current_shadow_lift, int(round(brightness_strength)))
        updates["base_color_gamma"] = min(current_gamma, 1.0 - (0.18 * strength))
    elif brightness_strength < 0.0:
        strength = abs(brightness_strength) / 100.0
        try:
            raw_scale = getattr(profile, "base_color_scale", None)
            current_scale = float(raw_scale if raw_scale is not None else 1.0)
        except (TypeError, ValueError, OverflowError):
            current_scale = 1.0
        dim_scale = max(0.10, min(4.0, current_scale * (1.0 - 0.55 * strength)))
        updates["base_color_scale"] = dim_scale
    tone_strength = normalize_tone_contrast(tone_contrast)
    if abs(tone_strength) > 0.0001:
        updates["base_color_tone_contrast"] = tone_strength
    if edge_strength > 0.0:
        source_mode = normalize_edge_relief_source(edge_relief_source)
        updates["edge_relief_strength"] = edge_strength
        updates["edge_relief_source"] = source_mode
        if source_mode in {"generate_source", "hybrid"}:
            updates["force_neutral_layer_support"] = True
        current_scale = getattr(profile, "displacement_scale_multiplier", None)
        current_cap = getattr(profile, "displacement_scale_max", None)
        edge_scale = edge_strength / 100.0
        updates["displacement_scale_multiplier"] = max(float(current_scale or 0.0), edge_scale)
        updates["displacement_scale_max"] = max(float(current_cap or 0.0), edge_scale)
    glow_strength = normalize_basic_control_percent(accent_glow_strength)
    if glow_strength > 0.0:
        updates["accent_glow_strength"] = glow_strength
        updates["emissive_mode"] = "intensity"
    if not updates:
        return profile
    return replace(profile, **updates)


def complete_swap_material_profile_to_dict(profile: CDMaterialRuntimeProfile) -> dict[str, object]:
    return {
        "schema": "cdmw_cd_material_runtime_profile_v1",
        "name": profile.name,
        "label": profile.label,
        "ma_layout": profile.ma_layout,
        "material_mask_layout": profile.material_mask_layout,
        "roughness_inverted": _profile_roughness_inverted(profile),
        "metallic_inverted": _profile_metallic_inverted(profile),
        "force_nonmetal": bool(profile.force_nonmetal),
        "ao_mode": profile.ao_mode,
        "ao_default": int(profile.ao_default),
        "roughness_default": int(profile.roughness_default),
        "metallic_default": int(profile.metallic_default),
        "alpha_default": int(profile.alpha_default),
        "emissive_mode": profile.emissive_mode,
        "shader": profile.shader,
        "base_binding_mode": profile.base_binding_mode,
        "mask_binding_mode": profile.mask_binding_mode,
        "support_policy": profile.support_policy,
        "scratch_roughness": profile.scratch_roughness,
        "scratch_metallic": profile.scratch_metallic,
        "shine_scalar": profile.shine_scalar,
        "neutral_color_rgb": tuple(profile.neutral_color_rgb),
        "preserve_scratch_alpha": bool(profile.preserve_scratch_alpha),
        "displacement_scale_multiplier": profile.displacement_scale_multiplier,
        "displacement_scale_max": profile.displacement_scale_max,
        "allow_factor_only_authority": bool(profile.allow_factor_only_authority),
        "bruteforce_texture_scope": profile.bruteforce_texture_scope,
        "force_neutral_layer_support": bool(profile.force_neutral_layer_support),
        "factor_only_material_mask": bool(profile.factor_only_material_mask),
        "preserve_target_layer_response": bool(profile.preserve_target_layer_response),
        "source_color_layer_authority": bool(profile.source_color_layer_authority),
        "base_color_lift": int(profile.base_color_lift),
        "base_color_scale": profile.base_color_scale,
        "base_color_gamma": profile.base_color_gamma,
        "base_color_saturation": profile.base_color_saturation,
        "base_color_value_max": profile.base_color_value_max,
        "base_color_auto_balance": int(profile.base_color_auto_balance),
        "base_color_shadow_lift": int(profile.base_color_shadow_lift),
        "base_color_tone_contrast": float(profile.base_color_tone_contrast),
        "emissive_color_scale": profile.emissive_color_scale,
        "emissive_color_saturation": profile.emissive_color_saturation,
        "emissive_color_value_max": profile.emissive_color_value_max,
        "roughness_min": profile.roughness_min,
        "roughness_scale": profile.roughness_scale,
        "roughness_max": profile.roughness_max,
        "metallic_min": profile.metallic_min,
        "metallic_scale": profile.metallic_scale,
        "metallic_max": profile.metallic_max,
        "xml_profile_mode": profile.xml_profile_mode,
        "authority_contract": profile.authority_contract,
        "global_gloss_reduction": float(profile.global_gloss_reduction),
        "gloss_reduction_mode": profile.gloss_reduction_mode,
        "edge_relief_strength": float(profile.edge_relief_strength),
        "edge_relief_source": profile.edge_relief_source,
        "accent_glow_strength": float(profile.accent_glow_strength),
        "accent_glow_intensity_max": float(profile.accent_glow_intensity_max),
        "note": profile.note,
    }


def write_complete_swap_calibrated_material_profile(path: Path | str, profile_name: str) -> Path:
    profile = get_complete_swap_material_profile(profile_name)
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(complete_swap_material_profile_to_dict(profile), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return target


def read_complete_swap_calibrated_material_profile(path: Path | str, default_profile: str = "arm_standard") -> CDMaterialRuntimeProfile:
    source = Path(path).expanduser()
    if not source.is_file():
        return get_complete_swap_material_profile(default_profile)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except Exception:
        return get_complete_swap_material_profile(default_profile)
    if not isinstance(data, Mapping):
        return get_complete_swap_material_profile(default_profile)
    if str(data.get("name") or "").strip() == MANUAL_COMPLETE_SWAP_MATERIAL_PROFILE_NAME:
        return _manual_material_profile_from_payload(data)
    return get_complete_swap_material_profile(str(data.get("name") or default_profile))


def complete_swap_material_probe_variants() -> tuple[CDMaterialProbeVariant, ...]:
    variants: list[CDMaterialProbeVariant] = []
    for profile in complete_swap_material_runtime_profiles():
        if _profile_is_source_only(profile):
            continue
        variants.append(
            CDMaterialProbeVariant(
                name=f"probe_{profile.name}",
                label=profile.label,
                material_profile_name=profile.name,
                description=profile.note or profile.label,
            )
        )
    return tuple(variants)


def complete_swap_material_probe_manifest(
    profile_name: str,
    *,
    source_package_path: str = "wolf_gravestone_sword_free (1).zip",
) -> dict[str, object]:
    profile = get_complete_swap_material_profile(profile_name)
    return {
        "kind": "cd_complete_swap_material_probe",
        "source_package": str(source_package_path or ""),
        "geometry": "identical",
        "material_profile": {
            "name": profile.name,
            "ma_layout": profile.ma_layout,
            "roughness_inverted": _profile_roughness_inverted(profile),
            "metallic_inverted": _profile_metallic_inverted(profile),
            "ao_mode": profile.ao_mode,
            "emissive_mode": profile.emissive_mode,
            "shader": profile.shader,
            "base_binding_mode": profile.base_binding_mode,
            "mask_binding_mode": profile.mask_binding_mode,
            "support_policy": profile.support_policy,
            "scratch_roughness": profile.scratch_roughness,
            "scratch_metallic": profile.scratch_metallic,
            "shine_scalar": profile.shine_scalar,
            "neutral_color_rgb": tuple(profile.neutral_color_rgb),
            "preserve_scratch_alpha": bool(profile.preserve_scratch_alpha),
            "displacement_scale_multiplier": profile.displacement_scale_multiplier,
            "displacement_scale_max": profile.displacement_scale_max,
            "allow_factor_only_authority": bool(profile.allow_factor_only_authority),
            "bruteforce_texture_scope": profile.bruteforce_texture_scope,
            "force_neutral_layer_support": bool(profile.force_neutral_layer_support),
            "factor_only_material_mask": bool(profile.factor_only_material_mask),
            "preserve_target_layer_response": bool(profile.preserve_target_layer_response),
            "source_color_layer_authority": bool(profile.source_color_layer_authority),
            "base_color_lift": int(profile.base_color_lift),
            "base_color_scale": profile.base_color_scale,
            "base_color_gamma": profile.base_color_gamma,
            "base_color_saturation": profile.base_color_saturation,
            "base_color_value_max": profile.base_color_value_max,
            "base_color_auto_balance": int(profile.base_color_auto_balance),
            "base_color_shadow_lift": int(profile.base_color_shadow_lift),
            "base_color_tone_contrast": float(profile.base_color_tone_contrast),
            "emissive_color_scale": profile.emissive_color_scale,
            "emissive_color_saturation": profile.emissive_color_saturation,
            "emissive_color_value_max": profile.emissive_color_value_max,
            "roughness_min": profile.roughness_min,
            "roughness_scale": profile.roughness_scale,
            "roughness_max": profile.roughness_max,
            "metallic_min": profile.metallic_min,
            "metallic_scale": profile.metallic_scale,
            "metallic_max": profile.metallic_max,
            "xml_profile_mode": profile.xml_profile_mode,
            "authority_contract": profile.authority_contract,
            "global_gloss_reduction": float(profile.global_gloss_reduction),
            "edge_relief_strength": float(profile.edge_relief_strength),
            "edge_relief_source": profile.edge_relief_source,
            "accent_glow_strength": float(profile.accent_glow_strength),
            "accent_glow_intensity_max": float(profile.accent_glow_intensity_max),
        },
    }


def write_complete_swap_material_probe_manifests(
    output_root: Path | str,
    *,
    source_package_path: str = "wolf_gravestone_sword_free (1).zip",
) -> tuple[Path, ...]:
    root = Path(output_root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for variant in complete_swap_material_probe_variants():
        variant_dir = root / variant.name
        variant_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = variant_dir / "cdmw_complete_swap_probe_profile.json"
        manifest = complete_swap_material_probe_manifest(
            variant.material_profile_name,
            source_package_path=source_package_path,
        )
        manifest["probe_variant"] = {
            "name": variant.name,
            "label": variant.label,
            "description": variant.description,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        written.append(manifest_path)
    return tuple(written)


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(bytes(data or b"")).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _probe_payload_items(payloads: Sequence[object]) -> tuple[tuple[str, bytes, str], ...]:
    items: list[tuple[str, bytes, str]] = []
    for payload in tuple(payloads or ()):
        target_path = str(getattr(payload, "target_path", "") or "").replace("\\", "/").strip()
        if not target_path and isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
            try:
                target_path = str(payload[0] or "").replace("\\", "/").strip()
            except Exception:
                target_path = ""
        if not target_path:
            continue
        raw_data = getattr(payload, "payload_data", None)
        if raw_data is None and isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
            try:
                raw_data = payload[1]
            except Exception:
                raw_data = b""
        data = raw_data.encode("utf-8") if isinstance(raw_data, str) else bytes(raw_data or b"")
        kind = str(getattr(payload, "kind", "") or "")
        items.append((target_path, data, kind))
    return tuple(items)


def write_complete_swap_material_probe_packages(
    output_root: Path | str,
    *,
    source_package_path: Path | str,
    target_pac_path: str = "",
    build_variant_payloads: Callable[[CDMaterialProbeVariant], Sequence[object]],
) -> CDMaterialProbePackageResult:
    """Write mod-ready complete-swap probe folders for all calibrated profiles."""

    source_package = Path(source_package_path).expanduser()
    if not source_package.is_file():
        raise FileNotFoundError(f"Complete swap probe source package is missing: {source_package}")
    root = Path(output_root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    source_hash = _hash_file(source_package)
    variant_dirs: list[Path] = []
    manifest_paths: list[Path] = []
    geometry_hash_by_variant: dict[str, str] = {}
    material_mask_hash_by_variant: dict[str, str] = {}
    for variant in complete_swap_material_probe_variants():
        payload_items = _probe_payload_items(tuple(build_variant_payloads(variant) or ()))
        if not payload_items:
            raise ValueError(f"Complete swap probe variant {variant.name} produced no package payloads.")
        variant_dir = root / variant.name
        files_dir = variant_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        payload_manifest: list[dict[str, object]] = []
        geometry_hashes: list[str] = []
        material_mask_hashes: list[str] = []
        for target_path, data, kind in payload_items:
            output_path = files_dir / PurePosixPath(target_path).as_posix()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(data)
            digest = _hash_bytes(data)
            lowered = target_path.lower()
            payload_manifest.append({"path": target_path, "kind": kind, "sha256": digest, "size": len(data)})
            if lowered.endswith((".pac", ".pab", ".pam", ".pamlod")):
                geometry_hashes.append(digest)
            if lowered.endswith(".dds") and ("_ma" in PurePosixPath(lowered).stem or "material_mask" in lowered):
                material_mask_hashes.append(digest)
        geometry_hash = hashlib.sha256("|".join(sorted(geometry_hashes)).encode("utf-8")).hexdigest() if geometry_hashes else ""
        material_mask_hash = hashlib.sha256("|".join(sorted(material_mask_hashes)).encode("utf-8")).hexdigest() if material_mask_hashes else ""
        if geometry_hash:
            geometry_hash_by_variant[variant.name] = geometry_hash
        if material_mask_hash:
            material_mask_hash_by_variant[variant.name] = material_mask_hash
        manifest = complete_swap_material_probe_manifest(
            variant.material_profile_name,
            source_package_path=source_package.as_posix(),
        )
        manifest.update(
            {
                "source_package_sha256": source_hash,
                "target_pac_path": str(target_pac_path or ""),
                "probe_variant": {
                    "name": variant.name,
                    "label": variant.label,
                    "description": variant.description,
                },
                "payloads": payload_manifest,
                "geometry_hash": geometry_hash,
                "material_mask_hash": material_mask_hash,
                "files_root": "files",
            }
        )
        manifest_path = variant_dir / "cdmw_complete_swap_probe_profile.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        variant_dirs.append(variant_dir)
        manifest_paths.append(manifest_path)
    distinct_geometry = {value for value in geometry_hash_by_variant.values() if value}
    if len(distinct_geometry) > 1:
        raise ValueError("Complete swap probe variants changed geometry; expected identical mesh payload hashes.")
    distinct_masks = {value for value in material_mask_hash_by_variant.values() if value}
    if len(material_mask_hash_by_variant) > 1 and len(distinct_masks) <= 1:
        raise ValueError("Complete swap probe variants did not produce distinct material-mask payloads.")
    return CDMaterialProbePackageResult(output_root=root, variant_dirs=tuple(variant_dirs), manifests=tuple(manifest_paths))


def _profile_base_binding_mode(material_profile: CDMaterialRuntimeProfile) -> str:
    mode = _sanitize_texture_component(str(getattr(material_profile, "base_binding_mode", "") or "overlay_texture"))
    aliases = {
        "overlay": "overlay_texture",
        "overlaytexture": "overlay_texture",
        "overlayfromcolorblendslot": "overlay_from_colorblend_slot",
        "colorblend": "overlay_from_colorblend_slot",
        "tint": "tint_only",
        "tintonly": "tint_only",
        "off": "disabled",
        "none": "disabled",
    }
    return aliases.get(mode, mode if mode in {"overlay_texture", "overlay_from_colorblend_slot", "tint_only", "disabled"} else "overlay_texture")


def _profile_mask_binding_mode(material_profile: CDMaterialRuntimeProfile) -> str:
    return material_profile_mask_binding_mode(material_profile)


def _profile_support_policy(material_profile: CDMaterialRuntimeProfile) -> str:
    return material_profile_support_policy(material_profile)


def _profile_is_source_only(material_profile: CDMaterialRuntimeProfile) -> bool:
    return _profile_support_policy(material_profile) == "source_only"


def _profile_is_material_authority_bruteforce(material_profile: CDMaterialRuntimeProfile) -> bool:
    return _sanitize_texture_component(str(getattr(material_profile, "name", "") or "")) in {
        "material_authority_bruteforce",
        "material_authority_bruteforce_tuned",
    }


def _profile_authority_contract(profile: Optional[CDMaterialRuntimeProfile]) -> str:
    return material_profile_authority_contract(profile)


def complete_swap_material_authority_contract(profile_name: str = "") -> str:
    """Return the final-package material authority contract for a runtime profile."""

    return _profile_authority_contract(get_complete_swap_material_profile(profile_name))


def complete_swap_material_allows_inherited_layer_color_bindings(profile_name: str = "") -> bool:
    return complete_swap_material_authority_contract(profile_name) == "runtime_xml_preserve"


def complete_swap_material_requires_true_source_authority(profile_name: str = "") -> bool:
    return complete_swap_material_authority_contract(profile_name).startswith("true_source_authority")


def _profile_is_runtime_xml(material_profile: Optional[CDMaterialRuntimeProfile]) -> bool:
    return material_profile_is_runtime_xml(material_profile)


def _profile_allows_factor_only_authority(material_profile: CDMaterialRuntimeProfile) -> bool:
    return bool(getattr(material_profile, "allow_factor_only_authority", False))


def _profile_bruteforce_texture_scope(material_profile: Optional[CDMaterialRuntimeProfile]) -> str:
    return _sanitize_texture_component(str(getattr(material_profile, "bruteforce_texture_scope", "") or "all")) or "all"


def _profile_forces_neutral_layer_support(material_profile: Optional[CDMaterialRuntimeProfile]) -> bool:
    return bool(getattr(material_profile, "force_neutral_layer_support", False))


def _profile_uses_factor_only_material_mask(material_profile: Optional[CDMaterialRuntimeProfile]) -> bool:
    return bool(getattr(material_profile, "factor_only_material_mask", False))


def _profile_preserves_target_layer_response(material_profile: Optional[CDMaterialRuntimeProfile]) -> bool:
    return bool(getattr(material_profile, "preserve_target_layer_response", False))


def _profile_applies_source_pbr_scalars_with_preserved_layers(material_profile: Optional[CDMaterialRuntimeProfile]) -> bool:
    return _sanitize_texture_component(str(getattr(material_profile, "name", "") or "")) == "material_authority_pbr_source_test"


def _profile_uses_detail_mask_material_contract(material_profile: Optional[CDMaterialRuntimeProfile]) -> bool:
    if material_profile is None:
        return False
    name = _sanitize_texture_component(str(getattr(material_profile, "name", "") or ""))
    contract = _sanitize_texture_component(str(getattr(material_profile, "authority_contract", "") or ""))
    return bool(
        name == "material_authority_detail_mask"
        or _profile_mask_binding_mode(material_profile) == "detail_mask_material"
        or contract in {"true_source_authority_detail_mask", "detail_mask_authority", "detailmaskauthority"}
    )


def _profile_routes_source_color_to_layer_slots(material_profile: Optional[CDMaterialRuntimeProfile]) -> bool:
    return bool(getattr(material_profile, "source_color_layer_authority", False))


def _profile_neutral_color_rgb(material_profile: Optional[CDMaterialRuntimeProfile]) -> Optional[tuple[int, int, int]]:
    if material_profile is None:
        return None
    raw = tuple(getattr(material_profile, "neutral_color_rgb", ()) or ())
    if len(raw) < 3:
        return None
    try:
        return tuple(max(0, min(255, int(component))) for component in raw[:3])  # type: ignore[return-value]
    except (TypeError, ValueError, OverflowError):
        return None


def _profile_base_color_lift(material_profile: Optional[CDMaterialRuntimeProfile]) -> int:
    if material_profile is None:
        return 0
    try:
        return max(0, min(254, int(getattr(material_profile, "base_color_lift", 0) or 0)))
    except (TypeError, ValueError, OverflowError):
        return 0


def _profile_base_color_gamma(material_profile: Optional[CDMaterialRuntimeProfile]) -> float:
    if material_profile is None:
        return 1.0
    raw = getattr(material_profile, "base_color_gamma", None)
    if raw is None:
        return 1.0
    try:
        return max(0.1, min(4.0, float(raw)))
    except (TypeError, ValueError, OverflowError):
        return 1.0


def _profile_base_color_saturation(material_profile: Optional[CDMaterialRuntimeProfile]) -> float:
    if material_profile is None:
        return 1.0
    raw = getattr(material_profile, "base_color_saturation", None)
    if raw is None:
        return 1.0
    try:
        return max(0.0, min(4.0, float(raw)))
    except (TypeError, ValueError, OverflowError):
        return 1.0


def _profile_optional_byte(material_profile: Optional[CDMaterialRuntimeProfile], field_name: str) -> Optional[int]:
    if material_profile is None:
        return None
    raw = getattr(material_profile, field_name, None)
    if raw is None:
        return None
    try:
        return max(0, min(255, int(raw)))
    except (TypeError, ValueError, OverflowError):
        return None


def _profile_optional_scale(material_profile: Optional[CDMaterialRuntimeProfile], field_name: str) -> Optional[float]:
    if material_profile is None:
        return None
    raw = getattr(material_profile, field_name, None)
    if raw is None:
        return None
    try:
        return max(0.0, min(4.0, float(raw)))
    except (TypeError, ValueError, OverflowError):
        return None


def _profile_displacement_scale_multiplier(material_profile: Optional[CDMaterialRuntimeProfile]) -> Optional[float]:
    if material_profile is None:
        return None
    raw = getattr(material_profile, "displacement_scale_multiplier", None)
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError, OverflowError):
        return None


def _profile_displacement_scale_max(material_profile: Optional[CDMaterialRuntimeProfile]) -> Optional[float]:
    if material_profile is None:
        return None
    raw = getattr(material_profile, "displacement_scale_max", None)
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError, OverflowError):
        return None


def _profile_roughness_inverted(material_profile: CDMaterialRuntimeProfile) -> bool:
    return _material_parameter_roughness_inverted(material_profile)


def _profile_metallic_inverted(material_profile: CDMaterialRuntimeProfile) -> bool:
    return _material_parameter_metallic_inverted(material_profile)


def _profile_ma_rgb_roles(material_profile: CDMaterialRuntimeProfile) -> tuple[str, str, str]:
    layout = _sanitize_texture_component(
        str(getattr(material_profile, "ma_layout", "") or getattr(material_profile, "material_mask_layout", "") or "arm")
    )
    aliases = {
        "ao_roughness_metallic_alpha": "arm",
        "aorm": "arm",
        "orm": "arm",
        "roughness_metallic_ao_alpha": "rma",
        "metallic_roughness_ao_alpha": "mra",
    }
    layout = aliases.get(layout, layout)
    if layout == "rma":
        return ("roughness", "metallic", "ao")
    if layout == "mra":
        return ("metallic", "roughness", "ao")
    return ("ao", "roughness", "metallic")


def _format_profile_color_hex(rgb: tuple[int, int, int], alpha: str = "ff") -> str:
    alpha_text = re.sub(r"[^0-9a-fA-F]+", "", str(alpha or "ff"))[:2] or "ff"
    if len(alpha_text) < 2:
        alpha_text = alpha_text.ljust(2, "f")
    return f"#{int(rgb[0]):02x}{int(rgb[1]):02x}{int(rgb[2]):02x}{alpha_text.lower()}"
