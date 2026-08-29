from __future__ import annotations

import os
import threading
import time
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QSettings, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QToolButton

from cdmw.ui.archive_browser.static_replacement_dialog_prompt_shell import _MeshEditorSaveAwareDialog
from cdmw.ui.mesh_editor.tab_lifetime import _stop_destroyed_mesh_editor_workers
from cdmw.ui.mesh_editor.tab import MeshEditorTab


class _SlowController:
    def __init__(self) -> None:
        self.close_called = False
        self.active_session_id = "slow-session"

    def close_active_session(self) -> None:
        self.close_called = True
        time.sleep(0.25)
        self.active_session_id = ""


class _RetiringDispatcher:
    def __init__(self) -> None:
        self.cancelled = False
        self.retired: list[object] = []

    def cancel_pending(self) -> None:
        self.cancelled = True

    def retire_controller(self, controller: object) -> None:
        self.retired.append(controller)


class _StopAwareWorker(QObject):
    finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        self.stop_event.wait(5.0)
        self.finished.emit()


def test_destroyed_worker_guard_accepts_shutdown_protocol_test_doubles() -> None:
    class ThreadStub:
        def __init__(self) -> None:
            self.interrupted = False
            self.quit_requested = False

        def requestInterruption(self) -> None:
            self.interrupted = True

        def quit(self) -> None:
            self.quit_requested = True

    worker = _StopAwareWorker()
    thread = ThreadStub()
    tab = type(
        "TabStub",
        (),
        {"iter_shutdown_workers": lambda self: (("test", thread, worker),)},
    )()

    _stop_destroyed_mesh_editor_workers(tab)

    assert worker.stop_event.is_set()
    assert thread.interrupted
    assert thread.quit_requested


def test_close_standalone_session_detaches_slow_controller_without_waiting() -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings("CDMWTests", "MeshEditorNonblockingClose")
    settings.clear()
    tab = MeshEditorTab(settings=settings)
    controller = _SlowController()
    dispatcher = _RetiringDispatcher()
    tab.standalone_controller = controller  # type: ignore[assignment]
    tab.standalone_live_stroke_dispatcher = dispatcher  # type: ignore[assignment]

    started = time.perf_counter()
    tab.close_standalone_session()
    elapsed = time.perf_counter() - started

    assert elapsed < 0.05
    assert tab.standalone_controller is None
    assert dispatcher.cancelled
    assert dispatcher.retired == [controller]
    assert not controller.close_called
    tab.standalone_live_stroke_dispatcher = None
    tab.deleteLater()
    app.processEvents()


def test_close_session_button_confirms_edits_and_returns_to_empty_state_without_waiting() -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings("CDMWTests", "MeshEditorCloseSessionButton")
    settings.clear()
    tab = MeshEditorTab(settings=settings)
    controller = _SlowController()
    dispatcher = _RetiringDispatcher()
    tab.standalone_controller = controller  # type: ignore[assignment]
    tab.standalone_live_stroke_dispatcher = dispatcher  # type: ignore[assignment]
    tab.current_undo_count = 1
    tab.workspace_stack.setCurrentWidget(tab.standalone_workspace)
    tab._sync_state()
    close_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorCloseSessionButton")

    assert close_button is not None
    assert close_button.isEnabled()
    with patch(
        "cdmw.ui.mesh_editor.tab.QMessageBox.question",
        side_effect=(QMessageBox.No, QMessageBox.Yes),
    ) as question:
        close_button.click()
        assert tab.standalone_controller is controller
        assert tab.workspace_stack.currentWidget() is tab.standalone_workspace

        started = time.perf_counter()
        close_button.click()
        elapsed = time.perf_counter() - started

    assert question.call_count == 2
    assert elapsed < 0.05
    assert tab.standalone_controller is None
    assert tab.workspace_stack.currentWidget() is tab.empty_state
    assert dispatcher.cancelled
    assert dispatcher.retired == [controller]
    assert not controller.close_called
    tab.standalone_live_stroke_dispatcher = None
    tab.deleteLater()
    app.processEvents()


