"""Destruction-only worker ownership for standalone Mesh Editor tab hosts."""

from __future__ import annotations

import time

from PySide6.QtCore import QThread


_DESTROYED_WORKER_DRAIN_SECONDS = 1.0


def install_mesh_editor_destroyed_worker_guard(tab: object) -> None:
    def guard(*_args: object) -> None:
        _stop_destroyed_mesh_editor_workers(tab)

    tab._mesh_editor_destroyed_worker_guard = guard
    tab.destroyed.connect(guard)


def _stop_destroyed_mesh_editor_workers(tab: object) -> None:
    iterator = getattr(tab, "iter_shutdown_workers", None)
    if not callable(iterator):
        return
    workers = tuple(iterator())
    for _name, _thread, worker in workers:
        stop = getattr(worker, "stop", None)
        if callable(stop):
            try:
                stop()
            except RuntimeError:
                pass
    threads: list[QThread] = []
    for _name, thread, _worker in workers:
        if thread is None:
            continue
        try:
            thread.requestInterruption()
            thread.quit()
            if isinstance(thread, QThread):
                threads.append(thread)
        except RuntimeError:
            pass
    deadline = time.monotonic() + _DESTROYED_WORKER_DRAIN_SECONDS
    current = QThread.currentThread()
    for thread in threads:
        try:
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            if thread is not current and thread.isRunning() and remaining_ms > 0:
                thread.wait(remaining_ms)
            if thread.isRunning():
                thread.setParent(None)
        except RuntimeError:
            pass


__all__ = ["install_mesh_editor_destroyed_worker_guard"]
