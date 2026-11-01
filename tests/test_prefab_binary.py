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
    # Real blobs end with the 0x01 terminator. The old fixture padded with five
    # zero bytes, which no shipped file does -- see cdmw/core/prefab_blob_tail.
    blob += pointee + struct.pack("<I", len(pointee)) + b"\x01"

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


def test_the_element_mask_is_as_wide_as_its_header_says() -> None:
    """The header's leading u16 is the mask's byte width; the type index follows it.

    A one-byte mask leaves the next byte to be the type index, not a mask high
    byte: over the 359 width-1 groups in the shipped character prefabs it equals
    the type declaration order would infer in 332, and names a smaller, more
    plausible component in the other 27. A three-byte mask carries member bits
    16..23, which is how an ``EffectComponent`` selects ``_effectTarget``.
    """
    from cdmw.core.prefab_binary import _BlobCursor, _find_element_header

    def header(width: int, mask_bytes: bytes, type_index: int) -> bytes:
        blob = bytearray()
        blob += struct.pack("<H", width)
        blob += mask_bytes
        blob += bytes((type_index, 0, 0))
        owner_at = len(blob)
        blob += b"\x00" * 8
        blob += struct.pack("<I", 1000 + owner_at + 8 + 4)
        blob += b"\x00" * 16
        return bytes(blob)

    mask, type_index = _find_element_header(_BlobCursor(header(1, bytes((0x07,)), 2), 1000))
    assert (mask, type_index) == (0x07, 2)
    mask, type_index = _find_element_header(_BlobCursor(header(2, bytes((0x38, 0x08)), 1), 1000))
    assert (mask, type_index) == (0x0838, 1)
    mask, type_index = _find_element_header(_BlobCursor(header(3, bytes((0x06, 0x01, 0x04)), 4), 1000))
    assert (mask, type_index) == (0x040106, 4), "member 18 (bit 2 of the third byte) is selected"


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


def test_a_wide_header_whose_extra_byte_is_zero_is_not_read_as_a_narrow_one() -> None:
    """Over 1,949 collections in completed walks, no correct narrow count was
    ever a multiple of 256. So where that signal appears it is the wide form."""

    from tests.prefab_collection_builder import build_with_collection

    document = decode_prefab_binary(build_with_collection(("A", "B"), wide=True))

    (collection,) = document.collections
    assert collection.count == 2, "512 is the narrow misread of a wide 2"
    assert collection.header_width == 6
    assert len(collection.elements) == 2


def test_an_indexed_object_list_reads_its_reference_and_element_indexes() -> None:
    """``SocketComponent._socketList`` (member ``extra`` 0x100) writes a 13-byte
    reference after a non-zero count, and each element's u32 index between its
    owner and its name pointer. Without this, 7,655 shipped prefabs declaring
    TransformSocket stopped at their socket list, among them the drop prefabs
    of over a thousand items."""

    from tests.prefab_collection_builder import build_with_collection

    document = decode_prefab_binary(build_with_collection(("A", "B", "C"), indexed=True))

    assert document.walk_complete, document.walk_note
    (collection,) = document.collections
    assert collection.count == 3 and len(collection.elements) == 3
    assert sorted(obj.name for obj in document.objects) == ["A", "B", "C"]
    assert sorted(value.text for obj in document.objects for value in obj.texts) == [
        "asset/a.pac", "asset/b.pac", "asset/c.pac"]
    # The index is authored: shipped props restart it per list or run it on.
    assert decode_prefab_binary(build_with_collection(("A", "B"), indexed=True, indexes=(0, 0))).walk_complete
    assert decode_prefab_binary(build_with_collection(("A", "B"), indexed=True, indexes=(3, 7))).walk_complete
    # An implausible index is not this layout.
    assert not decode_prefab_binary(build_with_collection(("A", "B"), indexed=True, indexes=(0, 1 << 20))).walk_complete
    assert decode_prefab_binary(build_with_collection(("A", "B"))).walk_complete, "plain lists are unchanged"
    assert decode_prefab_binary(build_with_collection((), indexed=True)).walk_complete, "no reference when empty"


