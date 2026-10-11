"""Exercise extension selection through the constructed Archive workspace."""

from collections import Counter
from dataclasses import replace
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QFocusEvent, QImage, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QPushButton, QTreeWidget

from cdmw.domain.archives.catalogue import ArchiveFacet, ArchiveFacetsResult
from cdmw.domain.archives.catalogue_operations import ArchiveBackendError
from cdmw.domain.archives.item_catalogue import BuildNameIndexResult
from cdmw.ui.archive_browser.mesh_builder_startup_smoke import (
    configure_synthetic_archive_context,
    synthetic_archive_entry,
)
from tests.test_archive_single_backend_workspace import workspace


def _ready(window, tmp_path, *, counts=True):
    archive = window.archive
    configure_synthetic_archive_context(window, synthetic_archive_entry(tmp_path))
    archive.archive_extension_counts = Counter({".pac": 12, ".dds": 4}) if counts else Counter()
    archive._rebuild_archive_extension_filter_choices("*")
    archive.archive_filters_dirty = False
    archive._update_archive_filter_button_state()
    assert not hasattr(archive, "archive_filter_worker")
    assert archive.archive_extension_picker_button.text() == "Select Extension"
    assert archive.archive_extension_picker_button.isEnabled()
    return archive


def _leaf(tree, value):
    for index in range(tree.topLevelItemCount()):
        parent = tree.topLevelItem(index)
        if parent.data(0, Qt.UserRole) == value:
            return parent
        for child_index in range(parent.childCount()):
            child = parent.child(child_index)
            if child.data(0, Qt.UserRole) == value:
                return child
    raise AssertionError(f"Missing extension {value}")


def _open_picker(archive):
    archive.archive_extension_picker_button.click()
    dialog = archive.archive_extension_picker_dialog
    assert dialog is not None and dialog.isVisible()
    QApplication.processEvents()
    return dialog


def _select_button(dialog):
    return next(button for button in dialog.findChildren(QPushButton) if button.text() == "Select Extension")


def _loading_hint(dialog):
    return next(label for label in dialog.findChildren(QLabel) if label.text() == "Loading extension counts...")


def _start_loading(workspace, monkeypatch):
    archive = workspace.archive
    bridge = archive.archive_remote_bridge
    assert bridge.current_session is None
    # Keep unrelated catalogue warmups out of this controlled startup sequence.
    monkeypatch.setattr(archive.archive_item_finder_warmup_controller, "start", lambda *args, **kwargs: None)
    monkeypatch.setattr(archive.archive_character_finder_warmup_controller, "start", lambda *args, **kwargs: None)
    monkeypatch.setattr(workspace, "_publish_archive_catalogue_session_to_consumers", lambda *args: None)
    monkeypatch.setattr(bridge, "request_structure_children", lambda *args: None)
    bridge._begin_pending("Loading archive catalogue...", operation="open")
    workspace.set_busy(False)
    return archive


