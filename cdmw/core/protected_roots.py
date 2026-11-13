"""Game folders are protected roots: CDMW's writers refuse them (decision 46).

CDMW never writes into the game installation. Everything it keeps for itself lives
in the CDMW folder. This module makes that hold by construction rather than by a
list of known writers. The shared file-writing helpers (``cdmw.core.atomic_file``)
call :func:`check_writable` before they create anything, and again right before
they move anything into place. Code that deletes, clears or replaces a folder
calls :func:`check_removable` first. A refused path raises
:class:`ProtectedGameFolderWrite`.

A path is in a game folder when:

* it lies inside a protected root: every game folder configured or detected this
  session (:func:`add_game_root`); roots are never removed while CDMW runs, so
  changing the game folder field leaves the previous one protected;
* or it lies inside a game installation, configured or not: a folder that holds
  ``meta/0.papgt`` together with ``bin64/CrimsonDesert.exe`` or the shipped
  ``0000`` archive group (:func:`installation_holding`). This rule needs no state,
  so it holds in every process, child processes included. ``meta/0.papgt`` alone is
  not enough: the archive-style mods CDMW writes for DMM hold their own.

Child processes inherit the session's roots through :data:`ROOTS_ENVIRONMENT`;
``cdmw.app.bootstrap`` adopts them before any helper mode starts.

The only callers that may write inside a game folder hold
:func:`game_folder_write_permit`: Browse Archives' Restore Backup... and Remove What
an Older CDMW Installed.... The permit lives in a context variable, so it covers the
worker thread that opens it and nothing else. No permit allows deleting, clearing
or replacing a game folder itself or a folder that holds one.
"""

from __future__ import annotations

import contextvars
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from cdmw.domain.output_paths import GAME_INDEX

#: Who may hold the permit, by the name the user sees.
PERMIT_HOLDERS = frozenset({"Restore Backup", "Remove What an Older CDMW Installed"})
#: Beside ``meta/0.papgt``, either of these marks a game installation rather than a mod.
INSTALLATION_MARKS = (Path("bin64") / "CrimsonDesert.exe", Path("0000") / "0.pamt")
#: The session's roots, as a JSON list, for child processes.
ROOTS_ENVIRONMENT = "CDMW_PROTECTED_GAME_ROOTS"

_lock = threading.Lock()
_roots: dict[str, Path] = {}
_permit: contextvars.ContextVar[str | None] = contextvars.ContextVar("cdmw_game_folder_write_permit", default=None)


class ProtectedGameFolderWrite(PermissionError):
    """A CDMW writer was asked to write into, clear or replace a game folder."""


def _plain(text: str) -> str:
    # \\?\C:\... and \\?\UNC\server\share\... name the same files as C:\... and
    # \\server\share\...; compare them in the plain form.
    if text.startswith("\\\\?\\UNC\\"):
        return "\\\\" + text[8:]
    if text.startswith("\\\\?\\"):
        return text[4:]
    return text


def _resolved(path: Path | str) -> Path | None:
    try:
        text = _plain(os.fspath(path))
        return Path(_plain(str(Path(os.path.abspath(Path(text).expanduser())).resolve(strict=False))))
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _inside(path: Path, folder: Path) -> bool:
    inner, outer = _key(path), _key(folder)
    return inner == outer or inner.startswith(outer.rstrip("\\/") + os.sep)


def _is_drive_root(path: Path) -> bool:
    return path.parent == path


def looks_like_game_folder(path: Path | str) -> bool:
    """Whether ``path`` holds the game's archive index (``meta/0.papgt``), itself or in ``game_files``."""

    resolved = _resolved(path)
    try:
        return resolved is not None and any(
            (folder / GAME_INDEX).is_file() for folder in (resolved, resolved / "game_files"))
    except OSError:
        return False


def _publish_to_children() -> None:
    # Called with the lock held. Children made with the default environment inherit it.
    os.environ[ROOTS_ENVIRONMENT] = json.dumps(sorted(str(root) for root in _roots.values()))


