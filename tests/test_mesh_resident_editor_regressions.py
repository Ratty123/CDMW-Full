from __future__ import annotations

import json
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

    def test_scene_ack_reapplies_current_builder_preview_mode(self) -> None:
        settings = QSettings("CDMWTests", "MeshEditorResidentPreviewModeRestore")
        settings.clear()
        tab = MeshEditorTab(settings=settings)
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        builder._mesh_editor_embedded_presentation_state = lambda: {  # type: ignore[attr-defined]
            "active_view": "comparison",
            "comparison_mode": "side_by_side",
        }
        tab.standalone_dotnet_target_embedded = True
        tab.standalone_dotnet_target_controller = builder.controller
        process = _FakeProcess()
        process._state = process.Running
        _install_shared_dotnet_test_process(tab, process, generation=7)
        tab._set_embedded_dotnet_state("ready", active=True)
        tab.standalone_dotnet_presentation_desired = {
            "active_view": "editable",
            "comparison_mode": "replacement_only",
        }
        session_id = builder.controller.session_view().session_id
        tab.standalone_dotnet_scene_pending = {
            "session_id": session_id,
            "request_id": 21,
            "process_generation": 7,
            "source_identity": "resident-preview-source",
            "scene_generation": 4,
        }
        acknowledgement = {
            "event": "scene_state_update_ack",
            "status": "applied",
            "session_id": session_id,
            "request_id": 21,
            "process_generation": 7,
            "source_identity": "resident-preview-source",
            "scene_generation": 4,
        }

        self.assertTrue(tab._handle_dotnet_protocol_event(acknowledgement))

        messages = [
            json.loads(raw.decode("utf-8"))
            for raw in process.stdin_writes
        ]
        presentation = next(
            message
            for message in reversed(messages)
            if message.get("event") == "presentation_state_update"
        )
        self.assertEqual("comparison", presentation["active_view"])
        self.assertEqual("side_by_side", presentation["comparison_mode"])
        tab.standalone_dotnet_editor_process = None
        tab.deleteLater()
        _APP.processEvents()

    def test_embedded_finish_keeps_resident_helper_active(self) -> None:
        settings = QSettings("CDMWTests", "MeshEditorResidentFinish")
        settings.clear()
        tab = MeshEditorTab(settings=settings)
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        builder._mesh_editor_embedded_placement_comparison_mode = lambda: "original_only"  # type: ignore[attr-defined]
        tab.standalone_dotnet_target_embedded = True
        tab.standalone_dotnet_target_controller = builder.controller
        process = _FakeProcess()
        process._state = process.Running
        _install_shared_dotnet_test_process(tab, process, generation=9)
        tab._set_embedded_dotnet_state("ready", active=True)
        session_id = builder.controller.active_session_id
        # The renderer request is already correlated to the controller and is
        # fresher than a lifecycle cache that can lag during reactivation.
        tab.standalone_dotnet_lifecycle_session_id = "stale-host-session"
        tab.standalone_dotnet_scene_frame = None
        tab.standalone_dotnet_scene_candidate = None
        tab.standalone_dotnet_scene_thread = object()  # exact captured state: frame worker still active
        tab.standalone_dotnet_experiment_package = SimpleNamespace(scene_frame=None)
        request = {
            "event": "save_request",
            "session_id": session_id,
            "request_id": 12,
            "base_revision": builder.controller.session_view().revision,
            "process_generation": 9,
            "protocol_version": 2,
            "source_identity": "resident-finish-source",
        }

        self.assertTrue(tab._handle_dotnet_protocol_event(request))
        messages = [json.loads(raw.decode("utf-8")) for raw in process.stdin_writes]
        scene_transition = next(
            message for message in messages if message.get("event") == "scene_state_update"
        )
        self.assertEqual(session_id, scene_transition["session_id"])
        self.assertEqual("placement", scene_transition["interaction_mode"])
        self.assertEqual("original_only", scene_transition["comparison_mode"])
        self.assertNotIn("roles", scene_transition)
        self.assertEqual([], builder.finalized_dotnet_imports)
        self.assertNotIn(b'"event":"command_result"', b"".join(process.stdin_writes))

        acknowledgement = {
            "event": "scene_state_update_ack",
            "status": "applied",
            "session_id": scene_transition["session_id"],
            "request_id": scene_transition["request_id"],
            "process_generation": scene_transition["process_generation"],
            "source_identity": scene_transition["source_identity"],
            "scene_generation": scene_transition["scene_generation"],
        }
        self.assertTrue(tab._handle_dotnet_protocol_event(acknowledgement))

        self.assertEqual(["dotnet_finish_edit"], builder.finalized_dotnet_imports)
        self.assertIs(process, tab.standalone_dotnet_editor_process)
        self.assertEqual("ready", tab.standalone_dotnet_embedded_state)
        self.assertTrue(getattr(builder, "_mesh_editor_embedded_dotnet_active", False))
        writes = b"".join(process.stdin_writes)
        self.assertNotIn(b'"event":"deactivate_request"', writes)
        self.assertIn(b'"event":"command_result"', writes)
        self.assertIn(b'"status":"saved"', writes)
        self.assertIn(b'"request_id":12', writes)
        self.assertIsNone(tab.standalone_dotnet_finish_scene_pending)
        tab.standalone_dotnet_scene_thread = None
        tab.standalone_dotnet_editor_process = None
        tab.deleteLater()
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

    def test_embedded_finish_rejects_busy_live_stroke_without_mode_change(self) -> None:
        settings = QSettings("CDMWTests", "MeshEditorResidentFinishBusyStroke")
        settings.clear()
        tab = MeshEditorTab(settings=settings)
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_embedded = True
        tab.standalone_dotnet_target_controller = builder.controller
        process = _FakeProcess()
        process._state = process.Running
        _install_shared_dotnet_test_process(tab, process, generation=10)
        tab.standalone_live_stroke_dispatcher = SimpleNamespace(
            metrics=lambda: {"active": 1, "control_depth": 0, "queue_depth": 1}
        )
        scene_transitions: list[dict[str, object]] = []
        tab._send_dotnet_scene_state = lambda **payload: scene_transitions.append(  # type: ignore[method-assign]
            dict(payload)
        ) or True
        request = {
            "event": "save_request",
            "session_id": builder.controller.active_session_id,
            "request_id": 13,
            "base_revision": builder.controller.session_view().revision,
            "process_generation": 10,
            "protocol_version": 2,
        }

        self.assertTrue(tab._handle_dotnet_protocol_event(request))
        self.assertEqual([], scene_transitions)
        self.assertEqual([], builder.finalized_dotnet_imports)
        writes = b"".join(process.stdin_writes)
        self.assertNotIn(b'"event":"deactivate_request"', writes)
        self.assertIn(b'"event":"command_result"', writes)
        self.assertIn(b'"status":"busy"', writes)
        self.assertIn(b'"request_id":13', writes)

        process.stdin_writes.clear()
        tab.standalone_live_stroke_dispatcher = SimpleNamespace(
            metrics=lambda: {"active": 0, "control_depth": 0, "queue_depth": 0}
        )
        tab.standalone_native_mesh_edit_stroke_id = "awaiting-qt-completion"
        request["request_id"] = 14

        self.assertTrue(tab._handle_dotnet_protocol_event(request))
        self.assertEqual([], scene_transitions)
        self.assertEqual([], builder.finalized_dotnet_imports)
        writes = b"".join(process.stdin_writes)
        self.assertNotIn(b'"event":"deactivate_request"', writes)
        self.assertIn(b'"status":"busy"', writes)
        self.assertIn(b'"request_id":14', writes)
        tab.standalone_native_mesh_edit_stroke_id = ""
        tab.standalone_live_stroke_dispatcher = None
        tab.standalone_dotnet_editor_process = None
        tab.deleteLater()
        _APP.processEvents()

    def test_embedded_finish_timeout_keeps_edit_mesh_open_and_reports_the_request(self) -> None:
        settings = QSettings("CDMWTests", "MeshEditorResidentFinishTimeout")
        settings.clear()
        tab = MeshEditorTab(settings=settings)
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_embedded = True
        tab.standalone_dotnet_target_controller = builder.controller
        process = _FakeProcess()
        process._state = process.Running
        _install_shared_dotnet_test_process(tab, process, generation=11)
        tab._set_embedded_dotnet_state("ready", active=True)
        session_id = builder.controller.active_session_id
        tab.standalone_dotnet_lifecycle_session_id = session_id
        tab.standalone_dotnet_scene_frame = None
        tab.standalone_dotnet_scene_candidate = None
        tab.standalone_dotnet_scene_thread = object()
        tab.standalone_dotnet_experiment_package = SimpleNamespace(
            scene_frame=SimpleNamespace(source_identity="resident-timeout-source")
        )
        request = {
            "event": "save_request",
            "session_id": session_id,
            "request_id": 15,
            "base_revision": builder.controller.session_view().revision,
            "process_generation": 11,
            "protocol_version": 2,
        }

        self.assertTrue(tab._handle_dotnet_protocol_event(request))
        self.assertTrue(tab.standalone_dotnet_finish_scene_timer.isActive())
        tab._handle_dotnet_finish_scene_timeout()

        self.assertEqual([], builder.finalized_dotnet_imports)
        self.assertIsNone(tab.standalone_dotnet_finish_scene_pending)
        self.assertIsNone(tab.standalone_dotnet_scene_pending)
        self.assertFalse(tab.standalone_dotnet_finish_scene_timer.isActive())
        writes = b"".join(process.stdin_writes)
        self.assertIn(b'"event":"command_result"', writes)
        self.assertIn(b'"status":"error"', writes)
        self.assertIn(b'"request_id":15', writes)
        self.assertIn(b"not acknowledged within 5 seconds", writes)
        tab.standalone_dotnet_scene_thread = None
        tab.standalone_dotnet_editor_process = None
        tab.deleteLater()
        builder.deleteLater()
        _APP.processEvents()

    def test_static_replacement_exit_adopts_hydrated_mesh_without_redundant_clone(self) -> None:
        authoritative_mesh = _quad_mesh(two_parts=True)
        clone_requests: list[bool] = []
        controller = SimpleNamespace(
            working_mesh=lambda *, clone: clone_requests.append(bool(clone)) or authoritative_mesh
        )
        session = StaticReplacementMeshEditSession(controller=controller)  # type: ignore[arg-type]

        synced = session.sync_working_mesh()

        self.assertIs(authoritative_mesh, synced)
        self.assertIs(authoritative_mesh, session.mesh)
        self.assertEqual([False], clone_requests)

    def test_dotnet_update_timeout_clock_starts_after_command_callback_returns(self) -> None:
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorDeferredUpdateAckTimer"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_controller = builder.controller
        queued: list[tuple[int, tuple[dict[str, object], ...]]] = []
        timer_syncs: list[bool] = []
        tab.standalone_dotnet_update_queue = SimpleNamespace(
            enqueue=lambda revision, packets: queued.append((int(revision), tuple(packets))) or True
        )
        tab._sync_dotnet_update_ack_timer = lambda: timer_syncs.append(True)  # type: ignore[method-assign]

        tab._send_dotnet_native_update(
            MeshEditorNativeUpdate(
                triangle_groups=({"source_submesh_index": 0, "triangles": ()},),
            )
        )

        self.assertEqual(1, len(queued))
        self.assertEqual([], timer_syncs)
        _APP.processEvents()
        self.assertEqual([True], timer_syncs)
        tab.deleteLater()

    def test_terminal_stroke_result_waits_for_correlated_authoritative_geometry(self) -> None:
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorTerminalStrokeGeometry"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_controller = builder.controller
        activity: list[tuple[str, object]] = []
        tab.standalone_dotnet_update_queue = SimpleNamespace(
            enqueue=lambda revision, packets: activity.append(
                ("geometry", (int(revision), tuple(packets)))
            )
            or True
        )

        with patch.object(
            tab,
            "_send_dotnet_protocol_message",
            side_effect=lambda payload: activity.append(("result", dict(payload))) or True,
        ):
            tab._send_dotnet_native_update(
                MeshEditorNativeUpdate(
                    vertex_groups=(
                        {
                            "source_submesh_index": 0,
                            "source_vertex_indices": [0],
                            "positions": [0.0, 0.1, 0.0],
                        },
                    ),
                ),
                result=MeshEditResult(action="grab", status="ok", revision=1),
                request_payload={
                    "event": "stroke_end",
                    "session_id": builder.controller.session_view().session_id,
                    "request_id": 42,
                    "base_revision": 0,
                    "process_generation": 7,
                    "protocol_version": 2,
                },
            )

        self.assertEqual(["geometry", "result"], [kind for kind, _payload in activity])
        queued = activity[0][1]
        assert isinstance(queued, tuple)
        self.assertEqual(42, queued[1][0]["request_id"])
        command_result = activity[1][1]
        assert isinstance(command_result, dict)
        self.assertTrue(command_result["authoritative_geometry_pending"])
        self.assertEqual(42, command_result["request_id"])
        tab.deleteLater()
        builder.deleteLater()

    def test_successful_part_command_uses_current_controller_for_result_revision(self) -> None:
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorPartCommandControllerHandoff"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        old_controller = builder.controller
        replacement = MeshEditorController()
        replacement.open_mesh(
            old_controller.working_mesh(clone=True),
            session_id="embedded-builder",
            mode="edit",
        )
        tab.standalone_dotnet_target_embedded = True
        tab.standalone_dotnet_target_controller = old_controller
        results: list[dict[str, object]] = []

        def replace_controller(_command: str, _indices: tuple[int, ...]) -> bool:
            old_controller.close_active_session()
            tab.standalone_dotnet_target_controller = replacement
            return True

        builder._mesh_editor_embedded_run_part_action = replace_controller  # type: ignore[method-assign]
        with (
            patch.object(tab, "_refresh_embedded_workspace_from_builder"),
            patch.object(
                tab,
                "_send_dotnet_command_result",
                side_effect=lambda command, **payload: results.append({"command": command, **payload}) or True,
            ),
        ):
            self.assertTrue(
                tab._handle_dotnet_command_request(
                    {
                        "event": "command_request",
                        "command": "delete",
                        "target_mode": "source",
                        "local_selection": {"source_indices": [0]},
                    }
                )
            )

        self.assertEqual("applied", results[-1]["status"])
        self.assertTrue(results[-1]["ok"])
        self.assertEqual(replacement.session_view().revision, results[-1]["revision"])
        replacement.close_active_session()
        tab.deleteLater()

    def test_embedded_dotnet_edit_uses_right_workspace_and_restores_previous_tab(self) -> None:
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorEmbeddedRightWorkspace"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        workspace = builder.tabs.findChild(QFrame, "MeshEditorEmbeddedMergedWorkspace")
        display_combo = builder.tabs.findChild(QComboBox, "MeshEditorViewportDisplayCombo")
        assert workspace is not None
        assert display_combo is not None
        show_controls = getattr(builder, "_mesh_editor_embedded_set_controls_visible")

        show_controls(True)

        advanced_index = builder.tabs.indexOf(workspace)
        self.assertTrue(builder.tabs.isTabVisible(advanced_index))
        self.assertIs(builder.tabs.currentWidget(), workspace)
        self.assertFalse(display_combo.isEnabled())

        tab.standalone_dotnet_capabilities.add("viewport_display_modes_v1")
        tab.standalone_dotnet_lifecycle_session_id = "right-workspace-session"
        sent: list[dict[str, object]] = []
        with patch.object(tab, "_send_dotnet_protocol_message", side_effect=lambda payload: sent.append(dict(payload)) or True):
            tab._set_embedded_dotnet_state("ready", active=True)
            # Both Mesh View controls are driven from the shared display-mode
            # table, so select by mode rather than by label text.
            display_combo.setCurrentIndex(display_combo.findData("wire"))
            sent.clear()
            display_combo.setCurrentIndex(display_combo.findData("untextured_faces"))
            _APP.processEvents()

        self.assertTrue(display_combo.isEnabled())
        self.assertEqual(
            {
                "event": "viewport_display_update",
                "session_id": "right-workspace-session",
                "request_id": 2,
                "process_generation": 0,
                "protocol_version": 2,
                "mode": "untextured_faces",
            },
            sent[-1],
        )

        show_controls(False)

        self.assertFalse(builder.tabs.isTabVisible(advanced_index))
        self.assertEqual("Setup", builder.tabs.tabText(builder.tabs.currentIndex()))
        _APP.processEvents()
        tab.deleteLater()

    def test_dotnet_move_rejects_explicit_empty_selection_instead_of_reusing_resident_parts(self) -> None:
        settings = QSettings("CDMWTests", "MeshEditorDotNetExplicitEmptySelection")
        settings.clear()
        tab = MeshEditorTab(settings=settings)
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_controller = builder.controller
        builder.controller.select(source_indices=(0,), operation="replace")
        captured: list[MeshEditCommand] = []
        results: list[tuple[tuple[object, ...], dict[str, object]]] = []

        with (
            patch.object(
                tab,
                "_start_dotnet_action_worker",
                side_effect=lambda _controller, command, **_kwargs: captured.append(command) or True,
            ),
            patch.object(
                tab,
                "_send_dotnet_command_result",
                side_effect=lambda *args, **kwargs: results.append((args, kwargs)),
            ),
        ):
            self.assertFalse(
                tab._handle_dotnet_command_request(
                    {
                        "event": "command_request",
                        "command": "transform_move",
                        "delta": [0.25, 0.0, 0.0],
                        "local_selection": {},
                    }
                )
            )

        self.assertEqual([], captured)
        self.assertEqual(1, len(results))
        self.assertEqual("transform_move", results[0][0][0])
        self.assertEqual("no_selection", results[0][1]["status"])
        self.assertIn("Select mesh vertices", results[0][1]["diagnostics"][0])
        self.assertEqual((0,), builder.controller.session_view().selection.source_indices)
        _APP.processEvents()
        tab.deleteLater()

    def test_dotnet_undo_and_redo_run_in_background(self) -> None:
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorDotNetBackgroundHistory"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_controller = builder.controller
        captured: list[MeshEditCommand] = []

        with patch.object(
            tab,
            "_start_dotnet_action_worker",
            side_effect=lambda _controller, command, **_kwargs: captured.append(command) or True,
        ):
            self.assertTrue(tab._handle_dotnet_command_request({"command": "undo"}))
            self.assertTrue(tab._handle_dotnet_command_request({"command": "redo"}))

        self.assertEqual(("undo", "redo"), tuple(command.action for command in captured))
        self.assertEqual(("Undo", "Redo"), tuple(command.label for command in captured))
        _APP.processEvents()
        tab.deleteLater()

    def test_dotnet_undo_is_rejected_until_active_stroke_finishes(self) -> None:
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorDotNetHistoryWaitsForStroke"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_controller = builder.controller
        tab.standalone_native_mesh_edit_stroke_id = "active-stroke"
        results: list[dict[str, object]] = []

        with (
            patch.object(
                tab,
                "_send_dotnet_command_result",
                side_effect=lambda command, **payload: results.append({"command": command, **payload}) or True,
            ),
            patch.object(
                tab,
                "_start_dotnet_action_worker",
                side_effect=AssertionError("undo started before the live stroke completed"),
            ),
        ):
            self.assertTrue(tab._handle_dotnet_command_request({"command": "undo"}))

        self.assertEqual("busy", results[-1]["status"])
        self.assertIn("stroke", results[-1]["diagnostics"][0])
        tab.standalone_native_mesh_edit_stroke_id = ""
        _APP.processEvents()
        tab.deleteLater()

    def test_dotnet_session_state_includes_live_action_history(self) -> None:
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorDotNetActionHistoryPayload"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_controller = builder.controller
        builder.controller.select(source_indices=(0,), operation="replace")
        sent: list[dict[str, object]] = []

        with patch.object(
            tab,
            "_send_dotnet_protocol_message",
            side_effect=lambda payload: sent.append(dict(payload)) or True,
        ):
            self.assertTrue(tab._send_dotnet_session_state())

        self.assertEqual(1, sent[-1]["history_cursor"])
        entries = sent[-1]["history_entries"]
        self.assertIsInstance(entries, list)
        assert isinstance(entries, list)
        self.assertEqual(
            [{"action": "select", "label": "Select", "state": "applied"}],
            entries,
        )
        _APP.processEvents()
        tab.deleteLater()

    def test_compact_selection_session_state_uses_worker_view_without_session_locks(self) -> None:
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorCompactSelectionSessionState"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_controller = builder.controller
        view = builder.controller.session_view()
        sent: list[dict[str, object]] = []

        with (
            patch.object(
                builder.controller,
                "session_view",
                side_effect=AssertionError("compact selection state refetched the session"),
            ),
            patch.object(
                builder.controller,
                "geometry_layer_state",
                side_effect=AssertionError("compact selection state entered the geometry lock"),
            ),
            patch.object(
                tab,
                "_send_dotnet_protocol_message",
                side_effect=lambda payload: sent.append(dict(payload)) or True,
            ),
        ):
            self.assertTrue(
                tab._send_dotnet_session_state(
                    include_selection=False,
                    session_view=view,
                )
            )

        self.assertEqual(1, len(sent))
        self.assertNotIn("selection", sent[0])
        self.assertNotIn("geometry_layers", sent[0])
        _APP.processEvents()
        tab.deleteLater()

    def test_dotnet_select_all_ignores_empty_local_snapshot_and_targets_every_vertex(self) -> None:
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorDotNetSelectAll"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_controller = builder.controller
        captured: list[MeshEditCommand] = []

        with patch.object(
            tab,
            "_start_dotnet_action_worker",
            side_effect=lambda _controller, command, **_kwargs: captured.append(command) or True,
        ):
            self.assertTrue(
                tab._handle_dotnet_command_request(
                    {
                        "event": "command_request",
                        "command": "select_all",
                        "target_mode": "source",
                        "local_selection": {},
                    }
                )
            )

        self.assertEqual(1, len(captured))
        self.assertEqual("all", captured[0].params["operation"])
        self.assertEqual("vertex", captured[0].params["target_mode"])
        assert captured[0].selection is not None
        self.assertTrue(captured[0].selection.is_empty())
        _APP.processEvents()
        tab.deleteLater()

    def test_dotnet_screen_selection_runs_in_background(self) -> None:
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorDotNetBackgroundSelect"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_controller = builder.controller
        captured: list[tuple[MeshEditCommand, str]] = []

        def submit(
            _controller: object,
            command: MeshEditCommand,
            phase: str,
            **_kwargs: object,
        ) -> int:
            captured.append((command, phase))
            return len(captured)

        with (
            patch.object(
                builder.controller,
                "apply",
                side_effect=AssertionError("screen selection ran synchronously on the UI thread"),
            ),
            patch.object(
                tab,
                "_ensure_standalone_live_stroke_dispatcher",
                return_value=SimpleNamespace(submit=submit),
            ),
        ):
            self.assertTrue(
                tab._handle_dotnet_select_request(
                    {
                        "event": "select_request",
                        "phase": "begin",
                        "stroke_id": "background-selection-1",
                        "sequence": 0,
                        "operation": "add",
                        "target_mode": "face",
                    }
                )
            )
            self.assertTrue(
                tab._handle_dotnet_select_request(
                    {
                        "event": "select_request",
                        "phase": "update",
                        "stroke_id": "background-selection-1",
                        "sequence": 1,
                        "operation": "add",
                        "target_mode": "face",
                        "selection_depth_mode": "visible",
                        "screen_brush": {
                            "x": 100.0,
                            "y": 80.0,
                            "radius_pixels": 14.0,
                            "viewport_width": 640.0,
                            "viewport_height": 480.0,
                            "world_view_projection": [1.0] * 16,
                        },
                    }
                )
            )

        self.assertEqual(["begin", "update"], [phase for _command, phase in captured])
        self.assertEqual("select", captured[1][0].action)
        self.assertEqual("add", captured[1][0].params["operation"])
        self.assertEqual("background-selection-1", captured[1][0].params["selection_stroke_id"])
        self.assertIn("_native_screen_selection_payload", captured[1][0].params)
        _APP.processEvents()
        tab.deleteLater()

    def test_dotnet_grow_preserves_vertex_target_without_promoting_parts(self) -> None:
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorDotNetGrowTarget"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_controller = builder.controller
        captured: list[MeshEditCommand] = []

        with patch.object(
            tab,
            "_start_dotnet_action_worker",
            side_effect=lambda _controller, command, **_kwargs: captured.append(command) or True,
        ):
            self.assertTrue(
                tab._handle_dotnet_command_request(
                    {
                        "event": "command_request",
                        "command": "grow",
                        "target_mode": "vertex",
                        "local_selection": {
                            "source_indices": [0],
                            "vertices_by_submesh": {"0": [0]},
                            "faces_by_submesh": {"0": [1]},
                        },
                    }
                )
            )

        self.assertEqual(1, len(captured))
        self.assertEqual("vertex", captured[0].params["target_mode"])
        _APP.processEvents()
        tab.deleteLater()
