from __future__ import annotations

import re
from dataclasses import replace
from typing import Dict, List, Sequence, Tuple

from cdmw.constants import (
    DDS_FORMAT_MODE_MATCH_ORIGINAL,
    DDS_MIP_MODE_FULL_CHAIN,
    DDS_SIZE_MODE_PNG,
    UPSCALE_POST_CORRECTION_NONE,
    UPSCALE_POST_CORRECTION_SOURCE_MATCH_BALANCED,
)
from cdmw.models import TextureProcessingProfile, TextureRule, TextureWorkflowProfile

_SCALAR_HIGH_PRECISION_MASK_SUBTYPES = frozenset(
    {
        "mask",
        "ao",
        "grayscale_data",
        "opacity_mask",
        "detail_support",
        "metallic",
        "specular",
        "subsurface",
        "emissive_intensity",
    }
)

_DEFAULT_SEMANTIC_SUBTYPES: Dict[str, str] = {
    "color": "albedo",
    "ui": "ui",
    "emissive": "emissive",
    "impostor": "impostor",
    "normal": "normal",
    "world_normal": "normal",
    "height": "height",
    "vector": "vector",
    "roughness": "roughness",
    "gloss_or_smoothness": "roughness",
    "mask": "mask",
    "unknown": "unknown",
}

_SEMANTIC_OVERRIDE_TEXTURE_TYPES: Dict[str, str] = {
    "albedo": "color",
    "albedo_variant": "color",
    "ui": "ui",
    "emissive": "emissive",
    "impostor": "impostor",
    "normal": "normal",
    "height": "height",
    "displacement": "height",
    "bump": "height",
    "parallax_height": "height",
    "vector": "vector",
    "direction_vector": "vector",
    "effect_vector": "vector",
    "pivot_position": "vector",
    "flow_vector": "vector",
    "position_vector": "vector",
    "roughness": "roughness",
    "mask": "mask",
    "orm": "mask",
    "rma": "mask",
    "mra": "mask",
    "arm": "mask",
    "packed_mask": "mask",
    "opacity_mask": "mask",
    "material_mask": "mask",
    "material_response": "mask",
    "ao": "mask",
    "metallic": "mask",
    "specular": "mask",
    "detail_support": "mask",
    "subsurface": "mask",
    "emissive_intensity": "mask",
    "grayscale_data": "mask",
    "unknown": "unknown",
}

_PROFILE_TABLE: Dict[str, TextureProcessingProfile] = {
    "color_default": TextureProcessingProfile(
        key="color_default",
        label="Color Default",
        allowed_intermediate_kinds=("visible_color_png_path",),
        preferred_texconv_format="BC7_UNORM_SRGB",
        colorspace_policy="srgb",
        alpha_policy="straight",
        mip_policy_hint="standard_color",
    ),
    "color_cutout_alpha": TextureProcessingProfile(
        key="color_cutout_alpha",
        label="Color Cutout Alpha",
        allowed_intermediate_kinds=("visible_color_png_path",),
        preferred_texconv_format="BC7_UNORM_SRGB",
        colorspace_policy="srgb",
        alpha_policy="cutout_coverage",
        mip_policy_hint="keep_coverage",
    ),
    "ui_alpha": TextureProcessingProfile(
        key="ui_alpha",
        label="UI Alpha",
        allowed_intermediate_kinds=("visible_color_png_path",),
        preferred_texconv_format="BC7_UNORM_SRGB",
        colorspace_policy="srgb",
        alpha_policy="straight",
        mip_policy_hint="ui_alpha_safe",
    ),
    "normal_bc5": TextureProcessingProfile(
        key="normal_bc5",
        label="Normal BC5",
        allowed_intermediate_kinds=("technical_preserve_path",),
        preferred_texconv_format="BC5_UNORM",
        colorspace_policy="linear",
        alpha_policy="none",
        mip_policy_hint="normal_linear",
        preserve_only=True,
    ),
    "scalar_bc4": TextureProcessingProfile(
        key="scalar_bc4",
        label="Scalar BC4",
        allowed_intermediate_kinds=("technical_preserve_path",),
        preferred_texconv_format="BC4_UNORM",
        colorspace_policy="linear",
        alpha_policy="none",
        mip_policy_hint="scalar_linear",
        preserve_only=True,
    ),
    "scalar_high_precision_bc4": TextureProcessingProfile(
        key="scalar_high_precision_bc4",
        label="Scalar High Precision BC4",
        allowed_intermediate_kinds=("technical_high_precision_path",),
        preferred_texconv_format="BC4_UNORM",
        colorspace_policy="linear",
        alpha_policy="none",
        mip_policy_hint="scalar_high_precision",
        preserve_only=False,
    ),
    "packed_mask_preserve_layout": TextureProcessingProfile(
        key="packed_mask_preserve_layout",
        label="Packed Mask Preserve Layout",
        allowed_intermediate_kinds=("technical_preserve_path",),
        preferred_texconv_format="MATCH_ORIGINAL",
        colorspace_policy="linear",
        alpha_policy="channel_data",
        mip_policy_hint="preserve_channels",
        preserve_only=True,
    ),
    "premultiplied_alpha_review_required": TextureProcessingProfile(
        key="premultiplied_alpha_review_required",
        label="Premultiplied Alpha Review Required",
        allowed_intermediate_kinds=("technical_preserve_path",),
        preferred_texconv_format="MATCH_ORIGINAL",
        colorspace_policy="match_source",
        alpha_policy="premultiplied",
        mip_policy_hint="review_required",
        preserve_only=True,
    ),
    "float_or_vector_preserve_only": TextureProcessingProfile(
        key="float_or_vector_preserve_only",
        label="Float Or Vector Preserve Only",
        allowed_intermediate_kinds=("technical_preserve_path",),
        preferred_texconv_format="MATCH_ORIGINAL",
        colorspace_policy="match_source",
        alpha_policy="none",
        mip_policy_hint="preserve_precision",
        preserve_only=True,
    ),
}


