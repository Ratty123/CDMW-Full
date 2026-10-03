from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QFrame, QPushButton, QTreeWidget, QTreeWidgetItem

from cdmw.domain.mesh import MeshEditCommand, MeshEditResult, MeshEditSelection
from cdmw.modding.mesh_native_core import native_mesh_core_available
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.services.mesh_service import MeshService
from cdmw.ui.archive_browser.static_replacement_dialog_prompt_shell import (
    _EmbeddedAlignmentBuilderDialog,
)
from cdmw.ui.mesh_editor import MeshEditorTab
from cdmw.ui.mesh_editor.controller import MeshEditorController, MeshEditorNativeUpdate
from cdmw.ui.mesh_editor.dotnet_update_queue import (
    MESH_EDIT_REVISION_CAPABILITY,
    MESH_MUTATION_ENVELOPE_CAPABILITY,
    DotNetRevisionUpdateQueue,
)
from cdmw.ui.mesh_editor.tab_dotnet_process import MeshEditorDotNetProcessMixin
from cdmw.ui.mesh_editor.tab_shell import MeshEditorTabShellMixin
from cdmw.ui.mesh_editor.static_replacement_adapter import StaticReplacementMeshEditSession
from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace
from tests.test_mesh_editor_action_bar import (
    _EmbeddedMeshBuilder,
    _FakeProcess,
    _install_shared_dotnet_test_process,
)
from tests.test_mesh_service_editing import _quad_mesh


_APP = QApplication.instance() or QApplication([])


