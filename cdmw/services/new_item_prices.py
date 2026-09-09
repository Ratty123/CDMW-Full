"""Remove embedded perk price contributions without changing shipped perks."""
from dataclasses import replace

from cdmw.core.iteminfo_row import clone_iteminfo_row, parse_iteminfo_row, rebuild_stat_block
from cdmw.domain.new_item.allocation import allocate_item_key, localization_keys


def own_zero_price_perks(row_bytes, snapshot, reserved_keys=()):
    """Return the equipment row and its distinct owned perk copies (source, clone)."""
    row = parse_iteminfo_row(row_bytes, item_keys=set(snapshot.rows))
    used = set(snapshot.rows) | set(reserved_keys) | {row.key}
    copies, mapped = [], {}
    for key in row.socket_items:
        if key in mapped:
            continue
        perk = snapshot.rows[key]
        if not any(p.price for p in perk.price_list) and not any(p.price for level in perk.enchant_levels for p in level.buy_prices):
            mapped[key] = key
            continue
        if perk.stat_block_offset is None:
            raise ValueError(f"Cannot remove the price contribution of undecoded perk {perk.string_key}.")
        clone_key = allocate_item_key(used)
        used.add(clone_key)
        name_key, desc_key = localization_keys(clone_key)
        raw = clone_iteminfo_row(perk, key=clone_key, string_key=f"CDMW_Perk_{row.key}_{key}",
                                 name_key=name_key, desc_key=desc_key if perk.desc_key else None)
        clone = parse_iteminfo_row(raw, item_keys=used)
        levels = tuple(replace(level, buy_prices=tuple(replace(p, price=0) for p in level.buy_prices)) for level in clone.enchant_levels)
        raw = rebuild_stat_block(clone, levels=levels, price_list=tuple(replace(p, price=0) for p in clone.price_list))
        clone = parse_iteminfo_row(raw, item_keys=used)
        copies.append((perk, clone))
        mapped[key] = clone_key
    sockets = tuple(mapped[key] for key in row.socket_items)
    return rebuild_stat_block(row, socket_items=sockets) if copies else row_bytes, tuple(copies)
