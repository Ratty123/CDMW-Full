"""Owned PAM and shipped-layout PAMLOD payloads for static mesh editor tests."""

from __future__ import annotations

import struct

_QUAD = ((0, 0, 0), (65535, 0, 0), (0, 65535, 0), (65535, 65535, 0))
_QUAD_UVS = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0))


def two_part_pam() -> bytes:
    """A PAM whose two quad Parts share one vertex and index buffer (20-byte records)."""
    table, record_size, parts = 0x410, 0x218, 2
    geometry = table + record_size * parts
    data = bytearray(geometry)
    data[:4] = b"PAR "
    struct.pack_into("<I", data, 0x10, parts)
    struct.pack_into("<I", data, 0x3C, geometry)
    struct.pack_into("<ffffff", data, 0x14, 0, 0, 0, 1, 1, 1)
    for part, name in enumerate((b"stone", b"wood")):
        record = table + part * record_size
        struct.pack_into("<IIII", data, record, 4, 6, part * 4, part * 6)
        data[record + 0x10:record + 0x15 + len(name)] = name + b".dds\0"
        data[record + 0x110:record + 0x111 + len(name)] = name + b"\0"
    for _part in range(parts):
        for position, uv in zip(_QUAD, _QUAD_UVS):
            data += struct.pack("<HHHHee8x", *position, 0, *uv)
    for _part in range(parts):
        data += struct.pack("<6H", 0, 1, 2, 1, 3, 2)
    return bytes(data)


def shipped_pamlod(levels=((4, 4), (3, 3), (3,)), materials=(b"stone", b"wood"), version=4,
                   packed=False) -> bytes:
    """A version 4 (or, with ``version=3``, 3) PAMLOD laid out as the game ships it.

    Per-level descriptor headers start at 0x54, a stated (offset, size, 0) block table ends at the
    geometry offset, and each level block holds 20-byte vertex records then u16 indices, starting
    on a 16-byte boundary. ``levels`` gives each level's vertex count per Part; each Part is a fan.
    Version 3 states only each block's offset and a block runs to the next one, alignment
    padding included; ``packed`` lays its blocks end to end instead.
    """
    head = bytearray(0x54)
    struct.pack_into("<I", head, 0x50, len(levels))
    head[0x0C] = version
    entry = 4 if version == 3 else 12
    descriptors = bytearray()
    blocks = []
    for level, parts in enumerate(levels):
        descriptors += struct.pack("<II", level + 1, len(parts))
        vertex_offset = index_offset = 0
        vertex_bytes, index_bytes = bytearray(), bytearray()
        for part, count in enumerate(parts):
            index_count = (count - 2) * 3
            record = bytearray(0x218)
            struct.pack_into("<IIII", record, 0, count, index_count, vertex_offset, index_offset)
            name = materials[part % len(materials)]
            record[0x10:0x15 + len(name)] = name + b".dds\0"
            record[0x110:0x111 + len(name)] = name + b"\0"
            descriptors += record
            for vertex in range(count):
                vertex_bytes += struct.pack(
                    "<HHHHee8x",
                    (vertex * 9001 + part * 20000 + level * 101) % 65536,
                    (vertex * 13003 + part * 7000) % 65536,
                    (level * 3001) % 65536,
                    0,
                    vertex / count,
                    part / 2,
                )
            for triangle in range(count - 2):
                index_bytes += struct.pack("<HHH", 0, triangle + 1, triangle + 2)
            vertex_offset += count
            index_offset += index_count
        blocks.append(bytes(vertex_bytes + index_bytes))
    geometry = (0x54 + len(descriptors) + entry * len(levels) + 15) & ~15
    data = bytearray(head + descriptors)
    data += bytes(geometry - entry * len(levels) - len(data))
    table = len(data)
    data += bytes(entry * len(levels))
    struct.pack_into("<II", data, 0, len(levels), geometry)
    struct.pack_into("<ffffff", data, 0x10, -1, -1, -1, 1, 1, 1)
    for level, block in enumerate(blocks):
        if not packed:
            data += bytes((-len(data)) % 16)
        if version == 3:
            struct.pack_into("<I", data, table + level * 4, len(data))
        else:
            struct.pack_into("<III", data, table + level * 12, len(data), len(block), 0)
        data += block
    return bytes(data)
