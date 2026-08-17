"""`gamedata/binary__/client/bin/iteminfo.pabgb` rows: the fields a New Item flow edits.

An ItemInfo row is the serialised `ItemInfo` reflection class (115 members; the
member names come from the read-failure messages CrimsonDesert.exe carries). This
module models the parts that are established on the shipped corpus and leaves the
rest as opaque bytes, because a wrong guess written back into a row is worse than a
gap the caller can see. What is modelled, and how it was established:

* **Prefix**, sequential from byte 0 and identical in shape on all 6,573 rows:
  `_key` u32; `_stringKey` (u32 length + ASCII, no terminator); u8 (`_isBlocked`, 0
  everywhere); `_maxStackCount` u32 (1 on equipment, 5/10/
  20/50/100 on stackables); u32 0; `_itemName` as a LocalStringInfo sub-record
  `07 70 00 00 00, u32 own key, u32 length, ASCII key`; u32 0; `_equipTypeInfo` u32
  (`hashlittle(lowercase equip type name, 0xC5EDE)`, 0 for non-equipment);
  `_occupiedEquipSlotDataList` (u32 count, then {u32 slot-name hash, u32 count,
  count x u32}).
* **`_itemDesc`** is the unique `07 71 00 00 00, own key` sub-record; **`_itemType`**
  is the u16 seventeen bytes after it, a numeric code per equip type (103 on every
  one-hand sword, 202 on every two-hand sword, 442/412/422 on helms by armour class,
  28001 on food, 4001 on notice papers). The developer memo (Korean text) is the
  first length-prefixed UTF-8 string that follows.
* **Stat block**, anchored by a composite signature and taken at its first
  occurrence after the item type: `DropDefaultData`'s `_socketItemList` (u32 count +
  item keys), `_addSocketMaterialItemList` (u32 count + {item, count, u32}), the
  byte 0x11 then two flag bytes, then **`_enchantDataList`** (u32 count, then one
  `EnchantData` per level: u32 level 0..n-1, six bytes, `_statList_DataDefinedStatic`
  as u32 count + 12-byte {u32 StatusInfo key, i32 value, u32}, `_statList_
  DataDefinedStaticLevel` as u32 count + 25-byte {u32 StatusInfo key, 21 bytes},
  `_buyPriceList` as u32 count + 20-byte {u32 item key, u32 price, u32, u32, u32 item
  key again}, `_equipBuffs` as u32 count + 8-byte {u32 key, u32}, u32 0), then
  **`_priceList`** in the same 20-byte entry shape. On the shipped table this decodes
  every equipment row's ladder; the rows without a stat block are the ones whose
  ladder count is zero and whose price list is empty, which the anchor cannot tell
  from padding.

Stat keys are `statusinfo.pabgb` rows: DDD (1000002) is what every weapon ladder
carries and DPV (1000003) what every armour ladder carries. Price item keys are
`Money_*` items (1 = copper, 11 = camp money, 12 = camp food, 15 = camp weapon
money). Nothing here claims to know `_itemTier`, `_equipableLevel` or
`_maxEndurance`; the bytes are there but their positions have not been proven, so
they stay inside the opaque spans.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, replace
from typing import Iterable, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive_format import hashlittle
from cdmw.core.structured_binary_editor import parse_pabgh_table

STATUSINFO_HASH_INIT = 0xC5EDE
NAME_TAG = b"\x07\x70\x00\x00\x00"
DESC_TAG = b"\x07\x71\x00\x00\x00"
_ITEM_TYPE_GAP = 17
_STAT_BLOCK_MARKER = 0x11
_MAX_LADDER_LEVELS = 40
#: The socket list the reader accepts (`_read_u32_list(limit=8)`); the shipped rows carry at most 4.
_MAX_SOCKET_ITEMS = 8
_MAX_LIST = 64


class ItemInfoRowError(ValueError):
    """Raised when bytes do not follow the established ItemInfo row shape."""


@dataclass(frozen=True, slots=True)
class StatValue:
    status_key: int
    value: int
    #: Byte offset of the i32 value inside the row (-1 on a value built for a rebuild).
    offset: int = -1
    #: The u32 after the value; 0 on every shipped weapon and armour, -1 on a few test items. Carried, not interpreted.
    extra: int = 0


@dataclass(frozen=True, slots=True)
class PriceEntry:
    item_key: int
    price: int
    #: Byte offset of the u32 price inside the row (-1 on an entry built for a rebuild).
    offset: int = -1
    #: The two u32 between the price and the repeated item key; zero on every shipped entry. Carried, not interpreted.
    reserved: Tuple[int, int] = (0, 0)


@dataclass(frozen=True, slots=True)
class EnchantLevel:
    level: int
    #: `_statList_DataDefinedStatic`: (StatusInfo key, i32 value); every weapon carries DDD here, every armour DPV.
    stats: Tuple[StatValue, ...]
    #: `_buyPriceList`: what the level costs to reach, per money item.
    buy_prices: Tuple[PriceEntry, ...]
    offset: int = -1
    end: int = -1
    #: `_statList_DataDefinedStaticLevel` entries by StatusInfo key; their 21 remaining bytes are carried, not decoded.
    level_stat_keys: Tuple[int, ...] = ()
    #: `_equipBuffs` keys.
    equip_buffs: Tuple[int, ...] = ()
    #: The six bytes after the level number (two empty lists on every shipped row).
    header_bytes: bytes = b"\x00" * 6
    #: The 25-byte `_statList_DataDefinedStaticLevel` records, verbatim.
    level_stat_entries: Tuple[bytes, ...] = ()
    #: The u32 beside each `_equipBuffs` key.
    equip_buff_extras: Tuple[int, ...] = ()
    #: The trailing u32 (0 on every shipped level).
    tail: int = 0


@dataclass(frozen=True, slots=True)
class OccupiedSlot:
    slot_name_hash: int
    indexes: Tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ItemInfoRow:
    raw: bytes
    key: int
    string_key: str
    is_blocked: int
    max_stack_count: int
    name_key: str
    equip_type_key: int
    occupied_slots: Tuple[OccupiedSlot, ...]
    prefix_end: int
    desc_key: Optional[str]
    desc_offset: Optional[int]
    item_type: Optional[int]
    item_type_offset: Optional[int]
    memo: Optional[str]
    socket_items: Tuple[int, ...]
    add_socket_materials: Tuple[Tuple[int, int, int], ...]
    stat_block_offset: Optional[int]
    enchant_levels: Tuple[EnchantLevel, ...]
    enchant_count: Optional[int]
    price_list: Tuple[PriceEntry, ...]
    stat_block_end: Optional[int]
    #: The two bytes after the 0x11 marker (`01 03` on Wolf's Fang); carried, not interpreted.
    stat_block_flags: Tuple[int, int] = (0, 0)

    @property
    def max_stack_count_offset(self) -> int:
        # key(4) + length(4) + name + isBlocked(1)
        return 8 + len(self.string_key.encode("utf-8")) + 1

    @property
    def coverage(self) -> str:
        return "stat-block" if self.stat_block_offset is not None else "no-stat-block"

    def stat(self, level: int, status_key: int) -> Optional[StatValue]:
        for entry in self.enchant_levels:
            if entry.level == level:
                for stat in entry.stats:
                    if stat.status_key == status_key:
                        return stat
        return None


# --------------------------------------------------------------------------- readers


def _u32(raw: bytes, offset: int) -> int:
    return struct.unpack_from("<I", raw, offset)[0]


def _read_str(raw: bytes, offset: int, *, limit: int = 1024) -> Tuple[str, int]:
    if offset + 4 > len(raw):
        raise ItemInfoRowError(f"string length at 0x{offset:X} runs past the row")
    length = _u32(raw, offset)
    if length > limit or offset + 4 + length > len(raw):
        raise ItemInfoRowError(f"string of {length} bytes at 0x{offset:X} does not fit the row")
    try:
        return raw[offset + 4 : offset + 4 + length].decode("utf-8"), offset + 4 + length
    except UnicodeDecodeError as exc:
        raise ItemInfoRowError(f"string at 0x{offset:X} is not UTF-8: {exc}") from exc


def _read_local_string(raw: bytes, offset: int, tag: bytes, key: int) -> Tuple[Optional[str], int]:
    """A LocalStringInfo sub-record, or a single 0 byte when the row has none."""

    if offset >= len(raw):
        raise ItemInfoRowError(f"local string at 0x{offset:X} runs past the row")
    if raw[offset] == 0:
        return None, offset + 1
    if raw[offset : offset + 5] != tag:
        raise ItemInfoRowError(f"expected {tag.hex()} at 0x{offset:X}, found {raw[offset:offset + 5].hex()}")
    if _u32(raw, offset + 5) != key:
        raise ItemInfoRowError(f"local string at 0x{offset:X} does not repeat the row key")
    text, end = _read_str(raw, offset + 9, limit=256)
    return text, end


def _read_u32_list(raw: bytes, offset: int, *, limit: int = _MAX_LIST) -> Tuple[Tuple[int, ...], int]:
    count = _u32(raw, offset)
    if count > limit or offset + 4 + 4 * count > len(raw):
        raise ItemInfoRowError(f"list of {count} at 0x{offset:X} does not fit the row")
    return tuple(_u32(raw, offset + 4 + 4 * i) for i in range(count)), offset + 4 + 4 * count


def _read_price_list(raw: bytes, offset: int) -> Optional[Tuple[Tuple[PriceEntry, ...], int]]:
    if offset + 4 > len(raw):
        return None
    count = _u32(raw, offset)
    if count > 8:
        return None
    cursor = offset + 4
    entries = []
    for _ in range(count):
        if cursor + 20 > len(raw):
            return None
        item, price, reserved_a, reserved_c, item_again = struct.unpack_from("<5I", raw, cursor)
        if item != item_again:
            return None
        entries.append(PriceEntry(item_key=item, price=price, offset=cursor + 4, reserved=(reserved_a, reserved_c)))
        cursor += 20
    return tuple(entries), cursor


def _read_enchant_level(raw: bytes, offset: int, level: int) -> Optional[EnchantLevel]:
    """One EnchantData record: level, two empty lists, static stats, static-level stats,
    buy prices, equip buffs, trailing u32. Returns None when the bytes are not that."""

    limit = len(raw)
    if offset + 10 > limit or _u32(raw, offset) != level or raw[offset + 4 : offset + 10] != b"\x00" * 6:
        return None
    cursor = offset + 10
    if cursor + 4 > limit:
        return None
    stat_count = _u32(raw, cursor)
    cursor += 4
    if stat_count > 16 or cursor + 12 * stat_count > limit:
        return None
    header_bytes = bytes(raw[offset + 4 : offset + 10])
    stats = []
    for _ in range(stat_count):
        key, value, extra = struct.unpack_from("<Iii", raw, cursor)
        stats.append(StatValue(status_key=key, value=value, offset=cursor + 4, extra=extra))
        cursor += 12
    if cursor + 4 > limit:
        return None
    level_stat_count = _u32(raw, cursor)
    cursor += 4
    if level_stat_count > 16 or cursor + 25 * level_stat_count > limit:
        return None
    level_stats = []
    level_stat_entries = []
    for _ in range(level_stat_count):
        level_stats.append(_u32(raw, cursor))
        level_stat_entries.append(bytes(raw[cursor : cursor + 25]))
        cursor += 25
    prices = _read_price_list(raw, cursor)
    if prices is None:
        return None
    buy_prices, cursor = prices
    if cursor + 4 > limit:
        return None
    buff_count = _u32(raw, cursor)
    cursor += 4
    if buff_count > 16 or cursor + 8 * buff_count > limit:
        return None
    buffs = tuple(_u32(raw, cursor + 8 * i) for i in range(buff_count))
    buff_extras = tuple(_u32(raw, cursor + 8 * i + 4) for i in range(buff_count))
    cursor += 8 * buff_count
    if cursor + 4 > limit or _u32(raw, cursor) != 0:
        return None
    tail = _u32(raw, cursor)
    cursor += 4
    return EnchantLevel(
        level=level, stats=tuple(stats), buy_prices=buy_prices, offset=offset, end=cursor,
        level_stat_keys=tuple(level_stats), equip_buffs=buffs, header_bytes=header_bytes,
        level_stat_entries=tuple(level_stat_entries), equip_buff_extras=buff_extras, tail=tail,
    )


def _read_stat_block(raw: bytes, offset: int, item_keys: Optional[Iterable[int]] = None):
    """Socket lists + 0x11 + ladder + price list at `offset`, or None if the shape is not there."""

    limit = len(raw)
    known = set(item_keys) if item_keys is not None else None
    if offset + 8 > limit:
        return None
    try:
        socket_items, cursor = _read_u32_list(raw, offset, limit=8)
    except ItemInfoRowError:
        return None
    if known is not None and any(item not in known for item in socket_items):
        return None
    if cursor + 4 > limit:
        return None
    add_count = _u32(raw, cursor)
    if add_count > 8 or cursor + 4 + 12 * add_count > limit:
        return None
    cursor += 4
    adds = []
    for _ in range(add_count):
        adds.append(struct.unpack_from("<III", raw, cursor))
        cursor += 12
    if any(item == 0 or count == 0 for item, count, _x in adds) or any(item == 0 for item in socket_items):
        return None
    if known is not None and any(item not in known for item, _count, _x in adds):
        return None
    if cursor + 7 > limit or raw[cursor] != _STAT_BLOCK_MARKER:
        return None
    flags = (raw[cursor + 1], raw[cursor + 2])
    cursor += 3
    ladder_offset = cursor
    count = _u32(raw, cursor)
    if count > _MAX_LADDER_LEVELS:
        return None
    cursor += 4
    levels = []
    for level in range(count):
        entry = _read_enchant_level(raw, cursor, level)
        if entry is None:
            return None
        levels.append(entry)
        cursor = entry.end
    prices = _read_price_list(raw, cursor)
    if prices is None:
        return None
    price_list, end = prices
    if count == 0 and not price_list and not socket_items and not adds:
        # zeros, a 0x11 and more zeros: not evidence of anything, and rows have such runs
        return None
    return {
        "offset": offset, "socket_items": socket_items, "adds": tuple(adds), "flags": flags,
        "ladder_offset": ladder_offset, "count": count, "levels": tuple(levels), "prices": price_list, "end": end,
    }


def _stat_block_candidates(raw: bytes, start: int) -> Iterable[int]:
    """Offsets where a stat block could begin, in row order.

    The block's 0x11 marker sits 8 + 4*socket_count + 12*material_count bytes after
    the block start, both counts being at most 8, so every 0x11 byte yields at most
    81 starts to check instead of scanning every offset with the full reader.
    """

    marker_at = raw.find(bytes([_STAT_BLOCK_MARKER]), start)
    seen: set[int] = set()
    while marker_at >= 0:
        candidates = []
        for socket_count in range(0, 9):
            for material_count in range(0, 9):
                candidate = marker_at - 8 - 4 * socket_count - 12 * material_count
                if candidate < start or candidate in seen:
                    continue
                if _u32(raw, candidate) != socket_count:
                    continue
                if _u32(raw, candidate + 4 + 4 * socket_count) != material_count:
                    continue
                seen.add(candidate)
                candidates.append(candidate)
        # A material entry {item, count, 0} followed by the marker also reads as
        # {count 1, item, no materials}; the real block starts earlier, so try the
        # earliest candidate first.
        for candidate in sorted(candidates):
            yield candidate
        marker_at = raw.find(bytes([_STAT_BLOCK_MARKER]), marker_at + 1)


def _find_memo(raw: bytes, start: int) -> Optional[str]:
    for offset in range(start, min(len(raw) - 4, start + 64)):
        length = _u32(raw, offset)
        if length == 0 or length > 400 or offset + 4 + length > len(raw):
            continue
        try:
            text = raw[offset + 4 : offset + 4 + length].decode("utf-8")
        except UnicodeDecodeError:
            continue
        if not text.isprintable():
            continue
        if text.isascii() or any("가" <= ch <= "힣" for ch in text):
            return text
    return None


def parse_iteminfo_row(raw: bytes, *, item_keys: Optional[Iterable[int]] = None) -> ItemInfoRow:
    """Decode one row. `item_keys` (every key in the table) tightens the stat-block anchor.

    Raises :class:`ItemInfoRowError` only when the prefix is not an ItemInfo row at
    all; a row whose stat block cannot be found parses with `coverage == "no-stat-block"`.
    """

    data = bytes(raw or b"")
    if len(data) < 12:
        raise ItemInfoRowError("row is too short to hold a key and a name")
    key = _u32(data, 0)
    string_key, cursor = _read_str(data, 4, limit=256)
    if cursor >= len(data):
        raise ItemInfoRowError("row ends inside its string key")
    is_blocked = data[cursor]
    cursor += 1
    max_stack_count = _u32(data, cursor)
    cursor += 4
    cursor += 4  # u32, zero on every shipped row
    name_key, cursor = _read_local_string(data, cursor, NAME_TAG, key)
    cursor += 4  # u32, zero on every shipped row
    equip_type_key = _u32(data, cursor)
    cursor += 4
    occupied_count = _u32(data, cursor)
    if occupied_count > 8:
        raise ItemInfoRowError(f"{occupied_count} occupied equip slots at 0x{cursor:X}")
    cursor += 4
    occupied = []
    for _ in range(occupied_count):
        slot_hash = _u32(data, cursor)
        indexes, cursor = _read_u32_list(data, cursor + 4, limit=16)
        occupied.append(OccupiedSlot(slot_name_hash=slot_hash, indexes=indexes))
    prefix_end = cursor

    # description anchor
    needle = DESC_TAG + struct.pack("<I", key)
    desc_offset = data.find(needle, prefix_end)
    desc_key = None
    item_type = None
    item_type_offset = None
    memo = None
    if desc_offset >= 0 and data.find(needle, desc_offset + 1) < 0:
        desc_key, desc_end = _read_local_string(data, desc_offset, DESC_TAG, key)
        if desc_end + _ITEM_TYPE_GAP + 2 <= len(data) and data[desc_end : desc_end + _ITEM_TYPE_GAP] == b"\x00" * _ITEM_TYPE_GAP:
            item_type_offset = desc_end + _ITEM_TYPE_GAP
            item_type = struct.unpack_from("<H", data, item_type_offset)[0]
            memo = _find_memo(data, item_type_offset + 2)
    else:
        desc_offset = None

    # stat block: first place (after the item type) where the composite shape holds
    block = None
    search_from = (item_type_offset + 2) if item_type_offset is not None else prefix_end
    for offset in _stat_block_candidates(data, search_from):
        block = _read_stat_block(data, offset, item_keys)
        if block is not None:
            break
    if block is None:
        return ItemInfoRow(
            raw=data, key=key, string_key=string_key, is_blocked=is_blocked, max_stack_count=max_stack_count,
            name_key=name_key or "", equip_type_key=equip_type_key, occupied_slots=tuple(occupied), prefix_end=prefix_end,
            desc_key=desc_key, desc_offset=desc_offset, item_type=item_type, item_type_offset=item_type_offset, memo=memo,
            socket_items=(), add_socket_materials=(), stat_block_offset=None, enchant_levels=(), enchant_count=None,
            price_list=(), stat_block_end=None,
        )
    return ItemInfoRow(
        raw=data, key=key, string_key=string_key, is_blocked=is_blocked, max_stack_count=max_stack_count,
        name_key=name_key or "", equip_type_key=equip_type_key, occupied_slots=tuple(occupied), prefix_end=prefix_end,
        desc_key=desc_key, desc_offset=desc_offset, item_type=item_type, item_type_offset=item_type_offset, memo=memo,
        socket_items=block["socket_items"], add_socket_materials=block["adds"], stat_block_offset=block["offset"],
        enchant_levels=block["levels"], enchant_count=block["count"], price_list=block["prices"], stat_block_end=block["end"],
        stat_block_flags=tuple(block["flags"]),
    )


# --------------------------------------------------------------------------- editors


def _write_u32(raw: bytes, offset: int, value: int, *, signed: bool = False) -> bytes:
    out = bytearray(raw)
    struct.pack_into("<i" if signed else "<I", out, offset, int(value))
    return bytes(out)


def set_max_stack_count(row: ItemInfoRow, value: int) -> bytes:
    if not 1 <= int(value) <= 0xFFFFFFFF:
        raise ItemInfoRowError("max stack count must be a positive u32")
    return _write_u32(row.raw, row.max_stack_count_offset, value)


def set_stat_value(row: ItemInfoRow, level: int, status_key: int, value: int) -> bytes:
    """Rewrite one existing stat entry's value in place (i32)."""

    stat = row.stat(level, status_key)
    if stat is None:
        raise ItemInfoRowError(f"level {level} has no stat {status_key} to rewrite; adding stats needs a row rebuild")
    if not -0x80000000 <= int(value) <= 0x7FFFFFFF:
        raise ItemInfoRowError("stat values are i32")
    return _write_u32(row.raw, stat.offset, value, signed=True)


