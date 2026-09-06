"""Owned recipe/output copies and bounded ItemInfo recipe-list updates."""
from dataclasses import replace
import struct

from cdmw.core.item_recipe_table import RecipeIngredient, RecipeGroupIngredient, encode_item_recipe
from cdmw.core.item_recipe_links import connected_recipe_keys
from cdmw.core.multichangeinfo_table import allocate_multichange_keys, find_multichange_keys
from cdmw.core.structured_binary_editor import append_table_rows, parse_pabgh_table
from cdmw.domain.new_item.authoring import RecipeOverride
from cdmw.domain.new_item.spec import EnhancementRows
from cdmw.services.new_item_acquisition_index import load_acquisition_index
from cdmw.services.new_item_recipe_outputs import own_recipe_outputs


def table_keys(payload, header):
    return {row.row_id for row in parse_pabgh_table(header, payload=payload).rows}


def replace_recipe_references(row, known_keys, selected, *, source_keys=None):
    old = find_multichange_keys(row, known_keys) if source_keys is None else source_keys
    if not old:
        if selected:
            raise ValueError("This template has no proven recipe-list boundary for new connections.")
        return row.raw
    needle = struct.pack("<I", len(old)) + struct.pack(f"<{len(old)}I", *old)
    stop = row.stat_block_offset if row.stat_block_offset is not None else len(row.raw)
    begin = row.prefix_end if source_keys is None else max(row.prefix_end, (row.item_type_offset or row.prefix_end) + 2)
    start = row.raw.find(needle, begin, stop)
    if start < 0 or row.raw.find(needle, start + 1, stop) >= 0:
        raise ValueError("The ItemInfo recipe-list boundary is ambiguous.")
    replacement = struct.pack("<I", len(selected)) + b"".join(struct.pack("<I", key) for key in selected)
    return row.raw[:start] + replacement + row.raw[start + len(needle):]


def plan_recipes(planner):
    spec, snapshot = planner.spec, planner.snapshot
    current = snapshot.sources and snapshot.sources.static_layout
    if spec.recipes is None and spec.enhancement is not EnhancementRows.OWN and not current:
        return None
    index = load_acquisition_index(snapshot, stop_event=planner.stop_event)
    listed = connected_recipe_keys(planner.template, snapshot.multichange_rows, index.recipes, index.rewards,
                                   related_keys=index.recipe_items.get(planner.template.key, ()))
    planner.recipe_source_keys = listed
    if spec.recipes == ():
        planner.manifest["recipes"] = []
        planner.summary.append("ItemInfo: clear the new item's recipe connections")
        return ()
    requested = spec.recipes or ()
    if len({choice.recipe_key for choice in requested}) != len(requested):
        raise ValueError("A recipe can be customized only once.")
    overrides = {choice.recipe_key: choice for choice in requested}
    # Unedited transitions still need owned item/output references. Keeping their
    # template keys makes the new item appear at its maximum refinement level.
    choices = tuple(overrides.pop(key, RecipeOverride(key)) for key in dict.fromkeys(listed))
    choices += tuple(overrides.values())
    recipe_pair, reward_pair = index.pairs["multichangeinfo"], index.pairs["dropsetinfo"]
    recipe_body, recipe_header = planner.table_data(recipe_pair)
    reward_body, reward_header = planner.table_data(reward_pair)
    recipe_keys = allocate_multichange_keys(table_keys(recipe_body, recipe_header), len(choices))
    used_rewards = table_keys(reward_body, reward_header)
    recipe_rows, reward_rows, mapping, manifests = [], [], {}, []
    for choice, new_key in zip(choices, recipe_keys):
        planner.check()
        source = index.recipes.get(choice.recipe_key)
        if source is None:
            detail = index.unsupported["multichangeinfo"].get(choice.recipe_key, "missing recipe")
            raise ValueError(f"Recipe {choice.recipe_key} cannot be authored: {detail}")
        tool = source.tool_key if choice.tool_key is None else choice.tool_key
        knowledge = source.knowledge_key if choice.knowledge_key is None else choice.knowledge_key
        if tool not in index.tools or (knowledge and knowledge not in index.knowledge):
            raise ValueError("A recipe tool or knowledge requirement is missing from the active tables.")
        ingredients, groups = source.ingredients, source.group_ingredients
        if choice.inputs is not None:
            ingredients, groups = [], []
            for entry in choice.inputs:
                if entry.quantity < 1 or not 0 <= entry.enhancement <= 65535 or entry.coupon_quantity < 0:
                    raise ValueError("Recipe quantities and enhancement levels are out of range.")
                key = int(spec.item_key) if entry.key == 0 and entry.kind == "item" else entry.key
                if entry.kind == "item" and key in (set(snapshot.rows) | {spec.item_key}):
                    ingredients.append(RecipeIngredient(key, quantity=entry.quantity, coupon_quantity=entry.coupon_quantity, enhancement=entry.enhancement))
                elif entry.kind == "group" and any(group.key == key for group in snapshot.item_groups):
                    groups.append(RecipeGroupIngredient(key, entry.quantity, entry.enhancement))
                else:
                    raise ValueError("A recipe input must name an existing item or item group.")
        else:
            # Enhancement consumes the new item; an initial crafting input that is a
            # different item remains that item (for example a base Kuku spear).
            ingredients = tuple(replace(value, item_key=int(spec.item_key)) if value.item_key == spec.template_key else value for value in ingredients)
        new_rewards, additional, outputs, output_manifest = own_recipe_outputs(
            planner, index, source, choice, new_key, used_rewards)
        reward_rows.extend(outputs)
        owned = replace(source, key=new_key, name=f"{spec.internal_name}_recipe_{new_key}", tool_key=tool,
                        knowledge_key=knowledge, ingredients=tuple(ingredients), group_ingredients=tuple(groups),
                        reward_keys=new_rewards, additional_reward_keys=additional)
        recipe_rows.append(encode_item_recipe(owned))
        mapping[source.key] = new_key
        manifests.append({"source_key": source.key, "key": new_key, "tool_key": tool, "knowledge_key": knowledge,
                          "reward_keys": new_rewards, "additional_reward_keys": additional, "outputs": output_manifest,
                          "elemental_status_keys": [value.key for value in source.elemental_statuses],
                          "inputs": [{"item_key": i.item_key, "quantity": i.quantity, "enhancement": i.enhancement} for i in ingredients],
                          "group_inputs": [{"group_key": i.group_key, "quantity": i.quantity, "enhancement": i.enhancement} for i in groups]})
    if recipe_rows:
        recipe_body, recipe_header = append_table_rows(recipe_body, recipe_header, recipe_rows)
        reward_body, reward_header = append_table_rows(reward_body, reward_header, reward_rows)
        for pair, body, header in ((recipe_pair, recipe_body, recipe_header), (reward_pair, reward_body, reward_header)):
            planner.patch(pair.payload_entry, body, f"{pair.payload_entry.path}: owned recipe dependencies")
            planner.patch(pair.header_entry, header, "Recipe dependency directory")
    planner.manifest["recipes"] = manifests
    planner.manifest["enhancement_rows"] = {str(old): new for old, new in mapping.items()}
    planner.summary.append(f"Recipes: {len(recipe_rows)} owned recipes and {len(reward_rows)} owned output records")
    return tuple(mapping.get(key, key) for key in listed) + tuple(new for old, new in mapping.items() if old not in listed)
