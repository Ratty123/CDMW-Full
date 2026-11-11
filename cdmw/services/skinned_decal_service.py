"""Read archive sequences and atomically save verified loose decal copies."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.atomic_file import atomic_write_bytes
from cdmw.core.skinned_decal import SkinnedDecalDocument, read_skinned_decal, write_skinned_decal
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.models import ArchiveEntry


@dataclass(frozen=True)
class DecalEditSource:
    entry: ArchiveEntry
    document: SkinnedDecalDocument


@dataclass(frozen=True)
class DecalSaveRequest:
    document: SkinnedDecalDocument
    output_path: Path
    changes: tuple[tuple[str, str], ...]


def load_decal_source(entry: ArchiveEntry, *, stop_event=None) -> DecalEditSource:
    raise_if_cancelled(stop_event, "Decal loading cancelled.")
    if entry.extension.lower() != ".paseq":
        raise ValueError("Choose a PASEQ sequence containing skinned decals.")
    data, _expanded, _note = read_archive_entry_data(entry, stop_event=stop_event)
    raise_if_cancelled(stop_event, "Decal loading cancelled.")
    result = DecalEditSource(entry, read_skinned_decal(data))
    raise_if_cancelled(stop_event, "Decal loading cancelled.")
    return result


def save_decal_copy(request: DecalSaveRequest, *, stop_event=None) -> Path:
    raise_if_cancelled(stop_event, "Decal saving cancelled.")
    if request.output_path.suffix.lower() != ".paseq":
        raise ValueError("Save the decal sequence as a .paseq file.")
    changes = dict(request.changes)
    if len(changes) != len(request.changes):
        raise ValueError("A decal setting cannot be edited twice in one save.")
    data = write_skinned_decal(request.document, changes)
    raise_if_cancelled(stop_event, "Decal saving cancelled.")
    atomic_write_bytes(request.output_path, data)
    return request.output_path
