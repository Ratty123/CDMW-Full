"""Guide collider eligibility and cache transitions, with immutable owned data."""

import copy
import struct

import pytest

from cdmw.modding.pac_cloth_collisions import (
    cloth_collider_contact_surface, resolve_cloth_moving_contact,
    select_guide_cloth_collision_candidates, update_guide_cloth_collision_cache,
)
from cdmw.modding.pac_cloth_state import finalize_cloth_base_state
from cdmw.modding.pac_cloth_runtime import build_cloth_collision_group_flags
from cdmw.modding.pabv_parser import PabvVolume, PabvVolumes, prepare_pabv_cloth_colliders
from cdmw.modding.skeleton_parser import Bone, Skeleton


def group(*, count=3, flags=0, srv=8, offset=200, scene=0x20003, pac=99, uav=9, result_offset=300):
    result = bytearray(56)
    struct.pack_into('<2H3I', result, 0, flags, count, pac, srv, uav)
    struct.pack_into('<3I', result, 28, scene, offset, result_offset)
    return result


def definition(flags=0):
    result = bytearray(104)
    struct.pack_into('<I', result, 100, flags)
    return result


def snapshots(count=3):
    particle, parameter, frame, scene = bytearray(152), bytearray(312), bytearray(100), bytearray(108)
    struct.pack_into('<I3I', parameter, 60, 0x20003, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF)
    struct.pack_into('<2I', parameter, 180, 100, 99)
    struct.pack_into('<H', parameter, 216, 0xFFFF)
    struct.pack_into('<H', parameter, 226, 3)
    struct.pack_into('<H', parameter, 238, 7)
    struct.pack_into('<I', frame, 32, 0x10)
    struct.pack_into('<2H', scene, 72, 5, 1)
    cache = struct.pack('<10I', 100, 101, 102, 103, 104, 0, *([0xFFFFFFFF]*4))
    return dict(particle=particle, simulation_parameter=parameter, per_frame=frame, per_scene=scene,
                working_flags=0, pre_collision=cache, reference_collidables={5: (1 << 16) | 11},
                extra_collidables={11: group(count=count)},
                collidables={(8, 200 + i): definition() for i in range(count)})


def select(data, **changes):
    return select_guide_cloth_collision_candidates(**(data | changes))


def update(data, queries, **changes):
    args = {k: v for k, v in data.items() if k not in ('reference_collidables', 'extra_collidables', 'collidables')}
    return update_guide_cloth_collision_cache(**(args | changes), evaluated_colliders=queries)


def ordinals(selection):
    return [candidate['ordinals'] for candidate in selection['candidates']]


def cached(data, tokens):
    struct.pack_into('<I', data['particle'], 64, 0x20000000)
    words = list(struct.unpack('<10I', data['pre_collision']))
    words[5] = len(tokens)
    words[6:6 + len(tokens)] = tokens
    data['pre_collision'] = struct.pack('<10I', *words)


def test_full_selection_resolves_ordered_definition_result_and_scene_addresses_without_mutation():
    data = snapshots()
    before = copy.deepcopy(data)
    selection = select(data)
    assert selection['cache_mode'] == 'rebuild'
    assert ordinals(selection) == [(0, 0, i) for i in range(3)]
    assert selection['candidates'][2] == dict(ordinals=(0, 0, 2), group_index=11,
                                             definition_key=(8, 202), result_key=(9, 302), scene_key=(2, 3))
    assert data == before


@pytest.mark.parametrize('component_flags,selected', [(0, 0), (0xDF, 0), (0x20, 3), (0xFF, 3)])
def test_cpu_component_flag_controls_working_particle_exemption(component_flags, selected):
    data = snapshots()
    bits = build_cloth_collision_group_flags(
        component_flags=component_flags, critical_collidable=False, same_pac_collidable=False,
    )
    struct.pack_into('<H', data['extra_collidables'][11], 0, bits)
    assert len(select(data, working_flags=0x10000)['candidates']) == selected


@pytest.mark.parametrize('critical,selected', [(False, 3), (True, 0)])
def test_ordinary_groups_remain_collidable_without_the_critical_flag(critical, selected):
    data = snapshots()
    bits = build_cloth_collision_group_flags(
        component_flags=0, critical_collidable=critical, same_pac_collidable=False,
    )
    struct.pack_into('<H', data['extra_collidables'][11], 0, bits)
    struct.pack_into('<I', data['per_frame'], 32, 0x20000010)
    struct.pack_into('<e', data['particle'], 88, .25)
    assert len(select(data)['candidates']) == selected


