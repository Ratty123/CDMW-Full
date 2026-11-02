"""Read-only Archive Browser inspectors for localization and static data tables.

Since the October 2026 game update the game's text ships as one `.paloc` per
string domain and language, usually inside the LZ4 `paloc` container, and its
gameplay tables ship as `gamedata/binarystaticinfo__` header/body pairs instead
of `.pabgh`/`.pabgb`. Both decode through the readers Item Finder and Create New
Item already use; this module only renders them as text for the preview pane.
"""

from __future__ import annotations

import struct
from collections import Counter
from pathlib import PurePosixPath
from typing import Mapping, Optional, Sequence

from cdmw.core.archive_model_references import _StructuredBinaryPreviewBundle
from cdmw.core.paloc_format import describe_categories, language_of_paloc_path, parse_paloc
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.models import ArchiveEntry

PREVIEW_ROW_LIMIT = 200
STATIC_TABLE_HEADER_EXTENSION = ".staticinfoheader"
STATIC_TABLE_BODY_EXTENSION = ".staticinfobody"
STATIC_TABLE_EXTENSIONS = frozenset({STATIC_TABLE_HEADER_EXTENSION, STATIC_TABLE_BODY_EXTENSION})
_TEXT_COLUMN_LIMIT = 200
_FIELD_PREVIEW_ROWS = 5


def _one_line(text: str) -> str:
    flattened = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
    if len(flattened) > _TEXT_COLUMN_LIMIT:
        return flattened[: _TEXT_COLUMN_LIMIT - 3] + "..."
    return flattened


def _paloc_language_and_domain(virtual_path: str) -> tuple[str, str]:
    parts = PurePosixPath(str(virtual_path or "").replace("\\", "/").lower()).parts
    name = parts[-1][: -len(".paloc")] if parts and parts[-1].endswith(".paloc") else ""
    if name.startswith("localizationstring_"):
        return language_of_paloc_path(virtual_path), "all game text"
    return (parts[-2] if len(parts) >= 2 else ""), name


def build_paloc_preview(data: bytes, virtual_path: str) -> _StructuredBinaryPreviewBundle:
    """Decode a whole `.paloc` and list its entries in file order.

    Raises `PalocFormatError` when the payload is not a table this build can read,
    so the caller can keep its raw-bytes fallback and say why.
    """

    table = parse_paloc(data, name=virtual_path)
    language, domain = _paloc_language_and_domain(virtual_path)
    numeric = sum(1 for entry in table.entries if entry.key.isdigit())
    categories = Counter(entry.category for entry in table.entries)
    prefixes = describe_categories(table)
    if table.source_container:
        _version, stored_size, payload_size = struct.unpack_from("<III", data, 5)
        container = f"LZ4 container, {stored_size:,} compressed bytes expanding to {payload_size:,}"
    else:
        container = "Uncompressed record table"
    lines = [
        f"PALOC localization table preview for {virtual_path}",
        "",
        "Summary:",
        f"- Language folder: {language or 'unknown'}",
        f"- String domain: {domain or 'unknown'}",
        f"- Storage: {container}",
        f"- Entries: {len(table):,} ({numeric:,} numeric keys, {len(table) - numeric:,} named keys)",
        f"- Categories: {len(categories):,}",
    ]
    for category, count in categories.most_common(8):
        prefix = prefixes.get(category, "")
        lines.append(f"  - {category}{f' ({prefix})' if prefix else ''}: {count:,}")
    shown = table.entries[:PREVIEW_ROW_LIMIT]
    lines.extend(["", f"Entries in file order ({len(shown):,} of {len(table):,}):"])
    lines.extend(f"  {entry.key} = {_one_line(entry.text)}" for entry in shown)
    if len(table) > len(shown):
        lines.append(f"  ... {len(table) - len(shown):,} more")
    return _StructuredBinaryPreviewBundle(
        preview_text="\n".join(lines),
        detail_lines=(
            f"Decoded {len(table):,} localization entries.",
            "This inspector is read-only; extracting the file keeps its original bytes.",
        ),
        metadata_label="Localization Table",
    )


def static_table_companion_path(virtual_path: str) -> str:
    """The other half of a static table pair, or "" for any other file."""

    path = str(virtual_path or "")
    lowered = path.lower()
    if lowered.endswith(STATIC_TABLE_HEADER_EXTENSION):
        return path[: -len(STATIC_TABLE_HEADER_EXTENSION)] + STATIC_TABLE_BODY_EXTENSION
    if lowered.endswith(STATIC_TABLE_BODY_EXTENSION):
        return path[: -len(STATIC_TABLE_BODY_EXTENSION)] + STATIC_TABLE_HEADER_EXTENSION
    return ""


def find_static_table_companion(
    entry: ArchiveEntry,
    entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]],
) -> Optional[ArchiveEntry]:
    """The pair's other half from the same archive index; halves are never mixed across layers."""

    companion_path = static_table_companion_path(entry.path)
    if not companion_path or not entries_by_normalized_path:
        return None
    key = companion_path.replace("\\", "/").strip("/").casefold()
    for candidate in entries_by_normalized_path.get(key, ()):
        if str(candidate.pamt_path).casefold() == str(entry.pamt_path).casefold():
            return candidate
    return None


