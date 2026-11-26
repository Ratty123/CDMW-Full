"""Read CDMW's own DMM operations back into the tables of an Add to existing mod base.

A DMM export of new items does not carry the part, shop and item group tables. Their
additions are operations in ``CDMW items - shops and groups.json`` instead (see
:mod:`cdmw.services.dmm_dlc_tables` and :mod:`cdmw.services.dmm_part_table`), because
DMM merges those into the game's rows. A mod base built only from the folder's files
therefore has the earlier items' rows but not their parts, shop lines or groups, and the
next item planned on it cannot use them.

This module applies those operations to the game's tables, giving the tables DMM itself
would build, so the base looks like the same mod in the CDUMM layout. Only the exact
shapes CDMW writes are accepted, and only for CDMW's own new items; anything else in
the file is refused rather than guessed at.

A shop line or group member goes into the copy of the row the game reads: the DLC's
copy when the DLC replaces that row, else the base table. That is where a plan puts a
new item's own additions too, so the DMM export of the next item folds both the same
way and restates the earlier operations unchanged.
"""
from __future__ import annotations

import json
import struct
from dataclasses import replace
from pathlib import Path
from typing import Dict, Mapping, Optional

from cdmw.services.dmm_part_table import PART_TABLE

#: The operations file a DMM export writes beside its archive (also in `dmm_send`).
OPERATIONS_FILE = "CDMW items - shops and groups.json"
_MAX_BYTES = 8 * 1024 * 1024
_ROW_TABLES = {"storeinfo.pabgb": ("storeinfo", "stock_data_list"),
               "itemgroupinfo.pabgb": ("itemgroupinfo", "item_info_list")}
_PART_VALUE = {"key_a", "key_b", "key_c", "bool_flag", "asset_id", "flag", "children"}


class DmmOperationsError(ValueError):
    """The mod's operations file holds something CDMW did not write."""


