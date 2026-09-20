"""Owned analytic scenarios for decoded base-step force and damping behavior."""

import math
import struct

import pytest

from cdmw.modding.pac_cloth_base import (
    apply_cloth_damping, cloth_contact_velocity_response, decode_cloth_force_parameters,
    integrate_cloth_forces, predict_cloth_position,
)
from cdmw.modding.pac_cloth_constraints import cloth_stretch_corrections
from cdmw.modding.pac_cloth_movement import finalize_cloth_motion


def records(*, flags=0, overrides=None, index=0xFFFF):
    particle, frame, scene, parameter = bytearray(152), bytearray(100), bytearray(108), bytearray(312)
    struct.pack_into('<3f', particle, 36, 2., 0., 0.)
    struct.pack_into('<3f', particle, 140, 2., 3., 4.)
    struct.pack_into('<I', frame, 32, flags)
    struct.pack_into('<e', frame, 54, 100.)
    struct.pack_into('<H', frame, 74, index)
    struct.pack_into('<e', scene, 82, -4.)
    struct.pack_into('<e', scene, 94, 1.)
    struct.pack_into('<4e', parameter, 256, 3., 25., -10., 2.)
    extra = None
    if overrides is not None:
        extra = bytearray(28)
        struct.pack_into('<2e', extra, 16, *overrides)
    return particle, frame, scene, parameter, extra


def forces(**changes):
    arguments = dict(velocity=(1, 2, 3), gravity_direction=(0, -1, 0), gravity=-10., delta_time=.5,
                     inverse_mass=1., underwater=False, underwater_density=2., bone_acceleration=(0, 0, 0),
                     inertial_scale=1., inertial_acceleration_limit=5., environmental_acceleration=(0, 0, 0),
                     skip_external_forces=False)
    arguments.update(changes)
    return integrate_cloth_forces(**arguments)


def damping(*, flags=0, index=0xFFFF, value=2., additional=2., group=None):
    particle, frame, _, _, _ = records(flags=flags, index=index)
    return apply_cloth_damping((12, 23, 34), particle=particle, per_frame=frame, damping=value,
                              additional_horizontal_damping=additional, advanced_damping=group)


@pytest.mark.parametrize('flags,overrides,expected', [
    (0, None, (-8., 3.)), (0, (1., -1.), (-8., 3.)), (0, (42., 0.), (-8., 0.)),
    (0, (0., .5), (0., .5)), (0, (-1., -1.), (-1., 3.)),
    (0x4000000, None, (-2., 3.)), (0x4000000, (-3., 4.), (-3., 4.)),
])
def test_gravity_and_damping_have_distinct_override_sentinels(flags, overrides, expected):
    _, frame, scene, parameter, extra = records(flags=flags, overrides=overrides)
    assert decode_cloth_force_parameters(parameter, frame, scene, extra) == expected


@pytest.mark.parametrize('water,mass,expected', [
    (False, 1., (1., -3., 3.)), (True, 1., (1., -.5, 3.)),
    (True, 2., (1., 2., 3.)), (True, 4., (1., 7., 3.)),
])
def test_gravity_and_buoyancy_use_direction_density_and_inverse_mass(water, mass, expected):
    assert forces(underwater=water, inverse_mass=mass)['velocity'] == pytest.approx(expected)


def test_gravity_direction_is_not_normalized_and_buoyancy_only_changes_y():
    assert forces(gravity_direction=(0, -2, 0))['velocity'] == (1., -8., 3.)
    assert forces(gravity_direction=(2, 0, 0), underwater=True)['velocity'] == (11., 2., 3.)


def test_bone_inertia_is_scaled_and_capped_before_environment_is_added():
    result = forces(bone_acceleration=(6, 8, 0), inertial_scale=2., environmental_acceleration=(1, 2, 3))
    assert result['non_gravity_acceleration'] == pytest.approx((4., 6., 3.))
    assert result['velocity'] == pytest.approx((3., 0., 4.5))


def test_external_skip_preserves_gravity_and_buoyancy():
    result = forces(underwater=True, bone_acceleration=(6, 8, 0), environmental_acceleration=(100, 200, 300),
                    skip_external_forces=True)
    assert result['non_gravity_acceleration'] == (0., 0., 0.)
    assert result['velocity'] == (1., -.5, 3.)


