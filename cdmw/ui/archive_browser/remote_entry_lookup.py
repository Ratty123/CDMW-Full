"""Bounded live-catalogue lookups for Archive Browser workflows.

Older workflows matched paths against the in-memory ``archive_entries`` list. The
standalone catalogue never fills that list, so those workflows saw an empty archive
while the browser showed thousands of rows. This module resolves only the paths,
basenames or entry ids a workflow actually needs, through the archive worker, in
batches that stay inside the worker's 4,096-entry lookup bound.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from PySide6.QtCore import QObject

from cdmw.domain.archives.catalogue import (
    ArchiveEntryDto,
    ArchiveLookupKind,
    ArchiveLookupRequest,
    ArchiveLookupResult,
)
from cdmw.models import ArchiveEntry

REMOTE_LOOKUP_VALUES_PER_REQUEST = 256
REMOTE_LOOKUP_RESULT_LIMIT = 4096


class LiveCatalogueState:
    """How usable the live archive catalogue is for a workflow."""

    READY = "ready"
    LOADING = "loading"
    UNAVAILABLE = "unavailable"


def live_catalogue_state(owner: object) -> str:
    """Return whether the Archive Browser's live catalogue can answer lookups."""

    archive = getattr(owner, "archive", owner)
    bridge = getattr(archive, "archive_remote_bridge", None)
    if bridge is None:
        return LiveCatalogueState.UNAVAILABLE
    if getattr(bridge, "current_session", None) is not None:
        return LiveCatalogueState.READY
    if bool(getattr(archive, "archive_remote_query_pending", False)):
        return LiveCatalogueState.LOADING
    return LiveCatalogueState.UNAVAILABLE


def live_catalogue_unavailable_message(owner: object, action: str) -> str:
    """Explain why ``action`` cannot use the archive catalogue right now."""

    if live_catalogue_state(owner) == LiveCatalogueState.LOADING:
        return f"The archive catalogue is still loading. Retry {action} when the Archive Browser shows its results."
    return (
        "Archive packages are not loaded yet. Open Archive Browser and scan or load the archive cache, "
        f"then retry {action}."
    )


def normalized_lookup_path(path: str) -> str:
    """The key the legacy path index used: forward slashes, no edge slashes, casefolded."""

    return str(path or "").replace("\\", "/").strip().strip("/").casefold()


def lookup_basename(path: str) -> str:
    return PurePosixPath(normalized_lookup_path(path)).name


@dataclass(frozen=True, slots=True)
class RemoteLookupOutcome:
    session_id: str
    entries: tuple[ArchiveEntryDto, ...]
    truncated: bool
    #: Requests whose answer was cut at the result limit. The worker keeps the lowest
    #: entry ids across all values of a request, so any value in one may be incomplete.
    truncated_requests: tuple[ArchiveLookupRequest, ...] = ()


def lookup_requests(
    session_id: str,
    kind: ArchiveLookupKind,
    values: Iterable[object],
    *,
    chunk_size: int = REMOTE_LOOKUP_VALUES_PER_REQUEST,
) -> tuple[ArchiveLookupRequest, ...]:
    """Split ``values`` into bounded lookup requests of one kind."""

    if kind is ArchiveLookupKind.ENTRY_IDS:
        unique: tuple[object, ...] = tuple(dict.fromkeys(int(value) for value in values))
    else:
        unique = tuple(dict.fromkeys(str(value) for value in values if str(value or "").strip()))
    requests: list[ArchiveLookupRequest] = []
    size = max(1, int(chunk_size))
    for start in range(0, len(unique), size):
        chunk = unique[start : start + size]
        if kind is ArchiveLookupKind.ENTRY_IDS:
            requests.append(
                ArchiveLookupRequest(
                    session_id,
                    kind,
                    entry_ids=tuple(int(value) for value in chunk),
                    limit=REMOTE_LOOKUP_RESULT_LIMIT,
                )
            )
        else:
            requests.append(
                ArchiveLookupRequest(
                    session_id,
                    kind,
                    values=tuple(str(value) for value in chunk),
                    limit=REMOTE_LOOKUP_RESULT_LIMIT,
                )
            )
    return tuple(requests)