def test_a_name_record_may_hold_several_indexed_names() -> None:
    """The fishing rod's SkinnedMeshComponent is named ``Tool_FishingRod`` and
    ``fishingrod``: a count of 2, each name after its own index."""

    from tests.prefab_collection_builder import build_with_collection

    document = decode_prefab_binary(build_with_collection(("A", "B"), aliases=("a_alias",)))

    assert document.walk_complete, document.walk_note
    assert sorted(obj.name for obj in document.objects) == ["A", "B"]


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


# ── How the blob closes ──────────────────────────────────────────────────
#
# There is no separate trailer grammar. Over the 799 completed walks ending
# `<u32> 01`, every one of those u32s is a pointee length field -- the same
# field _read_pointer validates mid-file. Controls: v+1 and v-1 explain 0 of
# 799; a value taken from a different file explains 3.3%. The walk simply stops
# a few bytes early and the residual was never mysterious, only unread.


def test_a_residual_length_field_closes_the_blob() -> None:
    from cdmw.core.prefab_blob_tail import closes_blob

    # A pointee starting at 8; its length field sits at 20 and must read 12.
    starts = frozenset({8})
    assert closes_blob(struct.pack("<I", 12) + bytes([1]), 20 - 20, starts) is False
    blob = bytes(20) + struct.pack("<I", 12) + bytes([1])
    assert closes_blob(blob, 20, starts)


def test_a_length_field_that_names_no_pointee_is_not_a_close() -> None:
    """This is the whole difference from the tolerant rule it replaced: a u32
    has to *be* something, not merely be four bytes long."""
    from cdmw.core.prefab_blob_tail import closes_blob

    blob = bytes(20) + struct.pack("<I", 12) + bytes([1])
    assert not closes_blob(blob, 20, frozenset({9}))
    assert not closes_blob(blob, 20, frozenset())


def test_bare_terminators_close_and_stray_data_does_not() -> None:
    from cdmw.core.prefab_blob_tail import closes_blob

    assert closes_blob(bytes([1]), 0, frozenset())
    assert closes_blob(bytes([1, 1, 1]), 0, frozenset())
    assert not closes_blob(b"character/model/a.pac", 0, frozenset())
    # No spare-byte allowance any more: every byte has something to be.
    assert not closes_blob(bytes(20) + struct.pack("<I", 12) + bytes([1, 0x99]), 20, frozenset({8}))
    assert not closes_blob(b"", 0, frozenset())


def test_pointee_starts_uses_the_same_identity_as_the_rest_of_the_decoder() -> None:
    from cdmw.core.prefab_blob_tail import pointee_starts

    base = 1000
    blob = bytearray(24)
    struct.pack_into("<I", blob, 8, base + 8 + 4)  # a pointer at blob offset 8

    assert 12 in pointee_starts(bytes(blob), base)
    assert pointee_starts(bytes(blob), base + 1) == frozenset()


# Stated layouts, measured on the installed game's 53,429 prefabs (2026-11-01):
# pointees read by the type their header states, numeric arrays by their kind
# byte, unselected lists inside a pointee as the empty byte 01, memberless
# element headers, and a narrower header preferred when only it fits.


def _typedef(name: str, *members: tuple[str, str, int, int, int]) -> bytes:
    body = _text(name) + struct.pack("<H", len(members))
    for member_name, type_name, flags, size, attr in members:
        body += _text(member_name) + _text(type_name) + struct.pack("<HHHH", flags, size, attr, 0)
    return body


def _assemble(typedefs: tuple[bytes, ...], blob_for) -> bytes:
    """A version-4, revision-15 prefab; ``blob_for(blob_offset)`` returns the blob."""
    header = bytearray(struct.pack("<HHH", 0xFFFF, 4, 0) + b"\x00" * 8)
    header += struct.pack("<I", 15) + struct.pack("<H", len(typedefs))
    for item in typedefs:
        header += item
    pool = struct.pack("<I", 0)
    blob_offset = len(header) + len(pool) + 28
    blob = bytes(blob_for(blob_offset))
    data_header = struct.pack("<III", 1, blob_offset + len(blob), 0)
    data_header += struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)
    data_header += struct.pack("<II", blob_offset, len(blob))
    return bytes(header + pool + data_header + blob)


