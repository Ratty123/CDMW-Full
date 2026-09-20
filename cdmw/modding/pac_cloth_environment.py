"""Decoded water queries/classification and force construction from scene samples.

Texture acquisition, procedural noise and runtime activation remain caller-owned.
The force reference produces the resolved environmental acceleration expected by
pac_cloth_base.integrate_cloth_forces; the query helpers do not sample textures.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence

from ._pbd_numeric import f32
from .pac_cloth_base import _boolean, _finite, _point, _record


_EPSILON = 9.999999974752427e-7


def _unit_or_zero(vector):
    length = math.hypot(*vector)
    _finite(length)
    return tuple(x / length for x in vector) if length else tuple(vector)


def _sample_vector(value, name, count=3):
    if value is None or len(value) != count:
        raise ValueError(f"Active cloth environment branch requires a {count}-component {name} sample.")
    _finite(*value)
    return tuple(float(x) for x in value)


def plan_cloth_water_samples(
    position_relative_to_previous_view: Sequence[float], water_constants: bytes,
) -> dict:
    """Select water-top texture and UVs for the base shader's water query.

    water_constants is the complete 768-byte WaterConstantBuffer. The returned
    common UV serves bottom water and both air-pocket samples, and coarse top
    when detail is unselected. Water uses bilinear clamp, air pockets bilinear
    black-border, all at LOD0. UVs are not clamped here or sampled implicitly.
    """
    _record(water_constants, 768)
    x, _, z = (f32(v) for v in _point(position_relative_to_previous_view))
    sx, sz = struct.unpack_from('<2f', water_constants, 8)
    dx = struct.unpack_from('<f', water_constants, 416)[0]
    dz = struct.unpack_from('<f', water_constants, 424)[0]
    _finite(sx, sz, dx, dz)
    common_uv = (f32(f32(x*sx) + .5), f32(.5 - f32(z*sz)))
    detail = abs(x) < f32(dx*.5) and abs(z) < f32(dz*.5)
    top_uv = common_uv
    if detail:
        detail_z_scale = struct.unpack_from('<f', water_constants, 428)[0]
        # The inspected shader uses component z for both the Z bound and X scale.
        top_uv = (f32(f32(x*dz) + .5), f32(.5 - f32(z*detail_z_scale)))
    return {'common_uv': common_uv, 'top_uv': top_uv, 'use_detail_top': detail}


def classify_cloth_water(
    position_relative_to_previous_view: Sequence[float], water_constants: bytes, *,
    current_view_y: float, depth_samples: Sequence[float],
) -> bool:
    """Classify supplied top/bottom/air-top/air-bottom texture samples in that order.

    Top must be the detail/coarse source selected by plan_cloth_water_samples.
    This returns volume membership, before the caller's flags2 0x1000 gate. A
    sample >=1 produces height -10000; smaller samples are not clamped. The
    water top is exclusive, bottom inclusive; the complete air interval is dry.
    """
    _record(water_constants, 768)
    position = _point(position_relative_to_previous_view)
    view_y = f32(current_view_y)
    samples = tuple(f32(v) for v in _sample_vector(depth_samples, 'water-depth', 4))
    minimum, maximum, bias = struct.unpack_from('<3f', water_constants, 32)
    extent = f32(maximum - minimum)
    origin = f32(f32(bias + view_y) - minimum)
    heights = tuple(f32(origin - f32(sample*extent)) if sample < 1 else -10000.
                    for sample in samples)
    y = f32(f32(position[1]) + view_y)
    top, bottom, air_top, air_bottom = heights
    return y < top and y >= bottom and (y > air_top or y < air_bottom)


def cloth_environment_acceleration(
    particle: bytes, *, simulation_parameter: bytes, per_frame: bytes, per_scene: bytes,
    particle_extra: bytes | None, working_position: Sequence[float],
    velocity_after_inertia: Sequence[float], particle_positions: Sequence[Sequence[float]],
    underwater: bool, head_underwater: bool, sampled_voxel_wind: Sequence[float] | None,
    sky_visibility: float | None, sampled_shallow_water_velocity: Sequence[float] | None,
    turbulence_sample: float | None, apply_sky_visibility_to_voxel_wind: bool,
    acceleration_limit: float,
) -> tuple[float, ...]:
    """Build drag/wind, then apply the common cap, orientation and wave response.

    velocity_after_inertia includes this step's gravity and bone inertia. The
    particle's p[1] at24 and particle_positions (also p[1]) supply orientation;
    working_position is the separately adjusted x used for wind masking/waves.
    Runtime force eligibility must already be established by the caller.

    Scene samples are explicit: voxel wind is the unscaled texture XYZ; sky
    visibility is the decoded 1-occlusion value; shallow water is its texture XY.
    head_underwater is the water classification at the head offset. A supplied
    turbulence_sample is the scalar procedural-noise result BEFORE branch scale
    and clamping. Missing active inputs are rejected, not replaced by calm water
    or zero wind. Global sky-on-voxel selection means the shader's value ==1.

    Water uses current velocity, bone velocity, half the scene water velocity,
    optional shallow-water flow, then turbulence. Air can include current
    velocity via frame0x40000000. Wind enable (flags2 flag0x8) does not disable air
    resistance. The common postprocess also applies to water drag.

    Singular dry-turbulence normalization and purely vertical nonzero forces
    make the inspected shader math non-finite. They are reported unsupported;
    this mathematical reference does not invent a fallback or emulate recovery.
    GPU arithmetic/texture sampling equivalence is not claimed.
    """
    for record, size in ((particle, 152), (simulation_parameter, 312), (per_frame, 100), (per_scene, 108)):
        _record(record, size)
    if particle_extra is not None:
        _record(particle_extra, 28)
    for value in (underwater, head_underwater, apply_sky_visibility_to_voxel_wind):
        _boolean(value)
    working, velocity = _point(working_position), _point(velocity_after_inertia)
    count = struct.unpack_from('<H', simulation_parameter, 236)[0]
    if len(particle_positions) != count:
        raise ValueError("Environment orientation requires the declared particle-position count.")
    positions = tuple(_point(p) for p in particle_positions)
    flags, flags2 = struct.unpack_from('<2I', per_frame, 32)
    guide_mode = struct.unpack_from('<H', simulation_parameter, 216)[0] == 0xFFFF
    inverse_mass = struct.unpack_from('<f', particle, 60)[0]
    bone_velocity = _point(struct.unpack_from('<3e', per_frame, 56))
    extra_flags = 0 if particle_extra is None else struct.unpack_from('<H', particle_extra, 0)[0]
    _finite(inverse_mass, acceleration_limit)
    if inverse_mass < 0 or acceleration_limit <= 0:
        raise ValueError("Environment requires nonnegative inverse mass and a positive acceleration cap.")
    if flags2 & 0x4000:
        if turbulence_sample is None:
            raise ValueError("Active cloth turbulence requires its procedural-noise sample.")
        _finite(turbulence_sample)

    if underwater:
        water_velocity = _point(struct.unpack_from('<3f', per_scene, 28))
        turbulence_scale, viscosity, drag, shallow_scale = struct.unpack_from('<4e', simulation_parameter, 288)
        _finite(turbulence_scale, viscosity, drag, shallow_scale)
        water = tuple(.5 * x for x in water_velocity)
        if not head_underwater and shallow_scale > 0:
            shallow = _sample_vector(sampled_shallow_water_velocity, "shallow-water", 2)
            water = (water[0] + shallow_scale * shallow[0], water[1], water[2] + shallow_scale * shallow[1])
        relative = _point(tuple(b + v - w for b, v, w in zip(bone_velocity, velocity, water)))
        squared = sum(x * x for x in relative)
        _finite(squared)
        if squared < .10000000149011612:
            relative = (0., 0., 0.)
        if flags2 & 0x4000:
            noise = .5 * turbulence_scale * turbulence_sample
            relative = _point(tuple(x + noise for x in relative))
        speed = math.hypot(*relative)
        _finite(speed)
        limited = min(2. if flags & 0x20000000 else 10000., speed)
        quadratic_scale = drag * limited * (limited / speed) if speed > _EPSILON else 0.
        raw = _point(tuple((-quadratic_scale * x - viscosity * x) * inverse_mass for x in relative))
    else:
        relative = tuple(-b - (v if flags & 0x40000000 else 0.) for b, v in zip(bone_velocity, velocity))
        if flags2 & 0x4000:
            perturbation = min(5., math.hypot(*bone_velocity)) * 3. * turbulence_sample
            size = math.sqrt(3. * perturbation * perturbation)
            _finite(size)
            if size == 0:
                raise ValueError("Dry turbulence has no supported finite result at zero perturbation.")
            perturbation *= min(10., size) / size
            ground_height = struct.unpack_from('<f', per_frame, 24)[0]
            _finite(ground_height)
            relative = (relative[0] - perturbation,
                        relative[1] - (0. if ground_height < -500. else perturbation),
                        relative[2] - perturbation)
        relative = _point(relative)
        resistance = struct.unpack_from('<e', simulation_parameter, 280)[0]
        _finite(resistance)
        speed = math.hypot(*relative)
        _finite(speed)
        wind = (0., 0., 0.)
        if flags2 & 8:
            voxel = _sample_vector(sampled_voxel_wind, "voxel-wind")
            if sky_visibility is None:
                raise ValueError("Active cloth wind requires its sky-visibility sample.")
            _finite(sky_visibility)
            visibility = min(1., max(0., sky_visibility))
            response = struct.unpack_from('<e', simulation_parameter, 268)[0]
            wind_scale = 1. if particle_extra is None else struct.unpack_from('<e', particle_extra, 20)[0]
            frame_wind = _point(struct.unpack_from('<3e', per_frame, 48))
            _finite(response, wind_scale)
            voxel = _point(tuple(x * response for x in voxel))
            voxel_speed = math.hypot(*voxel)
            _finite(voxel_speed)
            sky_scale = visibility if apply_sky_visibility_to_voxel_wind else 1.
            frame_scale = 1.
            if guide_mode:
                frame_scale = 0. if visibility < .10000000149011612 else visibility
                if visibility >= .800000011920929:
                    frame_scale += 1. - visibility
            wind = _point(tuple(wind_scale * (sky_scale * voxel_speed * x + frame_scale * f) * inverse_mass
                                for x, f in zip(voxel, frame_wind)))
            if flags2 & 0x10:
                if guide_mode:
                    head = _point(struct.unpack_from('<3f', per_scene, 16))
                    offset = _point(struct.unpack_from('<3f', per_frame, 0))
                    radius = math.dist(head, offset)
                else:
                    radius = 5.
                distance = math.hypot(working[0], working[2])
                _finite(radius, distance)
                if distance < radius * .6000000238418579:
                    radial = (working[0] / max(distance, _EPSILON), 0., working[2] / max(distance, _EPSILON))
                    amount = min(1., max(0., (radius * .6000000238418579 - distance)
                                       / max(radius * .40000003576278687, _EPSILON)))
                    amount = amount * amount * (3. - 2. * amount)
                    inward = min(0., sum(a * b for a, b in zip(wind, radial)))
                    wind = _point(tuple((x - amount * inward * n) * (1. - .6000000238418579 * amount)
                                        for x, n in zip(wind, radial)))
        raw = _point(tuple(w + resistance * inverse_mass * speed * r for w, r in zip(wind, relative)))

    magnitude = math.hypot(*raw)
    _finite(magnitude)
    if magnitude <= _EPSILON:
        return (0., 0., 0.)
    direction = tuple(x / magnitude for x in raw)
    capped = tuple(x / max(1., magnitude / acceleration_limit) for x in raw)
    first, second = struct.unpack_from('<2H', particle, 112)
    original = _point(struct.unpack_from('<3f', particle, 24))
    factor = 1.
    if flags & 0x80000 and not extra_flags & 4 and first < count:
        edge = _unit_or_zero(tuple(x - a for x, a in zip(positions[first], original)))
        factor = 1. - abs(sum(x * y for x, y in zip(edge, direction)))
    elif first < count and second < count:
        a = tuple(x - p for x, p in zip(positions[first], original))
        b = tuple(x - p for x, p in zip(positions[second], original))
        normal = _unit_or_zero((a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2], a[0]*b[1] - a[1]*b[0]))
        factor = abs(sum(x * y for x, y in zip(normal, direction)))
    horizontal_length = math.hypot(direction[0], direction[2])
    if horizontal_length == 0:
        raise ValueError("Vertical environment force has no supported finite horizontal-wave direction.")
    side = (-direction[2] / horizontal_length, 0., direction[0] / horizontal_length)
    phase = struct.unpack_from('<e', per_frame, 64)[0]
    amplitude = struct.unpack_from('<e', simulation_parameter, 284)[0]
    _finite(phase, amplitude)
    phase += sum(x * y for x, y in zip(working, side))
    wave_angle = phase * 6.283180236816406
    _finite(wave_angle)
    wave = .5 * (math.cos(wave_angle) + 1.)
    modulation = 1. + min(1., max(0., amplitude)) * (wave - 1.)
    return _point(tuple(x * factor * modulation for x in capped))
