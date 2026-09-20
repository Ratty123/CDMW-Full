"""Owned records for decoded guide animation, clock and kinematic branches."""

import math
import struct

import pytest

from cdmw.modding.pac_cloth_base import integrate_cloth_forces
from cdmw.modding.pac_cloth_state import (
    predict_dynamic_cloth_state, prepare_guide_cloth_animation,
    select_cloth_base_integration, select_cloth_base_substep,
)


def records(*, flags=0, flags2=0, particle_flags=0, inverse_mass=1.):
    particle = bytearray(range(152))
    parameter, frame, scene = bytearray(312), bytearray(100), bytearray(108)
    guide, character, clock = bytearray(64), bytearray(272), bytearray(1216)
    for offset, point in ((0, (9., 8., 7.)), (12, (11., 12., 13.)),
                          (24, (21., 22., 23.)), (36, (2., 3., 4.)),
                          (48, (31., 32., 33.)), (128, (1., 0., 0.)),
                          (140, (7., 8., 9.))):
        struct.pack_into('<3f', particle, offset, *point)
    struct.pack_into('<fI', particle, 60, inverse_mass, particle_flags)
    struct.pack_into('<2e', particle, 88, .5, 0.)
    struct.pack_into('<H', particle, 116, 0)
    struct.pack_into('<2H', parameter, 216, 0xFFFF, 0xFFFF)
    struct.pack_into('<e', parameter, 266, 99.)
    struct.pack_into('<2I', frame, 32, flags, flags2)
    struct.pack_into('<e', scene, 94, 1.)
    struct.pack_into('<3e', scene, 100, 0., -1., 0.)
    struct.pack_into('<3f', guide, 48, 0., 2., 0.)
    for row in range(4):
        struct.pack_into('<f', character, row * 20, 1.)
    struct.pack_into('<3f', character, 48, 100., 200., 300.)
    struct.pack_into('<5fI', clock, 864, .25, .5, .75, .125, .25, 4)
    struct.pack_into('<5fI', clock, 896, .5, .75, 1.5, .25, .5, 2)
    return particle, parameter, frame, scene, guide, character, clock


def substep(data, index=0):
    return select_cloth_base_substep(data[2], data[3], data[6], substep_index=index)


def animate(data, **changes):
    options = dict(substep_index=0, animation_blend=.25, inside_water_volume=False)
    options.update(changes)
    return prepare_guide_cloth_animation(*data[:6], **options)


def point(particle, offset):
    return struct.unpack_from('<3f', particle, offset)


def test_clock_selects_scaled_fields_and_scene_scale_only_changes_integration_time():
    data = records()
    struct.pack_into('<e', data[3], 94, .5)
    assert substep(data, 1) == {'delta_time': .125, 'guide_animation_blend': .5}
    struct.pack_into('<I', data[2], 36, 0x8000)
    assert substep(data, 1) == {'delta_time': .25, 'guide_animation_blend': .5}
    assert substep(data, 2) is None  # Scaled count2, ordinary count4.
    struct.pack_into('<I', data[2], 36, 0)
    assert substep(data, 2) == {'delta_time': .125, 'guide_animation_blend': .75}


@pytest.mark.parametrize('flags,flags2,index,expected', [
    (0, 0, 0, None), (0x800, 0, 0, None),
    (0x400, 0, 0, {'delta_time': 0., 'guide_animation_blend': 0.}),
    (0, 0x800, 0, {'delta_time': .5, 'guide_animation_blend': 1.}),
    (0, 0x800, 1, None), (0x400, 0, 4, None),
])
def test_zero_fixed_step_requires_reset_or_variable_mode_and_still_obeys_count(flags, flags2, index, expected):
    data = records(flags=flags, flags2=flags2)
    struct.pack_into('<f', data[6], 864, 0.)
    assert substep(data, index) == expected


def test_fixed_clock_uses_strict_float32_minimum_and_guide_duration_threshold():
    data = records()
    minimum_bits = struct.unpack('<I', struct.pack('<f', .0001))[0]
    struct.pack_into('<I', data[6], 864, minimum_bits - 1)
    assert substep(data) is None
    struct.pack_into('<I', data[6], 864, minimum_bits)
    assert substep(data) is not None
    struct.pack_into('<I', data[2], 32, 0x400)
    struct.pack_into('<f', data[6], 864, 0.)
    struct.pack_into('<f', data[6], 880, 0.)
    duration_bits = struct.unpack('<I', struct.pack('<f', .000001))[0]
    struct.pack_into('<I', data[6], 872, duration_bits)
    assert substep(data)['guide_animation_blend'] == 1.
    struct.pack_into('<I', data[6], 872, duration_bits + 1)
    assert substep(data)['guide_animation_blend'] == 0.


