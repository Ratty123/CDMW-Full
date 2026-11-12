"""Bounded new-guide construction for decoded, guide-free PAC metadata.

Creates layout 3 cloth on an existing skeleton. This never extends a skeleton,
edits an archive, replaces authored guides, or guesses unknown metadata offsets.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
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
        _find_pac_descriptors(data, start, metadata["size"], lods), sections, lod_count=lods)
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


def _flat(points, face):
    a, b, c = (points[v] for v in face)
    ab = tuple(b[i] - a[i] for i in range(3))
    ac = tuple(c[i] - a[i] for i in range(3))
    cross = (ab[1]*ac[2]-ab[2]*ac[1], ab[2]*ac[0]-ab[0]*ac[2], ab[0]*ac[1]-ab[1]*ac[0])
    return math.hypot(*cross) <= 1e-12


def _topology(points, faces, pins):
    edges, adjacent = {}, [set() for _ in points]
    for a, b, c in faces:
        # drop_flat_stored_triangles removes these first; this stays as the format's own guard.
        if _flat(points, (a, b, c)):
            raise ValueError("The guide source contains a degenerate triangle.")
        for x, y, opposite in ((a, b, c), (b, c, a), (c, a, b)):
            edge = tuple(sorted((x, y)))
            edges.setdefault(edge, []).append(opposite)
            adjacent[x].add(y)
            adjacent[y].add(x)
    if any(len(faces) > 2 for faces in edges.values()):
        raise ValueError("The guide source has a non-manifold edge. Choose a simpler source LOD.")
    if not pins or len(pins) == len(points):
        raise ValueError("Choose a pin height or pins that leave both fixed and moving guides.")
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
        raise ValueError("Every disconnected guide piece needs a fixed guide. Lower the pin height, paint a pin on each piece or select fewer parts.")
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


def _stored(points):
    """The guide positions as the PAC stores them: 15 bits an axis across their bounds."""
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
    return box_bytes, quantized, decoded


def drop_flat_stored_triangles(points, faces):
    """Drop triangles that have no area once the positions are stored.

    A thin triangle can pass in the source and still be flat at 15 bits an axis.
    Dropping one can leave a guide unused, and leaving it out changes the bounds
    the others are stored against, so this repeats until nothing is flat; every
    pass removes at least one triangle, so it ends. Returns the points still used
    (indices into ``points``, in order), the remaining faces renumbered to them,
    and the indices of the dropped faces.
    """
    alive, dropped, used = list(range(len(faces))), [], []
    while True:
        used = sorted({v for i in alive for v in faces[i]})
        if not used:
            break
        stored = dict(zip(used, _stored([points[v] for v in used])[2]))
        flat = {i for i in alive if _flat(stored, faces[i])}
        if not flat:
            break
        dropped += sorted(flat)
        alive = [i for i in alive if i not in flat]
    index = {v: n for n, v in enumerate(used)}
    return used, [tuple(index[v] for v in faces[i]) for i in alive], sorted(dropped)


def _guide_block(points, skins, faces, pins):
    box_bytes, quantized, decoded = _stored(points)
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


#: Painted pins must sit on the part's LOD0 vertices within this share of its size.
PIN_TOLERANCE = 1e-3


def _painted_pins(lod0, source, pinned_points, name):
    """Per source-LOD vertex: pinned when its nearest LOD0 vertex was painted as a pin.

    Every painted pin must still sit on a LOD0 vertex of the part, so pins painted
    before an edit that moved or removed those vertices are refused, not misplaced.
    """
    if not pinned_points:
        return [False] * len(source)
    from .pac_cloth_paint import ClothPaintSamples, _nearest_values
    if not lod0:
        raise ValueError(f"Cloth pins for {name} need the part's LOD0 geometry.")
    low = [min(p[i] for p in lod0) for i in range(3)]
    high = [max(p[i] for p in lod0) for i in range(3)]
    tolerance = max(1e-6, math.dist(low, high) * PIN_TOLERANCE)
    reference = ClothPaintSamples(tuple(tuple(float(v) for v in p[:3]) for p in lod0), (0.0,) * len(lod0))
    _, distances = _nearest_values(pinned_points, reference, tolerance)
    if any(distance > tolerance for distance in distances):
        raise ValueError(f"Cloth pins on {name} no longer line up with its vertices. "
                         "Create the cloth guides again; paint the pins first if they are gone.")
    pins = ClothPaintSamples(tuple(tuple(float(v) for v in p) for p in pinned_points), (1.0,) * len(pinned_points))
    # Mark the LOD0 vertices the pins sit on, then give each source vertex its
    # nearest LOD0 vertex's mark (exact for LOD0, closest match below it).
    _, to_pin = _nearest_values(reference.positions, pins, tolerance)
    if source is lod0:
        return [distance <= tolerance for distance in to_pin]
    marks = ClothPaintSamples(reference.positions, tuple(1.0 if d <= tolerance else 0.0 for d in to_pin))
    values, _ = _nearest_values([tuple(float(v) for v in p[:3]) for p in source], marks)
    return [value > 0.5 for value in values]


@dataclass(frozen=True, slots=True)
class SkippedGuideTriangles:
    """Triangles of one part's guide source that make no guide face."""

    part: str
    lod: int
    #: Two corners welded into one guide (a sliver along a seam).
    collapsed: int
    #: No area once the guide positions are stored at 15 bits an axis.
    flat: int


