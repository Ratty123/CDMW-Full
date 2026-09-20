"""Analytic PABV records and authored-geometry to cloth-update handoff."""

from dataclasses import FrozenInstanceError, replace
import math
import struct

import pytest

from cdmw.modding.pabv_parser import (
    decode_pabv, default_pabv_cloth_flag_bone_sets,
    merge_pabv_body_head_volumes, pabv_cloth_collider_definition, prepare_pabv_cloth_colliders,
    resolve_pabv_bones,
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


def test_preparation_replaces_all_three_runtime_bits_and_retains_other_source_flags():
    volumes = decode_pabv(container(
        record(key=11, flags=0x8000000F), record(key=22, flags=0x20), flags=3,
    ))
    prepared = prepare_pabv_cloth_colliders(
        volumes, rig(11, 22), flag_bone_sets={2: {11}, 4: {22}, 8: {11, 22}},
    )
    assert [struct.unpack_from('<I', d, 100)[0] for d in prepared.definitions] == [0x8000000B, 0x2C]
    assert prepared.bone_indices == (0, 1) and prepared.source_ordinals == (0, 1)
    assert prepared.has_activation_flag
    assert volumes.volumes[0].flags == 0x8000000F


def test_preparation_uses_resolved_hashes_for_legacy_index_records():
    prepared = prepare_pabv_cloth_colliders(
        decode_pabv(container(record(key=1), flags=0)), rig(11, 22),
        flag_bone_sets={2: {22}, 4: {1}, 8: set()},
    )
    assert struct.unpack_from('<I', prepared.definitions[0], 100)[0] == 2
    assert prepared.bone_indices == (1,) and not prepared.has_activation_flag


def test_deduplication_keeps_first_mapping_even_when_identical_geometry_uses_different_bones():
    volumes = decode_pabv(container(record(key=22), record(key=11)))
    prepared = prepare_pabv_cloth_colliders(volumes, rig(11, 22), flag_bone_sets={2: (), 4: (), 8: ()})
    assert len(prepared.definitions) == 1
    assert prepared.bone_indices == (1,) and prepared.source_ordinals == (0,)


def test_deduplication_threshold_is_inclusive_float32_and_compares_only_kept_records():
    threshold_bits = struct.unpack('<I', struct.pack('<f', .001))[0]
    threshold, = struct.unpack('<f', struct.pack('<I', threshold_bits))
    above, = struct.unpack('<f', struct.pack('<I', threshold_bits + 1))

    def translated(value):
        return record(matrix=IDENTITY[:12] + (value, 0., 0., 1.))

    for offsets in ((0., threshold, above), (0., .0008, .0016)):
        volumes = decode_pabv(container(*(translated(value) for value in offsets)))
        prepared = prepare_pabv_cloth_colliders(
            volumes, rig(0x12345678), flag_bone_sets={2: (), 4: (), 8: ()},
        )
        assert prepared.source_ordinals == (0, 2)


def test_deduplication_compares_type_flags_and_full_matrix():
    volumes = decode_pabv(container(
        record(flags=0), record(1, flags=0), record(flags=1),
        record(matrix=IDENTITY[:15] + (1.01,), flags=0), flags=3,
    ))
    prepared = prepare_pabv_cloth_colliders(volumes, rig(0x12345678), flag_bone_sets={2: (), 4: (), 8: ()})
    assert prepared.source_ordinals == (0, 1, 2, 3)
    assert prepared.has_activation_flag


def test_large_finite_matrix_differences_do_not_overflow_deduplication():
    volumes = decode_pabv(container(
        record(matrix=IDENTITY[:12] + (3e38, 0., 0., 1.)),
        record(matrix=IDENTITY[:12] + (-3e38, 0., 0., 1.)),
    ))
    prepared = prepare_pabv_cloth_colliders(volumes, rig(0x12345678), flag_bone_sets={2: (), 4: (), 8: ()})
    assert prepared.source_ordinals == (0, 1)


@pytest.mark.parametrize('sets', [{2: (), 4: ()}, {2: (), 4: (), 8: (), 16: ()},
                                   {2: {-1}, 4: (), 8: ()}, {2: (), 4: {True}, 8: ()}])
def test_preparation_requires_complete_valid_runtime_bone_sets(sets):
    with pytest.raises(ValueError, match='bone sets'):
        prepare_pabv_cloth_colliders(decode_pabv(container()), rig(), flag_bone_sets=sets)


def test_initial_flag_sets_match_decoded_names_and_stored_bone_hashes():
    # Expected hashes are stored in the fixed PHW PAB, independently of this
    # helper's checksum calculation. The three sets come from the CPU loader.
    legs = {0xBC1D1337, 0xD17D9109, 0x59314D02, 0xAB802677, 0xDD9C07F3, 0xF4A5787C}
    expected = {2: frozenset({0x3C739A3A, *legs}),
                4: frozenset({0x9B5DF434, 0x24D97B45}), 8: frozenset(legs)}
    actual = default_pabv_cloth_flag_bone_sets()
    assert actual == expected
    assert all(isinstance(values, frozenset) for values in actual.values())
    actual[2] = frozenset()
    assert default_pabv_cloth_flag_bone_sets() == expected


def test_explicit_initial_profile_drives_pelvis_leg_arm_and_unclassified_shapes():
    hashes = (0x3C739A3A, 0xD17D9109, 0x9B5DF434, 0x12345678)
    volumes = decode_pabv(container(*(record(key=key, flags=0x2E) for key in hashes), flags=3))
    prepared = prepare_pabv_cloth_colliders(
        volumes, rig(*hashes), flag_bone_sets=default_pabv_cloth_flag_bone_sets(),
    )
    assert [struct.unpack_from('<I', d, 100)[0] for d in prepared.definitions] == [0x22, 0x2A, 0x24, 0x20]
    assert prepared.bone_indices == (0, 1, 2, 3)
    assert not prepared.has_activation_flag  # The profile does not introduce bit 0.


def test_body_head_merge_replaces_first_head_only_and_preserves_complete_source_records():
    key = 0xA23A288E
    body = decode_pabv(container(record(key=11), record(key=key), record(key=key, parameters=(.5, 3.))))
    head = decode_pabv(container(
        record(key=22, flags=0),
        record(2, key=key, flags=0x80000001, usage=2,
               vertices=((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)), indices=(2, 1, 0)),
        record(key=key, flags=4), flags=3,
    ))
    merged = merge_pabv_body_head_volumes(body, head)
    assert merged.volumes.volumes == (body.volumes[0], head.volumes[1], body.volumes[2])
    assert merged.volumes.volumes[1] is head.volumes[1]
    assert merged.source_records == ((0, 0), (1, 1), (0, 2))
    assert merged.volumes.flags == 3 and body.flags == 1
    assert body.volumes[1].serialized_shape == 5  # The input is unchanged.


def test_body_without_head_keeps_every_record_and_source_ordinal():
    body = decode_pabv(container(record(key=11), record(key=22), flags=0x80000001))
    merged = merge_pabv_body_head_volumes(body)
    assert merged.volumes.volumes == body.volumes
    assert merged.source_records == ((0, 0), (0, 1))
    assert merged.volumes.flags == 3  # A materialized record set, not a file header.
    assert body.flags == 0x80000001
    assert merge_pabv_body_head_volumes(decode_pabv(container(flags=0))).source_records == ()


@pytest.mark.parametrize('body_key,head_key', [(11, 0xA23A288E), (0xA23A288E, 11), (11, 22)])
def test_body_head_merge_rejects_missing_head_match_without_appending_or_guessing(body_key, head_key):
    body = decode_pabv(container(record(key=body_key)))
    head = decode_pabv(container(record(key=head_key)))
    with pytest.raises(ValueError, match='Bip01 Head in both'):
        merge_pabv_body_head_volumes(body, head)


def test_body_head_merge_normalizes_legacy_indices_through_each_explicit_source_rig():
    body = decode_pabv(container(record(key=1), record(key=0), flags=0))
    head = decode_pabv(container(record(4, (.75,), key=0, flags=1), flags=2))
    merged = merge_pabv_body_head_volumes(
        body, head, body_skeleton=rig(11, 0xA23A288E), head_skeleton=rig(0xA23A288E, 22),
    )
    assert [volume.bone_key for volume in merged.volumes.volumes] == [0xA23A288E, 11]
    assert merged.source_records == ((1, 0), (0, 1))
    assert merged.volumes.volumes[0].parameters == (.75,)
    assert merged.volumes.volumes[0].flags == 1
    assert body.volumes[0].bone_key == 1 and head.volumes[0].bone_key == 0


def test_legacy_head_never_implicitly_uses_the_body_rig():
    legacy = decode_pabv(container(record(key=0), flags=0))
    hashed = decode_pabv(container(record(key=0xA23A288E)))
    with pytest.raises(ValueError, match='body merge source needs'):
        merge_pabv_body_head_volumes(legacy)
    with pytest.raises(ValueError, match='head merge source needs'):
        merge_pabv_body_head_volumes(hashed, legacy, body_skeleton=rig(0xA23A288E))


def test_merged_records_prepare_colliders_with_the_replaced_geometry_and_provenance():
    body = decode_pabv(container(record(key=0xA23A288E), record(key=0x3C739A3A)))
    head = decode_pabv(container(record(4, (.75,), key=0xA23A288E)))
    merged = merge_pabv_body_head_volumes(body, head)
    prepared = prepare_pabv_cloth_colliders(
        merged.volumes, rig(0xA23A288E, 0x3C739A3A),
        flag_bone_sets=default_pabv_cloth_flag_bone_sets(),
    )
    assert [struct.unpack_from('<Iff', row) for row in prepared.definitions] == [
        (1 << 16, .75, 0.), (5 << 16, .25, 2.),
    ]
    assert [struct.unpack_from('<I', row, 100)[0] for row in prepared.definitions] == [0, 2]
    assert tuple(merged.source_records[i] for i in prepared.source_ordinals) == ((1, 0), (0, 1))
