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
    03   04    driver list       who this bone follows, and by how much
    04   04    driver list       same shape, second group
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

**1,857 of 2,541 blocks (73.1%) consume exactly**, against 682 (26.8%) for the single
canonical shape this replaces. Two independent checks keep that honest:

* A block must be consumed to its final byte. The grammar has no per-block free
  parameters, so landing exactly on 1,857 block boundaries is not something arbitrary
  rules do.
* `record_count` in the header is the total record count across every block. Where every
  block in a rig decodes -- `cd_m0001_00_bear` -- the walk reproduces it exactly (12).

The remaining 684 blocks stop at a handful of distinct constructs, chiefly a `09 03`
record and the piston chains in the machine rigs. `decode_block` reports where it stopped
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
_DRIVERS = frozenset({(0x03, 0x04), (0x04, 0x04)})
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


def _read_driver_group(block: bytes, at: int, channels: int) -> tuple[DriverGroup, int]:
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
    span = 4 * (_BASE_LIMITS + channels)
    if at + span > len(block):
        raise PaprBlockError(f"{span} bytes of limits run past the block", at)
    limits = struct.unpack_from(f"<{_BASE_LIMITS + channels}f", block, at)
    return DriverGroup(drivers=tuple(drivers), limits=tuple(limits)), at + span


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
            if pair in _DRIVERS:
                group, at = _read_driver_group(block, at, channels)
                groups.append(group)
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