@dataclass(frozen=True, slots=True)
class GuideBuildReport:
    guide_count: int
    skipped: tuple[SkippedGuideTriangles, ...] = ()
    #: The build's non-blocking findings (`cdmw.domain.mesh.findings.MeshFinding`), such as skipped triangles.
    findings: tuple = ()


def _unheld_pieces(count, faces, pins):
    """Connected guide pieces with no fixed guide, as sets of guide indices."""
    parent = list(range(count))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, c in faces:
        parent[find(a)] = find(b)
        parent[find(b)] = find(c)
    held = {find(p) for p in pins}
    pieces = {}
    for vertex in range(count):
        root = find(vertex)
        if root not in held:
            pieces.setdefault(root, set()).add(vertex)
    return list(pieces.values())


# ------------------------------------------------------------ check, then build

GUIDE_LIMIT = 1024
CATEGORY = "cloth_guides"
# Finding kinds. The check produces them and the builder refuses on the blockers,
# so the status shown before a build and the refusal at build time are one result.
CODE_LAYOUT = "cloth_guide.layout"
CODE_RULE = "cloth_guide.rule"
CODE_PINS_MISALIGNED = "cloth_guide.pins_misaligned"
CODE_INVALID_INFLUENCES = "cloth_guide.invalid_influences"
CODE_NEEDS_REDUCE_SKINNING = "cloth_guide.needs_reduce_skinning"
CODE_COLLAPSED_TRIANGLES = "cloth_guide.collapsed_triangles"
CODE_FLAT_TRIANGLES = "cloth_guide.flat_triangles"
CODE_NOTHING_LEFT = "cloth_guide.nothing_left"
CODE_GUIDE_LIMIT = "cloth_guide.guide_limit"
CODE_UNHELD_PIECE = "cloth_guide.unheld_piece"
CODE_NON_MANIFOLD = "cloth_guide.non_manifold_edge"
CODE_PINS = "cloth_guide.pins"


@dataclass(frozen=True, slots=True)
class ClothGuideCheck:
    """What a guide build of these rules would do, without building it."""

    findings: tuple
    guide_count: int
    #: Guides per part index, after welding and skipping.
    part_guides: tuple[tuple[int, int], ...] = ()

    @property
    def blockers(self):
        return tuple(finding for finding in self.findings if finding.is_blocker)

    @property
    def builds(self) -> bool:
        return not self.blockers


@dataclass(frozen=True, slots=True)
class ClothGuideLodStatus:
    """Whether one part builds from one source LOD, measured with that part alone."""

    part_index: int
    part: str
    lod: int
    guide_count: int
    collapsed: int
    flat: int
    findings: tuple

    @property
    def builds(self) -> bool:
        return not any(finding.is_blocker for finding in self.findings) and self.guide_count <= GUIDE_LIMIT

    @property
    def blockers(self):
        return tuple(finding for finding in self.findings if finding.is_blocker)


