"""Resolve the active barber icons for a page and discard obsolete results."""
import threading

from PySide6.QtCore import QObject, Signal

from cdmw.domain.archives.catalogue import ArchiveLookupKind, ArchiveLookupRequest, ArchiveLookupResult
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService


class HairIconPreparation(QObject):
    ready = Signal(int, object)

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self._owner = owner
        self._service = owner.archive.archive_catalogue_service
        self._request = None
        self._token = 0
        self._stop = threading.Event()
        self._entries = {}
        self._service.batch_ready.connect(self._batch)
        self._service.result_ready.connect(self._result)
        self._service.request_failed.connect(self._failed)
        self._service.request_cancelled.connect(self._failed)

    def cancel(self):
        self._token += 1
        self._stop.set()
        request, self._request = self._request, None
        self._entries.clear()
        if request:
            self._service.cancel(request)

    def start(self, session_id, paths, generation):
        self.cancel()
        self._session_id, self._generation = session_id, generation
        self._stop = threading.Event()
        self._paths = frozenset(path.casefold() for path in paths)
        self._truncated = False
        if not self._paths:
            self.ready.emit(generation, {})
            return
        if len(self._paths) > 24:
            raise ValueError("Hair icons must be resolved one page at a time.")
        try:
            self._request = self._service.resolve_entries(ArchiveLookupRequest(session_id,
                ArchiveLookupKind.EXACT_PATHS, values=tuple(sorted(self._paths)), limit=192),
                ui_generation=generation)
        except Exception:
            self.ready.emit(generation, {})

    def _batch(self, request, _operation, result):
        if (request != self._request or not isinstance(result, ArchiveLookupResult)
                or result.session_id != self._session_id):
            return
        self._entries.update((entry.entry_id, entry) for entry in result.entries)
        self._truncated |= result.truncated

    def _result(self, request, operation, result):
        if (request != self._request or not isinstance(result, ArchiveLookupResult)
                or result.session_id != self._session_id):
            return
        self._batch(request, operation, result)
        self._request = None
        if self._truncated or len(self._entries) != result.total_matches:
            self.ready.emit(self._generation, {})
            return
        by_path = {}
        for entry in self._entries.values():
            if entry.path.casefold() in self._paths and not entry.override_state.casefold().startswith("shadowed"):
                by_path.setdefault(entry.path.casefold(), []).append(entry)
        entries = []
        for values in by_path.values():
            active = [entry for entry in values if entry.is_active_override or
                      entry.override_state.casefold().startswith("active")]
            selected = active if active else values
            if len(selected) == 1 and 0 < selected[0].original_size <= 2 * 1024 * 1024:
                entries.append(ArchiveCatalogueService.compatibility_entry(selected[0]))
        token, generation, stop = self._token, self._generation, self._stop
        def ready(images):
            if token == self._token and not stop.is_set():
                self.ready.emit(generation, images)
        if not entries:
            ready({})
            return
        from cdmw.workers.hair_catalogue_icons import prepare_hair_icons
        self._owner._run_utility_task_when_idle(status_message="Loading hairstyle thumbnails…",
            task=lambda _log: prepare_hair_icons(tuple(entries), stop), on_complete=ready,
            on_error=lambda _message: ready({}))

    def _failed(self, request, *_error):
        if request == self._request:
            self._request = None
            self.ready.emit(self._generation, {})
