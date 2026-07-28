"""Turning a clip's file name into something a person can choose between.

`cd_phm_sword_00_01_normal_stand_weapon_out_000` says everything about what it is and none
of it legibly. When the tool has to ask "which of these two draws do you want?", showing two
names that differ only at `00_01` versus `01_03` is not a question anyone can answer.

The vocabulary here is the game's own, read off the clip names across the install: a stance
or context word, a posture, an action, and a take number. Anything not recognised is passed
through rather than dropped, so an unfamiliar clip still names itself.
"""

from __future__ import annotations

import re

from typing import Dict, List, Optional, Tuple

#: Word in the file name -> what it means. Ordered longest-first when matched, so `runfast`
#: never reads as `run`.
_CONTEXT: Tuple[Tuple[str, str], ...] = (
    ("move_runfast2", "sprinting"),
    ("move_runfast", "sprinting"),
    ("move_walkfast", "walking"),
    ("move_run", "running"),
    ("move_walk", "walking"),
    ("move_jump", "jumping"),
    ("tosit", "sitting down"),
    # NOT horseback. Checked against the action charts: `cd_phm_swds_00_01_sit_std_*` is
    # named by `sword_upper.paac`, an ordinary on-foot chart, while the genuinely mounted
    # clips are the `cd_prh_` ones named by `ride_weapon_upper.paac`. What `sit` actually
    # denotes here is a lowered stance; the charts do not say which, so neither does this.
    ("sit_base_std", "in a low stance"),
    ("sit_std", "in a low stance"),
    ("sit", "in a low stance"),
    ("alert_nor_std", "ready for a fight"),
    ("alert", "ready for a fight"),
    ("nor_base_std", "standing still"),
    ("normal_stand", "standing still"),
    ("nor_stand", "standing still"),
    ("nor_std", "standing still"),
    ("std", "standing still"),
)

