"""Typed business boundary over the resident full archive process client."""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, field, replace
import time
import traceback
from pathlib import Path
from typing import Callable
from uuid import uuid4

from PySide6.QtCore import QObject, QTimer, Signal

from cdmw.domain.archives.catalogue import (
    ArchiveAssociationRequest,
    ArchiveAssociationResult,
    ArchiveChildrenRequest,
    ArchiveChildrenResult,
    ArchiveFacetsResult,
    ArchiveLookupRequest,
    ArchiveLookupKind,
    ArchiveLookupResult,
    ArchivePage,
    ArchiveQuery,
    ArchiveQueryHandle,
    ArchiveSessionHandle,
)
from cdmw.domain.archives.catalogue_operations import (
    ArchiveBackendError,
    ArchiveBackendOperation,
    ArchiveExportRequest,
    ArchiveExportResult,
    ArchiveTextSearchBatch,
    ArchiveTextSearchRequest,
    CacheHealthRequest,
    CacheHealthResult,
    CloseArchiveRequest,
    CloseArchiveResult,
    CreateQueryRequest,
    FetchPageRequest,
    OpenArchiveRequest,
    PrepareEntryRequest,
    PrepareEntryResult,
    PrepareEntriesRequest,
    PrepareEntriesResult,
    ProgressUpdate,
)
from cdmw.domain.archives.item_catalogue import (
    BuildNameIndexRequest,
    BuildNameIndexResult,
    ItemCatalogScopeRequest,
    ItemCatalogScopeResult,
    ItemCatalogSearchRequest,
    ItemCatalogSearchResult,
    ItemIconBatchRequest,
    ItemIconBatchResult,
)
from cdmw.domain.archives.catalogue_wire import ArchiveContractError
from cdmw.domain.archives.character_catalogue import (
    BuildCharacterCatalogRequest, BuildCharacterCatalogResult,
    CharacterCatalogSearchRequest, CharacterCatalogSearchResult,
    CharacterCatalogDetailRequest, CharacterCatalogDetailResult,
    CharacterCatalogScopeRequest, CharacterCatalogScopeResult,
)
from cdmw.models import ArchiveEntry
from cdmw.services.archive_failure_report import ArchiveOperationFailure, archive_failure_report


_ResultParser = Callable[[object], object]


@dataclass(slots=True)
class _RetryBudget:
    retries: int = 0


@dataclass(slots=True)
class _CatalogueRequest:
    operation: ArchiveBackendOperation
    payload: object
    ui_generation: int
    result_parser: _ResultParser
    batch_parser: _ResultParser | None = None
    query: ArchiveQuery | None = None
    session_id: str | None = None
    fingerprint: str | None = None
    package_root: str = ""
    budget: _RetryBudget = field(default_factory=_RetryBudget)
    created_at: float = 0.0
    started_at: float | None = None
    start_acknowledged: bool = False
    last_progress_at: float = 0.0
    last_progress: ProgressUpdate | None = None
    last_batch: object = None
    progress_tail: deque[str] = field(default_factory=lambda: deque(maxlen=12))
    delay_notice_shown: bool = False
    retry_at: float | None = None
    stall_deadline: float | None = None
    timeout_error: ArchiveBackendError | None = None
    wire_id: str = ""
    dispatches: int = 0
    internal_kind: str = ""
    recovery_target_id: str | None = None
    recovery_old_session_id: str | None = None


