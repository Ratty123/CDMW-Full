"""Mathematical reference for the guide branch of ComputePbdUpdateResult.

Runtime buffers and flags are explicit inputs, not inferred from a PAC. This
stage converts supplied particle results into guide frames; it is not a cloth
solver or a bit-exact implementation of GPU float32/fast-math operations.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .pac_cloth_skinning import _matrix4


_IDENTITY = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))


def _point(value):
    if len(value) != 3 or any(not math.isfinite(x) for x in value):
        raise ValueError("Guide frame inputs must be finite three-component vectors.")
    return tuple(float(x) for x in value)


def _points(values, count):
    if len(values) != count:
        raise ValueError("Guide frame inputs require one value per guide.")
    return tuple(_point(value) for value in values)


def _flags(value):
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("Guide frame flags must be unsigned 32-bit integers.")
    return value


def _basis(value):
    if len(value) != 3:
        raise ValueError("Guide frame bases must be 3 by 3 row-major matrices.")
    return _points(value, 3)


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _lerp(a, b, weight):
    return tuple(x + weight * (y - x) for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _unit(value):
    length = math.hypot(*value)
    if not math.isfinite(length) or length == 0:
        raise ValueError("Degenerate guide rotation has no supported finite shader result.")
    return tuple(x / length for x in value)


def _transform(value, basis):
    return tuple(sum(value[i] * basis[i][j] for i in range(3)) for j in range(3))


def _multiply(a, b):
    return tuple(_transform(row, b) for row in a)


def _inverse(basis):
    a, b, c = basis
    cofactors = (_cross(b, c), _cross(c, a), _cross(a, b))
    determinant = sum(a[i] * cofactors[0][i] for i in range(3))
    if not math.isfinite(determinant) or determinant == 0:
        raise ValueError("Degenerate guide rotation has no supported finite shader result.")
    return tuple(tuple(cofactors[j][i] / determinant for j in range(3)) for i in range(3))


def select_guide_result_positions(
    animation_positions: Sequence[Sequence[float]],
    previous_positions: Sequence[Sequence[float]],
    simulated_positions: Sequence[Sequence[float]],
    *, per_frame_flags2: int, interpolation_ratio: float, animation_blend: float,
) -> tuple[tuple[float, ...], ...]:
    """Select the positions used for guide translations, before space conversion.

    Particle offsets 0, 12 and 36 are respectively `_ix`, `_p[0]` and `_x`.
    Unless per-frame flags2 bit 0x800 is set, interpolate `_p[0]` toward `_x`.
    Then blend toward `_ix`. Both factors are saturated to [0, 1].

    Supply remaining/fixed simulation delta time as interpolation_ratio, using
    the scaled clock when flags2 bit 0x8000 is set. animation_blend is the
    decoded half at per-frame offset 78 (high half of packed `_p6`). Native
    16-bit shader reflection names it `_fadingRatio`, distinct from offset 96's
    packed smoothing field. pac_cloth_runtime.advance_cloth_frame_blend supplies
    the decoded CPU fade update from explicit controller/scene inputs.
    """
    flags = _flags(per_frame_flags2)
    count = len(animation_positions)
    animation = _points(animation_positions, count)
    previous = _points(previous_positions, count)
    simulated = _points(simulated_positions, count)
    if not math.isfinite(interpolation_ratio) or not math.isfinite(animation_blend):
        raise ValueError("Guide position blend inputs must be finite.")
    interpolation = max(0., min(1., interpolation_ratio))
    blend = max(0., min(1., animation_blend))
    return tuple(_point(_lerp(current if flags & 0x800 else _lerp(old, current, interpolation), target, blend))
                 for target, old, current in zip(animation, previous, simulated))


def _single_edge_rotation(index, neighbors, animation, simulated, result):
    # A valid second neighbor wins even when its edge is too short. Only an
    # out-of-range second index allows the first-neighbor branch to run.
    neighbor = neighbors[1] if neighbors[1] < len(animation) else neighbors[0]
    if neighbor >= len(animation):
        return _IDENTITY
    a = _sub(animation[index], animation[neighbor])
    b = _sub(result[index], simulated[neighbor])
    if min(math.hypot(*a), math.hypot(*b)) <= 0.009999999776482582:
        return _IDENTITY
    a, b = _unit(a), _unit(b)
    cosine = sum(x * y for x, y in zip(a, b))
    if cosine < -0.9998999834060669:
        # The shader deliberately chooses -I, not a 180-degree proper rotation.
        return tuple(tuple(-x for x in row) for row in _IDENTITY)
    x, y, z = _cross(a, b)
    h = 1. / (1. + cosine)
    return ((cosine + h*x*x, h*x*y + z, h*x*z - y),
            (h*x*y - z, cosine + h*y*y, h*y*z + x),
            (h*x*z + y, h*y*z - x, cosine + h*z*z))


def _two_edge_rotation(index, neighbors, animation, simulated):
    directions = []
    for neighbor, fallback in zip(neighbors, (_IDENTITY[1], _IDENTITY[0])):
        if neighbor >= len(animation):
            directions.append((fallback, fallback))
            continue
        a = _sub(animation[neighbor], animation[index])
        b = _sub(simulated[neighbor], simulated[index])
        input_direction, simulated_direction = _unit(a), _unit(b)
        blend = max(0., min(1., math.hypot(*b) / (0.800000011920929 * math.hypot(*a))))
        directions.append((input_direction, _unit(_lerp(input_direction, simulated_direction, blend))))
    frames = []
    for column in range(2):
        y, second = directions[0][column], directions[1][column]
        z = _unit(_cross(second, y))
        x = _unit(_cross(y, z))
        frames.append((x, y, z))
    return _multiply(_inverse(frames[0]), frames[1])


def update_guide_result_frames(
    animation_frames: Sequence[Sequence[Sequence[float]]],
    *, animation_positions: Sequence[Sequence[float]],
    simulated_positions: Sequence[Sequence[float]],
    result_positions: Sequence[Sequence[float]],
    orientation_neighbors: Sequence[Sequence[int] | None],
    per_frame_flags: int, world_basis: Sequence[Sequence[float]],
    inverse_world_basis: Sequence[Sequence[float]],
    pbd_space_offset: Sequence[float], runtime_blend_factors: Sequence[float],
) -> tuple[tuple[tuple[float, ...], ...], ...]:
    """Update existing animated guide frames from supplied particle positions.

    flags bit 0x10000 suppresses this guide update; bit 0x4000 enables rotation.
    When enabled, bit 0x80000 selects single-edge rotation, otherwise two-edge
    frame alignment. These flags' runtime owners must be supplied by the caller.

    Neighbors are the two unsigned 16-bit indices from particle offset 112.
    Out-of-range values have shader-defined behavior. None from preparation
    means unknown memory, not an invalid-index sentinel, and cannot be consumed
    by an enabled rotation branch. Singular frame math is reported unsupported.

    Positions share PBD simulation coordinates. Rotation maps animation `_ix`
    toward simulation `_x`; only the single-edge branch uses the selected result
    for its own endpoint. Transform the old model basis through world, rotation,
    then inverse-world bases. Translation is (result + offset) * inverse-world
    basis, without an inverse translation row. The caller supplies the shader's
    actual three-row bases, not inferred or silently inverted transforms.

    Supply guide_runtime_blend_factor results for row0.w. Other w components
    remain metadata. Frames can then feed prepare_guide_skinning_matrices.
    """
    flags = _flags(per_frame_flags)
    frames = tuple(_matrix4(frame) for frame in animation_frames)
    if flags & 0x10000:
        return frames
    count = len(frames)
    animation = _points(animation_positions, count)
    simulated = _points(simulated_positions, count)
    result = _points(result_positions, count)
    world, inverse_world = _basis(world_basis), _basis(inverse_world_basis)
    offset = _point(pbd_space_offset)
    if len(orientation_neighbors) != count or len(runtime_blend_factors) != count:
        raise ValueError("Guide frame inputs require one value per guide.")
    if any(not math.isfinite(x) or not 0 <= x <= 1 for x in runtime_blend_factors):
        raise ValueError("Guide runtime blend factors must be finite and within [0, 1].")
    updated = []
    for index, frame in enumerate(frames):
        basis = tuple(row[:3] for row in frame[:3])
        if flags & 0x4000:
            neighbors = orientation_neighbors[index]
            if neighbors is None:
                raise ValueError("Rotation requires known orientation neighbors; untouched memory is unknown.")
            if len(neighbors) != 2 or any(type(x) is not int or not 0 <= x <= 0xFFFF for x in neighbors):
                raise ValueError("Orientation neighbors must be two unsigned 16-bit indices.")
            rotation = (_single_edge_rotation(index, neighbors, animation, simulated, result)
                        if flags & 0x80000 else _two_edge_rotation(index, neighbors, animation, simulated))
            basis = _multiply(_multiply(_multiply(basis, world), rotation), inverse_world)
        translation = _transform(tuple(x + y for x, y in zip(result[index], offset)), inverse_world)
        updated.append(_matrix4(((*basis[0], runtime_blend_factors[index]),
                                 (*basis[1], frame[1][3]), (*basis[2], frame[2][3]),
                                 (*translation, frame[3][3]))))
    return tuple(updated)
