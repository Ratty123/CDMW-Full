"""P8's screens: Create New Item's Template page for mounts, pets, the dragon, ships and vehicles.

The real Template page is built headlessly and driven through the Rust input bridge,
as the helper drives it. The game is an owned fixture: the wearer test game plus one
template per kind, with the game's own slot and selector names (read from the
installed tables on 2026-11-12, see the side-thread report); nothing is read from
the game here, and nothing here is proven in game.
"""

from __future__ import annotations

import json
import struct

import pytest

from cdmw.core.iteminfo_row import equip_type_key, parse_iteminfo_row
from cdmw.core.stringinfo_table import stringinfo_key
from cdmw.domain.new_item.wearer_kinds import (
    KIND_DRAGON, KIND_HORSE, KIND_PET, KIND_PLAYER, KIND_SHIP, KIND_WAGON, KIND_WAR_MACHINE,
)
from cdmw.services.new_item_template_search import USABLE_ITEMS_CATEGORY, search_template_options
from cdmw.ui.new_item.state import NewItemDraft
from tests.compact_item_fixtures import item
from tests.item_layout_fixtures import counted
from tests.test_iteminfo_row import build_row
from tests.test_new_item_rust_ui import _send, studio  # noqa: F401 - the fixture
from tests.test_new_item_wearers import wearer_game  # noqa: F401 - the fixture

HORSE_BREEDS = ("horse_none", "friesian_none", "arabian_none", "akhalteke_none", "shire_none")
SELECTORS = (*HORSE_BREEDS, "verybigboat_large_none", "verybigboat_small_none", "cat_none", "greatdane_none",
             "wagon_2horse4wheels_none", "player_2", "human_female")

#: (key, internal name, EquipTypeInfo slot, worn selector lists, expected kind, expected lines)
TEMPLATES = {
    "horse helm": (3000001, "Test_Horse_Helm", "HorseHelm", (HORSE_BREEDS,), KIND_HORSE,
                   ("Template kind: Horse gear",
                    "Worn by these horse breeds: horse, friesian, arabian, akhalteke, shire",
                    "Worn model entries: 1")),
    "ship sail": (3000002, "Test_Ship_Sail", "ShipSail", (("verybigboat_large_none", "verybigboat_small_none"),),
                  KIND_SHIP, ("Template kind: Ship parts", "Worn by these ship hulls: large, small",
                              "Worn model entries: 1")),
    "pet armour": (3000003, "Test_Pet_Armor", "PetArmor", (("cat_none",), ("greatdane_none",)), KIND_PET,
                   ("Template kind: Pet gear", "Worn by these pets: cat, greatdane", "Worn model entries: 2")),
    "dragon armour": (3000004, "Dragon_Armor_Test", "DragonArmor", ((),), KIND_DRAGON,
                      ("Template kind: Dragon gear", "Not limited to particular dragons.", "Worn model entries: 1")),
    "wagon seat": (3000005, "Test_Wagon_Seat", "WagonDriverSeat", (("wagon_2horse4wheels_none",),), KIND_WAGON,
                   ("Template kind: Wagon parts", "Worn by these wagons: 2horse4wheels", "Worn model entries: 1")),
    "war machine": (3000006, "Test_Robot_Body", "RobotBody", ((),), KIND_WAR_MACHINE,
                    ("Template kind: War machine parts", "Not limited to particular war machines.",
                     "Worn model entries: 1")),
    "humanoid chest": (3000007, "Test_Upperbody", "Upperbody", (("player_2", "human_female"),), KIND_PLAYER, ()),
}


def _prefab(selectors, kind=0):
    return (struct.pack('<3f', 1, 2, 3) + counted((111 + kind,)) + counted(())
            + counted((), 'H') + counted(selectors) + struct.pack('<IBBB', 0, 0, 0, kind))


def _template(key, name, slot, selector_lists):
    entries = [_prefab(tuple(stringinfo_key(text) for text in selectors)) for selectors in selector_lists]
    prefabs = struct.pack('<I', len(entries) + 1) + b"".join(entries) + _prefab((789,), 3)
    raw = item(build_row(key=key, string_key=name, equip=slot.lower()), fields={'_prefabDataList': prefabs})
    return parse_iteminfo_row(raw, structured=True)


@pytest.fixture
def creature_game(wearer_game):
    """The wearer test game with one template of each kind added to its snapshot."""

    service, snapshot = wearer_game
    rows, names = dict(snapshot.rows), dict(snapshot.equip_type_names)
    for key, name, slot, selector_lists, _kind, _lines in TEMPLATES.values():
        rows[key] = _template(key, name, slot, selector_lists)
        names[equip_type_key(slot)] = slot
    snapshot.rows = rows
    snapshot.equip_type_names = names
    snapshot.stringinfo_texts = {**snapshot.stringinfo_texts, **{stringinfo_key(t): t for t in SELECTORS}}
    snapshot._template_search_catalogue = None
    return service, snapshot


def _shown(panel, expected=None, timeout=5.0):
    """The template list's keys once the search lane has answered (it may run off the GUI thread)."""

    import time

    from PySide6.QtWidgets import QApplication

    deadline = time.monotonic() + timeout
    while True:
        QApplication.processEvents()
        keys = [panel.matches.topLevelItem(i).data(0, 0x0100) for i in range(panel.matches.topLevelItemCount())]
        if expected is None or expected(keys) or time.monotonic() > deadline:
            return keys
        time.sleep(0.01)


def _open(tab, snapshot, key):
    controller = tab.controller
    controller.snapshot = snapshot
    controller.draft = NewItemDraft(template_key=key, internal_name="P8", display_names={"eng": "P8"})
    controller.invalidate_plan()
    tab.show_step(0)
    # The studio fixture prefills the Find box with its template's name; these tests search everything.
    tab.template_panel.filter_edit.clear()
    return tab.template_panel.wearers


