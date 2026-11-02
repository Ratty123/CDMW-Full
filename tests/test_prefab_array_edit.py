"""Gates for adding and removing whole ``.prefab`` collection elements.

Behaviour tests over synthesised payloads: each builds a prefab holding a
collection, resizes it, and asserts on what the decoder reads back. The corpus
gate at the end is the one that matters most -- duplicate-then-remove has to
return the original bytes on every shipped prefab it can be run against, which
is the only external check this operation has, since no two shipped prefabs
differ by exactly one collection element.
"""

from __future__ import annotations

import struct

import pytest

from cdmw.core.prefab_array_edit import (
    describe_collections,
    duplicate_prefab_element,
    remove_prefab_element,
    resize_round_trips,
)
from cdmw.core.prefab_binary import decode_prefab_binary, pointer_sites
from cdmw.core.prefab_binary_edit import PrefabEditError
from tests.prefab_collection_builder import build_with_collection as _build_with_collection


def test_the_walk_records_every_collection_and_its_element_spans() -> None:
    """Element boundaries come from the walk. Nothing else can supply them: an
    element ends wherever the previous one stopped being read."""
    document = decode_prefab_binary(_build_with_collection())

    assert document.walk_complete, document.walk_note
    (collection,) = document.collections
    assert collection.member_name == "_childSceneObjects"
    assert collection.count == 2
    assert len(collection.elements) == 2
    first, second = collection.elements
    assert first[1] == second[0], "elements are laid end to end"


def test_the_count_offset_points_at_the_count_whatever_the_header_width() -> None:
    for wide in (False, True):
        data = _build_with_collection(wide=wide)
        (collection,) = decode_prefab_binary(data).collections
        assert collection.header_width == (6 if wide else 5)
        stored = struct.unpack_from("<I", data, collection.count_offset)[0]
        assert stored == 2


def test_a_wide_header_is_not_read_as_a_count_256_times_too_large() -> None:
    """The narrow read of a wide header whose extra byte is zero yields the true
    count shifted up a byte. Left alone the walk still finishes -- it stops on
    the trailer -- so the file looks read while the count is fiction."""
    document = decode_prefab_binary(_build_with_collection(wide=True))

    (collection,) = document.collections
    assert collection.count == 2, "512 would be the narrow misread of a wide 2"
    assert len(collection.elements) == 2


def test_duplicating_an_element_puts_the_copy_after_the_original() -> None:
    data = _build_with_collection(("Alpha", "Beta"), name_lengths=True)

    result = duplicate_prefab_element(data, 0, 0)

    assert result.count_before == 2 and result.count_after == 3
    after = decode_prefab_binary(result.data)
    assert [item.name for item in after.objects] == ["Alpha", "Alpha", "Beta"]


def test_removing_an_element_drops_it_and_nothing_else() -> None:
    data = _build_with_collection(("Alpha", "Beta", "Gamma"), name_lengths=True)

    result = remove_prefab_element(data, 0, 1)

    assert result.count_after == 2
    after = decode_prefab_binary(result.data)
    assert [item.name for item in after.objects] == ["Alpha", "Gamma"]


def test_every_pointer_in_a_copied_element_is_rewritten_for_its_new_position() -> None:
    """Pointers are self-relative, so a copied one is wrong until recomputed --
    it would otherwise still address the original's position."""
    data = _build_with_collection(("Alpha", "Beta"), name_lengths=True)
    before = decode_prefab_binary(data)

    grown = duplicate_prefab_element(data, 0, 0).data

    after = decode_prefab_binary(grown)
    sites = pointer_sites(grown, after.blob_offset, after.blob_length)
    for site in sites:
        assert struct.unpack_from("<I", grown, site)[0] == site + 4
    assert len(sites) == len(before.pointers) + 1, "the copy brought its own pointer"


def test_the_declared_file_size_follows_the_resize() -> None:
    data = _build_with_collection(("Alpha", "Beta"), name_lengths=True)

    grown = duplicate_prefab_element(data, 0, 0)

    document = decode_prefab_binary(grown.data)
    stated = struct.unpack_from("<I", grown.data, document.blob_offset - 24)[0]
    assert stated == len(grown.data)
    assert len(grown.data) == len(data) + grown.byte_delta


