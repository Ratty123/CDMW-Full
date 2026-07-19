"""Latest-wins bridge between the archive catalogue service and remote model."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from PySide6.QtCore import QModelIndex, QObject, QTimer, Signal

from cdmw.domain.archives.catalogue import (
    ArchiveChildrenRequest,
    ArchiveChildrenResult,
    ArchiveDurableIdentity,
    ArchiveEntryDto,
    ArchiveFacetsResult,
    ArchiveLookupKind,
    ArchiveLookupRequest,
    ArchiveLookupResult,
    ArchivePage,
    ArchiveQuery,
    ArchiveQueryHandle,
    ArchiveSessionHandle,
    ArchiveViewMode,
    archive_durable_identity_key,
)
from cdmw.domain.archives.catalogue_operations import FetchPageRequest, OpenArchiveRequest
from cdmw.ui.archive_browser.remote_model import (
    RemoteArchiveBrowserModel,
    RemoteChildrenFetch,
    RemotePageFetch,
)


@dataclass(slots=True)
class _TrackedRequest:
    kind: str
    generation: int
    payload: object | None = None


@dataclass(slots=True)
class _StagedQuery:
    generation: int
    session: ArchiveSessionHandle
    query: ArchiveQuery
    handle: ArchiveQueryHandle | None = None
    first_page: ArchivePage | None = None
    first_children_fetch: RemoteChildrenFetch | None = None
    first_children: ArchiveChildrenResult | None = None
    facets: ArchiveFacetsResult | None = None


@dataclass(slots=True)
class _SelectionRequest:
    identity: ArchiveDurableIdentity
    entries: list[ArchiveEntryDto] = field(default_factory=list)
    query_rows: list[int] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _StructureChildrenFetch:
    parent_path: str
    offset: int


class ArchiveRemoteCatalogueController(QObject):
    """Keep old rows visible while a bounded replacement query is prepared."""

    statusChanged = Signal(str)
    progressChanged = Signal(str, object)
    queryPublished = Signal(object)
    facetsReady = Signal(object)
    structureChildrenReady = Signal(str, object)
    selectionIndexReady = Signal(object)
    selectionUnavailable = Signal(object)
    requestFailed = Signal(str, object)
    actionsSafeChanged = Signal(bool)

    def __init__(
        self,
        service: object,
        model: RemoteArchiveBrowserModel,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._model = model
        self._generation = 0
        self._requests: dict[str, _TrackedRequest] = {}
        self._staged: _StagedQuery | None = None
        self._current_session: ArchiveSessionHandle | None = None
        self._current_query: ArchiveQuery | None = None
        self._structure_pending: set[_StructureChildrenFetch] = set()
        self._structure_inflight: set[_StructureChildrenFetch] = set()
        self._selection_identity: ArchiveDurableIdentity | None = None
        self._pending_selection_row: int | None = None
        self._actions_safe = True
        service.result_ready.connect(self._handle_result)
        service.batch_ready.connect(self._handle_batch)
        service.request_failed.connect(self._handle_failure)
        service.request_cancelled.connect(self._handle_cancelled)
        service.progress.connect(self._handle_progress)
        model.pageRequested.connect(self._fetch_page)
        model.childrenRequested.connect(self._fetch_children)

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def current_session(self) -> ArchiveSessionHandle | None:
        return self._current_session

    @property
    def current_query(self) -> ArchiveQuery | None:
        return self._current_query

    @property
    def actions_safe(self) -> bool:
        return self._actions_safe

    def open_archive(
        self,
        package_root: Path | str,
        *,
        query: ArchiveQuery | None = None,
        force_refresh: bool = False,
        selection_identity: ArchiveDurableIdentity | None = None,
    ) -> int:
        generation = self._begin_generation(selection_identity)
        template = query or ArchiveQuery(session_id="")
        request = OpenArchiveRequest(str(Path(package_root)), force_refresh=force_refresh)
        try:
            request_id = self._service.open_archive(request, ui_generation=generation)
        except Exception as exc:
            self._fail_publication("open_archive", exc)
            return generation
        self._requests[request_id] = _TrackedRequest("open", generation, template)
        self.statusChanged.emit("Refreshing archive catalogue..." if force_refresh else "Opening archive catalogue...")
        return generation

    def apply_query(
        self,
        query: ArchiveQuery,
        *,
        selection_identity: ArchiveDurableIdentity | None = None,
    ) -> int:
        session = self._current_session
        if session is None:
            raise RuntimeError("An archive session must be published before applying a query.")
        generation = self._begin_generation(selection_identity)
        current = replace(query, session_id=session.session_id)
        self._staged = _StagedQuery(generation, session, current)
        self._submit_query(self._staged)
        return generation

    def set_selection_identity(self, identity: ArchiveDurableIdentity | None) -> None:
        self._selection_identity = identity

    def request_structure_children(self, parent_path: str = "", *, offset: int = 0) -> None:
        normalized_parent = str(parent_path or "").replace("\\", "/").strip("/").casefold()
        fetch = _StructureChildrenFetch(normalized_parent, max(0, int(offset)))
        if fetch in self._structure_pending or fetch in self._structure_inflight:
            return
        self._structure_pending.add(fetch)
        self._dispatch_structure_requests()

    def entry_for_index(self, index: QModelIndex):
        return self._model.entry_for_index(index)

    def compatibility_entry_for_index(self, index: QModelIndex):
        entry = self.entry_for_index(index)
        return None if entry is None else self._service.compatibility_entry(entry)

    def cancel_pending(self) -> None:
        self._generation += 1
        self._cancel_tracked_requests()
        self._staged = None
        self._model.suspend_requests(False)

    def _begin_generation(self, selection_identity: ArchiveDurableIdentity | None) -> int:
        self._generation += 1
        self._cancel_tracked_requests()
        self._staged = None
        self._pending_selection_row = None
        if selection_identity is not None:
            self._selection_identity = selection_identity
        self._model.suspend_requests(True)
        return self._generation

    def _cancel_tracked_requests(self) -> None:
        for request_id, tracked in tuple(self._requests.items()):
            try:
                self._service.cancel(request_id)
            except Exception:
                pass
            if tracked.kind == "page" and isinstance(tracked.payload, RemotePageFetch):
                self._model.reject_page(tracked.payload.page_start)
            elif tracked.kind == "children" and isinstance(tracked.payload, RemoteChildrenFetch):
                self._model.reject_children(tracked.payload)
        self._requests.clear()
        self._structure_inflight.clear()

    def _submit_query(self, staged: _StagedQuery) -> None:
        try:
            request_id = self._service.create_query(staged.query, ui_generation=staged.generation)
        except Exception as exc:
            self._fail_publication("create_query", exc)
            return
        self._requests[request_id] = _TrackedRequest("query", staged.generation)
        self.statusChanged.emit("Preparing archive query...")

    def _stage_first_result(self, staged: _StagedQuery) -> None:
        handle = staged.handle
        if handle is None:
            self._fail_publication("create_query", TypeError("Archive query handle is missing."))
            return
        if handle.total_matches <= 0:
            self._publish(staged)
            return
        if staged.query.view_mode is ArchiveViewMode.FLAT:
            request = RemotePageFetch(
                handle.session_id,
                handle.query_id,
                handle.generation,
                0,
                self._model.page_size,
            )
            try:
                request_id = self._service.fetch_page(
                    FetchPageRequest(handle.query_id, 0, self._model.page_size),
                    ui_generation=staged.generation,
                )
            except Exception as exc:
                self._fail_publication("fetch_page", exc)
                return
            self._requests[request_id] = _TrackedRequest("stage_page", staged.generation, request)
            return
        if staged.query.view_mode is ArchiveViewMode.FOLDERS:
            fetch = RemoteChildrenFetch(
                handle.session_id,
                handle.query_id,
                handle.generation,
                "root",
                None,
                None,
                0,
                self._model.child_page_size,
            )
            staged.first_children_fetch = fetch
            try:
                request_id = self._service.fetch_children(
                    ArchiveChildrenRequest(handle.query_id, limit=fetch.limit),
                    ui_generation=staged.generation,
                )
            except Exception as exc:
                self._fail_publication("fetch_children", exc)
                return
            self._requests[request_id] = _TrackedRequest("stage_children", staged.generation, fetch)
            return
        self._request_stage_facets(staged)

    def _request_stage_facets(self, staged: _StagedQuery) -> None:
        try:
            request_id = self._service.facets(staged.session.session_id, ui_generation=staged.generation)
        except Exception as exc:
            self._fail_publication("facets", exc)
            return
        self._requests[request_id] = _TrackedRequest("stage_facets", staged.generation)

    def _publish(self, staged: _StagedQuery) -> None:
        handle = staged.handle
        if handle is None or staged.generation != self._generation:
            return
        validation_error = self._staged_payload_error(staged)
        if validation_error:
            self._fail_publication("publish", RuntimeError(validation_error))
            return
        self._model.publish_query(handle, view_mode=staged.query.view_mode, prime=False)
        if staged.first_page is not None and not self._model.accept_page(staged.first_page):
            self._fail_publication("fetch_page", RuntimeError("The first archive page was stale."))
            return
        if staged.first_children is not None and staged.first_children_fetch is not None:
            if not self._model.accept_children(staged.first_children_fetch, staged.first_children):
                self._fail_publication("fetch_children", RuntimeError("The first child page was stale."))
                return
        if staged.facets is not None:
            self._model.publish_categories(staged.facets.categories)
            self.facetsReady.emit(staged.facets)
        self._model.suspend_requests(False)
        self._current_session = staged.session
        self._current_query = staged.query
        self._staged = None
        self._set_actions_safe(True)
        self.queryPublished.emit(handle)
        self._dispatch_structure_requests()
        self.statusChanged.emit(f"Archive catalogue ready. Showing {handle.total_matches:,} entries.")
        if staged.query.view_mode is ArchiveViewMode.FLAT and handle.total_matches > 0:
            self._model.request_visible_rows(0, min(handle.total_matches - 1, self._model.page_size - 1))
        self._restore_selection(handle)
        if staged.facets is None:
            QTimer.singleShot(0, lambda current=handle: self._request_facets_if_current(current))

    def _request_facets_if_current(self, handle: ArchiveQueryHandle) -> None:
        if self._model.query_handle == handle and self._staged is None:
            self._request_facets(handle)

    def _request_facets(self, handle: ArchiveQueryHandle) -> None:
        try:
            request_id = self._service.facets(handle.session_id, ui_generation=self._generation)
        except Exception as exc:
            self.requestFailed.emit("facets", exc)
            return
        self._requests[request_id] = _TrackedRequest("facets", self._generation)

    def _restore_selection(self, handle: ArchiveQueryHandle) -> None:
        identity = self._selection_identity
        if identity is None:
            return
        cached = self._model.find_cached_index_for_identity(identity)
        if cached.isValid():
            self.selectionIndexReady.emit(cached)
            return
        request = ArchiveLookupRequest(
            handle.session_id,
            ArchiveLookupKind.IDENTITIES,
            identities=(identity,),
            limit=1,
            query_id=handle.query_id,
        )
        try:
            request_id = self._service.resolve_entries(request, ui_generation=self._generation)
        except Exception as exc:
            self.requestFailed.emit("selection_lookup", exc)
            return
        self._requests[request_id] = _TrackedRequest(
            "selection",
            self._generation,
            _SelectionRequest(identity),
        )

    def _fetch_page(self, fetch: RemotePageFetch) -> None:
        handle = self._model.query_handle
        if handle is None or not _fetch_matches_handle(fetch, handle) or self._staged is not None:
            self._model.reject_page(fetch.page_start)
            return
        try:
            request_id = self._service.fetch_page(
                FetchPageRequest(fetch.query_id, fetch.page_start, fetch.page_size),
                ui_generation=self._generation,
            )
        except Exception as exc:
            self._model.reject_page(fetch.page_start)
            self.requestFailed.emit("fetch_page", exc)
            return
        self._requests[request_id] = _TrackedRequest("page", self._generation, fetch)

    def _fetch_children(self, fetch: RemoteChildrenFetch) -> None:
        handle = self._model.query_handle
        if handle is None or not _fetch_matches_handle(fetch, handle) or self._staged is not None:
            self._model.reject_children(fetch)
            return
        request = ArchiveChildrenRequest(
            fetch.query_id,
            parent_path=fetch.parent_path,
            category=fetch.category,
            limit=fetch.limit,
            offset=fetch.offset,
        )
        try:
            request_id = self._service.fetch_children(request, ui_generation=self._generation)
        except Exception as exc:
            self._model.reject_children(fetch)
            self.requestFailed.emit("fetch_children", exc)
            return
        self._requests[request_id] = _TrackedRequest("children", self._generation, fetch)

    def _dispatch_structure_requests(self) -> None:
        session = self._current_session
        if session is None or self._staged is not None or not self._structure_pending:
            return
        for fetch in sorted(self._structure_pending, key=lambda item: (item.parent_path, item.offset)):
            request = ArchiveChildrenRequest(
                "",
                parent_path=fetch.parent_path or None,
                limit=512,
                offset=fetch.offset,
                include_package_root=True,
            )
            try:
                request_id = self._service.fetch_structure_children(
                    session.session_id,
                    request,
                    ui_generation=self._generation,
                )
            except Exception as exc:
                self.requestFailed.emit("structure_children", exc)
                continue
            self._structure_pending.discard(fetch)
            self._structure_inflight.add(fetch)
            self._requests[request_id] = _TrackedRequest("structure_children", self._generation, fetch)

    def _handle_result(self, request_id: str, _operation: str, result: object) -> None:
        tracked = self._requests.pop(request_id, None)
        if tracked is None or tracked.generation != self._generation:
            return
        if tracked.kind == "open" and isinstance(result, ArchiveSessionHandle):
            template = tracked.payload if isinstance(tracked.payload, ArchiveQuery) else ArchiveQuery(session_id="")
            query = replace(template, session_id=result.session_id)
            self._staged = _StagedQuery(tracked.generation, result, query)
            if self._current_session is not None and self._current_session.fingerprint != result.fingerprint:
                self._set_actions_safe(False)
            self._submit_query(self._staged)
            return
        staged = self._staged
        if tracked.kind == "query" and isinstance(result, ArchiveQueryHandle) and staged is not None:
            if not self._adopt_staged_session(staged, result.session_id):
                self._fail_publication("create_query", RuntimeError("Recovered archive session is unavailable."))
                return
            staged.handle = result
            self._stage_first_result(staged)
            return
        if tracked.kind == "stage_page" and isinstance(result, ArchivePage) and staged is not None:
            if staged.handle is not None and (
                result.session_id != staged.handle.session_id or result.query_id != staged.handle.query_id
            ):
                if not self._adopt_staged_session(staged, result.session_id):
                    self._fail_publication("fetch_page", RuntimeError("Recovered archive session is unavailable."))
                    return
                staged.handle = ArchiveQueryHandle(
                    result.session_id,
                    result.query_id,
                    result.generation,
                    result.total_matches,
                )
            staged.first_page = result
            self._publish(staged)
            return
        if tracked.kind == "stage_children" and isinstance(result, ArchiveChildrenResult) and staged is not None:
            if staged.handle is not None and (
                result.session_id != staged.handle.session_id or result.query_id != staged.handle.query_id
            ):
                if not self._adopt_staged_session(staged, result.session_id):
                    self._fail_publication("fetch_children", RuntimeError("Recovered archive session is unavailable."))
                    return
                staged.handle = replace(
                    staged.handle,
                    session_id=result.session_id,
                    query_id=result.query_id,
                )
                if staged.first_children_fetch is not None:
                    staged.first_children_fetch = replace(
                        staged.first_children_fetch,
                        session_id=result.session_id,
                        query_id=result.query_id,
                    )
            staged.first_children = result
            self._publish(staged)
            return
        if tracked.kind == "stage_facets" and isinstance(result, ArchiveFacetsResult) and staged is not None:
            staged.facets = result
            self._publish(staged)
            return
        if tracked.kind == "page" and isinstance(result, ArchivePage):
            if not self._model.accept_page(result):
                self._restart_current_query_after_recovery(result.session_id)
                return
            self._finish_pending_selection()
            return
        if tracked.kind == "children" and isinstance(result, ArchiveChildrenResult):
            fetch = tracked.payload
            if isinstance(fetch, RemoteChildrenFetch):
                if not self._model.accept_children(fetch, result):
                    self._restart_current_query_after_recovery(result.session_id)
            return
        if tracked.kind == "structure_children" and isinstance(result, ArchiveChildrenResult):
            fetch = tracked.payload
            if not isinstance(fetch, _StructureChildrenFetch):
                self.requestFailed.emit("structure_children", TypeError("Archive structure request state is invalid."))
                return
            self._structure_inflight.discard(fetch)
            session = self._current_session
            if (
                session is None
                or result.session_id != session.session_id
                or result.query_id
                or result.offset != fetch.offset
            ):
                self._structure_pending.add(fetch)
                self._restart_current_query_after_recovery(result.session_id)
                return
            self.structureChildrenReady.emit(fetch.parent_path, result)
            return
        if tracked.kind == "facets" and isinstance(result, ArchiveFacetsResult):
            self.facetsReady.emit(result)
            return
        if tracked.kind == "selection" and isinstance(result, ArchiveLookupResult):
            selection = tracked.payload
            if isinstance(selection, _SelectionRequest):
                combined = ArchiveLookupResult(
                    result.session_id,
                    tuple(selection.entries) + result.entries,
                    result.total_matches,
                    result.truncated,
                    tuple(selection.query_rows) + result.query_rows,
                )
                self._handle_selection_lookup(combined)
            else:
                self._handle_selection_lookup(result)
            return
        self._handle_failure(request_id, TypeError(f"Unexpected archive result for {tracked.kind}."), tracked=tracked)

    def _handle_selection_lookup(self, result: ArchiveLookupResult) -> None:
        identity = self._selection_identity
        if (
            identity is None
            or len(result.entries) != 1
            or len(result.query_rows) != 1
            or archive_durable_identity_key(result.entries[0].identity) != archive_durable_identity_key(identity)
        ):
            self.selectionUnavailable.emit(identity)
            return
        self._pending_selection_row = result.query_rows[0]
        self._model.index_for_query_row(self._pending_selection_row)
        self._finish_pending_selection()

    def _finish_pending_selection(self) -> None:
        row = self._pending_selection_row
        identity = self._selection_identity
        if row is None or identity is None:
            return
        index = self._model.index(row, 0)
        entry = self._model.entry_for_index(index)
        if entry is None:
            return
        self._pending_selection_row = None
        if archive_durable_identity_key(entry.identity) == archive_durable_identity_key(identity):
            self.selectionIndexReady.emit(index)
        else:
            self.selectionUnavailable.emit(identity)

    def _handle_failure(
        self,
        request_id: str,
        error: object,
        *,
        tracked: _TrackedRequest | None = None,
    ) -> None:
        current = tracked or self._requests.pop(request_id, None)
        if current is None or current.generation != self._generation:
            return
        if current.kind == "structure_children":
            if isinstance(current.payload, _StructureChildrenFetch):
                self._structure_inflight.discard(current.payload)
            self.requestFailed.emit(current.kind, error)
            return
        if current.kind == "page" and isinstance(current.payload, RemotePageFetch):
            self._model.reject_page(current.payload.page_start)
        elif current.kind == "children" and isinstance(current.payload, RemoteChildrenFetch):
            self._model.reject_children(current.payload)
        if current.kind.startswith("stage_") or current.kind in {"open", "query"}:
            self._fail_publication(current.kind, error)
            return
        if current.kind == "selection":
            self.selectionUnavailable.emit(self._selection_identity)
        self.requestFailed.emit(current.kind, error)

    def _handle_cancelled(self, request_id: str) -> None:
        tracked = self._requests.pop(request_id, None)
        if tracked is None:
            return
        if tracked.kind == "structure_children" and isinstance(tracked.payload, _StructureChildrenFetch):
            self._structure_inflight.discard(tracked.payload)
            self._structure_pending.add(tracked.payload)
            return
        if tracked.kind == "page" and isinstance(tracked.payload, RemotePageFetch):
            self._model.reject_page(tracked.payload.page_start)
        elif tracked.kind == "children" and isinstance(tracked.payload, RemoteChildrenFetch):
            self._model.reject_children(tracked.payload)

    def _handle_progress(self, request_id: str, update: object) -> None:
        tracked = self._requests.get(request_id)
        if tracked is not None and tracked.generation == self._generation:
            self.progressChanged.emit(tracked.kind, update)

    def _handle_batch(self, request_id: str, _operation: str, result: object) -> None:
        tracked = self._requests.get(request_id)
        if (
            tracked is None
            or tracked.generation != self._generation
            or tracked.kind != "selection"
            or not isinstance(tracked.payload, _SelectionRequest)
            or not isinstance(result, ArchiveLookupResult)
        ):
            return
        tracked.payload.entries.extend(result.entries)
        tracked.payload.query_rows.extend(result.query_rows)

    def _fail_publication(self, kind: str, error: object) -> None:
        self._cancel_tracked_requests()
        self._staged = None
        self._model.suspend_requests(False)
        self.statusChanged.emit("Archive catalogue update failed; the previous valid view remains open.")
        self.requestFailed.emit(kind, error)

    def _adopt_staged_session(self, staged: _StagedQuery, session_id: str) -> bool:
        if staged.session.session_id == session_id:
            return True
        session = self._service.session(session_id)
        if session is None or session.fingerprint != staged.session.fingerprint:
            return False
        staged.session = session
        staged.query = replace(staged.query, session_id=session.session_id)
        return True

    def _restart_current_query_after_recovery(self, session_id: str) -> None:
        current_session = self._current_session
        current_query = self._current_query
        recovered = self._service.session(session_id)
        if (
            current_session is None
            or current_query is None
            or recovered is None
            or recovered.fingerprint != current_session.fingerprint
        ):
            self._set_actions_safe(False)
            self.requestFailed.emit(
                "worker_recovery",
                RuntimeError("Archive worker recovery could not preserve the current source fingerprint."),
            )
            return
        self._current_session = recovered
        self.statusChanged.emit("Archive worker restarted; restoring the current archive query...")
        self.apply_query(replace(current_query, session_id=recovered.session_id))

    def _staged_payload_error(self, staged: _StagedQuery) -> str:
        handle = staged.handle
        if handle is None:
            return "Archive query handle is missing."
        if handle.session_id != staged.session.session_id:
            return "Archive query session does not match the staged session."
        if staged.first_page is not None:
            page = staged.first_page
            if (
                page.session_id != handle.session_id
                or page.query_id != handle.query_id
                or page.generation != handle.generation
                or page.total_matches != handle.total_matches
                or page.page_start != 0
                or len(page.rows) > self._model.page_size
                or page.page_start + len(page.rows) > page.total_matches
                or any(row.session_id != handle.session_id for row in page.rows)
            ):
                return "First archive page does not match the staged query."
        if staged.first_children is not None:
            children = staged.first_children
            fetch = staged.first_children_fetch
            if (
                fetch is None
                or children.session_id != handle.session_id
                or children.query_id != handle.query_id
                or children.offset != fetch.offset
            ):
                return "First archive child page does not match the staged query."
        if staged.facets is not None and staged.facets.session_id != handle.session_id:
            return "Archive facets do not match the staged session."
        return ""

    def _set_actions_safe(self, safe: bool) -> None:
        normalized = bool(safe)
        if self._actions_safe == normalized:
            return
        self._actions_safe = normalized
        self.actionsSafeChanged.emit(normalized)


def _fetch_matches_handle(fetch: object, handle: ArchiveQueryHandle) -> bool:
    return (
        getattr(fetch, "session_id", None) == handle.session_id
        and getattr(fetch, "query_id", None) == handle.query_id
        and getattr(fetch, "generation", None) == handle.generation
    )


__all__ = ["ArchiveRemoteCatalogueController"]
