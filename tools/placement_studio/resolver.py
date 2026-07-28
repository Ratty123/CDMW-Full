"""Join descriptor rows, body sockets, and weapon child sockets into placement bindings.

Two scoping rules drive the whole design, and getting either wrong produces nonsense:

1. **Body sockets are per character model**, defined once in `<model>.pab.sockets.xml`.
   Editing one moves every part routed through it.
2. **Child sockets are per weapon model.** Every weapon file defines its own
   `Basic_ChildSocket`, `Spine2_R_ChildSocket`, and so on. They are not competing
   definitions of one socket, so they must never be flattened into a shared table — the
   child socket for a binding comes from *that item's* file.

Socket-file resolution is also load-order dependent: `phw_01.pab.sockets.xml` is a
30-socket *subset*, not a rename of the 53-socket `phw_damian_01.pab.sockets.xml`, and which
one a character resolves to depends on which other mods are active. The active files are an
explicit input, never inferred from the character name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .documents import (
    DescriptorDocument,
    SocketDocument,
    is_body_socket_file,
    is_descriptor_file,
    is_socket_file,
)
from .model import DescriptorPart, PlacementBinding, Socket, SocketRef

KNOWN_MODELS = {
    "1_phm": "Kliff (PHM)",
    "2_phw": "Damian (PHW)",
    "14_ptm": "PTM",
}

WEAPON_CATEGORIES = {
    "1_onehandweapon": "one-hand",
    "2_twohandweapon": "two-hand",
}


def model_of(game_path: str) -> str:
    """Recover the model directory (`1_phm`, `2_phw`, ...) from a socket path."""

    parts = game_path.lower().replace("\\", "/").split("/")
    for index, segment in enumerate(parts):
        if segment == "socketbonedata" and index + 2 < len(parts):
            return parts[index + 2]
    return ""


def weapon_category_of(game_path: str) -> str:
    parts = game_path.lower().replace("\\", "/").split("/")
    for segment in parts:
        if segment in WEAPON_CATEGORIES:
            return segment
    return ""


def descriptor_model_of(game_path: str) -> str:
    """Map a descriptor file to the character model it describes.

    Descriptors are named by model prefix — `phm_description_player_kliff.xml` is Kliff,
    `phw_description_player_001.xml` is Damian. Without this, every descriptor merges into
    one table and the last one loaded silently wins, so Kliff's rows get shown as Damian's.
    """

    name = Path(game_path).name.lower()
    for prefix, model in (("phm_", "1_phm"), ("phw_", "2_phw"), ("ptm_", "14_ptm")):
        if name.startswith(prefix):
            return model
    return ""


def weapon_id_of(game_path: str) -> str:
    """`cd_phm_01_sword_0001_r_in.sockets.xml` -> `cd_phm_01_sword_0001_r_in`."""

    name = Path(game_path).name
    return name[: -len(".sockets.xml")] if name.lower().endswith(".sockets.xml") else name


@dataclass(frozen=True, slots=True)
class WeaponSocketFile:
    """One weapon model's own child-socket definitions."""

    game_path: str
    weapon_id: str
    model: str
    category: str
    sockets: Mapping[str, Socket]

    @property
    def is_case(self) -> bool:
        """`_in` files hold the sheath/case variant of a weapon."""

        return self.weapon_id.endswith("_in")

    @property
    def label(self) -> str:
        """What the dropdown shows: the weapon named, not its file stem.

        `cd_phm_01_sword_0001_r (one-hand)` is nine tokens of which two vary between rows. The
        variant number stays — a character carries several swords that differ only by it.
        """

        from .clip_names import weapon_label

        kind = WEAPON_CATEGORIES.get(self.category, self.category or "?")
        return f"{weapon_label(self.weapon_id)} ({kind}{', case' if self.is_case else ''})"


@dataclass(frozen=True, slots=True)
class BodySocketFile:
    game_path: str
    model: str
    sockets: Mapping[str, Socket]
    priority: int = 0


