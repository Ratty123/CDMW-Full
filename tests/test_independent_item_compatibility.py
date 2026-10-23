from dataclasses import replace
import struct
import threading

import pytest

from cdmw.core.papgt_format import papgt_with_directory, parse_papgt, serialize_papgt
from cdmw.domain.archives.overlay_merge import OverlayConflict, _table
from cdmw.domain.cancellation import RunCancelled
from cdmw.services.independent_item_compatibility import scan_independent_conflicts, prepare_independent_mod_merge
from cdmw.services.independent_item_install import prepare_install, prepare_remove, load_registry
from cdmw.services.independent_item_package import package_bytes
from cdmw.services.archive_overlay_rebuild import prepare_overlay_rebuild
from tests.test_archive_overlay_manager import Backups, snapshot_of
from tests.test_independent_items import authored, setup_game
from tests.test_new_item_service import build_package, _table4, OTHER, TEMPLATE, _named_row


def table_change(snapshot, name='iteminfo', key=OTHER):
    body = next(p for p in snapshot.entries if p.endswith(f'/{name}.staticinfobody'))
    head = body.replace('.staticinfobody', '.staticinfoheader')
    rows = []
    for raw_key, raw in _table(snapshot.payload(body), snapshot.payload(head))[1]:
        number = int.from_bytes(raw_key, 'little')
        if number == key:
            if name == 'iteminfo':
                from cdmw.core.iteminfo_row import parse_iteminfo_row
                row = parse_iteminfo_row(raw)
                value = bytearray(raw)
                struct.pack_into('<I', value, row.max_stack_count_offset, row.max_stack_count + 1)
                raw = bytes(value)
            else:
                raw = _named_row(key, 'ChangedEquipment')
        rows.append((number, raw))
    payload, header = _table4(rows)
    return {body: payload, head: header}


def mount_mod(root, tmp_path, files, name='foreign', first=False):
    pamt = build_package(tmp_path, files)
    group = root / name
    group.mkdir(exist_ok=True)
    for path in pamt.parent.iterdir():
        if path.is_file():
            (group / path.name).write_bytes(path.read_bytes())
    mount = root / 'meta/0.papgt'
    mount.write_bytes(papgt_with_directory(mount.read_bytes(), name,
        int.from_bytes((group / '0.pamt').read_bytes()[:4], 'little'), first=first))
    return {p: p.read_bytes() for p in group.iterdir() if p.is_file()}


@pytest.mark.parametrize('transport', ['mounted', 'folder'])
@pytest.mark.parametrize('path', [
    '../escape', 'sequencer/../escape', '/sequencer/file', 'sequencer//file',
    'sequencer/file.', 'sequencer/file ', 'sequencer\\file', 'sequencer/x:y',
    'sequencer/\0bad', 'sequencer/' + 'a' * 503,
])
def test_external_resources_retain_canonical_path_guards(tmp_path, monkeypatch, transport, path):
    from cdmw.services.independent_item_compatibility import external_mods
    from cdmw.services.new_item_mod_base import ModFolderPayload
    from cdmw.services.new_item_provenance import SourceTracker

    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    folders = ()
    if transport == 'mounted':
        mount_mod(root, tmp_path / 'foreign-source', {'sequencer/test.paseq': b'foreign'})
        original = SourceTracker.parse_index
        def malformed_index(self, pamt, **kwargs):
            return [replace(entry, path=path) for entry in original(self, pamt, **kwargs)]
        monkeypatch.setattr(SourceTracker, 'parse_index', malformed_index)
    else:
        folder = tmp_path / 'foreign-folder'
        folder.mkdir()
        source = folder / 'sequence.paseq'
        source.write_bytes(b'foreign')
        monkeypatch.setattr('cdmw.services.new_item_mod_base.mod_folder_payloads',
                            lambda *args, **kwargs: {path: ModFolderPayload(path=source)})
        folders = (folder,)
    with pytest.raises(ValueError, match='Invalid package resource path'):
        external_mods(root, {'directory': 'cdmw'}, folders=folders)


@pytest.mark.parametrize('first', [True, False])
def test_disjoint_external_records_survive_two_items_update_and_removal(tmp_path, first):
    _, one = authored(tmp_path / 'a')
    _, two = authored(tmp_path / 'b')
    _, stock, _ = setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    files = table_change(stock)
    foreign = mount_mod(root, tmp_path / 'foreign', files, first=first)
    shipped = {p: p.read_bytes() for p in (root / '0009').iterdir() if p.is_file()}
    for package in (one, two):
        backups.apply(prepare_install([package_bytes(package)], root).preparation)
    bindings = load_registry(root)['items']
    assert len({row['values']['iteminfo']['item'] for row in bindings.values()}) == 2
    assert snapshot_of(root).rows[OTHER].max_stack_count == stock.rows[OTHER].max_stack_count + 1
    _, updated = authored(tmp_path / 'updated', one.identity, 'Updated')
    backups.apply(prepare_install([package_bytes(updated)], root).preparation)
    for index, package in enumerate((two, one)):
        backups.apply(prepare_remove(package.identity, root))
        expected = stock.rows[OTHER].max_stack_count + int(first or index == 0)
        assert snapshot_of(root).rows[OTHER].max_stack_count == expected
    assert all(p.read_bytes() == value for p, value in {**shipped, **foreign}.items())


