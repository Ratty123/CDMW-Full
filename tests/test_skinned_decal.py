"""Owned PASEQ fixtures: shared strings, presence masks and exact preservation."""
import struct
import threading
from pathlib import Path

import pytest

from cdmw.core.prefab_binary import PrefabMember, PrefabType
from cdmw.core.prefab_component_graft import encode_prefab_type
from cdmw.core.skinned_decal import SkinnedDecalError, _parse, read_skinned_decal, write_skinned_decal


def sequence_fixture(revision=14, *, persistent=True, inline=False):
    def member(name, kind, size, typename):
        return PrefabMember(name, typename, kind, size, 0, 0)
    types = (
        PrefabType("Sequencer", (member("_events", 7, 0, "ReflectObjectPtr"),), 0),
        PrefabType("GameSkinnedDecalEventData", (
            member("_skinnedDecalProperty", 5, 8, "ReflectObjectPtr"),
            member("_opacity", 0, 4, "float")), 0),
        PrefabType("SkinnedDecalProperty", (
            member("_decalNormalTexture", 4, 8, "ReflectObject"),
            member("_decalMaskTexture", 4, 8, "ReflectObject"),
            member("_slopeBias", 0, 4, "float"),
            member("_isPersistent", 0, 1, "bool"),
            member("_unowned", 0, 8, "uint64")), 0),
        PrefabType("ResourceReferencePath_ITexture", (member("_path", 1, 1, "staticstringA"),), 0),
    )
    prefix = bytes(16) + struct.pack("<HHHIH", 0xFFFF, 3, 0, revision, len(types))
    prefix += b"".join(encode_prefab_type(t) for t in types)
    if revision == 14:
        prefix += bytes(4)
    text = b"texture/shared.dds"
    prefix += struct.pack("<III", 1, 0, len(text)) + text
    blob_start = len(prefix) + 28
    blob = bytearray()

    def header(index, mask):
        blob.extend(struct.pack("<HBHB", 1, mask, index, 0))

    def record(index, mask, emit):
        header(index, mask)
        blob.extend(struct.pack("<Q", 0x12345678))
        blob.extend(struct.pack("<I", blob_start + len(blob) + 4 - 16))
        start = len(blob)
        blob.extend(bytes(4))
        emit()
        blob.extend(struct.pack("<I", len(blob) - start))

    def property_values():
        record(3, 1, lambda: blob.extend(struct.pack("<II", 0xFFFFFFFF, len(text)) + text if inline else bytes(4)))
        record(3, 1, lambda: blob.extend(bytes(4)))
        blob.extend(struct.pack("<f", 0.5))
        if persistent:
            blob.append(0)  # Explicit false must remain distinct from absence.
        blob.extend(struct.pack("<Q", 0xBADC0FFEE))

    def event_values():
        blob.append(1)
        record(2, 31 if persistent else 23, property_values)
        blob.extend(struct.pack("<f", 0.75))

    header(0, 0)
    blob.append(0)
    blob.extend(struct.pack("<I", 1))
    if revision == 14:
        blob.append(0)
    blob.extend(bytes(12))
    record(1, 3, event_values)
    offset = blob_start - 16
    directory = struct.pack("<IIIQII", 1, offset + len(blob), 0, 0xFFFFFFFFFFFFFFFF, offset, len(blob))
    trailer = struct.pack("<HHHIH", 0xFFFF, 3, 0, revision, 0)
    trailer += bytes(12 if revision == 14 else 8) + struct.pack("<I", 28 if revision == 14 else 24)
    return prefix + directory + blob + trailer


@pytest.mark.parametrize("revision", [13, 14])
@pytest.mark.parametrize("persistent", [False, True])
def test_noop_is_exact_including_omitted_and_explicit_false(revision, persistent):
    source = sequence_fixture(revision, persistent=persistent)
    document = read_skinned_decal(source)
    assert write_skinned_decal(document, {}) == source
    assert write_skinned_decal(document, {f.path: f.text() for f in document.fields}) == source
    fields = {f.name: f for f in document.fields}
    assert ("_isPersistent" in fields) is persistent
    if persistent:
        assert fields["_isPersistent"].value is False


