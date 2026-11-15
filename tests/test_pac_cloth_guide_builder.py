"""Owned guide-free PACs: new geometry, all-LOD binding and relocation proof."""

import struct

import pytest

from cdmw.domain.mesh.cloth_guides import PacClothGuideRule
from cdmw.modding.mesh_parser import _decode_pac_skin_influences, _parse_par_sections
from cdmw.modding.pabv_parser import decode_pac_embedded_volumes
from cdmw.modding.pac_cloth import decode_pac_cloth_binding, pac_cloth_lods
from cdmw.modding.pac_cloth_guide_builder import (
    SkippedGuideTriangles, create_pac_cloth_guides, create_pac_cloth_guides_with_report,
    drop_flat_stored_triangles, guide_creation_layout)
from cdmw.modding.pac_cloth_guides import decode_pac_cloth_guides, inspect_guide_topology


PALETTE = tuple(0xaabbcd00+i for i in range(8))
POINTS = ((0., 0., 0.), (1., 0., 0.), (0., 1., 0.), (1., 1., 0.))
FACES = ((0, 1, 2), (1, 3, 2))


def guide_free_pac(*, lods=4, parts=1, extra=b"", flags=0, empty_last=False, palette=PALETTE, shapes=None):
    """``shapes`` maps a part index to its own (points, faces), at every LOD; points lie in [0, 1]."""
    metadata = bytearray(struct.pack("<IB", flags, lods) + bytes(8*lods) + struct.pack("<H", parts))
    geometry = [bytearray() for _ in range(lods)]
    indices = [bytearray() for _ in range(lods)]
    for part in range(parts):
        points, faces = (shapes or {}).get(part, (POINTS, FACES))
        name = f"guide{part}".encode()
        metadata += bytes((len(name),)) + name + bytes((len(name),)) + name
        descriptor = bytearray(40 + 6*lods)
        descriptor[0] = 1
        struct.pack_into("<8f", descriptor, 3, 0, 0, part*3, 0, 0, 1, 1, 0)
        descriptor[35:36+lods] = bytes((lods, *range(lods)))
        for lod in range(lods):
            empty = empty_last and part == 0 and lod == lods-1
            struct.pack_into("<H", descriptor, 40+2*lod, 0 if empty else len(points))
            struct.pack_into("<I", descriptor, 40+2*lods+4*lod, 0 if empty else 3*len(faces))
            if empty:
                continue
            for x, y, z in points:
                record = bytearray(40)
                struct.pack_into("<3H", record, 0, round(x*32767), round(y*32767), 0)
                record[6:20] = bytes.fromhex("1234003400380000003c00000040")
                struct.pack_into("<2I", record, 20, 1 << 10 | 0xc0000000, 0x80000000)
                record[28:32] = bytes((128, 127, 0, 0))
                record[36:40] = bytes((52, 73, 255, 0xff))
                geometry[lod] += record
            indices[lod] += struct.pack(f"<{3*len(faces)}H", *(i for f in faces for i in f))
        metadata += descriptor
    if flags & 0x2000:
        metadata += struct.pack("<6fHH", *([0.]*6), 0, 0)
    metadata += struct.pack(f"<H{len(palette)}I6f", len(palette), *palette, 0, 0, 0, 4, 1, 0)
    if flags & 4:
        metadata += struct.pack("<6f", 0, 0, 0, 4, 1, 0)
    metadata += struct.pack("<H", 0)  # empty model collision table
    metadata += bytes(13) + extra  # empty, sequential metadata trailer
    header = bytearray(80)
    header[:8] = b"PAR \x03\x09\0\x01"
    cursor = 80 + len(metadata)
    payloads = []
    for lod in reversed(range(lods)):
        struct.pack_into("<I", metadata, 5+4*lod, cursor)
        struct.pack_into("<I", metadata, 5+4*lods+4*lod, cursor+len(geometry[lod]))
        payload = bytes(geometry[lod] + indices[lod])
        payloads.append(payload)
        cursor += len(payload)
    for slot, payload in enumerate((metadata, *payloads)):
        struct.pack_into("<2I", header, 16+8*slot, 0, len(payload))
    return bytes(header + metadata) + b"".join(payloads)


