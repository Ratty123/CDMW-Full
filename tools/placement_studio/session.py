"""One character's complete placement state, loaded and ready to inspect.

A session is the unit the window binds to: a skeleton, the body sockets that hang off it, the
descriptor rows that route equipment through them, and the weapon files whose child sockets
complete a binding. Everything is read-only here — Phase 3 adds editing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .documents import is_body_socket_file
from .model import PlacementBinding, Socket, Vec3
from .resolver import (
    KNOWN_MODELS,
    PlacementResolver,
    WeaponSocketFile,
    model_of,
    resolver_from_baseline,
)
from .skeleton import (
    BoneHierarchy,
    Matrix,
    PlacedSocket,
    invert_rigid,
    matrix_from,
    multiply,
    translation_of,
    world_axis_to_local,
)


def skeleton_path_for(socket_path: str) -> str:
    """`.../socketbonedata/1_pc/1_phm/phm_01.pab.sockets.xml` -> `.../model/1_pc/1_phm/phm_01.pab`.

    The socket file is named after the skeleton it describes, so the pairing is derivable
    rather than a lookup table that would drift.
    """

    path = PurePosixPath(str(socket_path).replace("\\", "/"))
    name = path.name
    if not name.lower().endswith(".pab.sockets.xml"):
        return ""
    skeleton_name = name[: -len(".sockets.xml")]
    parts = list(path.parts)
    try:
        anchor = parts.index("socketbonedata")
    except ValueError:
        return ""
    # descriptors/socketbonedata/<group>/<model>/... -> model/<group>/<model>/<skeleton>
    tail = parts[anchor + 1 : -1]
    head = parts[: anchor - 1] if anchor >= 1 else []
    return "/".join([*head, "model", *tail, skeleton_name])


def skeleton_paths_for(socket_paths: Iterable[str]) -> List[str]:
    return sorted({p for p in (skeleton_path_for(s) for s in socket_paths) if p})


@dataclass(frozen=True, slots=True)
class SocketUsage:
    """Which descriptor rows reference a socket, and in what role."""

    stowed: tuple[str, ...] = field(default=())
    held: tuple[str, ...] = field(default=())
    child_offset: tuple[str, ...] = field(default=())

    @property
    def total(self) -> int:
        return len(set(self.stowed) | set(self.held) | set(self.child_offset))

    @property
    def empty(self) -> bool:
        return self.total == 0

    def roles(self) -> str:
        labels = []
        if self.stowed:
            labels.append(f"stowed x{len(self.stowed)}")
        if self.held:
            labels.append(f"held x{len(self.held)}")
        if self.child_offset:
            labels.append(f"child x{len(self.child_offset)}")
        return ", ".join(labels) or "unused"


class PlacementSession:
    """Everything loaded for one character model."""

    __slots__ = ("model", "hierarchy", "_resolver", "_body_sockets", "_placed", "_weapon",
                 "warnings", "_bind_hierarchy", "_usage_cache", "pose_matrices")

    def __init__(
        self,
        model: str,
        hierarchy: Optional[BoneHierarchy],
        resolver: PlacementResolver,
        *,
        warnings: Sequence[str] = (),
    ) -> None:
        self.model = model
        self.hierarchy = hierarchy
        self._resolver = resolver
        self._body_sockets: Dict[str, Socket] = resolver.body_sockets(model)
        self._weapon: Optional[WeaponSocketFile] = None
        self.warnings: List[str] = list(warnings)
        self._placed: Dict[str, PlacedSocket] = {}
        self._bind_hierarchy: Optional[BoneHierarchy] = None
        self._usage_cache: Optional[Dict[str, SocketUsage]] = None
        #: World matrices from the last `apply_pose`, so skinning does not redo them.
        self.pose_matrices = None
        self._reposition()

    # ── construction ────────────────────────────────────────────────

    @classmethod
    def from_baseline(cls, baseline, model: str) -> "PlacementSession":
        resolver = resolver_from_baseline(baseline)
        warnings: List[str] = []

        hierarchy: Optional[BoneHierarchy] = None
        socket_files = [
            path
            for path in baseline.paths()
            if is_body_socket_file(path) and model_of(path) == model
        ]
        if not socket_files:
            warnings.append(f"no body socket file found for model {model}")
            return cls(model, None, resolver, warnings=warnings)

        # Each socket file names its own `.pab`, but customization variants share the base
        # rig: `phw_damian_01.pab.sockets.xml` has no `phw_damian_01.pab` — Damian is a
        # customization of PHW with its own socket transforms on the same skeleton. So try
        # each derived path, then fall back to whichever `.pab` this model does ship.
        candidates = [skeleton_path_for(path) for path in sorted(socket_files)]
        candidates = [path for path in candidates if path]
        fallback = sorted(
            path
            for path in baseline.paths()
            if path.endswith(".pab") and f"/model/" in path and f"/{model}/" in path
        )
        for path in [*candidates, *fallback]:
            if path not in baseline:
                continue
            try:
                hierarchy = BoneHierarchy.from_pab(baseline.read(path), path)
            except Exception as exc:  # noqa: BLE001 - try the next candidate
                warnings.append(f"{path}: {exc}")
                continue
            if path not in candidates:
                warnings.append(
                    f"using shared rig {path} — no dedicated skeleton for this variant"
                )
            break
        else:
            warnings.append(f"no skeleton available for model {model} (tried {candidates})")

        return cls(model, hierarchy, resolver, warnings=warnings)

    @classmethod
    def available_models(cls, baseline) -> List[str]:
        return resolver_from_baseline(baseline).models()

    # ── state ───────────────────────────────────────────────────────

    @property
    def label(self) -> str:
        return KNOWN_MODELS.get(self.model, self.model)

    @property
    def has_skeleton(self) -> bool:
        return self.hierarchy is not None and len(self.hierarchy) > 0

    @property
    def bone_count(self) -> int:
        return len(self.hierarchy) if self.hierarchy else 0

    @property
    def weapon(self) -> Optional[WeaponSocketFile]:
        return self._weapon

    def weapons(self) -> List[WeaponSocketFile]:
        return self._resolver.weapons(model=self.model)

    def select_weapon(self, weapon: Optional[WeaponSocketFile]) -> None:
        """Choose the item whose child sockets apply. Child sockets are per weapon model."""

        self._weapon = weapon
        self._usage_cache = None
        self._reposition()

    def add_socket_file(self, game_path: str, data: bytes) -> None:
        """Register another socket file — how archive weapons join the pinned baseline."""

        self._resolver.add_socket_file(game_path, data)
        self._body_sockets = self._resolver.body_sockets(self.model)
        self._usage_cache = None
        self._reposition()

    # ── animation playback ──────────────────────────────────────────

    def apply_pose(self, clip, frame: float) -> None:
        """Pose the rig from a motion clip; sockets re-place against the posed bones.

        The bind hierarchy is kept so every seek re-poses from the rest pose rather than
        from the previous frame, which would compound the delta each tick.
        """

        from .playback import posed_hierarchy

        if self._bind_hierarchy is None:
            self._bind_hierarchy = self.hierarchy
        if self._bind_hierarchy is None:
            return
        from tools.paa_motion.pose import world_matrices

        parsed = getattr(self._bind_hierarchy, "parsed", None)
        self.pose_matrices = world_matrices(parsed, clip, frame) if parsed is not None else None
        self.hierarchy = posed_hierarchy(
            self._bind_hierarchy, clip, frame, matrices=self.pose_matrices
        )
        self._reposition()

    def clear_pose(self) -> None:
        """Return the rig to its bind pose."""

        if self._bind_hierarchy is None:
            return
        self.hierarchy = self._bind_hierarchy
        self._bind_hierarchy = None
        self.pose_matrices = None
        self._reposition()

    @property
    def posed(self) -> bool:
        return self._bind_hierarchy is not None

    def _reposition(self) -> None:
        # Only *body* sockets get a world position from the rig. A child socket is an
        # item-local offset applied after attaching, so it has no standalone world position —
        # placing it here would draw every child socket at the origin and read as a bug.
        self._placed = {}
        if self.hierarchy is None:
            return
        for placed in self.hierarchy.place_all(self._body_sockets.values()):
            self._placed[placed.name] = placed

    def attachment_matrix(self, body_socket: str, child_socket: str = "") -> Optional[Matrix]:
        """Where an item actually ends up: the body socket composed with its child offset.

        This, not the socket position alone, is where the weapon sits.
        """

        placed = self._placed.get(body_socket)
        if placed is None:
            return None
        if not child_socket or self._weapon is None:
            return placed.world_matrix
        child = self._weapon.sockets.get(child_socket)
        if child is None:
            return placed.world_matrix
        # The child socket is a frame *on the item* that mates with the body socket, so the
        # item is transformed by its INVERSE to bring that frame onto the socket. Applying it
        # forwards points a held blade 93% backwards — visible immediately in the render, and
        # invisible to every file-level check.
        return multiply(invert_rigid(child.rotation, child.translation), placed.world_matrix)

    def attachment_point(self, body_socket: str, child_socket: str = "") -> Optional[Vec3]:
        matrix = self.attachment_matrix(body_socket, child_socket)
        return translation_of(matrix) if matrix is not None else None

    def binding_points(self, binding: PlacementBinding) -> Dict[str, Optional[Vec3]]:
        """Stowed and held attachment points for one equipment row."""

        return {
            "stowed": self.attachment_point(binding.part.in_socket, binding.part.in_child_socket),
            "held": self.attachment_point(binding.part.out_socket, binding.part.out_child_socket),
        }

    # ── queries ─────────────────────────────────────────────────────

    def body_sockets(self) -> List[Socket]:
        return sorted(self._body_sockets.values(), key=lambda s: s.name)

    def child_sockets(self) -> List[Socket]:
        if self._weapon is None:
            return []
        return sorted(self._weapon.sockets.values(), key=lambda s: s.name)

    def placed(self, name: str) -> Optional[PlacedSocket]:
        return self._placed.get(name)

    def placed_sockets(self) -> List[PlacedSocket]:
        return sorted(self._placed.values(), key=lambda p: p.name)

    def bindings(self) -> List[PlacementBinding]:
        return list(self._resolver.resolve(model=self.model, weapon=self._weapon).bindings)

    def report(self):
        return self._resolver.resolve(model=self.model, weapon=self._weapon)

    def conventional_child_socket(self, body_socket: str, *, held: bool = False) -> str:
        """The child socket vanilla pairs with a body socket, or "" if it pairs with none.

        Body and child sockets are matched pairs, not independent choices: every vanilla row uses
        `Pelvis_L_Socket` with `Pelvis_L_ChildSocket`, and the back sockets with
        `Spine2_B_SubWeapon_ChildSocket`. A child socket carries the item's *orientation*, so
        re-routing the body socket alone leaves a back-slung sword hanging at the hip's angle.

        Read off the descriptor rather than inferred from the names, because the names do not
        actually follow one rule — `Spine2_B_MainWeapon_Socket` pairs with a `SubWeapon` child.
        """

        counts: Dict[str, int] = {}
        for binding in self.bindings():
            part = binding.part
            child = part.out_child_socket if held else part.in_child_socket
            socket = part.out_socket if held else part.in_socket
            if socket == body_socket and child:
                counts[child] = counts.get(child, 0) + 1
        if not counts:
            return ""
        # Most-used wins; ties break by name so the answer never depends on row order.
        return max(sorted(counts), key=lambda name: counts[name])

    def borrowed_child_socket(self, child_name: str):
        """A child socket of this name defined by some *other* item, or `None`.

        The one case this exists for: a one-hand sword has `Pelvis_L_ChildSocket` and
        `Pelvis_R_ChildSocket` and nothing else, because the game never slings it on the back.
        Route it there anyway and it keeps the hip's orientation, which on the back reads as
        upside down — the hip child socket is an identity rotation while the back one is a
        180-degree turn about Y.

        Borrowing is sound here because every weapon in the corpus shares one local axis
        convention: all of them, one-hand and two-hand alike, define `Basic_ChildSocket` at
        the same translation and rotation. So a rotation authored for the back on one sword
        means the same thing on another.

        Only the *rotation* is worth taking. The translation is the grip offset along the
        blade — the two-hand sword's -0.470 suits its own length, not a shorter weapon's.
        """

        for weapon in self.weapons():
            socket = weapon.sockets.get(child_name)
            if socket is not None:
                return socket
        return None

    def usage(self, socket_name: str) -> SocketUsage:
        """Which rows route through a socket — the 'what moves if I edit this?' answer."""

        return self.usage_map().get(socket_name, SocketUsage())

    def usage_map(self) -> Dict[str, SocketUsage]:
        """Every socket's usage from one pass over the bindings.

        Asking per socket meant resolving the descriptor rows once per socket — 52 resolves
        to paint one frame, which is most of the cost of a playback tick. The rows do not
        depend on the pose, so the answer is cached until the weapon or an edit changes it.
        """

        if self._usage_cache is not None:
            return self._usage_cache
        stowed: Dict[str, List[str]] = {}
        held: Dict[str, List[str]] = {}
        child: Dict[str, List[str]] = {}
        for binding in self.bindings():
            part = binding.part
            if part.in_socket:
                stowed.setdefault(part.in_socket, []).append(part.part_name)
            if part.out_socket:
                held.setdefault(part.out_socket, []).append(part.part_name)
            for name in (part.in_child_socket, part.out_child_socket):
                if name:
                    child.setdefault(name, []).append(part.part_name)
        names = set(stowed) | set(held) | set(child) | set(self._body_sockets)
        self._usage_cache = {
            name: SocketUsage(
                tuple(stowed.get(name, ())),
                tuple(held.get(name, ())),
                tuple(child.get(name, ())),
            )
            for name in names
        }
        return self._usage_cache

    def invalidate_usage(self) -> None:
        """Drop the usage cache. Posing does not touch it; editing and weapon swaps do."""

        self._usage_cache = None

    def world_axis_for_socket(self, socket_name: str, world_axis: Vec3) -> Vec3:
        """Convert a world-space drag axis into the space a socket's rotation is stored in.

        Body sockets are parented to a bone, so the axis must be taken into that bone's space.
        A child socket is item-local with no bone, so the axis passes through unchanged.
        """

        placed = self._placed.get(socket_name)
        if placed is None or placed.bone is None:
            return world_axis
        return world_axis_to_local(world_axis, placed.bone.bind_matrix)

    def bone_chain(self, socket_name: str) -> List[str]:
        placed = self._placed.get(socket_name)
        if placed is None or placed.bone is None or self.hierarchy is None:
            return []
        return [bone.name for bone in self.hierarchy.path_to_root(placed.bone.name)]

    def sockets_on_bone(self, bone_name: str) -> List[str]:
        return sorted(
            name
            for name, placed in self._placed.items()
            if placed.bone is not None and placed.bone.name == bone_name
        )

    def occupied_bones(self) -> List[str]:
        """Bones that actually carry a socket — the useful subset of 434."""

        return sorted(
            {placed.bone.name for placed in self._placed.values() if placed.bone is not None}
        )

    def summary(self) -> str:
        return (
            f"{self.label}: {self.bone_count} bones, "
            f"{len(self._body_sockets)} body sockets, "
            f"{len(self.child_sockets())} child sockets, "
            f"{len(self.weapons())} weapon file(s)"
        )
