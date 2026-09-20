"""Owned synthetic records for base-state eligibility and writeback boundaries."""

import struct

import pytest

from cdmw.modding.pac_cloth_base import integrate_cloth_forces
from cdmw.modding.pac_cloth_state import (
    finalize_cloth_base_hold, predict_dynamic_cloth_state, prepare_cloth_fixed_state,
)


def records(*, guide=True, flags=0, frame_flags=0, flags2=0, group=0, active=0,
            inverse_mass=1., ratio=99., cr=0.):
    particle = bytearray(range(152))  # Distinct sentinels in fields these stages do not own.
    parameter, frame, scene = bytearray(312), bytearray(100), bytearray(108)
    struct.pack_into('<3f', particle, 12, 8., -2., 1.)
    struct.pack_into('<3f', particle, 24, 5., 6., 7.)
    struct.pack_into('<3f', particle, 36, 2., 3., 4.)
    struct.pack_into('<fI', particle, 60, inverse_mass, flags)
    struct.pack_into('<8e', particle, 72, 0., -1., 0., 3.5, 1., 2., 3., 4.5)
    struct.pack_into('<2e', particle, 88, .75, cr)
    struct.pack_into('<H', particle, 116, group)
    struct.pack_into('<f', particle, 120, 4.25)
    struct.pack_into('<3f', particle, 140, 11., 12., 13.)
    struct.pack_into('<I', parameter, 168, active)
    struct.pack_into('<2H', parameter, 216, 0xFFFF if guide else 7, 0xFFFF)
    struct.pack_into('<2e', parameter, 248, .25, .5)
    struct.pack_into('<e', parameter, 266, ratio)
    struct.pack_into('<2I', frame, 32, frame_flags, flags2)
    struct.pack_into('<3e', scene, 86, 3., 0., 4.)
    struct.pack_into('<3e', scene, 100, 0., -1., 0.)
    return particle, parameter, frame, scene


def predict(data, velocity=(4., -2., 8.), **changes):
    options = dict(delta_time=.5, integration_skipped=False, storage_variant='packed')
    options.update(changes)
    return predict_dynamic_cloth_state(*data, velocity, **options)


def flags_of(particle):
    return struct.unpack_from('<I', particle, 64)[0]


def vector(particle, offset):
    return struct.unpack_from('<3f', particle, offset)


@pytest.mark.parametrize('group,active,fixed', [
    (0, 0xFFFFFFFF, False), (1, 2, True), (1, 1, False),
    (31, 0x80000000, True), (32, 0xFFFFFFFF, False),
])
def test_fixed_groups_use_original_one_through_31_bit_indices(group, active, fixed):
    particle, parameter, _, _ = records(group=group, active=active, flags=0x15)
    before = bytes(particle), bytes(parameter)
    result = prepare_cloth_fixed_state(particle, parameter)
    assert result['fixed_by_group_or_mask'] is fixed
    assert result['dynamic'] is not fixed
    assert flags_of(result['particle']) == (0x40 if fixed else 0)
    assert result['particle'][:64] == particle[:64]
    assert result['particle'][68:] == particle[68:]
    assert (bytes(particle), bytes(parameter)) == before


@pytest.mark.parametrize('guide,ratio,expected_flags,fixed', [
    (True, 98., 0, False), (False, 98., 0x4000, False),
    (True, 99., 0x40, True), (False, 99., 0x4040, True),
])
def test_overstretch_veto_reads_old_flag_before_guide_clears_it(guide, ratio, expected_flags, fixed):
    particle, parameter, _, _ = records(guide=guide, ratio=ratio, flags=0x4015, group=1, active=2)
    result = prepare_cloth_fixed_state(particle, parameter)
    assert result['fixed_by_group_or_mask'] is fixed
    assert flags_of(result['particle']) == expected_flags


def test_shrink_mask_can_fix_particles_outside_groups_but_zero_inverse_mass_sets_no_group_bit():
    particle, parameter, _, _ = records(flags=0x800040)
    struct.pack_into('<H', parameter, 218, 3)
    fixed = prepare_cloth_fixed_state(particle, parameter, shrink_mask=0)
    assert fixed['fixed_by_group_or_mask'] and not fixed['dynamic']
    assert flags_of(fixed['particle']) == 0x800040
    free = prepare_cloth_fixed_state(particle, parameter, shrink_mask=1)
    assert free['dynamic'] and not free['fixed_by_group_or_mask']
    assert flags_of(free['particle']) == 0
    struct.pack_into('<f', particle, 60, 0.)
    pinned = prepare_cloth_fixed_state(particle, parameter, shrink_mask=1)
    assert not pinned['dynamic'] and not pinned['fixed_by_group_or_mask']
    assert flags_of(pinned['particle']) == 0


