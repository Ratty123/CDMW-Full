"""Analytic CPU-to-shader scenarios using owned material and frame values."""

import math
import struct

import pytest

from cdmw.modding.pac_cloth_constraints import cloth_stretch_corrections
from cdmw.modding.pac_cloth_runtime import (
    build_cloth_collision_group_flags, build_cloth_material_collision_mask,
    select_cloth_constraint_dispatches, select_cloth_dispatch_schedule,
    update_cloth_frame_stiffness, update_cloth_iteration_bits, update_cloth_material_frame_flags,
)
from cdmw.modding.pac_cloth_state import select_cloth_base_substep


def dispatch_globals(*, ordinary=2, scaled=4, maximum=6, active=1, reverse=0):
    data = bytearray(1216)
    for offset, value in ((816, active), (824, maximum), (884, ordinary),
                          (916, scaled), (1148, reverse)):
        struct.pack_into('<I', data, offset, value)
    for offset in (864, 896):
        struct.pack_into('<f', data, offset, 1 / 60)
    # Deliberately distinct category dimensions reveal wrong category selection
    # and the 64-thread linear versus 32-thread triangle dispatch boundaries.
    for category in range(40):
        struct.pack_into('<I', data, 160 + category * 4, category + 1)
        struct.pack_into('<I', data, 320 + category * 4, 65 + category)
    return bytes(data)


def schedule(data=None, **changes):
    args = dict(dispatch_mode=0, solver_iterations=5,
                mode1_iteration_limit=3, mode1_substep_limit=1)
    return select_cloth_dispatch_schedule(dispatch_globals() if data is None else data,
                                          **(args | changes))


def test_dispatch_loop_counts_keep_both_clocks_and_mode1_caps_before_even_rounding():
    ordinary = schedule()
    assert ordinary == dict(substep_count=4, selected_iteration_count=5, iteration_count=6,
                            movement_enabled=True, constraints_enabled=True,
                            initialize_static_vertices_enabled=False,
                            layer_collision_points_enabled=True)
    limited = schedule(dispatch_mode=1)
    assert limited['substep_count'] == 1
    assert limited['selected_iteration_count'] == 3
    assert limited['iteration_count'] == 4
    assert limited['initialize_static_vertices_enabled']
    assert not limited['layer_collision_points_enabled']
    assert schedule(dispatch_globals(maximum=1))['iteration_count'] == 2


def test_dispatch_loop_does_not_override_per_model_clock_admission():
    globals_ = dispatch_globals()
    scene = bytearray(108)
    struct.pack_into('<e', scene, 94, 1)
    counts = []
    for flags2 in (0, 0x8000):
        frame_ = bytearray(100)
        struct.pack_into('<I', frame_, 36, flags2)
        counts.append(sum(select_cloth_base_substep(frame_, scene, globals_, substep_index=index)
                          is not None for index in range(schedule(globals_)['substep_count'])))
    assert counts == [2, 4]
    empty = dispatch_globals(ordinary=0, scaled=0)
    assert schedule(empty)['substep_count'] == 1
    assert select_cloth_base_substep(bytes(100), scene, empty, substep_index=0) is None


@pytest.mark.parametrize('offset', [808, 816, 820])
def test_dispatch_enable_uses_each_global_work_counter(offset):
    data = bytearray(dispatch_globals(active=0))
    assert not schedule(data)['movement_enabled']
    struct.pack_into('<I', data, offset, 1)
    assert schedule(data)['movement_enabled']
    zero_iterations = schedule(data, solver_iterations=0)
    assert zero_iterations['iteration_count'] == 0
    assert zero_iterations['movement_enabled']
    assert not zero_iterations['constraints_enabled']


def test_dispatch_count_summary_preserves_uint32_wrap_without_materializing_work():
    result = schedule(dispatch_globals(ordinary=0xFFFFFFFF, maximum=0xFFFFFFFF),
                      solver_iterations=0xFFFFFFFF)
    assert result['substep_count'] == 0xFFFFFFFF
    assert result['selected_iteration_count'] == 0xFFFFFFFF
    assert result['iteration_count'] == 0
    assert result['constraints_enabled']


