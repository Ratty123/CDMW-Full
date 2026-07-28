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
