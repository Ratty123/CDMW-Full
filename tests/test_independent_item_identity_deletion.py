"""Explicit identity cleanup must not damage archives or retained install history."""
import threading

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services import archive_overlay_manager as overlays
from cdmw.services import independent_item_install as installer
from cdmw.services.independent_item_package import canonical, package_bytes
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import publish_profile
from tests.test_archive_overlay_manager import Backups, snapshot_of
from tests.test_independent_items import authored, setup_game
from tests.test_independent_item_regressions import files_in
from tests.test_virtual_loader import game_bytes


@pytest.fixture
def removed_item(tmp_path):
    _, package = authored(tmp_path / 'author')
    setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    backups.apply(installer.prepare_install([package_bytes(package)], root).preparation)
    backups.apply(installer.prepare_remove(package.identity, root))
    return root, package, backups


def delete(prepared, backups, **kwargs):
    return installer.apply_identity_deletion(prepared, confirmed=True, mutations=backups,
                                             game_running=lambda: False, **kwargs)


def test_deletion_changes_only_local_ledgers_and_matching_backup_restores_them(removed_item, tmp_path):
    root, package, backups = removed_item
    before, registry = files_in(root), installer.load_registry(root)
    prepared = installer.prepare_identity_deletion(package.identity, root)
    assert files_in(root) == before
    assert set(dict(prepared.writes)) == {installer.REGISTRY_PATH, overlays.INDEX_PATH}
    result = delete(prepared, backups)
    assert result.identity == package.identity and result.title == package.title
    assert installer.inventory(root) == ()
    after = files_in(root)
    assert set(after) == set(before)
    assert {path.as_posix() for path in before if before[path] != after[path]} == set(dict(prepared.writes))
    exported = installer.export_profile(root, tmp_path / 'without-deleted.cdprofile')
    assert package.identity not in installer._read_registry(exported)['items']
    # Retain immutable payload journals: other layers can still need their baseline.
    layers = overlays._load_index(root)['layers']
    assert layers and all('independent_identity' not in layer for layer in layers)
    backups.restore_backup(result.backup_dir)
    assert files_in(root) == before and installer.load_registry(root) == registry


def test_deleted_identity_can_be_reused_and_reinstalled_with_other_items_intact(tmp_path):
    _, first = authored(tmp_path / 'first')
    _, second = authored(tmp_path / 'second')
    _, third = authored(tmp_path / 'third')
    _, updated = authored(tmp_path / 'updated', first.identity, 'Updated')
    setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    backups.apply(installer.prepare_install([package_bytes(first), package_bytes(second)], root).preparation)
    original = installer.load_registry(root)['items']
    freed_key = original[first.identity]['values']['iteminfo']['item']
    backups.apply(installer.prepare_install([package_bytes(updated)], root).preparation)
    backups.apply(installer.prepare_remove(first.identity, root))
    before = game_bytes(root)
    delete(installer.prepare_identity_deletion(first.identity, root), backups)
    assert game_bytes(root) == before
    assert installer.load_registry(root)['items'][second.identity] == original[second.identity]
    backups.apply(installer.prepare_install([package_bytes(third)], root).preparation)
    assert installer.load_registry(root)['items'][third.identity]['values']['iteminfo']['item'] == freed_key
    backups.apply(installer.prepare_install([package_bytes(updated)], root).preparation)
    current = installer.load_registry(root)['items']
    assert current[first.identity]['values']['iteminfo']['item'] != freed_key
    assert current[second.identity] == original[second.identity]
    backups.apply(installer.prepare_remove(second.identity, root))
    assert {row[0] for row in installer.inventory(root) if row[3] == 'Installed'} == {first.identity, third.identity}
    assert current[first.identity]['values']['iteminfo']['item'] in snapshot_of(root).rows


