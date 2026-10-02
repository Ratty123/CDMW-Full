import json
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.archive_resident_index import ResidentArchiveIndex, ResidentArchiveSource
from cdmw.core.item_sources import ItemDataSources
from cdmw.domain.archives.catalogue import ArchiveSessionHandle
from cdmw.models import RunCancelled
from cdmw.services.new_item_service import NewItemService
from cdmw.workers.new_item_workers import snapshot_task
from tests.archive_resident_index_fixtures import write_dependency_index, write_resident_index
from tests.test_new_item_service import TEMPLATE, _read, build_package, synthetic_files


@pytest.fixture
def catalogue(tmp_path):
    root = tmp_path / "packages"
    files = synthetic_files()
    files.update({f"unrelated/textures/image_{index}.dds": b"x" for index in range(1000)})
    files["character/model/1_pc/1_phm/armor/15_vest/fixture.pac"] = b"synthetic wearable"
    files["character/motion/1_pc/1_phm/idle.paa"] = b"synthetic clip"
    entries = tuple(sorted(parse_archive_pamt(build_package(root, files)), key=lambda entry: entry.path.encode().lower()))
    return root, entries, write_resident_index(root, entries, tmp_path / "generation")


def test_resident_index_reads_exact_locations_and_reuses_generation(catalogue):
    _root, entries, source = catalogue
    index = source.open()
    assert len(index) == len(entries)
    assert list(index) == list(entries)
    assert source.open() is index
    expected = [entry for entry in entries if entry.extension == ".pac"]
    assert list(index.by_extension[".pac"]) == expected
    assert list(index.matching((".pac",))) == expected
    for entry in expected:
        assert list(index.by_path[entry.path.lower()]) == [entry]
        assert list(index.by_basename[entry.basename.lower()]) == [entry]


def test_recent_row_paths_and_source_paths_are_reused_in_a_bounded_cache(catalogue, monkeypatch):
    _root, entries, source = catalogue
    index = source.open()
    expected = tuple((entry.path, str(entry.pamt_path.parent).replace("\\", "/").casefold()) for entry in entries)
    tuple(index)  # Prime each archive payload file path, which remains decoded on demand.
    monkeypatch.setattr(index, "_string", lambda *args: pytest.fail("resident path or owner decoded again"))
    monkeypatch.setattr(index, "_path_bytes", lambda *args: pytest.fail("recent row path decoded again"))
    assert len(index._row_paths) <= 256
    for row in range(len(entries) - 10, len(entries)):
        path, package = expected[row]
        assert index._package_for_row(row) == package
        assert index[row].path == path


def test_open_does_not_visit_rows_and_exact_lookups_use_the_mapped_indexes(catalogue, monkeypatch):
    _root, entries, source = catalogue
    with patch.object(ResidentArchiveIndex, '_path_bytes', side_effect=AssertionError('enumerated at open')):
        index = source.open()
    assert not index._row_paths and not index._lookups and index._extensions is None
    # Truthiness is used repeatedly during snapshot construction. It must not
    # count every distinct path or basename before an exact lookup can start.
    with patch.object(index, '_scan_rows', side_effect=AssertionError('enumerated for lookup')):
        assert index.by_path and index.by_basename and index.by_extension
        expected = entries[-1]
        assert list(index.by_path[expected.path.lower()]) == [expected]
        assert list(index.by_basename[expected.basename.lower()]) == [expected]
        assert index.active_entry(expected.path.upper().replace('/', '\\')) == expected
    assert index._dependency_mapping is not None


def test_query_caches_remain_bounded_after_many_models_and_textures(catalogue):
    _root, entries, source = catalogue
    index = source.open()
    for entry in entries:
        assert index.by_path[entry.path.lower()][0] == entry
        assert index.by_basename[entry.basename.lower()][0] == entry
    assert len(index._lookups) <= 256
    assert len(index._row_paths) <= 256
    assert len(index._source_paths) <= 256


def test_large_extension_groups_stream_and_support_sequence_operations(catalogue, tmp_path, monkeypatch):
    monkeypatch.setattr('cdmw.core.archive_resident_index._CACHED_EXTENSION_ROWS', 1024)
    root, entries, _source = catalogue
    rows = [replace(entries[0], path=f'texture/image_{row:05}.dds') for row in range(5000)]
    index = write_resident_index(root, rows, tmp_path / 'large-extension').open()
    group = index.by_extension['.dds']
    assert len(group) == len(rows)
    assert list(group[:3]) == rows[:3]
    assert group[-1] == rows[-1]
    assert list(group[20:2:-3]) == rows[20:2:-3]
    assert list(group[::-997]) == rows[::-997]
    assert index._extensions['.dds'][1] is None
    assert list(index.by_extension.get('.missing', ())) == []
    assert len(index._row_paths) <= 256


