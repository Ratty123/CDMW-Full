"""One "Save as mod" for everything Placement & Animations can change.

There used to be four ways out, and none of them covered the common case. `Packages...` took
operations only and refused every hand adjustment with "Nothing to package"; `Export...` wrote
loose files with no mod metadata; Driven bones and Rig behaviour each had their own `Build`
button, which still wrote a CDUMM package after CDMW became DMM-only. This module is the one
route that replaces them: it lists every pending change in plain words, lets the user leave
any of them out, and writes one DMM mod through the same isolated replay and preflight the
operation packager always used.

Nothing here builds a widget, so the whole decision can be tested without a window. Text a
person reads goes through `translate_active_ui_text`, which also registers it with the
localization manifest; with no application running it passes the English through.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.services.active_ui_translation import translate_active_ui_text

from .clip_names import part_label, socket_label
from .editing import (EditError, OP_EDIT_ANIMATION, OP_MANUAL_ORIENTATION, OP_MOVE_EQUIPMENT,
                      OP_REPLACE_ANIMATIONS, OP_RETIME_EVENTS)

#: CDMW exports mods for DMM only; other managers are not updated for the October 2026 DLC.
MOD_MANAGERS: Tuple[str, ...] = ("DMM",)

#: Keys for the changes that live outside the operation history.
MANUAL = "manual"
DRIVEN_BONES = "driven_bones"
RIG_BEHAVIOUR = "rig_behaviour"
#: Hand re-routes and chart retargets: listed so they are not forgotten, never saved.
UNSAVEABLE = "unsaveable"

#: Characters Windows does not allow in a folder name.
_BAD_NAME_CHARACTERS = ':/\\*?"<>|'


@dataclass(frozen=True, slots=True)
class ModChange:
    """One line in the "Your mod" list: what a person would call the change."""

    key: str
    title: str
    detail: Tuple[str, ...] = ()
    #: What to call a mod made of this change, when the user gives no name.
    name_hint: str = ""
    #: False for a change that is listed but can never go into a mod.
    saveable: bool = True


@dataclass(frozen=True, slots=True)
class SaveRequest:
    name: str
    folder: Path
    include: Tuple[str, ...]
    author: str = ""
    version: str = "1.0.0"
    description: str = ""
    replace_existing: bool = False
    accept_warnings: bool = False
    #: Saving into DMM's own mods folder: DMM lists every folder there, so a replaced mod
    #: keeps no backup beside it, and a folder CDMW did not write is never replaced.
    into_dmm: bool = False


@dataclass(frozen=True, slots=True)
class SaveOutcome:
    """What happened. Exactly one of `results`, `problems` or `warnings` matters."""

    results: Tuple[object, ...] = ()
    #: Plain sentences saying why nothing was written.
    problems: Tuple[str, ...] = ()
    #: Plain sentences the user has to accept before anything is written.
    warnings: Tuple[str, ...] = ()
    detail: str = ""
    destination: Optional[Path] = None
    #: The manual operation the hand adjustments were gathered into, so a second attempt
    #: (replace the folder, accept a warning) includes them again.
    manual_operation: str = ""
    #: Where the previous version of a replaced mod folder was kept, if it was.
    backup: Optional[Path] = None
    #: The mod folder is already there and replacing it was not asked for. The window asks;
    #: it cannot look for words in `problems`, which are already in the user's language.
    already_exists: bool = False

    @property
    def saved(self) -> bool:
        return bool(self.results)


def describe_operation(operation) -> ModChange:
    """An operation as a sentence, with the game's identifiers only in the detail lines."""

    parts = operation.routed_parts()
    clips = operation.replaced_clips()
    destination = operation.scope.destination_socket
    subject = part_label(parts[0]) if parts else (operation.label or "Item")
    place = socket_label(destination) if destination else ""
    retimed = operation.retimed_events()
    if operation.kind == OP_EDIT_ANIMATION:
        title = hint = operation.label or translate_active_ui_text("Edited animation")
    elif operation.kind == OP_RETIME_EVENTS:
        title = hint = operation.label or translate_active_ui_text(
            f"Draw and put-away timing ({len(retimed)} hand-off(s))")
    elif operation.kind == OP_MOVE_EQUIPMENT and destination and clips:
        hint = translate_active_ui_text(f"Move {subject} to {place}")
        title = translate_active_ui_text(
            f"Move {subject} to {place}, with {len(clips)} matching animation(s)")
    elif operation.kind == OP_MOVE_EQUIPMENT and destination:
        title = hint = translate_active_ui_text(f"Move {subject} to {place}")
    elif (operation.kind == OP_REPLACE_ANIMATIONS or clips) and parts:
        title = hint = translate_active_ui_text(f"Replace {len(clips)} animation(s) for {subject}")
    elif operation.kind == OP_REPLACE_ANIMATIONS or clips:
        title = hint = translate_active_ui_text(f"Replace {len(clips)} animation(s)")
    else:
        title = hint = operation.label or translate_active_ui_text("Change")
    detail: List[str] = []
    for socket in operation.modified_sockets():
        detail.append(translate_active_ui_text(
            f"Adjusted attach point {socket_label(socket)}  ({socket})"))
    for socket in operation.created_sockets():
        detail.append(translate_active_ui_text(f"New attach point {socket}"))
    for part in parts:
        detail.append(translate_active_ui_text(f"Re-routed {part_label(part)}  ({part})"))
    if clips:
        detail.append(translate_active_ui_text(f"{len(clips)} animation file(s) replaced"))
    for chart, address, begin in retimed:
        animation, _sep, event = address.partition(":")
        name = chart.rsplit("/", 1)[-1]
        detail.append(translate_active_ui_text(
            f"{name}, animation {animation}: the hand-off now happens at {float(begin):.3f} s"))
    return ModChange(operation.operation_id, title, tuple(detail), hint)


