"""Analytic final-movement scenarios using owned geometry/runtime records."""

import struct

import pytest

from cdmw.modding.pac_cloth_constraints import cloth_stretch_corrections
from cdmw.modding.pac_cloth_frames import select_guide_result_positions
from cdmw.modding.pac_cloth_movement import (
    cloth_attachment_correction, finalize_cloth_motion, guide_final_input_blend,
)
from cdmw.modding.pac_cloth_preparation import prepare_guide_cloth_attachments
from tests.test_pac_cloth_attachments import guides_with


def records(*, flags=0, flags2=0, scene_flags=0, state=0, blend=.5, override=None,
            scale=1., timer=0., speed_limit=10., time_scale=1., friction=.5,
            bone_velocity=(0., 0., 0.), front=(0., 0., 1.), push_back=0.):
    particle, frame, scene, parameter = bytearray(152), bytearray(100), bytearray(108), bytearray(312)
    struct.pack_into('<I', particle, 64, state)
    struct.pack_into('<e', particle, 90, 1. - blend)  # _cr is a separate channel.
    struct.pack_into('<e', particle, 94, blend)
    struct.pack_into('<f', particle, 120, timer)
    struct.pack_into('<2I', frame, 32, flags, flags2)
    struct.pack_into('<2e', frame, 44, scale, push_back)
    struct.pack_into('<e', frame, 54, speed_limit)
    struct.pack_into('<3e', frame, 56, *bone_velocity)
    struct.pack_into('<I', scene, 64, scene_flags)
    struct.pack_into('<3e', scene, 86, *front)
    struct.pack_into('<e', scene, 94, time_scale)
    struct.pack_into('<e', parameter, 254, friction)
    extra = None
    if override is not None:
        extra = bytearray(28)
        struct.pack_into('<e', extra, 6, override)
    return particle, frame, scene, parameter, extra


def attachments(**changes):
    arguments = dict(position=(3, 0, 0), animation_position=(1, 0, 0),
                     anchor_indices=(0,), anchor_rest_lengths=(1.,), particle_positions=((0, 0, 0),),
                     animation_positions=((0, 0, 0),), inverse_masses=(0.,), particle_flags=(0,),
                     bone_scale=1., stretching_scale=1., per_frame_flags=0x80, current_particle_flags=0)
    arguments.update(changes)
    return cloth_attachment_correction(**arguments)


def final_blend(*, enabled=True, **settings):
    particle, frame, scene, _, extra = records(**settings)
    return guide_final_input_blend(particle, frame, scene, extra, use_input_position_blending=enabled)


def motion(*, settings=None, **changes):
    _, frame, scene, parameter, _ = records(**(settings or {}))
    arguments = dict(position=(3, 4, 0), animation_position=(0, 0, 0), previous_position=(99, 0, 0),
                     velocity_reference_position=(0, 0, 0), attachment_correction=(0, 0, 0),
                     animation_blend=0., inverse_mass=1., particle_flags=0, per_frame=frame,
                     per_scene=scene, simulation_parameter=parameter, fixed_substep_delta_time=.1,
                     variable_substep_delta_time=.2, minimum_velocity_delta_time=.01)
    arguments.update(changes)
    return finalize_cloth_motion(**arguments)


def test_attachment_corrections_average_only_violations_from_one_input_position():
    inputs = dict(anchor_indices=(0, 1, 2), anchor_rest_lengths=(1., 1., 10.),
                  particle_positions=((0, 0, 0), (5, 0, 0), (3, 0, 0)),
                  animation_positions=((0, 0, 0), (5, 0, 0), (3, 0, 0)),
                  inverse_masses=(0, 0, 0), particle_flags=(0, 0, 0))
    # Radii 1.1: corrections -1.9 and +.9 average to -.5. The satisfied
    # third anchor is not part of the divisor, and reversing order is harmless.
    assert attachments(**inputs) == pytest.approx((-.5, 0, 0))
    inputs.update(anchor_indices=(2, 1, 0), anchor_rest_lengths=(10., 1., 1.))
    assert attachments(**inputs) == pytest.approx((-.5, 0, 0))


@pytest.mark.parametrize('changes,expected', [
    ({}, (-1.9, 0, 0)), ({'per_frame_flags': 0}, (0, 0, 0)),
    ({'current_particle_flags': 0x40}, (0, 0, 0)),
    ({'inverse_masses': (1e-8,)}, (0, 0, 0)),
    ({'inverse_masses': (1.,), 'particle_flags': (0x40,)}, (-1.9, 0, 0)),
    ({'anchor_indices': (0xFFFF,)}, (0, 0, 0)),
    ({'position': (0, 0, 0), 'anchor_rest_lengths': (0.,)}, (0, 0, 0)),
])
def test_attachment_runtime_gates_and_invalid_anchor_sentinel(changes, expected):
    assert attachments(**changes) == pytest.approx(expected)