def set_buy_price(row: ItemInfoRow, level: int, item_key: int, price: int) -> bytes:
    for entry in row.enchant_levels:
        if entry.level == level:
            for price_entry in entry.buy_prices:
                if price_entry.item_key == item_key:
                    return _write_u32(row.raw, price_entry.offset, price)
    raise ItemInfoRowError(f"level {level} has no buy price in item {item_key}")


def set_price(row: ItemInfoRow, item_key: int, price: int) -> bytes:
    for entry in row.price_list:
        if entry.item_key == item_key:
            return _write_u32(row.raw, entry.offset, price)
    raise ItemInfoRowError(f"the price list has no entry in item {item_key}")


def scale_stats(row: ItemInfoRow, status_key: int, factor: float) -> bytes:
    """Multiply one stat across every decoded level; the usual 'stronger clone' edit."""

    out = row.raw
    touched = 0
    for entry in row.enchant_levels:
        for stat in entry.stats:
            if stat.status_key == status_key:
                out = _write_u32(out, stat.offset, int(round(stat.value * factor)), signed=True)
                touched += 1
    if not touched:
        raise ItemInfoRowError(f"no level carries stat {status_key}")
    return out


def clone_iteminfo_row(
    row: ItemInfoRow,
    *,
    key: int,
    string_key: str,
    name_key: str,
    desc_key: Optional[str] = None,
    replace_hashes: Optional[Mapping[int, int]] = None,
) -> bytes:
    """A new row from a template: new key (three places), internal name, localisation keys.

    `replace_hashes` swaps u32 values anywhere after the prefix (model stem hashes,
    icon hash); each old value must occur at least once. This is exactly the recipe
    that produced the in-game-verified clones on 2026-08-17.
    """

    if not (0 < int(key) <= 0xFFFFFFFF):
        raise ItemInfoRowError("key must be a positive u32")
    if int(key) == row.key:
        raise ItemInfoRowError("the clone needs a key different from its template")
    if not string_key or not string_key.isascii() or len(string_key.encode("ascii")) > 255:
        raise ItemInfoRowError("string key must be short ASCII")
    if not name_key or not name_key.isascii():
        raise ItemInfoRowError("name key must be ASCII")
    if row.desc_offset is not None and (desc_key is None or not desc_key.isascii()):
        raise ItemInfoRowError("the template has a description key; give the clone one")
    raw = row.raw
    old_key = struct.pack("<I", row.key)
    new_key = struct.pack("<I", int(key))
    # rebuild [key][string key][isBlocked][maxStack][u32][name lstr]... by slicing around the strings
    name_start = 8 + len(row.string_key.encode("utf-8")) + 1 + 4 + 4
    old_name = row.raw[name_start:]
    if not old_name.startswith(NAME_TAG + old_key):
        raise ItemInfoRowError("template name sub-record is not where the prefix says")
    old_name_len = _u32(raw, name_start + 5 + 4)
    name_end = name_start + 9 + 4 + old_name_len
    out = bytearray()
    out += new_key
    encoded = string_key.encode("ascii")
    out += struct.pack("<I", len(encoded)) + encoded
    out += raw[8 + len(row.string_key.encode("utf-8")) : name_start]  # isBlocked, maxStack, u32
    encoded_name = name_key.encode("ascii")
    out += NAME_TAG + new_key + struct.pack("<I", len(encoded_name)) + encoded_name
    tail = bytearray(raw[name_end:])
    if row.desc_offset is not None:
        desc_at = row.desc_offset - name_end
        if not bytes(tail[desc_at : desc_at + 9]) == DESC_TAG + old_key:
            raise ItemInfoRowError("template description sub-record is not where the parse says")
        old_desc_len = _u32(tail, desc_at + 9)
        encoded_desc = (desc_key or "").encode("ascii")
        tail[desc_at : desc_at + 13 + old_desc_len] = DESC_TAG + new_key + struct.pack("<I", len(encoded_desc)) + encoded_desc
    if tail.count(old_key):
        raise ItemInfoRowError(
            f"the template key still appears {tail.count(old_key)} more time(s) after the description; refusing to guess what it means"
        )
    for old_hash, new_hash in (replace_hashes or {}).items():
        needle = struct.pack("<I", int(old_hash) & 0xFFFFFFFF)
        if tail.count(needle) == 0:
            raise ItemInfoRowError(f"hash 0x{int(old_hash):08X} does not occur in the template after the prefix")
        tail = bytearray(bytes(tail).replace(needle, struct.pack("<I", int(new_hash) & 0xFFFFFFFF)))
    out += tail
    return bytes(out)


