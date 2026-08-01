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


@dataclass(frozen=True, slots=True)
class PabghTable:
    row_size: int
    rows: Tuple[PabghRow, ...]
    header_size: int = 2
    proof_lines: Tuple[str, ...] = ()
    key_width: int = 4

    def row_spans(self, payload_length: int) -> Tuple[Tuple[PabghRow, int, int], ...]:
        """`(row, start, end)` per row, in payload order.

        Offsets address the companion `.pabgb`, so a row runs to the next offset
        and the last row runs to the end of the blob. This is the whole reason the
        directory exists: without it a reader has to guess where a record stops.
        """

        limit = max(0, int(payload_length))
        ordered = sorted(self.rows, key=lambda row: int(row.offset))
        usable = [row for row in ordered if 0 <= int(row.offset) < limit]
        return tuple(
            (
                row,
                int(row.offset),
                int(usable[index + 1].offset) if index + 1 < len(usable) else limit,
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


def _parse_pabgh_row_directory(header: bytes, payload: bytes) -> PabghTable | None:
    """Resolve the header's count and key widths against the row payload.

    A one-row table fits several widths arithmetically, so the inline key -- every
    row repeats its own primary key as its first field -- is what decides between
    them. Without the payload that ambiguity is unresolvable, and this returns None
    rather than guessing.
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
        if any(payload[row.offset : row.offset + key_width] != row.key for row in rows):
            continue
        return PabghTable(
            row_size=row_size,
            rows=tuple(rows),
            header_size=count_width,
            key_width=key_width,
            proof_lines=(
                f"Detected {count:,} row(s).",
                f"Resolved a {count_width}-byte count and a {key_width}-byte key against the payload.",
                "Every row repeats its own key inline.",
            ),
        )
    return None


def parse_pabgh_table(data: bytes, *, payload: bytes | None = None) -> PabghTable:
    """Parse a `.pabgh` row directory.

    `payload` is the companion `.pabgb`. Supplying it enables the general width
    search and the inline-key check; without it only the two fixed row flavors the
    structured-sidecar editor can rewrite are recognized.
    """

    header = bytes(data or b"")
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
    if payload is not None:
        resolved = _parse_pabgh_row_directory(header, bytes(payload))
        if resolved is not None:
            return resolved
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
