"""Read-only PAC guide geometry, following the CPU loader and skinning shader.

This is a separate mesh from the visible 40-byte render vertices. Its byte
channels and alpha bitmask are retained without assigning physical-pin semantics.
No values here authorize changing the game's constraint or collision data.
"""

from __future__ import annotations

from collections import Counter
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
    groups_a: tuple[tuple[int, ...], ...] = ()
    group_a_tags: tuple[int, ...] = ()
    constraint_records: tuple[tuple[int, int, int, int, int], ...] = ()
    constraint_indices: tuple[int, ...] = ()
    vertex_constraint_spans: tuple[tuple[int, int], ...] = ()
    groups_b: tuple[tuple[int, ...], ...] = ()
    edge_indices: tuple[int, ...] = ()


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

    def groups(name: str, *, tagged: bool = False) -> tuple[tuple[tuple[int, ...], ...], tuple[int, ...]]:
        values, tags = [], []
        for index in range(u16(name + "_count")):
            values.append(tuple(v[0] for v in struct.iter_unpack("<H", array(f"{name}_{index}", 2))))
            if tagged:
                tags.append(take(f"{name}_{index}_tag", 1, 1)[0])
        return tuple(values), tuple(tags)

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
    groups_a, group_a_tags = groups("groups_a", tagged=layout == 7)
    # Preserve complete records, including unknown high bytes. Structural matches
    # can be inspected separately without assuming solver or editable-pin meaning.
    constraint_records = tuple(struct.iter_unpack("<5H", array("records_10", 10)))
    constraint_indices = tuple(v[0] for v in struct.iter_unpack("<H", array("indices_a", 2)))
    vertex_constraint_spans = tuple(struct.iter_unpack("<2H", array("records_4", 4)))
    groups_b, _ = groups("groups_b")
    edge_indices = tuple(v[0] for v in struct.iter_unpack("<H", array("indices_b", 2)))
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
        groups_a, group_a_tags, constraint_records, constraint_indices,
        vertex_constraint_spans, groups_b, edge_indices,
    )


def inspect_guide_topology(guides: PacClothGuides) -> dict:
    """Report structural relationships, not runtime pin or solver semantics.

    Stock samples have pair records, four-point hinges and triangle records.
    Only the low byte of the fifth word participates in that observed pattern;
    its high byte is retained, not discarded or assigned a meaning. Unrecognized
    records remain available in the decoder and are counted explicitly here.
    """
    count = len(guides.vertices)
    triangles = Counter(tuple(sorted(t)) for t in guides.triangles)
    edge_faces: dict[tuple[int, int], list[int]] = {}
    for a, b, c in guides.triangles:
        for x, y, opposite in ((a, b, c), (b, c, a), (c, a, b)):
            edge_faces.setdefault(tuple(sorted((x, y))), []).append(opposite)
    edges = set(edge_faces)
    classified = []
    for a, b, c, d, tag in guides.constraint_records:
        low = tag & 255
        if low == 0 and c == d == 0:
            kind, vertices = "pair", (a, b)
        elif low == 0 and d == 65535:
            kind, vertices = "triangle", (a, b, c)
        elif low == 1:
            kind, vertices = "hinge", (a, b, c, d)
        else:
            kind, vertices = "unrecognized", ()
        if any(v >= count for v in vertices) or len(set(vertices)) != len(vertices):
            kind, vertices = "unrecognized", ()
        classified.append((kind, vertices))
    kinds = Counter(kind for kind, _ in classified)
    pairs = {tuple(sorted(v)) for kind, v in classified if kind == "pair"}
    areas = Counter(tuple(sorted(v)) for kind, v in classified if kind == "triangle")
    hinges = [v for kind, v in classified if kind == "hinge"]
    alpha = {i for i in range(count) if guides.alpha_words[i // 32] >> (i % 32) & 1}
    maximum_b = {i for i, value in enumerate(guides.channel_b) if value == 255}
    stored_edges = guides.edge_indices
    edge_table_matches = len(stored_edges) % 2 == 0 and Counter(
        tuple(sorted(v)) for v in zip(stored_edges[::2], stored_edges[1::2])
    ) == Counter({edge: 1 for edge in edges})

    expected = [[] for _ in range(count)]
    for record_index, (_, vertices) in enumerate(classified):
        for vertex in vertices:
            expected[vertex].append(record_index)
    spans_match = len(guides.vertex_constraint_spans) == count and not kinds["unrecognized"]
    groups_match = len(guides.groups_b) == len(guides.vertex_constraint_spans) == count
    cursor = 0
    for vertex, (offset, packed_counts) in enumerate(guides.vertex_constraint_spans):
        first_count, second_count = packed_counts & 255, packed_counts >> 8
        end = offset + first_count + second_count
        refs = guides.constraint_indices[offset:end]
        valid = offset == cursor and end <= len(guides.constraint_indices) and vertex < count
        valid = valid and all(index < len(classified) for index in refs)
        if valid:
            valid = Counter(refs) == Counter(expected[vertex])
            valid = valid and all(classified[i][0] in ("pair", "hinge") for i in refs[:first_count])
            valid = valid and all(classified[i][0] == "triangle" for i in refs[first_count:])
        spans_match = spans_match and valid
        groups_match = (groups_match and end <= len(guides.constraint_indices)
                        and vertex < len(guides.groups_b) and guides.groups_b[vertex] == refs[:first_count])
        cursor = end
    spans_match = spans_match and cursor == len(guides.constraint_indices)

    return {
        "record_counts": {kind: kinds[kind] for kind in ("pair", "hinge", "triangle", "unrecognized")},
        "record_high_bytes": sorted({row[4] >> 8 for row in guides.constraint_records}),
        "guide_edge_count": len(edges),
        "edge_table_matches_triangles": edge_table_matches,
        "triangle_records_match_triangles": areas == triangles,
        "hinge_records_match_adjacent_triangles": all(
            Counter(edge_faces.get(tuple(sorted((a, b))), ())) == Counter((c, d))
            for a, b, c, d in hinges
        ),
        "pair_records_missing_edges": len(edges - pairs),
        "pair_records_extra_edges": len(pairs - edges),
        "missing_pair_records_match_alpha_edges": edges - pairs == {
            edge for edge in edges if all(v in alpha for v in edge)
        },
        "alpha_vertex_count": len(alpha),
        "alpha_bits_match_channel_b_255": alpha == maximum_b,
        "group_starts_match_alpha_bits": {group[0] for group in guides.groups_a if group} == alpha,
        "vertex_constraint_spans_match_records": spans_match,
        "groups_b_match_first_span": groups_match,
    }
