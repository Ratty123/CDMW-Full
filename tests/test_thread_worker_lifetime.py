"""A QThread's worker is deleted on the GUI thread once its thread ended, never twice.

B pass 13 crashed twice (access violation, current thread an unnamed [QThread]
with no Python frame) when Finish ran in the Mesh Editor while the texture
sharing search still ran its per-batch scan threads. Each batch's worker was
deleted on its own thread by ``worker.deleteLater`` while the GUI thread dropped
the controller's last Python reference to it, which PySide turns into a second
delete of the same object on the GUI thread. A busy Python thread (Finish)
widens the window. ``release_worker_after_thread`` holds the worker until the
thread ended and lets it go on the GUI thread.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QObject, QThread, Qt, Signal, Slot
from shiboken6 import isValid

ROOT = Path(__file__).resolve().parents[1]

# The search controller's own batch threads, driven as the sharing search drives them,
# with a busy Python thread standing in for Finish.
_SEARCH_BATCHES = r'''
import faulthandler, os, sys, threading
os.environ["QT_QPA_PLATFORM"] = "offscreen"
faulthandler.enable(all_threads=True)
faulthandler.dump_traceback_later(100, exit=True)
from PySide6.QtCore import QCoreApplication, QTimer
from cdmw.core.archive_reverse_references import ReferenceScanBatch
from cdmw.models import ArchiveEntry
from cdmw.services import archive_reference_search as search
from cdmw.workers import archive_reference_workers as workers

workers.scan_reference_batch = lambda target, entries, stop_event: ReferenceScanBatch(scanned=len(entries))
app = QCoreApplication([])
busy = True
def finish_stand_in():
    while busy:
        sum(index * index for index in range(2000))
threading.Thread(target=finish_stand_in, daemon=True).start()

entry = ArchiveEntry.__new__(ArchiveEntry)
controller = search.ArchiveReferenceSearchController()
controller._active = True
controller.state = search.ReferenceSearchState(0, None, "")
batches = int(sys.argv[1])
count = [0]
def advance():
    count[0] += 1
    if count[0] >= batches:
        controller._active = False
        QTimer.singleShot(200, app.quit)
        return
    controller._run((entry,))
controller._advance = advance
QTimer.singleShot(0, lambda: controller._run((entry,)))
app.exec()
busy = False
print("done", count[0], flush=True)
'''


def test_search_batch_threads_survive_the_gui_dropping_their_workers():
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    completed = subprocess.run([sys.executable, "-c", _SEARCH_BATCHES, "200"], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=150)
    # Before the fix this died within a second (access violation on a [QThread] with no
    # Python frame, or a heap corruption) or deadlocked.
    assert completed.returncode == 0, (completed.returncode, completed.stdout[-2000:], completed.stderr[-4000:])
    assert "done 200" in completed.stdout


@pytest.fixture
def app():
    # A full QApplication, not a QCoreApplication: a later test module asks for
    # QApplication.instance() and builds widgets on it, which Qt refuses (and aborts)
    # on a core application.
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _Worker(QObject):
    finished = Signal()

    def __init__(self, hold: threading.Event) -> None:
        super().__init__()
        self.hold = hold

    @Slot()
    def run(self) -> None:
        self.finished.emit()
        self.hold.wait(10)  # the thread is still running after its worker said it is done


class _Receiver(QObject):
    """Lives on the GUI thread, so a queued signal to it is delivered there."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    @Slot()
    def note(self) -> None:
        self.calls += 1


def _wait_until(app, condition, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    return condition()


def test_worker_outlives_the_owner_until_its_thread_ended_then_goes_on_the_gui_thread(app):
    from cdmw.workers.thread_lifetime import held_worker_count, release_worker_after_thread

    hold = threading.Event()
    destroyed_on = []
    thread = QThread()
    worker = _Worker(hold)
    child = QObject(worker)  # tells, from here, whether the worker's C++ side still exists
    worker.moveToThread(thread)
    worker.destroyed.connect(lambda *_: destroyed_on.append(threading.get_ident()), Qt.DirectConnection)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    release_worker_after_thread(thread, worker)
    receiver = _Receiver()
    worker.finished.connect(receiver.note, Qt.QueuedConnection)
    thread.start()
    worker = None  # the owner lets go, as a finished slot does
    assert _wait_until(app, lambda: receiver.calls)
    time.sleep(0.05)
    app.processEvents()
    assert isValid(child), "the worker was deleted while its thread still ran"
    assert held_worker_count() >= 1
    hold.set()
    assert thread.wait(10000)
    assert _wait_until(app, lambda: not isValid(child))
    assert destroyed_on == [threading.get_ident()]


def test_no_thread_worker_is_deleted_on_its_own_thread():
    # Any signal (finished, completed, error...) connected to a worker's deleteLater, with
    # or without a connection type. The helper's own fallback is the one exception.
    pattern = re.compile(r"\.\w+\.connect\(\s*(\w+(?:\.\w+)?)\.deleteLater\b")
    found = []
    for path in sorted((ROOT / "cdmw").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "moveToThread" not in text or path.name == "thread_lifetime.py":
            continue
        for number, line in enumerate(text.splitlines(), 1):
            match = pattern.search(line)
            if match and "thread" not in match.group(1).casefold():
                found.append(f"{path.relative_to(ROOT).as_posix()}:{number}: {line.strip()}")
    assert found == [], "use release_worker_after_thread(thread, worker) instead:\n" + "\n".join(found)
