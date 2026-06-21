"""Pure DDS output-setting rules for texture workflows."""

from __future__ import annotations

import math
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from cdmw.constants import (
    DDS_FORMAT_MODE_MATCH_ORIGINAL,
    DDS_MIP_MODE_CUSTOM,
    DDS_MIP_MODE_FULL_CHAIN,
    DDS_MIP_MODE_MATCH_ORIGINAL,
    DDS_MIP_MODE_SINGLE,
    DDS_SIZE_MODE_CUSTOM,
    DDS_SIZE_MODE_ORIGINAL,
    DDS_SIZE_MODE_PNG,
    UPSCALE_BACKEND_NONE,
    UPSCALE_BACKEND_REALESRGAN_NCNN,
)
from cdmw.core.upscale_profiles import (
    TextureUpscaleDecision,
    is_png_intermediate_high_risk,
    suggest_texture_upscale_decision,
)
from cdmw.models import (
    DdsInfo,
    DdsOutputSettings,
    NormalizedConfig,
    TextureProcessingPlan,
    TextureRule,
    TextureWorkflowDdsOverride,
)

_VISIBLE_COLOR_TEXTURE_TYPES = frozenset({"color", "ui", "emissive", "impostor"})


def max_mips_for_size(width: int, height: int) -> int:
    return int(math.floor(math.log2(max(width, height)))) + 1


def _srgb_variant(texconv_format: str) -> str:
    mapping = {
        "R8G8B8A8_UNORM": "R8G8B8A8_UNORM_SRGB",
        "B8G8R8A8_UNORM": "B8G8R8A8_UNORM_SRGB",
        "BC1_UNORM": "BC1_UNORM_SRGB",
        "BC2_UNORM": "BC2_UNORM_SRGB",
        "BC3_UNORM": "BC3_UNORM_SRGB",
        "BC7_UNORM": "BC7_UNORM_SRGB",
    }
    return mapping.get(texconv_format, texconv_format)


def _linear_variant(texconv_format: str) -> str:
    mapping = {
        "R8G8B8A8_UNORM_SRGB": "R8G8B8A8_UNORM",
        "B8G8R8A8_UNORM_SRGB": "B8G8R8A8_UNORM",
        "BC1_UNORM_SRGB": "BC1_UNORM",
        "BC2_UNORM_SRGB": "BC2_UNORM",
        "BC3_UNORM_SRGB": "BC3_UNORM",
        "BC7_UNORM_SRGB": "BC7_UNORM",
    }
    return mapping.get(texconv_format, texconv_format)


def apply_texture_workflow_output_override(
    settings: DdsOutputSettings,
    override: TextureWorkflowDdsOverride,
    *,
    dds_info: DdsInfo,
    note_label: str,
) -> DdsOutputSettings:
    next_settings = DdsOutputSettings(
        texconv_format=settings.texconv_format,
        mip_count=settings.mip_count,
        width=settings.width,
        height=settings.height,
        resize_to_dimensions=settings.resize_to_dimensions,
        notes=list(settings.notes),
        texconv_color_args=list(settings.texconv_color_args),
        texconv_extra_args=list(settings.texconv_extra_args),
    )

    if override.format_value:
        if override.format_value == DDS_FORMAT_MODE_MATCH_ORIGINAL:
            next_settings.texconv_format = dds_info.texconv_format
        else:
            next_settings.texconv_format = override.format_value
    if override.size_value:
        if override.size_value == DDS_SIZE_MODE_PNG:
            next_settings.resize_to_dimensions = False
        elif override.size_value == DDS_SIZE_MODE_ORIGINAL:
            next_settings.width = dds_info.width
            next_settings.height = dds_info.height
            next_settings.resize_to_dimensions = True
        else:
            width_text, height_text = override.size_value.lower().split("x", 1)
            next_settings.width = int(width_text)
            next_settings.height = int(height_text)
            next_settings.resize_to_dimensions = True
    if override.mip_value:
        max_possible_mips = max_mips_for_size(next_settings.width, next_settings.height)
        if override.mip_value == DDS_MIP_MODE_MATCH_ORIGINAL:
            next_settings.mip_count = min(dds_info.mip_count, max_possible_mips)
        elif override.mip_value == DDS_MIP_MODE_FULL_CHAIN:
            next_settings.mip_count = max_mips_for_size(next_settings.width, next_settings.height)
        elif override.mip_value == DDS_MIP_MODE_SINGLE:
            next_settings.mip_count = 1
        elif override.mip_value not in {DDS_MIP_MODE_MATCH_ORIGINAL, DDS_MIP_MODE_FULL_CHAIN, DDS_MIP_MODE_SINGLE}:
            next_settings.mip_count = int(override.mip_value)

    if override.format_value or override.size_value or override.mip_value:
        next_settings.notes.append(note_label)
    return next_settings


