"""Synthetic end-to-end field edits, mixed-package protection and recomposition."""
import threading
from uuid import uuid4

import pytest

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.iteminfo_row import parse_iteminfo_row
from cdmw.domain.archives.iteminfo_composition import rows_of
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.iteminfo_operations import ItemFieldConflict
from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services import archive_overlay_manager as overlays
from cdmw.services.independent_item_install import (MOD_PROFILE_FORMAT, load_registry, prepare_install, prepare_rebuild,
    prepare_remove, export_profile, prepare_profile_import, inventory)
from cdmw.services.independent_item_package import from_plan, package_bytes
from cdmw.services.independent_item_operations import from_iteminfo_operations
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import publish_profile, generation_path, load_profile
from tests.test_archive_overlay_manager import Backups, shop_spec, snapshot_of
from tests.test_independent_items import setup_game
from tests.test_independent_item_regressions import files_in
from tests.test_iteminfo_operations import assignment
from tests.test_iteminfo_row import DDD
from tests.test_virtual_loader import game_bytes


def field_package(snapshot, *, stat=False, value=7, identity=None):
    raw = snapshot.rows[1001295].raw
    return from_iteminfo_operations(snapshot, identity or uuid4().hex, 'Existing stat' if stat else 'Existing stack',
                                    [assignment(raw, stat=stat, value=value)])


def virtual_row(root, key=1001295):
    profile = load_profile(root)
    generation = generation_path(root, profile['generation'])
    pamt = next(generation.glob('files/*/0.pamt'))
    entries = parse_archive_pamt(pamt)
    body = next(entry for entry in entries if entry.path.endswith(('iteminfo.staticinfobody', 'iteminfo.pabgb')))
    head = next(entry for entry in entries if entry.path.endswith(('iteminfo.staticinfoheader', 'iteminfo.pabgh')))
    return parse_iteminfo_row(rows_of(read_archive_entry_data(body)[0], read_archive_entry_data(head)[0])[key])


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('batch', [False, True])
def test_physical_disjoint_fields_compose_in_either_order_without_allocating_items(tmp_path, reverse, batch):
    _, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    stock = game_bytes(root)
    packages = [field_package(snapshot), field_package(snapshot, stat=True, value=13000)]
    order = packages[::-1] if reverse else packages
    for selected in ([order] if batch else [[p] for p in order]):
        backups.apply(prepare_install([package_bytes(p) for p in selected], root).preparation)
    row = snapshot_of(root).rows[1001295]
    assert row.max_stack_count == 7 and row.stat(0, DDD).value == 13000
    registry = load_registry(root)
    assert registry['format'] == MOD_PROFILE_FORMAT
    assert all(not row['values'] and not row['paths'] and not row['stem'] for row in registry['items'].values())
    assert all(row[2] is None and row[3] == 'Installed' for row in inventory(root))
    assert prepare_install([package_bytes(p) for p in packages], root).preparation is None
    backups.apply(prepare_rebuild(packages[0].identity, root).preparation)
    assert snapshot_of(root).rows[1001295].stat(0, DDD).value == 13000
    backups.apply(prepare_remove(packages[0].identity, root))
    row = snapshot_of(root).rows[1001295]
    assert row.max_stack_count == snapshot.rows[1001295].max_stack_count
    assert row.stat(0, DDD).value == 13000
    backups.apply(prepare_remove(packages[1].identity, root))
    assert snapshot_of(root).rows[1001295].raw == snapshot.rows[1001295].raw
    assert {p: data for p, data in game_bytes(root).items() if p.startswith('0009/')} == {p: data for p, data in stock.items() if p.startswith('0009/')}
    assert load_registry(root)['items'][packages[0].identity]['binding_hash'] == registry['items'][packages[0].identity]['binding_hash']


