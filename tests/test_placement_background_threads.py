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
