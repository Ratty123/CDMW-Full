"""Complete synthetic current recipe dependencies for the current-game fixture."""
import struct

from cdmw.core.item_recipe_table import ItemRecipe, RecipeIngredient, encode_item_recipe
from cdmw.core.item_reward_table import ItemReward, ItemRewardSet, encode_item_reward_set
from cdmw.core.item_use_reward import ItemUseReward, encode_item_use_reward
from tests.test_multichangeinfo_table import _table


def current_recipe_tables(template, keys):
    recipes, rewards = [], []
    for level, key in enumerate(keys):
        reward_key = 880000 + level
        recipe = ItemRecipe(key, f"Template_{level}", 28001, 3, (), 0, "", b"\1\0\1\1\0",
                            (RecipeIngredient(template, enhancement=level),), (),
                            b"\x0d\xd0\0\0\0" + bytes(8), bytes(38), (reward_key,))
        reward = ItemRewardSet(reward_key, f"Output_{level}", bytes(13),
            (ItemReward(template, 1000000, 0, 1, 1, level + 1),), bytes(10), 1000000, 0, "")
        recipes.append((key, encode_item_recipe(recipe)))
        rewards.append((reward_key, encode_item_reward_set(reward)))
    files = {}
    use = ItemUseReward(1000030, "UnusedGift", b"\2\1" + bytes(17), (), 880000, b"\0\x0e" + bytes(5))
    pairs = {"multichangeinfo": _table(recipes), "dropsetinfo": _table(rewards),
             "itemuseinfo": _table([(use.key, encode_item_use_reward(use))]),
             "knowledgeinfo": _table([(44, struct.pack("<II", 44, 9) + b"Knowledge")]),
             "crafttoolinfo": (struct.pack("<HI", 28001, 7) + b"Enchant", struct.pack("<HHI", 1, 28001, 0))}
    for stem, (body, header) in pairs.items():
        prefix = "gamedata/binarystaticinfo__/bin/" + stem
        files[prefix + ".staticinfobody"] = body
        files[prefix + ".staticinfoheader"] = header
    return files