def test_guide_blend_uses_execution_plus_previous_remaining_time_and_saturates():
    data = records()
    struct.pack_into('<f', data[6], 872, .125)
    struct.pack_into('<f', data[6], 880, .375)
    assert substep(data, 0)['guide_animation_blend'] == .5  # Not 1 / count.
    assert substep(data, 3)['guide_animation_blend'] == 1.


def test_guide_anchor_uses_character_basis_then_subtracts_frame_translation():
    data = records(particle_flags=0x15)
    for offset, vector in ((0, (0., 1., 0.)), (16, (-1., 0., 0.)), (32, (0., 0., 2.))):
        struct.pack_into('<3f', data[5], offset, *vector)
    struct.pack_into('<3f', data[4], 48, 3., 4., 5.)
    struct.pack_into('<3f', data[2], 0, 10., 20., 30.)
    before = tuple(bytes(record) for record in data)
    output = animate(data)
    assert point(output['particle'], 0) == (-2.75, -4.25, -5.)
    assert not output['space_adjusted']
    allowed = set(range(12)) | set(range(64, 68))
    assert all(output['particle'][i] == before[0][i] for i in range(152) if i not in allowed)
    assert tuple(bytes(record) for record in data) == before


def test_reset_frame_selects_full_anchor_without_enabling_rotation_by_itself():
    data = records(flags=0x400)
    output = animate(data)
    assert point(output['particle'], 0) == (0., 2., 0.)
    assert not output['space_adjusted']
    assert point(output['particle'], 36) == (2., 3., 4.)
    assert point(output['particle'], 140) == (7., 8., 9.)


@pytest.mark.parametrize('skip_integration', [False, True])
def test_first_step_rotation_updates_exactly_one_position_and_zeros_velocity(skip_integration):
    data = records(flags=1, flags2=0x100 if skip_integration else 0)
    output = animate(data)
    particle = output['particle']
    assert output['skip_external_forces'] and output['space_adjusted']
    assert output['integration_skipped'] is skip_integration
    assert point(particle, 0) == (0., 2., 0.)
    assert point(particle, 12) == ((-3., 2., 4.) if skip_integration else (11., 12., 13.))
    assert point(particle, 36) == ((2., 3., 4.) if skip_integration else (-3., 2., 4.))
    assert point(particle, 140) == (0., 0., 0.)
    for start, end in ((24, 36), (48, 60), (72, 140)):
        assert particle[start:end] == data[0][start:end]


def test_later_substep_keeps_velocity_and_positions_while_retaining_skip_decisions():
    data = records(flags=1, flags2=0x100)
    output = animate(data, substep_index=1)
    assert output['skip_external_forces'] and output['integration_skipped']
    assert not output['space_adjusted']
    assert point(output['particle'], 0) == (.75, .5, 0.)
    assert output['particle'][12:] == data[0][12:]


@pytest.mark.parametrize('movement,lra,frame_enabled,scene_enabled,expected', [
    (-30., .5, True, True, False), (-10., .5, True, True, False),
    (-20., .5, True, True, True), (-20., .75, True, True, False),
    (-20., .5, False, True, False), (-20., .5, True, False, False),
])
def test_special_adjustment_has_narrower_window_than_prediction_boost(movement, lra, frame_enabled, scene_enabled, expected):
    data = records(flags=0x20000000 if frame_enabled else 0)
    struct.pack_into('<I', data[3], 64, 0x200 if scene_enabled else 0)
    struct.pack_into('<e', data[2], 62, movement)
    struct.pack_into('<e', data[0], 88, lra)
    result = animate(data)
    assert result['space_adjusted'] is expected
    assert result['skip_external_forces'] is expected
    assert result['integration_skipped'] is expected


def test_old_guide_flag_is_observed_before_fixed_preparation_clears_it():
    data = records(flags2=0x100, particle_flags=0x4000)
    struct.pack_into('<H', data[0], 116, 1)
    struct.pack_into('<I', data[1], 168, 2)
    struct.pack_into('<e', data[1], 266, 98.)
    output = animate(data)
    assert output['dynamic']  # Original 0x4000 vetoes group fixing below99.
    assert output['space_adjusted'] and not output['integration_skipped']
    assert struct.unpack_from('<I', output['particle'], 64)[0] == 0
    assert point(output['particle'], 36) == (-3., 2., 4.)