@pytest.mark.parametrize("name", list(TEMPLATES))
def test_the_wearer_box_shows_who_wears_the_template_and_offers_players_only_for_humanoid_gear(
        studio, creature_game, name):
    _fixture, tab, bridge = studio
    _service, snapshot = creature_game
    key, _internal, slot, _selectors, kind, lines = TEMPLATES[name]
    assert snapshot.equip_type_name(snapshot.rows[key]) == slot
    editor = _open(tab, snapshot, key)
    projected = json.dumps(bridge.snapshot(), ensure_ascii=False)
    if kind == KIND_PLAYER:
        assert editor.player_choices.isVisibleTo(editor) and not editor.worn_by.isVisibleTo(editor)
        assert editor.choices["kliff"].isEnabled()
        assert editor.choices["damiane"].isChecked() and not editor.choices["damiane"].isEnabled()
        assert editor.status.text() == "Locked choices are already included by the template."
        _send(bridge, editor.choices["kliff"], "toggle", True)
        assert tab.controller.draft.behavior_settings is not None
        return
    # Creature, hull and vehicle gear: the player boxes are gone, the wearers are listed read-only.
    assert not editor.player_choices.isVisibleTo(editor) and not editor.note.isVisibleTo(editor)
    assert editor.worn_by.isVisibleTo(editor)
    assert tuple(editor.worn_by.text().split("\n")) == lines
    assert editor.status.text() == (
        "This template is not worn by a playable character, so its wearers cannot be changed here.")
    for line in lines:
        assert line in projected
    assert "Kliff" not in projected
    # And the player selectors cannot be written into it, even when asked directly.
    editor._changed("kliff", True)
    assert tab.controller.draft.behavior_settings is None


def test_worn_by_lists_each_kind_with_its_count_and_filters_the_template_list(studio, creature_game):
    _fixture, tab, bridge = studio
    _service, snapshot = creature_game
    _open(tab, snapshot, TEMPLATES["humanoid chest"][0])
    panel = tab.template_panel
    panel._refresh_categories()
    counts = snapshot.template_search_catalogue().wearer_kind_counts()
    assert counts[KIND_HORSE] == counts[KIND_SHIP] == counts[KIND_PET] == counts[KIND_DRAGON] == 1
    assert counts[KIND_WAGON] == counts[KIND_WAR_MACHINE] == 1 and counts[KIND_PLAYER] >= 1
    items = [(panel.worn_by.itemText(i), panel.worn_by.itemData(i)) for i in range(panel.worn_by.count())]
    assert items[0] == ("All", None)
    assert items[1:] == [(text, kind) for kind, text in (
        (KIND_PLAYER, f"Characters ({counts[KIND_PLAYER]:,})"), (KIND_HORSE, "Horse gear (1)"),
        (KIND_PET, "Pet gear (1)"), (KIND_DRAGON, "Dragon gear (1)"), (KIND_SHIP, "Ship parts (1)"),
        (KIND_WAGON, "Wagon parts (1)"), (KIND_WAR_MACHINE, "War machine parts (1)"))]
    # The added fixture templates are in no game equipment group, so list All equipment.
    _send(bridge, panel.category, "choose", panel.category.findText("All equipment"))
    ours = {value[0] for value in TEMPLATES.values()}
    every = set(_shown(panel, lambda keys: ours <= set(keys)))
    assert ours <= every
    horse, ship = TEMPLATES["horse helm"][0], TEMPLATES["ship sail"][0]
    _send(bridge, panel.worn_by, "choose", panel.worn_by.findData(KIND_HORSE))
    assert _shown(panel, lambda keys: keys == [horse]) == [horse]
    _send(bridge, panel.worn_by, "choose", panel.worn_by.findData(KIND_SHIP))
    assert _shown(panel, lambda keys: keys == [ship]) == [ship]
    _send(bridge, panel.worn_by, "choose", 0)
    assert set(_shown(panel, lambda keys: set(keys) == every)) == every


def test_usable_items_are_worn_by_no_one(studio, creature_game):
    """A chosen wearer kind hides usable items; All, and the Usable items category, show them."""

    _fixture, tab, bridge = studio
    _service, snapshot = creature_game
    _open(tab, snapshot, TEMPLATES["humanoid chest"][0])
    panel = tab.template_panel
    panel._refresh_categories()
    _send(bridge, panel.worn_by, "choose", panel.worn_by.findData(KIND_HORSE))
    assert panel.worn_by.isEnabled()
    _send(bridge, panel.category, "choose", panel.category.findData(USABLE_ITEMS_CATEGORY))
    # Under Usable items the filter is All and switched off, so usable items still list.
    assert panel.worn_by.currentIndex() == 0 and not panel.worn_by.isEnabled()
    assert panel._worn_by_kinds() is None
    catalogue = snapshot.template_search_catalogue()
    usable = search_template_options(catalogue, "", group_key=USABLE_ITEMS_CATEGORY, limit=None)
    assert search_template_options(catalogue, "", group_key=USABLE_ITEMS_CATEGORY, limit=None,
                                   wearer_kinds={KIND_PLAYER}) == []
    expected = [option[0] for option in usable]
    assert _shown(panel, lambda keys: keys == expected) == expected


def test_typing_a_kind_finds_its_templates(creature_game):
    _service, snapshot = creature_game
    catalogue = snapshot.template_search_catalogue()
    found = {option[1] for option in search_template_options(catalogue, "horse gear", limit=None)}
    assert found == {"Test_Horse_Helm"}
    found = {option[1] for option in search_template_options(catalogue, "war machine", limit=None)}
    assert found == {"Test_Robot_Body"}
