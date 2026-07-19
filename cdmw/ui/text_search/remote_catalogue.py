"""Bounded standalone-catalogue integration for Text Search."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Sequence

from cdmw.domain.archives.catalogue import ArchiveSessionHandle
from cdmw.domain.archives.catalogue_operations import (
    ArchiveExportCollisionPolicy,
    ArchiveExportRequest,
    ArchiveExportResult,
    ArchiveExportSelectionKind,
    ArchiveTextSearchBatch,
    ArchiveTextSearchRequest,
    PrepareEntryRequest,
    PrepareEntryResult,
)
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.services.text_search_service import (
    TextSearchResult,
    TextSearchRunStats,
    normalize_text_search_extensions,
)


REMOTE_TEXT_SEARCH_MATCH_LIMIT = 20_000


class TextSearchArchiveCatalogueMixin:
    """Route v2 archive operations without materializing the archive catalogue."""

    def _initialize_archive_catalogue(
        self,
        service: ArchiveCatalogueService | None,
    ) -> None:
        self.archive_catalogue_service = service
        self.archive_catalogue_session: ArchiveSessionHandle | None = None
        self.remote_search_request_id: str | None = None
        self.remote_preview_request_id: str | None = None
        self.remote_export_request_id: str | None = None
        self._remote_search_generation = 0
        self._remote_preview_generation = 0
        self._remote_export_generation = 0
        self._remote_export_label = ""
        self._remote_search_results: dict[int, TextSearchResult] = {}
        self._remote_search_match_keys: set[tuple[object, ...]] = set()
        if service is None:
            return
        service.batch_ready.connect(self._handle_catalogue_batch)
        service.result_ready.connect(self._handle_catalogue_result)
        service.progress.connect(self._handle_catalogue_progress)
        service.request_failed.connect(self._handle_catalogue_failure)
        service.request_cancelled.connect(self._handle_catalogue_cancelled)

    def set_archive_catalogue_session(self, session: ArchiveSessionHandle | None) -> None:
        previous = self.archive_catalogue_session
        if previous is not None and (session is None or previous.session_id != session.session_id):
            self._cancel_all_catalogue_requests(clear=True)
        self.archive_catalogue_session = session
        if session is None:
            return
        self.archive_entries = []
        self.archive_package_root_text = session.package_root.strip()
        if self.source_combo.currentData() == "archive" and not self.search_results:
            self.results_summary_label.setText(
                f"Archive source ready: {session.entry_count:,} worker-catalogued entry(s) available for text search."
            )

    def _catalogue_archive_ready(self) -> bool:
        return self.archive_catalogue_service is not None and self.archive_catalogue_session is not None

    def _catalogue_request_busy(self) -> bool:
        return self.remote_search_request_id is not None or self.remote_export_request_id is not None

    def _catalogue_session_for_result(self, session_id: str) -> ArchiveSessionHandle | None:
        current = self.archive_catalogue_session
        service = self.archive_catalogue_service
        if current is None or service is None:
            return None
        if current.session_id == session_id:
            return current
        candidate = service.session(session_id)
        if candidate is None or candidate.fingerprint != current.fingerprint:
            return None
        return candidate

    def _start_catalogue_text_search(
        self,
        request_generation: int,
        *,
        query: str,
        extension_text: str,
        path_filter: str,
        case_sensitive: bool,
        regex_enabled: bool,
    ) -> bool:
        service = self.archive_catalogue_service
        session = self.archive_catalogue_session
        if service is None or session is None:
            return False
        self._remote_search_generation = request_generation
        self._remote_search_results = {}
        self._remote_search_match_keys = set()
        try:
            request_id = service.text_search(
                ArchiveTextSearchRequest(
                    session_id=session.session_id,
                    query=query,
                    use_regular_expression=regex_enabled,
                    case_sensitive=case_sensitive,
                    path_filter=path_filter or None,
                    extensions=normalize_text_search_extensions(extension_text),
                    maximum_matches=REMOTE_TEXT_SEARCH_MATCH_LIMIT,
                ),
                ui_generation=request_generation,
            )
        except Exception as exc:
            self._handle_search_error(request_generation, str(exc))
            return True
        self.remote_search_request_id = request_id
        self._update_controls()
        self.append_log("Starting worker-side archive text search.")
        self.status_message_requested.emit("Starting worker-side archive text search...", False)
        return True

    def _start_catalogue_preview(self, request_generation: int, result: TextSearchResult) -> bool:
        service = self.archive_catalogue_service
        session = self.archive_catalogue_session
        if (
            service is None
            or session is None
            or result.archive_entry_id is None
            or not result.archive_session_id
        ):
            return False
        self._cancel_catalogue_preview(clear=True)
        result_session = self._catalogue_session_for_result(result.archive_session_id)
        if result_session is None:
            self._handle_preview_error(request_generation, "The archive session changed; run the text search again.")
            return True
        self._remote_preview_generation = request_generation
        try:
            self.remote_preview_request_id = service.prepare_entry(
                PrepareEntryRequest(result_session.session_id, result.archive_entry_id),
                ui_generation=request_generation,
            )
        except Exception as exc:
            self._handle_preview_error(request_generation, str(exc))
        return True

    def _start_catalogue_export(
        self,
        request_generation: int,
        results: Sequence[TextSearchResult],
        output_root: Path,
        *,
        label: str,
    ) -> bool:
        if not results or not any(result.archive_entry_id is not None for result in results):
            return False
        service = self.archive_catalogue_service
        session = self.archive_catalogue_session
        if service is None or session is None:
            self._handle_export_error(request_generation, "The standalone archive session is unavailable.")
            return True
        result_session_ids = {result.archive_session_id for result in results}
        result_session = (
            self._catalogue_session_for_result(next(iter(result_session_ids)))
            if len(result_session_ids) == 1
            else None
        )
        if result_session is None or any(
            result.source_kind != "archive"
            or result.archive_entry_id is None
            or result.archive_session_id != result_session.session_id
            for result in results
        ):
            self._handle_export_error(request_generation, "The archive results are stale or belong to mixed sessions.")
            return True
        entry_ids = tuple(dict.fromkeys(int(result.archive_entry_id) for result in results if result.archive_entry_id is not None))
        self._remote_export_generation = request_generation
        self._remote_export_label = label
        try:
            self.remote_export_request_id = service.export(
                ArchiveExportRequest(
                    session_id=result_session.session_id,
                    selection_kind=ArchiveExportSelectionKind.ENTRY_IDS,
                    destination=str(output_root),
                    entry_ids=entry_ids,
                    collision_policy=ArchiveExportCollisionPolicy.OVERWRITE,
                    write_manifest=True,
                ),
                ui_generation=request_generation,
            )
        except Exception as exc:
            self._handle_export_error(request_generation, str(exc))
            return True
        self.search_progress_label.setText(f"Preparing to export {len(entry_ids):,} matched file(s)...")
        self.search_progress_bar.setRange(0, max(1, len(entry_ids)))
        self.search_progress_bar.setValue(0)
        self.search_progress_bar.setFormat(f"0 / {len(entry_ids):,}")
        self._update_controls()
        self.status_message_requested.emit("Starting worker-side text result export...", False)
        return True

    def _handle_catalogue_batch(self, request_id: str, operation: str, payload: object) -> None:
        if request_id != self.remote_search_request_id or operation != "text_search":
            return
        if not isinstance(payload, ArchiveTextSearchBatch):
            return
        self._append_catalogue_search_matches(payload)
        self.search_progress_label.setText(
            f"Worker search: {payload.files_scanned:,} candidate file(s), "
            f"{len(self._remote_search_results):,} matching file(s)."
        )

    def _append_catalogue_search_matches(self, batch: ArchiveTextSearchBatch) -> None:
        for match in batch.matches:
            key = (match.entry_id, match.line, match.column, match.length, match.context)
            if key in self._remote_search_match_keys:
                continue
            self._remote_search_match_keys.add(key)
            result = self._remote_search_results.get(match.entry_id)
            if result is None:
                normalized_path = match.path.replace("\\", "/")
                result = TextSearchResult(
                    source_kind="archive",
                    relative_path=normalized_path,
                    extension=PurePosixPath(normalized_path).suffix.lower(),
                    match_count=1,
                    snippet=match.context.strip(),
                    package_label=match.package,
                    archive_session_id=batch.session_id,
                    archive_entry_id=match.entry_id,
                )
                self._remote_search_results[match.entry_id] = result
            else:
                result.match_count += 1

    def _handle_catalogue_result(self, request_id: str, operation: str, payload: object) -> None:
        if request_id == self.remote_search_request_id and operation == "text_search":
            self._complete_catalogue_search(payload)
            return
        if request_id == self.remote_preview_request_id and operation == "prepare_entry":
            self._complete_catalogue_preview(payload)
            return
        if request_id == self.remote_export_request_id and operation == "export":
            self._complete_catalogue_export(payload)

    def _complete_catalogue_search(self, payload: object) -> None:
        generation = self._remote_search_generation
        self.remote_search_request_id = None
        if generation != self.search_request_id or not isinstance(payload, ArchiveTextSearchBatch):
            self._update_controls()
            return
        self._append_catalogue_search_matches(payload)
        for warning in payload.warnings:
            self.append_log(f"Warning: {warning}")
        if payload.limit_reached:
            self.append_log(
                f"Search stopped at the bounded {REMOTE_TEXT_SEARCH_MATCH_LIMIT:,}-match limit; narrow the query for more detail."
            )
        read_errors = sum(
            warning.startswith("Could not decode ") or warning.startswith("Skipped oversized ")
            for warning in payload.warnings
        )
        stats = TextSearchRunStats(
            source_kind="archive",
            candidate_count=payload.files_scanned,
            searched_count=max(0, payload.files_scanned - read_errors),
            skipped_read_error_count=read_errors,
        )
        self._handle_search_complete(
            generation,
            {"results": list(self._remote_search_results.values()), "stats": stats},
        )
        self._update_controls()

    def _complete_catalogue_preview(self, payload: object) -> None:
        generation = self._remote_preview_generation
        self.remote_preview_request_id = None
        if generation != self.preview_request_id or not isinstance(payload, PrepareEntryResult):
            return
        result = self.current_preview_result
        if result is None or result.archive_entry_id != payload.entry.entry_id:
            return
        self._start_preview_decode_worker(
            generation,
            result,
            prepared_archive_path=Path(payload.prepared_path),
            prepared_archive_note=str(payload.note or ""),
        )

    def _complete_catalogue_export(self, payload: object) -> None:
        generation = self._remote_export_generation
        label = self._remote_export_label
        self.remote_export_request_id = None
        if generation != self.export_request_id or not isinstance(payload, ArchiveExportResult):
            self._update_controls()
            return
        if payload.cancelled:
            self._handle_export_cancelled(generation, "Text export stopped by user.")
        else:
            if payload.manifest_path:
                self.append_log(f"Export manifest: {payload.manifest_path}")
            for item in payload.items:
                if item.status == "failed":
                    self.append_log(f"FAIL {item.source_path}: {item.message or 'export failed'}")
            self._handle_export_complete(
                generation,
                {
                    "exported": payload.exported,
                    "renamed": 0,
                    "skipped": payload.skipped,
                    "failed": payload.failed,
                },
                label,
            )
        self._update_controls()

    def _handle_catalogue_progress(self, request_id: str, update: object) -> None:
        completed = int(getattr(update, "completed", 0) or 0)
        total = int(getattr(update, "total", 0) or 0)
        phase = str(getattr(update, "phase", "Working") or "Working").replace("_", " ").title()
        current_item = str(getattr(update, "current_item", "") or "")
        detail = f"{phase}: {current_item}" if current_item else phase
        if request_id == self.remote_search_request_id:
            self._handle_progress(self._remote_search_generation, completed, total, detail)
        elif request_id == self.remote_export_request_id:
            self._handle_export_progress(self._remote_export_generation, completed, total, detail)

    def _handle_catalogue_failure(self, request_id: str, error: object) -> None:
        message = str(getattr(error, "message", "") or error or "Archive worker request failed.")
        if request_id == self.remote_search_request_id:
            generation = self._remote_search_generation
            self.remote_search_request_id = None
            self._handle_search_error(generation, message)
        elif request_id == self.remote_preview_request_id:
            generation = self._remote_preview_generation
            self.remote_preview_request_id = None
            self._handle_preview_error(generation, message)
        elif request_id == self.remote_export_request_id:
            generation = self._remote_export_generation
            self.remote_export_request_id = None
            self._handle_export_error(generation, message)
        self._update_controls()

    def _handle_catalogue_cancelled(self, request_id: str) -> None:
        if request_id == self.remote_search_request_id:
            generation = self._remote_search_generation
            self.remote_search_request_id = None
            self._handle_search_cancelled(generation, "Text search stopped by user.")
        elif request_id == self.remote_preview_request_id:
            self.remote_preview_request_id = None
        elif request_id == self.remote_export_request_id:
            generation = self._remote_export_generation
            self.remote_export_request_id = None
            self._handle_export_cancelled(generation, "Text export stopped by user.")
        self._update_controls()

    def _cancel_catalogue_preview(self, *, clear: bool = False) -> None:
        request_id = self.remote_preview_request_id
        if request_id is not None and self.archive_catalogue_service is not None:
            self.archive_catalogue_service.cancel(request_id)
        if clear:
            self.remote_preview_request_id = None

    def _cancel_all_catalogue_requests(self, *, clear: bool = False) -> None:
        service = self.archive_catalogue_service
        if service is not None:
            for request_id in (
                self.remote_search_request_id,
                self.remote_preview_request_id,
                self.remote_export_request_id,
            ):
                if request_id is not None:
                    service.cancel(request_id)
        if clear:
            self.remote_search_request_id = None
            self.remote_preview_request_id = None
            self.remote_export_request_id = None


__all__ = ["REMOTE_TEXT_SEARCH_MATCH_LIMIT", "TextSearchArchiveCatalogueMixin"]