def test_duplicate_then_remove_returns_the_original_bytes() -> None:
    """Catches a field either step writes wrongly. Not one both steps forget:
    that is restored by the way back, which is why the exact-file tests below
    exist."""
    data = _build_with_collection(("Alpha", "Beta", "Gamma"), name_lengths=True)

    assert resize_round_trips(data, 0, 0)
    assert resize_round_trips(data, 0, 1)
    assert resize_round_trips(data, 0, 2)


# Neighbours of different sizes, so a name record paired with its neighbour's
# length shows. Chosen so no variant puts a u32 that equals its own offset + 4
# into the element headers: these files are small enough that offsets near 0x100
# do that ("Beta", "Gamma" reads a fourth pointer).
NAMES = ("Alpha", "Bravo", "Charlie", "Delta")


@pytest.mark.parametrize("index", range(len(NAMES)))
def test_a_duplicate_is_exactly_the_file_built_with_the_extra_element(index: int) -> None:
    """The one oracle that does not come from the writer: the builder lays out a
    three-element and a four-element file to the same grammar, so duplicating
    element ``index`` must produce the second byte for byte.

    Shipped elements end with their name record's length field, and the walk
    gives that field to the next element. Splicing the walk's span left the
    original's name record without its length (element 0) or with its
    neighbour's, and both the read-back and the duplicate-then-remove round trip
    passed it.
    """
    data = _build_with_collection(NAMES, name_lengths=True)
    expected = list(NAMES)
    expected.insert(index + 1, NAMES[index])

    result = duplicate_prefab_element(data, 0, index)

    assert result.data == _build_with_collection(tuple(expected), name_lengths=True)


@pytest.mark.parametrize("index", range(len(NAMES)))
def test_a_removal_is_exactly_the_file_built_without_the_element(index: int) -> None:
    data = _build_with_collection(NAMES, name_lengths=True)
    expected = tuple(name for position, name in enumerate(NAMES) if position != index)

    result = remove_prefab_element(data, 0, index)

    assert result.data == _build_with_collection(expected, name_lengths=True)


def test_an_element_whose_name_record_has_no_length_field_is_refused() -> None:
    """No shipped element lacks the field, so the record's extent is unknown."""
    with pytest.raises(PrefabEditError, match="no pointee length field"):
        duplicate_prefab_element(_build_with_collection(NAMES), 0, 0)


# Everything below is a refusal: a case where the file does not determine the
# edit. Guessing would write a byte into a plausible wrong place, which is worse
# than declining.


def test_an_unknown_collection_is_refused() -> None:
    with pytest.raises(PrefabEditError, match="No collection 4"):
        duplicate_prefab_element(_build_with_collection(), 4, 0)


def test_an_unknown_element_is_refused() -> None:
    with pytest.raises(PrefabEditError, match="No element 9"):
        duplicate_prefab_element(_build_with_collection(), 0, 9)


def test_removing_the_last_element_is_refused() -> None:
    """No shipped prefab carries an empty collection, and the count field is not
    the thing to find out with."""
    with pytest.raises(PrefabEditError, match="would leave an empty collection"):
        remove_prefab_element(_build_with_collection(("Only",)), 0, 0)


def test_an_indexed_socket_list_is_not_resized() -> None:
    """Socket list elements store their own position; a splice would not renumber them."""
    indexed = _build_with_collection(("A", "B", "C"), indexed=True)
    for edit in (duplicate_prefab_element, remove_prefab_element):
        with pytest.raises(PrefabEditError, match="indexed list"):
            edit(indexed, 0, 2)


def test_a_prefab_that_does_not_walk_is_refused() -> None:
    data = bytearray(_build_with_collection())
    document = decode_prefab_binary(bytes(data))
    # Break the second element's name pointer. A pointer that no longer holds
    # its own position plus four stops the walk where it stands.
    struct.pack_into("<I", data, document.pointers[-1].site, 0x0BAD)

    with pytest.raises(PrefabEditError, match="did not decode completely"):
        duplicate_prefab_element(bytes(data), 0, 0)


def test_a_collection_declaring_more_elements_than_were_read_is_refused() -> None:
    """The walk stopped early inside it, so the last element's extent is unknown
    and a splice would land in the middle of one."""
    data = bytearray(_build_with_collection(("Alpha", "Beta")))
    (collection,) = decode_prefab_binary(bytes(data)).collections
    struct.pack_into("<I", data, collection.count_offset, 7)

    with pytest.raises(PrefabEditError, match="only 2 were read"):
        duplicate_prefab_element(bytes(data), 0, 0)


