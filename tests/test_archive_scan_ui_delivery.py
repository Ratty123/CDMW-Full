from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QObject, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication

from cdmw.ui.archive_browser.scan_lifecycle import _ArchiveScanUiReceiver


class _Window(QObject):
    def __init__(self, loop: QEventLoop) -> None:
        super().__init__()
        self.loop = loop
        self.completed_thread: QThread | None = None

    def _handle_archive_scan_complete(self, _result: object) -> None:
        self.completed_thread = QThread.currentThread()
        self.loop.quit()


class _Worker(QObject):
    completed = Signal(object)

    @Slot()
    def run(self) -> None:
        self.completed.emit({})


def test_archive_scan_receiver_delivers_completion_on_ui_thread() -> None:
    app = QApplication.instance() or QApplication([])
    loop = QEventLoop()
    window = _Window(loop)
    receiver = _ArchiveScanUiReceiver(window)
    thread = QThread()
    worker = _Worker()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.completed.connect(receiver.handle_completed)
    QTimer.singleShot(2000, loop.quit)

    thread.start()
    loop.exec()
    thread.quit()
    assert thread.wait(2000)

    assert window.completed_thread is app.thread()
