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


@pytest.mark.parametrize('optional_sets', [0, 1, 2])
def test_absent_optional_sets_are_distinct_from_explicit_empty_sets(optional_sets):
    rig = parse_pab(fixture(*(section() for _ in range(1 + optional_sets))))
    decoded = decode_pab_embedded_volumes(rig)
    assert decoded.primary.volumes == ()
    assert (decoded.rendering is None) == (optional_sets < 1)
    assert (decoded.physics is None) == (optional_sets < 2)
    for values in (decoded.rendering, decoded.physics):
        if values is not None:
            assert values.volumes == ()


def test_every_truncated_primary_tail_fails_before_binding():
    rig = parse_pab(fixture(section(record(key=0, flags=1)), flags=22))
    for cut in range(len(rig.tail_data)):
        with pytest.raises(ValueError, match='truncated'):
            decode_pab_embedded_volumes(replace(rig, tail_data=rig.tail_data[:cut]))


@pytest.mark.parametrize('suffix', [b'\x00', section(record())[:-1], section() * 3])
def test_incomplete_optional_sets_and_data_after_three_sets_are_rejected(suffix):
    with pytest.raises(ValueError, match='truncated|trailing'):
        decode_pab_embedded_volumes(parse_pab(fixture(section(), suffix)))


@pytest.mark.parametrize('change', [
    {'source_header': b''}, {'source_header': b'PAR \x01\x04' + bytes(16)},
    {'parser_mode': 'legacy_scan'}, {'bone_count': 1}, {'tail_offset': 22},
])
def test_unknown_headers_scanned_layouts_and_inconsistent_rigs_are_rejected(change):
    rig = parse_pab(fixture(section()))
    with pytest.raises(ValueError, match='PAB'):
        decode_pab_embedded_volumes(replace(rig, **change))


def test_empty_rig_requires_a_primary_count_and_manual_rigs_have_no_header_proof():
    header = b'PAR \x01\x05' + bytes(range(10)) + struct.pack('<IH', 0x16, 0)
    assert decode_pab_embedded_volumes(parse_pab(header + section())).primary.volumes == ()
    with pytest.raises(ValueError, match='truncated'):
        decode_pab_embedded_volumes(parse_pab(header))
    with pytest.raises(ValueError, match='header'):
        decode_pab_embedded_volumes(Skeleton())


def test_embedded_index_conversion_precedes_hash_lookup_and_unresolved_keys_stay_explicit():
    rig = parse_pab(fixture(section(record(key=1), record(key=0xFFFFFFFF))))
    # Even if a small value also exists as a hash, the embedded loader first
    # interprets keys below the bone count as indices.
    rig.bones[0].name_hash = 1
    decoded = decode_pab_embedded_volumes(rig)
    assert [v.bone_key for v in decoded.primary.volumes] == [0xA2000001, 0xFFFFFFFF]
    with pytest.raises(ValueError, match='hash'):
        resolve_pabv_bones(decoded.primary, rig)


def test_primary_geometry_reaches_existing_cloth_definition_preparation_without_other_sets():
    rig = parse_pab(fixture(
        section(record(key=0, flags=1), record(4, (.75,), key=0xA2000001, flags=0)),
        section(record(0, (10., 20., 30.), key=0, flags=0)), flags=4,
    ))
    decoded = decode_pab_embedded_volumes(rig)
    prepared = prepare_pabv_cloth_colliders(decoded.primary, rig, flag_bone_sets={2: (), 4: (), 8: ()})
    assert prepared.bone_indices == (0, 1)
    assert prepared.source_ordinals == (0, 1)
    assert prepared.has_activation_flag
    assert [struct.unpack_from('<Iff', row) for row in prepared.definitions] == [
        (5 << 16, .25, 2.), (1 << 16, .75, 0.),
    ]
