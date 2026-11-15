"""Bounded worn-set discovery for the Item Finder's archive preview."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from cdmw.domain.archives.catalogue import (
    ArchiveEntryDto, ArchiveLookupKind, ArchiveLookupRequest, ArchiveLookupResult,
)


class ItemSetScopeResolver(QObject):
    """Resolve all scoped rows before choosing the primary, independent of paging."""
    ready = Signal(str, object)
    failed = Signal(str)

    def __init__(self, service: object, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._request_id: str | None = None
        self._session_id = ""
        self._ids: frozenset[int] = frozenset()
        self._entries: dict[int, ArchiveEntryDto] = {}
        service.batch_ready.connect(self._batch)
        service.result_ready.connect(self._result)
        service.request_failed.connect(self._failed)
        service.request_cancelled.connect(self._cancelled)

    def request(self, session_id: str, entry_ids: tuple[int, ...], generation: int) -> bool:
        self.cancel()
        self._session_id = session_id
        self._ids = frozenset(entry_ids)
        if not self._ids or len(self._ids) > 4096:
            return False
        try:
            self._request_id = self._service.resolve_entries(
                ArchiveLookupRequest(session_id, ArchiveLookupKind.ENTRY_IDS,
                                     entry_ids=entry_ids, limit=len(entry_ids)),
                ui_generation=generation,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return False
        return True

    def cancel(self) -> None:
        request_id, self._request_id = self._request_id, None
        self._entries.clear()
        self._ids = frozenset()
        if request_id is not None:
            try:
                self._service.cancel(request_id)
            except (AttributeError, RuntimeError):
                pass  # The owning service may already be gone during shutdown.

    def _accept(self, payload: object) -> bool:
        if not isinstance(payload, ArchiveLookupResult) or payload.session_id != self._session_id or payload.truncated:
            return False
        for entry in payload.entries:
            if entry.session_id != self._session_id or entry.entry_id not in self._ids:
                return False
            self._entries[entry.entry_id] = entry
        return True

    def _batch(self, request_id: str, operation: str, payload: object) -> None:
        if request_id == self._request_id and operation == "resolve_entries" and not self._accept(payload):
            self._fail("This choice has incomplete or ambiguous dependencies.")

    def _result(self, request_id: str, operation: str, payload: object) -> None:
        if request_id != self._request_id or operation != "resolve_entries":
            return
        if not self._accept(payload) or set(self._entries) != self._ids:
            self._fail("This choice has incomplete or ambiguous dependencies.")
            return
        entries = tuple(self._entries.values())
        self._request_id = None
        self._entries.clear()
        self.ready.emit(self._session_id, entries)

    def _fail(self, message: str) -> None:
        self.cancel()
        self.failed.emit(message)

    def _failed(self, request_id: str, error: object) -> None:
        if request_id == self._request_id:
            self._fail(str(getattr(error, "message", error)))

    def _cancelled(self, request_id: str) -> None:
        if request_id == self._request_id:
            self._request_id = None
            self._entries.clear()
            self.failed.emit("Item set preview preparation was cancelled.")
