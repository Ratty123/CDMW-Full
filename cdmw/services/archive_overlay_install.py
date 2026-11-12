"""Read helpers for the archive-group overlays an older CDMW installed.

CDMW no longer installs into the game (decision 39). The install code moved to
tests/support; Browse Archives' Remove What an Older CDMW Installed... takes an
old install out. Nothing here writes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from cdmw.core.papgt_format import read_papgt_directories

__all__ = [
    "OVERLAY_DIRECTORY_FIRST",
    "OVERLAY_OWNER_MARKER",
    "OVERLAY_OWNER_BYTES",
    "is_cdmw_overlay_directory",
    "overlay_directory_name",
]

#: Where the workbench's own overlay directory starts looking for a free name. The shipped
#: install ends at 0035, and the game reads a directory only if the mount list names it, so
#: an unmounted 0036 left by something else is not in the way.
OVERLAY_DIRECTORY_FIRST = 36
OVERLAY_OWNER_MARKER = ".cdmw-new-item-overlay"
OVERLAY_OWNER_BYTES = b"CDMW New Item Studio overlay v1\n"


def is_cdmw_overlay_directory(directory: Path) -> bool:
    """Whether ``directory`` carries the exact marker written by this installer."""

    marker = Path(directory) / OVERLAY_OWNER_MARKER
    try:
        return marker.is_file() and marker.read_bytes() == OVERLAY_OWNER_BYTES
    except OSError:
        return False


def overlay_directory_name(package_root: Path, *, existing: Optional[str] = None) -> str:
    """The directory the workbench's overlay lives in: the one it already mounted, else the
    first free four-digit name not reserved on disk or in the game's mount list."""

    root = Path(package_root)
    if existing and is_cdmw_overlay_directory(root / existing):
        return existing
    used = {child.name for child in root.iterdir() if child.is_dir()}
    mount_list = root / "meta" / "0.papgt"
    if mount_list.is_file():
        used.update(item.name for item in read_papgt_directories(mount_list.read_bytes()))
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


