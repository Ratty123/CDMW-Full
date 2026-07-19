from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QApplication

from cdmw.core.text_search import TextSearchResult
from cdmw.domain.archives.catalogue import (
    ArchiveDurableIdentity,
    ArchiveEntryRef,
    ArchiveSessionHandle,
)
from cdmw.domain.archives.catalogue_operations import (
    ArchiveExportCollisionPolicy,
    ArchiveExportItem,
    ArchiveExportResult,
    ArchiveTextMatch,
    ArchiveTextSearchBatch,
    PrepareEntryResult,
)
from cdmw.ui.text_search.tab import TextSearchTab


class _CatalogueService(QObject):
    progress = Signal(str, object)
    batch_ready = Signal(str, str, object)
    result_ready = Signal(str, str, object)
    request_failed = Signal(str, object)
    request_cancelled = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.search_requests = []
        self.prepare_requests = []
        self.export_requests = []
        self.cancelled: list[str] = []

    def text_search(self, request, *, ui_generation: int) -> str:
        self.search_requests.append((request, ui_generation))
        return f"search-{len(self.search_requests)}"

    def prepare_entry(self, request, *, ui_generation: int) -> str:
        self.prepare_requests.append((request, ui_generation))
        return f"prepare-{len(self.prepare_requests)}"

    def export(self, request, *, ui_generation: int) -> str:
        self.export_requests.append((request, ui_generation))
        return f"export-{len(self.export_requests)}"

    def cancel(self, request_id: str) -> bool:
        self.cancelled.append(request_id)
        return True


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


def _tab(root: Path, service: _CatalogueService) -> TextSearchTab:
    return TextSearchTab(
        settings=QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat),
        base_dir=root,
        theme_key="graphite",
        archive_catalogue_service=service,  # type: ignore[arg-type]
    )


def _session(root: Path) -> ArchiveSessionHandle:
    return ArchiveSessionHandle("session-v2", str(root), "fingerprint-v2", 1_674_732, 3, True)


def _batch(*, matches: tuple[ArchiveTextMatch, ...], final: bool = False) -> ArchiveTextSearchBatch:
    return ArchiveTextSearchBatch(
        "session-v2",
        files_scanned=12,
        files_matched=1,
        bytes_read=2048,
        matches=matches,
        is_final=final,
        limit_reached=False,
        warnings=(),
    )


def test_worker_catalogue_search_streams_bounded_results_without_global_entries(tmp_path: Path) -> None:
    _app()
    service = _CatalogueService()
    tab = _tab(tmp_path, service)
    tab.set_archive_catalogue_session(_session(tmp_path))
    tab.set_archive_entries([object()])  # type: ignore[list-item]
    tab.query_edit.setText("needle")
    tab.extensions_edit.setText("txt; xml")
    tab.path_filter_edit.setText("ui/")
    try:
        before = time.perf_counter()
        tab.start_search()
        assert time.perf_counter() - before < 0.05
        assert tab.archive_entries == []
        assert tab.remote_search_request_id == "search-1"
        request, generation = service.search_requests[-1]
        assert generation == tab.search_request_id
        assert request.session_id == "session-v2"
        assert request.extensions == (".txt", ".xml")
        assert request.path_filter == "ui/"

        first = ArchiveTextMatch(7, "ui/example10.txt", 2, 4, 6, "first needle", "0009/0.pamt")
        second = ArchiveTextMatch(7, "ui/example10.txt", 8, 1, 6, "second needle", "0009/0.pamt")
        service.batch_ready.emit("search-1", "text_search", _batch(matches=(first,)))
        service.batch_ready.emit("stale-search", "text_search", _batch(matches=(second,)))
        service.batch_ready.emit("search-1", "text_search", _batch(matches=(second,), final=True))
        service.result_ready.emit("search-1", "text_search", _batch(matches=(second,), final=True))

        assert tab.remote_search_request_id is None
        assert len(tab.search_results) == 1
        result = tab.search_results[0]
        assert result.relative_path == "ui/example10.txt"
        assert result.match_count == 2
        assert result.package_label == "0009/0.pamt"
        assert result.archive_session_id == "session-v2"
        assert result.archive_entry_id == 7
        assert result.archive_entry is None
        assert tab.last_search_stats.candidate_count == 12
    finally:
        tab.request_shutdown()


def test_worker_catalogue_prepares_preview_and_exports_entry_ids(tmp_path: Path) -> None:
    _app()
    service = _CatalogueService()
    tab = _tab(tmp_path, service)
    tab.set_archive_catalogue_session(_session(tmp_path))
    result = tab_result = TextSearchResult(
        source_kind="archive",
        relative_path="text/example.txt",
        extension=".txt",
        match_count=1,
        snippet="needle",
        package_label="0009/0.pamt",
        archive_session_id="session-v2",
        archive_entry_id=7,
    )
    tab.search_results = [tab_result]
    tab.current_preview_result = result
    tab.last_search_query = "needle"
    prepared = tmp_path / "prepared.txt"
    prepared.write_text("prefix needle suffix", encoding="utf-8")
    identity = ArchiveDurableIdentity("text/example.txt", "C:/game/0009/0.pamt", 0, 0)
    reference = ArchiveEntryRef("session-v2", 7, identity, "text/example.txt")
    try:
        tab.preview_request_id = 4
        tab._start_preview_worker(4, result)
        assert tab.remote_preview_request_id == "prepare-1"
        service.result_ready.emit(
            "prepare-1",
            "prepare_entry",
            PrepareEntryResult(reference, str(prepared), prepared.stat().st_size, "sha", "Raw"),
        )
        _wait_until(lambda: tab.preview_thread is None and "needle" in tab.preview_text_edit.toPlainText())
        assert service.prepare_requests[-1][0].entry_id == 7

        tab.export_root_edit.setText(str(tmp_path / "export"))
        with patch.object(tab, "_confirm_export", return_value=True):
            tab._export_results([result], label="selected")
        assert tab.remote_export_request_id == "export-1"
        export_request, generation = service.export_requests[-1]
        assert generation == tab.export_request_id
        assert export_request.entry_ids == (7,)
        assert export_request.collision_policy is ArchiveExportCollisionPolicy.OVERWRITE
        assert export_request.write_manifest
        service.result_ready.emit(
            "export-1",
            "export",
            ArchiveExportResult(
                "session-v2",
                requested=1,
                exported=1,
                skipped=0,
                failed=0,
                cancelled=False,
                manifest_path=str(tmp_path / "export" / "cdmw-export-manifest.json"),
                items=(ArchiveExportItem("text/example.txt", str(tmp_path / "export" / "text/example.txt"), "exported"),),
                items_truncated=False,
            ),
        )
        assert tab.remote_export_request_id is None
        assert "Exported 1 file" in tab.search_progress_label.text()
    finally:
        tab.request_shutdown()
        _wait_until(lambda: tab.preview_thread is None)


def test_worker_catalogue_stop_and_shutdown_cancel_owned_requests(tmp_path: Path) -> None:
    _app()
    service = _CatalogueService()
    tab = _tab(tmp_path, service)
    tab.set_archive_catalogue_session(_session(tmp_path))
    tab.query_edit.setText("needle")
    try:
        tab.start_search()
        assert tab.is_busy()
        tab.stop_search()
        assert service.cancelled == ["search-1"]
        service.request_cancelled.emit("search-1")
        assert not tab.is_busy()

        tab.start_search()
        assert tab.remote_search_request_id == "search-2"
        tab.request_shutdown()
        assert "search-2" in service.cancelled
        assert tab.remote_search_request_id is None
    finally:
        tab.request_shutdown()
