import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh


def _assert_vec3_close(test: unittest.TestCase, actual: object, expected: tuple[float, float, float]) -> None:
    test.assertEqual(3, len(actual))  # type: ignore[arg-type]
    for actual_value, expected_value in zip(actual, expected):  # type: ignore[arg-type]
        test.assertAlmostEqual(float(actual_value), expected_value, places=6)


def _screen_wvp(x_offset: float = 0.0) -> list[float]:
    return [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 0.5, 0.0,
        x_offset, 0.0, 0.5, 1.0,
    ]


def _quad_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="quad",
        material="mat",
        texture="a.dds",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
        ],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)],
        normals=[(0.0, 0.0, 1.0)] * 4,
        faces=[(0, 1, 2), (1, 3, 2)],
        vertex_count=4,
        face_count=2,
    )
    return ParsedMesh(
        path="quad.pac",
        format="pac",
        submeshes=[submesh],
        total_vertices=4,
        total_faces=2,
        has_uvs=True,
    )


def _two_part_mesh() -> ParsedMesh:
    first = _quad_mesh().submeshes[0]
    second = SubMesh(
        name="quad_b",
        material="mat_b",
        texture="b.dds",
        vertices=list(first.vertices),
        uvs=list(first.uvs),
        normals=list(first.normals),
        faces=list(first.faces),
        vertex_count=4,
        face_count=2,
    )
    return ParsedMesh(
        path="two_part.pac",
        format="pac",
        submeshes=[first, second],
        total_vertices=8,
        total_faces=4,
        has_uvs=True,
    )


def _overlapping_depth_mesh() -> ParsedMesh:
    vertices = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (1.0, 1.0, 0.0),
        (0.0, 0.0, 0.5),
        (1.0, 0.0, 0.5),
        (0.0, 1.0, 0.5),
        (1.0, 1.0, 0.5),
        (0.25, 0.25, 0.0),
        (0.25, 0.25, 0.5),
    ]
    submesh = SubMesh(
        name="overlap",
        material="mat",
        texture="a.dds",
        vertices=vertices,
        uvs=[(0.0, 0.0)] * len(vertices),
        normals=[(0.0, 0.0, 1.0)] * len(vertices),
        faces=[(0, 1, 2), (1, 3, 2), (4, 5, 6), (5, 7, 6)],
        vertex_count=len(vertices),
        face_count=4,
    )
    return ParsedMesh(
        path="overlap.pac",
        format="pac",
        submeshes=[submesh],
        total_vertices=len(vertices),
        total_faces=4,
        has_uvs=True,
    )


def _duplicate_loose_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="duplicate_loose",
        material="mat",
        texture="a.dds",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0002, 0.0, 0.0),
            (2.0, 2.0, 2.0),
        ],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0), (0.0, 0.0), (0.5, 0.5)],
        normals=[(0.0, 0.0, 1.0)] * 6,
        faces=[(0, 1, 2), (4, 3, 2)],
        vertex_count=6,
        face_count=2,
    )
    return ParsedMesh(
        path="duplicate_loose.pac",
        format="pac",
        submeshes=[submesh],
        total_vertices=6,
        total_faces=2,
        has_uvs=True,
    )


def _loose_vertex_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="loose_vertex",
        material="mat",
        texture="a.dds",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
            (2.0, 2.0, 2.0),
        ],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0), (0.5, 0.5)],
        normals=[(0.0, 0.0, 1.0)] * 5,
        faces=[(0, 1, 2), (1, 3, 2)],
        vertex_count=5,
        face_count=2,
    )
    return ParsedMesh(
        path="loose_vertex.pac",
        format="pac",
        submeshes=[submesh],
        total_vertices=5,
        total_faces=2,
        has_uvs=True,
    )


def _loose_edge_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="loose_edges",
        material="mat",
        texture="a.dds",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
        ],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)],
        normals=[(0.0, 0.0, 1.0)] * 4,
        faces=[],
        vertex_count=4,
        face_count=0,
    )
    return ParsedMesh(
        path="loose_edges.pac",
        format="pac",
        submeshes=[submesh],
        total_vertices=4,
        total_faces=0,
        has_uvs=True,
    )


def _reversed_triangle_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="triangle",
        material="mat",
        texture="a.dds",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
        ],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        normals=[(0.0, 0.0, 1.0)] * 3,
        faces=[(0, 2, 1)],
        vertex_count=3,
        face_count=1,
    )
    return ParsedMesh(
        path="triangle.pac",
        format="pac",
        submeshes=[submesh],
        total_vertices=3,
        total_faces=1,
        has_uvs=True,
    )


