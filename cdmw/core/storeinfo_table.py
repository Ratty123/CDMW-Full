"""`storeinfo.pabgb` rows: what a shop stocks, and how to change it.

The row grammar was measured on the shipped table (437 rows, 6,378 stock entries,
2026-08-17) with the exe's own member names as the guide (`StoreInfo._stockDataList`,
`StockData._stockIndex/_orderIndex/_minPricePercent/_maxPricePercent/...`):

    u16 key, u32 len, name, ... opaque prefix (37 or 85 bytes; the longer one carries a
    6 x u64 sell-percent list) ...
    u32 buyableStockCount, u32 sellableStockCount, u8 storeType, u32 stockCount
    stockCount x StockData
    ... opaque tail (15-17 bytes) ...

    StockData (relative offsets):
    +0x00 u16 storeInfo (== the row key)     +0x02 u64 minPricePercent (1,000,000 = 100%)
    +0x0a u64 maxPricePercent                +0x12 u32 count (refill / stock quantity)
    +0x16 i32 threshold (-1 or a count)      +0x1a u32 stockIndex (== position, always)
    +0x1e u32 orderIndex                     +0x22 i32 importantSaveIndex (-1 everywhere)
    +0x26 5 x u8 flags: ?, isStockSellable, isStockBuyable, ?, ?
    +0x2b u32 item                           +0x2f 55 bytes drop data (enchant level etc.)
    +0x66 u32 item again                     +0x6a 8 bytes
    +0x72 u8 hasOption; if 1: u32 option item, u8, 8 bytes (a condition hash)
    u32 n; n x 12 bytes (order-count records)

Every row round-trips byte for byte through `parse_store_row` and `encode_store_row`;
the corpus gate in `tests/test_storeinfo_table.py` holds that. Buyable entries come
first and sellable ones after them, `stockIndex` equals the entry's position, and the
head counts equal the number of entries carrying each flag, so an insert renumbers and
recounts from the entries rather than trusting the caller. The 2026-08-17 spike swapped
items in place in `Store_Camp_Equipment` and `Store_Pai_Equipment` and the game sold the
new items; inserting a whole entry changes the row length and goes through
`replace_table_row`, and is unproven in game.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, replace
from typing import Iterable, Mapping, Optional, Sequence, Tuple

from cdmw.core.structured_binary_editor import parse_pabgh_table, replace_table_row

STOREINFO_PAYLOAD_PATH = "gamedata/binary__/client/bin/storeinfo.pabgb"
STOREINFO_HEADER_PATH = "gamedata/binary__/client/bin/storeinfo.pabgh"

_HEAD = 13
_FIXED = 0x77
_OPTION = 13
_ORDER_RECORD = 12
_ITEM_A = 0x2B
_ITEM_B = 0x66
_OPTION_FLAG = 0x72
_KNOWN_STORE_TYPES = (0, 1, 2, 4, 5)
_MAX_ORDER_RECORDS = 8


class StoreInfoError(ValueError):
    """Raised when a store row does not read as the format, or an edit is refused."""


@dataclass(frozen=True, slots=True)
class StockEntry:
    """One `StockData` record: an item a shop buys or sells."""

    store_key: int
    min_price_percent: int
    max_price_percent: int
    count: int
    threshold: int
    stock_index: int
    order_index: int
    important_save_index: int
    flags: bytes
    item_key: int
    drop_bytes: bytes
    after_bytes: bytes
    option_block: Optional[bytes]
    order_records: Tuple[bytes, ...]
    offset: int = -1
    end: int = -1

    @property
    def is_sellable(self) -> bool:
        return bool(self.flags[1])

    @property
    def is_buyable(self) -> bool:
        return bool(self.flags[2])

    @property
    def option_item_key(self) -> Optional[int]:
        return struct.unpack_from("<I", self.option_block, 0)[0] if self.option_block else None

    def with_item(self, item_key: int) -> "StockEntry":
        return replace(self, item_key=_u32(item_key, "item key"), offset=-1, end=-1)

    def with_indices(self, stock_index: int, order_index: Optional[int] = None) -> "StockEntry":
        return replace(
            self,
            stock_index=_u32(stock_index, "stock index"),
            order_index=self.order_index if order_index is None else _u32(order_index, "order index"),
            offset=-1,
            end=-1,
        )


def encode_stock_entry(entry: StockEntry) -> bytes:
    if len(entry.flags) != 5:
        raise StoreInfoError("a stock entry carries five flag bytes")
    if len(entry.drop_bytes) != _ITEM_B - (_ITEM_A + 4):
        raise StoreInfoError(f"drop data is {_ITEM_B - (_ITEM_A + 4)} bytes")
    if len(entry.after_bytes) != _OPTION_FLAG - (_ITEM_B + 4):
        raise StoreInfoError(f"the bytes after the second item key are {_OPTION_FLAG - (_ITEM_B + 4)} bytes")
    if entry.option_block is not None and len(entry.option_block) != _OPTION:
        raise StoreInfoError(f"the option block is {_OPTION} bytes")
    if any(len(record) != _ORDER_RECORD for record in entry.order_records):
        raise StoreInfoError(f"order-count records are {_ORDER_RECORD} bytes")
    out = bytearray()
    out += struct.pack("<H", _u16(entry.store_key, "store key"))
    out += struct.pack("<QQ", _u64(entry.min_price_percent, "min price percent"), _u64(entry.max_price_percent, "max price percent"))
    out += struct.pack("<Ii", _u32(entry.count, "count"), _i32(entry.threshold, "threshold"))
    out += struct.pack("<IIi", _u32(entry.stock_index, "stock index"), _u32(entry.order_index, "order index"), _i32(entry.important_save_index, "important save index"))
    out += bytes(entry.flags)
    out += struct.pack("<I", _u32(entry.item_key, "item key"))
    out += bytes(entry.drop_bytes)
    out += struct.pack("<I", entry.item_key)
    out += bytes(entry.after_bytes)
    if entry.option_block is None:
        out += b"\x00"
    else:
        out += b"\x01" + bytes(entry.option_block)
    out += struct.pack("<I", len(entry.order_records))
    for record in entry.order_records:
        out += bytes(record)
    return bytes(out)


@dataclass(frozen=True, slots=True)
class StoreRow:
    """One store: its stock, and the bytes around it that this module does not decode."""

    raw: bytes
    key: int
    name: str
    prefix: bytes
    buyable_count: int
    sellable_count: int
    store_type: int
    entries: Tuple[StockEntry, ...]
    tail: bytes
    head_offset: int

    @property
    def buyable_entries(self) -> Tuple[StockEntry, ...]:
        return tuple(entry for entry in self.entries if entry.is_buyable)

    @property
    def sellable_entries(self) -> Tuple[StockEntry, ...]:
        return tuple(entry for entry in self.entries if entry.is_sellable)

    def entries_for(self, item_key: int) -> Tuple[StockEntry, ...]:
        return tuple(entry for entry in self.entries if entry.item_key == int(item_key))


def _u16(value: int, what: str) -> int:
    value = int(value)
    if not 0 <= value <= 0xFFFF:
        raise StoreInfoError(f"{what} {value} does not fit a u16")
    return value


def _u32(value: int, what: str) -> int:
    value = int(value)
    if not 0 <= value <= 0xFFFFFFFF:
        raise StoreInfoError(f"{what} {value} does not fit a u32")
    return value


def _i32(value: int, what: str) -> int:
    value = int(value)
    if not -0x80000000 <= value <= 0x7FFFFFFF:
        raise StoreInfoError(f"{what} {value} does not fit an i32")
    return value


def _u64(value: int, what: str) -> int:
    value = int(value)
    if not 0 <= value <= 0xFFFFFFFFFFFFFFFF:
        raise StoreInfoError(f"{what} {value} does not fit a u64")
    return value


def _entry_length(raw: bytes, offset: int) -> Optional[int]:
    """The byte length of the entry at `offset`, or None if the shape fails."""

    if offset + _FIXED > len(raw):
        return None
    flag = raw[offset + _OPTION_FLAG]
    if flag == 0:
        fixed = _FIXED
    elif flag == 1:
        fixed = _FIXED + _OPTION
    else:
        return None
    if offset + fixed > len(raw):
        return None
    records = struct.unpack_from("<I", raw, offset + fixed - 4)[0]
    if records > _MAX_ORDER_RECORDS:
        return None
    length = fixed + records * _ORDER_RECORD
    return length if offset + length <= len(raw) else None


def _looks_like_first_entry(raw: bytes, offset: int, key: int) -> bool:
    if offset + _FIXED > len(raw):
        return False
    if struct.unpack_from("<H", raw, offset)[0] != key:
        return False
    if struct.unpack_from("<I", raw, offset + _ITEM_A)[0] != struct.unpack_from("<I", raw, offset + _ITEM_B)[0]:
        return False
    if struct.unpack_from("<I", raw, offset + 0x1A)[0] != 0:
        return False
    if _entry_length(raw, offset) is None:
        return False
    return raw[offset - 5] in _KNOWN_STORE_TYPES and struct.unpack_from("<I", raw, offset - 4)[0] >= 1


def _parse_entry(raw: bytes, offset: int, length: int) -> StockEntry:
    store_key = struct.unpack_from("<H", raw, offset)[0]
    min_pct, max_pct = struct.unpack_from("<QQ", raw, offset + 2)
    count, threshold = struct.unpack_from("<Ii", raw, offset + 0x12)
    stock_index, order_index, save_index = struct.unpack_from("<IIi", raw, offset + 0x1A)
    flags = bytes(raw[offset + 0x26:offset + 0x2B])
    item = struct.unpack_from("<I", raw, offset + _ITEM_A)[0]
    drop = bytes(raw[offset + _ITEM_A + 4:offset + _ITEM_B])
    after = bytes(raw[offset + _ITEM_B + 4:offset + _OPTION_FLAG])
    pos = offset + _OPTION_FLAG + 1
    option = None
    if raw[offset + _OPTION_FLAG] == 1:
        option = bytes(raw[pos:pos + _OPTION])
        pos += _OPTION
    records_count = struct.unpack_from("<I", raw, pos)[0]
    pos += 4
    records = tuple(bytes(raw[pos + i * _ORDER_RECORD:pos + (i + 1) * _ORDER_RECORD]) for i in range(records_count))
    return StockEntry(
        store_key=store_key, min_price_percent=min_pct, max_price_percent=max_pct, count=count,
        threshold=threshold, stock_index=stock_index, order_index=order_index,
        important_save_index=save_index, flags=flags, item_key=item, drop_bytes=drop,
        after_bytes=after, option_block=option, order_records=records, offset=offset, end=offset + length,
    )


def _find_empty_head(raw: bytes, name_end: int) -> Optional[int]:
    """The head of a store with no stock: eight zero bytes, a store type, four zero bytes,
    followed by a tail of at most 32 bytes.

    The zero bytes of such a tail match the pattern again a few bytes later, so the
    earliest hit is the head.
    """

    for offset in range(name_end, len(raw) - _HEAD + 1):
        if raw[offset:offset + 8] != b"\x00" * 8 or raw[offset + 9:offset + 13] != b"\x00" * 4:
            continue
        if raw[offset + 8] not in _KNOWN_STORE_TYPES:
            continue
        if len(raw) - (offset + _HEAD) <= 32:
            return offset
    return None


def parse_store_row(raw: bytes, *, key: Optional[int] = None) -> StoreRow:
    """Decode one store row. `key` cross-checks the row's own u16 key when given."""

    data = bytes(raw)
    if len(data) < 6:
        raise StoreInfoError("row is too short for a key and a name length")
    row_key = struct.unpack_from("<H", data, 0)[0]
    if key is not None and int(key) != row_key:
        raise StoreInfoError(f"row key {row_key} does not match the directory key {int(key)}")
    length = struct.unpack_from("<I", data, 2)[0]
    if 6 + length + 1 > len(data):
        raise StoreInfoError(f"store name of {length} bytes runs past the row")
    name = data[6:6 + length].decode("utf-8", "replace")
    name_end = 6 + length + 1

    head = None
    for offset in range(name_end + _HEAD, len(data) - _FIXED + 1):
        if _looks_like_first_entry(data, offset, row_key):
            head = offset - _HEAD
            break
    if head is None:
        head = _find_empty_head(data, name_end)
        if head is None:
            raise StoreInfoError(f"store {name!r} ({row_key}): no stock list found")
    buyable, sellable = struct.unpack_from("<II", data, head)
    store_type = data[head + 8]
    total = struct.unpack_from("<I", data, head + 9)[0]
    if store_type not in _KNOWN_STORE_TYPES:
        raise StoreInfoError(f"store {name!r} ({row_key}): unknown store type {store_type}")

    entries = []
    pos = head + _HEAD
    for index in range(total):
        length = _entry_length(data, pos)
        if length is None:
            raise StoreInfoError(f"store {name!r} ({row_key}): stock entry {index} at 0x{pos:X} does not read")
        entry = _parse_entry(data, pos, length)
        if entry.store_key != row_key:
            raise StoreInfoError(f"store {name!r} ({row_key}): entry {index} names store {entry.store_key}")
        if entry.item_key != struct.unpack_from("<I", data, pos + _ITEM_B)[0]:
            raise StoreInfoError(f"store {name!r} ({row_key}): entry {index} does not repeat its item key")
        entries.append(entry)
        pos += length
    return StoreRow(
        raw=data, key=row_key, name=name, prefix=data[:head], buyable_count=buyable,
        sellable_count=sellable, store_type=store_type, entries=tuple(entries),
        tail=data[pos:], head_offset=head,
    )


