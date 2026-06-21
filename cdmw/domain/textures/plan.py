"""Pure texture workflow plan state and planning rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from cdmw.constants import (
    UPSCALE_BACKEND_CHAINNER,
    UPSCALE_BACKEND_NONE,
    UPSCALE_BACKEND_REALESRGAN_NCNN,
)
from cdmw.core.upscale_profiles import (
    TextureUpscaleDecision,
    is_technical_texture_type,
    should_upscale_texture,
)
from cdmw.domain.textures.profiles import (
    _DEFAULT_SEMANTIC_SUBTYPES,
    _PROFILE_TABLE,
    _SCALAR_HIGH_PRECISION_MASK_SUBTYPES,
    _SEMANTIC_OVERRIDE_TEXTURE_TYPES,
)
from cdmw.models import (
    BackendCapabilityDecision,
    BackendCapabilityMatrix,
    ChainnerChainAnalysis,
    DdsInfo,
    EffectiveNcnnSettings,
    IntermediateKind,
    NormalizedConfig,
    TextureProcessingPlan,
    TextureProcessingProfile,
    TextureRule,
    TextureSemanticEvidence,
    TextureWorkflowDdsOverride,
    TextureWorkflowProfile,
)


@dataclass(frozen=True, slots=True)
class TextureWorkflowPlan:
    workspace_root: Path
    profile_key: str
    source_count: int = 0


_VISIBLE_COLOR_TEXTURE_TYPES = frozenset({"color", "ui", "emissive", "impostor"})


def _dds_colorspace_intent_from_format(texconv_format: str) -> str:
    normalized = str(texconv_format or "").strip().upper()
    if normalized.endswith("_SRGB"):
        return "srgb"
    if normalized:
        return "linear"
    return "unknown"


def _normalize_alpha_policy(alpha_mode: str) -> str:
    normalized = str(alpha_mode or "").strip().lower()
    if normalized == "cutout":
        return "cutout_coverage"
    if normalized in {"none", "straight", "channel_data", "premultiplied"}:
        return normalized
    return "straight" if normalized else "none"


def _semantic_override_components(value: str) -> Tuple[str, str]:
    normalized = str(value or "").strip().lower()
    if not normalized:
        raise ValueError("Semantic override cannot be empty.")
    for separator in (":", "/"):
        if separator in normalized:
            texture_type, semantic_subtype = [piece.strip() for piece in normalized.split(separator, 1)]
            if texture_type not in _DEFAULT_SEMANTIC_SUBTYPES:
                raise ValueError(f"Unsupported semantic override texture type: {texture_type}")
            if not semantic_subtype:
                raise ValueError("Semantic override subtype cannot be empty.")
            return texture_type, semantic_subtype
    texture_type = _SEMANTIC_OVERRIDE_TEXTURE_TYPES.get(normalized)
    if texture_type is not None:
        if normalized in _DEFAULT_SEMANTIC_SUBTYPES:
            return normalized, _DEFAULT_SEMANTIC_SUBTYPES[normalized]
        return texture_type, normalized
    raise ValueError(f"Unsupported semantic override: {value}")


def _profile_for_key(key: str) -> TextureProcessingProfile:
    profile = _PROFILE_TABLE.get(str(key or "").strip().lower())
    if profile is None:
        raise ValueError(f"Unsupported texture processing profile: {key}")
    return profile


def _infer_profile_key(
    decision: TextureUpscaleDecision,
    alpha_policy: str,
    dds_info: DdsInfo,
    explicit_profile: Optional[str] = None,
) -> str:
    if explicit_profile:
        return _profile_for_key(explicit_profile).key

    if decision.precision_sensitive or decision.texture_type == "vector" or "FLOAT" in dds_info.texconv_format.upper() or "SNORM" in dds_info.texconv_format.upper():
        return "float_or_vector_preserve_only"
    if alpha_policy == "premultiplied":
        return "premultiplied_alpha_review_required"
    if decision.texture_type == "normal":
        return "normal_bc5"
    if decision.texture_type in {"height", "roughness"}:
        return "scalar_high_precision_bc4"
    if decision.texture_type == "mask":
        if decision.semantic_subtype in {"orm", "rma", "mra", "arm", "packed_mask", "material_mask", "material_response"} or decision.packed_channels:
            return "packed_mask_preserve_layout"
        if (
            not dds_info.has_alpha
            and alpha_policy == "none"
            and decision.semantic_subtype in _SCALAR_HIGH_PRECISION_MASK_SUBTYPES
        ):
            return "scalar_high_precision_bc4"
        return "scalar_bc4"
    if decision.texture_type == "ui" and alpha_policy in {"straight", "cutout_coverage"} and dds_info.has_alpha:
        return "ui_alpha"
    if alpha_policy == "cutout_coverage":
        return "color_cutout_alpha"
    return "color_default"


def _is_scalar_high_precision_candidate(
    decision: TextureUpscaleDecision,
    dds_info: DdsInfo,
    alpha_policy: str,
    profile: TextureProcessingProfile,
) -> bool:
    if profile.key != "scalar_high_precision_bc4":
        return False
    if dds_info.precision_sensitive or decision.precision_sensitive:
        return False
    if alpha_policy != "none":
        return False
    if decision.packed_channels:
        return False
    if decision.texture_type in {"height", "roughness"}:
        return True
    if decision.texture_type == "mask" and decision.semantic_subtype in _SCALAR_HIGH_PRECISION_MASK_SUBTYPES:
        return not dds_info.has_alpha
    return False


def _workflow_profile_for_rule(
    rule: Optional[TextureRule],
    workflow_profiles: Sequence[TextureWorkflowProfile],
) -> Optional[TextureWorkflowProfile]:
    if rule is None:
        return None
    target_id = str(getattr(rule, "workflow_profile_id", "") or "").strip()
    if not target_id:
        return None
    for profile in workflow_profiles:
        if profile.profile_id == target_id:
            return profile
    return None


def _effective_output_override(
    workflow_profile: Optional[TextureWorkflowProfile],
    rule: Optional[TextureRule],
) -> TextureWorkflowDdsOverride:
    override = TextureWorkflowDdsOverride()
    if workflow_profile is not None:
        override = TextureWorkflowDdsOverride(
            format_value=workflow_profile.format_value,
            size_value=workflow_profile.size_value,
            mip_value=workflow_profile.mip_value,
        )
    if rule is not None:
        if rule.format_value:
            override.format_value = rule.format_value
        if rule.size_value:
            override.size_value = rule.size_value
        if rule.mip_value:
            override.mip_value = rule.mip_value
    return override


def _effective_ncnn_settings(
    normalized: NormalizedConfig,
    workflow_profile: Optional[TextureWorkflowProfile],
) -> EffectiveNcnnSettings:
    settings = EffectiveNcnnSettings(
        model_name=normalized.ncnn_model_name,
        scale=normalized.ncnn_scale,
        tile_size=normalized.ncnn_tile_size,
        extra_args=normalized.ncnn_extra_args,
        post_correction_mode=normalized.upscale_post_correction_mode,
    )
    if workflow_profile is None:
        return settings
    if workflow_profile.ncnn_model_name:
        settings.model_name = workflow_profile.ncnn_model_name
    if workflow_profile.ncnn_scale is not None:
        settings.scale = workflow_profile.ncnn_scale
    if workflow_profile.ncnn_tile_size is not None:
        settings.tile_size = workflow_profile.ncnn_tile_size
    if workflow_profile.ncnn_extra_args:
        settings.extra_args = workflow_profile.ncnn_extra_args
    if workflow_profile.post_correction_mode:
        settings.post_correction_mode = workflow_profile.post_correction_mode
    return settings


def _apply_workflow_profile_action_override(
    workflow_profile: Optional[TextureWorkflowProfile],
    *,
    action: str,
    action_reason: str,
    requires_png_processing: bool,
) -> Tuple[str, str, bool]:
    if workflow_profile is None or not workflow_profile.action_mode:
        return action, action_reason, requires_png_processing

    profile_reason = f"workflow profile '{workflow_profile.label}' forces {workflow_profile.action_mode}"
    if workflow_profile.action_mode == "skip":
        return "skip_by_rule", profile_reason, False
    if workflow_profile.action_mode == "preserve_original":
        return "preserve_original", profile_reason, False
    if workflow_profile.action_mode == "rebuild_from_png":
        return "rebuild_from_png", profile_reason, True
    if workflow_profile.action_mode == "upscale_then_rebuild":
        return "upscale_then_rebuild", profile_reason, True
    return action, action_reason, requires_png_processing


def _decision_with_texture_rule_overrides(
    decision: TextureUpscaleDecision,
    rule: Optional[TextureRule],
    dds_info: DdsInfo,
    *,
    preset: str,
) -> TextureUpscaleDecision:
    if rule is None:
        return decision

    next_decision = decision
    notes = list(decision.notes)
    source_evidence = list(decision.source_evidence)

    if rule.semantic_value:
        override_type, override_subtype = _semantic_override_components(rule.semantic_value)
        next_decision = replace(
            next_decision,
            texture_type=override_type,
            semantic_subtype=override_subtype,
            should_upscale=should_upscale_texture(override_type, preset),
        )
        source_evidence.append(f"texture rule semantic override -> {override_type}/{override_subtype}")
        notes.append(f"texture rule overrides semantic classification to {override_type}/{override_subtype}.")

    if rule.colorspace_value:
        colorspace_value = str(rule.colorspace_value).strip().lower()
        target_colorspace = _dds_colorspace_intent_from_format(dds_info.texconv_format) if colorspace_value == "match_source" else colorspace_value
        next_decision = replace(next_decision, recommended_colorspace=target_colorspace or next_decision.recommended_colorspace)
        notes.append(f"texture rule overrides colorspace policy to {target_colorspace or 'match_source'}.")

    if rule.alpha_policy_value:
        alpha_override = str(rule.alpha_policy_value).strip().lower()
        mapped_alpha_mode = "cutout" if alpha_override == "cutout_coverage" else alpha_override
        next_decision = replace(
            next_decision,
            alpha_mode=mapped_alpha_mode,
            preserve_alpha=alpha_override != "none" and dds_info.has_alpha,
        )
        notes.append(f"texture rule overrides alpha policy to {alpha_override}.")

    if rule.intermediate_value:
        intermediate = str(rule.intermediate_value).strip().lower()
        preserve_original = intermediate == "technical_preserve_path"
        next_decision = replace(
            next_decision,
            intermediate_policy="preserve_original" if preserve_original else "png_ok",
            preserve_original_due_to_intermediate=preserve_original,
        )
        notes.append(f"texture rule overrides processing path to {intermediate}.")

    return replace(next_decision, notes=notes, source_evidence=source_evidence)


def _plan_path_kind(
    normalized: NormalizedConfig,
    decision: TextureUpscaleDecision,
    profile: TextureProcessingProfile,
    rule: Optional[TextureRule],
    dds_info: DdsInfo,
    alpha_policy: str,
) -> IntermediateKind | str:
    rule_intermediate = str(rule.intermediate_value).strip().lower() if rule is not None and rule.intermediate_value else ""
    unsafe_override_applies = (
        normalized.enable_unsafe_technical_override
        and is_technical_texture_type(decision.texture_type)
        and not (rule is not None and (rule.action == "skip" or rule_intermediate in {"technical_preserve_path", "technical_high_precision_path"}))
    )
    if rule is not None and rule.intermediate_value:
        return rule_intermediate
    if unsafe_override_applies:
        return "visible_color_png_path"
    if _is_scalar_high_precision_candidate(decision, dds_info, alpha_policy, profile):
        return "technical_high_precision_path"
    if profile.preserve_only or decision.preserve_original_due_to_intermediate:
        return "technical_preserve_path"
    if decision.texture_type in _VISIBLE_COLOR_TEXTURE_TYPES:
        return "visible_color_png_path"
    if decision.texture_type == "unknown" and not normalized.enable_automatic_texture_rules and decision.should_upscale:
        return "visible_color_png_path"
    return "technical_preserve_path"


def _build_backend_capability_matrix(
    normalized: NormalizedConfig,
    *,
    chain_analysis: Optional[ChainnerChainAnalysis] = None,
) -> BackendCapabilityMatrix:
    normalized_backend = str(normalized.upscale_backend or "").strip().lower()
    decisions_by_path_kind: Dict[str, BackendCapabilityDecision] = {
        "technical_preserve_path": BackendCapabilityDecision(
            backend=normalized_backend,
            path_kind="technical_preserve_path",
            compatible=True,
            execution_mode="preserve_original",
            reason="Pass 1 keeps this file on the technical preserve path instead of routing it through a PNG intermediate.",
        ),
        "technical_high_precision_path": BackendCapabilityDecision(
            backend=normalized_backend,
            path_kind="technical_high_precision_path",
            compatible=False,
            execution_mode="preserve_original",
            reason="Technical high-precision path requires a backend/path combination that has not been enabled for this run.",
        ),
    }
    planner_notes: List[str] = []
    if normalized.enable_unsafe_technical_override:
        planner_notes.append(
            "Expert unsafe technical override is enabled: technical maps may be forced through the generic visible-color PNG path instead of preserve/high-precision paths."
        )

    if normalized_backend == UPSCALE_BACKEND_NONE:
        visible_decision = BackendCapabilityDecision(
            backend=normalized_backend,
            path_kind="visible_color_png_path",
            compatible=True,
            execution_mode="rebuild_from_png",
            reason="Backend is disabled, so the planner will rebuild DDS from the current PNG input.",
        )
        if normalized.enable_dds_staging and normalized.dds_staging_root is not None:
            decisions_by_path_kind["technical_high_precision_path"] = BackendCapabilityDecision(
                backend=normalized_backend,
                path_kind="technical_high_precision_path",
                compatible=True,
                execution_mode="rebuild_from_high_precision_png",
                reason="Backend is disabled, but DDS staging is enabled, so eligible scalar technical maps can rebuild from high-precision staged PNG data.",
            )
        else:
            decisions_by_path_kind["technical_high_precision_path"] = BackendCapabilityDecision(
                backend=normalized_backend,
                path_kind="technical_high_precision_path",
                compatible=True,
                execution_mode="rebuild_from_high_precision_png",
                reason="Backend is disabled, so the technical high-precision path will use matching PNG files from PNG root when they are valid 16-bit grayscale intermediates.",
            )
    elif normalized_backend == UPSCALE_BACKEND_CHAINNER:
        if chain_analysis is not None and not chain_analysis.planner_compatible:
            preview_reasons = "; ".join(chain_analysis.blocking_warnings[:3])
            extra = "" if len(chain_analysis.blocking_warnings) <= 3 else f" (+{len(chain_analysis.blocking_warnings) - 3} more)"
            reason = (
                "chaiNNer is not planner-compatible for the visible-color path with the current chain configuration: "
                f"{preview_reasons}{extra}"
            )
            visible_decision = BackendCapabilityDecision(
                backend=normalized_backend,
                path_kind="visible_color_png_path",
                compatible=False,
                execution_mode="preserve_original",
                reason=reason,
            )
            planner_notes.extend(chain_analysis.blocking_warnings[:5])
        else:
            reason = (
                "chaiNNer is allowed on the visible-color path when the chain reads from the planned input roots "
                "and writes planner-selected PNG outputs into the configured PNG root."
            )
            if chain_analysis is None:
                reason += " Runtime chain validation is still pending."
            visible_decision = BackendCapabilityDecision(
                backend=normalized_backend,
                path_kind="visible_color_png_path",
                compatible=True,
                execution_mode="upscale_then_rebuild",
                reason=reason,
            )
        decisions_by_path_kind["technical_high_precision_path"] = BackendCapabilityDecision(
            backend=normalized_backend,
            path_kind="technical_high_precision_path",
            compatible=False,
            execution_mode="preserve_original",
            reason="chaiNNer is only trusted on the visible-color path in this tranche. Technical high-precision scalar paths stay preserve-first.",
        )
    elif normalized_backend == UPSCALE_BACKEND_REALESRGAN_NCNN:
        visible_decision = BackendCapabilityDecision(
            backend=normalized_backend,
            path_kind="visible_color_png_path",
            compatible=True,
            execution_mode="upscale_then_rebuild",
            reason=f"{normalized_backend} is allowed on the visible-color path in this tranche.",
        )
        decisions_by_path_kind["technical_high_precision_path"] = BackendCapabilityDecision(
            backend=normalized_backend,
            path_kind="technical_high_precision_path",
            compatible=False,
            execution_mode="preserve_original",
            reason=f"{normalized_backend} does not support the technical high-precision path in this tranche.",
        )
    else:
        visible_decision = BackendCapabilityDecision(
            backend=normalized_backend,
            path_kind="visible_color_png_path",
            compatible=False,
            execution_mode="preserve_original",
            reason=f"Unsupported upscale backend: {normalized_backend}",
        )

    decisions_by_path_kind["visible_color_png_path"] = visible_decision
    return BackendCapabilityMatrix(
        backend=normalized_backend,
        decisions_by_path_kind=decisions_by_path_kind,
        planner_notes=tuple(planner_notes),
    )


def _resolve_backend_capability(
    backend_matrix: BackendCapabilityMatrix,
    path_kind: str,
) -> BackendCapabilityDecision:
    return backend_matrix.decision_for(path_kind)


def _plan_preserve_reason(
    decision: TextureUpscaleDecision,
    profile: TextureProcessingProfile,
    path_kind: str,
    backend_capability: BackendCapabilityDecision,
    rule: Optional[TextureRule],
) -> str:
    if rule is not None and rule.action == "skip":
        return f"texture rule matched: {rule.pattern} -> skip"
    if rule is not None and rule.intermediate_value == "technical_preserve_path":
        return f"texture rule forces technical preserve path for {decision.texture_type}/{decision.semantic_subtype}"
    if rule is not None and rule.intermediate_value == "technical_high_precision_path" and not backend_capability.compatible:
        return backend_capability.reason
    if not backend_capability.compatible:
        return backend_capability.reason
    if path_kind not in {"technical_preserve_path", "technical_high_precision_path"}:
        return ""
    if profile.preserve_only:
        return f"profile {profile.key} is preserve-only for {decision.texture_type}/{decision.semantic_subtype}"
    if decision.preserve_original_due_to_intermediate:
        return f"automatic rules preserve {decision.texture_type}/{decision.semantic_subtype}"
    if path_kind == "technical_high_precision_path":
        return ""
    return f"planner preserved {decision.texture_type}/{decision.semantic_subtype} on the technical preserve path"


def _lossy_intermediate_warning(decision: TextureUpscaleDecision, path_kind: str) -> str:
    if path_kind != "visible_color_png_path":
        return ""
    if decision.intermediate_policy == "risky_png":
        return f"Visible-color path still uses a lossy PNG intermediate for {decision.texture_type}/{decision.semantic_subtype}; review the rebuilt DDS carefully."
    return ""


def describe_processing_path_kind(path_kind: str) -> str:
    normalized = str(path_kind or "").strip().lower()
    if normalized == "visible_color_png_path":
        return "Visible-color PNG path: generic 8-bit image staging for color-like textures."
    if normalized == "technical_preserve_path":
        return "Technical preserve path: keep the original DDS unchanged because the current workflow is not trusted for this texture."
    if normalized == "technical_high_precision_path":
        return "Technical high-precision path: use high-bit-depth staged PNG data for eligible scalar technical textures instead of the generic visible-color path."
    return f"Unknown planner path: {path_kind}"


def _build_texture_processing_plan_entry(
    normalized: NormalizedConfig,
    dds_path: Path,
    rel_path: Path,
    dds_info: DdsInfo,
    decision: TextureUpscaleDecision,
    rule: Optional[TextureRule],
    backend_matrix: BackendCapabilityMatrix,
) -> TextureProcessingPlan:
    decision = _decision_with_texture_rule_overrides(
        decision,
        rule,
        dds_info,
        preset=normalized.upscale_texture_preset,
    )
    rule_intermediate = str(rule.intermediate_value).strip().lower() if rule is not None and rule.intermediate_value else ""
    unsafe_override_applies = (
        normalized.enable_unsafe_technical_override
        and is_technical_texture_type(decision.texture_type)
        and not (rule is not None and (rule.action == "skip" or rule_intermediate in {"technical_preserve_path", "technical_high_precision_path"}))
    )
    workflow_profile = _workflow_profile_for_rule(rule, normalized.workflow_profiles)
    effective_output_override = _effective_output_override(workflow_profile, rule)
    effective_ncnn_settings = _effective_ncnn_settings(normalized, workflow_profile)
    base_alpha_policy = _normalize_alpha_policy(decision.alpha_mode)
    profile = _profile_for_key(_infer_profile_key(decision, base_alpha_policy, dds_info, rule.profile_value if rule else None))
    alpha_policy = str(rule.alpha_policy_value).strip().lower() if rule and rule.alpha_policy_value else profile.alpha_policy or base_alpha_policy
    path_kind = _plan_path_kind(normalized, decision, profile, rule, dds_info, alpha_policy)
    if (
        unsafe_override_applies
        and path_kind == "visible_color_png_path"
    ):
        notes = list(decision.notes)
        notes.append(
            "expert override forced this technical texture onto the generic visible-color PNG path; expect a higher risk of broken normals, mask drift, or shading errors."
        )
        decision = replace(decision, notes=notes)
    if path_kind == "technical_high_precision_path" and decision.preserve_original_due_to_intermediate:
        notes = list(decision.notes)
        notes.append("planner upgraded this scalar technical map from preserve-only to the technical high-precision path.")
        decision = replace(
            decision,
            preserve_original_due_to_intermediate=False,
            intermediate_policy="high_precision_png",
            notes=notes,
        )
    backend_capability = _resolve_backend_capability(backend_matrix, path_kind)
    preserve_reason = _plan_preserve_reason(decision, profile, path_kind, backend_capability, rule)
    lossy_warning = _lossy_intermediate_warning(decision, path_kind)

    dds_info.colorspace_intent = _dds_colorspace_intent_from_format(dds_info.texconv_format)
    dds_info.precision_sensitive = dds_info.precision_sensitive or decision.precision_sensitive
    dds_info.packed_channel_risk = bool(decision.packed_channels) or decision.semantic_subtype in {"orm", "rma", "mra", "arm", "packed_mask", "material_mask", "material_response"}
    dds_info.preserve_only_source = bool(preserve_reason) or profile.preserve_only

    if rule is not None and rule.action == "skip":
        action = "skip_by_rule"
        action_reason = preserve_reason
        requires_png_processing = False
    elif (
        normalized.upscale_backend == UPSCALE_BACKEND_NONE
        and backend_capability.compatible
        and path_kind in {"visible_color_png_path", "technical_high_precision_path"}
    ):
        action = backend_capability.execution_mode
        action_reason = backend_capability.reason
        requires_png_processing = action in {"rebuild_from_png", "rebuild_from_high_precision_png"}
    elif not decision.should_upscale and not unsafe_override_applies:
        action = "preserve_original"
        action_reason = f"preset excludes {decision.texture_type}/{decision.semantic_subtype}"
        preserve_reason = action_reason
        requires_png_processing = False
    elif path_kind == "technical_preserve_path" or not backend_capability.compatible:
        action = "preserve_original"
        action_reason = preserve_reason or backend_capability.reason
        requires_png_processing = False
    else:
        action = backend_capability.execution_mode
        action_reason = backend_capability.reason
        requires_png_processing = action in {"rebuild_from_png", "rebuild_from_high_precision_png", "upscale_then_rebuild"}

    action, action_reason, requires_png_processing = _apply_workflow_profile_action_override(
        workflow_profile,
        action=action,
        action_reason=action_reason,
        requires_png_processing=requires_png_processing,
    )
    if action in {"preserve_original", "skip_by_rule"} and action_reason:
        preserve_reason = action_reason

    return TextureProcessingPlan(
        dds_path=dds_path,
        relative_path=rel_path,
        dds_info=dds_info,
        decision=decision,
        action=action,
        action_reason=action_reason,
        path_kind=path_kind,
        intermediate_kind=path_kind,
        profile=profile,
        alpha_policy=alpha_policy,
        backend_capability=backend_capability,
        requires_png_processing=requires_png_processing,
        preserve_reason=preserve_reason,
        lossy_intermediate_warning=lossy_warning,
        matched_rule=rule,
        workflow_profile=workflow_profile,
        effective_output_override=effective_output_override,
        effective_ncnn_settings=effective_ncnn_settings,
        semantic_evidence=TextureSemanticEvidence(tuple(decision.source_evidence)),
    )


__all__ = [
    "TextureWorkflowPlan",
    "_apply_workflow_profile_action_override",
    "_build_backend_capability_matrix",
    "_build_texture_processing_plan_entry",
    "_dds_colorspace_intent_from_format",
    "_decision_with_texture_rule_overrides",
    "_effective_ncnn_settings",
    "_effective_output_override",
    "_infer_profile_key",
    "_is_scalar_high_precision_candidate",
    "_normalize_alpha_policy",
    "_plan_path_kind",
    "_profile_for_key",
    "_semantic_override_components",
    "_workflow_profile_for_rule",
    "describe_processing_path_kind",
]
