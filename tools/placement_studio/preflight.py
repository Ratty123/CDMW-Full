"""What a package is allowed to contain, checked before a single byte is written.

The packaging path used to serialize the whole edit session, so an earlier shield move and an
earlier one-handed animation swap shipped alongside the two-handed sword the user had just
finished. Replaying selected operations onto vanilla makes that structurally impossible; this
module is the second line, and it exists because "structurally impossible" is a claim about
code that changes.

Every check is an *allowlist* comparison. The operations declare what they may touch, the
isolated replay says what actually changed, and a difference blocks the package with a message
that names both sides — these are read minutes later by somebody who did not write the gate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import carry
from .documents import is_descriptor_file, is_socket_file
from .editing import EditOperation, EditSession, OP_MOVE_EQUIPMENT
from .model import EquipmentUnit

#: How many animation replacements count as "a lot", and so need saying out loud.
LARGE_REPLACEMENT_COUNT = 120

MANIFEST_FORMAT = "cdmw_placement_operation_v1"
MANIFEST_NAME = "operation_manifest.json"


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing wrong, or one thing worth confirming."""

    code: str
    message: str
    operation_id: str = ""
    detail: Mapping[str, object] = field(default_factory=dict)

    def describe(self) -> str:
        where = f"[{self.operation_id}] " if self.operation_id else ""
        return f"{where}{self.message}"


@dataclass(frozen=True, slots=True)
class PackageScopeSummary:
    """Exactly what the package contains, in the words a reviewer needs."""

    operations: Tuple[str, ...] = ()
    equipment_units: Tuple[str, ...] = ()
    descriptor_parts: Tuple[str, ...] = ()
    linked_parts: Tuple[str, ...] = ()
    destination: str = ""
    descriptor_files_changed: Tuple[str, ...] = ()
    socket_files_changed: Tuple[str, ...] = ()
    created_sockets: Tuple[str, ...] = ()
    modified_sockets: Tuple[str, ...] = ()
    shared_sockets_modified: Tuple[str, ...] = ()
    animation_targets: Mapping[str, int] = field(default_factory=dict)
    animation_donors: Mapping[str, int] = field(default_factory=dict)
    animation_files: int = 0
    borrowed_count: int = 0
    mounted_count: int = 0
    orientation_sources: Tuple[Tuple[str, str], ...] = ()
    warnings_accepted: Tuple[str, ...] = ()
    excluded_operations: Tuple[str, ...] = ()
    loose_edits: int = 0
    payload_paths: Tuple[str, ...] = ()

    def render(self) -> str:
        """The scope block shown before anything is written."""

        lines = [
            "Package scope",
            "",
            f"Operations: {len(self.operations)}",
            f"Equipment: {', '.join(self.equipment_units) or '-'}",
            f"Linked parts: {', '.join(self.linked_parts) or '-'}",
            f"Destination: {self.destination or '-'}",
            "",
            f"Descriptor rows changed: {len(self.descriptor_parts)}",
            f"Socket files changed: {len(self.socket_files_changed)}",
            f"New child sockets: {len(self.created_sockets)}",
            f"Existing shared sockets modified: {len(self.shared_sockets_modified)}",
            "",
            "Animation targets:",
        ]
        lines += [f"  {name}: {count}" for name, count in self.animation_targets.items()] or [
            "  (none)"
        ]
        lines += ["", "Animation donors:"]
        lines += [f"  {name}: {count}" for name, count in self.animation_donors.items()] or [
            "  (none)"
        ]
        if self.borrowed_count or self.mounted_count:
            lines += [
                "",
                f"Borrowed-character clips: {self.borrowed_count}",
                f"Mounted clips: {self.mounted_count}",
            ]
        if self.orientation_sources:
            lines += ["", "Orientation sources:"]
            lines += [f"  {name}: {source}" for name, source in self.orientation_sources]
        lines += ["", f"Excluded earlier operations: {len(self.excluded_operations)}"]
        if self.loose_edits:
            lines.append(
                f"Excluded free-form edits (not part of any operation): {self.loose_edits}"
            )
        if self.warnings_accepted:
            lines += ["", "Warnings accepted:"]
            lines += [f"  - {item}" for item in self.warnings_accepted]
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class PackagePreflight:
    """The verdict. Packaging is blocked when `errors` is not empty."""

    errors: Tuple[Finding, ...] = ()
    warnings: Tuple[Finding, ...] = ()
    summary: PackageScopeSummary = field(default_factory=PackageScopeSummary)

    @property
    def blocked(self) -> bool:
        return bool(self.errors)

    @property
    def needs_confirmation(self) -> bool:
        return bool(self.warnings)

    def render(self) -> str:
        lines: List[str] = []
        if self.errors:
            lines += ["Package blocked", "---------------"]
            lines += [f"  ERROR  {item.describe()}" for item in self.errors]
            lines.append("")
        if self.warnings:
            lines += ["Confirm before continuing", "-------------------------"]
            lines += [f"  {item.describe()}" for item in self.warnings]
            lines.append("")
        lines.append(self.summary.render())
        return "\n".join(lines)


