"""Decoded guide constraint projection math, before contacts and dispatch.

Inputs are the selected runtime values, after upload/half decoding. These
functions return position corrections from one input iteration; callers must
accumulate them without feeding one correction into another constraint's input.
They do not select active constraints, execute collision/flag propagation,
integrate time, or emulate GPU float32/half rounding.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence


def _points(values, count):
    if len(values) != count or any(len(p) != 3 or any(not math.isfinite(x) for x in p) for p in values):
        raise ValueError(f"Constraint projection requires {count} finite three-component points.")
    return tuple(tuple(float(x) for x in p) for p in values)


def _scalars(values, count, *, nonnegative=False):
    if len(values) != count or any(not math.isfinite(x) or (nonnegative and x < 0) for x in values):
        raise ValueError(f"Constraint projection requires {count} finite scalar inputs with valid signs.")
    return tuple(float(x) for x in values)


def _flags(values, count, limit=0xFFFFFFFF):
    if len(values) != count or any(type(x) is not int or not 0 <= x <= limit for x in values):
        raise ValueError("Constraint flags must be unsigned integers of the declared width.")


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2], a[0]*b[1] - a[1]*b[0])


def decode_guide_constraint_stiffness(
    per_frame: bytes, particle_extra: bytes | None,
) -> tuple[float, float]:
    """Select stretch/bend stiffness from complete 100/28-byte runtime records.

    Native 16-bit shader reflection identifies per-frame half offsets 66/68 as
    modified stretch/bend stiffness, and extra-data half offsets 8/10 as their
    overrides. A negative override falls back to the corresponding frame value;
    zero is a real override. Absent extra data supplies the shader's -1 sentinel.
    This does not derive modified stiffness from material XML or clamp it.
    """
    if len(per_frame) != 100 or (particle_extra is not None and len(particle_extra) != 28):
        raise ValueError("Stiffness decoding requires complete 100-byte frame and optional 28-byte extra records.")
    frame_values = _scalars(struct.unpack_from('<2e', per_frame, 66), 2)
    overrides = (-1., -1.) if particle_extra is None else _scalars(struct.unpack_from('<2e', particle_extra, 8), 2)
    return tuple(base if override < 0 else override for base, override in zip(frame_values, overrides))


def select_guide_bending_projection(
    upload_type: int, *, per_frame_flags2: int, particle: bytes, particle_extra: bytes | None,
) -> str:
    """Select the formulation after guide bend/iteration gates have enabled it.

    Type 2 uses coefficients only with flags2 bit 0x400 and effective input
    position blend < .5. That blend is particle half94 (_ix_blend_rate), unless
    overridden by a nonnegative extra-data half6. It is NOT particle half90
    (_cr). Type 1 and the remaining eligible type-2 cases use angle bending.
    This selector does not determine whether the constraint runs this iteration.
    """
    if type(upload_type) is not int or upload_type not in (1, 2):
        raise ValueError("Guide bending selection requires upload type 1 or 2.")
    _flags((per_frame_flags2,), 1)
    if len(particle) != 152 or (particle_extra is not None and len(particle_extra) != 28):
        raise ValueError("Bend selection requires complete 152-byte particle and optional 28-byte extra records.")
    base = struct.unpack_from('<e', particle, 94)[0]
    override = -1. if particle_extra is None else struct.unpack_from('<e', particle_extra, 6)[0]
    _scalars((base, override), 2)
    blend = base if override < 0 else override
    return "coefficient" if upload_type == 2 and per_frame_flags2 & 0x400 and blend < .5 else "angle"


def cloth_stretch_corrections(
    positions: Sequence[Sequence[float]], *, animation_positions: Sequence[Sequence[float]],
    inverse_masses: Sequence[float], lra_ratios: Sequence[float], stiffness: Sequence[float],
    reference_length: float, uploaded_inverse_mass_sum: float, bone_scale: float,
    stretching_scale: float, length_smoothing_byte: int, follow_the_leader_ratio: float,
    per_frame_flags: int, particle_flags: Sequence[int], particle_extra_flags: Sequence[int],
) -> tuple[tuple[float, ...], ...]:
    """Core type-0 stretch correction for the two endpoints in record order.

    positions are the selected `_p` input buffer, not `_x`. Rest length first
    scales by scene-object boneScale, blends toward the `_ix` edge using the low
    byte of packedSmoothingRatios / 255, then scales by material stretchingScale.
    The uploaded normalization is 1 / (initial wA + initial wB); do not recompute
    it from current or follow-the-leader masses. stiffness is selected per end.

    Follow-the-leader is disabled for an underwater endpoint (particle bit 0x80).
    Otherwise it can replace the mass pair with 1-ratio / 1+ratio according to
    their LRA ratios. Its comparisons and thresholds follow the shader. Frame
    bit 0x80000 halves stiffness for target lengths below .01 unless the current
    particle's extra flag 4 disables that branch. These switches are supplied,
    not inferred from the material's simulation mode.

    This is the core correction only. Global stretch enable, record-index flag
    checks, contacts, collision flags, normal propagation and dispatch are outside
    this function and must not be treated as implicitly handled.
    """
    p, animated = _points(positions, 2), _points(animation_positions, 2)
    masses = _scalars(inverse_masses, 2, nonnegative=True)
    ratios, strengths = _scalars(lra_ratios, 2), _scalars(stiffness, 2)
    reference, normalization, scale, stretch = _scalars(
        (reference_length, uploaded_inverse_mass_sum, bone_scale, stretching_scale), 4, nonnegative=True,
    )
    _scalars((follow_the_leader_ratio,), 1)
    _flags((per_frame_flags,), 1)
    _flags(particle_flags, 2)
    _flags(particle_extra_flags, 2, 0xFFFF)
    _flags((length_smoothing_byte,), 1, 255)
    target = scale * reference
    if length_smoothing_byte:
        target += (math.dist(*animated) - target) * (length_smoothing_byte / 255.)
    target *= stretch
    edge = _sub(p[0], p[1])
    length = math.hypot(*edge)
    error = length - target
    if not all(math.isfinite(x) for x in (target, length, error)):
        raise ValueError("Constraint projection produced non-finite geometry.")
    if length <= 9.999999747378752e-5 or abs(error) <= 9.999999747378752e-5:
        return ((0., 0., 0.),) * 2
    result = []
    for index in range(2):
        a, b = masses
        leader = 0. if particle_flags[index] & 0x80 else follow_the_leader_ratio
        if leader > .0010000000474974513:
            if ratios[0] < ratios[1] - .05000000074505806 and a > .10000000149011612 and b > .10000000149011612:
                a, b = 1. - leader, 1. + leader
            if ratios[1] < ratios[0] - .05000000074505806 and a > .10000000149011612 and b > .10000000149011612:
                a, b = 1. + leader, 1. - leader
        strength = strengths[index]
        if per_frame_flags & 0x80000 and not particle_extra_flags[index] & 4 and target < .009999999776482582:
            strength *= .5
        weight = -a if index == 0 else b
        amount = strength * normalization * error * weight / length
        result.append(tuple(x * amount for x in edge))
    return _points(result, 2)


def cloth_coefficient_bending_corrections(
    positions: Sequence[Sequence[float]], *, inverse_masses: Sequence[float],
    coefficients: Sequence[float], stiffness: Sequence[float],
) -> tuple[tuple[float, ...], ...]:
    """Core coefficient-bending branch, with four coefficients in A/B/C/D order.

    In the packed upload these are k1, k2, k3 and the reused inv_sum_w lane.
    Computation uses positions relative to A, preserving the shader's behavior
    even if half rounding makes the four coefficients sum to a nonzero value.
    A denominator <= float32(.1) skips correction, as in the shader.

    Upload type 2 alone does not enable this branch: it additionally requires
    guide mode, frame flags2 bit 0x400, effective input position blend < .5 and
    the surrounding bend/iteration gates. Other eligible cases use angle bending.
    Activation must be resolved before calling this mathematical reference.
    """
    p = _points(positions, 4)
    masses = _scalars(inverse_masses, 4, nonnegative=True)
    k, strengths = _scalars(coefficients, 4), _scalars(stiffness, 4)
    relative = tuple(_sub(value, p[0]) for value in p)
    q = tuple(sum(k[i] * relative[i][j] for i in range(1, 4)) for j in range(3))
    gradients = tuple(tuple(value * component for component in q) for value in k)
    denominator = sum(w * _dot(g, g) for w, g in zip(masses, gradients))
    if not math.isfinite(denominator):
        raise ValueError("Constraint projection produced non-finite geometry.")
    if denominator <= .10000000149011612:
        return ((0., 0., 0.),) * 4
    energy = .5 * _dot(q, q)
    return _points(tuple(tuple(-s * energy / denominator * w * x for x in gradient)
                         for s, w, gradient in zip(strengths, masses, gradients)), 4)


def cloth_angle_bending_corrections(
    positions: Sequence[Sequence[float]], *, inverse_masses: Sequence[float],
    reference_angle: float, stiffness: Sequence[float],
) -> tuple[tuple[float, ...], ...]:
    """Core angle-bending branch for A/B/C/D, using the same directed A-B edge.

    Flat adjacent triangles have angle pi under this convention. Degenerate
    normals with squared length below float32(1e-5), or the weighted gradient
    denominator <= float32(.001), skip correction. Activation/iteration gates
    and contact-normal accumulation are outside this mathematical reference.
    """
    p = _points(positions, 4)
    masses = _scalars(inverse_masses, 4, nonnegative=True)
    strengths = _scalars(stiffness, 4)
    _scalars((reference_angle,), 1)
    edge, c, d = (_sub(value, p[0]) for value in p[1:])
    n1, n2 = _cross(edge, c), _cross(edge, d)
    squares = _dot(n1, n1), _dot(n2, n2)
    if any(not math.isfinite(x) for x in squares):
        raise ValueError("Constraint projection produced non-finite geometry.")
    if min(squares) < 9.999999747378752e-6:
        return ((0., 0., 0.),) * 4
    length1, length2 = (math.sqrt(x) for x in squares)
    n1, n2 = tuple(x / length1 for x in n1), tuple(x / length2 for x in n2)
    cosine = max(-1., min(1., _dot(n1, n2)))

    def gradient(value, first, second, length):
        a, b = _cross(value, second), _cross(value, first)
        return tuple((x - cosine * y) / length for x, y in zip(a, b))

    gc, gd = gradient(edge, n1, n2, length1), gradient(edge, n2, n1, length2)
    bc, bd = gradient(c, n1, n2, length1), gradient(d, n2, n1, length2)
    gb = tuple(-x - y for x, y in zip(bc, bd))
    ga = tuple(-x - y - z for x, y, z in zip(gb, gc, gd))
    gradients = ga, gb, gc, gd
    denominator = sum(w * _dot(g, g) for w, g in zip(masses, gradients))
    if not math.isfinite(denominator):
        raise ValueError("Constraint projection produced non-finite geometry.")
    if denominator <= .0010000000474974513:
        return ((0., 0., 0.),) * 4
    amount = -math.sqrt(max(0., 1. - cosine*cosine)) * (math.acos(cosine) - reference_angle) / denominator
    return _points(tuple(tuple(s * amount * w * x for x in gradient)
                         for s, w, gradient in zip(strengths, masses, gradients)), 4)
