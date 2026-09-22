"""Numerical cases for the native scalar material spline evaluator."""
import pytest

from cdmw.services.effect_material_spline import sample_material_spline


def point(x, y, *, inner=0., outer=0., mode=0):
    return dict(position=(x, y), inner_tangent=inner, outer_tangent=outer, interpolation=mode)


def test_native_bezier_tangents_are_segment_control_offsets():
    # Native RVA 0x3e39414..0x3e3948c: controls become (0, 1, 1, 1).
    # Hermite slope interpretation would give .625 at t=.5, not .875.
    assert sample_material_spline([point(0., 0., outer=1.), point(1., 1.)], 5) == pytest.approx(
        (0., .578125, .875, .984375, 1.)
    )
    # Unequal segment width and an incoming control below the endpoint.
    assert sample_material_spline([point(0., 0., outer=2.), point(.5, 1., inner=-2.), point(1., 1.)], 5) == pytest.approx(
        (0., .5, 1., 1., 1.)
    )


def test_linear_and_hold_modes_do_not_apply_cubic_tangents():
    for mode, expected in [(2, (2., 3., 4., 5., 6.)), (3, (2., 2., 2., 2., 6.))]:
        assert sample_material_spline([point(0., 2., outer=80., mode=mode), point(1., 6., inner=-80.)], 5) == expected


def test_unknown_noise_and_easing_modes_are_not_silently_linearized():
    assert sample_material_spline([point(0., 0., mode=37), point(1., 1.)]) == ()
    assert sample_material_spline([point(0., 0., mode=5), point(1., 1.)]) == ()
    assert sample_material_spline([point(.5, 0.), point(.5, 1.)]) == ()
    assert sample_material_spline([point(0., float("nan"))]) == ()
    assert sample_material_spline([point(.5, 2.)]) == (2.,) * 128
