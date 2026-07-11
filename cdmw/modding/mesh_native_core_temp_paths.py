from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import threading

_native_preview_delta_paths_lock = threading.RLock()
_native_preview_delta_paths: set[Path] = set()
_native_preview_delta_dirs: set[Path] = set()
_allocations_since_prune = 0
_PRUNE_INTERVAL = 1024


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
    with tempfile.NamedTemporaryFile(prefix="cdmw_mesh_preview_delta_", suffix=suffix, delete=False) as handle:
        path = Path(handle.name)
    with _native_preview_delta_paths_lock:
        _native_preview_delta_paths.add(path)
        _record_allocation_locked()
    return str(path)


def native_preview_delta_output_dir() -> str:
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


def cleanup_native_preview_delta_paths() -> None:
    with _native_preview_delta_paths_lock:
        paths = tuple(_native_preview_delta_paths)
        dirs = tuple(_native_preview_delta_dirs)
        _native_preview_delta_paths.clear()
        _native_preview_delta_dirs.clear()
    for path in paths:
        _unlink_delta_path(path)
    for path in dirs:
        shutil.rmtree(path, ignore_errors=True)
