"""Original PAMT evidence across ordinary and resident authoring consumers."""
import hashlib
import threading

import pytest

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.services.new_item_provenance import StaleNewItemSource
from cdmw.services.new_item_service import NewItemService
from cdmw.workers.new_item_workers import list_archive_entries, snapshot_task
from tests.archive_resident_index_fixtures import write_resident_index
from tests.test_independent_item_index_witness import index_fixture, replace_index
from tests.test_new_item_provenance import spec
from tests.test_new_item_service import TEMPLATE, _read


def hide_index_stat_change(monkeypatch, pamt):
    """Hold the complete existing file-stamp contract equal, including ctime."""
    import cdmw.services.new_item_provenance as provenance
    stamp = provenance._stamp
    original = stamp(pamt)
    monkeypatch.setattr(provenance, '_stamp', lambda path: original if path == pamt else stamp(path))


@pytest.mark.parametrize('same_stamp', [False, True])
def test_raw_snapshot_refuses_original_coordinates_after_valid_index_remap(tmp_path, monkeypatch, same_stamp):
    pamt, original, changed = index_fixture(tmp_path)
    entries = parse_archive_pamt(pamt)
    hide_index_stat_change(monkeypatch, pamt)
    replace_index(pamt, changed, same_stamp)
    with pytest.raises(StaleNewItemSource, match='[Ii]ndex'):
        NewItemService().build_snapshot(entries, read_entry=_read)
    assert pamt.read_bytes() == changed != original


def test_snapshot_worker_keeps_listing_witness_before_the_first_payload_read(tmp_path, monkeypatch):
    pamt, _, changed = index_fixture(tmp_path)
    hide_index_stat_change(monkeypatch, pamt)

    class ReplacedIndexService(NewItemService):
        def build_snapshot(self, entries, **kwargs):
            replace_index(pamt, changed, True)
            return super().build_snapshot(entries, **kwargs)

    with pytest.raises(StaleNewItemSource, match='[Ii]ndex'):
        snapshot_task((), service=ReplacedIndexService(), read_entry=_read,
                      package_root=tmp_path / 'game')(lambda _: None, threading.Event())


@pytest.mark.parametrize('cached', [False, True])
def test_resident_snapshot_refuses_remapped_index_with_identical_stat_values(tmp_path, monkeypatch, cached):
    pamt, _, changed = index_fixture(tmp_path)
    root = tmp_path / 'game'
    source = write_resident_index(root, parse_archive_pamt(pamt), tmp_path / 'generation')
    catalogue = source.open()
    service = NewItemService()
    hide_index_stat_change(monkeypatch, pamt)
    if cached:
        assert service.build_snapshot((), read_entry=_read, resident_catalogue=catalogue).rows[TEMPLATE].max_stack_count == 1
    replace_index(pamt, changed, True)
    with pytest.raises(StaleNewItemSource, match='[Ii]ndex'):
        service.build_snapshot((), read_entry=_read, resident_catalogue=catalogue)


@pytest.mark.parametrize('route', ['raw', 'listing', 'resident'])
def test_unchanged_authoring_exports_with_original_index_witness(tmp_path, route):
    pamt, original, _ = index_fixture(tmp_path)
    root = tmp_path / 'game'
    service = NewItemService()
    if route == 'resident':
        source = write_resident_index(root, parse_archive_pamt(pamt), tmp_path / 'generation')
        snapshot = service.build_snapshot((), read_entry=_read, resident_catalogue=source.open())
    else:
        entries = parse_archive_pamt(pamt) if route == 'raw' else list_archive_entries(root, lambda _: None, None)
        snapshot = snapshot_task(entries, service=service, read_entry=_read,
                                 package_root=root)(lambda _: None, threading.Event())
    expected = (pamt, hashlib.sha256(original).hexdigest())
    assert expected in snapshot.provenance.capture().indexes
    plan = service.plan(spec('Witnessed'), snapshot)
    assert expected in plan.source_revision.indexes
    plan.source_revision.validate()
    result = service.export_loose(plan, tmp_path / 'output', manager='JMM')
    assert (tmp_path / 'output/new-item.json').is_file()
    assert result is not None and pamt.read_bytes() == original


def test_mod_base_rejects_index_remapped_after_folder_parse(tmp_path, monkeypatch):
    import cdmw.core.archive_format as archive_format
    from cdmw.services.new_item_mod_base import build_mod_base_snapshot
    game_pamt, _, _ = index_fixture(tmp_path / 'stock')
    service = NewItemService()
    snapshot = service.build_snapshot(parse_archive_pamt(game_pamt), read_entry=_read)
    mod_pamt, _, changed = index_fixture(tmp_path / 'mod')
    hide_index_stat_change(monkeypatch, mod_pamt)
    parse = archive_format._parse_archive_pamt_bytes

    def remap(data, path, **kwargs):
        result = parse(data, path, **kwargs)
        if path == mod_pamt:
            replace_index(mod_pamt, changed, True)
        return result

    monkeypatch.setattr(archive_format, '_parse_archive_pamt_bytes', remap)
    with pytest.raises(StaleNewItemSource, match='[Ii]ndex'):
        build_mod_base_snapshot(service, snapshot, mod_pamt.parent.parent, read_entry=_read)


