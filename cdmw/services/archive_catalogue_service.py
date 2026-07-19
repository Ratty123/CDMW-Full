"""Typed business boundary over the resident full archive process client."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable
from uuid import uuid4

from PySide6.QtCore import QObject, Signal

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
    CreateQueryRequest,
    FetchPageRequest,
    OpenArchiveRequest,
    PrepareEntryRequest,
    PrepareEntryResult,
    ProgressUpdate,
)
from cdmw.domain.archives.catalogue_wire import ArchiveContractError
from cdmw.models import ArchiveEntry


_ResultParser = Callable[[object], object]


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
    recovery_attempts: int = 0
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

    def __init__(self, client: object, parent: QObject | None = None) -> None:
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
        client.request_progress.connect(self._handle_progress)
        client.request_batch.connect(self._handle_batch)
        client.request_succeeded.connect(self._handle_result)
        client.request_failed.connect(self._handle_failure)
        client.request_cancelled.connect(self._handle_cancelled)
        client.state_changed.connect(self.worker_state_changed.emit)
        client.worker_crashed.connect(self._handle_worker_crash)
        client.worker_ready.connect(self._handle_worker_ready)

    @property
    def current_session(self) -> ArchiveSessionHandle | None:
        if self._current_session_id is None:
            return None
        return self._sessions.get(self._current_session_id)

    def session(self, session_id: str) -> ArchiveSessionHandle | None:
        return self._sessions.get(str(session_id))

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
        return self.open_archive(
            OpenArchiveRequest(str(Path(package_root)), force_refresh=True),
            ui_generation=ui_generation,
        )

    def create_query(self, query: ArchiveQuery, *, ui_generation: int) -> str:
        session = self._require_session(query.session_id)
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
        session = self._require_session(request.session_id)
        return self._submit(
            ArchiveBackendOperation.RESOLVE_ENTRIES,
            request,
            ArchiveLookupResult.from_wire,
            batch_parser=ArchiveLookupResult.from_wire,
            ui_generation=ui_generation,
            session=session,
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

    def prepare_entry(self, request: PrepareEntryRequest, *, ui_generation: int) -> str:
        session = self._require_session(request.session_id)
        return self._submit(
            ArchiveBackendOperation.PREPARE_ENTRY,
            request,
            PrepareEntryResult.from_wire,
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
        return bool(self._client.cancel(str(request_id)))

    def invalidate_before(self, ui_generation: int) -> None:
        self._minimum_ui_generation = max(self._minimum_ui_generation, int(ui_generation))
        self._client.invalidate_before(self._minimum_ui_generation)

    def request_shutdown(self) -> None:
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
        request_id = str(uuid4())
        self._requests[request_id] = _CatalogueRequest(
            operation=operation,
            payload=payload,
            ui_generation=ui_generation,
            result_parser=result_parser,
            batch_parser=batch_parser,
            query=query,
            session_id=session.session_id if session is not None else None,
            fingerprint=session.fingerprint if session is not None else None,
        )
        try:
            self._dispatch(request_id)
        except Exception:
            self._requests.pop(request_id, None)
            raise
        return request_id

    def _dispatch(self, request_id: str) -> None:
        request = self._requests[request_id]
        self._client.submit(
            request.operation,
            request.payload,
            request_id=request_id,
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
        self.progress.emit(request_id, update)

    def _handle_batch(self, request_id: str, payload: object) -> None:
        request = self._requests.get(request_id)
        if request is None or request.batch_parser is None:
            return
        try:
            result = request.batch_parser(payload)
        except (ArchiveContractError, TypeError, ValueError) as exc:
            self._reject_invalid_payload(request_id, "batch", exc)
            return
        self.batch_ready.emit(request_id, request.operation.value, result)

    def _handle_result(self, request_id: str, payload: object) -> None:
        request = self._requests.pop(request_id, None)
        if request is None:
            return
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
                self.request_failed.emit(request_id, error)
            return
        if isinstance(result, ArchiveSessionHandle):
            self.session_published.emit(result)
        self.result_ready.emit(request_id, request.operation.value, result)

    def _handle_failure(self, request_id: str, error: object) -> None:
        request = self._requests.get(request_id)
        if request is None:
            return
        if request_id in self._recovering_requests and getattr(error, "code", "") == "worker_crashed":
            return
        self._requests.pop(request_id, None)
        if request.internal_kind == "recovery_open":
            self._fail_recovery_session(request.recovery_old_session_id, error)
            return
        if request.internal_kind == "recovery_query":
            self._fail_recovery_target(request.recovery_target_id, error)
            return
        self._recovering_requests.discard(request_id)
        self.request_failed.emit(request_id, error)

    def _handle_cancelled(self, request_id: str) -> None:
        if self._requests.pop(request_id, None) is not None:
            self._recovering_requests.discard(request_id)
            self.request_cancelled.emit(request_id)

    def _handle_worker_crash(self, detail: str) -> None:
        for request_id, request in self._requests.items():
            if request.internal_kind or request.recovery_attempts >= 1 or not self._is_recoverable(request):
                continue
            request.recovery_attempts += 1
            self._recovering_requests.add(request_id)
            if request.session_id:
                self._recovery_sessions.add(request.session_id)
        if self._current_session_id is not None:
            self._recovery_sessions.add(self._current_session_id)
        self.worker_crashed.emit(detail)

    def _handle_worker_ready(self) -> None:
        active_old_sessions = set(self._recovery_open_requests.values())
        for old_session_id in tuple(self._recovery_sessions - active_old_sessions):
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
        self._sessions[session.session_id] = session
        if old_session_id != session.session_id:
            self._sessions.pop(old_session_id, None)
        for query_id, (query, _handle, _fingerprint) in tuple(self._queries.items()):
            if query.session_id == old_session_id:
                self._queries.pop(query_id, None)
        if self._current_session_id == old_session_id:
            self._current_session_id = session.session_id
            self.session_published.emit(session)
        if old_session is None or old_session.fingerprint != session.fingerprint:
            self._fail_recovery_session(
                old_session_id,
                ArchiveBackendError(
                    "recovery_fingerprint_changed",
                    "Archive sources changed while the worker was restarting; stale queries were not retried.",
                ),
            )
            return
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
            elif request.operation is ArchiveBackendOperation.RESOLVE_ENTRIES and isinstance(request.payload, ArchiveLookupRequest):
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
        if isinstance(target.payload, FetchPageRequest):
            target.payload = replace(target.payload, query_id=handle.query_id)
        elif isinstance(target.payload, ArchiveChildrenRequest):
            target.payload = replace(target.payload, query_id=handle.query_id)
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
        if request.operation in {
            ArchiveBackendOperation.CREATE_QUERY,
            ArchiveBackendOperation.FETCH_PAGE,
            ArchiveBackendOperation.FETCH_CHILDREN,
            ArchiveBackendOperation.FACETS,
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
        if self._requests.pop(request_id, None) is not None:
            self.request_failed.emit(request_id, error)

    def _fail_recovery_session(self, old_session_id: str | None, error: object) -> None:
        if not old_session_id:
            return
        self._recovery_sessions.discard(old_session_id)
        for request_id, mapped_session in tuple(self._recovery_open_requests.items()):
            if mapped_session == old_session_id:
                self._recovery_open_requests.pop(request_id, None)
                self._requests.pop(request_id, None)
        targets = [
            target
            for target in self._recovering_requests
            if self._requests.get(target) is not None
            and self._requests[target].session_id == old_session_id
        ]
        for target in targets:
            self._fail_recovery_target(target, error)

    def _reject_invalid_payload(self, request_id: str, kind: str, error: Exception) -> None:
        self._requests.pop(request_id, None)
        self._client.cancel(request_id)
        self.request_failed.emit(
            request_id,
            ArchiveBackendError(
                "invalid_stream_payload",
                f"Archive backend returned an invalid {kind} payload.",
                str(error),
            ),
        )

    def _require_session(
        self,
        session_id: str,
        *,
        fingerprint: str | None = None,
    ) -> ArchiveSessionHandle:
        session = self._sessions.get(str(session_id))
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