def rule(lod=0, height=.5):
    return PacClothGuideRule(lod, height, PALETTE)


@pytest.mark.parametrize("lods", [2, 3, 4])
@pytest.mark.parametrize("flags", [0, 0x2004, 0x8000])
def test_new_guides_preserve_geometry_metadata_and_skeletal_deformation_at_all_lods(lods, flags):
    source = guide_free_pac(lods=lods, parts=2, flags=flags)
    metadata, insertion, palette, before = guide_creation_layout(source)
    result = create_pac_cloth_guides(source, {0: rule()})
    guides = decode_pac_cloth_guides(result)
    assert guides.vertices == POINTS and guides.triangles == FACES
    assert guides.channel_b == bytes((0, 0, 255, 255))
    assert guides.bone_indices == ((0, 1, 0, 0),) * 4
    assert guides.bone_weight_bytes == ((128, 127, 0, 0),) * 4
    assert guides.metadata_flags == (flags & ~0x8000) | 0x300
    assert all(v for v in inspect_guide_topology(guides).values() if type(v) is bool)
    delta = len(result)-len(source)
    assert result[insertion+delta:metadata["offset"]+metadata["size"]+delta] == source[insertion:metadata["offset"]+metadata["size"]]
    assert decode_pac_embedded_volumes(result).bone_palette == palette
    after = pac_cloth_lods(result)
    for old, new in zip(before, after, strict=True):
        for part_index, (a, b) in enumerate(zip(old.submeshes, new.submeshes, strict=True)):
            assert a.vertices == b.vertices and a.faces == b.faces and a.uvs == b.uvs and a.normals == b.normals
            for i, (oa, ob) in enumerate(zip(a.source_vertex_offsets, b.source_vertex_offsets, strict=True)):
                assert ob == oa + delta
                rowa, rowb = source[oa:oa+40], result[ob:ob+40]
                assert _decode_pac_skin_influences(source, oa) == _decode_pac_skin_influences(result, ob)
                if part_index:
                    assert rowa == rowb
                else:
                    assert rowa[:12] == rowb[:12] and rowa[16:20] == rowb[16:20] and rowa[36:39] == rowb[36:39]
                    assert rowa[39] & 0xc0 == rowb[39] & 0xc0
                    blend, ids, weights = decode_pac_cloth_binding(result, ob)
                    assert blend == 0 and sum(weights) == 255 and max(ids) < 4
                    assert ids[0] == i and weights[0] == 255
    assert create_pac_cloth_guides(source, {0: rule()}) == result


# A seam: vertex 4 sits on vertex 1 with the same skin, so welding makes them one guide.
SEAM = (POINTS + ((1., 0., 0.),), FACES + ((1, 4, 3),))
STEP = 1 / 32767


def test_a_triangle_that_welding_collapses_is_skipped_and_reported():
    source = guide_free_pac(lods=3, shapes={0: SEAM})
    result, report = create_pac_cloth_guides_with_report(source, {0: rule()})
    guides = decode_pac_cloth_guides(result)
    # Only the kept triangles make guides; the render mesh keeps its five vertices and three faces.
    assert guides.vertices == POINTS and guides.triangles == FACES
    assert report.guide_count == 4
    assert report.skipped == (SkippedGuideTriangles("guide0", 0, collapsed=1, flat=0),)
    assert all(v for v in inspect_guide_topology(guides).values() if type(v) is bool)
    assert [list(p.faces) for p in pac_cloth_lods(result)[0].submeshes] == [list(SEAM[1])]
    assert create_pac_cloth_guides(source, {0: rule()}) == result


