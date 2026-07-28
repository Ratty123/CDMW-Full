"""Read the numeric values a prefab stores, and render them for people.

The decoder recovers each inline member's raw bytes; this turns them into
something a modder can act on. The interesting one is ``Transform``: 40 bytes
holding ten floats, laid out as

    floats[0:3]  scale
    floats[3:7]  rotation, as a quaternion (x, y, z, w)
    floats[7:10] position

``TiledTransform`` is the same 40 bytes plus a trailing tile index.

That layout was measured, not assumed: the slice at ``floats[3:7]`` is
unit-length in 74,190 of 74,225 transforms sampled from the shipped archives,
scale slots sit at exactly 1.0 about half the time, and a prefab's
``_worldTransform`` and ``_tiledTransform`` agree value for value.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

_TRANSFORM_TYPES = frozenset({"Transform", "TiledTransform"})
_SIGNED = {"int8": "b", "int16": "h", "int32": "i", "int64": "q"}
_UNSIGNED = {"uint8": "B", "uint16": "H", "uint32": "I", "uint64": "Q"}


@dataclass(frozen=True, slots=True)
class Placement:
    """A decoded transform."""

    scale: tuple[float, float, float]
    rotation: tuple[float, float, float, float]
    position: tuple[float, float, float]
    tile: int | None = None

    @property
    def is_identity_rotation(self) -> bool:
        return abs(self.rotation[3] - 1.0) < 1e-6 and all(abs(v) < 1e-6 for v in self.rotation[:3])

    @property
    def is_uniform_scale(self) -> bool:
        return abs(self.scale[0] - self.scale[1]) < 1e-6 and abs(self.scale[1] - self.scale[2]) < 1e-6


def read_placement(raw: bytes) -> Placement | None:
    """Decode a 40- or 44-byte transform, or ``None`` if it is neither."""
    data = bytes(raw or b"")
    if len(data) not in (40, 44):
        return None
    values = struct.unpack_from("<10f", data, 0)
    if any(math.isnan(v) or math.isinf(v) for v in values):
        return None
    tile = struct.unpack_from("<i", data, 40)[0] if len(data) == 44 else None
    return Placement(
        scale=(values[0], values[1], values[2]),
        rotation=(values[3], values[4], values[5], values[6]),
        position=(values[7], values[8], values[9]),
        tile=tile,
    )


def write_placement(placement: Placement) -> bytes:
    """Encode a placement back to its 40- or 44-byte form.

    The inverse of :func:`read_placement`. Fixed size, so a caller can splice
    the result over the original without moving anything around it.
    """
    raw = struct.pack(
        "<10f",
        *placement.scale,
        *placement.rotation,
        *placement.position,
    )
    if placement.tile is None:
        return raw
    return raw + struct.pack("<i", placement.tile)


def degrees_to_rotation(yaw: float, pitch: float, roll: float) -> tuple[float, float, float, float]:
    """Yaw/pitch/roll degrees back to a quaternion (x, y, z, w).

    The inverse of :func:`rotation_degrees` for the same convention. Euler
    angles are ambiguous, so this is for turning user input into a quaternion,
    not for round-tripping one.
    """
    # rotation_degrees extracts pitch about X, yaw about Y and roll about Z;
    # its inverse composes them in the order yaw, then pitch, then roll.
    def axis(index: int, degrees: float) -> tuple[float, float, float, float]:
        half = math.radians(degrees) / 2.0
        parts = [0.0, 0.0, 0.0, math.cos(half)]
        parts[index] = math.sin(half)
        return (parts[0], parts[1], parts[2], parts[3])

    def multiply(
        left: tuple[float, float, float, float], right: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        ax, ay, az, aw = left
        bx, by, bz, bw = right
        return (
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz,
        )

    return multiply(multiply(axis(1, yaw), axis(0, pitch)), axis(2, roll))


def rotation_degrees(
    rotation: tuple[float, float, float, float], *, digits: int = 2
) -> tuple[float, float, float]:
    """Quaternion (x, y, z, w) as yaw/pitch/roll degrees, for reading.

    Euler angles are ambiguous and degenerate at the poles, so a value that
    came from here must never be converted back and written unless the user
    actually edited it -- see :data:`POLE_PITCH_DEGREES`.

    ``digits`` defaults to 2 because that is a readable rendering. An editor
    seeding input boxes wants more, or it quantises a rotation nobody touched.
    """
    x, y, z, w = rotation
    sin_pitch = max(-1.0, min(1.0, 2.0 * (w * x - y * z)))
    pitch = math.asin(sin_pitch)
    yaw = math.atan2(2.0 * (w * y + z * x), 1.0 - 2.0 * (x * x + y * y))
    roll = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (x * x + z * z))
    return tuple(round(math.degrees(v), digits) for v in (yaw, pitch, roll))  # type: ignore[return-value]


# Beyond this pitch, yaw and roll rotate about nearly the same axis and cannot
# be recovered separately: an edit entered in degrees will not come back as the
# angles that were typed. Weapon child sockets sit at exactly pitch 90.
POLE_PITCH_DEGREES = 89.5


def is_near_pole(rotation: tuple[float, float, float, float]) -> bool:
    """Is this orientation one where yaw and roll are not separable?"""
    return abs(rotation_degrees(rotation, digits=6)[1]) > POLE_PITCH_DEGREES


#: What a transform member's numbers are measured against. Established from
#: the shipped archives: ``_worldTransform`` and ``_tiledTransform`` occur only
#: on world objects, 5,228 of each, with a median absolute position component
#: of 61 units and 81.6% above 10 -- world coordinates, not local offsets.
#: ``_offsetTransform`` is rare (26) and named for what it is. Character
#: prefabs carry no transforms at all.
_PLACEMENT_SPACES = {
    "_worldTransform": "world",
    "_tiledTransform": "world",
    "_offsetTransform": "offset",
}


def placement_space(member_name: str) -> str:
    """``"world"``, ``"offset"`` or ``"unknown"`` for a transform member.

    Telling a modder the wrong basis makes every nudge wrong, so an
    unrecognised member says so rather than assuming world.
    """
    return _PLACEMENT_SPACES.get(str(member_name or ""), "unknown")


def _round(values: tuple[float, ...], places: int = 3) -> str:
    return ", ".join(f"{value:g}" for value in (round(v, places) for v in values))


def describe_value(type_name: str, raw: bytes) -> str:
    """A readable rendering of one inline member value."""
    data = bytes(raw or b"")
    name = str(type_name or "")
    if not data:
        return ""
    if name in _TRANSFORM_TYPES:
        placement = read_placement(data)
        if placement is None:
            return data.hex(" ")
        parts = [f"position ({_round(placement.position, 2)})"]
        if not placement.is_identity_rotation:
            parts.append(f"rotation ({_round(rotation_degrees(placement.rotation), 1)})°")
        if placement.scale != (1.0, 1.0, 1.0):
            scale = f"{placement.scale[0]:g}" if placement.is_uniform_scale else _round(placement.scale)
            parts.append(f"scale {scale}")
        if placement.tile:
            parts.append(f"tile {placement.tile}")
        return ", ".join(parts)
    if name == "bool" and len(data) == 1:
        return "yes" if data[0] else "no"
    if name == "float" and len(data) == 4:
        return f"{struct.unpack('<f', data)[0]:g}"
    if name == "double" and len(data) == 8:
        return f"{struct.unpack('<d', data)[0]:g}"
    if name == "float3" and len(data) == 12:
        return f"({_round(struct.unpack('<3f', data))})"
    code = _UNSIGNED.get(name) or _SIGNED.get(name)
    if code and len(data) == struct.calcsize(f"<{code}"):
        return str(struct.unpack(f"<{code}", data)[0])
    if len(data) == 16:
        return data.hex()
    return data.hex(" ")


__all__ = [
    "POLE_PITCH_DEGREES",
    "Placement",
    "degrees_to_rotation",
    "describe_value",
    "is_near_pole",
    "placement_space",
    "read_placement",
    "rotation_degrees",
    "write_placement",
]
