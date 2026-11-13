"""Remove what an older CDMW installed into a game folder (decision 42).

CDMW up to 0.11.0-alpha.31 could install items into the game itself: archive
overlays (numbered archive group folders named in the game's mount list, with
their textures in the texture registry) and the virtual loader (an ASI in
``bin64`` and its files under ``.cdmw/virtual-loader``). Those features are gone;
this is the one way to take what they left back out.

Only what can be proved to be CDMW's is removed:

- an overlay folder is a candidate when it holds the exact owner mark the
  installer wrote (``.cdmw-new-item-overlay`` with its fixed content). The mark
  proves the folder, not its files: another tool can write its own archive into
  a marked folder after Steam's file check. So each ``0.pamt`` and ``0.paz`` is
  removed only when its SHA-256 equals the digest CDMW's overlay index recorded
  when it published that file (``published`` in ``.cdmw/overlays.json``);
  anything else in the folder stays and is named as not CDMW's. A folder named
  only in CDMW's own records (the overlay index or the last install receipt) but
  already gone from disk counts too, so a half-removed install can be finished;
- a mount-list entry is CDMW's when it names such a folder whose ``0.pamt`` is
  proved, or that is gone;
- a texture-registry entry is CDMW's when its texture is held by a proved
  ``0.pamt`` and by no other mounted archive group;
- ``bin64/CDMWVirtualLoader.asi`` is CDMW's when the owner file CDMW wrote
  beside it names its exact SHA-256;
- everything else in CDMW's own ``.cdmw/`` folder (decision 46). The item
  identity registry there (``.cdmw/independent-items.json``) is first carried
  over to the CDMW folder (``cdmw.services.game_records``) unless CDMW already
  keeps one.

Kept, always: the ASI loader (``bin64/winmm.dll``, installed by the user) and the
save backups under ``.cdmw/virtual-loader/save-backups``.

The plan is made read-only. Removal refuses while the game or DMM runs or holds
a file, refuses a plan whose files changed since it was shown, backs up every
file it will write or delete through ``ArchiveMutationService.backup_files``
(so Restore Backup can undo it), writes the mount list and the registry first
and deletes files after, and restores the backup if any step fails. The
October 2026 mount-list layout is never rewritten: a CDMW folder still named
in it blocks the removal, with Steam's file check as the way out.

This module imports nothing of the removed installers; the two ownership
formats below are copied as data.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Iterable, Optional

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.application_shutdown_service import archive_write_scope

#: What the overlay installer wrote into every folder it created.
OVERLAY_OWNER_MARKER = ".cdmw-new-item-overlay"
OVERLAY_OWNER_BYTES = b"CDMW New Item Studio overlay v1\n"
#: The files an overlay install created in its folder.
OVERLAY_FILES = ("0.pamt", "0.paz", OVERLAY_OWNER_MARKER)
#: Shipped archive groups end at 0035; CDMW numbered its folders from 0036.
OVERLAY_FIRST = 36
RUNTIME_PATH = "bin64/CDMWVirtualLoader.asi"
RUNTIME_OWNER_PATH = ".cdmw/virtual-loader/runtime-owner.json"
RUNTIME_OWNER_FORMAT = "cdmw_virtual_runtime_owner_v1"
#: CDMW's records about overlay installs.
OVERLAY_RECORDS = (".cdmw/overlays.json", ".cdmw/last-overlay-install.json")
OVERLAY_RECORD_FOLDERS = (".cdmw/overlays", ".cdmw/retired-overlays")
VIRTUAL_FOLDER = ".cdmw/virtual-loader"
SAVE_BACKUPS = ".cdmw/virtual-loader/save-backups"
#: CDMW's own folder in the game. Since decision 46 nothing live is kept there: the item
#: identity registry moved to the CDMW folder (``cdmw.services.game_records``).
CDMW_FOLDER = ".cdmw"
LEGACY_REGISTRY = ".cdmw/independent-items.json"
BOOTSTRAP_PATH = "bin64/winmm.dll"
GAME_EXECUTABLE = "CrimsonDesert.exe"
MOD_MANAGER_EXECUTABLES = ("DMM.exe",)
MOUNT_LIST = "meta/0.papgt"
TEXTURE_REGISTRY = "meta/0.pathc"
CANCELLED = "Removing what an older CDMW installed was cancelled. Nothing was changed."
#: Every failure after the first change starts with this, so the page does not call it a refusal.
STOPPED_PARTWAY = "The removal stopped partway"
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


class OldInstallRemovalRefused(RuntimeError):
    """The removal cannot start; the message says why. Nothing was written."""


@dataclass(frozen=True, slots=True)
class OldInstallPlan:
    """What a removal would do, found read-only. Paths are relative to ``root``."""

    root: Path
    #: Every file to delete, in deletion order.
    delete_files: tuple[str, ...] = ()
    #: Folders to remove once empty, deepest first.
    delete_folders: tuple[str, ...] = ()
    #: CDMW overlay folders found, and the mount-list entries naming them.
    overlay_folders: tuple[str, ...] = ()
    mount_entries: tuple[str, ...] = ()
    #: Texture paths whose registry entries go.
    registry_paths: tuple[str, ...] = ()
    mount_list_after: Optional[bytes] = None
    registry_after: Optional[bytes] = None
    #: Items the overlay index says the old overlays held.
    overlay_items: tuple[str, ...] = ()
    not_cdmw: tuple[str, ...] = ()
    kept: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    #: (relative path, sha256 or None) of everything the removal reads or writes.
    observed: tuple[tuple[str, Optional[str]], ...] = ()
    total_bytes: int = 0

    @property
    def nothing_found(self) -> bool:
        return not (self.delete_files or self.mount_entries or self.registry_paths)

    @property
    def can_remove(self) -> bool:
        return not self.nothing_found and not self.blockers

    @property
    def written_files(self) -> tuple[str, ...]:
        return tuple(path for path, data in ((MOUNT_LIST, self.mount_list_after),
                                             (TEXTURE_REGISTRY, self.registry_after)) if data is not None)

    def review_lines(self) -> tuple[str, ...]:
        """Everything the removal will change, one line each, for the confirmation."""

        lines = []
        for name in self.overlay_folders:
            files = [file for file in OVERLAY_FILES if f"{name}/{file}" in self.delete_files]
            if files:  # a proved file only: an archive another tool wrote stays and is listed as not CDMW's
                lines.append(f"Folder {name}: {', '.join(files)}")
        lines += [f"Mount list entry {name} in {MOUNT_LIST}" for name in self.mount_entries]
        if self.registry_paths:
            lines.append(f"{len(self.registry_paths)} texture registry entries in {TEXTURE_REGISTRY}:")
            lines += [f"  {path}" for path in self.registry_paths]
        overlay_files = {f"{name}/{file}" for name in self.overlay_folders for file in OVERLAY_FILES}
        lines += [f"File {path}" for path in self.delete_files if path not in overlay_files]
        return tuple(lines)


@dataclass(frozen=True, slots=True)
class OldInstallRemovalResult:
    root: Path
    backup_dir: Path
    removed: tuple[str, ...]
    not_cdmw: tuple[str, ...]
    kept: tuple[str, ...]
    leftovers: tuple[str, ...] = field(default=())


# ----------------------------------------------------------------- reading


def _digest(path: Path) -> Optional[str]:
    try:
        if not path.is_file():
            return None
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                hasher.update(block)
        return hasher.hexdigest()
    except OSError:
        return None


def _is_link(path: Path) -> bool:
    """A symlink, or any Windows reparse point (a junction among them), whatever the Python version."""

    try:
        status = os.lstat(path)
    except OSError:
        return False
    if path.is_symlink():
        return True
    return bool(getattr(status, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _checked(root: Path, relative: str) -> Path:
    """``_inside``, plus the resolved path must still lie inside the game folder."""

    path = _inside(root, relative)
    try:
        path.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise OldInstallRemovalRefused(f"{relative} resolves outside the game folder; it is left alone.") from exc
    return path


def _inside(root: Path, relative: str) -> Path:
    """``root / relative``, refusing anything that leaves ``root`` or passes a link."""

    parts = relative.replace("\\", "/").split("/")
    if relative.startswith("/") or any(part in ("", ".", "..") or ":" in part for part in parts):
        raise OldInstallRemovalRefused(f"Unsafe path in an old install record: {relative}")
    path = root
    for part in parts:
        path = path / part
        if _is_link(path):
            raise OldInstallRemovalRefused(f"{relative} passes through a link; it is left alone.")
    return path


def _read_json(path: Path) -> Optional[dict]:
    try:
        if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def is_cdmw_overlay_folder(folder: Path) -> bool:
    marker = Path(folder) / OVERLAY_OWNER_MARKER
    try:
        return marker.is_file() and not marker.is_symlink() and marker.read_bytes() == OVERLAY_OWNER_BYTES
    except OSError:
        return False


def _overlay_name(name: str) -> bool:
    return len(name) == 4 and name.isdigit() and int(name) >= OVERLAY_FIRST


def _recorded_overlay_names(root: Path) -> tuple[set[str], tuple[str, ...]]:
    """Folder names CDMW's own records claim, and the item labels the index lists."""

    names, labels = set(), []
    index = _read_json(root / ".cdmw" / "overlays.json")
    if index is not None:
        directory = str(index.get("directory") or "")
        if _overlay_name(directory):
            names.add(directory)
        for layer in index.get("layers") or ():
            if isinstance(layer, dict) and isinstance(layer.get("label"), str):
                labels.append(layer["label"])
    receipt = _read_json(root / ".cdmw" / "last-overlay-install.json")
    if receipt is not None and receipt.get("format") == "cdmw_overlay_install_receipt_v1":
        directory = str(receipt.get("overlay_directory") or "")
        if _overlay_name(directory):
            names.add(directory)
    return names, tuple(labels)


