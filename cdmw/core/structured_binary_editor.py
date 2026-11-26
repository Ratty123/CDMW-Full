from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Sequence, Tuple


@dataclass(frozen=True, slots=True)
class StructuredStringField:
    index: int
    offset: int
    length: int
    text: str
    kind: str = "string"


@dataclass(frozen=True, slots=True)
class StructuredStringPatchResult:
    data: bytes
    field: StructuredStringField
    resized: bool = False
    proof_lines: Tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PabghRow:
    index: int
    row_id: int
    offset: int
    #: Raw primary key bytes. Wider than `row_id` for the composite-key tables,
    #: where `row_id` holds only the leading u32.
    key: bytes = b""
    string_key: str = ""
    size: int | None = None


@dataclass(frozen=True, slots=True)
class PabghTable:
    row_size: int
    rows: Tuple[PabghRow, ...]
    header_size: int = 2
    proof_lines: Tuple[str, ...] = ()
    key_width: int = 4
    key_layout: str = "prefix"
    header_format: str = "legacy"

    def row_spans(self, payload_length: int) -> Tuple[Tuple[PabghRow, int, int], ...]:
        """`(row, start, end)` per row, in payload order.

        Offsets address the companion `.pabgb`, so a row runs to the next offset
        and the last row runs to the end of the blob. When `row.size` is set
        (the 1.0.0.3840 `.staticinfoheader` format), it gives the exact end.
        """

        limit = max(0, int(payload_length))
        ordered = sorted(self.rows, key=lambda row: int(row.offset))
        usable = [row for row in ordered if 0 <= int(row.offset) < limit]
        return tuple(
            (
                row,
                int(row.offset),
                min(limit, int(row.offset) + int(row.size))
                if row.size is not None
                else (int(usable[index + 1].offset) if index + 1 < len(usable) else limit),
            )
            for index, row in enumerate(usable)
        )


def _looks_like_editable_text(raw: bytes) -> bool:
    if not raw:
        return False
    if b"\x00" in raw[:-1]:
        return False
    try:
        text = raw.rstrip(b"\x00").decode("utf-8")
    except UnicodeDecodeError:
        return False
    stripped = text.strip()
    if not stripped:
        return False
    printable = sum(1 for char in stripped if char.isprintable())
    return printable >= max(1, int(len(stripped) * 0.8))


def classify_structured_string(text: str) -> str:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return "empty"
    if lowered.endswith((".paa", ".paao", ".hkx", ".hkt")) or "/animation/" in lowered:
        return "animation"
    if lowered.endswith((".pac", ".pam", ".pamlod", ".prefab", ".dds")):
        return "asset_path"
    if lowered.startswith(("bgm_", "sfx_", "vce_", "event:/", "wwise")):
        return "audio_event"
    if "/" in lowered or "\\" in lowered:
        return "object_path"
    return "text"


def parse_length_prefixed_string_fields(
    data: bytes,
    *,
    max_length: int = 4096,
    scan_limit: int = 262_144,
) -> Tuple[StructuredStringField, ...]:
    payload = bytes(data or b"")
    fields: list[StructuredStringField] = []
    seen: set[tuple[int, int]] = set()
    limit = min(len(payload), max(0, int(scan_limit)))
    for offset in range(0, max(0, limit - 4)):
        length = struct.unpack_from("<I", payload, offset)[0]
        if length <= 0 or length > max_length:
            continue
        start = offset + 4
        end = start + length
        if end > len(payload):
            continue
        raw = payload[start:end]
        if not _looks_like_editable_text(raw):
            continue
        text = raw.rstrip(b"\x00").decode("utf-8", errors="replace")
        key = (start, end)
        if key in seen:
            continue
        seen.add(key)
        fields.append(
            StructuredStringField(
                index=len(fields),
                offset=offset,
                length=length,
                text=text,
                kind=classify_structured_string(text),
            )
        )
    return tuple(fields)


