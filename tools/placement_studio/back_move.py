"""Move one kind of item on the back by its own child point, leaving the body point alone.

Every 2H sword hangs from the body point `Spine2_B_SubWeapon_Socket` (the women's
`Spine2_B_MainWeapon_Socket`), which spears, pikes, hammers and tools share, so moving that
point moves all of them. Each item hangs from it by a child point in its own socket file, and
only 2H swords read the 2H sword files (research reference, Section 7.5; Weapon Carry NOTES
item 26). Moving the child point in those files moves the 2H swords alone. Weapon Carry's
Custom Cores do this, and on 2026-11-17 such a Core moved Kliff's 2H sword in game while the
spear stayed put.

The move is made on the item where it hangs, in world space, and turned back into the child
point (row-vector form, as `carry_plan`):

    W  = inverse(C) * S          the item, hung on body point S (in the world) by child C
    W' = W * M                   moved by the world move M
    C' = S * inverse(W')         the child point that hangs it there

`M` is built in the back plane of the item as the game hangs it: the plane's normal is the
item's own y axis (a 2H sword's and a shield's flat side), turned out of the back, and the
plane's left-right axis lies level. A turn is made about the guard, `TWO_HAND_GUARD` up the
blade for a two-hand sword and the item's own origin otherwise. The order follows the
generator's 2H tab: turn seen from behind, tip out, then the three moves along the turned
blade.

Files that hang the same kind of item the same way move with it: the sword's own file and its
sheaths' (`cd_phm_02_sword_0001`, `_0001_in`, `_0015_in`), and a file whose child differs but
hangs the item on the same line (Damiane's `cd_phw_02_sword_0002`). Each gets the same world
move, so they stay in step. Nothing here builds a widget.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from .carry_plan import _close, _inverse, _rounded, rigid_of, weapon_world
from .model import Quat, Socket, Vec3
from .skeleton import Matrix, matrix_from, multiply

#: How far up a two-hand sword's blade its guard sits from the model's origin, in metres: the
#: widest slice of the mesh, which Weapon Carry's 2H tab turns about.
TWO_HAND_GUARD = 0.16

#: The back-plane moves, in the order the generator's 2H tab lists them (labels: Fine-tune).
MOVES: Tuple[str, ...] = ("out", "along", "across", "turn", "tip_out")
#: The moves that turn, by an angle, rather than shift, by a distance.
TURNS = frozenset({"turn", "tip_out"})

#: A plane whose normal leans further than this from the body's front-back axis is not a
#: back plane: the item lies edge-on to the back.
_MIN_FACING = 0.3
#: Two files hang an item on one line when their blades point the same way to within this
#: (cosine) and their origins sit this close to that line, in metres.
_SAME_LINE_COSINE = math.cos(math.radians(1.0))
_SAME_LINE_DISTANCE = 0.01

#: Item files that hang their own way and never move in step, by file stem. The game's
#: `cd_phm_02_sword_0045` hangs its sword on Kliff's 2H sword line, 47 cm lower, and nothing in
#: the files tells it apart from Damiane's `_0002` (12 cm along hers), which does move. Weapon
#: Carry's 2H tab leaves it as the game has it, and Fredric chose the same here (2026-11-17).
HANGS_ITS_OWN_WAY = frozenset({"cd_phm_02_sword_0045"})


def _stem(path: str) -> str:
    return str(path).replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".sockets.xml")


class BackMoveError(ValueError):
    """A back-plane move that cannot be made."""


# ── small vector helpers ─────────────────────────────────────────────

Vec = Tuple[float, float, float]


def _row(m: Matrix, index: int) -> Vec:
    return (m[index * 4], m[index * 4 + 1], m[index * 4 + 2])


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _scale(a: Vec, s: float) -> Vec:
    return (a[0] * s, a[1] * s, a[2] * s)


def _add(*vectors: Vec) -> Vec:
    return tuple(sum(v[i] for v in vectors) for i in range(3))


def _unit(a: Vec) -> Vec:
    length = math.sqrt(_dot(a, a))
    if length <= 1e-9:
        raise BackMoveError("A direction of zero length cannot be followed")
    return _scale(a, 1.0 / length)


def _origin(m: Matrix) -> Vec:
    return (m[12], m[13], m[14])


def _tip(m: Matrix) -> Vec:
    """The item's tip direction in the world: its own -z axis, as the game's blades point."""

    return _unit(_scale(_row(m, 2), -1.0))


def _turn_about(axis: Vec, degrees: float, pivot: Vec) -> Matrix:
    """A world turn of `degrees` about `axis` through `pivot` (right-handed, row-vector)."""

    rotation = matrix_from(Quat.from_axis_angle(Vec3(*axis), degrees), Vec3())
    moved = (
        pivot[0] * rotation[0] + pivot[1] * rotation[4] + pivot[2] * rotation[8],
        pivot[0] * rotation[1] + pivot[1] * rotation[5] + pivot[2] * rotation[9],
        pivot[0] * rotation[2] + pivot[1] * rotation[6] + pivot[2] * rotation[10],
    )
    offset = _add(pivot, _scale(moved, -1.0))
    return rotation[:12] + (offset[0], offset[1], offset[2], 1.0)


def _shift(offset: Vec) -> Matrix:
    return matrix_from(Quat(), Vec3(*offset))


# ── the plane and the move ───────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BackPlane:
    """The plane an item lies in on the back, in the world."""

    #: Out of the back (+z: the character faces -z).
    normal: Vec
    #: In the plane and level, toward the character's left arm (+x).
    across: Vec
    #: In the plane, up.
    up: Vec


def back_plane(world: Matrix) -> BackPlane:
    """The back plane of an item hung at `world`: its own y axis, turned out of the back."""

    normal = _unit(_row(world, 1))
    if abs(normal[2]) < _MIN_FACING:
        raise BackMoveError("The item lies edge-on to the back, so it has no back plane to "
                            "move in")
    if normal[2] < 0.0:
        normal = _scale(normal, -1.0)
    across = _unit(_cross((0.0, 1.0, 0.0), normal))
    return BackPlane(normal, across, _cross(normal, across))


def guard_for(socket_file: str) -> float:
    """How far up the item its turns pivot: a two-hand sword's guard, else its own origin."""

    from .equipment_assets import socket_file_kind

    path = str(socket_file or "").replace("\\", "/").lower()
    if "2_twohandweapon" in path and socket_file_kind(path) == "sword":
        return TWO_HAND_GUARD
    return 0.0