def test_extension_row_cache_has_a_shared_budget(catalogue, tmp_path, monkeypatch):
    monkeypatch.setattr('cdmw.core.archive_resident_index._EXTENSION_ROW_BUDGET', 100)
    root, entries, _source = catalogue
    rows = [replace(entries[0], path=f'asset/{row:03}.ext{kind}')
            for kind in range(5) for row in range(40)]
    index = write_resident_index(root, rows, tmp_path / 'extension-budget').open()
    assert {entry.path for entry in index.by_extension['.ext3']} == {
        entry.path for entry in rows if entry.extension == '.ext3'}
    assert sum(len(group[1]) for group in index._extensions.values() if group[1] is not None) <= 100


@pytest.mark.parametrize('derived_state', ['missing', 'truncated', 'stale'])
def test_basename_queries_stream_without_valid_derived_data_then_adopt_publication(catalogue, monkeypatch, derived_state):
    _root, entries, source = catalogue
    derived = Path(source.index_path).with_suffix('.adi')
    if derived_state == 'missing':
        derived.unlink()
    elif derived_state == 'truncated':
        derived.write_bytes(b'CDMWADI1')
    else:
        import struct
        data = bytearray(derived.read_bytes())
        struct.pack_into('<Q', data, 64, 1)  # Wrong source-index size.
        derived.write_bytes(data)
    now = [1.]
    monkeypatch.setattr('cdmw.core.archive_resident_index.time.monotonic', lambda: now[0])
    index = source.open()
    expected = entries[-1]
    assert list(index.by_basename[expected.basename.lower()]) == [expected]
    assert index._dependency_mapping is None
    assert list(index.by_basename.candidate_keys(suffix='.pac')) == list(dict.fromkeys(
        entry.basename.lower() for entry in entries if entry.extension == '.pac'))
    write_dependency_index(source, entries)
    now[0] += 2
    another = entries[-2]
    with patch.object(index, '_scan_rows', side_effect=AssertionError('did not adopt derived index')):
        assert list(index.by_basename[another.basename.lower()]) == [another]
    assert index._dependency_mapping is not None


def test_basename_hash_collisions_do_not_return_unrelated_records(catalogue, monkeypatch):
    _root, entries, source = catalogue
    write_dependency_index(source, entries, basename_hash=lambda _: 7)
    monkeypatch.setattr('cdmw.core.archive_resident_index._basename_hash', lambda _: 7)
    index = source.open()
    expected = entries[-1]
    assert list(index.by_basename[expected.basename.lower()]) == [expected]
    assert index.by_basename.get('absent.dds') is None


def test_path_order_and_duplicate_groups_preserve_case_and_override_flags(catalogue, tmp_path):
    root, entries, _source = catalogue
    # ASCII folding orders '_' before lowercase letters; uppercase folding does
    # not. This is the real FAI3 ordering used by its writer and native readers.
    (root / 'meta' / '0.papgt').unlink()
    first = replace(entries[0], path='Model/_sword.PAC')
    duplicate = replace(first, offset=first.offset + 1)
    later = replace(first, path='model/Asword.pac')
    unicode = replace(first, path='model/Äsword.pac')
    index = write_resident_index(root, [later, first, duplicate, unicode], tmp_path / 'path-order',
                                 override_flags=(0, 2, 3, 0)).open()
    assert list(index.by_path['model/_sword.pac']) == [first, duplicate]
    assert index.active_entry('MODEL/_SWORD.PAC') == duplicate
    assert index.active_entry('model/asword.pac') == later
    assert index.active_entry('model/äsword.pac') == unicode
    assert list(index.by_basename['äsword.pac']) == [unicode]
    assert list(index.matching(('.pac',), contains='_sword')) == [duplicate]
    assert list(index.matching(('.pac',), contains='_sword', active_only=False)) == [first, duplicate]


