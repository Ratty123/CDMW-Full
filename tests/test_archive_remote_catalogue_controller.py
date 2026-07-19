from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from cdmw.domain.archives.catalogue import (
    ArchiveChildNode,
    ArchiveChildrenResult,
    ArchiveDurableIdentity,
    ArchiveEntryDto,
    ArchiveEntryRole,
    ArchiveFacet,
    ArchiveFacetsResult,
    ArchiveLookupResult,
    ArchivePage,
    ArchiveQuery,
    ArchiveQueryHandle,
    ArchiveSessionHandle,
    ArchiveViewMode,
)
from cdmw.ui.archive_browser.remote_controller import ArchiveRemoteCatalogueController
from cdmw.ui.archive_browser.remote_model import RemoteArchiveBrowserModel


_APPLICATION: QApplication | None = None


def _app() -> QApplication:
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    return _APPLICATION


def _drain_events() -> None:
    app = _app()
    for _ in range(5):
        app.processEvents()


def _session(identifier: str = "session-a", fingerprint: str = "fingerprint-a") -> ArchiveSessionHandle:
    return ArchiveSessionHandle(identifier, "C:/game", fingerprint, 2_000, 2, True)


def _entry(entry_id: int, *, session: str = "session-a", path: str | None = None) -> ArchiveEntryDto:
    resolved = path or f"character/model/file_{entry_id}.pac"
    return ArchiveEntryDto(
        session,
        entry_id,
        ArchiveDurableIdentity(resolved.casefold(), "0009/0.pamt", 0, entry_id * 10),
        resolved,
        "C:/game/0009/0.pamt",
        "C:/game/0009/0.paz",
        0,
        entry_id * 10,
        10,
        20,
        1,
        Path(resolved).suffix,
        "0009/0.pamt",
        ArchiveEntryRole.MODEL,
        "model_mesh_physics",
        True,
    )


class _FakeCatalogueService(QObject):
    result_ready = Signal(str, str, object)
    batch_ready = Signal(str, str, object)
    request_failed = Signal(str, object)
    request_cancelled = Signal(str)
    progress = Signal(str, object)

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, str, object, int]] = []
        self.cancelled: list[str] = []
        self._counter = 0
        self._sessions: dict[str, ArchiveSessionHandle] = {}
        self.current_session: ArchiveSessionHandle | None = None

    def _request(self, kind: str, payload: object, generation: int) -> str:
        self._counter += 1
        request_id = f"{kind}-{self._counter}"
        self.calls.append((request_id, kind, payload, generation))
        return request_id

    def open_archive(self, request, *, ui_generation: int) -> str:
        return self._request("open_archive", request, ui_generation)

    def create_query(self, request, *, ui_generation: int) -> str:
        return self._request("create_query", request, ui_generation)

    def fetch_page(self, request, *, ui_generation: int) -> str:
        return self._request("fetch_page", request, ui_generation)

    def fetch_children(self, request, *, ui_generation: int) -> str:
        return self._request("fetch_children", request, ui_generation)

    def facets(self, session_id: str, *, ui_generation: int) -> str:
        return self._request("facets", session_id, ui_generation)

    def resolve_entries(self, request, *, ui_generation: int) -> str:
        return self._request("resolve_entries", request, ui_generation)

    def cancel(self, request_id: str) -> bool:
        self.cancelled.append(request_id)
        self.request_cancelled.emit(request_id)
        return True

    def session(self, session_id: str) -> ArchiveSessionHandle | None:
        return self._sessions.get(session_id)

    @staticmethod
    def compatibility_entry(entry: ArchiveEntryDto) -> tuple[str, int]:
        return entry.path, entry.entry_id

    def complete(self, request_id: str, result: object) -> None:
        if isinstance(result, ArchiveSessionHandle):
            self._sessions[result.session_id] = result
            self.current_session = result
        kind = next(call[1] for call in self.calls if call[0] == request_id)
        self.result_ready.emit(request_id, kind, result)

    def fail(self, request_id: str, error: object) -> None:
        self.request_failed.emit(request_id, error)

    def batch(self, request_id: str, result: object) -> None:
        kind = next(call[1] for call in self.calls if call[0] == request_id)
        self.batch_ready.emit(request_id, kind, result)

    def latest(self, kind: str) -> tuple[str, object, int]:
        request_id, _kind, payload, generation = next(
            call for call in reversed(self.calls) if call[1] == kind
        )
        return request_id, payload, generation


