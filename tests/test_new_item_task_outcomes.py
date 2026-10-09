"""Real queued delivery must agree with a package writer's terminal outcome."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from dataclasses import replace
from pathlib import Path
import threading
import time
import zipfile

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.core.item_icon_addition import NewItemIcon, icon_string_for_stem, icon_target_path
from cdmw.core.stringinfo_table import stringinfo_key
from cdmw.domain.new_item.spec import IconSource
from cdmw.domain.cancellation import RunCancelled
from cdmw.services import independent_item_package as packages
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.workers.utility_workers import UtilityWorker
from tests.test_archive_overlay_manager import shop_spec
from tests.test_independent_items import setup_game
from tests.test_new_item_service import _fake_dds


def pump(app, predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.001)
    assert predicate(), 'Owned worker did not finish'


@pytest.fixture
def studio(tmp_path):
    app = QApplication.instance() or QApplication([])
    service, snapshot, _ = setup_game(tmp_path / 'author')
    spec = replace(shop_spec('TerminalResult'), icon=IconSource.GENERATED)
    name = icon_string_for_stem(service.allocate(spec, snapshot).stem)
    icon = NewItemIcon(name, stringinfo_key(name), icon_target_path(name), _fake_dds(), None, None)
    controller = NewItemStudioController()
    controller.plan = service.plan(spec, snapshot, icon=icon, capture_independent=True)
    controller._plan_revision = controller._draft_revision
    controller.independent_mode = True
    try:
        yield app, controller
    finally:
        controller.request_shutdown()
        pump(app, lambda: not controller.iter_shutdown_workers())


@pytest.mark.parametrize('phase', ['before_io', 'resource_io', 'before_replace', 'after_replace', 'queued'])
def test_export_cancellation_agrees_with_atomic_output(studio, tmp_path, monkeypatch, phase):
    app, controller = studio
    entered, release = threading.Event(), threading.Event()
    destination = tmp_path / 'result.cditem'
    completed, statuses, callback_threads = [], [], []
    old_identity = controller.draft.independent_identity
    controller.export_finished.connect(completed.append)
    controller.export_finished.connect(lambda _value: callback_threads.append(threading.get_ident()))
    controller.status_message.connect(lambda *value: statuses.append(value))

    def pause():
        entered.set()
        assert release.wait(5), 'Test did not release its owned writer'

    if phase == 'before_io':
        original = packages.from_plan
        def from_plan(*args, **kwargs):
            pause()
            return original(*args, **kwargs)
        monkeypatch.setattr(packages, 'from_plan', from_plan)
    elif phase == 'resource_io':
        original = zipfile._ZipWriteFile.write
        def write(writer, data):
            result = original(writer, data)
            if writer._zinfo.filename.startswith('assets/') and not entered.is_set():
                pause()
            return result
        monkeypatch.setattr(packages, '_ZIP_CHUNK_BYTES', 64)
        monkeypatch.setattr(zipfile._ZipWriteFile, 'write', write)
    elif phase in ('before_replace', 'after_replace'):
        original = packages.os.replace
        def publish(source, target):
            if Path(target) == destination and phase == 'before_replace':
                pause()  # The writer has already passed its last cancellation guard.
            result = original(source, target)
            if Path(target) == destination and phase == 'after_replace':
                pause()
            return result
        monkeypatch.setattr(packages.os, 'replace', publish)

    try:
        assert controller.start_independent_export(destination)
        # Deliberately hold GUI delivery; worker completion must survive the next
        # queued Cancel even when the native worker has already stopped.
        if phase == 'queued':
            assert controller._thread.wait(5000)
        else:
            assert entered.wait(5)
        assert controller.cancel_operation('export')
    finally:
        release.set()
        pump(app, lambda: not controller.busy)

    if phase in ('before_io', 'resource_io'):
        assert not destination.exists() and completed == []
        assert controller.draft.independent_identity == old_identity
        assert statuses == [('Operation cancelled.', False)]
    else:
        exported = packages.read_package(destination)
        assert len(completed) == 1
        assert completed[0].identity == exported.identity == controller.draft.independent_identity
        assert completed[0].digest == exported.digest
        assert callback_threads == [threading.get_ident()]
        assert statuses == []
    assert not list(tmp_path.glob('.cditem-*.tmp'))


def test_shutdown_suppresses_queued_callback_without_removing_committed_export(studio, tmp_path):
    app, controller = studio
    destination = tmp_path / 'shutdown.cditem'
    completed, statuses = [], []
    controller.export_finished.connect(completed.append)
    controller.status_message.connect(lambda *value: statuses.append(value))
    assert controller.start_independent_export(destination)
    assert controller._thread.wait(5000)
    controller.request_shutdown()
    pump(app, lambda: not controller.iter_shutdown_workers())
    assert packages.read_package(destination).identity
    assert completed == statuses == []


def test_late_cancel_does_not_hide_a_real_export_error(studio, tmp_path, monkeypatch):
    app, controller = studio
    entered, release = threading.Event(), threading.Event()
    statuses, completed = [], []
    controller.status_message.connect(lambda *value: statuses.append(value))
    controller.export_finished.connect(completed.append)
    destination = tmp_path / 'failed.cditem'

    def fail(_source, _target):
        entered.set()
        assert release.wait(5)
        raise OSError('owned publication failure')

    monkeypatch.setattr(packages.os, 'replace', fail)
    try:
        assert controller.start_independent_export(destination)
        assert entered.wait(5)
        assert controller.cancel_operation('export')
    finally:
        release.set()
        pump(app, lambda: not controller.busy)
    assert statuses == [('owned publication failure', True)]
    assert completed == [] and not destination.exists()
    assert not list(tmp_path.glob('.cditem-*.tmp'))


@pytest.mark.parametrize('publishes', [False, True])
@pytest.mark.parametrize('result', ['success', 'cancel', 'failure'])
def test_worker_outcome_preserves_legacy_signals_and_actual_terminal_state(publishes, result):
    terminal, completed, errors, finished = [], [], [], []
    value = object()

    def task(_log, stop):
        assert stop.is_set()  # A requested cancellation alone cannot decide the result.
        if result == 'cancel':
            raise RunCancelled('owned cancellation')
        if result == 'failure':
            raise OSError('owned failure')
        return value

    worker = UtilityWorker(task, task_accepts_cancel=True, publishes_result=publishes)
    worker.outcome.connect(terminal.append)
    worker.completed.connect(completed.append)
    worker.error.connect(errors.append)
    worker.finished.connect(lambda: finished.append(True))
    worker.stop()
    worker.run()
    assert len(terminal) == 1 and finished == [True]
    outcome = terminal[0]
    if result == 'success':
        assert outcome.kind == ('committed' if publishes else 'completed')
        assert outcome.value is value and completed == [value] and errors == []
    else:
        assert outcome.kind == ('cancelled' if result == 'cancel' else 'failed')
        assert errors == [outcome.message] and completed == []


@pytest.mark.parametrize('synchronous', [False, True])
def test_typed_cancellation_without_a_ui_request_has_one_terminal_callback(studio, synchronous):
    app, controller = studio
    controller._synchronous = synchronous
    cancelled, completed, errors = [], [], []

    def task(_log, _stop):
        raise RunCancelled('The service cancelled before publication')

    assert controller._run('export', task, completed.append, errors.append, publishes_result=True,
                           on_cancel=lambda: cancelled.append(True))
    pump(app, lambda: not controller.busy)
    assert cancelled == [True] and completed == errors == []


@pytest.mark.parametrize('kind', ['merge', 'update'])
def test_mod_export_dialog_keeps_committed_result_after_late_cancel(studio, tmp_path, monkeypatch, kind):
    from types import SimpleNamespace
    from cdmw.ui.new_item import mod_merge_dialog, mod_update_dialog
    app, controller = studio
    module, dialog_type, factory = (
        (mod_merge_dialog, mod_merge_dialog.ModMergeDialog, 'mod_merge_export_task') if kind == 'merge' else
        (mod_update_dialog, mod_update_dialog.ModUpdateDialog, 'mod_update_export_task'))
    entered, release = threading.Event(), threading.Event()
    destination = tmp_path / 'owned-export'

    def task(_log, _stop):
        destination.mkdir()
        (destination / 'result').write_bytes(b'owned fixture')
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(package_root=destination)

    monkeypatch.setattr(module, factory, lambda *args, **kwargs: task)
    dialog = dialog_type(controller, str(tmp_path))
    dialog.destination.setText(str(destination))
    dialog._plan = SimpleNamespace(conflicts=(), can_update=True)
    try:
        dialog._export()
        assert entered.wait(5)
        assert controller.cancel_operation('mod_' + kind)
        release.set()
        pump(app, lambda: not controller.busy)
        assert str(destination) in dialog.status.text() and 'written' in dialog.status.text()
        assert dialog._plan is None and not dialog._working
        assert (destination / 'result').read_bytes() == b'owned fixture'
    finally:
        release.set()
        dialog.reject()
        pump(app, lambda: not controller.busy)
