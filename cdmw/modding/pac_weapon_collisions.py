"""Explicit capsule fitting and loose PAC output for single-root weapons.

These are conservative cloth contact shapes, not combat collision geometry or
proof that a live character registers the weapon in its collider references.
"""

from __future__ import annotations

import math
import struct

from .pac_cloth import pac_cloth_lods
from .pac_cloth_guides import decode_pac_cloth_guides
from .pabv_parser import decode_pac_embedded_volumes


def weapon_collision_layout(data):
    from .mesh_parser import _parse_par_sections
    from .pac_cloth_guide_builder import _validate_metadata_tail

    volumes = decode_pac_embedded_volumes(data)
    if (len(volumes.model_bones) != 1 or len(volumes.bone_palette) != 1
            or volumes.bone_palette[0] != volumes.model_bones[0].name_hash
            or not volumes.model_bones[0].name.startswith("B_Weapon_")
            or volumes.model_bones[0].parent_index != -1):
        raise ValueError("Weapon colliders need a decoded single weapon root and matching palette.")
    bone = volumes.model_bones[0]
    for matrix in (bone.bind_matrix, bone.inv_bind_matrix):
        if (any(abs(matrix[i]) > 1e-5 for i in (3, 7, 11)) or abs(matrix[15] - 1) > 1e-5
                or any(abs(sum(matrix[4*i+k] * matrix[4*j+k] for k in range(3)) - (i == j)) > 1e-5
                       for i in range(3) for j in range(3))):
            raise ValueError("Weapon colliders need rigid embedded bone transforms.")
    if any(abs(sum(bone.bind_matrix[4*i+k] * bone.inv_bind_matrix[4*k+j] for k in range(4))
               - (i == j)) > 1e-4 for i in range(4) for j in range(4)):
        raise ValueError("Weapon collider bone transforms must be mutual inverses.")
    metadata = _parse_par_sections(data)[0]
    _validate_metadata_tail(data, volumes.file_end, metadata["offset"] + metadata["size"], volumes.metadata_flags)
    return volumes, metadata


def _point(point, matrix):
    return tuple(sum(point[i] * matrix[4*i+j] for i in range(3)) + matrix[12+j] for j in range(3))


def _dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def _unit(value):
    size = math.hypot(*value)
    if size <= 1e-10:
        raise ValueError("Weapon collider geometry is degenerate.")
    return tuple(v / size for v in value)


def _cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def weapon_capsules(data, *, parts=None, included=None, check_cancelled=lambda: None):
    """Fit each wholly rigid part; a guide-bound ribbon is never an obstacle."""
    volumes, _ = weapon_collision_layout(data)
    bone = volumes.model_bones[0]
    originals = pac_cloth_lods(data)[0].submeshes
    current = originals if parts is None else parts
    if len(current) != len(originals):
        raise ValueError("Weapon collider fitting needs retained part identities.")
    has_guides = decode_pac_cloth_guides(data) is not None
    result = []
    for index, (source, part) in enumerate(zip(originals, current)):
        check_cancelled()
        if included is not None and index not in included:
            continue
        if has_guides and any(data[o+39] & 63 != 63 for o in source.source_vertex_offsets):
            continue
        if not part.vertices or not part.faces:
            continue
        if (len(part.bone_indices) != len(part.vertices) or len(part.bone_weights) != len(part.vertices)
                or any(not slots or len(slots) != len(weights)
                       or any(not math.isfinite(w) or w < 0 for w in weights)
                       or abs(sum(weights) - 1) > 1e-5
                       or any(slot != 0 for slot, weight in zip(slots, weights) if weight > 0)
                       for slots, weights in zip(part.bone_indices, part.bone_weights))):
            raise ValueError("Weapon colliders cannot follow edited or multiple skeletal attachments.")
        if len(part.vertices) > 100_000 or any(not math.isfinite(v) or abs(v) > 1e6 for p in part.vertices for v in p):
            raise ValueError("Weapon collider geometry exceeds the supported bounds.")
        points = [_point(p, bone.inv_bind_matrix) for p in part.vertices]
        center = tuple(sum(p[i] for p in points) / len(points) for i in range(3))
        relative = [tuple(p[i] - center[i] for i in range(3)) for p in points]
        covariance = [[sum(p[i]*p[j] for p in relative) for j in range(3)] for i in range(3)]
        main = max(range(3), key=lambda i: covariance[i][i])
        axis = tuple(float(i == main) for i in range(3))
        for _ in range(24):
            axis = _unit(tuple(_dot(row, axis) for row in covariance))
        along = [_dot(p, axis) for p in relative]
        radius = max(0.002, max(math.hypot(*(p[i] - t*axis[i] for i in range(3)))
                                  for p, t in zip(relative, along)))
        low, high = min(along), max(along)
        if not 1e-5 < high - low <= 1e4 or not 0 < radius <= 10:
            raise ValueError("Weapon collider dimensions are unsupported.")
        seed = tuple(float(i == min(range(3), key=lambda j: abs(axis[j]))) for i in range(3))
        x = _unit(_cross(axis, seed))
        z = _cross(x, axis)
        middle = tuple(center[i] + .5*(low + high)*axis[i] for i in range(3))
        matrix = (*x, 0., *axis, 0., *z, 0., *middle, 1.)
        a = tuple(center[i] + low*axis[i] for i in range(3))
        b = tuple(center[i] + high*axis[i] for i in range(3))
        result.append({"kind": 5, "center1": list(_point(a, bone.bind_matrix)),
                       "center2": list(_point(b, bone.bind_matrix)), "radius": radius,
                       "bone_index": 0, "source_ordinal": index, "matrix": matrix,
                       "height": high-low, "bone_key": bone.name_hash})
    if not 1 <= len(result) <= 64:
        raise ValueError("Weapon collider fitting needs between 1 and 64 wholly rigid parts.")
    return result


