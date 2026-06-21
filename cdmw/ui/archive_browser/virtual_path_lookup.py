"""Archive entry lookup helpers keyed by virtual archive paths."""

from __future__ import annotations

from typing import Optional

from cdmw.models import ArchiveEntry


class ArchiveVirtualPathLookupMixin:
    """Find archive entries through the active normalized path index."""

    def _find_archive_entry_by_virtual_path(self, virtual_path: str) -> Optional[ArchiveEntry]:
        normalized = virtual_path.replace("\\", "/").strip().lower()
        matches = self.archive_entries_by_normalized_path.get(normalized, [])
        return matches[0] if matches else None


__all__ = ["ArchiveVirtualPathLookupMixin"]
