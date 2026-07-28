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

import hashlib
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


def _length_field_candidates(
    data: bytes, target: int, limit: int, in_string: bytes
) -> list[int]:
    """Every position that could be this pointee's trailing length field."""
    end = min(len(data) - 4, target + limit)
    return [
        probe
        for probe in range(target + 4, end + 1)
        if struct.unpack_from("<I", data, probe)[0] == probe - target
        and not in_string[probe]
    ]


def _length_field_for(
    data: bytes, target: int, limit: int, in_string: bytes | None = None
) -> int:
    """Offset of the trailing length field for the pointee starting at ``target``.

    The field stores the pointee's byte count, so it is the position ``q``
    where the stored u32 equals ``q - target``.

    That test alone is not enough. Pointees nest, so the scan crosses string
    data on its way to the outer pointee's field, and a string's own u32 length
    prefix matches whenever the string happens to sit ``len(text)`` bytes from
    the pointee start. Taking the first match then patches the *string's* length
    prefix and leaves the real field stale -- corrupting the file. Measured on
    the shipped archives, that hit 63 of 1,371 prefabs.

    ``in_string`` marks every byte covered by a decoded string, prefix included.
    A length field cannot live inside string data, so those candidates are
    skipped and the scan continues to the genuine one.
    """
    # Start past the pointee's 4-byte head: it stores zero, which would match
    # the `q - target` test trivially at `q == target`.
    end = min(len(data) - 4, target + limit)
    for probe in range(target + 4, end + 1):
        if struct.unpack_from("<I", data, probe)[0] != probe - target:
            continue
        if in_string is not None and in_string[probe]:
            continue
        return probe
    raise PrefabEditError(f"no pointee length field after 0x{target:x}")


def _string_byte_mask(data: bytes, document: PrefabDocument) -> bytes:
    """One flag per byte: is this byte part of a decoded string?"""
    mask = bytearray(len(data))
    for item in document.all_strings():
        start = item.offset
        stop = min(len(data), start + 4 + len(item.text.encode("utf-8")))
        if 0 <= start < stop:
            mask[start:stop] = b"\x01" * (stop - start)
    return bytes(mask)


def _shift_for(boundaries: Sequence[int], deltas: Sequence[int], offset: int) -> int:
    """Cumulative byte shift applied to everything at or before ``offset``."""
    index = bisect_right(boundaries, offset)
    return deltas[index - 1] if index else 0


def prefab_source_digest(data: bytes) -> str:
    """Fingerprint of the payload a caller decoded, for staleness checks."""
    return hashlib.sha256(bytes(data or b"")).hexdigest()


def plan_prefab_path_edits(
    document: PrefabDocument,
    replacements: Mapping[str, str] | Sequence[PrefabPathEdit],
) -> tuple[PrefabPathEdit, ...]:
    """Work out which bytes to replace.

    Two forms, and the difference matters:

    * a **sequence of** :class:`PrefabPathEdit` names one occurrence each, by
      byte offset, and every offset is checked against the decoded string that
      sits there. Use this when the caller is acting on specific rows;
    * a **mapping** of old path to new path replaces *every* occurrence of that
      path in the file. That is the right default for retargeting a mesh, but
      it cannot express two different replacements for the same path, and it
      will change occurrences the caller never looked at.
    """
    if not isinstance(replacements, Mapping):
        return _plan_from_occurrences(document, replacements)
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