def test_describe_collections_names_the_member_and_its_owner() -> None:
    lines = describe_collections(decode_prefab_binary(_build_with_collection()))

    assert len(lines) == 1
    assert "_childSceneObjects" in lines[0]
    assert "2 element(s)" in lines[0]


@pytest.mark.real_game
def test_shipped_prefabs_survive_duplicate_then_remove() -> None:
    """The corpus gate. No two shipped prefabs differ by one collection element,
    so there is no shipped file to compare a resize against. The round trip
    compares against the original bytes, but it cannot see a field both steps
    leave unwritten; ``scripts/prefab_edit_oracle.py`` checks every byte of a
    single resize instead, and is the check to run over the archives.

    Capped at a sample: the point is that failures are zero, not that every file
    is visited, and a full sweep costs minutes rather than the second a gate
    should take.
    """
    from cdmw.core.archive_extraction import read_archive_entry_data
    from tools.placement_studio import corpus

    if not corpus.game_root().is_dir():
        pytest.skip("needs the installed game")

    attempted = exact = 0
    differing: list[str] = []
    for _package, entry in corpus._iter_archive_entries(corpus.game_root()):
        path = corpus.normalize_game_path(entry.path)
        if not path.endswith(".prefab"):
            continue
        try:
            data, _decompressed, _note = read_archive_entry_data(entry)
            document = decode_prefab_binary(data)
        except Exception:
            continue
        if not document.walk_complete:
            continue
        for index, collection in enumerate(document.collections):
            if collection.count < 2 or len(collection.elements) != collection.count:
                continue
            try:
                grown = duplicate_prefab_element(data, index, 0)
                shrunk = remove_prefab_element(grown.data, index, 1)
            except PrefabEditError:
                continue  # a refusal is the writer working, not failing
            attempted += 1
            if shrunk.data == data:
                exact += 1
            else:
                differing.append(path)
            break
        if attempted >= 120:
            break

    assert attempted, "no shipped prefab offered a resizable collection"
    assert exact == attempted, f"{len(differing)} of {attempted} did not round trip: {differing[:3]}"


def _holder_field(document):
    """(site, field) of the object holding the nested collection."""
    nested = document.collections[1]
    return next(
        (site, field)
        for site, field in document.pointee_length_fields
        if site + 4 < nested.header_offset and field >= nested.elements[-1][1]
    )


def test_a_nested_duplicate_grows_every_pointee_around_it() -> None:
    """The holder's name pointee encloses its _components, so a copied leaf
    makes it longer by exactly the copy. Kept at its old value, the field no
    longer closes the holder, and the round trip still came back exact."""
    from tests.prefab_collection_builder import build_nested_groups

    data = build_nested_groups()
    before = decode_prefab_binary(data)
    site, field = _holder_field(before)
    start, end = before.collections[1].elements[0]

    result = duplicate_prefab_element(data, 1, 0)

    grown = result.data
    delta = end - start
    assert struct.unpack_from("<I", grown, field + delta)[0] == struct.unpack_from("<I", data, field)[0] + delta
    after = decode_prefab_binary(grown)
    assert after.walk_complete, after.walk_note
    assert len(after.pointee_length_fields) == len(before.pointee_length_fields) + 1
    assert remove_prefab_element(grown, 1, 1).data == data


def test_removing_a_nested_element_shrinks_the_pointee_around_it() -> None:
    from tests.prefab_collection_builder import build_nested_groups

    data = build_nested_groups(("Alpha", "Beta", "Gamma"))
    before = decode_prefab_binary(data)
    site, field = _holder_field(before)
    start, end = before.collections[1].elements[1]

    shrunk = remove_prefab_element(data, 1, 1).data

    delta = start - end
    assert struct.unpack_from("<I", shrunk, field + delta)[0] == struct.unpack_from("<I", data, field)[0] + delta
    assert decode_prefab_binary(shrunk).collections[1].count == 2


def test_a_resize_that_leaves_an_enclosing_length_stale_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The read-back check, not the writer, is what catches a missed field."""
    from cdmw.core import prefab_array_edit
    from tests.prefab_collection_builder import build_nested_groups

    monkeypatch.setattr(prefab_array_edit, "_enclosing_fields", lambda *args, **kwargs: {})

    # Either the walk no longer closes (the stale field is left over) or it
    # closes with one field fewer; both are refusals.
    with pytest.raises(PrefabEditError, match="no longer reads all the way|pointee length field"):
        duplicate_prefab_element(build_nested_groups(), 1, 0)
