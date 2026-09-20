"""Synthetic dynamics, lifecycle and matrix cases for the decoded bone path."""

import math
import struct

import pytest

from cdmw.modding.pac_jiggle_bones import jiggle_bone_blend_override, step_jiggle_bone


IDENTITY = ((1., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., 0.), (0., 0., 0., 1.))
PI = 3.1415927410125732
TAU = 6.2831854820251465


def matrix(rows=IDENTITY):
    return struct.pack('<16f', *(x for row in rows for x in row))


def state(*, p=(0, 0, 0), v=(0, 0, 0), r=(0, 0, 0), rv=(0, 0, 0), flags=0, frame=0):
    result = bytearray(116)
    for offset, vector in ((0, p), (12, v), (24, r), (36, rv)):
        struct.pack_into('<3f', result, offset, *vector)
    struct.pack_into('<2I', result, 108, flags, frame)
    return result


def shader(*, settings=(0, 1, 100, 100, 0, 1, 100, 100), platform=(0, 0, 0),
           flags=0, masks=()):
    result = bytearray(264)
    struct.pack_into('<3f', result, 0, *platform)
    struct.pack_into('<8f', result, 32, *settings)
    struct.pack_into('<2I', result, 64, flags, len(masks))
    for index, (bone, weight) in enumerate(masks):
        struct.pack_into('<H', result, 72 + 2 * index, bone)
        struct.pack_into('<f', result, 136 + 4 * index, weight)
    return result


def character(*, world=IDENTITY, inverse=IDENTITY, origin=(0, 0, 0),
              old_origin=(0, 0, 0), bound_a=(0, 0, 0), bound_b=(0, 0, 0)):
    result = bytearray(272)
    result[:64] = matrix(world)
    result[192:256] = matrix(inverse)
    for offset, value in ((48, origin), (112, old_origin), (128, bound_a), (144, bound_b)):
        struct.pack_into('<3f', result, offset, *value)
    return result


def run(previous, **changes):
    args = dict(command_bone=state(), shader_data=shader(), animation_matrix=matrix(),
                character_transform=character(), view_position=(0, 0, 0), previous_view_position=(0, 0, 0),
                bone_scale=1., original_bone_index=0, update_frame_index=1, delta_time=.25,
                reset_requested=False)
    args.update(changes)
    return step_jiggle_bone(previous, **args)


def vector(result, offset):
    return struct.unpack_from('<3f', result['bone'], offset)


def assert_matrix(actual, expected):
    for row, reference in zip(actual, expected, strict=True):
        assert row == pytest.approx(reference, abs=2e-6)


def rotated(x, y, z):
    # Independent elementary row rotations: Rz * Rx * Ry.
    rx = ((1, 0, 0), (0, math.cos(x), math.sin(x)), (0, -math.sin(x), math.cos(x)))
    ry = ((math.cos(y), 0, -math.sin(y)), (0, 1, 0), (math.sin(y), 0, math.cos(y)))
    rz = ((math.cos(z), math.sin(z), 0), (-math.sin(z), math.cos(z), 0), (0, 0, 1))
    product = lambda a, b: tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3))
                                     for j in range(3)) for i in range(3))
    return tuple((*row, 0.) for row in product(product(rz, rx), ry)) + (IDENTITY[3],)


@pytest.mark.parametrize('flags,expected', [(0, (0, .25)), (1, (1, .25)),
                                          (2, (1, -.5)), (3, (1, .25)), (0x80, (0, .25))])
def test_mask_mode_and_last_duplicate_override_without_clamping(flags, expected):
    data = shader(flags=flags, masks=((4, 2.), (8, .5), (4, -.5)))
    assert jiggle_bone_blend_override(data, 4, .25) == expected


def test_mask_indices_are_u16_and_unmatched_bones_retain_the_instance_weight():
    data = shader(flags=2, masks=tuple((i, i / 16) for i in range(31)) + ((65535, 1.5),))
    assert jiggle_bone_blend_override(data, 65535, .2) == (1., 1.5)
    assert jiggle_bone_blend_override(data, 65536, .2) == (1., .2)
    assert jiggle_bone_blend_override(shader(flags=2), 0, .2) == (1., .2)