@pytest.mark.parametrize("terminal", ["failure", "cancelled"])
def test_startup_warmup_waits_for_picker_and_search_activity_then_resumes(workspace, tmp_path, monkeypatch, terminal):
    archive = _ready(workspace, tmp_path)
    warmup = archive.archive_item_finder_warmup_controller
    session = archive.archive_remote_bridge.current_session
    calls = []
    monkeypatch.setattr(archive.archive_catalogue_service, "build_name_index", lambda *_a, **_k: calls.append("build") or f"build-{len(calls)}")
    monkeypatch.setattr(archive.archive_catalogue_service, "search_item_catalog", lambda *_a, **_k: calls.append("search") or "search")
    cancelled = []
    monkeypatch.setattr(archive.archive_catalogue_service, "cancel", cancelled.append)

    def ready_and_idle():
        archive.archive_browser_preload_state = "ready"
        archive.archive_browser_first_visible_paint_done = True
        archive.archive_browser_first_visible_painted_at = time.perf_counter() - 1.0
        archive._clear_archive_ui_activity()

    ready_and_idle()
    assert archive._archive_browser_background_work_allowed()
    dialog = _open_picker(archive)
    warmup.start(session, ui_generation=0)
    # A picker stays interactive even while the user pauses between clicks.
    archive._clear_archive_ui_activity()
    warmup._continue_warmup()
    assert not calls and warmup._continue_timer.isActive()

    tree = dialog.findChild(QTreeWidget)
    tree.setCurrentItem(_leaf(tree, ".pac"))
    _select_button(dialog).click()
    assert archive.archive_extension_picker_dialog is None
    ready_and_idle()
    QApplication.sendEvent(archive.archive_filter_edit, QFocusEvent(QEvent.FocusIn))
    assert archive._archive_ui_interactive_active()
    warmup._continue_warmup()
    assert not calls
    QTest.keyClicks(archive.archive_filter_edit, "body")
    assert archive._archive_ui_interactive_active()

    # Simulate the new search completing and the input grace period expiring.
    ready_and_idle()
    warmup._continue_warmup()
    assert calls == ["build"]
    QApplication.sendEvent(archive.archive_filter_edit, QFocusEvent(QEvent.FocusIn))
    warmup._handle_result("build-1", "build_name_index", BuildNameIndexResult(session.session_id, True, True, 1, 0))
    warmup._continue_warmup()
    assert calls == ["build"] and cancelled == ["build-1"]
    archive._clear_archive_ui_activity()
    warmup._continue_warmup()
    assert calls == ["build", "build"]  # Interrupted catalogue preparation resumes on idle.
    warmup._handle_result("build-2", "build_name_index", BuildNameIndexResult(session.session_id, True, True, 1, 0))
    warmup._continue_warmup()
    assert calls == ["build", "build", "search"]
    if terminal == "failure":
        warmup._handle_failure("search", ArchiveBackendError("fixture_failure", "Owned failure"))
    else:
        warmup._handle_cancelled("search")
    warmup._continue_warmup()
    assert calls == ["build", "build", "search"]  # Failed/cancelled work needs an explicit retry.
    warmup.invalidate()
    assert not warmup._continue_timer.isActive()


def test_foreground_finder_icons_keep_priority_while_background_warmup_is_deferred(workspace, tmp_path, monkeypatch):
    archive = _ready(workspace, tmp_path)
    warmup = archive.archive_item_finder_warmup_controller
    session = archive.archive_remote_bridge.current_session
    calls = []
    monkeypatch.setattr(archive.archive_catalogue_service, "load_item_icons", lambda request, **_k: calls.append(request) or "icons")
    warmup.start(session, ui_generation=0)
    warmup._state = "building"
    warmup._catalogue_ready = True
    archive._note_archive_ui_activity()
    assert not archive._archive_browser_background_work_allowed()
    assert warmup.prioritize_icons(session.session_id, (1234,)) == (1234,)
    warmup._continue_warmup()
    assert len(calls) == 1 and calls[0].item_ids == (1234,)
    warmup.invalidate()


