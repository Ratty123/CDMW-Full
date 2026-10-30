"""Paged incoming-reference search over legacy entries or the resident catalogue."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from cdmw.core.archive_reverse_references import (
    MAX_REFERENCE_FILE_BYTES, MAX_REFERENCE_RESULTS, MAX_REFERENCE_SCAN_BYTES,
    REFERENCE_SOURCE_EXTENSIONS, ReferenceScanBatch,
    REVERSE_TARGET_EXTENSIONS, reference_evidence_group,
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
        self._legacy = ()
        self._position = 0
        self._budget = 0
        if catalogue is not None:
            catalogue.result_ready.connect(self._result)
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
        self._position = self._budget = 0
        self._query = None
        self._legacy = tuple(entries) if not session_id else ()
        self.state = ReferenceSearchState(generation, replace(target), session_id, total=len(self._legacy))
        self.updated.emit(self.state)
        try:
            if session_id:
                self._request = self.catalogue.create_query(
                    ArchiveQuery(session_id, extensions=REFERENCE_SOURCE_EXTENSIONS), ui_generation=generation,
                )
            else:
                QTimer.singleShot(0, self._advance)
        except Exception as exc:
            self._finish(error=str(exc))
        return True

    def cancel(self):
        self._epoch += 1
        self._active = False
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
        self.state = replace(self.state, finished=True, **fields)
        self.updated.emit(self.state)
        if self._thread is None:
            self.idle.emit()

    def _advance(self):
        if not self._active or self._thread is not None:
            return
        if len(self.state.references) >= MAX_REFERENCE_RESULTS or self._budget >= MAX_REFERENCE_SCAN_BYTES:
            self._finish(limited=True)
            return
        if self._position >= self.state.total:
            self._finish()
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
                entries = self._admit(tuple(entry for entry in page if entry.extension in REFERENCE_SOURCE_EXTENSIONS))
                self.state = replace(self.state, visited=self._position)
                self._run(entries)
        except Exception as exc:
            self._finish(error=str(exc))

    def _admit(self, entries):
        accepted = []
        skipped = 0
        limited = self.state.limited
        for entry in entries:
            size = max(entry.orig_size, entry.comp_size, entry.prepared_size or 0)
            if size > MAX_REFERENCE_FILE_BYTES or self._budget + size > MAX_REFERENCE_SCAN_BYTES:
                skipped += 1
                limited |= self._budget + size > MAX_REFERENCE_SCAN_BYTES
                continue
            self._budget += size
            accepted.append(replace(entry))
        self.state = replace(self.state, skipped=self.state.skipped + skipped, limited=limited)
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
                self.state = replace(self.state, session_id=payload.session_id, total=payload.total_matches)
                self._advance()
            elif isinstance(payload, ArchivePage):
                if (payload.page_start != self._position or payload.query_id != self._query.query_id
                        or payload.session_id != self.state.session_id or payload.generation != self._query.generation):
                    raise ValueError("Reference search received a mismatched archive page.")
                if not payload.rows:
                    if self._position < self.state.total:
                        raise ValueError("Reference search received an incomplete archive page.")
                    self._finish()
                    return
                self._position += len(payload.rows)
                self.state = replace(self.state, visited=self._position)
                entries = self._admit(tuple(ArchiveCatalogueService.compatibility_entry(dto) for dto in payload.rows))
                identities = {entry.identity for entry in entries}
                self._page = tuple(dto for dto in payload.rows if ArchiveCatalogueService.compatibility_entry(dto).identity in identities)
                if self._page:
                    self._request = self.catalogue.prepare_entries(
                        PrepareEntriesRequest(self.state.session_id, tuple(dto.entry_id for dto in self._page)),
                        ui_generation=self.state.generation,
                    )
                else:
                    QTimer.singleShot(0, self._advance)
            elif isinstance(payload, PrepareEntriesResult):
                prepared = {item.entry.entry_id: item for item in payload.items}
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
