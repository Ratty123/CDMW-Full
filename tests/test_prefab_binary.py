"""Structural decoding guards for cdmw.core.prefab_binary.

These are behaviour tests over synthesised payloads, not source-string guards:
each one builds bytes in the documented grammar and asserts what the decoder
recovers, so a change that breaks decoding fails here rather than silently
producing empty results.
"""

from __future__ import annotations

import struct

import pytest

from cdmw.core.prefab_binary import (
    KIND_COLLECTION,
    KIND_POINTER,
    KIND_POINTER,
    KIND_STRING,
    PrefabBinaryError,
    decode_prefab_binary,
    pointer_sites,
)


def _text(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def _member(name: str, type_name: str, flags: int, size: int) -> bytes:
    return _text(name) + _text(type_name) + struct.pack("<HHHH", flags, size, 0, 0)


def _build(*, revision: int = 15, version: int = 4, pool: tuple[str, ...] = ()) -> bytes:
    """Build a minimal one-object prefab: a root with a single string member."""
    types = bytearray()
    types += _text("SceneObject") + struct.pack("<H", 1)
    types += _member("_attachedSocketName", "IndexedStringA", KIND_STRING, 1)

    header = bytearray()
    header += struct.pack("<HHH", 0xFFFF, version, 0)
    if version == 4:
        header += b"\x00" * 8
    header += struct.pack("<I", revision)
    header += struct.pack("<H", 1)
    header += types

    pool_bytes = bytearray()
    if revision >= 14:
        pool_bytes += struct.pack("<I", len(pool))
        for item in pool:
            pool_bytes += _text(item)

    blob = bytearray()
    blob += struct.pack("<H", 2)
    blob += (1).to_bytes(6, "little")  # presence mask: member 0 only
    blob += _text("Pelvis_R_Socket")

    blob_offset = len(header) + len(pool_bytes) + 28
    total = blob_offset + len(blob)
    data_header = struct.pack("<III", 1, total, 0)
    data_header += struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)
    data_header += struct.pack("<II", blob_offset, len(blob))
    return bytes(header + pool_bytes + data_header + blob)


def _build_with_pointer() -> bytes:
    """A prefab whose root holds a pointer to a resource path."""
    types = bytearray()
    types += _text("SceneObject") + struct.pack("<H", 2)
    types += _member("_socketName", "IndexedStringA", KIND_STRING, 1)
    types += _member("_meshFile", "ReflectObjectPtr", KIND_POINTER, 8)
    types += _text("ResourceReferencePath_SkinnedMesh") + struct.pack("<H", 0)

    header = bytearray()
    header += struct.pack("<HHH", 0xFFFF, 4, 0) + b"\x00" * 8
    header += struct.pack("<I", 15) + struct.pack("<H", 2) + types
    pool = struct.pack("<I", 0)
    blob_offset = len(header) + len(pool) + 28

    blob = bytearray()
    blob += struct.pack("<H", 2) + (0b11).to_bytes(6, "little")
    blob += _text("Pelvis_R_Socket")
    blob += struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)
    blob += struct.pack("<I", blob_offset + len(blob) + 4)
    pointee = bytearray(struct.pack("<I", 0) + _text("character/model/a/b.pac"))
    blob += pointee + struct.pack("<I", len(pointee)) + b"\x00" * 5

    data_header = struct.pack("<III", 1, blob_offset + len(blob), 0)
    data_header += struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)
    data_header += struct.pack("<II", blob_offset, len(blob))
    return bytes(header + pool + data_header + blob)


def test_decodes_type_table_with_member_metadata() -> None:
    document = decode_prefab_binary(_build())
    assert document.version == 4
    assert document.revision == 15
    assert [item.type_name for item in document.types] == ["SceneObject"]
    member = document.types[0].members[0]
    assert member.name == "_attachedSocketName"
    assert member.type_name == "IndexedStringA"
    assert member.is_string
    assert member.kind_label == "text"


def test_presence_mask_selects_root_members() -> None:
    document = decode_prefab_binary(_build())
    assert document.root_type == "SceneObject"
    assert document.root_members == ("_attachedSocketName",)


