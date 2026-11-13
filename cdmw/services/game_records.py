"""What CDMW keeps about one game installation, in the CDMW folder (decision 46).

CDMW used to keep the item identity registry in ``<game>/.cdmw/independent-items.json``.
Everything CDMW keeps for itself now lives in the CDMW folder, under
``workspace/game-records/<key>/``, where ``<key>`` is derived from the game folder's
resolved path, so two game folders never share one registry.

An older CDMW's file in the game folder is read in its place until CDMW next records
identities, which writes the carried-over registry into the CDMW folder; this module
never writes, renames or deletes anything in the game folder. Browse Archives' Remove What an Older CDMW Installed... lists that old folder,
which is CDMW's own, and offers to remove it.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

RECORDS_DIRNAME = "game-records"
REGISTRY_FILE = "independent-items.json"
#: Where an older CDMW kept the registry, relative to the game folder. Read only.
LEGACY_REGISTRY_PATH = ".cdmw/independent-items.json"
_ABOUT_FILE = "game.json"


def game_key(game_root: Path | str) -> str:
    resolved = Path(os.path.abspath(Path(game_root).expanduser())).resolve(strict=False)
    return hashlib.sha256(os.path.normcase(str(resolved)).encode("utf-8")).hexdigest()[:24]


def records_root() -> Path:
    from cdmw.app.app_folder import workspace_folder

    return workspace_folder() / RECORDS_DIRNAME


def game_records_folder(game_root: Path | str) -> Path:
    """``workspace/game-records/<key>`` for this game folder (not created here)."""

    return records_root() / game_key(game_root)


def _legacy_registry(game_root: Path | str) -> Path | None:
    root = Path(game_root).resolve()
    path = root / LEGACY_REGISTRY_PATH
    try:
        if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
            return None
        path.resolve().relative_to(root)
    except (OSError, ValueError):
        return None
    return path


def registry_path(game_root: Path | str) -> Path:
    """Where CDMW keeps the identity registry for ``game_root`` (it may not exist yet)."""

    return game_records_folder(game_root) / REGISTRY_FILE


def registry_source(game_root: Path | str) -> Path | None:
    """The registry file to read for ``game_root``, or None when there is none.

    The record in the CDMW folder when it exists. Until it does, an older CDMW's file
    in the game folder is read in its place; the first :func:`write_registry` carries
    its content over (the caller writes what it read, plus its changes). Nothing here
    writes, and the game folder's copy is never written, renamed or deleted.
    """

    target = registry_path(game_root)
    if target.is_file():
        return target
    return _legacy_registry(game_root)


def write_registry(game_root: Path | str, data: bytes) -> Path:
    """Write the identity registry for ``game_root`` into the CDMW folder."""

    from cdmw.core.atomic_file import atomic_write_bytes

    target = game_records_folder(game_root) / REGISTRY_FILE
    if target.is_file() and target.read_bytes() == data:
        return target
    atomic_write_bytes(target, data)
    _describe(game_root)
    return target


def _describe(game_root: Path | str) -> None:
    """A note beside the records saying which game folder they belong to."""

    from cdmw.core.atomic_file import atomic_write_text

    about = game_records_folder(game_root) / _ABOUT_FILE
    text = json.dumps({"format": "cdmw_game_records_v1", "game_folder": str(Path(game_root).resolve())},
                      indent=2) + "\n"
    try:
        if not about.is_file() or about.read_text(encoding="utf-8") != text:
            atomic_write_text(about, text)
    except OSError:
        pass


__all__ = [
    "LEGACY_REGISTRY_PATH",
    "REGISTRY_FILE",
    "game_key",
    "game_records_folder",
    "records_root",
    "registry_path",
    "registry_source",
    "write_registry",
]
