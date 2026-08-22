"""One move, planned whole before any of it is applied.

The dialog used to apply as it went: re-route the body socket, then follow the child socket,
then check the orientation, then swap animations — each step reporting into the status bar and
none of them able to undo the last. A failure halfway left a weapon on a new socket with its
sheath on the old one, and the animation swap ran anyway.

Here the whole move is resolved first into a `MovePlan`: which rows move, which child socket
each one gets, which sockets have to be created, what is blocked and what needs confirming.
Applying it is then a single operation that either lands complete or rolls back to nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import carry
from .editing import (
    OP_MOVE_EQUIPMENT,
    OP_REPLACE_ANIMATIONS,
    EditError,
    EditOperation,
    EditSession,
    OperationScope,
)
from .model import EquipmentUnit, LinkedPart, Socket
from .orientation import (
    SOURCE_BORROWED_ZONE,
    SOURCE_MANUAL,
    OrientationTemplate,
    SocketEditDecision,
    clone_socket,
    free_operation_socket_name,
)


@dataclass(frozen=True, slots=True)
class StateRow:
    """One field of the three-state comparison the review page has to show."""

    field_label: str
    vanilla: str = ""
    pending: str = ""
    proposed: str = ""

    @property
    def changed_by_this_operation(self) -> bool:
        return self.proposed != self.pending

    @property
    def already_changed(self) -> bool:
        """The pending state is not vanilla — an earlier operation moved this."""

        return self.pending != self.vanilla

    def describe(self) -> str:
        return (
            f"{self.field_label:<24} {self.vanilla or '-':<32} "
            f"{self.pending or '-':<32} {self.proposed or '-'}"
        )


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """What happens to one descriptor row: where it goes, and what aims it there."""

    part_name: str
    role: str
    source_file: str
    destination_socket: str
    current_child: str = ""
    proposed_child: str = ""
    socket_file: str = ""
    template: OrientationTemplate = field(default_factory=OrientationTemplate)
    creates_socket: bool = False
    clone_decision: Optional[SocketEditDecision] = None
    blocked: str = ""

    @property
    def is_primary(self) -> bool:
        return self.role == "primary"

    @property
    def orientation_source(self) -> str:
        return self.template.source

    def describe(self) -> str:
        aim = self.proposed_child or "(unchanged)"
        note = f"  BLOCKED: {self.blocked}" if self.blocked else ""
        return f"{self.part_name} [{self.role}] -> {self.destination_socket} aimed by {aim}{note}"


@dataclass(frozen=True, slots=True)
class MoveRequest:
    """What the user asked for, as one immutable object."""

    unit: EquipmentUnit
    destination_socket: str
    scope: carry.AnimationScope = field(default_factory=carry.AnimationScope)
    #: Linked rows that come along. Required rows are included whether named or not unless
    #: they appear in `leave_behind`.
    include_links: Tuple[str, ...] = ()
    #: Required rows the user explicitly chose to leave where they are. High risk, and every
    #: one lands in the operation manifest.
    leave_behind: Tuple[str, ...] = ()
    replacements: Tuple[carry.AnimationReplacement, ...] = ()
    orientation_reviewed: bool = False
    #: Whether the user has accepted the advanced-scope confirmation, when one is needed.
    advanced_confirmed: bool = False

    @property
    def moves(self) -> bool:
        return bool(self.destination_socket)

    @property
    def destination_zone(self) -> str:
        return carry.zone_of(self.destination_socket)


@dataclass(frozen=True, slots=True)
class MovePlan:
    """The whole move, resolved. Nothing here has been applied."""

    request: MoveRequest
    states: Tuple[StateRow, ...] = ()
    routes: Tuple[RouteDecision, ...] = ()
    new_sockets: Tuple[Tuple[str, str], ...] = ()  # (socket file, socket name)
    blockers: Tuple[str, ...] = ()
    confirmations: Tuple[str, ...] = ()
    earlier_operations: Tuple[str, ...] = ()
    placement_changes: bool = False

    @property
    def unit(self) -> EquipmentUnit:
        return self.request.unit

    @property
    def animation_count(self) -> int:
        return len(self.request.replacements)

    @property
    def blocked(self) -> bool:
        return bool(self.blockers)

    @property
    def changes_anything(self) -> bool:
        return self.placement_changes or bool(self.request.replacements)

    def action_label(self) -> str:
        """Button text that matches what will happen — 4.4's `Move it` problem.

        A placement no-op must never be presented as a move. `Move it` shipped hundreds of
        animation replacements for a weapon that had not moved, because the button was enabled
        by the animation list and labelled by the dialog's title.
        """

        moved = [route.part_name for route in self.routes if route.destination_socket]
        rows = len(moved)
        animations = self.animation_count
        if not self.changes_anything:
            return "No changes"
        if self.placement_changes and animations:
            noun = "weapon and case" if rows > 1 else "weapon"
            return f"Move {noun}, replace {animations} animations"
        if self.placement_changes:
            return "Move weapon and case" if rows > 1 else "Move weapon"
        return f"Replace {animations} animations"

    def scope_for(self, *, model: str = "") -> OperationScope:
        """The allowlists this move is entitled to, and nothing wider."""

        request = self.request
        unit = request.unit
        parts = tuple(dict.fromkeys(route.part_name for route in self.routes))
        socket_files = tuple(dict.fromkeys(
            [route.socket_file for route in self.routes if route.socket_file]
        ))
        socket_names = tuple(dict.fromkeys(name for _file, name in self.new_sockets))
        kind = OP_MOVE_EQUIPMENT if self.placement_changes else OP_REPLACE_ANIMATIONS
        return OperationScope(
            kind=kind,
            equipment_unit_id=unit.unit_id,
            model=model or unit.model,
            destination_socket=request.destination_socket,
            allowed_descriptor_parts=parts,
            allowed_descriptor_files=unit.allowed_descriptor_files,
            allowed_socket_files=socket_files or unit.allowed_socket_files,
            allowed_animation_targets=carry.animation_target_allowlist(request.replacements),
            allowed_animation_families=unit.target_animation_families,
            allowed_socket_names=socket_names,
        )

    def review_lines(self) -> List[str]:
        """The review page, in text, so a headless test asserts the same thing a user reads."""

        request = self.request
        unit = request.unit
        targets, donors = carry.family_counts(request.replacements)
        lines = [
            "Equipment",
            f"  {unit.primary_part}",
            "",
            "Linked parts",
        ]
        lines += [f"  {link.describe()}" for link in unit.linked_parts] or ["  (none)"]
        lines += [
            "",
            "Placement",
            f"  {unit.in_socket or '(nowhere)'} -> {request.destination_socket or '(unchanged)'}"
            f"  [{request.destination_zone or '-'}]",
            "",
            "Orientation",
        ]
        for route in self.routes:
            lines.append(f"  {route.part_name}: {route.template.describe()}")
        lines += [
            f"  Existing shared sockets modified: "
            f"{sum(1 for r in self.routes if r.clone_decision and not r.clone_decision.clone_required and r.clone_decision.shared)}",
            "",
            "Animations",
            f"  Scope: {request.scope.label}",
            f"  Target families: {', '.join(f'{k}: {v}' for k, v in targets.items()) or 'none'}",
            f"  Donor families: {', '.join(f'{k}: {v}' for k, v in donors.items()) or 'none'}",
        ]
        risks = carry.risk_summary(request.replacements)
        lines += [
            f"  Borrowed-character clips: {risks['borrowed']}",
            f"  Mounted clips: {risks['mounted']}",
            "",
            f"Earlier operations, excluded from this one: {len(self.earlier_operations)}",
        ]
        if self.confirmations:
            lines += ["", "Confirm"]
            lines += [f"  - {item}" for item in self.confirmations]
        if self.blockers:
            lines += ["", "Blocked"]
            lines += [f"  - {item}" for item in self.blockers]
        return lines


# ── planning ─────────────────────────────────────────────────────────


def _state_rows(session, edits: EditSession, unit: EquipmentUnit,
                routes: Sequence[RouteDecision]) -> Tuple[StateRow, ...]:
    """Vanilla, pending, proposed for the primary row and every linked row."""

    proposed = {route.part_name: route for route in routes}
    rows: List[StateRow] = []
    order = [(unit.primary_part, unit.primary_source_file, "Weapon")]
    order += [
        (link.part_name, link.source_file, link.role.capitalize())
        for link in unit.linked_parts
    ]
    for part_name, source_file, label in order:
        vanilla = edits.original_part(source_file, part_name)
        pending = edits.part(source_file, part_name) or vanilla
        route = proposed.get(part_name)
        rows.append(
            StateRow(
                f"{label} body socket",
                getattr(vanilla, "in_socket", "") or "",
                getattr(pending, "in_socket", "") or "",
                (route.destination_socket if route else
                 getattr(pending, "in_socket", "") or ""),
            )
        )
        rows.append(
            StateRow(
                f"{label} child socket",
                getattr(vanilla, "in_child_socket", "") or "",
                getattr(pending, "in_child_socket", "") or "",
                (route.proposed_child or getattr(pending, "in_child_socket", "") or ""
                 if route else getattr(pending, "in_child_socket", "") or ""),
            )
        )
    return tuple(rows)


def _socket_file_for(session, part_name: str, unit: EquipmentUnit, *, link: Optional[LinkedPart]):
    """Which asset file aims this row — the weapon's own, or the case's own.

    C5: the weapon and the case have different geometry and different local axes, so each one
    needs its own child-socket decision. Writing the case's aim into the weapon's file would
    also put it in the wrong package payload.
    """

    if link is None:
        return unit.weapon_path
    case_asset = None
    weapon = None
    for candidate in session.weapons():
        if candidate.weapon_id == unit.weapon_id:
            weapon = candidate
        if candidate.weapon_id == f"{unit.weapon_id}_in":
            case_asset = candidate
    if link.role in ("case", "sheath", "scabbard", "quiver", "holster") and case_asset:
        return case_asset.game_path
    return getattr(weapon, "game_path", "") or unit.weapon_path


def _asset_for_file(session, game_path: str):
    return next((w for w in session.weapons() if w.game_path == game_path), None)


def _defined_socket_names(edits: EditSession, game_path: str) -> Tuple[str, ...]:
    """Socket names the edit session's own copy of a file currently defines."""

    return tuple(edits.sockets_in(game_path))