@pytest.mark.parametrize('sample', [None, True, -1, 0x100000000])
def test_active_shrink_resource_requires_resolved_uint32(sample):
    particle, parameter, _, _ = records()
    struct.pack_into('<H', parameter, 218, 3)
    with pytest.raises(ValueError, match='resolved uint32'):
        prepare_cloth_fixed_state(particle, parameter, shrink_mask=sample)


@pytest.mark.parametrize('guide,cr,flags,eligible', [
    (True, 0., 0x10000000, False), (True, 1., 0, True),
    (False, 1., 0, False), (False, 0., 0x10000000, True),
])
def test_guide_and_static_contacts_use_different_eligibility(guide, cr, flags, eligible):
    result = predict(records(guide=guide, cr=cr, flags=flags))
    assert result['contact_response_eligible'] is eligible
    expected_velocity = (3., 1., 6.) if eligible else (4., -2., 8.)
    expected_position = (3.5, 3.5, 7.) if eligible else (4., 2., 8.)
    assert vector(result['particle'], 140) == expected_velocity
    assert vector(result['particle'], 12) == expected_position
    assert flags_of(result['particle']) == (0 if eligible else flags)


def test_outward_contact_clears_static_flag_without_changing_velocity():
    result = predict(records(guide=False, flags=0x10000000), velocity=(4., 2., 8.))
    assert result['contact_response_eligible']
    assert vector(result['particle'], 140) == (4., 2., 8.)
    assert flags_of(result['particle']) == 0


@pytest.mark.parametrize('variant,retain', [
    ('packed', False), ('native16', False), ('packed', True), ('native16', True),
])
def test_contact_cache_variant_preserves_other_fields_and_inputs(variant, retain):
    data = records(guide=False, cr=2., flags2=0x200 if retain else 0)
    before = tuple(bytes(record) for record in data)
    result = predict(data, storage_variant=variant)['particle']
    if retain:
        assert result[72:92] == data[0][72:92]
    else:
        assert struct.unpack_from('<4e', result, 72) == (0., 0., 0., 3.5 if variant == 'native16' else 0.)
        assert struct.unpack_from('<4e', result, 80) == (0., 0., 0., 4.5 if variant == 'native16' else 0.)
        assert struct.unpack_from('<2e', result, 88) == (.75, 0.)
    assert vector(result, 48) == (2., 3., 4.)
    allowed = set(range(12, 24)) | set(range(48, 60)) | set(range(64, 68))
    allowed |= set(range(72, 88)) | {90, 91} | set(range(140, 152))
    assert all(result[i] == before[0][i] for i in range(152) if i not in allowed)
    assert tuple(bytes(record) for record in data) == before


@pytest.mark.parametrize('w,frame_flag,scene_flag,boost', [
    (-50., True, True, False), (-5., True, True, False), (-25., True, True, True),
    (-25., False, True, False), (-25., True, False, False),
])
def test_backward_boost_affects_prediction_only_with_both_flags_and_strict_window(w, frame_flag, scene_flag, boost):
    data = records(frame_flags=0x20000000 if frame_flag else 0)
    struct.pack_into('<e', data[2], 62, w)
    struct.pack_into('<I', data[3], 64, 0x200 if scene_flag else 0)
    result = predict(data, velocity=(0., 0., 0.))
    assert result['prediction_velocity'] == pytest.approx((-.12, 0., -.16) if boost else (0., 0., 0.))
    assert vector(result['particle'], 12) == pytest.approx((1.94, 3., 3.92) if boost else (2., 3., 4.))
    assert vector(result['particle'], 140) == (0., 0., 0.)


def test_skipped_integration_still_clips_prepared_prediction_against_ground():
    data = records(frame_flags=0x1000000)
    struct.pack_into('<f', data[1], 208, .5)
    struct.pack_into('<f', data[2], 24, 1.)
    result = predict(data, velocity=(100., 200., 300.), integration_skipped=True)
    assert result['ground_contact']
    assert vector(result['particle'], 12) == (8., 1.5, 1.)
    assert vector(result['particle'], 48) == (2., 3., 4.)
    assert vector(result['particle'], 140) == (100., 200., 300.)
    assert flags_of(result['particle']) == 2