@pytest.mark.parametrize('route', ['installed', 'disabled', 'virtual'])
def test_active_and_disabled_identities_cannot_be_deleted(tmp_path, route, monkeypatch):
    monkeypatch.setattr('cdmw.services.new_item_service.game_is_running', lambda: False)
    _, package = authored(tmp_path / 'author')
    setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    if route == 'virtual':
        source = tmp_path / 'item.cditem'
        source.write_bytes(package_bytes(package))
        publish_profile(prepare_profile(VirtualProfile((source,)), root))
    else:
        backups.apply(installer.prepare_install([package_bytes(package)], root).preparation)
        if route == 'disabled':
            layer = installer.load_registry(root)['items'][package.identity]['layer']
            backups.apply(overlays.prepare_overlay_enabled(root, layer, False))
    before = files_in(root)
    with pytest.raises(ValueError, match='Remove this item from Mods'):
        installer.prepare_identity_deletion(package.identity, root)
    assert files_in(root) == before


def test_removed_virtual_identity_deletion_preserves_the_active_profile(tmp_path, monkeypatch):
    monkeypatch.setattr('cdmw.services.new_item_service.game_is_running', lambda: False)
    from tests.test_virtual_loader import packages
    from cdmw.services.virtual_loader_state import load_profile
    root, sources = packages(tmp_path)
    publish_profile(prepare_profile(VirtualProfile(sources), root))
    identities = list(installer.load_registry(root)['items'])
    publish_profile(prepare_profile(VirtualProfile(sources[1:]), root))
    before, profile = game_bytes(root), load_profile(root)
    removed = (set(identities) - set(profile['items'])).pop()
    prepared = installer.prepare_identity_deletion(removed, root)
    assert set(dict(prepared.writes)) == {installer.REGISTRY_PATH}
    delete(prepared, Backups(tmp_path))
    assert game_bytes(root) == before and load_profile(root) == profile
    assert {row[0] for row in installer.inventory(root)} == set(profile['items'])
    publish_profile(prepare_profile(VirtualProfile(sources), root))
    assert len(installer.inventory(root)) == 2


def test_forgetting_removed_linked_items_keeps_remaining_reservations_readable(tmp_path):
    from tests.test_independent_package_links import pair
    provider, consumer = pair(tmp_path)
    setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    backups.apply(installer.prepare_install([package_bytes(provider), package_bytes(consumer)], root).preparation)
    backups.apply(installer.prepare_remove(consumer.identity, root))
    with pytest.raises(ValueError, match='Another installed item'):
        installer.prepare_identity_deletion(consumer.identity, root)
    backups.apply(installer.prepare_remove(provider.identity, root))
    provider_row = installer.load_registry(root)['items'][provider.identity]
    delete(installer.prepare_identity_deletion(consumer.identity, root), backups)
    assert installer.load_registry(root)['items'] == {provider.identity: provider_row}
    delete(installer.prepare_identity_deletion(provider.identity, root), backups)
    assert not installer.inventory(root)
    backups.apply(installer.prepare_install([package_bytes(provider), package_bytes(consumer)], root).preparation)
    assert all(row[3] == 'Installed' for row in installer.inventory(root))


@pytest.mark.parametrize('phase', ['before_backup', 'after_backup'])
def test_stale_identity_deletion_refuses_without_overwriting_newer_records(removed_item, monkeypatch, phase):
    root, package, backups = removed_item
    prepared = installer.prepare_identity_deletion(package.identity, root)
    def change():
        registry = installer.load_registry(root)
        registry['items'][package.identity]['title'] = 'Newer title'
        (root / installer.REGISTRY_PATH).write_bytes(canonical(registry))
    if phase == 'before_backup':
        change()
    else:
        original = backups.backup_files
        def backup(*args, **kwargs):
            result = original(*args, **kwargs)
            change()
            return result
        monkeypatch.setattr(backups, 'backup_files', backup)
    with pytest.raises(ValueError, match='changed'):
        delete(prepared, backups)
    assert installer.load_registry(root)['items'][package.identity]['title'] == 'Newer title'


@pytest.mark.parametrize('phase', ['before_backup', 'after_backup'])
def test_cancelled_identity_deletion_keeps_original_ledgers(removed_item, monkeypatch, phase):
    root, package, backups = removed_item
    prepared = installer.prepare_identity_deletion(package.identity, root)
    before, stop = files_in(root), threading.Event()
    if phase == 'before_backup':
        stop.set()
    else:
        original = backups.backup_files
        def backup(*args, **kwargs):
            result = original(*args, **kwargs)
            stop.set()
            return result
        monkeypatch.setattr(backups, 'backup_files', backup)
    with pytest.raises(RunCancelled):
        delete(prepared, backups, stop_event=stop)
    assert files_in(root) == before