@pytest.mark.parametrize('volume_flags,matching_pac,selected', [
    (0, True, 0), (1, True, 1), (14, True, 0), (15, True, 1), (1, False, 0),
])
def test_volume_producer_flag_reopens_same_source_only_for_the_same_pac(volume_flags, matching_pac, selected):
    identity = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)
    volumes = PabvVolumes(3, (PabvVolume(0, 0, 123, identity, 1, 5, (.25, 2.), (), (), volume_flags),))
    skeleton = Skeleton(bones=[Bone(index=0, name='owned', name_hash=123)], bone_count=1)
    prepared = prepare_pabv_cloth_colliders(volumes, skeleton, flag_bone_sets={2: (), 4: (), 8: ()})
    bits = build_cloth_collision_group_flags(
        component_flags=0, critical_collidable=False, same_pac_collidable=prepared.has_activation_flag,
    )
    data = snapshots(1)
    data['extra_collidables'] = {11: group(count=1, flags=bits, srv=7, offset=100,
                                         pac=99 if matching_pac else 100)}
    data['collidables'] = {(7, 100): prepared.definitions[0]}
    before = copy.deepcopy(data)
    assert len(select(data)['candidates']) == selected
    assert data == before


def test_cached_token_has_reference_in_units_group_in_thousands_and_collider_in_millions():
    data = snapshots()
    cached(data, [9002004])
    struct.pack_into('<H', data['per_scene'], 74, 5)
    data['reference_collidables'] = {9: (3 << 16) | 11}
    data['extra_collidables'] = {13: group(count=10)}
    data['collidables'] = {(8, 209): definition()}
    selection = select(data)
    assert selection['cache_mode'] == 'cached'
    assert ordinals(selection) == [(4, 2, 9)]
    assert selection['candidates'][0]['group_index'] == 13


def test_consumed_ffffffff_token_resolves_to_zero_ordinals_instead_of_being_skipped():
    data = snapshots()
    cached(data, [0xFFFFFFFF])
    assert ordinals(select(data)) == [(0, 0, 0)]


@pytest.mark.parametrize('token,missing', [(1, 'reference_collidables'), (1000, 'extra_collidables'),
                                         (3000000, 'collidables')])
def test_stale_cached_ordinals_skip_at_each_bound_without_falling_back_to_full_scan(token, missing):
    data = snapshots()
    cached(data, [token])
    assert select(data, **{missing: None}) == {'cache_mode': 'cached', 'candidates': ()}


def test_invalid_reference_and_empty_cached_list_do_not_require_deeper_snapshots():
    data = snapshots()
    cached(data, [0])
    data['reference_collidables'][5] = 0xFFFFFFFF
    assert not select(data, extra_collidables=None, collidables=None)['candidates']
    cached(data, [])
    assert select(data, reference_collidables=None) == {'cache_mode': 'cached', 'candidates': ()}


@pytest.mark.parametrize('count,mode', [(4, 'cached'), (5, 'full'), (9, 'full')])
def test_overflow_counts_all_candidates_but_stores_only_four_and_never_rebuilds_a_valid_cache(count, mode):
    data = snapshots(count)
    before = copy.deepcopy(data)
    result = update(data, [(0, 0, i, -.1) for i in range(count)], working_flags=0x8000)
    words = struct.unpack('<10I', result['pre_collision'])
    assert words[:5] == (100, 101, 102, 103, 104)
    assert words[5] == count
    assert words[6:] == (0, 1000000, 2000000, 3000000)
    assert result['flags'] == 0x20008000
    assert data == before
    struct.pack_into('<I', data['particle'], 64, result['flags'])
    data['pre_collision'] = result['pre_collision']
    assert select(data)['cache_mode'] == mode
    unchanged = update(data, [(0, 0, 0, float('nan'))], working_flags=0)
    assert unchanged == {'flags': 0, 'pre_collision': result['pre_collision'], 'cache_mode': mode}


def test_cache_reuses_candidates_after_mask_change_but_rechecks_current_group_eligibility():
    data = snapshots()
    built = update(data, [(0, 0, 0, -.1), (0, 0, 2, .02)])
    struct.pack_into('<I', data['particle'], 64, built['flags'])
    struct.pack_into('<3I', data['simulation_parameter'], 64, 0, 0, 0)
    data['pre_collision'] = built['pre_collision']
    assert ordinals(select(data)) == [(0, 0, 0), (0, 0, 2)]
    assert not select(data, working_flags=0x10000)['candidates']
    struct.pack_into('<I', data['particle'], 64, 0)
    assert select(data) == {'cache_mode': 'rebuild', 'candidates': ()}