def encode_store_row(row: StoreRow) -> bytes:
    """Serialise a row; a fresh parse re-encodes to its own bytes."""

    out = bytearray(row.prefix)
    out += struct.pack("<II", _u32(row.buyable_count, "buyable count"), _u32(row.sellable_count, "sellable count"))
    out += bytes([row.store_type])
    out += struct.pack("<I", len(row.entries))
    for entry in row.entries:
        out += encode_stock_entry(entry)
    out += row.tail
    return bytes(out)


def _renumbered(row: StoreRow, entries: Sequence[StockEntry]) -> StoreRow:
    """`row` with `entries`, stock indices set to position and the head counts recounted."""

    fixed = tuple(entry.with_indices(index) if entry.stock_index != index else entry for index, entry in enumerate(entries))
    buyable = sum(1 for entry in fixed if entry.is_buyable)
    sellable = sum(1 for entry in fixed if entry.is_sellable)
    updated = replace(row, entries=fixed, buyable_count=buyable, sellable_count=sellable)
    return replace(updated, raw=encode_store_row(updated))


def swap_stock_item(row: StoreRow, old_item_key: int, new_item_key: int, *, all_entries: bool = False) -> StoreRow:
    """Point the entry stocking `old_item_key` at `new_item_key`, in place.

    Both copies of the key move together and nothing else in the row changes, which is
    what the spike did and the game accepted. A store that lists the old item more than
    once is refused unless `all_entries` is set, so a caller cannot retarget an entry it
    has not looked at.
    """

    matches = row.entries_for(old_item_key)
    if not matches:
        raise StoreInfoError(f"store {row.name!r} does not stock item {int(old_item_key)}")
    if len(matches) > 1 and not all_entries:
        raise StoreInfoError(
            f"store {row.name!r} lists item {int(old_item_key)} {len(matches)} times; pass all_entries=True to retarget every one"
        )
    entries = tuple(entry.with_item(new_item_key) if entry.item_key == int(old_item_key) else entry for entry in row.entries)
    updated = replace(row, entries=entries)
    return replace(updated, raw=encode_store_row(updated))


