"""Constraint timing, moving surfaces and guide contact state composition."""

import copy
import struct

import pytest

from cdmw.modding.pac_cloth_collisions import (
    apply_attached_static_cloth_collisions, apply_guide_cloth_animated_collisions,
    sample_cloth_collider_motion, select_cloth_collider_blends,
)


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def collider_result(a=(0., 0., 0.), b=(0., 4., 0.), *, current_a=None, current_b=None, radius=1.):
    result = bytearray(56)
    struct.pack_into('<f', result, 4, radius)
    struct.pack_into('<12f', result, 8, *a, *(a if current_a is None else current_a),
                     *b, *(b if current_b is None else current_b))
    return result


def snapshots():
    particle, parameter, frame, scene = bytearray(152), bytearray(312), bytearray(100), bytearray(108)
    globals_, push, group, definition = bytearray(1216), bytearray(44), bytearray(56), bytearray(104)
    struct.pack_into('<3f', particle, 36, 2., 0., 0.)
    struct.pack_into('<4I', parameter, 60, 0x10001, *([0xFFFFFFFF]*3))
    struct.pack_into('<2I', parameter, 180, 100, 99)
    struct.pack_into('<2H', parameter, 214, 0xFFFF, 0xFFFF)
    struct.pack_into('<H', parameter, 226, 3)
    struct.pack_into('<H', parameter, 238, 7)
    struct.pack_into('<2I', frame, 32, 0x10, 4)
    struct.pack_into('<2H', scene, 72, 0, 1)
    struct.pack_into('<f', globals_, 864, .01)
    struct.pack_into('<I', globals_, 884, 1)
    struct.pack_into('<2I', push, 0, 1, 4)
    struct.pack_into('<2H3I', group, 0, 1, 1, 99, 5, 6)
    struct.pack_into('<I', group, 28, 0x10001)
    struct.pack_into('<Hf', definition, 2, 1, 99.)  # Animated radius comes from result, not here.
    return dict(particle=particle, simulation_parameter=parameter, per_frame=frame, per_scene=scene,
                global_parameters=globals_, push_constants=push, working_position=(.5, 1., 0.),
                working_flags=0, pre_collision=struct.pack('<10I', *range(100, 110)),
                reference_collidables={0: 1 << 16}, extra_collidables={0: group},
                collidables={(5, 0): definition}, collidable_results={(6, 0): collider_result()},
                scene_objects={(1, 1): bytearray(108)})


def blends(data):
    return select_cloth_collider_blends(data['per_frame'], data['global_parameters'], data['push_constants'])


def apply(data, **changes):
    return apply_guide_cloth_animated_collisions(**(data | changes))


def motion(reference=(2., 0., 0.), result=None, **changes):
    options = dict(translation_to_collider_space=(0., 0., 0.), sample_blend=0., current_blend=1.)
    return sample_cloth_collider_motion(reference, collider_result() if result is None else result, **(options | changes))


def test_constraint_blends_use_substep_count_instead_of_base_animation_interval():
    data = snapshots()
    struct.pack_into('<I', data['global_parameters'], 884, 4)
    struct.pack_into('<I', data['push_constants'], 40, 2)
    struct.pack_into('<2f', data['global_parameters'], 872, 999., -999.)
    assert blends(data) == {'previous': .5, 'current': .75, 'sample': .5}
    struct.pack_into('<I', data['per_frame'], 32, 0x12)
    assert blends(data)['sample'] == .75


@pytest.mark.parametrize('subdivision,expected', [(0, (.5, 1.)), (1, (.625, .75)), (2, (.5, 1.))])
def test_iteration_subdivision_requires_global_value_one(subdivision, expected):
    data = snapshots()
    struct.pack_into('<I', data['global_parameters'], 884, 2)
    struct.pack_into('<I', data['global_parameters'], 1124, subdivision)
    struct.pack_into('<I', data['push_constants'], 40, 1)
    struct.pack_into('<I', data['push_constants'], 0, 2)
    result = blends(data)
    assert (result['previous'], result['current']) == expected


def test_iteration_limit_and_backward_adjustment_use_the_selected_low_three_bits():
    data = snapshots()
    struct.pack_into('<I', data['per_frame'], 36, 3)
    struct.pack_into('<I', data['global_parameters'], 1124, 1)
    struct.pack_into('<I', data['global_parameters'], 1148, 1)
    struct.pack_into('<2I', data['push_constants'], 0, 5, 6)
    result = blends(data)
    assert result['previous'] == pytest.approx(1/3)
    assert result['current'] == pytest.approx(2/3)


