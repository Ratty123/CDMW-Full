"""Semantic exports retain original requirements through actual disk reimport."""
from copy import deepcopy
from uuid import uuid4

import pytest

from cdmw.core.mod_compatibility import SEMANTIC_EXPORT_FILE, read_semantic_export
from cdmw.core.mod_export_history import mod_metadata_path
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.iteminfo_operations import ItemFieldConflict
from cdmw.domain.new_item.package_links import validate_link_record
from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services import archive_overlay_manager as overlays
from cdmw.services.archive_overlay_manager import prepare_overlay_enabled
from cdmw.services.independent_item_compatibility import (
    prepare_independent_mod_merge, scan_independent_conflicts,
)
from cdmw.services.independent_item_install import load_registry, prepare_install, prepare_remove
from cdmw.services.independent_item_operations import from_iteminfo_operations
from cdmw.services.independent_item_package import from_plan, package_bytes, read_package
from cdmw.services.independent_mod_package import migrate_v1, read_v2
from cdmw.services.mod_merge_service import export_merged_mod
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import load_profile, publish_profile
from tests.test_archive_overlay_manager import Backups, shop_spec, snapshot_of
from tests.test_independent_item_fields import field_package, virtual_row
from tests.test_independent_item_regressions import files_in
from tests.test_independent_items import setup_game
from tests.test_independent_package_links import pair
from tests.test_iteminfo_operations import assignment
from tests.test_iteminfo_row import DDD
from tests.test_virtual_loader import game_bytes


def export_active(root, destination):
    before = files_in(root)
    report = scan_independent_conflicts(root)
    assert report.compatible, report.text()
    exported = export_merged_mod(prepare_independent_mod_merge(root), destination)
    bundle = read_semantic_export(exported.package_root)
    assert bundle is not None
    assert read_semantic_export(exported.package_root / SEMANTIC_EXPORT_FILE).packages == bundle.packages
    assert files_in(root) == before
    return exported.package_root, bundle


def package_path(folder, package):
    path = folder / f'{package.identity}-{package.digest}.cditem'
    path.write_bytes(package_bytes(package))
    return path


def deploy(root, sources, *, virtual, backups, folders=()):
    if virtual:
        publish_profile(prepare_profile(VirtualProfile(tuple(sources), tuple(folders)), root))
    else:
        prepared = prepare_install(sources, root, folders=folders)
        if prepared.preparation is not None:
            backups.apply(prepared.preparation)


@pytest.mark.parametrize('value', [1, 7])
def test_semantic_export_preserves_explicit_fields_including_source_equal_requirement(tmp_path, value):
    _, snapshot, _ = setup_game(tmp_path)
    root = tmp_path / 'game'
    package = field_package(snapshot, value=value)
    Backups(tmp_path).apply(prepare_install([package_bytes(package)], root).preparation)

    _folder, bundle = export_active(root, tmp_path / 'merged')
    retained = tuple(read_package(raw) for raw in bundle.packages)
    assert len(retained) == 1
    assert retained[0].identity == package.identity and retained[0].digest == package.digest
    assert retained[0].manifest == package.manifest
    assert retained[0].dependencies == package.dependencies
    assert set(bundle.bindings['items']) == {package.identity}
    assert {path: data for path, data, _ in bundle.files}


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('virtual', [False, True])
def test_source_equal_requirement_conflicts_after_real_export_reimport_in_both_orders_and_routes(tmp_path, reverse, virtual):
    folders, packages = [], []
    for index, value in enumerate((1, 9)):
        source = tmp_path / f'source-{index}'
        _, snapshot, _ = setup_game(source)
        package = field_package(snapshot, value=value)
        root = source / 'game'
        Backups(source).apply(prepare_install([package_bytes(package)], root).preparation)
        folder, _bundle = export_active(root, tmp_path / f'export-{index}')
        folders.append(folder)
        packages.append(package)
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    before = files_in(root)
    selected = tuple(folders[::-1] if reverse else folders)
    with pytest.raises(ItemFieldConflict, match='opposing assignments') as error:
        if virtual:
            prepare_profile(VirtualProfile((), selected), root)
        else:
            prepare_install(list(selected), root)
    assert all(package.identity in str(error.value) for package in packages)
    assert files_in(root) == before