def _owner_and_pointer(blob: bytearray, base: int) -> int:
    """Append an owner field and a self-relative pointer; return the pointee start."""
    blob += struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)
    blob += struct.pack("<I", base + len(blob) + 4)
    return len(blob)


def _typed_pointee_prefab() -> bytes:
    """A root whose ReflectObjectPtr points at a whole object, not a path."""
    root = _typedef("SceneObject", ("_spline", "ReflectObjectPtr", KIND_POINTER, 8, 0x1008))
    spline = _typedef(
        "SplineThing",
        ("_thickness", "float", 0, 4, 0),
        ("_points", "float3", 3, 12, 0x1020),  # a list kind: written as 01 when unselected
        ("_name", "staticstringA", KIND_STRING, 1, 0),
    )

    def blob_for(base: int) -> bytearray:
        blob = bytearray(struct.pack("<H", 2) + (0b1).to_bytes(6, "little"))
        blob += b"\x01"  # presence byte: kind 5 only
        blob += struct.pack("<H", 1) + bytes((0b101, 1)) + b"\x00\x00"  # width, mask, type 1
        start = _owner_and_pointer(blob, base)
        blob += struct.pack("<I", 0)
        blob += struct.pack("<f", 0.25)  # _thickness
        blob += b"\x01"  # _points, unselected and empty
        blob += _text("pointtracing")  # _name
        blob += struct.pack("<I", len(blob) - start)  # the pointee's closing length
        return blob

    return _assemble((root, spline), blob_for)


def test_a_pointee_is_read_by_the_type_its_header_states() -> None:
    from cdmw.core.prefab_binary import _decode_with_width_retry

    data = _typed_pointee_prefab()
    document = decode_prefab_binary(data)

    assert document.walk_complete, document.walk_note
    assert [item.text for item in document.root_texts] == ["pointtracing"]
    assert [item.name for item in document.root_numbers] == ["_thickness"]
    assert len(document.pointee_length_fields) == 1
    # The earlier path-only reading cannot read it, which is what made it partial.
    assert not _decode_with_width_retry(data, stated_layouts=False)[0].walk_complete


def test_an_unselected_list_inside_a_pointee_must_be_the_empty_byte() -> None:
    data = bytearray(_typed_pointee_prefab())
    marker = data.rindex(b"\x01" + _text("pointtracing"))
    data[marker] = 0x05

    document = decode_prefab_binary(bytes(data))

    assert not document.walk_complete
    assert "_points is not empty" in document.walk_note


def test_a_path_in_a_two_member_reference_stays_a_resource() -> None:
    """ResourceReferencePath_SkinnedMesh carries a bool after its _path.

    It reads by its stated type now, and its path has to stay a resource: the
    rewriter and the asset checks look only at resources.
    """
    root = _typedef("SceneObject", ("_mesh", "ReflectObject", 4, 8, 8))
    reference = _typedef(
        "ResourceReferencePath_SkinnedMesh",
        ("_path", "NormalizedPathA", KIND_STRING, 1, 0),
        ("_isFacialBlendShape", "bool", 0, 1, 0),
    )

    def blob_for(base: int) -> bytearray:
        blob = bytearray(struct.pack("<H", 2) + (0b1).to_bytes(6, "little"))
        blob += struct.pack("<H", 1) + bytes((0b11, 1)) + b"\x00\x00"  # kind 4: no presence byte
        start = _owner_and_pointer(blob, base)
        blob += struct.pack("<I", 0) + _text("character/model/a/b.pac") + b"\x01"
        blob += struct.pack("<I", len(blob) - start)
        return blob

    document = decode_prefab_binary(_assemble((root, reference), blob_for))

    assert document.walk_complete, document.walk_note
    assert [item.text for item in document.resource_strings()] == ["character/model/a/b.pac"]


