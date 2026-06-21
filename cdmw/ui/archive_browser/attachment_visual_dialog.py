"""Visual placement dialog entry point for archive attachment workflows."""

from __future__ import annotations

from typing import Optional, Sequence

from cdmw.models import ArchiveEntry, AssetFamilyGraph


class ArchiveAttachmentVisualDialogMixin:
    """Open visual placement through the native safe-placement editor."""

    def _open_archive_attachment_visual_placement_dialog(
        self,
        target_entry: ArchiveEntry,
        donor_entry: Optional[ArchiveEntry],
        target_graph: AssetFamilyGraph,
        donor_graph: Optional[AssetFamilyGraph] = None,
        package_plan_rows: Sequence[dict] = (),
    ) -> None:
        return self._open_archive_attachment_safe_placement_dialog(
            target_entry,
            donor_entry,
            target_graph,
            donor_graph,
            package_plan_rows=package_plan_rows,
        )


__all__ = ["ArchiveAttachmentVisualDialogMixin"]
