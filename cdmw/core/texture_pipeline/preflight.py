from __future__ import annotations

import shutil
import threading
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from cdmw.constants import (
    DDS_MIP_MODE_CUSTOM,
    DDS_MIP_MODE_MATCH_ORIGINAL,
    DDS_MIP_MODE_SINGLE,
    DDS_SIZE_MODE_CUSTOM,
    DDS_SIZE_MODE_ORIGINAL,
    UPSCALE_BACKEND_CHAINNER,
    UPSCALE_BACKEND_NONE,
    UPSCALE_BACKEND_REALESRGAN_NCNN,
)
from cdmw.core.common import raise_if_cancelled
from cdmw.core.texture_pipeline.discovery import find_png_matches_across_roots, resolve_png
from cdmw.core.texture_pipeline.inspection import parse_dds
from cdmw.core.texture_pipeline.preview import _validate_high_precision_staged_png
from cdmw.core.upscale_postprocess import build_source_match_plan_for_decision, describe_post_upscale_correction_mode
from cdmw.core.upscale_profiles import classify_texture_type
from cdmw.domain.textures.output import (
    _resolve_plan_output_settings,
    summarize_effective_dds_override,
    summarize_effective_ncnn_settings,
    summarize_texture_workflow_rule,
)
from cdmw.domain.textures.plan import _build_backend_capability_matrix, describe_processing_path_kind
from cdmw.models import (
    BackendCapabilityMatrix,
    ChainnerChainAnalysis,
    NormalizedConfig,
    TextureProcessingPlan,
    TextureRule,
)

def _summarize_policy_size(
    normalized: NormalizedConfig,
    entry: TextureProcessingPlan,
) -> str:
    dds_info = entry.dds_info
    if entry.action == "preserve_original":
        return f"{dds_info.width}x{dds_info.height} (unchanged)"
    if normalized.dds_size_mode == DDS_SIZE_MODE_ORIGINAL:
        return f"{dds_info.width}x{dds_info.height} (match original)"
    if normalized.dds_size_mode == DDS_SIZE_MODE_CUSTOM:
        return f"{normalized.dds_custom_width}x{normalized.dds_custom_height} (custom)"
    if normalized.upscale_backend == UPSCALE_BACKEND_REALESRGAN_NCNN and entry.action == "upscale_then_rebuild":
        effective_scale = max(1, int(getattr(entry.effective_ncnn_settings, "scale", normalized.ncnn_scale) or normalized.ncnn_scale))
        estimated_width = max(1, dds_info.width * effective_scale)
        estimated_height = max(1, dds_info.height * effective_scale)
        return f"{estimated_width}x{estimated_height} (estimated {effective_scale}x direct backend PNG)"
    if entry.action == "rebuild_from_high_precision_png" and normalized.enable_dds_staging:
        return "staged high-precision PNG size (resolved from DDS-to-PNG conversion)"
    if entry.action == "rebuild_from_high_precision_png":
        return "existing high-precision PNG size (resolved from PNG root)"
    if normalized.upscale_backend == UPSCALE_BACKEND_NONE and normalized.enable_dds_staging:
        return "staged PNG size (resolved from DDS-to-PNG conversion)"
    return "final PNG size (resolved at rebuild time)"


def _summarize_policy_mips(
    normalized: NormalizedConfig,
    entry: TextureProcessingPlan,
) -> str:
    dds_info = entry.dds_info
    if entry.action == "preserve_original":
        return f"{dds_info.mip_count} (unchanged)"
    if normalized.dds_mip_mode == DDS_MIP_MODE_MATCH_ORIGINAL:
        return f"{dds_info.mip_count} (match original)"
    if normalized.dds_mip_mode == DDS_MIP_MODE_SINGLE:
        return "1 (single mip)"
    if normalized.dds_mip_mode == DDS_MIP_MODE_CUSTOM:
        return f"{normalized.dds_custom_mip_count} (custom)"
    return "full chain"


