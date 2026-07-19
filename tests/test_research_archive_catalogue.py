from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from cdmw.domain.archives.catalogue import (
    ArchiveDurableIdentity,
    ArchiveEntryDto,
    ArchiveEntryRef,
    ArchiveEntryRole,
    ArchiveLookupResult,
    ArchivePage,
    ArchiveQueryHandle,
    ArchiveSessionHandle,
)
from cdmw.domain.archives.catalogue_operations import PrepareEntriesResult, PrepareEntryResult
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.ui.research.remote_catalogue import (
    REMOTE_RESEARCH_COMPATIBILITY_ENTRY_LIMIT,
    ResearchArchiveCatalogueMixin,
)


class _Value:
    def __init__(self) -> None:
        self.enabled = True
        self.text = ""

    def setEnabled(self, value: bool) -> None:
        self.enabled = value

    def setRange(self, _minimum: int, _maximum: int) -> None:
        return

    def setText(self, value: str) -> None:
        self.text = value


class _CatalogueService(QObject):
    progress = Signal(str, object)
    batch_ready = Signal(str, str, object)
    result_ready = Signal(str, str, object)
    request_failed = Signal(str, object)
    request_cancelled = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.page_requests: list[tuple[object, int]] = []
        self.lookup_requests: list[tuple[object, int]] = []
        self.prepare_many_requests: list[tuple[object, int]] = []
        self.prepare_requests: list[tuple[object, int]] = []
        self.cancelled: list[str] = []

    def resolve_entries(self, request: object, *, ui_generation: int) -> str:
        self.lookup_requests.append((request, ui_generation))
        return f"lookup-{len(self.lookup_requests)}"

    def fetch_page(self, request: object, *, ui_generation: int) -> str:
        self.page_requests.append((request, ui_generation))
        return f"fetch-{len(self.page_requests)}"

    def prepare_entries(self, request: object, *, ui_generation: int) -> str:
        self.prepare_many_requests.append((request, ui_generation))
        return f"prepare-many-{len(self.prepare_many_requests)}"

    def prepare_entry(self, request: object, *, ui_generation: int) -> str:
        self.prepare_requests.append((request, ui_generation))
        return f"prepare-{len(self.prepare_requests)}"

    def cancel(self, request_id: str) -> bool:
        self.cancelled.append(request_id)
        return True

    compatibility_entry = staticmethod(ArchiveCatalogueService.compatibility_entry)


class _Harness(ResearchArchiveCatalogueMixin, QObject):
    status_message_requested = Signal(str, bool)

    def __init__(self, service: _CatalogueService) -> None:
        super().__init__()
        self.refresh_button = _Value()
        self.refresh_progress = _Value()
        self.refresh_status_label = _Value()
        self.ui_constraint_refresh_button = _Value()
        self.ui_constraint_status_label = _Value()
        self.reference_resolve_button = _Value()
        self.reference_status_label = _Value()
        self.archive_picker_status_label = _Value()
        self.archive_picker_preview_request_id = 0
        self.unknown_preview_request_id = 0
        self.dirty_count = 0
        self.refresh_count = 0
        self.preview_starts: list[tuple[int, object]] = []
        self._initialize_research_archive_catalogue(
            service,  # type: ignore[arg-type]
            get_archive_entries=lambda: (_ for _ in ()).throw(AssertionError("legacy archive entries were read")),
            get_filtered_archive_entries=lambda: (_ for _ in ()).throw(AssertionError("legacy filtered entries were read")),
        )

    def mark_archive_picker_dirty(self) -> None:
        self.dirty_count += 1

    def refresh_research(self) -> None:
        self.refresh_count += 1

    def refresh_ui_constraints(self) -> None:
        return

    def resolve_references(self) -> None:
        return

    def refresh_archive_picker(self) -> None:
        return

    def _start_archive_picker_preview_worker(self, request_id: int, entry: object) -> None:
        self.preview_starts.append((request_id, entry))

    def _start_unknown_preview_worker(self, _request_id: int, _entry: object) -> None:
        return

    def _handle_archive_picker_preview_error(self, request_id: int, message: str) -> None:
        raise AssertionError(f"unexpected preview error {request_id}: {message}")

    def _handle_unknown_preview_error(self, request_id: int, message: str) -> None:
        raise AssertionError(f"unexpected preview error {request_id}: {message}")


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _session(tmp_path: Path) -> ArchiveSessionHandle:
    return ArchiveSessionHandle("session-research", str(tmp_path), "fingerprint", 1_674_732, 3, True)


def _query() -> ArchiveQueryHandle:
    return ArchiveQueryHandle("session-research", "query-current", 9, 3)


