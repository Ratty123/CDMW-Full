"""Turning a clip's file name into something a person can choose between.

`cd_phm_sword_00_01_normal_stand_weapon_out_000` says everything about what it is and none
of it legibly. When the tool has to ask "which of these two draws do you want?", showing two
names that differ only at `00_01` versus `01_03` is not a question anyone can answer.

The vocabulary here is the game's own, read off the clip names across the install: a stance
or context word, a posture, an action, and a take number. Anything not recognised is passed
through rather than dropped, so an unfamiliar clip still names itself.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

#: Word in the file name -> what it means. Ordered longest-first when matched, so `runfast`
#: never reads as `run`.
_CONTEXT: Tuple[Tuple[str, str], ...] = (
    ("move_runfast2", "while sprinting"),
    ("move_runfast", "while sprinting"),
    ("move_walkfast", "while walking"),
    ("move_run", "while running"),
    ("move_walk", "while walking"),
    ("move_jump", "while jumping"),
    ("tosit", "sitting down"),
    ("sit_base_std", "seated"),
    ("sit_std", "seated"),
    ("sit", "seated"),
    ("alert_nor_std", "on alert"),
    ("alert", "on alert"),
    ("nor_base_std", "standing"),
    ("normal_stand", "standing"),
    ("nor_stand", "standing"),
    ("nor_std", "standing"),
    ("std", "standing"),
)

#: What the clip actually does.
_ACTION: Tuple[Tuple[str, str], ...] = (
    ("weapon_out", "take the weapon out"),
    ("weapon_in", "put the weapon away"),
    ("weapon_ing", "mid-swap"),
)

_DIRECTION: Dict[str, str] = {
    "_f_": " forward",
    "_l_": " to the left",
    "_r_": " to the right",
}


def action_of(stem: str) -> str:
    lowered = stem.lower()
    for token, label in _ACTION:
        if token in lowered:
            return label
    return ""


def context_of(stem: str) -> str:
    lowered = stem.lower()
    for token, label in _CONTEXT:
        if token in lowered:
            return label
    return ""


def take_of(stem: str) -> str:
    """The trailing take number, as a human count rather than an index."""

    body = stem[: -len("_lod")] if stem.endswith("_lod") else stem
    last = body.rsplit("_", 1)[-1]
    if last.isdigit() and int(last) > 0:
        return f"version {int(last) + 1}"
    return ""


def friendly(stem: str) -> str:
    """A plain-language description of one clip, as specific as the name allows.

    Never returns nothing: an unrecognised clip falls back to its own name, because a row
    labelled with an empty string is worse than a row labelled with a file name.
    """

    parts: List[str] = []
    context = context_of(stem)
    action = action_of(stem)
    if context:
        parts.append(context[0].upper() + context[1:])
    if action:
        parts.append(action if not parts else action)
    if not parts:
        return stem
    if not action:
        extra = residual_words(stem)
        if extra:
            parts.append(extra)
    text = " — ".join(parts) if len(parts) > 1 else parts[0]
    for token, suffix in _DIRECTION.items():
        if token in stem.lower():
            text += suffix
            break
    if stem.endswith("_lod"):
        text += " (distant version)"
    take = take_of(stem)
    if take:
        text += f", {take}"
    return text


def residual_words(stem: str) -> str:
    """The descriptive words left once the family and the index numbers are stripped.

    Used when nothing in the action vocabulary matches, so `..._nor_base_std_eat_bread_00`
    still reads as "eat bread" rather than losing everything but its posture.
    """

    body = stem[: -len("_lod")] if stem.endswith("_lod") else stem
    words = [w for w in body.split("_")[3:] if not w.isdigit()]
    known = set()
    for token, _label in _CONTEXT + _ACTION:
        known.update(token.split("_"))
    kept = [w for w in words if w not in known]
    return " ".join(kept)


def stance_of(stem: str) -> str:
    """The stance index — the pair of numbers after the family — as a bare string."""

    parts = stem.split("_")
    numbers = [p for p in parts[3:6] if p.isdigit()]
    return "_".join(numbers)


def group_key(stem: str) -> str:
    """What kind of animation this is, ignoring which take of it this file happens to be.

    `weapon_in_000`, `_002`, `_004` and their `_lod` copies are all the same moment — the
    game picks between them at runtime for variety. Asking which stand-in to use for each
    one separately produced twenty rows of the same question, so they are decided together.
    """

    parts = stem.split("_")
    # Four things have to match before two clips are the same question.
    #
    # The *character*: `cd_prh_` is mounted, and offering it as a style for a standing draw
    # chose a motion from horseback.
    #
    # The *weapon family*: `sword` and `dualsword` are different equipped weapons with
    # different draws, and one answer cannot serve both.
    #
    # The *stance*: `00_01` and `01_01` are different states the character can be standing
    # in, and the game plays whichever matches at the time — so collapsing them meant the
    # clip that actually fired could be one the choice never covered.
    #
    # Only the take number is left to vary, which is the one the game picks at random.
    character = parts[1] if len(parts) > 1 else ""
    family = parts[2] if len(parts) > 2 else ""
    return (
        f"{character}|{family}|{stance_of(stem)}|"
        f"{context_of(stem)}|{action_of(stem)}|{residual_words(stem)}"
    )


#: The equipped weapon a clip family belongs to, in words. Two decisions that differ only by
#: this were previously indistinguishable on screen.
FAMILY_LABELS: Dict[str, str] = {
    "sword": "One-handed sword",
    "dualsword": "Dual swords",
    "dlsd": "Dual swords",
    "swds": "Sword and shield",
    "swd": "Sword",
    "longsword": "Two-handed sword",
    "lswd": "Two-handed sword",
}


def family_label(stem: str) -> str:
    parts = stem.split("_")
    family = parts[2] if len(parts) > 2 else ""
    return FAMILY_LABELS.get(family, family)


def group_label(stem: str, count: int) -> str:
    """The heading for one decision: which weapon, which state, and what it settles.

    The weapon and the stance both have to appear. Without them several decisions read
    identically — three rows saying "Standing — eat bread" is no more answerable than the
    twenty rows it replaced.
    """

    base = friendly(stem)
    base = base.replace(" (distant version)", "").split(", version")[0]
    weapon = family_label(stem)
    stance = stance_of(stem)
    head = f"{weapon} — {base}" if weapon else base
    # The stance is the character's state; there is no word for it, so it is numbered.
    if stance and stance not in ("00_00", "00_01"):
        head += f" (state {stance.replace('_', '.')})"
    return f"{head}  ({count} clip{'s' if count != 1 else ''})"


def distinct_labels(stems) -> "List[str]":
    """Friendly labels for a set of options, made distinguishable from each other.

    Two stances of the same standing draw describe identically — which is exactly the case
    the user is being asked about — so where labels collide the stance and take numbers that
    separate them are appended. A choice between two identical labels is not a choice.
    """

    stems = list(stems)
    labels = [friendly(stem) for stem in stems]
    out = []
    for label, stem in zip(labels, stems):
        if labels.count(label) > 1:
            parts = stem.split("_")
            marker = "_".join(p for p in parts[3:6] if p.isdigit()) or parts[-1]
            out.append(f"{label}  [{marker}]")
        else:
            out.append(label)
    return out
