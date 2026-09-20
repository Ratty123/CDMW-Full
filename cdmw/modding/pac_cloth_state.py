"""Selected ComputePbdProcessBaseMovement state stages, build 1.0.0.2944.

These consume explicit runtime records around the existing force reference.
Guide/static animation adjustment, substep timing and integration selection are
included; resource resolution, collision detection and full dispatch selection
remain caller-owned. Preserve the decoded stage order and variant.
The arithmetic is a mathematical reference, not bit-exact GPU execution.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Mapping, Sequence

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


def _static_vector(vector, transform):
    rows = tuple(_point(struct.unpack_from('<3f', transform, offset)) for offset in (0, 16, 32))
    return tuple(_f32(sum(vector[i] * rows[i][j] for i in range(3))) for j in range(3))


def _static_translation(transform):
    translation = _point(struct.unpack_from('<3f', transform, 48))
    tile_z, tile_x = struct.unpack_from('<2h', transform, 12)
    return translation, (tile_x, tile_z)


def prepare_static_cloth_animation(
    particle: bytes, simulation_parameter: bytes, per_frame: bytes, per_scene: bytes,
    skinning_data: bytes, host_transform: bytes, *, substep_index: int,
    attaching_transform: bytes | None = None, particle_extra: bytes | None = None,
    reference_particles: Mapping[int, bytes] | None = None,
    reference_skinning: Mapping[int, bytes] | None = None, shrink_mask: int | None = None,
) -> dict:
    """Prepare static-mesh animation/attachment state, before water classification.

    Transforms are already resolved from the shader's selected buffer bank.
    Reference maps use the extra record's particle-relative uint16 indices and
    contain the actual working positions/local positions read by this dispatch.
    Missing active inputs are rejected; unselected attachment/extra data is ignored.

    Static anchors do not use guide interpolation or subtract frame translation.
    Water is sampled AFTER adjustment at the returned world position (the shader
    subtracts previous-view position for sampling). Water does not clear the two
    static skip decisions. Continue with select_cloth_base_integration afterwards.
    """
    for record, size in ((per_frame, 100), (per_scene, 108), (skinning_data, 64), (host_transform, 64)):
        _record(record, size)
    prepared = prepare_cloth_fixed_state(particle, simulation_parameter, shrink_mask=shrink_mask)
    if struct.unpack_from('<H', simulation_parameter, 216)[0] == 0xFFFF:
        raise ValueError("Static animation preparation requires a static-mesh particle.")
    index = _substep_index(substep_index)
    flags, flags2 = struct.unpack_from('<2I', per_frame, 32)
    has_extra = (struct.unpack_from('<H', simulation_parameter, 224)[0] != 0xFFFF
                 and struct.unpack_from('<I', simulation_parameter, 144)[0] != 0xFFFFFFFF)
    extra_flags, references = 0, (0xFFFF, 0xFFFF)
    if has_extra:
        if particle_extra is None:
            raise ValueError("Active static particle-extra storage requires its resolved record.")
        _record(particle_extra, 28)
        extra_flags = struct.unpack_from('<H', particle_extra, 0)[0]
        references = struct.unpack_from('<2H', particle_extra, 22)
    ratio = struct.unpack_from('<e', simulation_parameter, 266)[0]
    attaching_id = struct.unpack_from('<I', skinning_data, 60)[0]
    attaching_offset = struct.unpack_from('<I', simulation_parameter, 92)[0]
    veto = bool(flags & 0x80000 and not extra_flags & 4 and ratio < 99)
    attached = bool(flags & 0x200000 and not veto and attaching_id < 0xFFFF
                    and attaching_offset < 0x1FFFFFFF)
    host_translation, host_tiles = _static_translation(host_transform)
    host_world = (_f32(host_translation[0] + host_tiles[0]*1000), host_translation[1],
                  _f32(host_translation[2] + host_tiles[1]*1000))
    original_local = _point(struct.unpack_from('<3f', skinning_data, 0))
    local = original_local
    selected_transform, relative_translation = host_transform, (0., 0., 0.)
    if attached:
        if attaching_transform is None:
            raise ValueError("Active static attachment requires its resolved attaching transform.")
        _record(attaching_transform, 64)
        tx, ty, tz, scale, qx, qy, qz, qw = struct.unpack_from('<8e', simulation_parameter, 296)
        _finite(tx, ty, tz, scale, qx, qy, qz, qw)
        vector = tuple(_f32(v * scale) for v in local)
        # q * (vector, 0) * conjugate(q), without quaternion normalization.
        projection = sum(v * q for v, q in zip(vector, (qx, qy, qz)))
        factor = qw*qw - qx*qx - qy*qy - qz*qz
        cross = (qy*vector[2] - qz*vector[1], qz*vector[0] - qx*vector[2],
                 qx*vector[1] - qy*vector[0])
        local = tuple(_f32(t + factor*v + 2*(q*projection + qw*c))
                      for t, v, q, c in zip((tx, ty, tz), vector, (qx, qy, qz), cross))
        translation, tiles = _static_translation(attaching_transform)
        relative_translation = (
            _f32(_f32(translation[0] - host_translation[0]) + (tiles[0] - host_tiles[0])*1000),
            _f32(translation[1] - host_translation[1]),
            _f32(_f32(translation[2] - host_translation[2]) + (tiles[1] - host_tiles[1])*1000))
        selected_transform = attaching_transform
    anchor = tuple(_f32(v + t) for v, t in zip(_static_vector(local, selected_transform), relative_translation))
    paired = all(reference != 0xFFFF for reference in references)
    if paired:
        if (reference_particles is None or reference_skinning is None
                or any(i not in reference_particles or i not in reference_skinning for i in references)):
            raise ValueError("Static reference pair requires both indexed particle and skinning records.")
        positions, locals_ = [], []
        for i in references:
            _record(reference_particles[i], 152)
            _record(reference_skinning[i], 64)
            positions.append(_point(struct.unpack_from('<3f', reference_particles[i], 36)))
            locals_.append(_point(struct.unpack_from('<3f', reference_skinning[i], 0)))
        local_edge = tuple(b - a for a, b in zip(*locals_))
        simulated_edge = tuple(b - a for a, b in zip(*positions))
        local_length = math.hypot(*local_edge)
        if local_length == 0:
            raise ValueError("Static reference pair has a zero local edge and no finite shader result.")
        offset = _static_vector(tuple(v - a for v, a in zip(original_local, locals_[0])), selected_transform)
        rotated = _rotate_with_guide_anchor(offset, _static_vector(local_edge, selected_transform), simulated_edge)
        length_ratio = math.hypot(*simulated_edge) / local_length
        anchor = tuple(_f32(a + v*length_ratio) for a, v in zip(positions[0], rotated))

    scene_flags = struct.unpack_from('<I', per_scene, 64)[0]
    special = False
    if flags & 0x20000000 and scene_flags & 0x200:
        lra = struct.unpack_from('<e', particle, 88)[0]
        movement = struct.unpack_from('<e', per_frame, 62)[0]
        _finite(lra, movement)
        special = lra < 0.699999988079071 and -30 < movement < -10
    skip_forces = bool(flags & 1 or special)
    skip_integration = bool(flags2 & 0x100 or special)
    result = bytearray(prepared['particle'])
    if paired and prepared['fixed_by_group_or_mask']:
        _put(result, 12, anchor)
        _put(result, 36, anchor)
    adjusted = skip_forces and index == 0
    if adjusted:
        position = _point(struct.unpack_from('<3f', result, 36))
        previous = _point(struct.unpack_from('<3f', particle, 128))
        _put(result, 12 if skip_integration else 36, _rotate_with_guide_anchor(position, previous, anchor))
        _put(result, 140, (0., 0., 0.))
    _put(result, 0, anchor)
    working = _point(struct.unpack_from('<3f', result, 36))
    frame_translation = _point(struct.unpack_from('<3f', per_frame, 0))
    water_position = tuple(_f32(_f32(h + f) + x) for h, f, x in zip(host_world, frame_translation, working))
    return {**prepared, 'particle': bytes(result), 'attachment_used': attached,
            'reference_pair_used': paired, 'space_adjusted': adjusted,
            'skip_external_forces': skip_forces, 'integration_skipped': skip_integration,
            'host_world_translation': host_world, 'water_test_enabled': bool(flags2 & 0x1000),
            'water_sample_world_position': water_position}


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


def finalize_cloth_base_state(
    particle: bytes, simulation_parameter: bytes, per_frame: bytes, per_scene: bytes, *,
    non_gravity_acceleration: Sequence[float], delta_time: float,
    pre_collision: bytes | None = None,
) -> dict:
    """Finish a fixed/dynamic base step: outward flag, pre-collision resets, hold.

    Inputs are AFTER integration selection/forces/prediction. Early-return modes
    must bypass this function. Fixed particles use the shader's zero acceleration;
    dynamic particles use the retained non-gravity force, not velocity/gravity.

    pre_collision is the ten-uint window at parameter148 + particle_index*10
    in the selected uint buffer, NOT particle sbc_offset124. Supply it when the
    valid resource and reset flags request a write; untouched data is preserved.
    A degenerate outward direction has no supported finite shader result.
    """
    for record, size in ((particle, 152), (simulation_parameter, 312),
                         (per_frame, 100), (per_scene, 108)):
        _record(record, size)
    frame_flags = struct.unpack_from('<I', per_frame, 32)[0]
    if frame_flags & 0xC00:
        raise ValueError("Early-return cloth modes bypass base finalization.")
    flags = struct.unpack_from('<I', particle, 64)[0]
    inverse_mass = struct.unpack_from('<f', particle, 60)[0]
    _finite(inverse_mass)
    acceleration = ((0., 0., 0.) if inverse_mass <= 0 or flags & 0x40 else
                    tuple(_f32(v) for v in _point(non_gravity_acceleration)))
    working = _point(struct.unpack_from('<3f', particle, 36))
    upward = tuple(-v for v in _point(struct.unpack_from('<3e', per_scene, 100)))
    projection = sum(x*u for x, u in zip(working, upward))
    radial = tuple(x - projection*u for x, u in zip(working, upward))
    radial_length = math.hypot(*radial)
    direction = tuple(r + radial_length*u for r, u in zip(radial, upward))
    direction_length = math.hypot(*direction)
    if direction_length == 0:
        raise ValueError("Cloth outward direction is degenerate with no finite shader result.")
    measure = _f32(sum(a*d/direction_length for a, d in zip(acceleration, direction)))
    outward = measure > 30
    flags = flags | 0x40000 if outward else flags & ~0x40000
    resource_valid = struct.unpack_from('<H', simulation_parameter, 226)[0] != 0xFFFF
    reset_first = bool(resource_valid and frame_flags & 0x80000000)
    reset_second = bool(resource_valid and frame_flags & 0x10)
    cache = None
    if pre_collision is not None:
        _record(pre_collision, 40)
        cache = bytearray(pre_collision)
    if (reset_first or reset_second) and cache is None:
        raise ValueError("Active pre-collision reset requires the resolved ten-uint window.")
    if reset_first:
        struct.pack_into('<5I', cache, 0, 0, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0)
    if reset_second:
        struct.pack_into('<5I', cache, 20, 0, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF)
        flags &= ~0x20000000
    result = bytearray(particle)
    struct.pack_into('<I', result, 64, flags)
    final = finalize_cloth_base_hold(bytes(result), simulation_parameter, per_frame,
                                     non_gravity_acceleration=acceleration, delta_time=delta_time)
    return {**final, 'outward_force': outward, 'outward_measure': measure,
            'pre_collision': None if cache is None else bytes(cache),
            'reset_pre_collision_halves': (reset_first, reset_second)}


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
