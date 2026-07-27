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


def _build(path: str = PATH, socket: str = "Pelvis_R_Socket") -> bytes:
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
    blob += _text(socket)
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


def _build_with_transform() -> bytes:
    """A prefab whose root carries a world transform as well as a path."""
    types = bytearray()
    types += _text("SceneObject") + struct.pack("<H", 3)
    types += _member("_socketName", "IndexedStringA", KIND_STRING, 1)
    types += _member("_worldTransform", "Transform", 0x0000, 40)
    types += _member("_meshFile", "ReflectObjectPtr", KIND_POINTER, 8)
    types += _text("ResourceReferencePath_SkinnedMesh") + struct.pack("<H", 0)

    header = bytearray()
    header += struct.pack("<HHH", 0xFFFF, 4, 0) + b"\x00" * 8
    header += struct.pack("<I", 15) + struct.pack("<H", 2) + types
    pool = struct.pack("<I", 0)
    blob_offset = len(header) + len(pool) + 28

    blob = bytearray()
    blob += struct.pack("<H", 2)
    blob += (0b111).to_bytes(6, "little")
    blob += _text("Pelvis_R_Socket")
    blob += struct.pack("<10f", 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0, 1.0, 2.0, 3.0)
    blob += struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)
    blob += struct.pack("<I", blob_offset + len(blob) + 4)
    pointee = bytearray(struct.pack("<I", 0) + _text(PATH))
    blob += pointee + struct.pack("<I", len(pointee)) + b"\x00" * 5

    data_header = struct.pack("<III", 1, blob_offset + len(blob), 0)
    data_header += struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)
    data_header += struct.pack("<II", blob_offset, len(blob))
    return bytes(header + pool + data_header + blob)


def _build_with_two_copies_of_the_path() -> bytes:
    """The same path in two places, so an edit has to name which one."""
    return _build(socket=PATH)


def _first_placement(document):
    from cdmw.domain.archives.prefab_values import read_placement

    for number in document.root_numbers:
        if read_placement(number.raw) is not None:
            return number
    raise AssertionError("fixture has no placement")


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


def test_legacy_resize_refuses_rather_than_losing_a_pointer() -> None:
    """The old offset-candidate scan corrupts real prefabs; it must fail loudly.

    It relocates by looking for u32s that happen to equal a known string
    offset, which cannot distinguish a pointer from a coincidence. On a real
    prefab that drops an internal pointer, so the rebuild is now checked
    against the exact pointer test and refused when one goes missing.
    """
    from cdmw.core.crimson_formats import _reject_if_pointers_were_lost

    payload = _build()
    # A rebuild that dropped a pointer: same length, pointer no longer
    # addressing the byte past itself.
    corrupted = bytearray(payload)
    pointer = decode_prefab_binary(payload).pointers[0]
    struct.pack_into("<I", corrupted, pointer.site, pointer.site + 64)
    with pytest.raises(ValueError, match="internal pointer"):
        _reject_if_pointers_were_lost(payload, bytes(corrupted))

    # A faithful rebuild is left alone, so the guard cannot block correct work.
    _reject_if_pointers_were_lost(payload, payload)

    # And the structural path handles the resize the legacy scan cannot.
    result = rewrite_prefab_paths(payload, {PATH: PATH + "_LONGER"})
    assert decode_prefab_binary(result.data).walk_complete


def test_placement_edit_keeps_the_file_the_same_size() -> None:
    """Transforms are fixed size, so a move must not shift a single byte."""
    from cdmw.core.prefab_binary_edit import rewrite_prefab_placements
    from cdmw.domain.archives.prefab_values import Placement, read_placement, write_placement

    payload = _build_with_transform()
    document = decode_prefab_binary(payload)
    number = next(n for n in document.root_numbers if n.type_name == "Transform")
    placement = read_placement(number.raw)
    assert placement is not None
    moved = Placement(
        scale=placement.scale,
        rotation=placement.rotation,
        position=(99.0, -5.0, 12.0),
        tile=placement.tile,
    )
    result = rewrite_prefab_placements(payload, {number.offset: write_placement(moved)})
    assert len(result.data) == len(payload)
    assert result.byte_delta == 0
    again = decode_prefab_binary(result.data)
    assert again.walk_complete
    written = next(n for n in again.root_numbers if n.offset == number.offset)
    assert read_placement(written.raw).position == (99.0, -5.0, 12.0)


