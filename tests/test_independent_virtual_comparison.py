"""Shared-files comparisons use the applied virtual packages without publishing."""
from dataclasses import replace
import threading
from uuid import uuid4

import pytest

from cdmw.domain.archives.overlay_merge import OverlayConflict
from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services import independent_item_compatibility as comparison
from cdmw.services.independent_item_install import load_registry, prepare_install, prepare_remove
from cdmw.services.independent_item_package import from_plan, package_bytes
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import PROFILE_PATH, generation_path, load_profile, publish_profile
from tests.test_archive_overlay_manager import Backups, shop_spec
from tests.test_independent_item_compatibility import table_change
from tests.test_independent_item_regressions import files_in
from tests.test_independent_item_semantic_routes import virtual_row
from tests.test_independent_items import setup_game
from tests.test_new_item_service import TEMPLATE


def applied_virtual_items(tmp_path, monkeypatch, *, borrowed=False):
    monkeypatch.setattr('cdmw.services.new_item_service.game_is_running', lambda: False)
    service, snapshot, _ = setup_game(tmp_path)
    sources = []
    for name in ('VirtualOne', 'VirtualTwo'):
        choice = replace(shop_spec(name), socket_items=(TEMPLATE,)) if borrowed else shop_spec(name)
        package = from_plan(service.plan(choice, snapshot, capture_independent=True), uuid4().hex)
        source = tmp_path / f'{name}.cditem'
        source.write_bytes(package_bytes(package))
        sources.append(source)
    root = tmp_path / 'game'
    publish_profile(prepare_profile(VirtualProfile(tuple(sources)), root))
    return root, tuple(sources), snapshot


def test_two_virtual_items_are_compared_from_applied_versions_without_writes(tmp_path, monkeypatch):
    root, sources, _ = applied_virtual_items(tmp_path, monkeypatch)
    # Downloads are not ownership: a moved file or unapplied draft must not
    # change the installed contributors being compared.
    sources[0].unlink()
    sources[1].write_bytes(b'unapplied draft')
    before = files_in(root)
    report = comparison.scan_independent_conflicts(root)
    assert report.compatible and report.virtual_profile
    assert {'VirtualOne', 'VirtualTwo'} <= {name for row in report.findings for name in row.mods}
    assert 'Install an independent item' not in report.text()
    assert 'Use Apply changes in Mods' in report.text()
    assert not (root / '.cdmw/overlays.json').exists()
    assert files_in(root) == before
    with pytest.raises(OverlayConflict, match='Archive export cannot include'):
        comparison.prepare_independent_mod_merge(root)
    assert files_in(root) == before


def test_virtual_scan_includes_active_archive_items_and_excludes_removed_identities(tmp_path, monkeypatch):
    root, sources, _ = applied_virtual_items(tmp_path, monkeypatch)
    service, snapshot, _ = setup_game(tmp_path / 'author')
    backups = Backups(tmp_path)
    for name in ('ArchivedItem', 'RemovedItem'):
        package = from_plan(service.plan(shop_spec(name), snapshot, capture_independent=True), uuid4().hex)
        backups.apply(prepare_install((package_bytes(package),), root).preparation)
        if name == 'RemovedItem':
            backups.apply(prepare_remove(package.identity, root))
    # Remove one virtual contributor, leaving its ID reserved as well.
    publish_profile(prepare_profile(VirtualProfile(sources[:1]), root))
    before = files_in(root)
    report = comparison.scan_independent_conflicts(root)
    assert report.compatible
    names = {name for row in report.findings for name in row.mods}
    assert {'VirtualOne', 'ArchivedItem'} <= names
    assert not {'RemovedItem', 'VirtualTwo'} & names
    assert len(load_registry(root)['items']) == 4
    assert files_in(root) == before


@pytest.mark.parametrize('saved_folder', [False, True])
@pytest.mark.parametrize('borrowed', [False, True])
def test_virtual_scan_checks_saved_and_prospective_folder_overlaps_and_conflicts(tmp_path, monkeypatch, saved_folder, borrowed):
    root, sources, snapshot = applied_virtual_items(tmp_path, monkeypatch, borrowed=borrowed)
    for binding in load_registry(root)['items'].values():
        clone = virtual_row(root, binding['values']['iteminfo']['item'])
        assert (TEMPLATE in clone.socket_items) == borrowed
    folder = tmp_path / 'external'
    def write_changes(key=None):
        files = table_change(snapshot) if key is None else table_change(snapshot, key=key)
        for relative, data in files.items():
            path = folder / 'files' / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    write_changes()
    if saved_folder:
        publish_profile(prepare_profile(VirtualProfile(sources, (folder,)), root))
    selected = () if saved_folder else (folder,)
    report = comparison.scan_independent_conflicts(root, folders=selected)
    assert report.compatible and report.virtual_profile
    assert any(row.status == 'Merge available' and str(folder) in row.mods for row in report.findings)
    write_changes(TEMPLATE)
    before = files_in(tmp_path)
    report = comparison.scan_independent_conflicts(root, folders=selected)
    assert report.compatible is (not borrowed)
    if borrowed:
        assert str(folder) in report.text() and str(TEMPLATE) in report.text()
        assert any(row.status == 'Conflict' for row in report.findings)
    else:
        assert any(row.status == 'Merge available' and str(folder) in row.mods for row in report.findings)
    assert files_in(tmp_path) == before