def test_constraint_dispatch_order_dimensions_and_ping_pong_slots():
    first = select_cloth_constraint_dispatches(dispatch_globals(), dispatch_mode=0,
                                               iteration=1, iteration_count=6, enabled=True)
    assert [row['shader'] for row in first] == [
        'ComputePbdProcessConstraints', 'ComputeTriangleFrameBeforeADMM',
        'ComputeTriangleADMMPrimalUpdate', 'ComputeTriangleADMMVertexConsensus',
        'ComputeTriangleADMMDualUpdate',
    ]
    assert [row['category'] for row in first] == [27, 8, 8, 9, 8]
    assert [row['groups'] for row in first] == [(2, 28, 1), (3, 9, 1), (3, 9, 1),
                                               (3, 10, 1), (3, 9, 1)]
    assert all((row['input_slot'], row['output_slot']) == (0, 1) for row in first)
    second = select_cloth_constraint_dispatches(dispatch_globals(), dispatch_mode=1,
                                                iteration=2, iteration_count=6, enabled=False)
    assert [row['category'] for row in second] == [28, 10, 10, 11, 10]
    assert all(row['groups'][2] == 0 for row in second)
    assert all((row['input_slot'], row['output_slot']) == (1, 0) for row in second)


@pytest.mark.parametrize('mode,expected', [(0, [34, 33, 32, 31, 27, 27]),
                                         (1, [38, 37, 36, 35, 28, 28])])
def test_reversed_iterations_change_only_linear_category_and_keep_cpu_parity(mode, expected):
    globals_ = dispatch_globals(reverse=2)  # CPU tests nonzero, not equality to one.
    rows = [select_cloth_constraint_dispatches(globals_, dispatch_mode=mode, iteration=i,
                                              iteration_count=6, enabled=True) for i in range(1, 7)]
    assert [row[0]['category'] for row in rows] == expected
    assert [row[0]['input_slot'] for row in rows] == [0, 1, 0, 1, 0, 1]
    assert all(row[1]['category'] == 8 + 2 * mode for row in rows)


def test_dispatch_uint_addition_and_empty_category_do_not_invent_gpu_work():
    data = bytearray(dispatch_globals())
    struct.pack_into('<I', data, 320 + 27 * 4, 0xFFFFFFFF)
    struct.pack_into('<I', data, 160 + 8 * 4, 0)
    rows = select_cloth_constraint_dispatches(data, dispatch_mode=0, iteration=1,
                                             iteration_count=2, enabled=True)
    assert rows[0]['groups'] == (0, 28, 1)
    assert rows[1]['groups'] == (3, 0, 1)


@pytest.mark.parametrize('changes', [
    {'dispatch_mode': True}, {'dispatch_mode': 2}, {'solver_iterations': -1},
    {'mode1_iteration_limit': 1.5}, {'mode1_substep_limit': 0x100000000},
])
def test_schedule_requires_resolved_stored_inputs(changes):
    with pytest.raises(ValueError):
        schedule(**changes)


@pytest.mark.parametrize('changes', [
    {'dispatch_mode': -1}, {'iteration': 0}, {'iteration': 7}, {'iteration_count': 5},
    {'enabled': 1}, {'dispatch_mode': 1, 'iteration_count': 10, 'iteration': 10},
])
def test_constraint_dispatch_rejects_untraced_or_out_of_table_inputs(changes):
    args = dict(dispatch_mode=0, iteration=1, iteration_count=6, enabled=True)
    with pytest.raises(ValueError):
        select_cloth_constraint_dispatches(dispatch_globals(), **(args | changes))


def test_dispatch_references_require_complete_global_records():
    with pytest.raises(ValueError, match='1216-byte'):
        schedule(bytes(1215))
    with pytest.raises(ValueError, match='1216-byte'):
        select_cloth_constraint_dispatches(bytes(1217), dispatch_mode=0,
                                           iteration=1, iteration_count=2, enabled=True)