@pytest.mark.parametrize('name', ['iteminfo', 'equiptypeinfo'])
def test_required_record_conflict_identifies_mod_file_and_record(tmp_path, name):
    _, package = authored(tmp_path / 'author')
    _, stock, _ = setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    key = stock.rows[TEMPLATE].socket_items[0] if name == 'iteminfo' else stock.rows[TEMPLATE].equip_type_key
    mount_mod(root, tmp_path / 'foreign', table_change(stock, name, key))
    before = (root / 'meta/0.papgt').read_bytes()
    with pytest.raises(OverlayConflict, match=rf'foreign.*{name}.*record {key}'):
        prepare_install([package_bytes(package)], root)
    assert not (root / '.cdmw/independent-items.json').exists()
    assert (root / 'meta/0.papgt').read_bytes() == before


def test_external_item_ids_are_reserved_and_owned_duplicates_are_refused(tmp_path):
    from cdmw.core.iteminfo_row import clone_iteminfo_row
    _, package = authored(tmp_path / 'author')
    _, stock, _ = setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    body = stock.iteminfo.payload_entry.path
    head = stock.iteminfo.header_entry.path
    original = [(int.from_bytes(key, 'little'), raw) for key, raw in _table(stock.payload(body), stock.payload(head))[1]]
    foreign_row = clone_iteminfo_row(stock.rows[OTHER], key=1990000, string_key='ForeignItem', name_key='998877', desc_key='998878')
    data, header = _table4([*original, (1990000, foreign_row)])
    mount_mod(root, tmp_path / 'foreign', {body: data, head: header})
    another_row = clone_iteminfo_row(stock.rows[OTHER], key=1990050, string_key='AnotherForeignItem', name_key='998879', desc_key='998880')
    data, header = _table4([*original, (1990050, another_row)])
    mount_mod(root, tmp_path / 'second', {body: data, head: header}, name='second')
    backups.apply(prepare_install([package_bytes(package)], root).preparation)
    key = load_registry(root)['items'][package.identity]['values']['iteminfo']['item']
    assert key != 1990000
    snapshot = snapshot_of(root)
    assert snapshot.rows[1990000].string_key == 'ForeignItem'
    assert snapshot.rows[1990050].string_key == 'AnotherForeignItem'
    # Even identical record bytes cannot become a second mod's owned identity.
    data, header = _table4([*original, (1990000, foreign_row), (key, snapshot.rows[key].raw)])
    mount_mod(root, tmp_path / 'changed', {body: data, head: header})
    report = scan_independent_conflicts(root)
    assert not report.compatible and f'owned record {key}' in report.text()


def test_unrelated_equipment_record_can_change_but_incomplete_pair_cannot(tmp_path):
    _, package = authored(tmp_path / 'author')
    _, stock, _ = setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    body = next(p for p in stock.entries if p.endswith('/equiptypeinfo.staticinfobody'))
    head = body.replace('body', 'header')
    rows = [(int.from_bytes(key, 'little'), raw) for key, raw in _table(stock.payload(body), stock.payload(head))[1]]
    data, header = _table4([*rows, (123456, _named_row(123456, 'ForeignEquipment'))])
    mount_mod(root, tmp_path / 'foreign', {body: data, head: header})
    assert prepare_install([package_bytes(package)], root).preparation is not None
    mount_mod(root, tmp_path / 'partial', {body: data})
    with pytest.raises(OverlayConflict, match='Both table files'):
        prepare_install([package_bytes(package)], root)


def test_additive_tables_with_identical_bodies_keep_the_composed_pair(tmp_path):
    from cdmw.services.independent_item_compatibility import ExternalMods, foreign_underlay
    from cdmw.services.new_item_mod_base import ModFolderPayload
    from cdmw.services.new_item_provenance import SourceTracker
    body, head = 'gamedata/test.staticinfobody', 'gamedata/test.staticinfoheader'
    original = dict(zip((body, head), _table4([(1, b'base')])))
    class Snapshot:
        def has_entry(self, path):
            return path in original
        def payload(self, path):
            return original[path]
    external = ExternalMods(tmp_path, 'cdmw', SourceTracker(lambda entry: b''), snapshot=Snapshot())
    for key in (2, 3):
        # Table identities live in the directory; two new records may have
        # identical payload bytes while still needing distinct entries.
        for path, data in zip((body, head), _table4([(1, b'base'), (key, b'added')])):
            source = tmp_path / f'{key}-{path.rsplit("/", 1)[-1]}'
            source.write_bytes(data)
            external.providers.setdefault(path, []).append((str(key), ModFolderPayload(path=source)))
    merged = foreign_underlay(external, original, external.snapshot)
    rows = {int.from_bytes(key, 'little'): raw for key, raw in _table(merged[body], merged[head])[1]}
    assert rows == {1: b'base', 2: b'added', 3: b'added'}


