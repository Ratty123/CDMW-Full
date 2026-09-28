"""Post-startup template loading through the real shell callback and task lane."""

from __future__ import annotations

import threading
import time
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests import test_new_item_studio_tab as support
from PySide6.QtCore import QEvent, QThread, QTimer, Qt
from PySide6.QtWidgets import QApplication, QTabWidget, QVBoxLayout, QWidget

from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
from cdmw.ui.new_item.rust_ui_tab import RustNewItemStudioTab
from cdmw.ui.new_item.tab import NewItemStudioTab
from cdmw.ui.shell.lazy_tool_tab import LazyToolTab
from cdmw.ui.shell.tool_tabs import ShellToolTabsMixin
from cdmw.ui.shell.close_controller import (
    iter_transient_shutdown_workers, request_tab_shutdowns, request_transient_shutdowns,
)
from cdmw.workers.new_item_preview_warmup import NewItemPreviewWarmup


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


@pytest.fixture
def preload_shell():
    class Shell(QWidget, ShellToolTabsMixin):
        pass

    support.TabTests.setUpClass()
    fixture = support.TabTests("runTest")
    fixture.setUp()
    shell = Shell()
    shell.setAttribute(Qt.WA_DontShowOnScreen)
    layout = QVBoxLayout(shell)
    tabs = QTabWidget()
    layout.addWidget(tabs)
    tabs.addTab(QWidget(), "Current")
    shell.app_context = SimpleNamespace(services=SimpleNamespace(new_items=support.NewItemService()))
    shell.archive = SimpleNamespace(
        archive_entries=fixture.entries,
        archive_cache_root=fixture.root / "cache",
        archive_package_root_edit=SimpleNamespace(text=lambda: str(fixture.root)),
        archive_entries_by_normalized_path=None, archive_entries_by_basename=None,
        archive_entries_by_extension=None,
    )
    shell.textures = SimpleNamespace(_show_archive_browser_from_texture_editor=lambda *_args: None)
    shell.set_status_message = lambda *_args, **_kwargs: None
    controller = shell._shared_new_item_controller()
    controller._read_entry = support._read
    created = []

    def create():
        tab = shell._create_new_item_studio_tab()
        fixture._tabs.append(tab.workflow)
        created.append(tab)
        return tab

    lazy = LazyToolTab(create)
    tabs.addTab(lazy, "Create New Item")
    shell.new_item_studio_tab = lazy
    shell._startup_splash_window = object()
    shell._schedule_new_item_rust_prewarm()
    timer = shell.findChildren(QTimer, options=Qt.FindDirectChildrenOnly)[0]
    with patch.object(RustNewItemStudioTab, "_start_prepare") as renderer, \
            patch.object(controller, "persist_issued_identities"), \
            patch.object(controller, "start_effect_index"):
        try:
            yield shell, controller, tabs, lazy, timer, created, renderer
        finally:
            request_tab_shutdowns(shell)
            request_transient_shutdowns(shell)
            _until(lambda: not tuple(iter_transient_shutdown_workers(shell)))
            shell.close()
            fixture.tearDown()
            shell.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.mark.parametrize("outcome", ['complete', 'close', 'failed'])
