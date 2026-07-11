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
            ensure_indexes = getattr(self, "_ensure_archive_basic_index_worker_started", None)
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
        ensure_indexes = getattr(self, "_ensure_archive_basic_index_worker_started", None)
        if callable(ensure_indexes):
            ensure_indexes()
        set_status = getattr(self, "set_status_message", None)
        if callable(set_status):
            set_status("Archive path lookup is warming; retry this action when indexing finishes.")
        return None


__all__ = ["ArchiveVirtualPathLookupMixin"]