def _resolve_plan_output_settings(
    normalized: NormalizedConfig,
    plan: TextureProcessingPlan,
    png_width: int,
    png_height: int,
    *,
    has_alpha: bool,
) -> DdsOutputSettings:
    output_settings = resolve_dds_output_settings(normalized, plan.dds_info, png_width, png_height)
    explicit_output_format_override = str(plan.effective_output_override.format_value or "").strip().lower()
    if plan.workflow_profile is not None and (
        plan.effective_output_override.format_value
        or plan.effective_output_override.size_value
        or plan.effective_output_override.mip_value
    ):
        output_settings = apply_texture_workflow_output_override(
            output_settings,
            plan.effective_output_override,
            dds_info=plan.dds_info,
            note_label=f"workflow profile matched: {plan.workflow_profile.label}",
        )
    elif plan.effective_output_override.format_value or plan.effective_output_override.size_value or plan.effective_output_override.mip_value:
        output_settings = apply_texture_workflow_output_override(
            output_settings,
            plan.effective_output_override,
            dds_info=plan.dds_info,
            note_label="workflow override applied",
        )
    explicit_profile_override = bool(
        plan.matched_rule is not None and str(plan.matched_rule.profile_value or "").strip()
    )
    if normalized.enable_automatic_texture_rules:
        output_settings = apply_automatic_texture_rule_adjustments(
            output_settings,
            plan.relative_path,
            plan.dds_info,
            has_alpha=has_alpha,
            preset=normalized.upscale_texture_preset,
            intermediate_kind=plan.path_kind,
            semantic_decision=plan.decision,
            allow_auto_format_override=(
                plan.path_kind == "technical_high_precision_path" and explicit_output_format_override == ""
            ),
            prefer_manual_visible_format=(
                normalized.dds_format_mode == DDS_FORMAT_MODE_MATCH_ORIGINAL
                and explicit_output_format_override == ""
                and not explicit_profile_override
            ),
        )

    allow_profile_format_override = (
        plan.profile.preferred_texconv_format not in {"", "MATCH_ORIGINAL"}
        and explicit_output_format_override == ""
        and (
            explicit_profile_override
            or plan.path_kind == "technical_high_precision_path"
        )
    )
    if allow_profile_format_override:
        output_settings.texconv_format = plan.profile.preferred_texconv_format
    elif (
        plan.profile.preferred_texconv_format not in {"", "MATCH_ORIGINAL"}
        and normalized.dds_format_mode == DDS_FORMAT_MODE_MATCH_ORIGINAL
        and not normalized.enable_automatic_texture_rules
        and explicit_output_format_override == ""
        and not explicit_profile_override
    ):
        output_settings.notes.append(
            f"planner profile suggests {plan.profile.preferred_texconv_format}, but manual Match original DDS format remains in effect because automatic color/format rules are disabled."
        )
    elif (
        plan.profile.preferred_texconv_format not in {"", "MATCH_ORIGINAL"}
        and plan.path_kind != "technical_high_precision_path"
        and explicit_output_format_override == ""
        and not explicit_profile_override
        and output_settings.texconv_format != plan.profile.preferred_texconv_format
    ):
        output_settings.notes.append(
            f"planner profile suggests {plan.profile.preferred_texconv_format}, but the explicit DDS Output format setting remains in effect."
        )
    output_settings.notes.append(f"planner profile: {plan.profile.key}")
    output_settings.notes.append(f"planner path: {plan.path_kind}")
    output_settings.notes.append(f"planner alpha policy: {plan.alpha_policy}")
    if plan.path_kind == "technical_high_precision_path":
        output_settings.notes.append(
            "planner path detail: expects a 16-bit grayscale-style PNG intermediate and falls back to preserving the original DDS if that intermediate is missing or invalid."
        )
    if plan.lossy_intermediate_warning:
        output_settings.notes.append(plan.lossy_intermediate_warning)
    return output_settings