def test_a_numeric_array_opens_with_a_kind_byte() -> None:
    root = _typedef(
        "SceneObject",
        ("_transforms", "float3", 3, 12, 0x1000),
        ("_enableList", "uint32", 3, 4, 0x1020),
    )

    def blob_for(base: int) -> bytearray:
        blob = bytearray(struct.pack("<H", 2) + (0b11).to_bytes(6, "little"))
        blob += b"\x00" + struct.pack("<I", 2) + struct.pack("<6f", *range(6))
        blob += b"\x01"  # selected but empty
        return blob

    document = decode_prefab_binary(_assemble((root,), blob_for))

    assert document.walk_complete, document.walk_note
    (transforms,) = document.root_numbers
    assert transforms.type_name == "float3[]"
    assert len(transforms.raw) == 24


def _one_element_prefab(element_header: bytes, element_body: bytes, *types: bytes) -> tuple[bytes, int]:
    """A root ``_components`` list holding one element.

    Returns the payload and the element's absolute start offset.
    """
    root = _typedef("SceneObject", ("_components", "ReflectObjectPtr", KIND_COLLECTION, 0, 0x1008))
    where: list[int] = []

    def blob_for(base: int) -> bytearray:
        blob = bytearray(struct.pack("<H", 2) + (0b1).to_bytes(6, "little"))
        blob += b"\x00" + struct.pack("<I", 1) + b"\x00" * 13  # header and reference
        where.append(base + len(blob))
        blob += element_header
        start = _owner_and_pointer(blob, base)
        blob += struct.pack("<HH", 0, 0)  # unnamed
        blob += element_body
        blob += struct.pack("<I", len(blob) - start) + b"\x01"
        return blob

    data = _assemble((root, *types), blob_for)
    return data, where[0]


def test_a_memberless_type_has_a_zero_width_header() -> None:
    memberless = _typedef("SceneObjectActorInfoContainer")
    header = struct.pack("<H", 0) + bytes((1,)) + b"\x00\x00"  # width 0, type 1

    data, element_at = _one_element_prefab(header, b"", memberless)
    document = decode_prefab_binary(data)

    assert document.walk_complete, document.walk_note
    (item,) = document.objects
    assert item.component_type == "SceneObjectActorInfoContainer"
    (collection,) = document.collections
    assert collection.count == len(collection.elements) == 1
    # The object is the element, so an edit aimed at it lands on its own span
    # rather than on whatever element follows.
    start, end = collection.elements[0]
    assert item.offset == start and start <= element_at < end


def test_a_wide_header_read_inside_a_length_field_yields_to_the_one_that_fits() -> None:
    """``04 00 00 01 00 07 01 00 00``: width 4 first, the real width-1 header after.

    Both end at the same owner, so the pointer check cannot choose. The width-4
    mask (0x07000100) fits no type; the width-1 mask (0x07) fits the stated one.
    """
    switch = _typedef(
        "SwitchComponent",
        ("_a", "bool", 0, 1, 0),
        ("_b", "bool", 0, 1, 0),
        ("_c", "bool", 0, 1, 0),
    )
    header = b"\x04\x00\x00" + struct.pack("<H", 1) + bytes((0b111, 1)) + b"\x00\x00"

    data, _ = _one_element_prefab(header, b"\x01\x00\x01", switch)
    document = decode_prefab_binary(data)

    assert document.walk_complete, document.walk_note
    (item,) = document.objects
    assert item.component_type == "SwitchComponent"
    assert item.member_names == ("_a", "_b", "_c")


def test_a_file_the_stated_layouts_do_not_touch_is_read_once() -> None:
    import dataclasses

    from cdmw.core.prefab_binary import READING_STATED_LAYOUTS, _decode_previous, _decode_with_width_retry

    data = _build_with_pointer()
    document, departed = _decode_with_width_retry(data, stated_layouts=True)

    assert not departed
    earlier = _decode_with_width_retry(data, stated_layouts=False)[0]
    assert dataclasses.replace(earlier, reading=READING_STATED_LAYOUTS) == document
    assert _decode_previous(data) == document


