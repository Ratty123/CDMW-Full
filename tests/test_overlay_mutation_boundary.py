"""Rollback owns publication work only after a mutating call can have begun."""
from dataclasses import replace
from pathlib import Path
import threading

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.services import archive_overlay_manager as overlays
from cdmw.services.independent_item_install import prepare_install, prepare_remove
from cdmw.services.independent_item_package import package_bytes
from tests.test_archive_overlay_manager import Backups
from tests.test_independent_item_fields import field_package
from tests.test_independent_item_regressions import files_in
from tests.test_independent_items import setup_game


@pytest.fixture
def prepared_item(tmp_path):
    _, snapshot, _ = setup_game(tmp_path)
    root = tmp_path / 'game'
    package = field_package(snapshot)
    prepared = prepare_install([package_bytes(package)], root).preparation
    return root, Backups(tmp_path), package.identity, prepared


@pytest.mark.parametrize('new_target', [False, True])
@pytest.mark.parametrize('failure', ['cancel_inside_check', 'error_inside_check', 'cancel_after_check'])
def test_premutation_failure_preserves_external_bytes_without_restore_or_cleanup(prepared_item, monkeypatch, new_target, failure):
    root, backups, _, prepared = prepared_item
    stop = threading.Event()
    relative = prepared.directory_name + '/0.paz' if new_target else 'meta/0.papgt'
    target = root / relative
    assert (dict(prepared.before)[relative] is None) == new_target
    validate, write = overlays._verify_source_content, overlays.atomic_write_bytes
    checks, own_writes, restores, changed = [], [], [], []

    def external_change_during_final_check(preparation, stop_event):
        validate(preparation, stop_event)
        checks.append(True)
        if len(checks) == 2:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'external writer must retain these bytes')
            changed.append(files_in(root))
            if failure == 'error_inside_check':
                raise RuntimeError('injected prepublication failure')
            stop.set()
            if failure == 'cancel_inside_check':
                raise RunCancelled('injected cancellation during final validation')

    def record_write(path, data):
        own_writes.append(path)
        return write(path, data)

    def record_restore(path):
        restores.append(path)
        backups.restore_backup(path)

    monkeypatch.setattr(overlays, '_verify_source_content', external_change_during_final_check)
    monkeypatch.setattr(overlays, 'atomic_write_bytes', record_write)
    with pytest.raises(RuntimeError if failure == 'error_inside_check' else RunCancelled):
        overlays.apply_overlay_change(prepared, confirmed=True,
            backup=lambda paths, label: backups.backup_files(paths, description=label),
            restore_backup=record_restore, game_running=lambda: False, stop_event=stop)
    assert len(checks) == 2 and backups.count == 1 and own_writes == []
    assert restores == []
    assert files_in(root) == changed[0]


def test_mount_only_replace_then_raise_still_restores_verified_backup(prepared_item, monkeypatch):
    root, backups, _, prepared = prepared_item
    mount = 'meta/0.papgt'
    prepared = replace(prepared, writes=((mount, dict(prepared.writes)[mount]),),
        before=((mount, dict(prepared.before)[mount]),), deletes=(), paths=())
    original = files_in(root)
    write = overlays.atomic_write_bytes
    restores = []

    def fail_after_replace(path, data):
        write(path, data)
        raise OSError('injected failure after mount replacement')

    def restore(path):
        restores.append(path)
        backups.restore_backup(path)

    monkeypatch.setattr(overlays, 'atomic_write_bytes', fail_after_replace)
    with pytest.raises(OSError, match='after mount replacement'):
        overlays.apply_overlay_change(prepared, confirmed=True,
            backup=lambda paths, label: backups.backup_files(paths, description=label),
            restore_backup=restore, game_running=lambda: False)
    assert len(restores) == 1 and files_in(root) == original


def test_unlink_then_raise_restores_removed_archive_and_ownership(prepared_item, monkeypatch):
    root, backups, identity, prepared = prepared_item
    backups.apply(prepared)
    original = files_in(root)
    removal = prepare_remove(identity, root)
    removed_file = root / next(path for path in removal.deletes if path.endswith('/0.pamt'))
    unlink = Path.unlink
    deleted = []

    def fail_after_unlink(path, *args, **kwargs):
        result = unlink(path, *args, **kwargs)
        if path == removed_file:
            deleted.append(path)
            raise OSError('injected failure after archive deletion')
        return result

    monkeypatch.setattr(Path, 'unlink', fail_after_unlink)
    with pytest.raises(OSError, match='after archive deletion'):
        backups.apply(removal)
    assert deleted == [removed_file] and files_in(root) == original