def insert_stock_entry(
    row: StoreRow,
    item_key: int,
    *,
    template: Optional[StockEntry] = None,
    position: Optional[int] = None,
) -> StoreRow:
    """Add a stock entry for `item_key`, shaped like `template`.

    The template defaults to the row's last buyable entry, so the new item is sold on
    the same terms as its neighbour; a store with no buyable entry needs one passed in.
    The entry goes at `position` (default: after the last buyable entry, so the
    sellable ones stay behind it), every entry is renumbered so `stockIndex` still equals
    its position, the order index becomes one past the largest, and the head counts are
    recounted from the flags. The row grows, so the caller writes it back with
    `replace_table_row`.
    """

    source = template
    if source is None:
        buyable = row.buyable_entries
        if not buyable:
            raise StoreInfoError(f"store {row.name!r} has no buyable entry to copy; pass a template")
        source = buyable[-1]
    if row.entries_for(item_key):
        raise StoreInfoError(f"store {row.name!r} already stocks item {int(item_key)}")
    if position is None:
        last_buyable = max((index for index, entry in enumerate(row.entries) if entry.is_buyable), default=-1)
        position = last_buyable + 1
    if not 0 <= int(position) <= len(row.entries):
        raise StoreInfoError(f"position {position} is outside 0..{len(row.entries)}")
    next_order = max((entry.order_index for entry in row.entries), default=-1) + 1
    fresh = replace(source, store_key=row.key, item_key=_u32(item_key, "item key"), order_index=next_order, offset=-1, end=-1)
    entries = list(row.entries)
    entries.insert(int(position), fresh)
    return _renumbered(row, entries)


