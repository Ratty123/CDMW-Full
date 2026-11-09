"""Carry a weapon somewhere else, for either body: the rows, the hand, and a mirrored carry.

The descriptor row decides where a weapon hangs (research reference, Section 7.5), and each
body has its own: Kliff reads `phm_description_player_kliff.xml`, and Damiane and female Kliff
(Character Creator, Heroine of Pywel) read `phw_description_player_001.xml` with the `phw_01`
and `phw_damian_01` body socket files. Damiane's rows hold some weapons in the left hand, so
Kliff's right-handed carry looks wrong on her. What worked in game is Kliff's carry mirrored:
a new body attach point solved so the weapon, hung by the same child socket, lands where it
would have landed on the other side of the body,

    W' = S * W * S,  W = inverse(child) * socket * bone   (row-vector form)

with S the reflection across the skeleton's left-right axis. The solve runs per body socket
file, since the files' sockets differ.

`plan_mirrored_move` builds on `move_operation.plan_move`: the move is planned to the spot the
user picked, then re-aimed at the mirrored attach point, which the same operation creates.
Nothing here builds a widget.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Dict, Iterable, List, Optional, Tuple

from .documents import is_body_socket_file
from .model import Quat, Socket, Vec3
from .skeleton import Matrix, invert_rigid, matrix_from, multiply

#: What the user calls each body in the tab.
BODY_LABELS: Dict[str, str] = {
    "1_phm": "Kliff",
    "2_phw": "Damiane and female Kliff",
}

#: Largest mismatch, in metres or matrix units, a solved socket may leave against `S W S`.
_SOLVE_TOLERANCE = 1e-5
#: How far a case's child socket may differ from the weapon's before a mirror of the weapon's
#: placement is called approximate for the case.
_CHILD_MATCH = 1e-3


class MirrorError(ValueError):
    """A mirrored carry that cannot be solved."""


def body_label(model: str) -> str:
    return BODY_LABELS.get(model, model)


def held_hand(part) -> str:
    """`left` or `right`: the hand the row holds the item in, or "" when it names neither."""

    socket = (getattr(part, "out_socket", "") or "").lower()
    if socket.startswith("lhand"):
        return "left"
    if socket.startswith("rhand"):
        return "right"
    return ""


def mirror_name(name: str) -> str:
    """`Pelvis_L_Socket` <-> `Pelvis_R_Socket`; a centre name is its own mirror."""

    from tools.paa_motion.edit import mirror_partner_name

    return mirror_partner_name(name)


def mirrorable(socket_name: str) -> bool:
    """Whether a spot has another side: the back's centre and the small of the back do not."""

    return mirror_name(socket_name) != socket_name


def free_mirrored_name(source: str, taken: Iterable[str]) -> str:
    """The mirrored spot's name, or a new one beside it when that name is already in use.

    `Pelvis_L_Socket` mirrors to `Pelvis_R_Socket`, which other weapons already hang from, so
    the carry gets `Pelvis_R_Carry_Socket` of its own (and `_2`, `_3` after that), the way the
    shipped mod gave female Kliff's two-hand sword `Pelvis_R_SubWeapon_Socket`.
    """

    used = set(taken)
    wanted = mirror_name(source)
    if wanted not in used:
        return wanted
    stem = wanted[: -len("_Socket")] if wanted.endswith("_Socket") else wanted
    for number in range(1, 100):
        candidate = f"{stem}_Carry{'' if number == 1 else f'_{number}'}_Socket"
        if candidate not in used:
            return candidate
    raise MirrorError(f"No free name for a mirror of {source}")


# ── the solve ────────────────────────────────────────────────────────


def mirror_axis(hierarchy) -> int:
    """The world axis left and right differ along, read off the bind pose."""

    spread = [0.0, 0.0, 0.0]
    for bone in hierarchy.bones:
        partner = hierarchy.by_name(mirror_name(bone.name))
        if partner is None or partner.name == bone.name:
            continue
        a, b = bone.bind_matrix, partner.bind_matrix
        for axis in range(3):
            spread[axis] += abs(a[12 + axis] - b[12 + axis])
    if not any(spread):
        raise MirrorError("The skeleton has no left and right bones to mirror across")
    return max(range(3), key=lambda axis: spread[axis])


def _reflection(axis: int) -> Matrix:
    return tuple(-1.0 if i == axis * 5 else (1.0 if i % 5 == 0 else 0.0) for i in range(16))