def back_move(world: Matrix, plane: BackPlane, *, out: float = 0.0, along: float = 0.0,
              across: float = 0.0, turn: float = 0.0, tip_out: float = 0.0,
              guard: float = 0.0) -> Matrix:
    """The world move `M` (`W' = W * M`) for an item hung at `world`.

    Distances are in metres, angles in degrees:

    * `out` along the plane's normal, out of the back;
    * `along` up the blade, toward the pommel (negative lowers the item);
    * `across` across the blade in the plane, toward the left arm;
    * `turn` about the normal at the guard, clockwise as seen from behind;
    * `tip_out` about the line across the blade at the guard, the tip out of the back.

    The turns come first and the moves follow the turned blade, as on the generator's 2H tab.
    """

    pivot = _add(_origin(world), _scale(_tip(world), guard))
    move: Matrix = _shift((0.0, 0.0, 0.0))
    current = world
    if turn:
        # Right-handed about +z, which a viewer behind the character (+x to their left)
        # sees turn clockwise.
        step = _turn_about(plane.normal, turn, pivot)
        move, current = multiply(move, step), multiply(current, step)
    if tip_out:
        axis = _cross(_tip(current), plane.normal)
        if math.sqrt(_dot(axis, axis)) <= 1e-6:
            raise BackMoveError("The item points straight out of the back, so it cannot tip "
                                "further out")
        step = _turn_about(_unit(axis), tip_out, pivot)
        move, current = multiply(move, step), multiply(current, step)
    tip = _tip(current)
    sideways = _cross(plane.normal, tip)
    if math.sqrt(_dot(sideways, sideways)) <= 1e-6:
        sideways = plane.across
    sideways = _unit(sideways)
    if _dot(sideways, plane.across) < 0.0:
        sideways = _scale(sideways, -1.0)
    offset = _add(_scale(plane.normal, out), _scale(tip, -along), _scale(sideways, across))
    if any(offset):
        move = multiply(move, _shift(offset))
    return move


def moved_child(hierarchy, body_socket: Socket, child: Socket, move: Matrix) -> Socket:
    """The child point that hangs the item at `W * move` from the same body point."""

    world = weapon_world(hierarchy, body_socket, child)
    target = multiply(world, move)
    socket_world = multiply(weapon_world(hierarchy, body_socket,
                                         Socket("", rotation=Quat(), translation=Vec3())),
                            _inverse(target))
    rotation, translation = rigid_of(socket_world)
    return Socket(child.name, parent_bone=child.parent_bone, rotation=_rounded(rotation),
                  translation=_rounded(translation), ui_visible=child.ui_visible,
                  source_file=child.source_file)


# ── files that move together ─────────────────────────────────────────


def _same_line(a: Matrix, b: Matrix) -> bool:
    tip_a, tip_b = _tip(a), _tip(b)
    if _dot(tip_a, tip_b) < _SAME_LINE_COSINE:
        return False
    gap = _add(_origin(b), _scale(_origin(a), -1.0))
    off_line = _add(gap, _scale(tip_a, -_dot(gap, tip_a)))
    return math.sqrt(_dot(off_line, off_line)) <= _SAME_LINE_DISTANCE


