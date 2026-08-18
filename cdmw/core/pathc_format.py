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
icon needs no new header; a texture of a shape the registry has never seen gets a
header row of its own (its DDS header with the reserved words normalised the way
every shipped registry header has them: `dwReserved1` zero, `dwReserved2` a usage
tag, 4 on most character textures) and block infos computed as mip sizes. A
checksum that is already taken is refused: the game resolves that with the
collision table, and nothing here has needed it yet.
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


#: The `dwReserved2` tag the registry's headers carry; 4 on 22,611 of the 36,477 shipped
#: character textures (normals, displacement, mask, gloss, emissive alike), so it is
#: the tag a new header takes when nothing better is known.
DEFAULT_HEADER_TAG = 4
#: The tags by texture role, measured on the 36,485 shipped `character/texture` files
#: (2026-08-18): base colours are 12 (6,082 DXT1) or 13 (625 DXT5, 543 DXT1); `_sp`
#: material maps 12 (3,956 of 4,594); `_n`, `_disp`, `_ma`, `_mg`, `_o`, `_emi` are 4;
#: `_m` masks 5 (2,387 DXT5). Icons are 15. Whatever the engine reads the tag as
#: (a colour-space or a streaming class), a new texture takes the tag its kind ships with.
COLOR_HEADER_TAG = 12
COLOR_ALPHA_HEADER_TAG = 13
MASK_HEADER_TAG = 5
_TAG_BY_SUFFIX = {"n": 4, "disp": 4, "ma": 4, "mg": 4, "o": 4, "emi": 4, "wn": 4, "flow": 4, "sp": COLOR_HEADER_TAG, "m": MASK_HEADER_TAG}


def header_tag_for(path: str, dds_data: bytes) -> int:
    """The `dwReserved2` tag a texture of `path`'s kind ships with; see the tags above.
    Named suffixes decide; anything else is a colour texture, 13 when it carries alpha
    (DXT5 / BC3 / BC7) and 12 otherwise."""

    name = str(path).replace("\\", "/").rsplit("/", 1)[-1].lower()
    stem = name[:-4] if name.endswith(".dds") else name
    suffix = stem.rsplit("_", 1)[-1] if "_" in stem else ""
    if suffix in _TAG_BY_SUFFIX:
        return _TAG_BY_SUFFIX[suffix]
    header = bytes(dds_data[:_DDS_HEADER_LENGTH])
    fourcc = header[84:88] if len(header) >= 88 else b""
    if fourcc in (b"DXT3", b"DXT5"):
        return COLOR_ALPHA_HEADER_TAG
    if fourcc == b"DX10" and len(dds_data) >= 132:
        dxgi = struct.unpack_from("<I", dds_data, 128)[0]
        if dxgi in (77, 78, 98, 99):  # BC3, BC7
            return COLOR_ALPHA_HEADER_TAG
    return COLOR_HEADER_TAG


def header_tag(header: bytes) -> int:
    """The `dwReserved2` tag of a registry (or file) DDS header."""

    return struct.unpack_from("<I", bytes(header[:_DDS_HEADER_LENGTH]), 124)[0]
_BLOCK_BYTES = {b"DXT1": 8, b"BC4U": 8, b"ATI1": 8, b"BC4S": 8, b"DXT3": 16, b"DXT5": 16, b"BC5U": 16, b"ATI2": 16, b"BC5S": 16}
_DXGI_BLOCK_BYTES = {70: 8, 71: 8, 72: 8, 79: 8, 80: 8, 81: 8, 73: 16, 74: 16, 75: 16, 76: 16, 77: 16, 78: 16, 82: 16, 83: 16, 84: 16, 94: 16, 95: 16, 96: 16, 97: 16, 98: 16, 99: 16}