@dataclass(slots=True)
class _GuidePlan:
    findings: list
    metadata: object = None
    insertion: int = 0
    palette: tuple = ()
    levels: tuple = ()
    points: list = None
    skins: list = None
    owners: list = None
    faces: list = None
    pins: set = None
    ranges: dict = None
    names: dict = None
    collapsed: dict = None
    flat: dict = None


def _finding(severity, code, message, **values):
    from cdmw.domain.mesh.findings import mesh_finding

    return mesh_finding(severity, code, message, category=CATEGORY, **values)


def _skin_findings(data, levels, index, name, palette_count, reduce_skinning):
    """Blockers for render vertices of one part, at every LOD, that guides cannot bind."""
    from cdmw.domain.mesh.findings import ELEMENT_VERTEX, FIX_CLOTH_REDUCE_SKINNING

    found = []
    for lod, level in enumerate(levels):
        if index >= len(level.submeshes):
            continue
        invalid, heavy = [], []
        for vertex, offset in enumerate(level.submeshes[index].source_vertex_offsets):
            try:
                _skin(data, offset, palette_count, reduce_skinning)
            except ValueError as exc:
                (heavy if "Reduce skinning" in str(exc) else invalid).append(vertex)
        if invalid:
            found.append(_finding(
                "blocker", CODE_INVALID_INFLUENCES,
                f"{name}, LOD {lod}: {len(invalid):,} vertices have no valid bone influence. "
                "New cloth bindings require valid existing bone influences at every LOD.",
                part=name, lod=lod, submesh=index, element_kind=ELEMENT_VERTEX, elements=invalid))
        if heavy:
            found.append(_finding(
                "blocker", CODE_NEEDS_REDUCE_SKINNING,
                f"{name}, LOD {lod}: {len(heavy):,} vertices need skeletal weight conversion. "
                "Enable Reduce skinning to four bones to allow it at every LOD.",
                part=name, lod=lod, submesh=index, element_kind=ELEMENT_VERTEX, elements=heavy,
                fix_command=FIX_CLOTH_REDUCE_SKINNING, fix_arguments={"part": index}))
    return found