def test_positive_noncontact_plane_distance_is_cached_but_exact_point_zero_three_is_not():
    data = snapshots()
    surface, normal = cloth_collider_contact_surface((2., 0., 0.), collider_type=1,
                                                     center1=(0., 0., 0.), center2=None,
                                                     radius=1., thickness=0.)
    target = (1.02, 0., 0.)
    response = resolve_cloth_moving_contact(target, (2., 0., 0.), surface_position=surface,
                                            surface_normal=normal, collider_displacement=(0., 0., 0.),
                                            apply_tangential_damping=False)
    assert not response['contact']
    distance = sum((p - s)*n for p, s, n in zip(target, surface, normal))
    threshold = struct.unpack('<f', struct.pack('<f', .03))[0]
    result = update(data, [(4, 2, 9, distance), (1, 1, 1, threshold), (2, 2, 2, .031)])
    words = struct.unpack('<10I', result['pre_collision'])
    assert words[5:] == (1, 9002004, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF)


def test_empty_rebuild_marks_valid_and_preserves_both_unused_slots_and_other_half():
    data = snapshots()
    result = update(data, [])
    assert result['pre_collision'] == data['pre_collision']
    assert result['flags'] == 0x20000000


def test_wire_encoding_keeps_decimal_carry_and_uint32_overflow_without_inventing_field_clamps():
    words = struct.unpack('<10I', update(snapshots(), [(1000, 0, 0, -1.), (0, 0, 5000, -1.)])['pre_collision'])
    assert words[5:] == (2, 1000, 705032704, 0xFFFFFFFF, 0xFFFFFFFF)


@pytest.mark.parametrize('frame_flags,resource', [(0, 3), (0x10, 0xFFFF)])
def test_unavailable_cache_forces_full_search_even_with_original_valid_bit(frame_flags, resource):
    data = snapshots()
    cached(data, [])
    struct.pack_into('<I', data['per_frame'], 32, frame_flags)
    struct.pack_into('<H', data['simulation_parameter'], 226, resource)
    selection = select(data, pre_collision=None)
    assert selection['cache_mode'] == 'full'
    assert len(selection['candidates']) == 3


def test_cache_resource_65000_is_present_and_requires_the_resolved_buffer_zero_window():
    data = snapshots()
    struct.pack_into('<H', data['simulation_parameter'], 226, 65000)
    struct.pack_into('<H', data['per_scene'], 74, 0)
    with pytest.raises(ValueError, match='ten-uint'):
        select(data, pre_collision=None)
    assert select(data)['cache_mode'] == 'rebuild'


def test_guide_disabled_conditions_bypass_lists_and_cache_and_frame_override_reopens_them():
    data = snapshots()
    struct.pack_into('<H', data['per_scene'], 72, 0xFFFF)
    assert select(data, pre_collision=None, reference_collidables=None)['cache_mode'] == 'disabled'
    struct.pack_into('<H', data['per_scene'], 72, 5)
    struct.pack_into('<I', data['particle'], 64, 0x400)
    assert select(data, pre_collision=None, reference_collidables=None)['cache_mode'] == 'disabled'
    struct.pack_into('<I', data['per_frame'], 32, 0x20010)
    assert len(select(data)['candidates']) == 3


def test_base_reset_clears_valid_bit_and_reopens_rebuild_on_the_next_constraint_pass():
    data = snapshots()
    cached(data, [0, 1000000])
    struct.pack_into('<3f', data['particle'], 36, 1., 0., 0.)
    struct.pack_into('<3e', data['per_scene'], 100, 0., -1., 0.)
    reset = finalize_cloth_base_state(data['particle'], data['simulation_parameter'], data['per_frame'],
                                      data['per_scene'], non_gravity_acceleration=(0., 0., 0.),
                                      delta_time=.01, pre_collision=data['pre_collision'])
    data['particle'], data['pre_collision'] = reset['particle'], reset['pre_collision']
    assert select(data)['cache_mode'] == 'rebuild'
    assert struct.unpack('<10I', data['pre_collision'])[5:] == (0, *([0xFFFFFFFF]*4))


def test_own_source_requires_both_group_override_and_definition_matching_pac_flag():
    data = snapshots(1)
    data['extra_collidables'][11] = group(count=1, srv=7, offset=100)
    data['collidables'] = {(7, 100): definition(1)}
    assert not select(data)['candidates']
    struct.pack_into('<H', data['extra_collidables'][11], 0, 4)
    assert len(select(data)['candidates']) == 1
    data['collidables'][(7, 100)] = definition(0)
    assert not select(data)['candidates']
    data['collidables'][(7, 100)] = definition(1)
    struct.pack_into('<I', data['simulation_parameter'], 184, 0xFFFFFFFF)
    struct.pack_into('<I', data['extra_collidables'][11], 4, 0xFFFFFFFF)
    assert not select(data)['candidates']


@pytest.mark.parametrize('scene_flag,working_flag', [(1, 0), (0, 0x10000), (0, 0x20000)])
def test_group_bit_one_bypasses_selected_scene_and_working_particle_exclusions(scene_flag, working_flag):
    data = snapshots()
    struct.pack_into('<I', data['per_scene'], 64, scene_flag)
    assert not select(data, working_flags=working_flag)['candidates']
    struct.pack_into('<H', data['extra_collidables'][11], 0, 1)
    assert len(select(data, working_flags=working_flag)['candidates']) == 3
    struct.pack_into('<I', data['particle'], 64, 0x10000)
    struct.pack_into('<I', data['per_scene'], 64, 0)
    struct.pack_into('<H', data['extra_collidables'][11], 0, 0)
    assert len(select(data, working_flags=0)['candidates']) == 3


