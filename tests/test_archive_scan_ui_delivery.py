import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import threading
from PySide6.QtCore import QObject, QThread, QThreadPool, Qt, Slot
from PySide6.QtWidgets import QApplication
from cdmw.workers.game_executable_fingerprint import GameExecutableFingerprintTask
from tools.dotnet_archive_backend.probe_full_archive_backend import _Awaiter

_APP = QApplication.instance() or QApplication([])


def test_current_opening_game_evidence_is_delivered_on_the_ui_thread(tmp_path):
    executable = tmp_path / "CrimsonDesert.exe"
    executable.write_bytes(b"owned synthetic executable")
    events = []
    class Receiver(QObject):
        @Slot(int, object)
        def completed(self, generation, result):
            events.append((QThread.currentThread(), generation, result))
    receiver = Receiver()
    pool = QThreadPool()
    task = GameExecutableFingerprintTask(3, tmp_path, {}, threading.Event())
    task.signals.completed.connect(receiver.completed, Qt.QueuedConnection)
    pool.start(task)
    assert _Awaiter._wait_until(lambda: bool(events), timeout_ms=1000)
    assert pool.waitForDone(1000)
    assert events[0][0] == _APP.thread() and events[0][1] == 3
    assert events[0][2][0][str(executable).lower()]["sha256"]
    assert executable.read_bytes() == b"owned synthetic executable"


def test_cancelled_game_evidence_task_does_not_publish(tmp_path):
    (tmp_path / "CrimsonDesert.exe").write_bytes(b"owned input")
    stop = threading.Event()
    stop.set()
    events = []
    task = GameExecutableFingerprintTask(1, tmp_path, {}, stop)
    task.signals.completed.connect(lambda *result: events.append(result))
    task.run()
    assert not events
