"""Read dependencies must remain identical through review and verified backup."""
import os
import threading

import pytest

from cdmw.services import archive_overlay_manager as overlays
from cdmw.services.independent_item_install import prepare_install
from cdmw.services.independent_item_package import package_bytes
from tests.test_archive_overlay_manager import Backups
from tests.test_independent_item_fields import field_package
from tests.test_independent_item_regressions import files_in
from tests.test_independent_items import setup_game


@pytest.mark.parametrize('during_backup', [False, True])
@pytest.mark.parametrize('suffix', ['.pamt', '.paz'])
def test_same_size_same_timestamp_source_change_cannot_publish(tmp_path, during_backup, suffix):
    _, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    prepared = prepare_install([package_bytes(field_package(snapshot))], root).preparation
    entry = snapshot.iteminfo.payload_entry
    source = entry.pamt_path if suffix == '.pamt' else entry.paz_file
    offset = source.stat().st_size - 1 if suffix == '.pamt' else entry.offset + (entry.comp_size if entry.compressed else entry.orig_size) - 1
    original_stamp = overlays._stamp(source)
    changed = None

    def mutate():
        nonlocal changed
        stamp = source.stat()
        with source.open('r+b') as handle:
            handle.seek(offset)
            byte = handle.read(1)
            handle.seek(offset)
            handle.write(bytes([byte[0] ^ 1]))
        os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        assert overlays._stamp(source) == original_stamp
        changed = files_in(root)

    def backup(paths, description):
        result = backups.backup_files(paths, description=description)
        if during_backup:
            mutate()
        return result

    if not during_backup:
        mutate()
    with pytest.raises(ValueError, match='[Ss]ource'):
        overlays.apply_overlay_change(prepared, confirmed=True, backup=backup,
            restore_backup=backups.restore_backup, game_running=lambda: False)
    assert files_in(root) == changed
    assert backups.count == int(during_backup)


@pytest.mark.parametrize('during_backup', [False, True])
def test_cancellation_during_source_verification_preserves_previous_installation(tmp_path, monkeypatch, during_backup):
    from cdmw.domain.cancellation import RunCancelled

    _, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    prepared = prepare_install([package_bytes(field_package(snapshot))], root).preparation
    original = files_in(root)
    stop = threading.Event()
    checksum = overlays._read_source_checksum
    restores = []

    def cancel_in_checksum(path, stop_event):
        if bool(backups.count) == during_backup:
            stop.set()
        return checksum(path, stop_event)

    def restore(path):
        restores.append(path)
        backups.restore_backup(path)

    monkeypatch.setattr(overlays, '_read_source_checksum', cancel_in_checksum)
    with pytest.raises(RunCancelled):
        overlays.apply_overlay_change(prepared, confirmed=True,
            backup=lambda paths, label: backups.backup_files(paths, description=label),
            restore_backup=restore, game_running=lambda: False, stop_event=stop)
    assert files_in(root) == original
    assert backups.count == len(restores) == int(during_backup)