def build_texture_policy_preview_payload(
    normalized: NormalizedConfig,
    dds_files: Sequence[Path],
    *,
    processing_plan: Sequence[TextureProcessingPlan] = (),
    backend_matrix: Optional[BackendCapabilityMatrix] = None,
) -> Dict[str, object]:
    resolved_backend_matrix = backend_matrix or _build_backend_capability_matrix(normalized)
    if processing_plan:
        plan = list(processing_plan)
    else:
        from cdmw.core.texture_pipeline.planning import build_texture_processing_plan

        plan = build_texture_processing_plan(
            normalized,
            dds_files,
            backend_matrix=resolved_backend_matrix,
        )
    rows: List[Dict[str, object]] = []
    action_counts: Dict[str, int] = defaultdict(int)
    semantic_counts: Dict[str, int] = defaultdict(int)
    direct_backend_supported = normalized.upscale_backend in {
        UPSCALE_BACKEND_REALESRGAN_NCNN,
    }
    for entry in plan:
        final_action = entry.action
        final_reason = entry.action_reason
        output_format = entry.dds_info.dds_format
        detail_notes = list(entry.decision.notes)
        effective_correction_mode = (
            entry.effective_ncnn_settings.post_correction_mode
            if normalized.upscale_backend == UPSCALE_BACKEND_REALESRGAN_NCNN
            else normalized.upscale_post_correction_mode
        )
        correction_plan = build_source_match_plan_for_decision(
            effective_correction_mode,
            entry.decision,
            direct_backend_supported=direct_backend_supported,
            planner_path_kind=entry.path_kind,
            planner_profile_key=entry.profile.key,
        )
        detail_notes.append(
            "post-correction: "
            f"{describe_post_upscale_correction_mode(effective_correction_mode)} -> "
            f"{correction_plan.correction_action} ({correction_plan.correction_reason})"
        )
        if entry.workflow_profile is not None:
            detail_notes.append(f"workflow profile: {entry.workflow_profile.label} ({entry.workflow_profile.profile_id})")
            detail_notes.append(f"workflow DDS override: {summarize_effective_dds_override(entry)}")
            detail_notes.append(f"workflow NCNN override: {summarize_effective_ncnn_settings(normalized, entry)}")
        if entry.matched_rule is not None:
            detail_notes.append(f"matched texture rule: {summarize_texture_workflow_rule(entry.matched_rule)}")
        if entry.preserve_reason:
            detail_notes.append(f"preserve reason: {entry.preserve_reason}")
        if entry.lossy_intermediate_warning:
            detail_notes.append(entry.lossy_intermediate_warning)
        if entry.action not in {"preserve_original", "skip_by_rule"}:
            output_settings = _resolve_plan_output_settings(
                normalized,
                entry,
                entry.dds_info.width,
                entry.dds_info.height,
                has_alpha=entry.dds_info.has_alpha,
            )
            output_format = output_settings.dds_format
            detail_notes.extend(output_settings.notes)
        elif entry.action == "skip_by_rule":
            output_format = "-"
        action_counts[final_action] += 1
        semantic_counts[entry.decision.semantic_subtype] += 1
        rows.append(
            {
                "path": entry.relative_path.as_posix(),
                "texture_type": entry.decision.texture_type,
                "semantic_subtype": entry.decision.semantic_subtype,
                "semantic_confidence": entry.decision.semantic_confidence,
                "alpha_mode": entry.decision.alpha_mode,
                "alpha_policy": entry.alpha_policy,
                "packed_channels": list(entry.decision.packed_channels),
                "intermediate_policy": entry.decision.intermediate_policy,
                "path_kind": entry.path_kind,
                "path_description": describe_processing_path_kind(entry.path_kind),
                "profile_key": entry.profile.key,
                "profile_label": entry.profile.label,
                "workflow_profile_id": entry.workflow_profile.profile_id if entry.workflow_profile is not None else "",
                "workflow_profile_label": entry.workflow_profile.label if entry.workflow_profile is not None else "(none)",
                "matched_rule": summarize_texture_workflow_rule(entry.matched_rule),
                "effective_dds_override": summarize_effective_dds_override(entry),
                "effective_ncnn_summary": summarize_effective_ncnn_settings(normalized, entry),
                "effective_ncnn_model": entry.effective_ncnn_settings.model_name,
                "effective_ncnn_scale": entry.effective_ncnn_settings.scale,
                "effective_ncnn_tile": entry.effective_ncnn_settings.tile_size,
                "effective_ncnn_extra_args": entry.effective_ncnn_settings.extra_args,
                "effective_ncnn_correction": entry.effective_ncnn_settings.post_correction_mode,
                "backend_compatible": entry.backend_capability.compatible,
                "backend_execution_mode": entry.backend_capability.execution_mode,
                "backend_reason": entry.backend_capability.reason,
                "original_format": entry.dds_info.dds_format,
                "planned_format": output_format,
                "size_policy": _summarize_policy_size(normalized, entry),
                "mip_policy": _summarize_policy_mips(normalized, entry),
                "action": final_action,
                "action_reason": final_reason,
                "requires_png_processing": entry.requires_png_processing,
                "preserve_reason": entry.preserve_reason,
                "correction_mode": describe_post_upscale_correction_mode(effective_correction_mode),
                "correction_eligibility": correction_plan.correction_eligibility,
                "correction_action": correction_plan.correction_action,
                "correction_reason": correction_plan.correction_reason,
                "source_evidence": list(entry.decision.source_evidence),
                "notes": detail_notes,
            }
        )

    return {
        "rows": rows,
        "summary": {
            "total_files": len(plan),
            "actions": dict(sorted(action_counts.items())),
            "semantic_subtypes": dict(sorted(semantic_counts.items())),
            "backend": normalized.upscale_backend,
            "backend_visible_path_mode": resolved_backend_matrix.decision_for("visible_color_png_path").execution_mode,
            "backend_visible_path_allowed": resolved_backend_matrix.decision_for("visible_color_png_path").compatible,
            "backend_high_precision_path_mode": resolved_backend_matrix.decision_for("technical_high_precision_path").execution_mode,
            "backend_high_precision_path_allowed": resolved_backend_matrix.decision_for("technical_high_precision_path").compatible,
            "backend_planner_notes": list(resolved_backend_matrix.planner_notes),
            "correction_mode": describe_post_upscale_correction_mode(normalized.upscale_post_correction_mode),
            "path_kinds": dict(sorted((key, sum(1 for entry in plan if entry.path_kind == key)) for key in {entry.path_kind for entry in plan})),
            "png_root": str(normalized.png_root),
            "texture_editor_png_root": str(normalized.texture_editor_png_root) if normalized.texture_editor_png_root else "",
            "output_root": str(normalized.output_root),
            "staging_root": str(normalized.dds_staging_root) if normalized.dds_staging_root else "",
        },
    }