def collision_mask(keys=(), *, include=(), exclude=(), temporary=()):
    return build_cloth_material_collision_mask(
        keys, inclusion_bone_hashes=include, exclusion_bone_hashes=exclude,
        temporary_fix_exclusion_bone_hashes=temporary,
    )


def material_flags(data=None, **changes):
    args = dict(use_rotation_correction=False, is_cloak=False,
                shrink_when_shield_is_in_socket=False, use_input_position_collision=False,
                rotation_correction_enabled=False, cloak_enabled=False)
    return update_cloth_material_frame_flags(bytes(100) if data is None else data, **(args | changes))


@pytest.mark.parametrize('material_switch,runtime_switch,mask', [
    ('use_rotation_correction', 'rotation_correction_enabled', 0x4000),
    ('is_cloak', 'cloak_enabled', 0x20000000),
])
@pytest.mark.parametrize('material,runtime', [(False, False), (False, True), (True, False), (True, True)])
def test_material_frame_branches_require_both_authored_and_runtime_enables(
    material_switch, runtime_switch, mask, material, runtime,
):
    result = material_flags(**{material_switch: material, runtime_switch: runtime})
    assert struct.unpack_from('<I', result['per_frame'], 32)[0] == (mask if material and runtime else 0)


def test_material_flags_clear_stale_bits_preserve_unrelated_state_and_only_invalidate_changes():
    data = bytearray(range(100))
    struct.pack_into('<2I', data, 32, 0xFFFFFFFF, 0xFFFFFFFF)
    before = bytes(data)
    cleared = material_flags(data)
    assert struct.unpack_from('<2I', cleared['per_frame'], 32) == (0xDFFFBFDF, 0xFFFDFFFF)
    assert cleared['updated_offsets'] == (32, 36) and cleared['upload_invalidated']
    assert cleared['per_frame'][:32] == before[:32] and cleared['per_frame'][40:] == before[40:]
    assert bytes(data) == before
    unchanged = material_flags(cleared['per_frame'])
    assert unchanged['per_frame'] == cleared['per_frame']
    assert unchanged['updated_offsets'] == () and not unchanged['upload_invalidated']
    enabled = material_flags(cleared['per_frame'], use_rotation_correction=True, is_cloak=True,
                             shrink_when_shield_is_in_socket=True, use_input_position_collision=True,
                             rotation_correction_enabled=True, cloak_enabled=True)
    assert enabled['per_frame'] == before


@pytest.mark.parametrize('field', [
    'use_rotation_correction', 'is_cloak', 'shrink_when_shield_is_in_socket',
    'use_input_position_collision', 'rotation_correction_enabled', 'cloak_enabled',
])
def test_material_frame_flags_reject_implicit_boolean_inputs(field):
    with pytest.raises(ValueError, match='explicit booleans'):
        material_flags(**{field: 1})


@pytest.mark.parametrize('material,global_enabled', [(False, False), (False, True), (True, False), (True, True)])
def test_long_range_attachment_flag_requires_material_and_runtime_switch(material, global_enabled):
    data = bytearray(100)
    struct.pack_into('<I', data, 32, 0x80000088)
    result = material_flags(bytes(data), use_lra_constraint=material, lra_constraint_enabled=global_enabled)
    assert struct.unpack_from('<I', result['per_frame'], 32)[0] == (
        0x80000008 | (0x80 if material and global_enabled else 0))
    assert bytes(data)[32:36] == struct.pack('<I', 0x80000088)


@pytest.mark.parametrize('enabled', [False, True])
def test_backstop_flag_is_explicit_and_preserves_unselected_lra_bit(enabled):
    data = bytearray(100)
    struct.pack_into('<I', data, 32, 0x80000088)
    result = material_flags(bytes(data), use_back_stop_collision=enabled)
    assert struct.unpack_from('<I', result['per_frame'], 32)[0] == (0x80000080 | (8 if enabled else 0))
    assert result['upload_invalidated'] is not enabled


