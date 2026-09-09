"""Real Qt construction, folder export, and worker close/stale-result behavior."""
import os
import threading
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop
from PySide6.QtWidgets import QApplication

from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.mod_merge_dialog import ModMergeDialog
from tests.test_mod_merge import make_mods, payloads


@pytest.fixture
def app():
    app = QApplication.instance() or QApplication([])
    yield app
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def drain(app, condition):
    deadline = time.monotonic() + 5
    while not condition() and time.monotonic() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        time.sleep(0.005)
    assert condition()


def test_dialog_checks_real_folders_and_exports_without_a_new_item_draft(app, tmp_path):
    _service, _snapshot, _entries, plans, folders = make_mods(tmp_path)
    controller = NewItemStudioController(synchronous=True)
    dialog = ModMergeDialog(controller, tmp_path / "game")
    try:
        assert controller.snapshot is None and controller.plan is None
        for folder in folders:
            dialog.add_folder(folder)
        dialog.destination.setText(str(tmp_path / "combined"))
        assert dialog.scan_button.isEnabled() and not dialog.export_button.isEnabled()
        dialog.scan_button.click()
        assert dialog.export_button.isEnabled(), dialog.status.text() + dialog.review.toPlainText()
        dialog.export_button.click()
        assert "Merged mod written" in dialog.status.text()
        assert any("iteminfo" in path for path in payloads(tmp_path / "combined"))
        assert not dialog.export_button.isEnabled()
        assert controller.plan is None
    finally:
        dialog.reject()
        controller.deleteLater()


def test_dialog_reports_conflicts_and_invalidates_review_when_selection_changes(app, tmp_path):
    _service, _snapshot, _entries, _plans, folders = make_mods(tmp_path, same_key=True)
    controller = NewItemStudioController(synchronous=True)
    dialog = ModMergeDialog(controller, tmp_path / "game")
    try:
        for folder in folders:
            dialog.add_folder(folder)
        dialog.destination.setText(str(tmp_path / "combined"))
        dialog.scan_button.click()
        assert "1990000" in dialog.review.toPlainText()
        assert not dialog.export_button.isEnabled()
        dialog.folders.setCurrentRow(0)
        dialog.remove_button.click()
        assert dialog._plan is None and not dialog.export_button.isEnabled()
    finally:
        dialog.reject()
        controller.deleteLater()


def test_closing_dialog_cancels_its_worker_without_waiting(app, tmp_path, monkeypatch):
    from cdmw.ui.new_item import mod_merge_dialog
    from cdmw.domain.cancellation import raise_if_cancelled
    started, cancelled = threading.Event(), threading.Event()
    def factory(*_args):
        def run(_log, stop):
            started.set()
            stop.wait(3)
            if stop.is_set():
                cancelled.set()
            raise_if_cancelled(stop, "cancelled")
            return None
        return run
    monkeypatch.setattr(mod_merge_dialog, "mod_merge_scan_task", factory)
    controller = NewItemStudioController()
    dialog = ModMergeDialog(controller, tmp_path / "game")
    dialog.add_folder(tmp_path / "a")
    dialog.add_folder(tmp_path / "b")
    dialog.scan_button.click()
    try:
        drain(app, started.is_set)
        before = time.monotonic()
        dialog.reject()
        assert time.monotonic() - before < 0.2
        drain(app, lambda: not controller.busy)
        assert cancelled.is_set()
    finally:
        controller.cancel_operation("mod_merge")
        drain(app, lambda: not controller.busy)
        controller.deleteLater()


def test_late_result_cannot_reenable_export_after_selection_changed(app, tmp_path):
    controller = NewItemStudioController(synchronous=True)
    calls = []
    controller._run = lambda _lane, _task, done, failed: calls.append((done, failed)) or True
    dialog = ModMergeDialog(controller, tmp_path / "game")
    try:
        dialog.add_folder(tmp_path / "a")
        dialog.add_folder(tmp_path / "b")
        dialog.destination.setText(str(tmp_path / "out"))
        dialog.scan_button.click()
        dialog.add_folder(tmp_path / "c")
        calls[0][0](SimpleNamespace(conflicts=(), folders=(1, 2), files=(), items=()))
        assert dialog._plan is None and not dialog.export_button.isEnabled()
    finally:
        dialog.reject()
        controller.deleteLater()
