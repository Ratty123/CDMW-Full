"""Move what is already patched into the shipped archives out into the overlay, and take
the overlay away again.

The workbench used to have one way to install: write into the archives the game shipped and
keep a backup of every file it touched. An install that goes into a directory of its own is
cheaper and easier to undo, but it does nothing for someone who already has items in the
shipped archives -- and while those patches are in there, the shipped archives are not the
shipped archives any more.

The backups say what changed. Every patch this workbench wrote copied the files it was about
to touch, so the oldest copy of a file is what that file looked like before any of it
happened. Comparing that copy's index with the one on disk names every archive entry that
was added or rewritten, which is exactly what has to move; payloads move as they are stored,
so nothing is decompressed and recompressed on the way.

Removing the overlay is the other half: unmount it, delete it, and the game is reading the
shipped archives again.
"""

from __future__ import annotations

import json
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.archive_overlay import OverlayFile, build_overlay_archive
from cdmw.core.papgt_format import PapgtDirectory, papgt_with_directory, parse_papgt, serialize_papgt
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.archive_overlay_install import (
    OVERLAY_OWNER_BYTES,
    OVERLAY_OWNER_MARKER,
    is_cdmw_overlay_directory,
    overlay_directory_name,
)

__all__ = [
    "MigrationPlan",
    "MigrationResult",
    "RemovalResult",
    "migrate_into_overlay",
    "plan_migration",
    "remove_overlay",
]


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    """What a move would carry: the entries that differ from the oldest backup, the archive
    files that would go back to that backup, and which backups the comparison came from."""

    entries: Tuple[OverlayFile, ...]
    restore: Tuple[Tuple[Path, Path], ...]
    backups: Tuple[Path, ...]
    groups_without_a_backup: Tuple[str, ...] = field(default=())

    @property
    def payload_bytes(self) -> int:
        return sum(len(item.payload) for item in self.entries)

    @property
    def is_empty(self) -> bool:
        return not self.entries


@dataclass(frozen=True, slots=True)
class MigrationResult:
    directory: Path
    moved: int
    restored: Tuple[Path, ...]
    backup_dir: Optional[Path]
    payload_bytes: int


@dataclass(frozen=True, slots=True)
class RemovalResult:
    directory: Optional[Path]
    unmounted: bool
    removed_files: int
    backup_dir: Optional[Path]
    #: Loose files beside the archives that the overlay had rewritten and that came back
    #: with it, `meta/0.pathc` above all.
    restored_meta: Tuple[str, ...] = ()


