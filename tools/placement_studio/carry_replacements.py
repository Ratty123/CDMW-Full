"""Animation replacement pairing and risk reports for the carry workflow."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

def _target_entries(entries, unit, scope: "AnimationScope"):
    """This character's own clips in the unit's exact target families, and nothing else.

    Every exclusion here has a reason recorded against it: `00_mon` is the player as they
    appear in creature encounters and neither shipped mod touches it, `_swarm_` clips drive
    crowds, and another model's folder is somebody else's character.
    """

    families = set(unit.target_animation_families)
    prefixes = player_clip_prefixes(unit.model)
    if not families or not prefixes:
        return []
    out = []
    for entry in entries:
        path = str(getattr(entry, "path", "") or "")
        name = str(getattr(entry, "name", "") or "")
        if not scope.include_other_models and f"/{unit.model}/" not in path:
            continue
        if "/00_mon/" in path or "_swarm_" in name:
            continue
        if not name.startswith(prefixes):
            continue
        # Exact parsed family token, never a substring: `sword` sits inside `longsword` and
        # `dualsword`, so a substring match rewrites both grips from either one.
        if family_of(name) not in families:
            continue
        if not scope.allows_clip(name):
            continue
        out.append(entry)
    return out


def rank_donors(target_name: str, candidates):
    """The nearest stand-in, not merely the first one alphabetically.

    Signature matching ignores the stance and take numbers so a clip with no exact twin still
    finds one — but among several twins those numbers are the only thing separating one
    stance from another, and name order chose between them at random.
    """

    wanted = counterpart_names(target_name)
    rank = {name: position for position, name in enumerate(wanted)}
    return sorted(
        candidates,
        key=lambda entry: (
            rank.get(str(getattr(entry, "name", "")), len(rank)),
            str(getattr(entry, "name", "")),
        ),
    )


def swappable_pairs(
    unit,
    entries,
    scope: Optional["AnimationScope"] = None,
    *,
    destination_zone: str = "",
) -> Tuple[AnimationReplacement, ...]:
    """Target/donor pairs for one equipment unit, at one scope.

    Everything that decides the answer comes off `unit` — the model, the handedness, the
    exact target families — rather than off whatever the window has selected, which is what
    let one descriptor row move while another weapon's animations were rewritten.

    `destination_zone` is accepted because every caller has it and the review reports it; it
    does not currently widen or narrow the set, and saying so is cheaper than letting a
    reader assume it does.
    """

    import collections

    scope = scope or AnimationScope()
    if not scope.replaces_animations:
        return ()
    entries = list(entries)
    targets = _target_entries(entries, unit, scope)
    if not targets:
        return ()

    wanted_donor_families = set(unit.donor_animation_families)
    donors: Dict[object, List[object]] = collections.defaultdict(list)
    for entry in entries:
        name = str(getattr(entry, "name", "") or "")
        path = str(getattr(entry, "path", "") or "")
        if f"/{unit.model}/" not in path or "/00_mon/" in path or "_swarm_" in name:
            continue
        if family_of(name) not in wanted_donor_families:
            continue
        signature = clip_signature(name)
        if signature:
            donors[signature].append(entry)

    # A body may borrow the other playable character's clips where it has none of its own.
    # Off unless asked for: the rigs differ in proportion, so a borrowed draw may reach near
    # the hilt rather than onto it, and that is not a thing to discover in game.
    elsewhere: Dict[object, List[object]] = collections.defaultdict(list)
    cousin = OTHER_PLAYER.get(unit.model, "")
    if scope.include_borrowed and cousin:
        cousin_prefixes = player_clip_prefixes(cousin)
        for entry in entries:
            name = str(getattr(entry, "name", "") or "")
            path = str(getattr(entry, "path", "") or "")
            if f"/{cousin}/" not in path or "/00_mon/" in path or "_swarm_" in name:
                continue
            if not name.startswith(cousin_prefixes):
                continue
            if family_of(name) not in wanted_donor_families:
                continue
            motion = clip_motion(name)
            if motion:
                elsewhere[motion].append(entry)

    out: List[AnimationReplacement] = []
    for entry in targets:
        name = str(getattr(entry, "name", "") or "")
        signature = clip_signature(name)
        candidates = donors.get(signature) if signature else None
        if not candidates:
            motion = clip_motion(name)
            candidates = elsewhere.get(motion) if motion else None
        if not candidates:
            continue
        ranked = rank_donors(name, candidates)
        chosen = ranked[0]
        donor_name = str(getattr(chosen, "name", "") or "")
        out.append(
            AnimationReplacement(
                target=entry,
                donor=chosen,
                options=tuple(ranked),
                target_family=family_of(name),
                donor_family=family_of(donor_name),
                context_group=context_group_of(name),
                borrowed=borrowed_from_other_body(name, donor_name),
                mounted=is_mounted(name) or is_mounted(donor_name),
                dual_wield_donor=family_of(donor_name) in DUAL_WIELD_FAMILIES,
            )
        )
    out.sort(key=lambda row: str(getattr(row.target, "name", "")))
    return tuple(out)


def animation_target_allowlist(replacements: Sequence[AnimationReplacement]) -> Tuple[str, ...]:
    """The exact target paths an operation may write, computed before anything is recorded."""

    return tuple(sorted({row.target_path for row in replacements if row.target_path}))


def family_counts(replacements: Sequence[AnimationReplacement]):
    """`(targets, donors)` as family -> file count, which is what a review has to state."""

    import collections

    targets: Dict[str, int] = collections.Counter()
    donors: Dict[str, int] = collections.Counter()
    for row in replacements:
        if row.target_family:
            targets[row.target_family] += 1
        if row.donor_family:
            donors[row.donor_family] += 1
    return dict(sorted(targets.items())), dict(sorted(donors.items()))


def context_counts(replacements: Sequence[AnimationReplacement]) -> Dict[str, int]:
    import collections

    counts: Dict[str, int] = collections.Counter()
    for row in replacements:
        counts[row.context_group] += 1
    return dict(sorted(counts.items()))


def risk_summary(replacements: Sequence[AnimationReplacement]) -> Dict[str, int]:
    """How many replacements carry each risk — the numbers a confirmation has to show."""

    return {
        "borrowed": sum(1 for row in replacements if row.borrowed),
        "mounted": sum(1 for row in replacements if row.mounted),
        "dual_wield_donor": sum(1 for row in replacements if row.dual_wield_donor),
    }


def risk_warnings(replacements: Sequence[AnimationReplacement]) -> Tuple[str, ...]:
    """Plain sentences for the risks that are actually present."""

    counts = risk_summary(replacements)
    out: List[str] = []
    if counts["dual_wield_donor"]:
        out.append(
            f"{counts['dual_wield_donor']} selected donors come from a dual-sword family "
            f"and may alter the off-hand pose."
        )
    if counts["borrowed"]:
        out.append(
            f"{counts['borrowed']} clips come from the other playable character, whose rig "
            f"has different proportions; reaching and contact may be a little off."
        )
    if counts["mounted"]:
        out.append(f"{counts['mounted']} clips are horseback animations.")
    return tuple(out)

# Late imports keep this sibling directly importable while carry.py re-exports this API.
from .carry import (
    DUAL_WIELD_FAMILIES,
    OTHER_PLAYER,
    AnimationReplacement,
    AnimationScope,
    borrowed_from_other_body,
    clip_motion,
    clip_signature,
    context_group_of,
    counterpart_names,
    family_of,
    is_mounted,
    player_clip_prefixes,
)