def _plan_guides(data, rules, appearance) -> _GuidePlan:
    """Everything the build decides, as findings plus the inputs the writer needs.

    Never raises for a problem with the source; each becomes a finding. Only an
    invalid rule mapping (a programming error) raises.
    """
    from cdmw.domain.mesh.findings import (
        ELEMENT_FACE, ELEMENT_GUIDE, FIX_CLEAN_UP_MESH, FIX_CLOTH_FEWER_PARTS, FIX_CLOTH_PINS, FIX_CLOTH_SOURCE_LOD,
    )

    plan = _GuidePlan(findings=[])
    try:
        plan.metadata, plan.insertion, plan.palette, plan.levels = guide_creation_layout(data)
    except ValueError as exc:
        plan.findings.append(_finding("blocker", CODE_LAYOUT, str(exc)))
        return plan
    levels, palette = plan.levels, plan.palette
    if any(type(i) is not int or not 0 <= i < len(levels[0].submeshes)
           or not isinstance(rule, PacClothGuideRule) for i, rule in rules.items()):
        raise ValueError("Guide settings refer to an invalid PAC part.")
    points, skins, owners, faces, face_owners, face_sources, pins = [], [], [], [], [], [], set()
    names, collapsed, displayed, usable = {}, {}, {}, []
    for index, rule in sorted(rules.items()):
        names[index] = str(index)
        collapsed[index] = 0
        if rule.bone_palette != palette:
            plan.findings.append(_finding("blocker", CODE_RULE, "The captured guide bone palette does not match this PAC.",
                                          submesh=index))
            continue
        if rule.source_lod >= len(levels):
            plan.findings.append(_finding("blocker", CODE_RULE, "The guide source LOD is not stored in this PAC.",
                                          submesh=index, fix_command=FIX_CLOTH_SOURCE_LOD,
                                          fix_arguments={"part": index}))
            continue
        source = levels[rule.source_lod].submeshes[index]
        name = names[index] = source.name or str(index)
        if not source.faces or not source.vertices:
            plan.findings.append(_finding(
                "blocker", CODE_RULE, "The selected guide source LOD has no geometry for this part.",
                part=name, lod=rule.source_lod, submesh=index, fix_command=FIX_CLOTH_SOURCE_LOD,
                fix_arguments={"part": index}))
            continue
        for lod in {0, rule.source_lod}:
            if lod not in displayed:
                displayed[lod] = appearance.to_neutral(levels[lod]) if appearance else levels[lod]
        heights = displayed[rule.source_lod].submeshes[index].vertices
        try:
            painted = _painted_pins(displayed[0].submeshes[index].vertices, heights, rule.pinned_points, name)
        except ValueError as exc:
            plan.findings.append(_finding("blocker", CODE_PINS_MISALIGNED, str(exc), part=name, lod=rule.source_lod,
                                          submesh=index, fix_command=FIX_CLOTH_PINS, fix_arguments={"part": index}))
            continue
        skin_problems = _skin_findings(data, levels, index, name, len(palette), rule.reduce_skinning)
        if skin_problems:
            plan.findings.extend(skin_problems)
            continue
        used = sorted({i for face in source.faces for i in face})
        weld, local, local_skins, local_pins, mapping = {}, [], [], set(), {}
        for vertex in used:
            point = tuple(source.vertices[vertex])
            skin = _skin(data, source.source_vertex_offsets[vertex], len(palette), rule.reduce_skinning)
            key = (point, skin)
            if key not in weld:
                weld[key] = len(local)
                local.append(point)
                local_skins.append(skin)
            if (rule.fixed_above is not None and heights[vertex][1] >= rule.fixed_above) or painted[vertex]:
                local_pins.add(weld[key])
            mapping[vertex] = weld[key]
        kept, kept_sources, seen, collapsed_faces = [], [], set(), []
        for face_index, face in enumerate(source.faces):
            row = tuple(mapping[v] for v in face)
            if len(set(row)) != 3:
                # Welding collapsed a sliver; its corners become guides only through other faces.
                collapsed_faces.append(face_index)
                continue
            identity = tuple(sorted(row))
            if identity not in seen:
                kept.append(row)
                kept_sources.append(face_index)
                seen.add(identity)
        collapsed[index] = len(collapsed_faces)
        if not kept:
            plan.findings.append(_finding(
                "blocker", CODE_NOTHING_LEFT,
                f"{name}, LOD {rule.source_lod}: all {len(source.faces):,} triangles collapse when "
                "the guide source is welded, so there is nothing to build guides from. "
                "Choose another source LOD or leave this part out.",
                part=name, lod=rule.source_lod, submesh=index, element_kind=ELEMENT_FACE, elements=collapsed_faces,
                fix_command=FIX_CLOTH_SOURCE_LOD, fix_arguments={"part": index}))
            continue
        if collapsed_faces:
            plan.findings.append(_finding(
                "warning", CODE_COLLAPSED_TRIANGLES,
                f"Skipped {len(collapsed_faces):,} collapsed triangles on {name}, LOD {rule.source_lod}.",
                part=name, lod=rule.source_lod, submesh=index, element_kind=ELEMENT_FACE, elements=collapsed_faces,
                fix_command=FIX_CLEAN_UP_MESH, fix_arguments={"lod": rule.source_lod, "part": index}))
        usable.append(index)
        # A guide only for a vertex a kept triangle uses: an unused one would count
        # against the limit and, unpinned, be a piece that nothing holds.
        keep = sorted({v for face in kept for v in face})
        renumber = {v: len(points) + n for n, v in enumerate(keep)}
        points += [local[v] for v in keep]
        skins += [local_skins[v] for v in keep]
        owners += [index] * len(keep)
        pins |= {renumber[v] for v in local_pins if v in renumber}
        faces += [tuple(renumber[v] for v in face) for face in kept]
        face_owners += [index] * len(kept)
        face_sources += kept_sources
    plan.names, plan.collapsed = names, collapsed
    if any(finding.is_blocker for finding in plan.findings):
        # Measured parts still report their guides; nothing below can change the refusal.
        plan.flat = dict.fromkeys(rules, 0)
        return plan
    order, faces, dropped = drop_flat_stored_triangles(points, faces)
    flat_faces = {index: [] for index in rules}
    for face in dropped:
        flat_faces[face_owners[face]].append(face_sources[face])
    plan.flat = {index: len(values) for index, values in flat_faces.items()}
    gone = set(dropped)
    face_sources = [source for face, source in enumerate(face_sources) if face not in gone]
    renumber = {old: new for new, old in enumerate(order)}
    points, skins, owners = [points[i] for i in order], [skins[i] for i in order], [owners[i] for i in order]
    pins = {renumber[p] for p in pins if p in renumber}
    ranges = {}
    for guide, index in enumerate(owners):
        ranges[index] = (ranges.get(index, (guide, guide))[0], guide + 1)
    for index in usable:
        rule = rules[index]
        if flat_faces[index]:
            plan.findings.append(_finding(
                "warning", CODE_FLAT_TRIANGLES,
                f"Skipped {len(flat_faces[index]):,} triangles too thin to store on {names[index]}, "
                f"LOD {rule.source_lod}.",
                part=names[index], lod=rule.source_lod, submesh=index, element_kind=ELEMENT_FACE,
                elements=flat_faces[index], fix_command=FIX_CLEAN_UP_MESH,
                fix_arguments={"lod": rule.source_lod, "part": index}))
        if index not in ranges:
            plan.findings.append(_finding(
                "blocker", CODE_NOTHING_LEFT,
                f"{names[index]}, LOD {rule.source_lod}: all {plan.flat[index] + collapsed[index]:,} "
                "triangles are too thin to store as guide faces, so there is nothing to build "
                "guides from. Choose another source LOD or leave this part out.",
                part=names[index], lod=rule.source_lod, submesh=index, element_kind=ELEMENT_FACE,
                elements=flat_faces[index], fix_command=FIX_CLOTH_SOURCE_LOD, fix_arguments={"part": index}))
    plan.points, plan.skins, plan.owners, plan.faces, plan.pins, plan.ranges = (
        points, skins, owners, faces, pins, ranges)
    if any(finding.is_blocker for finding in plan.findings):
        return plan
    if not 3 <= len(points) <= GUIDE_LIMIT:
        plan.findings.append(_finding(
            "blocker", CODE_GUIDE_LIMIT,
            f"New cloth requires 3 to 1024 welded guides in total; these parts give {len(points):,}. "
            "Choose a lower source LOD or fewer parts.",
            element_kind=ELEMENT_GUIDE, element_count=len(points), fix_command=FIX_CLOTH_FEWER_PARTS))
        return plan
    edges = {}
    for face_index, face in enumerate(faces):
        for x, y in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            edges.setdefault(tuple(sorted((x, y))), []).append(face_index)
    shared = {}
    for edge, users in edges.items():
        if len(users) > 2:
            shared.setdefault(owners[edge[0]], []).append(users)
    for index, users in sorted(shared.items()):
        rule = rules[index]
        plan.findings.append(_finding(
            "blocker", CODE_NON_MANIFOLD,
            f"{names[index]}, LOD {rule.source_lod}: {len(users):,} edges are shared by more than two "
            "triangles, which cloth guides cannot use. Choose a simpler source LOD.",
            part=names[index], lod=rule.source_lod, submesh=index, element_kind=ELEMENT_FACE,
            elements=(face_sources[face] for faces_on_edge in users for face in faces_on_edge),
            fix_command=FIX_CLOTH_SOURCE_LOD, fix_arguments={"part": index}))
    if shared:
        return plan
    if not pins or len(pins) == len(points):
        plan.findings.append(_finding("blocker", CODE_PINS,
                                      "Choose a pin height or pins that leave both fixed and moving guides.",
                                      fix_command=FIX_CLOTH_PINS))
        return plan
    loose = {}
    for piece in _unheld_pieces(len(points), faces, pins):
        loose.setdefault(owners[min(piece)], []).append(piece)
    # One refusal text naming every part, as it always has; one finding per part.
    where = "; ".join(f"{len(pieces):,} on {names[index]}, LOD {rules[index].source_lod}"
                      for index, pieces in sorted(loose.items()))
    for index, pieces in sorted(loose.items()):
        plan.findings.append(_finding(
            "blocker", CODE_UNHELD_PIECE,
            f"Every disconnected guide piece needs a fixed guide ({where} without one). Lower the "
            "pin height, paint a pin on each piece or select fewer parts.",
            part=names[index], lod=rules[index].source_lod, submesh=index, element_kind=ELEMENT_GUIDE,
            elements=(guide for piece in pieces for guide in piece),
            fix_command=FIX_CLOTH_PINS, fix_arguments={"part": index}))
    return plan