@pytest.mark.parametrize('changes', [
    {'use_back_stop_collision': 1}, {'use_lra_constraint': True},
    {'lra_constraint_enabled': True}, {'use_lra_constraint': 1, 'lra_constraint_enabled': False},
])
def test_optional_collision_flags_never_infer_missing_or_nonboolean_runtime_inputs(changes):
    with pytest.raises(ValueError, match='explicit booleans'):
        material_flags(**changes)


def test_collision_mask_without_inclusions_preserves_unused_slots_and_excludes_matches():
    assert collision_mask() == (0xFFFFFFFF,) * 3
    assert collision_mask((10, 20, 30), exclude=(20, 999), temporary=(30,)) == (
        0xFFFFFFF9, 0xFFFFFFFF, 0xFFFFFFFF,
    )


def test_collision_exclusions_win_over_inclusions_and_repeated_hashes_keep_their_slots():
    keys, include, exclude, temporary = [10, 20, 30, 10], [30, 10, 20, 10], [20], [30]
    assert collision_mask(keys, include=include, exclude=exclude, temporary=temporary) == (9, 0, 0)
    assert (keys, include, exclude, temporary) == ([10, 20, 30, 10], [30, 10, 20, 10], [20], [30])


def test_collision_mask_word_boundaries_and_96_slot_limit():
    keys = tuple(range(1000, 1100))
    include = tuple(keys[index] for index in (0, 31, 32, 63, 64, 95, 96))
    assert collision_mask(keys, include=include) == (0x80000001,) * 3
    assert collision_mask(keys, include=include, exclude=(keys[64], keys[96])) == (
        0x80000001, 0x80000001, 0x80000000,
    )


def test_collision_sentinel_skips_matching_but_consumes_a_slot_and_counts_as_an_inclusion():
    keys = (0xFFFFFFFF, 10, 20, 10)
    assert collision_mask(keys, include=(10,)) == (10, 0, 0)
    assert collision_mask(keys, include=(0xFFFFFFFF,)) == (0, 0, 0)
    assert collision_mask(keys, exclude=(0xFFFFFFFF, 10)) == (0xFFFFFFF5, 0xFFFFFFFF, 0xFFFFFFFF)


@pytest.mark.parametrize('values', [(-1,), (0x100000000,), (True,), (1.5,)])
@pytest.mark.parametrize('field', ['keys', 'include', 'exclude', 'temporary'])
def test_collision_mask_rejects_non_uint32_hashes(values, field):
    with pytest.raises(ValueError, match='storage range'):
        collision_mask(**{field: values})


@pytest.mark.parametrize('changes,message', [
    ({'component_flags': 256}, 'storage range'),
    ({'component_flags': -1}, 'storage range'),
    ({'critical_collidable': 1}, 'explicit booleans'),
    ({'same_pac_collidable': None}, 'explicit booleans'),
])
def test_collision_group_requires_resolved_byte_and_boolean_inputs(changes, message):
    args = dict(component_flags=0, critical_collidable=False, same_pac_collidable=False)
    with pytest.raises(ValueError, match=message):
        build_cloth_collision_group_flags(**(args | changes))


def frame(*, stretch=0., bend=-1., area=0., restore=-1., underwater=-1., flags2=0):
    result = bytearray(range(100))
    for offset, value in zip((66, 68, 70, 72, 94), (stretch, bend, area, restore, underwater)):
        struct.pack_into('<e', result, offset, value)
    struct.pack_into('<I', result, 36, flags2)
    return result


def stiffness(data=None, **changes):
    arguments = dict(simulation_mode=2, stretching_stiffness=0., bending_stiffness=0.,
                     area_stiffness=0., restore_angle_stiffness=0., underwater_restore_angle_stiffness=-1.,
                     stiffness_denominator=2., scale_factors=(1., 1., 1., 1.), limits=(1., 1., 1., 1.),
                     bend_uses_unit_denominator=False)
    arguments.update(changes)
    return update_cloth_frame_stiffness(frame() if data is None else data, **arguments)