def patch_length_prefixed_string(
    data: bytes,
    field: StructuredStringField,
    replacement_text: str,
    *,
    allow_size_change: bool = False,
) -> StructuredStringPatchResult:
    payload = bytearray(data or b"")
    if field.offset < 0 or field.offset + 4 + field.length > len(payload):
        raise ValueError("String field is outside the binary payload.")
    replacement = str(replacement_text or "").encode("utf-8")
    original_length = int(field.length)
    if not allow_size_change and len(replacement) > original_length:
        raise ValueError(
            f"Replacement is {len(replacement):,} byte(s), but the fixed-size field allows {original_length:,}."
        )
    start = field.offset + 4
    end = start + original_length
    proof = [
        f"String field {field.index} starts at 0x{field.offset:X}.",
        f"Original length prefix: {original_length:,} byte(s).",
    ]
    if allow_size_change:
        payload[field.offset : field.offset + 4] = struct.pack("<I", len(replacement))
        payload[start:end] = replacement
        proof.append(f"Size-changing edit wrote new length prefix {len(replacement):,}.")
        return StructuredStringPatchResult(
            data=bytes(payload),
            field=field,
            resized=len(replacement) != original_length,
            proof_lines=tuple(proof),
        )
    padded = replacement + b"\x00" * (original_length - len(replacement))
    payload[start:end] = padded
    proof.append("Fixed-size edit preserved the original length prefix and payload span.")
    return StructuredStringPatchResult(data=bytes(payload), field=field, resized=False, proof_lines=tuple(proof))


#: Header count fields and primary keys are both variable width, so both are
#: resolved by search against the payload rather than assumed. Composite keys
#: (8 and 12 bytes) are real: `characterappearanceindexinfo` uses 8 and
#: `aieventtableinfo` uses 12, and a reader that allows only 1/2/4 drops them.
_PABGH_COUNT_WIDTHS = (1, 2, 4)
_PABGH_KEY_WIDTHS = (1, 2, 4, 8, 12)


def table_row_key(raw: bytes, key_width: int, key_layout: str = "prefix") -> bytes:
    """Read the qualified key position, including compact name-before-key rows."""
    offset = 0
    if key_layout == "named":
        if len(raw) < 4:
            raise ValueError("Truncated compact table row name.")
        length = int.from_bytes(raw[:4], "little")
        offset = 4 + length
        if length > 4096 or offset + key_width > len(raw):
            raise ValueError("Invalid compact table row name boundary.")
        raw[4:offset].decode("utf-8")
    elif key_layout not in ("prefix", "indexed"):
        raise ValueError("Unknown table key layout.")
    if offset + key_width > len(raw):
        raise ValueError("Table row is shorter than its key.")
    return raw[offset:offset + key_width]


def encode_staticinfo_3840_header(
    count_width: int,
    rows: Sequence[tuple[bytes, str, int, int]],
) -> bytes:
    """Encode a 1.0.0.3840 variable-length `.staticinfoheader` directory."""
    if count_width not in _PABGH_COUNT_WIDTHS:
        raise ValueError(f"Unsupported directory count width: {count_width}")
    total = len(rows)
    if total >= 1 << (8 * count_width):
        raise ValueError(f"{total:,} rows do not fit the header's {count_width}-byte count.")
    out = bytearray(total.to_bytes(count_width, "little"))
    for key, string_key, offset, size in rows:
        sk_bytes = str(string_key or "").encode("utf-8")
        out += bytes(key)
        out += struct.pack("<I", len(sk_bytes))
        out += sk_bytes
        out += struct.pack("<II", int(offset), int(size))
    return bytes(out)


def next_static_info_index(*pairs: object) -> int:
    """Return max `_staticInfoIndex` + 1 across `(payload, header)` pairs, or 0 if empty/pre-3840.

    Accepts either `next_static_info_index(payload, header)` or `next_static_info_index((p1, h1), ...)`.
    """
    if (
        len(pairs) == 2
        and isinstance(pairs[0], (bytes, bytearray, memoryview))
        and isinstance(pairs[1], (bytes, bytearray, memoryview))
    ):
        resolved_pairs: tuple[tuple[object, object], ...] = ((pairs[0], pairs[1]),)
    else:
        resolved_pairs = tuple(pairs)  # type: ignore[assignment]
    max_index = -1
    saw_indexed = False
    for payload, header in resolved_pairs:
        if not header:
            continue
        table = parse_pabgh_table(bytes(header), payload=bytes(payload or b""))
        if table.key_layout != "indexed":
            continue
        saw_indexed = True
        payload_bytes = bytes(payload or b"")
        key_width = int(table.key_width)
        for _row, start, end in table.row_spans(len(payload_bytes)):
            if end - start >= key_width + 4:
                index = struct.unpack_from("<I", payload_bytes, start + key_width)[0]
                if index > max_index:
                    max_index = index
    return (max_index + 1) if saw_indexed else 0


