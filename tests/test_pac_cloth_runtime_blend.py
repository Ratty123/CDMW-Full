"""Owned controller windows linking CPU LOD/fading to shader guide positions."""

import struct

import pytest

from cdmw.modding.pac_cloth_frames import select_guide_result_positions
from cdmw.modding.pac_cloth_runtime import (
    advance_cloth_frame_blend, select_cloth_simulation_lod, update_cloth_lod_state,
)


def controller(*, lod=3, direction=0, fade=.5, override=0., additive=0., transition=0.,
               timed_remaining=0., timed_amount=.25, inverted=False, previous_state=False):
    result = bytearray(range(64))
    struct.pack_into('<2b', result, 0, lod, direction)
    struct.pack_into('<6f', result, 4, fade, override, additive, transition, timed_remaining, timed_amount)
    result[0x38], result[0x39] = int(inverted), int(previous_state)
    return result


def frame():
    result = bytearray(range(100))
    struct.pack_into('<2e', result, 76, 0., 0.)
    return result


def scalar(record, offset):
    return struct.unpack_from('<f', record, offset)[0]


def direction(record):
    return struct.unpack_from('<b', record, 1)[0]


def blend(window=None, per_frame=None, **changes):
    options = dict(delta_time=.25, fade_reciprocal_denominator=5., minimum_fade_rate=1.,
                   elasticity_transition_duration=.5, scene_requests_natural_warmup=False,
                   need_natural_warmup=False, material_elasticity=0., ragdoll_active=False,
                   additive_ragdoll_elasticity=0., external_elasticity_ratio=0.)
    options.update(changes)
    return advance_cloth_frame_blend(controller() if window is None else window,
                                     frame() if per_frame is None else per_frame, **options)


def lod_state(window=None, **changes):
    options = dict(selected_lod=0, simulation_lod_limit=3, reset_fade=False, current_state_flag=False)
    options.update(changes)
    return update_cloth_lod_state(controller() if window is None else window, **options)


@pytest.mark.parametrize('ratio,expected', [(-1., 3), (.05, 3), (.1, 2), (.29, 2), (.3, 1), (.6, 0)])
def test_screen_ratio_thresholds_are_strict_and_not_clamped(ratio, expected):
    assert select_cloth_simulation_lod(ratio, material_scale=1., apply_material_scale=True,
                                      global_scale=1., thresholds=(.1, .3, .6), forced_lod=-1) == expected


def test_lod_scaling_requires_live_material_and_preserves_threshold_order():
    arguments = dict(material_scale=2., global_scale=1.4, thresholds=(.1, .3, .6), forced_lod=-1)
    assert select_cloth_simulation_lod(.25, apply_material_scale=True, **arguments) == 0
    assert select_cloth_simulation_lod(.25, apply_material_scale=False, **arguments) == 1
    arguments['thresholds'] = (.6, .1, .3)
    assert select_cloth_simulation_lod(.25, apply_material_scale=False, **arguments) == 3


@pytest.mark.parametrize('forced,expected', [(0x101, 1), (0xFF, -1), (-254, 2)])
def test_forced_lod_uses_signed_low_byte_without_consuming_the_score_path(forced, expected):
    assert select_cloth_simulation_lod(None, material_scale=None, apply_material_scale=True,
                                      global_scale=None, thresholds=(), forced_lod=forced) == expected


def test_lod_reactivation_updates_direction_and_returns_external_side_effects():
    window = controller(override=.75, previous_state=True)
    before = bytes(window)
    result = lod_state(window)
    after = result['controller_window']
    assert after[0] == 0 and direction(after) == -1
    assert scalar(after, 8) == 0. and after[0x39] == 0
    assert result['reactivated'] and result['reset_resource_103']
    assert result['lod_changed'] and result['increment_count_1c8']
    owned = {0, 1, 8, 9, 10, 11, 0x39}
    assert all(after[i] == before[i] for i in range(64) if i not in owned)
    assert bytes(window) == before


@pytest.mark.parametrize('old_lod,new_lod,old_direction,fade,expected_direction,count', [
    (0, 3, -1, .5, 1, True), (0, 1, -1, 1., -1, True),
    (3, 3, 0, 1., 0, False), (3, 3, 0, .99, 0, True),
])
def test_lod_crossings_and_stored_fade_control_the_count_request(old_lod, new_lod, old_direction, fade,
                                                               expected_direction, count):
    window = controller(lod=old_lod, direction=old_direction, fade=fade, previous_state=True)
    result = lod_state(window, selected_lod=new_lod)
    assert direction(result['controller_window']) == expected_direction
    assert result['increment_count_1c8'] is count
    if new_lod >= 3:
        assert result['controller_window'][0x39] == 1  # Inactive path does not consume caller state.
        assert not result['reset_resource_103']


def test_explicit_early_force_branch_clears_fade_but_keeps_reactivation_side_effects():
    result = lod_state(controller(direction=1), reset_fade=True)
    assert direction(result['controller_window']) == 0
    assert result['reactivated'] and result['lod_changed']


@pytest.mark.parametrize('initial_direction,start,boundary', [(1, .75, 1.), (-1, .25, 0.)])
def test_fade_clears_direction_only_after_crossing_its_boundary(initial_direction, start, boundary):
    first = blend(controller(direction=initial_direction, fade=start))
    assert first['values']['fading_ratio'] == boundary
    assert direction(first['controller_window']) == initial_direction
    second = blend(first['controller_window'], first['per_frame'])
    assert second['values']['fading_ratio'] == boundary
    assert direction(second['controller_window']) == 0
    third = blend(second['controller_window'], second['per_frame'])
    assert third['values']['fading_ratio'] == 0.
    assert scalar(third['controller_window'], 4) == boundary


