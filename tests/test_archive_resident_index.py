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
from tests.archive_resident_index_fixtures import write_resident_index
from tests.test_new_item_service import TEMPLATE, _read, build_package, synthetic_files


@pytest.fixture
def catalogue(tmp_path):
    root = tmp_path / "packages"
    files = synthetic_files()
    files.update({f"unrelated/textures/image_{index}.dds": b"x" for index in range(1000)})
    files["character/model/1_pc/1_phm/armor/15_vest/fixture.pac"] = b"synthetic wearable"
    files["character/motion/1_pc/1_phm/idle.paa"] = b"synthetic clip"
    entries = tuple(parse_archive_pamt(build_package(root, files)))
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


def test_row_paths_and_package_ownership_are_reused_without_string_decode(catalogue, monkeypatch):
    _root, entries, source = catalogue
    index = source.open()
    expected = tuple((entry.path, str(entry.pamt_path.parent).replace("\\", "/").casefold()) for entry in entries)
    tuple(index)  # Prime each archive payload file path, which remains decoded on demand.
    monkeypatch.setattr(index, "_string", lambda *args: pytest.fail("resident path or owner decoded again"))
    for row, (path, package) in enumerate(expected):
        assert index._package_for_row(row) == package
        assert index[row].path == path


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
