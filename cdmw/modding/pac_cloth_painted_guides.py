"""Build a PAC's own cloth guides from painted cloth, replacing any template guides.

The painted cloth bind (``pac_cloth_paint``) ties painted vertices to the guides a
template already ships. Those guides follow the template's garment, not the
import's, so a skirt over a cloak's guides swings from the wrong places. This
module instead:

1. removes the template's guide block and turns every render vertex back to
   skeleton-only (``remove_pac_cloth_guides``);
2. takes the painted faces of the highest-detail stored LOD that fits, welds
   them by position, and reduces them by edge collapse when no LOD has at most
   1,024 guides (``reduce_guide_mesh``);
3. pins the guides where the painted area meets unpainted vertices (the line it
   hangs from) and wherever a pin was painted;
4. writes the guide block with the existing builder's grammar, then binds the
   painted render vertices at every LOD to the new guides, blending by paint.

Each step decodes its result again. Nothing is guessed: a painted area that
does not line up with the built model, has no pinned guide, or cannot be made a
manifold mesh of at most 1,024 guides is refused with the reason.
"""

from __future__ import annotations

import heapq
import math
import struct
from collections import defaultdict
from dataclasses import dataclass

from .mesh_parser import PAC_SKIN_EXTRA_INDEX_SENTINEL, _parse_par_sections
from .pabv_parser import decode_pac_embedded_volumes
from .pac_cloth import pac_cloth_lods
from .pac_cloth_guide_builder import _guide_block, _skin, guide_creation_layout
from .pac_cloth_guides import decode_pac_cloth_guides, inspect_guide_topology
from .pac_cloth_paint import ClothPaintSamples, _nearest_values, apply_pac_cloth_paint, blend_for_paint

GUIDE_LIMIT = 1024
#: Reduction stops a little under the limit so welding noise cannot push it over.
REDUCTION_TARGET = 1000
REDUCTION_PASSES = 12
#: How straight a border must run for a vertex to slide along it, per pass: strict
#: first, then a little looser so a gently curved hem can still be thinned.
BORDER_STRAIGHTNESS = (0.985, 0.985, 0.94, 0.94, 0.87)


@dataclass(frozen=True, slots=True)
class PaintedGuideReport:
    guide_count: int
    pinned_guides: int
    source_lod: int
    source_vertices: int
    reduced: bool
    cloth_vertices: int
    rigid_vertices: int
    reduced_skin_vertices: int
    cloth_parts: tuple[str, ...]
    removed_template_guides: int
    #: Painted pieces nothing holds: they get no guides and follow the nearest held cloth.
    riding_pieces: int = 0


def remove_pac_cloth_guides(data: bytes) -> tuple[bytes, int]:
    """Drop the guide block and every render binding; return the data and old guide count.

    Render records keep their four skeletal slots, foreign bits and every other
    lane, exactly as switching a cloth vertex back to bones does elsewhere. The
    block is located from the decoder's own ranges, and the result must pass the
    guide creator's admission check (no guides, no bindings, decoded trailer).
    """
    guides = decode_pac_cloth_guides(data)
    result = bytearray(data)
    for level in pac_cloth_lods(data):
        for part in level.submeshes:
            for offset in part.source_vertex_offsets:
                if data[offset + 39] & 63 == 63:
                    continue
                group1, = struct.unpack_from("<I", data, offset + 24)
                struct.pack_into("<I", result, offset + 24, group1 & 0xC00003FF)
                result[offset + 12:offset + 16] = PAC_SKIN_EXTRA_INDEX_SENTINEL
                result[offset + 32:offset + 36] = bytes(4)
                result[offset + 39] = (data[offset + 39] & 0xC0) | 63
    if guides is None:
        result = bytes(result)
        guide_creation_layout(result)
        return result, 0
    sections = _parse_par_sections(data)
    metadata = sections[0]
    start, lods = metadata["offset"], data[metadata["offset"] + 4]
    first, last = guides.ranges[0], guides.ranges[-1]
    block_start, block_end = first.offset, last.offset + last.count * last.stride
    if first.name != "vertices_count" or last.name != "guide_bbox" or not start < block_start < block_end:
        raise ValueError("The template's cloth guide block could not be located exactly.")
    size = block_end - block_start
    stored, total = struct.unpack_from("<2I", data, 16)
    if stored not in (0, total) or total != metadata["size"]:
        raise ValueError("Guide removal needs decompressed PAC metadata.")
    flags, = struct.unpack_from("<I", data, start)
    struct.pack_into("<I", result, start, flags & ~0x8F00)
    struct.pack_into("<2I", result, 16, stored and total - size, total - size)
    for i in range(2 * lods):
        offset = start + 5 + 4 * i
        struct.pack_into("<I", result, offset, struct.unpack_from("<I", data, offset)[0] - size)
    result = bytes(result[:block_start] + result[block_end:])
    if decode_pac_cloth_guides(result) is not None:
        raise ValueError("Guide removal left a guide block behind.")
    guide_creation_layout(result)
    if decode_pac_embedded_volumes(result).bone_palette != decode_pac_embedded_volumes(data).bone_palette:
        raise ValueError("Guide removal changed the retained bone palette.")
    return result, len(guides.vertices)