def _open_flat(
    service: _FakeCatalogueService,
    controller: ArchiveRemoteCatalogueController,
    *,
    session: ArchiveSessionHandle | None = None,
    query_id: str = "query-a",
    rows: tuple[ArchiveEntryDto, ...] | None = None,
    total: int | None = None,
) -> tuple[ArchiveSessionHandle, ArchiveQueryHandle]:
    opened = session or _session()
    controller.open_archive("C:/game", query=ArchiveQuery("", view_mode=ArchiveViewMode.FLAT))
    open_id, _payload, generation = service.latest("open_archive")
    service.complete(open_id, opened)
    query_request_id, query, query_generation = service.latest("create_query")
    assert query.session_id == opened.session_id
    assert query_generation == generation
    page_rows = rows or (_entry(0, session=opened.session_id), _entry(1, session=opened.session_id))
    match_count = len(page_rows) if total is None else total
    handle = ArchiveQueryHandle(opened.session_id, query_id, generation, match_count)
    service.complete(query_request_id, handle)
    page_request_id, page_request, _ = service.latest("fetch_page")
    service.complete(
        page_request_id,
        ArchivePage(
            opened.session_id,
            handle.query_id,
            handle.generation,
            handle.total_matches,
            page_request.page_start,
            page_rows,
        ),
    )
    return opened, handle


def test_open_keeps_previous_rows_until_new_first_page_is_ready() -> None:
    _app()
    service = _FakeCatalogueService()
    model = RemoteArchiveBrowserModel(page_size=4)
    old_handle = ArchiveQueryHandle("old-session", "old-query", 1, 1)
    old_entry = _entry(90, session="old-session", path="old/visible.pac")
    model.publish_query(old_handle, view_mode=ArchiveViewMode.FLAT, prime=False)
    assert model.accept_page(ArchivePage("old-session", "old-query", 1, 1, 0, (old_entry,)))
    controller = ArchiveRemoteCatalogueController(service, model)
    published: list[ArchiveQueryHandle] = []
    controller.queryPublished.connect(published.append)

    controller.open_archive("C:/game", query=ArchiveQuery(""))
    open_id, _request, generation = service.latest("open_archive")
    assert model.data(model.index(0, 0)) == "visible.pac"
    service.complete(open_id, _session())
    query_request_id, _query, _ = service.latest("create_query")
    service.complete(query_request_id, ArchiveQueryHandle("session-a", "query-new", generation, 2))
    assert model.data(model.index(0, 0)) == "visible.pac"

    page_request_id, page_request, _ = service.latest("fetch_page")
    rows = (_entry(0), _entry(1))
    service.complete(
        page_request_id,
        ArchivePage("session-a", "query-new", generation, 2, page_request.page_start, rows),
    )

    assert model.data(model.index(0, 0)) == "file_0.pac"
    assert controller.current_session == _session()
    assert published[-1].query_id == "query-new"


def test_filter_generations_cancel_obsolete_query_and_ignore_late_result() -> None:
    _app()
    service = _FakeCatalogueService()
    model = RemoteArchiveBrowserModel(page_size=4)
    controller = ArchiveRemoteCatalogueController(service, model)
    _open_flat(service, controller)

    first_generation = controller.apply_query(ArchiveQuery("", include_text="first"))
    first_id, _first_query, _ = service.latest("create_query")
    second_generation = controller.apply_query(ArchiveQuery("", include_text="second"))
    second_id, second_query, _ = service.latest("create_query")

    assert second_generation == first_generation + 1
    assert first_id in service.cancelled
    service.complete(first_id, ArchiveQueryHandle("session-a", "stale", first_generation, 50))
    assert model.query_handle is not None and model.query_handle.query_id == "query-a"
    assert second_query.include_text == "second"

    service.complete(second_id, ArchiveQueryHandle("session-a", "current", second_generation, 1))
    page_id, page_request, _ = service.latest("fetch_page")
    service.complete(
        page_id,
        ArchivePage("session-a", "current", second_generation, 1, page_request.page_start, (_entry(7),)),
    )
    assert model.query_handle is not None and model.query_handle.query_id == "current"
    assert model.data(model.index(0, 0)) == "file_7.pac"


