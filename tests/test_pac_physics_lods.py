"""Empty lower-LOD descriptors must not shift physics edits to another part."""

import struct

import pytest

from cdmw.domain.mesh.cloth import PacClothRule
from cdmw.domain.mesh.jiggle import PacJiggleRule
from cdmw.modding.pac_cloth import apply_pac_cloth_rules, pac_cloth_lods
from cdmw.modding.pac_jiggle import apply_pac_jiggle_rules
from tests.test_pac_skin_extra_influences import _record


def empty_lod_part_fixture(empty_part=1):
    metadata = bytearray(37)
    metadata[4] = 4
    lod_payloads = [bytearray() for _ in range(4)]
    lod_indices = [bytearray() for _ in range(4)]
    for part in range(3):
        name = f"part{part}".encode()
        metadata.extend(bytes([len(name)]) + name + bytes([len(name)]) + name)
        descriptor = bytearray(64)
        descriptor[0] = 1
        struct.pack_into("<8f", descriptor, 3, 0, 0, 0, 0, 0, 1, 1, 1)
        descriptor[35:40] = bytes([4, 0, 1, 2, 3])
        for lod in range(4):
            count = 0 if lod == 3 and part == empty_part else 3
            struct.pack_into("<H", descriptor, 40 + lod * 2, count)
            struct.pack_into("<I", descriptor, 48 + lod * 4, count)
            for i in range(count):
                row = bytearray(_record(palette=(1, 2, 3, 4, 5, 6),
                                       weights=(255, 0, 0, 0, 255, 0, 0, 0),
                                       extra=(0., 1.), gate=0))
                struct.pack_into("<3H", row, 0, int(i == 1) * 32767, int(i == 2) * 32767, 0)
                row[38] = 249 + part
                lod_payloads[lod].extend(row)
            if count:
                lod_indices[lod].extend(struct.pack("<3H", 0, 1, 2))
        metadata.extend(descriptor)
    payloads = [metadata] + [lod_payloads[lod] + lod_indices[lod] for lod in (3, 2, 1, 0)]
    header = bytearray(80)
    header[:4] = b"PAR "
    cursor = 80
    for section, payload in enumerate(payloads):
        struct.pack_into("<II", header, 16 + section * 8, 0, len(payload))
        if section:
            lod = 4 - section
            struct.pack_into("<I", metadata, 5 + lod * 4, cursor)
            struct.pack_into("<I", metadata, 21 + lod * 4, cursor + len(lod_payloads[lod]))
        cursor += len(payload)
    return bytes(header) + b"".join(payloads)


@pytest.mark.parametrize("empty_part", [0, 1, 2])
def test_empty_part_keeps_identity_and_later_parts_are_edited_at_every_lod(empty_part):
    source = empty_lod_part_fixture(empty_part)
    levels = pac_cloth_lods(source)
    assert [p.name for p in levels[3].submeshes] == ["part0", "part1", "part2"]
    assert levels[3].submeshes[empty_part].vertices == []
    for target in range(3):
        jiggle = apply_pac_jiggle_rules(source, {target: PacJiggleRule()})
        expected = bytearray(source)
        for mesh in levels:
            for offset in mesh.submeshes[target].source_vertex_offsets:
                expected[offset + 38] = 255
        assert jiggle == expected
        cloth = apply_pac_cloth_rules(source, {target: PacClothRule(.5)})
        expected = bytearray(source)
        for mesh in levels:
            for offset in mesh.submeshes[target].source_vertex_offsets:
                expected[offset + 39] = (source[offset + 39] & 0xC0) | 32
        assert cloth == expected


def test_nonempty_part_that_cannot_be_parsed_is_still_rejected():
    source = bytearray(empty_lod_part_fixture())
    descriptor = pac_cloth_lods(source)[0].submeshes[1].source_descriptor_offset
    # No stored vertices, but it claims triangles. This is not an empty part.
    struct.pack_into("<I", source, descriptor + 60, 3)
    with pytest.raises(ValueError):
        pac_cloth_lods(bytes(source))