def _oldest_copies(backups: Sequence[Path]) -> Tuple[Dict[Path, Path], Tuple[Path, ...]]:
    """`{original file: its oldest copy}` across `backups`; the oldest copy wins, which is
    the state before this workbench touched the file at all."""

    copies: Dict[Path, Path] = {}
    used: List[Path] = []
    for backup in sorted(backups, key=lambda path: path.name):
        try:
            manifest = json.loads((backup / "backup_manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        contributed = False
        for record in manifest.get("files", ()) or ():
            try:
                original = Path(str(record["original_path"])).resolve()
                copy = Path(str(record["backup_path"]))
            except (KeyError, TypeError, ValueError):
                continue
            if copy.is_file() and original not in copies:
                copies[original] = copy
                contributed = True
        if contributed:
            used.append(backup)
    return copies, tuple(used)


def _entry_key(entry) -> str:
    return str(entry.path).replace("\\", "/").strip("/")


def _read_span(path: Path, offset: int, size: int) -> Optional[bytes]:
    if size <= 0 or not path.is_file():
        return None
    with path.open("rb") as handle:
        handle.seek(int(offset))
        payload = handle.read(int(size))
    return payload if len(payload) == int(size) else None


def plan_migration(
    package_root: Path,
    *,
    backups: Optional[Sequence[Path]] = None,
    stop_event: Optional[threading.Event] = None,
) -> MigrationPlan:
    """What sits in the shipped archives that did not ship with them.

    An entry counts as changed when its stored bytes differ from the ones in the oldest
    backup of its archive, or when that backup's index has no such entry. Archive groups
    with no backup at all are reported rather than guessed at: nothing is known about what
    was done to them, so nothing of theirs moves.
    """

    from cdmw.core.archive_patching import list_archive_patch_backups

    root = Path(package_root).resolve()
    known = list(backups) if backups is not None else list(list_archive_patch_backups())
    copies, used = _oldest_copies(known)
    entries: List[OverlayFile] = []
    restore: List[Tuple[Path, Path]] = []
    without: List[str] = []  # archive groups the backups say nothing about
    for pamt_path in sorted(root.glob("*/0.pamt")):
        raise_if_cancelled(stop_event, "Reading the archives was cancelled.")
        resolved = pamt_path.resolve()
        older_pamt = copies.get(resolved)
        if older_pamt is None:
            without.append(pamt_path.parent.name)
            continue
        # the copies are flat files named "<group>_<file>", so a PAZ of the old index is
        # found by the original path it was copied from rather than beside the copy
        old_paz = {
            index: copies.get((pamt_path.parent / f"{index}.paz").resolve())
            for index in range(64)
        }
        before = {}
        for entry in parse_archive_pamt(older_pamt, paz_dir=older_pamt.parent):
            before[_entry_key(entry)] = entry
        moved_here = 0
        for entry in parse_archive_pamt(pamt_path):
            raise_if_cancelled(stop_event, "Reading the archives was cancelled.")
            key = _entry_key(entry)
            payload = _read_span(Path(entry.paz_file), int(entry.offset), int(entry.comp_size))
            if payload is None:
                continue
            previous = before.get(key)
            if previous is not None:
                source = old_paz.get(int(previous.paz_index))
                if source is not None:
                    old_payload = _read_span(source, int(previous.offset), int(previous.comp_size))
                    if old_payload == payload:
                        continue
                elif int(previous.comp_size) == int(entry.comp_size) and int(previous.offset) == int(entry.offset):
                    continue  # no copy of that PAZ to compare against, and nothing moved
            entries.append(OverlayFile(path=key, payload=payload, orig_size=int(entry.orig_size), flags=int(entry.flags)))
            moved_here += 1
        if moved_here:
            restore.append((resolved, older_pamt))
            for index, source in old_paz.items():
                if source is not None and (pamt_path.parent / f"{index}.paz").is_file():
                    restore.append(((pamt_path.parent / f"{index}.paz").resolve(), source))
    papgt = (root / "meta" / "0.papgt").resolve()
    if entries and papgt in copies:
        restore.append((papgt, copies[papgt]))
    return MigrationPlan(
        entries=tuple(sorted(entries, key=lambda item: item.path)),
        restore=tuple(sorted(set(restore))),
        backups=used,
        groups_without_a_backup=tuple(sorted(set(without))),
    )


def migrate_into_overlay(
    package_root: Path,
    *,
    plan: Optional[MigrationPlan] = None,
    backup: Optional[Callable[[Sequence[Path], str], Path]] = None,
    restore_backup: Optional[Callable[[Path], object]] = None,
    game_running: Optional[Callable[[], bool]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> MigrationResult:
    """Carry everything `plan_migration` found into the overlay and put the shipped
    archives back the way the oldest backup has them.

    The payloads are read before anything is restored, so a failure part-way leaves the
    archives as they were rather than half of each.
    """

    root = Path(package_root).resolve()
    if game_running is not None and game_running():
        raise RuntimeError("CrimsonDesert.exe is running; close the game before installing, its archives are open.")
    migration = plan if plan is not None else plan_migration(root, stop_event=stop_event)
    if migration.is_empty:
        raise ValueError("Nothing in the shipped archives differs from the oldest backup of it.")
    papgt_path = root / "meta" / "0.papgt"
    mounted = {item.name for item in parse_papgt(papgt_path.read_bytes())}
    existing = next(
        (
            item
            for item in sorted(mounted)
            if item.isdigit() and int(item) >= 36 and is_cdmw_overlay_directory(root / item)
        ),
        None,
    )
    name = overlay_directory_name(root, existing=existing)
    directory = root / name

    from cdmw.services.archive_overlay_install import _existing_overlay_files, _write_atomic

    files: Dict[str, OverlayFile] = dict(_existing_overlay_files(directory))
    for item in migration.entries:
        files[item.path] = item
    built = build_overlay_archive(sorted(files.values(), key=lambda item: item.path), on_log=on_log)
    raise_if_cancelled(stop_event, "The move was cancelled before anything was written.")

    backup_dir: Optional[Path] = None
    marker = directory / OVERLAY_OWNER_MARKER
    touched = [path for path, _copy in migration.restore] + [papgt_path, directory / "0.pamt", directory / "0.paz", marker]
    rollback_files = (
        ()
        if backup is not None and restore_backup is not None
        else tuple((path.resolve(), path.read_bytes()) for path in touched if path.is_file())
    )
    created_files = tuple(path.resolve() for path in touched if not path.exists())
    if backup is not None:
        targets = [path for path, _copy in migration.restore] + [papgt_path]
        targets += [path for path in (directory / "0.pamt", directory / "0.paz", marker) if path.is_file()]
        backup_dir = backup(sorted(set(targets)), f"Move {len(migration.entries)} entrie(s) into the overlay at {name}")
        if on_log is not None:
            on_log(f"Backup created: {backup_dir}")

    restored: List[Path] = []
    try:
        raise_if_cancelled(stop_event, "Archive patch cancelled; restoring the backup.")
        for target, source in migration.restore:
            _write_atomic(target, source.read_bytes())
            restored.append(target)
            if on_log is not None:
                on_log(f"Restored {target.parent.name}/{target.name} from the oldest backup of it.")

        directory.mkdir(parents=True, exist_ok=True)
        _write_atomic(marker, OVERLAY_OWNER_BYTES)
        _write_atomic(directory / "0.paz", built.paz_bytes)
        _write_atomic(directory / "0.pamt", built.pamt_bytes)
        _write_atomic(papgt_path, papgt_with_directory(papgt_path.read_bytes(), name, built.pamt_checksum, first=True))
    except BaseException as error:
        try:
            if backup_dir is not None and restore_backup is not None:
                restore_backup(backup_dir)
            else:
                for target, payload in rollback_files:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    _write_atomic(target, payload)
        except Exception as rollback_error:
            raise RuntimeError(f"Overlay migration failed and its backup could not be restored: {rollback_error}") from error
        finally:
            for path in sorted(created_files, key=lambda item: len(item.parts), reverse=True):
                path.unlink(missing_ok=True)
            try:
                directory.rmdir()
            except OSError:
                pass
        raise
    if on_log is not None:
        on_log(f"Moved {len(migration.entries)} entrie(s) into {name}: {len(built.paz_bytes):,} bytes, mounted first.")
    return MigrationResult(
        directory=directory,
        moved=len(migration.entries),
        restored=tuple(restored),
        backup_dir=backup_dir,
        payload_bytes=len(built.paz_bytes),
    )


def remove_overlay(
    package_root: Path,
    *,
    directory_name: Optional[str] = None,
    backup: Optional[Callable[[Sequence[Path], str], Path]] = None,
    restore_backup: Optional[Callable[[Path], object]] = None,
    game_running: Optional[Callable[[], bool]] = None,
    backups: Optional[Sequence[Path]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> RemovalResult:
    """Unmount the workbench's overlay and delete it.

    Anything that only lived in the overlay is gone from the game with it, which is the
    point: the shipped archives were never written to, so taking the directory away leaves
    the install as it was.
    """

    root = Path(package_root).resolve()
    if game_running is not None and game_running():
        raise RuntimeError("CrimsonDesert.exe is running; close the game before installing, its archives are open.")
    papgt_path = root / "meta" / "0.papgt"
    directories = list(parse_papgt(papgt_path.read_bytes()))
    if directory_name is not None:
        name = str(directory_name)
        if not is_cdmw_overlay_directory(root / name):
            raise ValueError(f"Archive directory {name} is not owned by CDMW and will not be removed.")
    else:
        name = next(
            (
                item.name
                for item in directories
                if item.name.isdigit() and int(item.name) >= 36 and is_cdmw_overlay_directory(root / item.name)
            ),
            None,
        )
    if name is None:
        return RemovalResult(directory=None, unmounted=False, removed_files=0, backup_dir=None)
    directory = root / name
    files = [path for path in (directory / "0.pamt", directory / "0.paz") if path.is_file()]
    owned_files = [path for path in directory.rglob("*") if path.is_file()]
    stale_meta = _meta_to_restore(root, backups=backups)

    raise_if_cancelled(stop_event, "The move was cancelled before anything was written.")
    touched = [papgt_path, *owned_files, *stale_meta]
    rollback_files = (
        ()
        if backup is not None and restore_backup is not None
        else tuple((path.resolve(), path.read_bytes()) for path in touched if path.is_file())
    )

    backup_dir: Optional[Path] = None
    if backup is not None:
        backup_dir = backup(sorted({papgt_path, *owned_files, *stale_meta}), f"Remove the overlay at {name}")
        if on_log is not None:
            on_log(f"Backup created: {backup_dir}")

    from cdmw.services.archive_overlay_install import _write_atomic

    kept = [item for item in directories if item.name != name]
    restored: List[str] = []
    try:
        raise_if_cancelled(stop_event, "Archive patch cancelled; restoring the backup.")
        _write_atomic(papgt_path, serialize_papgt(kept, header=papgt_path.read_bytes()[:12]))
        if on_log is not None:
            on_log(f"Unmounted {name} from meta/0.papgt; {len(kept)} directories left.")
        if directory.is_dir():
            shutil.rmtree(directory)
            if on_log is not None:
                on_log(f"Deleted {name} ({len(files)} file(s)).")
        for target, baseline in sorted(stale_meta.items()):
            _write_atomic_meta(target, baseline.read_bytes())
            relative = target.relative_to(root).as_posix()
            restored.append(relative)
            if on_log is not None:
                on_log(f"Put {relative} back to what it was before the overlay.")
    except BaseException as error:
        try:
            if backup_dir is not None and restore_backup is not None:
                restore_backup(backup_dir)
            else:
                for target, payload in rollback_files:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    _write_atomic(target, payload)
        except Exception as rollback_error:
            raise RuntimeError(f"Overlay removal failed and its backup could not be restored: {rollback_error}") from error
        raise
    from cdmw.services.archive_overlay_install import forget_overlay_baseline

    forget_overlay_baseline(root)
    return RemovalResult(
        directory=directory, unmounted=True, removed_files=len(files), backup_dir=backup_dir,
        restored_meta=tuple(restored),
    )


def _write_atomic_meta(path: Path, payload: bytes) -> None:
    from cdmw.services.archive_overlay_install import _write_atomic

    _write_atomic(path, payload)


def _meta_to_restore(root: Path, *, backups: Optional[Sequence[Path]] = None) -> Dict[Path, Path]:
    """`{loose file beside the archives: the copy from before the overlay}` for the ones
    that differ, as the install recorded them.

    Not the workbench's backup folders: the oldest of those is only as old as the first
    time this workbench touched the file, which may already have been a modified one, and
    restoring from it would write a stale registry over a good one.
    """

    from cdmw.services.archive_overlay_install import overlay_baseline_files

    out: Dict[Path, Path] = {}
    for relative, kept in overlay_baseline_files(root).items():
        target = root / relative
        try:
            if target.is_file() and target.read_bytes() != kept.read_bytes():
                out[target] = kept
        except OSError:
            continue
    return out
