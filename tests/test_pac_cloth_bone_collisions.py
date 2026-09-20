"""Static animated contacts and the shared bone-collision stage boundary."""

import copy
import struct

import pytest

from cdmw.modding.pac_cloth_collisions import (
    apply_cloth_bone_collisions, apply_static_cloth_animated_collisions,
)


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def definition(kind=1):
    value = bytearray(104)
    struct.pack_into('<Hf', value, 2, kind, 99.)
    return value


def collider_result(a=(0., 0., 0.), b=(0., 4., 0.), *, current_a=None, current_b=None, radius=1.):
    value = bytearray(56)
    struct.pack_into('<f', value, 4, radius)
    struct.pack_into('<12f', value, 8, *a, *(a if current_a is None else current_a),
                     *b, *(b if current_b is None else current_b))
    return value


def snapshots():
    particle, parameter, frame, scene = bytearray(152), bytearray(312), bytearray(100), bytearray(108)
    globals_, push = bytearray(1216), bytearray(44)
    struct.pack_into('<3f', particle, 36, 2., 0., 0.)
    struct.pack_into('<4I', parameter, 60, 0x10001, *([0xFFFFFFFF]*3))
    struct.pack_into('<2I', parameter, 160, 11, 19)
    struct.pack_into('<2I', parameter, 180, 25, 99)
    struct.pack_into('<2H', parameter, 214, 0xFFFF, 0)
    struct.pack_into('<H', parameter, 226, 0xFFFF)
    struct.pack_into('<2H', parameter, 232, 5, 6)
    struct.pack_into('<H', parameter, 238, 7)
    struct.pack_into('<H', parameter, 242, 1)
    struct.pack_into('<2I', frame, 32, 0x100, 4)
    struct.pack_into('<2H', scene, 72, 0, 1)
    struct.pack_into('<f', globals_, 864, .01)
    struct.pack_into('<I', globals_, 884, 1)
    struct.pack_into('<2I', push, 0, 1, 4)
    return dict(particle=particle, simulation_parameter=parameter, per_frame=frame, per_scene=scene,
                global_parameters=globals_, push_constants=push, working_position=(.5, 1., 0.),
                working_flags=0x8000, frame_number_y=0, pre_collision=struct.pack('<10I', *range(100, 110)),
                collidables={(5, 11): definition()}, collidable_results={(6, 19): collider_result()})


def apply(data, **changes):
    return apply_cloth_bone_collisions(**(data | changes))


def attach_plane(data, height=2.):
    struct.pack_into('<H', data['simulation_parameter'], 214, (1 << 11) | 7)
    struct.pack_into('<I', data['simulation_parameter'], 88, 13)
    struct.pack_into('<I', data['per_scene'], 48, 9)
    group = bytearray(16)
    struct.pack_into('<H', group, 2, 1)
    struct.pack_into('<2I', group, 8, 17, 23)
    plane = definition(4)
    struct.pack_into('<6f', plane, 76, 0., height, 0., 0., 1., 0.)
    data.update(static_instances={(9, 13): bytearray(64)}, attached_reference_collidables={7: 31},
                attached_collider_groups={31: group})
    data['collidables'][17, 23] = plane


def guide_snapshots(mixed=False):
    data = snapshots()
    struct.pack_into('<H', data['simulation_parameter'], 216, 0xFFFF)
    groups = {}
    for index in range(2 if mixed else 1):
        group = bytearray(56)
        struct.pack_into('<2H3I', group, 0, 1 if index == 0 else 0, 1, 99, 5, 6)
        struct.pack_into('<3I', group, 28, 0x10001, 11 + index, 19 + index)
        groups[index] = group
    data.update(reference_collidables={0: len(groups) << 16}, extra_collidables=groups,
                scene_objects={(1, 1): bytearray(108)})
    if mixed:
        struct.pack_into('<3f', data['particle'], 36, 2., 2., 0.)
        data['working_position'] = (0., 0., 0.)
        data['collidables'][5, 12] = definition()
        data['collidable_results'] = {
            (6, 19): collider_result(a=(0., 2., 0.), b=(0., 6., 0.)),
            (6, 20): collider_result(a=(2., 0., 0.), b=(2., 4., 0.), radius=2.),
        }
    return data


