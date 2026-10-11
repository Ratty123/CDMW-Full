"""Queued Mesh overlay outcomes must describe the actual installation result."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEventLoop, QObject, QThread, QTimer, Qt, Slot
from PySide6.QtWidgets import QApplication

from cdmw.domain.archives.mutation import ArchivePatchRequest
from cdmw.services import archive_overlay_install as install
from cdmw.workers import mesh_editor_workers as workers
from tests.test_archive_overlay_manager import Backups
from tests.test_independent_items import setup_game


class _Receiver(QObject):
    def __init__(self):
        super().__init__()
        self.results = []
        self.finished_count = 0
        self.callback_threads = []

    def record(self, kind, request_id, value):
        self.results.append((kind, request_id, value))
        self.callback_threads.append(threading.get_ident())

    @Slot(int, object)
    def completed(self, request_id, value):
        self.record('completed', request_id, value)

    @Slot(int, str)
    def cancelled(self, request_id, value):
        self.record('cancelled', request_id, value)

    @Slot(int, str)
    def error(self, request_id, value):
        self.record('error', request_id, value)

    @Slot()
    def finished(self):
        self.finished_count += 1
        self.callback_threads.append(threading.get_ident())


def _run_queued(app, worker):
    receiver = _Receiver()
    thread = QThread()
    worker.moveToThread(thread)
    worker.completed.connect(receiver.completed, Qt.QueuedConnection)
    worker.cancelled.connect(receiver.cancelled, Qt.QueuedConnection)
    worker.error.connect(receiver.error, Qt.QueuedConnection)
    worker.finished.connect(receiver.finished, Qt.QueuedConnection)
    worker.finished.connect(thread.quit, Qt.DirectConnection)
    thread.finished.connect(worker.deleteLater)
    thread.started.connect(worker.run)
    loop, timer = QEventLoop(), QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    thread.finished.connect(loop.quit, Qt.QueuedConnection)
    try:
        timer.start(5_000)
        thread.start()
        loop.exec()
        assert thread.wait(1_000), 'Owned overlay worker did not stop'
        app.processEvents()
        assert receiver.finished_count == 1
        assert len(receiver.results) == 1
        assert receiver.callback_threads == [threading.get_ident()] * 2
        return receiver.results[0]
    finally:
        timer.stop()
        thread.quit()
        assert thread.wait(1_000), 'Owned overlay thread could not be cleaned up'
        thread.deleteLater()
        receiver.deleteLater()
        app.processEvents()


@pytest.mark.parametrize('phase', [
    'before_backup', 'restored', 'failed_restore', 'failed_backup', 'committed',
])
def test_queued_overlay_outcome_matches_disk(tmp_path, monkeypatch, phase):
    app = QApplication.instance() or QApplication([])
    _, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    pathc, mount = root / 'meta/0.pathc', root / 'meta/0.papgt'
    before_pathc, before_mount = pathc.read_bytes(), mount.read_bytes()
    shipped = {path: path.read_bytes() for path in (root / '0009').glob('*') if path.is_file()}
    replacement = b'owned synthetic metadata replacement'
    prepared = install.prepare_overlay_install(
        [ArchivePatchRequest(snapshot.iteminfo.payload_entry, b'owned synthetic table')],
        package_root=root, meta_files=(('meta/0.pathc', replacement),),
    )
    restores, execution_threads = [], []
    retained_backup = {}
    monkeypatch.setattr(install, 'overlay_baseline_dir', lambda _root: tmp_path / 'baseline')
    monkeypatch.setattr(workers, 'game_is_running', lambda: False)

    def backup(paths, *, description):
        execution_threads.append(threading.get_ident())
        if phase == 'failed_backup':
            stop.set()
            raise OSError('owned backup failure')
        directory = backups.backup_files(paths, description=description)
        manifest = directory / 'backup_manifest.json'
        retained_backup[manifest] = manifest.read_bytes()
        for row in json.loads(retained_backup[manifest])['files']:
            copy = Path(row['backup_path'])
            retained_backup[copy] = copy.read_bytes()
        return directory

    def restore(path, *, confirmed):
        assert confirmed
        restores.append(path)
        if phase == 'failed_restore':
            raise OSError('owned recovery failure')
        return backups.restore_backup(path, confirmed=confirmed)

    worker = workers.MeshOverlayApplyWorker(
        19, prepared, SimpleNamespace(backup_files=backup, restore_backup=restore),
    )
    stop = worker.stop_event
    write = install._write_atomic

    def write_and_cancel(path, payload):
        write(path, payload)
        if (path == pathc and phase in ('restored', 'failed_restore')) or (
            path == mount and phase == 'committed'
        ):
            stop.set()

    monkeypatch.setattr(install, '_write_atomic', write_and_cancel)
    if phase == 'before_backup':
        worker.stop()
    kind, request_id, value = _run_queued(app, worker)
    assert request_id == 19 and stop.is_set()
    assert all(ident != threading.get_ident() for ident in execution_threads)
    assert all(path.read_bytes() == payload for path, payload in shipped.items())
    assert all(path.read_bytes() == payload for path, payload in retained_backup.items())
    if phase in ('restored', 'failed_restore'):
        assert len(restores) == 1
        scope = restores[0]
        assert scope.name == 'scoped-restore'
        assert scope.is_relative_to(tmp_path / 'backup-0')
        manifest = json.loads((scope / 'backup_manifest.json').read_bytes())
        assert {Path(row['original_path']) for row in manifest['files']} == {pathc}

    if phase in ('before_backup', 'restored'):
        assert kind == 'cancelled'
        assert 'cancelled' in value.lower()
        assert 'rolled back' not in value.lower()  # No unverified recovery-success claim.
        assert pathc.read_bytes() == before_pathc
        assert mount.read_bytes() == before_mount
        if phase == 'before_backup':
            assert restores == []
        assert not prepared.directory.exists()
    elif phase == 'failed_restore':
        assert kind == 'error'
        assert 'owned recovery failure' in value
        assert str(tmp_path / 'backup-0') in value
        assert pathc.read_bytes() == replacement
        assert mount.read_bytes() == before_mount
        assert (tmp_path / 'backup-0/backup_manifest.json').is_file()
    elif phase == 'failed_backup':
        assert kind == 'error' and 'owned backup failure' in value
        assert restores == [] and backups.count == 0
        assert pathc.read_bytes() == before_pathc
        assert mount.read_bytes() == before_mount
        assert not prepared.directory.exists()
    else:
        assert kind == 'completed'
        assert value.kind == 'overlay_install'
        assert value.output_path == prepared.directory
        assert value.install_result.backup_dir == tmp_path / 'backup-0'
        assert value.install_result.receipt_path.is_file()
        assert pathc.read_bytes() == replacement
        assert mount.read_bytes() == prepared.papgt_after
        assert restores == []
