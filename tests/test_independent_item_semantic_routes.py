"""Scans retain typed intent; flattened exports refuse intent they cannot preserve."""
from uuid import uuid4

import pytest

from cdmw.core.iteminfo_row import set_max_stack_count
from cdmw.domain.archives.iteminfo_composition import item_pair, replace_rows, rows_of
from cdmw.domain.archives.overlay_merge import OverlayConflict
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.iteminfo_operations import ItemFieldConflict
from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services.archive_overlay_manager import prepare_overlay_enabled
from cdmw.services.archive_overlay_rebuild import prepare_overlay_rebuild
from cdmw.services.independent_item_compatibility import scan_independent_conflicts, prepare_independent_mod_merge
from cdmw.services.independent_item_install import load_registry, prepare_install, prepare_remove
from cdmw.services.independent_item_package import from_plan, package_bytes
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import publish_profile
from tests.test_archive_overlay_manager import Backups, shop_spec, snapshot_of
from tests.test_independent_item_compatibility import mount_mod
from tests.test_independent_item_fields import field_package, virtual_row
from tests.test_independent_item_regressions import files_in
from tests.test_independent_items import setup_game


def assert_scan_and_export_boundary(root, *, fields=True):
    before = files_in(root)
    report = scan_independent_conflicts(root)
    assert report.compatible, report.text()
    if fields:
        with pytest.raises(OverlayConflict, match='merged archive export cannot preserve'):
            prepare_independent_mod_merge(root)
        assert files_in(root) == before
        return
    plan = prepare_independent_mod_merge(root)
    files = {path: data for path, data, _ in plan.files}
    body, header = item_pair(files)
    expected = snapshot_of(root)
    assert rows_of(files[body], files[header]) == {key: row.raw for key, row in expected.rows.items()}
    assert files_in(root) == before


@pytest.mark.parametrize('reverse', [False, True])
def test_scanning_and_export_policy_keep_disjoint_fields_through_rebuild_disable_and_removal(tmp_path, reverse):
    _, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    packages = [field_package(snapshot), field_package(snapshot, stat=True, value=13000)]
    backups.apply(prepare_install([package_bytes(p) for p in (packages[::-1] if reverse else packages)], root).preparation)
    bindings = load_registry(root)
    assert_scan_and_export_boundary(root)
    backups.apply(prepare_overlay_rebuild(root))
    assert_scan_and_export_boundary(root)
    layer = bindings['items'][packages[0].identity]['layer']
    backups.apply(prepare_overlay_enabled(root, layer, False))
    assert_scan_and_export_boundary(root)
    backups.apply(prepare_overlay_enabled(root, layer, True))
    assert_scan_and_export_boundary(root)
    assert load_registry(root) == bindings
    backups.apply(prepare_remove(packages[0].identity, root))
    assert_scan_and_export_boundary(root)


@pytest.mark.parametrize('value', [1, 7])
def test_equal_assignments_stay_owned_after_refused_export_and_removal(tmp_path, value):
    _, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    packages = [field_package(snapshot, value=value), field_package(snapshot, value=value)]
    opposite = package_bytes(field_package(snapshot, value=9))
    backups.apply(prepare_install([package_bytes(p) for p in packages], root).preparation)
    assert_scan_and_export_boundary(root)
    backups.apply(prepare_remove(packages[0].identity, root))
    assert_scan_and_export_boundary(root)
    before = files_in(root)
    with pytest.raises(ItemFieldConflict, match='opposing assignments'):
        prepare_install([opposite], root)
    assert files_in(root) == before


@pytest.mark.parametrize('mounted', [False, True])
def test_source_equal_requirement_cannot_disappear_under_foreign_edit(tmp_path, mounted):
    _, snapshot, _ = setup_game(tmp_path)
    root = tmp_path / 'game'
    package = field_package(snapshot, value=snapshot.rows[1001295].max_stack_count)
    path = tmp_path / 'keep-stack.cditem'
    path.write_bytes(package_bytes(package))
    Backups(tmp_path).apply(prepare_install([path], root).preparation)
    pair = snapshot.iteminfo
    files = {pair.payload_entry.path: replace_rows(pair.payload, pair.header,
                {1001295: set_max_stack_count(snapshot.rows[1001295], 9)}),
             pair.header_entry.path: pair.header}
    folder = tmp_path / 'foreign'
    if mounted:
        mount_mod(root, folder, files)
        folders = ()
    else:
        for name, data in files.items():
            target = folder / 'files' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        folders = (folder,)
    before = files_in(root)
    report = scan_independent_conflicts(root, folders=folders)
    assert not report.compatible, report.text()
    assert 'source row changed' in report.text()
    with pytest.raises(OverlayConflict, match='source row changed'):
        prepare_independent_mod_merge(root, folders=folders)
    if mounted:
        with pytest.raises(IndependentItemError, match='source row changed'):
            prepare_overlay_rebuild(root)
    else:
        setup_game(tmp_path / 'virtual')
        virtual_root = tmp_path / 'virtual/game'
        virtual_before = files_in(virtual_root)
        with pytest.raises(IndependentItemError, match='source row changed'):
            prepare_profile(VirtualProfile((path,), folders), virtual_root)
        assert files_in(virtual_root) == virtual_before
    assert files_in(root) == before


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('remove_legacy', [False, True])
def test_source_equal_assignment_and_legacy_requirement_coexist_and_remain_enforced(tmp_path, reverse, remove_legacy):
    service, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    legacy = from_plan(service.plan(shop_spec('SourceEqualLegacy'), snapshot, capture_independent=True), uuid4().hex)
    field = field_package(snapshot, value=snapshot.rows[1001295].max_stack_count)
    opposite = package_bytes(field_package(snapshot, value=9))
    packages = [legacy, field][::-1] if reverse else [legacy, field]
    backups.apply(prepare_install([package_bytes(p) for p in packages], root).preparation)
    bindings = load_registry(root)['items']
    assert_scan_and_export_boundary(root)
    backups.apply(prepare_remove(legacy.identity if remove_legacy else field.identity, root))
    assert_scan_and_export_boundary(root, fields=remove_legacy)
    assert load_registry(root)['items'][legacy.identity]['binding_hash'] == bindings[legacy.identity]['binding_hash']
    before = files_in(root)
    with pytest.raises(ItemFieldConflict):
        prepare_install([opposite], root)
    assert files_in(root) == before


@pytest.mark.parametrize('reverse', [False, True])
def test_virtual_source_equal_assignment_preserves_legacy_rows_and_bindings(tmp_path, reverse):
    service, snapshot, _ = setup_game(tmp_path)
    root = tmp_path / 'game'
    legacy = from_plan(service.plan(shop_spec('SourceEqualVirtual'), snapshot, capture_independent=True), uuid4().hex)
    field = field_package(snapshot, value=snapshot.rows[1001295].max_stack_count)
    paths = []
    for package in (legacy, field):
        path = tmp_path / f'{package.identity}.cditem'
        path.write_bytes(package_bytes(package))
        paths.append(path)
    publish_profile(prepare_profile(VirtualProfile(tuple(paths[::-1] if reverse else paths)), root))
    bindings = load_registry(root)['items']
    assert virtual_row(root).raw == snapshot.rows[1001295].raw
    publish_profile(prepare_profile(VirtualProfile((paths[1],)), root))
    assert virtual_row(root).raw == snapshot.rows[1001295].raw
    assert load_registry(root)['items'][legacy.identity]['binding_hash'] == bindings[legacy.identity]['binding_hash']
