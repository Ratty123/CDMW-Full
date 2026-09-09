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
