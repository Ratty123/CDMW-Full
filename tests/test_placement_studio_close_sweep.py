"""Placement Studio's threads must be reachable by the shell's close sweep.

The shell discovers running threads through `findChildren`, so it hid the window and
waited -- but `placement_studio_tab` was not in `WORKER_TAB_NAMES` and the tab exposed
neither `iter_shutdown_workers` nor `request_shutdown`, so nothing could name those
threads, ask them to stop, or force-stop them. Closing during a baseline extraction,
carry measurement or armour index left the app alive but hidden until the operation
finished on its own.

The methods are called against a stand-in rather than a constructed tab. Building a
real `PlacementStudioTab` builds its studio window, which starts an armour thread that
nothing stops, and the process then aborts at exit with "QThread: Destroyed while
thread is still running" -- taking the whole pytest run with it. That abort is
pre-existing and reproduces on an unmodified tree; it is exactly the thread this change
makes visible to the sweep.
"""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cdmw.ui.shell.close_controller import (
    WORKER_TAB_NAMES,
    iter_tab_shutdown_workers,
    request_tab_shutdowns,
)
from tools.placement_studio.tab import PlacementStudioTab


class _FakeThread:
    def __init__(self) -> None:
        self.interrupted = False
        self.quit_calls = 0

    def requestInterruption(self) -> None:  # noqa: N802 - Qt spelling
        self.interrupted = True

    def quit(self) -> None:
        self.quit_calls += 1


def _tab_stub(**threads: object) -> SimpleNamespace:
    """A stand-in carrying only the attributes the two methods read."""

    stub = SimpleNamespace(
        _thread=threads.get("baseline"),
        _worker=None,
        _studio=(
            SimpleNamespace(
                _armour_thread=threads.get("armour"),
                _swap_thread=threads.get("swap"),
                _carry_thread=threads.get("carry"),
            )
            if any(key != "baseline" for key in threads)
            else None
        ),
    )
    stub.iter_shutdown_workers = lambda: PlacementStudioTab.iter_shutdown_workers(stub)
    stub.request_shutdown = lambda: PlacementStudioTab.request_shutdown(stub)
    return stub


class PlacementStudioCloseSweepTests(unittest.TestCase):
    def test_the_tab_is_registered_with_the_shell_close_sweep(self) -> None:
        self.assertIn("placement_studio_tab", WORKER_TAB_NAMES)

    def test_every_studio_thread_is_named_for_the_sweep(self) -> None:
        baseline, armour, carry = _FakeThread(), _FakeThread(), _FakeThread()
        stub = _tab_stub(baseline=baseline, armour=armour, carry=carry)

        named = {name: thread for name, thread, _worker in stub.iter_shutdown_workers()}

        self.assertEqual({"baseline", "armour_thread", "carry_thread"}, set(named))
        self.assertIs(baseline, named["baseline"])
        self.assertIs(carry, named["carry_thread"])

        owner = SimpleNamespace(placement_studio_tab=stub)
        self.assertEqual(
            {
                "placement_studio_tab.baseline",
                "placement_studio_tab.armour_thread",
                "placement_studio_tab.carry_thread",
            },
            {name for name, _thread, _worker in iter_tab_shutdown_workers(owner)},
        )

    def test_request_shutdown_asks_every_thread_without_waiting(self) -> None:
        baseline, armour, carry = _FakeThread(), _FakeThread(), _FakeThread()
        stub = _tab_stub(baseline=baseline, armour=armour, carry=carry)

        request_tab_shutdowns(SimpleNamespace(placement_studio_tab=stub))

        for label, thread in (("baseline", baseline), ("armour", armour), ("carry", carry)):
            self.assertTrue(thread.interrupted, label)
            self.assertEqual(1, thread.quit_calls, label)

    def test_a_studio_that_was_never_prepared_reports_no_threads(self) -> None:
        stub = _tab_stub()

        self.assertEqual((), stub.iter_shutdown_workers())
        stub.request_shutdown()

    def test_a_thread_slot_that_is_empty_is_left_out(self) -> None:
        armour = _FakeThread()
        stub = _tab_stub(armour=armour)

        named = {name for name, _thread, _worker in stub.iter_shutdown_workers()}

        self.assertEqual({"armour_thread"}, named)


if __name__ == "__main__":
    unittest.main()