def describe_manual(commands) -> ModChange:
    """Position edits made by hand: nudges, typed angles, new attach points."""

    sockets = sorted({c.target for c in commands if c.kind in {"translate", "rotate", "reparent"}})
    created = sorted({c.target for c in commands if c.kind == "add_socket"})
    detail: List[str] = []
    detail += [translate_active_ui_text(f"Adjusted attach point {socket_label(name)}  ({name})")
               for name in sockets]
    detail += [translate_active_ui_text(f"New attach point {name}") for name in created]
    places = sockets or created
    hint = (translate_active_ui_text(f"{socket_label(places[0])} adjustment") if places
            else translate_active_ui_text("Placement adjustment"))
    return ModChange(MANUAL, translate_active_ui_text("Manual adjustments"), tuple(detail), hint)


def describe_unsaveable(commands) -> ModChange:
    """Hand re-routes and chart retargets, made under Advanced."""

    detail = [translate_active_ui_text(f"Re-routed {part_label(c.target)}  ({c.target})")
              for c in commands if c.kind == "route"]
    detail += [translate_active_ui_text(f"Animation chart now uses {c.text} instead of {c.target}")
               for c in commands if c.kind == "retarget"]
    detail.append(translate_active_ui_text(
        "These cannot go into a mod: they skip the checks a move makes. Use Carried at to move "
        "an item, or Export changed files only to keep the files."))
    return ModChange(UNSAVEABLE,
                     translate_active_ui_text("Advanced edits that cannot be saved as a mod"),
                     tuple(detail), saveable=False)


def pending_changes(
    edits,
    *,
    driven_bones: Sequence[str] = (),
    rig_behaviour: Sequence[str] = (),
) -> List[ModChange]:
    """Every change that could go into a mod, oldest first.

    Hand position edits are one entry whether or not they were already gathered into the
    manual operation by an earlier save.
    """

    changes: List[ModChange] = []
    if edits is not None:
        manual_commands = []
        for operation in edits.operations():
            if operation.kind == OP_MANUAL_ORIENTATION:
                manual_commands += list(operation.commands)
            else:
                changes.append(describe_operation(operation))
        manual_commands += edits.adoptable_loose_commands()
        if manual_commands:
            changes.append(describe_manual(manual_commands))
        others = [c for c in edits.loose_commands() if c not in edits.adoptable_loose_commands()]
        if others:
            changes.append(describe_unsaveable(others))
    if driven_bones:
        changes.append(ModChange(DRIVEN_BONES,
                                 translate_active_ui_text("Driven bones (secondary motion)"),
                                 tuple(driven_bones)))
    if rig_behaviour:
        changes.append(ModChange(RIG_BEHAVIOUR, translate_active_ui_text("Rig behaviour settings"),
                                 tuple(rig_behaviour)))
    return changes