def test_ordinary_damping_is_per_step_with_optional_horizontal_addition():
    assert damping() == pytest.approx((9.6, 18.4, 27.2))
    assert damping(flags=0x2000000) == pytest.approx((7.2, 18.4, 20.4))
    assert damping(value=12.) == pytest.approx((-2.4, -4.6, -6.8))  # No invented coefficient clamp.


def test_advanced_damping_uses_old_velocity_and_rigid_group_angular_motion():
    group = struct.pack('<9f', 1, 0, 0, 10, 20, 30, 0, 0, 2)
    # Old x=(2,0,0), v=(2,3,4). Group target velocity=(10,22,30).
    # New forces are retained: (12,23,34) + .2*(target - OLD velocity).
    assert damping(flags=4, index=7, group=group) == pytest.approx((13.6, 26.8, 39.2))
    assert damping(flags=0x2000004, index=7, group=group) == pytest.approx((15.2, 26.8, 44.4))
    assert damping(flags=4, group=None) == pytest.approx((9.6, 18.4, 27.2))  # FFFF disables the path.
    assert damping(index=7, group=None) == pytest.approx((9.6, 18.4, 27.2))  # Flag also required.


def test_advanced_damping_is_translation_invariant_and_does_not_mutate_records():
    particle, frame, _, _, _ = records(flags=4, index=7)
    group = bytearray(struct.pack('<9f', 1, 0, 0, 10, 20, 30, 0, 0, 2))
    struct.pack_into('<3f', particle, 36, 102., -25., 8.)
    struct.pack_into('<3f', group, 0, 101., -25., 8.)
    before = bytes(particle), bytes(frame), bytes(group)
    result = apply_cloth_damping((12, 23, 34), particle=particle, per_frame=frame, damping=2.,
                                additional_horizontal_damping=0., advanced_damping=group)
    assert result == pytest.approx((13.6, 26.8, 39.2))
    assert (bytes(particle), bytes(frame), bytes(group)) == before


@pytest.mark.parametrize('velocity,expected', [
    ((3, -4, 5), (2.25, 2., 3.75)), ((3, 4, 5), (3., 4., 5.)), ((3, 0, 5), (3., 0., 5.)),
])
def test_contact_response_only_changes_inward_velocity(velocity, expected):
    assert cloth_contact_velocity_response(velocity, normal=(0, -1, 0), friction=.25,
                                           restitution=.5) == pytest.approx(expected)


def test_contact_response_preserves_supplied_normal_length():
    assert cloth_contact_velocity_response((0, -4, 0), normal=(0, -2, 0), friction=.5,
                                           restitution=.25) == (0., 10., 0.)


@pytest.mark.parametrize('enabled,y,expected,contact', [
    (True, 3., 1.5, True), (True, 6., 3., False), (False, 3., 0., False),
    (False, -1997., -1000., True),
])
def test_position_prediction_and_ground_plane_include_disabled_branch_limit(enabled, y, expected, contact):
    result = predict_cloth_position((0, y, 0), (0, -6, 0), delta_time=.5, gravity_direction=(0, -1, 0),
                                    ground_height=1., ground_thickness=.5, ground_collision_enabled=enabled)
    assert result == {'position': (0., expected, 0.), 'ground_contact': contact}


def test_ground_projection_follows_gravity_direction_instead_of_world_y():
    result = predict_cloth_position((0, 3, 0), (0, 0, 0), delta_time=.5, gravity_direction=(1, 0, 0),
                                    ground_height=1., ground_thickness=.5, ground_collision_enabled=True)
    assert result == {'position': (-1.5, 3., 0.), 'ground_contact': True}