def plan_move(session, edits: EditSession, request: MoveRequest) -> MovePlan:
    """Resolve one move without applying any of it.

    `session` is the live `PlacementSession`; `edits` is the session's `EditSession`. Both are
    read only here.
    """

    unit = request.unit
    destination = request.destination_socket
    zone = request.destination_zone

    blockers: List[str] = []
    confirmations: List[str] = []
    routes: List[RouteDecision] = []
    new_sockets: List[Tuple[str, str]] = []

    if request.scope.is_advanced and not request.advanced_confirmed:
        blockers.append(
            f"{request.scope.label} has not been confirmed. It replaces "
            f"{len(request.replacements)} files across the whole family and changes the "
            f"off-hand and stance as well."
        )

    wanted_links: List[LinkedPart] = []
    for link in unit.linked_parts:
        if link.part_name in request.leave_behind:
            if link.required_for_stow:
                confirmations.append(f"leave {link.part_name} behind")
            continue
        if link.required_for_stow or link.part_name in request.include_links:
            wanted_links.append(link)

    if destination:
        owned = set(unit.part_names)
        targets: List[Tuple[str, str, str, Optional[LinkedPart]]] = [
            (unit.primary_part, "primary", unit.primary_source_file, None)
        ]
        targets += [
            (link.part_name, link.role, link.source_file, link) for link in wanted_links
        ]

        for part_name, role, source_file, link in targets:
            socket_file = _socket_file_for(session, part_name, unit, link=link)
            asset = _asset_for_file(session, socket_file)
            current_part = edits.part(source_file, part_name)
            current_child = getattr(current_part, "in_child_socket", "") or (
                link.in_child_socket if link is not None else unit.in_child_socket
            )
            template = session.orientation_template(
                destination, current_child=current_child, weapon=asset
            )

            proposed_child = template.child_socket_name
            creates = False
            clone_decision = None
            if not proposed_child:
                # Nothing usable is defined for the destination, so the operation owns a new
                # socket rather than editing a shared one. 4.5 / C3.
                #
                # The names already in the *edit session's* copy of the file are what decide
                # uniqueness, not the resolver's — the resolver is rebuilt from a preview and
                # may lag a socket an earlier operation added.
                proposed_child = free_operation_socket_name(
                    part_name,
                    zone or "dest",
                    role="" if role == "primary" else role,
                    taken=_defined_socket_names(edits, socket_file),
                )
                creates = True
            elif proposed_child == current_child:
                clone_decision = session.socket_edit_decision(current_child, owned)
            else:
                clone_decision = session.socket_edit_decision(proposed_child, owned)

            blocked = ""
            if not socket_file:
                blocked = (
                    f"{part_name} has no asset file to define a child socket in, so its "
                    f"orientation cannot be resolved"
                )
            elif not source_file:
                blocked = f"{part_name} has no descriptor row to re-route"
            elif template.source == SOURCE_MANUAL and not request.orientation_reviewed:
                blocked = (
                    f"{part_name} has nothing compatible defined for the {zone or 'destination'}; "
                    f"aim it in the viewport and mark the orientation reviewed"
                )
            if blocked:
                blockers.append(blocked)

            if template.source == SOURCE_BORROWED_ZONE and not request.orientation_reviewed:
                confirmations.append(
                    f"{part_name} borrows its aim from {template.donor_weapon_id or 'another item'}; "
                    f"preview it with all linked geometry before committing"
                )

            if creates and socket_file:
                new_sockets.append((socket_file, proposed_child))

            routes.append(
                RouteDecision(
                    part_name=part_name,
                    role=role,
                    source_file=source_file,
                    destination_socket=destination,
                    current_child=current_child,
                    proposed_child=proposed_child,
                    socket_file=socket_file,
                    template=template,
                    creates_socket=creates,
                    clone_decision=clone_decision,
                    blocked=blocked,
                )
            )

    # A placement no-op is a placement no-op: when every row already hangs on the destination
    # with the aim it would be given, there is no move, and the button must not say there is.
    placement_changes = False
    for route in routes:
        pending = edits.part(route.source_file, route.part_name)
        if pending is None:
            placement_changes = True
            break
        if pending.in_socket != route.destination_socket:
            placement_changes = True
            break
        if route.proposed_child and pending.in_child_socket != route.proposed_child:
            placement_changes = True
            break

    confirmations.extend(carry.risk_warnings(request.replacements))
    if request.scope.include_borrowed and any(r.borrowed for r in request.replacements):
        confirmations.append("borrowed-character donor clips are included")
    if request.scope.include_mounted:
        confirmations.append("mounted clips are included")

    return MovePlan(
        request=request,
        states=_state_rows(session, edits, unit, routes),
        routes=tuple(routes),
        new_sockets=tuple(dict.fromkeys(new_sockets)),
        blockers=tuple(dict.fromkeys(blockers)),
        confirmations=tuple(dict.fromkeys(confirmations)),
        earlier_operations=tuple(op.operation_id for op in edits.operations()),
        placement_changes=placement_changes,
    )