def test_scaled_clock_and_variable_substeps_choose_their_own_counts():
    data = snapshots()
    struct.pack_into('<I', data['per_frame'], 36, 0x8004)
    struct.pack_into('<f', data['global_parameters'], 864, 0.)
    struct.pack_into('<f', data['global_parameters'], 896, .02)
    struct.pack_into('<I', data['global_parameters'], 916, 4)
    struct.pack_into('<I', data['push_constants'], 40, 1)
    assert blends(data) == {'previous': .25, 'current': .5, 'sample': .25}
    struct.pack_into('<I', data['per_frame'], 36, 0x8804)
    assert blends(data) is None
    struct.pack_into('<I', data['push_constants'], 40, 0)
    struct.pack_into('<f', data['global_parameters'], 896, 0.)
    assert blends(data) == {'previous': 0., 'current': 1., 'sample': 0.}


@pytest.mark.parametrize('reason', ['frame400', 'frame800', 'short_step', 'out_of_range', 'zero_count'])
def test_skipped_constraint_clocks_cannot_enter_the_contact_pass(reason):
    data = snapshots()
    if reason.startswith('frame'):
        struct.pack_into('<I', data['per_frame'], 32, int(reason[5:], 16))
    elif reason == 'short_step':
        struct.pack_into('<f', data['global_parameters'], 864, .00001)
    elif reason == 'out_of_range':
        struct.pack_into('<I', data['push_constants'], 40, 1)
    else:
        struct.pack_into('<I', data['global_parameters'], 884, 0)
    assert blends(data) is None
    with pytest.raises(ValueError, match='skipped constraint'):
        apply(data)


def test_zero_iteration_divisor_is_rejected_only_when_subdivision_is_active():
    data = snapshots()
    struct.pack_into('<I', data['per_frame'], 36, 0)
    assert blends(data)['current'] == 1.
    struct.pack_into('<I', data['global_parameters'], 1124, 1)
    with pytest.raises(ValueError, match='zero iterations'):
        blends(data)


def test_pure_translation_interpolates_endpoints_and_advects_reference_by_the_selected_interval():
    result = collider_result(current_a=(2., 4., 6.), current_b=(2., 8., 6.))
    sample = motion(result=result, sample_blend=.25, current_blend=.75,
                    translation_to_collider_space=(10., 20., 30.))
    assert sample['center1'] == (-8.5, -17., -25.5)
    assert sample['center2'] == (-8.5, -13., -25.5)
    assert sample['displacement'] == (1., 2., 3.)
    assert sample['reference_position'] == (3., 2., 3.)


def test_rotating_endpoints_use_the_average_axis_to_compute_point_dependent_motion():
    result = collider_result(current_a=(1., 0., 0.), current_b=(5., 0., 0.))
    sample = motion((0., 2., 0.), result)
    assert sample['axial_coordinate'] == .375
    assert sample['displacement'] == (2.5, -1.5, 0.)
    assert sample['reference_position'] == (2.5, .5, 0.)


def test_axial_motion_extrapolates_beyond_the_segment_instead_of_clamping():
    sample = motion((2., 12., 0.), collider_result(current_b=(0., 8., 0.)))
    assert sample['axial_coordinate'] == 2.
    assert sample['displacement'] == (0., 8., 0.)
    assert sample['reference_position'] == (2., 20., 0.)


def test_motion_follows_rotation_and_translation_of_the_entire_problem():
    def transform(point, translate=True):
        x, y, z = point
        return (y + (10 if translate else 0), -x + (20 if translate else 0), z + (30 if translate else 0))
    result = collider_result(current_a=(1., 0., 0.), current_b=(5., 0., 0.))
    original = motion((0., 2., 0.), result)
    moved = collider_result(transform((0., 0., 0.)), transform((0., 4., 0.)),
                            current_a=transform((1., 0., 0.)), current_b=transform((5., 0., 0.)))
    sample = motion(transform((0., 2., 0.)), moved)
    assert sample['displacement'] == transform(original['displacement'], False)
    assert sample['reference_position'] == transform(original['reference_position'])


def test_collapsed_average_axis_is_rejected_even_when_each_endpoint_axis_has_length():
    with pytest.raises(ValueError, match='average collider axis'):
        motion(result=collider_result(current_b=(0., -4., 0.)))


