"""Start a worker task for a page that shows its own progress, once the shell is free.

The shell runs one utility task at a time. Its own wait (`_run_utility_task_when_idle`)
gives up after five seconds, and a task it refuses because Text Search or a texture
export is running reports nothing back. That suits a button the user can press again; a
page that shows a progress bar until its task answers would be left waiting forever.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QTimer
from shiboken6 import isValid

BUSY_MESSAGE = "Another background task is running. Try again when it has finished."
_POLL_MS = 150


def run_task_when_shell_idle(shell, owner, *, status_message: str, on_error: Callable[[str], None],
                             on_waiting: Callable[[], None] | None = None,
                             on_start: Callable[[], None] | None = None, _told: bool = False, **task) -> None:
    """Run ``task`` on the shell's utility worker as soon as no other task runs.

    Waits for as long as ``owner`` (the page's widget) lives, so a first prefab search of
    several minutes does not make a table read fail. ``on_waiting`` is called once when
    the task has to wait and ``on_start`` just before it starts. Every outcome reaches
    ``on_complete`` or ``on_error``.

    ``status_message`` is named here and handed on below (not in a nested function), so the
    translation catalogue finds the text callers pass, as it does for `_run_utility_task`.
    """

    if not isValid(owner):
        return
    if getattr(shell, "worker_thread", None) is not None:
        if not _told and on_waiting is not None:
            on_waiting()
        QTimer.singleShot(_POLL_MS, lambda: run_task_when_shell_idle(
            shell, owner, status_message=status_message, on_error=on_error, on_waiting=on_waiting,
            on_start=on_start, _told=True, **task))
        return
    busy = getattr(shell, "_background_task_active", None)
    if callable(busy) and busy():
        # Text Search or a texture export: the shell would drop the task without a word.
        on_error(BUSY_MESSAGE)
        return
    if on_start is not None:
        on_start()
    shell._run_utility_task(status_message=status_message, on_error=on_error, **task)


__all__ = ["BUSY_MESSAGE", "run_task_when_shell_idle"]