def test_base_prediction_stretch_and_final_step_keep_an_authored_length():
    particle, frame, scene, parameter, _ = records()
    old = (1., 0., 0.)
    velocity = forces(velocity=(0, 0, 0), delta_time=.1)['velocity']
    predicted = predict_cloth_position(old, velocity, delta_time=.1, gravity_direction=(0, -1, 0),
                                      ground_height=-10., ground_thickness=0., ground_collision_enabled=True)
    corrections = cloth_stretch_corrections(
        ((0, 0, 0), predicted['position']), animation_positions=((0, 0, 0), old), inverse_masses=(0, 1),
        lra_ratios=(0, 1), stiffness=(1, 1), reference_length=1., uploaded_inverse_mass_sum=1., bone_scale=1.,
        stretching_scale=1., length_smoothing_byte=0, follow_the_leader_ratio=0., per_frame_flags=0,
        particle_flags=(0, 0), particle_extra_flags=(0, 0))
    constrained = tuple(x + d for x, d in zip(predicted['position'], corrections[1]))
    result = finalize_cloth_motion(
        constrained, animation_position=old, previous_position=old, velocity_reference_position=old,
        attachment_correction=(0, 0, 0), animation_blend=0., inverse_mass=1., particle_flags=0,
        per_frame=frame, per_scene=scene, simulation_parameter=parameter, fixed_substep_delta_time=.1,
        variable_substep_delta_time=.1, minimum_velocity_delta_time=.01)
    length = math.sqrt(1.01)
    assert result['position'] == pytest.approx((1/length, -.1/length, 0.))
    assert result['velocity'] == pytest.approx(((1/length-1)/.1, -1/length, 0.))


def test_repeated_base_and_final_steps_match_independent_damped_freefall_series():
    particle, frame, scene, parameter, _ = records()
    p, v = (0., 20., 0.), (0., 2., 0.)
    q, dt, steps = 1. - 3. * .10000000149011612, .1, 20
    for _ in range(steps):
        after_forces = forces(velocity=v, delta_time=dt)['velocity']
        damped = apply_cloth_damping(after_forces, particle=particle, per_frame=frame, damping=3.,
                                    additional_horizontal_damping=0., advanced_damping=None)
        predicted = predict_cloth_position(p, damped, delta_time=dt, gravity_direction=(0, -1, 0),
                                          ground_height=0., ground_thickness=0., ground_collision_enabled=False)
        result = finalize_cloth_motion(
            predicted['position'], animation_position=p, previous_position=p, velocity_reference_position=p,
            attachment_correction=(0, 0, 0), animation_blend=0., inverse_mass=1., particle_flags=0,
            per_frame=frame, per_scene=scene, simulation_parameter=parameter, fixed_substep_delta_time=dt,
            variable_substep_delta_time=dt, minimum_velocity_delta_time=.01)
        p, v = result['position'], result['velocity']
    geometric_sum = q * (1. - q**steps) / (1. - q)
    expected_v = q**steps * 2. + q * (-10.) * dt * (1. - q**steps) / (1. - q)
    expected_p = 20. + dt * (2. * geometric_sum + q * (-10.) * dt / (1. - q) * (steps - geometric_sum))
    assert v == pytest.approx((0., expected_v, 0.))
    assert p == pytest.approx((0., expected_p, 0.))


@pytest.mark.parametrize('changes', [
    {'underwater': True, 'underwater_density': 0.}, {'inertial_acceleration_limit': 0.},
    {'environmental_acceleration': (float('inf'), 0, 0)}, {'delta_time': -.1},
])
def test_invalid_force_inputs_are_rejected(changes):
    with pytest.raises(ValueError):
        forces(**changes)


def test_active_damping_requires_a_valid_group_record_and_finite_data():
    with pytest.raises(ValueError, match='referenced'):
        damping(flags=4, index=0, group=None)
    with pytest.raises(ValueError, match='36-byte'):
        damping(flags=4, index=0, group=bytes(35))
    with pytest.raises(ValueError, match='finite'):
        damping(value=float('nan'))


def test_force_record_decoder_rejects_truncation_and_nonfinite_overrides():
    _, frame, scene, parameter, extra = records(overrides=(float('nan'), -1.))
    with pytest.raises(ValueError, match='finite'):
        decode_cloth_force_parameters(parameter, frame, scene, extra)
    with pytest.raises(ValueError, match='312-byte'):
        decode_cloth_force_parameters(parameter[:-1], frame, scene, None)
