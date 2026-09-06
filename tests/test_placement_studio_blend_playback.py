"""Acceptance of stored parameter scale, two smoothing stages and held weights."""
from dataclasses import replace
import math

import pytest

from tools.placement_studio.blend_playback import advance, PreviewBlends
from tools.placement_studio.motionblending import Dimension, Example, MotionSpace, BlendError


def space(*, factor=0., rates=(1., 3.), scale=1., keep=0):
    return MotionSpace('test.motionblending', '', ('a.paa', 'b.paa'),
        (Dimension('Speed', 0., 1., True, scale, factor),),
        (Example((0.,), (0,), (1,)), Example((1.,), (1,), (1,))),
        (), (), True, 2., rates, keep_weights=keep)


def test_parameter_scale_precedes_clamping_and_supports_reversed_input_bounds():
    assert dict(space(scale=2).weights((.25,))) == {0:.5, 1:.5}
    assert dict(space(scale=2).weights((1.,))) == {1:1.}
    assert space(scale=-2).dimensions[0].input_bounds == (-.5, -0.)
    assert dict(space(scale=-2).weights((-.25,))) == {0:.5, 1:.5}
    assert space(scale=0).dimensions[0].input_bounds == (0., 0.)


def test_exponential_parameter_smoothing_has_the_expected_half_life():
    blend = space(factor=math.log(2), rates=(100., 100.))
    before = advance(blend, (0.,))
    half = advance(blend, (1.,), before, elapsed=1.)
    assert half.parameters == pytest.approx((.5,))
    assert dict(half.weights)[1] == pytest.approx(.5)
    quarter = advance(blend, (1.,), half, elapsed=1.)
    assert quarter.parameters == pytest.approx((.75,))
    assert advance(blend, (1.,), before, elapsed=0.) is before


def test_weight_speed_depends_on_largest_difference_and_stays_normalized():
    blend = space()
    before = advance(blend, (0.,))
    moved = advance(blend, (1.,), before, elapsed=.1)
    assert dict(moved.weights) == pytest.approx({0:.7, 1:.3})
    # Delta .7 -> speed 1 + (3-1)*.7 = 2.4, so the next step moves .24.
    moved = advance(blend, (1.,), moved, elapsed=.1)
    assert dict(moved.weights) == pytest.approx({0:.46, 1:.54})
    arrived = advance(blend, (1.,), moved, elapsed=20.)
    assert dict(arrived.weights) == pytest.approx({0:0., 1:1.})
    assert sum(weight for _, weight in arrived.weights) == pytest.approx(1.)
    frozen = advance(space(rates=(-2., -1.)), (1.,), before, elapsed=2.)
    assert dict(frozen.weights) == {0:1., 1:0.}


def test_smoothing_is_separate_from_character_scale_and_initial_weight_hold():
    blend = space(keep=1)
    before = advance(blend, (.2,))
    assert advance(blend, (1.,), before, elapsed=100.) is before
    assert dict(advance(blend, (1.,)).weights) == {1:1.}
    assert advance(replace(blend, keep_weights=0), (1.,), before, smoothing=False).parameters == (1.,)
    # Character scale is input metadata, not a multiplier on weights or clip duration.
    assert replace(blend, scale=10.).weights((.3,)) == blend.weights((.3,))


def test_comparison_calls_are_idempotent_and_paused_changes_or_seek_restart_cleanly():
    blend = space(); clock = PreviewBlends()
    clock.sample(blend, (0.,), 0., playing=True)
    current = clock.sample(blend, (1.,), .1, playing=True)
    assert clock.sample(blend, (1.,), .1, playing=True) == current
    assert clock.sample(blend, (1.,), 0., playing=True) == current  # Shared clock loop.
    static = clock.sample(blend, (.6,), 0., playing=False)
    assert dict(static.weights)[1] == pytest.approx(.6)
    clock.reset()
    assert clock.sample(blend, (1.,), 0.).parameters == (1.,)


@pytest.mark.parametrize('parameters,elapsed', [((float('nan'),),0), ((),0), ((1.,),-1), ((1.,),float('inf'))])
def test_invalid_clock_or_parameters_are_rejected(parameters, elapsed):
    with pytest.raises(BlendError): advance(space(), parameters, elapsed=elapsed)
