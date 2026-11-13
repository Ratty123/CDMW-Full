from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator, TextIO
from uuid import uuid4

# Every writer here refuses a path in a game folder unless the caller holds the permit
# only Restore Backup and the removal action have, and never replaces a game folder or
# a folder that holds one (decision 46). Targets are checked before anything is made,
# again after their folder is made, and right before each move into place; staged
# sources are checked too, since moving them takes them out of where they are.
from cdmw.core.protected_roots import check_removable, check_writable


def _replace(staged: Path, target: Path, *, folder: bool = False) -> None:
    check = check_removable if folder else check_writable
    check(staged)
    check(target)
    os.replace(staged, target)


def _temporary_file(target: Path) -> tuple[int, Path]:
    check_writable(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    check_writable(target)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    return descriptor, Path(name)


@contextmanager
def atomic_binary_writer(path: Path | str, *, durable: bool = True) -> Iterator[BinaryIO]:
    """Publish a complete binary file without exposing partial contents.

    ``durable=False`` skips the flush to disk. Only for files that are verified
    on read and rebuilt when missing, such as preview cache packages; build
    output and anything that is the only copy keep the default.
    """

    target = Path(path)
    descriptor, temporary = _temporary_file(target)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            yield handle
            handle.flush()
            if durable:
                os.fsync(handle.fileno())
        _replace(temporary, target)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


@contextmanager
def atomic_text_writer(
    path: Path | str, *, encoding: str = "utf-8", durable: bool = True,
) -> Iterator[TextIO]:
    """Publish a complete text file without exposing partial contents.

    ``durable`` as for :func:`atomic_binary_writer`.
    """

    target = Path(path)
    descriptor, temporary = _temporary_file(target)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline="") as handle:
            descriptor = -1
            yield handle
            handle.flush()
            if durable:
                os.fsync(handle.fileno())
        _replace(temporary, target)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def atomic_write_bytes(path: Path | str, data: bytes, *, durable: bool = True) -> None:
    with atomic_binary_writer(path, durable=durable) as handle:
        handle.write(data)


def atomic_write_text(
    path: Path | str, text: str, *, encoding: str = "utf-8", durable: bool = True,
) -> None:
    with atomic_text_writer(path, encoding=encoding, durable=durable) as handle:
        handle.write(text)


def atomic_copy_file(source: Path | str, destination: Path | str) -> None:
    with Path(source).open("rb") as source_handle, atomic_binary_writer(destination) as destination_handle:
        shutil.copyfileobj(source_handle, destination_handle, length=1024 * 1024)


def atomic_publish_files(files: Mapping[Path | str, Path | str]) -> None:
    """Publish staged files as one rollback-capable operation."""

    pairs = [(Path(staged), Path(target)) for staged, target in files.items()]
    for staged, target in pairs:
        check_writable(staged)
        check_writable(target)
    if len({target for _staged, target in pairs}) != len(pairs):
        raise ValueError("atomic publication targets must be unique")
    if any(not staged.is_file() for staged, _target in pairs):
        raise FileNotFoundError("atomic publication requires every staged file")
    published: list[tuple[Path, Path | None]] = []
    success = False
    try:
        for staged, target in pairs:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and not target.is_file():
                raise IsADirectoryError(target)
            backup = target.with_name(f".{target.name}.{uuid4().hex}.bak") if target.exists() else None
            if backup is not None:
                _replace(target, backup)
            try:
                _replace(staged, target)
            except Exception:
                if backup is not None:
                    os.replace(backup, target)
                raise
            published.append((target, backup))
        success = True
    finally:
        if not success:
            for target, backup in reversed(published):
                if backup is not None and backup.exists():
                    os.replace(backup, target)
                else:
                    target.unlink(missing_ok=True)
        else:
            for _target, backup in published:
                if backup is not None:
                    backup.unlink(missing_ok=True)


def atomic_publish_directory(
    staged: Path | str,
    target: Path | str,
    *,
    replace_existing: bool = True,
    retain_backup: bool = False,
) -> Path | None:
    """Publish with rollback; optionally refuse replacement or retain and return old output."""
    staged_path = Path(staged)
    target_path = Path(target)
    check_removable(staged_path)
    check_removable(target_path)
    if not staged_path.is_dir():
        raise NotADirectoryError(staged_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists() and not target_path.is_dir():
        raise NotADirectoryError(target_path)
    if target_path.exists() and not replace_existing:
        raise FileExistsError(f"Destination already exists: {target_path}")
    backup = target_path.with_name(f".{target_path.name}.{uuid4().hex}.bak") if target_path.exists() else None
    if backup is not None:
        _replace(target_path, backup, folder=True)
    try:
        _replace(staged_path, target_path, folder=True)
    except Exception:
        if backup is not None:
            os.replace(backup, target_path)
        raise
    if backup is not None:
        if retain_backup:
            return backup
        shutil.rmtree(backup, ignore_errors=True)
    return None


def atomic_publish_paths(
    paths: Sequence[tuple[Path, Path]],
    *,
    check_cancelled: Callable[[], None] | None = None,
    replace_existing: bool = True,
) -> None:
    """Publish files and directories together, restoring prior output on failure."""
    pairs = [(Path(staged), Path(target)) for staged, target in paths]
    for staged, target in pairs:
        check_removable(staged)
        check_removable(target)
    if len({os.path.normcase(str(target.absolute())) for _, target in pairs}) != len(pairs):
        raise ValueError("atomic publication targets must be unique")
    for staged, target in pairs:
        if not staged.exists():
            raise FileNotFoundError(staged)
        if not replace_existing and (target.exists() or target.is_symlink()):
            raise FileExistsError(f"Destination already exists: {target}")
        if target.exists() and not target.is_symlink() and staged.is_dir() != target.is_dir():
            raise ValueError(f"atomic publication cannot change the target type: {target}")

    def remove(path: Path) -> None:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)

    published: list[tuple[Path, Path | None]] = []
    try:
        for staged, target in pairs:
            if check_cancelled is not None:
                check_cancelled()
            target.parent.mkdir(parents=True, exist_ok=True)
            if not replace_existing and (target.exists() or target.is_symlink()):
                raise FileExistsError(f"Destination already exists: {target}")
            backup = target.with_name(f".{target.name}.{uuid4().hex}.bak") if replace_existing and (target.exists() or target.is_symlink()) else None
            check_removable(staged)
            check_removable(target)
            if backup is not None:
                target.replace(backup)
            try:
                if replace_existing:
                    staged.replace(target)
                else:
                    staged.rename(target)
            except BaseException:
                if backup is not None:
                    backup.replace(target)
                raise
            published.append((target, backup))
        if check_cancelled is not None:
            check_cancelled()
    except BaseException:
        for target, backup in reversed(published):
            remove(target)
            if backup is not None:
                backup.replace(target)
        raise
    else:
        for _, backup in published:
            if backup is not None:
                try:
                    remove(backup)
                except OSError:
                    # Publication already succeeded; retain an undeletable backup.
                    pass


__all__ = [
    "atomic_binary_writer",
    "atomic_copy_file",
    "atomic_publish_directory",
    "atomic_publish_files",
    "atomic_publish_paths",
    "atomic_text_writer",
    "atomic_write_bytes",
    "atomic_write_text",
]