def test_app_input_interrupts_character_page_and_resumes_only_after_all_pause_owners_clear(workspace, tmp_path):
    archive = _ready(workspace, tmp_path)
    warmup = archive.archive_character_finder_warmup_controller
    archive.archive_browser_preload_state = "ready"
    archive.archive_browser_first_visible_paint_done = True
    archive.archive_browser_first_visible_painted_at = time.perf_counter() - 3
    archive._clear_archive_ui_activity()
    calls = []
    preview = SimpleNamespace(_closed=False, page_complete=False,
        pause_scheduling=lambda **kw: calls.append(("pause", kw)),
        resume_scheduling=lambda: calls.append(("resume", {})),
        shutdown=lambda: None, iter_shutdown_workers=lambda: iter(()))
    warmup._session = archive.archive_remote_bridge.current_session
    warmup._preview, warmup._rendering = preview, True
    warmup._pages.append("retained page")
    warmup._continue()
    assert warmup._timer.isActive()
    calls.clear()
    # A drag anywhere in the application must stop an already-started page.
    target = QLineEdit(workspace)
    QApplication.sendEvent(target, QMouseEvent(QEvent.MouseMove, QPointF(5, 5), QPointF(5, 5),
        Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
    assert calls == [("pause", {"cancel_active": True})]
    assert archive.archive_ui_activity_timer.interval() == 2000
    assert archive.archive_ui_activity_until - time.perf_counter() > 1.5
    assert archive.archive_item_finder_warmup_controller._background_paused
    warmup._continue()
    assert len(calls) == 1 and warmup._pages
    finder = object()
    warmup.pause(finder)
    archive.archive_ui_activity_timer.timeout.emit()
    warmup._continue()
    assert warmup._paused  # Closing the input grace period cannot unpause an open Finder.
    assert all(name == "pause" for name, _ in calls)
    warmup.resume(finder)
    warmup._continue()
    assert not warmup._paused and calls[-1][0] == "resume" and warmup._pages
    warmup.invalidate()


def test_native_renderer_input_pauses_warmups_but_other_apps_do_not(workspace, tmp_path, monkeypatch):
    from cdmw.ui.archive_browser import runtime_state
    archive = _ready(workspace, tmp_path)
    activity = archive.archive_ui_activity_filter
    activity._native_input_timer.stop()
    activity._last_native_input = 10
    archive._clear_archive_ui_activity()
    monkeypatch.setattr(runtime_state, "_native_input_state", lambda: (11, True, False))
    activity._poll_native_input()
    assert archive._archive_ui_interactive_active()
    assert archive.archive_item_finder_warmup_controller._background_paused
    archive._clear_archive_ui_activity()
    activity._poll_native_input()
    assert not archive._archive_ui_interactive_active()  # An unchanged input timestamp stays idle.
    monkeypatch.setattr(runtime_state, "_native_input_state", lambda: (11, True, True))
    activity._poll_native_input()
    assert archive._archive_ui_interactive_active()  # Holding a sculpt/drag gesture is not idle.
    archive._clear_archive_ui_activity()
    monkeypatch.setattr(runtime_state, "_native_input_state", lambda: (12, False, True))
    activity._poll_native_input()
    assert not archive._archive_ui_interactive_active()


def test_app_activity_pauses_new_item_preload_and_foreground_promotion_unblocks_it(workspace, tmp_path):
    archive = _ready(workspace, tmp_path)
    gate = workspace._new_item_preload_gate
    archive.archive_entries = (synthetic_archive_entry(tmp_path),)
    captured = []
    controller = SimpleNamespace(start_snapshot=lambda *args, **kwargs: captured.append(kwargs) or True)
    assert workspace._preload_new_item_archive_data(controller)
    assert captured[0]["preload_gate"] is gate
    stop, finished = threading.Event(), threading.Event()
    gate.bind(stop)
    target = QLineEdit(workspace)
    QApplication.sendEvent(target, QMouseEvent(QEvent.MouseMove, QPointF(5, 5), QPointF(5, 5),
        Qt.NoButton, Qt.LeftButton, Qt.NoModifier))

    def checkpoint():
        gate.is_set()
        finished.set()

    thread = threading.Thread(target=checkpoint)
    thread.start()
    try:
        assert not finished.wait(0.08)
        archive._clear_archive_ui_activity()
        assert finished.wait(2)
        archive._note_archive_ui_activity()
        gate.promote()
        assert not gate.is_set()  # Opening a consuming tool overrides idle-only preloading.
    finally:
        stop.set()
        thread.join(2)
        assert not thread.is_alive()


def test_item_startup_page_yields_and_cancelled_icon_requests_are_retried(workspace, tmp_path, monkeypatch):
    archive = _ready(workspace, tmp_path)
    warmup = archive.archive_item_finder_warmup_controller
    session = archive.archive_remote_bridge.current_session
    requests, cancelled = [], []
    monkeypatch.setattr(warmup, "_background_allowed", lambda: True)
    monkeypatch.setattr(archive.archive_catalogue_service, "load_item_icons",
        lambda request, **kw: requests.append(request) or f"icons-{len(requests)}")
    monkeypatch.setattr(archive.archive_catalogue_service, "cancel", cancelled.append)
    warmup.start(session, ui_generation=0)
    warmup._catalogue_ready = True
    warmup._state = "searching"
    warmup._enumeration_done = True
    archive._note_archive_ui_activity()
    warmup._publish_initial_search(SimpleNamespace(items=(SimpleNamespace(item_id=1234, icon_paths=("icon.dds",)),)))
    warmup._continue_warmup()
    assert not requests  # The saved first page is still background work.
    archive._clear_archive_ui_activity()
    warmup._continue_warmup()
    assert len(requests) == 1
    archive._note_archive_ui_activity()
    assert cancelled == ["icons-1"] and 1234 in warmup._pending_icon_ids
    warmup._handle_cancelled("icons-1")
    warmup._handle_failure("icons-1", RuntimeError("late result"))
    assert not warmup._failed_icon_ids
    archive._clear_archive_ui_activity()
    warmup._continue_warmup()
    assert len(requests) == 2 and requests[1].item_ids == (1234,)
    warmup.invalidate()


def test_activity_cancels_icon_decode_and_requeues_it_without_failure(workspace, tmp_path, monkeypatch):
    from cdmw.workers.archive_item_finder_workers import ArchiveItemThumbnailWorker
    archive = _ready(workspace, tmp_path)
    warmup = archive.archive_item_finder_warmup_controller
    session = archive.archive_remote_bridge.current_session
    started, release = threading.Event(), threading.Event()
    def batch(worker):
        started.set()
        while not release.wait(.005) and not worker.stop_event.is_set():
            pass
        return {}
    monkeypatch.setattr(ArchiveItemThumbnailWorker, "_batch_dds_previews", batch)
    monkeypatch.setattr(warmup, "_background_allowed", lambda: True)
    monkeypatch.setattr(archive.archive_catalogue_service, "load_item_icons", lambda *a, **kw: "retry")
    image = QImage(8, 8, QImage.Format_ARGB32)
    image.fill(Qt.red)
    path = tmp_path / "icon.png"
    assert image.save(str(path))
    warmup.start(session, ui_generation=0)
    warmup._state = "icon_warmup"
    warmup._catalogue_ready = warmup._initial_search_complete = warmup._enumeration_done = True
    archive._clear_archive_ui_activity()
    warmup._inflight_icon_ids.add(1234)
    failures = []
    warmup.iconsFailed.connect(lambda *args: failures.append(args))
    try:
        warmup._start_decode_worker({1234: str(path)}, requested_ids=(1234,))
        assert started.wait(2)
        archive._note_archive_ui_activity()
        deadline = time.monotonic() + 3
        while warmup._threads and time.monotonic() < deadline:
            QTest.qWait(5)
        assert not warmup._threads and 1234 in warmup._pending_icon_ids
        assert not failures and not warmup._failed_icon_ids
        release.set()
        archive._clear_archive_ui_activity()
        warmup._continue_warmup()
        warmup._publish_icon_sources(SimpleNamespace(session_id=session.session_id,
            items=(SimpleNamespace(item_id=1234, png_path=str(path)),)), (1234,))
        deadline = time.monotonic() + 3
        while warmup._threads and time.monotonic() < deadline:
            QTest.qWait(5)
        assert not warmup._threads and 1234 in warmup.cached_icons(session.session_id, (1234,))
        assert not failures
    finally:
        release.set()
        warmup.invalidate()


def test_cached_picker_opens_without_blocking_the_application_or_rescanning(workspace, tmp_path, monkeypatch):
    archive = _ready(workspace, tmp_path)

    class NoScan(list):
        def __iter__(self):
            pytest.fail("Opening the cached picker must not scan archive entries.")

    class BlockedEvents(QObject):
        blocked = 0
        painted = False

        def eventFilter(self, watched, event):
            if event.type() == QEvent.WindowBlocked:
                self.blocked += 1
            if event.type() == QEvent.Paint and watched is archive.archive_extension_picker_dialog:
                self.painted = True
            return False

    archive.archive_entries = NoScan()
    monkeypatch.setattr(QDialog, "exec", lambda _dialog: pytest.fail("The extension picker must not enter a modal loop."))
    events = BlockedEvents()
    app = QApplication.instance()
    app.installEventFilter(events)
    try:
        dialog = _open_picker(archive)
        assert not dialog.isModal()
        assert _leaf(dialog.findChild(QTreeWidget), ".pac").text(1) == "12"
        assert QApplication.activeModalWidget() is None
        assert events.painted and events.blocked == 0
        dialog.reject()
    finally:
        app.removeEventFilter(events)


@pytest.mark.parametrize("counts_before_rows", [False, True])
def test_startup_click_opens_picker_before_first_rows(workspace, tmp_path, monkeypatch, counts_before_rows):
    archive = _start_loading(workspace, monkeypatch)
    controller = archive.archive_remote_bridge.controller
    facets = ArchiveFacetsResult("synthetic-session", (ArchiveFacet(".pac", ".pac", 12),), (), (), ())
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: errors.append(error))
    dialog = _open_picker(archive)
    tree = dialog.findChild(QTreeWidget)
    search = dialog.findChild(QLineEdit)
    hint = _loading_hint(dialog)
    assert hint.isVisible() and tree.topLevelItemCount() == 1
    search.setText("pac")
    if counts_before_rows:
        controller.facetsReady.emit(facets)
    configure_synthetic_archive_context(workspace, synthetic_archive_entry(tmp_path))
    controller.queryPublished.emit(archive.archive_remote_bridge.model.query_handle)
    if not counts_before_rows:
        controller.facetsReady.emit(facets)
    assert search.text() == "pac" and not hint.isVisible()
    item = _leaf(tree, ".pac")
    assert item.text(1) == "12" and not item.isHidden()
    controller.facetsReady.emit(ArchiveFacetsResult("obsolete-session", (ArchiveFacet(".dds", ".dds", 4),), (), (), ()))
    assert _leaf(tree, ".pac") is item
    tree.setCurrentItem(item)
    _select_button(dialog).click()
    assert errors == []
    assert archive.archive_extension_picker_dialog is None
    assert archive.textures._combo_value(archive.archive_extension_filter_combo) == ".pac"
    assert archive.archive_filters_dirty


@pytest.mark.parametrize("finish", ["cancel", "window_close", "escape", "destroy", "load_failure", "counts_failure"])
def test_startup_picker_close_disconnects_late_updates(workspace, tmp_path, monkeypatch, finish):
    archive = _start_loading(workspace, monkeypatch)
    bridge = archive.archive_remote_bridge
    controller = bridge.controller
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: errors.append(error))
    dialog = _open_picker(archive)
    if finish == "counts_failure":
        configure_synthetic_archive_context(workspace, synthetic_archive_entry(tmp_path))
        controller.queryPublished.emit(bridge.model.query_handle)
    if finish == "cancel":
        dialog.reject()
    elif finish == "window_close":
        dialog.close()
    elif finish == "escape":
        QTest.keyClick(dialog, Qt.Key_Escape)
    elif finish == "destroy":
        dialog.deleteLater()
    else:
        controller.requestFailed.emit("facets" if finish == "counts_failure" else "open", RuntimeError("Fixture load failure"))
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert archive.archive_extension_picker_dialog is None
    assert archive.archive_remote_query_pending == (finish not in {"load_failure", "counts_failure"})
    assert archive.textures._combo_value(archive.archive_extension_filter_combo) == "*"
    assert not archive.archive_filters_dirty
    configure_synthetic_archive_context(workspace, synthetic_archive_entry(tmp_path))
    controller.queryPublished.emit(bridge.model.query_handle)
    controller.facetsReady.emit(ArchiveFacetsResult("synthetic-session", (ArchiveFacet(".pac", ".pac", 12),), (), (), ()))
    controller.requestFailed.emit("facets", RuntimeError("Late fixture failure"))
    assert errors == []


