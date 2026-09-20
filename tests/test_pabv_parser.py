"""Analytic PABV records and authored-geometry to cloth-update handoff."""

from dataclasses import FrozenInstanceError, replace
import math
import struct

import pytest

from cdmw.modding.pabv_parser import (
    decode_pabv, pabv_cloth_collider_definition, resolve_pabv_bones,
)
from cdmw.modding.pac_cloth_collisions import update_guide_cloth_collider_result
from cdmw.modding.skeleton_parser import Bone, Skeleton


IDENTITY = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)


def record(tag=5, parameters=(.25, 2.), *, key=0x12345678, matrix=IDENTITY,
           usage=1, flags=None, vertices=(), indices=()):
    data = struct.pack('<I16fBB', key, *matrix, usage, tag)
    if tag == 2:
        data += struct.pack('<H', len(vertices))
        data += b''.join(struct.pack('<3f', *v) for v in vertices)
        data += struct.pack(f'<H{len(indices)}H', len(indices), *indices)
    else:
        data += struct.pack(f'<{len(parameters)}f', *parameters)
    return data + (b'' if flags is None else struct.pack('<I', flags))


def container(*records, flags=1):
    return b'PAR \x36\x01' + bytes(range(10)) + struct.pack('<IH', flags, len(records)) + b''.join(records)


def rig(*hashes):
    return Skeleton(bones=[Bone(index=i, name=f'bone{i}', name_hash=h) for i, h in enumerate(hashes)],
                    bone_count=len(hashes))


@pytest.mark.parametrize('extended', [False, True])
def test_all_shapes_offsets_flags_and_owned_immutable_geometry(extended):
    extra = {'flags': 0xA0000005} if extended else {}
    payloads = [
        record(0, (2., 4., 6.), usage=2, **extra),
        record(1, (.5, 3.), **extra),
        record(2, vertices=((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)), indices=(2, 0, 1), **extra),
        record(4, (.75,), **extra),
        record(5, (.25, 2.), **extra),
    ]
    data = bytearray(container(*payloads, flags=3 if extended else 1))
    original = bytes(data)
    decoded = decode_pabv(data)
    assert bytes(data) == original
    assert decoded.uses_bone_hashes and decoded.has_volume_flags == extended
    assert [v.shape_type for v in decoded.volumes] == [2, 3, 4, 1, 5]
    assert [v.parameters for v in decoded.volumes] == [(2., 4., 6.), (.5, 3.), (), (.75,), (.25, 2.)]
    assert decoded.volumes[0].usage == 2
    assert decoded.volumes[2].indices == (2, 0, 1)
    assert decoded.volumes[2].vertices == ((0., 0., 0.), (1., 0., 0.), (0., 1., 0.))
    offset = 22
    for volume, payload in zip(decoded.volumes, payloads):
        assert (volume.file_offset, volume.file_end) == (offset, offset + len(payload))
        assert volume.local_matrix == IDENTITY
        assert volume.flags == (0xA0000005 if extended else 0)
        offset += len(payload)
    data[:] = b'\0' * len(data)
    assert decoded.volumes[0].parameters == (2., 4., 6.)
    with pytest.raises(FrozenInstanceError):
        decoded.volumes[0].bone_key = 0


def test_empty_volume_file_and_unknown_flag_bits_are_retained():
    decoded = decode_pabv(container(flags=0x80000003))
    assert decoded.flags == 0x80000003 and decoded.volumes == ()
    assert resolve_pabv_bones(decoded, rig()) == ()


def test_every_truncated_prefix_and_trailing_data_are_rejected():
    data = container(record(flags=0), record(4, (.5,), flags=4), flags=3)
    for end in range(len(data)):
        with pytest.raises(ValueError):
            decode_pabv(data[:end])
    with pytest.raises(ValueError, match='trailing'):
        decode_pabv(data + b'\0')
    excessive_count = bytearray(container())
    struct.pack_into('<H', excessive_count, 20, 65535)
    with pytest.raises(ValueError, match='truncated'):
        decode_pabv(excessive_count)


@pytest.mark.parametrize('offset,value', [(0, 0), (4, 0x35), (5, 2), (15, 0)])
def test_unknown_header_is_rejected(offset, value):
    data = bytearray(container(record()))
    data[offset] = value
    with pytest.raises(ValueError, match='header'):
        decode_pabv(data)


@pytest.mark.parametrize('tag', [3, 6, 255])
def test_invalid_shape_tags_fail_without_reinterpreting_payload(tag):
    with pytest.raises(ValueError, match='shape tag'):
        decode_pabv(container(record(tag)))


