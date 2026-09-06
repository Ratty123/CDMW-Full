"""Real Qt delivery and native thread lifetime, including cancelled old results."""
import os
import threading
import time

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from tools.placement_studio.background import LatestTask, _retained

_app = QApplication.instance() or QApplication([])


def until(predicate, timeout=3000):
    end = time.monotonic() + timeout / 1000
    while not predicate() and time.monotonic() < end:
        loop = QEventLoop()
        QTimer.singleShot(5, loop.quit)
        loop.exec()
    assert predicate(), 'Timed out waiting for Qt delivery'


def test_latest_request_supersedes_pending_and_rejects_old_result():
    task = LatestTask()
    started = threading.Event()
    release = threading.Event()
    results, ran = [], []
    task.ready.connect(lambda result,error: results.append((result,error)))
    def old(cancelled, progress):
        started.set()
        release.wait(2)
        progress(1,1)
        return 'obsolete'
    task.submit(old)
    until(started.is_set)
    task.submit(lambda *_: ran.append('discarded'))
    task.submit(lambda *_: 'newest')
    release.set()
    until(lambda: not task.busy)
    assert results == [('newest','')]
    assert ran == []
    task.shutdown()
    until(lambda: not _retained)


def test_close_does_not_wait_or_deliver_into_reopened_owner():
    owner = QWidget()
    task = LatestTask(owner)
    started, release = threading.Event(), threading.Event()
    results = []
    task.ready.connect(lambda *args: results.append(args))
    def work(*_):
        started.set(); release.wait(2); return 'late'
    task.submit(work)
    until(started.is_set)
    before = time.monotonic()
    task.shutdown()
    owner.deleteLater()
    assert time.monotonic() - before < .1
    replacement = LatestTask()
    replacement.ready.connect(lambda value,error: results.append((value,error)))
    replacement.submit(lambda *_: 'reopened')
    release.set()
    until(lambda: not _retained)
    assert results == [('reopened','')]
    replacement.shutdown()