def test_version_3_header_has_no_content_hash() -> None:
    document = decode_prefab_binary(_build(version=3, revision=14))
    assert document.version == 3
    assert document.root_members == ("_attachedSocketName",)


def test_revision_13_has_no_string_pool() -> None:
    """The pool arrived in revision 14; revision 13 omits it entirely."""
    document = decode_prefab_binary(_build(revision=13))
    assert document.string_pool == ()
    assert document.root_members == ("_attachedSocketName",)


def test_string_pool_is_recovered() -> None:
    document = decode_prefab_binary(_build(pool=("InteractionPivot", "Basic_ChildSocket")))
    assert document.string_pool == ("InteractionPivot", "Basic_ChildSocket")


def test_rejects_foreign_magic() -> None:
    payload = bytearray(_build())
    payload[0:2] = struct.pack("<H", 0x1234)
    with pytest.raises(PrefabBinaryError, match="magic"):
        decode_prefab_binary(bytes(payload))


def test_rejects_unsupported_version() -> None:
    payload = bytearray(_build())
    payload[2:4] = struct.pack("<H", 9)
    with pytest.raises(PrefabBinaryError, match="version"):
        decode_prefab_binary(bytes(payload))


def test_rejects_blob_bounds_outside_payload() -> None:
    payload = bytearray(_build())
    document = decode_prefab_binary(bytes(payload))
    # Point the blob past the end of the file.
    site = len(payload) - len(payload) + document.blob_offset
    assert site > 0
    header_at = document.blob_offset - 8
    payload[header_at : header_at + 4] = struct.pack("<I", 10_000)
    with pytest.raises(PrefabBinaryError, match="outside"):
        decode_prefab_binary(bytes(payload))


def test_pointer_sites_are_exact_not_heuristic() -> None:
    """A u32 is a pointer only when it addresses the byte just past itself."""
    blob_offset = 100
    blob = bytearray(b"\x00" * 40)
    struct.pack_into("<I", blob, 8, blob_offset + 8 + 4)  # a genuine pointer
    struct.pack_into("<I", blob, 20, blob_offset + 999)  # a near miss
    data = bytes(blob_offset) + bytes(blob)
    assert pointer_sites(data, blob_offset, len(blob)) == (blob_offset + 8,)


def test_decoded_document_reports_walk_state() -> None:
    document = decode_prefab_binary(_build())
    assert document.walk_complete is True
    assert document.walk_note == ""


def test_truncated_payload_raises_rather_than_guessing() -> None:
    with pytest.raises(PrefabBinaryError):
        decode_prefab_binary(_build()[:12])


def test_group_component_is_read_from_the_type_index_not_guessed() -> None:
    """Two components can both accommodate a mask; only the index disambiguates.

    The element header states the component's index into the type table at
    three bytes before the owner field. Inferring the type from the mask picks
    whichever candidate happens to be smallest, which is wrong as soon as a
    prefab declares more than one component.
    """
    from cdmw.core.prefab_binary import _BlobCursor, _find_element_header

    blob = bytearray()
    blob += struct.pack("<H", 3)  # marker
    blob += struct.pack("<H", 0b101)  # component mask
    blob += bytes((0x00, 0x07, 0x00, 0x00))  # tail; type index sits at owner-3
    owner_at = len(blob)
    blob += b"\x00" * 8  # owner
    blob += struct.pack("<I", 1000 + owner_at + 8 + 4)  # self-relative pointer
    blob += b"\x00" * 16  # the header search needs room to look ahead

    cursor = _BlobCursor(bytes(blob), 1000)
    mask, type_index = _find_element_header(cursor)
    assert mask == 0b101
    assert type_index == 7


def _fake_type(name: str, member_count: int):
    from cdmw.core.prefab_binary import PrefabMember, PrefabType

    members = tuple(
        PrefabMember(name=f"_m{index}", type_name="bool", flags=0, value_size=1, attr_flags=0, extra=0)
        for index in range(member_count)
    )
    return PrefabType(type_name=name, members=members, offset=0)


