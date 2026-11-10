"""Part role names on both sides of the October 2026 `CD_` rename."""

import pytest

from cdmw.core.prefab_corpus_probe_values import (
    _longer_placement_probe_value,
    _same_length_placement_probe_value,
)
from cdmw.domain.part_names import (
    bare_part_name,
    find_part_name,
    is_part_role_name,
    part_name_like,
    same_part_name,
)


@pytest.mark.parametrize("name,bare", [
    ("CD_MainWeapon_Sword_R", "MainWeapon_Sword_R"),
    ("MainWeapon_Sword_R", "MainWeapon_Sword_R"),
    ("CD_Bag_For_Dock", "Bag_For_Dock"),
    (" CD_Upperbody ", "Upperbody"),
    ("", ""),
    (None, ""),
])
def test_the_bare_name_drops_only_the_pre_update_prefix(name, bare):
    assert bare_part_name(name) == bare


def test_either_naming_is_the_same_role_and_other_roles_are_not():
    assert same_part_name("CD_TwoHandWeapon_Sword_IN", "TwoHandWeapon_Sword_IN")
    assert same_part_name("Hair", "CD_Hair")
    assert not same_part_name("MainWeapon_Sword_R", "MainWeapon_Sword_R_Aux")
    assert not same_part_name("CD_Hair", "Hair_Tail")
    assert not same_part_name("", "CD_")


def test_a_written_name_takes_the_form_of_the_file_it_goes_into():
    assert part_name_like("CD_MainWeapon_Sword_L", "MainWeapon_Sword_R") == "MainWeapon_Sword_L"
    assert part_name_like("MainWeapon_Sword_L", "CD_MainWeapon_Sword_R") == "CD_MainWeapon_Sword_L"
    assert part_name_like("CD_MainWeapon_Sword_L", "CD_MainWeapon_Sword_R") == "CD_MainWeapon_Sword_L"
    assert part_name_like("", "CD_MainWeapon_Sword_R") == ""


def test_lookup_returns_the_spelling_the_descriptor_uses():
    current = ("MainWeapon_Sword_IN_R", "MainWeapon_Sword_R")
    legacy = ("CD_MainWeapon_Sword_IN_R", "CD_MainWeapon_Sword_R")
    assert find_part_name(current, "CD_MainWeapon_Sword_R") == "MainWeapon_Sword_R"
    assert find_part_name(legacy, "MainWeapon_Sword_R") == "CD_MainWeapon_Sword_R"
    assert find_part_name(current, "TwoHandWeapon_Sword") == ""


@pytest.mark.parametrize("text,expected", [
    ("MainWeapon_Sword_R", True), ("CD_MainWeapon_Sword_R", True), ("p1", True),
    ("character/model/a.pac", False), ("Hair Tail", False), ("_partName", False), ("", False),
])
def test_role_shape(text, expected):
    assert is_part_role_name(text) is expected


@pytest.mark.parametrize("value", ["CD_MainWeapon_Sword_R", "MainWeapon_Sword_R"])
def test_corpus_probes_rename_a_role_in_either_naming_and_keep_its_form(value):
    same = _same_length_placement_probe_value("_partName", value)
    assert same and same != value and len(same) == len(value)
    assert same.startswith("CD_") is value.startswith("CD_")
    longer = _longer_placement_probe_value("_partName", value)
    assert longer.startswith(value) and len(longer) > len(value)
    assert _same_length_placement_probe_value("_partName", "character/model/a.pac") == ""
