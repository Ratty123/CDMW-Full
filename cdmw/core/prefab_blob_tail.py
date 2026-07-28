"""How a ``.prefab`` data blob closes.

Deciding "is there anything left to read" is the most consequential judgement
the decoder makes, because a walk that recovered every object but cannot close
is reported *partial*, and partial switches editing off.

## What the tail actually is

It is not padding and there is no separate trailer grammar. Measured over the
799 completed walks whose blob ends ``<u32> 01``, **every single one** of those
trailing u32s is a *pointee length field* -- the same field ``_read_pointer``
consumes and validates in the middle of the file, where it must equal the
pointee's byte count::

    length == field_position - pointee_start        (blob-relative)

The controls are what make that convincing: matching against ``v + 1`` or
``v - 1`` explains 0 of 799, and taking each file's value and testing it against
a *different* file's pointers explains 3.3%. The relationship is exact, not a
coincidence of small numbers.

So the walk systematically stops a few bytes early, leaving one or more real
length fields plus the one-byte ``01`` terminator. The bytes were never
mysterious; they were simply unread.

## Why this file used to be four heuristics

Earlier versions grew a tolerance: a 5-or-6 byte footer, then a *run* of records
opening ``01``, then a 6-byte record width, then a footer permitted before the
run. Each step was justified by corpus measurement and each bought completions.

All of it was reading the same repeating structure through an off-by-one frame.
``<u32 length> 01`` repeated looks exactly like ``01 <u32>`` repeated if you
start one byte later, which is why ``01 01 25 00 00 00 01 70 00 00 00`` parsed
two different ways with nothing to choose between them. Tolerating both is what
a rule does when it does not know what it is looking at.

The tolerant version also could not be validated. Widening it never changed the
decoded prefix -- only the verdict -- so "the same objects came back" was
guaranteed in advance and proved nothing about whether the newly accepted bytes
were understood.

This version explains every byte instead, and scores better for it: 926
completions against the tolerant rule's 922, over the same 1,500 files.
"""

from __future__ import annotations

import struct

#: The one-byte terminator, and the marker separating closing length fields.
TERMINATOR = 0x01


def pointee_starts(blob: bytes, base: int) -> frozenset[int]:
    """Blob-relative offsets at which a pointee begins.

    A pointer is identified by the exact identity the rest of the decoder uses
    -- a u32 at ``k`` holding ``base + k + 4`` -- and its pointee starts at the
    byte just past it. Derived from the blob rather than passed in, so the close
    rule cannot be handed a stale set.
    """
    found = set()
    for offset in range(max(0, len(blob) - 3)):
        if struct.unpack_from("<I", blob, offset)[0] == base + offset + 4:
            found.add(offset + 4)
    return frozenset(found)


def closes_blob(blob: bytes, at: int, starts: frozenset[int]) -> bool:
    """Is everything from ``at`` to the end an unread close, rather than data?

    The residual must consist entirely of ``01`` terminator bytes and u32 length
    fields, each of which has to equal its own distance from a real pointee
    start. A byte that is neither fails the whole tail.

    This is a validation, not a tolerance: there is no spare-byte allowance and
    no footer of unexplained width, because every byte now has something to be.
    """
    if at >= len(blob):
        return False
    position = at
    while position < len(blob):
        if blob[position] == TERMINATOR:
            position += 1
            continue
        if position + 4 > len(blob):
            return False
        length = struct.unpack_from("<I", blob, position)[0]
        if position - length not in starts:
            return False
        position += 4
    return True


__all__ = ["TERMINATOR", "pointee_starts", "closes_blob"]