def test_stated_type_index_wins_when_it_fits() -> None:
    from cdmw.core.prefab_binary import _BlobCursor, _component_for

    small, large = _fake_type("Small", 4), _fake_type("Large", 20)
    cursor = _BlobCursor(b"", 0, (small, large))
    chosen, stated = _component_for(cursor, type_index=1, mask=0b11, components=(small, large), highest=2)
    assert chosen.type_name == "Large"
    assert stated is True


def test_unstated_type_takes_the_next_declared_one() -> None:
    """Marker=1 groups have no room for a type index, so declaration order
    decides: nested types appear in the order they are first referenced."""
    from cdmw.core.prefab_binary import _BlobCursor, _component_for

    first, second = _fake_type("First", 8), _fake_type("Second", 8)
    cursor = _BlobCursor(b"", 0, (first, second))
    components = (first, second)
    # No usable index (-1): the first declared type that fits is taken...
    one, stated = _component_for(cursor, type_index=-1, mask=0b1, components=components, highest=1)
    assert one.type_name == "First"
    assert stated is False, "declaration order is inference, not something the file said"
    # ...and the next group cannot claim it again.
    two, _ = _component_for(cursor, type_index=-1, mask=0b1, components=components, highest=1)
    assert two.type_name == "Second"


def test_a_mask_too_wide_for_every_type_is_refused() -> None:
    from cdmw.core.prefab_binary import _BlobCursor, _component_for

    small = _fake_type("Small", 3)
    cursor = _BlobCursor(b"", 0, (small,))
    with pytest.raises(PrefabBinaryError, match="exceeds every candidate"):
        _component_for(cursor, type_index=-1, mask=0xFFFF, components=(small,), highest=16)


def test_marker_one_refuses_to_read_the_mask_as_a_type_index() -> None:
    """With marker 1 the byte at owner-3 is the mask's own high byte.

    Reading it would be reading the mask twice. It was never accepted
    downstream -- the member count check rejected it on all 376 marker-1 groups
    in the corpus -- but that was luck, not design.
    """
    from cdmw.core.prefab_binary import _BlobCursor, _find_element_header

    blob = bytearray()
    blob += struct.pack("<H", 1)  # marker 1
    blob += struct.pack("<H", 0x0207)  # mask; high byte 0x02 looks like an index
    blob += bytes((0x00, 0x00))  # tail is marker + 1 == 2 bytes
    owner_at = len(blob)
    blob += b"\x00" * 8
    blob += struct.pack("<I", 1000 + owner_at + 8 + 4)
    blob += b"\x00" * 16

    mask, type_index = _find_element_header(_BlobCursor(bytes(blob), 1000))
    assert mask == 0x0207
    assert type_index == -1, "marker 1 states no type; it must not fall back to the mask"


def test_objects_record_whether_their_type_was_stated() -> None:
    document = decode_prefab_binary(_build())
    assert all(item.type_source in {"stated", "inferred"} for item in document.objects)
    assert document.inferred_objects == tuple(
        item for item in document.objects if item.type_source == "inferred"
    )


def test_the_walk_records_where_each_pointee_length_field_sits() -> None:
    """It reads and validates that field, so nothing should have to search.

    Searching for "a u32 equal to its own distance from the pointee start" can
    land on a nested string's own length prefix, which corrupted 63 of 1,371
    shipped prefabs before the editor stopped relying on it.
    """
    from cdmw.core.prefab_binary_edit import _string_byte_mask  # noqa: F401

    payload = _build_with_pointer()
    document = decode_prefab_binary(payload)
    assert document.walk_complete, document.walk_note
    recorded = dict(document.pointee_length_fields)
    assert recorded, "the walk consumed a pointee, so it must have recorded its field"
    for site, field in recorded.items():
        assert struct.unpack_from("<I", payload, field)[0] == field - (site + 4)


