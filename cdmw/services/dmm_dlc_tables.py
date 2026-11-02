"""Fold CDMW's shop and item-group additions from the DLC's table copies into the base tables.

DMM merges a mod's tables into the game record by record. It ignores a mod's copy of a
DLC table (`storeinfo.dlc_01` and the like) and carries shop and group changes made to
the base tables into the DLC's replacement rows itself. CDMW plans a new item's shop
line in the copy the game reads, which for the shops the DLC replaces is the DLC's, so
before a mod goes to DMM those additions move to the same rows of the base tables.

Only additions move: new stock lines and new group members. Anything else in a DLC
copy, or a row only the DLC has, cannot be expressed for DMM and is refused.
"""
from __future__ import annotations

import re
from typing import Callable, Mapping, Optional

from cdmw.core.itemgroupinfo_table import add_group_members, apply_item_group_row, parse_item_group_table
from cdmw.core.storeinfo_table import apply_store_row, insert_stock_entry, parse_store_table

_DLC_TABLE = re.compile(r"^(?P<dir>.*/)?(?P<name>storeinfo|itemgroupinfo)\.(?P<dlc>dlc_\d+)\.(?P<kind>staticinfobody|pabgb)$")
_HEADER = {"staticinfobody": "staticinfoheader", "pabgb": "pabgh"}
#: Any layer of the shop and item group tables, body or header.
_SHOP_OR_GROUP_TABLE = re.compile(
    r"^gamedata/binarystaticinfo__/bin/(storeinfo|itemgroupinfo)(\.dlc_\d+)?\.(staticinfobody|staticinfoheader|pabgb|pabgh)$")


class DmmTableError(ValueError):
    """A DLC table change that DMM cannot be given."""


def _stores(payload: bytes, header: bytes):
    error = None
    for layout in ("current", "legacy"):
        try:
            return {row.key: row for row in parse_store_table(payload, header, layout=layout)}
        except ValueError as exc:  # The layout that round-trips is the table's.
            error = exc
    raise DmmTableError(f"StoreInfo could not be read: {error}")


def _groups(payload: bytes, header: bytes):
    return {row.key: row for row in parse_item_group_table(payload, header)}


def _store_additions(name, original, changed):
    if original is None:
        raise DmmTableError(f"Shop {changed.name!r} exists only in the DLC's table, which DMM does not take from mods.")
    added = [entry for entry in changed.entries if not original.entries_for(entry.item_key)]
    kept = [entry.item_key for entry in changed.entries if original.entries_for(entry.item_key)]
    if kept != [entry.item_key for entry in original.entries] or len(added) + len(kept) != len(changed.entries):
        raise DmmTableError(f"Shop {changed.name!r} changes more than added stock lines in the DLC's copy; DMM cannot take that.")
    return added


def _group_additions(original, changed):
    if original is None:
        raise DmmTableError(f"Item group {changed.name!r} exists only in the DLC's table, which DMM does not take from mods.")
    added = [key for key in changed.members if key not in original.members]
    if [key for key in changed.members if key in original.members] != list(original.members):
        raise DmmTableError(f"Item group {changed.name!r} changes more than added members in the DLC's copy; DMM cannot take that.")
    return added


_KINDS = (("staticinfobody", "staticinfoheader"), ("pabgb", "pabgh"))
_BIN = "gamedata/binarystaticinfo__/bin/"


def field_operations(files: Mapping[str, bytes], read_game: Callable[[str], Optional[bytes]], owned_items):
    """Shop and group additions in the base tables as DMM V3 operations; those tables leave `files`.

    DMM turns a changed table row into a whole-row edit and carries it into the DLC's copy
    of that row, which drops what the DLC adds there. An append operation adds
    CDMW's items to the base and DLC rows alike and leaves everything else in place.
    """
    from dataclasses import replace

    from cdmw.core.dmm_item_fields import stock_value
    from cdmw.core.storeinfo_table import encode_stock_entry

    def stock(row, original):
        added = _store_additions("storeinfo", original, row)
        return [dict(op="array_append", key=row.key, field="stock_data_list",
                     new=stock_value(encode_stock_entry(replace(entry, stock_index=len(original.entries) + index))))
                for index, entry in enumerate(added)], [entry.item_key for entry in added]

    def group(row, original):
        added = _group_additions(original, row)
        # DMM has no union operation; CDMW's new item keys are in no group yet, so appending each is the same.
        return [dict(op="array_append", key=row.key, field="item_info_list", new=key) for key in added], added

    result, targets = dict(files), []
    owned = {int(key) for key in owned_items}
    for name, read, lower in (("storeinfo", _stores, stock), ("itemgroupinfo", _groups, group)):
        for body_kind, header_kind in _KINDS:
            body, header = f"{_BIN}{name}.{body_kind}", f"{_BIN}{name}.{header_kind}"
            if body not in files:
                continue
            game_header = read_game(header)
            before = read(read_game(body), game_header)
            after = read(files[body], files.get(header, game_header))
            if set(after) != set(before):
                raise DmmTableError(f"{name} gains or loses rows; DMM operations can only add to existing ones.")
            intents = []
            for key, row in after.items():
                if row.raw == before[key].raw:
                    continue
                operations, items = lower(row, before[key])
                if not set(items) <= owned:
                    raise DmmTableError(f"{row.name!r} gains items that are not this mod's own; DMM cannot take that.")
                intents += operations
            result.pop(body, None)
            result.pop(header, None)
            if intents:
                targets.append(dict(file=f"{name}.pabgb", intents=intents))
    return result, targets


