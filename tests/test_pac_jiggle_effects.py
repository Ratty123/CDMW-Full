"""Command-to-effect transitions, fading and the two angular solver paths."""

import math
import struct

import pytest

from cdmw.modding.pac_jiggle_bones import prepare_jiggle_command
from tests.test_pac_jiggle_bones import IDENTITY, assert_matrix, character, matrix, rotated, run, shader, state, vector


EPSILON = 9.999999747378752e-05


def command(*, velocity=(0, 0, 0), angular_velocity=(0, 0, 0), weight=1., duration=2.,
            fade_range=.5, mode=4, packed_skeleton=0, bone_index=0):
    result = bytearray(48)
    struct.pack_into('<9f3I', result, 0, *velocity, *angular_velocity, weight, duration, fade_range,
                     mode, packed_skeleton, bone_index)
    return result


def trigger(**values):
    return prepare_jiggle_command(command(**values), skeleton_data=bytes(124),
                                  object_data=bytes(128), shader_data=shader())['bone']


def continuing(*, elapsed=0., axis=(0, 0, 0), angle=0., flags=1, motion=None, **effect):
    result = state(flags=flags) if motion is None else bytearray(motion)
    result[48:88] = command(**effect)[:40]
    struct.pack_into('<5fI', result, 88, *axis, angle, elapsed, flags)
    return result


def tail(result):
    return struct.unpack_from('<5fII', result['bone'], 88)


def test_command_copies_exact_payload_into_a_cleared_record_and_uses_lod0_offset():
    payload = command(velocity=(1, 2, 3), angular_velocity=(4, 5, 6), weight=.7,
                      duration=3, fade_range=.4, mode=14, bone_index=6, packed_skeleton=0x20009)
    skeleton, obj, data = bytearray(124), bytearray(128), shader()
    struct.pack_into('<2I', skeleton, 32, 7, 99)
    struct.pack_into('<I', obj, 0, 0x101)  # LOD1 plus an unrelated high-byte flag.
    struct.pack_into('<I', data, 12, 20)
    result = prepare_jiggle_command(payload, skeleton_data=skeleton, object_data=obj, shader_data=data)
    assert result['state_index'] == 33
    assert result['bone'][:48] == bytes(48)
    assert result['bone'][48:88] == payload[:40]
    assert result['bone'][88:108] == bytes(20)
    assert struct.unpack_from('<2I', result['bone'], 108) == (3, 0)


@pytest.mark.parametrize('lod,shader_offset', [(2, 0), (255, 0), (1, 0xFFFFFFFF)])
def test_ineligible_commands_skip_without_resolving_shader_data(lod, shader_offset):
    obj = bytearray(128)
    struct.pack_into('<I', obj, 0, lod)
    struct.pack_into('<I', obj, 84, shader_offset)
    assert prepare_jiggle_command(command(), skeleton_data=bytes(124), object_data=obj,
                                   shader_data=None) is None


def test_command_address_wraps_u32_and_eligible_missing_resource_is_explicit():
    data = shader()
    struct.pack_into('<I', data, 12, 0xFFFFFFFE)
    result = prepare_jiggle_command(command(bone_index=5), skeleton_data=bytes(124),
                                    object_data=bytes(128), shader_data=data)
    assert result['state_index'] == 3
    with pytest.raises(ValueError, match='resolved shader data'):
        prepare_jiggle_command(command(), skeleton_data=bytes(124), object_data=bytes(128), shader_data=None)


def test_linear_impulse_is_added_once_and_pre_fade_restores_stored_velocity():
    settings = shader(settings=(0, .5, 100, 100, 0, 1, 100, 100), flags=1)
    first = run(state(v=(1, 0, 0)), command_bone=trigger(velocity=(3, 0, 0)), shader_data=settings)
    assert vector(first, 0) == (.5, 0, 0)  # Integrates damped velocity2.
    assert vector(first, 12) == (4, 0, 0)  # Stores velocity2 / damping0.5.
    assert tail(first)[-2:] == (1, 1)  # Pending bit is cleared.
    second = run(first['bone'], update_frame_index=2, shader_data=settings)
    assert vector(second, 0) == (1, 0, 0)
    assert vector(second, 12) == (4, 0, 0)  # No second +3 impulse.
    assert tail(second)[4] == .5
    assert second['matrix'][1][3] == 1


def test_pre_fade_velocity_division_occurs_after_speed_and_displacement_limits():
    result = run(state(), command_bone=trigger(velocity=(10, 0, 0)),
                 shader_data=shader(settings=(0, .5, 1, .1, 0, 1, 1, 1)))
    assert vector(result, 0) == pytest.approx((.1, 0, 0))
    assert vector(result, 12) == (2, 0, 0)  # Can exceed maxLinearSpeed=1.


