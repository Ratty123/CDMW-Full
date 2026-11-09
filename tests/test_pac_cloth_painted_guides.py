"""Own cloth guides from paint: template removal, pins, reduction and binding."""

import struct

import pytest

from cdmw.modding.pac_cloth import decode_pac_cloth_binding, pac_cloth_lods
from cdmw.modding.pac_cloth_guide_builder import create_pac_cloth_guides, guide_creation_layout
from cdmw.modding.pac_cloth_guides import decode_pac_cloth_guides, inspect_guide_topology
from cdmw.modding.pac_cloth_paint import ClothPaintSamples
from cdmw.modding.pac_cloth_painted_guides import (
    GUIDE_LIMIT, create_painted_cloth_guides, manifold_problem, reduce_guide_mesh, remove_pac_cloth_guides,
)
from tests.test_pac_cloth_guide_builder import PALETTE, guide_free_pac, rule

TOLERANCE = 1e-3


def grid(n):
    points = [(i / (n - 1), j / (n - 1), 0.) for j in range(n) for i in range(n)]
    faces = []
    for j in range(n - 1):
        for i in range(n - 1):
            a, b, c, d = j * n + i, j * n + i + 1, (j + 1) * n + i, (j + 1) * n + i + 1
            faces += [(a, b, c), (b, d, c)]
    return points, faces


def grid_pac(sizes=(13, 7, 5), *, double_sided=False):
    """One part whose LOD n is an n x n grid on the unit square, y up.

    Every lower LOD's points are LOD0 points, as in a built import."""
    lods = len(sizes)
    metadata = bytearray(struct.pack("<IB", 0, lods) + bytes(8 * lods) + struct.pack("<H", 1))
    name = b"skirt"
    metadata += bytes((len(name),)) + name + bytes((len(name),)) + name
    descriptor = bytearray(40 + 6 * lods)
    descriptor[0] = 1
    struct.pack_into("<8f", descriptor, 3, 0, 0, 0, 0, 0, 1, 1, 0)
    descriptor[35:36 + lods] = bytes((lods, *range(lods)))
    geometry, indices = [], []
    for lod, n in enumerate(sizes):
        points, faces = grid(n)
        if double_sided:
            faces = faces + [(a, c, b) for a, b, c in faces]
        struct.pack_into("<H", descriptor, 40 + 2 * lod, len(points))
        struct.pack_into("<I", descriptor, 40 + 2 * lods + 4 * lod, 3 * len(faces))
        vertex_bytes = bytearray()
        for x, y, _ in points:
            record = bytearray(40)
            struct.pack_into("<3H", record, 0, round(x * 32767), round(y * 32767), 0)
            record[6:20] = bytes.fromhex("1234003400380000003c00000040")
            struct.pack_into("<2I", record, 20, 1 << 10 | 0xc0000000, 0x80000000)
            record[28:32] = bytes((128, 127, 0, 0))
            record[36:40] = bytes((52, 73, 255, 0xff))
            vertex_bytes += record
        geometry.append(vertex_bytes)
        indices.append(struct.pack(f"<{3 * len(faces)}H", *(i for f in faces for i in f)))
    metadata += descriptor
    metadata += struct.pack("<H8I6f", 8, *PALETTE, 0, 0, 0, 1, 1, 0)
    metadata += struct.pack("<H", 0) + bytes(13)
    header = bytearray(80)
    header[:8] = b"PAR \x03\x09\0\x01"
    cursor, payloads = 80 + len(metadata), []
    for lod in reversed(range(lods)):
        struct.pack_into("<I", metadata, 5 + 4 * lod, cursor)
        struct.pack_into("<I", metadata, 5 + 4 * lods + 4 * lod, cursor + len(geometry[lod]))
        payloads.append(bytes(geometry[lod] + indices[lod]))
        cursor += len(payloads[-1])
    for slot, payload in enumerate((metadata, *payloads)):
        struct.pack_into("<2I", header, 16 + 8 * slot, 0, len(payload))
    return bytes(header + metadata) + b"".join(payloads)


