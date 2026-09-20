"""Analytic bone/vertex/cloth handoff cases; no game assets or renderer."""

import math
import struct

import pytest

from cdmw.modding.pac_cloth_skinning import blend_render_cloth_matrix
from cdmw.modding.pac_jiggle_skinning import (
    blend_render_jiggle_matrix, prepare_jiggle_bone_skinning,
)
from tests.test_pac_jiggle_bones import IDENTITY, assert_matrix, matrix, run, state


def frame(position=(0., 0., 0.), marker=0., weight=0.):
    return ((1., 0., 0., marker), (0., 1., 0., weight), IDENTITY[2], (*position, 1.))


def record(*, slots=(0,) * 6, weights=(255, 0, 0, 0, 0, 0, 0, 0), jiggle=0, cloth=63):
    data = bytearray(40)
    for group in range(2):
        struct.pack_into('<I', data, 20 + 4 * group,
                         sum(slots[3 * group + i] << (10 * i) for i in range(3)))
    data[28:36] = bytes(weights)
    data[38:40] = bytes((jiggle, cloth | 0xC0))
    return data


def blend(data=None, **changes):
    args = dict(render_flags=128, bone_palette=(0,), skinning_index_map=(0,),
                skeletal_matrices=(IDENTITY,), jiggle_matrices=(frame((10, 0, 0)),))
    args.update(changes)
    return blend_render_jiggle_matrix(record() if data is None else data, 0, **args)


def point(transform, value):
    return tuple(sum(value[i] * transform[i][j] for i in range(3)) + transform[3][j] for j in range(3))


def test_inverse_bind_precedes_scaled_pose_and_metadata_moves_to_ordinary_matrix():
    animation = ((0., 1., 0., 9.), (-1., 0., 0., 8.), IDENTITY[2], (10., 20., 30., 1.))
    prepared = prepare_jiggle_bone_skinning(
        inverse_bind_matrix=frame((-2, 0, 0)), animation_matrix=animation,
        jiggle_matrix=frame((12, 20, 30), marker=2, weight=.7), character_space_scale=(2, 3, 4))
    ordinary, simulated = prepared['skeletal_matrix'], prepared['jiggle_matrix']
    assert point(ordinary, (2, 0, 0)) == pytest.approx((10, 20, 30))
    assert point(ordinary, (3, 0, 0)) == pytest.approx((10, 22, 30))
    assert point(simulated, (2, 0, 0)) == pytest.approx((12, 20, 30))
    assert point(simulated, (3, 0, 0)) == pytest.approx((14, 20, 30))
    assert (ordinary[0][3], ordinary[1][3]) == (1., .7)
    assert tuple(row[3] for row in simulated) == (0., 0., 0., 1.)
    disabled = prepare_jiggle_bone_skinning(
        inverse_bind_matrix=IDENTITY, animation_matrix=animation,
        jiggle_matrix=None, character_space_scale=(1, 1, 1))
    assert disabled['jiggle_matrix'] is None
    assert tuple(row[3] for row in disabled['skeletal_matrix']) == (0., 0., 0., 1.)


def test_six_weights_are_normalized_after_both_palette_maps():
    data = record(slots=(0, 1, 2, 0, 1, 2), weights=(10, 20, 30, 40, 50, 60, 255, 255))
    result = blend(data, bone_palette=(2, 0, 1), skinning_index_map=(1, 2, 0), jiggle_matrices=None,
                   skeletal_matrices=(frame((1, 0, 0)), frame((10, 0, 0)), frame((100, 0, 0))))
    assert point(result, (2, 0, 0)) == pytest.approx((2 + 9750 / 210, 0, 0))


@pytest.mark.parametrize('flags,cloth', [(128, 62), (128 | 512, 63), (128 | 1024, 63)])
def test_guide_slots_and_other_render_modes_are_not_extra_skeletal_slots(flags, cloth):
    data = record(slots=(0, 0, 0, 0, 1023, 1022), weights=(30, 0, 0, 0, 255, 255, 255, 255), cloth=cloth)
    struct.pack_into('<2e', data, 12, math.nan, math.nan)
    result = blend(data, render_flags=flags)
    # A guide-bound vertex still receives jiggle; the other render modes do not.
    assert point(result, (1, 0, 0)) == pytest.approx((11 if flags == 128 else 1, 0, 0))


@pytest.mark.parametrize('raw,flags,amount', [
    (0, 128, 1), (240, 128, 1), (249, 128, .4), (254, 128, 1 / 15),
    (255, 128, 0), (143, 128, 0), (240, 0, 15 / 255),
])
def test_vertex_blend_selects_nibble_or_full_byte_mode(raw, flags, amount):
    result = blend(record(jiggle=raw), render_flags=flags,
                   skeletal_matrices=(frame((2, 0, 0)),), jiggle_matrices=(frame((17, 0, 0)),))
    assert result[3][0] == pytest.approx(2 + 15 * amount)


