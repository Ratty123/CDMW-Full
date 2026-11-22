"""Placement and Animations: the retained-thread set holds plain QThreads too."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from tools.placement_studio import background


def test_others_busy_reads_a_retained_carry_thread_without_an_owner():
    # window_carry._stop_carry_index retains its plain QThread here until it has
    # stopped, and the viewport asks others_busy() from its paint path meanwhile.
    QApplication.instance() or QApplication([])
    thread = QThread()
    background._retained.add(thread)
    try:
        assert background.others_busy() is False
        assert background.others_busy(excluding="layers") is False
    finally:
        background._retained.discard(thread)


def test_latest_task_reuses_persistent_worker_and_reports_idle_state():
    import threading
    import time
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication([])
    task = background.LatestTask()
    task.setObjectName("reuse_worker")
    gate_started = threading.Event()
    gate_release = threading.Event()
    results = []
    task.ready.connect(lambda res, err: results.append((res, err)))

    def wait_for(predicate, timeout=2.0):
        end = time.monotonic() + timeout
        while not predicate() and time.monotonic() < end:
            loop = QEventLoop()
            QTimer.singleShot(5, loop.quit)
            loop.exec()
        assert predicate()

    try:
        task.submit(lambda c, p: threading.get_ident())
        wait_for(lambda: len(results) == 1 and not task.busy)
        assert background.others_busy() is False

        task.submit(lambda c, p: threading.get_ident())
        wait_for(lambda: len(results) == 2 and not task.busy)
        assert results[0][0] == results[1][0]
        assert background.others_busy() is False

        def blocked(c, p):
            gate_started.set()
            gate_release.wait(2.0)
            return threading.get_ident()

        task.submit(blocked)
        assert gate_started.wait(2.0)
        assert background.others_busy() is True
        assert background.others_busy(excluding="reuse_worker") is False
        gate_release.set()
        wait_for(lambda: len(results) == 3 and not task.busy)
    finally:
        gate_release.set()
        task.shutdown()
        assert task.wait(2000)
        wait_for(lambda: not background._retained)


def test_edit_session_in_place_drag_coalescing_matches_full_replay():
    from tests.test_placement_studio_operations import BODY, _edits
    from tools.placement_studio.editing import EditSession
    from tools.placement_studio.model import Vec3

    edits = _edits()
    socket = edits.socket(BODY, "Pelvis_R_Socket")
    edits.set_translation(BODY, socket.name, Vec3(socket.translation.x + 0.1, socket.translation.y, socket.translation.z))
    edits.set_translation(BODY, socket.name, Vec3(socket.translation.x + 0.25, socket.translation.y - 0.05, socket.translation.z))
    edits.set_rotation_euler(BODY, socket.name, 5.0, 10.0, 15.0)
    edits.set_rotation_euler(BODY, socket.name, 12.0, -4.0, 22.0)

    fresh = EditSession.from_snapshot(edits.capture())
    assert edits.current_files() == fresh.current_files()


def test_key_timeline_coalesces_scrub_and_emits_scrub_state():
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    from tools.placement_studio.key_timeline import KeyTimeline

    app = QApplication.instance() or QApplication([])
    timeline = KeyTimeline()
    timeline.resize(420, 80)
    timeline.set_length(100)
    seeks = []
    states = []
    timeline.seek_requested.connect(seeks.append)
    timeline.scrub_state_changed.connect(states.append)

    def mouse(kind, x):
        pos = QPointF(float(x), 8.0)
        return QMouseEvent(
            kind, pos, pos,
            Qt.LeftButton if kind != QMouseEvent.Type.MouseMove else Qt.NoButton,
            Qt.LeftButton if kind != QMouseEvent.Type.MouseButtonRelease else Qt.NoButton,
            Qt.NoModifier,
        )

    timeline.mousePressEvent(mouse(QMouseEvent.Type.MouseButtonPress, timeline.x_of(10)))
    assert states == [True]
    assert seeks == [10.0]

    x25 = timeline.x_of(25)
    timeline.mouseMoveEvent(mouse(QMouseEvent.Type.MouseMove, x25))
    timeline.mouseMoveEvent(mouse(QMouseEvent.Type.MouseMove, x25))
    timeline.mouseMoveEvent(mouse(QMouseEvent.Type.MouseMove, timeline.x_of(40)))
    assert seeks == [10.0]

    timeline.mouseReleaseEvent(mouse(QMouseEvent.Type.MouseButtonRelease, timeline.x_of(40)))
    app.processEvents()
    assert seeks == [10.0, 40.0]
    assert states == [True, False]
