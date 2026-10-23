"""Classification changes must keep recipe searches after the u16 category."""
import struct
from types import SimpleNamespace

from cdmw.core.item_recipe_links import connected_recipe_keys
from cdmw.core.iteminfo_row import parse_iteminfo_row
from cdmw.services.new_item_recipes import replace_recipe_references
from tests.test_iteminfo_row import build_row


def test_recipe_discovery_and_rebinding_ignore_a_list_before_the_category():
    # The description's one-byte text and the empty secondary record encode a
    # decoy {count=1, key=65}. It precedes the category and is not a recipe list.
    original = build_row(desc_key='A', item_type_code=56)
    parsed = parse_iteminfo_row(original)
    needle = struct.pack('<II', 1, 65)
    raw = original[:parsed.stat_block_offset] + needle + original[parsed.stat_block_offset:]
    row = parse_iteminfo_row(raw)
    assert raw.find(needle, row.item_type_offset + 1) < row.category_info_offset
    recipes = {65: SimpleNamespace(ingredients=(SimpleNamespace(item_key=row.key),),
                                   reward_keys=(), additional_reward_keys=())}
    assert connected_recipe_keys(row, recipes, recipes, {}) == (65,)
    changed = replace_recipe_references(row, recipes, (66,), source_keys=(65,))
    assert changed == original[:parsed.stat_block_offset] + struct.pack('<II', 1, 66) + original[parsed.stat_block_offset:]
    assert parse_iteminfo_row(changed).desc_key == 'A'
