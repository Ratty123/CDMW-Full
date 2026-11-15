"""Folders deeper than MAX_PATH for the native long-path tests (2026-11-13).

Windows refuses a path over 260 characters without the extended-length prefix
unless long paths are switched on for the machine, which no test may change.
The helpers here build such folders through the prefix, so the test itself
does not depend on that setting; the programs under test get the plain path.
"""

from __future__ import annotations

import os
from pathlib import Path

LONG_PATH_LENGTH = 300


def extended(path: Path | str) -> str:
    """The extended-length form of an absolute path, for Python's own file calls."""

    text = os.path.abspath(str(path))
    if os.name != "nt" or text.startswith("\\\\?\\"):
        return text
    if text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + text[2:]
    return "\\\\?\\" + text


def long_folder(root: Path, *, length: int = LONG_PATH_LENGTH) -> Path:
    """A folder under root whose path is at least ``length`` characters long."""

    folder = Path(os.path.abspath(str(root)))
    index = 0
    while len(str(folder)) < length:
        folder = folder / f"deep-folder-{index:02d}-{'x' * 24}"
        index += 1
    os.makedirs(extended(folder), exist_ok=True)
    assert len(str(folder)) >= length
    return folder


def write_bytes(path: Path, data: bytes) -> None:
    os.makedirs(extended(path.parent), exist_ok=True)
    with open(extended(path), "wb") as stream:
        stream.write(data)


def read_bytes(path: Path) -> bytes:
    with open(extended(path), "rb") as stream:
        return stream.read()


def exists(path: Path) -> bool:
    return os.path.exists(extended(path))
