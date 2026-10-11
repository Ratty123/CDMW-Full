"""Actual queued texture-package authoring through the shared UI controller."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
import sys
import threading
import time
import traceback

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QFileDialog

from cdmw.services import independent_item_package as codec
from cdmw.services.independent_item_install import resolve_items
from cdmw.services.independent_item_package import read_package, write_package
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.texture_workflow import independent_package_dialog as dialog_module
from tests.test_independent_item_regressions import files_in
from tests.test_independent_texture_authoring import change_same_size_and_timestamp
from tests.test_independent_texture_packages import TEXTURE_PATH, dds_payload, texture_game, texture_package
from tests.test_texture_replacement_workspace import wait_for, workspace


@pytest.fixture
def texture_dialog(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    root, snapshot = texture_game(tmp_path)
    replacement = tmp_path / 'replacement.dds'
    replacement.write_bytes(dds_payload(fill=1))
    controller = NewItemStudioController()
    dialog = dialog_module.IndependentTexturePackageDialog(controller, root)
    callback_errors = []
    monkeypatch.setattr(sys, 'excepthook',
        lambda *error: callback_errors.append(''.join(traceback.format_exception(*error))))
    dialog.show()
    try:
        yield app, root, snapshot, replacement, controller, dialog
    finally:
        dialog.request_shutdown()
        controller.shutdown()
        wait_for(lambda: not controller.busy)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
        assert not callback_errors, '\n'.join(callback_errors)


def find_and_review(dialog, controller, replacement, destination):
    dialog.texture_filter.setText(TEXTURE_PATH)
    dialog.find_button.click()
    wait_for(lambda: not controller.busy)
    assert dialog.target.currentText() == TEXTURE_PATH, dialog.status.text()
    dialog.replacement.setText(str(replacement))
    if dialog._update is None:
        dialog.destination.setText(str(destination))
    assert dialog.review_button.isEnabled(), dialog.status.text()
    dialog.review_button.click()
    wait_for(lambda: not controller.busy)
    assert dialog._plan is not None, dialog.status.text()
    assert TEXTURE_PATH in dialog.review.toPlainText()
    assert dialog.write_button.isEnabled()


def load_update(dialog, controller, destination, monkeypatch):
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_a, **_k: (str(destination), ''))
    dialog.load_button.click()
    wait_for(lambda: not controller.busy)
    assert dialog._update is not None, dialog.status.text()
    assert dialog.destination.isReadOnly()


def test_actual_queued_new_write_and_loaded_update_preserve_identity_and_compile(texture_dialog, tmp_path, monkeypatch):
    app, root, _snapshot, replacement, controller, dialog = texture_dialog
    before = files_in(root)
    worker_calls, deliveries = [], []
    for name in ('find_existing_texture_targets', 'load_texture_package_update',
                 'prepare_texture_package', 'write_texture_package'):
        actual = getattr(dialog_module, name)
        def check_worker(*args, _actual=actual, _name=name, **kwargs):
            assert QThread.currentThread() != app.thread()
            worker_calls.append(_name)
            return _actual(*args, **kwargs)
        monkeypatch.setattr(dialog_module, name, check_worker)
    for name in ('_found', '_loaded', '_prepared', '_written'):
        actual = getattr(dialog, name)
        def check_delivery(value, _actual=actual, _name=name):
            assert QThread.currentThread() == app.thread()
            deliveries.append(_name)
            return _actual(value)
        monkeypatch.setattr(dialog, name, check_delivery)
    destination = tmp_path / 'texture.cditem'
    dialog.texture_filter.setText(TEXTURE_PATH)
    dialog.find_button.click()
    wait_for(lambda: not controller.busy)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_a, **_k: (str(replacement), ''))
    dialog.replacement_browse.click()
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *_a, **_k: (str(destination), ''))
    dialog.destination_browse.click()
    dialog.title.setText('Queued texture')
    dialog.review_button.click()
    wait_for(lambda: not controller.busy)
    assert dialog._plan is not None, dialog.status.text()
    identity = dialog._plan.package.identity
    dialog.write_button.click()
    wait_for(lambda: not controller.busy)
    first = read_package(destination)
    assert first.identity == identity
    assert dialog._identity != identity, 'A later new package must receive a fresh identity.'
    assert 'written to' in dialog.status.text()
    assert dialog._plan is None
    load_update(dialog, controller, destination, monkeypatch)
    assert dialog._update.identity == identity and dialog._update.digest == first.digest
    replacement.write_bytes(dds_payload(fill=2))
    dialog.release.setText('2')
    find_and_review(dialog, controller, replacement, destination)
    dialog.write_button.click()
    wait_for(lambda: not controller.busy)
    updated = read_package(destination)
    assert updated.identity == identity and updated.digest != first.digest
    assert updated.manifest['release'] == '2'
    assert 'written to' in dialog.status.text()
    assert dialog._plan is None
    assert set(worker_calls) == {'find_existing_texture_targets', 'load_texture_package_update',
                                 'prepare_texture_package', 'write_texture_package'}
    assert deliveries.count('_written') == 2 and deliveries.count('_prepared') == 2
    for target in ('archive', 'virtual'):
        resolved = resolve_items([destination], root, target=target)
        assert resolved.contributions[0][1][TEXTURE_PATH]['after'] == replacement.read_bytes()
        assert resolved.rows[0][2] is None
    assert files_in(root) == before


def test_queued_publication_guard_keeps_selected_package_after_same_stamp_input_drift(texture_dialog, tmp_path, monkeypatch):
    app, _root, snapshot, replacement, controller, dialog = texture_dialog
    destination = tmp_path / 'texture.cditem'
    write_package(texture_package(snapshot), destination)
    previous = destination.read_bytes()
    load_update(dialog, controller, destination, monkeypatch)
    replacement.write_bytes(dds_payload(fill=2))
    dialog.release.setText('2')
    find_and_review(dialog, controller, replacement, destination)
    actual_write, actual_read = codec._write_package_archive, codec.read_package
    readbacks = []
    def drift_after_stage(package, stream, stop):
        assert QThread.currentThread() != app.thread()
        actual_write(package, stream, stop)
        change_same_size_and_timestamp(replacement)
    def record_read(source, **kwargs):
        result = actual_read(source, **kwargs)
        if isinstance(source, Path) and source.name.startswith('.cditem-'):
            assert QThread.currentThread() != app.thread()
            readbacks.append(result.identity)
        return result
    monkeypatch.setattr(codec, '_write_package_archive', drift_after_stage)
    monkeypatch.setattr(codec, 'read_package', record_read)
    dialog.write_button.click()
    wait_for(lambda: not controller.busy)
    assert readbacks == [read_package(destination).identity]
    assert 'replacement texture changed' in dialog.status.text()
    assert dialog._plan is None and not dialog.write_button.isEnabled()
    assert destination.read_bytes() == previous
    assert not tuple(tmp_path.glob('.cditem-*.tmp'))


def test_queued_late_cancel_retains_truthful_committed_result(texture_dialog, tmp_path, monkeypatch):
    _app, _root, _snapshot, replacement, controller, dialog = texture_dialog
    destination = tmp_path / 'texture.cditem'
    find_and_review(dialog, controller, replacement, destination)
    actual_write = dialog_module.write_texture_package
    committed, release = threading.Event(), threading.Event()
    def commit_before_delivery(*args, **kwargs):
        result = actual_write(*args, **kwargs)
        committed.set()
        assert release.wait(5), 'The test must release the committed worker.'
        assert kwargs['stop_event'].is_set()
        return result
    monkeypatch.setattr(dialog_module, 'write_texture_package', commit_before_delivery)
    try:
        dialog.write_button.click()
        wait_for(committed.is_set)
        assert destination.is_file() and controller.busy
        dialog.cancel_button.click()
        assert 'Cancelling' in dialog.status.text()
        release.set()
        wait_for(lambda: not controller.busy)
        assert 'written to' in dialog.status.text()
        assert dialog._plan is None
        assert read_package(destination).manifest['requires'] == {'texture.replace': 1}
    finally:
        release.set()
        wait_for(lambda: not controller.busy)


def test_close_during_real_queued_review_cancels_without_blocking_or_late_delivery(texture_dialog, tmp_path, monkeypatch):
    _app, _root, _snapshot, replacement, controller, dialog = texture_dialog
    dialog.texture_filter.setText(TEXTURE_PATH)
    dialog.find_button.click()
    wait_for(lambda: not controller.busy)
    dialog.replacement.setText(str(replacement))
    dialog.destination.setText(str(tmp_path / 'texture.cditem'))
    actual_prepare = dialog_module.prepare_texture_package
    entered, release = threading.Event(), threading.Event()
    delivered = []
    def pending_review(*args, **kwargs):
        entered.set()
        assert release.wait(5), 'The test must release the cancelled worker.'
        return actual_prepare(*args, **kwargs)
    monkeypatch.setattr(dialog_module, 'prepare_texture_package', pending_review)
    monkeypatch.setattr(dialog, '_prepared', lambda result: delivered.append(result))
    try:
        dialog.review_button.click()
        wait_for(entered.is_set)
        started = time.monotonic()
        dialog.reject()
        assert time.monotonic() - started < .25
        assert dialog._closed and controller.busy
        assert controller._thread is not None, 'The shared controller retains the running native thread.'
        assert controller._cancel_requested_lane == 'independent_texture'
        release.set()
        wait_for(lambda: not controller.busy)
        assert not delivered and dialog._plan is None
        assert not (tmp_path / 'texture.cditem').exists()
    finally:
        release.set()
        wait_for(lambda: not controller.busy)


@pytest.mark.parametrize('workspace', ['legacy', 'compact_rail'], indirect=True)
def test_texture_toolbar_opens_discoverable_package_editor_on_shared_controller(workspace):
    window, textures, _matcher = workspace
    assert textures.job.mode == 'replace'
    assert not textures.independent_package_button.isHidden()
    textures.independent_package_button.click()
    dialog = textures._texture_package_dialog
    assert dialog.isVisible()
    assert dialog.controller is window._shared_new_item_controller()
    assert dialog.controller is textures.shell._shared_new_item_controller()
    assert dialog.target.count() == 0 and not dialog.write_button.isEnabled()
    textures.independent_package_button.click()
    assert textures._texture_package_dialog is dialog
    dialog.close()
