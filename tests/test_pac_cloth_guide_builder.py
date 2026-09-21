"""Owned guide-free PACs: new geometry, all-LOD binding and relocation proof."""

import struct

import pytest

from cdmw.domain.mesh.cloth_guides import PacClothGuideRule
from cdmw.modding.mesh_parser import _decode_pac_skin_influences, _parse_par_sections
from cdmw.modding.pabv_parser import decode_pac_embedded_volumes
from cdmw.modding.pac_cloth import decode_pac_cloth_binding, pac_cloth_lods
from cdmw.modding.pac_cloth_guide_builder import create_pac_cloth_guides, guide_creation_layout
from cdmw.modding.pac_cloth_guides import decode_pac_cloth_guides, inspect_guide_topology


PALETTE = tuple(0xaabbcd00+i for i in range(8))
POINTS = ((0., 0., 0.), (1., 0., 0.), (0., 1., 0.), (1., 1., 0.))
FACES = ((0, 1, 2), (1, 3, 2))


def guide_free_pac(*, lods=4, parts=1, extra=b"", flags=0, empty_last=False):
    metadata = bytearray(struct.pack("<IB", flags, lods) + bytes(8*lods) + struct.pack("<H", parts))
    geometry = [bytearray() for _ in range(lods)]
    indices = [bytearray() for _ in range(lods)]
    for part in range(parts):
        name = f"guide{part}".encode()
        metadata += bytes((len(name),)) + name + bytes((len(name),)) + name
        descriptor = bytearray(40 + 6*lods)
        descriptor[0] = 1
        struct.pack_into("<8f", descriptor, 3, 0, 0, part*3, 0, 0, 1, 1, 0)
        descriptor[35:36+lods] = bytes((lods, *range(lods)))
        for lod in range(lods):
            empty = empty_last and part == 0 and lod == lods-1
            struct.pack_into("<H", descriptor, 40+2*lod, 0 if empty else 4)
            struct.pack_into("<I", descriptor, 40+2*lods+4*lod, 0 if empty else 6)
            if empty:
                continue
            for x, y, z in POINTS:
                record = bytearray(40)
                struct.pack_into("<3H", record, 0, round(x*32767), round(y*32767), 0)
                record[6:20] = bytes.fromhex("1234003400380000003c00000040")
                struct.pack_into("<2I", record, 20, 1 << 10 | 0xc0000000, 0x80000000)
                record[28:32] = bytes((128, 127, 0, 0))
                record[36:40] = bytes((52, 73, 255, 0xff))
                geometry[lod] += record
            indices[lod] += struct.pack("<6H", *(i for f in FACES for i in f))
        metadata += descriptor
    if flags & 0x2000:
        metadata += struct.pack("<6fHH", *([0.]*6), 0, 0)
    metadata += struct.pack("<H8I6f", 8, *PALETTE, 0, 0, 0, 4, 1, 0)
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


def test_parts_are_bound_to_their_own_guides_and_empty_lod_parts_keep_identity():
    source = guide_free_pac(parts=2, empty_last=True)
    result = create_pac_cloth_guides(source, {0: rule(), 1: rule()})
    assert len(decode_pac_cloth_guides(result).vertices) == 8
    levels = pac_cloth_lods(result)
    assert not levels[-1].submeshes[0].vertices
    for level in levels:
        for index, part in enumerate(level.submeshes):
            for offset in part.source_vertex_offsets:
                assert all(index*4 <= i < (index+1)*4 for i in decode_pac_cloth_binding(result, offset)[1])


@pytest.mark.parametrize("fault", ["opaque", "bones", "palette", "offset", "compressed", "binding", "six_bones", "weight_total", "pins", "all_fixed", "missing_lod"])
def test_unsupported_sources_and_rules_fail_without_changing_input(fault):
    source = bytearray(guide_free_pac(extra=b"opaque" if fault == "opaque" else b""))
    selected = rule()
    offset = pac_cloth_lods(source)[0].submeshes[0].source_vertex_offsets[0]
    if fault == "bones":
        struct.pack_into("<I", source, 80, 0x20)
    elif fault == "palette":
        selected = PacClothGuideRule(0, .5, tuple(reversed(PALETTE)))
    elif fault == "offset":
        struct.pack_into("<I", source, 85, 123)
    elif fault == "compressed":
        struct.pack_into("<I", source, 16, 2)
    elif fault == "binding":
        source[offset+39] = 0
    elif fault == "six_bones":
        source[offset+28:offset+34] = bytes((50, 50, 50, 50, 30, 25))
    elif fault == "weight_total":
        source[offset+28] = 0
    elif fault == "pins":
        selected = rule(height=2)
    elif fault == "all_fixed":
        selected = rule(height=-1)
    elif fault == "missing_lod":
        source = bytearray(guide_free_pac(lods=2))
        selected = rule(lod=3)
    before = bytes(source)
    with pytest.raises(ValueError):
        create_pac_cloth_guides(source, {0: selected})
    assert bytes(source) == before


