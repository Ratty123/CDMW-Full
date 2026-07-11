"""Cancellable, transactional structured-sidecar edit preparation."""

from __future__ import annotations

import dataclasses
import threading
from dataclasses import dataclass
from pathlib import Path

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.atomic_file import atomic_write_bytes
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.core.structured_binary_editor import (
    PabghTable,
    StructuredStringField,
    parse_length_prefixed_string_fields,
    parse_pabgh_table,
    patch_length_prefixed_string,
    rebuild_pabgh_table,
)
from cdmw.models import ArchiveEntry


@dataclass(frozen=True, slots=True)
class StructuredSidecarDocument:
    entry: ArchiveEntry
    data: bytes
    extension: str
    table: PabghTable | None = None
    fields: tuple[StructuredStringField, ...] = ()


@dataclass(frozen=True, slots=True)
class StructuredSidecarEditRequest:
    document: StructuredSidecarDocument
    output_path: Path
    selected_index: int
    replacement_text: str = ""
    replacement_offset: int | None = None


@dataclass(frozen=True, slots=True)
class StructuredSidecarEditResult:
    output_path: Path
    proof_lines: tuple[str, ...]


def load_structured_sidecar_document(
    entry: ArchiveEntry,
    *,
    stop_event: threading.Event | None = None,
) -> StructuredSidecarDocument:
    raise_if_cancelled(stop_event, "Structured sidecar loading cancelled.")
    data, _decompressed, _note = read_archive_entry_data(entry, stop_event=stop_event)
    raise_if_cancelled(stop_event, "Structured sidecar loading cancelled.")
    extension = str(entry.extension or "").lower()
    if extension == ".pabgh":
        return StructuredSidecarDocument(entry, bytes(data), extension, table=parse_pabgh_table(data))
    fields = parse_length_prefixed_string_fields(data)
    return StructuredSidecarDocument(entry, bytes(data), extension, fields=tuple(fields))


def write_structured_sidecar_edit(
    request: StructuredSidecarEditRequest,
    *,
    stop_event: threading.Event | None = None,
) -> StructuredSidecarEditResult:
    document = request.document
    raise_if_cancelled(stop_event, "Structured sidecar edit cancelled.")
    if document.extension == ".pabgh":
        table = document.table
        if table is None or not 0 <= request.selected_index < len(table.rows):
            raise ValueError("Selected PABGH row is no longer available.")
        if request.replacement_offset is None:
            raise ValueError("PABGH replacement offset is required.")
        rows = list(table.rows)
        row = rows[request.selected_index]
        rows[request.selected_index] = dataclasses.replace(
            row,
            offset=int(request.replacement_offset),
        )
        edited_data = rebuild_pabgh_table(document.data, rows, row_size=table.row_size)
        proof_lines = (
            *table.proof_lines,
            f"Edited row {request.selected_index} offset to 0x{int(request.replacement_offset):X}.",
        )
    else:
        if not 0 <= request.selected_index < len(document.fields):
            raise ValueError("Selected structured string field is no longer available.")
        patch = patch_length_prefixed_string(
            document.data,
            document.fields[request.selected_index],
            request.replacement_text,
            allow_size_change=False,
        )
        edited_data = patch.data
        proof_lines = patch.proof_lines
    raise_if_cancelled(stop_event, "Structured sidecar edit cancelled.")
    atomic_write_bytes(request.output_path, edited_data)
    return StructuredSidecarEditResult(request.output_path, tuple(proof_lines))


__all__ = [
    "StructuredSidecarDocument",
    "StructuredSidecarEditRequest",
    "StructuredSidecarEditResult",
    "load_structured_sidecar_document",
    "write_structured_sidecar_edit",
]
