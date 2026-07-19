"""Typed business boundary over the resident full archive process client."""

from __future__ import annotations

from dataclasses import dataclass
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
    result_parser: _ResultParser
    batch_parser: _ResultParser | None = None
    query: ArchiveQuery | None = None


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
        client.request_progress.connect(self._handle_progress)
        client.request_batch.connect(self._handle_batch)
        client.request_succeeded.connect(self._handle_result)
        client.request_failed.connect(self._handle_failure)
        client.request_cancelled.connect(self._handle_cancelled)
        client.state_changed.connect(self.worker_state_changed.emit)
        client.worker_crashed.connect(self.worker_crashed.emit)

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
            ui_generation=ui_generation,
            session=session,
        )

    def cancel(self, request_id: str) -> bool:
        return bool(self._client.cancel(str(request_id)))

    def invalidate_before(self, ui_generation: int) -> None:
        self._client.invalidate_before(int(ui_generation))

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
            result_parser=result_parser,
            batch_parser=batch_parser,
            query=query,
        )
        try:
            self._client.submit(
                operation,
                payload,
                request_id=request_id,
                ui_generation=ui_generation,
                session_id=session.session_id if session is not None else None,
                expected_fingerprint=session.fingerprint if session is not None else None,
            )
        except Exception:
            self._requests.pop(request_id, None)
            raise
        return request_id

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
            if isinstance(result, ArchiveSessionHandle):
                self._sessions[result.session_id] = result
                self._current_session_id = result.session_id
            elif isinstance(result, ArchiveQueryHandle) and request.query is not None:
                session = self._require_session(result.session_id)
                self._queries[result.query_id] = (request.query, result, session.fingerprint)
        except (ArchiveContractError, KeyError, RuntimeError, TypeError, ValueError) as exc:
            self.request_failed.emit(
                request_id,
                ArchiveBackendError("invalid_result", "Archive backend returned an invalid result.", str(exc)),
            )
            return
        if isinstance(result, ArchiveSessionHandle):
            self.session_published.emit(result)
        self.result_ready.emit(request_id, request.operation.value, result)

    def _handle_failure(self, request_id: str, error: object) -> None:
        if self._requests.pop(request_id, None) is not None:
            self.request_failed.emit(request_id, error)

    def _handle_cancelled(self, request_id: str) -> None:
        if self._requests.pop(request_id, None) is not None:
            self.request_cancelled.emit(request_id)

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