def get_texture_processing_profile_keys() -> Tuple[str, ...]:
    return tuple(sorted(_PROFILE_TABLE))


def upgrade_default_texture_workflow_state(
    workflow_profiles: Sequence[TextureWorkflowProfile],
    texture_rules: Sequence[TextureRule],
) -> Tuple[Tuple[TextureWorkflowProfile, ...], Tuple[TextureRule, ...]]:
    current_profiles = {profile.profile_id: profile for profile in build_default_texture_workflow_profiles()}
    legacy_profiles = {profile.profile_id: profile for profile in _build_legacy_default_texture_workflow_profiles()}
    pre_conservative_specular_profiles = {
        profile.profile_id: profile for profile in _build_pre_conservative_specular_texture_workflow_profiles()
    }
    pre_inherit_scale_profiles = {
        profile.profile_id: profile for profile in _build_pre_inherit_scale_texture_workflow_profiles()
    }
    pre_conservative_technical_profiles = {
        profile.profile_id: profile for profile in _build_pre_conservative_technical_texture_workflow_profiles()
    }
    upgraded_profiles: List[TextureWorkflowProfile] = []
    profiles_changed = False
    for profile in workflow_profiles:
        replacement = current_profiles.get(profile.profile_id)
        legacy = legacy_profiles.get(profile.profile_id)
        pre_conservative_specular = pre_conservative_specular_profiles.get(profile.profile_id)
        pre_inherit_scale = pre_inherit_scale_profiles.get(profile.profile_id)
        pre_conservative_technical = pre_conservative_technical_profiles.get(profile.profile_id)
        if replacement is not None and (
            (legacy is not None and profile == legacy)
            or (pre_conservative_specular is not None and profile == pre_conservative_specular)
            or (pre_inherit_scale is not None and profile == pre_inherit_scale)
            or (pre_conservative_technical is not None and profile == pre_conservative_technical)
        ):
            upgraded_profiles.append(replacement)
            profiles_changed = True
        else:
            upgraded_profiles.append(profile)

    current_rules = {rule.pattern: rule for rule in build_default_texture_workflow_rules()}
    legacy_rules = {rule.pattern: rule for rule in _build_legacy_default_texture_workflow_rules()}
    pre_conservative_technical_rules = {
        rule.pattern: rule for rule in _build_pre_conservative_technical_texture_workflow_rules()
    }
    upgraded_rules: List[TextureRule] = []
    rules_changed = False
    for rule in texture_rules:
        replacement = current_rules.get(rule.pattern)
        legacy = legacy_rules.get(rule.pattern)
        pre_conservative_technical = pre_conservative_technical_rules.get(rule.pattern)
        if replacement is not None and (
            (legacy is not None and rule == legacy)
            or (pre_conservative_technical is not None and rule == pre_conservative_technical)
        ):
            upgraded_rules.append(replacement)
            rules_changed = True
        else:
            upgraded_rules.append(rule)

    upgraded_rule_by_pattern = {str(rule.pattern or "").strip().lower(): rule for rule in upgraded_rules}
    if "*_disp.dds" not in upgraded_rule_by_pattern:
        starter_height_rule_variants = tuple(
            rule
            for rule in (
                current_rules.get("*_d.dds"),
                legacy_rules.get("*_d.dds"),
            )
            if rule is not None
        )
        existing_height_rule = upgraded_rule_by_pattern.get("*_d.dds")
        if existing_height_rule is not None and any(existing_height_rule == variant for variant in starter_height_rule_variants):
            disp_rule = current_rules.get("*_disp.dds")
            if disp_rule is not None:
                upgraded_rules.append(disp_rule)
                rules_changed = True

    if not profiles_changed and not rules_changed:
        return tuple(workflow_profiles), tuple(texture_rules)
    return tuple(upgraded_profiles), tuple(upgraded_rules)