def test_the_member_kind_taxonomy_matches_the_documented_survey() -> None:
    """The kind constants are a claim about the corpus, so pin them.

    The pairing 4:5 :: 6:7 -- singular then collection, by value then by pointer -- is
    what identified kind 6 as the one blocking every shipped `.pcg`. A future edit that
    renumbers or merges these would quietly invalidate that reasoning.
    """
    from cdmw.core import prefab_binary as pb

    assert (pb.KIND_OBJECT, pb.KIND_POINTER) == (0x0004, 0x0005)
    assert (pb.KIND_OBJECT_COLLECTION, pb.KIND_COLLECTION) == (0x0006, 0x0007)
    assert pb.COLLECTION_KINDS == {pb.KIND_OBJECT_COLLECTION, pb.KIND_COLLECTION}
    assert pb.POINTER_KINDS == {pb.KIND_OBJECT, pb.KIND_POINTER}
    assert pb.INLINE_KINDS == {pb.KIND_INLINE, pb.KIND_ENUM, pb.KIND_INLINE_12}
    # 6 is deliberately absent from the handled sets: it is named, not yet read.
    assert pb.KIND_OBJECT_COLLECTION not in pb.POINTER_KINDS
    assert pb.KIND_OBJECT_COLLECTION not in pb.INLINE_KINDS


def test_an_unread_member_kind_fails_loudly_rather_than_guessing() -> None:
    """Kind 6 must not be silently skipped: a wrong length would corrupt an edit."""
    import pathlib

    from cdmw.core import prefab_binary as pb

    source = pathlib.Path(pb.__file__).read_text(encoding="utf-8")
    assert "unsupported member kind" in source
    # The handled-collection branch must not have quietly absorbed kind 6.
    assert "if flags == KIND_COLLECTION:" in source


def test_pointee_strings_are_recoverable_without_the_walk() -> None:
    """45.6% of shipped prefabs stop mid-walk; the pointers are still exact.

    Measured against 635 complete-walk prefabs, this recovers every resource
    the walk found, at identical offsets and identical text.
    """
    from cdmw.core.prefab_recovery import recover_pointee_strings

    payload = _build_with_pointer()
    document = decode_prefab_binary(payload)
    recovered = recover_pointee_strings(payload, document.blob_offset, document.blob_length)
    by_offset = {item.offset: item.text for item in recovered}
    for item in document.resource_strings():
        assert by_offset.get(item.offset) == item.text


def test_recovery_still_works_when_the_walk_cannot_finish() -> None:
    from cdmw.core.prefab_recovery import recover_pointee_strings

    payload = bytearray(_build_with_pointer())
    intact = decode_prefab_binary(bytes(payload))
    expected = [item.text for item in intact.resource_strings()]

    # Declare a blob longer than the walk consumes, so it stops short while
    # every pointer record stays exactly where it was. Corrupting a pointer
    # instead would defeat recovery too, which is not the case under test.
    payload += bytes(8)
    struct.pack_into("<I", payload, intact.blob_offset - 4, intact.blob_length + 8)
    struct.pack_into("<I", payload, intact.blob_offset - 24, len(payload))
    broken = decode_prefab_binary(bytes(payload))
    assert not broken.walk_complete, "the fixture must actually stop short"

    recovered = recover_pointee_strings(
        bytes(payload), broken.blob_offset, broken.blob_length
    )
    assert expected and all(text in [i.text for i in recovered] for text in expected)


def test_a_stopped_walk_says_where_it_stopped() -> None:
    """"Cannot follow this structure" is not something anyone can act on."""
    payload = bytearray(_build_with_pointer())
    intact = decode_prefab_binary(bytes(payload))
    assert intact.walk_complete
    assert intact.walk_stop_offset == -1
    assert intact.walk_progress == 1.0

    payload += bytes(8)
    struct.pack_into("<I", payload, intact.blob_offset - 4, intact.blob_length + 8)
    struct.pack_into("<I", payload, intact.blob_offset - 24, len(payload))
    stopped = decode_prefab_binary(bytes(payload))

    assert not stopped.walk_complete
    assert stopped.blob_offset <= stopped.walk_stop_offset <= len(payload)
    assert 0.0 < stopped.walk_progress <= 1.0


