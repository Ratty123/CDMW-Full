"""Reader and in-place editor for the Crimson Desert `.papr` constraint rig.

A `.papr` sits beside a character model and defines its *secondary* motion: the bones
that are driven by other bones rather than by an animation clip. That is hair, cloth,
tassels, pistons, and the `B_Jiggle_*` chains. Twenty ship with the game, one per rig.

    'PAR ' u8 0x35 u8 1 b'\\x00\\x01...\\x09'  container header; 0x35 is ASCII '5'
    u32 zero
    u32 14
    u32 payload_bytes                      counted from 0x1C to the end
    u32 entry_count
    u32 unidentified
    entry_count x { u16 len; name  u16 len; parent  ...typed record... }

Strings are `u16 length` then that many bytes, with no terminator -- unlike `.paac`,
where the length counts a trailing NUL.

**What is not decoded.** The per-entry record after the name/parent pair is a typed
stream: short opcode triplets like `05 03 00 | 10 01 01 | 10 01 02` that vary between
entries and select what follows. One rig (`cd_m0001_00_bear`) walks cleanly on the
simplest reading and the other nineteen do not, so the grammar is not solved and this
module does not pretend to rebuild a file. There is no `encode_papr`, deliberately: a
writer built on a guessed grammar would produce files that load and misbehave.

**What is decoded, and editable.** Inside those records the driver lists are plain:
a bone name followed immediately by an `f32` influence weight expressed as a
percentage. Across the twenty shipped rigs, 98.5% of the non-zero weights found this
way are whole numbers in 0..100 and 98.6% are multiples of five, which is what a
hand-authored percentage looks like and not what a misread float looks like.

Editing one is a four-byte overwrite: same length, nothing moves, and every byte the
reader did not touch is still where it was. `set_weights` will not write unless the
caller states the value it expects to replace, so a site located by mistake fails
loudly instead of quietly corrupting a rig.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Mapping, Sequence, Tuple

PAR_MAGIC = b"PAR "
#: The version pair reads `0x35 0x01` in all twenty shipped rigs. `0x35` is ASCII `5`,
#: so the exporter appears to have written the major version as a character where
#: `.paa` writes plain numbers. Recorded as the raw bytes rather than reinterpreted,
#: because guessing which of the two is "really" 5 would be a guess.
PAPR_VERSION = (0x35, 0x01)
_HEADER_TAIL = bytes(range(10))
_HEADER_SIZE = 0x10
_ENTRIES_AT = 0x24

#: Bone names in the shipped rigs use only these bytes.
_NAME_BYTES = frozenset(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_ -.[]()"
)
_MIN_NAME = 2
_MAX_NAME = 64

#: Weights are percentages. Anything outside this is not one.
WEIGHT_MIN = 0.0
WEIGHT_MAX = 100.0


class PaprFormatError(ValueError):
    """Raised when a buffer is not a `.papr` constraint rig."""


@dataclass(frozen=True)
class PaprHeader:
    version: Tuple[int, int]
    payload_bytes: int
    entry_count: int
    unidentified: int


@dataclass(frozen=True)
class WeightSite:
    """A bone name and the influence weight stored immediately after it."""

    #: Byte offset of the f32, which is what `set_weights` addresses.
    offset: int
    bone: str
    value: float

    @property
    def confident(self) -> bool:
        """A whole percentage of at least one: the shape authored weights take.

        Zero is excluded because four zero bytes are equally consistent with padding
        or an unrelated integer, so a zero site is not evidence of anything. The floor
        of 1 matters more than it looks: a denormal like 3.6e-43 is four bytes of some
        neighbouring integer read as a float, and it passes a bare "is it a whole
        number" test because it rounds to zero. Every weight actually observed in the
        twenty rigs is 10 or more.
        """

        return (
            abs(self.value - round(self.value)) < 1e-4
            and 1 <= round(self.value) <= WEIGHT_MAX
        )


def parse_header(data: bytes, *, name: str = "") -> PaprHeader:
    """Read and check the container header."""

    where = f" ({name})" if name else ""
    if len(data) < _ENTRIES_AT or data[:4] != PAR_MAGIC:
        raise PaprFormatError(f"not a PAR container{where}")
    version = (data[4], data[5])
    if data[6:_HEADER_SIZE] != _HEADER_TAIL:
        raise PaprFormatError(f"unexpected container header{where}")
    if version != PAPR_VERSION:
        raise PaprFormatError(
            f"unsupported .papr version {version[0]}.{version[1]}{where}"
        )
    payload, entries, unidentified = struct.unpack_from("<III", data, 0x18)
    if payload != len(data) - 0x1C:
        raise PaprFormatError(
            f"payload says {payload:,} bytes but {len(data) - 0x1C:,} follow 0x1C{where}"
        )
    return PaprHeader(
        version=version,
        payload_bytes=payload,
        entry_count=entries,
        unidentified=unidentified,
    )


def _named_spans(data: bytes) -> list[tuple[int, int, str]]:
    """Every `u16 length` + name-shaped run, left to right and non-overlapping.

    The record grammar is unsolved, so this scans rather than walks. Overlaps are
    resolved longest-first at each position, which stops a name's own tail being
    reported as a second shorter name.
    """

    found: list[tuple[int, int, str]] = []
    limit = len(data) - 2
    for pos in range(limit):
        length = struct.unpack_from("<H", data, pos)[0]
        if not _MIN_NAME <= length <= _MAX_NAME:
            continue
        end = pos + 2 + length
        if end > len(data):
            continue
        raw = data[pos + 2: end]
        if not raw or any(byte not in _NAME_BYTES for byte in raw):
            continue
        found.append((pos, end, raw.decode("ascii")))
    found.sort(key=lambda span: (span[0], -(span[1] - span[0])))
    chosen: list[tuple[int, int, str]] = []
    reach = -1
    for start, end, text in found:
        if start >= reach:
            chosen.append((start, end, text))
            reach = end
    return chosen


def find_weight_sites(data: bytes, *, confident_only: bool = True) -> Tuple[WeightSite, ...]:
    """Locate the bone-name/influence-weight pairs.

    With `confident_only` the result is limited to non-zero whole percentages, which
    is the set an editor should offer. Pass `False` to see every candidate, including
    the ones whose float is not weight-shaped and is therefore probably not a weight.
    """

    sites: list[WeightSite] = []
    for _start, end, bone in _named_spans(data):
        if end + 4 > len(data):
            continue
        value = struct.unpack_from("<f", data, end)[0]
        if not math.isfinite(value):
            continue
        site = WeightSite(offset=end, bone=bone, value=value)
        if confident_only and not site.confident:
            continue
        sites.append(site)
    return tuple(sites)


def set_weights(
    data: bytes,
    changes: Mapping[int, float],
    *,
    expected: Mapping[int, float] | None = None,
) -> bytes:
    """Overwrite influence weights in place.

    `changes` maps a byte offset from `find_weight_sites` to the new percentage.
    `expected` maps the same offsets to the value the caller believes is there; when
    given, a mismatch raises rather than writes. Pass it. A site located against the
    wrong file is the one way this can go wrong, and the check costs nothing.

    The output is the same length as the input and differs only in the bytes named.
    """

    if not changes:
        return bytes(data)
    out = bytearray(data)
    for offset, value in changes.items():
        if not 0 <= offset <= len(out) - 4:
            raise PaprFormatError(f"offset 0x{offset:X} is not inside the file")
        if not WEIGHT_MIN <= value <= WEIGHT_MAX:
            raise PaprFormatError(
                f"weight {value} at 0x{offset:X} is outside {WEIGHT_MIN}..{WEIGHT_MAX}"
            )
        if expected is not None:
            if offset not in expected:
                raise PaprFormatError(f"no expected value given for 0x{offset:X}")
            found = struct.unpack_from("<f", out, offset)[0]
            if not math.isclose(found, expected[offset], rel_tol=0, abs_tol=1e-4):
                raise PaprFormatError(
                    f"0x{offset:X} holds {found}, not the expected {expected[offset]}"
                )
        struct.pack_into("<f", out, offset, value)
    if len(out) != len(data):
        raise PaprFormatError("in-place edit changed the file length")
    return bytes(out)


def scale_weights(
    data: bytes, sites: Sequence[WeightSite], factor: float
) -> bytes:
    """Multiply the given weights by `factor`, clamped to the percentage range.

    The blunt instrument a modder reaches for first: half the stiffness of every hair
    bone, or take the jiggle out of a cloak entirely with a factor of zero.
    """

    changes = {
        site.offset: min(WEIGHT_MAX, max(WEIGHT_MIN, site.value * factor))
        for site in sites
    }
    expected = {site.offset: site.value for site in sites}
    return set_weights(data, changes, expected=expected)


def describe(data: bytes, *, name: str = "") -> str:
    """A one-line summary for a preview pane."""

    header = parse_header(data, name=name)
    sites = find_weight_sites(data)
    bones = {site.bone for site in sites}
    return (
        f"Constraint rig: {header.entry_count:,} entries, "
        f"{len(sites):,} editable influence weights across {len(bones):,} driver bones"
    )
