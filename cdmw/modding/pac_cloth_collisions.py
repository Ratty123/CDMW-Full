"""Decoded cloth collision references, build 1.0.0.2944.

The guide input pass runs before integration; shape/contact helpers belong to
the later constraint pass. Explicit snapshots and selected positions are required.
This is a mathematical reference, not a complete contact solver or GPU emulator.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Mapping, Sequence

from ._pbd_numeric import f32
from .pac_cloth_base import _boolean, _finite, _point, _record


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


def _shape_type(value):
    if type(value) is not int or not 0 <= value <= 0xFFFF:
        raise ValueError("Cloth collider type must be an unsigned 16-bit integer.")


def _difference(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def _unit(value):
    length = math.hypot(*value)
    if not math.isfinite(length) or length == 0:
        raise ValueError("Degenerate cloth contact direction has no supported finite shader result.")
    return tuple(x/length for x in value)


def cloth_collider_proximity_distance(
    position: Sequence[float], *, collider_type: int, center1: Sequence[float],
    center2: Sequence[float] | None, radius: float,
) -> float:
    """Constraint prepass signed distance: sphere1, capped cylinder3, capsule5.

    The caller supplies the queried position and current centers in one space,
    and the DEFINITION radius consumed by this prepass. Other types return its
    literal1000 sentinel. A collapsed capsule has no finite distance branch here;
    the later surface query has a distinct short-capsule rule.
    """
    _shape_type(collider_type)
    if collider_type not in (1, 3, 5):
        return 1000.
    p, a = _point(position), _point(center1)
    _finite(radius)
    relative = _difference(p, a)
    if collider_type == 1:
        distance = math.hypot(*relative) - radius
    else:
        if center2 is None:
            raise ValueError("Cloth proximity collider requires its second center.")
        edge = _difference(_point(center2), a)
        length = math.hypot(*edge)
        if length == 0:
            raise ValueError("Degenerate proximity collider axis has no supported finite shader result.")
        axis = tuple(v/length for v in edge)
        axial = _dot(relative, axis)
        if collider_type == 5:
            along = min(max(axial, 0.), length)
            distance = math.hypot(*(v - along*n for v, n in zip(relative, axis))) - radius
        else:
            radial = math.hypot(*(v - axial*n for v, n in zip(relative, axis))) - radius
            end = abs(axial - length*.5) - length*.5
            distance = max(radial, end)
            if distance >= 0:
                distance = math.hypot(max(radial, 0.), max(end, 0.))
    _finite(distance)
    return distance


def cloth_collider_contact_surface(
    reference_position: Sequence[float], *, collider_type: int,
    center1: Sequence[float], center2: Sequence[float] | None,
    radius: float, thickness: float,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Return the later pass's surface point and response normal in one space.

    Radius is already selected by the caller (animated result or static definition).
    Thickness expands sphere/capsule radius; cylinders also extend both ends.
    Cylinder cap/side ties choose the cap, then an edge band can blend the normal
    without changing that selected point. This is the shader response surface,
    not a claim that the point is the Euclidean closest point. Types outside
    1/3/5 return the shader's zero point/normal; static type4 uses its own branch.
    """
    _shape_type(collider_type)
    if collider_type not in (1, 3, 5):
        return (0., 0., 0.), (0., 0., 0.)
    p, a = _point(reference_position), _point(center1)
    _finite(radius, thickness)
    expanded = radius + thickness
    _finite(expanded)
    if collider_type == 1:
        normal = _unit(_difference(p, a))
        return _point(tuple(x + expanded*n for x, n in zip(a, normal))), normal
    if center2 is None:
        raise ValueError("Cloth contact collider requires its second center.")
    b = _point(center2)
    edge = _difference(b, a)
    length = math.hypot(*edge)
    if collider_type == 5:
        center = a
        if length >= f32(.000001):
            axis = tuple(v/length for v in edge)
            along = _dot(_difference(p, a), axis)
            center = b if along > length else a if along < 0 else tuple(x + along*n for x, n in zip(a, axis))
        normal = _unit(_difference(p, center))
        return _point(tuple(x + expanded*n for x, n in zip(center, normal))), normal

    original_axis = _unit(edge)
    a = tuple(x - thickness*n for x, n in zip(a, original_axis))
    b = tuple(x + thickness*n for x, n in zip(b, original_axis))
    edge = _difference(b, a)
    axis = _unit(edge)
    half = math.hypot(*edge)*.5
    relative = _difference(p, a)
    along = _dot(relative, axis)
    radial = tuple(x - along*n for x, n in zip(relative, axis))
    radial_distance = math.hypot(*radial) - expanded
    cap_distance = abs(along - half) - half
    cap_normal = axis if along > half else tuple(-n for n in axis)
    side = cap_distance < radial_distance
    normal = _unit(radial) if side else cap_normal
    distance = radial_distance if side else cap_distance
    surface = _point(tuple(x - distance*n for x, n in zip(p, normal)))
    band = min(half, expanded)*.5
    if min(radial_distance, cap_distance) > -band:
        radial_normal = _unit(radial)
        normal = _unit(tuple((band + radial_distance)*r + (band + cap_distance)*c
                             for r, c in zip(radial_normal, cap_normal)))
    return surface, normal