@pytest.mark.parametrize('reverse', [False, True])
def test_virtual_disjoint_fields_compose_and_remove_without_game_writes(tmp_path, reverse):
    _, snapshot, _ = setup_game(tmp_path)
    root, stock = tmp_path / 'game', game_bytes(tmp_path / 'game')
    packages = [field_package(snapshot), field_package(snapshot, stat=True, value=13000)]
    paths = []
    for index, package in enumerate(packages):
        path = tmp_path / f'{index}.cditem'
        path.write_bytes(package_bytes(package))
        paths.append(path)
    publish_profile(prepare_profile(VirtualProfile(tuple(paths[::-1] if reverse else paths)), root))
    row = virtual_row(root)
    assert row.max_stack_count == 7 and row.stat(0, DDD).value == 13000
    assert all(not row['values'] for row in load_registry(root)['items'].values())
    publish_profile(prepare_profile(VirtualProfile((paths[1],)), root))
    row = virtual_row(root)
    assert row.max_stack_count == snapshot.rows[1001295].max_stack_count and row.stat(0, DDD).value == 13000
    publish_profile(prepare_profile(VirtualProfile(), root))
    assert not load_profile(root)['items'] and game_bytes(root) == stock


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('route', ['batch', 'later', 'virtual'])
def test_legacy_required_records_are_protected_independently_of_compile_order(tmp_path, reverse, route):
    service, snapshot, _ = setup_game(tmp_path)
    root = tmp_path / 'game'
    legacy = from_plan(service.plan(shop_spec('LegacyItem'), snapshot, capture_independent=True), uuid4().hex)
    edited = field_package(snapshot)
    packages = [legacy, edited][::-1] if reverse else [legacy, edited]
    if route == 'later':
        Backups(tmp_path).apply(prepare_install([package_bytes(packages[0])], root).preparation)
    before = files_in(root)
    with pytest.raises(ItemFieldConflict, match='complete record unchanged') as error:
        if route == 'virtual':
            paths = []
            for index, package in enumerate(packages):
                path = tmp_path / f'{index}.cditem'
                path.write_bytes(package_bytes(package))
                paths.append(path)
            prepare_profile(VirtualProfile(tuple(paths)), root)
        else:
            prepare_install([package_bytes(p) for p in packages[1:]] if route == 'later'
                            else [package_bytes(p) for p in packages], root)
    assert legacy.identity in str(error.value) and edited.identity in str(error.value)
    assert files_in(root) == before


@pytest.mark.parametrize('same', [False, True])
def test_same_field_values_coexist_or_conflict_without_last_writer_wins(tmp_path, same):
    _, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    first, second = field_package(snapshot), field_package(snapshot, value=7 if same else 9)
    backups.apply(prepare_install([package_bytes(first)], root).preparation)
    before = files_in(root)
    if same:
        backups.apply(prepare_install([package_bytes(second)], root).preparation)
        backups.apply(prepare_remove(first.identity, root))
        assert snapshot_of(root).rows[1001295].max_stack_count == 7
    else:
        with pytest.raises(ItemFieldConflict, match='opposing assignments'):
            prepare_install([package_bytes(second)], root)
        assert files_in(root) == before


@pytest.mark.parametrize('retired_legacy', [False, True])
def test_field_publication_failure_restores_output_and_profile_upgrade(tmp_path, monkeypatch, retired_legacy):
    service, snapshot, _ = setup_game(tmp_path)
    root = tmp_path / 'game'
    package = field_package(snapshot)
    if retired_legacy:
        legacy = from_plan(service.plan(shop_spec('RetiredLegacy'), snapshot, capture_independent=True), uuid4().hex)
        backups = Backups(tmp_path)
        backups.apply(prepare_install([package_bytes(legacy)], root).preparation)
        backups.apply(prepare_remove(legacy.identity, root))
    original = files_in(root)
    plan = prepare_install([package_bytes(package)], root)
    write = overlays.atomic_write_bytes
    def fail(path, data):
        write(path, data)
        if path.name == 'independent-items.json':
            raise OSError('injected field publication failure')
    monkeypatch.setattr(overlays, 'atomic_write_bytes', fail)
    with pytest.raises(OSError, match='injected field'):
        Backups(tmp_path).apply(plan.preparation)
    assert files_in(root) == original