def test_scan_prospective_folder_exports_merged_copy_without_changing_sources(tmp_path):
    from cdmw.services.mod_merge_service import export_merged_mod
    from cdmw.services.new_item_mod_base import mod_folder_payloads
    _, package = authored(tmp_path / 'author')
    _, stock, _ = setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    backups.apply(prepare_install([package_bytes(package)], root).preparation)
    files = table_change(stock)
    folder = tmp_path / 'prospective'
    for path, data in {**files, 'character/texture/unrelated.dat': b'foreign asset'}.items():
        target = folder / 'files' / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    report = scan_independent_conflicts(root, folders=(folder,))
    assert report.compatible and any(row.status == 'Merge available' for row in report.findings)
    plan = prepare_independent_mod_merge(root, folders=(folder,))
    output = export_merged_mod(plan, tmp_path / 'combined')
    payloads = mod_folder_payloads(output.package_root)
    body = next(path for path in files if path.endswith('body'))
    head = body.replace('body', 'header')
    rows = dict(_table(payloads[body].read_bytes(), payloads[head].read_bytes())[1])
    key = load_registry(root)['items'][package.identity]['values']['iteminfo']['item']
    assert key.to_bytes(4, 'little') in rows
    assert rows[OTHER.to_bytes(4, 'little')] == dict(_table(files[body], files[head])[1])[OTHER.to_bytes(4, 'little')]
    assert payloads['character/texture/unrelated.dat'].read_bytes() == b'foreign asset'
    assert all(p.read_bytes() == data for p, data in before.items())


def test_scan_and_reviewed_rebuild_detect_later_mod_and_preserve_removal(tmp_path):
    _, package = authored(tmp_path / 'author')
    _, stock, _ = setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    backups.apply(prepare_install([package_bytes(package)], root).preparation)
    foreign = mount_mod(root, tmp_path / 'foreign', table_change(stock), first=True)
    report = scan_independent_conflicts(root)
    assert report.compatible
    backups.apply(prepare_overlay_rebuild(root))
    assert snapshot_of(root).rows[OTHER].max_stack_count == stock.rows[OTHER].max_stack_count + 1
    # Removing the external mount must not resurrect its contribution from a journal.
    mount = root / 'meta/0.papgt'
    data = mount.read_bytes()
    mount.write_bytes(serialize_papgt([r for r in parse_papgt(data) if r.name != 'foreign'], header=data[:12]))
    backups.apply(prepare_overlay_rebuild(root))
    assert snapshot_of(root).rows[OTHER].max_stack_count == stock.rows[OTHER].max_stack_count
    assert all(path.read_bytes() == value for path, value in foreign.items())


def test_conflicting_providers_unknown_formats_and_cancel_do_not_claim_compatibility(tmp_path):
    _, package = authored(tmp_path / 'author')
    _, stock, _ = setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    backups.apply(prepare_install([package_bytes(package)], root).preparation)
    mount_mod(root, tmp_path / 'foreign', table_change(stock))
    mount_mod(root, tmp_path / 'another', table_change(stock, key=TEMPLATE), name='another')
    report = scan_independent_conflicts(root)
    assert not report.compatible and 'different replacements' in report.text()
    folder = tmp_path / 'unknown'
    folder.mkdir()
    (folder / 'plugin.asi').write_bytes(b'not executed')
    assert any(row.status == 'Unknown' for row in scan_independent_conflicts(root, folders=(folder,)).findings)
    stop = threading.Event()
    stop.set()
    with pytest.raises(RunCancelled):
        scan_independent_conflicts(root, stop_event=stop)


@pytest.mark.parametrize('after_backup', [False, True])
def test_external_archive_added_after_review_refuses_without_writing(tmp_path, after_backup):
    _, package = authored(tmp_path / 'author')
    _, stock, _ = setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    mount_mod(root, tmp_path / 'foreign', table_change(stock))
    prepared = prepare_install([package_bytes(package)], root).preparation
    original_backup = backups.backup_files
    def changed():
        (root / 'foreign/1.pamt').write_bytes((root / 'foreign/0.pamt').read_bytes())
    if after_backup:
        def backup(*args, **kwargs):
            result = original_backup(*args, **kwargs)
            changed()
            return result
        backups.backup_files = backup
    else:
        changed()
    with pytest.raises(OverlayConflict, match='folder.*changed'):
        backups.apply(prepared)
    assert not (root / '.cdmw/independent-items.json').exists()
