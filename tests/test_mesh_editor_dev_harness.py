from __future__ import annotations

import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from cdmw.domain.mesh import MESH_EDIT_ACTIONS, MeshEditSelection
from cdmw.domain.mesh.skeleton import (
    MeshAnimationClip,
    MeshAnimationKeyframe,
    MeshAnimationSequenceSegment,
    MeshAnimationTrack,
)
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.services.asset_authoring_service import (
    ASSET_AUTHORING_MESH_HEALTH_SCHEMA,
    ASSET_AUTHORING_SOURCE_IMAGE_SCHEMA,
    ASSET_AUTHORING_TANGENT_REPORT_SCHEMA,
    ASSET_AUTHORING_UV_REPORT_SCHEMA,
)
from cdmw.modding.mesh_native_core import (
    clear_native_mesh_core_fallback_counts,
    native_mesh_core_available,
    native_mesh_core_fallback_counts,
    native_mesh_core_fallback_events,
    record_native_mesh_core_fallback,
)
from cdmw.rendering.native_d3d11_host import find_native_d3d11_host
from cdmw.ui.mesh_editor.native_preview_payloads import (
    mesh_edit_material_override_groups,
    mesh_edit_selection_groups,
    mesh_edit_triangle_groups,
    mesh_edit_vertex_update_groups,
    mesh_to_native_preview,
)
from cdmw.ui.mesh_editor.actions import MESH_EDITOR_ACTIONS
from cdmw.ui.mesh_editor.native_preview_runtime import (
    mesh_editor_native_preview_command,
    mesh_editor_write_native_preview_package,
)
from cdmw.models import ArchiveEntry
from tools.mesh_editor_dev_harness import (
    _build_two_part_synthetic_mesh,
    _coverage_command,
    _papr_constraint_metadata_summary,
    _png_capture_summary,
    _real_archive_papr_read_status,
    _sample_real_archive_paa_playback,
    _selection_edges_from_group,
    _selection_faces_from_group,
    _sequence_event_marker_overlap,
    _sequence_lane_pair_summary,
    _sequence_path_record_context,
    _sequence_reference_overlap,
    _sequence_timeline_field_overlap,
    _sequence_timeline_field_semantic_aliases,
    build_native_benchmark_mesh,
    build_synthetic_mesh,
    run_scenario,
)


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type)
    checksum = zlib.crc32(payload, checksum) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", checksum)


def _write_rgb_png(path: Path, width: int, height: int, rows: list[bytes]) -> None:
    raw = b"".join(b"\x00" + row for row in rows)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b"")
)