def set_row_static_info_index(row: bytes, key_width: int, index: int) -> bytes:
    """Stamp `_staticInfoIndex` (u32 immediately after the inline key) in a 1.0.0.3840 body row."""
    raw = bytes(row)
    if key_width <= 0 or len(raw) < key_width + 4:
        raise ValueError(f"Row is too short ({len(raw)} byte(s)) to hold a {key_width}-byte key and 4-byte index.")
    return raw[:key_width] + struct.pack("<I", int(index)) + raw[key_width + 4 :]


def _parse_staticinfo_3840_directory(header: bytes, payload: bytes) -> PabghTable | None:
    """Resolve the 1.0.0.3840 variable-length `.staticinfoheader` directory.

    Record layout: ``<count: u8|u16|u32>`` followed by ``count`` variable entries:
    ``key[key_width], string_key_len[u32], string_key[utf-8], body_offset[u32], body_size[u32]``.
    """
    payload_len = len(payload)
    for count_width in _PABGH_COUNT_WIDTHS:
        if len(header) < count_width:
            continue
        count = int.from_bytes(header[:count_width], "little")
        if count == 0:
            if len(header) == count_width and payload_len == 0:
                return PabghTable(
                    row_size=0,
                    rows=(),
                    header_size=count_width,
                    key_width=4,
                    key_layout="indexed",
                    header_format="indexed_3840",
                    proof_lines=(
                        "Detected 0 row(s) in indexed .staticinfoheader directory.",
                    ),
                )
            continue
        for key_width in _PABGH_KEY_WIDTHS:
            pos = count_width
            usable = True
            rows: list[PabghRow] = []
            for index in range(count):
                if pos + key_width + 4 > len(header):
                    usable = False
                    break
                key = header[pos : pos + key_width]
                pos += key_width
                sk_len = struct.unpack_from("<I", header, pos)[0]
                pos += 4
                if sk_len > 4096 or pos + sk_len + 8 > len(header):
                    usable = False
                    break
                try:
                    sk = header[pos : pos + sk_len].decode("utf-8")
                except UnicodeDecodeError:
                    usable = False
                    break
                pos += sk_len
                offset, size = struct.unpack_from("<II", header, pos)
                pos += 8
                if size < key_width or offset + size > payload_len:
                    usable = False
                    break
                if payload[offset : offset + key_width] != key:
                    usable = False
                    break
                rows.append(
                    PabghRow(
                        index=index,
                        row_id=int.from_bytes(key[:4], "little"),
                        offset=offset,
                        key=bytes(key),
                        string_key=sk,
                        size=size,
                    )
                )
            if not usable or pos != len(header):
                continue
            ordered = sorted(rows, key=lambda r: (r.offset, r.size or 0))
            expected_off = 0
            contiguous = True
            for r in ordered:
                if r.offset != expected_off:
                    contiguous = False
                    break
                expected_off += int(r.size or 0)
            if not contiguous or expected_off != payload_len:
                continue
            return PabghTable(
                row_size=0,
                rows=tuple(rows),
                header_size=count_width,
                key_width=key_width,
                key_layout="indexed",
                header_format="indexed_3840",
                proof_lines=(
                    f"Detected {count:,} row(s) in 1.0.0.3840 indexed directory.",
                    f"Resolved a {count_width}-byte count and a {key_width}-byte inline key with internal names in the header.",
                ),
            )
    return None


