"""Placement domain types: transforms, sockets, descriptor rows, bindings.

Values keep the game's on-disk formatting (space-separated, six decimals) so a parse/format
cycle is lossless. Rotations are quaternions in `x y z w` order — identity is
`0.000000 0.000000 0.000000 1.000000`.

The tuning guide is explicit that quaternions must not be hand-edited, so the euler helpers
here exist to give the UI a degrees-based surface with conversion in one reviewed place.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Sequence, Tuple

_PRECISION = 6

# Translation step sizes the tuning guide sanctions, smallest first.
NUDGE_TINY = 0.010
NUDGE_NORMAL = 0.020
NUDGE_LARGE = 0.050
NUDGE_RISKY = 0.100
SAFE_NUDGES: Tuple[float, ...] = (NUDGE_TINY, NUDGE_NORMAL, NUDGE_LARGE)


class TransformError(ValueError):
    """Raised when a transform value is malformed or cannot be represented."""


def format_scalar(value: float) -> str:
    return f"{value:.{_PRECISION}f}"


def format_values(values: Iterable[float]) -> str:
    return " ".join(format_scalar(float(v)) for v in values)


def parse_values(text: str, *, expected: int) -> Tuple[float, ...]:
    parts = str(text or "").split()
    if len(parts) != expected:
        raise TransformError(f"Expected {expected} values, got {len(parts)}: {text!r}")
    try:
        return tuple(float(p) for p in parts)
    except ValueError as exc:
        raise TransformError(f"Non-numeric transform value: {text!r}") from exc


@dataclass(frozen=True, slots=True)
class Vec3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    @classmethod
    def parse(cls, text: str) -> "Vec3":
        return cls(*parse_values(text, expected=3))

    def format(self) -> str:
        return format_values((self.x, self.y, self.z))

    def offset(self, dx: float = 0.0, dy: float = 0.0, dz: float = 0.0) -> "Vec3":
        return Vec3(self.x + dx, self.y + dy, self.z + dz)

    def distance_to(self, other: "Vec3") -> float:
        return math.dist((self.x, self.y, self.z), (other.x, other.y, other.z))


@dataclass(frozen=True, slots=True)
class Quat:
    """Rotation quaternion in `x y z w` order."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: float = 1.0

    @classmethod
    def parse(cls, text: str) -> "Quat":
        return cls(*parse_values(text, expected=4))

    def format(self) -> str:
        return format_values((self.x, self.y, self.z, self.w))

    @property
    def norm(self) -> float:
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z + self.w * self.w)

    def is_normalized(self, *, tolerance: float = 1e-4) -> bool:
        return abs(self.norm - 1.0) <= tolerance

    def normalized(self) -> "Quat":
        length = self.norm
        if length <= 1e-12:
            raise TransformError("Cannot normalize a zero-length quaternion")
        return Quat(self.x / length, self.y / length, self.z / length, self.w / length)

    @classmethod
    def from_axis_angle(cls, axis: "Vec3", degrees: float) -> "Quat":
        """Rotation of `degrees` about `axis`. Axis need not be normalized."""

        length = math.sqrt(axis.x * axis.x + axis.y * axis.y + axis.z * axis.z)
        if length <= 1e-12:
            return cls()
        half = math.radians(degrees) / 2.0
        s = math.sin(half) / length
        return cls(axis.x * s, axis.y * s, axis.z * s, math.cos(half))

    def then(self, other: "Quat") -> "Quat":
        """Apply this rotation, then `other`. Composition in quaternion space.

        A gizmo must compose here rather than via euler: at pitch +/-90 euler cannot represent
        the result, which is exactly where several weapon child sockets sit.
        """

        return Quat(
            other.w * self.x + other.x * self.w + other.y * self.z - other.z * self.y,
            other.w * self.y - other.x * self.z + other.y * self.w + other.z * self.x,
            other.w * self.z + other.x * self.y - other.y * self.x + other.z * self.w,
            other.w * self.w - other.x * self.x - other.y * self.y - other.z * self.z,
        ).normalized()

    def angle_to(self, other: "Quat") -> float:
        """Shortest rotation angle to another quaternion, in degrees.

        Always well defined, unlike a difference of euler angles: at pitch +/-90 two rotations
        that are genuinely far apart report identical euler triples, so any delta computed from
        euler reads as zero. This is the number to show a user.
        """

        dot = abs(self.x * other.x + self.y * other.y + self.z * other.z + self.w * other.w)
        return math.degrees(2.0 * math.acos(max(-1.0, min(1.0, dot))))

    @property
    def near_gimbal_lock(self) -> bool:
        """True when euler decomposition is degenerate (pitch at +/-90).

        `Basic_ChildSocket` sits exactly here on every sword, so this is the common case, not a
        corner case: the euler fields cannot round-trip and must not be presented as if they can.
        """

        sinp = 2.0 * (self.w * self.y - self.z * self.x)
        return abs(abs(sinp) - 1.0) < 1e-3

    def to_euler_degrees(self) -> Tuple[float, float, float]:
        """Intrinsic X-Y-Z euler angles in degrees."""

        x, y, z, w = self.x, self.y, self.z, self.w
        sinr_cosp = 2.0 * (w * x + y * z)
        cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
        roll = math.atan2(sinr_cosp, cosr_cosp)

        sinp = 2.0 * (w * y - z * x)
        pitch = math.copysign(math.pi / 2.0, sinp) if abs(sinp) >= 1.0 else math.asin(sinp)

        siny_cosp = 2.0 * (w * z + x * y)
        cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
        yaw = math.atan2(siny_cosp, cosy_cosp)
        return (math.degrees(roll), math.degrees(pitch), math.degrees(yaw))

    @classmethod
    def from_euler_degrees(cls, roll: float, pitch: float, yaw: float) -> "Quat":
        cr, sr = math.cos(math.radians(roll) / 2), math.sin(math.radians(roll) / 2)
        cp, sp = math.cos(math.radians(pitch) / 2), math.sin(math.radians(pitch) / 2)
        cy, sy = math.cos(math.radians(yaw) / 2), math.sin(math.radians(yaw) / 2)
        return cls(
            x=sr * cp * cy - cr * sp * sy,
            y=cr * sp * cy + sr * cp * sy,
            z=cr * cp * sy - sr * sp * cy,
            w=cr * cp * cy + sr * sp * sy,
        ).normalized()


