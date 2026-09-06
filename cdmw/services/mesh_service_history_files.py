"""Bounded Morph & Refit history snapshots and atomic file restoration."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import ctypes
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path, PurePosixPath
from typing import Sequence
from uuid import uuid4
from cdmw.services.mesh_service_state import _MeshHistorySnapshot


_MESH_MORPH_PROFILE_MAX_DEPTH = 4
_MESH_MORPH_PROFILE_MAX_ENTRIES = 4096
_MESH_MORPH_PROFILE_MAX_FILE_BYTES = 8 * 1024 * 1024
_MESH_MORPH_PROFILE_MAX_TOTAL_BYTES = 64 * 1024 * 1024


def _mesh_morph_profile_directory_state(
    root: Path | str,
) -> tuple[bool, tuple[tuple[str, bytes], ...], str]:
    """Capture one bounded settings-owned profile tree for reversible history."""

    path = Path(root).expanduser().absolute()
    if os.path.lexists(path) and _mesh_history_path_is_link(path):
        raise RuntimeError("Mesh morph profile history does not accept symbolic links")
    if os.path.lexists(path) and not path.is_dir():
        raise RuntimeError(f"Mesh morph profile root is not a directory: {path}")
    if not path.is_dir():
        digest = hashlib.sha256()
        digest.update(b"missing")
        return False, (), digest.hexdigest().upper()
    owned_root = path.resolve(strict=True)
    if _mesh_history_path_is_link(path):
        raise RuntimeError("Mesh morph profile history does not accept symbolic links")
    root_stat = path.stat()
    captured: list[tuple[str, bytes]] = []
    stack: list[tuple[Path, int]] = [(path, 0)]
    entry_count = 0
    total_bytes = 0
    while stack:
        directory, depth = stack.pop()
        for item in directory.iterdir():
            entry_count += 1
            if entry_count > _MESH_MORPH_PROFILE_MAX_ENTRIES:
                raise RuntimeError("Mesh morph profile history contains too many entries")
            if _mesh_history_path_is_link(item):
                raise RuntimeError("Mesh morph profile history does not accept symbolic links")
            resolved = item.resolve(strict=True)
            if _mesh_history_path_is_link(item):
                raise RuntimeError("Mesh morph profile history does not accept symbolic links")
            if owned_root not in resolved.parents:
                raise RuntimeError("Mesh morph profile history contains an unsafe relative path")
            if item.is_dir():
                if depth >= _MESH_MORPH_PROFILE_MAX_DEPTH:
                    raise RuntimeError("Mesh morph profile history exceeds its directory-depth limit")
                stack.append((item, depth + 1))
                continue
            if not item.is_file():
                raise RuntimeError("Mesh morph profile history contains an unsafe relative path")
            declared_stat = item.stat()
            declared_length = int(declared_stat.st_size)
            if declared_length > _MESH_MORPH_PROFILE_MAX_FILE_BYTES:
                raise RuntimeError("Mesh morph profile history file exceeds the 8 MiB limit")
            with item.open("rb") as stream:
                opened_stat = os.fstat(stream.fileno())
                if (
                    int(opened_stat.st_dev) != int(declared_stat.st_dev)
                    or int(opened_stat.st_ino) != int(declared_stat.st_ino)
                    or int(opened_stat.st_size) != declared_length
                ):
                    raise RuntimeError("Mesh morph profile changed before history capture")
                data = stream.read(_MESH_MORPH_PROFILE_MAX_FILE_BYTES + 1)
                final_stat = os.fstat(stream.fileno())
            if _mesh_history_path_is_link(item):
                raise RuntimeError("Mesh morph profile history does not accept symbolic links")
            current_stat = item.stat()
            if (
                len(data) > _MESH_MORPH_PROFILE_MAX_FILE_BYTES
                or len(data) != declared_length
                or int(final_stat.st_size) != declared_length
                or int(current_stat.st_dev) != int(declared_stat.st_dev)
                or int(current_stat.st_ino) != int(declared_stat.st_ino)
            ):
                raise RuntimeError("Mesh morph profile changed or exceeded its history limit")
            total_bytes += len(data)
            if total_bytes > _MESH_MORPH_PROFILE_MAX_TOTAL_BYTES:
                raise RuntimeError("Mesh morph profile history exceeds the 64 MiB total limit")
            captured.append((item.relative_to(path).as_posix(), data))
    if _mesh_history_path_is_link(path):
        raise RuntimeError("Mesh morph profile history does not accept symbolic links")
    current_root_stat = path.stat()
    if (
        path.resolve(strict=True) != owned_root
        or int(current_root_stat.st_dev) != int(root_stat.st_dev)
        or int(current_root_stat.st_ino) != int(root_stat.st_ino)
    ):
        raise RuntimeError("Mesh morph profile root changed during history capture")
    payload = tuple(sorted(captured, key=lambda candidate: candidate[0].casefold()))
    return True, payload, _mesh_morph_profile_state_fingerprint(True, payload)


def _mesh_history_path_is_link(path: Path) -> bool:
    attributes = int(getattr(path.lstat(), "st_file_attributes", 0) or 0)
    return path.is_symlink() or bool(
        attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0) or 0)
    )


def _mesh_history_directory_identity(path: Path) -> tuple[int, int]:
    if not os.path.lexists(path) or _mesh_history_path_is_link(path) or not path.is_dir():
        raise RuntimeError("Mesh morph profile history directory identity is unsafe")
    value = path.stat()
    return int(value.st_dev), int(value.st_ino)


@contextmanager
def _pinned_mesh_history_parent(path: Path):
    """Keep the lexical settings/session parent stable during publication."""

    expected_identity = _mesh_history_directory_identity(path)
    expected_resolved = path.resolve(strict=True)
    handle = None
    if os.name == "nt":
        create_file = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
        create_file.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        create_file.restype = wintypes.HANDLE
        handle = create_file(
            str(path),
            0,
            0x00000001 | 0x00000002,
            None,
            3,
            0x02000000,
            None,
        )
        if handle == wintypes.HANDLE(-1).value:
            raise RuntimeError("Mesh morph profile history parent could not be pinned")
    try:
        if (
            _mesh_history_directory_identity(path) != expected_identity
            or path.resolve(strict=True) != expected_resolved
        ):
            raise RuntimeError("Mesh morph profile history parent changed before publication")
        yield expected_identity
    finally:
        if handle is not None:
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(handle)


def _mesh_morph_profile_state_fingerprint(
    existed: bool,
    files: Sequence[tuple[str, bytes]],
) -> str:
    digest = hashlib.sha256()
    if not existed:
        digest.update(b"missing")
        return digest.hexdigest().upper()
    for relative, data in files:
        digest.update(str(relative).encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes(data))
        digest.update(b"\0")
    return digest.hexdigest().upper()


def _validated_mesh_morph_profile_files(
    files: Sequence[tuple[str, bytes]],
) -> tuple[tuple[PurePosixPath, bytes], ...]:
    validated: list[tuple[PurePosixPath, bytes]] = []
    seen: set[str] = set()
    directories: set[tuple[str, ...]] = set()
    total_bytes = 0
    for raw_relative, raw_data in files:
        relative = PurePosixPath(str(raw_relative))
        if (
            relative.is_absolute()
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise RuntimeError("Mesh morph profile history contains an unsafe relative path")
        folded = relative.as_posix().casefold()
        if folded in seen:
            raise RuntimeError("Mesh morph profile history contains duplicate paths")
        if len(relative.parts) - 1 > _MESH_MORPH_PROFILE_MAX_DEPTH:
            raise RuntimeError("Mesh morph profile history exceeds its directory-depth limit")
        directories.update(
            tuple(relative.parts[:depth])
            for depth in range(1, len(relative.parts))
        )
        if len(validated) + 1 + len(directories) > _MESH_MORPH_PROFILE_MAX_ENTRIES:
            raise RuntimeError("Mesh morph profile history contains too many entries")
        try:
            data_length = len(raw_data)
        except TypeError as exc:
            raise RuntimeError("Mesh morph profile history contains invalid file data") from exc
        if data_length > _MESH_MORPH_PROFILE_MAX_FILE_BYTES:
            raise RuntimeError("Mesh morph profile history file exceeds the 8 MiB limit")
        total_bytes += int(data_length)
        if total_bytes > _MESH_MORPH_PROFILE_MAX_TOTAL_BYTES:
            raise RuntimeError("Mesh morph profile history exceeds the 64 MiB total limit")
        seen.add(folded)
        validated.append((relative, bytes(raw_data)))
    return tuple(validated)


def _restore_mesh_morph_profile_directory_state(
    root: Path | str,
    *,
    existed: bool,
    files: Sequence[tuple[str, bytes]],
    expected_fingerprint: str,
) -> None:
    """Atomically restore a profile tree if its current state is still expected."""

    path = Path(root).expanduser().absolute()
    if path.name != "mesh_slider_profiles":
        raise RuntimeError("Mesh morph history target is not the settings-owned profile root")
    validated = tuple(
        sorted(
            _validated_mesh_morph_profile_files(files),
            key=lambda item: item[0].as_posix().casefold(),
        )
    )
    if not existed and validated:
        raise RuntimeError("Missing Mesh morph profile history cannot contain files")
    target_files = tuple((relative.as_posix(), data) for relative, data in validated)
    target_fingerprint = _mesh_morph_profile_state_fingerprint(
        bool(existed),
        target_files,
    )
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent / f".{path.name}.history-stage-{uuid4().hex}"
    backup = parent / f".{path.name}.history-backup-{uuid4().hex}"
    rejected = parent / f".{path.name}.history-rejected-{uuid4().hex}"
    moved_current = False
    published_target = False
    completed = False
    current_identity: tuple[int, int] | None = None
    staging_identity: tuple[int, int] | None = None

    def cleanup_owned_tree(candidate: Path, identity: tuple[int, int] | None) -> None:
        if identity is None or not os.path.lexists(candidate):
            return
        try:
            if _mesh_history_directory_identity(candidate) != identity:
                return
            _mesh_morph_profile_directory_state(candidate)
            shutil.rmtree(candidate)
        except Exception:
            pass

    with _pinned_mesh_history_parent(parent) as parent_identity:
        current_existed, _current_files, current_fingerprint = (
            _mesh_morph_profile_directory_state(path)
        )
        if current_fingerprint != str(expected_fingerprint).upper():
            raise RuntimeError(
                "Morph profiles changed outside Mesh Editor; Undo or Redo was rejected."
            )
        if current_existed:
            current_identity = _mesh_history_directory_identity(path)
        try:
            if existed:
                staging.mkdir()
                for relative, data in validated:
                    target = staging.joinpath(*relative.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                staging_identity = _mesh_history_directory_identity(staging)
                if _mesh_morph_profile_directory_state(staging)[2] != target_fingerprint:
                    raise RuntimeError("Mesh morph profile history staging validation failed")

            if _mesh_history_directory_identity(parent) != parent_identity:
                raise RuntimeError("Mesh morph profile history parent changed before publication")
            recheck_existed, _recheck_files, recheck_fingerprint = (
                _mesh_morph_profile_directory_state(path)
            )
            if (
                recheck_existed != current_existed
                or recheck_fingerprint != str(expected_fingerprint).upper()
                or (
                    current_identity is not None
                    and _mesh_history_directory_identity(path) != current_identity
                )
            ):
                raise RuntimeError(
                    "Morph profiles changed outside Mesh Editor; Undo or Redo was rejected."
                )
            if existed and (
                staging_identity is None
                or _mesh_history_directory_identity(staging) != staging_identity
                or _mesh_morph_profile_directory_state(staging)[2] != target_fingerprint
            ):
                raise RuntimeError("Mesh morph profile history staging changed before publication")

            if current_existed:
                os.replace(path, backup)
                moved_current = True
                if _mesh_history_directory_identity(backup) != current_identity:
                    raise RuntimeError("Mesh morph profile history backup identity changed")
            if existed:
                os.replace(staging, path)
                published_target = True
                if (
                    _mesh_history_directory_identity(path) != staging_identity
                    or _mesh_morph_profile_directory_state(path)[2] != target_fingerprint
                ):
                    raise RuntimeError("Mesh morph profile history publication validation failed")
            elif os.path.lexists(path):
                raise RuntimeError("Mesh morph profile history deletion did not complete")
            if _mesh_history_directory_identity(parent) != parent_identity:
                raise RuntimeError("Mesh morph profile history parent changed during publication")
            completed = True
        except Exception:
            if (published_target or moved_current) and os.path.lexists(path):
                os.replace(path, rejected)
            if moved_current and os.path.lexists(backup):
                os.replace(backup, path)
            cleanup_owned_tree(rejected, staging_identity)
            raise
        finally:
            cleanup_owned_tree(staging, staging_identity)
            if completed:
                cleanup_owned_tree(backup, current_identity)


def _validate_mesh_morph_profile_history_state(snapshot: _MeshHistorySnapshot) -> None:
    if snapshot.morph_profile_root is None:
        return
    expected = str(snapshot.morph_profile_expected_fingerprint or "").upper()
    if not expected:
        raise RuntimeError("Mesh morph profile history is missing its expected state")
    current = _mesh_morph_profile_directory_state(snapshot.morph_profile_root)[2]
    if current != expected:
        raise RuntimeError(
            "Morph profiles changed outside Mesh Editor; Undo or Redo was rejected."
        )
