"""Decoded normal-step final cloth movement, with explicit runtime inputs.

These are mathematical references for ComputePbdProcessFinalMovement. They do
not select dispatches, handle reset/hold branches, update contact bookkeeping,
or emulate GPU rounding. They do not infer runtime settings from material XML.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence


def _point(value):
    if len(value) != 3 or any(not math.isfinite(x) for x in value):
        raise ValueError("Final movement requires finite three-component vectors.")
    return tuple(float(x) for x in value)


def _finite(*values):
    if any(not math.isfinite(x) for x in values):
        raise ValueError("Final movement requires finite scalar inputs.")


def _flags(value):
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("Final movement flags must be unsigned 32-bit integers.")
    return value


def _record(value, size):
    if len(value) != size:
        raise ValueError(f"Final movement requires a complete {size}-byte runtime record.")


def cloth_attachment_correction(
    position: Sequence[float], *, animation_position: Sequence[float],
    anchor_indices: Sequence[int], anchor_rest_lengths: Sequence[float],
    particle_positions: Sequence[Sequence[float]],
    animation_positions: Sequence[Sequence[float]], inverse_masses: Sequence[float],
    particle_flags: Sequence[int], bone_scale: float, stretching_scale: float,
    per_frame_flags: int, current_particle_flags: int,
) -> tuple[float, ...]:
    """Average the active long-range attachment corrections, at most four.

    position is the current particle's selected solver output (_p[1] for an
    odd iteration count, _p[0] otherwise). Anchor particle_positions always use
    _p[0], regardless of that parity. Rest distances are the uploaded halves.

    Frame bit 0x80 enables this pass; current particle bit 0x40 skips it. An
    anchor must be in range and have inverse mass exactly zero or bit 0x40.
    Frame bit 0x800000 expands the bone-scaled radius to at least the animated
    distance, before multiplying by float32(1.1) and stretching scale.
    Only violated radii contribute to the average, from the same input point.
    Out-of-range u16 anchors are skipped; no candidate is silently substituted.
    """
    p, animated = _point(position), _point(animation_position)
    count = len(particle_positions)
    if any(len(values) != count for values in (animation_positions, inverse_masses, particle_flags)):
        raise ValueError("Attachment arrays must have the same particle count.")
    if len(anchor_indices) != len(anchor_rest_lengths) or len(anchor_indices) > 4:
        raise ValueError("Attachments require up to four paired indices and rest lengths.")
    if any(type(i) is not int or not 0 <= i <= 0xFFFF for i in anchor_indices):
        raise ValueError("Attachment indices must be unsigned 16-bit integers.")
    positions = tuple(_point(value) for value in particle_positions)
    animation = tuple(_point(value) for value in animation_positions)
    _finite(bone_scale, stretching_scale, *inverse_masses, *anchor_rest_lengths)
    if min((bone_scale, stretching_scale, *inverse_masses, *anchor_rest_lengths)) < 0:
        raise ValueError("Attachment scales, inverse masses and rest lengths must be nonnegative.")
    flags = _flags(per_frame_flags)
    current_flags = _flags(current_particle_flags)
    for value in particle_flags:
        _flags(value)
    if not flags & 0x80 or current_flags & 0x40:
        return (0., 0., 0.)
    corrections = []
    for index, rest in zip(anchor_indices, anchor_rest_lengths):
        if index >= count or (inverse_masses[index] != 0 and not particle_flags[index] & 0x40):
            continue
        radius = rest * bone_scale
        if flags & 0x800000:
            radius = max(radius, math.dist(animation[index], animated))
        radius *= stretching_scale * 1.100000023841858
        delta = tuple(a - b for a, b in zip(positions[index], p))
        distance = math.hypot(*delta)
        _finite(radius, distance)
        if distance > radius:
            corrections.append(tuple(x / distance * (distance - radius) for x in delta))
    if not corrections:
        return (0., 0., 0.)
    return _point(tuple(sum(row[i] for row in corrections) / len(corrections) for i in range(3)))


def guide_final_input_blend(
    particle: bytes, per_frame: bytes, per_scene: bytes, particle_extra: bytes | None,
    *, use_input_position_blending: bool,
) -> float:
    """Resolve the final-pass animation blend from complete runtime records.

    The global use-input-position-blending switch is explicit. Particle half94
    (not _cr at half90) is overridden by a nonnegative extra-data half6. The
    frame's half44 stiffness scale modifies the blend, which this final pass
    discards unless strictly above float32(.999). Other stages can still use
    smaller weights. Pinch/state overrides and their ordering are retained.
    """
    for record, size in ((particle, 152), (per_frame, 100), (per_scene, 108)):
        _record(record, size)
    if particle_extra is not None:
        _record(particle_extra, 28)
    if type(use_input_position_blending) is not bool:
        raise ValueError("Input position blending requires an explicit boolean global switch.")
    flags, flags2 = struct.unpack_from('<2I', per_frame, 32)
    scene_flags = struct.unpack_from('<I', per_scene, 64)[0]
    if not use_input_position_blending or (flags2 & 0x80 and scene_flags & 0x4000):
        return 0.
    particle_flags = struct.unpack_from('<I', particle, 64)[0]
    base = struct.unpack_from('<e', particle, 94)[0]
    override = -1. if particle_extra is None else struct.unpack_from('<e', particle_extra, 6)[0]
    scale = struct.unpack_from('<e', per_frame, 44)[0]
    timer = struct.unpack_from('<f', particle, 120)[0]
    _finite(base, override, scale, timer)
    weight = base if override < 0 else override
    scaled = scale * weight if scale < 1 else (scale - 1) + (2 - scale) * weight
    _finite(scaled)
    blend = min(1., max(0., scaled)) if weight < 1 else 1.
    if blend <= .9990000128746033:
        blend = 0.
    if flags2 & 0x800000 and particle_flags & 0x80:
        blend = blend**5
    suppress_velocity = bool(flags & 1 and not flags2 & 0x80)
    state_mask = bool(particle_flags & 0x300000)
    forced_state = state_mask and suppress_velocity
    if state_mask and not forced_state:
        blend = 0.
    if particle_flags & (0x40 | 0x300) or forced_state or 100000 <= timer <= 100001:
        blend = 1.
    if timer > 100001:
        recovery = min(1., max(0., (timer - 100001) * .3333333432674408))
        blend = 1. + recovery * (blend - 1.)
    return blend


def finalize_cloth_motion(
    position: Sequence[float], *, animation_position: Sequence[float],
    previous_position: Sequence[float], velocity_reference_position: Sequence[float],
    attachment_correction: Sequence[float], animation_blend: float, inverse_mass: float,
    particle_flags: int, per_frame: bytes, per_scene: bytes, simulation_parameter: bytes,
    fixed_substep_delta_time: float, variable_substep_delta_time: float,
    minimum_velocity_delta_time: float,
) -> dict:
    """Apply normal-path corrections, velocity limits and ground response.

    position is selected _p[iterationCount & 1]; previous_position is old _x,
    NOT _p[0]. velocity_reference_position is currentPosForVelocity at half-open
    byte range [48, 60). Pass the two reference functions' correction and blend.
    This consumes already eligible runtime state. Reset/hold branches are
    rejected; visibility, dispatch, collision flags/normals and NaN recovery are
    not simulated here. Inputs and supported outputs must be finite.

    Frame flags2 bit 0x40 also shifts the velocity reference by the attachment
    correction. Velocity uses the selected fixed/variable clock times scene
    timeScale, floored by the supplied minimum dt. Speed limiting and velocity
    suppression precede ground response, so ground response can reintroduce
    motion or exceed the earlier cap. Returned previous_position is the new
    _p[0] history; position is the new _p[1] and _x. No runtime records mutate.
    """
    p, animation = _point(position), _point(animation_position)
    previous, reference = _point(previous_position), _point(velocity_reference_position)
    correction = _point(attachment_correction)
    for record, size in ((per_frame, 100), (per_scene, 108), (simulation_parameter, 312)):
        _record(record, size)
    flags, flags2 = struct.unpack_from('<2I', per_frame, 32)
    state = _flags(particle_flags)
    if flags & 0xC00 or state & 0x80004 == 0x80004:
        raise ValueError("Reset/hold branches are outside the normal movement reference.")
    _finite(animation_blend, inverse_mass, fixed_substep_delta_time,
            variable_substep_delta_time, minimum_velocity_delta_time)
    if not 0 <= animation_blend <= 1 or min(inverse_mass, fixed_substep_delta_time,
                                         variable_substep_delta_time, minimum_velocity_delta_time) < 0:
        raise ValueError("Movement blend, inverse mass and delta times are outside the supported domain.")
    time_scale = struct.unpack_from('<e', per_scene, 94)[0]
    speed_limit = struct.unpack_from('<e', per_frame, 54)[0]
    _finite(time_scale, speed_limit)
    if time_scale < 0 or speed_limit <= 0:
        raise ValueError("Movement requires nonnegative time scale and a positive speed limit.")
    selected_dt = variable_substep_delta_time if flags2 & 0x800 else fixed_substep_delta_time
    dt = max(minimum_velocity_delta_time, time_scale * selected_dt)
    _finite(dt)
    if dt <= 0:
        raise ValueError("Movement velocity requires a positive effective delta time.")
    p = tuple(x + d for x, d in zip(p, correction))
    if flags2 & 0x40:
        reference = tuple(x + d for x, d in zip(reference, correction))
    p = _point(tuple(x + animation_blend * (a - x) for x, a in zip(p, animation)))
    reference = _point(reference)
    velocity = _point(tuple((x - r) / dt for x, r in zip(p, reference)))
    if state & 4:
        speed_limit *= .10000000149011612
    speed = math.hypot(*velocity)
    _finite(speed)
    divisor = max(1., speed / speed_limit)
    velocity = tuple(x / divisor for x in velocity)
    suppress_velocity = bool(flags & 1 and not flags2 & 0x80)
    if suppress_velocity or inverse_mass < 9.999999747378752e-5:
        velocity = (0., 0., 0.)
    if state & 2:
        friction = struct.unpack_from('<e', simulation_parameter, 254)[0]
        bone_velocity = struct.unpack_from('<3e', per_frame, 56)
        front = struct.unpack_from('<3e', per_scene, 86)
        _finite(friction, *bone_velocity, *front)
        vx, vz = tuple((velocity[i] + bone_velocity[i]) * (1. - friction) - bone_velocity[i]
                       for i in (0, 2))
        if abs(front[1]) < .10000000149011612:
            push_back = struct.unpack_from('<e', per_frame, 46)[0]
            _finite(push_back)
            vx, vz = vx - front[0] * push_back, vz - front[2] * push_back
        velocity = (vx, 0., vz)
    history = p if suppress_velocity and not flags2 & 0x100 else previous
    return {"position": p, "previous_position": history,
            "velocity_reference_position": reference, "velocity": _point(velocity)}
