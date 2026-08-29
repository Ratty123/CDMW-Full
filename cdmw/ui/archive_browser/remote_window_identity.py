"""Identity and path rules shared by the remote Archive Browser bridge."""

from __future__ import annotations

from pathlib import PurePosixPath

from cdmw.domain.archives.catalogue import ArchiveDurableIdentity, ArchiveEntryDto
from cdmw.models import ArchiveEntry


def legacy_identity(entry: ArchiveEntry | None) -> ArchiveDurableIdentity | None:
    if entry is None:
        return None
    identity = entry.identity
    return ArchiveDurableIdentity(
        identity.normalized_path,
        identity.source_pamt,
        identity.paz_index,
        identity.entry_offset,
    )


def legacy_identity_key(entry: ArchiveEntry) -> tuple[object, ...]:
    identity = entry.identity
    return (
        _normalized(identity.normalized_path),
        _normalized(identity.source_pamt),
        int(identity.paz_index),
        int(identity.entry_offset),
    )


def base_index_identity_key(entry: ArchiveEntry) -> tuple[object, ...]:
    identity = entry.identity
    return (
        _normalized(identity.normalized_path),
        str(identity.source_pamt).replace("\\", "/"),
        int(identity.entry_offset),
    )


def dto_identity_key(entry: ArchiveEntryDto) -> tuple[object, ...]:
    identity = entry.identity
    return (
        _normalized(identity.normalized_path),
        _normalized(identity.source_pamt),
        int(identity.paz_index),
        int(identity.archive_offset),
    )


def structure_sort_key(value: str) -> tuple[int, int, str]:
    leaf = value.rsplit("/", 1)[-1]
    return (0, int(leaf), leaf) if leaf.isdigit() else (1, 0, leaf)


def workflow_path(entry: ArchiveEntryDto) -> str:
    package_root = PurePosixPath(entry.source_pamt.replace("\\", "/")).parent.name.strip() or "package"
    normalized_path = entry.path.replace("\\", "/").lstrip("/")
    return f"{package_root}/{normalized_path}"


def _normalized(value: object) -> str:
    return str(value or "").replace("\\", "/").strip("/").casefold()


__all__ = [
    "base_index_identity_key",
    "dto_identity_key",
    "legacy_identity",
    "legacy_identity_key",
    "structure_sort_key",
    "workflow_path",
]