# --------------------------------------------------------------------------- stat block rebuild
#
# The editors above rewrite values in place. Changing the *shape* of the ladder
# (a stat the template lacks, one more enhancement level, a price in another
# money item) means re-serialising the whole stat block, which is only safe if
# the encoder reproduces every shipped block byte for byte from its own parse.
# That round trip is what test_iteminfo_row's real_game gate proves before any
# rebuilt block is trusted; the encoder below carries every byte the parser saw.


def _encode_price_entry(entry: PriceEntry) -> bytes:
    return struct.pack("<5I", entry.item_key, entry.price, entry.reserved[0], entry.reserved[1], entry.item_key)


def encode_enchant_level(level: EnchantLevel) -> bytes:
    """One `EnchantData` record in the proven grammar."""

    if len(level.header_bytes) != 6:
        raise ItemInfoRowError("an enchant level carries six header bytes")
    if len(level.level_stat_keys) != len(level.level_stat_entries) or any(len(entry) != 25 for entry in level.level_stat_entries):
        raise ItemInfoRowError("static-level entries are 25 bytes each, one per key")
    if len(level.equip_buffs) != len(level.equip_buff_extras):
        raise ItemInfoRowError("every equip buff key carries one extra u32")
    out = bytearray(struct.pack("<I", level.level)) + level.header_bytes
    out += struct.pack("<I", len(level.stats))
    for stat in level.stats:
        out += struct.pack("<Iii", stat.status_key, stat.value, stat.extra)
    out += struct.pack("<I", len(level.level_stat_entries)) + b"".join(level.level_stat_entries)
    out += struct.pack("<I", len(level.buy_prices)) + b"".join(_encode_price_entry(entry) for entry in level.buy_prices)
    out += struct.pack("<I", len(level.equip_buffs))
    for key, extra in zip(level.equip_buffs, level.equip_buff_extras):
        out += struct.pack("<II", key, extra)
    out += struct.pack("<I", level.tail)
    return bytes(out)


