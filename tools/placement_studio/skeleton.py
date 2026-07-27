"""Bone hierarchy and socket world placement.

The `.pab` skeleton gives every bone a 4x4 bind matrix, row-major, with the world translation
in row 3. A socket's world transform is its local offset composed onto its parent bone's bind
matrix, so a socket marker can be drawn at the position the game will actually attach to.

Row-vector convention throughout: a point is a row, and `point * matrix` transforms it. That
matches the on-disk layout, so no transposition happens anywhere in this module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .model import Quat, Socket, Vec3

Matrix = Tuple[float, ...]  # 16 floats, row-major

IDENTITY_MATRIX: Matrix = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)


def multiply(a: Matrix, b: Matrix) -> Matrix:
    """Row-major 4x4 multiply: the result applies `a` then `b`."""

    out = [0.0] * 16
    for row in range(4):
        for column in range(4):
            out[row * 4 + column] = sum(a[row * 4 + k] * b[k * 4 + column] for k in range(4))
    return tuple(out)


def translation_of(matrix: Matrix) -> Vec3:
    return Vec3(matrix[12], matrix[13], matrix[14])


def transform_point(point: Vec3, matrix: Matrix) -> Vec3:
    x, y, z = point.x, point.y, point.z
    return Vec3(
        x * matrix[0] + y * matrix[4] + z * matrix[8] + matrix[12],
        x * matrix[1] + y * matrix[5] + z * matrix[9] + matrix[13],
        x * matrix[2] + y * matrix[6] + z * matrix[10] + matrix[14],
    )


def matrix_from(rotation: Quat, translation: Vec3) -> Matrix:
    """Build a row-major transform from a quaternion (xyzw) and a translation."""

    x, y, z, w = rotation.x, rotation.y, rotation.z, rotation.w
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return (
        1.0 - 2.0 * (yy + zz), 2.0 * (xy + wz), 2.0 * (xz - wy), 0.0,
        2.0 * (xy - wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz + wx), 0.0,
        2.0 * (xz + wy), 2.0 * (yz - wx), 1.0 - 2.0 * (xx + yy), 0.0,
        translation.x, translation.y, translation.z, 1.0,
    )


def invert_rigid(rotation: Quat, translation: Vec3) -> Matrix:
    """Inverse of a rotation-plus-translation frame.

    Not simply the negated translation: it must be rotated by the inverted rotation, otherwise
    the offset lands in the wrong direction.
    """

    inverse = Quat(-rotation.x, -rotation.y, -rotation.z, rotation.w)
    rotated = transform_point(
        Vec3(-translation.x, -translation.y, -translation.z), matrix_from(inverse, Vec3())
    )
    return matrix_from(inverse, rotated)


def world_axis_to_local(axis: Vec3, matrix: Matrix) -> Vec3:
    """Express a world-space axis in the space `matrix` maps *out of*.

    Needed by the rotation gizmo: the drag axis comes from the camera in world space, but a
    socket's rotation is stored in *parent-bone* space, so dragging without this converts to a
    rotation about the wrong axis.

    The bind rotations are orthonormal only to ~1.4e-3 (float noise, worst case `B_Eyeball_L`),
    so the rows are normalized before transposing rather than assuming a clean rotation.
    """

    rows = (
        (matrix[0], matrix[1], matrix[2]),
        (matrix[4], matrix[5], matrix[6]),
        (matrix[8], matrix[9], matrix[10]),
    )
    unit = []
    for row in rows:
        length = math.sqrt(row[0] * row[0] + row[1] * row[1] + row[2] * row[2])
        unit.append(tuple(c / length for c in row) if length > 1e-12 else row)

    # Inverse of an orthonormal rotation is its transpose, so project onto the rows.
    return Vec3(
        axis.x * unit[0][0] + axis.y * unit[0][1] + axis.z * unit[0][2],
        axis.x * unit[1][0] + axis.y * unit[1][1] + axis.z * unit[1][2],
        axis.x * unit[2][0] + axis.y * unit[2][1] + axis.z * unit[2][2],
    )


def world_to_bone(point: Vec3, bone) -> Vec3:
    """A world point expressed in a bone's local frame.

    Sockets store their offset relative to the parent bone, so a point picked off the screen
    has to come back through the bone's bind matrix. Skipping this puts every picked socket
    at the character's origin.
    """

    matrix = bone.bind_matrix
    if len(matrix) != 16:
        return point
    # Rigid inverse: transpose the rotation and rotate the negated translation through it.
    tx, ty, tz = matrix[12], matrix[13], matrix[14]
    dx, dy, dz = point.x - tx, point.y - ty, point.z - tz
    return Vec3(
        dx * matrix[0] + dy * matrix[1] + dz * matrix[2],
        dx * matrix[4] + dy * matrix[5] + dz * matrix[6],
        dx * matrix[8] + dy * matrix[9] + dz * matrix[10],
    )


@dataclass(frozen=True, slots=True)
class BoneNode:
    """One bone, with its world bind transform."""

    index: int
    name: str
    parent_index: int
    bind_matrix: Matrix
    local_position: Vec3

    @property
    def world_position(self) -> Vec3:
        return translation_of(self.bind_matrix)

    @property
    def is_root(self) -> bool:
        return self.parent_index < 0


@dataclass(frozen=True, slots=True)
class PlacedSocket:
    """A socket resolved to a world position via its parent bone."""

    socket: Socket
    bone: Optional[BoneNode]
    world_matrix: Matrix = IDENTITY_MATRIX

    @property
    def name(self) -> str:
        return self.socket.name

    @property
    def world_position(self) -> Vec3:
        return translation_of(self.world_matrix)

    @property
    def anchored(self) -> bool:
        """False when the parent bone is missing or the socket is world-space."""

        return self.bone is not None

    @property
    def offset_from_bone(self) -> float:
        if self.bone is None:
            return 0.0
        return self.world_position.distance_to(self.bone.world_position)


class BoneHierarchy:
    """A parsed skeleton, queryable by name and by parent."""

    __slots__ = ("_bones", "_by_name", "_children", "source", "parsed")

    def __init__(self, bones: Sequence[BoneNode], source: str = "", parsed=None) -> None:
        self._bones = tuple(bones)
        self.source = source
        #: The `cdmw.modding.skeleton_parser.Skeleton` this came from, when it came from a
        #: `.pab`. Animation playback needs the per-bone name hash and local bind transform,
        #: neither of which a `BoneNode` carries.
        self.parsed = parsed
        self._by_name: Dict[str, BoneNode] = {bone.name: bone for bone in self._bones}
        self._children: Dict[int, List[BoneNode]] = {}
        for bone in self._bones:
            self._children.setdefault(bone.parent_index, []).append(bone)

    @classmethod
    def from_pab(cls, data: bytes, source: str = "") -> "BoneHierarchy":
        from cdmw.modding.skeleton_parser import parse_pab

        parsed = parse_pab(data, source)
        bones = [
            BoneNode(
                index=int(bone.index),
                name=str(bone.name),
                parent_index=int(bone.parent_index),
                bind_matrix=tuple(bone.bind_matrix) if len(bone.bind_matrix) == 16 else IDENTITY_MATRIX,
                local_position=Vec3(*bone.position) if len(bone.position) == 3 else Vec3(),
            )
            for bone in parsed.bones
        ]
        return cls(bones, source, parsed)

    def __len__(self) -> int:
        return len(self._bones)

    def __iter__(self):
        return iter(self._bones)

    @property
    def bones(self) -> Tuple[BoneNode, ...]:
        return self._bones

    def by_name(self, name: str) -> Optional[BoneNode]:
        return self._by_name.get(name)

    def children_of(self, index: int) -> List[BoneNode]:
        return list(self._children.get(index, ()))

    def roots(self) -> List[BoneNode]:
        return list(self._children.get(-1, ()))

    def path_to_root(self, name: str) -> List[BoneNode]:
        """Bone chain from a bone up to its root — the 'what drives this socket' answer."""

        chain: List[BoneNode] = []
        current = self._by_name.get(name)
        seen: set[int] = set()
        while current is not None and current.index not in seen:
            seen.add(current.index)
            chain.append(current)
            if current.parent_index < 0 or current.parent_index >= len(self._bones):
                break
            current = self._bones[current.parent_index]
        return chain

    def bounds(self) -> Tuple[Vec3, Vec3]:
        """World-space min/max over bone positions, for framing a view."""

        positions = [bone.world_position for bone in self._bones if any(bone.bind_matrix)]
        if not positions:
            return (Vec3(), Vec3())
        return (
            Vec3(min(p.x for p in positions), min(p.y for p in positions), min(p.z for p in positions)),
            Vec3(max(p.x for p in positions), max(p.y for p in positions), max(p.z for p in positions)),
        )

    # ── socket placement ────────────────────────────────────────────

    def place(self, socket: Socket) -> PlacedSocket:
        """Compose a socket's local offset onto its parent bone's world bind matrix."""

        local = matrix_from(socket.rotation, socket.translation)
        bone = self._by_name.get(socket.parent_bone) if socket.parent_bone else None
        if bone is None:
            # No parent bone: the socket is positioned in world space, as several docking
            # sockets are. Drawing it at its raw translation is correct, not a fallback.
            return PlacedSocket(socket=socket, bone=None, world_matrix=local)
        return PlacedSocket(socket=socket, bone=bone, world_matrix=multiply(local, bone.bind_matrix))

    def place_all(self, sockets: Iterable[Socket]) -> List[PlacedSocket]:
        return [self.place(socket) for socket in sockets]

    def unresolved_parents(self, sockets: Iterable[Socket]) -> List[str]:
        """Socket parent bones this skeleton does not define."""

        missing = {
            socket.parent_bone
            for socket in sockets
            if socket.parent_bone and socket.parent_bone not in self._by_name
        }
        return sorted(missing)