def _parse_pabgh_row_directory(header: bytes, payload: bytes) -> PabghTable | None:
    """Resolve the header's count and key widths against the row payload.

    A one-row table fits several widths arithmetically. Match every inline key,
    either at the row start or after its compact name, to resolve the layout.
    Without the payload that ambiguity is unresolvable, so return None.
    """

    for count_width in _PABGH_COUNT_WIDTHS:
        if len(header) < count_width:
            continue
        count = int.from_bytes(header[:count_width], "little")
        if count <= 0:
            continue
        remainder = len(header) - count_width
        if remainder % count:
            continue
        row_size = remainder // count
        key_width = row_size - 4
        if key_width not in _PABGH_KEY_WIDTHS:
            continue
        rows: list[PabghRow] = []
        cursor = count_width
        previous = -1
        usable = True
        for index in range(count):
            key = header[cursor : cursor + key_width]
            target_offset = struct.unpack_from("<I", header, cursor + key_width)[0]
            if target_offset <= previous:
                usable = False
                break
            previous = target_offset
            rows.append(
                PabghRow(
                    index=index,
                    row_id=int.from_bytes(key[:4], "little"),
                    offset=target_offset,
                    key=bytes(key),
                )
            )
            cursor += row_size
        if not usable or not rows:
            continue
        if rows[0].offset != 0 or rows[-1].offset >= len(payload):
            continue
        key_layout = None
        for candidate in ("prefix", "named"):
            try:
                if all(table_row_key(payload[row.offset:rows[index + 1].offset if index + 1 < count else len(payload)],
                                     key_width, candidate) == row.key for index, row in enumerate(rows)):
                    key_layout = candidate
                    break
            except (ValueError, UnicodeError):
                pass
        if key_layout is None:
            continue
        return PabghTable(
            row_size=row_size,
            rows=tuple(rows),
            header_size=count_width,
            key_width=key_width,
            key_layout=key_layout,
            proof_lines=(
                f"Detected {count:,} row(s).",
                f"Resolved a {count_width}-byte count and a {key_width}-byte key against the payload.",
                "Every row repeats its own key inline.",
            ),
        )
    return None


def parse_pabgh_table(data: bytes, *, payload: bytes | None = None) -> PabghTable:
    """Parse a `.pabgh` or `.staticinfoheader` row directory.

    `payload` is the companion `.pabgb`/`.staticinfobody`. Supplying it enables the
    general width search, 1.0.0.3840 variable-length directory parsing, and inline-key checks;
    without it only the two fixed row flavors the structured-sidecar editor can rewrite
    are recognized.
    """

    header = bytes(data or b"")
    if len(header) < (1 if payload is not None else 2):
        raise ValueError("PABGH table is too short to contain a row count.")
    if payload is not None:
        resolved = _parse_pabgh_row_directory(header, bytes(payload))
        if resolved is not None:
            return resolved
        indexed = _parse_staticinfo_3840_directory(header, bytes(payload))
        if indexed is not None:
            return indexed
    if len(header) < 2:
        raise ValueError("PABGH table is too short to contain a row count.")
    count = struct.unpack_from("<H", header, 0)[0]
    exact_row_sizes = [
        row_size
        for row_size in (8, 5)
        if count > 0 and 2 + count * row_size == len(header)
    ]
    if exact_row_sizes:
        row_size = exact_row_sizes[0]
        rows: list[PabghRow] = []
        offset = 2
        for index in range(count):
            if row_size == 5:
                key = header[offset : offset + 1]
            else:
                key = header[offset : offset + 4]
            target_offset = struct.unpack_from("<I", header, offset + row_size - 4)[0]
            rows.append(
                PabghRow(
                    index=index,
                    row_id=int.from_bytes(key, "little"),
                    offset=target_offset,
                    key=bytes(key),
                )
            )
            offset += row_size
        return PabghTable(
            row_size=row_size,
            rows=tuple(rows),
            key_width=row_size - 4,
            proof_lines=(
                f"Detected {count:,} row(s).",
                f"Detected exact {row_size}-byte row flavor.",
            ),
        )
    candidates: list[tuple[int, int]] = []
    for row_size in (5, 8):
        table_end = 2 + count * row_size
        if count > 0 and table_end <= len(header):
            valid_offsets = 0
            cursor = 2
            for _index in range(count):
                target_offset = struct.unpack_from("<I", header, cursor + row_size - 4)[0]
                if 0 <= target_offset <= len(header):
                    valid_offsets += 1
                cursor += row_size
            candidates.append((valid_offsets, row_size))
    if not candidates:
        raise ValueError(f"PABGH row table count {count:,} does not fit the payload.")
    row_size = max(candidates, key=lambda candidate: (candidate[0], -candidate[1]))[1]
    rows: list[PabghRow] = []
    offset = 2
    for index in range(count):
        key = header[offset : offset + (1 if row_size == 5 else 4)]
        target_offset = struct.unpack_from("<I", header, offset + row_size - 4)[0]
        rows.append(
            PabghRow(
                index=index,
                row_id=int.from_bytes(key, "little"),
                offset=target_offset,
                key=bytes(key),
            )
        )
        offset += row_size
    return PabghTable(
        row_size=row_size,
        rows=tuple(rows),
        key_width=row_size - 4,
        proof_lines=(
            f"Detected {count:,} row(s).",
            f"Detected {row_size}-byte row flavor.",
        ),
    )


