"""Wind/water sample reference decoded from UpdateJiggleBoneSample (1.0.0.2944).

Consumes caller-supplied 96-byte sample and 224-byte JiggleBoneEffectGlobalData
records. It does not discover live weather, initialize sample directions, or
decide which models consume these matrices. See the modding README for evidence.
"""

from __future__ import annotations

import math
import struct

from .pac_jiggle_bones import (
    _angular_motion, _bits, _f32, _finite, _linear_motion, _random, _record,
    _rotation, _TAU, _transform,
)


def step_jiggle_sample(previous_sample: bytes, *, global_data: bytes, sample_index: int) -> dict:
    """Advance one of the shader's 512 samples and emit its skinning matrix.

    global_data is the 224-byte struct at constant-buffer offset 48, not the
    entire 340-byte constant buffer. Its second uint selects the wind/water
    boundary (the inspected CPU upload writes 256). Nonzero isCPUMode bypasses
    integration and emits the existing state; it does not reset the sample.

    The result contains `sample` (96 packed bytes), `matrix` (four row-major
    rows), and `matrix_index` (1024 + sample_index). Only cycle 0 advances.
    The shader integrates AGAIN after its clamped spring step, including the
    old spring velocity. External force is not followed by another clamp.

    Arithmetic follows the existing Python bone reference, with float32 at
    storage/seed/cycle boundaries. This is not bit-exact GPU emulation. Callers
    supply dt, environment and both settings blocks without invented defaults.
    """
    _record(previous_sample, 96)
    _record(global_data, 224)
    if type(sample_index) is not int or not 0 <= sample_index < 512:
        raise ValueError("Jiggle sample index must be in the shader's 0..511 range.")
    source = bytes(previous_sample)
    position, velocity, rotation, angular_velocity = (
        struct.unpack_from('<3f', source, offset) for offset in (48, 60, 72, 84))
    _finite(*position, *rotation)
    cpu_mode = struct.unpack_from('<I', global_data, 140)[0] != 0
    result = bytearray(source)
    if not cpu_mode:
        wind = sample_index < struct.unpack_from('<I', global_data, 4)[0]
        dt = struct.unpack_from('<f', global_data, 84)[0]
        elapsed, duration = struct.unpack_from('<2f', source, 32)
        settings = struct.unpack_from('<8f', global_data, 160 if wind else 192)
        _finite(dt, elapsed, duration, *velocity, *angular_velocity, *settings)
        if dt < 0 or any(settings[i] < 0 for i in (2, 3, 6, 7)):
            raise ValueError("Jiggle sample time and speed/displacement limits must be nonnegative.")
        frame = struct.unpack_from('<I', global_data, 136)[0]
        velocity_bits = _bits(_f32(_f32(_f32(velocity[0] * 999999995904.) * velocity[1]) * velocity[2]))
        seed = (sample_index * sample_index * (sample_index & 63) * frame + velocity_bits) & 0xFFFFFFFF
        elapsed = _f32(elapsed + dt)
        cycle_linear = struct.unpack_from('<3f', source, 0)
        cycle_angular = struct.unpack_from('<3f', source, 16)
        if elapsed >= duration:
            cycle = struct.unpack_from('<f', global_data, 76 if wind else 104)[0]
            perturb = struct.unpack_from('<f', global_data, 60 if wind else 132)[0]
            _finite(cycle, perturb)
            integer, seed = _random(seed)
            random_value = _f32(integer * 3.051944077014923e-05)
            duration = max(.0333000011742115, _f32(cycle * _f32(1. + _f32(random_value * perturb))))
            elapsed = 0.
            if not wind:
                rates = struct.unpack_from('<4f', global_data, 112)
                _finite(*rates, *cycle_linear)
                angles = []
                for rate in rates:
                    integer, seed = _random(seed)
                    angles.append((_f32(integer * 6.103888154029846e-05) - 1.) * rate)
                # First linear perturbation is Y/yaw, second X/pitch. The
                # previous cycle direction rotates; the global waterDir is not
                # substituted here and a zero supplied direction stays zero.
                cycle_linear = _transform(cycle_linear, _rotation((angles[1], angles[0], 0.)))
                cycle_angular = (angles[2], angles[3], 0.)
                struct.pack_into('<3f', result, 0, *map(_f32, cycle_linear))
                struct.pack_into('<4f', result, 16, *map(_f32, cycle_angular), 0.)
        phase = math.sin(elapsed / duration * _TAU)
        position, velocity, seed = _linear_motion(
            position, velocity, (0., 0., 0.), settings, 1., dt, seed)
        rotation, angular_velocity = _angular_motion(
            rotation, angular_velocity, (0., 0., 0.), settings, dt, seed)
        if wind:
            direction = struct.unpack_from('<3f', global_data, 16)
            rotational = struct.unpack_from('<3f', global_data, 32)
            acc, damping = struct.unpack_from('<2f', global_data, 48)
            bias, perturb, speed = struct.unpack_from('<3f', global_data, 64)
            _finite(*direction, *rotational, acc, damping, bias, perturb, speed)
            force = (speed * dt * (bias + perturb * phase)) * (damping * acc)
            angular_force = (1. if phase > 0 else -1.) * dt * damping
        else:
            direction, rotational = cycle_linear, cycle_angular
            speed = struct.unpack_from('<f', global_data, 108)[0]
            perturb = struct.unpack_from('<f', global_data, 128)[0]
            _finite(*direction, *rotational, speed, perturb)
            force = angular_force = speed * dt * (1. + perturb * phase)
        velocity = tuple(v + force * d for v, d in zip(velocity, direction))
        angular_velocity = tuple(v + angular_force * d for v, d in zip(angular_velocity, rotational))
        position = tuple(p + dt * v for p, v in zip(position, velocity))
        rotation = tuple(r + dt * v for r, v in zip(rotation, angular_velocity))
        struct.pack_into('<2f', result, 32, elapsed, duration)
        for offset, values in ((48, position), (60, velocity), (72, rotation), (84, angular_velocity)):
            struct.pack_into('<3f', result, offset, *map(_f32, values))
    basis = _rotation(rotation)
    matrix = tuple((*row, 0.) for row in basis) + ((*position, 1.),)
    for row in matrix:
        _finite(*row)
    return {'sample': bytes(result), 'matrix': matrix, 'matrix_index': 1024 + sample_index}
