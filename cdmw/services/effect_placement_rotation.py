"""The effect placement's rotation arithmetic, in the conventions the rest of the
placement already uses and nothing else.

Everything here is row-vector, row-major: a point is a row and rotates as ``v @ M``,
which is the convention of the archives' matrices (:mod:`effect_character_reference`),
of .NET's ``Matrix4x4``, and of the resident helper's placement. The Euler order is
X, then Y, then Z -- ``M = Rx @ Ry @ Rz`` -- because that is the order the helper's
``ManualLinearMatrix`` and the host's ``_placement_matrix`` compose, so the numbers
in the dialog's boxes are exactly the turn the viewport draws.

The scene the dialog shows can be the character's frame: the item (and the anchor)
are baked through the item rotation ``C`` (item -> scene, ``v @ C``). The helper then
applies the manual placement to the baked vertices, while the game applies the
``_offsetTransform`` in the item's own frame and only then turns the item into the
hand. Matching the two (a uniform scale commutes with every rotation) gives

    scene placement = C^T @ item placement @ C

which is what :func:`euler_item_to_scene` and :func:`euler_scene_to_item` compute.

The quaternion for the game's 40-byte Transform is the same rotation, converted so
that the standard column-convention rotation ``q v q*`` equals ``v @ M``. Whether the
game reads its quaternion in exactly this convention is unproven until seen in game;
the shipped spear's own transform carries a quarter turn about z, so the field is
read, but its sign convention has not been measured.
"""

from __future__ import annotations

import math
from typing import Sequence, Tuple

__all__ = [
    "euler_item_to_scene",
    "euler_scene_to_item",
    "euler_xyz_matrix",
    "euler_xyz_quaternion",
    "matrix_euler_xyz",
    "wrap_degrees",
]

Vec3 = Tuple[float, float, float]
Mat3 = Tuple[float, float, float, float, float, float, float, float, float]
Quat = Tuple[float, float, float, float]


def wrap_degrees(value: float) -> float:
    """`value` wrapped into (-180, 180], so a drag past a half turn reads as the
    short way round rather than as 270."""

    wrapped = math.fmod(float(value), 360.0)
    if wrapped > 180.0:
        wrapped -= 360.0
    elif wrapped <= -180.0:
        wrapped += 360.0
    return wrapped


def _mat_mul3(a: Sequence[float], b: Sequence[float]) -> Mat3:
    return tuple(
        sum(a[row * 3 + k] * b[k * 3 + column] for k in range(3))
        for row in range(3)
        for column in range(3)
    )  # type: ignore[return-value]


def _transpose3(m: Sequence[float]) -> Mat3:
    return (m[0], m[3], m[6], m[1], m[4], m[7], m[2], m[5], m[8])  # type: ignore[return-value]


def euler_xyz_matrix(degrees: Sequence[float]) -> Mat3:
    """The 3x3 (row-major, for row vectors) of the X-then-Y-then-Z turn `degrees`."""

    rx, ry, rz = (math.radians(float(v)) for v in tuple(degrees)[:3])
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    # Rx @ Ry @ Rz, each in .NET's row-vector layout
    return (
        cy * cz, cy * sz, -sy,
        sx * sy * cz - cx * sz, sx * sy * sz + cx * cz, sx * cy,
        cx * sy * cz + sx * sz, cx * sy * sz - sx * cz, cx * cy,
    )


def matrix_euler_xyz(matrix: Sequence[float]) -> Vec3:
    """The X, Y, Z degrees whose :func:`euler_xyz_matrix` is `matrix`. At the gimbal
    poles (y at +-90) x and z share an axis; z is reported as 0 and x carries the turn."""

    m = tuple(float(v) for v in matrix)
    sy = max(-1.0, min(1.0, -m[2]))
    ry = math.asin(sy)
    if abs(m[2]) < 0.999999:
        rx = math.atan2(m[5], m[8])
        rz = math.atan2(m[1], m[0])
    elif sy > 0.0:
        rx = math.atan2(m[3], m[4])
        rz = 0.0
    else:
        rx = math.atan2(-m[3], m[4])
        rz = 0.0
    return (math.degrees(rx), math.degrees(ry), math.degrees(rz))


def euler_item_to_scene(degrees: Sequence[float], item_rotation: Sequence[float] | None) -> Vec3:
    """The item-frame turn as the scene-frame Euler the viewport takes: C^T @ R @ C."""

    if item_rotation is None:
        return tuple(float(v) for v in tuple(degrees)[:3])  # type: ignore[return-value]
    frame = tuple(float(v) for v in item_rotation)
    rotation = euler_xyz_matrix(degrees)
    return matrix_euler_xyz(_mat_mul3(_mat_mul3(_transpose3(frame), rotation), frame))


def euler_scene_to_item(degrees: Sequence[float], item_rotation: Sequence[float] | None) -> Vec3:
    """A scene-frame turn (a rotate drag's result) back in the item's frame: C @ R @ C^T."""

    if item_rotation is None:
        return tuple(float(v) for v in tuple(degrees)[:3])  # type: ignore[return-value]
    frame = tuple(float(v) for v in item_rotation)
    rotation = euler_xyz_matrix(degrees)
    return matrix_euler_xyz(_mat_mul3(_mat_mul3(frame, rotation), _transpose3(frame)))


def euler_xyz_quaternion(degrees: Sequence[float]) -> Quat:
    """`degrees` as the (x, y, z, w) quaternion whose standard column-convention
    rotation equals ``v @ euler_xyz_matrix(degrees)``: qz * qy * qx, x applied first."""

    half_x, half_y, half_z = (math.radians(float(v)) * 0.5 for v in tuple(degrees)[:3])
    qx = (math.sin(half_x), 0.0, 0.0, math.cos(half_x))
    qy = (0.0, math.sin(half_y), 0.0, math.cos(half_y))
    qz = (0.0, 0.0, math.sin(half_z), math.cos(half_z))

    def multiply(a: Quat, b: Quat) -> Quat:
        ax, ay, az, aw = a
        bx, by, bz, bw = b
        return (
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz,
        )

    return multiply(qz, multiply(qy, qx))
