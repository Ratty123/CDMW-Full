"""Incoming-reference search over legacy entries or the resident catalogue.

A search reads only the formats measured to store paths of the target's kind
(`reference_search_plan`). With a worker that offers byte search, the worker
finds the files holding the target's name natively and Python reads just those;
otherwise every file of those formats is prepared and read in pages.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from cdmw.core.archive_reverse_references import (
    MAX_REFERENCE_FILE_BYTES, MAX_REFERENCE_RESULTS, NOTE_NO_PATH_SOURCES, NOTE_RUNTIME_NAMED_SOUND, ReferenceScanBatch,
    REVERSE_TARGET_EXTENSIONS, bank_media_id_query, reference_evidence_group, reference_search_plan,
    reference_source_extension_groups,
)
from cdmw.domain.archives.catalogue import (
    ArchiveLookupKind, ArchiveLookupRequest, ArchiveLookupResult, ArchivePage, ArchiveQuery, ArchiveQueryHandle,
)
from cdmw.domain.archives.catalogue_operations import (
    ArchiveTextSearchBatch, ArchiveTextSearchRequest, FetchPageRequest, PrepareEntriesRequest, PrepareEntriesResult,
)
from cdmw.models import ArchiveEntry, ArchiveModelTextureReference
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.workers.archive_reference_workers import ArchiveReferenceScanWorker


@dataclass(frozen=True)
class ReferenceSearchState:
    generation: int
    target: ArchiveEntry
    session_id: str = ""
    references: tuple[ArchiveModelTextureReference, ...] = ()
    total: int = 0
    visited: int = 0
    scanned: int = 0
    skipped: int = 0
    unreadable: int = 0
    unsupported_banks: int = 0
    bytes_read: int = 0
    finished: bool = False
    cancelled: bool = False
    limited: bool = False
    error: str = ""
    #: Why the plan reads nothing, for example a sound chosen by name at run time.
    note: str = ""
    #: Files the worker's byte search found holding the target's name.
    candidates: int = 0


#: Worker byte-search hits per needle; a stem shared by thousands of files stops here.
MAX_REFERENCE_CANDIDATES = 10_000
#: Candidate files resolved and prepared per request in the byte-search path.
CANDIDATE_PAGE_SIZE = 32


class ArchiveReferenceSearchController(QObject):
    updated = Signal(object)
    idle = Signal()

    def __init__(self, catalogue=None, parent=None):
        super().__init__(parent)
        self.catalogue = catalogue
        self.state = None
        self._epoch = 0
        self._active = False
        self._request = None
        self._thread = None
        self._worker = None
        self._query = None
        self._page = ()
        self._prepared = {}
        self._legacy = ()
        self._position = 0
        self._extension_groups = iter(())
        self._source_extensions = ()
        self._plan = None
        self._native = False
        self._needle_queries = []
        self._candidates = {}
        self._confirm_ids = ()
        self._confirm_position = 0
        self._confirming = False
        self._resolved = []
        self._group_total = 0
        self._scanned_base = 0
        self._counting_scans = False
        if catalogue is not None:
            catalogue.result_ready.connect(self._result)
            catalogue.batch_ready.connect(self._prepared_batch)
            catalogue.request_failed.connect(self._failure)
            catalogue.request_cancelled.connect(self._cancelled)
            progress = getattr(catalogue, "progress", None)
            if progress is not None:
                progress.connect(self._progress)

    @property
    def busy(self):
        return self._active or self._thread is not None

    def start(self, target, entries=(), *, session_id="", generation=0):
        if self.busy:
            return False
        self._epoch += 1
        self._active = True
        self._position = 0
        self._query = None
        self._legacy = tuple(entries) if not session_id else ()
        self._needle_queries = []
        self._candidates = {}
        self._confirm_ids = ()
        self._confirming = False
        self._resolved = []
        self._counting_scans = False
        self._scanned_base = 0
        self._group_total = 0
        self._plan = reference_search_plan(target)
        self._native = bool(session_id) and bool(getattr(self.catalogue, "byte_search_available", False))
        self._extension_groups = iter(self._plan.groups)
        self.state = ReferenceSearchState(
            generation, replace(target), session_id, total=len(self._legacy), note=self._plan.note,
        )
        self.updated.emit(self.state)
        self._next_source_group()
        return True

    def _next_source_group(self):
        if not self._active:
            return
        self._position = 0
        self._query = None
        self._source_extensions = next(self._extension_groups, ())
        if not self._source_extensions:
            self._finish()
            return
        try:
            if self.state.session_id:
                self._request = self.catalogue.create_query(
                    ArchiveQuery(self.state.session_id, extensions=self._source_extensions),
                    ui_generation=self.state.generation,
                )
            else:
                QTimer.singleShot(0, self._advance)
        except Exception as exc:
            self._finish(error=str(exc))

    def cancel(self):
        self._epoch += 1
        self._active = False
        self._prepared.clear()
        request, self._request = self._request, None
        if request is not None:
            self.catalogue.cancel(request)
        if self._worker is not None:
            self._worker.stop()
        if self.state is not None and not self.state.finished:
            self.state = replace(self.state, finished=True, cancelled=True)
            self.updated.emit(self.state)
        if self._thread is None:
            self.idle.emit()

    def request_shutdown(self):
        self.cancel()

    def iter_shutdown_workers(self):
        if self._thread is not None:
            yield "archive_references", self._thread, self._worker

    def _finish(self, **fields):
        self._active = False
        self._request = None
        self._prepared.clear()
        self._candidates = {}
        self._confirm_ids = ()
        self._confirming = False
        self._resolved = []
        self.state = replace(self.state, finished=True, **fields)
        self.updated.emit(self.state)
        if self._thread is None:
            self.idle.emit()

    # -- byte-search path: the worker finds candidate files, Python confirms them

    def _begin_native_search(self):
        plan = self._plan
        if plan.bank_media_id is not None and ".bnk" in self._source_extensions:
            # Banks store media IDs as four little-endian bytes, never as names.
            self._needle_queries = [(bank_media_id_query(plan.bank_media_id), True)]
        else:
            self._needle_queries = [(needle, False) for needle in plan.needles]
        self._candidates = {}
        self._scanned_base = self.state.scanned
        self._search_next_needle(first=True)

    def _search_next_needle(self, *, first=False):
        if not self._active:
            return
        if not self._needle_queries:
            self._counting_scans = False
            self._confirm_ids = tuple(self._candidates)
            self._confirm_position = 0
            self._confirming = True
            self.state = replace(self.state, candidates=self.state.candidates + len(self._confirm_ids))
            self.updated.emit(self.state)
            self._confirm_next()
            return
        query, case_sensitive = self._needle_queries.pop(0)
        self._counting_scans = first
        try:
            self._request = self.catalogue.text_search(
                ArchiveTextSearchRequest(
                    self.state.session_id, query, case_sensitive=case_sensitive,
                    extensions=self._source_extensions, maximum_matches=MAX_REFERENCE_CANDIDATES,
                    context_characters=0, match_bytes=True,
                ),
                ui_generation=self.state.generation,
            )
        except Exception as exc:
            self._finish(error=str(exc))

    def _collect_candidates(self, payload):
        if payload.session_id != self.state.session_id:
            raise ValueError("Reference search received a mismatched archive search batch.")
        for match in payload.matches:
            self._candidates.setdefault(match.entry_id, None)
        fields = {"limited": self.state.limited or payload.limit_reached}
        if self._counting_scans:
            scanned = self._scanned_base + payload.files_scanned
            fields.update(scanned=scanned, visited=scanned)
        self.state = replace(self.state, **fields)
        self.updated.emit(self.state)

    def _confirm_next(self):
        if not self._active or self._thread is not None:
            return
        if len(self.state.references) >= MAX_REFERENCE_RESULTS:
            self._finish(limited=True)
            return
        if self._confirm_position >= len(self._confirm_ids):
            self._confirming = False
            self._next_source_group()
            return
        chunk = self._confirm_ids[self._confirm_position:self._confirm_position + CANDIDATE_PAGE_SIZE]
        self._confirm_position += len(chunk)
        self._resolved = []
        try:
            self._request = self.catalogue.resolve_entries(
                ArchiveLookupRequest(self.state.session_id, ArchiveLookupKind.ENTRY_IDS, entry_ids=chunk, limit=len(chunk)),
                ui_generation=self.state.generation,
            )
        except Exception as exc:
            self._finish(error=str(exc))

    def _prepare_page(self, rows):
        entries = self._admit(tuple(ArchiveCatalogueService.compatibility_entry(dto) for dto in rows))
        identities = {entry.identity for entry in entries}
        self._page = tuple(dto for dto in rows if ArchiveCatalogueService.compatibility_entry(dto).identity in identities)
        if self._page:
            self._prepared.clear()
            self._request = self.catalogue.prepare_entries(
                PrepareEntriesRequest(self.state.session_id, tuple(dto.entry_id for dto in self._page)),
                ui_generation=self.state.generation,
            )
        else:
            QTimer.singleShot(0, self._advance)

    def _progress(self, request_id, update):
        # Text search reports its walk over the whole index; scale it to this group
        # so the counter moves while no candidate has been found yet.
        if not (self._active and self._native and request_id == self._request and self._counting_scans):
            return
        current, total = getattr(update, "completed", 0), getattr(update, "total", 0)
        if not total or self._group_total <= 0:
            return
        estimate = self._scanned_base + min(self._group_total, int(self._group_total * current / total))
        if estimate > self.state.scanned:
            self.state = replace(self.state, scanned=estimate, visited=estimate)
            self.updated.emit(self.state)

    def _advance(self):
        if not self._active or self._thread is not None:
            return
        if self._confirming:
            self._confirm_next()
            return
        if len(self.state.references) >= MAX_REFERENCE_RESULTS:
            self._finish(limited=True)
            return
        group_total = self._query.total_matches if self._query is not None else len(self._legacy)
        if self._position >= group_total:
            self._next_source_group()
            return
        try:
            if self._query is not None:
                self._request = self.catalogue.fetch_page(
                    FetchPageRequest(self._query.query_id, self._position, 16), ui_generation=self.state.generation,
                )
            else:
                # Keep each UI scheduling slice small even in a large legacy index.
                page = self._legacy[self._position:self._position + 128]
                self._position += len(page)
                candidates = tuple(entry for entry in page if entry.extension in self._source_extensions)
                entries = self._admit(candidates)
                self.state = replace(self.state, visited=self.state.visited + len(candidates))
                self._run(entries)
        except Exception as exc:
            self._finish(error=str(exc))

    def _admit(self, entries):
        accepted = []
        skipped = 0
        for entry in entries:
            size = max(entry.orig_size, entry.comp_size, entry.prepared_size or 0)
            if size > MAX_REFERENCE_FILE_BYTES:
                skipped += 1
                continue
            accepted.append(replace(entry))
        self.state = replace(self.state, skipped=self.state.skipped + skipped)
        return tuple(accepted)

    def _result(self, request_id, operation, payload):
        if not self._active or request_id != self._request:
            return
        self._request = None
        try:
            if isinstance(payload, ArchiveQueryHandle):
                if payload.session_id != self.state.session_id:
                    raise ValueError("Reference search received a mismatched archive page.")
                self._query = payload
                self._group_total = payload.total_matches
                self.state = replace(self.state, total=self.state.total + payload.total_matches)
                if self._native:
                    if payload.total_matches:
                        self._begin_native_search()
                    else:
                        self._next_source_group()
                else:
                    self._advance()
            elif isinstance(payload, ArchiveTextSearchBatch):
                # The final reply carries totals only; matches arrived as batches.
                self._collect_candidates(payload)
                self._search_next_needle()
            elif isinstance(payload, ArchiveLookupResult):
                rows = (*self._resolved, *payload.entries)
                self._resolved = []
                if payload.session_id != self.state.session_id or any(dto.session_id != self.state.session_id for dto in rows):
                    raise ValueError("Reference search received a mismatched archive lookup.")
                self._prepare_page(tuple(rows))
            elif isinstance(payload, ArchivePage):
                if (payload.page_start != self._position or payload.query_id != self._query.query_id
                        or payload.session_id != self.state.session_id or payload.generation != self._query.generation):
                    raise ValueError("Reference search received a mismatched archive page.")
                if not payload.rows:
                    if self._position < self._query.total_matches:
                        raise ValueError("Reference search received an incomplete archive page.")
                    self._finish()
                    return
                self._position += len(payload.rows)
                self.state = replace(self.state, visited=self.state.visited + len(payload.rows))
                self._prepare_page(payload.rows)
            elif isinstance(payload, PrepareEntriesResult):
                self._collect_prepared(payload)
                prepared, self._prepared = self._prepared, {}
                entries = []
                for dto in self._page:
                    item = prepared.get(dto.entry_id)
                    if (item is None or payload.session_id != self.state.session_id
                            or item.entry.session_id != payload.session_id or item.entry.identity != dto.identity):
                        raise ValueError("Reference search preparation omitted a requested file.")
                    entry = ArchiveCatalogueService.compatibility_entry(dto)
                    entry.prepared_path = Path(item.prepared_path)
                    entry.prepared_size = item.size
                    entry.prepared_sha256 = item.sha256
                    entries.append(entry)
                self._run(tuple(entries))
            else:
                raise ValueError("Reference search received an unexpected archive response.")
        except Exception as exc:
            self._finish(error=str(exc))

    def _collect_prepared(self, payload):
        expected = {dto.entry_id: dto for dto in self._page}
        if (payload.session_id != self.state.session_id or payload.requested != len(expected)
                or payload.prepared != len(expected)):
            raise ValueError("Reference search preparation omitted a requested file.")
        for item in payload.items:
            dto = expected.get(item.entry.entry_id)
            previous = self._prepared.get(item.entry.entry_id)
            if (dto is None or item.entry.session_id != payload.session_id or item.entry.identity != dto.identity
                    or (previous is not None and previous != item)):
                raise ValueError("Reference search preparation omitted a requested file.")
            self._prepared[item.entry.entry_id] = item

    def _prepared_batch(self, request_id, operation, payload):
        if not self._active or request_id != self._request:
            return
        try:
            if isinstance(payload, ArchiveTextSearchBatch):
                self._collect_candidates(payload)
                return
            if isinstance(payload, ArchiveLookupResult):
                self._resolved.extend(payload.entries)
                return
            if not isinstance(payload, PrepareEntriesResult):
                raise ValueError("Reference search received an unexpected archive response.")
            self._collect_prepared(payload)
        except Exception as exc:
            request = self._request
            self._finish(error=str(exc))
            self.catalogue.cancel(request)

    def _run(self, entries):
        if not entries:
            self.updated.emit(self.state)
            QTimer.singleShot(0, self._advance)
            return
        worker = ArchiveReferenceScanWorker(self._epoch, self.state.target, entries)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._batch)
        worker.failed.connect(self._worker_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        self._worker, self._thread = worker, thread
        thread.start()

    def _batch(self, epoch, result: ReferenceScanBatch):
        if not self._active or epoch != self._epoch:
            return
        references = (*self.state.references, *result.references)
        # In the byte-search path the worker already counted these files as searched.
        scanned = self.state.scanned + (0 if self._native else result.scanned)
        self.state = replace(
            self.state, references=references[:MAX_REFERENCE_RESULTS],
            scanned=scanned, skipped=self.state.skipped + result.skipped,
            unreadable=self.state.unreadable + result.unreadable,
            unsupported_banks=self.state.unsupported_banks + result.unsupported_banks,
            bytes_read=self.state.bytes_read + result.bytes_read,
            limited=self.state.limited or len(references) >= MAX_REFERENCE_RESULTS,
        )
        self.updated.emit(self.state)

    def _thread_finished(self):
        thread, self._thread = self._thread, None
        self._worker = None
        if thread is not None:
            thread.deleteLater()
        if self._active:
            QTimer.singleShot(0, self._advance)
        else:
            self.idle.emit()

    def _worker_failed(self, epoch, message):
        if epoch == self._epoch and self._active:
            self._finish(error=message)

    def _failure(self, request_id, error):
        if self._active and request_id == self._request:
            self._finish(error=str(getattr(error, "message", error)))

    def _cancelled(self, request_id):
        if self._active and request_id == self._request:
            self.cancel()
