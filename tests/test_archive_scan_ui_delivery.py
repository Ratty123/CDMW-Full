from __future__ import annotations

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid as qt_wrapper_is_valid

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


class _FinishWindow(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.archive_scan_ui_receiver: object | None = None
        self.cleanup_joined: list[bool] = []

    def _cleanup_worker_refs(self, owner_thread: QThread) -> None:
        self.cleanup_joined.append(owner_thread.wait(0))


def test_archive_scan_receiver_delivers_completion_on_ui_thread() -> None:
    app = QApplication.instance() or QApplication([])
    loop = QEventLoop()
    window = _Window(loop)
    thread = QThread()
    receiver = _ArchiveScanUiReceiver(window, thread)
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


def test_archive_scan_receiver_retains_thread_through_finished_signal_native_tail() -> None:
    QApplication.instance() or QApplication([])
    loop = QEventLoop()
    window = _FinishWindow()
    thread = QThread()
    receiver = _ArchiveScanUiReceiver(window, thread)
    window.archive_scan_ui_receiver = receiver
    finished_signal_blocked = threading.Event()
    release_finished_signal = threading.Event()
    blocked_state: list[tuple[bool, bool, bool, int]] = []

    def block_finished_signal() -> None:
        finished_signal_blocked.set()
        release_finished_signal.wait(2.0)

    def inspect_native_tail() -> None:
        if not finished_signal_blocked.is_set():
            QTimer.singleShot(1, inspect_native_tail)
            return
        blocked_state.append(
            (thread.isRunning(), thread.isFinished(), thread.wait(0), len(window.cleanup_joined))
        )
        release_finished_signal.set()

    thread.started.connect(thread.quit, Qt.ConnectionType.DirectConnection)
    thread.finished.connect(receiver.handle_thread_finished, Qt.ConnectionType.QueuedConnection)
    thread.finished.connect(block_finished_signal, Qt.ConnectionType.DirectConnection)
    receiver.destroyed.connect(loop.quit)
    QTimer.singleShot(0, inspect_native_tail)
    QTimer.singleShot(2000, release_finished_signal.set)
    QTimer.singleShot(2500, loop.quit)

    thread.start()
    loop.exec()
    release_finished_signal.set()
    if qt_wrapper_is_valid(thread) and not thread.wait(0):
        assert thread.wait(2000)

    assert blocked_state == [(False, True, False, 0)]
    assert window.cleanup_joined == [True]
    assert window.archive_scan_ui_receiver is None
