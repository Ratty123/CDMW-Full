"""`meta/0.papgt`: the list of archive directories the game mounts, in the order it reads
them.

The file is small and its shape is fixed: a 12-byte header, one 12-byte record per
directory, the size of the string table, and the table itself. Each record carries the
directory's flags, the offset of its name in the table, and the checksum of that
directory's `0.pamt`, which is what makes the file the head of the checksum chain the
patcher maintains.

The order matters. The game walks the list and takes the first directory that holds a
path, so a directory listed before the shipped ones overrides them, which is how a mod
can add or replace entries without touching a shipped archive at all: a new numbered
directory beside them with its own `0.pamt` and `0.paz`, named first here.

Nothing in this module writes to disk; it parses bytes and returns bytes, so a caller can
put the result inside whatever backup or transaction it already has.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from cdmw.core.archive_format import calculate_pa_checksum

__all__ = [
    "PAPGT_DEFAULT_FLAGS",
    "PapgtDirectory",
    "papgt_with_directory",
    "parse_papgt",
    "serialize_papgt",
]

#: What the sixteen shipped language-neutral data directories carry (0000-0018 and 0035).
#: The byte layout is `is_optional`, a sixteen-bit language mask, then zero: 0x00 optional,
#: 0x7FFF every language. The fourteen per-language string directories each carry one bit
#: of that mask and are marked optional (0x00000101 for the first of them, and so on).
PAPGT_DEFAULT_FLAGS = 0x007FFF00

_HEADER_BYTES = 12
_RECORD_BYTES = 12


@dataclass(frozen=True, slots=True)
class PapgtDirectory:
    """One mounted archive directory: its folder name, its flags, and its PAMT checksum."""

    name: str
    flags: int
    pamt_checksum: int


def _read_name(table: bytes, offset: int) -> str:
    if offset >= len(table):
        raise ValueError(f"PAPGT name offset {offset} is past the {len(table)}-byte string table")
    end = table.find(b"\x00", offset)
    if end < 0:
        raise ValueError(f"PAPGT name at {offset} is not terminated")
    return table[offset:end].decode("ascii")


def parse_papgt(data: bytes) -> Tuple[PapgtDirectory, ...]:
    """The directories `data` mounts, in the order the game reads them."""

    if len(data) < _HEADER_BYTES + 4:
        raise ValueError("PAPGT is too small to hold a header")
    stored = struct.unpack_from("<I", data, 4)[0]
    computed = calculate_pa_checksum(data[_HEADER_BYTES:])
    if stored != computed:
        raise ValueError(f"PAPGT checksum does not match its body: stored=0x{stored:08X} computed=0x{computed:08X}")
    # The record count is not written down: the table size follows the records, so the
    # count is the one that makes the file end exactly where the string table ends.
    for count in range(0, (len(data) - _HEADER_BYTES) // _RECORD_BYTES + 1):
        size_at = _HEADER_BYTES + count * _RECORD_BYTES
        if size_at + 4 > len(data):
            break
        table_size = struct.unpack_from("<I", data, size_at)[0]
        if size_at + 4 + table_size != len(data):
            continue
        table = data[size_at + 4 : size_at + 4 + table_size]
        out: List[PapgtDirectory] = []
        for index in range(count):
            flags, name_offset, checksum = struct.unpack_from("<III", data, _HEADER_BYTES + index * _RECORD_BYTES)
            out.append(PapgtDirectory(name=_read_name(table, name_offset), flags=flags, pamt_checksum=checksum))
        return tuple(out)
    raise ValueError("PAPGT does not end where its string table says it should")


def serialize_papgt(directories: Sequence[PapgtDirectory], *, header: bytes = b"") -> bytes:
    """`directories` back into bytes, in the order given, with the header checksum set.

    `header` carries the first twelve bytes of the file the entries came from; the first
    four and the last four are metadata this module does not interpret, so they are kept
    rather than invented.
    """

    prefix = bytes(header[:_HEADER_BYTES]) if header else b"\x00" * _HEADER_BYTES
    if len(prefix) != _HEADER_BYTES:
        raise ValueError("a PAPGT header is twelve bytes")
    table = bytearray()
    offsets: Dict[str, int] = {}
    for directory in directories:
        if directory.name not in offsets:
            offsets[directory.name] = len(table)
            table += directory.name.encode("ascii") + b"\x00"
    body = bytearray()
    for directory in directories:
        body += struct.pack("<III", int(directory.flags) & 0xFFFFFFFF, offsets[directory.name], int(directory.pamt_checksum) & 0xFFFFFFFF)
    body += struct.pack("<I", len(table)) + bytes(table)
    out = bytearray(prefix) + body
    struct.pack_into("<I", out, 4, calculate_pa_checksum(bytes(body)))
    return bytes(out)


def papgt_with_directory(
    data: bytes,
    name: str,
    pamt_checksum: int,
    *,
    flags: int = PAPGT_DEFAULT_FLAGS,
    first: bool = True,
) -> bytes:
    """`data` with `name` mounted, ahead of everything else when `first`.

    A directory already in the list keeps its place and takes the new checksum, so
    re-installing an overlay does not grow the file.
    """

    directories = list(parse_papgt(data))
    existing = next((index for index, item in enumerate(directories) if item.name == name), None)
    if existing is not None:
        directories[existing] = PapgtDirectory(name=name, flags=directories[existing].flags, pamt_checksum=int(pamt_checksum))
    else:
        entry = PapgtDirectory(name=str(name), flags=int(flags), pamt_checksum=int(pamt_checksum))
        directories.insert(0 if first else len(directories), entry)
    return serialize_papgt(directories, header=data[:_HEADER_BYTES])