def encode_stat_block(
    row: ItemInfoRow,
    *,
    levels: Optional[Sequence[EnchantLevel]] = None,
    price_list: Optional[Sequence[PriceEntry]] = None,
    socket_items: Optional[Sequence[int]] = None,
) -> bytes:
    """The stat block bytes for `row`, with its ladder, price list and/or socket items replaced.

    With no argument the result equals `row.raw[stat_block_offset:stat_block_end]`
    on every shipped row (the corpus gate). Levels must be numbered 0..n-1 in order.
    `socket_items` are the Abyss Gear items embedded by default (the "perks" the
    tooltip lists); the shipped rows carry 0..4 and the reader accepts up to 8.
    """

    if row.stat_block_offset is None:
        raise ItemInfoRowError(f"{row.string_key} has no decoded stat block to rebuild")
    ladder = tuple(row.enchant_levels if levels is None else levels)
    prices = tuple(row.price_list if price_list is None else price_list)
    sockets = tuple(int(item) for item in (row.socket_items if socket_items is None else socket_items))
    if [entry.level for entry in ladder] != list(range(len(ladder))):
        raise ItemInfoRowError("enchant levels must run 0..n-1 without gaps")
    if len(ladder) > _MAX_LADDER_LEVELS:
        raise ItemInfoRowError(f"more than {_MAX_LADDER_LEVELS} enchant levels")
    if len(sockets) > _MAX_SOCKET_ITEMS:
        raise ItemInfoRowError(f"more than {_MAX_SOCKET_ITEMS} socket items")
    if any(not 0 < item <= 0xFFFFFFFF for item in sockets):
        raise ItemInfoRowError("socket items are positive u32 item keys")
    out = bytearray(struct.pack("<I", len(sockets)))
    for item in sockets:
        out += struct.pack("<I", item)
    out += struct.pack("<I", len(row.add_socket_materials))
    for item, count, extra in row.add_socket_materials:
        out += struct.pack("<III", item, count, extra)
    out += bytes([_STAT_BLOCK_MARKER, row.stat_block_flags[0], row.stat_block_flags[1]])
    out += struct.pack("<I", len(ladder)) + b"".join(encode_enchant_level(level) for level in ladder)
    out += struct.pack("<I", len(prices)) + b"".join(_encode_price_entry(entry) for entry in prices)
    return bytes(out)