def test_static_loop_uses_direct_records_result_radius_fixed_thickness_and_preserves_inputs():
    data = snapshots()
    struct.pack_into('<f', data['simulation_parameter'], 204, float('nan'))
    struct.pack_into('<e', data['simulation_parameter'], 286, float('nan'))
    struct.pack_into('<I', data['collidables'][5, 11], 100, 1)  # No guide ownership filter.
    struct.pack_into('<H', data['simulation_parameter'], 226, 3)
    struct.pack_into('<I', data['per_frame'], 32, 0x110)  # Does not rebuild a guide cache.
    before = copy.deepcopy(data)
    result = apply(data)
    assert result['active'] and result['contact']
    assert result['position'] == pytest.approx((1. + f32(.01), 1., 0.))
    assert result['normal_sum'] == (1., 0., 0.)
    assert result['last_radius'] == 1. and result['last_bit1_radius'] == 0.
    assert result['bit1_position'] == result['bit0_position'] == data['working_position']
    assert result['flags'] == 0 and result['cache_mode'] is None
    assert result['pre_collision'] == data['pre_collision'] and data == before


def test_static_motion_uses_frame_translation_without_scene_origin_tiles_or_tangent_damping():
    data = snapshots()
    struct.pack_into('<3f', data['per_frame'], 0, 10., 20., 30.)
    struct.pack_into('<3f2h', data['per_scene'], 0, float('nan'), float('nan'), float('nan'), 23, -42)
    struct.pack_into('<I', data['per_scene'], 64, 0x4000)
    struct.pack_into('<I', data['per_frame'], 32, 0x20000100)
    data['collidable_results'][6, 19] = collider_result(
        a=(10., 20., 30.), b=(10., 24., 30.), current_a=(11., 20., 30.), current_b=(11., 24., 30.))
    result = apply(data)
    assert result['position'] == pytest.approx((2. + f32(.01), 1., 0.))
    assert result['normal_sum'] == (1., 0., 0.)


def test_static_working_reference_requires_both_frame_and_scene_bits():
    data = snapshots()
    data['working_position'] = (.3, .4, 0.)
    struct.pack_into('<I', data['per_frame'], 32, 0x120)
    assert apply(data)['position'] == pytest.approx((1. + f32(.01), .4, 0.))
    struct.pack_into('<I', data['per_scene'], 64, 0x200)
    result = apply(data)
    assert result['position'] == pytest.approx((.6*(1. + f32(.01)), .8*(1. + f32(.01)), 0.))
    assert result['normal_sum'] == pytest.approx((.6, .8, 0.))


def test_static_mask_does_not_accept_guide_bypasses_and_stops_at_index_95():
    data = snapshots()
    struct.pack_into('<3I', data['simulation_parameter'], 64, 0, 0, 0)
    struct.pack_into('<H', data['simulation_parameter'], 242, 97)
    struct.pack_into('<I', data['per_scene'], 64, 0x40000)
    struct.pack_into('<I', data['per_frame'], 36, 0x400004)
    data['collidables'] = {(5, 107): definition()}
    data['collidable_results'] = {(6, 115): collider_result()}
    assert apply(data)['position'] == pytest.approx((1. + f32(.01), 1., 0.))


def test_static_skip_source_compares_raw_resource_and_element_start():
    data = snapshots()
    struct.pack_into('<H', data['simulation_parameter'], 238, 5)
    struct.pack_into('<I', data['simulation_parameter'], 180, 11)
    result = apply(data, collidables=None, collidable_results=None)
    assert not result['contact'] and result['position'] == data['working_position']
    struct.pack_into('<H', data['simulation_parameter'], 238, 65000)
    struct.pack_into('<H', data['simulation_parameter'], 232, 0xFFFF)
    data['collidables'] = {(0, 11): definition()}
    assert apply(data)['contact']  # Same resolved buffer0 is not the same raw source.


