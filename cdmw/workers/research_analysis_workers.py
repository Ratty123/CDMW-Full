"""Cancellable detail and output workers for Texture Research analysis."""

from __future__ import annotations

import threading
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.research.contracts import (
    MipAnalysisRow,
    NormalValidationRow,
    TextureBudgetClassSummary,
    TextureBudgetGroupSummary,
    TextureBudgetProfileSummary,
    TextureBudgetRow,
)
from cdmw.models import RunCancelled
from cdmw.services.research_service import research_service


FrozenRecord = tuple[tuple[str, object], ...]


def _freeze_value(value: object) -> object:
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((str(key), _freeze_value(item)) for key, item in value.items()))
    return value


def freeze_record(row: object) -> FrozenRecord:
    if not is_dataclass(row) or isinstance(row, type):
        raise TypeError("Research analysis snapshots require dataclass rows.")
    return tuple((field.name, _freeze_value(getattr(row, field.name))) for field in fields(row))


def _restore_record(row_type: type, record: FrozenRecord) -> object:
    return row_type(**dict(record))


@dataclass(frozen=True, slots=True)
class AnalysisDetailRequest:
    kind: str
    root_path: Path
    secondary_root_path: Path | None
    texconv_path: Path | None
    row: FrozenRecord
    family_members: tuple[str, ...] = ()
    request_id: int = 0


@dataclass(frozen=True, slots=True)
class AnalysisDetailResult:
    request_id: int
    kind: str
    detail_text: str


@dataclass(frozen=True, slots=True)
class AnalysisReportExportRequest:
    output_path: Path
    mip_rows: tuple[FrozenRecord, ...]
    normal_rows: tuple[FrozenRecord, ...]
    budget_rows: tuple[FrozenRecord, ...]
    budget_class_rows: tuple[FrozenRecord, ...]
    budget_group_rows: tuple[FrozenRecord, ...]
    budget_profile: FrozenRecord | None
    request_id: int = 0


@dataclass(frozen=True, slots=True)
class AnalysisReportExportResult:
    request_id: int
    output_path: Path


def mip_detail_request(
    original_root: Path,
    rebuilt_root: Path,
    texconv_path: Path | None,
    row: MipAnalysisRow,
    family_members: Sequence[str],
) -> AnalysisDetailRequest:
    return AnalysisDetailRequest(
        "mip",
        Path(original_root),
        Path(rebuilt_root),
        Path(texconv_path) if texconv_path is not None else None,
        freeze_record(row),
        tuple(str(path) for path in family_members),
    )


def normal_detail_request(
    root: Path,
    texconv_path: Path | None,
    row: NormalValidationRow,
) -> AnalysisDetailRequest:
    return AnalysisDetailRequest(
        "normal",
        Path(root),
        None,
        Path(texconv_path) if texconv_path is not None else None,
        freeze_record(row),
    )


def report_export_request(
    output_path: Path,
    *,
    mip_rows: Sequence[object],
    normal_rows: Sequence[object],
    budget_rows: Sequence[object],
    budget_class_rows: Sequence[object],
    budget_group_rows: Sequence[object],
    budget_profile: object | None,
) -> AnalysisReportExportRequest:
    return AnalysisReportExportRequest(
        Path(output_path),
        tuple(freeze_record(row) for row in mip_rows),
        tuple(freeze_record(row) for row in normal_rows),
        tuple(freeze_record(row) for row in budget_rows),
        tuple(freeze_record(row) for row in budget_class_rows),
        tuple(freeze_record(row) for row in budget_group_rows),
        freeze_record(budget_profile) if budget_profile is not None else None,
    )


def run_analysis_detail_request(
    request: AnalysisDetailRequest,
    *,
    stop_event: Optional[threading.Event] = None,
) -> AnalysisDetailResult:
    raise_if_cancelled(stop_event, "Research analysis detail cancelled.")
    if request.kind == "mip":
        if request.secondary_root_path is None:
            raise ValueError("Mip detail requires an output root.")
        row = _restore_record(MipAnalysisRow, request.row)
        detail = research_service.texture_analysis.build_mip_detail(
            request.root_path,
            request.secondary_root_path,
            row,
            texconv_path=request.texconv_path,
            family_members_by_path={row.relative_path: request.family_members},
            stop_event=stop_event,
        )
    elif request.kind == "normal":
        row = _restore_record(NormalValidationRow, request.row)
        detail = research_service.texture_analysis.build_normal_detail(
            request.root_path,
            row,
            texconv_path=request.texconv_path,
            stop_event=stop_event,
        )
    else:
        raise ValueError(f"Unsupported research detail kind: {request.kind}")
    raise_if_cancelled(stop_event, "Research analysis detail cancelled.")
    return AnalysisDetailResult(request.request_id, request.kind, detail)


def run_analysis_report_export(
    request: AnalysisReportExportRequest,
    *,
    stop_event: Optional[threading.Event] = None,
) -> AnalysisReportExportResult:
    mip_rows = tuple(_restore_record(MipAnalysisRow, row) for row in request.mip_rows)
    normal_rows = tuple(_restore_record(NormalValidationRow, row) for row in request.normal_rows)
    budget_rows = tuple(_restore_record(TextureBudgetRow, row) for row in request.budget_rows)
    class_rows = tuple(_restore_record(TextureBudgetClassSummary, row) for row in request.budget_class_rows)
    group_rows = tuple(_restore_record(TextureBudgetGroupSummary, row) for row in request.budget_group_rows)
    profile = (
        _restore_record(TextureBudgetProfileSummary, request.budget_profile)
        if request.budget_profile is not None
        else None
    )
    raise_if_cancelled(stop_event, "Texture analysis report export cancelled.")
    output_path = research_service.texture_analysis.export_report(
        request.output_path,
        mip_rows,
        normal_rows,
        budget_rows=budget_rows,
        budget_class_rows=class_rows,
        budget_group_rows=group_rows,
        budget_profile=profile,
        stop_event=stop_event,
    )
    return AnalysisReportExportResult(request.request_id, output_path)


class _ResearchAnalysisWorker(QObject):
    completed = Signal(object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(self, request: object, operation: object) -> None:
        super().__init__()
        self.request = request
        self.operation = operation
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            result = self.operation(self.request, stop_event=self.stop_event)
            raise_if_cancelled(self.stop_event)
            self.completed.emit(result)
        except RunCancelled:
            pass
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(int(getattr(self.request, "request_id", -1)), str(exc))
        finally:
            self.finished.emit()


class AnalysisDetailWorker(_ResearchAnalysisWorker):
    def __init__(self, request: AnalysisDetailRequest) -> None:
        super().__init__(request, run_analysis_detail_request)


class AnalysisReportExportWorker(_ResearchAnalysisWorker):
    def __init__(self, request: AnalysisReportExportRequest) -> None:
        super().__init__(request, run_analysis_report_export)


__all__ = [
    "AnalysisDetailRequest",
    "AnalysisDetailResult",
    "AnalysisDetailWorker",
    "AnalysisReportExportRequest",
    "AnalysisReportExportResult",
    "AnalysisReportExportWorker",
    "freeze_record",
    "mip_detail_request",
    "normal_detail_request",
    "report_export_request",
    "run_analysis_detail_request",
    "run_analysis_report_export",
]
