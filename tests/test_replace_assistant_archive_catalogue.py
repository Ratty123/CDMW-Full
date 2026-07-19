from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QApplication

from cdmw.domain.archives.catalogue import (
    ArchiveDurableIdentity,
    ArchiveEntryDto,
    ArchiveEntryRef,
    ArchiveEntryRole,
    ArchiveLookupKind,
    ArchiveLookupResult,
    ArchivePage,
    ArchiveQueryHandle,
    ArchiveSessionHandle,
)
from cdmw.domain.archives.catalogue_operations import PrepareEntryResult
from cdmw.models import ReplaceAssistantItem
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.services.replace_assistant_service import (
    build_replace_assistant_archive_index,
    match_replace_assistant_item_to_archive_entry,
    replace_assistant_archive_lookup_values,
)
from cdmw.ui.replace_assistant.archive_picker import RemoteArchiveOriginalDialog
from cdmw.ui.replace_assistant_tab import ReplaceAssistantTab


class _CatalogueService(QObject):
    progress = Signal(str, object)
    batch_ready = Signal(str, str, object)
    result_ready = Signal(str, str, object)
    request_failed = Signal(str, object)
    request_cancelled = Signal(str)

    def __init__(self, session: ArchiveSessionHandle) -> None:
        super().__init__()
        self.active_session = session
        self.lookup_requests = []
        self.prepare_requests = []
        self.query_requests = []
        self.page_requests = []
        self.cancelled: list[str] = []

    def resolve_entries(self, request, *, ui_generation: int) -> str:
        self.lookup_requests.append((request, ui_generation))
        return f"lookup-{len(self.lookup_requests)}"

    def prepare_entry(self, request, *, ui_generation: int) -> str:
        self.prepare_requests.append((request, ui_generation))
        return f"prepare-{len(self.prepare_requests)}"

    def create_query(self, request, *, ui_generation: int) -> str:
        self.query_requests.append((request, ui_generation))
        return f"query-{len(self.query_requests)}"

    def fetch_page(self, request, *, ui_generation: int) -> str:
        self.page_requests.append((request, ui_generation))
        return f"page-{len(self.page_requests)}"

    def cancel(self, request_id: str) -> bool:
        self.cancelled.append(request_id)
        return True

    def session(self, session_id: str) -> ArchiveSessionHandle | None:
        return self.active_session if session_id == self.active_session.session_id else None


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_until(predicate, *, timeout: float = 4.0) -> None:
    deadline = time.perf_counter() + timeout
    app = _app()
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    app.processEvents()
    assert predicate()


def _session(root: Path) -> ArchiveSessionHandle:
    return ArchiveSessionHandle("replace-v2", str(root), "replace-fingerprint", 1_200_000, 3, True)


def _entry(root: Path, entry_id: int, path: str, *, active: bool = False) -> ArchiveEntryDto:
    source_pamt = str(root / "0009" / "0.pamt")
    return ArchiveEntryDto(
        session_id="replace-v2",
        entry_id=entry_id,
        identity=ArchiveDurableIdentity(path, source_pamt, 0, entry_id * 100),
        path=path,
        source_pamt=source_pamt,
        paz_file=str(root / "0009" / "0.paz"),
        paz_index=0,
        offset=entry_id * 100,
        stored_size=128,
        original_size=256,
        flags=2,
        extension=".dds",
        package="0009/0.pamt",
        role=ArchiveEntryRole.IMAGE,
        category="Textures",
        is_previewable=True,
        is_active_override=active,
    )


def _tab(root: Path, service: _CatalogueService) -> ReplaceAssistantTab:
    return ReplaceAssistantTab(
        settings=QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat),
        base_dir=root,
        get_archive_entries=lambda: (),
        get_original_root=lambda: "",
        get_current_config=lambda: None,
        archive_catalogue_service=service,  # type: ignore[arg-type]
    )


def test_lookup_values_preserve_package_relative_path_and_dds_basename(tmp_path: Path) -> None:
    source = tmp_path / "0009" / "ui" / "icons" / "item10.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"png")
    exact, basenames = replace_assistant_archive_lookup_values(
        source,
        build_replace_assistant_archive_index(()),
    )
    assert "ui/icons/item10.dds" in exact
    assert basenames == ("item10.png", "item10.dds")