@pytest.mark.parametrize("revision", [13, 14])
@pytest.mark.parametrize("inline", [False, True])
@pytest.mark.parametrize("replacement", ["a.dds", "effect/texture/a_much_longer_unique_normal_map.dds"])
def test_resized_texture_changes_only_selected_reference_and_relocation(revision, inline, replacement):
    source = sequence_fixture(revision, inline=inline)
    document, _, walker, _, pool_site, header_site = _parse(source)
    field = next(f for f in document.fields if "_decalNormalTexture" in f.path)
    output = write_skinned_decal(document, {field.path: replacement})
    reopened = read_skinned_decal(output)
    values = {f.path: f.value for f in reopened.fields}
    assert values[field.path] == replacement
    for other in document.fields:
        if other.path != field.path:
            assert values[other.path] == other.value
    # Undo the selected reference, inserted pool entry and required relocation.
    # EVERY other byte, including unknown values and masks, must equal the source.
    new_header = _parse(output)[-1]
    restored = bytearray(output[:header_site] + output[new_header:])
    restored[field.offset:field.offset + 4] = source[field.offset:field.offset + field.wire_size]
    for site in (pool_site, header_site + 4, header_site + 20, header_site + 24, *walker.pointer_sites,
                 *(site for site, _ in walker.length_sites)):
        restored[site:site + 4] = source[site:site + 4]
    assert bytes(restored) == source


def test_multiple_edits_keep_noop_and_shared_references_independent():
    document = read_skinned_decal(sequence_fixture(inline=True))
    changes = {f.path: "texture/unique.dds" if f.kind == 1 else "0.125" for f in document.fields
               if f.kind == 1 or f.name == "_opacity"}
    edited = read_skinned_decal(write_skinned_decal(document, changes))
    assert write_skinned_decal(edited, {}) == edited.source
    assert all(f.value == "texture/unique.dds" for f in edited.fields if f.kind == 1)


@pytest.mark.parametrize("setting,text", [("_opacity", "0"), ("_slopeBias", "-0.25"), ("_isPersistent", "true")])
def test_existing_numeric_and_boolean_change_only_their_value_bytes(setting, text):
    source = sequence_fixture()
    document = read_skinned_decal(source)
    field = next(f for f in document.fields if f.name == setting)
    output = write_skinned_decal(document, {field.path: text})
    assert len(output) == len(source)
    assert output[:field.offset] == source[:field.offset]
    assert output[field.offset + len(field.raw):] == source[field.offset + len(field.raw):]
    assert output != source


@pytest.mark.parametrize("text", ["NaN", "Infinity", "1e100", "true", "[1,2]"])
def test_invalid_numeric_values_are_refused(text):
    document = read_skinned_decal(sequence_fixture())
    field = next(f for f in document.fields if f.name == "_opacity")
    with pytest.raises(SkinnedDecalError):
        write_skinned_decal(document, {field.path: text})


@pytest.mark.parametrize("path", ["", "../a.dds", "C:/a.dds", "/a.dds", "texture\\a.dds", "a.png", "a\x00.dds"])
def test_invalid_texture_references_are_refused(path):
    document = read_skinned_decal(sequence_fixture())
    field = next(f for f in document.fields if f.name == "_path")
    with pytest.raises(SkinnedDecalError):
        write_skinned_decal(document, {field.path: path})


def test_absent_setting_and_unsupported_tail_are_refused():
    source = sequence_fixture(persistent=False)
    document = read_skinned_decal(source)
    with pytest.raises(SkinnedDecalError):
        write_skinned_decal(document, {"[0]._events[0]._skinnedDecalProperty._isPersistent": "false"})
    for broken in (source[:-1], source + b"unknown", bytes(16) + source[16:22] + struct.pack("<I", 15) + source[26:]):
        with pytest.raises(SkinnedDecalError):
            read_skinned_decal(broken)


def test_service_cancellation_and_failure_preserve_existing_destination(tmp_path, monkeypatch):
    from cdmw.models import ArchiveEntry, RunCancelled
    from cdmw.services import skinned_decal_service as service
    source = sequence_fixture()
    entry = ArchiveEntry("test.paseq", Path("0.pamt"), Path("0.paz"), 1, 0, len(source), len(source), 0)
    monkeypatch.setattr(service, "read_archive_entry_data", lambda *a, **kw: (source, False, ""))
    loaded = service.load_decal_source(entry)
    path = tmp_path / "out.paseq"
    path.write_bytes(b"previous")
    request = service.DecalSaveRequest(loaded.document, path, ())
    stop = threading.Event()
    stop.set()
    with pytest.raises(RunCancelled):
        service.save_decal_copy(request, stop_event=stop)
    assert path.read_bytes() == b"previous"
    with pytest.raises(SkinnedDecalError):
        service.save_decal_copy(service.DecalSaveRequest(loaded.document, path, (("absent", "0"),)))
    assert path.read_bytes() == b"previous"
    assert service.save_decal_copy(request) == path
    assert path.read_bytes() == source