def test_generated_guide_translation_and_existing_bone_pose_reach_render_vertices():
    from cdmw.modding.pac_cloth_preview import build_cloth_preview_snapshot
    from cdmw.modding.pac_cloth_skinning import blend_render_cloth_matrix, prepare_guide_skinning_matrices
    source = guide_free_pac()
    result = create_pac_cloth_guides(source, {0: rule()})
    guides = decode_pac_cloth_guides(result)
    identity = [[float(i == j) for j in range(4)] for i in range(4)]
    palette = tuple(reversed(range(8)))
    poses = [[row[:] for row in identity] for _ in palette]
    poses[palette[1]][3][1] = .5
    posed = build_cloth_preview_snapshot(result, dict(bone_palette=palette, inverse_bind_matrices=[identity]*8, neutral_global_matrices=poses))
    for point, frame in zip(POINTS, posed["animation_frames"], strict=True):
        assert frame[3][1] == pytest.approx(point[1] + .5*127/255)
    preview = build_cloth_preview_snapshot(result, dict(bone_palette=palette, inverse_bind_matrices=[identity]*8, neutral_global_matrices=[identity]*8))
    preview["animation_frames"][0][3][0] += .25
    matrices = prepare_guide_skinning_matrices(guides, preview["animation_frames"])
    for level in pac_cloth_lods(result):
        part = level.submeshes[0]
        for vertex, offset in enumerate(part.source_vertex_offsets):
            matrix = blend_render_cloth_matrix(result, offset, skeletal_matrix=identity, guide_matrices=matrices)
            moved = tuple(sum((*part.vertices[vertex], 1)[k]*matrix[k][j] for k in range(4)) for j in range(3))
            assert moved == pytest.approx((part.vertices[vertex][0] + (.25 if vertex == 0 else 0), part.vertices[vertex][1], 0))


def test_six_influences_are_reduced_only_after_explicit_opt_in():
    data = bytearray(guide_free_pac(parts=2))
    for level in pac_cloth_lods(data):
        for offset in level.submeshes[0].source_vertex_offsets:
            struct.pack_into("<2I", data, offset+20, 0 | 1 << 10 | 2 << 20, 3 | 4 << 10 | 5 << 20)
            data[offset+28:offset+34] = bytes((100, 70, 40, 20, 15, 10))
    source = bytes(data)
    with pytest.raises(ValueError, match="Enable Reduce"):
        create_pac_cloth_guides(source, {0: rule()})
    result = create_pac_cloth_guides(source, {0: PacClothGuideRule(0, .5, PALETTE, True)})
    guides = decode_pac_cloth_guides(result)
    assert guides.bone_indices == ((0, 1, 2, 3),)*4
    assert guides.bone_weight_bytes == ((111, 78, 44, 22),)*4
    for before, after in zip(pac_cloth_lods(source), pac_cloth_lods(result), strict=True):
        for offset in after.submeshes[0].source_vertex_offsets:
            assert result[offset+28:offset+32] == bytes((111, 78, 44, 22))
        for old, new in zip(before.submeshes[1].source_vertex_offsets, after.submeshes[1].source_vertex_offsets, strict=True):
            assert source[old:old+40] == result[new:new+40]


def test_pin_height_uses_neutral_coordinates_but_guides_keep_source_frame():
    from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance
    matrix = (1., 0., 0., 0., 0., 2., 0., 0., 0., 0., 1., 0., 0., 10., 0., 1.)
    appearance = NeutralMeshAppearance("owned", tuple(range(8)), (matrix,)*8)
    source = guide_free_pac()
    out = create_pac_cloth_guides(source, {0: rule(height=11)}, appearance=appearance)
    guides = decode_pac_cloth_guides(out)
    assert guides.vertices == POINTS and guides.channel_b == bytes((0, 0, 255, 255))


def test_metadata_tail_framing_is_relative_and_preserved_including_opaque_blob():
    # Sequential groups, auxiliary points, self-contained blob, optional arrays,
    # post-blob groups and final twelve-byte records from the traced loader.
    tail = bytes((1, 2)) + b"G"*32 + struct.pack("<I", 2) + b"P"*24
    tail += struct.pack("<I", 12) + b"opaque-block"
    tail += bytes((1,)) + struct.pack("<2I", 1, 7) + struct.pack("<3I", 2, 3, 8)
    tail += struct.pack("<2H", 1, 2) + b"V"*32 + bytes((2,)) + b"F"*24
    source = guide_free_pac(flags=0x02000000)
    model = decode_pac_embedded_volumes(source)
    end = 80 + _parse_par_sections(source)[0]["size"]
    delta = len(tail)-(end-model.file_end)
    data = bytearray(source[:model.file_end] + tail + source[end:])
    struct.pack_into("<I", data, 20, end-80+delta)
    for i in range(8):
        value, = struct.unpack_from("<I", data, 85+4*i)
        struct.pack_into("<I", data, 85+4*i, value+delta)
    result = create_pac_cloth_guides(bytes(data), {0: rule()})
    after = decode_pac_embedded_volumes(result)
    assert result[after.file_end:80+_parse_par_sections(result)[0]["size"]] == tail
    for cut in (0, 1, 34, 38, len(tail)-1):
        from cdmw.modding.pac_cloth_guide_builder import _validate_metadata_tail
        with pytest.raises(ValueError):
            _validate_metadata_tail(tail, 0, cut, 0x02000000)


def test_limit_nonmanifold_and_unanchored_components_are_rejected():
    from cdmw.modding.pac_cloth_guide_builder import _topology
    with pytest.raises(ValueError, match="non-manifold"):
        _topology(POINTS + ((.5, -.5, 0),), FACES + ((1, 2, 4),), {2, 3})
    with pytest.raises(ValueError, match="disconnected"):
        _topology(POINTS + tuple((x+3, y, z) for x, y, z in POINTS), FACES + tuple(tuple(i+4 for i in f) for f in FACES), {2, 3})
    source = guide_free_pac(parts=257)
    with pytest.raises(ValueError, match="1024"):
        create_pac_cloth_guides(source, {i: rule() for i in range(257)})
