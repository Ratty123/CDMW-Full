"""Latest-wins bounded dependency lookups for v2 previews and workflows."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from PySide6.QtCore import QObject, Signal

from cdmw.domain.archives.catalogue import (
    ArchiveAssociationPurpose,
    ArchiveAssociationRequest,
    ArchiveAssociationResult,
    ArchiveEntryDto,
)
from cdmw.domain.archives.catalogue_operations import (
    PrepareEntryResult,
    PrepareEntriesRequest,
    PrepareEntriesResult,
)
from cdmw.models import ArchiveEntry, ArchiveEntryIdentity
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService


MAX_ARCHIVE_PREVIEW_ENTRIES = 4096
MAX_ARCHIVE_PREVIEW_DEPENDENCIES = MAX_ARCHIVE_PREVIEW_ENTRIES - 1
MAX_ARCHIVE_PREVIEW_SNAPSHOTS = 4


@dataclass(frozen=True, slots=True)
class ArchivePreviewDependencySet:
    """One selected row plus the bounded candidates supplied by the worker."""

    session_id: str
    entry_id: int
    entries: tuple[ArchiveEntry, ...]
    entries_by_normalized_path: Mapping[str, tuple[ArchiveEntry, ...]]
    entries_by_basename: Mapping[str, tuple[ArchiveEntry, ...]]
    total_candidates: int
    truncated: bool

    @property
    def selected_entry(self) -> ArchiveEntry:
        if not self.entries:
            raise ValueError("Archive preview dependency set has no selected entry.")
        return self.entries[0]

    @classmethod
    def from_dtos(
        cls,
        selected: ArchiveEntryDto,
        candidates: tuple[ArchiveEntryDto, ...],
        *,
        total_candidates: int,
        truncated: bool,
        prepared: Mapping[int, PrepareEntryResult],
    ) -> "ArchivePreviewDependencySet":
        ordered_dtos = (selected, *candidates)
        seen_ids: set[int] = set()
        entries: list[ArchiveEntry] = []
        paths: dict[str, list[ArchiveEntry]] = {}
        basenames: dict[str, list[ArchiveEntry]] = {}
        for dto in ordered_dtos:
            if dto.entry_id in seen_ids:
                continue
            seen_ids.add(dto.entry_id)
            entry = ArchiveCatalogueService.compatibility_entry(dto)
            prepared_item = prepared.get(dto.entry_id)
            if prepared_item is None:
                raise ValueError(f"Prepared preview source is missing for entry id {dto.entry_id}.")
            entry.prepared_path = Path(prepared_item.prepared_path)
            entry.prepared_sha256 = prepared_item.sha256
            entry.prepared_note = str(prepared_item.note or "")
            entries.append(entry)
            normalized_path = _normalized(entry.path)
            if normalized_path:
                paths.setdefault(normalized_path, []).append(entry)
            basename = entry.basename.strip().casefold()
            if basename:
                basenames.setdefault(basename, []).append(entry)
        return cls(
            session_id=selected.session_id,
            entry_id=selected.entry_id,
            entries=tuple(entries),
            entries_by_normalized_path={key: tuple(value) for key, value in paths.items()},
            entries_by_basename={key: tuple(value) for key, value in basenames.items()},
            total_candidates=max(0, int(total_candidates)),
            truncated=bool(truncated),
        )


@dataclass(slots=True)
class _PendingPreviewDependencies:
    request_id: str
    operation: str
    ui_request_id: int
    selected: ArchiveEntryDto
    candidates: dict[int, ArchiveEntryDto] = field(default_factory=dict)
    prepared: dict[int, PrepareEntryResult] = field(default_factory=dict)
    total_candidates: int = 0
    truncated: bool = False


class ArchiveRemotePreviewDependencyProvider(QObject):
    """Resolve prepared dependency sets without retaining the global catalogue."""

    ready = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, service: object, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._pending: _PendingPreviewDependencies | None = None
        self._snapshot: ArchivePreviewDependencySet | None = None
        self._snapshot_ui_request_id = -1
        self._snapshots_by_identity: OrderedDict[
            ArchiveEntryIdentity,
            ArchivePreviewDependencySet,
        ] = OrderedDict()
        service.batch_ready.connect(self._handle_batch)
        service.result_ready.connect(self._handle_result)
        service.request_failed.connect(self._handle_failure)
        service.request_cancelled.connect(self._handle_cancelled)

    @property
    def pending_ui_request_id(self) -> int | None:
        return None if self._pending is None else self._pending.ui_request_id

    def snapshot_for(self, ui_request_id: int, entry_id: int) -> ArchivePreviewDependencySet | None:
        snapshot = self._snapshot
        if snapshot is None:
            return None
        if snapshot.entry_id != int(entry_id) or self._snapshot_ui_request_id != int(ui_request_id):
            return None
        return snapshot

    def snapshot_for_entry(self, entry: ArchiveEntry) -> ArchivePreviewDependencySet | None:
        if not isinstance(entry, ArchiveEntry):
            return None
        snapshot = self._snapshots_by_identity.get(entry.identity)
        if snapshot is not None:
            self._snapshots_by_identity.move_to_end(entry.identity)
        return snapshot

    def request(self, selected: ArchiveEntryDto, *, ui_request_id: int) -> bool:
        self.cancel(clear_snapshot=False)
        request = ArchiveAssociationRequest(
            selected.session_id,
            selected.entry_id,
            limit=MAX_ARCHIVE_PREVIEW_DEPENDENCIES,
            purpose=ArchiveAssociationPurpose.PREVIEW,
        )
        try:
            request_id = self._service.find_association_candidates(
                request,
                ui_generation=int(ui_request_id),
            )
        except Exception as exc:
            self.failed.emit(int(ui_request_id), str(exc))
            return False
        self._pending = _PendingPreviewDependencies(
            request_id=str(request_id),
            operation="find_association_candidates",
            ui_request_id=int(ui_request_id),
            selected=selected,
        )
        return True

    def cancel(self, *, clear_snapshot: bool = False) -> None:
        pending = self._pending
        self._pending = None
        if pending is not None:
            try:
                self._service.cancel(pending.request_id)
            except (AttributeError, RuntimeError):
                pass
        if clear_snapshot:
            self._snapshot = None
            self._snapshot_ui_request_id = -1
            self._snapshots_by_identity.clear()

    def _handle_batch(self, request_id: str, operation: str, payload: object) -> None:
        pending = self._matching_pending(request_id, operation)
        if pending is None:
            return
        if pending.operation == "find_association_candidates":
            if not self._accept_payload(pending, payload):
                self._fail_pending("The archive worker returned preview candidates for the wrong entry.")
            return
        if pending.operation == "prepare_entries" and not self._accept_prepared_batch(pending, payload):
            self._fail_pending("The archive worker returned invalid prepared preview dependencies.")

    def _handle_result(self, request_id: str, operation: str, payload: object) -> None:
        pending = self._matching_pending(request_id, operation)
        if pending is None:
            return
        if pending.operation == "find_association_candidates":
            if not self._accept_payload(pending, payload):
                self._fail_pending("The archive worker returned preview candidates for the wrong entry.")
                return
            if pending.truncated:
                self._fail_pending(
                    "Archive preview dependency lookup exceeded the 4,096-entry safety bound."
                )
                return
            self._start_dependency_preparation(pending)
            return
        if pending.operation != "prepare_entries" or not self._accept_prepared_batch(pending, payload):
            self._fail_pending("The archive worker returned invalid prepared preview dependencies.")
            return
        expected_ids = {pending.selected.entry_id, *pending.candidates}
        if set(pending.prepared) != expected_ids:
            self._fail_pending("The archive worker did not prepare every bounded preview dependency.")
            return
        self._pending = None
        snapshot = ArchivePreviewDependencySet.from_dtos(
            pending.selected,
            tuple(pending.candidates.values()),
            total_candidates=pending.total_candidates,
            truncated=pending.truncated,
            prepared=pending.prepared,
        )
        self._snapshot = snapshot
        self._snapshot_ui_request_id = pending.ui_request_id
        self._remember_snapshot(snapshot)
        self.ready.emit(pending.ui_request_id, snapshot)

    def _remember_snapshot(self, snapshot: ArchivePreviewDependencySet) -> None:
        identity = snapshot.selected_entry.identity
        self._snapshots_by_identity[identity] = snapshot
        self._snapshots_by_identity.move_to_end(identity)
        while len(self._snapshots_by_identity) > MAX_ARCHIVE_PREVIEW_SNAPSHOTS:
            self._snapshots_by_identity.popitem(last=False)

    def _handle_failure(self, request_id: str, error: object) -> None:
        pending = self._pending
        if pending is None or pending.request_id != str(request_id):
            return
        message = str(getattr(error, "message", "") or error or "Archive preview lookup failed.")
        self._fail_pending(message)

    def _handle_cancelled(self, request_id: str) -> None:
        pending = self._pending
        if pending is not None and pending.request_id == str(request_id):
            self._pending = None

    def _matching_pending(
        self,
        request_id: str,
        operation: str,
    ) -> _PendingPreviewDependencies | None:
        pending = self._pending
        if (
            pending is None
            or pending.request_id != str(request_id)
            or str(operation) != (
                "find_association_candidates"
                if pending.operation == "find_association_candidates"
                else "prepare_entry"
            )
        ):
            return None
        return pending

    @staticmethod
    def _accept_payload(pending: _PendingPreviewDependencies, payload: object) -> bool:
        if not isinstance(payload, ArchiveAssociationResult):
            return False
        if payload.session_id != pending.selected.session_id or payload.entry_id != pending.selected.entry_id:
            return False
        for candidate in payload.candidates:
            pending.candidates.setdefault(candidate.entry_id, candidate)
        pending.total_candidates = max(pending.total_candidates, int(payload.total_candidates))
        pending.truncated = pending.truncated or bool(payload.truncated)
        return True

    @staticmethod
    def _accept_prepared_batch(
        pending: _PendingPreviewDependencies,
        payload: object,
    ) -> bool:
        if (
            not isinstance(payload, PrepareEntriesResult)
            or payload.session_id != pending.selected.session_id
        ):
            return False
        expected_ids = {pending.selected.entry_id, *pending.candidates}
        if payload.requested != len(expected_ids) or payload.prepared != len(expected_ids):
            return False
        for item in payload.items:
            if (
                item.entry.session_id != pending.selected.session_id
                or item.entry.entry_id not in expected_ids
            ):
                return False
            pending.prepared.setdefault(item.entry.entry_id, item)
        return True

    def _start_dependency_preparation(self, pending: _PendingPreviewDependencies) -> None:
        entry_ids = (pending.selected.entry_id, *pending.candidates)
        try:
            request_id = self._service.prepare_entries(
                PrepareEntriesRequest(pending.selected.session_id, entry_ids),
                ui_generation=pending.ui_request_id,
            )
        except Exception as exc:
            self._fail_pending(str(exc))
            return
        pending.request_id = str(request_id)
        pending.operation = "prepare_entries"

    def _fail_pending(self, message: str) -> None:
        pending = self._pending
        self._pending = None
        if pending is not None:
            try:
                self._service.cancel(pending.request_id)
            except (AttributeError, RuntimeError):
                pass
            self.failed.emit(pending.ui_request_id, str(message))


def _normalized(value: str) -> str:
    return str(value or "").replace("\\", "/").strip("/").casefold()


__all__ = [
    "ArchivePreviewDependencySet",
    "ArchiveRemotePreviewDependencyProvider",
    "MAX_ARCHIVE_PREVIEW_DEPENDENCIES",
    "MAX_ARCHIVE_PREVIEW_ENTRIES",
    "MAX_ARCHIVE_PREVIEW_SNAPSHOTS",
]
