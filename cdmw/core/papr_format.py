"""Reader, writer, and editor for the Crimson Desert `.papr` constraint rig.

A `.papr` sits beside a character model and defines its *secondary* motion: the bones
driven by other bones rather than by an animation clip. That is hair, cloth, tassels,
pistons, and the `B_Jiggle_*` chains. Twenty ship with the game, one per rig.

    'PAR ' u8 0x35 u8 0x01 b'\\x00\\x01...\\x09'  container header; 0x35 is ASCII '5'
    u32 zero
    u32 14
    u32 payload_bytes                          counted from 0x1C to the end
    u32 entry_count
    u32 record_count                           total tag records across all blocks
    entry_count x entry

    entry:
        u16 len; name          the bone this entry configures
        u16 len; parent        the bone it hangs from
        u8 a  u8 b  u8 has_transform
        if has_transform: 10 x f32             scale[3], rotation[4], translation[3]
        u8 kind                                0 = nothing follows, otherwise a block
        block                                  tag-record stream, see below

Strings are `u16 length` then that many bytes with no terminator -- unlike `.paac`,
where the length counts a trailing NUL.

`record_count` at 0x20 is the total number of 3-byte tag records across every block.
It is an independent check on a parse: bear declares 12 and its two blocks hold six
records each; dog declares 30 and has five blocks of six.

## The block, and what is still opaque

Blocks are a stream of 3-byte `(tag, type, value)` records. Type `0x03` opens, type
`0x05` closes (`07 05 00` is the closing record), type `0x01` is a scalar, and type
`0x04` introduces a member. What is *known* about the payloads:

* `05 03 00` / `06 04 00` / `07 05 00` / `10 01 xx` carry no payload.
* `0a 04 00` is always followed by exactly two bytes, in all 1,084 occurrences.
* A driver list is `u8 count`, then that many `(u16 name, f32 weight)` pairs, then a
  `0x00` sentinel. It is introduced by `03 04 00` or `04 04 00`.
* The tag vocabulary across the corpus is `01 03 04 05 06 07 09 0a 10 11 12` against
  types `01 03 04 05`.

**26.8% of blocks (682 of 2,541) are one canonical 27-byte shape** -- `05 03 00`, three
`10 01 xx`, `06 04 00`, three `10 01 xx`, `07 05 00`, nine records exactly. Those are
fully understood and `block_shape` reports them as `canonical`.

The rest are not solved. The payload of a type-04 member depends on the member id, the
rules differ per id, and the schema that would say so is not in the file. Fitting the
remaining shapes against the corpus produces rules that consume 73% of block bytes and
are plainly overfitted (a `11 01` "string then ten floats then four bytes" is not a
struct anyone wrote), so none of that guesswork is in this module.

So this module does **not** interpret block contents. It finds each block's exact
extent and carries the bytes verbatim. That is enough for everything below, and it
means an edit can never corrupt a construct we do not understand.

`record_count` at 0x20 remains the oracle for whoever attacks this next: any candidate
grammar has to make the per-block record counts sum to it.

Block extents come from locating entry *starts* rather than block ends: a start is two
name-shaped strings followed by a tail whose third byte is 0 or 1, and the chain of
starts from 0x24 must be exactly `entry_count` long and tile the file. Searching for
the closing `07 05 00` instead does not work, because those three bytes also occur
inside float payloads and inside the expression strings some rigs carry
(`ExposeTransform_Bip01 R Forearm:5`, `-Local_Euler...`).

Nineteen of the twenty shipped rigs tile exactly. `cd_m0001_00_circusmachine_boss`
finds 236 starts against a declared 237 and is rejected rather than guessed at.

## What can be edited

Everything the entry header holds -- bone name, parent, the transform frame -- plus the
influence weights inside blocks. Names may change length: nothing in the format is
offset-addressed, and `payload_bytes` is recomputed on write.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, replace
from typing import Iterable, Mapping, Sequence, Tuple

PAR_MAGIC = b"PAR "
#: The version pair reads `0x35 0x01` in all twenty shipped rigs. `0x35` is ASCII `5`,
#: so the exporter appears to have written the major version as a character where
#: `.paa` writes plain numbers. Recorded as the raw bytes rather than reinterpreted.
PAPR_VERSION = (0x35, 0x01)
_HEADER_TAIL = bytes(range(10))
_HEADER_SIZE = 0x10
_ENTRIES_AT = 0x24
_PAYLOAD_FROM = 0x1C

#: Bone names in the shipped rigs use only these bytes. Block expression strings use
#: more (`:`, digits, operators), which is why the entry-start scan stays strict.
_NAME_BYTES = frozenset(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_ -.[]()"
)
_MIN_NAME = 1
_MAX_NAME = 64
#: The two counter bytes ahead of the transform flag never exceed this in the corpus.
_MAX_TAIL_COUNTER = 8

#: Weights are percentages. Anything outside this is not one.
WEIGHT_MIN = 0.0
WEIGHT_MAX = 100.0


class PaprFormatError(ValueError):
    """Raised when a buffer is not a `.papr` constraint rig this reader understands."""


#: The one block shape that is fully decoded: nine 3-byte records and nothing else.
#: `05 03 00`, three `10 01 xx`, `06 04 00`, three `10 01 xx`, `07 05 00`.
_CANONICAL_BLOCK_BYTES = 27


def is_canonical_block(block: bytes) -> bool:
    """True for the 9-record block shape whose every byte is accounted for."""

    if len(block) != _CANONICAL_BLOCK_BYTES:
        return False
    if block[0:3] != b"\x05\x03\x00" or block[12:15] != b"\x06\x04\x00":
        return False
    if block[24:27] != b"\x07\x05\x00":
        return False
    return all(block[at:at + 2] == b"\x10\x01" for at in (3, 6, 9, 15, 18, 21))


@dataclass(frozen=True)
class PaprHeader:
    version: Tuple[int, int]
    payload_bytes: int
    entry_count: int
    record_count: int
    #: The two words ahead of the payload length: zero and fourteen in every rig.
    leading: Tuple[int, int] = (0, 14)


@dataclass(frozen=True)
class ConstraintEntry:
    """One driven bone: what it is, what it hangs from, and how it is configured."""

    name: str
    parent: str
    #: `(a, b)` ahead of the transform flag. Small counters; not modelled.
    counters: Tuple[int, int]
    #: `scale[3], rotation[4], translation[3]`, or None when the entry omits it.
    transform: Tuple[float, ...] | None
    #: Zero when nothing follows the header.
    kind: int
    #: The tag-record stream, carried verbatim.
    block: bytes

    @property
    def driven(self) -> bool:
        """True when the entry carries a configuration block rather than just a link."""

        return bool(self.kind)

    @property
    def block_shape(self) -> str:
        """`none`, `canonical` for the fully understood 9-record form, else `opaque`.

        The UI uses this to say which entries are completely understood rather than
        implying the same confidence everywhere.
        """

        if not self.block:
            return "none"
        return "canonical" if is_canonical_block(self.block) else "opaque"


@dataclass(frozen=True)
class PaprDocument:
    header: PaprHeader
    entries: Tuple[ConstraintEntry, ...]

    def index(self) -> Mapping[str, ConstraintEntry]:
        return {entry.name: entry for entry in self.entries}

    def children_of(self, bone: str) -> Tuple[ConstraintEntry, ...]:
        return tuple(entry for entry in self.entries if entry.parent == bone)


@dataclass(frozen=True)
class WeightSite:
    """A driver bone and the influence weight stored immediately after its name."""

    #: Index into `PaprDocument.entries`. Weights live inside one entry's block.
    entry_index: int
    #: Byte offset of the f32 within that entry's block.
    block_offset: int
    bone: str
    value: float

    @property
    def confident(self) -> bool:
        """A whole percentage of at least one: the shape authored weights take.

        Zero is excluded because four zero bytes are equally consistent with padding
        or an unrelated integer. The floor of 1 matters more than it looks: a denormal
        like 3.6e-43 is four bytes of some neighbouring integer read as a float, and it
        passes a bare "is it a whole number" test because it rounds to zero.
        """

        return (
            abs(self.value - round(self.value)) < 1e-4
            and 1 <= round(self.value) <= WEIGHT_MAX
        )


# --------------------------------------------------------------------------- reading


def _read_name(data: bytes, pos: int) -> tuple[str, int] | None:
    if pos + 2 > len(data):
        return None
    length = struct.unpack_from("<H", data, pos)[0]
    if not _MIN_NAME <= length <= _MAX_NAME or pos + 2 + length > len(data):
        return None
    raw = data[pos + 2: pos + 2 + length]
    if any(byte not in _NAME_BYTES for byte in raw):
        return None
    return raw.decode("ascii"), pos + 2 + length


def _entry_header_at(data: bytes, pos: int):
    """Parse an entry header at `pos`, or None if this is not one."""

    first = _read_name(data, pos)
    if first is None:
        return None
    name, after_name = first
    second = _read_name(data, after_name)
    if second is None:
        return None
    parent, after_parent = second
    if after_parent + 3 > len(data):
        return None
    a, b, has_transform = data[after_parent: after_parent + 3]
    if has_transform not in (0, 1) or a > _MAX_TAIL_COUNTER or b > _MAX_TAIL_COUNTER:
        return None
    pos = after_parent + 3
    transform = None
    if has_transform:
        if pos + 40 > len(data):
            return None
        transform = struct.unpack_from("<10f", data, pos)
        pos += 40
    if pos >= len(data):
        return None
    kind = data[pos]
    return name, parent, (a, b), transform, kind, pos + 1


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
    zero, fourteen, payload, entries, records = struct.unpack_from("<IIIII", data, 0x10)
    if payload != len(data) - _PAYLOAD_FROM:
        raise PaprFormatError(
            f"payload says {payload:,} bytes but {len(data) - _PAYLOAD_FROM:,} follow"
            f" 0x{_PAYLOAD_FROM:X}{where}"
        )
    return PaprHeader(
        version=version,
        payload_bytes=payload,
        entry_count=entries,
        record_count=records,
        leading=(zero, fourteen),
    )


def parse_papr(data: bytes, *, name: str = "") -> PaprDocument:
    """Parse a constraint rig into its entries.

    Entry starts are located by shape and then required to tile the file exactly, so a
    rig whose chain does not come out at `entry_count` fails loudly rather than
    returning a plausible-looking wrong answer.
    """

    where = f" ({name})" if name else ""
    header = parse_header(data, name=name)

    starts: dict[int, tuple] = {}
    for pos in range(_ENTRIES_AT, len(data) - 5):
        parsed = _entry_header_at(data, pos)
        if parsed is not None:
            starts[pos] = parsed
    ordered = sorted(starts)

    entries: list[ConstraintEntry] = []
    pos = _ENTRIES_AT
    while pos in starts:
        entry_name, parent, counters, transform, kind, after = starts[pos]
        following = None
        for candidate in ordered:
            if candidate >= after:
                following = candidate
                break
        end = following if following is not None else len(data)
        block = data[after:end] if kind else b""
        if not kind and end != after:
            raise PaprFormatError(
                f"entry {len(entries)} ({entry_name}) has no block but {end - after:,}"
                f" bytes follow it{where}"
            )
        entries.append(
            ConstraintEntry(
                name=entry_name,
                parent=parent,
                counters=counters,
                transform=transform,
                kind=kind,
                block=block,
            )
        )
        if following is None:
            pos = len(data)
            break
        pos = following

    if len(entries) != header.entry_count:
        raise PaprFormatError(
            f"header declares {header.entry_count} entries but the chain finds"
            f" {len(entries)}{where}"
        )
    return PaprDocument(header=header, entries=tuple(entries))


# --------------------------------------------------------------------------- writing


def encode_papr(document: PaprDocument) -> bytes:
    """Serialise a constraint rig. Re-encoding an unedited parse reproduces the source.

    `payload_bytes` and `entry_count` are recomputed, so renaming a bone to a different
    length is safe. `record_count` is carried through: blocks are opaque here, so the
    number of tag records cannot change.
    """

    body = bytearray()
    for index, entry in enumerate(document.entries):
        for text, what in ((entry.name, "name"), (entry.parent, "parent")):
            try:
                raw = text.encode("ascii", "strict")
            except UnicodeEncodeError as exc:
                raise PaprFormatError(
                    f"entry {index} {what} {text!r} is not ASCII: {exc}"
                ) from exc
            if not _MIN_NAME <= len(raw) <= _MAX_NAME:
                raise PaprFormatError(
                    f"entry {index} {what} must be 1..{_MAX_NAME} bytes, got {len(raw)}"
                )
            if any(byte not in _NAME_BYTES for byte in raw):
                raise PaprFormatError(f"entry {index} {what} {text!r} has unsupported characters")
            body += struct.pack("<H", len(raw)) + raw
        a, b = entry.counters
        for value, what in ((a, "counter a"), (b, "counter b")):
            if not 0 <= value <= _MAX_TAIL_COUNTER:
                raise PaprFormatError(f"entry {index} {what} {value} is out of range")
        body += bytes((a, b, 1 if entry.transform is not None else 0))
        if entry.transform is not None:
            if len(entry.transform) != 10:
                raise PaprFormatError(
                    f"entry {index} transform needs 10 floats, got {len(entry.transform)}"
                )
            body += struct.pack("<10f", *entry.transform)
        if not 0 <= entry.kind <= 0xFF:
            raise PaprFormatError(f"entry {index} kind {entry.kind} does not fit a byte")
        body += bytes((entry.kind,))
        if entry.kind:
            body += entry.block
        elif entry.block:
            raise PaprFormatError(f"entry {index} has kind 0 but carries a block")

    head = bytearray(PAR_MAGIC + bytes(document.header.version) + _HEADER_TAIL)
    head += struct.pack("<II", *document.header.leading)
    head += struct.pack("<I", len(body) + 8)  # payload counted from 0x1C
    head += struct.pack("<I", len(document.entries))
    head += struct.pack("<I", document.header.record_count)
    return bytes(head + body)


def rebuild_is_exact(data: bytes, *, name: str = "") -> bool:
    """Parse then re-encode, and say whether the bytes came back identical."""

    try:
        document = parse_papr(data, name=name)
    except PaprFormatError:
        return False
    return encode_papr(document) == data


# --------------------------------------------------------------------------- editing


def find_weight_sites(
    document: PaprDocument, *, confident_only: bool = True
) -> Tuple[WeightSite, ...]:
    """Locate the driver-bone/influence-weight pairs inside every block.

    With `confident_only` the result is limited to whole percentages, which is the set
    an editor should offer. Pass `False` to see every candidate, including floats that
    are not weight-shaped and are therefore probably not weights.
    """

    sites: list[WeightSite] = []
    for entry_index, entry in enumerate(document.entries):
        block = entry.block
        reach = -1
        for pos in range(max(0, len(block) - 2)):
            if pos < reach:
                continue
            length = struct.unpack_from("<H", block, pos)[0]
            if not 2 <= length <= _MAX_NAME or pos + 2 + length + 4 > len(block):
                continue
            raw = block[pos + 2: pos + 2 + length]
            if any(byte not in _NAME_BYTES for byte in raw):
                continue
            value_at = pos + 2 + length
            value = struct.unpack_from("<f", block, value_at)[0]
            if not math.isfinite(value):
                continue
            site = WeightSite(
                entry_index=entry_index,
                block_offset=value_at,
                bone=raw.decode("ascii"),
                value=value,
            )
            reach = value_at + 4
            if confident_only and not site.confident:
                continue
            sites.append(site)
    return tuple(sites)


def set_weights(
    document: PaprDocument,
    changes: Mapping[Tuple[int, int], float],
    *,
    expected: Mapping[Tuple[int, int], float] | None = None,
) -> PaprDocument:
    """Overwrite influence weights, keyed by `(entry_index, block_offset)`.

    `expected` maps the same keys to the value the caller believes is there; when
    given, a mismatch raises rather than writes. Pass it. A site located against the
    wrong rig is the one way this can go wrong, and the check costs nothing.
    """

    if not changes:
        return document
    blocks = {index: bytearray(entry.block) for index, entry in enumerate(document.entries)}
    for (entry_index, offset), value in changes.items():
        if entry_index not in blocks:
            raise PaprFormatError(f"entry {entry_index} is not in this rig")
        block = blocks[entry_index]
        if not 0 <= offset <= len(block) - 4:
            raise PaprFormatError(f"offset 0x{offset:X} is not inside entry {entry_index}")
        if not WEIGHT_MIN <= value <= WEIGHT_MAX:
            raise PaprFormatError(
                f"weight {value} is outside {WEIGHT_MIN}..{WEIGHT_MAX}"
            )
        if expected is not None:
            key = (entry_index, offset)
            if key not in expected:
                raise PaprFormatError(f"no expected value given for {key}")
            found = struct.unpack_from("<f", block, offset)[0]
            if not math.isclose(found, expected[key], rel_tol=0, abs_tol=1e-4):
                raise PaprFormatError(
                    f"entry {entry_index} offset 0x{offset:X} holds {found}, "
                    f"not the expected {expected[key]}"
                )
        struct.pack_into("<f", block, offset, value)
    entries = tuple(
        replace(entry, block=bytes(blocks[index]))
        for index, entry in enumerate(document.entries)
    )
    return replace(document, entries=entries)


def scale_weights(
    document: PaprDocument, sites: Sequence[WeightSite], factor: float
) -> PaprDocument:
    """Multiply the given weights by `factor`, clamped and rounded to whole percent.

    The blunt instrument a modder reaches for first: halve the influence on every hair
    bone, or take the motion out of a cloak entirely with a factor of zero.

    Rounding is not cosmetic. Weights are located by shape, and a whole number in
    1..100 is what makes a site recognisable as a weight at all; halving 15 to 7.5
    would leave a value that the next `find_weight_sites` no longer offers, so the
    second edit in a session would silently have nothing to work on.
    """

    changes = {
        (site.entry_index, site.block_offset):
            float(round(min(WEIGHT_MAX, max(WEIGHT_MIN, site.value * factor))))
        for site in sites
    }
    expected = {(site.entry_index, site.block_offset): site.value for site in sites}
    return set_weights(document, changes, expected=expected)


def rename_bone(document: PaprDocument, old: str, new: str) -> PaprDocument:
    """Rename a bone everywhere the entry headers mention it.

    Names may change length. Block contents are left alone: a driver list inside a
    block names bones too, but rewriting opaque bytes is exactly what this module
    refuses to do, so a rename that needs to reach inside a block is not offered.
    """

    if not any(entry.name == old or entry.parent == old for entry in document.entries):
        raise PaprFormatError(f"no entry names or parents {old!r}")
    entries = tuple(
        replace(
            entry,
            name=new if entry.name == old else entry.name,
            parent=new if entry.parent == old else entry.parent,
        )
        for entry in document.entries
    )
    return replace(document, entries=entries)


def set_transform(
    document: PaprDocument, entry_index: int, transform: Iterable[float]
) -> PaprDocument:
    """Replace an entry's `scale[3], rotation[4], translation[3]` frame."""

    values = tuple(float(v) for v in transform)
    if len(values) != 10:
        raise PaprFormatError(f"a transform frame is 10 floats, got {len(values)}")
    if not 0 <= entry_index < len(document.entries):
        raise PaprFormatError(f"entry {entry_index} is not in this rig")
    if document.entries[entry_index].transform is None:
        raise PaprFormatError(
            f"entry {entry_index} carries no transform frame; adding one would change "
            f"the entry shape and is not offered"
        )
    entries = list(document.entries)
    entries[entry_index] = replace(entries[entry_index], transform=values)
    return replace(document, entries=tuple(entries))


def describe(document: PaprDocument) -> str:
    """A one-line summary for a preview pane."""

    sites = find_weight_sites(document)
    driven = sum(1 for entry in document.entries if entry.driven)
    posed = sum(1 for entry in document.entries if entry.transform is not None)
    return (
        f"Constraint rig: {len(document.entries):,} bones, {driven:,} with a "
        f"configuration block, {posed:,} with a transform frame, "
        f"{len(sites):,} editable influence weights"
    )
