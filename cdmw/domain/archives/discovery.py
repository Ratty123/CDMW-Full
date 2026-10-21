"""Folder exclusions shared by archive discovery and its settings editor."""

from __future__ import annotations

from collections.abc import Iterable


BUILTIN_IGNORED_ARCHIVE_FOLDERS = (
    "cdmods", "backups", ".cdmw", "crimsonforge_backups",
    "dmmsa", "dmmgen", "CrimsonFastLoad.backup",
)
ARCHIVE_IGNORED_FOLDERS_SETTING = "archive/ignored_folders"
ARCHIVE_IGNORED_FOLDERS_OVERRIDE_SETTING = "archive/ignored_folders_override"


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
