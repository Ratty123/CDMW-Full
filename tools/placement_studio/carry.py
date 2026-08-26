"""Where a weapon is carried, and which animations belong to that position.

Moving a sword from the hip to the back has to take its draw with it — the arm reaches
somewhere else entirely. The obvious place to look for that link is the action charts,
since they name sockets and clips together, but the association there is far too coarse to
use: a single chart names hundreds of clips, so `RHand_Socket` "matches" 4,989 of them.

So this module measures it instead. A draw animation is a clip in which a hand travels to
wherever the weapon is stowed and takes it; the rig and the socket definitions are both
already loaded, so the reach can simply be played back and watched. Whichever carry socket
a hand comes closest to over the clip is where that draw starts from — and on the shipped
clips the answer is decisive, typically 0.1 m to the winner against 0.25 m to the next.

That makes the placement -> animation question answerable by evidence rather than by naming
convention, which matters because the convention does not hold: `cd_phm_longsword_*` draws
from the hip, not the back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

#: Sockets a weapon can be carried on, in the order they should be offered, with the label
#: the user sees. Everything else a rig defines is an eye, a ring, an effect emitter or a
#: gimmick anchor, none of which are places to hang a sword.
CARRY_SOCKETS: Tuple[Tuple[str, str], ...] = (
    ("RHand_Socket", "Right hand"),
    ("LHand_Socket", "Left hand"),
    ("Pelvis_R_Socket", "Hip — right"),
    ("Pelvis_L_Socket", "Hip — left"),
    ("Pelvis_B_Socket", "Hip — back"),
    ("RThigh_Socket", "Thigh — right"),
    ("LThigh_Socket", "Thigh — left"),
    ("Spine2_B_MainWeapon_Socket", "Back — main weapon"),
    ("Spine2_B_SubWeapon_Socket", "Back — sub weapon"),
    ("Spine2_B_RangeWeapon_Socket", "Back — ranged"),
    ("Spine2_B_RangeWeapon_Musket_Socket", "Back — musket"),
    ("Spine2_B_Shield_Socket", "Back — shield"),
)
# Deliberately absent: `Spine0_B_Socket`, `Spine1_B_Socket` and `Spine2_B_Battery_Socket`.
# They are back attachment points, but no vanilla weapon row stows anything on them, and
# because they sit along the spine within about 0.15 m of the real back sockets they win
# reaches that belong to their neighbours — which showed up as "Back — waist" draws for
# spears that are plainly slung from the main weapon socket.
CARRY_LABELS: Dict[str, str] = dict(CARRY_SOCKETS)
CARRY_ORDER: Tuple[str, ...] = tuple(name for name, _label in CARRY_SOCKETS)

#: The hands are carry positions — a weapon routed there is a weapon being held — but they
#: are not *stow* positions, and they must never be measured against. A hand sits on its own
#: hand socket at a distance of nothing, so including them lets `RHand_Socket` win every clip
#: and the margin test then discards the lot. Measuring is about where a draw *starts*.
HELD_SOCKETS: Tuple[str, ...] = ("RHand_Socket", "LHand_Socket")
STOW_ORDER: Tuple[str, ...] = tuple(
    name for name in CARRY_ORDER if name not in HELD_SOCKETS
)

#: The region of the body a socket belongs to, which is the level animations can actually be
#: told apart at.
#:
#: The grouping is drawn from the measured distances between the sockets on the bind pose,
#: not from their names, because the names mislead. On `1_phm`:
#:
#:   Spine2_B_SubWeapon <-> Spine2_B_RangeWeapon   0.000 m   (the same point)
#:   Spine2_B_Main      <-> Spine2_B_Shield        0.052 m
#:   RThigh             <-> LThigh                 0.050 m
#:   RThigh             <-> Pelvis_R               0.189 m
#:   Pelvis_R           <-> Pelvis_B               0.348 m
#:
#: So the thigh sockets are nearer the hip than the two hip sockets are to each other, and
#: the five upper-back sockets are effectively one place. A reach cannot separate points that
#: close, and it should not try: the animation is the same over-the-shoulder or down-to-the-
#: hip motion whichever of them a weapon hangs on.
#:
#: `Pelvis_B_Socket` — the small of the back — is the awkward one, and it is deliberately not
#: measured at all (see `UNMEASURABLE`). It sits between the other two zones, 0.251 m from the
#: back sockets and 0.348 m from the hip, so whichever zone it joins it eats exactly the
#: separation that hip and back draws need from each other: with it in "back", the shipped
#: one-hand sword draw fell from a 0.177 m margin to 0.004 m and was discarded.
ZONES: Dict[str, str] = {
    "RHand_Socket": "hand",
    "LHand_Socket": "hand",
    "Pelvis_R_Socket": "hip",
    "Pelvis_L_Socket": "hip",
    "RThigh_Socket": "hip",
    "LThigh_Socket": "hip",
    "Pelvis_B_Socket": "hip",
    "Spine2_B_MainWeapon_Socket": "back",
    "Spine2_B_SubWeapon_Socket": "back",
    "Spine2_B_RangeWeapon_Socket": "back",
    "Spine2_B_RangeWeapon_Musket_Socket": "back",
    "Spine2_B_Shield_Socket": "back",
}
ZONE_LABELS: Dict[str, str] = {
    "hand": "In hand",
    "hip": "Hip / thigh",
    "back": "Back",
}
ZONE_ORDER: Tuple[str, ...] = ("hand", "hip", "back")


#: Carry sockets that can be routed to but never measured against. `Pelvis_B_Socket` is too
#: near both zones to separate them, so including it as a candidate loses real draws in both
#: directions; a weapon routed there still gets its zone's clips, just from the other sockets.
UNMEASURABLE: Tuple[str, ...] = ("Pelvis_B_Socket",)


#: The child socket vanilla pairs with each body socket, as a last resort when the descriptor
#: rows resolved for the *selected* weapon happen not to mention that pairing.
#:
#: `conventional_child_socket` reads the live bindings, which resolve against whichever weapon
#: is selected — so with a one-hand sword in hand, nothing in view pairs
#: `Spine2_B_MainWeapon_Socket` with a child socket, the lookup returns nothing, and the move
#: silently keeps the hip's angle. That is what leaves a back-slung sword hanging upside down.
FALLBACK_CHILD_SOCKETS: Dict[str, str] = {
    "Pelvis_R_Socket": "Pelvis_R_ChildSocket",
    "Pelvis_L_Socket": "Pelvis_L_ChildSocket",
    "Spine2_B_MainWeapon_Socket": "Spine2_B_SubWeapon_ChildSocket",
    "Spine2_B_SubWeapon_Socket": "Spine2_B_SubWeapon_ChildSocket",
    "Spine2_B_RangeWeapon_Socket": "Spine2_B_SubWeapon_ChildSocket",
    "Spine2_B_Shield_Socket": "Spine2_B_SubWeapon_ChildSocket",
}


def zone_of(socket: str) -> str:
    """The body region a carry socket sits in, or "" for one that is not a carry point."""

    return ZONES.get(socket, "")


#: Animation family -> how many hands the weapon it belongs to takes.
#:
#: A clip stem is `cd_<character>_<family>_...`, so the family is the third token:
#: `cd_phm_longsword_00_01_...` is `longsword`, `cd_prh_swd_01_01_...` is `swd`. Matching on
#: substrings instead would be wrong in both directions — `sword` is inside `longsword` and
#: `dualsword`, so a one-hand change would rewrite the two-hand animations and vice versa.
#:
#: The split is confirmed by the two shipped mods: `1H Sword Back Carry` replaces the `sword`,
#: `dualsword`, `dlsd`, `swds` and mounted `swd`/`dlsd` families, while `2H Sword Hip Carry`
#: replaces `longsword`, `lswd` and mounted `lswd`.
CLIP_FAMILIES: Dict[str, str] = {
    "sword": "1h",
    "dualsword": "1h",
    "dlsd": "1h",
    "swds": "1h",
    "swd": "1h",
    "longsword": "2h",
    "lswd": "2h",
    # Damian's one-handed set. He shares exactly one family with Kliff — `lswd` — and none of
    # the sword families at all: his weapon *files* are named `cd_phw_01_sword_*`, but the
    # animations for them are `rpr`, the rapier. Without these two, every swap on Damian
    # reported that no animation had a counterpart, which read as the tool being broken.
    "rpr": "1h",
    "2rpr": "1h",
}


#: Which family plays the same role for the other number of hands, best guess first.
#:
#: This is the pairing the shipped mods use, and they use it literally: `1H Sword Back Carry`
#: writes `cd_phm_lswd_00_01_sit_std_weapon_out_00` onto `cd_phm_dlsd_00_01_sit_std_weapon_out_00`
#: — the same clip name with only the family token changed, byte for byte. Six of the eight
#: replacements that have a vanilla counterpart are exact copies; the other two were edited
#: further by hand, and sixteen more were authored outright because no counterpart exists.
#:
#: Going the other way is ambiguous — `lswd` has several one-hand counterparts — so candidates
#: are tried in order and the first that actually exists wins.
#:
#: Damian's pairing was established the same way, by measurement rather than by his file names:
#: renaming the family token of his 640 `lswd` clips lands on a real clip 394 times for `rpr`
#: (62%) and 232 for `2rpr` (36%). For comparison, the best of Kliff's pairings — the ones the
#: shipped mods use literally — matches 15%. Both of Damian's are one-handed: a family that
#: pairs *with* `lswd` sits on the other side of it by construction.
FAMILY_COUNTERPARTS: Dict[str, Tuple[str, ...]] = {
    "sword": ("longsword",),
    "dualsword": ("longsword",),
    "dlsd": ("lswd",),
    "swds": ("lswd",),
    "swd": ("lswd",),
    "longsword": ("sword", "dualsword"),
    # Kliff's candidates first, then Damian's. The two sets are disjoint — no character has
    # both — so a miss on one simply falls through to the other.
    "lswd": ("swds", "dlsd", "swd", "rpr", "2rpr"),
    "rpr": ("lswd",),
    "2rpr": ("lswd",),
}


#: Tokens that sit between the character and the family instead of being one. Kliff's mounted
#: clips fold the context into the character slot — `cd_prh_swd_...` — so the family is still
#: third. Damian's keep her name and add the context after it: `cd_damian_rd_prh_lswd_...`,
#: which put `rd` in the family slot and made every mounted clip of hers unplaceable.
_CONTEXT_TOKENS = frozenset({"rd", "prh"})


def family_of(clip_stem: str) -> str:
    """The animation family a clip belongs to — the third token, past any context tokens."""

    parts = clip_stem.split("_")
    if len(parts) < 3 or parts[0] != "cd":
        return ""
    index = 2
    while index < len(parts) - 1 and parts[index] in _CONTEXT_TOKENS:
        index += 1
    return parts[index]


#: How many trailing variant numbers to try when the exact one has no counterpart.
_VARIANTS = 4


def clip_signature(clip_stem: str):
    """What a clip *is*, with the family and the index numbers taken out.

    A clip name is `cd_<char>_<family>_<A>_<B>_<words...>_<take>`, where `A`/`B` are a stance
    or set index and `take` is which recording it is. None of those three line up across
    weapon families — the two-hand `cd_phm_lswd_01_00_sit_std_idle_00` is the one-hand
    `cd_phm_swds_00_01_sit_std_idle_00` — so matching on the whole name found a counterpart
    for only 26% of what the shipped two-hand mod replaces.

    The descriptive words are kept exactly, and that is the point: `walkfast_start_180_l` is
    a different animation from `walkfast_start_l`, and a looser match would happily pair them.

    Returns `(character, words)`, or `None` when the name is not shaped like a clip.
    """

    parts = clip_stem.split("_")
    if len(parts) < 4 or parts[0] != "cd":
        return None
    body, _number, suffix = _split_variant(clip_stem)
    words = tuple(body.split("_")[3:])
    # Drop the stance pair, which is the leading run of pure numbers after the family.
    while words and words[0].isdigit():
        words = words[1:]
    if not words:
        return None
    return (parts[1], words, suffix)


def _split_variant(stem: str):
    """`(head, number, suffix)` — the trailing take number, and any `_lod` after it.

    `cd_phm_sword_00_01_normal_move_run_f_end_l_000_lod` splits into the name, `000`, `_lod`.
    """

    suffix = ""
    body = stem
    if body.endswith("_lod"):
        body, suffix = body[: -len("_lod")], "_lod"
    head, _sep, last = body.rpartition("_")
    if head and last.isdigit():
        return head, last, suffix
    return body, "", suffix


def counterpart_names(clip_stem: str) -> List[str]:
    """The same clip as it would be named for the other number of hands, best guess first.

    Only the family token changes. A draw is not chosen by measuring where it reaches — it is
    chosen by being *the same animation* authored for the weapon whose carry style you want.

    Take numbers do not line up across families, which matters far more for locomotion than
    for draws: `cd_phm_longsword_00_01_normal_move_run_f_end_l_001` has no `_001` on the
    one-hand side, only `_000`. Requiring an exact match found a counterpart for just 30 of
    the 141 clips the two-hand mod replaces, so the nearby takes are tried too — the original
    number first, since where it does exist it is the right one.
    """

    parts = clip_stem.split("_")
    family = family_of(clip_stem)
    if not family:
        return []

    out: List[str] = []
    for other in FAMILY_COUNTERPARTS.get(family, ()):
        swapped = "_".join(parts[:2] + [other] + parts[3:])
        head, number, suffix = _split_variant(swapped)
        if not number:
            out.append(swapped)
            continue
        width = len(number)
        ordered = [number] + [
            str(i).zfill(width) for i in range(_VARIANTS) if str(i).zfill(width) != number
        ]
        out.extend(f"{head}_{take}{suffix}" for take in ordered)
    return out


def clip_handedness(clip_stem: str) -> str:
    """`1h`, `2h`, or "" when the clip belongs to no weapon family we can place."""

    return CLIP_FAMILIES.get(family_of(clip_stem), "")


def weapon_handedness(weapon) -> str:
    """How many hands the selected weapon takes, read off its own identifiers.

    The game says so twice: a weapon's socket file lives under `weapon/1_onehandweapon/` or
    `weapon/2_twohandweapon/`, and its id carries the same `01`/`02` — `cd_phm_01_sword_0001_r`
    against `cd_phm_02_sword_0001`. The path is checked first because it is unambiguous.
    """

    path = (getattr(weapon, "game_path", "") or "").lower()
    if "1_onehandweapon" in path:
        return "1h"
    if "2_twohandweapon" in path:
        return "2h"
    weapon_id = (getattr(weapon, "weapon_id", "") or "").lower()
    parts = weapon_id.split("_")
    if len(parts) > 2:
        if parts[2] == "01":
            return "1h"
        if parts[2] == "02":
            return "2h"
    return ""

#: The bones that actually take hold of a weapon. Both are tried: plenty of clips draw
#: left-handed, and picking one hand up front would misclassify all of them.
HAND_BONES: Tuple[str, ...] = ("Bip01 R Hand", "Bip01 L Hand")

#: Frames sampled per clip. The reach is a slow arm sweep lasting most of the clip, so a
#: dozen samples find its closest approach; every frame would cost 20x for a distance that
#: changes by millimetres between neighbours. Posing the rig costs 2.3 ms a sample, and this
#: runs over hundreds of clips, so the count is the whole cost of building an index.
SAMPLES = 12

#: A hand this far from a socket never actually took anything off it. Draws that connect
#: land inside 0.2 m; this leaves room for the ones that grip by the fingertips.
MAX_REACH = 0.45

#: How far a hand must close on a socket before that counts as reaching for it.
#:
#: Proximity alone is not the signal, which is the whole subtlety here. In a back draw the
#: right hand goes over the shoulder while the *left* hand hangs idle by the left hip — so
#: the nearest hand-to-socket pair in the entire clip is the idle one, and scoring on
#: distance classifies back draws as hip draws. Measured on the shipped bola and spear
#: draws, nearest-only says `Pelvis_L_Socket` while the hand that actually travels closes
#: 0.26-0.36 m onto `Spine2_B_SubWeapon_Socket`. An idle hand barely moves relative to the
#: socket it happens to sit near, so the distance it closes is what separates the two.
MIN_APPROACH = 0.12

#: How much more the winner must close than the best pair in a different zone before the
#: answer counts as well separated.
#:
#: This ranks rather than gates. It was a gate, and it threw away correct answers: the shipped
#: one-hand sword draw wins for the hip by 0.004 m over the idle left arm swinging past the
#: back sockets, and the spear wins for the back by 0.010 m — both right, both discarded. In
#: every close case checked by hand the winner's *zone* was still correct, so the useful thing
#: to do with a thin margin is to sort it below the clear-cut clips, not to drop it.
MIN_MARGIN = 0.05


@dataclass(frozen=True, slots=True)
class Reach:
    """Where one clip's drawing hand goes."""

    socket: str
    #: Closest the hand ever gets to the socket.
    distance: float
    #: Gap to the best pair naming a different socket, in approach. Small means the two
    #: candidates are equally plausible.
    margin: float
    hand: str = ""
    #: How far the hand closed on the socket over the clip — the evidence a draw happened.
    approach: float = 0.0

    @property
    def confident(self) -> bool:
        """Did a hand demonstrably reach this socket? What decides inclusion at all."""

        return (
            bool(self.socket)
            and self.distance <= MAX_REACH
            and self.approach >= MIN_APPROACH
        )

    @property
    def strong(self) -> bool:
        """Is the zone clearly separated from the runner-up? What decides ordering."""

        return self.confident and self.margin >= MIN_MARGIN

    @property
    def label(self) -> str:
        return CARRY_LABELS.get(self.socket, self.socket)

    @property
    def zone(self) -> str:
        return zone_of(self.socket)

    @property
    def zone_label(self) -> str:
        return ZONE_LABELS.get(self.zone, self.zone)


