"""Read-only PAC guide geometry, following the CPU loader and skinning shader.

This is a separate mesh from the visible 40-byte render vertices. Raw tables
are retained alongside the traced particle initialization and topology evidence.
No values here authorize changing the game's constraint or collision data.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import struct
from typing import Sequence

from ._pbd_numeric import FLOAT32_MAX, f32
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
    cpu_unskinned_vertices: tuple[tuple[float, float, float], ...] = ()
    metadata_flags: int = 0


def inspect_guide_profile_admission(metadata_flags: int, guide_count: int) -> dict:
    """Static resource prerequisites for the profile selector, not live activation.

    Loader 0x142C63CE0 copies the guide count to resource+0x148 and the
    count<=1024 result to byte+0x120. Selector 0x142CE39D0 requires both a
    nonzero count and that limit check. An oversized resource fails regardless
    of the global policy that optionally discards its guides after loading.
    Loader 0x142C6D6E0 copies metadata bit15 to byte+0x121; the selector uses
    1+that bit as its fallback profile mode. Named profiles, NoSimulation,
    per-model overrides and later scene scheduling remain separate inputs.
    """
    if (type(metadata_flags) is not int or not 0 <= metadata_flags <= 0xFFFFFFFF
            or type(guide_count) is not int or not 0 <= guide_count <= 0xFFFF):
        raise ValueError("Guide admission requires unsigned PAC flags and a uint16 guide count.")
    layout = (metadata_flags >> 8) & 15
    if not layout and guide_count:
        raise ValueError("A PAC without a guide section cannot supply a guide count.")
    return {"passes_resource_checks": bool(layout and 0 < guide_count <= 1024),
            "guide_count_limit": 1024,
            "default_profile_mode": "spline" if metadata_flags & 0x8000 else "cloth"}


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
    vertices, cpu_vertices, bone_indices, bone_weight_bytes = [], [], [], []
    for x, y, z, fourth, packed, w0, w1, w2, w3 in struct.iter_unpack("<4HI4B", records):
        vertices.append(tuple(box[i] + (value & 32767) / 32767 * box[i + 3]
                              for i, value in enumerate((x, y, z))))
        # The CPU initializer reads all 16 bits; the guide animation shader
        # masks them to 15. Keep both views explicit instead of conflating them.
        cpu_vertices.append(tuple(box[i] + value / 32767 * box[i + 3]
                                  for i, value in enumerate((x, y, z))))
        bone_indices.append((packed & 1023, (packed >> 10) & 1023,
                             (packed >> 20) & 1023, fourth & 1023))
        bone_weight_bytes.append((w0, w1, w2, w3))
    return PacClothGuides(
        layout, tuple(box[:3]), tuple(box[3:]), tuple(vertices), tuple(bone_indices),
        tuple(bone_weight_bytes), tuple(zip(indices[::3], indices[1::3], indices[2::3])),
        channel_a, channel_b, alpha_words, tuple(ranges),
        groups_a, group_a_tags, constraint_records, constraint_indices,
        vertex_constraint_spans, groups_b, edge_indices, tuple(cpu_vertices),
        metadata_flags=flags,
    )


def inspect_guide_particle_initialization(
    guides: PacClothGuides, *, material_mass: float | None = None,
    use_vertex_alpha_position_blending: bool | None = None,
) -> dict:
    """Decode authored particle channels without guessing the active material.

    In build 1.0.0.2944, the view constructor at 0x153954980 connects PAC
    channels A/B to the initializer at 0x143CCAAC0. B=255 writes zero inverse
    mass; every other B uses the same material inverse mass (1/Mass when
    positive, otherwise 1). Intermediate B values are not mass weights.

    Position blend is stored as binary16. Both material-flag cases are reported
    because the PAC alone does not select UseVertexAlphaPositionBlending.
    Group IDs 1..31 can select dynamic-fix bits in the base-movement shader;
    membership does not mean that bit is active. Runtime overrides, collisions
    and further solver processing are outside this initialization report.
    Supplying both material inputs also calculates their initial values, before
    long-range attachment preparation can further modify position blends.
    """
    fixed = [index for index, value in enumerate(guides.channel_b) if value == 255]
    result = {
        "fixed_vertex_indices": fixed,
        "inverse_mass_factors": [0 if value == 255 else 1 for value in guides.channel_b],
        "position_blend_with_vertex_alpha": [
            struct.unpack("<e", struct.pack("<e", value / 255))[0]
            for value in guides.channel_b
        ],
        "position_blend_without_vertex_alpha": [float(value == 255) for value in guides.channel_b],
        "group_ids": list(guides.channel_a),
        "dynamic_fix_group_ids": [value if 1 <= value <= 31 else None for value in guides.channel_a],
    }
    if material_mass is not None or use_vertex_alpha_position_blending is not None:
        if (material_mass is None or not math.isfinite(material_mass)
                or type(use_vertex_alpha_position_blending) is not bool):
            raise ValueError("Guide initialization requires finite Mass and an explicit vertex-alpha flag together.")
        inverse_mass = 1 / material_mass if material_mass > 0 else 1.0
        if not math.isfinite(inverse_mass):
            raise ValueError("Material Mass produces an unrepresentable initial inverse mass.")
        blend_key = "position_blend_with_vertex_alpha" if use_vertex_alpha_position_blending else "position_blend_without_vertex_alpha"
        result["supplied_material_initialization"] = {
            "mass": material_mass,
            "use_vertex_alpha_position_blending": use_vertex_alpha_position_blending,
            "inverse_masses": [inverse_mass * factor for factor in result["inverse_mass_factors"]],
            "position_blends": list(result[blend_key]),
        }
    return result


def _classify_guide_constraints(guides: PacClothGuides) -> list[tuple[str, tuple[int, ...]]]:
    count = len(guides.vertices)
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
    return classified


def inspect_guide_constraint_geometry(
    guides: PacClothGuides, *, particle_positions: Sequence[Sequence[float]] | None = None,
) -> dict:
    """Derive rest geometry from authored records and explicit particle positions.

    CPU preparation at 0x143CCB740 expands 10-byte records to 36-byte records:
    distance, angle and area are stored in the same float lane. The optional
    bending path at 0x143CCE5B0 derives four cotangent coefficients. These are
    mathematical values before binary16 upload, not bit-exact CPU emulation.

    Without supplied positions, use the decoded CPU coordinates before skinning.
    Area activation, sequential bending-mode selection and runtime overrides
    require additional state and are not inferred from these measurements.
    """
    supplied = particle_positions is not None
    positions = tuple(tuple(point) for point in (
        particle_positions if supplied else guides.cpu_unskinned_vertices
    ))
    if len(positions) != len(guides.vertices) or any(
        len(point) != 3 or any(not math.isfinite(v) for v in point) for point in positions
    ):
        raise ValueError("Constraint geometry requires one finite 3D position per guide vertex.")

    def sub(a, b):
        return tuple(x - y for x, y in zip(a, b))

    def dot(a, b):
        return sum(x * y for x, y in zip(a, b))

    def cross(a, b):
        return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0])

    records = []
    for index, (kind, vertices) in enumerate(_classify_guide_constraints(guides)):
        row = {"source_index": index, "kind": kind, "vertices": vertices}
        records.append(row)
        if kind == "unrecognized":
            continue
        a, b = (positions[v] for v in vertices[:2])
        edge = sub(b, a)
        if kind == "pair":
            row["rest_length"] = math.hypot(*edge)
            continue
        c = positions[vertices[2]]
        n1 = cross(edge, sub(c, a))
        length1 = math.hypot(*n1)
        if kind == "triangle":
            row["rest_area"] = 0.5 * length1
            row["degenerate"] = length1 == 0
            continue
        d = positions[vertices[3]]
        # Both normals use the same directed edge in the CPU initializer.
        # A flat pair of adjacent triangles therefore has rest angle pi.
        n2 = cross(edge, sub(d, a))
        length2 = math.hypot(*n2)
        degenerate = length1 == 0 or length2 == 0
        # CPU normalization leaves a zero normal unchanged, giving acos(0).
        cosine = dot(n1, n2) / length1 / length2 if not degenerate else 0.0
        row["rest_angle_radians"] = math.acos(max(-1.0, min(1.0, cosine)))
        row["degenerate"] = degenerate
        cotangents = (
            dot(sub(b, c), edge) / length1 if length1 > 0.001 else 0.0,
            dot(sub(c, a), edge) / length1 if length1 > 0.001 else 0.0,
            dot(sub(d, a), edge) / length2 if length2 > 0.001 else 0.0,
            dot(sub(b, d), edge) / length2 if length2 > 0.001 else 0.0,
        )
        row["cotangent_limit_passed"] = all(value < 11.43 for value in cotangents)
        row["bending_coefficients"] = None
        if not degenerate:
            c0, c1, c2, c3 = cotangents
            scale = math.sqrt(3.0 / (0.5 * (length1 + length2)))
            row["bending_coefficients"] = tuple(
                value * scale for value in (c0 + c3, c1 + c2, -c0 - c1, -c2 - c3)
            )
    return {"position_basis": "caller_supplied" if supplied else "cpu_unskinned",
            "constraints": records}


def inspect_guide_attachment_candidates(
    guides: PacClothGuides, *, particle_positions: Sequence[Sequence[float]] | None = None,
) -> dict:
    """Compare the two traced mode-1 cloth attachment selection paths.

    Build 1.0.0.2944 uses 0x143CCD480 with connected components, or
    0x143CCDE90 with one candidate pool. Both call 0x143CCC580, which keeps
    four distinct squared float32 distances, retaining the first equal-distance
    candidate. Initial fixed particles and dynamic-fix group IDs 1..31 qualify;
    group activation is separate. Candidate order follows guide index order.

    The report stops before half upload, ratio/auto-weighting preparation and
    runtime activation. Default positions precede skeletal transformation.
    """
    supplied = particle_positions is not None
    positions = tuple(tuple(point) for point in (
        particle_positions if supplied else guides.cpu_unskinned_vertices
    ))
    count = len(guides.vertices)
    if (len(positions) != count or len(guides.channel_a) != count
            or len(guides.channel_b) != count or any(
                len(point) != 3 or any(not math.isfinite(v) for v in point) for point in positions
            )):
        raise ValueError("Cloth attachments require one finite 3D position and both channels per guide vertex.")
    if any(len(t) != 3 or any(type(i) is not int or not 0 <= i < count for i in t)
           for t in guides.triangles):
        raise ValueError("Cloth attachments require valid guide triangle indices.")

    positions = tuple(tuple(f32(v) for v in p) for p in positions)
    parents = list(range(count))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for a, b, c in guides.triangles:
        parents[root(b)] = root(a)
        parents[root(c)] = root(a)
    labels = {}
    components = []
    for index in range(count):
        owner = root(index)
        components.append(labels.setdefault(owner, len(labels)))
    eligible = [i for i in range(count)
                if guides.channel_b[i] == 255 or 1 <= guides.channel_a[i] <= 31]
    component_rows, whole_rows = [], []

    def selected_rows(candidates):
        first_at_distance = {}
        for distance, index in candidates:
            # The CPU's four empty entries use FLT_MAX and reject equal keys.
            if distance < FLOAT32_MAX:
                first_at_distance.setdefault(distance, index)
        selected = sorted(first_at_distance.items())[:4]
        return {
            "guide_indices": [index for _, index in selected],
            "squared_distances": [distance for distance, _ in selected],
            "rest_lengths_before_half_upload": [f32(math.sqrt(distance)) for distance, _ in selected],
        }

    for index, point in enumerate(positions):
        candidates = []
        for anchor in eligible:
            dx, dy, dz = (f32(a - b) for a, b in zip(point, positions[anchor]))
            distance = f32(f32(f32(dy * dy) + f32(dx * dx)) + f32(dz * dz))
            candidates.append((distance, anchor))
        whole_rows.append(selected_rows(candidates))
        component_rows.append(selected_rows(
            (distance, anchor) for distance, anchor in candidates if components[anchor] == components[index]
        ))
    return {
        "position_basis": "caller_supplied" if supplied else "cpu_unskinned",
        "eligible_guide_indices": eligible,
        "component_ids": components,
        "component_count": len(labels),
        "by_connected_component": component_rows,
        "whole_mesh": whole_rows,
        "limitations": "Mode-1 cloth preparation scenarios, not active runtime attachments. Eligibility uses initial particle channels. Positions precede skinning unless supplied. Runtime selection, dynamic-fix activation, half upload, long-range ratios and automatic position blending are not inferred.",
    }


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
    classified = _classify_guide_constraints(guides)
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