# ── what actually changed ────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ChangedItems:
    """The isolated replay's own account of what it altered, by kind."""

    descriptor_parts: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    sockets: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    created_sockets: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    animation_paths: Tuple[str, ...] = ()
    other_paths: Tuple[str, ...] = ()

    @property
    def descriptor_files(self) -> Tuple[str, ...]:
        return tuple(sorted(self.descriptor_parts))

    @property
    def socket_files(self) -> Tuple[str, ...]:
        return tuple(sorted(self.sockets))

    def all_parts(self) -> Tuple[str, ...]:
        out: set = set()
        for names in self.descriptor_parts.values():
            out.update(names)
        return tuple(sorted(out))

    def all_sockets(self) -> Tuple[str, ...]:
        out: set = set()
        for names in self.sockets.values():
            out.update(names)
        return tuple(sorted(out))

    def all_created(self) -> Tuple[str, ...]:
        out: set = set()
        for names in self.created_sockets.values():
            out.update(names)
        return tuple(sorted(out))


def changed_items(plan) -> ChangedItems:
    """Read a derived plan back into "which rows, which sockets, which clips".

    Derived from the emitted bytes rather than from the commands, so what the check sees is
    what the package would contain. A command list can agree with itself and still disagree
    with the file.
    """

    descriptor_parts: Dict[str, set] = {}
    sockets: Dict[str, set] = {}
    created: Dict[str, set] = {}
    animation: set = set()
    other: set = set()
    for operation in plan.operations:
        path = operation.game_path
        target = operation.target
        if operation.kind in {"xml_attr", "xml_attr_add", "xml_element_add"}:
            if is_socket_file(path):
                sockets.setdefault(path, set()).add(target)
                if operation.kind == "xml_element_add":
                    created.setdefault(path, set()).add(target)
            elif is_descriptor_file(path):
                descriptor_parts.setdefault(path, set()).add(target)
            else:
                other.add(path)
            continue
        if operation.kind == "descriptor_alias":
            continue
        if str(operation.detail.get("payload_kind") or "") == "animation":
            animation.add(path)
            continue
        other.add(path)
    return ChangedItems(
        descriptor_parts={k: tuple(sorted(v)) for k, v in sorted(descriptor_parts.items())},
        sockets={k: tuple(sorted(v)) for k, v in sorted(sockets.items())},
        created_sockets={k: tuple(sorted(v)) for k, v in sorted(created.items())},
        animation_paths=tuple(sorted(animation)),
        other_paths=tuple(sorted(other)),
    )


# ── the checks ───────────────────────────────────────────────────────


def _union(values: Iterable[Iterable[str]]) -> set:
    out: set = set()
    for group in values:
        out.update(group)
    return out


def _check_operation_integrity(
    session: EditSession,
    selected: Sequence[EditOperation],
    wanted: Sequence[str],
    errors: List[Finding],
) -> None:
    # F2: the selected operations must not carry another operation's commands. Structurally
    # impossible through `isolated_session`; asserted because that is a claim about code.
    for operation in selected:
        stray = {c.operation_id for c in operation.commands} - {operation.operation_id}
        if stray:
            errors.append(
                Finding(
                    "foreign_command",
                    f"{operation.operation_id} carries commands from {', '.join(sorted(stray))}",
                    operation.operation_id,
                )
            )

    # F2: two selected operations that settle the same field differently.
    for conflict in session.operation_conflicts(wanted):
        errors.append(
            Finding("operation_conflict", conflict.describe(), conflict.left,
                    {"other": conflict.right})
        )