def _is_blank_workflow_profile_placeholder(profile: TextureWorkflowProfile) -> bool:
    if not re.fullmatch(r"Profile(?:\s+\d+)?", str(profile.label or "").strip(), flags=re.IGNORECASE):
        return False
    return not any(
        [
            str(profile.action_mode or "").strip(),
            str(profile.format_value or "").strip(),
            str(profile.size_value or "").strip(),
            str(profile.mip_value or "").strip(),
            str(profile.ncnn_model_name or "").strip(),
            profile.ncnn_scale is not None,
            profile.ncnn_tile_size is not None,
            str(profile.ncnn_extra_args or "").strip(),
            str(profile.post_correction_mode or "").strip(),
        ]
    )


def _is_blank_workflow_rule_placeholder(rule: TextureRule) -> bool:
    return (
        str(rule.pattern or "").strip().lower() == "*.dds"
        and bool(rule.enabled)
        and str(rule.match_mode or "glob").strip().lower() == "glob"
        and str(rule.action or "process").strip().lower() == "process"
        and not any(
            [
                str(rule.format_value or "").strip(),
                str(rule.size_value or "").strip(),
                str(rule.mip_value or "").strip(),
                str(rule.semantic_value or "").strip(),
                str(rule.profile_value or "").strip(),
                str(rule.colorspace_value or "").strip(),
                str(rule.alpha_policy_value or "").strip(),
                str(rule.intermediate_value or "").strip(),
                str(rule.workflow_profile_id or "").strip(),
            ]
        )
    )


def should_seed_default_texture_workflow_state(
    workflow_profiles: Sequence[TextureWorkflowProfile],
    texture_rules: Sequence[TextureRule],
) -> bool:
    if not workflow_profiles and not texture_rules:
        return True
    if len(texture_rules) == 1 and _is_blank_workflow_rule_placeholder(texture_rules[0]):
        if not workflow_profiles:
            return True
        if len(workflow_profiles) == 1 and _is_blank_workflow_profile_placeholder(workflow_profiles[0]):
            return True
    return False


