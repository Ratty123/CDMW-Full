"""Add and remove whole elements of a ``.prefab`` collection.

:mod:`cdmw.core.prefab_binary_edit` changes what a file *says*; this changes how
much of it there is. A collection is a one-byte kind, a u32 element count, and
then that many element bodies laid end to end, so growing one means writing a
larger count and splicing another body in -- and then repairing everything the
splice moved.

Three facts make that tractable, and all three were measured rather than assumed:

* **Pointers are self-relative.** A u32 at absolute ``k`` is a pointer exactly
  when it holds ``k + 4``. So a relocated pointer is recomputed from its own new
  position, and a *copied* pointer is recomputed from the copy's position. No
  pointer in a duplicated element refers to anything outside it that has to be
  chased.
* **Pointee length fields are distances**, not offsets. Both endpoints of a
  pointee inside a moved or copied element shift together, so those fields keep
  their values. The one case that would break this -- a pointee spanning the
  splice point -- is checked for and refused rather than reasoned about.
* **Owner fields are not offsets.** This was the hazard worth ruling out: each
  pointer record is preceded by an 8-byte owner, and if those held absolute
  positions then every one of them after the splice would need fixing. Measured
  over 1,500 shipped prefabs, an owner is either ``NULL_OWNER`` or a small
  ordinal (0 or 1). Not one of the 706 non-null owners fell inside the data blob.
  They are indices, so the splice does not touch them.

## Why duplicate rather than construct

There is no way to synthesise an element body for an arbitrary component: the
layout depends on the component's member mask, and the mask is per-element. But
a *copy of a sibling* is by construction a valid body for the same collection,
and it is also what the edit is usually for -- one more attachment slot, one more
child object -- with the copy then retargeted through the ordinary path rewriter.
So the two primitives here are "duplicate element N" and "remove element N", and
between them they cover growing and shrinking by any amount.

## What validates it

The corpus has no two prefabs that differ by exactly one collection element --
that was searched for, and the six near-pairs it turned up are unrelated assets
whose names coincide. So there is no shipped file to diff a resize against, and
the validation is internal instead:

* **Duplicate then remove the duplicate returns the original bytes.** Every
  intermediate field -- count, pointers, header -- has to be exactly right in
  both directions for the round trip to close, and a byte comparison against the
  input is not something the writer's own arithmetic can talk its way out of.
* **The result is read back** before it is returned, and refused unless the walk
  completes, the collection carries the new count, and every pointer still
  satisfies the identity.

Neither proves the *game* accepts the file. They prove the file is the same kind
of object it was, which is the strongest claim available without the engine.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Sequence

from cdmw.core.prefab_binary import (
    PrefabCollection,
    PrefabDocument,
    decode_prefab_binary,
    pointer_sites,
    walk_is_determined,
)
from cdmw.core.prefab_binary_edit import PrefabEditError, _patch_data_header


@dataclass(frozen=True, slots=True)
class PrefabArrayResult:
    """A resized payload, and what had to be repaired to get it."""

    data: bytes
    #: Index into ``document.collections`` of the collection that changed.
    collection_index: int
    member_name: str
    count_before: int
    count_after: int
    byte_delta: int
    relocated_pointers: int
    proof_lines: tuple[str, ...]


def describe_collections(document: PrefabDocument) -> tuple[str, ...]:
    """One line per collection, for a caller offering the user a choice."""

    lines = []
    for index, item in enumerate(document.collections):
        owner = item.owner_type or "(root)"
        lines.append(
            f"{index}: {owner}.{item.member_name} -- {item.count} element(s)"
            f" at 0x{item.header_offset:x}"
        )
    return tuple(lines)


def _resizable_collection(
    document: PrefabDocument, collection_index: int
) -> PrefabCollection:
    """The collection to edit, or a refusal explaining why it cannot be."""

    if not document.walk_complete:
        raise PrefabEditError(
            "Prefab did not decode completely, so resizing would be unsafe: "
            + (document.walk_note or "unknown")
        )
    if not 0 <= collection_index < len(document.collections):
        raise PrefabEditError(
            f"No collection {collection_index}; this prefab has {len(document.collections)}"
        )
    collection = document.collections[collection_index]
    if len(collection.elements) != collection.count:
        # The walk stopped early inside this collection, so the last element's
        # extent is unknown and a splice would land in the middle of it.
        raise PrefabEditError(
            f"{collection.member_name} declares {collection.count} element(s) but "
            f"only {len(collection.elements)} were read; refusing to resize it"
        )
    return collection


def _pointee_spans_splice(document: PrefabDocument, at: int) -> bool:
    """Would the splice land inside a pointee, invalidating its length field?

    It should not -- elements are group boundaries and a pointee never straddles
    one -- but "should not" is the kind of claim that costs a corrupted file, and
    the check is two comparisons.
    """
    return any(site + 4 < at < field_at + 4 for site, field_at in document.pointee_length_fields)


def _spliced_pointer_sites(
    sites: Sequence[int], start: int, end: int, at: int, delta: int
) -> tuple[int, ...]:
    """Where every pointer ends up, including the ones in a copied block.

    Written out rather than re-derived from the result, because re-deriving it
    would find whatever the splice happened to produce and agree with it.
    """
    moved = []
    for site in sites:
        if site < at:
            moved.append(site)
        elif delta < 0 and start <= site < end:
            continue  # removed along with its element
        else:
            moved.append(site + delta)
    if delta > 0:
        # The copy sits immediately after the source, so a pointer at ``site``
        # inside it lands ``end - start`` further on.
        moved.extend(site + (end - start) for site in sites if start <= site < end)
    return tuple(sorted(moved))


def _resize(data: bytes, collection_index: int, element_index: int, *, insert: bool) -> PrefabArrayResult:
    payload = bytes(data or b"")
    document = decode_prefab_binary(payload)
    collection = _resizable_collection(document, collection_index)
    if not walk_is_determined(payload):
        raise PrefabEditError(
            "This prefab's collection headers read two different ways and the file "
            "does not choose between them, so every offset in it is a guess; "
            "refusing to resize."
        )
    if not 0 <= element_index < len(collection.elements):
        raise PrefabEditError(
            f"No element {element_index} in {collection.member_name}; "
            f"it has {len(collection.elements)}"
        )
    start, end = collection.elements[element_index]
    block = payload[start:end]
    if not block:
        raise PrefabEditError(f"Element {element_index} is empty; refusing to resize")

    if insert:
        at, delta = end, len(block)
        rebuilt = bytearray(payload[:end] + block + payload[end:])
    else:
        if collection.count <= 1:
            # Nothing in the corpus shows an empty collection is legal, and the
            # count byte is not the thing to find out with.
            raise PrefabEditError(
                f"{collection.member_name} has one element left; removing it would "
                "leave an empty collection, which no shipped prefab does"
            )
        at, delta = start, -(end - start)
        rebuilt = bytearray(payload[:start] + payload[end:])

    if _pointee_spans_splice(document, at):
        raise PrefabEditError(
            f"A pointee spans 0x{at:x}, so its stored length would no longer "
            "describe it; refusing to splice there"
        )

    count_after = collection.count + (1 if insert else -1)
    # The header always precedes its elements, so the count never moves.
    struct.pack_into("<I", rebuilt, collection.count_offset, count_after)

    sites = pointer_sites(payload, document.blob_offset, document.blob_length)
    relocated = _spliced_pointer_sites(sites, start, end, at, delta)
    for site in relocated:
        struct.pack_into("<I", rebuilt, site, site + 4)

    _patch_data_header(rebuilt, document, delta)
    _verify_resize(
        bytes(rebuilt),
        payload,
        collection_index=collection_index,
        expected_count=count_after,
        expected_pointers=len(relocated),
        delta=delta,
        twins=(element_index, element_index + 1, len(block)) if insert else None,
    )

    verb = "Duplicated" if insert else "Removed"
    proof = (
        f"{verb} element {element_index} of {collection.member_name} "
        f"({abs(delta)} bytes at 0x{start:x}).",
        f"Element count {collection.count} -> {count_after}, written at "
        f"0x{collection.count_offset:x}.",
        f"Recomputed {len(relocated)} pointer(s) from their own new positions; "
        "pointee lengths are distances and did not move relative to their pointees.",
        "Read the result back: the walk completes and the collection carries the new count.",
    )
    return PrefabArrayResult(
        data=bytes(rebuilt),
        collection_index=collection_index,
        member_name=collection.member_name,
        count_before=collection.count,
        count_after=count_after,
        byte_delta=delta,
        relocated_pointers=len(relocated),
        proof_lines=proof,
    )


def _verify_resize(
    rebuilt: bytes,
    original: bytes,
    *,
    collection_index: int,
    expected_count: int,
    expected_pointers: int,
    delta: int,
    twins: tuple[int, int, int] | None,
) -> None:
    """Read the result back and refuse it unless it is the file it claims to be.

    Shares no arithmetic with the writer. Everything here is a property of the
    rebuilt bytes alone, so a writer that miscomputed a position cannot satisfy
    it by miscomputing the same position twice.
    """
    try:
        after = decode_prefab_binary(rebuilt)
    except Exception as exc:  # noqa: BLE001 -- any failure to read back is a refusal
        raise PrefabEditError(f"The resized prefab does not read back: {exc}") from exc
    if not after.walk_complete:
        raise PrefabEditError(
            f"The resized prefab no longer reads all the way through: {after.walk_note}"
        )
    if collection_index >= len(after.collections):
        raise PrefabEditError("The resized prefab reads back with fewer collections")
    got = after.collections[collection_index]
    if got.count != expected_count:
        raise PrefabEditError(
            f"The resized collection reads back with {got.count} element(s), "
            f"expected {expected_count}"
        )
    if len(got.elements) != expected_count:
        raise PrefabEditError(
            f"The resized collection declares {expected_count} element(s) but "
            f"{len(got.elements)} were read back"
        )
    if len(rebuilt) != len(original) + delta:
        raise PrefabEditError(
            f"The resized prefab is {len(rebuilt)} bytes, expected {len(original) + delta}"
        )
    if twins is not None:
        # A copy is only a copy if it reads back the same size as its source.
        # Without this the file can still walk and still count correctly while
        # the re-walk resynchronised a few bytes off inside the copy -- which is
        # exactly what one corpus file did, and it survived every other check
        # here before failing the round trip.
        source, copy, expected_span = twins
        for index in (source, copy):
            if index >= len(got.elements):
                raise PrefabEditError(f"Element {index} is missing from the resized collection")
            start, end = got.elements[index]
            if end - start != expected_span:
                raise PrefabEditError(
                    f"Element {index} reads back as {end - start} bytes, but the "
                    f"duplicated element is {expected_span}; the copy did not "
                    "re-read as its own source"
                )
    found = pointer_sites(rebuilt, after.blob_offset, after.blob_length)
    if len(found) != expected_pointers:
        raise PrefabEditError(
            f"The resized prefab holds {len(found)} pointer(s), expected {expected_pointers}"
        )
    stated = struct.unpack_from("<I", rebuilt, after.blob_offset - 24)[0]
    if stated != len(rebuilt):
        raise PrefabEditError(
            f"The resized prefab declares {stated} bytes but is {len(rebuilt)}"
        )


def duplicate_prefab_element(
    data: bytes, collection_index: int, element_index: int
) -> PrefabArrayResult:
    """Copy one element of a collection, placing the copy after the original.

    The copy is a byte-for-byte sibling: same component, same members, same
    resource paths. Retarget it afterwards through
    :func:`cdmw.core.prefab_binary_edit.rewrite_prefab_paths`, which is the tool
    that already knows how to change what an element refers to.
    """
    return _resize(data, collection_index, element_index, insert=True)


def remove_prefab_element(
    data: bytes, collection_index: int, element_index: int
) -> PrefabArrayResult:
    """Drop one element of a collection, and everything nested inside it."""

    return _resize(data, collection_index, element_index, insert=False)


def resize_round_trips(data: bytes, collection_index: int, element_index: int) -> bool:
    """Does duplicating an element and removing the duplicate return the input?

    This is the resize equivalent of the path rewriter's shrink-and-regrow gate.
    It is the strongest check available given no shipped file differs from
    another by one element, and it is strict: the comparison is against the
    original bytes, so any field either step gets wrong shows up as a mismatch
    rather than as a plausible-looking file.
    """
    try:
        grown = duplicate_prefab_element(data, collection_index, element_index)
        shrunk = remove_prefab_element(grown.data, collection_index, element_index + 1)
    except PrefabEditError:
        return False
    return shrunk.data == bytes(data)


__all__ = [
    "PrefabArrayResult",
    "describe_collections",
    "duplicate_prefab_element",
    "remove_prefab_element",
    "resize_round_trips",
]