def _check_operation_allowlists(
    selected: Sequence[EditOperation],
    errors: List[Finding],
) -> None:
    # F2, per operation. The union below covers a deliberate multi-operation selection; this
    # covers the case the union cannot see — an operation that changed something its *own*
    # allowlist does not name, which is what a widened scope or a stale replay looks like.
    for operation in selected:
        scope = operation.scope
        for command in operation.commands:
            if command.kind == "route":
                if command.target not in scope.allowed_descriptor_parts:
                    errors.append(
                        Finding(
                            "descriptor_out_of_scope",
                            f"{operation.operation_id} changed {command.target}, which its own "
                            f"allowlist does not name "
                            f"({', '.join(scope.allowed_descriptor_parts) or 'nothing'})",
                            operation.operation_id,
                            {"part": command.target},
                        )
                    )
                continue
            if command.kind in {"translate", "rotate", "reparent", "add_socket"}:
                if command.game_path not in scope.allowed_socket_files:
                    errors.append(
                        Finding(
                            "socket_file_out_of_scope",
                            f"{operation.operation_id} changed {command.game_path}, which its "
                            f"own allowlist does not name",
                            operation.operation_id,
                            {"path": command.game_path},
                        )
                    )
                continue
            if command.kind == "replace_file":
                if command.game_path not in scope.allowed_animation_targets:
                    errors.append(
                        Finding(
                            "animation_out_of_scope",
                            f"{operation.operation_id} would replace {command.game_path}, which "
                            f"its own animation target allowlist does not name",
                            operation.operation_id,
                            {"path": command.game_path},
                        )
                    )
                    continue
                family = carry.family_of(Path(command.game_path).name.rsplit(".", 1)[0])
                if (
                    scope.allowed_animation_families
                    and family
                    and family not in scope.allowed_animation_families
                ):
                    errors.append(
                        Finding(
                            "animation_family_mismatch",
                            f"{operation.operation_id} would write {command.game_path}, which "
                            f"is in the {family} family — not one of this equipment unit's "
                            f"target families "
                            f"({', '.join(scope.allowed_animation_families)})",
                            operation.operation_id,
                            {"path": command.game_path, "family": family},
                        )
                    )

def _check_changed_allowlists(
    changed: ChangedItems,
    selected: Sequence[EditOperation],
    units: Mapping[str, EquipmentUnit],
    errors: List[Finding],
) -> None:
    allowed_parts = _union(op.scope.allowed_descriptor_parts for op in selected)
    allowed_descriptor_files = _union(op.scope.allowed_descriptor_files for op in selected)
    allowed_socket_files = _union(op.scope.allowed_socket_files for op in selected)
    allowed_targets = _union(op.scope.allowed_animation_targets for op in selected)
    allowed_families = _union(op.scope.allowed_animation_families for op in selected)
    models = {op.scope.model for op in selected if op.scope.model}

    # F2: a descriptor part outside the allowlist changed.
    for part in changed.all_parts():
        if part not in allowed_parts:
            errors.append(
                Finding(
                    "descriptor_out_of_scope",
                    f"{part} changed but is not part of the selected operation "
                    f"(allowed: {', '.join(sorted(allowed_parts)) or 'none'})",
                    detail={"part": part},
                )
            )
    for path in changed.descriptor_files:
        if path not in allowed_descriptor_files:
            errors.append(
                Finding(
                    "descriptor_file_out_of_scope",
                    f"{path} changed but is not a descriptor file the selected operation "
                    f"may write",
                    detail={"path": path},
                )
            )

    # F2: a socket file outside the allowlist changed.
    for path in changed.socket_files:
        if path not in allowed_socket_files:
            errors.append(
                Finding(
                    "socket_file_out_of_scope",
                    f"{path} changed but is not a socket file the selected operation may write",
                    detail={"path": path},
                )
            )

    # F2: an animation target outside the target allowlist.
    for path in changed.animation_paths:
        if path not in allowed_targets:
            errors.append(
                Finding(
                    "animation_out_of_scope",
                    f"{path} would be replaced but is not in the operation's animation "
                    f"target allowlist",
                    detail={"path": path},
                )
            )
            continue
        family = carry.family_of(Path(path).name.rsplit(".", 1)[0])
        if allowed_families and family and family not in allowed_families:
            errors.append(
                Finding(
                    "animation_family_mismatch",
                    f"{path} belongs to the {family} family, which is not one of the selected "
                    f"equipment unit's target families "
                    f"({', '.join(sorted(allowed_families))})",
                    detail={"path": path, "family": family},
                )
            )

    # F2: a character or model mismatch.
    if len(models) > 1:
        errors.append(
            Finding(
                "model_mismatch",
                f"The selected operations belong to different characters: "
                f"{', '.join(sorted(models))}",
            )
        )
    for operation in selected:
        unit = units.get(operation.equipment_unit_id)
        if unit is not None and operation.scope.model and unit.model != operation.scope.model:
            errors.append(
                Finding(
                    "model_mismatch",
                    f"{operation.operation_id} is scoped to {operation.scope.model} but its "
                    f"equipment unit belongs to {unit.model}",
                    operation.operation_id,
                )
            )

