"""Owned collider snapshots with analytic plane projections and selection cases."""

import struct

import pytest

from cdmw.modding.pac_cloth_collisions import apply_cloth_input_collisions
from cdmw.modding.pac_cloth_runtime import build_cloth_material_collision_mask
from cdmw.modding.pac_cloth_state import select_cloth_base_integration


def fixture(*, mode=4, count=1, radius=.25, anchor=(.05, -.2, 0.), thickness=.125):
    particle = bytearray(range(152))
    parameter, frame, scene, globals_ = bytearray(312), bytearray(100), bytearray(108), bytearray(1216)
    struct.pack_into('<3f', particle, 0, *anchor)
    struct.pack_into('<fI', particle, 60, 1., 0x8000)
    struct.pack_into('<e', particle, 88, .2)
    struct.pack_into('<I', parameter, 60, 0x10002)
    struct.pack_into('<3I', parameter, 64, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF)
    struct.pack_into('<2I', parameter, 180, 10, 42)
    struct.pack_into('<if', parameter, 196, mode, thickness)
    struct.pack_into('<H', parameter, 216, 0xFFFF)
    struct.pack_into('<H', parameter, 238, 5)
    struct.pack_into('<2I', frame, 32, 0x20000000, 0x20000)
    struct.pack_into('<I', scene, 64, 0x200)
    struct.pack_into('<2H', scene, 72, 7, 1)
    struct.pack_into('<2I', globals_, 1200, 1, 1)
    group = bytearray(56)
    struct.pack_into('<2H3I', group, 0, 2, count, 42, 6, 7)
    struct.pack_into('<3I', group, 28, 0x20003, 20, 30)
    other = bytearray(108)
    struct.pack_into('<I', other, 68, 0x10002)
    results, definitions = {}, {}
    for index in range(count):
        result, definition = bytearray(56), bytearray(104)
        struct.pack_into('<f', result, 4, radius)
        struct.pack_into('<3f', result, 44, 0., -1., 0.)
        struct.pack_into('<H', definition, 2, 3)
        results[7, 30 + index], definitions[6, 20 + index] = result, definition
    return dict(particle=particle, simulation_parameter=parameter, per_frame=frame, per_scene=scene,
                global_parameters=globals_, reference_collidables={7: 0x1000B},
                extra_collidables={11: group}, scene_objects={(2, 3): other},
                collidable_results=results, collidables=definitions)


def run(data):
    return apply_cloth_input_collisions(**data)


def position(result):
    return struct.unpack_from('<3f', result['particle'])


def flags(result):
    return struct.unpack_from('<I', result['particle'], 64)[0]


def snapshot(data):
    return {key: {k: bytes(v) if isinstance(v, bytearray) else v for k, v in value.items()}
            if isinstance(value, dict) else bytes(value) for key, value in data.items()}


@pytest.mark.parametrize('mode,height,contact', [
    (0, .125, True), (1, .125, True), (2, .125, True), (3, .125, True),
    (4, .125, True), (5, .125, True), (6, .125, True), (7, .125, True),
    (8, .125, True), (9, .14, True), (10, .05, True), (11, .03, True),
    (12, .125, True), (13, .08, True), (14, .01, True), (15, .02, True),
    (16, .03, True), (17, .125, True), (18, .03, True), (19, .01, False),
    (20, .175, True), (21, .125, True), (22, .02, True), (23, .02, True),
])
def test_single_collider_modes_project_to_the_decoded_plane_height(mode, height, contact):
    data = fixture(mode=mode)
    before = snapshot(data)
    result = run(data)
    assert result['active'] and result['projected_colliders'] == 1
    assert position(result) == pytest.approx((.05, height, 0.))
    assert flags(result) == 0x8000 | (0x41000000 if contact else 0)
    allowed = set(range(12)) | set(range(64, 68))
    assert all(result['particle'][i] == before['particle'][i] for i in range(152) if i not in allowed)
    assert snapshot(data) == before