def test_fade_uses_maximum_of_reciprocal_and_minimum_rate():
    result = blend(controller(direction=1, fade=0.), fade_reciprocal_denominator=.5, minimum_fade_rate=1.)
    assert result['values']['fading_ratio'] == .5
    result = blend(controller(direction=1, fade=0.), fade_reciprocal_denominator=5., minimum_fade_rate=3.)
    assert result['values']['fading_ratio'] == .75


def test_inactive_fade_uploads_zero_and_preserves_stored_value_without_reading_rate_globals():
    window = controller(fade=1.)
    result = blend(window, fade_reciprocal_denominator=None, minimum_fade_rate=None)
    assert result['values']['fading_ratio'] == 0.
    assert scalar(result['controller_window'], 4) == 1.


@pytest.mark.parametrize('scene,material,expected', [(True, True, 0.), (False, True, .25), (True, False, .25)])
def test_natural_warmup_requires_both_flags_and_keeps_the_direction(scene, material, expected):
    result = blend(controller(direction=-1), scene_requests_natural_warmup=scene, need_natural_warmup=material)
    assert result['values']['fading_ratio'] == expected
    assert scalar(result['controller_window'], 4) == expected
    assert direction(result['controller_window']) == -1


def test_natural_warmup_excludes_positive_direction_until_it_is_cleared():
    options = dict(scene_requests_natural_warmup=True, need_natural_warmup=True)
    first = blend(controller(direction=1, fade=.75), **options)
    assert first['values']['fading_ratio'] == 1.
    second = blend(first['controller_window'], **options)
    assert second['values']['fading_ratio'] == 0.
    assert scalar(second['controller_window'], 4) == 0.
    assert direction(second['controller_window']) == 0


@pytest.mark.parametrize('inverted,expected', [(False, 0.), (True, 1.)])
def test_elasticity_transition_updates_at_expiry_then_retains_the_result(inverted, expected):
    first = blend(controller(transition=.25, additive=.75, inverted=inverted))
    assert scalar(first['controller_window'], 0x10) == 0.
    assert scalar(first['controller_window'], 0xC) == expected
    assert first['values']['elasticity'] == expected
    second = blend(first['controller_window'], elasticity_transition_duration=None)
    assert second['values']['elasticity'] == expected


def test_timed_elasticity_only_contributes_after_decrement_if_time_remains():
    first = blend(controller(timed_remaining=.5, timed_amount=.5), material_elasticity=.25)
    assert first['values']['elasticity'] == .75
    second = blend(first['controller_window'], material_elasticity=.25)
    assert second['values']['elasticity'] == .25
    assert scalar(second['controller_window'], 0x14) == 0.


def test_elasticity_addends_clamp_before_two_ordered_unclamped_overrides():
    result = blend(controller(additive=.125, timed_remaining=1., timed_amount=.125, override=.5),
                   material_elasticity=.125, ragdoll_active=True, additive_ragdoll_elasticity=.125,
                   external_elasticity_ratio=.5)
    assert result['values']['elasticity'] == .875
    result = blend(controller(override=.5), material_elasticity=-2., external_elasticity_ratio=2.)
    assert result['values']['elasticity'] == 1.5
    result = blend(controller(), material_elasticity=.25, ragdoll_active=False,
                   additive_ragdoll_elasticity=10.)
    assert result['values']['elasticity'] == .25


def test_frame_upload_preserves_other_fields_and_all_source_records():
    window, data = controller(direction=1, fade=.25), frame()
    before = bytes(window), bytes(data)
    result = blend(window, data, material_elasticity=.5)
    assert struct.unpack_from('<2e', result['per_frame'], 76) == (.5, .5)
    assert result['updated_offsets'] == (76, 78)
    assert result['per_frame'][:76] == before[1][:76]
    assert result['per_frame'][80:] == before[1][80:]
    assert (bytes(window), bytes(data)) == before


def test_lod_reactivation_fade_feeds_the_existing_guide_result_blend():
    state = lod_state(controller(lod=3, fade=1.))
    runtime = blend(state['controller_window'])
    fading = struct.unpack_from('<e', runtime['per_frame'], 78)[0]
    assert fading == .75
    positions = select_guide_result_positions(
        [(10., 0., 0.)], [(2., 0., 0.)], [(6., 0., 0.)],
        per_frame_flags2=0, interpolation_ratio=.5, animation_blend=fading)
    assert positions == ((8.5, 0., 0.),)


def test_invalid_consumed_runtime_values_are_rejected():
    with pytest.raises(ValueError, match='complete 64-byte'):
        blend(controller()[:-1])
    with pytest.raises(ValueError, match='nonnegative'):
        blend(delta_time=-1.)
    with pytest.raises(ValueError, match='positive reciprocal denominator'):
        blend(controller(direction=1), fade_reciprocal_denominator=0.)
    with pytest.raises(ValueError, match='positive duration'):
        blend(controller(transition=1.), elasticity_transition_duration=0.)
    with pytest.raises(ValueError, match='explicit booleans'):
        blend(need_natural_warmup=1)
    with pytest.raises(ValueError, match='storage range'):
        lod_state(selected_lod=128)