def test_startup_imports_leave_the_ui_responsive_and_are_owned_until_shutdown(preload_shell, monkeypatch, outcome):
    from cdmw.ui.shell import tool_tabs
    shell, controller, _tabs, lazy, timer, created, renderer = preload_shell
    shell._new_item_controller = None
    entered, release = threading.Event(), threading.Event()
    import_threads = []
    captured = []

    def prepare(module):
        assert module == 'cdmw.ui.new_item.controller'
        import_threads.append(QThread.currentThread())
        entered.set()
        assert release.wait(5)
        if outcome == 'failed':
            raise ImportError('Fixture dependency is unavailable')

    def shared():
        assert release.is_set()
        assert QThread.currentThread() is QApplication.instance().thread()
        shell._new_item_controller = controller
        return controller

    monkeypatch.setattr(tool_tabs.importlib, 'import_module', prepare)
    monkeypatch.setattr(shell, '_shared_new_item_controller', shared)
    monkeypatch.setattr(shell, '_preload_new_item_archive_data', lambda value: captured.append(value) or True)
    shell._startup_splash_window = None
    shell.show()
    try:
        timer.timeout.emit()
        _until(entered.is_set)
        assert all(thread is not QApplication.instance().thread() for thread in import_threads)
        assert tuple(iter_transient_shutdown_workers(shell))
        assert not created and not lazy._load_requested
        beats = []
        QTimer.singleShot(0, lambda: beats.append(True))
        _until(lambda: bool(beats))
        timer.timeout.emit()
        assert len(import_threads) == 1 and not captured
        if outcome == 'close':
            request_tab_shutdowns(shell)
            request_transient_shutdowns(shell)
        release.set()
        _until(lambda: not tuple(iter_transient_shutdown_workers(shell)))
        assert captured == ([controller] if outcome == 'complete' else [])
        if outcome == 'failed':
            assert not timer.isActive()
        assert not created
        renderer.assert_not_called()
    finally:
        release.set()
        request_transient_shutdowns(shell)
        _until(lambda: not tuple(iter_transient_shutdown_workers(shell)))


def test_startup_waits_for_the_cached_catalogue_instead_of_relisting_archives(preload_shell, tmp_path):
    from cdmw.core.archive_format import parse_archive_pamt
    from tests.archive_resident_index_fixtures import write_resident_index
    from tests.test_new_item_service import build_package, synthetic_files

    shell, controller, _tabs, lazy, timer, created, renderer = preload_shell
    root = tmp_path / 'game'
    entries = tuple(parse_archive_pamt(build_package(root, synthetic_files())))
    source = write_resident_index(root, entries, tmp_path / 'generation')
    catalogue = SimpleNamespace(current_session=None)
    shell.archive.archive_entries = ()
    shell.archive.archive_package_root_edit = SimpleNamespace(text=lambda: str(root))
    shell.archive.archive_catalogue_service = catalogue
    shell._startup_splash_window = None
    shell.show()
    with patch('cdmw.workers.new_item_workers.list_archive_entries', side_effect=AssertionError('relisted')):
        timer.timeout.emit()
        assert timer.isActive()
        assert not controller.busy and controller.snapshot is None
        assert not controller._snapshot_error
        catalogue.current_session = source
        timer.timeout.emit()
        _until(lambda: not controller.busy)
        assert controller.snapshot is not None, controller._snapshot_error
        assert not timer.isActive()
        assert not created and not lazy._load_requested
        renderer.assert_not_called()


@pytest.mark.parametrize("restored", [False, True])
def test_shell_preloads_only_data_and_reuses_it_when_opened(preload_shell, restored):
    shell, controller, tabs, lazy, timer, created, renderer = preload_shell
    current = tabs.currentWidget()
    if restored:
        tabs.setCurrentWidget(lazy)
    entered, release = threading.Event(), threading.Event()
    worker_threads = []
    build = controller.service.build_snapshot

    def delayed_build(*args, **kwargs):
        worker_threads.append(QThread.currentThread())
        entered.set()
        assert release.wait(5), "Test did not release the snapshot worker"
        return build(*args, **kwargs)

    def data_only_offer(warmup, _entries):
        assert warmup.cache_root is None, "Startup must not prepare native previews"

    with patch.object(type(controller.service), "build_snapshot", side_effect=delayed_build) as read, \
            patch.object(NewItemPreviewWarmup, "offer", autospec=True, side_effect=data_only_offer):
        try:
            timer.timeout.emit()
            assert not lazy._load_requested
            shell.show()
            if restored:
                _until(lambda: lazy.widget_if_created() is not None)
                assert created[0].isVisible()
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

            release.set()
            _until(lambda: controller.ready and not controller.busy)
            if not restored:
                assert lazy.widget_if_created() is None
                assert not lazy._load_requested and not created
                renderer.assert_not_called()
                controller.start_effect_index.assert_not_called()
            assert support.TEMPLATE in controller.snapshot.rows
            snapshot, draft = controller.snapshot, controller.draft
            tabs.setCurrentWidget(lazy)
            _until(lambda: bool(created) and created[0].workflow._panels_built)
            tab = created[0]
            workflow = tab.workflow
            assert workflow._current_step == 0
            assert workflow._panels[0] is workflow.template_panel
            controller.start_effect_index.assert_called_once_with()
            assert workflow._perks_panel is None
            tabs.setCurrentWidget(current)
            tabs.setCurrentWidget(lazy)
            assert read.call_count == 1
            assert controller.snapshot is snapshot
            assert controller.draft is draft
        finally:
            release.set()
            _until(lambda: not controller.iter_shutdown_workers())


