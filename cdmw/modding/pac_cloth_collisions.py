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
        raise ValueError(f"Cloth collision requires the selected {name} record {key}.")
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


def apply_attached_static_cloth_collisions(
    position: Sequence[float], reference_position: Sequence[float],
    simulation_parameter: bytes, per_frame: bytes, per_scene: bytes, *,
    frame_number_y: int, previous_contact: bool,
    static_instances: Mapping[tuple[int, int], bytes] | None = None,
    reference_collidables: Mapping[int, int] | None = None,
    collider_groups: Mapping[int, bytes] | None = None,
    collidables: Mapping[tuple[int, int], bytes] | None = None,
) -> dict:
    """Apply the constraint pass's attached-static list after animated contacts.

    Both guide and static-mesh branches use this loop. The caller must resolve
    outer constraint/collision eligibility and supply the selected target,
    unchanged reference position and previous contact aggregate. This function
    does not write particle flags, normals, caches or other destination positions.

    frame_number_y is the uint at SceneConstantBuffer byte36, not a frame parity
    inferred here. Instance/definition maps use (buffer, element) keys and 64/104
    byte records; reference and 16-byte group maps use absolute integer indices.
    Missing consumed records are rejected, without inventing an empty resource.
    Native SSA4930..5325 and5745..6142; packed SSA4941..5336 and5757..6154.
    """
    for record, size in ((simulation_parameter, 312), (per_frame, 100), (per_scene, 108)):
        _record(record, size)
    p, reference = _point(position), _point(reference_position)
    _boolean(previous_contact)
    if type(frame_number_y) is not int or not 0 <= frame_number_y <= 0xFFFFFFFF:
        raise ValueError("Cloth frame-number y must be an unsigned 32-bit integer.")
    contact = previous_contact
    packed = struct.unpack_from('<H', simulation_parameter, 214)[0]
    if packed == 0xFFFF:
        return {'position': p, 'contact': contact}

    resource = (struct.unpack_from('<I', per_scene, 48)[0] + (frame_number_y != 0)) & 0xFFFFFFFF
    host_key = (resource if resource < 65000 else 0,
                struct.unpack_from('<I', simulation_parameter, 88)[0])
    host = _entry(static_instances, host_key, 64, 'static-instance')
    start, count = packed & 2047, packed >> 11
    # The shader loads the host even for count0, but does not use its coordinates.
    translation, thickness = None, None
    for reference_index in range(start, start + count):
        if reference_collidables is None or reference_index not in reference_collidables:
            raise ValueError(f"Cloth attached-static collision requires reference entry {reference_index}.")
        group_index = reference_collidables[reference_index]
        if type(group_index) is not int or not 0 <= group_index <= 0xFFFFFFFF:
            raise ValueError("Cloth attached-static references must be unsigned 32-bit integers.")
        if group_index == 0xFFFFFFFF:
            continue
        group = _entry(collider_groups, group_index, 16, 'attached-static group')
        collider_count = struct.unpack_from('<H', group, 2)[0]
        if not collider_count:
            continue
        if translation is None:
            local = _point(struct.unpack_from('<3f', host, 48))
            offset = _point(struct.unpack_from('<3f', per_frame, 0))
            tile_z, tile_x = struct.unpack_from('<2h', host, 12)
            translation = _point((local[0] + offset[0] + tile_x*1000.,
                                  local[1] + offset[1],
                                  local[2] + offset[2] + tile_z*1000.))
            guide = struct.unpack_from('<H', simulation_parameter, 216)[0] == 0xFFFF
            thickness = struct.unpack_from('<f', simulation_parameter, 204)[0] if guide else f32(.01)
            _finite(thickness)
        srv, element_start = struct.unpack_from('<2I', group, 8)
        for index in range(collider_count):
            key = (srv if srv < 65000 else 0, (element_start + index) & 0xFFFFFFFF)
            definition = _entry(collidables, key, 104, 'collidable-definition')
            result = project_static_cloth_collider(
                p, reference, definition, group,
                translation_to_collider_space=translation, collision_thickness=thickness)
            p, contact = result['position'], contact or result['contact']
    return {'position': p, 'contact': contact}


