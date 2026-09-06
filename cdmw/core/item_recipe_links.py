"""Identify a current ItemInfo recipe list using decoded recipe relationships."""
import struct

from cdmw.core.new_item_record import RecordError


def recipe_item_connections(recipes, rewards, *, check=lambda: None):
    result = {}
    for key, recipe in recipes.items():
        check()
        items = {value.item_key for value in recipe.ingredients if value.item_key}
        items.update(entry.item_key for reward_key in recipe.reward_keys + recipe.additional_reward_keys
                     for entry in getattr(rewards.get(reward_key), "entries", ()))
        for item in items:
            result.setdefault(item, set()).add(key)
    return {key: frozenset(values) for key, values in result.items()}


def connected_recipe_keys(row, known_keys, recipes, rewards, *, related_keys=None):
    """Require one list after the item type that consumes or produces this item.

    ItemUse, group and other lists can contain integers that are also recipe
    keys. A longest-run search alone is not evidence of a recipe connection.
    Unknown transitions in an otherwise proven list are retained for preflight
    to reject; they are never silently dropped.
    """
    related = recipe_item_connections(recipes, rewards).get(row.key, ()) if related_keys is None else related_keys
    known = set(known_keys)
    start = max(row.prefix_end, (row.item_type_offset or row.prefix_end) + 2)
    stop = row.stat_block_offset if row.stat_block_offset is not None else len(row.raw)
    candidates = []
    for offset in range(start, stop - 7):
        count = struct.unpack_from("<I", row.raw, offset)[0]
        if not 1 <= count <= 64 or offset + 4 + count * 4 > stop:
            continue
        keys = struct.unpack_from(f"<{count}I", row.raw, offset + 4)
        if all(key in known for key in keys) and any(key in related for key in keys):
            candidates.append((offset, keys))
    if len(candidates) > 1:
        raise RecordError("The ItemInfo recipe-list boundary is ambiguous.")
    return candidates[0][1] if candidates else ()