def _replacement_query() -> ArchiveQueryHandle:
    return ArchiveQueryHandle("session-research", "query-current", 10, 45)


def _dto(entry_id: int, path: str, extension: str, *, size: int = 1024) -> ArchiveEntryDto:
    return ArchiveEntryDto(
        session_id="session-research",
        entry_id=entry_id,
        identity=ArchiveDurableIdentity(path.casefold(), "0009/0.pamt", 0, entry_id * 100),
        path=path,
        source_pamt="C:/Game/0009/0.pamt",
        paz_file="C:/Game/0009/0.paz",
        paz_index=0,
        offset=entry_id * 100,
        stored_size=size,
        original_size=size,
        flags=0,
        extension=extension,
        package="0009",
        role=ArchiveEntryRole.IMAGE if extension == ".dds" else ArchiveEntryRole.METADATA,
        category="Textures",
        is_previewable=True,
    )


def _prepared(dto: ArchiveEntryDto, path: Path) -> PrepareEntryResult:
    return PrepareEntryResult(
        ArchiveEntryRef(dto.session_id, dto.entry_id, dto.identity, dto.path),
        str(path),
        dto.original_size,
        f"sha-{dto.entry_id}",
        "prepared",
    )


def test_research_compatibility_entry_budget_stays_below_process_ceiling() -> None:
    assert REMOTE_RESEARCH_COMPATIBILITY_ENTRY_LIMIT < 10_000


def test_research_uses_bounded_worker_candidates_and_prepares_sidecars(tmp_path: Path) -> None:
    app = _app()
    service = _CatalogueService()
    harness = _Harness(service)
    harness.set_archive_catalogue_context(_session(tmp_path), _query())

    assert harness._prepare_catalogue_research_refresh_if_needed("refresh") is True
    view_request, _generation = service.page_requests[0]
    assert view_request.query_id == "query-current"
    assert view_request.page_start == 0
    assert view_request.page_size == 512

    image = _dto(1, "texture/weapon.dds", ".dds")
    mesh = _dto(4, "model/weapon.pac", ".pac")
    view_sidecar = _dto(2, "model/weapon.pac_xml", ".xml")
    service.result_ready.emit(
        "fetch-1",
        "fetch_page",
        ArchivePage("session-research", "query-current", 9, 3, 0, (image, mesh, view_sidecar)),
    )
    analysis_request, _generation = service.lookup_requests[0]
    assert analysis_request.query_id == "query-current"
    assert analysis_request.limit == 4096
    assert {".dds", ".lua", ".xml"} <= set(analysis_request.values)
    service.batch_ready.emit(
        "lookup-1",
        "resolve_entries",
        ArchiveLookupResult("session-research", (image, view_sidecar), 2, False),
    )
    service.result_ready.emit(
        "lookup-1",
        "resolve_entries",
        ArchiveLookupResult("session-research", (), 2, False),
    )

    sidecar_request, _generation = service.lookup_requests[1]
    assert sidecar_request.query_id is None
    assert sidecar_request.limit == 1024
    assert {".cfg", ".ini", ".lua", ".txt", ".yaml", ".yml"} <= set(sidecar_request.values)

    full_sidecar = _dto(3, "model/shared.pami", ".pami")
    service.batch_ready.emit(
        "lookup-2",
        "resolve_entries",
        ArchiveLookupResult("session-research", (view_sidecar, full_sidecar), 2, False),
    )
    service.result_ready.emit(
        "lookup-2",
        "resolve_entries",
        ArchiveLookupResult("session-research", (), 2, False),
    )
    prepare_request, _generation = service.prepare_many_requests[0]
    assert prepare_request.entry_ids == (2, 3)

    prepared_view = _prepared(view_sidecar, tmp_path / "weapon.pac_xml")
    prepared_full = _prepared(full_sidecar, tmp_path / "shared.pami")
    service.batch_ready.emit(
        "prepare-many-1",
        "prepare_entry",
        PrepareEntriesResult("session-research", (prepared_view, prepared_full), 2, 2, 2048),
    )
    service.result_ready.emit(
        "prepare-many-1",
        "prepare_entry",
        PrepareEntriesResult("session-research", (), 2, 2, 2048),
    )
    app.processEvents()

    assert harness.refresh_count == 1
    assert [entry.path for entry in harness.get_filtered_archive_entries()] == [image.path, view_sidecar.path]
    assert [entry.path for entry in harness.get_archive_entries()] == [image.path, view_sidecar.path, full_sidecar.path]
    picker_entries, _fallback_entries = harness._research_archive_picker_entry_sources()
    assert [entry.path for entry in picker_entries] == [image.path, mesh.path, view_sidecar.path]
    assert harness.get_filtered_archive_entries()[0].prepared_path is None
    assert harness.get_filtered_archive_entries()[1].prepared_path == tmp_path / "weapon.pac_xml"


