"""Own both recipe output lists without changing shared reward definitions."""
from dataclasses import replace

from cdmw.core.item_reward_table import encode_item_reward_set
from cdmw.core.multichangeinfo_table import allocate_multichange_keys


def own_recipe_outputs(planner, index, source, choice, new_key, used_keys):
    spec = planner.spec
    edits = {} if choice.outputs is None else {(v.reward_index, v.entry_index): v for v in choice.outputs}
    if choice.outputs is not None and len(edits) != len(choice.outputs):
        raise ValueError("A recipe output is selected more than once.")
    keys, rows, manifest, produced = [], [], [], False
    for reward_index, reward_key in enumerate(source.reward_keys + source.additional_reward_keys):
        planner.check()
        reward = index.rewards.get(reward_key)
        if reward is None:
            raise ValueError(f"Recipe output {reward_key} has an unsupported reward layout.")
        key = allocate_multichange_keys(used_keys, 1)[0]
        used_keys.add(key)
        products = []
        for entry_index, entry in enumerate(reward.entries):
            edit = edits.pop((reward_index, entry_index), None)
            if edit is not None:
                maximum = edit.quantity if edit.maximum is None else edit.maximum
                if not 1 <= edit.quantity <= maximum <= 0xffffffffffffffff or not -1 <= edit.enhancement <= 32767:
                    raise ValueError("Recipe output quantity or enhancement is out of range.")
                entry = replace(entry, item_key=int(spec.item_key), minimum=edit.quantity,
                                maximum=maximum, enhancement=edit.enhancement)
            elif choice.outputs is None and entry.item_key == spec.template_key:
                entry = replace(entry, item_key=int(spec.item_key))
            produced |= entry.item_key == spec.item_key
            products.append(entry)
            manifest.append({"item_key": entry.item_key, "minimum": entry.minimum, "maximum": entry.maximum,
                             "enhancement": entry.enhancement, "weight": entry.weight,
                             "sub_weight": entry.sub_weight, "conditions": entry.condition_references,
                             "reward_index": reward_index, "entry_index": entry_index,
                             "additional": reward_index >= len(source.reward_keys)})
        owned = reward.with_entries(products, key=key, name=f"{spec.internal_name}_recipe_{new_key}_{reward_index}")
        rows.append(encode_item_reward_set(owned))
        keys.append(key)
    if edits or not produced:
        raise ValueError("Select a supported recipe output that produces the new item.")
    boundary = len(source.reward_keys)
    return tuple(keys[:boundary]), tuple(keys[boundary:]), rows, manifest
