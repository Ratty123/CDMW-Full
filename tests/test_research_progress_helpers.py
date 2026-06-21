from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QProgressBar

from cdmw.ui.research.progress_helpers import (
    set_progress_error,
    set_progress_idle,
    set_progress_ready,
    set_research_progress,
)


_APP = QApplication.instance() or QApplication([])


def test_set_research_progress_clamps_and_formats_determinate_progress() -> None:
    progress = QProgressBar()

    safe_current = set_research_progress(progress, 15, 10)

    assert safe_current == 10
    assert progress.minimum() == 0
    assert progress.maximum() == 10
    assert progress.value() == 10
    assert progress.format() == "10 / 10"


def test_set_research_progress_marks_indeterminate_work() -> None:
    progress = QProgressBar()

    safe_current = set_research_progress(progress, 1, 0)

    assert safe_current == 0
    assert progress.minimum() == 0
    assert progress.maximum() == 0
    assert progress.format() == "Working..."


def test_progress_error_and_ready_helpers_set_terminal_states() -> None:
    progress = QProgressBar()

    set_progress_error(progress)
    assert progress.minimum() == 0
    assert progress.maximum() == 1
    assert progress.value() == 0
    assert progress.format() == "Error"

    set_progress_ready(progress)
    assert progress.minimum() == 0
    assert progress.maximum() == 1
    assert progress.value() == 1
    assert progress.format() == "Ready"

    set_progress_idle(progress)
    assert progress.minimum() == 0
    assert progress.maximum() == 1
    assert progress.value() == 0
    assert progress.format() == "Idle"