def test_delete_later_stops_owned_worker_before_qt_destroys_its_thread() -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings("CDMWTests", "MeshEditorDestroyedWorkerGuard")
    settings.clear()
    tab = MeshEditorTab(settings=settings)
    worker = _StopAwareWorker()
    thread = QThread(tab)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit, Qt.DirectConnection)
    tab.standalone_action_worker = worker
    tab.standalone_action_thread = thread
    thread.start()
    assert thread.isRunning()

    tab.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()

    assert worker.stop_event.is_set()
    try:
        assert not thread.isRunning() or thread.parent() is None
    except RuntimeError:
        pass


def test_geometry_layer_close_defers_dialog_disposal_until_background_save_finishes() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = _MeshEditorSaveAwareDialog()
    saved: list[bool] = []

    def save(_force_without_saving: bool) -> None:
        time.sleep(0.2)

    dialog.configureMeshEditorClose(save, lambda: saved.append(True))
    dialog.show()
    app.processEvents()

    started = time.perf_counter()
    dialog.done(QDialog.Rejected)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.05
    assert dialog.isVisible()
    deadline = time.perf_counter() + 2.0
    while time.perf_counter() < deadline and not saved:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert saved == [True]
    assert not dialog.isVisible()
    dialog.deleteLater()
    app.processEvents()


def test_closing_a_session_retires_the_ids_queued_completions_are_matched_against() -> None:
    """Cancelling a worker cannot recall a result already queued on the event loop.

    Teardown stopped the action and rebuild workers but left their request ids intact,
    so a completion emitted just before the cancel still matched and was published --
    through whichever controller was current by then. An operation started on one mesh
    could refresh the next one with an incompatible native payload.
    """

    app = QApplication.instance() or QApplication([])
    settings = QSettings("CDMWTests", "MeshEditorStaleCompletion")
    settings.clear()
    tab = MeshEditorTab(settings=settings)
    tab.standalone_action_request_id = 7
    tab.standalone_rebuild_report_request_id = 4
    in_flight_action = tab.standalone_action_request_id
    in_flight_rebuild = tab.standalone_rebuild_report_request_id

    tab.close_standalone_session()

    assert tab.standalone_action_request_id != in_flight_action
    assert tab.standalone_rebuild_report_request_id != in_flight_rebuild

    # The late result now fails the id check and never reaches a controller.
    published: list[object] = []
    tab.standalone_action_controller = object()  # type: ignore[assignment]
    tab._finish_standalone_action_execution = lambda *a, **k: published.append(a)  # type: ignore[assignment]
    tab._handle_standalone_action_completed(in_flight_action, object())

    assert published == []
    tab.deleteLater()
    app.processEvents()


def test_a_finished_rebuild_report_survives_an_unrelated_selection_refresh() -> None:
    """Selecting a different part used to destroy a valid rebuild report.

    Every `update_editor_session_state` cleared it, and part selection goes through
    that path -- so a finished report could no longer be inspected, previewed or
    packaged after a click that changed no geometry. Only a geometry command moves
    `MeshEditSessionView.revision`, which is what now decides staleness.
    """

    from cdmw.domain.mesh import MeshEditSelection, MeshEditSessionView

    def _view(revision: int) -> MeshEditSessionView:
        return MeshEditSessionView(
            session_id="session-a",
            mode="object",
            revision=revision,
            selection=MeshEditSelection(),
            submesh_count=1,
            vertex_count=8,
            face_count=12,
        )

    app = QApplication.instance() or QApplication([])
    settings = QSettings("CDMWTests", "MeshEditorRebuildReportRetention")
    settings.clear()
    tab = MeshEditorTab(settings=settings)
    report = object()
    tab.standalone_last_rebuild_report = report
    tab.standalone_rebuild_report_revision = 4

    tab.update_editor_session_state(_view(4))
    assert tab.standalone_last_rebuild_report is report

    tab.update_editor_session_state(_view(5))
    assert tab.standalone_last_rebuild_report is report
    assert tab.standalone_rebuild_report_revision == 4

    # A session that has gone away clears it too.
    tab.standalone_last_rebuild_report = report
    tab.standalone_rebuild_report_revision = 6
    tab.update_editor_session_state(None)
    assert tab.standalone_last_rebuild_report is None

    tab.deleteLater()
    app.processEvents()