@pytest.mark.parametrize('virtual', [False, True])
def test_dependency_pins_and_typed_exports_survive_real_reimport(tmp_path, virtual):
    provider, consumer = pair(tmp_path, alias=True)
    setup_game(tmp_path / 'source')
    source = tmp_path / 'source/game'
    Backups(tmp_path / 'source').apply(
        prepare_install([package_bytes(consumer), package_bytes(provider)], source).preparation)
    folder, bundle = export_active(source, tmp_path / 'merged')
    retained = {package.identity: package for package in map(read_package, bundle.packages)}
    assert retained[consumer.identity].manifest == consumer.manifest
    assert retained[provider.identity].manifest == provider.manifest

    setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path / 'recipient')
    deploy(root, (), virtual=virtual, backups=backups, folders=(folder,))
    if virtual:
        lock = load_profile(root)['compilation']
    else:
        from cdmw.domain.new_item.compilation_storage import read_compilation
        state = overlays._load_index(root)
        layer = next(row for row in state['layers'] if row.get('independent_identity') == consumer.identity)
        lock = read_compilation(layer['independent_compilation'], state['compilation_contexts'])
    graph = validate_link_record(lock['inputs']['links'])
    assert graph['order'] == [provider.identity, consumer.identity]
    assert graph['requirements'][0]['content'] == provider.digest
    assert graph['providers'][provider.identity]['exports']['items/travel-sword']['value'] == (
        load_registry(root)['items'][provider.identity]['values']['iteminfo']['item'])
    for identity, source_row in load_registry(source)['items'].items():
        assert load_registry(root)['items'][identity]['values'] == source_row['values']

    before = files_in(root)
    consumer_path = package_path(tmp_path, retained[consumer.identity])
    with pytest.raises(IndependentItemError, match='missing required package'):
        if virtual:
            prepare_profile(VirtualProfile((consumer_path,)), root)
        else:
            prepare_remove(provider.identity, root)
    changed_meta = deepcopy(provider.manifest)
    changed_meta['release'] = '2'
    changed = read_v2(changed_meta, provider.blobs)
    changed_path = package_path(tmp_path, changed)
    with pytest.raises(IndependentItemError, match='release/content differs'):
        if virtual:
            prepare_profile(VirtualProfile((changed_path, consumer_path)), root)
        else:
            prepare_install([changed_path], root)
    assert files_in(root) == before