#: What the clip actually does.
_ACTION: Tuple[Tuple[str, str], ...] = (
    ("weapon_out", "drawing the weapon"),
    ("weapon_in", "sheathing the weapon"),
    ("weapon_ing", "switching weapons"),
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


#: The action, said as briefly as it can be. The context is the lane heading, so repeating
#: "Standing —" on every row inside the Standing lane was pure noise.
_SHORT_ACTION: Dict[str, str] = {
    "drawing the weapon": "Drawing the weapon",
    "sheathing the weapon": "Sheathing the weapon",
    "switching weapons": "Switching weapons",
}


def short_label(stem: str) -> str:
    """One row inside a lane: the action, and nothing that is not a decision.

    The take number and the distance copy are deliberately absent. The game picks between
    takes at runtime for variety and swaps to the distance copy by camera range — neither is
    something a modder chooses, so `put away  ·  v3  ·  distant` was four rows of noise
    dressed as detail. Files that differ only in those two respects share a row.
    """

    action = _SHORT_ACTION.get(action_of(stem), "")
    if not action:
        # An action with no entry in the vocabulary still names itself rather than
        # disappearing; capitalised so it does not read as a fragment beside the others.
        words = residual_words(stem) or family_label(stem).lower() or stem
        action = words[0].upper() + words[1:] if words else stem
    for token, suffix in _DIRECTION.items():
        if token in stem.lower():
            return f"{action} {suffix.strip()}"
    return action


def lane_of(stem: str, charts: "Optional[Dict[str, str]]" = None) -> str:
    """The heading a row belongs under.

    The action charts are asked first, because they are the game's own statement of when a
    clip plays; the file name is only consulted where no chart claims it. Reading the name
    alone put a mounted draw under "standing still" purely because it contained `nor_std`.
    """

    if charts:
        lane = charts.get(stem) or charts.get(stem[: -len("_lod")] if stem.endswith("_lod") else stem)
        if lane:
            return lane

    # The mounted clips are identified by their character, not by a word in the rest of the
    # name: `cd_prh_*` are the ones `ride_weapon_upper.paac` names. Reading `nor_std` off one
    # of those filed a horseback draw under "standing still".
    parts = stem.split("_")
    if len(parts) > 1 and parts[1] == "prh":
        return "On horseback"
    context = context_of(stem)
    if not context:
        return "Everything else"
    return context[0].upper() + context[1:]


#: Tokens that carry no choice: they are the default and every clip has them. `nor` is the
#: normal stance and `basic` the unarmed set — naming them in every row says nothing.
_DROPPED = frozenset({"cd", "nor", "normal", "basic", "base", "rd"})

#: Tokens worth spelling out. Anything absent is title-cased as it stands, so a word this
#: vocabulary has never seen still appears rather than vanishing.
_TRIM_WORDS = {
    "std": "Standing", "move": "Move", "run": "Run", "walk": "Walk",
    "walkfast": "Walkfast", "sit": "Seated", "crouch": "Crouching",
    "weapon": "Weapon", "out": "Out", "in": "In", "idle": "Idle",
    "prh": "On horseback", "abn": "Abnormal", "dam": "Damaged",
    # Written without the underscore in some chart-named clips, so the pair rule never sees
    # them as two tokens and they would come through as `Weaponin`.
    "weaponout": "Draw", "weaponin": "Sheathe",
}

#: Phase suffixes. These are kept — three clips that differ only by phase are three different
#: clips, and collapsing them would put identical rows in the list.
_PHASE = {"stt": "start", "ing": "during", "end": "end"}

#: Tokens that name a stance. `std` is only "standing" when none of these is present: in
#: `sit_base_std` it marks the standard variant *of sitting*, so spelling it out as well gave
#: rows that read `Seated - Standing`.
_STANCES = frozenset({"sit", "crouch", "prh", "swim", "crawl", "ladder", "climb", "slide"})

_TURN = re.compile(r"^turn(\d+)([lr])$")

#: Pairs read as one thing. Split apart, `weapon out` is less legible than the file name was.
_TRIM_PAIRS = {
    ("weapon", "out"): "Draw",
    ("weapon", "in"): "Sheathe",
    ("weapon", "ing"): "Draw",
}

#: The abbreviations the file names are built from. A row saying `Lswd` has translated nothing.
_TRIM_ABBREV = {
    "phm": "Kliff", "phw": "Damian",
    "swd": "Sword", "lswd": "Longsword", "dlsd": "Dual swords",
    "swds": "Sword and shield", "spr": "Spear", "hm": "Hammer",
    "sythe": "Scythe", "bow": "Bow", "arw": "Arrow", "pst": "Pistol",
    "f": "forward", "b": "back", "l": "left", "r": "right", "s": "sideways",
    "lk": "corpse", "rd": "riding",
}


def _trim_token(token: str) -> str:
    turn = _TURN.match(token)
    if turn is not None:
        return f"Turn {turn.group(1)} {turn.group(2).upper()}"
    known = _TRIM_WORDS.get(token) or _TRIM_ABBREV.get(token)
    if known:
        return known[:1].upper() + known[1:]
    return token[:1].upper() + token[1:]


def trimmed(stem: str) -> str:
    """A file name with the boilerplate taken out, and nothing renamed.

    `cd_boarmimic_basic_00_00_nor_move_walkfast_turn180l_stt_00` reads as
    `Boarmimic - Move - Walkfast - Turn 180 L (start)`.

    Deliberately a trim and not a translation. The plain-language route — `friendly` — reads
    better on the few clips whose vocabulary is known and falls back to the raw name on the
    rest, which in a list of 104,649 gives a column that is half prose and half file names.
    Dropping the parts that are the same on every row keeps every clip recognisable, keeps
    them distinct from each other, and still matches what a modder sees on disk.

    The phase is the one thing kept that the trim would otherwise lose: `stt`, `ing` and `end`
    are the start, middle and end of one motion, so three clips would collapse onto one row.
    """

    phase = ""
    tokens = [
        token.lower() for token in stem.split("_")
        if token.lower() not in _DROPPED and not token.isdigit()
    ]
    if any(token in _STANCES for token in tokens):
        tokens = [token for token in tokens if token != "std"]
    words: List[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        pair = _TRIM_PAIRS.get((token, tokens[index + 1])) if index + 1 < len(tokens) else None
        if pair is not None:
            words.append(pair)
            index += 2
            continue
        if token in _PHASE:
            phase = _PHASE[token]
            index += 1
            continue
        word = _trim_token(token)
        # File names repeat themselves — `corpse_lk_phm_..._corpse_lk_phm_...` — and a row that
        # says the same word twice is harder to read than one that says it once.
        if word.lower() not in {seen.lower() for seen in words}:
            words.append(word)
        index += 1
    if not words:
        return stem
    trimmed_name = " - ".join(words)
    return f"{trimmed_name} ({phase})" if phase else trimmed_name


#: A body socket named the way a person would say it. The game's own name is kept alongside in
#: the tooltip: it is what the file holds, and a modder comparing against a chart needs it.
SOCKET_PLACES = {
    "RHand_Socket": "Right hand", "LHand_Socket": "Left hand",
    "Pelvis_R_Socket": "Right hip", "Pelvis_L_Socket": "Left hip",
    "RThigh_Socket": "Right thigh", "LThigh_Socket": "Left thigh",
    "Pelvis_B_Socket": "Lower back",
    "Spine2_B_MainWeapon_Socket": "Back — main weapon",
    "Spine2_B_SubWeapon_Socket": "Back — second weapon",
    "Spine2_B_RangeWeapon_Socket": "Back — bow",
    "Spine2_B_RangeWeapon_Musket_Socket": "Back — musket",
    "Spine2_B_Shield_Socket": "Back — shield",
    "LForearm_Socket": "Left forearm", "RForearm_Socket": "Right forearm",
    "LHand_Lantern_Socket": "Left hand — lantern",
}

#: Suffixes a weapon file uses for which side it is worn on, and the cased variant.
_SIDE = {"r": "right", "l": "left", "in": "cased"}


def socket_label(socket: str) -> str:
    """`Pelvis_L_Socket` as `Left hip`, or the raw name when it is not a place we know."""

    known = SOCKET_PLACES.get(socket)
    if known:
        return known
    trimmed_name = socket.replace("_Socket", "").replace("_", " ").strip()
    return trimmed_name or socket


def weapon_label(stem: str) -> str:
    """`cd_phm_01_sword_0001_r` as `Sword 0001 — right`.

    The variant number stays. A character carries several swords that differ only by it, so
    dropping it the way the clip trim drops take numbers would collapse distinct weapons onto
    one indistinguishable row.
    """

    tokens = [token.lower() for token in stem.split("_") if token]
    if tokens and tokens[0] == "cd":
        tokens = tokens[1:]
    # The model code and the two-digit category are on every row for a given character.
    tokens = [t for t in tokens if t not in _TRIM_ABBREV or t not in {"phm", "phw"}]
    sides = [_SIDE[t] for t in tokens if t in _SIDE]
    body = [t for t in tokens if t not in _SIDE and not (len(t) == 2 and t.isdigit())]
    words = []
    for token in body:
        if token in {"phm", "phw"}:
            continue
        words.append(_TRIM_ABBREV.get(token, token[:1].upper() + token[1:]))
    label = " ".join(words) if words else stem
    return f"{label} — {', '.join(sides)}" if sides else label


def part_label(part: str) -> str:
    """`CD_MainWeapon_Sword_R` as `Main weapon: Sword (right)`.

    The prefix is on every row, so it says nothing about which row this is; the side is the
    thing that actually distinguishes two otherwise identical entries and it was buried at the
    end of a long identifier.
    """

    tokens = [t for t in part.split("_") if t]
    if tokens and tokens[0].lower() == "cd":
        tokens = tokens[1:]
    head = ""
    if tokens and tokens[0].lower() in {"mainweapon", "subweapon", "rangeweapon"}:
        head = {"mainweapon": "Main weapon", "subweapon": "Second weapon",
                "rangeweapon": "Ranged"}[tokens[0].lower()]
        tokens = tokens[1:]
    sides = [_SIDE[t.lower()] for t in tokens if t.lower() in _SIDE]
    rest = [t for t in tokens if t.lower() not in _SIDE]
    name = " ".join(word[:1].upper() + word[1:].lower() for word in rest) or part
    if sides:
        name = f"{name} ({', '.join(sides)})"
    return f"{head}: {name}" if head else name


#: What a rig folder is, where the install actually says so. Only three models carry a
#: descriptor naming them — `phm_description_player_kliff.xml` is where Kliff comes from — so
#: the rest are left as their codes rather than guessed at. Calling an unknown rig "a monster"
#: because its code is unfamiliar would be inventing information the files do not contain.
RIG_NAMES = {
    "1_phm": "Kliff", "2_phw": "Damian", "14_ptm": "PTM",
}

#: The folder every rig sits under. `1_pc` is the playable cast; nothing in the install names
#: the other groups either, so they are shown as they are.
RIG_GROUPS = {"1_pc": "playable"}


def rig_label(rig: str) -> str:
    """`1_pc/1_phm` as `1_phm — Kliff (playable)`, and unknown rigs as themselves.

    The code stays at the front. It is what the clip names are built from and what the search
    box matches, so replacing it outright would break the connection between this dropdown and
    every row beneath it.
    """

    group, _, model = rig.partition("/")
    if not model:
        return rig
    name = RIG_NAMES.get(model, "")
    kind = RIG_GROUPS.get(group, "")
    if name and kind:
        return f"{model} — {name} ({kind})"
    if name:
        return f"{model} — {name}"
    if kind:
        return f"{model} ({kind})"
    return rig
