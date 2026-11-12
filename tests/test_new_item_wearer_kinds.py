"""Equipment for mounts, pets, the dragon, ships and vehicles in Create New Item's data (P8).

Slot and selector names below are the ones the installed game's ItemInfo and
StringInfo use (read 2026-11-12, see the side-thread report). The rows are
owned fixtures; nothing is read from the game here.
"""

from __future__ import annotations

import struct
from types import SimpleNamespace

import pytest

from cdmw.core.item_index import _classify_item_definition
from cdmw.core.iteminfo_row import parse_iteminfo_row
from cdmw.core.stringinfo_table import stringinfo_key
from cdmw.domain.new_item.wearer_kinds import (
    KIND_CREATURE_MOUNT,
    KIND_DRAGON,
    KIND_HORSE,
    KIND_PET,
    KIND_PLAYER,
    KIND_SHIP,
    KIND_WAGON,
    KIND_WAR_MACHINE,
    WEARER_KINDS,
    non_humanoid_selector_kind,
    selector_family,
    wearer_kind_for_slot,
)
from cdmw.services.new_item_template_search import build_template_search_catalogue, search_template_options
from cdmw.services.new_item_wearers import (
    PLAYER_SELECTORS,
    WearerSupportError,
    set_wearer_support,
    template_wearer_kind,
    template_wearers,
    wearer_support,
)
from tests.compact_item_fixtures import item
from tests.item_layout_fixtures import counted

# Every non-humanoid equipment slot the game's EquipTypeInfo names, with its kind.
GAME_SLOTS = {
    "HorseArmor": KIND_HORSE, "HorseHelm": KIND_HORSE, "HorseSaddle": KIND_HORSE,
    "HorseShoe": KIND_HORSE, "HorseStirrup": KIND_HORSE,
    "PetAccessory": KIND_PET, "PetArmor": KIND_PET, "PetHelm": KIND_PET,
    "SpecialVehicleArmor": KIND_CREATURE_MOUNT, "DragonArmor": KIND_DRAGON,
    "ShipBowCannon": KIND_SHIP, "ShipCannon": KIND_SHIP, "ShipFigurehead": KIND_SHIP, "ShipSail": KIND_SHIP,
    "ShipStern": KIND_SHIP, "ShipTeleporter": KIND_SHIP, "TurtleShipBowCannon": KIND_SHIP,
    "WagonDriverSeat": KIND_WAGON, "WagonLantern": KIND_WAGON, "WagonWheel": KIND_WAGON, "Wagoncargo": KIND_WAGON,
    "RobotBackPack": KIND_WAR_MACHINE, "RobotBody": KIND_WAR_MACHINE, "RobotCannon": KIND_WAR_MACHINE,
    "RobotFist": KIND_WAR_MACHINE, "RobotFoot": KIND_WAR_MACHINE, "RobotGatling": KIND_WAR_MACHINE,
}
HUMANOID_SLOTS = ("Upperbody", "Helm", "Cloak", "OneHandSword", "TwoHandPike", "BackPack", "Lantern",
                  "ToolFishingRod", "Tooltrumpet", "Ring", "HiddenEquip", "OneHandShield")


def test_every_game_slot_has_its_wearer_kind():
    for slot, kind in GAME_SLOTS.items():
        assert wearer_kind_for_slot(slot) == kind, slot
    for slot in HUMANOID_SLOTS:
        assert wearer_kind_for_slot(slot) == KIND_PLAYER, slot
    assert {kind.key for kind in WEARER_KINDS} >= set(GAME_SLOTS.values()) | {KIND_PLAYER}


def test_wearer_kinds_agree_with_the_item_finder_groups():
    """The Item Finder puts the same slots under Mount / Pet and Ships; the two rules must not drift."""

    for slot in (*GAME_SLOTS, *HUMANOID_SLOTS):
        category = (_classify_item_definition("item", slot) or ("", ""))[0]
        non_humanoid = category in ("Mount / Pet", "Ships")
        assert non_humanoid == (wearer_kind_for_slot(slot) != KIND_PLAYER), (slot, category)


def test_selectors_name_hulls_wagons_and_breeds_but_not_humanoids():
    assert selector_family("verybigboat_large_none") == selector_family("verybigboat_large_none")
    assert (selector_family("verybigboat_large_none").kind, selector_family("verybigboat_large_none").family) == (
        KIND_SHIP, "large")
    assert selector_family("verybigboat_none").family == "standard"
    assert selector_family("wagon_2horse4wheels_none").kind == KIND_WAGON
    assert selector_family("friesian_none").kind == KIND_HORSE
    assert selector_family("player_2").kind == KIND_PLAYER
    # Humanoid templates also use `_none` selectors; they must not read as creatures.
    for text in ("hexe_none", "imp_none", "machine_none", "human_female", "orc_male"):
        assert selector_family(text).kind == "", text
    assert non_humanoid_selector_kind(("human_female", "verybigboat_small_none")) == KIND_SHIP
    assert non_humanoid_selector_kind(("hexe_none", "player_1")) == ""


def _prefab(selectors, kind=0):
    return (struct.pack('<3f', 1, 2, 3) + counted((111 + kind,)) + counted(())
            + counted((), 'H') + counted(selectors) + struct.pack('<IBBB', 0, 0, 0, kind))