def test_fading_damps_velocity_and_changes_output_weight_without_rewriting_authored_weight():
    old = continuing(motion=state(v=(4, 0, 0)), weight=2., duration=1., fade_range=1.)
    result = run(old, shader_data=shader(settings=(0, .5, 100, 100, 0, 1, 100, 100), flags=1))
    assert vector(result, 0) == (.5, 0, 0)
    assert vector(result, 12) == (2, 0, 0)
    assert result['matrix'][1][3] == 1.5
    assert struct.unpack_from('<f', result['bone'], 72)[0] == 2.


@pytest.mark.parametrize('fade_range', [0., -1.])
def test_nonpositive_fade_range_skips_fading_but_duration_still_expires(fade_range):
    first = run(state(), command_bone=trigger(velocity=(4, 0, 0), duration=.25, fade_range=fade_range, weight=.75),
                shader_data=shader(flags=1))
    assert vector(first, 12) == (4, 0, 0)
    assert first['matrix'][1][3] == .75
    assert tail(first)[-2] == 0
    second = run(first['bone'], shader_data=shader(flags=1), update_frame_index=2)
    assert vector(second, 0) == (2, 0, 0)
    assert second['matrix'][1][3] == 0.
    assert tail(second)[4] == .25  # Ordinary path does not advance effect time.


@pytest.mark.parametrize('dt,expected_speed', [(EPSILON / 2, 4.), (EPSILON, 2.)])
def test_pre_fade_threshold_is_strict(dt, expected_speed):
    old = continuing(motion=state(v=(4, 0, 0)), duration=1., fade_range=1.)
    result = run(old, delta_time=dt, shader_data=shader(settings=(0, .5, 100, 100, 0, 1, 100, 100)))
    assert vector(result, 12)[0] == expected_speed


def test_small_weight_restores_animation_before_a_later_bone_mask_override():
    source = IDENTITY[:2] + ((0, 0, 1, .4), (10, 0, 0, .5))
    result = run(continuing(motion=state(p=(3, 0, 0), v=(4, 0, 0)), weight=EPSILON / 2),
                 animation_matrix=matrix(source), shader_data=shader(flags=2, masks=((0, 1.),)))
    assert vector(result, 0) == (10, 0, 0)
    assert vector(result, 12) == (0, 0, 0)
    assert tail(result)[-2] == 1  # Low weight is not the expiration condition.
    assert_matrix(result['matrix'], (source[0][:3] + (1.,), source[1][:3] + (1.,), *source[2:]))


def test_weight_exactly_at_cutoff_reconstructs_instead_of_passing_through_metadata():
    source = IDENTITY[:2] + ((0, 0, 1, .4), (0, 0, 0, .5))
    result = run(continuing(mode=0, weight=EPSILON), animation_matrix=matrix(source), shader_data=shader(flags=1))
    assert result['matrix'][1][3] == EPSILON
    assert result['matrix'][2][3] == 0.
    assert result['matrix'][3][3] == 1.


def test_disabled_effect_components_snap_pose_but_retain_continuing_velocities():
    old = continuing(mode=0, motion=state(p=(2, 0, 0), v=(3, 0, 0), r=(.2, 0, 0), rv=(4, 0, 0)))
    result = run(old)
    assert vector(result, 0) == vector(result, 24) == (0, 0, 0)
    assert vector(result, 12) == (3, 0, 0)
    assert vector(result, 36) == (4, 0, 0)


def test_new_command_overrides_instance_data_but_reads_runtime_axis_from_previous_state():
    old = continuing(mode=10, elapsed=1.5, axis=(0, 1, 0), angle=.4, weight=.1, flags=0x11)
    current = trigger(mode=0, duration=3., weight=.8)
    result = run(old, command_bone=current)
    assert result['bone'][48:88] == current[48:88]
    assert tail(result) == (0, 1, 0, 0, .25, 1, 1)


def test_pending_effect_applies_on_initialization_but_reset_does_not_retrigger_continuing_impulse():
    first = run(None, command_bone=trigger(velocity=(4, 0, 0)))
    assert first['reset']
    assert vector(first, 0) == first['matrix'][3][:3] == (1, 0, 0)
    assert vector(first, 12) == (4, 0, 0)
    second = run(first['bone'], update_frame_index=2, reset_requested=True)
    assert second['reset']
    assert vector(second, 0) == vector(second, 12) == (0, 0, 0)
    assert tail(second)[4] == .5


def test_fading_euler_effect_uses_component_limits_and_does_not_reapply_impulse():
    old = continuing(mode=8, duration=1., fade_range=1., angular_velocity=(100, 100, 100),
                     motion=state(rv=(2, -4, 6)))
    result = run(old, shader_data=shader(settings=(0, 1, 100, 100, 0, .5, 1, .2)))
    assert vector(result, 36) == (1, -1, 1)
    assert vector(result, 24) == pytest.approx((.2, -.2, .2))


def test_euler_effect_keeps_damping_before_fade():
    result = run(continuing(mode=8, motion=state(rv=(2, 0, 0))),
                 shader_data=shader(settings=(0, 1, 100, 100, 0, .5, 100, 100)))
    assert vector(result, 36) == (1, 0, 0)
    assert vector(result, 24) == pytest.approx((.25, 0, 0), abs=1e-7)


