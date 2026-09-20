"""Owned static-mesh runtime records for attachment and reference-pair state."""

import struct

import pytest

from cdmw.modding.pac_cloth_state import (
    prepare_static_cloth_animation, select_cloth_base_integration,
)


IDENTITY = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))


def transform(basis=IDENTITY, translation=(10., 20., 30.), tiles=(-2, 3)):
    record = bytearray(64)
    for row, values in enumerate(basis):
        struct.pack_into('<3f', record, row*16, *values)
    struct.pack_into('<2h', record, 12, tiles[1], tiles[0])
    struct.pack_into('<3f', record, 48, *translation)
    return record


def records(*, flags=0, flags2=0, particle_flags=0, inverse_mass=1., attaching_id=0xFFFF):
    particle = bytearray(range(152))
    parameter, frame, scene = bytearray(312), bytearray(100), bytearray(108)
    skinning = bytearray(range(64))
    for offset, vector in ((12, (11., 12., 13.)), (24, (21., 22., 23.)),
                           (36, (2., 3., 4.)), (48, (31., 32., 33.)),
                           (128, (1., 0., 0.)), (140, (7., 8., 9.))):
        struct.pack_into('<3f', particle, offset, *vector)
    struct.pack_into('<fI', particle, 60, inverse_mass, particle_flags)
    struct.pack_into('<e', particle, 88, .5)
    struct.pack_into('<H', particle, 116, 0)
    struct.pack_into('<I', parameter, 144, 0xFFFFFFFF)
    struct.pack_into('<2H', parameter, 216, 1, 0xFFFF)
    struct.pack_into('<H', parameter, 224, 0xFFFF)
    struct.pack_into('<e', parameter, 266, 99.)
    struct.pack_into('<8e', parameter, 296, 0., 0., 0., 1., 0., 0., 0., 1.)
    struct.pack_into('<3f', frame, 0, 2., 3., 4.)
    struct.pack_into('<2I', frame, 32, flags, flags2)
    struct.pack_into('<3f', skinning, 0, 1., 2., 3.)
    struct.pack_into('<I', skinning, 60, attaching_id)
    return particle, parameter, frame, scene, skinning, transform()


def extra(data, *, flags=0, indices=(0xFFFF, 0xFFFF)):
    struct.pack_into('<I', data[1], 144, 100)
    struct.pack_into('<H', data[1], 224, 3)
    record = bytearray(28)
    struct.pack_into('<H', record, 0, flags)
    struct.pack_into('<2H', record, 22, *indices)
    return record


def prepare(data, **changes):
    options = dict(substep_index=0)
    options.update(changes)
    return prepare_static_cloth_animation(*data, **options)


def point(record, offset):
    return struct.unpack_from('<3f', record, offset)


def pair_records():
    particles, skinning = {}, {}
    for index, current, local in ((5, (10., 20., 30.), (1., 0., 0.)),
                                   (9, (10., 24., 30.), (3., 0., 0.))):
        particles[index], skinning[index] = bytearray(152), bytearray(64)
        struct.pack_into('<3f', particles[index], 36, *current)
        struct.pack_into('<3f', skinning[index], 0, *local)
    return particles, skinning


def test_host_basis_produces_uninterpolated_anchor_without_frame_or_world_translation():
    data = records(particle_flags=0x4001)
    data[-1][:] = transform(((0., 2., 0.), (-3., 0., 0.), (0., 0., 4.)))
    struct.pack_into('<3f', data[2], 0, 100., 200., 300.)
    before = tuple(bytes(record) for record in data)
    result = prepare(data, substep_index=2)
    assert point(result['particle'], 0) == (-6., 2., 12.)
    assert not result['attachment_used'] and not result['reference_pair_used']
    assert not result['space_adjusted'] and not result['skip_external_forces']
    assert struct.unpack_from('<I', result['particle'], 64)[0] == 0x4000
    assert result['host_world_translation'] == (-1990., 20., 3030.)
    assert result['water_sample_world_position'] == (-1888., 223., 3334.)
    allowed = set(range(12)) | set(range(64, 68))
    assert all(result['particle'][i] == before[0][i] for i in range(152) if i not in allowed)
    assert tuple(bytes(record) for record in data) == before