def _inverse(m: Matrix) -> Matrix:
    """Inverse of a rigid row-vector transform: transpose the rotation, rotate the offset back."""

    r = (m[0], m[4], m[8], m[1], m[5], m[9], m[2], m[6], m[10])
    t = (m[12], m[13], m[14])
    return (
        r[0], r[1], r[2], 0.0,
        r[3], r[4], r[5], 0.0,
        r[6], r[7], r[8], 0.0,
        -(t[0] * r[0] + t[1] * r[3] + t[2] * r[6]),
        -(t[0] * r[1] + t[1] * r[4] + t[2] * r[7]),
        -(t[0] * r[2] + t[1] * r[5] + t[2] * r[8]),
        1.0,
    )


def rigid_of(m: Matrix) -> Tuple[Quat, Vec3]:
    """The quaternion and translation `skeleton.matrix_from` would build `m` from."""

    # matrix_from stores the column-vector rotation M transposed: M[i][j] = m[j * 4 + i].
    m00, m11, m22 = m[0], m[5], m[10]
    m21, m12 = m[6], m[9]
    m02, m20 = m[8], m[2]
    m10, m01 = m[1], m[4]
    trace = m00 + m11 + m22
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        w, x, y, z = 0.25 * s, (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        w, x, y, z = (m21 - m12) / s, 0.25 * s, (m01 + m10) / s, (m02 + m20) / s
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        w, x, y, z = (m02 - m20) / s, (m01 + m10) / s, 0.25 * s, (m12 + m21) / s
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
        w, x, y, z = (m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, 0.25 * s
    if w < 0.0:
        w, x, y, z = -w, -x, -y, -z
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    return Quat(x / norm, y / norm, z / norm, w / norm), Vec3(m[12], m[13], m[14])


def _bone_matrix(hierarchy, name: str) -> Matrix:
    bone = hierarchy.by_name(name) if name else None
    if bone is None:
        raise MirrorError(f"The skeleton has no bone {name or '(none)'}")
    return bone.bind_matrix


def weapon_world(hierarchy, socket: Socket, child: Socket) -> Matrix:
    """Where an item hung on `socket` by `child` sits on the bind pose."""

    local = matrix_from(socket.rotation, socket.translation)
    return multiply(multiply(invert_rigid(child.rotation, child.translation), local),
                    _bone_matrix(hierarchy, socket.parent_bone))


@dataclass(frozen=True, slots=True)
class MirroredSocket:
    """A solved attach point for one body socket file."""

    socket_file: str
    socket: Socket
    #: The spot it mirrors, in the same file.
    source: str
    #: Largest difference between where the item lands and the mirrored target.
    error: float


def solve_mirrored_socket(hierarchy, source: Socket, child: Socket, *, name: str,
                          socket_file: str = "") -> MirroredSocket:
    """The socket on the mirror partner of `source`'s bone that puts the item at `S W S`.

    The partner is found by name (`B_WeaponIn_R_00` <-> `B_WeaponIn_L_00`); a centre bone is
    its own partner. Checked by placing the item through the solved socket again.
    """

    axis = mirror_axis(hierarchy)
    reflect = _reflection(axis)
    world = weapon_world(hierarchy, source, child)
    target = multiply(multiply(reflect, world), reflect)
    partner = mirror_name(source.parent_bone)
    bone = partner if hierarchy.by_name(partner) is not None else source.parent_bone
    local = multiply(multiply(matrix_from(child.rotation, child.translation), target),
                     _inverse(_bone_matrix(hierarchy, bone)))
    rotation, translation = rigid_of(local)
    solved = Socket(name=name, parent_bone=bone, rotation=_rounded(rotation),
                    translation=_rounded(translation), source_file=socket_file)
    error = max(abs(a - b) for a, b in zip(weapon_world(hierarchy, solved, child), target))
    if error > 1e-3:
        raise MirrorError(f"The mirrored {source.name} could not be solved (off by {error:.4f})")
    return MirroredSocket(socket_file, solved, source.name, error)


def _rounded(value):
    """To the six decimals the files store, which keeps a written socket equal to its solve."""

    if isinstance(value, Quat):
        q = Quat(*(round(v, 6) for v in (value.x, value.y, value.z, value.w)))
        return Quat(*(0.0 if abs(v) < 5e-7 else v for v in (q.x, q.y, q.z, q.w)))
    return Vec3(*(0.0 if abs(v) < 5e-7 else round(v, 6) for v in (value.x, value.y, value.z)))


# ── the plan ─────────────────────────────────────────────────────────


def body_socket_files(edits, model: str) -> List[str]:
    """This body's socket files in the edit session: one for Kliff, two for Damiane."""

    from .resolver import model_of

    return sorted(path for path in edits.paths
                  if is_body_socket_file(path) and model_of(path) == model)


def _child_of(edits, route) -> Optional[Socket]:
    """The child socket a route will hang its row by, as the move would leave it."""

    if route.creates_socket:
        template = route.template
        return Socket(route.proposed_child, rotation=template.rotation or Quat(),
                      translation=template.translation or Vec3())
    if route.socket_file and route.proposed_child:
        return edits.socket(route.socket_file, route.proposed_child)
    return None


def _close(a: Socket, b: Socket) -> bool:
    """The same child transform, allowing for the two signs of one quaternion."""

    ta, tb = a.translation, b.translation
    if max(abs(ta.x - tb.x), abs(ta.y - tb.y), abs(ta.z - tb.z)) > _CHILD_MATCH:
        return False
    qa = (a.rotation.x, a.rotation.y, a.rotation.z, a.rotation.w)
    qb = (b.rotation.x, b.rotation.y, b.rotation.z, b.rotation.w)
    return min(max(abs(x - y) for x, y in zip(qa, qb)),
               max(abs(x + y) for x, y in zip(qa, qb))) <= _CHILD_MATCH


def plan_mirrored_move(session, edits, request, *, hierarchy=None):
    """Plan `request` to its destination, then mirror it to the other side of the body.

    The returned `MovePlan` routes every row to a new attach point, created by the same
    operation in each of this body's socket files that defines the picked spot, so the weapon
    lands as it would on the picked spot, reflected across the body. The child sockets are the
    ones the plain move would use.
    """

    from .move_operation import _state_rows, plan_move

    source = request.destination_socket
    if not source or not mirrorable(source):
        raise MirrorError(f"{source or 'That spot'} has no other side to mirror to")
    base = plan_move(session, edits, request)
    if base.blocked:
        return base
    hierarchy = hierarchy if hierarchy is not None else session.hierarchy
    if hierarchy is None:
        raise MirrorError("This character has no skeleton to mirror across")
    primary = next((route for route in base.routes if route.is_primary), None)
    child = _child_of(edits, primary) if primary is not None else None
    if child is None:
        raise MirrorError("The weapon has no child socket for that spot, so its mirror "
                          "cannot be solved")

    files = [path for path in body_socket_files(edits, session.model)
             if edits.socket(path, source) is not None]
    if not files:
        raise MirrorError(f"No body socket file of this character defines {source}")
    taken = set()
    for path in files:
        taken.update(edits.sockets_in(path))
    name = free_mirrored_name(source, taken)
    solved = [solve_mirrored_socket(hierarchy, edits.socket(path, source), child, name=name,
                                    socket_file=path) for path in files]

    confirmations = list(base.confirmations)
    for route in base.routes:
        if route is primary:
            continue
        other = _child_of(edits, route)
        if other is not None and not _close(other, child):
            confirmations.append(
                f"{route.part_name} hangs by its own {route.proposed_child}, so its mirrored "
                f"place follows the weapon's and may sit slightly off; check it in the view")
    confirmations.append(
        "A mirrored carry turns the item rather than flipping it, so an edge or a guard that "
        "faced outward on one side may face inward on the other; check it in the view")

    routes = tuple(replace(route, destination_socket=name) for route in base.routes)
    mirrored_request = replace(request, destination_socket=name)
    return replace(
        base,
        request=mirrored_request,
        routes=routes,
        states=_state_rows(session, edits, request.unit, routes),
        new_body_sockets=tuple((m.socket_file, m.socket) for m in solved),
        mirror_of=source,
        confirmations=tuple(dict.fromkeys(confirmations)),
        placement_changes=True,
    )


def describe_rows(unit, edits) -> List[Tuple[str, Dict[str, str]]]:
    """`(role, attributes)` for the weapon row and each linked row, as this session has them."""

    rows: List[Tuple[str, Dict[str, str]]] = []
    order = [(unit.primary_part, unit.primary_source_file, "Weapon")]
    order += [(link.part_name, link.source_file, link.role.capitalize())
              for link in unit.linked_parts]
    for part_name, source_file, role in order:
        part = edits.part(source_file, part_name) or edits.original_part(source_file, part_name)
        values = {
            "Row": part_name,
            "Put away on": getattr(part, "in_socket", "") or "",
            "Put-away child": getattr(part, "in_child_socket", "") or "",
            "Held in": getattr(part, "out_socket", "") or "",
            "Held child": getattr(part, "out_child_socket", "") or "",
            "Case": getattr(part, "weapon_case_part", "") or "",
            "File": source_file,
        }
        rows.append((role, values))
    return rows

