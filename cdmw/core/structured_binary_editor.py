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


@dataclass(frozen=True, slots=True)
class PabghTable:
    row_size: int
    rows: Tuple[PabghRow, ...]
    header_size: int = 2
    proof_lines: Tuple[str, ...] = ()


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


def parse_pabgh_table(data: bytes) -> PabghTable:
    payload = bytes(data or b"")
    if len(payload) < 2:
        raise ValueError("PABGH table is too short to contain a row count.")
    count = struct.unpack_from("<H", payload, 0)[0]
    candidates: list[tuple[int, int]] = []
    for row_size in (5, 8):
        table_end = 2 + count * row_size
        if count > 0 and table_end <= len(payload):
            valid_offsets = 0
            cursor = 2
            for _index in range(count):
                if row_size == 5:
                    target_offset = struct.unpack_from("<I", payload, cursor + 1)[0]
                else:
                    target_offset = struct.unpack_from("<I", payload, cursor + 4)[0]
                if 0 <= target_offset <= len(payload):
                    valid_offsets += 1
                cursor += row_size
            candidates.append((valid_offsets, row_size))
    if not candidates:
        raise ValueError(f"PABGH row table count {count:,} does not fit the payload.")
    row_size = max(candidates, key=lambda candidate: (candidate[0], -candidate[1]))[1]
    rows: list[PabghRow] = []
    offset = 2
    for index in range(count):
        if row_size == 5:
            row_id = payload[offset]
            target_offset = struct.unpack_from("<I", payload, offset + 1)[0]
        else:
            row_id = struct.unpack_from("<I", payload, offset)[0]
            target_offset = struct.unpack_from("<I", payload, offset + 4)[0]
        rows.append(PabghRow(index=index, row_id=row_id, offset=target_offset))
        offset += row_size
    return PabghTable(
        row_size=row_size,
        rows=tuple(rows),
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
