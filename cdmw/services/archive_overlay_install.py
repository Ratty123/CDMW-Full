"""Install a mutation plan as an archive directory of its own, leaving the shipped ones
alone.

The patcher route writes the plan's payloads into the archives the game shipped: every
touched `.paz` is backed up whole and re-checksummed, which for one new item is fifteen
files and 0.62 GB. This route writes the same payloads into a new directory beside them and
names that directory first in `meta/0.papgt`, which is where the game looks first. What
gets backed up is then the mount list and the texture registry, both of them under a
kilobyte, and what gets written is a few megabytes that were not there before.

Two things follow from the game taking the first directory that holds a path:

* the overlay has to carry every file the mods before it changed, not only the ones this
  plan touches, or mounting it first would hide them. Everything already in the workbench's
  own overlay is carried forward, and this plan's files replace their namesakes;
* the workbench has to read the archives in the same order the game does, or it would plan
  against a shipped table while the game reads the overlay's. `discover_pamt_files` orders
  its results by the mount list for that reason.
"""

from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional, Sequence, Tuple

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.archive_overlay import OverlayFile, build_overlay_archive
from cdmw.core.papgt_format import PAPGT_DEFAULT_FLAGS, papgt_with_directory, parse_papgt
from cdmw.domain.archives.mutation import ArchiveAddRequest, ArchivePatchRequest
from cdmw.domain.cancellation import raise_if_cancelled

__all__ = [
    "OVERLAY_DIRECTORY_FIRST",
    "OverlayInstallResult",
    "install_overlay",
    "overlay_directory_name",
]

#: Where the workbench's own overlay directory starts looking for a free name. The shipped
#: install ends at 0035, and the game reads a directory only if the mount list names it, so
#: an unmounted 0036 left by something else is not in the way.
OVERLAY_DIRECTORY_FIRST = 36


@dataclass(frozen=True, slots=True)
class OverlayInstallResult:
    """What an overlay install wrote."""

    directory: Path
    pamt_checksum: int
    file_count: int
    payload_bytes: int
    carried_forward: int
    backup_dir: Optional[Path]
    paths: Tuple[str, ...]


def overlay_directory_name(package_root: Path, *, existing: Optional[str] = None) -> str:
    """The directory the workbench's overlay lives in: the one it already mounted, else the
    first four-digit name at or after 0036 that no directory on disk uses."""

    root = Path(package_root)
    if existing and (root / existing).is_dir():
        return existing
    used = {child.name for child in root.iterdir() if child.is_dir()}
    for number in range(OVERLAY_DIRECTORY_FIRST, 10000):
        name = f"{number:04d}"
        if name not in used:
            return name
    raise ValueError("no free archive directory name is left under the package root")


def _processed_payload(payload: bytes, *, compression_type: int, encrypted: bool, basename: str) -> bytes:
    from cdmw.core import archive_patching as patching

    processed = patching._compress_archive_payload(bytes(payload), int(compression_type))
    if encrypted:
        processed = patching._crypt_archive_payload(processed, basename)
    return processed


def _existing_overlay_files(directory: Path) -> Dict[str, OverlayFile]:
    """What the workbench's overlay already holds, keyed by path, ready to carry forward."""

    pamt = directory / "0.pamt"
    paz = directory / "0.paz"
    if not pamt.is_file() or not paz.is_file():
        return {}
    payload = paz.read_bytes()
    out: Dict[str, OverlayFile] = {}
    for entry in parse_archive_pamt(pamt):
        chunk = payload[int(entry.offset) : int(entry.offset) + int(entry.comp_size)]
        if len(chunk) != int(entry.comp_size):
            continue
        out[str(entry.path)] = OverlayFile(path=str(entry.path), payload=chunk, orig_size=int(entry.orig_size), flags=int(entry.flags))
    return out