def test_profile_upgrade_preserves_retired_v1_bindings_and_cannot_masquerade_as_v1(tmp_path):
    from copy import deepcopy
    from cdmw.services.independent_item_install import PROFILE_FORMAT, _validate_registry
    service, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    field = field_package(snapshot)
    legacy = from_plan(service.plan(shop_spec('RetiredLegacy'), snapshot, capture_independent=True), uuid4().hex)
    backups.apply(prepare_install([package_bytes(legacy)], root).preparation)
    backups.apply(prepare_remove(legacy.identity, root))
    original = load_registry(root)
    assert original['format'] == PROFILE_FORMAT
    backups.apply(prepare_install([package_bytes(field)], root).preparation)
    current = load_registry(root)
    assert current['format'] == MOD_PROFILE_FORMAT and current['items'][legacy.identity] == original['items'][legacy.identity]
    mislabeled = deepcopy(current)
    mislabeled['format'] = PROFILE_FORMAT
    with pytest.raises(IndependentItemError, match='identity reservation is missing'):
        _validate_registry(mislabeled)


def test_field_identity_profile_transfers_without_dummy_item_ids(tmp_path):
    _, snapshot, _ = setup_game(tmp_path / 'first')
    root, backups = tmp_path / 'first/game', Backups(tmp_path)
    package = field_package(snapshot)
    backups.apply(prepare_install([package_bytes(package)], root).preparation)
    profile = export_profile(root, tmp_path / 'saved.cdprofile')
    setup_game(tmp_path / 'second')
    second = tmp_path / 'second/game'
    backups.apply(prepare_profile_import(profile, second))
    assert load_registry(second)['format'] == MOD_PROFILE_FORMAT
    backups.apply(prepare_install([package_bytes(package)], second).preparation)
    assert snapshot_of(second).rows[1001295].max_stack_count == 7
    assert load_registry(second)['items'][package.identity]['values'] == {}


def test_existing_overlay_install_preserves_field_only_reservations_and_complete_pairs(tmp_path):
    service, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    package = field_package(snapshot)
    backups.apply(prepare_install([package_bytes(package)], root).preparation)
    plan = service.plan(shop_spec('GenericClone'), snapshot_of(root))
    backups.apply(overlays.prepare_item_overlay(plan, root))
    assert snapshot_of(root).rows[1001295].max_stack_count == 7
    assert plan.spec.item_key in snapshot_of(root).rows


def test_virtual_field_package_uses_real_worker_process_and_no_op_owner_can_be_removed(tmp_path):
    from cdmw.services.virtual_loader_process import prepare_profile_in_subprocess
    _, snapshot, _ = setup_game(tmp_path)
    root, path = tmp_path / 'game', tmp_path / 'item.cditem'
    package = field_package(snapshot, value=snapshot.rows[1001295].max_stack_count)
    path.write_bytes(package_bytes(package))
    prepared = prepare_profile_in_subprocess(VirtualProfile((path,)), root)
    publish_profile(prepared)
    assert virtual_row(root).raw == snapshot.rows[1001295].raw
    publish_profile(prepare_profile(VirtualProfile(), root))
    backups = Backups(tmp_path)
    backups.apply(prepare_install([path], root).preparation)
    backups.apply(prepare_remove(package.identity, root))


def test_cancel_during_field_composition_leaves_previous_installation_unchanged(tmp_path, monkeypatch):
    import cdmw.domain.new_item.iteminfo_operations as operations
    _, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    first, second = field_package(snapshot), field_package(snapshot, stat=True, value=13000)
    backups.apply(prepare_install([package_bytes(first)], root).preparation)
    before = files_in(root)
    stop = threading.Event()
    write = operations.set_stat_value
    def cancel_after_write(*args):
        result = write(*args)
        stop.set()
        return result
    monkeypatch.setattr(operations, 'set_stat_value', cancel_after_write)
    with pytest.raises(RunCancelled):
        prepare_install([package_bytes(second)], root, stop_event=stop)
    assert files_in(root) == before


