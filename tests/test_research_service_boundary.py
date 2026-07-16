from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from cdmw.core import atomic_file, research_archive_analysis
from cdmw.domain.research.contracts import MipAnalysisRow, ResearchNote
from cdmw.models import ArchivePreviewResult
from cdmw.services.research_notes_service import ResearchNotesService
from cdmw.services.research_service import (
    ResearchArchiveService,
    ResearchPreviewService,
    ResearchTextureAnalysisService,
)
from cdmw.ui.research.workers import UnknownResolverPreviewWorker
from cdmw.workers.research_analysis_workers import report_export_request, run_analysis_report_export


def _note(text: str) -> ResearchNote:
    return ResearchNote(
        target_key="texture/example.dds",
        source_kind="archive",
        tags=["review"],
        note=text,
        updated_at="2026-07-10T00:00:00+00:00",
    )


def _mip_row(path: str) -> MipAnalysisRow:
    return MipAnalysisRow(path, "BC7", "BC7", "4x4", "4x4", 1, 1, 0)


def test_research_notes_publish_atomically_and_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes_path = tmp_path / "research_notes.json"
    service = ResearchNotesService()
    service.save(notes_path, {"texture/example.dds": _note("original")})
    original_bytes = notes_path.read_bytes()

    def fail_publish(_source: object, _destination: object) -> None:
        raise OSError("injected publish failure")

    monkeypatch.setattr(atomic_file.os, "replace", fail_publish)
    with pytest.raises(OSError, match="injected publish failure"):
        service.save(notes_path, {"texture/example.dds": _note("replacement")})

    assert notes_path.read_bytes() == original_bytes
    assert service.load(notes_path)["texture/example.dds"].note == "original"
    assert not list(tmp_path.glob(".research_notes.json.*.tmp"))


def test_research_archive_service_is_explicit_and_delegates_to_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = {"classification_rows": []}
    received: dict[str, object] = {}

    def fake_snapshot(entries: object, **kwargs: object) -> dict[str, object]:
        received["entries"] = entries
        received.update(kwargs)
        return sentinel

    monkeypatch.setattr(research_archive_analysis, "build_archive_research_snapshot", fake_snapshot)
    service = ResearchArchiveService()
    result = service.build_snapshot([], classification_limit=7, group_limit=3)

    assert result is sentinel
    assert received["classification_limit"] == 7
    assert received["group_limit"] == 3
    assert not any(
        parameter.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
        for parameter in inspect.signature(service.build_snapshot).parameters.values()
    )


def test_unknown_preview_worker_routes_preview_through_research_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, object]] = []

    def fake_preview(
        _self: ResearchPreviewService,
        entry: object,
        *,
        stop_event: object,
    ) -> ArchivePreviewResult:
        calls.append(("native", entry))
        assert stop_event is not None
        return ArchivePreviewResult(status="ok", title="real preview")

    monkeypatch.setattr(ResearchPreviewService, "build_archive_preview", fake_preview)
    worker = UnknownResolverPreviewWorker(12, None)
    completed: list[tuple[int, ArchivePreviewResult]] = []
    worker.completed.connect(lambda request_id, result: completed.append((request_id, result)))

    worker.run()

    assert calls == [("native", None)]
    assert completed[0][0] == 12
    assert completed[0][1].title == "real preview"


def test_analysis_export_worker_routes_transaction_through_research_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "analysis.json"
    calls: list[Path] = []

    def fake_export(
        _self: ResearchTextureAnalysisService,
        report_path: Path,
        _mip_rows: object,
        _normal_rows: object,
        **_kwargs: object,
    ) -> Path:
        calls.append(report_path)
        return report_path

    monkeypatch.setattr(ResearchTextureAnalysisService, "export_report", fake_export)
    request = report_export_request(
        output_path,
        mip_rows=[_mip_row("texture/example.dds")],
        normal_rows=[],
        budget_rows=[],
        budget_class_rows=[],
        budget_group_rows=[],
        budget_profile=None,
    )

    result = run_analysis_report_export(request)

    assert result.output_path == output_path
    assert calls == [output_path]
