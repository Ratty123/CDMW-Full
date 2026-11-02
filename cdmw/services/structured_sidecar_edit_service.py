"""Cancellable, transactional structured-sidecar edit preparation."""

from __future__ import annotations

import dataclasses
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

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
from cdmw.core.static_table_records import apply_field_edits, require_same_archive, require_table_kind
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


@dataclass(frozen=True, slots=True)
class StaticTableEditRequest:
    """Whitelisted field edits for one static table pair, written as loose files."""

    stem: str
    header: bytes
    body: bytes
    edits: Mapping[tuple[int, str], object]
    output_dir: Path


@dataclass(frozen=True, slots=True)
class StaticTableEditResult:
    header_path: Path
    body_path: Path
    proof_lines: tuple[str, ...]


def load_static_table_pair(
    header_entry: ArchiveEntry,
    body_entry: ArchiveEntry,
    *,
    stop_event: threading.Event | None = None,
) -> tuple[bytes, bytes]:
    """Read both halves of one table pair; they must come from the same archive index."""

    require_same_archive(header_entry.pamt_path, body_entry.pamt_path)
    raise_if_cancelled(stop_event, "Structured sidecar loading cancelled.")
    header = read_archive_entry_data(header_entry, stop_event=stop_event)[0]
    raise_if_cancelled(stop_event, "Structured sidecar loading cancelled.")
    body = read_archive_entry_data(body_entry, stop_event=stop_event)[0]
    return bytes(header), bytes(body)


def write_static_table_edits(
    request: StaticTableEditRequest,
    *,
    stop_event: threading.Event | None = None,
) -> StaticTableEditResult:
    """Apply constrained field edits and write the edited pair under `output_dir`.

    Only loose files are written; installing them is the mod manager's job.
    """

    kind = require_table_kind(request.stem)
    raise_if_cancelled(stop_event, "Structured sidecar edit cancelled.")
    edit = apply_field_edits(kind, request.header, request.body, request.edits)
    raise_if_cancelled(stop_event, "Structured sidecar edit cancelled.")
    output_dir = Path(request.output_dir)
    header_path = output_dir / f"{request.stem}.staticinfoheader"
    body_path = output_dir / f"{request.stem}.staticinfobody"
    atomic_write_bytes(body_path, edit.body)
    atomic_write_bytes(header_path, edit.header)
    proof = [f"{request.stem}: {len(edit.changes)} field(s) rewritten in place; row directory unchanged."]
    proof.extend(f"Row {c.key} {c.field}: {c.before} -> {c.after}" for c in edit.changes)
    return StaticTableEditResult(header_path, body_path, tuple(proof))


__all__ = [
    "StaticTableEditRequest",
    "StaticTableEditResult",
    "StructuredSidecarDocument",
    "StructuredSidecarEditRequest",
    "StructuredSidecarEditResult",
    "load_static_table_pair",
    "load_structured_sidecar_document",
    "write_static_table_edits",
    "write_structured_sidecar_edit",
]