def test_untyped_external_edit_cannot_bypass_field_source_contract(tmp_path):
    from cdmw.core.iteminfo_row import set_stat_value
    from cdmw.domain.archives.iteminfo_composition import replace_rows
    _, snapshot, _ = setup_game(tmp_path)
    root, path = tmp_path / 'game', tmp_path / 'item.cditem'
    path.write_bytes(package_bytes(field_package(snapshot)))
    pair = snapshot.iteminfo
    edited = replace_rows(pair.payload, pair.header, {1001295: set_stat_value(snapshot.rows[1001295], 0, DDD, 12345)})
    mod = tmp_path / 'external'
    for entry, data in ((pair.payload_entry, edited), (pair.header_entry, pair.header)):
        output = mod / 'files' / entry.path
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
    before = files_in(root)
    with pytest.raises(IndependentItemError, match='source row changed'):
        prepare_profile(VirtualProfile((path,), (mod,)), root)
    assert files_in(root) == before


def test_active_composition_operation_budget_refuses_before_publication(tmp_path, monkeypatch):
    import cdmw.domain.new_item.iteminfo_operations as operations
    _, snapshot, _ = setup_game(tmp_path)
    root = tmp_path / 'game'
    selected = [package_bytes(field_package(snapshot)) for _ in range(3)]
    monkeypatch.setattr(operations, 'MAX_OPERATIONS', 2)
    before = files_in(root)
    with pytest.raises(IndependentItemError, match='operation budget'):
        prepare_install(selected, root)
    assert files_in(root) == before


@pytest.mark.parametrize('virtual', [False, True])
def test_one_v2_package_executes_legacy_and_unrelated_field_modules(tmp_path, virtual):
    from copy import deepcopy
    from cdmw.services.independent_mod_package import migrate_v1, read_v2
    from cdmw.services.new_item_service import NewItemService
    from tests.test_new_item_service import build_package, _read, _table4
    from tests.test_iteminfo_row import build_row
    _, source, source_entries = setup_game(tmp_path / 'source')
    files = {entry.path: source.payload(entry.path) for entry in source_entries}
    body = 'gamedata/binarystaticinfo__/bin/iteminfo.staticinfobody'
    header = body.replace('.staticinfobody', '.staticinfoheader')
    raw = build_row(key=992000, string_key='UnrelatedStock')
    files[body], files[header] = _table4([*rows_of(files[body], files[header]).items(), (992000, raw)])
    root = tmp_path / 'game'
    entries = parse_archive_pamt(build_package(root, files))
    (root / 'meta/0.pathc').write_bytes((tmp_path / 'source/game/meta/0.pathc').read_bytes())
    service = NewItemService()
    snapshot = service.build_snapshot(entries, read_entry=_read)
    original = from_plan(service.plan(shop_spec('MixedModules'), snapshot, capture_independent=True), uuid4().hex)
    envelope = deepcopy(migrate_v1(original).manifest)
    envelope['requires']['item.fields'] = 1
    envelope['modules'].append({'id': 'edits', 'type': 'item.fields', 'version': 1, 'required': True,
                                'data': {'operations': [assignment(raw, value=13)]}})
    package = read_v2(envelope, original.blobs)
    if virtual:
        path = tmp_path / 'mixed.cditem'
        path.write_bytes(package_bytes(package))
        publish_profile(prepare_profile(VirtualProfile((path,)), root))
        assert virtual_row(root, 992000).max_stack_count == 13
        key = load_registry(root)['items'][original.identity]['values']['iteminfo']['item']
        assert virtual_row(root, key).key == key
    else:
        Backups(tmp_path).apply(prepare_install([package_bytes(package)], root).preparation)
        assert snapshot_of(root).rows[992000].max_stack_count == 13
        key = load_registry(root)['items'][original.identity]['values']['iteminfo']['item']
        assert key in snapshot_of(root).rows
