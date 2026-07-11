"""Cancellable material-sidecar loading for the editor UI."""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import try_decode_text_like_archive_data
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.core.material_sidecar_editor import (
    MaterialSidecarEditResult,
    MaterialSidecarEditableValue,
    MaterialSidecarRelatedFile,
    apply_material_sidecar_edits,
    detect_material_sidecar_related_files,
    discover_material_sidecar_values,
)
from cdmw.models import ArchiveEntry, ArchiveModelTextureReference


@dataclass(frozen=True, slots=True)
class MaterialSidecarEditorDocument:
    entry: ArchiveEntry
    original_text: str
    rows: tuple[MaterialSidecarEditableValue, ...]


@dataclass(frozen=True, slots=True)
class MaterialSidecarExportPreparation:
    edit_result: MaterialSidecarEditResult
    related_files: tuple[MaterialSidecarRelatedFile, ...]


def load_material_sidecar_editor_document(
    entry: ArchiveEntry,
    *,
    stop_event: threading.Event | None = None,
) -> MaterialSidecarEditorDocument:
    raise_if_cancelled(stop_event, "Material sidecar loading cancelled.")
    data, _decompressed, _note = read_archive_entry_data(entry, stop_event=stop_event)
    original_text = try_decode_text_like_archive_data(data)
    if original_text is None:
        original_text = data.decode("utf-8", errors="replace")
    raise_if_cancelled(stop_event, "Material sidecar loading cancelled.")
    rows = tuple(discover_material_sidecar_values(original_text))
    return MaterialSidecarEditorDocument(entry, original_text, rows)


def prepare_material_sidecar_export(
    entry: ArchiveEntry,
    original_text: str,
    edited_values: Mapping[str, str],
    *,
    references: Sequence[ArchiveModelTextureReference] = (),
    archive_entries_by_basename: Mapping[str, Sequence[ArchiveEntry]] | None = None,
    stop_event: threading.Event | None = None,
) -> MaterialSidecarExportPreparation:
    raise_if_cancelled(stop_event, "Material sidecar export preparation cancelled.")
    edit_result = apply_material_sidecar_edits(original_text, edited_values)
    raise_if_cancelled(stop_event, "Material sidecar export preparation cancelled.")
    related_files = detect_material_sidecar_related_files(
        entry,
        references=references,
        archive_entries_by_basename=archive_entries_by_basename,
    )
    return MaterialSidecarExportPreparation(edit_result, tuple(related_files))


__all__ = [
    "MaterialSidecarEditorDocument",
    "MaterialSidecarExportPreparation",
    "load_material_sidecar_editor_document",
    "prepare_material_sidecar_export",
]