def _check_operation_safety(
    selected: Sequence[EditOperation],
    units: Mapping[str, EquipmentUnit],
    changed: ChangedItems,
    shared_socket_users: Mapping[str, Sequence[str]],
    errors: List[Finding],
    warnings: List[Finding],
) -> None:
    changed_parts = set(changed.all_parts())
    created = set(changed.all_created())

    for operation in selected:
        unit = units.get(operation.equipment_unit_id)

        # F2: a required case or sheath row was not handled.
        if operation.kind == OP_MOVE_EQUIPMENT and unit is not None:
            if unit.primary_part in changed_parts:
                for link in unit.required_links:
                    if link.part_name in changed_parts:
                        continue
                    if f"leave {link.part_name} behind" in operation.warnings_accepted:
                        warnings.append(
                            Finding(
                                "case_left_behind",
                                f"{link.part_name} ({link.role}) stays on its old socket while "
                                f"{unit.primary_part} moves; the two may separate or snap",
                                operation.operation_id,
                            )
                        )
                        continue
                    errors.append(
                        Finding(
                            "case_not_handled",
                            f"{unit.primary_part} moves but its {link.role} "
                            f"{link.part_name} was not, and no exception was confirmed",
                            operation.operation_id,
                        )
                    )

        # F2: a placement was expected but no route command exists.
        if operation.kind == OP_MOVE_EQUIPMENT and not operation.routed_parts():
            errors.append(
                Finding(
                    "placement_missing",
                    f"{operation.operation_id} is a placement operation but records no route "
                    f"change, so nothing would move",
                    operation.operation_id,
                )
            )

        # F2: a shared child socket was modified in place.
        for socket_name in operation.modified_sockets():
            if socket_name in created:
                continue
            users = shared_socket_users.get(socket_name)
            if users is None:
                continue
            owned = set(units[operation.equipment_unit_id].part_names) if (
                operation.equipment_unit_id in units
            ) else set(operation.scope.allowed_descriptor_parts)
            outside = [name for name in users if name not in owned]
            if outside or len(users) > 1:
                errors.append(
                    Finding(
                        "shared_socket_modified",
                        f"{socket_name} is used by {', '.join(users)} and was changed in "
                        f"place; clone it and reroute only this operation's rows",
                        operation.operation_id,
                        {"socket": socket_name, "users": list(users)},
                    )
                )

        # C6 / F2: body socket and child orientation must belong to the same destination zone.
        destination = operation.scope.destination_socket
        if destination:
            want_zone = carry.zone_of(destination)
            for command in operation.commands:
                if command.kind != "route" or command.field_name != "in_child_socket":
                    continue
                child = command.text
                if not child or child in created:
                    continue
                have_zone = carry.zone_of(child.replace("ChildSocket", "Socket"))
                if want_zone and have_zone and want_zone != have_zone:
                    errors.append(
                        Finding(
                            "orientation_zone_mismatch",
                            f"{command.target} hangs on {destination} ({want_zone}) but is "
                            f"aimed by {child}, which belongs to the {have_zone}",
                            operation.operation_id,
                        )
                    )

        # C6: a borrowed or hand-authored aim must have been looked at.
        borrowed_aims = [
            name for name, source in operation.orientation_sources
            if source in ("borrowed_zone", "manual")
        ]
        if borrowed_aims and not operation.orientation_reviewed:
            errors.append(
                Finding(
                    "orientation_unreviewed",
                    f"The aim for {', '.join(sorted(borrowed_aims))} was borrowed or authored "
                    f"by hand and has not been marked reviewed",
                    operation.operation_id,
                )
            )

        # F3: every warning the user was shown and accepted is restated here, so the package
        # review says what was waved through rather than leaving it in the dialog's history.
        for accepted in operation.warnings_accepted:
            warnings.append(Finding("accepted", accepted, operation.operation_id))
        if operation.scope.kind == OP_MOVE_EQUIPMENT and not operation.scope.destination_socket:
            warnings.append(
                Finding(
                    "destination_unrecorded",
                    "This placement operation did not record its destination socket, so the "
                    "orientation zone check could not run",
                    operation.operation_id,
                )
            )