def test_generic_merge_rejects_folder_index_remapped_after_parse(tmp_path, monkeypatch):
    import cdmw.core.archive_format as archive_format
    from cdmw.services.mod_merge_service import prepare_mod_merge
    game_pamt, _, _ = index_fixture(tmp_path / 'stock')
    entries = parse_archive_pamt(game_pamt)
    mod_pamt, _, changed = index_fixture(tmp_path / 'mod')
    other = tmp_path / 'other'
    (other / 'character').mkdir(parents=True)
    (other / 'character/other.bin').write_bytes(b'owned synthetic bytes')
    hide_index_stat_change(monkeypatch, mod_pamt)
    parse = archive_format._parse_archive_pamt_bytes

    def remap(data, path, **kwargs):
        result = parse(data, path, **kwargs)
        if path == mod_pamt:
            replace_index(mod_pamt, changed, True)
        return result

    monkeypatch.setattr(archive_format, '_parse_archive_pamt_bytes', remap)
    with pytest.raises(StaleNewItemSource, match='[Ii]ndex'):
        prepare_mod_merge((mod_pamt.parent.parent, other), game_pamt.parent.parent,
                          entries=entries, read_entry=_read)


def test_generic_merge_retains_and_checks_the_game_catalogue_witness(tmp_path, monkeypatch):
    from cdmw.services.mod_merge_service import prepare_mod_merge
    pamt, _, changed = index_fixture(tmp_path)
    entries = list_archive_entries(tmp_path / 'game', lambda _: None, None)
    folders = (tmp_path / 'first', tmp_path / 'second')
    for index, folder in enumerate(folders):
        (folder / 'character').mkdir(parents=True)
        (folder / f'character/resource{index}.bin').write_bytes(b'owned fixture')
    hide_index_stat_change(monkeypatch, pamt)
    replace_index(pamt, changed, True)
    with pytest.raises(StaleNewItemSource, match='[Ii]ndex'):
        prepare_mod_merge(folders, tmp_path / 'game', entries=entries, read_entry=_read)


def test_mod_base_retains_both_original_stock_and_folder_index_witnesses(tmp_path, monkeypatch):
    from cdmw.services.new_item_mod_base import build_mod_base_snapshot
    game_pamt, game_original, _ = index_fixture(tmp_path / 'stock')
    mod_pamt, mod_original, changed = index_fixture(tmp_path / 'mod')
    service = NewItemService()
    snapshot = service.build_snapshot(parse_archive_pamt(game_pamt), read_entry=_read)
    hide_index_stat_change(monkeypatch, mod_pamt)
    base = build_mod_base_snapshot(service, snapshot, mod_pamt.parent.parent, read_entry=_read)
    revision = base.provenance.capture()
    assert dict(revision.indexes) == {
        game_pamt: hashlib.sha256(game_original).hexdigest(),
        mod_pamt: hashlib.sha256(mod_original).hexdigest(),
    }
    revision.validate()
    replace_index(mod_pamt, changed, True)
    with pytest.raises(StaleNewItemSource, match='[Ii]ndex'):
        revision.validate()


def test_mounted_base_preserves_original_indexes_through_derived_snapshot(tmp_path):
    from cdmw.services.new_item_mounted_base import prepare_mounted_item_base
    from tests.test_new_item_mounted_base import mounted_game
    service, _, _, mounted, root = mounted_game(tmp_path)
    before = mounted.provenance.capture().indexes
    assert before
    base = prepare_mounted_item_base(service, mounted, read_entry=_read).snapshot
    after = dict(base.provenance.capture().indexes)
    assert all(after[path] == checksum for path, checksum in before)
    assert root / '0036/0.pamt' in after and root / '0009/0.pamt' in after
    base.provenance.capture().validate()


def test_listing_preserves_cancellation_from_inside_index_verification(tmp_path, monkeypatch):
    import cdmw.core.archive_format as archive_format
    from cdmw.domain.cancellation import RunCancelled
    index_fixture(tmp_path)
    stop = threading.Event()
    parse = archive_format._parse_archive_pamt_bytes

    def cancel(data, path, **kwargs):
        result = parse(data, path, **kwargs)
        stop.set()
        return result

    monkeypatch.setattr(archive_format, '_parse_archive_pamt_bytes', cancel)
    with pytest.raises(RunCancelled):
        list_archive_entries(tmp_path / 'game', lambda _: None, stop)


def test_witnessed_catalogue_cannot_omit_an_index(tmp_path):
    from cdmw.services.new_item_provenance import ArchiveCatalogue
    pamt, _, _ = index_fixture(tmp_path)
    catalogue = ArchiveCatalogue(tuple(parse_archive_pamt(pamt)), ())
    with pytest.raises(StaleNewItemSource, match='omits an original index witness'):
        NewItemService().build_snapshot(catalogue, read_entry=_read)


def test_resident_index_witness_scans_each_row_once_across_multiple_indexes(tmp_path, monkeypatch):
    import shutil
    from cdmw.services.new_item_provenance import SourceTracker
    pamt, _, _ = index_fixture(tmp_path)
    root = tmp_path / 'game'
    second = root / '0010'
    shutil.copytree(pamt.parent, second)
    indexes = (pamt, second / pamt.name)
    entries = [entry for path in indexes for entry in parse_archive_pamt(path)]
    catalogue = write_resident_index(root, entries, tmp_path / 'generation').open()
    scan_rows = catalogue._scan_rows
    yielded = []

    def count_rows(stop_event=None):
        for row in scan_rows(stop_event):
            yielded.append(row)
            yield row

    monkeypatch.setattr(catalogue, '_scan_rows', count_rows)
    tracker = SourceTracker(_read)
    catalogue.verify_parsed_indexes(tracker.parse_index)
    assert yielded == list(range(len(entries)))
    assert dict(tracker.capture().indexes) == {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in indexes
    }