def apply_automatic_texture_rule_adjustments(
    output_settings: DdsOutputSettings,
    rel_path: Path,
    dds_info: DdsInfo,
    *,
    has_alpha: bool,
    preset: str,
    intermediate_kind: str = "visible_color_png_path",
    sidecar_texts: Sequence[str] = (),
    semantic_decision: Optional[TextureUpscaleDecision] = None,
    allow_auto_format_override: bool = True,
    prefer_manual_visible_format: bool = False,
) -> DdsOutputSettings:
    decision = semantic_decision or suggest_texture_upscale_decision(
        rel_path.as_posix(),
        preset=preset,
        original_texconv_format=dds_info.texconv_format,
        has_alpha=has_alpha,
        sidecar_texts=sidecar_texts,
        enable_automatic_rules=True,
    )
    next_settings = DdsOutputSettings(
        texconv_format=output_settings.texconv_format,
        mip_count=output_settings.mip_count,
        width=output_settings.width,
        height=output_settings.height,
        resize_to_dimensions=output_settings.resize_to_dimensions,
        notes=list(output_settings.notes),
        texconv_color_args=list(output_settings.texconv_color_args),
        texconv_extra_args=list(output_settings.texconv_extra_args),
    )
    current_format = next_settings.texconv_format.upper()
    recommended = decision.recommended_texconv_format.upper()
    preserve_visible_format = (
        prefer_manual_visible_format
        and decision.texture_type in _VISIBLE_COLOR_TEXTURE_TYPES
    )

    updated_format = current_format
    if decision.texture_type in {"color", "ui", "emissive", "impostor"}:
        if allow_auto_format_override and not preserve_visible_format:
            srgb_candidate = _srgb_variant(current_format)
            if srgb_candidate != current_format:
                updated_format = srgb_candidate
            elif current_format == dds_info.texconv_format.upper() and recommended.endswith("_SRGB"):
                updated_format = recommended
    elif decision.texture_type == "normal" and allow_auto_format_override:
        if current_format.endswith("_SRGB") or current_format not in {"BC5_UNORM", "BC5_SNORM"}:
            updated_format = recommended
    elif decision.texture_type == "height" and allow_auto_format_override:
        linear_candidate = _linear_variant(current_format)
        if "FLOAT" in dds_info.texconv_format.upper():
            updated_format = dds_info.texconv_format.upper()
        elif linear_candidate != current_format:
            updated_format = linear_candidate
        elif current_format.endswith("_SRGB") or current_format not in {"BC4_UNORM", "BC4_SNORM", "R8G8B8A8_UNORM", "B8G8R8A8_UNORM"}:
            updated_format = recommended
    elif decision.texture_type == "vector" and allow_auto_format_override:
        linear_candidate = _linear_variant(current_format)
        if "FLOAT" in dds_info.texconv_format.upper():
            updated_format = dds_info.texconv_format.upper()
        elif linear_candidate != current_format:
            updated_format = linear_candidate
        elif current_format.endswith("_SRGB") or current_format != dds_info.texconv_format.upper():
            updated_format = recommended
    elif decision.texture_type == "roughness" and allow_auto_format_override:
        if current_format.endswith("_SRGB") or current_format not in {"BC4_UNORM", "BC4_SNORM"}:
            updated_format = recommended
    elif decision.texture_type == "mask" and allow_auto_format_override:
        linear_candidate = _linear_variant(current_format)
        if linear_candidate != current_format:
            updated_format = linear_candidate
        elif current_format.endswith("_SRGB"):
            updated_format = recommended

    if updated_format != current_format:
        next_settings.texconv_format = updated_format
        next_settings.notes.append(
            f"automatic texture rule: {decision.texture_type}/{decision.semantic_subtype} -> {updated_format}"
        )
    elif not allow_auto_format_override:
        next_settings.notes.append(
            f"automatic texture rule: keeping explicit DDS Output format {current_format}; safety rules are limited to path, alpha, and colorspace handling for this file."
        )
    elif preserve_visible_format:
        next_settings.notes.append(
            f"automatic texture rule: preserved original visible-texture format {current_format} to avoid unintended luminance shifts under manual Match original DDS format."
        )
    next_settings.texconv_color_args.clear()
    if decision.recommended_colorspace == "linear":
        next_settings.texconv_color_args.extend(["--ignore-srgb"])
    elif decision.recommended_colorspace == "srgb":
        next_settings.notes.append(
            "auto-rule: visible texture rebuild keeps PNG pixel values as-is and avoids extra texconv sRGB conversion flags to reduce luminance drift."
        )

    next_settings.texconv_extra_args = [
        arg
        for arg in next_settings.texconv_extra_args
        if str(arg).strip().lower() not in {
            "-sepalpha",
            "--separate-alpha",
            "--keep-coverage",
            "-pmalpha",
            "--premultiplied-alpha",
        }
    ]
    if decision.alpha_mode in {"cutout"} and next_settings.mip_count > 1:
        next_settings.texconv_extra_args.extend(["--keep-coverage", "0.5"])
        next_settings.notes.append("auto-rule: alpha-tested cutout texture will preserve alpha coverage during mip generation.")
    if decision.alpha_mode == "channel_data" and decision.preserve_alpha:
        next_settings.texconv_extra_args.append("--separate-alpha")
        next_settings.notes.append("auto-rule: alpha channel appears to store data, so separate-alpha mip handling is enabled.")
    if decision.alpha_mode == "premultiplied":
        next_settings.notes.append("auto-rule: possible premultiplied alpha detected; verify final blend behavior manually.")

    for note in decision.notes:
        prefixed = f"auto-rule: {note}"
        if prefixed not in next_settings.notes:
            next_settings.notes.append(prefixed)
    if decision.texture_type in {"height", "vector"}:
        if output_settings.width != dds_info.width or output_settings.height != dds_info.height:
            next_settings.notes.append(
                f"auto-rule: {decision.texture_type} map is using resized PNG dimensions; verify that the semantic data still makes sense."
            )
        if intermediate_kind == "visible_color_png_path" and is_png_intermediate_high_risk(decision.texture_type, dds_info.texconv_format):
            next_settings.notes.append(
                f"auto-rule: {decision.texture_type} map may lose precision through PNG intermediates; compare carefully against the source."
            )
        elif intermediate_kind == "technical_high_precision_path":
            next_settings.notes.append(
                f"auto-rule: {decision.texture_type} map is using the technical high-precision path instead of the generic visible-color PNG path."
            )
    if decision.semantic_subtype in {"orm", "rma", "mra", "arm", "packed_mask", "opacity_mask"}:
        next_settings.notes.append(
            f"auto-rule: packed-channel semantic '{decision.semantic_subtype}' detected; preserve exact channel meaning when reviewing results."
        )
    return next_settings


