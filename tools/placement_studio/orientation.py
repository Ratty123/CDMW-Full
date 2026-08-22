"""How an item is aimed at a destination, and when that may be written in place.

Two failures live here, and both were silent.

**A heuristic must not rotate anything.** The upside-down check measured the placed geometry
and, when it read inverted, added a half turn on its own. Mesh origins, geometry
distribution, attachment transforms and child-socket composition all differ by asset, so the
check is a useful *warning* and a poor authority. It reports now; it never writes.

**A shared child socket must not be edited in place.** `Pelvis_L_ChildSocket` is referenced by
every row that hangs on the left hip, so correcting one sword's angle there moves a dagger
and a tool as well. The operation clones instead, and reroutes only its own rows to the copy.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple

from .model import IDENTITY, Quat, Socket, Vec3

#: Same limit `editing.socket_name_problem` enforces: a `.paac` socket reference is stored as
#: length-prefixed ASCII, and the prefix byte holds len+1.
MAX_SOCKET_NAME = 62

#: Where an orientation came from, best first. The order *is* the resolution order from the
#: plan: an exact pairing this asset already defines beats a compatible one, which beats a
#: rotation borrowed from another asset for the same zone, which beats asking the user.
SOURCE_SAME_ASSET_SAME_ROLE = "same_asset_same_role"
SOURCE_SAME_ASSET = "same_asset"
SOURCE_BORROWED_ZONE = "borrowed_zone"
SOURCE_MANUAL = "manual"

SOURCE_LABELS: Dict[str, str] = {
    SOURCE_SAME_ASSET_SAME_ROLE: "this item's own child socket for that destination",
    SOURCE_SAME_ASSET: "a compatible child socket this item already defines",
    SOURCE_BORROWED_ZONE: "a known-good rotation copied from another item in the same zone",
    SOURCE_MANUAL: "needs aiming by hand",
}

_NAME_SAFE = re.compile(r"[^A-Za-z0-9_]+")


# ── clone-on-write naming ────────────────────────────────────────────


def operation_socket_name(
    part_name: str, zone: str, *, role: str = "", ordinal: int = 0
) -> str:
    """A deterministic, operation-owned child socket name.

    Deterministic because a preview is rebuilt many times and a name that moved between
    previews would show as a different socket each time — and because a replay of the same
    operation has to produce byte-identical output.

    `CDMW_<part>_<zone>_ChildSocket`, with the part id shortened by hash when the readable form
    would exceed what a `.paac` length prefix can carry. `ordinal` distinguishes a second
    operation that moves the same row into the same zone: reusing the first operation's socket
    would tie the two together, so packaging either one alone would leave a dangling route.
    """

    zone_token = _NAME_SAFE.sub("_", str(zone or "dest")).strip("_") or "dest"
    role_token = _NAME_SAFE.sub("_", str(role or "")).strip("_")
    part_token = _NAME_SAFE.sub("_", str(part_name or "part")).strip("_") or "part"
    # `CD_MainWeapon_Sword_IN_R` says the same thing as `MainWeapon_Sword_IN_R` with four
    # characters of a fixed prefix that every row shares.
    for prefix in ("CD_TwoHandWeapon_", "CD_MainWeapon_", "CD_Tool_", "CD_"):
        if part_token.startswith(prefix):
            part_token = part_token[len(prefix) :]
            break

    tail = ["_ChildSocket"] if ordinal <= 1 else [f"_{ordinal}_ChildSocket"]
    pieces = ["CDMW", part_token, zone_token]
    if role_token:
        pieces.append(role_token)
    candidate = "_".join(pieces) + tail[0]
    if len(candidate) <= MAX_SOCKET_NAME:
        return candidate

    # Shorten the part, which is the only variable-length piece, to a stable digest.
    digest = hashlib.sha256(part_token.encode("utf-8")).hexdigest()[:6]
    pieces = ["CDMW", digest, zone_token]
    if role_token:
        pieces.append(role_token)
    candidate = "_".join(pieces) + tail[0]
    if len(candidate) <= MAX_SOCKET_NAME:
        return candidate
    # Nothing readable fits. Keep the marker and the digest; both are needed to identify it.
    return f"CDMW_{digest}{tail[0]}"[:MAX_SOCKET_NAME]


def free_operation_socket_name(
    part_name: str, zone: str, *, role: str = "", taken=(), limit: int = 64
) -> str:
    """The first operation-owned name for this row and zone that nothing already uses.

    `taken` is asked, not guessed: two operations moving the same row into the same zone would
    otherwise agree on a name, and the second one's `add_socket` would fail — or worse, quietly
    depend on the first operation being packaged alongside it.
    """

    used = set(taken)
    for ordinal in range(1, max(2, limit) + 1):
        candidate = operation_socket_name(part_name, zone, role=role, ordinal=ordinal)
        if candidate not in used:
            return candidate
    # Every readable ordinal is used. Fall back to a digest of the whole set, which is stable
    # for the same inputs and cannot collide with the names above.
    digest = hashlib.sha256("|".join(sorted(used)).encode("utf-8")).hexdigest()[:8]
    return f"CDMW_{digest}_ChildSocket"


# ── shared-socket analysis ───────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SocketEditDecision:
    """Whether an operation may edit an existing child socket, and why."""

    socket_name: str
    users: Tuple[str, ...] = ()
    clone_required: bool = True
    reason: str = ""
    needs_confirmation: bool = False

    @property
    def shared(self) -> bool:
        return len(self.users) > 1

    def describe(self) -> str:
        verb = "clone required" if self.clone_required else "may be edited in place"
        used_by = ", ".join(self.users) or "(unused)"
        return f"{self.socket_name}: {verb} — used by {used_by}. {self.reason}".strip()


def decide_socket_edit(
    socket_name: str,
    users: Iterable[str],
    owned_parts: Iterable[str],
) -> SocketEditDecision:
    """Apply the clone-on-write rules to one child socket.

    Usage 0 or 1 and owned by this operation's unit: editable, with confirmation. Anything
    else clones — including the case where the one other user merely *might* be affected,
    because a local correction that alters another role is exactly the failure this prevents.
    """

    used_by = tuple(sorted({name for name in users if name}))
    owned = {name for name in owned_parts if name}
    outside = tuple(name for name in used_by if name not in owned)
    if outside:
        return SocketEditDecision(
            socket_name,
            used_by,
            clone_required=True,
            reason=(
                f"also used by {', '.join(outside)}, which this operation does not own"
            ),
        )
    if len(used_by) > 1:
        return SocketEditDecision(
            socket_name,
            used_by,
            clone_required=True,
            reason=f"{len(used_by)} rows reference it",
        )
    return SocketEditDecision(
        socket_name,
        used_by,
        clone_required=False,
        reason="only this operation's own row references it",
        needs_confirmation=True,
    )


# ── orientation templates ────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class OrientationTemplate:
    """The aim to give an item at a destination, and where that aim came from."""

    source: str = SOURCE_MANUAL
    #: The existing child socket to route to, when one is usable as it stands.
    child_socket_name: str = ""
    rotation: Optional[Quat] = None
    translation: Optional[Vec3] = None
    donor_weapon_id: str = ""
    #: True when a *new* socket has to be created rather than an existing one reused.
    creates_socket: bool = False
    note: str = ""

    @property
    def resolved(self) -> bool:
        return self.source != SOURCE_MANUAL

    @property
    def needs_manual_review(self) -> bool:
        return self.source in (SOURCE_BORROWED_ZONE, SOURCE_MANUAL)

    @property
    def label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)

    def describe(self) -> str:
        where = self.child_socket_name or "(new socket)"
        donor = f" from {self.donor_weapon_id}" if self.donor_weapon_id else ""
        return f"{where}: {self.label}{donor}. {self.note}".strip()


def resolve_orientation(
    *,
    destination_socket: str,
    asset_sockets: Mapping[str, Socket],
    conventional_child: str = "",
    fallback_child: str = "",
    current_child: str = "",
    borrow: Optional[Socket] = None,
    borrow_weapon_id: str = "",
) -> OrientationTemplate:
    """Pick the aim for one row at one destination, in the plan's resolution order.

    `asset_sockets` are the child sockets the *item's own* file defines — the only ones that
    can be routed to without inventing something. `borrow` is a same-named socket from
    another asset, whose **rotation** is worth taking and whose translation is not: the grip
    offset runs along the blade and a two-hand sword's -0.470 suits its own length.
    """

    if conventional_child and conventional_child in asset_sockets:
        socket = asset_sockets[conventional_child]
        return OrientationTemplate(
            source=SOURCE_SAME_ASSET_SAME_ROLE,
            child_socket_name=conventional_child,
            rotation=socket.rotation,
            translation=socket.translation,
            note="vanilla pairs this child socket with that destination for this item",
        )

    if fallback_child and fallback_child in asset_sockets:
        socket = asset_sockets[fallback_child]
        return OrientationTemplate(
            source=SOURCE_SAME_ASSET,
            child_socket_name=fallback_child,
            rotation=socket.rotation,
            translation=socket.translation,
            note="the item defines the child socket the destination conventionally uses",
        )

    if borrow is not None:
        keep = asset_sockets.get(current_child)
        return OrientationTemplate(
            source=SOURCE_BORROWED_ZONE,
            child_socket_name="",
            rotation=borrow.rotation,
            # C4: the rotation travels, the translation does not.
            translation=keep.translation if keep is not None else Vec3(),
            donor_weapon_id=borrow_weapon_id,
            creates_socket=True,
            note=(
                "rotation copied from another item that hangs there; this item's own "
                "translation is kept, so review the result before committing"
            ),
        )

    return OrientationTemplate(
        source=SOURCE_MANUAL,
        child_socket_name="",
        rotation=(asset_sockets[current_child].rotation
                  if current_child in asset_sockets else IDENTITY),
        translation=(asset_sockets[current_child].translation
                     if current_child in asset_sockets else Vec3()),
        creates_socket=True,
        note="nothing compatible is defined for that destination; aim it in the viewport",
    )


def clone_socket(
    template: OrientationTemplate,
    *,
    name: str,
    parent_bone: str = "",
    source_file: str = "",
) -> Socket:
    """The operation-owned socket a template describes, ready for `add_socket`."""

    return Socket(
        name=name,
        parent_bone=parent_bone,
        rotation=template.rotation or IDENTITY,
        translation=template.translation or Vec3(),
        source_file=source_file,
    )


# ── the inversion diagnostic ─────────────────────────────────────────


#: Vertical slack before an item counts as inverted. A hand's breadth, so a horizontal item
#: is not reported as upside down.
INVERSION_SLACK = 0.05

INVERSION_MESSAGE = (
    "The item may be inverted at this destination. Review orientation before commit."
)


@dataclass(frozen=True, slots=True)
class InversionDiagnostic:
    """What the geometry suggests about the item's aim. Advice, never an edit."""

    inverted: bool = False
    measured: bool = False
    anchor_height: float = 0.0
    far_height: float = 0.0
    note: str = ""

    @property
    def message(self) -> str:
        if not self.measured:
            return ""
        return INVERSION_MESSAGE if self.inverted else ""