def test_the_blob_trailer_is_a_run_of_records_not_a_fixed_width() -> None:
    """A completed blob ends `.. 00 00 00 01`, and there can be several.

    The trailer was accepted only at 5 or 6 bytes. Files carrying more of the
    same five-byte record stopped with "no element header" at a median 99% of
    the way through -- 1,036 of them, 18.9% of all incomplete walks.
    """
    from cdmw.core.prefab_binary import _is_trailer_run

    one = bytes([1]) + struct.pack("<I", 0xAF)
    assert _is_trailer_run(one, 0)
    assert _is_trailer_run(one * 3, 0)
    # One spare byte is tolerated; the records themselves must be intact.
    assert _is_trailer_run(one * 2 + bytes(1), 0)
    assert not _is_trailer_run(bytes([2]) + struct.pack("<I", 5), 0)
    assert not _is_trailer_run(one + bytes([9, 9, 9, 9, 9]), 0)
    assert not _is_trailer_run(b"", 0)


def test_a_bad_collection_header_says_what_is_actually_there() -> None:
    """"kind 98" invites enumerating kind bytes; there is no enumeration.

    The rejected kinds are scattered and the cursor is usually looking at a
    string, so the message reports what it found instead of describing a field
    that is not present.
    """
    from cdmw.core.prefab_binary import _BlobCursor, _describe_cursor

    text = b"Basic_ChildSocket"
    blob = struct.pack("<I", len(text)) + text
    assert "17-byte string" in _describe_cursor(_BlobCursor(blob, 0))
    assert "Basic_ChildSocket" in _describe_cursor(_BlobCursor(blob, 0))

    # A cursor a little short of the record says by how much.
    skewed = _BlobCursor(bytes(2) + blob, 0)
    assert "2 byte(s) further on" in _describe_cursor(skewed)

    owner = _BlobCursor(b"\xff" * 8 + bytes(8), 0)
    assert "owner field" in _describe_cursor(owner)

    opaque = _BlobCursor(bytes([9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9]), 0)
    assert _describe_cursor(opaque).startswith("bytes ")


def test_prefab_references_answers_without_a_complete_walk() -> None:
    """A modder needs to know whether one edit covers the set or is one of twenty.

    The confirming read goes through the pointer records, so a prefab the walk
    cannot finish still answers correctly.
    """
    from cdmw.core.prefab_recovery import prefab_references

    payload = _build_with_pointer()
    referenced = decode_prefab_binary(payload).resource_strings()[0].text

    assert prefab_references(payload, referenced)
    assert not prefab_references(payload, "character/model/nothing/here.pac")
    assert not prefab_references(payload, "")

    # A substring of a real path is not a reference to it.
    assert not prefab_references(payload, referenced[:-4])

    broken = bytearray(payload) + bytes(8)
    document = decode_prefab_binary(payload)
    struct.pack_into("<I", broken, document.blob_offset - 4, document.blob_length + 8)
    struct.pack_into("<I", broken, document.blob_offset - 24, len(broken))
    assert not decode_prefab_binary(bytes(broken)).walk_complete
    assert prefab_references(bytes(broken), referenced)


def test_a_file_with_no_ambiguous_collection_is_determined() -> None:
    """Decoding identically twice is one reading, not two valid ones.

    Most collection headers are locally ambiguous, and that is fine: a wrong
    width desyncs the rest and the blob fails to close, so completion picks the
    right one. Only ~1% of prefabs close under *both* readings. An early version
    of this check called every unambiguous file undetermined, which would have
    refused editing on nearly every prefab.
    """

    from cdmw.core.prefab_binary import walk_is_determined

    assert walk_is_determined(_build()) is True


def test_a_file_that_does_not_decode_is_not_called_undetermined() -> None:
    """Partial and unreadable files are already refused by other gates."""

    from cdmw.core.prefab_binary import walk_is_determined

    assert walk_is_determined(b"not a prefab") is True
    assert walk_is_determined(b"") is True


def test_the_shipped_collection_reader_is_restored_afterwards() -> None:
    """It swaps a module-level function out; leaking that would corrupt later walks."""

    from cdmw.core import prefab_binary as module

    before = module._read_collection_count
    module.walk_is_determined(_build())
    assert module._read_collection_count is before


# ── Collection header width ──────────────────────────────────────────────
#
# The header is a kind byte, an optional extra byte, then a u32 count. Reading
# the count four bytes early gives the true value shifted up a byte, which is
# still small enough to look plausible -- so the misread is silent, and the walk
# still finishes because it stops on the trailer when the elements run out.


