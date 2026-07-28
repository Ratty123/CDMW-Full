"""Randomised multi-edit guards for the prefab path rewriter.

The 1,500 round-trips that established the rewriter all used one substitution
pattern: a single path, replaced in place. That exercises neither of the two
places this code can go wrong under load -- pointer relocation when several
edits shift each other, and ``_length_field_for``, which takes the *first*
position whose u32 equals its own distance from the pointee and could in
principle take a coincidental one.

So this fuzzes: several resources per file, random subsets edited at once,
replacements shorter, longer and multi-byte, and the two boundary cases that
single-edit testing never reaches -- editing the first and last strings, and
editing every string in the file.

Seeded, so a failure is reproducible. No hypothesis dependency: the generator
is small enough that a deterministic Random beats adding one.
"""

from __future__ import annotations

import random
import struct

import pytest

from cdmw.core.prefab_binary import (
    KIND_POINTER,
    KIND_STRING,
    decode_prefab_binary,
    pointer_sites,
)
from cdmw.core.prefab_binary_edit import PrefabPathEdit, rewrite_prefab_paths

_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789_"


def _text(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def _member(name: str, type_name: str, flags: int, size: int) -> bytes:
    return _text(name) + _text(type_name) + struct.pack("<HHHH", flags, size, 0, 0)


def build_many(paths: list[str], socket: str = "Pelvis_R_Socket") -> bytes:
    """A prefab carrying ``len(paths)`` resource pointers off its root."""
    count = len(paths)
    types = bytearray()
    types += _text("SceneObject") + struct.pack("<H", 1 + count)
    types += _member("_socketName", "IndexedStringA", KIND_STRING, 1)
    for index in range(count):
        types += _member(f"_meshFile{index}", "ReflectObjectPtr", KIND_POINTER, 8)
    types += _text("ResourceReferencePath_SkinnedMesh") + struct.pack("<H", 0)

    header = bytearray()
    header += struct.pack("<HHH", 0xFFFF, 4, 0) + b"\x00" * 8
    header += struct.pack("<I", 15) + struct.pack("<H", 2) + types
    pool = struct.pack("<I", 0)
    blob_offset = len(header) + len(pool) + 28

    blob = bytearray()
    blob += struct.pack("<H", 2) + ((1 << (count + 1)) - 1).to_bytes(6, "little")
    blob += _text(socket)
    for path in paths:
        blob += struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)
        blob += struct.pack("<I", blob_offset + len(blob) + 4)
        pointee = struct.pack("<I", 0) + _text(path)
        blob += pointee + struct.pack("<I", len(pointee))
    blob += b"\x00" * 5

    data_header = struct.pack("<III", 1, blob_offset + len(blob), 0)
    data_header += struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)
    data_header += struct.pack("<II", blob_offset, len(blob))
    return bytes(header + pool + data_header + blob)


def _random_path(rng: random.Random) -> str:
    depth = rng.randint(1, 4)
    parts = ["".join(rng.choices(_ALPHABET, k=rng.randint(1, 14))) for _ in range(depth)]
    stem = "".join(rng.choices(_ALPHABET, k=rng.randint(1, 30)))
    if rng.random() < 0.12:
        # Multi-byte text: the format stores a byte length, so a character
        # count would diverge here and nowhere else.
        stem += "åäö"
    return "/".join(parts) + "/" + stem + ".pac"


def _check_invariants(payload: bytes, edits: list[PrefabPathEdit], expected: list[str]) -> bytes:
    result = rewrite_prefab_paths(payload, edits)
    before = decode_prefab_binary(payload)
    after = decode_prefab_binary(result.data)

    assert after.walk_complete, after.walk_note
    assert [item.text for item in after.resource_strings()] == expected
    # Every pointer must still satisfy the identity that defines one.
    assert len(pointer_sites(result.data, after.blob_offset, after.blob_length)) == len(
        pointer_sites(payload, before.blob_offset, before.blob_length)
    )
    delta = sum(
        len(edit.new_text.encode("utf-8")) - len(edit.old_text.encode("utf-8"))
        for edit in edits
    )
    assert result.byte_delta == delta
    assert len(result.data) == len(payload) + delta
    # The data header must agree with the file it describes.
    stated_size = struct.unpack_from("<I", result.data, after.blob_offset - 24)[0]
    assert stated_size == len(result.data)
    return result.data


@pytest.mark.parametrize("seed", range(40))
def test_random_multi_edits_keep_the_file_consistent(seed: int) -> None:
    rng = random.Random(seed)
    originals = [_random_path(rng) for _ in range(rng.randint(1, 5))]
    payload = build_many(originals)

    chosen = rng.sample(range(len(originals)), rng.randint(1, len(originals)))
    replacements = {index: _random_path(rng) for index in chosen}
    decoded = decode_prefab_binary(payload).resource_strings()
    edits = [
        PrefabPathEdit(
            offset=decoded[index].offset,
            old_text=originals[index],
            new_text=replacements[index],
        )
        for index in sorted(chosen)
    ]
    expected = [replacements.get(index, text) for index, text in enumerate(originals)]
    _check_invariants(payload, edits, expected)


