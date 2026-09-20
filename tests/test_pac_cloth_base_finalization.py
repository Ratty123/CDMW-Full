"""Owned water samples and base-step records for classification and final writes."""

import struct

import pytest

from cdmw.modding.pac_cloth_environment import classify_cloth_water, plan_cloth_water_samples
from cdmw.modding.pac_cloth_state import (
    finalize_cloth_base_state, prepare_guide_cloth_animation, select_cloth_base_integration,
)


def water_constants():
    record = bytearray(768)
    struct.pack_into('<4f', record, 0, 10., 20., .25, .5)
    struct.pack_into('<3f', record, 32, 0., 8., 0.)
    struct.pack_into('<4f', record, 416, 8., 777., 4., .25)
    return record


def in_water(y, *, samples=(.25, .75, 1., 1.), view_y=0., constants=None):
    return classify_cloth_water((0., y, 0.), water_constants() if constants is None else constants,
                                current_view_y=view_y, depth_samples=samples)


@pytest.mark.parametrize('x,z,detail', [(1., 1., True), (4., 0., False),
                                      (-4., 0., False), (0., 2., False), (0., -2., False)])
def test_water_top_detail_selection_uses_strict_bounds_and_unclamped_uvs(x, z, detail):
    constants = water_constants()
    before = bytes(constants)
    query = plan_cloth_water_samples((x, 5., z), constants)
    assert query['use_detail_top'] is detail
    assert query['common_uv'] == (.5 + x*.25, .5 - z*.5)
    assert query['top_uv'] == ((.5 + x*4., .5 - z*.25) if detail else query['common_uv'])
    assert bytes(constants) == before


@pytest.mark.parametrize('height,inside', [(-2., False), (-2.5, True), (-6., True), (-6.25, False)])
def test_water_top_is_exclusive_and_bottom_is_inclusive(height, inside):
    assert in_water(height) is inside


@pytest.mark.parametrize('height,inside', [(-2.5, True), (-3., False), (-4., False), (-5., False), (-5.5, True)])
def test_air_pocket_excludes_both_boundaries_and_its_interior(height, inside):
    assert in_water(height, samples=(.25, .75, .375, .625)) is inside


def test_depth_sentinels_do_not_clamp_samples_or_shift_with_view():
    assert not in_water(-4., samples=(1., .75, 1., 1.))
    assert not in_water(-4., samples=(1.1, .75, 1., 1.))
    assert in_water(.5, samples=(-.125, .75, 1., 1.))  # Negative top depth produces height1.
    assert in_water(-10001., view_y=1., samples=(0., 1., 0., .5))
    assert not in_water(-10001.5, view_y=1., samples=(0., 1., 0., .5))


def test_depth_conversion_uses_minimum_maximum_bias_and_current_view_y():
    constants = water_constants()
    struct.pack_into('<3f', constants, 32, 2., 10., 3.)
    assert in_water(-4., constants=constants, view_y=100.)
    assert in_water(-4., constants=constants, view_y=-200.)
    assert not in_water(-1., constants=constants, view_y=100.)


def test_selected_detail_top_changes_classification_with_the_same_other_samples():
    query = plan_cloth_water_samples((0., -4., 0.), water_constants())
    assert query['use_detail_top']
    assert in_water(-4., samples=(.125, .875, 1., 1.))
    assert not in_water(-4., samples=(.75, .875, 1., 1.))


def records(*, frame_flags=0, flags2=0, particle_flags=0, resource_valid=False, inverse_mass=1.):
    particle = bytearray(range(152))
    parameter, frame, scene = bytearray(312), bytearray(100), bytearray(108)
    for offset, point in ((0, (9., 8., 7.)), (12, (11., 12., 13.)), (24, (21., 22., 23.)),
                          (36, (1., 0., 0.)), (48, (31., 32., 33.)),
                          (128, (1., 0., 0.)), (140, (10000., 20000., 30000.))):
        struct.pack_into('<3f', particle, offset, *point)
    struct.pack_into('<fI', particle, 60, inverse_mass, particle_flags)
    struct.pack_into('<H', particle, 116, 0)
    struct.pack_into('<fI', particle, 120, 4., 0x12345678)
    struct.pack_into('<I', parameter, 148, 17)
    struct.pack_into('<2H', parameter, 216, 0xFFFF, 0xFFFF)
    struct.pack_into('<H', parameter, 226, 3 if resource_valid else 0xFFFF)
    struct.pack_into('<e', parameter, 266, 99.)
    struct.pack_into('<2I', frame, 32, frame_flags, flags2)
    cache = bytearray(struct.pack('<10I', *range(100, 110)))
    return particle, parameter, frame, scene, cache


def finish(data, acceleration=(31., 0., 0.), **changes):
    options = dict(non_gravity_acceleration=acceleration, delta_time=.25, pre_collision=data[4])
    options.update(changes)
    return finalize_cloth_base_state(*data[:4], **options)


def flags_of(particle):
    return struct.unpack_from('<I', particle, 64)[0]


