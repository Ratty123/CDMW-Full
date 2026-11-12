"""Who wears an equipment template: a playable character, or a mount, pet, dragon, ship or vehicle.

Create New Item's wearer controls were written for humanoid equipment, whose
worn prefab lists player selectors (`player_1` and so on). The game's ItemInfo
also holds equipment for horses, pets, ridable creatures, the dragon, ships,
wagons and the war machine. Those rows use the same ItemInfo route, carry
stats, and list creature or hull selectors instead (`horse_none`,
`cat_none`, `verybigboat_large_none`, `wagon_2horse4wheels_none`).

Evidence: the game's own tables, read from the installed archives on
2026-11-12 (slot names and counts are in the side-thread report, P8). Nothing
here is proven in game.

These rules are pure. The slot names are the EquipTypeInfo names
(`snapshot.equip_type_name(row)`); `cdmw.core.item_index._classify_item_definition`
groups the same slots under "Mount / Pet" and "Ships" for the Item Finder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

KIND_PLAYER = "player"
KIND_HORSE = "horse"
KIND_PET = "pet"
KIND_CREATURE_MOUNT = "creature_mount"
KIND_DRAGON = "dragon"
KIND_SHIP = "ship"
KIND_WAGON = "wagon"
KIND_WAR_MACHINE = "war_machine"


@dataclass(frozen=True, slots=True)
class WearerKind:
    key: str
    label: str
    #: What a wearer of this kind is called in a sentence ("horse breeds", "ship hulls").
    wearer_label: str
    humanoid: bool = False


WEARER_KINDS: tuple[WearerKind, ...] = (
    WearerKind(KIND_PLAYER, "Characters", "characters", humanoid=True),
    WearerKind(KIND_HORSE, "Horse gear", "horse breeds"),
    WearerKind(KIND_PET, "Pet gear", "pets"),
    WearerKind(KIND_CREATURE_MOUNT, "Creature mount gear", "creatures"),
    WearerKind(KIND_DRAGON, "Dragon gear", "dragons"),
    WearerKind(KIND_SHIP, "Ship parts", "ship hulls"),
    WearerKind(KIND_WAGON, "Wagon parts", "wagons"),
    WearerKind(KIND_WAR_MACHINE, "War machine parts", "war machines"),
)
_KINDS = {kind.key: kind for kind in WEARER_KINDS}

# Exact slot names first, then prefixes. Lower case.
_EXACT = {
    "specialvehiclearmor": KIND_CREATURE_MOUNT,
    "dragonarmor": KIND_DRAGON,
    "turtleshipbowcannon": KIND_SHIP,
    "ghostshipbowcannon": KIND_SHIP,
}
_PREFIXES = (
    ("horse", KIND_HORSE),
    ("pet", KIND_PET),
    ("ship", KIND_SHIP),
    ("wagon", KIND_WAGON),
    ("robot", KIND_WAR_MACHINE),
)

# Selector strings, as StringInfo holds them. Players and humans have no `_none` gender.
_PLAYER_PREFIX = "player_"
_SHIP_SELECTOR_PREFIX = "verybigboat"
_WAGON_SELECTOR_PREFIX = "wagon_"
_HORSE_BREEDS = frozenset({"horse", "friesian", "arabian", "akhalteke", "shire"})
_GENDER_SUFFIXES = ("_none", "_male", "_female")


def wearer_kind(key: str) -> WearerKind:
    return _KINDS.get(str(key or ""), _KINDS[KIND_PLAYER])


def wearer_kind_for_slot(equip_type: object) -> str:
    """The wearer kind of an EquipTypeInfo slot name; humanoid for anything else."""

    slot = str(equip_type or "").strip().casefold()
    if slot in _EXACT:
        return _EXACT[slot]
    for prefix, kind in _PREFIXES:
        if slot.startswith(prefix):
            return kind
    return KIND_PLAYER


def is_humanoid_slot(equip_type: object) -> bool:
    return wearer_kind(wearer_kind_for_slot(equip_type)).humanoid


@dataclass(frozen=True, slots=True)
class SelectorFamily:
    """One wearer selector read as a family: `verybigboat_large_none` is the large ship hull."""

    text: str
    kind: str
    family: str
    gender: str = ""


def selector_family(text: object) -> SelectorFamily:
    """Read one selector string. The kind is "" when the string alone does not say.

    Only rules seen in the game data are applied: player selectors, ship hulls
    (`verybigboat...`), wagons (`wagon_...`) and the five horse breeds. A pet
    or ridable creature is known from its slot, not from its selector.
    """

    raw = str(text or "").strip().casefold()
    gender = ""
    stem = raw
    for suffix in _GENDER_SUFFIXES:
        if raw.endswith(suffix):
            stem, gender = raw[: -len(suffix)], suffix[1:]
            break
    if raw.startswith(_PLAYER_PREFIX):
        return SelectorFamily(raw, KIND_PLAYER, raw, "")
    if stem.startswith(_SHIP_SELECTOR_PREFIX):
        hull = stem[len(_SHIP_SELECTOR_PREFIX):].lstrip("_") or "standard"
        return SelectorFamily(raw, KIND_SHIP, hull, gender)
    if stem.startswith(_WAGON_SELECTOR_PREFIX):
        return SelectorFamily(raw, KIND_WAGON, stem[len(_WAGON_SELECTOR_PREFIX):], gender)
    if stem in _HORSE_BREEDS:
        return SelectorFamily(raw, KIND_HORSE, stem, gender)
    return SelectorFamily(raw, "", stem, gender)


def non_humanoid_selector_kind(selectors: Iterable[object]) -> str:
    """The non-humanoid kind a selector list names, or "" when it names none.

    Used where only the prefab is known: a worn entry listing a ship hull, a
    wagon or a horse breed belongs to that kind whatever the caller thinks.
    """

    for text in selectors:
        family = selector_family(text)
        if family.kind and family.kind != KIND_PLAYER:
            return family.kind
    return ""


__all__ = [
    "KIND_CREATURE_MOUNT",
    "KIND_DRAGON",
    "KIND_HORSE",
    "KIND_PET",
    "KIND_PLAYER",
    "KIND_SHIP",
    "KIND_WAGON",
    "KIND_WAR_MACHINE",
    "SelectorFamily",
    "WEARER_KINDS",
    "WearerKind",
    "is_humanoid_slot",
    "non_humanoid_selector_kind",
    "selector_family",
    "wearer_kind",
    "wearer_kind_for_slot",
]