def diagnose_inversion(anchor: Optional[Vec3], vertices: Sequence[Vec3]) -> InversionDiagnostic:
    """Does the stowed item stick upward out of its attachment point?

    A stowed weapon hangs *down* from where it is fixed, so the far end of the mesh should
    sit below the socket. Measured on the placed geometry, which is the only thing that
    cannot disagree with what is on screen — and reported, because origins and attachment
    transforms differ enough by asset that the measurement is evidence and not a verdict.
    """

    if anchor is None or not vertices:
        return InversionDiagnostic(note="nothing placed to measure")
    far = max(vertices, key=lambda v: anchor.distance_to(v))
    return InversionDiagnostic(
        inverted=far.y > anchor.y + INVERSION_SLACK,
        measured=True,
        anchor_height=anchor.y,
        far_height=far.y,
    )


def half_turn_about_y(rotation: Quat) -> Quat:
    """`rotation` with a half turn about Y added.

    A half turn about Y is exactly what separates the hip child socket (identity) from the
    back one (0, 1, 0, 0) on every weapon in the corpus, so it is the correction an
    upside-down stow usually needs. Offered as a named operation the user can apply — it is
    no longer applied on their behalf.
    """

    return Quat(-rotation.z, rotation.w, rotation.x, -rotation.y).normalized()
