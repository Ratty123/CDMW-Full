"""Analytic constraint projections using owned geometry and runtime records."""

from dataclasses import replace
import math
import struct

import pytest

from cdmw.modding._pbd_numeric import round_pbd_half
from cdmw.modding.pac_cloth_constraints import (
    cloth_angle_bending_corrections, cloth_coefficient_bending_corrections,
    cloth_stretch_corrections, decode_guide_constraint_stiffness,
    select_guide_bending_projection,
)
from cdmw.modding.pac_cloth_guides import inspect_guide_constraint_geometry
from tests.test_pac_cloth_attachments import guides_with


FLAT = ((0., 0., 0.), (1., 0., 0.), (0., 1., 0.), (1., -1., 0.))
FOLDED = ((0., 0., 0.), (1., 0., 0.), (0., 1., 0.), (0., 0., 1.))


def geometry(points):
    guides = replace(guides_with(FLAT), constraint_records=((0, 1, 2, 3, 1),))
    return inspect_guide_constraint_geometry(guides, particle_positions=points)['constraints'][0]


def stretch(**changes):
    arguments = dict(positions=((0, 0, 0), (2, 0, 0)), animation_positions=((0, 0, 0), (1, 0, 0)),
                     inverse_masses=(1, 1), lra_ratios=(0, 1), stiffness=(1, 1), reference_length=1.,
                     uploaded_inverse_mass_sum=.5, bone_scale=1., stretching_scale=1.,
                     length_smoothing_byte=0, follow_the_leader_ratio=0., per_frame_flags=0,
                     particle_flags=(0, 0), particle_extra_flags=(0, 0))
    arguments.update(changes)
    return cloth_stretch_corrections(**arguments)


def assert_vectors(actual, expected):
    for a, b in zip(actual, expected, strict=True):
        assert a == pytest.approx(b, abs=1e-8)


@pytest.mark.parametrize("overrides,expected", [(None, (.25, .75)), ((-1, 0), (.25, 0)), ((1.25, -1), (1.25, .75))])
def test_stiffness_uses_named_half_fields_and_negative_sentinels(overrides, expected):
    frame = bytearray(100)
    struct.pack_into('<4e', frame, 64, 9., .25, .75, 8.)
    extra = None
    if overrides is not None:
        extra = bytearray(28)
        struct.pack_into('<2e', extra, 8, *overrides)
    before = bytes(frame), None if extra is None else bytes(extra)
    assert decode_guide_constraint_stiffness(frame, extra) == expected
    assert (bytes(frame), None if extra is None else bytes(extra)) == before


@pytest.mark.parametrize("kind,flags,blend,override,expected", [
    (2, 0x400, .25, None, "coefficient"), (2, 0x400, .5, None, "angle"),
    (2, 0x400, .75, -1., "angle"), (2, 0x400, .75, 0., "coefficient"),
    (2, 0x400, .25, .5, "angle"), (1, 0x400, .25, None, "angle"),
    (2, 0, .25, None, "angle"),
])
def test_bending_selection_uses_effective_input_blend_not_particle_cr(kind, flags, blend, override, expected):
    particle = bytearray(152)
    struct.pack_into('<e', particle, 90, 1. - blend)  # A different field, _cr.
    struct.pack_into('<e', particle, 94, blend)
    extra = None
    if override is not None:
        extra = bytearray(28)
        struct.pack_into('<e', extra, 6, override)
    assert select_guide_bending_projection(kind, per_frame_flags2=flags, particle=particle,
                                          particle_extra=extra) == expected


def test_distance_normalization_is_uploaded_not_recomputed_from_current_masses():
    assert_vectors(stretch(), ((.5, 0, 0), (-.5, 0, 0)))
    assert_vectors(stretch(inverse_masses=(0, 1)), ((0, 0, 0), (-.5, 0, 0)))
    assert_vectors(stretch(inverse_masses=(0, 1), uploaded_inverse_mass_sum=1), ((0, 0, 0), (-1, 0, 0)))


def test_distance_smoothing_comes_between_bone_and_material_scaling():
    arguments = dict(positions=((0, 0, 0), (4, 0, 0)), animation_positions=((0, 0, 0), (4, 0, 0)),
                     bone_scale=2., stretching_scale=.5)
    assert_vectors(stretch(**arguments), ((1.5, 0, 0), (-1.5, 0, 0)))
    assert_vectors(stretch(**arguments, length_smoothing_byte=255), ((1, 0, 0), (-1, 0, 0)))
    assert_vectors(stretch(**arguments, length_smoothing_byte=51), ((1.4, 0, 0), (-1.4, 0, 0)))


@pytest.mark.parametrize("changes,expected", [
    ({}, ((.25, 0, 0), (-.75, 0, 0))),
    ({'lra_ratios': (1, 0)}, ((.75, 0, 0), (-.25, 0, 0))),
    ({'lra_ratios': (0, .04)}, ((.5, 0, 0), (-.5, 0, 0))),
    ({'particle_flags': (0x80, 0)}, ((.5, 0, 0), (-.75, 0, 0))),
    ({'inverse_masses': (.1, 1)}, ((.05, 0, 0), (-.5, 0, 0))),
])
def test_follow_the_leader_uses_lra_order_and_endpoint_water_state(changes, expected):
    assert_vectors(stretch(follow_the_leader_ratio=.5, **changes), expected)


def test_short_edge_half_stiffness_and_extra_flag_are_per_endpoint():
    result = stretch(positions=((0, 0, 0), (.015, 0, 0)), reference_length=.005,
                     per_frame_flags=0x80000, particle_extra_flags=(0, 4))
    assert_vectors(result, ((.0025, 0, 0), (-.005, 0, 0)))


