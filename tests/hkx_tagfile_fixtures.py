"""Hand-assembled Havok 2024.2 tagfiles for HKX tests (no game data).

The builder lays items out with explicit alignments and writes ITEM/PTCH
itself, independently of the codec under test.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


def section(tag: str, flags: int, payload: bytes) -> bytes:
    return struct.pack(">I", (flags << 30) | (len(payload) + 8)) + tag.encode("ascii") + payload


def type_section(names: Sequence[str]) -> bytes:
    strings = b"".join(name.encode("ascii") + b"\0" for name in names)
    strings += b"\xff" * (-len(strings) % 4)
    table = bytes([len(names) + 1]) + b"".join(bytes([index, 0]) for index in range(len(names)))
    table += b"\0" * (-len(table) % 4)
    children = (
        section("MTTP", 1, bytes(8 * (len(names) + 1)))
        + section("TST1", 1, strings)
        + section("TNA1", 1, table)
        + section("TPAD", 1, b"")
    )
    return section("TYPE", 0, children)


def tagfile(
    names: Sequence[str],
    items: Sequence[Tuple[int, int, int, int]],
    data: bytes,
    patches: Optional[Dict[int, List[int]]] = None,
    sdk: bytes = b"20240200",
) -> bytes:
    item_table = bytes(12) + b"".join(
        struct.pack("<3I", (kind << 24) | type_index, offset, count) for kind, type_index, offset, count in items
    )
    index = section("ITEM", 1, item_table)
    if patches is not None:
        table = b"".join(
            struct.pack("<2I", key, len(words)) + struct.pack(f"<{len(words)}I", *words) for key, words in sorted(patches.items())
        )
        index += section("PTCH", 1, table)
    body = section("SDKV", 1, sdk) + section("DATA", 1, data) + type_section(names) + section("INDX", 0, index)
    return section("TAG0", 0, body)


@dataclass
class FixtureItem:
    kind: int
    type_index: int
    count: int
    payload: bytearray
    alignment: int
    patches: List[Tuple[int, int, int]] = field(default_factory=list)  # (local offset, patch type, target item)


def build_patched(names: Sequence[str], items: Sequence[FixtureItem]) -> bytes:
    """Lay ``items`` out in order (ITEM index = position + 1) and write PTCH words."""

    offsets = []
    cursor = 0
    for item in items:
        cursor = (cursor + item.alignment - 1) // item.alignment * item.alignment
        offsets.append(cursor)
        cursor += len(item.payload)
    data = bytearray((cursor + 15) // 16 * 16)
    patches: Dict[int, List[int]] = {}
    for item, offset in zip(items, offsets):
        data[offset : offset + len(item.payload)] = item.payload
        for local, patch_type, target in item.patches:
            struct.pack_into("<Q", data, offset + local, target)
            patches.setdefault(patch_type, []).append(offset + local)
    rows = [(item.kind, item.type_index, offset, item.count) for item, offset in zip(items, offsets)]
    return tagfile(names, rows, bytes(data), {key: sorted(words) for key, words in patches.items()})


PHYSICS_TYPES = (
    "hknpPhysicsSystemData",
    "hkArray",
    "hknpPhysicsSystemData::ExtendedBodyCinfo",
    "hknpConstraintCinfo",
    "hkStringPtr",
    "char",
    "hkRefPtr",
    "hknpLimitedHingeConstraintData",
    "hknpRagdollConstraintData",
)
BODY_NAMES = ("Ragdoll_Bip01 Pelvis", "_Leg_Ragdoll_Bip01 L Thigh", "_Leg_Ragdoll_Bip01 L Calf")


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def hinge_payload(*, bend: Tuple[float, float] = (-1.0, 150.0), friction: float = 2.0, limit_tag: int = 14) -> bytearray:
    payload = bytearray(336)
    struct.pack_into("<HBB", payload, 256, 17, 1, 0)
    struct.pack_into("<f", payload, 264, friction)
    struct.pack_into("<HBB", payload, 272, limit_tag, 1, 0)
    struct.pack_into("<4f", payload, 280, math.radians(bend[0]), math.radians(bend[1]), 1.0, 1.0)
    return payload


def _limit_cache(angle_degrees: float) -> Tuple[float, float]:
    angle = _f32(math.radians(angle_degrees))
    return 1.0 / math.cos(angle), math.tan(angle)


def ragdoll_payload(
    *,
    twist: Tuple[float, float] = (-10.0, 10.0),
    cone: float = 30.0,
    planes: Tuple[float, float] = (60.0, 120.0),
    friction: float = 1.0,
    disabled_planes: bool = False,
) -> bytearray:
    payload = bytearray(464)
    struct.pack_into("<HBB", payload, 304, 17, 1, 0)
    struct.pack_into("<f", payload, 312, friction)
    struct.pack_into("<HBB", payload, 320, 15, 1, 0)
    struct.pack_into("<4f", payload, 328, math.radians(twist[0]), math.radians(twist[1]), 0.8, 1.0)
    struct.pack_into("<HBB", payload, 352, 16, 1, 0)
    secant, tangent = _limit_cache(cone)
    struct.pack_into("<10f", payload, 360, 0.8, 1.0, 0.0, -100.0, math.radians(cone), 19.0 / 9.0, secant, -1.8446726e19, tangent, 0.0)
    struct.pack_into("<HBB", payload, 400, 16, 1, 1)
    if disabled_planes:
        struct.pack_into("<10f", payload, 408, 0.8, 1.0, 0.0, 0.0, math.pi, 19.0 / 9.0, 19.0 / 9.0, -1.8446726e19, 1.8446726e19, 0.0)
    else:
        low_secant, low_tangent = _limit_cache(planes[0])
        high_secant, high_tangent = _limit_cache(planes[1])
        struct.pack_into(
            "<10f", payload, 408, 0.8, 1.0, 0.0, math.radians(planes[0]), math.radians(planes[1]),
            low_secant, high_secant, low_tangent, high_tangent, 0.0,
        )
    return payload


def build_physics_fixture(
    *,
    hinge: Optional[bytearray] = None,
    ragdoll: Optional[bytearray] = None,
    body_names: Sequence[str] = BODY_NAMES,
) -> bytes:
    """A physics system with three bodies: a ragdoll joint (thigh-pelvis) and a hinge (calf-thigh).

    ITEMs: 1 system, 2 bodies, 3 constraint infos, 4 hinge, 5 ragdoll, 6-8 body names, 9-10 joint names.
    """

    system = FixtureItem(0x10, 1, 1, bytearray(136), 8, [(0, 2, 2), (16, 2, 3)])
    bodies = FixtureItem(0x20, 3, 3, bytearray(208 * 3), 16, [(208 * index + 24, 5, 6 + index) for index in range(3)])
    cinfo = bytearray(96)
    struct.pack_into("<I4xI", cinfo, 8, 1, 0)
    struct.pack_into("<I4xI", cinfo, 48 + 8, 2, 1)
    constraints = FixtureItem(0x20, 4, 2, cinfo, 16, [(0, 7, 5), (32, 5, 9), (48, 7, 4), (80, 5, 10)])
    hinge_item = FixtureItem(0x10, 8, 1, hinge if hinge is not None else hinge_payload(), 16)
    ragdoll_item = FixtureItem(0x10, 9, 1, ragdoll if ragdoll is not None else ragdoll_payload(), 16)
    strings = [name.encode("utf-8") + b"\0" for name in (*body_names, "hkRagdollConstraint001", "hkHingeConstraint001")]
    names = [FixtureItem(0x20, 6, len(text), bytearray(text), 2) for text in strings]
    return build_patched(PHYSICS_TYPES, [system, bodies, constraints, hinge_item, ragdoll_item, *names])