class ArchiveRemoteEntryLookup(QObject):
    """Run lookup requests one at a time and hand back every entry they matched."""

    def __init__(
        self,
        service: object,
        session_id: str,
        requests: Sequence[ArchiveLookupRequest],
        *,
        on_done: Callable[[RemoteLookupOutcome], None],
        on_error: Callable[[str], None],
        ui_generation: int = 0,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._session_id = str(session_id)
        self._pending = list(requests)
        self._on_done = on_done
        self._on_error = on_error
        self._generation = int(ui_generation)
        self._request_id: str | None = None
        self._request: ArchiveLookupRequest | None = None
        self._entries: dict[int, ArchiveEntryDto] = {}
        self._truncated = False
        self._truncated_requests: list[ArchiveLookupRequest] = []
        self._finished = False
        self._connected = False

    @property
    def running(self) -> bool:
        return not self._finished

    def start(self) -> None:
        service = self._service
        for signal_name, handler in (
            ("batch_ready", self._handle_batch),
            ("result_ready", self._handle_result),
            ("request_failed", self._handle_failed),
            ("request_cancelled", self._handle_cancelled),
        ):
            getattr(service, signal_name).connect(handler)
        self._connected = True
        self._dispatch_next()

    def cancel(self) -> None:
        if self._finished:
            return
        request_id = self._request_id
        self._request_id = None
        if request_id is not None:
            cancel = getattr(self._service, "cancel", None)
            if callable(cancel):
                try:
                    cancel(request_id)
                except Exception:
                    pass
        self._finish()

    def _dispatch_next(self) -> None:
        if self._finished:
            return
        if not self._pending:
            outcome = RemoteLookupOutcome(
                self._session_id,
                tuple(self._entries[key] for key in sorted(self._entries)),
                self._truncated,
                tuple(self._truncated_requests),
            )
            self._finish()
            self._on_done(outcome)
            return
        request = self._pending.pop(0)
        self._request = request
        try:
            self._request_id = self._service.resolve_entries(request, ui_generation=self._generation)
        except Exception as exc:
            self._fail(f"The archive worker could not start the lookup: {exc}")

    def _record(self, payload: ArchiveLookupResult) -> bool:
        if payload.session_id != self._session_id or any(
            entry.session_id != self._session_id for entry in payload.entries
        ):
            self._fail("The archive session changed during the lookup; retry the action.")
            return False
        for entry in payload.entries:
            self._entries[int(entry.entry_id)] = entry
        if payload.truncated:
            self._truncated = True
            request = self._request
            if request is not None and not any(request is seen for seen in self._truncated_requests):
                self._truncated_requests.append(request)
        return True

    def _handle_batch(self, request_id: str, operation: str, payload: object) -> None:
        if self._finished or request_id != self._request_id or operation != "resolve_entries":
            return
        if isinstance(payload, ArchiveLookupResult):
            self._record(payload)

    def _handle_result(self, request_id: str, operation: str, payload: object) -> None:
        if self._finished or request_id != self._request_id:
            return
        self._request_id = None
        if operation != "resolve_entries" or not isinstance(payload, ArchiveLookupResult):
            self._fail("The archive worker returned an invalid lookup result.")
            return
        if not self._record(payload):
            return
        self._dispatch_next()

    def _handle_failed(self, request_id: str, error: object) -> None:
        if self._finished or request_id != self._request_id:
            return
        self._request_id = None
        self._fail(str(getattr(error, "message", "") or error or "The archive lookup failed."))

    def _handle_cancelled(self, request_id: str) -> None:
        if self._finished or request_id != self._request_id:
            return
        self._request_id = None
        self._fail("The archive lookup was cancelled.")

    def _fail(self, message: str) -> None:
        if self._finished:
            return
        self._finish()
        self._on_error(message)

    def _finish(self) -> None:
        self._finished = True
        if self._connected:
            for signal_name, handler in (
                ("batch_ready", self._handle_batch),
                ("result_ready", self._handle_result),
                ("request_failed", self._handle_failed),
                ("request_cancelled", self._handle_cancelled),
            ):
                try:
                    getattr(self._service, signal_name).disconnect(handler)
                except (RuntimeError, TypeError):
                    pass
            self._connected = False


def start_live_catalogue_lookup(
    owner: object,
    attribute: str,
    requests: Sequence[ArchiveLookupRequest],
    *,
    on_done: Callable[[RemoteLookupOutcome], None],
    on_error: Callable[[str], None],
) -> ArchiveRemoteEntryLookup | None:
    """Start a lookup owned by ``owner.<attribute>``, replacing any earlier one there."""

    archive = getattr(owner, "archive", owner)
    bridge = getattr(archive, "archive_remote_bridge", None)
    session = getattr(bridge, "current_session", None)
    service = getattr(archive, "archive_catalogue_service", None)
    if session is None or service is None:
        on_error(live_catalogue_unavailable_message(owner, "the action"))
        return None
    previous = getattr(owner, attribute, None)
    if isinstance(previous, ArchiveRemoteEntryLookup):
        previous.cancel()
    generation = int(getattr(getattr(bridge, "controller", None), "generation", 0) or 0)

    def finished(outcome: RemoteLookupOutcome) -> None:
        if getattr(owner, attribute, None) is lookup:
            setattr(owner, attribute, None)
        on_done(outcome)

    def failed(message: str) -> None:
        if getattr(owner, attribute, None) is lookup:
            setattr(owner, attribute, None)
        on_error(message)

    lookup = ArchiveRemoteEntryLookup(
        service,
        session.session_id,
        requests,
        on_done=finished,
        on_error=failed,
        ui_generation=generation,
        parent=owner if isinstance(owner, QObject) else None,
    )
    setattr(owner, attribute, lookup)
    lookup.start()
    return lookup


def compatibility_entries(owner: object, entries: Iterable[ArchiveEntryDto]) -> tuple[ArchiveEntry, ...]:
    archive = getattr(owner, "archive", owner)
    service = getattr(archive, "archive_catalogue_service", None)
    convert = getattr(service, "compatibility_entry", None)
    if not callable(convert):
        from cdmw.services.archive_catalogue_service import ArchiveCatalogueService

        convert = ArchiveCatalogueService.compatibility_entry
    return tuple(convert(entry) for entry in entries)


def entry_indexes(
    entries: Iterable[ArchiveEntry],
) -> tuple[dict[str, tuple[ArchiveEntry, ...]], dict[str, tuple[ArchiveEntry, ...]]]:
    """Build path and basename indexes keyed the way the legacy indexes were."""

    by_path: dict[str, list[ArchiveEntry]] = {}
    by_basename: dict[str, list[ArchiveEntry]] = {}
    for entry in entries:
        path_key = normalized_lookup_path(entry.path)
        if not path_key:
            continue
        by_path.setdefault(path_key, []).append(entry)
        by_basename.setdefault(PurePosixPath(path_key).name, []).append(entry)
    return (
        {key: tuple(value) for key, value in by_path.items()},
        {key: tuple(value) for key, value in by_basename.items()},
    )


def dto_matching_entry(
    entries: Sequence[ArchiveEntryDto],
    entry: ArchiveEntry | None,
) -> ArchiveEntryDto | None:
    """Pick the DTO with ``entry``'s full archive identity, if there is one."""

    if entry is None:
        return None
    from cdmw.ui.archive_browser.remote_window_identity import (
        dto_identity_key,
        legacy_identity_key,
    )

    wanted = legacy_identity_key(entry)
    return next((candidate for candidate in entries if dto_identity_key(candidate) == wanted), None)


def legacy_indexes_available(owner: object) -> bool:
    archive = getattr(owner, "archive", owner)
    path_index: Mapping[str, object] = getattr(archive, "archive_entries_by_normalized_path", {}) or {}
    basename_index: Mapping[str, object] = getattr(archive, "archive_entries_by_basename", {}) or {}
    return bool(path_index and basename_index)


__all__ = [
    "REMOTE_LOOKUP_RESULT_LIMIT",
    "REMOTE_LOOKUP_VALUES_PER_REQUEST",
    "ArchiveRemoteEntryLookup",
    "LiveCatalogueState",
    "RemoteLookupOutcome",
    "compatibility_entries",
    "dto_matching_entry",
    "entry_indexes",
    "legacy_indexes_available",
    "live_catalogue_state",
    "live_catalogue_unavailable_message",
    "lookup_basename",
    "lookup_requests",
    "normalized_lookup_path",
    "start_live_catalogue_lookup",
]