def rebuild_stat_block(
    row: ItemInfoRow,
    *,
    levels: Optional[Sequence[EnchantLevel]] = None,
    price_list: Optional[Sequence[PriceEntry]] = None,
    socket_items: Optional[Sequence[int]] = None,
) -> bytes:
    """The row with its stat block re-serialised from `levels` / `price_list` / `socket_items`; every other byte stays."""

    block = encode_stat_block(row, levels=levels, price_list=price_list, socket_items=socket_items)
    return row.raw[: row.stat_block_offset] + block + row.raw[row.stat_block_end :]


def level_with_stat(level: EnchantLevel, status_key: int, value: int, *, extra: int = 0) -> EnchantLevel:
    """The level with `status_key` set to `value`, added at the end if it was not there."""

    if not -0x80000000 <= int(value) <= 0x7FFFFFFF:
        raise ItemInfoRowError("stat values are i32")
    stats = list(level.stats)
    for index, stat in enumerate(stats):
        if stat.status_key == status_key:
            stats[index] = replace(stat, value=int(value))
            return replace(level, stats=tuple(stats))
    stats.append(StatValue(status_key=int(status_key), value=int(value), extra=int(extra)))
    return replace(level, stats=tuple(stats))


def level_without_stat(level: EnchantLevel, status_key: int) -> EnchantLevel:
    stats = tuple(stat for stat in level.stats if stat.status_key != status_key)
    if len(stats) == len(level.stats):
        raise ItemInfoRowError(f"level {level.level} has no stat {status_key}")
    return replace(level, stats=stats)