def test_animated_contact_composes_selection_geometry_flags_radii_and_cache_without_mutation():
    data = snapshots()
    before = copy.deepcopy(data)
    result = apply(data)
    assert result['position'] == (1., 1., 0.)
    assert result['contact'] and result['normal_sum'] == (1., 0., 0.)
    assert result['last_radius'] == result['last_bit1_radius'] == 1.
    assert result['flags'] == 0x20008000
    assert result['bit1_position'] == result['bit0_position'] == (.5, 1., 0.)
    assert struct.unpack('<10I', result['pre_collision']) == (100, 101, 102, 103, 104, 1, 0, 107, 108, 109)
    assert data == before
    struct.pack_into('<I', data['particle'], 64, result['flags'])
    data['pre_collision'] = result['pre_collision']
    cached = apply(data)
    assert cached['position'] == result['position']
    assert cached['normal_sum'] == result['normal_sum']
    assert cached['pre_collision'] == result['pre_collision']
    assert cached['cache_mode'] == 'cached'


@pytest.mark.parametrize('moving', [False, True])
def test_tangent_damping_subtracts_collider_motion_before_measuring_relative_motion(moving):
    data = snapshots()
    struct.pack_into('<H', data['extra_collidables'][0], 0, 0)
    struct.pack_into('<I', data['per_scene'], 64, 0x4000)
    struct.pack_into('<I', data['per_frame'], 32, 0x20000010)
    if moving:
        data['collidable_results'][(6, 0)] = collider_result(current_a=(0., 1., 0.), current_b=(0., 5., 0.))
    expected_y = 1. if moving else 1. - f32(.45)*(1. + f32(.01) - .5)/1.5
    assert apply(data)['position'] == pytest.approx((1. + f32(.01), expected_y, 0.))


def test_frame_two_selects_current_sample_and_removes_inter_sample_motion():
    data = snapshots()
    data['collidable_results'][(6, 0)] = collider_result(current_a=(0., 1., 0.), current_b=(0., 5., 0.))
    assert apply(data, working_position=(.5, 0., 0.))['position'] == (1., 0., 0.)
    struct.pack_into('<I', data['per_frame'], 32, 0x12)
    result = apply(data, working_position=(.5, 0., 0.))
    normal = (2/5**.5, -1/5**.5, 0.)
    surface = (normal[0], 1 + normal[1], 0.)
    depth = sum((p - s)*n for p, s, n in zip((.5, 0., 0.), surface, normal))
    assert result['position'] == pytest.approx(tuple(p - depth*n for p, n in zip((.5, 0., 0.), normal)))


def test_working_reference_selection_changes_the_surface_direction():
    data = snapshots()
    struct.pack_into('<I', data['per_frame'], 32, 0x30)
    struct.pack_into('<I', data['per_scene'], 64, 0x200)
    struct.pack_into('<I', data['extra_collidables'][0], 28, 0x10002)
    data['scene_objects'] = {(1, 2): bytearray(108)}
    assert apply(data, working_position=(0., .5, 0.))['position'] == (0., 1., 0.)


@pytest.mark.parametrize('group_bits,expected_radius', [(1, 1.2), (3, 1.2 + .300048828125),
                                                      (0, 1. + f32(.01)), (2, 1. + f32(.01) + .300048828125)])
def test_group_bits_choose_authored_or_fixed_thickness_and_optional_half_addition(group_bits, expected_radius):
    data = snapshots()
    struct.pack_into('<H', data['extra_collidables'][0], 0, group_bits)
    struct.pack_into('<f', data['simulation_parameter'], 204, .2 if group_bits & 1 else float('nan'))
    struct.pack_into('<e', data['simulation_parameter'], 286, .3)
    assert apply(data)['position'][0] == pytest.approx(expected_radius)


