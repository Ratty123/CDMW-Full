"""Aggregate selected shop operations before writing StoreInfo once."""
from dataclasses import replace
from cdmw.core.storeinfo_table import (
    apply_store_row, encode_store_row, insert_stock_entry, swap_stock_item,
)
from cdmw.domain.new_item.spec import PlacementKind, UNLIMITED_STOCK


def plan_shops(spec, snapshot, payload, header):
    placements = (spec.placement,) if spec.shop_placements is None else spec.shop_placements
    stores = {store.name: store for store in snapshot.stores}
    changed, summaries, warnings, manifests = {}, [], [], []
    selected = set()
    for placement in placements:
        if placement.kind is PlacementKind.NONE:
            continue
        identity = (placement.store_name, placement.kind, placement.stock_index if placement.stock_index is not None else placement.old_item_name)
        if identity in selected:
            raise ValueError("The same shop operation is selected more than once.")
        selected.add(identity)
        if placement.store_name not in stores:
            raise ValueError(f"There is no store named {placement.store_name}")
        store = changed.get(placement.store_name, stores[placement.store_name])
        if placement.kind is PlacementKind.SWAP:
            old_key = snapshot.keys_by_name.get(placement.old_item_name)
            if old_key is None:
                raise ValueError(f"there is no item named {placement.old_item_name}")
            source = None
            if placement.stock_index is not None:
                source = next((entry for entry in store.entries if entry.stock_index == placement.stock_index), None)
                if source is None or source.item_key != old_key:
                    raise ValueError("The selected shop entry no longer matches the reviewed item.")
                moved = source.with_item(spec.item_key)
                if not placement.keep_requirement:
                    moved = moved.without_requirement()
                if placement.stock_count is not None:
                    moved = moved.with_count(placement.stock_count)
                updated = replace(store, entries=tuple(moved if entry is source else entry for entry in store.entries))
                updated = replace(updated, raw=encode_store_row(updated))
            else:
                updated = swap_stock_item(store, old_key, int(spec.item_key), keep_requirement=placement.keep_requirement, count=placement.stock_count)
                source = next(iter(store.entries_for(old_key)), None)
            what = f"StoreInfo: {store.name} sells {spec.internal_name} instead of {placement.old_item_name}"
        else:
            source = store.buyable_entries[-1] if store.buyable_entries else None
            updated = insert_stock_entry(store, int(spec.item_key), keep_requirement=placement.keep_requirement, count=placement.stock_count)
            what = f"StoreInfo: {store.name} gains a stock entry for {spec.internal_name}"
        required = source.requirement_item_key if source else None
        if required is not None:
            unlock = snapshot.rows.get(required)
            name = unlock.string_key if unlock is not None else str(required)
            if placement.keep_requirement:
                warnings.append(f"The shop line keeps its unlock requirement: the buyer needs the knowledge of {name} before it sells (the shop shows \"Knowledge\" until then).")
            else:
                what += f" (its unlock requirement, the knowledge of {name}, dropped so it sells freely)"
        if placement.stock_count is not None:
            what += " (unlimited stock)" if placement.stock_count == UNLIMITED_STOCK else f" ({placement.stock_count} in stock)"
        if placement.price is not None:
            warnings.append("StoreInfo entries carry no price of their own; the shop prices the item from its buy-price list, so the placement price was not written. Use a buy-price edit.")
        changed[store.name] = updated
        summaries.append(what)
        manifests.append({"name": store.name, "kind": placement.kind.value, "old_item": placement.old_item_name or None,
                          "stock_index": placement.stock_index, "requirement_kept": bool(placement.keep_requirement),
                          "stock_count": placement.stock_count})
    for store in changed.values():
        payload, header = apply_store_row(payload, header, store)
    return payload, header, summaries, warnings, manifests