def test_placement_edit_refuses_an_offset_it_did_not_decode() -> None:
    from cdmw.core.prefab_binary_edit import rewrite_prefab_placements

    with pytest.raises(PrefabEditError, match="No decoded value"):
        rewrite_prefab_placements(_build_with_transform(), {0x999999: b"\x00" * 40})


def test_placement_edit_refuses_a_wrong_sized_replacement() -> None:
    from cdmw.core.prefab_binary_edit import rewrite_prefab_placements

    payload = _build_with_transform()
    document = decode_prefab_binary(payload)
    number = next(n for n in document.root_numbers if n.type_name == "Transform")
    with pytest.raises(PrefabEditError, match="byte"):
        rewrite_prefab_placements(payload, {number.offset: b"\x00" * 8})


def test_two_rows_sharing_a_path_get_independent_replacements() -> None:
    """Keyed by text, the second edit silently overwrote the first."""
    from cdmw.core.prefab_binary import decode_prefab_binary
    from cdmw.core.prefab_binary_edit import PrefabPathEdit

    payload = _build_with_two_copies_of_the_path()
    document = decode_prefab_binary(payload)
    sites = [item for item in document.all_strings() if item.text == PATH]
    assert len(sites) == 2, "fixture must contain the same path twice"

    edits = plan_prefab_path_edits(
        document,
        [
            PrefabPathEdit(offset=sites[0].offset, old_text=PATH, new_text="a/first.pac"),
            PrefabPathEdit(offset=sites[1].offset, old_text=PATH, new_text="a/second.pac"),
        ],
    )
    assert [edit.new_text for edit in edits] == ["a/first.pac", "a/second.pac"]

    # The mapping form still means "every occurrence", which is the useful
    # default for retargeting a mesh -- but it cannot express the above.
    both = plan_prefab_path_edits(document, {PATH: "a/only.pac"})
    assert [edit.new_text for edit in both] == ["a/only.pac", "a/only.pac"]


def test_an_offset_holding_something_else_is_refused() -> None:
    from cdmw.core.prefab_binary import decode_prefab_binary
    from cdmw.core.prefab_binary_edit import PrefabPathEdit

    document = decode_prefab_binary(_build())
    site = document.all_strings()[0]
    with pytest.raises(PrefabEditError, match="not"):
        plan_prefab_path_edits(
            document,
            [PrefabPathEdit(offset=site.offset, old_text="never/here.pac", new_text="x.pac")],
        )


def test_placement_write_checks_the_bytes_the_caller_expected() -> None:
    """The old check compared the payload against itself and could not fail."""
    from cdmw.core.prefab_binary import decode_prefab_binary
    from cdmw.core.prefab_binary_edit import rewrite_prefab_placements

    payload = _build_with_transform()
    number = _first_placement(decode_prefab_binary(payload))
    replacement = bytes(len(number.raw))

    # Correct expectation: accepted.
    result = rewrite_prefab_placements(payload, {number.offset: (number.raw, replacement)})
    assert result.data != payload

    # Stale expectation: refused, where the bare-bytes form would have written.
    wrong = bytes(b"\xff" * len(number.raw))
    with pytest.raises(PrefabEditError, match="not what was read"):
        rewrite_prefab_placements(payload, {number.offset: (wrong, replacement)})


def test_a_changed_source_file_rejects_the_whole_batch() -> None:
    from cdmw.core.prefab_binary import decode_prefab_binary
    from cdmw.core.prefab_binary_edit import prefab_source_digest, rewrite_prefab_placements

    payload = _build_with_transform()
    number = _first_placement(decode_prefab_binary(payload))
    stale = prefab_source_digest(payload + b"\x00")
    with pytest.raises(PrefabEditError, match="changed since it was read"):
        rewrite_prefab_placements(
            payload,
            {number.offset: (number.raw, bytes(len(number.raw)))},
            source_digest=stale,
        )
