"""Backups and Restore for the game files an older CDMW changed.

CDMW never writes into the game's archives. What is left here:

- ``list_backups`` and ``restore_backup``, behind Browse Archives' **Restore
  Backup...**, which puts back the archive files an older CDMW version patched
  into the game, from the backup it made then;
- ``backup_files`` and ``restore_backup`` behind Browse Archives' **Remove What
  an Older CDMW Installed...** (``cdmw.services.old_install_removal``), which
  backs up the index files it changes first, so Restore Backup can undo it, and
  restores that backup itself if the removal fails halfway.

The direct patch plan (``prepare_patch`` and ``apply_patch``) was removed with the
"Patch Game Files" route (decision 35), and the overlay and virtual-loader
installs with decision 39.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cdmw.domain.archives.mutation import ArchiveAddRequest, ArchivePatchRequest, ArchivePatchResult
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.application_shutdown_service import archive_write_scope


def _archive_patching():
    from cdmw.core import archive_patching

    return archive_patching


@dataclass(slots=True)
class ArchiveMutationService:
    settings: object | None = None

    @property
    def backup_root(self) -> Path:
        return _archive_patching().ARCHIVE_PATCH_BACKUP_ROOT

    @archive_write_scope()
    def backup_files(
        self,
        paths: Iterable[Path],
        *,
        description: str = "",
        on_log: Optional[Callable[[str], None]] = None,
    ) -> Path:
        """Copy `paths` into a new backup folder and return it.

        The overlay route knows exactly which files it is about to overwrite -- the mount
        list, the texture registry, and its own previous overlay -- so it hands them here
        rather than going through a patch plan that would work out the shipped archives.
        """

        targets = sorted({Path(path).resolve() for path in paths})
        if not targets:
            raise ValueError("A backup needs at least one file.")
        return _archive_patching()._create_backup(targets, description=str(description or "Archive backup"), on_log=on_log)

    def backup_roots(self) -> tuple[Path, ...]:
        """Where backups are looked for: the current root, then the one older versions used.

        CDMW now keeps its temporary files in ``workspace\\temp``; an older version
        made its backups under the system's temp folder, and those are the ones
        Restore Backup exists for.
        """

        from cdmw.app.app_folder import system_temp_dir
        from cdmw.constants import APP_NAME

        roots = [Path(self.backup_root)]
        legacy = system_temp_dir() / APP_NAME / "archive_patch_backups"
        try:
            same = legacy.resolve() == roots[0].resolve()
        except OSError:
            same = False
        if not same:
            roots.append(legacy)
        return tuple(roots)

    def list_backups(self, *, limit: Optional[int] = None) -> list[Path]:
        """Every backup folder with a manifest, newest first, from every backup root."""

        found: dict[Path, Path] = {}
        for root in self.backup_roots():
            try:
                children = list(root.iterdir()) if root.is_dir() else []
            except OSError:
                children = []
            for path in children:
                if path.is_dir() and (path / "backup_manifest.json").is_file():
                    found.setdefault(path.resolve(), path)
        backups = sorted(found.values(), key=lambda path: path.name, reverse=True)
        return backups if limit is None else backups[: max(0, int(limit))]

    @archive_write_scope()
    def restore_backup(
        self,
        backup: Path | str,
        *,
        confirmed: bool = False,
        on_log: Optional[Callable[[str], None]] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> Path:
        if not confirmed:
            raise PermissionError("Archive backup restore requires explicit confirmation.")
        raise_if_cancelled(stop_event, "Archive backup restore cancelled before writing game files.")
        # A partial multi-file restore can break the checksum chain, so finish once started.
        from cdmw.services.installation_lane import backup_installation_lanes
        with backup_installation_lanes(Path(backup)):
            return _archive_patching().restore_archive_patch_backup(Path(backup), on_log=on_log)


__all__ = [
    "ArchiveAddRequest",
    "ArchiveMutationService",
    "ArchivePatchRequest",
    "ArchivePatchResult",
]
