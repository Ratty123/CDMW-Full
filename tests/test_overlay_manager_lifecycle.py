import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.overlay_manager_dialog import OverlayManagerDialog


def pump(app, predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    assert predicate()


def test_close_cancels_preview_and_keeps_its_worker_owner_alive_until_finished(tmp_path, monkeypatch):
    from cdmw.domain.cancellation import raise_if_cancelled
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController(synchronous=False)
    monkeypatch.setattr(OverlayManagerDialog, 'refresh', lambda self: None)
    dialog = OverlayManagerDialog(controller, tmp_path, None)
    monkeypatch.setattr(dialog.preview, '_ensure_host', lambda: True)
    started, release = threading.Event(), threading.Event()
    cancelled = []

    def source(stop):
        started.set()
        assert release.wait(3)
        cancelled.append(stop.is_set())
        raise_if_cancelled(stop)

    dialog.open()
    dialog.preview.show(source, token='owned-blocked-preview')
    try:
        pump(app, started.is_set)
        dialog.reject()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert isValid(dialog), 'The running preview retains its QObject/thread owner.'
        beats = []
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: beats.append(True))
        pump(app, lambda: bool(beats))
        release.set()
        pump(app, lambda: not dialog.iter_shutdown_workers())
        dialog._delete_when_ready()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not isValid(dialog)
        assert cancelled == [True]
    finally:
        release.set()
        if isValid(dialog):
            dialog.request_shutdown()
            pump(app, lambda: not dialog.iter_shutdown_workers())
            dialog.deleteLater()
        controller.deleteLater()


def test_close_deletes_a_preview_host_reparented_to_a_rust_portal(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from PySide6.QtWidgets import QWidget
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController(synchronous=False)
    monkeypatch.setattr(OverlayManagerDialog, 'refresh', lambda self: None)
    dialog = OverlayManagerDialog(controller, tmp_path, None)
    rust_host = QWidget()
    preview_host = QWidget(rust_host)
    preview_host.controller = SimpleNamespace(shutdown=lambda: None)
    preview_host.set_icon_capture_mode = lambda _: None
    dialog.preview.host = preview_host
    dialog.reject()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(dialog)
    assert not isValid(preview_host)
    rust_host.deleteLater()
    controller.deleteLater()


@pytest.mark.parametrize('operation', ['read', 'apply', 'failed_apply'])
def test_close_discards_late_reads_and_preserves_transaction_outcomes(tmp_path, monkeypatch, operation):
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController(synchronous=False)
    started, release = threading.Event(), threading.Event()
    received, errors, rendered = [], [], []
    controller.install_finished.connect(received.append)
    controller.status_message.connect(lambda message, error: errors.append(message) if error else None)
    result = object()

    def task(_log, _stop):
        started.set()
        assert release.wait(3)
        if operation == 'failed_apply':
            raise OSError('transaction failed and restored its backup')
        return result

    # Control the read task as well: closing must not publish into its deleted UI.
    monkeypatch.setattr(OverlayManagerDialog, 'refresh', lambda self: None)
    dialog = OverlayManagerDialog(controller, tmp_path, None)
    dialog.open()
    dialog._run(task, rendered.append, 'Working', applying=operation != 'read')
    try:
        pump(app, started.is_set)
        dialog.reject()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not isValid(dialog)
        release.set()
        pump(app, lambda: not controller.busy)
        assert rendered == []
        assert received == ([result] if operation == 'apply' else [])
        assert errors == (['transaction failed and restored its backup'] if operation == 'failed_apply' else [])
    finally:
        release.set()
        pump(app, lambda: not controller.busy)
        controller.deleteLater()