def _hands(path: str) -> str:
    lowered = path.lower()
    return "2h" if "2_twohandweapon" in lowered else "1h" if "1_onehandweapon" in lowered else ""


@dataclass(frozen=True, slots=True)
class InStep:
    """Another item file that moves with the selected one."""

    socket_file: str
    child: Socket
    #: `same`: it holds the same child point; `line`: its own, hanging the item on that line.
    how: str


def in_step_files(weapons, edits, socket_file: str, child_name: str, *, hierarchy=None,
                  body_socket: Optional[Socket] = None) -> List[InStep]:
    """The other loaded files that hang this kind of item the way `socket_file` does.

    A file qualifies when it is the same kind of item in the same hands folder (`sword` under
    `2_twohandweapon`), defines `child_name` on the same bone, and either holds the same value
    now or, given the rig and the body point, hangs the item on the same line in the world.
    So Kliff's sword file takes its two sheath files along and Damiane's sword file her other
    one, while a spear file holding the same child point is another kind and stays. A file in
    `HANGS_ITS_OWN_WAY` neither comes along nor takes others along.
    """

    from .equipment_assets import socket_file_kind

    def current(path: str, fallback: Optional[Socket]) -> Optional[Socket]:
        found = edits.socket(path, child_name) if edits is not None else None
        return found or fallback

    by_path = {}
    for weapon in weapons:
        by_path.setdefault(weapon.game_path, weapon)
    own_weapon = by_path.get(socket_file)
    own = current(socket_file, own_weapon.sockets.get(child_name) if own_weapon else None)
    if own is None or _stem(socket_file) in HANGS_ITS_OWN_WAY:
        return []
    kind, hands = socket_file_kind(socket_file), _hands(socket_file)
    own_world = None
    if hierarchy is not None and body_socket is not None:
        own_world = weapon_world(hierarchy, body_socket, own)
    editable = set(edits.paths) if edits is not None else set(by_path)
    out: List[InStep] = []
    for path in sorted(by_path):
        if (path == socket_file or path not in editable or socket_file_kind(path) != kind
                or _hands(path) != hands or _stem(path) in HANGS_ITS_OWN_WAY):
            continue
        other = current(path, by_path[path].sockets.get(child_name))
        if other is None or other.parent_bone != own.parent_bone:
            continue
        if _close(other, own):
            out.append(InStep(path, other, "same"))
        elif own_world is not None and _same_line(
                own_world, weapon_world(hierarchy, body_socket, other)):
            out.append(InStep(path, other, "line"))
    return out


@dataclass(frozen=True, slots=True)
class BackMoveTarget:
    """What On the back acts on: an item's own point and the body point it hangs from."""

    socket_file: str
    child: Socket
    #: The game's value of the child point, which the back plane is read from.
    game_child: Optional[Socket]
    body_socket: Socket
    in_step: Tuple[InStep, ...] = ()


@dataclass(frozen=True, slots=True)
class BackMovePlan:
    """The new child point for each file a back-plane move writes, the selected one first."""

    sockets: Tuple[Tuple[str, Socket], ...]

    @property
    def files(self) -> Tuple[str, ...]:
        return tuple(path for path, _socket in self.sockets)


def plan_back_move(hierarchy, body_socket: Socket, socket_file: str, child: Socket,
                   game_child: Optional[Socket] = None, *, key: str, amount: float,
                   in_step: Sequence[InStep] = ()) -> BackMovePlan:
    """One step of one back-plane move, for `socket_file` and every file in step with it.

    `key` is one of `MOVES`; `amount` is metres, or degrees for `TURNS`. The plane is read
    from the item as the game hangs it (`game_child`), so steps do not tilt it as they go.
    """

    if key not in MOVES:
        raise BackMoveError(f"Not a back move: {key}")
    if hierarchy is None:
        raise BackMoveError("This character has no skeleton to measure the back on")
    plane = back_plane(weapon_world(hierarchy, body_socket, game_child or child))
    sockets = []
    for path, current in [(socket_file, child)] + [(o.socket_file, o.child) for o in in_step]:
        # Each file turns about its own guard, as the generator's 2H tab does: Damiane's
        # `_0002` swords sit 12 cm along the same line, and their guard with them.
        world = weapon_world(hierarchy, body_socket, current)
        move = back_move(world, plane, guard=guard_for(path), **{key: amount})
        sockets.append((path, moved_child(hierarchy, body_socket, current, move)))
    return BackMovePlan(tuple(sockets))


def labels(paths: Iterable[str]) -> List[str]:
    """`cd_phm_02_sword_0001_in` for each file, for a note that names them."""

    return [str(path).replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".sockets.xml")
            for path in paths]