def _scan_direct_high_precision_png_inputs(
    normalized: NormalizedConfig,
    processing_plan: Sequence[TextureProcessingPlan],
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[int, List[str], List[str]]:
    if normalized.enable_dds_staging:
        return 0, [], []
    planned_entries = [
        entry
        for entry in processing_plan
        if entry.path_kind == "technical_high_precision_path"
        and entry.action == "rebuild_from_high_precision_png"
    ]
    if not planned_entries:
        return 0, [], []

    relative_index, basename_index, _png_count = find_png_matches_across_roots(
        (normalized.png_root, normalized.texture_editor_png_root),
        stop_event=stop_event,
    )
    missing_examples: List[str] = []
    invalid_examples: List[str] = []

    for entry in planned_entries:
        raise_if_cancelled(stop_event, "Preflight scan cancelled by user.")
        png_path, match_note = resolve_png(
            entry.relative_path,
            relative_index,
            basename_index,
            normalized.allow_unique_basename_fallback,
        )
        rel_text = entry.relative_path.as_posix()
        if png_path is None:
            if len(missing_examples) < 5:
                missing_examples.append(f"{rel_text} ({match_note})")
            continue
        validation_message = _validate_high_precision_staged_png(png_path, entry)
        if validation_message is not None and len(invalid_examples) < 5:
            invalid_examples.append(f"{rel_text} ({validation_message})")

    return len(planned_entries), missing_examples, invalid_examples


def build_preflight_report_lines(
    normalized: NormalizedConfig,
    dds_files: Sequence[Path],
    *,
    processing_plan: Sequence[TextureProcessingPlan] = (),
    chain_analysis: Optional[ChainnerChainAnalysis] = None,
    backend_matrix: Optional[BackendCapabilityMatrix] = None,
    texture_rules: Sequence[TextureRule] = (),
    stop_event: Optional[threading.Event] = None,
) -> List[str]:
    total_dds_bytes = 0
    texture_type_counts: Dict[str, int] = defaultdict(int)
    semantic_subtype_counts: Dict[str, int] = defaultdict(int)
    action_counts: Dict[str, int] = defaultdict(int)
    path_kind_counts: Dict[str, int] = defaultdict(int)
    preserve_reason_counts: Dict[str, int] = defaultdict(int)
    high_risk_examples: List[str] = []
    high_precision_examples: List[str] = []
    high_precision_path_examples: List[str] = []
    blocked_high_precision_examples: List[str] = []
    high_precision_input_scan_total = 0
    missing_high_precision_input_examples: List[str] = []
    invalid_high_precision_input_examples: List[str] = []
    plan_by_rel: Dict[str, TextureProcessingPlan] = {
        entry.relative_path.as_posix(): entry for entry in processing_plan
    }
    policy_examples: List[str] = []
    for path in dds_files:
        try:
            total_dds_bytes += path.stat().st_size
        except OSError:
            continue
        rel_text = path.relative_to(normalized.original_dds_root).as_posix()
        plan_entry = plan_by_rel.get(rel_text)
        if plan_entry is not None:
            texture_type = plan_entry.decision.texture_type
            semantic_subtype = plan_entry.decision.semantic_subtype
            action_counts[plan_entry.action] += 1
            path_kind_counts[plan_entry.path_kind] += 1
            if plan_entry.preserve_reason:
                preserve_reason_counts[plan_entry.preserve_reason] += 1
            semantic_subtype_counts[semantic_subtype] += 1
            if plan_entry.path_kind == "technical_high_precision_path" and len(high_precision_path_examples) < 5:
                high_precision_path_examples.append(rel_text)
            if (
                plan_entry.path_kind == "technical_high_precision_path"
                and plan_entry.action == "preserve_original"
                and len(blocked_high_precision_examples) < 5
            ):
                blocked_high_precision_examples.append(f"{rel_text} ({plan_entry.action_reason})")
            if len(policy_examples) < 8:
                policy_examples.append(
                    f"{rel_text} -> {plan_entry.action} [{texture_type}/{semantic_subtype}] profile={plan_entry.profile.key} path={plan_entry.path_kind}"
                )
        else:
            texture_type = classify_texture_type(rel_text)
            semantic_subtype = texture_type
        texture_type_counts[texture_type] += 1
        if len(high_risk_examples) < 5 and texture_type in {"height", "vector"}:
            high_risk_examples.append(rel_text)
        if len(high_precision_examples) < 5:
            try:
                info = plan_entry.dds_info if plan_entry is not None else parse_dds(path)
            except Exception:
                info = None
            if info is not None and ("FLOAT" in info.dds_format or "SNORM" in info.dds_format):
                high_precision_examples.append(f"{rel_text} [{info.dds_format}]")
    (
        high_precision_input_scan_total,
        missing_high_precision_input_examples,
        invalid_high_precision_input_examples,
    ) = _scan_direct_high_precision_png_inputs(
        normalized,
        processing_plan,
        stop_event=stop_event,
    )

    lines = [
        "Preflight report:",
        f"- DDS files matching filter: {len(dds_files)}",
        f"- Original DDS root: {normalized.original_dds_root}",
        f"- PNG root: {normalized.png_root}",
        f"- Texture Editor PNG root: {normalized.texture_editor_png_root or '(not configured)'}",
        f"- Output root: {normalized.output_root}",
        f"- Upscaling backend: {normalized.upscale_backend}",
        f"- DDS staging: {'enabled' if normalized.enable_dds_staging else 'disabled'}",
    ]

    if normalized.enable_dds_staging and normalized.dds_staging_root is not None:
        lines.append(f"- DDS staging root: {normalized.dds_staging_root}")
        if normalized.upscale_backend == UPSCALE_BACKEND_CHAINNER:
            lines.append(
                "Warning: DDS-to-PNG conversion is enabled before chaiNNer. "
                "PNG-input chains should read PNG files from the staging root or another matching PNG folder. "
                "DDS-direct chains can ignore the staged PNGs if that is intentional."
            )
        if normalized.upscale_backend == UPSCALE_BACKEND_CHAINNER and "${staging_png_root}" not in normalized.chainner_override_json:
            lines.append("- Warning: staging is enabled, but your chaiNNer overrides do not reference ${staging_png_root}.")
        if normalized.upscale_backend == UPSCALE_BACKEND_REALESRGAN_NCNN:
            lines.append(
                "Warning: DDS-to-PNG conversion is enabled before Real-ESRGAN NCNN. "
                "The NCNN stage will read source PNGs from the staging root and write its output into PNG root."
            )
    elif normalized.upscale_backend == UPSCALE_BACKEND_CHAINNER and "${staging_png_root}" in normalized.chainner_override_json:
        lines.append(
            "- Error: chaiNNer overrides reference ${staging_png_root}, but DDS staging is disabled. "
            "Enable 'Create source PNGs from DDS before processing' or remove that token."
        )

    lines.extend(
        [
            f"- Incremental resume: {'enabled' if normalized.enable_incremental_resume else 'disabled'}",
            f"- Texture rules loaded: {len(texture_rules)}",
            f"- Estimated source DDS data: {total_dds_bytes / (1024 * 1024):.1f} MiB",
        ]
    )
    if backend_matrix is not None:
        visible_capability = backend_matrix.decision_for("visible_color_png_path")
        technical_capability = backend_matrix.decision_for("technical_high_precision_path")
        lines.append(
            "- Planner backend matrix: "
            f"visible_color_png_path={'allow' if visible_capability.compatible else 'preserve'} "
            f"({visible_capability.execution_mode}), "
            f"technical_high_precision_path={'allow' if technical_capability.compatible else 'preserve'} "
            f"({technical_capability.execution_mode})"
        )
        if backend_matrix.planner_notes:
            for note in backend_matrix.planner_notes[:5]:
                lines.append(f"- Planner backend note: {note}")
    if texture_type_counts:
        type_summary = ", ".join(
            f"{texture_type}={count}"
            for texture_type, count in sorted(texture_type_counts.items(), key=lambda item: (-item[1], item[0]))
        )
        lines.append(f"- Texture-type summary: {type_summary}")
    if semantic_subtype_counts:
        subtype_summary = ", ".join(
            f"{subtype}={count}"
            for subtype, count in sorted(semantic_subtype_counts.items(), key=lambda item: (-item[1], item[0]))
        )
        lines.append(f"- Semantic subtype summary: {subtype_summary}")
    if action_counts:
        action_summary = ", ".join(
            f"{action}={count}"
            for action, count in sorted(action_counts.items(), key=lambda item: (-item[1], item[0]))
        )
        lines.append(f"- Per-texture policy summary: {action_summary}")
    if path_kind_counts:
        path_summary = ", ".join(
            f"{path_kind}={count}"
            for path_kind, count in sorted(path_kind_counts.items(), key=lambda item: (-item[1], item[0]))
        )
        lines.append(f"- Planner path summary: {path_summary}")
    if preserve_reason_counts:
        preserved_due_to_technical = sum(
            count for reason, count in preserve_reason_counts.items() if "technical preserve path" in reason or "profile" in reason
        )
        preserved_due_to_precision = sum(
            count for reason, count in preserve_reason_counts.items() if "precision" in reason or "float" in reason or "snorm" in reason
        )
        preserved_due_to_alpha = sum(
            count for reason, count in preserve_reason_counts.items() if "alpha" in reason or "premultiplied" in reason
        )
        rebuilt_visible = path_kind_counts.get("visible_color_png_path", 0)
        rebuilt_high_precision = path_kind_counts.get("technical_high_precision_path", 0)
        lines.append(
            "- Planner summary counts: "
            f"technical_preserve={preserved_due_to_technical}, "
            f"precision_preserve={preserved_due_to_precision}, "
            f"alpha_preserve={preserved_due_to_alpha}, "
            f"visible_color_path={rebuilt_visible}, "
            f"technical_high_precision_path={rebuilt_high_precision}"
        )
    if policy_examples:
        lines.append("- Policy examples:")
        for example in policy_examples[:6]:
            lines.append(f"  {example}")
    if high_risk_examples:
        lines.append(
            "- Warning: precision-sensitive technical maps were detected "
            f"({'; '.join(high_risk_examples[:3])}). Safer presets keep these out of the upscale path."
        )
    if high_precision_examples:
        lines.append(
            "- Warning: float/snorm DDS formats were detected "
            f"({'; '.join(high_precision_examples[:3])}). PNG intermediates can lose precision for these assets."
        )
    if high_precision_path_examples:
        lines.append(
            "- Technical high-precision path examples: "
            + "; ".join(high_precision_path_examples[:3])
        )
    if high_precision_input_scan_total:
        lines.append(
            "- Technical high-precision PNG input preflight: "
            f"checked {high_precision_input_scan_total} planned files in PNG root because DDS staging is disabled."
        )
    if missing_high_precision_input_examples:
        lines.append(
            "- Warning: some planned technical high-precision files have no matching PNG input and will preserve the original DDS: "
            + "; ".join(missing_high_precision_input_examples[:3])
        )
    if invalid_high_precision_input_examples:
        lines.append(
            "- Warning: some planned technical high-precision files matched invalid PNG inputs and will preserve the original DDS: "
            + "; ".join(invalid_high_precision_input_examples[:3])
        )
    if blocked_high_precision_examples:
        lines.append(
            "- Technical high-precision path blocked under current settings: "
            + "; ".join(blocked_high_precision_examples[:3])
        )

    try:
        usage = shutil.disk_usage(normalized.output_root if normalized.output_root.exists() else normalized.output_root.parent)
        lines.append(f"- Free disk space near output root: {usage.free / (1024 * 1024 * 1024):.1f} GiB")
    except OSError:
        lines.append("- Free disk space near output root: unavailable")

    if normalized.upscale_backend == UPSCALE_BACKEND_REALESRGAN_NCNN:
        lines.append(f"- Real-ESRGAN NCNN executable: {normalized.ncnn_exe_path}")
        lines.append(f"- Real-ESRGAN NCNN model folder: {normalized.ncnn_model_dir}")
        lines.append(f"- Real-ESRGAN NCNN model: {normalized.ncnn_model_name}")
        lines.append(
            f"- Real-ESRGAN NCNN scale/tile/preset: {normalized.ncnn_scale}x / tile {normalized.ncnn_tile_size} / {normalized.upscale_texture_preset}"
        )
        if normalized.ncnn_extra_args:
            lines.append(f"- Real-ESRGAN NCNN extra args: {normalized.ncnn_extra_args}")
        lines.append(f"- Direct post-upscale correction: {normalized.upscale_post_correction_mode}")
    lines.append(
        f"- Automatic color/format rules: {'enabled' if normalized.enable_automatic_texture_rules else 'disabled'}"
    )
    lines.append(
        f"- Expert unsafe technical override: {'enabled' if normalized.enable_unsafe_technical_override else 'disabled'}"
    )
    lines.append(
        f"- Retry with smaller tile: {'enabled' if normalized.retry_smaller_tile_on_failure else 'disabled'}"
    )
    if normalized.enable_automatic_texture_rules:
        lines.append(
            "- Automatic rules now keep color-like textures sRGB-aware, prefer BC5 for normals, apply alpha-aware mip hints for cutout data, distinguish grayscale/packed technical maps more explicitly, and preserve original float/vector or packed-data DDS files when the PNG intermediate would be unsafe."
        )
    if normalized.enable_unsafe_technical_override:
        lines.append(
            "- Warning: expert unsafe technical override is enabled, so technical maps may be forced through the generic visible-color PNG/upscale path instead of being preserved."
        )
    if normalized.upscale_backend != UPSCALE_BACKEND_NONE:
        lines.append(
            "- Safe preset behavior: files excluded by the selected preset are copied through as original DDS files instead of being rebuilt from PNG."
        )
    lines.append(
        f"- Ready mod package export: {'enabled' if normalized.enable_mod_ready_loose_export else 'disabled'}"
    )
    if normalized.enable_mod_ready_loose_export and normalized.mod_ready_export_root is not None:
        expanded_options = mod_package_expanded_export_options(normalized.mod_ready_export_options, kind="dds_loose_mod")
        package_roots = [
            resolve_mod_package_profile_root(
                normalized.mod_ready_export_root,
                normalized.mod_ready_package_info,
                str(getattr(profile_options, "output_profile_suffix", "") or profile),
                multi_profile=bool(getattr(profile_options, "output_profile_suffix", "")),
            )
            for profile, profile_options in expanded_options
        ]
        lines.append(f"- Mod package parent root: {normalized.mod_ready_export_root}")
        lines.append(f"- Mod package folder: {', '.join(path.name for path in package_roots)}")
        lines.append(f"- Mod package output: {', '.join(str(path) for path in package_roots)}")
        lines.append(f"- .no_encrypt file: {'enabled' if normalized.mod_ready_create_no_encrypt_file else 'disabled'}")
    if chain_analysis and chain_analysis.warnings:
        lines.append("- chaiNNer preflight warnings:")
        for warning in chain_analysis.warnings[:5]:
            lines.append(f"  {warning}")

    return lines
