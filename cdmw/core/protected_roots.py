"""The configured game folder is a protected root: CDMW's writers refuse paths inside it (decision 46).

CDMW never writes into the game installation. Everything it keeps for itself lives
in the CDMW folder. This module makes that hold by construction rather than by a
list of known writers: the game folder is registered here when it is configured,
and the shared file-writing helpers (``cdmw.core.atomic_file``) call
:func:`check_writable` before they create anything. A path that resolves inside a
protected root is refused with :class:`ProtectedGameFolderWrite`.

The only callers that may write there hold :func:`game_folder_write_permit`:
Browse Archives' Restore Backup... and Remove What an Older CDMW Installed....
The permit lives in a context variable, so it covers the worker thread that opens
it and nothing else.
"""

from __future__ import annotations

import contextvars
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

#: Who may hold the permit, by the name the user sees.
PERMIT_HOLDERS = frozenset({"Restore Backup", "Remove What an Older CDMW Installed"})

_lock = threading.Lock()
_roots: dict[str, Path] = {}
_permit: contextvars.ContextVar[str | None] = contextvars.ContextVar("cdmw_game_folder_write_permit", default=None)


class ProtectedGameFolderWrite(PermissionError):
    """A CDMW writer was asked to write inside the configured game folder."""


def _resolved(path: Path | str) -> Path | None:
    try:
        return Path(os.path.abspath(Path(path).expanduser())).resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None


def _key(path: Path) -> str:
    return os.path.normcase(str(path))


def set_configured_game_root(path: Path | str | None) -> Path | None:
    """Protect ``path`` as the configured game folder, replacing the previous one.

    An empty value, or a folder that does not exist, clears it: a folder that is not
    there cannot be written into by accident, and the next configuration sets it.
    """

    resolved = _resolved(path) if path is not None and str(path).strip() else None
    with _lock:
        _roots.pop("configured", None)
        if resolved is not None and resolved.is_dir():
            _roots["configured"] = resolved
            return resolved
    return None


def protect_root(name: str, path: Path | str) -> None:
    """Protect another game folder under ``name`` (a test, or a second configured install)."""

    resolved = _resolved(path)
    if resolved is not None:
        with _lock:
            _roots[str(name)] = resolved


def release_root(name: str) -> None:
    with _lock:
        _roots.pop(str(name), None)


def protected_roots() -> tuple[Path, ...]:
    with _lock:
        return tuple(_roots.values())


def protecting_root(path: Path | str) -> Path | None:
    """The protected root ``path`` lies inside, or None."""

    resolved = _resolved(path)
    if resolved is None:
        return None
    target = _key(resolved)
    for root in protected_roots():
        prefix = _key(root)
        if target == prefix or target.startswith(prefix.rstrip("\\/") + os.sep):
            return root
    return None


def check_writable(path: Path | str) -> None:
    """Refuse to write ``path`` when it lies inside a protected game folder without the permit."""

    root = protecting_root(path)
    if root is not None and _permit.get() is None:
        raise ProtectedGameFolderWrite(
            f"CDMW does not write into the game folder ({root}); it refused {path}. "
            "Everything CDMW keeps for itself lives in the CDMW folder.")


@contextmanager
def game_folder_write_permit(holder: str) -> Iterator[None]:
    """Allow CDMW's writers into the game folder for one confirmed action."""

    if holder not in PERMIT_HOLDERS:
        raise ProtectedGameFolderWrite(f"{holder!r} may not write into the game folder.")
    token = _permit.set(holder)
    try:
        yield
    finally:
        _permit.reset(token)


__all__ = [
    "PERMIT_HOLDERS",
    "ProtectedGameFolderWrite",
    "check_writable",
    "game_folder_write_permit",
    "protect_root",
    "protected_roots",
    "protecting_root",
    "release_root",
    "set_configured_game_root",
]
