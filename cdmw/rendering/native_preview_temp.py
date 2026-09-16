"""Owned Preview Core job folders, including recovery after an interrupted run."""

from __future__ import annotations

import atexit
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time

_MARKER = ".cdmw-preview-job"
_SIGNATURE = b"cdmw-preview-job-v1\n"
_owners: dict[Path, object] = {}
_unconfirmed_helpers: set[Path] = set()
_lock = threading.RLock()
_swept = False


def _file_lock(handle: object) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def sweep_abandoned_preview_jobs(temp_root: Path, *, min_age_seconds: float = 1800.0) -> int:
    """Only remove marked, unlocked direct children of the supplied temp root.

    A file lock protects folders owned by another live CDMW process. Unknown
    legacy folders are deliberately left alone; a name or age is not ownership.
    This runs on the preview preparation worker, never on the Qt thread.
    """
    root = Path(temp_root).resolve()
    removed = 0
    try:
        candidates = tuple(root.glob("cdmw_preview_core_*"))
    except OSError:
        return 0
    for candidate in candidates:
        handle = None
        try:
            if candidate.is_symlink() or candidate.resolve() != candidate.absolute():
                continue
            if candidate.resolve().parent != root or not candidate.is_dir():
                continue
            if time.time() - candidate.stat().st_mtime < min_age_seconds:
                continue
            marker = candidate / _MARKER
            if marker.is_symlink() or marker.resolve().parent != candidate:
                continue
            with _lock:
                if candidate in _owners:
                    continue
                handle = marker.open("r+b")
                _file_lock(handle)
                if handle.read(len(_SIGNATURE) + 1) != _SIGNATURE:
                    continue
                handle.close()
                handle = None
                shutil.rmtree(candidate)
                removed += 1
        except OSError:
            continue
        finally:
            if handle is not None:
                handle.close()
    return removed


def create_preview_job_root() -> Path:
    global _swept
    with _lock:
        sweep = not _swept
        _swept = True
    if sweep:
        sweep_abandoned_preview_jobs(Path(tempfile.gettempdir()))
    root = Path(tempfile.mkdtemp(prefix="cdmw_preview_core_")).resolve()
    handle = None
    try:
        handle = (root / _MARKER).open("w+b")
        handle.write(_SIGNATURE)
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


def remove_preview_job_root(root: Path) -> None:
    root = Path(root).resolve()
    with _lock:
        handle = _owners.pop(root, None)
        _unconfirmed_helpers.discard(root)
        if handle is None:
            return
        handle.close()
        shutil.rmtree(root, ignore_errors=True)


def retain_preview_job_for_helper(root: Path) -> None:
    """Quarantine inputs if cancellation did not confirm the helper's exit."""
    root = Path(root).resolve()
    with _lock:
        handle = _owners.get(root)
        if handle is not None and root not in _unconfirmed_helpers:
            handle.seek(0, os.SEEK_END)
            handle.write(b"unconfirmed-helper\n")
            handle.flush()
            _unconfirmed_helpers.add(root)


def _close_preview_jobs() -> None:
    # Stop a long successful reference-preview session from hanging at exit.
    # Unremoved marked roots become eligible for the next process's sweep.
    deadline = time.monotonic() + 0.5
    with _lock:
        roots = tuple(_owners)
    for root in roots:
        if root not in _unconfirmed_helpers and time.monotonic() < deadline:
            remove_preview_job_root(root)
        else:
            with _lock:
                handle = _owners.pop(root, None)
            if handle is not None:
                handle.close()


atexit.register(_close_preview_jobs)
