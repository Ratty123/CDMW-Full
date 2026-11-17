"""The window thread's collector keeps full collections for idle moments.

On Python 3.14.3 the collector's `collect(1)` did nothing most seconds and now
and then walked the whole heap: 4.8 s on the window thread in the review, with
the Mesh Editor open and 2.3 GiB in use. The young generation is collected
every second; a full collection waits until nobody has used the keyboard or
mouse for a few seconds, or until one has not run for a long time.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.ui.shell import garbage_collection


class _FakeGc:
    def __init__(self, young_count: int = 5000) -> None:
        self.calls: list[object] = []
        self.young_count = young_count

    def get_count(self):
        return (self.young_count, 20, 20)

    def get_threshold(self):
        return (2000, 10, 10)

    def collect(self, *generation):
        self.calls.append(generation[0] if generation else "full")
        return 0

    def isenabled(self):
        return False

    def enable(self):
        pass

    def disable(self):
        pass


@pytest.fixture
def collector(monkeypatch):
    app = QApplication.instance() or QApplication([])
    fake = _FakeGc()
    monkeypatch.setattr(garbage_collection, "gc", fake)
    state = SimpleNamespace(now=0.0, idle=0.0)
    try:
        result = garbage_collection.GuiGarbageCollector(
            app, input_idle_seconds=lambda: state.idle, clock=lambda: state.now,
        )
    except TypeError:  # a collector without an idle rule
        result = garbage_collection.GuiGarbageCollector(app)
    result._timer.stop()
    yield result, fake, state
    result.deleteLater()


def _seconds(collector, state, count):
    for _ in range(count):
        state.now += 1.0
        collector._collect()


def test_while_the_user_works_only_the_young_generation_is_collected(collector):
    gui, fake, state = collector

    _seconds(gui, state, int(getattr(garbage_collection, "FULL_COLLECTION_MAX_INTERVAL_S", 300.0)) - 1)

    assert fake.calls and "full" not in fake.calls and 2 not in fake.calls
    if garbage_collection._INCREMENTAL_GC:
        # collect(1) is the call that walked the whole heap now and then.
        assert set(fake.calls) == {0}


def test_an_idle_window_gets_its_full_collection(collector):
    gui, fake, state = collector
    _seconds(gui, state, int(getattr(garbage_collection, "FULL_COLLECTION_MIN_INTERVAL_S", 60.0)))
    assert "full" not in fake.calls

    state.idle = getattr(garbage_collection, "FULL_COLLECTION_IDLE_S", 5.0) + 1
    _seconds(gui, state, 1)

    assert fake.calls[-1] == "full"
    # Not again straight away, idle or not.
    _seconds(gui, state, 5)
    assert fake.calls.count("full") == 1


def test_a_full_collection_runs_after_the_longest_interval_even_while_busy(collector):
    gui, fake, state = collector

    _seconds(gui, state, int(getattr(garbage_collection, "FULL_COLLECTION_MAX_INTERVAL_S", 300.0)) + 1)

    assert fake.calls.count("full") == 1


def test_nothing_allocated_means_no_full_collection(collector):
    gui, fake, state = collector
    fake.young_count = 10
    state.idle = 3600.0

    _seconds(gui, state, int(getattr(garbage_collection, "FULL_COLLECTION_MAX_INTERVAL_S", 300.0)) * 2)

    assert fake.calls == []


def test_the_full_collection_also_drops_wrappers_of_layout_items_qt_deleted(collector, monkeypatch):
    from cdmw.ui import layout_item_wrappers

    gui, fake, state = collector
    sweeps = []
    monkeypatch.setattr(layout_item_wrappers, "release_all_layout_item_wrappers", lambda: sweeps.append(state.now) or 0)

    _seconds(gui, state, int(getattr(garbage_collection, "FULL_COLLECTION_MAX_INTERVAL_S", 300.0)) + 1)

    assert fake.calls.count("full") == 1
    assert len(sweeps) == 1  # with the full collection only, never every second