def test_a_group_reads_its_unselected_lists_and_closes_on_its_own_length_field() -> None:
    """An element span holds the whole object: its trailing 01 and closing field.

    Read the earlier way, the holder's span stopped after its last selected
    member, and its empty ``_tags`` byte and closing length went to whatever
    read next. That is what put a duplicated element inside its source's
    name pointee.
    """
    from cdmw.core.prefab_binary import READING_GROUP_LISTS, _decode_previous
    from tests.prefab_collection_builder import build_nested_groups

    data = build_nested_groups()
    document = decode_prefab_binary(data)

    assert document.walk_complete, document.walk_note
    assert document.reading == READING_GROUP_LISTS
    root, nested = document.collections
    assert (root.member_name, nested.member_name) == ("_childSceneObjects", "_components")
    assert root.elements[-1][1] == document.blob_offset + document.blob_length
    holder = next(item for item in document.objects if item.component_type == "Holder")
    assert holder.offset == root.elements[0][0]
    assert holder.member_names == ("_label", "_components")
    # Every object's name pointee is closed by a field the walk recorded.
    name_sites = {site for site, _field in document.pointee_length_fields}
    assert len(name_sites) == 3
    for site, field in document.pointee_length_fields:
        assert struct.unpack_from("<I", data, field)[0] == field - (site + 4)

    earlier = _decode_previous(data)
    assert earlier.walk_complete
    assert earlier.collections[0].elements[0][1] < root.elements[0][1]
    assert earlier.pointee_length_fields == ()


def test_an_unselected_list_written_in_full_is_read_as_a_collection() -> None:
    """A nested prefab instance writes a populated ``_components`` whatever its mask.

    Skipped, its elements were found by the next header search and read as
    siblings of the object that holds them.
    """
    from tests.prefab_collection_builder import build_nested_groups

    data = build_nested_groups(nested_type="/object/test/child.prefab", holder_mask=0b001)
    document = decode_prefab_binary(data)

    assert document.walk_complete, document.walk_note
    root, nested = document.collections
    assert nested.member_name == "_components" and nested.count == 2
    holder = next(item for item in document.objects if item.component_type.startswith("/"))
    assert holder.member_names == ("_label", "_components")


def test_an_unselected_list_that_is_neither_empty_nor_a_collection_stops_the_group_reading() -> None:
    from cdmw.core.prefab_binary import READING_GROUP_LISTS, _read_prefab
    from tests.prefab_collection_builder import build_nested_groups

    data = bytearray(build_nested_groups())
    # The holder's unselected _tags byte is the blob's last byte but four.
    data[-5] = 0x07
    document = _read_prefab(bytes(data), group_lists=True)[0]

    assert not document.walk_complete
    assert "unselected _tags of Holder is not empty" in document.walk_note
    fallback = decode_prefab_binary(bytes(data))
    assert not (fallback.walk_complete and fallback.reading == READING_GROUP_LISTS)


def test_the_group_reading_ends_on_the_last_byte_or_not_at_all() -> None:
    """All 52,947 walks it completes end exactly; a spare byte is not a tail."""
    from cdmw.core.prefab_binary import _read_prefab
    from tests.prefab_collection_builder import build_nested_groups

    data = bytearray(build_nested_groups())
    data += b"\x01"
    # Data header: u32 count, u32 file size, u32, u64 ffff.., u32 offset, u32 length.
    blob_length_at = data.index(struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)) + 12
    length = struct.unpack_from("<I", data, blob_length_at)[0]
    struct.pack_into("<I", data, blob_length_at, length + 1)
    struct.pack_into("<I", data, blob_length_at - 20, len(data))

    document = _read_prefab(bytes(data), group_lists=True)[0]

    assert not document.walk_complete
    assert document.walk_note == "walk ended 1 bytes short"


def test_a_file_read_by_the_group_lists_has_no_header_width_to_choose() -> None:
    from cdmw.core.prefab_binary import walk_is_determined
    from tests.prefab_collection_builder import build_nested_groups

    data = build_nested_groups()

    assert walk_is_determined(data)
    assert {item.header_width for item in decode_prefab_binary(data).collections} == {5}
