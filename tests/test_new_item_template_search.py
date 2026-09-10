"""Template query compatibility and real Qt input/worker lifecycle regressions."""

from __future__ import annotations

import os
import threading
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QThread, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from cdmw.domain.cancellation import RunCancelled  # noqa: E402
from cdmw.services import new_item_template_search as search_service  # noqa: E402
from cdmw.services.new_item_template_search import build_template_search_catalogue, search_template_options  # noqa: E402
from cdmw.ui.new_item.controller import NewItemStudioController  # noqa: E402
from cdmw.ui.new_item.panels_template import TemplatePanel  # noqa: E402
from cdmw.workers import new_item_template_search as search_worker  # noqa: E402


def _snapshot():
    rows = {
        3: SimpleNamespace(string_key="Ziane_OneHandSword", equip_type_key=1, stat_block_offset=0, enchant_levels=(1,)),
        12: SimpleNamespace(string_key="Redrin_Fabric_Helm", equip_type_key=2, stat_block_offset=0, enchant_levels=()),
        2: SimpleNamespace(string_key="Cigar_OneHandSword", equip_type_key=1, stat_block_offset=None, enchant_levels=()),
        20: SimpleNamespace(string_key="No_Equipment", equip_type_key=0),
    }
    display = {3: "Wolf's Fang", 2: "Cigar"}
    localized = {3: ("Wolf's Fang", "Wolfszahn", "سيف الاختبار"), 12: ("Roter Helm",)}
    entry = SimpleNamespace(path="owned-fixture/table", pamt_path="owned-fixture/archive")
    table = SimpleNamespace(descriptor={"layout": "legacy"}, payload_entry=entry)
    snapshot = SimpleNamespace(
        rows=rows, item_groups=(), iteminfo=table, stringinfo=table, storeinfo=table,
        languages=("eng", "ger", "ara"), sources=None,
        item_display_names=lambda: display, item_search_names=lambda: localized,
        equip_type_name=lambda row: {1: "OneHandSword", 2: "Helm"}.get(row.equip_type_key, ""),
    )
    snapshot._template_search_catalogue = build_template_search_catalogue(snapshot)
    snapshot.template_search_catalogue = lambda: snapshot._template_search_catalogue
    return snapshot


@pytest.mark.parametrize("query,expected", [
    ("", [2, 12, 3]),
    ("helmet red", [12]),
    ('"wolf\'s fang" OR cigar', [2, 3]),
    ("sword -cigar", [3]),
    ("Wolfszahn", [3]),
    ("سيف الاختبار", [3]),
    ("name:helm", [12]),
    ("name:*helm", [12]),
    ("name:3", []),
    ("3", [3]),
    ("path:helm", []),
    ('"helm red"', []),
])
def test_prepared_search_preserves_query_semantics(query, expected):
    options = search_template_options(_snapshot().template_search_catalogue(), query, limit=None)
    assert [option[0] for option in options] == expected


def test_catalogue_is_immutable_and_preserves_category_ranking_and_sorting():
    snapshot = _snapshot()
    snapshot.rows[9] = SimpleNamespace(string_key="A_CigarHolder", equip_type_key=1, stat_block_offset=0, enchant_levels=())
    snapshot.item_groups = (
        SimpleNamespace(key=100, name="ItemGroup_Category_Equipment", members=(3,), subgroups=(101,)),
        SimpleNamespace(key=101, name="ItemGroup_SubCategory_Equip_Helm", members=(12,), subgroups=(100,)),
    )
    catalogue = build_template_search_catalogue(snapshot)
    assert search_template_options(catalogue, "cigar", limit=1)[0][0] == 2, "exact names precede internal-name prefixes"
    assert [row[0] for row in search_template_options(catalogue, group_key=100)] == [12, 3]
    assert [row[0] for row in search_template_options(catalogue, sort_column=2, descending=True)] == [12, 9, 3, 2]
    assert [row[0] for row in search_template_options(catalogue, sort_column=4)] == [9, 12, 3, 2]
    snapshot.rows.clear()
    snapshot.item_display_names().clear()
    assert search_template_options(catalogue, "Wolfszahn")[0][2] == "Wolf's Fang"
    with pytest.raises(TypeError):
        catalogue.category_members[100] = frozenset()


def test_search_observes_cancellation_before_and_during_matching(monkeypatch):
    catalogue = _snapshot().template_search_catalogue()
    stop = threading.Event()
    stop.set()
    with pytest.raises(RunCancelled):
        search_template_options(catalogue, "helm", stop_event=stop)
    stop.clear()
    original = search_service.archive_name_search_text_match

    def cancel_during_match(field, term):
        stop.set()
        return original(field, term)

    monkeypatch.setattr(search_service, "archive_name_search_text_match", cancel_during_match)
    with pytest.raises(RunCancelled):
        search_template_options(catalogue, "missing", stop_event=stop)


