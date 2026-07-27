"""Rewrite resource paths in a ``.prefab`` binary, relocating pointers exactly.

The blob stores absolute file offsets, so changing a string's byte length moves
every following byte and invalidates them. :mod:`cdmw.core.crimson_formats`
avoids the problem by refusing anything but same-length edits, and its
experimental resize path scans preserved bytes for u32s that happen to equal a
known string offset -- which guesses at pointers and rewrites any coincidental
match.

Here the pointers are *identified* rather than guessed. A u32 at blob-relative
``k`` is a pointer if and only if it stores ``blobOffset + k + 4``: it addresses
the byte immediately after itself. That identity also survives relocation --
after the edit a pointer's value is simply its own new offset plus four -- so
the fixups are arithmetic, not inference.

Three things need adjusting after a length change:

* each pointer field, recomputed from its own new position;
* each pointee's trailing length field, which records the pointee's byte count;
* the data header's file size and blob length.
"""

from __future__ import annotations

import struct
from bisect import bisect_right
from dataclasses import dataclass
from typing import Mapping, Sequence

from cdmw.core.prefab_binary import (
    PrefabBinaryError,
    PrefabDocument,
    decode_prefab_binary,
    pointer_sites,
)

_POINTEE_SCAN = 8192


class PrefabEditError(PrefabBinaryError):
    """Raised when an edit cannot be applied safely."""


@dataclass(frozen=True, slots=True)
class PrefabPathEdit:
    """One resource path replacement, addressed by its byte offset."""

    offset: int
    old_text: str
    new_text: str


@dataclass(frozen=True, slots=True)
class PrefabRewriteResult:
    data: bytes
    edits: tuple[PrefabPathEdit, ...]
    byte_delta: int
    relocated_pointers: int
    proof_lines: tuple[str, ...]


def _length_field_for(data: bytes, target: int, limit: int) -> int:
    """Offset of the trailing length field for the pointee starting at ``target``.

    The field stores the pointee's byte count, so it is the position ``q``
    where the stored u32 equals ``q - target``.
    """
    # Start past the pointee's 4-byte head: it stores zero, which would match
    # the `q - target` test trivially at `q == target`.
    end = min(len(data) - 4, target + limit)
    for probe in range(target + 4, end + 1):
        if struct.unpack_from("<I", data, probe)[0] == probe - target:
            return probe
    raise PrefabEditError(f"no pointee length field after 0x{target:x}")


def _shift_for(boundaries: Sequence[int], deltas: Sequence[int], offset: int) -> int:
    """Cumulative byte shift applied to everything at or before ``offset``."""
    index = bisect_right(boundaries, offset)
    return deltas[index - 1] if index else 0


def plan_prefab_path_edits(
    document: PrefabDocument,
    replacements: Mapping[str, str],
) -> tuple[PrefabPathEdit, ...]:
    """Match ``replacements`` (old path -> new path) against decoded strings."""
    wanted = {
        str(old or "").replace("\\", "/").strip(): str(new or "").replace("\\", "/").strip()
        for old, new in dict(replacements or {}).items()
        if str(old or "").strip() and str(new or "").strip()
    }
    edits: list[PrefabPathEdit] = []
    for item in document.all_strings():
        current = item.text.replace("\\", "/").strip()
        replacement = wanted.get(current) or wanted.get(current.lstrip("/"))
        if not replacement or replacement == current:
            continue
        edits.append(PrefabPathEdit(offset=item.offset, old_text=item.text, new_text=replacement))
    edits.sort(key=lambda item: item.offset)
    return tuple(edits)