def fold_dlc_additions(files: Mapping[str, bytes], read_game: Callable[[str], Optional[bytes]], *,
                       on_log: Optional[Callable[[str], None]] = None) -> dict[str, bytes]:
    """`files` with DLC shop and group copies replaced by the same additions in the base tables."""
    result = dict(files)
    moved = {"storeinfo": 0, "itemgroupinfo": 0}
    for path in sorted(files):
        match = _DLC_TABLE.match(path)
        if not match:
            continue
        name, kind, folder = match["name"], match["kind"], match["dir"] or ""
        header_path = f"{folder}{name}.{match['dlc']}.{_HEADER[kind]}"
        base_path, base_header_path = f"{folder}{name}.{kind}", f"{folder}{name}.{_HEADER[kind]}"
        dlc_before = (read_game(path), read_game(header_path))
        dlc_after = (files[path], files.get(header_path, dlc_before[1]))
        base = (result.get(base_path, read_game(base_path)), result.get(base_header_path, read_game(base_header_path)))
        if None in dlc_before or None in dlc_after or None in base:
            raise DmmTableError(f"The game has no complete base and DLC copy of {name}.")
        read = _stores if name == "storeinfo" else _groups
        before, after, base_rows = read(*dlc_before), read(*dlc_after), read(*base)
        payload, header = base
        for key, row in after.items():
            if before.get(key) is not None and row.raw == before[key].raw:
                continue
            target = base_rows.get(key)
            if target is None:
                raise DmmTableError(f"{'Shop' if name == 'storeinfo' else 'Item group'} {row.name!r} exists only in the DLC, "
                                    "and DMM does not take a mod's copy of a DLC table.")
            if name == "storeinfo":
                for entry in _store_additions(name, before.get(key), row):
                    target = insert_stock_entry(target, entry.item_key, template=entry, count=entry.count)
                    moved[name] += 1
                payload, header = apply_store_row(payload, header, target)
            else:
                added = _group_additions(before.get(key), row)
                target = add_group_members(target, added)
                moved[name] += len(added)
                payload, header = apply_item_group_row(payload, header, target)
        result[base_path], result[base_header_path] = payload, header
        result.pop(path, None)
        result.pop(header_path, None)
    if on_log and any(moved.values()):
        on_log(f"Moved {moved['storeinfo']} shop line(s) and {moved['itemgroupinfo']} item group member(s) from the DLC's "
               "copies into the base tables, where DMM takes them and carries them into the DLC's shops and groups.")
    return result


def _plan_item_keys(manifest) -> set[int]:
    """Every item a new-item plan adds: the item, its price perks and the items it carries forward."""
    keys = set()

    def collect(value):
        if isinstance(value, dict):
            if isinstance(value.get("item_key"), int):
                keys.add(value["item_key"])
            for nested in value.values():
                if isinstance(nested, (dict, list, tuple)):
                    collect(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                if isinstance(nested, int) and not isinstance(nested, bool):
                    keys.add(nested)  # `mounted_base.items` may list bare keys
                else:
                    collect(nested)

    collect(manifest.get("iteminfo"))
    collect(manifest.get("owned_price_perks"))
    collect(manifest.get("previous_items"))
    collect((manifest.get("mounted_base") or {}).get("items"))
    return keys


def plan_for_dmm(plan, read_game: Callable[[str], Optional[bytes]], *,
                 on_log: Optional[Callable[[str], None]] = None):
    """A new-item plan without shop and group tables, and those additions as DMM operations.

    The tables leave the plan: the DLC's copies fold into the base rows and the base
    rows become append and union operations, so DMM adds the item to the base and the
    DLC's shops and groups alike instead of replacing either.
    """
    from dataclasses import replace

    tables = {path: data for path, data in plan.loose_files.items() if _SHOP_OR_GROUP_TABLE.match(path)}
    if not tables:
        return plan, []
    folded = fold_dlc_additions(tables, read_game, on_log=on_log)
    kept, targets = field_operations(folded, read_game, _plan_item_keys(plan.manifest))
    if kept:
        raise DmmTableError("The shop and item group tables could not all become DMM operations: "
                            + ", ".join(sorted(kept)) + ".")
    dropped = set(tables)
    return replace(
        plan,
        patches=tuple(request for request in plan.patches if request.entry.path not in dropped),
        additions=tuple(item for item in plan.additions if item.path not in dropped),
        loose_files={path: data for path, data in plan.loose_files.items() if path not in dropped},
    ), targets
