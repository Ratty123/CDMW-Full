"""Semantic commands and operation transaction records for Placement Studio editing."""

from __future__ import annotations

import hashlib
import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .model import Quat, Socket, Vec3

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
