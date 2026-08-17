"""`meta/0.pathc`: the texture registry, and how to register a new texture in it.

The game does not open a `.dds` by its archive record alone: it looks the path up
here first, by `calculate_pa_checksum("/" + path)`, and takes the DDS header (and
the per-mip block sizes) from this table. A texture that is in the archive but not
in here draws as the placeholder bag; that is what the first phase 6 icon check
showed (2026-08-17), and it is why the mod managers rebuild this file.

Layout, measured on the shipped file (6,942,328 bytes, 648 headers, 285,224 entries,
12 collisions), which the reader in `archive_preview_support` decodes to the byte:

    u64 reserved (0)
    u32 header_size (148 = a 128-byte DDS header + 20)
    u32 header_count, u32 entry_count, u32 collision_count, u32 filenames_length
    header_count x header_size          distinct DDS headers, shared by every texture of that shape
    entry_count x u32                   path checksums, strictly ascending and unique
    entry_count x { u16 header_index, u8 collision_start, u8 collision_end, 16 bytes block infos }
                                        parallel to the checksums; header 0xFFFF means "see collisions"
    collision_count x { u32 name_offset, u16 header_index, u16 unknown, 16 bytes block infos }
    filenames_length bytes              NUL-terminated names for the collision rows

Registering a texture is one checksum + one entry row slotted into the ascending
order, pointing at the header its bytes already match (7,260 shipped icons share
header 2, a 256x256 DXT5 with one mip, all with the same block infos), so a new
icon needs no new header. A checksum that is already taken is refused: the game
resolves that with the collision table, and nothing here has needed it yet.
"""

from __future__ import annotations

import struct
from bisect import bisect_left
from dataclasses import dataclass, replace
from typing import Optional, Tuple

from cdmw.core.archive_format import calculate_pa_checksum

PATHC_RELATIVE_PATH = "meta/0.pathc"
_HEAD = struct.Struct("<QIIIII")
_ENTRY = struct.Struct("<HBB16s")
_COLLISION = struct.Struct("<IHH16s")
_DDS_HEADER_LENGTH = 128
_NO_HEADER = 0xFFFF
_NO_COLLISION = 0xFF


def dds_shape(header: bytes) -> bytes:
    """The bytes of a 128-byte DDS header that describe the texture: magic, size, flags,
    height, width, pitch, depth, mip count, the pixel format and the caps. `dwReserved1`
    (+32..+76) and `dwReserved2` (+124) are left out: the shipped icons carry engine tags
    there that differ between the archive copy and the registry copy of the same header
    (3,000 of 3,000 icons compared, 2026-08-17)."""

    data = bytes(header[:_DDS_HEADER_LENGTH])
    return data[:32] + data[76:124]


class PathcError(ValueError):
    """Raised when the bytes are not a PATHC table, or a registration is refused."""


@dataclass(frozen=True, slots=True)
class PathcEntry:
    checksum: int
    header_index: int
    collision_start: int
    collision_end: int
    block_infos: bytes

    @property
    def is_direct(self) -> bool:
        return self.header_index != _NO_HEADER


@dataclass(frozen=True, slots=True)
class PathcTable:
    reserved: int
    header_size: int
    headers: Tuple[bytes, ...]
    entries: Tuple[PathcEntry, ...]
    #: The collision rows and their name blob, carried opaque.
    collisions: Tuple[bytes, ...]
    filenames: bytes

    def index_of(self, checksum: int) -> Optional[int]:
        at = bisect_left([entry.checksum for entry in self.entries], int(checksum))
        if at < len(self.entries) and self.entries[at].checksum == int(checksum):
            return at
        return None

    def find(self, path: str) -> Optional[PathcEntry]:
        at = self.index_of(pathc_checksum(path))
        return self.entries[at] if at is not None else None

    def dds_header_for(self, entry: PathcEntry) -> bytes:
        """The 128-byte DDS header the game hands out for `entry`."""

        if not entry.is_direct or not 0 <= entry.header_index < len(self.headers):
            raise PathcError("the entry does not name a texture header")
        return self.headers[entry.header_index][:_DDS_HEADER_LENGTH]


def pathc_checksum(path: str) -> int:
    normalized = str(path or "").replace("\\", "/").lstrip("/")
    return calculate_pa_checksum(f"/{normalized}")


def parse_pathc(raw: bytes) -> PathcTable:
    data = bytes(raw)
    if len(data) < _HEAD.size:
        raise PathcError("buffer is too short for a PATHC head")
    reserved, header_size, header_count, entry_count, collision_count, filenames_length = _HEAD.unpack_from(data, 0)
    expected = _HEAD.size + header_count * header_size + entry_count * (4 + _ENTRY.size) + collision_count * _COLLISION.size + filenames_length
    if expected != len(data):
        raise PathcError(f"PATHC counts describe {expected:,} bytes but the buffer holds {len(data):,}")
    pos = _HEAD.size
    headers = tuple(data[pos + i * header_size: pos + (i + 1) * header_size] for i in range(header_count))
    pos += header_count * header_size
    checksums = struct.unpack_from(f"<{entry_count}I", data, pos)
    pos += 4 * entry_count
    entries = []
    for checksum in checksums:
        header_index, start, end, blocks = _ENTRY.unpack_from(data, pos)
        entries.append(PathcEntry(checksum=checksum, header_index=header_index, collision_start=start, collision_end=end, block_infos=bytes(blocks)))
        pos += _ENTRY.size
    collisions = tuple(data[pos + i * _COLLISION.size: pos + (i + 1) * _COLLISION.size] for i in range(collision_count))
    pos += collision_count * _COLLISION.size
    filenames = data[pos: pos + filenames_length]
    return PathcTable(reserved=reserved, header_size=header_size, headers=headers, entries=tuple(entries), collisions=collisions, filenames=filenames)