IDENTITY = Quat()


@dataclass(frozen=True, slots=True)
class Socket:
    """A socket definition: an attach point parented to a skeleton bone."""

    name: str
    parent_bone: str = ""
    rotation: Quat = field(default_factory=Quat)
    translation: Vec3 = field(default_factory=Vec3)
    ui_visible: bool = True
    source_file: str = ""

    @property
    def is_identity(self) -> bool:
        return self.rotation == IDENTITY and self.translation == Vec3()

    @property
    def is_child_socket(self) -> bool:
        return self.name.endswith("ChildSocket")

    @property
    def is_orphan(self) -> bool:
        """A socket with no parent bone is positioned in world space, not on the rig."""

        return not self.parent_bone


@dataclass(frozen=True, slots=True)
class DescriptorPart:
    """One equipment row: which sockets an item uses when stowed and when held."""

    part_name: str
    in_socket: str = ""
    out_socket: str = ""
    in_child_socket: str = ""
    out_child_socket: str = ""
    weapon_case_part: str = ""
    bag_socket: str = ""
    vehicle_bag_socket: str = ""
    source_file: str = ""

    @property
    def has_case(self) -> bool:
        """Sheathed types (Sword, Dagger, Arw) link a case part; Axe and Mace do not."""

        return bool(self.weapon_case_part)

    @property
    def category(self) -> str:
        name = self.part_name
        for prefix, label in (
            ("CD_MainWeapon_", "main_weapon"),
            ("CD_TwoHandWeapon_", "two_hand_weapon"),
            ("CD_Tool_", "tool"),
        ):
            if name.startswith(prefix):
                return label
        return "other"

    @property
    def weapon_type(self) -> str:
        """`CD_MainWeapon_Sword_IN_R` -> `Sword`; `CD_TwoHandWeapon_Axe` -> `Axe`."""

        name = self.part_name
        for prefix in ("CD_MainWeapon_", "CD_TwoHandWeapon_", "CD_Tool_"):
            if name.startswith(prefix):
                rest = name[len(prefix) :]
                for suffix in ("_IN_L", "_IN_R", "_L_Aux", "_R_Aux", "_IN", "_L", "_R"):
                    if rest.endswith(suffix):
                        return rest[: -len(suffix)]
                return rest
        return ""

    @property
    def side(self) -> str:
        for suffix, side in (("_L", "left"), ("_R", "right")):
            if self.part_name.endswith(suffix) or f"{suffix}_Aux" in self.part_name:
                return side
        return ""

    @property
    def is_case_row(self) -> bool:
        return "_IN" in self.part_name