def append_table_rows(
    payload: bytes,
    header: bytes,
    rows: Sequence[bytes],
    *,
    string_keys: Sequence[str] | None = None,
) -> Tuple[bytes, bytes]:
    """Append whole rows to a `.pabgb`/`.staticinfobody` payload and register them in its directory."""

    payload_bytes = bytes(payload or b"")
    header_bytes = bytes(header or b"")
    table = parse_pabgh_table(header_bytes, payload=payload_bytes)
    key_width = int(table.key_width)
    count_width = int(table.header_size)
    if table.header_format == "indexed_3840":
        names = tuple("" for _ in rows) if string_keys is None else tuple(str(name) for name in string_keys)
        if len(names) != len(rows):
            raise ValueError(f"Expected {len(rows)} string_keys for appended indexed rows, got {len(names)}.")
        entries: list[tuple[bytes, str, int, int]] = [
            (bytes(r.key), r.string_key, int(r.offset), int(r.size or 0))
            for r in table.rows
        ]
        known_keys = {bytes(row.key) for row in table.rows}
        new_payload = bytearray(payload_bytes)
        for index, (row, sk) in enumerate(zip(rows, names)):
            row_bytes = bytes(row)
            if len(row_bytes) < key_width:
                raise ValueError(f"Row {index} is {len(row_bytes)} byte(s), shorter than the {key_width}-byte key.")
            key = table_row_key(row_bytes, key_width, table.key_layout)
            if key in known_keys:
                raise ValueError(f"Row {index} repeats key {key.hex()} which the table already holds.")
            known_keys.add(key)
            entries.append((key, sk, len(new_payload), len(row_bytes)))
            new_payload += row_bytes
        new_header = encode_staticinfo_3840_header(count_width, entries)
        check = parse_pabgh_table(new_header, payload=bytes(new_payload))
        if len(check.rows) != len(entries) or check.key_width != key_width:
            raise ValueError("The extended table does not parse back the way it was written.")
        return bytes(new_payload), new_header

    directory_row_size = key_width + 4
    if len(header_bytes) != count_width + len(table.rows) * directory_row_size:
        raise ValueError(
            f"PABGH header is {len(header_bytes):,} bytes, not the {count_width + len(table.rows) * directory_row_size:,} "
            f"its {len(table.rows):,} directory row(s) imply."
        )
    known_keys = {bytes(row.key) for row in table.rows}
    new_payload = bytearray(payload_bytes)
    new_directory = bytearray()
    for index, row in enumerate(rows):
        row_bytes = bytes(row)
        if len(row_bytes) < key_width:
            raise ValueError(f"Row {index} is {len(row_bytes)} byte(s), shorter than the {key_width}-byte key.")
        key = table_row_key(row_bytes, key_width, table.key_layout)
        if key in known_keys:
            raise ValueError(f"Row {index} repeats key {key.hex()} which the table already holds.")
        known_keys.add(key)
        new_directory += key + struct.pack("<I", len(new_payload))
        new_payload += row_bytes
    total = len(table.rows) + len(rows)
    if total >= 1 << (8 * count_width):
        raise ValueError(f"{total:,} rows do not fit the header's {count_width}-byte count.")
    new_header = total.to_bytes(count_width, "little") + header_bytes[count_width:] + bytes(new_directory)
    check = parse_pabgh_table(new_header, payload=bytes(new_payload))
    if len(check.rows) != total or check.key_width != key_width:
        raise ValueError("The extended table does not parse back the way it was written.")
    return bytes(new_payload), new_header