def check_pac_cloth_guides(data: bytes, rules: Mapping[int, PacClothGuideRule], *, appearance=None) -> ClothGuideCheck:
    """The findings a guide build of ``rules`` would act on, without building anything.

    A pure function of the PAC bytes and the rules: ``create_pac_cloth_guides``
    runs this same check and refuses on its blockers, so a status shown before
    the build and the refusal at build time cannot disagree. Pass the bytes the
    build will read (the output prepared for the current edit), not the original.
    """
    if not rules:
        return ClothGuideCheck((), 0)
    plan = _plan_guides(data, rules, appearance)
    counts = {}
    for owner in plan.owners or ():
        counts[owner] = counts.get(owner, 0) + 1
    return ClothGuideCheck(tuple(plan.findings), len(plan.points or ()), tuple(sorted(counts.items())))


def cloth_guide_lod_statuses(data: bytes, rules: Mapping[int, PacClothGuideRule], *, appearance=None):
    """For each part of ``rules`` and each stored LOD: would guides build from it?

    Each part is measured alone, with its own rule at that LOD, so a user can pick
    a source LOD that works before building. The 1,024-guide limit applies to
    all chosen parts together; ``check_pac_cloth_guides`` measures that.
    """
    from dataclasses import replace

    try:
        levels = pac_cloth_lods(data)
    except ValueError:
        levels = ()
    statuses = []
    for index, rule in sorted(rules.items()):
        for lod in range(len(levels)):
            plan = _plan_guides(data, {index: replace(rule, source_lod=lod)}, appearance)
            guides = len(plan.points or ())
            name = (plan.names or {}).get(index, str(index))
            findings = list(plan.findings)
            if guides > GUIDE_LIMIT and not any(f.code == CODE_GUIDE_LIMIT for f in findings):
                findings.append(_finding("blocker", CODE_GUIDE_LIMIT,
                                         f"{name}, LOD {lod}: {guides:,} guides; at most 1,024 are allowed.",
                                         part=name, lod=lod, submesh=index, element_count=guides))
            statuses.append(ClothGuideLodStatus(index, name, lod, guides, (plan.collapsed or {}).get(index, 0),
                                                (plan.flat or {}).get(index, 0), tuple(findings)))
    return tuple(statuses)


