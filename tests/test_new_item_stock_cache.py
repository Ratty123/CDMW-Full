"""Clean stock reuse must never share draft state or accept stale providers."""
from concurrent.futures import ThreadPoolExecutor
import shutil
import struct
import threading

import pytest

from cdmw.core import archive_format
from cdmw.domain.cancellation import RunCancelled
from cdmw.services import independent_item_package as owner
from cdmw.services.new_item_service import NewItemService
from tests.test_cditem_index_consumers import hide_index_stat_change
from tests.test_independent_item_index_witness import ALTERNATE, BODY, index_fixture, replace_index
from tests.test_new_item_service import TEMPLATE, _read


@pytest.fixture(autouse=True)
def separate_stock_cache(monkeypatch):
    monkeypatch.setattr(owner, '_stock_snapshot_cache', None)


def mounts(root, names):
    data, strings = bytearray(12), bytearray()
    for name in names:
        checksum, = struct.unpack_from('<I', (root / name / '0.pamt').read_bytes())
        data += struct.pack('<III', 0x007FFF00, len(strings), checksum)
        strings += name.encode('ascii') + b'\0'
    data += struct.pack('<I', len(strings)) + strings
    struct.pack_into('<I', data, 4, archive_format.calculate_pa_checksum(bytes(data[12:])))
    return bytes(data)


def test_stock_reuses_parsed_tables_with_private_mutable_state_and_entries(tmp_path, monkeypatch):
    index_fixture(tmp_path)
    root = tmp_path / 'game'
    parse, parsed = archive_format.parse_archive_pamt_bytes, []
    def count(data, path, **kwargs):
        parsed.append(path)
        return parse(data, path, **kwargs)
    monkeypatch.setattr(archive_format, 'parse_archive_pamt_bytes', count)
    first = owner.stock_snapshot(root, overlay_changes=())
    initial = list(parsed)
    second = owner.stock_snapshot(root, overlay_changes=())
    assert initial and parsed == initial
    assert first.rows is second.rows and first.iteminfo.payload is second.iteminfo.payload
    assert first.provenance is not second.provenance
    assert first.provenance.capture() == second.provenance.capture()
    with pytest.raises(TypeError):
        first.rows[TEMPLATE] = second.rows[TEMPLATE]
    for name in ('base_payloads', 'base_manifest'):
        with pytest.raises(TypeError):
            getattr(first, name)['draft'] = 'local'
    first._contexts['draft'] = 'local'
    first._families['draft'] = 'local'
    first._payloads['draft'] = b'local'
    first._authoring_indexes['draft'] = 'local'
    before = second.entry(BODY).offset
    first.entry(BODY).offset += 7
    first.iteminfo.payload_entry.offset += 9
    first.provenance.capture().payloads[0].entry.offset += 11
    assert second.entry(BODY).offset == before
    assert all('draft' not in getattr(second, name) for name in ('_contexts', '_families', '_payloads', '_authoring_indexes'))
    third = owner.stock_snapshot(root, overlay_changes=())
    assert third.entry(BODY).offset == before and third.iteminfo.payload_entry.offset == before
    third.provenance.capture().validate()


def test_changed_exact_index_rebuilds_stock_even_when_all_stamps_match(tmp_path, monkeypatch):
    pamt, _, changed = index_fixture(tmp_path)
    root = tmp_path / 'game'
    hide_index_stat_change(monkeypatch, pamt)
    first = owner.stock_snapshot(root, overlay_changes=())
    replace_index(pamt, changed, True)
    second = owner.stock_snapshot(root, overlay_changes=())
    assert first.rows[TEMPLATE].max_stack_count == 1
    assert second.rows[TEMPLATE].max_stack_count == 9
    assert first.provenance.capture().indexes != second.provenance.capture().indexes


def test_changed_payload_rebuilds_stock_even_when_catalogue_and_stamps_match(tmp_path):
    index_fixture(tmp_path)
    root = tmp_path / 'game'
    replaced = False
    entries = {entry.path: entry for entry in archive_format.parse_archive_pamt(root / '0009/0.pamt')}
    alternative = _read(entries[ALTERNATE])
    def reader(entry):
        return alternative if replaced and entry.path == BODY else _read(entry)
    first = owner.stock_snapshot(root, read_entry=reader, overlay_changes=())
    replaced = True
    second = owner.stock_snapshot(root, read_entry=reader, overlay_changes=())
    assert first.rows[TEMPLATE].max_stack_count == 1
    assert second.rows[TEMPLATE].max_stack_count == 9


def test_mount_order_changes_invalidate_stock_provider_selection(tmp_path, monkeypatch):
    pamt, _, changed = index_fixture(tmp_path)
    root = tmp_path / 'game'
    shutil.copytree(pamt.parent, root / '0010')
    (root / '0010/0.pamt').write_bytes(changed)
    mount = root / 'meta/0.papgt'
    mount.write_bytes(mounts(root, ('0009', '0010')))
    hide_index_stat_change(monkeypatch, mount)
    first = owner.stock_snapshot(root, overlay_changes=())
    replace_index(mount, mounts(root, ('0010', '0009')), True)
    second = owner.stock_snapshot(root, overlay_changes=())
    assert first.rows[TEMPLATE].max_stack_count == 1
    assert second.rows[TEMPLATE].max_stack_count == 9


