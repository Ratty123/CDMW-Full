"""Bounded worn-set discovery for the Item Finder's archive preview."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QObject, Signal

from cdmw.domain.archives.catalogue import (
    ArchiveEntryDto, ArchiveLookupKind, ArchiveLookupRequest, ArchiveLookupResult,
)
from cdmw.domain.archives.catalogue_operations import PrepareEntriesRequest, PrepareEntriesResult
from cdmw.domain.archives.item_sets import MAX_SET_FILES

#: An item prefab is a few kilobytes (the Kuku Marni Laser Helm's are 1,998 bytes);
#: a larger file is not read on the UI thread.
_MAX_PREFAB_BYTES = 256 * 1024


def read_prefab_models(prepared_path: str) -> tuple[str, ...]:
    """The PAC paths a prepared ``.prefab`` lists, in its own order; () when unreadable."""

    from cdmw.core.prefab_binary import decode_prefab_binary

    try:
        path = Path(prepared_path)
        if path.stat().st_size > _MAX_PREFAB_BYTES:
            return ()
        strings = decode_prefab_binary(path.read_bytes()).resource_strings()
    except Exception:  # noqa: BLE001 - an unreadable prefab only leaves the set unfiltered
        return ()
    paths = (item.text.replace("\\", "/").strip() for item in strings)
    return tuple(dict.fromkeys(path for path in paths if path.casefold().endswith(".pac")))


class ItemSetScopeResolver(QObject):
    """Resolve all scoped rows before choosing the primary, independent of paging.

    Then read the item's own prefabs, the ones its model stems name, so the set can
    leave out other wearers' copies (`worn_set_members`). ``ready`` carries the
    session, the scoped entries and (prefab path, model paths) for those prefabs in
    the item's order: empty when there are none or they could not be read, and the
    set is then every worn model.
    """
    ready = Signal(str, object, object)
    failed = Signal(str)

    def __init__(
        self,
        service: object,
        parent: QObject | None = None,
        *,
        prefab_reader: Callable[[str], tuple[str, ...]] = read_prefab_models,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._prefab_reader = prefab_reader
        self._request_id: str | None = None
        self._operation = "resolve_entries"
        self._session_id = ""
        self._generation = 0
        self._ids: frozenset[int] = frozenset()
        self._stems: tuple[str, ...] = ()
        self._entries: dict[int, ArchiveEntryDto] = {}
        self._prefabs: tuple[ArchiveEntryDto, ...] = ()
        self._prepared: dict[int, str] = {}
        service.batch_ready.connect(self._batch)
        service.result_ready.connect(self._result)
        service.request_failed.connect(self._failed)
        service.request_cancelled.connect(self._cancelled)

    def request(
        self,
        session_id: str,
        entry_ids: tuple[int, ...],
        generation: int,
        prefab_stems: tuple[str, ...] = (),
    ) -> bool:
        self.cancel()
        self._session_id = session_id
        self._generation = int(generation)
        self._ids = frozenset(entry_ids)
        self._stems = tuple(dict.fromkeys(
            PurePosixPath(str(stem or "").replace("\\", "/")).name.casefold()
            for stem in prefab_stems if str(stem or "").strip()
        ))
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
        self._operation = "resolve_entries"
        return True

    def cancel(self) -> None:
        request_id, self._request_id = self._request_id, None
        self._entries.clear()
        self._prepared.clear()
        self._prefabs = ()
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

    def _accept_prepared(self, payload: object) -> bool:
        if not isinstance(payload, PrepareEntriesResult) or payload.session_id != self._session_id:
            return False
        wanted = {entry.entry_id for entry in self._prefabs}
        for item in payload.items:
            if item.entry.session_id != self._session_id or item.entry.entry_id not in wanted:
                return False
            self._prepared[item.entry.entry_id] = item.prepared_path
        return True

    def _batch(self, request_id: str, operation: str, payload: object) -> None:
        if request_id != self._request_id or operation != self._operation:
            return
        if self._operation == "resolve_entries":
            if not self._accept(payload):
                self._fail("This choice has incomplete or ambiguous dependencies.")
        elif not self._accept_prepared(payload):
            self._publish_worn_set(())

    def _result(self, request_id: str, operation: str, payload: object) -> None:
        if request_id != self._request_id or operation != self._operation:
            return
        if self._operation == "resolve_entries":
            if not self._accept(payload) or set(self._entries) != self._ids:
                self._fail("This choice has incomplete or ambiguous dependencies.")
                return
            self._read_item_prefabs()
            return
        if not self._accept_prepared(payload):
            self._publish_worn_set(())
            return
        self._publish_worn_set(tuple(
            (path, models) for path, models in (
                (entry.path, self._prefab_reader(self._prepared[entry.entry_id]))
                for entry in self._prefabs if entry.entry_id in self._prepared
            ) if models
        ))

    def _read_item_prefabs(self) -> None:
        rank = {stem: index for index, stem in enumerate(self._stems)}
        prefabs = sorted(
            (entry for entry in self._entries.values()
             if entry.extension.casefold() == ".prefab"
             and "dropitem" not in entry.path.casefold()
             and PurePosixPath(entry.path.replace("\\", "/")).stem.casefold() in rank),
            key=lambda entry: (rank[PurePosixPath(entry.path.replace("\\", "/")).stem.casefold()],
                               entry.path.casefold(), entry.entry_id),
        )
        self._prefabs = tuple(prefabs[:MAX_SET_FILES])
        if not self._prefabs:
            self._publish_worn_set(())
            return
        try:
            self._request_id = self._service.prepare_entries(
                PrepareEntriesRequest(self._session_id, tuple(entry.entry_id for entry in self._prefabs)),
                ui_generation=self._generation,
            )
        except Exception:  # noqa: BLE001 - the set still opens, unfiltered
            self._publish_worn_set(())
            return
        self._operation = "prepare_entry"

    def _publish_worn_set(self, prefab_models: tuple[tuple[str, tuple[str, ...]], ...]) -> None:
        entries = tuple(self._entries.values())
        self._request_id = None
        self._entries.clear()
        self._prepared.clear()
        self._prefabs = ()
        self.ready.emit(self._session_id, entries, prefab_models)

    def _fail(self, message: str) -> None:
        self.cancel()
        self.failed.emit(message)

    def _failed(self, request_id: str, error: object) -> None:
        if request_id != self._request_id:
            return
        if self._operation == "prepare_entry":
            self._publish_worn_set(())  # The prefabs only narrow the set; without them it opens whole.
            return
        self._fail(str(getattr(error, "message", error)))

    def _cancelled(self, request_id: str) -> None:
        if request_id == self._request_id:
            self._request_id = None
            self._entries.clear()
            self._prepared.clear()
            self._prefabs = ()
            self.failed.emit("Item set preview preparation was cancelled.")