def test_missing_page_signal_dispatches_bounded_service_fetch_and_accepts_result() -> None:
    _app()
    service = _FakeCatalogueService()
    model = RemoteArchiveBrowserModel(page_size=4)
    controller = ArchiveRemoteCatalogueController(service, model)
    _open_flat(service, controller, rows=tuple(_entry(index) for index in range(4)), total=8)
    handle = model.query_handle
    assert handle is not None

    assert model.data(model.index(6, 0)) == "Loading..."
    _drain_events()
    request_id, request, generation = service.latest("fetch_page")
    assert request.page_start == 4
    assert request.page_size == 4
    service.complete(
        request_id,
        ArchivePage("session-a", handle.query_id, handle.generation, 8, 4, tuple(_entry(index) for index in range(4, 8))),
    )
    assert generation == controller.generation
    assert model.data(model.index(6, 0)) == "file_6.pac"


def test_selection_restore_resolves_query_row_then_waits_for_its_page() -> None:
    _app()
    service = _FakeCatalogueService()
    model = RemoteArchiveBrowserModel(page_size=256)
    controller = ArchiveRemoteCatalogueController(service, model)
    _open_flat(service, controller, rows=tuple(_entry(index) for index in range(2)))
    selected = _entry(700)
    ready_rows: list[int] = []
    controller.selectionIndexReady.connect(lambda index: ready_rows.append(index.row()))

    generation = controller.apply_query(
        ArchiveQuery("", include_text="model"),
        selection_identity=selected.identity,
    )
    query_id, _query, _ = service.latest("create_query")
    service.complete(query_id, ArchiveQueryHandle("session-a", "query-selection", generation, 1_000))
    page_id, page_request, _ = service.latest("fetch_page")
    service.complete(
        page_id,
        ArchivePage(
            "session-a",
            "query-selection",
            generation,
            1_000,
            page_request.page_start,
            tuple(_entry(index) for index in range(256)),
        ),
    )
    lookup_id, lookup, _ = service.latest("resolve_entries")
    assert lookup.query_id == "query-selection"
    service.batch(lookup_id, ArchiveLookupResult("session-a", (selected,), 1, False, (700,)))
    service.complete(lookup_id, ArchiveLookupResult("session-a", (), 1, False, ()))
    assert ready_rows == []
    _drain_events()
    selected_page_id, _kind, selected_page_request, _generation = next(
        call
        for call in reversed(service.calls)
        if call[1] == "fetch_page" and call[2].page_start == 512
    )
    assert selected_page_request.page_start == 512
    rows = tuple(selected if index == 700 else _entry(index) for index in range(512, 768))
    service.complete(
        selected_page_id,
        ArchivePage("session-a", "query-selection", generation, 1_000, 512, rows),
    )
    assert ready_rows == [700]


def test_changed_fingerprint_disables_actions_until_replacement_session_publishes() -> None:
    _app()
    service = _FakeCatalogueService()
    model = RemoteArchiveBrowserModel(page_size=4)
    controller = ArchiveRemoteCatalogueController(service, model)
    _open_flat(service, controller, session=_session(fingerprint="fingerprint-old"))
    safety: list[bool] = []
    controller.actionsSafeChanged.connect(safety.append)

    controller.open_archive("C:/game", force_refresh=True)
    open_id, _request, generation = service.latest("open_archive")
    service.complete(open_id, _session("session-new", "fingerprint-new"))
    assert safety == [False]
    query_id, _query, _ = service.latest("create_query")
    service.complete(query_id, ArchiveQueryHandle("session-new", "query-new", generation, 1))
    page_id, page_request, _ = service.latest("fetch_page")
    service.complete(
        page_id,
        ArchivePage("session-new", "query-new", generation, 1, page_request.page_start, (_entry(1, session="session-new"),)),
    )
    assert safety == [False, True]
    assert controller.actions_safe


