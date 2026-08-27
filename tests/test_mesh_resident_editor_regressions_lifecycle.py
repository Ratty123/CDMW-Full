"""Resident editor regressions: the lifecycle half.

Split from test_mesh_resident_editor_regressions to keep both files inside
the owned-file line cap. Same TestCase shape and the same imports; these are
the cases about finishing, timing out, and tearing the resident editor down.
"""

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


class MeshResidentEditorLifecycleRegressionTests(unittest.TestCase):
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

    def test_failed_terminal_selection_enqueue_rejects_provisional_authority(self) -> None:
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorSelectionEnqueueFailure"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_controller = builder.controller
        tab.standalone_dotnet_update_ack_start_timer.stop()
        recorded: list[tuple[str, dict[str, object]]] = []
        sent: list[dict[str, object]] = []
        tab.standalone_dotnet_update_queue = SimpleNamespace(
            enqueue=lambda _revision, _packets: False,
            metrics=lambda: {"recovery_failed": True},
        )
        tab._record_mesh_dotnet_event = (  # type: ignore[method-assign]
            lambda event, **payload: recorded.append((event, dict(payload)))
        )

        with patch.object(
            tab,
            "_send_dotnet_protocol_message",
            side_effect=lambda payload: sent.append(dict(payload)) or True,
        ):
            published = tab._send_dotnet_native_update(
                MeshEditorNativeUpdate(
                    refresh_selection=True,
                    session_view=builder.controller.session_view(),
                ),
                result=MeshEditResult(action="select", status="ok", revision=0),
                request_payload={
                    "event": "select_request",
                    "session_id": builder.controller.session_view().session_id,
                    "request_id": 55,
                    "base_revision": 0,
                    "process_generation": 7,
                    "protocol_version": 2,
                },
            )

        self.assertFalse(published)
        self.assertFalse(tab.standalone_dotnet_update_ack_start_timer.isActive())
        self.assertEqual("mesh_dotnet_native_update_enqueue_failed", recorded[0][0])
        self.assertEqual(55, recorded[0][1]["request_id"])
        self.assertEqual(1, len(sent))
        self.assertEqual("command_result", sent[0]["event"])
        self.assertEqual("error", sent[0]["status"])
        self.assertFalse(sent[0]["ok"])
        self.assertEqual(55, sent[0]["request_id"])
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
        tab.standalone_dotnet_target_embedded = True
        tab.standalone_dotnet_target_controller = builder.controller
        tab.standalone_dotnet_lifecycle_session_id = "right-workspace-session"
        authoring_controller = tab._active_shared_dotnet_controller()
        assert authoring_controller is not None
        sent: list[tuple[str, dict[str, object]]] = []

        def send_correlated(event: str, payload: object) -> int:
            sent.append((event, dict(payload)))
            return len(sent)

        with patch.object(authoring_controller, "send_correlated", side_effect=send_correlated):
            tab._set_embedded_dotnet_state("ready", active=True)
            # Both Mesh View controls are driven from the shared display-mode
            # table, so select by mode rather than by label text.
            display_combo.setCurrentIndex(display_combo.findData("wire"))
            display_combo.setCurrentIndex(display_combo.findData("untextured_faces"))
            _APP.processEvents()
            self.assertTrue(tab._publish_dotnet_presentation_state())

        self.assertTrue(display_combo.isEnabled())
        self.assertEqual("presentation_state_update", sent[-1][0])
        self.assertEqual("untextured_faces", sent[-1][1]["display"]["mode"])
        self.assertEqual(len(sent), tab.standalone_dotnet_presentation_request_id)

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
