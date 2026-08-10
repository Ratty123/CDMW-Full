from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from tests.test_native_mesh_editor_session import _quad_mesh


class NativeMeshEditorSessionProtocolTests(unittest.TestCase):
    def test_resident_session_separate_append_undo_redo_keeps_native_state(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-separate-{uuid4().hex}"
        try:
            open_report = mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0)
            self.assertIsNotNone(open_report)
            self.assertEqual(1, open_report["submesh_count"])

            select_report = mesh_native_core.select_native_mesh_editor_session(
                session_id,
                {"faces_by_submesh": {0: (0,)}},
                timeout_seconds=5.0,
            )
            self.assertIsNotNone(select_report)

            apply_report = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {"operation": "separate"},
                timeout_seconds=10.0,
            )
            undo_report = mesh_native_core.undo_native_mesh_editor_session(session_id, timeout_seconds=10.0)
            redo_report = mesh_native_core.redo_native_mesh_editor_session(session_id, timeout_seconds=10.0)
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(apply_report)
        self.assertIsNotNone(undo_report)
        self.assertIsNotNone(redo_report)
        self.assertEqual([0, 1], apply_report["affected_submesh_indices"])
        self.assertEqual(2, apply_report["submesh_count"])
        self.assertTrue(apply_report["topology_changed"])
        source_item, append_item = apply_report["edit_report"]["submeshes"]
        self.assertEqual(0, source_item["index"])
        self.assertEqual(0, source_item["preview_triangle_group"]["source_submesh_index"])
        self.assertTrue(append_item["append_submesh"])
        self.assertEqual(1, append_item["index"])
        self.assertEqual("quad split", append_item["name"])
        self.assertEqual("mat", append_item["material"])
        self.assertEqual("a.dds", append_item["texture"])
        self.assertEqual(1, append_item["preview_triangle_group"]["source_submesh_index"])

        self.assertEqual([0, 1], undo_report["affected_submesh_indices"])
        self.assertEqual(1, undo_report["submesh_count"])
        self.assertTrue(undo_report["topology_changed"])
        self.assertEqual(1, len(undo_report["edit_report"]["submeshes"]))
        self.assertEqual(0, undo_report["edit_report"]["submeshes"][0]["index"])

        redo_source, redo_append = redo_report["edit_report"]["submeshes"]
        self.assertEqual([0, 1], redo_report["affected_submesh_indices"])
        self.assertEqual(2, redo_report["submesh_count"])
        self.assertTrue(redo_report["topology_changed"])
        self.assertEqual(0, redo_source["index"])
        self.assertTrue(redo_append["append_submesh"])
        self.assertEqual(1, redo_append["index"])
        self.assertEqual("quad split", redo_append["name"])
        self.assertEqual("mat", redo_append["material"])
        self.assertEqual("a.dds", redo_append["texture"])
        self.assertEqual(1, redo_append["preview_triangle_group"]["source_submesh_index"])

    def test_open_sends_editor_session_command_with_binary_submeshes(self) -> None:
        from cdmw.modding import mesh_native_core

        calls: list[dict[str, object]] = []

        def service_job(_binary: Path, command: str, payload: dict[str, object], **_kwargs: object) -> dict[str, object]:
            self.assertEqual("mesh-editor-session-json", command)
            calls.append(payload)
            self.assertEqual("open", payload["command"])
            item = payload["submeshes"][0]  # type: ignore[index]
            self.assertEqual(0, item["index"])
            self.assertEqual("quad", item["name"])
            self.assertEqual("mat", item["material"])
            self.assertEqual("a.dds", item["texture"])
            self.assertTrue(Path(item["vertices_binary"]["path"]).is_file())  # type: ignore[index]
            self.assertTrue(Path(item["faces_binary"]["path"]).is_file())  # type: ignore[index]
            self.assertIn("normals_binary", item)
            self.assertIn("uvs_binary", item)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "protocol": "mesh-editor-session-json",
                "command": "open",
                "session_id": payload["session_id"],
                "submesh_count": 1,
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_enabled", return_value=True),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=service_job),
        ):
            report = mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), "editor-1", timeout_seconds=1.0)

        self.assertIsNotNone(report)
        self.assertEqual("editor-1", report["session_id"])
        self.assertEqual(1, len(calls))
        self.assertEqual("mesh-editor-session-json", calls[0]["protocol"])

    def test_select_and_apply_use_same_editor_session_protocol(self) -> None:
        from cdmw.modding import mesh_native_core

        commands: list[tuple[str, dict[str, object]]] = []

        def service_job(_binary: Path, command: str, payload: dict[str, object], **_kwargs: object) -> dict[str, object]:
            commands.append((command, payload))
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "protocol": "mesh-editor-session-json",
                "command": payload["command"],
                "session_id": payload["session_id"],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_enabled", return_value=True),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=service_job),
        ):
            select_report = mesh_native_core.select_native_mesh_editor_session(
                "editor-1",
                {"faces_by_submesh": [{"index": 0, "indices": [0]}]},
            )
            apply_report = mesh_native_core.apply_native_mesh_editor_session(
                "editor-1",
                {"operation": "delete", "mode": "faces"},
                include_preview_deltas=False,
            )

        self.assertIsNotNone(select_report)
        self.assertIsNotNone(apply_report)
        self.assertEqual("mesh-editor-session-json", commands[0][0])
        self.assertEqual("select", commands[0][1]["command"])
        self.assertEqual("replace", commands[0][1]["selection_operation"])
        self.assertTrue(Path(commands[0][1]["selection_output_dir"]).is_dir())
        self.assertEqual("apply", commands[1][1]["command"])
        self.assertEqual({"operation": "delete", "mode": "faces"}, commands[1][1]["edit"])
        self.assertTrue(Path(commands[1][1]["delta_output_dir"]).is_dir())
        self.assertTrue(commands[1][1]["include_edit_report"])
        self.assertFalse(commands[1][1]["include_preview_deltas"])

    def test_editor_session_selection_report_parser_reads_ranges_and_sidecars(self) -> None:
        from cdmw.modding import mesh_native_core

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            vertices_path = root / "vertices.bin"
            edges_path = root / "edges.bin"
            vertices_path.write_bytes(struct.pack("<ii", 1, 3))
            edges_path.write_bytes(struct.pack("<iiii", 0, 1, 2, 3))
            parsed = mesh_native_core.native_mesh_editor_session_selection_from_report(
                {
                    "submeshes": [
                        {
                            "index": 0,
                            "selected_vertices_binary": {
                                "path": str(vertices_path),
                                "count": 2,
                                "components": 1,
                                "type": "i32",
                            },
                            "selected_edges_binary": {
                                "path": str(edges_path),
                                "count": 2,
                                "components": 2,
                                "type": "i32",
                            },
                            "selected_face_start": 4,
                            "selected_face_count": 2,
                        }
                    ],
                    "source_indices": [0],
                }
            )

        self.assertIsNotNone(parsed)
        self.assertEqual({0: {1, 3}}, parsed["vertices_by_submesh"])
        self.assertEqual({0: {(0, 1), (2, 3)}}, parsed["edges_by_submesh"])
        self.assertEqual({0: {4, 5}}, parsed["faces_by_submesh"])
        self.assertEqual((0,), parsed["source_indices"])

    def test_apply_editor_session_accepts_explicit_native_stroke_payload(self) -> None:
        from cdmw.modding import mesh_native_core

        captured: dict[str, object] = {}

        def service_job(_binary: Path, command: str, payload: dict[str, object], **_kwargs: object) -> dict[str, object]:
            self.assertEqual("mesh-editor-session-json", command)
            captured.update(payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "protocol": "mesh-editor-session-json",
                "command": payload["command"],
                "session_id": payload["session_id"],
                "stroke": {
                    "phase": payload["edit"]["stroke_phase"],  # type: ignore[index]
                    "stroke_id": payload["edit"]["stroke_id"],  # type: ignore[index]
                    "active": True,
                },
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_enabled", return_value=True),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=service_job),
        ):
            report = mesh_native_core.apply_native_mesh_editor_session(
                "editor-1",
                {"operation": "transform", "translate": (0.0, 0.0, 0.25)},
                stroke_phase="BEGIN",
                stroke_id="drag-1",
            )

        self.assertIsNotNone(report)
        self.assertEqual("apply", captured["command"])
        self.assertEqual("begin", captured["edit"]["stroke_phase"])  # type: ignore[index]
        self.assertEqual("drag-1", captured["edit"]["stroke_id"])  # type: ignore[index]
        self.assertEqual({"phase": "begin", "stroke_id": "drag-1", "active": True}, report["stroke"])

    def test_undo_and_redo_request_delta_reports(self) -> None:
        from cdmw.modding import mesh_native_core

        commands: list[dict[str, object]] = []

        def service_job(_binary: Path, command: str, payload: dict[str, object], **_kwargs: object) -> dict[str, object]:
            self.assertEqual("mesh-editor-session-json", command)
            commands.append(payload)
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "protocol": "mesh-editor-session-json",
                "command": payload["command"],
                "session_id": payload["session_id"],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_enabled", return_value=True),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=service_job),
        ):
            undo_report = mesh_native_core.undo_native_mesh_editor_session("editor-1")
            redo_report = mesh_native_core.redo_native_mesh_editor_session("editor-1")

        self.assertIsNotNone(undo_report)
        self.assertIsNotNone(redo_report)
        self.assertEqual(["undo", "redo"], [command["command"] for command in commands])
        for command in commands:
            self.assertTrue(Path(command["delta_output_dir"]).is_dir())
            self.assertTrue(command["include_edit_report"])

    def test_large_select_uses_range_and_binary_sidecars(self) -> None:
        from cdmw.modding import mesh_native_core

        captured: dict[str, object] = {}

        def service_job(_binary: Path, command: str, payload: dict[str, object], **_kwargs: object) -> dict[str, object]:
            self.assertEqual("mesh-editor-session-json", command)
            captured.update(payload)
            selection = payload["selection"]  # type: ignore[index]
            vertices = selection["vertices_by_submesh"][0]  # type: ignore[index]
            faces = selection["faces_by_submesh"][0]  # type: ignore[index]
            edges = selection["edges_by_submesh"][0]  # type: ignore[index]
            self.assertEqual({"index": 0, "start": 0, "count": 100_000}, vertices)
            self.assertNotIn("indices", faces)
            self.assertTrue(Path(faces["indices_binary"]["path"]).is_file())  # type: ignore[index]
            self.assertNotIn("edges", edges)
            self.assertTrue(Path(edges["edges_binary"]["path"]).is_file())  # type: ignore[index]
            return {
                "status": "ok",
                "backend": "cdmw_mesh_core_0.1",
                "protocol": "mesh-editor-session-json",
                "command": "select",
                "session_id": payload["session_id"],
            }

        with (
            patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.modding.mesh_native_core._native_mesh_core_service_enabled", return_value=True),
            patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=service_job),
        ):
            report = mesh_native_core.select_native_mesh_editor_session(
                "editor-1",
                {
                    "vertices_by_submesh": {0: range(100_000)},
                    "faces_by_submesh": {0: range(0, 6000, 2)},
                    "edges_by_submesh": {0: tuple((index, index + 1) for index in range(3000))},
                },
            )

        self.assertIsNotNone(report)
        self.assertEqual("select", captured["command"])


if __name__ == "__main__":
    unittest.main()