def test_data_preload_failure_is_retained_until_the_opened_tool_retries(preload_shell):
    shell, controller, tabs, lazy, timer, created, renderer = preload_shell
    shell._startup_splash_window = None
    shell.show()
    with patch.object(type(controller.service), "build_snapshot", side_effect=ValueError("Owned preload failure")) as read:
        timer.timeout.emit()
        _until(lambda: not controller.busy)
        assert controller._snapshot_error == "Owned preload failure"
        assert lazy.widget_if_created() is None
        renderer.assert_not_called()
        tabs.setCurrentWidget(lazy)
        _until(lambda: bool(created) and "Owned preload failure" in created[0].workflow._read_failure.report_text)
        workflow = created[0].workflow
        assert workflow._read_button.text() == "Try again"
        assert workflow._read_button.isEnabled()
        assert read.call_count == 1
    workflow._read_button.click()
    _until(lambda: workflow._panels_built and not controller.busy)
    assert controller._snapshot_error == ""


def test_shell_owns_and_cancels_data_preload_before_any_tool_exists(preload_shell):
    shell, controller, _tabs, lazy, timer, _created, renderer = preload_shell
    snapshot = controller.service.build_snapshot(shell.archive.archive_entries, read_entry=support._read)
    entered, release = threading.Event(), threading.Event()
    stops = []

    def delayed_result(*_args, **kwargs):
        stops.append(kwargs["stop_event"])
        entered.set()
        assert release.wait(5)
        return snapshot

    shell._startup_splash_window = None
    shell.show()
    with patch.object(type(controller.service), "build_snapshot", side_effect=delayed_result):
        try:
            timer.timeout.emit()
            _until(entered.is_set)
            assert lazy.widget_if_created() is None
            assert any(name == "transient.snapshot" for name, _, _ in iter_transient_shutdown_workers(shell))
            request_transient_shutdowns(shell)
            assert stops[0].is_set()
        finally:
            release.set()
            _until(lambda: not controller.iter_shutdown_workers())
    assert controller.snapshot is None
    renderer.assert_not_called()


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