def test_catalogue_auto_match_resolves_exact_path_without_global_entries(tmp_path: Path) -> None:
    _app()
    session = _session(tmp_path)
    service = _CatalogueService(session)
    tab = _tab(tmp_path, service)
    source = tmp_path / "0009" / "ui" / "icons" / "item10.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"png")
    tab.items = [ReplaceAssistantItem(source, "png", status="unresolved")]
    tab.set_archive_catalogue_session(session)
    try:
        assert tab._start_catalogue_auto_match(refresh_preview=False)
        request, _generation = service.lookup_requests[-1]
        assert request.kind is ArchiveLookupKind.EXACT_PATHS
        assert "ui/icons/item10.dds" in request.values
        tab.set_archive_entries([ArchiveCatalogueService.compatibility_entry(_entry(tmp_path, 99, "ignored.dds"))])
        assert tab.archive_entries == []

        dto = _entry(tmp_path, 17, "ui/icons/item10.dds", active=True)
        service.batch_ready.emit(
            "lookup-1",
            "resolve_entries",
            ArchiveLookupResult(session.session_id, (dto,), 1, False),
        )
        service.result_ready.emit(
            "lookup-1",
            "resolve_entries",
            ArchiveLookupResult(session.session_id, (), 1, False),
        )
        matched = tab.items[0].matched_original
        assert matched is not None
        assert matched.archive_entry_id == 17
        assert matched.archive_session_id == session.session_id
        assert matched.archive_fingerprint == session.fingerprint
        assert matched.archive_relative_path == "ui/icons/item10.dds"
        assert tab.remote_match_request_id is None
    finally:
        tab.request_shutdown()


def test_legacy_auto_match_keeps_list_backed_compatibility_path(tmp_path: Path) -> None:
    _app()
    dto = _entry(tmp_path, 41, "ui/icons/legacy.dds")
    archive_entry = ArchiveCatalogueService.compatibility_entry(dto)
    tab = ReplaceAssistantTab(
        settings=QSettings(str(tmp_path / "legacy.ini"), QSettings.Format.IniFormat),
        base_dir=tmp_path,
        get_archive_entries=lambda: (archive_entry,),
        get_original_root=lambda: "",
        get_current_config=lambda: None,
    )
    source = tmp_path / "0009" / "ui" / "icons" / "legacy.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"png")
    tab.items = [ReplaceAssistantItem(source, "png")]
    try:
        tab.auto_match_all_items(refresh_preview=False)
        _wait_until(lambda: tab.match_thread is None)
        assert tab.items[0].matched_original is not None
        assert tab.items[0].matched_original.archive_entry is archive_entry
        assert tab.items[0].matched_original.archive_entry_id is None
    finally:
        tab.request_shutdown()


def test_auto_match_worker_hands_unresolved_items_to_catalogue(tmp_path: Path) -> None:
    _app()
    session = _session(tmp_path)
    service = _CatalogueService(session)
    tab = _tab(tmp_path, service)
    source = tmp_path / "0009" / "ui" / "icons" / "worker.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"png")
    tab.items = [ReplaceAssistantItem(source, "png")]
    tab.set_archive_catalogue_session(session)
    try:
        _wait_until(lambda: not tab.is_busy())
        tab.auto_match_all_items(refresh_preview=False)
        _wait_until(lambda: bool(service.lookup_requests))
        _wait_until(lambda: tab.match_thread is None)
        assert tab.match_thread is None
        assert tab.remote_match_request_id == "lookup-1"
        dto = _entry(tmp_path, 19, "ui/icons/worker.dds", active=True)
        service.batch_ready.emit(
            "lookup-1",
            "resolve_entries",
            ArchiveLookupResult(session.session_id, (dto,), 1, False),
        )
        service.result_ready.emit(
            "lookup-1",
            "resolve_entries",
            ArchiveLookupResult(session.session_id, (), 1, False),
        )
        assert tab.items[0].matched_original is not None
        assert not tab.is_busy()
    finally:
        tab.request_shutdown()


