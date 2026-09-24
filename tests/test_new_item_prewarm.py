"""Post-startup template loading through the real shell callback and task lane."""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest

from tests import test_new_item_studio_tab as support
from PySide6.QtCore import QEvent, QThread, QTimer, Qt
from PySide6.QtWidgets import QApplication, QTabWidget, QVBoxLayout, QWidget

from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.rust_ui_tab import RustNewItemStudioTab
from cdmw.ui.new_item.tab import NewItemStudioTab
from cdmw.ui.shell.lazy_tool_tab import LazyToolTab
from cdmw.ui.shell.tool_tabs import ShellToolTabsMixin


def _until(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return
        time.sleep(0.001)
    assert predicate(), "New Item worker did not settle"


@pytest.fixture
def unprepared():
    support.TabTests.setUpClass()
    fixture = support.TabTests("runTest")
    fixture.setUp()
    controller = NewItemStudioController(read_entry=support._read)
    workflow = NewItemStudioTab(controller=controller, get_archive_entries=lambda: fixture.entries)
    fixture._tabs.append(workflow)
    # Native rendering and effect indexing are separate contracts; keep the
    # real snapshot, panel construction, and asynchronous task shutdown here.
    with patch.object(RustNewItemStudioTab, "_start_prepare"), \
            patch.object(controller, "start_effect_index"):
        tab = RustNewItemStudioTab(workflow=workflow)
        try:
            yield tab
        finally:
            tab.request_shutdown()
            workflow.setParent(None)
            fixture.tearDown()
            tab.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.mark.parametrize("restored", [False, True])
def test_shell_prepares_template_after_startup_without_blocking_or_switching_tools(unprepared, restored):
    class Shell(QWidget, ShellToolTabsMixin):
        pass

    tab = unprepared
    workflow, controller = tab.workflow, tab.controller
    shell = Shell()
    shell.setAttribute(Qt.WA_DontShowOnScreen)
    layout = QVBoxLayout(shell)
    tabs = QTabWidget()
    layout.addWidget(tabs)
    current = QWidget()
    tabs.addTab(current, "Current")
    lazy = LazyToolTab(lambda: tab)
    tabs.addTab(lazy, "Create New Item")
    if restored:
        tabs.setCurrentWidget(lazy)
    shell.new_item_studio_tab = lazy
    shell._startup_splash_window = object()
    shell._schedule_new_item_rust_prewarm()
    timer = shell.findChild(QTimer)
    entered, release = threading.Event(), threading.Event()
    worker_threads = []
    build = controller.service.build_snapshot

    def delayed_build(*args, **kwargs):
        worker_threads.append(QThread.currentThread())
        entered.set()
        assert release.wait(5), "Test did not release the snapshot worker"
        return build(*args, **kwargs)

    with patch.object(type(controller.service), "build_snapshot", side_effect=delayed_build) as read:
        try:
            timer.timeout.emit()
            assert not lazy._load_requested
            shell.show()
            if restored:
                _until(lambda: lazy.widget_if_created() is tab)
                assert tab.isVisible()
            timer.timeout.emit()
            read.assert_not_called()
            assert controller.snapshot is None
            shell._startup_splash_window = None
            with patch.object(QApplication, "activeModalWidget", return_value=object()):
                timer.timeout.emit()
            read.assert_not_called()

            timer.timeout.emit()
            _until(entered.is_set)
            assert not timer.isActive()
            assert worker_threads == [controller._thread]
            assert worker_threads[0] is not QApplication.instance().thread()
            assert tabs.currentWidget() is (lazy if restored else current)
            assert controller.busy
            beats = []
            QTimer.singleShot(0, lambda: beats.append(True))
            _until(lambda: bool(beats))
            assert not release.is_set()

            # A restored tab is already visible; the other case must finish
            # loading while hidden so its first opening goes straight to Template.
            tab.prewarm()
            assert read.call_count == 1
            release.set()
            _until(lambda: workflow._panels_built and not controller.busy)
            assert tab.isVisible() == restored
            assert workflow._current_step == 0
            assert workflow._panels[0] is workflow.template_panel
            assert support.TEMPLATE in controller.snapshot.rows
            snapshot, draft = controller.snapshot, controller.draft
            tabs.setCurrentWidget(lazy)
            assert workflow._current_step == 0
            tabs.setCurrentWidget(current)
            tabs.setCurrentWidget(lazy)
            tab.prewarm()
            assert read.call_count == 1
            assert controller.snapshot is snapshot
            assert controller.draft is draft
        finally:
            release.set()
            lazy.request_shutdown()
            _until(lambda: not tab.iter_shutdown_workers())
            tab.setParent(None)
            shell.close()
            shell.deleteLater()


@pytest.mark.parametrize("already_loaded", [False, True])
def test_prewarm_reuses_an_inflight_handoff_and_the_loaded_draft(unprepared, already_loaded):
    tab = unprepared
    controller = tab.controller
    tab.prefill_template(support.TEMPLATE)
    assert controller.busy
    if already_loaded:
        _until(lambda: controller.draft.template_key == support.TEMPLATE and not controller.busy)
    with patch.object(tab.workflow, "start_snapshot") as restart:
        tab.prewarm()
        _until(lambda: controller.draft.template_key == support.TEMPLATE and not controller.busy)
        controller.draft.internal_name = "Keep_My_Draft"
        tab.workflow.show_step(1)
        snapshot, draft = controller.snapshot, controller.draft
        tab.prewarm()
        tab.show()
        QApplication.processEvents()
        restart.assert_not_called()
        assert controller.snapshot is snapshot
        assert controller.draft is draft
        assert draft.internal_name == "Keep_My_Draft"
        assert tab.workflow._current_step == 1


def test_failed_background_read_retains_retry_without_restarting_automatically(unprepared):
    tab = unprepared
    workflow, controller = tab.workflow, tab.controller
    errors = []
    tab.status_message_requested.connect(lambda *args: errors.append(args))
    with patch.object(type(controller.service), "build_snapshot", side_effect=ValueError("Owned read failure")) as read:
        tab.prewarm()
        _until(lambda: not controller.busy)
        assert controller.snapshot is None
        assert not workflow._panels_built
        assert "Owned read failure" in workflow._read_failure.report_text
        assert workflow._read_button.isEnabled()
        assert workflow._read_button.text() == "Try again"
        tab.prewarm()
        tab.show()
        QApplication.processEvents()
        assert read.call_count == 1
        assert not errors
    workflow._read_button.click()
    _until(lambda: workflow._panels_built and not controller.busy)
    assert support.TEMPLATE in controller.snapshot.rows


def test_shutdown_cancels_background_read_and_drops_its_late_result(unprepared):
    tab = unprepared
    controller = tab.controller
    # A completed result deliberately delivered after shutdown exercises the
    # existing controller rejection path as well as the new automatic launch.
    snapshot = controller.service.build_snapshot(tab.workflow._get_entries(), read_entry=support._read)
    entered, release = threading.Event(), threading.Event()
    stops = []

    def delayed_result(*args, **kwargs):
        stops.append(kwargs["stop_event"])
        entered.set()
        assert release.wait(5), "Test did not release the snapshot worker"
        return snapshot

    with patch.object(type(controller.service), "build_snapshot", side_effect=delayed_result) as read:
        try:
            tab.prewarm()
            _until(entered.is_set)
            tab.request_shutdown()
            assert stops[0].is_set()
            assert any(lane == "snapshot" for lane, _, _ in tab.iter_shutdown_workers())
            tab.prewarm()
            assert read.call_count == 1
        finally:
            release.set()
            _until(lambda: not tab.iter_shutdown_workers())
        assert controller.snapshot is None
        assert not tab.workflow._panels_built
