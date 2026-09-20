"""Selected ComputePbdProcessBaseMovement state stages, build 1.0.0.2944.

These consume explicit runtime records around the existing force reference.
Guide animation adjustment, substep timing and integration selection are included;
resource resolution, static-mesh space adjustment, collision detection and full
dispatch selection remain caller-owned. Preserve the decoded stage order and variant.
The arithmetic is a mathematical reference, not bit-exact GPU execution.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence

from .pac_cloth_base import (
    _boolean, _finite, _point, _record, cloth_contact_velocity_response,
    predict_cloth_position,
)


def _f32(value):
    try:
        result = struct.unpack('<f', struct.pack('<f', value))[0]
    except (OverflowError, struct.error) as exc:
        raise ValueError("Cloth state values must fit float32 storage.") from exc
    _finite(result)
    return result


def _put(record, offset, values):
    struct.pack_into(f'<{len(values)}f', record, offset, *(_f32(v) for v in values))


def _substep_index(value):
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("Cloth substep index must be an unsigned 32-bit integer.")
    return value


def select_cloth_base_substep(
    per_frame: bytes, per_scene: bytes, global_parameters: bytes, *, substep_index: int,
) -> dict | None:
    """Resolve the base shader's clock gate, delta time and GUIDE animation blend.

    None means the clock skips this invocation, before particle access. This
    does not resolve visibility, resource validity or dispatch bounds. flags2
    0x8000 selects the scaled clock; 0x800 selects one variable step at index0.
    Scene half94 scales integration time, not animation interpolation.
    """
    for record, size in ((per_frame, 100), (per_scene, 108), (global_parameters, 1216)):
        _record(record, size)
    index = _substep_index(substep_index)
    flags, flags2 = struct.unpack_from('<2I', per_frame, 32)
    offset = 896 if flags2 & 0x8000 else 864
    fixed = struct.unpack_from('<f', global_parameters, offset)[0]
    count = struct.unpack_from('<I', global_parameters, offset + 20)[0]
    _finite(fixed)
    variable = bool(flags2 & 0x800)
    if (fixed < 0.00009999999747378752 and not (variable or flags & 0x400)
            or variable and index != 0 or index >= count):
        return None
    selected = struct.unpack_from('<f', global_parameters, offset + 4)[0] if variable else fixed
    scale = struct.unpack_from('<e', per_scene, 94)[0]
    dt = _f32(selected * scale)
    if dt < 0:
        raise ValueError("Cloth substep delta time must be nonnegative.")
    blend = 1.
    if not variable:
        interval = struct.unpack_from('<f', global_parameters, offset + 8)[0]
        previous_remaining = struct.unpack_from('<f', global_parameters, offset + 16)[0]
        duration = _f32(interval + previous_remaining)
        if duration > 0.0000009999999974752427:
            blend = max(0., min(1., _f32(_f32((index + 1) * fixed) / duration)))
    return {'delta_time': dt, 'guide_animation_blend': blend}


def _rotate_with_guide_anchor(position, previous, current):
    lengths = math.hypot(*previous), math.hypot(*current)
    if min(lengths) < 0.0000009999999974752427:
        return position
    a, b = (tuple(v / length for v in point)
            for point, length in zip((previous, current), lengths))
    cosine = sum(x * y for x, y in zip(a, b))
    if cosine < -0.9998999834060669:
        # The shader uses -I in this case, including the third axis.
        return tuple(-v for v in position)
    x, y, z = (a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2],
               a[0]*b[1] - a[1]*b[0])
    h = 1. / (1. + cosine)
    basis = ((cosine + h*x*x, h*x*y + z, h*x*z - y),
             (h*x*y - z, cosine + h*y*y, h*y*z + x),
             (h*x*z + y, h*y*z - x, cosine + h*z*z))
    return tuple(_f32(sum(position[i] * basis[i][j] for i in range(3))) for j in range(3))


def prepare_guide_cloth_animation(
    particle: bytes, simulation_parameter: bytes, per_frame: bytes, per_scene: bytes,
    guide_animation_matrix: bytes, character_transform: bytes, *, substep_index: int,
    animation_blend: float, inside_water_volume: bool, shrink_mask: int | None = None,
) -> dict:
    """Prepare original flags and guide animation before input-position collision.

    Consume the ORIGINAL particle, before prepare_cloth_fixed_state clears its
    flags. The two matrix records are already resolved to the selected guide and
    character. Only guide translation and the character's first three basis rows
    produce the anchor; subtract frame translation without adding world translation.
    inside_water_volume is an actual resolved water/air-pocket classification,
    gated here by flags2 0x1000. No water texture sampling is invented.

    Pass the selected substep's guide_animation_blend. First-step adjustment may
    rotate x or p[0] and zero velocity; p[1], velocity reference and prev_ix remain.
    Input-position collision can still alter ix/flags before integration selection.
    """
    for record, size in ((per_frame, 100), (per_scene, 108),
                         (guide_animation_matrix, 64), (character_transform, 272)):
        _record(record, size)
    prepared = prepare_cloth_fixed_state(particle, simulation_parameter, shrink_mask=shrink_mask)
    if struct.unpack_from('<H', simulation_parameter, 216)[0] != 0xFFFF:
        raise ValueError("Guide animation preparation requires a guide-mesh particle.")
    index = _substep_index(substep_index)
    _boolean(inside_water_volume)
    blend = _f32(animation_blend)
    if not 0 <= blend <= 1:
        raise ValueError("Guide animation blend must be the selected substep ratio in [0, 1].")
    flags, flags2 = struct.unpack_from('<2I', per_frame, 32)
    scene_flags = struct.unpack_from('<I', per_scene, 64)[0]
    old_flags = struct.unpack_from('<I', particle, 64)[0]
    special = False
    if flags & 0x20000000 and scene_flags & 0x200:
        lra = struct.unpack_from('<e', particle, 88)[0]
        movement = struct.unpack_from('<e', per_frame, 62)[0]
        _finite(lra, movement)
        special = lra < 0.699999988079071 and -30 < movement < -10
    skip_forces = bool(flags & 1 or special)
    skip_integration = bool(flags2 & 0x100 or special)
    if old_flags & 0x4000:
        skip_forces, skip_integration = True, False
    underwater = bool(flags2 & 0x1000 and inside_water_volume)
    if underwater:
        skip_forces = skip_integration = False

    bone = _point(struct.unpack_from('<3f', guide_animation_matrix, 48))
    basis = tuple(_point(struct.unpack_from('<3f', character_transform, offset))
                  for offset in (0, 16, 32))
    offset = _point(struct.unpack_from('<3f', per_frame, 0))
    current = tuple(_f32(_f32(sum(bone[i] * basis[i][j] for i in range(3))) - offset[j])
                    for j in range(3))
    previous = _point(struct.unpack_from('<3f', particle, 128))
    anchor = current if flags & 0x400 else tuple(
        _f32(old + blend * (new - old)) for old, new in zip(previous, current))
    result = bytearray(prepared['particle'])
    adjusted = skip_forces and index == 0
    if adjusted:
        position = _point(struct.unpack_from('<3f', particle, 36))
        _put(result, 12 if skip_integration else 36,
             _rotate_with_guide_anchor(position, previous, current))
        _put(result, 140, (0., 0., 0.))
        anchor = current
    _put(result, 0, anchor)
    return {**prepared, 'particle': bytes(result), 'underwater': underwater,
            'skip_external_forces': skip_forces, 'integration_skipped': skip_integration,
            'space_adjusted': adjusted}


def select_cloth_base_integration(particle: bytes, per_frame: bytes) -> dict:
    """Select early-return, fixed or dynamic after space/input-collision handling.

    Early-return flags0xC00 take priority and bypass ALL later stages. Fixed
    particles copy the adjusted ix to both position histories without clearing
    velocity/contact data; they still need final flags/SBC/hold processing, using
    zero non-gravity acceleration. Dynamic particles proceed to forces/prediction.
    """
    _record(particle, 152)
    _record(per_frame, 100)
    if struct.unpack_from('<I', per_frame, 32)[0] & 0xC00:
        return {'particle': bytes(particle), 'branch': 'early_return'}
    mass = struct.unpack_from('<f', particle, 60)[0]
    _finite(mass)
    fixed = mass <= 0 or struct.unpack_from('<I', particle, 64)[0] & 0x40
    result = bytearray(particle)
    if fixed:
        anchor = _point(struct.unpack_from('<3f', particle, 0))
        _put(result, 12, anchor)
        _put(result, 24, anchor)
    return {'particle': bytes(result), 'branch': 'fixed' if fixed else 'dynamic'}


def prepare_cloth_fixed_state(
    particle: bytes, simulation_parameter: bytes, *, shrink_mask: int | None = None,
) -> dict:
    """Clear per-step flags and select a fixed group/mask before space adjustment.

    A valid shrink-mask resource (parameter u16@218 != FFFF) requires its resolved
    uint sample; no resource access/default value is invented. Inverse mass <= 0 also
    bypasses dynamic integration, but does not itself set the group-fixed bit.
    """
    _record(particle, 152)
    _record(simulation_parameter, 312)
    old_flags = struct.unpack_from('<I', particle, 64)[0]
    group = struct.unpack_from('<H', particle, 116)[0]
    active = struct.unpack_from('<I', simulation_parameter, 168)[0]
    ratio = struct.unpack_from('<e', simulation_parameter, 266)[0]
    inverse_mass = struct.unpack_from('<f', particle, 60)[0]
    _finite(ratio, inverse_mass)
    static_index, shrink_index = struct.unpack_from('<2H', simulation_parameter, 216)
    flags = old_flags & (0xB777FF00 if static_index != 0xFFFF else 0xB777BF00)
    fixed = bool(1 <= group <= 31 and active & (1 << group)
                 and not (old_flags & 0x4000 and ratio < 99))
    if shrink_index != 0xFFFF:
        if type(shrink_mask) is not int or not 0 <= shrink_mask <= 0xFFFFFFFF:
            raise ValueError("Active shrink-mask storage requires its resolved uint32 sample.")
        if shrink_mask == 0:
            fixed = True
            flags |= 0x800000
    if fixed:
        flags |= 0x40
    result = bytearray(particle)
    struct.pack_into('<I', result, 64, flags)
    return {'particle': bytes(result), 'fixed_by_group_or_mask': fixed,
            'dynamic': inverse_mass > 0 and not fixed}


def predict_dynamic_cloth_state(
    particle: bytes, simulation_parameter: bytes, per_frame: bytes, per_scene: bytes,
    velocity: Sequence[float], *, delta_time: float, integration_skipped: bool,
    storage_variant: str,
) -> dict:
    """Contact response, prediction/ground projection and contact-cache writeback.

    particle must contain the already-adjusted animation/working position and
    prepared flags. velocity is AFTER forces/damping. This is the normal dynamic
    branch: fast-return frame modes, nonpositive inverse mass and fixed groups
    are rejected.
    The caller resolves integration_skipped after guide/water/space decisions.
    Prediction's optional backward boost does not change the stored velocity.
    packed clears cn[0/1].xyzw; native16 clears only xyz. Both clear cr, unless
    flags2 & 0x200 retains the cache. Later hold/flags/SBC stages are separate.
    """
    for record, size in ((particle, 152), (simulation_parameter, 312),
                         (per_frame, 100), (per_scene, 108)):
        _record(record, size)
    _boolean(integration_skipped)
    if storage_variant not in ('packed', 'native16'):
        raise ValueError("Cloth state storage variant must be packed or native16.")
    dt = _f32(delta_time)
    if dt < 0:
        raise ValueError("Cloth prediction delta time must be nonnegative.")
    frame_flags, flags2 = struct.unpack_from('<2I', per_frame, 32)
    flags = struct.unpack_from('<I', particle, 64)[0]
    inverse_mass = struct.unpack_from('<f', particle, 60)[0]
    _finite(inverse_mass)
    if frame_flags & 0xC00 or inverse_mass <= 0 or flags & 0x40:
        raise ValueError("Cloth prediction requires the normal dynamic branch.")
    v = _point(velocity)
    guide = struct.unpack_from('<H', simulation_parameter, 216)[0] == 0xFFFF
    if guide:
        cr = struct.unpack_from('<e', particle, 90)[0]
        _finite(cr)
        contact = cr > 0
    else:
        contact = bool(flags & 0x10000000)
    if contact:
        friction, restitution = struct.unpack_from('<2e', simulation_parameter, 248)
        v = cloth_contact_velocity_response(v, normal=struct.unpack_from('<3e', particle, 72),
                                            friction=friction, restitution=restitution)
        flags &= ~0x10000000
    predicted_velocity = v
    scene_flags = struct.unpack_from('<I', per_scene, 64)[0]
    bone_velocity_w = struct.unpack_from('<e', per_frame, 62)[0]
    _finite(bone_velocity_w)
    if frame_flags & 0x20000000 and scene_flags & 0x200 and -50 < bone_velocity_w < -5:
        backward = _point(struct.unpack_from('<3e', per_scene, 86))
        length = math.hypot(*backward)
        if length == 0:
            raise ValueError("Active backward boost requires a nonzero direction.")
        predicted_velocity = tuple(speed - axis * 0.20000000298023224 / length
                                   for speed, axis in zip(v, backward))
    working_position = _point(struct.unpack_from('<3f', particle, 36))
    position = _point(struct.unpack_from('<3f', particle, 12)) if integration_skipped else working_position
    prediction = predict_cloth_position(
        position, predicted_velocity, delta_time=0. if integration_skipped else dt,
        gravity_direction=struct.unpack_from('<3e', per_scene, 100),
        ground_height=struct.unpack_from('<f', per_frame, 24)[0],
        ground_thickness=struct.unpack_from('<f', simulation_parameter, 208)[0],
        ground_collision_enabled=bool(frame_flags & 0x1000000))
    if prediction['ground_contact']:
        flags |= 2
    result = bytearray(particle)
    _put(result, 12, prediction['position'])
    _put(result, 48, working_position)
    _put(result, 140, v)
    struct.pack_into('<I', result, 64, flags)
    if not flags2 & 0x200:
        for offset in (72, 80):
            count = 8 if storage_variant == 'packed' else 6
            result[offset:offset + count] = bytes(count)
        result[90:92] = bytes(2)
    return {'particle': bytes(result), 'contact_response_eligible': contact,
            'prediction_velocity': predicted_velocity, 'ground_contact': prediction['ground_contact']}


def finalize_cloth_base_hold(
    particle: bytes, simulation_parameter: bytes, per_frame: bytes, *,
    non_gravity_acceleration: Sequence[float], delta_time: float,
) -> dict:
    """Final pinch-timer/hold stage after preceding base flags and SBC updates.

    Acceleration is the retained non-gravity term, not velocity or total gravity.
    Holding requires an existing top flag, flags2 & 0x10000, overstretch >= 99,
    and an acceleration absolute-component sum strictly below float32(0.1).
    It replaces both p histories with working x without erasing velocity/x.
    This does not perform the earlier outward-force flag or SBC buffer writes.
    """
    for record, size in ((particle, 152), (simulation_parameter, 312), (per_frame, 100)):
        _record(record, size)
    dt = _f32(delta_time)
    if dt < 0:
        raise ValueError("Cloth hold delta time must be nonnegative.")
    flags = struct.unpack_from('<I', particle, 64)[0]
    timer = 100000. if flags & 0x300 else struct.unpack_from('<f', particle, 120)[0]
    _finite(timer)
    held = False
    if flags & 0x80000000:
        acc = tuple(_f32(v) for v in _point(non_gravity_acceleration))
        size = _f32(_f32(abs(acc[0]) + abs(acc[1])) + abs(acc[2]))
        ratio = struct.unpack_from('<e', simulation_parameter, 266)[0]
        _finite(ratio)
        held = bool(size < 0.10000000149011612 and ratio >= 99
                    and struct.unpack_from('<I', per_frame, 36)[0] & 0x10000)
    result = bytearray(particle)
    _put(result, 120, (timer + dt,))
    struct.pack_into('<I', result, 64, flags if held else flags & 0x7FFFFFFF)
    if held:
        result[12:24] = result[24:36] = particle[36:48]
    return {'particle': bytes(result), 'held': held}