def test_attachment_applies_component_scale_quaternion_translation_then_selected_basis_and_tile_delta():
    data = records(flags=0x200000, attaching_id=7)
    struct.pack_into('<8e', data[1], 296, 5., 6., 7., 2., 0., 0., 1., 0.)
    attaching = transform(((0., 1., 0.), (-1., 0., 0.), (0., 0., 1.)),
                           translation=(15., 18., 37.), tiles=(-1, 1))
    result = prepare(data, attaching_transform=attaching)
    assert result['attachment_used']
    assert point(result['particle'], 0) == (1003., 1., -1980.)
    assert result['host_world_translation'] == (-1990., 20., 3030.)


@pytest.mark.parametrize('quaternion,expected', [
    ((.5, .5, .5, .5), (3., 1., 2.)),
    ((0., 0., 0., 2.), (4., 8., 12.)),
    ((0., 0., 0., 0.), (0., 0., 0.)),
])
def test_component_quaternion_direction_and_nonunit_magnitude_are_preserved(quaternion, expected):
    data = records(flags=0x200000, attaching_id=0)
    struct.pack_into('<4e', data[1], 304, *quaternion)
    result = prepare(data, attaching_transform=data[-1])
    assert point(result['particle'], 0) == expected


def test_relative_translation_keeps_small_offsets_at_large_signed_world_tiles():
    data = records(flags=0x200000, attaching_id=0)
    data[-1][:] = transform(translation=(.125, .5, .25), tiles=(-32768, 32767))
    attaching = transform(translation=(.25, .75, .5), tiles=(-32768, 32767))
    result = prepare(data, attaching_transform=attaching)
    assert point(result['particle'], 0) == (1.125, 2.25, 3.25)


@pytest.mark.parametrize('flags,attaching_id,offset,ratio,extra_flags,expected', [
    (0, 0, 0, 99., 0, False),
    (0x200000, 65534, 0x1FFFFFFE, 99., 0, True),
    (0x200000, 65535, 0, 99., 0, False),
    (0x200000, 0xFFFFFFFF, 0, 99., 0, False),
    (0x200000, 0, 0x1FFFFFFF, 99., 0, False),
    (0x280000, 0, 0, 98., 0, False),
    (0x280000, 0, 0, 99., 0, True),
    (0x280000, 0, 0, 98., 4, True),
])
def test_attachment_resource_and_stretch_veto_boundaries(flags, attaching_id, offset, ratio, extra_flags, expected):
    data = records(flags=flags, attaching_id=attaching_id)
    struct.pack_into('<I', data[1], 92, offset)
    struct.pack_into('<e', data[1], 266, ratio)
    extra_record = extra(data, flags=extra_flags)
    result = prepare(data, particle_extra=extra_record,
                     attaching_transform=transform() if expected else None)
    assert result['attachment_used'] is expected


def test_inactive_extra_storage_cannot_override_attachment_veto():
    data = records(flags=0x280000, attaching_id=0)
    struct.pack_into('<e', data[1], 266, 98.)
    extra_record = extra(data, flags=4)
    struct.pack_into('<I', data[1], 144, 0xFFFFFFFF)
    assert not prepare(data, particle_extra=extra_record)['attachment_used']
    struct.pack_into('<I', data[1], 144, 100)
    struct.pack_into('<H', data[1], 224, 0xFFFF)
    assert not prepare(data, particle_extra=extra_record)['attachment_used']


def test_reference_pair_overrides_component_offset_and_uses_untransformed_local_length():
    data = records(flags=0x200000, attaching_id=0)
    struct.pack_into('<3f', data[4], 0, 2., 1., 0.)
    struct.pack_into('<8e', data[1], 296, 100., 200., 300., 7., .5, .5, .5, .5)
    attaching = transform(((2., 0., 0.), (0., 3., 0.), (0., 0., 4.)),
                           translation=(1000., 2000., 3000.), tiles=(1, -2))
    particle_refs, skinning_refs = pair_records()
    extra_record = extra(data, indices=(5, 9))
    before = tuple(bytes(record) for record in data)
    reference_before = {i: (bytes(particle_refs[i]), bytes(skinning_refs[i])) for i in particle_refs}
    result = prepare(data, particle_extra=extra_record, attaching_transform=attaching,
                     reference_particles=particle_refs, reference_skinning=skinning_refs)
    assert result['attachment_used'] and result['reference_pair_used']
    assert point(result['particle'], 0) == (4., 24., 30.)
    assert point(result['particle'], 36) == (2., 3., 4.)
    assert tuple(bytes(record) for record in data) == before
    assert {i: (bytes(particle_refs[i]), bytes(skinning_refs[i])) for i in particle_refs} == reference_before