def test_folder_and_category_queries_publish_worker_children_and_facets() -> None:
    _app()
    service = _FakeCatalogueService()
    model = RemoteArchiveBrowserModel(child_page_size=32)
    controller = ArchiveRemoteCatalogueController(service, model)

    controller.open_archive("C:/game", query=ArchiveQuery("", view_mode=ArchiveViewMode.FOLDERS))
    open_id, _request, generation = service.latest("open_archive")
    service.complete(open_id, _session())
    query_id, _query, _ = service.latest("create_query")
    service.complete(query_id, ArchiveQueryHandle("session-a", "folders", generation, 10))
    children_id, children_request, _ = service.latest("fetch_children")
    assert children_request.offset == 0
    service.complete(
        children_id,
        ArchiveChildrenResult(
            "session-a",
            "folders",
            (ArchiveChildNode("character", "character", True, 10),),
            False,
            total_children=1,
        ),
    )
    assert model.rowCount() == 1
    assert model.data(model.index(0, 0)) == "character (10)"

    controller.apply_query(ArchiveQuery("", view_mode=ArchiveViewMode.CATEGORIES))
    category_query_id, _query, category_generation = service.latest("create_query")
    service.complete(category_query_id, ArchiveQueryHandle("session-a", "categories", category_generation, 10))
    facets_id, _session_id, _ = service.latest("facets")
    service.complete(
        facets_id,
        ArchiveFacetsResult("session-a", (), (), (), (ArchiveFacet("model", "Models", 10),)),
    )
    assert model.rowCount() == 1
    assert model.data(model.index(0, 0)) == "Models (10)"


def test_invalid_first_page_fails_closed_without_replacing_previous_view() -> None:
    _app()
    service = _FakeCatalogueService()
    model = RemoteArchiveBrowserModel(page_size=4)
    controller = ArchiveRemoteCatalogueController(service, model)
    _open_flat(service, controller, query_id="old-query")
    failures: list[str] = []
    controller.requestFailed.connect(lambda kind, _error: failures.append(kind))

    controller.apply_query(ArchiveQuery("", include_text="new"))
    query_id, _query, generation = service.latest("create_query")
    service.complete(query_id, ArchiveQueryHandle("session-a", "new-query", generation, 5))
    page_id, _page, _ = service.latest("fetch_page")
    service.complete(
        page_id,
        ArchivePage("session-a", "new-query", generation, 5, 4, (_entry(4),)),
    )

    assert failures == ["publish"]
    assert model.query_handle is not None and model.query_handle.query_id == "old-query"
    assert model.data(model.index(0, 0)) == "file_0.pac"


def test_recovered_page_session_recreates_query_before_publishing_more_rows() -> None:
    _app()
    service = _FakeCatalogueService()
    model = RemoteArchiveBrowserModel(page_size=4)
    controller = ArchiveRemoteCatalogueController(service, model)
    _open_flat(
        service,
        controller,
        session=_session("session-old", "same-fingerprint"),
        rows=tuple(_entry(index, session="session-old") for index in range(4)),
        total=8,
    )

    assert model.data(model.index(6, 0)) == "Loading..."
    _drain_events()
    page_id, page_request, _ = service.latest("fetch_page")
    recovered = _session("session-recovered", "same-fingerprint")
    service._sessions[recovered.session_id] = recovered
    service.current_session = recovered
    service.complete(
        page_id,
        ArchivePage(
            recovered.session_id,
            "query-recovered-internally",
            controller.generation,
            8,
            page_request.page_start,
            tuple(_entry(index, session=recovered.session_id) for index in range(4, 8)),
        ),
    )

    restart_query_id, restart_query, restart_generation = service.latest("create_query")
    assert restart_query.session_id == recovered.session_id
    service.complete(
        restart_query_id,
        ArchiveQueryHandle(recovered.session_id, "query-restarted", restart_generation, 8),
    )
    first_page_id, first_page_request, _ = service.latest("fetch_page")
    service.complete(
        first_page_id,
        ArchivePage(
            recovered.session_id,
            "query-restarted",
            restart_generation,
            8,
            first_page_request.page_start,
            tuple(_entry(index, session=recovered.session_id) for index in range(4)),
        ),
    )

    assert controller.current_session == recovered
    assert model.query_handle is not None and model.query_handle.query_id == "query-restarted"
