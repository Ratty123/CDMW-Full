"""Find the current game files that saved Mesh Editor work was made from."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

from PySide6.QtCore import QObject

from cdmw.domain.archives.catalogue import (
    ArchiveLookupKind,
    ArchiveLookupRequest,
    ArchiveLookupResult,
)
from cdmw.models import ArchiveEntry

MAX_LOOKUP_PATHS = 256
SourceMap = Mapping[str, ArchiveEntry | None]


def normalized_archive_path(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/").casefold()


def _active(candidates: list) -> object | None:
    usable = [item for item in candidates if not str(item.override_state or "").casefold().startswith("shadowed")]
    active = [item for item in usable if item.is_active_override
              or str(item.override_state or "").casefold().startswith("active")]
    chosen = active or usable
    return chosen[0] if chosen else None


class SavedWorkSourceResolver(QObject):
    """Resolve game file paths to archive entries without blocking the UI.

    The callback receives None when no game archive is loaded, otherwise a
    mapping from each normalized path to its current entry, or None when the
    game no longer has that file.
    """

    def __init__(self, archive: object, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._archive = archive
        self._service = None
        self._request = None
        self._session_id = ""
        self._paths: tuple[str, ...] = ()
        self._callback: Callable[[SourceMap | None], None] | None = None
        self._dtos: dict[int, object] = {}
        # Catalogue entry ids of the last v2 lookup, for scoping Archive Browser.
        self.entry_ids: dict[str, int] = {}

    def _remote(self):
        bridge = getattr(self._archive, "archive_remote_bridge", None)
        return bridge if bridge is not None and bool(getattr(bridge, "displays_v2", False)) else None

    def cancel(self) -> None:
        request, self._request = self._request, None
        self._callback = None
        if request is not None and self._service is not None:
            try:
                self._service.cancel(request)
            except RuntimeError:
                pass

    def resolve(self, paths: Iterable[str], callback: Callable[[SourceMap | None], None]) -> None:
        self.cancel()
        wanted = tuple(dict.fromkeys(normalized_archive_path(path) for path in paths if str(path or "").strip()))
        wanted = wanted[:MAX_LOOKUP_PATHS]
        bridge = self._remote()
        if bridge is None:
            index = getattr(self._archive, "archive_entries_by_normalized_path", None) or {}
            if not index:
                callback(None)
                return
            callback({path: next(iter(index.get(path, ()) or ()), None) for path in wanted})
            return
        session = getattr(bridge, "current_session", None)
        service = getattr(self._archive, "archive_catalogue_service", None)
        if session is None or service is None:
            callback(None)
            return
        if not wanted:
            callback({})
            return
        if self._service is not service:
            if self._service is not None:
                self._disconnect()
            self._service = service
            service.batch_ready.connect(self._batch)
            service.result_ready.connect(self._result)
            service.request_failed.connect(self._failed)
            service.request_cancelled.connect(self._failed)
        self._session_id = str(session.session_id)
        self._paths = wanted
        self._callback = callback
        self._dtos = {}
        # A request older than the browser's current generation is cancelled.
        generation = int(getattr(getattr(bridge, "controller", None), "generation", 0) or 0)
        try:
            self._request = service.resolve_entries(
                ArchiveLookupRequest(self._session_id, ArchiveLookupKind.EXACT_PATHS,
                                     values=wanted, limit=max(16, len(wanted) * 8)),
                ui_generation=generation,
            )
        except Exception:
            self._request = None
            self._callback = None
            callback(None)

    def _disconnect(self) -> None:
        for signal, slot in (("batch_ready", self._batch), ("result_ready", self._result),
                             ("request_failed", self._failed), ("request_cancelled", self._failed)):
            try:
                getattr(self._service, signal).disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def _batch(self, request, _operation, result) -> None:
        if request != self._request or not isinstance(result, ArchiveLookupResult) or result.session_id != self._session_id:
            return
        self._dtos.update((dto.entry_id, dto) for dto in result.entries)

    def _result(self, request, operation, result) -> None:
        if request != self._request or not isinstance(result, ArchiveLookupResult) or result.session_id != self._session_id:
            return
        self._batch(request, operation, result)
        self._request = None
        callback, self._callback = self._callback, None
        if callback is None:
            return
        from cdmw.services.archive_catalogue_service import ArchiveCatalogueService

        by_path: dict[str, list] = {}
        for dto in self._dtos.values():
            by_path.setdefault(normalized_archive_path(dto.path), []).append(dto)
        resolved: dict[str, ArchiveEntry | None] = {}
        self.entry_ids = {}
        for path in self._paths:
            chosen = _active(by_path.get(path, []))
            resolved[path] = ArchiveCatalogueService.compatibility_entry(chosen) if chosen is not None else None
            if chosen is not None:
                self.entry_ids[path] = int(chosen.entry_id)
        callback(resolved)

    def _failed(self, request, *_error) -> None:
        if request != self._request:
            return
        self._request = None
        callback, self._callback = self._callback, None
        if callback is not None:
            callback(None)


__all__ = ["SavedWorkSourceResolver", "normalized_archive_path"]