@pytest.mark.parametrize('indices', [(5, 0xFFFF), (0xFFFF, 9)])
def test_one_missing_reference_disables_pair_without_reading_reference_storage(indices):
    data = records()
    result = prepare(data, particle_extra=extra(data, indices=indices))
    assert not result['reference_pair_used']
    assert point(result['particle'], 0) == (1., 2., 3.)


@pytest.mark.parametrize('group_fixed', [True, False])
def test_pair_snap_uses_group_or_mask_fixed_state_not_zero_inverse_mass(group_fixed):
    data = records(inverse_mass=1. if group_fixed else 0.)
    if group_fixed:
        struct.pack_into('<H', data[0], 116, 1)
        struct.pack_into('<I', data[1], 168, 2)
    particle_refs, skinning_refs = pair_records()
    result = prepare(data, particle_extra=extra(data, indices=(5, 9)),
                     reference_particles=particle_refs, reference_skinning=skinning_refs)
    anchor = (6., 20., 36.)  # Local offset(0,2,3), quarter-turn, current/rest length2.
    assert point(result['particle'], 0) == anchor
    assert point(result['particle'], 12) == (anchor if group_fixed else (11., 12., 13.))
    assert point(result['particle'], 36) == (anchor if group_fixed else (2., 3., 4.))
    selected = select_cloth_base_integration(result['particle'], data[2])
    assert selected['branch'] == 'fixed'
    assert point(selected['particle'], 12) == point(selected['particle'], 24) == anchor
    assert point(selected['particle'], 140) == (7., 8., 9.)


def test_collapsed_simulated_edge_uses_first_reference_but_zero_local_edge_is_rejected():
    data = records()
    particle_refs, skinning_refs = pair_records()
    particle_refs[9][:] = particle_refs[5]
    options = dict(particle_extra=extra(data, indices=(5, 9)),
                   reference_particles=particle_refs, reference_skinning=skinning_refs)
    assert point(prepare(data, **options)['particle'], 0) == (10., 20., 30.)
    skinning_refs[9][:] = skinning_refs[5]
    with pytest.raises(ValueError, match='zero local edge'):
        prepare(data, **options)


@pytest.mark.parametrize('skip_integration', [False, True])
def test_first_step_static_adjustment_preserves_skip_decisions_for_later_water_query(skip_integration):
    data = records(flags=1, flags2=0x1000 | (0x100 if skip_integration else 0), particle_flags=0x4000)
    struct.pack_into('<3f', data[4], 0, 0., 2., 0.)
    result = prepare(data)
    particle = result['particle']
    assert result['space_adjusted'] and result['skip_external_forces']
    assert result['water_test_enabled']
    assert result['integration_skipped'] is skip_integration  # Old0x4000 has no guide override here.
    assert point(particle, 12) == ((-3., 2., 4.) if skip_integration else (11., 12., 13.))
    assert point(particle, 36) == ((2., 3., 4.) if skip_integration else (-3., 2., 4.))
    assert point(particle, 140) == (0., 0., 0.)
    assert result['water_sample_world_position'] == ((-1986., 26., 3038.) if skip_integration else (-1991., 25., 3038.))
    later = prepare(data, substep_index=1)
    assert not later['space_adjusted'] and later['skip_external_forces']
    assert point(later['particle'], 140) == (7., 8., 9.)


@pytest.mark.parametrize('movement,expected', [(-30., False), (-20., True), (-10., False)])
def test_static_special_movement_obeys_strict_window(movement, expected):
    data = records(flags=0x20000000)
    struct.pack_into('<I', data[3], 64, 0x200)
    struct.pack_into('<e', data[2], 62, movement)
    result = prepare(data, substep_index=1)
    assert result['skip_external_forces'] is expected
    assert result['integration_skipped'] is expected


def test_missing_active_records_and_wrong_mesh_mode_are_rejected():
    data = records(flags=0x200000, attaching_id=0)
    with pytest.raises(ValueError, match='attaching transform'):
        prepare(data)
    extra_record = extra(data, indices=(5, 9))
    with pytest.raises(ValueError, match='particle-extra storage'):
        prepare(data, attaching_transform=data[-1])
    with pytest.raises(ValueError, match='both indexed'):
        prepare(data, attaching_transform=data[-1], particle_extra=extra_record)
    with pytest.raises(ValueError, match='64-byte'):
        prepare_static_cloth_animation(*data[:-1], data[-1][:-1], substep_index=0)
    struct.pack_into('<H', data[1], 216, 0xFFFF)
    with pytest.raises(ValueError, match='static-mesh'):
        prepare(data)
