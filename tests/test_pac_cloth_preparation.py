"""Decoded mode-1 attachment ratios, automatic blends and orientation neighbors."""

from dataclasses import replace
import math

import pytest

from cdmw.modding.pac_cloth_preparation import prepare_guide_cloth_attachments
from tests.test_pac_cloth_attachments import guides_with


def prepare(guides, *, separate=True, alpha=True, automatic=True, base=.5, shift=0):
    return prepare_guide_cloth_attachments(
        guides, separate_components=separate, use_vertex_alpha_position_blending=alpha,
        auto_weighting_enabled=automatic, auto_weighting_exponential_base=base,
        auto_weighting_input_ratio_shift=shift,
    )


@pytest.mark.parametrize('separate', [False, True])
@pytest.mark.parametrize('alpha, expected', [
    (False, [1, .03125, .0009765625]),
    (True, [1, .01556396484375, .0004863739013671875]),
])
def test_auto_weighting_replaces_or_multiplies_dynamic_blends_but_preserves_fixed_vertices(separate, alpha, expected):
    guides = guides_with([(0, 0, 0), (1, 0, 0), (2, 0, 0)], fixed=(0,), triangles=((0, 1, 2),))
    result = prepare(guides, separate=separate, alpha=alpha)
    assert result['long_range_ratios'] == [0, .5, 1]
    assert result['position_blends'] == expected
    assert result['anchor_rest_lengths'] == [[0], [1], [2]]
    assert result['auto_weighted_vertex_indices'] == [1, 2]
    assert result['orientation_neighbor_indices'] == [(1, 2), (2, 0), (0, 1)]


def test_component_and_whole_mesh_normalization_remain_distinct():
    guides = guides_with([(0, 0, 0), (1, 0, 0), (2, 0, 0),
                          (100, 0, 0), (102, 0, 0), (104, 0, 0)],
                         fixed=(0, 3), triangles=((0, 1, 2), (3, 4, 5)))
    assert prepare(guides)['long_range_ratios'] == [0, .5, 1, 0, .5, 1]
    whole = prepare(guides, separate=False)
    assert whole['mean_anchor_distances'] == [50, 50, 50, 50, 52, 54]
    assert whole['long_range_ratios'] == [0, 0, 0, 0, .5, 1]


@pytest.mark.parametrize('alpha, expected_blends, expected_ratios', [
    (True, [1, .498046875, 0], [0, .501953125, 1]),
    (False, [1, 0, 0], [0, 1, 1]),
])
def test_equal_distance_range_uses_initialized_blend_and_skips_auto_weighting(alpha, expected_blends, expected_ratios):
    guides = guides_with([(0, 0, 0)] * 3, fixed=(0,), triangles=((0, 1, 2),))
    guides = replace(guides, channel_b=bytes((255, 127, 0)))
    result = prepare(guides, alpha=alpha, base=0, shift=1)
    assert result['long_range_ratios'] == expected_ratios
    assert result['position_blends'] == expected_blends
    assert result['auto_weighted_vertex_indices'] == []


def test_disabled_auto_weighting_keeps_initial_position_blends():
    guides = guides_with([(0, 0, 0), (1, 0, 0), (2, 0, 0)], fixed=(0,), triangles=((0, 1, 2),))
    result = prepare(guides, automatic=False)
    assert result['position_blends'] == [1, .498046875, .498046875]
    assert result['long_range_ratios'] == [0, .5, 1]
    assert result['auto_weighted_vertex_indices'] == []


def test_means_are_computed_before_half_distance_upload():
    guides = guides_with([(0, 0, 0), (1e-9, 0, 0), (2e-9, 0, 0)],
                         fixed=(0,), triangles=((0, 1, 2),))
    result = prepare(guides)
    assert result['anchor_rest_lengths'] == [[0], [0], [0]]
    assert result['long_range_ratios'] == [0, .5, 1]


def test_auto_weighting_uses_full_float_ratio_before_half_packing():
    guides = guides_with([(0, 0, 0), (1, 0, 0), (3, 0, 0)], fixed=(0,), triangles=((0, 1, 2),))
    result = prepare(guides, alpha=False)
    assert result['long_range_ratios'][1] == .333251953125
    # Half rounding of 2**(-10/3). Feeding the packed ratio back into pow gives
    # the adjacent half .0992431640625 instead.
    assert result['position_blends'][1] == .09918212890625


@pytest.mark.parametrize('later_distance, expected', [(1, (3, 4)), (2, (1, 2))])
def test_neighbors_choose_smallest_packed_ratio_and_keep_first_triangle_on_a_tie(later_distance, expected):
    guides = guides_with([(0, 0, 0), (2.0001, 0, 0), (4, 0, 0),
                          (later_distance, 0, 0), (5, 0, 0)],
                         fixed=(0,), triangles=((0, 1, 2), (0, 3, 4)))
    result = prepare(guides)
    assert result['orientation_neighbor_indices'][0] == expected
    if later_distance == 2:
        assert result['long_range_ratios'][1] == result['long_range_ratios'][3]


def test_missing_anchors_and_unreferenced_neighbors_are_not_fabricated():
    guides = guides_with([(i, 0, 0) for i in range(4)], triangles=((0, 1, 2),))
    result = prepare(guides)
    assert result['anchor_indices'] == [[]] * 4
    assert result['mean_anchor_distances'] == [None] * 4
    assert result['long_range_ratios'] == [.501953125] * 4
    assert result['orientation_neighbor_indices'][-1] is None


@pytest.mark.parametrize('shift, expected', [(0, [1, 0, 0]), (-.5, [1, 1, 0]), (-1, [1, 1, 1])])
def test_zero_exponential_base_handles_positive_zero_and_negative_exponents(shift, expected):
    guides = guides_with([(0, 0, 0), (1, 0, 0), (2, 0, 0)], fixed=(0,), triangles=((0, 1, 2),))
    assert prepare(guides, alpha=False, base=0, shift=shift)['position_blends'] == expected


def test_non_boolean_switches_and_nonfinite_inputs_are_rejected():
    guides = guides_with([(0, 0, 0)] * 3)
    with pytest.raises(ValueError, match='boolean'):
        prepare(guides, automatic='0')
    with pytest.raises(ValueError, match='finite'):
        prepare(guides, base=math.nan)