def manual_dependencies(edits, manual_id: str, included: Sequence[str]) -> List[str]:
    """Changes the hand adjustments build on that are not being saved with them.

    Fine-tuning the point a move created only means something together with that move;
    packaged alone, the adjustment would name a point no saved file defines.
    """

    operations = {op.operation_id: op for op in edits.operations()}
    manual = operations.get(manual_id)
    if manual is None:
        return []
    creators = {}
    for operation in operations.values():
        for socket in operation.created_sockets():
            creators.setdefault(socket, operation)
    needed = []
    for command in manual.commands:
        owner = creators.get(command.target)
        if owner is not None and owner.operation_id != manual_id \
                and owner.operation_id not in included and owner not in needed:
            needed.append(owner)
    return [describe_operation(op).title for op in needed]


def suggested_name(changes: Sequence[ModChange]) -> str:
    """A mod name a person would recognise, from the first change."""

    if not changes:
        return translate_active_ui_text("My placement mod")
    title = changes[0].name_hint or changes[0].title.split(",")[0]
    for bad in _BAD_NAME_CHARACTERS:
        title = title.replace(bad, " ")
    return " ".join(title.split())[:60] or translate_active_ui_text("My placement mod")


def save_mod(
    edits,
    request: SaveRequest,
    *,
    baseline=None,
    units: Optional[Mapping[str, object]] = None,
    shared_socket_users: Optional[Mapping[str, Sequence[str]]] = None,
    other_files: Optional[Mapping[str, Mapping[str, bytes]]] = None,
    baseline_current: Callable[[], bool] = lambda: True,
) -> SaveOutcome:
    """Write the chosen changes as one DMM mod, or say plainly why not.

    `other_files` maps `DRIVEN_BONES` / `RIG_BEHAVIOUR` to the files those panels edited.
    Hand adjustments are first gathered into one operation (`adopt_loose_commands`), so they
    pass through the same isolated replay and preflight as everything else.
    """

    from .packaging import PackageMetadata, PackagingError, build_all, build_for_operations
    from .packaging import package_destinations
    from .ops import Plan

    name = request.name.strip()
    if not name:
        return SaveOutcome(problems=(translate_active_ui_text("Give the mod a name."),))
    if any(character in name for character in _BAD_NAME_CHARACTERS) or name.endswith("."):
        return SaveOutcome(problems=(translate_active_ui_text(
            f"A mod name cannot contain any of {' '.join(_BAD_NAME_CHARACTERS)} or end with a "
            f"full stop, because it becomes a folder name."),))
    if not baseline_current():
        return SaveOutcome(problems=(translate_active_ui_text(
            "The game was updated after Placement & Animations opened, so these changes were "
            "made on the old game files. Close and reopen the tab, then make and save them again."
        ),))
    metadata = PackageMetadata(
        name=name,
        version=request.version.strip() or "1.0.0",
        author=request.author.strip(),
        description=request.description.strip()
        or "Placement and animation changes made with CDMW's Placement & Animations.",
    )
    try:
        destination = package_destinations(metadata, out_root=Path(request.folder),
                                           managers=MOD_MANAGERS)[0]
    except PackagingError as exc:
        return SaveOutcome(problems=(str(exc),))
    if destination.exists() and request.into_dmm and not written_by_cdmw(destination):
        return SaveOutcome(
            problems=(translate_active_ui_text(
                f"DMM already has a mod folder named {destination.name} that CDMW did not "
                f"write. Give the mod another name."),),
            destination=destination,
        )
    if destination.exists() and not request.replace_existing:
        return SaveOutcome(
            problems=(translate_active_ui_text(
                f"A mod folder with this name already exists: {destination}"),),
            destination=destination,
            already_exists=True,
        )

    include = set(request.include)
    operation_ids: List[str] = []
    manual_id = ""
    if edits is not None:
        manual = edits.manual_operation()
        if MANUAL in include:
            manual_id = edits.adopt_loose_commands("Manual adjustments")
            if manual_id:
                include.add(manual_id)
        elif manual is not None:
            include.discard(manual.operation_id)
        if manual_id:
            needed = manual_dependencies(edits, manual_id, sorted(include))
            if needed:
                return SaveOutcome(problems=(translate_active_ui_text(
                    f"Your manual adjustments change an attach point that this change created, "
                    f"so they can only be saved together with it: {'; '.join(needed)}. Tick it "
                    f"too, or remove the adjustments."),
                ), manual_operation=manual_id, destination=destination)
        operation_ids = [op.operation_id for op in edits.operations() if op.operation_id in include]
    extra: Dict[str, bytes] = {}
    for key in (DRIVEN_BONES, RIG_BEHAVIOUR):
        if key in include:
            for path, data in (other_files or {}).get(key, {}).items():
                if path in extra and extra[path] != data:
                    return SaveOutcome(problems=(translate_active_ui_text(
                        f"Two panels changed {path} differently."),))
                extra[path] = data
    if not operation_ids and not extra:
        return SaveOutcome(problems=(translate_active_ui_text("Nothing is selected to save."),),
                           manual_operation=manual_id)

    try:
        if operation_ids:
            results, verdict = build_for_operations(
                edits,
                operation_ids,
                metadata,
                out_root=Path(request.folder),
                baseline=baseline,
                managers=MOD_MANAGERS,
                units=units,
                shared_socket_users=shared_socket_users,
                accept_warnings=request.accept_warnings,
                replace_existing=request.replace_existing,
                extra_files=extra,
                keep_backup=not request.into_dmm,
                managed_folder=request.into_dmm,
            )
            if verdict.blocked:
                return SaveOutcome(problems=tuple(plain_finding(f) for f in verdict.errors),
                                   detail=verdict.render(), destination=destination,
                                   manual_operation=manual_id)
            if not results:
                return SaveOutcome(warnings=tuple(plain_finding(f) for f in verdict.warnings),
                                   detail=verdict.render(), destination=destination,
                                   manual_operation=manual_id)
            return SaveOutcome(tuple(results), detail=verdict.summary.render(),
                               destination=destination, manual_operation=manual_id,
                               backup=results[0].backup_root)
        results = build_all(Plan(name=name), extra, metadata, out_root=Path(request.folder),
                            baseline=baseline, managers=MOD_MANAGERS,
                            replace_existing=request.replace_existing,
                            keep_backup=not request.into_dmm,
                            managed_folder=request.into_dmm)
        return SaveOutcome(tuple(results), destination=destination, manual_operation=manual_id,
                           backup=results[0].backup_root)
    except (PackagingError, EditError, OSError, ValueError) as exc:
        # Never into the Qt slot: a refusal the preflight did not anticipate is still a
        # reason to give, and nothing has been published when these are raised.
        return SaveOutcome(problems=(str(exc),), destination=destination,
                           manual_operation=manual_id)


