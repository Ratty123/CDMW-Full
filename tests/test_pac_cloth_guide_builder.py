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