def build_default_texture_workflow_profiles() -> Tuple[TextureWorkflowProfile, ...]:
    return (
        TextureWorkflowProfile(
            profile_id="starter_color_albedo",
            label="Starter Color / Albedo",
            action_mode="upscale_then_rebuild",
            size_value=DDS_SIZE_MODE_PNG,
            mip_value=DDS_MIP_MODE_FULL_CHAIN,
            post_correction_mode=UPSCALE_POST_CORRECTION_SOURCE_MATCH_BALANCED,
        ),
        TextureWorkflowProfile(
            profile_id="starter_normal_map",
            label="Starter Normal",
            action_mode="preserve_original",
            format_value="BC5_UNORM",
            size_value=DDS_SIZE_MODE_PNG,
            mip_value=DDS_MIP_MODE_FULL_CHAIN,
            post_correction_mode=UPSCALE_POST_CORRECTION_NONE,
        ),
        TextureWorkflowProfile(
            profile_id="starter_height_displacement",
            label="Starter Height / Displacement",
            action_mode="preserve_original",
            format_value=DDS_FORMAT_MODE_MATCH_ORIGINAL,
            size_value=DDS_SIZE_MODE_PNG,
            mip_value=DDS_MIP_MODE_FULL_CHAIN,
            post_correction_mode=UPSCALE_POST_CORRECTION_NONE,
        ),
        TextureWorkflowProfile(
            profile_id="starter_specular",
            label="Starter Specular",
            action_mode="preserve_original",
            format_value=DDS_FORMAT_MODE_MATCH_ORIGINAL,
            size_value=DDS_SIZE_MODE_PNG,
            mip_value=DDS_MIP_MODE_FULL_CHAIN,
            post_correction_mode=UPSCALE_POST_CORRECTION_NONE,
        ),
    )


def build_default_texture_workflow_rules() -> Tuple[TextureRule, ...]:
    return (
        TextureRule(
            pattern="*.dds",
            enabled=True,
            match_mode="glob",
            workflow_profile_id="starter_color_albedo",
            colorspace_value="match_source",
            alpha_policy_value="straight",
            intermediate_value="visible_color_png_path",
            source_line="default starter rule: *.dds",
        ),
        TextureRule(
            pattern="*_n.dds",
            enabled=True,
            match_mode="glob",
            workflow_profile_id="starter_normal_map",
            semantic_value="normal:normal",
            profile_value="normal_bc5",
            colorspace_value="linear",
            alpha_policy_value="none",
            intermediate_value="technical_preserve_path",
            source_line="default starter rule: *_n.dds",
        ),
        TextureRule(
            pattern="*_d.dds",
            enabled=True,
            match_mode="glob",
            workflow_profile_id="starter_height_displacement",
            semantic_value="height:displacement",
            profile_value="scalar_high_precision_bc4",
            colorspace_value="linear",
            alpha_policy_value="none",
            intermediate_value="technical_high_precision_path",
            source_line="default starter rule: *_d.dds",
        ),
        TextureRule(
            pattern="*_disp.dds",
            enabled=True,
            match_mode="glob",
            workflow_profile_id="starter_height_displacement",
            semantic_value="height:displacement",
            profile_value="scalar_high_precision_bc4",
            colorspace_value="linear",
            alpha_policy_value="none",
            intermediate_value="technical_high_precision_path",
            source_line="default starter rule: *_disp.dds",
        ),
        TextureRule(
            pattern="*_sp.dds",
            enabled=True,
            match_mode="glob",
            workflow_profile_id="starter_specular",
            semantic_value="mask:specular",
            profile_value="scalar_bc4",
            colorspace_value="linear",
            alpha_policy_value="none",
            intermediate_value="technical_preserve_path",
            source_line="default starter rule: *_sp.dds",
        ),
    )


def _build_legacy_default_texture_workflow_profiles() -> Tuple[TextureWorkflowProfile, ...]:
    return (
        TextureWorkflowProfile(
            profile_id="starter_color_albedo",
            label="Starter Color / Albedo",
            action_mode="upscale_then_rebuild",
            format_value="BC7_UNORM_SRGB",
            size_value=DDS_SIZE_MODE_PNG,
            mip_value=DDS_MIP_MODE_FULL_CHAIN,
            ncnn_scale=4,
            post_correction_mode=UPSCALE_POST_CORRECTION_SOURCE_MATCH_BALANCED,
        ),
        TextureWorkflowProfile(
            profile_id="starter_normal_map",
            label="Starter Normal",
            action_mode="upscale_then_rebuild",
            format_value="BC5_UNORM",
            size_value=DDS_SIZE_MODE_PNG,
            mip_value=DDS_MIP_MODE_FULL_CHAIN,
            ncnn_scale=2,
            post_correction_mode=UPSCALE_POST_CORRECTION_NONE,
        ),
        TextureWorkflowProfile(
            profile_id="starter_height_displacement",
            label="Starter Height / Displacement",
            action_mode="upscale_then_rebuild",
            format_value="BC4_UNORM",
            size_value=DDS_SIZE_MODE_PNG,
            mip_value=DDS_MIP_MODE_FULL_CHAIN,
            ncnn_scale=2,
            post_correction_mode=UPSCALE_POST_CORRECTION_NONE,
        ),
        TextureWorkflowProfile(
            profile_id="starter_specular",
            label="Starter Specular",
            action_mode="upscale_then_rebuild",
            format_value="BC4_UNORM",
            size_value=DDS_SIZE_MODE_PNG,
            mip_value=DDS_MIP_MODE_FULL_CHAIN,
            ncnn_scale=2,
            post_correction_mode=UPSCALE_POST_CORRECTION_NONE,
        ),
    )