def iterations(data=None, **changes):
    arguments = dict(simulation_lod=0, material_solver_iterations=6, material_over_iteration_skip_lod=-1,
                     global_solver_iterations=4, global_over_iteration_skip_lod=2)
    arguments.update(changes)
    return update_cloth_iteration_bits(frame() if data is None else data, **arguments)


def half(data, offset):
    return struct.unpack_from('<e', data, offset)[0]


def test_positive_stiffness_uses_exponential_conversion_before_half_upload():
    data = frame()
    before = bytes(data)
    result = stiffness(data, stretching_stiffness=.75, bending_stiffness=.75, area_stiffness=.75,
                       restore_angle_stiffness=.75, underwater_restore_angle_stiffness=.9375)
    assert tuple(result['values'].values()) == (.5, .5, .5, .5, .75)
    assert tuple(half(result['per_frame'], offset) for offset in (66, 68, 70, 72, 94)) == (.5, .5, .5, .5, .75)
    assert result['updated_offsets'] == (66, 68, 70, 72, 94)
    assert result['upload_invalidated']
    owned = {66, 67, 68, 69, 70, 71, 72, 73, 94, 95}
    assert all(result['per_frame'][i] == before[i] for i in range(100) if i not in owned)
    assert bytes(data) == before


@pytest.mark.parametrize('mode,expected', [(1, .4), (2, .99), (0, .99)])
def test_mode_caps_stretch_and_bend_but_area_and_restore_have_their_own_cap(mode, expected):
    result = stiffness(simulation_mode=mode, stretching_stiffness=2., bending_stiffness=2.,
                       area_stiffness=2., restore_angle_stiffness=2., stiffness_denominator=1.)
    assert tuple(result['values'].values()) == pytest.approx((expected, expected, 1., 1., 1.))


@pytest.mark.parametrize('enabled,expected', [(False, .5), (True, .75)])
def test_bend_runtime_switch_only_replaces_its_denominator(enabled, expected):
    result = stiffness(stretching_stiffness=.75, bending_stiffness=.75, area_stiffness=.75,
                       restore_angle_stiffness=.75, bend_uses_unit_denominator=enabled)
    assert tuple(result['values'].values()) == (.5, expected, .5, .5, .5)


def test_decoded_initial_global_values_remain_explicit_inputs():
    # Initialization constants are evidence of defaults, not captured live state.
    result = stiffness(simulation_mode=1, stretching_stiffness=.99, bending_stiffness=.25,
                       area_stiffness=.75, restore_angle_stiffness=.75, stiffness_denominator=4.,
                       scale_factors=(5., 1., 1., 1.), limits=(.6, .06, .6, .06),
                       bend_uses_unit_denominator=True)
    assert tuple(result['values'].values()) == pytest.approx(
        (1. - .6 ** 1.25, .06, 1. - .25 ** .25, .06, .06), abs=1e-7)
    assert half(result['per_frame'], 68) == .05999755859375


@pytest.mark.parametrize('value', [0., -1., -100.])
def test_nonpositive_stiffness_has_distinct_zero_and_minus_one_results(value):
    result = stiffness(stretching_stiffness=value, bending_stiffness=value, area_stiffness=value,
                       restore_angle_stiffness=value, underwater_restore_angle_stiffness=value)
    assert tuple(result['values'].values()) == (0., -1., 0., -1., -1.)
    assert not result['upload_invalidated']


@pytest.mark.parametrize('water,expected', [(-1., .5), (0., -1.), (.9375, .75)])
def test_underwater_restore_uses_raw_ordinary_value_only_for_negative_override(water, expected):
    result = stiffness(restore_angle_stiffness=.75, underwater_restore_angle_stiffness=water)
    assert result['values']['modified_restore_angle_stiffness'] == .5
    # Transforming the already-modified ordinary value again would yield ~.293.
    assert result['values']['modified_underwater_restore_angle_stiffness'] == expected


