"""`itemgroupinfo.pabgb` rows: which items belong to a group, and how to add one.

Measured on the shipped table (1,597 rows, 2026-08-17):

    u16 key, u32 len, name, NUL, `08 80 00 00 00`, u32 key again, u32 len2, len2 digits
    u32 subgroupCount, subgroupCount x u16 (keys of other item groups)
    u32 memberCount, memberCount x u32 (item keys)
    tail: u32 n, n x u8, u16, u8, u32, u32 (fifteen bytes plus n; carried opaque)

Every row round-trips byte for byte, and the walk lands on a tail whose length its
own leading count predicts in every row. Adding a member appends its key to the member list and bumps the count,
which is what the 2026-08-17 spike did in eleven groups before the game listed the
new items where their template was listed.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, replace
from typing import Iterable, Optional, Sequence, Tuple

from cdmw.core.structured_binary_editor import parse_pabgh_table, replace_table_row

ITEMGROUPINFO_PAYLOAD_PATH = "gamedata/binary__/client/bin/itemgroupinfo.pabgb"
ITEMGROUPINFO_HEADER_PATH = "gamedata/binary__/client/bin/itemgroupinfo.pabgh"

_TAG = bytes([0x08, 0x80, 0x00, 0x00, 0x00])
#: The tail is `u32 n, n x u8, u16, u8, u32, u32`: fifteen bytes plus n.
_TAIL_MIN = 15


class ItemGroupError(ValueError):
    """Raised when a row does not read as an item group, or an edit is refused."""


@dataclass(frozen=True, slots=True)
class ItemGroupRow:
    raw: bytes
    key: int
    name: str
    #: The bytes before the sub-group count: name, tag, repeated key, the digit string.
    prefix: bytes
    subgroups: Tuple[int, ...]
    members: Tuple[int, ...]
    tail: bytes

    @property
    def members_offset(self) -> int:
        return len(self.prefix) + 4 + 2 * len(self.subgroups) + 4


def parse_item_group_row(raw: bytes, *, key: Optional[int] = None, item_keys: Optional[Iterable[int]] = None) -> ItemGroupRow:
    """Decode one row. `item_keys`, when given, must contain every member."""

    data = bytes(raw)
    if len(data) < 6:
        raise ItemGroupError("row is too short for a key and a name length")
    row_key = struct.unpack_from("<H", data, 0)[0]
    if key is not None and int(key) != row_key:
        raise ItemGroupError(f"row key {row_key} does not match the directory key {int(key)}")
    length = struct.unpack_from("<I", data, 2)[0]
    pos = 6 + length
    if pos + 1 + len(_TAG) + 8 > len(data):
        raise ItemGroupError(f"item group {row_key}: the name runs past the row")
    name = data[6:pos].decode("utf-8", "replace")
    if data[pos] != 0 or data[pos + 1:pos + 1 + len(_TAG)] != _TAG:
        raise ItemGroupError(f"item group {name!r} ({row_key}): expected the NUL and 08 80 tag after the name")
    pos += 1 + len(_TAG)
    again, digits_length = struct.unpack_from("<II", data, pos)
    if again != row_key:
        raise ItemGroupError(f"item group {name!r} ({row_key}): the repeated key reads {again}")
    pos += 8 + digits_length
    if pos + 4 > len(data):
        raise ItemGroupError(f"item group {name!r} ({row_key}): the digit string runs past the row")
    prefix = data[:pos]
    subgroup_count = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    if pos + 2 * subgroup_count + 4 > len(data):
        raise ItemGroupError(f"item group {name!r} ({row_key}): {subgroup_count} sub-groups run past the row")
    subgroups = struct.unpack_from(f"<{subgroup_count}H", data, pos)
    pos += 2 * subgroup_count
    member_count = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    if pos + 4 * member_count > len(data):
        raise ItemGroupError(f"item group {name!r} ({row_key}): {member_count} members run past the row")
    members = struct.unpack_from(f"<{member_count}I", data, pos)
    pos += 4 * member_count
    tail = data[pos:]
    if len(tail) < _TAIL_MIN or len(tail) != _TAIL_MIN + struct.unpack_from("<I", tail, 0)[0]:
        raise ItemGroupError(
            f"item group {name!r} ({row_key}): {len(tail)} bytes follow the member list, "
            f"expected 15 plus the count the tail opens with"
        )
    if item_keys is not None:
        known = set(int(k) for k in item_keys)
        unknown = [m for m in members if m not in known]
        if unknown:
            raise ItemGroupError(f"item group {name!r} ({row_key}): {len(unknown)} member(s) are not item keys, e.g. {unknown[0]}")
    return ItemGroupRow(raw=data, key=row_key, name=name, prefix=prefix, subgroups=tuple(subgroups), members=tuple(members), tail=tail)


def encode_item_group_row(row: ItemGroupRow) -> bytes:
    out = bytearray(row.prefix)
    out += struct.pack("<I", len(row.subgroups))
    for sub in row.subgroups:
        out += struct.pack("<H", _u16(sub))
    out += struct.pack("<I", len(row.members))
    for member in row.members:
        out += struct.pack("<I", _u32(member))
    out += row.tail
    return bytes(out)


def _u16(value: int) -> int:
    value = int(value)
    if not 0 <= value <= 0xFFFF:
        raise ItemGroupError(f"{value} does not fit a u16")
    return value


def _u32(value: int) -> int:
    value = int(value)
    if not 0 <= value <= 0xFFFFFFFF:
        raise ItemGroupError(f"{value} does not fit a u32")
    return value


def add_group_members(row: ItemGroupRow, keys: Sequence[int], *, after: Optional[int] = None) -> ItemGroupRow:
    """The row with `keys` added, after member `after` when given, else at the end.

    A key the group already lists is refused, so a re-run cannot double a member.
    """

    additions = tuple(_u32(k) for k in keys)
    if not additions:
        return row
    present = [k for k in additions if k in row.members]
    if present:
        raise ItemGroupError(f"item group {row.name!r} already lists {present[0]}")
    if len(set(additions)) != len(additions):
        raise ItemGroupError("the same key is added twice")
    members = list(row.members)
    if after is None:
        members.extend(additions)
    else:
        if int(after) not in members:
            raise ItemGroupError(f"item group {row.name!r} does not list {int(after)}")
        index = members.index(int(after)) + 1
        members[index:index] = list(additions)
    updated = replace(row, members=tuple(members))
    return replace(updated, raw=encode_item_group_row(updated))


def parse_item_group_table(payload: bytes, header: bytes, *, item_keys: Optional[Iterable[int]] = None) -> Tuple[ItemGroupRow, ...]:
    """Every row of `itemgroupinfo.pabgb`, in payload order."""

    table = parse_pabgh_table(header, payload=payload)
    known = frozenset(int(k) for k in item_keys) if item_keys is not None else None
    return tuple(
        parse_item_group_row(payload[start:end], key=row.row_id, item_keys=known)
        for row, start, end in table.row_spans(len(payload))
    )


def groups_containing(rows: Iterable[ItemGroupRow], item_key: int) -> Tuple[ItemGroupRow, ...]:
    return tuple(row for row in rows if int(item_key) in row.members)


def apply_item_group_row(payload: bytes, header: bytes, row: ItemGroupRow) -> Tuple[bytes, bytes]:
    """Write `row` back into the table pair, shifting later rows by its growth."""

    return replace_table_row(payload, header, row.key, encode_item_group_row(row))


__all__ = [
    "ITEMGROUPINFO_HEADER_PATH",
    "ITEMGROUPINFO_PAYLOAD_PATH",
    "ItemGroupError",
    "ItemGroupRow",
    "add_group_members",
    "apply_item_group_row",
    "encode_item_group_row",
    "groups_containing",
    "parse_item_group_row",
    "parse_item_group_table",
]