class NativeMeshEditorSessionBridgeTests(unittest.TestCase):
    def test_resident_live_stroke_coalesces_transform_updates_in_native_history(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-stroke-{uuid4().hex}"
        stroke_id = f"stroke-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_stroke_snapshot_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"vertices_by_submesh": {0: (1,)}},
                    timeout_seconds=5.0,
                )
            )
            begin = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {"operation": "transform", "translate": (0.0, 0.0, 0.1)},
                stroke_phase="begin",
                stroke_id=stroke_id,
                timeout_seconds=10.0,
            )
            update = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {"operation": "transform", "translate": (0.0, 0.0, 0.2)},
                stroke_phase="update",
                stroke_id=stroke_id,
                timeout_seconds=10.0,
            )
            finish = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {"operation": "transform", "translate": (0.0, 0.0, 0.3)},
                stroke_phase="end",
                stroke_id=stroke_id,
                timeout_seconds=10.0,
            )
            after_stroke = export_vertices()
            undo = mesh_native_core.undo_native_mesh_editor_session(session_id, timeout_seconds=10.0)
            after_undo = export_vertices()
            redo = mesh_native_core.redo_native_mesh_editor_session(session_id, timeout_seconds=10.0)
            after_redo = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(begin)
        self.assertIsNotNone(update)
        self.assertIsNotNone(finish)
        self.assertEqual("begin", begin["stroke"]["phase"])  # type: ignore[index]
        self.assertTrue(begin["stroke"]["active"])  # type: ignore[index]
        self.assertFalse(begin["stroke"]["history_coalesced"])  # type: ignore[index]
        self.assertEqual("update", update["stroke"]["phase"])  # type: ignore[index]
        self.assertTrue(update["stroke"]["history_coalesced"])  # type: ignore[index]
        self.assertEqual("end", finish["stroke"]["phase"])  # type: ignore[index]
        self.assertFalse(finish["stroke"]["active"])  # type: ignore[index]
        self.assertTrue(finish["stroke"]["history_coalesced"])  # type: ignore[index]
        _assert_vec3_close(self, after_stroke[1], (1.0, 0.0, 0.6))
        self.assertIsNotNone(undo)
        _assert_vec3_close(self, after_undo[1], (1.0, 0.0, 0.0))
        self.assertIsNotNone(redo)
        _assert_vec3_close(self, after_redo[1], (1.0, 0.0, 0.6))

    def test_native_session_transform_accepts_d3d11_object_delta(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-object-delta-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_object_delta_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"vertices_by_submesh": {0: (1,)}},
                    timeout_seconds=5.0,
                )
            )
            moved = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {"operation": "transform", "translate": {"x": 0.25, "y": 0.0, "z": 0.5}},
                timeout_seconds=10.0,
            )
            after_move = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(moved)
        _assert_vec3_close(self, after_move[1], (1.25, 0.0, 0.5))

    def test_native_session_transform_resolves_d3d11_screen_drag(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-screen-drag-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_screen_drag_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"vertices_by_submesh": {0: (1,)}},
                    timeout_seconds=5.0,
                )
            )
            moved = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "transform",
                    "screen_drag": {
                        "start_x": 2.0,
                        "start_y": 3.0,
                        "end_x": 12.0,
                        "end_y": 7.0,
                        "yaw_degrees": 0.0,
                        "pitch_degrees": 0.0,
                        "distance": 1.0,
                        "viewport_height": 200.0,
                        "vertical_fov_degrees": 90.0,
                    },
                    "axis": "x",
                },
                timeout_seconds=10.0,
            )
            after_move = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(moved)
        _assert_vec3_close(self, after_move[1], (1.1, 0.0, 0.0))

    def test_native_session_screen_drag_prefers_d3d11_camera_world_matrix(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-screen-drag-camera-world-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_screen_drag_camera_world_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"vertices_by_submesh": {0: (1,)}},
                    timeout_seconds=5.0,
                )
            )
            moved = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "transform",
                    "screen_drag": {
                        "start_x": 0.0,
                        "start_y": 0.0,
                        "end_x": 5.0,
                        "end_y": 0.0,
                        "units_per_pixel": 0.01,
                        "camera_world": [
                            0.0, 0.0, 1.0, 0.0,
                            0.0, 1.0, 0.0, 0.0,
                            -1.0, 0.0, 0.0, 0.0,
                            0.0, 0.0, 0.0, 1.0,
                        ],
                    },
                    "axis": "z",
                },
                timeout_seconds=10.0,
            )
            after_move = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(moved)
        _assert_vec3_close(self, after_move[1], (1.0, 0.0, 0.05))

    def test_native_session_screen_drag_uses_d3d11_projection_at_native_pivot(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-screen-drag-wvp-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_screen_drag_wvp_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"vertices_by_submesh": {0: (1,)}},
                    timeout_seconds=5.0,
                )
            )
            moved = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "transform",
                    "screen_drag": {
                        "start_x": 0.0,
                        "start_y": 0.0,
                        "end_x": 5.0,
                        "end_y": 0.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "world_view_projection": _screen_wvp(),
                    },
                    "axis": "x",
                },
                timeout_seconds=10.0,
            )
            after_move = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(moved)
        _assert_vec3_close(self, after_move[1], (1.05, 0.0, 0.0))

    def test_native_session_screen_drag_applies_incremental_d3d11_steps_once(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-screen-drag-steps-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_screen_drag_steps_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"vertices_by_submesh": {0: (1,)}},
                    timeout_seconds=5.0,
                )
            )
            for start_x, end_x in ((0.0, 5.0), (5.0, 10.0)):
                moved = mesh_native_core.apply_native_mesh_editor_session(
                    session_id,
                    {
                        "operation": "transform",
                        "screen_drag": {
                            "start_x": start_x,
                            "start_y": 0.0,
                            "end_x": end_x,
                            "end_y": 0.0,
                            "viewport_width": 200.0,
                            "viewport_height": 200.0,
                            "world_view_projection": _screen_wvp(),
                        },
                        "axis": "x",
                    },
                    timeout_seconds=10.0,
                )
                self.assertIsNotNone(moved)
            after_move = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        _assert_vec3_close(self, after_move[1], (1.1, 0.0, 0.0))

    def test_native_session_screen_drag_wvp_ignores_legacy_translate(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-screen-drag-legacy-translate-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_screen_drag_legacy_translate_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"vertices_by_submesh": {0: (1,)}},
                    timeout_seconds=5.0,
                )
            )
            moved = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "transform",
                    "translate": {"x": 0.0, "y": 0.0, "z": 1.0},
                    "screen_drag": {
                        "start_x": 0.0,
                        "start_y": 0.0,
                        "end_x": 5.0,
                        "end_y": 0.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "world_view_projection": _screen_wvp(),
                    },
                    "axis": "x",
                },
                timeout_seconds=10.0,
            )
            after_move = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(moved)
        _assert_vec3_close(self, after_move[1], (1.05, 0.0, 0.0))

    def test_native_session_screen_drag_wvp_failure_does_not_use_legacy_camera_fallback(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-screen-drag-invalid-wvp-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_screen_drag_invalid_wvp_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"vertices_by_submesh": {0: (1,)}},
                    timeout_seconds=5.0,
                )
            )
            moved = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "transform",
                    "screen_drag": {
                        "start_x": 0.0,
                        "start_y": 0.0,
                        "end_x": 5.0,
                        "end_y": 0.0,
                        "units_per_pixel": 0.01,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "world_view_projection": [0.0] * 16,
                        "camera_world": [
                            1.0, 0.0, 0.0, 0.0,
                            0.0, 1.0, 0.0, 0.0,
                            0.0, 0.0, 1.0, 0.0,
                            0.0, 0.0, 0.0, 1.0,
                        ],
                    },
                    "axis": "x",
                },
                timeout_seconds=10.0,
            )
            after_move = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(moved)
        _assert_vec3_close(self, after_move[1], (1.0, 0.0, 0.0))

    def test_native_session_screen_drag_uses_source_projection_override(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-screen-drag-source-wvp-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_screen_drag_source_wvp_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"vertices_by_submesh": {0: (1,)}},
                    timeout_seconds=5.0,
                )
            )
            moved = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "transform",
                    "screen_drag": {
                        "start_x": 0.0,
                        "start_y": 0.0,
                        "end_x": 5.0,
                        "end_y": 0.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "world_view_projection": [
                            0.5, 0.0, 0.0, 0.0,
                            0.0, 0.5, 0.0, 0.0,
                            0.0, 0.0, 1.0, 0.0,
                            0.0, 0.0, 0.0, 1.0,
                        ],
                        "source_submesh_world_view_projections": [
                            {"source_submesh_index": 0, "world_view_projection": _screen_wvp()},
                        ],
                    },
                    "axis": "x",
                },
                timeout_seconds=10.0,
            )
            after_move = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(moved)
        _assert_vec3_close(self, after_move[1], (1.05, 0.0, 0.0))

    def test_native_session_screen_drag_uses_source_transform_override(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-screen-drag-source-transform-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_screen_drag_source_transform_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"vertices_by_submesh": {0: (1,)}},
                    timeout_seconds=5.0,
                )
            )
            moved = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "transform",
                    "screen_drag": {
                        "start_x": 0.0,
                        "start_y": 0.0,
                        "end_x": 5.0,
                        "end_y": 0.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "world_view_projection": [
                            0.5, 0.0, 0.0, 0.0,
                            0.0, 0.5, 0.0, 0.0,
                            0.0, 0.0, 1.0, 0.0,
                            0.0, 0.0, 0.0, 1.0,
                        ],
                        "source_submesh_world_transforms": [
                            {
                                "source_submesh_index": 0,
                                "world_transform": [
                                    2.0, 0.0, 0.0, 0.0,
                                    0.0, 2.0, 0.0, 0.0,
                                    0.0, 0.0, 1.0, 0.0,
                                    0.0, 0.0, 0.0, 1.0,
                                ],
                            },
                        ],
                    },
                    "axis": "x",
                },
                timeout_seconds=10.0,
            )
            after_move = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(moved)
        _assert_vec3_close(self, after_move[1], (1.05, 0.0, 0.0))

    def test_native_session_screen_drag_invalid_source_projection_does_not_use_base_wvp(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-screen-drag-invalid-source-wvp-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_screen_drag_invalid_source_wvp_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"vertices_by_submesh": {0: (1,)}},
                    timeout_seconds=5.0,
                )
            )
            moved = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "transform",
                    "screen_drag": {
                        "start_x": 0.0,
                        "start_y": 0.0,
                        "end_x": 5.0,
                        "end_y": 0.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "world_view_projection": _screen_wvp(),
                        "source_submesh_world_view_projections": [
                            {"source_submesh_index": 0, "world_view_projection": [1.0, 2.0]},
                        ],
                    },
                    "axis": "x",
                },
                timeout_seconds=10.0,
            )
            after_move = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(moved)
        _assert_vec3_close(self, after_move[1], (1.0, 0.0, 0.0))

    def test_native_session_brush_accepts_d3d11_object_vectors(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-brush-object-vectors-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_brush_object_vectors_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"vertices_by_submesh": {0: (1,)}},
                    timeout_seconds=5.0,
                )
            )
            brushed = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "brush",
                    "tool": "grab",
                    "center": {"x": 1.0, "y": 0.0, "z": 0.0},
                    "delta": {"x": 0.0, "y": 0.0, "z": 0.5},
                    "radius": 1.0,
                    "strength": 1.0,
                    "amount": 0.5,
                },
                timeout_seconds=10.0,
            )
            after_brush = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(brushed)
        _assert_vec3_close(self, after_brush[1], (1.0, 0.0, 0.5))

    def test_native_session_brush_resolves_d3d11_screen_drag(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-brush-screen-drag-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_brush_screen_drag_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"vertices_by_submesh": {0: (1,)}},
                    timeout_seconds=5.0,
                )
            )
            brushed = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "brush",
                    "tool": "grab",
                    "center": {"x": 1.0, "y": 0.0, "z": 0.0},
                    "screen_drag": {
                        "start_x": 2.0,
                        "start_y": 0.0,
                        "end_x": 7.0,
                        "end_y": 0.0,
                        "yaw_degrees": 90.0,
                        "pitch_degrees": 0.0,
                        "distance": 1.0,
                        "viewport_height": 200.0,
                        "vertical_fov_degrees": 90.0,
                    },
                    "radius": 1.0,
                    "strength": 1.0,
                },
                timeout_seconds=10.0,
            )
            after_brush = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(brushed)
        _assert_vec3_close(self, after_brush[1], (1.0, 0.0, 0.05))

    def test_native_session_brush_screen_drag_wvp_ignores_legacy_delta(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-brush-screen-drag-legacy-delta-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_brush_screen_drag_legacy_delta_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"vertices_by_submesh": {0: (1,)}},
                    timeout_seconds=5.0,
                )
            )
            brushed = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "brush",
                    "tool": "grab",
                    "center": {"x": 1.0, "y": 0.0, "z": 0.0},
                    "delta": {"x": 0.0, "y": 0.0, "z": 1.0},
                    "screen_drag": {
                        "start_x": 0.0,
                        "start_y": 0.0,
                        "end_x": 5.0,
                        "end_y": 0.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "world_view_projection": _screen_wvp(),
                    },
                    "radius": 1.0,
                    "strength": 1.0,
                },
                timeout_seconds=10.0,
            )
            after_brush = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(brushed)
        _assert_vec3_close(self, after_brush[1], (1.05, 0.0, 0.0))

    def test_native_session_brush_screen_drag_uses_source_projection_override(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-brush-screen-drag-source-wvp-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_brush_screen_drag_source_wvp_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"vertices_by_submesh": {0: (1,)}},
                    timeout_seconds=5.0,
                )
            )
            brushed = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "brush",
                    "tool": "grab",
                    "center": {"x": 1.0, "y": 0.0, "z": 0.0},
                    "screen_drag": {
                        "start_x": 0.0,
                        "start_y": 0.0,
                        "end_x": 5.0,
                        "end_y": 0.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "world_view_projection": [
                            0.5, 0.0, 0.0, 0.0,
                            0.0, 0.5, 0.0, 0.0,
                            0.0, 0.0, 1.0, 0.0,
                            0.0, 0.0, 0.0, 1.0,
                        ],
                        "source_submesh_world_view_projections": [
                            {"source_submesh_index": 0, "world_view_projection": _screen_wvp()},
                        ],
                    },
                    "radius": 1.0,
                    "strength": 1.0,
                },
                timeout_seconds=10.0,
            )
            after_brush = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(brushed)
        _assert_vec3_close(self, after_brush[1], (1.05, 0.0, 0.0))

    def test_native_session_brush_resolves_d3d11_screen_radius_amount(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-brush-screen-radius-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_brush_screen_radius_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"vertices_by_submesh": {0: (1,)}},
                    timeout_seconds=5.0,
                )
            )
            brushed = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "brush",
                    "tool": "inflate",
                    "center": {"x": 1.0, "y": 0.0, "z": 0.0},
                    "screen_radius": {
                        "radius_pixels": 1.0,
                        "distance": 1.0,
                        "viewport_height": 2.0,
                        "vertical_fov_degrees": 90.0,
                        "amount_scale": 0.08,
                    },
                    "strength": 1.0,
                },
                timeout_seconds=10.0,
            )
            after_brush = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(brushed)
        _assert_vec3_close(self, after_brush[1], (1.0, 0.0, 0.08))

    def test_native_session_screen_radius_prefers_d3d11_projection_at_native_center(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-screen-radius-wvp-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_screen_radius_wvp_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"vertices_by_submesh": {0: (1,)}},
                    timeout_seconds=5.0,
                )
            )
            brushed = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "brush",
                    "tool": "inflate",
                    "screen_radius": {
                        "radius_pixels": 10.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "amount_scale": 0.08,
                        "world_view_projection": [
                            1.0, 0.0, 0.0, 0.0,
                            0.0, 1.0, 0.0, 0.0,
                            0.0, 0.0, 1.0, 0.0,
                            0.0, 0.0, 0.0, 1.0,
                        ],
                    },
                    "strength": 1.0,
                },
                timeout_seconds=10.0,
            )
            after_brush = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(brushed)
        _assert_vec3_close(self, after_brush[1], (1.0, 0.0, 0.008))

    def test_native_session_screen_radius_wvp_ignores_legacy_center_radius_and_amount(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-screen-radius-legacy-fields-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_screen_radius_legacy_fields_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"vertices_by_submesh": {0: (1,)}},
                    timeout_seconds=5.0,
                )
            )
            brushed = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "brush",
                    "tool": "inflate",
                    "center": {"x": 1.0, "y": 0.0, "z": 99.0},
                    "radius": 50.0,
                    "amount": 1.0,
                    "screen_radius": {
                        "radius_pixels": 10.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "amount_scale": 0.08,
                        "world_view_projection": [
                            1.0, 0.0, 0.0, 0.0,
                            0.0, 1.0, 0.0, 0.0,
                            0.0, 0.0, 1.0, 0.0,
                            0.0, 0.0, 0.0, 1.0,
                        ],
                    },
                    "strength": 1.0,
                },
                timeout_seconds=10.0,
            )
            after_brush = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(brushed)
        _assert_vec3_close(self, after_brush[1], (1.0, 0.0, 0.008))

    def test_native_session_screen_radius_wvp_failure_does_not_use_legacy_fov_fallback(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-screen-radius-invalid-wvp-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_screen_radius_invalid_wvp_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"vertices_by_submesh": {0: (1,)}},
                    timeout_seconds=5.0,
                )
            )
            brushed = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "brush",
                    "tool": "inflate",
                    "screen_radius": {
                        "radius_pixels": 1.0,
                        "distance": 1.0,
                        "viewport_width": 200.0,
                        "viewport_height": 2.0,
                        "vertical_fov_degrees": 90.0,
                        "amount_scale": 0.08,
                        "world_view_projection": [0.0] * 16,
                    },
                    "strength": 1.0,
                },
                timeout_seconds=10.0,
            )
            after_brush = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(brushed)
        _assert_vec3_close(self, after_brush[1], (1.0, 0.0, 0.0))

    def test_native_session_screen_radius_uses_source_projection_override(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-screen-radius-source-wvp-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_screen_radius_source_wvp_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"vertices_by_submesh": {0: (1,)}},
                    timeout_seconds=5.0,
                )
            )
            brushed = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "brush",
                    "tool": "inflate",
                    "screen_radius": {
                        "radius_pixels": 10.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "amount_scale": 0.08,
                        "world_view_projection": [
                            0.5, 0.0, 0.0, 0.0,
                            0.0, 0.5, 0.0, 0.0,
                            0.0, 0.0, 1.0, 0.0,
                            0.0, 0.0, 0.0, 1.0,
                        ],
                        "source_submesh_world_view_projections": [
                            {"source_submesh_index": 0, "world_view_projection": _screen_wvp()},
                        ],
                    },
                    "strength": 1.0,
                },
                timeout_seconds=10.0,
            )
            after_brush = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(brushed)
        _assert_vec3_close(self, after_brush[1], (1.0, 0.0, 0.008))

    def test_native_session_screen_radius_uses_source_transform_override(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-screen-radius-source-transform-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_screen_radius_source_transform_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"vertices_by_submesh": {0: (1,)}},
                    timeout_seconds=5.0,
                )
            )
            brushed = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "brush",
                    "tool": "inflate",
                    "screen_radius": {
                        "radius_pixels": 10.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "amount_scale": 0.08,
                        "world_view_projection": [
                            0.5, 0.0, 0.0, 0.0,
                            0.0, 0.5, 0.0, 0.0,
                            0.0, 0.0, 1.0, 0.0,
                            0.0, 0.0, 0.0, 1.0,
                        ],
                        "source_submesh_world_transforms": [
                            {
                                "source_submesh_index": 0,
                                "world_transform": [
                                    2.0, 0.0, 0.0, 0.0,
                                    0.0, 2.0, 0.0, 0.0,
                                    0.0, 0.0, 1.0, 0.0,
                                    0.0, 0.0, 0.0, 1.0,
                                ],
                            },
                        ],
                    },
                    "strength": 1.0,
                },
                timeout_seconds=10.0,
            )
            after_brush = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(brushed)
        _assert_vec3_close(self, after_brush[1], (1.0, 0.0, 0.008))

    def test_native_session_pinch_derives_center_from_resident_selection_weights(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-pinch-native-center-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_pinch_native_center_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"vertices_by_submesh": {0: (0, 1)}},
                    timeout_seconds=5.0,
                )
            )
            brushed = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "brush",
                    "tool": "pinch",
                    "amount": 0.1,
                    "strength": 1.0,
                },
                timeout_seconds=10.0,
            )
            after_brush = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(brushed)
        _assert_vec3_close(self, after_brush[0], (0.1, 0.0, 0.0))
        _assert_vec3_close(self, after_brush[1], (0.9, 0.0, 0.0))

    def test_native_session_screen_radius_uses_screen_brush_center_without_legacy_center(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-screen-radius-screen-brush-center-{uuid4().hex}"
        wvp = [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            -1.0, 0.0, 0.0, 1.0,
        ]

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_screen_radius_screen_brush_center_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            brushed = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "brush",
                    "tool": "inflate",
                    "target_mode": "brush",
                    "screen_brush": {
                        "x": 100.0,
                        "y": 100.0,
                        "radius_pixels": 10.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "world_view_projection": wvp,
                    },
                    "screen_radius": {
                        "radius_pixels": 10.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "amount_scale": 0.08,
                        "world_view_projection": wvp,
                    },
                    "strength": 1.0,
                },
                timeout_seconds=10.0,
            )
            after_brush = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(brushed)
        _assert_vec3_close(self, after_brush[0], (0.0, 0.0, 0.0))
        _assert_vec3_close(self, after_brush[1], (1.0, 0.0, 0.008))
        _assert_vec3_close(self, after_brush[2], (0.0, 1.0, 0.0))

    def test_native_session_brush_resolves_d3d11_screen_brush_weights(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-brush-screen-brush-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_brush_screen_brush_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            brushed = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "brush",
                    "tool": "grab",
                    "delta": {"x": 0.0, "y": 0.0, "z": 1.0},
                    "screen_brush": {
                        "x": 100.0,
                        "y": 100.0,
                        "radius_pixels": 10.0,
                        "yaw_degrees": 0.0,
                        "pitch_degrees": 0.0,
                        "distance": 1.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "vertical_fov_degrees": 90.0,
                    },
                    "strength": 1.0,
                },
                timeout_seconds=10.0,
            )
            after_brush = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(brushed)
        _assert_vec3_close(self, after_brush[0], (0.0, 0.0, 1.0))
        _assert_vec3_close(self, after_brush[1], (1.0, 0.0, 0.0))
        _assert_vec3_close(self, after_brush[2], (0.0, 1.0, 0.0))

    def test_native_session_screen_brush_prefers_d3d11_world_view_projection(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-brush-wvp-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_brush_wvp_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            brushed = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "brush",
                    "tool": "grab",
                    "delta": {"x": 0.0, "y": 0.0, "z": 1.0},
                    "screen_brush": {
                        "x": 100.0,
                        "y": 100.0,
                        "radius_pixels": 10.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "world_view_projection": [
                            1.0, 0.0, 0.0, 0.0,
                            0.0, 1.0, 0.0, 0.0,
                            0.0, 0.0, 1.0, 0.0,
                            -1.0, 0.0, 0.0, 1.0,
                        ],
                    },
                    "strength": 1.0,
                },
                timeout_seconds=10.0,
            )
            after_brush = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(brushed)
        _assert_vec3_close(self, after_brush[0], (0.0, 0.0, 0.0))
        _assert_vec3_close(self, after_brush[1], (1.0, 0.0, 1.0))
        _assert_vec3_close(self, after_brush[2], (0.0, 1.0, 0.0))

    def test_native_session_screen_brush_invalid_source_transform_does_not_use_base_wvp(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-brush-invalid-source-transform-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_brush_invalid_source_transform_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            brushed = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "brush",
                    "tool": "grab",
                    "delta": {"x": 0.0, "y": 0.0, "z": 1.0},
                    "screen_brush": {
                        "x": 100.0,
                        "y": 100.0,
                        "radius_pixels": 10.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "world_view_projection": _screen_wvp(-1.0),
                        "source_submesh_world_transforms": [
                            {"source_submesh_index": 0, "world_transform": [1.0, 2.0]},
                        ],
                    },
                    "strength": 1.0,
                },
                timeout_seconds=10.0,
            )
            after_brush = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(brushed)
        _assert_vec3_close(self, after_brush[0], (0.0, 0.0, 0.0))
        _assert_vec3_close(self, after_brush[1], (1.0, 0.0, 0.0))
        _assert_vec3_close(self, after_brush[2], (0.0, 1.0, 0.0))

    def test_native_session_malformed_source_projection_payloads_fail_closed(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        expected = tuple(tuple(vertex) for vertex in _quad_mesh().submeshes[0].vertices)

        def apply_and_export(command: dict[str, object], selection: dict[str, object] | None = None) -> list[tuple[float, float, float]]:
            session_id = f"native-editor-malformed-source-projection-{uuid4().hex}"

            def export_vertices() -> list[tuple[float, float, float]]:
                with tempfile.TemporaryDirectory(prefix="cdmw_native_malformed_source_projection_") as temp_dir:
                    vertices_path = Path(temp_dir) / "vertices.bin"
                    report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                        session_id,
                        [{"index": 0, "vertices_output_path": str(vertices_path)}],
                        timeout_seconds=5.0,
                    )
                    self.assertIsNotNone(report)
                    raw = vertices_path.read_bytes()
                return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

            try:
                self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
                if selection is not None:
                    self.assertIsNotNone(
                        mesh_native_core.select_native_mesh_editor_session(
                            session_id,
                            selection,
                            timeout_seconds=5.0,
                        )
                    )
                result = mesh_native_core.apply_native_mesh_editor_session(session_id, command, timeout_seconds=10.0)
                self.assertIsNotNone(result)
                return export_vertices()
            finally:
                mesh_native_core.close_native_mesh_editor_session(session_id)

        after_drag = apply_and_export(
            {
                "operation": "transform",
                "screen_drag": {
                    "start_x": 0.0,
                    "start_y": 0.0,
                    "end_x": 5.0,
                    "end_y": 0.0,
                    "viewport_width": 200.0,
                    "viewport_height": 200.0,
                    "world_view_projection": _screen_wvp(),
                    "source_submesh_world_view_projections": {"bad": True},
                },
                "axis": "x",
            },
            {"vertices_by_submesh": {0: (1,)}},
        )
        after_brush = apply_and_export(
            {
                "operation": "brush",
                "tool": "grab",
                "delta": {"x": 0.0, "y": 0.0, "z": 1.0},
                "screen_brush": {
                    "x": 100.0,
                    "y": 100.0,
                    "radius_pixels": 10.0,
                    "viewport_width": 200.0,
                    "viewport_height": 200.0,
                    "world_view_projection": [
                        1.0, 0.0, 0.0, 0.0,
                        0.0, 1.0, 0.0, 0.0,
                        0.0, 0.0, 1.0, 0.0,
                        -1.0, 0.0, 0.0, 1.0,
                    ],
                    "source_submesh_world_transforms": {"bad": True},
                },
                "strength": 1.0,
            },
        )
        after_radius = apply_and_export(
            {
                "operation": "brush",
                "tool": "grab",
                "delta": {"x": 0.0, "y": 0.0, "z": 1.0},
                "screen_radius": {
                    "radius_pixels": 10.0,
                    "viewport_width": 200.0,
                    "viewport_height": 200.0,
                    "world_view_projection": _screen_wvp(),
                    "source_submesh_world_transforms": {"bad": True},
                },
                "strength": 1.0,
            },
        )

        for vertices in (after_drag, after_brush, after_radius):
            for actual, unchanged in zip(vertices, expected):
                _assert_vec3_close(self, actual, unchanged)

    def test_native_session_screen_brush_wvp_miss_does_not_use_object_radius_fallback(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-brush-wvp-miss-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_brush_wvp_miss_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            brushed = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "brush",
                    "tool": "grab",
                    "delta": {"x": 0.0, "y": 0.0, "z": 1.0},
                    "target_mode": "vertex",
                    "screen_brush": {
                        "x": 10.0,
                        "y": 10.0,
                        "radius_pixels": 4.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "world_view_projection": _screen_wvp(),
                    },
                    "strength": 1.0,
                },
                timeout_seconds=10.0,
            )
            after_brush = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(brushed)
        _assert_vec3_close(self, after_brush[0], (0.0, 0.0, 0.0))
        _assert_vec3_close(self, after_brush[1], (1.0, 0.0, 0.0))
        _assert_vec3_close(self, after_brush[2], (0.0, 1.0, 0.0))

    def test_native_session_screen_brush_uses_d3d11_camera_world_fallback(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-brush-camera-world-{uuid4().hex}"

        def export_vertices() -> list[tuple[float, float, float]]:
            with tempfile.TemporaryDirectory(prefix="cdmw_native_brush_camera_world_") as temp_dir:
                vertices_path = Path(temp_dir) / "vertices.bin"
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                self.assertIsNotNone(report)
                raw = vertices_path.read_bytes()
            return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            brushed = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {
                    "operation": "brush",
                    "tool": "grab",
                    "delta": {"x": 0.0, "y": 0.0, "z": 1.0},
                    "screen_brush": {
                        "x": 150.0,
                        "y": 100.0,
                        "radius_pixels": 5.0,
                        "yaw_degrees": 90.0,
                        "pitch_degrees": 0.0,
                        "distance": 2.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "vertical_fov_degrees": 90.0,
                        "camera_world": [
                            1.0, 0.0, 0.0, 0.0,
                            0.0, 1.0, 0.0, 0.0,
                            0.0, 0.0, 1.0, 0.0,
                            0.0, 0.0, 0.0, 1.0,
                        ],
                    },
                    "strength": 1.0,
                },
                timeout_seconds=10.0,
            )
            after_brush = export_vertices()
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(brushed)
        _assert_vec3_close(self, after_brush[0], (0.0, 0.0, 0.0))
        _assert_vec3_close(self, after_brush[1], (1.0, 0.0, 1.0))
        _assert_vec3_close(self, after_brush[2], (0.0, 1.0, 0.0))

    def test_native_session_brush_screen_brush_respects_visible_depth_mode(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        def brush_vertices(depth_mode: str) -> list[tuple[float, float, float]]:
            session_id = f"native-editor-brush-depth-{depth_mode}-{uuid4().hex}"

            def export_vertices() -> list[tuple[float, float, float]]:
                with tempfile.TemporaryDirectory(prefix="cdmw_native_brush_depth_") as temp_dir:
                    vertices_path = Path(temp_dir) / "vertices.bin"
                    report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                        session_id,
                        [{"index": 0, "vertices_output_path": str(vertices_path)}],
                        timeout_seconds=5.0,
                    )
                    self.assertIsNotNone(report)
                    raw = vertices_path.read_bytes()
                return [tuple(values) for values in struct.iter_unpack("=ddd", raw)]

            try:
                self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_overlapping_depth_mesh(), session_id, timeout_seconds=5.0))
                brushed = mesh_native_core.apply_native_mesh_editor_session(
                    session_id,
                    {
                        "operation": "brush",
                        "tool": "grab",
                        "delta": {"x": 0.0, "y": 0.0, "z": 1.0},
                        "target_mode": "vertex",
                        "selection_depth_mode": depth_mode,
                        "screen_brush": {
                            "x": 125.0,
                            "y": 75.0,
                            "radius_pixels": 2.0,
                            "viewport_width": 200.0,
                            "viewport_height": 200.0,
                            "world_view_projection": [
                                1.0, 0.0, 0.0, 0.0,
                                0.0, 1.0, 0.0, 0.0,
                                0.0, 0.0, 0.5, 0.0,
                                0.0, 0.0, 0.5, 1.0,
                            ],
                        },
                        "strength": 1.0,
                    },
                    timeout_seconds=10.0,
                )
                self.assertIsNotNone(brushed)
                return export_vertices()
            finally:
                mesh_native_core.close_native_mesh_editor_session(session_id)

        visible_vertices = brush_vertices("visible")
        xray_vertices = brush_vertices("xray")

        _assert_vec3_close(self, visible_vertices[8], (0.25, 0.25, 1.0))
        _assert_vec3_close(self, visible_vertices[9], (0.25, 0.25, 0.5))
        _assert_vec3_close(self, xray_vertices[8], (0.25, 0.25, 1.0))
        _assert_vec3_close(self, xray_vertices[9], (0.25, 0.25, 1.5))

    def test_native_session_select_resolves_d3d11_screen_brush(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        def screen_payload(x: float, y: float, radius: float = 2.0, target_mode: str | None = None) -> dict[str, object]:
            payload: dict[str, object] = {
                "screen_brush": {
                    "x": x,
                    "y": y,
                    "radius_pixels": radius,
                    "viewport_width": 200.0,
                    "viewport_height": 200.0,
                    "world_view_projection": [
                        1.0, 0.0, 0.0, 0.0,
                        0.0, 1.0, 0.0, 0.0,
                        0.0, 0.0, 0.5, 0.0,
                        0.0, 0.0, 0.5, 1.0,
                    ],
                }
            }
            if target_mode is not None:
                payload["target_mode"] = target_mode
            return payload

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id=f"native-editor-select-screen-brush-{uuid4().hex}", mode="edit")
        try:
            vertex_result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": screen_payload(200.0, 100.0),
                    },
                ),
            )
            vertex_selected = service.session_view(view.session_id).selection.vertex_map()
            edge_result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": screen_payload(150.0, 100.0, target_mode="edge"),
                    },
                ),
            )
            edge_selected = service.session_view(view.session_id).selection.edge_map()
            face_result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": screen_payload(125.0, 75.0, target_mode="face"),
                    },
                ),
            )
            face_selected = service.session_view(view.session_id).selection.face_map()
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(vertex_result.ok)
        self.assertEqual({0: {1}}, vertex_selected)
        self.assertEqual(1.0, vertex_result.metrics["editor_select_resident_operation"])
        self.assertTrue(edge_result.ok)
        self.assertEqual({0: {(0, 1)}}, edge_selected)
        self.assertEqual(1.0, edge_result.metrics["editor_select_resident_operation"])
        self.assertTrue(face_result.ok)
        self.assertEqual({0: {0}}, face_selected)
        self.assertEqual(1.0, face_result.metrics["editor_select_resident_operation"])

    def test_mesh_service_blocks_native_screen_selection_when_native_unavailable(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id=f"native-editor-select-screen-unavailable-{uuid4().hex}", mode="edit")
        try:
            with patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=False):
                result = service.apply_command(
                    view.session_id,
                    MeshEditCommand(
                        "select",
                        selection=MeshEditSelection(),
                        params={
                            "operation": "replace",
                            "_native_screen_selection_payload": {
                                "target_mode": "vertex",
                                "selection_depth_mode": "visible",
                                "screen_brush": {
                                    "x": 200.0,
                                    "y": 100.0,
                                    "radius_pixels": 2.0,
                                    "viewport_width": 200.0,
                                    "viewport_height": 200.0,
                                    "world_view_projection": _screen_wvp(),
                                },
                            },
                        },
                    ),
                )
            selected = service.session_view(view.session_id).selection.vertex_map()
        finally:
            service.close_edit_session(view.session_id)

        self.assertFalse(result.ok)
        self.assertEqual("error", result.status)
        self.assertIn("Native screen selection is unavailable", "\n".join(result.diagnostics))
        self.assertEqual({}, selected)

    def test_native_session_select_screen_brush_wvp_ignores_legacy_groups(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-select-screen-brush-legacy-groups-{uuid4().hex}"
        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            selected = mesh_native_core.select_native_mesh_editor_session(
                session_id,
                {
                    "vertices_by_submesh": {0: (1,)},
                    "screen_brush": {
                        "x": 10.0,
                        "y": 10.0,
                        "radius_pixels": 4.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "world_view_projection": _screen_wvp(),
                    },
                },
                operation="replace",
                timeout_seconds=5.0,
            )
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(selected)
        self.assertEqual({}, selected.get("selection", {}).get("vertices_by_submesh", {}))  # type: ignore[union-attr]

    def test_native_session_select_screen_brush_source_projection_does_not_fallback_other_sources(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        service = MeshService()
        view = service.open_edit_session(
            _two_part_mesh(),
            session_id=f"native-editor-select-screen-brush-source-only-{uuid4().hex}",
            mode="edit",
        )
        try:
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": {
                            "target_mode": "vertex",
                            "selection_depth_mode": "xray",
                            "screen_brush": {
                                "x": 100.0,
                                "y": 100.0,
                                "radius_pixels": 4.0,
                                "viewport_width": 200.0,
                                "viewport_height": 200.0,
                                "source_submesh_world_view_projections": [
                                    {"source_submesh_index": 0, "world_view_projection": _screen_wvp()},
                                ],
                            },
                        },
                    },
                ),
            )
            selected_vertices = service.session_view(view.session_id).selection.vertex_map()
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual({0: {0}}, selected_vertices)

    def test_native_session_select_source_brush_uses_source_only_projection_ray(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        first = SubMesh(
            name="source_triangle",
            material="mat",
            texture="a.dds",
            vertices=[
                (0.0, 1.0, 0.0),
                (-1.0, -1.0, 0.0),
                (1.0, -1.0, 0.0),
            ],
            uvs=[(0.5, 0.0), (0.0, 1.0), (1.0, 1.0)],
            normals=[(0.0, 0.0, 1.0)] * 3,
            faces=[(0, 1, 2)],
            vertex_count=3,
            face_count=1,
        )
        second = SubMesh(
            name="source_triangle_b",
            material="mat_b",
            texture="b.dds",
            vertices=list(first.vertices),
            uvs=list(first.uvs),
            normals=list(first.normals),
            faces=list(first.faces),
            vertex_count=first.vertex_count,
            face_count=first.face_count,
        )
        mesh = ParsedMesh(
            path="source_triangle_ray.pac",
            format="pac",
            submeshes=[first, second],
            total_vertices=6,
            total_faces=2,
            has_uvs=True,
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id=f"native-editor-source-ray-source-only-{uuid4().hex}", mode="edit")
        try:
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": {
                            "target_mode": "source",
                            "selection_depth_mode": "xray",
                            "screen_brush": {
                                "x": 100.0,
                                "y": 100.0,
                                "radius_pixels": 4.0,
                                "viewport_width": 200.0,
                                "viewport_height": 200.0,
                                "source_submesh_world_view_projections": [
                                    {"source_submesh_index": 0, "world_view_projection": _screen_wvp()},
                                ],
                            },
                        },
                    },
                ),
            )
            selected_sources = service.session_view(view.session_id).selection.source_indices
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual((0,), selected_sources)

    def test_native_session_select_screen_region_source_projection_ignores_legacy_groups(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-select-screen-region-source-legacy-groups-{uuid4().hex}"
        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            selected = mesh_native_core.select_native_mesh_editor_session(
                session_id,
                {
                    "vertices_by_submesh": {0: (1,)},
                    "screen_region": {
                        "mode": "rectangle",
                        "start_x": 10.0,
                        "start_y": 10.0,
                        "end_x": 14.0,
                        "end_y": 14.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "source_submesh_world_view_projections": [
                            {"source_submesh_index": 0, "world_view_projection": _screen_wvp()},
                        ],
                    },
                },
                operation="replace",
                timeout_seconds=5.0,
            )
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(selected)
        self.assertEqual({}, selected.get("selection", {}).get("vertices_by_submesh", {}))  # type: ignore[union-attr]

    def test_native_session_select_source_resolves_d3d11_screen_brush(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        mesh = _two_part_mesh()
        mesh.submeshes[1].vertices = [
            (-0.75, 0.0, 0.0),
            (-0.50, 0.0, 0.0),
            (-0.75, 0.25, 0.0),
            (-0.50, 0.25, 0.0),
        ]
        service = MeshService()
        view = service.open_edit_session(mesh, session_id=f"native-editor-select-source-brush-{uuid4().hex}", mode="edit")
        try:
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": {
                            "target_mode": "source",
                            "selection_depth_mode": "xray",
                            "screen_brush": {
                                "x": 25.0,
                                "y": 100.0,
                                "radius_pixels": 12.0,
                                "viewport_width": 200.0,
                                "viewport_height": 200.0,
                                "world_view_projection": [
                                    1.0, 0.0, 0.0, 0.0,
                                    0.0, 1.0, 0.0, 0.0,
                                    0.0, 0.0, 0.5, 0.0,
                                    0.0, 0.0, 0.5, 1.0,
                                ],
                            },
                        },
                    },
                ),
            )
            selected_sources = service.session_view(view.session_id).selection.source_indices
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual((1,), selected_sources)
        self.assertEqual(1.0, result.metrics["editor_select_resident_operation"])

    def test_native_session_select_source_brush_uses_source_projection_override(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        mesh = _quad_mesh()
        service = MeshService()
        view = service.open_edit_session(mesh, session_id=f"native-editor-select-source-brush-wvp-{uuid4().hex}", mode="edit")
        try:
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": {
                            "target_mode": "source",
                            "selection_depth_mode": "xray",
                            "screen_brush": {
                                "x": 125.0,
                                "y": 75.0,
                                "radius_pixels": 1.0,
                                "viewport_width": 200.0,
                                "viewport_height": 200.0,
                                "world_view_projection": _screen_wvp(1.0),
                                "source_submesh_world_view_projections": [
                                    {"source_submesh_index": 0, "world_view_projection": _screen_wvp()},
                                ],
                            },
                        },
                    },
                ),
            )
            selected_sources = service.session_view(view.session_id).selection.source_indices
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual((0,), selected_sources)
        self.assertEqual(1.0, result.metrics["editor_select_resident_operation"])

    def test_native_session_source_context_uses_d3d11_ray_for_face_hit(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        submesh = SubMesh(
            name="triangle",
            material="mat",
            texture="a.dds",
            vertices=[
                (-0.5, -0.5, 0.0),
                (0.5, -0.5, 0.0),
                (0.0, 0.5, 0.0),
            ],
            uvs=[(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)],
            normals=[(0.0, 0.0, 1.0)] * 3,
            faces=[(0, 1, 2)],
            vertex_count=3,
            face_count=1,
        )
        mesh = ParsedMesh(
            path="triangle.pac",
            format="pac",
            submeshes=[submesh],
            total_vertices=3,
            total_faces=1,
            has_uvs=True,
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id=f"native-editor-source-ray-{uuid4().hex}", mode="edit")
        try:
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "context",
                        "_native_screen_selection_payload": {
                            "target_mode": "source",
                            "selection_depth_mode": "xray",
                            "screen_brush": {
                                "x": 100.0,
                                "y": 100.0,
                                "radius_pixels": 1.0,
                                "viewport_width": 200.0,
                                "viewport_height": 200.0,
                                "world_view_projection": [
                                    1.0, 0.0, 0.0, 0.0,
                                    0.0, 1.0, 0.0, 0.0,
                                    0.0, 0.0, 0.5, 0.0,
                                    0.0, 0.0, 0.5, 1.0,
                                ],
                            },
                        },
                    },
                ),
            )
            selected_sources = service.session_view(view.session_id).selection.source_indices
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual((0,), selected_sources)
        self.assertEqual(1.0, result.metrics["editor_select_source_pick_count"])

    def test_native_session_select_face_uses_d3d11_ray_for_face_hit(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        submesh = SubMesh(
            name="triangle",
            material="mat",
            texture="a.dds",
            vertices=[
                (-0.5, -0.5, 0.0),
                (0.5, -0.5, 0.0),
                (0.0, 0.5, 0.0),
            ],
            uvs=[(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)],
            normals=[(0.0, 0.0, 1.0)] * 3,
            faces=[(0, 1, 2)],
            vertex_count=3,
            face_count=1,
        )
        mesh = ParsedMesh(
            path="triangle.pac",
            format="pac",
            submeshes=[submesh],
            total_vertices=3,
            total_faces=1,
            has_uvs=True,
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id=f"native-editor-face-ray-{uuid4().hex}", mode="edit")
        try:
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": {
                            "target_mode": "face",
                            "selection_depth_mode": "xray",
                            "screen_brush": {
                                "x": 100.0,
                                "y": 100.0,
                                "radius_pixels": 0.0,
                                "viewport_width": 200.0,
                                "viewport_height": 200.0,
                                "world_view_projection": [
                                    1.0, 0.0, 0.0, 0.0,
                                    0.0, 1.0, 0.0, 0.0,
                                    0.0, 0.0, 0.5, 0.0,
                                    0.0, 0.0, 0.5, 1.0,
                                ],
                            },
                        },
                    },
                ),
            )
            selected_faces = service.session_view(view.session_id).selection.face_map()
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual({0: {0}}, selected_faces)
        self.assertEqual(1.0, result.metrics["editor_select_resident_operation"])

    def test_native_session_select_edge_uses_d3d11_ray_for_edge_hit(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        submesh = SubMesh(
            name="triangle",
            material="mat",
            texture="a.dds",
            vertices=[
                (-0.5, 0.0, 0.0),
                (0.5, 0.0, 0.0),
                (0.0, 0.5, 0.0),
            ],
            uvs=[(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)],
            normals=[(0.0, 0.0, 1.0)] * 3,
            faces=[(0, 1, 2)],
            vertex_count=3,
            face_count=1,
        )
        mesh = ParsedMesh(
            path="triangle.pac",
            format="pac",
            submeshes=[submesh],
            total_vertices=3,
            total_faces=1,
            has_uvs=True,
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id=f"native-editor-edge-ray-{uuid4().hex}", mode="edit")
        try:
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": {
                            "target_mode": "edge",
                            "selection_depth_mode": "xray",
                            "screen_brush": {
                                "x": 100.0,
                                "y": 100.0,
                                "radius_pixels": 0.0,
                                "viewport_width": 200.0,
                                "viewport_height": 200.0,
                                "world_view_projection": [
                                    1.0, 0.0, 0.0, 0.0,
                                    0.0, 1.0, 0.0, 0.0,
                                    0.0, 0.0, 0.5, 0.0,
                                    0.0, 0.0, 0.5, 1.0,
                                ],
                            },
                        },
                    },
                ),
            )
            selected_edges = service.session_view(view.session_id).selection.edge_map()
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual({0: {(0, 1)}}, selected_edges)
        self.assertEqual(1.0, result.metrics["editor_select_resident_operation"])

    def test_native_session_source_context_screen_miss_preserves_selection(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id=f"native-editor-source-context-miss-{uuid4().hex}", mode="edit")
        try:
            service.apply_command(
                view.session_id,
                MeshEditCommand("select", selection=MeshEditSelection.from_maps(source_indices=(0,)), params={"operation": "replace"}),
            )
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "context",
                        "_native_screen_selection_payload": {
                            "target_mode": "source",
                            "selection_depth_mode": "xray",
                            "screen_brush": {
                                "x": 10_000.0,
                                "y": 10_000.0,
                                "radius_pixels": 1.0,
                                "viewport_width": 200.0,
                                "viewport_height": 200.0,
                                "world_view_projection": [
                                    1.0, 0.0, 0.0, 0.0,
                                    0.0, 1.0, 0.0, 0.0,
                                    0.0, 0.0, 0.5, 0.0,
                                    0.0, 0.0, 0.5, 1.0,
                                ],
                            },
                        },
                    },
                ),
            )
            selected_sources = service.session_view(view.session_id).selection.source_indices
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual((0,), selected_sources)
        self.assertEqual(0.0, result.metrics["editor_select_source_pick_count"])

    def test_native_session_delete_resolves_d3d11_screen_brush_faces(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id=f"native-editor-delete-screen-brush-{uuid4().hex}", mode="edit")
        try:
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "delete",
                    selection=MeshEditSelection(),
                    params={
                        "remove_orphans": False,
                        "recompute_normals": False,
                        "_native_screen_selection_payload": {
                            "target_mode": "face",
                            "selection_depth_mode": "xray",
                            "screen_brush": {
                                "x": 125.0,
                                "y": 75.0,
                                "radius_pixels": 2.0,
                                "viewport_width": 200.0,
                                "viewport_height": 200.0,
                                "world_view_projection": [
                                    1.0, 0.0, 0.0, 0.0,
                                    0.0, 1.0, 0.0, 0.0,
                                    0.0, 0.0, 0.5, 0.0,
                                    0.0, 0.0, 0.5, 1.0,
                                ],
                            },
                        },
                    },
                ),
            )
            after = service.session_view(view.session_id)
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(1, after.face_count)
        self.assertEqual(1.0, result.metrics["editor_select_inlined"])

    def test_native_session_delete_reuses_resident_screen_brush_selection(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        screen_payload = {
            "target_mode": "face",
            "selection_depth_mode": "xray",
            "screen_brush": {
                "x": 125.0,
                "y": 75.0,
                "radius_pixels": 2.0,
                "viewport_width": 200.0,
                "viewport_height": 200.0,
                "world_view_projection": [
                    1.0, 0.0, 0.0, 0.0,
                    0.0, 1.0, 0.0, 0.0,
                    0.0, 0.0, 0.5, 0.0,
                    0.0, 0.0, 0.5, 1.0,
                ],
            },
        }
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id=f"native-editor-delete-resident-screen-brush-{uuid4().hex}", mode="edit")
        try:
            select_result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={"operation": "replace", "_native_screen_selection_payload": screen_payload},
                ),
            )
            selected_faces = service.session_view(view.session_id).selection.face_map()
            delete_result = service.apply_command(
                view.session_id,
                MeshEditCommand("delete", params={"remove_orphans": False, "recompute_normals": False}),
            )
            after = service.session_view(view.session_id)
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(select_result.ok)
        self.assertEqual({0: {0}}, selected_faces)
        self.assertEqual(1.0, select_result.metrics["editor_select_resident_operation"])
        self.assertTrue(delete_result.ok)
        self.assertTrue(delete_result.topology_changed)
        self.assertEqual((0,), delete_result.affected_submesh_indices)
        self.assertEqual(1, after.face_count)

    def test_native_session_select_screen_brush_respects_visible_depth_mode(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        def screen_payload(x: float, y: float, target_mode: str, depth_mode: str) -> dict[str, object]:
            return {
                "target_mode": target_mode,
                "selection_depth_mode": depth_mode,
                "screen_brush": {
                    "x": x,
                    "y": y,
                    "radius_pixels": 2.0,
                    "viewport_width": 200.0,
                    "viewport_height": 200.0,
                    "world_view_projection": [
                        1.0, 0.0, 0.0, 0.0,
                        0.0, 1.0, 0.0, 0.0,
                        0.0, 0.0, 0.5, 0.0,
                        0.0, 0.0, 0.5, 1.0,
                    ],
                },
            }

        service = MeshService()
        view = service.open_edit_session(_overlapping_depth_mesh(), session_id=f"native-editor-select-depth-{uuid4().hex}", mode="edit")
        try:
            visible_vertex = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": screen_payload(125.0, 75.0, "vertex", "visible"),
                    },
                ),
            )
            visible_vertices = service.session_view(view.session_id).selection.vertex_map()
            xray_vertex = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": screen_payload(125.0, 75.0, "vertex", "xray"),
                    },
                ),
            )
            xray_vertices = service.session_view(view.session_id).selection.vertex_map()
            visible_edge = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": screen_payload(150.0, 50.0, "edge", "visible"),
                    },
                ),
            )
            visible_edges = service.session_view(view.session_id).selection.edge_map()
            xray_edge = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": screen_payload(150.0, 50.0, "edge", "xray"),
                    },
                ),
            )
            xray_edges = service.session_view(view.session_id).selection.edge_map()
            visible_face = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": screen_payload(125.0, 75.0, "face", "visible"),
                    },
                ),
            )
            visible_faces = service.session_view(view.session_id).selection.face_map()
            xray_face = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": screen_payload(125.0, 75.0, "face", "xray"),
                    },
                ),
            )
            xray_faces = service.session_view(view.session_id).selection.face_map()
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(visible_vertex.ok)
        self.assertEqual({0: {8}}, visible_vertices)
        self.assertTrue(xray_vertex.ok)
        self.assertEqual({0: {8, 9}}, xray_vertices)
        self.assertTrue(visible_edge.ok)
        self.assertEqual({0: {(1, 2)}}, visible_edges)
        self.assertTrue(xray_edge.ok)
        self.assertEqual({0: {(1, 2), (5, 6)}}, xray_edges)
        self.assertTrue(visible_face.ok)
        self.assertEqual({0: {0}}, visible_faces)
        self.assertTrue(xray_face.ok)
        self.assertEqual({0: {0, 2}}, xray_faces)

    def test_native_session_select_screen_region_respects_visible_depth_mode(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        def screen_payload(
            start_x: float,
            start_y: float,
            end_x: float,
            end_y: float,
            target_mode: str,
            depth_mode: str,
        ) -> dict[str, object]:
            return {
                "target_mode": target_mode,
                "selection_depth_mode": depth_mode,
                "screen_region": {
                    "mode": "rectangle",
                    "start_x": start_x,
                    "start_y": start_y,
                    "end_x": end_x,
                    "end_y": end_y,
                    "viewport_width": 200.0,
                    "viewport_height": 200.0,
                    "world_view_projection": [
                        1.0, 0.0, 0.0, 0.0,
                        0.0, 1.0, 0.0, 0.0,
                        0.0, 0.0, 0.5, 0.0,
                        0.0, 0.0, 0.5, 1.0,
                    ],
                },
            }

        service = MeshService()
        view = service.open_edit_session(_overlapping_depth_mesh(), session_id=f"native-editor-select-region-depth-{uuid4().hex}", mode="edit")
        try:
            visible_vertex = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": screen_payload(120.0, 70.0, 130.0, 80.0, "vertex", "visible"),
                    },
                ),
            )
            visible_vertices = service.session_view(view.session_id).selection.vertex_map()
            xray_vertex = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": screen_payload(120.0, 70.0, 130.0, 80.0, "vertex", "xray"),
                    },
                ),
            )
            xray_vertices = service.session_view(view.session_id).selection.vertex_map()
            visible_face = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": screen_payload(120.0, 60.0, 140.0, 80.0, "face", "visible"),
                    },
                ),
            )
            visible_faces = service.session_view(view.session_id).selection.face_map()
            xray_face = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": screen_payload(120.0, 60.0, 140.0, 80.0, "face", "xray"),
                    },
                ),
            )
            xray_faces = service.session_view(view.session_id).selection.face_map()
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(visible_vertex.ok)
        self.assertEqual({0: {8}}, visible_vertices)
        self.assertTrue(xray_vertex.ok)
        self.assertEqual({0: {8, 9}}, xray_vertices)
        self.assertTrue(visible_face.ok)
        self.assertEqual({0: {0}}, visible_faces)
        self.assertTrue(xray_face.ok)
        self.assertEqual({0: {0, 2}}, xray_faces)

    def test_native_session_select_source_resolves_d3d11_screen_region(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        first = _quad_mesh().submeshes[0]
        second = SubMesh(
            name="quad_shifted",
            material="mat",
            texture="b.dds",
            vertices=[(x + 2.0, y, z) for x, y, z in first.vertices],
            uvs=list(first.uvs),
            normals=list(first.normals),
            faces=list(first.faces),
            vertex_count=first.vertex_count,
            face_count=first.face_count,
        )
        mesh = ParsedMesh(
            path="two_source_region.pac",
            format="pac",
            submeshes=[first, second],
            total_vertices=8,
            total_faces=4,
            has_uvs=True,
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id=f"native-editor-select-source-region-{uuid4().hex}", mode="edit")
        try:
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": {
                            "target_mode": "source",
                            "selection_depth_mode": "xray",
                            "screen_region": {
                                "mode": "rectangle",
                                "start_x": 95.0,
                                "start_y": 95.0,
                                "end_x": 105.0,
                                "end_y": 105.0,
                                "viewport_width": 200.0,
                                "viewport_height": 200.0,
                                "world_view_projection": [
                                    1.0, 0.0, 0.0, 0.0,
                                    0.0, 1.0, 0.0, 0.0,
                                    0.0, 0.0, 0.5, 0.0,
                                    0.0, 0.0, 0.5, 1.0,
                                ],
                            },
                        },
                    },
                ),
            )
            selected_sources = service.session_view(view.session_id).selection.source_indices
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual((0,), selected_sources)

    def test_native_session_select_face_region_uses_source_projection_override(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        mesh = _quad_mesh()
        service = MeshService()
        view = service.open_edit_session(mesh, session_id=f"native-editor-select-face-region-wvp-{uuid4().hex}", mode="edit")
        try:
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": {
                            "target_mode": "face",
                            "selection_depth_mode": "xray",
                            "screen_region": {
                                "mode": "rectangle",
                                "start_x": 120.0,
                                "start_y": 70.0,
                                "end_x": 130.0,
                                "end_y": 80.0,
                                "viewport_width": 200.0,
                                "viewport_height": 200.0,
                                "world_view_projection": _screen_wvp(1.0),
                                "source_submesh_world_view_projections": [
                                    {"source_submesh_index": 0, "world_view_projection": _screen_wvp()},
                                ],
                            },
                        },
                    },
                ),
            )
            selected_faces = service.session_view(view.session_id).selection.face_map()
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual({0: {0}}, selected_faces)

    def test_native_session_select_edge_region_hits_projected_segment(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        submesh = SubMesh(
            name="edge_region",
            material="mat",
            texture="a.dds",
            vertices=[
                (-0.5, 0.0, 0.0),
                (0.5, 0.0, 0.0),
                (0.0, 0.5, 0.0),
            ],
            uvs=[(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)],
            normals=[(0.0, 0.0, 1.0)] * 3,
            faces=[(0, 1, 2)],
            vertex_count=3,
            face_count=1,
        )
        mesh = ParsedMesh(path="edge_region.pac", format="pac", submeshes=[submesh], total_vertices=3, total_faces=1, has_uvs=True)
        service = MeshService()
        view = service.open_edit_session(mesh, session_id=f"native-editor-select-edge-region-{uuid4().hex}", mode="edit")
        try:
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": {
                            "target_mode": "edge",
                            "selection_depth_mode": "xray",
                            "screen_region": {
                                "mode": "rectangle",
                                "start_x": 95.0,
                                "start_y": 95.0,
                                "end_x": 105.0,
                                "end_y": 105.0,
                                "viewport_width": 200.0,
                                "viewport_height": 200.0,
                                "world_view_projection": [
                                    1.0, 0.0, 0.0, 0.0,
                                    0.0, 1.0, 0.0, 0.0,
                                    0.0, 0.0, 0.5, 0.0,
                                    0.0, 0.0, 0.5, 1.0,
                                ],
                            },
                        },
                    },
                ),
            )
            selected_edges = service.session_view(view.session_id).selection.edge_map()
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual({0: {(0, 1)}}, selected_edges)

    def test_native_session_select_face_region_hits_projected_triangle(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        submesh = SubMesh(
            name="face_region",
            material="mat",
            texture="a.dds",
            vertices=[
                (0.0, 1.0, 0.0),
                (-1.0, -1.0, 0.0),
                (1.0, -1.0, 0.0),
            ],
            uvs=[(0.5, 0.0), (0.0, 1.0), (1.0, 1.0)],
            normals=[(0.0, 0.0, 1.0)] * 3,
            faces=[(0, 1, 2)],
            vertex_count=3,
            face_count=1,
        )
        mesh = ParsedMesh(path="face_region.pac", format="pac", submeshes=[submesh], total_vertices=3, total_faces=1, has_uvs=True)
        payload = {
            "selection_depth_mode": "xray",
            "screen_region": {
                "mode": "rectangle",
                "start_x": 95.0,
                "start_y": 95.0,
                "end_x": 105.0,
                "end_y": 105.0,
                "viewport_width": 200.0,
                "viewport_height": 200.0,
                "world_view_projection": [
                    1.0, 0.0, 0.0, 0.0,
                    0.0, 1.0, 0.0, 0.0,
                    0.0, 0.0, 0.5, 0.0,
                    0.0, 0.0, 0.5, 1.0,
                ],
            },
        }
        service = MeshService()
        view = service.open_edit_session(mesh, session_id=f"native-editor-select-face-region-{uuid4().hex}", mode="edit")
        try:
            face_result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": dict(payload, target_mode="face"),
                    },
                ),
            )
            selected_faces = service.session_view(view.session_id).selection.face_map()
            source_result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": dict(payload, target_mode="source"),
                    },
                ),
            )
            selected_sources = service.session_view(view.session_id).selection.source_indices
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(face_result.ok)
        self.assertEqual({0: {0}}, selected_faces)
        self.assertTrue(source_result.ok)
        self.assertEqual((0,), selected_sources)

    def test_native_session_select_edge_region_depth_uses_projected_hit(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        submesh = SubMesh(
            name="edge_region_depth",
            material="mat",
            texture="a.dds",
            vertices=[
                (-0.8, 0.0, 0.5),
                (0.8, 0.0, 0.5),
                (0.0, 0.8, 0.5),
                (-0.2, -0.2, 0.0),
                (0.2, -0.2, 0.0),
                (0.0, 0.2, 0.0),
            ],
            uvs=[(0.0, 0.0)] * 6,
            normals=[(0.0, 0.0, 1.0)] * 6,
            faces=[(0, 1, 2), (3, 4, 5)],
            vertex_count=6,
            face_count=2,
        )
        mesh = ParsedMesh(
            path="edge_region_depth.pac",
            format="pac",
            submeshes=[submesh],
            total_vertices=6,
            total_faces=2,
            has_uvs=True,
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id=f"native-editor-select-edge-region-depth-{uuid4().hex}", mode="edit")
        try:
            result = service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "select",
                    selection=MeshEditSelection(),
                    params={
                        "operation": "replace",
                        "_native_screen_selection_payload": {
                            "target_mode": "edge",
                            "selection_depth_mode": "visible",
                            "screen_region": {
                                "mode": "rectangle",
                                "start_x": 35.0,
                                "start_y": 95.0,
                                "end_x": 45.0,
                                "end_y": 105.0,
                                "viewport_width": 200.0,
                                "viewport_height": 200.0,
                                "world_view_projection": [
                                    1.0, 0.0, 0.0, 0.0,
                                    0.0, 1.0, 0.0, 0.0,
                                    0.0, 0.0, 0.5, 0.0,
                                    0.0, 0.0, 0.5, 1.0,
                                ],
                            },
                        },
                    },
                ),
            )
            selected_edges = service.session_view(view.session_id).selection.edge_map()
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual({0: {(0, 1)}}, selected_edges)

    def test_native_session_brush_update_screen_brush_overrides_stale_selection_weights(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-brush-screen-brush-update-{uuid4().hex}"

        with tempfile.TemporaryDirectory(prefix="cdmw_native_brush_screen_brush_update_") as temp_dir:
            temp_path = Path(temp_dir)
            indices_path = temp_path / "stroke_vertices.bin"
            weights_path = temp_path / "stroke_weights.bin"
            vertices_path = temp_path / "vertices.bin"
            indices_path.write_bytes(struct.pack("=i", 1))
            weights_path.write_bytes(struct.pack("=f", 1.0))
            selection = {
                "vertices_by_submesh": (
                    {
                        "index": 0,
                        "indices_binary": {
                            "path": str(indices_path),
                            "count": 1,
                            "components": 1,
                            "type": "i32",
                        },
                        "weights_binary": {
                            "path": str(weights_path),
                            "count": 1,
                            "components": 1,
                            "type": "f32",
                        },
                    },
                )
            }
            try:
                self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
                begin = mesh_native_core.apply_native_mesh_editor_session(
                    session_id,
                    {
                        "operation": "brush",
                        "tool": "grab",
                        "center": {"x": 1.0, "y": 0.0, "z": 0.0},
                        "delta": {"x": 0.0, "y": 0.0, "z": 1.0},
                        "radius": 0.1,
                        "strength": 1.0,
                    },
                    selection=selection,
                    stroke_phase="begin",
                    stroke_id="brush-screen-update",
                    timeout_seconds=10.0,
                )
                update = mesh_native_core.apply_native_mesh_editor_session(
                    session_id,
                    {
                        "operation": "brush",
                        "tool": "grab",
                        "delta": {"x": 0.0, "y": 0.0, "z": 1.0},
                        "screen_brush": {
                            "x": 100.0,
                            "y": 100.0,
                            "radius_pixels": 10.0,
                            "yaw_degrees": 0.0,
                            "pitch_degrees": 0.0,
                            "distance": 1.0,
                            "viewport_width": 200.0,
                            "viewport_height": 200.0,
                            "vertical_fov_degrees": 90.0,
                        },
                        "strength": 1.0,
                    },
                    stroke_phase="update",
                    stroke_id="brush-screen-update",
                    timeout_seconds=10.0,
                )
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                raw = vertices_path.read_bytes()
            finally:
                mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(begin)
        self.assertIsNotNone(update)
        self.assertIsNotNone(report)
        after_brush = [tuple(values) for values in struct.iter_unpack("=ddd", raw)]
        _assert_vec3_close(self, after_brush[0], (0.0, 0.0, 1.0))
        _assert_vec3_close(self, after_brush[1], (1.0, 0.0, 1.0))

    def test_native_session_brush_uses_d3d11_selection_weight_descriptor(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-brush-weights-{uuid4().hex}"

        with tempfile.TemporaryDirectory(prefix="cdmw_native_brush_weights_") as temp_dir:
            temp_path = Path(temp_dir)
            indices_path = temp_path / "stroke_vertices.bin"
            weights_path = temp_path / "stroke_weights.bin"
            vertices_path = temp_path / "vertices.bin"
            indices_path.write_bytes(struct.pack("=ii", 0, 1))
            weights_path.write_bytes(struct.pack("=ff", 0.25, 1.0))

            try:
                self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
                self.assertIsNotNone(
                    mesh_native_core.select_native_mesh_editor_session(
                        session_id,
                        {
                            "vertices_by_submesh": (
                                {
                                    "index": 0,
                                    "indices_binary": {
                                        "path": str(indices_path),
                                        "count": 2,
                                        "components": 1,
                                        "type": "i32",
                                    },
                                    "weights_binary": {
                                        "path": str(weights_path),
                                        "count": 2,
                                        "components": 1,
                                        "type": "f32",
                                    },
                                },
                            )
                        },
                        timeout_seconds=5.0,
                    )
                )
                brushed = mesh_native_core.apply_native_mesh_editor_session(
                    session_id,
                    {
                        "operation": "brush",
                        "tool": "grab",
                        "center": {"x": 1.0, "y": 0.0, "z": 0.0},
                        "delta": {"x": 0.0, "y": 0.0, "z": 1.0},
                        "radius": 0.1,
                        "strength": 1.0,
                    },
                    timeout_seconds=10.0,
                )
                report = mesh_native_core.export_native_mesh_editor_session_snapshot(
                    session_id,
                    [{"index": 0, "vertices_output_path": str(vertices_path)}],
                    timeout_seconds=5.0,
                )
                raw = vertices_path.read_bytes()
            finally:
                mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(brushed)
        self.assertIsNotNone(report)
        after_brush = [tuple(values) for values in struct.iter_unpack("=ddd", raw)]
        _assert_vec3_close(self, after_brush[0], (0.0, 0.0, 0.25))
        _assert_vec3_close(self, after_brush[1], (1.0, 0.0, 1.0))

    def test_mesh_service_live_stroke_reaches_native_session_as_one_undo_step(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.modding import mesh_native_core
        from cdmw.services.mesh_service import MeshService

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id=f"native-editor-service-stroke-{uuid4().hex}", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (1,)})
        stroke_id = f"stroke-{uuid4().hex}"
        mesh_native_core.clear_native_mesh_core_fallback_counts()
        try:
            with patch(
                "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                side_effect=AssertionError("live stroke must use resident native editor session"),
            ):
                begin = service.apply_command(
                    view.session_id,
                    MeshEditCommand(
                        "transform",
                        selection=selection,
                        params={"translate": (0.0, 0.0, 0.1), "stroke_phase": "begin", "stroke_id": stroke_id},
                    ),
                )
                update = service.apply_command(
                    view.session_id,
                    MeshEditCommand(
                        "transform",
                        selection=selection,
                        params={"translate": (0.0, 0.0, 0.2), "stroke_phase": "update", "stroke_id": stroke_id},
                    ),
                )
                finish = service.apply_command(
                    view.session_id,
                    MeshEditCommand(
                        "transform",
                        selection=selection,
                        params={"translate": (0.0, 0.0, 0.3), "stroke_phase": "end", "stroke_id": stroke_id},
                    ),
                )
                after_stroke = service.working_mesh(view.session_id).submeshes[0].vertices[1]
                after_view = service.session_view(view.session_id)
                undo = service.undo(view.session_id)
                after_undo = service.working_mesh(view.session_id).submeshes[0].vertices[1]
                undo_view = service.session_view(view.session_id)
                redo = service.redo(view.session_id)
                after_redo = service.working_mesh(view.session_id).submeshes[0].vertices[1]
                redo_view = service.session_view(view.session_id)
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(begin.ok)
        self.assertEqual(0.0, begin.metrics["native_stroke_history_coalesced"])
        self.assertEqual(0.0, begin.metrics["editor_select_reused"])
        self.assertTrue(update.ok)
        self.assertEqual(1.0, update.metrics["native_stroke_history_coalesced"])
        self.assertEqual(1.0, update.metrics["editor_select_reused"])
        self.assertEqual(0.0, update.metrics["editor_select_roundtrip_ms"])
        self.assertTrue(finish.ok)
        self.assertEqual(1.0, finish.metrics["native_stroke_history_coalesced"])
        self.assertEqual(0.0, finish.metrics["native_stroke_active"])
        self.assertEqual(1.0, finish.metrics["editor_select_reused"])
        self.assertEqual(0.0, finish.metrics["editor_select_roundtrip_ms"])
        _assert_vec3_close(self, after_stroke, (1.0, 0.0, 0.6))
        self.assertEqual(1, after_view.undo_count)
        self.assertEqual(0, after_view.redo_count)
        self.assertTrue(undo.ok)
        _assert_vec3_close(self, after_undo, (1.0, 0.0, 0.0))
        self.assertEqual(0, undo_view.undo_count)
        self.assertEqual(1, undo_view.redo_count)
        self.assertTrue(redo.ok)
        _assert_vec3_close(self, after_redo, (1.0, 0.0, 0.6))
        self.assertEqual(1, redo_view.undo_count)
        self.assertEqual(0, redo_view.redo_count)
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_mesh_service_live_stroke_cancel_restores_native_and_service_history(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.modding import mesh_native_core
        from cdmw.services.mesh_service import MeshService

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id=f"native-editor-service-cancel-{uuid4().hex}", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (1,)})
        stroke_id = f"stroke-{uuid4().hex}"
        try:
            service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "transform",
                    selection=selection,
                    params={"translate": (0.0, 0.0, 0.1), "stroke_phase": "begin", "stroke_id": stroke_id},
                ),
            )
            service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "transform",
                    selection=selection,
                    params={"translate": (0.0, 0.0, 0.2), "stroke_phase": "update", "stroke_id": stroke_id},
                ),
            )
            cancel = service.apply_command(
                view.session_id,
                MeshEditCommand("transform", selection=selection, params={"stroke_phase": "cancel", "stroke_id": stroke_id}),
            )
            after_cancel = service.working_mesh(view.session_id).submeshes[0].vertices[1]
            cancel_view = service.session_view(view.session_id)
            undo = service.undo(view.session_id)
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(cancel.ok)
        self.assertEqual(1.0, cancel.metrics["native_stroke_history_cancelled"])
        _assert_vec3_close(self, after_cancel, (1.0, 0.0, 0.0))
        self.assertEqual(0, cancel_view.undo_count)
        self.assertEqual(0, cancel_view.redo_count)
        self.assertEqual("noop", undo.status)

    def test_mesh_service_live_stroke_uses_native_candidate_selection_payload(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand
        from cdmw.services.mesh_service import MeshService

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id=f"native-editor-candidates-{uuid4().hex}", mode="sculpt")
        native_selection = {
            "vertices_by_submesh": (
                {
                    "index": 0,
                    "indices_binary": {"path": "stroke_vertices.bin", "count": 1, "components": 1, "type": "i32"},
                },
            )
        }
        stroke_id = f"stroke-{uuid4().hex}"
        applied_selections: list[object] = []

        def fake_apply(_session_id: str, _edit: dict[str, object], **kwargs: object) -> dict[str, object]:
            applied_selections.append(kwargs.get("selection"))
            phase = str(kwargs.get("stroke_phase") or "")
            return {
                "status": "ok",
                "metrics": {"cpp_ms": 0.1},
                "topology_changed": False,
                "submesh_count": 1,
                "submeshes": [{"index": 0, "vertex_count": 4, "face_count": 2}],
                "edit_report": {"submeshes": [{"index": 0, "vertex_count": 4, "face_count": 2}]},
                "stroke": {"phase": phase, "stroke_id": kwargs.get("stroke_id", ""), "active": phase != "end"},
            }

        try:
            with (
                patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
                patch("cdmw.services.mesh_service.open_native_mesh_editor_session", return_value={"status": "ok", "metrics": {}}),
                patch("cdmw.services.mesh_service.select_native_mesh_editor_session", side_effect=AssertionError("edit apply should inline native selection")),
                patch("cdmw.services.mesh_service._native_editor_selection_payload", side_effect=AssertionError("stroke finish should reuse resident native selection")),
                patch("cdmw.services.mesh_service.apply_native_mesh_editor_session", side_effect=fake_apply),
                patch(
                    "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                    side_effect=AssertionError("candidate stroke must use resident native editor session"),
                ),
            ):
                begin = service.apply_command(
                    view.session_id,
                    MeshEditCommand(
                        "brush",
                        params={
                            "tool": "grab",
                            "stroke_phase": "begin",
                            "stroke_id": stroke_id,
                            "_native_selection_payload": native_selection,
                        },
                        mode="sculpt",
                    ),
                )
                update = service.apply_command(
                    view.session_id,
                    MeshEditCommand(
                        "brush",
                        params={
                            "tool": "grab",
                            "stroke_phase": "update",
                            "stroke_id": stroke_id,
                        },
                        mode="sculpt",
                    ),
                )
                finish = service.apply_command(
                    view.session_id,
                    MeshEditCommand("brush", params={"tool": "grab", "stroke_phase": "end", "stroke_id": stroke_id}, mode="sculpt"),
                )
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(begin.ok)
        self.assertTrue(update.ok)
        self.assertTrue(finish.ok)
        self.assertEqual([native_selection, None, None], applied_selections)
        self.assertEqual(0.0, begin.metrics["editor_select_reused"])
        self.assertEqual(1.0, begin.metrics["editor_select_inlined"])
        self.assertEqual(1.0, update.metrics["editor_select_reused"])
        self.assertEqual(1.0, finish.metrics["editor_select_reused"])
        self.assertEqual(0.0, update.metrics["editor_select_roundtrip_ms"])
        self.assertEqual(0.0, finish.metrics["editor_select_roundtrip_ms"])

    def test_mesh_service_live_stroke_begin_reuses_resident_selection_without_payload(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import (
            MeshService,
            _mesh_edit_selection_signature,
            _native_editor_mesh_storage_signature,
        )

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id=f"native-editor-resident-begin-{uuid4().hex}", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (1,)})
        session = service._session(view.session_id)
        session.selection = selection
        session.native_editor_session_ready = True
        session.native_editor_selection_signature = _mesh_edit_selection_signature(selection)
        session.native_editor_mesh_signature = _native_editor_mesh_storage_signature(session.working_mesh)
        applied_selections: list[object] = []
        stroke_id = f"stroke-{uuid4().hex}"

        def fake_apply(_session_id: str, _edit: dict[str, object], **kwargs: object) -> dict[str, object]:
            applied_selections.append(kwargs.get("selection"))
            return {
                "status": "ok",
                "metrics": {"cpp_ms": 0.1},
                "topology_changed": False,
                "submesh_count": 1,
                "submeshes": [{"index": 0, "vertex_count": 4, "face_count": 2}],
                "edit_report": {"submeshes": [{"index": 0, "vertex_count": 4, "face_count": 2}]},
                "stroke": {"phase": "begin", "stroke_id": kwargs.get("stroke_id", ""), "active": True},
            }

        try:
            with (
                patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
                patch("cdmw.services.mesh_service.open_native_mesh_editor_session", side_effect=AssertionError("resident begin should not reopen native session")),
                patch("cdmw.services.mesh_service.select_native_mesh_editor_session", side_effect=AssertionError("resident begin should not issue a select roundtrip")),
                patch("cdmw.services.mesh_service._native_editor_selection_payload", side_effect=AssertionError("resident begin should not build a Python selection payload")),
                patch("cdmw.services.mesh_service.apply_native_mesh_editor_session", side_effect=fake_apply),
                patch(
                    "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                    side_effect=AssertionError("resident begin must use native editor session"),
                ),
            ):
                result = service.apply_command(
                    view.session_id,
                    MeshEditCommand(
                        "transform",
                        params={"translate": (0.0, 0.0, 0.1), "stroke_phase": "begin", "stroke_id": stroke_id},
                        mode="edit",
                    ),
                )
        finally:
            session.native_editor_session_ready = False
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual([None], applied_selections)
        self.assertEqual(1.0, result.metrics["editor_select_reused"])
        self.assertEqual(0.0, result.metrics["editor_select_inlined"])
        self.assertEqual(0.0, result.metrics["editor_select_roundtrip_ms"])

    def test_mesh_service_preserves_d3d11_object_delta_for_native_transform(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id=f"native-editor-object-delta-service-{uuid4().hex}", mode="edit")
        captured_edits: list[dict[str, object]] = []

        def fake_apply(_session_id: str, edit: dict[str, object], **kwargs: object) -> dict[str, object]:
            captured_edits.append(edit)
            phase = str(kwargs.get("stroke_phase") or "")
            return {
                "status": "ok",
                "metrics": {"cpp_ms": 0.1},
                "topology_changed": False,
                "submesh_count": 1,
                "submeshes": [{"index": 0, "vertex_count": 4, "face_count": 2}],
                "edit_report": {"submeshes": [{"index": 0, "vertex_count": 4, "face_count": 2}]},
                "stroke": {"phase": phase, "stroke_id": kwargs.get("stroke_id", ""), "active": phase != "end"},
            }

        try:
            with (
                patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
                patch("cdmw.services.mesh_service.open_native_mesh_editor_session", return_value={"status": "ok", "metrics": {}}),
                patch("cdmw.services.mesh_service.select_native_mesh_editor_session", return_value={"status": "ok", "metrics": {}}),
                patch("cdmw.services.mesh_service.apply_native_mesh_editor_session", side_effect=fake_apply),
                patch(
                    "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                    side_effect=AssertionError("D3D11 object delta must use resident native editor session"),
                ),
            ):
                result = service.apply_command(
                    view.session_id,
                    MeshEditCommand(
                        "transform",
                        selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (1,)}),
                        params={"translate": {"x": 0.25, "y": 0.0, "z": 0.5}, "stroke_phase": "begin", "stroke_id": "move-1"},
                    ),
                )
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual({"x": 0.25, "y": 0.0, "z": 0.5}, captured_edits[0]["translate"])

    def test_mesh_service_preserves_d3d11_object_vectors_for_native_brush(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id=f"native-editor-brush-object-service-{uuid4().hex}", mode="sculpt")
        captured_edits: list[dict[str, object]] = []

        def fake_apply(_session_id: str, edit: dict[str, object], **kwargs: object) -> dict[str, object]:
            captured_edits.append(edit)
            phase = str(kwargs.get("stroke_phase") or "")
            return {
                "status": "ok",
                "metrics": {"cpp_ms": 0.1},
                "topology_changed": False,
                "submesh_count": 1,
                "submeshes": [{"index": 0, "vertex_count": 4, "face_count": 2}],
                "edit_report": {"submeshes": [{"index": 0, "vertex_count": 4, "face_count": 2}]},
                "stroke": {"phase": phase, "stroke_id": kwargs.get("stroke_id", ""), "active": phase != "end"},
            }

        try:
            with (
                patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
                patch("cdmw.services.mesh_service.open_native_mesh_editor_session", return_value={"status": "ok", "metrics": {}}),
                patch("cdmw.services.mesh_service.select_native_mesh_editor_session", return_value={"status": "ok", "metrics": {}}),
                patch("cdmw.services.mesh_service.apply_native_mesh_editor_session", side_effect=fake_apply),
                patch(
                    "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                    side_effect=AssertionError("D3D11 brush vectors must use resident native editor session"),
                ),
            ):
                result = service.apply_command(
                    view.session_id,
                    MeshEditCommand(
                        "brush",
                        selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (1,)}),
                        params={
                            "tool": "grab",
                            "center": {"x": 1.0, "y": 0.0, "z": 0.0},
                            "delta": {"x": 0.0, "y": 0.0, "z": 0.5},
                            "amount": 0.5,
                            "screen_brush": {
                                "x": 100.0,
                                "y": 100.0,
                                "radius_pixels": 10.0,
                                "viewport_width": 200.0,
                                "viewport_height": 200.0,
                            },
                            "stroke_phase": "begin",
                            "stroke_id": "brush-1",
                        },
                        mode="sculpt",
                    ),
                )
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual({"x": 1.0, "y": 0.0, "z": 0.0}, captured_edits[0]["center"])
        self.assertEqual({"x": 0.0, "y": 0.0, "z": 0.5}, captured_edits[0]["delta"])
        self.assertEqual(0.5, captured_edits[0]["amount"])
        self.assertEqual(100.0, captured_edits[0]["screen_brush"]["x"])

    def test_mesh_service_suppresses_resident_topology_remap_report(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id=f"native-editor-topology-report-service-{uuid4().hex}", mode="edit")
        captured_edits: list[dict[str, object]] = []

        def fake_apply(_session_id: str, edit: dict[str, object], **_kwargs: object) -> dict[str, object]:
            captured_edits.append(edit)
            return {
                "status": "ok",
                "metrics": {"cpp_ms": 0.1, "io_serialization_ms": 0.1},
                "topology_changed": True,
                "submesh_count": 1,
                "submeshes": [{"index": 0, "vertex_count": 5, "face_count": 4}],
                "edit_report": {"submeshes": [{"index": 0, "vertex_count": 5, "face_count": 4}]},
            }

        try:
            with (
                patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
                patch("cdmw.services.mesh_service.open_native_mesh_editor_session", return_value={"status": "ok", "metrics": {}}),
                patch("cdmw.services.mesh_service.select_native_mesh_editor_session", return_value={"status": "ok", "metrics": {}}),
                patch("cdmw.services.mesh_service.apply_native_mesh_editor_session", side_effect=fake_apply),
                patch(
                    "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                    side_effect=AssertionError("topology tools must use resident native editor session"),
                ),
            ):
                result = service.apply_command(
                    view.session_id,
                    MeshEditCommand(
                        "subdivide",
                        selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                        mode="edit",
                    ),
                )
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual("subdivide", captured_edits[0]["operation"])
        self.assertIs(captured_edits[0]["suppress_vertex_remap_report"], True)

    def test_mesh_service_forwards_transform_screen_drag_to_native(self) -> None:
        from cdmw.services.mesh_service import _native_editor_transform_payload

        payload = _native_editor_transform_payload(
            {
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
                "axis": "x",
            }
        )

        self.assertEqual((0.0, 0.0, 0.0), payload["translate"])
        self.assertEqual("x", payload["axis"])
        self.assertEqual(5.0, payload["screen_drag"]["end_x"])

    def test_mesh_service_uses_screen_selection_payload_for_transform_apply(self) -> None:
        from cdmw.domain.mesh import MeshEditSelection
        from cdmw.services.mesh_service import _native_editor_selection_payload_for_apply

        payload = _native_editor_selection_payload_for_apply(
            MeshEditSelection.from_maps(vertices_by_submesh={0: (99,)}),
            {
                "_native_screen_selection_payload": {
                    "target_mode": "vertex",
                    "selection_depth_mode": "visible",
                    "falloff": "smooth",
                    "screen_brush": {
                        "x": 100.0,
                        "y": 80.0,
                        "radius_pixels": 24.0,
                        "viewport_width": 200.0,
                        "viewport_height": 160.0,
                    },
                }
            },
        )

        self.assertNotIn("vertices_by_submesh", payload)
        self.assertEqual("vertex", payload["target_mode"])
        self.assertEqual("visible", payload["selection_depth_mode"])
        self.assertEqual(100.0, payload["screen_brush"]["x"])

    def test_mesh_service_transform_uses_resident_native_editor_session_history(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.modding import mesh_native_core
        from cdmw.services.mesh_service import MeshService

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id=f"native-editor-transform-{uuid4().hex}", mode="edit")
        mesh_native_core.clear_native_mesh_core_fallback_counts()
        try:
            with patch(
                "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                side_effect=AssertionError("transform must use resident native editor session"),
            ):
                result = service.apply_command(
                    view.session_id,
                    MeshEditCommand(
                        "transform",
                        selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (1,)}),
                        params={
                            "translate": (0.0, 0.0, 0.5),
                            "scale": (2.0, 1.0, 1.0),
                            "rotate": (0.0, 0.0, 90.0),
                            "pivot": (0.0, 0.0, 0.0),
                        },
                    ),
                )
                after_apply = service.working_mesh(view.session_id).submeshes[0].vertices[1]
                undo = service.undo(view.session_id)
                after_undo = service.working_mesh(view.session_id).submeshes[0].vertices[1]
                redo = service.redo(view.session_id)
                after_redo = service.working_mesh(view.session_id).submeshes[0].vertices[1]
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(((0, range(1, 2)),), result.changed_vertices_by_submesh)
        self.assertGreaterEqual(result.metrics["cpp_ms"], 0.0)
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())
        _assert_vec3_close(self, after_apply, (0.0, 2.0, 0.5))
        self.assertTrue(undo.ok)
        self.assertEqual(((0, range(1, 2)),), undo.changed_vertices_by_submesh)
        _assert_vec3_close(self, after_undo, (1.0, 0.0, 0.0))
        self.assertTrue(redo.ok)
        self.assertEqual(((0, range(1, 2)),), redo.changed_vertices_by_submesh)
        _assert_vec3_close(self, after_redo, (0.0, 2.0, 0.5))

    def test_mesh_service_recalculate_normals_uses_resident_native_editor_session_history(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.modding import mesh_native_core
        from cdmw.services.mesh_service import MeshService

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id=f"native-editor-normal-{uuid4().hex}", mode="edit")
        service.working_mesh(view.session_id).submeshes[0].normals = [(0.0, 0.0, -1.0)] * 4
        mesh_native_core.clear_native_mesh_core_fallback_counts()
        try:
            with (
                patch(
                    "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                    side_effect=AssertionError("recalculate_normals must use resident native editor session"),
                ),
                patch(
                    "cdmw.services.mesh_service.apply_native_mesh_recalculate_normals",
                    side_effect=AssertionError("recalculate_normals must not use old one-shot native path"),
                ),
            ):
                result = service.apply_command(
                    view.session_id,
                    MeshEditCommand("recalculate_normals", selection=MeshEditSelection.from_maps(source_indices=(0,))),
                )
                after_apply = tuple(service.working_mesh(view.session_id).submeshes[0].normals)
                undo = service.undo(view.session_id)
                after_undo = tuple(service.working_mesh(view.session_id).submeshes[0].normals)
                redo = service.redo(view.session_id)
                after_redo = tuple(service.working_mesh(view.session_id).submeshes[0].normals)
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(((0, range(0, 4)),), result.changed_vertices_by_submesh)
        self.assertGreaterEqual(result.metrics["cpp_ms"], 0.0)
        self.assertEqual([(0.0, 0.0, 1.0)] * 4, list(after_apply))
        self.assertTrue(undo.ok)
        self.assertEqual(((0, range(0, 4)),), undo.changed_vertices_by_submesh)
        self.assertEqual([(0.0, 0.0, -1.0)] * 4, list(after_undo))
        self.assertTrue(redo.ok)
        self.assertEqual(((0, range(0, 4)),), redo.changed_vertices_by_submesh)
        self.assertEqual([(0.0, 0.0, 1.0)] * 4, list(after_redo))
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_mesh_service_generate_tangents_uses_resident_native_editor_session_history(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.modding import mesh_native_core
        from cdmw.services.mesh_service import MeshService

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id=f"native-editor-tangents-{uuid4().hex}", mode="edit")
        submesh = service.working_mesh(view.session_id).submeshes[0]
        submesh.tangents = []
        if hasattr(submesh, "tangent_signs"):
            submesh.tangent_signs = []
        mesh_native_core.clear_native_mesh_core_fallback_counts()
        try:
            with patch(
                "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                side_effect=AssertionError("generate_tangents must use resident native editor session"),
            ):
                result = service.apply_command(
                    view.session_id,
                    MeshEditCommand("generate_tangents", selection=MeshEditSelection.from_maps(source_indices=(0,))),
                )
                after_apply = tuple(service.working_mesh(view.session_id).submeshes[0].tangents)
                undo = service.undo(view.session_id)
                after_undo = tuple(service.working_mesh(view.session_id).submeshes[0].tangents)
                redo = service.redo(view.session_id)
                after_redo = tuple(service.working_mesh(view.session_id).submeshes[0].tangents)
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(4, len(after_apply))
        _assert_vec3_close(self, after_apply[0], (1.0, 0.0, 0.0))
        self.assertTrue(undo.ok)
        self.assertEqual((), after_undo)
        self.assertTrue(redo.ok)
        self.assertEqual(4, len(after_redo))
        _assert_vec3_close(self, after_redo[0], (1.0, 0.0, 0.0))
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_mesh_service_uv_transform_uses_resident_native_editor_session_history(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.modding import mesh_native_core
        from cdmw.services.mesh_service import MeshService

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id=f"native-editor-uv-{uuid4().hex}", mode="edit")
        mesh_native_core.clear_native_mesh_core_fallback_counts()
        try:
            with patch(
                "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                side_effect=AssertionError("uv_transform must use resident native editor session"),
            ):
                result = service.apply_command(
                    view.session_id,
                    MeshEditCommand(
                        "uv_transform",
                        selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}),
                        params={"offset": (0.25, 0.0)},
                    ),
                )
                after_apply = service.working_mesh(view.session_id).submeshes[0].uvs[0]
                undo = service.undo(view.session_id)
                after_undo = service.working_mesh(view.session_id).submeshes[0].uvs[0]
                redo = service.redo(view.session_id)
                after_redo = service.working_mesh(view.session_id).submeshes[0].uvs[0]
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(((0, range(0, 1)),), result.changed_vertices_by_submesh)
        self.assertEqual((0.25, 0.0), after_apply)
        self.assertTrue(undo.ok)
        self.assertEqual((0.0, 0.0), after_undo)
        self.assertTrue(redo.ok)
        self.assertEqual((0.25, 0.0), after_redo)
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_mesh_service_material_assign_copy_uses_resident_native_editor_session_history(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.modding import mesh_native_core
        from cdmw.services.mesh_service import MeshService

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        view = service.open_edit_session(_two_part_mesh(), session_id=f"native-editor-material-{uuid4().hex}", mode="edit")
        mesh_native_core.clear_native_mesh_core_fallback_counts()
        try:
            with patch(
                "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                side_effect=AssertionError("material tools must use resident native editor session"),
            ):
                assigned = service.apply_command(
                    view.session_id,
                    MeshEditCommand(
                        "material_assign",
                        selection=MeshEditSelection.from_maps(source_indices=(0,)),
                        params={
                            "material": "source_authority",
                            "texture": "source.dds",
                            "material_profile": "runtime_xml",
                            "route_status": "ready",
                            "native_material_overrides": {"roughness": 0.2},
                        },
                    ),
                )
                copied = service.apply_command(
                    view.session_id,
                    MeshEditCommand(
                        "material_copy",
                        selection=MeshEditSelection.from_maps(source_indices=(1,)),
                        params={"source_submesh_index": 0},
                    ),
                )
                after_copy = service.working_mesh(view.session_id).submeshes[1]
                after_copy_values = (
                    after_copy.material,
                    after_copy.texture,
                    getattr(after_copy, "cdmw_material_authority_profile"),
                    getattr(after_copy, "cdmw_material_route_status"),
                    getattr(after_copy, "preview_native_material_overrides"),
                )
                undo = service.undo(view.session_id)
                after_undo = service.working_mesh(view.session_id).submeshes[1]
                after_undo_values = (
                    after_undo.material,
                    after_undo.texture,
                    hasattr(after_undo, "cdmw_material_authority_profile"),
                )
                redo = service.redo(view.session_id)
                after_redo = service.working_mesh(view.session_id).submeshes[1]
                after_redo_values = (
                    after_redo.material,
                    getattr(after_redo, "cdmw_material_authority_profile"),
                )
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(assigned.ok)
        self.assertEqual((0,), assigned.affected_submesh_indices)
        self.assertTrue(copied.ok)
        self.assertEqual((1,), copied.affected_submesh_indices)
        self.assertEqual(("source_authority", "source.dds", "runtime_xml", "ready", {"roughness": 0.2}), after_copy_values)
        self.assertTrue(undo.ok)
        self.assertEqual(("mat_b", "b.dds", False), after_undo_values)
        self.assertTrue(redo.ok)
        self.assertEqual(("source_authority", "runtime_xml"), after_redo_values)
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_mesh_service_copy_normals_uses_resident_native_editor_session_history(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.modding import mesh_native_core
        from cdmw.services.mesh_service import MeshService

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id=f"native-editor-copy-normal-{uuid4().hex}", mode="edit")
        service.working_mesh(view.session_id).submeshes[0].normals = [(1.0, 0.0, 0.0)] * 4
        mesh_native_core.clear_native_mesh_core_fallback_counts()
        try:
            with patch(
                "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                side_effect=AssertionError("copy_normals must use resident native editor session"),
            ):
                result = service.apply_command(
                    view.session_id,
                    MeshEditCommand("copy_normals", selection=MeshEditSelection.from_maps(source_indices=(0,))),
                )
                after_apply = tuple(service.working_mesh(view.session_id).submeshes[0].normals)
                undo = service.undo(view.session_id)
                after_undo = tuple(service.working_mesh(view.session_id).submeshes[0].normals)
                redo = service.redo(view.session_id)
                after_redo = tuple(service.working_mesh(view.session_id).submeshes[0].normals)
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(((0, range(0, 4)),), result.changed_vertices_by_submesh)
        self.assertEqual([(0.0, 0.0, 1.0)] * 4, list(after_apply))
        self.assertTrue(undo.ok)
        self.assertEqual([(1.0, 0.0, 0.0)] * 4, list(after_undo))
        self.assertTrue(redo.ok)
        self.assertEqual([(0.0, 0.0, 1.0)] * 4, list(after_redo))
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_mesh_service_flip_normals_uses_resident_native_editor_session_history(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.modding import mesh_native_core
        from cdmw.services.mesh_service import MeshService

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id=f"native-editor-flip-{uuid4().hex}", mode="edit")
        mesh_native_core.clear_native_mesh_core_fallback_counts()
        try:
            with patch(
                "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                side_effect=AssertionError("flip_normals must use resident native editor session"),
            ):
                result = service.apply_command(
                    view.session_id,
                    MeshEditCommand("flip_normals", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})),
                )
                after_apply = tuple(service.working_mesh(view.session_id).submeshes[0].faces)
                undo = service.undo(view.session_id)
                after_undo = tuple(service.working_mesh(view.session_id).submeshes[0].faces)
                redo = service.redo(view.session_id)
                after_redo = tuple(service.working_mesh(view.session_id).submeshes[0].faces)
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertFalse(result.topology_changed)
        self.assertEqual(((0, 2, 1), (1, 3, 2)), after_apply)
        self.assertTrue(undo.ok)
        self.assertFalse(undo.topology_changed)
        self.assertEqual(((0, 1, 2), (1, 3, 2)), after_undo)
        self.assertTrue(redo.ok)
        self.assertFalse(redo.topology_changed)
        self.assertEqual(((0, 2, 1), (1, 3, 2)), after_redo)
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_mesh_service_cleanup_tools_use_resident_native_editor_session_history(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.modding import mesh_native_core
        from cdmw.services.mesh_service import MeshService

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        mesh_native_core.clear_native_mesh_core_fallback_counts()
        try:
            duplicate_view = service.open_edit_session(
                _duplicate_loose_mesh(),
                session_id=f"native-editor-remove-doubles-{uuid4().hex}",
                mode="edit",
            )
            loose_view = service.open_edit_session(
                _loose_vertex_mesh(),
                session_id=f"native-editor-delete-loose-{uuid4().hex}",
                mode="edit",
            )
            with patch(
                "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                side_effect=AssertionError("cleanup tools must use resident native editor session"),
            ):
                removed = service.apply_command(
                    duplicate_view.session_id,
                    MeshEditCommand(
                        "remove_doubles",
                        mode="edit",
                        selection=MeshEditSelection.from_maps(source_indices=(0,)),
                        params={"threshold": 0.001},
                    ),
                )
                self.assertEqual(1.0, removed.metrics["python_apply_deferred"])
                self.assertEqual(1, len(removed.native_preview_triangle_groups))
                self.assertEqual(0, removed.native_preview_triangle_groups[0]["source_submesh_index"])
                self.assertTrue(service._session(duplicate_view.session_id).native_editor_mesh_dirty)
                remove_count = service.working_mesh(duplicate_view.session_id).submeshes[0].vertex_count
                remove_undo = service.undo(duplicate_view.session_id)
                remove_undo_count = service.working_mesh(duplicate_view.session_id).submeshes[0].vertex_count
                remove_redo = service.redo(duplicate_view.session_id)
                remove_redo_count = service.working_mesh(duplicate_view.session_id).submeshes[0].vertex_count

                deleted = service.apply_command(
                    loose_view.session_id,
                    MeshEditCommand(
                        "delete_loose_vertices",
                        mode="edit",
                        selection=MeshEditSelection.from_maps(source_indices=(0,)),
                    ),
                )
                self.assertEqual(1.0, deleted.metrics["python_apply_deferred"])
                self.assertEqual(1, len(deleted.native_preview_triangle_groups))
                self.assertEqual(0, deleted.native_preview_triangle_groups[0]["source_submesh_index"])
                self.assertTrue(service._session(loose_view.session_id).native_editor_mesh_dirty)
                delete_count = service.working_mesh(loose_view.session_id).submeshes[0].vertex_count
                delete_undo = service.undo(loose_view.session_id)
                delete_undo_count = service.working_mesh(loose_view.session_id).submeshes[0].vertex_count
                delete_redo = service.redo(loose_view.session_id)
                delete_redo_count = service.working_mesh(loose_view.session_id).submeshes[0].vertex_count
        finally:
            for session_id in (locals().get("duplicate_view"), locals().get("loose_view")):
                if session_id is not None:
                    service.close_edit_session(session_id.session_id)

        self.assertTrue(removed.ok)
        self.assertEqual((0,), removed.affected_submesh_indices)
        self.assertTrue(removed.topology_changed)
        self.assertEqual(4, remove_count)
        self.assertTrue(remove_undo.ok)
        self.assertEqual(6, remove_undo_count)
        self.assertTrue(remove_redo.ok)
        self.assertEqual(4, remove_redo_count)

        self.assertTrue(deleted.ok)
        self.assertEqual((0,), deleted.affected_submesh_indices)
        self.assertTrue(deleted.topology_changed)
        self.assertEqual(4, delete_count)
        self.assertTrue(delete_undo.ok)
        self.assertEqual(5, delete_undo_count)
        self.assertTrue(delete_redo.ok)
        self.assertEqual(4, delete_redo_count)
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_remaining_topology_tools_defer_python_apply_from_native_counts(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        service = MeshService()
        actions = (
            "delete",
            "dissolve",
            "subdivide",
            "refine_smooth",
            "split",
            "separate",
            "duplicate",
            "mirror",
            "extrude",
            "inset",
            "loop_cut",
            "edge_split",
            "merge",
            "weld",
            "bridge",
            "fill",
            "remove_doubles",
            "delete_loose_vertices",
            "compact_orphans",
            "fix_winding",
            "fill_holes",
            "generate_tangents",
            "uv_transform",
            "material_assign",
            "material_copy",
        )
        action_params = {
            "uv_transform": {"auto_uv": True, "allow_topology_change": True},
            "material_assign": {"material": "mat_b", "texture": "b.dds"},
            "material_copy": {"source_submesh_index": 0},
        }

        def topology_report(
            _session_id: str,
            edit: dict[str, object],
            **_kwargs: object,
        ) -> dict[str, object]:
            action = str(edit.get("operation") or "")
            return {
                "status": "ok",
                "protocol": "mesh-editor-session-json",
                "command": "apply",
                "topology_changed": True,
                "submesh_count": 1,
                "vertex_count": 5,
                "face_count": 4,
                "affected_submesh_indices": [0],
                "submeshes": [{"index": 0, "name": "quad", "material": "mat", "texture": "a.dds", "vertex_count": 5, "face_count": 4}],
                "metrics": {"cpp_ms": 1.0},
                "edit_report": {
                    "operation": action,
                    "submeshes": [
                        {
                            "index": 0,
                            "vertex_count": 5,
                            "face_count": 4,
                            "changed_vertex_start": 4,
                            "changed_vertex_count": 1,
                            "preview_triangle_group": {
                                "preview_backend": "cdmw_mesh_core",
                                "source_submesh_index": 0,
                                "face_count": 4,
                            },
                        }
                    ],
                },
            }

        with (
            patch("cdmw.services.mesh_service.native_mesh_core_available", return_value=True),
            patch("cdmw.services.mesh_service.open_native_mesh_editor_session", return_value={"status": "ok"}),
            patch("cdmw.services.mesh_service.apply_native_mesh_editor_session", side_effect=topology_report),
            patch("cdmw.services.mesh_service.export_native_mesh_editor_session_to_mesh", side_effect=AssertionError("dirty native topology hydrated")),
            patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("legacy geometry dispatcher used")),
        ):
            for action in actions:
                with self.subTest(action=action):
                    view = service.open_edit_session(_quad_mesh(), session_id=f"native-editor-defer-{action}-{uuid4().hex}", mode="edit")
                    result = service.apply_command(
                        view.session_id,
                        MeshEditCommand(
                            action,
                            mode="edit",
                            selection=MeshEditSelection.from_maps(
                                vertices_by_submesh={0: (0, 1, 2)},
                                edges_by_submesh={0: ((0, 1), (2, 3))},
                                faces_by_submesh={0: (0,)},
                                source_indices=(0,),
                            ),
                            params=action_params.get(action, {}),
                        ),
                    )
                    self.assertTrue(result.ok)
                    self.assertTrue(result.topology_changed)
                    self.assertEqual(((0, range(4, 5)),), result.changed_vertices_by_submesh)
                    self.assertEqual(1.0, result.metrics["python_apply_deferred"])
                    self.assertEqual(((5, 4),), result.submesh_counts)
                    self.assertTrue(service._session(view.session_id).native_editor_mesh_dirty)

    def test_real_remaining_topology_tools_emit_native_preview_groups_without_python_apply(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.modding import mesh_native_core
        from cdmw.services.mesh_service import MeshService

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        cases = (
            (
                "split",
                _quad_mesh,
                MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}),
            ),
            (
                "edge_split",
                _quad_mesh,
                MeshEditSelection.from_maps(edges_by_submesh={0: ((1, 2),)}),
            ),
            (
                "bridge",
                _loose_edge_mesh,
                MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (2, 3))}),
            ),
            (
                "fix_winding",
                _reversed_triangle_mesh,
                MeshEditSelection.from_maps(source_indices=(0,)),
            ),
        )

        for action, mesh_factory, selection in cases:
            with self.subTest(action=action):
                service = MeshService()
                mesh_native_core.clear_native_mesh_core_fallback_counts()
                view = service.open_edit_session(
                    mesh_factory(),
                    session_id=f"native-editor-real-topology-{action}-{uuid4().hex}",
                    mode="edit",
                )
                try:
                    with (
                        patch(
                            "cdmw.services.mesh_service.export_native_mesh_editor_session_to_mesh",
                            side_effect=AssertionError(f"{action} should not hydrate Python topology"),
                        ),
                        patch(
                            "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                            side_effect=AssertionError(f"{action} must use resident native editor session"),
                        ),
                    ):
                        result = service.apply_command(
                            view.session_id,
                            MeshEditCommand(action, selection=selection, mode="edit"),
                        )
                finally:
                    service.close_edit_session(view.session_id)

                self.assertTrue(result.ok)
                self.assertTrue(result.topology_changed)
                self.assertEqual(1.0, result.metrics["python_apply_deferred"])
                self.assertTrue(result.submesh_counts)
                self.assertTrue(result.native_preview_triangle_groups)
                self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_native_session_extrude_emits_preview_groups_without_python_apply(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.modding import mesh_native_core
        from cdmw.services.mesh_service import MeshService

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        mesh_native_core.clear_native_mesh_core_fallback_counts()
        view = service.open_edit_session(_quad_mesh(), session_id=f"native-editor-extrude-{uuid4().hex}", mode="edit")
        try:
            with (
                patch(
                    "cdmw.services.mesh_service.export_native_mesh_editor_session_to_mesh",
                    side_effect=AssertionError("extrude should not hydrate Python topology"),
                ),
                patch(
                    "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                    side_effect=AssertionError("extrude must use resident native editor session"),
                ),
            ):
                result = service.apply_command(
                    view.session_id,
                    MeshEditCommand(
                        "extrude",
                        mode="edit",
                        selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                        params={"offset": (0.0, 0.0, 0.25)},
                    ),
                )
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(1.0, result.metrics["python_apply_deferred"])
        self.assertTrue(result.native_preview_triangle_groups)
        self.assertEqual(0, result.native_preview_triangle_groups[0]["source_submesh_index"])
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_native_session_mirror_append_defers_python_apply_from_native_preview_groups(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.modding import mesh_native_core
        from cdmw.services.mesh_service import MeshService

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        service = MeshService()
        mesh_native_core.clear_native_mesh_core_fallback_counts()
        view = service.open_edit_session(_quad_mesh(), session_id=f"native-editor-mirror-{uuid4().hex}", mode="edit")
        try:
            with (
                patch(
                    "cdmw.services.mesh_service.export_native_mesh_editor_session_to_mesh",
                    side_effect=AssertionError("mirror should not hydrate Python topology"),
                ),
                patch(
                    "cdmw.services.mesh_service.apply_mesh_edit_geometry_action",
                    side_effect=AssertionError("mirror must use resident native editor session"),
                ),
            ):
                result = service.apply_command(
                    view.session_id,
                    MeshEditCommand(
                        "mirror",
                        mode="edit",
                        selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                        params={"axis": "x"},
                    ),
                )
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((1,), result.affected_submesh_indices)
        self.assertEqual(1, result.submesh_count_delta)
        self.assertEqual(1.0, result.metrics["python_apply_deferred"])
        self.assertEqual(1, len(result.native_preview_triangle_groups))
        self.assertEqual(1, result.native_preview_triangle_groups[0]["source_submesh_index"])
        self.assertEqual({}, mesh_native_core.native_mesh_core_fallback_counts())

    def test_resident_session_topology_suppresses_remap_report_from_edit_payload(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-topology-report-{uuid4().hex}"
        try:
            open_report = mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0)
            self.assertIsNotNone(open_report)
            select_report = mesh_native_core.select_native_mesh_editor_session(
                session_id,
                {"faces_by_submesh": {0: (0,)}},
                timeout_seconds=5.0,
            )
            self.assertIsNotNone(select_report)
            apply_report = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {"operation": "subdivide", "suppress_vertex_remap_report": True},
                timeout_seconds=10.0,
            )
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(apply_report)
        self.assertTrue(apply_report["topology_changed"])
        item = apply_report["edit_report"]["submeshes"][0]
        self.assertIs(item["vertex_remap_report_suppressed"], True)
        self.assertNotIn("copy_vertex_indices", item)
        self.assertNotIn("copy_vertex_indices_binary", item)
        self.assertNotIn("vertex_blends", item)
        self.assertNotIn("vertex_blend_indices_binary", item)
        self.assertNotIn("index_map", item)
        self.assertNotIn("index_map_binary", item)
        self.assertIn("vertices_binary", item)
        self.assertIn("faces_binary", item)
        self.assertIn("preview_triangle_group", item)

    def test_export_native_editor_session_to_mesh_hydrates_topology_snapshot(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-export-to-mesh-{uuid4().hex}"
        mesh = _quad_mesh()
        try:
            self.assertIsNotNone(mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0))
            self.assertIsNotNone(
                mesh_native_core.select_native_mesh_editor_session(
                    session_id,
                    {"faces_by_submesh": {0: (0,)}},
                    timeout_seconds=5.0,
                )
            )
            self.assertIsNotNone(
                mesh_native_core.apply_native_mesh_editor_session(
                    session_id,
                    {"operation": "subdivide", "suppress_vertex_remap_report": True},
                    timeout_seconds=10.0,
                )
            )
            exported = mesh_native_core.export_native_mesh_editor_session_to_mesh(mesh, session_id, timeout_seconds=10.0)
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertTrue(exported)
        self.assertEqual("quad", mesh.submeshes[0].name)
        self.assertEqual("mat", mesh.submeshes[0].material)
        self.assertEqual("a.dds", mesh.submeshes[0].texture)
        self.assertGreater(len(mesh.submeshes[0].vertices), 4)
        self.assertGreater(len(mesh.submeshes[0].faces), 2)
        self.assertEqual(len(mesh.submeshes[0].vertices), mesh.total_vertices)
        self.assertEqual(len(mesh.submeshes[0].faces), mesh.total_faces)

    def test_open_native_editor_session_reuses_cached_native_submesh_session(self) -> None:
        from cdmw.modding import mesh_native_core

        mesh = _quad_mesh()
        calls: list[tuple[str, object]] = []

        def fake_job(_binary: Path, command: str, payload: object, **_kwargs: object) -> dict[str, object]:
            calls.append((command, payload))
            return {"status": "ok", "submesh_count": 1, "submeshes": [{"index": 0, "vertex_count": 4, "face_count": 2}]}

        mesh_native_core._clear_native_mesh_core_session_cache()
        try:
            with (
                patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
                patch("cdmw.modding.mesh_native_core._run_native_mesh_core_service_job", side_effect=fake_job),
            ):
                cached_id = mesh_native_core._ensure_native_mesh_session_submesh(
                    Path("native.exe"),
                    mesh,
                    0,
                    timeout_seconds=5.0,
                )
                opened = mesh_native_core.open_native_mesh_editor_session(mesh, "editor-from-cache", timeout_seconds=5.0)
        finally:
            mesh_native_core._clear_native_mesh_core_session_cache()

        self.assertTrue(cached_id)
        self.assertIsNotNone(opened)
        self.assertEqual("mesh-session-json", calls[0][0])
        self.assertEqual("mesh-editor-session-json", calls[1][0])
        editor_item = calls[1][1]["submeshes"][0]  # type: ignore[index]
        self.assertEqual(cached_id, editor_item["session_id"])
        self.assertEqual(0, editor_item["index"])
        self.assertNotIn("vertices_binary", editor_item)
        self.assertNotIn("faces_binary", editor_item)

    def test_resident_session_duplicate_append_undo_redo_keeps_native_state(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session_id = f"native-editor-append-{uuid4().hex}"
        try:
            open_report = mesh_native_core.open_native_mesh_editor_session(_quad_mesh(), session_id, timeout_seconds=5.0)
            self.assertIsNotNone(open_report)
            self.assertEqual(1, open_report["submesh_count"])
            self.assertEqual("quad", open_report["submeshes"][0]["name"])
            self.assertEqual("mat", open_report["submeshes"][0]["material"])
            self.assertEqual("a.dds", open_report["submeshes"][0]["texture"])

            snapshot_report = mesh_native_core.export_native_mesh_editor_session_snapshot(session_id, timeout_seconds=5.0)
            self.assertIsNotNone(snapshot_report)
            self.assertEqual("quad", snapshot_report["submeshes"][0]["name"])
            self.assertEqual("mat", snapshot_report["submeshes"][0]["material"])
            self.assertEqual("a.dds", snapshot_report["submeshes"][0]["texture"])

            select_report = mesh_native_core.select_native_mesh_editor_session(
                session_id,
                {"faces_by_submesh": {0: (0,)}},
                timeout_seconds=5.0,
            )
            self.assertIsNotNone(select_report)

            apply_report = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                {"operation": "duplicate"},
                timeout_seconds=10.0,
            )
            undo_report = mesh_native_core.undo_native_mesh_editor_session(session_id, timeout_seconds=10.0)
            redo_report = mesh_native_core.redo_native_mesh_editor_session(session_id, timeout_seconds=10.0)
        finally:
            mesh_native_core.close_native_mesh_editor_session(session_id)

        self.assertIsNotNone(apply_report)
        self.assertIsNotNone(undo_report)
        self.assertIsNotNone(redo_report)
        self.assertEqual([1], apply_report["affected_submesh_indices"])
        self.assertEqual(2, apply_report["submesh_count"])
        self.assertTrue(apply_report["topology_changed"])
        apply_items = apply_report["edit_report"]["submeshes"]
        self.assertEqual(1, len(apply_items))
        self.assertTrue(apply_items[0]["append_submesh"])
        self.assertEqual(1, apply_items[0]["index"])
        self.assertEqual("quad duplicate", apply_items[0]["name"])
        self.assertEqual("mat", apply_items[0]["material"])
        self.assertEqual("a.dds", apply_items[0]["texture"])
        self.assertEqual(1, apply_items[0]["preview_triangle_group"]["source_submesh_index"])

        self.assertEqual([1], undo_report["affected_submesh_indices"])
        self.assertEqual(1, undo_report["submesh_count"])
        self.assertTrue(undo_report["topology_changed"])
        self.assertEqual([], undo_report["edit_report"]["submeshes"])

        redo_items = redo_report["edit_report"]["submeshes"]
        self.assertEqual([1], redo_report["affected_submesh_indices"])
        self.assertEqual(2, redo_report["submesh_count"])
        self.assertTrue(redo_report["topology_changed"])
        self.assertEqual(1, len(redo_items))
        self.assertTrue(redo_items[0]["append_submesh"])
        self.assertEqual(1, redo_items[0]["index"])
        self.assertEqual("quad duplicate", redo_items[0]["name"])
        self.assertEqual("mat", redo_items[0]["material"])
        self.assertEqual("a.dds", redo_items[0]["texture"])
        self.assertEqual(1, redo_items[0]["preview_triangle_group"]["source_submesh_index"])

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
