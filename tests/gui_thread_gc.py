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
import sys
import threading

FULL_COLLECTION_EVERY = 100

_main_thread_ident = threading.main_thread().ident
_tests_since_full_collection = 0


def install() -> None:
    """Turn automatic collection off for the process."""

    gc.disable()


def apply_layout_item_rule(*, sweep: bool = False) -> None:
    """The app's rule for PySide's records of Qt-made layout items, in the test process.

    Qt deletes a widget's layout item when the widget is deleted or moved to another
    parent, and PySide keeps its record of the item under the freed address. The app
    drops such records as widgets leave their parents and sweeps every layout after a
    full collection (`cdmw/ui/layout_item_wrappers.py`, installed at app start). A
    pytest process never runs app start-up, so the records stayed, and the next QThread
    or list item Qt made at such an address took the process down natively: about 1 in
    14 runs of tests/test_texture_editor_tool_audit.py under load, in `QThread(self)` or
    in `QListWidget.clear()`.

    Called before and after every test. It does nothing until a test has made the
    QApplication; from then on the rule is in place, as in the app."""

    widgets = sys.modules.get("PySide6.QtWidgets")
    if widgets is None:
        return
    app = widgets.QApplication.instance()
    if not isinstance(app, widgets.QApplication):  # none yet, or a bare QCoreApplication
        return
    from cdmw.ui.layout_item_wrappers import (
        ensure_app_layout_item_wrapper_release,
        release_all_layout_item_wrappers,
    )

    ensure_app_layout_item_wrapper_release(app)
    if sweep:
        release_all_layout_item_wrappers()


def collect_after_test() -> bool:
    """Free the finished test's cycles on the main thread. True after a full collection."""

    global _tests_since_full_collection
    if threading.get_ident() != _main_thread_ident:
        raise RuntimeError("Test-process garbage collection must run on the main thread")
    _tests_since_full_collection += 1
    if _tests_since_full_collection >= FULL_COLLECTION_EVERY:
        _tests_since_full_collection = 0
        gc.collect()
        return True
    gc.collect(0)
    return False
