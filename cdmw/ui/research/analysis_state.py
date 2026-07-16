"""Analysis and budget display state rules for the Research tab."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence

from cdmw.domain.textures.plan import describe_processing_path_kind
from cdmw.domain.research.contracts import (
    MipAnalysisRow,
    NormalValidationRow,
    TextureBudgetClassSummary,
    TextureBudgetGroupSummary,
    TextureBudgetProfileSummary,
    TextureBudgetRow,
)

__all__ = [
    "ANALYSIS_CONTEXT_HELP_TEXT",
    "MissingMipFocusState",
    "MipFocusRefreshPendingState",
    "ResearchAnalysisReportRows",
    "analysis_report_default_name",
    "analysis_report_exported_status_text",
    "analysis_report_missing_status_text",
    "analysis_report_output_path",
    "compare_path_missing_status_text",
    "budget_detail_payload",
    "mip_analysis_tooltip_lines",
    "mip_focus_refresh_pending_state",
    "missing_mip_focus_state",
    "normal_validation_tooltip_lines",
    "research_analysis_report_rows",
    "texture_analysis_context_text",
]

ANALYSIS_CONTEXT_HELP_TEXT = (
    "Texture Analysis uses your current Original DDS root and Output root. Refresh Research after changing either folder.\n\n"
    "Mip Analysis compares matching DDS files found in both Original DDS root and Output root, including header validity, file-size drift, color-space changes, native preview-based alpha and brightness checks, and texture-specific warnings for normals, packed masks, and grayscale technical maps. "
    "Bulk Normal Validator scans normal-like DDS files from whichever of those roots currently exist. "
    "Budget Analysis adds exact mod-vs-vanilla growth metrics plus clearly labeled heuristic risk summaries."
)


@dataclass(frozen=True, slots=True)
class ResearchAnalysisReportRows:
    mip_rows: list[object]
    normal_rows: list[object]
    budget_rows: list[object]
    budget_class_rows: list[object]
    budget_group_rows: list[object]
    budget_profile: Optional[TextureBudgetProfileSummary]


@dataclass(frozen=True, slots=True)
class MissingMipFocusState:
    status_text: str
    detail_label: str
    detail_text: str
    user_status_text: str


@dataclass(frozen=True, slots=True)
class MipFocusRefreshPendingState:
    status_text: str
    user_status_text: str


def research_analysis_report_rows(research_payload: Mapping[str, object]) -> Optional[ResearchAnalysisReportRows]:
    mip_rows = research_payload.get("mip_rows", [])
    normal_rows = research_payload.get("normal_rows", [])
    if not isinstance(mip_rows, list) or not isinstance(normal_rows, list):
        return None
    budget_rows = research_payload.get("budget_rows", [])
    budget_class_rows = research_payload.get("budget_class_rows", [])
    budget_group_rows = research_payload.get("budget_group_rows", [])
    budget_profile = research_payload.get("budget_profile")
    return ResearchAnalysisReportRows(
        mip_rows=mip_rows,
        normal_rows=normal_rows,
        budget_rows=budget_rows if isinstance(budget_rows, list) else [],
        budget_class_rows=budget_class_rows if isinstance(budget_class_rows, list) else [],
        budget_group_rows=budget_group_rows if isinstance(budget_group_rows, list) else [],
        budget_profile=budget_profile if isinstance(budget_profile, TextureBudgetProfileSummary) else None,
    )


def missing_mip_focus_state(target_path: str) -> MissingMipFocusState:
    return MissingMipFocusState(
        status_text=(
            f"No Mip Analysis row was found for {target_path}. Refresh Research again after verifying both DDS roots."
        ),
        detail_label="Mip Analysis details",
        detail_text=(
            "No matching Mip Analysis row was found for the selected Compare file in the current Research snapshot.\n\n"
            f"Relative path: {target_path}\n\n"
            "This usually means the same DDS path was not found in both Original DDS root and Output root, or the "
            "current roots changed before Research was refreshed."
        ),
        user_status_text=(
            f"No Mip Analysis row was found for {target_path}. Check the current DDS roots and refresh Research again."
        ),
    )


def compare_path_missing_status_text() -> str:
    return "Select a DDS file in Compare first."


def mip_focus_refresh_pending_state(target_path: str) -> MipFocusRefreshPendingState:
    status_text = f"Research refresh already running. Will focus mip analysis for {target_path} when ready."
    return MipFocusRefreshPendingState(status_text=status_text, user_status_text=status_text)


def analysis_report_default_name(default_suffix: str) -> str:
    return f"texture_analysis_report{default_suffix}"


def analysis_report_output_path(selected_path: str, default_suffix: str) -> Path | None:
    if not selected_path:
        return None
    report_path = Path(selected_path)
    if report_path.suffix.lower() not in {".csv", ".json"}:
        return report_path.with_suffix(default_suffix)
    return report_path


def analysis_report_missing_status_text() -> str:
    return "Refresh Research first to build an analysis report."


def analysis_report_exported_status_text(final_path: Path) -> str:
    return f"Exported analysis report to {final_path}"


def _planner_tooltip_lines(
    *,
    warnings_or_issues: Sequence[str],
    planner_profile: str,
    planner_path_kind: str,
    planner_backend_mode: str,
    planner_alpha_policy: str,
    planner_preserve_reason: str,
) -> list[str]:
    tooltip_lines = list(warnings_or_issues)
    if planner_profile or planner_path_kind:
        tooltip_lines.extend(
            [
                "",
                f"Planner profile: {planner_profile or 'unavailable'}",
                f"Planner path: {planner_path_kind or 'unavailable'}",
                f"Planner path detail: {describe_processing_path_kind(planner_path_kind) if planner_path_kind else 'unavailable'}",
                f"Planner backend mode: {planner_backend_mode or 'unavailable'}",
                f"Planner alpha policy: {planner_alpha_policy or 'unavailable'}",
            ]
        )
        if planner_preserve_reason:
            tooltip_lines.append(f"Planner preserve reason: {planner_preserve_reason}")
    return [line for line in tooltip_lines if line]


def mip_analysis_tooltip_lines(row: MipAnalysisRow) -> list[str]:
    return _planner_tooltip_lines(
        warnings_or_issues=row.warnings,
        planner_profile=row.planner_profile,
        planner_path_kind=row.planner_path_kind,
        planner_backend_mode=row.planner_backend_mode,
        planner_alpha_policy=row.planner_alpha_policy,
        planner_preserve_reason=row.planner_preserve_reason,
    )


def normal_validation_tooltip_lines(row: NormalValidationRow) -> list[str]:
    return _planner_tooltip_lines(
        warnings_or_issues=row.issues,
        planner_profile=row.planner_profile,
        planner_path_kind=row.planner_path_kind,
        planner_backend_mode=row.planner_backend_mode,
        planner_alpha_policy=row.planner_alpha_policy,
        planner_preserve_reason=row.planner_preserve_reason,
    )


def budget_detail_payload(row: object) -> tuple[str, str] | None:
    if isinstance(row, TextureBudgetRow):
        detail_lines = [
            f"Path: {row.relative_path}",
            f"Group key: {row.group_key}",
            f"System area: {row.system_area}",
            f"Folder bucket: {row.folder_bucket}",
            f"Texture type: {row.texture_type}",
            f"Planner profile: {row.planner_profile or 'unavailable'}",
            f"Planner path kind: {row.planner_path_kind or 'unavailable'}",
            f"Planner alpha policy: {row.planner_alpha_policy or 'unavailable'}",
            f"Original bytes: {row.original_bytes:,}",
            f"Rebuilt bytes: {row.rebuilt_bytes:,}",
            f"Byte delta: {row.byte_delta:+,}",
            f"Byte ratio: {row.byte_ratio:.2f}x",
            f"Original size: {row.original_width}x{row.original_height}",
            f"Rebuilt size: {row.rebuilt_width}x{row.rebuilt_height}",
            f"Pixel ratio: {row.pixel_ratio:.2f}x",
            f"Mips: {row.original_mips} -> {row.rebuilt_mips} (delta {row.mip_delta:+d})",
            f"Format: {row.original_format} -> {row.rebuilt_format}",
            f"UI rect evidence: {row.ui_constraint_summary or 'none'}",
            f"Risk: {row.risk_score} ({row.risk_band})",
            "",
            "Signals:",
            *[f"- {signal}" for signal in row.risk_signals],
        ]
        return ("Budget file details", "\n".join(detail_lines))
    if isinstance(row, TextureBudgetClassSummary):
        return (
            "Budget class summary",
            "\n".join(
                [
                    f"Texture type: {row.texture_type}",
                    f"Affected textures: {row.affected_count:,}",
                    f"Total byte delta: {row.total_byte_delta:+,}",
                    f"Average risk: {row.average_risk:.1f} ({row.risk_band})",
                    "",
                    "Sample paths:",
                    *[f"- {path}" for path in row.sample_paths],
                ]
            ),
        )
    if isinstance(row, TextureBudgetGroupSummary):
        return (
            "Terrain-like group summary",
            "\n".join(
                [
                    f"Group key: {row.group_key}",
                    f"System area: {row.system_area}",
                    f"Textures: {row.texture_count:,}",
                    f"Original bytes: {row.total_original_bytes:,}",
                    f"Rebuilt bytes: {row.total_rebuilt_bytes:,}",
                    f"Byte delta: {row.total_byte_delta:+,}",
                    f"Average ratio: {row.average_byte_ratio:.2f}x",
                    f"Max ratio: {row.max_byte_ratio:.2f}x",
                    f"Average dimensions: {row.average_width:.1f} x {row.average_height:.1f}",
                    f"2048+ members: {row.large_2048_count}",
                    f"4096+ members: {row.large_4096_count}",
                    f"Risk: {row.risk_score} ({row.risk_band})",
                    "",
                    "Signals:",
                    *[f"- {signal}" for signal in row.signals],
                ]
            ),
        )
    if isinstance(row, TextureBudgetProfileSummary):
        return (
            "Budget profile summary",
            "\n".join(
                [
                    f"Profile: {row.profile_label}",
                    f"Original bytes: {row.total_original_bytes:,}",
                    f"Rebuilt bytes: {row.total_rebuilt_bytes:,}",
                    f"Byte delta: {row.total_byte_delta:+,}",
                    f"Total ratio: {row.total_byte_ratio:.2f}x",
                    f"Changed textures: {row.changed_texture_count:,}",
                    f"Upscaled textures: {row.upscaled_texture_count:,}",
                    f"High-risk fraction: {row.high_risk_texture_fraction * 100.0:.1f}%",
                    f"Highest terrain-like group risk: {row.highest_group_risk}",
                    "",
                    "Reasons:",
                    *[f"- {reason}" for reason in row.reasons],
                ]
            ),
        )
    return None


def texture_analysis_context_text(
    *,
    original_root_text: str,
    output_root_text: str,
    research_payload: Mapping[str, object],
) -> str:
    original_root_text = str(original_root_text or "").strip()
    output_root_text = str(output_root_text or "").strip()
    original_root = Path(original_root_text).expanduser() if original_root_text else None
    output_root = Path(output_root_text).expanduser() if output_root_text else None
    original_exists = original_root is not None and original_root.exists()
    output_exists = output_root is not None and output_root.exists()
    mip_rows = research_payload.get("mip_rows", [])
    normal_rows = research_payload.get("normal_rows", [])
    budget_rows = research_payload.get("budget_rows", [])
    budget_profile = research_payload.get("budget_profile")
    mip_count = len(mip_rows) if isinstance(mip_rows, list) else 0
    normal_count = len(normal_rows) if isinstance(normal_rows, list) else 0
    budget_count = len(budget_rows) if isinstance(budget_rows, list) else 0
    planner_path_counts: dict[str, int] = {}
    planner_profile_counts: dict[str, int] = {}
    if isinstance(mip_rows, list):
        for row in mip_rows:
            if isinstance(row, MipAnalysisRow):
                if row.planner_path_kind:
                    planner_path_counts[row.planner_path_kind] = planner_path_counts.get(row.planner_path_kind, 0) + 1
                if row.planner_profile:
                    planner_profile_counts[row.planner_profile] = planner_profile_counts.get(row.planner_profile, 0) + 1
    normal_roots: dict[str, int] = {}
    if isinstance(normal_rows, list):
        for row in normal_rows:
            if isinstance(row, NormalValidationRow):
                normal_roots[row.root_label] = normal_roots.get(row.root_label, 0) + 1
    normal_root_summary = ", ".join(
        f"{label}: {count:,}" for label, count in sorted(normal_roots.items())
    ) if normal_roots else "none"
    planner_path_summary = ", ".join(
        f"{label}: {count:,}" for label, count in sorted(planner_path_counts.items())
    ) if planner_path_counts else "unavailable"
    planner_profile_summary = ", ".join(
        f"{label}: {count:,}" for label, count in sorted(planner_profile_counts.items())
    ) if planner_profile_counts else "unavailable"
    return (
        "Texture Analysis context:\n"
        f"- Original DDS root: {original_root if original_root_text else '(not set)'}"
        + (" (available)" if original_exists else " (missing or not set)")
        + "\n"
        f"- Output root: {output_root if output_root_text else '(not set)'}"
        + (" (available)" if output_exists else " (missing or not set)")
        + "\n"
        f"- Mip Analysis rows: {mip_count:,} matching DDS file pair(s). Requires the same relative DDS path to exist in both roots. Uses DirectXTex/native previews when available for alpha, brightness, range, and channel-drift checks.\n"
        f"- Planner path summary: {planner_path_summary}.\n"
        f"- Planner profile summary: {planner_profile_summary}.\n"
        f"- Bulk Normal Validator rows: {normal_count:,} normal-like DDS file(s). Current roots represented: {normal_root_summary}.\n"
        f"- Budget rows: {budget_count:,} matching DDS pair(s)."
        + (
            f" Current heuristic budget profile: {budget_profile.profile_label}."
            if isinstance(budget_profile, TextureBudgetProfileSummary)
            else ""
        )
    )
