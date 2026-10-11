"""Flattened exports must refuse required intent their folder format cannot retain."""
from uuid import uuid4

import pytest

from cdmw.core.mod_export_history import mod_metadata_path
from cdmw.domain.archives.overlay_merge import OverlayConflict
from cdmw.services.archive_overlay_manager import prepare_overlay_enabled
from cdmw.services.independent_item_compatibility import (
    prepare_independent_mod_merge, scan_independent_conflicts,
)
from cdmw.services.independent_item_install import load_registry, prepare_install
from cdmw.services.independent_item_package import from_plan, package_bytes
from cdmw.services.independent_mod_package import migrate_v1
from cdmw.services.mod_merge_service import export_merged_mod
from tests.test_archive_overlay_manager import Backups, shop_spec
from tests.test_independent_item_fields import field_package
from tests.test_independent_item_regressions import files_in
from tests.test_independent_items import setup_game
from tests.test_independent_package_links import pair


@pytest.mark.parametrize('value', [1, 7])
def test_flattened_export_refuses_explicit_fields_including_source_equal_requirement(tmp_path, value):
    _, snapshot, _ = setup_game(tmp_path)
    root = tmp_path / 'game'
    package = field_package(snapshot, value=value)
    Backups(tmp_path).apply(prepare_install([package_bytes(package)], root).preparation)
    before = files_in(root)

    report = scan_independent_conflicts(root)
    assert report.compatible, report.text()
    with pytest.raises(OverlayConflict, match='merged archive export cannot preserve') as error:
        prepare_independent_mod_merge(root)
    assert package.title in str(error.value)
    assert '.cditem' in str(error.value)
    assert files_in(root) == before


def test_flattened_export_refuses_dependency_pins_and_typed_exports(tmp_path):
    provider, consumer = pair(tmp_path, alias=True)
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    Backups(tmp_path).apply(prepare_install([package_bytes(consumer), package_bytes(provider)], root).preparation)
    before = files_in(root)

    report = scan_independent_conflicts(root)
    assert report.compatible, report.text()
    with pytest.raises(OverlayConflict, match='merged archive export cannot preserve'):
        prepare_independent_mod_merge(root)
    assert files_in(root) == before


@pytest.mark.parametrize('version', [1, 2])
def test_legacy_only_v1_and_v2_packages_still_export_through_real_writer(tmp_path, version):
    service, snapshot, _ = setup_game(tmp_path)
    root = tmp_path / 'game'
    package = from_plan(service.plan(shop_spec('OrdinaryExport'), snapshot, capture_independent=True), uuid4().hex)
    if version == 2:
        package = migrate_v1(package)
    Backups(tmp_path).apply(prepare_install([package_bytes(package)], root).preparation)
    before = files_in(root)

    plan = prepare_independent_mod_merge(root)
    destination = tmp_path / 'merged'
    exported = export_merged_mod(plan, destination)
    assert exported.package_root == destination
    assert mod_metadata_path(destination, 'new-item.json').is_file()
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
    assert files_in(root) == before
