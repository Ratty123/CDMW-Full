"""Decoded guide input-position collision pass, build 1.0.0.2944.

Runs after animation preparation, before common integration selection. Explicit
buffer snapshots supply the referenced collider groups, scenes and transforms.
This is a mathematical reference, not a complete contact solver or GPU emulator.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Mapping

from ._pbd_numeric import f32
from .pac_cloth_base import _finite, _point, _record


def _entry(records, key, size, name):
    if records is None or key not in records:
        raise ValueError(f"Cloth input collision requires the selected {name} record {key}.")
    result = records[key]
    _record(result, size)
    return result


def _profile(mode, thickness, radius, count, moving):
    """Native SSA1034..1155: PAC mode can change geometry and flag writing."""
    outside, mark = True, True
    if count > 2 and mode < 2:
        thickness = f32(thickness + f32(.03))
    elif mode in (6, 7):
        if mode == 7 and moving:
            thickness = f32(.03)
        if count > 2:
            thickness = f32(-.05)
    elif mode in (8, 12):
        if moving:
            thickness = f32(.05)
    elif mode == 9:
        if moving or count == 1:
            thickness = f32(.14)
    elif mode == 10:
        thickness = f32(.08) if moving else f32(.05) if count == 1 else thickness
    elif mode == 11:
        thickness = f32(.05) if moving else f32(.03) if count == 1 else thickness
    elif mode == 13:
        if count == 1:
            radius, thickness = f32(radius * f32(.7)), f32(.08)
        else:
            thickness = f32(.1 if moving else .02)
    elif mode in (14, 19):
        if count == 1:
            thickness = f32(.01)
        mark = mode != 19
    elif mode == 15:
        if count == 1:
            thickness = f32(.02)
    elif mode == 16:
        if count == 1 or moving:
            thickness = f32(.03)
    elif mode in (17, 18):
        if radius < f32(.2):
            radius = f32(.3)
        if mode == 18 and count == 1:
            thickness = f32(.03)
    elif mode == 20:
        mark = count <= 1
        if count == 1:
            thickness = f32(thickness + f32(.05))
    elif mode in (21, 22, 23):
        outside = False
        if mode == 23 or (mode == 22 and count == 1):
            thickness = f32(.02)
    _finite(radius, thickness)
    return radius, thickness, outside, mark


def apply_cloth_input_collisions(
    particle: bytes, simulation_parameter: bytes, per_frame: bytes, per_scene: bytes,
    global_parameters: bytes, *, reference_collidables: Mapping[int, int] | None = None,
    extra_collidables: Mapping[int, bytes] | None = None,
    scene_objects: Mapping[tuple[int, int], bytes] | None = None,
    collidable_results: Mapping[tuple[int, int], bytes] | None = None,
    collidables: Mapping[tuple[int, int], bytes] | None = None,
) -> dict:
    """Correct prepared guide anchors using the base shader's actual list order.

    Reference-map keys are absolute indices; values pack extra-group start/count
    in low/high16 bits. Extra-map keys are absolute group indices (56-byte data).
    Scene/result/definition maps use (selected buffer, absolute element) keys
    and 108/56/104-byte records. Resource indices >=65000 select buffer0 as in
    the shader; identity checks still compare the original packed/raw indices.

    Static particles and disabled global/frame gates bypass the entire stage.
    Frame early-return/fixed modes do NOT bypass this earlier pass. Only ix and
    flags change; contact normals, predicted positions and velocity are untouched.
    Missing consumed snapshots and degenerate collider axes are rejected.
    """
    for record, size in ((particle, 152), (simulation_parameter, 312), (per_frame, 100),
                         (per_scene, 108), (global_parameters, 1216)):
        _record(record, size)
    frame_flags, flags2 = struct.unpack_from('<2I', per_frame, 32)
    enabled = struct.unpack_from('<I', global_parameters, 1200)[0] != 0
    guide = struct.unpack_from('<H', simulation_parameter, 216)[0] == 0xFFFF
    if not guide or not flags2 & 0x20000 or not enabled:
        return {'particle': bytes(particle), 'active': False, 'projected_colliders': 0}

    flags = struct.unpack_from('<I', particle, 64)[0]
    scene_flags = struct.unpack_from('<I', per_scene, 64)[0]
    velocity = _point(struct.unpack_from('<3e', per_frame, 56))
    fast = f32(math.hypot(*velocity)) > 4
    if bool(scene_flags & 0x200) != bool(scene_flags & 0xC00) or scene_flags & 0x10000 or fast:
        flags &= ~0x1000000
    anchor = _point(struct.unpack_from('<3f', particle, 0))
    reference_start, reference_count = struct.unpack_from('<2H', per_scene, 72)
    packed_scene = struct.unpack_from('<I', simulation_parameter, 60)[0]
    own_offset, pac_id = struct.unpack_from('<2I', simulation_parameter, 180)
    own_buffer = struct.unpack_from('<H', simulation_parameter, 238)[0]
    parameter_flags = struct.unpack_from('<H', simulation_parameter, 212)[0]
    force_mask = bool(scene_flags & 0x40000 or flags2 & 0x400000)
    projected = 0

    for reference_index in range(reference_start, reference_start + reference_count):
        if reference_collidables is None or reference_index not in reference_collidables:
            raise ValueError(f"Cloth input collision requires reference entry {reference_index}.")
        reference = reference_collidables[reference_index]
        if type(reference) is not int or not 0 <= reference <= 0xFFFFFFFF:
            raise ValueError("Cloth reference entries must be unsigned 32-bit integers.")
        if reference == 0xFFFFFFFF:
            continue
        start, count = reference & 0xFFFF, reference >> 16
        mask_offset = 0  # Restarts for each reference, including repeated references.
        for group_index in range(start, start + count):
            group = _entry(extra_collidables, group_index, 56, 'extra-collidable')
            group_flags, collider_count, group_pac, srv, uav = struct.unpack_from('<2H3I', group)
            other_packed, srv_offset, uav_offset = struct.unpack_from('<3I', group, 28)
            other_key = (other_packed >> 16 if other_packed < 65000 << 16 else 0,
                         other_packed & 0xFFFF)
            other_scene = _entry(scene_objects, other_key, 108, 'scene-object')
            same_scene = packed_scene == other_packed
            same_pac = same_scene and pac_id != 0xFFFFFFFF and pac_id == group_pac
            same_source = own_buffer == srv and own_offset == srv_offset
            group_selected = not same_source or bool(group_flags & 4 and same_pac)
            parent = struct.unpack_from('<I', other_scene, 68)[0]
            eligible = (parent == packed_scene and group_flags & 2 and
                        frame_flags & 0x20000000 and scene_flags & 0x200 and
                        (not parameter_flags & 0x10 or fast))
            if group_selected and eligible and collider_count:
                movement = struct.unpack_from('<e', per_frame, 62)[0]
                _finite(movement)
                if movement > -20:
                    for index in range(collider_count):
                        mask_index = mask_offset + index
                        if same_scene and not force_mask and mask_index <= 95:
                            mask = struct.unpack_from('<I', simulation_parameter, 64 + 4*(mask_index//32))[0]
                            if not mask & (1 << (mask_index % 32)):
                                continue
                        result_key = (uav if uav < 65000 else 0, (uav_offset + index) & 0xFFFFFFFF)
                        definition_key = (srv if srv < 65000 else 0, (srv_offset + index) & 0xFFFFFFFF)
                        collider_result = _entry(collidable_results, result_key, 56, 'collidable-result')
                        definition = _entry(collidables, definition_key, 104, 'collidable-definition')
                        corrected, contact = _project_input_anchor(
                            anchor, particle, simulation_parameter, per_frame, per_scene,
                            global_parameters, other_scene, collider_result, definition,
                            collider_count, index, fast)
                        projected += corrected != anchor
                        anchor = corrected
                        if contact:
                            flags |= 0x1000000
            mask_offset += collider_count  # Skipped groups still consume mask positions.

    flags |= (flags << 6) & 0x40000000  # OR the contact bit into its retained companion.
    result = bytearray(particle)
    struct.pack_into('<3f', result, 0, *anchor)
    struct.pack_into('<I', result, 64, flags)
    return {'particle': bytes(result), 'active': True, 'projected_colliders': projected}


def _project_input_anchor(anchor, particle, parameter, frame, scene, globals_, other_scene,
                          collider_result, definition, count, index, fast):
    center1 = _point(struct.unpack_from('<3f', collider_result, 20))
    center2 = _point(struct.unpack_from('<3f', collider_result, 44))
    axis = tuple(f32(a - b) for a, b in zip(center1, center2))
    length = math.hypot(*axis)
    if length == 0:
        raise ValueError("Degenerate input collider axis has no supported finite shader result.")
    axis = tuple(f32(v/length) for v in axis)
    host = _point(struct.unpack_from('<3f', scene, 0))
    offset = _point(struct.unpack_from('<3f', frame, 0))
    other = _point(struct.unpack_from('<3f', other_scene, 0))
    host_x, host_z = struct.unpack_from('<2h', scene, 12)
    other_x, other_z = struct.unpack_from('<2h', other_scene, 12)
    tile_delta = ((host_x - other_x)*1000., 0., (host_z - other_z)*1000.)
    relative = tuple(f32(f32(f32(f32(f32(a + b) - c) + d) + x) - e)
                     for a, b, c, d, x, e in zip(host, offset, other, tile_delta, anchor, center1))
    depth = f32(sum(a*b for a, b in zip(relative, axis)))
    radial = tuple(f32(v - f32(depth*n)) for v, n in zip(relative, axis))
    radial_distance = f32(math.hypot(*radial))
    radius = struct.unpack_from('<f', collider_result, 4)[0]
    custom = struct.unpack_from('<I', globals_, 1204)[0] != 0
    mode, thickness = struct.unpack_from('<if', parameter, 196) if custom else (0, 0.)
    ground_height = struct.unpack_from('<f', frame, 24)[0]
    _finite(ground_height)
    radius, thickness, outside, mark = _profile(mode, thickness, radius, count, fast or ground_height < -10)
    accepted = struct.unpack_from('<H', definition, 2)[0] == 3 and depth < thickness
    if mode & ~2 == 0 or mode > 5:
        accepted = accepted and (count == 1 or radius < f32(.4))
    if mode & ~2 == 1:
        accepted = accepted and (index == 0 or radius < f32(.4))
    elif mode == 5:
        lra = struct.unpack_from('<e', particle, 88)[0]
        _finite(lra)
        accepted = accepted and (count == 1 or radius < f32(.4)) and lra > f32(.1)
    inside_radius = radial_distance < radius
    if accepted and (inside_radius or outside):
        anchor = tuple(f32(x - f32(f32(depth - thickness)*n)) for x, n in zip(anchor, axis))
    return anchor, bool(accepted and inside_radius and mark)
