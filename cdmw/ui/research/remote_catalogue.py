"""Bounded standalone archive-catalogue integration for Research."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

from PySide6.QtCore import QTimer

from cdmw.domain.archives.catalogue import (
    ArchiveEntryDto,
    ArchiveLookupKind,
    ArchiveLookupRequest,
    ArchiveLookupResult,
    ArchivePage,
    ArchiveQueryHandle,
    ArchiveSessionHandle,
)
from cdmw.domain.archives.catalogue_operations import (
    ARCHIVE_BACKEND_MAXIMUM_PAGE_SIZE,
    FetchPageRequest,
    PrepareEntriesRequest,
    PrepareEntriesResult,
    PrepareEntryRequest,
    PrepareEntryResult,
)
from cdmw.domain.research.contracts import (
    RESEARCH_REFERENCE_SOURCE_EXTENSIONS,
    RESEARCH_TEXTURE_IMAGE_EXTENSIONS,
    RESEARCH_TEXTURE_SIDECAR_EXTENSIONS,
)
from cdmw.models import ArchiveEntry
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService


REMOTE_RESEARCH_VIEW_LIMIT = 4096
REMOTE_RESEARCH_ANALYSIS_LIMIT = 4096
REMOTE_RESEARCH_TEXT_LOOKUP_LIMIT = 1024
REMOTE_RESEARCH_TEXT_PREPARE_LIMIT = 512
REMOTE_RESEARCH_TEXT_FILE_LIMIT = 16 * 1024 * 1024
REMOTE_RESEARCH_TEXT_BYTE_LIMIT = 256 * 1024 * 1024
REMOTE_RESEARCH_COMPATIBILITY_ENTRY_LIMIT = (
    REMOTE_RESEARCH_VIEW_LIMIT + REMOTE_RESEARCH_ANALYSIS_LIMIT + REMOTE_RESEARCH_TEXT_PREPARE_LIMIT
)

RESEARCH_PREPARED_TEXT_EXTENSIONS = tuple(
    sorted(RESEARCH_TEXTURE_SIDECAR_EXTENSIONS | RESEARCH_REFERENCE_SOURCE_EXTENSIONS)
)
RESEARCH_ANALYSIS_EXTENSIONS = tuple(
    sorted(RESEARCH_TEXTURE_IMAGE_EXTENSIONS | set(RESEARCH_PREPARED_TEXT_EXTENSIONS))
)


class ResearchArchiveCatalogueMixin:
    """Feed existing Research workers bounded v2 candidates and prepared files."""

    def _initialize_research_archive_catalogue(
        self,
        service: ArchiveCatalogueService | None,
        get_archive_entries: Callable[[], Sequence[object]],
        get_filtered_archive_entries: Callable[[], Sequence[object]],
    ) -> None:
        self.archive_catalogue_service = service
        self.archive_catalogue_session: ArchiveSessionHandle | None = None
        self.archive_catalogue_query_handle: ArchiveQueryHandle | None = None
        self._remote_research_effective_session_id = ""
        self._remote_research_effective_query_id = ""
        self._legacy_get_archive_entries = get_archive_entries
        self._legacy_get_filtered_archive_entries = get_filtered_archive_entries
        self.get_archive_entries = self._research_archive_entries
        self.get_filtered_archive_entries = self._research_filtered_archive_entries
        self.remote_research_request_id: str | None = None
        self._remote_research_request_kind = ""
        self._remote_research_generation = 0
        self._remote_research_ready_key: tuple[str, str, int, str] | None = None
        self._remote_research_view_dtos: dict[int, ArchiveEntryDto] = {}
        self._remote_research_analysis_dtos: dict[int, ArchiveEntryDto] = {}
        self._remote_research_text_dtos: dict[int, ArchiveEntryDto] = {}
        self._remote_research_view_page_start = 0
        self._remote_research_prepared: dict[int, PrepareEntryResult] = {}
        self._remote_research_entries: tuple[ArchiveEntry, ...] = ()
        self._remote_research_view_entries: tuple[ArchiveEntry, ...] = ()
        self._remote_research_picker_entries: tuple[ArchiveEntry, ...] = ()
        self._remote_research_entry_ids: dict[object, int] = {}
        self._remote_research_pending_actions: set[str] = set()
        self._remote_research_notices: list[str] = []
        self._remote_research_preview_requests: dict[str, tuple[str, int, ArchiveEntry, int]] = {}
        self._pending_refresh_catalogue_context: tuple[str, str, int, str] | None = None
        self._pending_ui_constraint_catalogue_context: tuple[str, str, int, str] | None = None
        self._pending_reference_catalogue_context: tuple[str, str, int, str] | None = None
        if service is None:
            return
        service.batch_ready.connect(self._handle_research_catalogue_batch)
        service.result_ready.connect(self._handle_research_catalogue_result)
        service.progress.connect(self._handle_research_catalogue_progress)
        service.request_failed.connect(self._handle_research_catalogue_failure)
        service.request_cancelled.connect(self._handle_research_catalogue_cancelled)

    def set_archive_catalogue_session(self, session: ArchiveSessionHandle | None) -> None:
        self.set_archive_catalogue_context(session, None)

    def set_archive_catalogue_context(
        self,
        session: ArchiveSessionHandle | None,
        query_handle: ArchiveQueryHandle | None,
    ) -> None:
        new_key = (
            (
                session.session_id,
                query_handle.query_id if query_handle is not None else "",
                query_handle.generation if query_handle is not None else -1,
                session.fingerprint,
            )
            if session is not None
            else None
        )
        current_key = self._research_catalogue_context_key()
        self.archive_catalogue_session = session
        self.archive_catalogue_query_handle = query_handle
        if new_key == current_key:
            return
        self._cancel_research_catalogue_requests(clear=True)
        self._remote_research_ready_key = None
        self._remote_research_effective_session_id = session.session_id if session is not None else ""
        self._remote_research_effective_query_id = query_handle.query_id if query_handle is not None else ""
        self._remote_research_view_dtos = {}
        self._remote_research_analysis_dtos = {}
        self._remote_research_text_dtos = {}
        self._remote_research_prepared = {}
        self._remote_research_view_page_start = 0
        self._remote_research_entries = ()
        self._remote_research_view_entries = ()
        self._remote_research_picker_entries = ()
        self._remote_research_entry_ids = {}
        self._remote_research_notices = []
        for button_name in (
            "refresh_button",
            "ui_constraint_refresh_button",
            "reference_resolve_button",
        ):
            button = getattr(self, button_name, None)
            if button is not None:
                button.setEnabled(True)
        self.archive_picker_preview_request_id = int(getattr(self, "archive_picker_preview_request_id", 0) or 0) + 1
        self.unknown_preview_request_id = int(getattr(self, "unknown_preview_request_id", 0) or 0) + 1
        for worker_name in (
            "refresh_worker",
            "ui_constraint_worker",
            "resolve_worker",
            "archive_picker_preview_worker",
            "unknown_preview_worker",
        ):
            stop = getattr(getattr(self, worker_name, None), "stop", None)
            if callable(stop):
                stop()
        for timer_name in (
            "_refresh_population_timer",
            "_unknown_population_timer",
            "_archive_picker_population_timer",
        ):
            stop = getattr(getattr(self, timer_name, None), "stop", None)
            if callable(stop):
                stop()
        self.mark_archive_picker_dirty()

    def _research_catalogue_context_key(self) -> tuple[str, str, int, str] | None:
        session = self.archive_catalogue_session
        if session is None:
            return None
        handle = self.archive_catalogue_query_handle
        return (
            session.session_id,
            handle.query_id if handle is not None else "",
            handle.generation if handle is not None else -1,
            session.fingerprint,
        )

    def _research_catalogue_ready(self) -> bool:
        key = self._research_catalogue_context_key()
        return key is not None and key == self._remote_research_ready_key

    def _research_archive_entries(self) -> Sequence[object]:
        if self.archive_catalogue_session is not None:
            return self._remote_research_entries
        return self._legacy_get_archive_entries()

    def _research_filtered_archive_entries(self) -> Sequence[object]:
        if self.archive_catalogue_session is not None:
            return self._remote_research_view_entries
        return self._legacy_get_filtered_archive_entries()

    def _research_archive_picker_entry_sources(self) -> tuple[Sequence[object], Sequence[object]]:
        if self.archive_catalogue_session is not None:
            return self._remote_research_picker_entries, self._remote_research_picker_entries
        return self._legacy_get_filtered_archive_entries(), self._legacy_get_archive_entries()

    def _prepare_catalogue_research_refresh_if_needed(self, action: str) -> bool:
        service = self.archive_catalogue_service
        if service is None or self.archive_catalogue_session is None:
            return False
        if self._research_catalogue_ready():
            return False
        self._remote_research_pending_actions.add(str(action or "refresh"))
        self._set_research_catalogue_action_pending(action)
        if self.remote_research_request_id is not None:
            return True
        self._remote_research_generation += 1
        self._remote_research_view_dtos = {}
        self._remote_research_analysis_dtos = {}
        self._remote_research_text_dtos = {}
        self._remote_research_view_page_start = 0
        self._remote_research_prepared = {}
        self._remote_research_notices = []
        self._start_research_catalogue_view_page(0)
        return True

    def _set_research_catalogue_action_pending(self, action: str) -> None:
        message = "Requesting bounded Research candidates from the archive worker..."
        if action == "refresh":
            self.refresh_button.setEnabled(False)
            self.refresh_progress.setRange(0, 0)
            self.refresh_status_label.setText(message)
        elif action == "ui_constraints":
            self.ui_constraint_refresh_button.setEnabled(False)
            self.ui_constraint_status_label.setText(message)
        elif action == "references":
            self.reference_resolve_button.setEnabled(False)
            self.reference_status_label.setText(message)
        elif action == "archive_picker":
            self.archive_picker_status_label.setText(message)
        self.status_message_requested.emit(message, False)

    def _start_research_catalogue_view_page(self, page_start: int) -> None:
        service = self.archive_catalogue_service
        session = self.archive_catalogue_session
        query_id = self._remote_research_effective_query_id
        if service is None or session is None or not query_id:
            self._fail_research_catalogue_refresh("The standalone archive query is not ready for Research.")
            return
        remaining = REMOTE_RESEARCH_VIEW_LIMIT - len(self._remote_research_view_dtos)
        if remaining <= 0:
            self._start_research_analysis_lookup()
            return
        try:
            request_id = service.fetch_page(
                FetchPageRequest(
                    query_id=query_id,
                    page_start=page_start,
                    page_size=min(ARCHIVE_BACKEND_MAXIMUM_PAGE_SIZE, remaining),
                ),
                ui_generation=self._remote_research_generation,
            )
        except Exception as exc:
            self._fail_research_catalogue_refresh(str(exc))
            return
        self.remote_research_request_id = request_id
        self._remote_research_request_kind = "view_page"
        self._remote_research_view_page_start = page_start

    def _complete_research_view_page(self, result: ArchivePage) -> None:
        if result.page_start != self._remote_research_view_page_start:
            self._fail_research_catalogue_refresh("The archive worker returned stale Research page data.")
            return
        self._remote_research_effective_session_id = result.session_id
        self._remote_research_effective_query_id = result.query_id
        for entry in result.rows:
            self._remote_research_view_dtos.setdefault(entry.entry_id, entry)
        next_start = result.page_start + len(result.rows)
        bounded_total = min(result.total_matches, REMOTE_RESEARCH_VIEW_LIMIT)
        self.remote_research_request_id = None
        self._remote_research_request_kind = ""
        if next_start < bounded_total:
            if not result.rows:
                self._fail_research_catalogue_refresh("The archive worker returned an incomplete Research page sequence.")
                return
            self._start_research_catalogue_view_page(next_start)
            return
        if result.total_matches > len(self._remote_research_view_dtos):
            self._remote_research_notices.append(
                f"current-view Research candidates were capped at {len(self._remote_research_view_dtos):,} "
                f"of {result.total_matches:,} matches"
            )
        self._start_research_analysis_lookup()

    def _start_research_analysis_lookup(self) -> None:
        service = self.archive_catalogue_service
        session = self.archive_catalogue_session
        session_id = self._remote_research_effective_session_id
        query_id = self._remote_research_effective_query_id
        if service is None or session is None or not session_id or not query_id:
            self._fail_research_catalogue_refresh("The standalone archive query changed during Research preparation.")
            return
        try:
            request_id = service.resolve_entries(
                ArchiveLookupRequest(
                    session_id=session_id,
                    kind=ArchiveLookupKind.EXTENSIONS,
                    values=RESEARCH_ANALYSIS_EXTENSIONS,
                    limit=REMOTE_RESEARCH_ANALYSIS_LIMIT,
                    query_id=query_id,
                ),
                ui_generation=self._remote_research_generation,
            )
        except Exception as exc:
            self._fail_research_catalogue_refresh(str(exc))
            return
        self.remote_research_request_id = request_id
        self._remote_research_request_kind = "analysis_lookup"

    def _record_research_analysis_lookup(self, result: ArchiveLookupResult) -> None:
        for entry in result.entries:
            self._remote_research_analysis_dtos.setdefault(entry.entry_id, entry)

    def _complete_research_analysis_lookup(self, result: ArchiveLookupResult) -> None:
        self._remote_research_effective_session_id = result.session_id
        self._record_research_analysis_lookup(result)
        if result.truncated:
            self._remote_research_notices.append(
                f"current-query Research analysis candidates were capped at "
                f"{len(self._remote_research_analysis_dtos):,} of {result.total_matches:,} matches"
            )
        self.remote_research_request_id = None
        self._remote_research_request_kind = ""
        self._start_research_text_lookup()

    def _start_research_text_lookup(self) -> None:
        service = self.archive_catalogue_service
        session_id = self._remote_research_effective_session_id
        if service is None or self.archive_catalogue_session is None or not session_id:
            self._fail_research_catalogue_refresh("The standalone archive session is unavailable.")
            return
        try:
            request_id = service.resolve_entries(
                ArchiveLookupRequest(
                    session_id=session_id,
                    kind=ArchiveLookupKind.EXTENSIONS,
                    values=RESEARCH_PREPARED_TEXT_EXTENSIONS,
                    limit=REMOTE_RESEARCH_TEXT_LOOKUP_LIMIT,
                ),
                ui_generation=self._remote_research_generation,
            )
        except Exception as exc:
            self._fail_research_catalogue_refresh(str(exc))
            return
        self.remote_research_request_id = request_id
        self._remote_research_request_kind = "text_lookup"

    def _record_research_text_lookup(self, result: ArchiveLookupResult) -> None:
        for entry in result.entries:
            self._remote_research_text_dtos.setdefault(entry.entry_id, entry)

    def _complete_research_text_lookup(self, result: ArchiveLookupResult) -> None:
        self._remote_research_effective_session_id = result.session_id
        self._record_research_text_lookup(result)
        if result.truncated:
            self._remote_research_notices.append(
                f"Research sidecar/reference sources were capped at {len(self._remote_research_text_dtos):,} "
                f"of {result.total_matches:,} matches"
            )
        self.remote_research_request_id = None
        self._remote_research_request_kind = ""
        self._start_research_text_preparation()

    def _start_research_text_preparation(self) -> None:
        service = self.archive_catalogue_service
        session_id = self._remote_research_effective_session_id
        if service is None or self.archive_catalogue_session is None or not session_id:
            self._fail_research_catalogue_refresh("The standalone archive session changed during Research preparation.")
            return
        ordered: dict[int, ArchiveEntryDto] = dict(self._remote_research_text_dtos)
        for source in (self._remote_research_analysis_dtos, self._remote_research_view_dtos):
            for entry_id, entry in source.items():
                if entry.extension.casefold() in RESEARCH_PREPARED_TEXT_EXTENSIONS:
                    ordered.setdefault(entry_id, entry)
        selected_ids: list[int] = []
        selected_bytes = 0
        skipped_oversized = 0
        for entry in ordered.values():
            size = max(0, int(entry.original_size))
            if size > REMOTE_RESEARCH_TEXT_FILE_LIMIT:
                skipped_oversized += 1
                continue
            if len(selected_ids) >= REMOTE_RESEARCH_TEXT_PREPARE_LIMIT:
                break
            if selected_bytes + size > REMOTE_RESEARCH_TEXT_BYTE_LIMIT:
                break
            selected_ids.append(entry.entry_id)
            selected_bytes += size
        if skipped_oversized:
            self._remote_research_notices.append(
                f"{skipped_oversized:,} oversized sidecar/reference candidate(s) were excluded"
            )
        if len(selected_ids) < len(ordered):
            self._remote_research_notices.append(
                f"prepared sidecar/reference sources were bounded to {len(selected_ids):,} file(s) "
                f"and {selected_bytes / (1024 * 1024):.1f} MiB"
            )
        if not selected_ids:
            self._publish_research_catalogue_candidates()
            return
        try:
            request_id = service.prepare_entries(
                PrepareEntriesRequest(session_id, tuple(selected_ids)),
                ui_generation=self._remote_research_generation,
            )
        except Exception as exc:
            self._fail_research_catalogue_refresh(str(exc))
            return
        self.remote_research_request_id = request_id
        self._remote_research_request_kind = "prepare"

    def _record_research_preparation(self, result: PrepareEntriesResult) -> None:
        self._remote_research_effective_session_id = result.session_id
        for item in result.items:
            self._remote_research_prepared.setdefault(item.entry.entry_id, item)

    def _publish_research_catalogue_candidates(self) -> None:
        service = self.archive_catalogue_service
        key = self._research_catalogue_context_key()
        if service is None or key is None:
            self._fail_research_catalogue_refresh("The standalone archive session changed during Research preparation.")
            return
        entries_by_id: dict[int, ArchiveEntry] = {}

        def materialize(dto: ArchiveEntryDto) -> ArchiveEntry:
            existing = entries_by_id.get(dto.entry_id)
            if existing is not None:
                return existing
            prepared = self._remote_research_prepared.get(dto.entry_id)
            entry = service.compatibility_entry(dto)
            if prepared is not None:
                entry.prepared_path = Path(prepared.prepared_path)
                entry.prepared_sha256 = prepared.sha256
            entries_by_id[dto.entry_id] = entry
            return entry

        picker_entries = tuple(materialize(dto) for dto in self._remote_research_view_dtos.values())
        view_entries = tuple(
            materialize(dto)
            for dto in self._remote_research_analysis_dtos.values()
            if (
                dto.extension.casefold() not in RESEARCH_PREPARED_TEXT_EXTENSIONS
                or dto.entry_id in self._remote_research_prepared
            )
        )
        full_entries_list = list(view_entries)
        seen_ids = set(self._remote_research_analysis_dtos)
        for dto in self._remote_research_text_dtos.values():
            if dto.entry_id in seen_ids:
                continue
            if dto.entry_id not in self._remote_research_prepared:
                continue
            entry = materialize(dto)
            full_entries_list.append(entry)
            seen_ids.add(dto.entry_id)
        self._remote_research_picker_entries = picker_entries
        self._remote_research_view_entries = view_entries
        self._remote_research_entries = tuple(full_entries_list)
        self._remote_research_entry_ids = {
            entry.identity: entry_id
            for entry_id, entry in entries_by_id.items()
        }
        self._remote_research_ready_key = key
        self.remote_research_request_id = None
        self._remote_research_request_kind = ""
        actions = tuple(self._remote_research_pending_actions)
        self._remote_research_pending_actions.clear()
        dispatch = {
            "refresh": self.refresh_research,
            "ui_constraints": self.refresh_ui_constraints,
            "references": self.resolve_references,
            "archive_picker": self.refresh_archive_picker,
        }
        for action in ("refresh", "ui_constraints", "references", "archive_picker"):
            callback = dispatch.get(action)
            if action in actions and callback is not None:
                QTimer.singleShot(0, callback)

    def _research_catalogue_status_suffix(self) -> str:
        if not self._research_catalogue_ready():
            return ""
        summary = (
            f"Standalone v2 supplied {len(self._remote_research_entries):,} bounded analysis candidate(s) "
            f"and {len(self._remote_research_picker_entries):,} current-view picker row(s)."
        )
        if self._remote_research_notices:
            summary = f"{summary} {'; '.join(self._remote_research_notices)}."
        return summary

    def _start_catalogue_research_preview(
        self,
        channel: str,
        request_id: int,
        entry: ArchiveEntry | None,
    ) -> bool:
        service = self.archive_catalogue_service
        session_id = self._remote_research_effective_session_id
        if (
            service is None
            or self.archive_catalogue_session is None
            or not session_id
            or not isinstance(entry, ArchiveEntry)
        ):
            return False
        if entry.prepared_path is not None:
            return False
        entry_id = self._remote_research_entry_ids.get(entry.identity)
        if entry_id is None:
            self._report_research_preview_error(channel, request_id, "The selected file is outside the bounded Research candidate set.")
            return True
        for pending_id, pending in tuple(self._remote_research_preview_requests.items()):
            if pending[0] == channel:
                service.cancel(pending_id)
                self._remote_research_preview_requests.pop(pending_id, None)
        self._remote_research_generation += 1
        try:
            catalogue_request_id = service.prepare_entry(
                PrepareEntryRequest(session_id, entry_id, include_content_analysis=True),
                ui_generation=self._remote_research_generation,
            )
        except Exception as exc:
            self._report_research_preview_error(channel, request_id, str(exc))
            return True
        self._remote_research_preview_requests[catalogue_request_id] = (channel, request_id, entry, entry_id)
        return True

    def _complete_research_preview(self, catalogue_request_id: str, result: PrepareEntryResult) -> None:
        pending = self._remote_research_preview_requests.pop(catalogue_request_id, None)
        if pending is None:
            return
        channel, request_id, entry, entry_id = pending
        self._remote_research_effective_session_id = result.entry.session_id
        if result.entry.entry_id != entry_id:
            self._report_research_preview_error(channel, request_id, "The archive worker prepared a different Research entry.")
            return
        entry.prepared_path = Path(result.prepared_path)
        entry.prepared_sha256 = result.sha256
        entry.content_analysis_json_path = (
            Path(result.content_analysis_json_path) if result.content_analysis_json_path else None
        )
        entry.content_analysis_text_path = (
            Path(result.content_analysis_text_path) if result.content_analysis_text_path else None
        )
        entry.content_analysis_version = str(result.content_analysis_version or "")
        if channel == "archive_picker":
            if request_id == self.archive_picker_preview_request_id:
                self._start_archive_picker_preview_worker(request_id, entry)
        elif request_id == self.unknown_preview_request_id:
            self._start_unknown_preview_worker(request_id, entry)

    def _report_research_preview_error(self, channel: str, request_id: int, message: str) -> None:
        if channel == "archive_picker":
            self._handle_archive_picker_preview_error(request_id, message)
        else:
            self._handle_unknown_preview_error(request_id, message)

    def _handle_research_catalogue_batch(self, request_id: str, operation: str, payload: object) -> None:
        if request_id == self.remote_research_request_id:
            if operation == "resolve_entries" and isinstance(payload, ArchiveLookupResult):
                if self._remote_research_request_kind == "analysis_lookup":
                    self._record_research_analysis_lookup(payload)
                elif self._remote_research_request_kind == "text_lookup":
                    self._record_research_text_lookup(payload)
            elif operation == "prepare_entry" and isinstance(payload, PrepareEntriesResult):
                self._record_research_preparation(payload)

    def _handle_research_catalogue_result(self, request_id: str, operation: str, payload: object) -> None:
        if request_id in self._remote_research_preview_requests:
            if operation == "prepare_entry" and isinstance(payload, PrepareEntryResult):
                self._complete_research_preview(request_id, payload)
            return
        if request_id != self.remote_research_request_id:
            return
        if operation == "fetch_page" and isinstance(payload, ArchivePage):
            self._complete_research_view_page(payload)
        elif operation == "resolve_entries" and isinstance(payload, ArchiveLookupResult):
            if self._remote_research_request_kind == "analysis_lookup":
                self._complete_research_analysis_lookup(payload)
            elif self._remote_research_request_kind == "text_lookup":
                self._complete_research_text_lookup(payload)
        elif operation == "prepare_entry" and isinstance(payload, PrepareEntriesResult):
            self._record_research_preparation(payload)
            self._publish_research_catalogue_candidates()

    def _handle_research_catalogue_progress(self, request_id: str, update: object) -> None:
        if request_id != self.remote_research_request_id:
            return
        phase = str(getattr(update, "phase", "Preparing Research candidates") or "Preparing Research candidates")
        current = int(getattr(update, "completed", 0) or 0)
        total = int(getattr(update, "total", 0) or 0)
        detail = f"{phase.replace('_', ' ').title()}: {current:,} / {total:,}" if total > 0 else phase
        self.status_message_requested.emit(detail, False)

    def _handle_research_catalogue_failure(self, request_id: str, error: object) -> None:
        if request_id in self._remote_research_preview_requests:
            channel, preview_request_id, _entry, _entry_id = self._remote_research_preview_requests.pop(request_id)
            self._report_research_preview_error(
                channel,
                preview_request_id,
                str(getattr(error, "message", "") or error or "Archive worker request failed."),
            )
            return
        if request_id == self.remote_research_request_id:
            self._fail_research_catalogue_refresh(
                str(getattr(error, "message", "") or error or "Archive worker request failed.")
            )

    def _handle_research_catalogue_cancelled(self, request_id: str) -> None:
        self._remote_research_preview_requests.pop(request_id, None)
        if request_id == self.remote_research_request_id:
            self.remote_research_request_id = None
            self._remote_research_request_kind = ""

    def _fail_research_catalogue_refresh(self, message: str) -> None:
        actions = set(self._remote_research_pending_actions)
        self.remote_research_request_id = None
        self._remote_research_request_kind = ""
        self._remote_research_pending_actions.clear()
        self.refresh_button.setEnabled(True)
        self.ui_constraint_refresh_button.setEnabled(True)
        self.reference_resolve_button.setEnabled(True)
        labels = {
            "refresh": self.refresh_status_label,
            "ui_constraints": self.ui_constraint_status_label,
            "references": self.reference_status_label,
            "archive_picker": self.archive_picker_status_label,
        }
        for action in actions or {"refresh"}:
            label = labels.get(action)
            if label is not None:
                label.setText(message)
        self.refresh_progress.setRange(0, 1)
        self.status_message_requested.emit(message, True)

    def _cancel_research_catalogue_requests(self, *, clear: bool = False) -> None:
        service = self.archive_catalogue_service
        if service is not None:
            if self.remote_research_request_id is not None:
                service.cancel(self.remote_research_request_id)
            for request_id in tuple(self._remote_research_preview_requests):
                service.cancel(request_id)
        if clear:
            self.remote_research_request_id = None
            self._remote_research_request_kind = ""
            self._remote_research_preview_requests.clear()
            self._remote_research_pending_actions.clear()


__all__ = [
    "REMOTE_RESEARCH_ANALYSIS_LIMIT",
    "REMOTE_RESEARCH_COMPATIBILITY_ENTRY_LIMIT",
    "REMOTE_RESEARCH_TEXT_BYTE_LIMIT",
    "REMOTE_RESEARCH_TEXT_FILE_LIMIT",
    "REMOTE_RESEARCH_TEXT_LOOKUP_LIMIT",
    "REMOTE_RESEARCH_TEXT_PREPARE_LIMIT",
    "REMOTE_RESEARCH_VIEW_LIMIT",
    "ResearchArchiveCatalogueMixin",
]
