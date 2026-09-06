"""Bounded current recipe/reward shapes, using synthetic records only."""
from dataclasses import replace
from types import SimpleNamespace
import struct

import pytest

from cdmw.core.item_recipe_table import RecipeElementalStatus, parse_item_recipe, encode_item_recipe
from cdmw.core.item_recipe_links import connected_recipe_keys
from cdmw.core.item_reward_table import parse_item_reward_set, encode_item_reward_set
from cdmw.core.new_item_record import text_bytes
from cdmw.modding.mesh_parser import pac_bone_palette_candidates, resolve_pac_bone_palette
from tests.test_new_item_acquisition_authoring import recipe_row, reward_row


def test_recipe_status_list_and_variable_presentation_preserve_all_references():
    source = recipe_row()
    label = b"\x0d\xd0\0\4\0" + struct.pack("<I", 17) + text_bytes("status label")
    complete = b"\x0d\xd2\0\0\0" + struct.pack("<I", 81) + text_bytes("Refinement result")
    source = replace(source, elemental_statuses=(RecipeElementalStatus(12345, label),),
                     presentation=bytes(13) + struct.pack("<III", 321, 654, 987) + complete)
    raw = encode_item_recipe(source)
    parsed = parse_item_recipe(raw)
    assert parsed == source
    assert encode_item_recipe(parsed) == raw
    changed = replace(parsed, knowledge_key=0, ingredients=(replace(parsed.ingredients[0], quantity=7),))
    edited = parse_item_recipe(encode_item_recipe(changed))
    assert edited.ingredients[0].quantity == 7 and edited.knowledge_key == 0
    assert edited.elemental_statuses == source.elemental_statuses
    assert edited.description == source.description and edited.presentation == source.presentation
    for broken in (raw[:-1], raw + b"\0", raw.replace(b"status label", b"\xfftatus label")):
        with pytest.raises(ValueError):
            parse_item_recipe(broken)


def test_conditional_item_reward_edit_retains_reference_scopes_and_raw_weights():
    source = reward_row()
    entry = replace(source.entries[0], condition_references=(1000571, 1000567, 99881, 1000580), sub_weight=71)
    source = replace(source, entries=(entry,), original_string="")
    raw = encode_item_reward_set(source)
    assert encode_item_reward_set(parse_item_reward_set(raw)) == raw
    edited = source.with_entries((replace(entry, item_key=8888, minimum=3, maximum=8),), key=99)
    reread = parse_item_reward_set(encode_item_reward_set(edited))
    assert reread.entries[0].condition_references == entry.condition_references
    assert reread.entries[0].sub_weight == 71
    assert (reread.entries[0].item_key, reread.entries[0].minimum, reread.entries[0].maximum) == (8888, 3, 8)
    assert reread.original_string == ""
    with pytest.raises(ValueError, match="source expressions"):
        replace(source, original_string="unknown conditional expression").with_entries((entry,))


def palette_pac():
    data = bytearray(80 + 8000 + 1000)
    data[:4] = b"PAR "
    struct.pack_into("<II", data, 0x10, 0, 8000)
    struct.pack_into("<II", data, 0x18, 0, 1000)
    hashes = tuple(0xAABB1000 + i * 137 for i in range(20))
    struct.pack_into("<H12I", data, 6000, 12, *hashes[:12])
    # A longer sequence in geometry must not be mistaken for a metadata palette.
    struct.pack_into("<H20I", data, 8200, 20, *hashes)
    return bytes(data), hashes


def test_skin_palette_uses_complete_metadata_and_excludes_geometry():
    raw, hashes = palette_pac()
    skeleton = SimpleNamespace(bones=tuple(SimpleNamespace(name_hash=h) for h in hashes))
    assert resolve_pac_bone_palette(raw, skeleton) == tuple(range(12))
    assert not pac_bone_palette_candidates(raw, search_limit=4096)
    wrong_rig = SimpleNamespace(bones=tuple(SimpleNamespace(name_hash=h + 1) for h in hashes))
    assert resolve_pac_bone_palette(raw, wrong_rig) == ()


def test_skin_palette_must_end_inside_declared_metadata():
    raw, hashes = palette_pac()
    data = bytearray(raw)
    data[6000:6050] = bytes(50)
    struct.pack_into("<H20I", data, 8060, 20, *hashes)
    skeleton = SimpleNamespace(bones=tuple(SimpleNamespace(name_hash=h) for h in hashes))
    assert resolve_pac_bone_palette(bytes(data), skeleton) == ()


def test_recipe_list_does_not_confuse_other_lists_with_recipe_connections():
    raw = bytearray(200)
    struct.pack_into("<4I", raw, 24, 3, 1013165, 91, 92)
    struct.pack_into("<2I", raw, 120, 1, 1013165)
    row = SimpleNamespace(key=recipe_row().ingredients[0].item_key, raw=bytes(raw), prefix_end=20,
                          item_type_offset=90, stat_block_offset=160)
    known = {1013165, 91, 92}
    recipes, rewards = {1013165: recipe_row()}, {1009835: reward_row()}
    assert connected_recipe_keys(row, known, recipes, rewards) == (1013165,)
    struct.pack_into("<2I", raw, 140, 1, 1013165)
    row.raw = bytes(raw)
    with pytest.raises(ValueError, match="ambiguous"):
        connected_recipe_keys(row, known, recipes, rewards)
