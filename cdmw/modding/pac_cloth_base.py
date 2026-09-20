"""Decoded force, damping, contact and prediction math from the normal base step.

These references operate after animation/space adjustment and runtime eligibility
selection. Scene sampling, wind/water force construction, collider queries and
state bookkeeping are separate stages, not implicitly supplied by these helpers.
They are mathematical references, not bit-exact GPU arithmetic or a full solver.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence


def _finite(*values):
    if any(not math.isfinite(x) for x in values):
        raise ValueError("Cloth base-step inputs and results must be finite.")


def _point(value):
    if len(value) != 3:
        raise ValueError("Cloth base-step vectors must have three components.")
    _finite(*value)
    return tuple(float(x) for x in value)


def _record(value, size):
    if len(value) != size:
        raise ValueError(f"Cloth base step requires a complete {size}-byte runtime record.")


def _boolean(value):
    if type(value) is not bool:
        raise ValueError("Cloth base-step switches require explicit booleans.")


def decode_cloth_force_parameters(
    simulation_parameter: bytes, per_frame: bytes, per_scene: bytes, particle_extra: bytes | None,
) -> tuple[float, float]:
    """Return gravity scalar and damping, preserving their DIFFERENT sentinels.

    Gravity is simulation half260 (or scene half82 when frame bit0x4000000 is
    set), plus simulation half262. Extra-data half16 replaces that whole sum
    only when <=0; positive values mean fallback, and absent data supplies +1.
    Damping is simulation half256 unless extra half18 is nonnegative; absent
    data supplies -1. Neither result is clamped or equated to XML values.
    """
    for record, size in ((simulation_parameter, 312), (per_frame, 100), (per_scene, 108)):
        _record(record, size)
    if particle_extra is not None:
        _record(particle_extra, 28)
    flags = struct.unpack_from('<I', per_frame, 32)[0]
    gravity, additive = struct.unpack_from('<2e', simulation_parameter, 260)
    if flags & 0x4000000:
        gravity = struct.unpack_from('<e', per_scene, 82)[0]
    damping = struct.unpack_from('<e', simulation_parameter, 256)[0]
    override_gravity, override_damping = (1., -1.) if particle_extra is None else struct.unpack_from('<2e', particle_extra, 16)
    _finite(gravity, additive, damping, override_gravity, override_damping)
    gravity = gravity + additive if override_gravity > 0 else override_gravity
    damping = damping if override_damping < 0 else override_damping
    _finite(gravity, damping)
    return gravity, damping


def integrate_cloth_forces(
    velocity: Sequence[float], *, gravity_direction: Sequence[float], gravity: float,
    delta_time: float, inverse_mass: float, underwater: bool, underwater_density: float,
    bone_acceleration: Sequence[float], inertial_scale: float, inertial_acceleration_limit: float,
    environmental_acceleration: Sequence[float], skip_external_forces: bool,
) -> dict:
    """Integrate gravity/buoyancy, capped bone inertia and resolved environment.

    gravity_direction is scene half3 at100; it is used as supplied, not normalized.
    dt is the selected substep clock times scene half94 timeScale. Buoyancy adds
    (direction.y * gravity / density) * inverse_mass on Y only. Bone acceleration
    is frame float3 at12 times simulation float48, capped by global PBD float1132.

    environmental_acceleration must ALREADY include the game's air/water force
    construction, acceleration cap, orientation response and wave modulation.
    pac_cloth_environment supplies that stage from explicit scene samples. It
    consumes velocity after gravity/inertia; resolve it from that intermediate
    state before supplying it here with the ORIGINAL velocity. The skip flag
    skips both inertia and environment, but still applies gravity and buoyancy.
    Runtime fixed/dynamic selection and underwater detection precede this call.
    """
    v, direction = _point(velocity), _point(gravity_direction)
    bone, environment = _point(bone_acceleration), _point(environmental_acceleration)
    _finite(gravity, delta_time, inverse_mass, underwater_density, inertial_scale, inertial_acceleration_limit)
    _boolean(underwater)
    _boolean(skip_external_forces)
    if delta_time < 0 or inverse_mass < 0 or inertial_acceleration_limit <= 0 or (underwater and underwater_density <= 0):
        raise ValueError("Cloth force integration requires valid time, mass, cap and active water density.")
    acceleration = tuple(-gravity * x for x in direction)
    if underwater:
        acceleration = (acceleration[0], acceleration[1] + direction[1] * gravity / underwater_density * inverse_mass,
                        acceleration[2])
    non_gravity = (0., 0., 0.)
    if not skip_external_forces:
        inertia = _point(tuple(x * inertial_scale for x in bone))
        magnitude = math.hypot(*inertia)
        _finite(magnitude)
        divisor = max(1., magnitude / inertial_acceleration_limit)
        non_gravity = _point(tuple(x / divisor + a for x, a in zip(inertia, environment)))
    result = _point(tuple(x + (g + a) * delta_time for x, g, a in zip(v, acceleration, non_gravity)))
    return {"velocity": result, "non_gravity_acceleration": non_gravity}


def apply_cloth_damping(
    velocity_after_forces: Sequence[float], *, particle: bytes, per_frame: bytes,
    damping: float, additional_horizontal_damping: float, advanced_damping: bytes | None,
) -> tuple[float, ...]:
    """Apply the normal per-step damper, with optional rigid group motion.

    Frame0x2000000 adds global _positionBasedDynamicsParameter.x to X/Z damping
    only. Axis coefficients are float32(.1) times the resulting damping, without
    dt scaling, exponentiation or clamping. advanced_damping, if selected, is the
    36-byte record referenced by frame u16 at74: x_cm, v_cm, angular_velocity.

    Frame flag0x4 AND an index !=FFFF selects that path. Its correction is coefficient
    * (v_cm + angular_velocity cross (OLD particle x - x_cm) - OLD particle v),
    added to velocity_after_forces. Subtracting the already force-updated velocity
    would damp the new forces too and is not the shader's advanced branch.
    """
    velocity = _point(velocity_after_forces)
    _record(particle, 152)
    _record(per_frame, 100)
    _finite(damping, additional_horizontal_damping)
    flags = struct.unpack_from('<I', per_frame, 32)[0]
    index = struct.unpack_from('<H', per_frame, 74)[0]
    horizontal = damping + (additional_horizontal_damping if flags & 0x2000000 else 0.)
    coefficients = (horizontal * .10000000149011612, damping * .10000000149011612,
                    horizontal * .10000000149011612)
    _finite(*coefficients)
    if flags & 4 and index != 0xFFFF:
        if advanced_damping is None:
            raise ValueError("Active advanced damping requires its referenced group record.")
        _record(advanced_damping, 36)
        center = _point(struct.unpack_from('<3f', advanced_damping, 0))
        group_velocity = _point(struct.unpack_from('<3f', advanced_damping, 12))
        angular = _point(struct.unpack_from('<3f', advanced_damping, 24))
        position = _point(struct.unpack_from('<3f', particle, 36))
        old_velocity = _point(struct.unpack_from('<3f', particle, 140))
        r = tuple(x - c for x, c in zip(position, center))
        spin = (angular[1]*r[2] - angular[2]*r[1], angular[2]*r[0] - angular[0]*r[2],
                angular[0]*r[1] - angular[1]*r[0])
        return _point(tuple(v + k * (cm + w - old) for v, k, cm, w, old in
                            zip(velocity, coefficients, group_velocity, spin, old_velocity)))
    return _point(tuple(v * (1. - k) for v, k in zip(velocity, coefficients)))


def cloth_contact_velocity_response(
    velocity: Sequence[float], *, normal: Sequence[float], friction: float, restitution: float,
) -> tuple[float, ...]:
    """Core response after contact eligibility, before position prediction.

    The normal is particle cn[0].xyz (halves72/74/76), used without normalization.
    Only dot(normal, velocity)>0 responds. Tangential velocity scales by
    1-friction (simulation half248), while the normal part reverses and scales
    by restitution (half250). The surrounding guide cr>0/static-flag branch and
    contact flag clearing belong to the caller, not this projection.
    """
    v, n = _point(velocity), _point(normal)
    _finite(friction, restitution)
    inward = sum(a * b for a, b in zip(v, n))
    _finite(inward)
    if inward <= 0:
        return v
    return _point(tuple((x - inward * axis) * (1. - friction) - axis * inward * restitution
                        for x, axis in zip(v, n)))


def predict_cloth_position(
    position: Sequence[float], velocity: Sequence[float], *, delta_time: float,
    gravity_direction: Sequence[float], ground_height: float, ground_thickness: float,
    ground_collision_enabled: bool,
) -> dict:
    """Dynamic prediction and the decoded gravity-direction ground plane.

    Position integration must already be eligible. Supply velocity after any
    special backward boost, which is not necessarily the velocity stored by the
    shader. The plane uses frame float24 groundHeight plus parameter float208
    groundCollisionThickness when frame0x1000000 enables it; otherwise its scalar
    limit is still1000. It projects along the supplied gravity direction without
    normalizing it. Reported contact corresponds to setting particle flag0x2.
    """
    p, v, direction = _point(position), _point(velocity), _point(gravity_direction)
    _finite(delta_time, ground_height, ground_thickness)
    _boolean(ground_collision_enabled)
    if delta_time < 0:
        raise ValueError("Cloth prediction delta time must be nonnegative.")
    predicted = _point(tuple(x + speed * delta_time for x, speed in zip(p, v)))
    limit = -(ground_height + ground_thickness) if ground_collision_enabled else 1000.
    distance = limit - sum(x * n for x, n in zip(predicted, direction))
    _finite(distance)
    contact = distance < 0
    if contact:
        predicted = _point(tuple(x + distance * n for x, n in zip(predicted, direction)))
    return {"position": predicted, "ground_contact": contact}