def test_missing_previous_state_initializes_from_animation_without_origin_delta():
    source = ((2, 0, 0, .4), (0, 3, 0, .5), (0, 0, 4, .6), (1, 2, 3, .7))
    result = run(None, animation_matrix=matrix(source), shader_data=shader(flags=2, masks=((0, .25),)),
                 character_transform=character(origin=(100, 0, 0)), view_position=(100, 0, 0))
    assert result['reset']
    assert vector(result, 0) == (1, 2, 3)
    assert vector(result, 12) == vector(result, 24) == vector(result, 36) == (0, 0, 0)
    expected = ((2, 0, 0, 1), (0, 3, 0, .25), source[2], source[3])
    assert_matrix(result['matrix'], expected)
    assert struct.unpack_from('<2I', result['bone'], 108) == (0, 1)


@pytest.mark.parametrize('changes', [
    {'reset_requested': True}, {'update_frame_index': 2},
    {'character_transform': character(origin=(17.5001, 0, 0))},
])
def test_resets_preserve_inactive_effect_fields_but_clear_velocities(changes):
    previous = state(p=(1, 2, 3), v=(4, 5, 6), r=(.1, .2, .3), rv=(7, 8, 9), flags=0x10)
    struct.pack_into('<9fI5f', previous, 48, *([.125] * 9), 8, *([.25] * 5))
    result = run(previous, **changes)
    assert result['reset']
    assert vector(result, 12) == vector(result, 36) == (0, 0, 0)
    assert result['bone'][48:112] == previous[48:112]
    # The reset output matrix is animation, even when origin movement is still
    # added to the stored position for the next step.
    assert_matrix(result['matrix'], IDENTITY)
    if 'character_transform' in changes:
        assert vector(result, 0)[0] == pytest.approx(17.5001)


def test_speed_reset_uses_view_relative_origin_and_strict_threshold():
    previous = state()
    assert not run(previous, character_transform=character(origin=(17.5, 0, 0)))['reset']
    assert run(previous, view_position=(18, 0, 0))['reset']
    compensated = run(previous, view_position=(100, 0, 0),
                      character_transform=character(origin=(-100, 0, 0)))
    assert not compensated['reset']
    assert vector(compensated, 0) == (0, 0, 0)


def test_tiny_delta_time_disables_only_the_origin_speed_reset():
    args = dict(character_transform=character(origin=(1, 0, 0)))
    assert not run(state(), delta_time=0., **args)['reset']
    assert not run(state(), delta_time=9e-6, **args)['reset']
    assert run(state(), delta_time=1e-5, **args)['reset']
    assert run(state(), delta_time=0., update_frame_index=9, **args)['reset']


def test_frame_counter_continuity_wraps_at_u32_maximum():
    assert not run(state(frame=0xFFFFFFFF), update_frame_index=0)['reset']


def test_origin_compensation_subtracts_platform_motion_before_integration():
    result = run(state(p=(1, 0, 0)), view_position=(10, 0, 0), previous_view_position=(5, 0, 0),
                 character_transform=character(origin=(3, 0, 0), old_origin=(2, 0, 0)),
                 shader_data=shader(platform=(4, 0, 0)))
    assert not result['reset']
    assert vector(result, 0) == (3, 0, 0)
    assert result['matrix'][3] == (3, 0, 0, 1)


def test_linear_limits_are_vector_lengths_and_do_not_rewrite_stored_velocity():
    settings = (0, .5, 2, .25, 0, 1, 100, 100)
    result = run(state(v=(3, 4, 0)), shader_data=shader(settings=settings), delta_time=.5)
    assert vector(result, 12) == pytest.approx((1.2, 1.6, 0))
    assert vector(result, 0) == pytest.approx((.15, .2, 0))


