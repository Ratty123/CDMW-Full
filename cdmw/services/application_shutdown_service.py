"""Bound application exit without interrupting archive commit or recovery."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
import os
import threading
import time

from cdmw.domain.cancellation import RunCancelled
from cdmw.services.process_job_service import app_lifetime_job_is_bound


APPLICATION_SHUTDOWN_GRACE_SECONDS = 15.0
_condition = threading.Condition()
_archive_write_depth = threading.local()
_active_archive_writes = 0
_shutdown_started_at: float | None = None


@contextmanager
def archive_write_scope() -> Iterator[None]:
    """Retain a complete archive transaction, including nested rollback calls.

    Once shutdown begins, new transactions are refused. An already admitted
    transaction may still call the backup/restore service to finish safely.
    """

    global _active_archive_writes
    with _condition:
        depth = getattr(_archive_write_depth, "value", 0)
        if _shutdown_started_at is not None and depth == 0:
            raise RunCancelled("Archive write cancelled because CDMW is closing.")
        _archive_write_depth.value = depth + 1
        _active_archive_writes += 1
    try:
        yield
    finally:
        with _condition:
            _archive_write_depth.value = depth
            _active_archive_writes -= 1
            _condition.notify_all()


def archive_write_in_progress() -> bool:
    with _condition:
        return _active_archive_writes != 0


def _finish_shutdown_after_grace() -> None:
    with _condition:
        assert _shutdown_started_at is not None
        deadline = _shutdown_started_at + APPLICATION_SHUTDOWN_GRACE_SECONDS
        while True:
            remaining = deadline - time.monotonic()
            if remaining > 0:
                _condition.wait(remaining)
            elif _active_archive_writes:
                _condition.wait()
            else:
                # Do not run Qt destructors or atexit handlers against a stuck
                # worker. Process exit closes our job handle, so Windows also
                # terminates every owned helper and descendant. Keeping this
                # separate from Qt covers a blocked event loop and Python's
                # final wait for ThreadPoolExecutor threads as well.
                os._exit(1)


def begin_application_shutdown() -> None:
    """Arm one final exit deadline for a bootstrapped, contained application.

    Keep the watchdog alive through interpreter shutdown. Standalone widgets
    and test hosts that did not enter CDMW bootstrap do not own the process.
    """

    global _shutdown_started_at
    if not app_lifetime_job_is_bound():
        return
    with _condition:
        if _shutdown_started_at is not None:
            return
        _shutdown_started_at = time.monotonic()
        try:
            threading.Thread(
                target=_finish_shutdown_after_grace,
                name="CDMWShutdownWatchdog",
                daemon=True,
            ).start()
        except RuntimeError:
            _shutdown_started_at = None
            raise
