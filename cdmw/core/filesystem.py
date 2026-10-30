"""Native filesystem paths for internal file I/O."""

from __future__ import annotations

import os
from pathlib import Path


def filesystem_path(path: Path | str) -> Path:
    """Allow Windows file I/O beyond MAX_PATH without a machine-wide policy.

    Normalize before adding the extended prefix, which disables Win32's own
    slash/dot normalization. Keep logical paths in settings and cache identities.
    """
    if os.name != "nt":
        return Path(path)
    value = os.fspath(path)
    if value.startswith(("\\\\?\\", "\\\\.\\")):
        return Path(value)
    value = os.path.abspath(value)
    if value.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + value[2:])
    return Path("\\\\?\\" + value)