@pytest.mark.parametrize('gate,inside,underwater', [(False, True, False), (True, False, False), (True, True, True)])
def test_water_gate_overrides_both_skip_modes_and_old_guide_flag(gate, inside, underwater):
    data = records(flags=1, flags2=0x100 | (0x1000 if gate else 0), particle_flags=0x4000)
    output = animate(data, inside_water_volume=inside)
    assert output['underwater'] is underwater
    assert output['space_adjusted'] is not underwater
    assert output['skip_external_forces'] is not underwater
    assert not output['integration_skipped']


@pytest.mark.parametrize('previous,current,expected', [
    ((0., 0., 0.), (0., 2., 0.), (2., 3., 4.)),
    ((1., 0., 0.), (0., 0., 0.), (2., 3., 4.)),
    ((1., 0., 0.), (-1., 0., 0.), (-2., -3., -4.)),
])
def test_short_anchor_and_antiparallel_fallbacks_still_clear_velocity(previous, current, expected):
    data = records(flags=1)
    struct.pack_into('<3f', data[0], 128, *previous)
    struct.pack_into('<3f', data[4], 48, *current)
    output = animate(data)['particle']
    assert point(output, 36) == expected
    assert point(output, 140) == (0., 0., 0.)


def test_near_antiparallel_branch_uses_decoded_cosine_cutoff():
    data = records(flags=1)
    for cosine, reflected in ((-.99995, True), (-.9998, False)):
        sine = math.sqrt(1 - cosine*cosine)
        struct.pack_into('<3f', data[4], 48, cosine, sine, 0.)
        output = point(animate(data)['particle'], 36)
        expected = (-2., -3., -4.) if reflected else (2*cosine - 3*sine, 2*sine + 3*cosine, 4.)
        assert output == pytest.approx(expected, abs=.00001)


@pytest.mark.parametrize('flags,mass,particle_flags,branch', [
    (0x400, 0., 0x40, 'early_return'), (0x800, float('nan'), 0, 'early_return'),
    (0, 0., 0, 'fixed'), (0, -1., 0, 'fixed'), (0, 1., 0x40, 'fixed'),
    (0, 1., 0, 'dynamic'),
])
def test_integration_selection_prioritizes_early_return_and_keeps_fixed_velocity(flags, mass, particle_flags, branch):
    particle, _, frame, *_ = records(flags=flags, particle_flags=particle_flags, inverse_mass=mass)
    before = bytes(particle)
    output = select_cloth_base_integration(particle, frame)
    assert output['branch'] == branch
    expected = before[:12] + before[:12]*2 + before[36:] if branch == 'fixed' else before
    assert output['particle'] == expected
    assert bytes(particle) == before


def test_clock_animation_force_and_prediction_compose_without_reset_motion_impulse():
    data = records(flags=1)
    timing = substep(data)
    prepared = animate(data, animation_blend=timing['guide_animation_blend'])
    selected = select_cloth_base_integration(prepared['particle'], data[2])
    assert selected['branch'] == 'dynamic'
    forces = integrate_cloth_forces(
        point(selected['particle'], 140), gravity_direction=(0., -1., 0.), gravity=-4.,
        delta_time=timing['delta_time'], inverse_mass=1., underwater=prepared['underwater'],
        underwater_density=1., bone_acceleration=(100., 200., 300.), inertial_scale=1.,
        inertial_acceleration_limit=10., environmental_acceleration=(7., 8., 9.),
        skip_external_forces=prepared['skip_external_forces'])
    output = predict_dynamic_cloth_state(
        selected['particle'], data[1], data[2], data[3], forces['velocity'],
        delta_time=timing['delta_time'], integration_skipped=prepared['integration_skipped'],
        storage_variant='native16')['particle']
    assert point(output, 12) == (-3., 1.75, 4.)
    assert point(output, 140) == (0., -1., 0.)


def test_missing_records_invalid_modes_and_nonfinite_consumed_inputs_are_rejected():
    data = records()
    with pytest.raises(ValueError, match='1216-byte'):
        select_cloth_base_substep(data[2], data[3], data[6][:-1], substep_index=0)
    with pytest.raises(ValueError, match='unsigned 32-bit'):
        substep(data, True)
    with pytest.raises(ValueError, match='explicit booleans'):
        animate(data, inside_water_volume=1)
    with pytest.raises(ValueError, match='ratio'):
        animate(data, animation_blend=1.1)
    with pytest.raises(ValueError, match='finite'):
        animate(data, animation_blend=float('nan'))
    struct.pack_into('<H', data[1], 216, 0)
    with pytest.raises(ValueError, match='guide-mesh'):
        animate(data)
    struct.pack_into('<e', data[3], 94, -1.)
    with pytest.raises(ValueError, match='nonnegative'):
        substep(data)