@pytest.mark.parametrize('resource', [64999, 65000, 0xFFFF])
def test_static_resource_fallback_includes_ffff_and_element_offsets_wrap(resource):
    data = snapshots()
    struct.pack_into('<2H', data['simulation_parameter'], 232, resource, resource)
    struct.pack_into('<2I', data['simulation_parameter'], 160, 0xFFFFFFFF, 0xFFFFFFFE)
    struct.pack_into('<H', data['simulation_parameter'], 242, 2)
    buffer = resource if resource < 65000 else 0
    data['collidables'] = {(buffer, 0xFFFFFFFF): definition(0), (buffer, 0): definition()}
    data['collidable_results'] = {(buffer, 0xFFFFFFFE): b'\xff'*56, (buffer, 0xFFFFFFFF): collider_result()}
    assert apply(data)['contact']  # Unknown first shape does not consume undefined motion.


@pytest.mark.parametrize('iteration,maximum,local,backward,clear', [
    (2, 4, 4, 0, False), (3, 4, 4, 0, True), (4, 4, 4, 0, False),
    (5, 6, 3, 1, True), (5, 6, 3, 0, False), (0xFFFFFFFF, 0, 0, 0, True),
])
def test_static_flag_cleanup_is_penultimate_local_iteration_even_without_blend_subdivision(
    iteration, maximum, local, backward, clear,
):
    data = snapshots()
    struct.pack_into('<2I', data['push_constants'], 0, iteration, maximum)
    struct.pack_into('<I', data['per_frame'], 36, local)
    struct.pack_into('<I', data['global_parameters'], 1148, backward)
    result = apply(data, working_flags=0xFFFFFFFF)
    assert result['flags'] == 0xFFFFFFFF & (~0x308300 if clear else ~0x8000)


@pytest.mark.parametrize('guide,override', [(False, False), (False, True), (True, False)])
def test_disabled_animated_particles_still_get_attached_static_contacts_only_for_static_meshes(guide, override):
    data = guide_snapshots() if guide else snapshots()
    struct.pack_into('<I', data['particle'], 64, 0x3C00)
    if override:
        struct.pack_into('<I', data['per_frame'], 32, 0x20100)
    attach_plane(data)
    result = apply(data)
    assert result['contact'] is (not guide)
    assert result['position'][1] == pytest.approx(1. if guide else 2. + f32(.01))
    assert result['normal_sum'] == ((1., 0., 0.) if override else (0., 0., 0.))
    assert result['last_radius'] == (1. if override else 0.)


def test_guide_dispatch_uses_authored_thickness_then_attached_static_plane():
    data = guide_snapshots()
    struct.pack_into('<f', data['simulation_parameter'], 204, .25)
    attach_plane(data)
    result = apply(data)
    assert result['position'] == pytest.approx((1.25, 2.25, 0.))
    assert result['normal_sum'] == (1., 0., 0.) and result['contact']
    assert result['last_bit1_radius'] == 1. and result['flags'] & 0x8000


@pytest.mark.parametrize('frame_flags,original_flags,skip,height,active', [
    (0, 0, 0, 0., False), (0x100, 0x40, 0, 0., False),
    (0x100, 0, 1, -9.99, False), (0x100, 0, 1, -10., True),
    (0x100, 0, 1, -10.01, True), (0x100, 0, 0, float('nan'), True),
])
def test_outer_gate_uses_original_flags_and_inclusive_ground_override(frame_flags, original_flags, skip, height, active):
    data = snapshots()
    struct.pack_into('<I', data['per_frame'], 32, frame_flags)
    struct.pack_into('<I', data['particle'], 64, original_flags)
    struct.pack_into('<I', data['push_constants'], 12, skip)
    struct.pack_into('<f', data['per_frame'], 24, height)
    result = apply(data, working_flags=0x8040)  # Working fixed bit does not suppress the stage.
    assert result['active'] is active and result['flags'] == 0x40
    if active:
        assert result['contact']
    else:
        assert result['position'] == data['working_position']
        assert set(result) == {'active', 'position', 'flags', 'pre_collision'}