def add_game_root(path: Path | str | None) -> Path | None:
    """Protect a configured or detected game folder for the rest of the session.

    Only a folder that holds ``meta/0.papgt`` (or ``game_files/meta/0.papgt``) is
    added, and never a drive root, so a half-typed value protects nothing it should not. A root is never removed while
    CDMW runs. Returns the root, or None when nothing was added.
    """

    if path is None or not str(path).strip():
        return None
    resolved = _resolved(path)
    if resolved is None or _is_drive_root(resolved) or not looks_like_game_folder(resolved):
        return None
    with _lock:
        _roots.setdefault(_key(resolved), resolved)
        _publish_to_children()
    return resolved


#: Browse's game folder field calls this when editing finishes. It adds; it never
#: replaces or clears (the name is kept for the callers and tests that use it).
set_configured_game_root = add_game_root


def adopt_environment() -> tuple[Path, ...]:
    """Protect the roots the parent process passed down (a helper mode or --cli)."""

    try:
        values = json.loads(os.environ.get(ROOTS_ENVIRONMENT) or "[]")
    except ValueError:
        values = []
    if isinstance(values, list):
        for value in values:
            if isinstance(value, str):
                add_game_root(value)
    return protected_roots()


def protected_roots() -> tuple[Path, ...]:
    with _lock:
        return tuple(_roots.values())


def _reset_for_tests() -> None:
    with _lock:
        _roots.clear()
        os.environ.pop(ROOTS_ENVIRONMENT, None)


def game_folder_of(path: Path | str) -> Path | None:
    """The game folder ``path`` lies in (a protected root or a game installation), or None."""

    resolved = _resolved(path)
    if resolved is None:
        return None
    return _game_folder_of(resolved)


def installation_holding(path: Path) -> Path | None:
    """The nearest folder at or above ``path`` that is a game installation, or None."""

    for folder in (path, *path.parents):
        try:
            if (folder / GAME_INDEX).is_file() and any((folder / mark).is_file() for mark in INSTALLATION_MARKS):
                return folder
        except OSError:
            continue
    return None


def _game_folder_of(resolved: Path) -> Path | None:
    for root in protected_roots():
        if _inside(resolved, root):
            return root
    return installation_holding(resolved)


def _refuse(message: str) -> None:
    raise ProtectedGameFolderWrite(message + " Everything CDMW keeps for itself lives in the CDMW folder.")


def check_writable(path: Path | str) -> None:
    """Refuse to write ``path`` when it lies in a game folder and the caller has no permit.

    A path CDMW cannot resolve is refused too: the check fails closed.
    """

    resolved = _resolved(path)
    if resolved is None:
        _refuse(f"CDMW could not tell whether {path} lies in the game folder, so it did not write there.")
    root = _game_folder_of(resolved)
    if root is not None and _permit.get() is None:
        _refuse(f"CDMW does not write into the game folder ({root}); it refused {path}.")


def check_removable(path: Path | str) -> None:
    """Refuse to delete, clear or replace ``path`` when that would remove game files.

    Refused: a drive root, a path in a game folder (without the permit), a game
    folder itself, and a folder that holds a protected root, whatever permit is held.
    """

    resolved = _resolved(path)
    if resolved is None:
        _refuse(f"CDMW could not tell whether {path} holds the game folder, so it did not remove it.")
    if _is_drive_root(resolved):
        _refuse(f"CDMW does not clear or replace a whole drive ({resolved}).")
    for root in protected_roots():
        if _inside(root, resolved):
            _refuse(f"CDMW does not clear or replace {path}: it holds the game folder ({root}).")
    root = _game_folder_of(resolved)
    if root is not None and (_key(root) == _key(resolved) or _permit.get() is None):
        _refuse(f"CDMW does not write into the game folder ({root}), or clear or replace anything in it; "
                f"it refused {path}.")


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
    "ROOTS_ENVIRONMENT",
    "ProtectedGameFolderWrite",
    "add_game_root",
    "adopt_environment",
    "check_removable",
    "check_writable",
    "game_folder_of",
    "game_folder_write_permit",
    "installation_holding",
    "looks_like_game_folder",
    "protected_roots",
    "set_configured_game_root",
]
