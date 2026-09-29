"""Keep CDMW authoring records outside distributable mod packages.

History is bound to the package's payload bytes, so renaming or copying a mod
on this computer retains its history while edited payloads cannot reuse it.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from cdmw.constants import APP_NAME
from cdmw.core.atomic_file import atomic_publish_directory
from cdmw.domain.cancellation import raise_if_cancelled


HISTORY_FILES = ("new-item.json", "cdmw-compatibility.json", "cdmw-baseline.zip")
_AUTHORING_FILES = (*HISTORY_FILES, "mesh-editor-session.json")
_PACKAGE_METADATA = {*_AUTHORING_FILES, "README.txt", "meta/0.papgt"}


def _history_root() -> Path:
    local = os.environ.get("LOCALAPPDATA", "").strip()
    return (Path(local) if local else Path.home() / ".local" / "share") / APP_NAME / "mod_export_history"


def _package_history_directory(root: Path, *, stop_event=None) -> Path | None:
    from cdmw.core.mod_compatibility import hash_file

    root = Path(root).resolve()
    if not root.is_dir():
        return None
    ignored = {name.casefold() for name in _PACKAGE_METADATA}
    records = []
    for path in sorted(root.rglob("*")):
        raise_if_cancelled(stop_event, "Mod history lookup cancelled.")
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError(f"Mod history cannot follow a linked package path: {path}")
        relative = path.relative_to(root).as_posix().casefold()
        if path.is_file() and relative not in ignored:
            records.append((relative, hash_file(path, stop_event)))
    if not records:
        return None
    key = hashlib.sha256(json.dumps(sorted(records), separators=(",", ":")).encode("utf-8")).hexdigest()
    return _history_root() / key


def mod_metadata_path(root: Path, name: str, *, stop_event=None) -> Path:
    """Prefer legacy inline records, otherwise find history for these exact bytes."""
    if name not in _AUTHORING_FILES:
        raise ValueError(f"Not a CDMW history file: {name}")
    inline = Path(root) / name
    if inline.exists() or inline.is_symlink() or not _history_root().is_dir():
        return inline
    directory = _package_history_directory(root, stop_event=stop_event)
    return directory / name if directory is not None and (directory / name).is_file() else inline


def retain_mod_history(root: Path, *, stop_event=None) -> tuple[str, ...]:
    """Save authoring records before removing them and the manager-owned mount list."""
    root = Path(root).resolve()
    sources = [root / name for name in _AUTHORING_FILES if (root / name).exists()]
    if sources:
        destination = _package_history_directory(root, stop_event=stop_event)
        if destination is None:
            raise ValueError("Cannot retain mod history without package payloads.")
        destination = destination.resolve()
        if _history_root().resolve().is_relative_to(root) or root.is_relative_to(_history_root().resolve()):
            raise ValueError("The mod export must be outside CDMW's local history folder.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".history-", dir=destination.parent)).resolve()
        try:
            for source in sources:
                limit = 520 * 1024 * 1024 if source.suffix == ".zip" else 8 * 1024 * 1024
                if source.is_symlink() or not source.is_file() or source.stat().st_size > limit:
                    raise ValueError(f"Invalid or oversized mod history file: {source}")
                with source.open("rb") as reader, (staging / source.name).open("wb") as writer:
                    while data := reader.read(1024 * 1024):
                        raise_if_cancelled(stop_event, "Mod history save cancelled.")
                        writer.write(data)
            raise_if_cancelled(stop_event, "Mod history save cancelled.")
            atomic_publish_directory(staging, destination)
        finally:
            if staging.exists() and staging.is_relative_to(destination.parent):
                shutil.rmtree(staging)
    raise_if_cancelled(stop_event, "Mod history save cancelled.")
    removed = []
    for name in (*_AUTHORING_FILES, "meta/0.papgt"):
        path = root / name
        if path.exists():
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError(f"Mod history cannot remove a linked package path: {path}")
            path.unlink()
            removed.append(name)
    meta = root / "meta"
    if meta.is_dir() and not any(meta.iterdir()):
        meta.rmdir()
    return tuple(removed)


def retain_dmm_history(root: Path, *, stop_event=None) -> tuple[str, ...]:
    """Compatibility entry point for the existing DMM export workflow."""
    return retain_mod_history(root, stop_event=stop_event)
