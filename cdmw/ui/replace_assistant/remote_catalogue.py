"""Bounded standalone archive integration for Replace Assistant."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence

from PySide6.QtWidgets import QDialog

from cdmw.domain.archives.catalogue import (
    ArchiveEntryDto,
    ArchiveLookupKind,
    ArchiveLookupRequest,
    ArchiveLookupResult,
    ArchiveSessionHandle,
)
from cdmw.domain.archives.catalogue_operations import PrepareEntryRequest, PrepareEntryResult
from cdmw.models import ReplaceAssistantBuildOptions, ReplaceAssistantItem
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.services.replace_assistant_service import (
    match_replace_assistant_item_to_archive_entry,
    replace_assistant_archive_lookup_values,
)
from cdmw.ui.replace_assistant.archive_picker import RemoteArchiveOriginalDialog


REMOTE_LOOKUP_ITEM_BATCH = 64
REMOTE_LOOKUP_RESULT_LIMIT = 4096


@dataclass(frozen=True, slots=True)
class _LookupBatch:
    kind: ArchiveLookupKind
    item_indices: tuple[int, ...]


class ReplaceAssistantArchiveCatalogueMixin:
    """Resolve only bounded candidate sets and retain session/entry references."""

    def _initialize_archive_catalogue(self, service: ArchiveCatalogueService | None) -> None:
        self.archive_catalogue_service = service
        self.archive_catalogue_session: ArchiveSessionHandle | None = None
        self.remote_match_request_id: str | None = None
        self.remote_build_request_id: str | None = None
        self._remote_generation = 0
        self._remote_match_refresh_preview = True
        self._remote_match_phase: ArchiveLookupKind | None = None
        self._remote_match_pending: list[_LookupBatch] = []
        self._remote_match_current: _LookupBatch | None = None
        self._remote_match_exact_values: dict[int, tuple[str, ...]] = {}
        self._remote_match_basename_values: dict[int, tuple[str, ...]] = {}
        self._remote_match_candidates: dict[int, list[ArchiveEntryDto]] = {}
        self._remote_match_truncated: set[int] = set()
        self._remote_build_options: ReplaceAssistantBuildOptions | None = None
        self._remote_build_entry_indices: dict[int, tuple[int, ...]] = {}
        self._remote_build_pending: list[int] = []
        self._remote_build_active_entry_id: int | None = None
        if service is None:
            return
        service.batch_ready.connect(self._handle_catalogue_batch)
        service.result_ready.connect(self._handle_catalogue_result)
        service.request_failed.connect(self._handle_catalogue_failure)
        service.request_cancelled.connect(self._handle_catalogue_cancelled)

    def set_archive_catalogue_session(self, session: ArchiveSessionHandle | None) -> None:
        previous = self.archive_catalogue_session
        if previous is not None and (session is None or previous.session_id != session.session_id):
            self._cancel_all_catalogue_requests(clear=True)
        self.archive_catalogue_session = session
        if session is None:
            self._update_controls()
            return
        self.archive_entries = []
        for item in self.items:
            matched = item.matched_original
            if matched is None or matched.archive_entry_id is None:
                continue
            if matched.archive_fingerprint and matched.archive_fingerprint != session.fingerprint:
                item.matched_original = None
                item.status = "unresolved"
                item.status_detail = "archive session changed; run Auto-Match again"
                item.warning = item.status_detail
            else:
                matched.archive_session_id = session.session_id
                matched.archive_fingerprint = session.fingerprint
        if self.items:
            self._refresh_queue_tree()
        self._update_controls()

    def _catalogue_archive_ready(self) -> bool:
        return self.archive_catalogue_service is not None and self.archive_catalogue_session is not None

    def _catalogue_request_busy(self) -> bool:
        return self.remote_match_request_id is not None or self.remote_build_request_id is not None

    def _archive_original_source_ready(self) -> bool:
        return self._catalogue_archive_ready() or bool(self.archive_entries or self.get_archive_entries())

    def _start_catalogue_auto_match(self, *, refresh_preview: bool) -> bool:
        service = self.archive_catalogue_service
        session = self.archive_catalogue_session
        if service is None or session is None:
            return False
        indices = tuple(index for index, item in enumerate(self.items) if item.matched_original is None)
        if not indices:
            self._finalize_auto_match(refresh_preview=refresh_preview, prompt_ambiguous=True)
            return True
        self._remote_generation += 1
        self._remote_match_refresh_preview = refresh_preview
        self._remote_match_exact_values = {}
        self._remote_match_basename_values = {}
        self._remote_match_candidates = {}
        self._remote_match_truncated = set()
        for index in indices:
            exact, basenames = replace_assistant_archive_lookup_values(self.items[index].source_path, self.archive_index)
            self._remote_match_exact_values[index] = exact
            self._remote_match_basename_values[index] = basenames
        self.status_label.setText("Resolving archive originals through the standalone catalogue...")
        self.append_log("Resolving bounded exact-path archive candidates through the standalone catalogue.")
        self._begin_lookup_phase(ArchiveLookupKind.EXACT_PATHS, indices)
        return True

    def _begin_lookup_phase(self, kind: ArchiveLookupKind, indices: Sequence[int]) -> None:
        self._remote_match_phase = kind
        self._remote_match_candidates = {index: [] for index in indices}
        self._remote_match_truncated = set()
        self._remote_match_pending = [
            _LookupBatch(kind, tuple(indices[start : start + REMOTE_LOOKUP_ITEM_BATCH]))
            for start in range(0, len(indices), REMOTE_LOOKUP_ITEM_BATCH)
        ]
        self._dispatch_next_lookup_batch()

    def _lookup_values_for_batch(self, batch: _LookupBatch) -> tuple[str, ...]:
        source = (
            self._remote_match_exact_values
            if batch.kind is ArchiveLookupKind.EXACT_PATHS
            else self._remote_match_basename_values
        )
        values: list[str] = []
        for index in batch.item_indices:
            values.extend(source.get(index, ()))
        return tuple(dict.fromkeys(values))

    def _dispatch_next_lookup_batch(self) -> None:
        service = self.archive_catalogue_service
        session = self.archive_catalogue_session
        if service is None or session is None:
            self._fail_remote_auto_match("The standalone archive session is unavailable.")
            return
        while self._remote_match_pending:
            batch = self._remote_match_pending.pop(0)
            values = self._lookup_values_for_batch(batch)
            if not values:
                continue
            self._remote_match_current = batch
            try:
                self.remote_match_request_id = service.resolve_entries(
                    ArchiveLookupRequest(
                        session_id=session.session_id,
                        kind=batch.kind,
                        values=values,
                        limit=REMOTE_LOOKUP_RESULT_LIMIT,
                    ),
                    ui_generation=self._remote_generation,
                )
            except Exception as exc:
                self._fail_remote_auto_match(str(exc))
            self._update_controls()
            return
        self._complete_lookup_phase()

    def _record_lookup_result(self, batch: _LookupBatch, result: ArchiveLookupResult) -> None:
        for index in batch.item_indices:
            values = (
                self._remote_match_exact_values.get(index, ())
                if batch.kind is ArchiveLookupKind.EXACT_PATHS
                else self._remote_match_basename_values.get(index, ())
            )
            value_keys = {value.replace("\\", "/").strip("/").casefold() for value in values}
            if batch.kind is ArchiveLookupKind.EXACT_PATHS:
                matched = [
                    entry
                    for entry in result.entries
                    if entry.path.replace("\\", "/").strip("/").casefold() in value_keys
                ]
            else:
                matched = [
                    entry
                    for entry in result.entries
                    if PurePosixPath(entry.path.replace("\\", "/")).name.casefold() in value_keys
                ]
            existing = {
                (entry.session_id, entry.entry_id)
                for entry in self._remote_match_candidates.setdefault(index, [])
            }
            self._remote_match_candidates[index].extend(
                entry for entry in matched if (entry.session_id, entry.entry_id) not in existing
            )

    def _handle_catalogue_batch(self, request_id: str, operation: str, payload: object) -> None:
        if request_id != self.remote_match_request_id or operation != "resolve_entries":
            return
        batch = self._remote_match_current
        if batch is not None and isinstance(payload, ArchiveLookupResult):
            self._record_lookup_result(batch, payload)

    @staticmethod
    def _select_exact_candidate(
        values: Sequence[str],
        candidates: Sequence[ArchiveEntryDto],
    ) -> ArchiveEntryDto | None:
        ranks = {
            value.replace("\\", "/").strip("/").casefold(): index
            for index, value in enumerate(values)
        }
        ranked = [
            (ranks.get(entry.path.replace("\\", "/").strip("/").casefold(), len(ranks)), entry)
            for entry in candidates
        ]
        if not ranked:
            return None
        best_rank = min(rank for rank, _entry in ranked)
        best = [entry for rank, entry in ranked if rank == best_rank]
        active = [entry for entry in best if entry.is_active_override]
        if len(active) == 1:
            return active[0]
        if len(best) == 1:
            return best[0]
        return None

    def _apply_remote_entry(self, item: ReplaceAssistantItem, entry: ArchiveEntryDto, reason: str) -> None:
        session = self.archive_catalogue_session
        compatibility_entry = ArchiveCatalogueService.compatibility_entry(entry)
        match_replace_assistant_item_to_archive_entry(
            item,
            compatibility_entry,
            match_reason=reason,
            archive_session_id=entry.session_id,
            archive_entry_id=entry.entry_id,
            archive_fingerprint=session.fingerprint if session is not None else "",
        )

    def _complete_lookup_phase(self) -> None:
        phase = self._remote_match_phase
        if phase is ArchiveLookupKind.EXACT_PATHS:
            unresolved: list[int] = []
            for index, values in self._remote_match_exact_values.items():
                item = self.items[index]
                if item.matched_original is not None:
                    continue
                candidates = self._remote_match_candidates.get(index, ())
                selected = None if index in self._remote_match_truncated else self._select_exact_candidate(values, candidates)
                if selected is not None:
                    self._apply_remote_entry(
                        item,
                        selected,
                        f"matched standalone archive relative path: {selected.path}",
                    )
                else:
                    if candidates or index in self._remote_match_truncated:
                        item.status = "unresolved"
                        item.status_detail = "ambiguous archive path match; Choose Archive Original."
                        item.warning = item.status_detail
                    unresolved.append(index)
            if unresolved:
                self.append_log("Resolving bounded basename archive candidates through the standalone catalogue.")
                self._begin_lookup_phase(ArchiveLookupKind.BASENAMES, tuple(unresolved))
                return
        elif phase is ArchiveLookupKind.BASENAMES:
            for index in self._remote_match_basename_values:
                item = self.items[index]
                if item.matched_original is not None:
                    continue
                candidates = {
                    (entry.session_id, entry.entry_id): entry
                    for entry in self._remote_match_candidates.get(index, ())
                }
                if index not in self._remote_match_truncated and len(candidates) == 1:
                    selected = next(iter(candidates.values()))
                    self._apply_remote_entry(item, selected, "unique standalone archive basename fallback")
                elif candidates or index in self._remote_match_truncated:
                    count_text = f"{len(candidates)}+" if index in self._remote_match_truncated else str(len(candidates))
                    item.status = "unresolved"
                    item.status_detail = f"ambiguous archive basename fallback ({count_text} matches); Choose Archive Original."
                    item.warning = item.status_detail
                elif not item.status_detail:
                    item.status = "unresolved"
                    item.status_detail = "Choose Archive Original."
        self._remote_match_phase = None
        self._remote_match_current = None
        self._remote_match_pending = []
        self._finalize_auto_match(
            refresh_preview=self._remote_match_refresh_preview,
            prompt_ambiguous=True,
        )
        self._update_controls()

    def _fail_remote_auto_match(self, message: str) -> None:
        self.remote_match_request_id = None
        self._remote_match_current = None
        self._remote_match_pending = []
        self._remote_match_phase = None
        self.preview_refresh_suspended = False
        self.append_log(f"ERROR: Archive auto-match failed: {message}")
        self.status_label.setText(f"Archive auto-match failed: {message}")
        self.status_message_requested.emit(f"Archive auto-match failed: {message}", True)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Error")
        self._refresh_queue_tree()
        self._update_controls()

    def _choose_catalogue_archive_original(self, item: ReplaceAssistantItem) -> bool:
        service = self.archive_catalogue_service
        session = self.archive_catalogue_session
        if service is None or session is None:
            return False
        dialog = RemoteArchiveOriginalDialog(
            service,
            session,
            initial_filter=item.source_path.stem,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.selected_entry is None:
            return False
        selected = dialog.selected_entry
        selected_session = service.session(selected.session_id) or session
        compatibility_entry = ArchiveCatalogueService.compatibility_entry(selected)
        match_replace_assistant_item_to_archive_entry(
            item,
            compatibility_entry,
            match_reason="manual standalone archive original",
            archive_session_id=selected.session_id,
            archive_entry_id=selected.entry_id,
            archive_fingerprint=selected_session.fingerprint,
        )
        return True

    def _start_catalogue_build(self, options: ReplaceAssistantBuildOptions) -> bool:
        service = self.archive_catalogue_service
        session = self.archive_catalogue_session
        if service is None or session is None:
            return False
        entry_indices: dict[int, list[int]] = {}
        for index, item in enumerate(self.items):
            matched = item.matched_original
            if matched is None or matched.archive_entry_id is None or matched.original_dds_path is not None:
                continue
            if matched.archive_fingerprint and matched.archive_fingerprint != session.fingerprint:
                self._handle_build_error("An archive original is stale; run Auto-Match again before building.")
                return True
            entry_indices.setdefault(int(matched.archive_entry_id), []).append(index)
        if not entry_indices:
            self._launch_build_worker(options, self.items, archive_entries=())
            return True
        self._remote_generation += 1
        self._remote_build_options = options
        self._remote_build_entry_indices = {key: tuple(value) for key, value in entry_indices.items()}
        self._remote_build_pending = list(entry_indices)
        self._remote_build_active_entry_id = None
        self.status_label.setText(
            f"Preparing {len(entry_indices):,} matched archive original(s) through the standalone worker..."
        )
        self.append_log("Preparing matched archive originals through the standalone worker before package build.")
        self._dispatch_next_build_prepare()
        return True

    def _dispatch_next_build_prepare(self) -> None:
        service = self.archive_catalogue_service
        session = self.archive_catalogue_session
        if service is None or session is None:
            self._fail_catalogue_build("The standalone archive session is unavailable.")
            return
        if not self._remote_build_pending:
            options = self._remote_build_options
            self._clear_remote_build_state()
            if options is not None:
                self._launch_build_worker(options, self.items, archive_entries=())
            return
        entry_id = self._remote_build_pending.pop(0)
        self._remote_build_active_entry_id = entry_id
        try:
            self.remote_build_request_id = service.prepare_entry(
                PrepareEntryRequest(session.session_id, entry_id),
                ui_generation=self._remote_generation,
            )
        except Exception as exc:
            self._fail_catalogue_build(str(exc))
        self._update_controls()

    def _complete_build_prepare(self, payload: object) -> None:
        entry_id = self._remote_build_active_entry_id
        self.remote_build_request_id = None
        if entry_id is None or not isinstance(payload, PrepareEntryResult) or payload.entry.entry_id != entry_id:
            self._fail_catalogue_build("The standalone worker returned the wrong prepared archive entry.")
            return
        prepared_path = Path(payload.prepared_path)
        for index in self._remote_build_entry_indices.get(entry_id, ()):
            matched = self.items[index].matched_original
            if matched is None:
                continue
            matched.original_dds_path = prepared_path
            matched.archive_session_id = payload.entry.session_id
        completed = len(self._remote_build_entry_indices) - len(self._remote_build_pending)
        self.progress_bar.setRange(0, len(self._remote_build_entry_indices))
        self.progress_bar.setValue(completed)
        self.progress_bar.setFormat(f"{completed} / {len(self._remote_build_entry_indices)}")
        self._remote_build_active_entry_id = None
        self._dispatch_next_build_prepare()

    def _fail_catalogue_build(self, message: str) -> None:
        self.remote_build_request_id = None
        self._clear_remote_build_state()
        self._handle_build_error(f"Could not prepare archive original: {message}")
        self._update_controls()

    def _clear_remote_build_state(self) -> None:
        self.remote_build_request_id = None
        self._remote_build_options = None
        self._remote_build_entry_indices = {}
        self._remote_build_pending = []
        self._remote_build_active_entry_id = None

    def _handle_catalogue_result(self, request_id: str, operation: str, payload: object) -> None:
        if request_id == self.remote_match_request_id and operation == "resolve_entries":
            batch = self._remote_match_current
            self.remote_match_request_id = None
            if batch is None or not isinstance(payload, ArchiveLookupResult):
                self._fail_remote_auto_match("The standalone worker returned an invalid lookup result.")
                return
            if payload.truncated and len(batch.item_indices) > 1:
                for index in batch.item_indices:
                    self._remote_match_candidates[index] = []
                midpoint = max(1, len(batch.item_indices) // 2)
                self._remote_match_pending[0:0] = [
                    _LookupBatch(batch.kind, batch.item_indices[:midpoint]),
                    _LookupBatch(batch.kind, batch.item_indices[midpoint:]),
                ]
            else:
                self._record_lookup_result(batch, payload)
                if payload.truncated:
                    self._remote_match_truncated.update(batch.item_indices)
            self._remote_match_current = None
            self._dispatch_next_lookup_batch()
            return
        if request_id == self.remote_build_request_id and operation == "prepare_entry":
            self._complete_build_prepare(payload)

    def _handle_catalogue_failure(self, request_id: str, error: object) -> None:
        message = str(getattr(error, "message", "") or error or "Archive worker request failed.")
        if request_id == self.remote_match_request_id:
            self._fail_remote_auto_match(message)
        elif request_id == self.remote_build_request_id:
            self._fail_catalogue_build(message)

    def _handle_catalogue_cancelled(self, request_id: str) -> None:
        if request_id == self.remote_match_request_id:
            self.remote_match_request_id = None
            self._remote_match_current = None
            self._remote_match_pending = []
            self._remote_match_phase = None
            self.preview_refresh_suspended = False
        elif request_id == self.remote_build_request_id:
            self._clear_remote_build_state()
        self._update_controls()

    def _cancel_all_catalogue_requests(self, *, clear: bool = False) -> None:
        service = self.archive_catalogue_service
        if service is not None:
            for request_id in (self.remote_match_request_id, self.remote_build_request_id):
                if request_id is not None:
                    service.cancel(request_id)
        if clear:
            self.remote_match_request_id = None
            self._remote_match_current = None
            self._remote_match_pending = []
            self._remote_match_phase = None
            self._clear_remote_build_state()


__all__ = [
    "REMOTE_LOOKUP_ITEM_BATCH",
    "REMOTE_LOOKUP_RESULT_LIMIT",
    "ReplaceAssistantArchiveCatalogueMixin",
]