# ── applying ─────────────────────────────────────────────────────────


class MoveBlocked(EditError):
    """Raised when a move cannot be applied as planned. Nothing has been recorded."""


def apply_move(
    session,
    edits: EditSession,
    plan: MovePlan,
    *,
    clip_bytes: Optional[Mapping[str, bytes]] = None,
    label: str = "",
) -> EditOperation:
    """Apply the whole plan as one operation, or leave the session exactly as it was.

    Atomic by construction: every edit goes through one `OperationHandle`, and any failure
    rolls the handle back, which truncates the command list to where it started. B4's "apply
    all required linked routes or apply none" is then a property of the transaction rather
    than a sequence of compensating edits somebody has to get right.
    """

    if plan.blocked:
        raise MoveBlocked("; ".join(plan.blockers))
    if not plan.changes_anything:
        raise MoveBlocked("Nothing would change, so there is no operation to record")

    unit = plan.unit
    scope = plan.scope_for()
    handle = edits.begin_operation(
        scope,
        label=label or _default_label(plan),
    )
    try:
        for warning in plan.confirmations:
            handle.accept_warning(warning)
        handle.mark_orientation_reviewed(plan.request.orientation_reviewed)

        for socket_file, socket_name in plan.new_sockets:
            route = next(
                (r for r in plan.routes
                 if r.socket_file == socket_file and r.proposed_child == socket_name),
                None,
            )
            if route is None:
                continue
            handle.add_socket(
                socket_file,
                clone_socket(route.template, name=socket_name, source_file=socket_file),
            )
            handle.record_orientation(socket_name, route.template.source)

        for route in plan.routes:
            if not route.destination_socket:
                continue
            handle.set_route(
                route.source_file, route.part_name, "in_socket", route.destination_socket
            )
            if route.proposed_child and route.proposed_child != route.current_child:
                handle.set_route(
                    route.source_file, route.part_name, "in_child_socket", route.proposed_child
                )
            if not route.creates_socket and route.proposed_child:
                handle.record_orientation(route.proposed_child, route.template.source)

        for row in plan.request.replacements:
            data = (clip_bytes or {}).get(row.target_path)
            if data is None:
                continue
            handle.replace_clip(
                row.target_path,
                data,
                source=str(getattr(row.donor, "name", "") or ""),
            )
    except Exception:
        handle.rollback()
        raise
    return handle.commit()


def _default_label(plan: MovePlan) -> str:
    unit = plan.unit
    destination = plan.request.destination_socket
    if plan.placement_changes and destination:
        label = f"Move {unit.primary_part} to {destination}"
    else:
        label = f"Replace animations for {unit.primary_part}"
    if plan.animation_count and plan.placement_changes:
        label = f"{label} with {plan.animation_count} animation replacement(s)"
    return label