# ── equipment units ──────────────────────────────────────────────────

#: Suffixes that mark a descriptor row as a *companion* of another row rather than an item in
#: its own right, with the role each one plays. `_IN` is the carrier — sheath, scabbard,
#: quiver, holster — and `_Aux` is the second blade of a dual-wield pair. Longest first, so
#: `_IN_R` is not read as `_R`.
LINK_SUFFIXES: Tuple[Tuple[str, str], ...] = (
    ("_IN_L", "case"),
    ("_IN_R", "case"),
    ("_L_Aux", "auxiliary"),
    ("_R_Aux", "auxiliary"),
    ("_IN", "case"),
    ("_Aux", "auxiliary"),
)

#: What a weapon type's carrier is actually called. The descriptor only ever says
#: `WeaponCasePart`; the type decides the noun a review should print. Anything not listed
#: keeps the generic `case`, which is true of every carrier and wrong about none.
CASE_ROLE_BY_TYPE: Dict[str, str] = {
    "Sword": "sheath",
    "Dagger": "sheath",
    "Rapier": "sheath",
    "Arw": "quiver",
    "Bow": "quiver",
    "Gun": "holster",
    "Pistol": "holster",
    "Musket": "holster",
}

#: Roles whose row must move with the primary item or the two visibly separate. An auxiliary
#: blade has its own placement and is not part of the stow story, so it is not required.
STOW_CRITICAL_ROLES: Tuple[str, ...] = ("case", "sheath", "scabbard", "quiver", "holster")


def link_role(primary: "DescriptorPart", linked: "DescriptorPart") -> str:
    """What `linked` is *to* `primary` — sheath, quiver, auxiliary blade, or plain other.

    Classified from the descriptor relationship and the row's own name shape rather than
    from one hardcoded `Sword_IN`, so a holster or a quiver added later is recognised
    without a code change.
    """

    name = linked.part_name
    for suffix, role in LINK_SUFFIXES:
        if not name.endswith(suffix):
            continue
        if role != "case":
            return role
        return CASE_ROLE_BY_TYPE.get(linked.weapon_type or primary.weapon_type, "case")
    if primary.weapon_case_part and primary.weapon_case_part == name:
        # The descriptor says it is the carrier even though the name does not.
        return CASE_ROLE_BY_TYPE.get(primary.weapon_type, "case")
    return "other"


@dataclass(frozen=True, slots=True)
class LinkedPart:
    """A descriptor row that has to move with the item it belongs to."""

    part_name: str
    role: str = "other"          # sheath | scabbard | quiver | holster | case | auxiliary | other
    required_for_stow: bool = False
    source_file: str = ""
    in_socket: str = ""
    in_child_socket: str = ""
    out_socket: str = ""
    out_child_socket: str = ""

    @property
    def label(self) -> str:
        return f"{self.part_name}  ({self.role})"

    def describe(self) -> str:
        requirement = "moves with the primary item" if self.required_for_stow else "optional"
        return f"{self.part_name}  [{self.role}]  {self.in_socket or '(nowhere)'}  — {requirement}"


