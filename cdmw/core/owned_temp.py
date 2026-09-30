"""Marked temporary directories whose live owner holds a filesystem lock."""

from __future__ import annotations

import atexit
import json
import logging
import os
from pathlib import Path
import shutil
import stat
import tempfile
import threading
import time
from uuid import uuid4

from cdmw.constants import APP_NAME

OWNER_MARKER = ".cdmw-owned-temp.json"
OWNER_SCHEMA = "cdmw_owned_temp_v1"
RETIRED_PREFIX = ".cdmw-retired-temp-"
MIN_ABANDONED_AGE_SECONDS = 1800.0
_owners: dict[Path, object] = {}
_retiring: set[Path] = set()
_lock = threading.RLock()
_logger = logging.getLogger(__name__)


def _is_link(path: Path) -> bool:
    attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    return path.is_symlink() or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _file_lock(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _identity(path: Path) -> tuple[int, int]:
    info = path.stat()
    return int(info.st_dev), int(info.st_ino)


def _read_owner(root: Path, handle) -> dict:
    if _is_link(root) or root.resolve() != root.absolute():
        raise ValueError("Temporary directory was redirected.")
    handle.seek(0)
    payload = json.loads(handle.read(4097))
    if not isinstance(payload, dict) or payload.get("schema") != OWNER_SCHEMA or payload.get("app") != APP_NAME:
        raise ValueError("Temporary directory has no CDMW ownership record.")
    recorded_root = Path(str(payload.get("root", "")))
    retired_here = root.name.startswith(RETIRED_PREFIX) and recorded_root.parent == root.parent
    if (recorded_root != root and not retired_here) or tuple(payload.get("identity", ())) != _identity(root):
        raise ValueError("Temporary directory identity changed.")
    return payload


def create_owned_temp_directory(*, prefix: str, parent: Path | None = None) -> Path:
    """Allocate a private root; unrelated and unmarked directories are never adopted."""
    if not prefix or prefix in {".", ".."} or Path(prefix).name != prefix:
        raise ValueError("Temporary directory prefix must be a single filename component.")
    if parent is not None:
        parent = Path(parent).resolve()
        parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=prefix, dir=parent)).resolve()
    handle = None
    try:
        handle = (root / OWNER_MARKER).open("x+b")
        handle.write(json.dumps({
            "schema": OWNER_SCHEMA, "app": APP_NAME, "pid": os.getpid(),
            "root": str(root), "identity": _identity(root), "created_at": time.time(),
        }).encode("utf-8"))
        handle.flush()
        _file_lock(handle)
        with _lock:
            _owners[root] = handle
        return root
    except BaseException:
        if handle is not None:
            handle.close()
        shutil.rmtree(root, ignore_errors=True)
        raise


def owned_temp_directory_is_protected(root: Path, *, min_age_seconds: float = MIN_ABANDONED_AGE_SECONDS) -> bool:
    """Protect live, recent, redirected and unrecognised roots, including other processes."""
    root = Path(root).absolute()
    with _lock:
        if root in _owners or root in _retiring:
            return True
    handle = None
    try:
        marker = root / OWNER_MARKER
        if _is_link(marker) or marker.stat().st_size > 4096:
            return True
        handle = marker.open("r+b")
        _file_lock(handle)
        payload = _read_owner(root, handle)
        return time.time() - float(payload["created_at"]) < min_age_seconds
    except (OSError, ValueError, TypeError, KeyError):
        return True
    finally:
        if handle is not None:
            handle.close()


def cleanup_owned_temp_directory(root: Path, *, abandoned_only: bool = False, only_empty: bool = False) -> bool:
    """Retire an identity-checked root, preserving live owners and linked trees."""
    root = Path(root).absolute()
    handle = None
    owned = False
    retired = None
    with _lock:
        if root in _retiring:
            return False
        handle = _owners.get(root)
        owned = handle is not None
        if owned and abandoned_only:
            return False
        _retiring.add(root)
    try:
        if handle is None:
            marker = root / OWNER_MARKER
            if _is_link(marker) or marker.stat().st_size > 4096:
                return False
            handle = marker.open("r+b")
            _file_lock(handle)
        payload = _read_owner(root, handle)
        if abandoned_only and time.time() - float(payload["created_at"]) < MIN_ABANDONED_AGE_SECONDS:
            return False
        if only_empty and any(child.name != OWNER_MARKER for child in root.iterdir()):
            return False
        for directory, dirs, files in os.walk(root, followlinks=False):
            if any(_is_link(Path(directory, name)) for name in (*dirs, *files)):
                return False
        expected = _identity(root)
        retired = root.parent / f"{RETIRED_PREFIX}{uuid4().hex}"
        # Windows cannot delete the locked marker. Detach the directory entry
        # before deleting contents, and validate the entry that actually moved.
        if owned:
            with _lock:
                _owners.pop(root, None)
        handle.close()
        handle = None
        os.replace(root, retired)
        if _is_link(retired) or _identity(retired) != expected:
            raise ValueError("Temporary directory was replaced during retirement.")
        # Preserve the ownership record until every payload is removed. A denied
        # file must leave a recognisable root that a later launch can retry.
        handle = (retired / OWNER_MARKER).open("r+b")
        _file_lock(handle)
        _read_owner(retired, handle)
        for child in retired.iterdir():
            if child.name == OWNER_MARKER:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        handle.close()
        handle = None
        (retired / OWNER_MARKER).unlink()
        retired.rmdir()
        return True
    except (OSError, ValueError, TypeError, KeyError):
        if retired is not None and retired.exists() and not root.exists():
            if handle is not None:
                handle.close()
                handle = None
            try:
                os.replace(retired, root)
            except OSError:
                pass
        if owned and root.is_dir() and root not in _owners:
            try:
                handle = (root / OWNER_MARKER).open("r+b")
                _file_lock(handle)
                _read_owner(root, handle)
                with _lock:
                    _owners[root] = handle
            except (OSError, ValueError, TypeError, KeyError):
                if handle is not None:
                    handle.close()
                handle = None
        _logger.debug("Temporary cleanup deferred for %s", root, exc_info=True)
        return False
    finally:
        if handle is not None and (not owned or _owners.get(root) is not handle):
            handle.close()
        with _lock:
            _retiring.discard(root)


def close_owned_temp_directory_locks() -> None:
    """Exit releases ownership; deletion belongs to a background maintenance pass."""
    with _lock:
        handles = tuple(_owners.values())
        _owners.clear()
    for handle in handles:
        handle.close()


atexit.register(close_owned_temp_directory_locks)