@pytest.mark.parametrize('mode,height,contact', [
    (0, .155, True), (1, .155, True), (-1, .155, True), (6, -.05, True),
    (7, -.05, True), (13, .02, True), (19, .125, False), (20, .125, False),
    (22, .125, True), (23, .02, True),
])
def test_group_count_changes_thickness_and_flag_policy(mode, height, contact):
    result = run(fixture(mode=mode, count=3))
    assert position(result)[1] == pytest.approx(height)
    assert bool(flags(result) & 0x1000000) is contact


@pytest.mark.parametrize('mode,height', [(7, .03), (8, .05), (9, .14), (10, .08),
                                        (11, .05), (12, .05), (13, .1), (16, .03)])
@pytest.mark.parametrize('trigger', ['speed', 'ground'])
def test_movement_profiles_use_either_speed_or_ground_height(mode, height, trigger):
    data = fixture(mode=mode, count=2)
    if trigger == 'speed':
        struct.pack_into('<e', data['per_frame'], 56, 4.00390625)
    else:
        struct.pack_into('<f', data['per_frame'], 24, -10.001)
    assert position(run(data))[1] == pytest.approx(height)


def test_movement_thresholds_are_strict_and_parameter_veto_only_uses_speed():
    data = fixture(mode=8)
    struct.pack_into('<f', data['per_frame'], 24, -10.)
    struct.pack_into('<e', data['per_frame'], 56, 4.)
    assert position(run(data))[1] == pytest.approx(.125)
    struct.pack_into('<H', data['simulation_parameter'], 212, 0x10)
    struct.pack_into('<f', data['per_frame'], 24, -100.)
    assert not run(data)['projected_colliders']
    struct.pack_into('<e', data['per_frame'], 56, 4.00390625)
    assert position(run(data))[1] == pytest.approx(.05)
    struct.pack_into('<e', data['per_frame'], 62, -20.)
    assert not run(data)['projected_colliders']
    struct.pack_into('<e', data['per_frame'], 62, -19.984375)
    assert run(data)['projected_colliders'] == 1


@pytest.mark.parametrize('mode', [0, 2, 5, 6, 23])
def test_multiple_large_colliders_are_rejected_by_selected_modes(mode):
    data = fixture(mode=mode, count=2, radius=.4000000059604645)
    assert run(data)['projected_colliders'] == 0
    for record in data['collidable_results'].values():
        struct.pack_into('<f', record, 4, .399)
    # Coincident planes can make another tiny correction after float32 rounding.
    assert position(run(data))[1] == pytest.approx(.02 if mode == 23 else .125)


def test_mode_five_uses_particle_lra_and_mode_thirteen_shrinks_the_contact_radius():
    data = fixture(mode=5)
    struct.pack_into('<e', data['particle'], 88, .0999755859375)
    assert not run(data)['projected_colliders']
    struct.pack_into('<e', data['particle'], 88, .10003662109375)
    assert run(data)['projected_colliders'] == 1
    result = run(fixture(mode=13, anchor=(.2, -.2, 0.)))
    assert result['projected_colliders'] == 1
    assert not flags(result) & 0x1000000  # .2 is outside the modified radius .175.


@pytest.mark.parametrize('mode', [17, 18])
def test_small_radius_promotion_is_strict_and_affects_contact_flags(mode):
    data = fixture(mode=mode, radius=.199, anchor=(.25, -.2, 0.))
    assert flags(run(data)) & 0x1000000
    struct.pack_into('<f', data['collidable_results'][7, 30], 4, .2)
    assert not flags(run(data)) & 0x1000000


@pytest.mark.parametrize('mode', [21, 22, 23])
def test_disc_limited_modes_do_not_project_at_the_radius_boundary(mode):
    data = fixture(mode=mode, anchor=(.25, -.2, 0.))
    assert not run(data)['projected_colliders']
    struct.pack_into('<f', data['particle'], 0, .249)
    assert run(data)['projected_colliders'] == 1
    # Ordinary mode4 still projects outside the radius, without setting contact.
    struct.pack_into('<i', data['simulation_parameter'], 196, 4)
    struct.pack_into('<f', data['particle'], 0, 100.)
    result = run(data)
    assert result['projected_colliders'] == 1 and not flags(result) & 0x1000000


