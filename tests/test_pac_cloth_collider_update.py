"""Analytic collider producer geometry, history and contact handoff checks."""

import copy
import math
import struct

import pytest

from cdmw.modding.pac_cloth_collisions import (
    cloth_collider_contact_surface, resolve_cloth_moving_contact,
    sample_cloth_collider_motion, update_guide_cloth_collider_result,
    update_static_cloth_collider_result,
)


def matrix(size=64, *, scale=(1., 1., 1.), translation=(0., 0., 0.)):
    data = bytearray(size)
    for i, value in enumerate(scale):
        struct.pack_into('<f', data, i*20, value)
    struct.pack_into('<4f', data, 48, *translation, 1.)
    return data


def snapshots():
    definition = bytearray(104)
    struct.pack_into('<I2f', definition, 0, (5 << 16) | 3, .25, 2.)
    definition[12:76] = matrix()
    struct.pack_into('<6f', definition, 76, 1., 0., 0., 0., 1., 0.)
    group = bytearray(56)
    struct.pack_into('<I', group, 0, (1 << 16) | 1)
    struct.pack_into('<I', group, 28, 0x12345678)
    previous = bytearray(56)
    struct.pack_into('<I', previous, 0, 0xABCDEF01)
    struct.pack_into('<6f', previous, 20, 9., 8., 7., 100., 101., 102.)
    struct.pack_into('<3f', previous, 44, 6., 5., 4.)
    return dict(collider_definition=definition, previous_result=previous,
                extra_collidable=group, per_scene=bytearray(108), global_parameters=bytearray(1216),
                character_transform=matrix(272), use_bone_transform=False)


def unpack(data):
    assert len(data) == 56
    owner, radius = struct.unpack_from('<If', data)
    return dict(owner=owner, radius=radius, **{name: struct.unpack_from('<3f', data, offset)
                for name, offset in [('previous_a', 8), ('a', 20), ('previous_b', 32), ('b', 44)]})


def update(data, **changes):
    return unpack(update_guide_cloth_collider_result(**(data | changes)))


def test_guide_uses_scaled_bone_pose_then_world_basis_and_preserves_inputs():
    data = snapshots()
    data['character_transform'] = matrix(272, scale=(2., 1., .5), translation=(1000., 2000., 3000.))
    struct.pack_into('<3f', data['collider_definition'], 60, 1., 2., 3.)
    animation = matrix(translation=(10., 20., 30.))
    struct.pack_into('<4f', animation, 0, 0., 1., 0., math.nan)
    struct.pack_into('<3f', animation, 16, -1., 0., 0.)
    data.update(use_bone_transform=True, animation_matrix=animation, character_space_scale=(2., 3., 4.))
    before = copy.deepcopy(data)
    result = update(data)
    assert result == dict(owner=0x12345678, radius=.5, a=(8., 20., 21.), b=(8., 24., 21.),
                          previous_a=(8., 20., 21.), previous_b=(8., 24., 21.))
    assert data == before
    # The unmapped branch consumes neither bone inputs nor world translation.
    result = update(data, use_bone_transform=False, animation_matrix=None, character_space_scale=None)
    assert result['a'] == (0., 2., 1.5) and result['b'] == (4., 2., 1.5)
    assert result['radius'] == .125


def test_shear_extends_axis_and_removes_parallel_radius_component():
    data = snapshots()
    struct.pack_into('<f', data['collider_definition'], 4, .5)
    struct.pack_into('<3f', data['collider_definition'], 44, 1., 0., 1.)
    struct.pack_into('<3f', data['collider_definition'], 60, 2., 3., 4.)
    result = update(data)
    assert result['a'] == pytest.approx((.5, 3., 4.))
    assert result['b'] == pytest.approx((3.5, 3., 4.))
    assert result['radius'] == pytest.approx(.5)
    struct.pack_into('<I', data['collider_definition'], 100, 2)
    struct.pack_into('<e', data['per_scene'], 84, 2.)
    result = update(data)
    assert result['a'] == pytest.approx((0., 3., 4.))
    assert result['b'] == pytest.approx((4., 3., 4.))
    assert result['radius'] == pytest.approx(1.)


