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

import hashlib
import itertools
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


class ScopeError(EditError):
    """Raised when an edit falls outside the active operation's allowlists.

    A second enforcement layer behind the dialog's filtering. The dialog decides what to
    offer; this decides what may actually be recorded, so a bug in the offering cannot write
    a one-handed target path for a two-handed move.
    """


# ── commands ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Command:
    """One semantic edit, holding its final value rather than a delta.

    Absolute values are what make coalescing safe: dragging a socket across twenty mouse
    events collapses to one command, and replay is order-independent within a field.

    A command also carries which *operation* recorded it. That is what lets one accepted
    dialog be packaged, undone and reported on its own, rather than as an indistinguishable
    part of everything else the session has done.
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
    #: Which accepted operation recorded this. Empty for a free-form edit made outside one
    #: — a viewport nudge, say — which is exactly the kind of edit packaging must exclude.
    operation_id: str = ""
    equipment_unit_id: str = ""
    scope_kind: str = ""
    created_order: int = 0

    @property
    def coalesce_key(self) -> Tuple[str, str, str, str, str]:
        """Two commands collapse when they address the same field of the same thing.

        The operation is part of the key: two operations that happen to set the same field
        are two decisions and must stay separately undoable, even though a replay would
        settle on the later value either way.
        """

        return (self.operation_id, self.kind, self.game_path, self.target, self.field_name)

    @property
    def value_key(self) -> Tuple[object, ...]:
        """What this command settles the field to — for detecting cross-operation conflicts.

        Payload bytes are hashed rather than compared: two operations replacing the same
        clip with the same donor is a duplicate, not a conflict, and the whole payload has
        no business sitting in a conflict report.
        """

        payload = (
            hashlib.sha256(self.payload).hexdigest() if self.payload is not None else ""
        )
        socket = None
        if self.socket is not None:
            socket = (
                self.socket.name,
                self.socket.parent_bone,
                self.socket.rotation,
                self.socket.translation,
            )
        return (self.translation, self.rotation, self.text, socket, payload)

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


# ── operations ───────────────────────────────────────────────────────


#: Kinds of operation, so a report can say what the user actually asked for.
OP_MOVE_EQUIPMENT = "move_equipment"
OP_REPLACE_ANIMATIONS = "replace_animations"
OP_MANUAL_ORIENTATION = "manual_orientation"
OP_FREEFORM = "freeform"


@dataclass(frozen=True, slots=True)
class OperationScope:
    """Exactly what one accepted dialog may touch.

    Allowlists, never negative filters. An empty list means *nothing of that kind is
    allowed*, which is the reading that fails safe: an animation-only operation has no
    business writing a descriptor row, and a scope that forgot to name its socket files
    should stop rather than wave everything through.

    `enforce=False` exists for the free-form viewport editing that predates operations —
    a nudge, a hand-authored rotation — where there is no equipment unit to scope against.
    """

    kind: str = OP_FREEFORM
    equipment_unit_id: str = ""
    model: str = ""
    #: Where a placement operation is sending the item. Recorded on the scope because the
    #: preflight has to check the child socket's zone against it, and reading it back off the
    #: commands cannot tell a destination from an intermediate value.
    destination_socket: str = ""
    allowed_descriptor_parts: Tuple[str, ...] = ()
    allowed_descriptor_files: Tuple[str, ...] = ()
    allowed_socket_files: Tuple[str, ...] = ()
    allowed_animation_targets: Tuple[str, ...] = ()
    allowed_animation_families: Tuple[str, ...] = ()
    #: Socket names the operation may create. Empty means any valid name, still bounded by
    #: `allowed_socket_files`; naming them pins a replay to the sockets that were reviewed.
    allowed_socket_names: Tuple[str, ...] = ()
    enforce: bool = True

    @classmethod
    def unrestricted(cls, kind: str = OP_FREEFORM, **fields) -> "OperationScope":
        return cls(kind=kind, enforce=False, **fields)

    def allows_descriptor(self, game_path: str, part: str) -> str:
        if not self.enforce:
            return ""
        if part not in self.allowed_descriptor_parts:
            return f"{part} is not part of this operation's equipment unit"
        if game_path not in self.allowed_descriptor_files:
            return f"{game_path} is not a descriptor file this operation may change"
        return ""

    def allows_socket_file(self, game_path: str) -> str:
        if not self.enforce:
            return ""
        if game_path not in self.allowed_socket_files:
            return f"{game_path} is not a socket file this operation may change"
        return ""

    def allows_socket_name(self, name: str) -> str:
        if not self.enforce or not self.allowed_socket_names:
            return ""
        if name not in self.allowed_socket_names:
            return f"{name} is not a socket this operation declared it would create"
        return ""

    def allows_animation_target(self, game_path: str) -> str:
        if not self.enforce:
            return ""
        if game_path not in self.allowed_animation_targets:
            return f"{game_path} is not an animation target this operation may replace"
        return ""


@dataclass(frozen=True, slots=True)
class EditOperation:
    """One accepted workflow: its commands, its scope, and what it was allowed to touch."""

    operation_id: str
    kind: str
    equipment_unit_id: str
    baseline_revision: str
    commands: Tuple[Command, ...] = ()
    scope: OperationScope = field(default_factory=OperationScope)
    label: str = ""
    warnings_accepted: Tuple[str, ...] = ()
    #: `(socket name, where its aim came from)` for every socket the operation created, so a
    #: package report can state the provenance of each one rather than just its name.
    orientation_sources: Tuple[Tuple[str, str], ...] = ()
    #: Set once the user has looked at the orientation in the viewport and said it is right.
    #: A borrowed or hand-authored aim must not be packaged without it.
    orientation_reviewed: bool = False

    @property
    def empty(self) -> bool:
        return not self.commands

    def orientation_source(self, socket_name: str) -> str:
        return dict(self.orientation_sources).get(socket_name, "")

    @property
    def allowed_descriptor_parts(self) -> Tuple[str, ...]:
        return self.scope.allowed_descriptor_parts

    @property
    def allowed_socket_files(self) -> Tuple[str, ...]:
        return self.scope.allowed_socket_files

    @property
    def allowed_animation_targets(self) -> Tuple[str, ...]:
        return self.scope.allowed_animation_targets

    def routed_parts(self) -> Tuple[str, ...]:
        return tuple(sorted({c.target for c in self.commands if c.kind == "route"}))

    def created_sockets(self) -> Tuple[str, ...]:
        return tuple(sorted({c.target for c in self.commands if c.kind == "add_socket"}))

    def modified_sockets(self) -> Tuple[str, ...]:
        """Sockets whose transform this operation changed but did not itself create."""

        created = set(self.created_sockets())
        touched = {
            c.target for c in self.commands
            if c.kind in {"translate", "rotate", "reparent"}
        }
        return tuple(sorted(touched - created))

    def replaced_clips(self) -> Tuple[str, ...]:
        return tuple(sorted({c.game_path for c in self.commands if c.kind == "replace_file"}))

    def touched_paths(self) -> Tuple[str, ...]:
        return tuple(sorted({c.game_path for c in self.commands}))

    def counts(self) -> Dict[str, int]:
        return {
            "descriptor changes": len(self.routed_parts()),
            "sockets created": len(self.created_sockets()),
            "sockets modified": len(self.modified_sockets()),
            "animation replacements": len(self.replaced_clips()),
        }

    def describe(self) -> str:
        headline = self.label or f"{self.kind} {self.equipment_unit_id}".strip()
        detail = ", ".join(f"{count} {name}" for name, count in self.counts().items() if count)
        return f"{headline}  —  {detail}" if detail else headline

    def summary_lines(self) -> List[str]:
        lines = [self.label or self.kind]
        for name, count in self.counts().items():
            if count:
                lines.append(f"  {count} {name}")
        return lines


@dataclass(frozen=True, slots=True)
class OperationConflict:
    """Two selected operations that settle the same field to different values."""

    game_path: str
    target: str
    field_name: str
    left: str
    right: str
    reason: str = "different final value"

    def describe(self) -> str:
        where = f"{self.target}.{self.field_name}" if self.field_name else self.target
        return f"{self.game_path} :: {where}: {self.left} and {self.right} disagree ({self.reason})"


class OperationHandle:
    """A live operation. Every edit made through it belongs to it and is scope-checked.

    Nothing enters the session's *operation* history until `commit`; `rollback` removes the
    operation's commands outright. The commands are recorded into the session as they are
    made rather than buffered, because the viewport has to show the move being previewed —
    but the range is exactly bounded, so rolling back is a truncation and cannot leave a
    partly applied route behind.
    """

    __slots__ = ("_session", "operation_id", "scope", "label", "_mark", "_order", "_closed",
                 "_warnings", "_orientation_sources", "_orientation_reviewed")

    def __init__(self, session: "EditSession", operation_id: str, scope: OperationScope,
                 *, label: str = "", mark: int = 0) -> None:
        self._session = session
        self.operation_id = operation_id
        self.scope = scope
        self.label = label
        self._mark = mark
        self._order = itertools.count()
        self._closed = False
        self._warnings: List[str] = []
        self._orientation_sources: Dict[str, str] = {}
        self._orientation_reviewed = False

    # ── recording ───────────────────────────────────────────────────

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def mark(self) -> int:
        return self._mark

    def next_order(self) -> int:
        return next(self._order)

    def accept_warning(self, warning: str) -> None:
        """Record that the user was shown a high-risk warning and went ahead anyway."""

        if warning and warning not in self._warnings:
            self._warnings.append(warning)

    @property
    def warnings_accepted(self) -> Tuple[str, ...]:
        return tuple(self._warnings)

    def record_orientation(self, socket_name: str, source: str) -> None:
        """Note where a socket's aim came from — a template, a borrow, or the user's hand."""

        if socket_name:
            self._orientation_sources[socket_name] = source

    def mark_orientation_reviewed(self, reviewed: bool = True) -> None:
        """The user has looked at the aim in the viewport and accepted it."""

        self._orientation_reviewed = bool(reviewed)

    @property
    def orientation_reviewed(self) -> bool:
        return self._orientation_reviewed

    @property
    def orientation_sources(self) -> Tuple[Tuple[str, str], ...]:
        return tuple(sorted(self._orientation_sources.items()))

    # ── the edits an operation may make ─────────────────────────────

    def set_route(self, game_path: str, part: str, field_name: str, socket_name: str) -> None:
        self._session.set_route(game_path, part, field_name, socket_name)

    def add_socket(self, game_path: str, socket: Socket) -> None:
        self._session.add_socket(game_path, socket)

    def set_rotation_quaternion(self, game_path: str, name: str, value: Quat) -> None:
        self._session.set_rotation_quaternion(game_path, name, value)

    def set_rotation_euler(self, game_path: str, name: str, roll: float, pitch: float,
                           yaw: float) -> None:
        self._session.set_rotation_euler(game_path, name, roll, pitch, yaw)

    def set_translation(self, game_path: str, name: str, value: Vec3) -> None:
        self._session.set_translation(game_path, name, value)

    def replace_clip(self, game_path: str, data: bytes, source: str = "",
                     original: Optional[bytes] = None) -> None:
        self._session.replace_clip(game_path, data, source, original)

    # ── lifecycle ───────────────────────────────────────────────────

    def commit(self) -> EditOperation:
        return self._session._commit_operation(self)

    def rollback(self) -> None:
        self._session._rollback_operation(self)

    def __enter__(self) -> "OperationHandle":
        return self

    def __exit__(self, exc_type, _exc, _tb) -> bool:
        if self._closed:
            return False
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        return False


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
        #: The operation currently recording, or `None` for free-form editing.
        self._active: Optional[OperationHandle] = None
        #: Metadata per committed operation. The *live* list is derived from the surviving
        #: commands, so an undone or discarded operation cannot linger in the history.
        self._operation_records: Dict[str, EditOperation] = {}
        self._operation_counter = itertools.count(1)
        self._baseline_revision: str = ""
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

    def original_part(self, game_path: str, part_name: str):
        """A descriptor row as *vanilla* has it, whatever the session has since done.

        The dialog has to distinguish three states — vanilla, pending before this operation,
        proposed — and it could only show the third. That is how an earlier experiment's
        `Pelvis_R_Socket` came to read as the game's default.
        """

        data = self._base.get(game_path)
        if data is None:
            return None
        return DescriptorDocument.load(data, game_path).part_map().get(part_name)

    def part(self, game_path: str, part_name: str):
        """A descriptor row as the session currently has it — the pending state."""

        document = self._documents.get(game_path)
        if not isinstance(document, DescriptorDocument):
            return None
        return document.part_map().get(part_name)

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
        self._active = None
        self._operation_records = {}
        self._replay()

    def _record(self, command: Command) -> None:
        active = self._active
        if active is not None:
            command = replace(
                command,
                operation_id=active.operation_id,
                equipment_unit_id=active.scope.equipment_unit_id,
                scope_kind=active.scope.kind,
                created_order=active.next_order(),
            )
        # A new edit discards any redo tail, as in every editor.
        self._commands = self._commands[: self._cursor]
        if self._commands and self._commands[-1].coalesce_key == command.coalesce_key:
            self._commands[-1] = command  # a drag is one edit, not one per mouse event
        else:
            self._commands.append(command)
        self._cursor = len(self._commands)
        self._replay()

    # ── operations ──────────────────────────────────────────────────

    @property
    def active_operation(self) -> Optional[OperationHandle]:
        return self._active

    @property
    def baseline_revision(self) -> str:
        """A digest of the pinned vanilla bytes every command was replayed onto.

        Recorded on each operation so a replay can prove it was made against the same game
        files. Computed lazily — it hashes the whole baseline — and cached until the baseline
        grows.
        """

        if not self._baseline_revision:
            digest = hashlib.sha256()
            for path in sorted(self._base):
                digest.update(path.encode("utf-8"))
                digest.update(b"\0")
                digest.update(hashlib.sha256(self._base[path]).digest())
            self._baseline_revision = digest.hexdigest()[:16]
        return self._baseline_revision

    def begin_operation(self, scope: Optional[OperationScope] = None, *,
                        label: str = "") -> OperationHandle:
        """Start one isolated operation. Commit or roll back before starting another."""

        if self._active is not None:
            raise EditError(
                f"Operation {self._active.operation_id} is still open; commit or roll it back "
                f"before starting another"
            )
        scope = scope or OperationScope.unrestricted()
        number = next(self._operation_counter)
        operation_id = f"op-{number:03d}-{self.baseline_revision[:6]}"
        handle = OperationHandle(self, operation_id, scope, label=label, mark=self._cursor)
        self._active = handle
        return handle

    def _commit_operation(self, handle: OperationHandle) -> EditOperation:
        if handle.closed:
            raise EditError(f"Operation {handle.operation_id} is already closed")
        commands = tuple(self._commands[handle.mark : self._cursor])
        record = EditOperation(
            operation_id=handle.operation_id,
            kind=handle.scope.kind,
            equipment_unit_id=handle.scope.equipment_unit_id,
            baseline_revision=self.baseline_revision,
            commands=commands,
            scope=handle.scope,
            label=handle.label,
            warnings_accepted=handle.warnings_accepted,
            orientation_sources=handle.orientation_sources,
            orientation_reviewed=handle.orientation_reviewed,
        )
        handle._closed = True
        self._active = None
        if commands:
            self._operation_records[handle.operation_id] = record
        return record

    def _rollback_operation(self, handle: OperationHandle) -> None:
        if handle.closed:
            return
        # Absolute values make this a truncation rather than a sequence of inverse edits, so
        # a half-applied move is not representable.
        self._commands = self._commands[: handle.mark]
        self._cursor = min(self._cursor, handle.mark)
        handle._closed = True
        self._active = None
        self._replay()

    def operations(self) -> List[EditOperation]:
        """The committed operations still standing, oldest first.

        Derived from the surviving commands rather than kept as a second list — the same
        rule the plan follows — so undo, redo and discard cannot leave a phantom entry that
        packaging would then replay.
        """

        grouped: Dict[str, List[Command]] = {}
        order: List[str] = []
        for command in self._commands[: self._cursor]:
            if not command.operation_id:
                continue
            if command.operation_id not in grouped:
                grouped[command.operation_id] = []
                order.append(command.operation_id)
            grouped[command.operation_id].append(command)

        out: List[EditOperation] = []
        for operation_id in order:
            commands = tuple(grouped[operation_id])
            record = self._operation_records.get(operation_id)
            if record is None:
                record = EditOperation(
                    operation_id=operation_id,
                    kind=commands[0].scope_kind or OP_FREEFORM,
                    equipment_unit_id=commands[0].equipment_unit_id,
                    baseline_revision=self.baseline_revision,
                )
            out.append(replace(record, commands=commands))
        return out

    def operation(self, operation_id: str) -> Optional[EditOperation]:
        return next(
            (op for op in self.operations() if op.operation_id == operation_id), None
        )

    def latest_operation(self) -> Optional[EditOperation]:
        operations = self.operations()
        return operations[-1] if operations else None

    def loose_commands(self) -> List[Command]:
        """Edits made outside any operation. Never packaged, always reported."""

        return [c for c in self._commands[: self._cursor] if not c.operation_id]

    def start_clean_operation(self) -> int:
        """Drop every edit that belongs to no operation, keeping the committed ones.

        The state a new operation should start from: vanilla plus what has actually been
        accepted. A free-form nudge left over from a previous session of poking about is not a
        decision anybody made about this item, and it would ride along in every later preview.

        Returns how many edits were dropped.
        """

        if self._active is not None:
            raise EditError(
                f"Operation {self._active.operation_id} is still open; commit or roll it back "
                f"first"
            )
        dropped = sum(1 for c in self._commands if not c.operation_id)
        if not dropped:
            return 0
        removed_before_cursor = sum(
            1 for c in self._commands[: self._cursor] if not c.operation_id
        )
        self._commands = [c for c in self._commands if c.operation_id]
        self._cursor -= removed_before_cursor
        self._replay()
        return dropped

    def undo_operation(self) -> str:
        """Undo the newest operation whole, or the newest free-form edit. "" if nothing."""

        if self._cursor == 0:
            return ""
        operation_id = self._commands[self._cursor - 1].operation_id
        if not operation_id:
            self.undo()
            return ""
        while (
            self._cursor > 0
            and self._commands[self._cursor - 1].operation_id == operation_id
        ):
            self._cursor -= 1
        self._replay()
        return operation_id

    def redo_operation(self) -> str:
        if self._cursor >= len(self._commands):
            return ""
        operation_id = self._commands[self._cursor].operation_id
        if not operation_id:
            self.redo()
            return ""
        while (
            self._cursor < len(self._commands)
            and self._commands[self._cursor].operation_id == operation_id
        ):
            self._cursor += 1
        self._replay()
        return operation_id

    def discard_operation(self, operation_id: str) -> bool:
        """Remove an operation's commands outright, wherever it sits in the history.

        Sound because every command holds an absolute value: dropping one operation and
        replaying the rest gives the state those others describe, with no residue.
        """

        if not operation_id:
            return False
        removed_before_cursor = sum(
            1 for c in self._commands[: self._cursor] if c.operation_id == operation_id
        )
        kept = [c for c in self._commands if c.operation_id != operation_id]
        if len(kept) == len(self._commands):
            return False
        self._commands = kept
        self._cursor -= removed_before_cursor
        self._operation_records.pop(operation_id, None)
        self._replay()
        return True

    # ── isolated replay ─────────────────────────────────────────────

    def isolated_session(self, operation_ids: Sequence[str]) -> "EditSession":
        """A fresh session over the pinned vanilla baseline with only these operations replayed.

        This is what makes an earlier shield edit *structurally* unable to enter a later
        sword package: the isolated session never saw its commands, so no filtering step has
        to remember to exclude it.
        """

        wanted = set(operation_ids)
        isolated = EditSession(self._base)
        isolated._replaced_base = dict(self._replaced_base)
        isolated._replacement_source = dict(self._replacement_source)
        isolated._operation_records = {
            key: value for key, value in self._operation_records.items() if key in wanted
        }
        isolated._commands = [
            command
            for command in self._commands[: self._cursor]
            if command.operation_id in wanted
        ]
        isolated._cursor = len(isolated._commands)
        isolated._replay()
        return isolated

    def preview_for_operations(self, operation_ids: Sequence[str]) -> Dict[str, bytes]:
        return self.isolated_session(operation_ids).preview()

    def plan_for_operations(self, operation_ids: Sequence[str], name: str = "operation") -> Plan:
        return self.isolated_session(operation_ids).to_plan(name)

    def operation_conflicts(self, operation_ids: Sequence[str]) -> List[OperationConflict]:
        """Fields two selected operations settle differently. Same value is a duplicate."""

        wanted = list(dict.fromkeys(operation_ids))
        seen: Dict[Tuple[str, str, str, str], Tuple[str, Tuple[object, ...]]] = {}
        conflicts: List[OperationConflict] = []
        created: Dict[str, str] = {}
        for command in self._commands[: self._cursor]:
            if command.operation_id not in wanted:
                continue
            key = (command.kind, command.game_path, command.target, command.field_name)
            previous = seen.get(key)
            if previous is None:
                seen[key] = (command.operation_id, command.value_key)
            elif previous[0] != command.operation_id and previous[1] != command.value_key:
                conflicts.append(
                    OperationConflict(
                        command.game_path,
                        command.target,
                        command.field_name,
                        previous[0],
                        command.operation_id,
                    )
                )
            if command.kind == "add_socket":
                created[command.target] = command.operation_id

        # A socket one operation created and another then re-aimed is a hidden dependency:
        # packaging either alone gives a different result from packaging both.
        for command in self._commands[: self._cursor]:
            if command.operation_id not in wanted:
                continue
            if command.kind not in {"translate", "rotate", "reparent"}:
                continue
            owner = created.get(command.target)
            if owner and owner != command.operation_id:
                conflicts.append(
                    OperationConflict(
                        command.game_path,
                        command.target,
                        command.field_name,
                        owner,
                        command.operation_id,
                        reason="one operation edits a socket another created",
                    )
                )
        return conflicts

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
        self._check_scope_animation(game_path)
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

    def sockets_in(self, game_path: str) -> List[str]:
        """Socket names one file defines right now, pending additions included.

        The authority for whether a name is free. The resolver's view is rebuilt from a preview
        and can lag by an operation; a uniqueness check that lags produces a duplicate.
        """

        document = self._documents.get(game_path)
        if not isinstance(document, SocketDocument):
            return []
        return sorted(document.socket_map())

    def set_translation(self, game_path: str, name: str, value: Vec3) -> None:
        if self.socket(game_path, name) is None:
            raise EditError(f"No socket {name!r} in {game_path}")
        self._check_scope_socket_file(game_path)
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
        self._check_scope_socket_file(game_path)
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
        self._check_scope_socket_file(game_path)
        turned = current.rotation.then(Quat.from_axis_angle(axis, degrees))
        self._record(Command("rotate", game_path, name, "Rotation", rotation=turned))

    def set_rotation_quaternion(self, game_path: str, name: str, value: Quat) -> None:
        """Copy a known-good quaternion verbatim — the guide's sanctioned rotation route."""

        if not value.is_normalized():
            raise EditError("Refusing a non-normalized quaternion")
        self._check_scope_socket_file(game_path)
        self._record(Command("rotate", game_path, name, "Rotation", rotation=value))

    def reparent(self, game_path: str, name: str, bone: str) -> None:
        self._check_scope_socket_file(game_path)
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
            self._baseline_revision = ""
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
        self._baseline_revision = ""
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
        self._check_scope_socket_file(game_path, name=socket.name, creating=True)
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
        problem = (
            self._active.scope.allows_descriptor(game_path, part)
            if self._active is not None else ""
        )
        if problem:
            raise ScopeError(problem)
        self._record(Command("route", game_path, part, field_name, text=socket_name))

    def _socket_defined(self, name: str) -> bool:
        return any(
            isinstance(document, SocketDocument) and name in document.socket_map()
            for document in self._documents.values()
        )

    # ── scope enforcement ───────────────────────────────────────────

    def _check_scope_socket_file(self, game_path: str, *, name: str = "",
                                 creating: bool = False) -> None:
        if self._active is None:
            return
        scope = self._active.scope
        problem = scope.allows_socket_file(game_path)
        if not problem and creating:
            problem = scope.allows_socket_name(name)
        if problem:
            raise ScopeError(problem)

    def _check_scope_animation(self, game_path: str) -> None:
        if self._active is None:
            return
        problem = self._active.scope.allows_animation_target(game_path)
        if problem:
            raise ScopeError(problem)

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