def test_cancelled_extension_scan_does_not_publish_partial_groups_or_poison_reuse(catalogue, tmp_path):
    root, entries, _source = catalogue
    rows = [replace(entries[0], path=f'model/image_{row:05}.pac') for row in range(5000)]
    source = write_resident_index(root, rows, tmp_path / 'cancelled-extension')
    index = source.open()
    checks = []

    def stopped():
        checks.append(True)
        return len(checks) >= 3

    with pytest.raises(RunCancelled):
        list(index.matching(('.pac',), stop_event=stopped))
    assert index._extensions is None
    assert list(index.matching(('.pac',))) == rows
    assert source.open() is index
    with pytest.raises(RunCancelled):
        list(index.matching(('.pac',), stop_event=lambda: True))
    assert index.active_entry(rows[-1].path) == rows[-1]


def test_nonadjacent_unicode_duplicates_keep_the_global_mount_winner(catalogue, tmp_path):
    from cdmw.core.papgt_format import PAPGT_DEFAULT_FLAGS, PapgtDirectory, serialize_papgt
    root, entries, _source = catalogue
    other_pamt = root / '0010' / '0.pamt'
    other_pamt.parent.mkdir()
    other_pamt.write_bytes(b'owned overlay fixture')
    first = replace(entries[0], path='model/Äsword.pac')
    between = replace(first, path='model/Åsword.pac')
    winner = replace(first, path='model/äsword.pac', pamt_path=other_pamt)
    (root / 'meta' / '0.papgt').write_bytes(serialize_papgt([
        PapgtDirectory('0010', PAPGT_DEFAULT_FLAGS, 0), PapgtDirectory('0009', PAPGT_DEFAULT_FLAGS, 0),
    ]))
    index = write_resident_index(root, [first, between, winner], tmp_path / 'unicode-mounts').open()
    assert index.active_entry(first.path) == winner
    assert list(index.matching(('.pac',))) == [between, winner]
    assert list(index.by_path) == ['model/äsword.pac', 'model/åsword.pac']
    assert len(index.by_path) == 2


def test_unicode_ascii_casing_aliases_keep_lookup_filters_and_mount_priority(catalogue, tmp_path):
    from cdmw.core.papgt_format import PAPGT_DEFAULT_FLAGS, PapgtDirectory, serialize_papgt
    root, entries, _source = catalogue
    other_pamt = root / '0010' / '0.pamt'
    other_pamt.parent.mkdir()
    other_pamt.write_bytes(b'owned overlay fixture')
    first = replace(entries[0], path='model/ksword.pac')
    between = replace(first, path='model/zsword.pac')
    winner = replace(first, path='model/\u212asword.pac', pamt_path=other_pamt)
    (root / 'meta' / '0.papgt').write_bytes(serialize_papgt([
        PapgtDirectory('0010', PAPGT_DEFAULT_FLAGS, 0), PapgtDirectory('0009', PAPGT_DEFAULT_FLAGS, 0),
    ]))
    index = write_resident_index(root, [winner, between, first], tmp_path / 'unicode-ascii-alias').open()
    assert list(index.by_path[first.path]) == [first, winner]
    assert list(index.by_basename[first.basename]) == [first, winner]
    assert index.active_entry(first.path) == winner
    assert list(index.matching(('.pac',), contains='ksword')) == [winner]
    assert list(index.by_path) == [first.path, between.path]
    assert list(index.by_basename.candidate_keys(contains='k', suffix='.pac')) == [first.basename]


def test_unicode_extension_casing_keeps_the_full_name_context(catalogue, tmp_path, monkeypatch):
    root, entries, _source = catalogue
    row = replace(entries[0], path='model/A.\u03a3')
    index = write_resident_index(root, [row], tmp_path / 'unicode-extension').open()
    expected = '.' + row.path.lower().rsplit('.', 1)[-1]
    assert list(index.by_extension[expected]) == [row]
    assert list(index.by_extension) == [expected]
    # Also exercise the streaming-key branch when the extension-key budget is
    # exhausted, so iterating groups and querying them use the same casing.
    monkeypatch.setattr('cdmw.core.archive_resident_index._EXTENSION_CACHE_SIZE', 0)
    streamed = write_resident_index(root, [row], tmp_path / 'unicode-extension-streamed').open()
    assert list(streamed.by_extension) == [expected]
    assert list(streamed.by_extension[expected]) == [row]