@pytest.mark.parametrize("seed", range(20))
def test_editing_every_resource_at_once_round_trips_exactly(seed: int) -> None:
    """The involution: undo every edit and the original bytes must return.

    This is the strongest property available without the game, because it
    fails if relocation is merely self-consistent rather than correct.
    """
    rng = random.Random(1000 + seed)
    originals = [_random_path(rng) for _ in range(rng.randint(2, 5))]
    payload = build_many(originals)
    replacements = [_random_path(rng) for _ in originals]

    decoded = decode_prefab_binary(payload).resource_strings()
    forward = [
        PrefabPathEdit(offset=item.offset, old_text=old, new_text=new)
        for item, old, new in zip(decoded, originals, replacements)
    ]
    edited = _check_invariants(payload, forward, replacements)

    moved = decode_prefab_binary(edited).resource_strings()
    backward = [
        PrefabPathEdit(offset=item.offset, old_text=new, new_text=old)
        for item, new, old in zip(moved, replacements, originals)
    ]
    assert _check_invariants(edited, backward, originals) == payload


@pytest.mark.parametrize("count", [2, 3, 5])
def test_first_and_last_resources_are_editable_together(count: int) -> None:
    """Boundary case single-edit testing never reaches.

    The first edit shifts everything after it, including the offset the last
    edit was addressed by, so this is where an off-by-one in the shift table
    shows up.
    """
    originals = [f"character/model/1_pc/weapon/s{index}.pac" for index in range(count)]
    payload = build_many(originals)
    decoded = decode_prefab_binary(payload).resource_strings()
    edits = [
        PrefabPathEdit(
            offset=decoded[0].offset,
            old_text=originals[0],
            new_text="a/considerably/longer/replacement/for/the/first/one.pac",
        ),
        PrefabPathEdit(offset=decoded[-1].offset, old_text=originals[-1], new_text="b/s.pac"),
    ]
    expected = list(originals)
    expected[0] = edits[0].new_text
    expected[-1] = edits[1].new_text
    _check_invariants(payload, edits, expected)


def test_adjacent_edits_do_not_disturb_each_other() -> None:
    """Two neighbouring strings, one growing and one shrinking."""
    originals = ["a/one_original_name.pac", "a/two_original_name.pac", "a/three.pac"]
    payload = build_many(originals)
    decoded = decode_prefab_binary(payload).resource_strings()
    edits = [
        PrefabPathEdit(offset=decoded[0].offset, old_text=originals[0], new_text="a/x.pac"),
        PrefabPathEdit(
            offset=decoded[1].offset,
            old_text=originals[1],
            new_text="a/two_original_name_made_much_longer_than_before.pac",
        ),
    ]
    _check_invariants(payload, edits, [edits[0].new_text, edits[1].new_text, originals[2]])


def test_a_string_prefix_is_not_offered_as_a_pointee_length() -> None:
    """The corruption the corpus fuzz found, at the function that caused it.

    A pointee is ``head + ... + length``, and the scan accepts any position
    whose u32 equals its distance from the pointee start. A string's own u32
    length prefix satisfies that whenever the string sits ``len(text)`` bytes
    into the pointee -- which nesting makes routine. The scan took the first
    match, so it patched the *string's* prefix and left the real length field
    stale, corrupting 63 of 1,371 shipped prefabs.

    Layout below: head at 0, a 4-byte string at 4 (prefix holds 4, distance 4
    -- the decoy), and the genuine field at 12 holding 12.
    """
    from cdmw.core.prefab_binary_edit import _length_field_candidates

    data = struct.pack("<I", 0) + struct.pack("<I", 4) + b"abcd" + struct.pack("<I", 12)
    nothing_masked = bytes(len(data))
    assert _length_field_candidates(data, 0, 100, nothing_masked) == [4, 12]

    marked = bytearray(len(data))
    marked[4:12] = b"" * 8  # the string, prefix included
    assert _length_field_candidates(data, 0, 100, bytes(marked)) == [12]


def test_an_undecidable_pointee_is_refused_rather_than_guessed() -> None:
    """Where two positions survive masking, the file does not say which wins.

    6.5% of pointees in the archives are like this, and a nesting-consistency
    rule resolved 0 of 244 of them. An edit landing inside one is declined
    rather than written, which is why the corpus fuzz reports refusals and no
    corruptions.
    """
    from cdmw.core.prefab_binary_edit import _length_field_candidates

    # Two genuine-looking fields: 8 holds 8, and 16 holds 16.
    data = (
        struct.pack("<I", 0)
        + struct.pack("<I", 99)
        + struct.pack("<I", 8)
        + struct.pack("<I", 99)
        + struct.pack("<I", 16)
    )
    assert _length_field_candidates(data, 0, 100, bytes(len(data))) == [8, 16]