def preview_weapon_colliders(data, **kwargs):
    return [{key: value for key, value in row.items() if key in
             {"kind", "center1", "center2", "radius", "bone_index", "source_ordinal"}}
            for row in weapon_capsules(data, **kwargs)]


def preview_weapon_reference(data, *, check_cancelled=lambda: None):
    """Keep bounded rigid geometry alongside its fitted preview contacts."""
    colliders = preview_weapon_colliders(data, check_cancelled=check_cancelled)
    parts = pac_cloth_lods(data)[0].submeshes
    positions, indices = [], []
    for collider in colliders:
        check_cancelled()
        part = parts[collider["source_ordinal"]]
        if len(positions) + len(part.vertices) > 100_000 or len(indices) + 3 * len(part.faces) > 600_000:
            raise ValueError("Weapon reference geometry exceeds the supported preview bounds.")
        start = len(positions)
        for face in part.faces:
            if len(face) != 3 or any(type(i) is not int or not 0 <= i < len(part.vertices) for i in face):
                raise ValueError("Weapon reference has invalid triangle indices.")
            indices.extend(start + i for i in face)
        positions.extend(list(point) for point in part.vertices)
    return {"colliders": tuple(colliders), "mesh": {"positions": positions, "indices": indices},
            "offset": (0., 0., 0.), "rotation": (0., 0., 0.)}


def _place_weapon_point(point, reference):
    x, y, z = point
    a, b, c = (math.radians(v) for v in reference["rotation"])
    y, z = y*math.cos(a)-z*math.sin(a), y*math.sin(a)+z*math.cos(a)
    x, z = x*math.cos(b)+z*math.sin(b), -x*math.sin(b)+z*math.cos(b)
    x, y = x*math.cos(c)-y*math.sin(c), x*math.sin(c)+y*math.cos(c)
    return [v+offset for v, offset in zip((x, y, z), reference["offset"])]


def placed_weapon_reference(reference):
    if reference is None:
        return None
    return {"positions": [_place_weapon_point(p, reference) for p in reference["mesh"]["positions"]],
            "indices": reference["mesh"]["indices"]}


def combined_preview_colliders(data, *, parts=None, included=None, reference=None):
    reason = ""
    try:
        colliders = preview_weapon_colliders(data, parts=parts, included=included)
    except ValueError as exc:
        colliders, reason = [], str(exc)
    source = "rigid_parts" if colliders else ""
    if reference is not None:
        start = max((row["source_ordinal"] for row in colliders), default=-1) + 1
        colliders.extend({**row, "center1": _place_weapon_point(row["center1"], reference),
                          "center2": _place_weapon_point(row["center2"], reference),
                          "source_ordinal": start+i} for i, row in enumerate(reference["colliders"]))
        source = "rigid_parts_and_reference" if source else "reference"
        reason = ""
    return colliders, reason, source


def create_weapon_colliders(data, *, check_cancelled=lambda: None):
    """Append missing other-PAC and same-PAC capsules, preserving original sets."""
    volumes, metadata = weapon_collision_layout(data)
    capsules = weapon_capsules(data, check_cancelled=check_cancelled)
    existing = {data[v.file_offset:v.file_end] for v in volumes.volumes}
    additions = []
    for capsule in capsules:
        # Definition bit 0 selects same-PAC contacts. A separate ordinary
        # definition permits other clothing to consider this weapon's shape.
        for flags in (0, 1):
            record = struct.pack("<I16fBB2fI", capsule["bone_key"], *capsule["matrix"],
                                 1, 5, capsule["radius"], capsule["height"], flags)
            if record not in existing:
                additions.append(record)
                existing.add(record)
    if len(volumes.volumes) + len(additions) > 128:
        raise ValueError("Weapon collider output exceeds the 128-volume limit.")
    block = b"".join(additions)
    if not block:
        return data
    result = bytearray(data[:volumes.file_end] + block + data[volumes.file_end:])
    struct.pack_into("<H", result, volumes.file_offset, len(volumes.volumes) + len(additions))
    struct.pack_into("<2I", result, 16, 0, metadata["size"] + len(block))
    lods = data[metadata["offset"]+4]
    for i in range(2*lods):
        offset = metadata["offset"] + 5 + 4*i
        struct.pack_into("<I", result, offset, struct.unpack_from("<I", data, offset)[0] + len(block))
    check_cancelled()
    result = bytes(result)
    decoded, _ = weapon_collision_layout(result)
    if len(decoded.volumes) != len(volumes.volumes) + len(additions):
        raise ValueError("Weapon collider output failed independent decoding.")
    return result