def _check_defined_routes(
    isolated: EditSession,
    selected: Sequence[EditOperation],
    errors: List[Finding],
) -> None:
    # F2: a route that references an undefined socket.
    defined = set(isolated.defined_sockets())
    for operation in selected:
        for command in operation.commands:
            if command.kind != "route" or not command.text:
                continue
            if command.text not in defined:
                errors.append(
                    Finding(
                        "undefined_socket",
                        f"{command.target}.{command.field_name} points at {command.text}, "
                        f"which no packaged file defines",
                        operation.operation_id,
                    )
                )

def _add_replacement_warnings(
    changed: ChangedItems,
    replacements: Sequence["carry.AnimationReplacement"],
    warnings: List[Finding],
) -> None:
    if replacements:
        for message in carry.risk_warnings(replacements):
            warnings.append(Finding("donor_risk", message))
    if len(changed.animation_paths) >= LARGE_REPLACEMENT_COUNT:
        warnings.append(
            Finding(
                "large_replacement",
                f"{len(changed.animation_paths)} animation files would be replaced",
            )
        )

def run_preflight(
    session: EditSession,
    operation_ids: Sequence[str],
    *,
    units: Optional[Mapping[str, EquipmentUnit]] = None,
    shared_socket_users: Optional[Mapping[str, Sequence[str]]] = None,
    replacements: Sequence["carry.AnimationReplacement"] = (),
) -> PackagePreflight:
    """Check a selected set of operations against everything they declared.

    `units` maps equipment-unit id to the resolved unit, so the family and linked-row checks
    can be made against the item the user actually selected. `shared_socket_users` maps a
    child socket to every descriptor row that references it in vanilla, which is what decides
    whether an in-place edit is local or not.
    """
    wanted = list(dict.fromkeys(operation_ids))
    units = dict(units or {})
    shared_socket_users = {k: tuple(v) for k, v in (shared_socket_users or {}).items()}

    all_operations = session.operations()
    by_id = {op.operation_id: op for op in all_operations}
    selected = [by_id[oid] for oid in wanted if oid in by_id]
    missing = [oid for oid in wanted if oid not in by_id]

    errors: List[Finding] = []
    warnings: List[Finding] = []

    for oid in missing:
        errors.append(
            Finding(
                "unknown_operation",
                f"Operation {oid} is not in the session history, so it cannot be packaged",
                oid,
            )
        )

    isolated = session.isolated_session(wanted)
    plan = isolated.to_plan("package")
    changed = changed_items(plan)

    _check_operation_integrity(session, selected, wanted, errors)
    _check_operation_allowlists(selected, errors)
    _check_changed_allowlists(changed, selected, units, errors)
    _check_operation_safety(
        selected, units, changed, shared_socket_users, errors, warnings
    )
    _check_defined_routes(isolated, selected, errors)

    replacement_rows = list(replacements)
    _add_replacement_warnings(changed, replacement_rows, warnings)

    summary = _summarize(
        session,
        selected,
        wanted,
        changed,
        units=units,
        replacements=replacement_rows,
        shared_socket_users=shared_socket_users,
        payload_paths=tuple(sorted(isolated.preview())),
    )
    return PackagePreflight(tuple(errors), tuple(warnings), summary)


