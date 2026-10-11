"""Receipt diagnostics through actual queued launch and lookup ownership paths."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import json
from pathlib import Path
import sys
import threading
import traceback
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from cdmw.domain.virtual_loader import VirtualProfile, VirtualSessionStatus
from cdmw.services import virtual_loader_receipts as receipts
from cdmw.services import virtual_loader_runtime as runtime
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.virtual_loader_page import VirtualLoaderPage
from tests.test_mod_management import pump
from tests.test_virtual_loader import game_bytes
from tests.test_virtual_loader_saves import experimental_fixture


@pytest.fixture
def pages(monkeypatch):
    app = QApplication.instance() or QApplication([])
    owned, errors = [], []
    monkeypatch.setattr(sys, 'excepthook',
        lambda *error: errors.append(''.join(traceback.format_exception(*error))))

    def create(root):
        controller = NewItemStudioController()
        page = VirtualLoaderPage(controller, root)
        owned.append((controller, page))
        page.show()
        return app, controller, page

    yield create
    for controller, page in owned:
        page.request_shutdown()
        controller.shutdown()
    for controller, page in owned:
        pump(app, lambda: not controller.iter_shutdown_workers())
        page.close()
        page.deleteLater()
    app.processEvents()
    assert not errors, '\n'.join(errors)


@pytest.mark.parametrize('diagnostic_stage', ['none', 'preparation', 'launch'])
@pytest.mark.parametrize('late_cancel', [False, True])
def test_actual_queued_launch_keeps_receipts_diagnostics_and_committed_result(
        tmp_path, monkeypatch, pages, diagnostic_stage, late_cancel):
    root, _files, save = experimental_fixture(tmp_path, monkeypatch)
    before, save_before = game_bytes(root), save.read_bytes()
    app, controller, page = pages(root)
    page.refresh()
    pump(app, lambda: not controller.busy)
    assert page.launch_button.isEnabled(), page.status.text()

    worker_calls, delivered, reviews, spawns = [], [], [], []
    for name in ('prepare_experimental_launch', 'launch_experimental', 'session_status'):
        original = getattr(runtime, name)
        def checked(*args, _original=original, _name=name, **kwargs):
            assert QThread.currentThread() != app.thread()
            worker_calls.append(_name)
            result = _original(*args, **kwargs)
            if _name == 'prepare_experimental_launch':
                reviews.append(result)
            return result
        monkeypatch.setattr(runtime, name, checked)
    started = page._started
    def completed(result):
        assert QThread.currentThread() == app.thread()
        delivered.append(result)
        started(result)
    monkeypatch.setattr(page, '_started', completed)

    def spawn(command, **kwargs):
        assert QThread.currentThread() != app.thread()
        spawns.append((command, kwargs))
        return SimpleNamespace(pid=123)
    monkeypatch.setattr(runtime.subprocess, 'Popen', spawn)
    monkeypatch.setattr(runtime, '_process_alive', lambda pid: pid in (123, 456))
    monkeypatch.setattr('cdmw.services.process_job_service.breakaway_creation_flags', lambda: 0)
    if diagnostic_stage == 'preparation':
        def missing_backup_receipt(*args, **kwargs):
            assert QThread.currentThread() != app.thread()
            raise OSError('owned preparation receipt failure')
        monkeypatch.setattr(receipts, 'record_backup', missing_backup_receipt)

    entered, release = threading.Event(), threading.Event()
    record_launch = receipts.record_launch
    def observed_launch(*args, **kwargs):
        assert len(spawns) == 1, 'The process boundary has already returned success.'
        assert QThread.currentThread() != app.thread()
        entered.set()
        if late_cancel:
            assert release.wait(5)
        if diagnostic_stage == 'launch':
            raise OSError('owned launch receipt failure')
        return record_launch(*args, **kwargs)
    monkeypatch.setattr(receipts, 'record_launch', observed_launch)

    try:
        page.launch_button.click()
        if late_cancel:
            pump(app, entered.is_set)
            if diagnostic_stage == 'preparation':
                assert 'owned preparation receipt failure' in page.receipt_details.toPlainText()
            page.cancel_button.click()
            assert controller.busy and not delivered
            release.set()
        pump(app, lambda: bool(delivered) and not controller.busy)
        pump(app, lambda: not page._session_lookup.busy)
        page._session_timer.stop()
        result = delivered[0]
        assert result.state == 'starting' and result.pid == 123
        assert page._session == (str(root), result.detail, 123)
        assert result.detail == Path(spawns[0][0][1]).stem
        assert len(result.detail) == 32 and result.detail == reviews[0].receipt_token
        assert page.status.text() == 'Waiting for runtime readiness.'
        assert not page.launch_button.isEnabled()
        assert not page.receipt_details.isHidden()
        assert page.receipt_details.isReadOnly()
        assert page.receipt_details.maximumBlockCount() == 200
        text = page.receipt_details.toPlainText()
        if diagnostic_stage != 'none':
            message = 'owned ' + diagnostic_stage + ' receipt failure'
            assert message in text and text.count(message) == 1
        else:
            assert not result.diagnostics
        chain = receipts.read_session_receipts(root, result.detail)
        assert chain and chain[0].to_dict()['event'] == 'begin'
        assert any(row.to_dict()['event'] == 'launch-started' for row in chain) == (diagnostic_stage != 'launch')
        if result.receipt_path:
            assert Path(result.receipt_path).is_file() and result.receipt_path in text
        assert 'Verification receipt:' in text
        assert (reviews[0].backup.directory / 'files/account/slot1/save.save').read_bytes() == save_before
        assert save.read_bytes() == save_before and game_bytes(root) == before
        assert set(worker_calls) == {'prepare_experimental_launch', 'launch_experimental', 'session_status'}
    finally:
        release.set()


def test_actual_queued_launch_error_survives_receipt_recording_error(tmp_path, monkeypatch, pages):
    root, _files, save = experimental_fixture(tmp_path, monkeypatch)
    before, save_before = game_bytes(root), save.read_bytes()
    app, controller, page = pages(root)
    page.refresh()
    pump(app, lambda: not controller.busy)
    attempts = []
    def spawn(*args, **kwargs):
        attempts.append(args)
        raise OSError('owned host launch failure')
    def receipt_error(*args, **kwargs):
        raise OSError('owned failure receipt failure')
    monkeypatch.setattr(runtime.subprocess, 'Popen', spawn)
    monkeypatch.setattr(receipts, 'record_failure', receipt_error)
    monkeypatch.setattr('cdmw.services.process_job_service.breakaway_creation_flags', lambda: 0)
    page.launch_button.click()
    pump(app, lambda: bool(attempts) and not controller.busy)
    assert page._session is None and not page._session_timer.isActive()
    assert page.status.text() == 'owned host launch failure'
    assert 'failure receipt failure' not in page.status.text()
    assert save.read_bytes() == save_before and game_bytes(root) == before


@pytest.mark.parametrize('state', ['running', 'stopped'])
def test_queued_status_receipt_error_preserves_actual_runtime_state(tmp_path, monkeypatch, pages, state):
    app, controller, page = pages(tmp_path)
    token = 'c' * 32
    path = tmp_path / '.cdmw/virtual-loader' / ('session-' + token + '.json')
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'state': state, 'pid': 456}))
    monkeypatch.setattr(runtime, '_process_alive', lambda pid: True)
    calls, transitions = [], []
    controller.busy_changed.connect(transitions.append)
    def receipt_error(*args, stop_event=None, **kwargs):
        assert QThread.currentThread() != app.thread()
        assert stop_event is not None and not stop_event.is_set()
        calls.append(args)
        raise OSError('owned status receipt failure')
    monkeypatch.setattr(receipts, 'record_status', receipt_error)
    launch_path = str(tmp_path / 'prior-launch-receipt.json')
    page._started(VirtualSessionStatus('starting', token, pid=123, receipt_path=launch_path,
        diagnostics=('owned launch observation warning',)))
    pump(app, lambda: not page._session_lookup.busy)
    page._session_timer.stop()
    assert calls and not controller.busy and transitions == []
    expected = 'The virtual session is running.' if state == 'running' else 'The game session ended.'
    assert page.status.text() == expected and page.progress.isHidden()
    assert (page._session is not None) == (state == 'running')
    text = page.receipt_details.toPlainText()
    assert launch_path in text and 'owned launch observation warning' in text
    assert 'Session status: Session receipt could not be recorded: owned status receipt failure' in text
    if state == 'running':
        for _ in range(4):
            page._poll_session()
            pump(app, lambda: not page._session_lookup.busy)
        assert page.receipt_details.toPlainText() == text
        # A later complete observation supersedes this stage's transient warning.
        monkeypatch.setattr(receipts, 'record_status', lambda *a, **kw: None)
        page._poll_session()
        pump(app, lambda: not page._session_lookup.busy)
        text = page.receipt_details.toPlainText()
        assert 'status receipt failure' not in text and 'owned launch observation warning' in text


def test_queued_legacy_results_keep_receipt_panel_hidden(tmp_path, monkeypatch, pages):
    app, _controller, page = pages(tmp_path)
    stops = []
    def status(*args, stop_event=None, **kwargs):
        stops.append(stop_event)
        return SimpleNamespace(state='running', detail='owned legacy session status', pid=456, progress=None)
    monkeypatch.setattr(runtime, 'session_status', status)
    page._started(SimpleNamespace(state='starting', detail='d' * 32, pid=123))
    pump(app, lambda: not page._session_lookup.busy)
    page._session_timer.stop()
    assert page.status.text() == 'owned legacy session status'
    assert page._session[1] == 'd' * 32
    assert page.receipt_details.isHidden() and not page.receipt_details.toPlainText()
    assert stops and stops[0] is not None


@pytest.mark.parametrize('change', ['root', 'close'])
def test_queued_receipt_lookup_cancels_and_suppresses_stale_details(tmp_path, monkeypatch, pages, change):
    app, controller, page = pages(tmp_path)
    entered, release = threading.Event(), threading.Event()
    stops = []
    def status(*args, stop_event=None, **kwargs):
        assert QThread.currentThread() != app.thread()
        assert stop_event is not None
        stops.append(stop_event)
        entered.set()
        assert release.wait(5)
        return VirtualSessionStatus('stopped', 'stale terminal result', receipt_path='stale-receipt.json',
            diagnostics=('stale receipt warning',))
    monkeypatch.setattr(runtime, 'session_status', status)
    try:
        page._started(VirtualSessionStatus('starting', 'e' * 32, pid=123,
            receipt_path='owned-launch-receipt.json', diagnostics=('owned launch warning',)))
        pump(app, entered.is_set)
        if change == 'root':
            page.set_game_root(tmp_path / 'other')
        else:
            page.request_shutdown()
        assert stops[0].is_set() and page._session_lookup.busy
        assert controller.iter_shutdown_workers(), 'A draining native thread must stay owned.'
        after_change = page.receipt_details.toPlainText()
        release.set()
        pump(app, lambda: not page._session_lookup.busy)
        assert page.receipt_details.toPlainText() == after_change
        assert 'stale' not in page.receipt_details.toPlainText() + page.status.text()
        assert not page._session_timer.isActive()
        if change == 'root':
            assert page.receipt_details.isHidden() and not after_change
    finally:
        release.set()


@pytest.mark.parametrize('change', ['root', 'close'])
def test_queued_stale_preparation_cannot_publish_diagnostics_or_start(tmp_path, monkeypatch, pages, change):
    app, controller, page = pages(tmp_path)
    page._saved_selection = VirtualProfile()
    page._draft_loaded = True
    entered, release = threading.Event(), threading.Event()
    stops, starts = [], []
    def prepare(*args, stop_event=None, **kwargs):
        stops.append(stop_event)
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(backup=SimpleNamespace(directory=tmp_path),
            receipt_token='f' * 32, diagnostics=('stale preparation receipt warning',))
    monkeypatch.setattr(runtime, 'prepare_experimental_launch', prepare)
    monkeypatch.setattr(runtime, 'launch_experimental', lambda *a, **kw: starts.append(kw))
    try:
        page._prepare_launch()
        pump(app, entered.is_set)
        if change == 'root':
            page.set_game_root(tmp_path / 'other')
        else:
            page.request_shutdown()
        assert stops[0].is_set() and controller.iter_shutdown_workers()
        release.set()
        pump(app, lambda: not controller.busy)
        assert not starts and page._session is None
        assert page.receipt_details.isHidden() and not page.receipt_details.toPlainText()
    finally:
        release.set()