def test_any_positive_weighted_marker_selects_the_entire_weighted_override():
    result = blend(record(slots=(0, 1, 0, 0, 0, 0), weights=(64, 192, 0, 0, 0, 0, 0, 0), jiggle=255),
                   bone_palette=(0, 1), skinning_index_map=(0, 1),
                   skeletal_matrices=(frame(marker=1, weight=.8), frame(marker=0, weight=.4)),
                   jiggle_matrices=(frame((20, 0, 0)),) * 2)
    # Marker = 1/4; override = .8/4 + .4*3/4 = .5. It is not divided by marker.
    assert result[3][0] == pytest.approx(10)


@pytest.mark.parametrize('weight,expected', [(2, 20), (0, 0), (-.5, 0)])
def test_override_extrapolates_or_bypasses_without_clamping(weight, expected):
    result = blend(skeletal_matrices=(frame(marker=1, weight=weight),),
                   jiggle_matrices=(frame((10, 0, 0)),) if weight > 0 else ())
    assert result[3][0] == pytest.approx(expected)


def test_disabled_jiggle_does_not_fetch_simulation_or_wind_buffers():
    assert_matrix(blend(jiggle_matrices=None, wind_weight=1), IDENTITY)
    assert_matrix(blend(record(jiggle=255), jiggle_matrices=(), wind_weight=1), IDENTITY)
    assert_matrix(blend(render_flags=512, jiggle_matrices=(), wind_weight=1), IDENTITY)


def test_zero_weights_produce_zero_xyz_rows_without_fallback_identity():
    result = blend(record(weights=(0,) * 8))
    assert tuple(row[:3] for row in result) == ((0., 0., 0.),) * 4


def test_wind_uses_original_bone_low_byte_and_precedes_final_vertex_blend():
    jiggle = ((2., 0., 0., 0.), (0., 3., 0., 0.), (0., 0., 4., 0.), (10., 20., 30., 1.))
    sample = ((0., 1., 0., 0.), (-1., 0., 0., 0.), IDENTITY[2], (1., 2., 3., 1.))
    samples = (IDENTITY,) * 1025 + (sample,)
    result = blend(record(jiggle=9), bone_palette=(257,), skinning_index_map=(0,) * 258,
                   jiggle_matrices=(jiggle,), wind_weight=.5, wind_samples=samples)
    assert_matrix(result, ((1., .6, 0., 0.), (-.4, 1.2, 0., 0.), (0., 0., 2.2, 0.), (4.2, 8.4, 12.6, 1.)))
    assert point(result, (2, 3, 4)) == pytest.approx((5., 13.2, 21.4))


def test_wind_sample_fourth_column_is_consumed_by_basis_composition():
    sample = frame((3, 0, 0), marker=.5)
    result = blend(jiggle_matrices=(frame((2, 0, 0)),), wind_weight=1,
                   wind_samples=(IDENTITY,) * 1024 + (sample,))
    assert point(result, (1, 0, 0)) == pytest.approx((8.5, 0, 0))


def test_bone_solver_output_reaches_vertex_then_guide_cloth_blend():
    # A bone at x=2 advances to x=3 with velocity 4 and dt=.25.
    step = run(state(p=(2, 0, 0), v=(4, 0, 0)), animation_matrix=matrix(frame((2, 0, 0))))
    prepared = prepare_jiggle_bone_skinning(
        inverse_bind_matrix=frame((-2, 0, 0)), animation_matrix=frame((2, 0, 0)),
        jiggle_matrix=step['matrix'], character_space_scale=(1, 1, 1))
    data = record(jiggle=9, cloth=21, weights=(255, 0, 0, 0, 255, 0, 0, 0))
    skeletal = blend(data, skeletal_matrices=(prepared['skeletal_matrix'],),
                     jiggle_matrices=(prepared['jiggle_matrix'],))
    assert point(skeletal, (2, 0, 0)) == pytest.approx((2.4, 0, 0))
    cloth = blend_render_cloth_matrix(data, 0, skeletal_matrix=skeletal,
                                      guide_matrices=(frame((4, 0, 0), marker=1),))
    # Guide position 6, skeletal position 2.4, skeletal fraction 21/63.
    assert point(cloth, (2, 0, 0)) == pytest.approx((4.8, 0, 0))


def test_zero_weight_skeletal_slots_still_require_valid_buffers():
    with pytest.raises(ValueError, match='outside'):
        blend(record(slots=(0, 1, 0, 0, 0, 0)))
    with pytest.raises(ValueError, match='outside'):
        blend(bone_palette=(1,), skinning_index_map=(0, -1))


def test_incomplete_records_matrices_and_active_wind_inputs_are_rejected():
    with pytest.raises(ValueError, match='40-byte'):
        blend(bytes(39))
    with pytest.raises(ValueError, match='4 by 4'):
        blend(skeletal_matrices=(IDENTITY[:3],))
    with pytest.raises(ValueError, match='finite'):
        blend(skeletal_matrices=(frame((math.nan, 0, 0)),))
    with pytest.raises(ValueError, match='sample buffer'):
        blend(wind_weight=1)