def test_catalogue_auto_match_rejects_ambiguous_basename(tmp_path: Path) -> None:
    _app()
    session = _session(tmp_path)
    service = _CatalogueService(session)
    tab = _tab(tmp_path, service)
    source = tmp_path / "edited" / "shared.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"png")
    tab.items = [ReplaceAssistantItem(source, "png", status="unresolved")]
    tab.set_archive_catalogue_session(session)
    try:
        with patch.object(tab, "_prompt_resolve_ambiguous_items"):
            tab._start_catalogue_auto_match(refresh_preview=False)
            service.result_ready.emit(
                "lookup-1",
                "resolve_entries",
                ArchiveLookupResult(session.session_id, (), 0, False),
            )
            basename_request, _generation = service.lookup_requests[-1]
            assert basename_request.kind is ArchiveLookupKind.BASENAMES
            basename_payload = ArchiveLookupResult(
                session.session_id,
                (
                    _entry(tmp_path, 1, "ui/a/shared.dds"),
                    _entry(tmp_path, 2, "ui/b/shared.dds"),
                ),
                2,
                False,
            )
            service.batch_ready.emit("lookup-2", "resolve_entries", basename_payload)
            service.result_ready.emit(
                "lookup-2",
                "resolve_entries",
                ArchiveLookupResult(session.session_id, (), 2, False),
            )
        assert tab.items[0].matched_original is None
        assert tab.items[0].status == "unresolved"
        assert "ambiguous archive basename" in tab.items[0].warning
    finally:
        tab.request_shutdown()


def test_catalogue_shutdown_cancels_owned_lookup_request(tmp_path: Path) -> None:
    _app()
    session = _session(tmp_path)
    service = _CatalogueService(session)
    tab = _tab(tmp_path, service)
    source = tmp_path / "0009" / "ui" / "cancel.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"png")
    tab.items = [ReplaceAssistantItem(source, "png", status="unresolved")]
    tab.set_archive_catalogue_session(session)
    tab._start_catalogue_auto_match(refresh_preview=False)
    assert tab.remote_match_request_id == "lookup-1"
    tab.request_shutdown()
    assert "lookup-1" in service.cancelled
    assert tab.remote_match_request_id is None


def test_catalogue_build_prepares_only_matched_entry_ids(tmp_path: Path) -> None:
    _app()
    session = _session(tmp_path)
    service = _CatalogueService(session)
    tab = _tab(tmp_path, service)
    source = tmp_path / "edited.png"
    source.write_bytes(b"png")
    item = ReplaceAssistantItem(source, "png")
    dto = _entry(tmp_path, 23, "ui/icons/edited.dds")
    match_replace_assistant_item_to_archive_entry(
        item,
        ArchiveCatalogueService.compatibility_entry(dto),
        archive_session_id=session.session_id,
        archive_entry_id=dto.entry_id,
        archive_fingerprint=session.fingerprint,
    )
    tab.items = [item]
    tab.set_archive_catalogue_session(session)
    prepared = tmp_path / "prepared.dds"
    prepared.write_bytes(b"DDS ")
    try:
        options = tab._current_build_options()
        with patch.object(tab, "_launch_build_worker") as launch:
            assert tab._start_catalogue_build(options)
            request, _generation = service.prepare_requests[-1]
            assert request.entry_id == 23
            service.result_ready.emit(
                "prepare-1",
                "prepare_entry",
                PrepareEntryResult(
                    ArchiveEntryRef(session.session_id, 23, dto.identity, dto.path),
                    str(prepared),
                    prepared.stat().st_size,
                    "sha",
                    "Raw",
                ),
            )
            launch.assert_called_once()
            assert launch.call_args.kwargs["archive_entries"] == ()
        assert item.matched_original is not None
        assert item.matched_original.original_dds_path == prepared
    finally:
        tab.request_shutdown()


def test_remote_picker_fetches_only_one_bounded_dds_page(tmp_path: Path) -> None:
    _app()
    session = _session(tmp_path)
    service = _CatalogueService(session)
    dialog = RemoteArchiveOriginalDialog(
        service,  # type: ignore[arg-type]
        session,
        initial_filter="item10",
    )
    try:
        dialog._query_timer.stop()
        dialog._start_query()
        query, generation = service.query_requests[-1]
        assert query.extensions == (".dds",)
        assert query.include_text == "item10"
        service.result_ready.emit(
            "query-1",
            "create_query",
            ArchiveQueryHandle(session.session_id, "dds-query", generation, 700),
        )
        page_request, _page_generation = service.page_requests[-1]
        assert page_request.page_size == 500
        dto = _entry(tmp_path, 31, "ui/icons/item10.dds")
        service.result_ready.emit(
            "page-1",
            "fetch_page",
            ArchivePage(session.session_id, "dds-query", generation, 700, 0, (dto,)),
        )
        assert dialog.results_list.count() == 1
        assert "Showing 1 of 700" in dialog.status_label.text()
    finally:
        dialog.reject()