def _published_digests(root: Path) -> dict[str, str]:
    """``{relative path: sha256}`` of every overlay file CDMW's index recorded as published."""

    index = _read_json(root / ".cdmw" / "overlays.json")
    published = index.get("published") if index is not None else None
    if not isinstance(published, dict):
        return {}
    return {str(path).replace("\\", "/"): digest for path, digest in published.items()
            if isinstance(digest, str) and len(digest) == 64}


def _mount_list(root: Path):
    from cdmw.core.papgt_format import is_compact_papgt, read_papgt_directories

    path = root / "meta" / "0.papgt"
    data = path.read_bytes()
    return data, read_papgt_directories(data), is_compact_papgt(data)


def _dds_paths(pamt: Path, stop_event) -> set[str]:
    from cdmw.core.archive_format import parse_archive_pamt

    raise_if_cancelled(stop_event, CANCELLED)
    return {str(entry.path).replace("\\", "/").lower() for entry in parse_archive_pamt(pamt)
            if str(entry.path).lower().endswith(".dds")}


def _files_under(root: Path, relative: str) -> list[str]:
    folder = root / relative
    if not folder.is_dir() or _is_link(folder):
        return []
    found = []
    for current, dirs, files in os.walk(folder):
        dirs[:] = [name for name in dirs if not _is_link(Path(current) / name)]
        for name in files:
            path = Path(current) / name
            if not _is_link(path):
                found.append(path.relative_to(root).as_posix())
    return sorted(found)