def encode_pathc(table: PathcTable) -> bytes:
    for header in table.headers:
        if len(header) != table.header_size:
            raise PathcError("every texture header must be header_size bytes")
    out = bytearray(_HEAD.pack(table.reserved, table.header_size, len(table.headers), len(table.entries), len(table.collisions), len(table.filenames)))
    for header in table.headers:
        out += header
    out += struct.pack(f"<{len(table.entries)}I", *(entry.checksum for entry in table.entries))
    for entry in table.entries:
        if len(entry.block_infos) != 16:
            raise PathcError("block infos are 16 bytes")
        out += _ENTRY.pack(entry.header_index, entry.collision_start, entry.collision_end, entry.block_infos)
    for row in table.collisions:
        if len(row) != _COLLISION.size:
            raise PathcError("collision rows are 24 bytes")
        out += row
    out += table.filenames
    return bytes(out)


def register_texture(
    table: PathcTable,
    path: str,
    *,
    like: str,
    dds_header: Optional[bytes] = None,
) -> PathcTable:
    """Register `path` with the header and block infos of the shipped texture `like`.

    `dds_header`, when given, is the new file's own first 128 bytes; its shape
    (:func:`dds_shape`) must equal the header the reference is registered under,
    otherwise the game would decode the new pixels with the wrong size or format.
    """

    reference = table.find(like)
    if reference is None:
        raise PathcError(f"the reference texture {like!r} is not registered")
    if not reference.is_direct:
        raise PathcError(f"the reference texture {like!r} is registered through the collision table; pick a direct one")
    if dds_header is not None and dds_shape(dds_header) != dds_shape(table.dds_header_for(reference)):
        raise PathcError(f"the new texture's DDS header (size, format or mips) differs from {like!r}'s registered header")
    checksum = pathc_checksum(path)
    checksums = [entry.checksum for entry in table.entries]
    at = bisect_left(checksums, checksum)
    if at < len(checksums) and checksums[at] == checksum:
        raise PathcError(f"checksum {checksum:#010x} of {path!r} is already registered (a collision would need the collision table)")
    return _insert(table, at, PathcEntry(checksum=checksum, header_index=reference.header_index, collision_start=_NO_COLLISION, collision_end=_NO_COLLISION, block_infos=reference.block_infos))


def register_dds(table: PathcTable, path: str, dds_data: bytes) -> PathcTable:
    """Register `path` under the shipped header its own 128-byte DDS header equals.

    The block infos are the ones most of that header's textures carry (the plain
    per-mip sizes; a minority carry per-file values for textures stored another way,
    which a file written raw does not need). A DDS whose header matches no shipped
    header is refused: adding a header row would mean inventing its block infos.
    """

    header = bytes(dds_data[:_DDS_HEADER_LENGTH])
    if len(header) != _DDS_HEADER_LENGTH or header[:4] != b"DDS ":
        raise PathcError(f"{path!r} does not start with a DDS header")
    exact = [index for index, candidate in enumerate(table.headers) if candidate[:_DDS_HEADER_LENGTH] == header]
    shape = dds_shape(header)
    matches = exact + [index for index, candidate in enumerate(table.headers) if index not in exact and dds_shape(candidate) == shape]
    if not matches:
        raise PathcError(f"no shipped texture header matches {path!r}'s DDS header (shape or format); convert it to a shipped shape")
    checksum = pathc_checksum(path)
    checksums = [entry.checksum for entry in table.entries]
    at = bisect_left(checksums, checksum)
    if at < len(checksums) and checksums[at] == checksum:
        raise PathcError(f"checksum {checksum:#010x} of {path!r} is already registered (a collision would need the collision table)")
    for header_index in matches:
        tally: dict[bytes, int] = {}
        for entry in table.entries:
            if entry.header_index == header_index:
                tally[entry.block_infos] = tally.get(entry.block_infos, 0) + 1
        if tally:
            blocks = max(tally.items(), key=lambda item: item[1])[0]
            return _insert(table, at, PathcEntry(checksum=checksum, header_index=header_index, collision_start=_NO_COLLISION, collision_end=_NO_COLLISION, block_infos=blocks))
    raise PathcError(f"the shipped header matching {path!r} has no registered texture to take block infos from")


def _insert(table: PathcTable, at: int, entry: PathcEntry) -> PathcTable:
    return replace(table, entries=table.entries[:at] + (entry,) + table.entries[at:])


__all__ = [
    "PATHC_RELATIVE_PATH",
    "PathcEntry",
    "PathcError",
    "PathcTable",
    "dds_shape",
    "encode_pathc",
    "parse_pathc",
    "pathc_checksum",
    "register_dds",
    "register_texture",
]
