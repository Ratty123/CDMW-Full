"""Waiting for the shell's utility worker: a closing window starts no new task."""

from __future__ import annotations

import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from cdmw.ui.archive_browser.shell_idle import run_task_when_shell_idle


def _shell(**state):
    started = []
    defaults = {"worker_thread": None, "_shutting_down": False, "_background_task_active": lambda: False,
                "_run_utility_task": lambda **task: started.append(task)}
    shell = SimpleNamespace(**{**defaults, **state})
    return shell, started


def _pump(seconds: float) -> None:
    application = QApplication.instance()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.01)


def test_a_wait_that_ends_in_shutdown_starts_nothing() -> None:
    QApplication.instance() or QApplication([])
    owner = QWidget()
    shell, started = _shell(worker_thread=object())
    errors = []
    run_task_when_shell_idle(shell, owner, status_message="Reading", on_error=errors.append, task=lambda: None)
    shell._shutting_down = True
    shell.worker_thread = None  # the previous task ended as the window began to close
    _pump(0.5)
    assert started == [] and errors == []


def test_no_task_starts_once_the_window_is_closing() -> None:
    QApplication.instance() or QApplication([])
    owner = QWidget()
    shell, started = _shell(_shutting_down=True)
    run_task_when_shell_idle(shell, owner, status_message="Reading", on_error=lambda _message: None,
                             task=lambda: None)
    assert started == []
    shell._shutting_down = False
    run_task_when_shell_idle(shell, owner, status_message="Reading", on_error=lambda _message: None,
                             task=lambda: None)
    assert len(started) == 1
