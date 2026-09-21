"""Prepare template textures through the same bounded archive worker as Browse."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import threading

from PySide6.QtCore import QObject, QThread

from cdmw.domain.archives.catalogue import ArchiveLookupKind, ArchiveLookupRequest, ArchiveLookupResult
from cdmw.domain.cancellation import RunCancelled, raise_if_cancelled
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.ui.archive_browser.remote_preview_dependencies import (
    ArchiveRemotePreviewDependencyProvider, MAX_ARCHIVE_PREVIEW_ENTRIES,
)


@dataclass
class PreparedTemplateDependencies:
    """Immutable after publication; only preview workers wait for preparation."""

    done: threading.Event = field(default_factory=threading.Event)
    entries: tuple = ()
    error: Exception | None = None

    def wait(self, stop_event):
        if not self.done.is_set() and QThread.currentThread().isMainThread():
            raise RuntimeError("Template textures must be prepared on a preview worker.")
        while not self.done.wait(0.05):
            raise_if_cancelled(stop_event)
        raise_if_cancelled(stop_event)
        if self.error is not None:
            raise self.error
        return self.entries


class TemplatePreviewDependencies(QObject):
    """GUI-owned latest-wins lookup; shared by Template, Placement and Effects."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service
        self._provider = ArchiveRemotePreviewDependencyProvider(service, self, include_content_analysis=False)
        self._provider.ready.connect(self._model_ready)
        self._provider.failed.connect(self._model_failed)
        service.batch_ready.connect(self._batch)
        service.result_ready.connect(self._result)
        service.request_failed.connect(self._request_failed)
        service.request_cancelled.connect(self._request_cancelled)
        self._cache = OrderedDict()
        self._active = None
        self._request = None
        self._generation = 0
        self._closed = False

    def capture(self, models, prefabs):
        session = self._service.current_session
        identities = tuple(entry.identity for entry in (*models, *prefabs))
        key = (getattr(session, "session_id", None), getattr(session, "fingerprint", None), identities)
        if key in self._cache:
            self.cancel()
            self._cache.move_to_end(key)
            return self._cache[key]
        if self._active is not None and key == self._key:
            return self._active
        self.cancel()
        ticket = PreparedTemplateDependencies()
        if self._closed or session is None:
            ticket.error = RuntimeError("The archive catalogue is unavailable. Refresh the archives.")
            ticket.done.set()
            return ticket
        self._active, self._key = ticket, key
        self._session = session.session_id
        self._models, self._prefabs = tuple(models), tuple(prefabs)
        self._dtos, self._entries = {}, {}
        self._model_index = 0
        self._generation += 1
        if not models or len(models) > 32 or len(prefabs) > 32 or len(identities) > MAX_ARCHIVE_PREVIEW_ENTRIES:
            self._fail(ValueError("The template exceeds the bounded preview component limit."))
            return ticket
        try:
            self._request = self._service.resolve_entries(ArchiveLookupRequest(
                self._session, ArchiveLookupKind.EXACT_PATHS,
                values=tuple(dict.fromkeys(entry.path for entry in (*models, *prefabs))),
                limit=MAX_ARCHIVE_PREVIEW_ENTRIES,
            ), ui_generation=self._generation)
        except Exception as error:
            self._fail(error)
        return ticket

    def cancel(self):
        self._fail(RunCancelled("Template texture preparation cancelled."))

    def shutdown(self):
        self._closed = True
        self.cancel()
        self._cache.clear()

    def _fail(self, error):
        ticket, self._active = self._active, None
        request, self._request = self._request, None
        if ticket is not None:
            ticket.error = error
            ticket.done.set()
        self._provider.cancel(clear_snapshot=True)
        if request is not None:
            try:
                self._service.cancel(request)
            except (AttributeError, RuntimeError):
                pass  # The archive process may already be closing.

    def _batch(self, request, _operation, result):
        if request != self._request or self._active is None:
            return
        if not isinstance(result, ArchiveLookupResult) or result.session_id != self._session or result.truncated:
            self._fail(ValueError("The archive worker returned incomplete template dependencies."))
            return
        for dto in result.entries:
            self._dtos[ArchiveCatalogueService.compatibility_entry(dto).identity] = dto

    def _result(self, request, operation, result):
        if request != self._request or self._active is None:
            return
        self._batch(request, operation, result)
        if self._active is None:
            return
        self._request = None
        if any(entry.identity not in self._dtos for entry in (*self._models, *self._prefabs)):
            self._fail(ValueError("The template archive source changed. Refresh the archives."))
            return
        self._next_model()

    def _next_model(self):
        if self._model_index == len(self._models):
            ticket, self._active = self._active, None
            ticket.entries = tuple(self._entries.values())
            ticket.done.set()
            self._cache[self._key] = ticket
            while len(self._cache) > 4:
                self._cache.popitem(last=False)
            return
        selected = self._dtos[self._models[self._model_index].identity]
        self._provider.request(selected, ui_request_id=self._generation,
            preferred_prefab_stems=tuple(entry.basename.rsplit(".", 1)[0] for entry in self._prefabs),
            scope_entry_ids=tuple(self._dtos[entry.identity].entry_id for entry in self._prefabs))

    def _model_ready(self, generation, snapshot):
        if self._active is None or generation != self._generation:
            return
        session = self._service.current_session
        if session is None or (session.session_id, session.fingerprint) != self._key[:2]:
            self._fail(ValueError("The archive catalogue changed. Refresh the archives."))
            return
        expected = self._dtos[self._models[self._model_index].identity]
        if snapshot.session_id != self._session or snapshot.entry_id != expected.entry_id or snapshot.truncated:
            self._fail(ValueError("The archive worker returned incomplete template dependencies."))
            return
        for entry in snapshot.entries:
            self._entries.setdefault(entry.identity, entry)
        if len(self._entries) > MAX_ARCHIVE_PREVIEW_ENTRIES:
            self._fail(ValueError("The template exceeds the bounded preview dependency limit."))
            return
        self._model_index += 1
        self._next_model()

    def _model_failed(self, generation, message):
        if self._active is not None and generation == self._generation:
            self._fail(RuntimeError(message))

    def _request_failed(self, request, error):
        if request == self._request and self._active is not None:
            self._fail(RuntimeError(str(getattr(error, "message", error))))

    def _request_cancelled(self, request):
        if request == self._request and self._active is not None:
            self.cancel()
