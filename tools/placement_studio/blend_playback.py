"""Installed blend smoothing equations, independent of UI and clip payloads.

ParameterDimension defaults: scale 1, smoothing 0. MotionSpace weight speeds
default to 1.75 and 3.5. The inspected reader's constructors supply these when
fields are omitted. Parameter smoothing precedes scale/clamping/triangulation;
weight smoothing follows triangulation and preserves the normalized sum.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from .motionblending import BlendError


@dataclass(frozen=True, slots=True)
class BlendState:
    parameters: tuple[float, ...]
    weights: tuple[tuple[int, float], ...]


def advance(space, parameters, previous=None, *, elapsed=0., smoothing=True):
    parameters = tuple(parameters)
    if len(parameters) != len(space.dimensions) or any(not math.isfinite(p) for p in parameters):
        raise BlendError('Invalid blend parameters')
    if not math.isfinite(elapsed) or elapsed < 0:
        raise BlendError('Invalid blend elapsed time')
    if previous is not None and space.keep_weights:
        return previous
    if previous is None or not smoothing:
        return BlendState(parameters, space.weights(parameters))
    if elapsed == 0:
        return previous
    filtered = []
    for dimension, before, target in zip(space.dimensions, previous.parameters, parameters):
        factor = dimension.smoothing or 0.
        alpha = -math.expm1(-factor * elapsed) if factor > 0 else 1.
        filtered.append(before + (target - before) * alpha)
    target_weights = dict(space.weights(filtered))
    old = dict(previous.weights)
    indices = sorted(old.keys() | target_weights.keys())
    delta = min(1., max((abs(target_weights.get(i, 0.) - old.get(i, 0.)) for i in indices), default=0.))
    lo, hi = (max(0., value if value is not None else default)
              for value, default in zip(space.smoothing, (1.75, 3.5)))
    speed = lo + (hi - lo) * delta
    alpha = min(1., elapsed * speed / delta) if delta > 0 else 0.
    weights = tuple((i, old.get(i, 0.) + (target_weights.get(i, 0.) - old.get(i, 0.)) * alpha) for i in indices)
    return BlendState(tuple(filtered), weights)


class PreviewBlends:
    """One state per space and shared clock; repeated A/B renders are idempotent."""
    def __init__(self):
        self._states = {}

    def reset(self):
        self._states.clear()

    def sample(self, space, parameters, seconds, *, playing=False, smoothing=True):
        prior = self._states.get(space.path)
        previous, elapsed = None, 0.
        if prior is not None and prior[0] is space:
            _, old_seconds, old_input, previous = prior
            elapsed = max(0., seconds - old_seconds)
            # Paused controls inspect a fixed pose immediately. A held initial
            # weight set changes only on an explicit restart or new space.
            if not playing and tuple(parameters) != old_input and not space.keep_weights:
                previous = None
        state = advance(space, parameters, previous, elapsed=elapsed, smoothing=smoothing)
        self._states[space.path] = (space, seconds, tuple(parameters), state)
        return state