def test_new_euler_impulse_perturbs_old_angles_using_raw_integer_draws():
    result = run(state(), command_bone=trigger(mode=8, angular_velocity=(0, 0, 2), duration=1., fade_range=1.))
    # Seed1: three negative signs, then magnitude draws15735,28297,8608.
    assert vector(result, 24) == pytest.approx((-.1508666292147609, -.27131064549666917, .41746679731295444))
    assert vector(result, 36) == (0, 0, 2)


@pytest.mark.parametrize('mode,expected', [
    (8, (-.34966126179947743, -.6288125023921076, -.19128593209850026)),
    (12, (-.3878468915968187, -.11798374537461269, -.3835979416588389)),
])
def test_pre_fade_euler_target_perturbation_follows_conditional_random_consumption(mode, expected):
    old = continuing(mode=mode)
    result = run(old, shader_data=shader(settings=(0, 1, 100, 100, 10, 1, 100, 100)))
    assert vector(result, 36) == pytest.approx(expected)
    assert vector(result, 24) == pytest.approx(tuple(v * .25 for v in expected))
    # Once fading starts, the unperturbed animation target is used.
    result = run(continuing(mode=mode, duration=1., fade_range=1.),
                 shader_data=shader(settings=(0, 1, 100, 100, 10, 1, 100, 100)))
    assert vector(result, 36) == (0, 0, 0)


def test_initial_axis_mode_stores_impulse_magnitude_in_all_velocity_components():
    result = run(state(rv=(1, 2, 2)), command_bone=trigger(mode=10, angular_velocity=(0, 0, 1)),
                 shader_data=shader(settings=(0, 1, 100, 100, 0, .5, 1, 10)))
    assert vector(result, 36) == pytest.approx((2., math.sqrt(14), math.sqrt(14)))
    assert tail(result)[3] == .25
    assert math.hypot(*tail(result)[:3]) == pytest.approx(1.)


def rodrigues_rows(axis, angle):
    # Row-vector Rodrigues formula is independent of the implementation's quaternion construction.
    x, y, z = axis
    skew = ((0, z, -y), (-z, 0, x), (y, -x, 0))
    c, s = math.cos(angle), math.sin(angle)
    return tuple(tuple(c * (i == j) + (1-c) * axis[i] * axis[j] + s * skew[i][j]
                       for j in range(3)) for i in range(3))


@pytest.mark.parametrize('fade_range,expected_speed', [(.5, 2.), (2., 1.)])
def test_axis_rotation_pre_multiplies_animation_and_restores_only_x_velocity_before_fade(fade_range, expected_speed):
    source = rotated(.2, .3, .4)
    old = continuing(mode=10, motion=state(rv=(2, 7, 8)), axis=(0, 1, 0), angle=.1,
                     duration=2., fade_range=fade_range)
    result = run(old, animation_matrix=matrix(source),
                 shader_data=shader(settings=(0, 1, 100, 100, 0, .5, 100, 100)))
    assert vector(result, 36) == (expected_speed, 7, 8)
    assert tail(result)[3] == pytest.approx(.35)
    correction = rodrigues_rows(tail(result)[:3], tail(result)[3])
    for i in range(3):
        expected = tuple(sum(correction[i][k] * source[k][j] for k in range(3)) for j in range(3))
        assert result['matrix'][i][:3] == pytest.approx(expected, abs=2e-6)


def test_axis_attraction_overshoots_for_large_delta_time_instead_of_clamping_to_x():
    old = continuing(mode=10, axis=(-1, 0, 0), angle=.2)
    result = run(old, delta_time=.5)
    axis = tail(result)[:3]
    assert .99 < axis[0] < 1
    assert abs(axis[1]) + abs(axis[2]) > .001
    assert math.hypot(*axis) == pytest.approx(1.)


def test_faded_out_axis_effect_retains_updated_runtime_axis_and_angle_while_clearing_motion():
    old = continuing(mode=10, duration=.25, fade_range=.25, axis=(1, 0, 0), angle=.5,
                     motion=state(rv=(1, 2, 3)))
    result = run(old)
    assert vector(result, 0) == vector(result, 12) == vector(result, 24) == vector(result, 36) == (0, 0, 0)
    assert tail(result)[3] == pytest.approx(.75)
    assert tail(result)[-2] == 0
    assert math.hypot(*tail(result)[:3]) == pytest.approx(1.)


@pytest.mark.parametrize('mode,settings,match', [
    (4, (0, 0, 100, 100, 0, 1, 100, 100), 'linear damping'),
    (10, (0, 1, 100, 100, 0, 0, 100, 100), 'angular damping'),
])
def test_undefined_pre_fade_damping_division_is_rejected_only_when_output_consumes_it(mode, settings, match):
    with pytest.raises(ValueError, match=match):
        run(continuing(mode=mode), shader_data=shader(settings=settings))
    # The shader's later zero-weight select discards the undefined velocity.
    result = run(continuing(mode=mode, weight=0.), shader_data=shader(settings=settings))
    assert vector(result, 12) == vector(result, 36) == (0, 0, 0)
