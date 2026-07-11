"""Read-only importable-member discovery for model ZIP archives."""

from __future__ import annotations

import io
import threading
import zipfile
from pathlib import Path, PurePosixPath
from typing import Optional

from cdmw.core.common import raise_if_cancelled
from cdmw.domain.library.models import (
    ZIP_IMPORTABLE_MODEL_EXTENSIONS,
    ZIP_NESTED_IMPORTABLE_ARCHIVE_EXTENSIONS,
    ZIP_NESTED_IMPORTABLE_ARCHIVE_MAX_BYTES,
)


def zip_importable_members(
    archive_path: Path | str,
    *,
    stop_event: Optional[threading.Event] = None,
) -> tuple[str, ...]:
    archive = Path(archive_path)
    if archive.suffix.lower() != ".zip" or not archive.is_file():
        return ()
    priority = {".gltf": 0, ".glb": 1, ".obj": 2, ".dae": 3}
    members: list[str] = []
    try:
        with zipfile.ZipFile(archive, "r") as zip_file:
            for member in zip_file.infolist():
                raise_if_cancelled(stop_event, "Model import resolution cancelled.")
                member_name = safe_zip_member_name(member.filename)
                if not member.is_dir() and Path(member_name).suffix.lower() in ZIP_IMPORTABLE_MODEL_EXTENSIONS:
                    members.append(member_name)
    except (OSError, zipfile.BadZipFile):
        return ()
    return tuple(sorted(members, key=lambda value: (priority.get(Path(value).suffix.lower(), 99), value.lower())))


def zip_importable_member_refs(
    archive_path: Path | str,
    *,
    stop_event: Optional[threading.Event] = None,
) -> tuple[str, ...]:
    """Return direct and one-level nested ZIP importable member references."""
    archive = Path(archive_path)
    direct_members = list(zip_importable_members(archive, stop_event=stop_event))
    if archive.suffix.lower() != ".zip" or not archive.is_file():
        return tuple(direct_members)
    members = list(direct_members)
    seen = {member.lower() for member in members}
    try:
        with zipfile.ZipFile(archive, "r") as zip_file:
            for member in zip_file.infolist():
                raise_if_cancelled(stop_event, "Model import resolution cancelled.")
                member_name = safe_zip_member_name(member.filename)
                if Path(member_name).suffix.lower() not in ZIP_NESTED_IMPORTABLE_ARCHIVE_EXTENSIONS:
                    continue
                if int(getattr(member, "file_size", 0) or 0) > ZIP_NESTED_IMPORTABLE_ARCHIVE_MAX_BYTES:
                    continue
                for nested_member in _nested_zip_importable_members(zip_file, member, stop_event=stop_event):
                    ref = f"{member_name}::{nested_member}"
                    if ref.lower() not in seen:
                        seen.add(ref.lower())
                        members.append(ref)
    except (OSError, zipfile.BadZipFile):
        return tuple(direct_members)
    return tuple(sorted(members, key=_zip_importable_member_ref_sort_key))


def _nested_zip_importable_members(
    parent_archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    *,
    stop_event: Optional[threading.Event] = None,
) -> tuple[str, ...]:
    try:
        with parent_archive.open(member, "r") as stream:
            payload = _read_bounded_nested_zip(stream, stop_event=stop_event)
        with zipfile.ZipFile(io.BytesIO(payload), "r") as nested_archive:
            members = []
            for nested_member in nested_archive.infolist():
                raise_if_cancelled(stop_event, "Model import resolution cancelled.")
                name = safe_zip_member_name(nested_member.filename)
                if Path(name).suffix.lower() in ZIP_IMPORTABLE_MODEL_EXTENSIONS:
                    members.append(name)
    except (OSError, zipfile.BadZipFile, ValueError):
        return ()
    return tuple(sorted(members, key=lambda value: (Path(value).suffix.lower(), value.lower())))


def _read_bounded_nested_zip(stream: object, *, stop_event: Optional[threading.Event]) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        raise_if_cancelled(stop_event, "Model import resolution cancelled.")
        chunk = stream.read(min(1024 * 1024, ZIP_NESTED_IMPORTABLE_ARCHIVE_MAX_BYTES + 1 - total))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > ZIP_NESTED_IMPORTABLE_ARCHIVE_MAX_BYTES:
            raise ValueError("Nested model ZIP exceeds the size limit.")


def _zip_importable_member_ref_sort_key(value: str) -> tuple[int, int, str, str]:
    priority = {".gltf": 0, ".glb": 1, ".obj": 2, ".dae": 3, ".pac": 4, ".pam": 5, ".pamlod": 6}
    outer, nested = split_nested_zip_member_ref(value)
    suffix = Path(nested or outer).suffix.lower()
    return (priority.get(suffix, 99), 1 if nested else 0, outer.lower(), nested.lower())


def safe_zip_member_name(value: str) -> str:
    member_name = str(value or "").replace("\\", "/")
    if not member_name or member_name.startswith(("/", "//")) or "\x00" in member_name:
        return ""
    parts = PurePosixPath(member_name).parts
    if not parts or any(part in {"", ".", ".."} for part in parts) or ":" in parts[0]:
        return ""
    return PurePosixPath(*parts).as_posix()


def split_nested_zip_member_ref(value: str) -> tuple[str, str]:
    text = str(value or "").replace("\\", "/")
    return tuple(text.split("::", 1)) if "::" in text else (text, "")


def zip_contains_importable_model(archive_path: Path | str) -> bool:
    return bool(zip_importable_member_refs(archive_path))


__all__ = ["safe_zip_member_name", "split_nested_zip_member_ref", "zip_contains_importable_model", "zip_importable_member_refs", "zip_importable_members"]
