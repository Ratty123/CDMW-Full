from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QFrame, QTreeWidget, QTreeWidgetItem

from cdmw.domain.mesh import MeshEditCommand, MeshEditResult, MeshEditSelection
from cdmw.modding.mesh_native_core import native_mesh_core_available
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.services.mesh_service import MeshService
from cdmw.ui.mesh_editor import MeshEditorTab
from cdmw.ui.mesh_editor.controller import MeshEditorController, MeshEditorNativeUpdate
from cdmw.ui.mesh_editor.static_replacement_adapter import StaticReplacementMeshEditSession
from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace
from tests.test_mesh_editor_action_bar import _EmbeddedMeshBuilder, _FakeProcess
from tests.test_mesh_service_editing import _quad_mesh


_APP = QApplication.instance() or QApplication([])


class MeshResidentEditorRegressionTests(unittest.TestCase):
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
        tab.standalone_dotnet_process_generation = 7
        process = _FakeProcess()
        process._state = process.Running
        tab.standalone_dotnet_editor_process = process
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
        tab.standalone_dotnet_process_generation = 9
        process = _FakeProcess()
        process._state = process.Running
        tab.standalone_dotnet_editor_process = process
        tab._set_embedded_dotnet_state("ready", active=True)
        scene_transitions: list[dict[str, object]] = []
        tab._send_dotnet_scene_state = lambda **payload: scene_transitions.append(  # type: ignore[method-assign]
            dict(payload)
        ) or True
        request = {
            "event": "save_request",
            "session_id": builder.controller.active_session_id,
            "request_id": 12,
            "base_revision": builder.controller.session_view().revision,
            "process_generation": 9,
            "protocol_version": 2,
        }

        self.assertTrue(tab._handle_dotnet_protocol_event(request))
        self.assertEqual(
            [
                {
                    "interaction_mode": "placement",
                    "comparison_mode": "original_only",
                    "gizmo_tool": "move",
                }
            ],
            scene_transitions,
        )
        self.assertEqual(["dotnet_finish_edit"], builder.finalized_dotnet_imports)
        self.assertIs(process, tab.standalone_dotnet_editor_process)
        self.assertEqual("ready", tab.standalone_dotnet_embedded_state)
        self.assertTrue(getattr(builder, "_mesh_editor_embedded_dotnet_active", False))
        writes = b"".join(process.stdin_writes)
        self.assertNotIn(b'"event":"deactivate_request"', writes)
        self.assertIn(b'"event":"command_result"', writes)
        self.assertIn(b'"status":"saved"', writes)
        self.assertIn(b'"request_id":12', writes)
        tab.standalone_dotnet_editor_process = None
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
        tab.standalone_dotnet_process_generation = 10
        process = _FakeProcess()
        process._state = process.Running
        tab.standalone_dotnet_editor_process = process
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
            display_combo.setCurrentText("Faces")
            _APP.processEvents()

        self.assertTrue(display_combo.isEnabled())
        self.assertEqual(
            {
                "event": "viewport_display_update",
                "session_id": "right-workspace-session",
                "mode": "untextured_faces",
            },
            sent[-1],
        )

        show_controls(False)

        self.assertFalse(builder.tabs.isTabVisible(advanced_index))
        self.assertEqual("Setup", builder.tabs.tabText(builder.tabs.currentIndex()))
        _APP.processEvents()
        tab.deleteLater()

    def test_dotnet_commands_keep_explicit_empty_selection_instead_of_reusing_resident_selection(self) -> None:
        settings = QSettings("CDMWTests", "MeshEditorDotNetExplicitEmptySelection")
        settings.clear()
        tab = MeshEditorTab(settings=settings)
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_controller = builder.controller
        builder.controller.select(source_indices=(0,), operation="replace")
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
                        "command": "transform_move",
                        "delta": [0.25, 0.0, 0.0],
                        "local_selection": {},
                    }
                )
            )

        self.assertEqual(1, len(captured))
        self.assertEqual("transform", captured[0].action)
        self.assertIsNotNone(captured[0].selection)
        assert captured[0].selection is not None
        self.assertTrue(captured[0].selection.is_empty())
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

    def test_dotnet_select_all_ignores_empty_local_snapshot_and_targets_every_part(self) -> None:
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
        self.assertEqual("source", captured[0].params["target_mode"])
        assert captured[0].selection is not None
        self.assertEqual((0, 1), captured[0].selection.source_indices)
        _APP.processEvents()
        tab.deleteLater()

    def test_dotnet_screen_selection_runs_in_background(self) -> None:
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorDotNetBackgroundSelect"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_controller = builder.controller
        captured: list[MeshEditCommand] = []

        with (
            patch.object(
                builder.controller,
                "apply",
                side_effect=AssertionError("screen selection ran synchronously on the UI thread"),
            ),
            patch.object(
                tab,
                "_start_dotnet_action_worker",
                side_effect=lambda _controller, command, **_kwargs: captured.append(command) or True,
            ),
        ):
            self.assertTrue(
                tab._handle_dotnet_select_request(
                    {
                        "event": "select_request",
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

        self.assertEqual(1, len(captured))
        self.assertEqual("select", captured[0].action)
        self.assertEqual("add", captured[0].params["operation"])
        self.assertIn("_native_screen_selection_payload", captured[0].params)
        _APP.processEvents()
        tab.deleteLater()

    def test_dotnet_grow_forwards_the_active_selection_target(self) -> None:
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

    @unittest.skipUnless(native_mesh_core_available(), "native mesh core is unavailable")
    def test_native_vertex_grow_and_shrink_ignore_other_selection_domains(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(_quad_mesh(), session_id="selection-domain-grow-shrink", mode="edit")
        contaminated_grow = MeshEditSelection.from_maps(
            vertices_by_submesh={0: (0,)},
            faces_by_submesh={0: (1,)},
            source_indices=(0,),
        )
        contaminated_shrink = MeshEditSelection.from_maps(
            vertices_by_submesh={0: (0, 1, 2)},
            faces_by_submesh={0: (1,)},
            source_indices=(0,),
        )
        try:
            controller.apply_command(
                MeshEditCommand(
                    "select",
                    selection=contaminated_grow,
                    params={"operation": "grow", "target_mode": "vertex"},
                )
            )
            self.assertEqual({0: {0, 1, 2}}, controller.session_view().selection.vertex_map())
            self.assertEqual((), controller.session_view().selection.source_indices)

            controller.apply_command(
                MeshEditCommand(
                    "select",
                    selection=contaminated_shrink,
                    params={"operation": "shrink", "target_mode": "vertex"},
                )
            )
            self.assertEqual({0: {0}}, controller.session_view().selection.vertex_map())
            self.assertEqual({}, controller.session_view().selection.face_map())
        finally:
            controller.close_active_session()

    @unittest.skipUnless(native_mesh_core_available(), "native mesh core is unavailable")
    def test_native_select_all_respects_every_dotnet_selection_domain(self) -> None:
        builder = _EmbeddedMeshBuilder()
        controller = builder.controller
        expected = {
            "source": (2, 0, 0, 0),
            "face": (0, 0, 0, 4),
            "edge": (0, 0, 10, 0),
            "vertex": (0, 8, 0, 0),
        }
        try:
            for target_mode, counts in expected.items():
                with self.subTest(target_mode=target_mode):
                    result = controller.apply_command(
                        MeshEditCommand(
                            "select",
                            selection=MeshEditSelection.from_maps(source_indices=(0, 1)),
                            params={"operation": "all", "target_mode": target_mode},
                        )
                    )
                    self.assertNotEqual("error", result.status)
                    selection = controller.session_view().selection
                    observed = (
                        len(selection.source_indices),
                        sum(len(values) for values in selection.vertex_map().values()),
                        sum(len(values) for values in selection.edge_map().values()),
                        sum(len(values) for values in selection.face_map().values()),
                    )
                    self.assertEqual(counts, observed)
                    controller.select(operation="replace")
        finally:
            controller.close_active_session()
            builder.deleteLater()

    def test_mesh_editor_blank_part_tree_click_clears_selection(self) -> None:
        workspace = MeshEditorWorkspace()
        workspace.resize(900, 700)
        workspace.show()
        _APP.processEvents()
        outliner = workspace.findChild(QTreeWidget, "MeshEditorOutlinerPanel")
        assert outliner is not None
        item = QTreeWidgetItem(("Part 0",))
        outliner.addTopLevelItem(item)
        item.setSelected(True)
        requests: list[tuple[int, str]] = []
        workspace.part_selection_requested.connect(
            lambda part_index, operation: requests.append((part_index, operation))
        )

        QTest.mouseClick(
            outliner.viewport(),
            Qt.MouseButton.LeftButton,
            pos=QPoint(5, max(5, outliner.viewport().height() - 5)),
        )
        _APP.processEvents()

        self.assertEqual([(-1, "clear")], requests)
        self.assertFalse(item.isSelected())
        workspace.close()
        workspace.deleteLater()

    def test_native_session_clones_preserve_resolved_preview_texture_bindings(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].preview_texture_path = "C:/cache/body.dds"
        mesh.submeshes[0].preview_texture_dds_path = "C:/cache/body.dds"
        mesh.submeshes[0].preview_material_texture_inputs = (
            SimpleNamespace(semantic_type="base", source_dds_path="C:/cache/body.dds"),
        )
        native_snapshot = {"kind": "native_submesh_snapshot", "submeshes": []}

        def restore(target: ParsedMesh, _snapshot: object) -> bool:
            target.path = mesh.path
            target.format = mesh.format
            target.submeshes = [_quad_mesh().submeshes[0]]
            return True

        with (
            patch("cdmw.services.mesh_service._service_session_native_clone_supported", return_value=True),
            patch("cdmw.services.mesh_service.snapshot_native_mesh_submeshes", return_value=native_snapshot),
            patch("cdmw.services.mesh_service.restore_native_mesh_submesh_snapshot", side_effect=restore),
            patch("cdmw.services.mesh_service.dispose_native_mesh_submesh_snapshot"),
            patch("cdmw.services.mesh_service.clone_mesh_for_editing", side_effect=AssertionError("full clone")),
        ):
            service = MeshService()
            view = service.open_edit_session(mesh, session_id="native-clone-preview-texture", mode="edit")
            cloned = service.working_mesh(view.session_id, clone=True)

        submesh = cloned.submeshes[0]
        self.assertEqual("C:/cache/body.dds", submesh.preview_texture_path)
        self.assertEqual("C:/cache/body.dds", submesh.preview_texture_dds_path)
        self.assertEqual("base", submesh.preview_material_texture_inputs[0].semantic_type)
