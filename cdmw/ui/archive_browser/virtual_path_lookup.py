"""Archive entry lookup helpers keyed by virtual archive paths."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Optional, Tuple

from cdmw.models import ArchiveEntry


class ArchiveVirtualPathLookupMixin:
    """Find archive entries through the active normalized path index."""

    def _find_archive_entry_by_virtual_path(self, virtual_path: str) -> Optional[ArchiveEntry]:
        normalized = virtual_path.replace("\\", "/").strip().strip("/").casefold()
        matches = self.archive_entries_by_normalized_path.get(normalized, ())
        if not matches:
            matches = getattr(self, "archive_mesh_entries_by_normalized_path", {}).get(normalized, ())
        if not matches and getattr(self, "archive_entries", ()):
            ensure_indexes = getattr(self, "_archive_catalogue_lookup_pending", None)
            if callable(ensure_indexes):
                ensure_indexes()
        return matches[0] if matches else None

    def _archive_lookup_indexes_snapshot(
        self,
    ) -> Optional[
        Tuple[
            Mapping[str, Sequence[ArchiveEntry]],
            Mapping[str, Sequence[ArchiveEntry]],
        ]
    ]:
        path_index = getattr(self, "archive_entries_by_normalized_path", {}) or {}
        basename_index = getattr(self, "archive_entries_by_basename", {}) or {}
        if path_index and basename_index:
            return path_index, basename_index
        if not getattr(self, "archive_entries", ()):
            return {}, {}
        ensure_indexes = getattr(self, "_archive_catalogue_lookup_pending", None)
        if callable(ensure_indexes):
            ensure_indexes()
        set_status = getattr(self.shell, "set_status_message", None)
        if callable(set_status):
            set_status("Archive path lookup is warming; retry this action when indexing finishes.")
        return None

    def _reveal_archive_path_in_live_catalogue(
        self,
        virtual_path: str,
        entry: Optional[ArchiveEntry] = None,
    ) -> bool:
        """Show one archive file in the browser, whatever filters or page are active.

        The file is found through the live catalogue and shown as a one-file scope, so a
        filter or an unloaded page cannot hide it. With ``entry`` given, the match must
        carry its full archive identity (package, archive and offset), not only its path.
        Returns False when the live catalogue cannot take the request.
        """

        from cdmw.domain.archives.catalogue import ArchiveLookupKind
        from cdmw.ui.archive_browser.remote_entry_lookup import (
            LiveCatalogueState,
            RemoteLookupOutcome,
            dto_matching_entry,
            live_catalogue_state,
            lookup_requests,
            normalized_lookup_path,
            start_live_catalogue_lookup,
        )

        bridge = getattr(self, "archive_remote_bridge", None)
        session = getattr(bridge, "current_session", None)
        normalized = normalized_lookup_path(virtual_path)
        if live_catalogue_state(self) != LiveCatalogueState.READY or session is None or not normalized:
            return False
        display_path = str(virtual_path or "").replace("\\", "/").strip().strip("/")

        def found(outcome: RemoteLookupOutcome) -> None:
            candidates = tuple(
                dto for dto in outcome.entries if normalized_lookup_path(dto.path) == normalized
            )
            target = dto_matching_entry(candidates, entry)
            if target is None and entry is not None and candidates:
                self.shell.set_status_message(
                    f"{display_path} is in the archive, but not the copy this editor opened "
                    "(its package or offset changed). Refresh the Archive Browser and try again.",
                    error=True,
                )
                return
            if target is None and candidates:
                active = [dto for dto in candidates if dto.is_active_override]
                target = active[0] if active else candidates[0]
            if target is None:
                self.shell.set_status_message(
                    f"Archive Browser is open. Could not find {display_path} in the loaded archive catalogue.",
                    error=True,
                )
                return
            basename = display_path.rsplit("/", 1)[-1] or display_path
            if bridge.apply_entry_id_scope((target.entry_id,), label=f"{basename} (target)"):
                self.shell.set_status_message(f"Revealing {display_path} in Archive Browser...")
            else:
                self.shell.set_status_message(
                    f"Archive Browser could not show {display_path}; the catalogue session changed.",
                    error=True,
                )

        def failed(message: str) -> None:
            self.shell.set_status_message(f"Could not look up {display_path}: {message}", error=True)

        start_live_catalogue_lookup(
            self,
            "_archive_reveal_lookup",
            lookup_requests(session.session_id, ArchiveLookupKind.EXACT_PATHS, (display_path,)),
            on_done=found,
            on_error=failed,
        )
        return True


__all__ = ["ArchiveVirtualPathLookupMixin"]