def resolve_dds_output_settings(
    config: NormalizedConfig,
    dds_info: DdsInfo,
    png_width: int,
    png_height: int,
) -> DdsOutputSettings:
    notes: List[str] = []

    if config.dds_format_mode == DDS_FORMAT_MODE_MATCH_ORIGINAL:
        texconv_format = dds_info.texconv_format
    else:
        texconv_format = config.dds_custom_format
        notes.append(f"custom format {texconv_format}")

    if config.dds_size_mode == DDS_SIZE_MODE_ORIGINAL:
        output_width = dds_info.width
        output_height = dds_info.height
        resize_to_dimensions = True
        notes.append(f"original size {output_width}x{output_height}")
    elif config.dds_size_mode == DDS_SIZE_MODE_CUSTOM:
        output_width = config.dds_custom_width
        output_height = config.dds_custom_height
        resize_to_dimensions = True
        notes.append(f"custom size {output_width}x{output_height}")
    else:
        output_width = png_width
        output_height = png_height
        resize_to_dimensions = False

    max_possible_mips = max_mips_for_size(output_width, output_height)
    if config.dds_mip_mode == DDS_MIP_MODE_MATCH_ORIGINAL:
        mip_count = min(dds_info.mip_count, max_possible_mips)
        if mip_count != dds_info.mip_count:
            notes.append(
                f"original mip count {dds_info.mip_count} exceeds output max {max_possible_mips}, clamped to {mip_count}"
            )
    elif config.dds_mip_mode == DDS_MIP_MODE_FULL_CHAIN:
        mip_count = max_possible_mips
        notes.append(f"full mip chain {mip_count}")
    elif config.dds_mip_mode == DDS_MIP_MODE_SINGLE:
        mip_count = 1
        notes.append("single mip")
    else:
        mip_count = min(config.dds_custom_mip_count, max_possible_mips)
        if mip_count != config.dds_custom_mip_count:
            notes.append(
                f"custom mip count {config.dds_custom_mip_count} exceeds output max {max_possible_mips}, clamped to {mip_count}"
            )
        else:
            notes.append(f"custom mip count {mip_count}")

    return DdsOutputSettings(
        texconv_format=texconv_format,
        mip_count=mip_count,
        width=output_width,
        height=output_height,
        resize_to_dimensions=resize_to_dimensions,
        notes=notes,
    )