@dataclass(frozen=True, slots=True)
class EquipmentUnit:
    """One selected item, resolved whole: its row, its carrier, and what it may touch.

    This is the source of truth for a placement operation. Handedness, target animation
    families, the descriptor files and the socket files are all read off *this* object, never
    re-derived later from whatever the window happens to have selected — which is how a move
    of one row ended up carrying another weapon's animations.
    """

    model: str
    weapon_id: str
    primary_part: str
    linked_parts: Tuple[LinkedPart, ...] = ()
    handedness: str = ""
    target_animation_families: Tuple[str, ...] = ()
    donor_animation_families: Tuple[str, ...] = ()
    allowed_descriptor_files: Tuple[str, ...] = ()
    allowed_socket_files: Tuple[str, ...] = ()
    weapon_path: str = ""
    weapon_type: str = ""
    weapon_category: str = ""
    primary_source_file: str = ""
    in_socket: str = ""
    in_child_socket: str = ""
    out_socket: str = ""
    out_child_socket: str = ""

    @property
    def unit_id(self) -> str:
        """Stable identity: same character, same asset, same row means the same unit."""

        return f"{self.model}/{self.weapon_id}/{self.primary_part}"

    @property
    def part_names(self) -> Tuple[str, ...]:
        return (self.primary_part, *(link.part_name for link in self.linked_parts))

    @property
    def required_links(self) -> Tuple[LinkedPart, ...]:
        return tuple(link for link in self.linked_parts if link.required_for_stow)

    @property
    def has_required_case(self) -> bool:
        return bool(self.required_links)

    def link(self, part_name: str) -> Optional[LinkedPart]:
        return next((l for l in self.linked_parts if l.part_name == part_name), None)

    def describe(self) -> str:
        links = ", ".join(link.part_name for link in self.linked_parts) or "(none)"
        return (
            f"{self.primary_part} on {self.model} using {self.weapon_id} "
            f"({self.handedness or '?'}); linked: {links}"
        )


@dataclass(frozen=True, slots=True)
class SocketRef:
    """A resolved attach point: the body socket plus the item-side child socket."""

    body_socket_name: str = ""
    body_socket: Optional[Socket] = None
    child_socket_name: str = ""
    child_socket: Optional[Socket] = None

    @property
    def resolved(self) -> bool:
        return self.body_socket is not None

    @property
    def fully_resolved(self) -> bool:
        return self.body_socket is not None and (
            not self.child_socket_name or self.child_socket is not None
        )

    @property
    def parent_bone(self) -> str:
        return self.body_socket.parent_bone if self.body_socket else ""

    def missing(self) -> Tuple[str, ...]:
        gaps = []
        if self.body_socket_name and self.body_socket is None:
            gaps.append(self.body_socket_name)
        if self.child_socket_name and self.child_socket is None:
            gaps.append(self.child_socket_name)
        return tuple(gaps)


@dataclass(frozen=True, slots=True)
class PlacementBinding:
    """Everything that decides where one equipment part sits, in one object.

    This is the unit the UI selects and edits: a descriptor row joined to the body socket it
    routes through and the item-side child socket that offsets it.
    """

    part: DescriptorPart
    stowed: SocketRef = field(default_factory=SocketRef)
    held: SocketRef = field(default_factory=SocketRef)
    case_binding: Optional["PlacementBinding"] = None

    @property
    def part_name(self) -> str:
        return self.part.part_name

    @property
    def complete(self) -> bool:
        return self.stowed.fully_resolved and self.held.fully_resolved

    def unresolved(self) -> Tuple[str, ...]:
        return tuple(sorted(set(self.stowed.missing() + self.held.missing())))

    def describe(self) -> str:
        stowed = self.stowed.body_socket_name or "-"
        held = self.held.body_socket_name or "-"
        case = f"  case={self.part.weapon_case_part}" if self.part.has_case else ""
        return f"{self.part_name:<34} stowed={stowed:<30} held={held:<18}{case}"
