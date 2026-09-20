"""Decoded CPU cloth parameter updates from build 1.0.0.2944.

These implement selected stages of 0x143CE26F0, after material/LOD resolution.
Supply actual runtime globals explicitly; initialization defaults do not prove
live configuration. Python pow rounded to float32 is not bit-exact CRT powf.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence

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
