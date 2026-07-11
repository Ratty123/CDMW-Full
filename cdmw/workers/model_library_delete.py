"""Validated, cancellable local deletion for Model Library."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.workers.model_library_rows import ModelLibraryDeleteTarget


@dataclass(frozen=True, slots=True)
class ModelLibraryDeleteRequest:
    request_id: int
    targets: tuple[ModelLibraryDeleteTarget, ...]


@dataclass(frozen=True, slots=True)
class ModelLibraryDeleteResult:
    request_id: int
    deleted_paths: tuple[str, ...]
    errors: tuple[str, ...]


def delete_model_library_targets(
    request: ModelLibraryDeleteRequest,
    *,
    stop_event: Optional[threading.Event] = None,
) -> ModelLibraryDeleteResult:
    """Validate ownership, plan without mutation, then delete each target."""

    deleted: list[str] = []
    errors: list[str] = []
    for target in request.targets:
        raise_if_cancelled(stop_event, "Model Library deletion cancelled.")
        try:
            path, files, directories = _validated_delete_plan(target, stop_event=stop_event)
            raise_if_cancelled(stop_event, "Model Library deletion cancelled.")
            _commit_delete(path, files, directories, target.target_kind)
            deleted.append(str(path))
        except OSError as exc:
            errors.append(f"{target.path}: {exc}")
        except ValueError as exc:
            errors.append(f"{target.path}: {exc}")
    return ModelLibraryDeleteResult(request.request_id, tuple(deleted), tuple(errors))


def _validated_delete_plan(
    target: ModelLibraryDeleteTarget,
    *,
    stop_event: Optional[threading.Event],
) -> tuple[Path, tuple[Path, ...], tuple[Path, ...]]:
    path = Path(os.path.abspath(target.path))
    root = Path(os.path.abspath(target.allowed_root))
    if path == root or root not in path.parents:
        raise ValueError("target is outside its approved local root")
    if _path_identity(path) != target.identity:
        raise ValueError("target identity changed after confirmation")
    if target.target_kind == "local_file":
        if not os.path.lexists(path):
            raise ValueError("confirmed local file no longer exists")
        if path.is_dir() and not path.is_symlink():
            raise ValueError("confirmed local file became a directory")
        if not path.is_symlink() and root.resolve(strict=True) not in path.resolve(strict=True).parents:
            raise ValueError("local file resolves outside its approved root")
        return path, (path,), ()
    if target.target_kind != "download_dir":
        raise ValueError("unsupported delete target type")
    if path.is_symlink():
        raise ValueError("download folder cannot be a symlink")
    resolved_path = path.resolve(strict=True)
    resolved_root = root.resolve(strict=True)
    if resolved_root not in resolved_path.parents:
        raise ValueError("download folder resolves outside its approved root")
    if not path.is_dir() or not (path / "model_metadata.json").is_file():
        raise ValueError("download folder ownership marker is missing")
    files: list[Path] = []
    directories: list[Path] = []
    _plan_directory(path, files, directories, stop_event=stop_event)
    return path, tuple(files), tuple(directories)


def _plan_directory(
    directory: Path,
    files: list[Path],
    directories: list[Path],
    *,
    stop_event: Optional[threading.Event],
) -> None:
    raise_if_cancelled(stop_event, "Model Library deletion cancelled.")
    with os.scandir(directory) as entries:
        for entry in entries:
            raise_if_cancelled(stop_event, "Model Library deletion cancelled.")
            path = Path(entry.path)
            if entry.is_dir(follow_symlinks=False):
                _plan_directory(path, files, directories, stop_event=stop_event)
            else:
                files.append(path)
    directories.append(directory)


def _commit_delete(
    root: Path,
    files: tuple[Path, ...],
    directories: tuple[Path, ...],
    target_kind: str,
) -> None:
    if target_kind == "local_file":
        root.unlink()
        return
    for path in files:
        path.unlink(missing_ok=True)
    for directory in directories:
        directory.rmdir()


def _path_identity(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path))).casefold()


__all__ = [
    "ModelLibraryDeleteRequest",
    "ModelLibraryDeleteResult",
    "delete_model_library_targets",
]