@pytest.mark.parametrize('bounds,bone_scale,limit', [
    ((0, 0, 0), 2., 1.), ((0, 0, 1.8), 2., 2.), ((0, 3, 4), 2., 5.),
])
def test_character_size_scales_linear_speed_and_displacement_limits(bounds, bone_scale, limit):
    settings = (0, 1, 1, .1, 0, 1, 1, .1)
    result = run(state(v=(0, 10, 0), rv=(10, 10, 10)), delta_time=1., bone_scale=bone_scale,
                 character_transform=character(bound_b=bounds), shader_data=shader(settings=settings))
    assert vector(result, 12) == pytest.approx((0, limit, 0))
    assert vector(result, 0) == pytest.approx((0, .1 * limit, 0))
    assert vector(result, 36) == (1, 1, 1)
    assert vector(result, 24) == pytest.approx((.1, .1, .1))


def test_randomized_acceleration_precedes_damping_and_consumes_two_sequential_samples():
    # Zero old products + bone0 + frame1 gives seed1. The decoded integer draws
    # are 4210 then 1236; their spring multipliers are different.
    source = ((0, 1, 0, 0), (-1, 0, 0, 0), (0, 0, 1, 0), (1, 0, 0, 1))
    result = run(state(), animation_matrix=matrix(source),
                 shader_data=shader(settings=(8, .5, 100, 100, 4, .5, 100, 100)))
    assert vector(result, 12) == pytest.approx((.5642434358596802, 0, 0))
    assert vector(result, 0) == pytest.approx((.14106085896492004, 0, 0))
    angular_speed = .5188609957695007 * (PI / 2) * .5
    assert vector(result, 36) == pytest.approx((0, 0, angular_speed))
    assert vector(result, 24) == pytest.approx((0, 0, angular_speed * .25))


def test_angular_speed_and_displacement_clamp_each_axis_without_velocity_reprojection():
    result = run(state(rv=(3, 4, -5)), shader_data=shader(settings=(0, 1, 100, 100, 0, 1, 1, .1)))
    assert vector(result, 36) == (1, 1, -1)
    assert vector(result, 24) == pytest.approx((.1, .1, -.1))


def test_seed_uses_original_bone_frame_and_old_float_products_before_platform_adjustment():
    # p's product is 24 (0x41c00000), v's is 2 (0x40000000), plus bone3/frame2.
    # The seed 0x81c00005 draws 31396, giving multiplier 0.9790941476821899.
    result = run(state(p=(2, 3, 4), v=(1, 1, 2), frame=1),
                 original_bone_index=3, update_frame_index=2, delta_time=.125,
                 shader_data=shader(platform=(-1, 0, 0), settings=(1, 1, 100, 100, 0, 1, 100, 100)))
    assert vector(result, 12) == pytest.approx((.6328396797180176, .6328396797180176, 1.5104529857635498))


def test_position_below_displacement_limit_retains_prediction_without_cancellation():
    source = IDENTITY[:3] + ((1e20, 0, 0, 1),)
    result = run(state(p=(1, 0, 0)), animation_matrix=matrix(source),
                 shader_data=shader(settings=(0, 1, 100, 1e30, 0, 1, 100, 100)))
    assert vector(result, 0) == (1, 0, 0)


@pytest.mark.parametrize('angle,expected', [(PI, PI), (-PI, -PI), (TAU, 0.), (-TAU, 0.)])
def test_angle_wrap_preserves_both_pi_endpoints_and_reduces_full_turns(angle, expected):
    result = run(state(r=(0, 0, angle)))
    assert vector(result, 24)[2] == pytest.approx(expected, abs=1e-7)


def test_angular_acceleration_takes_the_shortest_path_across_pi():
    result = run(state(r=(0, 0, -3.1)), animation_matrix=matrix(rotated(0, 0, 3.1)),
                 shader_data=shader(settings=(0, 1, 100, 100, 4, 1, 100, 1)))
    assert -.1 < vector(result, 36)[2] < 0
    # The final target+clamped difference is NOT wrapped a second time.
    assert PI < vector(result, 24)[2] < 3.2