def _wait(app, predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        time.sleep(0.001)
    assert predicate(), "Qt search work did not settle within the test deadline"


def _keys(panel):
    return [int(panel.matches.topLevelItem(index).text(2)) for index in range(panel.matches.topLevelItemCount())]


@pytest.fixture
def search_ui():
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController()
    controller.snapshot = _snapshot()
    panel = TemplatePanel(controller)
    try:
        _wait(app, lambda: _keys(panel) == [2, 12, 3] and not controller.iter_shutdown_workers())
        yield app, controller, panel
    finally:
        controller.request_shutdown()
        _wait(app, lambda: not controller.iter_shutdown_workers())
        panel.deleteLater()
        controller.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_typing_coalesces_without_blocking_gui_events(search_ui, monkeypatch):
    app, controller, panel = search_ui
    started, release = threading.Event(), threading.Event()
    calls, heartbeat, published_on_gui = [], [], []
    original = search_worker.search_template_options

    def slow_search(catalogue, text, **kwargs):
        calls.append((text, QThread.currentThread() != app.thread()))
        started.set()
        release.wait(3)
        return original(catalogue, text, **kwargs)

    monkeypatch.setattr(search_worker, "search_template_options", slow_search)
    controller.template_search_ready.connect(lambda _rows: published_on_gui.append(QThread.currentThread() == app.thread()))
    try:
        QTest.keyClicks(panel.filter_edit, "helm")
        assert panel.filter_edit.text() == "helm"
        assert not calls, "keystrokes only schedule work; they never run the matcher"
        _wait(app, started.is_set)
        assert calls == [("helm", True)], "four keystrokes become one background search"
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        _wait(app, lambda: bool(heartbeat))
        assert panel.filter_edit.isEnabled()
        assert _keys(panel) == [2, 12, 3], "current results remain usable during the search"
        assert len(controller.iter_shutdown_workers()) == 1
        release.set()
        _wait(app, lambda: _keys(panel) == [12] and not controller.iter_shutdown_workers())
        assert published_on_gui == [True]
    finally:
        release.set()


def test_new_text_cancels_old_work_and_rejects_queued_results(search_ui, monkeypatch):
    app, controller, panel = search_ui
    started, release = threading.Event(), threading.Event()
    calls = []
    original = search_worker.search_template_options

    def slow_first_search(catalogue, text, **kwargs):
        calls.append(text)
        if text == "sword":
            started.set()
            release.wait(3)
        return original(catalogue, text, **kwargs)

    monkeypatch.setattr(search_worker, "search_template_options", slow_first_search)
    try:
        panel.filter_edit.setText("sword")
        _wait(app, started.is_set)
        lane = controller._template_search_lane
        old_thread = lane._thread
        panel.matches.setCurrentItem(panel.matches.topLevelItem(0))
        assert panel._pick_timer.isActive()
        panel.filter_edit.setText("helm missing")
        assert old_thread.stop_event.is_set(), "cancellation happens before the debounce expires"
        assert not panel._pick_timer.isActive()
        assert panel._pending_key is None
        panel.filter_edit.setText("helm")
        lane._completed(old_thread.generation, controller.snapshot.template_search_catalogue(), [])
        assert _keys(panel) == [2, 12, 3], "even an already queued obsolete result cannot replace the rows"
        _wait(app, lambda: not lane._timer.isActive())
        assert calls == ["sword"]
        assert lane._thread is old_thread, "the newer request waits for the one owned worker to exit"
        release.set()
        _wait(app, lambda: _keys(panel) == [12] and not controller.iter_shutdown_workers())
        assert calls == ["sword", "helm"]
    finally:
        release.set()


def test_replacing_snapshot_rejects_results_from_previous_catalogue(search_ui, monkeypatch):
    app, controller, panel = search_ui
    started, release = threading.Event(), threading.Event()
    published = []
    original = search_worker.search_template_options

    def slow_search(catalogue, text, **kwargs):
        started.set()
        release.wait(3)
        return original(catalogue, text, **kwargs)

    monkeypatch.setattr(search_worker, "search_template_options", slow_search)
    controller.template_search_ready.connect(published.append)
    try:
        panel.filter_edit.setText("helm")
        _wait(app, started.is_set)
        controller.snapshot = _snapshot()
        release.set()
        _wait(app, lambda: not controller.iter_shutdown_workers())
        assert published == [], "a changed snapshot invalidates results even before its refresh signal"
        controller.snapshot_ready.emit()
        _wait(app, lambda: _keys(panel) == [12] and not controller.iter_shutdown_workers())
        assert len(published) == 1
    finally:
        release.set()


def test_shutdown_cancels_pending_search_and_retains_running_thread(search_ui, monkeypatch):
    app, controller, panel = search_ui
    started, release = threading.Event(), threading.Event()
    calls, published = [], []
    original = search_worker.search_template_options

    def slow_search(catalogue, text, **kwargs):
        calls.append(text)
        started.set()
        release.wait(3)
        return original(catalogue, text, **kwargs)

    monkeypatch.setattr(search_worker, "search_template_options", slow_search)
    controller.template_search_ready.connect(published.append)
    try:
        panel.filter_edit.setText("sword")
        _wait(app, started.is_set)
        panel.filter_edit.setText("helm")
        thread = controller._template_search_lane._thread
        before = time.monotonic()
        controller.request_shutdown()
        assert time.monotonic() - before < 0.08
        assert thread.stop_event.is_set()
        assert controller.iter_shutdown_workers() == (("template search", thread, thread),)
        controller.request_template_search("cigar")
        release.set()
        _wait(app, lambda: not controller.iter_shutdown_workers())
        assert calls == ["sword"]
        assert published == []
        assert not controller._template_search_lane._timer.isActive()
    finally:
        release.set()


def test_failed_search_keeps_rows_and_allows_next_query(search_ui, monkeypatch):
    app, controller, panel = search_ui
    errors = []
    controller.log_message.connect(errors.append)
    original = search_worker.search_template_options

    def failed_search(catalogue, text, **kwargs):
        if text == "broken":
            raise RuntimeError("owned search failure")
        return original(catalogue, text, **kwargs)

    monkeypatch.setattr(search_worker, "search_template_options", failed_search)
    panel.filter_edit.setText("broken")
    _wait(app, lambda: bool(errors) and not controller.iter_shutdown_workers())
    assert errors == ["owned search failure"]
    assert _keys(panel) == [2, 12, 3]
    panel.filter_edit.setText("helm")
    _wait(app, lambda: _keys(panel) == [12] and not controller.iter_shutdown_workers())