def carry_positions(session) -> List[Tuple[str, str]]:
    """The carry sockets this rig actually defines, as `(socket, label)`.

    Filtered against the rig rather than offered wholesale: a socket the model does not
    define cannot be routed to, and `set_route` rightly refuses it.
    """

    if session is None:
        return []
    defined = {placed.name for placed in session.placed_sockets()}
    return [(name, label) for name, label in CARRY_SOCKETS if name in defined]


def stow_positions(session) -> List[str]:
    """Carry sockets worth measuring a draw against — everywhere but the hands."""

    skip = set(HELD_SOCKETS) + set() if False else set(HELD_SOCKETS) | set(UNMEASURABLE)
    return [name for name, _label in carry_positions(session) if name not in skip]


def reach_of_clip(session, clip, candidates: Optional[Sequence[str]] = None) -> Reach:
    """Which carry socket this clip's hands reach, measured by playing it back.

    Poses the session frame by frame and watches both hands against every candidate socket.
    The socket positions are re-read each frame because they are parented to bones and move
    with the pose — measuring against the bind pose would put the back socket in the wrong
    place for exactly the clips this is meant to tell apart.

    The session is left posed; callers that care restore it.
    """

    names = list(candidates) if candidates is not None else stow_positions(session)
    if not names or clip is None or session is None:
        return Reach("", float("inf"), 0.0)

    frames = max(1, int(getattr(clip, "frame_count", 1)))
    step = max(1, frames // SAMPLES)
    # (hand, socket) -> the distance between them at every sampled frame.
    series: Dict[Tuple[str, str], List[float]] = {}
    for frame in range(0, frames, step):
        session.apply_pose(clip, float(frame))
        placed = {p.name: p.world_position for p in session.placed_sockets()}
        for bone in (session.hierarchy or ()):
            if bone.name not in HAND_BONES:
                continue
            for name in names:
                point = placed.get(name)
                if point is not None:
                    series.setdefault((bone.name, name), []).append(
                        point.distance_to(bone.world_position)
                    )
    if not series:
        return Reach("", float("inf"), 0.0)

    # Score each hand-socket pair by how far the hand closed, not by how near it got. The
    # median is the resting separation; subtracting the minimum gives the travel.
    scored = []
    for (hand, socket), distances in series.items():
        if len(distances) < 3:
            continue
        nearest = min(distances)
        if nearest > MAX_REACH:
            continue
        ordered = sorted(distances)
        resting = ordered[len(ordered) // 2]
        scored.append((resting - nearest, nearest, socket, hand))
    if not scored:
        return Reach("", float("inf"), 0.0)

    scored.sort(reverse=True)
    approach, nearest, socket, hand = scored[0]
    # The rival has to be a different *zone*. Two back sockets a few centimetres apart are
    # the same reach, and requiring a margin between them would throw away every back draw.
    zone = zone_of(socket)
    rival = next((row[0] for row in scored[1:] if zone_of(row[2]) != zone), None)
    margin = (approach - rival) if rival is not None else float("inf")
    return Reach(socket, nearest, margin, hand, approach)


def is_draw(name: str) -> bool:
    """Does this clip name a draw or a sheathe?

    The only naming convention this module trusts, and only to decide what is worth
    measuring. Not quite as consistent as it looked: `weapon_out` and `weapon_in` are the usual
    spelling, but a run of mounted clips writes them without the underscore, and reading only
    the usual one classified every mounted draw as ordinary locomotion.
    """

    lowered = name.lower()
    return any(word in lowered for word in ("weapon_out", "weapon_in", "weaponout", "weaponin"))


def is_sheathe(name: str) -> bool:
    lowered = name.lower()
    return "weapon_in" in lowered or "weaponin" in lowered


class CarryIndex:
    """Clip -> the carry socket its draw starts from.

    Built by measurement, so it is only as complete as the clips fed to it. Anything that
    could not be decided is simply absent, which is why lookups return a list that may be
    empty rather than a fallback: offering a hip draw for a back carry would be worse than
    offering nothing.
    """

    __slots__ = ("_by_clip",)

    def __init__(self, reaches: Optional[Dict[str, Reach]] = None) -> None:
        self._by_clip: Dict[str, Reach] = dict(reaches or {})

    def __len__(self) -> int:
        return len(self._by_clip)

    def add(self, clip_name: str, reach: Reach) -> None:
        if reach.confident:
            self._by_clip[clip_name] = reach

    def reach(self, clip_name: str) -> Optional[Reach]:
        return self._by_clip.get(clip_name)

    def zones(self) -> List[str]:
        found = {reach.zone for reach in self._by_clip.values() if reach.zone}
        return [name for name in ZONE_ORDER if name in found]

    def clips_for(self, socket: str, *, sheathe: Optional[bool] = None) -> List[str]:
        """Clips whose draw starts from the same body region as this socket.

        Matching by zone, not by exact socket: a weapon moved to `Spine2_B_SubWeapon_Socket`
        wants the same over-the-shoulder draws as one on `Spine2_B_MainWeapon_Socket`, and
        the reach cannot tell those two apart anyway.

        `sheathe=False` gives draws, `True` gives sheathes, `None` gives both. Strongest
        reach first, so the picker's default is the cleanest example.
        """

        return self.clips_for_zone(zone_of(socket), sheathe=sheathe)

    def clips_for_zone(self, zone: str, *, sheathe: Optional[bool] = None) -> List[str]:
        if not zone:
            return []
        rows = [
            (name, reach)
            for name, reach in self._by_clip.items()
            if reach.zone == zone and (sheathe is None or is_sheathe(name) == sheathe)
        ]
        # Clear-cut reaches first, then by how far the hand travelled. A clip whose margin is
        # thin is still very likely right, but it belongs below the unambiguous ones.
        rows.sort(key=lambda row: (not row[1].strong, -row[1].approach, row[0]))
        return [name for name, _reach in rows]

    def counts(self) -> Dict[str, int]:
        """zone -> how many clips were measured to it. What the UI reports."""

        out: Dict[str, int] = {}
        for reach in self._by_clip.values():
            if reach.zone:
                out[reach.zone] = out.get(reach.zone, 0) + 1
        return out

    # ── persistence ────────────────────────────────────────────────

    def to_json(self) -> dict:
        return {
            "version": 1,
            "clips": {
                name: [reach.socket, round(reach.distance, 4), round(reach.margin, 4), reach.hand,
                 round(reach.approach, 4)]
                for name, reach in self._by_clip.items()
            },
        }

    @classmethod
    def from_json(cls, raw) -> "CarryIndex":
        if not isinstance(raw, dict) or raw.get("version") != 1:
            return cls()
        out: Dict[str, Reach] = {}
        for name, row in (raw.get("clips") or {}).items():
            try:
                socket, distance, margin, hand, approach = row
                out[name] = Reach(
                    str(socket), float(distance), float(margin), str(hand), float(approach)
                )
            except (TypeError, ValueError):
                continue
        return cls(out)


def build_index(
    session,
    clips: Iterable[Tuple[str, object]],
    *,
    should_stop=None,
    on_progress=None,
) -> CarryIndex:
    """Measure a batch of clips. `clips` yields `(name, clip)` pairs, already parsed.

    Runs on whatever session it is given — pass a private one, since it poses the rig
    repeatedly and would otherwise fight the viewport for it.
    """

    index = CarryIndex()
    names = stow_positions(session)
    done = 0
    for name, clip in clips:
        if should_stop is not None and should_stop():
            break
        try:
            index.add(name, reach_of_clip(session, clip, names))
        except Exception:  # noqa: BLE001 - one unreadable clip must not stop the sweep
            pass
        done += 1
        if on_progress is not None and done % 25 == 0:
            on_progress(done)
    return index


#: Which clip names belong to the player themselves, per model.
#:
#: The motion tree is shared: an unfiltered sweep of `1_phm` rewrote 121 files including
#: `cd_darkguide` and `cd_redwarden` — every boss's draw, for a change to the player's sword.
#: So a swap only ever touches the player's own clips, and this is the list of what those are
#: called. It was hard-coded to Kliff's two prefixes, which meant every swap on Damian matched
#: nothing at all and reported that no animation had a counterpart.
#:
#: `cd_prh_` is Kliff mounted; Damian's mounted clips are named after him instead.
PLAYER_CLIP_PREFIXES: Dict[str, Tuple[str, ...]] = {
    "1_phm": ("cd_phm_", "cd_prh_"),
    "2_phw": ("cd_phw_", "cd_damian_"),
}


def player_clip_prefixes(model: str) -> Tuple[str, ...]:
    """The prefixes a swap may rewrite for this character, never another's.

    An unknown model falls back to its own token alone — narrow rather than wide, because the
    cost of being wrong here is rewriting somebody else's animations.
    """

    known = PLAYER_CLIP_PREFIXES.get(model)
    if known:
        return known
    token = model.split("_", 1)[-1] if "_" in model else model
    return (f"cd_{token}_",) if token else ()


def clip_motion(clip_stem: str):
    """What a clip *does*, with the character taken out as well as the family and the takes.

    `clip_signature` keeps the character, which is right when a swap stays inside one body.
    Borrowing across bodies needs the same words to match regardless of who they were authored
    for, so this is that signature minus its first element.
    """

    signature = clip_signature(clip_stem)
    return None if signature is None else (signature[1], signature[2])


#: The other playable character, for borrowing animations when a body has none of its own.
#:
#: Their skeletons share 403 bone names of Kliff's 434 and Damian's 448, and a Kliff sword draw
#: resolves against Damian's rig with exactly the coverage it has on Kliff's — 89.6% either way.
#: So the clip plays. It is not free: `.paa` keys are bind-pose deltas in bone-local axes, so
#: the same rotations on different proportions land in a slightly different place, and contact
#: points are where that shows. A borrowed draw may reach near the hilt rather than onto it.
OTHER_PLAYER: Dict[str, str] = {"1_phm": "2_phw", "2_phw": "1_phm"}


def borrowed_from_other_body(target_stem: str, donor_stem: str) -> bool:
    """Whether this pair crosses from one playable character to the other."""

    target, donor = clip_signature(target_stem), clip_signature(donor_stem)
    if target is None or donor is None:
        return False
    return target[0] != donor[0]


# ── animation scope ──────────────────────────────────────────────────
#
# Scope is the whole risk in a move. `1_phm`'s motion tree is shared with every NPC that uses
# it, and the family names overlap by substring, so a sweep one token too wide rewrites a
# boss's draw for a change to the player's sword. Everything below builds an *allowlist* —
# the exact target paths an operation may write — rather than filtering a wide set down.

#: The four scopes a move may ask for, narrowest first.
SCOPE_PLACEMENT_ONLY = "placement_only"
SCOPE_DRAW_STOW = "draw_stow"
SCOPE_STOWED_LOCOMOTION = "stowed_locomotion"
SCOPE_FULL_BODY = "full_body"

SCOPE_ORDER: Tuple[str, ...] = (
    SCOPE_PLACEMENT_ONLY,
    SCOPE_DRAW_STOW,
    SCOPE_STOWED_LOCOMOTION,
    SCOPE_FULL_BODY,
)

SCOPE_LABELS: Dict[str, str] = {
    SCOPE_PLACEMENT_ONLY: "Placement only",
    SCOPE_DRAW_STOW: "Draw and stow only",
    SCOPE_STOWED_LOCOMOTION: "Draw, stow, and stowed locomotion",
    SCOPE_FULL_BODY: "Full-body family replacement (advanced)",
}

SCOPE_HINTS: Dict[str, str] = {
    SCOPE_PLACEMENT_ONLY: "Move the item and leave every animation alone.",
    SCOPE_DRAW_STOW: "The minimum that makes a moved weapon look right.",
    SCOPE_STOWED_LOCOMOTION: "Also how the character stands and moves with it stowed.",
    SCOPE_FULL_BODY: (
        "Every animation in the weapon's family, including incidental ones. Donor clips "
        "drive the whole body, so the off-hand, shield arm and stance change too."
    ),
}

#: Scopes that must never be reached without the user saying so outright.
ADVANCED_SCOPES: Tuple[str, ...] = (SCOPE_FULL_BODY,)


#: Optional context groups, each opted into separately. `Everything` used to mean all of
#: these at once, with only a file count to judge it by.
CONTEXT_GROUPS: Tuple[Tuple[str, str], ...] = (
    ("standing", "Standing"),
    ("locomotion", "Walking and running"),
    ("crouching", "Crouching and low stance"),
    ("sitting", "Sitting"),
    ("riding", "Riding"),
    ("combat", "Combat"),
    ("traversal", "Climbing and traversal"),
    ("other", "Other incidental states"),
)
CONTEXT_LABELS: Dict[str, str] = dict(CONTEXT_GROUPS)

#: Contexts the stowed-locomotion preset covers: how the character carries the weapon through
#: ordinary movement, and nothing beyond it.
STOWED_LOCOMOTION_CONTEXTS: Tuple[str, ...] = ("standing", "locomotion")

#: Contexts that must be opted into explicitly whatever the scope. Riding puts the character
#: on another rig entirely, and traversal clips move the whole body through space.
OPT_IN_CONTEXTS: Tuple[str, ...] = ("riding", "traversal")

#: Tokens that place a clip in a context group, tried in this order, so a mounted draw is
#: `riding` rather than `standing`.
#:
#: `sit_std` is deliberately *not* `sitting`. The action charts put
#: `cd_phm_swds_00_01_sit_std_*` in `sword_upper.paac`, an ordinary on-foot chart — what `sit`
#: denotes there is a lowered stance, so it groups with crouching. The genuinely seated clips
#: are the `tosit` ones.
_CONTEXT_GROUP_TOKENS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("traversal", ("climb", "ladder", "vault", "swim", "rope", "hang", "mantle")),
    ("combat", ("_att_", "attack", "skill", "_hit_", "guard", "parry", "block", "dodge",
                "avoid", "counter", "execution")),
    ("sitting", ("tosit", "sitdown", "chair", "bench")),
    ("crouching", ("crouch", "sneak", "crawl", "sit_base_std", "sit_std")),
    ("locomotion", ("move_", "turn", "step", "walk", "run", "jump", "dash", "roll")),
    ("standing", ("nor_std", "nor_stand", "normal_stand", "nor_base_std", "alert", "idle",
                  "_std_")),
)

#: Families whose clips drive both hands. A donor from one of these can change the off-hand
#: pose and the shield arm even though the item being moved is a single weapon.
DUAL_WIELD_FAMILIES: frozenset = frozenset({"dualsword", "dlsd", "swds", "2rpr"})


def other_handedness(hands: str) -> str:
    """`1h` <-> `2h`, or "" when the handedness is unknown."""

    if hands == "1h":
        return "2h"
    if hands == "2h":
        return "1h"
    return ""


def families_for_handedness(hands: str) -> Tuple[str, ...]:
    """Every animation family belonging to that number of hands, in a stable order."""

    return tuple(sorted(name for name, kind in CLIP_FAMILIES.items() if kind == hands))


def target_families(hands: str, *, available: Optional[Iterable[str]] = None) -> Tuple[str, ...]:
    """The families a weapon of this handedness owns — the only paths it may write to.

    `available` narrows the list to families this character actually ships, which is what
    keeps a two-hand move on Damian from declaring Kliff's `longsword` among its targets.
    """

    families = families_for_handedness(hands)
    if available is None:
        return families
    seen = {str(name) for name in available}
    return tuple(name for name in families if name in seen)


def donor_families(hands: str, *, available: Optional[Iterable[str]] = None) -> Tuple[str, ...]:
    """The families a weapon of this handedness may *borrow* bytes from.

    Deliberately the other handedness: a two-handed carry style is achieved by giving the
    weapon the other grip's motion. Donors are not targets, and reporting the two apart is
    what makes a genuine one-handed target leak visible.
    """

    return target_families(other_handedness(hands), available=available)


def is_mounted(clip_stem: str) -> bool:
    """Is this a horseback clip?

    The context token sits in different slots per character — Kliff folds it into the
    character token (`cd_prh_swd_...`), Damian keeps her name and adds it after
    (`cd_damian_rd_prh_...`) — so the first few tokens are checked rather than one position.
    """

    parts = clip_stem.lower().split("_")
    return bool(set(parts[1:4]) & _CONTEXT_TOKENS)


def context_group_of(clip_stem: str) -> str:
    """Which optional context group a clip belongs to. Never empty."""

    if is_mounted(clip_stem):
        return "riding"
    lowered = f"_{clip_stem.lower()}_"
    for group, tokens in _CONTEXT_GROUP_TOKENS:
        if any(token in lowered for token in tokens):
            return group
    return "other"


@dataclass(frozen=True, slots=True)
class AnimationScope:
    """How much of the animation set a move may rewrite.

    Every default here is the safe one: draw and stow, on foot, this character's own clips.
    Each widening is a field somebody had to set.
    """

    kind: str = SCOPE_DRAW_STOW
    #: Which context groups are in. Empty means "whatever the preset implies".
    contexts: Tuple[str, ...] = ()
    include_borrowed: bool = False
    include_mounted: bool = False
    include_other_models: bool = False

    @property
    def label(self) -> str:
        return SCOPE_LABELS.get(self.kind, self.kind)

    @property
    def is_advanced(self) -> bool:
        return self.kind in ADVANCED_SCOPES

    @property
    def replaces_animations(self) -> bool:
        return self.kind != SCOPE_PLACEMENT_ONLY

    def effective_contexts(self) -> Tuple[str, ...]:
        """The context groups actually in play, with the opt-in ones honoured."""

        if self.kind == SCOPE_PLACEMENT_ONLY:
            return ()
        if self.contexts:
            chosen = tuple(self.contexts)
        elif self.kind == SCOPE_STOWED_LOCOMOTION:
            chosen = STOWED_LOCOMOTION_CONTEXTS
        else:
            chosen = tuple(name for name, _label in CONTEXT_GROUPS)
        out = [name for name in chosen if name not in OPT_IN_CONTEXTS]
        if self.include_mounted and "riding" in chosen:
            out.append("riding")
        if "traversal" in self.contexts:
            out.append("traversal")
        return tuple(dict.fromkeys(out))

    def allows_clip(self, clip_stem: str) -> bool:
        if self.kind == SCOPE_PLACEMENT_ONLY:
            return False
        drawing = is_draw(clip_stem)
        if self.kind == SCOPE_DRAW_STOW and not drawing:
            return False
        group = context_group_of(clip_stem)
        if self.kind == SCOPE_STOWED_LOCOMOTION and not drawing:
            if group not in STOWED_LOCOMOTION_CONTEXTS:
                return False
        if group == "riding" and not self.include_mounted:
            return False
        return group in self.effective_contexts()


def recommended_scope(from_socket: str, to_socket: str) -> str:
    """The scope a move should start on, given where it is going.

    Moving within a zone does not change how the weapon is reached for, so nothing needs
    replacing. Crossing between hip and back does, and draw-and-stow is the minimum that
    covers it. Full-body is never a default.
    """

    from_zone, to_zone = zone_of(from_socket), zone_of(to_socket)
    if not to_zone or from_zone == to_zone:
        return SCOPE_PLACEMENT_ONLY
    return SCOPE_DRAW_STOW


@dataclass(frozen=True, slots=True)
class AnimationReplacement:
    """One target clip, the donor chosen for it, and what makes it risky.

    Indexable as `(target, donor, options)` so the move dialog, which unpacks rows
    positionally, keeps working while the richer fields are there for the review page.
    """

    target: object
    donor: object
    options: Tuple[object, ...] = ()
    target_family: str = ""
    donor_family: str = ""
    context_group: str = "other"
    borrowed: bool = False
    mounted: bool = False
    dual_wield_donor: bool = False

    def __getitem__(self, index: int):
        return (self.target, self.donor, self.options)[index]

    def __len__(self) -> int:
        return 3

    def __iter__(self):
        return iter((self.target, self.donor, self.options))

    @property
    def target_path(self) -> str:
        return str(getattr(self.target, "path", "") or "")

    @property
    def risks(self) -> Tuple[str, ...]:
        out = []
        if self.borrowed:
            out.append("borrowed from the other playable character")
        if self.mounted:
            out.append("horseback")
        if self.dual_wield_donor:
            out.append("dual-wield donor: may alter the off-hand")
        return tuple(out)


from .carry_replacements import (
    _target_entries,
    animation_target_allowlist,
    context_counts,
    family_counts,
    rank_donors,
    risk_summary,
    risk_warnings,
    swappable_pairs,
)
