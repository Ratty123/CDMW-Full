"""`multichangeinfo.pabgb`: enhancement (and crafting) transition rows, and how to clone them.

An item's `_multiChangeInfoList` is a `u32 count` plus that many u32 keys inside its
ItemInfo row; each key names a row here. Measured on the shipped table (18,540 rows,
2026-08-17): a row is `u32 key, u32 len, name, NUL, ...` and the enhancement rows are
named `<item internal name>_<level>`, one per step, and carry the item's own key 24
bytes after the name's NUL (17,032 of the 17,831 rows named that way; the rest are
crafting recipes whose result differs from the name). Ziane's sword lists fourteen
such rows, `Ziane_OneHandSword_0..13`, and no other sword references them.

A clone that shares the template's rows enhances through rows that name the template
(the form the in-game-verified spike shipped); a clone with rows of its own gets each
row copied under a new key and name with the item key repointed. Everything else in a
row (materials, conditions, the recipe description's localisation key) is carried
opaque. Cloned rows are unproven in game.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence, Tuple

from cdmw.core.iteminfo_row import ItemInfoRow
from cdmw.core.structured_binary_editor import append_table_rows, parse_pabgh_table

MULTICHANGEINFO_PAYLOAD_PATH = "gamedata/binary__/client/bin/multichangeinfo.pabgb"
MULTICHANGEINFO_HEADER_PATH = "gamedata/binary__/client/bin/multichangeinfo.pabgh"
DEFAULT_MULTICHANGE_KEY_RANGE = range(1_990_000, 2_000_000)

_ITEM_AFTER_NAME = 24


class MultiChangeError(ValueError):
    """Raised when a row does not read as a transition row, or a clone is refused."""


@dataclass(frozen=True, slots=True)
class MultiChangeRow:
    raw: bytes
    key: int
    name: str
    #: The item key 24 bytes after the name's NUL; None when the bytes are not there.
    item_key: Optional[int]

    @property
    def name_end(self) -> int:
        return 8 + len(self.name.encode("utf-8")) + 1

    @property
    def level_suffix(self) -> Optional[int]:
        _base, _sep, tail = self.name.rpartition("_")
        return int(tail) if _sep and tail.isdigit() else None


def parse_multichange_row(raw: bytes, *, key: Optional[int] = None) -> MultiChangeRow:
    data = bytes(raw)
    if len(data) < 9:
        raise MultiChangeError("row is too short for a key and a name")
    row_key, length = struct.unpack_from("<II", data, 0)
    if key is not None and int(key) != row_key:
        raise MultiChangeError(f"row key {row_key} does not match the directory key {int(key)}")
    if 8 + length + 1 > len(data) or data[8 + length] != 0:
        raise MultiChangeError(f"multichange {row_key}: the name is not NUL-terminated where its length says")
    name = data[8:8 + length].decode("utf-8", "replace")
    at = 8 + length + 1 + _ITEM_AFTER_NAME
    item = struct.unpack_from("<I", data, at)[0] if at + 4 <= len(data) else None
    return MultiChangeRow(raw=data, key=row_key, name=name, item_key=item)


def parse_multichange_table(payload: bytes, header: bytes) -> Tuple[MultiChangeRow, ...]:
    table = parse_pabgh_table(header, payload=payload)
    return tuple(parse_multichange_row(payload[s:e], key=row.row_id) for row, s, e in table.row_spans(len(payload)))


def find_multichange_keys(row: ItemInfoRow, known_keys: Iterable[int]) -> Tuple[int, ...]:
    """The keys of the item's `_multiChangeInfoList`: a u32 count followed by that many known keys.

    The list sits after the model stem hashes, before the stat block; it is found by
    its own shape rather than at a fixed offset, so a row with no list yields ().
    """

    known = set(int(k) for k in known_keys)
    raw = row.raw
    stop = row.stat_block_offset if row.stat_block_offset is not None else len(raw)
    best: Tuple[int, ...] = ()
    for offset in range(row.prefix_end, stop - 7):
        count = struct.unpack_from("<I", raw, offset)[0]
        if not 1 <= count <= 64 or offset + 4 + 4 * count > stop:
            continue
        values = struct.unpack_from(f"<{count}I", raw, offset + 4)
        if all(value in known for value in values) and count > len(best):
            best = tuple(values)
    return best


def transition_rows_for(rows: Mapping[int, MultiChangeRow], keys: Sequence[int], item_key: int) -> Tuple[MultiChangeRow, ...]:
    """The listed rows that name `item_key` 24 bytes after their name: the item's own enhancement steps."""

    out = []
    for key in keys:
        row = rows.get(int(key))
        if row is not None and row.item_key == int(item_key):
            out.append(row)
    return tuple(out)


def clone_multichange_row(row: MultiChangeRow, *, key: int, name: str, item_key: int) -> bytes:
    """The row under a new key and name, pointing at `item_key`; every other byte kept."""

    if not 0 < int(key) <= 0xFFFFFFFF:
        raise MultiChangeError("the new key must be a positive u32")
    if row.item_key is None:
        raise MultiChangeError(f"multichange {row.key} ({row.name}) has no item key to repoint")
    encoded = str(name or "").encode("utf-8")
    if not encoded or len(encoded) > 255:
        raise MultiChangeError("the new name must be 1..255 bytes")
    rest = bytearray(row.raw[row.name_end:])
    struct.pack_into("<I", rest, _ITEM_AFTER_NAME, int(item_key))
    return struct.pack("<II", int(key), len(encoded)) + encoded + b"\x00" + bytes(rest)


def allocate_multichange_keys(used: Iterable[int], count: int, *, key_range: range = DEFAULT_MULTICHANGE_KEY_RANGE) -> Tuple[int, ...]:
    taken = set(int(k) for k in used)
    out = []
    if int(count) <= 0:
        return ()
    for candidate in key_range:
        if candidate not in taken:
            out.append(candidate)
            if len(out) == int(count):
                return tuple(out)
    raise MultiChangeError(f"no {count} free multichange keys in {key_range.start}..{key_range.stop - 1}")


def clone_transition_rows(
    payload: bytes,
    header: bytes,
    rows: Sequence[MultiChangeRow],
    *,
    new_item_key: int,
    new_item_name: str,
    new_keys: Sequence[int],
) -> Tuple[bytes, bytes, Mapping[int, int]]:
    """Append clones of `rows` for a new item; return (payload, header, old key -> new key)."""

    if len(new_keys) != len(rows):
        raise MultiChangeError("one new key per transition row")
    mapping = {}
    encoded = []
    for row, key in zip(rows, new_keys):
        suffix = row.level_suffix
        name = f"{new_item_name}_{suffix}" if suffix is not None else f"{new_item_name}_{row.name.rsplit('_', 1)[-1]}"
        encoded.append(clone_multichange_row(row, key=int(key), name=name, item_key=int(new_item_key)))
        mapping[row.key] = int(key)
    payload, header = append_table_rows(payload, header, encoded)
    return payload, header, mapping


__all__ = [
    "DEFAULT_MULTICHANGE_KEY_RANGE",
    "MULTICHANGEINFO_HEADER_PATH",
    "MULTICHANGEINFO_PAYLOAD_PATH",
    "MultiChangeError",
    "MultiChangeRow",
    "allocate_multichange_keys",
    "clone_multichange_row",
    "clone_transition_rows",
    "find_multichange_keys",
    "parse_multichange_row",
    "parse_multichange_table",
    "transition_rows_for",
]
