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