def level_with_buy_price(level: EnchantLevel, item_key: int, price: int) -> EnchantLevel:
    """The level with its price in `item_key` set (added at the end if missing)."""

    if not 0 <= int(price) <= 0xFFFFFFFF:
        raise ItemInfoRowError("prices are u32")
    entries = list(level.buy_prices)
    for index, entry in enumerate(entries):
        if entry.item_key == item_key:
            entries[index] = replace(entry, price=int(price))
            return replace(level, buy_prices=tuple(entries))
    entries.append(PriceEntry(item_key=int(item_key), price=int(price)))
    return replace(level, buy_prices=tuple(entries))


def level_without_buy_price(level: EnchantLevel, item_key: int) -> EnchantLevel:
    entries = tuple(entry for entry in level.buy_prices if entry.item_key != item_key)
    if len(entries) == len(level.buy_prices):
        raise ItemInfoRowError(f"level {level.level} has no buy price in item {item_key}")
    return replace(level, buy_prices=entries)


def next_level_like(last: EnchantLevel) -> EnchantLevel:
    """A new top level copied from `last`: same stats, prices, buffs and static-level entries, level + 1.

    Adding a level this way writes only shapes the game has already been shown for
    this item; the caller then changes numbers with :func:`level_with_stat` and
    :func:`level_with_buy_price`.
    """

    return replace(
        last,
        level=last.level + 1,
        offset=-1,
        end=-1,
        stats=tuple(replace(stat, offset=-1) for stat in last.stats),
        buy_prices=tuple(replace(entry, offset=-1) for entry in last.buy_prices),
    )