@dataclass(frozen=True, slots=True)
class ResolutionReport:
    """What resolved, what did not, and why."""

    model: str = ""
    weapon: str = ""
    bindings: tuple[PlacementBinding, ...] = field(default=())
    missing_body_sockets: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    missing_child_sockets: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    unused_body_sockets: tuple[str, ...] = field(default=())
    warnings: tuple[str, ...] = field(default=())

    @property
    def complete(self) -> bool:
        return not self.missing_body_sockets and not self.missing_child_sockets

    @property
    def resolved_count(self) -> int:
        return sum(1 for binding in self.bindings if binding.complete)

    def by_weapon_type(self) -> Dict[str, List[PlacementBinding]]:
        grouped: Dict[str, List[PlacementBinding]] = {}
        for binding in self.bindings:
            grouped.setdefault(binding.part.weapon_type or "(other)", []).append(binding)
        return dict(sorted(grouped.items()))

    def summary(self) -> str:
        return (
            f"{len(self.bindings)} rows, {self.resolved_count} fully resolved, "
            f"{len(self.missing_body_sockets)} missing body socket, "
            f"{len(self.missing_child_sockets)} missing child socket"
        )


class PlacementResolver:
    """Builds `PlacementBinding` objects from a character's active files."""

    def __init__(self) -> None:
        self._body: List[BodySocketFile] = []
        self._weapons: List[WeaponSocketFile] = []
        self._descriptors: List[DescriptorDocument] = []
        self._warnings: List[str] = []

    # ── inputs ──────────────────────────────────────────────────────

    def add_socket_file(self, game_path: str, data: bytes, *, priority: int = 0) -> None:
        document = SocketDocument.load(data, game_path)
        sockets = document.socket_map()
        self._warnings.extend(f"{game_path}: {item}" for item in document.warnings)
        if not document.count_matches_contents():
            self._warnings.append(
                f"{game_path}: SocketList Count={document.declared_count} "
                f"but {len(sockets)} sockets defined"
            )
        model = model_of(game_path)
        if is_body_socket_file(game_path):
            self._body.append(BodySocketFile(game_path, model, sockets, priority))
        else:
            self._weapons.append(
                WeaponSocketFile(
                    game_path,
                    weapon_id_of(game_path),
                    model,
                    weapon_category_of(game_path),
                    sockets,
                )
            )

    def add_descriptor_file(self, game_path: str, data: bytes) -> None:
        self._descriptors.append(DescriptorDocument.load(data, game_path))

    def add_files(self, files: Mapping[str, bytes], *, priority: int = 0) -> None:
        for game_path, data in files.items():
            if is_socket_file(game_path):
                self.add_socket_file(game_path, data, priority=priority)
            elif is_descriptor_file(game_path):
                self.add_descriptor_file(game_path, data)

    # ── queries ─────────────────────────────────────────────────────

    def models(self) -> List[str]:
        return sorted({f.model for f in self._body} - {""})

    def weapons(self, *, model: str = "") -> List[WeaponSocketFile]:
        return sorted(
            (w for w in self._weapons if not model or w.model == model),
            key=lambda w: w.weapon_id,
        )

    def body_sockets(self, model: str) -> Dict[str, Socket]:
        """Flatten body-socket files for one model. Higher priority wins."""

        table: Dict[str, Socket] = {}
        for source in sorted((f for f in self._body if f.model == model), key=lambda f: f.priority):
            table.update(source.sockets)
        return table

    def child_sockets(self, weapon: Optional[WeaponSocketFile]) -> Dict[str, Socket]:
        return dict(weapon.sockets) if weapon is not None else {}

    def parts(self, *, model: str = "") -> Dict[str, DescriptorPart]:
        """Descriptor rows, scoped to one character model.

        Unscoped merging is a correctness bug, not a convenience: Kliff and Damian share part
        names, so whichever descriptor loaded last would silently own every row.
        """

        parts: Dict[str, DescriptorPart] = {}
        for document in self._descriptors:
            if model and descriptor_model_of(document.game_path) not in ("", model):
                continue
            parts.update(document.part_map())
        return parts

    def descriptors(self, *, model: str = "") -> List[str]:
        return sorted(
            document.game_path
            for document in self._descriptors
            if not model or descriptor_model_of(document.game_path) in ("", model)
        )

    def child_socket_providers(self, name: str, *, model: str = "") -> List[str]:
        """Which weapon files define a given child socket."""

        return [w.weapon_id for w in self.weapons(model=model) if name in w.sockets]

    # ── resolution ──────────────────────────────────────────────────

    def resolve(
        self,
        *,
        model: str,
        weapon: Optional[WeaponSocketFile] = None,
    ) -> ResolutionReport:
        """Resolve every descriptor row for one character model.

        `weapon` selects the item whose child sockets apply. Without it, body sockets still
        resolve and child sockets are reported as unresolved — which is correct: a child
        socket has no meaning until you name the item it belongs to.
        """

        body = self.body_sockets(model)
        child = self.child_sockets(weapon)

        bindings: List[PlacementBinding] = []
        missing_body: Dict[str, tuple[str, ...]] = {}
        missing_child: Dict[str, tuple[str, ...]] = {}
        used_body: set[str] = set()

        for name, part in sorted(self.parts(model=model).items()):
            stowed = SocketRef(
                body_socket_name=part.in_socket,
                body_socket=body.get(part.in_socket),
                child_socket_name=part.in_child_socket,
                child_socket=child.get(part.in_child_socket),
            )
            held = SocketRef(
                body_socket_name=part.out_socket,
                body_socket=body.get(part.out_socket),
                child_socket_name=part.out_child_socket,
                child_socket=child.get(part.out_child_socket),
            )
            bindings.append(PlacementBinding(part=part, stowed=stowed, held=held))

            for socket_name in (part.in_socket, part.out_socket):
                if socket_name:
                    used_body.add(socket_name)

            body_gaps = tuple(
                s for s in (part.in_socket, part.out_socket) if s and s not in body
            )
            child_gaps = tuple(
                s
                for s in (part.in_child_socket, part.out_child_socket)
                if s and s not in child
            )
            if body_gaps:
                missing_body[name] = body_gaps
            if child_gaps:
                missing_child[name] = child_gaps

        # Link sheath rows to the weapon they case, so the UI can move them together.
        by_name = {binding.part_name: binding for binding in bindings}
        linked = tuple(
            PlacementBinding(
                part=binding.part,
                stowed=binding.stowed,
                held=binding.held,
                case_binding=by_name.get(binding.part.weapon_case_part)
                if binding.part.has_case
                else None,
            )
            for binding in bindings
        )

        return ResolutionReport(
            model=model,
            weapon=weapon.weapon_id if weapon else "",
            bindings=linked,
            missing_body_sockets=missing_body,
            missing_child_sockets=missing_child,
            unused_body_sockets=tuple(sorted(n for n in body if n not in used_body)),
            warnings=tuple(self._warnings),
        )

    def bindings_through(self, socket_name: str, *, model: str) -> List[PlacementBinding]:
        """'What moves if I edit this socket?' - the question the UI must answer instantly."""

        report = self.resolve(model=model)
        return [
            binding
            for binding in report.bindings
            if socket_name
            in (
                binding.part.in_socket,
                binding.part.out_socket,
                binding.part.in_child_socket,
                binding.part.out_child_socket,
            )
        ]


def resolver_from_baseline(baseline) -> PlacementResolver:
    """Build a resolver over the pinned vanilla baseline."""

    resolver = PlacementResolver()
    for game_path in baseline.paths():
        if is_socket_file(game_path) or is_descriptor_file(game_path):
            resolver.add_files({game_path: baseline.read(game_path)})
    return resolver
