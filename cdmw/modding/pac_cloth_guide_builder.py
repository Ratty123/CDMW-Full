"""Bounded new-guide construction for decoded, guide-free PAC metadata.

Creates layout 3 cloth on an existing skeleton. This never extends a skeleton,
edits an archive, replaces authored guides, or guesses unknown metadata offsets.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
import math
import struct

from cdmw.domain.mesh.cloth_guides import PacClothGuideRule
from .mesh_parser import _parse_par_sections, _find_pac_descriptors, _validated_pac_descriptor_prefix
from .pabv_parser import decode_pac_embedded_volumes
from .pac_cloth import pac_cloth_lods
from .pac_cloth_guides import decode_pac_cloth_guides, inspect_guide_topology


def _validate_metadata_tail(data, cursor, end, flags):
    """Validate sequential trailer framing; preserve every payload byte.

    Build 1.0.0.2944: 0x142C65090 reads u8 groups of u8-counted 16-byte
    records and, under flag 0x02000000, u32-counted 12-byte records.
    0x142C61960 otherwise skips four bytes, then 0x142C623E0 passes a
    length-delimited blob's own address/size to its loader (no PAC offsets).
    The remaining optional u32 arrays, u16 groups of 16-byte rows and u8
    array of 12-byte rows are copied sequentially by 0x142C61960. Their
    meanings are not inferred. Unframed/truncated trailers are rejected.
    """
    def take(size):
        nonlocal cursor
        if size < 0 or cursor + size > end:
            raise ValueError("Guide creation requires a complete, decoded PAC metadata trailer.")
        view = memoryview(data)[cursor:cursor+size]
        cursor += size
        return view

    def count(format):
        return struct.unpack(format, take(struct.calcsize(format)))[0]

    for _ in range(count("<B")):
        take(count("<B") * 16)
    if flags & 0x02000000:
        take(count("<I") * 12)
    else:
        take(4)
    take(count("<I"))
    if count("<B"):
        for _ in range(2):
            size = count("<I")
            if size == 0:
                raise ValueError("PAC optional metadata arrays cannot be empty when enabled.")
            take(size * 4)
    for _ in range(count("<H")):
        take(count("<H") * 16)
    take(count("<B") * 12)
    if cursor != end:
        raise ValueError("Guide creation cannot relocate undecoded trailing PAC metadata.")


def guide_creation_layout(data: bytes):
    """Admit only fully decoded metadata whose absolute offsets we can relocate."""
    if len(data) < 80 or data[:6] != b"PAR \x03\x09":
        raise ValueError("Guide creation requires the known PAC 3/9 layout.")
    sections = _parse_par_sections(data)
    if not sections or sections[0]["index"] != 0:
        raise ValueError("Guide creation requires complete PAC sections.")
    for section in sections:
        stored = struct.unpack_from("<I", data, 16 + section["index"] * 8)[0]
        if stored not in (0, section["size"]):
            raise ValueError("Guide creation requires decoded PAC sections.")
    metadata = sections[0]
    start, end = metadata["offset"], metadata["offset"] + metadata["size"]
    if metadata["size"] < 5:
        raise ValueError("Guide creation requires complete PAC metadata.")
    flags, lods = struct.unpack_from("<IB", data, start)
    if flags & 0xf00:
        raise ValueError("This PAC already has authored guides. Restore or edit those guides instead.")
    if not 2 <= lods <= 4 or [s["index"] for s in sections] != list(range(lods + 1)):
        raise ValueError("Guide creation requires the decoded 2, 3 or 4 LOD section layout.")
    if sections[-1]["offset"] + sections[-1]["size"] != len(data):
        raise ValueError("Guide creation cannot relocate undecoded data after the PAC sections.")
    count_offset = start + 5 + 8 * lods
    if count_offset + 2 > end:
        raise ValueError("Guide creation requires a complete descriptor count.")
    descriptors = _validated_pac_descriptor_prefix(
        _find_pac_descriptors(data, start, metadata["size"], lods), sections)
    count, = struct.unpack_from("<H", data, count_offset)
    if not descriptors or len(descriptors) != count:
        raise ValueError("Guide creation cannot locate every PAC descriptor.")
    insertion = max(d.descriptor_offset + 40 + 6 * d.stored_lod_count for d in descriptors)
    model = decode_pac_embedded_volumes(data)
    _validate_metadata_tail(data, model.file_end, end, flags)
    if (not 1 <= len(model.bone_palette) <= 1024
            or len(set(model.bone_palette)) != len(model.bone_palette)):
        raise ValueError("Guide creation requires an unambiguous existing bone palette.")
    levels = pac_cloth_lods(data)
    for lod, level in enumerate(levels):
        section = sections[lods - lod]
        vertex_offset, = struct.unpack_from("<I", data, start + 5 + 4 * lod)
        index_offset, = struct.unpack_from("<I", data, start + 5 + 4 * lods + 4 * lod)
        expected_split = section["offset"] + sum(len(p.vertices) * 40 for p in level.submeshes)
        if vertex_offset != section["offset"] or index_offset != expected_split:
            raise ValueError("Guide creation cannot prove the PAC vertex/index section offsets.")
        if any(data[offset + 39] & 63 != 63 for part in level.submeshes for offset in part.source_vertex_offsets):
            raise ValueError("A guide-free PAC contains unexpected existing render guide bindings.")
    return metadata, insertion, model.bone_palette, levels


def _skin(data, offset, palette_count, reduce_skinning):
    words = struct.unpack_from("<2I", data, offset + 20)
    slots = tuple((word >> shift) & 1023 for word in words for shift in (0, 10, 20))
    live = [(slot, weight) for slot, weight in zip(slots, data[offset + 28:offset + 34]) if weight]
    if not live or any(slot >= palette_count for slot, _ in live):
        raise ValueError("New cloth bindings require valid existing bone influences at every LOD.")
    if reduce_skinning:
        combined = {}
        for slot, weight in live:
            combined[slot] = combined.get(slot, 0) + weight
        live = sorted(combined.items(), key=lambda row: (-row[1], row[0]))[:4]
        total = sum(weight for _, weight in live)
        scaled = [weight / total * 255 for _, weight in live]
        quantized = [math.floor(value) for value in scaled]
        for i in sorted(range(len(live)), key=lambda i: (-(scaled[i]-quantized[i]), live[i][0]))[:255-sum(quantized)]:
            quantized[i] += 1
        live = [(slot, weight) for (slot, _), weight in zip(live, quantized, strict=True) if weight]
    elif len(live) > 4 or sum(weight for _, weight in live) != 255:
        raise ValueError("This source needs skeletal weight conversion. Enable Reduce skinning to four bones to allow it at every LOD.")
    # Compact without quantizing or dropping any live skeletal influence.
    live += [(live[0][0], 0)] * (4 - len(live))
    return tuple(v[0] for v in live), tuple(v[1] for v in live)


def _topology(points, faces, pins):
    edges, adjacent = {}, [set() for _ in points]
    for a, b, c in faces:
        ab = tuple(points[b][i] - points[a][i] for i in range(3))
        ac = tuple(points[c][i] - points[a][i] for i in range(3))
        cross = (ab[1]*ac[2]-ab[2]*ac[1], ab[2]*ac[0]-ab[0]*ac[2], ab[0]*ac[1]-ab[1]*ac[0])
        if math.hypot(*cross) <= 1e-12:
            raise ValueError("The guide source contains a degenerate triangle.")
        for x, y, opposite in ((a, b, c), (b, c, a), (c, a, b)):
            edge = tuple(sorted((x, y)))
            edges.setdefault(edge, []).append(opposite)
            adjacent[x].add(y)
            adjacent[y].add(x)
    if any(len(faces) > 2 for faces in edges.values()):
        raise ValueError("The guide source has a non-manifold edge. Choose a simpler source LOD.")
    if not pins or len(pins) == len(points):
        raise ValueError("Choose a pin height that leaves both fixed and moving guides.")
    # Deterministic multi-source forest. Root-to-leaf chains retain a fixed
    # first vertex, including isolated fixed roots; the fallback mode is cloth.
    parents = {pin: None for pin in sorted(pins)}
    queue = deque(parents)
    while queue:
        current = queue.popleft()
        for other in sorted(adjacent[current]):
            if other not in parents:
                parents[other] = current
                queue.append(other)
    if len(parents) != len(points):
        raise ValueError("Every disconnected guide piece needs a fixed guide. Lower the pin height or select fewer parts.")
    children = {parent for parent in parents.values() if parent is not None}
    groups = []
    for leaf in sorted(set(parents) - children):
        chain = []
        while leaf is not None:
            chain.append(leaf)
            leaf = parents[leaf]
        groups.append(tuple(reversed(chain)))
    records = [(*edge, 0, 0, 0) for edge in sorted(edges) if not set(edge) <= pins]
    records += [(*edge, *edges[edge], 1) for edge in sorted(edges) if len(edges[edge]) == 2]
    records += [(*face, 65535, 0) for face in faces]
    linear, area = [[] for _ in points], [[] for _ in points]
    for index, (a, b, c, d, tag) in enumerate(records):
        members = (a, b, c, d) if tag else ((a, b, c) if d == 65535 else (a, b))
        for vertex in members:
            (area if not tag and d == 65535 else linear)[vertex].append(index)
    refs, spans = [], []
    for first, second in zip(linear, area, strict=True):
        if max(len(first), len(second)) > 255:
            raise ValueError("Guide constraints exceed the per-vertex format limit.")
        spans.append((len(refs), len(first) | len(second) << 8))
        refs.extend(first + second)
    return edges, groups, records, refs, spans, linear


def _words(values):
    if any(type(v) is not int or not 0 <= v <= 65535 for v in values):
        raise ValueError("Guide tables exceed the uint16 format limit.")
    return struct.pack(f"<{len(values)}H", *values)


def _array(rows, format):
    return _words((len(rows),)) + b"".join(struct.pack(format, *row) for row in rows)


def _groups(rows):
    return _words((len(rows),)) + b"".join(_words((len(row), *row)) for row in rows)


def _guide_block(points, skins, faces, pins):
    minimum = tuple(min(p[i] for p in points) for i in range(3))
    extent = tuple(max(p[i] for p in points) - minimum[i] for i in range(3))
    try:
        box_bytes = struct.pack("<6f", *minimum, *extent)
    except (OverflowError, struct.error) as exc:
        raise ValueError("Guide bounds cannot be represented in the PAC format.") from exc
    box = struct.unpack("<6f", box_bytes)
    if not all(math.isfinite(v) for v in box):
        raise ValueError("Guide bounds must be finite.")
    quantized = [tuple(max(0, min(32767, round((p[i] - box[i]) / box[i+3] * 32767)))
                       if box[i+3] else 0 for i in range(3)) for p in points]
    decoded = [tuple(box[i] + q[i] / 32767 * box[i+3] for i in range(3)) for q in quantized]
    edges, groups, records, refs, spans, linear = _topology(decoded, faces, pins)
    if max(len(records), len(refs), len(faces)*3, len(edges)*2) > 65535:
        raise ValueError("Guide topology exceeds the format limits. Choose a simpler source LOD.")
    block = _words((len(points),))
    for q, (slots, weights) in zip(quantized, skins, strict=True):
        block += struct.pack("<4HI4B", *q, slots[3], slots[0] | slots[1] << 10 | slots[2] << 20, *weights)
    block += bytes(len(points)) + bytes(255 if i in pins else 0 for i in range(len(points)))
    block += _words((len(faces)*3, *(v for face in faces for v in face)))
    alpha = [sum(1 << (i % 32) for i in pins if i // 32 == word) for word in range((len(points)+31)//32)]
    block += struct.pack(f"<{len(alpha)}I", *alpha)
    block += _groups(groups) + _array(records, "<5H") + _words((len(refs), *refs))
    block += _array(spans, "<2H") + _groups(linear)
    block += _words((len(edges)*2, *(v for edge in sorted(edges) for v in edge)))
    return block + box_bytes, decoded


def _bindings(positions, guides):
    """Four nearest guides, inverse-distance weights with an exact 255 total."""
    import numpy as np
    guide_array = np.asarray(guides, dtype=np.float64)
    width = min(4, len(guides))
    for start in range(0, len(positions), 256):
        delta = np.asarray(positions[start:start+256], dtype=np.float64)[:, None, :] - guide_array[None, :, :]
        distances = np.einsum("vgi,vgi->vg", delta, delta)
        nearest = np.argsort(distances, axis=1, kind="stable")[:, :width]
        for row, indices in zip(distances, nearest, strict=True):
            ids = [int(v) for v in indices]
            values = [float(row[v]) for v in ids]
            if values[0] <= 1e-20:
                weights = [255] + [0] * (len(ids)-1)
            else:
                raw = [values[0] / v for v in values]
                scaled = [v / sum(raw) * 255 for v in raw]
                weights = [math.floor(v) for v in scaled]
                for i in sorted(range(len(ids)), key=lambda i: (-(scaled[i]-weights[i]), ids[i]))[:255-sum(weights)]:
                    weights[i] += 1
            ids += [ids[0]] * (4-len(ids))
            weights += [0] * (4-len(weights))
            yield ids, weights


def create_pac_cloth_guides(data: bytes, rules: Mapping[int, PacClothGuideRule], *, appearance=None) -> bytes:
    """Generate guides, constraints and bindings at all LODs, or fail atomically."""
    if not rules:
        return data
    metadata, insertion, palette, levels = guide_creation_layout(data)
    if any(type(i) is not int or not 0 <= i < len(levels[0].submeshes)
           or not isinstance(rule, PacClothGuideRule) for i, rule in rules.items()):
        raise ValueError("Guide settings refer to an invalid PAC part.")
    points, skins, faces, pins, ranges = [], [], [], set(), {}
    displayed = {}
    for index, rule in sorted(rules.items()):
        if rule.bone_palette != palette:
            raise ValueError("The captured guide bone palette does not match this PAC.")
        if rule.source_lod >= len(levels):
            raise ValueError("The guide source LOD is not stored in this PAC.")
        source = levels[rule.source_lod].submeshes[index]
        if not source.faces or not source.vertices:
            raise ValueError("The selected guide source LOD has no geometry for this part.")
        if rule.source_lod not in displayed:
            displayed[rule.source_lod] = appearance.to_neutral(levels[rule.source_lod]) if appearance else levels[rule.source_lod]
        heights = displayed[rule.source_lod].submeshes[index].vertices
        used = sorted({i for face in source.faces for i in face})
        first, weld, mapping = len(points), {}, {}
        for vertex in used:
            point = tuple(source.vertices[vertex])
            skin = _skin(data, source.source_vertex_offsets[vertex], len(palette), rule.reduce_skinning)
            key = (point, skin)
            if key not in weld:
                weld[key] = len(points)
                points.append(point)
                skins.append(skin)
                if heights[vertex][1] >= rule.fixed_above:
                    pins.add(weld[key])
            mapping[vertex] = weld[key]
        ranges[index] = (first, len(points))
        seen = set()
        for face in source.faces:
            row = tuple(mapping[v] for v in face)
            if len(set(row)) != 3:
                raise ValueError("Welding the guide source produces a degenerate triangle.")
            identity = tuple(sorted(row))
            if identity not in seen:
                faces.append(row)
                seen.add(identity)
    if not 3 <= len(points) <= 1024:
        raise ValueError("New cloth requires 3 to 1024 welded guides in total. Choose a lower source LOD or fewer parts.")
    block, decoded = _guide_block(points, skins, faces, pins)
    patched = bytearray(data)
    for level in levels:
        for index, (first, last) in ranges.items():
            part = level.submeshes[index]
            for offset, (ids, weights) in zip(part.source_vertex_offsets, _bindings(part.vertices, decoded[first:last]), strict=True):
                slots, bone_weights = _skin(data, offset, len(palette), rules[index].reduce_skinning)
                group0, group1 = struct.unpack_from("<2I", data, offset + 20)
                ids = [v + first for v in ids]
                struct.pack_into("<2I", patched, offset + 20,
                    (group0 & 0xc0000000) | slots[0] | slots[1] << 10 | slots[2] << 20,
                    (group1 & 0xc0000000) | slots[3] | ids[0] << 10 | ids[1] << 20)
                struct.pack_into("<2e", patched, offset + 12, ids[2], ids[3])
                patched[offset+28:offset+32] = bytes(bone_weights)
                patched[offset+32:offset+36] = bytes(weights)
                patched[offset+39] = data[offset+39] & 0xc0
    result = patched[:insertion] + block + patched[insertion:]
    start = metadata["offset"]
    flags, = struct.unpack_from("<I", data, start)
    struct.pack_into("<I", result, start, (flags & ~0x8f00) | 0x300)
    struct.pack_into("<2I", result, 16, 0, metadata["size"] + len(block))
    for i in range(2 * len(levels)):
        offset = start + 5 + 4*i
        value, = struct.unpack_from("<I", data, offset)
        struct.pack_into("<I", result, offset, value + len(block))
    result = bytes(result)
    guides = decode_pac_cloth_guides(result)
    if guides is None or not all(v for v in inspect_guide_topology(guides).values() if type(v) is bool):
        raise ValueError("Generated guide topology did not pass independent decoding.")
    if decode_pac_embedded_volumes(result).bone_palette != palette:
        raise ValueError("Guide creation changed the retained bone palette.")
    return result