class ArchiveCatalogueService(QObject):
    """Expose worker requests/results without leaking process details to widgets."""

    progress = Signal(str, object)
    batch_ready = Signal(str, str, object)
    result_ready = Signal(str, str, object)
    request_failed = Signal(str, object)
    request_cancelled = Signal(str)
    session_published = Signal(object)
    worker_state_changed = Signal(str)
    worker_crashed = Signal(str)
    operation_delayed = Signal(str, str, float)

    def __init__(self, client: object, parent: QObject | None = None, *, clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__(parent)
        self._client = client
        self._requests: dict[str, _CatalogueRequest] = {}
        self._sessions: dict[str, ArchiveSessionHandle] = {}
        self._queries: dict[str, tuple[ArchiveQuery, ArchiveQueryHandle, str]] = {}
        self._current_session_id: str | None = None
        self._minimum_ui_generation = 0
        self._recovering_requests: set[str] = set()
        self._recovery_sessions: set[str] = set()
        self._recovery_open_requests: dict[str, str] = {}
        self._clock = clock
        self._closing = False
        self._wire_requests: dict[str, str] = {}
        self._failed_requests: OrderedDict[str, _CatalogueRequest] = OrderedDict()
        self._invalid_sessions: set[str] = set()
        self._session_aliases: dict[str, str] = {}
        self._invalid_queries: set[str] = set()
        self._publication_budgets: dict[int, _RetryBudget] = {}
        for signal, handler in (
            (client.request_progress, self._handle_progress),
            (client.request_batch, self._handle_batch),
            (client.request_succeeded, self._handle_result),
            (client.request_failed, self._handle_failure),
            (client.request_cancelled, self._handle_cancelled),
        ):
            signal.connect(lambda wire_id, *args, handler=handler: self._deliver(handler, wire_id, *args))
        if hasattr(client, "request_started"):
            client.request_started.connect(lambda wire_id: self._deliver(self._handle_started, wire_id))
        client.state_changed.connect(self.worker_state_changed.emit)
        client.worker_crashed.connect(self._handle_worker_crash)
        client.worker_ready.connect(self._handle_worker_ready)
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(200)
        self._watchdog.timeout.connect(self._check_operations)
        self._watchdog.start()

    def begin_publication(self, generation: int) -> None:
        self._publication_budgets[int(generation)] = _RetryBudget()

    def end_publication(self, generation: int) -> None:
        self._publication_budgets.pop(int(generation), None)

    def _deliver(self, handler: Callable, wire_id: str, *args: object) -> None:
        request_id = self._wire_requests.get(wire_id)
        if request_id is not None and not self._closing:
            handler(request_id, *args)

    def _forget_wire(self, request: _CatalogueRequest) -> None:
        self._wire_requests.pop(request.wire_id, None)

    def _handle_started(self, request_id: str) -> None:
        request = self._requests.get(request_id)
        if request is not None and request.stall_deadline is None and not request.start_acknowledged:
            request.start_acknowledged = True
            request.last_progress_at = self._clock()
            request.delay_notice_shown = False

    def _check_operations(self) -> None:
        if self._closing:
            return
        now = self._clock()
        for request_id, request in tuple(self._requests.items()):
            if request_id not in self._requests:
                continue
            if request.ui_generation < self._minimum_ui_generation:
                self.cancel(request_id)
            elif request.retry_at is not None:
                if now >= request.retry_at:
                    request.retry_at = None
                    self._begin_retry(request_id)
            elif request.stall_deadline is not None:
                if now >= request.stall_deadline:
                    # Detach the timed-out attempt before terminating its process.
                    self._forget_wire(request)
                    request.stall_deadline = None
                    self._client.abort_unresponsive()
                    self._invalid_sessions.update(self._sessions)
                    self._handle_failure(request_id, request.timeout_error)
            elif request.started_at is not None:
                idle = now - request.last_progress_at
                if idle >= 300:
                    request.timeout_error = ArchiveBackendError(
                        "request_stalled", "Archive operation stopped making progress for five minutes.",
                        "Cancellation was requested. Retry the operation; inspect the last stage and diagnostic tail if it stalls again.",
                    )
                    request.stall_deadline = now + 2
                    self._client.cancel(request.wire_id)
                elif idle >= 30 and not request.delay_notice_shown:
                    request.delay_notice_shown = True
                    stage = request.last_progress.phase if request.last_progress else "waiting for progress"
                    for visible_id in self._progress_targets(request_id, request):
                        self.operation_delayed.emit(visible_id, stage, now - request.created_at)

    def _begin_retry(self, request_id: str) -> None:
        request = self._requests.get(request_id)
        if request is None or self._closing:
            return
        try:
            recovered_session = None
            if request.session_id in self._session_aliases:
                recovered_session = self._require_session(request.session_id, fingerprint=request.fingerprint)
                request.session_id = recovered_session.session_id
            if request.session_id in self._invalid_sessions:
                self._recovering_requests.add(request_id)
                self._recovery_sessions.add(request.session_id)
                # Queue the recovery open before startup so its wire request
                # owns startup failures under the original retry budget.
                self._handle_worker_ready()
            elif recovered_session is not None:
                self._resume_recovery_target(request_id, recovered_session)
            else:
                self._dispatch(request_id)
        except Exception as error:
            self._handle_failure(request_id, ArchiveBackendError("dispatch_failed", str(error), traceback.format_exc()))

    def _progress_targets(self, request_id: str, request: _CatalogueRequest) -> tuple[str, ...]:
        if request.recovery_target_id:
            return (request.recovery_target_id,)
        if request.internal_kind == "recovery_open":
            return tuple(visible for target in self._recovering_requests if target in self._requests
                         and self._requests[target].session_id == request.recovery_old_session_id
                         for visible in self._progress_targets(target, self._requests[target]))
        return (request_id,)

    def retry_failed(self, request_id: str) -> str:
        """Manual retry preserves the exact payload and starts a fresh budget."""
        previous = self._failed_requests.pop(str(request_id))
        if self._closing or previous.ui_generation < self._minimum_ui_generation:
            raise RuntimeError("This archive operation was superseded.")
        new_id = str(uuid4())
        budget = _RetryBudget()
        if previous.ui_generation in self._publication_budgets:
            self._publication_budgets[previous.ui_generation] = budget
        request = replace(previous, budget=budget, created_at=self._clock(),
                          started_at=None, start_acknowledged=False, last_progress=None, last_batch=None, progress_tail=deque(maxlen=12),
                          retry_at=None, stall_deadline=None, timeout_error=None, wire_id="", dispatches=0)
        self._requests[new_id] = request
        self._begin_retry(new_id)
        return new_id


    @property
    def current_session(self) -> ArchiveSessionHandle | None:
        if self._current_session_id is None:
            return None
        return self._sessions.get(self._current_session_id)

    def session(self, session_id: str) -> ArchiveSessionHandle | None:
        return self._sessions.get(self._session_aliases.get(str(session_id), str(session_id)))

    def cache_health(self, request: CacheHealthRequest, *, ui_generation: int) -> str:
        return self._submit(
            ArchiveBackendOperation.CACHE_HEALTH,
            request,
            CacheHealthResult.from_wire,
            ui_generation=ui_generation,
        )

    def open_archive(self, request: OpenArchiveRequest, *, ui_generation: int) -> str:
        operation = (
            ArchiveBackendOperation.REFRESH_ARCHIVE
            if request.force_refresh
            else ArchiveBackendOperation.OPEN_ARCHIVE
        )
        return self._submit(
            operation,
            request,
            ArchiveSessionHandle.from_wire,
            ui_generation=ui_generation,
        )

    def refresh_archive(self, package_root: Path | str, *, ui_generation: int) -> str:
        current = self.current_session
        return self.open_archive(
            OpenArchiveRequest(
                str(Path(package_root)),
                force_refresh=True,
                supersedes_session_id=current.session_id if current is not None else None,
            ),
            ui_generation=ui_generation,
        )

    def close_archive(self, session_id: str, *, ui_generation: int) -> str:
        return self._submit(
            ArchiveBackendOperation.CLOSE_ARCHIVE,
            CloseArchiveRequest(session_id),
            CloseArchiveResult.from_wire,
            ui_generation=ui_generation,
        )

    def create_query(self, query: ArchiveQuery, *, ui_generation: int) -> str:
        session = self._require_session(query.session_id)
        query = replace(query, session_id=session.session_id)
        return self._submit(
            ArchiveBackendOperation.CREATE_QUERY,
            CreateQueryRequest(query),
            ArchiveQueryHandle.from_wire,
            ui_generation=ui_generation,
            session=session,
            query=query,
        )

    def fetch_page(self, request: FetchPageRequest, *, ui_generation: int) -> str:
        query, _handle, fingerprint = self._require_query(request.query_id)
        session = self._require_session(query.session_id, fingerprint=fingerprint)
        return self._submit(
            ArchiveBackendOperation.FETCH_PAGE,
            request,
            ArchivePage.from_wire,
            ui_generation=ui_generation,
            session=session,
            query=query,
        )

    def fetch_children(self, request: ArchiveChildrenRequest, *, ui_generation: int) -> str:
        query, _handle, fingerprint = self._require_query(request.query_id)
        session = self._require_session(query.session_id, fingerprint=fingerprint)
        return self._submit(
            ArchiveBackendOperation.FETCH_CHILDREN,
            request,
            ArchiveChildrenResult.from_wire,
            ui_generation=ui_generation,
            session=session,
            query=query,
        )

    def fetch_structure_children(
        self,
        session_id: str,
        request: ArchiveChildrenRequest,
        *,
        ui_generation: int,
    ) -> str:
        if request.query_id or not request.include_package_root:
            raise ValueError("Structure children require an empty query token and package-root hierarchy mode.")
        session = self._require_session(session_id)
        return self._submit(
            ArchiveBackendOperation.FETCH_CHILDREN,
            request,
            ArchiveChildrenResult.from_wire,
            ui_generation=ui_generation,
            session=session,
        )

    def facets(self, session_id: str, *, ui_generation: int) -> str:
        session = self._require_session(session_id)
        return self._submit(
            ArchiveBackendOperation.FACETS,
            {},
            ArchiveFacetsResult.from_wire,
            ui_generation=ui_generation,
            session=session,
        )

    def resolve_entries(self, request: ArchiveLookupRequest, *, ui_generation: int) -> str:
        query = None
        if request.query_id:
            query, _handle, fingerprint = self._require_query(request.query_id)
            if query.session_id != self._session_aliases.get(request.session_id, request.session_id):
                raise ValueError("Archive lookup query does not belong to the requested session.")
            session = self._require_session(request.session_id, fingerprint=fingerprint)
        else:
            session = self._require_session(request.session_id)
        return self._submit(
            ArchiveBackendOperation.RESOLVE_ENTRIES,
            request,
            ArchiveLookupResult.from_wire,
            batch_parser=ArchiveLookupResult.from_wire,
            ui_generation=ui_generation,
            session=session,
            query=query,
        )

    def find_association_candidates(
        self,
        request: ArchiveAssociationRequest,
        *,
        ui_generation: int,
    ) -> str:
        session = self._require_session(request.session_id)
        return self._submit(
            ArchiveBackendOperation.FIND_ASSOCIATION_CANDIDATES,
            request,
            ArchiveAssociationResult.from_wire,
            batch_parser=ArchiveAssociationResult.from_wire,
            ui_generation=ui_generation,
            session=session,
        )

    def build_name_index(self, session_id: str, *, ui_generation: int) -> str:
        session = self._require_session(session_id)
        return self._submit(
            ArchiveBackendOperation.BUILD_NAME_INDEX,
            BuildNameIndexRequest(session_id),
            BuildNameIndexResult.from_wire,
            ui_generation=ui_generation,
            session=session,
        )

    def search_item_catalog(
        self,
        request: ItemCatalogSearchRequest,
        *,
        ui_generation: int,
    ) -> str:
        session = self._require_session(request.session_id)
        return self._submit(
            ArchiveBackendOperation.SEARCH_ITEM_CATALOG,
            request,
            ItemCatalogSearchResult.from_wire,
            ui_generation=ui_generation,
            session=session,
        )

    def load_item_icons(
        self,
        request: ItemIconBatchRequest,
        *,
        ui_generation: int,
    ) -> str:
        session = self._require_session(request.session_id)
        return self._submit(
            ArchiveBackendOperation.LOAD_ITEM_ICONS,
            request,
            ItemIconBatchResult.from_wire,
            ui_generation=ui_generation,
            session=session,
        )

    def scope_item_catalog(
        self,
        request: ItemCatalogScopeRequest,
        *,
        ui_generation: int,
    ) -> str:
        session = self._require_session(request.session_id)
        return self._submit(
            ArchiveBackendOperation.SCOPE_ITEM_CATALOG,
            request,
            ItemCatalogScopeResult.from_wire,
            ui_generation=ui_generation,
            session=session,
        )

    def prepare_entry(self, request: PrepareEntryRequest, *, ui_generation: int) -> str:
        session = self._require_session(request.session_id)
        return self._submit(
            ArchiveBackendOperation.PREPARE_ENTRY,
            request,
            PrepareEntryResult.from_wire,
            ui_generation=ui_generation,
            session=session,
        )

    @property
    def character_catalog_available(self) -> bool:
        return "character_catalog_v1" in getattr(self._client, "capabilities", ())

    def _require_character_catalog(self) -> None:
        if not self.character_catalog_available:
            raise ValueError("Body & Face Finder requires an updated archive helper. Rebuild the archive worker or install a current CDMW build, then reopen the archives.")

    def build_character_catalog(self, session_id: str, *, ui_generation: int) -> str:
        self._require_character_catalog()
        session = self._require_session(session_id)
        return self._submit(ArchiveBackendOperation.BUILD_CHARACTER_CATALOG,
                            BuildCharacterCatalogRequest(session_id), BuildCharacterCatalogResult.from_wire,
                            ui_generation=ui_generation, session=session)

    def search_character_catalog(self, request: CharacterCatalogSearchRequest, *, ui_generation: int) -> str:
        self._require_character_catalog()
        session = self._require_session(request.session_id)
        return self._submit(ArchiveBackendOperation.SEARCH_CHARACTER_CATALOG, request,
                            CharacterCatalogSearchResult.from_wire, ui_generation=ui_generation, session=session)

    def get_character_catalog_detail(self, request: CharacterCatalogDetailRequest, *, ui_generation: int) -> str:
        self._require_character_catalog()
        session = self._require_session(request.session_id)
        return self._submit(ArchiveBackendOperation.GET_CHARACTER_CATALOG_DETAIL, request,
                            CharacterCatalogDetailResult.from_wire, ui_generation=ui_generation, session=session)

    def scope_character_catalog(self, request: CharacterCatalogScopeRequest, *, ui_generation: int) -> str:
        self._require_character_catalog()
        session = self._require_session(request.session_id)
        return self._submit(ArchiveBackendOperation.SCOPE_CHARACTER_CATALOG, request,
                            CharacterCatalogScopeResult.from_wire, ui_generation=ui_generation, session=session)

    def prepare_entries(self, request: PrepareEntriesRequest, *, ui_generation: int) -> str:
        session = self._require_session(request.session_id)
        return self._submit(
            ArchiveBackendOperation.PREPARE_ENTRY,
            request,
            PrepareEntriesResult.from_wire,
            batch_parser=PrepareEntriesResult.from_wire,
            ui_generation=ui_generation,
            session=session,
        )

    def text_search(self, request: ArchiveTextSearchRequest, *, ui_generation: int) -> str:
        session = self._require_session(request.session_id)
        return self._submit(
            ArchiveBackendOperation.TEXT_SEARCH,
            request,
            ArchiveTextSearchBatch.from_wire,
            batch_parser=ArchiveTextSearchBatch.from_wire,
            ui_generation=ui_generation,
            session=session,
        )

    def export(self, request: ArchiveExportRequest, *, ui_generation: int) -> str:
        session = self._require_session(request.session_id)
        return self._submit(
            ArchiveBackendOperation.EXPORT,
            request,
            ArchiveExportResult.from_wire,
            batch_parser=ArchiveExportResult.from_wire,
            ui_generation=ui_generation,
            session=session,
        )

    def cancel(self, request_id: str) -> bool:
        request = self._requests.pop(str(request_id), None)
        self._failed_requests.pop(str(request_id), None)
        if request is None:
            return False
        self._forget_wire(request)
        self._recovering_requests.discard(str(request_id))
        for child_id, child in tuple(self._requests.items()):
            if child.recovery_target_id == request_id:
                self.cancel(child_id)
        if request.wire_id:
            self._client.cancel(request.wire_id)
        if request.session_id and not any(
            self._requests[target].session_id == request.session_id
            for target in self._recovering_requests if target in self._requests
        ):
            self._recovery_sessions.discard(request.session_id)
            for child_id, old_session in tuple(self._recovery_open_requests.items()):
                if old_session == request.session_id:
                    self._recovery_open_requests.pop(child_id, None)
                    self.cancel(child_id)
        self.request_cancelled.emit(str(request_id))
        return True

    def invalidate_before(self, ui_generation: int) -> None:
        self._minimum_ui_generation = max(self._minimum_ui_generation, int(ui_generation))
        for request_id, request in tuple(self._requests.items()):
            if request.ui_generation < self._minimum_ui_generation:
                self.cancel(request_id)
        for request_id, request in tuple(self._failed_requests.items()):
            if request.ui_generation < self._minimum_ui_generation:
                self._failed_requests.pop(request_id, None)
        self._client.invalidate_before(self._minimum_ui_generation)

    def request_shutdown(self) -> None:
        self._closing = True
        self._watchdog.stop()
        for request_id in tuple(self._requests):
            self.cancel(request_id)
        self._client.shutdown()

    @staticmethod
    def compatibility_entry(entry: object) -> ArchiveEntry:
        from cdmw.domain.archives.catalogue import ArchiveEntryDto

        if not isinstance(entry, ArchiveEntryDto):
            raise TypeError("compatibility_entry requires one bounded ArchiveEntryDto.")
        return ArchiveEntry(
            path=entry.path,
            pamt_path=Path(entry.source_pamt),
            paz_file=Path(entry.paz_file),
            offset=entry.offset,
            comp_size=entry.stored_size,
            orig_size=entry.original_size,
            flags=entry.flags,
            paz_index=entry.paz_index,
        )

    def _submit(
        self,
        operation: ArchiveBackendOperation,
        payload: object,
        result_parser: _ResultParser,
        *,
        ui_generation: int,
        session: ArchiveSessionHandle | None = None,
        batch_parser: _ResultParser | None = None,
        query: ArchiveQuery | None = None,
    ) -> str:
        if self._closing:
            raise RuntimeError("Archive catalogue is shutting down.")
        request_id = str(uuid4())
        self._requests[request_id] = _CatalogueRequest(
            operation=operation,
            payload=payload,
            created_at=self._clock(),
            budget=self._publication_budgets.get(ui_generation, _RetryBudget()) if operation in {
                ArchiveBackendOperation.OPEN_ARCHIVE, ArchiveBackendOperation.REFRESH_ARCHIVE,
                ArchiveBackendOperation.CREATE_QUERY, ArchiveBackendOperation.FETCH_PAGE,
                ArchiveBackendOperation.FETCH_CHILDREN, ArchiveBackendOperation.FACETS,
            } else _RetryBudget(),
            ui_generation=ui_generation,
            result_parser=result_parser,
            batch_parser=batch_parser,
            query=query,
            session_id=session.session_id if session is not None else None,
            fingerprint=session.fingerprint if session is not None else None,
            package_root=session.package_root if session is not None else str(getattr(payload, "package_root", "")),
        )
        try:
            request = self._requests[request_id]
            if request.session_id in self._invalid_sessions and self._is_recoverable(request):
                self._handle_failure(request_id, ArchiveBackendError("worker_crashed", "The archive worker exited before this operation could start."))
            elif getattr(payload, "query_id", "") in self._invalid_queries and query is not None:
                self._start_recovery_query(request_id, request, session)
            else:
                self._dispatch(request_id)
        except Exception as error:
            self._handle_failure(request_id, ArchiveBackendError("dispatch_failed", str(error), traceback.format_exc()))
        return request_id

    def _dispatch(self, request_id: str) -> None:
        request = self._requests[request_id]
        self._forget_wire(request)
        request.dispatches += 1
        request.wire_id = request_id if request.dispatches == 1 else str(uuid4())
        self._wire_requests[request.wire_id] = request_id
        request.started_at = request.last_progress_at = self._clock()
        request.start_acknowledged = False
        request.last_batch = None
        request.stall_deadline = None
        request.timeout_error = None
        if request.session_id and hasattr(request.payload, "session_id"):
            request.payload = replace(request.payload, session_id=request.session_id)
        query_id = getattr(request.payload, "query_id", "")
        if query_id and query_id not in self._invalid_queries and query_id in self._queries:
            request.payload = replace(request.payload, query_id=self._queries[query_id][1].query_id)
        self._client.submit(
            request.operation,
            request.payload,
            request_id=request.wire_id,
            ui_generation=request.ui_generation,
            session_id=request.session_id,
            expected_fingerprint=request.fingerprint,
        )

    def _handle_progress(self, request_id: str, payload: object) -> None:
        if request_id not in self._requests:
            return
        try:
            update = ProgressUpdate.from_wire(payload)
        except (ArchiveContractError, TypeError, ValueError) as exc:
            self._reject_invalid_payload(request_id, "progress", exc)
            return
        request = self._requests[request_id]
        if request.stall_deadline is not None:
            return
        changed = request.last_progress != update
        if changed:
            request.last_progress_at = self._clock()
            request.delay_notice_shown = False
            request.last_progress = update
            request.progress_tail.append(f"{update.phase}: {update.completed}/{update.total} {update.current_item or ''}")
        if request.internal_kind and changed:
            for target_id in self._progress_targets(request_id, request):
                target = self._requests.get(target_id)
                if target is not None:
                    target.last_progress = update
                    target.progress_tail.append(f"{update.phase}: {update.completed}/{update.total} {update.current_item or ''}")
        self.progress.emit(request_id, update)
        if request.internal_kind:
            for target_id in self._progress_targets(request_id, request):
                self.progress.emit(target_id, update)

    def _handle_batch(self, request_id: str, payload: object) -> None:
        request = self._requests.get(request_id)
        if request is None or request.batch_parser is None:
            return
        try:
            result = request.batch_parser(payload)
        except (ArchiveContractError, TypeError, ValueError) as exc:
            self._reject_invalid_payload(request_id, "batch", exc)
            return
        if request.stall_deadline is not None:
            return
        if request.last_batch != result:
            request.last_batch = result
            request.last_progress_at = self._clock()
            request.delay_notice_shown = False
        self.batch_ready.emit(request_id, request.operation.value, result)

    def _handle_result(self, request_id: str, payload: object) -> None:
        request = self._requests.get(request_id)
        if request is None:
            return
        if request.stall_deadline is not None:
            self._handle_failure(request_id, request.timeout_error)
            return
        self._requests.pop(request_id, None)
        self._forget_wire(request)
        self._recovering_requests.discard(request_id)
        try:
            result = request.result_parser(payload)
            if request.internal_kind == "recovery_open":
                if not isinstance(result, ArchiveSessionHandle):
                    raise TypeError("Recovery open did not return an archive session.")
                self._complete_recovery_open(request_id, request, result)
                return
            if request.internal_kind == "recovery_query":
                if not isinstance(result, ArchiveQueryHandle):
                    raise TypeError("Recovery query did not return a query handle.")
                self._complete_recovery_query(request, result)
                return
            if isinstance(result, ArchiveSessionHandle):
                self._sessions[result.session_id] = result
                self._current_session_id = result.session_id
            elif isinstance(result, ArchiveQueryHandle) and request.query is not None:
                session = self._require_session(result.session_id)
                self._queries[result.query_id] = (request.query, result, session.fingerprint)
            elif isinstance(result, ArchivePage) and isinstance(request.payload, FetchPageRequest):
                handle = self._require_query(request.payload.query_id)[1]
                if (result.session_id != request.session_id or result.query_id != handle.query_id
                    or result.total_matches != handle.total_matches or result.page_start != request.payload.page_start
                    or len(result.rows) > min(request.payload.page_size, max(0, result.total_matches - result.page_start))
                    or any(row.session_id != result.session_id for row in result.rows)):
                    raise ArchiveContractError("Archive page does not match the requested query, range or session.")
                # The compiled query can outlive a cancelled UI publication.
                # Route its page to the current logical request generation.
                result = replace(result, generation=request.ui_generation)
            elif isinstance(result, BuildNameIndexResult) and not result.available:
                self._emit_failure(request_id, request, ArchiveBackendError(
                    "item_names_unavailable", result.warning or "Item-name indexing did not produce an available catalogue."))
                return
            elif isinstance(result, CloseArchiveResult) and result.closed:
                self._sessions.pop(result.session_id, None)
                self._invalid_sessions.discard(result.session_id)
                for alias, destination in tuple(self._session_aliases.items()):
                    if destination == result.session_id:
                        self._session_aliases.pop(alias, None)
                for query_id, (query, _handle, _fingerprint) in tuple(self._queries.items()):
                    if query.session_id == result.session_id:
                        self._queries.pop(query_id, None)
                        self._invalid_queries.discard(query_id)
        except (ArchiveContractError, KeyError, RuntimeError, TypeError, ValueError) as exc:
            error = ArchiveBackendError(
                "invalid_result",
                "Archive backend returned an invalid result.",
                str(exc),
            )
            if request.internal_kind == "recovery_open":
                self._fail_recovery_session(request.recovery_old_session_id, error)
            elif request.internal_kind == "recovery_query":
                self._fail_recovery_target(request.recovery_target_id, error)
            else:
                self._emit_failure(request_id, request, error)
            return
        if isinstance(result, ArchiveSessionHandle):
            self.session_published.emit(result)
        self.result_ready.emit(request_id, request.operation.value, result)

    def _handle_failure(self, request_id: str, error: object) -> None:
        request = self._requests.get(request_id)
        if request is None or self._closing:
            return
        if request.ui_generation < self._minimum_ui_generation or getattr(error, "code", "") in {"stale_generation", "client_shutdown"}:
            self.cancel(request_id)
            return
        if request.timeout_error is not None:
            error = request.timeout_error
        self._forget_wire(request)
        request.started_at = None
        request.stall_deadline = None
        if self._is_recoverable(request) and request.budget.retries < 1 and getattr(error, "code", "") in {
            "file_sharing", "worker_crashed", "startup_timeout", "operation_timeout", "indexer_timeout", "request_stalled",
        }:
            request.budget.retries += 1
            request.retry_at = self._clock() + 1
            self.progress.emit(request_id, ProgressUpdate(0, 0, "Retrying in one second"))
            return
        self._requests.pop(request_id, None)
        if request.internal_kind == "recovery_open":
            self._fail_recovery_session(request.recovery_old_session_id, error)
        elif request.internal_kind == "recovery_query":
            self._fail_recovery_target(request.recovery_target_id, error)
        else:
            self._recovering_requests.discard(request_id)
            self._emit_failure(request_id, request, error)

    def _emit_failure(self, request_id: str, request: _CatalogueRequest, error: object) -> None:
        if self._closing or request.ui_generation < self._minimum_ui_generation:
            return
        if not isinstance(error, ArchiveBackendError):
            error = ArchiveBackendError(getattr(error, "code", "unknown_error"), getattr(error, "message", str(error)), getattr(error, "detail", None))
        session = self._sessions.get(request.session_id or "")
        root = request.package_root or (session.package_root if session else "")
        update = request.last_progress or ProgressUpdate(0, 0, "waiting for worker")
        report = archive_failure_report(
            error, operation=request.operation.value, backend=getattr(self._client, "backend_identity", "standalone archive worker"),
            attempts=1 + request.budget.retries, phase=update.phase, completed=update.completed, total=update.total,
            elapsed=self._clock() - request.created_at, current_item=update.current_item or "",
            progress=tuple(request.progress_tail), diagnostic_tail=getattr(self._client, "diagnostics_tail", ""), package_root=root,
        )
        self._failed_requests[request_id] = request
        while len(self._failed_requests) > 32:
            self._failed_requests.popitem(last=False)
        failure = ArchiveOperationFailure(error.code, error.message, error.detail, report, request_id)
        # Missing helpers can fail synchronously during submit. Let callers first
        # register their logical request, and suppress superseded queued errors.
        QTimer.singleShot(0, lambda: self.request_failed.emit(request_id, failure)
            if not self._closing and self._failed_requests.get(request_id) is request
            and request.ui_generation >= self._minimum_ui_generation else None)

    def _handle_cancelled(self, request_id: str) -> None:
        request = self._requests.get(request_id)
        if request is not None and request.stall_deadline is not None:
            self._handle_failure(request_id, request.timeout_error)
        else:
            self.cancel(request_id)

    def _handle_worker_crash(self, detail: str) -> None:
        self._invalid_sessions.update(self._sessions)
        self.worker_crashed.emit(detail)

    def _handle_worker_ready(self) -> None:
        active_old_sessions = set(self._recovery_open_requests.values())
        for old_session_id in tuple(self._recovery_sessions - active_old_sessions):
            targets = [self._requests[target] for target in self._recovering_requests if target in self._requests and self._requests[target].session_id == old_session_id]
            if not targets:
                self._recovery_sessions.discard(old_session_id)
                continue
            old_session = self._sessions.get(old_session_id)
            if old_session is None:
                self._fail_recovery_session(
                    old_session_id,
                    ArchiveBackendError("recovery_session_missing", "Archive session could not be reopened after worker restart."),
                )
                continue
            request_id = str(uuid4())
            request = _CatalogueRequest(
                operation=ArchiveBackendOperation.OPEN_ARCHIVE,
                payload=OpenArchiveRequest(old_session.package_root),
                ui_generation=max(
                    (
                        self._requests[target].ui_generation
                        for target in self._recovering_requests
                        if self._requests.get(target) is not None
                        and self._requests[target].session_id == old_session_id
                    ),
                    default=self._minimum_ui_generation,
                ),
                result_parser=ArchiveSessionHandle.from_wire,
                budget=targets[0].budget,
                created_at=targets[0].created_at,
                internal_kind="recovery_open",
                recovery_old_session_id=old_session_id,
            )
            self._requests[request_id] = request
            self._recovery_open_requests[request_id] = old_session_id
            try:
                self._dispatch(request_id)
            except Exception as exc:
                self._requests.pop(request_id, None)
                self._recovery_open_requests.pop(request_id, None)
                self._fail_recovery_session(
                    old_session_id,
                    ArchiveBackendError("recovery_open_failed", "Archive session reopen could not be dispatched.", str(exc)),
                )

    def _complete_recovery_open(
        self,
        request_id: str,
        request: _CatalogueRequest,
        session: ArchiveSessionHandle,
    ) -> None:
        old_session_id = request.recovery_old_session_id or ""
        old_session = self._sessions.get(old_session_id)
        self._recovery_open_requests.pop(request_id, None)
        self._recovery_sessions.discard(old_session_id)
        if old_session is None or old_session.fingerprint != session.fingerprint:
            self._fail_recovery_session(
                old_session_id,
                ArchiveBackendError(
                    "recovery_fingerprint_changed",
                    "Archive sources changed while the worker was restarting; stale queries were not retried.",
                ),
            )
            return
        self._sessions[session.session_id] = session
        for alias, destination in tuple(self._session_aliases.items()):
            if destination == old_session_id:
                self._session_aliases[alias] = session.session_id
        if old_session_id != session.session_id:
            self._session_aliases[old_session_id] = session.session_id
            self._sessions.pop(old_session_id, None)
        else:
            self._session_aliases.pop(old_session_id, None)
        for query_id, (query, _handle, _fingerprint) in tuple(self._queries.items()):
            if query.session_id == old_session_id:
                self._queries[query_id] = (replace(query, session_id=session.session_id), _handle, _fingerprint)
                self._invalid_queries.add(query_id)
        if self._current_session_id == old_session_id:
            self._current_session_id = session.session_id
            self.session_published.emit(session)
        self._invalid_sessions.discard(old_session_id)
        targets = [
            target
            for target in self._recovering_requests
            if self._requests.get(target) is not None
            and self._requests[target].session_id == old_session_id
        ]
        for target in targets:
            self._resume_recovery_target(target, session)

    def _resume_recovery_target(self, request_id: str, session: ArchiveSessionHandle) -> None:
        request = self._requests.get(request_id)
        if request is None:
            return
        try:
            if request.operation is ArchiveBackendOperation.CREATE_QUERY and request.query is not None:
                request.query = replace(request.query, session_id=session.session_id)
                request.payload = CreateQueryRequest(request.query)
            elif request.operation is ArchiveBackendOperation.FACETS:
                request.payload = {}
            elif request.operation in {
                ArchiveBackendOperation.BUILD_NAME_INDEX,
                ArchiveBackendOperation.SEARCH_ITEM_CATALOG,
                ArchiveBackendOperation.LOAD_ITEM_ICONS,
                ArchiveBackendOperation.SCOPE_ITEM_CATALOG,
            }:
                request.payload = replace(request.payload, session_id=session.session_id)
            elif request.operation is ArchiveBackendOperation.RESOLVE_ENTRIES and isinstance(request.payload, ArchiveLookupRequest):
                if request.payload.query_id and request.query is not None:
                    self._start_recovery_query(request_id, request, session)
                    return
                request.payload = replace(request.payload, session_id=session.session_id)
            elif (
                request.operation is ArchiveBackendOperation.FETCH_CHILDREN
                and request.query is None
                and isinstance(request.payload, ArchiveChildrenRequest)
                and not request.payload.query_id
            ):
                request.session_id = session.session_id
                request.fingerprint = session.fingerprint
                self._dispatch(request_id)
                return
            elif request.operation in {
                ArchiveBackendOperation.FETCH_PAGE,
                ArchiveBackendOperation.FETCH_CHILDREN,
            } and request.query is not None:
                self._start_recovery_query(request_id, request, session)
                return
            else:
                raise RuntimeError("Archive query operation cannot be safely reconstructed.")
            request.session_id = session.session_id
            request.fingerprint = session.fingerprint
            self._dispatch(request_id)
        except Exception as exc:
            self._fail_recovery_target(
                request_id,
                ArchiveBackendError("query_recovery_failed", "Archive query could not be retried after worker restart.", str(exc)),
            )

    def _start_recovery_query(
        self,
        target_request_id: str,
        target: _CatalogueRequest,
        session: ArchiveSessionHandle,
    ) -> None:
        if target.query is None:
            raise RuntimeError("Recovered page request has no query definition.")
        query = replace(target.query, session_id=session.session_id)
        request_id = str(uuid4())
        self._requests[request_id] = _CatalogueRequest(
            operation=ArchiveBackendOperation.CREATE_QUERY,
            payload=CreateQueryRequest(query),
            ui_generation=target.ui_generation,
            result_parser=ArchiveQueryHandle.from_wire,
            query=query,
            session_id=session.session_id,
            fingerprint=session.fingerprint,
            budget=target.budget,
            created_at=target.created_at,
            internal_kind="recovery_query",
            recovery_target_id=target_request_id,
        )
        self._dispatch(request_id)

    def _complete_recovery_query(
        self,
        request: _CatalogueRequest,
        handle: ArchiveQueryHandle,
    ) -> None:
        target_id = request.recovery_target_id or ""
        target = self._requests.get(target_id)
        if target is None or request.query is None:
            return
        session = self._require_session(handle.session_id)
        self._queries[handle.query_id] = (request.query, handle, session.fingerprint)
        old_query_id = getattr(target.payload, "query_id", "")
        if old_query_id:
            self._queries[old_query_id] = (request.query, handle, session.fingerprint)
            self._invalid_queries.discard(old_query_id)
        if isinstance(target.payload, FetchPageRequest):
            target.payload = replace(target.payload, query_id=handle.query_id)
        elif isinstance(target.payload, ArchiveChildrenRequest):
            target.payload = replace(target.payload, query_id=handle.query_id)
        elif isinstance(target.payload, ArchiveLookupRequest):
            target.payload = replace(
                target.payload,
                session_id=session.session_id,
                query_id=handle.query_id,
            )
        else:
            self._fail_recovery_target(
                target_id,
                ArchiveBackendError("query_recovery_failed", "Recovered query target has an unsupported payload."),
            )
            return
        target.query = request.query
        target.session_id = session.session_id
        target.fingerprint = session.fingerprint
        try:
            self._dispatch(target_id)
        except Exception as exc:
            self._fail_recovery_target(
                target_id,
                ArchiveBackendError("query_recovery_failed", "Recovered query could not be dispatched.", str(exc)),
            )

    @staticmethod
    def _is_recoverable(request: _CatalogueRequest) -> bool:
        if request.operation in {ArchiveBackendOperation.OPEN_ARCHIVE, ArchiveBackendOperation.REFRESH_ARCHIVE, ArchiveBackendOperation.CACHE_HEALTH}:
            return True
        if request.operation in {
            ArchiveBackendOperation.CREATE_QUERY,
            ArchiveBackendOperation.FETCH_PAGE,
            ArchiveBackendOperation.FETCH_CHILDREN,
            ArchiveBackendOperation.FACETS,
            ArchiveBackendOperation.BUILD_NAME_INDEX,
            ArchiveBackendOperation.SEARCH_ITEM_CATALOG,
            ArchiveBackendOperation.LOAD_ITEM_ICONS,
            ArchiveBackendOperation.SCOPE_ITEM_CATALOG,
        }:
            return request.session_id is not None
        if request.operation is ArchiveBackendOperation.RESOLVE_ENTRIES:
            return (
                isinstance(request.payload, ArchiveLookupRequest)
                and request.payload.kind is not ArchiveLookupKind.ENTRY_IDS
            )
        return False

    def _fail_recovery_target(self, request_id: str | None, error: object) -> None:
        if not request_id:
            return
        self._recovering_requests.discard(request_id)
        request = self._requests.pop(request_id, None)
        if request is not None:
            self._forget_wire(request)
            self._emit_failure(request_id, request, error)

    def _fail_recovery_session(self, old_session_id: str | None, error: object) -> None:
        if not old_session_id:
            return
        self._recovery_sessions.discard(old_session_id)
        for request_id, mapped_session in tuple(self._recovery_open_requests.items()):
            if mapped_session == old_session_id:
                self._recovery_open_requests.pop(request_id, None)
                request = self._requests.pop(request_id, None)
                if request is not None:
                    self._forget_wire(request)
        targets = [
            target
            for target in self._recovering_requests
            if self._requests.get(target) is not None
            and self._requests[target].session_id == old_session_id
        ]
        for target in targets:
            self._fail_recovery_target(target, error)

    def _reject_invalid_payload(self, request_id: str, kind: str, error: Exception) -> None:
        request = self._requests.get(request_id)
        if request is not None:
            self._client.cancel(request.wire_id)
            self._handle_failure(request_id, ArchiveBackendError("invalid_stream_payload", f"Archive backend returned an invalid {kind} payload.", str(error)))

    def _require_session(
        self,
        session_id: str,
        *,
        fingerprint: str | None = None,
    ) -> ArchiveSessionHandle:
        session = self._sessions.get(self._session_aliases.get(str(session_id), str(session_id)))
        if session is None:
            raise KeyError("Archive session is not available in the catalogue service.")
        if fingerprint is not None and session.fingerprint != fingerprint:
            raise RuntimeError("Archive session fingerprint changed before the request was issued.")
        return session

    def _require_query(self, query_id: str) -> tuple[ArchiveQuery, ArchiveQueryHandle, str]:
        try:
            return self._queries[str(query_id)]
        except KeyError as exc:
            raise KeyError("Archive query token is not available or has expired.") from exc


__all__ = ["ArchiveCatalogueService"]
