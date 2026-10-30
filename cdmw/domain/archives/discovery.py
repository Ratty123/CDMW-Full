"""Folder exclusions shared by archive discovery and its settings editor."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import PurePath


BUILTIN_IGNORED_ARCHIVE_FOLDERS = (
    "cdmods", "backups", ".cdmw", "crimsonforge_backups",
    "dmmsa", "dmmgen", "CrimsonFastLoad.backup",
    ".CrimsonModsCache", "bin64/.CrimsonModsCache",
)
ARCHIVE_IGNORED_FOLDERS_SETTING = "archive/ignored_folders"
ARCHIVE_IGNORED_FOLDERS_OVERRIDE_SETTING = "archive/ignored_folders_override"


def suggested_archive_exclusion(package_root: str, source_path: str) -> str | None:
    """Suggest only a known mod/backup subtree from an exact, in-root source."""
    root, source = PurePath(package_root), PurePath(source_path)
    if not root.is_absolute() or not source.is_absolute() or ".." in root.parts or ".." in source.parts:
        return None
    try:
        relative = source.relative_to(root)
    except ValueError:
        return None
    if relative.suffix.casefold() != ".pamt":
        return None
    ancestors = {parent.as_posix().casefold() for parent in relative.parents}
    return next((folder for folder in BUILTIN_IGNORED_ARCHIVE_FOLDERS if folder.casefold() in ancestors), None)


def normalize_ignored_archive_folders(values: Iterable[str]) -> tuple[str, ...]:
    result: dict[str, str] = {}
    for value in values:
        path = str(value).strip().replace("\\", "/").rstrip("/")
        parts = path.split("/")
        if (not path or any(part in {"", ".", ".."} for part in parts)
                or any(ord(char) < 32 or char in '<>:"|?*' for char in path)):
            raise ValueError("Enter a folder path relative to the game folder, without wildcards or '..'.")
        result.setdefault(path.casefold(), path)
    return tuple(result.values())