def test_zero_timestep_still_applies_damping_per_update():
    result = run(state(v=(2, 0, 0), rv=(0, 2, 0)), delta_time=0.,
                 shader_data=shader(settings=(100, .5, 100, 100, 100, .25, 100, 100)))
    assert vector(result, 0) == vector(result, 24) == (0, 0, 0)
    assert vector(result, 12) == (1, 0, 0)
    assert vector(result, 36) == (0, .5, 0)


def test_multistep_free_decay_matches_a_geometric_series():
    previous = state(v=(8, 0, 0))
    settings = shader(settings=(0, .5, 100, 100, 0, 1, 100, 100))
    for frame in range(1, 9):
        result = run(previous, shader_data=settings, update_frame_index=frame)
        assert not result['reset']
        assert vector(result, 12)[0] == 8 * .5**frame
        assert vector(result, 0)[0] == 2 * (1 - .5**frame)
        previous = result['bone']


def test_matrix_reconstruction_preserves_three_axis_rotation_and_nonuniform_scale():
    angles = (.3, -.4, .6)
    rotation = rotated(*angles)
    source = tuple(tuple(x * scale for x in row[:3]) + (0.,)
                   for row, scale in zip(rotation[:3], (2, 3, 4))) + ((1, 2, 3, 1),)
    result = run(state(p=(1, 2, 3), r=angles), animation_matrix=matrix(source))
    assert_matrix(result['matrix'], source)


def test_output_uses_inverse_world_basis_without_its_translation():
    world = ((0, 1, 0, 0), (-1, 0, 0, 0), (0, 0, 1, 0), IDENTITY[3])
    inverse = ((0, -1, 0, 0), (1, 0, 0, 0), (0, 0, 1, 0), (40, 50, 60, 1))
    source = ((2, 0, 0, 0), (0, 3, 0, 0), (0, 0, 4, 0), IDENTITY[3])
    result = run(state(p=(0, 4, 0), r=(0, 0, PI / 2)), animation_matrix=matrix(source),
                 character_transform=character(world=world, inverse=inverse))
    assert_matrix(result['matrix'], source[:3] + ((4, 0, 0, 1),))


@pytest.mark.parametrize('pitch,roll', [(math.pi / 2, .3), (-math.pi / 2, 1.1)])
def test_gimbal_branch_sets_yaw_zero_and_recovers_combined_roll(pitch, roll):
    result = run(None, animation_matrix=matrix(rotated(pitch, .4, .7)))
    assert vector(result, 24) == pytest.approx((pitch, 0, roll), abs=2e-6)


def test_only_current_flags_with_both_low_bits_replace_previous_effect():
    assert not run(state(flags=0x10), command_bone=state(flags=1))['reset']
    with pytest.raises(ValueError, match='instance effects'):
        run(state(), command_bone=state(flags=3))
    with pytest.raises(ValueError, match='instance effects'):
        run(state(flags=1), reset_requested=True)


@pytest.mark.parametrize('changes,match', [
    ({'command_bone': bytes(115)}, '116-byte'),
    ({'shader_data': bytes(263)}, '264-byte'),
    ({'animation_matrix': bytes(63)}, '64-byte'),
    ({'character_transform': bytes(271)}, '272-byte'),
    ({'animation_matrix': bytes(64)}, 'zero-length'),
    ({'reset_requested': 1}, 'boolean'),
    ({'delta_time': -1.}, 'nonnegative'),
    ({'delta_time': float('nan')}, 'finite'),
    ({'original_bone_index': -1}, 'unsigned'),
    ({'shader_data': shader(settings=(0, 1, -1, 1, 0, 1, 1, 1))}, 'limits'),
])
def test_unsupported_inputs_are_rejected(changes, match):
    with pytest.raises(ValueError, match=match):
        run(state(), **changes)


def test_mask_count_bounds_are_checked_only_in_the_consuming_mode():
    data = shader(flags=2)
    struct.pack_into('<I', data, 68, 33)
    with pytest.raises(ValueError, match='32-entry'):
        jiggle_bone_blend_override(data, 0, .3)
    struct.pack_into('<I', data, 64, 1)
    assert jiggle_bone_blend_override(data, 0, .3) == (1., .3)