def resolve_cloth_moving_contact(
    position: Sequence[float], reference_position: Sequence[float], *,
    surface_position: Sequence[float], surface_normal: Sequence[float],
    collider_displacement: Sequence[float], apply_tangential_damping: bool,
) -> dict:
    """Project the selected target against a supplied moving-collider surface.

    Surface lookup, collider motion/space conversion and branch selection precede
    this call. The optional decoded tangent correction uses0.45 and relative
    motion; it does not use the static-group friction coefficients. Contact flags,
    cached normals and the selection of destination positions remain caller work.
    """
    p, reference, surface, normal, motion = (
        _point(v) for v in (position, reference_position, surface_position, surface_normal, collider_displacement))
    _boolean(apply_tangential_damping)
    depth = _dot(normal, _difference(p, surface))
    _finite(depth)
    if depth >= 0:
        return {'position': p, 'contact': False}
    projected = tuple(x - depth*n for x, n in zip(p, normal))
    if apply_tangential_damping:
        relative = tuple(x - r - m for x, r, m in zip(p, reference, motion))
        along = _dot(relative, normal)
        tangent = tuple(x - along*n for x, n in zip(relative, normal))
        # Positive penetration / zero normal motion is +inf, then FMin selects1.
        ratio = 1. if along == 0 else min(-depth/abs(along), 1.)
        amount = -f32(.45)*ratio
        projected = tuple(x + amount*t for x, t in zip(projected, tangent))
    return {'position': _point(projected), 'contact': True}


def project_static_cloth_collider(
    position: Sequence[float], reference_position: Sequence[float],
    collider_definition: bytes, collider_group: bytes, *,
    translation_to_collider_space: Sequence[float], collision_thickness: float,
) -> dict:
    """Project one selected attached-static collider, including its friction.

    Definition/group records are104/16 bytes. The caller supplies the selected
    scene/frame/tile translation. Type4 reads localCenter2 as an UNNORMALIZED
    plane normal and bypasses friction; 1/3/5 use the reference-position surface
    and group half4/6 static/kinetic coefficients. Group traversal/activation and
    later flags remain separate. Records and input points are never modified.
    """
    _record(collider_definition, 104)
    _record(collider_group, 16)
    p, reference, translation = (_point(v) for v in (position, reference_position, translation_to_collider_space))
    _finite(collision_thickness)
    kind = struct.unpack_from('<H', collider_definition, 2)[0]
    a = _point(struct.unpack_from('<3f', collider_definition, 76))
    b = struct.unpack_from('<3f', collider_definition, 88)
    center = _difference(a, translation)
    if kind == 4:
        normal = _point(b)
        depth = _dot(_difference(p, center), normal) - collision_thickness
        _finite(depth)
        return {'position': _point(tuple(x - depth*n for x, n in zip(p, normal))) if depth < 0 else p,
                'contact': depth < 0}
    radius = struct.unpack_from('<f', collider_definition, 4)[0]
    surface, normal = cloth_collider_contact_surface(
        reference, collider_type=kind, center1=center, center2=_difference(b, translation),
        radius=radius, thickness=collision_thickness)
    depth = _dot(_difference(p, surface), normal)
    _finite(depth)
    if depth >= 0:
        return {'position': p, 'contact': False}
    penetration = -depth
    projected = tuple(x + penetration*n for x, n in zip(p, normal))
    movement = _difference(p, reference)
    along = _dot(movement, normal)
    tangent = tuple(x - along*n for x, n in zip(movement, normal))
    length = math.hypot(*tangent)
    if length > f32(.000001):
        static, kinetic = struct.unpack_from('<2e', collider_group, 4)
        _finite(static, kinetic)
        static_enabled = static > f32(.001)
        if static_enabled and length <= static*penetration:
            projected = _difference(projected, tangent)
        elif kinetic > f32(.001):
            coefficient = min(kinetic, static) if static_enabled else kinetic
            amount = min(coefficient*penetration, length)/length
            projected = tuple(x - amount*t for x, t in zip(projected, tangent))
    return {'position': _point(projected), 'contact': True}
