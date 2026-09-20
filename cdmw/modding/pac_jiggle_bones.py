"""Bone jiggle reference from UpdateJiggleEffect in game build 1.0.0.2944.

This is the per-bone path after dispatch eligibility and LOD mapping, including
timed instance effects. It requires supplied animation/runtime records. It does
not resolve rig bindings, simulate wind/water samples, or claim GPU arithmetic
or rendered parity. PAC byte 38 is a later render blend, not a spring parameter.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence


_PI = 3.1415927410125732
_TAU = 6.2831854820251465
_UINT_MAX = 0xFFFFFFFF


def _finite(*values):
    if any(not math.isfinite(x) for x in values):
        raise ValueError("Bone jiggle inputs and results must be finite.")


def _record(value, size):
    if len(value) != size:
        raise ValueError(f"Bone jiggle requires a complete {size}-byte runtime record.")


def _uint(value):
    if type(value) is not int or not 0 <= value <= _UINT_MAX:
        raise ValueError("Bone jiggle indices and flags must be unsigned 32-bit integers.")


def _point(value):
    if len(value) != 3:
        raise ValueError("Bone jiggle vectors must have three components.")
    _finite(*value)
    return tuple(float(x) for x in value)


def _f32(value):
    try:
        result = struct.unpack('<f', struct.pack('<f', value))[0]
    except OverflowError as exc:
        raise ValueError("Bone jiggle value exceeds finite float32 range.") from exc
    _finite(result)
    return result


def _bits(value):
    return struct.unpack('<I', struct.pack('<f', _f32(value)))[0]


def _random(seed):
    # The GPU feeds float bits back into its seed. This is not the CPU RNG.
    first = (seed * 214013 + 2531011) & _UINT_MAX
    second = (first * 214013 + 2531011) & _UINT_MAX
    integer = ((second & 0xFFFF0000) | (first >> 16)) % 32767
    sample = _f32(integer * 3.051944077014923e-05)
    return integer, ((second >> 1) + (_bits(sample) >> 1)) & _UINT_MAX


def _wrap(angle):
    # Round_z is truncation. Keep both +/- pi endpoints and the shader's two
    # reduction stages; Python modulo chooses a different endpoint at +pi.
    if -_PI <= angle <= _PI:
        return angle
    if angle >= _TAU or angle <= -_TAU:
        angle -= math.trunc(_f32(angle * 0.15915493667125702)) * _TAU
    return angle - math.trunc(_f32(angle * 0.31830987334251404)) * _TAU


def _angle_difference(a, b):
    difference = _wrap(a) - _wrap(b)
    if difference > _PI:
        difference -= _TAU
    elif difference < -_PI:
        difference += _TAU
    return difference


def _atan2(y, x):
    if x == 0:
        return _PI / 2 if y >= 0 else -_PI / 2
    angle = math.atan(y / x)
    return angle + (_PI if y >= 0 else -_PI) if x < 0 else angle


def _angles(rows, scales):
    x = math.asin(-max(-1., min(1., rows[2][1] / scales[2])))
    if math.cos(x) > 9.999999747378752e-05:
        y = _atan2(rows[2][0] / scales[2], rows[2][2] / scales[2])
        z = _atan2(rows[0][1] / scales[0], rows[1][1] / scales[1])
    else:
        y = 0.
        z = _atan2(-rows[1][0] / scales[1], rows[0][0] / scales[0])
    return x, y, z


def _rotation(angles):
    x, y, z = angles
    sx, sy, sz = math.sin(x), math.sin(y), math.sin(z)
    cx, cy, cz = math.cos(x), math.cos(y), math.cos(z)
    return ((cz * cy + sz * sx * sy, sz * cx, sz * sx * cy - cz * sy),
            (cz * sx * sy - sz * cy, cz * cx, cz * sx * cy + sz * sy),
            (cx * sy, -sx, cx * cy))


def _transform(vector, basis):
    return tuple(sum(vector[i] * basis[i][j] for i in range(3)) for j in range(3))


def _limit_length(vector, limit):
    length = math.hypot(*vector)
    _finite(length)
    return tuple(x * limit / length for x in vector) if length > limit else vector


def _spring_multiplier(seed):
    integer, seed = _random(seed)
    return _f32(_f32(integer * 1.5259720385074615e-05) + .5), seed


def _linear_motion(position, velocity, target, settings, size_scale, dt, seed):
    acc, damping, speed, difference = settings[:4]
    multiplier, seed = _spring_multiplier(seed)
    acceleration = acc * dt * multiplier
    velocity = _limit_length(tuple((v + acceleration * (t - p)) * damping
                                   for v, t, p in zip(velocity, target, position)), speed * size_scale)
    predicted = tuple(p + v * dt for p, v in zip(position, velocity))
    offset = tuple(p - t for p, t in zip(predicted, target))
    if math.hypot(*offset) > difference * size_scale:
        offset = _limit_length(offset, difference * size_scale)
        position = tuple(t + d for t, d in zip(target, offset))
    else:
        position = predicted
    # Clamping position does not recompute or remove stored velocity.
    return position, velocity, seed


def _angular_motion(rotation, velocity, target, settings, dt, seed):
    acc, damping, speed, difference = settings[4:]
    multiplier, _ = _spring_multiplier(seed)
    acceleration = acc * dt * multiplier
    velocity = tuple(max(-speed, min(speed, (v + acceleration * _angle_difference(t, r)) * damping))
                     for v, t, r in zip(velocity, target, rotation))
    predicted = tuple(r + v * dt for r, v in zip(rotation, velocity))
    rotation = tuple(t + max(-difference, min(difference, _angle_difference(r, t)))
                     for r, t in zip(predicted, target))
    return rotation, velocity


def _perturb_angles(rotation, size_scale, seed):
    signs, magnitudes = [], []
    for _ in range(3):
        integer, seed = _random(seed)
        signs.append(-1. if _f32(integer * 3.051944077014923e-05) < .5 else 1.)
    for _ in range(3):
        integer, seed = _random(seed)
        magnitudes.append(integer)
    amplitude = 9.58796499617165e-06 - (size_scale - 1.) * 1.725833726595738e-06
    return tuple(_wrap(r + sign * amplitude * magnitude)
                 for r, sign, magnitude in zip(rotation, signs, magnitudes)), seed


def _unit(vector):
    length = math.hypot(*vector)
    _finite(length)
    if length == 0:
        raise ValueError("Bone jiggle axis normalization is undefined for a zero vector.")
    return tuple(x / length for x in vector)


def _axis_instance(rotation_velocity, axis, angle, target, settings, dt, seed, restore_damping):
    acc, damping, speed, difference = settings[4:]
    multiplier, seed = _spring_multiplier(seed)
    scalar_velocity = (rotation_velocity[0] + _angle_difference(0., angle) * dt * acc * multiplier) * damping
    scalar_velocity = max(-speed, min(speed, scalar_velocity))
    angle = max(-difference, min(difference, _angle_difference(angle + scalar_velocity * dt, 0.)))
    random_direction = []
    for _ in range(3):
        integer, seed = _random(seed)
        random_direction.append(1. - integer * 6.103888154029846e-05)
    perturbation = _unit(random_direction)
    perturbed = tuple(a + .10000000149011612 * p for a, p in zip(axis, perturbation))
    # This interpolation is deliberately not saturated: large dt can overshoot.
    axis = _unit(tuple(a + (target_axis - a) * (3. * dt)
                       for a, target_axis in zip(perturbed, (1., 0., 0.))))
    quaternion_axis = _unit(axis) if math.hypot(*axis) > 9.999999747378752e-06 else axis
    x, y, z = (a * math.sin(angle * .5) for a in quaternion_axis)
    w = math.cos(angle * .5)
    correction = ((1 - 2 * (y*y + z*z), 2 * (x*y + w*z), 2 * (x*z - w*y)),
                  (2 * (x*y - w*z), 1 - 2 * (x*x + z*z), 2 * (y*z + w*x)),
                  (2 * (x*z + w*y), 2 * (y*z - w*x), 1 - 2 * (x*x + y*y)))
    # The correction PRE-multiplies the animated rotation in row convention.
    target_basis = _rotation(target)
    combined = tuple(_transform(row, target_basis) for row in correction)
    rotation = _angles(combined, (1., 1., 1.))
    if restore_damping:
        if damping == 0:
            raise ValueError("Bone jiggle pre-fade angular damping division is undefined at zero.")
        scalar_velocity /= damping
    return rotation, (scalar_velocity, *rotation_velocity[1:]), axis, angle


def _step_instance(previous, selected, motion, target, settings, size_scale, dt, seed):
    position, velocity, rotation, angular_velocity = motion
    target_position, target_rotation = target
    impulse = struct.unpack_from('<3f', selected, 48)
    angular_impulse = struct.unpack_from('<3f', selected, 60)
    weight, duration, fade_range = struct.unpack_from('<3f', selected, 72)
    mode = struct.unpack_from('<I', selected, 84)[0]
    axis = struct.unpack_from('<3f', previous, 88)
    angle, elapsed = struct.unpack_from('<2f', previous, 100)
    flags = struct.unpack_from('<I', selected, 108)[0]
    _finite(*impulse, *angular_impulse, weight, duration, fade_range, *axis, angle, elapsed)
    if flags & 2:
        elapsed = 0.
        velocity = tuple(v + kick for v, kick in zip(velocity, impulse)) if mode & 4 else (0., 0., 0.)
        if not mode & 8:
            angle = 0.
            angular_velocity = (0., 0., 0.)
        elif mode & 2:
            speed = math.hypot(*(v + kick for v, kick in zip(angular_velocity, angular_impulse)))
            angular_velocity = (speed, speed, speed)
            axis, angle = (1., 0., 0.), 0.
        else:
            if math.hypot(*angular_impulse) > 0:
                rotation, seed = _perturb_angles(rotation, size_scale, seed)
            angular_velocity = tuple(v + kick for v, kick in zip(angular_velocity, angular_impulse))
    elapsed += dt
    fade = max(0., min(1., (fade_range - duration + elapsed) / fade_range)) if fade_range > 0 else 0.
    before_fade = fade < 9.999999747378752e-05
    result_weight = weight - fade * weight
    passthrough = result_weight < 9.999999747378752e-05
    if mode & 4:
        position, velocity, seed = _linear_motion(position, velocity, target_position, settings, size_scale, dt, seed)
        if before_fade and not passthrough:
            if settings[1] == 0:
                raise ValueError("Bone jiggle pre-fade linear damping division is undefined at zero.")
            velocity = tuple(v / settings[1] for v in velocity)
    else:
        position = target_position
    if mode & 8:
        if mode & 2:
            rotation, angular_velocity, axis, angle = _axis_instance(
                angular_velocity, axis, angle, target_rotation, settings, dt, seed,
                before_fade and not passthrough)
        else:
            spring_target = target_rotation
            if before_fade:
                spring_target, seed = _perturb_angles(spring_target, size_scale, seed)
            rotation, angular_velocity = _angular_motion(rotation, angular_velocity, spring_target, settings, dt, seed)
    else:
        rotation = target_rotation
    if passthrough:
        position, rotation = target_position, target_rotation
        velocity = angular_velocity = (0., 0., 0.)
    flags &= 0xFFFFFFFC if duration <= elapsed else 0xFFFFFFFD
    return {'motion': (position, velocity, rotation, angular_velocity), 'axis': axis,
            'angle': angle, 'elapsed': elapsed, 'flags': flags, 'weight': result_weight,
            'passthrough': passthrough}


def prepare_jiggle_command(
    command: bytes, *, skeleton_data: bytes, object_data: bytes, shader_data: bytes | None,
) -> dict | None:
    """Resolve one command's state address and payload after resource lookup.

    The caller must supply the skeleton/object selected through the packed
    resource reference at command byte40 and skeleton byte80. Missing jiggle
    data (object byte84==FFFFFFFF) or low-byte LOD >1 skips the command. Eligible
    commands add current state offset + original bone index + LOD0 animation
    offset with uint32 wrap; they do NOT use a LOD1 animation offset.

    Returns `state_index` and a fresh 116-byte `bone` with command data at48 and
    flags3. No existing motion/timer is copied into this CURRENT command record.
    ClearJiggleBone's complete cleared record is simply bytes(116). Concurrent
    commands targeting the same state have no established deterministic winner.
    """
    for record, size in ((command, 48), (skeleton_data, 124), (object_data, 128)):
        _record(record, size)
    lods = struct.unpack_from('<I', object_data, 0)[0]
    shader_offset = struct.unpack_from('<I', object_data, 84)[0]
    if lods & 0xFE or shader_offset == _UINT_MAX:
        return None
    if shader_data is None:
        raise ValueError("Eligible bone jiggle commands require resolved shader data.")
    _record(shader_data, 264)
    index = (struct.unpack_from('<I', shader_data, 12)[0]
             + struct.unpack_from('<I', command, 44)[0]
             + struct.unpack_from('<I', skeleton_data, 32)[0]) & _UINT_MAX
    result = bytearray(116)
    result[48:88] = command[:40]
    struct.pack_into('<I', result, 108, 3)
    return {'state_index': index, 'bone': bytes(result)}


def jiggle_bone_blend_override(
    shader_data: bytes, original_bone_index: int, instance_weight: float,
) -> tuple[float, float]:
    """Return output matrix row0.w marker and row1.w blend override.

    Low flag bits !=0 set the marker. Mode 2 visits every packed u16 mask entry,
    so the LAST duplicate wins. An unmatched bone retains instance_weight, which
    is zero on the ordinary path. Neither mask nor instance weight is clamped.
    A marker of zero leaves the later vertex-derived blend in control.
    """
    _record(shader_data, 264)
    _uint(original_bone_index)
    _finite(instance_weight)
    flags, count = struct.unpack_from('<2I', shader_data, 64)
    mode = flags & 3
    result = float(instance_weight)
    if mode == 2:
        if count > 32:
            raise ValueError("Bone jiggle mask count exceeds its 32-entry runtime record.")
        for index in range(count):
            if struct.unpack_from('<H', shader_data, 72 + 2 * index)[0] == original_bone_index:
                result = struct.unpack_from('<f', shader_data, 136 + 4 * index)[0]
        _finite(result)
    return float(mode != 0), result


def step_jiggle_bone(
    previous_bone: bytes | None, *, command_bone: bytes, shader_data: bytes,
    animation_matrix: bytes, character_transform: bytes,
    view_position: Sequence[float], previous_view_position: Sequence[float],
    bone_scale: float, original_bone_index: int, update_frame_index: int,
    delta_time: float, reset_requested: bool,
) -> dict:
    """Advance one eligible bone, including a pending or continuing instance effect.

    Record sizes: previous/command JiggleBone 116, SkinnedMeshJiggleShaderData
    264, selected animation matrix 64, CharacterTransformData 272 bytes.
    previous_bone=None represents an absent previous-state buffer. command_bone
    is the CURRENT state after commands, not a replacement for previous_bone.
    Current flags&3==3 select a pending effect; otherwise previous flags apply.
    Effects apply even when a motion reset is required. Mode mask 0x4 enables
    linear motion, 0x8 angular motion, and 0x2 selects the axis-angle variant.

    reset_requested is object render-flags mask 0x2. Frame discontinuity and origin
    speed >70 also reset, with the inverse-dt guard at float32(1e-5). Origins
    include their respective view positions. The supplied world/inverse-world
    bases are used directly; inverse translation and platform rotation are not.

    The result has a packed `bone`, four row-major `matrix` rows, and `reset`.
    Packed state permits subsequent steps with the shader's float32 seed input.
    Other math uses Python floats and is not bit-exact GPU emulation. Speed and
    displacement limits must be nonnegative. Damping is per update, not per
    second; there is no invented fixed timestep or stiffness normalization.
    Before fading starts, linear and axis-angle effects divide their stored
    velocity by damping AFTER integration/capping. A consumed division by zero
    or zero-axis normalization is rejected instead of inventing a fallback.
    """
    for record, size in ((command_bone, 116), (shader_data, 264),
                         (animation_matrix, 64), (character_transform, 272)):
        _record(record, size)
    if previous_bone is not None:
        _record(previous_bone, 116)
    if type(reset_requested) is not bool:
        raise ValueError("Bone jiggle reset requires an explicit boolean.")
    for value in (original_bone_index, update_frame_index):
        _uint(value)
    _finite(bone_scale, delta_time)
    if delta_time < 0:
        raise ValueError("Bone jiggle delta time must be nonnegative.")
    delta_time = _f32(delta_time)
    view, old_view = _point(view_position), _point(previous_view_position)
    previous = bytes(116) if previous_bone is None else previous_bone
    previous_flags, previous_frame = struct.unpack_from('<2I', previous, 108)
    command_flags = struct.unpack_from('<I', command_bone, 108)[0]
    selected = command_bone if command_flags & 3 == 3 else previous
    flags = command_flags if command_flags & 3 == 3 else previous_flags
    active = bool(flags & 1)

    rows = [struct.unpack_from('<4f', animation_matrix, 16 * i) for i in range(4)]
    world = [struct.unpack_from('<3f', character_transform, 16 * i) for i in range(3)]
    inverse = [struct.unpack_from('<3f', character_transform, 192 + 16 * i) for i in range(3)]
    current_origin = struct.unpack_from('<3f', character_transform, 48)
    previous_origin = struct.unpack_from('<3f', character_transform, 112)
    platform = struct.unpack_from('<3f', shader_data, 0)
    for row in (*rows, *world, *inverse, current_origin, previous_origin, platform):
        _finite(*row)
    origin_delta = tuple((view[i] + current_origin[i]) - (old_view[i] + previous_origin[i])
                         for i in range(3))
    inverse_dt = 0. if delta_time < 9.999999747378752e-06 else 1. / delta_time
    reset = (previous_bone is None or reset_requested
             or ((previous_frame + 1) & _UINT_MAX) != update_frame_index
             or math.hypot(*origin_delta) * inverse_dt > 70.)
    movement = (0., 0., 0.) if previous_bone is None else tuple(
        (view[i] + current_origin[i] - platform[i]) - (old_view[i] + previous_origin[i])
        for i in range(3))
    animated = tuple(_transform(row[:3], world) for row in rows)
    scales = tuple(math.hypot(*row) for row in animated[:3])
    for row in animated:
        _finite(*row)
    _finite(*scales)
    if any(scale == 0 for scale in scales):
        raise ValueError("Bone jiggle cannot decompose a zero-length animation basis.")
    target_position, target_rotation = animated[3], _angles(animated, scales)

    if active or not reset:
        old_motion = tuple(
            struct.unpack_from('<3f', previous, offset) for offset in (0, 12, 24, 36))
        for vector in old_motion:
            _finite(*vector)
        # Seed uses OLD state, before origin compensation, and wraps uint sums.
        seed = (original_bone_index + update_frame_index + sum(
            _bits(_f32(_f32(vector[1] * vector[0]) * vector[2]))
            for vector in old_motion)) & _UINT_MAX
        settings = struct.unpack_from('<8f', shader_data, 32)
        _finite(*settings)
        if min(settings[i] for i in (2, 3, 6, 7)) < 0:
            raise ValueError("Bone jiggle speed and displacement limits must be nonnegative.")
        size_a = struct.unpack_from('<3f', character_transform, 128)
        size_b = struct.unpack_from('<3f', character_transform, 144)
        _finite(*size_a, *size_b)
        size_scale = max(1., min(5., bone_scale * .5555555820465088
                                * math.dist(size_a, size_b)))

    if reset:
        position = tuple(x + d for x, d in zip(target_position, movement))
        velocity = angular_velocity = (0., 0., 0.)
        rotation = target_rotation
    else:
        position, velocity, rotation, angular_velocity = old_motion
        position = tuple(x + d for x, d in zip(position, movement))

    effect = None
    if active:
        effect = _step_instance(previous, selected, (position, velocity, rotation, angular_velocity),
                                (target_position, target_rotation), settings, size_scale, delta_time, seed)
        position, velocity, rotation, angular_velocity = effect['motion']
        flags = effect['flags']
        passthrough = effect['passthrough']
    elif not reset:
        position, velocity, seed = _linear_motion(
            position, velocity, target_position, settings, size_scale, delta_time, seed)
        rotation, angular_velocity = _angular_motion(
            rotation, angular_velocity, target_rotation, settings, delta_time, seed)
        passthrough = False
    else:
        passthrough = True

    if passthrough:
        output_rows = list(rows)
    else:
        rotated = _rotation(rotation)
        output_rows = [(*_transform(tuple(x * scale for x in row), inverse), 0.)
                       for row, scale in zip(rotated, scales)]
        output_rows.append((*_transform(position, inverse), 1.))

    marker, weight = jiggle_bone_blend_override(shader_data, original_bone_index,
                                               effect['weight'] if effect is not None else 0.)
    output_rows[0] = (*output_rows[0][:3], marker)
    output_rows[1] = (*output_rows[1][:3], weight)
    for row in output_rows:
        _finite(*row)
    result = bytearray(previous)
    if effect is not None:
        result[48:88] = selected[48:88]
        struct.pack_into('<5f', result, 88,
                         *(_f32(x) for x in (*effect['axis'], effect['angle'], effect['elapsed'])))
    for offset, vector in ((0, position), (12, velocity), (24, rotation), (36, angular_velocity)):
        struct.pack_into('<3f', result, offset, *(_f32(x) for x in vector))
    struct.pack_into('<2I', result, 108, flags, update_frame_index)
    return {'bone': bytes(result), 'matrix': tuple(output_rows), 'reset': reset}