def _row_key_text(key: bytes) -> str:
    return str(int.from_bytes(key, "little")) if len(key) <= 8 else "0x" + key.hex()


def _append_decoded_fields(lines, detail, stem, body, key_width, shown) -> None:
    """Field values for tables with a closed record schema, decoded for the listed rows only."""

    from cdmw.core.static_table_records import StaticTableError, decode_record, table_kind_for_stem
    from cdmw.core.new_item_record import RecordError

    kind = table_kind_for_stem(stem)
    if kind is None:
        return
    records, refused = [], 0
    for _row, start, end in shown:
        try:
            records.append(decode_record(kind, body[start:end], start=start, key_width=key_width))
        except (RecordError, StaticTableError, UnicodeDecodeError):
            refused += 1
    lines.extend(["", f"Decoded fields ({len(records):,} of {len(shown):,} listed rows):"])
    for record in records[:_FIELD_PREVIEW_ROWS]:
        lines.append(f"  key {record.key}  {record.name}")
        for field in record.fields:
            if field.name in ("_stringKey", "_key"):
                continue
            if field.shape == "nested":
                value = f"{field.value:,} bytes"
            elif field.shape == "text":
                value = repr(_one_line(field.value))
            else:
                value = str(field.value)
            lines.append(f"    {field.name} ({field.shape}) = {value}")
    if len(records) > _FIELD_PREVIEW_ROWS:
        lines.append(f"  ... fields of {len(records) - _FIELD_PREVIEW_ROWS:,} more decoded rows not shown")
    message = f"The closed {kind} record schema decoded {len(records):,} of the {len(shown):,} listed rows."
    if refused:
        message += f" {refused:,} did not decode with it and are listed without fields."
    detail.append(message)


def build_static_table_preview(
    data: bytes,
    virtual_path: str,
    *,
    extension: str,
    companion_data: Optional[bytes] = None,
) -> _StructuredBinaryPreviewBundle:
    """List a static table's rows from its header/body pair.

    The header is the row directory: a count, then one {key, body offset} per row.
    Its count and key widths are only unambiguous against the body, so a lone half
    is described without guessing row boundaries.
    """

    is_header = str(extension or "").lower() == STATIC_TABLE_HEADER_EXTENSION
    header, body = (data, companion_data) if is_header else (companion_data, data)
    name = PurePosixPath(str(virtual_path or "").replace("\\", "/")).name
    stem = name[: -len(extension)] if name.lower().endswith(str(extension).lower()) else name
    lines = [f"Static data table preview for {virtual_path}", "", "Summary:", f"- Table: {stem}"]
    detail: list[str] = []
    if header is not None and len(header) in (1, 2, 4) and not any(header) and not body:
        lines.append("- Rows: 0 (empty table)")
        detail.append(
            "This table is empty. An empty current table replaces any older copy of the same table."
        )
    elif header is None or body is None:
        missing = static_table_companion_path(virtual_path).rsplit("/", 1)[-1]
        lines.append(f"- {'Row directory' if is_header else 'Row data'}: {len(data):,} bytes")
        detail.append(
            f"Row keys and boundaries need both halves of the pair; {missing} was not available "
            "to this preview."
        )
    else:
        try:
            table = parse_pabgh_table(header, payload=body)
        except ValueError as exc:
            lines.append(f"- Header: {len(header):,} bytes, body: {len(body):,} bytes")
            detail.append(f"The row directory did not resolve against the body: {exc}")
        else:
            layout = "name, then key" if table.key_layout == "named" else "key first"
            lines.extend(
                [
                    f"- Rows: {len(table.rows):,}",
                    f"- Row directory: {table.header_size}-byte count, {table.key_width}-byte keys",
                    f"- Row layout: {layout}",
                    f"- Body: {len(body):,} bytes",
                ]
            )
            spans = table.row_spans(len(body))
            shown = spans[:PREVIEW_ROW_LIMIT]
            lines.extend(["", f"Rows in body order ({len(shown):,} of {len(spans):,}):"])
            for row, start, end in shown:
                label = ""
                if table.key_layout == "named" and end - start >= 4:
                    length = int.from_bytes(body[start : start + 4], "little")
                    if 0 < length <= min(4096, end - start - 4):
                        label = body[start + 4 : start + 4 + length].decode("utf-8", "replace")
                lines.append(
                    f"  [{row.index}] key {_row_key_text(row.key)}"
                    f"{f'  {label}' if label else ''}  ({end - start:,} bytes)"
                )
            if len(spans) > len(shown):
                lines.append(f"  ... {len(spans) - len(shown):,} more")
            detail.append(f"Resolved {len(table.rows):,} rows from the header and body pair.")
            _append_decoded_fields(lines, detail, stem, body, table.key_width, shown)
    detail.append("This inspector is read-only.")
    return _StructuredBinaryPreviewBundle(
        preview_text="\n".join(lines),
        detail_lines=tuple(detail),
        metadata_label="Static Data Table",
    )


__all__ = [
    "PREVIEW_ROW_LIMIT",
    "STATIC_TABLE_EXTENSIONS",
    "build_paloc_preview",
    "build_static_table_preview",
    "find_static_table_companion",
    "static_table_companion_path",
]