@pytest.mark.parametrize('height,expected_radius,extension', [(.0005, math.sqrt(.5), 0.), (.001, .5, .5)])
def test_short_height_branch_skips_shear_angle_but_still_requires_nonzero_axis(height, expected_radius, extension):
    data = snapshots()
    struct.pack_into('<2f', data['collider_definition'], 4, .5, height)
    struct.pack_into('<3f', data['collider_definition'], 44, 1., 0., 1.)
    result = update(data)
    assert result['radius'] == pytest.approx(expected_radius)
    assert result['a'] == pytest.approx((-height*.5-extension, 0., 0.))
    assert result['b'] == pytest.approx((height*.5+extension, 0., 0.))


@pytest.mark.parametrize('flags, radius, reset', [
    (0, .5, False), (2, .5, True), (0x40, .5, True), (0x80, .5, True),
    (0xC0, .5, False), (0, .00001, True), (0, .0001, False),
])
def test_guide_history_uses_prior_current_centers_unless_radius_reset_or_lod_transition(flags, radius, reset):
    data = snapshots()
    struct.pack_into('<I', data['per_scene'], 64, flags)
    struct.pack_into('<f', data['previous_result'], 4, radius)
    result = update(data)
    assert result['previous_a'] == ((-1., 0., 0.) if reset else (9., 8., 7.))
    assert result['previous_b'] == ((1., 0., 0.) if reset else (6., 5., 4.))


@pytest.mark.parametrize('group_flags, scene_flags, expected', [(0, 0, 0.), (4, 0, 0.), (1, 0, .25),
                                                             (2, 0, .25), (0, 4, .25)])
def test_guide_radius_output_respects_group_and_scene_activation(group_flags, scene_flags, expected):
    data = snapshots()
    struct.pack_into('<I', data['extra_collidable'], 0, (1 << 16) | group_flags)
    struct.pack_into('<I', data['per_scene'], 64, scene_flags)
    assert update(data)['radius'] == expected


def test_enlargement_only_changes_current_history_and_is_type_gated_without_scene_8000():
    data = snapshots()
    struct.pack_into('<I', data['extra_collidable'], 0, (3 << 16) | 2)
    struct.pack_into('<I', data['per_scene'], 64, 0x8000)
    struct.pack_into('<f', data['global_parameters'], 1172, .5)
    result = update(data)
    assert result['a'] == result['previous_a'] == (-1., 0., 0.)
    assert result['previous_b'] == (1., 0., 0.)
    assert result['b'] == (3.5, 0., 0.)
    struct.pack_into('<I', data['per_scene'], 64, 4)
    struct.pack_into('<I', data['global_parameters'], 1180, 1)
    assert update(data)['b'] == (1., 0., 0.)  # capsule type5 does not use shield branch
    struct.pack_into('<H', data['collider_definition'], 2, 3)
    assert update(data)['b'] == (6., 0., 0.)  # ratio defaults to1 outside scene8000


@pytest.mark.parametrize('count,radius,custom,flags,shift', [
    (1, .25, .125, 0, .125), (1, .25, -2., 0, 0.),
    (1, .25, -2., 0x20000, .02), (3, .25, -2., 0, .07),
    (3, .25, -2., 0x20000, .05), (3, .5, .125, 0, 0.),
    (3, .5, .125, 0x20000, .02),
])
def test_pac_custom_shift_sentinels_and_large_radius_override(count, radius, custom, flags, shift):
    data = snapshots()
    struct.pack_into('<I', data['extra_collidable'], 0, (count << 16) | 2)
    struct.pack_into('<f', data['collider_definition'], 4, radius)
    struct.pack_into('<I', data['per_scene'], 64, 0x8000 | flags)
    struct.pack_into('<e', data['per_scene'], 98, custom)
    struct.pack_into('<I', data['global_parameters'], 1204, 1)
    result = update(data)  # ratio0 isolates the translation from length enlargement
    assert result['a'] == pytest.approx((-1.-shift, 0., 0.))
    assert result['b'] == pytest.approx((1.-shift, 0., 0.))
    assert result['previous_a'] == (-1., 0., 0.)
    assert result['previous_b'] == (1., 0., 0.)


