from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import threading

_native_preview_delta_paths_lock = threading.RLock()
_native_preview_delta_paths: set[Path] = set()
_native_preview_delta_dirs: set[Path] = set()


def native_preview_delta_output_path(suffix: str = ".bin") -> str:
    with tempfile.NamedTemporaryFile(prefix="cdmw_mesh_preview_delta_", suffix=suffix, delete=False) as handle:
        path = Path(handle.name)
    with _native_preview_delta_paths_lock:
        _native_preview_delta_paths.add(path)
    return str(path)


def native_preview_delta_output_dir() -> str:
    path = Path(tempfile.mkdtemp(prefix="cdmw_mesh_editor_delta_"))
    with _native_preview_delta_paths_lock:
        _native_preview_delta_dirs.add(path)
    return str(path)


def cleanup_native_preview_delta_paths() -> None:
    with _native_preview_delta_paths_lock:
        paths = tuple(_native_preview_delta_paths)
        dirs = tuple(_native_preview_delta_dirs)
        _native_preview_delta_paths.clear()
        _native_preview_delta_dirs.clear()
    for path in paths:
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
    for path in dirs:
        shutil.rmtree(path, ignore_errors=True)
