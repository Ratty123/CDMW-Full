"""Paged incoming-reference search over legacy entries or the resident catalogue."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from cdmw.core.archive_reverse_references import (
    MAX_REFERENCE_FILE_BYTES, MAX_REFERENCE_RESULTS, ReferenceScanBatch,
    REVERSE_TARGET_EXTENSIONS, reference_evidence_group, reference_source_extension_groups,
)
from cdmw.domain.archives.catalogue import ArchivePage, ArchiveQuery, ArchiveQueryHandle
from cdmw.domain.archives.catalogue_operations import FetchPageRequest, PrepareEntriesRequest, PrepareEntriesResult
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
        if catalogue is not None:
            catalogue.result_ready.connect(self._result)
            catalogue.batch_ready.connect(self._prepared_batch)
            catalogue.request_failed.connect(self._failure)
            catalogue.request_cancelled.connect(self._cancelled)

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
        self._extension_groups = iter(reference_source_extension_groups(target))
        self.state = ReferenceSearchState(generation, replace(target), session_id, total=len(self._legacy))
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
        self.state = replace(self.state, finished=True, **fields)
        self.updated.emit(self.state)
        if self._thread is None:
            self.idle.emit()

    def _advance(self):
        if not self._active or self._thread is not None:
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
                self.state = replace(self.state, total=self.state.total + payload.total_matches)
                self._advance()
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
                entries = self._admit(tuple(ArchiveCatalogueService.compatibility_entry(dto) for dto in payload.rows))
                identities = {entry.identity for entry in entries}
                self._page = tuple(dto for dto in payload.rows if ArchiveCatalogueService.compatibility_entry(dto).identity in identities)
                if self._page:
                    self._prepared.clear()
                    self._request = self.catalogue.prepare_entries(
                        PrepareEntriesRequest(self.state.session_id, tuple(dto.entry_id for dto in self._page)),
                        ui_generation=self.state.generation,
                    )
                else:
                    QTimer.singleShot(0, self._advance)
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
        self.state = replace(
            self.state, references=references[:MAX_REFERENCE_RESULTS],
            scanned=self.state.scanned + result.scanned, skipped=self.state.skipped + result.skipped,
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