def test_a_triangle_flat_only_once_stored_is_dropped_with_its_unused_guides():
    # Part 1 sits at x = 3 to 4, so the guides are stored across x = 0 to 4: four source
    # steps become one, and this sliver's two x values round to the same stored value.
    thin = ((16000 * STEP, .2, 0.), (16001 * STEP, .5, 0.), (16000 * STEP, .8, 0.))
    part0 = (POINTS + thin, FACES + ((4, 5, 6),))
    source = guide_free_pac(lods=2, parts=2, shapes={0: part0})
    result, report = create_pac_cloth_guides_with_report(source, {0: rule(), 1: rule()})
    assert report.skipped == (SkippedGuideTriangles("guide0", 0, collapsed=0, flat=1),)
    guides = decode_pac_cloth_guides(result)
    assert len(guides.vertices) == 8 and len(guides.triangles) == 4
    assert all(v for v in inspect_guide_topology(guides).values() if type(v) is bool)
    # Every render vertex of part 0 still binds to a guide of its own part.
    for offset in pac_cloth_lods(result)[0].submeshes[0].source_vertex_offsets:
        _, ids, weights = decode_pac_cloth_binding(result, offset)
        assert max(ids) < 4 and sum(weights) == 255


def test_dropping_flat_triangles_repeats_until_none_is_left_and_ends():
    points = [(0., 0., 0.), (1., 0., 0.), (0., 1., 0.), (2., 2., 0.), (2. + 1e-9, 2.5, 0.), (2., 3., 0.)]
    used, faces, dropped = drop_flat_stored_triangles(points, [(0, 1, 2), (3, 4, 5)])
    assert dropped == [1] and used == [0, 1, 2] and faces == [(0, 1, 2)]
    # Stored alone, the same sliver has bounds of its own and keeps its area.
    assert drop_flat_stored_triangles(points, [(3, 4, 5)]) == ([3, 4, 5], [(0, 1, 2)], [])


def test_a_part_left_with_no_triangle_refuses_and_names_itself():
    points = ((0., 0., 0.), (1., 0., 0.), (1., 0., 0.), (0., 1., 0.))
    source = guide_free_pac(lods=2, parts=2, shapes={1: (points, ((0, 1, 2),))})
    with pytest.raises(ValueError, match=r"^guide1, LOD 0: all 1 triangles collapse"):
        create_pac_cloth_guides(source, {0: rule(), 1: rule()})


def test_a_piece_cut_off_by_a_skipped_triangle_names_its_part():
    # A held top piece and an unheld bottom piece, joined only by a sliver that welding collapses.
    points = ((0., .6, 0.), (1., .6, 0.), (0., 1., 0.), (0., 0., 0.), (1., 0., 0.), (0., .3, 0.), (0., 1., 0.))
    faces = ((0, 1, 2), (3, 4, 5), (2, 6, 3))
    source = guide_free_pac(lods=2, shapes={0: (points, faces)})
    with pytest.raises(ValueError, match=r"needs a fixed guide \(1 on guide0, LOD 0 without one\)"):
        create_pac_cloth_guides(source, {0: rule()})


def test_the_mesh_editor_shows_what_the_last_build_of_this_state_skipped():
    from types import SimpleNamespace

    from cdmw.modding.pac_cloth_guide_builder import GuideBuildReport
    from cdmw.services.mesh_rust_cloth_guides import _guide_output_key, _skipped_triangles

    session = SimpleNamespace(revision=3, material_generation=1, original_data=b"pac", replacement_state=None)
    report = GuideBuildReport(4, (SkippedGuideTriangles("Cloak", 1, collapsed=3, flat=0),))
    authoring = SimpleNamespace(cloth_guide_output_cache=(_guide_output_key(session), b"out", (), report))
    assert _skipped_triangles(authoring, session) == [{"part": "Cloak", "lod": 1, "collapsed": 3, "flat": 0}]
    # A cached build of another revision says nothing about this one.
    session.revision = 4
    assert _skipped_triangles(authoring, session) == []
