"""The app's garbage-collection rule, applied to the test process.

The app turns automatic cyclic collection off and collects from a timer on the
GUI thread (`cdmw/ui/shell/garbage_collection.py`), so a reference cycle that
holds a Qt object is only ever freed between events on that thread. A pytest
process never runs app start-up, so without this module collection stays
automatic: it starts inside whatever allocates next, on whichever thread that is.

That killed long runs natively. `QApplication.setStyleSheet` re-polishes a copy
of the list of every widget in the process and calls Python event overrides
while it walks it; a collection started inside one of those calls freed windows
an earlier test had left in a cycle, and the walk then touched the freed
widgets (an access violation, or heap corruption 0xC0000374 found later).
Worker threads could do the same while the GUI thread had released the GIL.

Here automatic collection is off for the whole session, and each test's
teardown collects on the main thread, outside any Qt call: the young
generation after every test (everything the test made and left in a cycle is
young, since nothing collects while it runs), and everything every
`FULL_COLLECTION_EVERY` tests, for cycles that were still alive at an earlier
teardown. The young collection, not the app's `collect(1)`, is used because on
Python 3.14.0-3.14.4 `collect(1)` only scans an increment sized by recent
allocation, so it may leave a finished test's windows for a later test.
"""

from __future__ import annotations

import gc
import threading

FULL_COLLECTION_EVERY = 100

_main_thread_ident = threading.main_thread().ident
_tests_since_full_collection = 0


def install() -> None:
    """Turn automatic collection off for the process."""

    gc.disable()


def collect_after_test() -> None:
    """Free the finished test's cycles on the main thread."""

    global _tests_since_full_collection
    if threading.get_ident() != _main_thread_ident:
        raise RuntimeError("Test-process garbage collection must run on the main thread")
    _tests_since_full_collection += 1
    if _tests_since_full_collection >= FULL_COLLECTION_EVERY:
        _tests_since_full_collection = 0
        gc.collect()
    else:
        gc.collect(0)