def _normalize(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/").lower()


def read_operations(folder: Path):
    """The targets of the folder's operations file, or None when it has none."""
    path = Path(folder) / OPERATIONS_FILE
    if not path.is_file():
        return None
    if path.is_symlink() or path.stat().st_size > _MAX_BYTES:
        raise DmmOperationsError(f"The mod's {OPERATIONS_FILE} is a link or too large to read.")
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise DmmOperationsError(f"The mod's {OPERATIONS_FILE} cannot be read: {exc}") from exc
    targets = document.get("targets") if isinstance(document, dict) else None
    if not isinstance(document, dict) or document.get("format") != 3 or not isinstance(targets, list):
        raise DmmOperationsError(f"The mod's {OPERATIONS_FILE} is not a DMM V3 operations file written by CDMW.")
    for target in targets:
        if (not isinstance(target, dict) or set(target) != {"file", "intents"}
                or not isinstance(target["intents"], list)):
            raise DmmOperationsError(f"The mod's {OPERATIONS_FILE} has a target CDMW does not write.")
        if target["file"] not in _ROW_TABLES and target["file"] != PART_TABLE:
            raise DmmOperationsError(f"The mod's {OPERATIONS_FILE} changes {target['file']!r}, which CDMW does not write.")
    return targets


def _int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _own_item(snapshot, item, where):
    if not _int(item) or item in snapshot.rows:
        raise DmmOperationsError(
            f"{where} adds item {item!r}, which is not one of the mod's own new items. "
            f"CDMW only reads back the {OPERATIONS_FILE} it wrote itself.")


def fold_operations(snapshot, payloads: Mapping[str, object], targets, *, stop_event=None) -> Dict[str, bytes]:
    """`{game path: table bytes}` for the tables the operations change, applied to the game's.

    `payloads` is the folder's own files (path -> object with `read_bytes()`): a table the
    folder carries is the starting point instead of the game's, and an added part's prefab
    must be one of them.
    """
    from cdmw.domain.cancellation import raise_if_cancelled

    tables: Dict[str, bytes] = {}

    def current(path, fallback):
        path = _normalize(path)
        if path in tables:
            return tables[path]
        if path in payloads:
            return payloads[path].read_bytes()
        return fallback() if callable(fallback) else fallback

    parts = []
    for target in targets:
        if target["file"] == PART_TABLE:
            parts += target["intents"]
            continue
        name, field = _ROW_TABLES[target["file"]]
        for intent in target["intents"]:
            raise_if_cancelled(stop_event, "New item plan cancelled.")
            if (not isinstance(intent, dict) or set(intent) != {"op", "key", "field", "new"}
                    or intent["op"] != "array_append" or intent["field"] != field or not _int(intent["key"])):
                raise DmmOperationsError(f"The mod's {OPERATIONS_FILE} has a {name} operation CDMW does not write.")
            pair = snapshot.row_sources.get(name, {}).get(intent["key"])
            if pair is None:
                raise DmmOperationsError(f"The mod's {OPERATIONS_FILE} adds to {name} row {intent['key']}, "
                                         "which this game does not have.")
            body_path, header_path = _normalize(pair.payload_entry.path), _normalize(pair.header_entry.path)
            payload, header = current(body_path, pair.payload), current(header_path, pair.header)
            apply = _append_stock if name == "storeinfo" else _append_member
            tables[body_path], tables[header_path] = apply(snapshot, payload, header, intent)
    if parts:
        tables[_normalize(PART_TABLE)] = _append_parts(
            snapshot, payloads, current(PART_TABLE, lambda: snapshot.payload(PART_TABLE)), parts)
    return tables


def _row(payload, header, key):
    from cdmw.core.structured_binary_editor import parse_pabgh_table

    table = parse_pabgh_table(header, payload=payload)
    for row, start, end in table.row_spans(len(payload)):
        if row.row_id == key:
            return table, row, payload[start:end]
    raise DmmOperationsError(f"Row {key} is missing from the table.")


def _append_stock(snapshot, payload, header, intent):
    from cdmw.core.compact_static import read_compact_layout
    from cdmw.core.dmm_item_fields import stock_bytes
    from cdmw.core.item_layout import replace_layout_fields
    from cdmw.core.new_item_record import RecordError
    from cdmw.core.storeinfo_compact import parse_compact_store
    from cdmw.core.storeinfo_table import (StoreInfoError, _parse_entry, apply_store_row, encode_stock_entry,
                                           encode_store_row, parse_store_row)

    key, value = intent["key"], intent["new"]
    table, directory_row, raw = _row(payload, header, key)
    try:
        entry = stock_bytes(value)
        item = value["value"]["raw_q"]
        if table.key_layout in ("named", "indexed"):
            row = parse_compact_store(raw, key, name=directory_row.string_key, key_layout=table.key_layout)
        else:
            row = parse_store_row(raw, key=key, layout="current")
        _own_item(snapshot, item, f"Shop {row.name!r}")
        if value["lookup_a"] != key:
            raise DmmOperationsError(f"A stock line for shop {row.name!r} names another shop.")
        if row.entries_for(item):
            raise DmmOperationsError(f"Shop {row.name!r} already stocks item {item}.")
        if table.key_layout in ("named", "indexed"):
            layout = read_compact_layout(raw, "storeinfo", key_layout=table.key_layout)
            stock = layout.data("_stockDataList")
            grown = struct.pack("<I", struct.unpack_from("<I", stock)[0] + 1) + stock[4:] + entry
            row = parse_compact_store(
                replace_layout_fields(layout, {"_stockDataList": grown}).raw,
                key,
                name=directory_row.string_key,
                key_layout=table.key_layout,
            )
        else:
            added = _parse_entry(entry, 0, len(entry), 8)
            if encode_stock_entry(added) != entry or added.item_key != item:
                raise DmmOperationsError(f"A stock line for shop {row.name!r} cannot be read back.")
            row = replace(row, entries=row.entries + (added,))
    except (RecordError, StoreInfoError, struct.error) as exc:
        raise DmmOperationsError(f"A shop operation cannot be read back: {exc}") from exc
    # The head counts follow the flags, and stock_index follows position in this copy of the store.
    entries = row.entries[:-1] + (replace(row.entries[-1], stock_index=len(row.entries) - 1),)
    counted = replace(row, entries=entries,
                      buyable_count=sum(1 for e in entries if e.is_buyable),
                      sellable_count=sum(1 for e in entries if e.is_sellable))
    return apply_store_row(payload, header, replace(counted, raw=encode_store_row(counted)))


def _append_member(snapshot, payload, header, intent):
    from cdmw.core.itemgroupinfo_table import add_group_members, apply_item_group_row, parse_item_group_row

    key, item = intent["key"], intent["new"]
    table, directory_row, raw = _row(payload, header, key)
    row = parse_item_group_row(raw, key=key, name=directory_row.string_key, key_layout=table.key_layout)
    _own_item(snapshot, item, f"Item group {row.name!r}")
    if item in row.members:
        raise DmmOperationsError(f"Item group {row.name!r} already lists item {item}.")
    return apply_item_group_row(payload, header, add_group_members(row, [item]))


def _append_parts(snapshot, payloads, data, intents):
    from cdmw.core.pappt_format import (PapptFormatError, PartPrefabPart, PartPrefabRecord, encode_pappt,
                                        insert_part_prefabs, parse_pappt)

    records = []
    for intent in intents:
        new = intent.get("new") if isinstance(intent, dict) else None
        if (not isinstance(intent, dict) or set(intent) != {"op", "key", "field", "new"} or intent["op"] != "list_append"
                or intent["key"] != 0 or intent["field"] != "primary" or not isinstance(new, dict)
                or set(new) != _PART_VALUE or new["bool_flag"] != 1 or not isinstance(new["children"], list)):
            raise DmmOperationsError(f"The mod's {OPERATIONS_FILE} has a part operation CDMW does not write.")
        try:
            record = PartPrefabRecord(
                stem=str(new["key_a"]), folder=str(new["key_b"]), sockets_path=str(new["key_c"]),
                extra=str(new["asset_id"]), flag=int(new["flag"]),
                parts=tuple(PartPrefabPart(name=str(child["sub_key"]), flag=int(child["sub_flag"]))
                            for child in new["children"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise DmmOperationsError(f"A part operation cannot be read back: {exc}") from exc
        # The same witness the export requires: the part belongs to a prefab this mod carries.
        if _normalize(record.prefab_path) not in payloads:
            raise DmmOperationsError(f"Part {record.stem!r} has no prefab in this mod; "
                                     "refusing to register another mod's part.")
        records.append(record)
    try:
        return encode_pappt(insert_part_prefabs(parse_pappt(data, name=PART_TABLE), records))
    except PapptFormatError as exc:
        raise DmmOperationsError(f"The mod's part operations cannot be read back: {exc}") from exc


def operation_payloads(folder: Path, snapshot, payloads: Mapping[str, object], *,
                       stop_event=None) -> Optional[Dict[str, bytes]]:
    """The folder's operations as table bytes, or None when the folder has no operations file."""
    targets = read_operations(folder)
    if targets is None:
        return None
    return fold_operations(snapshot, payloads, targets, stop_event=stop_event)