@pytest.mark.parametrize("early_open", [False, True])
def test_workspace_mount_yields_between_panels_and_publishes_only_when_complete(unprepared, early_open):
    from cdmw.ui.new_item import tab as tab_module

    tab = unprepared
    workflow = tab.workflow
    bridge = NewItemPresentationBridge(workflow)
    events = []
    checkpoints = []
    panel_names = ("TemplatePanel", "IdentityPanel", "ModelPanel", "OutputPanel")

    def constructor(name, original):
        def build(panel, *args, **kwargs):
            original(panel, *args, **kwargs)
            events.append((name, QThread.currentThread() is QApplication.instance().thread()))

            def heartbeat():
                events.append(("heartbeat", True))
                state = bridge.snapshot()
                checkpoints.append((workflow._panels_built, state["root"]["kind"],
                                    state["unsupported"], workflow._progress.isHidden()))

            QTimer.singleShot(0, heartbeat)
        return build

    with ExitStack() as patches:
        for name in panel_names:
            cls = getattr(tab_module, name)
            patches.enter_context(patch.object(cls, "__init__", constructor(name, cls.__init__)))
        tab.prewarm()
        if early_open:
            tab.show()
        _until(lambda: workflow._panels_built and not tab.controller.busy)

    assert events == [(name, True) for panel in panel_names for name in (panel, "heartbeat")]
    assert len(checkpoints) == 4
    assert all(not ready and kind != "workspace" and not unsupported and not hidden
               for ready, kind, unsupported, hidden in checkpoints)
    assert bridge.snapshot()["root"]["kind"] == "workspace"
    assert workflow._panel_mount_steps is None
    assert not workflow._panel_mount_timer.isActive()
    assert tab.isVisible() == early_open
    tab.controller.start_effect_index.assert_called_once_with()
    assert workflow._perks_panel is None


def test_handoff_during_workspace_mount_reuses_snapshot_and_waits_for_panels(unprepared, tmp_path):
    tab = unprepared
    workflow, controller = tab.workflow, tab.controller
    build = controller.service.build_snapshot
    imports = []
    source = tmp_path / "import.obj"
    with patch.object(type(controller.service), "build_snapshot", side_effect=build) as read, \
            patch.object(controller, "start_model_import", side_effect=imports.append):
        tab.prewarm()
        _until(lambda: controller.ready and not controller.busy)
        workflow._panel_mount_timer.stop()
        assert not workflow._panels_built
        snapshot = controller.snapshot
        tab.prefill_template(support.TEMPLATE)
        tab.open_model_source(source)
        tab.show()
        tab.prewarm()
        workflow.start_snapshot()
        assert not imports
        assert read.call_count == 1
        workflow._panel_mount_timer.start()
        _until(lambda: bool(imports) and not controller.busy)
        assert workflow._panels_built
        assert controller.snapshot is snapshot
        assert controller.draft.template_key == support.TEMPLATE
        assert imports == [source.resolve()]
        assert workflow._current_step == 2
        assert read.call_count == 1


@pytest.mark.parametrize("after_model", [False, True])
def test_shutdown_stops_partial_workspace_mount(unprepared, after_model):
    tab = unprepared
    workflow, controller = tab.workflow, tab.controller
    tab.prewarm()
    if after_model:
        _until(lambda: hasattr(workflow, "model_panel"))
    else:
        _until(lambda: controller.ready and not controller.busy)
    workflow._panel_mount_timer.stop()
    assert not workflow._panels_built
    assert not hasattr(workflow, "output_panel")
    tab.request_shutdown()
    # Even a callback already queued at close must not resume construction.
    workflow._advance_panel_mount()
    _until(lambda: not tab.iter_shutdown_workers())
    assert workflow._panel_mount_steps is None
    assert not workflow._panel_mount_timer.isActive()
    assert not workflow._panels_built
    assert not hasattr(workflow, "output_panel")
    assert "New Item workspace ready." not in workflow.log.toPlainText()
    controller.start_effect_index.assert_not_called()