class MeshResidentEditorRegressionTests(unittest.TestCase):
    def test_shared_process_generation_recontexts_resident_update_queue(self) -> None:
        sent: list[dict[str, object]] = []
        queue = DotNetRevisionUpdateQueue(
            lambda payload: not sent.append(dict(payload))
        )
        queue.set_context(session_id="mesh-session", process_generation=1)
        queue.observe_capabilities(
            {
                "capabilities": [
                    MESH_EDIT_REVISION_CAPABILITY,
                    MESH_MUTATION_ENVELOPE_CAPABILITY,
                ]
            }
        )
        self.assertTrue(
            queue.enqueue(1, ({"event": "preview_vertex_update"},))
        )
        self.assertEqual(1, queue.metrics()["active_revision"])

        harness = SimpleNamespace(
            standalone_dotnet_editor_process=None,
            standalone_dotnet_process_generation=1,
            standalone_dotnet_lifecycle_session_id="mesh-session",
            standalone_dotnet_update_queue=queue,
            standalone_dotnet_lifecycle_counts={
                "renderer_process_start_count": 1,
                "process_restart_count": 0,
            },
            _record_mesh_dotnet_event=lambda *args, **kwargs: None,
            _dotnet_process_event_payload=lambda process: {},
        )
        process = object()
        controller = SimpleNamespace(
            process=process,
            process_generation=2,
            capabilities=(
                MESH_EDIT_REVISION_CAPABILITY,
                MESH_MUTATION_ENVELOPE_CAPABILITY,
            ),
        )

        MeshEditorTabShellMixin._sync_shared_dotnet_process_identity(
            harness,
            controller,
        )

        self.assertIs(process, harness.standalone_dotnet_editor_process)
        self.assertEqual(2, harness.standalone_dotnet_process_generation)
        self.assertEqual(0, queue.metrics()["active_revision"])
        self.assertTrue(queue.metrics()["revision_ack_capable"])
        self.assertTrue(queue.metrics()["correlated_ack_capable"])
        self.assertTrue(
            queue.enqueue(2, ({"event": "preview_vertex_update"},))
        )
        self.assertEqual(2, sent[-1]["process_generation"])

    def test_same_process_session_handoff_keeps_revision_pacing_capable(self) -> None:
        sent: list[dict[str, object]] = []
        queue = DotNetRevisionUpdateQueue(
            lambda payload: not sent.append(dict(payload))
        )
        queue.set_context(session_id="prewarm-session", process_generation=2)
        queue.observe_capabilities(
            {
                "capabilities": [
                    MESH_EDIT_REVISION_CAPABILITY,
                    MESH_MUTATION_ENVELOPE_CAPABILITY,
                ]
            }
        )
        process = object()
        harness = SimpleNamespace(
            standalone_dotnet_editor_process=process,
            standalone_dotnet_process_generation=2,
            standalone_dotnet_lifecycle_session_id="mesh-session",
            standalone_dotnet_update_queue=queue,
            standalone_dotnet_lifecycle_counts={
                "renderer_process_start_count": 1,
                "process_restart_count": 0,
            },
            _record_mesh_dotnet_event=lambda *args, **kwargs: None,
            _dotnet_process_event_payload=lambda current: {},
        )
        controller = SimpleNamespace(
            process=process,
            process_generation=2,
            capabilities=(
                MESH_EDIT_REVISION_CAPABILITY,
                MESH_MUTATION_ENVELOPE_CAPABILITY,
            ),
        )

        MeshEditorTabShellMixin._sync_shared_dotnet_process_identity(
            harness,
            controller,
        )

        self.assertTrue(queue.metrics()["revision_ack_capable"])
        self.assertTrue(queue.metrics()["correlated_ack_capable"])
        self.assertTrue(
            queue.enqueue(1, ({"event": "preview_vertex_update"},))
        )
        self.assertEqual("mesh-session", sent[-1]["session_id"])
        self.assertEqual(1, queue.metrics()["active_revision"])

    def test_same_process_empty_lifecycle_signal_preserves_acked_revision(self) -> None:
        queue = DotNetRevisionUpdateQueue(lambda _payload: True)
        queue.set_context(
            session_id="mesh-session",
            process_generation=2,
            renderer_revision=5,
        )
        process = object()
        harness = SimpleNamespace(
            standalone_dotnet_editor_process=process,
            standalone_dotnet_process_generation=2,
            standalone_dotnet_lifecycle_session_id="",
            standalone_dotnet_update_queue=queue,
            standalone_dotnet_lifecycle_counts={
                "renderer_process_start_count": 1,
                "process_restart_count": 0,
            },
            _record_mesh_dotnet_event=lambda *args, **kwargs: None,
            _dotnet_process_event_payload=lambda current: {},
        )
        controller = SimpleNamespace(
            process=process,
            process_generation=2,
            capabilities=(
                MESH_EDIT_REVISION_CAPABILITY,
                MESH_MUTATION_ENVELOPE_CAPABILITY,
            ),
        )

        MeshEditorTabShellMixin._sync_shared_dotnet_process_identity(
            harness,
            controller,
        )

        self.assertEqual(5, queue.metrics()["last_acked_revision"])
        self.assertTrue(queue.metrics()["revision_ack_capable"])

    def test_protocol_routes_applied_resync_ack_back_to_update_queue(self) -> None:
        tab = MeshEditorTab(
            settings=QSettings("CDMWTests", "MeshEditorResyncAckRouting")
        )
        sent: list[dict[str, object]] = []
        queue = DotNetRevisionUpdateQueue(
            lambda payload: not sent.append(dict(payload)),
            resync_packets=lambda: (
                {"event": "resident_state_resync", "snapshot": "authoritative"},
            ),
        )
        queue.set_context(session_id="mesh-session", process_generation=2)
        queue.observe_capabilities(
            {
                "capabilities": [
                    MESH_EDIT_REVISION_CAPABILITY,
                    MESH_MUTATION_ENVELOPE_CAPABILITY,
                ]
            }
        )
        tab.standalone_dotnet_update_queue = queue
        try:
            self.assertTrue(
                queue.enqueue(5, ({"event": "preview_vertex_update"},))
            )
            rejected = {
                "event": "preview_vertex_update_ack",
                "session_id": sent[-1]["session_id"],
                "request_id": sent[-1]["request_id"],
                "process_generation": sent[-1]["process_generation"],
                "edit_revision": sent[-1]["edit_revision"],
                "status": "rejected",
                "capabilities": [
                    MESH_EDIT_REVISION_CAPABILITY,
                    MESH_MUTATION_ENVELOPE_CAPABILITY,
                ],
            }
            self.assertTrue(tab._handle_dotnet_protocol_event(rejected))
            self.assertEqual("resident_state_resync", sent[-1]["event"])
            self.assertTrue(queue.metrics()["resync_active"])

            applied = {
                **rejected,
                "event": "resident_state_resync_ack",
                "session_id": sent[-1]["session_id"],
                "request_id": sent[-1]["request_id"],
                "process_generation": sent[-1]["process_generation"],
                "edit_revision": sent[-1]["edit_revision"],
                "status": "applied",
            }
            self.assertTrue(tab._handle_dotnet_protocol_event(applied))
            self.assertFalse(queue.metrics()["resync_active"])
            self.assertFalse(queue.metrics()["recovery_failed"])

            self.assertTrue(
                queue.enqueue(6, ({"event": "preview_vertex_update"},))
            )
            self.assertEqual(6, sent[-1]["edit_revision"])
            self.assertTrue(
                tab._handle_dotnet_protocol_event(
                    {
                        **applied,
                        "event": "preview_vertex_update_ack",
                        "session_id": sent[-1]["session_id"],
                        "request_id": sent[-1]["request_id"],
                        "process_generation": sent[-1]["process_generation"],
                        "edit_revision": sent[-1]["edit_revision"],
                    }
                )
            )
            self.assertEqual(6, queue.metrics()["last_acked_revision"])
        finally:
            tab.standalone_dotnet_update_ack_timer.stop()
            tab.deleteLater()

    def test_completed_dotnet_worker_handoff_accepts_the_next_correlated_command(self) -> None:
        class _Harness(MeshEditorDotNetProcessMixin):
            pass

        harness = _Harness()
        harness.standalone_action_thread = object()
        harness.standalone_action_worker = object()
        harness.standalone_action_request_id = 7
        harness.standalone_action_finished_request_id = 6
        harness.standalone_action_dotnet_command = "morph_author_definition"
        self.assertTrue(harness._standalone_action_worker_active())

        harness.standalone_action_finished_request_id = 7
        self.assertFalse(harness._standalone_action_worker_active())

        harness.standalone_action_dotnet_command = ""
        self.assertTrue(harness._standalone_action_worker_active())

    def test_stale_action_cleanup_cannot_touch_the_successor_worker(self) -> None:
        class _Progress:
            def __init__(self) -> None:
                self.closed = 0
                self.deleted = 0

            def close(self) -> None:
                self.closed += 1

            def deleteLater(self) -> None:
                self.deleted += 1

        class _Harness(MeshEditorDotNetProcessMixin):
            pass

        harness = _Harness()
        old_thread = object()
        old_worker = object()
        new_thread = object()
        new_worker = object()
        progress = _Progress()
        calls: list[str] = []
        harness.standalone_action_thread = new_thread
        harness.standalone_action_worker = new_worker
        harness.standalone_action_progress = progress
        harness.standalone_action_text = "Select All"
        harness.standalone_action_controller = object()
        harness.standalone_action_dotnet_command = "select_all"
        harness.standalone_action_dotnet_request_payload = {"request_id": 8}
        harness.current_selection_empty = False
        harness.update_editor_action_state = lambda **_kwargs: calls.append("update")
        harness._standalone_dotnet_editor_process_running = lambda: True
        harness._send_dotnet_session_state = lambda: calls.append("session") or True
        harness._complete_pending_dotnet_exit = lambda: calls.append("exit")
        harness._retry_pending_dotnet_finish = lambda: calls.append("finish")

        harness._cleanup_standalone_action_worker(old_thread, old_worker)

        self.assertIs(new_thread, harness.standalone_action_thread)
        self.assertIs(new_worker, harness.standalone_action_worker)
        self.assertIs(progress, harness.standalone_action_progress)
        self.assertEqual([], calls)
        self.assertEqual((0, 0), (progress.closed, progress.deleted))

        harness._cleanup_standalone_action_worker(new_thread, new_worker)
        self.assertIsNone(harness.standalone_action_thread)
        self.assertIsNone(harness.standalone_action_worker)
        self.assertIsNone(harness.standalone_action_progress)
        self.assertEqual(["update", "exit", "finish"], calls)
        self.assertEqual((1, 1), (progress.closed, progress.deleted))

        harness._cleanup_standalone_action_worker(old_thread, old_worker)
        self.assertEqual(["update", "exit", "finish"], calls)
        self.assertEqual((1, 1), (progress.closed, progress.deleted))

    def test_embedded_builder_escape_does_not_close_the_workflow(self) -> None:
        host = QFrame()
        host.show()
        dialog = _EmbeddedAlignmentBuilderDialog(host)
        dialog.setWindowFlags(Qt.Widget)
        finished: list[int] = []
        dialog.finished.connect(finished.append)
        dialog.show()
        _APP.processEvents()

        QTest.keyClick(dialog, Qt.Key_Escape)
        _APP.processEvents()

        self.assertTrue(dialog.isVisible())
        self.assertEqual([], finished)
        dialog.reject()
        _APP.processEvents()
        self.assertEqual([0], finished)
        host.deleteLater()

    def test_state_sync_drops_deleted_embedded_button(self) -> None:
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorDeletedEmbeddedButton"))
        button = QPushButton(tab)
        tab.embedded_dotnet_editor_button = button
        button.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        tab._sync_state()

        self.assertIsNone(tab.embedded_dotnet_editor_button)
        tab.deleteLater()

    def test_embedded_preview_loading_tracks_resident_activation(self) -> None:
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorPreviewLoading"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        updates: list[tuple[bool, str, str]] = []
        builder._mesh_editor_embedded_set_preview_loading = (  # type: ignore[attr-defined]
            lambda active, message, *, detail="": updates.append(
                (bool(active), str(message), str(detail))
            )
        )
        tab.standalone_dotnet_target_embedded = True

        tab._set_embedded_dotnet_preview_loading(
            True,
            "Preparing Mesh Editor geometry...",
            detail="background",
        )
        with (
            patch.object(tab, "_notify_embedded_dotnet_ready"),
            patch.object(tab, "_send_dotnet_session_state"),
            patch.object(tab, "_send_dotnet_scene_state", return_value=True),
            patch.object(tab, "_sync_embedded_builder_presentation_state"),
        ):
            self.assertTrue(tab._handle_dotnet_lifecycle_event({}, "activated"))

        self.assertEqual(
            (True, "Preparing Mesh Editor geometry...", "background"),
            updates[0],
        )
        self.assertEqual((False, "Preview ready.", ""), updates[-1])
        tab.deleteLater()
        builder.deleteLater()
        _APP.processEvents()

    def test_embedded_finish_cannot_report_saved_without_builder_shell_finalizer(self) -> None:
        settings = QSettings("CDMWTests", "MeshEditorResidentFinishMissingFinalizer")
        settings.clear()
        tab = MeshEditorTab(settings=settings)
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        builder._mesh_editor_embedded_finalize_dotnet_import = None  # type: ignore[method-assign]

        self.assertFalse(tab._finalize_embedded_dotnet_import("dotnet_finish_edit"))

        tab.deleteLater()
        _APP.processEvents()
