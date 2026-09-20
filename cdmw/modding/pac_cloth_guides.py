"""Read-only PAC guide geometry, following the CPU loader and skinning shader.

This is a separate mesh from the visible 40-byte render vertices. Its byte
channels and alpha bitmask are retained without assigning physical-pin semantics.
No values here authorize changing the game's constraint or collision data.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import struct

from .mesh_parser import (
    _find_pac_descriptors, _parse_par_sections, _validated_pac_descriptor_prefix,
)


@dataclass(frozen=True, slots=True)
class PacGuideRange:
    name: str
    offset: int
    count: int
    stride: int


@dataclass(frozen=True, slots=True)
class PacClothGuides:
    layout: int
    bbox_min: tuple[float, float, float]
    bbox_extent: tuple[float, float, float]
    vertices: tuple[tuple[float, float, float], ...]
    bone_indices: tuple[tuple[int, int, int, int], ...]
    bone_weight_bytes: tuple[tuple[int, int, int, int], ...]
    triangles: tuple[tuple[int, int, int], ...]
    channel_a: bytes
    channel_b: bytes
    alpha_words: tuple[int, ...]
    ranges: tuple[PacGuideRange, ...]


def decode_pac_cloth_guides(data: bytes) -> PacClothGuides | None:
    """Decode known guide layouts 3/7, or return None when their flag is absent.

    Truncated, compressed and unsupported input raises ValueError. Offsets stay
    within section 0; descriptor count is checked before locating the guide block.
    Bone indices are palette slots, not skeleton IDs. Skin weights are stored
    unmodified: the guide shader divides each by 255, even for sums of 254/256.
    """
    if len(data) < 80 or data[:4] != b"PAR " or data[4:6] != b"\x03\x09":
        raise ValueError("Guide decoding requires the known PAC 3/9 header.")
    sections = _parse_par_sections(data)
    metadata = next((row for row in sections if row["index"] == 0), None)
    if metadata is None or metadata["size"] < 5:
        raise ValueError("Guide decoding requires complete PAC metadata.")
    stored = struct.unpack_from("<I", data, 0x10)[0]
    if stored not in (0, metadata["size"]):
        raise ValueError("Guide decoding requires decompressed PAC metadata.")
    start, end = metadata["offset"], metadata["offset"] + metadata["size"]
    if end > len(data):
        raise ValueError("PAC guide metadata is truncated.")
    flags = struct.unpack_from("<I", data, start)[0]
    layout = (flags >> 8) & 15
    if layout == 0:
        return None
    if layout not in (3, 7):
        raise ValueError(f"PAC guide layout {layout} is not decoded.")
    lod_count = data[start + 4]
    count_offset = start + 5 + 8 * lod_count
    if not 2 <= lod_count <= 4 or count_offset + 2 > end:
        raise ValueError("PAC guide descriptor layout is not decoded.")
    part_count = struct.unpack_from("<H", data, count_offset)[0]
    descriptors = _validated_pac_descriptor_prefix(
        _find_pac_descriptors(data, start, metadata["size"], lod_count), sections,
    )
    if not descriptors or len(descriptors) != part_count:
        raise ValueError("PAC guide block cannot be located after every descriptor.")
    cursor = max(d.descriptor_offset + 40 + 6 * d.stored_lod_count for d in descriptors)
    ranges = []

    def take(name: str, count: int, stride: int) -> memoryview:
        nonlocal cursor
        stop = cursor + count * stride
        if cursor < start or stop > end:
            raise ValueError(f"PAC guide {name} is truncated.")
        ranges.append(PacGuideRange(name, cursor, count, stride))
        value = memoryview(data)[cursor:stop]
        cursor = stop
        return value

    def u16(name: str) -> int:
        return struct.unpack("<H", take(name, 1, 2))[0]

    def array(name: str, stride: int) -> memoryview:
        return take(name, u16(name + "_count"), stride)

    def groups(name: str, *, tagged: bool = False) -> None:
        for index in range(u16(name + "_count")):
            array(f"{name}_{index}", 2)
            if tagged:
                take(f"{name}_{index}_tag", 1, 1)

    count = u16("vertices_count")
    # The CPU loader accepts at most 1024 guide vertices, matching 10-bit indices.
    if count > 1024:
        raise ValueError("PAC guide vertex count exceeds the decoded 1024-vertex limit.")
    records = take("vertices", count, 16)
    channel_a = bytes(take("channel_a", count, 1))
    channel_b = bytes(take("channel_b", count, 1))
    indices = tuple(v[0] for v in struct.iter_unpack("<H", array("triangle_indices", 2)))
    if len(indices) % 3 or any(index >= count for index in indices):
        raise ValueError("PAC guide triangles contain invalid indices.")
    alpha_words = tuple(v[0] for v in struct.iter_unpack("<I", take("alpha_bits", (count + 31) // 32, 4)))
    groups("groups_a", tagged=layout == 7)
    # These lengths are proven by the CPU loader. Their solver semantics remain
    # undecoded; skip by the stored counts instead of scanning for plausible floats.
    array("records_10", 10)
    array("indices_a", 2)
    array("records_4", 4)
    groups("groups_b")
    array("indices_b", 2)
    box = struct.unpack("<6f", take("guide_bbox", 2, 12))
    if any(not math.isfinite(v) for v in box) or any(v < 0 for v in box[3:]):
        raise ValueError("PAC guide bounding box is invalid.")
    vertices, bone_indices, bone_weight_bytes = [], [], []
    for x, y, z, fourth, packed, w0, w1, w2, w3 in struct.iter_unpack("<4HI4B", records):
        vertices.append(tuple(box[i] + (value & 32767) / 32767 * box[i + 3]
                              for i, value in enumerate((x, y, z))))
        bone_indices.append((packed & 1023, (packed >> 10) & 1023,
                             (packed >> 20) & 1023, fourth & 1023))
        bone_weight_bytes.append((w0, w1, w2, w3))
    return PacClothGuides(
        layout, tuple(box[:3]), tuple(box[3:]), tuple(vertices), tuple(bone_indices),
        tuple(bone_weight_bytes), tuple(zip(indices[::3], indices[1::3], indices[2::3])),
        channel_a, channel_b, alpha_words, tuple(ranges),
    )