def written_by_cdmw(folder: Path) -> bool:
    """Whether a mod folder carries CDMW's own manifest, so replacing it loses nobody's work."""

    import json

    try:
        manifest = json.loads((Path(folder) / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(manifest, dict) and str(manifest.get("generator", "")).startswith(
        "Crimson Desert Mod Workbench")


def plain_finding(finding) -> str:
    """A preflight finding said the way a modder would need to hear it."""

    code = getattr(finding, "code", "")
    detail = dict(getattr(finding, "detail", {}) or {})
    message = str(getattr(finding, "message", "") or finding)
    if code == "shared_socket_modified":
        raw = str(detail.get("socket", ""))
        socket = socket_label(raw) or raw
        users = list(detail.get("users") or ())
        names = ", ".join(part_label(str(u)) for u in users[:4]) + ("…" if len(users) > 4 else "")
        return translate_active_ui_text(
            f"{socket} is shared by several items ({names}), so changing it would move all of "
            f"them. Undo that adjustment and move the item with Carried at instead, which "
            f"gives it an attach point of its own.")
    if code == "undefined_socket":
        return translate_active_ui_text(
            "A change points an item at an attach point that no saved file defines.")
    if code == "case_not_handled":
        return translate_active_ui_text(
            "The weapon moves but its sheath or case does not. Move it again with Carried at so "
            "both go together.")
    if code == "case_left_behind":
        return translate_active_ui_text(
            "The sheath or case stays where it was while the weapon moves.")
    if code == "orientation_unreviewed":
        return translate_active_ui_text(
            "An angle was borrowed or set by hand and has not been confirmed as looking right.")
    if code == "operation_conflict":
        return translate_active_ui_text(
            "Two of the selected changes set the same value differently. Untick or remove one "
            "of them.")
    if code == "large_replacement":
        return translate_active_ui_text(f"{message}. Check the result in game before sharing it.")
    if code == "accepted":
        return translate_active_ui_text(f"You accepted this earlier: {message}")
    return message