def install_overlay(
    requests: Sequence[ArchivePatchRequest],
    additions: Sequence[ArchiveAddRequest] = (),
    *,
    package_root: Path,
    meta_files: Iterable[Tuple[str, bytes]] = (),
    directory_name: Optional[str] = None,
    backup: Optional[Callable[[Sequence[Path], str], Path]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> OverlayInstallResult:
    """Write `requests` and `additions` into an overlay directory and mount it first.

    `backup` is handed the files this is about to overwrite and returns where it put them;
    the shipped archives are not among them, because none of them is touched.
    """

    root = Path(package_root)
    papgt_path = root / "meta" / "0.papgt"
    if not papgt_path.is_file():
        raise FileNotFoundError(f"Could not find the archive mount list at {papgt_path}.")
    raise_if_cancelled(stop_event, "Overlay install cancelled before it started.")

    mounted = {item.name for item in parse_papgt(papgt_path.read_bytes())}
    name = directory_name or overlay_directory_name(root, existing=next((item for item in sorted(mounted) if int(item) >= OVERLAY_DIRECTORY_FIRST), None))
    directory = root / name
    carried = _existing_overlay_files(directory)
    if carried and on_log is not None:
        on_log(f"Carrying {len(carried)} file(s) forward from the overlay at {name}.")

    files: Dict[str, OverlayFile] = dict(carried)
    for request in requests:
        raise_if_cancelled(stop_event, "Overlay install cancelled while composing.")
        entry = request.entry
        path = str(entry.path).replace("\\", "/").strip("/")
        payload = _processed_payload(
            request.payload_data,
            compression_type=int(entry.compression_type),
            encrypted=bool(entry.encrypted),
            basename=str(entry.basename),
        )
        files[path] = OverlayFile(path=path, payload=payload, orig_size=len(request.payload_data), flags=int(entry.flags))
    for addition in additions:
        raise_if_cancelled(stop_event, "Overlay install cancelled while composing.")
        path = str(addition.path).replace("\\", "/").strip("/")
        payload = _processed_payload(
            addition.payload_data,
            compression_type=int(addition.compression_type),
            encrypted=bool(addition.encryption_type),
            basename=str(addition.basename),
        )
        files[path] = OverlayFile(path=path, payload=payload, orig_size=len(addition.payload_data), flags=int(addition.flags))
    if not files:
        raise ValueError("An overlay install needs at least one file to write.")

    built = build_overlay_archive(sorted(files.values(), key=lambda item: item.path), on_log=on_log)
    raise_if_cancelled(stop_event, "Overlay install cancelled before writing.")

    metas = [(str(relative), bytes(payload)) for relative, payload in meta_files]
    backup_dir: Optional[Path] = None
    if backup is not None:
        targets = [papgt_path] + [root / relative for relative, _payload in metas]
        targets += [path for path in (directory / "0.pamt", directory / "0.paz") if path.is_file()]
        backup_dir = backup(sorted(set(targets)), f"Mount {name} with {len(files)} overlay file(s)")
        if on_log is not None:
            on_log(f"Backup created: {backup_dir}")

    for relative, _payload in metas:
        remember_overlay_baseline(root, relative)
    directory.mkdir(parents=True, exist_ok=True)
    _write_atomic(directory / "0.paz", built.paz_bytes)
    _write_atomic(directory / "0.pamt", built.pamt_bytes)
    if on_log is not None:
        on_log(f"Wrote {name}/0.pamt and {name}/0.paz: {len(files)} file(s), {len(built.paz_bytes):,} bytes.")
    for relative, payload in metas:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(target, payload)
        if on_log is not None:
            on_log(f"Wrote {relative} ({len(payload):,} bytes).")
    mounted_bytes = papgt_with_directory(papgt_path.read_bytes(), name, built.pamt_checksum, flags=PAPGT_DEFAULT_FLAGS, first=True)
    _write_atomic(papgt_path, mounted_bytes)
    if on_log is not None:
        order = [item.name for item in parse_papgt(mounted_bytes)]
        on_log(f"Mounted {name} first in meta/0.papgt ({len(order)} directories, {order[0]} then {order[1]}).")
    return OverlayInstallResult(
        directory=directory,
        pamt_checksum=built.pamt_checksum,
        file_count=len(files),
        payload_bytes=len(built.paz_bytes),
        carried_forward=len(carried),
        backup_dir=backup_dir,
        paths=tuple(sorted(files)),
    )


def overlay_baseline_dir(package_root: Path) -> Path:
    """Where the workbench keeps the loose files an overlay overwrote, per install.

    `meta/0.pathc` is a loose file beside the archives rather than an entry inside one, so
    an overlay has nowhere to write it except in place, and removing the overlay has to put
    it back. The copy has to be the one from before the overlay existed: the workbench's
    own backup folders are not that, since the oldest of them is only as old as the first
    time this workbench touched the file, which may already have been a modified one.
    """

    import hashlib

    from cdmw.core.archive_patching import ARCHIVE_PATCH_BACKUP_ROOT

    fingerprint = hashlib.sha256(str(Path(package_root).resolve()).lower().encode("utf-8")).hexdigest()[:16]
    return Path(ARCHIVE_PATCH_BACKUP_ROOT).parent / "overlay_baseline" / fingerprint


def remember_overlay_baseline(package_root: Path, relative: str) -> Optional[Path]:
    """Keep the file at `relative` as it is now, unless it is already kept. First write
    wins: what matters is the state before the overlay, not before the latest install."""

    root = Path(package_root)
    source = root / relative
    target = overlay_baseline_dir(root) / relative
    if target.is_file() or not source.is_file():
        return target if target.is_file() else None
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(target, source.read_bytes())
    return target


def overlay_baseline_files(package_root: Path) -> Dict[str, Path]:
    """`{path relative to the package root: the copy from before the overlay}`."""

    base = overlay_baseline_dir(package_root)
    if not base.is_dir():
        return {}
    return {
        path.relative_to(base).as_posix(): path
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def forget_overlay_baseline(package_root: Path) -> None:
    """Drop the kept copies; the overlay they belonged to is gone."""

    import shutil

    shutil.rmtree(overlay_baseline_dir(package_root), ignore_errors=True)


def _write_atomic(path: Path, payload: bytes) -> None:
    """Write beside the target and move it into place, so a half-written archive never is."""

    temporary = path.with_suffix(path.suffix + ".cdmw_new")
    temporary.write_bytes(payload)
    temporary.replace(path)