def price_list_with(entries: Sequence[PriceEntry], item_key: int, price: int) -> Tuple[PriceEntry, ...]:
    """A price list with `item_key` set to `price` (added at the end if missing)."""

    if not 0 <= int(price) <= 0xFFFFFFFF:
        raise ItemInfoRowError("prices are u32")
    out = list(entries)
    for index, entry in enumerate(out):
        if entry.item_key == item_key:
            out[index] = replace(entry, price=int(price))
            return tuple(out)
    out.append(PriceEntry(item_key=int(item_key), price=int(price)))
    return tuple(out)


def price_list_without(entries: Sequence[PriceEntry], item_key: int) -> Tuple[PriceEntry, ...]:
    out = tuple(entry for entry in entries if entry.item_key != item_key)
    if len(out) == len(tuple(entries)):
        raise ItemInfoRowError(f"the price list has no entry in item {item_key}")
    return out


# --------------------------------------------------------------------------- StatusInfo names


def parse_status_names(payload: bytes, header: bytes) -> Mapping[int, str]:
    """`statusinfo.pabgb`: key -> stat name (Hp, DDD, DPV, CriticalRate ...)."""

    table = parse_pabgh_table(bytes(header or b""), payload=bytes(payload or b""))
    names = {}
    for row, start, end in table.row_spans(len(payload)):
        length = _u32(payload, start + table.key_width)
        text_start = start + table.key_width + 4
        if 0 < length <= 128 and text_start + length <= end:
            names[row.row_id] = payload[text_start : text_start + length].split(b"\x00", 1)[0].decode("ascii", "replace")
    return names


