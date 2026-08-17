"""`gamedata/binary__/client/bin/stringinfo.pabgb`: the game's hash-to-string dictionary.

Game tables refer to model stems, icon names, socket names and similar identifiers
by `hashlittle(text, 0xC5EDE)`; StringInfo is where the runtime turns such a hash
back into its text. Every one of the 31,438 shipped rows keys itself by exactly
that hash, and each row is

    u32 key         hashlittle(text, 0xC5EDE)
    u8[5]           zero
    u32 length      byte length of the text (no terminator)
    utf-8 text

so a row is 13 + length bytes and the `.pabgh` directory row for it is the same
key plus its offset. A brand-new stem the ItemInfo table wants to name therefore
needs one appended row here, which :func:`append_stringinfo_strings` builds.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence, Tuple

from cdmw.core.archive_format import hashlittle
from cdmw.core.structured_binary_editor import append_table_rows, parse_pabgh_table

STRINGINFO_HASH_INIT = 0xC5EDE
_ROW_HEAD = struct.calcsize("<I5sI")


class StringInfoFormatError(ValueError):
    """Raised when a payload/header pair is not a StringInfo table."""


@dataclass(frozen=True, slots=True)
class StringInfoRow:
    key: int
    text: str


def stringinfo_key(text: str) -> int:
    """The key the game files use for `text`."""

    return int(hashlittle(str(text).encode("utf-8"), STRINGINFO_HASH_INIT)) & 0xFFFFFFFF


def build_stringinfo_row(text: str) -> bytes:
    raw = str(text).encode("utf-8")
    return struct.pack("<I5sI", stringinfo_key(text), b"\x00" * 5, len(raw)) + raw


def parse_stringinfo(payload: bytes, header: bytes, *, name: str = "") -> Tuple[StringInfoRow, ...]:
    """Every row, in payload order, checked against the layout above."""

    where = f" ({name})" if name else ""
    payload_bytes = bytes(payload or b"")
    try:
        table = parse_pabgh_table(bytes(header or b""), payload=payload_bytes)
    except ValueError as exc:
        raise StringInfoFormatError(f"the .pabgh directory does not parse{where}: {exc}") from exc
    if table.key_width != 4:
        raise StringInfoFormatError(f"StringInfo keys are 4 bytes, this directory has {table.key_width}{where}")
    rows: list[StringInfoRow] = []
    for row, start, end in table.row_spans(len(payload_bytes)):
        if end - start < _ROW_HEAD:
            raise StringInfoFormatError(f"row {row.index} at 0x{start:X} is shorter than a row head{where}")
        key, zeros, length = struct.unpack_from("<I5sI", payload_bytes, start)
        if key != row.row_id:
            raise StringInfoFormatError(f"row {row.index} at 0x{start:X} does not repeat its directory key{where}")
        if zeros != b"\x00" * 5:
            raise StringInfoFormatError(f"row {row.index} at 0x{start:X} carries non-zero padding{where}")
        if end - start != _ROW_HEAD + length:
            raise StringInfoFormatError(
                f"row {row.index} at 0x{start:X} spans {end - start} bytes but declares {length}{where}"
            )
        try:
            text = payload_bytes[start + _ROW_HEAD : end].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise StringInfoFormatError(f"row {row.index} at 0x{start:X} is not UTF-8{where}: {exc}") from exc
        if stringinfo_key(text) != key:
            raise StringInfoFormatError(f"row {row.index} {text!r} is not keyed by its own hash{where}")
        rows.append(StringInfoRow(key=key, text=text))
    return tuple(rows)


def stringinfo_index(rows: Iterable[StringInfoRow]) -> Mapping[int, str]:
    return {row.key: row.text for row in rows}


def append_stringinfo_strings(
    payload: bytes,
    header: bytes,
    texts: Sequence[str],
    *,
    name: str = "",
) -> Tuple[bytes, bytes, Tuple[int, ...]]:
    """Make every text in `texts` resolvable; return (payload, header, keys).

    Texts the table already holds are left alone and their existing keys are
    returned, so a caller can hand over the full set of names it needs without
    first asking which are new. A hash that already keys a *different* text is a
    collision the game could not tell apart, and is refused.
    """

    existing = stringinfo_index(parse_stringinfo(payload, header, name=name))
    keys: list[int] = []
    new_rows: list[bytes] = []
    pending: dict[int, str] = {}
    for text in texts:
        text = str(text)
        key = stringinfo_key(text)
        keys.append(key)
        held = existing.get(key)
        if held is not None:
            if held != text:
                raise StringInfoFormatError(f"{text!r} hashes to 0x{key:08X}, which already names {held!r}")
            continue
        queued = pending.get(key)
        if queued is not None:
            if queued != text:
                raise StringInfoFormatError(f"{text!r} and {queued!r} both hash to 0x{key:08X}")
            continue
        pending[key] = text
        new_rows.append(build_stringinfo_row(text))
    if not new_rows:
        return bytes(payload), bytes(header), tuple(keys)
    new_payload, new_header = append_table_rows(payload, header, new_rows)
    return new_payload, new_header, tuple(keys)


__all__ = [
    "STRINGINFO_HASH_INIT",
    "StringInfoFormatError",
    "StringInfoRow",
    "append_stringinfo_strings",
    "build_stringinfo_row",
    "parse_stringinfo",
    "stringinfo_index",
    "stringinfo_key",
]