def _plan_from_occurrences(
    document: PrefabDocument, requested: Sequence[PrefabPathEdit]
) -> tuple[PrefabPathEdit, ...]:
    """Validate offset-addressed edits against what actually decoded there."""
    decoded = {item.offset: item.text for item in document.all_strings()}
    edits: list[PrefabPathEdit] = []
    for edit in requested:
        found = decoded.get(edit.offset)
        if found is None:
            raise PrefabEditError(f"No decoded string sits at 0x{edit.offset:x}")
        if found != edit.old_text:
            raise PrefabEditError(
                f"String at 0x{edit.offset:x} is {found!r}, not {edit.old_text!r}; "
                "refusing to write over something the caller has not seen"
            )
        if edit.new_text and edit.new_text != found:
            edits.append(edit)
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
    # A pointee's stored length is a distance, so it only needs rewriting when
    # an edit lands *inside* that pointee. Every other field keeps its value:
    # both of its endpoints shift by the same amount. Touching only what must
    # change keeps the ambiguous ones (6.5% of pointees have more than one
    # position satisfying the length test, and nothing in the file resolves
    # which) out of the blast radius entirely.
    in_string = _string_byte_mask(payload, document)
    string_at = {item.offset: item for item in document.all_strings()}
    edit_positions = [edit.offset for edit in edits]
    length_fields: dict[int, int] = {}
    for site in sites:
        target = site + 4
        # A pointee that opens with a decoded string has a *computable* field:
        # 4 bytes of head, then the string, then the length. No scan, so no
        # ambiguity -- and this is the shape every resource-path pointee takes,
        # which is exactly where edits land.
        held = string_at.get(target + 4)
        if held is not None:
            derived = target + 8 + len(held.text.encode("utf-8"))
            if (
                derived + 4 <= len(payload)
                and struct.unpack_from("<I", payload, derived)[0] == derived - target
            ):
                if any(target <= position < derived + 4 for position in edit_positions):
                    length_fields[site] = derived
                continue
        candidates = _length_field_candidates(payload, target, _POINTEE_SCAN, in_string)
        if not candidates:
            raise PrefabEditError(f"no pointee length field after 0x{target:x}")
        # Widest possible extent, so "unaffected" is never claimed too eagerly.
        extent = candidates[-1] + 4
        if not any(target <= position < extent for position in edit_positions):
            continue
        if len(candidates) > 1:
            raise PrefabEditError(
                f"The pointee at 0x{target:x} has {len(candidates)} possible length "
                "fields and the file does not say which; refusing to guess on an "
                "edit inside it."
            )
        length_fields[site] = candidates[0]

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


def _split_placement_request(request: object) -> tuple[bytes | None, bytes]:
    """Accept either ``new`` alone or ``(expected_old, new)``.

    Bare bytes are the older, unverified form: nothing is checked beyond the
    offset existing and the size matching.
    """
    if isinstance(request, (bytes, bytearray, memoryview)):
        return None, bytes(request)
    if isinstance(request, Sequence) and len(request) == 2:
        expected_old, new_raw = request
        return bytes(expected_old), bytes(new_raw)
    raise PrefabEditError(
        "A placement replacement must be bytes, or an (expected_old, new) pair"
    )


@dataclass(frozen=True, slots=True)
class PrefabPlacementEdit:
    """One transform replacement, addressed by its byte offset."""

    offset: int
    old_raw: bytes
    new_raw: bytes


def rewrite_prefab_placements(
    data: bytes,
    replacements: Mapping[int, bytes] | Mapping[int, tuple[bytes, bytes]],
    *,
    source_digest: str | None = None,
) -> PrefabRewriteResult:
    """Write transforms back in place, keyed by byte offset.

    Transforms are fixed size, so nothing moves and no pointer needs
    relocating -- this is strictly safer than a path edit.

    Each value may be either the replacement bytes alone, or a
    ``(expected_old, new)`` pair. Pass the pair: it is the only form that can
    detect a stale offset. An earlier version claimed to check "the bytes
    currently at that offset", but it decoded the very payload it then compared
    against, so the comparison could never fail. Only the caller knows what it
    read, so only the caller can say what it expects to still be there.

    ``source_digest`` is :func:`prefab_source_digest` of the payload the caller
    decoded. Supplying it rejects the whole batch if the file has changed
    underneath, rather than catching it one offset at a time.
    """
    payload = bytearray(data or b"")
    if source_digest is not None and prefab_source_digest(bytes(payload)) != source_digest:
        raise PrefabEditError(
            "This prefab has changed since it was read; reopen it before saving."
        )
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
    for offset, request in dict(replacements or {}).items():
        expected_old, new_raw = _split_placement_request(request)
        number = known.get(int(offset))
        if number is None:
            raise PrefabEditError(f"No decoded value sits at 0x{int(offset):x}")
        if len(new_raw) != len(number.raw):
            raise PrefabEditError(
                f"Value at 0x{number.offset:x} is {len(number.raw)} byte(s); "
                f"replacement is {len(new_raw)}"
            )
        if expected_old is not None and bytes(expected_old) != number.raw:
            raise PrefabEditError(
                f"Value at 0x{number.offset:x} is not what was read there; refusing to write"
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
