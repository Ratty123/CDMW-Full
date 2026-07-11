from __future__ import annotations

from tests.mesh_harness_support import (
    unittest,
    MESH_EDIT_ACTIONS,
    Path,
    _build_two_part_synthetic_mesh,
    _coverage_command,
    _selection_edges_from_group,
    _selection_faces_from_group,
    build_synthetic_mesh,
    clear_native_mesh_core_fallback_counts,
    native_mesh_core_available,
    native_mesh_core_fallback_counts,
    native_mesh_core_fallback_events,
    patch,
    record_native_mesh_core_fallback,
    run_scenario,
    struct,
    tempfile,
)

class MeshHarnessNativeScenarioTests(unittest.TestCase):
    def test_native_smoke_selection_event_helpers_accept_ranges_and_binary_edges(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            edge_path = Path(temp_dir) / "cdmw_mesh_preview_delta_test_edges.bin"
            edge_path.write_bytes(struct.pack("<iiii", 0, 1, 2, 3))
            group = {
                "source_edges_binary": {
                    "path": str(edge_path),
                    "count": 2,
                    "components": 2,
                    "type": "i32",
                    "delete_after": True,
                },
                "source_face_start": 0,
                "source_face_count": 2,
            }

            self.assertEqual(((0, 1), (2, 3)), _selection_edges_from_group(group))
            self.assertEqual((0, 1), _selection_faces_from_group(group))
            self.assertFalse(edge_path.exists())

    def test_native_mesh_core_fallback_telemetry_records_and_clears(self) -> None:
        clear_native_mesh_core_fallback_counts()
        try:
            record_native_mesh_core_fallback(
                "preview_geometry",
                "forced test fallback",
                vertex_count=4,
                face_count=2,
                submesh_indices=(0,),
            )

            self.assertEqual({"preview_geometry": 1}, native_mesh_core_fallback_counts())
            events = native_mesh_core_fallback_events()
            self.assertEqual("preview_geometry", events[0]["operation"])
            self.assertEqual("forced test fallback", events[0]["reason"])
            self.assertEqual(4, events[0]["vertex_count"])
        finally:
            clear_native_mesh_core_fallback_counts()

    def test_dotnet_native_parity_report_scenario_is_non_blocking_scaffold(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_scenario("mesh-dotnet-native-parity-report", Path(temp_dir))
            self.assertTrue((Path(temp_dir) / "dotnet_native_parity_report.json").is_file())

        self.assertFalse(result["ok"])
        parity = result["dotnet_native_parity"]
        self.assertEqual("blocked_report_scaffold", parity["mode"])
        self.assertEqual("dotnet_vortice_d3d11", parity["authority"])
        self.assertEqual("legacy_cpp_d3d11", parity["comparison_backend"])
        self.assertEqual("production_authoritative_renderer", parity["dotnet_role"])
        self.assertIn("final", parity["debug_channels"])
        self.assertTrue(parity["blockers"])

    def test_long_edit_mesh_tools_scenario_exercises_all_active_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_scenario("long-edit-mesh-tools", Path(temp_dir))

        self.assertTrue(result["ok"])
        long_edit = result["long_edit"]
        self.assertEqual(17, long_edit["tool_count"])
        self.assertEqual([], long_edit["failed_tools"])
        self.assertTrue(long_edit["native_fallback_ok"])
        if long_edit["native_core_available"]:
            self.assertEqual({}, long_edit["native_fallback_counts"])
        self.assertTrue(all(item["toggle_persistence_ok"] for item in long_edit["tools"]))
        tools = {item["tool"] for item in long_edit["tools"]}
        self.assertTrue(
            {
                "move",
                "grab",
                "smooth",
                "inflate",
                "pinch",
                "delete_face",
                "delete_edge",
                "delete_vertex",
                "subdivide_face",
                "subdivide_edge",
                "subdivide_vertex",
                "refine_smooth_face",
                "refine_smooth_edge",
                "refine_smooth_vertex",
                "split_face",
                "split_edge",
                "split_vertex",
            }.issubset(tools)
        )

    def test_native_mesh_editor_workflow_scenario_uses_native_session_without_fallback(self) -> None:
        if not native_mesh_core_available():
            self.skipTest("native mesh core binary not built")
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")):
                result = run_scenario("native-mesh-editor-workflow", Path(temp_dir))

        self.assertTrue(result["ok"])
        workflow = result["native_mesh_editor_workflow"]
        self.assertTrue(workflow["native_core_available"])
        self.assertTrue(workflow["native_fallback_ok"])
        self.assertEqual({}, workflow["native_fallback_counts"])
        self.assertTrue(workflow["command_ok"])
        self.assertTrue(workflow["topology_ok"])
        self.assertTrue(workflow["undo_redo_ok"])
        self.assertEqual(
            ["select_replace", "select_grow", "select_shrink", "select_smooth"],
            [item["label"] for item in workflow["selection_commands"]],
        )
        self.assertTrue(all("cpp_ms" in item.get("metrics", {}) for item in workflow["selection_commands"]))
        self.assertTrue(all("editor_select_cpp_ms" in item.get("metrics", {}) for item in workflow["selection_commands"]))
        self.assertEqual(["delete", "subdivide", "refine_smooth", "brush", "undo", "redo"], [item["label"] for item in workflow["commands"]])
        self.assertTrue(all("native_apply_roundtrip_ms" in item.get("metrics", {}) for item in workflow["commands"][:4]))
        self.assertTrue(all("service_total_ms" in item.get("metrics", {}) for item in workflow["commands"][:4]))
        self.assertTrue(all(item.get("metrics", {}).get("io_serialization_ms", 0.0) > 0.0 for item in workflow["commands"][:3]))
        self.assertTrue(all("native_history_roundtrip_ms" in item.get("metrics", {}) for item in workflow["commands"][4:6]))

    def test_native_session_action_coverage_avoids_legacy_geometry_dispatcher(self) -> None:
        from cdmw.services.mesh_service import MeshService

        if not native_mesh_core_available():
            self.skipTest("native mesh core binary not built")
        nonresident_display_actions = {"triangulate_display", "quadrangulate_display"}
        for action in sorted(set(MESH_EDIT_ACTIONS) - nonresident_display_actions):
            service = MeshService()
            mesh = _build_two_part_synthetic_mesh() if action == "material_copy" else build_synthetic_mesh()
            view = service.open_edit_session(mesh, session_id=f"native-session-coverage-{action}", mode="edit")
            try:
                with patch(
                    "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                    side_effect=AssertionError(f"old geometry dispatcher used: {action}"),
                ):
                    result = service.apply_command(view.session_id, _coverage_command(action))
            finally:
                service.close_edit_session(view.session_id)
            with self.subTest(action=action):
                self.assertIn(result.status, {"ok", "noop"})

    def test_native_mesh_editor_qt_responsiveness_scenario_uses_worker_without_fallback(self) -> None:
        if not native_mesh_core_available():
            self.skipTest("native mesh core binary not built")
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")):
                result = run_scenario("native-mesh-editor-qt-responsiveness", Path(temp_dir))

        self.assertTrue(result["ok"])
        responsiveness = result["native_mesh_editor_qt_responsiveness"]
        self.assertTrue(responsiveness["native_core_available"])
        self.assertTrue(responsiveness["thread_ready_ok"])
        self.assertTrue(responsiveness["dispatch_target_ok"])
        self.assertTrue(responsiveness["progress_target_ok"])
        self.assertTrue(responsiveness["qt_heartbeat_ok"])
        self.assertTrue(responsiveness["command_ok"])
        self.assertTrue(responsiveness["native_fallback_ok"])
        self.assertEqual({}, responsiveness["native_fallback_counts"])
        self.assertTrue(
            responsiveness["heartbeat_count"] >= 2
            or responsiveness["total_elapsed_ms"] <= 200.0
        )

    def test_native_mesh_editor_qt_cancellation_scenario_cancels_without_fallback(self) -> None:
        if not native_mesh_core_available():
            self.skipTest("native mesh core binary not built")
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")):
                result = run_scenario("native-mesh-editor-qt-cancellation", Path(temp_dir))

        self.assertTrue(result["ok"], result)
        cancellation = result["native_mesh_editor_qt_cancellation"]
        self.assertTrue(cancellation["native_core_available"])
        self.assertTrue(cancellation["thread_ready_ok"])
        self.assertTrue(cancellation["dispatch_target_ok"])
        self.assertTrue(cancellation["progress_target_ok"])
        self.assertTrue(cancellation["cancel_target_ok"])
        self.assertTrue(cancellation["native_fallback_ok"])
        self.assertEqual({}, cancellation["native_fallback_counts"])
        self.assertLessEqual(cancellation["cancel_latency_ms"], 500.0)
        self.assertIn("Cancelled", cancellation["cancelled"])

    def test_native_mesh_editor_standalone_stroke_scenario_uses_native_session_without_fallback(self) -> None:
        if not native_mesh_core_available():
            self.skipTest("native mesh core binary not built")
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")):
                result = run_scenario("native-mesh-editor-standalone-stroke", Path(temp_dir))

        self.assertTrue(result["ok"], result)
        stroke = result["native_mesh_editor_standalone_stroke"]
        self.assertTrue(stroke["native_core_available"])
        self.assertTrue(stroke["moved"])
        self.assertTrue(stroke["undo_restored"])
        self.assertTrue(stroke["brush_moved"])
        self.assertTrue(stroke["brush_weighted_delta_ok"])
        self.assertTrue(stroke["brush_undo_restored"])
        self.assertEqual(1, stroke["undo_count_after_stroke"])
        self.assertEqual(1, stroke["undo_count_after_brush"])
        self.assertEqual("", stroke["stroke_id_after_finish"])
        self.assertTrue(stroke["dispatch_target_ok"])
        self.assertTrue(stroke["signals_ok"])
        self.assertTrue(stroke["screen_selection_ok"])
        self.assertTrue(stroke["screen_payloads_without_legacy_camera_fields_ok"])
        self.assertEqual([1], stroke["screen_selection_vertices"])
        self.assertEqual([[0, 1]], stroke["screen_selection_edges"])
        self.assertEqual([0], stroke["screen_selection_faces"])
        self.assertIn("set_mesh_edit_selection", stroke["host_calls"])
        self.assertEqual(1.0, stroke["screen_selection_metrics"]["editor_select_resident_operation"])
        self.assertEqual(1.0, stroke["last_action_metrics"]["editor_select_reused"])
        self.assertEqual(0.0, stroke["last_action_metrics"]["editor_select_roundtrip_ms"])
        self.assertTrue(stroke["native_fallback_ok"])
        self.assertEqual({}, stroke["native_fallback_counts"])
        self.assertIn("set_mesh_edit_state", stroke["host_calls"])
        self.assertIn("update_mesh_edit_vertices", stroke["host_calls"])
        self.assertEqual("grab", stroke["mesh_edit_state"]["tool"])
        self.assertEqual("selection", stroke["mesh_edit_state"]["target_mode"])

    def test_native_mesh_editor_static_screen_stroke_scenario_uses_native_session_without_fallback(self) -> None:
        if not native_mesh_core_available():
            self.skipTest("native mesh core binary not built")
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")):
                result = run_scenario("native-mesh-editor-static-screen-stroke", Path(temp_dir))

        self.assertTrue(result["ok"])
        stroke = result["native_mesh_editor_static_screen_stroke"]
        self.assertTrue(stroke["native_core_available"])
        self.assertTrue(stroke["transform_moved"])
        self.assertTrue(stroke["descriptor_transform_moved"])
        self.assertTrue(stroke["brush_moved"])
        self.assertTrue(stroke["transform_delta_ok"])
        self.assertTrue(stroke["transform_incremental_drag_ok"])
        self.assertEqual(0.0, stroke["transform_begin_screen_drag"]["start_x"])
        self.assertEqual(2.0, stroke["transform_begin_screen_drag"]["end_x"])
        self.assertEqual(2.0, stroke["transform_update_screen_drag"]["start_x"])
        self.assertEqual(5.0, stroke["transform_update_screen_drag"]["end_x"])
        self.assertTrue(stroke["descriptor_transform_delta_ok"])
        self.assertTrue(stroke["brush_delta_ok"])
        self.assertTrue(stroke["screen_payloads_without_legacy_camera_fields_ok"])
        self.assertTrue(stroke["screen_payloads_with_source_transform_overrides_ok"])
        self.assertEqual(1, stroke["transform_vertex_group_count"])
        self.assertEqual(1, stroke["descriptor_transform_vertex_group_count"])
        self.assertEqual(1, stroke["brush_vertex_group_count"])
        self.assertTrue(stroke["native_fallback_ok"])
        self.assertEqual({}, stroke["native_fallback_counts"])

    def test_standalone_native_grab_update_skips_redundant_selection_payload(self) -> None:
        from cdmw.ui.mesh_editor import MeshEditorTab

        class Adapter:
            standalone_native_mesh_edit_stroke_id = "stroke-1"
            _standalone_native_payload_vec3 = staticmethod(MeshEditorTab._standalone_native_payload_vec3)
            _standalone_native_payload_float = staticmethod(MeshEditorTab._standalone_native_payload_float)
            _standalone_native_payload_int = staticmethod(MeshEditorTab._standalone_native_payload_int)

            @staticmethod
            def _standalone_native_payload_selection(_payload: object) -> dict[str, object]:
                raise AssertionError("grab update should reuse resident native selection")

        command = MeshEditorTab._standalone_native_mesh_edit_stroke_command(
            Adapter(),
            {
                "stroke_id": "stroke-1",
                "tool": "grab",
                "center": {"x": 0.0, "y": 0.0, "z": 0.0},
                "screen_drag": {
                    "start_x": 0.0,
                    "start_y": 0.0,
                    "end_x": 5.0,
                    "end_y": 0.0,
                    "yaw_degrees": 90.0,
                    "pitch_degrees": 0.0,
                    "distance": 1.0,
                    "viewport_height": 200.0,
                    "vertical_fov_degrees": 90.0,
                },
                "groups": [{"source_submesh_index": 0, "source_vertex_indices": [0, 1]}],
            },
            "update",
        )

        self.assertIsNotNone(command)
        self.assertEqual("brush", command.action)
        self.assertNotIn("_native_selection_payload", command.params)
        self.assertIn("screen_drag", command.params)
        self.assertNotIn("yaw_degrees", command.params["screen_drag"])
        self.assertNotIn("vertical_fov_degrees", command.params["screen_drag"])

    def test_standalone_native_grab_begin_with_screen_brush_skips_host_groups(self) -> None:
        from cdmw.ui.mesh_editor import MeshEditorTab

        class Adapter:
            standalone_native_mesh_edit_stroke_id = ""
            _standalone_native_payload_vec3 = staticmethod(MeshEditorTab._standalone_native_payload_vec3)
            _standalone_native_payload_float = staticmethod(MeshEditorTab._standalone_native_payload_float)
            _standalone_native_payload_int = staticmethod(MeshEditorTab._standalone_native_payload_int)

            @staticmethod
            def _standalone_native_payload_selection(_payload: object) -> dict[str, object]:
                raise AssertionError("grab screen-brush begin should not require host-expanded groups")

        command = MeshEditorTab._standalone_native_mesh_edit_stroke_command(
            Adapter(),
            {
                "stroke_id": "grab-1",
                "tool": "grab",
                "target_mode": "vertex",
                "selection_depth_mode": "visible",
                "falloff": "smooth",
                "screen_drag": {
                    "start_x": 100.0,
                    "start_y": 80.0,
                    "end_x": 100.0,
                    "end_y": 80.0,
                },
                "screen_brush": {
                    "x": 100.0,
                    "y": 80.0,
                    "radius_pixels": 24.0,
                    "viewport_width": 200.0,
                    "viewport_height": 160.0,
                },
                "strength": 0.5,
            },
            "begin",
        )

        self.assertIsNotNone(command)
        self.assertEqual("brush", command.action)
        self.assertIn("screen_drag", command.params)
        self.assertIn("screen_brush", command.params)
        self.assertEqual("vertex", command.params["target_mode"])
        self.assertNotIn("_native_selection_payload", command.params)

    def test_standalone_native_move_begin_forwards_screen_selection_to_native(self) -> None:
        from cdmw.ui.mesh_editor import MeshEditorTab

        class Adapter:
            standalone_native_mesh_edit_stroke_id = ""
            _standalone_native_payload_vec3 = staticmethod(MeshEditorTab._standalone_native_payload_vec3)
            _standalone_native_payload_float = staticmethod(MeshEditorTab._standalone_native_payload_float)
            _standalone_native_payload_int = staticmethod(MeshEditorTab._standalone_native_payload_int)

            @staticmethod
            def _standalone_native_payload_selection(_payload: object) -> dict[str, object]:
                raise AssertionError("move screen selection should not require host-expanded groups")

        command = MeshEditorTab._standalone_native_mesh_edit_stroke_command(
            Adapter(),
            {
                "stroke_id": "move-1",
                "tool": "move",
                "target_mode": "vertex",
                "selection_depth_mode": "visible",
                "falloff": "smooth",
                "screen_drag": {
                    "start_x": 100.0,
                    "start_y": 80.0,
                    "end_x": 100.0,
                    "end_y": 80.0,
                },
                "screen_brush": {
                    "x": 100.0,
                    "y": 80.0,
                    "radius_pixels": 24.0,
                    "viewport_width": 200.0,
                    "viewport_height": 160.0,
                },
            },
            "begin",
        )

        self.assertIsNotNone(command)
        self.assertEqual("transform", command.action)
        self.assertIn("screen_drag", command.params)
        self.assertNotIn("_native_selection_payload", command.params)
        screen_payload = command.params["_native_screen_selection_payload"]
        self.assertEqual("vertex", screen_payload["target_mode"])
        self.assertEqual("visible", screen_payload["selection_depth_mode"])
        self.assertEqual(100.0, screen_payload["screen_brush"]["x"])

    def test_standalone_native_move_requires_screen_drag(self) -> None:
        from cdmw.ui.mesh_editor import MeshEditorTab

        class Adapter:
            standalone_native_mesh_edit_stroke_id = ""
            _standalone_native_payload_vec3 = staticmethod(MeshEditorTab._standalone_native_payload_vec3)
            _standalone_native_payload_float = staticmethod(MeshEditorTab._standalone_native_payload_float)
            _standalone_native_payload_int = staticmethod(MeshEditorTab._standalone_native_payload_int)

            @staticmethod
            def _standalone_native_payload_selection(_payload: object) -> dict[str, object]:
                return {"vertices_by_submesh": [{"index": 0, "indices": [0]}]}

        command = MeshEditorTab._standalone_native_mesh_edit_stroke_command(
            Adapter(),
            {
                "stroke_id": "move-1",
                "tool": "move",
                "step_delta": {"x": 0.0, "y": 0.0, "z": 0.25},
            },
            "begin",
        )

        self.assertIsNone(command)
        finish_command = MeshEditorTab._standalone_native_mesh_edit_stroke_command(
            Adapter(),
            {
                "stroke_id": "move-1",
                "tool": "move",
            },
            "end",
        )

        self.assertIsNotNone(finish_command)
        self.assertNotIn("screen_drag", finish_command.params)

    def test_standalone_native_inflate_forwards_screen_radius_to_native(self) -> None:
        from cdmw.ui.mesh_editor import MeshEditorTab

        class Adapter:
            standalone_native_mesh_edit_stroke_id = "stroke-1"
            _standalone_native_payload_vec3 = staticmethod(MeshEditorTab._standalone_native_payload_vec3)
            _standalone_native_payload_float = staticmethod(MeshEditorTab._standalone_native_payload_float)
            _standalone_native_payload_int = staticmethod(MeshEditorTab._standalone_native_payload_int)

            @staticmethod
            def _standalone_native_payload_selection(_payload: object) -> dict[str, object]:
                raise AssertionError("screen_brush update should reuse resident native selection")

        command = MeshEditorTab._standalone_native_mesh_edit_stroke_command(
            Adapter(),
            {
                "stroke_id": "stroke-1",
                "tool": "inflate",
                "center": {"x": 0.0, "y": 0.0, "z": 0.0},
                "screen_radius": {"radius_pixels": 8.0, "distance": 2.0, "viewport_height": 100.0, "vertical_fov_degrees": 45.0},
                "screen_brush": {"x": 100.0, "y": 120.0, "radius_pixels": 8.0, "viewport_width": 200.0, "viewport_height": 100.0},
                "target_mode": "vertex",
                "selection_depth_mode": "visible",
                "strength": 0.5,
            },
            "update",
        )

        self.assertIsNotNone(command)
        self.assertEqual("brush", command.action)
        self.assertNotIn("_native_selection_payload", command.params)
        self.assertIn("screen_radius", command.params)
        self.assertIn("screen_brush", command.params)
        self.assertNotIn("distance", command.params["screen_radius"])
        self.assertNotIn("vertical_fov_degrees", command.params["screen_radius"])
        self.assertEqual("vertex", command.params["target_mode"])
        self.assertEqual("visible", command.params["selection_depth_mode"])
        self.assertNotIn("amount", command.params)

    def test_standalone_native_selection_event_uses_screen_payload(self) -> None:
        tab_source = "\n".join(
            Path(path).read_text(encoding="utf-8")
            for path in (
                "cdmw/ui/mesh_editor/tab_shell.py",
                "cdmw/ui/mesh_editor/tab_interaction.py",
            )
        )
        self.assertIn('"mesh_edit_selection_changed", self._handle_standalone_native_mesh_edit_selection_changed', tab_source)
        handler_start = tab_source.index("def _handle_standalone_native_mesh_edit_selection_changed")
        handler_body = tab_source[handler_start:tab_source.index("def _apply_standalone_native_mesh_edit_stroke", handler_start)]
        self.assertIn('payload.get("screen_brush")', handler_body)
        self.assertIn('payload.get("screen_region")', handler_body)
        self.assertIn("_native_screen_selection_payload=screen_payload", handler_body)
        self.assertIn('screen_payload["screen_brush"]', handler_body)
        self.assertIn('screen_payload["screen_region"]', handler_body)
        self.assertIn('screen_payload["target_mode"]', handler_body)
        self.assertIn('screen_payload["selection_depth_mode"]', handler_body)
        self.assertIn("native_update = controller.native_update_for_result(result)", handler_body)
        self.assertIn("self._apply_standalone_native_update(native_update)", handler_body)
        self.assertNotIn("_standalone_native_payload_selection(payload)", handler_body)
