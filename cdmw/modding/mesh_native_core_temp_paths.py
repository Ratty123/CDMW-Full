from __future__ import annotations

from pathlib import Path
import os
import shutil
import tempfile
import threading
import time

_native_preview_delta_paths_lock = threading.RLock()
_native_preview_delta_paths: set[Path] = set()
_native_preview_delta_dirs: set[Path] = set()
_allocations_since_prune = 0
_PRUNE_INTERVAL = 1024
#: Temp-entry prefixes this module owns; the stale sweep removes abandoned
#: entries left behind by a crash or a budget-limited exit cleanup.
_SWEEP_PREFIXES = (
    "cdmw_mesh_preview_delta_",
    "cdmw_mesh_editor_delta_",
    "cdmw_mesh_core_uv_selection_",
)
_stale_sweep_lock = threading.Lock()
_stale_sweep_started = False


def _unlink_delta_path(path: Path) -> None:
    for candidate in (
        path,
        Path(str(path) + ".source_indices.bin"),
        Path(str(path) + ".source_vertices.bin"),
        Path(str(path) + ".source_edges.bin"),
        Path(str(path) + ".source_faces.bin"),
        Path(str(path) + ".normals.bin"),
        Path(str(path) + ".uvs.bin"),
        Path(str(path) + ".indices.bin"),
    ):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass


def _prune_missing_paths_locked() -> None:
    existing_paths = {path for path in _native_preview_delta_paths if path.exists()}
    existing_dirs = {path for path in _native_preview_delta_dirs if path.exists()}
    _native_preview_delta_paths.intersection_update(existing_paths)
    _native_preview_delta_dirs.intersection_update(existing_dirs)


def _record_allocation_locked() -> None:
    """Amortize stale-path pruning instead of scanning the registry per payload."""

    global _allocations_since_prune
    _allocations_since_prune += 1
    if _allocations_since_prune < _PRUNE_INTERVAL:
        return
    _allocations_since_prune = 0
    _prune_missing_paths_locked()


def native_preview_delta_output_path(suffix: str = ".bin") -> str:
    start_stale_native_preview_delta_sweep()
    with tempfile.NamedTemporaryFile(prefix="cdmw_mesh_preview_delta_", suffix=suffix, delete=False) as handle:
        path = Path(handle.name)
    with _native_preview_delta_paths_lock:
        _native_preview_delta_paths.add(path)
        _record_allocation_locked()
    return str(path)


def native_preview_delta_output_dir() -> str:
    start_stale_native_preview_delta_sweep()
    path = Path(tempfile.mkdtemp(prefix="cdmw_mesh_editor_delta_"))
    with _native_preview_delta_paths_lock:
        _native_preview_delta_dirs.add(path)
        _record_allocation_locked()
    return str(path)


def release_native_preview_delta_path(path: str | Path) -> bool:
    """Acknowledge and remove one app-owned native delta payload."""

    candidate = Path(path)
    with _native_preview_delta_paths_lock:
        tracked_file = candidate in _native_preview_delta_paths
        tracked_dir = next(
            (directory for directory in _native_preview_delta_dirs if candidate.parent == directory),
            None,
        )
        if not tracked_file and tracked_dir is None:
            return False
        _native_preview_delta_paths.discard(candidate)
    _unlink_delta_path(candidate)
    if tracked_dir is not None:
        try:
            tracked_dir.rmdir()
        except OSError:
            pass
        else:
            with _native_preview_delta_paths_lock:
                _native_preview_delta_dirs.discard(tracked_dir)
    return True


def cleanup_native_preview_delta_paths(time_budget_seconds: float | None = None) -> int:
    """Delete tracked delta payloads, optionally under a time budget.

    A sculpt session tracks one delta payload per accepted stroke sample, and
    each one fans out to eight candidate names on disk -- so an unbounded
    cleanup at exit walked hundreds of thousands of unlink attempts on the
    GUI thread and Windows reported the window hung for the whole walk (the
    recorded 2026-08-02 15:12 stall was exactly this stack). Under a budget
    the remainder is deliberately left behind: the stale sweep removes it in
    the background the next time the Mesh Editor allocates a delta.

    Returns the number of tracked entries left undeleted.
    """
    deadline = (
        None
        if time_budget_seconds is None
        else time.monotonic() + max(0.0, float(time_budget_seconds))
    )
    with _native_preview_delta_paths_lock:
        paths = tuple(_native_preview_delta_paths)
        dirs = tuple(_native_preview_delta_dirs)
        _native_preview_delta_paths.clear()
        _native_preview_delta_dirs.clear()
    remaining = 0
    for index, path in enumerate(paths):
        if deadline is not None and time.monotonic() > deadline:
            remaining += len(paths) - index
            break
        _unlink_delta_path(path)
    for index, path in enumerate(dirs):
        if deadline is not None and time.monotonic() > deadline:
            remaining += len(dirs) - index
            break
        shutil.rmtree(path, ignore_errors=True)
    return remaining


def sweep_stale_native_preview_delta_temp(
    *,
    max_age_seconds: float = 1800.0,
    temp_root: str | Path | None = None,
) -> int:
    """Remove abandoned delta temp entries older than ``max_age_seconds``.

    Only entries carrying this module's prefixes are touched, and only when
    their mtime is comfortably stale: delta payloads live for seconds between
    the app writing them and the resident helper acknowledging them, so a
    half-hour-old entry belongs to a crashed or budget-limited earlier run.
    Entries tracked by this process are skipped regardless of age.
    """
    root = Path(temp_root) if temp_root is not None else Path(tempfile.gettempdir())
    cutoff = time.time() - max(0.0, float(max_age_seconds))
    with _native_preview_delta_paths_lock:
        owned = {str(path) for path in _native_preview_delta_paths}
        owned.update(str(path) for path in _native_preview_delta_dirs)
    removed = 0
    try:
        entries = list(os.scandir(root))
    except OSError:
        return 0
    for entry in entries:
        if not entry.name.startswith(_SWEEP_PREFIXES) or entry.path in owned:
            continue
        try:
            if entry.stat(follow_symlinks=False).st_mtime > cutoff:
                continue
        except OSError:
            continue
        try:
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path, ignore_errors=True)
            else:
                os.unlink(entry.path)
            removed += 1
        except OSError:
            continue
    return removed


def start_stale_native_preview_delta_sweep() -> None:
    """Run the stale sweep once per process, on a background thread."""

    global _stale_sweep_started
    with _stale_sweep_lock:
        if _stale_sweep_started:
            return
        _stale_sweep_started = True
    threading.Thread(
        target=lambda: sweep_stale_native_preview_delta_temp(),
        name="cdmw-mesh-delta-sweep",
        daemon=True,
    ).start()