def test_same_scene_group_bit_one_is_excluded_by_frame_20_and_scene_200_combination():
    data = snapshots()
    struct.pack_into('<I', data['per_frame'], 32, 0x30)
    struct.pack_into('<I', data['per_scene'], 64, 0x200)
    struct.pack_into('<H', data['extra_collidables'][11], 0, 1)
    assert not select(data)['candidates']
    struct.pack_into('<I', data['extra_collidables'][11], 28, 0x20004)
    assert len(select(data)['candidates']) == 3


@pytest.mark.parametrize('lra,count', [(.25, 0), (.2998, 0), (.3, 3), (.5, 3)])
def test_group_bit_two_low_lra_exclusion_uses_frame_and_scene_flags(lra, count):
    data = snapshots()
    struct.pack_into('<I', data['per_frame'], 32, 0x20000010)
    struct.pack_into('<H', data['extra_collidables'][11], 0, 2)
    struct.pack_into('<e', data['particle'], 88, lra)
    assert len(select(data)['candidates']) == count
    struct.pack_into('<I', data['per_scene'], 64, 0x200)
    assert len(select(data)['candidates']) == 3


def test_mask_positions_include_skipped_groups_restart_per_reference_and_stop_at_95():
    data = snapshots()
    struct.pack_into('<3I', data['simulation_parameter'], 64, 1, 0, 0)
    struct.pack_into('<H', data['per_scene'], 74, 2)
    data['reference_collidables'] = {5: (2 << 16) | 11, 6: (1 << 16) | 12}
    data['extra_collidables'] = {11: group(count=95, srv=7, offset=100), 12: group()}
    assert ordinals(select(data)) == [(0, 1, 1), (0, 1, 2), (1, 0, 0)]


@pytest.mark.parametrize('bypass', ['other_scene', 'scene_flag', 'frame_flag'])
def test_uncached_mask_bypass_conditions(bypass):
    data = snapshots()
    struct.pack_into('<3I', data['simulation_parameter'], 64, 0, 0, 0)
    if bypass == 'other_scene':
        struct.pack_into('<I', data['extra_collidables'][11], 28, 0x20004)
    elif bypass == 'scene_flag':
        struct.pack_into('<I', data['per_scene'], 64, 0x40000)
    else:
        struct.pack_into('<I', data['per_frame'], 36, 0x400000)
    assert len(select(data)['candidates']) == 3


def test_resource_fallback_and_wrapped_elements_preserve_raw_ownership_identity():
    data = snapshots(2)
    struct.pack_into('<H', data['simulation_parameter'], 238, 0)
    struct.pack_into('<I', data['simulation_parameter'], 180, 0xFFFFFFFF)
    data['extra_collidables'][11] = group(count=2, srv=65000, offset=0xFFFFFFFF,
                                        uav=65001, result_offset=0xFFFFFFFF, scene=(65000 << 16) | 3)
    data['collidables'] = {(0, 0xFFFFFFFF): definition(), (0, 0): definition()}
    candidates = select(data)['candidates']
    assert [c['definition_key'] for c in candidates] == [(0, 0xFFFFFFFF), (0, 0)]
    assert [c['result_key'] for c in candidates] == [(0, 0xFFFFFFFF), (0, 0)]
    assert [c['scene_key'] for c in candidates] == [(0, 3), (0, 3)]
    struct.pack_into('<H', data['simulation_parameter'], 238, 65000)
    assert not select(data)['candidates']  # Same raw source now excludes the group.


def test_matching_pac_requires_raw_scene_identity_even_when_both_resources_select_buffer_zero():
    data = snapshots(1)
    struct.pack_into('<I', data['simulation_parameter'], 60, (65000 << 16) | 3)
    struct.pack_into('<I', data['extra_collidables'][11], 28, (65001 << 16) | 3)
    data['collidables'][(8, 200)] = definition(1)
    assert not select(data)['candidates']
    struct.pack_into('<I', data['extra_collidables'][11], 28, (65000 << 16) | 3)
    assert len(select(data)['candidates']) == 1


@pytest.mark.parametrize('missing,match', [('reference_collidables', 'reference entry'),
                                         ('extra_collidables', 'extra-collidable'),
                                         ('collidables', 'collidable-definition')])
def test_missing_consumed_records_raise_instead_of_silently_disabling_collisions(missing, match):
    with pytest.raises(ValueError, match=match):
        select(snapshots(), **{missing: None})