def test_projection_requires_type_three_and_strict_plane_penetration():
    data = fixture(anchor=(0., .125, 0.))
    assert not run(data)['projected_colliders']
    struct.pack_into('<f', data['particle'], 4, .124)
    for shape in (0, 1, 2, 4, 0xFFFF):
        struct.pack_into('<H', data['collidables'][6, 20], 2, shape)
        assert not run(data)['projected_colliders']
    struct.pack_into('<H', data['collidables'][6, 20], 2, 3)
    assert run(data)['projected_colliders'] == 1


def test_disabled_custom_parameters_still_apply_the_default_group_thickness_rule():
    data = fixture(mode=23, count=3)
    struct.pack_into('<f', data['simulation_parameter'], 200, float('nan'))
    struct.pack_into('<I', data['global_parameters'], 1204, 0)
    assert position(run(data))[1] == pytest.approx(.03)


def test_current_centers_and_signed_tile_translations_define_the_collision_plane():
    data = fixture(anchor=(0., 0., 0.))
    struct.pack_into('<3f2h', data['per_scene'], 0, 12., 6., 20., 2, -3)
    struct.pack_into('<3f', data['per_frame'], 0, 2., 3., -4.)
    struct.pack_into('<3f2h', data['scene_objects'][2, 3], 0, 4., 5., 8., 1, -5)
    result = data['collidable_results'][7, 30]
    struct.pack_into('<3f', result, 20, 1010., 5., 2008.)
    struct.pack_into('<3f', result, 44, 1010., 4., 2008.)
    struct.pack_into('<3f', result, 8, 999., 888., 777.)
    struct.pack_into('<3f', result, 32, -999., -888., -777.)
    assert position(run(data)) == pytest.approx((0., 1.125, 0.))


def test_colliders_project_sequentially_and_modes_one_and_three_only_use_first_large_collider():
    data = fixture(count=2, radius=1., anchor=(-1., -1., 0.), thickness=0.)
    struct.pack_into('<3f', data['collidable_results'][7, 30], 44, -1., 0., 0.)
    struct.pack_into('<3f', data['collidable_results'][7, 31], 44, 1., -1., 0.)
    assert position(run(data)) == pytest.approx((-.5, -.5, 0.))
    for mode in (1, 3):
        struct.pack_into('<i', data['simulation_parameter'], 196, mode)
        assert position(run(data)) == pytest.approx((0., -1., 0.))
    struct.pack_into('<i', data['simulation_parameter'], 196, 4)
    data['collidable_results'][7, 30], data['collidable_results'][7, 31] = (
        data['collidable_results'][7, 31], data['collidable_results'][7, 30])
    assert position(run(data)) == pytest.approx((0., -1., 0.))


def self_scene(data):
    struct.pack_into('<I', data['extra_collidables'][11], 28, 0x10002)
    struct.pack_into('<I', data['per_scene'], 68, 0x10002)
    data['scene_objects'] = {(1, 2): data['per_scene']}


