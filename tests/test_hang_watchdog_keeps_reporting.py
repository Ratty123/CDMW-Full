"""A wedged interface must keep saying so, and a failed report must not silence it.

Observed on 2026-08-02: the app's UI thread wedged during Modify Original and
stayed wedged for over six minutes against a 45-second threshold. Windows
reported the window hung, the heartbeat file stopped at the moment of the
freeze, and the watchdog thread was alive and cycling the whole time -- and no
`app_hang_detected` report was ever written.

The flag was latched before the write was attempted, so any single failure to
write silenced the watchdog for the rest of the session, and a stall that never
recovered was described once at most however long it ran.
"""

import threading
import time
import unittest

from cdmw.services.diagnostics_service import start_hang_watchdog


class _Clock:
    """Heartbeat age under test control, so no test waits on real time.

    The watchdog measures against `time.time()`, so the reported beat has to be
    anchored to it -- a fixed epoch here makes every age astronomically large
    and every threshold trivially true.
    """

    def __init__(self) -> None:
        self.age = 0.0

    def heartbeat_written_at(self) -> float:
        return time.time() - self.age


def _run_watchdog(ages, *, writer, stale=45.0, recovered=15.0):
    """Drive the watchdog through a fixed sequence of heartbeat ages."""

    clock = _Clock()
    stop = threading.Event()
    steps = iter(ages)
    done = threading.Event()

    def _wait(_interval):
        try:
            clock.age = next(steps)
        except StopIteration:
            done.set()
            return True  # stop_event set -> loop exits
        return False

    stop.wait = _wait  # type: ignore[method-assign]
    thread = start_hang_watchdog(
        stop,
        clock.heartbeat_written_at,
        writer,
        interval_seconds=0.001,
        stale_seconds=stale,
        recovered_seconds=recovered,
        format_thread_dump_fn=lambda: "<dump>",
    )
    thread.join(timeout=5.0)
    return thread


class HangWatchdogTests(unittest.TestCase):
    def test_a_stall_is_reported_once_it_crosses_the_threshold(self) -> None:
        written = []
        _run_watchdog([1.0, 10.0, 50.0], writer=lambda *a, **k: written.append(k.get("context", {})))
        self.assertEqual(len(written), 1)
        self.assertGreaterEqual(written[0]["heartbeat_age_seconds"], 45.0)

    def test_a_stall_that_keeps_growing_is_reported_again(self) -> None:
        """Six minutes of silence should not look the same as forty-six seconds."""

        written = []
        _run_watchdog([50.0, 60.0, 120.0, 400.0], writer=lambda *a, **k: written.append(k.get("context", {})))
        ages = [row["heartbeat_age_seconds"] for row in written]
        self.assertGreaterEqual(len(written), 3, f"a growing stall reported only {ages}")
        self.assertEqual(ages, sorted(ages))

    def test_a_failed_write_does_not_silence_the_watchdog(self) -> None:
        attempts = []

        def _writer(*args, **kwargs):
            attempts.append(kwargs.get("context", {}))
            if len(attempts) == 1:
                raise OSError("crash directory unavailable")
            return None

        _run_watchdog([50.0, 60.0], writer=_writer)
        self.assertGreaterEqual(len(attempts), 2, "the watchdog gave up after one failed write")

    def test_recovery_resets_so_a_later_stall_reports_again(self) -> None:
        written = []
        _run_watchdog([50.0, 1.0, 50.0], writer=lambda *a, **k: written.append(k.get("context", {})))
        self.assertEqual(len(written), 2, "a second stall after recovery went unreported")

    def test_a_healthy_app_is_never_reported(self) -> None:
        written = []
        _run_watchdog([0.5, 1.0, 2.0, 14.0], writer=lambda *a, **k: written.append(k))
        self.assertEqual(written, [])

    def test_the_report_carries_a_thread_dump(self) -> None:
        written = []
        _run_watchdog([50.0], writer=lambda *a, **k: written.append(k.get("context", {})))
        self.assertEqual(written[0]["thread_dump"], "<dump>")


if __name__ == "__main__":
    unittest.main()