def _build_pre_conservative_specular_texture_workflow_profiles() -> Tuple[TextureWorkflowProfile, ...]:
    profiles = list(build_default_texture_workflow_profiles())
    for index, profile in enumerate(profiles):
        if profile.profile_id == "starter_specular":
            profiles[index] = replace(profile, format_value="BC4_UNORM")
            break
    return tuple(profiles)


def _build_pre_inherit_scale_texture_workflow_profiles() -> Tuple[TextureWorkflowProfile, ...]:
    return (
        TextureWorkflowProfile(
            profile_id="starter_color_albedo",
            label="Starter Color / Albedo",
            action_mode="upscale_then_rebuild",
            size_value=DDS_SIZE_MODE_PNG,
            mip_value=DDS_MIP_MODE_FULL_CHAIN,
            ncnn_scale=4,
            post_correction_mode=UPSCALE_POST_CORRECTION_SOURCE_MATCH_BALANCED,
        ),
        TextureWorkflowProfile(
            profile_id="starter_normal_map",
            label="Starter Normal",
            action_mode="upscale_then_rebuild",
            format_value="BC5_UNORM",
            size_value=DDS_SIZE_MODE_PNG,
            mip_value=DDS_MIP_MODE_FULL_CHAIN,
            ncnn_scale=2,
            post_correction_mode=UPSCALE_POST_CORRECTION_NONE,
        ),
        TextureWorkflowProfile(
            profile_id="starter_height_displacement",
            label="Starter Height / Displacement",
            action_mode="upscale_then_rebuild",
            format_value="BC4_UNORM",
            size_value=DDS_SIZE_MODE_PNG,
            mip_value=DDS_MIP_MODE_FULL_CHAIN,
            ncnn_scale=2,
            post_correction_mode=UPSCALE_POST_CORRECTION_NONE,
        ),
        TextureWorkflowProfile(
            profile_id="starter_specular",
            label="Starter Specular",
            action_mode="upscale_then_rebuild",
            format_value=DDS_FORMAT_MODE_MATCH_ORIGINAL,
            size_value=DDS_SIZE_MODE_PNG,
            mip_value=DDS_MIP_MODE_FULL_CHAIN,
            ncnn_scale=2,
            post_correction_mode=UPSCALE_POST_CORRECTION_NONE,
        ),
    )


def _build_pre_conservative_technical_texture_workflow_profiles() -> Tuple[TextureWorkflowProfile, ...]:
    return (
        TextureWorkflowProfile(
            profile_id="starter_color_albedo",
            label="Starter Color / Albedo",
            action_mode="upscale_then_rebuild",
            size_value=DDS_SIZE_MODE_PNG,
            mip_value=DDS_MIP_MODE_FULL_CHAIN,
            post_correction_mode=UPSCALE_POST_CORRECTION_SOURCE_MATCH_BALANCED,
        ),
        TextureWorkflowProfile(
            profile_id="starter_normal_map",
            label="Starter Normal",
            action_mode="upscale_then_rebuild",
            format_value="BC5_UNORM",
            size_value=DDS_SIZE_MODE_PNG,
            mip_value=DDS_MIP_MODE_FULL_CHAIN,
            post_correction_mode=UPSCALE_POST_CORRECTION_NONE,
        ),
        TextureWorkflowProfile(
            profile_id="starter_height_displacement",
            label="Starter Height / Displacement",
            action_mode="upscale_then_rebuild",
            format_value="BC4_UNORM",
            size_value=DDS_SIZE_MODE_PNG,
            mip_value=DDS_MIP_MODE_FULL_CHAIN,
            post_correction_mode=UPSCALE_POST_CORRECTION_NONE,
        ),
        TextureWorkflowProfile(
            profile_id="starter_specular",
            label="Starter Specular",
            action_mode="upscale_then_rebuild",
            format_value=DDS_FORMAT_MODE_MATCH_ORIGINAL,
            size_value=DDS_SIZE_MODE_PNG,
            mip_value=DDS_MIP_MODE_FULL_CHAIN,
            post_correction_mode=UPSCALE_POST_CORRECTION_NONE,
        ),
    )