@pytest.mark.parametrize('prefix_count', [31, 32, 95, 96])
def test_skipped_groups_still_advance_the_96_bit_collider_mask(prefix_count):
    data = fixture()
    self_scene(data)
    prefix = bytearray(data['extra_collidables'][11])
    struct.pack_into('<H', prefix, 2, prefix_count)
    struct.pack_into('<I', prefix, 8, 5)
    struct.pack_into('<I', prefix, 32, 10)  # Same source, excluded without flag4.
    data['extra_collidables'][12] = data['extra_collidables'][11]
    data['extra_collidables'][11] = prefix
    data['reference_collidables'][7] = 0x2000B
    struct.pack_into('<3I', data['simulation_parameter'], 64, 0, 0, 0)
    if prefix_count <= 95:
        assert not run(data)['projected_colliders']
        struct.pack_into('<I', data['simulation_parameter'], 64 + 4*(prefix_count//32), 1 << (prefix_count % 32))
    assert run(data)['projected_colliders'] == 1


@pytest.mark.parametrize('override', ['scene', 'frame'])
def test_mask_overrides_allow_same_scene_colliders(override):
    data = fixture()
    self_scene(data)
    struct.pack_into('<3I', data['simulation_parameter'], 64, 0, 0, 0)
    assert not run(data)['projected_colliders']
    if override == 'scene':
        struct.pack_into('<I', data['per_scene'], 64, 0x40200)
    else:
        struct.pack_into('<I', data['per_frame'], 36, 0x420000)
    assert run(data)['projected_colliders'] == 1


@pytest.mark.parametrize('include,exclude,temporary,projected', [
    ((), (), (), 1), ((123,), (), (), 1), ((456,), (), (), 0),
    ((123,), (123,), (), 0), ((123,), (), (123,), 0),
])
def test_cpu_material_mask_upload_controls_same_scene_input_projection(include, exclude, temporary, projected):
    data = fixture()
    self_scene(data)
    words = build_cloth_material_collision_mask(
        (123,), inclusion_bone_hashes=include, exclusion_bone_hashes=exclude,
        temporary_fix_exclusion_bone_hashes=temporary,
    )
    struct.pack_into('<3I', data['simulation_parameter'], 64, *words)
    before = snapshot(data)
    result = run(data)
    assert result['projected_colliders'] == projected
    assert position(result)[1] == pytest.approx(.125 if projected else -.2)
    assert snapshot(data) == before


def test_each_reference_restarts_the_mask_counter_and_sentinel_entries_are_skipped():
    data = fixture()
    self_scene(data)
    selected = data['extra_collidables'][11]
    prefix = bytearray(selected)
    struct.pack_into('<H', prefix, 0, 0)
    missing = bytearray(selected)
    struct.pack_into('<I', missing, 36, 900)
    data['extra_collidables'] = {11: prefix, 12: selected, 13: missing}
    data['reference_collidables'] = {7: 0x2000B, 8: 0x1000D, 9: 0xFFFFFFFF, 10: 123}
    struct.pack_into('<H', data['per_scene'], 74, 4)
    struct.pack_into('<3I', data['simulation_parameter'], 64, 6, 0, 0)
    assert run(data)['projected_colliders'] == 1  # Reference8 starts at masked bit0.


def test_own_source_is_only_reenabled_by_flag_four_and_a_matching_non_sentinel_pac():
    data = fixture()
    self_scene(data)
    struct.pack_into('<H', data['simulation_parameter'], 238, 6)
    struct.pack_into('<I', data['simulation_parameter'], 180, 20)
    assert not run(data)['projected_colliders']
    struct.pack_into('<H', data['extra_collidables'][11], 0, 6)
    assert run(data)['projected_colliders'] == 1
    struct.pack_into('<I', data['simulation_parameter'], 184, 41)
    assert not run(data)['projected_colliders']
    for record, offset in ((data['simulation_parameter'], 184), (data['extra_collidables'][11], 4)):
        struct.pack_into('<I', record, offset, 0xFFFFFFFF)
    assert not run(data)['projected_colliders']


def test_selected_resource_fallbacks_use_buffer_zero_and_uint32_element_addition():
    data = fixture(count=2)
    group = data['extra_collidables'][11]
    struct.pack_into('<2I', group, 8, 65000, 65535)
    struct.pack_into('<3I', group, 28, (65000 << 16) | 3, 0xFFFFFFFF, 0xFFFFFFFF)
    data['scene_objects'] = {(0, 3): data['scene_objects'][2, 3]}
    data['collidables'] = {(0, 0xFFFFFFFF): data['collidables'][6, 20], (0, 0): data['collidables'][6, 21]}
    data['collidable_results'] = {(0, 0xFFFFFFFF): data['collidable_results'][7, 30], (0, 0): data['collidable_results'][7, 31]}
    struct.pack_into('<3f', data['collidable_results'][0, 0], 20, 0., 1., 0.)
    struct.pack_into('<3f', data['collidable_results'][0, 0], 44, 0., 0., 0.)
    result = run(data)
    assert result['projected_colliders'] == 2
    assert position(result)[1] == pytest.approx(1.125)


@pytest.mark.parametrize('gate', ['global', 'frame', 'static'])
def test_disabled_outer_gate_preserves_every_byte_without_consuming_snapshots(gate):
    data = fixture()
    if gate == 'global':
        struct.pack_into('<I', data['global_parameters'], 1200, 0)
    elif gate == 'frame':
        struct.pack_into('<I', data['per_frame'], 36, 0)
    else:
        struct.pack_into('<H', data['simulation_parameter'], 216, 0)
    data['reference_collidables'] = None
    assert run(data) == {'particle': bytes(data['particle']), 'active': False, 'projected_colliders': 0}


@pytest.mark.parametrize('gate', ['parent', 'group', 'movement', 'scene'])
def test_inner_gates_skip_geometry_without_requiring_collider_records(gate):
    data = fixture()
    if gate == 'parent':
        struct.pack_into('<I', data['scene_objects'][2, 3], 68, 999)
    elif gate == 'group':
        struct.pack_into('<H', data['extra_collidables'][11], 0, 0)
    elif gate == 'movement':
        struct.pack_into('<I', data['per_frame'], 32, 0)
    else:
        struct.pack_into('<I', data['per_scene'], 64, 0)
    data['collidable_results'] = data['collidables'] = None
    assert not run(data)['projected_colliders']


@pytest.mark.parametrize('scene_flags,retained', [(0, True), (0x200, False), (0x400, False),
                                                (0x600, True), (0x10600, False)])
def test_contact_flag_clear_and_companion_or_also_run_with_no_references(scene_flags, retained):
    data = fixture()
    struct.pack_into('<I', data['particle'], 64, 0x1008000)
    struct.pack_into('<I', data['per_scene'], 64, scene_flags)
    struct.pack_into('<H', data['per_scene'], 74, 0)
    assert flags(run(data)) == 0x8000 | (0x41000000 if retained else 0)
    struct.pack_into('<I', data['particle'], 64, 0x41008000)
    struct.pack_into('<e', data['per_frame'], 56, 5.)
    assert flags(run(data)) == 0x40008000  # Clearing bit24 does not clear existing bit30.


def test_collisions_precede_early_return_and_fixed_integration_selection():
    data = fixture()
    struct.pack_into('<I', data['per_frame'], 32, 0x20000400)
    assert run(data)['projected_colliders'] == 1
    struct.pack_into('<I', data['per_frame'], 32, 0x20000000)
    struct.pack_into('<f', data['particle'], 60, 0.)
    corrected = run(data)
    selected = select_cloth_base_integration(corrected['particle'], data['per_frame'])
    assert selected['branch'] == 'fixed'
    assert selected['particle'][12:36] == corrected['particle'][:12] * 2


def test_missing_consumed_records_invalid_references_and_degenerate_axes_are_rejected():
    for name in ('reference_collidables', 'extra_collidables', 'scene_objects', 'collidable_results', 'collidables'):
        data = fixture()
        data[name] = None
        with pytest.raises(ValueError, match='requires'):
            run(data)
    data = fixture()
    data['reference_collidables'][7] = -1
    with pytest.raises(ValueError, match='unsigned'):
        run(data)
    data = fixture()
    struct.pack_into('<3f', data['collidable_results'][7, 30], 44, 0., 0., 0.)
    with pytest.raises(ValueError, match='Degenerate'):
        run(data)