def test_startup_picker_keeps_existing_worker_and_query_gates(workspace, tmp_path, monkeypatch):
    archive = _start_loading(workspace, monkeypatch)
    assert archive.archive_extension_picker_button.isEnabled()
    with monkeypatch.context() as patch:
        patch.setattr(workspace, "worker_thread", object())
        archive._update_archive_filter_button_state()
        assert not archive.archive_extension_picker_button.isEnabled()
    configure_synthetic_archive_context(workspace, synthetic_archive_entry(tmp_path))
    archive._update_archive_filter_button_state()
    assert not archive.archive_extension_picker_button.isEnabled()
    archive.archive_remote_query_pending = False
    archive._update_archive_filter_button_state()
    assert archive.archive_extension_picker_button.isEnabled()


@pytest.mark.parametrize("interaction", ["select", "double_click"])
def test_selecting_pac_closes_the_real_picker_before_applying_the_filter(workspace, tmp_path, monkeypatch, interaction):
    archive = _ready(workspace, tmp_path)
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: errors.append(error))
    dialog = _open_picker(archive)
    tree = dialog.findChild(QTreeWidget)
    item = _leaf(tree, ".pac")
    visible_during_change = []
    archive.archive_extension_filter_combo.currentTextChanged.connect(lambda _text: visible_during_change.append(dialog.isVisible()))
    QTest.mouseClick(tree.viewport(), Qt.LeftButton, pos=tree.visualItemRect(item).center())
    if interaction == "select":
        _select_button(dialog).click()
    else:
        QTest.mouseDClick(tree.viewport(), Qt.LeftButton, pos=tree.visualItemRect(item).center())
    assert errors == []
    assert archive.archive_extension_picker_dialog is None
    assert visible_during_change and not any(visible_during_change)
    assert archive.textures._combo_value(archive.archive_extension_filter_combo) == ".pac"
    assert archive.archive_filters_dirty