@pytest.mark.parametrize('filtered', [False, True])
def test_skeleton_search_filters_names_before_decoding_records(catalogue, tmp_path, monkeypatch, filtered):
    from cdmw.core.skeleton_resolver import _all_indexed_pab_candidates, _descriptor_candidates_for_model

    root, entries, _source = catalogue
    model = replace(entries[0], path='character/model/fixture.pac')
    descriptor = replace(entries[0], path='character/prefab/fixture.prefabdata_xml')
    alternate = replace(entries[0], path='character/prefab/fixture.prefabdata.xml')
    skeleton = replace(entries[0], path='character/skeleton/fixture.pab')
    excluded_pamt = root / '0010' / '0.pamt'
    excluded_pamt.parent.mkdir()
    excluded_pamt.write_bytes(b'owned index fixture')
    excluded = replace(skeleton, path='character/skeleton/obsolete.pab', pamt_path=excluded_pamt)
    source = write_resident_index(root, (*entries, model, descriptor, alternate, skeleton, excluded),
                                  tmp_path / 'skeleton-generation')
    index = source.open()
    sources = ItemDataSources({}, {}, False,
        frozenset((str(excluded_pamt.parent).replace('\\', '/').casefold(),)) if filtered else frozenset(), {})
    by_path, by_name = index.index_maps(sources)
    get_entry = ResidentArchiveIndex.__getitem__
    decoded = []

    def tracked(index, row):
        entry = get_entry(index, row)
        assert 'prefabdata' in entry.basename or entry.extension == '.pab'
        decoded.append(entry.path)
        return entry

    monkeypatch.setattr(ResidentArchiveIndex, '__getitem__', tracked)
    descriptors = _descriptor_candidates_for_model(model, archive_entries=(),
        archive_entries_by_normalized_path=by_path, archive_entries_by_basename=by_name)
    assert {entry.path for entry in descriptors} == {descriptor.path, alternate.path}
    skeletons = _all_indexed_pab_candidates(archive_entries=(), archive_entries_by_basename=by_name)
    assert skeletons == ((skeleton,) if filtered else (skeleton, excluded))
    assert len(decoded) < 12


def test_snapshot_uses_shared_metadata_without_listing_or_decoding_unrelated_entries(catalogue):
    root, _entries, source = catalogue
    materialized = []
    original = ResidentArchiveIndex.__getitem__

    def record(index, row):
        result = original(index, row)
        materialized.append(result.path)
        return result

    with (patch("cdmw.workers.new_item_workers.list_archive_entries", side_effect=AssertionError("relisted")),
          patch.object(ResidentArchiveIndex, "__getitem__", record)):
        snapshot = snapshot_task((), service=NewItemService(), read_entry=_read,
                                 package_root=root, resident_source=source)(lambda _: None, threading.Event())
    assert TEMPLATE in snapshot.rows
    assert len(materialized) < 100
    assert not any(path.startswith("unrelated/") for path in materialized)
    assert snapshot.has_entry("unrelated/textures/image_1.dds")
    assert snapshot.entry("unrelated/textures/image_1.dds").comp_size == 1
    by_path, by_name = snapshot.archive_index_maps()
    assert by_name["image_1.dds"][0] == by_path["unrelated/textures/image_1.dds"][0]


def test_resident_index_rejects_source_changes_before_reuse(catalogue):
    _root, entries, source = catalogue
    source.open()
    with entries[0].pamt_path.open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(ValueError, match="Archive source changed"):
        source.open()


def test_parsed_item_tables_are_reused_with_independent_planning_caches(catalogue):
    _root, _entries, source = catalogue
    service = NewItemService()
    index = source.open()
    first = service.build_snapshot((), read_entry=_read, resident_catalogue=index)
    first._contexts[999] = object()
    first._payloads["draft-only"] = b"draft"
    with patch("cdmw.services.new_item_service.build_snapshot", side_effect=AssertionError("reparsed")):
        second = service.build_snapshot((), read_entry=_read, resident_catalogue=index)
    assert second is not first
    assert second.rows is first.rows
    assert not second._contexts and not second._payloads
    with first.iteminfo.payload_entry.pamt_path.open("ab") as handle:
        handle.write(b"new generation")
    with pytest.raises(ValueError, match="Archive source changed"):
        service.build_snapshot((), read_entry=_read, resident_catalogue=index)


def test_resident_index_rejects_wrong_generation_and_truncated_records(catalogue):
    _root, _entries, source = catalogue
    with pytest.raises(ValueError, match="generation changed"):
        replace(source, fingerprint="another-generation").open()
    Path(source.index_path).write_bytes(b"CDMWFAI3")
    with pytest.raises(ValueError, match="header is truncated"):
        source.open()


