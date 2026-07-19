"""Resident-worker lookup helpers for related-set archive export."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Dict, List, Sequence

from cdmw.domain.archives.catalogue import (
    ArchiveEntryDto,
    ArchiveLookupKind,
    ArchiveLookupRequest,
    ArchiveLookupResult,
)
from cdmw.domain.archives.catalogue_operations import ArchiveExportSelectionKind
from cdmw.ui.archive_browser.remote_window_bridge import (
    MAX_REMOTE_EXPORT_ENTRY_IDS,
    ArchiveRemoteExportSelection,
)


class ArchiveRemoteRelatedExportMixin:
    """Resolve related paths and hand worker entry IDs to archive export."""

    def _start_remote_related_archive_lookup(
        self,
        normalized_paths: tuple[str, ...],
        description: str,
    ) -> None:
        if len(normalized_paths) > MAX_REMOTE_EXPORT_ENTRY_IDS:
            self.set_status_message(
                f"Related-set extraction accepts at most {MAX_REMOTE_EXPORT_ENTRY_IDS:,} paths.",
                error=True,
            )
            return
        self._ensure_remote_archive_export_wiring()
        if self._archive_remote_export_request_id is not None:
            self.set_status_message("Another archive export is already running.", error=True)
            return
        if self._archive_remote_related_lookup_request_id is not None:
            self.set_status_message("Another related-set lookup is already running.", error=True)
            return
        session = self.archive_remote_bridge.current_session
        self._archive_remote_export_generation += 1
        generation = self._archive_remote_export_generation
        request = ArchiveLookupRequest(
            session_id=session.session_id,
            kind=ArchiveLookupKind.EXACT_PATHS,
            values=normalized_paths,
            limit=MAX_REMOTE_EXPORT_ENTRY_IDS,
        )
        self._archive_remote_related_lookup_context = {
            "paths": normalized_paths,
            "description": str(description or "Extracting related archive set..."),
            "entries": [],
            "session_ids": set(),
            "truncated": False,
        }
        try:
            self._archive_remote_related_lookup_request_id = self.archive_catalogue_service.resolve_entries(
                request,
                ui_generation=generation,
            )
        except Exception as exc:
            self._archive_remote_related_lookup_context = {}
            self.set_status_message(f"Related archive paths could not be resolved: {exc}", error=True)
            return
        self.set_busy(True, build_mode=True)
        self.set_status_message("Resolving related archive paths with the standalone worker...")
        self._set_archive_load_progress(
            "Resolving related archive paths...",
            phase="Resolving",
            percent=0,
            allow_decrease=True,
        )

    def _handle_remote_related_lookup_progress(self, request_id: str, update: object) -> None:
        if request_id != getattr(self, "_archive_remote_related_lookup_request_id", None):
            return
        completed = max(0, int(getattr(update, "completed", 0) or 0))
        total = max(0, int(getattr(update, "total", 0) or 0))
        phase = str(getattr(update, "phase", "resolve_entries") or "resolve_entries").replace(
            "_", " "
        ).title()
        self._set_archive_load_progress(phase, completed, total, phase="Resolving")

    def _record_remote_related_lookup(self, payload: ArchiveLookupResult) -> None:
        entries = self._archive_remote_related_lookup_context.get("entries")
        if isinstance(entries, list):
            entries.extend(payload.entries)
        session_ids = self._archive_remote_related_lookup_context.get("session_ids")
        if isinstance(session_ids, set):
            session_ids.add(payload.session_id)
            session_ids.update(entry.session_id for entry in payload.entries)
        if payload.truncated:
            self._archive_remote_related_lookup_context["truncated"] = True

    def _handle_remote_related_lookup_batch(
        self,
        request_id: str,
        operation: str,
        payload: object,
    ) -> None:
        if (
            request_id != getattr(self, "_archive_remote_related_lookup_request_id", None)
            or operation != "resolve_entries"
            or not isinstance(payload, ArchiveLookupResult)
        ):
            return
        self._record_remote_related_lookup(payload)

    def _finish_remote_related_lookup(self) -> Dict[str, object]:
        context = dict(getattr(self, "_archive_remote_related_lookup_context", {}) or {})
        self._archive_remote_related_lookup_request_id = None
        self._archive_remote_related_lookup_context = {}
        self.set_busy(False, build_mode=False)
        return context

    def _handle_remote_related_lookup_result(
        self,
        request_id: str,
        operation: str,
        payload: object,
    ) -> None:
        if request_id != getattr(self, "_archive_remote_related_lookup_request_id", None):
            return
        if operation == "resolve_entries" and isinstance(payload, ArchiveLookupResult):
            self._record_remote_related_lookup(payload)
        context = self._finish_remote_related_lookup()
        if operation != "resolve_entries" or not isinstance(payload, ArchiveLookupResult):
            self.set_status_message("Archive worker returned an invalid related-set lookup.", error=True)
            return
        if bool(context.get("truncated", False)):
            self.set_status_message(
                "Related-set extraction matched too many duplicate archive entries; narrow the requested paths.",
                error=True,
            )
            return
        current_session = getattr(getattr(self, "archive_remote_bridge", None), "current_session", None)
        session_ids = context.get("session_ids", set())
        if (
            current_session is None
            or not isinstance(session_ids, set)
            or session_ids != {current_session.session_id}
        ):
            self.set_status_message(
                "The archive session changed while related paths were resolving; retry the extraction.",
                error=True,
            )
            return
        requested_paths = tuple(str(path) for path in context.get("paths", ()) if str(path))
        raw_entries = context.get("entries", ())
        entries = (
            tuple(entry for entry in raw_entries if isinstance(entry, ArchiveEntryDto))
            if isinstance(raw_entries, (list, tuple))
            else ()
        )
        selection = _remote_related_export_selection(requested_paths, entries)
        if selection is None:
            self.set_status_message(
                "No matching archive entries were found for the related-set extraction.",
                error=True,
            )
            return
        missing = max(0, len(requested_paths) - selection.requested_count)
        if missing:
            self.append_archive_log(
                f"Related-set lookup skipped {missing:,} path(s) that were not present in the current archive session."
            )
        self._run_remote_archive_export(
            selection,
            allow_original_dds_root=False,
            description=str(context.get("description", "Extracting related archive set...")),
        )

    def _handle_remote_related_lookup_failure(self, request_id: str, error: object) -> None:
        if request_id != getattr(self, "_archive_remote_related_lookup_request_id", None):
            return
        self._finish_remote_related_lookup()
        message = str(getattr(error, "message", "") or error or "Related archive lookup failed.")
        self.set_status_message(message, error=True)
        self._set_archive_load_progress("Related archive lookup failed.", phase="Ready", percent=100)

    def _handle_remote_related_lookup_cancelled(self, request_id: str) -> None:
        if request_id != getattr(self, "_archive_remote_related_lookup_request_id", None):
            return
        self._finish_remote_related_lookup()
        self.set_status_message("Related archive lookup cancelled.")
        self._set_archive_load_progress("Related archive lookup cancelled.", phase="Ready", percent=100)


def normalized_related_archive_paths(raw_paths: Sequence[object]) -> tuple[str, ...]:
    """Normalize, deduplicate, and preserve caller order for related paths."""

    paths: list[str] = []
    seen: set[str] = set()
    for raw_path in raw_paths:
        if not isinstance(raw_path, str):
            continue
        normalized = raw_path.strip().replace("\\", "/").strip("/").casefold()
        if normalized and normalized not in seen:
            paths.append(normalized)
            seen.add(normalized)
    return tuple(paths)


def _remote_related_export_selection(
    requested_paths: Sequence[str],
    entries: Sequence[ArchiveEntryDto],
) -> ArchiveRemoteExportSelection | None:
    candidates_by_path: Dict[str, List[ArchiveEntryDto]] = {}
    requested_set = set(requested_paths)
    for entry in entries:
        normalized = entry.path.replace("\\", "/").strip("/").casefold()
        if normalized in requested_set:
            candidates_by_path.setdefault(normalized, []).append(entry)
    selected: list[ArchiveEntryDto] = []
    seen_entry_ids: set[int] = set()
    for path in requested_paths:
        candidates = candidates_by_path.get(path, ())
        if not candidates:
            continue
        active = [entry for entry in candidates if entry.is_active_override]
        entry = (active or list(candidates))[-1]
        if entry.entry_id in seen_entry_ids:
            continue
        selected.append(entry)
        seen_entry_ids.add(entry.entry_id)
    if not selected:
        return None
    workflow_paths: list[str] = []
    for entry in selected:
        source_pamt = entry.source_pamt.replace("\\", "/")
        package_root = PurePosixPath(source_pamt).parent.name.strip() or "package"
        virtual_path = entry.path.replace("\\", "/").lstrip("/")
        workflow_paths.append(f"{package_root}/{virtual_path}")
    dds_count = sum(entry.extension.casefold() == ".dds" for entry in selected)
    return ArchiveRemoteExportSelection(
        ArchiveExportSelectionKind.ENTRY_IDS,
        len(selected),
        entry_ids=tuple(entry.entry_id for entry in selected),
        all_dds=dds_count == len(selected),
        workflow_paths=tuple(workflow_paths),
        dds_count=dds_count,
        include_package_root=True,
    )


__all__ = ["ArchiveRemoteRelatedExportMixin", "normalized_related_archive_paths"]