def equip_type_key(name: str) -> int:
    """`_equipTypeInfo` keys are `hashlittle` of the lowercase equip type name."""

    return int(hashlittle(str(name).lower().encode("utf-8"), STATUSINFO_HASH_INIT)) & 0xFFFFFFFF


def describe_row(row: ItemInfoRow, status_names: Optional[Mapping[int, str]] = None) -> Tuple[str, ...]:
    names = dict(status_names or {})
    lines = [
        f"{row.string_key} (key {row.key}) type {row.item_type} stack {row.max_stack_count} coverage {row.coverage}",
    ]
    for level in row.enchant_levels:
        stats = ", ".join(f"{names.get(s.status_key, s.status_key)}={s.value}" for s in level.stats) or "no stats"
        prices = ", ".join(f"{p.item_key}:{p.price}" for p in level.buy_prices)
        lines.append(f"  +{level.level}: {stats}" + (f"; buy {prices}" if prices else ""))
    if row.price_list:
        lines.append("  price: " + ", ".join(f"{p.item_key}:{p.price}" for p in row.price_list))
    return tuple(lines)


__all__ = [
    "DESC_TAG",
    "EnchantLevel",
    "ItemInfoRow",
    "ItemInfoRowError",
    "NAME_TAG",
    "OccupiedSlot",
    "PriceEntry",
    "StatValue",
    "clone_iteminfo_row",
    "describe_row",
    "equip_type_key",
    "parse_iteminfo_row",
    "parse_status_names",
    "scale_stats",
    "set_buy_price",
    "set_max_stack_count",
    "set_price",
    "set_stat_value",
]