def test_a_wide_header_whose_extra_byte_is_zero_is_not_read_as_a_narrow_one() -> None:
    """Over 1,949 collections in completed walks, no correct narrow count was
    ever a multiple of 256. So where that signal appears it is the wide form."""

    from tests.prefab_collection_builder import build_with_collection

    document = decode_prefab_binary(build_with_collection(("A", "B"), wide=True))

    (collection,) = document.collections
    assert collection.count == 2, "512 is the narrow misread of a wide 2"
    assert collection.header_width == 6
    assert len(collection.elements) == 2


def test_a_narrow_header_is_left_alone() -> None:
    from tests.prefab_collection_builder import build_with_collection

    (collection,) = decode_prefab_binary(build_with_collection(("A", "B"))).collections

    assert collection.header_width == 5
    assert collection.count == 2


def test_the_wide_retry_is_dropped_when_it_reads_less_of_the_file() -> None:
    """The signal is necessary, not sufficient. One shipped file carries it at a
    header where neither reading matches the elements that follow, and forcing
    the wide form there costs 5,234 bytes of walk. Judging the retry on the
    whole file rather than on the header is what leaves that file alone.

    Here: three elements under a count of 512. The narrow reading over-declares
    but consumes everything; the wide reading takes 2 and leaves an element
    behind, so it is rejected and the narrow one stands.
    """

    from tests.prefab_collection_builder import build_with_collection

    data = build_with_collection(("A", "B", "C"), wide=True, declared=512)

    document = decode_prefab_binary(data)

    assert document.walk_complete
    (collection,) = document.collections
    assert collection.count == 512, "the worse reading was not adopted"
    assert len(collection.elements) == 3


def test_an_over_declared_collection_is_reported_rather_than_hidden() -> None:
    """A count the walk could not satisfy is a decode that is wrong without
    saying so. Callers that edit have to be able to see it."""

    from cdmw.core.prefab_collection_spans import over_declared
    from tests.prefab_collection_builder import build_with_collection

    honest = decode_prefab_binary(build_with_collection(("A", "B")))
    inflated = decode_prefab_binary(
        build_with_collection(("A", "B", "C"), wide=True, declared=512)
    )

    assert over_declared(honest) == 0
    assert over_declared(inflated) == 1


def test_the_trailer_record_comes_in_two_widths() -> None:
    """Width follows the component family, as it does for the footer search.

    Reading only the five-byte record left 28 files in 1,500 stopping exactly
    seven bytes short -- every one of them holding `01 01 06 00 00 00 01`, which
    is one six-byte record and the terminator, not a structure the walk had
    failed to follow.
    """
    from cdmw.core.prefab_binary import _is_trailer_run

    six = bytes.fromhex("01 01 06 00 00 00")
    assert _is_trailer_run(six + bytes([1]), 0), "the shipped tail, exactly"
    assert _is_trailer_run(six, 0)
    assert _is_trailer_run(six * 2, 0)
    # Still a record run, not "any leftover starting with 01": the whole
    # remainder has to be records, which is what stops this closing a lost walk.
    assert not _is_trailer_run(six + bytes([1, 2, 3]), 0)
    assert not _is_trailer_run(bytes.fromhex("02 01 06 00 00 00"), 0)


def test_a_six_byte_trailer_closes_the_blob() -> None:
    """End to end: the width matters because it decides `walk_complete`."""

    from tests.prefab_collection_builder import build_with_collection

    data = build_with_collection(("A", "B"))
    # Swap the five-byte trailer this builder writes for the six-byte record
    # plus terminator that the 28 shipped files carry.
    grown = bytearray(data)
    document = decode_prefab_binary(data)
    end = document.blob_offset + document.blob_length
    grown[end - 5: end] = bytes.fromhex("01 01 06 00 00 00 01")
    struct.pack_into("<I", grown, document.blob_offset - 4, document.blob_length + 2)
    struct.pack_into("<I", grown, document.blob_offset - 24, len(grown))

    after = decode_prefab_binary(bytes(grown))

    assert after.walk_complete, after.walk_note
    assert len(after.objects) == 2