def _mip_bytes(header: bytes, level: int) -> Optional[int]:
    """Bytes of mip `level` for a block-compressed DDS header, or None when the format is unknown."""

    height, width = struct.unpack_from("<II", header, 12)
    fourcc = header[84:88]
    if fourcc == b"DX10":
        block = _DXGI_BLOCK_BYTES.get(struct.unpack_from("<I", header, 128)[0]) if len(header) >= 132 else None
    else:
        block = _BLOCK_BYTES.get(fourcc)
    if block is None:
        return None
    w = max(1, width >> level)
    h = max(1, height >> level)
    return ((w + 3) // 4) * ((h + 3) // 4) * block


def block_infos_for(dds_data: bytes) -> bytes:
    """The four block-info words for a texture stored raw: the byte sizes of mips 0..3
    (zero beyond the mip count), except a one-mip texture, whose registry rows repeat
    the top size in the second word (all 7,260 shipped icons)."""

    header = bytes(dds_data[:148])
    mips = max(1, struct.unpack_from("<I", header, 28)[0])
    sizes = []
    for level in range(4):
        size = _mip_bytes(header, level) if level < mips else 0
        if size is None:
            raise PathcError("the DDS format is not one whose mip sizes are known here")
        sizes.append(size)
    if mips == 1:
        sizes[1] = sizes[0]
    return struct.pack("<4I", *sizes)


def registry_header_for(dds_data: bytes, *, tag: int = DEFAULT_HEADER_TAG) -> bytes:
    """A registry header row for a DDS: its own 128-byte header with `dwReserved1`
    zeroed and `dwReserved2` set to `tag` (as every shipped registry header), then the
    20-byte DX10 extension when the file has one, else zeros."""

    header = bytearray(dds_data[:_DDS_HEADER_LENGTH])
    if len(header) != _DDS_HEADER_LENGTH or header[:4] != b"DDS ":
        raise PathcError("not a DDS header")
    header[32:76] = bytes(44)
    struct.pack_into("<I", header, 124, int(tag))
    extension = bytes(dds_data[128:148]) if header[84:88] == b"DX10" and len(dds_data) >= 148 else bytes(20)
    return bytes(header) + extension


def register_dds(table: PathcTable, path: str, dds_data: bytes, *, tag: Optional[int] = None) -> PathcTable:
    """Register `path` under the shipped header its own 128-byte DDS header equals, or,
    when no shipped header has that shape and tag, under a new header row made from
    the file.

    `tag` is the header's `dwReserved2`; None takes :func:`header_tag_for` (the tag the
    texture's kind ships with). A shipped header is reused only when it carries that
    tag as well as the shape, so a base colour never lands on a mask's header row.

    Under a shipped header the block infos are the ones most of that header's textures
    carry (the plain per-mip sizes; a minority carry per-file values for textures stored
    another way, which a file written raw does not need). Under a new header they are
    computed from the format and size (:func:`block_infos_for`).
    """

    header = bytes(dds_data[:_DDS_HEADER_LENGTH])
    if len(header) != _DDS_HEADER_LENGTH or header[:4] != b"DDS ":
        raise PathcError(f"{path!r} does not start with a DDS header")
    if tag is None:
        tag = header_tag_for(path, dds_data)
    checksum = pathc_checksum(path)
    checksums = [entry.checksum for entry in table.entries]
    at = bisect_left(checksums, checksum)
    if at < len(checksums) and checksums[at] == checksum:
        raise PathcError(f"checksum {checksum:#010x} of {path!r} is already registered (a collision would need the collision table)")
    exact = [index for index, candidate in enumerate(table.headers) if candidate[:_DDS_HEADER_LENGTH] == header and header_tag(candidate) == tag]
    shape = dds_shape(header)
    matches = exact + [
        index for index, candidate in enumerate(table.headers)
        if index not in exact and dds_shape(candidate) == shape and header_tag(candidate) == tag
    ]
    for header_index in matches:
        tally: dict[bytes, int] = {}
        for entry in table.entries:
            if entry.header_index == header_index:
                tally[entry.block_infos] = tally.get(entry.block_infos, 0) + 1
        if tally:
            blocks = max(tally.items(), key=lambda item: item[1])[0]
            return _insert(table, at, PathcEntry(checksum=checksum, header_index=header_index, collision_start=_NO_COLLISION, collision_end=_NO_COLLISION, block_infos=blocks))
    if len(table.headers) >= 0xFFFE:
        raise PathcError("the registry has no room for another header")
    if table.header_size != 148:
        raise PathcError(f"the registry's header size is {table.header_size}, not the 148 a new header is written as")
    new_header = registry_header_for(dds_data, tag=tag)
    blocks = block_infos_for(dds_data)
    grown = replace(table, headers=table.headers + (new_header,))
    return _insert(grown, at, PathcEntry(checksum=checksum, header_index=len(table.headers), collision_start=_NO_COLLISION, collision_end=_NO_COLLISION, block_infos=blocks))


def _insert(table: PathcTable, at: int, entry: PathcEntry) -> PathcTable:
    return replace(table, entries=table.entries[:at] + (entry,) + table.entries[at:])


__all__ = [
    "COLOR_ALPHA_HEADER_TAG",
    "COLOR_HEADER_TAG",
    "DEFAULT_HEADER_TAG",
    "MASK_HEADER_TAG",
    "PATHC_RELATIVE_PATH",
    "PathcEntry",
    "PathcError",
    "PathcTable",
    "block_infos_for",
    "dds_shape",
    "registry_header_for",
    "encode_pathc",
    "header_tag",
    "header_tag_for",
    "parse_pathc",
    "pathc_checksum",
    "register_dds",
    "register_texture",
]
