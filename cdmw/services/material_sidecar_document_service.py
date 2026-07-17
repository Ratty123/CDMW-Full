"""Cancellable material-sidecar loading for the editor UI."""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.core.material_sidecar_editor import (
    MaterialSidecarEditResult,
    MaterialSidecarEditableValue,
    MaterialSidecarRelatedFile,
    detect_material_sidecar_related_files,
    material_sidecar_rows_from_document,
)
from cdmw.domain.pac_xml_editor import PacXmlDocument, PacXmlSourceFormat, parse_pac_xml_document, parse_pac_xml_payload
from cdmw.models import ArchiveEntry, ArchiveModelTextureReference


@dataclass(frozen=True, slots=True)
class MaterialSidecarEditorDocument:
    entry: ArchiveEntry
    original_text: str
    rows: tuple[MaterialSidecarEditableValue, ...]
    parsed_document: PacXmlDocument
    original_payload: bytes
    source_format: PacXmlSourceFormat


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
    parsed_document = parse_pac_xml_payload(data)
    original_text = parsed_document.text
    raise_if_cancelled(stop_event, "Material sidecar loading cancelled.")
    rows = material_sidecar_rows_from_document(parsed_document)
    return MaterialSidecarEditorDocument(
        entry=entry,
        original_text=original_text,
        rows=rows,
        parsed_document=parsed_document,
        original_payload=bytes(data),
        source_format=parsed_document.source_format,
    )


def prepare_material_sidecar_export(
    entry: ArchiveEntry,
    original_text: str,
    edited_values: Mapping[str, str],
    *,
    references: Sequence[ArchiveModelTextureReference] = (),
    archive_entries_by_basename: Mapping[str, Sequence[ArchiveEntry]] | None = None,
    original_payload: bytes = b"",
    stop_event: threading.Event | None = None,
) -> MaterialSidecarExportPreparation:
    raise_if_cancelled(stop_event, "Material sidecar export preparation cancelled.")
    if original_payload:
        parsed_document = parse_pac_xml_payload(original_payload)
        rendered = parsed_document.render(edited_values)
        edit_result = MaterialSidecarEditResult(
            text=rendered.text,
            changed_rows=rendered.changed_rows,
            payload=rendered.payload,
            structural_signature=rendered.structural_signature,
        )
    else:
        # Compatibility path for callers that only have decoded text.
        parsed_document = parse_pac_xml_document(original_text)
        rendered = parsed_document.render(edited_values)
        edit_result = MaterialSidecarEditResult(
            text=rendered.text,
            changed_rows=rendered.changed_rows,
            payload=rendered.payload,
            structural_signature=rendered.structural_signature,
        )
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