@pytest.mark.parametrize('payload', [
    record(matrix=(math.nan,) + IDENTITY[1:]),
    record(parameters=(math.inf, 2.)),
    record(parameters=(-.5, 2.)),
    record(2, vertices=((math.nan, 0., 0.),)),
    record(2, vertices=((0., 0., 0.),), indices=(0, 0, 1)),
    record(2, vertices=((0., 0., 0.),), indices=(0, 0)),
])
def test_invalid_geometry_is_rejected(payload):
    with pytest.raises(ValueError):
        decode_pabv(container(payload))


def test_hash_binding_uses_keys_not_shape_ordinals_or_first_hash_match():
    data = decode_pabv(container(record(key=22), record(key=11), record(key=22)))
    assert resolve_pabv_bones(data, rig(11, 22)) == (1, 0, 1)
    with pytest.raises(ValueError, match='missing or ambiguous'):
        resolve_pabv_bones(data, rig(11))
    with pytest.raises(ValueError, match='missing or ambiguous'):
        resolve_pabv_bones(data, rig(11, 22, 22))


def test_legacy_index_binding_and_unverified_rigs_fail_explicitly():
    data = decode_pabv(container(record(key=1), flags=0))
    skeleton = rig(1, 2)
    assert not data.uses_bone_hashes
    assert resolve_pabv_bones(data, skeleton) == (1,)
    with pytest.raises(ValueError, match='out of range'):
        resolve_pabv_bones(data, rig(1))
    for invalid in (replace(skeleton, parser_mode='heuristic'), replace(skeleton, bone_count=3),
                    replace(skeleton, bones=list(reversed(skeleton.bones)))):
        with pytest.raises(ValueError, match='fixed-layout'):
            resolve_pabv_bones(data, invalid)


@pytest.mark.parametrize('tag,parameters,shape_type,height', [
    (4, (.5,), 1, 0.), (1, (.5, 2.), 3, 2.), (5, (.5, 2.), 5, 2.),
])
def test_collider_definition_preserves_geometry_and_requires_resolved_runtime_flags(tag, parameters, shape_type, height):
    volume, = decode_pabv(container(record(tag, parameters, flags=15), flags=3)).volumes
    definition = pabv_cloth_collider_definition(volume, resolved_flags=0x80000002)
    assert len(definition) == 104
    assert struct.unpack_from('<I2f', definition) == (shape_type << 16, .5, height)
    assert struct.unpack_from('<16f', definition, 12) == IDENTITY
    assert definition[76:100] == bytes(24)
    assert struct.unpack_from('<I', definition, 100)[0] == 0x80000002
    assert volume.flags == 15


def test_unsupported_contact_shapes_and_invalid_flags_are_rejected():
    for raw in (record(0, (1., 1., 1.)), record(2)):
        volume, = decode_pabv(container(raw)).volumes
        with pytest.raises(ValueError, match='sphere, cylinder or capsule'):
            pabv_cloth_collider_definition(volume, resolved_flags=0)
    volume, = decode_pabv(container(record())).volumes
    for flags in (-1, 2**32, True, 1.):
        with pytest.raises(ValueError, match='uint32'):
            pabv_cloth_collider_definition(volume, resolved_flags=flags)


def test_decoded_capsule_drives_existing_animated_collider_geometry():
    local = (0., 1., 0., 0., -1., 0., 0., 0., 0., 0., 1., 0., 1., 2., 3., 1.)
    decoded = decode_pabv(container(record(matrix=local)))
    assert resolve_pabv_bones(decoded, rig(0x12345678)) == (0,)
    definition = pabv_cloth_collider_definition(decoded.volumes[0], resolved_flags=0)
    bone_matrix = struct.pack('<16f', *(IDENTITY[:12] + (10., 20., 30., 1.)))
    character = struct.pack('<16f', *IDENTITY) + bytes(208)
    group = bytearray(56)
    struct.pack_into('<I', group, 0, (1 << 16) | 1)
    result = update_guide_cloth_collider_result(
        definition, bytes(56), group, bytes(108), bytes(1216), character,
        use_bone_transform=True, animation_matrix=bone_matrix, character_space_scale=(1., 1., 1.),
    )
    assert struct.unpack_from('<f', result, 4)[0] == .25
    assert struct.unpack_from('<3f', result, 20) == (11., 21., 33.)
    assert struct.unpack_from('<3f', result, 44) == (11., 23., 33.)
    assert result[8:20] == result[20:32]  # First update resets both history endpoints.
    assert result[32:44] == result[44:56]