def replace_table_row(
    payload: bytes,
    header: bytes,
    key: bytes | int,
    new_row: bytes,
    *,
    string_key: str | None = None,
) -> Tuple[bytes, bytes]:
    """Replace one row's bytes in a payload, shifting later offsets and updating its directory entry."""

    payload_bytes = bytes(payload or b"")
    header_bytes = bytes(header or b"")
    table = parse_pabgh_table(header_bytes, payload=payload_bytes)
    key_width = int(table.key_width)
    count_width = int(table.header_size)
    key_bytes = int(key).to_bytes(key_width, "little") if isinstance(key, int) else bytes(key)
    if len(key_bytes) != key_width:
        raise ValueError(f"Key is {len(key_bytes)} byte(s); this table's keys are {key_width}.")
    row_bytes = bytes(new_row)
    if len(row_bytes) < key_width or table_row_key(row_bytes, key_width, table.key_layout) != key_bytes:
        raise ValueError("The replacement row must begin with the row's own key.")
    matches = [row for row in table.rows if bytes(row.key) == key_bytes]
    if len(matches) != 1:
        raise ValueError(f"Key {key_bytes.hex()} matches {len(matches)} directory row(s); expected exactly one.")
    target = matches[0]
    spans = table.row_spans(len(payload_bytes))
    span = next(((start, end) for row, start, end in spans if row.index == target.index), None)
    if span is None:
        raise ValueError(f"Directory row {target.index} points outside the payload.")
    start, end = span
    delta = len(row_bytes) - (end - start)
    new_payload = payload_bytes[:start] + row_bytes + payload_bytes[end:]

    if table.header_format == "indexed_3840":
        entries = []
        for row in table.rows:
            if row.index == target.index:
                entries.append((
                    bytes(row.key),
                    row.string_key if string_key is None else str(string_key),
                    int(row.offset),
                    len(row_bytes),
                ))
            else:
                new_off = int(row.offset) + delta if int(row.offset) > start else int(row.offset)
                entries.append((bytes(row.key), row.string_key, new_off, int(row.size or 0)))
        new_header_bytes = encode_staticinfo_3840_header(count_width, entries)
        check = parse_pabgh_table(new_header_bytes, payload=new_payload)
        if len(check.rows) != len(table.rows) or check.key_width != key_width:
            raise ValueError("The table does not parse back the way it was rewritten.")
        return new_payload, new_header_bytes

    directory_row_size = key_width + 4
    if len(header_bytes) != count_width + len(table.rows) * directory_row_size:
        raise ValueError(
            f"PABGH header is {len(header_bytes):,} bytes, not the {count_width + len(table.rows) * directory_row_size:,} "
            f"its {len(table.rows):,} directory row(s) imply."
        )
    new_header = bytearray(header_bytes)
    for row in table.rows:
        if row.offset > start:
            offset_at = count_width + row.index * directory_row_size + key_width
            struct.pack_into("<I", new_header, offset_at, row.offset + delta)
    check = parse_pabgh_table(bytes(new_header), payload=new_payload)
    if len(check.rows) != len(table.rows) or check.key_width != key_width:
        raise ValueError("The table does not parse back the way it was rewritten.")
    return new_payload, bytes(new_header)


def rebuild_pabgh_table(data: bytes, rows: Sequence[PabghRow], *, row_size: int) -> bytes:
    if row_size not in {5, 8}:
        raise ValueError("PABGH row size must be 5 or 8 bytes.")
    payload = bytearray(data or b"")
    table_size = 2 + len(rows) * row_size
    if table_size > len(payload):
        raise ValueError("Edited PABGH table would exceed the original payload size.")
    payload[0:2] = struct.pack("<H", len(rows))
    cursor = 2
    for row in rows:
        row_id = int(row.row_id)
        target_offset = int(row.offset)
        if target_offset < 0 or target_offset > len(payload):
            raise ValueError(f"PABGH row {row.index} points outside the payload.")
        if row_size == 5:
            if not 0 <= row_id <= 0xFF:
                raise ValueError(f"PABGH 5-byte row id must fit in u8: {row_id}.")
            payload[cursor] = row_id
            payload[cursor + 1 : cursor + 5] = struct.pack("<I", target_offset)
        else:
            payload[cursor : cursor + 4] = struct.pack("<I", row_id & 0xFFFFFFFF)
            payload[cursor + 4 : cursor + 8] = struct.pack("<I", target_offset)
        cursor += row_size
    return bytes(payload)
