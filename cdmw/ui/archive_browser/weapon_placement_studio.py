"""Disabled weapon placement studio entry point."""

from __future__ import annotations

from typing import Optional

from cdmw.models import ArchiveEntry


class ArchiveWeaponPlacementStudioMixin:
    def _open_archive_weapon_placement_studio_dialog(
        self,
        entry: Optional[ArchiveEntry] = None,
    ) -> None:
        self.set_status_message("Weapon Placement Studio is disabled - WIP.", error=True)
        return


__all__ = ["ArchiveWeaponPlacementStudioMixin"]