def _summarize(
    session: EditSession,
    selected: Sequence[EditOperation],
    wanted: Sequence[str],
    changed: ChangedItems,
    *,
    units: Mapping[str, EquipmentUnit],
    replacements: Sequence["carry.AnimationReplacement"],
    shared_socket_users: Mapping[str, Sequence[str]],
    payload_paths: Tuple[str, ...],
) -> PackageScopeSummary:
    excluded = tuple(
        op.operation_id for op in session.operations() if op.operation_id not in set(wanted)
    )
    targets, donors = carry.family_counts(replacements)
    if not targets:
        # No dialog rows to read from — count the families off the paths that would ship.
        targets = {}
        for path in changed.animation_paths:
            family = carry.family_of(Path(path).name.rsplit(".", 1)[0])
            if family:
                targets[family] = targets.get(family, 0) + 1
        targets = dict(sorted(targets.items()))
    risks = carry.risk_summary(replacements)

    unit_ids = tuple(dict.fromkeys(op.equipment_unit_id for op in selected if op.equipment_unit_id))
    linked = tuple(
        dict.fromkeys(
            link.part_name
            for unit_id in unit_ids
            if unit_id in units
            for link in units[unit_id].linked_parts
        )
    )
    destinations = tuple(
        dict.fromkeys(op.scope.destination_socket for op in selected if op.scope.destination_socket)
    )
    created = set(changed.all_created())
    shared_modified = tuple(
        sorted(
            name
            for op in selected
            for name in op.modified_sockets()
            if name not in created and len(shared_socket_users.get(name, ())) > 1
        )
    )
    return PackageScopeSummary(
        operations=tuple(op.operation_id for op in selected),
        equipment_units=unit_ids,
        descriptor_parts=changed.all_parts(),
        linked_parts=linked,
        destination=", ".join(destinations),
        descriptor_files_changed=changed.descriptor_files,
        socket_files_changed=changed.socket_files,
        created_sockets=changed.all_created(),
        modified_sockets=tuple(
            sorted(name for name in changed.all_sockets() if name not in created)
        ),
        shared_sockets_modified=shared_modified,
        animation_targets=targets,
        animation_donors=donors,
        animation_files=len(changed.animation_paths),
        borrowed_count=risks["borrowed"],
        mounted_count=risks["mounted"],
        orientation_sources=tuple(
            sorted({pair for op in selected for pair in op.orientation_sources})
        ),
        warnings_accepted=tuple(
            dict.fromkeys(item for op in selected for item in op.warnings_accepted)
        ),
        excluded_operations=excluded,
        loose_edits=len(session.loose_commands()),
        payload_paths=payload_paths,
    )


# ── the manifest ─────────────────────────────────────────────────────


def operation_manifest(
    operations: Sequence[EditOperation],
    summary: PackageScopeSummary,
    *,
    units: Optional[Mapping[str, EquipmentUnit]] = None,
) -> Dict[str, object]:
    """The machine-readable record of what the package claims to be.

    Written beside the package metadata so a later verification pass can compare the claim
    against the files without re-deriving the operation model.
    """

    units = dict(units or {})
    return {
        "format": MANIFEST_FORMAT,
        "operations": [
            {
                "operation_id": op.operation_id,
                "kind": op.kind,
                "label": op.label,
                "equipment_unit_id": op.equipment_unit_id,
                "baseline_revision": op.baseline_revision,
                "destination_socket": op.scope.destination_socket,
                "routed_parts": list(op.routed_parts()),
                "created_sockets": list(op.created_sockets()),
                "modified_sockets": list(op.modified_sockets()),
                "replaced_clips": list(op.replaced_clips()),
                "orientation_reviewed": op.orientation_reviewed,
                "warnings_accepted": list(op.warnings_accepted),
            }
            for op in operations
        ],
        "equipment_units": [
            {
                "unit_id": unit.unit_id,
                "model": unit.model,
                "weapon_id": unit.weapon_id,
                "primary_part": unit.primary_part,
                "handedness": unit.handedness,
                "linked_parts": [
                    {
                        "part_name": link.part_name,
                        "role": link.role,
                        "required_for_stow": link.required_for_stow,
                    }
                    for link in unit.linked_parts
                ],
                "target_animation_families": list(unit.target_animation_families),
                "donor_animation_families": list(unit.donor_animation_families),
                "allowed_descriptor_files": list(unit.allowed_descriptor_files),
                "allowed_socket_files": list(unit.allowed_socket_files),
            }
            for unit in units.values()
        ],
        "descriptor_parts": list(summary.descriptor_parts),
        "created_sockets": list(summary.created_sockets),
        "modified_sockets": list(summary.modified_sockets),
        "shared_sockets_modified": list(summary.shared_sockets_modified),
        "orientation_sources": [
            {"socket": name, "source": source} for name, source in summary.orientation_sources
        ],
        "animation_targets": dict(summary.animation_targets),
        "animation_donors": dict(summary.animation_donors),
        "animation_files": summary.animation_files,
        "borrowed_character_clips": summary.borrowed_count,
        "mounted_clips": summary.mounted_count,
        "warnings_accepted": list(summary.warnings_accepted),
        "excluded_operations": list(summary.excluded_operations),
        "excluded_loose_edits": summary.loose_edits,
        "payload_paths": list(summary.payload_paths),
    }


def write_operation_manifest(root: Path, manifest: Mapping[str, object]) -> Path:
    target = Path(root) / MANIFEST_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(manifest, indent=2, sort_keys=False, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target
