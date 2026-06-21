"""Refresh population state rules for the Research tab."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, TypeVar

from cdmw.core.research import (
    MaterialTextureReferenceRow,
    MipAnalysisRow,
    NormalValidationRow,
    TextureBudgetClassSummary,
    TextureBudgetGroupSummary,
    TextureBudgetProfileSummary,
    TextureBudgetRow,
    TextureClassificationRow,
    TextureSetGroup,
    TextureUsageHeatRow,
)

__all__ = [
    "ResearchRefreshPopulationRows",
    "ResearchRefreshStartState",
    "research_refresh_initial_status_text",
    "research_refresh_phase_status_text",
    "research_refresh_ready_status_text",
    "research_refresh_start_state",
    "research_refresh_population_rows",
    "research_refresh_population_total",
]

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ResearchRefreshPopulationRows:
    texture_groups: list[TextureSetGroup]
    classification_rows: list[TextureClassificationRow]
    heatmap_groups: list[tuple[str, list[TextureUsageHeatRow]]]
    mip_rows: list[MipAnalysisRow]
    normal_rows: list[NormalValidationRow]
    ui_constraint_rows: list[MaterialTextureReferenceRow]
    budget_rows: list[TextureBudgetRow]
    budget_class_rows: list[TextureBudgetClassSummary]
    budget_group_rows: list[TextureBudgetGroupSummary]
    budget_profile_rows: list[TextureBudgetProfileSummary]


@dataclass(frozen=True, slots=True)
class ResearchRefreshStartState:
    status_text: str
    user_status_text: str


def _typed_payload_rows(payload: object, row_type: type[T]) -> list[T]:
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, row_type)]


def research_refresh_population_rows(research_payload: Mapping[str, object]) -> ResearchRefreshPopulationRows:
    heatmap_groups_by_scope: dict[str, list[TextureUsageHeatRow]] = {}
    heatmap_groups: list[tuple[str, list[TextureUsageHeatRow]]] = []
    heatmap_rows = research_payload.get("heatmap_rows", [])
    if isinstance(heatmap_rows, list):
        for row in heatmap_rows:
            if not isinstance(row, TextureUsageHeatRow):
                continue
            if row.scope not in heatmap_groups_by_scope:
                heatmap_groups_by_scope[row.scope] = []
                heatmap_groups.append((row.scope, heatmap_groups_by_scope[row.scope]))
            heatmap_groups_by_scope[row.scope].append(row)
    budget_profile = research_payload.get("budget_profile")
    return ResearchRefreshPopulationRows(
        texture_groups=_typed_payload_rows(research_payload.get("texture_groups", []), TextureSetGroup),
        classification_rows=_typed_payload_rows(research_payload.get("classification_rows", []), TextureClassificationRow),
        heatmap_groups=heatmap_groups,
        mip_rows=_typed_payload_rows(research_payload.get("mip_rows", []), MipAnalysisRow),
        normal_rows=_typed_payload_rows(research_payload.get("normal_rows", []), NormalValidationRow),
        ui_constraint_rows=_typed_payload_rows(research_payload.get("ui_constraint_rows", []), MaterialTextureReferenceRow),
        budget_rows=_typed_payload_rows(research_payload.get("budget_rows", []), TextureBudgetRow),
        budget_class_rows=_typed_payload_rows(research_payload.get("budget_class_rows", []), TextureBudgetClassSummary),
        budget_group_rows=_typed_payload_rows(research_payload.get("budget_group_rows", []), TextureBudgetGroupSummary),
        budget_profile_rows=[budget_profile] if isinstance(budget_profile, TextureBudgetProfileSummary) else [],
    )


def research_refresh_population_total(rows: ResearchRefreshPopulationRows) -> int:
    return (
        len(rows.texture_groups)
        + len(rows.classification_rows)
        + len(rows.heatmap_groups)
        + len(rows.mip_rows)
        + len(rows.normal_rows)
        + len(rows.ui_constraint_rows)
        + len(rows.budget_rows)
        + len(rows.budget_class_rows)
        + len(rows.budget_group_rows)
        + len(rows.budget_profile_rows)
    )


def research_refresh_initial_status_text(*, uses_full_archive_view: bool, total: int) -> str:
    scope_text = "the full loaded archive" if uses_full_archive_view else "the current Archive Browser view"
    return f"Populating research snapshot for {scope_text}... 0 / {total:,}"


def research_refresh_start_state(
    *,
    uses_full_archive_view: bool,
    archive_entry_count: int,
    view_entry_count: int,
    has_cached_archive_snapshot: bool,
) -> ResearchRefreshStartState:
    scope_text = "the full loaded archive" if uses_full_archive_view else "the current Archive Browser view"
    entry_count = archive_entry_count if uses_full_archive_view else view_entry_count
    cache_text = " with cached archive insights" if has_cached_archive_snapshot else ""
    return ResearchRefreshStartState(
        status_text=f"Preparing research snapshot from {scope_text} ({entry_count:,} file(s)){cache_text}...",
        user_status_text=(
            "Refreshing research snapshot with cached archive insights..."
            if has_cached_archive_snapshot
            else "Refreshing research snapshot..."
        ),
    )


def research_refresh_phase_status_text(*, phase_name: object, processed: int, total: int) -> str:
    name = str(phase_name or "research")
    return f"Populating {name}... {processed:,} / {total:,}"


def research_refresh_ready_status_text(
    *,
    uses_full_archive_view: bool,
    archive_entry_count: int,
    view_entry_count: int,
) -> str:
    return (
        f"Research snapshot ready for the full loaded archive ({archive_entry_count:,} file(s))."
        if uses_full_archive_view
        else f"Research snapshot ready for the current Archive Browser view ({view_entry_count:,} file(s))."
    )