@pytest.mark.parametrize('difference,invalidated', [(2. ** -23, False), (2. ** -22, True)])
def test_upload_threshold_precedes_half_packing_and_can_invalidate_identical_bytes(difference, invalidated):
    data = frame(stretch=.5)
    result = stiffness(data, stretching_stiffness=.5 + difference, stiffness_denominator=1.)
    assert result['upload_invalidated'] is invalidated
    assert result['updated_offsets'] == ((66,) if invalidated else ())
    assert result['per_frame'] == bytes(data)


def test_unordered_previous_half_is_repaired_when_comparing_upload_values():
    data = frame()
    struct.pack_into('<H', data, 66, 0x7FFF)
    result = stiffness(data, stretching_stiffness=.75)
    assert result['updated_offsets'] == (66,)
    assert half(result['per_frame'], 66) == .5
    assert math.isnan(half(data, 66))


def test_uploaded_coefficient_drives_existing_stretch_projection():
    result = stiffness(stretching_stiffness=.75)
    coefficient = half(result['per_frame'], 66)
    corrections = cloth_stretch_corrections(
        ((0., 0., 0.), (2., 0., 0.)), animation_positions=((0., 0., 0.), (1., 0., 0.)),
        inverse_masses=(0., 1.), lra_ratios=(0., 1.), stiffness=(coefficient, coefficient),
        reference_length=1., uploaded_inverse_mass_sum=1., bone_scale=1., stretching_scale=1.,
        length_smoothing_byte=0, follow_the_leader_ratio=0., per_frame_flags=0,
        particle_flags=(0, 0), particle_extra_flags=(0, 0))
    assert corrections[0] == (0., 0., 0.)
    assert corrections[1] == (-.5, 0., 0.)  # Raw .75 would incorrectly produce -.75.


@pytest.mark.parametrize('changes,expected', [
    ({}, 4), ({'simulation_lod': 1}, 4), ({'simulation_lod': 2}, 2),
    ({'material_over_iteration_skip_lod': 0}, 2),
    ({'material_over_iteration_skip_lod': 3, 'simulation_lod': 2}, 4),
    ({'material_solver_iterations': 2}, 2),
    ({'material_solver_iterations': 0x10002}, 2),
    ({'material_solver_iterations': 0}, 0),
    ({'material_over_iteration_skip_lod': -10, 'global_over_iteration_skip_lod': 0}, 2),
])
def test_iteration_limits_keep_lod_override_and_low_word_rules(changes, expected):
    data = frame(flags2=0xA5A51000)
    before = bytes(data)
    result = iterations(data, **changes)
    assert result['selected_limit'] == expected
    assert result['iteration_bits'] == expected
    assert struct.unpack_from('<I', result['per_frame'], 36)[0] == 0xA5A51000 | expected
    assert result['per_frame'][:36] == before[:36]
    assert result['per_frame'][40:] == before[40:]
    assert bytes(data) == before


def test_iteration_invalidation_compares_full_selected_limit_before_encoding():
    unchanged = iterations(frame(flags2=0x80000004))
    assert not unchanged['upload_invalidated']
    data = frame(flags2=0x80000000)
    masked = iterations(data, material_solver_iterations=8, global_solver_iterations=8)
    assert masked['selected_limit'] == 8 and masked['iteration_bits'] == 0
    assert masked['upload_invalidated']
    assert masked['per_frame'] == bytes(data)


def test_invalid_inputs_are_rejected_without_repairing_missing_runtime_choices():
    with pytest.raises(ValueError, match='complete 100-byte'):
        stiffness(frame()[:-1])
    with pytest.raises(ValueError, match='positive'):
        stiffness(stiffness_denominator=0.)
    with pytest.raises(ValueError, match='stretch, bend, area and restore'):
        stiffness(scale_factors=(1., 1., 1.))
    with pytest.raises(ValueError, match='explicit booleans'):
        stiffness(bend_uses_unit_denominator=1)
    with pytest.raises(ValueError, match='finite float32'):
        stiffness(stretching_stiffness=float('inf'))
    with pytest.raises(ValueError, match='storage range'):
        iterations(simulation_lod=128)
    with pytest.raises(ValueError, match='storage range'):
        iterations(global_solver_iterations=0x10000)