def paint_below(data, height, *, value=1.0, pins=None):
    """Samples from LOD0: painted below ``height``; optional pin predicate."""
    part = pac_cloth_lods(data)[0].submeshes[0]
    positions = tuple(tuple(v) for v in part.vertices)
    values = tuple(value if p[1] < height else 0.0 for p in positions)
    return ClothPaintSamples(positions, values, None if pins is None else tuple(bool(pins(p)) for p in positions))


def test_removal_drops_the_block_and_bindings_and_admits_new_guides():
    source = guide_free_pac(lods=3, parts=2)
    with_guides = create_pac_cloth_guides(source, {0: rule()})
    stripped, count = remove_pac_cloth_guides(with_guides)
    assert count == 4 and decode_pac_cloth_guides(stripped) is None
    assert len(stripped) == len(source)
    guide_creation_layout(stripped)  # no guides, no bindings, decoded trailer
    for old, new in zip(pac_cloth_lods(source), pac_cloth_lods(stripped)):
        for a, b in zip(old.submeshes, new.submeshes):
            assert a.vertices == b.vertices and a.faces == b.faces
            assert a.bone_indices == b.bone_indices and a.bone_weights == b.bone_weights
            for offset in b.source_vertex_offsets:
                assert decode_pac_cloth_binding(stripped, offset) is None
    assert remove_pac_cloth_guides(source) == (source, 0)


def test_paint_builds_guides_from_painted_faces_pinned_on_the_attachment_line():
    data = grid_pac()
    samples = paint_below(data, .55)
    result, report = create_painted_cloth_guides(data, samples, max_sample_distance=TOLERANCE)
    guides = decode_pac_cloth_guides(result)
    assert report.source_lod == 0 and not report.reduced and report.guide_count == len(guides.vertices)
    assert all(v for v in inspect_guide_topology(guides).values() if type(v) is bool)
    fixed = [guides.vertices[i] for i, b in enumerate(guides.channel_b) if b == 255]
    moving = [guides.vertices[i] for i, b in enumerate(guides.channel_b) if b != 255]
    assert fixed and moving and report.pinned_guides == len(fixed)
    # LOD0 rows sit at y = k/12: the last painted row (6/12) touches the first unpainted one.
    assert {round(p[1], 3) for p in fixed} == {0.5}
    assert all(p[1] < .55 for p in guides.vertices)
    for level in pac_cloth_lods(result):
        for vertex, offset in zip(level.submeshes[0].vertices, level.submeshes[0].source_vertex_offsets):
            binding = decode_pac_cloth_binding(result, offset)
            nearest = min(samples.positions, key=lambda p: sum((a - b) ** 2 for a, b in zip(p, vertex)))
            if samples.values[samples.positions.index(nearest)] > 0:
                assert binding is not None and binding[0] == 0 and sum(binding[2]) == 255
                assert max(binding[1]) < len(guides.vertices)
            else:
                assert binding is None


def test_template_guides_are_replaced_not_kept():
    template = create_pac_cloth_guides(grid_pac(), {0: rule(height=.9)})
    old = decode_pac_cloth_guides(template)
    result, report = create_painted_cloth_guides(template, paint_below(template, .55), max_sample_distance=TOLERANCE)
    assert report.removed_template_guides == len(old.vertices)
    assert decode_pac_cloth_guides(result).vertices != old.vertices
    assert all(p[1] < .55 for p in decode_pac_cloth_guides(result).vertices)


def test_painted_pins_hold_a_fully_painted_part():
    data = grid_pac()
    with pytest.raises(ValueError, match="Nothing holds the painted cloth"):
        create_painted_cloth_guides(data, paint_below(data, 2.0), max_sample_distance=TOLERANCE)
    samples = paint_below(data, 2.0, pins=lambda p: p[1] > .99)
    result, report = create_painted_cloth_guides(data, samples, max_sample_distance=TOLERANCE)
    guides = decode_pac_cloth_guides(result)
    assert {round(guides.vertices[i][1], 3) for i, b in enumerate(guides.channel_b) if b == 255} == {1.0}


def test_paint_blend_and_double_sided_shells():
    data = grid_pac(double_sided=True)
    result, report = create_painted_cloth_guides(data, paint_below(data, .55, value=.5), max_sample_distance=TOLERANCE)
    guides = decode_pac_cloth_guides(result)
    assert len(guides.triangles) == len({tuple(sorted(t)) for t in guides.triangles})
    painted = [decode_pac_cloth_binding(result, o) for o in pac_cloth_lods(result)[0].submeshes[0].source_vertex_offsets]
    assert {b[0] for b in painted if b is not None} == {32}


