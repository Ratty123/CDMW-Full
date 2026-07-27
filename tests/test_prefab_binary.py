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