def _normal(points, face):
    a, b, c = (points[i] for i in face)
    ab = [b[i] - a[i] for i in range(3)]
    ac = [c[i] - a[i] for i in range(3)]
    return (ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0])


def _edges_of(face):
    a, b, c = face
    return (tuple(sorted((a, b))), tuple(sorted((b, c))), tuple(sorted((a, c))))


def manifold_problem(faces) -> str:
    counts = defaultdict(int)
    for face in faces:
        for edge in _edges_of(face):
            counts[edge] += 1
    return "non-manifold edge" if any(count > 2 for count in counts.values()) else ""


def reduce_guide_mesh(points, faces, pins, *, target=REDUCTION_TARGET, check_cancelled=lambda: None):
    """Collapse the shortest edges until at most ``target`` vertices remain.

    Half-edge collapse: the removed vertex moves onto a kept one, so every
    surviving guide keeps an original position and its original skin. A
    collapse is refused when it would make the mesh non-manifold (link
    condition), flip or flatten a face, move a pin onto an unpinned vertex, or
    pull an open border inwards. An edge refused once is tried again after the
    mesh around it has changed, for a bounded number of passes. Returns (kept
    original indices, faces in kept order, pins in kept order) or raises
    ValueError when the target is unreachable.
    """
    faces = {tuple(face) for face in faces}
    vertex_faces = defaultdict(set)
    for face in faces:
        for vertex in face:
            vertex_faces[vertex].add(face)
    alive = set(vertex_faces)
    if len(alive) <= target:
        order = sorted(alive)
        index = {v: i for i, v in enumerate(order)}
        return order, [tuple(index[v] for v in face) for face in sorted(faces)], {index[v] for v in pins if v in index}

    def neighbours(vertex):
        return {other for face in vertex_faces[vertex] for other in face if other != vertex}

    def edge_faces(a, b):
        return [face for face in vertex_faces[a] if b in face]

    def on_border(vertex):
        return any(len(edge_faces(vertex, other)) == 1 for other in neighbours(vertex))

    def length(a, b):
        return math.dist(points[a], points[b])

    def edge_heap():
        heap = list({(length(a, b), a, b) for face in faces for a, b in _edges_of(face)})
        heapq.heapify(heap)
        return heap

    def collapse_ok(u, v):
        if u in pins and v not in pins:
            return False
        shared = edge_faces(u, v)
        if not shared:
            return False
        if on_border(u):
            if len(shared) != 1:
                return False  # a border vertex may slide only along its border
            # ... and only where the border runs straight, so hems keep their corners.
            ends = [w for w in neighbours(u) if len(edge_faces(u, w)) == 1]
            if len(ends) != 2:
                return False
            a, b = ([points[w][i] - points[u][i] for i in range(3)] for w in ends)
            size = math.hypot(*a) * math.hypot(*b)
            if size <= 1e-20 or sum(x * y for x, y in zip(a, b)) > -straight * size:
                return False
        link = neighbours(u) & neighbours(v)
        opposite = {w for face in shared for w in face if w not in (u, v)}
        if link != opposite:
            return False
        present = {frozenset(face) for face in vertex_faces[v]}
        for face in vertex_faces[u]:
            if v in face:
                continue
            moved = tuple(v if w == u else w for w in face)
            if frozenset(moved) in present:
                return False
            before, after = _normal(points, face), _normal(points, moved)
            size_before, size_after = math.hypot(*before), math.hypot(*after)
            if size_after <= 1e-12 or sum(x * y for x, y in zip(before, after)) <= 0.2 * size_before * size_after:
                return False
        return True

    steps, straight = 0, BORDER_STRAIGHTNESS[0]
    for turn in range(REDUCTION_PASSES):
        straight = BORDER_STRAIGHTNESS[min(turn, len(BORDER_STRAIGHTNESS) - 1)]
        heap, collapsed = edge_heap(), 0
        while len(alive) > target and heap:
            steps += 1
            if steps % 2048 == 0:
                check_cancelled()
            _, a, b = heapq.heappop(heap)
            if a not in alive or b not in alive or not edge_faces(a, b):
                continue
            for u, v in ((a, b), (b, a)):
                if not collapse_ok(u, v):
                    continue
                for face in list(vertex_faces[u]):
                    for w in face:
                        vertex_faces[w].discard(face)
                    faces.discard(face)
                    if v in face:
                        continue
                    moved = tuple(v if w == u else w for w in face)
                    faces.add(moved)
                    for w in moved:
                        vertex_faces[w].add(moved)
                alive.discard(u)
                del vertex_faces[u]
                collapsed += 1
                for other in neighbours(v):
                    heapq.heappush(heap, (length(v, other), *sorted((v, other))))
                break
        # An edge refused earlier may collapse now that its surroundings changed.
        if len(alive) <= target or (not collapsed and turn >= len(BORDER_STRAIGHTNESS) - 1):
            break
    if len(alive) > target:
        raise ValueError(f"The painted area could not be reduced to {target} cloth guides without "
                         f"breaking its surface (it stops at {len(alive):,}). Paint a smaller area.")
    order = sorted(alive)
    index = {v: i for i, v in enumerate(order)}
    return order, [tuple(index[v] for v in face) for face in sorted(faces)], {index[v] for v in pins if v in index}