def test_stock_cache_never_uses_the_mounted_custom_catalogue(tmp_path):
    pamt, _, changed = index_fixture(tmp_path)
    root = tmp_path / 'game'
    service = NewItemService()
    stock = owner.stock_snapshot(root, service=service, overlay_changes=())
    shutil.copytree(pamt.parent, root / '0036')
    (root / '0036/0.pamt').write_bytes(changed)
    (root / 'meta/0.papgt').write_bytes(mounts(root, ('0036', '0009')))
    entries = [*archive_format.parse_archive_pamt(pamt), *archive_format.parse_archive_pamt(root / '0036/0.pamt')]
    mounted = service.build_snapshot(entries)
    assert mounted.rows[TEMPLATE].max_stack_count == 9
    clean = owner.stock_snapshot(root, service=service, overlay_changes=())
    assert stock.rows[TEMPLATE].max_stack_count == clean.rows[TEMPLATE].max_stack_count == 1
    assert all(path.parent.name != '0036' for path, _ in clean.provenance.capture().indexes)


def test_cancelled_stock_build_does_not_publish_partial_cache(tmp_path, monkeypatch):
    index_fixture(tmp_path)
    stop = threading.Event()
    parse = archive_format.parse_archive_pamt_bytes
    def cancel(data, path, **kwargs):
        result = parse(data, path, **kwargs)
        stop.set()
        return result
    monkeypatch.setattr(archive_format, 'parse_archive_pamt_bytes', cancel)
    with pytest.raises(RunCancelled):
        owner.stock_snapshot(tmp_path / 'game', stop_event=stop, overlay_changes=())
    assert owner._stock_snapshot_cache is None


def test_concurrent_stock_requests_keep_cancellation_and_draft_state_separate(tmp_path):
    index_fixture(tmp_path)
    root = tmp_path / 'game'
    owner.stock_snapshot(root, overlay_changes=())
    stopped = threading.Event()
    stopped.set()
    with ThreadPoolExecutor(max_workers=3) as pool:
        cancelled = pool.submit(owner.stock_snapshot, root, stop_event=stopped, overlay_changes=())
        left = pool.submit(owner.stock_snapshot, root, overlay_changes=())
        right = pool.submit(owner.stock_snapshot, root, overlay_changes=())
        with pytest.raises(RunCancelled):
            cancelled.result()
        first, second = left.result(), right.result()
    first._payloads['draft'] = b'local'
    assert 'draft' not in second._payloads
    assert first.provenance is not second.provenance
    assert first.rows is second.rows
    assert first.entry(BODY) is not second.entry(BODY)
    first.provenance.capture().validate()
    second.provenance.capture().validate()


def test_overlay_pathc_rebase_is_applied_fresh_after_cached_stock(tmp_path):
    from cdmw.core.pathc_format import PathcTable, encode_pathc
    index_fixture(tmp_path)
    root = tmp_path / 'game'
    raw = encode_pathc(PathcTable(0, 148, (), (), (), b''))
    (root / 'meta/0.pathc').write_bytes(raw)
    first = owner.stock_snapshot(root, overlay_changes=({'meta/0.pathc': {'before': None}},))
    second = owner.stock_snapshot(root, overlay_changes=())
    assert first.pathc is None and second.pathc is not None
    assert encode_pathc(second.pathc) == raw


def test_distinct_custom_service_instances_are_separate_cache_authorities(tmp_path):
    index_fixture(tmp_path)
    built = []
    class CustomService(NewItemService):
        def __eq__(self, other):
            return isinstance(other, CustomService)
        def build_snapshot(self, entries, **kwargs):
            built.append(self)
            return super().build_snapshot(entries, **kwargs)
    left, right = CustomService(), CustomService()
    assert left == right  # Value equality does not establish service authority.
    root = tmp_path / 'game'
    owner.stock_snapshot(root, service=left, overlay_changes=())
    owner.stock_snapshot(root, service=right, overlay_changes=())
    assert built == [left, right] and built[0] is left and built[1] is right


def test_equal_callable_readers_do_not_share_stock_source_authority(tmp_path):
    index_fixture(tmp_path)
    root = tmp_path / 'game'
    entries = {entry.path: entry for entry in archive_format.parse_archive_pamt(root / '0009/0.pamt')}
    alternative = _read(entries[ALTERNATE])
    class Reader:
        def __init__(self, changed):
            self.changed = changed
        def __eq__(self, other):
            return isinstance(other, Reader)
        def __call__(self, entry):
            return alternative if self.changed and entry.path == BODY else _read(entry)
    left, right = Reader(False), Reader(True)
    assert left == right
    first = owner.stock_snapshot(root, read_entry=left, overlay_changes=())
    second = owner.stock_snapshot(root, read_entry=right, overlay_changes=())
    assert first.rows[TEMPLATE].max_stack_count == 1
    assert second.rows[TEMPLATE].max_stack_count == 9