def _folders_under(root: Path, relative: str) -> list[str]:
    folder = root / relative
    if not folder.is_dir() or _is_link(folder):
        return []
    found = [relative]
    for current, dirs, _files in os.walk(folder):
        dirs[:] = [name for name in dirs if not _is_link(Path(current) / name)]
        found += [(Path(current) / name).relative_to(root).as_posix() for name in dirs]
    return sorted(found, key=lambda value: value.count("/"), reverse=True)


def find_old_install(
    root: Path | str,
    *,
    on_progress: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> OldInstallPlan:
    """What an older CDMW left in ``root`` and what removing it would change. Reads only."""

    from cdmw.core.papgt_format import parse_papgt, serialize_papgt
    from cdmw.core.pathc_format import parse_pathc, pathc_checksum

    root = Path(root).expanduser().resolve()
    if not (root / "bin64" / GAME_EXECUTABLE).is_file() or not (root / MOUNT_LIST).is_file():
        raise OldInstallRemovalRefused(f"{root} is not a Crimson Desert game folder. Choose the game folder first.")
    progress = on_progress or (lambda _text: None)
    delete, folders, not_cdmw, kept, blockers = [], [], [], [], []
    progress("Reading the mount list...")
    mount_data, mounted, compact = _mount_list(root)
    recorded, overlay_items = _recorded_overlay_names(root)
    published = _published_digests(root)

    # Overlay folders: marked on disk, or named by CDMW's records and already gone.
    owned, looks_like = [], []
    candidates = {child.name for child in root.iterdir() if child.is_dir() and _overlay_name(child.name)}
    candidates |= {item.name for item in mounted if _overlay_name(item.name)} | recorded
    for name in sorted(candidates):
        raise_if_cancelled(stop_event, CANCELLED)
        folder = root / name
        if _is_link(folder):
            not_cdmw.append(f"{name}: a link, left alone")
        elif folder.is_dir() and is_cdmw_overlay_folder(folder):
            owned.append(name)
        elif folder.is_dir():
            looks_like.append(name)
        elif name in recorded:
            owned.append(name)  # Half removed: CDMW's records name it, the folder is gone.
    for name in looks_like:
        not_cdmw.append(f"{name}: no CDMW owner mark, so it is not CDMW's")
    # The mark proves the folder, not its files: each archive file must match what
    # CDMW's index recorded when it published it.
    proved = []  # folders whose 0.pamt is CDMW's, or that are gone
    for name in owned:
        folder = root / name
        if not folder.is_dir():
            proved.append(name)
            continue
        unproved = []
        for file in ("0.pamt", "0.paz"):
            relative = f"{name}/{file}"
            if not (folder / file).is_file():
                continue
            if published.get(relative) is not None and published[relative] == _digest(folder / file):
                delete.append(relative)
            else:
                unproved.append(file)
                not_cdmw.append(f"{relative}: not the file CDMW's records say it installed, so it is left alone")
        if (folder / OVERLAY_OWNER_MARKER).is_file() and not unproved:
            delete.append(f"{name}/{OVERLAY_OWNER_MARKER}")
        if "0.pamt" not in unproved:
            proved.append(name)
        extra = sorted(child.name for child in folder.iterdir() if child.name not in OVERLAY_FILES)
        not_cdmw += [f"{name}/{child}: not written by CDMW's installer" for child in extra]
        folders.append(name)

    # Mount-list entries naming CDMW's folders whose index file is proved.
    mount_entries = tuple(item.name for item in mounted if item.name in proved)
    mount_after = None
    if mount_entries and compact:
        blockers.append(
            f"The game's mount list ({MOUNT_LIST}) still names {', '.join(mount_entries)}, and CDMW cannot rewrite "
            "the mount list of the current game version. Use Steam's Verify integrity of game files first, then "
            "check again.")
    elif mount_entries:
        entries = parse_papgt(mount_data)
        mount_after = serialize_papgt([item for item in entries if item.name not in mount_entries],
                                      header=mount_data[:12])

    # Texture-registry entries held only by CDMW's folders.
    registry_paths, registry_after = (), None
    registry = root / TEXTURE_REGISTRY
    owned_dds = set()
    for name in proved:
        pamt = root / name / "0.pamt"
        if pamt.is_file():
            progress(f"Reading {name}...")
            owned_dds |= _dds_paths(pamt, stop_event)
    if owned_dds and registry.is_file():
        others = set()
        for item in mounted:
            if item.name in proved:
                continue
            for pamt in sorted((root / item.name).glob("*.pamt")):
                progress(f"Reading {item.name}/{pamt.name}...")
                others |= _dds_paths(pamt, stop_event)
        only_cdmw = sorted(owned_dds - others)
        table = parse_pathc(registry.read_bytes())
        present = [path for path in only_cdmw if table.index_of(pathc_checksum(path)) is not None]
        if present and compact:
            blockers.append(
                f"The texture registry ({TEXTURE_REGISTRY}) still lists {len(present)} texture(s) of CDMW's old "
                "overlays on the current game version. Use Steam's Verify integrity of game files first, then "
                "check again.")
        elif present:
            registry_paths = tuple(present)
            registry_after = _without_entries(table, {pathc_checksum(path) for path in present})

    # CDMW's records about overlay installs.
    for relative in OVERLAY_RECORDS:
        if (root / relative).is_file():
            delete.append(relative)
    for relative in (*OVERLAY_RECORD_FOLDERS, VIRTUAL_FOLDER):
        if _is_link(root / relative):
            not_cdmw.append(f"{relative}: a link, left alone")
    for relative in OVERLAY_RECORD_FOLDERS:
        delete += _files_under(root, relative)
        folders += _folders_under(root, relative)

    # The virtual loader.
    runtime, owner_path = root / RUNTIME_PATH, root / RUNTIME_OWNER_PATH
    if runtime.is_file():
        owner = _read_json(owner_path)
        recorded_digest = owner.get("sha256") if owner is not None else None
        actual_digest = _digest(runtime)
        if (owner is not None and owner.get("format") == RUNTIME_OWNER_FORMAT and isinstance(recorded_digest, str)
                and len(recorded_digest) == 64 and actual_digest is not None and recorded_digest == actual_digest):
            delete.append(RUNTIME_PATH)
        else:
            not_cdmw.append(f"{RUNTIME_PATH}: its owner file does not name this exact file, so it is not proven CDMW's")
    virtual = root / VIRTUAL_FOLDER
    if virtual.is_dir() and not _is_link(virtual):
        save_backups = set(_files_under(root, SAVE_BACKUPS))
        delete += [path for path in _files_under(root, VIRTUAL_FOLDER) if path not in save_backups]
        folders += [path for path in _folders_under(root, VIRTUAL_FOLDER)
                    if path != SAVE_BACKUPS and not path.startswith(SAVE_BACKUPS + "/")
                    and not (save_backups and path == VIRTUAL_FOLDER)]
        if save_backups:
            kept.append(f"{SAVE_BACKUPS}: your save backups, kept")
    if (root / BOOTSTRAP_PATH).is_file() and RUNTIME_PATH in delete:
        kept.append(f"{BOOTSTRAP_PATH}: the ASI loader you installed, kept")
    # Everything else in CDMW's own .cdmw folder (decision 46), save backups excepted.
    cdmw = root / CDMW_FOLDER
    if _is_link(cdmw):
        not_cdmw.append(f"{CDMW_FOLDER}: a link, left alone")
    elif cdmw.is_dir():
        save_backups = set(_files_under(root, SAVE_BACKUPS))
        delete += [path for path in _files_under(root, CDMW_FOLDER) if path not in save_backups]
        folders += [path for path in _folders_under(root, CDMW_FOLDER)
                    if path != SAVE_BACKUPS and not path.startswith(SAVE_BACKUPS + "/")
                    and not (save_backups and SAVE_BACKUPS.startswith(path + "/"))]

    delete = list(dict.fromkeys(delete))
    for relative in (*delete, *folders):
        _checked(root, relative)
    folders = sorted(dict.fromkeys(folders), key=lambda value: value.count("/"), reverse=True)
    written = [path for path, data in ((MOUNT_LIST, mount_after), (TEXTURE_REGISTRY, registry_after)) if data is not None]
    observed = tuple((relative, _digest(root / relative)) for relative in (*delete, *written, MOUNT_LIST))
    total = sum((root / relative).stat().st_size for relative in delete if (root / relative).is_file())
    return OldInstallPlan(
        root=root, delete_files=tuple(delete), delete_folders=tuple(folders), overlay_folders=tuple(owned),
        mount_entries=mount_entries, registry_paths=registry_paths, mount_list_after=mount_after,
        registry_after=registry_after, overlay_items=overlay_items if owned else (), not_cdmw=tuple(not_cdmw),
        kept=tuple(kept), blockers=tuple(blockers), observed=tuple(dict.fromkeys(observed)), total_bytes=total,
    )


def _without_entries(table, checksums: set[int]) -> bytes:
    """The registry without ``checksums``; texture headers only they used go too."""

    from cdmw.core.pathc_format import encode_pathc

    kept = [entry for entry in table.entries if entry.checksum not in checksums]
    used = sorted({entry.header_index for entry in kept if entry.is_direct})
    remap = {old: new for new, old in enumerate(used)}
    headers = tuple(table.headers[old] for old in used)
    entries = tuple(replace(entry, header_index=remap[entry.header_index]) if entry.is_direct else entry
                    for entry in kept)
    return encode_pathc(replace(table, headers=headers, entries=entries))


# ----------------------------------------------------------------- removing


def _process_running(image: str) -> bool:
    """Whether ``image`` runs. Raises OSError when Windows cannot say: that is not "closed"."""

    if os.name != "nt":
        return False
    import csv
    import subprocess

    from cdmw.core.common import hidden_subprocess_kwargs

    try:
        done = subprocess.run(["tasklist", "/fo", "csv", "/nh", "/fi", f"IMAGENAME eq {image}"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                              **hidden_subprocess_kwargs())
    except (OSError, subprocess.SubprocessError) as exc:
        raise OSError(f"tasklist did not run: {exc}") from exc
    if done.returncode != 0:
        raise OSError(f"tasklist ended with code {done.returncode}")
    rows = csv.reader(line for line in done.stdout.splitlines() if line.strip() and not line.startswith("INFO:"))
    return any(row and row[0].strip().casefold() == image.casefold() for row in rows)


def default_running_check() -> str:
    """Why removal must wait, or "" when nothing holds the game."""

    try:
        if _process_running(GAME_EXECUTABLE):
            return "Close Crimson Desert first."
        for image in MOD_MANAGER_EXECUTABLES:
            if _process_running(image):
                return f"Close {Path(image).stem} first."
    except OSError as exc:
        return f"CDMW could not check whether Crimson Desert or DMM is running ({exc}). Close them, then check again."
    return ""


def _held(path: Path) -> bool:
    """Whether another program holds ``path`` so it cannot be changed."""

    if not path.is_file():
        return False
    try:
        with path.open("r+b"):
            return False
    except PermissionError:
        return True
    except OSError:
        return True


@archive_write_scope()
def remove_old_install(
    plan: OldInstallPlan,
    *,
    confirmed: bool,
    configured_root: Path | str,
    backup: Callable[[Iterable[Path], str], Path],
    restore_backup: Callable[[Path], object],
    running_check: Optional[Callable[[], str]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> OldInstallRemovalResult:
    """Remove what ``plan`` lists. Backs up first; restores the backup if a step fails."""

    log = on_log or (lambda _text: None)
    if not confirmed:
        raise PermissionError("Removing what an older CDMW installed needs your confirmation.")
    root = plan.root
    if Path(configured_root).expanduser().resolve() != root:
        raise OldInstallRemovalRefused("The game folder changed since the check. Check again.")
    if plan.blockers:
        raise OldInstallRemovalRefused(plan.blockers[0])
    if plan.nothing_found:
        raise OldInstallRemovalRefused("Nothing an older CDMW installed was found.")
    reason = (running_check or default_running_check)()
    if reason:
        raise OldInstallRemovalRefused(reason)
    _recheck(plan, root)
    raise_if_cancelled(stop_event, CANCELLED)
    from cdmw.services.installation_lane import installation_lane

    # recovery=True: an Apply an older CDMW did not finish left a transaction file that
    # blocks every other change; the removal is the way out, and its plan deletes it.
    with installation_lane(root, recovery=True):
        from cdmw.core.protected_roots import game_folder_write_permit

        with game_folder_write_permit("Remove What an Older CDMW Installed"):
            return _remove(plan, root, backup=backup, restore_backup=restore_backup, log=log, stop_event=stop_event,
                           running_check=running_check or default_running_check)


def _recheck(plan, root) -> None:
    """Refuse when a planned file changed or another program holds one. Writes nothing."""

    for relative, expected in plan.observed:
        if _digest(_checked(root, relative)) != expected:
            raise OldInstallRemovalRefused(f"{relative} changed since the check. Check again.")
    held = [relative for relative in (*plan.delete_files, *plan.written_files) if _held(root / relative)]
    if held:
        raise OldInstallRemovalRefused(f"Another program holds {held[0]}. Close it, then check again.")


def _remove(plan, root, *, backup, restore_backup, log, stop_event, running_check):
    from cdmw.core.atomic_file import atomic_write_bytes

    targets = [root / relative for relative in dict.fromkeys((*plan.written_files, *plan.delete_files))
               if (root / relative).is_file()]
    log(f"Backing up {len(targets)} file(s)...")
    backup_dir = Path(backup(targets, "Remove what an older CDMW installed"))
    # Decision 46: the identity registry now lives in the CDMW folder. Carry an older
    # CDMW's copy over before it is removed from the game, unless CDMW already has one.
    legacy = root / LEGACY_REGISTRY
    if LEGACY_REGISTRY in plan.delete_files and legacy.is_file():
        from cdmw.services import game_records

        if not game_records.registry_path(root).is_file():
            game_records.write_registry(root, legacy.read_bytes())
            log("Carried the item identities over to the CDMW folder.")
    if stop_event is not None and stop_event.is_set():
        log("Cancelled before anything was changed; the backup is kept.")
        raise_if_cancelled(stop_event, CANCELLED)
    # The backup can take long: check again right before the first change.
    reason = running_check()
    if reason:
        raise OldInstallRemovalRefused(reason)
    _recheck(plan, root)
    removed: list[str] = []
    try:
        # The mount list and the registry first: an unmounted folder is inert,
        # so the game stays loadable whatever happens after this point.
        for relative, data in ((MOUNT_LIST, plan.mount_list_after), (TEXTURE_REGISTRY, plan.registry_after)):
            if data is not None:
                log(f"Writing {relative}...")
                removed.append(relative)  # before the write: a failure inside it still needs the rollback
                atomic_write_bytes(_checked(root, relative), data)
        for relative in plan.delete_files:
            path = _checked(root, relative)
            if path.is_file():
                removed.append(relative)
                path.unlink()
        leftovers = []
        for relative in plan.delete_folders:
            path = _checked(root, relative)
            try:
                path.rmdir()
            except FileNotFoundError:
                pass
            except OSError:
                if path.exists():
                    leftovers.append(relative)
    except BaseException as failure:
        if not removed:
            raise
        log("A step failed; putting every file back from the backup...")
        try:
            restore_backup(backup_dir)
        except BaseException as restore_failure:
            raise RuntimeError(
                f"{STOPPED_PARTWAY} ({failure}), and putting the files back failed too ({restore_failure}). "
                f"Changed before it stopped: {', '.join(removed)}. Every one of them is in the backup {backup_dir}; "
                "use Restore Backup... to put them back.") from failure
        raise RuntimeError(
            f"{STOPPED_PARTWAY} ({failure}). Everything it had changed ({', '.join(removed)}) was put back from "
            f"the backup {backup_dir}.") from failure
    log(f"Removed {len(removed)} file(s). Backup: {backup_dir}")
    return OldInstallRemovalResult(root, backup_dir, tuple(removed), plan.not_cdmw, plan.kept, tuple(leftovers))


__all__ = [
    "OVERLAY_OWNER_BYTES",
    "OVERLAY_OWNER_MARKER",
    "OldInstallPlan",
    "OldInstallRemovalRefused",
    "OldInstallRemovalResult",
    "default_running_check",
    "find_old_install",
    "is_cdmw_overlay_folder",
    "remove_old_install",
]
