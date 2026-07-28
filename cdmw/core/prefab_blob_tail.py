"""How a ``.prefab`` data blob closes.

Split from :mod:`cdmw.core.prefab_binary` because deciding "is there anything
left to read" turned into three rules, and because getting it wrong is the
single most consequential judgement the decoder makes: a walk that recovered
every object but cannot close is reported as *partial*, which switches editing
off. Several of these files had already been read correctly and were being
refused on the last nine bytes.

The tail is, in the general case:

    tail := footer? trailer-record+ terminator?

* A **trailer record** opens with ``01`` and is 5 or 6 bytes wide. The width
  follows the component family, the same way the pointer-record footer search
  does. Reading only the five-byte form left 28 files in 1,500 stopping exactly
  seven bytes short on ``01 01 06 00 00 00 01``.
* A **footer** of 1 to 6 bytes may precede the run. Observed widths are 1, 2 and
  4 -- zero padding, or a four-byte field such as ``5c 00 00 00`` -- and
  allowing it completes 16 more files, every one of which had *already*
  recovered all of its objects. The object counts before and after are
  identical; only the verdict changes.
* At most one spare byte is tolerated at the very end.

The safety of all this rests on **exact consumption**: from wherever the run is
judged to start, every remaining byte has to be part of a record. That is what
stops a tail rule from closing a walk that is merely lost, and it is why the
footer tolerance can be as wide as six bytes without the rule becoming a way to
say yes to anything.
"""

from __future__ import annotations

#: Trailer record widths, narrow first.
TRAILER_WIDTHS = (5, 6)
#: Footer widths tried before the run. 1, 2 and 4 are attested.
FOOTER_WIDTHS = (1, 2, 3, 4, 5, 6)
#: The only six-byte record the corpus contains. Matched exactly, unlike the
#: five-byte form, whose u32 payload genuinely varies across shipped files.
#:
#: Accepting "``01`` then five bytes" instead would let the width absorb one
#: arbitrary byte per record, and combined with the footer skip that is enough
#: to close on trailing garbage -- ``5c 00 00 00 01 de 00 00 00 99 99`` reads as
#: a four-byte footer, a six-byte record and a spare byte. A second six-byte
#: record showing up later will surface as a partial walk, which is the safe
#: direction to be wrong in.
SIX_BYTE_RECORD = bytes.fromhex("01 01 06 00 00 00")


def is_trailer_run_of(blob: bytes, at: int, width: int) -> bool:
    """A run of ``width``-byte records from ``at``, consuming all but a byte."""
    pos = at
    seen = 0
    while pos + width <= len(blob):
        if width == 6:
            if blob[pos : pos + 6] != SIX_BYTE_RECORD:
                return False
        elif blob[pos] != 1:
            return False
        pos += width
        seen += 1
    return seen > 0 and len(blob) - pos <= 1


def is_trailer_run(blob: bytes, at: int) -> bool:
    """Is everything from ``at`` to the end a run of trailer records?"""
    return any(is_trailer_run_of(blob, at, width) for width in TRAILER_WIDTHS)


def closes_blob(blob: bytes, at: int) -> bool:
    """Is everything from ``at`` to the end a closing tail rather than data?

    A footer is only considered when the bytes do not already open a record --
    otherwise this would just be the run rule with extra chances, and a genuine
    record could be re-read as footer plus a shorter run.
    """
    if is_trailer_run(blob, at):
        return True
    if at < len(blob) and blob[at] == 1:
        return False
    return any(
        at + skip < len(blob) and is_trailer_run(blob, at + skip)
        for skip in FOOTER_WIDTHS
    )


__all__ = ["TRAILER_WIDTHS", "FOOTER_WIDTHS", "is_trailer_run_of", "is_trailer_run", "closes_blob"]
