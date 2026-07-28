"""Interactive editing: semantic commands, replayed onto pinned vanilla bytes.

Two rules shape this module.

**Undo/redo is over the command list, never over file bytes.** Every edit is a semantic
command holding its *final* value. The output is produced by replaying the surviving commands
onto the pinned vanilla document from scratch, so undo cannot leave a half-reverted file and
the emitted plan can never disagree with the emitted bytes — both come from the same replay.

**Rotation is authored in degrees.** The tuning guide is explicit that quaternions must not be
hand-edited, so the UI surface is euler degrees and conversion happens in one reviewed place,
with normalization enforced before any write.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import ops
from .documents import (
    DescriptorDocument,
    SocketDocument,
    is_descriptor_file,
    is_socket_file,
)
from .model import (
    NUDGE_LARGE,
    NUDGE_NORMAL,
    NUDGE_RISKY,
    NUDGE_TINY,
    Quat,
    Socket,
    TransformError,
    Vec3,
)
from .ops import Operation, Plan, descriptor_alias_source
from .xmldoc import XmlDocumentError

# Step sizes the tuning guide sanctions, with its own risk labels.
NUDGE_STEPS: Tuple[Tuple[str, float, bool], ...] = (
    ("tiny", NUDGE_TINY, False),
    ("normal", NUDGE_NORMAL, False),
    ("large", NUDGE_LARGE, False),
    ("risky", NUDGE_RISKY, True),
)

_ROUTE_FIELDS = ("in_socket", "out_socket", "in_child_socket", "out_child_socket")

# Every vanilla socket name is drawn from this set, and it is also the safe intersection of two
# formats: an XML attribute value, and a length-prefixed ASCII string inside a `.paac` chart.
_NAME_PATTERN = re.compile(r"[A-Za-z0-9_]+")
MAX_SOCKET_NAME = 62


def socket_name_problem(name: str) -> str:
    """Why this name cannot be used, or "" if it can.

    Returns a message rather than raising so a dialog can show it while the user is still typing.
    """

    if not name:
        return "Give the socket a name"
    if not _NAME_PATTERN.fullmatch(name):
        return "Use only letters, digits and underscores"
    if len(name) > MAX_SOCKET_NAME:
        # A `.paac` reference is prefixed with a single length byte holding len+1.
        return f"Name is too long ({len(name)}); the chart length prefix allows {MAX_SOCKET_NAME}"
    return ""


class EditError(RuntimeError):
    """Raised when an edit is not representable in the operation vocabulary."""


# ── commands ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Command:
    """One semantic edit, holding its final value rather than a delta.

    Absolute values are what make coalescing safe: dragging a socket across twenty mouse
    events collapses to one command, and replay is order-independent within a field.
    """

    kind: str          # translate | rotate | reparent | add_socket | route | replace_file
    game_path: str
    target: str        # socket name, or descriptor part name
    field_name: str = ""
    translation: Optional[Vec3] = None
    rotation: Optional[Quat] = None
    text: str = ""
    socket: Optional[Socket] = None
    #: Whole-file payload, for `replace_file`.
    payload: Optional[bytes] = None

    @property
    def coalesce_key(self) -> Tuple[str, str, str, str]:
        """Two commands collapse when they address the same field of the same thing."""

        return (self.kind, self.game_path, self.target, self.field_name)

    def describe(self) -> str:
        if self.kind == "translate" and self.translation is not None:
            return f"move {self.target} -> {self.translation.format()}"
        if self.kind == "rotate" and self.rotation is not None:
            roll, pitch, yaw = self.rotation.to_euler_degrees()
            return f"rotate {self.target} -> roll {roll:.2f} pitch {pitch:.2f} yaw {yaw:.2f}"
        if self.kind == "reparent":
            return f"reparent {self.target} -> {self.text}"
        if self.kind == "add_socket":
            return f"create socket {self.target}"
        if self.kind == "route":
            return f"route {self.target}.{self.field_name} -> {self.text}"
        if self.kind == "replace_file":
            target = self.game_path.rsplit("/", 1)[-1]
            return f"replace {target} with {self.text or 'supplied bytes'}"
        if self.kind == "retarget":
            return f"retarget {self.field_name} -> {self.text} in {self.game_path.rsplit('/', 1)[-1]}"
        return f"{self.kind} {self.target}"


@dataclass(frozen=True, slots=True)
class SocketEditState:
    """A socket's current edited value alongside its pinned original."""

    name: str
    original: Socket
    current: Socket

    @property
    def translation_changed(self) -> bool:
        return self.original.translation != self.current.translation

    @property
    def rotation_changed(self) -> bool:
        return self.original.rotation != self.current.rotation

    @property
    def parent_changed(self) -> bool:
        return self.original.parent_bone != self.current.parent_bone

    @property
    def modified(self) -> bool:
        return self.translation_changed or self.rotation_changed or self.parent_changed

    def translation_delta(self) -> Vec3:
        return Vec3(
            self.current.translation.x - self.original.translation.x,
            self.current.translation.y - self.original.translation.y,
            self.current.translation.z - self.original.translation.z,
        )


