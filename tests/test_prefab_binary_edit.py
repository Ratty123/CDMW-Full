"""Guards for length-changing prefab path edits.

The point of these is relocation: the blob stores absolute file offsets, so an
edit that changes a string's byte length must move every pointer and pointee
length field with it. A test that only checks the new text is present would
pass on a corrupted file, so each case re-decodes and requires the structural
walk to still complete.
"""

from __future__ import annotations

import struct

import pytest

from cdmw.core.prefab_binary import KIND_POINTER, KIND_STRING, decode_prefab_binary
from cdmw.core.prefab_binary_edit import (
    PrefabEditError,
    plan_prefab_path_edits,
    rewrite_prefab_paths,
)


def _text(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def _member(name: str, type_name: str, flags: int, size: int) -> bytes:
    return _text(name) + _text(type_name) + struct.pack("<HHHH", flags, size, 0, 0)


PATH = "character/model/1_pc/weapon/sword.pac"


def _build(path: str = PATH) -> bytes:
    """A prefab whose root holds one string member and one pointer to a path."""
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
    blob += struct.pack("<H", 2)
    blob += (0b11).to_bytes(6, "little")
    blob += _text("Pelvis_R_Socket")
    blob += struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)
    pointer_at = blob_offset + len(blob)
    blob += struct.pack("<I", pointer_at + 4)
    pointee = bytearray(struct.pack("<I", 0) + _text(path))
    blob += pointee
    blob += struct.pack("<I", len(pointee))
    blob += b"\x00" * 5  # trailer

    data_header = struct.pack("<III", 1, blob_offset + len(blob), 0)
    data_header += struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)
    data_header += struct.pack("<II", blob_offset, len(blob))
    return bytes(header + pool + data_header + blob)


def test_fixture_decodes_with_a_complete_walk() -> None:
    document = decode_prefab_binary(_build())
    assert document.walk_complete, document.walk_note
    assert [item.text for item in document.resource_strings()] == [PATH]


@pytest.mark.parametrize(
    "replacement",
    [
        "character/model/1_pc/weapon/a_considerably_longer_sword_name.pac",
        "character/model/1_pc/weapon/s.pac",
        "character/model/1_pc/weapon/sword2.pac",
    ],
    ids=["longer", "shorter", "same-length"],
)
def test_rewrite_survives_a_redecode(replacement: str) -> None:
    original = _build()
    result = rewrite_prefab_paths(original, {PATH: replacement})
    document = decode_prefab_binary(result.data)
    assert document.walk_complete, document.walk_note
    assert [item.text for item in document.resource_strings()] == [replacement]
    expected = len(original) + len(replacement.encode()) - len(PATH.encode())
    assert len(result.data) == expected
    assert result.byte_delta == len(replacement.encode()) - len(PATH.encode())


def test_declared_file_size_tracks_the_edit() -> None:
    replacement = "character/model/1_pc/weapon/much_longer_name_here.pac"
    result = rewrite_prefab_paths(_build(), {PATH: replacement})
    document = decode_prefab_binary(result.data)
    header_at = document.blob_offset - 28
    declared = struct.unpack_from("<I", result.data, header_at + 4)[0]
    blob_length = struct.unpack_from("<I", result.data, header_at + 24)[0]
    assert declared == len(result.data)
    assert document.blob_offset + blob_length == len(result.data)


def test_pointers_still_address_the_byte_after_themselves() -> None:
    """The defining pointer identity must hold after relocation."""
    result = rewrite_prefab_paths(_build(), {PATH: "character/model/1_pc/weapon/x.pac"})
    document = decode_prefab_binary(result.data)
    assert document.pointers
    for pointer in document.pointers:
        stored = struct.unpack_from("<I", result.data, pointer.site)[0]
        assert stored == pointer.site + 4


def test_unmatched_replacement_returns_the_payload_unchanged() -> None:
    original = _build()
    result = rewrite_prefab_paths(original, {"not/present.pac": "other.pac"})
    assert result.data == original
    assert result.edits == ()
    assert result.byte_delta == 0


def test_plan_reports_what_would_change() -> None:
    document = decode_prefab_binary(_build())
    edits = plan_prefab_path_edits(document, {PATH: "new/path.pac"})
    assert [(item.old_text, item.new_text) for item in edits] == [(PATH, "new/path.pac")]


def test_incomplete_decode_refuses_to_edit() -> None:
    """A prefab we cannot fully walk must fail closed rather than guess."""
    payload = bytearray(_build())
    document = decode_prefab_binary(bytes(payload))
    # Break the pointer's self-relative identity: the header still parses, but
    # the structural walk can no longer follow the heap.
    pointer = document.pointers[0]
    struct.pack_into("<I", payload, pointer.site, pointer.site + 64)
    broken = decode_prefab_binary(bytes(payload))
    assert not broken.walk_complete
    with pytest.raises(PrefabEditError, match="did not decode completely"):
        rewrite_prefab_paths(bytes(payload), {PATH: "new/path.pac"})
