"""Decoded CPU cloth parameter updates from build 1.0.0.2944.

These implement selected material-mask, LOD and frame-update stages.
Supply actual runtime globals explicitly; initialization defaults do not prove
live configuration. Python pow rounded to float32 is not bit-exact CRT powf.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Collection, Sequence

from ._pbd_numeric import f32, round_pbd_half
from .pac_cloth_base import _boolean, _record


def _integer(value, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError("Cloth runtime integer is outside its decoded storage range.")
    return value


def _four(values):
    if len(values) != 4:
        raise ValueError("Cloth stiffness globals require stretch, bend, area and restore entries.")
    return tuple(f32(value) for value in values)


def _modified_stiffness(value, cap, scale, denominator, limit, nonpositive):
    if value <= 0:
        return nonpositive
    bounded = max(0., min(value, cap))
    exponent = f32(scale / denominator)
    try:
        powered = f32(math.pow(f32(1. - bounded), exponent))
    except (OverflowError, ValueError) as exc:
        raise ValueError("Cloth stiffness conversion requires a finite power result.") from exc
    return min(f32(1. - powered), limit)


def _update_half(record, offset, value):
    old = struct.unpack_from('<e', record, offset)[0]
    # VCOMISS treats an unordered old value as requiring a write. Finite values
    # use float32 subtraction and an inclusive +/- FLT_EPSILON comparison.
    if math.isfinite(old) and abs(f32(old - value)) <= 2.0 ** -23:
        return False
    struct.pack_into('<e', record, offset, round_pbd_half(value))
    return True


def build_cloth_material_collision_mask(
    collider_bone_hashes: Sequence[int], *, inclusion_bone_hashes: Collection[int],
    exclusion_bone_hashes: Collection[int],
    temporary_fix_exclusion_bone_hashes: Collection[int],
) -> tuple[int, int, int]:
    """Build the three CPU mask words at owner+0x80 from 0x143CE1B20.

    Supply collider hashes in the caller's concatenated group/element order,
    not skeleton or PAC palette order. Material lists contain already-hashed
    uint32 names. No inclusions starts with all 96 bits set; any inclusion entry
    starts with zero, even if its hash is the skipped 0xFFFFFFFF sentinel.
    Inclusion sets matching bits, then either exclusion list clears them.

    Sentinel collider keys retain their initial bit and still consume a slot.
    Repeated hashes retain separate slots; indices beyond 95 cannot change this
    mask. CPU upload at 0x143CE2237 copies these words to simulation bytes64..75.
    Other masks, live overrides and shader admission gates remain caller-owned.
    """
    for values in (collider_bone_hashes, inclusion_bone_hashes, exclusion_bone_hashes,
                   temporary_fix_exclusion_bone_hashes):
        for value in values:
            _integer(value, 0, 0xFFFFFFFF)
    inclusions = frozenset(inclusion_bone_hashes)
    exclusions = frozenset(exclusion_bone_hashes) | frozenset(temporary_fix_exclusion_bone_hashes)
    words = [0 if inclusion_bone_hashes else 0xFFFFFFFF] * 3
    for index, bone_hash in enumerate(collider_bone_hashes[:96]):
        if bone_hash == 0xFFFFFFFF:
            continue
        word, bit = index // 32, 1 << (index % 32)
        if inclusion_bone_hashes and bone_hash in inclusions:
            words[word] |= bit
        if bone_hash in exclusions:
            words[word] &= ~bit
    return tuple(words)


def update_cloth_frame_stiffness(
    per_frame: bytes, *, simulation_mode: int, stretching_stiffness: float,
    bending_stiffness: float, area_stiffness: float, restore_angle_stiffness: float,
    underwater_restore_angle_stiffness: float, stiffness_denominator: float,
    scale_factors: Sequence[float], limits: Sequence[float],
    bend_uses_unit_denominator: bool,
) -> dict:
    """Transform authored stiffness and update five half fields in the frame.

    Both four-entry global sequences are ordered stretch, bend, area, restore.
    Mode 1 caps stretch/bend inputs at float32(.4); other byte modes use .99.
    Area/restore inputs cap at1. Positive values become
    min(1 - powf(1 - clamped_input, scale / denominator), global_limit).
    Bend uses denominator1 when its separate runtime switch is true.

    Nonpositive stretch/area produce0, bend/restore produce-1. Negative underwater
    restore uses the RAW ordinary restore value before applying the same transform;
    zero is an explicit -1 result, not fallback. It shares restore globals.

    Each old half is compared with the unrounded result before CPU half packing.
    A write invalidates the upload even if the packed bytes happen to stay equal.
    Other frame fields, including fading/elasticity and flags, are preserved.
    """
    _record(per_frame, 100)
    _integer(simulation_mode, 0, 255)
    _boolean(bend_uses_unit_denominator)
    scales, caps = _four(scale_factors), _four(limits)
    denominator = f32(stiffness_denominator)
    if denominator <= 0:
        raise ValueError("Cloth stiffness denominator must be positive.")
    stretch, bend, area, restore, underwater = (
        f32(value) for value in (stretching_stiffness, bending_stiffness, area_stiffness,
                                restore_angle_stiffness, underwater_restore_angle_stiffness))
    input_cap = f32(.4 if simulation_mode == 1 else .99)
    if underwater < 0:
        underwater = restore
    values = {
        'modified_stretch_stiffness': _modified_stiffness(stretch, input_cap, scales[0], denominator, caps[0], 0.),
        'modified_bend_stiffness': _modified_stiffness(
            bend, input_cap, scales[1], 1. if bend_uses_unit_denominator else denominator, caps[1], -1.),
        'modified_area_stiffness': _modified_stiffness(area, 1., scales[2], denominator, caps[2], 0.),
        'modified_restore_angle_stiffness': _modified_stiffness(restore, 1., scales[3], denominator, caps[3], -1.),
        'modified_underwater_restore_angle_stiffness': _modified_stiffness(
            underwater, 1., scales[3], denominator, caps[3], -1.),
    }
    result = bytearray(per_frame)
    offsets = tuple(offset for offset, value in zip((66, 68, 70, 72, 94), values.values())
                    if _update_half(result, offset, value))
    return {'per_frame': bytes(result), 'values': values, 'updated_offsets': offsets,
            'upload_invalidated': bool(offsets)}


def update_cloth_iteration_bits(
    per_frame: bytes, *, simulation_lod: int, material_solver_iterations: int,
    material_over_iteration_skip_lod: int, global_solver_iterations: int,
    global_over_iteration_skip_lod: int,
) -> dict:
    """Select and upload the low three frame-flags2 bits after LOD selection.

    material_solver_iterations is the already-parsed uint32 CPU field at0xDC;
    XML parsing rounds odd values upward BEFORE this stage. Only its low16 bits
    and the global uint16 count are compared. A negative material skip LOD uses
    the global signed threshold. LOD at/above that threshold chooses2; otherwise
    the smaller count is selected. Comparison occurs BEFORE the low3-bit mask,
    so counts above7 can invalidate an upload without changing packed bits.
    This does not derive LOD or the complete GPU dispatch/iteration schedule.
    """
    _record(per_frame, 100)
    _integer(simulation_lod, -128, 127)
    _integer(material_solver_iterations, 0, 0xFFFFFFFF)
    _integer(global_solver_iterations, 0, 0xFFFF)
    _integer(material_over_iteration_skip_lod, -0x80000000, 0x7FFFFFFF)
    _integer(global_over_iteration_skip_lod, -0x80000000, 0x7FFFFFFF)
    threshold = (global_over_iteration_skip_lod if material_over_iteration_skip_lod < 0
                 else material_over_iteration_skip_lod)
    selected = 2 if simulation_lod >= threshold else min(material_solver_iterations & 0xFFFF,
                                                        global_solver_iterations)
    flags = struct.unpack_from('<I', per_frame, 36)[0]
    invalidated = (flags & 7) != selected
    result = bytearray(per_frame)
    if invalidated:
        struct.pack_into('<I', result, 36, (flags & 0xFFFFFFF8) | (selected & 7))
    return {'per_frame': bytes(result), 'selected_limit': selected, 'iteration_bits': selected & 7,
            'upload_invalidated': invalidated}


def select_cloth_simulation_lod(
    screen_ratio: float, *, material_scale: float, apply_material_scale: bool,
    global_scale: float, thresholds: Sequence[float], forced_lod: int,
) -> int:
    """Normal LOD selection at0x143CE2790..282A, after caller force branches.

    thresholds are ordered LOD3, LOD2, LOD1. Strictly below a threshold selects
    that LOD; equality continues toward higher detail. No sorting or clamping is
    inserted. Material scale applies only with the resolved live resource pair.
    forced_lod=-1 selects the score path; any other signed32 value supplies its
    signed low byte. Earlier forced3/forced0/skip branches bypass this function.
    """
    _boolean(apply_material_scale)
    _integer(forced_lod, -0x80000000, 0x7FFFFFFF)
    if forced_lod != -1:
        return ((forced_lod + 128) & 255) - 128
    if len(thresholds) != 3:
        raise ValueError("Cloth LOD requires thresholds for LOD3, LOD2 and LOD1.")
    score = f32(screen_ratio)
    if apply_material_scale:
        score = f32(score * f32(material_scale))
    score = f32(score * f32(global_scale))
    for lod, threshold in zip((3, 2, 1), thresholds):
        if score < f32(threshold):
            return lod
    return 0


def update_cloth_lod_state(
    controller_window: bytes, *, selected_lod: int, simulation_lod_limit: int,
    reset_fade: bool, current_state_flag: bool,
) -> dict:
    """Update the owner+0x60..0x9F window after LOD selection.

    The 64-byte window is a slice, NOT a whole controller object. Its first two
    bytes are LOD/direction, float4 stores fading, float8 the elasticity override,
    and byte0x39 the prior caller state. reset_fade identifies the earlier
    forced3/forced0/skip branches; the normal and cvar-forced paths preserve an
    existing direction unless they cross the simulation LOD limit.

    External writes are returned as requests: reactivation copies the configured
    resource+0x102 byte and sets owner+0x12D mask0x4; a caller-state falling edge
    below the limit copies resource+0x103. LOD changes set component+0xB5 mask0x2.
    The owner count at+0x1C8 increments below the limit or while stored fading
    is <=float32(.99). Resource resolution/counter values remain caller-owned.
    """
    _record(controller_window, 64)
    _integer(selected_lod, -128, 127)
    _integer(simulation_lod_limit, -0x80000000, 0x7FFFFFFF)
    _boolean(reset_fade)
    _boolean(current_state_flag)
    old_lod, direction = struct.unpack_from('<2b', controller_window)
    reactivated = old_lod >= simulation_lod_limit and selected_lod < simulation_lod_limit
    if reset_fade:
        direction = 0
    elif reactivated:
        direction = -1
    elif old_lod < simulation_lod_limit <= selected_lod:
        direction = 1
    result = bytearray(controller_window)
    struct.pack_into('<2b', result, 0, selected_lod, direction)
    struct.pack_into('<f', result, 8, 0.)
    reset_resource_103 = False
    if selected_lod < simulation_lod_limit:
        reset_resource_103 = bool(controller_window[0x39] and not current_state_flag)
        result[0x39] = int(current_state_flag)
        increment_count = True
    else:
        increment_count = f32(struct.unpack_from('<f', controller_window, 4)[0]) <= f32(.99)
    return {'controller_window': bytes(result), 'reactivated': reactivated,
            'reset_resource_103': reset_resource_103, 'lod_changed': selected_lod != old_lod,
            'increment_count_1c8': increment_count}


def advance_cloth_frame_blend(
    controller_window: bytes, per_frame: bytes, *, delta_time: float,
    fade_reciprocal_denominator: float, minimum_fade_rate: float,
    elasticity_transition_duration: float, scene_requests_natural_warmup: bool,
    need_natural_warmup: bool, material_elasticity: float, ragdoll_active: bool,
    additive_ragdoll_elasticity: float, external_elasticity_ratio: float,
) -> dict:
    """Advance CPU blend state and upload elasticity76/fading78 at0x143CE3C26.

    controller_window is owner+0x60..0x9F. delta_time is already selected/scaled
    by the caller. Timer0x74 contributes amount0x78 only while still positive
    AFTER decrement. Timer0x70 updates additive0x6C from remaining/duration,
    inverted when byte0x98 is nonzero; an inactive timer preserves that additive.

    Nonzero direction0x61 computes rate=max(minimum_rate,1/denominator). +1/-1
    advances stored fade0x64 up/down; only crossing1/0 clears the direction.
    Direction zero instead uploads fade0, preserving stored fade. Natural warmup
    resets stored/uploaded fade unless the updated direction is+1.

    Elasticity clamps material+eligible ragdoll+additive+eligible timed amount,
    then blends toward1 by override0x68 and the explicit external ratio in order.
    Those final two ratios are not implicitly clamped. This stage does not update
    wind, bone motion, scene flags or the timers' activation/source state.
    """
    _record(controller_window, 64)
    _record(per_frame, 100)
    for flag in (scene_requests_natural_warmup, need_natural_warmup, ragdoll_active):
        _boolean(flag)
    dt = f32(delta_time)
    if dt < 0:
        raise ValueError("Cloth blend delta time must be nonnegative.")
    result = bytearray(controller_window)
    timed_remaining = f32(struct.unpack_from('<f', result, 0x14)[0])
    if timed_remaining > 0:
        timed_remaining = max(0., f32(timed_remaining - dt))
        struct.pack_into('<f', result, 0x14, timed_remaining)
    transition_remaining = f32(struct.unpack_from('<f', result, 0x10)[0])
    if transition_remaining > 0:
        duration = f32(elasticity_transition_duration)
        if duration <= 0:
            raise ValueError("Active cloth elasticity transition requires a positive duration.")
        transition_remaining = max(0., f32(transition_remaining - dt))
        additive = f32(transition_remaining / duration)
        if result[0x38]:
            additive = f32(1. - additive)
        struct.pack_into('<2f', result, 0xC, additive, transition_remaining)
    direction = struct.unpack_from('<b', result, 1)[0]
    fading = 0.
    if direction:
        denominator = f32(fade_reciprocal_denominator)
        if denominator <= 0:
            raise ValueError("Active cloth fade requires a positive reciprocal denominator.")
        rate = max(f32(minimum_fade_rate), f32(1. / denominator))
        fading = f32(struct.unpack_from('<f', result, 4)[0])
        if direction in (-1, 1):
            step = f32(rate * dt)
            fading = f32(fading + step) if direction == 1 else f32(fading - step)
            if direction == 1 and fading > 1. or direction == -1 and fading < 0.:
                fading = 1. if direction == 1 else 0.
                direction = 0
                struct.pack_into('<b', result, 1, direction)
            struct.pack_into('<f', result, 4, fading)
    if scene_requests_natural_warmup and direction != 1 and need_natural_warmup:
        fading = 0.
        struct.pack_into('<f', result, 4, fading)
    elasticity = f32(material_elasticity)
    elasticity = f32(elasticity + (f32(additive_ragdoll_elasticity) if ragdoll_active else 0.))
    elasticity = f32(elasticity + f32(struct.unpack_from('<f', result, 0xC)[0]))
    elasticity = f32(elasticity + (f32(struct.unpack_from('<f', result, 0x18)[0]) if timed_remaining > 0 else 0.))
    elasticity = min(1., max(0., elasticity))
    for ratio in (struct.unpack_from('<f', result, 8)[0], external_elasticity_ratio):
        elasticity = f32(elasticity + f32(f32(1. - elasticity) * f32(ratio)))
    frame_result = bytearray(per_frame)
    offsets = tuple(offset for offset, value in ((76, elasticity), (78, fading))
                    if _update_half(frame_result, offset, value))
    return {'controller_window': bytes(result), 'per_frame': bytes(frame_result),
            'values': {'elasticity': elasticity, 'fading_ratio': fading},
            'updated_offsets': offsets, 'upload_invalidated': bool(offsets)}