def test_attachment_animation_expansion_precedes_stretch_scale():
    inputs = dict(position=(4, 0, 0), animation_position=(4, 0, 0), bone_scale=2., stretching_scale=.5)
    assert attachments(**inputs) == pytest.approx((-2.9, 0, 0))
    assert attachments(**inputs, per_frame_flags=0x800080) == pytest.approx((-1.8, 0, 0))


@pytest.mark.parametrize('settings,expected', [
    ({'blend': .5}, 0.), ({'blend': .99853515625}, 0.),
    ({'blend': .9990234375}, .9990234375), ({'blend': 1., 'scale': 0.}, 1.),
    ({'blend': .5, 'scale': 2.}, 1.), ({'blend': .5, 'scale': 1.5}, 0.),
    ({'blend': 1., 'override': 0.}, 0.), ({'blend': .5, 'override': 1.}, 1.),
    ({'blend': 1., 'override': -1.}, 1.),
])
def test_final_blend_uses_half94_override_and_strict_near_one_threshold(settings, expected):
    assert final_blend(**settings) == expected


def test_underwater_power_requires_both_bits_and_follows_threshold():
    inputs = dict(blend=.99951171875)
    assert final_blend(**inputs, flags2=0x800000, state=0x80) == pytest.approx(.99951171875**5)
    assert final_blend(**inputs, flags2=0x800000) == .99951171875
    assert final_blend(**inputs, state=0x80) == .99951171875
    assert final_blend(blend=.5, flags2=0x800000, state=0x80) == 0.


@pytest.mark.parametrize('settings,expected', [
    ({'state': 0x40}, 1.), ({'state': 0x100}, 1.), ({'state': 0x200}, 1.),
    ({'blend': 1., 'state': 0x100000}, 0.),
    ({'state': 0x200000, 'flags': 1}, 1.),
    ({'state': 0x200000, 'flags': 1, 'flags2': 0x80}, 0.),
    ({'state': 0x200040}, 1.),
    ({'state': 0x40, 'flags2': 0x80, 'scene_flags': 0x4000}, 0.),
    ({'state': 0x40, 'scene_flags': 0x4000}, 1.),
])
def test_final_blend_state_overrides_and_global_gates(settings, expected):
    assert final_blend(**settings) == expected
    assert final_blend(enabled=False, **settings) == 0.


@pytest.mark.parametrize('timer,expected', [
    (99999., 0.), (100000., 1.), (100001., 1.), (100002.5, .5), (100004., 0.),
])
def test_pinch_timer_sentinel_window_and_three_unit_recovery(timer, expected):
    assert final_blend(timer=timer) == pytest.approx(expected)


def test_velocity_uses_distinct_reference_and_preserves_direction_at_speed_cap():
    result = motion()
    assert result['position'] == (3., 4., 0.)
    assert result['velocity'] == pytest.approx((6., 8., 0.))
    assert result['previous_position'] == (99., 0., 0.)
    assert motion(particle_flags=4)['velocity'] == pytest.approx((.6, .8, 0.))


@pytest.mark.parametrize('flags2,scale,minimum,expected', [
    (0, 2., .5, 1.), (0x800, 2., .5, 2.), (0, 0., .25, 4.),
])
def test_clock_selection_scene_scale_and_minimum_velocity_dt(flags2, scale, minimum, expected):
    result = motion(position=(1, 0, 0), fixed_substep_delta_time=.5, variable_substep_delta_time=.125,
                    minimum_velocity_delta_time=minimum, settings={'flags2': flags2, 'time_scale': scale})
    assert result['velocity'] == pytest.approx((expected, 0, 0))


def test_attachment_velocity_removal_precedes_animation_blend():
    inputs = dict(position=(3, 0, 0), animation_position=(10, 0, 0), attachment_correction=(-1, 0, 0),
                  animation_blend=.5, fixed_substep_delta_time=1.)
    regular = motion(**inputs)
    removed = motion(**inputs, settings={'flags2': 0x40})
    assert regular['position'] == removed['position'] == (6., 0., 0.)
    assert regular['velocity'] == (6., 0., 0.)
    assert removed['velocity_reference_position'] == (-1., 0., 0.)
    assert removed['velocity'] == (7., 0., 0.)


@pytest.mark.parametrize('settings,mass,expected_history,expected_velocity', [
    ({'flags': 1}, 1., (3., 4., 0.), (0., 0., 0.)),
    ({'flags': 1, 'flags2': 0x100}, 1., (99., 0., 0.), (0., 0., 0.)),
    ({'flags': 1, 'flags2': 0x80}, 1., (99., 0., 0.), (6., 8., 0.)),
    ({}, .00005, (99., 0., 0.), (0., 0., 0.)),
])
def test_velocity_suppression_and_history_selection(settings, mass, expected_history, expected_velocity):
    result = motion(settings=settings, inverse_mass=mass)
    assert result['previous_position'] == expected_history
    assert result['velocity'] == pytest.approx(expected_velocity)