def _build_legacy_default_texture_workflow_rules() -> Tuple[TextureRule, ...]:
    return (
        TextureRule(
            pattern="*.dds",
            enabled=True,
            match_mode="glob",
            workflow_profile_id="starter_color_albedo",
            profile_value="color_default",
            colorspace_value="srgb",
            alpha_policy_value="straight",
            intermediate_value="visible_color_png_path",
            source_line="default starter rule: *.dds",
        ),
        TextureRule(
            pattern="*_n.dds",
            enabled=True,
            match_mode="glob",
            workflow_profile_id="starter_normal_map",
            semantic_value="normal:normal",
            profile_value="normal_bc5",
            colorspace_value="linear",
            alpha_policy_value="none",
            intermediate_value="visible_color_png_path",
            source_line="default starter rule: *_n.dds",
        ),
        TextureRule(
            pattern="*_d.dds",
            enabled=True,
            match_mode="glob",
            workflow_profile_id="starter_height_displacement",
            semantic_value="height:displacement",
            profile_value="scalar_high_precision_bc4",
            colorspace_value="linear",
            alpha_policy_value="none",
            intermediate_value="visible_color_png_path",
            source_line="default starter rule: *_d.dds",
        ),
        TextureRule(
            pattern="*_sp.dds",
            enabled=True,
            match_mode="glob",
            workflow_profile_id="starter_specular",
            semantic_value="mask:specular",
            profile_value="scalar_bc4",
            colorspace_value="linear",
            alpha_policy_value="none",
            intermediate_value="visible_color_png_path",
            source_line="default starter rule: *_sp.dds",
        ),
    )


def _build_pre_conservative_technical_texture_workflow_rules() -> Tuple[TextureRule, ...]:
    return (
        TextureRule(
            pattern="*.dds",
            enabled=True,
            match_mode="glob",
            workflow_profile_id="starter_color_albedo",
            colorspace_value="match_source",
            alpha_policy_value="straight",
            intermediate_value="visible_color_png_path",
            source_line="default starter rule: *.dds",
        ),
        TextureRule(
            pattern="*_n.dds",
            enabled=True,
            match_mode="glob",
            workflow_profile_id="starter_normal_map",
            semantic_value="normal:normal",
            profile_value="normal_bc5",
            colorspace_value="linear",
            alpha_policy_value="none",
            intermediate_value="visible_color_png_path",
            source_line="default starter rule: *_n.dds",
        ),
        TextureRule(
            pattern="*_d.dds",
            enabled=True,
            match_mode="glob",
            workflow_profile_id="starter_height_displacement",
            semantic_value="height:displacement",
            profile_value="scalar_high_precision_bc4",
            colorspace_value="linear",
            alpha_policy_value="none",
            intermediate_value="visible_color_png_path",
            source_line="default starter rule: *_d.dds",
        ),
        TextureRule(
            pattern="*_disp.dds",
            enabled=True,
            match_mode="glob",
            workflow_profile_id="starter_height_displacement",
            semantic_value="height:displacement",
            profile_value="scalar_high_precision_bc4",
            colorspace_value="linear",
            alpha_policy_value="none",
            intermediate_value="visible_color_png_path",
            source_line="default starter rule: *_disp.dds",
        ),
        TextureRule(
            pattern="*_sp.dds",
            enabled=True,
            match_mode="glob",
            workflow_profile_id="starter_specular",
            semantic_value="mask:specular",
            profile_value="scalar_bc4",
            colorspace_value="linear",
            alpha_policy_value="none",
            intermediate_value="visible_color_png_path",
            source_line="default starter rule: *_sp.dds",
        ),
    )