def test_picker_opens_before_counts_and_updates_in_place_then_disconnects(workspace, tmp_path, monkeypatch):
    archive = _ready(workspace, tmp_path, counts=False)
    controller = archive.archive_remote_bridge.controller
    facets = ArchiveFacetsResult("synthetic-session", (ArchiveFacet(".pac", ".pac", 12),), (), (), ())
    dialog = _open_picker(archive)
    hint = _loading_hint(dialog)
    tree = dialog.findChild(QTreeWidget)
    assert hint.isVisible() and tree.topLevelItemCount() == 1
    controller.facetsReady.emit(ArchiveFacetsResult("obsolete-session", facets.extensions, (), (), ()))
    assert tree.topLevelItemCount() == 1
    dialog.findChild(QLineEdit).setText("pac")
    controller.facetsReady.emit(facets)
    assert not hint.isVisible()
    item = _leaf(tree, ".pac")
    assert item.text(1) == "12" and not item.isHidden()
    tree.setCurrentItem(item)
    _select_button(dialog).click()
    assert archive.textures._combo_value(archive.archive_extension_filter_combo) == ".pac"
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: errors.append(error))
    controller.facetsReady.emit(facets)
    assert errors == []


def test_cancelling_the_extension_picker_preserves_the_current_filter(workspace, tmp_path):
    archive = _ready(workspace, tmp_path)
    dialog = _open_picker(archive)
    dialog.findChild(QTreeWidget).setCurrentItem(_leaf(dialog.findChild(QTreeWidget), ".pac"))
    dialog.reject()
    assert archive.textures._combo_value(archive.archive_extension_filter_combo) == "*"
    assert not archive.archive_filters_dirty


