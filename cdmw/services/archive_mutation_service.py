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


class RestoreOutsideGameFolder(PermissionError):
    """Restore Backup refused a backup before writing anything (decision 41)."""


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.relative_to(folder)
    except ValueError:
        return False
    return True


def check_backup_targets(backup: Path | str, game_root: Path | str | None) -> list[tuple[Path, Path]]:
    """Every (copy, target) pair of ``backup``, or a refusal naming the first path that is not allowed.

    A target is allowed when its recorded path, with every link resolved, lies inside
    ``game_root`` (also resolved). The copy it is restored from must lie inside the
    backup folder itself. Nothing is written here.
    """

    import json

    if game_root is None or not str(game_root).strip() or not Path(game_root).is_dir():
        raise RestoreOutsideGameFolder(
            "Choose the game folder in Browse Archives first. Restore Backup only writes inside it.")
    root = Path(game_root).expanduser().resolve()
    folder = Path(backup).expanduser().resolve()
    manifest_path = folder / "backup_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Backup manifest was not found under {folder}.")
    try:
        rows = json.loads(manifest_path.read_text(encoding="utf-8")).get("files", [])
    except (OSError, ValueError, AttributeError) as error:
        raise ValueError(f"The backup manifest in {folder} cannot be read: {error}") from error
    pairs = []
    if not isinstance(rows, list):
        raise ValueError(f"The backup manifest in {folder} cannot be read: its file list is not a list.")
    for row in rows:
        recorded = str((row or {}).get("original_path", "")) if isinstance(row, dict) else ""
        copy = str((row or {}).get("backup_path", "")) if isinstance(row, dict) else ""
        if not recorded or not Path(recorded).is_absolute():
            raise RestoreOutsideGameFolder(
                f"Restore Backup refused {folder.name}: it names a file without a full path ({recorded or 'empty'}). "
                "Nothing was written.")
        target = Path(recorded).resolve()
        if not _inside(target, root):
            raise RestoreOutsideGameFolder(
                f"Restore Backup refused {folder.name}: it would write {recorded}, which is outside the game folder "
                f"CDMW is set to ({root}). Nothing was written. Point CDMW at the game folder the backup was made "
                "for, then try again.")
        source = Path(copy).resolve() if copy else None
        if source is None or not _inside(source, folder):
            raise RestoreOutsideGameFolder(
                f"Restore Backup refused {folder.name}: the copy of {recorded} is not inside the backup folder "
                f"({copy or 'empty'}). Nothing was written.")
        pairs.append((source, target))
    return pairs


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

        from cdmw.app.app_folder import system_temp_dir, workspace_temp_folder
        from cdmw.constants import APP_NAME

        roots = [Path(self.backup_root)]
        # Where this version kept them while its temp folder was workspace/temp (when
        # there are any), then where older versions kept them.
        earlier = workspace_temp_folder() / APP_NAME / "archive_patch_backups"
        legacy = system_temp_dir() / APP_NAME / "archive_patch_backups"
        for candidate in (earlier, legacy):
            if candidate is earlier and not candidate.is_dir():
                continue
            try:
                known = any(candidate.resolve() == root.resolve() for root in roots)
            except OSError:
                known = False
            if not known:
                roots.append(candidate)
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
        game_root: Path | str | None = None,
        on_log: Optional[Callable[[str], None]] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> Path:
        """Put back the files ``backup`` holds, but only inside ``game_root`` (decision 41).

        Every file the manifest names is checked before the first write: its recorded
        path, links resolved, must lie inside the configured game folder, and its copy
        inside the backup folder. Otherwise the whole backup is refused
        (``RestoreOutsideGameFolder``) and nothing is written.
        """

        if not confirmed:
            raise PermissionError("Archive backup restore requires explicit confirmation.")
        raise_if_cancelled(stop_event, "Archive backup restore cancelled before writing game files.")
        # The check and the copy use the same parsed list: the manifest is not read twice.
        pairs = check_backup_targets(backup, game_root)
        # A partial multi-file restore can break the checksum chain, so finish once started.
        from cdmw.core.protected_roots import game_folder_write_permit
        from cdmw.services.installation_lane import backup_installation_lanes
        with backup_installation_lanes(Path(backup)), game_folder_write_permit("Restore Backup"):
            return _archive_patching().restore_archive_patch_backup(Path(backup), on_log=on_log, pairs=pairs)


__all__ = [
    "ArchiveAddRequest",
    "ArchiveMutationService",
    "ArchivePatchRequest",
    "ArchivePatchResult",
    "RestoreOutsideGameFolder",
    "check_backup_targets",
]