def test_research_preview_materializes_one_bounded_entry_before_existing_worker(tmp_path: Path) -> None:
    _app()
    service = _CatalogueService()
    harness = _Harness(service)
    harness.set_archive_catalogue_context(_session(tmp_path), _query())
    image = _dto(7, "texture/preview.dds", ".dds")
    archive_entry = service.compatibility_entry(image)
    harness._remote_research_entry_ids[archive_entry.identity] = image.entry_id
    harness.archive_picker_preview_request_id = 11

    assert harness._start_catalogue_research_preview("archive_picker", 11, archive_entry) is True
    request, _generation = service.prepare_requests[0]
    assert request.entry_id == image.entry_id

    prepared = _prepared(image, tmp_path / "preview.dds")
    service.result_ready.emit("prepare-1", "prepare_entry", prepared)

    assert archive_entry.prepared_path == tmp_path / "preview.dds"
    assert harness.preview_starts == [(11, archive_entry)]


def test_research_picker_keeps_unprepared_current_row_out_of_analysis_workers(tmp_path: Path) -> None:
    _app()
    service = _CatalogueService()
    harness = _Harness(service)
    harness.set_archive_catalogue_context(_session(tmp_path), _query())
    text_source = _dto(9, "scripts/reference.lua", ".lua")
    harness._remote_research_view_dtos[text_source.entry_id] = text_source

    harness._publish_research_catalogue_candidates()

    picker_entries, _fallback_entries = harness._research_archive_picker_entry_sources()
    assert [entry.path for entry in picker_entries] == [text_source.path]
    assert harness.get_filtered_archive_entries() == ()
    assert harness.get_archive_entries() == ()


def test_research_candidate_view_pages_without_reconstructing_the_full_catalogue(tmp_path: Path) -> None:
    _app()
    service = _CatalogueService()
    harness = _Harness(service)
    query = ArchiveQueryHandle("session-research", "query-paged", 4, 513)
    harness.set_archive_catalogue_context(_session(tmp_path), query)
    assert harness._prepare_catalogue_research_refresh_if_needed("archive_picker") is True

    first_rows = tuple(_dto(1_000 + index, f"model/{index}.pac", ".pac") for index in range(512))
    service.result_ready.emit(
        "fetch-1",
        "fetch_page",
        ArchivePage("session-research", "query-paged", 4, 513, 0, first_rows),
    )
    second_request, _generation = service.page_requests[1]
    assert second_request.page_start == 512
    assert second_request.page_size == 512

    final_row = _dto(1_512, "model/final.pac", ".pac")
    service.result_ready.emit(
        "fetch-2",
        "fetch_page",
        ArchivePage("session-research", "query-paged", 4, 513, 512, (final_row,)),
    )
    assert len(harness._remote_research_view_dtos) == 513
    assert len(service.lookup_requests) == 1


def test_research_query_change_cancels_and_ignores_stale_candidate_lookup(tmp_path: Path) -> None:
    _app()
    service = _CatalogueService()
    harness = _Harness(service)
    harness.set_archive_catalogue_context(_session(tmp_path), _query())
    assert harness._prepare_catalogue_research_refresh_if_needed("refresh") is True
    assert harness.refresh_button.enabled is False

    harness.set_archive_catalogue_context(_session(tmp_path), _replacement_query())

    assert service.cancelled == ["fetch-1"]
    assert harness.refresh_button.enabled is True
    stale = _dto(8, "texture/stale.dds", ".dds")
    service.result_ready.emit(
        "fetch-1",
        "fetch_page",
        ArchivePage("session-research", "query-current", 9, 1, 0, (stale,)),
    )
    assert harness.refresh_count == 0
    assert harness.get_archive_entries() == ()
    assert len(service.page_requests) == 1
    assert service.lookup_requests == []


def test_research_candidate_failure_restores_the_requesting_action(tmp_path: Path) -> None:
    _app()
    service = _CatalogueService()
    harness = _Harness(service)
    harness.set_archive_catalogue_context(_session(tmp_path), _query())

    def fail_page(_request: object, *, ui_generation: int) -> str:
        raise RuntimeError(f"candidate lookup failed at generation {ui_generation}")

    service.fetch_page = fail_page  # type: ignore[method-assign]
    assert harness._prepare_catalogue_research_refresh_if_needed("references") is True
    assert harness.reference_resolve_button.enabled is True
    assert harness.reference_status_label.text == "candidate lookup failed at generation 1"