def test_late_counts_restore_the_current_extension_in_the_picker(workspace, tmp_path):
    archive = _ready(workspace, tmp_path, counts=False)
    archive._rebuild_archive_extension_filter_choices(".pac")
    dialog = _open_picker(archive)
    tree = dialog.findChild(QTreeWidget)
    assert tree.currentItem() is None
    archive.archive_remote_bridge.controller.facetsReady.emit(ArchiveFacetsResult(
        "synthetic-session", (ArchiveFacet(".pac", ".pac", 12),), (), (), ()))
    assert tree.currentItem().data(0, Qt.UserRole) == ".pac"
    dialog.reject()
    assert archive.textures._combo_value(archive.archive_extension_filter_combo) == ".pac"


def test_repeated_clicks_keep_one_picker_and_reopening_uses_current_counts(workspace, tmp_path):
    archive = _ready(workspace, tmp_path)
    dialog = _open_picker(archive)
    search = dialog.findChild(QLineEdit)
    search.setText("pac")
    assert _open_picker(archive) is dialog
    assert search.text() == "pac"
    dialog.reject()
    archive.archive_extension_counts[".pac"] = 24
    reopened = _open_picker(archive)
    assert reopened is not dialog
    assert _leaf(reopened.findChild(QTreeWidget), ".pac").text(1) == "24"
    next(button for button in reopened.findChildren(QPushButton) if button.text() == "All Files").click()
    assert archive.archive_extension_picker_dialog is None
    assert archive.textures._combo_value(archive.archive_extension_filter_combo) == "*"


@pytest.mark.parametrize("operation", ["open", "query", "retry"])
def test_new_archive_operation_closes_picker_without_changing_filter(workspace, tmp_path, operation):
    archive = _ready(workspace, tmp_path)
    dialog = _open_picker(archive)
    dialog.findChild(QTreeWidget).setCurrentItem(_leaf(dialog.findChild(QTreeWidget), ".pac"))
    archive.archive_remote_bridge._begin_pending("Fixture archive operation", operation=operation)
    assert not dialog.isVisible() and archive.archive_extension_picker_dialog is None
    assert archive.textures._combo_value(archive.archive_extension_filter_combo) == "*"
    assert not archive.archive_filters_dirty


def test_replaced_session_closes_picker_without_applying_stale_selection(workspace, tmp_path):
    archive = _ready(workspace, tmp_path)
    bridge = archive.archive_remote_bridge
    dialog = _open_picker(archive)
    bridge.controller.queryPublished.emit(replace(bridge.model.query_handle, session_id="new-session"))
    assert not dialog.isVisible() and archive.archive_extension_picker_dialog is None
    assert archive.textures._combo_value(archive.archive_extension_filter_combo) == "*"