def apply_texture_rule_to_output_settings(
    settings: DdsOutputSettings,
    rule: TextureRule,
) -> Tuple[Optional[DdsOutputSettings], str]:
    if rule.action == "skip":
        return None, f"texture rule matched: {rule.pattern} -> skip"

    next_settings = DdsOutputSettings(
        texconv_format=settings.texconv_format,
        mip_count=settings.mip_count,
        width=settings.width,
        height=settings.height,
        resize_to_dimensions=settings.resize_to_dimensions,
        notes=list(settings.notes),
        texconv_color_args=list(settings.texconv_color_args),
        texconv_extra_args=list(settings.texconv_extra_args),
    )

    if rule.format_value and rule.format_value != DDS_FORMAT_MODE_MATCH_ORIGINAL:
        next_settings.texconv_format = rule.format_value
    if rule.size_value:
        if rule.size_value == DDS_SIZE_MODE_PNG:
            next_settings.resize_to_dimensions = False
        elif rule.size_value == DDS_SIZE_MODE_ORIGINAL:
            next_settings.resize_to_dimensions = True
        else:
            width_text, height_text = rule.size_value.lower().split("x", 1)
            next_settings.width = int(width_text)
            next_settings.height = int(height_text)
            next_settings.resize_to_dimensions = True
    if rule.mip_value:
        if rule.mip_value == DDS_MIP_MODE_FULL_CHAIN:
            next_settings.mip_count = max_mips_for_size(next_settings.width, next_settings.height)
        elif rule.mip_value == DDS_MIP_MODE_SINGLE:
            next_settings.mip_count = 1
        elif rule.mip_value not in {DDS_MIP_MODE_MATCH_ORIGINAL, DDS_MIP_MODE_FULL_CHAIN, DDS_MIP_MODE_SINGLE}:
            next_settings.mip_count = int(rule.mip_value)

    next_settings.notes.append(f"texture rule matched: {rule.pattern}")
    return next_settings, f"texture rule matched: {rule.pattern}"


def summarize_texture_workflow_rule(rule: Optional[TextureRule]) -> str:
    if rule is None:
        return "(none)"
    match_mode = "Exact" if str(getattr(rule, "match_mode", "glob") or "glob").strip().lower() == "exact" else "Glob"
    return f"{match_mode}: {rule.pattern}"


def summarize_effective_dds_override(entry: TextureProcessingPlan) -> str:
    parts: List[str] = []
    if entry.effective_output_override.format_value:
        parts.append(f"fmt={entry.effective_output_override.format_value}")
    if entry.effective_output_override.size_value:
        parts.append(f"size={entry.effective_output_override.size_value}")
    if entry.effective_output_override.mip_value:
        parts.append(f"mips={entry.effective_output_override.mip_value}")
    return ", ".join(parts) if parts else "Inherit main DDS Output"


def summarize_effective_ncnn_settings(
    normalized: NormalizedConfig,
    entry: TextureProcessingPlan,
) -> str:
    if normalized.upscale_backend != UPSCALE_BACKEND_REALESRGAN_NCNN:
        return "Ignored unless direct NCNN is selected"
    settings = entry.effective_ncnn_settings
    parts = [
        settings.model_name or "(inherit)",
        f"{settings.scale}x",
        f"tile {settings.tile_size}",
    ]
    if settings.post_correction_mode:
        parts.append(settings.post_correction_mode)
    if settings.extra_args:
        parts.append("extra args")
    return " | ".join(parts)


__all__ = [
    "_linear_variant",
    "_resolve_plan_output_settings",
    "_srgb_variant",
    "apply_automatic_texture_rule_adjustments",
    "apply_texture_rule_to_output_settings",
    "apply_texture_workflow_output_override",
    "max_mips_for_size",
    "resolve_dds_output_settings",
    "summarize_effective_dds_override",
    "summarize_effective_ncnn_settings",
    "summarize_texture_workflow_rule",
]
