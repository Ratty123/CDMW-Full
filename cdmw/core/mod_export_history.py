"""Keep CDMW authoring records outside distributable mod packages.

History is bound to the package's payload bytes, so renaming or copying a mod
on this computer retains its history while edited payloads cannot reuse it.
Mod managers read every file a package ships (DMM parses every `.json`), so
records are filed here when they are written and never placed in the package.

The key covers payload files in sub-folders (archive groups, `meta/`, game
paths); top-level files are manager metadata such as `manifest.json`, which
exports write last. Packages filed under the earlier key, which also covered
top-level files, are still found.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import zipfile

from cdmw.constants import APP_NAME
from cdmw.core.atomic_file import atomic_publish_directory
from cdmw.domain.cancellation import raise_if_cancelled


HISTORY_FILES = ("new-item.json", "cdmw-compatibility.json", "cdmw-baseline.zip")
_AUTHORING_FILES = (*HISTORY_FILES, "mesh-editor-session.json")
_PACKAGE_METADATA = {*_AUTHORING_FILES, "README.txt", "meta/0.papgt"}


def _history_root() -> Path:
    local = os.environ.get("LOCALAPPDATA", "").strip()
    return (Path(local) if local else Path.home() / ".local" / "share") / APP_NAME / "mod_export_history"


def _package_history_directory(root: Path, *, stop_event=None, legacy: bool = False) -> Path | None:
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
        if not path.is_file() or relative in ignored or (not legacy and "/" not in relative):
            continue
        records.append((relative, hash_file(path, stop_event)))
    return _records_directory(records)


def _records_directory(records) -> Path | None:
    if not records:
        return None
    key = hashlib.sha256(json.dumps(sorted(records), separators=(",", ":")).encode("utf-8")).hexdigest()
    return _history_root() / key


def archive_history_directory(path: Path, *, stop_event=None) -> Path | None:
    """The history folder of a ZIP made from a package, found from its members' bytes.

    Members may sit at the ZIP root or under one wrapping folder.
    """
    ignored = {name.casefold() for name in _PACKAGE_METADATA}
    with zipfile.ZipFile(path) as package:
        infos = [info for info in package.infolist() if not info.is_dir()]
        names = [info.filename.replace("\\", "/") for info in infos]
        prefixes = [""]
        tops = {name.split("/", 1)[0] for name in names}
        if len(tops) == 1 and all("/" in name for name in names):
            prefixes.append(next(iter(tops)) + "/")
        hashes: dict[str, str] = {}
        for prefix in prefixes:
            for legacy in (False, True):
                records = []
                for info, name in zip(infos, names):
                    if not name.startswith(prefix):
                        continue
                    relative = name[len(prefix):].casefold()
                    if relative in ignored or (not legacy and "/" not in relative):
                        continue
                    if name not in hashes:
                        hasher = hashlib.sha256()
                        with package.open(info) as stream:
                            while chunk := stream.read(1024 * 1024):
                                raise_if_cancelled(stop_event, "Mod history lookup cancelled.")
                                hasher.update(chunk)
                        hashes[name] = hasher.hexdigest()
                    records.append((relative, hashes[name]))
                directory = _records_directory(records)
                if directory is not None and directory.is_dir():
                    return directory
    return None


def mod_metadata_path(root: Path, name: str, *, stop_event=None) -> Path:
    """Prefer legacy inline records, otherwise find history for these exact bytes."""
    if name not in _AUTHORING_FILES:
        raise ValueError(f"Not a CDMW history file: {name}")
    inline = Path(root) / name
    if inline.exists() or inline.is_symlink() or not _history_root().is_dir():
        return inline
    for legacy in (False, True):
        directory = _package_history_directory(root, stop_event=stop_event, legacy=legacy)
        if directory is not None and (directory / name).is_file():
            return directory / name
    return inline


def _record_limit(name: str) -> int:
    return 520 * 1024 * 1024 if name.endswith(".zip") else 8 * 1024 * 1024


def file_mod_history(root: Path, records, *, stop_event=None) -> Path | None:
    """File authoring records for the package at `root` in CDMW's history.

    `records` maps a record name to bytes or to a file to copy. Records already
    filed for the same payload bytes are kept unless replaced. Nothing is written
    into the package. Returns the history folder, or None for a package with no
    payload files to bind the records to.
    """
    root = Path(root).resolve()
    records = dict(records)
    for name in records:
        if name not in _AUTHORING_FILES:
            raise ValueError(f"Not a CDMW history file: {name}")
    destination = _package_history_directory(root, stop_event=stop_event)
    if destination is None:
        return None
    destination = destination.resolve()
    if _history_root().resolve().is_relative_to(root) or root.is_relative_to(_history_root().resolve()):
        raise ValueError("The mod export must be outside CDMW's local history folder.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".history-", dir=destination.parent)).resolve()
    try:
        if destination.is_dir():
            for kept in destination.iterdir():
                if kept.is_file() and kept.name in _AUTHORING_FILES and kept.name not in records:
                    shutil.copyfile(kept, staging / kept.name)
        for name, source in records.items():
            if isinstance(source, (bytes, bytearray, memoryview)):
                if len(source) > _record_limit(name):
                    raise ValueError(f"Oversized mod history record: {name}")
                (staging / name).write_bytes(bytes(source))
                continue
            source = Path(source)
            if source.is_symlink() or not source.is_file() or source.stat().st_size > _record_limit(name):
                raise ValueError(f"Invalid or oversized mod history file: {source}")
            with source.open("rb") as reader, (staging / name).open("wb") as writer:
                while data := reader.read(1024 * 1024):
                    raise_if_cancelled(stop_event, "Mod history save cancelled.")
                    writer.write(data)
        raise_if_cancelled(stop_event, "Mod history save cancelled.")
        atomic_publish_directory(staging, destination)
    finally:
        if staging.exists() and staging.is_relative_to(destination.parent):
            shutil.rmtree(staging)
    return destination


def retain_mod_history(root: Path, *, stop_event=None) -> tuple[str, ...]:
    """Save authoring records before removing them and the manager-owned mount list."""
    root = Path(root).resolve()
    sources = {name: root / name for name in _AUTHORING_FILES if (root / name).exists()}
    if sources and file_mod_history(root, sources, stop_event=stop_event) is None:
        raise ValueError("Cannot retain mod history without package payloads.")
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