def test_static_attached_transform_has_signed_relative_tiles_and_authored_radius():
    data = snapshots()
    frame = bytearray(100)
    struct.pack_into('<I', frame, 32, 0x200000)
    host = matrix(translation=(10., 20., 30.))
    child = matrix(scale=(2., 3., 4.), translation=(11., 22., 33.))
    struct.pack_into('<3f', child, 0, 0., 2., 0.)
    struct.pack_into('<3f', child, 16, -3., 0., 0.)
    struct.pack_into('<2h', host, 12, 3, -2)
    struct.pack_into('<2h', child, 12, -4, 1)
    result = unpack(update_static_cloth_collider_result(data['collider_definition'], data['previous_result'],
                                                       frame, host, attached_transform=child))
    assert result['a'] == result['previous_a'] == (3001., 4., -6997.)
    assert result['b'] == result['previous_b'] == (2998., 2., -6997.)
    assert result['owner'] == 0xABCDEF01 and result['radius'] == .25
    struct.pack_into('<H', data['collider_definition'], 0, 0xFFFF)
    result = unpack(update_static_cloth_collider_result(data['collider_definition'], data['previous_result'], frame, host))
    assert result['a'] == (1., 0., 0.) and result['b'] == (0., 1., 0.)


@pytest.mark.parametrize('flags, radius, reset', [(0, .5, False), (2, .5, True), (0, .00001, True)])
def test_static_history_uses_frame_reset_without_guide_lod_flags(flags, radius, reset):
    data = snapshots()
    frame = bytearray(100)
    struct.pack_into('<I', frame, 32, flags)
    struct.pack_into('<f', data['previous_result'], 4, radius)
    result = unpack(update_static_cloth_collider_result(data['collider_definition'], data['previous_result'], frame, matrix()))
    assert result['previous_a'] == ((1., 0., 0.) if reset else (9., 8., 7.))
    assert result['previous_b'] == ((0., 1., 0.) if reset else (6., 5., 4.))


def test_updated_guide_record_feeds_existing_moving_capsule_contact():
    data = snapshots()
    data.update(use_bone_transform=True, animation_matrix=matrix(), character_space_scale=(1., 1., 1.))
    data['previous_result'] = update_guide_cloth_collider_result(**data)
    data['animation_matrix'] = matrix(translation=(0., 2., 0.))
    result = update_guide_cloth_collider_result(**data)
    motion = sample_cloth_collider_motion((0., .1, 0.), result,
        translation_to_collider_space=(0., 0., 0.), sample_blend=0., current_blend=1.)
    assert motion['displacement'] == (0., 2., 0.)
    surface, normal = cloth_collider_contact_surface(motion['reference_position'], collider_type=5,
        center1=motion['center1'], center2=motion['center2'], radius=.25, thickness=0.)
    contact = resolve_cloth_moving_contact((0., 2.1, 0.), (0., .1, 0.), surface_position=surface, surface_normal=normal,
        collider_displacement=motion['displacement'], apply_tangential_damping=False)
    assert contact['contact'] and contact['position'] == pytest.approx((0., 2.25, 0.))


def test_missing_selected_resources_and_consumed_degenerate_math_fail_without_mutation():
    data = snapshots()
    before = copy.deepcopy(data)
    with pytest.raises(ValueError, match='selected animation'):
        update(data, use_bone_transform=True)
    with pytest.raises(ValueError, match='booleans'):
        update(data, use_bone_transform=1)
    assert data == before
    struct.pack_into('<f', data['collider_definition'], 8, 0.)
    with pytest.raises(ValueError, match='Degenerate'):
        update(data)
    frame = bytearray(100)
    struct.pack_into('<I', frame, 32, 0x200000)
    with pytest.raises(ValueError, match='selected object'):
        update_static_cloth_collider_result(data['collider_definition'], data['previous_result'], frame, matrix())
    with pytest.raises(ValueError, match='272-byte'):
        update(snapshots(), character_transform=bytes(64))
