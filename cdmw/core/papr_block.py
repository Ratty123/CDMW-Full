"""Decoder for the `.papr` configuration block -- the part that says *how* a bone follows.

`papr_format` finds each block's exact extent and carries the bytes verbatim. This module
reads what is inside one. It is strictly read-only: nothing here is used to write a file,
so a construct we misread cannot corrupt anything.

## The grammar

A block is a flat stream of 3-byte `(tag, type, value)` records. Type says whether a
payload follows and how long it is; tag says what the payload means.

    tag  type  payload
    05   03    -                 opens the block
    07   05    -                 closes it
    10   01    -                 scalar; the value is the record's third byte
    06   04    -                 member marker
    0a   04    2 bytes           channel count in the high byte -- see below
    03   04    driver list       who this bone follows, by how much, plus limits
    04   04    driver list       the same list with no limits after it
    12   01    string            a plain name reference
    11   01    expression        a 3ds Max expression controller, below

    driver list:
        u8 count
        count x (u16 len, ASCII name, f32 weight)
        u8 0x00                              sentinel
        (4 + channels) x f32                 limits; `channels` comes from the last 0a-04

    expression:
        u16 len, ASCII name, u8 0x00         the node the expression is bound to
        u16 count                            variables
        count x (u8 kind, u16 len, ASCII name, u8 0x00)
        u8 0x00                              end of the variable table
        u16 len, ASCII text                  the expression itself

## What this recovers, and why it is worth having

The expression payload is the actual rule the rig runs. 1,148 of them decode across the
corpus, and they read like what they are -- MAXScript float-expression controllers:

    -Local_Euler_Z*3+30.5
    amin(Local_Euler_Z*5.5+20) 8
    amin((Local_Euler_Z*0.1)+0.20-3.141592) -3.141592

A modder reading "Bip01 L Knee_back follows Bip01 L Calf" learns much less than one
reading "at three times its Z rotation, offset 30.5 degrees, clamped at 8".

## How far it gets, and how that is known

**2,441 of 2,541 blocks (96.1%) consume exactly**, against 682 (26.8%) for the single
canonical shape this replaces. Two independent checks keep that honest:

* A block must be consumed to its final byte. The grammar has no per-block free
  parameters, so landing exactly on 1,857 block boundaries is not something arbitrary
  rules do.
* `record_count` in the header is the total record count across every block, and nothing
  in this grammar can influence it. All four rigs that decode end to end reproduce their
  declared total exactly: bear 12, deerila 324, golemhorse 377, horse 353. That check is
  also what settled the bound-node question -- counted as records, the last three overshot
  by 6, 11 and 11, which is precisely how many bound nodes they hold.

The remaining 100 blocks stop at four constructs. `09 03` (56 blocks) is a record whose
payload is not any shape here. The other three are all places where a byte this grammar
expects to be zero is not: a bound node followed by `01` (37), a `01 03` frame followed by
a count (3), and one zero-length string. Those three look like the same missing idea --
that several of these payloads begin with a count rather than a fixed zero, and the decoded
forms are simply the count-is-one case -- but the shapes that would confirm it have not
been pinned down, so they fail loudly instead. `decode_block` reports where it stopped
rather than guessing past it, and `BlockDecode.complete` is False for those.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Tuple

#: Bytes an in-block string may contain. Expression text uses operators and digits, so
#: this is far wider than the bone-name set `papr_format` scans entry headers with.
_PRINTABLE = frozenset(range(0x20, 0x7F))
_MAX_STRING = 160
_MAX_DRIVERS = 16
_MAX_VARIABLES = 32

#: Records with no payload at all.
_FREE_RECORDS = frozenset({(0x05, 0x03), (0x07, 0x05), (0x10, 0x01), (0x06, 0x04)})
_CHANNELS = (0x0A, 0x04)
#: Takes a driver list *and* the limits after it.
_DRIVERS_WITH_LIMITS = (0x03, 0x04)
#: Takes the list only. Reading limits here swallowed the records that follow.
_DRIVERS_ONLY = (0x04, 0x04)
#: Continuations of the driver payload: a bound node and its own limits. Not records --
#: the header's `record_count` is what settles that. Counted as records, deerila overshoots
#: its declared total by 6 and the two horse rigs by 11, which is exactly how many of these
#: they hold; not counted, all three land exactly.
#:
#: The split is by tag, not by shape: tags 1 to 5 with type 1 or 2 are bound nodes, while
#: 0x10, 0x11 and 0x12 at the same types are real records (a scalar, an expression and a
#: name). Reading only the two forms first observed left 452 blocks short for want of
#: `02 01` and `02 02`, which carry the identical zero-name-limits payload.
_BOUND_NODES = frozenset(
    (tag, typ) for tag in range(0x01, 0x06) for typ in (0x01, 0x02)
)
#: A bare frame: one zero byte then three floats.
_FRAME = (0x01, 0x03)
_FRAME_FLOATS = 3
_EXPRESSION = (0x11, 0x01)
_NAME_REF = (0x12, 0x01)
#: Limits after a driver list: four, plus one per channel the last `0a 04` declared.
_BASE_LIMITS = 4


class PaprBlockError(ValueError):
    """Raised when the block grammar does not fit. Carries how far it got."""

    def __init__(self, message: str, at: int) -> None:
        super().__init__(message)
        self.at = at


@dataclass(frozen=True)
class Driver:
    """One bone this entry follows, and its weight as a percentage."""

    name: str
    weight: float


@dataclass(frozen=True)
class DriverGroup:
    """A driver list plus the limits that follow it."""

    drivers: Tuple[Driver, ...]
    #: `(4 + channels)` floats. Read as radian limits; not interpreted further here.
    limits: Tuple[float, ...]


@dataclass(frozen=True)
class Expression:
    """A 3ds Max expression controller: what it reads, and the formula."""

    #: The node the controller is bound to, e.g. `Bip01 L Calf:1:2`.
    node: str
    #: `(kind, name)` per variable the expression may reference.
    variables: Tuple[Tuple[int, str], ...]
    #: The formula, e.g. `amin(Local_Euler_Z*5.5+20) 8`.
    text: str


@dataclass(frozen=True)
class BlockDecode:
    """What one block turned out to hold."""

    #: `(tag, type, value)` for every record, in order.
    records: Tuple[Tuple[int, int, int], ...] = ()
    groups: Tuple[DriverGroup, ...] = ()
    expressions: Tuple[Expression, ...] = ()
    names: Tuple[str, ...] = ()
    #: True when the walk reached the block's final byte with every rule satisfied.
    complete: bool = False
    #: Offset the walk stopped at, and why, when `complete` is False.
    stopped_at: int = 0
    note: str = ""

    @property
    def record_count(self) -> int:
        return len(self.records)

    @property
    def drivers(self) -> Tuple[Driver, ...]:
        return tuple(driver for group in self.groups for driver in group.drivers)


def _read_string(block: bytes, at: int) -> tuple[str, int]:
    if at + 2 > len(block):
        raise PaprBlockError("string length runs past the block", at)
    length = struct.unpack_from("<H", block, at)[0]
    if not 1 <= length <= _MAX_STRING or at + 2 + length > len(block):
        raise PaprBlockError(f"implausible string length {length}", at)
    raw = block[at + 2 : at + 2 + length]
    if not all(byte in _PRINTABLE for byte in raw):
        raise PaprBlockError("string is not printable ASCII", at)
    return raw.decode("ascii"), at + 2 + length


def _read_zero(block: bytes, at: int, what: str) -> int:
    if at >= len(block) or block[at] != 0:
        raise PaprBlockError(f"expected a zero byte after {what}", at)
    return at + 1


def _read_bound_node(block: bytes, at: int, channels: int) -> tuple[str, int]:
    """A zero byte, the node this follows, then the same limit run a driver list takes."""

    at = _read_zero(block, at, "a bound node")
    name, at = _read_string(block, at)
    span = 4 * (_BASE_LIMITS + channels)
    if at + span > len(block):
        raise PaprBlockError(f"{span} bytes of bound-node limits run past the block", at)
    return name, at + span


def _read_driver_group(
    block: bytes, at: int, channels: int, *, limits: bool = True
) -> tuple[DriverGroup, int]:
    if at >= len(block):
        raise PaprBlockError("driver count runs past the block", at)
    count = block[at]
    if not 1 <= count <= _MAX_DRIVERS:
        raise PaprBlockError(f"implausible driver count {count}", at)
    at += 1
    drivers = []
    for _ in range(count):
        name, at = _read_string(block, at)
        if at + 4 > len(block):
            raise PaprBlockError("driver weight runs past the block", at)
        weight = struct.unpack_from("<f", block, at)[0]
        at += 4
        drivers.append(Driver(name=name, weight=weight))
    at = _read_zero(block, at, "the driver list")
    if not limits:
        return DriverGroup(drivers=tuple(drivers), limits=()), at
    span = 4 * (_BASE_LIMITS + channels)
    if at + span > len(block):
        raise PaprBlockError(f"{span} bytes of limits run past the block", at)
    values = struct.unpack_from(f"<{_BASE_LIMITS + channels}f", block, at)
    return DriverGroup(drivers=tuple(drivers), limits=tuple(values)), at + span


def _read_expression(block: bytes, at: int) -> tuple[Expression, int]:
    node, at = _read_string(block, at)
    at = _read_zero(block, at, "the expression's node")
    if at + 2 > len(block):
        raise PaprBlockError("variable count runs past the block", at)
    count = struct.unpack_from("<H", block, at)[0]
    at += 2
    if count > _MAX_VARIABLES:
        raise PaprBlockError(f"implausible variable count {count}", at)
    variables = []
    for _ in range(count):
        if at >= len(block):
            raise PaprBlockError("variable kind runs past the block", at)
        kind = block[at]
        at += 1
        name, at = _read_string(block, at)
        at = _read_zero(block, at, "a variable name")
        variables.append((kind, name))
    at = _read_zero(block, at, "the variable table")
    text, at = _read_string(block, at)
    return Expression(node=node, variables=tuple(variables), text=text), at


def decode_block(block: bytes) -> BlockDecode:
    """Read one block. Never raises: an unfitting block comes back `complete=False`."""

    records: list[tuple[int, int, int]] = []
    groups: list[DriverGroup] = []
    expressions: list[Expression] = []
    names: list[str] = []
    channels = 0
    at = 0
    try:
        while at < len(block):
            if at + 3 > len(block):
                raise PaprBlockError("trailing bytes shorter than a record", at)
            record = (block[at], block[at + 1], block[at + 2])
            pair = (record[0], record[1])
            at += 3
            if pair in _BOUND_NODES:
                # Payload, not a record: see `_BOUND_NODES`.
                name, at = _read_bound_node(block, at, channels)
                names.append(name)
                continue
            records.append(record)
            if pair in _FREE_RECORDS:
                continue
            if pair == _CHANNELS:
                if at + 2 > len(block):
                    raise PaprBlockError("channel payload runs past the block", at)
                # Low byte is zero throughout the corpus; the high byte is the count.
                channels = block[at + 1]
                at += 2
                continue
            if pair in (_DRIVERS_WITH_LIMITS, _DRIVERS_ONLY):
                group, at = _read_driver_group(
                    block, at, channels, limits=pair == _DRIVERS_WITH_LIMITS
                )
                groups.append(group)
                continue
            if pair == _FRAME:
                at = _read_zero(block, at, "a frame")
                if at + 4 * _FRAME_FLOATS > len(block):
                    raise PaprBlockError("frame floats run past the block", at)
                at += 4 * _FRAME_FLOATS
                continue
            if pair == _EXPRESSION:
                expression, at = _read_expression(block, at)
                expressions.append(expression)
                continue
            if pair == _NAME_REF:
                name, at = _read_string(block, at)
                names.append(name)
                continue
            raise PaprBlockError(
                f"no payload rule for tag 0x{record[0]:02x} type 0x{record[1]:02x}", at - 3
            )
    except PaprBlockError as error:
        return BlockDecode(
            records=tuple(records),
            groups=tuple(groups),
            expressions=tuple(expressions),
            names=tuple(names),
            complete=False,
            stopped_at=error.at,
            note=str(error),
        )
    return BlockDecode(
        records=tuple(records),
        groups=tuple(groups),
        expressions=tuple(expressions),
        names=tuple(names),
        complete=True,
    )
