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


class RegistryConflict(ValueError):
    """The older registry in the game folder and the one CDMW keeps cannot be combined."""


def merged_registry(game_root: Path | str) -> bytes | None:
    """The registry to keep once the older copy in the game folder is gone, or None.

    None when the game folder holds no older copy, or CDMW's copy already has
    everything it holds. Without a copy in the CDMW folder, the older file is carried
    over byte for byte. When both exist and differ, the result holds every identity
    either one issued. For an item both hold, CDMW's row is kept: CDMW's copy began
    as the carried-over older one and changed with each send since, so it is the
    newer state of that item. :class:`RegistryConflict` when an item only the older
    copy holds was given a value CDMW's copy gives another item, or when either copy
    cannot be read. Reads only.
    """

    legacy = _legacy_registry(game_root)
    if legacy is None:
        return None
    kept = registry_path(game_root)
    older = legacy.read_bytes()
    if not kept.is_file():
        return older
    if kept.read_bytes() == older:
        return None
    from cdmw.services.independent_item_install import IndependentItemError, _read_registry, _validate_registry
    from cdmw.services.independent_item_package import canonical

    try:
        ours = _read_registry(kept)
    except IndependentItemError as error:
        raise RegistryConflict(f"CDMW's copy of the item identities ({kept}) cannot be read: {error}") from error
    try:
        theirs = _read_registry(legacy)
    except IndependentItemError as error:
        raise RegistryConflict(f"The older item identities in {LEGACY_REGISTRY_PATH} cannot be read: {error}") from error
    if ours["format"] != theirs["format"]:
        raise RegistryConflict(f"The older item identities in {LEGACY_REGISTRY_PATH} are in another format "
                               "than the ones CDMW keeps for this game.")
    items = dict(ours["items"])
    for identity, row in theirs["items"].items():
        items.setdefault(identity, row)
    if len(items) == len(ours["items"]):
        return None
    merged = {"format": ours["format"], "items": items}
    try:
        _validate_registry(merged)
    except IndependentItemError as error:
        raise RegistryConflict(f"The older item identities in {LEGACY_REGISTRY_PATH} and the ones CDMW keeps for "
                               f"this game cannot be combined: {error}") from error
    return canonical(merged)


#: Item packages an older CDMW retained in the game folder, carried over before removal.
RETAINED_PACKAGES_DIRNAME = "retained-packages"


def keep_package_copy(game_root: Path | str, name: str, data: bytes) -> Path | None:
    """Keep ``data`` (an item package from the game folder) in the CDMW folder.

    Returns the new copy, or None when the CDMW folder already holds the same bytes.
    """

    from cdmw.core.atomic_file import atomic_write_bytes

    folder = game_records_folder(game_root) / RETAINED_PACKAGES_DIRNAME
    digest = hashlib.sha256(data).hexdigest()
    try:
        existing = [path for path in folder.iterdir() if path.is_file()] if folder.is_dir() else []
    except OSError:
        existing = []
    for path in existing:
        try:
            if path.stat().st_size == len(data) and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
                return None
        except OSError:
            continue
    plain = Path(name).name
    target = folder / plain
    if target.exists():
        target = folder / f"{Path(plain).stem}-{digest[:12]}{Path(plain).suffix}"
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
    "RETAINED_PACKAGES_DIRNAME",
    "RegistryConflict",
    "game_key",
    "game_records_folder",
    "keep_package_copy",
    "merged_registry",
    "records_root",
    "registry_path",
    "registry_source",
    "write_registry",
]