def _guide_collision_cache_mode(particle, parameter, frame, scene, cache):
    for record, size in ((particle, 152), (parameter, 312), (frame, 100), (scene, 108)):
        _record(record, size)
    if cache is not None:
        _record(cache, 40)
    if struct.unpack_from('<H', parameter, 216)[0] != 0xFFFF:
        raise ValueError("This collision selection belongs to guide cloth, not static meshes.")
    flags = struct.unpack_from('<I', particle, 64)[0]
    frame_flags = struct.unpack_from('<I', frame, 32)[0]
    if (struct.unpack_from('<H', scene, 72)[0] == 0xFFFF or
            flags & 0x3C00 and not frame_flags & 0x20000):
        return 'disabled'
    cache_enabled = bool(frame_flags & 0x10 and struct.unpack_from('<H', parameter, 226)[0] != 0xFFFF)
    if not cache_enabled:
        return 'full'
    if cache is None:
        raise ValueError("Guide collision selection requires the resolved ten-uint pre-collision window.")
    count = struct.unpack_from('<I', cache, 20)[0]
    if not flags & 0x20000000:
        return 'rebuild'
    return 'cached' if count < 5 else 'full'


def select_guide_cloth_collision_candidates(
    particle: bytes, simulation_parameter: bytes, per_frame: bytes, per_scene: bytes, *,
    working_flags: int, pre_collision: bytes | None = None,
    reference_collidables: Mapping[int, int] | None = None,
    extra_collidables: Mapping[int, bytes] | None = None,
    collidables: Mapping[tuple[int, int], bytes] | None = None,
) -> dict:
    """Resolve eligible guide colliders before ordered geometry evaluation.

    The caller has passed outer constraint/collision gates. particle is the
    ORIGINAL invocation snapshot; working_flags is the current flag value after
    preceding constraints/prepasses. The shader uses these at different points.
    'disabled' bypasses both animated and attached-static guide contacts; other
    cache modes still allow the later attached-static loop, even with no candidates.

    pre_collision is the 40-byte window at parameter uint148 + particle_index*10
    in buffer parameter ushort226 (>=65000 selects0; FFFF disables it). Candidate
    ordinals are (reference, group, collider); address pairs are (buffer, element).
    Selection does not acquire result/scene records or perform their geometry.
    """
    mode = _guide_collision_cache_mode(particle, simulation_parameter, per_frame, per_scene, pre_collision)
    if type(working_flags) is not int or not 0 <= working_flags <= 0xFFFFFFFF:
        raise ValueError("Cloth working flags must be an unsigned 32-bit integer.")
    candidates = []
    if mode == 'disabled':
        return {'cache_mode': mode, 'candidates': ()}
    frame_flags, flags2 = struct.unpack_from('<2I', per_frame, 32)
    scene_flags = struct.unpack_from('<I', per_scene, 64)[0]
    reference_start, reference_count = struct.unpack_from('<2H', per_scene, 72)
    packed_scene = struct.unpack_from('<I', simulation_parameter, 60)[0]
    own_offset, pac_id = struct.unpack_from('<2I', simulation_parameter, 180)
    own_buffer = struct.unpack_from('<H', simulation_parameter, 238)[0]

    def reference_at(ordinal):
        key = reference_start + ordinal
        if reference_collidables is None or key not in reference_collidables:
            raise ValueError(f"Guide cloth collision requires reference entry {key}.")
        value = reference_collidables[key]
        if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
            raise ValueError("Guide cloth references must be unsigned 32-bit integers.")
        return value

    def eligible_group(group):
        bits, _, other_pac, srv = struct.unpack_from('<2H2I', group)
        other_scene, offset = struct.unpack_from('<2I', group, 28)
        same_scene = other_scene == packed_scene
        same_pac = same_scene and pac_id != 0xFFFFFFFF and pac_id == other_pac
        same_source = own_buffer == srv and own_offset == offset
        if same_source and not (bits & 4 and same_pac):
            return False
        if not bits & 1 and (working_flags & 0x30000 or scene_flags & 1):
            return False
        if bits & 1 and same_scene and frame_flags & 0x20 and scene_flags & 0x200:
            return False
        if bits & 2 and frame_flags & 0x20000000 and not scene_flags & 0x200:
            lra = struct.unpack_from('<e', particle, 88)[0]
            _finite(lra)
            if lra < f32(.3):
                return False
        return True

    def emit(ref_ordinal, group_ordinal, collider_ordinal, group_index, group):
        other_pac, srv, uav = struct.unpack_from('<3I', group, 4)
        other_scene, srv_offset, uav_offset = struct.unpack_from('<3I', group, 28)
        definition_key = (srv if srv < 65000 else 0, (srv_offset + collider_ordinal) & 0xFFFFFFFF)
        definition = _entry(collidables, definition_key, 104, 'collidable-definition')
        requires_same_pac = struct.unpack_from('<I', definition, 100)[0] & 1
        same_source = own_buffer == srv and own_offset == srv_offset
        same_pac = packed_scene == other_scene and pac_id != 0xFFFFFFFF and pac_id == other_pac
        if (not same_pac if requires_same_pac else same_source):
            return
        candidates.append({
            'ordinals': (ref_ordinal, group_ordinal, collider_ordinal), 'group_index': group_index,
            'definition_key': definition_key,
            'result_key': (uav if uav < 65000 else 0, (uav_offset + collider_ordinal) & 0xFFFFFFFF),
            'scene_key': (other_scene >> 16 if other_scene < 65000 << 16 else 0, other_scene & 0xFFFF),
        })

    if mode == 'cached':
        count = struct.unpack_from('<I', pre_collision, 20)[0]
        for slot in range(count):
            token = struct.unpack_from('<I', pre_collision, 24 + 4*slot)[0]
            # A consumed FFFFFFFF token resolves to three zero ordinals in DXIL.
            collider_ordinal, remainder = divmod(token, 1000000) if token != 0xFFFFFFFF else (0, 0)
            group_ordinal, ref_ordinal = divmod(remainder, 1000)
            if ref_ordinal >= reference_count:
                continue
            packed = reference_at(ref_ordinal)
            if packed == 0xFFFFFFFF or group_ordinal >= packed >> 16:
                continue
            group_index = (packed & 0xFFFF) + group_ordinal
            group = _entry(extra_collidables, group_index, 56, 'extra-collidable')
            if collider_ordinal < struct.unpack_from('<H', group, 2)[0] and eligible_group(group):
                emit(ref_ordinal, group_ordinal, collider_ordinal, group_index, group)
    else:
        for ref_ordinal in range(reference_count):
            packed = reference_at(ref_ordinal)
            if packed == 0xFFFFFFFF:
                continue
            start, count = packed & 0xFFFF, packed >> 16
            mask_offset = 0  # SSA4180 resets per reference; skipped groups still advance it.
            for group_ordinal in range(count):
                group_index = start + group_ordinal
                group = _entry(extra_collidables, group_index, 56, 'extra-collidable')
                collider_count = struct.unpack_from('<H', group, 2)[0]
                if eligible_group(group):
                    same_scene = struct.unpack_from('<I', group, 28)[0] == packed_scene
                    bypass_mask = not same_scene or bool(scene_flags & 0x40000 or flags2 & 0x400000)
                    for collider_ordinal in range(collider_count):
                        mask_index = mask_offset + collider_ordinal
                        if not bypass_mask and mask_index <= 95:
                            mask = struct.unpack_from('<I', simulation_parameter, 64 + 4*(mask_index//32))[0]
                            if not mask & (1 << (mask_index % 32)):
                                continue
                        emit(ref_ordinal, group_ordinal, collider_ordinal, group_index, group)
                mask_offset += collider_count
    return {'cache_mode': mode, 'candidates': tuple(candidates)}


def update_guide_cloth_collision_cache(
    particle: bytes, simulation_parameter: bytes, per_frame: bytes, per_scene: bytes, *,
    working_flags: int, evaluated_colliders: Sequence[tuple[int, int, int, float]],
    pre_collision: bytes | None = None,
) -> dict:
    """Record the eligible full scan's ordered response-plane queries.

    Each item is (reference ordinal, group ordinal, collider ordinal, distance).
    Distance is the float32 signed response-plane distance BEFORE projection,
    from the selected target and animated surface, not a volume distance. All
    eligible queries must be supplied, including noncontacts. Geometry and the
    complete contact flag/normal propagation remain caller work.

    Only an enabled cache with the ORIGINAL particle valid bit clear rebuilds.
    Four tokens are stored, but all distances below float32(.03) are counted.
    Unused slots and the other five words remain unchanged. Inputs are immutable.
    """
    mode = _guide_collision_cache_mode(particle, simulation_parameter, per_frame, per_scene, pre_collision)
    if type(working_flags) is not int or not 0 <= working_flags <= 0xFFFFFFFF:
        raise ValueError("Cloth working flags must be an unsigned 32-bit integer.")
    cache = None if pre_collision is None else bytes(pre_collision)
    if mode == 'rebuild':
        cache = bytearray(pre_collision)
        count = 0
        for ref_ordinal, group_ordinal, collider_ordinal, distance in evaluated_colliders:
            if any(type(v) is not int or not 0 <= v <= 0xFFFF
                   for v in (ref_ordinal, group_ordinal, collider_ordinal)):
                raise ValueError("Guide collider ordinals must be unsigned 16-bit integers.")
            if f32(distance) < f32(.03):
                if count < 4:
                    token = (ref_ordinal + 1000*group_ordinal + 1000000*collider_ordinal) & 0xFFFFFFFF
                    struct.pack_into('<I', cache, 24 + 4*count, token)
                count = (count + 1) & 0xFFFFFFFF
        struct.pack_into('<I', cache, 20, count)
        working_flags |= 0x20000000
        cache = bytes(cache)
    return {'flags': working_flags, 'pre_collision': cache, 'cache_mode': mode}


def _cloth_collider_substep_blends(per_frame, global_parameters, push_constants):
    """Resolve the clock gate without consuming collision-only iteration data."""
    for record, size in ((per_frame, 100), (global_parameters, 1216), (push_constants, 44)):
        _record(record, size)
    flags, flags2 = struct.unpack_from('<2I', per_frame, 32)
    if flags & 0xC00:
        return None
    clock = 896 if flags2 & 0x8000 else 864
    fixed = struct.unpack_from('<f', global_parameters, clock)[0]
    _finite(fixed)
    count = struct.unpack_from('<I', global_parameters, clock + 20)[0]
    substep = struct.unpack_from('<I', push_constants, 40)[0]
    variable = bool(flags2 & 0x800)
    if fixed < f32(.0001) and not variable or variable and substep != 0 or substep >= count:
        return None
    reciprocal = f32(1./f32(count))
    previous = 0. if variable else min(1., f32(f32(substep)*reciprocal))
    current = 1. if variable else min(1., f32(f32(substep + 1)*reciprocal))
    return previous, current


def select_cloth_collider_blends(per_frame: bytes, global_parameters: bytes, push_constants: bytes) -> dict | None:
    """Resolve constraint collider timing, before outer collision eligibility.

    Push constants are the 44-byte GlobalPushConstants record, not the scene
    constant buffer. None means the constraint invocation's clock/frame gate
    skips it. This uses substep-count fractions, unlike base animation timing.
    The optional solver-iteration subdivision is enabled by global uint1124==1.
    """
    blends = _cloth_collider_substep_blends(per_frame, global_parameters, push_constants)
    if blends is None:
        return None
    previous, current = blends
    flags, flags2 = struct.unpack_from('<2I', per_frame, 32)
    if struct.unpack_from('<I', global_parameters, 1124)[0] == 1:
        iteration, maximum = struct.unpack_from('<2I', push_constants)
        iterations = min(flags2 & 7, maximum)
        if not iterations:
            raise ValueError("Collider iteration subdivision has no finite result with zero iterations.")
        if struct.unpack_from('<I', global_parameters, 1148)[0]:
            iteration = (iteration + iterations - maximum) & 0xFFFFFFFF
        before = f32((iteration - 1) & 0xFFFFFFFF)
        previous_fraction = f32(before/f32(iterations))
        current_fraction = f32(f32(before + 1.)/f32(iterations))
        interval = f32(current - previous)
        current = f32(previous + f32(current_fraction*interval))
        previous = f32(previous + f32(previous_fraction*interval))
    return {'previous': previous, 'current': current, 'sample': current if flags & 2 else previous}


def sample_cloth_collider_motion(
    reference_position: Sequence[float], collider_result: bytes, *,
    translation_to_collider_space: Sequence[float], sample_blend: float, current_blend: float,
) -> dict:
    """Advect a cloth reference by the decoded two-endpoint collider movement.

    Result56 supplies previous/current endpoints at8/20 and32/44. The reference
    is projected onto the average sampled/current axis WITHOUT segment clamping.
    That axial coordinate determines the movement from sample to current time.
    Returned current centers are in particle space. A collapsed average axis
    has no supported finite result, including for a later sphere surface query.
    """
    _record(collider_result, 56)
    reference, translation = _point(reference_position), _point(translation_to_collider_space)
    _finite(sample_blend, current_blend)
    old_a, new_a, old_b, new_b = (_point(struct.unpack_from('<3f', collider_result, offset))
                                 for offset in (8, 20, 32, 44))

    def interpolate(old, new, ratio):
        return _point(tuple(a + (b - a)*ratio - t for a, b, t in zip(old, new, translation)))

    sample_a = interpolate(old_a, new_a, sample_blend)
    sample_b = interpolate(old_b, new_b, sample_blend)
    current_a = interpolate(old_a, new_a, current_blend)
    current_b = interpolate(old_b, new_b, current_blend)
    midpoint_a = tuple((a + b)*.5 for a, b in zip(sample_a, current_a))
    average_axis = tuple((b + d - a - c)*.5 for a, b, c, d in zip(sample_a, sample_b, current_a, current_b))
    length_squared = _dot(average_axis, average_axis)
    if not math.isfinite(length_squared) or length_squared == 0:
        raise ValueError("Degenerate average collider axis has no supported finite motion result.")
    axial = _dot(_difference(reference, midpoint_a), average_axis)/length_squared
    _finite(axial)
    displacement = _point(tuple(c - a + axial*((d - c) - (b - a))
                                for a, b, c, d in zip(sample_a, sample_b, current_a, current_b)))
    return {'center1': current_a, 'center2': current_b, 'axial_coordinate': axial,
            'displacement': displacement,
            'reference_position': _point(tuple(r + m for r, m in zip(reference, displacement)))}


def apply_guide_cloth_animated_collisions(
    particle: bytes, simulation_parameter: bytes, per_frame: bytes, per_scene: bytes,
    global_parameters: bytes, push_constants: bytes, *,
    working_position: Sequence[float], working_flags: int, pre_collision: bytes | None = None,
    reference_collidables: Mapping[int, int] | None = None,
    extra_collidables: Mapping[int, bytes] | None = None,
    collidables: Mapping[tuple[int, int], bytes] | None = None,
    collidable_results: Mapping[tuple[int, int], bytes] | None = None,
    scene_objects: Mapping[tuple[int, int], bytes] | None = None,
) -> dict:
    """Run guide animated contacts up to the attached-static loop's entry.

    Outer collision eligibility and preceding constraint/prepass work are caller
    responsibilities. particle is the ORIGINAL invocation snapshot; working
    position/flags are the current values. Clocks that skip must bypass this call.
    Selection, endpoint motion, shape response, cache writes and contact flags
    compose here. Group-bit1/bit0 histories, unnormalized normal sum and last
    radii are returned separately for the later attached-static/position merge.
    This does not write the particle buffer or execute later layer/world contacts.
    """
    blends = select_cloth_collider_blends(per_frame, global_parameters, push_constants)
    if blends is None:
        raise ValueError("The skipped constraint invocation must bypass animated collisions.")
    selection = select_guide_cloth_collision_candidates(
        particle, simulation_parameter, per_frame, per_scene, working_flags=working_flags,
        pre_collision=pre_collision, reference_collidables=reference_collidables,
        extra_collidables=extra_collidables, collidables=collidables)
    position = bit1_position = bit0_position = _point(working_position)
    flags = working_flags & ~0x8000
    normal_sum = (0., 0., 0.)
    last_radius = last_bit1_radius = 0.
    contact = bit1_contact = bit0_contact = False
    cache = None if pre_collision is None else bytes(pre_collision)
    if selection['cache_mode'] != 'disabled':
        frame_flags, flags2 = struct.unpack_from('<2I', per_frame, 32)
        scene_flags = struct.unpack_from('<I', per_scene, 64)[0]
        original_flags = struct.unpack_from('<I', particle, 64)[0]
        parameter_flags = struct.unpack_from('<H', simulation_parameter, 212)[0]
        use_working_reference = bool(frame_flags & 0x20 and scene_flags & 0x200)
        reference = position if use_working_reference else _point(struct.unpack_from('<3f', particle, 36))
        flypapering = bool(struct.unpack_from('<I', global_parameters, 1140)[0] and parameter_flags & 8
                          and frame_flags & 0x20000000 and original_flags & 0x4000000
                          and not scene_flags & 0x4000)
        split_targets = flypapering or bool(flags2 & 0x80 and scene_flags & 0x4000)
        queries = []
        for candidate in selection['candidates']:
            group = _entry(extra_collidables, candidate['group_index'], 56, 'extra-collidable')
            definition = _entry(collidables, candidate['definition_key'], 104, 'collidable-definition')
            result = _entry(collidable_results, candidate['result_key'], 56, 'collidable-result')
            other_scene = _entry(scene_objects, candidate['scene_key'], 108, 'scene-object')
            group_flags = struct.unpack_from('<H', group)[0]
            bit1 = bool(group_flags & 1)
            kind = struct.unpack_from('<H', definition, 2)[0]
            if kind not in (1, 3, 5):
                # Unhandled animated shapes return a zero surface/normal: distance0.
                queries.append((*candidate['ordinals'], 0.))
                continue
            host, offset, other = (_point(struct.unpack_from('<3f', data))
                                   for data in (per_scene, per_frame, other_scene))
            host_x, host_z = struct.unpack_from('<2h', per_scene, 12)
            other_x, other_z = struct.unpack_from('<2h', other_scene, 12)
            translation = (host[0] + offset[0] - other[0] + (host_x - other_x)*1000.,
                           host[1] + offset[1] - other[1],
                           host[2] + offset[2] - other[2] + (host_z - other_z)*1000.)
            motion = sample_cloth_collider_motion(
                reference, result, translation_to_collider_space=translation,
                sample_blend=blends['sample'], current_blend=blends['current'])
            thickness = struct.unpack_from('<f', simulation_parameter, 204)[0] if bit1 else f32(.01)
            if group_flags & 2:
                thickness += struct.unpack_from('<e', simulation_parameter, 286)[0]
            radius = struct.unpack_from('<f', result, 4)[0]
            surface, normal = cloth_collider_contact_surface(
                motion['reference_position'], collider_type=kind, center1=motion['center1'],
                center2=motion['center2'], radius=radius, thickness=thickness)
            target = (bit1_position if bit1 else bit0_position) if split_targets else position
            distance = _dot(_difference(target, surface), normal)
            _finite(distance)
            queries.append((*candidate['ordinals'], distance))
            damping = use_working_reference or bool(frame_flags & 0x20000000 and not bit1 and scene_flags & 0x4000)
            response = resolve_cloth_moving_contact(
                target, reference, surface_position=surface, surface_normal=normal,
                collider_displacement=motion['displacement'], apply_tangential_damping=damping)
            if response['contact']:
                position, contact, last_radius = response['position'], True, radius
                if split_targets:
                    if bit1:
                        bit1_position = position
                    else:
                        bit0_position = position
                bit1_contact |= bit1
                bit0_contact |= not bit1
                if not flypapering or bit1:
                    normal_sum = _point(tuple(a + b for a, b in zip(normal_sum, normal)))
                if bit1:
                    flags |= 0x8000
                    last_bit1_radius = radius
                else:
                    flags &= ~0x8000
        recorded = update_guide_cloth_collision_cache(
            particle, simulation_parameter, per_frame, per_scene, working_flags=flags,
            evaluated_colliders=queries, pre_collision=cache)
        flags, cache = recorded['flags'], recorded['pre_collision']
        if bit1_contact and bit0_contact:
            flags |= 0x10000
        if frame_flags & 0x20000000 or not bit0_contact:
            flags &= ~0x30000
    return {'position': position, 'bit1_position': bit1_position, 'bit0_position': bit0_position,
            'normal_sum': normal_sum, 'last_radius': last_radius, 'last_bit1_radius': last_bit1_radius,
            'contact': contact, 'flags': flags, 'pre_collision': cache, 'cache_mode': selection['cache_mode']}


def apply_static_cloth_animated_collisions(
    particle: bytes, simulation_parameter: bytes, per_frame: bytes, per_scene: bytes,
    global_parameters: bytes, push_constants: bytes, *,
    working_position: Sequence[float], working_flags: int, pre_collision: bytes | None = None,
    collidables: Mapping[tuple[int, int], bytes] | None = None,
    collidable_results: Mapping[tuple[int, int], bytes] | None = None,
) -> dict:
    """Run static-mesh animated contacts before the attached-static loop.

    Outer collision gates must have passed. Unlike guide cloth, this branch
    reads a direct collider list, has no animated cache or group filters, uses
    only the frame translation and fixed float32(.01) thickness, and omits
    tangential damping. Skipping its animated list does not skip attached-static
    contacts. Native SSA5326..5745; packed SSA5337..5757.
    """
    blends = select_cloth_collider_blends(per_frame, global_parameters, push_constants)
    if blends is None:
        raise ValueError("The skipped constraint invocation must bypass animated collisions.")
    for record, size in ((particle, 152), (simulation_parameter, 312), (per_scene, 108)):
        _record(record, size)
    if pre_collision is not None:
        _record(pre_collision, 40)
    if struct.unpack_from('<H', simulation_parameter, 216)[0] == 0xFFFF:
        raise ValueError("This collision loop belongs to static meshes, not guide cloth.")
    if type(working_flags) is not int or not 0 <= working_flags <= 0xFFFFFFFF:
        raise ValueError("Cloth working flags must be an unsigned 32-bit integer.")
    position = initial_position = _point(working_position)
    frame_flags, flags2 = struct.unpack_from('<2I', per_frame, 32)
    scene_flags = struct.unpack_from('<I', per_scene, 64)[0]
    original_flags = struct.unpack_from('<I', particle, 64)[0]
    iteration, maximum = struct.unpack_from('<2I', push_constants)
    iterations = min(flags2 & 7, maximum)
    if struct.unpack_from('<I', global_parameters, 1148)[0]:
        iteration = (iteration + iterations - maximum) & 0xFFFFFFFF
    # This penultimate-iteration cleanup is independent of blend subdivision.
    flags = working_flags & (~0x308300 if iteration == (iterations - 1) & 0xFFFFFFFF else ~0x8000)
    normal_sum, last_radius, contact = (0., 0., 0.), 0., False
    srv, uav = struct.unpack_from('<2H', simulation_parameter, 232)
    start, result_start = struct.unpack_from('<2I', simulation_parameter, 160)
    own_srv = struct.unpack_from('<H', simulation_parameter, 238)[0]
    own_start = struct.unpack_from('<I', simulation_parameter, 180)[0]
    count = struct.unpack_from('<H', simulation_parameter, 242)[0]
    if (not original_flags & 0x3C00 or frame_flags & 0x20000) and (srv, start) != (own_srv, own_start):
        for index in range(count):
            if index <= 95:
                mask = struct.unpack_from('<I', simulation_parameter, 64 + 4*(index//32))[0]
                if not mask & (1 << (index % 32)):
                    continue
            definition = _entry(collidables, (srv if srv < 65000 else 0, (start + index) & 0xFFFFFFFF),
                                104, 'collidable-definition')
            result = _entry(collidable_results, (uav if uav < 65000 else 0, (result_start + index) & 0xFFFFFFFF),
                            56, 'collidable-result')
            kind = struct.unpack_from('<H', definition, 2)[0]
            if kind not in (1, 3, 5):
                continue
            reference = initial_position if frame_flags & 0x20 and scene_flags & 0x200 else struct.unpack_from('<3f', particle, 36)
            motion = sample_cloth_collider_motion(
                reference, result, translation_to_collider_space=struct.unpack_from('<3f', per_frame),
                sample_blend=blends['sample'], current_blend=blends['current'])
            radius = struct.unpack_from('<f', result, 4)[0]
            surface, normal = cloth_collider_contact_surface(
                motion['reference_position'], collider_type=kind, center1=motion['center1'],
                center2=motion['center2'], radius=radius, thickness=f32(.01))
            response = resolve_cloth_moving_contact(
                position, reference, surface_position=surface, surface_normal=normal,
                collider_displacement=motion['displacement'], apply_tangential_damping=False)
            if response['contact']:
                position, contact, last_radius = response['position'], True, radius
                normal_sum = _point(tuple(a + b for a, b in zip(normal_sum, normal)))
    return {'position': position, 'bit1_position': initial_position, 'bit0_position': initial_position,
            'normal_sum': normal_sum, 'last_radius': last_radius, 'last_bit1_radius': 0.,
            'contact': contact, 'flags': flags, 'pre_collision': None if pre_collision is None else bytes(pre_collision),
            'cache_mode': None}


def apply_cloth_bone_collisions(
    particle: bytes, simulation_parameter: bytes, per_frame: bytes, per_scene: bytes,
    global_parameters: bytes, push_constants: bytes, *,
    working_position: Sequence[float], working_flags: int, frame_number_y: int,
    pre_collision: bytes | None = None,
    reference_collidables: Mapping[int, int] | None = None,
    extra_collidables: Mapping[int, bytes] | None = None,
    collidables: Mapping[tuple[int, int], bytes] | None = None,
    collidable_results: Mapping[tuple[int, int], bytes] | None = None,
    scene_objects: Mapping[tuple[int, int], bytes] | None = None,
    static_instances: Mapping[tuple[int, int], bytes] | None = None,
    attached_reference_collidables: Mapping[int, int] | None = None,
    attached_collider_groups: Mapping[int, bytes] | None = None,
) -> dict | None:
    """Compose animated/attached-static contacts and the history position blend.

    Preceding constraints/prepasses remain caller work. None skips the entire
    constraint invocation; active=False skips this collision stage only. Active
    results include the contact state for later layer/world contacts, not final
    particle-buffer writes. particle must remain the ORIGINAL invocation
    snapshot. frame_number_y is SceneConstantBuffer uint36, not push data.
    All supplied records remain immutable.
    """
    if _cloth_collider_substep_blends(per_frame, global_parameters, push_constants) is None:
        return None
    for record, size in ((particle, 152), (simulation_parameter, 312), (per_scene, 108)):
        _record(record, size)
    if pre_collision is not None:
        _record(pre_collision, 40)
    if type(working_flags) is not int or not 0 <= working_flags <= 0xFFFFFFFF:
        raise ValueError("Cloth working flags must be an unsigned 32-bit integer.")
    initial_position = _point(working_position)
    original_flags = struct.unpack_from('<I', particle, 64)[0]
    frame_flags, flags2 = struct.unpack_from('<2I', per_frame, 32)
    scene_flags = struct.unpack_from('<I', per_scene, 64)[0]
    active = bool(frame_flags & 0x100 and not original_flags & 0x40)
    if active and struct.unpack_from('<I', push_constants, 12)[0]:
        ground_height = struct.unpack_from('<f', per_frame, 24)[0]
        _finite(ground_height)
        active = ground_height <= -10.
    if not active:
        return {'active': False, 'position': initial_position, 'flags': working_flags & ~0x8000,
                'pre_collision': None if pre_collision is None else bytes(pre_collision)}
    guide = struct.unpack_from('<H', simulation_parameter, 216)[0] == 0xFFFF
    branch = apply_guide_cloth_animated_collisions if guide else apply_static_cloth_animated_collisions
    guide_resources = dict(reference_collidables=reference_collidables, extra_collidables=extra_collidables,
                           scene_objects=scene_objects) if guide else {}
    result = branch(
        particle, simulation_parameter, per_frame, per_scene, global_parameters, push_constants,
        working_position=initial_position, working_flags=working_flags, pre_collision=pre_collision,
        collidables=collidables, collidable_results=collidable_results, **guide_resources)
    if result['cache_mode'] != 'disabled':
        reference = initial_position if frame_flags & 0x20 and scene_flags & 0x200 else struct.unpack_from('<3f', particle, 36)
        result.update(apply_attached_static_cloth_collisions(
            result['position'], reference, simulation_parameter, per_frame, per_scene,
            frame_number_y=frame_number_y, previous_contact=result['contact'], static_instances=static_instances,
            reference_collidables=attached_reference_collidables, collider_groups=attached_collider_groups,
            collidables=collidables))
    parameter_flags = struct.unpack_from('<H', simulation_parameter, 212)[0]
    flypapering = bool(struct.unpack_from('<I', global_parameters, 1140)[0] and parameter_flags & 8
                      and frame_flags & 0x20000000 and original_flags & 0x4000000 and not scene_flags & 0x4000)
    weight = None
    if flypapering:
        lra = struct.unpack_from('<e', particle, 88)[0]
        _finite(lra)
        weight = .5 if lra > f32(.3) else f32(.1)
    elif scene_flags & 0x4000 and flags2 & 0x80:
        weight = .5
    if weight is not None:
        # Deliberately after attached-static response: this can replace that
        # response position while preserving its contact aggregate/metadata.
        result['position'] = _point(tuple(a + weight*(b - a)
                                          for a, b in zip(result['bit1_position'], result['bit0_position'])))
    return {'active': True, **result}