def test_effect_cache_is_ready_before_first_perks_visit_and_refreshes_with_snapshot(unprepared, tmp_path):
    from cdmw.services.effect_catalogue import build_effect_catalogue, save_effect_catalogue
    from cdmw.workers import effect_catalogue_worker

    tab = unprepared
    workflow, controller = tab.workflow, tab.controller
    snapshot = controller.service.build_snapshot(workflow._get_entries(), read_entry=support._read)
    cache_path = tmp_path / "effects.json"
    expected = build_effect_catalogue(snapshot)
    save_effect_catalogue(expected, cache_path)
    controller.effect_cache_path = cache_path
    load = effect_catalogue_worker.load_effect_catalogue
    load_threads = []

    def load_cache(*args, **kwargs):
        load_threads.append(QThread.currentThread())
        return load(*args, **kwargs)

    start_index = NewItemStudioController.start_effect_index.__get__(controller)
    with patch.object(controller, "start_effect_index", wraps=start_index) as start, \
            patch.object(effect_catalogue_worker, "load_effect_catalogue", side_effect=load_cache), \
            patch.object(effect_catalogue_worker, "build_effect_catalogue") as rebuild:
        tab.prewarm()
        _until(lambda: controller.effect_catalogue is not None and not controller.iter_shutdown_workers())
        assert start.call_count == 1
        assert workflow._perks_panel is None
        assert workflow._current_step == 0
        assert controller.effect_catalogue == expected
        original = controller.effect_catalogue
        workflow.start_snapshot()
        _until(lambda: start.call_count == 2 and not controller.iter_shutdown_workers())
        assert controller.effect_catalogue is not original
        assert workflow._perks_panel is None
        catalogue = controller.effect_catalogue
        workflow.show_step(4)
        assert not workflow.perks_panel.index_button.isEnabled()
        workspace = workflow.perks_panel.effects_workspace
        _until(lambda: bool(workspace._library_rows))
        assert all(row.facts == catalogue.get(stem) for stem, row in workspace._library_rows.items())
        workflow.show_step(0)
        workflow.show_step(4)
        assert start.call_count == 2
        assert controller.effect_catalogue is catalogue

        # A reread refreshes prewarmed metadata even while another step is open.
        workflow.show_step(0)
        workflow.start_snapshot()
        _until(lambda: start.call_count == 3 and not controller.iter_shutdown_workers())
        assert controller.effect_catalogue is not catalogue
        assert len(load_threads) == 3
        assert all(thread is not QApplication.instance().thread() for thread in load_threads)
        rebuild.assert_not_called()


@pytest.mark.parametrize("visit_while_indexing", [False, True])
def test_cold_effect_index_starts_before_perks_and_is_reused(unprepared, visit_while_indexing):
    from cdmw.services.effect_catalogue import build_effect_catalogue
    from cdmw.workers import effect_catalogue_worker

    tab = unprepared
    workflow, controller = tab.workflow, tab.controller
    entered, release = threading.Event(), threading.Event()
    threads = []

    def build(snapshot, **kwargs):
        threads.append(QThread.currentThread())
        entered.set()
        assert release.wait(5), "Test did not release the effect worker"
        return build_effect_catalogue(snapshot, **kwargs)

    start_index = NewItemStudioController.start_effect_index.__get__(controller)
    with patch.object(controller, "start_effect_index", wraps=start_index) as start, \
            patch.object(effect_catalogue_worker, "build_effect_catalogue", side_effect=build) as rebuild:
        try:
            tab.prewarm()
            _until(lambda: entered.is_set() and workflow._panels_built and not controller.busy)
            assert workflow._current_step == 0
            assert workflow._perks_panel is None
            assert controller.effect_catalogue is None
            assert threads == [controller._effect_lane._thread]
            assert threads[0] is not QApplication.instance().thread()
            if visit_while_indexing:
                workflow.show_step(4)
                assert start.call_count == 1
            beats = []
            QTimer.singleShot(0, lambda: beats.append(True))
            _until(lambda: bool(beats))
        finally:
            release.set()
            _until(lambda: not controller.iter_shutdown_workers())

        assert controller.effect_catalogue is not None
        catalogue = controller.effect_catalogue
        if not visit_while_indexing:
            workflow.show_step(4)
        assert not workflow.perks_panel.index_button.isEnabled()
        workflow.show_step(0)
        workflow.show_step(4)
        assert controller.effect_catalogue is catalogue
        assert start.call_count == 1
        assert rebuild.call_count == 1
