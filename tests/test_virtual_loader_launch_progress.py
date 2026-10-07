"""Launch latency, authoritative guards and stable session-status presentation."""
import json
import threading
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.domain.virtual_loader import VirtualLoaderError, VirtualSessionStatus
from cdmw.services import virtual_loader_runtime as runtime
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.virtual_loader_page import VirtualLoaderPage
from tests.test_mod_management import pump
from tests.test_virtual_loader_saves import experimental_fixture


def test_launch_preflight_avoids_baseline_rehash_but_passes_every_guard_to_host(tmp_path, monkeypatch):
    root, files, _save = experimental_fixture(tmp_path, monkeypatch)
    review = runtime.prepare_experimental_launch(root)
    read, events, manifests = [], [], []
    original = runtime.hash_file
    def hashed(path, *args):
        read.append(Path(path))
        return original(path, *args)
    monkeypatch.setattr(runtime, 'hash_file', hashed)
    def start(game, profile, **kwargs):
        _token, raw = runtime.session_manifest(game, profile, mode=kwargs['mode'],
            executable_sha256=runtime.GAME_SHA256, launcher=runtime._steam_launcher(),
            extra_guards=kwargs['extra_guards'])
        manifests.append((profile, raw))
        return VirtualSessionStatus('starting', 'a' * 32, profile['generation'], 123)
    monkeypatch.setattr(runtime, '_start', start)
    runtime.launch_experimental(review, confirmed=True,
        on_progress=lambda n, total, detail: events.append((n, total, detail)))
    profile, raw = manifests[0]
    baseline = [Path(path) for path, _sha in profile['sources'] if path not in profile['packages']]
    assert baseline and any(path.suffix == '.paz' for path in baseline)
    assert not set(baseline) & set(read)
    assert set(files) <= set(read)
    for path, checksum in profile['sources']:
        assert path.encode('utf-16le') in raw and bytes.fromhex(checksum) in raw
    assert events and [n for n, _, _ in events] == sorted(n for n, _, _ in events)
    assert all(total == 100 and detail for _, total, detail in events)


def test_status_progress_accepts_legacy_reports_and_rejects_invalid_values(tmp_path, monkeypatch):
    token = 'a' * 32
    report = tmp_path / '.cdmw/virtual-loader' / f'session-{token}.json'
    report.parent.mkdir(parents=True)
    monkeypatch.setattr(runtime, '_process_alive', lambda pid: True)
    value = {'state': 'starting', 'pid': 0, 'host_pid': 123, 'detail': 'Verifying launch files...'}
    report.write_text(json.dumps(value))
    assert runtime.session_status(tmp_path, token).progress is None
    report.write_text(json.dumps({**value, 'progress': 37}))
    assert runtime.session_status(tmp_path, token).progress == 37
    for invalid in (-1, 101, True, '37'):
        report.write_text(json.dumps({**value, 'progress': invalid}))
        with pytest.raises(VirtualLoaderError, match='progress'):
            runtime.session_status(tmp_path, token)


def test_session_poll_does_not_toggle_operation_busy_or_repaint_controls(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController()
    page = VirtualLoaderPage(controller, tmp_path)
    transitions, threads = [], []
    controller.busy_changed.connect(transitions.append)
    def status(*args, **kwargs):
        threads.append(threading.get_ident())
        return VirtualSessionStatus('starting', 'Verifying launch files...', progress=37)
    monkeypatch.setattr(runtime, 'session_status', status)
    try:
        page._started(VirtualSessionStatus('starting', 'a' * 32, pid=123))
        page._buttons()
        for _ in range(3):
            pump(app, lambda: not page._session_lookup.busy)
            assert page.progress.value() == 37 and page.add_items.isEnabled()
            assert not page.launch_button.isEnabled()
            assert not controller.busy and not page._working and transitions == []
            page._poll_session()
        pump(app, lambda: not page._session_lookup.busy)
        assert threads and all(t != threading.get_ident() for t in threads)
        page._session_status_ready(page._session, VirtualSessionStatus('running', 'The virtual session is running.', pid=456, progress=100))
        assert page.progress.isHidden() and page._session
        page._session_status_ready(page._session, VirtualSessionStatus('stopped', 'The game session ended.'))
        assert page._session is None and not page._session_timer.isActive()
    finally:
        page.request_shutdown()
        controller.shutdown()
        page.close()


@pytest.mark.parametrize('change', ['root', 'close'])
def test_session_poll_discards_late_results_and_retains_draining_worker(tmp_path, monkeypatch, change):
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController()
    page = VirtualLoaderPage(controller, tmp_path)
    entered, release = threading.Event(), threading.Event()
    def status(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return VirtualSessionStatus('starting', 'stale session result', progress=72)
    monkeypatch.setattr(runtime, 'session_status', status)
    try:
        page._started(VirtualSessionStatus('starting', 'a' * 32, pid=123))
        pump(app, entered.is_set)
        if change == 'root':
            page.set_game_root(tmp_path / 'other')
        else:
            page.request_shutdown()
        assert page._session_lookup.busy and controller.iter_shutdown_workers()
        release.set()
        pump(app, lambda: not page._session_lookup.busy)
        assert 'stale' not in page.status.text() and page.progress.value() != 72
        assert not page._session_timer.isActive()
    finally:
        release.set()
        page.request_shutdown()
        controller.shutdown()
        page.close()