@pytest.mark.parametrize('flags,flags2,ratio,acceleration,held', [
    (0x80000000, 0x10000, 99., (.03, -.04, .02), True),
    (0x80000000, 0x10000, 99., (.1, 0., 0.), False),
    (0x80000000, 0x10000, 98., (0., 0., 0.), False),
    (0x80000000, 0, 99., (0., 0., 0.), False),
    (0, 0x10000, 99., (0., 0., 0.), False),
])
def test_hold_requires_existing_flag_and_all_thresholds_and_preserves_velocity(flags, flags2, ratio, acceleration, held):
    particle, parameter, frame, _ = records(flags=flags | 0x40000, flags2=flags2, ratio=ratio)
    before = bytes(particle), bytes(parameter), bytes(frame)
    result = finalize_cloth_base_hold(particle, parameter, frame,
                                      non_gravity_acceleration=acceleration, delta_time=.5)
    assert result['held'] is held
    output = result['particle']
    assert output[12:36] == (particle[36:48] * 2 if held else particle[12:36])
    assert flags_of(output) == (0x80040000 if held else 0x40000)
    assert struct.unpack_from('<f', output, 120)[0] == 4.75
    allowed = set(range(12, 36)) | set(range(64, 68)) | set(range(120, 124))
    assert all(output[i] == before[0][i] for i in range(152) if i not in allowed)
    assert (bytes(particle), bytes(parameter), bytes(frame)) == before


@pytest.mark.parametrize('flags', [0x100, 0x200])
def test_pinch_flags_reset_timer_before_time_is_added(flags):
    particle, parameter, frame, _ = records(flags=flags)
    result = finalize_cloth_base_hold(particle, parameter, frame,
                                      non_gravity_acceleration=(0., 0., 0.), delta_time=.5)
    assert struct.unpack_from('<f', result['particle'], 120)[0] == 100000.5


def test_force_prediction_hold_composition_uses_non_gravity_acceleration_not_velocity():
    particle, parameter, frame, scene = records(flags=0x80000000, flags2=0x10000)
    prepared = prepare_cloth_fixed_state(particle, parameter)
    assert prepared['dynamic']
    forces = integrate_cloth_forces(
        (0., 0., 0.), gravity_direction=(0., -1., 0.), gravity=-10., delta_time=.5,
        inverse_mass=1., underwater=False, underwater_density=1., bone_acceleration=(0., 0., 0.),
        inertial_scale=1., inertial_acceleration_limit=10., environmental_acceleration=(0., 0., 0.),
        skip_external_forces=False)
    predicted = predict((prepared['particle'], parameter, frame, scene), velocity=forces['velocity'])
    assert vector(predicted['particle'], 12) == (2., .5, 4.)
    held = finalize_cloth_base_hold(predicted['particle'], parameter, frame,
                                    non_gravity_acceleration=forces['non_gravity_acceleration'], delta_time=.5)
    assert held['held']
    assert vector(held['particle'], 12) == vector(held['particle'], 24) == (2., 3., 4.)
    assert vector(held['particle'], 140) == (0., -5., 0.)


@pytest.mark.parametrize('changes', [
    dict(frame_flags=0x400), dict(frame_flags=0x800), dict(inverse_mass=0.), dict(flags=0x40),
])
def test_prediction_rejects_branches_that_need_separate_state_handling(changes):
    with pytest.raises(ValueError, match='normal dynamic branch'):
        predict(records(**changes))


def test_incomplete_or_nonfinite_consumed_data_and_ambiguous_choices_are_rejected():
    data = records()
    with pytest.raises(ValueError, match='complete 152-byte'):
        prepare_cloth_fixed_state(data[0][:-1], data[1])
    with pytest.raises(ValueError, match='variant'):
        predict(data, storage_variant='automatic')
    with pytest.raises(ValueError, match='explicit booleans'):
        predict(data, integration_skipped=1)
    with pytest.raises(ValueError, match='nonnegative'):
        predict(data, delta_time=-.5)
    with pytest.raises(ValueError, match='finite'):
        predict(data, velocity=(float('nan'), 0., 0.))
    data = records(frame_flags=0x20000000)
    struct.pack_into('<e', data[2], 62, -25.)
    struct.pack_into('<I', data[3], 64, 0x200)
    struct.pack_into('<3e', data[3], 86, 0., 0., 0.)
    with pytest.raises(ValueError, match='nonzero direction'):
        predict(data)