def test_resident_index_cancellation_does_not_publish_partial_lookups(catalogue):
    _root, _entries, source = catalogue
    stop = threading.Event()
    stop.set()
    with pytest.raises(RunCancelled):
        source.open(stop)
    assert source.open().by_extension[".pac"]


def test_selected_sources_exclude_obsolete_packages_and_keep_mount_priority(catalogue, tmp_path):
    root, entries, _source = catalogue
    first = next(entry for entry in entries if entry.extension == ".pac")
    other_pamt = root / "0010" / "0.pamt"
    other_pamt.parent.mkdir()
    other_pamt.write_bytes(b"another table")
    newer = replace(first, pamt_path=other_pamt)
    source = write_resident_index(root, [first, newer], tmp_path / "duplicates", override_flags=(2, 3))
    index = source.open()
    old_package = str(first.pamt_path.parent).replace("\\", "/").casefold()
    new_package = str(newer.pamt_path.parent).replace("\\", "/").casefold()
    sources = ItemDataSources({}, {}, False, frozenset((old_package,)), {old_package: 2, new_package: 1})
    selected = index.selected_paths(sources)
    assert list(selected) == [first.path.lower()]
    assert selected[first.path.lower()] == newer
    # 0010 is not mounted in the fixture PAPGT even though its cached duplicate
    # flag says active. The authoritative mount list takes precedence.
    assert list(index.matching((".pac",))) == [first]
    assert list(index.index_maps(sources)[1][first.basename.lower()]) == [newer]


def test_session_handle_captures_only_the_matching_resident_catalogue(catalogue):
    root, entries, source = catalogue
    wire = {"session_id": "test", "package_root": str(root), "fingerprint": source.fingerprint,
            "entry_count": len(entries), "index_version": 3, "cache_hit": True}
    legacy = ArchiveSessionHandle.from_wire(wire)
    assert ResidentArchiveSource.capture(SimpleNamespace(current_session=legacy), root) is None
    session = ArchiveSessionHandle.from_wire({**wire, "index_path": source.index_path})
    assert ResidentArchiveSource.capture(SimpleNamespace(current_session=session), root) == source
    assert ResidentArchiveSource.capture(SimpleNamespace(current_session=session), root / "other") is None


def test_placement_catalogues_and_baseline_use_resident_entries(catalogue, monkeypatch, tmp_path):
    from tools.placement_studio.armour import index_wearables
    from tools.placement_studio.clips import scan_archives
    from tools.placement_studio.corpus import archive_entry_sizes, extract_baseline
    root, _entries, source = catalogue
    monkeypatch.setenv("CDMW_PS_GAME_ROOT", str(root))
    with patch("cdmw.core.archive_format.parse_archive_pamt", side_effect=AssertionError("parsed PAMT again")):
        wearables, _sockets, _meshes = index_wearables(root, cache=False, resident_source=source)
        assert any(piece.name == "fixture" for piece in wearables.all_pieces())
        clips = list(scan_archives(root, cache=False, resident_source=source))[-1][2]
        assert clips is not None
        index = source.open()
        sizes = archive_entry_sizes(".pac", contains="/armor/", resident_catalogue=index)
        assert sizes == {"character/model/1_pc/1_phm/armor/15_vest/fixture.pac": len(b"synthetic wearable")}
        baseline = extract_baseline(sizes, out_root=tmp_path / "baseline", resident_catalogue=index)
        assert baseline.read(next(iter(sizes))) == b"synthetic wearable"


def test_resident_index_respects_mount_order_for_the_first_record(catalogue, tmp_path):
    from cdmw.core.papgt_format import PAPGT_DEFAULT_FLAGS, PapgtDirectory, serialize_papgt
    root, entries, _source = catalogue
    first = next(entry for entry in entries if entry.extension == ".pac")
    other_pamt = root / "0010" / "0.pamt"
    other_pamt.parent.mkdir()
    other_pamt.write_bytes(b"another table")
    other = replace(first, pamt_path=other_pamt)
    (root / "meta" / "0.papgt").write_bytes(serialize_papgt([
        PapgtDirectory("0009", PAPGT_DEFAULT_FLAGS, 0), PapgtDirectory("0010", PAPGT_DEFAULT_FLAGS, 0),
    ]))
    source = write_resident_index(root, [first, other], tmp_path / "mount-order", override_flags=(2, 3))
    assert list(source.open().matching((".pac",))) == [first]
    assert source.open().active_entry(first.path) == first
    with pytest.raises(ValueError, match="root changed"):
        source.open(package_root=root / "changed")