def test_stiffness_overrides_can_disable_one_endpoint_without_changing_the_other():
    assert_vectors(stretch(stiffness=(0, .5)), ((0, 0, 0), (-.25, 0, 0)))


@pytest.mark.parametrize("positions", [((0, 0, 0), (0, 0, 0)), ((0, 0, 0), (1.00001, 0, 0))])
def test_distance_shader_thresholds_skip_unusable_or_satisfied_edges(positions):
    assert stretch(positions=positions) == ((0., 0., 0.),) * 2


def test_prepared_half_coefficients_reduce_bending_energy_and_keep_pins_fixed():
    k = tuple(round_pbd_half(x) for x in geometry(FLAT)['bending_coefficients'])
    bent = (*FLAT[:3], (1., -1., 1.))
    deltas = cloth_coefficient_bending_corrections(bent, inverse_masses=(1, 1, 1, 1),
                                                 coefficients=k, stiffness=(1, 1, 1, 1))
    assert_vectors(deltas, ((0, 0, .125), (0, 0, .125), (0, 0, -.125), (0, 0, -.125)))
    fixed = cloth_coefficient_bending_corrections(bent, inverse_masses=(0, 0, 1, 1),
                                                coefficients=k, stiffness=(1, 1, 1, 1))
    assert_vectors(fixed, ((0, 0, 0), (0, 0, 0), (0, 0, -.25), (0, 0, -.25)))


def test_coefficient_math_uses_relative_positions_even_for_rounded_nonzero_coefficient_sum():
    arguments = dict(inverse_masses=(1, 1, 1, 1), coefficients=(1.001, 1, -1, -1), stiffness=(1, 1, 1, 1))
    bent = (*FLAT[:3], (1., -1., 1.))
    original = cloth_coefficient_bending_corrections(bent, **arguments)
    translated = tuple(tuple(x + t for x, t in zip(p, (8, -4, 16))) for p in bent)
    assert_vectors(cloth_coefficient_bending_corrections(translated, **arguments), original)


def test_coefficient_denominator_threshold_does_not_turn_small_energy_into_large_motion():
    result = cloth_coefficient_bending_corrections((*FLAT[:3], (1., -1., .01)),
                                                 inverse_masses=(1, 1, 1, 1),
                                                 coefficients=(1, 1, -1, -1), stiffness=(1, 1, 1, 1))
    assert result == ((0., 0., 0.),) * 4


def test_angle_correction_opens_a_right_angle_toward_authored_flat_geometry():
    reference = geometry(FLAT)['rest_angle_radians']
    deltas = cloth_angle_bending_corrections(FOLDED, inverse_masses=(1, 1, 1, 1),
                                           reference_angle=reference, stiffness=(1, 1, 1, 1))
    step = math.pi / 8
    assert_vectors(deltas, ((0, step, step), (0, 0, 0), (0, 0, -step), (0, -step, 0)))
    corrected = tuple(tuple(x + dx for x, dx in zip(p, delta)) for p, delta in zip(FOLDED, deltas))
    assert abs(geometry(corrected)['rest_angle_radians'] - reference) < math.pi / 2


def test_angle_correction_matches_an_independent_numerical_angle_gradient():
    points = ((1.3, -.7, .2), (2., .9, -.4), (.2, .2, 1.1), (1.6, -1.2, 2.5))
    masses, strengths, reference = (0., 1., 2., .5), (.4, .6, .8, .2), 2.7
    angle = geometry(points)['rest_angle_radians']
    epsilon = 1e-6
    gradients = []
    for i in range(4):
        row = []
        for axis in range(3):
            plus, minus = [list(p) for p in points], [list(p) for p in points]
            plus[i][axis] += epsilon
            minus[i][axis] -= epsilon
            row.append((geometry(plus)['rest_angle_radians'] - geometry(minus)['rest_angle_radians']) / (2 * epsilon))
        gradients.append(row)
    denominator = sum(w * sum(x*x for x in g) for w, g in zip(masses, gradients))
    expected = tuple(tuple(-s * w * (angle-reference) * x / denominator for x in g)
                     for s, w, g in zip(strengths, masses, gradients))
    actual = cloth_angle_bending_corrections(points, inverse_masses=masses,
                                           reference_angle=reference, stiffness=strengths)
    assert_vectors(actual, expected)


@pytest.mark.parametrize("positions,masses", [(FLAT, (1, 1, 1, 1)), (FOLDED, (0, 0, 0, 0)),
                                             (((0, 0, 0),) * 4, (1, 1, 1, 1))])
def test_angle_shader_thresholds_skip_singular_or_fixed_constraints(positions, masses):
    assert cloth_angle_bending_corrections(positions, inverse_masses=masses, reference_angle=1.,
                                          stiffness=(1, 1, 1, 1)) == ((0., 0., 0.),) * 4


@pytest.mark.parametrize("changes", [
    {'stiffness': (math.nan, 1)}, {'inverse_masses': (-1, 1)}, {'positions': [(0, 0, 0)]},
    {'length_smoothing_byte': 256}, {'per_frame_flags': -1}, {'particle_extra_flags': (65536, 0)},
    {'reference_length': -1}, {'follow_the_leader_ratio': math.inf},
])
def test_invalid_distance_inputs_are_rejected(changes):
    with pytest.raises(ValueError):
        stretch(**changes)


@pytest.mark.parametrize("frame,extra", [(bytes(99), None), (bytes(100), bytes(27)),
                                         (bytes(66) + struct.pack('<e', math.nan) + bytes(32), None)])
def test_stiffness_rejects_bad_record_sizes_and_nonfinite_values(frame, extra):
    with pytest.raises(ValueError):
        decode_guide_constraint_stiffness(frame, extra)