@pytest.mark.parametrize('mode', ['ordinary', 'scene_split', 'flypapering'])
def test_group_position_histories_and_normal_accumulation_follow_selected_mode(mode):
    data = snapshots()
    struct.pack_into('<3f', data['particle'], 36, 2., 2., 0.)
    data['reference_collidables'][0] = 2 << 16
    second = bytearray(data['extra_collidables'][0])
    struct.pack_into('<H', second, 0, 0)
    struct.pack_into('<2I', second, 32, 1, 1)
    data['extra_collidables'][1] = second
    data['collidables'][(5, 1)] = bytearray(data['collidables'][(5, 0)])
    data['collidable_results'] = {(6, 0): collider_result((0., 2., 0.), (0., 6., 0.)),
                                  (6, 1): collider_result((2., 0., 0.), (2., 4., 0.), radius=2.)}
    if mode == 'scene_split':
        struct.pack_into('<I', data['per_frame'], 36, 0x84)
        struct.pack_into('<I', data['per_scene'], 64, 0x4000)
    elif mode == 'flypapering':
        struct.pack_into('<I', data['global_parameters'], 1140, 1)
        struct.pack_into('<H', data['simulation_parameter'], 212, 8)
        struct.pack_into('<I', data['particle'], 64, 0x4000000)
        struct.pack_into('<I', data['per_frame'], 32, 0x20000010)
    result = apply(data, working_position=(0., 0., 0.))
    assert result['position'] == (1. if mode == 'ordinary' else 0., 2. + f32(.01), 0.)
    assert result['normal_sum'] == (1., 0. if mode == 'flypapering' else 1., 0.)
    assert result['bit1_position'] == ((0., 0., 0.) if mode == 'ordinary' else (1., 0., 0.))
    assert result['bit0_position'] == ((0., 0., 0.) if mode == 'ordinary' else (0., 2. + f32(.01), 0.))
    assert result['last_radius'] == 2. and result['last_bit1_radius'] == 1.
    assert result['flags'] == (0x20000000 if mode == 'flypapering' else 0x20010000)


def test_scene_and_frame_translation_use_signed_scene_tile_order():
    data = snapshots()
    struct.pack_into('<3f2h', data['per_scene'], 0, 4., 5., 6., -2, 3)
    struct.pack_into('<3f2h', data['scene_objects'][(1, 1)], 0, 1., 2., 3., -1, 1)
    struct.pack_into('<3f', data['per_frame'], 0, 7., 8., 9.)
    # Translation=(-990, 11, 2012). The result is in the other scene's space.
    data['collidable_results'][(6, 0)] = collider_result((-990., 11., 2012.), (-990., 15., 2012.))
    assert apply(data)['position'] == (1., 1., 0.)


def test_collapsed_current_capsule_uses_surface_fallback_when_average_motion_axis_is_valid():
    data = snapshots()
    struct.pack_into('<H', data['collidables'][(5, 0)], 2, 5)
    data['collidable_results'][(6, 0)] = collider_result(current_b=(0., 0., 0.))
    assert apply(data)['position'] == (1., 1., 0.)


def test_unhandled_animated_shape_has_no_contact_but_its_zero_plane_query_still_enters_cache():
    data = snapshots()
    struct.pack_into('<H', data['collidables'][(5, 0)], 2, 4)
    data['collidable_results'][(6, 0)] = bytearray(56)
    result = apply(data)
    assert not result['contact'] and result['position'] == data['working_position']
    assert result['normal_sum'] == (0., 0., 0.)
    assert struct.unpack_from('<2I', result['pre_collision'], 20) == (1, 0)


def test_disabled_guide_branch_only_clears_8000_and_preserves_cache_and_other_flags():
    data = snapshots()
    struct.pack_into('<H', data['per_scene'], 72, 0xFFFF)
    result = apply(data, working_flags=0x38000, collidable_results=None, scene_objects=None)
    assert result['flags'] == 0x30000 and not result['contact']
    assert result['pre_collision'] == data['pre_collision']


def test_animated_position_feeds_the_following_attached_static_stage():
    data = snapshots()
    animated = apply(data, working_position=(.5, -.5, 0.))
    struct.pack_into('<H', data['simulation_parameter'], 214, 1 << 11)
    static_definition, static_group = bytearray(104), bytearray(16)
    struct.pack_into('<H', static_definition, 2, 4)
    struct.pack_into('<3f', static_definition, 88, 0., 1., 0.)
    struct.pack_into('<H', static_group, 2, 1)
    static = apply_attached_static_cloth_collisions(
        animated['position'], (2., 0., 0.), data['simulation_parameter'], data['per_frame'], data['per_scene'],
        frame_number_y=0, previous_contact=animated['contact'], static_instances={(0, 0): bytearray(64)},
        reference_collidables={0: 0}, collider_groups={0: static_group}, collidables={(0, 0): static_definition})
    assert static == {'position': (1., 0., 0.), 'contact': True}