def rewrite_prefab_paths(
    data: bytes,
    replacements: Mapping[str, str],
) -> PrefabRewriteResult:
    """Replace resource paths, relocating every pointer and length field.

    Unlike the same-length-only path, the replacement may be longer or shorter
    than the original.
    """
    payload = bytes(data or b"")
    document = decode_prefab_binary(payload)
    if not document.walk_complete:
        raise PrefabEditError(
            "Prefab did not decode completely, so edits would be unsafe: " + (document.walk_note or "unknown")
        )
    edits = plan_prefab_path_edits(document, replacements)
    if not edits:
        return PrefabRewriteResult(
            data=payload,
            edits=(),
            byte_delta=0,
            relocated_pointers=0,
            proof_lines=("No matching resource paths; payload returned unchanged.",),
        )

    sites = pointer_sites(payload, document.blob_offset, document.blob_length)
    length_fields = {site: _length_field_for(payload, site + 4, _POINTEE_SCAN) for site in sites}

    # Build the edited bytes and record where each edit shifts what follows.
    out = bytearray()
    cursor = 0
    boundaries: list[int] = []
    running: list[int] = []
    total = 0
    for edit in edits:
        encoded_old = edit.old_text.encode("utf-8")
        encoded_new = edit.new_text.encode("utf-8")
        # PrefabString.offset addresses the u32 length prefix, not the text.
        prefix_at = edit.offset
        if prefix_at < 0 or prefix_at + 4 + len(encoded_old) > len(payload):
            raise PrefabEditError(f"edit at 0x{edit.offset:x} lies outside the payload")
        stored = struct.unpack_from("<I", payload, prefix_at)[0]
        if stored != len(encoded_old):
            raise PrefabEditError(
                f"length prefix at 0x{prefix_at:x} is {stored}, expected {len(encoded_old)}"
            )
        out += payload[cursor:prefix_at]
        out += struct.pack("<I", len(encoded_new))
        out += encoded_new
        cursor = prefix_at + 4 + len(encoded_old)
        total += len(encoded_new) - len(encoded_old)
        boundaries.append(cursor)
        running.append(total)
    out += payload[cursor:]
    rebuilt = bytearray(out)

    # Pointers address the byte just past themselves, so each one is simply
    # recomputed from its relocated position.
    for site in sites:
        moved = site + _shift_for(boundaries, running, site)
        struct.pack_into("<I", rebuilt, moved, moved + 4)
    # Each pointee's trailing length field records its own distance from the
    # pointee start; both ends may have moved independently.
    for site, field_at in length_fields.items():
        target = site + 4
        moved_target = target + _shift_for(boundaries, running, target)
        moved_field = field_at + _shift_for(boundaries, running, field_at)
        struct.pack_into("<I", rebuilt, moved_field, moved_field - moved_target)

    _patch_data_header(rebuilt, document, total)

    proof = [
        "Pointers are identified by the exact test value == offset + 4, not by scanning for "
        "u32s that happen to match a string offset.",
        f"Relocated {len(sites)} pointer(s) and {len(length_fields)} pointee length field(s).",
    ]
    proof.extend(f"{edit.old_text} -> {edit.new_text}" for edit in edits)
    return PrefabRewriteResult(
        data=bytes(rebuilt),
        edits=edits,
        byte_delta=total,
        relocated_pointers=len(sites),
        proof_lines=tuple(proof),
    )


@dataclass(frozen=True, slots=True)
class PrefabPlacementEdit:
    """One transform replacement, addressed by its byte offset."""

    offset: int
    old_raw: bytes
    new_raw: bytes


def rewrite_prefab_placements(
    data: bytes,
    replacements: Mapping[int, bytes],
) -> PrefabRewriteResult:
    """Write transforms back in place, keyed by byte offset.

    Transforms are fixed size, so nothing moves and no pointer needs
    relocating -- this is strictly safer than a path edit. Each write is
    checked against the bytes currently at that offset, so an offset from a
    stale decode is refused rather than splicing over whatever is there now.
    """
    payload = bytearray(data or b"")
    document = decode_prefab_binary(bytes(payload))
    if not document.walk_complete:
        raise PrefabEditError(
            "Prefab did not decode completely, so edits would be unsafe: "
            + (document.walk_note or "unknown")
        )
    known = {
        number.offset: number
        for source in (document.root_numbers, *(obj.numbers for obj in document.objects))
        for number in source
    }
    edits: list[PrefabPlacementEdit] = []
    for offset, new_raw in dict(replacements or {}).items():
        number = known.get(int(offset))
        if number is None:
            raise PrefabEditError(f"No decoded value sits at 0x{int(offset):x}")
        if len(new_raw) != len(number.raw):
            raise PrefabEditError(
                f"Value at 0x{number.offset:x} is {len(number.raw)} byte(s); "
                f"replacement is {len(new_raw)}"
            )
        if bytes(payload[number.offset : number.end]) != number.raw:
            raise PrefabEditError(
                f"Bytes at 0x{number.offset:x} changed since decoding; refusing to write"
            )
        if bytes(new_raw) == number.raw:
            continue
        edits.append(
            PrefabPlacementEdit(offset=number.offset, old_raw=number.raw, new_raw=bytes(new_raw))
        )
    for edit in edits:
        payload[edit.offset : edit.offset + len(edit.new_raw)] = edit.new_raw
    proof = [
        "Transforms are fixed size, so nothing moved and no pointer needed relocating.",
        f"Rewrote {len(edits)} value(s) in place.",
    ]
    return PrefabRewriteResult(
        data=bytes(payload),
        edits=(),
        byte_delta=0,
        relocated_pointers=0,
        proof_lines=tuple(proof),
    )


def _patch_data_header(rebuilt: bytearray, document: PrefabDocument, delta: int) -> None:
    """Update the declared file size and blob length after a resize."""
    header_at = document.blob_offset - 28
    if header_at < 0 or document.blob_offset > len(rebuilt):
        raise PrefabEditError("data header lies outside the payload")
    struct.pack_into("<I", rebuilt, header_at + 4, len(rebuilt))
    struct.pack_into("<I", rebuilt, header_at + 20, document.blob_offset)
    struct.pack_into("<I", rebuilt, header_at + 24, document.blob_length + delta)


__all__ = [
    "PrefabEditError",
    "PrefabPlacementEdit",
    "rewrite_prefab_placements",
    "PrefabPathEdit",
    "PrefabRewriteResult",
    "plan_prefab_path_edits",
    "rewrite_prefab_paths",
]
