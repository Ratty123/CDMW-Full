"""Embedded PAB volumes use distinct header flags and ordered tail sections."""

from dataclasses import replace
import struct

import pytest

from cdmw.modding.pabv_parser import (
    decode_pab_embedded_volumes, prepare_pabv_cloth_colliders, resolve_pabv_bones,
)
from cdmw.modding.skeleton_parser import Skeleton, parse_pab
from tests.test_pab_bind_transforms import fixture as bone_fixture
from tests.test_pabv_parser import record


def section(*records):
    return struct.pack('<H', len(records)) + b''.join(records)


def fixture(*sections, flags=0):
    data = bytearray(bone_fixture()[0])
    data[:20] = b'PAR \x01\x05' + bytes(range(10)) + struct.pack('<I', flags)
    if flags & 0x10:
        data.extend(struct.pack('<2i', -1, 0))
    if flags & 0x2:
        data.extend(b'\x01\x00')
    data.extend(b''.join(sections))
    return bytes(data)


@pytest.mark.parametrize('flags', [0, 2, 4, 16, 18, 20, 22, 23])
def test_pab_flag_lanes_locate_distinct_sets_and_keep_absolute_record_provenance(flags):
    extra = {'flags': 0x80000001} if flags & 4 else {}
    body = record(key=1, **extra)
    render = record(4, (.75,), key=0xA2000000, usage=0, **extra)
    physics = record(2, key=0, usage=2, vertices=((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)),
                     indices=(0, 1, 2), **extra)
    data = fixture(section(body), section(render), section(physics), flags=flags)
    rig = parse_pab(data)
    decoded = decode_pab_embedded_volumes(rig)
    assert rig.source_header == data[:22]
    assert decoded.header_flags == flags
    sets = (decoded.primary, decoded.rendering, decoded.physics)
    assert [s.volumes[0].shape_type for s in sets] == [5, 1, 4]
    assert [s.volumes[0].usage for s in sets] == [1, 0, 2]
    assert [s.volumes[0].bone_key for s in sets] == [0xA2000001, 0xA2000000, 0xA2000000]
    assert [resolve_pabv_bones(s, rig) for s in sets] == [(1,), (0,), (0,)]
    cursor = rig.tail_offset + (8 if flags & 16 else 0) + (2 if flags & 2 else 0)
    for values, payload in zip(sets, (body, render, physics), strict=True):
        assert values.flags == (3 if flags & 4 else 1)
        volume, = values.volumes
        assert volume.flags == (0x80000001 if flags & 4 else 0)
        assert (volume.file_offset, volume.file_end) == (cursor + 2, cursor + 2 + len(payload))
        assert data[volume.file_offset:volume.file_end] == payload
        cursor = volume.file_end
    assert cursor == len(data)
    assert rig.tail_data == data[rig.tail_offset:]
