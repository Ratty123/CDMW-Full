"""Clone a reward and item-use record, then reconnect only selected consumers."""
from dataclasses import replace
from cdmw.core.item_reward_table import encode_item_reward_set
from cdmw.core.item_use_reward import encode_item_use_reward, replace_item_use_reference
from cdmw.core.iteminfo_row import parse_iteminfo_row
from cdmw.core.multichangeinfo_table import allocate_multichange_keys
from cdmw.core.structured_binary_editor import append_table_rows, replace_table_row
from cdmw.services.new_item_acquisition_index import load_acquisition_index
from cdmw.services.new_item_recipes import table_keys


def plan_reward_acquisition(planner):
    choices = planner.spec.reward_acquisitions
    if not choices:
        return
    snapshot, spec = planner.snapshot, planner.spec
    index = load_acquisition_index(snapshot, stop_event=planner.stop_event)
    selected, identities = {}, set()
    for choice in choices:
        identity = (choice.consumer_item_key, choice.use_index, choice.entry_index)
        if identity in identities or choice.mode not in ("insert", "swap"):
            raise ValueError("Reward routes must identify distinct supported operations.")
        identities.add(identity)
        selected.setdefault(identity[:2], []).append(choice)
    use_pair, reward_pair = index.pairs["itemuseinfo"], index.pairs["dropsetinfo"]
    use_body, use_header = planner.table_data(use_pair)
    reward_body, reward_header = planner.table_data(reward_pair)
    item_body, item_header = planner.table_data(snapshot.iteminfo)
    use_keys, reward_keys = table_keys(use_body, use_header), table_keys(reward_body, reward_header)
    use_rows, reward_rows, changed_items, manifests = [], [], {}, []
    for identity, edits in selected.items():
        planner.check()
        consumer = next((value for value in index.consumers if value[:2] == identity), None)
        if consumer is None:
            raise ValueError("The selected item-producing reward consumer is unsupported or missing.")
        item_key, use_index, source_use_key, source_reward_key = consumer
        source_use, source_reward = index.uses[source_use_key], index.rewards[source_reward_key]
        products = list(source_reward.entries)
        for edit in edits:
            if not 0 <= edit.entry_index < len(source_reward.entries) or not 1 <= edit.minimum <= edit.maximum or not -1 <= edit.enhancement <= 32767:
                raise ValueError("Reward entry, quantity or enhancement is out of range.")
            old = source_reward.entries[edit.entry_index]
            weight = old.weight if edit.weight is None else edit.weight
            if not 0 <= weight <= 0xffffffffffffffff:
                raise ValueError("Reward weight must fit the stored unsigned value.")
            product = replace(old, item_key=int(spec.item_key), minimum=edit.minimum, maximum=edit.maximum,
                              enhancement=edit.enhancement, weight=weight)
            if edit.mode == "swap":
                products[edit.entry_index] = product
            else:
                products.append(product)
        reward_key = allocate_multichange_keys(reward_keys, 1)[0]
        reward_keys.add(reward_key)
        use_key = allocate_multichange_keys(use_keys, 1)[0]
        use_keys.add(use_key)
        owned_reward = source_reward.with_entries(products, key=reward_key, name=f"{spec.internal_name}_reward_{reward_key}")
        owned_use = replace(source_use, key=use_key, name=f"{spec.internal_name}_use_{use_key}", reward_key=reward_key)
        reward_rows.append(encode_item_reward_set(owned_reward))
        use_rows.append(encode_item_use_reward(owned_use))
        item = changed_items.get(item_key, snapshot.rows[item_key])
        raw = replace_item_use_reference(item, use_keys, use_index, source_use_key, use_key)
        changed_items[item_key] = parse_iteminfo_row(raw, item_keys=set(snapshot.rows))
        manifests.append({"consumer_item_key": item_key, "consumer_name": item.string_key, "use_index": use_index,
                          "source_use_key": source_use_key, "use_key": use_key, "source_reward_key": source_reward_key,
                          "reward_key": reward_key, "operations": [{"mode": edit.mode, "entry_index": edit.entry_index,
                          "minimum": edit.minimum, "maximum": edit.maximum, "enhancement": edit.enhancement,
                          "weight": source_reward.entries[edit.entry_index].weight if edit.weight is None else edit.weight,
                          "sub_weight": source_reward.entries[edit.entry_index].sub_weight,
                          "conditions": source_reward.entries[edit.entry_index].condition_references} for edit in edits],
                          "use_conditions": [value.hex() for value in source_use.conditions]})
    use_body, use_header = append_table_rows(use_body, use_header, use_rows)
    reward_body, reward_header = append_table_rows(reward_body, reward_header, reward_rows)
    for item in changed_items.values():
        item_body, item_header = replace_table_row(item_body, item_header, item.key, item.raw)
    for pair, body, header in ((use_pair, use_body, use_header), (reward_pair, reward_body, reward_header),
                               (snapshot.iteminfo, item_body, item_header)):
        planner.patch(pair.payload_entry, body, f"{pair.payload_entry.path}: selected reward routes")
        planner.patch(pair.header_entry, header, "Reward route directory")
    planner.manifest["reward_acquisitions"] = manifests
    planner.summary.append(f"Rewards: {len(manifests)} selected consumers; shared definitions preserved")
