"""Rapid navigation must leave obsolete presentation work paused and reusable."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

from cdmw.ui.shell.lazy_tool_tab import LazyToolTab


# Keep Qt alive while deferred deletions and worker retirement span test cases.
_APP = QApplication.instance() or QApplication([])


def _wait(app: QApplication, predicate, timeout: float = 3.0) -> None:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.001)
    assert predicate()


def test_rapid_visits_prepare_only_the_tool_that_remains_selected() -> None:
    app = QApplication.instance() or QApplication([])
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "Archive")
    prepared, built = [], []
    lazy_tabs = []
    for name in ("New Item", "Model Library", "Item Icons", "Mesh Editor"):
        def build(name=name):
            built.append(name)
            return QWidget()

        lazy = LazyToolTab(build, prepare=lambda name=name: prepared.append(name))
        lazy_tabs.append(lazy)
        tabs.addTab(lazy, name)
    try:
        tabs.show()
        app.processEvents()
        for lazy in lazy_tabs:
            tabs.setCurrentWidget(lazy)
            app.processEvents()
        _wait(app, lambda: lazy_tabs[-1].widget_if_created() is not None)
        assert prepared == ["Mesh Editor"]
        assert built == ["Mesh Editor"]
        assert all(lazy.widget_if_created() is None for lazy in lazy_tabs[:-1])
    finally:
        for lazy in lazy_tabs:
            lazy.request_shutdown()
        _wait(app, lambda: all(lazy._prepare_thread is None for lazy in lazy_tabs))
        tabs.close()
        tabs.deleteLater()
        app.processEvents()


def test_leaving_during_preload_defers_gui_work_then_resumes_once() -> None:
    app = QApplication.instance() or QApplication([])
    started, release = threading.Event(), threading.Event()
    ui_prepared, built, published = [], [], []

    def prepare():
        started.set()
        release.wait(3)

    def build():
        built.append(QWidget())
        return built[-1]

    lazy = LazyToolTab(build, prepare=prepare, prepare_ui=lambda: ui_prepared.append(True))
    lazy.when_created(published.append)
    try:
        lazy.show()
        _wait(app, started.is_set)
        lazy.hide()
        release.set()
        _wait(app, lambda: lazy._prepare_thread is None)
        app.processEvents()
        assert ui_prepared == built == published == []
        lazy.show()
        _wait(app, lambda: lazy.widget_if_created() is not None)
        lazy.hide()
        lazy.show()
        app.processEvents()
        assert ui_prepared == [True]
        assert published == built and len(built) == 1
    finally:
        release.set()
        lazy.request_shutdown()
        _wait(app, lambda: lazy._prepare_thread is None)
        lazy.close()
        lazy.deleteLater()
        app.processEvents()


def test_explicit_hidden_handoff_can_finish_a_paused_navigation_load() -> None:
    app = QApplication.instance() or QApplication([])
    built = []
    lazy = LazyToolTab(lambda: built.append(QWidget()) or built[-1])
    try:
        lazy.show()
        lazy.hide()
        lazy.request_widget()
        _wait(app, lambda: lazy.widget_if_created() is not None)
        assert len(built) == 1
        assert not lazy.isVisible()
    finally:
        lazy.shutdown()
        lazy.deleteLater()
        app.processEvents()


def test_leaving_after_construction_defers_created_callbacks() -> None:
    app = QApplication.instance() or QApplication([])
    built = QWidget()
    published = []
    lazy = LazyToolTab(lambda: built)
    lazy.when_created(published.append)
    try:
        lazy.show()
        _wait(app, lambda: lazy._pending_widget is built)
        lazy.hide()
        app.processEvents()
        assert lazy.widget_if_created() is None and published == []
        lazy.show()
        _wait(app, lambda: lazy.widget_if_created() is built)
        assert published == [built]
    finally:
        lazy.shutdown()
        lazy.close()
        lazy.deleteLater()
        app.processEvents()


def test_model_library_pauses_rows_and_auto_preview_without_losing_checks(tmp_path: Path) -> None:
    from cdmw.ui.model_library.tab import ModelLibraryTab
    from tests.test_model_library_rows_async import _close_tab

    app = QApplication.instance() or QApplication([])
    tab = ModelLibraryTab(settings=QSettings(str(tmp_path / "model.ini"), QSettings.IniFormat), base_dir=tmp_path)
    tab.auto_preview_checkbox.setChecked(False)
    tab.RESULTS_POPULATION_BATCH_SIZE = 1
    previews = []
    tab.preview_selected_model_here = lambda: previews.append(True)
    try:
        tab.show()
        app.processEvents()
        rows = [{"kind": "local", "name": name, "path": f"{name}.obj", "extension": ".obj"}
                for name in ("Alpha", "Beta", "Gamma")]
        tab._begin_results_population(rows, len(rows), tab._results_request_id)
        first = tab.results_tree.topLevelItem(0)
        tab.results_tree.setCurrentItem(first)
        first.setCheckState(0, Qt.Checked)
        tab._payload_can_preview_here = lambda _payload: True
        tab.auto_preview_checkbox.setChecked(True)
        tab._schedule_auto_inline_preview()
        tab.hide()
        for _ in range(3):
            app.processEvents()
            tab._flush_results_population_batch()
        tab._preview_current_model_if_auto_enabled()
        assert tab.results_tree.topLevelItemCount() == 1
        assert previews == []
        tab.show()
        _wait(app, lambda: not tab._populating_results)
        assert tab.results_tree.topLevelItemCount() == 3
        assert tab.results_tree.topLevelItem(0).checkState(0) == Qt.Checked
    finally:
        _close_tab(app, tab)


def test_item_icons_pauses_rows_and_coalesces_preview_until_return(tmp_path: Path) -> None:
    from PIL import Image
    from tests.test_item_icon_workers import _finish_tab, _make_tab, _record

    app = QApplication.instance() or QApplication([])
    tab = _make_tab(tmp_path)
    tab.RECORD_POPULATION_BATCH_SIZE = 1
    previews = []
    tab.update_source_preview = lambda: previews.append("source")
    tab.update_final_preview = lambda: previews.append("final")
    try:
        _wait(app, lambda: tab._index_thread is None)
        tab.show()
        app.processEvents()
        records = []
        for name in ("a.png", "b.png", "c.png"):
            path = tmp_path / name
            Image.new("RGBA", (2, 2), "white").save(path)
            records.append(_record(path))
        tab.records = records
        tab._records_by_key = {tab._path_key(record.path): record for record in records}
        tab._populate_records_tree(select_path=records[-1].path)
        tab._schedule_selected_record_previews()
        tab.hide()
        for _ in range(3):
            app.processEvents()
            tab._flush_record_population_batch()
        tab._refresh_selected_record_previews()
        assert tab.records_tree.topLevelItemCount() == 1
        assert previews == []
        tab.show()
        _wait(app, lambda: not tab._record_population_pending and len(previews) == 2)
        assert tab.records_tree.topLevelItemCount() == 3
        assert tab.current_source_path() == records[-1].path
        assert previews == ["source", "final"]
    finally:
        _finish_tab(tab)
