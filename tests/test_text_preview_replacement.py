"""Preview text must not disconnect Qt objects while a worker is retiring."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.ui.archive_browser.preview_details import ArchivePreviewDetailsMixin
from cdmw.ui.text_preview_widgets import ArchiveDetailsEditor, CodePreviewEditor


@pytest.mark.parametrize("editor_type", [CodePreviewEditor, ArchiveDetailsEditor])
def test_replacing_preview_text_keeps_live_highlighter_connections(editor_type, monkeypatch):
    app = QApplication.instance() or QApplication([])
    editor = editor_type(theme_key="graphite")
    document = editor.document()
    highlighter = editor.syntax_highlighter
    try:
        document.setMaximumBlockCount(4)
        editor.setPlainText("Path: old.dds\nWarning: old preview")
        editor.search_text("old")
        assert editor._search_matches

        # The captured freeze was inside this native disconnect, holding the
        # GIL while a retiring worker held Qt's connection mutex. Fail before
        # entering that call, rather than hanging the test runner on the race.
        def reject_reconnection(_document):
            pytest.fail("Text replacement disconnected the live syntax highlighter")

        monkeypatch.setattr(highlighter, "setDocument", reject_reconnection)
        for index in range(3):
            editor.setPlainText(f"Discarded\nPath: texture_{index}.dds\nWidth: 512\nHeight: 1024\nWarning: preview")
            assert editor.toPlainText() == f"Path: texture_{index}.dds\nWidth: 512\nHeight: 1024\nWarning: preview"
            assert document.blockCount() == 4
            assert highlighter.document() is document
            assert document.lastBlock().layout().formats()
            assert not editor._search_matches
            assert not editor._match_selections
            assert editor.updatesEnabled()
            assert not document.signalsBlocked()
            assert not editor.signalsBlocked()

        editor.setUpdatesEnabled(False)
        editor.setPlainText("Path: final.dds")
        assert not editor.updatesEnabled()
        assert editor.toPlainText() == "Path: final.dds"
        app.processEvents()
    finally:
        editor.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _run_worker_delivery_probe():
    class Worker(QObject):
        completed = Signal(int, object)
        finished = Signal()

        @Slot()
        def run(self):
            self.completed.emit(1, "Path: character/texture/bark_bamboo_01_color.dds\n\nDDS format: BC1_UNORM\nWidth: 512\nHeight: 1024")
            self.finished.emit()

    class Host(QWidget, ArchivePreviewDetailsMixin):
        def __init__(self):
            super().__init__()
            self.archive_preview_details_edit = ArchiveDetailsEditor(theme_key="graphite", parent=self)
            self.archive_preview_details_edit.document().setMaximumBlockCount(2000)
            self.current_archive_preview_result = None
            self.rounds = 0
            self.received = 0

        def start(self):
            self.rounds += 1
            self._set_archive_preview_base_detail_text("Loading texture preview...", include_current_model_debug=False)
            self.thread = QThread(self)
            self.worker = Worker()
            self.worker.moveToThread(self.thread)
            self.thread.started.connect(self.worker.run)
            self.worker.completed.connect(self.ready)
            self.worker.finished.connect(self.thread.quit)
            self.worker.finished.connect(self.worker.deleteLater)
            self.thread.finished.connect(self.cleanup)
            self.thread.start()

        @Slot(int, object)
        def ready(self, _request_id, details):
            self._set_archive_preview_base_detail_text(details, include_current_model_debug=False)
            self.received += 1

        @Slot()
        def cleanup(self):
            if not self.thread.wait(0):
                QTimer.singleShot(1, self.cleanup)
                return
            self.worker = None
            self.thread.deleteLater()
            self.thread = None
            if self.rounds < 32:
                QTimer.singleShot(0, self.start)
            else:
                app.quit()

    app = QApplication([])
    host = Host()
    QTimer.singleShot(0, host.start)
    app.exec()
    assert host.received == host.rounds == 32
    assert host.thread is None
    assert "bark_bamboo_01_color.dds" in host.archive_preview_details_edit.toPlainText()
    host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.shutdown()
    print("32 preview deliveries and worker teardowns completed")


def test_archive_details_updates_complete_during_worker_teardown():
    # A native deadlock cannot be interrupted by a Qt timer in the stuck UI
    # thread. Keep this lifecycle probe in a child owned by the test.
    result = subprocess.run(
        [sys.executable, "-c", f"import runpy; runpy.run_path({str(Path(__file__).resolve())!r}, run_name='__main__')"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "32 preview deliveries and worker teardowns completed" in result.stdout


if __name__ == "__main__":
    _run_worker_delivery_probe()