def create_pac_cloth_guides(data: bytes, rules: Mapping[int, PacClothGuideRule], *, appearance=None) -> bytes:
    """Generate guides, constraints and bindings at all LODs, or fail atomically."""
    return create_pac_cloth_guides_with_report(data, rules, appearance=appearance)[0]


def create_pac_cloth_guides_with_report(
        data: bytes, rules: Mapping[int, PacClothGuideRule], *, appearance=None) -> tuple[bytes, GuideBuildReport]:
    """As ``create_pac_cloth_guides``, with what the build left out.

    A triangle that welding collapses, or that is flat once stored, makes no guide
    face and is reported per part; the render mesh is unchanged. The build runs
    ``check_pac_cloth_guides`` first and is refused on its first blocker, whose
    message names the part, LOD and count; the error carries every finding.
    """
    from cdmw.domain.mesh.findings import raise_for_blockers

    if not rules:
        return data, GuideBuildReport(0)
    plan = _plan_guides(data, rules, appearance)
    raise_for_blockers(plan.findings)
    metadata, insertion, palette, levels = plan.metadata, plan.insertion, plan.palette, plan.levels
    points, skins, faces, pins, ranges = plan.points, plan.skins, plan.faces, plan.pins, plan.ranges
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
    names, collapsed, flat = plan.names, plan.collapsed, plan.flat
    skipped = tuple(SkippedGuideTriangles(names[index], rules[index].source_lod, collapsed[index], flat[index])
                    for index in sorted(rules) if collapsed[index] or flat[index])
    warnings = tuple(finding for finding in plan.findings if not finding.is_blocker)
    return result, GuideBuildReport(len(points), skipped, warnings)