def test_virtual_scan_detects_conflicting_typed_archive_contributor(tmp_path, monkeypatch):
    from tests.test_independent_item_fields import field_package
    monkeypatch.setattr('cdmw.services.new_item_service.game_is_running', lambda: False)
    _, snapshot, _ = setup_game(tmp_path)
    root = tmp_path / 'game'
    source = tmp_path / 'virtual.cditem'
    source.write_bytes(package_bytes(field_package(snapshot, value=7)))
    publish_profile(prepare_profile(VirtualProfile((source,)), root))
    Backups(tmp_path).apply(prepare_install((package_bytes(field_package(snapshot, value=8)),), root).preparation)
    before = files_in(root)
    report = comparison.scan_independent_conflicts(root)
    assert not report.compatible and report.virtual_profile
    assert any(row.status == 'Conflict' for row in report.findings)
    assert 'max_stack_count' in report.text()
    assert files_in(root) == before


def test_virtual_scan_accepts_semantic_folder_without_omitting_applied_items(tmp_path, monkeypatch):
    from tests.test_independent_item_fields import field_package
    from tests.test_independent_export_requirements import export_active
    root, _, snapshot = applied_virtual_items(tmp_path, monkeypatch)
    setup_game(tmp_path / 'producer')
    producer = tmp_path / 'producer/game'
    package = field_package(snapshot, value=snapshot.rows[TEMPLATE].max_stack_count)
    Backups(tmp_path).apply(prepare_install((package_bytes(package),), producer).preparation)
    folder = tmp_path / 'semantic'
    export_active(producer, folder)
    before = files_in(tmp_path)
    report = comparison.scan_independent_conflicts(root, folders=(folder,))
    assert report.compatible and report.virtual_profile, report.text()
    assert {'VirtualOne', 'VirtualTwo', 'Existing stack'} <= {name for row in report.findings for name in row.mods}
    assert files_in(tmp_path) == before


def test_folder_only_virtual_profile_is_scanned_and_reports_unsupported_changes(tmp_path, monkeypatch):
    root, _, _ = applied_virtual_items(tmp_path, monkeypatch)
    folder = tmp_path / 'external'
    (folder / 'files/character').mkdir(parents=True)
    (folder / 'files/character/example.txt').write_bytes(b'foreign data')
    publish_profile(prepare_profile(VirtualProfile(mods=(folder,)), root))
    report = comparison.scan_independent_conflicts(root)
    assert report.compatible and report.virtual_profile and str(folder) in report.text()
    assert 'VirtualOne' not in report.text() and 'VirtualTwo' not in report.text()
    (folder / 'unknown.asi').write_bytes(b'unsupported')
    before = files_in(tmp_path)
    report = comparison.scan_independent_conflicts(root)
    assert not report.compatible and 'runtime code' in report.text()
    assert files_in(tmp_path) == before


@pytest.mark.parametrize('missing', [False, True])
def test_missing_or_substituted_retained_virtual_package_is_not_compatible(tmp_path, monkeypatch, missing):
    root, sources, _ = applied_virtual_items(tmp_path, monkeypatch)
    profile = load_profile(root)
    identity, binding = next(iter(profile['items'].items()))
    retained = generation_path(root, profile['generation']) / 'packages' / f'{identity}-{binding["digest"]}.cditem'
    if missing:
        retained.unlink()
    else:
        from cdmw.services.independent_item_package import read_package
        other = next(source for source in sources if read_package(source).identity != identity)
        retained.write_bytes(other.read_bytes())
    before = files_in(root)
    report = comparison.scan_independent_conflicts(root)
    assert not report.compatible and report.virtual_profile
    assert 'Install an independent item' not in report.text()
    assert files_in(root) == before


def test_virtual_profile_change_during_comparison_invalidates_the_result(tmp_path, monkeypatch):
    root, _, _ = applied_virtual_items(tmp_path, monkeypatch)
    validate = comparison._validate_composition_packages
    def changed(*args, **kwargs):
        result = validate(*args, **kwargs)
        (root / PROFILE_PATH).write_bytes(b'changed during scan')
        return result
    monkeypatch.setattr(comparison, '_validate_composition_packages', changed)
    with pytest.raises(OverlayConflict, match='changed during comparison'):
        comparison.scan_independent_conflicts(root)


def test_virtual_scan_preserves_cancellation(tmp_path, monkeypatch):
    root, _, _ = applied_virtual_items(tmp_path, monkeypatch)
    before = files_in(root)
    stop = threading.Event()
    stop.set()
    with pytest.raises(RunCancelled):
        comparison.scan_independent_conflicts(root, stop_event=stop)
    stop.clear()
    from cdmw.services import independent_item_install
    resolve = independent_item_install.resolve_items
    def cancelled(*args, **kwargs):
        stop.set()
        return resolve(*args, **kwargs)
    monkeypatch.setattr(independent_item_install, 'resolve_items', cancelled)
    with pytest.raises(RunCancelled):
        comparison.scan_independent_conflicts(root, stop_event=stop)
    assert files_in(root) == before