def remove_stock_entry(row: StoreRow, item_key: int) -> StoreRow:
    """Drop the single entry stocking `item_key`, renumbering and recounting the rest."""

    matches = row.entries_for(item_key)
    if len(matches) != 1:
        raise StoreInfoError(f"store {row.name!r} lists item {int(item_key)} {len(matches)} times; expected exactly one")
    return _renumbered(row, [entry for entry in row.entries if entry.item_key != int(item_key)])


def parse_store_table(payload: bytes, header: bytes) -> Tuple[StoreRow, ...]:
    """Every row of `storeinfo.pabgb`, in payload order."""

    table = parse_pabgh_table(header, payload=payload)
    return tuple(parse_store_row(payload[start:end], key=row.row_id) for row, start, end in table.row_spans(len(payload)))


def store_index(rows: Iterable[StoreRow]) -> Mapping[str, StoreRow]:
    """internal name -> row."""

    return {row.name: row for row in rows}


def apply_store_row(payload: bytes, header: bytes, row: StoreRow) -> Tuple[bytes, bytes]:
    """Write `row` back into the table pair, shifting later rows if its size changed."""

    return replace_table_row(payload, header, row.key, encode_store_row(row))


__all__ = [
    "STOREINFO_HEADER_PATH",
    "STOREINFO_PAYLOAD_PATH",
    "StockEntry",
    "StoreInfoError",
    "StoreRow",
    "apply_store_row",
    "encode_stock_entry",
    "encode_store_row",
    "insert_stock_entry",
    "parse_store_row",
    "parse_store_table",
    "remove_stock_entry",
    "store_index",
    "swap_stock_item",
]