def test_ground_response_follows_cap_and_uses_bone_relative_horizontal_motion():
    inputs = dict(bone_velocity=(4, 50, 8), push_back=3.)
    # Capped (6,8,0), plus bone motion (4,8), halves to (5,4), minus bone
    # motion gives (1,-4). Horizontal front push adds (0,-3); Y is cleared.
    result = motion(settings=inputs, particle_flags=2)
    assert result['velocity'] == pytest.approx((1., 0., -7.))
    inputs['front'] = (0, .125, 1)
    assert motion(settings=inputs, particle_flags=2)['velocity'] == pytest.approx((1., 0., -4.))


def test_ground_response_can_reintroduce_motion_after_suppression_and_exceed_cap():
    result = motion(inverse_mass=0., particle_flags=2,
                    settings={'speed_limit': 1., 'bone_velocity': (40, 0, 0)})
    assert result['velocity'] == (-20., 0., 0.)


def test_prepared_anchor_and_stretch_feed_final_motion_then_result_interpolation():
    animated = ((0., 0., 0.), (1., 0., 0.), (0., 1., 0.))
    guides = guides_with(animated, fixed=(0,))
    prepared = prepare_guide_cloth_attachments(guides, separate_components=False,
                                              use_vertex_alpha_position_blending=True,
                                              auto_weighting_enabled=False)
    delta = cloth_stretch_corrections(
        ((0, 0, 0), (2, 0, 0)), animation_positions=animated[:2], inverse_masses=(0, 1),
        lra_ratios=(0, 1), stiffness=(.5, .5), reference_length=1., uploaded_inverse_mass_sum=1.,
        bone_scale=1., stretching_scale=1., length_smoothing_byte=0, follow_the_leader_ratio=0.,
        per_frame_flags=0, particle_flags=(0, 0), particle_extra_flags=(0, 0))
    selected = (2 + delta[1][0], 0., 0.)
    correction = cloth_attachment_correction(
        selected, animation_position=animated[1], anchor_indices=prepared['anchor_indices'][1],
        anchor_rest_lengths=prepared['anchor_rest_lengths'][1],
        particle_positions=(animated[0], (2, 0, 0), animated[2]),
        animation_positions=animated, inverse_masses=(0, 1, 1), particle_flags=(0, 0, 0), bone_scale=1.,
        stretching_scale=1., per_frame_flags=0x80, current_particle_flags=0)
    particle, frame, scene, parameter, extra = records(flags=0x80, flags2=0x40,
                                                       blend=prepared['position_blends'][1])
    snapshots = tuple(bytes(x) for x in (particle, frame, scene, parameter))
    blend = guide_final_input_blend(particle, frame, scene, extra, use_input_position_blending=True)
    result = finalize_cloth_motion(
        selected, animation_position=animated[1], previous_position=animated[1],
        velocity_reference_position=animated[1], attachment_correction=correction,
        animation_blend=blend, inverse_mass=1., particle_flags=0, per_frame=frame, per_scene=scene,
        simulation_parameter=parameter, fixed_substep_delta_time=1., variable_substep_delta_time=1.,
        minimum_velocity_delta_time=.01)
    assert result['position'] == pytest.approx((1.1, 0, 0))
    assert result['velocity'] == pytest.approx((.5, 0, 0))
    interpolated = select_guide_result_positions(
        (animated[1],), (result['previous_position'],), (result['position'],),
        per_frame_flags2=0, interpolation_ratio=.5, animation_blend=0.)
    assert interpolated[0] == pytest.approx((1.05, 0, 0))
    assert tuple(bytes(x) for x in (particle, frame, scene, parameter)) == snapshots


@pytest.mark.parametrize('changes', [
    {'anchor_indices': (-1,)}, {'anchor_rest_lengths': (float('nan'),)},
    {'anchor_indices': (0, 0, 0, 0, 0), 'anchor_rest_lengths': (1.,) * 5},
    {'animation_positions': ()}, {'per_frame_flags': -1},
])
def test_invalid_attachment_inputs_are_rejected(changes):
    with pytest.raises(ValueError):
        attachments(**changes)


@pytest.mark.parametrize('changes', [
    {'settings': {'flags': 0x400}}, {'settings': {'flags': 0x800}}, {'particle_flags': 0x80004},
    {'fixed_substep_delta_time': 0., 'minimum_velocity_delta_time': 0.},
    {'settings': {'speed_limit': 0.}}, {'animation_blend': float('nan')}, {'per_scene': bytes(107)},
])
def test_unsupported_movement_inputs_are_rejected_without_fabricating_state(changes):
    with pytest.raises(ValueError):
        motion(**changes)


def test_blend_record_validation():
    particle, frame, scene, _, extra = records()
    with pytest.raises(ValueError, match='28-byte'):
        guide_final_input_blend(particle, frame, scene, bytes(27), use_input_position_blending=True)
    with pytest.raises(ValueError, match='finite'):
        struct.pack_into('<e', particle, 94, float('nan'))
        guide_final_input_blend(particle, frame, scene, extra, use_input_position_blending=True)