def test_lowest_detail_lod_that_fits_is_chosen_then_reduction():
    data = grid_pac((41, 21, 11))
    # 33 painted LOD0 rows of 41 exceed the limit; LOD1 fits.
    _, report = create_painted_cloth_guides(data, paint_below(data, .8), max_sample_distance=2e-2)
    assert report.source_lod == 1 and not report.reduced and report.guide_count <= GUIDE_LIMIT
    big = grid_pac((65, 33))
    result, report = create_painted_cloth_guides(big, paint_below(big, .99), max_sample_distance=2e-2)
    assert report.reduced and report.source_vertices > GUIDE_LIMIT and report.guide_count <= 1000
    guides = decode_pac_cloth_guides(result)
    assert all(v for v in inspect_guide_topology(guides).values() if type(v) is bool)
    assert not manifold_problem(guides.triangles)


def test_reduction_keeps_pins_borders_and_orientation():
    points, faces = grid(20)
    points = [(x, y, 0.) for x, y, _ in points]
    pins = {i for i, p in enumerate(points) if p[1] == 1.0}
    order, reduced, kept_pins = reduce_guide_mesh(points, faces, pins, target=120)
    assert len(order) <= 120 and not manifold_problem(reduced)
    # A pin may merge into a neighbouring pin, never into a moving guide.
    kept = {order[i] for i in kept_pins}
    assert kept and kept <= pins and kept == pins & set(order)
    border = {i for i, p in enumerate(points) if p[0] in (0., 1.) or p[1] in (0., 1.)}
    corners = {0, 19, 380, 399}
    assert corners <= set(order) and set(order) & border
    for a, b, c in reduced:
        pa, pb, pc = points[order[a]], points[order[b]], points[order[c]]
        cross = (pb[0] - pa[0]) * (pc[1] - pa[1]) - (pb[1] - pa[1]) * (pc[0] - pa[0])
        assert cross > 0  # every face keeps the source winding
    with pytest.raises(ValueError, match="could not be reduced"):
        reduce_guide_mesh(points, faces, set(), target=3)  # four corners must stay


@pytest.mark.parametrize("problem, message", [
    ("misaligned", "does not line up|no painted faces"),
    ("nothing", "Paint at least one area"),
])
def test_refusals_name_the_reason(problem, message):
    data = grid_pac()
    samples = paint_below(data, .55)
    if problem == "misaligned":
        samples = ClothPaintSamples(tuple((x + 5, y, z) for x, y, z in samples.positions), samples.values)
    else:
        samples = ClothPaintSamples(samples.positions, (0.0,) * len(samples.values))
    with pytest.raises(ValueError, match=message):
        create_painted_cloth_guides(data, samples, max_sample_distance=TOLERANCE)


def test_two_islands_each_hang_from_their_own_attachment_line():
    data = grid_pac()
    part = pac_cloth_lods(data)[0].submeshes[0]
    positions = tuple(tuple(v) for v in part.vertices)
    # An unpainted band splits the paint into two islands; each touches the band.
    values = tuple(0.0 if .4 < p[1] < .6 else 1.0 for p in positions)
    result, report = create_painted_cloth_guides(data, ClothPaintSamples(positions, values), max_sample_distance=TOLERANCE)
    guides = decode_pac_cloth_guides(result)
    fixed_rows = {round(guides.vertices[i][1], 3) for i, b in enumerate(guides.channel_b) if b == 255}
    assert fixed_rows == {round(4 / 12, 3), round(8 / 12, 3)}
    with pytest.raises(ValueError, match="one true/false flag"):
        ClothPaintSamples(positions, values, (True,) * (len(positions) - 1))


def test_a_piece_without_any_pin_is_reported():
    from cdmw.modding.pac_cloth_painted_guides import _components_without_pins
    faces = [(0, 1, 2), (3, 4, 5)]
    assert len(_components_without_pins(faces, 6, {0})) == 1
    assert _components_without_pins(faces, 6, {0, 4}) == []