@pytest.mark.parametrize('acceleration,outward', [(29., False), (30., False), (30.00001, True), (-40., False)])
def test_outward_force_threshold_is_strict_and_updates_only_its_bit_and_timer(acceleration, outward):
    data = records(particle_flags=0x140000)
    before = tuple(bytes(record) for record in data)
    result = finish(data, (acceleration, 0., 0.))
    assert result['outward_force'] is outward
    assert flags_of(result['particle']) == (0x140000 if outward else 0x100000)
    assert struct.unpack_from('<f', result['particle'], 120)[0] == 4.25
    allowed = set(range(64, 68)) | set(range(120, 124))
    assert all(result['particle'][i] == before[0][i] for i in range(152) if i not in allowed)
    assert result['pre_collision'] == before[4]
    assert tuple(bytes(record) for record in data) == before


def test_outward_direction_uses_working_position_and_does_not_normalize_gravity_input():
    data = records()
    struct.pack_into('<3e', data[3], 100, 0., -2., 0.)
    result = finish(data, (0., 40., 0.))
    assert result['outward_force']
    assert result['outward_measure'] == pytest.approx(80 / (5**.5))
    assert not finish(data, (0., 0., 0.))['outward_force']  # Large stored velocity is irrelevant.


@pytest.mark.parametrize('resource_valid', [True, False])
@pytest.mark.parametrize('frame_flags', [0, 0x80000000, 0x10, 0x80000010])
def test_pre_collision_halves_reset_independently_without_clearing_contact_normals(resource_valid, frame_flags):
    data = records(frame_flags=frame_flags, resource_valid=resource_valid, particle_flags=0x20000000)
    before = tuple(bytes(record) for record in data)
    result = finish(data, (0., 0., 0.))
    first = resource_valid and bool(frame_flags & 0x80000000)
    second = resource_valid and bool(frame_flags & 0x10)
    expected = list(range(100, 110))
    if first:
        expected[:5] = [0, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0]
    if second:
        expected[5:] = [0, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF]
    assert struct.unpack('<10I', result['pre_collision']) == tuple(expected)
    assert result['reset_pre_collision_halves'] == (first, second)
    assert flags_of(result['particle']) == (0 if second else 0x20000000)
    assert result['particle'][72:120] == before[0][72:120]
    assert result['particle'][124:] == before[0][124:]
    assert tuple(bytes(record) for record in data) == before


@pytest.mark.parametrize('mass,extra_flag', [(0., 0), (1., 0x40)])
def test_fixed_branch_uses_zero_force_and_applies_hold_after_fixed_position_selection(mass, extra_flag):
    data = records(flags2=0x10000, inverse_mass=mass, particle_flags=0x80000100 | extra_flag)
    selected = select_cloth_base_integration(data[0], data[2])
    assert selected['branch'] == 'fixed'
    assert selected['particle'][12:24] == data[0][:12]
    updated = (selected['particle'], *data[1:])
    result = finish(updated, (999., 999., 999.))
    assert result['held'] and not result['outward_force']
    assert result['outward_measure'] == 0.
    assert result['particle'][12:36] == data[0][36:48]*2
    assert result['particle'][140:] == data[0][140:]
    assert flags_of(result['particle']) == 0x80000100 | extra_flag
    assert struct.unpack_from('<f', result['particle'], 120)[0] == 100000.25


def test_water_classification_connects_to_guide_adjustment_suppression():
    data = records(frame_flags=1, flags2=0x1100)
    struct.pack_into('<3f', data[0], 36, 1., -4., 0.)
    guide, character = bytearray(64), bytearray(272)
    struct.pack_into('<3f', guide, 48, 0., 2., 0.)
    for row in range(3):
        struct.pack_into('<f', character, row*20, 1.)
    position = struct.unpack_from('<3f', data[0], 36)
    inside = classify_cloth_water(position, water_constants(), current_view_y=0.,
                                  depth_samples=(.25, .75, 1., 1.))
    prepared = prepare_guide_cloth_animation(*data[:4], guide, character,
                                            substep_index=0, animation_blend=.5, inside_water_volume=inside)
    assert prepared['underwater']
    assert not prepared['space_adjusted'] and not prepared['skip_external_forces']
    assert not prepared['integration_skipped']
    assert prepared['particle'][140:] == data[0][140:]


def test_missing_active_cache_and_early_return_or_degenerate_math_are_rejected():
    data = records(frame_flags=0x10, resource_valid=True)
    with pytest.raises(ValueError, match='ten-uint'):
        finish(data, pre_collision=None)
    with pytest.raises(ValueError, match='40-byte'):
        finish(data, pre_collision=data[4][:-1])
    data = records(resource_valid=True)
    assert finish(data, pre_collision=None)['pre_collision'] is None
    for frame_flags in (0x400, 0x800):
        with pytest.raises(ValueError, match='Early-return'):
            finish(records(frame_flags=frame_flags))
    struct.pack_into('<3f', data[0], 36, 0., 5., 0.)
    struct.pack_into('<3e', data[3], 100, 0., -1., 0.)
    with pytest.raises(ValueError, match='degenerate'):
        finish(data)


def test_nonfinite_water_data_and_invalid_consumed_records_are_rejected():
    with pytest.raises(ValueError, match='768-byte'):
        plan_cloth_water_samples((0., 0., 0.), water_constants()[:-1])
    with pytest.raises(ValueError, match='water-depth'):
        in_water(-4., samples=None)
    with pytest.raises(ValueError, match='finite'):
        in_water(-4., samples=(float('nan'), .75, 1., 1.))
    with pytest.raises(ValueError, match='finite'):
        finish(records(), acceleration=(float('nan'), 0., 0.))
    with pytest.raises(ValueError, match='nonnegative'):
        finish(records(), delta_time=-1.)