def _row(*worn_selector_lists):
    entries = [_prefab(tuple(stringinfo_key(text) for text in selectors)) for selectors in worn_selector_lists]
    prefabs = struct.pack('<I', len(entries) + 1) + b"".join(entries) + _prefab((789,), 3)
    return parse_iteminfo_row(item(fields={'_prefabDataList': prefabs}), structured=True)


HORSE_BREEDS = ("horse_none", "friesian_none", "arabian_none", "akhalteke_none", "shire_none")
STRINGS = {stringinfo_key(text): text for text in (
    *PLAYER_SELECTORS.values(), *HORSE_BREEDS, "verybigboat_large_none", "verybigboat_small_none",
    "cat_none", "catkitten_none", "hexe_none", "human_female")}


def test_player_controls_refuse_horse_gear_even_without_the_slot_name():
    helm = _row(HORSE_BREEDS)  # one worn entry, as 63 of the game's horse gear rows have
    assert template_wearer_kind(helm, STRINGS) == KIND_HORSE
    with pytest.raises(WearerSupportError, match="not_player_equipment"):
        wearer_support(helm, None, STRINGS)
    with pytest.raises(WearerSupportError, match="not_player_equipment"):
        set_wearer_support(helm, None, STRINGS, "kliff", True)
    wearers = template_wearers(helm, None, STRINGS)
    assert wearers.kind == KIND_HORSE and wearers.families == ("horse", "friesian", "arabian", "akhalteke", "shire")
    assert wearers.worn_entries == 1 and not wearers.unrestricted


def test_pet_gear_is_known_from_its_slot_and_ship_parts_list_their_hulls():
    pet = _row(("cat_none",), ("catkitten_none",))  # one model per species
    assert template_wearer_kind(pet, STRINGS) == KIND_PLAYER  # the selectors alone do not say
    assert template_wearer_kind(pet, STRINGS, equip_type="PetArmor") == KIND_PET
    with pytest.raises(WearerSupportError, match="ambiguous|not_player_equipment"):
        wearer_support(pet, None, STRINGS, equip_type="PetArmor")
    assert template_wearers(pet, None, STRINGS, equip_type="PetArmor").families == ("cat", "catkitten")
    sail = _row(("verybigboat_large_none", "verybigboat_small_none"))
    wearers = template_wearers(sail, None, STRINGS, equip_type="ShipSail")
    assert (wearers.kind, wearers.families) == (KIND_SHIP, ("large", "small"))
    dragon = _row(())
    assert template_wearers(dragon, None, STRINGS, equip_type="DragonArmor").unrestricted
    with pytest.raises(WearerSupportError, match="not_player_equipment"):
        wearer_support(dragon, None, STRINGS, equip_type="DragonArmor")


def test_humanoid_gear_with_creature_like_selectors_keeps_the_player_controls():
    row = _row(("hexe_none", "human_female"))
    assert template_wearer_kind(row, STRINGS, equip_type="Upperbody") == KIND_PLAYER
    support = wearer_support(row, None, STRINGS, equip_type="Upperbody")
    assert "kliff" in support.available
    assert set_wearer_support(row, None, STRINGS, "kliff", True, equip_type="Upperbody") is not None


def _snapshot(rows):
    keyed = {index: SimpleNamespace(string_key=name, is_blocked=False, raw=b"", stat_block_offset=1,
                                    enchant_levels=(), slot=slot)
             for index, (name, slot) in enumerate(rows, start=100)}
    return SimpleNamespace(rows=keyed, item_display_names=lambda: {}, item_search_names=lambda: {},
                           equip_type_name=lambda row: row.slot, item_groups=())


def test_template_search_carries_the_wearer_kind_and_filters_by_it():
    catalogue = build_template_search_catalogue(_snapshot((
        ("Marni_HorseArmor_Armor", "HorseArmor"), ("item_ship_sail_open_0001", "ShipSail"),
        ("Dragon_Armor_01", "DragonArmor"), ("Item_Wagon_Base_Seat_0001", "WagonDriverSeat"),
        ("Leather_Upperbody", "Upperbody"), ("WarRobot_Body_01", "RobotBody"),
    )))
    assert catalogue.wearer_kind_counts() == {KIND_PLAYER: 1, KIND_HORSE: 1, KIND_DRAGON: 1, KIND_SHIP: 1,
                                              KIND_WAGON: 1, KIND_WAR_MACHINE: 1}
    every = search_template_options(catalogue, "", limit=None)
    assert len(every) == 6  # no filter: unchanged, every kind is listed
    players = search_template_options(catalogue, "", limit=None, wearer_kinds={KIND_PLAYER})
    assert [option[1] for option in players] == ["Leather_Upperbody"]
    mounts = search_template_options(catalogue, "", limit=None, wearer_kinds={KIND_HORSE, KIND_DRAGON})
    assert {option[1] for option in mounts} == {"Marni_HorseArmor_Armor", "Dragon_Armor_01"}
    # The kind's label is searchable.
    assert [option[1] for option in search_template_options(catalogue, "ship parts", limit=None)] == [
        "item_ship_sail_open_0001"]