def _i32_descriptor_values(group: dict[str, object], json_key: str, binary_key: str) -> list[int]:
    raw_json = group.get(json_key)
    raw_descriptor = group.get(binary_key)
    if isinstance(raw_json, list) and (raw_json or not isinstance(raw_descriptor, dict)):
        return [int(value) for value in raw_json]
    if "vertex" in json_key:
        start_key, count_key = "source_vertex_start", "source_vertex_count"
    elif "face" in json_key:
        start_key, count_key = "source_face_start", "source_face_count"
    else:
        start_key, count_key = "", ""
    try:
        raw_start = group.get(start_key, -1)
        raw_count = group.get(count_key, 0)
        start = int(raw_start if raw_start is not None else -1)
        count = int(raw_count if raw_count is not None else 0)
    except (TypeError, ValueError, OverflowError):
        start, count = -1, 0
    if start >= 0 and count > 0:
        return list(range(start, start + count))
    if not isinstance(raw_descriptor, dict) or not str(raw_descriptor.get("path") or "").strip():
        return []
    path = Path(str(raw_descriptor.get("path") or ""))
    data = path.read_bytes()
    if len(data) % 4:
        return []
    return list(struct.unpack("<" + "i" * (len(data) // 4), data))


def _f64_descriptor_values(group: dict[str, object], json_key: str, binary_key: str) -> list[float]:
    raw_json = group.get(json_key)
    if isinstance(raw_json, list):
        return [float(value) for value in raw_json]
    raw_descriptor = group.get(binary_key)
    if not isinstance(raw_descriptor, dict):
        return []
    path = Path(str(raw_descriptor.get("path") or ""))
    data = path.read_bytes()
    if len(data) % 8:
        return []
    return list(struct.unpack("<" + "d" * (len(data) // 8), data))


def _edge_descriptor_values(group: dict[str, object]) -> list[list[int]]:
    raw_json = group.get("source_edges")
    if isinstance(raw_json, list):
        return [[int(edge[0]), int(edge[1])] for edge in raw_json if isinstance(edge, list) and len(edge) >= 2]
    values = _i32_descriptor_values(group, "source_edges", "source_edges_binary")
    return [[values[index], values[index + 1]] for index in range(0, len(values) - 1, 2)]


class MeshEditorDevHarnessTests(unittest.TestCase):
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
        self.assertTrue(responsiveness["dispatch_target_ok"])
        self.assertTrue(responsiveness["progress_target_ok"])
        self.assertTrue(responsiveness["qt_heartbeat_ok"])
        self.assertTrue(responsiveness["command_ok"])
        self.assertTrue(responsiveness["native_fallback_ok"])
        self.assertEqual({}, responsiveness["native_fallback_counts"])
        self.assertGreaterEqual(responsiveness["heartbeat_count"], 2)

    def test_native_mesh_editor_qt_cancellation_scenario_cancels_without_fallback(self) -> None:
        if not native_mesh_core_available():
            self.skipTest("native mesh core binary not built")
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")):
                result = run_scenario("native-mesh-editor-qt-cancellation", Path(temp_dir))

        self.assertTrue(result["ok"])
        cancellation = result["native_mesh_editor_qt_cancellation"]
        self.assertTrue(cancellation["native_core_available"])
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

        self.assertTrue(result["ok"])
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
        tab_source = Path("cdmw/ui/mesh_editor/tab.py").read_text(encoding="utf-8")
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

    def test_d3d11_brush_selection_event_carries_screen_brush_context(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")
        self.assertIn("void send_mesh_edit_screen_brush_selection_event(int x, int y)", source)
        selection_event_start = source.index("void send_mesh_edit_selection_event(")
        selection_event_body = source[selection_event_start:source.index("int update_mesh_edit_vertices_from_payload", selection_event_start)]
        self.assertIn("bool include_screen_brush = false", selection_event_body)
        self.assertIn('\\"screen_brush\\":', selection_event_body)
        screen_event_body = source[source.index("void send_mesh_edit_screen_brush_selection_event("):selection_event_start]
        self.assertIn('\\"target_mode\\":', screen_event_body)
        self.assertIn('\\"selection_depth_mode\\":', screen_event_body)
        self.assertIn("mesh_edit_screen_brush_json(mesh_edit_.last_x, mesh_edit_.last_y, mesh_edit_.radius_pixels)", selection_event_body)
        brush_json_start = source.index("std::string mesh_edit_screen_brush_json(")
        brush_json_body = source[brush_json_start:source.index("std::string mesh_edit_screen_region_json(", brush_json_start)]
        self.assertIn("mesh_edit_source_projection_overrides_json()", brush_json_body)
        brush_selection_start = source.index("void apply_mesh_edit_brush_selection(")
        brush_selection_body = source[brush_selection_start:source.index("bool mesh_edit_preview_event_due", brush_selection_start)]
        self.assertIn("send_mesh_edit_screen_brush_selection_event(x, y)", brush_selection_body)
        self.assertNotIn("mesh_edit_depth_filter_enabled()", brush_selection_body)
        self.assertNotIn("mesh_edit_face_candidates_at", brush_selection_body)
        self.assertNotIn("mesh_edit_edge_candidates_at", brush_selection_body)
        self.assertNotIn("mesh_edit_candidates_at(x, y, mesh_edit_.radius_pixels, false)", brush_selection_body)

    def test_d3d11_region_selection_event_carries_screen_region_context(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")
        self.assertIn("std::string mesh_edit_screen_region_json(int x, int y) const", source)
        self.assertIn("void send_mesh_edit_screen_region_selection_event(int x, int y)", source)

        region_start = source.index("std::string mesh_edit_screen_region_json(")
        region_body = source[region_start:source.index("std::string mesh_edit_payload_json(", region_start)]
        self.assertIn('\\"start_x\\":', region_body)
        self.assertIn('\\"end_x\\":', region_body)
        self.assertIn('\\"points\\":', region_body)
        self.assertIn('\\"source_submesh_indices\\":', region_body)
        self.assertIn('\\"world_view_projection\\":', region_body)
        self.assertIn("XMStoreFloat4x4(&world_view_projection, current_mvp_matrix())", region_body)
        self.assertIn("mesh_edit_source_projection_overrides_json()", region_body)
        for legacy_field in ('\\"camera_world\\":', '\\"yaw_degrees\\":', '\\"pitch_degrees\\":', '\\"distance\\":', '\\"vertical_fov_degrees\\":', '\\"pan\\":'):
            self.assertNotIn(legacy_field, region_body)

        region_event_start = source.index("void send_mesh_edit_screen_region_selection_event(")
        region_event_body = source[region_event_start:source.index("void send_mesh_edit_selection_event(", region_event_start)]
        self.assertIn('\\"target_mode\\":', region_event_body)
        self.assertIn('\\"selection_depth_mode\\":', region_event_body)
        self.assertIn('\\"screen_region\\":', region_event_body)

        selection_start = source.index("void apply_mesh_edit_region_selection")
        selection_body = source[selection_start:source.index("void finish_mesh_edit_selection_drag", selection_start)]
        self.assertIn("send_mesh_edit_screen_region_selection_event(x, y)", selection_body)
        self.assertNotIn("mesh_edit_screen_vertices_for_view", selection_body)
        self.assertNotIn("mesh_edit_depth_filter_enabled()", selection_body)
        self.assertNotIn("mesh_edit_faces_in_selection_region", selection_body)
        self.assertNotIn("apply_mesh_edit_face_selection_delta", selection_body)
        self.assertNotIn("apply_mesh_edit_edge_selection_delta", selection_body)
        self.assertNotIn("apply_mesh_edit_selection_delta", selection_body)

    def test_d3d11_source_selection_accepts_screen_payload(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")
        brush_command_start = source.index('if (command == "select_mesh_edit_brush")')
        brush_command_body = source[brush_command_start:source.index('if (command == "select_mesh_edit_region")', brush_command_start)]
        region_command_start = source.index('if (command == "select_mesh_edit_region")')
        region_command_body = source[region_command_start:source.index('if (command == "update_mesh_edit_vertices")', region_command_start)]
        brush_event_start = source.index("void send_mesh_edit_screen_brush_selection_event(")
        brush_event_body = source[brush_event_start:source.index("void send_mesh_edit_screen_region_selection_event(", brush_event_start)]
        part_click_start = source.index("void send_source_part_screen_selection_event(")
        part_click_body = source[part_click_start:source.index("void update_source_part_hover(", part_click_start)]
        part_context_start = source.index("void send_source_part_screen_context_event(")
        part_context_body = source[part_context_start:source.index("void update_source_part_hover(", part_context_start)]
        hover_start = source.index("void update_source_part_hover(")
        hover_body = source[hover_start:source.index("void begin_source_part_click(", hover_start)]
        begin_part_click_start = source.index("void begin_source_part_click(")
        begin_part_click_body = source[begin_part_click_start:source.index("void finish_source_part_click(", begin_part_click_start)]
        finish_part_click_start = source.index("void finish_source_part_click(")
        finish_part_click_body = source[finish_part_click_start:source.index("bool request_source_part_context(", finish_part_click_start)]
        source_context_start = source.index("bool request_source_part_context(")
        source_context_body = source[source_context_start:source.index("std::string mesh_edit_screen_drag_json(", source_context_start)]
        brush_json_start = source.index("std::string mesh_edit_screen_brush_json(")
        brush_json_body = source[brush_json_start:source.index("std::string mesh_edit_screen_region_json(", brush_json_start)]
        region_json_start = source.index("std::string mesh_edit_screen_region_json(")
        region_json_body = source[region_json_start:source.index("std::string mesh_edit_payload_json(", region_json_start)]
        overrides_start = source.index("std::string mesh_edit_source_projection_overrides_json() const")
        overrides_body = source[overrides_start:source.index("std::string mesh_edit_screen_brush_json(", overrides_start)]

        tab_source = Path("cdmw/ui/mesh_editor/tab.py").read_text(encoding="utf-8")
        handler_start = tab_source.index("def _handle_standalone_native_mesh_edit_selection_changed")
        handler_body = tab_source[handler_start:tab_source.index("def _apply_standalone_native_mesh_edit_stroke", handler_start)]

        native_source = Path("native/cdmw_mesh_core/src/main.cpp").read_text(encoding="utf-8")
        native_projection_start = native_source.index("MeshEditorScreenBrushProjection mesh_editor_screen_brush_projection")
        native_projection_body = native_source[native_projection_start:native_source.index("bool mesh_editor_screen_ray_from_projection", native_projection_start)]
        native_brush_start = native_source.index("void mesh_editor_add_screen_brush_selection(")
        native_brush_body = native_source[native_brush_start:native_source.index("bool mesh_editor_screen_region_contains", native_brush_start)]
        native_select_start = native_source.index('if (command == "select")')
        native_select_body = native_source[native_select_start:native_source.index('if (command == "apply")', native_select_start)]
        native_region_start = native_source.index("void mesh_editor_add_screen_region_selection(")
        native_region_body = native_source[native_region_start:native_source.index("MeshEditorSelection mesh_editor_selection_from_json", native_region_start)]
        harness_source = Path("tools/mesh_editor_dev_harness.py").read_text(encoding="utf-8")

        self.assertIn('target_mode == "source"', brush_command_body)
        self.assertIn('target_mode == "source"', region_command_body)
        self.assertIn('\\"target_mode\\":', brush_event_body)
        self.assertIn('\\"screen_brush\\":', brush_event_body)
        self.assertIn('\\"operation\\":\\"toggle\\"', part_click_body)
        self.assertIn('\\"target_mode\\":\\"source\\"', part_click_body)
        self.assertIn('\\"selection_depth_mode\\":\\"xray\\"', part_click_body)
        self.assertIn("mesh_edit_screen_brush_json(x, y, 28.0f, false)", part_click_body)
        self.assertIn('send_mesh_edit_event("mesh_edit_selection_changed", payload.str())', part_click_body)
        self.assertIn('\\"operation\\":\\"context\\"', part_context_body)
        self.assertIn('\\"target_mode\\":\\"source\\"', part_context_body)
        self.assertIn('\\"context_request\\":true', part_context_body)
        self.assertIn('\\"context_x\\":', part_context_body)
        self.assertIn("mesh_edit_screen_brush_json(x, y, 28.0f, false)", part_context_body)
        self.assertIn("if (mesh_edit_.enabled)", hover_body)
        self.assertLess(
            hover_body.index("if (mesh_edit_.enabled)"),
            hover_body.index("source_part_at(x, y, 28.0f)"),
        )
        self.assertIn('send_source_part_event("source_part_hovered", -1)', hover_body)
        self.assertIn("if (mesh_edit_.enabled)", source_context_body)
        self.assertLess(
            source_context_body.index("if (mesh_edit_.enabled)"),
            source_context_body.index("source_part_at(x, y, 28.0f)"),
        )
        self.assertIn("send_source_part_screen_context_event(x, y)", source_context_body)
        self.assertIn("bool include_source_filter = true", brush_json_body)
        self.assertIn("include_source_filter && !mesh_edit_.source_submesh_indices.empty()", brush_json_body)
        self.assertIn("mesh_edit_source_projection_overrides_json()", brush_json_body)
        self.assertIn("mesh_edit_source_projection_overrides_json()", region_json_body)
        self.assertIn("alignment_preview_transform_active()", overrides_body)
        self.assertIn("batch_uses_source_normalization(batch)", overrides_body)
        self.assertIn("mesh_edit_source_world_transform_for_batch(batch)", overrides_body)
        self.assertIn("mesh_edit_source_allowed(batch.source_submesh_index)", overrides_body)
        self.assertIn("source_submesh_world_transforms", overrides_body)
        self.assertIn("world_transform", overrides_body)
        self.assertNotIn("current_world_view_projection", overrides_body)
        self.assertIn("if (!mesh_edit_.enabled)", begin_part_click_body)
        self.assertIn("source_part_at(x, y, 28.0f)", begin_part_click_body)
        self.assertIn("if (mesh_edit_.enabled)", finish_part_click_body)
        self.assertIn("send_source_part_screen_selection_event(x, y)", finish_part_click_body)
        self.assertIn("send_source_part_event(\"source_part_selected\"", finish_part_click_body)
        self.assertLess(
            finish_part_click_body.index("if (mesh_edit_.enabled)"),
            finish_part_click_body.index("send_source_part_screen_selection_event(x, y)"),
        )
        self.assertIn('target_mode == "source"', native_brush_body)
        self.assertIn("source_submesh_world_transforms", native_projection_body)
        self.assertIn("matrix4x4_multiply(source_world_transform, projection.world_view_projection)", native_projection_body)
        self.assertIn("mesh_editor_projection_for_submesh(", native_projection_body)
        self.assertIn("mesh_editor_projection_for_submesh(projection, entry.first)", native_brush_body)
        self.assertIn("mesh_editor_pick_source_with_screen_ray(session, *raw_brush, projection)", native_brush_body)
        self.assertIn("selection.source_indices.insert(best_source_index)", native_brush_body)
        self.assertIn('target_mode == "edge" || target_mode == "face"', native_brush_body)
        self.assertIn("mesh_editor_screen_ray_from_projection(*raw_brush, entry_projection, screen_ray)", native_brush_body)
        self.assertIn("mesh_editor_ray_segment_distance(", native_brush_body)
        self.assertIn("mesh_editor_ray_intersects_triangle(", native_brush_body)
        self.assertIn("mesh_editor_project_screen_brush_vertex_with_projection", native_brush_body)
        self.assertIn('selection_operation == "context"', native_select_body)
        self.assertIn("source_pick_count", native_select_body)
        self.assertIn("mesh_editor_selection_empty(incoming)", native_select_body)
        self.assertIn("editor_select_source_pick_count", handler_body)
        self.assertIn("show_part_context_menu_for_part", handler_body)
        self.assertIn('payload.get("context_request")', handler_body)
        self.assertIn('target_mode == "source"', native_region_body)
        self.assertIn("mesh_editor_projection_for_submesh(projection, entry.first)", native_region_body)
        self.assertIn("selection.source_indices.insert(entry.first)", native_region_body)
        self.assertIn('"command": "select_mesh_edit_brush"', harness_source)
        self.assertIn('"target_mode": "source"', harness_source)
        self.assertIn("source_screen_selection_ok", harness_source)
        self.assertIn('"command": "set_alignment_transforms"', harness_source)
        self.assertIn("_screen_source_transform_override_ok", harness_source)
        self.assertIn("screen_payloads_with_source_transform_overrides_ok", harness_source)

    def test_d3d11_native_screen_tools_skip_overlay_candidate_hits(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")
        overlay_start = source.index("const bool cursor_in_view =")
        overlay_body = source[overlay_start:source.index("if (mesh_edit_.selection_drag_active &&", overlay_start)]

        self.assertIn("add_ring(", overlay_body)
        self.assertIn('const bool remove_tool = mesh_edit_.tool == "remove";', overlay_body)
        self.assertIn("draw_mesh_edit_vertex_dots_instanced(view, *dot_vertices, xray_mode);", source)
        self.assertIn("mesh_edit_source_face_selected(batch, triangle_index, base)", source)
        self.assertIn("mesh_edit_source_edge_selected(key0, key1)", source)
        self.assertNotIn("native_screen_tool", source)
        self.assertNotIn("brush_vertices", source)
        self.assertNotIn("brush_triangle", source)
        self.assertNotIn("struct EditorCandidate", source)
        self.assertNotIn("struct MeshEditEdgeCandidate", source)
        self.assertNotIn("mesh_edit_candidates_at_in_view", source)
        self.assertNotIn("mesh_edit_edge_candidates_at_in_view", source)
        self.assertNotIn("mesh_edit_face_candidates_at_in_view", source)
        self.assertNotIn("std::vector<EditorCandidate> mesh_edit_face_candidates_at_in_view", source)
        self.assertNotIn("distance_to_screen_triangle", source)
        self.assertNotIn("distance_to_screen_segment", source)

    def test_d3d11_inflate_payload_uses_screen_radius_not_host_amount(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")
        amount_start = source.index("} else if (amount_tool) {")
        amount_body = source[amount_start:source.index("} else {", amount_start)]

        self.assertIn('\\"screen_radius\\":', amount_body)
        self.assertIn('\\"screen_brush\\":', amount_body)
        radius_start = source.index("std::string mesh_edit_screen_radius_json(")
        radius_body = source[radius_start:source.index("std::string mesh_edit_screen_brush_json(", radius_start)]
        self.assertIn('\\"world_view_projection\\":', radius_body)
        self.assertNotIn('\\"camera_world\\":', radius_body)
        self.assertIn("XMStoreFloat4x4(&world_view_projection, current_mvp_matrix())", radius_body)
        self.assertIn("mesh_edit_source_projection_overrides_json()", radius_body)
        self.assertNotIn('\\"distance\\":', radius_body)
        self.assertNotIn('\\"vertical_fov_degrees\\":', radius_body)
        self.assertNotIn('\\"center\\":', amount_body)
        self.assertNotIn("mesh_edit_average_position(candidates)", amount_body)
        self.assertNotIn('\\"amount\\":', amount_body)
        self.assertNotIn("amount_world", amount_body)

        native_source = Path("native/cdmw_mesh_core/src/main.cpp").read_text(encoding="utf-8")
        self.assertIn("mesh_editor_source_world_view_projection_from_json", native_source)
        self.assertIn("mesh_editor_screen_radius_units_at_center(screen_radius_payload, center, result.index)", native_source)

    def test_d3d11_screen_drag_payload_uses_cursor_endpoints(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")
        drag_start = source.index("std::string mesh_edit_screen_drag_json(")
        drag_body = source[drag_start:source.index("std::string mesh_edit_screen_radius_json(", drag_start)]
        payload_start = source.index("std::string mesh_edit_payload_json(")
        payload_body = source[payload_start:source.index("void send_mesh_edit_event(", payload_start)]

        self.assertIn('\\"start_x\\":', drag_body)
        self.assertIn('\\"end_x\\":', drag_body)
        self.assertIn('\\"world_view_projection\\":', drag_body)
        self.assertIn("XMStoreFloat4x4(&world_view_projection, current_mvp_matrix())", drag_body)
        self.assertIn("mesh_edit_source_projection_overrides_json()", drag_body)
        self.assertNotIn("const std::string screen_drag = mesh_edit_screen_drag_json", payload_body)
        self.assertEqual(2, payload_body.count("mesh_edit_screen_drag_json(mesh_edit_.last_x, mesh_edit_.last_y, x, y)"))
        for legacy_field in ('\\"yaw_degrees\\":', '\\"pitch_degrees\\":', '\\"distance\\":', '\\"vertical_fov_degrees\\":'):
            self.assertNotIn(legacy_field, drag_body)
        self.assertNotIn('\\"camera_world\\":', drag_body)
        self.assertNotIn("delta_x_pixels", drag_body)
        self.assertNotIn("end_x - start_x", drag_body)

        native_source = Path("native/cdmw_mesh_core/src/main.cpp").read_text(encoding="utf-8")
        self.assertIn("mesh_editor_screen_drag_projection_delta", native_source)
        self.assertIn("const Vec3 base_translate = screen_drag_projection_payload ? Vec3{0.0, 0.0, 0.0} : transform.translate", native_source)
        self.assertIn("add_screen_drag_delta(base_translate, screen_drag, &transform.pivot, result.index)", native_source)
        self.assertIn("const Vec3 drag_base = screen_drag_projection_payload", native_source)
        self.assertIn("add_screen_drag_delta(\n        drag_base,", native_source)
        self.assertIn("result.index\n    );", native_source)

    def test_d3d11_smooth_payload_sends_screen_brush_context(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")
        brush_start = source.index("std::string mesh_edit_screen_brush_json(")
        brush_body = source[brush_start:source.index("std::string mesh_edit_screen_region_json(", brush_start)]
        payload_start = source.index("std::string mesh_edit_payload_json(")
        payload_body = source[payload_start:source.index("void send_mesh_edit_event(", payload_start)]
        smooth_start = source.index("} else if (smooth_tool) {")
        smooth_body = source[smooth_start:source.index("} else if (amount_tool) {", smooth_start)]
        begin_start = source.index("bool begin_mesh_edit_drag(")
        begin_body = source[begin_start:source.index("bool update_mesh_edit_drag(", begin_start)]
        update_start = source.index("bool update_mesh_edit_drag(")
        update_body = source[update_start:source.index("bool finish_mesh_edit_drag(", update_start)]

        self.assertIn('\\"x\\":', brush_body)
        self.assertIn('\\"radius_pixels\\":', brush_body)
        self.assertIn('\\"viewport_width\\":', brush_body)
        self.assertIn('\\"world_view_projection\\":', brush_body)
        self.assertIn("XMStoreFloat4x4(&world_view_projection, current_mvp_matrix())", brush_body)
        for legacy_field in ('\\"camera_world\\":', '\\"yaw_degrees\\":', '\\"pitch_degrees\\":', '\\"distance\\":', '\\"vertical_fov_degrees\\":', '\\"pan\\":'):
            self.assertNotIn(legacy_field, brush_body)
        self.assertIn('\\"source_submesh_indices\\":[', brush_body)
        self.assertIn('const bool grab_screen_brush_tool = grab_tool && mesh_edit_.target_mode != "selection";', payload_body)
        self.assertIn("bool include_screen_selection = false", payload_body)
        self.assertIn("screen_brush_tool || include_screen_selection", payload_body)
        self.assertIn('const bool remove_screen_tool = tool == "remove" && mesh_edit_.delete_mode != "selection";', payload_body)
        self.assertIn("const bool screen_brush_tool = grab_screen_brush_tool || smooth_tool || amount_tool || remove_screen_tool", payload_body)
        self.assertNotIn("mesh_edit_falloff_weight", source)
        self.assertIn('\\"target_mode\\":', payload_body)
        self.assertIn('\\"selection_depth_mode\\":', payload_body)
        self.assertIn('\\"screen_brush\\":', smooth_body)
        self.assertIn("const bool has_resident_selection = !mesh_edit_.selected_vertices.empty()", begin_body)
        self.assertIn("|| !mesh_edit_.selected_edges.empty()", begin_body)
        self.assertIn("|| !mesh_edit_.selected_faces.empty()", begin_body)
        self.assertIn("|| !mesh_edit_.selected_sources.empty();", begin_body)
        self.assertIn('move_screen_selection_tool = mesh_edit_.tool == "move" && !has_resident_selection', begin_body)
        self.assertIn('grab_screen_selection_tool = mesh_edit_.tool == "grab" && mesh_edit_.target_mode == "selection" && !has_resident_selection', begin_body)
        self.assertIn("bool screen_selection_tool = move_screen_selection_tool || grab_screen_selection_tool", begin_body)
        self.assertIn("bool resident_selection_drag_tool = selection_drag_tool && has_resident_selection", begin_body)
        self.assertIn("bool native_selection_tool = screen_brush_tool || resident_selection_drag_tool", begin_body)
        self.assertIn('mesh_edit_.tool == "grab" && mesh_edit_.target_mode != "selection"', begin_body)
        self.assertIn("bool screen_brush_tool = screen_selection_tool", begin_body)
        self.assertIn("drag_uses_resident_selection = screen_selection_tool || resident_selection_drag_tool", begin_body)
        self.assertIn("if (!native_selection_tool) return true;", begin_body)
        self.assertIn('send_mesh_edit_event("mesh_edit_stroke_started", mesh_edit_payload_json(x, y, false, screen_selection_tool));', begin_body)
        self.assertNotIn("drag_candidates", begin_body)
        self.assertNotIn("mesh_edit_payload_json(candidates", begin_body)
        self.assertIn("screen_brush_update_tool", update_body)
        self.assertIn("resident_selection_drag = drag_mode && mesh_edit_.drag_uses_resident_selection", update_body)
        self.assertIn('mesh_edit_.tool == "grab" && mesh_edit_.target_mode != "selection"', update_body)
        self.assertIn("!screen_brush_update_tool && !resident_selection_drag", update_body)
        self.assertIn('send_mesh_edit_event("mesh_edit_stroke_previewed", mesh_edit_payload_json(x, y, ctrl_down));', update_body)
        self.assertNotIn("mesh_edit_payload_json(candidates", update_body)
        self.assertNotIn("mesh_edit_groups_json", source)

    def test_d3d11_remove_payload_sends_screen_brush_without_groups(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")
        payload_start = source.index("std::string mesh_edit_payload_json(")
        payload_body = source[payload_start:source.index("void send_mesh_edit_event(", payload_start)]
        remove_start = payload_body.index("} else if (remove_screen_tool) {")
        remove_body = payload_body[remove_start:]
        begin_start = source.index("bool begin_mesh_edit_drag(")
        begin_body = source[begin_start:source.index("bool update_mesh_edit_drag(", begin_start)]
        update_start = source.index("bool update_mesh_edit_drag(")
        update_body = source[update_start:source.index("bool finish_mesh_edit_drag(", update_start)]

        self.assertIn('remove_screen_tool = tool == "remove" && mesh_edit_.delete_mode != "selection"', payload_body)
        self.assertIn('remove_screen_tool ? "face"', payload_body)
        self.assertIn('\\"delete_mode\\":\\"', remove_body)
        self.assertIn("json_escape(mesh_edit_.delete_mode)", remove_body)
        self.assertIn('\\"screen_brush\\":', remove_body)
        self.assertIn('\\"falloff\\":', remove_body)
        self.assertNotIn("mesh_edit_average_position", remove_body)
        self.assertNotIn('\\"screen_radius\\":', remove_body)
        self.assertIn('remove_screen_tool = mesh_edit_.tool == "remove" && mesh_edit_.delete_mode != "selection"', begin_body)
        self.assertIn("|| remove_screen_tool", begin_body)
        self.assertIn("native_selection_tool", begin_body)
        self.assertIn("!native_selection_tool", begin_body)
        self.assertIn('remove_screen_tool = mesh_edit_.tool == "remove" && mesh_edit_.delete_mode != "selection"', update_body)
        self.assertIn("screen_brush_update_tool = remove_screen_tool", update_body)
        self.assertIn("!screen_brush_update_tool && !resident_selection_drag", update_body)

    def test_d3d11_grab_brush_target_payload_sends_screen_brush_without_groups(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")
        payload_start = source.index("std::string mesh_edit_payload_json(")
        payload_body = source[payload_start:source.index("void send_mesh_edit_event(", payload_start)]
        grab_start = payload_body.index("if (grab_tool) {")
        grab_body = payload_body[grab_start:payload_body.index("} else if (smooth_tool) {", grab_start)]
        begin_start = source.index("bool begin_mesh_edit_drag(")
        begin_body = source[begin_start:source.index("bool update_mesh_edit_drag(", begin_start)]
        update_start = source.index("bool update_mesh_edit_drag(")
        update_body = source[update_start:source.index("bool finish_mesh_edit_drag(", update_start)]

        self.assertIn('grab_screen_brush_tool = grab_tool && mesh_edit_.target_mode != "selection"', payload_body)
        self.assertIn('\\"screen_drag\\":', grab_body)
        self.assertIn('\\"screen_brush\\":', grab_body)
        self.assertIn('\\"falloff\\":', grab_body)
        self.assertIn('mesh_edit_.tool == "grab" && mesh_edit_.target_mode != "selection"', begin_body)
        self.assertIn('grab_screen_selection_tool = mesh_edit_.tool == "grab" && mesh_edit_.target_mode == "selection" && !has_resident_selection', begin_body)
        self.assertIn('send_mesh_edit_event("mesh_edit_stroke_started", mesh_edit_payload_json(x, y, false, screen_selection_tool));', begin_body)
        self.assertIn('mesh_edit_.tool == "grab" && mesh_edit_.target_mode != "selection"', update_body)
        self.assertIn('send_mesh_edit_event("mesh_edit_stroke_previewed", mesh_edit_payload_json(x, y, ctrl_down));', update_body)

    def test_d3d11_selected_drag_begin_uses_resident_selection_without_groups(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")
        begin_start = source.index("bool begin_mesh_edit_drag(")
        begin_body = source[begin_start:source.index("bool update_mesh_edit_drag(", begin_start)]
        update_start = source.index("bool update_mesh_edit_drag(")
        update_body = source[update_start:source.index("bool finish_mesh_edit_drag(", update_start)]

        self.assertNotIn("mesh_edit_selected_candidates()", begin_body)
        self.assertIn('selection_drag_tool = mesh_edit_.target_mode == "selection"', begin_body)
        self.assertIn("resident_selection_drag_tool = selection_drag_tool && has_resident_selection", begin_body)
        self.assertIn("native_selection_tool = screen_brush_tool || resident_selection_drag_tool", begin_body)
        self.assertIn("drag_uses_resident_selection = screen_selection_tool || resident_selection_drag_tool", begin_body)
        self.assertIn('send_mesh_edit_event("mesh_edit_stroke_started", mesh_edit_payload_json(x, y, false, screen_selection_tool));', begin_body)
        self.assertNotIn("mesh_edit_payload_json(candidates", begin_body)
        self.assertIn("resident_selection_drag = drag_mode && mesh_edit_.drag_uses_resident_selection", update_body)
        self.assertIn("!screen_brush_update_tool && !resident_selection_drag", update_body)
        self.assertNotIn("drag_candidates", update_body)

    def test_native_mesh_editor_d3d11_delta_scenario_uses_vertex_update_without_fallback(self) -> None:
        if not native_mesh_core_available():
            self.skipTest("native mesh core binary not built")
        if find_native_d3d11_host() is None:
            self.skipTest("native D3D11 preview host not built")
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")):
                result = run_scenario("native-mesh-editor-d3d11-delta", Path(temp_dir), allow_synthetic_d3d11=True)

        self.assertTrue(result["ok"])
        d3d11_delta = result["native_mesh_editor_d3d11_delta"]
        self.assertTrue(d3d11_delta["native_core_available"])
        self.assertTrue(d3d11_delta["transform_delta_ok"])
        self.assertTrue(d3d11_delta["transform_screen_payload_ok"])
        self.assertTrue(d3d11_delta["transform_dispatch_target_ok"])
        self.assertTrue(d3d11_delta["dispatch_target_ok"])
        self.assertEqual(["update_mesh_edit_vertices"], d3d11_delta["transform_host_calls"])
        self.assertEqual("mesh_edit_vertices_updated", d3d11_delta["transform_update_event"]["event"])
        self.assertGreater(d3d11_delta["transform_update_event"]["changed_vertices"], 0)
        self.assertEqual(0, d3d11_delta["transform_triangle_group_count"])
        self.assertFalse(d3d11_delta["transform_replace_all_triangles"])
        self.assertGreaterEqual(d3d11_delta["transform_command"]["metrics"]["d3d11_update_ms"], 0.0)
        self.assertTrue(d3d11_delta["delta_only_ok"])
        self.assertTrue(d3d11_delta["brush_screen_payload_ok"])
        self.assertTrue(d3d11_delta["screen_payloads_without_legacy_camera_fields_ok"])
        self.assertTrue(d3d11_delta["screen_payloads_with_source_transform_overrides_ok"])
        self.assertTrue(d3d11_delta["brush_dispatch_target_ok"])
        self.assertEqual(["update_mesh_edit_vertices"], d3d11_delta["host_calls"])
        self.assertEqual("mesh_edit_vertices_updated", d3d11_delta["update_event"]["event"])
        self.assertGreater(d3d11_delta["update_event"]["changed_vertices"], 0)
        self.assertEqual(0, d3d11_delta["triangle_group_count"])
        self.assertFalse(d3d11_delta["replace_all_triangles"])
        self.assertTrue(d3d11_delta["native_fallback_ok"])
        self.assertEqual({}, d3d11_delta["native_fallback_counts"])
        self.assertTrue(d3d11_delta["native_apply_and_d3d11_metrics_ok"])
        self.assertTrue(d3d11_delta["native_history_and_d3d11_metrics_ok"])
        self.assertGreaterEqual(d3d11_delta["d3d11_update_ms"], 0.0)
        self.assertGreaterEqual(d3d11_delta["command"]["metrics"]["d3d11_update_ms"], 0.0)
        self.assertTrue(d3d11_delta["topology_delta_ok"])
        self.assertIn("replace_mesh_edit_triangles", d3d11_delta["topology_host_calls"])
        self.assertNotIn("update_mesh_edit_vertices", d3d11_delta["topology_host_calls"])
        self.assertEqual("mesh_edit_triangles_replaced", d3d11_delta["topology_update_event"]["event"])
        self.assertGreaterEqual(d3d11_delta["topology_update_event"]["replaced_batches"], 1)
        self.assertEqual([0], d3d11_delta["topology_triangle_calls"][0]["source_submesh_indices"])
        self.assertFalse(d3d11_delta["topology_replace_all_triangles"])
        self.assertGreaterEqual(d3d11_delta["topology_command"]["metrics"]["d3d11_update_ms"], 0.0)
        self.assertTrue(d3d11_delta["appended_delta_ok"])
        self.assertIn("replace_mesh_edit_triangles", d3d11_delta["appended_host_calls"])
        self.assertNotIn("update_mesh_edit_vertices", d3d11_delta["appended_host_calls"])
        self.assertEqual("mesh_edit_triangles_replaced", d3d11_delta["appended_update_event"]["event"])
        self.assertGreaterEqual(d3d11_delta["appended_update_event"]["replaced_batches"], 1)
        self.assertEqual([1], d3d11_delta["appended_triangle_calls"][0]["source_submesh_indices"])
        self.assertFalse(d3d11_delta["appended_replace_all_triangles"])
        self.assertGreater(d3d11_delta["appended_command"]["submesh_count_delta"], 0)
        self.assertGreaterEqual(d3d11_delta["appended_command"]["metrics"]["d3d11_update_ms"], 0.0)
        self.assertTrue(d3d11_delta["separated_delta_ok"])
        self.assertIn("replace_mesh_edit_triangles", d3d11_delta["separated_host_calls"])
        self.assertNotIn("update_mesh_edit_vertices", d3d11_delta["separated_host_calls"])
        self.assertEqual("mesh_edit_triangles_replaced", d3d11_delta["separated_update_event"]["event"])
        self.assertGreaterEqual(d3d11_delta["separated_update_event"]["replaced_batches"], 1)
        self.assertEqual([0, 2], d3d11_delta["separated_triangle_calls"][0]["source_submesh_indices"])
        self.assertFalse(d3d11_delta["separated_replace_all_triangles"])
        self.assertGreater(d3d11_delta["separated_command"]["submesh_count_delta"], 0)
        self.assertGreaterEqual(d3d11_delta["separated_command"]["metrics"]["d3d11_update_ms"], 0.0)

    def test_native_mesh_editor_d3d11_payload_scenario_proves_source_transform_overrides(self) -> None:
        if find_native_d3d11_host() is None:
            self.skipTest("native D3D11 preview host not built")
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_scenario("native-mesh-editor-d3d11-payloads", Path(temp_dir), allow_synthetic_d3d11=True)

        self.assertTrue(result["ok"])
        payloads = result["native_mesh_editor_d3d11_payloads"]
        self.assertTrue(payloads["screen_payloads_without_legacy_camera_fields_ok"])
        self.assertTrue(payloads["screen_payloads_with_source_transform_overrides_ok"])
        self.assertEqual("alignment_transforms", payloads["alignment_transform_status"]["event"])
        self.assertTrue(payloads["alignment_transform_status"]["ok"])

    def test_synthetic_d3d11_scenarios_are_blocked_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_scenario("native-mesh-editor-d3d11-delta", Path(temp_dir))

        self.assertFalse(result["ok"])
        self.assertIn("Synthetic Mesh Editor D3D11", result["error"])
        self.assertIn("real-archive-mesh-editor-d3d11-side-by-side-edit-smoke", result["error"])

        with tempfile.TemporaryDirectory() as temp_dir:
            full_suite = run_scenario("full-suite-smoke", Path(temp_dir))

        self.assertFalse(full_suite["ok"])
        self.assertIn("real-archive-mesh-editor-d3d11-side-by-side-edit-smoke", full_suite["error"])

    def test_mesh_editor_harness_defaults_to_real_archive_visual_proof(self) -> None:
        source = Path("tools/mesh_editor_dev_harness.py").read_text(encoding="utf-8")

        self.assertIn('_REAL_MESH_EDITOR_VISUAL_SCENARIO = "real-archive-mesh-editor-d3d11-side-by-side-edit-smoke"', source)
        self.assertIn("default=_REAL_MESH_EDITOR_VISUAL_SCENARIO", source)

    def test_codex_mesh_check_runs_real_game_proof_not_synthetic_square(self) -> None:
        source = Path("scripts/codex_check.ps1").read_text(encoding="utf-8")

        self.assertIn('"mesh", "mesh-unit"', source)
        self.assertIn('if ($Area -eq "mesh")', source)
        self.assertIn("real-archive-mesh-editor-d3d11-side-by-side-edit-smoke", source)
        self.assertIn('Synthetic unit coverage moved to -Area mesh-unit', source)
        self.assertIn('"mesh-unit" = @(', source)

    def test_native_benchmark_mesh_meets_target_counts(self) -> None:
        mesh = build_native_benchmark_mesh()

        self.assertGreaterEqual(mesh.total_vertices, 100_000)
        self.assertGreaterEqual(mesh.total_faces, 200_000)
        self.assertEqual(mesh.total_vertices, len(mesh.submeshes[0].vertices))
        self.assertEqual(mesh.total_faces, len(mesh.submeshes[0].faces))

    def test_sequence_reference_overlap_summarizes_source_compiled_clip_refs(self) -> None:
        overlap = _sequence_reference_overlap(
            (
                "character/motion/a_idle.paa",
                "character/motion/b_idle.paa",
                "effect/hit.paem",
            ),
            (
                "CHARACTER/MOTION/A_IDLE.PAA",
                "character/motion/c_idle.paa",
            ),
            active_path="character/motion/a_idle.paa",
        )

        self.assertEqual("source_compiled_clip_reference_overlap", overlap["status"])
        self.assertEqual("proven_reference_string_overlap", overlap["confidence"])
        self.assertEqual(3, overlap["source_reference_count"])
        self.assertEqual(2, overlap["compiled_reference_count"])
        self.assertEqual(1, overlap["overlap_reference_count"])
        self.assertEqual(2, overlap["source_only_reference_count"])
        self.assertEqual(1, overlap["compiled_only_reference_count"])
        self.assertEqual(1, overlap["overlap_paa_reference_count"])
        self.assertTrue(overlap["active_clip_in_overlap"])
        self.assertEqual(("character/motion/a_idle.paa",), overlap["overlap_paths"])

    def test_sequence_lane_pair_summary_maps_source_and_compiled_lane_offsets(self) -> None:
        source_timeline = {
            "lanes": (
                {"index": 0, "path": "character/motion/a_idle.paa", "source_offset": 120, "confidence": "string_path"},
                {"index": 1, "path": "character/motion/b_idle.paa", "source_offset": 240, "confidence": "string_path"},
            )
        }
        compiled_timeline = {
            "lanes": (
                {"index": 0, "path": "CHARACTER/MOTION/A_IDLE.PAA", "source_offset": 48, "confidence": "string_path"},
            )
        }

        summary = _sequence_lane_pair_summary(
            source_timeline,
            compiled_timeline,
            active_path="character/motion/a_idle.paa",
        )

        self.assertEqual("source_compiled_lane_pair_overlap", summary["status"])
        self.assertEqual(2, summary["source_lane_count"])
        self.assertEqual(1, summary["compiled_lane_count"])
        self.assertEqual(1, summary["lane_pair_count"])
        self.assertEqual(1, summary["active_lane_pair_count"])
        pair = summary["lane_pairs"][0]
        self.assertEqual("character/motion/a_idle.paa", pair["path"])
        self.assertEqual(0, pair["source_lane_index"])
        self.assertEqual(0, pair["compiled_lane_index"])
        self.assertEqual(120, pair["source_offset"])
        self.assertEqual(48, pair["compiled_offset"])
        self.assertTrue(pair["active_clip"])
        self.assertEqual("source_compiled_lane_pair_read_only", pair["status"])

    def test_sequence_event_marker_overlap_maps_source_and_compiled_offsets(self) -> None:
        summary = _sequence_event_marker_overlap(
            {
                "event_markers": (
                    {"text": "Trigger_00", "offset": 120, "role": "event"},
                    {"text": "_startTimePiece", "offset": 240, "role": "timing"},
                    {"text": "source_only", "offset": 360, "role": "event"},
                )
            },
            {
                "event_markers": (
                    {"text": "trigger_00", "offset": 48, "role": "event"},
                    {"text": "compiled_only", "offset": 96, "role": "event"},
                )
            },
        )

        self.assertEqual("source_compiled_event_marker_overlap", summary["status"])
        self.assertEqual("proven_readable_string_overlap", summary["confidence"])
        self.assertEqual(3, summary["source_marker_count"])
        self.assertEqual(2, summary["compiled_marker_count"])
        self.assertEqual(1, summary["overlap_marker_count"])
        self.assertEqual(2, summary["source_only_marker_count"])
        self.assertEqual(1, summary["compiled_only_marker_count"])
        row = summary["overlap_markers"][0]
        self.assertEqual("Trigger_00", row["text"])
        self.assertEqual(120, row["source_offset"])
        self.assertEqual(48, row["compiled_offset"])
        self.assertEqual("source_compiled_event_marker_overlap_read_only", row["status"])

    def test_sequence_timeline_field_overlap_deduplicates_field_names(self) -> None:
        summary = _sequence_timeline_field_overlap(
            {
                "timeline_fields": (
                    {"name": "_startTimePiece", "offset": 120, "role": "timing", "declared_type": "int32"},
                    {"name": "_startTimePiece", "offset": 240, "role": "timing", "declared_type": "int32"},
                    {"name": "_framesPerSecond", "offset": 360, "role": "timing", "declared_type": "int32"},
                )
            },
            {
                "timeline_fields": (
                    {"name": "_STARTTIMEPIECE", "offset": 48, "role": "timing", "declared_type": "int32"},
                    {"name": "_startBlendTime", "offset": 96, "role": "timing", "declared_type": "float"},
                )
            },
        )

        self.assertEqual("source_compiled_timeline_field_overlap", summary["status"])
        self.assertEqual("proven_field_name_overlap", summary["confidence"])
        self.assertEqual(2, summary["source_unique_field_count"])
        self.assertEqual(2, summary["compiled_unique_field_count"])
        self.assertEqual(1, summary["overlap_field_count"])
        self.assertEqual(1, summary["source_only_field_count"])
        self.assertEqual(1, summary["compiled_only_field_count"])
        row = summary["overlap_fields"][0]
        self.assertEqual("_startTimePiece", row["name"])
        self.assertEqual(120, row["source_offset"])
        self.assertEqual(48, row["compiled_offset"])
        self.assertEqual(("_framesPerSecond",), summary["source_only_fields"])
        self.assertEqual(("_startBlendTime",), summary["compiled_only_fields"])

    def test_sequence_timeline_field_semantic_aliases_match_source_only_fields(self) -> None:
        summary = _sequence_timeline_field_semantic_aliases(
            {
                "timeline_fields": (
                    {"name": "_startBlendingTime", "offset": 120, "role": "timing", "declared_type": "float"},
                    {"name": "_endBlendingTime", "offset": 180, "role": "timing", "declared_type": "float"},
                    {"name": "_hasTransformBlend", "offset": 240, "role": "timing", "declared_type": "bool"},
                )
            },
            {
                "timeline_fields": (
                    {"name": "_startBlendTime", "offset": 48, "role": "timing", "declared_type": "float"},
                    {"name": "_hasTransformBlend", "offset": 96, "role": "timing", "declared_type": "bool"},
                )
            },
        )

        self.assertEqual("source_compiled_timeline_field_semantic_aliases", summary["status"])
        self.assertEqual("inferred_name_alias_value_unbound", summary["confidence"])
        self.assertEqual(1, summary["alias_count"])
        row = summary["alias_rows"][0]
        self.assertEqual("_startBlendingTime", row["source_name"])
        self.assertEqual("_startBlendTime", row["compiled_name"])
        self.assertEqual("startblendtime", row["alias_key"])
        self.assertEqual(120, row["source_offset"])
        self.assertEqual(48, row["compiled_offset"])
        self.assertIn("_endBlendingTime", summary["unmatched_source_fields"])
        self.assertNotIn("_hasTransformBlend", summary["unmatched_source_fields"])

    def test_sequence_path_record_context_reports_read_only_byte_window(self) -> None:
        path = "character/motion/a_idle.paa"
        actor = b"actor"
        path_bytes = path.encode("ascii")
        data = (
            b"\x00" * 8
            + struct.pack("<I", len(actor))
            + actor
            + struct.pack("<I", len(path_bytes))
            + path_bytes
            + struct.pack("<I", 30)
            + struct.pack("<f", 2.0)
        )

        context = _sequence_path_record_context(data, path, window_before=24, window_after=len(path_bytes) + 12)

        text_offset = data.index(path_bytes)
        self.assertEqual("path_record_window_recovered", context["status"])
        self.assertEqual("active_lane_record_layout_unbound", context["binding_status"])
        self.assertEqual(text_offset, context["path_text_offset"])
        self.assertEqual(text_offset - 4, context["path_length_offset"])
        self.assertEqual(2, context["length_prefixed_string_count"])
        self.assertEqual(1, context["fps_like_u32_count"])
        self.assertEqual(1, context["float32_candidate_count"])
        self.assertEqual("actor", context["length_prefixed_strings"][0]["text"])
        self.assertEqual(path, context["length_prefixed_strings"][1]["text"])
        self.assertIn((text_offset + len(path_bytes), 30), tuple((row["offset"], row["u32"]) for row in context["scalar_rows"]))

    def test_mesh_editor_native_runtime_writes_preview_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "preview_package"

            package_dir = mesh_editor_write_native_preview_package(
                build_synthetic_mesh("pam"),
                output_root=output_dir,
                use_textures=False,
            )
            manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(output_dir, package_dir)
            self.assertEqual("pam", manifest["format"])
            self.assertEqual(1, len(manifest["batches"]))
            self.assertTrue((package_dir / "geometry" / "geometry.bin").is_file())

    def test_mesh_editor_native_runtime_writes_overlay_compare_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "compare_package"
            source_mesh = build_synthetic_mesh("pam")
            edited_mesh = build_synthetic_mesh("pam")
            edited_mesh.submeshes[0].vertices[0] = (0.0, 0.0, 0.5)

            package_dir = mesh_editor_write_native_preview_package(
                edited_mesh,
                reference_mesh=source_mesh,
                output_root=output_dir,
                use_textures=False,
                display_mode="overlay",
            )
            manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual("overlay", manifest["display_mode"])
            self.assertEqual(2, len(manifest["batches"]))
            self.assertEqual("original_reference", manifest["batches"][0]["editor_identity"]["role"])
            self.assertFalse(manifest["batches"][0]["editor_identity"]["editable"])
            self.assertEqual("replacement_preview", manifest["batches"][1]["editor_identity"]["role"])
            self.assertTrue(manifest["batches"][1]["editor_identity"]["editable"])

    def test_mesh_editor_native_runtime_builds_host_command(self) -> None:
        package_dir = Path("C:/tmp/mesh-editor-package")
        status_file = Path("C:/tmp/mesh-editor-status.json")
        host = Path("C:/native/cdmw-d3d11-preview.exe")

        with patch("cdmw.ui.mesh_editor.native_preview_runtime.find_native_d3d11_host", return_value=host):
            program, args = mesh_editor_native_preview_command(
                package_dir,
                status_file,
                crash_dir=Path("C:/tmp/crash"),
                diagnostic_log=Path("C:/tmp/native.jsonl"),
            )

        self.assertEqual(str(host), program)
        self.assertIn("--preview-package", args)
        self.assertIn(str(package_dir), args)
        self.assertIn("--status-file", args)
        self.assertIn(str(status_file), args)
        self.assertIn("--crash-dir", args)
        self.assertIn(str(Path("C:/tmp/crash")), args)

    def test_real_archive_playback_sampler_reports_preview_only_geometry(self) -> None:
        mesh = build_synthetic_mesh("pac")
        mesh.has_bones = True
        mesh.submeshes[0].bone_indices = [(0,), (0,), (0,), (0,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        skeleton = Skeleton(bones=[Bone(index=0, name="Root", parent_index=-1)], bone_count=1)
        clip = MeshAnimationClip(
            source="sequence_clip.paa",
            duration_seconds=1.0,
            tracks=(
                MeshAnimationTrack(
                    bone_name="Root",
                    rotation_keyframes=(
                        MeshAnimationKeyframe(0.0, (0.0, 0.0, 0.0)),
                        MeshAnimationKeyframe(1.0, (0.0, 0.0, 90.0)),
                    ),
                ),
            ),
            sequence_segments=(
                MeshAnimationSequenceSegment(
                    sequence_path="sequencer/binary__/sequence_sample.paseqc",
                    clip_path="sequence_clip.paa",
                    lane_index=5,
                    start_seconds=0.0,
                    end_seconds=1.0,
                    status="paseqc_lane_bound_to_paa_clip_preview_only_sequence_semantics_unknown",
                ),
            ),
            frame_rate=30.0,
            timing_confidence="inferred",
            timing_status="default_30fps_unproven",
        )

        sample = _sample_real_archive_paa_playback(mesh, skeleton, clip)

        self.assertTrue(sample["ready"])
        self.assertTrue(sample["enabled"])
        self.assertGreater(sample["sampled_bone_count"], 0)
        self.assertEqual(sample["sampled_bone_count"], sample["repeat_sampled_bone_count"])
        self.assertEqual(5, sample["active_sequence_lane_index"])
        self.assertEqual("sequencer/binary__/sequence_sample.paseqc", sample["active_sequence_path"])
        self.assertEqual("sequence_clip.paa", sample["active_sequence_clip_path"])
        self.assertIn("paseqc_lane_bound", sample["active_sequence_status"])
        self.assertTrue(sample["pose_changed"])
        self.assertTrue(sample["deterministic_repeat_seek"])
        self.assertEqual(sample["time_seconds"], sample["repeat_time_seconds"])
        self.assertTrue(sample["export_geometry_unchanged"])
        self.assertEqual("default_30fps_unproven", sample["timing_status"])

    def test_papr_constraint_summary_exposes_record_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            entry = ArchiveEntry(
                path="character/model/body.papr",
                pamt_path=root / "0009" / "0.pamt",
                paz_file=root / "0009" / "0.paz",
                offset=0,
                comp_size=0,
                orig_size=0,
                flags=0,
                paz_index=0,
            )
            gap = struct.pack("<I", 0) + struct.pack("<f", 0.5) + struct.pack("<I", 24) + struct.pack("<I", 1)
            data = (
                b"PAR "
                + b"Bip01 Head\x00" + gap + b"P_Bip01 Head\x00" + gap + b"Bip01 Head_Dummy\x00"
            )
            data += (b"\x00" * (((len(data) + 3) & ~3) - len(data))) + struct.pack("<f", 3.0) + struct.pack("<f", 30.5) + gap
            data += b"Local_Euler_Z*3+30.5\x00" + gap + b"amin(Local_Euler_Z*5+9.8) -1\x00"

            summary = _papr_constraint_metadata_summary(data, entry)

            self.assertEqual(5, summary["constraint_string_evidence"])
            self.assertGreaterEqual(summary["constraint_record_candidates"], 2)
            self.assertGreaterEqual(len(summary["constraint_record_candidate_rows"]), 2)
            self.assertGreaterEqual(summary["constraint_expression_evidence"]["channel_counts"]["Local_Euler_Z"], 2)
            self.assertGreaterEqual(summary["constraint_expression_evidence"]["shape_counts"]["linear_channel_transform_candidate"], 1)
            self.assertGreaterEqual(summary["constraint_expression_evidence"]["shape_counts"]["limit_linear_channel_transform_candidate"], 1)
            self.assertGreaterEqual(summary["constraint_expression_evidence"]["numeric_role_counts"]["channel_coefficient"], 2)
            self.assertGreaterEqual(summary["constraint_expression_evidence"]["numeric_role_counts"]["additive_offset"], 2)
            self.assertGreaterEqual(summary["constraint_expression_evidence"]["numeric_role_counts"]["limit_argument"], 1)
            self.assertGreaterEqual(
                sum(summary["constraint_expression_evidence"]["syntax_signature_counts"].values()),
                1,
            )
            self.assertTrue(
                any(
                    "shape=linear_channel_transform_candidate" in signature
                    for signature in summary["constraint_expression_evidence"]["syntax_signature_counts"]
                )
            )
            self.assertEqual("unknown", summary["constraint_expression_evidence"]["semantics_confidence"])
            self.assertGreaterEqual(summary["constraint_expression_shape_counts"]["linear_channel_transform_candidate"], 1)
            self.assertGreaterEqual(summary["constraint_expression_numeric_role_counts"]["channel_coefficient"], 2)
            self.assertGreaterEqual(summary["constraint_expression_channel_counts"]["Local_Euler_Z"], 2)
            self.assertGreaterEqual(summary["constraint_limit_operator_counts"]["amin"], 1)
            self.assertGreaterEqual(summary["constraint_expression_numeric_values"], 1)
            self.assertGreaterEqual(summary["constraint_offset_evidence"]["target_offset_count"], 1)
            self.assertEqual("proven", summary["constraint_offset_evidence"]["offset_confidence"])
            self.assertGreaterEqual(summary["constraint_offset_field_counts"]["target"], 1)
            layout = summary["constraint_record_layout_evidence"]
            self.assertEqual("nearby_string_span_layout_evidence", layout["status"])
            self.assertGreaterEqual(layout["candidate_count"], 2)
            self.assertGreater(layout["max_span_size"], 0)
            self.assertGreaterEqual(layout["field_sequence_counts"]["parent>helper>target>expression"], 2)
            self.assertEqual("proven_decoded_string_offset_order", layout["field_sequence_confidence"])
            self.assertGreaterEqual(layout["gap_status_counts"]["binary_like_interfield_gap_bytes_unbound"], 1)
            self.assertGreaterEqual(sum(layout["gap_class_counts"].values()), 1)
            self.assertGreaterEqual(layout["gap_pair_count"], 1)
            self.assertGreater(layout["max_gap_size"], 0)
            self.assertGreaterEqual(layout["gap_scalar_status_counts"]["unbound_interfield_scalar_candidates"], 1)
            self.assertGreaterEqual(layout["gap_scalar_kind_counts"]["f32_unit_candidate"], 1)
            self.assertGreaterEqual(layout["gap_aligned_word_count"], 1)
            self.assertGreaterEqual(layout["gap_scalar_candidate_count"], 1)
            self.assertGreaterEqual(layout["gap_numeric_match_status_counts"]["unbound_scalar_numeric_constant_matches"], 1)
            self.assertGreaterEqual(layout["gap_numeric_match_role_counts"]["channel_coefficient"], 1)
            self.assertGreaterEqual(layout["gap_numeric_match_role_counts"]["additive_offset"], 1)
            self.assertGreaterEqual(layout["gap_numeric_match_pair_counts"]["target>expression"], 1)
            self.assertGreaterEqual(sum(layout["gap_numeric_match_value_confidence_counts"].values()), 1)
            self.assertGreaterEqual(
                layout["gap_numeric_match_value_confidence_counts"]["exact_float32_numeric_value_match_layout_unproven"],
                1,
            )
            self.assertGreaterEqual(layout["gap_numeric_match_family_counts"]["driver_expression_candidate"], 1)
            self.assertGreaterEqual(layout["gap_numeric_match_family_row_counts"]["driver_expression_candidate"], 1)
            self.assertGreaterEqual(
                layout["gap_numeric_match_family_role_counts"]["driver_expression_candidate"]["channel_coefficient"],
                1,
            )
            self.assertGreaterEqual(
                layout["gap_numeric_match_family_pair_counts"]["driver_expression_candidate"]["target>expression"],
                1,
            )
            self.assertGreaterEqual(
                layout["gap_numeric_match_family_value_confidence_counts"]["driver_expression_candidate"][
                    "exact_float32_numeric_value_match_layout_unproven"
                ],
                1,
            )
            self.assertGreaterEqual(sum(layout["gap_numeric_match_signature_counts"].values()), 1)
            self.assertGreaterEqual(sum(layout["gap_numeric_match_candidate_relative_signature_counts"].values()), 1)
            self.assertTrue(
                any(
                    "family=driver_expression_candidate" in signature
                    and "role=channel_coefficient" in signature
                    for signature in layout["gap_numeric_match_signature_counts"]
                )
            )
            self.assertTrue(
                any(
                    "family=driver_expression_candidate" in signature
                    and "rel=" in signature
                    for signature in layout["gap_numeric_match_candidate_relative_signature_counts"]
                )
            )
            self.assertGreaterEqual(sum(layout["gap_numeric_match_previous_delta_counts"].values()), 1)
            self.assertGreaterEqual(sum(layout["gap_numeric_match_next_delta_counts"].values()), 1)
            self.assertGreaterEqual(sum(layout["gap_numeric_match_candidate_relative_offset_counts"].values()), 1)
            self.assertEqual(
                "observed_relative_to_decoded_string_gap_boundaries_value_layout_unproven",
                layout["gap_numeric_match_offset_confidence"],
            )
            self.assertEqual(
                "observed_relative_to_inferred_candidate_offset_value_layout_unproven",
                layout["gap_numeric_match_candidate_relative_offset_confidence"],
            )
            self.assertGreaterEqual(layout["gap_numeric_match_count"], 1)
            self.assertGreaterEqual(len(layout["gap_numeric_match_rows"]), 1)
            self.assertEqual(
                summary["constraint_record_candidate_rows"][0]["offset"],
                layout["gap_numeric_match_rows"][0]["candidate_offset"],
            )
            self.assertEqual(
                layout["gap_numeric_match_rows"][0]["match_offset"]
                - layout["gap_numeric_match_rows"][0]["candidate_offset"],
                layout["gap_numeric_match_rows"][0]["candidate_relative_offset"],
            )
            self.assertEqual("driver_expression_candidate", layout["gap_numeric_match_rows"][0]["constraint_type"])
            self.assertEqual("target>expression", layout["gap_numeric_match_rows"][0]["between_fields"])
            self.assertIn(
                layout["gap_numeric_match_rows"][0]["value_confidence"],
                {
                    "exact_u32_numeric_value_match_layout_unproven",
                    "exact_float32_numeric_value_match_layout_unproven",
                    "approx_float32_numeric_value_match_layout_unproven",
                },
            )
            self.assertIn("candidate_relative_match_signature", layout["gap_numeric_match_rows"][0])
            self.assertGreaterEqual(
                layout["layout_status_counts"]["nearby_string_span_only_value_layout_unproven"],
                2,
            )
            first_candidate = summary["constraint_record_candidate_rows"][0]
            self.assertGreater(first_candidate["record_span_size"], 0)
            self.assertGreaterEqual(first_candidate["record_span_field_count"], 2)
            self.assertEqual(
                "nearby_string_span_only_value_layout_unproven",
                first_candidate["record_layout_status"],
            )
            self.assertEqual(("parent", "helper", "target", "expression"), first_candidate["record_field_sequence"])
            self.assertEqual("proven_decoded_string_offset_order", first_candidate["record_field_sequence_confidence"])
            self.assertEqual("linear_channel_transform_candidate", first_candidate["expression_shape"])
            self.assertIn("shape=linear_channel_transform_candidate", first_candidate["expression_syntax_signature"])
            self.assertEqual("inferred_readable_expression_syntax", first_candidate["expression_shape_confidence"])
            self.assertEqual("solver_semantics_unknown", first_candidate["expression_shape_status"])
            self.assertEqual(("channel_coefficient", "additive_offset"), first_candidate["expression_numeric_roles"])
            self.assertEqual("inferred_readable_expression_syntax", first_candidate["expression_numeric_role_confidence"])
            self.assertEqual("binary_like_interfield_gap_bytes_unbound", first_candidate["record_gap_status"])
            self.assertGreaterEqual(sum(first_candidate["record_gap_class_counts"].values()), 1)
            self.assertGreater(first_candidate["record_gap_max_size"], 0)
            self.assertEqual("unbound_interfield_scalar_candidates", first_candidate["record_gap_scalar_status"])
            self.assertGreaterEqual(first_candidate["record_gap_scalar_kind_counts"]["f32_unit_candidate"], 1)
            self.assertGreaterEqual(first_candidate["record_gap_scalar_candidate_count"], 1)
            self.assertEqual("unbound_scalar_numeric_constant_matches", first_candidate["record_gap_numeric_match_status"])
            self.assertGreaterEqual(first_candidate["record_gap_numeric_match_role_counts"]["channel_coefficient"], 1)
            self.assertGreaterEqual(first_candidate["record_gap_numeric_match_role_counts"]["additive_offset"], 1)
            self.assertGreaterEqual(first_candidate["record_gap_numeric_match_pair_counts"]["target>expression"], 1)
            self.assertGreaterEqual(
                first_candidate["record_gap_numeric_match_value_confidence_counts"][
                    "exact_float32_numeric_value_match_layout_unproven"
                ],
                1,
            )
            self.assertGreaterEqual(sum(first_candidate["record_gap_numeric_match_signature_counts"].values()), 1)
            self.assertGreaterEqual(
                sum(first_candidate["record_gap_numeric_match_candidate_relative_signature_counts"].values()),
                1,
            )
            self.assertGreaterEqual(sum(first_candidate["record_gap_numeric_match_previous_delta_counts"].values()), 1)
            self.assertGreaterEqual(sum(first_candidate["record_gap_numeric_match_next_delta_counts"].values()), 1)
            self.assertGreaterEqual(
                sum(first_candidate["record_gap_numeric_match_candidate_relative_offset_counts"].values()),
                1,
            )
            self.assertGreaterEqual(first_candidate["record_gap_numeric_match_count"], 1)
            self.assertEqual("blocked_record_layout_unproven", summary["constraint_record_candidate_rows"][0]["solver_status"])
            self.assertFalse(summary["constraint_solving_supported"])

    def test_papr_read_status_aggregates_expression_and_offset_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            entry = ArchiveEntry(
                path="character/model/body.papr",
                pamt_path=root / "0009" / "0.pamt",
                paz_file=root / "0009" / "0.paz",
                offset=0,
                comp_size=0,
                orig_size=0,
                flags=0,
                paz_index=0,
            )
            gap = struct.pack("<I", 0) + struct.pack("<f", 0.5) + struct.pack("<I", 24) + struct.pack("<I", 1)
            data = (
                b"PAR "
                + b"Bip01 Head\x00" + gap + b"P_Bip01 Head\x00" + gap + b"Bip01 Head_Dummy\x00"
            )
            data += (b"\x00" * (((len(data) + 3) & ~3) - len(data))) + struct.pack("<f", 3.0) + struct.pack("<f", 30.5) + gap
            data += b"Local_Euler_Z*3+30.5\x00" + gap + b"amin(Local_Euler_Z*5+9.8) -1\x00"

            with patch("tools.mesh_editor_dev_harness.read_archive_entry_data", return_value=(data, False, "plain")):
                status = _real_archive_papr_read_status((entry,))

            self.assertEqual(1, status["entry_count"])
            self.assertEqual(1, status["read_ok_count"])
            self.assertGreaterEqual(status["constraint_expression_shape_totals"]["linear_channel_transform_candidate"], 1)
            self.assertGreaterEqual(status["constraint_expression_shape_totals"]["limit_linear_channel_transform_candidate"], 1)
            self.assertGreaterEqual(sum(status["constraint_expression_syntax_signature_totals"].values()), 1)
            self.assertTrue(
                any(
                    "shape=linear_channel_transform_candidate" in signature
                    for signature in status["constraint_expression_syntax_signature_totals"]
                )
            )
            self.assertGreaterEqual(status["constraint_expression_numeric_role_totals"]["channel_coefficient"], 2)
            self.assertGreaterEqual(status["constraint_expression_numeric_role_totals"]["additive_offset"], 2)
            self.assertGreaterEqual(status["constraint_expression_numeric_role_totals"]["limit_argument"], 1)
            self.assertGreaterEqual(status["constraint_expression_channel_totals"]["Local_Euler_Z"], 2)
            self.assertGreaterEqual(status["constraint_limit_operator_totals"]["amin"], 1)
            self.assertGreaterEqual(status["constraint_metadata_totals"]["constraint_expression_numeric_values"], 1)
            self.assertGreaterEqual(status["constraint_offset_field_totals"]["target"], 1)
            self.assertGreaterEqual(status["constraint_candidate_family_totals"]["driver_expression_candidate"], 1)
            self.assertGreaterEqual(status["constraint_candidate_family_totals"]["local_transform_limit_candidate"], 1)
            self.assertGreaterEqual(status["constraint_candidate_solver_status_totals"]["blocked_record_layout_unproven"], 2)
            self.assertGreaterEqual(status["constraint_candidate_family_field_totals"]["driver_expression_candidate"]["target"], 1)
            self.assertGreaterEqual(status["constraint_candidate_family_field_totals"]["local_transform_limit_candidate"]["expression"], 1)
            self.assertGreaterEqual(
                status["constraint_candidate_family_channel_totals"]["driver_expression_candidate"]["Local_Euler_Z"],
                1,
            )
            self.assertGreaterEqual(
                status["constraint_candidate_family_channel_totals"]["local_transform_limit_candidate"]["Local_Euler_Z"],
                1,
            )
            self.assertGreaterEqual(status["constraint_candidate_family_limit_totals"]["local_transform_limit_candidate"]["amin"], 1)
            self.assertGreaterEqual(
                status["constraint_record_layout_status_totals"]["nearby_string_span_only_value_layout_unproven"],
                2,
            )
            self.assertGreaterEqual(status["constraint_record_field_sequence_totals"]["parent>helper>target>expression"], 2)
            self.assertGreater(status["constraint_record_layout_max_span_size"], 0)
            self.assertGreaterEqual(status["constraint_record_gap_status_totals"]["binary_like_interfield_gap_bytes_unbound"], 1)
            self.assertGreaterEqual(sum(status["constraint_record_gap_class_totals"].values()), 1)
            self.assertGreaterEqual(status["constraint_record_gap_pair_total"], 1)
            self.assertGreater(status["constraint_record_gap_max_size"], 0)
            self.assertGreaterEqual(status["constraint_record_gap_scalar_status_totals"]["unbound_interfield_scalar_candidates"], 1)
            self.assertGreaterEqual(status["constraint_record_gap_scalar_kind_totals"]["f32_unit_candidate"], 1)
            self.assertGreaterEqual(status["constraint_record_gap_aligned_word_total"], 1)
            self.assertGreaterEqual(status["constraint_record_gap_scalar_candidate_total"], 1)
            self.assertGreaterEqual(status["constraint_record_gap_numeric_match_status_totals"]["unbound_scalar_numeric_constant_matches"], 1)
            self.assertGreaterEqual(status["constraint_record_gap_numeric_match_role_totals"]["channel_coefficient"], 1)
            self.assertGreaterEqual(status["constraint_record_gap_numeric_match_role_totals"]["additive_offset"], 1)
            self.assertGreaterEqual(status["constraint_record_gap_numeric_match_pair_totals"]["target>expression"], 1)
            self.assertGreaterEqual(
                sum(status["constraint_record_gap_numeric_match_value_confidence_totals"].values()),
                1,
            )
            self.assertGreaterEqual(
                status["constraint_record_gap_numeric_match_value_confidence_totals"][
                    "exact_float32_numeric_value_match_layout_unproven"
                ],
                1,
            )
            self.assertGreaterEqual(status["constraint_record_gap_numeric_match_family_totals"]["driver_expression_candidate"], 1)
            self.assertGreaterEqual(status["constraint_record_gap_numeric_match_family_row_totals"]["driver_expression_candidate"], 1)
            self.assertGreaterEqual(
                status["constraint_record_gap_numeric_match_family_role_totals"][
                    "driver_expression_candidate"
                ]["channel_coefficient"],
                1,
            )
            self.assertGreaterEqual(
                status["constraint_record_gap_numeric_match_family_pair_totals"][
                    "driver_expression_candidate"
                ]["target>expression"],
                1,
            )
            self.assertGreaterEqual(
                status["constraint_record_gap_numeric_match_family_value_confidence_totals"][
                    "driver_expression_candidate"
                ]["exact_float32_numeric_value_match_layout_unproven"],
                1,
            )
            self.assertGreaterEqual(
                sum(status["constraint_record_gap_numeric_match_signature_totals"].values()),
                1,
            )
            self.assertGreaterEqual(
                sum(status["constraint_record_gap_numeric_match_candidate_relative_signature_totals"].values()),
                1,
            )
            self.assertTrue(
                any(
                    "family=driver_expression_candidate" in signature
                    and "role=channel_coefficient" in signature
                    for signature in status["constraint_record_gap_numeric_match_signature_totals"]
                )
            )
            self.assertTrue(
                any(
                    "family=driver_expression_candidate" in signature
                    and "rel=" in signature
                    for signature in status["constraint_record_gap_numeric_match_candidate_relative_signature_totals"]
                )
            )
            self.assertGreaterEqual(sum(status["constraint_record_gap_numeric_match_previous_delta_totals"].values()), 1)
            self.assertGreaterEqual(sum(status["constraint_record_gap_numeric_match_next_delta_totals"].values()), 1)
            self.assertGreaterEqual(
                sum(status["constraint_record_gap_numeric_match_candidate_relative_offset_totals"].values()),
                1,
            )
            self.assertEqual(
                "observed_relative_to_decoded_string_gap_boundaries_value_layout_unproven",
                status["constraint_record_gap_numeric_match_offset_confidence"],
            )
            self.assertEqual(
                "observed_relative_to_inferred_candidate_offset_value_layout_unproven",
                status["constraint_record_gap_numeric_match_candidate_relative_offset_confidence"],
            )
            self.assertGreaterEqual(status["constraint_record_gap_numeric_match_total"], 1)
            self.assertGreaterEqual(len(status["constraint_record_gap_numeric_match_rows"]), 1)
            self.assertEqual("character/model/body.papr", status["constraint_record_gap_numeric_match_rows"][0]["path"])
            self.assertEqual("driver_expression_candidate", status["constraint_record_gap_numeric_match_rows"][0]["constraint_type"])
            self.assertEqual("target>expression", status["constraint_record_gap_numeric_match_rows"][0]["between_fields"])
            self.assertFalse(status["constraint_solving_supported"])

    def test_asset_authoring_mesh_health_scenario_writes_json_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            result = run_scenario("asset-authoring-mesh-health", output_dir)
            report = json.loads(Path(result["asset_authoring"]["report_path"]).read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertEqual(ASSET_AUTHORING_MESH_HEALTH_SCHEMA, report["schema"])
        self.assertTrue(report["topology"]["topology_changed"])
        self.assertGreaterEqual(report["totals"]["duplicate_vertices"], 1)
        self.assertGreaterEqual(report["totals"]["degenerate_faces"], 1)
        self.assertGreaterEqual(report["totals"]["invalid_indices"], 1)

    def test_asset_authoring_uv_report_scenario_writes_json_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            result = run_scenario("asset-authoring-uv-report", output_dir)
            report = json.loads(Path(result["asset_authoring"]["report_path"]).read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertEqual(ASSET_AUTHORING_UV_REPORT_SCHEMA, report["schema"])
        self.assertGreaterEqual(report["island_count"], 1)
        self.assertTrue(report["uv_bounds"]["available"])

    def test_asset_authoring_tangent_report_scenario_writes_json_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            result = run_scenario("asset-authoring-tangent-report", output_dir)
            report = json.loads(Path(result["asset_authoring"]["report_path"]).read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertEqual(ASSET_AUTHORING_TANGENT_REPORT_SCHEMA, report["schema"])
        self.assertEqual("generate_tangents", report["operation"])
        self.assertGreaterEqual(report["before"]["totals"]["missing_tangent_parts"], 1)
        self.assertGreaterEqual(report["totals"]["complete_tangent_parts"], 1)
        self.assertEqual("ok", report["command"]["status"])

    def test_asset_authoring_openimageio_report_scenario_writes_json_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            result = run_scenario("asset-authoring-openimageio-report", output_dir)
            report = json.loads(Path(result["asset_authoring"]["report_path"]).read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertEqual(ASSET_AUTHORING_SOURCE_IMAGE_SCHEMA, report["schema"])
        self.assertEqual("helper_unavailable", report["status"])
        self.assertTrue(report["openimageio_source_candidate"])
        self.assertFalse(report["can_convert"])
        self.assertEqual("helper_unavailable", report["metadata_command"]["status"])
        self.assertEqual("helper_unavailable", report["convert_command"]["status"])

    def test_service_smoke_writes_result_json_without_starting_app(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            result = run_scenario("service-smoke", output_dir)

            self.assertTrue(result["ok"])
            self.assertTrue((output_dir / "result.json").is_file())
            evidence_report = json.loads((output_dir / "evidence_report.json").read_text(encoding="utf-8"))
            self.assertEqual("cdmw_mesh_editor_evidence_report_v1", evidence_report["schema"])
            self.assertEqual("service-smoke", evidence_report["scenario"])
            self.assertIn("preview-only", evidence_report["state_labels"])
            self.assertIn(".paseqc", evidence_report["corpus_manifest"]["formats"])
            self.assertTrue(any(row["feature"] == "Direct archive mutation" and row["state"] == "blocked" for row in evidence_report["feature_status_rows"]))
            self.assertEqual("service-smoke", result["scenario"])
            self.assertGreater(result["service"]["session"]["face_count"], 2)
            selection_operations = result["service"]["selection_operations"]
            self.assertTrue(selection_operations["ok"])
            self.assertEqual({"0": [0, 3]}, selection_operations["added"]["vertices_by_submesh"])
            self.assertEqual({"0": [[1, 2]]}, selection_operations["subtracted"]["edges_by_submesh"])
            self.assertEqual({"0": [2]}, selection_operations["toggled"]["vertices_by_submesh"])
            self.assertEqual({}, selection_operations["toggled"]["faces_by_submesh"])
            selection_pruning = result["service"]["selection_pruning"]
            self.assertTrue(selection_pruning["ok"])
            self.assertEqual({"0": [[0, 1]]}, selection_pruning["malformed"]["edges_by_submesh"])
            self.assertEqual({}, selection_pruning["malformed"]["faces_by_submesh"])
            self.assertEqual({"0": [[0, 3]]}, selection_pruning["loose_edge"]["edges_by_submesh"])
            history_selection = result["service"]["history_selection"]
            self.assertTrue(history_selection["ok"])
            self.assertEqual([1], history_selection["before_undo"]["source_indices"])
            self.assertEqual({}, history_selection["after_undo"]["faces_by_submesh"])
            self.assertEqual([], history_selection["after_undo"]["source_indices"])
            self.assertEqual(1, history_selection["submesh_count_after_undo"])
            history_context = result["service"]["history_context"]
            self.assertTrue(history_context["ok"])
            self.assertEqual({"0": [0]}, history_context["after_undo"]["faces_by_submesh"])
            self.assertEqual({"1": [0]}, history_context["after_redo"]["faces_by_submesh"])
            self.assertEqual([1], history_context["after_redo"]["source_indices"])
            self.assertEqual("object", history_context["mode_restore"]["after_undo"])
            self.assertEqual("edit", history_context["mode_restore"]["after_redo"])
            uv_operations = result["service"]["uv_operations"]
            self.assertTrue(uv_operations["ok"])
            self.assertEqual({"0": [1, 2]}, uv_operations["pivot_flip"]["changed_vertices"])
            self.assertEqual([-0.5, -0.5], uv_operations["pivot_flip"]["uvs"][1])
            self.assertEqual([0.5, 0.5], uv_operations["pivot_flip"]["uvs"][2])
            transform_targets = result["service"]["transform_targets"]
            self.assertTrue(transform_targets["ok"])
            self.assertEqual([], transform_targets["empty"]["command"]["affected_submesh_indices"])
            self.assertEqual([-0.75, -0.75, 0.0], transform_targets["empty"]["vertices"][0])
            self.assertEqual([], transform_targets["stale_edge"]["command"]["affected_submesh_indices"])
            self.assertEqual([-0.75, -0.75, 0.0], transform_targets["stale_edge"]["vertices"][0])
            self.assertEqual([], transform_targets["non_edge"]["command"]["affected_submesh_indices"])

            self.assertEqual([-0.75, -0.75, 0.0], transform_targets["non_edge"]["vertices"][0])
            self.assertEqual([0.75, 0.75, 0.0], transform_targets["non_edge"]["vertices"][3])
            self.assertEqual([-0.75, -0.75, 0.5], transform_targets["source"]["vertices"][0])
            topology_targets = result["service"]["topology_targets"]
            self.assertTrue(topology_targets["ok"])
            self.assertEqual([], topology_targets["duplicate_empty"]["command"]["affected_submesh_indices"])
            self.assertEqual(1, topology_targets["duplicate_empty"]["submesh_count"])
            self.assertEqual([], topology_targets["duplicate_invalid_face"]["command"]["affected_submesh_indices"])
            self.assertEqual(1, topology_targets["duplicate_invalid_face"]["submesh_count"])
            self.assertEqual([], topology_targets["duplicate_malformed_face"]["command"]["affected_submesh_indices"])
            self.assertEqual(1, topology_targets["duplicate_malformed_face"]["submesh_count"])
            self.assertEqual([], topology_targets["mirror_empty"]["command"]["affected_submesh_indices"])
            self.assertEqual(1, topology_targets["mirror_empty"]["submesh_count"])
            self.assertEqual([], topology_targets["mirror_invalid_face"]["command"]["affected_submesh_indices"])
            self.assertEqual(1, topology_targets["mirror_invalid_face"]["submesh_count"])
            self.assertEqual([1], topology_targets["duplicate_source"]["command"]["affected_submesh_indices"])
            self.assertEqual([1], topology_targets["mirror_source"]["command"]["affected_submesh_indices"])
            material_operations = result["service"]["material_operations"]
            self.assertTrue(material_operations["ok"])
            self.assertTrue(material_operations["face_assign"]["command"]["topology_changed"])
            self.assertEqual(["harness_material", "face_material"], [submesh["material"] for submesh in material_operations["face_assign"]["submeshes"]])
            self.assertEqual({"roughness": 0.4}, material_operations["face_assign"]["submeshes"][1]["overrides"])
            self.assertTrue(material_operations["face_copy"]["command"]["topology_changed"])
            self.assertEqual(["harness_material", "harness_material_b", "harness_material"], [submesh["material"] for submesh in material_operations["face_copy"]["submeshes"]])
            self.assertEqual({"roughness": 0.2, "metalness": 0.6}, material_operations["face_copy"]["submeshes"][2]["overrides"])
            plain_reset = material_operations["plain_assign_reset"]
            self.assertEqual("plain_material", plain_reset["material"])
            self.assertFalse(plain_reset["has_route_metadata"])
            self.assertEqual({}, plain_reset["overrides"])
            edge_face_topology = result["service"]["edge_face_topology"]
            self.assertTrue(edge_face_topology["ok"])
            self.assertEqual(3, edge_face_topology["copied_vertex_count"])
            self.assertEqual(1, edge_face_topology["copied_face_count"])
            self.assertEqual([[0, 1, 2]], edge_face_topology["copied_faces"])
            self.assertEqual(2, edge_face_topology["mirror"]["submesh_count"])
            self.assertEqual(3, edge_face_topology["mirror"]["vertex_count"])
            self.assertEqual(1, edge_face_topology["mirror"]["face_count"])
            self.assertEqual([[0, 2, 1]], edge_face_topology["mirror"]["faces"])
            self.assertEqual([[0.75, -0.75, 0.0], [-0.75, -0.75, 0.0], [0.75, 0.75, 0.0]], edge_face_topology["mirror"]["vertices"])
            self.assertEqual(3, edge_face_topology["delete"]["vertex_count"])
            self.assertEqual(1, edge_face_topology["delete"]["face_count"])
            self.assertEqual([[0, 2, 1]], edge_face_topology["delete"]["faces"])
            self.assertEqual(4, edge_face_topology["dissolve"]["vertex_count"])
            self.assertEqual(1, edge_face_topology["dissolve"]["face_count"])
            self.assertEqual([[1, 3, 2]], edge_face_topology["dissolve"]["faces"])
            self.assertEqual(4, edge_face_topology["internal_dissolve"]["vertex_count"])
            self.assertEqual(2, edge_face_topology["internal_dissolve"]["face_count"])
            self.assertEqual([[0, 1, 3], [0, 3, 2]], edge_face_topology["internal_dissolve"]["faces"])
            self.assertEqual(7, edge_face_topology["subdivide"]["vertex_count"])
            self.assertEqual(5, edge_face_topology["subdivide"]["face_count"])
            self.assertEqual([1, 3, 2], edge_face_topology["subdivide"]["faces"][-1])
            self.assertEqual(5, edge_face_topology["loop_cut_two_edges"]["vertex_count"])
            self.assertEqual(3, edge_face_topology["loop_cut_two_edges"]["face_count"])
            self.assertEqual([[3, 1, 4], [0, 3, 4], [0, 4, 2]], edge_face_topology["loop_cut_two_edges"]["faces"])
            self.assertEqual({"0": [3, 4]}, edge_face_topology["loop_cut_two_edges"]["changed_vertices"])
            self.assertEqual(5, edge_face_topology["loop_cut_multi"]["vertex_count"])
            self.assertEqual(3, edge_face_topology["loop_cut_multi"]["face_count"])
            self.assertEqual([[0, 3, 2], [3, 4, 2], [4, 1, 2]], edge_face_topology["loop_cut_multi"]["faces"])
            self.assertEqual({"0": [3, 4]}, edge_face_topology["loop_cut_multi"]["changed_vertices"])
            self.assertAlmostEqual(-0.25, edge_face_topology["loop_cut_multi"]["vertices"][3][0], places=6)
            self.assertAlmostEqual(0.25, edge_face_topology["loop_cut_multi"]["vertices"][4][0], places=6)
            self.assertAlmostEqual(1.0, edge_face_topology["loop_cut_multi"]["uvs"][3][1], places=6)
            self.assertAlmostEqual(1.0, edge_face_topology["loop_cut_multi"]["uvs"][4][1], places=6)
            self.assertEqual(4, edge_face_topology["loop_cut_factor"]["vertex_count"])
            self.assertEqual(2, edge_face_topology["loop_cut_factor"]["face_count"])
            self.assertEqual({"0": [3]}, edge_face_topology["loop_cut_factor"]["changed_vertices"])
            self.assertAlmostEqual(-0.375, edge_face_topology["loop_cut_factor"]["vertices"][3][0], places=6)
            self.assertAlmostEqual(0.25, edge_face_topology["loop_cut_factor"]["uvs"][3][0], places=6)
            self.assertEqual([[0, 3, 2], [3, 1, 2]], edge_face_topology["loop_cut_factor"]["faces"])
            self.assertEqual(1, edge_face_topology["split"]["submesh_count"])
            self.assertEqual(6, edge_face_topology["split"]["vertex_count"])
            self.assertEqual(2, edge_face_topology["split"]["face_count"])
            self.assertEqual([[0, 4, 5], [1, 3, 2]], edge_face_topology["split"]["faces"])
            self.assertEqual({"0": [4, 5]}, edge_face_topology["split"]["changed_vertices"])
            self.assertEqual(2, edge_face_topology["separate"]["submesh_count"])
            self.assertEqual(1, edge_face_topology["separate"]["source_face_count"])
            self.assertEqual(1, edge_face_topology["separate"]["moved_face_count"])
            self.assertEqual(3, edge_face_topology["fill"]["face_count"])
            self.assertEqual([0, 1, 3], edge_face_topology["fill"]["faces"][-1])
            self.assertEqual(2, edge_face_topology["quad_fill"]["face_count"])
            self.assertEqual([[0, 1, 3], [0, 3, 2]], edge_face_topology["quad_fill"]["faces"])
            self.assertEqual(2, edge_face_topology["face_fill"]["face_count"])
            self.assertEqual(2, edge_face_topology["existing_fill"]["face_count"])
            self.assertEqual(8, edge_face_topology["extrude"]["vertex_count"])
            self.assertEqual(12, edge_face_topology["extrude"]["face_count"])
            self.assertEqual({"0": [4, 5, 6, 7]}, edge_face_topology["extrude"]["changed_vertices"])
            self.assertEqual(6, edge_face_topology["edge_extrude"]["vertex_count"])
            self.assertEqual(2, edge_face_topology["edge_extrude"]["face_count"])
            self.assertEqual([[0, 1, 5], [0, 5, 4]], edge_face_topology["edge_extrude"]["faces"])
            self.assertEqual({"0": [4, 5]}, edge_face_topology["edge_extrude"]["changed_vertices"])
            self.assertAlmostEqual(0.2, edge_face_topology["edge_extrude"]["vertices"][4][2], places=6)
            self.assertAlmostEqual(0.2, edge_face_topology["edge_extrude"]["vertices"][5][2], places=6)
            self.assertEqual(edge_face_topology["edge_extrude"]["uvs"][0], edge_face_topology["edge_extrude"]["uvs"][4])
            self.assertEqual(edge_face_topology["edge_extrude"]["uvs"][1], edge_face_topology["edge_extrude"]["uvs"][5])
            self.assertFalse(edge_face_topology["non_edge_extrude"]["command"]["topology_changed"])
            self.assertEqual([], edge_face_topology["non_edge_extrude"]["command"]["affected_submesh_indices"])
            self.assertEqual(4, edge_face_topology["non_edge_extrude"]["vertex_count"])
            self.assertEqual(2, edge_face_topology["non_edge_extrude"]["face_count"])
            self.assertEqual(8, edge_face_topology["inset"]["vertex_count"])
            self.assertEqual(10, edge_face_topology["inset"]["face_count"])
            self.assertEqual({"0": [4, 5, 6, 7]}, edge_face_topology["inset"]["changed_vertices"])
            self.assertEqual(4, edge_face_topology["inset_zero"]["vertex_count"])
            self.assertEqual(2, edge_face_topology["inset_zero"]["face_count"])
            self.assertEqual([[0, 1, 2], [1, 3, 2]], edge_face_topology["inset_zero"]["faces"])
            self.assertFalse(edge_face_topology["inset_zero"]["command"]["topology_changed"])
            self.assertEqual(4, edge_face_topology["merge"]["vertex_count"])
            self.assertEqual(2, edge_face_topology["merge"]["face_count"])
            self.assertEqual([[0, 1, 2], [1, 3, 2]], edge_face_topology["merge"]["faces"])
            self.assertEqual(4, edge_face_topology["weld"]["vertex_count"])
            self.assertEqual(2, edge_face_topology["weld"]["face_count"])
            self.assertEqual([[0, 1, 2], [1, 3, 2]], edge_face_topology["weld"]["faces"])
            self.assertEqual(2, edge_face_topology["bridge"]["face_count"])
            self.assertEqual([[0, 1, 3], [0, 3, 2]], edge_face_topology["bridge"]["faces"])
            self.assertEqual(2, edge_face_topology["filled_bridge"]["face_count"])
            self.assertEqual(2, edge_face_topology["face_flip_normals"]["face_count"])
            self.assertEqual([], edge_face_topology["empty_recalculate_normals"]["command"]["affected_submesh_indices"])
            self.assertEqual([[0.0, 0.0, -1.0]] * 4, edge_face_topology["empty_recalculate_normals"]["normals"])
            self.assertEqual([0], edge_face_topology["source_recalculate_normals"]["command"]["affected_submesh_indices"])
            self.assertEqual([[0.0, 0.0, 1.0]] * 4, edge_face_topology["source_recalculate_normals"]["normals"])
            self.assertEqual([[0, 2, 1], [1, 3, 2]], edge_face_topology["face_flip_normals"]["faces"])
            self.assertFalse(edge_face_topology["face_flip_normals"]["command"]["topology_changed"])
            self.assertEqual(2, edge_face_topology["empty_flip_normals"]["face_count"])
            self.assertEqual([[0, 1, 2], [1, 3, 2]], edge_face_topology["empty_flip_normals"]["faces"])
            self.assertFalse(edge_face_topology["empty_flip_normals"]["command"]["topology_changed"])
            self.assertEqual([], edge_face_topology["empty_flip_normals"]["command"]["affected_submesh_indices"])
            self.assertEqual(2, edge_face_topology["source_flip_normals"]["face_count"])
            self.assertEqual([[0, 2, 1], [1, 2, 3]], edge_face_topology["source_flip_normals"]["faces"])
            self.assertFalse(edge_face_topology["source_flip_normals"]["command"]["topology_changed"])
            self.assertEqual([0], edge_face_topology["source_flip_normals"]["command"]["affected_submesh_indices"])
            coverage = result["service"]["coverage"]
            self.assertTrue(coverage["ok"])
            self.assertEqual([], coverage["missing_actions"])
            self.assertEqual(set(MESH_EDIT_ACTIONS) | {"undo", "redo"}, set(coverage["covered_actions"]))
            self.assertEqual(["pac", "pam", "pamlod"], coverage["covered_formats"])
            palette = result["service"]["palette"]
            self.assertTrue(palette["ok"])
            self.assertEqual([], palette["missing_actions"])
            self.assertEqual({action.key for action in MESH_EDITOR_ACTIONS}, set(palette["covered_actions"]))
            commands = {command["key"]: command for command in palette["commands"]}
            self.assertGreater(commands["select_face"]["selection_group_count"], 0)
            self.assertTrue(commands["select_face"]["selection_refresh"])
            self.assertTrue(commands["duplicate"]["selection_refresh"])
            self.assertTrue(commands["undo"]["selection_refresh"])
            self.assertGreater(commands["uv_flip_u"]["vertex_update_group_count"], 0)
            self.assertGreater(commands["uv_normalize"]["vertex_update_group_count"], 0)
            self.assertGreater(commands["uv_align_u"]["vertex_update_group_count"], 0)
            self.assertGreater(commands["uv_align_v"]["vertex_update_group_count"], 0)
            self.assertGreater(commands["uv_planar_project"]["vertex_update_group_count"], 0)
            self.assertGreater(commands["uv_box_project"]["vertex_update_group_count"], 0)
            self.assertGreater(commands["uv_cylindrical_project"]["vertex_update_group_count"], 0)
            self.assertGreater(commands["uv_pack"]["vertex_update_group_count"], 0)
            self.assertGreater(commands["uv_snap_grid"]["vertex_update_group_count"], 0)
            self.assertGreater(commands["uv_snap_pixels"]["vertex_update_group_count"], 0)
            self.assertGreater(commands["material_assign"]["material_override_group_count"], 0)
            self.assertGreater(commands["material_copy"]["material_override_group_count"], 0)

    def test_real_archive_rigging_smoke_reports_missing_game_root_without_archive_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            output_dir = temp_root / "out"

            result = run_scenario("real-archive-rigging-smoke", output_dir, game_root=temp_root / "missing")

            self.assertFalse(result["ok"])
            self.assertTrue((output_dir / "result.json").is_file())
            real_archive = result["real_archive"]
            self.assertTrue(real_archive["read_only"])
            self.assertIn("missing PAMT", real_archive["skipped"])

    def test_real_archive_animation_binding_smoke_reports_missing_game_root_without_archive_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            output_dir = temp_root / "out"

            result = run_scenario("real-archive-animation-binding-smoke", output_dir, game_root=temp_root / "missing")

            self.assertFalse(result["ok"])
            self.assertTrue((output_dir / "result.json").is_file())
            real_archive = result["real_archive_animation"]
            self.assertTrue(real_archive["read_only"])
            self.assertIn("missing PAMT", real_archive["skipped"])

    def test_real_archive_sequence_binding_smoke_reports_missing_game_root_without_archive_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            output_dir = temp_root / "out"

            result = run_scenario("real-archive-sequence-binding-smoke", output_dir, game_root=temp_root / "missing")

            self.assertFalse(result["ok"])
            self.assertTrue((output_dir / "result.json").is_file())
            real_archive = result["real_archive_sequence"]
            self.assertTrue(real_archive["read_only"])
            self.assertIn("missing PAMT", real_archive["skipped"])

    def test_real_archive_app_workflow_smoke_reports_missing_game_root_without_archive_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            output_dir = temp_root / "out"

            result = run_scenario("real-archive-app-workflow-smoke", output_dir, game_root=temp_root / "missing")

            self.assertFalse(result["ok"])
            self.assertTrue((output_dir / "result.json").is_file())
            real_archive = result["real_archive_app"]
            self.assertTrue(real_archive["read_only"])
            self.assertIn("missing PAMT", real_archive["skipped"])

    def test_real_archive_mesh_editor_d3d11_edit_smoke_reports_missing_game_root_without_archive_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            output_dir = temp_root / "out"

            result = run_scenario("real-archive-mesh-editor-d3d11-edit-smoke", output_dir, game_root=temp_root / "missing")

            self.assertFalse(result["ok"])
            self.assertTrue((output_dir / "result.json").is_file())
            real_archive = result["real_archive_mesh_editor_d3d11_edit"]
            self.assertTrue(real_archive["read_only"])
            self.assertIn("missing PAMT", real_archive["skipped"])

    def test_real_archive_mesh_editor_drag_smoke_uses_multistep_mouse_moves(self) -> None:
        source = Path("tools/mesh_editor_dev_harness.py").read_text(encoding="utf-8")
        self.assertIn("mouse_drag_mid = (mouse_drag_start[0] + 16, mouse_drag_start[1])", source)
        self.assertIn("mouse_drag_points = (mouse_drag_mid, mouse_drag_end)", source)
        self.assertIn("for move_index, (move_x, move_y) in enumerate(mouse_drag_points):", source)
        self.assertIn('all(event.get("event") == "mesh_edit_vertices_updated" for event in edit_update_events)', source)
        self.assertIn('"mouse_drag_points": [list(point) for point in mouse_drag_points]', source)
        self.assertIn("selected_before_capture_path = output_dir / \"real_archive_selected_before_drag.png\"", source)
        self.assertIn("visual_proof_path = output_dir / \"real_archive_visual_edit_proof.png\"", source)
        self.assertIn("_write_real_archive_visual_edit_proof(", source)
        self.assertIn('"visual_edit_proof_png": str(visual_proof_path)', source)
        self.assertIn('"visual_edit_proof_summary": visual_proof_summary', source)
        self.assertIn('"live_stroke_timings": live_stroke_timings', source)
        self.assertIn('"live_stroke_timing_summary": live_stroke_timing_summary', source)
        self.assertIn('"live_stroke_frame_budget_ok": live_stroke_frame_budget_ok', source)
        self.assertIn('"handler_ms": handler_ms', source)
        self.assertIn('"d3d11_send_ms": sum(_finite_float(item.get("send_ms")) for item in update_send_metrics)', source)

    def test_real_archive_mesh_editor_side_by_side_drag_smoke_uses_replacement_viewport(self) -> None:
        source = Path("tools/mesh_editor_dev_harness.py").read_text(encoding="utf-8")
        self.assertIn('"real-archive-mesh-editor-d3d11-side-by-side-edit-smoke"', source)
        self.assertIn("reference_mesh=mesh if side_by_side else None", source)
        self.assertIn('display_mode="side_by_side" if side_by_side else "replacement_only"', source)
        self.assertIn("projection_probe_start = (700, 360) if side_by_side else (440, 360)", source)
        self.assertIn("replacement_viewport_offset_ok = (not side_by_side) or viewport_x > 1.0", source)
        self.assertIn('"drag_points_in_replacement_viewport": drag_points_in_replacement_viewport', source)

    def test_png_capture_summary_rejects_blank_capture(self) -> None:
        width = 64
        height = 64
        blank_row = bytes((0, 0, 0)) * width
        visible_rows: list[bytes] = []
        for y in range(height):
            row = bytearray()
            for x in range(width):
                row.extend((220, 220, 220) if x == y or x == width - y - 1 else (18, 24, 30))
            visible_rows.append(bytes(row))

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            blank_path = output_dir / "blank.png"
            visible_path = output_dir / "visible.png"
            _write_rgb_png(blank_path, width, height, [blank_row] * height)
            _write_rgb_png(visible_path, width, height, visible_rows)

            blank_summary = _png_capture_summary(blank_path)
            visible_summary = _png_capture_summary(visible_path)

            self.assertFalse(blank_summary["ok"])
            self.assertEqual(1, blank_summary["unique_rgb_count"])
            self.assertTrue(visible_summary["ok"])
            self.assertGreater(visible_summary["unique_rgb_count"], 1)
            self.assertGreater(visible_summary["bright_sample_count"], 0)

    def test_synthetic_mesh_builder_covers_target_formats(self) -> None:
        for mesh_format in ("pac", "pam", "pamlod"):
            with self.subTest(mesh_format=mesh_format):
                mesh = build_synthetic_mesh(mesh_format)

                self.assertEqual(mesh_format, mesh.format)
                self.assertTrue(str(mesh.path).endswith(f".{mesh_format}"))

        with self.assertRaisesRegex(ValueError, "Unsupported synthetic mesh format"):
            build_synthetic_mesh("fbx")

    def test_preview_and_live_edit_payloads_use_source_identity(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].preview_native_material_overrides = {"roughness": 0.4, "metalness": 0.2}
        prepared = mesh_to_native_preview(mesh)
        triangle_groups = mesh_edit_triangle_groups(mesh)
        material_groups = mesh_edit_material_override_groups(mesh, (0,))
        mesh_to_reset = build_synthetic_mesh()
        reset_material_groups = mesh_edit_material_override_groups(mesh_to_reset, (0,), include_defaults=True)
        vertex_groups = mesh_edit_vertex_update_groups(mesh, {0: (0, 2)})
        selection_groups = mesh_edit_selection_groups(mesh, MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}))

        self.assertEqual(1, len(prepared.batches))
        self.assertEqual({"roughness": 0.4, "metalness": 0.2}, prepared.batches[0].preview_native_material_overrides)
        self.assertEqual(6, prepared.batches[0].index_count)
        prepared_identity = {
            "source_vertex_indices": list(prepared.batches[0].source_vertex_indices),
            "source_vertex_indices_binary": prepared.batches[0].source_vertex_indices_binary,
            "source_vertex_start": prepared.batches[0].source_vertex_range_start,
            "source_vertex_count": prepared.batches[0].source_vertex_range_count,
            "source_face_indices": list(prepared.batches[0].source_face_indices),
            "source_face_indices_binary": prepared.batches[0].source_face_indices_binary,
            "source_face_start": prepared.batches[0].source_face_range_start,
            "source_face_count": prepared.batches[0].source_face_range_count,
        }
        self.assertEqual([0, 1, 2, 1, 3, 2], _i32_descriptor_values(prepared_identity, "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual([0, 1], _i32_descriptor_values(prepared_identity, "source_face_indices", "source_face_indices_binary"))
        self.assertEqual([0], [group["source_submesh_index"] for group in triangle_groups])
        self.assertEqual("harness_material", triangle_groups[0]["material_name"])
        self.assertEqual([0], material_groups[0]["source_submesh_indices"])
        self.assertEqual(0.4, material_groups[0]["roughness"])
        self.assertEqual(str(mesh_to_reset.submeshes[0].material), reset_material_groups[0]["material_name"])
        self.assertEqual(0.0, reset_material_groups[0]["roughness"])
        self.assertEqual(0.0, reset_material_groups[0]["metalness"])
        self.assertEqual(1.0, reset_material_groups[0]["texture_brightness"])
        self.assertEqual([0, 1, 2, 3], _i32_descriptor_values(triangle_groups[0], "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual(8, len(_f64_descriptor_values(triangle_groups[0], "uvs", "uvs_binary")))
        self.assertEqual([0, 2], _i32_descriptor_values(vertex_groups[0], "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual(6, len(_f64_descriptor_values(vertex_groups[0], "positions", "positions_binary")))
        self.assertEqual([0.0, 1.0, 0.0, 0.0], _f64_descriptor_values(vertex_groups[0], "uvs", "uvs_binary"))
        self.assertEqual([0, 1, 2], _i32_descriptor_values(selection_groups[0], "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual([0], _i32_descriptor_values(selection_groups[0], "source_face_indices", "source_face_indices_binary"))
        self.assertEqual(1, len(_i32_descriptor_values(selection_groups[0], "source_face_indices", "source_face_indices_binary")))
        edge_selection_groups = mesh_edit_selection_groups(mesh, MeshEditSelection.from_maps(edges_by_submesh={0: ((1, 2),)}))
        self.assertEqual([[1, 2]], _edge_descriptor_values(edge_selection_groups[0]))
        non_edge_selection_groups = mesh_edit_selection_groups(mesh, MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 3),)}))
        self.assertEqual([], non_edge_selection_groups)

        loose_edge_mesh = build_synthetic_mesh()
        loose_edge_mesh.submeshes[0].faces = []
        loose_edge_mesh.submeshes[0].face_count = 0
        loose_edge_mesh.total_faces = 0
        loose_edge_selection_groups = mesh_edit_selection_groups(
            loose_edge_mesh,
            MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 3),)}),
        )
        self.assertEqual([[0, 3]], _edge_descriptor_values(loose_edge_selection_groups[0]))
        self.assertEqual([0, 3], _i32_descriptor_values(loose_edge_selection_groups[0], "source_vertex_indices", "source_vertex_indices_binary"))

    def test_live_vertex_update_groups_forward_native_binary_descriptors(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].cdmw_native_preview_vertex_update_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices_binary": {"path": "ids.bin", "count": 2, "components": 1, "type": "i32", "delete_after": True},
            "positions_binary": {"path": "positions.bin", "count": 2, "components": 3, "type": "f64", "delete_after": True},
            "normals_binary": {"path": "normals.bin", "count": 2, "components": 3, "type": "f64", "delete_after": True},
            "uvs_binary": {"path": "uvs.bin", "count": 2, "components": 2, "type": "f64", "delete_after": True},
        }

        groups = mesh_edit_vertex_update_groups(mesh, {0: (0, 2)})

        self.assertEqual(
            [
                {
                    "preview_backend": "cdmw_mesh_core",
                    "source_submesh_index": 0,
                    "source_vertex_indices_binary": {"path": "ids.bin", "count": 2, "components": 1, "type": "i32", "delete_after": True},
                    "positions_binary": {"path": "positions.bin", "count": 2, "components": 3, "type": "f64", "delete_after": True},
                    "normals_binary": {"path": "normals.bin", "count": 2, "components": 3, "type": "f64", "delete_after": True},
                    "uvs_binary": {"path": "uvs.bin", "count": 2, "components": 2, "type": "f64", "delete_after": True},
                }
            ],
            groups,
        )
        self.assertFalse(hasattr(mesh.submeshes[0], "cdmw_native_preview_vertex_update_group"))

    def test_live_vertex_update_groups_forward_native_full_range(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].cdmw_native_preview_vertex_update_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_start": 0,
            "source_vertex_count": 4,
            "positions_binary": {"path": "positions.bin", "count": 4, "components": 3, "type": "f64", "delete_after": True},
            "normals_binary": {"path": "normals.bin", "count": 4, "components": 3, "type": "f64", "delete_after": True},
            "uvs_binary": {"path": "uvs.bin", "count": 4, "components": 2, "type": "f64", "delete_after": True},
        }

        groups = mesh_edit_vertex_update_groups(mesh, {0: range(0, 4)})

        self.assertEqual(
            [
                {
                    "preview_backend": "cdmw_mesh_core",
                    "source_submesh_index": 0,
                    "source_vertex_start": 0,
                    "source_vertex_count": 4,
                    "positions_binary": {"path": "positions.bin", "count": 4, "components": 3, "type": "f64", "delete_after": True},
                    "normals_binary": {"path": "normals.bin", "count": 4, "components": 3, "type": "f64", "delete_after": True},
                    "uvs_binary": {"path": "uvs.bin", "count": 4, "components": 2, "type": "f64", "delete_after": True},
                }
            ],
            groups,
        )
        self.assertFalse(hasattr(mesh.submeshes[0], "cdmw_native_preview_vertex_update_group"))

    def test_live_vertex_update_python_fallback_uses_compact_source_range(self) -> None:
        mesh = build_synthetic_mesh()

        with (
            patch("cdmw.modding.mesh_native_core.native_mesh_core_available", return_value=False),
            patch("cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_vertex_update_groups_native", return_value={}),
        ):
            groups = mesh_edit_vertex_update_groups(mesh, {0: range(0, 4)}, allow_python_fallback=True)

        self.assertEqual(1, len(groups))
        self.assertEqual(0, groups[0]["source_vertex_start"])
        self.assertEqual(4, groups[0]["source_vertex_count"])
        self.assertNotIn("source_vertex_indices", groups[0])

    def test_live_vertex_update_python_fallback_is_legacy_opt_in(self) -> None:
        mesh = build_synthetic_mesh()

        with (
            patch("cdmw.modding.mesh_native_core.native_mesh_core_available", return_value=False),
            patch("cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_vertex_update_groups_native", return_value={}),
        ):
            groups = mesh_edit_vertex_update_groups(mesh, {0: range(0, 4)})

        self.assertEqual([], groups)

    def test_triangle_groups_forward_native_binary_descriptors(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].cdmw_native_preview_triangle_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices_binary": {"path": "source_vertices.bin", "count": 4, "components": 1, "type": "i32", "delete_after": True},
            "source_face_indices_binary": {"path": "source_faces.bin", "count": 2, "components": 1, "type": "i32", "delete_after": True},
            "positions_binary": {"path": "positions.bin", "count": 4, "components": 3, "type": "f64", "delete_after": True},
            "normals_binary": {"path": "normals.bin", "count": 4, "components": 3, "type": "f64", "delete_after": True},
            "uvs_binary": {"path": "uvs.bin", "count": 4, "components": 2, "type": "f64", "delete_after": True},
            "indices_binary": {"path": "indices.bin", "count": 6, "components": 1, "type": "i32", "delete_after": True},
        }

        groups = mesh_edit_triangle_groups(mesh, (0,))

        self.assertEqual("cdmw_mesh_core", groups[0]["preview_backend"])
        self.assertEqual("positions.bin", groups[0]["positions_binary"]["path"])
        self.assertEqual("indices.bin", groups[0]["indices_binary"]["path"])
        self.assertNotIn("positions", groups[0])
        self.assertFalse(hasattr(mesh.submeshes[0], "cdmw_native_preview_triangle_group"))

    def test_triangle_groups_forward_native_source_ranges(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].cdmw_native_preview_triangle_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_start": 7,
            "source_vertex_count": 4,
            "source_face_start": 3,
            "source_face_count": 2,
            "positions_binary": {"path": "positions.bin", "count": 4, "components": 3, "type": "f64", "delete_after": True},
            "normals_binary": {"path": "normals.bin", "count": 4, "components": 3, "type": "f64", "delete_after": True},
            "uvs_binary": {"path": "uvs.bin", "count": 4, "components": 2, "type": "f64", "delete_after": True},
            "indices_binary": {"path": "indices.bin", "count": 6, "components": 1, "type": "i32", "delete_after": True},
        }

        groups = mesh_edit_triangle_groups(mesh, (0,))

        self.assertEqual("cdmw_mesh_core", groups[0]["preview_backend"])
        self.assertEqual([7, 8, 9, 10], _i32_descriptor_values(groups[0], "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual([3, 4], _i32_descriptor_values(groups[0], "source_face_indices", "source_face_indices_binary"))
        self.assertNotIn("source_vertex_indices", groups[0])
        self.assertNotIn("source_vertex_indices_binary", groups[0])
        self.assertNotIn("source_face_indices", groups[0])
        self.assertNotIn("source_face_indices_binary", groups[0])
        self.assertFalse(hasattr(mesh.submeshes[0], "cdmw_native_preview_triangle_group"))

    def test_triangle_group_python_fallback_uses_compact_identity_ranges(self) -> None:
        mesh = build_synthetic_mesh()

        with (
            patch("cdmw.modding.mesh_native_core.native_mesh_core_available", return_value=False),
            patch("cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_triangle_groups_native", return_value={}),
        ):
            groups = mesh_edit_triangle_groups(mesh, (0,), allow_python_fallback=True)

        self.assertEqual(0, groups[0]["source_vertex_start"])
        self.assertEqual(4, groups[0]["source_vertex_count"])
        self.assertEqual(0, groups[0]["source_face_start"])
        self.assertEqual(2, groups[0]["source_face_count"])
        self.assertNotIn("source_vertex_indices", groups[0])
        self.assertNotIn("source_face_indices", groups[0])

    def test_triangle_group_python_fallback_is_legacy_opt_in(self) -> None:
        mesh = build_synthetic_mesh()

        with (
            patch("cdmw.modding.mesh_native_core.native_mesh_core_available", return_value=False),
            patch("cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_triangle_groups_native", return_value={}),
        ):
            groups = mesh_edit_triangle_groups(mesh, (0,))

        self.assertEqual([], groups)

    def test_standalone_preview_initial_blob_uses_native_geometry_writer(self) -> None:
        mesh = build_synthetic_mesh()
        vertex_struct = struct.Struct("<23f")
        native_blob = b"".join(
            vertex_struct.pack(
                float(index),
                0.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.25,
                0.55,
                0.85,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
            )
            for index in range(6)
        )
        identity_blob = struct.pack(
            "<iiiiiiiiiiiiiiiiii",
            0,
            0,
            0,
            0,
            1,
            0,
            0,
            2,
            0,
            0,
            1,
            1,
            0,
            3,
            1,
            0,
            2,
            1,
        )
        calls: list[dict[str, object]] = []

        def _fake_native_geometry(output_path: Path, **kwargs: object) -> dict[str, object]:
            calls.append(dict(kwargs))
            Path(output_path).write_bytes(native_blob)
            identity_output_path = kwargs.get("identity_output_path")
            if identity_output_path:
                Path(identity_output_path).write_bytes(identity_blob)
            return {
                "vertex_count": 6,
                "geometry_size": len(native_blob),
                "batches": [
                    {
                        "mesh_index": 0,
                        "first_vertex": 0,
                        "vertex_count": 6,
                        "has_texture_coordinates": True,
                        "source_vertex_indices": [0, 1, 2, 1, 3, 2],
                        "source_face_indices": [0, 1],
                        "identity_offset": 0,
                        "identity_size": len(identity_blob),
                    }
                ],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"),
            patch("cdmw.modding.mesh_native_core.write_native_preview_geometry_blob", side_effect=_fake_native_geometry),
        ):
            prepared = mesh_to_native_preview(mesh)

        self.assertEqual(1, len(calls))
        self.assertEqual("session-0", calls[0]["meshes"][0]["session_id"])
        self.assertNotIn("positions", calls[0]["meshes"][0])
        self.assertNotIn("normals", calls[0]["meshes"][0])
        self.assertNotIn("texture_coordinates", calls[0]["meshes"][0])
        self.assertNotIn("faces", calls[0]["meshes"][0])
        self.assertNotIn("source_vertex_indices", calls[0]["meshes"][0])
        self.assertNotIn("source_face_indices", calls[0]["meshes"][0])
        self.assertNotIn("indices", calls[0]["meshes"][0])
        self.assertEqual(6, prepared.batches[0].index_count)
        self.assertEqual((0, 1, 2, 1, 3, 2), prepared.batches[0].source_vertex_indices)
        self.assertEqual((0, 1), prepared.batches[0].source_face_indices)
        self.assertEqual(identity_blob, prepared.batches[0].editor_identity_blob)

    def test_standalone_preview_records_native_geometry_fallback(self) -> None:
        clear_native_mesh_core_fallback_counts()
        try:
            with patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "native Mesh Editor preview geometry unavailable"):
                    mesh_to_native_preview(build_synthetic_mesh())

            self.assertEqual({"preview_geometry": 1}, native_mesh_core_fallback_counts())
            self.assertEqual("native preview geometry unavailable", native_mesh_core_fallback_events()[0]["reason"])
        finally:
            clear_native_mesh_core_fallback_counts()

    def test_large_standalone_initial_preview_python_fallback_blocks_when_native_available(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].vertices = [(0.0, 0.0, 0.0)] * 10_001
        mesh.submeshes[0].normals = [(0.0, 0.0, 1.0)] * 10_001
        mesh.submeshes[0].uvs = [(0.0, 0.0)] * 10_001
        mesh.submeshes[0].faces = [(0, 1, 2)]
        mesh.submeshes[0].vertex_count = 10_001
        mesh.submeshes[0].face_count = 1
        mesh.total_vertices = 10_001
        mesh.total_faces = 1

        clear_native_mesh_core_fallback_counts()
        try:
            with (
                patch("cdmw.modding.mesh_native_core.native_mesh_core_available", return_value=True),
                patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=None),
            ):
                with self.assertRaisesRegex(RuntimeError, "native Mesh Editor preview geometry unavailable"):
                    mesh_to_native_preview(mesh)

            self.assertEqual({"preview_geometry.blocked": 1}, native_mesh_core_fallback_counts())
            self.assertEqual(
                "Python preview fallback blocked while native mesh core is available",
                native_mesh_core_fallback_events()[0]["reason"],
            )
        finally:
            clear_native_mesh_core_fallback_counts()

    def test_selection_overlay_groups_use_native_helper_when_available(self) -> None:
        mesh = build_synthetic_mesh()
        calls: list[dict[str, object]] = []

        def _fake_native_selection_groups(mesh_arg: object, **kwargs: object) -> list[dict[str, object]]:
            calls.append(dict(kwargs))
            return [
                {
                    "preview_backend": "cdmw_mesh_core",
                    "source_submesh_index": 0,
                    "source_vertex_indices": [0, 1, 2],
                    "source_face_indices": [0],
                }
            ]

        with patch("cdmw.modding.mesh_native_core.build_native_mesh_selection_groups", side_effect=_fake_native_selection_groups):
            groups = mesh_edit_selection_groups(mesh, MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}))

        self.assertEqual("cdmw_mesh_core", groups[0]["preview_backend"])
        self.assertEqual({0: {0}}, calls[0]["faces_by_submesh"])
        self.assertEqual({}, calls[0]["vertices_by_submesh"])

    def test_selection_overlay_python_fallback_uses_compact_ranges(self) -> None:
        mesh = build_synthetic_mesh()

        with (
            patch("cdmw.modding.mesh_native_core.native_mesh_core_available", return_value=False),
            patch("cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_selection_groups_native", return_value=None),
        ):
            whole_groups = mesh_edit_selection_groups(
                mesh,
                MeshEditSelection(source_indices=(0,)),
                allow_python_fallback=True,
            )
            face_groups = mesh_edit_selection_groups(
                mesh,
                MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                allow_python_fallback=True,
            )

        self.assertEqual(0, whole_groups[0]["source_vertex_start"])
        self.assertEqual(4, whole_groups[0]["source_vertex_count"])
        self.assertNotIn("source_vertex_indices", whole_groups[0])
        self.assertEqual(0, face_groups[0]["source_vertex_start"])
        self.assertEqual(3, face_groups[0]["source_vertex_count"])
        self.assertEqual(0, face_groups[0]["source_face_start"])
        self.assertEqual(1, face_groups[0]["source_face_count"])
        self.assertNotIn("source_vertex_indices", face_groups[0])
        self.assertNotIn("source_face_indices", face_groups[0])

    def test_selection_overlay_python_fallback_is_legacy_opt_in(self) -> None:
        mesh = build_synthetic_mesh()

        with (
            patch("cdmw.modding.mesh_native_core.native_mesh_core_available", return_value=False),
            patch("cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_selection_groups_native", return_value=None),
        ):
            groups = mesh_edit_selection_groups(mesh, MeshEditSelection(source_indices=(0,)))

        self.assertEqual([], groups)

    def test_large_standalone_preview_python_fallback_blocks_when_native_available(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].vertices = [(0.0, 0.0, 0.0)] * 10_001
        mesh.submeshes[0].normals = [(0.0, 0.0, 1.0)] * 10_001
        mesh.submeshes[0].uvs = [(0.0, 0.0)] * 10_001
        mesh.submeshes[0].faces = [(0, 1, 2)]
        mesh.submeshes[0].vertex_count = 10_001
        mesh.submeshes[0].face_count = 1
        mesh.total_vertices = 10_001
        mesh.total_faces = 1

        clear_native_mesh_core_fallback_counts()
        try:
            with (
                patch("cdmw.modding.mesh_native_core.native_mesh_core_available", return_value=True),
                patch("cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_triangle_groups_native", return_value={}),
                patch("cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_vertex_update_groups_native", return_value={}),
                patch("cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_selection_groups_native", return_value=None),
            ):
                triangle_groups = mesh_edit_triangle_groups(mesh)
                vertex_groups = mesh_edit_vertex_update_groups(mesh, {0: range(0, 10_001)})
                selection_groups = mesh_edit_selection_groups(mesh, MeshEditSelection(source_indices=(0,)))

            self.assertEqual([], triangle_groups)
            self.assertEqual([], vertex_groups)
            self.assertEqual([], selection_groups)
            self.assertEqual(
                {
                    "preview_triangle_group.blocked": 1,
                    "preview_vertex_update.blocked": 1,
                    "selection_overlay.blocked": 1,
                },
                native_mesh_core_fallback_counts(),
            )
        finally:
            clear_native_mesh_core_fallback_counts()

    def test_large_selection_overlay_blocks_before_python_work_estimate(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].vertices = [(0.0, 0.0, 0.0)] * 10_001
        mesh.submeshes[0].normals = [(0.0, 0.0, 1.0)] * 10_001
        mesh.submeshes[0].uvs = [(0.0, 0.0)] * 10_001
        mesh.submeshes[0].vertex_count = 10_001
        mesh.total_vertices = 10_001

        clear_native_mesh_core_fallback_counts()
        try:
            with (
                patch("cdmw.modding.mesh_native_core.native_mesh_core_available", return_value=True),
                patch("cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_selection_groups_native", return_value=None),
                patch(
                    "cdmw.ui.mesh_editor.native_preview_payloads._selection_preview_fallback_work",
                    side_effect=AssertionError("selection fallback work should be blocked first"),
                ),
            ):
                groups = mesh_edit_selection_groups(mesh, MeshEditSelection.from_maps(vertices_by_submesh={0: range(10_001)}))

            self.assertEqual([], groups)
            self.assertEqual({"selection_overlay.blocked": 1}, native_mesh_core_fallback_counts())
        finally:
            clear_native_mesh_core_fallback_counts()

    def test_preview_payloads_ignore_malformed_faces(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].faces = [(0, "bad", 2), (0, 1, 2), (0, float("inf"), 2), (1, 99, 2), (-1, 2, 3)]  # type: ignore[list-item]
        mesh.submeshes[0].face_count = len(mesh.submeshes[0].faces)
        mesh.total_faces = len(mesh.submeshes[0].faces)

        prepared = mesh_to_native_preview(mesh)
        triangle_groups = mesh_edit_triangle_groups(mesh)
        selection_groups = mesh_edit_selection_groups(mesh, MeshEditSelection.from_maps(faces_by_submesh={0: (0, 1, 2)}))

        self.assertEqual(1, prepared.face_count)
        self.assertEqual(3, prepared.batches[0].index_count)
        prepared_identity = {
            "source_vertex_indices": list(prepared.batches[0].source_vertex_indices),
            "source_vertex_indices_binary": prepared.batches[0].source_vertex_indices_binary,
            "source_vertex_start": prepared.batches[0].source_vertex_range_start,
            "source_vertex_count": prepared.batches[0].source_vertex_range_count,
            "source_face_indices": list(prepared.batches[0].source_face_indices),
            "source_face_indices_binary": prepared.batches[0].source_face_indices_binary,
            "source_face_start": prepared.batches[0].source_face_range_start,
            "source_face_count": prepared.batches[0].source_face_range_count,
        }
        self.assertEqual([0, 1, 2], _i32_descriptor_values(prepared_identity, "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual([1], _i32_descriptor_values(prepared_identity, "source_face_indices", "source_face_indices_binary"))
        self.assertEqual([1], _i32_descriptor_values(triangle_groups[0], "source_face_indices", "source_face_indices_binary"))
        self.assertEqual([0, 1, 2], _i32_descriptor_values(triangle_groups[0], "indices", "indices_binary"))
        self.assertEqual([0, 1, 2], _i32_descriptor_values(selection_groups[0], "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual([1], _i32_descriptor_values(selection_groups[0], "source_face_indices", "source_face_indices_binary"))

    def test_vertex_update_consumes_native_group_before_scanning_changed_ids(self) -> None:
        class CountOnlyIndices:
            def __len__(self) -> int:
                return 2

            def __iter__(self):  # type: ignore[no-untyped-def]
                raise AssertionError("python changed-id scan")

        mesh = build_synthetic_mesh()
        mesh.submeshes[0].cdmw_native_preview_vertex_update_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices": [0, 2],
            "positions": [0.0, 0.0, 0.0, 1.0, 1.0, 0.0],
            "normals": [0.0, 0.0, 1.0, 0.0, 0.0, 1.0],
            "uvs": [0.0, 0.0, 1.0, 1.0],
        }

        with patch(
            "cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_vertex_update_groups_native",
            side_effect=AssertionError("native generator fallback"),
        ):
            groups = mesh_edit_vertex_update_groups(mesh, {0: CountOnlyIndices()})  # type: ignore[dict-item]

        self.assertEqual([0, 2], groups[0]["source_vertex_indices"])
        self.assertEqual([0.0, 0.0, 0.0, 1.0, 1.0, 0.0], groups[0]["positions"])

    def test_vertex_update_descriptor_reaches_native_generator_before_python_scan(self) -> None:
        mesh = build_synthetic_mesh()
        descriptor_input = {
            "changed_vertices_binary": {"path": "changed.bin", "count": 2, "components": 1, "type": "i32", "delete_after": True}
        }
        native_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices_binary": {"path": "changed.bin", "count": 2, "components": 1, "type": "i32", "delete_after": True},
            "positions_binary": {"path": "positions.bin", "count": 2, "components": 3, "type": "f64", "delete_after": True},
            "normals_binary": {"path": "normals.bin", "count": 2, "components": 3, "type": "f64", "delete_after": True},
            "uvs_binary": {"path": "uvs.bin", "count": 2, "components": 2, "type": "f64", "delete_after": True},
        }

        def native_groups(_mesh: object, changed_vertices_by_submesh: object) -> dict[int, dict[str, object]]:
            self.assertEqual({0: descriptor_input}, changed_vertices_by_submesh)
            return {0: native_group}

        with (
            patch("cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_vertex_update_groups_native", side_effect=native_groups),
            patch("cdmw.ui.mesh_editor.native_preview_payloads._source_vertex_indices", side_effect=AssertionError("python id scan")),
        ):
            groups = mesh_edit_vertex_update_groups(mesh, {0: descriptor_input})

        self.assertEqual([native_group], groups)

    def test_vertex_update_native_generator_retries_after_session_invalidation(self) -> None:
        from cdmw.ui.mesh_editor import native_preview_payloads

        mesh = build_synthetic_mesh()
        native_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_start": 0,
            "source_vertex_count": 4,
            "positions_binary": {"path": "positions.bin", "count": 4, "components": 3, "type": "f64", "delete_after": True},
        }
        calls: list[dict[int, object]] = []
        invalidated: list[int] = []

        def native_groups(_mesh: object, changed_vertices_by_submesh: object) -> list[dict[str, object]]:
            calls.append(dict(changed_vertices_by_submesh))  # type: ignore[arg-type]
            return [] if len(calls) == 1 else [native_group]

        def invalidate(_mesh: object, submesh_indices: object) -> None:
            invalidated.extend(int(index) for index in submesh_indices)  # type: ignore[arg-type]

        with (
            patch("cdmw.modding.mesh_native_core.build_native_mesh_preview_vertex_update_groups", side_effect=native_groups),
            patch("cdmw.modding.mesh_native_core.invalidate_native_mesh_session_submeshes", side_effect=invalidate),
        ):
            groups = native_preview_payloads._mesh_edit_vertex_update_groups_native(mesh, {0: range(0, 4)})

        self.assertEqual([{0: range(0, 4)}, {0: range(0, 4)}], calls)
        self.assertEqual([0], invalidated)
        self.assertEqual(native_group, groups[0])

    def test_vertex_update_native_generator_sends_sanitized_request(self) -> None:
        from cdmw.ui.mesh_editor import native_preview_payloads

        mesh = build_synthetic_mesh()
        native_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_start": 0,
            "source_vertex_count": 4,
            "positions_binary": {"path": "positions.bin", "count": 4, "components": 3, "type": "f64"},
        }
        calls: list[dict[int, object]] = []

        def native_groups(_mesh: object, changed_vertices_by_submesh: object) -> list[dict[str, object]]:
            calls.append(dict(changed_vertices_by_submesh))  # type: ignore[arg-type]
            return [native_group]

        with patch("cdmw.modding.mesh_native_core.build_native_mesh_preview_vertex_update_groups", side_effect=native_groups):
            groups = native_preview_payloads._mesh_edit_vertex_update_groups_native(
                mesh,
                {0: range(0, 4), -1: range(0, 1), 999: range(0, 1), "bad": range(0, 1)},  # type: ignore[dict-item]
            )

        self.assertEqual([{0: range(0, 4)}], calls)
        self.assertEqual(native_group, groups[0])

    def test_preview_payloads_sanitize_non_finite_vertex_data(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.total_vertices = float("inf")  # type: ignore[assignment]
        mesh.submeshes[0].vertices[1] = (float("inf"), 5.0, float("nan"))  # type: ignore[index]
        mesh.submeshes[0].normals[1] = (float("nan"), 0.5, float("inf"))  # type: ignore[index]
        mesh.submeshes[0].uvs[1] = (float("inf"), float("nan"))  # type: ignore[index]
        mesh.submeshes[0].preview_native_material_overrides = {
            "texture_brightness": "1.2",
            "roughness": float("inf"),
            "metalness": 0.2,
            "specular": True,
            "emissive_color": "bad",
            "tint_color": [0.2, 0.3, 0.4],
        }

        with self.assertRaisesRegex(RuntimeError, "native Mesh Editor preview geometry unavailable"):
            mesh_to_native_preview(mesh)
        with patch("cdmw.modding.mesh_native_core.native_mesh_core_available", return_value=False):
            triangle_groups = mesh_edit_triangle_groups(
                mesh,
                source_submesh_indices=(True, 0.5, 0, float("inf")),  # type: ignore[arg-type]
                allow_python_fallback=True,
            )
            vertex_groups = mesh_edit_vertex_update_groups(
                mesh,
                {0: (True, 1.0, 1.9, float("inf"), "bad"), float("inf"): (0,)},  # type: ignore[dict-item]
                allow_python_fallback=True,
            )
        material_groups = mesh_edit_material_override_groups(mesh, (0,))
        reset_material_groups = mesh_edit_material_override_groups(mesh, (0,), include_defaults=True)

        self.assertEqual([0.0, 5.0, 0.0], _f64_descriptor_values(triangle_groups[0], "positions", "positions_binary")[3:6])
        self.assertEqual([0.0, 0.5, 0.0], _f64_descriptor_values(triangle_groups[0], "normals", "normals_binary")[3:6])
        self.assertEqual([0.0, 0.0], _f64_descriptor_values(triangle_groups[0], "uvs", "uvs_binary")[2:4])
        self.assertEqual([1], _i32_descriptor_values(vertex_groups[0], "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual([0.0, 5.0, 0.0], _f64_descriptor_values(vertex_groups[0], "positions", "positions_binary"))
        self.assertEqual([0.0, 0.5, 0.0], _f64_descriptor_values(vertex_groups[0], "normals", "normals_binary"))
        self.assertEqual([0.0, 0.0], _f64_descriptor_values(vertex_groups[0], "uvs", "uvs_binary"))
        self.assertEqual(1.2, material_groups[0]["texture_brightness"])
        self.assertEqual(0.2, material_groups[0]["metalness"])
        self.assertEqual([0.2, 0.3, 0.4], material_groups[0]["tint_color"])
        self.assertNotIn("roughness", material_groups[0])
        self.assertNotIn("specular", material_groups[0])
        self.assertNotIn("emissive_color", material_groups[0])
        self.assertEqual(0.0, reset_material_groups[0]["roughness"])
        self.assertEqual(0.0, reset_material_groups[0]["specular"])
        self.assertEqual([0.35, 0.68, 1.0], reset_material_groups[0]["emissive_color"])
        self.assertEqual([], mesh_edit_triangle_groups(mesh, source_submesh_indices=float("inf")))  # type: ignore[arg-type]
        self.assertEqual([], mesh_edit_vertex_update_groups(mesh, {0: float("inf")}))  # type: ignore[dict-item]


if __name__ == "__main__":
    unittest.main()
