"""Composed Research operations used by UI-owned background workers."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from cdmw.domain.research.contracts import (
    MaterialTextureReferenceRow,
    MipAnalysisRow,
    NormalValidationRow,
    SidecarDiscoveryRow,
    TextureBudgetClassSummary,
    TextureBudgetGroupSummary,
    TextureBudgetProfileSummary,
    TextureBudgetRow,
    TextureClassificationRow,
    TextureSetGroup,
    TextureUsageHeatRow,
    UnknownResolverGroup,
)
from cdmw.models import AppConfig, ArchiveEntry, ArchivePreviewResult, TextureProcessingPlan
from cdmw.services.research_notes_service import ResearchNotesService


ProgressCallback = Callable[[int, int, str], None]


@dataclass(slots=True)
class ResearchArchiveService:
    def build_snapshot(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        classification_limit: int = 3000,
        group_limit: int = 2000,
        heatmap_limit_per_scope: int = 24,
        sidecar_source_entries: Optional[Sequence[ArchiveEntry]] = None,
        stop_event: Optional[object] = None,
        on_progress: Optional[ProgressCallback] = None,
    ) -> Dict[str, object]:
        from cdmw.core.research_archive_analysis import build_archive_research_snapshot

        return build_archive_research_snapshot(
            entries,
            classification_limit=classification_limit,
            group_limit=group_limit,
            heatmap_limit_per_scope=heatmap_limit_per_scope,
            sidecar_source_entries=sidecar_source_entries,
            stop_event=stop_event,
            on_progress=on_progress,
        )

    def classify_textures(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        limit: int = 3000,
    ) -> List[TextureClassificationRow]:
        from cdmw.core.research_archive_analysis import classify_texture_entries

        return classify_texture_entries(entries, limit=limit)

    def bundle_texture_sets(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        limit: int = 2000,
    ) -> List[TextureSetGroup]:
        from cdmw.core.research_classification import bundle_texture_sets

        return bundle_texture_sets(entries, limit=limit)


@dataclass(slots=True)
class ResearchReferenceService:
    def resolve_material_references(
        self,
        entries: Sequence[ArchiveEntry],
        target_path: str,
        *,
        limit: int = 240,
        on_progress: Optional[ProgressCallback] = None,
        stop_event: Optional[object] = None,
    ) -> Tuple[List[MaterialTextureReferenceRow], Dict[str, object]]:
        from cdmw.core.research_references import resolve_material_texture_references

        return resolve_material_texture_references(
            entries,
            target_path,
            limit=limit,
            on_progress=on_progress,
            stop_event=stop_event,
        )

    def discover_sidecars(
        self,
        entries: Sequence[ArchiveEntry],
        target_path: str,
        *,
        limit: int = 120,
        stop_event: Optional[object] = None,
    ) -> List[SidecarDiscoveryRow]:
        from cdmw.core.research_references import discover_archive_sidecars

        return discover_archive_sidecars(entries, target_path, limit=limit, stop_event=stop_event)

    def build_ui_constraint_rows(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        limit: int = 2000,
        stop_event: Optional[object] = None,
        on_progress: Optional[ProgressCallback] = None,
    ) -> List[MaterialTextureReferenceRow]:
        from cdmw.core.research_references import build_ui_constraint_reference_rows

        return build_ui_constraint_reference_rows(
            entries,
            limit=limit,
            stop_event=stop_event,
            on_progress=on_progress,
        )

    def summarize_ui_constraints(
        self,
        entries: Sequence[ArchiveEntry],
        target_path: str,
        *,
        stop_event: Optional[object] = None,
    ) -> Dict[str, object]:
        from cdmw.core.research_references import summarize_ui_reference_constraints

        return summarize_ui_reference_constraints(entries, target_path, stop_event=stop_event)


@dataclass(slots=True)
class ResearchClassificationService:
    def build_detail(
        self,
        group: UnknownResolverGroup,
        selected_member_path: str,
        *,
        entries_by_path: Dict[str, ArchiveEntry],
        texconv_path: Optional[Path] = None,
    ) -> str:
        from cdmw.core.research_classification import build_unknown_resolver_detail

        return build_unknown_resolver_detail(
            group,
            selected_member_path,
            entries_by_path=entries_by_path,
            texconv_path=texconv_path,
        )


@dataclass(slots=True)
class ResearchTextureAnalysisService:
    def analyze_mips(
        self,
        original_root: Path,
        rebuilt_root: Path,
        *,
        texconv_path: Optional[Path] = None,
        limit: int = 3000,
        processing_plan_lookup: Optional[Dict[str, TextureProcessingPlan]] = None,
        stop_event: Optional[object] = None,
        family_members_by_path: Optional[Dict[str, Tuple[str, ...]]] = None,
    ) -> List[MipAnalysisRow]:
        from cdmw.core.research_texture_analysis import analyze_mip_behavior

        return analyze_mip_behavior(
            original_root,
            rebuilt_root,
            texconv_path=texconv_path,
            limit=limit,
            processing_plan_lookup=processing_plan_lookup,
            stop_event=stop_event,
            family_members_by_path=family_members_by_path,
        )

    def mip_family_members(
        self,
        original_root: Path,
        rebuilt_root: Path,
        *,
        stop_event: Optional[object] = None,
    ) -> Dict[str, Tuple[str, ...]]:
        from cdmw.core.research_texture_analysis import build_mip_analysis_family_members_by_path

        return build_mip_analysis_family_members_by_path(original_root, rebuilt_root, stop_event=stop_event)

    def processing_plan_lookup(
        self,
        app_config: AppConfig,
        *,
        original_root_override: Optional[Path] = None,
        stop_event: Optional[object] = None,
    ) -> Dict[str, TextureProcessingPlan]:
        from cdmw.core.research_texture_analysis import build_processing_plan_lookup

        return build_processing_plan_lookup(
            app_config,
            original_root_override=original_root_override,
            stop_event=stop_event,
        )

    def texture_budget(
        self,
        original_root: Path,
        rebuilt_root: Path,
        *,
        processing_plan_lookup: Optional[Dict[str, TextureProcessingPlan]] = None,
        archive_entries: Sequence[ArchiveEntry] = (),
        ui_constraint_related_paths: Sequence[str] = (),
        stop_event: Optional[object] = None,
    ) -> Dict[str, object]:
        from cdmw.core.research_texture_analysis import build_texture_budget_analysis

        return build_texture_budget_analysis(
            original_root,
            rebuilt_root,
            processing_plan_lookup=processing_plan_lookup,
            archive_entries=archive_entries,
            ui_constraint_related_paths=ui_constraint_related_paths,
            stop_event=stop_event,
        )

    def texture_usage_heatmap(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        limit_per_scope: int = 24,
    ) -> List[TextureUsageHeatRow]:
        from cdmw.core.research_texture_analysis import build_texture_usage_heatmap

        return build_texture_usage_heatmap(entries, limit_per_scope=limit_per_scope)

    def validate_normals(
        self,
        root: Path,
        *,
        root_label: Optional[str] = None,
        texconv_path: Optional[Path] = None,
        limit: int = 1500,
        processing_plan_lookup: Optional[Dict[str, TextureProcessingPlan]] = None,
        stop_event: Optional[object] = None,
    ) -> List[NormalValidationRow]:
        from cdmw.core.research_texture_analysis import validate_normal_maps

        return validate_normal_maps(
            root,
            root_label=root_label,
            texconv_path=texconv_path,
            limit=limit,
            processing_plan_lookup=processing_plan_lookup,
            stop_event=stop_event,
        )

    def build_mip_detail(
        self,
        original_root: Path,
        rebuilt_root: Path,
        row: MipAnalysisRow,
        *,
        texconv_path: Optional[Path] = None,
        family_members_by_path: Optional[Dict[str, Tuple[str, ...]]] = None,
        stop_event: Optional[object] = None,
    ) -> str:
        from cdmw.core.research_texture_analysis import build_mip_analysis_detail

        return build_mip_analysis_detail(
            original_root,
            rebuilt_root,
            row,
            texconv_path=texconv_path,
            family_members_by_path=family_members_by_path,
            stop_event=stop_event,
        )

    def build_normal_detail(
        self,
        root: Path,
        row: NormalValidationRow,
        *,
        texconv_path: Optional[Path] = None,
        stop_event: Optional[object] = None,
    ) -> str:
        from cdmw.core.research_texture_analysis import build_normal_validation_detail

        return build_normal_validation_detail(root, row, texconv_path=texconv_path, stop_event=stop_event)

    def export_report(
        self,
        report_path: Path,
        mip_rows: Sequence[MipAnalysisRow],
        normal_rows: Sequence[NormalValidationRow],
        *,
        budget_rows: Sequence[TextureBudgetRow] = (),
        budget_class_rows: Sequence[TextureBudgetClassSummary] = (),
        budget_group_rows: Sequence[TextureBudgetGroupSummary] = (),
        budget_profile: Optional[TextureBudgetProfileSummary] = None,
        stop_event: Optional[object] = None,
    ) -> Path:
        from cdmw.core.research_texture_analysis import export_texture_analysis_report

        return export_texture_analysis_report(
            report_path,
            mip_rows,
            normal_rows,
            budget_rows=budget_rows,
            budget_class_rows=budget_class_rows,
            budget_group_rows=budget_group_rows,
            budget_profile=budget_profile,
            stop_event=stop_event,
        )


@dataclass(slots=True)
class ResearchPreviewService:
    def build_archive_preview(
        self,
        texconv_path: Optional[Path],
        entry: Optional[ArchiveEntry],
        *,
        stop_event: Optional[threading.Event] = None,
    ) -> ArchivePreviewResult:
        from cdmw.services.archive_preview_service import build_archive_preview_result

        return build_archive_preview_result(texconv_path, entry, [], stop_event=stop_event)


@dataclass(slots=True)
class ResearchService:
    settings: object | None = None
    archive: ResearchArchiveService = field(default_factory=ResearchArchiveService)
    references: ResearchReferenceService = field(default_factory=ResearchReferenceService)
    classification: ResearchClassificationService = field(default_factory=ResearchClassificationService)
    texture_analysis: ResearchTextureAnalysisService = field(default_factory=ResearchTextureAnalysisService)
    preview: ResearchPreviewService = field(default_factory=ResearchPreviewService)
    notes: ResearchNotesService = field(default_factory=ResearchNotesService)


research_service = ResearchService()


__all__ = [
    "ResearchArchiveService",
    "ResearchClassificationService",
    "ResearchPreviewService",
    "ResearchReferenceService",
    "ResearchService",
    "ResearchTextureAnalysisService",
    "research_service",
]