def test_whole_invocation_skip_precedes_particle_reads_and_inactive_stage_only_clears_8000():
    data = snapshots()
    struct.pack_into('<I', data['per_frame'], 32, 0x500)
    assert apply(data, particle=b'') is None
    struct.pack_into('<I', data['per_frame'], 32, 0)
    struct.pack_into('<I', data['push_constants'], 0, 3)  # Static cleanup must not run on bypass.
    assert apply(data, working_flags=0xFFFFFFFF)['flags'] == 0xFFFF7FFF
    struct.pack_into('<I', data['global_parameters'], 1124, 1)
    struct.pack_into('<I', data['per_frame'], 36, 0)
    assert not apply(data)['active']  # Bypass does not evaluate a zero iteration divisor.


@pytest.mark.parametrize('mode,lra,weight', [('flypapering', .2998, f32(.1)), ('flypapering', .3, .5),
                                             ('scene', float('nan'), .5)])
def test_history_blend_runs_after_attached_contact_and_keeps_contact_metadata(mode, lra, weight):
    data = guide_snapshots(mixed=True)
    attach_plane(data, height=4.)
    struct.pack_into('<I', data['particle'], 64, 0x4000000)
    struct.pack_into('<e', data['particle'], 88, lra)
    struct.pack_into('<H', data['simulation_parameter'], 212, 8)
    struct.pack_into('<I', data['global_parameters'], 1140, 1)
    struct.pack_into('<I', data['per_frame'], 32, 0x20000100)
    if mode == 'scene':
        struct.pack_into('<I', data['per_scene'], 64, 0x4000)
        struct.pack_into('<I', data['per_frame'], 36, 0x84)
    result = apply(data)
    assert result['bit1_position'] == pytest.approx((1., 0., 0.))
    # Scene mode enables tangent damping for flag-clear groups. Their reference
    # movement has a -2 X tangent, adding 0.9 X before the history blend.
    bit0_x = 2.*f32(.45) if mode == 'scene' else 0.
    assert result['bit0_position'] == pytest.approx((bit0_x, 2. + f32(.01), 0.))
    assert result['position'] == pytest.approx((1. + weight*(bit0_x - 1.), weight*(2. + f32(.01)), 0.))
    assert result['position'][1] < 4. and result['contact']  # Attached correction was replaced.
    assert result['normal_sum'] == ((1., 1., 0.) if mode == 'scene' else (1., 0., 0.))
    assert result['last_radius'] == 2. and result['last_bit1_radius'] == 1.


def test_static_branch_uses_the_common_history_blend_without_erasing_contact_metadata():
    data = snapshots()
    struct.pack_into('<I', data['per_scene'], 64, 0x4000)
    struct.pack_into('<I', data['per_frame'], 36, 0x84)
    result = apply(data)
    assert result['position'] == data['working_position']
    assert result['contact'] and result['normal_sum'] == (1., 0., 0.)


def test_direct_static_loop_rejects_a_guide_record_and_a_skipped_clock():
    data = snapshots()
    data.pop('frame_number_y')
    struct.pack_into('<H', data['simulation_parameter'], 216, 0xFFFF)
    with pytest.raises(ValueError, match='static meshes'):
        apply_static_cloth_animated_collisions(**data)
    struct.pack_into('<I', data['per_frame'], 32, 0xC00)
    with pytest.raises(ValueError, match='skipped constraint'):
        apply_static_cloth_animated_collisions(**data)