def test_partial_identity_deletion_rolls_back_both_ledgers(removed_item, monkeypatch):
    root, package, backups = removed_item
    prepared, before = installer.prepare_identity_deletion(package.identity, root), files_in(root)
    writer = installer.atomic_write_bytes
    def fail(path, payload):
        writer(path, payload)
        if path == root / overlays.INDEX_PATH:
            raise OSError('injected publication failure')
    monkeypatch.setattr(installer, 'atomic_write_bytes', fail)
    with pytest.raises(OSError, match='injected publication failure'):
        delete(prepared, backups)
    assert files_in(root) == before
    assert installer.inventory(root)[0][3] == 'Removed / reserved'


def test_identity_deletion_requires_confirmation_and_a_verified_backup(removed_item, monkeypatch):
    root, package, backups = removed_item
    prepared, before = installer.prepare_identity_deletion(package.identity, root), files_in(root)
    with pytest.raises(PermissionError, match='confirmation'):
        installer.apply_identity_deletion(prepared, confirmed=False, mutations=backups)
    monkeypatch.setattr(backups, 'backup_files', lambda *args, **kwargs: root / 'missing-backup')
    with pytest.raises(ValueError, match='backup manifest'):
        delete(prepared, backups)
    assert files_in(root) == before


@pytest.mark.parametrize('outcome', ['delete', 'rollback', 'stale', 'cancel'])
def test_bulk_identity_deletion_is_one_recoverable_transaction(tmp_path, monkeypatch, outcome):
    from tests.test_virtual_loader import packages
    root, sources = packages(tmp_path, 3)
    backups = Backups(tmp_path)
    backups.apply(installer.prepare_install(sources, root).preparation)
    identities = tuple(installer.load_registry(root)['items'])
    backups.apply(installer.prepare_remove(identities[:2], root))
    registry, before = installer.load_registry(root), files_in(root)
    prepared = installer.prepare_identity_deletion(identities[:2], root)
    assert tuple(row[0] for row in prepared.items) == identities[:2]
    assert files_in(root) == before
    count = backups.count
    stop = threading.Event()
    if outcome == 'rollback':
        writer = installer.atomic_write_bytes
        def fail(path, data):
            writer(path, data)
            if path == root / overlays.INDEX_PATH:
                raise OSError('batch publication failure')
        monkeypatch.setattr(installer, 'atomic_write_bytes', fail)
    elif outcome in ('stale', 'cancel'):
        backup = backups.backup_files
        def intervene(*args, **kwargs):
            result = backup(*args, **kwargs)
            if outcome == 'cancel':
                stop.set()
            else:
                registry['items'][identities[1]]['title'] = 'Changed after review'
                (root / installer.REGISTRY_PATH).write_bytes(canonical(registry))
            return result
        monkeypatch.setattr(backups, 'backup_files', intervene)
    if outcome == 'delete':
        result = delete(prepared, backups)
        assert set(installer.load_registry(root)['items']) == {identities[2]}
        assert installer.load_registry(root)['items'][identities[2]] == registry['items'][identities[2]]
        backups.restore_backup(result.backup_dir)
        assert files_in(root) == before
    else:
        with pytest.raises({'rollback': OSError, 'stale': ValueError, 'cancel': RunCancelled}[outcome]):
            delete(prepared, backups, stop_event=stop)
        assert installer.load_registry(root) == registry
        if outcome != 'stale':
            assert files_in(root) == before
    assert backups.count == count + 1


def test_bulk_identity_deletion_rejects_an_installed_member_without_changes(tmp_path):
    from tests.test_virtual_loader import packages
    root, sources = packages(tmp_path)
    backups = Backups(tmp_path)
    backups.apply(installer.prepare_install(sources, root).preparation)
    identities = tuple(installer.load_registry(root)['items'])
    backups.apply(installer.prepare_remove(identities[0], root))
    before = files_in(root)
    with pytest.raises(ValueError, match='Remove this item from Mods'):
        installer.prepare_identity_deletion(identities, root)
    assert files_in(root) == before