@pytest.mark.parametrize('remove_first', [False, True])
@pytest.mark.parametrize('virtual', [False, True])
def test_exported_equal_owners_update_disable_remove_last_and_reinstall(tmp_path, remove_first, virtual):
    _, snapshot, _ = setup_game(tmp_path / 'source')
    source = tmp_path / 'source/game'
    packages = [field_package(snapshot, value=7), field_package(snapshot, value=7)]
    raw = snapshot.rows[1001295].raw
    updated = from_iteminfo_operations(snapshot, packages[0].identity, 'Updated equal owner',
        [assignment(raw, value=7), assignment(raw, identity='damage', stat=True, value=13000)], release='2')
    conflicting = field_package(snapshot, identity=packages[0].identity, value=9)
    Backups(tmp_path / 'source').apply(prepare_install([package_bytes(p) for p in packages], source).preparation)
    folder, bundle = export_active(source, tmp_path / 'merged')
    retained = {package.identity: package for package in map(read_package, bundle.packages)}
    assert set(retained) == {package.identity for package in packages}

    setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path / 'recipient')
    stock = game_bytes(root)
    deploy(root, (folder / SEMANTIC_EXPORT_FILE,), virtual=virtual, backups=backups)
    bindings = load_registry(root)
    row = lambda: virtual_row(root) if virtual else snapshot_of(root).rows[1001295]
    assert row().max_stack_count == 7
    paths = [package_path(tmp_path, retained[p.identity]) for p in packages]
    updated_path = package_path(tmp_path, updated)
    deploy(root, (updated_path, paths[1]) if virtual else (updated_path,), virtual=virtual, backups=backups)
    assert row().max_stack_count == 7 and row().stat(0, DDD).value == 13000

    conflicting_path = package_path(tmp_path, conflicting)
    before = files_in(root)
    with pytest.raises(ItemFieldConflict, match='opposing assignments'):
        if virtual:
            prepare_profile(VirtualProfile((conflicting_path, paths[1])), root)
        else:
            prepare_install([conflicting_path], root)
    assert files_in(root) == before

    if virtual:
        deploy(root, (paths[1],), virtual=True, backups=backups)
    else:
        layer = load_registry(root)['items'][packages[0].identity]['layer']
        backups.apply(prepare_overlay_enabled(root, layer, False))
    assert row().max_stack_count == 7
    assert row().stat(0, DDD).value == snapshot.rows[1001295].stat(0, DDD).value
    if virtual:
        deploy(root, (updated_path, paths[1]), virtual=True, backups=backups)
    else:
        backups.apply(prepare_overlay_enabled(root, layer, True))
    assert row().stat(0, DDD).value == 13000

    removed, remaining = (0, 1) if remove_first else (1, 0)
    active_paths = (updated_path, paths[1])
    if virtual:
        deploy(root, (active_paths[remaining],), virtual=True, backups=backups)
    else:
        backups.apply(prepare_remove(packages[removed].identity, root))
    assert row().max_stack_count == 7
    assert row().stat(0, DDD).value == (
        snapshot.rows[1001295].stat(0, DDD).value if remove_first else 13000)
    if virtual:
        deploy(root, (), virtual=True, backups=backups)
        assert not load_profile(root)['items']
        assert game_bytes(root) == stock
    else:
        backups.apply(prepare_remove(packages[remaining].identity, root))
        assert row().raw == snapshot.rows[1001295].raw
    deploy(root, active_paths, virtual=virtual, backups=backups)
    assert row().max_stack_count == 7 and row().stat(0, DDD).value == 13000
    for package in packages:
        assert load_registry(root)['items'][package.identity]['binding_hash'] == (
            bindings['items'][package.identity]['binding_hash'])


@pytest.mark.parametrize('version', [1, 2])
def test_legacy_only_v1_and_v2_packages_still_export_through_real_writer(tmp_path, version):
    service, snapshot, _ = setup_game(tmp_path)
    root = tmp_path / 'game'
    package = from_plan(service.plan(shop_spec('OrdinaryExport'), snapshot, capture_independent=True), uuid4().hex)
    if version == 2:
        package = migrate_v1(package)
    Backups(tmp_path).apply(prepare_install([package_bytes(package)], root).preparation)
    before = files_in(root)

    exported = export_merged_mod(prepare_independent_mod_merge(root), tmp_path / 'merged')
    assert exported.package_root == tmp_path / 'merged'
    assert mod_metadata_path(exported.package_root, 'new-item.json').is_file()
    assert read_semantic_export(exported.package_root) is None
    assert files_in(root) == before


def test_disabled_field_owner_does_not_prevent_export_of_active_legacy_item(tmp_path):
    service, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    legacy = from_plan(service.plan(shop_spec('RetainedLegacy'), snapshot, capture_independent=True), uuid4().hex)
    fields = field_package(snapshot, value=snapshot.rows[1001295].max_stack_count)
    backups.apply(prepare_install([package_bytes(legacy), package_bytes(fields)], root).preparation)
    layer = load_registry(root)['items'][fields.identity]['layer']
    backups.apply(prepare_overlay_enabled(root, layer, False))
    before = files_in(root)

    plan = prepare_independent_mod_merge(root)
    assert plan.files and not plan.conflicts
    exported = export_merged_mod(plan, tmp_path / 'legacy-merged')
    assert read_semantic_export(exported.package_root) is None
    assert files_in(root) == before