# ── edit session ─────────────────────────────────────────────────────


class EditSession:
    """Records commands, replays them onto vanilla, and emits bytes plus a plan."""

    def __init__(self, base: Mapping[str, bytes]) -> None:
        from .animation import is_actionchart

        self._base: Dict[str, bytes] = {
            path: bytes(data) for path, data in base.items()
            if is_socket_file(path) or is_descriptor_file(path) or is_actionchart(path)
        }
        self._commands: List[Command] = []
        self._cursor = 0  # commands[:cursor] are applied; the tail is redoable
        self._documents: Dict[str, object] = {}
        # Action charts are patched as bytes, not parsed into a document.
        self._charts: Dict[str, bytes] = {}
        #: Whole files supplied outright rather than edited. See `replace_file`.
        self._replacements: Dict[str, bytes] = {}
        #: Vanilla bytes for those files. `_base` deliberately holds only the XML and charts
        #: it knows how to parse, so a clip has no entry there to compare against.
        self._replaced_base: Dict[str, bytes] = {}
        #: What each replacement came from, for the pending-changes list.
        self._replacement_source: Dict[str, str] = {}
        self._replay()

    # ── base access ─────────────────────────────────────────────────

    @property
    def paths(self) -> List[str]:
        return sorted(self._base)

    def original_socket(self, game_path: str, name: str) -> Optional[Socket]:
        data = self._base.get(game_path)
        if data is None:
            return None
        return SocketDocument.load(data, game_path).socket_map().get(name)

    def socket(self, game_path: str, name: str) -> Optional[Socket]:
        document = self._documents.get(game_path)
        if not isinstance(document, SocketDocument):
            return None
        return document.socket_map().get(name)

    def state(self, game_path: str, name: str) -> Optional[SocketEditState]:
        original = self.original_socket(game_path, name)
        current = self.socket(game_path, name)
        if original is None or current is None:
            return None
        return SocketEditState(name, original, current)

    # ── history ─────────────────────────────────────────────────────

    @property
    def can_undo(self) -> bool:
        return self._cursor > 0

    @property
    def can_redo(self) -> bool:
        return self._cursor < len(self._commands)

    @property
    def command_count(self) -> int:
        return self._cursor

    def commands(self) -> List[Command]:
        return list(self._commands[: self._cursor])

    def undo(self) -> bool:
        if not self.can_undo:
            return False
        self._cursor -= 1
        self._replay()
        return True

    def redo(self) -> bool:
        if not self.can_redo:
            return False
        self._cursor += 1
        self._replay()
        return True

    def reset(self) -> None:
        self._commands = []
        self._cursor = 0
        self._replay()

    def _record(self, command: Command) -> None:
        # A new edit discards any redo tail, as in every editor.
        self._commands = self._commands[: self._cursor]
        if self._commands and self._commands[-1].coalesce_key == command.coalesce_key:
            self._commands[-1] = command  # a drag is one edit, not one per mouse event
        else:
            self._commands.append(command)
        self._cursor = len(self._commands)
        self._replay()

    # ── replay ──────────────────────────────────────────────────────

    def _replay(self) -> None:
        from .animation import is_actionchart

        self._documents = {}
        self._charts = {}
        self._replacements = {}
        for path, data in self._base.items():
            if is_actionchart(path):
                self._charts[path] = data
            elif is_socket_file(path):
                self._documents[path] = SocketDocument.load(data, path)
            else:
                self._documents[path] = DescriptorDocument.load(data, path)

        for command in self._commands[: self._cursor]:
            self._apply(command)

    def _apply(self, command: Command) -> None:
        if command.kind == "replace_file":
            if command.payload is None:
                raise EditError("replace_file without a payload")
            self._replacements[command.game_path] = command.payload
            return
        if command.kind == "retarget":
            self._apply_retarget(command)
            return
        document = self._documents.get(command.game_path)
        if document is None:
            raise EditError(f"Not a loaded file: {command.game_path}")
        try:
            if command.kind == "translate" and isinstance(document, SocketDocument):
                document.set_translation(command.target, command.translation or Vec3())
            elif command.kind == "rotate" and isinstance(document, SocketDocument):
                document.set_rotation(command.target, command.rotation or Quat())
            elif command.kind == "reparent" and isinstance(document, SocketDocument):
                document.doc.set_attribute(
                    "Name", command.target, "Parent", command.text, container="SocketList"
                )
            elif command.kind == "add_socket" and isinstance(document, SocketDocument):
                if command.socket is None:
                    raise EditError("add_socket without a socket")
                document.add_socket(command.socket)
            elif command.kind == "route" and isinstance(document, DescriptorDocument):
                document.set_route(command.target, command.field_name, command.text)
            else:
                raise EditError(f"Cannot apply {command.kind} to {command.game_path}")
        except (XmlDocumentError, TransformError) as exc:
            raise EditError(f"{command.describe()}: {exc}") from exc

    def _apply_retarget(self, command: Command) -> None:
        """Tier C: same-length socket rename inside an action chart."""

        from . import paac
        from .animation import RetargetError

        data = self._charts.get(command.game_path)
        if data is None:
            raise EditError(f"Not a loaded action chart: {command.game_path}")
        old, new = command.field_name, command.text
        try:
            self._charts[command.game_path] = paac.retarget(data, old, new)
        except (paac.PaacPatchError, RetargetError) as exc:
            raise EditError(f"{command.describe()}: {exc}") from exc

    # ── edits ───────────────────────────────────────────────────────

    def charts(self) -> List[str]:
        return sorted(self._charts)

    def chart_bytes(self, game_path: str) -> Optional[bytes]:
        return self._charts.get(game_path)

    def replace_clip(
        self, game_path: str, data: bytes, source: str = "", original: Optional[bytes] = None
    ) -> None:
        """Ship a different animation at an existing clip's path.

        This is how the shipped mods actually change a draw, and it is worth spelling out why
        it beats editing the action chart. A chart names each clip as a length-prefixed full
        path, so pointing it somewhere else means finding a replacement of exactly the same
        byte length — and measured across every chart for `1_phm`, none of the 31 referenced
        hip draws has one. Overwriting the *file* sidesteps that entirely: the chart still
        names the same path, and the bytes behind it are the animation you chose.

        Verified against `1H Sword Back Carry and Draw Animations`, which does precisely this
        — its `cd_phm_sword_00_01_normal_stand_weapon_out_000.paa` is a byte-identical copy of
        the vanilla longsword draw.
        """

        if not data:
            raise EditError(f"Refusing to write an empty clip to {game_path}")
        if original is not None:
            self._replaced_base[game_path] = bytes(original)
        if source:
            self._replacement_source[game_path] = source
        self._record(
            Command("replace_file", game_path, game_path, text=source, payload=data)
        )

    def retarget(self, game_path: str, old_name: str, new_name: str) -> None:
        """Point an action chart at a different socket of the same name length.

        The socket must already be defined somewhere — Tier C depends on Tier A2, because a
        retarget target is usually a socket the user has just created.
        """

        from .animation import retarget_candidates

        if game_path not in self._charts:
            raise EditError(f"Not a loaded action chart: {game_path}")
        if len(old_name) != len(new_name):
            raise EditError(
                f"Same-length only: {old_name!r} ({len(old_name)}) != {new_name!r} ({len(new_name)})"
            )
        if not self._socket_defined(new_name):
            raise EditError(
                f"Socket {new_name!r} is not defined by any loaded file; "
                "create the definition before retargeting to it"
            )
        allowed = retarget_candidates(old_name, defined_sockets=self.defined_sockets())
        if new_name not in allowed:
            raise EditError(f"{new_name!r} is not a valid retarget for {old_name!r}")
        self._record(Command("retarget", game_path, old_name, old_name, text=new_name))

    def defined_sockets(self) -> List[str]:
        """Every socket name defined by the loaded socket files, including pending additions."""

        names: set[str] = set()
        for document in self._documents.values():
            if isinstance(document, SocketDocument):
                names.update(document.socket_map())
        return sorted(names)

    def set_translation(self, game_path: str, name: str, value: Vec3) -> None:
        if self.socket(game_path, name) is None:
            raise EditError(f"No socket {name!r} in {game_path}")
        self._record(Command("translate", game_path, name, "Translation", translation=value))

    def nudge(self, game_path: str, name: str, dx: float = 0.0, dy: float = 0.0, dz: float = 0.0) -> None:
        """Offset from the socket's *current* value, recorded as an absolute."""

        current = self.socket(game_path, name)
        if current is None:
            raise EditError(f"No socket {name!r} in {game_path}")
        self.set_translation(game_path, name, current.translation.offset(dx, dy, dz))

    def set_rotation_euler(self, game_path: str, name: str, roll: float, pitch: float, yaw: float) -> None:
        """Author rotation in degrees; conversion and normalization happen here only."""

        if self.socket(game_path, name) is None:
            raise EditError(f"No socket {name!r} in {game_path}")
        self._record(
            Command(
                "rotate", game_path, name, "Rotation",
                rotation=Quat.from_euler_degrees(roll, pitch, yaw),
            )
        )

    def rotate_by(self, game_path: str, name: str, axis: Vec3, degrees: float) -> None:
        """Twist a socket about `axis` (in the socket's own space) by `degrees`.

        Composed in quaternion space and recorded as the resulting absolute rotation, so drags
        coalesce like translation does and gimbal lock cannot corrupt the result — which a
        euler-based gizmo would, since several weapon child sockets sit at pitch +/-90.
        """

        current = self.socket(game_path, name)
        if current is None:
            raise EditError(f"No socket {name!r} in {game_path}")
        if abs(degrees) < 1e-9:
            return
        turned = current.rotation.then(Quat.from_axis_angle(axis, degrees))
        self._record(Command("rotate", game_path, name, "Rotation", rotation=turned))

    def set_rotation_quaternion(self, game_path: str, name: str, value: Quat) -> None:
        """Copy a known-good quaternion verbatim — the guide's sanctioned rotation route."""

        if not value.is_normalized():
            raise EditError("Refusing a non-normalized quaternion")
        self._record(Command("rotate", game_path, name, "Rotation", rotation=value))

    def reparent(self, game_path: str, name: str, bone: str) -> None:
        self._record(Command("reparent", game_path, name, "Parent", text=bone))

    def add_base_files(self, files: Mapping[str, bytes]) -> int:
        """Register several vanilla files at once, replaying only after the last.

        `add_base_file` replays on every call, which is right for one file and quadratic for a
        hundred — and a character's chart set is a hundred.
        """

        added = 0
        for game_path, data in files.items():
            if data and game_path not in self._base:
                self._base[game_path] = bytes(data)
                added += 1
        if added:
            self._replay()
        return added

    def add_base_file(self, game_path: str, data: bytes) -> bool:
        """Register another vanilla file, so edits can be made against it.

        The baseline is pinned to what one character needs; a second character's action charts
        live in the packages. Without them the charts on screen belonged to somebody else.

        Returns whether anything was added. Existing entries are left alone — the pinned copy
        is the one every command so far was replayed onto, and swapping it underneath would
        silently change what those commands mean.
        """

        if not data or game_path in self._base:
            return False
        self._base[game_path] = bytes(data)
        self._replay()
        return True

    def add_socket(self, game_path: str, socket: Socket) -> None:
        """Create a socket *definition*. Safe; referencing an undefined socket is not.

        The name is validated here rather than in the dialog, because a name that survives to
        the file is one an action chart may later have to carry: `.paac` stores socket references
        as length-prefixed ASCII, so a non-ASCII or quote-bearing name would corrupt either the
        chart or the XML it is written into.
        """

        document = self._documents.get(game_path)
        if not isinstance(document, SocketDocument):
            raise EditError(f"Not a socket file: {game_path}")
        problem = socket_name_problem(socket.name)
        if problem:
            raise EditError(problem)
        if socket.name in document.socket_map():
            raise EditError(f"Socket {socket.name!r} already defined")
        self._record(Command("add_socket", game_path, socket.name, socket=socket))

    def set_route(self, game_path: str, part: str, field_name: str, socket_name: str) -> None:
        """Point a descriptor row at a different socket.

        The socket must exist after every pending `add_socket` — the invariant that keeps a
        route from dangling, which is the failure mode that crashed the earlier studio.
        """

        if field_name not in _ROUTE_FIELDS:
            raise EditError(f"Not a routable field: {field_name!r}")
        if socket_name and not self._socket_defined(socket_name):
            raise EditError(
                f"Socket {socket_name!r} is not defined by any loaded file; "
                "create the definition before routing to it"
            )
        self._record(Command("route", game_path, part, field_name, text=socket_name))

    def _socket_defined(self, name: str) -> bool:
        return any(
            isinstance(document, SocketDocument) and name in document.socket_map()
            for document in self._documents.values()
        )

    # ── output ──────────────────────────────────────────────────────

    def modified_paths(self) -> List[str]:
        changed = [
            path
            for path, document in self._documents.items()
            if document.to_bytes() != self._base.get(path)
        ]
        changed.extend(
            path for path, data in self._charts.items() if data != self._base.get(path)
        )
        changed.extend(
            path
            for path, data in self._replacements.items()
            if data != self._replaced_base.get(path, self._base.get(path))
        )
        return sorted(set(changed))

    def preview(self) -> Dict[str, bytes]:
        """Edited bytes for every touched file, plus any mirrored descriptor alias."""

        output = {}
        for path in self.modified_paths():
            if path in self._replacements:
                output[path] = self._replacements[path]
            elif path in self._charts:
                output[path] = self._charts[path]
            else:
                output[path] = self._documents[path].to_bytes()
        for path, data in list(output.items()):
            if not is_descriptor_file(path):
                continue
            # The guide requires the root-level alias to stay byte-identical to its pair.
            for candidate, source in self._alias_pairs().items():
                if source == path:
                    output[candidate] = data
        return output

    def _alias_pairs(self) -> Dict[str, str]:
        pairs: Dict[str, str] = {}
        for path in self._base:
            source = descriptor_alias_source(path)
            if source:
                pairs[path] = source
        return pairs

    def to_plan(self, name: str = "edit") -> Plan:
        """Derive the Phase 0 operation list from the replayed output.

        Deriving rather than recording means the plan is a function of the bytes, so the two
        can never drift apart.
        """

        operations: List[Operation] = []
        preview = self.preview()
        for path in self.modified_paths():
            base = self._replaced_base.get(path, self._base.get(path))
            operations.extend(ops.derive_file(path, base, preview[path]))
        for alias, source in self._alias_pairs().items():
            if source in self.modified_paths():
                operations.append(
                    Operation("B2", "descriptor_alias", alias, "*", {"mirrors": source})
                )
        return Plan(name, tuple(operations))

    def diff(self) -> List[str]:
        """Human-readable summary of every pending change."""

        lines: List[str] = []
        preview = self.preview()
        for path in self.modified_paths():
            lines.append(path)
            source = self._replacement_source.get(path)
            if source:
                # A replaced file has no readable diff — say what it was replaced *with*,
                # which is the only thing that tells you whether the edit is the one you meant.
                lines.append(f"  animation replaced with {source}")
                continue
            for operation in ops.derive_file(path, self._base.get(path), preview[path]):
                lines.append(f"  {operation.describe()}")
        if not lines:
            lines.append("(no changes)")
        return lines

    def write(self, out_root) -> List[str]:
        """Write edited files under a directory, preserving game-relative paths."""

        from pathlib import Path

        root = Path(out_root)
        written: List[str] = []
        for path, data in self.preview().items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            written.append(path)
        return sorted(written)


def session_from_baseline(baseline, *, paths: Optional[Iterable[str]] = None) -> EditSession:
    """Build an edit session over the pinned vanilla baseline."""

    from .animation import is_actionchart

    wanted = list(paths) if paths is not None else baseline.paths()
    return EditSession(
        {
            path: baseline.read(path)
            for path in wanted
            if is_socket_file(path) or is_descriptor_file(path) or is_actionchart(path)
        }
    )