def held_guide_pieces(points, records, faces, pins):
    """Keep the connected pieces a pin holds; the rest ride the nearest kept guide.

    A painted button, trim strip or tassel is a piece of its own with no
    attachment line. It gets no guides: its vertices are still cloth and bind to
    the nearest guide of the cloth it sits on. Returns (points, records, faces,
    pins, dropped piece count); nothing is dropped when no piece is held, so the
    caller can say that nothing holds the cloth at all.
    """
    parent = list(range(len(points)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, c in faces:
        for x, y in ((a, b), (b, c)):
            parent[find(x)] = find(y)
    held = {find(p) for p in pins}
    loose = {find(v) for face in faces for v in face} - held
    if not held or not loose:
        return points, records, faces, pins, 0
    keep = [v for v in range(len(points)) if find(v) in held]
    index = {old: new for new, old in enumerate(keep)}
    return ([points[v] for v in keep], [records[v] for v in keep],
            [tuple(index[v] for v in face) for face in faces if face[0] in index],
            {index[p] for p in pins}, len(loose))


def painted_guide_source(data, samples: ClothPaintSamples, *, max_sample_distance, lod):
    """Welded painted faces at one stored LOD, with pins and one source record per guide.

    Returns (points, records, faces, pins, painted part names). A guide is pinned
    when its position is on the painted area's attachment line (a face of any
    covered part joins it to an unpainted vertex) or it lies nearest a sample
    painted as a pin.
    """
    level = pac_cloth_lods(data)[lod]
    pinned_samples = samples.pins or ()
    # The line is gathered across every part first: a seam's records belong to
    # different parts, and the face that crosses it may be in the other part.
    prepared, anchor_positions = [], set()
    for index, part in enumerate(level.submeshes):
        if not part.vertices or not part.faces:
            continue
        values, distances = _nearest_values(part.vertices, samples, max_sample_distance)
        if all(distance > max_sample_distance for distance in distances):
            continue  # a template part the import does not cover
        painted = [blend_for_paint(value) < 63 and distance <= max_sample_distance
                   for value, distance in zip(values, distances)]
        keys = [tuple(float(x) for x in vertex) for vertex in part.vertices]
        if not any(painted):
            continue
        pin_hits = [False] * len(part.vertices)
        if pinned_samples:
            pin_values, _ = _nearest_values(part.vertices, ClothPaintSamples(
                samples.positions, tuple(1.0 if p else 0.0 for p in pinned_samples)), max_sample_distance)
            pin_hits = [value > 0.5 for value in pin_values]
        anchor_positions.update(keys[v] for face in part.faces
                                if not all(painted[i] for i in face) for v in face if painted[v])
        prepared.append((index, part, keys, painted, pin_hits))
    points, records, faces, pins, names = [], [], [], set(), {}
    weld: dict[tuple[float, float, float], int] = {}
    seen = set()
    for index, part, keys, painted, pin_hits in prepared:
        for face in part.faces:
            if not all(painted[i] for i in face):
                continue
            face_keys = [keys[vertex] for vertex in face]
            if len(set(face_keys)) != 3:
                continue  # welding collapses a sliver; its vertices become guides only through other faces
            identity = tuple(sorted(face_keys))
            if identity in seen:
                continue  # the other side of a double-sided shell
            seen.add(identity)
            row = []
            for vertex, key in zip(face, face_keys):
                if key not in weld:
                    weld[key] = len(points)
                    points.append(key)
                    records.append(part.source_vertex_offsets[vertex])
                guide = weld[key]
                if pin_hits[vertex] or key in anchor_positions:
                    pins.add(guide)
                row.append(guide)
            faces.append(tuple(row))
            names.setdefault(part.name or str(index), None)
    return points, records, faces, pins, tuple(names)


def create_painted_cloth_guides(
    data: bytes,
    samples: ClothPaintSamples,
    *,
    max_sample_distance: float,
    check_cancelled=lambda: None,
) -> tuple[bytes, PaintedGuideReport]:
    if not math.isfinite(max_sample_distance) or max_sample_distance <= 0:
        raise ValueError("Cloth paint needs a positive sample tolerance.")
    if not any(v > 0 for v in samples.values):
        raise ValueError("Paint at least one area as cloth.")
    stripped, removed = remove_pac_cloth_guides(data)
    metadata, insertion, palette, levels = guide_creation_layout(stripped)
    check_cancelled()
    candidates, reasons = [], []
    for lod in range(len(levels)):
        points, records, faces, pins, names = painted_guide_source(
            stripped, samples, max_sample_distance=max_sample_distance, lod=lod)
        if not faces:
            reasons.append(f"LOD {lod}: no painted faces")
            continue
        points, records, faces, pins, riding = held_guide_pieces(points, records, faces, pins)
        problem = manifold_problem(faces)
        if problem:
            reasons.append(f"LOD {lod}: {problem}")
            continue
        candidates.append((lod, points, records, faces, pins, names, riding))
        if len(points) <= GUIDE_LIMIT:
            break
    if not candidates:
        raise ValueError("The painted area cannot become a cloth guide mesh ("
                         + "; ".join(reasons) + "). Paint whole faces of a single-layer surface.")
    fitting = [row for row in candidates if len(row[1]) <= GUIDE_LIMIT]
    lod, points, records, faces, pins, names, riding = (
        fitting[0] if fitting else min(candidates, key=lambda row: len(row[1])))
    source_vertices = len(points)
    reduced = source_vertices > GUIDE_LIMIT
    if reduced:
        order, faces, pins = reduce_guide_mesh(points, faces, pins, check_cancelled=check_cancelled)
        points, records = [points[i] for i in order], [records[i] for i in order]
    if len(points) < 3 or not faces:
        raise ValueError("The painted area is too small for cloth. Paint at least one whole face.")
    if not pins:
        raise ValueError("Nothing holds the painted cloth. Leave the area it hangs from unpainted, "
                         "or paint pins where it attaches.")
    if len(pins) == len(points):
        raise ValueError("Every cloth guide is pinned, so nothing would move. Paint a larger area or fewer pins.")
    skins = [_skin(stripped, offset, len(palette), True) for offset in records]
    check_cancelled()
    block, _decoded = _guide_block(points, skins, faces, pins)
    result = bytearray(stripped[:insertion] + block + stripped[insertion:])
    start = metadata["offset"]
    flags, = struct.unpack_from("<I", stripped, start)
    struct.pack_into("<I", result, start, (flags & ~0x8F00) | 0x300)
    stored, total = struct.unpack_from("<2I", stripped, 16)
    struct.pack_into("<2I", result, 16, stored and total + len(block), total + len(block))
    for i in range(2 * len(levels)):
        offset = start + 5 + 4 * i
        struct.pack_into("<I", result, offset, struct.unpack_from("<I", stripped, offset)[0] + len(block))
    result = bytes(result)
    guides = decode_pac_cloth_guides(result)
    if guides is None or len(guides.vertices) != len(points) or not all(
            value for value in inspect_guide_topology(guides).values() if type(value) is bool):
        raise ValueError("The new cloth guides did not pass independent decoding.")
    if decode_pac_embedded_volumes(result).bone_palette != palette:
        raise ValueError("Cloth guide creation changed the retained bone palette.")
    check_cancelled()
    output, bind = apply_pac_cloth_paint(result, {}, default=samples, max_sample_distance=max_sample_distance)
    return output, PaintedGuideReport(
        guide_count=len(points), pinned_guides=len(pins), source_lod=lod, source_vertices=source_vertices,
        reduced=reduced, cloth_vertices=bind.cloth_vertices, rigid_vertices=bind.rigid_vertices,
        reduced_skin_vertices=bind.reduced_vertices, cloth_parts=bind.cloth_parts or names,
        removed_template_guides=removed, riding_pieces=riding)
